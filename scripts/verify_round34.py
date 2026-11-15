"""Round 34: facing arrows/semantics, per-skill damage settlement, 爆裂箭.

    python -X utf8 scripts/verify_round34.py
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
const team=id=>C.teams.find(t=>t.id===id),mem=t=>t.members.map(mk);
let ulia,filler,inanna;
for(const t of C.teams)for(const m of t.members){if(!ulia&&m.name.includes('乌莉娅'))ulia=m;if(!filler&&m.name.includes('柯瓦雷'))filler=m;}
inanna=D.roster.find(x=>x.name==='伊南娜');
const f=mk(filler);

// ---- 1. facing controls front spawns for all four directions -------------
const facing={};
for(const [n,d] of Object.entries({east:[1,0],west:[-1,0],south:[0,1],north:[0,-1]})){
  const o=S.simulate({data:D,mech:M,map,teams:{A:[mk(ulia),f,f,f],B:[f,f,f,f]},seed:7,
    maxRounds:3,substrate:SUB,spawns:{A:[{x:9,y:3,dir:d}],B:[]}});
  const snow=(o.steps[0].placed||[]).find(x=>x.id===516);
  const i=S.simulate({data:D,mech:M,map,teams:{A:[mk(inanna),f,f,f],B:[f,f,f,f]},seed:7,
    maxRounds:3,substrate:SUB,spawns:{A:[{x:9,y:3,dir:d}],B:[]}});
  const guard=(i.steps[0].snap||[]).find(x=>x.uid==='AS1');
  facing[n]={want:[9+d[0],3+d[1]],snow:snow?[snow.x,snow.y]:null,
             guard:guard?[guard.x,guard.y]:null,dir:(o.steps[0].snap||[]).find(x=>x.uid==='A1')?.dir};
}

// ---- 2. live facing changes on walk + cast -------------------------------
const s0=C.schedules[0];
const rf=S.simulate({data:D,mech:M,map,teams:{A:mem(team(s0.team1Id)),B:mem(team(s0.team2Id))},
  seed:7,maxRounds:20,substrate:SUB});
let moved=0,cast=0,noTurn=0,badMove=0;
for(const st of rf.steps.slice(1)){
  const cur=(st.snap||[]).find(x=>x.uid===st.actor)?.dir;
  const before=st.facingFrom;
  if(!cur||!before)continue;
  const changed=cur.join(',')!==before.join(',');
  if(changed&&st.kind==='move')moved++;
  if(changed&&st.kind==='skill')cast++;
  if(!changed&&st.kind==='skill')noTurn++;
  if(st.kind==='move'&&st.path?.length>=2){
    const p=st.path,last=p[p.length-2],end=p[p.length-1];
    const want=Math.abs(end.x-last.x)>=Math.abs(end.y-last.y)
      ?[Math.sign(end.x-last.x),0]:[0,Math.sign(end.y-last.y)];
    if((want[0]||want[1])&&(cur[0]!==want[0]||cur[1]!==want[1]))badMove++;
  }
}

// ---- 3. 爆裂箭 19449 ------------------------------------------------------
const sched=C.schedules.find(s=>s.id===22);
const buffs=sched.buffDetails.map(b=>({buffId:b.buffId,side:b.target===1?'A':b.target===2?'B':'both'}));
// Round 36: 安娜 now follows her declared skill order, so 爆裂箭 comes later.
// Scan seeds for a cast where the追加段 actually resolved (the client skips
// overkill when the primary target falls to the 3 base hits).
let boom=null, rb=null;
for(const seed of [7,1090,20261107,3,11,23]){
  rb=S.simulate({data:D,mech:M,map,teams:{A:mem(team(sched.team1Id)),B:mem(team(sched.team2Id))},
    seed,maxRounds:20,env:{weatherId:C.environment.weatherId,buffs},substrate:SUB});
  boom=rb.steps.find(s=>s.skill?.id===19449 && s.consumption &&
    (s.hits||[]).some(h=>/^追加/.test(h.seg||'')))||null;
  if(boom)break;
}
const bh=boom?.hits||[];
const base=bh.filter(h=>/第 \d\/3 段/.test(h.seg||''));
const extra=bh.find(h=>/^追加/.test(h.seg||''));
const plan=M.skillPlans['19449'];
const boomData={found:!!boom,text:boom?.text?.slice(0,120)||'',
  baseCount:base.length,baseFactors:[...new Set(base.map(h=>h.factor))],
  baseAmounts:base.map(h=>h.amount),baseCrits:base.map(h=>!!h.crit),
  baseCalcs:base.map(h=>h.calc?.length||0),
  extra:extra?{factor:extra.factor,boost:extra.boost,seg:extra.seg,amount:extra.amount,calc:extra.calc?.length}:null,
  plan,c:boom?.consumption||null,events:(boom?.events||[]).filter(e=>/消耗|追加伤害结算/.test(e)),
  planOnStep:!!boom?.plan,skipped:rb.mechanics.skipped||{},unknown:rb.mechanics.luaUnknown||{}};

// ---- 4. generic multi-hit sweep ------------------------------------------
let done=0,err=0,exceptions=[],planSteps=0,segments=0,bonus=0,facingChanges=0,multiSkills={};
const skipped={},unknown={};
for(const s of C.schedules.slice(0,40)){
  const bf=s.buffDetails.map(b=>({buffId:b.buffId,side:b.target===1?'A':b.target===2?'B':'both'}));
  let r;try{r=S.simulate({data:D,mech:M,map,teams:{A:mem(team(s.team1Id)),B:mem(team(s.team2Id))},
    seed:1000+s.id,maxRounds:20,env:{weatherId:C.environment.weatherId,buffs:bf},substrate:SUB});}
  catch(e){err++;exceptions.push(s.id+':'+e.message);continue;}
  if(r.error){err++;continue;}
  done++;
  for(const st of r.steps){
    if(st.plan){planSteps++;segments+=(st.hits||[]).filter(h=>h.seg).length;
      if(st.plan.h>1)multiSkills[st.skill.name]=(multiSkills[st.skill.name]||0)+1;}
    for(const h of st.hits||[])if(/^追加/.test(h.seg||''))bonus++;
    if(st.facingFrom){const cur=(st.snap||[]).find(x=>x.uid===st.actor)?.dir;
      if(cur&&cur.join(',')!==st.facingFrom.join(','))facingChanges++;}
  }
  for(const [k,v] of Object.entries(r.mechanics.skipped||{}))skipped[k]=(skipped[k]||0)+v;
  for(const [k,v] of Object.entries(r.mechanics.luaUnknown||{}))unknown[k]=(unknown[k]||0)+v;
}
const a=S.simulate({data:D,mech:M,map,teams:{A:[mk(ulia),f,f,f],B:[f,f,f,f]},seed:7,maxRounds:20,substrate:SUB});
const b=S.simulate({data:D,mech:M,map,teams:{A:[mk(ulia),f,f,f],B:[f,f,f,f]},seed:7,maxRounds:20,substrate:SUB});
const sig=x=>JSON.stringify(x.steps.map(s=>s.text+(s.events||[]).join('|')));
console.log(JSON.stringify({facing,live:{moved,cast,noTurn,badMove},boom:boomData,
  sweep:{done,err,exceptions:exceptions.slice(0,3),planSteps,segments,bonus,facingChanges,
    multiSkillCount:Object.keys(multiSkills).length,
    topMulti:Object.entries(multiSkills).sort((x,y)=>y[1]-x[1]).slice(0,5),
    skipped:Object.entries(skipped).sort((x,y)=>y[1]-x[1]).slice(0,5),
    unknown:Object.entries(unknown).sort((x,y)=>y[1]-x[1]).slice(0,5)},
  deterministic:sig(a)===sig(b),
  planStats:{plans:Object.keys(M.skillPlans||{}).length,
    multi:Object.values(M.skillPlans||{}).filter(p=>p.h>1).length,
    consume:Object.values(M.skillPlans||{}).filter(p=>p.cons).length,
    bonus:Object.values(M.skillPlans||{}).filter(p=>p.bonus).length}}));
"""


def main():
    core = (ROOT / 'battle-sim-core.js').read_text('utf8')
    ui = (ROOT / 'battle-sim-ui.js').read_text('utf8')
    css = (ROOT / 'refinements.css').read_text('utf8')
    mech = (ROOT / 'data/battle-mech.js').read_text('utf8')
    M = json.loads(mech.split('=', 1)[1].strip().rstrip(';'))
    compiler = (ROOT / 'scripts/skill_mechanics.py').read_text('utf8')
    extractor = (ROOT / 'scripts/extract_battle_sim.py').read_text('utf8')

    # 1. arrows
    check('direction-derived arrow helper', 'function facingArrow(d, outer, inner, halfW)' in ui
          and 'const ux = d[0] / len' in ui)
    check('no hard-coded north tip', 'M0,${-CELL * 0.42}' not in ui)
    check('2D unit arrow uses live step dir', 'const d = s.dir || u.initialDir' in ui)
    check('3D token has facing arrow', 'bsim3-facing' in ui and 'bsim3-facing' in css)
    check('facing note in step detail', 'bsim-facing-note' in ui and 'DIR_NAMES(actorDir)' in ui)
    check('multi-segment hit aggregation', 'function aggregateHits(step)' in ui
          and ui.count('aggregateHits(step)') >= 2)

    # 2. facing semantics
    for key in ('facingFrom: unit.dir.slice()', 'step.plan = skillPlan(skill)',
                'captureConsumption', 'applyConsumption', 'settleBonus'):
        check(f'engine {key}', key in core)
    check('cast only turns for real casts', 'opts.free || caster.flags?.notTurnAround' in core)
    check('move sets final facing', 'unit.dir = dirTo(last, {x, y})' in core)
    check('front spawns use current dir', 'ctx?.dir || owner.dir || owner.initialDir' in core)
    check('dirTo zero guard', 'if (!dx && !dy) return from.dir || [1, 0]' in core)
    check('facing change logged', '朝向由 ${names(step.facingFrom)} 转为' in core)

    # 3. plans / compiler
    check('skillPlans exported', len(M['skillPlans']) >= 900, str(len(M['skillPlans'])))
    plan = M['skillPlans']['19449']
    check('爆裂箭 plan groups 3 × 50%', plan['g'] == [[3, 50]] and plan['h'] == 3)
    check('爆裂箭 consumes TP + 多重爆裂', plan['cons'] == {'tp': 2, 'apply': 1, 'b': 7391}
          or (plan['cons'].get('tp') and plan['cons'].get('b') == 7391), str(plan['cons']))
    check('爆裂箭 bonus 40% per layer +60%', plan['bonus'] == [[40, 60, 1]], str(plan['bonus']))
    check('爆裂箭 cites decrypted specs', '25468' in plan.get('from', []) and '24043' in plan.get('from', []))
    check('compiler parses mixed groups', 'RE_MIXED' in compiler and 'RE_PER_HIT' in compiler
          and 'RE_CONSUME_TP' in compiler and 'RE_BONUS' in compiler)
    check('compiler records Lua evidence', 'temp_attributes.tp' in compiler and "plan['from']" in compiler)
    check('hits_of handles all wordings', "进行\\s*(\\d+)\\s*次攻击" in extractor
          and "RE_SEGMENTS" in compiler)
    for key in ('skillPlan(', 'hitsOverride', 'factorOverride', 'extraBoost',
                'segLabel', 'ADDITIONAL_DAMAGE_BY_CONSUME', 'seg: seg.label'):
        check(f'engine settlement {key}', key in core)
    check('describeHit shows segment', '〔${h.seg}〕' in core)
    check('UI skill plan panel', 'bsim-skill-plan' in ui and '解密 speciality 依据' in ui)

    out = subprocess.run([str(NODE), '-e', ENGINE], cwd=ROOT, capture_output=True,
                         text=True, encoding='utf8', timeout=900)
    try:
        e = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        e = {}
        print(out.stdout[-1200:], out.stderr[-1500:])

    fa = e.get('facing', {})
    for n, d in fa.items():
        check(f'facing {n} front spawn', d.get('snow') == d.get('want')
              and d.get('guard') == d.get('want') and d.get('dir'),
              f"want {d.get('want')} snow={d.get('snow')} guard={d.get('guard')}")
    check('four facings tested', len(fa) == 4)

    live = e.get('live', {})
    check('walking changes facing', live.get('moved', 0) > 0, str(live.get('moved')))
    check('casting changes facing', live.get('cast', 0) > 0, str(live.get('cast')))
    check('some casts keep facing', live.get('noTurn', 0) > 0, str(live.get('noTurn')))
    check('final walking facing matches last path segment', live.get('badMove') == 0,
          str(live.get('badMove')))

    bo = e.get('boom', {})
    check('爆裂箭 is cast', bo.get('found') is True)
    check('3 base hits settled separately', bo.get('baseCount') == 3
          and bo.get('baseFactors') == [50], str(bo.get('baseFactors')))
    check('each base hit has own calc and crit', all(x >= 8 for x in bo.get('baseCalcs', []))
          and len(bo.get('baseAmounts', [])) == 3)
    ex = bo.get('extra') or {}
    check('bonus segment settled', ex.get('boost') == 60 and ex.get('factor', 0) >= 40
          and ex.get('calc', 0) >= 8, str(ex))
    check('bonus factor = 40 × consumed layers',
          ex.get('factor') == 40 * (bo.get('c') or {}).get('count', 0), str(ex.get('factor')))
    check('consumption + bonus logged', any('消耗' in x for x in bo.get('events', []))
          and any('追加伤害结算' in x for x in bo.get('events', [])))
    check('plan attached to step', bo.get('planOnStep') is True)
    check('no skipped effects / Lua unknowns in 爆裂箭 case',
          bo.get('skipped') == {} and bo.get('unknown') == {}, str(bo.get('unknown')))

    sw = e.get('sweep', {})
    check('40 cup matches clean', sw.get('done') == 40 and sw.get('err') == 0,
          str(sw.get('exceptions')))
    check('multi-hit skills settled at scale', sw.get('multiSkillCount', 0) >= 4
          and sw.get('segments', 0) >= 100, str(sw.get('topMulti')))
    check('bonus segments settle at scale', sw.get('bonus', 0) > 0, str(sw.get('bonus')))
    check('facing changes at scale', sw.get('facingChanges', 0) > 100,
          str(sw.get('facingChanges')))
    check('no Lua unknowns at scale', not sw.get('unknown'), str(sw.get('unknown')))
    check('deterministic', e.get('deterministic') is True)

    ps = e.get('planStats', {})
    check('plan dataset coverage', ps.get('plans', 0) >= 900 and ps.get('multi', 0) >= 80
          and ps.get('consume', 0) >= 100 and ps.get('bonus', 0) >= 1, str(ps))

    # browser
    errors, failed = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(offline=True, viewport={'width': 1600, 'height': 1000})
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
        page.locator('[data-spawn-pick="A:0"]').click()
        page.wait_for_timeout(150)
        page.locator('.bsim-cell[data-x="9"][data-y="3"]').first.click()
        page.wait_for_timeout(400)
        tips = {}
        for val, name in [('1,0', '东'), ('-1,0', '西'), ('0,1', '南'), ('0,-1', '北')]:
            page.locator('[data-spawn-dir="A:0"]').select_option(val)
            page.wait_for_timeout(320)
            a = page.locator('.bsim-facing-arrow').first
            d = a.get_attribute('d') if a.count() else None
            if d:
                pts = [tuple(map(float, p.split(','))) for p in
                       d.replace('M', '').replace('L', ' ').replace('Z', '').split() if ',' in p]
                tips[name] = pts[0] if pts else None
        want = {'东': (1, 0), '西': (-1, 0), '南': (0, 1), '北': (0, -1)}
        ok = all(tips.get(n) and (tips[n][0] * w[0] + tips[n][1] * w[1] > 5)
                 and abs(tips[n][0] * w[1] - tips[n][1] * w[0]) < 0.2
                 for n, w in want.items())
        check('all four spawn arrows point correctly', ok, str(tips))
        check('南 arrow no longer points north', bool(tips.get('南') and tips['南'][1] > 0),
              str(tips.get('南')))
        check('unit facing arrows drawn', page.locator('.bsim-unit-facing').count() > 0)

        page.locator('#bsim-cup-sched').select_option('22')
        page.locator('[data-cup-load="both"]').click()
        page.wait_for_timeout(1700)
        # Round 35: a 爆裂箭 whose target evades settles only the evade record,
        # so look for a cast that actually resolves its damage segments.
        found = False
        mx = int(page.locator('#bsim-range').get_attribute('max') or 0)
        for i in range(0, min(mx, 90)):
            page.evaluate("(i)=>{const r=document.querySelector('#bsim-range');r.value=String(i);r.dispatchEvent(new Event('input',{bubbles:true}));}", i)
            page.wait_for_timeout(18)
            txt = page.locator('#bsim-detail').inner_text()
            if '爆裂箭' in txt and '第 1/3 段' in txt and '追加' in txt:
                found = True
                break
        check('爆裂箭 step reachable in browser', found)
        if found:
            detail = page.locator('#bsim-detail').inner_text()
            check('step detail lists 3 segments + bonus', '第 1/3 段' in detail
                  and '第 3/3 段' in detail and '追加' in detail)
            check('skill plan panel shown', page.locator('.bsim-skill-plan').count() == 1)
            check('per-segment calculation panels', page.locator('.bsim-calc-hit').count() >= 4,
                  str(page.locator('.bsim-calc-hit').count()))
            check('facing note shown', page.locator('.bsim-facing-note').count() == 1)
        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
