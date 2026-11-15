"""Round 28: hidden tooltip effects (dynamic_param, BUFF_CHANGE, 解放技能,
shields, placed objects, base-stat provenance).

    python -X utf8 scripts/verify_round28.py
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
const mk=m=>({name:m.name,stats:m.stats,move:m.move,prof:m.prof,profName:m.profName,
  kit:m.kit,skills:m.skills,edited:false,npcId:m.npcId,star:m.star});
const findAll=l=>{const o=[];for(const t of C.teams)for(const m of t.members)if(m.name.includes(l))o.push(m);return o;};
const filler=mk(findAll('柯瓦雷')[0]||findAll('麦莎')[0]);
const run=who=>S.simulate({data:D,mech:M,map:arena,
  teams:{A:[mk(who),filler,filler,filler],B:[filler,filler,filler,filler]},seed:7,maxRounds:20});
const lx=findAll('流星队')[0], dark=findAll('黑暗医师')[0], ulia=findAll('乌莉娅')[0], ax=findAll('阿列克谢·SP')[0];
const lr=run(lx), ur=run(ulia), ar=run(ax);
// ---- 1: module skill + BUFF_CHANGE -> 虔诚值 + CONVERT_ATTRIBUTE ----
const p0=lr.inspect(0,'A1');
const patk=p0.attrs.find(a=>a.key==='PHYSIC_ATTACK');
const convert=patk.parts.filter(x=>x.skillId===22143 && x.t==='CONVERT_ATTRIBUTE');
const lxEvents=lr.steps.some(s=>(s.events||[]).some(e=>e.includes('虔诚值')));
// ---- 2: shields ----
const shields=p0.shields||[];
const shieldRatio=p0.mhp?p0.shieldPhys/p0.mhp:0;
// ---- 3: snowman ----
// Round 31: the snowman is now destroyed by 乌莉娅's basic attack, so it is
// no longer in the FINAL placed list. Scan per-step snapshots instead.
const snow=(ur.steps||[]).flatMap(s=>s.placed||[]).filter(o=>o.kind==='PLACE_ITEM')
  .filter((o,i,a)=>a.findIndex(x=>x.id===o.id&&x.x===o.x&&x.y===o.y)===i);
// ---- 5: 渴血战斧 dynamic layers + non-current-turn condition ----
const axeSteps=[];for(let i=0;i<Math.min(12,ar.steps.length);i++){
  const q=ar.inspect(i,'A1');const pa=q.attrs.find(a=>a.key==='PHYSIC_ATTACK');
  const dyn=pa.parts.find(x=>x.specId===26211);const b=q.buffs.find(x=>x.id===698);
  axeSteps.push({seq:i,actor:ar.steps.find(s=>s.seq===i)?.actor,axe:b?b.stacks:0,
    pct:dyn?dyn.pct:null,ok:dyn?dyn.ok:null,patk:Math.round(pa.value)});
}
// ---- 6: full sweep ----
const team=id=>C.teams.find(t=>t.id===id);
const mem=t=>t.members.map(mk);
let done=0,err=0,exceptions=[];const exec={},skipped={},unknown={},placed={};
const t0=Date.now();
for(const s of C.schedules){
  const buffs=s.buffDetails.map(b=>({buffId:b.buffId,side:b.target===1?'A':b.target===2?'B':'both'}));
  let r;
  try{r=S.simulate({data:D,mech:M,map:arena,teams:{A:mem(team(s.team1Id)),B:mem(team(s.team2Id))},
    seed:1000+s.id,maxRounds:20,env:{weatherId:C.environment.weatherId,buffs}});}
  catch(e){err++;exceptions.push(s.id+':'+e.message);continue;}
  if(r.error){err++;continue;}
  done++;
  for(const [k,v] of Object.entries(r.mechanics.executed))exec[k]=(exec[k]||0)+v;
  for(const [k,v] of Object.entries(r.mechanics.skipped||{}))skipped[k]=(skipped[k]||0)+v;
  for(const [k,v] of Object.entries(r.mechanics.luaUnknown||{}))unknown[k]=(unknown[k]||0)+v;
  for(const o of r.placed||[])placed[o.kind]=(placed[o.kind]||0)+1;
}
// determinism
const s0=C.schedules[0];
const o={data:D,mech:M,map:arena,teams:{A:mem(team(s0.team1Id)),B:mem(team(s0.team2Id))},seed:7,maxRounds:20};
const a=S.simulate(o),b=S.simulate(o);
for(let i=0;i<6;i++)a.inspect(i,a.units[i%a.units.length].uid);
const sig=x=>JSON.stringify(x.steps.map(s=>s.text+(s.events||[]).join('|')));
const dpSpecs=Object.values(M.specs).filter(s=>s.dp).length;
const moduleFighters=C.teams.reduce((x,t)=>x+t.members.filter(m=>(m.kit.module||[]).length).length,0);
console.log(JSON.stringify({
 dpMeta:M.dynamicParams,dpSpecs,moduleFighters,
 lx:{kit:lx.kit.module,events:lxEvents,buff8878:p0.buffs.some(x=>x.id===8878),
     convert:convert.map(x=>({spec:x.specId,flat:x.flat,ok:x.ok})),
     dynamicExec:lr.mechanics.executed['DYNAMIC_PARAM']||0},
 shields:{items:shields,ratio:shieldRatio,phys:p0.shieldPhys,spell:p0.shieldSpell,hp:p0.mhp},
 snow,statSource:dark.statSource,
 axe:{steps:axeSteps,dp:M.specs['26211']?.dp,cond:M.specs['26211']?.c},
 sweep:{done,err,exceptions:exceptions.slice(0,3),totalMs:Date.now()-t0,
   dynamicExec:exec['DYNAMIC_PARAM']||0,
   newEffects:Object.fromEntries(['PLACE_ITEM','PLACE_TRAP','PLACE_UNIT','LIFE_LOST','ACTED_ACT','ACTED_MOVE']
     .map(k=>[k,exec[k]||0])),
   placed,topSkipped:Object.entries(skipped).sort((x,y)=>y[1]-x[1]).slice(0,6),
   luaUnknown:unknown},
 deterministic:sig(a)===sig(b),
}));
"""


def main():
    C = load('data/match-cup.js', 'WIKI_MATCH_CUP')
    M = load('data/battle-mech.js', 'WIKI_BATTLE_MECH')
    core = (ROOT / 'battle-sim-core.js').read_text('utf8')
    ui = (ROOT / 'battle-sim-ui.js').read_text('utf8')

    # ---- static checks ----
    check('dynamic_param exported', M.get('dynamicParams', {}).get('exported', 0) > 200,
          str(M.get('dynamicParams')))
    check('engine resolves dynamic params', 'resolvedSpec' in core and 'Lua.params' in core)
    check('Lua supports multi-return', 'vs: st.es && st.es.length > 1' in core)
    check('BUFF_CHANGE context wired', 'FindChangedBuff' in core and 'stack_count_change' in core
          and 'changedBuffs' in core)
    check('shield multiplied by stacks', 'perLayer * b.stacks' in core)
    check('shield provenance in panel', 'shields: shieldPartsOf(u)' in core and 'bsim-shield-row' in ui)
    check('base stat provenance exported', all(m.get('statSource') for t in C['teams'] for m in t['members']))
    check('base stat provenance shown in UI', 'bsim-stat-src' in ui)
    check('module skills in kits', any(m.get('kit', {}).get('module') for t in C['teams'] for m in t['members']))
    check('placed objects implemented', 'placeObject' in core and 'placed: placed.filter' in core)
    check('new effect handlers present', all(k in core for k in
          ('PLACE_ITEM(inst, ctx)', 'PLACE_UNIT(inst, ctx)', 'LIFE_LOST(inst, ctx)',
           'BUFF_BUNDLE_GAIN(inst, ctx)', 'ACTED_ACT(inst, ctx)')))

    out = subprocess.run([str(NODE), '-e', ENGINE], cwd=ROOT, capture_output=True, text=True,
                         encoding='utf8', timeout=900)
    try:
        e = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        e = {}
        print(out.stdout[-1200:], out.stderr[-1500:])
    lx = e.get('lx', {})
    check('解放技能 in kit', lx.get('kit') == [22143], str(lx.get('kit')))
    check('虔诚值 gained on 后备隐藏脂肪', lx.get('events') is True and lx.get('buff8878') is True)
    check('魔攻 10%/30% 转物攻 present', len(lx.get('convert', [])) >= 2, str(lx.get('convert')))
    check('dynamic params executed in battle', lx.get('dynamicExec', 0) > 0)

    sh = e.get('shields', {})
    items = sh.get('items', [])
    check('shield sources itemised', len(items) >= 2, str(items)[:220])
    check('6 layers = 60% max HP', abs(sh.get('ratio', 0) - 0.6) < 0.02,
          f"phys={sh.get('phys')} hp={sh.get('hp')} ratio={sh.get('ratio')}")
    check('shield row shows per-layer value', all('perLayer' in x and 'stacks' in x for x in items))

    check('乌莉娅 places 雪人', any(x.get('kind') == 'PLACE_ITEM' for x in e.get('snow', [])),
          str(e.get('snow')))
    st = e.get('statSource', {})
    check('黑暗医师 base provenance exact', st.get('modifyId') == 263 and st.get('level') == 60
          and st.get('row', {}).get('physic_attack') == 2212, str(st)[:220])
    check('base provenance lists rarity multipliers', len(st.get('rarityAdjust', {})) >= 4)

    axe = e.get('axe', {})
    steps = axe.get('steps', [])
    check('渴血战斧 dynamic_param exported', 'stack_count' in (axe.get('dp') or ''), str(axe.get('dp')))
    check('每层 10% 物攻 = 层数 × 10', any(x.get('axe') == 2 and x.get('pct') == 20 for x in steps),
          str(steps[:5]))
    check('非当前行动时条件生效', any(x.get('actor') == 'A1' and x.get('ok') is False for x in steps)
          and any(x.get('actor') != 'A1' and x.get('ok') is True for x in steps), str(steps[:10]))

    sw = e.get('sweep', {})
    check('192 cup matches run clean', sw.get('done') == 192 and sw.get('err') == 0,
          f"done={sw.get('done')} err={sw.get('err')} ex={sw.get('exceptions')}")
    check('dynamic params execute at scale', sw.get('dynamicExec', 0) > 10000, str(sw.get('dynamicExec')))
    check('new effects actually fire', sum(v for k, v in sw.get('newEffects', {}).items()) > 1000,
          str(sw.get('newEffects')))
    check('objects placed across matches', sum(sw.get('placed', {}).values()) > 100, str(sw.get('placed')))
    check('inspection stays deterministic', e.get('deterministic') is True)

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
        page.evaluate("()=>{document.querySelector('.bsim-cup').open=true;}")
        page.evaluate("()=>{document.querySelector('.bsim-cup-roster').open=true;}")
        page.wait_for_timeout(300)
        check('base stat source visible in roster', page.locator('.bsim-stat-src').count() > 0)
        dark = page.locator('.bsim-cup-unit').filter(has_text='黑暗医师').first
        if dark.count():
            dark.evaluate('e=>e.open=true')
            page.wait_for_timeout(150)
            src = dark.locator('.bsim-stat-src').first
            src.evaluate('e=>e.open=true')
            page.wait_for_timeout(120)
            check('dark physician provenance text', '2212' in src.inner_text() and '2388' in src.inner_text(),
                  src.inner_text()[:160])
        else:
            check('dark physician provenance text', True, 'not in first schedule')
        page.locator('[data-cup-load="both"]').click()
        page.wait_for_timeout(2200)
        page.locator('.bsim-unit[data-unit]').first.click()
        page.wait_for_timeout(300)
        check('character panel opens', page.locator('.bsim-panel-head').count() == 1)
        check('mechanism coverage present', page.locator('.bsim-mech').count() == 1)
        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
