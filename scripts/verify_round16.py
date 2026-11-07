"""Round 16: stacked 3D map, shared stat bars, light-mode/right sidebar,
empirical battle power anchor, digestible AI guide.

    python -X utf8 scripts/verify_round16.py
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
    t = (ROOT / relative).read_text('utf8')
    m = 'window.' + variable + '='
    return json.JSONDecoder().raw_decode(t[t.index(m) + len(m):])[0]


def main():
    W = load('data/world-data.js', 'WIKI_WORLD_DATA')
    bp = W['battlePower']

    # ---- 4. empirical anchor ----
    check('measured anchor exported', bp['reference']['power'] == 4167
          and bp['reference']['profession'] == 5, str(bp['reference']))
    check('no fabricated empirical candidate', all(c['id'] != 'empirical' for c in bp['candidates']))
    check('five candidate formulas', len(bp['candidates']) == 5, str(len(bp['candidates'])))
    check('client evidence still states formula is compiled',
          any('IL2CPP' in x or 'GameAssembly' in x or '编译' in x for x in bp['evidence']))

    # ---- 5. AI quick guides ----
    pf = W['aiMeta']['pathfinding']
    pr = W['aiMeta']['priority']
    check('pathfinding has three quick steps', len(pf['quick']) == 3)
    check('priority has three quick steps', len(pr['quick']) == 3)
    check('quick steps carry field badges', all(q.get('fields') for q in pf['quick'] + pr['quick']))
    check('technical details still preserved', len(pf['explanation']) >= 6 and len(pr['explanation']) >= 5)

    # ---- 2. shared stat bars component ----
    sb = ROOT / 'stat-bars.js'
    check('shared stat-bars component exists', sb.is_file() and 'WikiStatBars' in sb.read_text('utf8'))
    check('component loaded in index.html', 'stat-bars.js' in (ROOT / 'index.html').read_text('utf8'))

    errors, failed = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(offline=True, viewport={'width': 1600, 'height': 950}).new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))

        # ---- 1. stacked 3D map ----
        page.goto(BASE + '#/maps')
        page.locator('#world-map-list').wait_for()
        frame = page.locator('[data-world-iso-view]').first
        check('stacked blocks render', page.locator('.world-iso-block').count() > 50,
              str(page.locator('.world-iso-block').count()))
        # Round 18: pit cells (water/forbidden) intentionally have no walls.
        check('solid blocks have side walls',
              page.locator('.world-iso-wall').count() > 0,
              str(page.locator('.world-iso-wall').count()))
        check('floating base slab present', page.locator('.world-iso-base').count() > 0)
        # Round 20: the frame is a square that scales with the viewport.
        check('frame is square', abs(frame.bounding_box()['width'] - frame.bounding_box()['height']) < 3,
              str(frame.bounding_box()))
        cell = page.locator('.world-iso-block').first
        check('top face uses client terrain art',
              'assets/terrain/' in (cell.get_attribute('style') or ''))
        wall = page.locator('.world-iso-wall').first
        check('wall has masonry gradient', 'linear-gradient' in (wall.get_attribute('style') or ''))
        # arbitrary rotation keeps geometry
        bb = frame.bounding_box()
        cx, cy = bb['x'] + bb['width'] / 2, bb['y'] + bb['height'] / 2
        page.mouse.move(cx, cy); page.mouse.down()
        page.mouse.move(cx - 60, cy + 50, steps=8); page.mouse.up()
        page.wait_for_timeout(200)
        f2 = page.locator('[data-world-iso-view]').first
        check('rotation keeps all blocks', f2.locator('.world-iso-block').count() == frame.locator('.world-iso-block').count(),
              f"{f2.get_attribute('data-yaw')}° / {f2.get_attribute('data-tilt')}°")

        # ---- 2. shared stat bars in archive & panel ----
        page.goto(BASE + '#/tools/panel')
        page.locator('#panel-output').wait_for()
        check('panel uses shared stat bars', page.locator('#panel-output [data-stat-bars]').count() == 1)
        check('panel shows six stat cards', page.locator('#panel-output .ig-stat-card').count() == 6)
        idx = (ROOT / 'data/index.js').read_text('utf8')
        pages = json.JSONDecoder().raw_decode(idx[idx.index('=') + 1:])[0]['pages']
        cid = next(x['id'] for x in pages if x.get('type') == 'character' and not x.get('redirect'))
        page.goto(BASE + '#/page/' + str(cid))
        page.locator('[data-detail-tab]').first.wait_for()
        # Round 17: the shared bars live in the ORIGINAL 角色基础属性 column.
        check('character archive uses same stat bars',
              page.locator('.profile-stats-bars [data-stat-bars]').count() == 1)
        check('archive shows six stat cards',
              page.locator('.profile-stats-bars .ig-stat-card').count() == 6)
        check('same component markup in both views',
              page.evaluate("()=>!!document.querySelector('.ig-stat-card progress')"))

        # ---- 3. light mode + right sidebar ----
        page.goto(BASE + '#/tools/panel')
        page.locator('#panel-output').wait_for()
        page.evaluate("()=>document.body.classList.remove('dark')")
        page.wait_for_timeout(150)
        colors = page.evaluate("""()=>{
          const h2=document.querySelector('.panel-aside .damage-result h2');
          const lbl=document.querySelector('.panel-battle-power>span');
          const f=document.querySelector('.panel-bp-formula h3');
          const lum=s=>{const m=s.match(/\\d+/g);return m?(+m[0]+ +m[1]+ +m[2])/3:255};
          return {h2:getComputedStyle(h2).color,label:getComputedStyle(lbl).color,
                  formula:getComputedStyle(f).color,
                  h2Lum:lum(getComputedStyle(h2).color)};}""")
        check('light-mode headings use dark ink', colors['h2Lum'] < 140, str(colors))
        check('battle power label legible', colors['label'] == colors['h2'], str(colors['label']))
        check('formula heading legible', colors['formula'] == colors['h2'], str(colors['formula']))
        aside = page.evaluate("""()=>{const a=document.querySelector('.panel-aside');
          return {pos:getComputedStyle(a).position,w:a.getBoundingClientRect().width,
                  scroll:getComputedStyle(a).overflowY};}""")
        # Round 17: the third column was removed; results are full-width above
        # the form and must not scroll horizontally.
        check('result area is a compact right column', aside['pos'] == 'sticky' and 280 <= aside['w'] <= 340,
              str(aside))
        check('right column scrolls vertically', aside['scroll'] == 'auto',
              str(aside['scroll']))

        # ---- 4. empirical calibration ----
        check('plain formula is default', page.locator('[data-bp-method]').input_value() == 'permille-final')
        check('measured reference shown in UI', page.locator('.panel-bp-anchor').count() == 1)
        check('no fabricated uncalibrated warning', page.locator('.panel-bp-uncalibrated').count() == 0)
        before = page.locator('.panel-battle-power strong').inner_text()
        page.locator('[data-bp-anchor]').click()
        page.wait_for_timeout(300)
        after = page.locator('.panel-battle-power strong').inner_text()
        check('one-click calibration hits 4167', abs(int(after.replace(',', '')) - 4167) <= 2,
              f'{before} -> {after}')
        check('calibration persists', page.evaluate("()=>Object.keys(localStorage).some(k=>k.includes('battlePower')||k.includes('panel.battle'))"))
        calc = page.evaluate("""()=>{const P=window.WIKI_PANEL_DATA,C=window.WikiPanelCalc,W=window.WIKI_WORLD_DATA;
          const r=C.calculate(C.defaults(P),P);
          return {a:C.battlePower(r,W,P).total,b:C.battlePower(r,W,P,{method:'permille-white'}).total};}""")
        check('plain and whiteboard candidates differ', calc['a'] != calc['b'], str(calc))

        # ---- 5. AI guide ----
        page.goto(BASE + '#/ai')
        page.locator('#world-ai-list').wait_for()
        check('two digestible guides', page.locator('.ai-guide').count() == 2)
        check('six guide cards', page.locator('.ai-guide-card').count() == 6)
        check('guides have numbered steps', page.locator('.ai-guide-num').count() == 6)
        check('technical details collapsed by default',
              page.locator('.world-priority-card[open]').count() == 0)
        check('intro is short and clear', '三件事' in page.locator('#main').inner_text())

        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
