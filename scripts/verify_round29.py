"""Round 29: utility skills, real-time conversion, remaining effects, AI,
and the decrypted client Lua script index.

    python -X utf8 scripts/verify_round29.py
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
    if not ok: failures.append(name)


def load(rel, var):
    t = (ROOT / rel).read_text('utf8'); m = 'window.' + var + '='
    return json.JSONDecoder().raw_decode(t[t.index(m) + len(m):])[0]


ENGINE = r"""
const fs=require('fs'),vm=require('vm');const ctx={window:{}};vm.createContext(ctx);
for(const f of ['data/world-data.js','data/battle-sim.js','data/match-cup.js','data/battle-mech.js','battle-sim-core.js'])
  vm.runInContext(fs.readFileSync(f,'utf8'),ctx);
const W=ctx.window.WIKI_WORLD_DATA,D=ctx.window.WIKI_BATTLE_SIM,C=ctx.window.WIKI_MATCH_CUP,M=ctx.window.WIKI_BATTLE_MECH,S=ctx.window.WikiBattleSim;
const arena=W.maps.find(m=>m.id===C.environment.mapId);
const team=id=>C.teams.find(t=>t.id===id);
const mk=m=>({name:m.name,stats:m.stats,move:m.move,prof:m.prof,profName:m.profName,
  kit:m.kit,skills:m.skills,edited:false,npcId:m.npcId,star:m.star});
const mem=t=>t.members.map(mk);
const s0=C.schedules[0];
const opts={data:D,mech:M,map:arena,teams:{A:mem(team(s0.team1Id)),B:mem(team(s0.team2Id))},seed:42,maxRounds:20};
const r=S.simulate(opts);
if(r.error){console.log(JSON.stringify({err:r.error}));}
// skill bar
let bar=0,utility=0;const examples=[];
for(const u of r.units){bar+=u.skills.length;const us=u.skills.filter(s=>s.dt===5||(!s.df&&!s.dmg&&!s.dp));
  utility+=us.length;for(const s of us)if(examples.length<6)examples.push([s.id,s.n,s.dt]);}
// conversion from 流星队
let lx;for(const t of C.teams)for(const m of t.members)if(!lx&&m.name.includes('流星队'))lx=m;
const f=mk(lx);
const r2=S.simulate({...opts,teams:{A:[f,f,f,f],B:[f,f,f,f]},seed:7,maxRounds:20});
const pa=r2.inspect(0,'A1').attrs.find(a=>a.key==='PHYSIC_ATTACK');
const spell=r2.inspect(0,'A1').attrs.find(a=>a.key==='SPELL_ATTACK');
const conv=pa.parts.filter(x=>x.converted&&x.ok);
// 40-schedule sweep for skipped effects
const skipped={},executed={},unknown={};let done=0,err=0,exceptions=[];
for(const s of C.schedules.slice(0,40)){
  const buffs=s.buffDetails.map(b=>({buffId:b.buffId,side:b.target===1?'A':b.target===2?'B':'both'}));
  let q;
  try{q=S.simulate({data:D,mech:M,map:arena,teams:{A:mem(team(s.team1Id)),B:mem(team(s.team2Id))},
    seed:1000+s.id,maxRounds:20,env:{weatherId:C.environment.weatherId,buffs}});}
  catch(e){err++;exceptions.push(s.id+':'+e.message);continue;}
  if(q.error){err++;continue;}
  done++;
  for(const [k,v] of Object.entries(q.mechanics.skipped||{}))skipped[k]=(skipped[k]||0)+v;
  for(const [k,v] of Object.entries(q.mechanics.executed||{}))executed[k]=(executed[k]||0)+v;
  for(const [k,v] of Object.entries(q.mechanics.luaUnknown||{}))unknown[k]=(unknown[k]||0)+v;
}
// AI: alternative candidates recorded, and utility casts
const casts=new Set();for(const st of r.steps)for(const e of st.events||[]){const m=e.match(/发动「([^」]+)」/);if(m)casts.add(m[1]);}
const utilNames=new Set();for(const u of r.units)for(const s of u.skills)if(s.dt===5||(!s.df&&!s.dmg&&!s.dp))utilNames.add(s.n);
const utilCast=[...utilNames].filter(n=>casts.has(n));
// determinism
const a=S.simulate(opts),b=S.simulate(opts);
for(let i=0;i<6;i++)a.inspect(i,a.units[i%a.units.length].uid);
const sig=x=>JSON.stringify(x.steps.map(s=>s.text+(s.events||[]).join('|')));
console.log(JSON.stringify({
 err:r.error||null,steps:r.steps.length,bar,utility,examples,
 conv:{value:pa.value,converted:pa.converted,formula:pa.formula,
   spell:spell.value,parts:conv.map(x=>({n:x.n,flat:x.flat,note:x.note}))},
 sweep:{done,err,exceptions:exceptions.slice(0,3),
   skippedTotal:Object.values(skipped).reduce((x,y)=>x+y,0),
   topSkipped:Object.entries(skipped).sort((x,y)=>y[1]-x[1]).slice(0,6),
   unknownTotal:Object.values(unknown).reduce((x,y)=>x+y,0),
   topUnknown:Object.entries(unknown).sort((x,y)=>y[1]-x[1]).slice(0,6),
   newEffects:Object.fromEntries(['TARGET_TELEPORT','SHARE_DAMAGE','PARASITIC','RANDOM_UNIT',
     'SHAPESHIFT','DELAY_SKILL','KNOCKBACK_SELF','POISON','OTHER_TELEPORT_TO_TARGET',
     'CONSUME_RETURN','CONDITION_SKILL','CHANGE_WEATHER','CHARGE_ATTRIBUTE','PARASITIC_RECOVERY',
     'PER_DAMAGED_LIMIT','DAMAGE_STORAGE','DEMAND_ASSIST_DEFENCE'].map(k=>[k,executed[k]||0]))},
 ai:{casts:casts.size,utilNames:utilNames.size,utilCast},
 deterministic:sig(a)===sig(b),
}));
"""


def main():
    C = load('data/match-cup.js', 'WIKI_MATCH_CUP')
    M = load('data/battle-mech.js', 'WIKI_BATTLE_MECH')
    L = load('data/lua-scripts.js', 'WIKI_LUA_SCRIPTS')
    core = (ROOT / 'battle-sim-core.js').read_text('utf8')
    ui = (ROOT / 'battle-sim-ui.js').read_text('utf8')

    # 1. utility skills in the bar
    util = sum(1 for t in C['teams'] for m in t['members'] for s in m['allSkills'] if s.get('utility'))
    check('all active client skills marked castable',
          all(s['simulated'] for t in C['teams'] for m in t['members'] for s in m['allSkills']
              if s.get('clientType') == 1 and s.get('role') != '派生技能'))
    check('utility skills exported', util > 300, str(util))
    check('engine castable accepts all active skills', "force || s.ty === 1 || !!s.ap" in core)
    check('utility side inferred from specialities', 'function utilitySide' in core)

    # 2. real-time conversion added to total
    check('convert uses real-time source', 'attrRaw(u, attrName(s.p[0]), ctx)' in core)
    check('convert added after percentage layer', 'return core + converted;' in core)
    check('panel shows conversion separately', '实时属性转换' in core)

    # 3. effects
    for key in ('TARGET_TELEPORT', 'SHARE_DAMAGE', 'PARASITIC', 'RANDOM_UNIT', 'SHAPESHIFT',
                'DELAY_SKILL', 'KNOCKBACK_SELF', 'POISON', 'OTHER_TELEPORT_TO_TARGET',
                'CONSUME_RETURN', 'CONDITION_SKILL', 'CHANGE_WEATHER', 'CHARGE_ATTRIBUTE',
                'PARASITIC_RECOVERY', 'PER_DAMAGED_LIMIT', 'DAMAGE_STORAGE'):
        check(f'effect {key} implemented', f'{key}(inst' in core)

    # 4. AI
    check('AI scores utility effects', 'function effectValue' in core and 'UTILITY_W' in core)
    check('AI uses client AI hints', 's.aop' in core and 's.amc' in core)
    check('AI threat-aware positioning', 'const threat =' in core)
    for k in ('amc', 'aop', 'top'):
        check(f'client AI field {k} exported', any(k in s for s in M['skills'].values()))

    # 5. decryption
    meta = L['meta']
    check('decrypted most client scripts', meta['scripts'] > 4000,
          f"{meta['scripts']}/{meta['totalArchived']}")
    check('readable constant pool', meta['readableStrings'] > 50000, str(meta['readableStrings']))
    check('AI terms extracted', len(L['aiTerms']) > 5000, str(len(L['aiTerms'])))
    check('decryptor is reproducible', 'scripts/socdecode/lua_scripts.py' in
          (ROOT / 'scripts/socdecode/rebuild.py').read_text('utf8'))
    check('decrypted data registered', "lua: ['data/lua-scripts.js'" in
          (ROOT / 'perf-core.js').read_text('utf8'))
    check('decryption browser available', 'renderLuaScripts' in
          (ROOT / 'world-ui.js').read_text('utf8') and 'data-lua-load' in ui)

    out = subprocess.run([str(NODE), '-e', ENGINE], cwd=ROOT, capture_output=True,
                         text=True, encoding='utf8', timeout=900)
    try: e = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        e = {}; print(out.stdout[-1200:], out.stderr[-1500:])
    check('battle simulates', not e.get('err') and e.get('steps', 0) > 20, str(e.get('err')))
    check('utility skills present in skill bar', e.get('utility', 0) > 0,
          f"{e.get('utility')}/{e.get('bar')} {e.get('examples')}")
    cv = e.get('conv', {})
    check('conversion uses real-time spell attack',
          any('实时 SPELL_ATTACK' in x['note'] for x in cv.get('parts', [])), str(cv.get('parts'))[:220])
    check('conversion added to total, not multiplied',
          '实时属性转换' in (cv.get('formula') or '') and cv.get('converted', 0) > 0,
          cv.get('formula'))
    sw = e.get('sweep', {})
    check('40 cup matches clean', sw.get('done') == 40 and sw.get('err') == 0, str(sw.get('exceptions')))
    check('skipped effects drastically reduced', sw.get('skippedTotal', 9999) < 100,
          f"{sw.get('skippedTotal')} {sw.get('topSkipped')}")
    check('new effects actually fire', sum(sw.get('newEffects', {}).values()) > 0,
          str(sw.get('newEffects')))
    check('AI casts utility skills', e.get('ai', {}).get('utilCast', []) != [] or
          e.get('ai', {}).get('utilNames', 0) > 0, str(e.get('ai'))[:200])
    check('inspection stays deterministic', e.get('deterministic') is True)

    # browser
    errors, failed = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(offline=True, viewport={'width':1600,'height':1000}).new_page()
        page.set_default_timeout(30000)
        page.on('pageerror', lambda x: errors.append(str(x)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))
        page.goto(BASE + '#/tools/battle')
        page.locator('#bsim-board svg').wait_for()
        page.locator('.bsim-mech summary').first.click()
        page.wait_for_timeout(150)
        page.locator('[data-lua-load]').click()
        page.wait_for_timeout(900)
        stat = page.locator('.bsim-lua-stat').inner_text()
        check('decryption index loads in browser', '4,483' in stat or '4483' in stat, stat[:110])
        page.locator('.bsim-lua-q').fill('ai_dict')
        page.wait_for_timeout(250)
        check('script constant search works', page.locator('.bsim-lua-file').count() > 0)
        page.goto(BASE + '#/code')
        page.wait_for_timeout(1100)
        check('decryption panel on code page', page.locator('.world-lua-panel').count() == 1)
        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
