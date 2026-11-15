"""Export the data the offline auto-battle simulator needs.

Everything comes from the local client config tables already unpacked under
output/archive/library/当前版本/配置表 plus the generated wiki index:

  roster   playable characters (online_role_unit via data/panel-data.js)
           * 满级满星 stats from the character archive (data/index.js)
           * mobility / jump_up / jump_down / move_type from `unit`
           * 普攻 (unit.melee_skill), 初始技能 (unit.default_skills) and the
             two choices of every skill-line rank
             (online_unit_rank_modify_rank.skill1_id / skill2_id)
  skills   range_min / range_max / range_tag, target_method / target_select /
           target_width, damage_type, damage_factor, cooldown, ai_skill_order
  rules    profession restraint, high-ground modifier and crit constants from
           data/combat-data.js (itself extracted from the client)

The simulator itself (battle-sim-core.js) documents which client mechanics are
approximated. Writes data/battle-sim.js (window.WIKI_BATTLE_SIM).

    python -X utf8 scripts/extract_battle_sim.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / 'output' / 'archive' / 'library' / '当前版本' / '配置表'
OUT = ROOT / 'data' / 'battle-sim.js'

ACTIVE_TYPES = {2, 6, 9}            # 治疗 / 伤害（含普攻）/ 混合
ATTACK_DAMAGE = {1, 2, 4}            # 物理 / 魔法 / 穿透·固定
HEAL_DAMAGE = 3
TARGET_ENEMY = {1, 3, 10}            # 选择敌人 / 敌我 / 己方附近敌人
TARGET_ALLY = {2, 15, 16}            # 选择我方 / 己方附近友方 / 己方任意单位
TARGET_GROUND = {4, 5, 6, 11, 13, 14, 17}
TARGET_SELF = {7, 8}                 # 原地 / 仅自己
TARGET_DIRECTION = {9}


def load_js(name, var):
    text = (ROOT / 'data' / name).read_text('utf8')
    marker = 'window.' + var + '='
    start = text.index(marker) + len(marker) if marker in text else text.index('=') + 1
    return json.JSONDecoder().raw_decode(text[start:])[0]


def table(name):
    for folder in [CFG / 'lua_dbtemplateonline', CFG / 'lua_dbtemplate',
                   *[p for p in CFG.iterdir() if p.is_dir()]]:
        p = folder / f'{name}.json'
        if p.is_file():
            try:
                return json.loads(p.read_text('utf8'))
            except (ValueError, OSError):
                pass
    return []


def plain(text):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', str(text or ''))).strip()


def _num(value, default=0):
    try:
        return int(float(str(value if value not in (None, '') else default)))
    except (TypeError, ValueError):
        return default


def ints(value):
    return [int(x) for x in re.split(r'[|,;]', str(value or '')) if x.strip().isdigit()]


def area_of(row, desc):
    """Map target_select / target_width (+ wording) onto a simulator area."""
    sel, width = row.get('target_select') or 1, row.get('target_width') or 1
    if sel == 4:
        return {'type': 'rect', 'len': max(1, width), 'wide': 3}
    if sel == 1 and width > 1:
        return {'type': 'radius', 'r': width - 1}
    m = re.search(r'(?:自身|目标)?范围(\d+)格内所有|(\d+)圈内所有', desc)
    if m:
        return {'type': 'radius', 'r': int(m.group(1) or m.group(2))}
    return {'type': 'single'}


def hits_of(desc):
    """Client skill text uses several multi-hit wordings; recognise them all.

    「造成3次60%的伤害」「进行3次攻击，每次造成50%伤害」
    「造成1次20%的伤害，3次50%的伤害」「进行3段连击」
    """
    text = desc or ''
    mixed = re.findall(r'(\d+)\s*次\s*(?:的)?\s*(\d+)\s*%', text)
    if mixed:
        return min(20, sum(int(n) for n, _ in mixed))
    for pattern in (r'进行\s*(\d+)\s*次攻击', r'造成\s*(\d+)\s*次\s*(?:攻击|伤害)',
                    r'攻击\s*(\d+)\s*次', r'(\d+)\s*段\s*(?:攻击|伤害|连击)',
                    r'造成\s*(\d+)\s*次'):
        m = re.search(pattern, text)
        if m:
            return min(20, int(m.group(1)))
    return 1


_PERSONALITY = None


def personality_skill_ids(personality_id, star):
    """Skills a personality grants at a given star.

    unit_personality_skill lists every skill group once per star tier; the
    unit gets, for each group, the highest tier whose star <= the unit's star.
    """
    global _PERSONALITY
    if _PERSONALITY is None:
        _PERSONALITY = defaultdict(list)
        for r in table('unit_personality_skill'):
            _PERSONALITY[r.get('idunit_personality')].append(r)
    best = {}
    for r in _PERSONALITY.get(personality_id, []):
        if (r.get('star') or 0) > (star or 0):
            continue
        g = r.get('skill_group_id') or 0
        if g not in best or (r.get('star') or 0) > (best[g].get('star') or 0):
            best[g] = r
    return [best[g]['skill_id'] for g in sorted(best) if best[g].get('skill_id')]


def unit_kit(unit, *, basic=None, actives=(), star=5, personality_id=None, extra_reactive=None,
             extra_leader=None, ai_by_order=False, ai_sorted=False, boss_mode=False,
             boss_sequence=(), skill_order=()):
    """Every skill id the client attaches to a unit, grouped by role.

    The mechanics engine resolves passives, reactions, leader auras and
    personality skills from these ids (data/battle-mech.js), so nothing is
    dropped just because it is not an active damage / heal skill.
    """
    pid = personality_id if personality_id is not None else unit.get('personality_id')
    return {
        'basic': basic or unit.get('melee_skill') or 0,
        'actives': [s for s in actives if s],
        'initial': ints(unit.get('default_skills')),
        'reactive': [s for s in (extra_reactive, unit.get('reactive_skill')) if s],
        'leader': [s for s in (extra_leader, unit.get('leader_skill')) if s],
        'feature': ints(unit.get('feature_skills')),
        'personality': personality_skill_ids(pid, star) if pid else [],
        'tp': unit.get('tp') or 0, 'tpMax': unit.get('tp_max') or 0,
        # unit_tag ids (伊利亚 / 骑士同盟 / 召唤物 / 大型单位 …) used by Lua conditions.
        'tags': ints(unit.get('unit_tag_ids')),
        # unit_npc AI columns: the client's AIMachine uses skills in the
        # DECLARED order for 角斗士/BOSS units (skill_by_order / skill_orders).
        'aiByOrder': bool(ai_by_order), 'aiSorted': bool(ai_sorted),
        'bossMode': boss_mode, 'bossSequence': list(boss_sequence),
        'skillOrder': list(skill_order),
    }


def skill_entry(row, kind, rank=0, side=0):
    desc = plain(row.get('desc'))
    st, dt, tm = row.get('skill_type'), row.get('damage_type'), row.get('target_method')
    heal = dt == HEAL_DAMAGE
    attack = dt in ATTACK_DAMAGE and (row.get('damage_factor') or 0) > 0
    usable = st in ACTIVE_TYPES and (attack or heal) and (row.get('damage_factor') or 0) > 0
    if not usable:
        # Passives / supports are listed for completeness but never simulated;
        # keep them tiny so the lazily loaded data file stays small.
        return {'id': row['id'], 'name': row.get('name') or f'技能 {row["id"]}', 'kind': kind,
                'rank': rank, 'side': side, 'usable': False, 'skillType': st, 'desc': desc[:48]}
    if tm in TARGET_ENEMY:
        aim = 'enemy'
    elif tm in TARGET_ALLY:
        aim = 'ally'
    elif tm in TARGET_SELF:
        aim = 'self'
    elif tm in TARGET_DIRECTION:
        aim = 'direction'
    elif tm in TARGET_GROUND:
        aim = 'ground'
    else:
        aim = 'other'
    return {
        'id': row['id'], 'name': row.get('name') or f'技能 {row["id"]}', 'kind': kind,
        'rank': rank, 'side': side,
        'usable': bool(usable), 'heal': heal,
        'skillType': st, 'damageType': dt, 'targetMethod': tm, 'aim': aim,
        'rangeMin': row.get('range_min') or 0, 'rangeMax': row.get('range_max') or 0,
        # range_select (target_select) decides the cast shape; range_tag is
        # only the NONE / MELEE / RANGED tag read by active_param conditions.
        'targetSelect': _num(row.get('target_select')) or 1,
        'shape': 'cross' if _num(row.get('target_select')) == 2 else 'diamond',
        'arc': _num(row.get('range_tag')) == 3,
        'area': area_of(row, desc),
        'factor': row.get('damage_factor') or 0,
        'physic': row.get('physic_factor') or 0, 'spell': row.get('spell_factor') or 0,
        'cooldown': row.get('cooldown') or 0, 'order': row.get('ai_skill_order') or 0,
        'hits': hits_of(desc), 'ignoreDef': dt == 4,
        'attackUp': row.get('attack_up') or 0, 'attackDown': row.get('attack_down') or 0,
        'desc': desc[:160],
    }


def main():
    if not CFG.is_dir():
        print('跳过自动对局数据：缺少本地客户端配置表（先完成一次「本地更新」）。')
        return 0
    panel = load_js('panel-data.js', 'WIKI_PANEL_DATA')
    combat = load_js('combat-data.js', 'WIKI_COMBAT_DATA')
    world = load_js('world-data.js', 'WIKI_WORLD_DATA')
    index = load_js('index.js', 'WIKI_INDEX')
    # The archive writes「伊南娜•铃兰之剑」, the client「伊南娜·铃兰之剑」.
    norm = lambda s: re.sub(r'[·•・‧]', '·', str(s or '')).strip()
    by_name = {norm(p['name']): p for p in index['pages'] if p.get('type') == 'character' and not p.get('redirect')}

    units = {r['id']: r for r in table('unit')}
    skills = {r['id']: r for r in table('skill')}
    ranks = defaultdict(list)
    for r in table('online_unit_rank_modify_rank'):
        ranks[r['idonline_unit_rank_modify']].append(r)
    categories = {c['id']: c['name'] for c in combat.get('categories', [])}

    roster, missing = [], []
    for c in panel['characters']:
        if c.get('enabled') is False:
            continue
        page = by_name.get(norm(c['name']))
        stats = (page or {}).get('stats') or {}
        unit = units.get(c.get('unitId'), {})
        if not page or not stats.get('生命'):
            missing.append(c['name'])
            continue

        def num(key, fallback=0):
            try:
                return int(str(stats.get(key) or fallback).replace(',', ''))
            except ValueError:
                return fallback

        entries = []
        if unit.get('melee_skill') in skills:
            entries.append(skill_entry(skills[unit['melee_skill']], 'basic'))
        for sid in ints(unit.get('default_skills')):
            if sid in skills:
                entries.append(skill_entry(skills[sid], 'initial'))
        for r in sorted(ranks.get(c.get('rankModify'), []), key=lambda x: x['rank']):
            for side, key in ((1, 'skill1_id'), (2, 'skill2_id')):
                sid = r.get(key)
                if sid in skills:
                    entries.append(skill_entry(skills[sid], 'rank', r['rank'], side))
        prof = c.get('professionCategory') or 6
        kit = unit_kit(unit, star=5)
        kit['ranks'] = [[r['rank'], side, r.get(key)]
                        for r in sorted(ranks.get(c.get('rankModify'), []), key=lambda x: x['rank'])
                        for side, key in ((1, 'skill1_id'), (2, 'skill2_id')) if r.get(key) in skills]
        kit['unitId'] = c.get('unitId')
        roster.append({
            'kit': kit,
            'key': c['key'], 'name': c['name'], 'pageId': page['id'],
            'rarity': c.get('rarity'), 'prof': prof, 'profName': categories.get(prof, '无属性'),
            'avatar': page.get('avatar') or page.get('sprite') or '', 'sprite': page.get('sprite') or '',
            'stats': {'hp': num('生命'), 'patk': num('物攻'), 'matk': num('魔攻'),
                      'pdef': num('物防'), 'mdef': num('魔防'),
                      'spd': num('敏捷', c.get('speed') or unit.get('speed') or 100)},
            'move': {'mob': unit.get('mobility') or 3, 'up': unit.get('jump_up') or 2,
                     'down': unit.get('jump_down') or 2, 'type': unit.get('move_type') or 1},
            'skills': entries,
        })

    restraints = {f"{r['from']}-{r['to']}": r['factor'] for r in combat.get('restraints', [])}
    consts = combat.get('constants', {})
    terrain = {}
    for f in world.get('mapMeta', {}).get('fieldTypes', []):
        cost = f.get('mobility')
        terrain[str(f['id'])] = {'name': f.get('name') or f'地形 {f["id"]}',
                                 'cost': cost if cost is not None else 10,
                                 'pit': bool(f.get('pit')), 'type': f.get('type') or ''}

    # Height sanity: adjacent passable cells usually differ by small steps.
    deltas = Counter()
    for m in world.get('maps', []):
        grid = {(x, y): h for x, y, h, t in m.get('cells', []) if not terrain.get(str(t), {}).get('pit')}
        for (x, y), h in grid.items():
            for dx, dy in ((1, 0), (0, 1)):
                n = grid.get((x + dx, y + dy))
                if n is not None and n != h:
                    deltas[min(abs(n - h), 9)] += 1

    usable = sum(1 for u in roster for s in u['skills'] if s['usable'])
    data = {
        'v': 1,
        'roster': roster,
        'restraints': restraints,
        'categories': categories,
        'highGround': {'up': combat.get('highGround', {}).get('up', 15),
                       'down': combat.get('highGround', {}).get('down', -10), 'minDiff': 2},
        'crit': {'chance': (consts.get('CritBaseChance') or {}).get('value', 10),
                 'damage': (consts.get('CritBaseDamage') or {}).get('value', 30)},
        'terrain': terrain,
        'sources': [
            'online_role_unit / data/panel-data.js：可上场角色与技能轴',
            'data/index.js：角色图鉴满级满星六维（含速度）',
            'unit：mobility / jump_up / jump_down / move_type / melee_skill / default_skills',
            'online_unit_rank_modify_rank：各阶左 / 右技能',
            'skill：range_* / target_* / damage_type / damage_factor / cooldown / ai_skill_order',
            'profession_restrain → speciality：职业克制；const_param#64/#129：暴击；高低差修正',
            'field_type：地形通行消耗与深水 / 禁行（坑）',
        ],
    }
    OUT.write_text('window.WIKI_BATTLE_SIM=' + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n',
                   'utf8')
    print(f'自动对局数据：{len(roster)} 名角色，{usable} 个可模拟的主动技能，'
          f'{OUT.stat().st_size / 1024:.0f} KiB → {OUT.relative_to(ROOT)}')
    if missing:
        print(f'  未匹配到图鉴属性 {len(missing)} 名：{"、".join(missing[:8])}{" …" if len(missing) > 8 else ""}')
    print('  相邻格高差分布（非零）：', dict(sorted(deltas.items())))
    return 0


if __name__ == '__main__':
    sys.exit(main())
