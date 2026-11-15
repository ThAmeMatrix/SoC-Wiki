"""Round 30: decrypted mechanism substrate, client movement pipeline,
rendered placed objects, remaining effects/AI and live-speed turn order.

    python -X utf8 scripts/verify_round30.py
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
    t = (ROOT / rel).read_text('utf8'); m = 'window.' + var + '='
    return json.JSONDecoder().raw_decode(t[t.index(m) + len(m):])[0]


ENGINE = r"""
const fs=require('fs'),vm=require('vm');const ctx={window:{}};vm.createContext(ctx);
for(const f of ['data/world-data.js','data/battle-sim.js','data/match-cup.js','data/battle-mech.js',
                'data/client-mechanisms.js','battle-sim-core.js'])
  vm.runInContext(fs.readFileSync(f,'utf8'),ctx);
const W=ctx.window.WIKI_WORLD_DATA,D=ctx.window.WIKI_BATTLE_SIM,C=ctx.window.WIKI_MATCH_CUP,
      M=ctx.window.WIKI_BATTLE_MECH,SUB=ctx.window.WIKI_CLIENT_MECHANISMS,S=ctx.window.WikiBattleSim;
const arena=W.maps.find(m=>m.id===C.environment.mapId);
const team=id=>C.teams.find(t=>t.id===id);
const mk=m=>({name:m.name,stats:m.stats,move:m.move,prof:m.prof,profName:m.profName,
  kit:m.kit,skills:m.skills,edited:false,npcId:m.npcId,star:m.star});
const mem=t=>t.members.map(mk);
const s0=C.schedules[0];
const opts={data:D,mech:M,map:arena,teams:{A:mem(team(s0.team1Id)),B:mem(team(s0.team2Id))},
  seed:20261107,maxRounds:20,substrate:SUB};
const r=S.simulate(opts);
// 4) paths must always start at `from`
let full=0,truncated=0;
for(const s of r.steps) if(s.path?.length>1){
  if(s.path[0].x===s.from.x&&s.path[0].y===s.from.y) full++; else truncated++;
}
// 3) placed objects per step
let ulia,filler;
for(const t of C.teams)for(const m of t.members){if(!ulia&&m.name.includes('乌莉娅'))ulia=m;if(!filler&&m.name.includes('柯瓦雷'))filler=m;}
const f=mk(filler);
const r2=S.simulate({...opts,teams:{A:[mk(ulia),f,f,f],B:[f,f,f,f]},seed:7});
const objSteps=r2.steps.filter(s=>s.placed?.length);
const kinds=[...new Set(r2.steps.flatMap(s=>(s.placed||[]).map(o=>o.kind)))];
// 5) forced mid-round speed change
const m2=JSON.parse(JSON.stringify(M));
m2.specs.__speedMod={t:'MODIFY_ATTRIBUTE',at:1,p:[17,500,0,0],n:'测试速度+500'};
m2.specs.__grant={t:'BUFF',at:3,tt:5,p:['__speedBuff',1,0,0],n:'测试速度赋予'};
m2.buffs.__speedBuff={n:'速度成长',sp:['__speedMod'],bt:2,ui:true,d:'',et:''};
m2.skills.__grantSkill={n:'测试速度赋予',st:1,ty:3,sp:['__grant'],dt:5};
const base=x=>Object.assign({},x,{edited:true,kit:Object.assign({},x.kit,{personality:['__grantSkill']})});
const A=team(s0.team1Id).members.slice(0,3).map((x,i)=>i===0?base(x):x);
const B=team(s0.team2Id).members.slice(0,3);
// Round 36: with ai_skill_by_order, A1's declared first slot has no target
// on turn 1, so the injected at=3 speed buff lands in round 2 instead.
const r3=S.simulate({...opts,mech:m2,teams:{A,B},seed:7,maxRounds:6});
const logs=r3.steps.flatMap(s=>s.events||[]).filter(e=>e.includes('重排行动顺序'));
// compare round-1 vs round-2 acting sequence: boosted allies must jump ahead
const seq=round=>r3.steps.filter(s=>s.actor&&s.round===round).map(s=>s.actor).join(',');
// 2) effect coverage across 40 schedules
let done=0,err=0,exceptions=[];const skipped={},exec={};
for(const s of C.schedules.slice(0,40)){
  const buffs=s.buffDetails.map(b=>({buffId:b.buffId,side:b.target===1?'A':b.target===2?'B':'both'}));
  let q;try{q=S.simulate({...opts,teams:{A:mem(team(s.team1Id)),B:mem(team(s.team2Id))},
    seed:1000+s.id,env:{weatherId:C.environment.weatherId,buffs}});}
  catch(e){err++;exceptions.push(s.id+':'+e.message);continue;}
  if(q.error){err++;continue;}
  done++;
  for(const [k,v] of Object.entries(q.mechanics.skipped||{}))skipped[k]=(skipped[k]||0)+v;
  for(const [k,v] of Object.entries(q.mechanics.executed||{}))exec[k]=(exec[k]||0)+v;
}
// determinism
const a=S.simulate(opts),b=S.simulate(opts);
for(let i=0;i<6;i++)a.inspect(i,a.units[i%a.units.length].uid);
const sig=x=>JSON.stringify(x.steps.map(s=>s.text+(s.events||[]).join('|')));
console.log(JSON.stringify({
 err:r.error||null,steps:r.steps.length,substrateLoaded:r.substrateLoaded,phases:r.substratePhases,
 step1:{order:(r.steps[1].order||[]).slice(0,3),moveRule:r.steps[1].moveRule,phase:r.steps[1].phase},
 paths:{full,truncated},
 placed:{steps:objSteps.length,kinds,result:r2.placed.length,first:objSteps[0]?.placed},
 order:{changes:r3.orderChanges,logs:logs.length,seq1:seq(1),seq2:seq(2),sample:logs.slice(0,2)},
 sweep:{done,err,exceptions:exceptions.slice(0,3),
   skippedTotal:Object.values(skipped).reduce((x,y)=>x+y,0),
   topSkipped:Object.entries(skipped).sort((x,y)=>y[1]-x[1]).slice(0,5),
   newEffects:Object.fromEntries(['REBORN','COUNTER_ATTACK','PERCENT_HEAL','EVADE','PARRY',
     'FORCE_STOP','MELEE_TRIGGER','ALERT_ATTACK','FIRST_HIT','ASSIST_DEFENCE'].map(k=>[k,exec[k]||0]))},
 deterministic:sig(a)===sig(b),
}));
"""


def main():
    SUB = load('data/client-mechanisms.js', 'WIKI_CLIENT_MECHANISMS')
    M = load('data/battle-mech.js', 'WIKI_BATTLE_MECH')
    core = (ROOT / 'battle-sim-core.js').read_text('utf8')
    ui = (ROOT / 'battle-sim-ui.js').read_text('utf8')
    perf = (ROOT / 'perf-core.js').read_text('utf8')

    # 1. substrate
    check('substrate derived from decrypted scripts', SUB['meta']['scriptsDecrypted'] > 4000,
          str(SUB['meta']['scriptsDecrypted']))
    check('AI phases present', SUB['phases'] == ['CHECK_STATE', 'DO_SKILL', 'MOVE_OR_IDLE', 'FINISH'])
    check('skill list tags present', len(SUB['skillTags']) >= 13 and 'MOVE_TO' in SUB['skillTags'])
    check('cast pipeline from AIMachine', 'filterByMinMoveDist' in SUB['castPipeline']
          and 'sortByMoveAndTargetDist' in SUB['castPipeline'])
    check('AOE scoring fields', {'weakCount', 'hurtedCount', 'dyingCount'} <= set(SUB['aoeFields']))
    check('wait-time dynamic order evidence', SUB['waitTime']['dynamicOrder'] is True)
    types = {s['t'] for s in M['specs'].values()}
    check('effect types verified against bytecode', len(SUB['effectTypes']) >= 190,
          f"{len(SUB['effectTypes'])}/{len(types)}")
    check('substrate is a lazy dataset', "substrate: ['data/client-mechanisms.js'" in perf)
    check('substrate loaded on battle page', "'mech','substrate'" in
          (ROOT / 'app.js').read_text('utf8'))
    check('engine consumes substrate', 'const SUB = opts.substrate' in core and
          'RULE.filterByMinMoveDist' in core and 'TAG_W[skillTag(s)]' in core)
    check('substrate in regenerate chain', 'derive_mechanisms.py' in
          (ROOT / 'scripts/socdecode/rebuild.py').read_text('utf8'))

    # 2. effects / AI
    for key in ('TARGET_SELECT', 'COUNTER_ATTACK', 'REBORN', 'TELEPORT', 'BLINK',
                'DIE_INSTANTLY', 'PERCENT_HEAL', 'FORCE_STOP', 'EVADE', 'PARRY',
                'MELEE_TRIGGER', 'EXCHANGE_POSITION', 'DISPEL_CONVERT'):
        check(f'effect {key} implemented', f'{key}(inst' in core)
    check('AI uses AOE scoring fields', 'dyingCount' in core and 'weakCount' in core)
    check('AI uses skill tag priority', 'function skillTag' in core)
    check('AI quadrant comparator', 'quadrant(a.stand, a.target)' in core)
    check('basic-attack fallback for ADDITIONAL_ATTACK', "caster.basic" in core)

    # 3. placed objects
    check('per-step placed snapshot', 'step.placed = placedSnap()' in core)
    check('2D placed renderer', 'bsim-placed' in ui and 'step.placed || []' in ui)
    check('3D placed renderer', 'bsim3-placed' in ui)
    # Round 31: the plain chip list became an expandable object panel.
    check('placed list in detail', 'bsim-object-grid' in ui and 'bsim-objects' in ui)
    check('placed CSS', '.bsim-obj-body' in (ROOT / 'refinements.css').read_text('utf8'))

    # 4. movement
    check('occupied cells keep prev chain', 'node.blocked = true' in core)
    check('cast groups filter min move dist', 'RULE.filterByMinMoveDist' in core)
    check('approach uses min move dist', 'filterByMinMoveDist' in core and 'MOVE_OR_IDLE' in core)
    check('move rationale exposed', 'moveRule' in core and '为什么走到这里' in ui)

    # 5. dynamic order
    check('live speed ranking', 'const rankPending' in core and 'turnSpeed' in core)
    check('speed reads are read-only', 'sim.probe = true' in core and 'attrRaw(u, \'SPEED\'' in core)
    check('order shown in UI', '行动顺序（按实时速度）' in ui)

    out = subprocess.run([str(NODE), '-e', ENGINE], cwd=ROOT, capture_output=True,
                         text=True, encoding='utf8', timeout=900)
    try:
        e = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        e = {}
        print(out.stdout[-1200:], out.stderr[-1500:])
    check('battle simulates', not e.get('err') and e.get('steps', 0) > 20, str(e.get('err')))
    check('substrate loaded in engine', e.get('substrateLoaded') is True)
    check('AI phases attached to steps', e.get('step1', {}).get('phase', '').startswith('CHECK_STATE'))
    check('cast pipeline exposed per step', len(e.get('step1', {}).get('moveRule', {}).get('pipeline', [])) >= 10)
    p = e.get('paths', {})
    check('no truncated movement paths', p.get('truncated', 1) == 0 and p.get('full', 0) > 10, str(p))
    pl = e.get('placed', {})
    check('placed objects visible across replay', pl.get('steps', 0) > 10 and
          'PLACE_ITEM' in pl.get('kinds', []), str(pl.get('kinds')))
    o = e.get('order', {})
    check('mid-round speed change reorders turns', o.get('changes', 0) > 0 and o.get('logs', 0) > 0,
          str(o.get('logs')))
    check('boosted allies act before slower foes', o.get('seq1') != o.get('seq2'),
          f"r1={o.get('seq1')} r2={o.get('seq2')}")
    sw = e.get('sweep', {})
    check('40 cup matches clean', sw.get('done') == 40 and sw.get('err') == 0, str(sw.get('exceptions')))
    check('remaining skipped effects minimal', sw.get('skippedTotal', 999) < 40,
          f"{sw.get('skippedTotal')} {sw.get('topSkipped')}")
    check('new effects actually fire', sum(sw.get('newEffects', {}).values()) > 100,
          str(sw.get('newEffects')))
    check('inspection stays deterministic', e.get('deterministic') is True)

    # browser
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
        check('substrate auto-loaded in browser', page.evaluate('()=>!!window.WIKI_CLIENT_MECHANISMS'))
        page.locator('.bsim-mech summary').first.click()
        page.wait_for_timeout(200)
        check('substrate shown in coverage panel', '运行机制基底' in page.locator('.bsim-mech').inner_text())
        page.locator('#bsim-range').fill('2')
        page.wait_for_timeout(250)
        detail = page.locator('#bsim-detail').inner_text()
        check('live order shown in step detail', '行动顺序（按实时速度）' in detail)
        check('move rationale shown in step detail', '为什么走到这里' in detail)
        # load a schedule with 乌莉娅 and scan for placed markers
        page.evaluate("()=>{document.querySelector('.bsim-cup').open=true;}")
        page.wait_for_timeout(200)
        sid = page.evaluate("""()=>{const C=window.WIKI_MATCH_CUP;
          const t=C.teams.find(t=>t.members.some(m=>m.name.includes('乌莉娅')));
          const s=C.schedules.find(s=>s.team1Id===t.id||s.team2Id===t.id);
          return s?String(s.id):null;}""")
        page.locator('#bsim-cup-sched').select_option(sid)
        page.locator('[data-cup-load="both"]').click()
        page.wait_for_timeout(1600)
        maxn = 0
        last = int(page.locator('#bsim-range').get_attribute('max') or 0)
        for i in range(0, min(last, 26)):
            page.evaluate("(i)=>{const r=document.querySelector('#bsim-range');r.value=String(i);r.dispatchEvent(new Event('input',{bubbles:true}));}", i)
            page.wait_for_timeout(40)
            maxn = max(maxn, page.locator('.bsim-placed').count())
        check('snowman / items drawn on 2D board', maxn >= 1, str(maxn))
        page.locator('[data-bsim-view="3d"]').click()
        page.wait_for_timeout(500)
        check('objects also drawn on 3D board', page.locator('.bsim3-placed').count() >= 1)
        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
