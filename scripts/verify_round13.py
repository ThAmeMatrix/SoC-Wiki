"""Round 13: battle power formula, pagination controls, map UI, enhancement rules.

    python -X utf8 scripts/verify_round13.py
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
    E = load('data/enhance-data.js', 'WIKI_ENHANCE_DATA')

    # ---- 1. Battle power formula ----
    bp = W['battlePower']
    check('formula states per-mille weights', '120‰' in bp['formula'] and '200‰' in bp['formula'],
          bp['formula'][:100])
    check('weights exported separately', bp['hpWeight'] == 120 and bp['otherWeight'] == 200)
    check('calibration cites client reference values', 'enemy_fight_power' in bp['calibration'])
    check('profession coefficients present', len(bp['coefficients']) == 6)
    check('rarity adjustments present', len(bp['rarity']) == 4)

    # ---- 3a. map coordinates: no more empty rows ----
    m12 = next(m for m in W['maps'] if m['id'] == 12)
    rows = {c[1] for c in m12['cells']}
    check('map rows have no gaps after stride fix',
          len(rows) == m12['height'] and m12['height'] < 20,
          f"height {m12['height']}, rows {len(rows)}")
    check('maps carry Chinese terrain names', any(m.get('terrainNames') for m in W['maps']))
    check('maps carry terrain effect descriptions', any(m.get('terrainDescs') for m in W['maps']))
    check('field_status catalog exported', len(W['mapMeta'].get('terrainStatuses') or []) > 20,
          str(len(W['mapMeta'].get('terrainStatuses') or [])))

    # ---- 4. enhancement / random rules ----
    check('enhancement tables inventoried', len(E['tables']) == 10, str(len(E['tables'])))
    names = {t['table'] for t in E['tables']}
    check('roll ranges table included', 'online_charm_entry' in names)
    check('weighted pool table included', 'online_charm_build_entry' in names)
    check('character random table included', 'unit_random' in names)
    check('enchant cap table included', 'online_weapon_enchanting_element_entry' in names)
    check('rules explain limits of config data',
          any('没有' in r and ('保底' in r or '分布' in r) for r in E['rules']),
          str(len(E['rules'])) + ' rules')
    charm = next(t for t in E['tables'] if t['table'] == 'online_charm_entry')
    check('charm roll min/max/step exported',
          all(k in charm['ranges'] for k in ('attribute_value_min', 'attribute_value_max',
                                             'attribute_value_step')))
    pool = next(t for t in E['tables'] if t['table'] == 'online_charm_build_entry')
    check('pool weights exported', 'weight' in pool['ranges'])

    errors, failed = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(offline=True, viewport={'width': 1600, 'height': 1000}).new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))

        # ---- 1. Battle power UI: formula first, then result ----
        page.goto(BASE + '#/tools/panel')
        page.locator('#panel-output .panel-total-grid').wait_for()
        power = page.locator('.panel-battle-power strong').inner_text()
        value = int(power.replace(',', ''))
        check('battle power in client reference magnitude', 1500 < value < 6000, power)
        check('formula shown before result', page.locator('.panel-bp-expr').count() == 1)
        check('formula lists all five steps', page.locator('.panel-bp-steps li').count() == 5)
        check('step 2 uses per-mille weights', '120‰' in
              page.locator('.panel-bp-steps li').nth(1).inner_text())
        check('calibration shown in UI', 'enemy_fight_power' in
              page.locator('.panel-bp-detail').inner_text())
        calc = page.evaluate("""()=>{const P=window.WIKI_PANEL_DATA,C=window.WikiPanelCalc,W=window.WIKI_WORLD_DATA;
          const r=C.calculate(C.defaults(P),P);return C.battlePower(r,W,P);}""")
        check('core formula = weighted sum x rarity x profession',
              calc['total'] == int(calc['base'] * calc['rarity'] / 100 * calc['profession'] / 100),
              str(calc['total']))
        check('parts are stat x weight / 1000',
              abs(calc['parts'][0] - calc['stats'][0] * 120 / 1000) < 1e-9)

        # ---- 2. Pagination on four pages ----
        for route, pid, list_sel in (('#/maps', 'world-map-pager', '.world-map-card'),
                                     ('#/ai', 'world-ai-pager', '.world-ai-card'),
                                     ('#/code', 'world-code-pager', '.world-code-card'),
                                     ('#/enhance', 'enhance-pager', '.enhance-card')):
            page.goto(BASE + route)
            page.locator('#' + pid).wait_for()
            check(f'{route} jump-to-page input',
                  page.locator(f'#{pid} [data-page-input]').count() == 1)
            check(f'{route} page-size selector',
                  page.locator(f'#{pid} [data-page-size]').count() == 1)
            check(f'{route} first/last buttons',
                  page.locator(f'#{pid} [data-page="first"]').count() == 1)
            page.evaluate("()=>{document.documentElement.style.scrollBehavior='auto';window.scrollTo(0,1100)}")
            page.wait_for_timeout(180)
            before = page.evaluate("()=>Math.round(scrollY)")
            page.evaluate("id=>document.querySelector('#'+id+' [data-page=\"next\"]').click()", pid)
            page.wait_for_timeout(180)
            after = page.evaluate("()=>Math.round(scrollY)")
            check(f'{route} paging keeps scroll', abs(after - before) < 40,
                  f'{before} -> {after}')
            page.locator(f'#{pid} [data-page-input]').fill('3')
            page.locator(f'#{pid} [data-page-input]').press('Enter')
            page.wait_for_timeout(180)
            check(f'{route} jump to page 3',
                  page.locator(f'#{pid} button.active').inner_text() == '3')
            page.locator(f'#{pid} [data-page-size]').select_option('24')
            page.wait_for_timeout(180)
            check(f'{route} page size 24 applied',
                  page.locator(f'#{pid} [data-page-size]').input_value() == '24')

        # ---- 3. Map UI ----
        page.goto(BASE + '#/maps')
        page.locator('#world-map-list').wait_for()
        check('sticky header wrapper', page.locator('.world-sticky-head').count() == 1)
        head_pos = page.locator('.world-sticky-head').evaluate('e=>getComputedStyle(e).position')
        check('header is sticky', head_pos == 'sticky', head_pos)
        check('3D height ruler hint', page.locator('.world-iso-hint').count() > 0)
        iso = page.locator('[data-world-iso-view]').first
        check('3D view exposes yaw/scale state',
              iso.get_attribute('data-yaw') is not None and iso.get_attribute('data-scale') is not None)
        bb = iso.bounding_box()
        page.mouse.move(bb['x'] + bb['width'] / 2, bb['y'] + bb['height'] / 2)
        page.mouse.down()
        page.mouse.move(bb['x'] + bb['width'] / 2 + 100, bb['y'] + bb['height'] / 2, steps=6)
        page.mouse.up()
        page.wait_for_timeout(200)
        yaw = float(page.locator('[data-world-iso-view]').first.get_attribute('data-yaw'))
        check('drag rotates the 3D grid', abs(yaw) > 0.1, str(yaw))
        page.mouse.wheel(0, -240)
        page.wait_for_timeout(200)
        scale = float(page.locator('[data-world-iso-view]').first.get_attribute('data-scale'))
        check('wheel zooms the 3D grid', scale > 1, str(scale))
        for q, expect in (('草地', True), ('平原', True), ('stage05', True)):
            page.locator('#world-map-query').fill(q)
            page.wait_for_timeout(180)
            n = page.locator('.world-map-card').count()
            check(f'Chinese/model search "{q}"', n > 0 if expect else n == 0, str(n))

        # ---- 4. Enhancement page ----
        page.goto(BASE + '#/enhance')
        page.locator('#enhance-list').wait_for()
        check('enhancement cards render', page.locator('.enhance-card').count() > 0)
        check('探查 conclusions shown', page.locator('.world-priority-steps li').count() == 7)
        check('table filter present', page.locator('#enhance-table').count() == 1)
        page.locator('#enhance-table').select_option('online_charm_entry')
        page.wait_for_timeout(180)
        check('table filter works', page.locator('.enhance-card').count() == 1)
        check('sidebar config lists enhance entry',
              page.evaluate("()=>'#/enhance' in (window.WIKI_NAV_CONFIG?.show||{})"))

        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
