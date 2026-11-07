"""Round 18: single-map picker, pit semantics, day/night stat colours,
compact right-side results, corrected battle-power coefficient meaning.

    python -X utf8 scripts/verify_round18.py
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

    # ---- 2. pit semantics ----
    pits = [f for f in W['mapMeta']['fieldTypes'] if f.get('pit')]
    check('water/forbidden terrains flagged as pits', len(pits) == 3,
          str([(f['id'], f['name']) for f in pits]))
    check('deep water flagged', any(f['id'] == 15 and f['pit'] for f in pits))

    # ---- 5. coefficient semantics ----
    check('coefficient meaning cites client Chinese description',
          '攻击|防御' in bp['coefficientMeaning'], bp['coefficientMeaning'][:90])
    check('formula now uses attack/defence', '物攻' in bp['formula'] and '生命' not in bp['formula'])
    check('attack-defence candidate present',
          any(c['id'] == 'attack-defence' for c in bp['candidates']))
    check('candidate count is five', len(bp['candidates']) == 5, str(len(bp['candidates'])))
    check('evidence records the Chinese field description',
          any('攻击|防御' in x for x in bp['evidence']))

    errors, failed = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(offline=True, viewport={'width': 1440, 'height': 900}).new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))

        # ---- 1. single map picker ----
        page.goto(BASE + '#/maps')
        page.locator('#world-map-picker').wait_for()
        check('picker lists maps', page.locator('.world-pick-item').count() > 100,
              str(page.locator('.world-pick-item').count()))
        check('exactly one map rendered', page.locator('.world-map-card').count() == 1)
        check('picker is scrollable',
              page.evaluate("()=>getComputedStyle(document.querySelector('#world-map-picker')).overflowY") == 'auto')
        first = page.locator('.world-map-card h2').first.inner_text()
        page.locator('.world-pick-item').nth(3).click()
        page.wait_for_timeout(200)
        second = page.locator('.world-map-card h2').first.inner_text()
        check('selecting a picker item changes the single map', first != second, f'{first} -> {second}')
        check('still exactly one map after selection', page.locator('.world-map-card').count() == 1)
        page.locator('#world-map-query').fill('难民营地')
        page.wait_for_timeout(200)
        check('search narrows the picker', 0 < page.locator('.world-pick-item').count() < 30,
              str(page.locator('.world-pick-item').count()))
        page.locator('#world-map-query').fill('')
        page.wait_for_timeout(150)

        # ---- 2. pit rendering ----
        pit = page.locator('.world-iso-block.is-pit').first
        check('pit cells rendered', page.locator('.world-iso-block.is-pit').count() > 0,
              str(page.locator('.world-iso-block.is-pit').count()))
        if page.locator('.world-iso-block.is-pit').count():
            # Round 20: water now has its own recessed-basin side walls.
            check('pit cells have recessed side walls',
                  pit.locator('.world-iso-wall').count() >= 2)
            check('pit tooltip explains depth semantics',
                  '下沉坑' in (pit.get_attribute('data-info') or ''))

        # ---- 3. day/night stat bar colours ----
        idx = (ROOT / 'data/index.js').read_text('utf8')
        pages = json.JSONDecoder().raw_decode(idx[idx.index('=') + 1:])[0]['pages']
        cid = next(x['id'] for x in pages if x.get('type') == 'character' and not x.get('redirect'))
        page.goto(BASE + '#/page/' + str(cid))
        page.locator('.profile-stats-bars').wait_for()
        def colour():
            return page.evaluate("""()=>({
                bg:getComputedStyle(document.querySelector('.profile-stats-bars .ig-stat-card')).backgroundColor,
                val:getComputedStyle(document.querySelector('.profile-stats-bars .ig-stat-current')).color})""")
        page.evaluate("()=>document.body.classList.remove('dark')")
        page.wait_for_timeout(120)
        light = colour()
        page.evaluate("()=>document.body.classList.add('dark')")
        page.wait_for_timeout(120)
        dark = colour()
        check('light and dark card backgrounds differ', light['bg'] != dark['bg'],
              f"{light['bg'][:44]} vs {dark['bg'][:44]}")
        check('light and dark value colours differ', light['val'] != dark['val'],
              f"{light['val']} vs {dark['val']}")
        check('light theme uses a pale card', '242, 243, 237' in light['bg'], light['bg'][:60])
        check('dark theme uses an archive dark card', '22, 38, 45' in dark['bg'], dark['bg'][:60])

        # ---- 4. right column ----
        page.goto(BASE + '#/tools/panel')
        page.locator('#panel-output').wait_for()
        info = page.evaluate("""()=>{
            const a=document.querySelector('.panel-aside'), f=document.querySelector('#panel-form');
            const de=document.documentElement;
            return {docW:de.scrollWidth,inner:innerWidth,
                    sw:a.scrollWidth,cw:a.clientWidth,
                    ax:a.getBoundingClientRect().left,fx:f.getBoundingClientRect().left,
                    oy:getComputedStyle(a).overflowY,pos:getComputedStyle(a).position,
                    collapsed:document.querySelectorAll('.panel-aside details:not([open])').length};}""")
        check('results back on the right', info['ax'] > info['fx'], str(info))
        check('no horizontal scroll', info['docW'] <= info['inner'], str(info))
        check('no inner horizontal scroll', info['sw'] <= info['cw'] + 4, str(info))
        check('right column is sticky & scrollable', info['pos'] == 'sticky' and info['oy'] == 'auto',
              str(info))
        check('most sections collapsed by default', info['collapsed'] >= 4, str(info['collapsed']))
        page.locator('#panel-steps').evaluate("e=>{const d=e.closest('details');d.open=true}")
        page.wait_for_timeout(150)
        check('expanded results can scroll',
              page.evaluate("()=>{const a=document.querySelector('.panel-aside');return a.scrollHeight>a.clientHeight}"))

        # ---- 5. battle power ----
        page.locator('.panel-bp-formula').evaluate('e=>{e.open=true}')
        check('coefficient meaning shown in UI',
              '攻击|防御' in page.locator('.panel-bp-meaning').inner_text())
        check('five candidates offered', page.locator('[data-bp-method] option').count() == 5)
        values = page.evaluate("""()=>{const P=window.WIKI_PANEL_DATA,C=window.WikiPanelCalc,W=window.WIKI_WORLD_DATA;
            const r=C.calculate(C.defaults(P),P);
            return {ad:C.battlePower(r,W,P,{method:'attack-defence'}).total,
                    old:C.battlePower(r,W,P,{method:'permille-final'}).total};}""")
        check('attack/defence formula differs from old reading',
              values['ad'] != values['old'], str(values))
        page.locator('[data-bp-method]').select_option('attack-defence')
        page.wait_for_timeout(200)
        shown = int(page.locator('.panel-battle-power strong').inner_text().replace(',', ''))
        check('selected formula drives the displayed value', shown == values['ad'],
              f'{shown} vs {values["ad"]}')

        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
