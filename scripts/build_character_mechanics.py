"""Generate per-character battle-mechanism documentation from client tables.

For every character in the offline archive (playable roster + 乐土群星杯
fighters) this resolves the full skill chain and writes:

  data/character-mechanics.js   browsable, lazy-loaded dataset
  docs/character-mechanics.md   human-readable reference (one section each)

Each entry lists the character's kit, every speciality type they use, dynamic
Lua parameters, activation conditions, interactive objects and summons, and
whether the simulator implements the mechanism. Nothing is hand-written: all
facts come from the local decrypted client config tables.

    python -X utf8 scripts/build_character_mechanics.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / 'output' / 'archive' / 'library' / '当前版本' / '配置表'
OUT_JS = ROOT / 'data' / 'character-mechanics.js'
OUT_MD = ROOT / 'docs' / 'character-mechanics.md'


def load_js(name, var):
    text = (ROOT / 'data' / name).read_text('utf8')
    marker = 'window.' + var + '='
    return json.JSONDecoder().raw_decode(text[text.index(marker) + len(marker):])[0]


def table(name):
    for p in CFG.rglob(name + '.json'):
        try:
            return json.loads(p.read_text('utf8'))
        except ValueError:
            pass
    return []


def clean(s):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]*>', '', str(s or ''))).strip()


def n(v, d=0):
    try:
        return int(float(str(v if v not in (None, '') else d)))
    except (TypeError, ValueError):
        return d


# Mechanism categories used by the documentation. A character "uses" a
# mechanism when any speciality in their resolved skill closure has that type.
CATEGORIES = {
    '召唤物': ['PLACE_UNIT', 'PLACE_UNIT_INHERIT_ATTR'],
    '交互物': ['PLACE_ITEM', 'PLACE_TRAP', 'REMOVE_PROPS', 'TRIGGER_TRAP',
             'CHANGE_TRAP', 'WIDGET_SWITCH', 'ACTIVATION'],
    '动态参数': ['DYNAMIC_PARAM'],
    '属性转换': ['CONVERT_ATTRIBUTE', 'PREWAR_CONVERT_ATTRIBUTE'],
    '实时属性/护盾': ['PHYSIC_ARMOR', 'SPELL_ARMOR', 'MODIFY_ATTRIBUTE',
                'BUFF_STACK_MODIFY_ATTRIBUTE'],
    '再行动/额外回合': ['RE_ROUND', 'ACTED_ACT', 'ACTED_MOVE', 'ADDITIONAL_ATTACK',
                  'ASSIST_ATTACK', 'COUNTER_ATTACK'],
    '位移/传送': ['TARGET_TELEPORT', 'JUMP_MOVE', 'TELEPORT', 'BLINK',
              'EXCHANGE_POSITION', 'HOOK', 'KNOCKBACK'],
    '状态链': ['BUFF', 'BUFF_BUNDLE_GAIN', 'BUFF_ADD_REPLACE', 'DISPEL',
            'REMOVE_BUFF', 'BUFF_TRANSFER'],
    '技能链': ['CAST_SKILL', 'MAKE_OTHER_CAST_SKILL', 'GET_EXTRA_SKILL',
            'REPLACE_SKILL', 'DELAY_SKILL', 'SKILL_CD'],
    '伤害/治疗': ['DAMAGE', 'PERCENT_HEAL', 'RECOVER_ATTRIBUTE', 'LIFE_LOST',
              'SHARE_DAMAGE', 'PARASITIC', 'DAMAGE_STORAGE'],
    '变身/形态': ['SHAPESHIFT', 'BODY_REPLACE', 'SKILL_HEIGHT'],
    '条件触发': ['ACTIVATION', 'FORBIDDEN_REACTIVE', 'IMMUNE', 'EVADE', 'PARRY'],
}


def main() -> int:
    if not CFG.is_dir():
        print('跳过角色机制文档：缺少本地客户端配置表。')
        return 0
    mech = load_js('battle-mech.js', 'WIKI_BATTLE_MECH')
    sim = load_js('battle-sim.js', 'WIKI_BATTLE_SIM')
    try:
        cup = load_js('match-cup.js', 'WIKI_MATCH_CUP')
    except (OSError, ValueError):
        cup = {'teams': [], 'schedules': []}

    specs = {str(k): v for k, v in mech['specs'].items()}
    skills = {str(k): v for k, v in mech['skills'].items()}
    summons = mech.get('summons', {})
    props = mech.get('props', {})
    traps = mech.get('traps', {})
    buffs = mech.get('buffs', {})

    skill_rows = {n(r.get('id')): r for r in table('skill')}
    npc_rows = {n(r.get('id')): r for r in table('unit_npc')}

    # Implemented effect types are read straight from the engine source, so
    # the documentation reports the simulator's real coverage, not a guess.
    core = (ROOT / 'battle-sim-core.js').read_text('utf8')
    i = core.index('    const EFFECTS = {')
    j = core.index('\n    };', i)
    handlers = set(re.findall(r'^      ([A-Z_]+)\s*\(', core[i:j], re.M))
    si = core.index('const STATIC_TYPES')
    static = set(re.findall(r"'([A-Z_]+)'", core[si:core.index(']);', si)]))
    implemented = handlers | static

    def chain(ids, depth=0):
        """Walk skill -> speciality -> referenced skill/buff -> speciality."""
        found, seen = [], set()
        stack = [(x, depth) for x in ids if x]
        while stack:
            sid, d = stack.pop()
            sid = str(sid)
            if sid in seen or sid not in skills or d > 3:
                continue
            seen.add(sid)
            sk = skills[sid]
            found.append(sid)
            for sp in sk.get('sp') or []:
                raw = specs.get(str(sp))
                if not raw:
                    continue
                linked = []
                if raw['t'] in ('CAST_SKILL', 'MAKE_OTHER_CAST_SKILL', 'DELAY_CAST_SKILL',
                                'FORCE_CAST_SKILL', 'CONDITION_SKILL', 'ADDITIONAL_ATTACK'):
                    linked.append(raw['p'][0])
                if raw['t'] in ('BUFF', 'BUFF_BUNDLE_GAIN', 'BUFF_ADD_REPLACE'):
                    for spid in (buffs.get(str(raw['p'][0])) or {}).get('sp', []):
                        sub_spec = specs.get(str(spid))
                        if sub_spec and sub_spec['t'] in ('CAST_SKILL', 'MAKE_OTHER_CAST_SKILL'):
                            linked.append(sub_spec['p'][0])
                for skill_id in linked:
                    if skill_id and str(skill_id) in skills:
                        stack.append((str(skill_id), d + 1))
        return found, seen

    # Collect every character and the kits they use (roster + cup variants).
    chars = {}
    for r in sim.get('roster', []):
        name = r.get('name')
        if not name:
            continue
        rec = chars.setdefault(name, {'name': name, 'pageId': r.get('pageId') or 0,
                                      'kits': [], 'npcIds': set(), 'sources': {'角色图鉴'}})
        rec['kits'].append(('图鉴角色', r.get('kit') or {}))
        if r.get('kit', {}).get('unitId'):
            rec['unitId'] = r['kit']['unitId']
    for t in cup.get('teams', []):
        for m in t.get('members', []):
            name = m.get('name')
            if not name:
                continue
            rec = chars.setdefault(name, {'name': name, 'pageId': 0, 'kits': [],
                                          'npcIds': set(), 'sources': set()})
            rec['kits'].append(('群星杯', m.get('kit') or {}))
            if m.get('npcId'):
                rec['npcIds'].add(n(m['npcId']))
            rec['sources'].add('乐土群星杯')

    def kit_ids(kit):
        out = [kit.get('basic')]
        for k in ('actives', 'initial', 'reactive', 'leader', 'feature', 'personality',
                  'chain', 'bossSequence', 'choice', 'derived', 'eliteComp', 'module'):
            out += list(kit.get(k) or [])
        out += [x[2] for x in kit.get('ranks') or []]
        return [x for x in out if x]

    doc = {}
    for name, rec in sorted(chars.items()):
        all_ids = []
        for _src, kit in rec['kits']:
            all_ids += kit_ids(kit)
        own, closure = chain(all_ids)
        sp_types = Counter()
        conditions, dynamics, objects, summon_names = 0, 0, [], []
        skill_list = []
        for sid in own[:40]:
            sk = skills.get(str(sid), {})
            sts = []
            for sp in sk.get('sp') or []:
                raw = specs.get(str(sp))
                if not raw:
                    continue
                sp_types[raw['t']] += 1
                if raw.get('c'):
                    conditions += 1
                if raw.get('dp'):
                    dynamics += 1
                if raw['t'] in ('PLACE_ITEM', 'PLACE_UNIT', 'PLACE_TRAP'):
                    pid = raw['p'][0]
                    if raw['t'] == 'PLACE_UNIT' and pid >= 100:
                        s = summons.get(str(pid))
                        if s:
                            summon_names.append(s['n'])
                    if raw['t'] == 'PLACE_ITEM':
                        s = props.get(str(pid))
                        if s:
                            objects.append(s['n'])
                    if raw['t'] == 'PLACE_TRAP':
                        s = traps.get(str(pid))
                        if s:
                            objects.append(s['n'])
                sts.append(raw['t'])
            row = skill_rows.get(n(sid), {})
            skill_list.append({'id': n(sid), 'name': sk.get('n') or row.get('name') or f'技能 {sid}',
                               'desc': clean(row.get('desc'))[:120],
                               'types': sorted(set(sts))[:14]})
        categories = []
        for label, types in CATEGORIES.items():
            hits = {t: sp_types[t] for t in types if sp_types[t]}
            if hits:
                missing = [t for t in types if t not in implemented]
                categories.append({'label': label, 'types': hits,
                                   'status': '完整' if not missing else '部分',
                                   'missing': missing})
        unimplemented = sorted({t for t in sp_types if t not in implemented})
        # Personality skills are the character's defining passive kit. Resolve
        # them with descriptions and every speciality so the reference can show
        # exactly what each personality does and how it is implemented.
        personality = []
        timings = (mech.get('enums') or {}).get('activeTime') or {}
        for _label, kit in (rec.get('kits') or []):
            for pid in (kit.get('personality') or []):
                sk = skills.get(str(pid))
                if not sk or any(x['id'] == pid for x in personality):
                    continue
                eff = []
                for sid in (sk.get('sp') or []):
                    sp = specs.get(str(sid))
                    if not sp:
                        continue
                    eff.append({'id': sid, 'type': sp.get('t'), 'timing': timings.get(str(sp.get('at'))),
                                'at': sp.get('at'), 'params': sp.get('p'), 'name': sp.get('n', ''),
                                'condition': (sp.get('c') or '')[:180],
                                'dynamic': (sp.get('dp') or '')[:180],
                                'implemented': sp.get('t') in implemented})
                personality.append({'id': pid, 'name': sk.get('n') or '',
                                    'desc': clean(sk.get('desc') or ''),
                                    'effects': eff,
                                    'types': sorted({e['type'] for e in eff if e['type']})})
        doc[name] = {
            'personality': personality,
            'name': name, 'pageId': rec.get('pageId') or 0,
            'unitId': rec.get('unitId') or 0,
            'npcIds': sorted(rec['npcIds'])[:8],
            'sources': sorted(rec['sources']),
            'skillCount': len(own), 'closureSkills': len(closure),
            'skills': skill_list,
            'effectTypes': dict(sp_types.most_common(18)),
            'conditions': conditions, 'dynamics': dynamics,
            'objects': sorted(set(objects))[:8], 'summons': sorted(set(summon_names))[:8],
            'categories': categories,
            'unimplemented': unimplemented,
            'coverage': round(100 * (1 - len(unimplemented) / max(1, len(sp_types))), 1),
        }

    payload = {
        'meta': {
            'characters': len(doc), 'skills': len(skills), 'specs': len(specs),
            'implementedTypes': len(implemented), 'summonTemplates': len(summons),
            'personalitySkills': sum(len(v.get('personality') or []) for v in doc.values()),
            'generatedFrom': ['skill', 'speciality', 'speciality_type', 'buff', 'unit_npc',
                              'unit', 'unit_modify_level', 'props', 'trap', 'widget',
                              'data/battle-sim.js', 'data/match-cup.js', 'battle-sim-core.js'],
            'note': '逐角色机制来自客户端配置表与模拟器实现对照；「部分」表示该机制下有尚未实现的子类型。',
        },
        'categories': {k: v for k, v in CATEGORIES.items()},
        'characters': doc,
    }
    OUT_JS.write_text('window.WIKI_CHARACTER_MECHANICS=' +
                      json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + ';\n', 'utf8')

    # ---- Markdown reference -------------------------------------------------
    lines = [
        '# 逐角色战斗机制说明',
        '',
        f"> 本文件由 `scripts/build_character_mechanics.py` 自动生成，覆盖 **{len(doc)} 名角色**、"
        f"{len(skills)} 个客户端技能与 {len(specs)} 条效果。"
        '数据来源为本地客户端配置表（skill / speciality / buff / props / trap / unit_npc 等）与模拟器实现清单；'
        '不是人工推断。',
        '',
        '## 机制分类与实现口径',
        '',
        '| 分类 | 客户端效果类型 | 模拟器状态 |',
        '| --- | --- | --- |',
    ]
    for label, types in CATEGORIES.items():
        missing = [t for t in types if t not in implemented]
        lines.append(f'| {label} | {", ".join("`" + t + "`" for t in types)} | '
                     + ('完整' if not missing else '部分：' + ', '.join(missing)) + ' |')
    lines += ['', '## 角色索引', '',
              '| 角色 | 技能数 | 机制分类 | 覆盖率 |',
              '| --- | ---: | --- | ---: |']
    for name, d in doc.items():
        lines.append(f'| [{name}](#{name.replace(" ", "-")}) | {d["skillCount"]} | '
                     + '、'.join(x['label'] for x in d['categories'][:6]) +
                     f' | {d["coverage"]}% |')
    lines += ['', '## 逐角色明细', '']
    for name, d in doc.items():
        lines += [f'### {name}', '']
        meta = []
        if d['unitId']:
            meta.append(f'unit_id {d["unitId"]}')
        if d['npcIds']:
            meta.append('unit_npc ' + ', '.join(str(x) for x in d['npcIds']))
        meta += d['sources']
        lines += ['*' + ' · '.join(meta) + '*', '',
                  f'技能 {d["skillCount"]} 个（闭包 {d["closureSkills"]} 个）· '
                  f'Lua 激活条件 {d["conditions"]} 条 · dynamic_param {d["dynamics"]} 条 · '
                  f'已实现效果类型覆盖率 {d["coverage"]}%。', '']
        if d['summons']:
            lines += ['**召唤物**：' + '、'.join(d['summons']) + '（各自拥有 HP、技能与行动回合）', '']
        if d['objects']:
            lines += ['**交互物**：' + '、'.join(d['objects']) + '（按客户端触发类型结算）', '']
        if d.get('personality'):
            lines += [f'**个性效果**（{len(d["personality"])} 个客户端个性技能）', '']
            for ps in d['personality']:
                lines.append(f'- **{ps["name"]}** (`#{ps["id"]}`)：{ps["desc"] or "—"}')
                for e in ps['effects']:
                    flag = '已实现' if e['implemented'] else '待实现'
                    bits = [f'`{e["type"]}`', e['timing'] or ('at ' + str(e['at'])), flag]
                    if e['params'] and any(e['params']):
                        bits.append('参数 ' + '/'.join(str(x) for x in e['params'] if x is not None))
                    lines.append('  - ' + ' · '.join(bits))
                    if e['condition']:
                        lines.append(f'    - 条件：`{e["condition"]}`')
                    if e['dynamic']:
                        lines.append(f'    - 动态参数：`{e["dynamic"]}`')
            lines.append('')
        if d['categories']:
            lines += ['| 机制分类 | 效果类型 / 次数 | 状态 |', '| --- | --- | --- |']
            for c in d['categories']:
                detail = '、'.join(f'`{k}` ×{v}' for k, v in c['types'].items())
                lines.append(f'| {c["label"]} | {detail} | {c["status"]} |')
            lines.append('')
        if d['unimplemented']:
            lines += ['> 尚未实现：' + ', '.join('`' + x + '`' for x in d['unimplemented']), '']
        notable = [s for s in d['skills'] if s['desc']][:5]
        if notable:
            lines += ['<details><summary>关键技能与客户端原文</summary>', '']
            for s in notable:
                lines += [f'- **{s["name"]}** (`#{s["id"]}`)：{s["desc"]}',
                          '  - 效果：' + (', '.join('`' + t + '`' for t in s['types']) or '—')]
            lines += ['', '</details>', '']
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text('\n'.join(lines) + '\n', 'utf8')

    print(f'逐角色机制文档：{len(doc)} 名角色 · {len(implemented)} 类已实现效果 → '
          f'{OUT_JS.relative_to(ROOT)} ({OUT_JS.stat().st_size // 1024} KiB), '
          f'{OUT_MD.relative_to(ROOT)} ({OUT_MD.stat().st_size // 1024} KiB)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
