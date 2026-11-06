"""Round 14: battle power evidence/candidates/calibration, CSS-3D map camera,
fixed frame + yaw/tilt rotation, AI pathfinding/target analysis.

    python -X utf8 scripts/verify_round14.py
"""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / 'index.html').as_uri()
REF = Path(r'D:\Workspace\SoCxiezhouTool\app\js\map.js')
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

    # ---- 1. Battle power evidence ----
    bp = W['battlePower']
    check('formula evidence lists all client constants',
          len(bp['evidence']) == 5 and any('const_param#132' in x for x in bp['evidence']))
    check('explicitly states formula is not in config data',
          any('IL2CPP' in x or '编译' in x for x in bp['evidence']))
    check('four candidate formulas offered', len(bp['candidates']) == 4,
          str([c['id'] for c in bp['candidates']]))
    check('reference power curve exported', len(bp['questPowerCurve']) >= 60)

    # ---- 4. AI pathfinding data ----
    pf = W['aiMeta']['pathfinding']
    check('move types inventoried', len(pf['moveTypes']) == 5)
    check('terrain costs inventoried', len(pf['terrainCost']) == 30)
    check('target methods inventoried', len(pf['targetMethods']) == 18)
    check('target filter scripts counted', pf['targetFilterScripts'] > 500,
          str(pf['targetFilterScripts']))
    check('Lua map APIs inventoried', len(pf['luaApis']) >= 10, str(len(pf['luaApis'])))
    check('pathfinding explanation states solver is compiled',
          any('寻路算法' in x or '求解器' in x for x in pf['explanation']))
    check('target selection explanation covers four layers',
          any('目标排序' in x for x in pf['explanation']))

    # ---- 3. Reference implementation is the CSS-3D camera ----
    if REF.is_file():
        ref = REF.read_text('utf8')
        check('reference uses rotateX(tilt) rotateZ(yaw)',
              ('--tilt' in ref and '--yaw' in ref
               and 'camYaw' in ref and 'camTilt' in ref))
        check('reference uses drag right -> yaw decrease',
              'orbit.yaw - dx' in ref)

    errors, failed = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(offline=True, viewport={'width': 1600, 'height': 1000}).new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))

        # ---- 1. Battle power UI ----
        page.goto(BASE + '#/tools/panel')
        page.locator('#panel-output .panel-total-grid').wait_for()
        check('formula uncertainty disclosed', '未确证' in
              page.locator('.panel-battle-power').inner_text())
        check('evidence list shown', page.locator('.panel-bp-evidence li').count() == 5)
        check('candidate selector shown', page.locator('[data-bp-method]').count() == 1)
        check('four candidates selectable',
              page.locator('[data-bp-method] option').count() == 4)
        before = page.locator('.panel-battle-power strong').inner_text()
        page.locator('[data-bp-method]').select_option('permille-white')
        page.wait_for_timeout(220)
        after = page.locator('.panel-battle-power strong').inner_text()
        check('switching candidate changes result', before != after, f'{before} -> {after}')
        check('candidate selection survives repaint',
              page.locator('[data-bp-method]').input_value() == 'permille-white')
        page.locator('[data-bp-calibration]').fill('3000')
        page.locator('[data-bp-calibration]').dispatch_event('change')
        page.wait_for_timeout(220)
        check('calibration reverse-derives a multiplier',
              page.locator('.panel-bp-implied').count() == 1,
              page.locator('.panel-bp-implied').inner_text()[:60])
        check('calibration value survives repaint',
              page.locator('[data-bp-calibration]').input_value() == '3000')
        calc = page.evaluate("""()=>{const P=window.WIKI_PANEL_DATA,C=window.WikiPanelCalc,W=window.WIKI_WORLD_DATA;
          const r=C.calculate(C.defaults(P),P);
          return {a:C.battlePower(r,W,P,{method:'permille-final'}).total,
                  b:C.battlePower(r,W,P,{method:'permille-white'}).total,
                  c:C.battlePower(r,W,P,{method:'divisor-final'}).total,
                  scale:C.battlePower(r,W,P,{calibration:3000}).impliedScale};}""")
        check('candidates produce distinct values',
              len({calc['a'], calc['b'], calc['c']}) == 3, str(calc))
        check('implied scale is finite and positive',
              calc['scale'] and 0 < calc['scale'] < 100, str(calc['scale']))

        # ---- 2/3. CSS-3D map ----
        page.goto(BASE + '#/maps')
        page.locator('#world-map-list').wait_for()
        frames = page.locator('[data-world-iso-view]')
        check('CSS-3D frames render', frames.count() > 0, str(frames.count()))
        f = frames.first
        box0 = f.bounding_box()
        check('display frame has fixed height', 300 <= box0['height'] <= 380, str(box0['height']))
        check('canvas uses rotateX/rotateZ',
              'rotateX' in f.locator('.world-iso-canvas').evaluate('e=>e.style.cssText')
              or f.locator('.world-iso-canvas').evaluate('e=>getComputedStyle(e).transform').startswith('matrix3d'))
        check('frame declares perspective',
              f.evaluate('e=>getComputedStyle(e).perspective') != 'none',
              f.evaluate('e=>getComputedStyle(e).perspective'))
        check('3D cells render', f.locator('.world-iso-cell').count() > 50)
        check('reset camera button present', page.locator('[data-world-reset]').count() > 0)
        yaw0 = float(f.get_attribute('data-yaw'))
        tilt0 = float(f.get_attribute('data-tilt'))
        cx, cy = box0['x'] + box0['width'] / 2, box0['y'] + box0['height'] / 2
        page.mouse.move(cx, cy); page.mouse.down()
        page.mouse.move(cx + 100, cy, steps=6); page.mouse.up()
        page.wait_for_timeout(200)
        yaw1 = float(page.locator('[data-world-iso-view]').first.get_attribute('data-yaw'))
        check('drag right decreases yaw (direction fixed)', yaw1 < yaw0, f'{yaw0} -> {yaw1}')
        page.mouse.move(cx, cy); page.mouse.down()
        page.mouse.move(cx, cy - 60, steps=6); page.mouse.up()
        page.wait_for_timeout(200)
        tilt1 = float(page.locator('[data-world-iso-view]').first.get_attribute('data-tilt'))
        check('drag up increases tilt (vertical rotation)', tilt1 > tilt0, f'{tilt0} -> {tilt1}')
        page.mouse.wheel(0, -240)
        page.wait_for_timeout(200)
        scale1 = float(page.locator('[data-world-iso-view]').first.get_attribute('data-scale'))
        check('wheel zoom works', scale1 > 1, str(scale1))
        box1 = page.locator('[data-world-iso-view]').first.bounding_box()
        check('frame stays fixed after rotate + zoom',
              abs(box1['height'] - box0['height']) < 2 and abs(box1['width'] - box0['width']) < 2,
              f"{box0['width']}x{box0['height']} -> {box1['width']}x{box1['height']}")
        page.locator('[data-world-reset]').first.click()
        page.wait_for_timeout(200)
        fr = page.locator('[data-world-iso-view]').first
        check('reset restores camera',
              float(fr.get_attribute('data-yaw')) == 45 and float(fr.get_attribute('data-tilt')) == 54
              and float(fr.get_attribute('data-scale')) == 1)
        # To 135° and back: rendering must stay correct at arbitrary angles.
        bb = fr.bounding_box()
        cx, cy = bb['x'] + bb['width'] / 2, bb['y'] + bb['height'] / 2
        page.mouse.move(cx, cy); page.mouse.down()
        page.mouse.move(cx - 225, cy + 70, steps=8); page.mouse.up()
        page.wait_for_timeout(200)
        fa = page.locator('[data-world-iso-view]').first
        check('arbitrary yaw/tilt keeps all cells',
              fa.locator('.world-iso-cell').count() == f.locator('.world-iso-cell').count(),
              f"{fa.get_attribute('data-yaw')}° / {fa.get_attribute('data-tilt')}°")

        # ---- 4. AI pathfinding card ----
        page.goto(BASE + '#/ai')
        page.locator('#world-ai-list').wait_for()
        cards = page.locator('.world-priority-card')
        check('two analysis cards (priority + pathfinding)', cards.count() == 2, str(cards.count()))
        check('pathfinding card heading', '选走路路径' in
              cards.first.locator('h3').inner_text())
        check('pathfinding grid has six sections',
              page.locator('.world-pf-grid>div').count() == 6)
        check('pathfinding explains six layers',
              cards.first.locator('.world-priority-steps li').count() == 6)
        check('priority card still explains five layers',
              cards.last.locator('.world-priority-steps li').count() == 5)

        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
