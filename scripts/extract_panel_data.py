"""Build the offline panel calculator's numeric data from the client config tables.

Everything here is read from the local game's Lua configuration bundles (the same
source as the character archive). No network, no account data, no battle reports.

The output is a single ``window.WIKI_PANEL_DATA=...;`` script:

* character growth (level 1-60), rarity adjustment, star permillage, rank add-ons,
  skill-line permillage, friendship permillage;
* weapon / off-hand growth, star and rarity tables;
* tarot (client name: charm) growth, rarity, entry templates and entry types;
* enchant elements, their per-stat caps and material rarities;
* the 22 revelation tarot cards used as labels;
* per-rank skill-line branches (left/right), weapon-type whitelist per character,
  and the two account-wide talent trees (星辰天赋 / 开拓天赋).

The calculator itself lives in ``panel-calc.js``; this script only exports data.

Usage:
    python scripts/extract_panel_data.py --dry-run
    python scripts/extract_panel_data.py [--game PATH] [--output PATH]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

STATS = ('hp', 'physic_attack', 'spell_attack', 'physic_defence', 'spell_defence')
STAT_LABELS = ('生命', '物攻', '魔攻', '物防', '魔防')
# attribute_type.id -> STATS index (see attribute_type: 5 = all five).
ATTR_TO_STAT = {2: 0, 7: 1, 8: 3, 9: 2, 10: 4}
MAX_LEVEL = 60
MAX_RANK = 13

TABLES = (
    'online_role', 'online_role_unit', 'unit', 'unit_rarity',
    'online_unit_modify_level', 'online_unit_star',
    'online_unit_rank_modify', 'online_unit_rank_modify_rank',
    'online_unit_rank_skill_line', 'online_unit_rank_skill_line_modify',
    'online_role_friendship_attribute', 'attribute_type', 'weapon_type',
    'online_weapon', 'online_weapon_modify_level', 'online_weapon_star',
    'online_weapon_rarity', 'online_charm', 'online_charm_modify_level',
    'online_charm_rarity', 'online_charm_entry', 'online_charm_entry_attribute_type',
    'online_weapon_enchanting_element', 'online_weapon_enchanting_element_entry',
    'online_weapon_enchanting_material_rarity', 'online_revelation_tarot_collection',
    'profession', 'online_tech_category', 'online_tech_node', 'online_tech_node_level',
)

# Account-wide talent trees. system 49 = 星辰天赋 (之座), 122 = 开拓天赋 (之志).
TALENT_SYSTEMS = (('star', 49, '星辰天赋'), ('pioneer', 122, '开拓天赋'))
# 41 = CategoryAttributeModify, 51 = AttributeModify: the only node types that
# touch the five out-of-battle stats.
TALENT_UPGRADE_TYPES = (41, 51)


def norm_name(text: str) -> str:
    return re.sub(r'[·•‧・]', '-', text or '').strip()


def num(row, key):
    value = row.get(key, 0)
    return value if isinstance(value, (int, float)) else 0


def stat_row(row, keys=None):
    keys = keys or STATS
    return [int(num(row, key)) for key in keys]


def load_tables(game: Path):
    from socdecode.client import LuaTables, text_assets
    vm = LuaTables(game / 'SoC_Data' / 'Plugins' / 'x86_64' / 'slua.dll')
    try:
        vm.setup(text_assets(game / 'assets' / 'lua' / 'lua_db.unity3d'))
        bundles = [text_assets(p) for p in sorted((game / 'assets' / 'lua').glob('lua_dbtemplate*.unity3d'))]
        tables = {}
        for name in TABLES:
            for scripts in bundles:
                if name in scripts and name not in tables:
                    try:
                        tables[name] = vm.table(name, scripts[name])
                    except Exception as exc:          # noqa: BLE001 - report, keep going
                        print(f'  表 {name} 解析失败：{exc}', file=sys.stderr)
                    break
        return tables
    finally:
        vm.close()


def growth_by_level(rows, group_key):
    grouped = defaultdict(dict)
    for row in rows:
        grouped[row[group_key]][int(row['level'])] = stat_row(row)
    out = {}
    for key, levels in grouped.items():
        out[str(key)] = [levels.get(level, [0] * len(STATS)) for level in range(1, MAX_LEVEL + 1)]
    return out


def build_talents(tables):
    """Aggregate both talent trees into per-profession, per-level stat bonuses.

    ``online_tech_node_level`` carries ``upgrade_param1`` (the amount),
    ``upgrade_param0`` (an ``attribute_type`` id, possibly a composite such as
    5 = all five or 43 = both attacks) and ``upgrade_is_permillage``. A level N
    entry means "this node at level N"; the exported arrays are cumulative so
    the calculator can look up a talent level in O(1).
    """
    attr_map = {}
    for row in tables['attribute_type']:
        ids = str(row.get('attribute_type_ids') or '')
        if ids:
            targets = [ATTR_TO_STAT[int(x)] for x in ids.split('|') if x.isdigit()
                       and int(x) in ATTR_TO_STAT]
        else:
            targets = [ATTR_TO_STAT[row['id']]] if row['id'] in ATTR_TO_STAT else []
        attr_map[row['id']] = targets

    levels_by_node = defaultdict(list)
    for row in tables['online_tech_node_level']:
        levels_by_node[row['idonline_tech_node']].append(row)
    nodes_by_cat = defaultdict(list)
    for row in tables['online_tech_node']:
        if row['upgrade_type'] in TALENT_UPGRADE_TYPES:
            nodes_by_cat[row['idonline_tech_category']].append(row)

    out = {}
    for key, system, name in TALENT_SYSTEMS:
        by_category, max_level = {}, 0
        for cat in tables['online_tech_category']:
            if cat['system'] != system:
                continue
            per_level = defaultdict(lambda: {'flat': [0] * len(STATS),
                                            'perm': [0] * len(STATS)})
            for node in nodes_by_cat[cat['id']]:
                for level in levels_by_node[node['id']]:
                    amount = int(num(level, 'upgrade_param1'))
                    targets = attr_map.get(int(num(level, 'upgrade_param0')), [])
                    bucket = 'perm' if level.get('upgrade_is_permillage') else 'flat'
                    for index in targets:
                        per_level[int(level['level'])][bucket][index] += amount
            top = max(per_level, default=0)
            max_level = max(max_level, top)
            cumulative = [{'flat': [0] * len(STATS), 'perm': [0] * len(STATS)}]
            for level in range(1, top + 1):
                prev, cur = cumulative[-1], per_level[level]
                cumulative.append({
                    'flat': [prev['flat'][i] + cur['flat'][i] for i in range(len(STATS))],
                    'perm': [prev['perm'][i] + cur['perm'][i] for i in range(len(STATS))],
                })
            by_category[str(cat['profession_category'])] = cumulative
        out[key] = {'name': name, 'system': system,
                    'maxLevel': max_level, 'byCategory': by_category}
    return out


def build(tables, page_names, plain):
    by_id = {name: {row['id']: row for row in rows} for name, rows in tables.items()}

    rarities = {str(r['id']): [r['name'], int(r['base_attribute_adjust'])]
                for r in tables['unit_rarity']}
    stars = {str(r['id']): stat_row(r, ['permillage_' + s for s in STATS])
             for r in sorted(tables['online_unit_star'], key=lambda r: r['id'])}
    friendship = {}
    for r in tables['online_role_friendship_attribute']:
        level = int(r['friendship_level'])
        friendship[level] = friendship.get(level, 0) + int(num(r, 'attribute_permillage'))

    rank_configs = by_id['online_unit_rank_modify']
    rank_adds = defaultdict(dict)
    for row in tables['online_unit_rank_modify_rank']:
        rank_adds[row['idonline_unit_rank_modify']][int(row['rank'])] = stat_row(
            row, [s + '_add' for s in STATS])
    rank_adds = {str(k): [v.get(r, [0] * len(STATS)) for r in range(1, MAX_RANK + 1)]
                 for k, v in rank_adds.items()}

    lines = defaultdict(list)
    for row in tables['online_unit_rank_skill_line_modify']:
        lines[str(row['idonline_unit_rank_skill_line'])].append([
            int(row['rank']), int(num(row, 'tier')), bool(row.get('is_enhance')),
            stat_row(row, ['permillage_' + s for s in STATS]),
        ])
    lines = {k: sorted(v) for k, v in lines.items()}
    line_names = {str(r['id']): r['name'] for r in tables['online_unit_rank_skill_line']}
    # Ranks that actually carry a skill-line stat bonus, per skill-line id.
    line_ranks = {k: sorted({row[0] for row in v}) for k, v in lines.items()}

    wiki_names = {norm_name(n) for n in page_names}
    role_names = {r['id']: r.get('name') or '' for r in tables['online_role']}
    units = by_id['unit']
    professions = by_id['profession']
    characters = []
    for row in tables['online_role_unit']:
        unit = units.get(row['idunit'])
        if not unit:
            continue
        name = plain(row.get('sp_name') or role_names.get(row['idonline_role'], '')).strip()
        if not name:
            continue
        rank_id = row['online_unit_rank_modify_id']
        config = rank_configs.get(rank_id, {})
        weapon_ids = [int(x) for x in re.split(r'[|,]', str(unit.get('weapon_type_ids') or ''))
                      if x.strip().isdigit()]
        profession = professions.get(unit.get('profession'), {})
        characters.append({
            'name': name, 'key': norm_name(name), 'id': row['id'],
            'rarity': row['rarity'], 'modify': row['online_unit_modify_id'],
            'rankModify': rank_id, 'line': str(config.get('skill_line_id', 1)),
            'tier1': config.get('tier1_name') or '技能轴一',
            'tier2': config.get('tier2_name') or '技能轴二',
            'speed': int(num(unit, 'speed')),
            'unitId': row['idunit'],
            'weaponTypes': weapon_ids,
            'professionCategory': int(num(profession, 'category')),
            'wiki': norm_name(name) in wiki_names,
            'enabled': bool(row.get('enable')),
        })
    characters.sort(key=lambda c: (not c['wiki'], not c['enabled'], c['name']))

    weapon_types = {r['id']: r['name'] for r in tables['weapon_type']}
    weapons = []
    for row in tables['online_weapon']:
        name = plain(row['name']).strip()
        if not name or '内部测试' in name or '废弃' in name:
            continue
        weapons.append({
            'id': row['id'], 'name': name,
            'type': weapon_types.get(row['type'], str(row['type'])),
            'typeId': row['type'], 'rarity': row['rarity'],
            'modify': row['online_weapon_modify_id'],
            'icon': (row.get('icon') or '').strip(),
            'main': bool(weapon_types.get(row['type']) and
                         next((r['main_hand'] for r in tables['weapon_type'] if r['id'] == row['type']), True)),
        })
    weapons.sort(key=lambda w: (w['type'], w['rarity'], w['name']))
    weapon_stars = {str(r['id']): stat_row(r, ['permillage_' + s for s in STATS])
                    for r in sorted(tables['online_weapon_star'], key=lambda r: r['id'])}
    weapon_rarities = {str(r['id']): [r['name'], int(r['base_attribute_adjust'])]
                       for r in tables['online_weapon_rarity']}

    charms = []
    for row in tables['online_charm']:
        name = plain(row['name']).strip()
        if not name or 'test' in name.lower():
            continue
        charms.append({'id': row['id'], 'name': name, 'icon': row.get('icon') or '',
                       'modify': row['online_charm_modify_id']})
    charm_rarities = {str(r['id']): [r['name'], int(r['base_attribute_adjust']),
                                     int(num(r, 'entry_count')), int(num(r, 'level_cap'))]
                      for r in tables['online_charm_rarity']}

    entry_types = []
    for row in tables['online_charm_entry_attribute_type']:
        stat = ATTR_TO_STAT.get(int(num(row, 'attribute_type')))
        if stat is None:
            continue
        entry_types.append({'id': row['id'], 'label': row.get('editor_name') or row['name'],
                            'stat': stat, 'percent': int(num(row, 'attribute_additional_type')) == 2})
    entry_types.sort(key=lambda e: e['id'])
    entries = []
    for row in tables['online_charm_entry']:
        entries.append({'id': row['id'], 'name': plain(row['name']),
                        'rarity': int(num(row, 'rarity')), 'type': row['entry_attribute_type'],
                        'min': int(num(row, 'attribute_value_min')),
                        'max': int(num(row, 'attribute_value_max'))})

    elements = [{'id': r['id'], 'name': plain(r['name']), 'color': r.get('color_figure') or ''}
                for r in tables['online_weapon_enchanting_element']]
    enchant = []
    for row in tables['online_weapon_enchanting_element_entry']:
        stat = ATTR_TO_STAT.get(int(num(row, 'attribute_type')))
        if stat is None:
            continue
        enchant.append({'element': row['idonline_weapon_enchanting_element'],
                        'stat': stat, 'percent': bool(row.get('attribute_is_permillage')),
                        'max': int(num(row, 'attribute_max_value'))})
    enchant_rarities = [{'id': r['id'], 'name': r['name']}
                        for r in tables['online_weapon_enchanting_material_rarity']]
    tarot_cards = [{'id': r['id'], 'name': plain(r['name']), 'number': r.get('number') or '',
                    'icon': r.get('icon') or ''}
                   for r in tables['online_revelation_tarot_collection']]

    return {
        'schemaVersion': 1,
        'stats': list(STATS), 'statLabels': list(STAT_LABELS),
        'maxLevel': MAX_LEVEL, 'maxRank': MAX_RANK,
        'rarities': rarities, 'stars': stars, 'friendship': friendship,
        'characters': characters,
        'unitGrowth': growth_by_level(tables['online_unit_modify_level'], 'idonline_unit_modify'),
        'rankAdds': rank_adds, 'lines': lines, 'lineNames': line_names,
        'lineRanks': line_ranks,
        'talents': build_talents(tables),
        'weapons': weapons, 'weaponTypeNames': {str(k): v for k, v in weapon_types.items()},
        'weaponGrowth': growth_by_level(tables['online_weapon_modify_level'], 'idonline_weapon_modify'),
        'weaponStars': weapon_stars, 'weaponRarities': weapon_rarities,
        'charms': charms,
        'charmGrowth': growth_by_level(tables['online_charm_modify_level'], 'idonline_charm_modify'),
        'charmRarities': charm_rarities,
        'entryTypes': entry_types, 'entries': entries,
        'elements': elements, 'enchant': enchant,
        'enchantRarities': enchant_rarities, 'tarotCards': tarot_cards,
    }


def page_names(root: Path):
    text = (root / 'data' / 'index.js').read_text('utf8')
    payload = json.loads(text[text.index('=') + 1:text.index(';window.WIKI_PAGES')])
    return [page['name'] for page in payload['pages'] if page.get('type') == 'character']


def main():
    parser = argparse.ArgumentParser(description='导出局外面板计算器所需的客户端数值表')
    parser.add_argument('--game', help='游戏客户端目录（默认读本地配置）')
    parser.add_argument('--output', default=str(ROOT / 'data' / 'panel-data.js'))
    parser.add_argument('--dry-run', action='store_true', help='只统计，不写文件')
    args = parser.parse_args()

    from socdecode.client import game_root
    from socdecode.config import game_path
    from socdecode.model import plain
    try:
        game = game_root(Path(args.game) if args.game else game_path())
    except (ValueError, OSError) as error:
        output = Path(args.output)
        print(f'跳过局外面板数值导出：没有找到游戏客户端（{error}）。')
        if output.is_file():
            print(f'  {output.name} 以及随资料包附带的数值保持不变。')
        else:
            print('  资料包里也没有这份数据；离线 Wiki 仍可阅读，局外面板计算器会提示数据未载入。')
        print('  如需重新生成，请在「设置」里指定游戏客户端目录后重试。')
        return
    print(f'读取客户端：{game}')
    try:
        tables = load_tables(game)
    except Exception as error:              # noqa: BLE001 - a damaged Lua install
        print(f'跳过局外面板数值导出：读取客户端配置表失败（{type(error).__name__}: {error}）。')
        print('  已有的 data/panel-data.js 保持不变。')
        return
    missing = [name for name in TABLES if not tables.get(name)]
    if missing:
        print(f'跳过局外面板数值导出：客户端缺少必需的配置表 {missing}。')
        print('  已有的 data/panel-data.js 保持不变。')
        return
    data = build(tables, page_names(ROOT), plain)
    print(f"角色 {len(data['characters'])}（其中资料馆角色 "
          f"{sum(1 for c in data['characters'] if c['wiki'])}） · "
          f"武器 {len(data['weapons'])} · 塔罗 {len(data['charms'])} · "
          f"刻印属性 {len(data['enchant'])} · 塔罗词条 {len(data['entries'])}")
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    print(f'数据大小 {len(payload.encode("utf8")) / 1024:.0f} KiB')
    if not args.dry_run:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text('/* Generated by scripts/extract_panel_data.py from local client config. */\n'
                          'window.WIKI_PANEL_DATA=' + payload + ';\n', 'utf8')
        print(f'已写入 {output}')


if __name__ == '__main__':
    main()
