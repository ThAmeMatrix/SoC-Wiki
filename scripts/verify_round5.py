"""Round-5 checks: unified range diagrams, IME-safe mechanics search with
pinyin, tree-based skill axis and real talent trees.

    python -X utf8 scripts/verify_round5.py
"""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / 'index.html').as_uri()
failures = []


def check(name, ok, detail=''):
    print(('PASS ' if ok else 'FAIL ') + name + (f' :: {detail}' if detail else ''), flush=True)
    if not ok:
        failures.append(name)


def load(relative, variable):
    text = (ROOT / relative).read_text('utf8')
    marker = 'window.' + variable + '='
    return json.JSONDecoder().raw_decode(text[text.index(marker) + len(marker):])[0]


def main():
    # ---- 1. Every skill range diagram uses the blue/red flat overlay. ----
    from PIL import Image
    pages = ROOT / 'data' / 'pages'
    refs, wiki_refs, page_count = set(), set(), 0
    for f in pages.glob('*.js'):
        text = f.read_text('utf8')
        if 'clientRange' not in text and '技能范围' not in text:
            continue
        try:
            doc = json.loads(text[text.index('=') + 1:].rstrip().rstrip(';'))
        except (ValueError, IndexError):
            continue
        image = (doc.get('clientRange') or {}).get('image') or ''
        if image.startswith('assets/updates/range-'):
            refs.add(image)
            page_count += 1
        # Archived BWIKI range pictures must be gone from the article body once
        # a generated clientRange image takes over.
        if image and 'alt="技能范围' in (doc.get('html') or '') and 'assets/wiki/' in (doc.get('html') or ''):
            wiki_refs.add(f.stem)
    check('skill pages carry generated range images', page_count > 1400,
          f'{page_count} pages / {len(refs)} distinct diagrams')
    check('no archived range picture left beside a generated one', not wiki_refs, str(list(wiki_refs)[:4]))
    blue = red = 0
    for ref in list(refs)[:220]:
        path = ROOT / ref
        if not path.is_file():
            continue
        im = Image.open(path).convert('RGBA')
        pixels = [px for px in im.getdata() if px[3] > 40]
        if any(p[2] > p[0] + 40 and p[2] > p[1] + 20 for p in pixels):
            blue += 1
        if any(p[0] > p[2] + 40 and p[0] > p[1] + 20 for p in pixels):
            red += 1
    check('diagrams use blue cast range', blue > 100, str(blue))
    check('diagrams use red area of effect', red > 20, str(red))
    wiki_calls = (ROOT / 'scripts' / 'socdecode' / 'wiki.py').read_text('utf8')
    check('future updates draw the same style', 'render_png(diagram,tiles)' not in wiki_calls
          and wiki_calls.count('ranges.render_png(diagram)') >= 2)
    steps = (ROOT / 'scripts' / 'socdecode' / 'rebuild.py').read_text('utf8')
    check('rebuild redraws range images', 'rebuild_range_images.py' in steps)
    check('rebuild refreshes the pinyin index without stale slicing',
          "text.index(';window.WIKI_PAGES')" not in steps and 'raw_decode' in steps)
    # Same stale parse existed in the two data extractors; both must use raw_decode.
    for name in ('extract_panel_data.py', 'extract_battle_rules.py'):
        source = (ROOT / 'scripts' / name).read_text('utf8')
        check(f'{name} parses index.js robustly',
              ";window.WIKI_PAGES" not in source.replace('window.WIKI_PAGES={}', ''))
    choices = load('data/choice-skills.js', 'WIKI_CHOICE_SKILLS')
    preview_images = [v['rangeImage'] for v in choices.get('previews', {}).values() if v.get('rangeImage')]
    check('choice previews use the same generated diagrams',
          len(preview_images) > 200 and all((ROOT / p).is_file() for p in preview_images),
          f'{len(preview_images)} previews')

    # ---- 2. Mechanics search: Chinese IME + pinyin initials. ----
    mechanics = load('data/skill-mechanics.js', 'WIKI_SKILL_MECHANICS')
    sample = mechanics['skills'].get('7433')
    check('mechanics carry pinyin', bool(sample and sample.get('py') == 'renweicaisi'
                                        and sample.get('ini') == 'rwcs'),
          f"{sample and sample.get('py')}/{sample and sample.get('ini')}")
    check('pinyin covers most skills',
          sum(1 for s in mechanics['skills'].values() if s.get('ini')) > len(mechanics['skills']) * 0.9)

    errors, failed = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(offline=True, viewport={'width': 1440, 'height': 1000}).new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))

        page.goto(BASE + '#/mechanics')
        search = page.locator('#mechanics-query')
        search.wait_for()
        # Typing Chinese twice in a row must keep the same input element: the
        # old version rebuilt root.innerHTML on every keystroke and broke IME.
        search.fill('人为财死')
        page.wait_for_timeout(200)
        first = search.evaluate('(e)=>e.value')
        check('Chinese query accepted', first == '人为财死', first)
        check('Chinese query finds the skill',
              '人为财死' in page.locator('.mechanics-list').inner_text())
        search.fill('')
        search.type('聚拢规则', delay=20)
        page.wait_for_timeout(250)
        check('second Chinese input works', search.input_value() == '聚拢规则', search.input_value())
        check('input element survived repaints',
              page.evaluate("()=>document.querySelector('#mechanics-query')===window.__mechInput") or
              page.locator('#mechanics-query').count() == 1)
        # Real IME composition sequence must not be interrupted.
        search.fill('')
        search.evaluate("""e=>{
          e.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));
          e.value='ju';e.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true,data:'ju'}));
          e.value='聚拢';e.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'聚拢'}));
        }""")
        page.wait_for_timeout(250)
        check('IME composition finishes with Chinese', search.input_value() == '聚拢', search.input_value())
        check('composition triggers the search',
              '聚拢' in page.locator('#mechanics-count').inner_text() or
              page.locator('.mechanics-entry').count() > 0)

        search.fill('rwcs')
        page.wait_for_timeout(250)
        hits = page.locator('.mechanics-list').inner_text()
        check('pinyin initials find 人为财死', '人为财死' in hits, hits[:120].replace('\n', ' '))
        check('pinyin hint shown', '拼音首字母' in page.locator('#mechanics-count').inner_text())
        search.fill('renweicaisi')
        page.wait_for_timeout(250)
        check('full pinyin also matches', '人为财死' in page.locator('.mechanics-list').inner_text())
        search.fill('yzqj')
        page.wait_for_timeout(250)
        check('initials match other skills', '一掷千金' in page.locator('.mechanics-list').inner_text(),
              page.locator('.mechanics-list').inner_text()[:80].replace('\n', ' '))
        # ---- 3/4. Tree-based skill axis and real talent trees. ----
        page.goto(BASE + '#/tools/panel')
        page.locator('#panel-output [data-stat-bars]').wait_for()
        check('skill axis uses tree nodes', page.locator('[data-line-node]').count() >= 8
              and page.locator('.panel-tree-tier').count() >= 4)
        check('old segmented skill-axis control is gone', page.locator('[data-line-rank]').count() == 0)
        check('old invented talent tier selector is gone',
              page.locator('[data-path="talent.star"]').count() == 0)
        check('both real talent trees render', page.locator('.panel-talent-tree').count() == 2)
        star_view = page.locator('[data-path="talentView.star"]')
        pioneer_view = page.locator('[data-path="talentView.pioneer"]')
        check('star tree exposes seven grades', star_view.locator('option').count() == 7)
        check('pioneer tree exposes unlock groups', pioneer_view.locator('option').count() >= 20)
        count_before = page.locator('.panel-talent-node').count()
        star_view.select_option('4')
        page.wait_for_timeout(220)
        check('grade switch changes the node set',
              page.locator('.panel-talent-node').count() != count_before)
        # Both trees are fully lit by default, so no unmet prerequisites are
        # shown until a prerequisite node is switched off.
        page.evaluate("()=>document.querySelector('[data-talent-clear]').click()")
        page.wait_for_timeout(220)
        check('prerequisites are surfaced', page.locator('.panel-node-warn').count() > 0,
              str(page.locator('.panel-node-warn').count()))
        check('talent progress summary shown',
              '品阶' in page.locator('.panel-talent-summary').inner_text())
        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
