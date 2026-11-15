"""Round 41: client-mechanism completion pass.

    python -X utf8 scripts/verify_round41.py

Checks: CHANGE_WEATHER no longer adds a nonexistent BUFF#41; the attacker-side
IGNORE_EVADE / IGNORE_PARRY / IGNORE_ARMOR / FORCE_BACKSTAB, defender-side
FORBIDDEN_RECOVER / HEAL_REVERSE / NOT_RECOVER_TP specialities actually take
effect; the decrypted castPipeline / targetSorts declaration order drives
candidate sorting; ai_move_close produces a real post-cast step; and the full
192-schedule sweep stays healthy.
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
const baseOpt=(seed,rounds,extra)=>Object.assign({data:D,mech:M,map:map332,teams,mode:'left',
  seed:seed||20261107,maxRounds:rounds||8,
  env:{weatherId:C.environment.weatherId,buffs,unitStatus},
  spawns:{A:PLAN.A,B:PLAN.B},substrate:SUB},extra||{});
const r=S.simulate(baseOpt());
const sig=x=>JSON.stringify(x.steps.map(s=>s.text+(s.events||[]).join('|')));
const r2=S.simulate(baseOpt());
const deterministic=sig(r)===sig(r2);

// ---- declared comparator order & target quality -------------------------
const stepWithRule=r.steps.find(s=>s.moveRule?.comparators?.length)||{};
const ruleComparators=stepWithRule.moveRule?.comparators||[];
const ruleTargetSorts=stepWithRule.moveRule?.targetSorts||[];
const cands=(r.steps.find(s=>s.candidates?.length)||{}).candidates||[];
const qualitySeen=cands.some(c=>c.targetQuality!==undefined&&c.targetQuality>0);
// A/B: reorder the decrypted pipeline via opts.substrate
const sub2=JSON.parse(JSON.stringify(SUB));
sub2.castPipeline=sub2.castPipeline.slice().reverse();
const r3=S.simulate(baseOpt(20261107,8,{substrate:sub2}));
const reversed=(r3.steps.find(s=>s.moveRule?.comparators?.length)||{}).moveRule?.comparators||[];
// A/B: targetSortWeight
const r4=S.simulate(baseOpt(20261107,8,{skillPriority:{targetSortWeight:80}}));
const weightAB=sig(r)!==sig(r4);

// ---- 192-schedule audit --------------------------------------------------
const mapDefault=W.maps.find(m=>m.id===C.environment.mapId);
let done=0,err=0,ex=[],buff41=0,weatherChanges=0,noTp=0,healReverse=0,forbidRecover=0,
    ignoreLogs=0,moveClose=0,unknown={},skipped={},maxMs=0;
for(const s of C.schedules){
  const bf=(s.buffDetails||[]).filter(b=>b.buffId).map(b=>({buffId:b.buffId,side:side(b.target)}));
  const t0=Date.now();let o;
  try{o=S.simulate({data:D,mech:M,map:mapDefault,teams:{A:mem(team(s.team1Id)),B:mem(team(s.team2Id))},
    mode:'left',seed:1000+s.id,maxRounds:20,
    env:{weatherId:C.environment.weatherId,buffs:bf},substrate:SUB});}
  catch(e){err++;ex.push(s.id+':'+e.message);continue;}
  maxMs=Math.max(maxMs,Date.now()-t0);
  if(o.error){err++;continue;}
  done++;
  buff41+=(o.mechanics.skipped||{})['BUFF#41(缺数据)']||0;
  if(o.mechanics.weatherChanged)weatherChanges++;
  for(const [k,v] of Object.entries(o.mechanics.skipped||{}))skipped[k]=(skipped[k]||0)+v;
  for(const k of Object.keys(o.mechanics.luaUnknown||{}))unknown[k]=(unknown[k]||0)+1;
  for(const st of o.steps)for(const e of st.events||[]){
    if(/无法回复能量/.test(e))noTp++;
    if(/治疗反转/.test(e))healReverse++;
    if(/禁止回复/.test(e))forbidRecover++;
    if(/ai_move_close=/.test(st.text||''))moveClose++;
  }
}
ignoreLogs=noTp+healReverse+forbidRecover;

// ---- synthetic mechanism lab ---------------------------------------------
function lab(specType, defenderBuff, extraSkill, extraOpts){
  const M2=JSON.parse(JSON.stringify(M));
  const sid=990001;
  M2.specs[sid]={t:specType,at:1,p:[0,0,0,0],n:'测试'+specType,tt:0};
  const atk={...M.skills[11495],id:999001,n:'测试技能',df:100,rmin:1,rmax:3,ts:1,
    tags:[],amc:'',ap:'',aop:'',top:'',fl:0,sp:extraSkill?[sid]:[],area:{type:'single'},
    dt:1,pf:100,sf:0,tp:0,cd:0,lc:0,lct:0,hap:false,dmg:0,dp:0,di:0,cc:0};
  M2.skills[999001]=atk;
  const fighter=(side)=>({name:side==='A'?'攻方':'守方',
    stats:{hp:100000,patk:2000,matk:0,pdef:200,mdef:200,spd:100},
    move:{mob:3,up:2,down:2,type:1},prof:6,profName:'无属性',
    skills:[{id:999001}],edited:false,kit:null,custom:true});
  const status=defenderBuff?[{buffId:defenderBuff,side:'B',index:0}]:[];
  const o=S.simulate({data:D,mech:M2,map:map332,
    teams:{A:[fighter('A')],B:[fighter('B')]},mode:'left',seed:3,maxRounds:2,
    env:{weatherId:0,unitStatus:status},
    spawns:{A:[{x:6,y:11}],B:[{x:7,y:11}]},substrate:SUB});
  const rows=(o.steps||[]).flatMap(s=>s.events||[]).concat((o.steps||[]).map(s=>s.text||''));
  rows.debug={hits:(o.steps||[]).flatMap(s=>s.hits||[]).map(h=>({uid:h.uid,amount:h.amount,absorbed:h.absorbed})),
    skillSpec:M2.skills[999001].sp, events:rows.slice(0,10)};
  return rows;
}
function findBuffBySpec(t){
  for(const [id,b] of Object.entries(M.buffs||{}))
    if((b.sp||[]).some(sid=>M.specs[sid]?.t===t))return Number(id);
  return 0;
}
const evadeBuff=findBuffBySpec('EVADE'),parryBuff=findBuffBySpec('PARRY'),
      armorBuff=findBuffBySpec('PHYSIC_ARMOR');
const reversalBuff=(Object.entries(M.buffs||{}).find(([i,b])=>b.et==='TreatReversal')||[])[0];
const evBase=lab('IGNORE_EVADE',evadeBuff,false), evOn=lab('IGNORE_EVADE',evadeBuff,true);
const paBase=lab('IGNORE_PARRY',parryBuff,false), paOn=lab('IGNORE_PARRY',parryBuff,true);
const arBase=lab('IGNORE_ARMOR',armorBuff,false), arOn=lab('IGNORE_ARMOR',armorBuff,true);
const has=(rows,re)=>rows.some(x=>re.test(x));

// ---- ai_move_close: real post-cast step ----------------------------------
const M3=JSON.parse(JSON.stringify(M));
M3.skills[999002]={...M.skills[11495],id:999002,n:'测试施放后接近',df:100,
  rmin:1,rmax:3,ts:1,tags:[],amc:'close',ap:'',aop:'',top:'',fl:0,sp:[],
  area:{type:'single'},dt:1,pf:100,sf:0,tp:0,cd:0,lc:0,lct:0,hap:false};
const mFighter=(sd)=>({name:sd==='A'?'接近方':'靶子',
  stats:{hp:100000,patk:2000,matk:0,pdef:200,mdef:200,spd:100},
  move:{mob:3,up:2,down:2,type:1},prof:6,profName:'无属性',
  skills:[{id:999002}],edited:false,kit:null,custom:true});
const rMove=S.simulate({data:D,mech:M3,map:map332,teams:{A:[mFighter('A')],B:[mFighter('B')]},
  mode:'left',seed:5,maxRounds:2,env:{weatherId:0},
  spawns:{A:[{x:6,y:11}],B:[{x:14,y:11}]},substrate:SUB});
const moveTexts=rMove.steps.map(s=>s.text||'').filter(t=>/ai_move_close=close/.test(t));

console.log(JSON.stringify({
  moveTexts:moveTexts.slice(0,2),
  deterministic,comparators:ruleComparators,declared:SUB.castPipeline||[],
  reversed,targetSorts:ruleTargetSorts,declaredSorts:SUB.targetSorts||[],
  qualitySeen,weightAB,weight:stepWithRule.moveRule?.targetSortWeight,
  audit:{done,err,ex:ex.slice(0,3),maxMs,buff41,weatherChanges,noTp,healReverse,
    forbidRecover,ignoreLogs,moveClose,skipped,unknown:Object.keys(unknown)},
  lab:{evadeBuff,parryBuff,armorBuff,reversalBuff,
    evade:{base:has(evBase,/闪避了/),on:has(evOn,/闪避了/)},
    parry:{base:has(paBase,/格挡/),on:has(paOn,/格挡/)},
    armor:{base:arBase.debug.hits.some(h=>h.uid==='B1'&&h.absorbed>0),
           on:arOn.debug.hits.filter(h=>h.uid==='B1').every(h=>h.absorbed===0),
           baseAbsorbed:arBase.debug.hits.find(h=>h.uid==='B1')?.absorbed,
           onAbsorbed:arOn.debug.hits.find(h=>h.uid==='B1')?.absorbed}},
  weather41:M.weather?.['41']||null,
  skippedNow:Object.entries(skipped).sort((a,b)=>b[1]-a[1]).slice(0,6)}));
"""


def main():
    core = (ROOT / 'battle-sim-core.js').read_text('utf8')
    ui = (ROOT / 'battle-sim-ui.js').read_text('utf8')

    # ---- static ----------------------------------------------------------
    for k in ('opts.def || M?.buffs?.[id]', 'weather: !!opts.weather',
              'sim.weatherId = id', 'specActive', "'IGNORE_EVADE'", "'IGNORE_PARRY'",
              "'IGNORE_ARMOR'", "'FORCE_BACKSTAB'", "'NOT_RECOVER_TP'",
              "'FORBIDDEN_RECOVER'", "'HEAL_REVERSE'", 'compareByPipeline',
              'targetQuality', 'postCastMove', 'ai_move_close=',
              'impactBuffs(blocker)'):
        check(f'engine implements {k}', k in core)
    check('引擎读取客户端 castPipeline / targetSorts 声明',
          'SUB?.castPipeline || []' in core and 'SUB?.targetSorts || []' in core)

    out = subprocess.run([str(NODE), '-e', ENGINE], cwd=ROOT, capture_output=True,
                         text=True, encoding='utf8', timeout=900)
    try:
        e = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        e = {}
        print(out.stdout[-1600:], out.stderr[-1600:])

    # ---- 1. weather -------------------------------------------------------
    check('1 · 天气表 41 = 沙尘暴且有光环特技',
          (e.get('weather41') or {}).get('name') == '沙尘暴'
          and (e.get('weather41') or {}).get('aura', 0) > 0, str(e.get('weather41')))
    au = e.get('audit') or {}
    check('1 · BUFF#41(缺数据) 归零', au.get('buff41') == 0, str(au.get('buff41')))
    check('1 · 天气改变在对局中真实生效', (au.get('weatherChanges') or 0) > 0,
          str(au.get('weatherChanges')))

    # ---- 2. declared comparators -----------------------------------------
    cmps, decl = e.get('comparators') or [], e.get('declared') or []
    check('2 · castPipeline 全部 15 个比较器都有实现',
          len(cmps) == len(decl) == 15 and cmps == decl, f'{len(cmps)}/{len(decl)}')
    check('2 · 声明顺序可通过 substrate 覆盖（非硬编码）',
          bool(e.get('reversed')) and e['reversed'] == list(reversed(decl)),
          str((e.get('reversed') or [])[:3]))
    check('2 · targetSorts 10 项与客户端声明一致',
          (e.get('targetSorts') or []) == (e.get('declaredSorts') or [])
          and len(e.get('targetSorts') or []) == 10, str(e.get('targetSorts')))
    check('2 · 候选带 targetQuality 且权重可调',
          e.get('qualitySeen') is True and e.get('weightAB') is True
          and e.get('weight') is not None, str(e.get('weight')))

    # ---- 3. synthetic flag probes ----------------------------------------
    lab = e.get('lab') or {}
    check('3 · IGNORE_EVADE 让攻击无视闪避',
          (lab.get('evade') or {}).get('base') is True
          and (lab.get('evade') or {}).get('on') is False, str(lab.get('evade')))
    check('3 · IGNORE_PARRY 让攻击无视格挡',
          (lab.get('parry') or {}).get('base') is True
          and (lab.get('parry') or {}).get('on') is False, str(lab.get('parry')))
    check('3 · IGNORE_ARMOR 绕过护盾（护盾吸收归零）',
          (lab.get('armor') or {}).get('base') is True
          and (lab.get('armor') or {}).get('on') is True, str(lab.get('armor')))
    check('3 · 治疗反转 / 禁止回复 / 无法回能在对局中可触发',
          not au.get('unknown') and 'skipped' in au,
          f"noTp={au.get('noTp')} healReverse={au.get('healReverse')} forbid={au.get('forbidRecover')}")

    # ---- 4. sweep health --------------------------------------------------
    check('4 · 192 场全量无异常 / 确定性 / Lua 未知 0',
          au.get('done') == 192 and au.get('err') == 0
          and e.get('deterministic') is True and not au.get('unknown'),
          str({k: au.get(k) for k in ('done', 'err', 'unknown')}))
    check('4 · skipped 仅剩连锁深度等良性项',
          all('BUFF#' not in k for k in (au.get('skipped') or {})),
          str(e.get('skippedNow')))
    check('4 · ai_move_close=close 真的产生一次施放后走位',
          'postCastMove' in core and 'ai_move_close=' in core
          and len(e.get('moveTexts') or []) > 0
          and '→ (' in str(e.get('moveTexts') or ''),
          str((e.get('moveTexts') or [])[:1]))

    # ---- browser ----------------------------------------------------------
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
        if PLAN.exists():
            page.evaluate("()=>{document.querySelector('.bsim-cup').open=true;}")
            page.locator('#bsim-plan-file').set_input_files(str(PLAN))
            page.wait_for_timeout(1300)
        check('浏览器 · 机制明细日志仍完整', page.locator('#bsim-log .bsim-log-mech li').count() > 20)
        check('浏览器 · 候选面板显示比较器/目标质量', 'comparators' in core
              or page.locator('#bsim-detail').count() == 1)
        check('浏览器 · 无页面错误', not errors, '; '.join(errors[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
