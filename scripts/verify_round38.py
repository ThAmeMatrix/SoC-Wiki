"""Round 38: 瞬发 / 极限射程 / 技能分组与放置顺序 / 警戒 2 段 / 客户端机制整改.

    python -X utf8 scripts/verify_round38.py

Uses the same spawn plan as round 37 (赛程 90 / 地图 332) plus a full 192
schedule sweep. Run after editing battle-sim-core.js / battle-sim-ui.js.
"""
import json
import subprocess
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / 'index.html').as_uri()
NODE = Path(r'C:\Users\thamechen\AppData\Local\Programs\Python\Python313\Lib\site-packages\playwright\driver\node.exe')
PLAN = Path('C:/Users/thamechen/Downloads/铃兰档案馆-站位方案-332-赛程90 (1).json')
failures = []


def check(name, ok, detail=''):
    print(('PASS ' if ok else 'FAIL ') + name + (f' :: {detail}' if detail else ''), flush=True)
    if not ok:
        failures.append(name)


ENGINE = r"""
const fs=require('fs'),vm=require('vm');const ctx={window:{},console};vm.createContext(ctx);
for(const f of ['data/world-data.js','data/battle-sim.js','data/match-cup.js','data/battle-mech.js',
                'data/client-mechanisms.js','battle-sim-core.js'])
  vm.runInContext(fs.readFileSync(f,'utf8'),ctx,{filename:f});
const W=ctx.window.WIKI_WORLD_DATA,D=ctx.window.WIKI_BATTLE_SIM,C=ctx.window.WIKI_MATCH_CUP,
      M=ctx.window.WIKI_BATTLE_MECH,SUB=ctx.window.WIKI_CLIENT_MECHANISMS,S=ctx.window.WikiBattleSim;
const mk=m=>({name:m.name,stats:m.stats,move:m.move,prof:m.profName,kit:m.kit,skills:m.skills,
  edited:false,npcId:m.npcId,star:m.star,statLevel:m.statLevel});
const team=id=>C.teams.find(t=>t.id===id),mem=t=>t.members.map(mk);
const side=t=>t===1?'A':t===2?'B':'both';
const PLAN=JSON.parse(fs.readFileSync('C:/Users/thamechen/Downloads/铃兰档案馆-站位方案-332-赛程90 (1).json','utf8')).plans[0];
const map332=W.maps.find(m=>m.id===332),sc=C.schedules.find(x=>x.id===90);
const buffs=(sc.buffDetails||[]).filter(b=>b.buffId).map(b=>({buffId:b.buffId,side:side(b.target)}));
const teams={A:mem(team(sc.team1Id)),B:mem(team(sc.team2Id))};
const unitStatus=[];
for(const st of sc.unitStatus||[]){const s=st.teamIndex===1?'A':'B';
  const i=teams[s].findIndex(m=>Number(m.npcId)===Number(st.npcId));
  if(i>=0&&st.buffId)unitStatus.push({buffId:st.buffId,side:s,index:i});}
const baseOpt=(seed,rounds)=>({data:D,mech:M,map:map332,teams,mode:'left',seed,maxRounds:rounds||8,
  env:{weatherId:C.environment.weatherId,buffs,unitStatus},spawns:{A:PLAN.A,B:PLAN.B},substrate:SUB});
const r=S.simulate(baseOpt(20261107,8));
const nameOf=uid=>(r.units.find(u=>u.uid===uid)||{}).name||'';
const manhattan=(a,b)=>Math.abs(a.x-b.x)+Math.abs(a.y-b.y);
const steps=r.steps.map((st,i)=>({i,name:nameOf(st.actor),from:st.from,to:st.to,kind:st.kind,
  skill:st.skill||null,chainIndex:st.chainIndex||0,target:st.target||null,text:st.text||'',
  alert:st.alert||null,alertHit:st.alertHit||null,candidates:st.candidates||[],
  moveRule:st.moveRule||{},events:st.events||[]}));
const anna=r.units.find(u=>u.name==='安娜'),igor=r.units.find(u=>/伊戈尔/.test(u.name));
const unitInfo=u=>u?({uid:u.uid,slotOrder:u.slotOrder,tiers:[...u.skillTier],
  instantIds:[...u.instantIds],byOrder:u.ai.byOrder}):null;
const alerts=steps.filter(s=>s.alertHit).map(s=>({owner:s.alertHit.owner,hits:s.alertHit.hits,
  forced:s.alertHit.forced,interrupts:s.alertHit.interrupts,segments:s.alertHit.segments||[],
  text:s.text,cell:s.alertHit.cell}));
const armor=steps.filter(s=>s.skill?.id===18987).map(s=>{
  const c=s.candidates.find(x=>x.id===18987)||{};
  return {stand:c.stand||null,to:s.to,target:s.target,
    dist:c.stand&&s.target?manhattan(c.stand,s.target):-1,
    castDist:c.castDist,chainIndex:s.chainIndex};});
const instantSteps=steps.filter(s=>s.skill?.instant).map(s=>({name:s.name,skill:s.skill.name,
  instant:s.skill.instant,tier:s.skill.tier,slot:s.skill.slot,chainIndex:s.chainIndex}));
const chainPairs=[];
for(let i=0;i<steps.length-1;i++){
  if(steps[i].skill?.instant && steps[i+1].chainIndex>0 && steps[i+1].name===steps[i].name)
    chainPairs.push({first:steps[i].skill.name,next:steps[i+1].skill?.name||steps[i+1].kind,
      chainIndex:steps[i+1].chainIndex,text:steps[i+1].text.slice(0,220)});
}
const forceStopEvents=steps.flatMap(s=>s.events.filter(e=>/被强制停止|行动被打断/.test(e)));
const phantomSecondCast=steps.flatMap(s=>s.events.filter(e=>/发动「CloneCloneClone」/.test(e)));
const annaAlert=steps.find(s=>s.alert&&s.name==='安娜')?.alert||null;

// A/B: 技能放置顺序 must decide a near-tie between two carried skills.
const runOrder=(slotOrder)=>{
  const o=baseOpt(20261107,3);
  o.teams=JSON.parse(JSON.stringify(teams));
  o.teams.B[5]=Object.assign({},o.teams.B[5],{slotOrder});
  // Isolate the 技能放置顺序 A/B: with the round-40 instant-first rule ON,
  // 应急护甲 (a [瞬发] skill) would win both runs as a free first action.
  o.skillPriority={personality:0,carried:0,basic:0,tierStep:0,slotStep:5000,
                   instantBonus:0,instantFirst:false};
  const out=S.simulate(o);
  const first=out.steps.find(s=>s.actor==='B6');
  return {skill:first?.skill?.name||first?.kind||null,rule:first?.moveRule?.slotOrder||[],
          prio:first?.moveRule?.skillPriority||{},cands:(first?.candidates||[]).map(c=>({skill:c.skill,priority:c.priority,slot:c.slot}))};
};
const orderA=runOrder([18984,18987,4169]),orderB=runOrder([18987,18984,4169]);

// Synthetic 1v1: a skill with one client ADDITIONAL_ATTACK link to a pure
// damage skill must settle as TWO segments (安娜 警戒 2 × 35%), not as a
// phantom second cast; and a 个性 role must reach the personality tier.
const M2=JSON.parse(JSON.stringify(M));
M2.skills[999001]=Object.assign({},M.skills[19204],{id:999001,n:'测试二段',ty:1,st:6,ct:5,
  df:35,rmin:1,rmax:3,rt:1,tw:1,sp:[999002],desc:'（物理伤害）测试二段',aim:'enemy',
  area:{type:'single'},dt:1,pf:100,sf:0,tp:0,cd:0,lc:0,lct:0,hap:false,ap:''});
M2.specs[999002]={t:'ADDITIONAL_ATTACK',at:3,p:[999003,0,1,0],n:'测试第二段',tt:3};
M2.skills[999003]=Object.assign({},M.skills[19642],{id:999003,n:'测试第二段技能',df:35,sp:[],ty:1});
const synthetic=(roles)=>({name:'测试单位',stats:{hp:10000,patk:1000,matk:0,pdef:0,mdef:0,spd:100},
  move:{mob:3,up:2,down:2,type:1},prof:6,profName:'无属性',skills:[{id:999001}],
  edited:false,kit:null,custom:true,skillRoles:roles});
const syn=S.simulate({data:D,mech:M2,map:map332,
  teams:{A:[synthetic(null)],B:[synthetic({999001:'个性'})]},mode:'left',seed:7,maxRounds:1,
  env:{},spawns:{A:[{x:6,y:11}],B:[{x:5,y:10}]},substrate:SUB});
const synHit=syn.steps.find(s=>s.skill?.id===999001);
const syntheticResult={error:syn.error||null,hits:(synHit?.hits||[]).map(h=>({seg:h.seg,amount:h.amount})),
  tiers:[...new Set((syn.units||[]).flatMap(u=>[...(u.skillTier||[])].map(x=>x[1])))],
  // A sub-cast logs 「发动「测试第二段技能」」; the segment label 第 2/2 段
  // is now also printed by the numeric damage trace and is NOT a sub-cast.
  events:(synHit?.events||[]).filter(e=>/发动「测试第二段技能」/.test(e))};

// 192-match sweep
const mapDefault=W.maps.find(m=>m.id===C.environment.mapId);
let done=0,err=0,ex=[],alertsN=0,alertSegments=0,instantN=0,chainN=0,armorN=0,armorRim=0,maxMs=0;
const armorDists=[];let armorRimOk=0;
const unknown={},skipped={};
for(const s of C.schedules){
  const bf=(s.buffDetails||[]).filter(b=>b.buffId).map(b=>({buffId:b.buffId,side:side(b.target)}));
  const t0=Date.now();let o;
  try{o=S.simulate({data:D,mech:M,map:mapDefault,
    teams:{A:mem(team(s.team1Id)),B:mem(team(s.team2Id))},mode:'left',seed:1000+s.id,maxRounds:20,
    env:{weatherId:C.environment.weatherId,buffs:bf},substrate:SUB});}
  catch(e){err++;ex.push(s.id+':'+e.message);continue;}
  maxMs=Math.max(maxMs,Date.now()-t0);
  if(o.error){err++;continue;}
  done++;
  for(const st of o.steps){
    if(st.alertHit){alertsN++;if((st.alertHit.segments||[]).length>=2)alertSegments++;}
    if(st.skill?.instant)instantN++;
    if(st.chainIndex>0)chainN++;
    if(st.skill?.id===18987){armorN++;const c=(st.candidates||[]).find(x=>x.id===18987)||{};const d=c.castDist??-1;armorDists.push(d);if(d===5)armorRim++;if(c.castRim!=null&&c.castRim===d)armorRimOk++;}
  }
  for(const [k,v] of Object.entries(o.mechanics.skipped||{}))skipped[k]=(skipped[k]||0)+v;
  for(const [k,v] of Object.entries(o.mechanics.luaUnknown||{}))unknown[k]=(unknown[k]||0)+v;
}
const a=S.simulate(baseOpt(20261107,3)),b=S.simulate(baseOpt(20261107,3));
const sig=x=>JSON.stringify(x.steps.map(s=>s.text+(s.events||[]).join('|')));
console.log(JSON.stringify({steps:steps.slice(0,30),alerts,armor,instantSteps,chainPairs,
  forceStopEvents,phantomSecondCast,annaAlert,anna:unitInfo(anna),igor:unitInfo(igor),
  orderA,orderB,syntheticResult,
  sweep:{done,err,ex:ex.slice(0,3),maxMs,alertsN,alertSegments,instantN,chainN,armorN,armorRim,armorRimOk,armorDists,
    unknown:Object.entries(unknown).sort((x,y)=>y[1]-x[1]).slice(0,4),
    skipped:Object.entries(skipped).sort((x,y)=>y[1]-x[1]).slice(0,4)},
  deterministic:sig(a)===sig(b)}));
"""


def main():
    core = (ROOT / 'battle-sim-core.js').read_text('utf8')
    ui = (ROOT / 'battle-sim-ui.js').read_text('utf8')
    css = (ROOT / 'refinements.css').read_text('utf8')

    # ---- static: client-derived mechanisms actually implemented ---------
    for k in ('isInstant', 'NEGATED_INSTANT', 'MAX_INSTANT_CHAIN', 'actOnce',
              'instantUsed', 'slotOrder', 'skillTier', 'instantIds', 'linkedSpecs',
              'interrupts', 'castDist', 'specsSkillRange', 'SKILL_PRIO',
              # Round 56: runSkillSpecs gained an optional `aoeUnits` argument
              # (head-AOE marker expansion). Match the stable prefix, not the
              # whole parameter list.
              'DEFAULT_SKILL_PRIORITY', 'runSkillSpecs(skill, caster, at, ctx, skip',
              'function decide(unit, reachOverride) {'):
        check(f'engine implements {k}', k in core)
    for k in ('data-slot-up', 'data-slot-down', 'data-prio', 'data-prio-reset',
              'skillSlotRows', 'skillPriority', 'chainInfo', 'bsim-instant-note',
              'TIER_LABEL', 'castDist'):
        check(f'UI exposes {k}', k in ui)
    for k in ('.bsim-instant-note', '.bsim-slot-row', '.bsim-skill-prio'):
        check(f'CSS defines {k}', k in css)
    check('警戒不再把「警戒强化」当打断',
          "state.interrupts" in core and "state.strengthened;\n          const forced" not in core)
    check('极限射程选位按射程外环', 'const rim = best.filter(c => castDist(c) >= maxDist - 0.01);' in core)

    out = subprocess.run([str(NODE), '-e', ENGINE], cwd=ROOT, capture_output=True,
                         text=True, encoding='utf8', timeout=900)
    try:
        e = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        e = {}
        print(out.stdout[-1500:], out.stderr[-1500:])

    steps = e.get('steps') or []
    alerts = e.get('alerts') or []
    armor = e.get('armor') or []

    # ---- 1. 安娜的警戒：每次 2 段、不打断 -------------------------------
    check('1 · 展开警戒标出「每次 2 段伤害」且标注不打断',
          bool(e.get('annaAlert')) and e['annaAlert'].get('hits') == 2
          and e['annaAlert'].get('interrupts') is False
          and e['annaAlert'].get('strengthened') is True,
          str(e.get('annaAlert')))
    check('1 · 每次警戒触发都是 2 段', bool(alerts) and all(a['hits'] == 2 for a in alerts),
          str(alerts[:2]))
    check('1 · 安娜警戒不打断行动', bool(alerts) and all(
        a['forced'] is False and a['interrupts'] is False for a in alerts), str(alerts[:2]))
    check('1 · 没有「被强制停止 / 行动被打断」日志', not e.get('forceStopEvents'),
          str(e.get('forceStopEvents')[:2]))
    check('1 · ADDITIONAL_ATTACK 第二段并入同一技能，不再幻影子施放',
          not e.get('phantomSecondCast'), str(e.get('phantomSecondCast')[:2]))
    syn = e.get('syntheticResult') or {}
    check('1 · 合成对局：链接技能结算为 2 个独立伤害段',
          not syn.get('error') and len(syn.get('hits') or []) == 2
          and all('段' in str(h.get('seg')) for h in syn['hits']),
          str(syn))
    check('1 · 合成对局：不再把链接技能当子施放',
          not syn.get('events'), str(syn.get('events')))

    # ---- 2. 极限距离施放 ------------------------------------------------
    check('2 · 应急护甲确有施放', bool(armor), str(armor[:2]))
    check('2 · 每次应急护甲都站在射程极限 5 格',
          bool(armor) and all(a['dist'] == 5 and a['castDist'] == 5 for a in armor),
          str(armor[:4]))

    # ---- 3. [瞬发] 不结束行动 -------------------------------------------
    ins = e.get('instantSteps') or []
    check('3 · 客户端 [瞬发] 技能被识别（烟幕游击 / 应急护甲）',
          {'烟幕游击', '应急护甲'} <= {x['skill'] for x in ins}, str(ins[:4]))
    check('3 · 瞬发技能带分组 / 槽位信息',
          all(set(('tier', 'slot', 'instant')) <= set(x) for x in ins), str(ins[:2]))
    check('3 · 瞬发后同回合继续走或继续放技能', bool(e.get('chainPairs')),
          str(e.get('chainPairs')[:3]))
    check('3 · 后续阶段文案标明「瞬发后继续行动」',
          all('瞬发后继续行动' in x['text'] for x in (e.get('chainPairs') or [])),
          str(e.get('chainPairs')[:2]))
    check('3 · 瞬发技能不重复施放（阶段上限内）',
          all(x['chainIndex'] <= 3 for x in steps), 'chainIndex cap')

    # ---- 4. 分组优先级 + 技能放置顺序 -----------------------------------
    ig = e.get('igor') or {}
    check('4 · 单位按个性 / 普攻 / 携带技能分组',
          {'basic', 'carried'} <= {t for _, t in ig.get('tiers', [])}, str(ig.get('tiers')))
    check('4 · 个性角色标记能进入 personality 分组',
          'personality' in (e.get('syntheticResult') or {}).get('tiers', []),
          str((e.get('syntheticResult') or {}).get('tiers')))
    check('4 · 候选带分组、槽位、瞬发与施法距离',
          any(all(k in c for k in ('tier', 'slot', 'instant', 'castDist'))
              for s in steps for c in s.get('candidates', [])), 'candidates')
    check('4 · 默认放置顺序取自客户端 skill_orders',
          ig.get('slotOrder', [])[:2] == [18984, 18987], str(ig.get('slotOrder')))
    oa, ob = e.get('orderA') or {}, e.get('orderB') or {}
    check('4 · 自定义放置顺序传进引擎', ob.get('rule')[:2] == [18987, 18984], str(ob.get('rule')))
    check('4 · 优先级参数可调整', (oa.get('prio') or {}).get('slotStep') == 5000,
          str(oa.get('prio')))
    check('4 · 调换技能槽位改变同分技能的胜者',
          bool(oa.get('skill')) and bool(ob.get('skill')) and oa['skill'] != ob['skill'],
          f"A={oa.get('skill')} B={ob.get('skill')}")

    # ---- 5. 全量回归 ----------------------------------------------------
    sw = e.get('sweep') or {}
    check('5 · 192 场全量无异常', sw.get('done') == 192 and sw.get('err') == 0, str(sw.get('ex')))
    check('5 · 无 Lua 未知条件', not sw.get('unknown'), str(sw.get('unknown')))
    check('5 · 全量瞬发 / 后续阶段均生效',
          (sw.get('instantN') or 0) > 20 and (sw.get('chainN') or 0) > 20,
          f"instant={sw.get('instantN')} chain={sw.get('chainN')}")
    check('5 · 全量警戒按 2 段结算', (sw.get('alertSegments') or 0) > 0,
          f"alerts={sw.get('alertsN')} segments={sw.get('alertSegments')}")
    dists = sw.get('armorDists') or []
    check('5 · 全量应急护甲都从可达射程外环施放',
          bool(dists) and sw.get('armorRimOk') == sw.get('armorN')
          and min(dists) >= 1 and (sw.get('armorRim') or 0) >= len(dists) * 0.6,
          f"armor={sw.get('armorN')} outerRing={sw.get('armorRimOk')} at5={sw.get('armorRim')} dists={sorted(set(dists))}")
    check('5 · 确定性保持', e.get('deterministic') is True)

    # ---- browser ---------------------------------------------------------
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        c = browser.new_context(offline=True, viewport={'width': 1600, 'height': 1000})
        page = c.new_page()
        page.set_default_timeout(40000)
        page.on('pageerror', lambda x: errors.append(str(x)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.goto(BASE + '#/tools/battle')
        page.locator('#bsim-board svg').wait_for()
        check('浏览器 · 技能优先级面板存在', page.locator('#bsim-skill-prio').count() == 1)
        check('浏览器 · 三组优先级输入存在', page.locator('[data-prio]').count() == 6,
              str(page.locator('[data-prio]').count()))
        if PLAN.exists():
            page.evaluate("()=>{document.querySelector('.bsim-cup').open=true;}")
            page.locator('#bsim-plan-file').set_input_files(str(PLAN))
            page.wait_for_timeout(1200)
            page.locator('[data-edit="B:5"]').click()
            page.wait_for_timeout(300)
            rows = page.locator('.bsim-slot-row')
            check('浏览器 · 角色编辑器列出技能放置顺序', rows.count() >= 2, str(rows.count()))
            first_before = rows.nth(0).inner_text()
            page.locator('[data-slot-down="0"]').click()
            page.wait_for_timeout(200)
            first_after = page.locator('.bsim-slot-row').nth(0).inner_text()
            check('浏览器 · ↑/↓ 可调整技能放置顺序', first_before != first_after,
                  f'{first_before[:50]} -> {first_after[:50]}')
            page.locator('[data-editor-save]').click()
            page.wait_for_timeout(900)
            check('浏览器 · 保存后重算且无报错', page.locator('#bsim-range').count() == 1)
            mx = int(page.locator('#bsim-range').get_attribute('max') or 0)
            found_instant = False
            for i in range(0, min(mx, 10)):
                page.evaluate("(i)=>{const r=document.querySelector('#bsim-range');r.value=String(i);r.dispatchEvent(new Event('input',{bubbles:true}));}", i)
                page.wait_for_timeout(20)
                if '[瞬发]' in page.locator('#bsim-detail').inner_text():
                    found_instant = True
                    break
            check('浏览器 · 只调顺序仍保留客户端技能（瞬发生效）', found_instant)
            page.evaluate("()=>{document.querySelector('#bsim-skill-prio').open=true;}")
            page.locator('[data-prio="slotStep"]').fill('30')
            page.locator('[data-prio="slotStep"]').dispatch_event('change')
            page.wait_for_timeout(900)
            check('浏览器 · 优先级调整后重算', page.locator('[data-prio="slotStep"]').input_value() == '30')
        check('浏览器 · 无页面错误', not errors, '; '.join(errors[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
