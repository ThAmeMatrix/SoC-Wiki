"""Export the client battle mechanics the offline simulator executes.

The battle rules live in plain client config tables:

  skill                 ranges, targeting, damage type / factors, TP, cooldown,
                        speciality_ids (the effects a skill carries)
  speciality(_type)     32k effect instances of 257 typed effects with their
                        parameters, trigger timing (active_time), target side,
                        per-turn limits and Lua activation conditions
  buff (+category)      timed states: speciality_ids, buff / debuff kind,
                        effect type, dispel / immune flags, stacking rules
  aoe_param / range_select   area shapes used by AOE specialities
  attribute_type, abnormal_state, buff_effect_type, damage_type
  hp_attenuation        受伤 / 濒死 thresholds and their specialities
  profession_restrain   class restraint → speciality
  weather               battle weather aura specialities
  const_param           crit / restraint / knockback / fall constants
  battle_guidebook_part the client's own battle-rule handbook (战斗手册)

Starting from every skill a playable character or 乐土群星杯 fighter carries
(data/battle-sim.js and data/match-cup.js kits), the cup's mission buffs and
unit statuses, weather auras, injury thresholds and restraint, this walks
skill → speciality → referenced skills / buffs → speciality … and writes only
that closure to data/battle-mech.js (window.WIKI_BATTLE_MECH).

    python -X utf8 scripts/extract_battle_mechanics.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from skill_mechanics import derive_plans
from extract_battle_sim import (table, plain, ints, load_js, area_of, TARGET_ENEMY, TARGET_ALLY,
                                TARGET_GROUND, TARGET_SELF, TARGET_DIRECTION)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data' / 'battle-mech.js'

# Trigger timings come straight from the client enum table `active_time`
# (1 ANY 任意, 2 ATTACK 攻击前, 3 ATTACKED 攻击后, 4 BEATTACKED 被攻击后 …
# 65 BUFFREMOVED). The engine lists which of them it raises in ENGINE_TIMINGS.
# 62/63 = 被非贯穿攻击前/后 (defender side, gated by the client `Break` tag),
# 64 = 触发陷阱时 (raised by triggerObject when a PLACE_TRAP is crossed).
ENGINE_TIMINGS = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26,
                  27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49,
                  50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65}


def _n(v, d=0):
    try:
        return int(float(str(v if v not in (None, '') else d)))
    except (TypeError, ValueError):
        return d


def clean(text):
    s = re.sub(r'<sprite[^>]*name="([^"]+)"[^>]*>', lambda m: '·' + m.group(1).upper(), str(text or ''))
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]*>', '', s)).strip()


def main():
    cfg = ROOT / 'output' / 'archive' / 'library' / '当前版本' / '配置表'
    if not cfg.is_dir():
        print('跳过战斗机制数据：缺少本地客户端配置表（先完成一次「本地更新」）。')
        return 0
    sim = load_js('battle-sim.js', 'WIKI_BATTLE_SIM')
    try:
        cup = load_js('match-cup.js', 'WIKI_MATCH_CUP')
    except (OSError, ValueError):
        cup = {'teams': [], 'schedules': []}

    skills = {r['id']: r for r in table('skill')}
    specs = {r['id']: r for r in table('speciality')}
    stype = {r['id']: r for r in table('speciality_type')}
    buffs = {r['id']: r for r in table('buff')}
    bcat = {r['id']: r for r in table('buff_category')}
    aoe = {r['id']: r for r in table('aoe_param')}
    rsel = {r['id']: r.get('type') for r in table('range_select')}
    tags = {r['id']: r.get('type') or '' for r in table('skill_tag')}
    # skill_tag.name carries the CLIENT'S OWN Chinese labels (物理 / 魔法 /
    # 范围伤害 / 援攻 / 警戒 / 普攻 …). The engine needs `type` (English enum)
    # for its mechanics checks, but the replay UI must show `name` — exporting
    # only `type` left every skill labelled with internal English identifiers.
    tag_names = {r['id']: r.get('name') or '' for r in table('skill_tag')}
    tag_show = {r['id']: bool(r.get('is_show')) for r in table('skill_tag')}
    dt_names = {r['id']: r.get('name') or '' for r in table('damage_type')}
    attrs = {r['id']: r.get('type') for r in table('attribute_type')}
    abnormal = {r['id']: r.get('type') for r in table('abnormal_state')}
    effect_types = {r['id']: r.get('type') for r in table('buff_effect_type')}
    middle = {r['id']: r.get('type') for r in table('buff_middle_type')}
    sub = {r['id']: r.get('type') for r in table('buff_sub_type')}
    mutex = {r['id']: r.get('type') for r in table('buff_mutex_type')}
    weathers = {r['id']: r for r in table('weather')}
    active_time = {r['id']: (r.get('type') or '', clean(r.get('name'))) for r in table('active_time')}
    unit_tags = {r['id']: clean(r.get('name')) for r in table('unit_tag')}
    # Client `field_status` declares 30 terrain overlays: extra movement
    # cost, the specialities applied to a unit that passes / stops on the
    # tile, coverage priority and which OPERATION ids may not overwrite it.
    # Only the id→type enum used to be exported, so the engine could never
    # apply 「燃烧 / 冰冻 / 沼泽」 terrain rules.
    field_rows = table('field_status')
    # Client `buff_group` declares the attribute-buff TIERS: 「1级增益」→
    # 「二级属性增益」→「3级增益」. A higher tier must REPLACE a lower one of
    # the same buff_category (攻击3 #81 replaces 攻击2 #53 immediately), while
    # a lower tier must never overwrite a higher one. Without this the engine
    # only saw `CategoryMutex` and let an aura re-apply 攻击2 every frame,
    # instantly wiping the 攻击3 granted by 烟幕游击.
    tier_word = {'1': 1, '一': 1, '2': 2, '二': 2, '3': 3, '三': 3,
                 '4': 4, '四': 4, '5': 5, '五': 5}
    buff_tiers = {}
    for row in table('buff_group'):
        name = clean(row.get('name')) or ''
        m = re.search(r'([一二三四五12345])\s*级', name)
        tier = tier_word.get(m.group(1)) if m else 0
        if not tier:
            continue
        for bid in ints(row.get('buff_ids')):
            buff_tiers[bid] = max(buff_tiers.get(bid, 0), tier)
    # speciality.OPERATION.param0 is an `operation.id`, NOT a field_status.id.
    # operation.field_status is the resulting terrain: op 18「释放烟雾」→
    # field 14「烟雾」, op 10「冰冻」→ field 3「冰冻」. The engine needs this
    # map or every OPERATION would apply the wrong terrain rules.
    operation_map = {r['id']: {'name': clean(r.get('name')), 'type': r.get('type') or '',
                               'field': _n(r.get('field_status'))}
                     for r in table('operation')}
    field_defs = {r['id']: {
        'name': clean(r.get('name')), 'type': r.get('type') or '',
        'desc': clean(r.get('desc'))[:180], 'mobility': _n(r.get('mobility')),
        'exitMobility': _n(r.get('exit_mobility')), 'showMobility': _n(r.get('show_mobility')),
        'priority': _n(r.get('priority')), 'irreplaceable': bool(r.get('irreplaceable')),
        'forbid': ints(r.get('forbid_operation_ids')),
        'sp': [x for x in ints(r.get('speciality_ids')) if x in specs]}
        for r in field_rows}
    # Interactive objects: props (雪人/雪球…), trap (蜜果/碎冰…) and widget
    # (落石/开关…). Their speciality_ids / trigger_skill / melee_skill drive
    # placement, pick-up triggers, destruction and death effects in battle.
    props = {r['id']: r for r in table('props')}
    traps = {r['id']: r for r in table('trap')}
    widgets = {r['id']: r for r in table('widget')}
    trap_trigger = {r['id']: r.get('type') or '' for r in table('trap_trigger_type')}
    widget_trigger = {r['id']: r.get('type') or '' for r in table('widget_trigger_type')}
    widget_type = {r['id']: r.get('type') or '' for r in table('widget_type')}

    # ---- seeds ----
    seed_skills, seed_buffs, seed_specs = set(), set(), set()
    # Object-owned effects are not reachable from any fighter kit, so seed them
    # explicitly: every prop speciality, every trap trigger/destroy skill, and
    # every widget melee skill.
    for r in props.values():
        seed_specs.update(ints(r.get('speciality_ids')))
    for r in traps.values():
        for k in ('trigger_skill', 'destroy_skill'):
            if r.get(k):
                seed_skills.add(r[k])
    for r in widgets.values():
        for k in ('melee_skill', 'destroy_skill'):
            if r.get(k):
                seed_skills.add(r[k])
    # Summoned units (PLACE_UNIT p[0] = unit_npc id) are real fighters with
    # their own skills. Their kits are not reachable from any playable / cup
    # kit, so seed those skill rows into the closure explicitly.
    # Every client personality skill is a live battle passive (not only the
    # ones belonging to a PLACE_UNIT summon). Seeding them explicitly keeps
    # the closure complete and data-driven; an earlier version accidentally
    # reached the same set through a bogus 0==0 column match, which also
    # dropped the REAL personality links for summons.
    personality_rows = table('unit_personality_skill')
    for row in personality_rows:
        sid = _n(row.get('skill_id') or row.get('idskill'))
        if sid:
            seed_skills.add(sid)
    npc_by_id = {r['id']: r for r in table('unit_npc')}
    summon_npc_ids = set()
    for row in specs.values():
        if stype.get(row.get('type'), {}).get('type') != 'PLACE_UNIT':
            continue
        nid = _n(row.get('param0'))
        if nid > 100 and nid in npc_by_id:
            summon_npc_ids.add(nid)
    for nid in summon_npc_ids:
        n = npc_by_id[nid]
        for k in ('melee_skill', 'reactive_skill', 'leader_skill'):
            if _n(n.get(k)):
                seed_skills.add(_n(n.get(k)))
        seed_skills.update(ints(n.get('skill_ids')))
        # `unit_personality_skill` keys the group with `idunit_personality`,
        # NOT `personality_id` / `idpersonality`. Using the wrong column made
        # EVERY summon lose its personality (e.g. 虚空投影 personality 1312
        # → skill 21731「虚空造物」with [失焦] / [不屈] / 无法移动).
        for row in personality_rows:
            if _n(row.get('idunit_personality') or row.get('personality_id')) == _n(n.get('personality_id')):
                if _n(row.get('skill_id') or row.get('idskill')):
                    seed_skills.add(_n(row.get('skill_id') or row.get('idskill')))


    def kit_ids(kit):
        out = [kit.get('basic')]
        for k in ('actives', 'initial', 'reactive', 'leader', 'feature', 'personality', 'chain',
                  'bossSequence', 'choice', 'derived', 'eliteComp', 'module'):
            out += list(kit.get(k) or [])
        out += [r[2] for r in kit.get('ranks') or []]
        return [s for s in out if s]

    for r in sim.get('roster', []):
        seed_skills.update(kit_ids(r.get('kit') or {}))
    for t in cup.get('teams', []):
        for m in t.get('members', []):
            seed_skills.update(kit_ids(m.get('kit') or {}))
    for s in cup.get('schedules', []):
        seed_buffs.update(b['buffId'] for b in s.get('buffDetails', []) if b.get('buffId'))
        seed_buffs.update(u['buffId'] for u in s.get('unitStatus', []) if u.get('buffId'))
    hp_att = []
    for r in table('hp_attenuation'):
        ids = ints(r.get('speciality_ids'))
        seed_specs.update(ids)
        hp_att.append({'type': r.get('type'), 'name': r.get('name'), 'min': r.get('hp_min'), 'max': r.get('hp_max'),
                       'sp': ids})
    restrain = []
    for r in table('profession_restrain'):
        ids = ints(r.get('speciality_ids'))
        seed_specs.update(ids)
        restrain.append({'from': r['idprofession_category'], 'to': r['profession_category_target'],
                         'evaluate': r.get('evaluate'), 'sp': ids})
    weather_out = {}
    for w in weathers.values():
        if w.get('aura_speciality'):
            seed_specs.add(w['aura_speciality'])
        weather_out[w['id']] = {'name': clean(w.get('name')), 'desc': clean(w.get('desc'))[:120],
                                'aura': w.get('aura_speciality') or 0}
    # Terrain specialities are owned by the TILE, not by any fighter kit, so
    # the skill→speciality closure never reached them (0 of 51 exported).
    # Seed all of them explicitly: BUFF (灼烧 / 疲劳 / 圣痕), AURA (香料闪避),
    # CAST_SKILL (粉尘爆炸), NO_KNOCKBACK_DISTANCE (冰面滑退) …
    for f in field_defs.values():
        seed_specs.update(f['sp'])

    # ---- closure ----
    keep_skills, keep_specs, keep_buffs = set(), set(), set()
    todo_sk, todo_sp, todo_bf = list(seed_skills), list(seed_specs), list(seed_buffs)

    def spec_refs(r):
        st = stype.get(r['type'], {})
        sk_refs, bf_refs = [], []
        # CAST_SKILL / MAKE_OTHER_CAST_SKILL put the linked skill in param0
        # without a 技能 param name; follow the reference explicitly.
        if st.get('type') in ('CAST_SKILL', 'MAKE_OTHER_CAST_SKILL', 'DELAY_CAST_SKILL',
                              'FORCE_CAST_SKILL', 'CONDITION_SKILL', 'ACTIVATION'):
            if isinstance(r.get('param0'), int) and r['param0'] in skills:
                sk_refs.append(r['param0'])
        for i in range(4):
            name = str(st.get(f'param{i}_name') or '')
            v = r.get(f'param{i}')
            if not v:
                continue
            if '技能' in name and isinstance(v, int) and v in skills:
                sk_refs.append(v)
            if 'BUFF' in name.upper() and isinstance(v, int) and v in buffs:
                bf_refs.append(v)
        if st.get('type') == 'BUFF' and r.get('sparam'):
            bf_refs += [x for x in ints(r['sparam']) if x in buffs]
        if st.get('type') in ('REPLACE_SKILL',):
            sk_refs += [x for x in (r.get('param0'), r.get('param1')) if x in skills]
        return sk_refs, bf_refs

    while todo_sk or todo_sp or todo_bf:
        while todo_sk:
            sid = todo_sk.pop()
            if sid in keep_skills or sid not in skills:
                continue
            keep_skills.add(sid)
            row = skills[sid]
            todo_sp += ints(row.get('speciality_ids'))
            for k in ('skill_attached_passive_id', 'idskill_follow', 'skill_cast_id', 'overwritten_skill_id'):
                if row.get(k) in skills:
                    todo_sk.append(row[k])
        while todo_sp:
            pid = todo_sp.pop()
            if pid in keep_specs or pid not in specs:
                continue
            keep_specs.add(pid)
            a, b = spec_refs(specs[pid])
            todo_sk += a
            todo_bf += b
        while todo_bf:
            bid = todo_bf.pop()
            if bid in keep_buffs or bid not in buffs:
                continue
            keep_buffs.add(bid)
            todo_sp += ints(buffs[bid].get('speciality_ids'))

    # ---- records ----
    def aim_of(tm):
        return ('enemy' if tm in TARGET_ENEMY else 'ally' if tm in TARGET_ALLY else
                'self' if tm in TARGET_SELF else 'direction' if tm in TARGET_DIRECTION else
                'ground' if tm in TARGET_GROUND else 'other')

    used_aoe = set()
    out_skills = {}
    for sid in sorted(keep_skills):
        r = skills[sid]
        desc = plain(r.get('desc'))
        sp_ids = [x for x in ints(r.get('speciality_ids')) if x in specs]
        # The client defines every multi-target area through an AOE speciality
        # (aoe_param). Guessing from description text ("…7 格内最近的敌人")
        # turned single-target skills into huge areas, so default to single.
        area = {'type': 'single'}
        for x in sp_ids:
            if stype.get(specs[x]['type'], {}).get('type') == 'AOE' and specs[x].get('param0') in aoe:
                a = aoe[specs[x]['param0']]
                used_aoe.add(a['id'])
                area = {'type': 'aoe', 'id': a['id']}
                break
        out_skills[sid] = {
            # Hidden passives have no display name; fall back to the editor label.
            'n': clean(r.get('name')) or clean(r.get('editor_name'))[:24] or f'技能 {sid}',
            'st': r.get('skill_type'), 'ty': r.get('type'),
            'ap': str(r.get('active_param') or '').strip(),
            'ct': r.get('class_type'), 'tp': r.get('tp') or 0, 'cd': r.get('cooldown') or 0,
            'pcd': r.get('pre_cooldown') or 0, 'rmin': r.get('range_min') or 0, 'rmax': r.get('range_max') or 0,
            'rt': r.get('range_tag') or 0, 'srt': r.get('shot_range_tag') or 0,
            'rw': r.get('range_width') or 0, 'tm': r.get('target_method') or 0,
            # `skill_attached_passive_id` points at a hidden passive SKILL
            # whose specialities are active while this skill is equipped.
            # 123 client skills use it (e.g. 伊凡「冰雪暴」20768 → 20777).
            'ap2': r.get('skill_attached_passive_id') or 0,
            # `skill_range_constant` marks skills whose range must NOT be
            # modified by SKILL_RANGE / environment buffs.
            'rc': bool(r.get('skill_range_constant')),
            'ts': r.get('target_select') or 0, 'ttp': r.get('target_type') or 0, 'tw': r.get('target_width') or 0,
            'hm': r.get('hit_method') or 0, 'am': r.get('attack_method') or 0, 'dt': r.get('damage_type') or 0,
            'pf': r.get('physic_factor') or 0, 'sf': r.get('spell_factor') or 0, 'df': r.get('damage_factor') or 0,
            'dmg': r.get('damage') or 0, 'dp': r.get('damage_percent') or 0, 'cc': r.get('crit_chance') or 0,
            'di': r.get('defence_ignore') or 0, 'up': r.get('attack_up') or 0, 'dn': r.get('attack_down') or 0,
            'fl': r.get('idskill_follow') if r.get('idskill_follow') in skills else 0,
            # Client `skill_cast_id`: the skill that ACTUALLY resolves when
            # this one is cast (1079 rows). 麦莎·SP「全装甲集火号令！」15934
            # → 15968「飞弹礼花Clone」carries the real damage factor and the
            # CAST_SKILL chain that broadcasts 协同响应. `overwritten_skill_id`
            # (61 rows) is the client's alternative "技能变更为" declaration.
            'scid': r.get('skill_cast_id') if r.get('skill_cast_id') in skills else 0,
            'ovid': r.get('overwritten_skill_id') if r.get('overwritten_skill_id') in skills else 0,
            'sp': sp_ids, 'tags': [tags[x] for x in ints(r.get('skill_tag_ids')) if tags.get(x)],
            # Chinese display labels + the client's is_show flag, in the same
            # order as `tags`, so the UI never has to guess a translation.
            'tn': [tag_names[x] for x in ints(r.get('skill_tag_ids')) if tag_names.get(x)],
            'tshow': [tag_show[x] for x in ints(r.get('skill_tag_ids')) if tag_names.get(x)],
            'ord': r.get('ai_skill_order') or 0,
            # Client AI hints (decrypted from the local Lua VM constant index):
            # ai_move_close / ai_order_param / target_order_param steer the
            # approach and skill priority in the client's own AI scripts.
            # Full Lua text (AI scripts can be >120 chars); the engine
            # evaluates them with its own Lua VM instead of guessing.
            'amc': str(r.get('ai_move_close') or '').strip(),
            'aop': str(r.get('ai_order_param') or '').strip(),
            'top': str(r.get('target_order_param') or '').strip(),
            # Client target legality (387 skills): `cast_param` is a Lua
            # predicate on the chosen target — 游击「return target.template.id
            # == 139 and owner:isFriend(target)」(only a friendly 枪影),
            # 「return not target:getBuffCount(N, 1)」, 「target:IsUnit(N)」.
            # `target_param` (638 skills) filters which entities inside the
            # area are affected. Neither was exported, so the engine let
            # skills land on blocks / units the client refuses.
            'cp': str(r.get('cast_param') or '').strip(),
            'tgp': str(r.get('target_param') or '').strip(),
            'hap': bool(r.get('hide_alert_preivew')),
            # `skill_category` groups skills for SKILL_COUNT specialities:
            # 「[安缇歌]-放置晶石雷区使用次数+1」p=[0,28,1,0] targets ALL
            # carried skills whose category is 28, not a single skill id.
            'cat': r.get('category') or 0,
            'lc': r.get('limit_count') or 0,
            'lct': r.get('limit_count_turn') or 0, 'aim': aim_of(r.get('target_method')),
            'area': area, 'desc': desc[:120],
            # 「在目标[空地]召唤 / 放置」— the client forbids casting these on
            # a tile already occupied by a unit or an interactive object.
            # 菲娜塔「召唤·虚空投影」21721 is the reported case: it used to
            # summon straight onto 灵感星核's tile.
            'eg': bool(re.search(r'\[空地\]', desc) and re.search(r'召唤|放置|制造|投掷|冰墙|投影', desc)),
            # Description-declared mechanics (「技能变更为：[X]」, 〈阵营〉额外
            # 协同响应) can sit past char 120. Keep the full text ONLY for those
            # skills so skill_mechanics.py can decode them without bloating the
            # 8 MB data file for the other ~7500 rows.
            **({'descFull': desc} if ('技能变更为' in desc or '协同响应' in desc or
                                      '变为[' in desc or '变为【' in desc or
                                      '变更为[' in desc or '变更为【' in desc) else {}),
        }
    type_names = {}
    out_specs = {}
    dynamic_count = 0
    # The client stores SPEED modifiers as WAIT-TIME deltas: 「速度+50」is
    # param1=-50, 「速度降低I」is +50. The game shows and applies them as a
    # normal speed bonus, so convert the sign here — once, at the data layer —
    # and let the engine, the turn order and the panel all see plain speed.
    SPEED_FLAT = {'MODIFY_ATTRIBUTE', 'PREWAR_MODIFY_ATTRIBUTE', 'PREWAR_MODIFY_BASE_ATTRIBUTE'}
    converted = 0
    for pid in sorted(keep_specs):
        r = specs[pid]
        t = stype.get(r['type'], {}).get('type') or f'T{r["type"]}'
        type_names[r['type']] = t
        pp = [_n(r.get('param0')), _n(r.get('param1')), _n(r.get('param2')), _n(r.get('param3'))]
        if t in SPEED_FLAT and attrs.get(pp[0]) == 'SPEED':
            pp[1], pp[2] = -pp[1], -pp[2]
            converted += 1
        elif t == 'CONVERT_ATTRIBUTE' and attrs.get(pp[1]) == 'SPEED':
            pp[2] = -pp[2]
            converted += 1
        rec = {'t': t, 'at': r.get('active_time') or 0,
               'p': pp,
               'n': clean(r.get('editor_name') or r.get('name'))[:46], 'tt': r.get('target_type') or 0}
        # `speciality_type.priority` orders specialities that share the SAME
        # active_time: SPECIFY_ATTRIBUTE_VALUE 100 → DISPEL/REMOVE 1 → normal 0
        # → CONVERT_ATTRIBUTE -1. Without it 命途所至's DISPEL (驱散2个减益)
        # ran AFTER its BUFF (施加[▼速度4]) and removed the debuff the same
        # skill had just applied, so 减少200速度 never took effect.
        pr = _n(stype.get(r['type'], {}).get('priority'))
        if pr:
            rec['pr'] = pr
        if r.get('sparam'):
            raw_s = str(r['sparam']).strip()
            rec['s'] = raw_s[:400]
            # 494 client rows carry a JSON `sparam` (compound parameters):
            # {"force_cast":true}, {"buff_category":[24]}, {"cast_limit":1,
            # "total_limit":2} … The engine used to see only the raw string
            # and never parse it, so e.g. 叶迦内's DISPEL #22116 declared
            # "only remove category-24 无法治疗 buffs" but removed 627
            # unrelated buffs. Export the parsed object as `sj` too, keeping
            # `s` for the existing text-based checks. Two rows use typographic
            # quotes (“…”) — normalise those before parsing.
            if raw_s.startswith('{'):
                try:
                    obj = json.loads(raw_s.replace('\u201c', '"').replace('\u201d', '"'))
                    if isinstance(obj, dict) and obj:
                        rec['sj'] = obj
                except (ValueError, TypeError):
                    pass
        if r.get('active_param'):
            # Full Lua source: truncating would leave the condition unparsable.
            rec['c'] = str(r['active_param']).strip()
        if r.get('skill_active_param'):
            # `skill_active_param` is a SECOND, skill-scoped condition: the
            # speciality only applies to skills matching this Lua predicate.
            # 227 client specialities use it, 81 of them SKILL_RANGE (e.g.
            # #5210「远程技能射程+2」→ skill:isRangeTag(RANGED)). Without it
            # 近战 and teleport skills wrongly gained +2 range.
            rec['sap'] = str(r['skill_active_param']).strip()
        if r.get('dynamic_param'):
            # Full Lua source, same reason. This is how hundreds of "hidden in
            # the tooltip" effects express e.g. 「每层渴血战斧 +10% 物攻」.
            rec['dp'] = str(r['dynamic_param']).strip()
        if r.get('target_to_caster'):
            rec['tc'] = 1
        for k, src in (('lt', 'limit_count_turn'), ('lc', 'limit_count'), ('d', 'duration'), ('sc', 'stack_count')):
            if r.get(src):
                rec[k] = r[src]
        # Three further client limit scopes, all declared on the SPECIALITY
        # row (distinct from limit_count / limit_count_turn which are scoped
        # to the OWNER only). Without them a multi-hit / chain skill could
        # fire the same row 9 times inside ONE command:
        #   limit_count_command            = per (owner, action, spec)
        #   limit_count_per_entity_command = per (owner, action, spec, target)
        #   limit_count_per_entity_turn    = per (owner, round, spec, target)
        # 「苍穹华光-对自己施加3个增益」#31415 declares command=1 but was
        # resolved once per chain segment. Export them so limitOk() can gate.
        for k, src in (('lcc', 'limit_count_command'),
                       ('lcpec', 'limit_count_per_entity_command'),
                       ('lcpet', 'limit_count_per_entity_turn')):
            if r.get(src):
                rec[k] = _n(r[src]) or 1
        if r.get('group_id'):
            rec['gid'] = _n(r['group_id'])
            if r.get('group_priority'):
                rec['gp'] = _n(r['group_priority'])
        if 'dp' in rec: dynamic_count += 1
        out_specs[pid] = rec
    out_buffs, used_cat = {}, set()
    for bid in sorted(keep_buffs):
        r = buffs[bid]
        used_cat.add(r.get('category') or 0)
        out_buffs[bid] = {
            'n': clean(r.get('name')) or clean(r.get('editor_name'))[:24] or f'状态 {bid}',
            'bt': r.get('buff_type') or 0, 'et': effect_types.get(r.get('effect_type'), ''),
            'ap': str(r.get('active_param') or r.get('activeParam') or '').strip(),
            'mt': middle.get(r.get('middle_type'), ''), 'su': sub.get(r.get('sub_type'), ''),
            'cat': r.get('category') or 0, 'end': r.get('end_time') or 2, 'sc': r.get('stack_count') or 1,
            'mi': r.get('middle_type') or 0, 'sb': r.get('sub_type') or 0,
            'disp': bool(r.get('candispel')), 'imm': bool(r.get('canimmune')),
            'sp': [x for x in ints(r.get('speciality_ids')) if x in specs],
            'd': clean(r.get('desc'))[:100], 'ui': bool(r.get('show_ui')),
        }
    out_cat = {c: [mutex.get(bcat.get(c, {}).get('mutex_type'), ''), bcat.get(c, {}).get('category_stack_limit') or 0]
               for c in sorted(used_cat) if c}
    out_aoe = {}
    for aid in sorted(used_aoe):
        a = aoe[aid]
        rng = _n(a.get('range'))
        out_aoe[aid] = {'sel': rsel.get(a.get('range_select'), 'diamond'), 'min': rng >> 16, 'max': rng & 0xFFFF,
                        'w': a.get('range_width') or 0, 'h': a.get('height') or 0}
    # Timing evidence: count + top effect types per active_time over the closure.
    tcount = Counter(r['at'] for r in out_specs.values())
    timings = {at: {'label': active_time.get(at, ('', f'时机 {at}'))[1], 'type': active_time.get(at, ('', ''))[0],
                    'count': n, 'mapped': at in ENGINE_TIMINGS,
                    'types': [t for t, _ in Counter(r['t'] for r in out_specs.values() if r['at'] == at).most_common(4)]}
               for at, n in tcount.most_common()}
    consts = {r.get('type'): r.get('iparam') for r in table('const_param')
              if r.get('type') in ('CritBaseChance', 'CritBaseDamage', 'RestrainFactor', 'BeRestrainFactor',
                                   'KnockbackImpactDamage', 'FallDamage', 'FallDamageHeight', 'BattleBackCount',
                                   'BattlePerfectTurnCount', 'TacticPointRecoverPerTurn')}
    rules = []
    for r in sorted(table('battle_guidebook_part'), key=lambda r: (r.get('idbattle_guidebook') or 0, r.get('order_id') or 0)):
        if r.get('idbattle_guidebook') == 1:
            rules.append({'name': r.get('name'), 'text': clean(r.get('desc'))})

    # ---- interactive object definitions ---------------------------------
    out_props, out_traps, out_widgets = {}, {}, {}
    for pid, r in props.items():
        sp_ids = [x for x in ints(r.get('speciality_ids')) if x in keep_specs]
        if not sp_ids and not (r.get('hp') or r.get('attackable')):
            continue
        out_props[pid] = {
            'n': clean(r.get('name') or r.get('editor_name'))[:28],
            'd': clean(r.get('desc'))[:200],
            'hp': r.get('hp') or 0, 'hpAdd': r.get('hp_add') or 0,
            'atk': bool(r.get('attackable')), 'col': bool(r.get('collidable')),
            'mov': bool(r.get('movable')), 'h': r.get('height') or 0,
            'pdef': r.get('physic_defence') or 0, 'mdef': r.get('spell_defence') or 0,
            'sp': sp_ids, 'model': r.get('model') or '', 'icon': r.get('icon') or '',
        }
    for tid, r in traps.items():
        out_traps[tid] = {
            'n': clean(r.get('name'))[:28], 'd': clean(r.get('desc'))[:200],
            'tt': r.get('trigger_type') or 0, 'ts': r.get('trigger_skill') or 0,
            'ds': r.get('destroy_skill') or 0, 'lim': r.get('limit_count') or 0,
            'harm': bool(r.get('harmful')), 'atk': bool(r.get('attackable')),
            'friend': bool(r.get('dont_trigger_friend')),
            'model': r.get('model') or '', 'icon': r.get('icon') or '',
        }
    for wid, r in widgets.items():
        out_widgets[wid] = {
            'n': clean(r.get('name'))[:28], 'd': clean(r.get('desc'))[:160],
            'ty': widget_type.get(r.get('type'), ''), 'tt': r.get('trigger_type') or 0,
            'ms': r.get('melee_skill') or 0, 'lim': r.get('limit_count') or 0,
            'harm': bool(r.get('harmful')), 'model': r.get('model') or '',
        }

    # ---- summon templates -------------------------------------------------
    # Every PLACE_UNIT speciality references a unit_npc row. Those summons are
    # full fighters in the client (they have HP, skills, a personality and
    # their own turn), not scenery. Resolve their level-60 growth stats and
    # kit here so the simulator can spawn acting units at runtime.
    npc_rows = {_n(r.get('id')): r for r in table('unit_npc')}
    unit_rows = {_n(r.get('id')): r for r in table('unit')}
    prof_rows = {_n(r.get('id')): r for r in table('profession')}
    growth = defaultdict(list)
    for r in table('unit_modify_level'):
        growth[_n(r.get('idunit_modify'))].append(r)
    for rows in growth.values():
        rows.sort(key=lambda r: _n(r.get('level')))
    personality_groups = defaultdict(list)
    for r in personality_rows:
        personality_groups[_n(r.get('idunit_personality') or r.get('personality_id'))].append(r)
    for rows in personality_groups.values():
        rows.sort(key=lambda r: (_n(r.get('star')), -_n(r.get('skill_id'))))

    summon_ids = set()
    owner_of_spec = defaultdict(set)
    for sid, row in skills.items():
        for pid in ints(row.get('speciality_ids')):
            owner_of_spec[pid].add(sid)
    for bid, row in buffs.items():
        for pid in ints(row.get('speciality_ids')):
            owner_of_spec[pid].add(bid)
    for s in out_specs.values():
        if s['t'] in ('PLACE_UNIT', 'PLACE_UNIT_INHERIT_ATTR'):
            v = (s.get('p') or [0])[0]
            if v and v in npc_rows and v > 100:
                summon_ids.add(v)

    out_summons = {}
    for nid in sorted(summon_ids):
        n = npc_rows[nid]
        u = unit_rows.get(_n(n.get('unit_id')), {})
        rows = growth.get(_n(n.get('unit_modify_id')), [])
        g = next((r for r in rows if _n(r.get('level')) == 60), None)
        if g is None and rows:
            g = min(rows, key=lambda r: abs(_n(r.get('level')) - 60))
        def stat(field, fallback):
            return _n(g and g.get(field), _n(u.get(fallback)))
        star = _n(n.get('star')) or 1
        per_ids = []
        for r in personality_groups.get(_n(n.get('personality_id')), []):
            if _n(r.get('star')) <= star:
                sid = _n(r.get('skill_id') or r.get('idskill'))
                if sid and sid not in per_ids:
                    per_ids.append(sid)
        active_ids = [x for x in ints(n.get('skill_ids')) if x in skills]
        kit = {
            'basic': _n(n.get('melee_skill')), 'actives': active_ids[:6],
            'reactive': [x for x in [_n(n.get('reactive_skill'))] if x],
            'leader': [x for x in [_n(n.get('leader_skill'))] if x],
            'feature': [], 'personality': per_ids[:4], 'chain': [], 'choice': [],
            'derived': [], 'tp': _n(n.get('tp'), 3), 'tpMax': _n(n.get('tp_max'), 5),
            'tags': [], 'unitId': _n(n.get('unit_id')),
        }
        # Client `unit.mobility = 0` means the summon cannot move; a basic
        # skill whose own description says 「不会主动攻击」(静物 / 灵感搜集)
        # means it never takes a turn either. 虚空投影 / 灵感星核 both match,
        # while 幼年夏铃草 (also mobility 0, but basic 穿刺) still acts.
        basic_desc = plain(skills.get(_n(n.get('melee_skill')), {}).get('desc'))
        no_move = _n(u.get('mobility'), 3) == 0
        no_turn = no_move and ('不会主动攻击' in basic_desc or _n(n.get('tp_max'), 5) == 0)
        # 「场上可以存在多个虚空投影但只能有一个灵感星核」: the client enforces
        # this with a REPLACE_SKILL chain on the summoning skill (21460 星核·造物
        # → 21472 星核·位移). Derive uniqueness from that chain, not a table of
        # hard-coded npc ids.
        owner_skills = set()
        for pid, q in specs.items():
            if stype.get(q['type'], {}).get('type') == 'PLACE_UNIT' and _n(q.get('param0')) == nid:
                owner_skills.update(owner_of_spec.get(pid, ()))
        unique = any(any(_n(q.get('param0')) == sid for q in specs.values()
                         if stype.get(q['type'], {}).get('type') == 'REPLACE_SKILL')
                     for sid in owner_skills)
        out_summons[str(nid)] = {
            'n': clean(n.get('name') or u.get('name') or f'召唤物 {nid}')[:28],
            'npc': nid, 'star': star,
            'noMove': no_move, 'noTurn': no_turn, 'unique': unique,
            'faction': _n(n.get('faction')), 'tags': ints(u.get('unit_tag_ids')),
            'basicDesc': basic_desc[:80],
            'stats': {'hp': max(1, stat('hp', 'hp')), 'patk': stat('physic_attack', 'physic_attack'),
                      'matk': stat('spell_attack', 'spell_attack'),
                      'pdef': stat('physic_defence', 'physic_defence'),
                      'mdef': stat('spell_defence', 'spell_defence'),
                      'spd': _n(u.get('speed'), 100)},
            'move': {'mob': _n(u.get('mobility'), 3), 'up': _n(u.get('jump_up'), 2),
                     'down': _n(u.get('jump_down'), 2), 'type': _n(u.get('move_type'), 1)},
            'prof': _n(prof_rows.get(_n(u.get('profession')), {}).get('category')) or 6,
            'profName': clean(prof_rows.get(_n(u.get('profession')), {}).get('name'))[:16],
            'kit': kit,
            'note': '客户端 unit_npc → unit → unit_modify_level（60 级成长表）；召唤物拥有自己的行动回合。',
        }

    # Client `shapeshift` table: SHAPESHIFT p[0] is a form id whose row names
    # the NPC the unit turns into. Buffs gate on the NEW identity, e.g. 3279
    # 金狮形态 `return owner:IsUnit(923)` after form 266 → npc 8292 (unit 923).
    shape_rows = {r['id']: r for r in table('shapeshift')}
    out_shapes = {}
    for q in out_specs.values():
        if q.get('t') != 'SHAPESHIFT':
            continue
        fid = _n((q.get('p') or [0])[0])
        row = shape_rows.get(fid)
        if not row or str(fid) in out_shapes:
            continue
        npc = _n(row.get('unit_npc_id'))
        nrow = npc_by_id.get(npc, {})
        out_shapes[str(fid)] = {
            'n': clean(row.get('name') or '')[:40], 'npc': npc,
            'unit': _n(nrow.get('unit_id')),
            'inheritSkill': bool(row.get('inherit_skill')),
            'inheritAttr': bool(row.get('inherit_attribute')),
            'inheritHp': bool(row.get('inherit_hp_percent')),
            'hpPct': _n(row.get('hp_percent'), 100),
        }

    # Round 34: resolve every skill's damage / effect pipeline from its client
    # description and the decrypted speciality Lua (`dynamic_param`).
    skill_plans, plan_stats = derive_plans(out_skills, out_specs, out_buffs, attrs, unit_tags)

    data = {
        'v': 1,
        'skillPlans': skill_plans,
        'shapeshifts': out_shapes,
        'skills': out_skills, 'specs': out_specs, 'buffs': out_buffs, 'buffCats': out_cat,
        # buff id → client attribute-buff tier (1..5), from buff_group names.
        'buffTiers': buff_tiers, 'aoe': out_aoe,
        # unit_tag id → name (铃兰之剑=1 …). Engine resolves 〈阵营〉 conditions
        # and faction-aura targets from this map, never from hard-coded names.
        'unitTags': {str(k): v for k, v in unit_tags.items()},
        'specTypes': {str(k): v for k, v in sorted(type_names.items())},
        # Full client tag dictionaries for the skill-label UI.
        'skillTagNames': {str(k): v for k, v in tag_names.items()},
        'damageTypeNames': {str(k): v for k, v in dt_names.items()},
        'enums': {'attributes': attrs, 'abnormal': abnormal, 'effectTypes': effect_types,
                  'activeTime': {k: v[0] for k, v in active_time.items()},
                  'specTypeAll': {r['id']: r.get('type') for r in stype.values()},
                  'middleTypes': middle, 'subTypes': sub, 'unitTags': unit_tags,
                  'damageTypes': {r['id']: r.get('type') for r in table('damage_type')},
                  'hitMethod': {'NONE': 1, 'DIRECT': 2, 'INDIRECT': 3},
                  'rangeTag': {'NONE': 1, 'MELEE': 2, 'RANGED': 3},
                  'buffType': {'NONE': 1, 'SPECIAL': 1, 'BUFF': 2, 'DEBUFF': 3, 'ARMOR': 4},
                  'fieldStatus': {r['id']: r.get('type') for r in field_rows}},
        # Full client terrain rules (30 overlays) + their tile specialities,
        # plus the OPERATION id → field_status id mapping.
        'fieldStatusDefs': field_defs, 'fieldOperations': operation_map,
        'props': out_props, 'traps': out_traps, 'widgets': out_widgets,
        'summons': out_summons,
        'trapTriggers': trap_trigger, 'widgetTriggers': widget_trigger,
        'hpAttenuation': hp_att, 'restrain': restrain, 'weather': weather_out,
        'constants': consts, 'timings': timings, 'rules': rules,
        'dynamicParams': {'exported': dynamic_count,
                          'note': '客户端 speciality.dynamic_param 的 Lua 脚本，运行时按 owner/target/buff 状态改写 param0-3；'
                                  '例如「每层渴血战斧使物攻额外提高10%」「获得脂肪时获得等量信仰值」。'},
        'speedConversion': {'attribute': 'SPEED', 'converted': converted,
                            'note': '客户端把速度修正存为行动等待(WT)增量（速度+50 记为 -50）；导出时取反为正常速度加成，速度越大越先行动。'},
        'sources': [
            'skill：射程 / 目标 / 伤害类型与系数 / 能量 / 冷却 / speciality_ids / 技能标签',
            'speciality + speciality_type：效果类型、参数、触发时机 active_time、目标方 target_type、次数限制与 Lua 激活条件',
            'buff + buff_category：增益 / 减益、效果类、驱散 / 免疫标记、互斥与叠层、持续递减时机 end_time',
            'aoe_param + range_select：范围形状（菱形 / 十字 / 单向线 / 矩形 / 全场 …）与高度',
            'hp_attenuation：受伤 / 濒死阈值与效果；profession_restrain：职业克制效果',
            'weather.aura_speciality：天气光环；const_param：暴击 / 克制 / 撞击 / 坠落常数',
            'battle_guidebook_part：客户端战斗手册（伤害计算、能量、行动开始 / 结束、击退、援护、反击规则）',
            'unit_npc / unit / unit_modify_level：PLACE_UNIT 召唤物模板（王女亲卫等），含 60 级五维、技能编组与行动能力',
            'props / trap / widget：交互物定义（生命 / 可攻击 / 可碰撞 / 可推动 / 自身效果）与触发物（途经 / 停留、触发技能、次数上限、是否被己方触发）',
            'skill.desc + speciality.dynamic_param（已解密 Lua）：逐技能结算方案 —— 多段命中、'
            '消耗能量/层数追加伤害、增伤、击退等，由引擎逐段独立结算',
        ],
    }
    OUT.write_text('window.WIKI_BATTLE_MECH=' + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n',
                   'utf8')
    tc = Counter(r['t'] for r in out_specs.values())
    print(f'战斗机制数据：{len(out_skills)} 个技能 / {len(out_specs)} 条效果（{len(tc)} 种类型）/ '
          f'{len(out_buffs)} 个状态 / {len(out_props)} 个交互物 / {len(out_traps)} 个触发物 / '
          f'{len(out_widgets)} 个装置 / {len(out_summons)} 个召唤物模板 / {len(out_aoe)} 种范围 / {len(rules)} 条手册规则，'
          f'{OUT.stat().st_size / 1024:.0f} KiB → {OUT.relative_to(ROOT)}')
    print(f'  逐技能结算方案：{len(skill_plans)} 个 / 多段 {plan_stats["groups"]} / '
          f'消耗 {plan_stats["consume"]} / 追加伤害 {plan_stats["bonus"]} / 击退 {plan_stats["knock"]}')
    print('  效果类型前 20：', tc.most_common(20))
    print('  未识别时机：', {k: v['count'] for k, v in timings.items() if not v['mapped']})
    return 0


if __name__ == '__main__':
    sys.exit(main())
