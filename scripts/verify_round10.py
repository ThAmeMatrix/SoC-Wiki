"""Round 10: whiteboard percent formula, equipment base display, preset JSON IO,
client maps and auto-battle AI browsers.

    python -X utf8 scripts/verify_round10.py
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
    # ---- 1. Whiteboard formula documented with the in-client source ----
    combat = load('data/combat-data.js', 'WIKI_COMBAT_DATA')
    panel_formula = next(f for f in combat['formulas'] if f['id'] == 'panel')
    check('formula cites the archived whiteboard definition',
          '白板' in panel_formula['source'] and '塔罗图鉴库' in panel_formula['source'],
          panel_formula['source'][:150])
    check('formula expression uses whiteboard',
          '白板' in panel_formula['expr'], panel_formula['expr'][:130])
    check('formula step says Q applies to whiteboard only',
          any('白板' in s for s in panel_formula['steps']))

    # ---- 4/5. World data exported ----
    world = load('data/world-data.js', 'WIKI_WORLD_DATA')
    check('maps exported', len(world['maps']) > 500, str(len(world['maps'])))
    check('map grids decoded',
          sum(len(m['cells']) for m in world['maps']) > 100000,
          str(sum(len(m['cells']) for m in world['maps'])))
    check('map metadata includes weather',
          any(m['weather'] for m in world['maps']))
    check('AI units exported', len(world['aiUnits']) > 8000, str(len(world['aiUnits'])))
    check('AI Lua scripts exported', len(world['aiScripts']) > 10, str(len(world['aiScripts'])))
    check('AI boss sequences present',
          any(u['sequence'] for u in world['aiUnits']))
    # AI records now also include numeric-only AI settings; the Lua-bearing
    # ones must still keep the verbatim script.
    check('AI Lua records keep raw Lua',
          all('lua' in s for s in world['aiScripts'])
          and any(s['lua'].strip() for s in world['aiScripts']))

    errors, failed = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(offline=True, viewport={'width': 1600, 'height': 900}).new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))

        # ---- 1/2/3. Panel ----
        page.goto(BASE + '#/tools/panel')
        page.locator('#panel-output .panel-total-grid').wait_for()
        page.locator('.panel-formula').evaluate('e=>{e.open=true}')
        page.wait_for_timeout(180)
        row = page.locator('.formula-row').first.inner_text()
        check('formula shows whiteboard multiplication',
              '白板' in row and '100%' in row, row[:130].replace('\n', ' '))
        check('formula shows addends outside the multiplier',
              '武器' in row and '天赋固定' in row)
        check('whiteboard note visible', '白板' in page.locator('.panel-formula').inner_text())
        calc = page.evaluate("""()=>{const P=window.WIKI_PANEL_DATA,C=window.WikiPanelCalc;
          const r=C.calculate(C.defaults(P),P);
          return {whiteboard:r.whiteboard[0],addends:r.addends[0],perm:r.permillage[0],
                  total:r.total[0],flat:r.flat[0]};}""")
        expect = (calc['whiteboard'] * (1000 + calc['perm']) // 1000) + calc['addends']
        check('total = scaled whiteboard + addends', calc['total'] == expect,
              f"{calc['whiteboard']}×{(1000 + calc['perm']) / 1000}+{calc['addends']}={expect}, got {calc['total']}")
        old = calc['flat'] * (1000 + calc['perm']) // 1000
        check('not the old whole-total formula', calc['total'] != old, f'{old} vs {calc["total"]}')

        bases = page.locator('.panel-equip-base')
        check('three equipment base blocks', bases.count() == 3, str(bases.count()))
        check('weapon base shows five stats',
              bases.first.locator('strong').count() == 5,
              bases.first.inner_text()[:100].replace('\n', ' '))
        check('equipment base values are numeric',
              all(any(ch.isdigit() for ch in x) for x in bases.first.locator('strong').all_inner_texts()))

        # Preset JSON round-trip.
        page.locator('.preset-card').evaluate('e=>{e.open=true}')
        check('plan import/export buttons present',
              page.locator('[data-tool="export-panel-plans"]').count() == 1
              and page.locator('[data-tool="import-panel-plans"]').count() == 1)
        tmp = Path(tempfile.gettempdir())
        with page.expect_download() as dl:
            page.locator('[data-tool="export-panel-plans"]').click()
        exported = tmp / 'socwiki-r10-export.json'
        dl.value.save_as(str(exported))
        payload = json.loads(exported.read_text('utf8'))
        check('export format and current config',
              payload.get('format') == 'socwiki-panel-plans' and 'current' in payload
              and isinstance(payload.get('presets'), list))
        payload['presets'] = [{'name': '导入验证', 'config': payload['current']}]
        incoming = tmp / 'socwiki-r10-import.json'
        incoming.write_text(json.dumps(payload, ensure_ascii=False), 'utf8')
        page.locator('#panel-plan-file').set_input_files(str(incoming))
        page.wait_for_timeout(450)
        # paint() re-renders the folded preset card, so inner_text can be
        # empty for hidden content; use text_content instead.
        names = page.eval_on_selector_all('[data-panel-preset]', 'els=>els.map(e=>e.textContent.trim())')
        check('imported preset appears', any('导入验证' in x for x in names), str(names))

        # ---- 4. Maps browser ----
        page.goto(BASE + '#/maps')
        page.locator('#world-map-list').wait_for()
        check('map cards render', page.locator('.world-map-card').count() > 0)
        check('map grids render (CSS-3D or 2D SVG)',
              page.locator('[data-world-iso-view], svg.world-grid').count() > 0)
        check('map count shown', '632' in page.locator('#world-map-count').inner_text())
        page.locator('#world-map-query').fill('stage05')
        page.wait_for_timeout(200)
        check('map search filters', page.locator('.world-map-card').count() < 24,
              str(page.locator('.world-map-card').count()))
        page.locator('#world-map-grid').check()
        page.wait_for_timeout(200)
        check('grid-only filter works',
              page.locator('.world-map-card').count() >= 0
              and '2 /' in page.locator('#world-map-count').inner_text(),
              page.locator('#world-map-count').inner_text())

        # ---- 5. AI browser ----
        page.goto(BASE + '#/ai')
        page.locator('#world-ai-list').wait_for()
        check('AI unit cards render', page.locator('.world-ai-card').count() > 0)
        check('AI unit count shown', '8,114' in page.locator('#world-ai-count').inner_text())
        page.locator('[data-world-tab="scripts"]').click()
        page.wait_for_timeout(200)
        check('AI Lua cards render', page.locator('.world-lua-card').count() > 10,
              str(page.locator('.world-lua-card').count()))
        check('Lua source preserved in UI',
              page.locator('.world-lua').first.inner_text().strip().startswith(('local', 'if', '--', 'return')),
              page.locator('.world-lua').first.inner_text()[:60].replace('\n', ' '))
        page.locator('#world-ai-query').fill('防御姿态')
        page.wait_for_timeout(200)
        check('AI search works', page.locator('.world-lua-card').count() == 1,
              str(page.locator('.world-lua-card').count()))

        # New pages are hidden by default (nav-config.js); the config must
        # still expose them and allow enabling them per browser.
        # New pages are hidden by default (nav-config.js); the config must
        # still list them and allow enabling them per browser.
        check('sidebar config lists both new entries',
              page.evaluate("() => ['#/maps','#/ai'].every(k => k in (window.WIKI_NAV_CONFIG || {}).show)"))
        js = """() => {
            window.WikiNav.set('#/maps', true);
            window.WikiNav.set('#/ai', true);
            return !!document.querySelector('#sidebar a[href="#/maps"]');
        }"""
        check('hidden entries can be enabled via WikiNav', page.evaluate(js))
        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
