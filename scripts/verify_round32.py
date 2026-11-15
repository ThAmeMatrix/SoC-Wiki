"""Round 32: interactive objects, acting summons, general client mechanisms
and the generated per-character mechanism reference.

    python -X utf8 scripts/verify_round32.py
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
const map=W.maps.find(m=>m.id===C.environment.mapId);
const mk=m=>({name:m.name,stats:m.stats,move:m.move,prof:m.prof,profName:m.profName,
  kit:m.kit,skills:m.skills,edited:false,npcId:m.npcId,star:m.star});
const team=id=>C.teams.find(t=>t.id===id);
const mem=t=>t.members.map(mk);
let ulia,filler,inanna;
for(const t of C.teams)for(const m of t.members){if(!ulia&&m.name.includes('乌莉娅'))ulia=m;if(!filler&&m.name.includes('柯瓦雷'))filler=m;}
const inannaR=D.roster.find(r=>r.name==='伊南娜');
const custom=n=>({name:n,key:n,stats:{hp:9000,patk:2500,matk:2500,pdef:1000,mdef:1000,spd:200},
  move:{mob:3,up:2,down:2,type:1},prof:6,profName:'',edited:false,
  skills:[{id:'atk',name:'普攻',usable:true,factor:100,rangeMin:0,rangeMax:1,shape:'diamond',
           aim:'enemy',area:{type:'single'},cooldown:0,order:1,hits:1,damageType:1}]});

// ---- 1. snowman objects ----
const f=mk(filler);
const r=S.simulate({data:D,mech:M,map,teams:{A:[mk(ulia),f,f,f],B:[f,f,f,f]},
  seed:7,maxRounds:12,substrate:SUB});
const snowStep=r.steps.find(s=>(s.placed||[]).some(o=>o.id===516));
const snow=snowStep?.placed.find(o=>o.id===516);
let ringOK=0,ringBad=0;
for(const s of r.steps){
  // Only traps SPAWNED BY THE SNOWMAN must be in its 1-ring; a honey placed
  // by 乌莉娅's own skill (蜜果大喷射 / 友军脚下) has no parent and is free
  // to be elsewhere.
  for(const o of s.placed||[])if((o.id===151||o.id===153)&&o.parent&&o.parent.id===516){
    if(Math.max(Math.abs(o.x-o.parent.x),Math.abs(o.y-o.parent.y))<=1)ringOK++;else ringBad++;}}
const PICKUP=/触发「[^」]+」（\d+）/;
const pickups=r.steps.flatMap(s=>s.events||[]).filter(e=>PICKUP.test(e)).length;
const parentLogs=r.steps.flatMap(s=>s.events||[]).filter(e=>/母体/.test(e)).length;
const removeLogs=r.steps.flatMap(s=>s.events||[]).filter(e=>/雪人」被移除|雪人」被摧毁/.test(e)).length;
// Every snowman removal must come from 乌莉娅's basic-attack chain, never a pickup.
const removalReasons=r.steps.map((s,i)=>({s,i})).filter(({s,i})=>i>0&&
  (r.steps[i-1].placed||[]).some(o=>o.id===516)&&!(s.placed||[]).some(o=>o.id===516))
  .map(({s})=>({basic:(s.events||[]).some(e=>/普攻-触发并移除雪人|雪人再造/.test(e)),
                pickup:(s.events||[]).some(e=>PICKUP.test(e))}));
// Pickup of a parent-linked trap must leave its snowman alive.
const pickupSteps=r.steps.filter(s=>(s.events||[]).some(e=>PICKUP.test(e)));
const aliveAtPickup=pickupSteps.map(s=>(s.placed||[]).some(o=>o.id===516));
// ---- 1b. concrete honey pickups with the snowman alive (all 192 schedules)
let honeyWithSnow=0, honeyDeadAtStep=0, honeyRemovedByPickup=0, honeyBasicAttack=0;
const HONEY=/触发「[^」]*蜜果[^」]*」（\d+）/;
for(const s of C.schedules){
  let q;try{q=S.simulate({data:D,mech:M,map,
    teams:{A:mem(team(s.team1Id)),B:mem(team(s.team2Id))},seed:1000+s.id,
    maxRounds:20,env:{weatherId:C.environment.weatherId,
      buffs:s.buffDetails.map(b=>({buffId:b.buffId,side:b.target===1?'A':b.target===2?'B':'both'}))},
    substrate:SUB});}catch(e){continue;}
  if(q.error)continue;
  for(let i=1;i<q.steps.length;i++){
    const prev=q.steps[i-1],cur=q.steps[i];
    if(!(cur.events||[]).some(e=>HONEY.test(e)))continue;
    const was=(prev.placed||[]).some(o=>o.id===516);
    const now=(cur.placed||[]).some(o=>o.id===516);
    if(!was)continue;
    honeyWithSnow++;
    const evs=cur.events||[];
    const basic=evs.some(e=>/普攻-触发并移除雪人|雪人再造/.test(e));
    if(basic)honeyBasicAttack++;
    if(!now)honeyDeadAtStep++;
    // Only a removal WITHOUT the client's basic-attack chain would be a bug.
    const removed=evs.some(e=>/雪人」被移除|雪人」被摧毁|雪人」被击破/.test(e));
    if(removed&&!basic)honeyRemovedByPickup++;
  }
}
// ---- 2. 伊南娜 summons ----
const r2=S.simulate({data:D,mech:M,map,
  teams:{A:[inannaR.name,custom('F1'),custom('F2'),custom('F3')],
         B:[custom('G1'),custom('G2'),custom('G3'),custom('G4')]},
  seed:7,maxRounds:8,substrate:SUB});
const summonActs=r2.steps.filter(s=>r2.summons?.some(u=>u.uid===s.actor));
const guard=r2.summons?.find(u=>u.name==='王女亲卫');
// ---- 3. ANY / timing-64 / Lua bindings ----
const core=fs.readFileSync('battle-sim-core.js','utf8');
// ---- determinism ----
const a=S.simulate({data:D,mech:M,map,teams:{A:[mk(ulia),f,f,f],B:[f,f,f,f]},seed:7,maxRounds:12,substrate:SUB});
const b=S.simulate({data:D,mech:M,map,teams:{A:[mk(ulia),f,f,f],B:[f,f,f,f]},seed:7,maxRounds:12,substrate:SUB});
const sig=x=>JSON.stringify(x.steps.map(s=>s.text+(s.events||[]).join('|')));
// ---- 40-match sweep ----
let done=0,err=0,exceptions=[];const skipped={},exec={},unknown={};
let summons=0,summonActions=0,allPickups=0,allRingOK=0,allRingBad=0;
for(const s of C.schedules.slice(0,40)){
  const buffs=s.buffDetails.map(b=>({buffId:b.buffId,side:b.target===1?'A':b.target===2?'B':'both'}));
  let q;try{q=S.simulate({data:D,mech:M,map,teams:{A:mem(team(s.team1Id)),B:mem(team(s.team2Id))},
    seed:1000+s.id,maxRounds:20,env:{weatherId:C.environment.weatherId,buffs},substrate:SUB});}
  catch(e){err++;exceptions.push(s.id+':'+e.message);continue;}
  if(q.error){err++;continue;}
  done++;summons+=q.summons?.length||0;
  summonActions+=q.steps.filter(x=>q.summons?.some(u=>u.uid===x.actor)).length;
  for(const st of q.steps){
    allPickups+=(st.events||[]).filter(e=>/触发「[^」]+」（\d+）/.test(e)).length;
    for(const o of st.placed||[])if((o.id===151||o.id===153)&&o.parent&&o.parent.id===516){
      if(Math.max(Math.abs(o.x-o.parent.x),Math.abs(o.y-o.parent.y))<=1)allRingOK++;else allRingBad++;}
  }
  for(const [k,v] of Object.entries(q.mechanics.skipped||{}))skipped[k]=(skipped[k]||0)+v;
  for(const [k,v] of Object.entries(q.mechanics.executed||{}))exec[k]=(exec[k]||0)+v;
  for(const [k,v] of Object.entries(q.mechanics.luaUnknown||{}))unknown[k]=(unknown[k]||0)+v;
}
console.log(JSON.stringify({
 err:r.error||null,steps:r.steps.length,
 objects:{snow,ringOK,ringBad,pickups,parentLogs,removeLogs,removalReasons,
   pickupSteps:pickupSteps.length,aliveAtPickup,
   honey:{withSnow:honeyWithSnow,deadAtStep:honeyDeadAtStep,basicAttack:honeyBasicAttack,
     removedByPickup:honeyRemovedByPickup}},
 summons:{err:r2.error||null,list:r2.summons,guard,acting:summonActs.length,
   sample:summonActs.slice(0,3).map(s=>({seq:s.seq,actor:s.actor,kind:s.kind})),
   templates:Object.keys(M.summons||{}).length},
 sweep:{done,err,exceptions:exceptions.slice(0,3),summons,summonActions,allPickups,allRingOK,allRingBad,
   skippedTotal:Object.values(skipped).reduce((x,y)=>x+y,0),
   topSkipped:Object.entries(skipped).sort((a,b)=>b[1]-a[1]).slice(0,6),
   selected:Object.fromEntries(['PLACE_ITEM','PLACE_TRAP','REMOVE_PROPS','TRIGGER_TRAP',
     'PLACE_UNIT(SUMMON)','PLACE_UNIT_INHERIT_ATTR'].map(k=>[k,exec[k]||0]))},
 deterministic:sig(a)===sig(b),
}));
"""


def main():
    M = load('data/battle-mech.js', 'WIKI_BATTLE_MECH')
    doc = load('data/character-mechanics.js', 'WIKI_CHARACTER_MECHANICS')
    core = (ROOT / 'battle-sim-core.js').read_text('utf8')
    ui = (ROOT / 'battle-sim-ui.js').read_text('utf8')
    mechui = (ROOT / 'mechanics-ui.js').read_text('utf8')
    perf = (ROOT / 'perf-core.js').read_text('utf8')

    # 1. object mechanics
    check('snowman definition still complete', M['props']['516']['n'] == '呆呆雪人'
          and len(M['props']['516']['sp']) >= 10)
    check('traps defined', M['traps']['151']['tt'] == 2 and M['traps']['153']['tt'] == 2)
    for key in ('ringCells', 'freeObjectCell', 'setObjectRing', 'sim.objectOrigin',
                'sim.randomCell', 'parent: ctx?.object'):
        check(f'object helper {key}', key in core)
    check('object spawns strictly in 1-ring', 'ringCells(origin, 1).filter(free)' in core
          and 'Object spawns NEVER widen past the declared ring' in core)
    check('RANDOM_BLOCK honours empty block condition', 'block.temp_trap == nil' in core)
    check('pickup never removes parent', '母体「${o.parent.name}」仍在' in core)
    check('REMOVE_PROPS requires explicit target', 'REMOVE_PROPS(无目标)' in core)
    check('friendly damage reduction uses p[2]', 's.p[2] ?? s.p[1]' in core)
    check('duplicate trap handlers removed',
          core.count('TRIGGER_TRAP(inst, ctx)') == 1 and core.count('CHANGE_TRAP(inst, ctx)') == 1)

    # 2. acting summons
    check('summon templates exported', len(M['summons']) >= 100, str(len(M['summons'])))
    guard = M['summons']['2959']
    check('王女亲卫 template has stats + kit', guard['n'] == '王女亲卫'
          and guard['stats']['hp'] > 5000 and str(guard['kit']['basic']) in M['skills'])
    for key in ('spawnUnitFrom', 'freeCellNear', 'sim.newUnits', 'drainSummons',
                'summons: summoned.map', 'PLACE_UNIT(SUMMON)'):
        check(f'summon engine {key}', key in core)
    check('ANY (active_time 1) skill effects fire', 'ANY specs on the skill itself' in core
          and 'UNIT_SPEC' in core)
    check('timing 64 fires on trap trigger', 'fire(64, u,' in core)
    check('summon count + cap', 'aliveSame >= 4' in core and 'summonCasts' in core)
    check('UI hides not-yet-spawned summons', 'snap.has(u.uid)' in ui)

    # 3. general mechanisms + docs
    for key in ('CLASS_TYPE: strict({NONE: 0, MELEE: 1', 'AITemplate', 'BehaviorDecision: () => true',
                'AT_ALIAS = {51: 28, 52: 27, 62: 2}', 'battle,',
                # Round 33: `block` is now a real per-cell proxy so
                # place_on_unit / active_time 64 Lua conditions can fire.
                'trapProxy', 'blockProxy(cell, c.blockTrap)'):
        check(f'client binding {key}', key in core)
    check('per-character doc generated', doc['meta']['characters'] >= 250,
          str(doc['meta']['characters']))
    check('doc covers 乌莉娅 objects', '交互物' in json.dumps(doc['characters']['乌莉娅']['categories'], ensure_ascii=False)
          and any('雪人' in x for x in doc['characters']['乌莉娅']['objects']))
    check('doc covers 伊南娜 summons', '召唤物' in json.dumps(doc['characters']['伊南娜']['categories'], ensure_ascii=False))
    check('doc lists 流星队 conversion', 'CONVERT_ATTRIBUTE' in doc['characters']['流星队']['effectTypes'])
    check('doc lists 阿列克谢·SP', '阿列克谢·SP' in doc['characters'])
    check('Markdown reference exists', (ROOT / 'docs' / 'character-mechanics.md').is_file()
          and (ROOT / 'docs' / 'character-mechanics.md').stat().st_size > 100000)
    check('doc page registered', "charmech: ['data/character-mechanics.js'" in perf
          and 'renderCharacters' in mechui and "#/character-mechanics" in (ROOT / 'app.js').read_text('utf8'))
    check('doc build in regenerate + package', 'build_character_mechanics.py' in
          (ROOT / 'scripts/socdecode/rebuild.py').read_text('utf8') and
          'character-mechanics.js' in (ROOT / 'scripts/package.py').read_text('utf8'))

    out = subprocess.run([str(NODE), '-e', ENGINE], cwd=ROOT, capture_output=True,
                         text=True, encoding='utf8', timeout=900)
    try:
        e = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        e = {}
        print(out.stdout[-1200:], out.stderr[-1500:])
    check('ulia battle simulates', not e.get('err') and e.get('steps', 0) > 20, str(e.get('err')))
    ob = e.get('objects', {})
    check('snowman spawns in 1-ring only', ob.get('ringBad') == 0 and ob.get('ringOK', 0) >= 3,
          f"ringOK={ob.get('ringOK')} ringBad={ob.get('ringBad')}")
    check('snowman still removed by basic attack', ob.get('removeLogs', 0) > 0,
          str(ob.get('removeLogs')))
    rr = ob.get('removalReasons') or []
    check('snowman only removed by 乌莉娅 basic attack', bool(rr)
          and all(x['basic'] and not x['pickup'] for x in rr), str(rr))
    honey = ob.get('honey', {})
    check('real honey pickups occur with snowman alive', honey.get('withSnow', 0) >= 3,
          str(honey))
    check('吃果后雪人不消失', honey.get('removedByPickup') == 0 and
          honey.get('deadAtStep', 0) == honey.get('basicAttack', 0), str(honey))
    su = e.get('summons', {})
    check('伊南娜 summons 王女亲卫', su.get('guard', {}).get('name') == '王女亲卫',
          str(su.get('list'))[:180])
    check('summon takes its own turns', su.get('acting', 0) >= 4, str(su.get('acting')))
    sw = e.get('sweep', {})
    check('40 cup matches clean', sw.get('done') == 40 and sw.get('err') == 0,
          str(sw.get('exceptions')))
    check('summons act at scale', sw.get('summons', 0) > 50 and sw.get('summonActions', 0) > 200,
          f"{sw.get('summons')} units / {sw.get('summonActions')} actions")
    check('all cup object spawns in 1-ring', sw.get('allRingBad') == 0 and sw.get('allRingOK', 0) > 30,
          f"ok={sw.get('allRingOK')} bad={sw.get('allRingBad')}")
    check('object effects fire at scale', sum(sw.get('selected', {}).values()) > 300,
          str(sw.get('selected')))
    check('deterministic', e.get('deterministic') is True)

    # browser
    errors, failed = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(offline=True, viewport={'width': 1600, 'height': 1000}).new_page()
        page.set_default_timeout(40000)
        page.on('pageerror', lambda x: errors.append(str(x)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))
        page.goto(BASE + '#/character-mechanics')
        page.locator('#cm-list .mechanics-entry').first.wait_for()
        check('doc page renders', page.locator('#cm-list .mechanics-entry').count() > 0)
        check('doc dataset loads', page.evaluate('()=>!!window.WIKI_CHARACTER_MECHANICS'))
        page.locator('#cm-query').fill('乌莉娅')
        page.wait_for_timeout(220)
        check('doc search works', page.locator('#cm-list .mechanics-entry').count() == 1
              and '乌莉娅' in page.locator('#cm-list').inner_text())
        page.locator('#cm-query').fill('')
        page.locator('#cm-kind').select_option('召唤物')
        page.wait_for_timeout(220)
        check('doc category filter works', page.locator('#cm-list .mechanics-entry').count() > 0)
        page.goto(BASE + '#/tools/battle')
        page.locator('#bsim-board svg').wait_for()
        page.evaluate("()=>{document.querySelector('.bsim-cup').open=true;}")
        sid = page.evaluate("""()=>{const C=window.WIKI_MATCH_CUP;
          const t=C.teams.find(t=>t.members.some(m=>m.name.includes('乌莉娅')));
          const s=C.schedules.find(s=>s.team1Id===t.id||s.team2Id===t.id);return String(s.id);}""")
        page.locator('#bsim-cup-sched').select_option(sid)
        page.locator('[data-cup-load="both"]').click()
        page.wait_for_timeout(1700)
        classes = set()
        last = int(page.locator('#bsim-range').get_attribute('max') or 0)
        for i in range(0, min(last, 24)):
            page.evaluate("(i)=>{const r=document.querySelector('#bsim-range');r.value=String(i);r.dispatchEvent(new Event('input',{bubbles:true}));}", i)
            page.wait_for_timeout(30)
            classes.update(page.evaluate("()=>[...document.querySelectorAll('.bsim-placed')].map(e=>e.getAttribute('class'))"))
        check('snowman / honey / ice drawn', any('is-snowman' in c for c in classes)
              and any('is-honey' in c for c in classes) and any('is-ice' in c for c in classes),
              str(sorted(classes)[:4]))
        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
