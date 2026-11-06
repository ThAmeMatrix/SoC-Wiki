"""Round 11: live equipment base, plan-named export, map visualisation,
client Lua code library and enhanced AI browser.

    python -X utf8 scripts/verify_round11.py
"""
import json
import sys
import tempfile
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
    # ---- 4. Client code corpus ----
    code = load('data/client-code.js', 'WIKI_CLIENT_CODE')
    check('client code library exported', len(code['scripts']) > 7000,
          str(len(code['scripts'])))
    check('code deduplicated with references',
          code['meta']['references'] > code['meta']['unique'],
          f"{code['meta']['unique']} / {code['meta']['references']}")
    check('code fields classified', len(code['meta']['fields']) == 10,
          str(len(code['meta']['fields'])))
    check('AI code flagged', code['meta']['ai'] > 0, str(code['meta']['ai']))
    check('code keeps verbatim Lua',
          any('return' in s['code'] and s['refs'] for s in code['scripts'][:200]))

    world = load('data/world-data.js', 'WIKI_WORLD_DATA')
    check('AI records expanded', len(world['aiScripts']) > 200, str(len(world['aiScripts'])))
    check('AI kinds classified', len(world['aiMeta']['kinds']) >= 3,
          str(world['aiMeta']['kinds']))
    check('AI Lua scripts present', world['aiMeta']['luaScripts'] > 20,
          str(world['aiMeta']['luaScripts']))

    errors, failed = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(offline=True, viewport={'width': 1600, 'height': 1000}).new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))

        # ---- 1. Base value before enchant, live on star/level ----
        page.goto(BASE + '#/tools/panel')
        page.locator('#panel-output .panel-total-grid').wait_for()
        order = page.locator('#panel-sec-02').evaluate(
            "e=>[...e.children].map(x=>x.id||x.className)")
        check('weapon base shown before enchant',
              any('panel-equip-base-weapon' in x for x in order)
              and order.index(next(x for x in order if 'panel-equip-base-weapon' in x))
                  < order.index(next(x for x in order if 'panel-sub' in x)),
              str(order[:5]))
        base60 = page.locator('#panel-equip-base-weapon strong').all_inner_texts()
        page.locator('[data-path="weapon.level"]').select_option('1')
        page.wait_for_timeout(220)
        base1 = page.locator('#panel-equip-base-weapon strong').all_inner_texts()
        check('base follows level', base60 != base1, f'{base60} -> {base1}')
        page.locator('[data-path="weapon.star"]').select_option('1')
        page.wait_for_timeout(220)
        basestar1 = page.locator('#panel-equip-base-weapon strong').all_inner_texts()
        check('base follows star', basestar1 != base1, f'{base1} -> {basestar1}')
        check('base label reflects current level/star',
              '1 级' in page.locator('#panel-equip-base-weapon small').inner_text()
              and '1 星' in page.locator('#panel-equip-base-weapon small').inner_text())
        check('offhand and charm base blocks present',
              page.locator('#panel-equip-base-offhand').count() == 1
              and page.locator('#panel-equip-base-charm').count() == 1)

        # ---- 2. Export name follows the plan name ----
        page.locator('.preset-card').evaluate('e=>{e.open=true}')
        page.locator('#panel-preset-name').fill('我的满配/方案:测试')
        tmp = Path(tempfile.gettempdir())
        with page.expect_download() as dl:
            page.locator('[data-tool="export-panel-plans"]').click()
        name = dl.value.suggested_filename
        check('export filename uses the plan name', '我的满配' in name and name.endswith('.json'), name)
        check('unsafe path characters sanitised', '/' not in name and ':' not in name, name)
        exported = tmp / 'r11-export.json'
        dl.value.save_as(str(exported))
        payload = json.loads(exported.read_text('utf8'))
        check('export carries planName', payload.get('planName') == '我的满配/方案:测试')

        # ---- 3. Map visualisation ----
        page.goto(BASE + '#/maps')
        page.locator('#world-map-list').wait_for()
        # The default view is a CSS-3D DOM grid (ported from SoCxiezhouTool).
        check('only grid maps shown by default',
              page.locator('[data-world-iso-view]').count() == page.locator('.world-map-card').count(),
              f"{page.locator('[data-world-iso-view]').count()} / {page.locator('.world-map-card').count()}")
        iso = page.locator('[data-world-iso-view]').first
        check('3D blocks rendered', iso.locator('.world-iso-cell').count() > 50,
              str(iso.locator('.world-iso-cell').count()))
        page.locator('[data-world-view]').first.click()
        page.wait_for_timeout(220)
        svg = page.locator('svg.world-grid:not(.world-grid-iso)').first
        check('grid has coordinate axes', svg.locator('.world-axis').count() > 4,
              str(svg.locator('.world-axis').count()))
        check('grid has gridlines', svg.locator('.world-grid-line').count() > 10)
        check('cells have hover metadata', svg.locator('.world-cell[data-info]').count() > 50)
        check('larger cells than before',
              int(svg.get_attribute('width')) > 400, svg.get_attribute('width'))
        check('terrain toggles present', page.locator('[data-world-terrain]').count() > 0)
        old_size = int(svg.get_attribute('width'))
        page.locator('[data-world-zoom="1"]').first.click()
        page.wait_for_timeout(200)
        check('zoom control enlarges the grid',
              int(page.locator('svg.world-grid:not(.world-grid-iso)').first.get_attribute('width')) > old_size,
              f'{old_size} -> {page.locator("svg.world-grid:not(.world-grid-iso)").first.get_attribute("width")}')
        before_toggle = page.locator('svg.world-grid:not(.world-grid-iso)').first.locator('.world-cell').count()
        page.locator('[data-world-terrain]').first.click()
        page.wait_for_timeout(200)
        check('terrain toggle changes cells',
              page.locator('svg.world-grid:not(.world-grid-iso)').first.locator('.world-cell').count()
              <= before_toggle)
        page.locator('[data-world-fullscreen]').first.click()
        page.wait_for_timeout(250)
        check('fullscreen dialog opens',
              page.locator('#world-map-dialog').evaluate('e=>e.open'))
        page.locator('#world-dialog-close').click()
        page.locator('#world-map-query').fill('stage05')
        page.wait_for_timeout(200)
        check('map search still works', page.locator('.world-map-card').count() < 12,
              str(page.locator('.world-map-card').count()))

        # ---- 4. Client code browser ----
        page.goto(BASE + '#/code')
        page.locator('#world-code-list').wait_for()
        check('code cards render', page.locator('.world-code-card').count() > 0)
        check('stats shown', page.locator('.world-stat-grid').count() == 1)
        check('Lua syntax highlighting', page.locator('.lua-keyword').count() > 0,
              str(page.locator('.lua-keyword').count()))
        page.locator('#world-code-field').select_option('skill.ai_order_param')
        page.wait_for_timeout(200)
        check('field filter works', 0 < page.locator('.world-code-card').count() < 16,
              str(page.locator('.world-code-card').count()))
        page.locator('#world-code-query').fill('physic_armor')
        page.wait_for_timeout(200)
        check('code full-text search works', page.locator('.world-code-card').count() == 1,
              str(page.locator('.world-code-card').count()))
        page.locator('#world-code-field').select_option('')
        page.locator('#world-code-query').fill('')
        page.locator('#world-code-ai').check()
        page.wait_for_timeout(200)
        check('AI-only filter works', page.locator('.world-code-card').count() > 0)

        # ---- 5. Enhanced AI browser ----
        page.goto(BASE + '#/ai')
        page.locator('#world-ai-list').wait_for()
        check('AI stats cards', page.locator('.world-stat-grid>div').count() == 4)
        check('BOSS sequence timelines visible',
              page.locator('.world-timeline').count() > 0,
              str(page.locator('.world-timeline').count()))
        check('unit mode badges', page.locator('.world-ai-card .world-kind').count() > 0)
        page.locator('[data-world-tab="scripts"]').click()
        page.wait_for_timeout(250)
        check('AI code tab renders', page.locator('.world-lua-card').count() > 0)
        check('AI kind badges', page.locator('.world-lua-card .world-kind').count() > 0)
        check('AI Lua highlighted', page.locator('.world-lua-card .lua-keyword').count() > 0)
        check('kind filter visible in code tab', page.locator('#world-ai-kind').is_visible())
        page.locator('#world-ai-kind').select_option('技能决策')
        page.wait_for_timeout(200)
        check('kind filter works',
              all('技能决策' in x for x in page.locator('.world-lua-card .world-kind').all_inner_texts()),
              str(page.locator('.world-lua-card').count()))

        check('sidebar config lists all three world entries',
              page.evaluate("()=>['#/maps','#/ai','#/code'].every(k=>k in (window.WIKI_NAV_CONFIG?.show||{}))"))
        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
