"""Create skill entries for the branches of every 抉择 skill.

``scripts/extract_battle_rules.py`` writes ``data/choice-skills.js`` with the
authoritative parent -> child mapping (from ``speciality`` rows of type 158).
This script gives each child a real, linkable skill page:

* children that already have a wiki skill page are reused;
* the rest get a client-style page at ``100000000 + skillId``, the same id rule
  ``socdecode/wiki.py`` uses for client skill pages;
* ``data/index.js``, ``search.js``, ``advanced-search.js`` and ``pinyin.js``
  are extended so navigation and search work offline.

Called from ``socdecode.rebuild.run()`` after ``plan_update`` has written the
index, so it is idempotent and survives every update.

Usage:
    python -X utf8 scripts/build_choice_pages.py --dry-run
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

CHOICES = ROOT / 'data' / 'choice-skills.js'
INDEX = ROOT / 'data' / 'index.js'
PAGES = ROOT / 'data' / 'pages'
SEARCH = ROOT / 'data' / 'search.js'
ADVANCED = ROOT / 'data' / 'advanced-search.js'
ID_BASE = 100_000_000


def read_js(path: Path, variable: str):
    text = path.read_text('utf8')
    marker = f'window.{variable}='
    start = text.index(marker) + len(marker)
    data, end = json.JSONDecoder().raw_decode(text[start:])
    return data, text[:text.index(marker)]


def write_js(path: Path, variable: str, data, prefix='', newline=True):
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    path.write_text(prefix + f'window.{variable}=' + payload + ';' + ('\n' if newline else ''), 'utf8')


def load_choices():
    if not CHOICES.is_file():
        return None
    data, _ = read_js(CHOICES, 'WIKI_CHOICE_SKILLS')
    return data


def build():
    choices = load_choices()
    if not choices or not choices.get('groups'):
        print('没有抉择技能数据，跳过词条页生成。')
        return 0
    previews = choices.get('previews') or {}
    payload, head = read_js(INDEX, 'WIKI_DATA')
    pages = payload['pages']
    by_id = {p['id']: p for p in pages}
    skill_by_name = {}
    for p in pages:
        if p.get('type') == 'skill':
            skill_by_name.setdefault(p.get('name', ''), p)

    search = json.loads(SEARCH.read_text('utf8')[len('window.WIKI_SEARCH='):].rstrip().rstrip(';')) \
        if SEARCH.is_file() else {}
    advanced = json.loads(ADVANCED.read_text('utf8')[len('window.WIKI_ADVANCED_DATA='):].rstrip().rstrip(';')) \
        if ADVANCED.is_file() else {}

    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    created = reused = 0
    pending_docs = []
    mapping = {}          # parent skill id -> [{id, name, pageId}]
    parent_pages = {}     # child page id -> [{parentName, parentPageId}]

    for group in choices['groups']:
        parent_page = by_id.get(ID_BASE + group['id'])
        if parent_page is None:
            parent_page = skill_by_name.get(group['name'])
        parent_page_id = parent_page['id'] if parent_page else None
        entries = []
        for child in group['children']:
            cid = child['id']
            existing = by_id.get(ID_BASE + cid) or skill_by_name.get(child['name'])
            page_id = existing['id'] if existing else ID_BASE + cid
            if page_id in by_id:
                reused += 1
                # Existing generated pages may predate the icon/range export;
                # refresh those fields without touching original wiki pages.
                path = PAGES / f'{page_id}.js'
                preview = previews.get(str(cid), {})
                if path.is_file() and (parent_page_id or (page_id >= ID_BASE and preview)):
                    try:
                        text = path.read_text('utf8')
                        doc = json.loads(text[text.index('=') + 1:].rstrip().rstrip(';'))
                        dirty = False
                        if parent_page_id and parent_page_id not in (doc.get('related') or []):
                            doc['related'] = (doc.get('related') or []) + [parent_page_id]
                            doc['choiceParent'] = {'skillId': group['id'], 'name': group['name'],
                                                   'pageId': parent_page_id}
                            dirty = True
                        if page_id >= ID_BASE and preview and not doc.get('choicePreview'):
                            doc['choicePreview'] = preview
                            doc['clientRange'] = {'image': preview.get('rangeImage') or '',
                                                  'label': preview.get('rangeLabel') or ''}
                            if preview.get('rangeImage'):
                                doc['html'] = (doc.get('html') or '') + (
                                    f'<figure class="skill-range"><div class="range-heading"><span>作用范围</span>'
                                    f'<small>{html.escape(preview.get("rangeLabel") or "")}</small></div>'
                                    f'<img src="{html.escape(preview["rangeImage"])}" alt="技能范围" width="180" height="180"></figure>')
                            dirty = True
                        if dirty:
                            pending_docs.append((page_id, doc))
                    except (OSError, ValueError, IndexError):
                        pass
            else:
                name = child['name']
                desc = child.get('desc') or child.get('keywordDesc') or ''
                summary = re.sub(r'\s+', ' ', desc)[:220]
                preview = previews.get(str(cid), {})
                entry = {
                    'id': page_id, 'title': '技能图鉴库/' + name, 'name': name, 'type': 'skill',
                    'image': preview.get('iconFile') or '', 'date': today,
                    'summary': summary, 'categories': ['抉择技能分支'],
                    'class': '', 'rarity': '', 'faction': '', 'weapon': '', 'aliases': [],
                    'redirect': '', 'sourceOrder': 2, 'choiceParent': group['id'],
                }
                pages.append(entry)
                by_id[page_id] = entry
                skill_by_name.setdefault(name, entry)
                fields = {'技能名称': html.escape(name), '技能描述': html.escape(desc)}
                if child.get('cost') is not None:
                    fields['技能消耗'] = html.escape(str(child['cost']))
                if child.get('cooldown') is not None:
                    fields['技能冷却'] = html.escape(str(child['cooldown']))
                rng = child.get('range') or []
                if any(rng):
                    fields['技能射程'] = html.escape(f'{rng[0]} ~ {rng[1]}')
                fields['所属抉择技能'] = html.escape(group['name'])
                if preview.get('iconFile'):
                    fields['技能图标'] = html.escape(preview['iconFile'])
                if preview.get('rangeLabel'):
                    fields['作用范围'] = html.escape(preview['rangeLabel'])
                icon_html = (f'<img class="choice-skill-icon" src="{html.escape(preview["iconFile"])}" alt="" width="64" height="64">'
                             if preview.get('iconFile') else '')
                range_html = (f'<figure class="skill-range"><div class="range-heading"><span>作用范围</span>'
                              f'<small>{html.escape(preview["rangeLabel"])}</small></div>'
                              f'<img src="{html.escape(preview["rangeImage"])}" alt="技能范围 {html.escape(preview["rangeLabel"])}" width="180" height="180">'
                              f'</figure>' if preview.get('rangeImage') else '')
                doc = {
                    'id': page_id, 'title': entry['title'], 'fields': fields,
                    'rawFields': {k: re.sub(r'<[^>]+>', '', v) for k, v in fields.items()},
                    'related': [parent_page_id] if parent_page_id else [],
                    'recoveredFields': [], 'revision': 1, 'date': today,
                    'sections': [], 'source': '', 'hasOnlineMedia': False,
                    'html': icon_html + '<div class="ability-description">' + html.escape(desc) + '</div>' + range_html,
                    'choiceParent': {'skillId': group['id'], 'name': group['name'],
                                     'pageId': parent_page_id},
                    'choiceSkillId': cid,
                    'choicePreview': previews.get(str(cid), {}),
                    'clientRange': {'image': preview.get('rangeImage') or '',
                                    'label': preview.get('rangeLabel') or ''},
                }
                pending_docs.append((page_id, doc))
                search[str(page_id)] = ' '.join([name, '技能图鉴库', group['name'], summary])
                advanced[str(page_id)] = {'fields': doc['rawFields'], 'related': doc['related']}
                created += 1
            entries.append({'id': cid, 'name': child['name'], 'pageId': page_id,
                            'preview': previews.get(str(cid), {})})
            parent_pages.setdefault(page_id, []).append(
                {'name': group['name'], 'skillId': group['id'], 'pageId': parent_page_id})
        mapping[str(group['id'])] = {'name': group['name'], 'pageId': parent_page_id,
                                     'children': entries}

    return {'created': created, 'reused': reused, 'mapping': mapping,
            'parentPages': parent_pages, 'payload': payload, 'head': head,
            'search': search, 'advanced': advanced, 'choices': choices,
            'pendingDocs': pending_docs}


def apply(result, dry_run=False):
    created, reused = result['created'], result['reused']
    print(f'抉择技能：新建词条页 {created} 个，复用已有页面 {reused} 个，共 {len(result["mapping"])} 组')
    if dry_run:
        return
    if not created and not reused:
        return
    # Nothing new: keep the (large) index files byte-for-byte as they are.
    choices = result['choices']
    if not created and not result['pendingDocs'] and choices.get('branches') and choices.get('pages'):
        return
    for page_id, doc in result['pendingDocs']:
        (PAGES / f'{page_id}.js').write_text(
            f'window.WIKI_PAGES[{page_id}]=' +
            json.dumps(doc, ensure_ascii=False, separators=(',', ':')) + ';\n', 'utf8')
    # Keep the choices file self-contained so the UI can jump without guessing.
    choices['pages'] = {str(k): v['pageId'] for k, v in result['mapping'].items() if v['pageId']}
    if 'previews' not in choices:
        choices['previews'] = {}
    choices['branches'] = result['mapping']
    choices['backlinks'] = {str(k): v for k, v in result['parentPages'].items()}
    write_js(CHOICES, 'WIKI_CHOICE_SKILLS', choices,
             '/* Generated by scripts/extract_battle_rules.py + build_choice_pages.py. */\n')

    payload = result['payload']
    # Keep the sidebar counts truthful after adding skill pages.
    counts = {}
    for page in payload['pages']:
        counts[page['type']] = counts.get(page['type'], 0) + 1
    if payload.get('archive', {}).get('counts'):
        payload['archive']['counts'] = counts
    text = result['head'] + 'window.WIKI_DATA=' + json.dumps(payload, ensure_ascii=False, separators=(',', ':')) \
        + ';\nwindow.WIKI_PAGES={};\n'
    # Preserve any trailing declarations the original index had.
    INDEX.write_text(text, 'utf8')
    # ``data/archive.json`` describes the original BWIKI snapshot; it is left
    # untouched on purpose. Only the live index needs the new counts.
    if SEARCH.is_file():
        write_js(SEARCH, 'WIKI_SEARCH', result['search'])
    if ADVANCED.is_file():
        write_js(ADVANCED, 'WIKI_ADVANCED_DATA', result['advanced'])
    try:
        from socdecode import pinyin
        if pinyin.available():
            write_js(ROOT / 'data' / 'pinyin.js', 'WIKI_PINYIN', pinyin.build(payload['pages']))
            print('  拼音索引已同步')
    except (ImportError, OSError, ValueError) as error:
        print('  拼音索引未能同步：', error)


def main():
    parser = argparse.ArgumentParser(description='生成抉择技能的分支技能词条页')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    result = build()
    if isinstance(result, int):
        return
    apply(result, args.dry_run)


if __name__ == '__main__':
    main()
