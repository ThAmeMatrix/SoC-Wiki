"""Export client map and battle-AI data for the offline wiki.

    python -X utf8 scripts/extract_world_data.py [--dry-run]

Reads the decrypted client configuration tables (local archive first, then the
installed game) and writes ``data/world-data.js``:

* maps   - ``map`` metadata joined with ``weather`` / ``sound``, plus the
           decoded protobuf grid (x, y, terrain, height) for every map that
           has one. Coordinates use the client's own field numbers.
* ai     - ``unit_npc`` auto-battle configuration (skill order, boss skill
           sequence, personality), ``skill.ai_order_param`` Lua scripts and
           ``ai_skill_order`` priorities, joined with readable skill names.

The export is optional: if no client tables are available the existing file is
left untouched so the offline package keeps working.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_CFG = ROOT / 'output' / 'archive' / 'library' / '当前版本' / '配置表'
OUT = ROOT / 'data' / 'world-data.js'
CODE_OUT = ROOT / 'data' / 'client-code.js'
ENHANCE_OUT = ROOT / 'data' / 'enhance-data.js'


def table(name: str):
    for folder in [ARCHIVE_CFG / 'lua_dbtemplateonline', ARCHIVE_CFG / 'lua_dbtemplate',
                   *[p for p in ARCHIVE_CFG.iterdir() if p.is_dir()]] if ARCHIVE_CFG.is_dir() else []:
        p = folder / f'{name}.json'
        if p.is_file():
            try:
                return json.loads(p.read_text('utf8'))
            except (ValueError, OSError):
                pass
    # Fall back to the installed client bundles.
    try:
        sys.path.insert(0, str(ROOT / 'scripts'))
        from extract_battle_rules import Tables  # noqa: E402
        from socdecode.client import game_root  # noqa: E402
        from socdecode.config import game_path  # noqa: E402
        tables = Tables(game_root(game_path()), 'auto')
        try:
            return tables.get(name)
        finally:
            tables.close()
    except Exception:
        return []


def varint(buf: bytes, i: int):
    value = shift = 0
    while i < len(buf):
        b = buf[i]
        i += 1
        value |= (b & 0x7f) << shift
        if b < 0x80:
            return value, i
        shift += 7
    return value, i


def proto_fields(buf: bytes):
    out = []
    i = 0
    while i < len(buf):
        key, i = varint(buf, i)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, i = varint(buf, i)
        elif wire == 2:
            length, i = varint(buf, i)
            value = buf[i:i + length]
            i += length
        elif wire == 5:
            value = buf[i:i + 4]
            i += 4
        else:
            break
        out.append((number, wire, value))
    return out


def decode_grid(raw: str):
    """``map.data`` is a protobuf message with repeated field 3 cell records.

    Each cell has: 1 = x (even numbers, 2 units per tile), 3 = y, 2 = height /
    variant, 4 = terrain type. Fields omitted by protobuf mean zero.
    """
    if not raw:
        return []
    buf = raw.encode('latin1', 'ignore')
    # Compact tuples [x, y, h, terrain] instead of objects: 125k cells would
    # otherwise add several MB to the offline package.
    cells = []
    for number, wire, value in proto_fields(buf):
        if number != 3 or not isinstance(value, bytes):
            continue
        record = {n: v for n, w, v in proto_fields(value) if w == 0}
        # Both axes use a 2-unit stride in the client's protobuf; dividing
        # only x left every other row visually empty.
        cells.append([record.get(1, 0) // 2, record.get(3, 0) // 2,
                      record.get(2, 0), record.get(4, 0)])
    return cells


def id_list(raw):
    return [int(x) for x in str(raw or '').split('|') if x.strip().isdigit()]


def plain(value):
    return re.sub(r'<[^>]+>', '', str(value or '')).strip()


# Human-readable labels for the scene tokens baked into map model names.
# These come from the client's own naming convention (stage_<biome>-<place>-<time>-<id>).
SCENE_TOKENS = {
    'city': '城市', 'plain': '平原', 'mountain': '山地', 'desert': '沙漠',
    'marsh': '沼泽', 'cave': '洞窟', 'interior': '室内', 'snow': '雪原',
    'forest': '森林', 'ruin': '遗迹', 'coast': '海岸', 'sea': '海域',
    'da': '白天', 'ni': '夜晚', 'du': '黄昏', 'ra': '雨天', 'os': '野外',
    'cp': '营地', 'ug': '地下', 'ca': '城堡', 'spcl': '特殊', 'in': '室内',
}


def scene_label(model):
    parts = [SCENE_TOKENS[p] for p in re.split(r'[-_]', str(model or '')) if p in SCENE_TOKENS]
    seen, out = set(), []
    for p in parts:
        if p not in seen:
            seen.add(p); out.append(p)
    return ' · '.join(out)


def build_maps():
    maps = table('map')
    if not maps:
        return [], {}
    weather = {r['id']: r for r in table('weather')}
    weather_types = {r['id']: r.get('name') or str(r['id']) for r in table('weather_type')}
    sounds = {r['id']: r.get('name') or '' for r in table('sound')}
    # ``field_type`` is the client's terrain enum; map cell field 4 is its id.
    field_types = {r['id']: {
        'id': r['id'], 'name': r.get('name') or '', 'desc': plain(r.get('desc')),
        'mobility': r.get('mobility'), 'type': r.get('type') or '',
        'pit': (r.get('type') or '') in ('Water', 'Forbidden'),
        'icon': r.get('icon') or '',
        # Water / Forbidden cells are pits ("可被推落" / "不可进入"): their
        # field2 stores pit depth, NOT a stackable height. The 3D renderer must
        # sink them below surrounding ground instead of drawing solid columns.
        'pit': (r.get('type') or '') in ('Water', 'Forbidden'),
        'image': f"assets/terrain/{r.get('icon') or ''}.png" if r.get('icon') else '',
        'topImage': f"assets/terrain/top/{r.get('icon') or ''}.png" if r.get('icon') else '',
        'wallImage': f"assets/terrain/wall/{r.get('icon') or ''}.png" if r.get('icon') else '',
    } for r in table('field_type')}
    # Map id -> Chinese stage/area names from the client's own tables.
    stage_names = defaultdict(list)
    for r in table('mini_sandbox_capital_area'):
        name = plain(r.get('name'))
        if r.get('map_id') and name and name not in stage_names[r['map_id']]:
            stage_names[r['map_id']].append(name)
    for r in table('online_rogue_map_chain'):
        name = plain(r.get('name'))
        for sid in id_list(r.get('map_ids')):
            if name and name not in stage_names[sid]:
                stage_names[sid].append(name)
    for r in table('capital_area'):
        # capital_area.map_name is a scene model; match it to the map table.
        if r.get('map_name'):
            model = r['map_name']
            for m in maps:
                if m.get('model') == model:
                    name = plain(r.get('name'))
                    if name and name not in stage_names[m['id']]:
                        stage_names[m['id']].append(name)
                    break
    # field_status describes terrain CONDITIONS (燃烧 / 冰冻 / 圣域 ...);
    # include their text in the searchable blob even though map cells only
    # reference field_type ids.
    status_descs = [plain(x.get('desc')) for x in table('field_status')]
    status_text = ' '.join(d for d in status_descs if d)[:20000]
    rows = []
    terrain_counts = Counter()
    for r in maps:
        cells = decode_grid(r.get('data') or '')
        for c in cells:
            terrain_counts[c[3]] += 1
        w = weather.get(r.get('weather')) or {}
        rows.append({
            'id': r['id'], 'name': r.get('name') or '', 'model': r.get('model') or '',
            'scene': scene_label(r.get('model')),
            'stages': stage_names.get(r['id'], [])[:6],
            'terrainNames': sorted({field_types[k]['name'] for k in
                                    {c[3] for c in cells} if k in field_types}),
            'terrainDescs': sorted({field_types[k]['desc'] for k in
                                    {c[3] for c in cells} if k in field_types and field_types[k]['desc']}),
            'timeSlot': r.get('id_timeslot'), 'weatherId': r.get('weather'),
            'weather': w.get('name') or '', 'weatherDesc': plain(w.get('desc')),
            'weatherType': weather_types.get(w.get('type'), ''),
            'bgm': sounds.get(r.get('bgm')) or (str(r.get('bgm')) if r.get('bgm') else ''),
            'ambient': r.get('ambient'), 'cells': cells,
            'width': max((c[0] for c in cells), default=0) + 1,
            'height': max((c[1] for c in cells), default=0) + 1,
        })
    meta = {
        'terrainTypes': [dict(field_types.get(k, {'id': k, 'name': f'地形 {k}',
                          'desc': '', 'mobility': None, 'type': '', 'icon': ''}), cells=v)
                         for k, v in terrain_counts.most_common()],
        'fieldTypes': list(field_types.values()),
        'weatherTypes': [{'id': k, 'name': v} for k, v in weather_types.items()],
        'namedMaps': sum(1 for r in rows if r['stages']),
        'terrainStatuses': [{'name': x.get('name') or '', 'desc': plain(x.get('desc'))}
                            for x in table('field_status') if plain(x.get('desc'))],
    }
    return rows, meta


# Every config column that stores client-side Lua. ``kind`` groups them for
# the browser; ``label`` is the Chinese name the client uses for the field.
CODE_FIELDS = (
    ('speciality', 'active_param', '特效触发条件', 'speciality'),
    ('speciality', 'dynamic_param', '特效动态参数', 'speciality'),
    ('speciality', 'skill_active_param', '技能特效触发条件', 'speciality'),
    ('buff', 'active_param', '状态触发条件', 'buff'),
    ('skill', 'target_param', '目标选择脚本', 'skill'),
    ('skill', 'cast_param', '施放条件脚本', 'skill'),
    ('skill', 'active_param', '技能主动条件', 'skill'),
    ('skill', 'ai_order_param', 'AI 技能决策', 'skill'),
    ('skill', 'target_order_param', 'AI 目标排序', 'skill'),
    ('skill', 'icon_effects_active_param', '图标特效条件', 'skill'),
)
AI_FIELDS = {'ai_order_param', 'target_order_param', 'icon_effects_active_param'}


def _row_name(table_name, row):
    for key in ('name', 'editor_name', 'desc'):
        value = plain(row.get(key))
        if value and not value.startswith('<'):
            return value[:80]
    return f'{table_name} #{row.get("id")}'


def build_client_code():
    """Collect and de-duplicate every Lua snippet in the client config tables."""
    groups = {}
    seen = {}
    for table_name, field, label, entity in CODE_FIELDS:
        rows = table(table_name)
        for row in rows:
            code = str(row.get(field) or '').strip()
            if len(code) < 20:
                continue
            rid = row.get('id')
            digest = hashlib.sha1(code.encode('utf8', 'replace')).hexdigest()[:12]
            item = {'id': rid, 'name': _row_name(table_name, row),
                    'field': field, 'table': table_name, 'label': label,
                    'type': row.get('type'), 'code': code,
                    'ai': field in AI_FIELDS}
            if digest in seen:
                seen[digest].append(f'{table_name}#{rid}')
                continue
            item['refs'] = [f'{table_name}#{rid}']
            item['hash'] = digest
            seen[digest] = item['refs']
            groups[digest] = item
    out = list(groups.values())
    return out, {
        'fields': [{'table': a, 'field': b, 'label': c} for a, b, c, _ in CODE_FIELDS],
        'unique': len(out), 'references': sum(len(x['refs']) for x in out),
        'ai': sum(1 for x in out if x['ai']),
    }


def build_battle_power():
    """Client constants behind the out-of-battle combat-power readout.

    ``const_param#132 OnlineRoleUnitBattlePowerCoefficient = "120|200"`` gives
    the two per-stat divisors used to turn raw panel stats into score points;
    ``battle_power_coefficient`` and ``unit_rarity.battle_power_adjust`` are
    percent multipliers for profession/weapon and rarity. The exact assembly
    is not stored in the config tables (it lives in compiled IL2CPP code), so
    the calculator states the derived formula explicitly instead of guessing
    silently.
    """
    const = next((r for r in table('const_param')
                  if r.get('type') == 'OnlineRoleUnitBattlePowerCoefficient'), {})
    divisors = [int(x) for x in str(const.get('sparam') or '').split('|') if x.strip().isdigit()]
    coefficients = [{'profession': r.get('profession_category'), 'weaponType': r.get('weapon_type'),
                     'percent': r.get('percent')} for r in table('battle_power_coefficient')]
    rarity = {str(r['id']): {'name': r.get('name'), 'percent': r.get('battle_power_adjust')}
              for r in table('unit_rarity')}
    hp_weight = (divisors or [120, 200])[0]
    other_weight = (divisors or [120, 200])[1]
    quest_power = [r['enemy_fight_power'] for r in table('online_quest_level')
                  if isinstance(r.get('enemy_fight_power'), (int, float))]
    return {
        'divisors': divisors or [120, 200],
        'hpWeight': hp_weight, 'otherWeight': other_weight,
        'constId': const.get('id'), 'constName': const.get('type'),
        'coefficients': coefficients, 'rarity': rarity,
        'formula': '战斗力 = ⌊ ( (物攻 + 魔攻) × 120‰ + (物防 + 魔防) × 200‰ ) '
                   '× 稀有度修正 × 职业修正 ⌋',
        'coefficientMeaning': 'const_param#132 的中文名（db_template1.bytes 内嵌说明）为'
                              '「网游角色战力系数 (攻击|防御)」，即 120 = 攻击系数、200 = 防御系数；'
                              '此前误读成「生命 / 其它四维」，已更正。',
        'calibration': 'online_quest_level.enemy_fight_power：1 级 100 → 60 级约 2,670 → 80 级 8,552；'
                       'online_guild_challenge_normal_quest.battle_power 500 / 1,000 / 1,500 / 2,000，BOSS 10,000',
        'questPowerCurve': [{'level': i + 1, 'power': v} for i, v in enumerate(quest_power[:80])],
        'reference': {
            'character': '伊南娜·铃兰之剑', 'profession': 5, 'power': 4167,
            'note': '游戏内实测：守望者「小王女」方案的战力显示值，由用户提供，用于定标',
        },
        'empiricalScale': None,
        'evidence': [
            'const_param#132 OnlineRoleUnitBattlePowerCoefficient = "120|200"（iparam=0）；'
            '客户端 db_template1.bytes 里的中文字段说明是「网游角色战力系数(攻击|防御)」，'
            '因此 120 对应攻击、200 对应防御，而不是生命。这是配置表里唯一的战力系数字段。',
            'battle_power_coefficient：按 profession_category / weapon_type 给 95 / 100 / 105 / 110 的 percent。',
            'unit_rarity.battle_power_adjust：普通 95 / 精英 100 / 史诗 105 / 传说 110。',
            'online_quest_level.enemy_fight_power 与 online_guild_challenge_*_quest.battle_power 是关卡侧的参考战力，'
            '不是角色面板换算表。',
            '未在配置表、Lua 片段、global-metadata.dat 或 GameAssembly.dll 字符串中找到把上述常量装配成最终数值的公式；'
            'IL2CPP 编译后的方法名与实现均不可读，因此本地数据不足以唯一确定公式。',
        ],
        'candidates': [
            {'id': 'attack-defence', 'label': '攻击 120‰ / 防御 200‰（按客户端字段说明）',
             'expr': '⌊((物攻+魔攻)×120‰ + (物防+魔防)×200‰) × 稀有度% × 职业%⌋',
             'basis': '依据 db_template1.bytes 的中文说明「网游角色战力系数(攻击|防御)」；'
                      '不含生命。装配公式仍在编译代码中，此式仅按字段语义还原'},
            {'id': 'permille-final', 'label': '千分比权重 × 最终面板（旧解读）',
             'expr': '⌊(生命×120‰ + 其余四维×200‰) × 稀有度% × 职业%⌋',
             'basis': '把 120|200 读作千分比权重；结果与 60 级敌方战力约 2,670 同量级'},
            {'id': 'permille-white', 'label': '千分比权重 × 角色白板',
             'expr': '⌊(白板生命×120‰ + 其余白板四维×200‰) × 稀有度% × 职业%⌋',
             'basis': '同一权重但只取角色成长基础值，不含装备 / 天赋'},
            {'id': 'divisor-final', 'label': '除数法 × 最终面板',
             'expr': '⌊(生命÷120 + 其余四维÷200) × 稀有度% × 职业%⌋',
             'basis': '把 120|200 读作除数（早期实现，量级约 100，远小于关卡参考值）'},
            {'id': 'sum-percent', 'label': '五维总和百分比',
             'expr': '⌊(生命 + 其余四维) ÷ 10 × 稀有度% × 职业%⌋',
             'basis': '不区分五维的简化算法，用于对照'},
        ],
        'source': 'const_param#132 OnlineRoleUnitBattlePowerCoefficient (120|200) · '
                  'battle_power_coefficient · unit_rarity.battle_power_adjust · '
                  'online_quest_level.enemy_fight_power（量级校准）',
    }


def build_ai_priority(skills, npcs, scripts):
    """Describe how the client ranks skills for auto-battle.

    Three layers are visible in the config data:
      1. ``skill.ai_skill_order`` - a static base priority (higher first).
      2. ``skill.ai_order_param`` / ``target_order_param`` - Lua scoring
         snippets that return a weight; large negatives veto a skill.
      3. ``unit_npc`` order flags and ``boss_skill_sequence`` - per-unit
         overrides that bypass scoring entirely.
    """
    order_values = Counter(int(r.get('ai_skill_order') or 0) for r in skills
                           if r.get('ai_skill_order'))
    weights = Counter()
    for s in scripts:
        for value in re.findall(r'return\s+(-?\d+)', s.get('lua') or ''):
            weights[int(value)] += 1
    return {
        'quick': [
            {'title': '怎么选技能', 'steps': ['ai_skill_order：整数基准分，越大越优先',
                'ai_order_param：Lua 按战场状态加减权重', '大负数（−10000）直接否决该技能'],
             'fields': ['ai_skill_order', 'ai_order_param'],
             'summary': '所有可用技能先拿基准分，再由 Lua 打分，取最高分执行。'},
            {'title': '怎么选目标', 'steps': ['target_method 限定敌 / 我 / 地面',
                'range_select + 射程划出可选格', 'target_order_param 给每个候选打分'],
             'fields': ['target_method', 'range_select', 'target_order_param'],
             'summary': '同一技能对多个候选目标逐个打分，取权重最高者。'},
            {'title': '什么时候不评分', 'steps': ['ai_skill_sorted：按技能表顺序取用',
                'ai_skill_by_order：严格按序', 'boss_skill_mode：循环固定技能序列'],
             'fields': ['unit_npc.ai_skill_sorted', 'unit_npc.ai_skill_by_order', 'boss_skill_sequence'],
             'summary': '单位上的顺序标志或 BOSS 固定序列会绕过上面的评分，直接按预设执行。'},
        ],
        'baseOrder': [{'order': k, 'skills': v} for k, v in order_values.most_common(16)],
        'luaWeights': [{'weight': k, 'times': v} for k, v in weights.most_common(16)],
        'vetoValues': [k for k in weights if k <= -10000],
        'staticOrderSkills': sum(order_values.values()),
        'luaScripts': sum(1 for s in scripts if s.get('lua')),
        'sortedUnits': sum(1 for n in npcs if n.get('sorted')),
        'byOrderUnits': sum(1 for n in npcs if n.get('byOrder')),
        'bossSequenceUnits': sum(1 for n in npcs if n.get('bossMode')),
        'quick': [
            {'title': '怎么选技能', 'steps': ['静态优先级 ai_skill_order（数值大者优先）',
                'Lua 动态打分 ai_order_param（大负数=否决）', 'BOSS 固定序列直接跳过评分'],
             'fields': ['ai_skill_order', 'ai_order_param', 'boss_skill_sequence'],
             'summary': '每个可用技能先拿基准分，再由战场状态加减权重，取得分最高的一个。'},
            {'title': '怎么选目标', 'steps': ['target_method 限定敌 / 我 / 地面',
                'range_select 与射程限定可选格', 'target_param 过滤 + target_order_param 排序打分'],
             'fields': ['target_method', 'range_select', 'target_param', 'target_order_param'],
             'summary': '先划出能打到的格子，再对这些格子上的单位逐个打分，取最高分。'},
            {'title': '怎么走路', 'steps': ['mobility 决定能走几格',
                'field_type.mobility 决定每格代价', 'move_type / jump 决定能否跨越高低差'],
             'fields': ['unit.mobility', 'field_type.mobility', 'unit.move_type'],
             'summary': '在带权地形网格上求可达格；最短路算法本身在编译代码中，配置表只提供代价与规则。'},
        ],
        'explanation': [
            '① 静态优先级：skill.ai_skill_order 是整数基准分，数值越大越先被考虑；未配置（0）走默认顺序。',
            '② 动态打分：skill.ai_order_param 与 target_order_param 是客户端 Lua 片段，运行时以 owner / target / map 为上下文返回一个权重，叠加到基准分上；return -10000 / -11111 之类的大负数表示「此技能本次不可用」，正数（500 / 1000 / 2000）则显著抬高优先级。',
            '③ 目标排序：target_order_param 对候选目标打分（如友军 +100），AI 先按得分选目标，再按 ② 选技能。',
            '④ 单位覆盖：unit_npc.ai_skill_sorted 表示按技能表顺序取用，ai_skill_by_order 表示严格按序；boss_skill_mode 开启时直接循环 boss_skill_sequence 里的固定技能序列，完全跳过 ①②③ 的评分。',
            '⑤ 综合：AI 每回合枚举「可用技能 × 可选目标」，得分 = 基准优先级 + Lua 动态权重 + 目标排序权重，取最高分执行；被大负数否决的组合直接排除。相关配置字段与 Lua 原文均可在「客户端代码」与「自动战斗 AI」页检索。',
        ],
    }


ENHANCE_TABLES = (
    ('unit_random', '角色初始属性随机浮动', '按权重抽取一组千分比修正，作用于角色初始六维'),
    ('online_charm_entry', '塔罗词条数值区间', 'attribute_value_min / max / step 定义每次洗练的取值区间与步长'),
    ('online_charm_build', '塔罗词条池', '按稀有度与词条位组织的可选词条池'),
    ('online_charm_build_entry', '词条池权重', 'weight 决定同池内各词条被抽中的概率'),
    ('online_charm_entry_reforge', '护石精炼方案', 'max_count 精炼次数上限与消耗'),
    ('online_charm_entry_reforge_lock', '精炼锁定消耗', 'lock_count 锁定词条数对应的材料消耗'),
    ('online_charm_entry_study', '词条领悟等级', 'show_level 解锁显示 / study_level 生效等级'),
    ('online_weapon_enchanting_element_entry', '刻印词条上限', 'attribute_max_value 与 attribute_is_permillage'),
    ('online_weapon_star', '武器星级千分比', '每星对五维的成长千分比'),
    ('online_treasure_random_chest_bonus', '随机宝箱掉落', 'count_min / max / step 与 weight 定义数量随机'),
)


def build_enhancement():
    """Inventory the client's enhancement fields and numeric roll rules.

    This is an investigation aid: it reports which tables carry the fields and
    the exact value ranges / weights, without inventing a roll algorithm that
    is not present in the config data.
    """
    tables = []
    for name, label, note in ENHANCE_TABLES:
        rows = table(name)
        if not rows:
            continue
        keys = list(rows[0])
        numeric = [k for k in keys if any(x in k for x in
                   ('min', 'max', 'step', 'weight', 'permillage', 'value', 'level', 'count', 'rarity'))]
        sample = {k: rows[0][k] for k in keys[:12]}
        ranges = {}
        for k in numeric:
            vals = [r.get(k) for r in rows if isinstance(r.get(k), (int, float))]
            if vals:
                ranges[k] = {'min': min(vals), 'max': max(vals),
                             'distinct': len(set(vals))}
        tables.append({'table': name, 'label': label, 'note': note,
                       'rows': len(rows), 'fields': keys,
                       'numericFields': numeric, 'ranges': ranges,
                       'sample': sample, 'rowsData': rows[:40]})
    if not tables:
        return None
    rules = [
        '客户端把「强化 / 随机」拆成确定性成长表与概率抽取表两类：'
        '`online_weapon_modify_level` / `online_charm_modify_level` 是随等级线性成长的**确定性**数值，不含随机。',
        '`unit_random` 有 31 组、每组 weight=1（等概率），每组给六维中的两维各 ±50‰，'
        '总和为 0 —— 即角色初始属性的「性格浮动」，不是可强化的数值。',
        '`online_charm_entry` 用 `attribute_value_min / attribute_value_max / attribute_value_step` '
        '定义洗练区间：固定值类步长 1、百分比类步长 10；实际可取值数 = (max−min)/step + 1。',
        '`online_charm_build` (37 个池) 与 `online_charm_build_entry` (1,222 条 weight) 构成加权抽样：'
        '同一 `idonline_charm_build` 内按 weight 归一化后抽取条目。',
        '`online_weapon_enchanting_element_entry` 的 `attribute_max_value` 是刻印词条上限，'
        '`attribute_is_permillage` 区分固定值 / 千分比；配置表只有上限，没有分布曲线，'
        '因此**随机是否均匀、是否分档没有字段可证**。',
        '`online_charm_entry_reforge` / `_lock` / `_study` 管精炼次数、锁定消耗与领悟等级；'
        '`online_treasure_random_chest_bonus` 用 `count_min/count_max/count_step/weight` 定义掉落数量随机。',
        '结论：本地能查到「随机取值的范围、步长、权重、上限」，但**没有**记录伪随机种子、'
        '分布类型（均匀/正态）、保底或重抽规则的字段；这些逻辑在编译后的 IL2CPP 代码中，配置表无法反推。',
    ]
    return {'v': 1, 'tables': tables, 'rules': rules,
            'source': '客户端配置表：unit_random / online_charm_entry* / '
                      'online_charm_build* / online_weapon_enchanting_element_entry / '
                      'online_weapon_star / online_treasure_random_chest_bonus'}


def build_ai_pathfinding():
    """Inventory every config field that constrains AI movement and targeting.

    The client exposes the CONSTRAINTS (mobility, terrain cost, ranges, target
    filters and Lua scoring hooks) but the A*/Dijkstra solver itself lives in
    compiled IL2CPP code, so this reports inputs rather than inventing an
    algorithm.
    """
    units = table('unit')
    fields = table('field_type')
    skills = table('skill')
    target_methods = {r['id']: r.get('name') for r in table('target_method')}
    range_selects = {r['id']: r.get('name') for r in table('range_select')}
    move_types = {r['id']: {'name': r.get('name'), 'desc': plain(r.get('desc'))}
                  for r in table('move_type')}
    mobility = Counter(r.get('mobility') for r in units)
    move_type_use = Counter(r.get('move_type') for r in units)
    jump_up = Counter(r.get('jump_up') for r in units)
    terrain_cost = [{'id': r['id'], 'name': r.get('name'),
                     'mobility': r.get('mobility'), 'rainMobility': r.get('rain_mobility'),
                     'type': r.get('type') or ''} for r in fields]
    target_method_use = Counter(r.get('target_method') for r in skills)
    target_select_use = Counter(r.get('target_select') for r in skills)
    range_select_use = Counter(r.get('range_select') for r in skills) if any(
        'range_select' in r for r in skills[:1]) else Counter()
    lua_apis = Counter()
    for table_name, field, _, _ in CODE_FIELDS:
        for row in table(table_name):
            for m in re.finditer(r'\bmap\s*[:.]\s*(\w+)', str(row.get(field) or '')):
                lua_apis[m.group(1)] += 1
    target_filters = sum(1 for r in skills if str(r.get('target_param') or '').strip())
    return {
        'moveTypes': [{'id': k, **v} for k, v in sorted(move_types.items())],
        'mobility': [{'value': k, 'units': v} for k, v in sorted(mobility.items(), key=lambda x: str(x[0]))],
        'moveTypeUse': [{'id': k, 'units': v} for k, v in move_type_use.most_common()],
        'jumpUp': [{'value': k, 'units': v} for k, v in jump_up.most_common()],
        'terrainCost': terrain_cost,
        'targetMethods': [{'id': k, 'name': v, 'skills': target_method_use.get(k, 0)}
                          for k, v in sorted(target_methods.items())],
        'rangeSelects': [{'id': k, 'name': v, 'skills': range_select_use.get(k, 0)}
                         for k, v in sorted(range_selects.items())],
        'targetSelectUse': [{'id': k, 'skills': v} for k, v in target_select_use.most_common()],
        'targetFilterScripts': target_filters,
        'targetOrderScripts': sum(1 for r in skills if str(r.get('target_order_param') or '').strip()),
        'aiOrderScripts': sum(1 for r in skills if str(r.get('ai_order_param') or '').strip()),
        'aiMoveClose': [{'value': str(r.get('ai_move_close')), 'skill': r['id']}
                        for r in skills if r.get('ai_move_close')],
        'luaApis': [{'api': k, 'times': v} for k, v in lua_apis.most_common(20)],
        'quick': [
            {'title': '① 先看能走多远', 'fields': ['mobility', 'move_type', 'jump_up', 'jump_down'],
             'text': '移动力多数为 3 格；钝步 / 轻步 / 飞行 / 瞬移 / 不可移动决定能否跨越高低差与障碍。'},
            {'title': '② 再看每格代价', 'fields': ['field_type.mobility', 'rain_mobility', 'field_status'],
             'text': '普通地面 10、流沙 / 毒沼 20、禁行 0、虚空 1000；燃烧 / 冰冻等状态还会额外消耗 0.5–1 移动力。'},
            {'title': '③ 最后挑落点与技能', 'fields': ['ai_move_close', 'findChargeBlock', 'target_order_param'],
             'text': '技能给出贴近 / 原地偏好，再由目标打分选人；冲锋与影步会校验落点是否合法。'},
        ],
        'explanation': [
            '① 移动能力：`unit.mobility` 是本回合可走的格数（多数单位 3 格），`unit.jump_up / jump_down` 是可跨越的高度差，'
            '`unit.move_type` 决定移动规则：钝步 / 轻步（可跳 1 格宽障碍）/ 飞行（无视高低差）/ 瞬移 / 不可移动。',
            '② 地形代价：`field_type.mobility` 是每格通行消耗（一般 10、流沙 / 毒沼 20、禁行 0、虚空 1000），'
            '`rain_mobility` 是雨天覆盖值；`field_status` 的燃烧 / 冰冻等状态还会「每格额外消耗 0.5 / 1 移动力」。'
            'AI 在这些带权格上求解可达集合，但寻路算法本身（A* 或 Dijkstra）在编译后的 IL2CPP 代码中，配置表无法证实。',
            '③ 站位偏好：`skill.ai_move_close` 只有 close / stay / default 三种标志，'
            '表示技能希望贴近目标、原地不动或默认；`speciality.active_param` 里大量 `map:getNeighborUnitCount(owner, isFriend, range, height)` '
            '按周围敌友数决定是否触发，`map:findChargeBlock` / `map:CheckShadowStepValid` 校验冲锋与影步的合法落点。',
            '④ 目标筛选：`skill.target_method` 18 类（选择敌人 / 我方 / 地面 / 无人地面 / 仅自己…）先限定可选对象，'
            '`range_select` 11 种形状（菱形 / 十字 / 扇形 / 单向线 / 矩形…）与 `range_min / range_max` 限定射程，'
            '`target_param` 有 638 段 Lua 逐目标返回 true/false 做可用性过滤（如排除物件、排除召唤者之外的单位）。',
            '⑤ 目标排序：`skill.target_order_param` 的 Lua 对每个候选目标返回一个权重——例如友军 +100、'
            '「优先对基础攻击更高的友军释放」、按 buff 层数或剩余生命排序；AI 取权重最高的目标。',
            '⑥ 技能选择：`ai_skill_order` 是静态优先级，`ai_order_param` 的 Lua 再按战场状态给动态权重'
            '（-10000 之类的大负数否决），两者相加取最高；BOSS 固定序列绕过评分。'
            '结论：**选人靠「目标方法 + 范围形状 + 过滤 Lua + 排序 Lua」四层打分，走路靠「移动力 + 地形权重 + 跳跃规则」，'
            '配置表能查到全部输入与打分脚本，但最短路求解器不在配置数据中。**',
        ],
    }


def build_ai():
    units = table('unit_npc')
    if not units:
        return [], [], {}
    skills = {r['id']: r for r in table('skill')}
    personalities = {r['id']: r.get('name') or '' for r in table('unit_personality')}
    skill_types = {r['id']: r.get('name') or '' for r in table('skill_type')} if table('skill_type') else {}

    def skill_name(sid):
        s = skills.get(sid) or {}
        return plain(s.get('name')) or f'技能 {sid}'

    def id_list(raw):
        return [int(x) for x in str(raw or '').split('|') if x.strip().isdigit()]

    npcs = []
    for r in units:
        sequence = id_list(r.get('boss_skill_sequence'))
        skill_ids = id_list(r.get('skill_ids'))
        npcs.append({
            'id': r['id'], 'name': plain(r.get('name')), 'editor': plain(r.get('editor_name')),
            'faction': r.get('faction'), 'personalityId': r.get('personality_id'),
            'personality': personalities.get(r.get('personality_id'), ''),
            'byOrder': bool(r.get('ai_skill_by_order')), 'sorted': bool(r.get('ai_skill_sorted')),
            'bossMode': bool(r.get('boss_skill_mode')),
            'melee': r.get('melee_skill'), 'reactive': r.get('reactive_skill'),
            'leader': r.get('leader_skill'),
            'skills': [{'id': i, 'name': skill_name(i)} for i in skill_ids],
            'sequence': [{'id': i, 'name': skill_name(i)} for i in sequence],
        })

    # All AI-related snippets: decision scripts, target sorting, icon effects,
    # plus non-Lua AI settings (priority / movement) as readable records.
    scripts = []
    for r in skills.values():
        for field, kind in (('ai_order_param', '技能决策'),
                            ('target_order_param', '目标排序'),
                            ('icon_effects_active_param', '图标特效条件')):
            lua = str(r.get(field) or '').strip()
            if len(lua) < 8:
                continue
            scripts.append({'id': r['id'], 'name': plain(r.get('name')), 'field': field,
                            'kind': kind, 'order': r.get('ai_skill_order'),
                            'moveClose': r.get('ai_move_close') or '',
                            'skillType': skill_types.get(r.get('skill_type'), ''),
                            'lua': lua})
        # Plain numeric / keyword AI settings without Lua still matter.
        order = r.get('ai_skill_order')
        move = str(r.get('ai_move_close') or '')
        if (order or move) and not r.get('ai_order_param'):
            scripts.append({'id': r['id'], 'name': plain(r.get('name')), 'field': 'ai_setting',
                            'kind': 'AI 参数', 'order': order, 'moveClose': move,
                            'skillType': skill_types.get(r.get('skill_type'), ''),
                            'lua': ''})
    scripts.sort(key=lambda x: (-int(x['order'] or 0), x['name']))
    meta = {
        'units': len(npcs), 'scripts': len(scripts),
        'luaScripts': sum(1 for s in scripts if s['lua']),
        'kinds': dict(Counter(s['kind'] for s in scripts)),
        'orderModes': dict(Counter('按顺序' if n['byOrder'] else '按优先级' if n['sorted'] else '默认' for n in npcs)),
        'bossUnits': sum(1 for n in npcs if n['bossMode']),
        'priority': build_ai_priority(list(skills.values()), npcs, scripts),
        'pathfinding': build_ai_pathfinding(),
    }
    return npcs, scripts, meta


LOCAL_CODE_DIR = ROOT / 'output' / 'client-code'


def _safe_filename(value, limit=48):
    text = re.sub(r'[\\/:*?"<>|\r\n\t]', '_', str(value or '')).strip()
    return (text[:limit] or 'unnamed').strip(' .')


def export_code_files(code, code_meta, battle_power):
    """Write every Lua snippet to a browsable local folder.

    Layout: ``output/client-code/<table>/<field>/<id>-<name>.lua`` plus an
    ``index.md`` per group and a top-level ``README.md`` / ``manifest.json``.
    Existing files are reused when unchanged, so repeated updates are cheap.
    """
    if not code:
        return 0
    root = LOCAL_CODE_DIR
    root.mkdir(parents=True, exist_ok=True)
    by_group = defaultdict(list)
    written = 0
    for item in code:
        folder = root / _safe_filename(item['table'], 32) / _safe_filename(item['field'], 40)
        folder.mkdir(parents=True, exist_ok=True)
        filename = f"{item['id']}-{_safe_filename(item['name'])}.lua"
        path = folder / filename
        header = (f"-- {item['label']} | {item['table']}#{item['id']} | {item['name']}\n"
                  f"-- field: {item['table']}.{item['field']} | type: {item.get('type')}\n"
                  f"-- references: {', '.join(item['refs'])}\n"
                  f"-- ai: {item['ai']} | hash: {item['hash']}\n\n")
        content = header + item['code'] + '\n'
        if not path.is_file() or path.read_text('utf8') != content:
            path.write_text(content, 'utf8')
            written += 1
        by_group[(item['table'], item['field'], item['label'])].append(
            (filename, item['id'], item['name'], len(item['refs'])))
    for (table_name, field, label), items in by_group.items():
        folder = root / _safe_filename(table_name, 32) / _safe_filename(field, 40)
        lines = [f'# {table_name}.{field} — {label}', '',
                 f'共 {len(items)} 段去重后的客户端 Lua 原文。', '',
                 '| 文件 | 配置 id | 名称 | 引用处 |', '| --- | --- | --- | --- |']
        for filename, rid, name, refs in sorted(items, key=lambda x: str(x[1])):
            lines.append(f'| [{filename}](./{filename}) | {rid} | {name.replace("|", "/")} | {refs} |')
        (folder / 'index.md').write_text('\n'.join(lines) + '\n', 'utf8')
    ai = (root / 'AI_PRIORITY.md')
    ai.write_text(ai_priority_doc(code_meta, battle_power), 'utf8')
    lines = [
        '# 客户端 Lua 代码库', '',
        f'- 去重代码段：**{code_meta["unique"]}**',
        f'- 配置表引用：**{code_meta["references"]}**',
        f'- AI 相关：**{code_meta["ai"]}**', '',
        '按「表 / 字段」分目录，每段一个 `.lua` 文件；文件头注释保留表、id、名称、引用位置与内容哈希。',
        '', '## 目录', '',
    ]
    for table_name, field, label in sorted(by_group):
        href = f'./{_safe_filename(table_name, 32)}/{_safe_filename(field, 40)}/index.md'
        lines.append(f'- [{table_name}.{field} — {label}]({href})（{len(by_group[(table_name, field, label)])} 段）')
    lines += ['', '## AI 优先级机制', '',
              '[AI_PRIORITY.md](./AI_PRIORITY.md) 分析了掌管自动战斗技能优先级的逻辑块与实现方式。',
              '', '## 生成', '', '```', 'python -X utf8 scripts/extract_world_data.py', '```', '']
    (root / 'README.md').write_text('\n'.join(lines), 'utf8')
    (root / 'manifest.json').write_text(json.dumps({
        'unique': code_meta['unique'], 'references': code_meta['references'],
        'fields': code_meta['fields'], 'battlePower': battle_power,
    }, ensure_ascii=False, indent=2) + '\n', 'utf8')
    return written


def ai_priority_doc(code_meta, battle_power):
    W = None
    try:
        W = json.loads(OUT.read_text('utf8')[len('window.WIKI_WORLD_DATA='):-2])
    except Exception:
        W = {}
    priority = (W.get('aiMeta') or {}).get('priority') or {}
    lines = ['# 自动战斗 AI 优先级机制', '',
             '> 依据客户端 `skill.ai_skill_order` / `ai_order_param` / `target_order_param`、',
             '> `unit_npc.ai_skill_sorted` / `ai_skill_by_order` / `boss_skill_sequence`，',
             '> 以及本仓库整理出的 Lua 原文（见同目录各字段 `index.md`）。', '',
             '## 实现方式', '']
    for step in priority.get('explanation', []):
        lines.append(f'- {step}')
    lines += ['', '## 静态优先级分布', '', '| ai_skill_order | 技能数 |', '| --- | --- |']
    for row in priority.get('baseOrder', []):
        lines.append(f'| {row["order"]} | {row["skills"]} |')
    lines += ['', '## Lua 动态权重（return 值）', '', '| 权重 | 出现次数 | 含义 |', '| --- | --- | --- |']
    for row in priority.get('luaWeights', []):
        w = row['weight']
        meaning = '否决（不可用）' if w <= -10000 else '降低优先级' if w < 0             else '默认 / 不调整' if w == 0 else '提高优先级'
        lines.append(f'| {w} | {row["times"]} | {meaning} |')
    lines += ['', '## 相关代码文件', '',
              '- `skill/ai_order_param/index.md` — 技能决策 Lua',
              '- `skill/target_order_param/index.md` — 目标排序 Lua',
              '- `skill/active_param/index.md` — 技能主动条件（AI 判定可用性的前置）',
              '- `speciality/active_param/index.md` — 特效触发条件', '',
              '## 战斗力常量（对照）', '',
              f'- `const_param#{battle_power.get("constId")} {battle_power.get("constName")}` = '
              f'`{"|".join(str(x) for x in battle_power.get("divisors", []))}`',
              '- `battle_power_coefficient` 职业 / 武器百分比',
              '- `unit_rarity.battle_power_adjust` 稀有度百分比', '']
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    maps, map_meta = build_maps()
    npcs, scripts, ai_meta = build_ai()
    code, code_meta = build_client_code()
    battle_power = build_battle_power()
    enhancement = build_enhancement()
    if not maps and not npcs:
        print('没有找到客户端配置表，保留现有数据文件不变。')
        return
    payload = {'v': 3, 'maps': maps, 'mapMeta': map_meta,
               'aiUnits': npcs, 'aiScripts': scripts, 'aiMeta': ai_meta,
               'battlePower': battle_power}
    text = ('window.WIKI_WORLD_DATA=' + json.dumps(payload, ensure_ascii=False,
                                                    separators=(',', ':')) + ';\n')
    code_text = ('window.WIKI_CLIENT_CODE=' + json.dumps(
        {'v': 1, 'scripts': code, 'meta': code_meta}, ensure_ascii=False,
        separators=(',', ':')) + ';\n')
    enhance_text = ('window.WIKI_ENHANCE_DATA=' + json.dumps(enhancement or {},
        ensure_ascii=False, separators=(',', ':')) + ';\n') if enhancement else ''
    print(f'地图 {len(maps)} 张（{sum(len(m["cells"]) for m in maps)} 个地块） · '
          f'AI 单位 {len(npcs)} 个 · AI 记录 {len(scripts)} 条 · '
          f'客户端代码 {len(code)} 段（{code_meta["references"]} 处引用） · '
          f'{(len(text) + len(code_text) + len(enhance_text)) / 1024:.0f} KiB')
    if args.dry_run:
        return
    OUT.write_text(text, 'utf8')
    CODE_OUT.write_text(code_text, 'utf8')
    if enhance_text:
        ENHANCE_OUT.write_text(enhance_text, 'utf8')
    written = export_code_files(code, code_meta, battle_power)
    print(f'已写入 {OUT.name}、{CODE_OUT.name}、{ENHANCE_OUT.name} 与 {written} 个本地代码文件')


if __name__ == '__main__':
    main()
