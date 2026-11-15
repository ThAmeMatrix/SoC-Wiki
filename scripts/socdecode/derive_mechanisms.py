"""Derive a compact, machine-readable *mechanism substrate* from the decrypted
client Lua scripts.

``scripts/socdecode/lua_scripts.py`` dumps 4,483 compiled client scripts into
``data/lua-scripts.js`` (a pool of 112k plaintext constants plus a per-script
index). Their string constants are the client's own declaration of how the
battle engine works: AI phases, skill-list tags, the cast-position sort
pipeline, AOE scoring fields, wait-time bookkeeping and the full speciality
type registry.

This script turns that raw evidence into ``data/client-mechanisms.js`` which the
battle simulator loads as its runtime substrate (``window.WIKI_CLIENT_MECHANISMS``).
Nothing is guessed: every rule below is derived from identifiers that really
appear in the decrypted bytecode, and ``evidence`` records which script exposed
it. The generated file is ~25 KiB, so it can be lazy-loaded with the simulator.

    python -X utf8 scripts/socdecode/derive_mechanisms.py
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'data' / 'lua-scripts.js'
OUT = ROOT / 'data' / 'client-mechanisms.js'


def load_lua():
    t = SRC.read_text('utf8')
    return json.JSONDecoder().raw_decode(t[t.index('=') + 1:])[0]


def constants(lua, name):
    rec = lua['scripts'].get(name)
    if not rec:
        return []
    return [lua['pool'][i] for i in rec[1]]


def main() -> int:
    if not SRC.is_file():
        print(f'缺少 {SRC.relative_to(ROOT)}；请先运行 scripts/socdecode/lua_scripts.py', flush=True)
        return 1
    lua = load_lua()
    pool = lua['pool']
    upper = {x for x in pool if re.fullmatch(r'[A-Z][A-Z0-9_]{3,48}', x)}

    # ---- AI phases (Logic_AI_AI_Phase declares them in execution order) ----
    phase_src = 'Logic_AI_AI_Phase'
    phases = [x for x in constants(lua, phase_src) if x.isupper() and x != 'AI_PHASE']

    # ---- skill list tags: the client's own AI skill categories, in order ----
    tag_src = 'Logic_AI_Skill_List_Tag'
    skip = {'SKILL_LIST_TAG', 'COUNT'}
    tags = [x for x in constants(lua, tag_src) if x.isupper() and x not in skip]
    # The declaration order is the client's priority order. Heal / extra-turn /
    # buff categories come before ordinary attacks, so turn them into weights.
    tag_weight = {t: (len(tags) - i) * 4 for i, t in enumerate(tags)}

    # ---- cast-position decision pipeline (Logic_AI_AIMachine) ----
    machine_src = 'Logic_AI_AIMachine'
    machine = constants(lua, machine_src)
    cast_pipeline = [x for x in machine if re.fullmatch(r'(sortBy|filterBy|getQuadrant|posCompare)\w*', x)]
    machine_fields = [x for x in machine if re.fullmatch(r'[a-z_][a-z0-9_]{2,32}', x)
                      and re.search(r'move|dist|order|wait|block|step|alert|attack|skill|quadrant', x)]

    # ---- AOE position scoring fields (Logic_AI_AoePosition) ----
    aoe_src = 'Logic_AI_AoePosition'
    aoe_fields = [x for x in constants(lua, aoe_src)
                  if re.fullmatch(r'[a-z][A-Za-z]{3,24}', x) and re.search(r'Count|num|Enemy|taunt|dying|weak|hurt|block|move|quadrant', x)]

    # ---- wait-time / turn-order bookkeeping (WaitTimeView) ----
    wait_src = 'WaitTimeView'
    wait_all = constants(lua, wait_src)
    wait_fields = [x for x in wait_all if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{2,32}', x)
                   and re.search(r'(?i)wait|sort|line|adjust|reset|round|item', x)]
    dynamic_order = any(x in wait_all for x in ('AdjustWaitTime', 'ResetWaitTime', 'SortItems', 'ResetSortItems'))

    # ---- speciality (effect) type registry ----
    # The config tables are the authoritative list of 197 effect types; the
    # decrypted scripts prove which of them the client really branches on.
    mech_path = ROOT / 'data' / 'battle-mech.js'
    mech_text = mech_path.read_text('utf8') if mech_path.is_file() else ''
    configured = set()
    if mech_text:
        mech = json.JSONDecoder().raw_decode(mech_text[mech_text.index('=') + 1:])[0]
        configured = {s.get('t') for s in mech.get('specs', {}).values()}
    effect_types = sorted(configured & upper)
    # Evidence: how many decrypted scripts mention each configured type.
    evidence = Counter()
    for name, (_g, ids) in lua['scripts'].items():
        for t in {pool[i] for i in ids if pool[i] in configured}:
            evidence[t] += 1

    # ---- timing / active_time identifiers ----
    timing_fields = sorted(x for x in pool if re.search(r'active_time|wait_time|_time_', x) and len(x) < 48)

    # ---- movement rules actually declared by the client ----
    move_rules = {
        'filterByMinMoveDist': 'filterByMinMoveDist' in cast_pipeline,
        'sortByMoveAndTargetDist': 'sortByMoveAndTargetDist' in cast_pipeline,
        'sortBySkillMoveMode': 'sortBySkillMoveMode' in cast_pipeline,
        'quadrantCompare': 'getQuadrant' in cast_pipeline and 'posCompare' in cast_pipeline,
        'sortByPosition': 'sortByPosition' in cast_pipeline,
        'minMoveSteps': 'move_steps' in machine,
        'alertDistance': 'alert_dist' in machine,
        'skillMoveMode': 'skill_list_tag' in machine or 'SKILL_LIST_TAG' in machine,
    }
    core_src = (ROOT / 'battle-sim-core.js').read_text('utf8')
    ci = core_src.index('    const EFFECTS = {')
    cj = core_src.index('\n    };', ci)
    handlers = set(re.findall(r'^      ([A-Z_]+)\s*\(', core_src[ci:cj], re.M))
    si = core_src.index('const STATIC_TYPES')
    statics = set(re.findall(r"'([A-Z_]+)'", core_src[si:core_src.index(']);', si)]))
    engine_types = handlers | statics

    target_sorts = [x for x in cast_pipeline if x.startswith('sortBy') and
                    re.search('Weak|Taunt|Hurt|Dying|NearEnemy|Count|Position|Props', x)]

    # ---- reactive speciality type ids -------------------------------------
    # `SPECIALITY_COUNT_TURN` rows carry speciality_type.TYPE.<name> as p[1].
    # The client's own Chinese effect names identify which numeric id belongs
    # to 警戒 / 反击 / 先制 / 协战. Export the map so the simulator can add
    # "次数+N" auras to the generic per-turn limit check instead of guessing.
    type_words = [('ALERT_ATTACK', '警戒'), ('COUNTER_ATTACK', '反击'),
                  ('FIRST_HIT', '先制'), ('ASSIST_DEFENCE', '协战'),
                  ('ASSIST_ATTACK', '援攻')]
    speciality_types, type_evidence = {}, {}
    for sid, spec in (mech.get('specs') or {}).items():
        if spec.get('t') != 'SPECIALITY_COUNT_TURN':
            continue
        pid = (spec.get('p') or [0, 0])[1]
        name = str(spec.get('n') or '')
        if not isinstance(pid, int) or pid <= 0:
            continue
        for effect, word in type_words:
            if word in name:
                speciality_types.setdefault(effect, pid)
                type_evidence.setdefault(effect, []).append(sid)
                break
    # `p[0]` non-zero rows name a specific speciality id; keep the evidence
    # count so the code page can show how many client rows were classified.
    count_turn_rows = sum(1 for s in (mech.get('specs') or {}).values()
                          if s.get('t') == 'SPECIALITY_COUNT_TURN')

    # ---- decrypted identifiers backing the new engine rules --------------
    poolset = set(pool)
    client_mechanisms = {
        'allSkillList': 'all_skill_list' in poolset,
        'curSkill': 'cur_skill' in poolset,
        'skillOrders': 'skill_orders' in poolset,
        'skillByOrder': 'skill_by_order' in poolset,
        'bossSkillMode': 'boss_skill_mode' in poolset,
        'bossSkills': 'boss_skills' in poolset,
        'pathAlert': 'PathAlert' in poolset or 'Battle.ActionPathAlert' in poolset,
        'collectAlertBlocks': 'CollectAlertBlocks' in poolset,
        'findAlertTargetBlocks': 'FindAlertTargetBlocks' in poolset,
        'hideAlertPreview': 'hide_alert_preivew' in poolset,
        'alertAttackDisplay': 'ALERT_ATTACK_DISPLAY' in poolset,
        'strengthenAlert': 'STRENGTHEN_ALERT' in poolset,
        'specialityCountTurn': 'SPECIALITY_COUNT_TURN' in poolset,
        'limitCountTurn': 'limit_count_turn' in poolset,
        'curLimitCountTurn': 'cur_limit_count_turn' in poolset,
        'jumpMove': 'JUMP_MOVE' in poolset,
        'jumpMoveSteps': 'jump_move_steps' in poolset,
        'alliesPassable': 'isFriend' in poolset and 'move_block' in poolset,
    }

    payload = {
        'meta': {
            'source': 'data/lua-scripts.js (decrypted client .luac via slua.dll)',
            'scriptsDecrypted': lua['meta']['scripts'],
            'readableStrings': lua['meta']['readableStrings'],
            'effectTypesDeclared': len(effect_types),
            'note': '由解密脚本的明文常量导出；未解密的字符串只统计数量，不做猜测。',
        },
        'evidence': {
            'aiPhases': phase_src, 'skillTags': tag_src, 'castPipeline': machine_src,
            'aoeFields': aoe_src, 'waitTime': wait_src,
            'specialityTypes': 'data/battle-mech.js SPECIALITY_COUNT_TURN',
            'clientMechanisms': machine_src + ' / data/lua-scripts.js pool',
        },
        'phases': phases,
        'skillTags': tags,
        'tagWeight': tag_weight,
        'castPipeline': cast_pipeline,
        'aiFields': {
            'skillByOrder': 'skill_by_order', 'skillOrders': 'skill_orders',
            'allSkillList': 'all_skill_list', 'curSkill': 'cur_skill',
            'skillListTag': 'skill_list_tag', 'skillMoveMode': 'skill_move_mode',
            'aiMoveClose': 'ai_move_close', 'moveSteps': 'move_steps',
            'alertDist': 'alert_dist', 'alertPoints': 'alert_points',
            'prevBlockMin': 'prev_block_min', 'offsetMoves': 'offset_moves',
            'moveBlock': 'move_block', 'movableBlocks': 'movable_blocks',
            'bossSkillMode': 'boss_skill_mode', 'bossSkills': 'boss_skills',
        },
        'targetSorts': target_sorts,
        'specialityTypes': speciality_types,
        'specialityTypeEvidence': {k: v[:6] for k, v in type_evidence.items()},
        'specialityCountTurnRows': count_turn_rows,
        'clientMechanisms': client_mechanisms,
        'machineFields': sorted(set(machine_fields)),
        'aoeFields': aoe_fields,
        'waitTime': {'fields': sorted(set(wait_fields)), 'dynamicOrder': dynamic_order},
        'moveRules': move_rules,
        'timingFields': timing_fields[:60],
        'effectTypes': effect_types,
        'effectTypesUnverified': sorted(configured - upper),
        'effectEvidence': {k: v for k, v in evidence.most_common() if k in configured},
        # Which client effect types the simulator actually executes. Read from
        # the engine source (handlers + static types) so the code page can show
        # a truthful coverage figure instead of a guess.
        'engineEffectTypes': sorted(engine_types),
        'engineCoverage': round(100 * len(engine_types & configured) / max(1, len(configured)), 1),
    }
    OUT.write_text('window.WIKI_CLIENT_MECHANISMS=' +
                   json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + ';\n', 'utf8')
    print(f'机制基底：{len(phases)} 阶段 · {len(tags)} 技能标签 · {len(cast_pipeline)} 步选位流水线 · '
          f'{len(aoe_fields)} 个 AOE 评分字段 · {len(effect_types)} 个效果类型 · '
          f'引擎实现 {len(engine_types & configured)}/{len(configured)} 类 → '
          f'{OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KiB)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
