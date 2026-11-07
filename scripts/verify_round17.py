"""Round 17: client terrain face textures, original 角色基础属性 column,
no horizontal scroll / usable result area, stable battle power.

    python -X utf8 scripts/verify_round17.py
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

    # ---- 1. face textures ----
    ft = W['mapMeta']['fieldTypes']
    check('every terrain has a rectified top face',
          all(f.get('topImage', '').startswith('assets/terrain/top/') for f in ft))
    check('every terrain has a rectified wall face',
          all(f.get('wallImage', '').startswith('assets/terrain/wall/') for f in ft))
    top_dir, wall_dir = ROOT / 'assets/terrain/top', ROOT / 'assets/terrain/wall'
    check('top face PNGs exported', len(list(top_dir.glob('*.png'))) >= 40)
    check('wall face PNGs exported', len(list(wall_dir.glob('*.png'))) >= 40)
    manifest = json.loads((ROOT / 'assets/terrain/manifest.json').read_text('utf8'))
    check('manifest records both faces', all(set(v) == {'top', 'wall'} for v in manifest['faces'].values()))

    # ---- 4. stable battle power ----
    bp = W['battlePower']
    check('no fabricated candidate', all(c['id'] != 'empirical' for c in bp['candidates']))
    check('five candidates', len(bp['candidates']) == 5)
    check('measured anchor kept as reference', bp['reference']['power'] == 4167)
    check('no hardcoded empirical factor', bp.get('empiricalScale') in (None, 0))

    errors, failed = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(offline=True, viewport={'width': 1440, 'height': 900}).new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))

        # ---- 1. ----
        page.goto(BASE + '#/maps')
        page.locator('#world-map-list').wait_for()
        cell = page.locator('.world-iso-block').first
        wall = page.locator('.world-iso-wall').first
        check('top face uses /terrain/top/', '/terrain/top/' in (cell.get_attribute('style') or ''))
        check('top face covers whole square', '100% 100%' in (cell.get_attribute('style') or ''))
        check('wall uses /terrain/wall/', '/terrain/wall/' in (wall.get_attribute('style') or ''))
        check('wall covers the whole side', '100% 100%' in (wall.get_attribute('style') or ''))

        # ---- 2. original column ----
        idx = (ROOT / 'data/index.js').read_text('utf8')
        pages = json.JSONDecoder().raw_decode(idx[idx.index('=') + 1:])[0]['pages']
        cid = next(x['id'] for x in pages if x.get('type') == 'character' and not x.get('redirect'))
        page.goto(BASE + '#/page/' + str(cid))
        page.locator('[data-detail-tab]').first.wait_for()
        check('duplicate new block deleted', page.locator('.char-stat-bars').count() == 0)
        check('original 角色基础属性 heading kept',
              '角色基础属性' in page.locator('.profile-stats-heading').inner_text())
        check('stat bars inside the ORIGINAL column',
              page.locator('.profile-stats-bars [data-stat-bars]').count() == 1)
        check('six stat cards in original column',
              page.locator('.profile-stats-bars .ig-stat-card').count() == 6)
        before = page.locator('.profile-stats-bars .ig-stat-current').first.inner_text()
        page.locator('[data-level="base"]').click()
        page.wait_for_timeout(250)
        after = page.locator('.profile-stats-bars .ig-stat-current').first.inner_text()
        check('初始 / 满级满星 switch still works', before != after, f'{before} -> {after}')

        # ---- 3. result area ----
        page.goto(BASE + '#/tools/panel')
        page.locator('#panel-output').wait_for()
        layout = page.evaluate("""()=>{
            const a=document.querySelector('.panel-aside'), de=document.documentElement;
            return {docW:de.scrollWidth, inner:innerWidth,
                    asideSw:a.scrollWidth, asideCw:a.clientWidth,
                    asideW:a.getBoundingClientRect().width,
                    formW:document.querySelector('#panel-form').getBoundingClientRect().width,
                    ovx:getComputedStyle(a).overflowX};}""")
        check('no page horizontal scroll', layout['docW'] <= layout['inner'], str(layout))
        check('result area has no inner horizontal scroll',
              layout['asideSw'] <= layout['asideCw'] + 4, str(layout))
        # Round 18: results moved back to a compact right column.
        check('result area on the right', layout['asideW'] >= 280, str(layout['asideW']))
        check('form column still wide', layout['formW'] > 500, str(layout['formW']))
        check('stat bars render two abreast in right column',
              page.evaluate("()=>getComputedStyle(document.querySelector('.panel-aside .ig-stat-grid')).gridTemplateColumns.split(' ').length") == 2)
        check('formula collapsed by default',
              page.locator('.panel-bp-formula').get_attribute('open') is None)

        # ---- 4. stable battle power ----
        check('default formula is the plain one',
              page.locator('[data-bp-method]').input_value() == 'permille-final')
        check('five candidates offered', page.locator('[data-bp-method] option').count() == 5)
        check('no uncalibrated warning', page.locator('.panel-bp-uncalibrated').count() == 0)
        check('anchor button visible (outside collapsed formula)',
              page.locator('[data-bp-anchor]').is_visible())
        expected = page.evaluate("""()=>{const P=window.WIKI_PANEL_DATA,C=window.WikiPanelCalc,W=window.WIKI_WORLD_DATA;
            const r=C.calculate(C.defaults(P),P);return C.battlePower(r,W,P).total;}""")
        shown = int(page.locator('.panel-battle-power strong').inner_text().replace(',', ''))
        check('shown value equals pure calculation', shown == expected, f'{shown} vs {expected}')
        page.locator('[data-bp-anchor]').click()
        page.wait_for_timeout(250)
        p1 = page.locator('.panel-battle-power strong').inner_text()
        check('one-click calibration hits 4167', abs(int(p1.replace(',', '')) - 4167) <= 2, p1)
        page.reload()
        page.locator('#panel-output').wait_for()
        p2 = page.locator('.panel-battle-power strong').inner_text()
        check('calibration survives reload', p1 == p2, f'{p1} -> {p2}')
        # weapon-type coefficient matching
        coef = page.evaluate("""()=>{const P=window.WIKI_PANEL_DATA,C=window.WikiPanelCalc,W=window.WIKI_WORLD_DATA;
            const ch=P.characters.find(c=>c.name==='伊南娜·铃兰之剑');
            const cfg=Object.assign(C.defaults(P),{character:ch.key});
            const r=C.calculate(cfg,P);const b=C.battlePower(r,W,P);
            return {prof:b.profession,weaponTypes:ch.weaponTypes};}""")
        check('watcher uses generic coefficient row', coef['prof'] == 105, str(coef))

        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
