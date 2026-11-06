"""Round 12: named/3D maps, local client-code files, pagination, battle power.

    python -X utf8 scripts/verify_round12.py
"""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / 'index.html').as_uri()
LOCAL = ROOT / 'output' / 'client-code'
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
    world = load('data/world-data.js', 'WIKI_WORLD_DATA')
    # ---- 1. Terrain names / stage names ----
    terrain = world['mapMeta']['terrainTypes']
    check('terrain types carry Chinese names',
          all(t.get('name') for t in terrain[:8]), str([t['name'] for t in terrain[:4]]))
    check('terrain descriptions exported',
          any(t.get('desc') for t in terrain))
    check('maps linked to stage names', world['mapMeta']['namedMaps'] > 50,
          str(world['mapMeta']['namedMaps']))
    check('maps carry scene labels', any(m.get('scene') for m in world['maps']))

    # ---- 2. Local code files ----
    lua = list(LOCAL.rglob('*.lua'))
    check('local Lua files written', len(lua) > 7000, str(len(lua)))
    check('code grouped by table/field',
          all(p.parent.parent.name in ('skill', 'speciality', 'buff') for p in lua[:200]))
    indexes = list(LOCAL.rglob('index.md'))
    check('per-group indexes written', len(indexes) >= 8, str(len(indexes)))
    for name in ('README.md', 'manifest.json', 'AI_PRIORITY.md'):
        check(f'top-level {name} exists', (LOCAL / name).is_file())
    ai_doc = (LOCAL / 'AI_PRIORITY.md').read_text('utf8')
    check('AI priority doc explains all layers',
          all(k in ai_doc for k in ('ai_skill_order', 'ai_order_param', 'target_order_param',
                                    'boss_skill_sequence', '-10000')))
    check('AI priority doc has no duplicated numbering',
          '1. ①' not in ai_doc)
    sample = lua[0].read_text('utf8')
    check('Lua file header records provenance',
          sample.startswith('-- ') and 'field:' in sample and 'references:' in sample)
    priority = world['aiMeta']['priority']
    check('priority logic exported with distribution',
          len(priority['baseOrder']) > 5 and len(priority['luaWeights']) > 4,
          f"{len(priority['baseOrder'])} orders / {len(priority['luaWeights'])} weights")
    check('priority veto values detected', any(v <= -10000 for v in priority['vetoValues']),
          str(priority['vetoValues']))

    # ---- 4. Battle power constants ----
    bp = world['battlePower']
    check('battle power divisors from const_param',
          bp['divisors'] == [120, 200] and bp['constId'] == 132, str(bp['divisors']))
    check('profession coefficients exported', len(bp['coefficients']) == 6)
    check('rarity adjustments exported', len(bp['rarity']) == 4)

    errors, failed = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(offline=True, viewport={'width': 1600, 'height': 1000}).new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))

        # ---- 1. Maps UI ----
        page.goto(BASE + '#/maps')
        page.locator('#world-map-list').wait_for()
        # 3D is now a CSS-3D DOM grid (ported from SoCxiezhouTool), not SVG.
        check('3D frame fixed and present', page.locator('[data-world-iso-view]').count() > 0,
              str(page.locator('[data-world-iso-view]').count()))
        iso = page.locator('[data-world-iso-view]').first
        check('3D blocks rendered', iso.locator('.world-iso-cell').count() > 50,
              str(iso.locator('.world-iso-cell').count()))
        fb = iso.bounding_box()
        check('3D frame has a fixed height', 300 <= fb['height'] <= 380, str(fb['height']))
        check('terrain legend uses Chinese names',
              any(any(c in x for c in '土地草地石板禁行深水') for x in
                  page.locator('[data-world-terrain]').all_inner_texts()[:6]),
              str(page.locator('[data-world-terrain]').all_inner_texts()[:4]))
        check('stage names shown as card titles',
              page.locator('.world-stage-names').count() > 0)
        page.locator('[data-world-view]').first.click()
        page.wait_for_timeout(220)
        check('2D/3D toggle works', page.locator('svg.world-grid:not(.world-grid-iso)').count() > 0)

        # ---- 3. Pagination on all three pages ----
        for route, pager, list_sel in (('#/maps', 'world-map-pager', '.world-map-card'),
                                       ('#/code', 'world-code-pager', '.world-code-card'),
                                       ('#/ai', 'world-ai-pager', '.world-ai-card')):
            page.goto(BASE + route)
            page.locator('#world-' + route.split('/')[-1] + '-list').wait_for() \
                if route != '#/maps' else page.locator('#world-map-list').wait_for()
            pager_el = page.locator('#' + pager)
            check(f'{route} has pager buttons', pager_el.locator('[data-page]').count() > 2,
                  str(pager_el.locator('[data-page]').count()))
            check(f'{route} has no load-more button',
                  page.locator('[id$="-more"]').count() == 0)
            before = page.locator(list_sel).first.inner_text()[:60]
            pager_el.locator('[data-page="next"]').click()
            page.wait_for_timeout(250)
            after = page.locator(list_sel).first.inner_text()[:60]
            check(f'{route} next page changes content', before != after,
                  f'{before[:28]} -> {after[:28]}')
            check(f'{route} active page = 2',
                  page.locator('#' + pager + ' button.active').inner_text() == '2')

        # ---- 3. AI priority card ----
        page.goto(BASE + '#/ai')
        page.locator('#world-ai-list').wait_for()
        check('AI priority card present', page.locator('.world-priority-card').count() >= 2)
        check('AI priority explains five layers',
              page.locator('.world-priority-card').last.locator('.world-priority-steps li').count() == 5)
        check('AI priority shows veto weights',
              page.locator('.world-priority-grid .is-veto').count() > 0)

        # ---- 2. Code page local notice ----
        page.goto(BASE + '#/code')
        page.locator('#world-code-list').wait_for()
        check('local folder notice shown', 'output/client-code' in
              page.locator('.world-local-notice').inner_text())

        # ---- 4. Battle power UI ----
        page.goto(BASE + '#/tools/panel')
        page.locator('#panel-output .panel-total-grid').wait_for()
        power = page.locator('.panel-battle-power strong').inner_text()
        check('battle power displayed', power.isdigit() or ',' in power, power)
        page.locator('.panel-bp-detail').evaluate('e=>{e.open=true}')
        detail = page.locator('.panel-bp-detail').inner_text()
        check('battle power formula shown', '120' in detail and '200' in detail and 'battle_power_coefficient' in detail)
        check('battle power source disclosed', '编译代码' in detail or '复现' in detail)
        page.locator('[data-path="weapon.level"]').select_option('1')
        page.wait_for_timeout(250)
        check('battle power follows the panel',
              page.locator('.panel-battle-power strong').inner_text() != power,
              f'{power} -> {page.locator(".panel-battle-power strong").inner_text()}')
        calc = page.evaluate("""()=>{const P=window.WIKI_PANEL_DATA,C=window.WikiPanelCalc,W=window.WIKI_WORLD_DATA;
          const r=C.calculate(C.defaults(P),P);const b=C.battlePower(r,W,P);
          return {total:b.total,base:b.base,rarity:b.rarity,profession:b.profession};}""")
        check('battle power pure function consistent',
              calc['total'] > 0 and calc['base'] > 0, str(calc))

        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
