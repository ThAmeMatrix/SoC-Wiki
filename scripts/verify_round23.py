"""Round 23: gridIso reuse, layout fix, full cup parsing, result boundary/predictions.

    python -X utf8 scripts/verify_round23.py
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


def load(rel, var):
    t = (ROOT / rel).read_text('utf8')
    m = 'window.' + var + '='
    return json.JSONDecoder().raw_decode(t[t.index(m) + len(m):])[0]


def main():
    C = load('data/match-cup.js', 'WIKI_MATCH_CUP')
    ui = (ROOT / 'battle-sim-ui.js').read_text('utf8')
    w = (ROOT / 'world-ui.js').read_text('utf8')
    css = (ROOT / 'refinements.css').read_text('utf8')
    pkg = (ROOT / 'scripts/package.py').read_text('utf8')
    reb = (ROOT / 'scripts/socdecode/rebuild.py').read_text('utf8')

    # ---------- 1. gridIso reuse ----------
    # Round 29: renderLuaScripts added to the WikiWorld export list.
    check('gridIso exported from world-ui', 'renderEnhance, renderLuaScripts, gridIso, gridSvg' in w)
    check('simulator calls gridIso', 'WikiWorld?.gridIso' in ui and 'world-iso-cell' in ui)
    check('simulator no longer reimplements cubes', 'bsim3-cell' not in ui and 'staticBoard3D()' in ui)
    check('3D unit layer rides the world canvas', "canvas.appendChild(dyn)" in ui)
    check('gridIso frame scoped inside simulator', '.bsim-board .world-iso-frame.is-bsim' in css)

    # ---------- 2. layout ----------
    check('setup column clamps its content',
          '.bsim-setup{position:sticky;top:96px;display:grid;grid-template-columns:minmax(0,1fr)' in css
          and '.bsim-setup>*{min-width:0;max-width:100%}' in css)
    check('cup body clamps long text', 'grid-template-columns:minmax(0,1fr)' in css and 'overflow-wrap:anywhere' in css)

    # ---------- 3. full cup parsing ----------
    check('cup data schema v2', C.get('v') == 2)
    check('63 teams with 408 fighters', len(C['teams']) == 63 and
          sum(len(t['members']) for t in C['teams']) == 408, str(sum(len(t['members']) for t in C['teams'])))
    allsk = [s for t in C['teams'] for m in t['members'] for s in m['allSkills']]
    roles = {s['role'] for s in allsk}
    # Round 24: personality skills are taken per star tier (one per skill group),
    # so the total dropped from the earlier over-counted 4044.
    # Round 25: unit_npc.skill_ids is split by client skill.type into 主动/被动,
    # so "初始技能" (which came from the player `unit` template) is gone, while
    # the four skill-chain families are now resolved.
    check('every skill family parsed', len(allsk) > 2500 and
          {'普攻', '主动技能', '被动技能', '反应技', '个性', '附属被动', '连携技能', '施放技能'} <= roles,
          str(len(allsk)) + ' ' + str(sorted(roles)))
    check('fighters have personality / editor / AI fields',
          all(m.get('personality') is not None and 'editorName' in m and 'aiByOrder' in m
              for t in C['teams'] for m in t['members']))
    check('simulated skills keep numeric fields',
          all('rangeMax' in s and 'factor' in s for t in C['teams'][:5] for m in t['members'] for s in m['skills']))
    check('names cleaned of sprite markup',
          all('<sprite' not in m['name'] for t in C['teams'] for m in t['members']))
    sched = C['schedules']
    check('every schedule resolves a story quest',
          all(s['quest']['id'] and s['quest']['name'] for s in sched))
    check('every schedule has buff details + unit status',
          all('buffDetails' in s and 'unitStatus' in s for s in sched) and
          any(s['buffDetails'] and s['buffDetails'][0]['effect'] for s in sched))
    check('round info attached to schedules', all('roundCount' in s and 'turnLimit' in s['quest'] for s in sched))
    check('arena map candidates exported', len(C['arenaMaps']) >= 1 and
          all(m['cells'] > 100 for m in C['arenaMaps']), str(C['arenaMaps']))
    check('match types / bracket exported', len(C['matchTypes']) >= 5)
    check('sources document the new tables', len(C['sources']) >= 10, str(len(C['sources'])))
    check('package + rebuild include the extractor',
          'scripts/extract_match_cup.py' in pkg and 'extract_match_cup.py' in reb)

    # ---------- 4. result boundary ----------
    ra = C['resultAvailability']
    check('official per-match results explicitly unavailable', ra['hasOfficialResults'] is False and
          len(ra['searched']) >= 4, str(ra['searched']))
    check('boundary explained in notes', any('不编造赛果' in n for n in C['notes']) and
          any('交叉推定' in n for n in C['notes']))
    check('predictions implemented in UI', 'predictOne' in ui and 'predictCup' in ui and 'renderPredictions' in ui)

    errors, failed = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(offline=True, viewport={'width': 1500, 'height': 950})
        page = ctx.new_page()
        page.set_default_timeout(25000)
        page.on('pageerror', lambda x: errors.append(str(x)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))
        page.goto(BASE + '#/tools/battle')
        page.locator('#bsim-board svg').wait_for(timeout=30000)

        # ---------- 2. runtime layout ----------
        boxes = page.evaluate("""()=>{const s=document.querySelector('.bsim-setup'),
            t=document.querySelector('.bsim-stage');return {sw:s.scrollWidth,cw:s.clientWidth,
            setupRight:Math.round(s.getBoundingClientRect().right),
            stageLeft:Math.round(t.getBoundingClientRect().left)};}""")
        check('setup no longer overflows', boxes['sw'] <= boxes['cw'] + 2, str(boxes))
        check('setup no longer overlaps the stage', boxes['setupRight'] < boxes['stageLeft'], str(boxes))

        # ---------- 1. runtime 3D ----------
        page.locator('[data-bsim-view="3d"]').click()
        page.wait_for_timeout(450)
        cubes = page.locator('#bsim-board .world-iso-cell').count()
        check('gridIso cells render in simulator', cubes > 40, str(cubes))
        check('real side walls + pits from gridIso',
              page.locator('#bsim-board .world-iso-wall').count() > 100 and
              page.locator('#bsim-board .world-iso-block.is-pit').count() > 0)
        check('top textures applied', page.locator('#bsim-board .world-iso-cell.has-art').count() > 20)
        check('units ride the 3D canvas', page.locator('.bsim3-dyn .bsim3-unit').count() >= 2)
        f = page.locator('#bsim-board .world-iso-frame')
        bb = f.bounding_box()
        page.mouse.move(bb['x'] + bb['width'] / 2, bb['y'] + bb['height'] / 2)
        page.mouse.down()
        page.mouse.move(bb['x'] + bb['width'] / 2 - 100, bb['y'] + bb['height'] / 2 + 50, steps=6)
        page.mouse.up()
        page.wait_for_timeout(220)
        cam = page.evaluate("""()=>{const c=document.querySelector('#bsim-board .world-iso-canvas');
            return [c.style.getPropertyValue('--yaw'),c.style.getPropertyValue('--tilt')];}""")
        check('camera orbits on the shared renderer', cam[0] != '45deg' and cam[1] != '54deg', str(cam))
        page.mouse.wheel(0, -200); page.wait_for_timeout(180)
        check('wheel zoom works', page.evaluate("""()=>document.querySelector('#bsim-board .world-iso-frame')
            .style.getPropertyValue('--zoom')""") != '1')
        found = False
        for _ in range(14):
            page.locator('[data-play="next"]').click()
            if page.locator('#bsim-board .world-iso-cell.is-area').count():
                found = True
                break
        check('replay highlights real cube tops', found)
        page.locator('[data-cam-reset]').click()
        check('reset camera', page.evaluate("""()=>{const c=document.querySelector('#bsim-board .world-iso-canvas');
            return c.style.getPropertyValue('--yaw')==='45deg'&&c.style.getPropertyValue('--tilt')==='54deg';}"""))
        page.locator('[data-bsim-view="2d"]').click(); page.wait_for_timeout(220)
        check('back to 2D', page.locator('.bsim-svg').count() == 1)

        # ---------- 3. runtime cup data ----------
        page.evaluate("()=>{document.querySelector('.bsim-cup').open=true;}")
        check('roster + full skills visible',
              page.locator('.bsim-cup-unit').count() >= 10 and
              page.locator('.bsim-cup-skill').count() >= 50)
        info = page.locator('#bsim-cup-info').inner_text()
        check('quest / buff / status / odds visible',
              all(k in info for k in ('赛程关卡', '赛事增益', '选手状态', '不是官方赛果', '押注参考')), info[:120])
        check('arena map selectable', page.locator('#bsim-cup-map option').count() >= 1)
        page.evaluate("()=>{document.querySelector('.bsim-cup-roster').open=true;document.querySelector('.bsim-cup-unit').open=true;}")
        detail = page.locator('.bsim-cup-unit').first.inner_text()
        check('unit detail shows stats + skill roles',
              '60 级成长表' in detail and '仅资料' in detail or '普攻' in detail, detail[:120])

        # ---------- 4. runtime predictions ----------
        page.locator('[data-cup-predict="one"]').click()
        page.wait_for_timeout(1000)
        check('one-match prediction', page.locator('.bsim-pred-table tbody tr').count() == 1)
        head = page.locator('.bsim-pred-head').inner_text()
        row = page.locator('.bsim-pred-table tbody tr').first.inner_text()
        check('prediction reports winner + rounds', '非官方赛果' in head and
              any(k in row for k in ('小队', '队', '平局')) and any(c.isdigit() for c in row), row[:130])
        check('prediction columns complete',
              all(k in page.locator('.bsim-pred-table thead').inner_text()
                  for k in ('持续回合', '行动数', '存活')))

        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
