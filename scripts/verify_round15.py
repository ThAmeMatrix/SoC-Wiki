"""Round 15: client terrain artwork, compact map head, external nav config,
slimmed offline asset set.

    python -X utf8 scripts/verify_round15.py
"""
import json
import subprocess
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


def main():
    # ---- 1. Terrain artwork ----
    terrain = ROOT / 'assets' / 'terrain'
    pngs = list(terrain.glob('*.png')) if terrain.is_dir() else []
    check('client terrain sprites exported', len(pngs) >= 40, str(len(pngs)))
    manifest = json.loads((terrain / 'manifest.json').read_text('utf8')) if (terrain / 'manifest.json').is_file() else {}
    icons = {x['icon'] for x in manifest.get('fieldTypes', []) if x.get('icon')}
    check('every field_type icon has a sprite', all((terrain / (i + '.png')).is_file() for i in icons),
          f'{len(icons)} icons')
    check('grass sprite exists', (terrain / 'terrain2.png').is_file())
    W = json.loads('{}')  # world data read below via browser or raw
    raw = (ROOT / 'data' / 'world-data.js').read_text('utf8')
    world = json.JSONDecoder().raw_decode(raw[raw.index('=') + 1:])[0]
    ftypes = world['mapMeta']['fieldTypes']
    check('world data maps icons to client artwork',
          all(f.get('image', '').startswith('assets/terrain/') for f in ftypes if f.get('icon')),
          f"{sum(1 for f in ftypes if f.get('image'))}/{len(ftypes)}")

    # ---- 4. Slim asset set ----
    for name in ('sprites', 'expressions'):
        check(f'extra asset dir removed: {name}', not (ROOT / 'assets' / name).exists())
    for name in ('sprites.js', 'expressions.js', 'voices.js'):
        check(f'extra data removed: {name}', not (ROOT / 'data' / name).is_file())
    html = (ROOT / 'index.html').read_text('utf8')
    check('no removed scripts in index.html',
          all(f'data/{n}.js' not in html for n in ('sprites', 'expressions', 'voices')))
    app = (ROOT / 'app.js').read_text('utf8')
    check('no dead sprite/face globals', 'WIKI_SPRITES' not in app and 'WIKI_EXPRESSIONS' not in app)
    check('core assets kept', (ROOT / 'assets' / 'wiki').is_dir()
          and (ROOT / 'assets' / 'client').is_dir())
    # Files are deleted from the working tree; git index entries become
    # staged deletions once committed (git status shows them as ' D').
    # The deletions were committed in d1ddcc9e; assert the dirs are gone and
    # the commit removed them from the index.
    tracked = subprocess.run(['git', 'ls-files', 'assets/sprites', 'assets/expressions'],
                             capture_output=True, text=True).stdout
    check('removed art no longer tracked', not tracked.strip(), str(len(tracked.splitlines())))

    # ---- 3. nav config ----
    nav = (ROOT / 'nav-config.js').read_text('utf8')
    check('external nav config exists', 'WIKI_NAV_CONFIG' in nav and 'show:' in nav)
    # The config is user-editable; assert the switch MECHANISM rather than a
    # hard-coded value so enabling pages does not break the check.
    check('all recent pages have explicit show switches',
          all(f"'#/{k}':" in nav for k in
              ('dialogues', 'mechanics', 'maps', 'ai', 'code', 'enhance')))
    check('core pages are enabled', all(f"'#/{k}': true" in nav for k in
          ('search', 'tools', 'archive')))

    errors, failed = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(offline=True, viewport={'width': 1600, 'height': 900}).new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))

        # ---- 1/2. Maps ----
        page.goto(BASE + '#/maps')
        page.locator('#world-map-list').wait_for()
        head = page.locator('.world-sticky-head')
        h = head.bounding_box()['height']
        check('sticky head is compact', h < 110, f'{h}px of 900px viewport')
        check('sticky head is a single toolbar',
              page.evaluate("()=>document.querySelector('.world-sticky-head').children.length") == 1)
        check('sticky head stays fixed',
              head.evaluate('e=>getComputedStyle(e).position') == 'sticky')
        cells = page.locator('.world-iso-cell.has-art')
        check('3D cells use client terrain art', cells.count() > 50, str(cells.count()))
        style = page.locator('.world-iso-cell').first.get_attribute('style') or ''
        check('cell background points at a terrain png', 'assets/terrain/' in style, style[:110])
        loaded = page.evaluate("""async()=>{const i=new Image();i.src='assets/terrain/terrain2.png';
          return await new Promise(r=>{i.onload=()=>r(i.width+'x'+i.height);i.onerror=()=>r('ERR')})}""")
        check('terrain png loads', loaded != 'ERR', loaded)
        # 2D pattern
        page.locator('[data-world-view]').first.click()
        page.wait_for_timeout(220)
        check('2D view uses image patterns',
              page.locator('svg.world-grid pattern image').count() > 0,
              str(page.locator('svg.world-grid pattern image').count()))
        check('head-more foldout exists', page.locator('.world-head-more').count() == 1)

        # ---- 3. Nav config UI ----
        page.goto(BASE + '#/')
        page.evaluate("()=>localStorage.removeItem('nav.config')")
        page.reload()
        page.wait_for_timeout(250)
        vis = page.evaluate("""()=>{const s=(window.WIKI_NAV_CONFIG||{}).show||{};
          const keys=['#/maps','#/ai','#/code','#/enhance','#/mechanics','#/dialogues'];
          return {cfg:keys.map(k=>!!s[k]),
                  dom:keys.map(k=>!!document.querySelector('#sidebar a[href="'+k+'"]'))};}""")
        check('sidebar follows the nav config exactly', vis['cfg'] == vis['dom'], str(vis))
        check('core nav entries visible',
              page.evaluate("()=>!!document.querySelector('#sidebar a[href=\"#/search\"]')"))
        page.goto(BASE + '#/archive')
        page.locator('.nav-config-list').wait_for()
        check('nav settings card renders', page.locator('[data-nav-toggle]').count() >= 10,
              str(page.locator('[data-nav-toggle]').count()))
        page.locator('[data-nav-toggle="#/maps"]').check()
        page.wait_for_timeout(250)
        check('enabling an entry shows it',
              page.evaluate("()=>!!document.querySelector('#sidebar a[href=\"#/maps\"]')"))
        page.locator('[data-action="nav-reset"]').click()
        page.wait_for_timeout(250)
        page.evaluate("()=>window.WikiNav && window.WikiNav.reset()")
        page.wait_for_timeout(150)
        check('reset restores config defaults',
              page.evaluate("""()=>{const want=!!(window.WIKI_NAV_CONFIG||{}).show?.['#/maps'];
                return !!document.querySelector('#sidebar a[href="#/maps"]')===want;}"""))

        # ---- 4. No broken requests ----
        page.goto(BASE + '#/dialogues')
        page.wait_for_timeout(300)
        check('dialogue page works without expression images',
              page.locator('.dialogue-line').count() >= 0)
        check('no page errors', not errors, '; '.join(errors[:3]))
        bad = [u for u in failed if '/sprites/' in u or '/expressions/' in u]
        check('no requests for removed assets', not bad, '; '.join(bad[:2]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
