"""Export combat constants, choice-skill groups and decoded skill mechanics.

Three offline data products, all from the game's own Lua configuration tables:

* ``data/combat-data.js``     -> ``window.WIKI_COMBAT_DATA``
  Damage/panel formula sources and the authoritative numeric constants:
  ``const_param`` (crit, restraint, fall/knockback damage, damage caps),
  ``profession_restrain`` joined to ``speciality`` for the REAL restraint
  factor (its ``evaluate`` column is only a UI display value: 130/70 there,
  while 守望者→毁灭者 is actually 1.4 and 毁灭者→守望者 0.6 from
  ``speciality#3326/#3325.param2`` = +40/-40),
  ``profession_category``, ``damage_type``, ``attribute_type``; plus the
  high/low ground modifiers quoted from the archived BWIKI article.
  ``formulas[].variables`` records every term, its source table and its unit.

* ``data/choice-skills.js``   -> ``window.WIKI_CHOICE_SKILLS``
  For every ``（抉择）`` skill, the authoritative child list comes from a
  ``speciality`` row of type 158 (SKILL_GROUP), whose param0..param3 are the
  child skill ids. Also carries the bracket-glossary keyword descriptions.

* ``data/skill-mechanics.js`` -> ``window.WIKI_SKILL_MECHANICS``
  Each skill's decoded ``speciality_ids`` chain: the 257 ``speciality_type``
  rows give the mechanic name and parameter labels; ``aoe_param``,
  ``aoe_diffusion_mode``, ``range_select``, ``buff`` and ``target_method``
  decode the geometry and effects. This is where rules like 「人为财死」's
  gather come from: AOE diamond 3 (``OTHER_TELEPORT_TO_TARGET``, direction
  bits 15) teleports every selected enemy next to the target tile.

Two sources, like extract_dialogues.py: prefer the already-decrypted tables
under ``output/archive/library/当前版本/配置表/``; otherwise read the client's
``lua_dbtemplate*.unity3d`` bundles directly with the Lua decoder (about 30s).
Neither the client nor an archive available -> keep all existing files.

Usage:
    python -X utf8 scripts/extract_battle_rules.py --dry-run
    python -X utf8 scripts/extract_battle_rules.py --source client
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from socdecode import pinyin as soc_pinyin  # noqa: E402

ARCHIVE_CFG = ROOT / 'output' / 'archive' / 'library' / '当前版本' / '配置表'
OUT_COMBAT = ROOT / 'data' / 'combat-data.js'
OUT_CHOICES = ROOT / 'data' / 'choice-skills.js'
OUT_MECHANICS = ROOT / 'data' / 'skill-mechanics.js'
WIKI_FORMULA = ROOT / 'data' / 'raw' / '伤害公式汇总.json'

# Tables we need, with the bundle family that holds them in the client.
TABLES = {
    'const_param': 'lua_dbtemplate',
    'profession_category': 'lua_dbtemplate',
    'profession_restrain': 'lua_dbtemplate',
    'damage_type': 'lua_dbtemplate',
    'attribute_type': 'lua_dbtemplate',
    'range_select': 'lua_dbtemplate',
    'target_method': 'lua_dbtemplate',
    'aoe_param': 'lua_dbtemplate',
    'aoe_diffusion_mode': 'lua_dbtemplate',
    'speciality_type': 'lua_dbtemplate',
    'skill': 'lua_dbtemplateskill',
    'speciality': 'lua_dbtemplatespeciality',
    'buff': 'lua_dbtemplatespeciality',
    'skill_keyword': 'lua_dbtemplate',
}

# Client constants that actually feed a damage or panel formula.
CONSTANT_LABELS = {
    'RestrainFactor': ('克制方伤害系数', '百分比；通用克制参数（125%），PVE 实战以 profession_restrain → speciality.param2 为准'),
    'BeRestrainFactor': ('被克制方伤害系数', '百分比；通用被克制参数（80%）'),
    'CritBaseChance': ('基础暴击率', '百分比'),
    'CritBaseDamage': ('基础暴击伤害加成', '百分比，即暴击时伤害 +30%'),
    'KnockbackImpactDamage': ('击退撞击伤害', '每次撞击的固定伤害'),
    'FallDamage': ('坠落伤害', '每 3 格高度触发一次'),
    'FallDamageHeight': ('坠落伤害高度阈值', '格'),
    'FixBedamageLimit': ('易伤上限', '百分比'),
    'OnlineArenaDefenseCoefficient': ('竞技场防御系数', '仅竞技场结算'),
    'CharacterMaxLevel': ('角色等级上限', '等级'),
    'OnlineRoleFriendshipMaxLevel': ('好感度上限', '级'),
    'OnlineWeaponEnchantingMaxCount': ('刻印词条上限', '条'),
}

# speciality types worth spelling out in the mechanism panel.
MECHANIC_KINDS = {
    2: '回复', 5: '伤害', 14: '传送', 34: '击退', 36: '施加BUFF', 40: '范围攻击',
    94: '技能CD', 158: '技能组', 181: '聚拢/传送', 182: '聚拢', 183: '聚拢',
}
DIRECTION_BITS = {1: '上', 2: '下', 4: '左', 8: '右'}
TAG = re.compile(r'<[^>]+>')
BRACKET = re.compile(r'[\[<]style[^>\]]*[\]>]*|\[/?style[^\]]*\]')


SPRITE = {'1': '✕', '2': '▲', '3': '▼', '10': '◆'}


def plain(text) -> str:
    """Strip the client's rich-text markup for readable labels."""
    value = str(text or '')
    value = re.sub(r'<style=[^>]*>|</style>', '', value)
    value = re.sub(r'<sprite=(\d+)[^>]*>', lambda m: SPRITE.get(m.group(1), ''), value)
    value = TAG.sub('', value)
    return value.replace(' ', ' ').strip()


class Tables:
    """Read the needed tables from the archive, or straight from the client."""

    def __init__(self, game: Path, source: str):
        self.game = game
        self.cache = {}
        self.mode = 'archive' if source != 'client' and ARCHIVE_CFG.is_dir() else 'client'
        self.vm = None
        self.bundles = {}
        if self.mode == 'client':
            from socdecode.client import LuaTables, text_assets
            self.vm = LuaTables(game / 'SoC_Data' / 'Plugins' / 'x86_64' / 'slua.dll')
            self.vm.setup(text_assets(game / 'assets' / 'lua' / 'lua_db.unity3d'))
            self.text_assets = text_assets

    def close(self):
        if self.vm:
            self.vm.close()

    def get(self, name):
        if name in self.cache:
            return self.cache[name]
        group = TABLES.get(name, 'lua_dbtemplate')
        rows = []
        if self.mode == 'archive':
            for folder in (group, *sorted(p.name for p in ARCHIVE_CFG.glob('*') if p.is_dir())):
                path = ARCHIVE_CFG / folder / f'{name}.json'
                if path.is_file():
                    try:
                        rows = json.loads(path.read_text('utf8'))
                        break
                    except (OSError, ValueError):
                        continue
        else:
            for family in (group, *sorted(p.stem for p in (self.game / 'assets' / 'lua').glob('lua_dbtemplate*.unity3d'))):
                bundle = self.game / 'assets' / 'lua' / f'{family}.unity3d'
                if not bundle.is_file():
                    continue
                if family not in self.bundles:
                    self.bundles[family] = self.text_assets(bundle)
                scripts = self.bundles[family]
                if name in scripts:
                    try:
                        rows = self.vm.table(name, scripts[name])
                        break
                    except (ValueError, KeyError, IndexError):
                        continue
        self.cache[name] = rows or []
        return self.cache[name]


def skip(reason, *hint):
    print(f'跳过战斗规则提取：{reason}。')
    for line in hint:
        print(f'  {line}')
    print('  已有的 data/combat-data.js、choice-skills.js、skill-mechanics.js 保持不变。')


def build_combat(tables):
    constants = {}
    for row in tables.get('const_param'):
        key = row.get('type')
        if key not in CONSTANT_LABELS:
            continue
        label, note = CONSTANT_LABELS[key]
        constants[key] = {'id': row.get('id'), 'value': row.get('iparam'),
                          'label': label, 'note': note, 'source': f"const_param#{row.get('id')}"}
    categories = [{'id': r.get('id'), 'name': r.get('name'), 'type': r.get('type')}
                  for r in tables.get('profession_category')]
    names = {c['id']: c['name'] for c in categories}
    # ``profession_restrain.evaluate`` is only the number shown in the client UI.
    # The damage multiplier lives in the linked ``speciality`` row: param2 is
    # the attack modifier in percent (3323/3324 = ±30, 3326/3325 = ±40).
    # So 守望者→毁灭者 is 1.4 (not 1.3) and 毁灭者→守望者 is 0.6 (not 0.7).
    speciality = {r.get('id'): r for r in tables.get('speciality')}
    restraints = []
    for r in tables.get('profession_restrain'):
        if not r.get('show_ui'):
            continue
        sp_ids = [int(x) for x in str(r.get('speciality_ids') or '').split('|') if x.strip().isdigit()]
        sp = next((speciality[i] for i in sp_ids if i in speciality), None)
        param2 = int(sp.get('param2') or 0) if sp else 0
        factor = (100 + param2) / 100
        restraints.append({
            'from': r.get('idprofession_category'), 'fromName': names.get(r.get('idprofession_category'), ''),
            'to': r.get('profession_category_target'), 'toName': names.get(r.get('profession_category_target'), ''),
            'percent': int(round(factor * 100)), 'factor': factor,
            'evaluate': r.get('evaluate'), 'specialityId': sp.get('id') if sp else None,
            'specialityName': plain(sp.get('name')) if sp else '',
            'source': f"profession_restrain#{r.get('id')}"
                      + (f" → speciality#{sp.get('id')}.param2={param2}" if sp else '（缺 speciality，回落 evaluate）'),
        })
    damage_types = [{'id': r.get('id'), 'name': r.get('name'), 'type': r.get('type'), 'desc': r.get('desc')}
                    for r in tables.get('damage_type')]
    attributes = {r.get('id'): r.get('name') or r.get('editor_name')
                  for r in tables.get('attribute_type')}

    high, low, note = 15, -10, '高低差修正来自归档的《伤害公式汇总》（BWIKI 攻略，作者海森）'
    if WIKI_FORMULA.is_file():
        try:
            text = json.loads(WIKI_FORMULA.read_text('utf8'))['parse']['text']
            up = re.search(r'攻击力\s*\+(\d+)%', text)
            down = re.search(r'攻击力\s*-(\d+)%', text)
            if up:
                high = int(up.group(1))
            if down:
                low = -int(down.group(1))
        except (OSError, ValueError, KeyError):
            pass

    references = [
        {'table': 'online_unit_modify_level', 'provides': '角色等级成长（每级五维）', 'bundle': 'lua_dbtemplateonline'},
        {'table': 'unit_rarity', 'provides': '稀有度基础属性调整 base_attribute_adjust', 'bundle': 'lua_dbtemplate'},
        {'table': 'online_unit_star', 'provides': '星级千分比加成', 'bundle': 'lua_dbtemplateonline'},
        {'table': 'online_unit_rank_skill_line_modify', 'provides': '技能轴逐阶千分比加成', 'bundle': 'lua_dbtemplateonline'},
        {'table': 'online_unit_rank_modify_rank', 'provides': '每阶固定属性加成', 'bundle': 'lua_dbtemplateonline'},
        {'table': 'online_role_friendship_attribute', 'provides': '好感度千分比加成', 'bundle': 'lua_dbtemplateonline'},
        {'table': 'online_tech_node / online_tech_node_level', 'provides': '星辰 / 开拓天赋加成', 'bundle': 'lua_dbtemplateonline'},
        {'table': 'online_weapon_modify_level / online_charm_modify_level', 'provides': '武器与塔罗等级成长', 'bundle': 'lua_dbtemplateonline'},
        {'table': 'online_weapon_enchanting_element_entry', 'provides': '刻印固定值与千分比', 'bundle': 'lua_dbtemplateonline'},
        {'table': 'const_param', 'provides': '暴击 / 克制 / 坠落 / 击退 / 易伤上限等战斗常量', 'bundle': 'lua_dbtemplate'},
        {'table': 'profession_restrain → speciality', 'provides': '职业克制真实倍率（130/70 与 140/60 两档）', 'bundle': 'lua_dbtemplate + lua_dbtemplatespeciality'},
        {'table': 'skill', 'provides': 'damage_factor / defence_ignore / crit_chance 等技能倍率', 'bundle': 'lua_dbtemplateskill'},
        {'table': 'data/raw/伤害公式汇总.json', 'provides': '高低差 ±15% / -10%、技能倍率与伤害区间的文字说明（原站攻略）', 'bundle': '归档原文'},
    ]
    return {
        'v': 1, 'constants': constants, 'categories': categories, 'restraints': restraints,
        'damageTypes': damage_types, 'attributes': attributes,
        'highGround': {'up': high, 'down': low, 'source': note},
        'formulas': [
            {'id': 'panel', 'title': '角色局外面板',
             'expr': '⌊角色白板值 × (100% + 全局百分比 Q)⌋ + 装备 / 天赋 / 词条固定值；白板值 = ⌊等级成长 × 稀有度调整 × (1000 + 星级‰ + 技能轴‰ + 好感度‰) ÷ 1000 ÷ 100⌋ + 各阶固定加成',
             'source': '客户端 PlayerRoleUnit.CalculateAttributeByType（scripts/socdecode/model.py::attributes() 与 panel-calc.js 复现）；百分比乘区依据归档攻略《塔罗图鉴库》#2729 与《附魔图鉴库》#2736：「所有词条的百分比数值均为角色白板属性相对的百分比数值，即角色卸下所有装备后再减去天赋所增加的属性后的属性值」',
             'steps': ['① 基础成长 G = 等级成长 × 稀有度调整，定点数取整（online_unit_modify_level、unit_rarity）',
                       '② 角色乘区 P = 星级‰ + 逐阶技能轴‰ + 好感度‰；角色五维 = ⌊G × (1000 + P) / 1000⌋ + 各阶固定加成',
                       '③ 装备/天赋/塔罗固定值 F = 主手 + 副手 + 星辰天赋 + 开拓天赋 + 塔罗词条；这些全部相加，不参与 ② 的乘区',
                       '④ 全局乘区 Q = 武器 + 副手 + 塔罗 + 天赋的千分比 + 手动校准；Q 只作用于角色白板值（客户端：卸下装备、减去天赋后的属性值，见归档《塔罗图鉴库》《附魔图鉴库》），最终面板 = ⌊白板 × (1000 + Q) / 1000⌋ + F',
                       '⑤ 敏捷单独取角色 speed 基础值，不走上述乘区'],
             'variables': [
                 {'symbol': 'G', 'name': '等级成长 × 稀有度调整', 'unit': '五维整数',
                  'source': 'online_unit_modify_level · unit_rarity.base_attribute_adjust', 'note': '先乘后取整，定点数第一级'},
                 {'symbol': 'P', 'name': '角色千分比', 'unit': '‰',
                  'source': 'online_unit_star · online_unit_rank_skill_line_modify · online_role_friendship_attribute',
                  'note': '星级 + 逐阶技能轴左右 + 好感度，逐项累加'},
                 {'symbol': 'K', 'name': '各阶固定加成', 'unit': '五维整数',
                  'source': 'online_unit_rank_modify_rank', 'note': '① 之后再相加，不受 P 影响'},
                 {'symbol': 'F', 'name': '装备 / 天赋 / 塔罗固定值', 'unit': '五维整数',
                  'source': 'online_weapon_modify_level · online_charm_modify_level · online_tech_node_level · online_weapon_enchanting_element_entry',
                  'note': '刻印固定值与百分比分开结算'},
                 {'symbol': 'Q', 'name': '全局千分比', 'unit': '‰',
                  'source': '装备/天赋/塔罗词条千分比 + 界面手动校准', 'note': '只对角色白板值结算；装备与天赋固定值不参与乘区（客户端白板属性定义）'},
                 {'symbol': 'S', 'name': '敏捷', 'unit': '整数',
                  'source': 'unit.speed', 'note': '独立字段，不参与乘区'},
             ],
             'tables': ['online_unit_modify_level', 'unit_rarity', 'online_unit_star',
                        'online_unit_rank_skill_line_modify', 'online_unit_rank_modify_rank',
                        'online_role_friendship_attribute', 'online_tech_node_level']},
            {'id': 'damage', 'title': '战斗伤害',
             'expr': '⌊(攻击力 × 职业克制 × 高低差 − 有效防御) × 技能倍率 × 增伤 × 易伤⌋',
             'source': '原站攻略《伤害公式汇总》+ 客户端 const_param / profession_restrain → speciality / skill 倍率字段；本仓库 panel-calc.js::damage() 与 tools-core.js::calculateDamage() 实现',
             'steps': [f'① 有效攻击 A = 面板物攻/魔攻 × 职业克制 × 高低差（高 2 格 +{high}%、低 2 格 {low}%，归档攻略）',
                       '② 职业克制取 profession_restrain 关联的 speciality.param2：普通克制环 ±30%（1.3 / 0.7），守望者→毁灭者 +40%（1.4）、毁灭者→守望者 −40%（0.6）；表里的 evaluate=130/70 只是 UI 显示值，不用于结算',
                       '③ 有效防御 D = max(0, 目标防御 × (1 − 降防%) − 固定减防) × (1 − 无视防御%)',
                       '④ 基础差值 B = max(0, A − D)；技能倍率 M 取 skill.damage_factor / damage_percent',
                       '⑤ 最终伤害 = B × M × 增伤区间（下限 50%）× 易伤区间（上限 FixBedamageLimit = 230%）；暴击再乘 (1 + CritBaseDamage/100)，基础暴击率 CritBaseChance = 10%',
                       '⑥ 击退撞击与坠落伤害是独立的固定伤害：KnockbackImpactDamage = 20；每 FallDamageHeight = 3 格高度触发一次 FallDamage = 15'],
             'variables': [
                 {'symbol': 'A', 'name': '有效攻击', 'unit': '整数',
                  'source': '局外面板 + profession_restrain → speciality.param2 + 《伤害公式汇总》高低差',
                  'note': '克制和高低差都乘在攻击侧，先乘后减防'},
                 {'symbol': 'C', 'name': '职业克制', 'unit': '倍率',
                  'source': 'speciality#3323/3324（±30%）· #3326/3325（±40%）',
                  'note': '1.3 / 0.7 与 1.4 / 0.6 两档'},
                 {'symbol': 'D', 'name': '有效防御', 'unit': '整数',
                  'source': '目标面板物防/魔防 + 界面降防/无视防御', 'note': '先百分比降防，再减固定值，最后无视防御'},
                 {'symbol': 'M', 'name': '技能倍率', 'unit': '倍率',
                  'source': 'skill.damage_factor / damage_percent', 'note': '按技能配置，计算器里可手填'},
                 {'symbol': 'E', 'name': '增伤 / 易伤', 'unit': '倍率',
                  'source': 'const_param#296 FixBedamageLimit + 界面输入', 'note': '增伤下限 0.5，易伤上限 2.3'},
                 {'symbol': 'K', 'name': '暴击', 'unit': '倍率',
                  'source': 'const_param#129 CritBaseChance=10 · #64 CritBaseDamage=30',
                  'note': '暴击时伤害 ×1.3'},
             ],
             'tables': ['const_param', 'profession_restrain', 'speciality', 'skill', 'damage_type']},
        ],
        'references': references,
    }


def build_choices(tables):
    skill = {r.get('id'): r for r in tables.get('skill')}
    speciality = {r.get('id'): r for r in tables.get('speciality')}
    keywords = {r.get('id'): r for r in tables.get('skill_keyword')}
    groups = []
    for parent in skill.values():
        if '抉择' not in str(parent.get('desc', '')):
            continue
        children = []
        for token in str(parent.get('speciality_ids') or '').split('|'):
            if not token.strip().isdigit():
                continue
            group = speciality.get(int(token))
            if not group or group.get('type') != 158:      # SKILL_GROUP
                continue
            for index in range(4):
                child_id = group.get(f'param{index}')
                if not child_id:
                    continue
                child = skill.get(child_id)
                if not child:
                    continue
                kw_ids = [int(x) for x in str(parent.get('keyword_ids') or '').split('|') if x.isdigit()]
                kw = next((keywords[k] for k in kw_ids if keywords.get(k, {}).get('name') == child.get('name')), None)
                name = plain(child.get('name'))
                children.append({
                    'id': child_id, 'name': name,
                    'desc': plain(child.get('desc') or (kw or {}).get('desc') or ''),
                    'keywordId': kw.get('id') if kw else None,
                    'keywordDesc': plain((kw or {}).get('desc') or ''),
                    'cost': child.get('tp'), 'cooldown': child.get('cooldown'),
                    'range': [child.get('range_min'), child.get('range_max')],
                    'targetMethod': child.get('target_method'),
                    'icon': child.get('icon') or '',
                })
        if not children:
            continue
        # De-duplicate children that appear in several param slots.
        seen, unique = set(), []
        for child in children:
            if child['id'] in seen:
                continue
            seen.add(child['id'])
            unique.append(child)
        kw_ids = [int(x) for x in str(parent.get('keyword_ids') or '').split('|') if x.isdigit()]
        groups.append({
            'id': parent.get('id'), 'name': plain(parent.get('name')),
            'desc': plain(parent.get('desc')),
            'keywordIds': kw_ids,
            'children': unique,
        })
    return {'v': 1, 'groups': groups}


def directions(bits):
    if not bits:
        return '四个方向'
    names = [label for bit, label in DIRECTION_BITS.items() if bits & bit]
    return '、'.join(names) if names else '四个方向'


def authoritative_skills(choices=None):
    """Work out which client ``skill`` id is the real entry for a given name.

    The client table keeps one row per version of a skill (season variants,
    two-stage casts, enhanced copies, event reskins) - 2,237 duplicate names.
    Previously any row whose *name* matched a wiki page was exported, so one
    search produced a dozen near-identical cards. The genuine entry is the id
    the game actually shows the player, in descending confidence:

    * a 抉择 parent/child referenced by ``speciality#SKILL_GROUP``;
    * a skill id from the character skill trees (``output/client-data.json``);
    * a client-generated skill page (``clientSource.rowId`` / 100000000+id);
    * otherwise fall back to the archived BWIKI skill page description, then
      to the most complete / earliest client row.

    Returns ``(wiki_names, client_tree_ids, client_page_ids, choice_ids,
    wiki_desc)``; an empty structure means "export everything" as before.
    """
    index = ROOT / 'data' / 'index.js'
    pages = []
    wiki_names, wiki_skill_names, client_page_ids = set(), set(), set()
    if index.is_file():
        try:
            text = index.read_text('utf8')
            pages = json.JSONDecoder().raw_decode(text[text.index('=') + 1:])[0]['pages']
        except (OSError, ValueError, KeyError, IndexError):
            pages = []
    for pg in pages:
        if pg.get('name'):
            wiki_names.add(pg['name'])
        if pg.get('type') != 'skill':
            continue
        wiki_skill_names.add(pg.get('name') or '')
        if pg.get('id', 0) >= 100_000_000:
            client_page_ids.add(pg['id'] - 100_000_000)
    # clientSource.rowId links generated pages to the exact client row.
    pages_dir = ROOT / 'data' / 'pages'
    if pages_dir.is_dir():
        for f in pages_dir.glob('*.js'):
            try:
                text = f.read_text('utf8')
                if '"clientSource"' not in text or '"table":"skill"' not in text:
                    continue
                doc = json.loads(text[text.index('=') + 1:].rstrip().rstrip(';'))
                cs = doc.get('clientSource') or {}
                if cs.get('table') == 'skill' and cs.get('rowId'):
                    client_page_ids.add(int(cs['rowId']))
            except (OSError, ValueError, IndexError, TypeError):
                continue
    client_tree_ids = set()
    snapshot = ROOT / 'output' / 'client-data.json'
    if snapshot.is_file():
        try:
            snap = json.loads(snapshot.read_text('utf8'))
            skills = snap.get('skills') or {}
            client_tree_ids = {int(k) for k in skills if str(k).isdigit()}
        except (OSError, ValueError, TypeError):
            pass
    choice_ids = set()
    for group in (choices or {}).get('groups', []):
        choice_ids.add(group['id'])
        choice_ids.update(child['id'] for child in group['children'])
    # BWIKI skill pages carry the player-facing description; use it to break
    # ties when no client id is authoritative.
    wiki_desc = {}
    for pg in pages:
        if pg.get('type') != 'skill' or pg.get('id', 0) >= 100_000_000:
            continue
        f = pages_dir / f"{pg['id']}.js"
        if not f.is_file():
            continue
        try:
            text = f.read_text('utf8')
            doc = json.loads(text[text.index('=') + 1:].rstrip().rstrip(';'))
            desc = re.sub(r'<[^>]+>', '', str((doc.get('rawFields') or {}).get('技能描述') or ''))
            if desc:
                wiki_desc[pg.get('name')] = re.sub(r'\s+', '', desc)
        except (OSError, ValueError, IndexError):
            continue
    return wiki_names, client_tree_ids, client_page_ids, choice_ids, wiki_skill_names, wiki_desc


def build_mechanics(tables, choices=None):
    skill = tables.get('skill')
    auth = authoritative_skills(choices)
    wiki_names, client_tree_ids, client_page_ids, choice_ids, wiki_skill_names, wiki_desc = auth
    known_names = wiki_names | wiki_skill_names
    # Group every client row by display name first; only one id per name is
    # exported as the real entry and the rest are kept as compact variants.
    by_name = defaultdict(list)
    for row in skill:
        nm = plain(row.get('name'))
        if nm:
            by_name[nm].append(row)
    speciality = {r.get('id'): r for r in tables.get('speciality')}
    types = {r.get('id'): r for r in tables.get('speciality_type')}
    buffs = {r.get('id'): r for r in tables.get('buff')}
    aoe = {r.get('id'): r for r in tables.get('aoe_param')}
    diffusion = {r.get('id'): r.get('name') for r in tables.get('aoe_diffusion_mode')}
    ranges = {r.get('id'): r.get('name') for r in tables.get('range_select')}
    targets = {r.get('id'): r for r in tables.get('target_method')}

    def decode(sp):
        meta = types.get(sp.get('type'), {})
        params = []
        for index in range(4):
            key = f'param{index}'
            value = sp.get(key)
            label = meta.get(f'{key}_name') or ''
            kind = meta.get(f'{key}_type') or ''
            if value in (None, '', 0) and not label:
                continue
            display = str(value)
            extra = ''
            if kind == 'buff' and value in buffs:
                extra = plain(buffs[value].get('name') or buffs[value].get('desc'))
            elif kind == 'skill' and value:
                child = next((s for s in skill if s.get('id') == value), None)
                if child:
                    extra = plain(child.get('name'))
            elif kind == 'direction_bits':
                extra = directions(int(value or 0))
            elif kind == 'aoe_param' and value in aoe:
                row = aoe[value]
                shape = ranges.get(row.get('range_select'), '范围')
                size = int(row.get('range') or 0) & 0xFFFF
                extra = f'{shape} {size} 格 · {diffusion.get(row.get("perform_diffusion_mode"), "中心向外")} · 高差 {row.get("height")}'
            elif kind == 'attribute_type':
                extra = ''
            params.append({'name': label, 'value': value, 'display': extra, 'kind': kind})
        return {
            'id': sp.get('id'), 'typeId': sp.get('type'),
            'type': meta.get('type') or '', 'name': meta.get('name') or '',
            'editorName': plain(sp.get('editor_name') or sp.get('name') or ''),
            'targetType': sp.get('target_type'), 'activeTime': sp.get('active_time'),
            'params': params,
            'source': f"speciality#{sp.get('id')} · speciality_type#{sp.get('type')}",
        }

    def explain(decoded, skill_row):
        """Build {summary, detail, original, source} for every decoded rule.

        ``summary`` is the one-line rule (kept in ``rules`` for search/lists),
        ``detail`` explains what the client actually does and why it matches
        the skill description, ``original`` quotes the untouched client rows.
        """
        out = []

        def add(kind, summary, detail, original, source):
            out.append({'kind': kind, 'summary': summary, 'detail': detail,
                        'original': original, 'source': source})

        target = targets.get(skill_row.get('target_method') or 0, {})
        target_name = target.get('name') or '未指定'
        target_desc = target.get('desc') or ''
        if target:
            add('target', f'目标方式：{target_name}（{target_desc}）',
                '目标方式决定「点哪里」以及射程的起算点。选择地面时以射程内任意地面格为原点，'
                '随后由 AOE / 范围参数决定哪些单位会被选中；选择单位时则直接以该单位为原点。'
                '这一层发生在扣减防御与造成伤害之前，因此也决定了聚拢、击退等位移效果的坐标基准。',
                f"target_method#{skill_row.get('target_method')} · name={target_name} · desc={target_desc}",
                f"target_method#{skill_row.get('target_method')}")
        lo, hi = skill_row.get('range_min'), skill_row.get('range_max')
        if lo or hi:
            up, down = skill_row.get('attack_up'), skill_row.get('attack_down')
            add('range', f'射程 {lo} ~ {hi} 格；攻击高度 {up} / {down}',
                f'施法者与目标的距离必须落在 {lo}～{hi} 格之间（按菱形/曼哈顿距离计）。'
                f'攻击高度上限 {up}、下限 {down} 表示目标与施法者的高度差允许范围，'
                '超过范围的高台或低地格不可选。射程与范围是两个独立字段：射程决定「能指多远」，范围决定「命中几格」。',
                f"skill#{skill_row.get('id')} · range_min={lo} · range_max={hi} · attack_up={up} · attack_down={down}",
                f"skill#{skill_row.get('id')}")
        for item in decoded:
            name = item['name'] or item['type']
            values = ' '.join(f"{p['name'] or 'p' + str(i)}={p['value']}"
                              for i, p in enumerate(item['params']) if p['value'] not in (None, '', 0))
            raw = f"speciality#{item['id']} · {item['editorName'] or item['name']} · {values}".strip()
            if item['typeId'] == 40:            # AOE
                geom = next((p['display'] for p in item['params'] if p['kind'] == 'aoe_param'), '')
                add('aoe', f"范围判定：{item['editorName'] or name}{('（' + geom + '）') if geom else ''}",
                    'AOE 参数把「以目标格为原点」展开成一组候选格：形状（菱形/十字/扇形/矩形）决定覆盖哪些格，'
                    '扩散方式决定从中心向外还是从边缘开始的遍历顺序，高差决定高低差多少格仍算命中。'
                    '遍历顺序会影响聚拢、传送这类逐个落位的效果——先取到的单位先占位。'
                    + (f'本技能为 {geom}。' if geom else ''),
                    raw, item['source'])
            elif item['typeId'] in (181, 182, 183) or item['type'] == 'OTHER_TELEPORT_TO_TARGET':
                bits = next((p['value'] for p in item['params'] if p['kind'] == 'direction_bits'), 0)
                labels = directions(int(bits or 0))
                add('gather', f'聚拢规则：把范围内选中的其他单位传送到目标格身边，'
                              f'可选落点为{labels}；按 AOE 的「中心向外」顺序依次就近落位',
                    '这是客户端的 OTHER_TELEPORT_TO_TARGET（把其他单位传送到目标旁）机制，不是把目标拉向施法者：'
                    f'①先用上一条 AOE 规则选出范围内的单位；②为每个单位在目标格的{labels}寻找空位；'
                    '③按 AOE 的扩散顺序（本例为中心向外）依次处理，先处理的单位占用更靠近中心的格子；'
                    '④占位失败的后续单位顺延到更外侧，因此实际落点会随场上站位变化。'
                    '被传送的是「范围内选中的其他单位」，所以描述里的「范围 3 格内所有敌人」正来自这条链；'
                    '目标格本身与施法者不会被移动。',
                    raw, item['source'])
            elif item['typeId'] == 36:          # BUFF
                buff = next((p['display'] for p in item['params'] if p['kind'] == 'buff'), '')
                turns = next((p['value'] for p in item['params'] if p['name'] == '持续回合'), '')
                add('buff', f"施加状态：{buff or item['editorName'] or name}"
                    + (f'，持续 {turns} 回合' if turns else ''),
                    'BUFF 特效按 target_type 把状态挂到选中单位身上。状态在施放时立即生效，'
                    f'持续 {turns or '配置表'} 回合（回合数按客户端回合结算递减），'
                    '同名状态通常按层数叠加或刷新持续时间；▼表示降低、▲表示提高、✕表示禁止。'
                    '状态属于「效果」，与前面的位移是同一条特效链上的独立节点，互不影响触发顺序之外的结算。',
                    raw, item['source'])
            elif item['typeId'] == 158:         # SKILL_GROUP
                children = '、'.join(p['display'] for p in item['params'] if p['kind'] == 'skill' and p['display'])
                if children:
                    add('choice', f'可选择的技能：{children}',
                        'SKILL_GROUP（抉择）把多个子技能挂在同一个技能位上：施放时只能选其中一个，'
                        '选中后消耗、冷却与效果都按该子技能结算。子技能各自拥有独立的技能 id、图标与特效链，'
                        '所以本页为它们分别提供词条页；鼠标悬停在描述里的金色词条上仍可看到原站效果说明。',
                        raw, item['source'])
            elif item['typeId'] == 34:          # KNOCKBACK
                tiles = next((p['value'] for p in item['params'] if p['name'] == '后退格数'), '')
                add('knockback', f'击退 {tiles} 格' + (f"（{item['editorName']}）" if item['editorName'] else ''),
                    f'把目标沿「施法者→目标」方向推开 {tiles} 格；每撞到单位或地形会触发一次 '
                    'const_param#51 KnockbackImpactDamage 固定伤害，若被推下高台还会按 '
                    'const_param#52/#53 每 3 格高度结算一次坠落伤害。位移在伤害之后结算。',
                    raw, item['source'])
            elif item['editorName'] and item['typeId'] in MECHANIC_KINDS:
                add('other', f'{name}：{item["editorName"]}',
                    f'特效链上的 {name} 节点（{item["type"]}）：{item["editorName"]}。'
                    '参数释义见下方「原始特效链」，每条都标注了 speciality / speciality_type 的来源行。',
                    raw, item['source'])
        return out

    notable_ids = {14, 34, 36, 40, 94, 158, 181, 182, 183}
    notable_names = {'OTHER_TELEPORT_TO_TARGET', 'TELEPORT', 'KNOCKBACK', 'BUFF', 'AOE', 'SKILL_GROUP'}
    def pick_canonical(name, rows):
        """Return (row, authority, confidence) for the true entry."""
        wiki_text = wiki_desc.get(name, '')
        def score(row):
            sid = row.get('id') or 0
            value, why = 0, []
            if sid in choice_ids:
                value += 10000
                why.append('抉择技能分支')
            if sid in client_tree_ids:
                value += 5000
                why.append('角色技能树')
            if sid in client_page_ids:
                value += 2000
                why.append('客户端技能页')
            desc = plain(row.get('desc'))
            if wiki_text and desc:
                # Prefix overlap catches season/integer tweaks in the text.
                a = re.sub(r'\s+', '', desc)
                common = 0
                for x, y in zip(a, wiki_text):
                    if x != y:
                        break
                    common += 1
                if common >= 12:
                    value += 500 + min(common, 200)
                    why.append('与原站技能描述相符')
            if desc:
                value += 100
            tokens = [x for x in str(row.get('speciality_ids') or '').split('|') if x.strip().isdigit()]
            value += min(len(tokens), 20) * 5
            value += int(row.get('rarity') or 0) * 2
            return value, -sid, why           # earlier id wins ties
        best = max(rows, key=score)
        _, _, reasons = score(best)
        sid = best.get('id')
        if sid in choice_ids or sid in client_tree_ids or sid in client_page_ids:
            confidence = 'high'
        elif any('与原站技能描述相符' in r for r in reasons):
            confidence = 'medium'
        else:
            confidence = 'inferred'
        label = '、'.join(dict.fromkeys(reasons)) or '按特效链完整度推定'
        return best, label, confidence

    result = {}
    for name, rows in by_name.items():
        if known_names and name not in known_names and not any(
                r.get('id') in choice_ids for r in rows):
            continue
        canonical, authority, confidence = pick_canonical(name, rows)
        sid = canonical.get('id')
        tokens = [int(x) for x in str(canonical.get('speciality_ids') or '').split('|')
                  if x.strip().isdigit()]
        chain = [decode(speciality[t]) for t in tokens if t in speciality]
        chain = [item for item in chain
                 if item['typeId'] in notable_ids or item['type'] in notable_names]
        # A 抉择 branch is a real, reachable wiki entry even when its chain
        # holds no notable effect; ``explain`` still produces the target-mode
        # and range rules from the skill row itself.
        is_choice_name = any(r.get('id') in choice_ids for r in rows)
        if not chain and not is_choice_name:
            continue
        details = explain(chain, canonical)
        full, initials = soc_pinyin.spell(name) if soc_pinyin.available() else ('', '')
        variants = []
        for row in sorted(rows, key=lambda r: r.get('id') or 0):
            if row.get('id') == sid:
                continue
            desc = plain(row.get('desc'))
            variants.append({'id': row.get('id'), 'desc': desc[:180],
                             'range': [row.get('range_min'), row.get('range_max')],
                             'editorName': plain(row.get('editor_name') or ''),
                             'chain': str(row.get('speciality_ids') or '')[:120]})
        result[str(sid)] = {
            'name': name, 'py': full, 'ini': initials,
            'desc': plain(canonical.get('desc')),
            'authority': authority, 'confidence': confidence,
            'variantCount': len(variants), 'variants': variants,
            'targetName': (targets.get(canonical.get('target_method')) or {}).get('name') or '',
            'range': [canonical.get('range_min'), canonical.get('range_max')],
            'chain': chain,
            'rules': [d['summary'] for d in details],
            'details': details,
            'original': {'skillDesc': plain(canonical.get('desc')), 'skillName': name},
        }
    return {
        'v': 1, 'skills': result,
        'glossary': {
            'targetMethods': [{'id': r.get('id'), 'name': r.get('name')} for r in targets.values()],
            'rangeShapes': [{'id': k, 'name': v} for k, v in sorted(ranges.items())],
            'diffusion': [{'id': k, 'name': v} for k, v in sorted(diffusion.items())],
        },
    }


def icon_sources():
    """Map ``icon_skill_xxx`` names to archive object files (one real copy)."""
    versions = ROOT / 'output' / 'archive' / 'versions'
    if not versions.is_dir():
        return {}
    folders = sorted((p for p in versions.iterdir() if p.is_dir()), reverse=True)
    for folder in folders:
        manifest = folder / 'manifest.json.gz'
        if not manifest.is_file():
            continue
        try:
            data = json.loads(gzip.decompress(manifest.read_bytes()))
            fields = data['fields']
            rows = [dict(zip(fields, e)) for e in data['entries']]
        except (OSError, ValueError, KeyError):
            continue
        result = {}
        objects = ROOT / 'output' / 'archive' / 'objects'
        for row in rows:
            path = row.get('path') or ''
            if 'image/icon/skill/' not in path or not path.lower().endswith('.png'):
                continue
            stem = Path(path).stem
            blob = objects / str(row.get('hash') or '')[:2] / (str(row.get('hash') or '') + (row.get('ext') or '.png'))
            if blob.is_file():
                result.setdefault(stem, blob)
        return result
    return {}


def build_choice_previews(tables, choices, dry_run=False):
    """Give each 抉择 branch a skill icon and a pre-rendered range diagram.

    Icons come from the client's ``image/icon/skill/`` bundles (already in the
    resource archive); range diagrams use the same ``socdecode.ranges`` planner
    the skill pages use, so a reader can preview the effect without leaving the
    choice page. Missing art simply leaves the field empty and the UI hides it.
    """
    from socdecode import ranges
    skill = {r.get('id'): r for r in tables.get('skill')}
    icons = icon_sources()
    icon_dir = ROOT / 'assets' / 'skill-icons'
    range_dir = ROOT / 'assets' / 'updates'
    if not dry_run:
        icon_dir.mkdir(parents=True, exist_ok=True)
        range_dir.mkdir(parents=True, exist_ok=True)
    previews = {}
    icon_count = range_count = 0
    for group in choices.get('groups', []):
        for child in group['children']:
            row = skill.get(child['id']) or {}
            item = {'icon': '', 'iconFile': '', 'rangeImage': '', 'rangeLabel': '',
                    'rangeText': '', 'facts': {}}
            icon_name = child.get('icon') or row.get('icon') or ''
            item['icon'] = icon_name
            if icon_name:
                target = icon_dir / (icon_name + '.png')
                if not target.is_file() and icon_name in icons and not dry_run:
                    shutil.copyfile(icons[icon_name], target)
                if target.is_file():
                    item['iconFile'] = f'assets/skill-icons/{icon_name}.png'
                    icon_count += 1
            lo, hi = row.get('range_min'), row.get('range_max')
            item['facts'] = {
                '消耗': row.get('tp'), '冷却': row.get('cooldown'),
                '射程': f'{lo} ~ {hi}' if lo is not None and hi is not None else '',
                '类别': plain(row.get('desc') or '').partition('）')[0].removeprefix('（') if str(row.get('desc') or '').startswith('（') else '',
            }
            try:
                diagram = ranges.plan(row)
            except (KeyError, TypeError, ValueError):
                diagram = None
            if diagram:
                item['rangeLabel'] = diagram.get('label') or ''
                item['rangeText'] = diagram.get('note') or ''
                try:
                    content = ranges.render_png(diagram)
                    name = 'range-' + hashlib.sha256(content).hexdigest()[:24] + '.webp'
                    if not dry_run:
                        (range_dir / name).write_bytes(content)
                    item['rangeImage'] = f'assets/updates/{name}'
                    range_count += 1
                except (OSError, ValueError, ImportError):
                    pass
            previews[str(child['id'])] = item
    print(f'  抉择分支预览：技能图标 {icon_count} 个 · 作用范围图 {range_count} 张')
    choices['previews'] = previews
    return choices


def write(path: Path, variable: str, data, dry_run=False):
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    print(f'  {path.name}: {len(payload.encode("utf8")) / 1048576:.2f} MB')
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'/* Generated by scripts/extract_battle_rules.py from local client tables. */\n'
                        f'window.{variable}={payload};\n', 'utf8')


def main():
    parser = argparse.ArgumentParser(description='导出战斗公式常量、抉择技能与技能机制规则')
    parser.add_argument('--game', help='游戏客户端目录（默认读本地配置）')
    parser.add_argument('--source', choices=('auto', 'archive', 'client'), default='auto')
    parser.add_argument('--dry-run', action='store_true', help='只统计，不写文件')
    args = parser.parse_args()

    from socdecode.client import game_root
    from socdecode.config import game_path
    if args.source == 'archive' and not ARCHIVE_CFG.is_dir():
        skip('没有找到已解密的配置表目录', f'期望位置：{ARCHIVE_CFG}')
        return
    game = None
    try:
        game = game_root(Path(args.game) if args.game else game_path())
    except (ValueError, OSError):
        if not ARCHIVE_CFG.is_dir():
            skip('没有找到游戏客户端，也没有资源归档')
            return
    tables = Tables(game, args.source)
    try:
        print('数据来源：' + ('本地资源归档（已解密配置表）' if tables.mode == 'archive' else '游戏客户端 Lua 资源包'))
        if not tables.get('skill'):
            skip('没有读到 skill 表')
            return
        combat = build_combat(tables)
        choices = build_choices(tables)
        choices = build_choice_previews(tables, choices, args.dry_run)
        mechanics = build_mechanics(tables, choices)
    finally:
        tables.close()
    print(f"战斗常量 {len(combat['constants'])} 项 · 职业克制 {len(combat['restraints'])} 条 · "
          f"抉择技能 {len(choices['groups'])} 组 · 机制技能 {len(mechanics['skills'])} 个")
    for group in choices['groups'][:3]:
        print(f"  {group['name']}: " + '、'.join(c['name'] for c in group['children']))
    sample = mechanics['skills'].get('7433')
    if sample:
        print(f"  人为财死规则示例：{sample['rules'][:2]}")
    write(OUT_COMBAT, 'WIKI_COMBAT_DATA', combat, args.dry_run)
    write(OUT_CHOICES, 'WIKI_CHOICE_SKILLS', choices, args.dry_run)
    write(OUT_MECHANICS, 'WIKI_SKILL_MECHANICS', mechanics, args.dry_run)


if __name__ == '__main__':
    main()
