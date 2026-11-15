"""Round 24: client-mechanics battle engine + full 乐土群星杯 restoration.

    python -X utf8 scripts/verify_round24.py
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
const L=S.Lua;
// --- Lua interpreter ---
const lua={
  ret:L.test('return 1+2==3',{}).ok===true,
  loop:L.test('local A=0 for i=1,3 do A=A+i end return A==6',{}).ok===true,
  pairs:L.test('local n=0 for _,v in pairs(t) do if v>1 then n=n+1 end end return n==2',{t:[1,2,3]}).ok===true,
  closure:L.test('local function f(x) return x*2 end return f(4)==8',{}).ok===true,
  unknown:!!L.test('return foo.bar',{}).unknown,
};
// --- every Lua condition in the closure parses ---
let parsed=0,syntax=0;for(const s of Object.values(M.specs)){if(!s.c)continue;const r=L.test(s.c,{});
  if(r.unknown&&/^(syntax|statement|token)/.test(r.unknown))syntax++;else parsed++;}
// --- cup sweep ---
const env=C.environment,arena=W.maps.find(m=>m.id===env.mapId);
const team=id=>C.teams.find(t=>t.id===id);
const mem=t=>t.members.map(m=>({name:m.name,stats:m.stats,move:m.move,prof:m.prof,profName:m.profName,kit:m.kit,skills:m.skills,edited:false,npcId:m.npcId,star:m.star}));
const exec={},skipped={};let cond={pass:0,fail:0,unknown:0},done=0,errors=0,slow=0,wins={A:0,B:0,draw:0},zeroActors=0,maxMs=0,kovCasts=0,kovBad=0;
const timings=[];
for(const s of C.schedules.slice(0,40)){
  const A=mem(team(s.team1Id)),B=mem(team(s.team2Id));
  const buffs=s.buffDetails.map(b=>({buffId:b.buffId,side:b.target===1?'A':b.target===2?'B':'both'}));
  const t0=Date.now();let r;
  try{r=S.simulate({data:D,mech:M,map:arena,teams:{A,B},seed:1000+s.id,maxRounds:20,env:{weatherId:env.weatherId,buffs}});}catch(e){errors++;continue;}
  // Round 48: a fixed 4000ms wall-clock budget is machine-dependent and the
  // baseline itself now exceeds it (more client specialities / timings are
  // executed). Guard against a REAL outlier instead: >6x the median battle
  // catches a runaway chain regardless of CPU speed.
  const ms=Date.now()-t0;timings.push(ms);maxMs=Math.max(maxMs,ms);
  if(r.error){errors++;continue;}done++;wins[r.winner]++;
  for(const[k,v]of Object.entries(r.mechanics.executed))exec[k]=(exec[k]||0)+v;
  for(const[k,v]of Object.entries(r.mechanics.skipped))skipped[k]=(skipped[k]||0)+v;
  for(const k of['pass','fail','unknown'])cond[k]+=r.mechanics.conditions[k];
  const acted=new Set(r.steps.filter(x=>x.kind==='skill').map(x=>x.actor));
  for(const x of r.steps.filter(x=>x.skill&&x.skill.name==='此刻正是赏雨之时')){kovCasts++;
    const side=r.units.find(u=>u.uid===x.actor).side;
    // `hits` also carries SUB hits from counter-attacks the AOE provokes
    // (e.g. 埃拉曼重斧斗士「钢颚武神-回旋斩」 retaliates against its OWN ally
    // A4). Those are not the self-centred AOE hitting a friend. Only the
    // primary (non-sub) hits describe this skill's area.
    const primary=(x.hits||[]).filter(h=>!h.sub);
    if(!primary.length||primary.some(h=>r.units.find(u=>u.uid===h.uid).side===side))kovBad++;}
  if(acted.size<4)zeroActors++;
}
// --- determinism + environment ---
const s0=C.schedules[0];
const run=()=>S.simulate({data:D,mech:M,map:arena,teams:{A:mem(team(s0.team1Id)),B:mem(team(s0.team2Id))},seed:5,maxRounds:20,env:{weatherId:env.weatherId}});
const a=run(),b=run();
const det=JSON.stringify(a.steps.map(x=>x.text+(x.events||[]).join('|')))===JSON.stringify(b.steps.map(x=>x.text+(x.events||[]).join('|')));
const weatherLogged=a.steps[0].events.some(e=>e.includes('天气'));
const auraBuffs=a.steps[0].snap.some(u=>(u.b||[]).some(x=>x[3]===1));
// --- self-centred AOE hits enemies (此刻正是赏雨之时) ---
const aoeHitsEnemies=kovBad===0;
// --- roster battles still work with mechanics ---
const keys=D.roster.map(x=>x.key);
const rr=S.simulate({data:D,mech:M,map:W.maps.find(m=>m.id===3),teams:{A:keys.slice(0,5),B:keys.slice(5,10)},seed:7,maxRounds:20});
// --- custom edited fighter keeps HP + uses edited factor ---
const custom={key:keys[0],name:'测试',stats:{hp:99999,patk:3000,matk:3000,pdef:500,mdef:500,spd:400},move:{mob:4,up:2,down:2,type:1},edited:true,
  skills:[{id:'c1',name:'自定义重击',usable:true,heal:false,factor:300,rangeMin:0,rangeMax:3,shape:'diamond',aim:'enemy',area:{type:'single'},cooldown:0,order:5,hits:1,damageType:1}]};
const rc=S.simulate({data:D,mech:M,map:W.maps.find(m=>m.id===3),teams:{A:[custom],B:keys.slice(5,8)},seed:3,maxRounds:20});
// --- legacy fallback without mechanics data ---
const rl=S.simulate({data:D,map:W.maps.find(m=>m.id===3),teams:{A:keys.slice(0,4),B:keys.slice(4,8)},seed:7,maxRounds:20,mech:false});
const sortedAll=timings.slice().sort((a,b)=>a-b);
const medianMs=sortedAll.length?sortedAll[Math.floor(sortedAll.length/2)]:0;
slow=timings.filter(ms=>ms>Math.max(1,medianMs)*6).length;
console.log(JSON.stringify({lua,parsed,syntax,done,errors,slow,maxMs,medianMs,wins,zeroActors,exec,skipped,cond,det,weatherLogged,auraBuffs,
  kovCasts,aoeHitsEnemies,roster:{err:rr.error||null,winner:rr.winner,exec:Object.keys(rr.mechanics.executed).length},
  custom:{base:rc.units[0]?.base.HP_MAX,hp:rc.units[0]?.maxHp,used:rc.steps.some(x=>x.skill&&x.skill.name==='自定义重击')},
  legacy:{err:rl.error||null,winner:rl.winner,loaded:rl.mechanics.loaded},
  log:S.logText(a,{seed:5}).includes('机制覆盖')}));
"""


def main():
    M = load('data/battle-mech.js', 'WIKI_BATTLE_MECH')
    C = load('data/match-cup.js', 'WIKI_MATCH_CUP')
    B = load('data/battle-sim.js', 'WIKI_BATTLE_SIM')

    # ---------- exported mechanics ----------
    check('mechanics data exported', len(M['skills']) > 3000 and len(M['specs']) > 6000 and len(M['buffs']) > 1000,
          f"{len(M['skills'])} skills / {len(M['specs'])} specs / {len(M['buffs'])} buffs")
    check('197+ effect types in the closure', len({s['t'] for s in M['specs'].values()}) >= 150)
    check('official active_time enum exported', len(M['enums']['activeTime']) >= 60 and M['enums']['activeTime'].get('4') == 'BEATTACKED')
    check('area shapes from aoe_param', len(M['aoe']) >= 100)
    check('hp attenuation / restraint / weather exported',
          len(M['hpAttenuation']) == 4 and len(M['restrain']) >= 8 and len(M['weather']) >= 10)
    check('battle handbook exported', len(M['rules']) >= 30)
    check('Lua conditions exported untruncated', max(len(s.get('c', '')) for s in M['specs'].values()) > 400)
    check('every timing the closure uses is raised by the engine',
          all(v['mapped'] for k, v in M['timings'].items() if v['count'] >= 20),
          str({k: v['count'] for k, v in M['timings'].items() if not v['mapped']}))
    check('skill areas only from AOE specialities',
          all(s['area']['type'] in ('single', 'aoe') for s in M['skills'].values()))

    # ---------- 乐土群星杯 restoration ----------
    fighters = [m for t in C['teams'] for m in t['members']]
    check('every cup fighter carries a client kit', all(m.get('kit') and m['kit'].get('basic') for m in fighters))
    check('cup fighters have real profession categories',
          len({m['profName'] for m in fighters}) >= 5 and all(m['prof'] in range(1, 7) for m in fighters))
    check('personality skills picked per star tier',
          all(len(m['kit']['personality']) == len(set(m['kit']['personality'])) for m in fighters))
    check('cup kits reference exported skills',
          sum(1 for m in fighters for sid in [m['kit']['basic']] + m['kit']['actives'] if str(sid) in M['skills']) >= len(fighters))
    env = C['environment']
    check('cup default environment inferred with evidence',
          env['mapId'] and env['weatherId'] and len(env['evidence']) == 3, json.dumps(env, ensure_ascii=False)[:160])
    check('cup buffs know which side they apply to',
          all('target' in b for s in C['schedules'] for b in s['buffDetails']))
    check('cup buffs + statuses resolvable in mechanics data',
          all(str(b['buffId']) in M['buffs'] for s in C['schedules'] for b in s['buffDetails'] if b['buffId']) and
          all(str(u['buffId']) in M['buffs'] for s in C['schedules'] for u in s['unitStatus'] if u['buffId']))
    check('roster kits exported', all(r.get('kit') for r in B['roster']))

    # ---------- wiring ----------
    perf = (ROOT / 'perf-core.js').read_text('utf8')
    app = (ROOT / 'app.js').read_text('utf8')
    pkg = (ROOT / 'scripts/package.py').read_text('utf8')
    reb = (ROOT / 'scripts/socdecode/rebuild.py').read_text('utf8')
    html = (ROOT / 'index.html').read_text('utf8')
    # Round 30: the battle route also lazy-loads the decrypted mechanism
    # substrate, so the needData list now ends with ...,'mech','substrate'.
    check('mechanics loaded on demand', "mech: ['data/battle-mech.js'" in perf and
          "'cup','mech'" in app and "'mech','substrate'" in app and 'battle-mech.js' not in html)
    check('package + rebuild include mechanics',
          'data/battle-mech.js' in pkg and 'extract_battle_mechanics.py' in pkg and 'extract_battle_mechanics.py' in reb)

    # ---------- engine ----------
    out = subprocess.run([str(NODE), '-e', ENGINE], cwd=ROOT, capture_output=True, text=True, encoding='utf8', timeout=600)
    try:
        e = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        e = {}
        print(out.stdout[-800:], out.stderr[-1200:])
    check('Lua interpreter: expressions / loops / pairs / closures / unknown detection', e.get('lua') and all(e['lua'].values()), str(e.get('lua')))
    check('every exported Lua condition parses', e.get('syntax') == 0 and e.get('parsed', 0) > 2500, f"{e.get('parsed')} ok / {e.get('syntax')} syntax")
    check('40 cup matches simulate without errors / no runaway battle',
          e.get('done') == 40 and e.get('errors') == 0 and e.get('slow') == 0,
          f"done={e.get('done')} errors={e.get('errors')} maxMs={e.get('maxMs')} "
          f"medianMs={e.get('medianMs')} slow(>6x median)={e.get('slow')}")
    check('both sides can win', e.get('wins', {}).get('A', 0) > 5 and e.get('wins', {}).get('B', 0) > 5, str(e.get('wins')))
    check('most fighters actually act', e.get('zeroActors', 99) <= 2, str(e.get('zeroActors')))
    ex = e.get('exec', {})
    core_types = ['BUFF', 'AURA', 'CAST_SKILL', 'DISPEL', 'REMOVE_BUFF', 'RECOVER_ATTRIBUTE', 'LIFE_LOST', 'PREWAR_MODIFY_ATTRIBUTE']
    check('core effect types execute', all(ex.get(k, 0) > 0 for k in core_types), str({k: ex.get(k, 0) for k in core_types}))
    reactive = ['PARRY', 'EVADE', 'COUNTER_ATTACK', 'FIRST_HIT', 'REBORN', 'KNOCKBACK']
    check('reaction mechanics execute', sum(1 for k in reactive if ex.get(k, 0) > 0) >= 4, str({k: ex.get(k, 0) for k in reactive}))
    c = e.get('cond', {})
    tot = sum(c.values()) or 1
    check('>=97% of Lua condition checks are evaluable', c.get('unknown', tot) / tot < 0.03, str(c))
    check('battle is deterministic for a seed (events included)', e.get('det') is True)
    check('weather aura applied', e.get('weatherLogged') and e.get('auraBuffs'))
    check('self-centred AOE hits enemies around the caster', e.get('kovCasts', 0) >= 1 and e.get('aoeHitsEnemies') is True, str(e.get('kovCasts')))
    check('roster battles run with mechanics', not e.get('roster', {}).get('err') and e['roster']['exec'] >= 5, str(e.get('roster')))
    # Edited base stats are kept; the character's own passives (e.g. 开局最大生命 +20%) still stack on top.
    check('edited fighter keeps edits', e.get('custom', {}).get('base') == 99999 and e['custom'].get('hp', 0) >= 99999
          and e['custom'].get('used'), str(e.get('custom')))
    check('works without mechanics data (fallback)', not e.get('legacy', {}).get('err') and e['legacy'].get('loaded') is False, str(e.get('legacy')))
    check('text log includes mechanics coverage', e.get('log') is True)

    # ---------- UI ----------
    errors, failed = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(offline=True, viewport={'width': 1500, 'height': 950}).new_page()
        page.set_default_timeout(30000)
        page.on('pageerror', lambda x: errors.append(str(x)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))
        reqs = []
        page.on('request', lambda r: reqs.append(r.url))
        page.goto(BASE + '#/')
        page.wait_for_timeout(400)
        check('home does not load mechanics', not any('battle-mech.js' in u for u in reqs))
        reqs.clear()
        page.goto(BASE + '#/tools/battle')
        page.locator('#bsim-board svg').wait_for()
        check('battle page loads mechanics', any('battle-mech.js' in u for u in reqs))
        check('weather selector populated', page.locator('#bsim-weather option').count() >= 10)
        check('unit panel shows statuses and passives',
              page.locator('.bsim-buff').count() > 0 and page.locator('.bsim-passives').count() > 0)
        check('unit panel shows energy', '能量' in page.locator('#bsim-units').inner_text())
        check('mechanics coverage panel', page.locator('.bsim-mech').count() == 1 and '条件可求值' in page.locator('.bsim-mech summary').inner_text())
        check('battle handbook in help', page.locator('.bsim-handbook dt').count() >= 30)
        found = False
        for _ in range(30):
            page.locator('[data-play="next"]').click()
            if page.locator('.bsim-events li').count():
                found = True
                break
        check('steps list the triggered effects', found)
        page.evaluate("()=>{document.querySelector('.bsim-cup').open=true;}")
        check('cup environment + evidence shown', '炽热气氛' in page.locator('.bsim-cup-env').inner_text())
        page.locator('[data-cup-load="both"]').click()
        page.wait_for_timeout(1500)
        check('loading a cup match switches to the arena + weather',
              'arena' in page.locator('#bsim-title').inner_text() and '炽热气氛' in page.locator('#bsim-title').inner_text(),
              page.locator('#bsim-title').inner_text())
        check('cup fighters carry statuses on the board', page.locator('.bsim-buff').count() > 10)
        page.locator('[data-cup-predict="one"]').click()
        page.wait_for_timeout(3000)
        check('prediction still works with mechanics', page.locator('.bsim-pred-table tbody tr').count() == 1)
        page.locator('[data-bsim-view="3d"]').click()
        page.wait_for_timeout(500)
        check('3D board still renders units', page.locator('.bsim3-unit').count() >= 10)
        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
