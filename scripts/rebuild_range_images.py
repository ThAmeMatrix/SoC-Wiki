"""Redraw every skill range diagram with the blue/red overlay used by 抉择 previews.

``socdecode/ranges.render_png`` draws a flat blue cast range and red area of
effect when called without ``tiles``. The wiki update used to pass the client's
in-battle grid textures instead (small orange/cream icons), so skill pages and
choice previews showed two different diagrams for the same skill. This script
redraws all of them into one consistent style, in place:

* pages that already have ``clientRange.image`` keep their filename (the bytes
  are overwritten), so no page reference changes;
* pages that only carry an archived BWIKI range picture get a generated
  ``clientRange.image`` and the old picture is removed from ``doc.html``;
* plans come from the client ``skill`` table, so nothing is guessed.

Usage:
    python -X utf8 scripts/rebuild_range_images.py --dry-run
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from socdecode import ranges  # noqa: E402
from socdecode.transaction import sha  # noqa: E402
from extract_battle_rules import Tables, ARCHIVE_CFG, plain  # noqa: E402

PAGES = ROOT / 'data' / 'pages'
UPDATES = ROOT / 'assets' / 'updates'
# Only archived BWIKI pictures need removing from doc.html; the client's own
# generated <img class="range-diagram"> is intentionally left alone.
RANGE_IMG = re.compile(r'<img[^>]*src="assets/wiki/[^"]*"[^>]*alt="[^"]*技能范围[^"]*"[^>]*>|'
                       r'<img[^>]*alt="[^"]*技能范围[^"]*"[^>]*src="assets/wiki/[^"]*"[^>]*>')


def load_skill_rows():
    from socdecode.client import game_root
    from socdecode.config import game_path
    try:
        game = game_root(game_path())
    except (ValueError, OSError):
        game = None
    if game is None and not ARCHIVE_CFG.is_dir():
        return {}, {}
    tables = Tables(game, 'auto')
    try:
        rows = tables.get('skill')
        by_id = {r.get('id'): r for r in rows}
        by_name = {}
        for row in rows:
            name = plain(row.get('name'))
            if name:
                by_name.setdefault(name, row)
        return by_id, by_name
    finally:
        tables.close()


def main():
    parser = argparse.ArgumentParser(description='把所有技能范围图统一为蓝底射程 / 红底作用范围')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    skills, skills_by_name = load_skill_rows()
    if not skills:
        print('没有读到 skill 表，跳过范围图重绘。')
        return
    print(f'客户端技能 {len(skills):,} 行')
    if not args.dry_run:
        UPDATES.mkdir(parents=True, exist_ok=True)

    plans, drawn = {}, {}

    def plan_of(sid):
        if sid not in plans:
            try:
                plans[sid] = ranges.plan(skills[sid])
            except (KeyError, TypeError, ValueError):
                plans[sid] = None
        return plans[sid]

    def draw(sid, preferred=None):
        """Write the blue/red bytes; reuse ``preferred`` filename when given."""
        diagram = plan_of(sid)
        if not diagram:
            return None
        key = (sid, preferred)
        if key in drawn:
            return drawn[key]
        try:
            content = ranges.render_png(diagram)       # no tiles -> blue/red
        except (OSError, ValueError, TypeError) as error:
            print('  绘制失败', sid, error)
            drawn[key] = None
            return None
        name = Path(preferred).name if preferred else 'range-' + sha(content)[:24] + '.webp'
        if not args.dry_run:
            (UPDATES / name).write_bytes(content)
        result = {'image': f'assets/updates/{name}', 'label': diagram.get('label') or '见技能说明'}
        drawn[key] = result
        return result

    redrawn = rewritten = added = skipped = 0
    for path in sorted(PAGES.glob('*.js')):
        text = path.read_text('utf8')
        if '技能范围' not in text and 'clientRange' not in text:
            continue
        try:
            doc = json.loads(text[text.index('=') + 1:].rstrip().rstrip(';'))
        except (ValueError, IndexError):
            continue
        source = doc.get('clientSource') or {}
        sid = source.get('rowId') if source.get('table') == 'skill' else None
        if sid is None and isinstance(doc.get('id'), int) and doc['id'] >= 100_000_000:
            sid = doc['id'] - 100_000_000
        if sid not in skills:
            # Archived BWIKI skill pages have no clientSource; match by name so
            # their old wiki picture can be replaced by the same diagram.
            raw_fields = doc.get('rawFields') or {}
            label = plain(raw_fields.get('技能名称') or str(doc.get('title') or '').split('/')[-1])
            match = skills_by_name.get(label)
            if match:
                sid = match.get('id')
                if sid not in skills:
                    skills[sid] = match
        if sid not in skills:
            skipped += 1
            continue
        if not plan_of(sid):
            skipped += 1
            continue
        cr = doc.get('clientRange') or {}
        existing = cr.get('image') or ''
        preferred = existing if existing.startswith('assets/updates/range-') else None
        target = draw(sid, preferred)
        if not target:
            skipped += 1
            continue
        old_html = doc.get('html') or ''
        has_wiki_image = bool(RANGE_IMG.search(old_html))
        if preferred and not has_wiki_image:
            redrawn += 1          # bytes already overwritten, page unchanged
            continue
        cr = dict(cr)
        cr['image'] = target['image']
        cr['label'] = target['label']
        doc['clientRange'] = cr
        if has_wiki_image:
            doc['html'] = RANGE_IMG.sub('', old_html)
        raw = doc.get('rawFields') or {}
        if raw.get('技能范围') in ('/', '单体', '见技能说明', ''):
            raw['技能范围'] = target['label']
            doc['rawFields'] = raw
            if isinstance(doc.get('fields'), dict) and '技能范围' in doc['fields']:
                doc['fields']['技能范围'] = html_mod.escape(target['label'])
        if not args.dry_run:
            path.write_text(f'window.WIKI_PAGES[{doc["id"]}]=' +
                            json.dumps(doc, ensure_ascii=False, separators=(',', ':')) + ';\n', 'utf8')
        if existing:
            rewritten += 1
        else:
            added += 1
    print(f'范围图：原位重绘 {redrawn} 页 · 页面改写 {rewritten} 页 · 新增蓝红图 {added} 页 · 跳过 {skipped} 页')


if __name__ == '__main__':
    main()
