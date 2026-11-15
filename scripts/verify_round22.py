"""Round 22: simulator 3D, custom fighters, 乐土群星杯 client data injection.

    python -X utf8 scripts/verify_round22.py
"""
import json
import subprocess
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / 'index.html').as_uri()
NODE = Path(r'C:\Users\thamechen\AppData\Local\Programs\Python\Python313\Lib\site-packages\playwright\driver\node.exe')
failures = []


def check(name, ok, detail=''):
    print(('PASS ' if ok else 'FAIL ') + name + (f' :: {detail}' if detail else ''), flush=True)
    if not ok:
        failures.append(name)


def load(rel, var=None):
    t = (ROOT / rel).read_text('utf8')
    marker = 'window.' + var + '=' if var else '='
    return json.JSONDecoder().raw_decode(t[t.index(marker) + len(marker):])[0]


CUSTOM_ENGINE = r"""
const fs=require('fs'),vm=require('vm');const ctx={window:{}};vm.createContext(ctx);
for(const f of ['data/world-data.js','data/battle-sim.js','data/match-cup.js','battle-sim-core.js'])
  vm.runInContext(fs.readFileSync(f,'utf8'),ctx);
const W=ctx.window.WIKI_WORLD_DATA,D=ctx.window.WIKI_BATTLE_SIM,C=ctx.window.WIKI_MATCH_CUP,S=ctx.window.WikiBattleSim;
const map=W.maps.find(m=>m.id===3)||W.maps.find(m=>(m.cells||[]).length>=100);
const team=C.teams[0],team2=C.teams[1];
const cv=t=>(t.members||[]).slice(0,8).map(m=>({name:m.name,stats:{...m.stats},move:{...m.move},
  prof:m.prof,skills:m.skills.map(s=>({...s}))}));
const r=S.simulate({data:D,map,teams:{A:cv(team),B:cv(team2)},seed:5,maxRounds:20});
// custom edited stats must be honoured
const custom={name:'测试自定义',stats:{hp:99999,patk:2000,matk:2000,pdef:500,mdef:500,spd:300},
 move:{mob:3,up:2,down:2,type:1},prof:6,skills:[{id:'x1',name:'自定义技能',usable:true,heal:false,
 factor:250,rangeMin:0,rangeMax:3,shape:'diamond',aim:'enemy',area:{type:'single'},cooldown:0,
 order:0,hits:1,damageType:1,ignoreDef:false,attackUp:0,attackDown:0}]};
const r2=S.simulate({data:D,map,teams:{A:[custom],B:cv(team2)},seed:5,maxRounds:20});
// spawn anchors must be on opposite sides
const g=S.prepareMap(map,D);const sp=S.spawnCells(g,4,4);
const ax=sp.A.reduce((a,c)=>a+c.x,0)/sp.A.length,bx=sp.B.reduce((a,c)=>a+c.x,0)/sp.B.length;
console.log(JSON.stringify({cupWinner:r.winner,cupSteps:r.steps.length,cupUnits:r.units.length,
 customHp:r2.units[0].maxHp,customUsed:r2.steps.some(s=>s.skill&&s.skill.name==='自定义技能'),
 anchorsGap:Math.round(Math.abs(ax-bx)),gridW:g.w,teamSizes:[team.members.length,team2.members.length]}));
"""


def main():
    # ---------- static: cup data ----------
    C = load('data/match-cup.js', 'WIKI_MATCH_CUP')
    check('cup data export exists', C.get('title') == '乐土群星杯')
    check('four activity seasons', len(C['activities']) == 4, str(len(C['activities'])))
    check('63 preset teams', len(C['teams']) == 63, str(len(C['teams'])))
    check('>=180 scheduled matches', len(C['schedules']) >= 180, str(len(C['schedules'])))
    check('every scheduled match has both teams',
          all(any(t['id'] == s['team1Id'] for t in C['teams']) and
              any(t['id'] == s['team2Id'] for t in C['teams']) for s in C['schedules']))
    fighters = [m for t in C['teams'] for m in t['members']]
    check('fighters resolved from client tables', len(fighters) >= 350, str(len(fighters)))
    check('every fighter has level-60 stats and skills',
          all(m['stats']['hp'] > 1000 and m['skills'] and m['move']['mob'] > 0 for m in fighters))
    check('cup notes state the data boundaries', len(C['notes']) >= 4 and
          any('buff' in n or '增益' in n for n in C['notes']))
    check('cup sources listed', len(C['sources']) >= 6)
    check('betting odds exported', len(C['bets']) > 50, str(len(C['bets'])))

    perf = (ROOT / 'perf-core.js').read_text('utf8')
    app = (ROOT / 'app.js').read_text('utf8')
    html = (ROOT / 'index.html').read_text('utf8')
    pkg = (ROOT / 'scripts/package.py').read_text('utf8')
    reb = (ROOT / 'scripts/socdecode/rebuild.py').read_text('utf8')
    ui = (ROOT / 'battle-sim-ui.js').read_text('utf8')
    check('cup data loaded on demand', "cup: ['data/match-cup.js'" in perf)
    check('battle route requests cup data', "['world','battle','cup'" in app)
    check('cup data not eager in index.html', 'data/match-cup.js' not in html)
    check('package includes cup data + extractor',
          'data/match-cup.js' in pkg and 'scripts/extract_match_cup.py' in pkg)
    check('rebuild runs extract_match_cup', 'extract_match_cup.py' in reb)
    check('3D renderer reuses battle-map gridIso',
          'function staticBoard3D()' in ui and 'WikiWorld?.gridIso' in ui and 'world-iso-cell' in ui)
    check('custom editor implemented', 'function editorHtml(' in ui and 'data-editor-save' in ui)
    check('view attribute avoids catalog collision', 'data-bsim-view' in ui and 'data-view=' not in ui)

    # ---------- engine (node) ----------
    out = subprocess.run([str(NODE), '-e', CUSTOM_ENGINE], cwd=ROOT,
                         capture_output=True, text=True, encoding='utf8', timeout=240)
    try:
        e = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        e = {}
        print(out.stdout[-600:], out.stderr[-600:])
    check('cup teams simulate end-to-end', e.get('cupWinner') in ('A', 'B', 'draw') and e.get('cupSteps', 0) > 20, str(e))
    check('7v7 cup lineups enter the battle', e.get('cupUnits', 0) >= 10, str(e.get('cupUnits')))
    check('custom stats are honoured', e.get('customHp') == 99999, str(e.get('customHp')))
    check('custom skills are used by the AI', e.get('customUsed') is True)
    check('spawn anchors are on opposite sides', e.get('anchorsGap', 0) >= 4, str(e))

    errors, failed = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(offline=True, viewport={'width': 1500, 'height': 950}, accept_downloads=True)
        page = ctx.new_page()
        page.set_default_timeout(20000)
        page.on('pageerror', lambda x: errors.append(str(x)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))
        reqs = []
        page.on('request', lambda r: reqs.append(r.url))

        # ---------- lazy loading ----------
        page.goto(BASE + '#/')
        page.wait_for_timeout(500)
        check('home does not load cup data', not any('match-cup.js' in u for u in reqs))
        reqs.clear()
        page.goto(BASE + '#/tools/battle')
        page.locator('#bsim-board svg').wait_for(timeout=30000)
        check('battle page loads cup data on demand', any('match-cup.js' in u for u in reqs))
        check('2D board still works', page.locator('.bsim-cell').count() > 40)

        # ---------- 3D ----------
        page.locator('[data-bsim-view="3d"]').click()
        page.wait_for_timeout(400)
        cubes = page.locator('.bsim-board .world-iso-cell').count()
        check('3D cubes drawn from gridIso', cubes > 40, str(cubes))
        check('textured side walls present', page.locator('.bsim-board .world-iso-wall').count() >= cubes * 2)
        check('3D unit tokens present', page.locator('.bsim3-unit').count() >= 2)
        check('2D SVG removed in 3D', page.locator('.bsim-svg').count() == 0)
        check('gridIso frame reused', page.locator('#bsim-board .world-iso-frame.is-bsim').count() == 1)
        tri = page.evaluate("""()=>{const f=document.querySelector('#bsim-board .world-iso-frame'),
            c=f.querySelector('.world-iso-canvas');return {fit:f.style.getPropertyValue('--fit'),
            transform:getComputedStyle(c).transform.slice(0,20),w:f.clientWidth,h:f.clientHeight};}""")
        check('3D perspective + fit applied', tri['transform'].startswith('matrix3d') and float(tri['fit'] or 0) > 0, str(tri))
        bb = page.locator('#bsim-board .world-iso-frame').bounding_box()
        page.mouse.move(bb['x'] + bb['width'] / 2, bb['y'] + bb['height'] / 2)
        page.mouse.down()
        page.mouse.move(bb['x'] + bb['width'] / 2 - 120, bb['y'] + bb['height'] / 2 + 60, steps=8)
        page.mouse.up()
        page.wait_for_timeout(220)
        cam = page.evaluate("""()=>{const c=document.querySelector('#bsim-board .world-iso-canvas');
            return {yaw:c.style.getPropertyValue('--yaw'),tilt:c.style.getPropertyValue('--tilt')};}""")
        check('drag orbits yaw and tilt', cam['yaw'] != '45deg' and cam['tilt'] != '54deg', str(cam))
        page.mouse.wheel(0, -240)
        page.wait_for_timeout(220)
        check('wheel zooms', page.evaluate("()=>document.querySelector('#bsim-board .world-iso-frame').style.getPropertyValue('--zoom')") != '1')
        page.locator('[data-cam-reset]').click()
        check('reset restores camera',
              page.evaluate("""()=>{const f=document.querySelector('#bsim-board .world-iso-frame'),
                c=f.querySelector('.world-iso-canvas');
                return c.style.getPropertyValue('--yaw')==='45deg'&&
                       c.style.getPropertyValue('--tilt')==='54deg'&&
                       f.style.getPropertyValue('--zoom')==='1';}"""))
        found = False
        for _ in range(14):
            page.locator('[data-play="next"]').click()
            if page.locator('#bsim-board .world-iso-cell.is-area').count():
                found = True
                break
        check('3D replay shows area / target / path',
              found and page.locator('#bsim-board .world-iso-cell.is-target').count() == 1,
              f"area={page.locator('#bsim-board .world-iso-cell.is-area').count()}")
        page.locator('[data-bsim-view="2d"]').click()
        page.wait_for_timeout(250)
        check('switch back to 2D', page.locator('.bsim-svg').count() == 1 and page.locator('#bsim-board .world-iso-frame').count() == 0)

        # ---------- custom editor ----------
        page.locator('[data-edit="A:0"]').first.click()
        page.wait_for_timeout(200)
        check('editor dialog opens', page.locator('#bsim-editor').evaluate('e=>e.open'))
        check('six stat fields + skill editor',
              page.locator('#bsim-editor-body [data-stat]').count() == 6 and
              page.locator('.bsim-eskill').count() >= 1)
        page.locator('#bsim-editor-body [data-stat="hp"]').fill('99999')
        page.locator('[data-editor-save]').click()
        page.wait_for_timeout(400)
        check('edited fighter marked custom', page.locator('#bsim-chips-A .bsim-chip.is-custom').count() == 1)
        check('edited HP reaches the battle', page.locator('#bsim-units').inner_text().find('99,999') >= 0)
        page.locator('[data-edit="A:0"]').first.click()
        page.wait_for_timeout(180)
        n0 = page.locator('.bsim-eskill').count()
        page.locator('[data-skill-add]').click()
        check('skills can be added', page.locator('.bsim-eskill').count() == n0 + 1)
        page.locator('.bsim-eskill').last.locator('[data-skill-del]').click()
        check('skills can be removed', page.locator('.bsim-eskill').count() == n0)
        page.locator('[data-editor-close]').click()
        page.locator('[data-new="B"]').click()
        page.wait_for_timeout(180)
        check('new custom fighter can be created', page.locator('#bsim-editor').evaluate('e=>e.open'))
        page.locator('[data-editor-close]').click()

        # ---------- cup injection ----------
        page.evaluate("()=>{document.querySelector('.bsim-cup').open=true;}")
        info = page.locator('#bsim-cup-info').inner_text()
        check('cup panel shows matchup + buffs + odds',
              'vs' in info and '赛事增益' in info and '押注参考' in info, info[:110])
        check('schedules selectable', page.locator('#bsim-cup-sched option').count() >= 40)
        page.locator('[data-cup-load="both"]').click()
        page.wait_for_timeout(700)
        check('both cup lineups loaded', page.locator('#bsim-chips-A .bsim-chip').count() >= 5 and
              page.locator('#bsim-chips-B .bsim-chip').count() >= 5)
        check('loaded fighters are custom units',
              page.locator('.bsim-chip.is-custom').count() >= 10)
        check('cup battle simulated', '胜利' in page.locator('.bsim-result').inner_text() or
              '平局' in page.locator('.bsim-result').inner_text())
        check('cup notes shown in UI', page.locator('.bsim-cup .rich-text li').count() >= 4)
        check('roster + full skills shown',
              page.locator('.bsim-cup-unit').count() >= 10 and page.locator('.bsim-cup-skill').count() >= 50)
        check('TXT/JSON export still available',
              page.locator('[data-export="txt"]').count() == 1 and page.locator('[data-export="json"]').count() == 1)

        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
