"""Export 乐土群星杯 (client "斗蛐蛐活动版2") match data for the simulator.

The client config tables contain the whole tournament: activities, modes,
63 preset teams of NPC fighters, 204 scheduled matches with their mission
buffs, betting odds and rule texts. NPC stats come from the same tables the
game uses (unit_npc -> unit -> unit_modify_level at the cup's unit level),
and skills are the real `skill` rows (range / factor / cooldown / ai order).

Writes data/match-cup.js (window.WIKI_MATCH_CUP), loaded on demand by the
simulator. Nothing here is invented: fields without a client source are left
out and documented under `notes`.

    python -X utf8 scripts/extract_match_cup.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from extract_battle_sim import (table, plain, ints, load_js, personality_skill_ids, unit_kit,
                                area_of, hits_of, TARGET_ENEMY, TARGET_ALLY, TARGET_GROUND,
                                TARGET_SELF, TARGET_DIRECTION)

# Skill classification comes from the client's own columns:
#   skill.type      1 = castable active, 2 = derived/nested, 3 = passive/reactive
#   skill.skill_type 2/6/9 = castable damage/heal/mixed (the engine's castable())
# The old export labelled every unit_npc.skill_ids entry "主动技能" even when it
# was a type=3 passive, and fell back to an empty display name for personality
# skills (which only carry editor_name).
CLIENT_ROLE = {1: '主动', 2: '衍生', 3: '被动'}
CASTABLE_ST = {2, 6, 9}
CHAIN_FIELDS = (('skill_attached_passive_id', '附属被动'),
                ('idskill_follow', '连携技能'),
                ('skill_cast_id', '施放技能'),
                ('overwritten_skill_id', '替换技能'))
_SPEC_TYPE, _SPEC_ROW, _TAG_NAME = {}, {}, {}
# Specialities that reference OTHER skills. The client stores a fighter's
# directly carried skills in unit_npc.skill_ids, but many skills are only
# obtainable in battle: a 抉择 (choice) skill offers 2-4 options via
# SKILL_GROUP / TACTICS_SKILL_GROUP, and CAST_SKILL / GET_EXTRA_SKILL etc.
# release or replace skills. Those ids are real carried skills too.
CHOICE_SPEC = {'SKILL_GROUP', 'TACTICS_SKILL_GROUP'}
DERIVED_SPEC = {
    'CAST_SKILL', 'ADDITIONAL_ATTACK', 'MAKE_OTHER_CAST_SKILL', 'MAKE_BUFF_SOURCE_CAST_SKILL',
    'DELAY_CAST_SKILL', 'FORCE_CAST_SKILL', 'MAKE_SUMMONER_CAST_SKILL', 'MAKE_DYNAMIC_CAST_SKILL',
    'CONDITION_SKILL', 'LOGIC_SKILL', 'ACTED_ACT', 'COUNTER_ATTACK', 'FIRST_HIT', 'ALERT_ATTACK',
    'ASSIST_ATTACK', 'ASSIST_COUNTER_ATTACK', 'ASSIST_TEAMMATE', 'REACTIVE_SKILL',
    'GET_EXTRA_SKILL', 'REPLACE_SKILL', 'CONVERT_SKILL', 'SKILL_CD', 'SKILL_COUNT',
}

# Client SPEED (attribute_type 17) is a WAIT-TIME value: lower acts earlier.
# 「速度强化 I」is stored as -50, 「速度降低 I」as +50. Keep the raw value in the
# export and let the engine / panel explain the inverted sign.
# Client 「精英属性补回」: skill 16046 is attached through
# unit_personality_skill(skill_group_id=2, star=1) to 82 gladiator
# personalities. It grants PREWAR HP_MAX +80% and +10% to all four attack /
# defence stats. Those numbers only make sense as a compensation for NPCs
# whose growth table (unit_modify_id) is the NON-elite variant while the
# mission applies the「全体敌人升级为精英属性」buff (mission_buff_pool
# buff_id 9686 / 1130: +150% HP, +20% ATK, +30% DEF …). None of the 192 cup
# schedules references that buff (cup buff pool ids are 8603/8634/5874/…),
# and cup fighters use the level-60 growth table, so the compensation must
# NOT be applied to tournament fighters. It is kept as reference only.
ELITE_COMP_NAMES = ('精英属性补回',)

def is_elite_compensation(row):
    return any(x in str(row.get('editor_name') or '') for x in ELITE_COMP_NAMES)

SPEED_NOTE = ('客户端把速度修正存为行动等待(WT)增量（「速度+50」在配置里是 -50）；'
              'data/battle-mech.js 导出时已取反为正常速度加成。游戏内速度越大越先行动，+200 就是加 200 点速度。')

WORLD = load_js('world-data.js', 'WIKI_WORLD_DATA')

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data' / 'match-cup.js'

CUP_LEVEL = 60  # online_match.unit_level


def _num(v, default=0):
    try:
        return int(float(str(v or default)))
    except (TypeError, ValueError):
        return default


def clean_name(value):
    """Client names embed <sprite ...> markers; render them as readable text."""
    s = re.sub(r'<sprite[^>]*name="([^"]+)"[^>]*>', lambda m: '·' + m.group(1).upper(), str(value or ''))
    return re.sub(r'<[^>]*>', '', s).strip()


def client_skill_name(row):
    """Readable display name: client `name`, else editor label, else description."""
    n = clean_name(row.get('name'))
    if n:
        return n
    e = re.sub(r'[\[\]【】（）()]', ' ', str(row.get('editor_name') or ''))
    e = re.sub(r'\s+', ' ', e).strip()
    if e:
        return e[:34]
    d = plain(row.get('desc'))
    if d:
        return d[:26] or f"技能 {row['id']}"
    return f"技能 {row['id']}"


def skill_role(row, slot):
    """Role shown in the UI: the client's slot, refined by skill.type.

    unit_npc.skill_ids mixes castable actives and type=3 passives, so calling
    all of them "主动技能" was wrong. Reactions / leader / personality keep
    their explicit slot; derived nested skills coming from a chain keep the
    chain role assigned by the caller.
    """
    if slot not in ('主动技能', '初始技能'):
        return slot
    ty = _num(row.get('type'))
    return {1: '主动技能', 2: '衍生技能', 3: '被动技能'}.get(ty, '主动技能')


def skill_full(row, role, chain_from=0, depth=0):
    """Full client skill record with correct client-side classification.

    Every skill also carries its speciality (effect) type list, so the UI can
    explain what a passive / reaction / personality skill actually does
    instead of showing an empty name and a "not simulated" label.
    """
    desc = plain(row.get('desc'))
    ty, st = _num(row.get('type')), _num(row.get('skill_type'))
    spec_ids = ints(row.get('speciality_ids'))
    spec_types = []
    for sid in spec_ids:
        t = _SPEC_TYPE.get(_SPEC_ROW.get(sid, {}).get('type'))
        if t and t not in spec_types:
            spec_types.append(t)
    tags = [_TAG_NAME.get(t) for t in ints(row.get('skill_tag_ids'))]
    tags = [t for t in tags if t]
    # Align with the engine's castable(): EVERY client active (skill.type 1)
    # is castable, including heal / support / debuff / tactical families whose
    # skill_type is 1/4/5/8. They deal no damage but their specialities
    # (BUFF / DISPEL / RECOVER / AOE / ...) run when the skill is cast.
    simulated = ty == 1
    out = {
        'id': row['id'], 'name': client_skill_name(row), 'role': role, 'chainFrom': chain_from or 0,
        'clientType': ty, 'clientRole': CLIENT_ROLE.get(ty, '其它'), 'skillType': st,
        'classType': _num(row.get('class_type')), 'damageType': _num(row.get('damage_type')),
        'desc': desc[:150], 'editorName': str(row.get('editor_name') or '')[:70],
        'specCount': len(spec_ids), 'specTypes': spec_types[:10], 'tags': tags[:6],
        'activeParam': plain(row.get('active_param'))[:160],
        'skillRole': 'choice' if CHOICE_SPEC & set(spec_types) else '',
        'simulated': simulated,
        'utility': bool(simulated and (not _num(row.get('damage_factor')) and not _num(row.get('damage'))
                                       and not _num(row.get('damage_percent')) and _num(row.get('damage_type')) != 2)),
        'notSimulated': '' if simulated else '被动 / 反应 / 个性：由客户端效果结算',
    }
    if simulated:
        # Derive the cast geometry straight from the client row, so percent-heal
        # skills with damage_factor 0 still carry range / aim in the fallback.
        tm = _num(row.get('target_method'))
        aim = ('enemy' if tm in TARGET_ENEMY else 'ally' if tm in TARGET_ALLY else
               'self' if tm in TARGET_SELF else 'direction' if tm in TARGET_DIRECTION else
               'ground' if tm in TARGET_GROUND else 'other')
        if aim == 'other':
            aim = 'enemy'
        out.update({
            'usable': True, 'heal': _num(row.get('damage_type')) == 3, 'aim': aim,
            'rangeMin': _num(row.get('range_min')), 'rangeMax': _num(row.get('range_max')),
            # range_select (target_select) is the cast shape; range_tag is the
            # NONE / MELEE / RANGED tag used by active_param conditions only.
            'targetSelect': _num(row.get('target_select')) or 1,
            'shape': 'cross' if _num(row.get('target_select')) == 2 else 'diamond',
            'area': area_of(row, desc), 'factor': _num(row.get('damage_factor')),
            'cooldown': _num(row.get('cooldown')), 'order': _num(row.get('ai_skill_order')),
            'hits': hits_of(desc), 'ignoreDef': _num(row.get('damage_type')) == 4,
        })
        out.update({
            'usable': True,
            'damagePercent': row.get('damage_percent') or 0,
            'defenceIgnore': row.get('defence_ignore') or 0,
            'critChance': row.get('crit_chance') or 0,
            'attackMethod': row.get('attack_method') or 0,
            'physic': row.get('physic_factor') or 0, 'spell': row.get('spell_factor') or 0,
            'aiOrderParam': plain(row.get('ai_order_param'))[:110],
            'targetOrderParam': plain(row.get('target_order_param'))[:110],
            'activeParam': plain(row.get('active_param'))[:110],
            'tp': row.get('tp') or 0,
        })
    return out


def main():
    if not (ROOT / 'output/archive/library/当前版本/配置表').is_dir():
        print('跳过群星杯数据：缺少本地客户端配置表（先完成一次「本地更新」）。')
        return 0

    combat = load_js('combat-data.js', 'WIKI_COMBAT_DATA')
    categories = {c['id']: c['name'] for c in combat.get('categories', [])}
    unit = {r['id']: r for r in table('unit')}
    npc = {r['id']: r for r in table('unit_npc')}
    skills = {r['id']: r for r in table('skill')}
    global _SPEC_TYPE, _SPEC_ROW, _TAG_NAME
    _SPEC_TYPE = {r['id']: r.get('type') for r in table('speciality_type')}
    _SPEC_ROW = {r['id']: r for r in table('speciality')}
    _TAG_NAME = {r['id']: (r.get('name') or r.get('type')) for r in table('skill_tag')}
    # Player-version skill slots (unit_phantom_skill.slot1..6) are NOT the
    # tournament NPC's carried skills; export them as a clearly-labelled
    # reference only (the previous round removed them from the kit).
    global _PHANTOM, _SPECIALITY_SKILL_REFS, _SEASON_FACING, _MODULE_SKILLS
    # 解放/模组技能: online_module_skill.exclusive_unit_id →
    # online_role_unit.id → idunit (unit table id). Chains have 3 levels;
    # only the highest unlocked tier applies (cup fighters use the max tier).
    role_unit = {r['id']: r for r in table('online_role_unit')}
    _MODULE_SKILLS = defaultdict(dict)
    for r in table('online_module_skill'):
        ru = role_unit.get(r.get('exclusive_unit_id'))
        if not ru or r.get('skill_id') not in skills:
            continue
        uid = ru.get('idunit')
        lvl = _num(r.get('level')) or 1
        prev = _MODULE_SKILLS[uid].get('level', 0)
        if lvl >= prev:
            _MODULE_SKILLS[uid] = {'id': r['skill_id'], 'level': lvl,
                                   'name': clean_name(r.get('name') or '')}
    _MODULE_SKILLS = {uid: v['id'] for uid, v in _MODULE_SKILLS.items()}
    _PHANTOM = defaultdict(list)
    for r in table('unit_phantom_skill'):
        if r.get('type') == 2 and r.get('star') == 5 and r.get('rank') == 13:
            _PHANTOM[r.get('idunit')].append([r.get(f'slot{i}') or 0 for i in range(1, 7)])
    _SEASON_FACING = Counter(r.get('unit_facing') for r in table('arena_season_template'))
    modify_levels = defaultdict(list)
    for r in table('unit_modify_level'):
        modify_levels[r['idunit_modify']].append(r)
    for rows in modify_levels.values():
        rows.sort(key=lambda r: r['level'])
    personalities = {r['id']: r for r in table('unit_personality')}
    professions = {r['id']: r for r in table('profession')}
    modifies = {r['id']: r for r in table('unit_modify')}
    rarities = table('unit_rarity')
    unit_buff_names = {r['buff_id']: r.get('name') for r in table('online_match_activity_unit_buff')}
    buff_by_id = {r['id']: r for r in table('buff')}
    buff_pools = {r['id']: r for r in table('mission_buff_pool')}
    quests = {r['id']: r for r in table('online_quest')}
    battle_params = {r['id']: r for r in table('mission_battle_param')}

    def npc_fighter(nid):
        n = npc.get(nid)
        if not n:
            return None
        u = unit.get(_num(n.get('unit_id')), {})
        rows = modify_levels.get(_num(n.get('unit_modify_id')), [])
        growth = next((r for r in rows if r['level'] == CUP_LEVEL), None)
        if growth is None and rows:
            growth = min(rows, key=lambda r: abs(r['level'] - CUP_LEVEL))
        hp = _num(growth and growth['hp'], u.get('hp'))
        patk = _num(growth and growth['physic_attack'], u.get('physic_attack'))
        matk = _num(growth and growth['spell_attack'], u.get('spell_attack'))
        pdef = _num(growth and growth['physic_defence'], u.get('physic_defence'))
        mdef = _num(growth and growth['spell_defence'], u.get('spell_defence'))
        # Keep the exact provenance so the page can explain a base stat. The
        # client has separate rarity / rank multipliers; the growth row alone
        # is NOT necessarily the in-game base (e.g. 黑暗医师 2212 vs 2388).
        _mid = _num(n.get('unit_modify_id'))
        _lv = _num(growth and growth.get('level'), CUP_LEVEL)
        stat_source = {
            'modifyId': _mid,
            'modifyName': (modifies.get(_mid) or {}).get('name') or '',
            'level': _lv,
            'row': {k: _num(growth and growth.get(k)) for k in
                    ('hp', 'physic_attack', 'spell_attack', 'physic_defence', 'spell_defence')} if growth else {},
            'unitBase': {k: _num(u.get(k)) for k in
                         ('hp', 'physic_attack', 'spell_attack', 'physic_defence', 'spell_defence')},
            'unitModifyId': _num(u.get('unit_modify_id')),
            'rarityAdjust': {r['id']: _num(r.get('base_attribute_adjust')) for r in rarities},
            'note': '当前基础值取自 unit_npc.unit_modify_id 的 60 级成长表；客户端另有 unit_rarity.base_attribute_adjust 等倍率，游戏内面板可能更高。',
        }
        name = clean_name(n.get('name') or u.get('name') or f'NPC {nid}')
        # unit.profession is a `profession` row id; its `category` is the same
        # 1–6 profession category the restraint table uses.
        prof = _num(professions.get(_num(u.get('profession')), {}).get('category')) or 6
        # Collect EVERY skill the client assigns to this NPC. Only unit_npc
        # columns are authoritative: `unit` is the playable-character template
        # and its default_skills / feature_skills / skill_ids belong to a
        # different kit (they injected 149 unrelated player skills before).
        # Skill chains (attached passive / follow-up / cast / overwrite) are
        # client references on the skill row and must be carried too — the
        # engine resolves their effects from data/battle-mech.js.
        collected, seen, chain_ids = [], set(), []

        choice_ids, derived_ids = [], []

        def skill_refs(row):
            """Skills referenced by this skill's specialities (choice / cast / grant)."""
            choice, derived = [], []
            for sid in ints(row.get('speciality_ids')):
                spec = _SPEC_ROW.get(sid)
                if not spec:
                    continue
                typ = _SPEC_TYPE.get(spec.get('type'))
                if typ not in CHOICE_SPEC and typ not in DERIVED_SPEC:
                    continue
                refs = [_num(spec.get(f'param{i}')) for i in range(4)]
                refs += [x for x in ints(spec.get('sparam')) if x]
                for r in refs:
                    if r and r in skills and r != row['id']:
                        (choice if typ in CHOICE_SPEC else derived).append(r)
            return choice, derived

        def add(sid, slot, chain_from=0, depth=0):
            sid = _num(sid)
            if not sid or sid in seen or sid not in skills:
                return
            seen.add(sid)
            row = skills[sid]
            role = slot if chain_from else skill_role(row, slot)
            rec = skill_full(row, role, chain_from, depth)
            if is_elite_compensation(row):
                rec['notApplied'] = ('客户端精英环境补偿（skill 16046：生命+80%、攻防各+10%）；'
                                    '群星杯赛程未施加「全体敌人升级为精英属性」增益，实际对局不生效，仅作资料保留。')
            if role == '派生技能':
                rec = {k: rec[k] for k in ('id', 'name', 'role', 'chainFrom', 'clientType',
                                           'clientRole', 'skillType', 'specCount', 'specTypes',
                                           'simulated', 'notSimulated', 'activeParam')}
                rec['desc'] = plain(row.get('desc'))[:60]
            collected.append(rec)
            if depth >= 2:
                return
            for field, chain_role in CHAIN_FIELDS:
                for nxt in ints(row.get(field)):
                    if nxt in skills and nxt not in seen:
                        chain_ids.append(nxt)
                        add(nxt, chain_role, sid, depth + 1)
            # Client skills reached through effects: 抉择选项 must join the
            # fighter's castable actives; other derived skills join the mech
            # closure and the reference list.
            choice, derived = skill_refs(row)
            for nxt in choice:
                if nxt not in seen:
                    choice_ids.append(nxt)
                    add(nxt, '抉择选项', sid, depth + 1)
            for nxt in derived:
                derived_ids.append(nxt)
                if nxt not in seen:
                    add(nxt, '派生技能', sid, depth + 1)

        add(n.get('melee_skill'), '普攻')
        for sid in ints(n.get('skill_ids')):
            add(sid, '主动技能')
        add(n.get('reactive_skill'), '反应技')
        add(n.get('leader_skill'), '队长技')
        # Personality skills: for every skill group, the highest tier whose
        # star <= this fighter's star (unit_npc.star; NOT unit.personality_id,
        # 166/223 cup fighters use a tournament-specific personality).
        star = _num(n.get('star')) or 5
        elite_comp = []
        for sid in personality_skill_ids(_num(n.get('personality_id')), star):
            row = skills.get(sid) or {}
            if is_elite_compensation(row):
                elite_comp.append(sid)
                add(sid, '个性（精英补正）')
            else:
                add(sid, '个性')
        # 解放技能 (online_module_skill) belongs to the character, not to
        # unit_npc; without it 「光辉认证的坚定信仰」的虔诚值 / 魔攻转物攻
        # never enters the battle.
        module_skill = _MODULE_SKILLS.get(_num(n.get('unit_id')))
        if module_skill:
            add(module_skill, '解放技能')
        # unit_kit's `initial` / `feature` come from `unit`; for an NPC those
        # are the player template, so build a clean pseudo-unit that only keeps
        # the shared tags and energy profile.
        npc_unit = {'unit_tag_ids': u.get('unit_tag_ids'), 'tp': n.get('tp'), 'tp_max': n.get('tp_max')}
        ordered = ints(n.get('skill_ids'))
        kit = unit_kit(npc_unit, basic=_num(n.get('melee_skill')), actives=ordered, star=star,
                       personality_id=_num(n.get('personality_id')),
                       extra_reactive=_num(n.get('reactive_skill')), extra_leader=_num(n.get('leader_skill')),
                       ai_by_order=n.get('ai_skill_by_order'), ai_sorted=n.get('ai_skill_sorted'),
                       boss_mode=_num(n.get('boss_skill_mode')),
                       boss_sequence=ints(n.get('boss_skill_sequence')), skill_order=ordered)
        kit['chain'] = list(dict.fromkeys(chain_ids))
        # unit_kit() includes every personality skill. The elite compensation
        # is a reference-only entry: remove it from the live kit by default,
        # the page can opt in via setup.eliteComp (cupMembers re-injects it).
        kit['eliteComp'] = elite_comp
        kit['personality'] = [x for x in kit['personality'] if x not in elite_comp]
        if module_skill:
            kit['module'] = [module_skill]
        # Choice options are real castable skills in the client; derived skills
        # are released in battle (GET_EXTRA_SKILL / CAST_SKILL ...).
        kit['choice'] = [x for x in dict.fromkeys(choice_ids) if x in skills][:12]
        kit['derived'] = list(dict.fromkeys(derived_ids))[:40]
        kit['aiByOrder'] = bool(n.get('ai_skill_by_order'))
        kit['aiSorted'] = bool(n.get('ai_skill_sorted'))
        kit['bossMode'] = _num(n.get('boss_skill_mode'))
        kit['skillOrder'] = [x for x in ordered if x in skills]
        kit['bossSequence'] = [x for x in ints(n.get('boss_skill_sequence')) if x in skills]
        kit.update(tp=_num(n.get('tp')), tpMax=_num(n.get('tp_max')), unitId=_num(n.get('unit_id')))
        # `skills` is the legacy/fallback castable list; derived skills are
        # released in battle by effects and carry a compact record only.
        sim = [s for s in collected if s['simulated'] and s['role'] != '派生技能'][:8]
        if not sim:
            basic = next((s for s in collected if s['role'] == '普攻'), None) or (collected[0] if collected else None)
            if basic:
                basic = dict(basic)
                basic.update(usable=True, simulated=True, heal=False, aim='enemy',
                             rangeMin=0, rangeMax=1, shape='diamond', area={'type': 'single'},
                             factor=100, cooldown=0, hits=1, ignoreDef=False,
                             attackUp=0, attackDown=0)
                sim = [basic]
        personality = personalities.get(_num(n.get('personality_id')), {})
        return {
            'npcId': nid, 'name': name, 'unitId': _num(n.get('unit_id')),
            'editorName': n.get('editor_name') or '',
            'prof': prof, 'profName': categories.get(prof, '无属性'),
            'profRaw': _num(u.get('profession')), 'faction': _num(n.get('faction')),
            'star': _num(n.get('star')), 'tp': _num(n.get('tp')), 'tpMax': _num(n.get('tp_max')),
            'personality': clean_name(personality.get('name')) or '',
            'aiByOrder': bool(n.get('ai_skill_by_order')),
            'aiSorted': bool(n.get('ai_skill_sorted')),
            'bossSequence': str(n.get('boss_skill_sequence') or ''),
            'stats': {'hp': hp, 'patk': patk, 'matk': matk, 'pdef': pdef, 'mdef': mdef,
                      'spd': _num(u.get('speed'), 100),
                      'critRatio': _num(u.get('crit_ratio')),
                      'critDamage': _num(u.get('crit_damage'))},
            'move': {'mob': _num(u.get('mobility'), 3) or 3,
                     'up': _num(u.get('jump_up'), 2) or 2,
                     'down': _num(u.get('jump_down'), 2) or 2,
                     'type': _num(u.get('move_type'), 1) or 1},
            'skills': sim, 'allSkills': collected, 'kit': kit,
            'statSource': stat_source,
            'eliteCompensation': elite_comp,
            # Player-version skill slots of the SAME unit id, reference only:
            # the tournament NPC uses its own unit_npc fields, not these.
            'referenceSlots': [[clean_name(skills[x].get('name') or skills[x].get('editor_name') or '') or f'技能 {x}'
                                for x in row if x in skills and x]
                               for row in _PHANTOM.get(_num(n.get('unit_id')), [])][:2],
            'skillCount': len(collected), 'simSkillCount': len(sim),
            'statLevel': (growth or {}).get('level', CUP_LEVEL),
        }

    # ---- teams ----
    tname = {r['id']: r['name'] for r in table('online_match_activity_team_name')}
    teams, team_by_id = [], {}
    for r in table('online_match_activity_regular_team') + table('online_match_regular_team'):
        tid = r['id']
        if tid in team_by_id:
            continue
        name = r.get('name') or tname.get(r.get('name_id')) or f'队伍 {tid}'
        members = [f for f in (npc_fighter(i) for i in ints(r.get('unit_npc_ids'))) if f]
        if not members:
            continue
        t = {'id': tid, 'name': re.sub(r'<[^>]*>', '', str(name)).strip(), 'members': members}
        teams.append(t)
        team_by_id[tid] = t

    # ---- activities / modes / schedules / bets / rules ----
    activities = [{
        'id': r['id'], 'name': r['name'],
        'startAt': r.get('start_at'), 'endAt': r.get('end_at'),
        'teamIds': ints(r.get('regular_team_ids')),
        'minCost': _num(r.get('pickup_team_min_cost')),
        'maxCost': _num(r.get('pickup_team_max_cost')),
        'maxUnits': _num(r.get('pickup_team_max_unit_count')),
        'unitLevel': CUP_LEVEL,
    } for r in table('online_match_activity')]
    modes = [{
        'id': r['id'], 'activityId': r.get('idonline_match_activity'), 'name': r.get('name'),
        'roundCount': _num(r.get('round_count')), 'matchStructure': r.get('match_structure'),
        'category': r.get('match_category'), 'typeIds': ints(r.get('online_match_activity_type_ids')),
    } for r in table('online_match_activity_mode')]
    buffs = {r['id']: r.get('name') or r.get('editor_name') or f'增益 {r["id"]}'
             for r in table('mission_buff_pool')}
    # The client schedule has no battle-map id. Pick the only arena map with a
    # usable battle grid as the documented inference (evidence is exported).
    _CUP_MAP = {'id': 0, 'name': ''}
    for m in WORLD.get('maps', []):
        if 'arena' in str(m.get('model') or '').lower() and (m.get('cells') or []):
            _CUP_MAP = {'id': m['id'], 'name': (m.get('stages') or [None])[0] or m.get('name') or m.get('model')}
            break
    schedules = []
    for r in table('online_match_activity_server_schedule'):
        t1, t2 = team_by_id.get(r.get('team1_id')), team_by_id.get(r.get('team2_id'))
        if not t1 or not t2:
            continue
        pool_ids = ints(r.get('mission_buff_pool_ids'))
        pool = []
        for i in pool_ids:
            bp = buff_pools.get(i)
            if not bp:
                continue
            buff = buff_by_id.get(_num(bp.get('buff_id')), {})
            pool.append({'id': i, 'name': clean_name(bp.get('name') or bp.get('editor_name') or ''),
                         'buffId': _num(bp.get('buff_id')),
                         # mission_buff_pool.target: 1 = 我方(team1), 2 = 敌方(team2), 3 = 双方
                         'target': _num(bp.get('target')),
                         'buffName': clean_name(buff.get('name') or ''),
                         'effect': plain(buff.get('desc'))[:240],
                         'turnMax': _num(bp.get('turn_max'))})
        status = []
        try:
            status = json.loads(r.get('unit_status_data') or '[]')
        except (ValueError, TypeError):
            pass
        status_named = []
        for s in status:
            bid = _num(s.get('buff_id'))
            b = buff_by_id.get(bid, {})
            status_named.append({'npcId': _num(s.get('unit_npc_id')),
                                 'teamIndex': _num(s.get('team_index')),
                                 'buffId': bid,
                                 'name': clean_name(unit_buff_names.get(bid) or b.get('name') or ''),
                                 'effect': plain(b.get('desc'))[:240]})
        qid = _num(r.get('mission_id'))
        q = quests.get(qid, {})
        mid = _num(q.get('idmission'))
        bp_row = battle_params.get(mid, {})
        mode = next((m for m in modes if m['id'] == r.get('idonline_match_activity_mode')), {})
        schedules.append({
            'id': r['id'], 'name': r.get('name'), 'day': _num(r.get('day')),
            'group': _num(r.get('group')), 'modeId': r.get('idonline_match_activity_mode'),
            'modeName': mode.get('name') or '',
            'activityId': next((m['activityId'] for m in modes if m['id'] == r.get('idonline_match_activity_mode')), 1),
            'team1Id': t1['id'], 'team2Id': t2['id'],
            'team1': t1['name'], 'team2': t2['name'],
            'buffs': [x['name'] for x in pool], 'buffDetails': pool,
            'unitStatus': status_named,
            'quest': {'id': qid, 'name': clean_name(q.get('name') or ''),
                      'idmission': mid, 'level': _num(q.get('level')),
                      'winText': clean_name(q.get('win_text') or ''),
                      'loseText': clean_name(q.get('lose_text') or ''),
                      'scenario': plain(q.get('scenario_text'))[:200],
                      'battleRoleMax': _num(q.get('battle_role_max')),
                      'battleHeroMax': _num(q.get('battle_hero_max')),
                      'battleMercMax': _num(q.get('battle_merc_max')),
                      'turnLimit': _num(bp_row.get('appoint_turn_count')),
                      'battleResultType': _num(bp_row.get('battle_result_type')),
                      'resultType': _num(bp_row.get('result_type'))},
            'roundCount': _num(mode.get('roundCount')),
            # Per-match map / formation. The client schedule ONLY stores
            # mission_id (a story quest id), never a battle map id or spawn
            # coordinates. `arena_season_template.unit_facing` is the only
            # formation-ish field and belongs to the arena season, not this cup.
            # We therefore record the inferred arena map and expose the exact
            # evidence; the page lets the user override every fighter's tile.
            'mapId': _CUP_MAP['id'],
            'mapName': _CUP_MAP['name'],
            'mapSource': '推定（客户端赛程表无地图 id）',
            'formation': {
                'A': [{'npcId': m['npcId'], 'name': m['name']} for m in t1['members'][:8]],
                'B': [{'npcId': m['npcId'], 'name': m['name']} for m in t2['members'][:8]],
                'facingSource': 'arena_season_template.unit_facing（竞技场赛季朝向，非群星杯专属）',
                'spawnSource': '推定（map.data 仅含地形格子，无出生点）',
            },
        })
    bet_by_mode = defaultdict(list)
    bet_names = {r['id']: r.get('name') for r in table('online_match_activity_bet')}
    for r in table('online_match_activity_bet_option'):
        if r.get('win_odds'):
            bet_by_mode[r.get('idonline_match_activity_bet')].append({
                'name': r.get('name'), 'winOdds': _num(r.get('win_odds')),
                'loseOdds': _num(r.get('lose_odds')), 'round': _num(r.get('round')),
            })
    bets = [{'id': k, 'name': bet_names.get(k), 'options': v} for k, v in sorted(bet_by_mode.items())]
    rules = []
    seen_rules = set()
    for r in table('text'):
        s = plain(r.get('text'))
        if len(s) < 18 or s in seen_rules:
            continue
        if any(k in s for k in ('乐土群星杯', '博弈演习', '狂欢公开赛', '群星之杯')) and \
           any(k in s for k in ('押注', '竞猜', '赛程', '活动', '名望', '选手', '胜')):
            seen_rules.add(s)
            rules.append(s[:220])
        if len(rules) >= 10:
            break

    # Arena maps are the only client maps with a battle grid and an arena
    # model; the cup schedule itself only stores a story quest id (no map id),
    # so we expose the candidate maps and say so explicitly.
    arena_maps = []
    client_maps = {r['id']: r for r in table('map')}
    for m in WORLD.get('maps', []):
        cm = client_maps.get(m['id'], {})
        model = str(cm.get('model') or m.get('model') or '')
        name = (m.get('stages') or [None])[0] or m.get('name') or f"地图 {m['id']}"
        if re.search(r'(?i)arena', model) and (m.get('cells') or []):
            arena_maps.append({'id': m['id'], 'name': name, 'model': model,
                               'width': m['width'], 'height': m['height'],
                               'cells': len(m['cells'])})
    if not arena_maps:
        for m in WORLD.get('maps', []):
            if 120 <= len(m.get('cells') or []) <= 260:
                arena_maps.append({'id': m['id'], 'name': (m.get('stages') or [None])[0] or m['name'],
                                   'model': m.get('model') or '', 'width': m['width'],
                                   'height': m['height'], 'cells': len(m['cells'])})
                if len(arena_maps) >= 3:
                    break
    # Default battle environment. The schedule has no map id, but three
    # independent client facts point at the arena: every cup fighter is a
    # 「角斗士-…」 unit_npc, the only weather built for gladiators is
    # 「角斗场特制_炽热气氛」 (its aura speciality says 角斗士才拥有), and
    # the only arena map with a battle grid is stage_lyc-arena-*.
    weathers = table('weather')
    arena_weather = next((w for w in weathers if '角斗场' in str(w.get('editor_name') or '')), None)
    gladiators = sum(1 for t in teams for m in t['members'] if '角斗士' in m.get('editorName', ''))
    total = sum(len(t['members']) for t in teams)
    aura = {}
    if arena_weather and arena_weather.get('aura_speciality'):
        aura = next((r for r in table('speciality') if r['id'] == arena_weather['aura_speciality']), {})
    environment = {
        'mapId': arena_maps[0]['id'] if arena_maps else None,
        'mapName': arena_maps[0]['name'] if arena_maps else '',
        'weatherId': (arena_weather or {}).get('id'),
        'weatherName': (arena_weather or {}).get('name') or '',
        'weatherDesc': plain((arena_weather or {}).get('desc')),
        'auraSpeciality': (arena_weather or {}).get('aura_speciality') or 0,
        'evidence': [
            f'{gladiators}/{total} 名选手的 unit_npc.editor_name 为「角斗士-…」',
            f'weather#{(arena_weather or {}).get("id")}「{(arena_weather or {}).get("editor_name", "")}」，'
            f'光环 speciality#{aura.get("id", "")}「{aura.get("editor_name", "")}」',
            (f'map#{arena_maps[0]["id"]}「{arena_maps[0]["model"]}」是客户端唯一带战斗网格的 arena 地图'
             if arena_maps else '未找到带网格的 arena 地图'),
        ],
        'caveat': '赛程只存剧情关卡 id、不存地图 id，以上为多条客户端数据交叉推定的默认环境，页面上可改选其他地图或天气。',
    }
    match_types = [{'id': r['id'], 'name': r.get('name'), 'battleCount': _num(r.get('battle_count')),
                    'winScore': _num(r.get('win_score')), 'winNextId': _num(r.get('win_next_id')),
                    'loseNextId': _num(r.get('lose_next_id'))}
                   for r in table('online_match_activity_type')]

    data = {
        'v': 2,
        'title': '乐土群星杯',
        'clientName': '斗蛐蛐活动版2',
        'activities': activities, 'modes': modes, 'teams': teams,
        'schedules': schedules, 'bets': bets, 'rules': rules,
        'arenaMaps': arena_maps, 'matchTypes': match_types, 'environment': environment,
        'facing': {'source': 'arena_season_template.unit_facing（竞技场赛季表，非群星杯专属）',
                   'values': dict(_SEASON_FACING)},
        'spawnEditable': True,
        'eliteCompensation': {
            'skillId': 16046,
            'source': 'unit_personality_skill → skill_group_id 2 / star 1 → skill 16046',
            'effects': ['PREWAR_MODIFY_ATTRIBUTE 生命+80%', 'MODIFY_ATTRIBUTE 物攻+10%',
                        'MODIFY_ATTRIBUTE 魔攻+10%', 'MODIFY_ATTRIBUTE 物防+10%',
                        'MODIFY_ATTRIBUTE 魔防+10%'],
            'alternative': 'skill 15309「注册角斗士」同组，只有移除红牌，无任何属性加成',
            'eliteBuff': 'mission_buff_pool buff_id 9686 / 1130「[通用环境效果]全体敌人升级为精英属性」',
            'evidence': '群星杯 192 场赛程的 buffDetails 不含 9686 / 1130；选手使用 unit_modify_level 60 级成长表',
            'default': 'disabled',
            'fighters': sum(1 for tt in teams for mm in tt['members'] if mm.get('eliteCompensation')),
        },
        'speedNote': SPEED_NOTE,
        'resultAvailability': {
            'hasOfficialResults': False,
            'searched': ['online_match_* 全族配置表', 'output/archive 文本与对象',
                         'data/raw/pages 归档公告', '官方活动公告与维护公告（联网检索）'],
            'reason': '比赛由服务器实时结算，客户端只存赛程/队伍/赔率/增益；官方公开资料只公布活动规则与奖励，不公布逐场胜负与回合数。',
            'alternative': '本模拟器按客户端阵容、技能与赛程增益做离线推演，可复现地给出每场胜负与持续回合数（非官方赛果）。',
        },
        'sources': [
            'online_match_activity / online_match_activity_mode：4 期活动与 31 个赛制、轮次',
            'online_match_activity_regular_team / online_match_regular_team：63 支预设队伍与 unit_npc_ids',
            'online_match_activity_server_schedule：204 场赛程（双方队伍、日期、分组、mission_buff_pool_ids、unit_status_data）',
            'unit_npc + unit + unit_modify_level：选手 60 级五维、速度、移动/跳跃、普攻与技能',
            'skill：技能射程 / 倍率 / 冷却 / ai_skill_order；mission_buff_pool：赛事增益',
            'online_match_activity_bet_option：押注赔率；text：活动规则说明',
            'unit_npc.personality_id + unit_personality / unit_personality_skill：个性技能；skill：全量技能（普攻/主动/反应/队长/个性）',
            'online_quest + mission_battle_param：每场赛程对应的剧情关卡、胜利/失败文本与回合上限',
            'mission_buff_pool + buff：赛事增益说明；buff：选手精神状态（unit_status_data）名称与效果',
            'map / data/world-data.js：竞技场候选地图（赛程本身不存地图 id）',
        ],
        'notes': [
            '选手属性直接取自客户端 60 级成长表（unit_modify_level），与角色图鉴的满级满星口径不同，数值明显更高；让赛事队伍互相对阵最合理。',
            '职业类别由 unit.profession → profession.category 还原（与玩家职业克制表同一套 1–6 类别），参与克制计算。',
            '赛事增益（mission_buff_pool，按 target 1=队伍一 / 2=队伍二 / 3=双方）与选手精神状态（unit_status_data）'
            '在开局作为 buff 施加，由机制引擎按 buff → speciality 逐条结算。',
            '选手技能只取 unit_npc 的 melee_skill / skill_ids / reactive_skill / leader_skill / personality_id+star，'
            '不再混入 unit 表（玩家角色模板）的 default_skills / feature_skills / skill_ids；用 skill.type 区分主动（1）/衍生（2）/被动（3），'
            '并按 skill_attached_passive_id / idskill_follow / skill_cast_id / overwritten_skill_id 递归解析附属被动与连携技能链。',
            '个性技能按 unit_npc.star 取每个技能组中星级不超过选手星级的最高档；赛事专用个性（unit_npc.personality_id）与玩家角色个性不同，不做替换。'
            '技能名优先取客户端 name，缺失时回退 editor_name / desc；每条技能附带 speciality 效果类型数量与列表，便于核对它实际做什么。',
            '「精英属性补回」(skill 16046，生命+80% / 攻防各+10%) 由 unit_personality_skill 的第 2 技能组挂在 82 个角斗士个性上；'
            '它是对「全体敌人升级为精英属性」环境增益（buff 9686 / 1130）的属性补正，而群星杯 192 场赛程的增益池均不含该 buff，'
            '因此赛事选手默认不启用这个补正（页面可手动开启对照），阵容里保留为资料并标注未生效原因。',
            '客户端没有「赛事专属携带技能表」：权威来源是 unit_npc 的 melee_skill / skill_ids / reactive_skill / leader_skill / personality_id / boss_skill_sequence（多数选手只直接带 1–4 个技能），'
            '其余技能通过 SKILL_GROUP / TACTICS_SKILL_GROUP 抉择选项与 CAST_SKILL / GET_EXTRA_SKILL / REPLACE_SKILL 等效果在局内获得，已递归解析并分角色标注。'
            'unit_phantom_skill.slot1–6 是同一 unit_id 的玩家版 60 级满星技能槽，仅导出为 referenceSlots 供对照，不并入赛事编组。',
            '赛程表只有 mission_id（指向 online_quest 剧情关卡，8 个），没有逐场战斗地图 id 或选手站位；map.data 的 protobuf 只编码每个地形格（field 3），不含出生点，'
            'arena_season_template 的 arena_map_mission_id / unit_facing 属于竞技场赛季而非群星杯。因此每场地图与站位均为推定，页面可直接编辑每名选手的初始格子并即时重算。',
            '押注赔率仅供对照模拟结果，不参与胜负计算；比赛真实结果由服务器结算，这里是用客户端公开数据做的离线推演。',
            '已逐场查找过胜负结果、持续回合数：客户端配置表（online_match_* 全族）、归档文本与公开活动公告都没有逐场战绩字段——'
            '官方说明为“看准赛程押注、赛后结算名望”，比赛由服务器实时演算并在游戏内回放，结果不下发到配置表。'
            '因此本项目不编造赛果；页面上提供的是用本模拟器按客户端阵容/规则跑出的可复现推演结果与回合数。',
            '赛程的 mission_id 指向剧情关卡（风雪欲来 / 决斗 / 推演1 等），不是战斗地图 id；默认环境（竞技场地图 + 炽热气氛天气）'
            '由「角斗士」选手、角斗场特制天气与唯一带网格的 arena 地图三条数据交叉推定，见 environment.evidence。',
            '选手的全部技能（含被动、反应、队长、个性）由 data/battle-mech.js 的机制引擎按 speciality 结算；'
            '引擎未覆盖的效果类型与 Lua 条件函数会在页面「机制覆盖」中逐项列出。',
        ],
    }
    OUT.write_text('window.WIKI_MATCH_CUP=' + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n',
                   'utf8')
    fighters = sum(len(t['members']) for t in teams)
    usable = sum(1 for t in teams for m in t['members'] for s in m['skills'] if s.get('usable'))
    print(f'群星杯数据：{len(activities)} 期活动 / {len(modes)} 赛制 / {len(teams)} 支队伍 '
          f'({fighters} 名选手、{usable} 个可用技能) / {len(schedules)} 场赛程 / '
          f'{len(bets)} 组赔率 / {len(rules)} 条规则，{OUT.stat().st_size/1024:.0f} KiB → {OUT.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
