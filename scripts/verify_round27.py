"""Round 27: normal speed semantics, map spawn picking, left column scrollbar,
and the 「精英属性补回」compensation provenance / default disable.

    python -X utf8 scripts/verify_round27.py
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


def load(rel, var):
    t = (ROOT / rel).read_text('utf8')
    m = 'window.' + var + '='
    return json.JSONDecoder().raw_decode(t[t.index(m) + len(m):])[0]


ENGINE = r"""
const fs=require('fs'),vm=require('vm');const ctx={window:{}};vm.createContext(ctx);
for(const f of ['data/world-data.js','data/battle-sim.js','data/match-cup.js','data/battle-mech.js','battle-sim-core.js'])
  vm.runInContext(fs.readFileSync(f,'utf8'),ctx);
const W=ctx.window.WIKI_WORLD_DATA,D=ctx.window.WIKI_BATTLE_SIM,C=ctx.window.WIKI_MATCH_CUP,M=ctx.window.WIKI_BATTLE_MECH,S=ctx.window.WikiBattleSim;
const arena=W.maps.find(m=>m.id===C.environment.mapId);
const team=id=>C.teams.find(t=>t.id===id);
const mem=t=>t.members.map(m=>({name:m.name,stats:m.stats,move:m.move,prof:m.prof,profName:m.profName,
  kit:m.kit,skills:m.skills,edited:false,npcId:m.npcId,star:m.star}));
const s0=C.schedules[0];
const opts={data:D,mech:M,map:arena,teams:{A:mem(team(s0.team1Id)),B:mem(team(s0.team2Id))},seed:42,maxRounds:20};
const r=S.simulate(opts);
// speed: converted specs, panel, and strict turn order
const spdSpecs=Object.entries(M.specs).filter(([k,s])=>
  (s.t==='MODIFY_ATTRIBUTE'||s.t==='PREWAR_MODIFY_ATTRIBUTE')&&s.p[0]===17);
const allSpeeds=r.units.map(u=>({uid:u.uid,spd:Math.round(r.inspect(0,u.uid).attrs.find(a=>a.key==='SPEED').value)}));
const ranked=[...allSpeeds].sort((a,b)=>b.spd-a.spd);
const acting=[];for(const st of r.steps.slice(1,40))if(st.actor&&!acting.includes(st.actor))acting.push(st.actor);
const p0=r.inspect(0,r.units[0].uid);
const spdRow=p0.attrs.find(a=>a.key==='SPEED');
// first 8 actors must follow the speed ranking (ties allowed)
const rankOf=uid=>ranked.findIndex(x=>x.uid===uid);
let orderOk=true;
for(let i=1;i<Math.min(8,acting.length);i++) if(rankOf(acting[i])<rankOf(acting[i-1])) orderOk=false;
// elite comp: default out of kit, optional on
let withC=0,inKit=0;
for(const t of C.teams)for(const m of t.members){
  if((m.eliteCompensation||[]).length)withC++;
  if((m.kit.personality||[]).includes(16046))inKit++;
}
const t2=C.teams.find(t=>t.members.some(m=>(m.eliteCompensation||[]).length));
const A=t2.members.map(m=>({name:m.name,stats:m.stats,move:m.move,prof:m.prof,profName:m.profName,
  kit:m.kit,skills:m.skills,edited:false,npcId:m.npcId}));
const B=mem(team(s0.team2Id));
const off=S.simulate({...opts,teams:{A,B}});
const on=S.simulate({...opts,teams:{A:A.map(m=>(m.kit.eliteComp||[]).length
  ?{...m,kit:{...m.kit,personality:[...(m.kit.personality||[]),...m.kit.eliteComp]}}:m),B}});
console.log(JSON.stringify({
 err:r.error||null,steps:r.steps.length,
 speedConversion:M.speedConversion,convertedSpecs:spdSpecs.length,
 negativeSpeedSpecs:spdSpecs.filter(([k,s])=>s.p[1]<0&&/强化|加速|速度\+/.test(s.n)).length,
 speedSample:spdSpecs.slice(0,4).map(([k,s])=>[k,s.n.slice(0,20),s.p[1]]),
 panelSpeed:{label:spdRow.label,value:spdRow.value,wt:spdRow.wt,
   parts:spdRow.parts.map(x=>({n:x.n.slice(0,24),flat:x.flat,displayFlat:x.displayFlat,wt:x.wt}))},
 ranking:ranked.slice(0,8),acting:acting.slice(0,8),orderOk,
 elite:{info:C.eliteCompensation,withC,inKit,has16046:!!M.skills['16046'],
   hpOff:off.units[0].maxHp,hpOn:on.units[0].maxHp},
 spawns:off.spawns,
}));
"""


def main():
    C = load('data/match-cup.js', 'WIKI_MATCH_CUP')
    M = load('data/battle-mech.js', 'WIKI_BATTLE_MECH')
    core = (ROOT / 'battle-sim-core.js').read_text('utf8')
    ui = (ROOT / 'battle-sim-ui.js').read_text('utf8')
    css = (ROOT / 'refinements.css').read_text('utf8')

    # ---- 1. speed ----
    conv = M.get('speedConversion', {})
    check('mech exporter converts WT deltas to speed deltas', conv.get('converted', 0) > 0, str(conv))
    check('cup note states higher speed acts first', '速度越大越先行动' in C.get('speedNote', '')
          and '+200' in C.get('speedNote', ''))
    check('engine sorts by descending speed', 'b.spd - a.spd' in core and 'a.wt - b.wt' not in core)
    check('no WT wording left in engine / panel', 'displayFlat' not in core and 'WT 行动等待' not in core
          and '越小越快' not in ui)
    check('Lua wait_time stays inverse of speed', "wait_time: 10000 / Math.max(1, attr(u, 'SPEED'))" in core)

    # ---- 2. map spawn picking ----
    check('spawn editor uses map-pick buttons', '[data-spawn-pick]' in ui and "data-spawn-pick=" in ui)
    check('no numeric coordinate inputs remain', 'data-spawn="${side}:${i}:x"' not in ui)
    check('board click handles pick mode', 'spawnPick = side === null' in ui or 'setSpawnPick' in ui)
    check('2D + 3D markers rendered', 'bsim-spawn-mark' in ui and 'bsim3-spawn' in ui)
    check('Esc cancels picking', "e.key === 'Escape' && spawnPick" in ui)
    check('marker CSS present', '.bsim-spawn-mark' in css and '.bsim3-spawn' in css)

    # ---- 3. left scrollbar ----
    check('left setup column scrolls independently',
          'max-height:calc(100dvh - 112px);overflow-y:auto' in css
          or ('max-height:calc(100dvh - 112px)' in css and 'overflow-y:auto' in css))
    check('left/right share scrollbar styling', '.bsim-setup::-webkit-scrollbar' in css)

    # ---- 4. elite compensation ----
    info = C.get('eliteCompensation', {})
    check('elite compensation source documented', info.get('skillId') == 16046
          and 'unit_personality_skill' in info.get('source', ''), str(info.get('source')))
    check('elite compensation effects listed', len(info.get('effects', [])) == 5, str(info.get('effects')))
    check('elite buff + evidence documented', '9686' in info.get('eliteBuff', '')
          and '192' in info.get('evidence', ''))
    check('default disabled', info.get('default') == 'disabled')
    check('UI exposes provenance + opt-in toggle', 'bsim-elite-note' in ui and 'bsim-elite-comp' in ui)
    check('cupMembers re-injects only when enabled', 'setup.eliteComp && m.kit.eliteComp' in ui)
    check('reference skill marked notApplied', 'notApplied' in ui and 'is-not-applied' in ui)

    # ---- engine ----
    out = subprocess.run([str(NODE), '-e', ENGINE], cwd=ROOT, capture_output=True, text=True,
                         encoding='utf8', timeout=600)
    try:
        e = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        e = {}
        print(out.stdout[-900:], out.stderr[-1200:])
    sp = e.get('panelSpeed', {})
    check('cup battle simulates', not e.get('err') and e.get('steps', 0) > 20)
    check('client -50/200 become positive speed bonuses',
          e.get('negativeSpeedSpecs', 1) == 0 and e.get('convertedSpecs', 0) > 0,
          str(e.get('speedSample')))
    check('panel speed plain label, positive delta, no WT',
          sp.get('label') == '速度' and not sp.get('wt') and
          all(x.get('flat', 0) > 0 and x.get('displayFlat') is None and not x.get('wt')
              for x in sp.get('parts', []) if x.get('flat')),
          str(sp))
    check('turn order follows speed ranking', e.get('orderOk') is True,
          f"rank={e.get('ranking')} acting={e.get('acting')}")
    el = e.get('elite', {})
    check('elite comp excluded from default kit', el.get('inKit') == 0 and el.get('withC', 0) > 100,
          str({k: el.get(k) for k in ('withC', 'inKit')}))
    check('elite comp still resolvable in mech data', el.get('has16046') is True)
    check('elite comp off/on changes max HP', el.get('hpOff') != el.get('hpOn'),
          f"{el.get('hpOff')} vs {el.get('hpOn')}")

    # ---- browser ----
    errors, failed = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(offline=True, viewport={'width': 1600, 'height': 1000}).new_page()
        page.set_default_timeout(30000)
        page.on('pageerror', lambda x: errors.append(str(x)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))
        page.goto(BASE + '#/tools/battle')
        page.locator('#bsim-board svg').wait_for()

        check('left column scrollable in browser',
              page.evaluate("""()=>{const e=document.querySelector('.bsim-setup');
                return getComputedStyle(e).overflowY==='auto' && e.scrollHeight>e.clientHeight}"""))
        page.evaluate("()=>{document.querySelector('.bsim-cup').open=true;}")
        page.wait_for_timeout(200)
        page.evaluate("()=>{document.querySelector('.bsim-elite-note').open=true;}")
        page.wait_for_timeout(150)
        note = page.locator('.bsim-elite-note').inner_text()
        check('elite provenance visible in UI',
              'unit_personality_skill' in note and '16046' in note and '9686' in note)
        check('elite compensation off by default', not page.locator('#bsim-elite-comp').is_checked())

        page.evaluate("()=>{document.querySelector('#bsim-spawn-edit').open=true;}")
        page.wait_for_timeout(200)
        check('14 map-pick buttons, no numeric inputs',
              page.locator('[data-spawn-pick]').count() == 14 and page.locator('[data-spawn$=":x"]').count() == 0)
        page.locator('[data-spawn-pick="A:0"]').click()
        page.wait_for_timeout(150)
        check('pick mode hint + board armed',
              page.locator('.bsim-pick-hint').count() == 1 and
              'is-spawn-picking' in (page.locator('#bsim-board').get_attribute('class') or ''))
        page.locator('.bsim-cell[data-x="9"][data-y="0"]').first.click()
        page.wait_for_timeout(500)
        coord = page.locator('.bsim-spawn-row').first.locator('.bsim-spawn-coord').inner_text()
        check('2D click sets coordinate', '(9, 0)' in coord and page.locator('.bsim-pick-hint').count() == 0, coord)
        check('2D spawn marker drawn', page.locator('.bsim-spawn-mark').count() >= 1)

        page.locator('[data-bsim-view="3d"]').click()
        page.wait_for_timeout(500)
        check('3D spawn marker drawn', page.locator('.bsim3-spawn').count() >= 1)
        page.locator('[data-spawn-pick="B:0"]').click()
        page.wait_for_timeout(150)
        # The 3D board is CSS-transformed, so a coordinate-based click can
        # land on a neighbouring diamond. Dispatch on the exact cell element
        # to test the event handler without the transform flakiness.
        page.locator('.world-iso-cell[data-x="15"][data-y="1"]').first.dispatch_event(
            'click', {'bubbles': True})
        page.wait_for_timeout(500)
        bcoord = page.locator('.bsim-spawn-rows').nth(1).locator('.bsim-spawn-coord').first.inner_text()
        check('3D click sets coordinate', '(15, 1)' in bcoord, bcoord)
        page.locator('[data-bsim-view="2d"]').click()
        page.wait_for_timeout(250)

        # speed panel
        page.locator('.bsim-unit[data-unit]').first.click()
        page.wait_for_timeout(250)
        speed = page.locator('.bsim-attr').filter(has_text='速度').first
        check('speed row has no WT wording', speed.count() == 1 and 'WT' not in speed.locator('summary').inner_text(),
              speed.locator('summary').inner_text()[:60])
        check('no WT anywhere on page', not page.evaluate("()=>document.body.innerText.includes('WT 行动等待')"))
        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
