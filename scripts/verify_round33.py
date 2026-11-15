"""Round 33: initial facing, cast-block selection, place_on_unit pickup chains.

    python -X utf8 scripts/verify_round33.py
"""
import json
import subprocess
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / 'index.html').as_uri()
NODE = Path(r'C:\Users\thamechen\AppData\Local\Programs\Python\Python313\Lib\site-packages\playwright\driver\node.exe')
PLAN_FILE = Path('C:/Users/thamechen/Downloads/铃兰档案馆-站位方案-332-赛程90.json')
failures = []


def check(name, ok, detail=''):
    print(('PASS ' if ok else 'FAIL ') + name + (f' :: {detail}' if detail else ''), flush=True)
    if not ok:
        failures.append(name)


ENGINE = r"""
const fs=require('fs'),vm=require('vm');const ctx={window:{}};vm.createContext(ctx);
for(const f of ['data/world-data.js','data/battle-sim.js','data/match-cup.js','data/battle-mech.js',
                'data/client-mechanisms.js','battle-sim-core.js'])
  vm.runInContext(fs.readFileSync(f,'utf8'),ctx);
const W=ctx.window.WIKI_WORLD_DATA,D=ctx.window.WIKI_BATTLE_SIM,C=ctx.window.WIKI_MATCH_CUP,
      M=ctx.window.WIKI_BATTLE_MECH,SUB=ctx.window.WIKI_CLIENT_MECHANISMS,S=ctx.window.WikiBattleSim;
const plan=JSON.parse(fs.readFileSync('C:/Users/thamechen/Downloads/铃兰档案馆-站位方案-332-赛程90.json','utf8')).plans[0];
const sched=C.schedules.find(s=>s.id===plan.scheduleId);
const planMap=W.maps.find(m=>m.id===plan.mapId);
const env=W.maps.find(m=>m.id===C.environment.mapId);
const team=id=>C.teams.find(t=>t.id===id);
const mk=m=>({name:m.name,stats:m.stats,move:m.move,prof:m.prof,profName:m.profName,
  kit:m.kit,skills:m.skills,edited:false,npcId:m.npcId,star:m.star});
const mem=t=>t.members.map(mk);
let ulia,filler;
for(const t of C.teams)for(const m of t.members){if(!ulia&&m.name.includes('乌莉娅'))ulia=m;if(!filler&&m.name.includes('柯瓦雷'))filler=m;}
const inanna=D.roster.find(x=>x.name==='伊南娜');
const f=mk(filler);
const sim=(teamA,opts={})=>S.simulate(Object.assign({data:D,mech:M,map:env,
  teams:{A:[mk(teamA),f,f,f],B:[f,f,f,f]},seed:7,maxRounds:3,substrate:SUB},opts));

// ---- 1. facing controls object / summon spawn cells -----------------------
const facings={east:[1,0],west:[-1,0],south:[0,1],north:[0,-1]};
const facing={};
for(const [name,dir] of Object.entries(facings)){
  const o=sim(ulia,{spawns:{A:[{x:9,y:3,dir}],B:[]}});
  const snow=(o.steps[0].placed||[]).find(x=>x.id===516);
  const s=sim(inanna,{spawns:{A:[{x:9,y:3,dir}],B:[]}});
  const guard=(s.steps[0].snap||[]).find(x=>x.uid==='AS1');
  facing[name]={dir,snow:snow?[snow.x,snow.y]:null,guard:guard?[guard.x,guard.y]:null,
                initialDir:o.units.find(u=>u.uid==='A1')?.initialDir||null};
}

// ---- 2. the user's plan: first step must be (9,3) -> (12,3) ---------------
const r=S.simulate({data:D,mech:M,map:planMap,
  teams:{A:mem(team(sched.team1Id)),B:mem(team(sched.team2Id))},
  seed:20261107,maxRounds:4,env:{weatherId:C.environment.weatherId,
    buffs:sched.buffDetails.map(b=>({buffId:b.buffId,side:b.target===1?'A':b.target===2?'B':'both'}))},
  spawns:{A:plan.A,B:plan.B},substrate:SUB});
const st1=r.steps[1];
const cov=(st1.hits||[]).map(h=>h.uid);
const ev=st1.events||[];
const honeyPlaced=(st1.placed||[]); // final step snapshot (consumed traps are gone)
const placedHoney=ev.filter(e=>/在 \(\d+,\d+\) 放置「\[小羊女\|乌莉娅\]-蜜果」/.test(e)).length;
const pickup=ev.filter(e=>/停留触发「\[小羊女\|乌莉娅\]-蜜果」/.test(e)).length;
const energy=ev.filter(e=>/能量 \+1（能量补给）/.test(e)).length;
const cd=ev.filter(e=>/技能冷却 -1/.test(e)).length;
const buffs=ev.filter(e=>/获得「伤害2」|获得「速度2」/.test(e)).length;
const step1={from:st1.from,to:st1.to,skill:st1.skill?.name,target:st1.target,
  text:st1.text,covered:cov,placedHoney,pickup,energy,cd,buffs,
  mechanics:Object.fromEntries(['PLACE_TRAP','TRIGGER_TRAP','RECOVER_ATTRIBUTE','SKILL_CD']
    .map(k=>[k,r.mechanics.executed[k]||0])),skipped:r.mechanics.skipped||{},
  luaUnknown:r.mechanics.luaUnknown||{}};

// ---- 3. broad sweep / determinism -----------------------------------------
let done=0,err=0,exceptions=[],pickups=0,unknown={},skipped={};
for(const s of C.schedules.slice(0,40)){
  const buffs=s.buffDetails.map(b=>({buffId:b.buffId,side:b.target===1?'A':b.target===2?'B':'both'}));
  let q;try{q=S.simulate({data:D,mech:M,map:env,teams:{A:mem(team(s.team1Id)),B:mem(team(s.team2Id))},
    seed:1000+s.id,maxRounds:20,env:{weatherId:C.environment.weatherId,buffs},substrate:SUB});}
  catch(e){err++;exceptions.push(s.id+':'+e.message);continue;}
  if(q.error){err++;continue;}
  done++;
  for(const st of q.steps)for(const e of st.events||[])
    if(/停留触发「[^」]*蜜果|停留触发「碎冰/.test(e))pickups++;
  for(const [k,v] of Object.entries(q.mechanics.luaUnknown||{}))unknown[k]=(unknown[k]||0)+v;
  for(const [k,v] of Object.entries(q.mechanics.skipped||{}))skipped[k]=(skipped[k]||0)+v;
}
const a=S.simulate({data:D,mech:M,map:env,teams:{A:[mk(ulia),f,f,f],B:[f,f,f,f]},seed:7,maxRounds:20,substrate:SUB});
const b=S.simulate({data:D,mech:M,map:env,teams:{A:[mk(ulia),f,f,f],B:[f,f,f,f]},seed:7,maxRounds:20,substrate:SUB});
const sig=x=>JSON.stringify(x.steps.map(s=>s.text+(s.events||[]).join('|')));
console.log(JSON.stringify({facing,step1,
  sweep:{done,err,exceptions:exceptions.slice(0,3),pickups,
         unknown:Object.entries(unknown).sort((x,y)=>y[1]-x[1]).slice(0,5),
         topSkipped:Object.entries(skipped).sort((x,y)=>y[1]-x[1]).slice(0,5)},
  deterministic:sig(a)===sig(b)}));
"""


def main():
    core = (ROOT / 'battle-sim-core.js').read_text('utf8')
    ui = (ROOT / 'battle-sim-ui.js').read_text('utf8')
    M = json.loads((ROOT / 'data/battle-mech.js').read_text('utf8').split('=', 1)[1].strip().rstrip(';'))

    # 1. facing
    for key in ('function parseFacing', 'out.facing = {A: [], B: []}', 'initialDir:',
                'freeCellNear = (u, radius, front)', 'NOT_TURN_AROUND', 'spawns.facing?.[side]?.[i]'):
        check(f'engine facing {key}', key in core)
    for key in ('FACINGS = [', 'facingKey', 'data-spawn-dir', 'planCell', 'bsim-facing-arrow',
                'bsim-unit-facing', "version: 2", 'dirOf(c)'):
        check(f'UI facing {key}', key in ui)
    check('plan validation is map-local', 'const info = (D.terrain || {})[String(cell[3])]' in ui
          and 'const raw = planMap(mapId)?.raw' in ui)
    check('facing-only entries survive I/O', 'if (c.x === undefined && c.y === undefined) return true' in ui)

    # 2/3. mechanisms
    for key in ('trapProxy', 'blockProxy(cell, c.blockTrap)', 'place_on_unit/.test(sp)',
                'triggerObject(made, t, sub)', 'fire(64, u,', 'blockTrap: o',
                'perBlock', 'placeOnUnit', 'getAoePositions', 'sortValue'):
        check(f'engine mechanism {key}', key in core)
    check('honey trap 153 data', M['traps']['153']['ts'] == 19218 and M['traps']['153']['lim'] == 1)
    check('place_on_unit spec 27174', 'place_on_unit' in (M['specs']['27174'].get('s') or ''))
    check('energy supply passive at=64', M['specs']['27092']['at'] == 64
          and M['specs']['27092']['t'] == 'RECOVER_ATTRIBUTE')
    check('skill 19219 has follow 19234', M['skills']['19219']['fl'] == 19234)

    out = subprocess.run([str(NODE), '-e', ENGINE], cwd=ROOT, capture_output=True,
                         text=True, encoding='utf8', timeout=900)
    try:
        e = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        e = {}
        print(out.stdout[-1200:], out.stderr[-1500:])

    fa = e.get('facing', {})
    ok = True
    for name, d in fa.items():
        vec = d.get('dir') or []
        want = [9 + vec[0], 3 + vec[1]]
        if d.get('snow') != want or d.get('guard') != want: ok = False
        check(f'facing {name} front spawn', d.get('snow') == want and d.get('guard') == want,
              f"want {want}, snow={d.get('snow')} guard={d.get('guard')}")
    check('initialDir recorded', all(fa.get(k, {}).get('initialDir') for k in fa))
    check('four facings tested', len(fa) == 4)

    s1 = e.get('step1', {})
    check('user plan first step (9,3) -> (12,3)', s1.get('from') == {'x': 9, 'y': 3}
          and s1.get('to') == {'x': 12, 'y': 3}, str(s1.get('to')))
    check('first step casts 天降蜜果啦！', s1.get('skill') == '天降蜜果啦！', str(s1.get('skill')))
    check('AOE covers 4 incl B1 安娜', set(s1.get('covered', [])) == {'B1', 'B2', 'B3', 'B5'},
          str(s1.get('covered')))
    check('honey under each friendly', s1.get('placedHoney', 0) >= 4, str(s1.get('placedHoney')))
    check('immediate pickup on placement', s1.get('pickup', 0) >= 4, str(s1.get('pickup')))
    check('能量补给 +1 TP fires', s1.get('energy', 0) >= 1, str(s1.get('energy')))
    check('pickup reduces skill CD', s1.get('cd', 0) >= 1, str(s1.get('cd')))
    check('support buffs applied', s1.get('buffs', 0) >= 2, str(s1.get('buffs')))
    check('no skipped effects in user case', s1.get('skipped') == {}, str(s1.get('skipped')))
    check('no Lua unknowns in user case', s1.get('luaUnknown') == {}, str(s1.get('luaUnknown')))

    sw = e.get('sweep', {})
    check('40 cup matches clean', sw.get('done') == 40 and sw.get('err') == 0,
          str(sw.get('exceptions')))
    check('pickups fire at scale', sw.get('pickups', 0) > 50, str(sw.get('pickups')))
    check('no Lua unknowns at scale', not sw.get('unknown'), str(sw.get('unknown')))
    # Round 36: 连锁触发过深 is the client's own buff-loop re-entrancy guard
    # (decrypted AIMachine chain cap), not an unimplemented effect.
    check('skipped effects minimal',
          sum(v for k, v in dict(sw.get('topSkipped', [])).items()
              if not k.startswith('BUFF#') and k != '连锁触发过深') == 0,
          str(sw.get('topSkipped')))
    check('deterministic', e.get('deterministic') is True)

    # browser
    errors, failed = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(offline=True, viewport={'width': 1600, 'height': 1000},
                                  accept_downloads=True)
        page = ctx.new_page()
        page.set_default_timeout(40000)
        page.on('pageerror', lambda x: errors.append(str(x)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))
        page.goto(BASE + '#/tools/battle')
        page.locator('#bsim-board svg').wait_for()
        page.evaluate("()=>{document.querySelector('.bsim-cup').open=true;}")
        page.evaluate("()=>{document.querySelector('#bsim-spawn-edit').open=true;}")
        page.wait_for_timeout(250)
        check('facing selects rendered', page.locator('.bsim-spawn-dir').count() >= 8)
        page.locator('[data-spawn-dir="A:0"]').select_option('0,1')
        page.wait_for_timeout(650)
        check('facing select persists', page.locator('[data-spawn-dir="A:0"]').input_value() == '0,1')
        check('unit facing arrows drawn', page.locator('.bsim-unit-facing').count() > 0)
        with page.expect_download() as dl:
            page.locator('[data-plan="export"]').click()
        tmp = ROOT / 'work_r33_verify_plan.json'
        dl.value.save_as(str(tmp))
        doc = json.loads(tmp.read_text('utf8'))
        check('plan version 2 + dir exported', doc.get('version') == 2
              and any((c or {}).get('dir') == [0, 1] for c in doc['plans'][0]['A']),
              str([c for c in doc['plans'][0]['A'][:1]]))
        page.locator('[data-spawn-clear]').click()
        page.wait_for_timeout(450)
        page.locator('#bsim-plan-file').set_input_files(str(tmp))
        page.wait_for_timeout(600)
        check('plan re-import restores facing',
              page.locator('[data-spawn-dir="A:0"]').input_value() == '0,1')
        if PLAN_FILE.exists():
            page.locator('#bsim-plan-file').set_input_files(str(PLAN_FILE))
            page.wait_for_timeout(700)
            check('user plan imports', '已导入' in page.locator('#bsim-plan-msg').inner_text(),
                  page.locator('#bsim-plan-msg').inner_text())
        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        tmp.unlink(missing_ok=True)
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
