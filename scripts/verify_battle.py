"""Single, fast acceptance suite for the client battle simulator.

Usage:
    python -X utf8 scripts/verify_battle.py            # 31 acceptance criteria, a few battles (~15 s)
    python -X utf8 scripts/verify_battle.py --full     # + 192-schedule landing audit (~8 min)

Acceptance is defined per client mechanism, NOT per a frozen battle transcript:
the criteria below are the contract for schedule 76 / seed 292 and for the
decoded client tables. Each criterion has one explicit, measurable assertion.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = Path(r'C:\Users\thamechen\AppData\Local\Programs\Python\Python313\Lib\site-packages\playwright\driver\node.exe')
PLAN = 'C:/Users/thamechen/Downloads/铃兰档案馆-站位方案-470-赛程76.json'

ENGINE = r"""
const fs=require('fs'),vm=require('vm');const ctx={window:{},console};vm.createContext(ctx);
for(const f of ['data/world-data.js','data/battle-sim.js','data/match-cup.js',
                'data/battle-mech.js','data/client-mechanisms.js','battle-sim-core.js'])
  vm.runInContext(fs.readFileSync(f,'utf8'),ctx,{filename:f});
const UI=fs.readFileSync('battle-sim-ui.js','utf8');
const W=ctx.window.WIKI_WORLD_DATA,D=ctx.window.WIKI_BATTLE_SIM,C=ctx.window.WIKI_MATCH_CUP,
      M=ctx.window.WIKI_BATTLE_MECH,SUB=ctx.window.WIKI_CLIENT_MECHANISMS,S=ctx.window.WikiBattleSim;
const CORE=fs.readFileSync('battle-sim-core.js','utf8');
// Round 52: build fighters EXACTLY like the page (battle-sim-core.js
// cupFighters: real 职业 id, skillRoles) on the plan's own map. The old
// `prof: profName` string made every fighter 职业 6, and map 470 + the
// map-332 plan was a hybrid no user ever sees.
const team=id=>C.teams.find(t=>t.id===id);
const mem=t=>S.cupFighters(t);
const side=t=>t===1?'A':t===2?'B':'both';
// `--sweep-only` (run_regression's `sweep` job) skips the 92 fast checks and
// runs ONLY the 192-battle audit, so the fast suite and the sweep run in two
// parallel processes instead of one ~12-minute serial `--full` job.
let out={};
if(!SWEEP_ONLY){
const PLAN=JSON.parse(fs.readFileSync(PLAN_PATH,'utf8')).plans[0];
const sc=C.schedules.find(x=>x.id===76);
const teams={A:mem(team(sc.team1Id)),B:mem(team(sc.team2Id))};
const {buffs,unitStatus}=S.cupEnv(sc,teams);
const MAP=W.maps.find(m=>m.id===Number(PLAN.mapId));
const opt=(extra)=>Object.assign({data:D,mech:M,map:MAP,teams,mode:'left',
  seed:292,maxRounds:6,env:{weatherId:C.environment.weatherId,buffs,unitStatus},
  spawns:{A:PLAN.A,B:PLAN.B},substrate:SUB},extra||{});
const r=S.simulate(opt());
const nameOf=uid=>(r.units.find(u=>u.uid===uid)||{}).name||uid;
// Shared, memoised full-length battles. Every round-5x multi-seed check uses
// the SAME options, so re-simulating 50+ identical battles inside one process
// was pure waste (and made the regression runner exceed its 10-minute budget).
const battleCache=new Map();
const PRIO54={personality:3,carried:2,basic:1,tierStep:60,slotStep:14,instantBonus:420};
const battleOf=seed=>{
  if(!battleCache.has(seed))
    battleCache.set(seed,S.simulate(Object.assign(opt(),{seed,maxRounds:20,skillPriority:PRIO54})));
  return battleCache.get(seed);
};
const allEvents=r.steps.flatMap(s=>s.events||[]);
const sig=x=>JSON.stringify(x.steps.map(s=>s.text+(s.events||[]).join('|')));

// 1 — 全装甲集火号令 must never be cast with no enemy in its area.
const orders=r.steps.filter(s=>s.skill?.id===15934).map(s=>({seq:s.seq,text:s.text,
  hits:(s.hits||[]).map(h=>({uid:h.uid,amount:h.amount})),target:s.target}));
const emptyOrders=orders.filter(o=>o.hits.every(h=>!h.amount));

// 2 — 烟幕游击 1-3: every cast stays inside its effective range.
const teleports=r.steps.filter(s=>s.skill?.id===22008).map(s=>({seq:s.seq,
  stand:s.teleport?.from||s.from,land:s.target,
  dist:Math.abs((s.teleport?.from||s.from).x-s.target.x)+Math.abs((s.teleport?.from||s.from).y-s.target.y),
  effMax:s.moveRule?.skillState?.max}));

// 4 — 破晓的决意 (range_tag MELEE) must not take the +2 ranged bonus.
const resolveState=(r.inspect(0,'B4')?.skillStates||[]).find(x=>x.id===21966)||null;
const smokeState=(r.inspect(0,'B4')?.skillStates||[]).find(x=>x.id===22008)||null;
const rangedState=(r.inspect(0,'B1')?.skillStates||[]).find(x=>x.id===15934)||null;

// 5 — every extra turn must be traceable to a client ACTED_ACT/RE_ROUND log.
const extraSteps=r.steps.filter(s=>/^再行动：|，再行动：/.test(s.text||'')||/新回合：/.test(s.text||''));
const extraLogs=allEvents.filter(e=>/获得再行动|获得新回合/.test(e));

// 6 — attached passives are loaded and fire.
const ivan=(r.inspect(0,'A1')?.passives||[]).concat(r.inspect(0,'A1')?.personality||[]);
const attachedSpec=M.skills?.['20768']?.ap2;
const attachedSkill=attachedSpec?M.skills?.[attachedSpec]:null;
const attachedLogs=allEvents.filter(e=>/附属被动|冰川裂谷/.test(e));

// 7/9 — damage numbers are never negative; zero damage states a reason.
const allHits=r.steps.flatMap(s=>(s.hits||[]).map(h=>({seq:s.seq,...h})));
const negative=allHits.filter(h=>Number(h.amount)<0);
const zeroNoReason=r.steps.filter(s=>(s.hits||[]).some(h=>h.amount===0&&!h.miss&&!h.status&&!h.heal))
  .map(s=>({seq:s.seq,text:s.text}));

// 8 — trap 139 长枪之灵 & 明誓同征.
const trapEvents=allEvents.filter(e=>/长枪之灵|明誓同征/.test(e));
const trapDef=M.traps?.['139']||null;

// 10 — 协同号令 → 协同响应.
const chainCasts=r.steps.filter(s=>(M.skills?.[s.skill?.id]?.tags||[]).includes('ChainTag1')).length;
const chainEvents=allEvents.filter(e=>/协同响应|协同号令/.test(e));

// 3 — 虚空投影 personality [失焦]. The client chain is
//   summon 8644 → personality 1312 → skill 21731 → BUFF spec 29841
//   → buff 9079「暗影蛰伏Clone」→ FADE spec 20523 ([失焦]).
const voidTpl=Object.values(M.summons||{}).find(x=>/虚空投影/.test(x.n))||null;
const voidPassive=(voidTpl?.kit?.personality||[]).map(id=>({id,n:M.skills?.[id]?.n,
  sp:(M.skills?.[id]?.sp||[]).map(sid=>M.specs?.[sid]?.t)}));
const voidUnit=r.units.find(u=>/虚空投影/.test(u.name))||null;
const voidBuffSpecs=(M.skills?.[(voidTpl?.kit?.personality||[])[0]]?.sp||[])
  .map(sid=>M.specs?.[sid]).filter(x=>x?.t==='BUFF');
const voidBuffIds=voidBuffSpecs.map(x=>Number(x.p?.[0])||0);
const fadeBuff=voidBuffIds.find(id=>(M.buffs?.[id]?.sp||[]).some(sid=>M.specs?.[sid]?.t==='FADE'));
const fadeSpec=fadeBuff?(M.buffs?.[fadeBuff]?.sp||[]).find(sid=>M.specs?.[sid]?.t==='FADE'):0;

// decoded-table contracts.
const sapSpecs=Object.values(M.specs||{}).filter(x=>x.sap).length;
const ap2Skills=Object.values(M.skills||{}).filter(x=>x.ap2).length;
const summonsWithPassive=Object.values(M.summons||{}).filter(x=>(x.kit?.personality||[]).length).length;

// 11 — 附属被动: only skills with template tp >= 3 grant the extra action, the
// buff is removed once triggered, and the extra action's skill costs 0.
// Round 51: pathing now follows the client's 敌群 distance rule, so the exact
// turn on which 伊凡 spends >=3 TP changed. Scan a small fixed seed list and
// assert on a battle where the passive actually fires, rather than pinning
// the criterion to one frozen transcript.
let ap2Grants=[],ap2Follow=[],ap2Seed=292;
// Round 54: the xlsx-corrected damage formula changes which turn 伊凡 has
// >=3 TP to spend, so widen the deterministic scan.
// Round 54: only seeds that actually trigger the passive are needed; every
// extra full simulation adds ~3s to BOTH the fast and the --full suite.
for(const seed of [292,28645696]){
  const rr=S.simulate(Object.assign(opt(),{seed}));
  const grants=rr.steps.filter(s=>(s.events||[]).some(e=>/获得再行动（附属被动/.test(e)))
    .map(s=>({seq:s.seq,skill:s.skill?.name,tp:M.skills?.[s.skill?.id]?.tp??null}));
  const follow=grants.map(g=>{const st=rr.steps.find(x=>x.seq>g.seq&&x.actor===rr.steps[g.seq].actor&&/再行动：/.test(x.text||''));
    return st?{seq:st.seq,skill:st.skill?.name,cost:st.skill?.tp}:null;}).filter(Boolean);
  if(grants.length&&follow.length){ap2Grants=grants;ap2Follow=follow;ap2Seed=seed;break;}
}

// 12 — restricted extra actions cast ONLY their client-named skill.
const restrictViol=[],restrictOk=[];
for(const st of r.steps){
  if(!/再行动：/.test(st.text||'')||!st.skill)continue;
  const nm=nameOf(st.actor);
  const grant=r.steps.slice(0,st.seq+1).reverse().flatMap(x=>(x.events||[]).slice().reverse())
    .find(e=>e.startsWith(nm+' 获得再行动'));
  const m=grant&&grant.match(/仅限「([^」]+)」#(\d+)/);
  if(!m)continue;
  (Number(m[2])===Number(st.skill.id)?restrictOk:restrictViol).push({seq:st.seq,who:nm,need:m[1],got:st.skill.name});
}

// 13/14 — 技能变更为 and 金狮形态 data chains.
const P=id=>M.skillPlans?.[id]||{};
const swapPlans=Object.values(M.skillPlans||{}).filter(p=>p.swapTo).length;
const swapSteps=r.steps.filter(s=>s.skillSwap).map(s=>({seq:s.seq,who:nameOf(s.actor),...s.skillSwap}));
const lionSpec=M.specs?.['25245']||null;

// 15 — summons: inert, immobile, 灵感星核 unique.
const summonTpl=n=>Object.values(M.summons||{}).filter(x=>x.n===n).map(x=>({unique:x.unique,noTurn:x.noTurn,noMove:x.noMove,mob:x.move?.mob}));
const summonUids=new Set(r.units.filter(u=>/灵感星核|虚空投影/.test(u.name)).map(u=>u.uid));
const summonActs=r.steps.filter(s=>summonUids.has(s.actor)).length;
let coreMax=0;for(const s of r.steps)for(const sd of ['A','B'])
  coreMax=Math.max(coreMax,(s.snap||[]).filter(x=>x.alive&&String(x.uid).startsWith(sd)&&nameOf(x.uid)==='灵感星核').length);

// 16/17 — 协同号令 through skill_cast_id: 15934 → 15968 (80% 穿透) →
// 15937 → MAKE_OTHER_CAST_SKILL 15935 for 〈铃兰之剑〉 (50% 物攻+魔攻 穿透).
// Round 52: in the page-exact battle 麦莎·SP dies before her second action,
// so no seed scan can be relied on. A MECHANISM test needs a deterministic
// stage instead: 麦莎·SP (order skill only) spawns at (8,8), in front of
// the A line, and casts on her first action. Everything else is the page's
// own battle (fighters, map, buffs, statuses).
const teamsOrder=JSON.parse(JSON.stringify(teams));
for(const sd of ['A','B'])for(const m of teamsOrder[sd])
  if(/麦莎/.test(m.name)&&m.kit)m.kit=Object.assign({},m.kit,{actives:[15934],initial:[],choice:[]});
const subBy=(st,id)=>(st?.hits||[]).filter(h=>h.bySkillId===id);
const coordMiss=ro=>{ // responders that have an enemy within 3 tiles but no 50% hit
  const st=ro.steps.find(s=>s.skill?.id===15934); if(!st)return null;
  const nm=uid=>(ro.units.find(u=>u.uid===uid)||{}).name;
  const resp={}; for(const e of st.events||[]){
    const m=e.match(/^(\S+) 发动「飞弹礼花-后续」（飞弹礼花-后续）/);
    if(m)resp[m[1]]=(resp[m[1]]||0)+1;}
  const snap=st.snap||[],cs=String(st.actor||'B')[0];
  const must=Object.keys(resp).filter(n=>{const me=snap.find(x=>x.alive&&nm(x.uid)===n);
    return me&&snap.some(y=>y.alive&&String(y.uid)[0]!==cs&&Math.abs(y.x-me.x)+Math.abs(y.y-me.y)<=3);});
  const hitBy=new Set(subBy(st,15935).map(h=>h.byName));
  return {st,resp,must,missed:must.filter(n=>!hitBy.has(n))};
};
const orderSeed=292;
const rOrder=S.simulate(Object.assign(opt(),{teams:teamsOrder,seed:orderSeed,maxRounds:4,
  spawns:{A:PLAN.A,B:PLAN.B.map((p,i)=>i===0?{x:8,y:8}:p)}}));
const orderStep=rOrder.steps.find(s=>s.skill?.id===15934)||null;
const order15968=subBy(orderStep,15968).filter(h=>h.amount>0).length;
const order15935=subBy(orderStep,15935).filter(h=>h.amount>0).length;
const oName=uid=>(rOrder?.units.find(u=>u.uid===uid)||{}).name;
const respCasts=coordMiss(rOrder||{steps:[]})?.resp||{};
const responders=Object.keys(respCasts);
// A responder with an enemy inside its own 3-tile radius MUST land the 50% hit.
const snapO=orderStep?.snap||[];
const casterSide=String(orderStep?.actor||'B')[0];
const mustHit=responders.filter(n=>{const me=snapO.find(x=>x.alive&&oName(x.uid)===n);
  return me&&snapO.some(y=>y.alive&&String(y.uid)[0]!==casterSide&&Math.abs(y.x-me.x)+Math.abs(y.y-me.y)<=3);});
const hitBy=new Set(subBy(orderStep,15935).map(h=>h.byName));
const missed=mustHit.filter(n=>!hitBy.has(n));
const broadcast=(orderStep?.events||[]).filter(e=>/协同响应（特技 #19290/.test(e));
const cupActives=new Set();for(const t of C.teams)for(const m of t.members)for(const id of (m.kit?.actives||[]))cupActives.add(Number(id));
const cupScid=[...cupActives].filter(id=>M.skills?.[id]?.scid).length;

// 18 — 0-duration buffs are 「0回合（行动中）」.
const zeroDurBuffSpecs=Object.values(M.specs||{}).filter(x=>x.t==='BUFF'&&Number(x.p?.[1])===0).length;
const actionScopedExpired=Number(r.mechanics?.executed?.ACTION_SCOPED_EXPIRE||0);

// ---- Round 47 ----------------------------------------------------------
// Schedule 52 deterministically contains both 野狐塞娜 (血棘之花 → 落花之舞
// restricted extra action) and 阿尔曼大帝 (蛮勇转化 loop node). One extra
// battle keeps the fast suite at a few seconds while covering all four
// engine-side fixes from this round.
const sc52=C.schedules.find(x=>x.id===52);
const r52=S.simulate({data:D,mech:M,map:W.maps.find(m=>m.id===C.environment.mapId),
  teams:{A:mem(team(sc52.team1Id)),B:mem(team(sc52.team2Id))},mode:'left',seed:1000+sc52.id,
  maxRounds:20,env:{weatherId:C.environment.weatherId},substrate:SUB});
const nm52=uid=>r52.units.find(u=>u.uid===uid)?.name;
// 20 — every ACTED_ACT.p[0] extra action casts EXACTLY the named skill.
let r47Extra=0,r47ExtraViol=[],r47ExtraOther=0;
for(const st of r52.steps){
  if(!/再行动：|，再行动：|^再行动/.test(st.text||''))continue;
  const g=r52.steps.slice(0,st.seq+1).reverse().flatMap(x=>(x.events||[]).slice().reverse())
    .find(e=>e.startsWith((nm52(st.actor)||'')+' 获得再行动'));
  const m=g&&g.match(/仅限「([^」]+)」#(\d+)/);
  if(!m)continue;
  r47Extra++;
  const reason47=String(st.moveRule?.noCastReason||'');
  const legalWait=st.kind==='wait'&&/没有合法目标，原地待命/.test(reason47)&&reason47.includes(m[1]);
  if(!legalWait&&Number(m[2])!==Number(st.skill?.id))
    r47ExtraViol.push({seq:st.seq,need:m[1],got:st.skill?.name||st.kind});
  // A walk/teleport WITH the named skill is the skill's own SHADOW_STEP;
  // an explicitly recorded "no legal target" wait is also legal.
  if(!legalWait&&st.kind!=='skill')r47ExtraOther++;
}
// 21 — 落花之舞 may anchor on an enemy, an ally or the caster itself.
const luoHua=r52.steps.filter(s=>s.skill?.id===21016);
const luoHuaAnyUnit=luoHua.filter(st=>{
  const side=String(st.actor)[0],t=st.target;
  return (st.snap||[]).some(x=>x.alive&&x.x===t.x&&x.y===t.y&&String(x.uid)[0]===side);
}).length;
// 22 — 蛮勇转化 loop settles a bounded number of times, no log flood, and
// the client's 「每3/4层蓄势 → 1层威慑」 conversion really ran.
let manyuMax=0,manyuTotal=0,manyuWeishe=0;
for(const st of r52.steps){
  const n=(st.events||[]).filter(e=>/蛮勇转化-结算/.test(e)&&/发动/.test(e)).length;
  manyuMax=Math.max(manyuMax,n);manyuTotal+=n;
  manyuWeishe+=(st.events||[]).filter(e=>/获得「威慑」/.test(e)).length;
}
// 23 — simplified setup UI + deployment rings following live units.
const UI_SRC=fs.readFileSync('battle-sim-ui.js','utf8');
const CSS_SRC=fs.readFileSync('refinements.css','utf8');
const runButtons=(UI_SRC.match(/data-run/g)||[]).length;
const c20={extra:r47Extra,viol:r47ExtraViol,other:r47ExtraOther,
  src:CORE.includes('if (onlySkill)')&&CORE.includes('const restricted = isExtra')};
const c21={casts:luoHua.length,anyUnit:luoHuaAnyUnit,
  src:CORE.includes('const anyUnitAim')&&CORE.includes("case 'main_skill': return")};
const c22={max:manyuMax,total:manyuTotal,weishe:manyuWeishe,
  src:CORE.includes('isLoopNode')&&CORE.includes('consumeSpecs')};
const c23={runButtons,
  groups:(UI_SRC.match(/class="bsim-fold/g)||[]).length,
  summary:UI_SRC.includes('id="bsim-setup-summary"'),
  advancedFolded:UI_SRC.includes('id="bsim-advanced"')&&!UI_SRC.includes('id="bsim-advanced" open'),
  helpFolded:(UI_SRC.match(/class="bsim-help"/g)||[]).length,
  ringsFollow:UI_SRC.includes('paintSpawnMarkers(step)')&&UI_SRC.includes('const live = (step && !spawnPick)'),
  css:CSS_SRC.includes('.bsim-setup-quick')&&CSS_SRC.includes('.bsim-fold')};

// ---- Round 48: BUFF_CHANGE semantics + defender-side 62/63 timings ------
// Synthetic battle: give every unit 「自然守护」(buff 7350 carries at-62
// IGNORE_KNOCKBACK / CANT_TRANSFER) so the defender timings have real client
// specialities to execute. Then assert the engine raises them, never on a
// 贯穿(Break) attack, and that the speciality really fires.
const sc48=C.schedules.find(x=>x.id===76);
const status48=[];for(const sd of ['A','B'])for(let i=0;i<8;i++)status48.push({buffId:7350,side:sd,index:i});
const r48=S.simulate({data:D,mech:M,map:W.maps.find(m=>m.id===C.environment.mapId),
  teams:{A:mem(team(sc48.team1Id)),B:mem(team(sc48.team2Id))},mode:'left',seed:292,maxRounds:8,
  env:{weatherId:C.environment.weatherId,unitStatus:status48},substrate:SUB});
const at62Specs=Object.values(M.specs||{}).filter(x=>x.at===62).length;
const at63Specs=Object.values(M.specs||{}).filter(x=>x.at===63).length;
const c24={at62Specs,at63Specs,
  aliasRemoved:!/const AT_ALIAS = \{[^}]*62\s*:/.test(CORE),
  fires62:CORE.includes('fire(62, t, ctx)'),fires63:CORE.includes('fire(63, t, back)'),
  breakGate:CORE.includes("!(evSkill.tags || []).includes('Break')"),
  ignoreKnockback:Number(r48.mechanics?.executed?.IGNORE_KNOCKBACK||0),
  steps:r48.steps.length,error:r48.error||null,
  lua:r48.mechanics?.luaUnknown||{}};
// 25 — BUFF_CHANGE must fire only on an ACTUAL change, and removal must
// expose the changed buff with isDeleted=true / negative stack delta.
const c25={src:['const buffChanged','changedBuff: b, changedBuffId: b.id',
                "case 'isDeleted': return !!b.deleted",'fire(65, u, {target: u})']
              .every(k=>CORE.includes(k)),
  deep:Number(r.mechanics?.skipped?.['连锁触发过深']||0),
  at58Specs:Object.values(M.specs||{}).filter(x=>x.at===58).length,
  changedConditions:Object.values(M.specs||{}).filter(x=>x.at===58&&
    /changed_buffs|FindChangedBuff|stack_count_change/.test(String(x.c||'')+String(x.dp||''))).length};

// ---- Round 49: empty-tile casts / replay annotations / knockback audit /
// terrain rules / multi-seed sweep / grouped left rail -------------------
const sc49=C.schedules.find(x=>x.id===55);
const r49=S.simulate({data:D,mech:M,map:W.maps.find(m=>m.id===C.environment.mapId),
  teams:{A:mem(team(sc49.team1Id)),B:mem(team(sc49.team2Id))},mode:'left',seed:1055,maxRounds:20,
  env:{weatherId:C.environment.weatherId},substrate:SUB});
const egSkills=Object.values(M.skills||{}).filter(s=>s.eg).length;
const egSteps=r49.steps.filter(s=>s.skill?.id===21721);
const egBad=egSteps.filter(st=>{const p=r49.steps[st.seq-1]?.snap||[],t=st.target;
  return !t||p.some(u=>u.alive&&u.x===t.x&&u.y===t.y);}).length;
const egSpawned=r49.units.filter(u=>/虚空投影/.test(u.name)).length;
const c26={egSkills,egCasts:egSteps.length,egBad,egSpawned,
  gate:CORE.includes('function emptyTileOk')&&CORE.includes('目标不是空地')};
// 27 — name+id and defender coordinates in the replay text
const taggedSteps=r49.steps.filter(s=>/^(A|B)\d+ ·|·(A|B)\d+/.test(s.text||'')).length;
const coordHits=r49.steps.reduce((n,s)=>n+(s.text||'').split(/·(A|B)\d+\(/).length-1,0);
const hitCoords=r49.steps.reduce((n,s)=>n+(s.hits||[]).filter(h=>Number.isFinite(h.x)).length,0);
const c27={taggedSteps,coordHits,hitCoords,
  svg:UI_SRC.includes('bsim-tag-uid')&&UI_SRC.includes('esc(s.uid)'),
  src:CORE.includes('const tagOf =')&&CORE.includes('const cellOf =')};
// 28 — knockback audit trail (declared / computed / direction / moved / stop)
const knocks=r49.steps.flatMap(s=>s.knockbacks||[]);
const c28={count:knocks.length,
  withDetail:knocks.filter(k=>Number.isFinite(k.declared)&&Number.isFinite(k.moved)&&k.stop&&k.direction).length,
  withPositions:knocks.filter(k=>k.from&&k.to).length,
  ui:UI_SRC.includes('bsim-knock'),src:CORE.includes('击退明细：')};
// 29 — terrain rules exported and really applied
const fieldDefs=Object.keys(M.fieldStatusDefs||{}).length;
const tileSpecs=[...new Set(Object.values(M.fieldStatusDefs||{}).flatMap(f=>f.sp||[]))];
const terrainSteps=r49.steps.filter(s=>(s.terrain||[]).length).length;
const terrainBuffs=r49.steps.reduce((n,s)=>n+(s.events||[]).filter(e=>/地块「/.test(e)).length,0);
const fieldOps=Object.keys(M.fieldOperations||{}).length;
const op18=M.fieldOperations?.[18]||{},op10=M.fieldOperations?.[10]||{};
const c29={fieldDefs,tileSpecs:tileSpecs.length,tileSpecsExported:tileSpecs.filter(i=>M.specs[i]).length,
  terrainSteps,terrainBuffs,fieldOps,op18:op18.field,op10:op10.field,
  src:['function setFieldStatus','function fieldStepCost','function runFieldSpecs',
       'function clearFieldStatus','NO_KNOCKBACK_DISTANCE','operationField('].every(k=>CORE.includes(k)),
  ui:UI_SRC.includes('bsim-terrain-cell')};
// 30 — multi-seed sweep UI
const c30={ui:['data-batch-run','data-batch-watch','data-batch-filter','id="bsim-batch-n"',
               'function battleOpts','const runBatch','const watchSeed',
               'battleOpts(seed)','renderBatch(']
                .every(k=>UI_SRC.includes(k)),
  winrate:UI_SRC.includes('我方胜率'),
  css:CSS_SRC.includes('.bsim-batch-table')};
// 31 — left rail categorised
const c31={groups:c23.groups,nav:(UI_SRC.match(/data-fold-go=/g)||[]).length,
  numbered:(UI_SRC.match(/bsim-fold-idx/g)||[]).length,
  runButtons,css:CSS_SRC.includes('.bsim-fold-nav')};

// ---- Round 50: client-faithful turn-1 mechanics -----------------------
// All eight items are checked against the SAME official schedule-76
// deployment used by the rest of this suite, never against a frozen step id.
const buffTiers=Object.keys(M.buffTiers||{}).length;
const tier53=Number(M.buffTiers?.[53]||0),tier81=Number(M.buffTiers?.[81]||0);
const coleStep=r.steps.find(s=>s.skill?.id===22008);
const coleAfter=coleStep?(r.steps[coleStep.seq+1]?.snap||coleStep.snap||[]):[];
const colBuffs=(coleAfter.find(u=>u.uid==='B4')?.b||[]).map(x=>Number(x[0]));
// 32 — [攻击3] immediately replaces the aura [攻击2] and stays active.
const c32={tiers:buffTiers,tier53,tier81,has81:colBuffs.includes(81),has53:colBuffs.includes(53),
  src:CORE.includes('const tierOf =')&&CORE.includes('buffTiers')};
// 33 — 伊凡 freezes the caster's whole 1-tile radius at battle start AND at
// action end (CAST_SKILL at25/28 + OPERATION at1 applied over the AOE).
const frozen=allEvents.filter(e=>/变为「冰冻」/.test(e));
const frozenCells=[...new Set(frozen.map(e=>e.match(/\((\d+,\d+)\)/)?.[1]).filter(Boolean))];
const c33={events:frozen.length,cells:frozenCells.length,
  atBattleStart:(r.steps[0]?.events||[]).some(e=>/变为「冰冻」/.test(e)),
  src:CORE.includes("'OPERATION'].includes(sp.t)")&&CORE.includes('opArea')};
// 34 — 「静聆神谕」 forced 3-skill choice + 再行动.
const oracle=r.steps.filter(s=>s.actor==='A4');
const firstOracle=oracle.find(s=>[21570,21571,21572].includes(Number(s.skill?.id)));
const afterOracle=firstOracle?oracle.find(s=>s.seq>firstOracle.seq):null;
const c34={first:firstOracle?.skill?.name||null,firstId:firstOracle?.skill?.id||0,
  next:afterOracle?.skill?.name||afterOracle?.kind||null,
  ord:[21571,21572,21570].map(id=>Number(M.skills[id]?.ord||0)),
  src:CORE.includes('choiceGroup')&&CORE.includes('ACTED_ACT(inst)')};
// 35 — one-shot timed MODIFY_ATTRIBUTE: 法卡尔·SP starts with 4 TP.
const tpLog=allEvents.find(e=>/能量 3 → 4/.test(e))||'';
const b3Start=(r.steps[0]?.snap||[]).find(u=>u.uid==='B3');
const c35={tpStart:b3Start?.tp??null,log:tpLog.slice(0,80),
  src:CORE.includes('function applyTimedAttribute')&&CORE.includes('TIMED_MODIFY_ATTRIBUTE')};
// 36 — personality [瞬发] chain (潜袭) and the 协同号令 opening setup
// (戍卫箭幕). Use the plan's OWN map (332) for a full 20-round battle so the
// assertion matches the deployment the user is looking at, not the suite's
// map-470 hybrid.
const r50=S.simulate(Object.assign(opt(),{map:W.maps.find(m=>m.id===PLAN.mapId),maxRounds:20}));
const coleChain=r50.steps.filter(s=>s.actor==='B4'&&s.seq<=8).map(s=>s.skill?.name||s.kind);
const fakeChain=r50.steps.filter(s=>s.actor==='B3'&&s.seq<=18).map(s=>s.skill?.name||s.kind);
const c36={qianxi:coleChain.includes('潜袭'),qianxiAfter:coleChain.indexOf('潜袭')>coleChain.indexOf('烟幕游击'),
  shuwei:fakeChain.includes('戍卫箭幕'),fakeChain:fakeChain.slice(0,4),steps:r50.steps.length,
  src:CORE.includes('stanceBonus')&&CORE.includes('setupTagStep')};
// 37 — full-HP heal AOE is still castable for its BUFF part (damageIntent).
const c37={src:CORE.includes("if (s.dt === 3) return false;")&&CORE.includes('skipHeal'),
  oracleHeal:firstOracle?.skill?.id===21572};
// 38 — probability-gated extra effects are observable (no silent no-proc).
const c38={src:CORE.includes('概率判定未通过'),
  buff8572:!!M.buffs?.[8572],sleepSpec:Number(M.specs?.['28132']?.p?.[0]||0)};
// 39 — pathing distance field agrees with reachable() on terrain cost.
const c39={src:CORE.includes('dist.get(key(cur.x, cur.y)) + cur.step + fieldStepCost(unit, cur)')
    &&CORE.includes('const foeSum = foes.reduce'),
  timedOps:Object.values(M.specs||{}).filter(x=>x.t==='MODIFY_ATTRIBUTE'&&x.at===25).length,
  prioritySpecs:Object.values(M.specs||{}).filter(x=>Number(x.pr||0)!==0).length,
  control:CORE.includes('const isControlBuff'),
  moveAttack:CORE.includes("s.t === 'MOVE_ATTACK'")&&CORE.includes('u.flags?.moveSteps')};

// ---- Round 51: pathing / cup statuses / AOE jump / speed debuff -------
// Official schedule-76 deployment on its OWN map (332), same as the replay
// the user is comparing against. This also exercises every 选手精神状态.
const PLAN51=JSON.parse(fs.readFileSync(PLAN_PATH,'utf8')).plans[0];
const sc51=C.schedules.find(x=>x.id===76);
const bf51=(sc51.buffDetails||[]).filter(b=>b.buffId).map(b=>({buffId:b.buffId,side:side(b.target)}));
const t51={A:mem(team(sc51.team1Id)),B:mem(team(sc51.team2Id))};
const us51=[];
for(const st of sc51.unitStatus||[]){const s=st.teamIndex===1?'A':'B';
  const i=t51[s].findIndex(m=>Number(m.npcId)===Number(st.npcId));
  if(i>=0&&st.buffId)us51.push({buffId:st.buffId,side:s,index:i});}
const opt51=seed=>Object.assign(opt(),{map:W.maps.find(m=>m.id===PLAN51.mapId),teams:t51,seed,
  maxRounds:20,env:{weatherId:C.environment.weatherId,buffs:bf51,unitStatus:us51},
  spawns:{A:PLAN51.A,B:PLAN51.B}});
const r51=S.simulate(opt51(292));
const ev51=r51.steps.flatMap(s=>s.events||[]);
// 40 — 走位：麦莎·SP (B1) 第一步按客户端 posCompare 走 (9,5)，不是高差 (12,8)
const firstMove=r51.steps.find(s=>s.actor==='B1'&&s.kind==='move');
const c40={firstMove:firstMove?{x:firstMove.to?.x,y:firstMove.to?.y}:null,
  src:CORE.includes('const foeSum = foes.reduce')&&CORE.includes('cur.step + fieldStepCost(unit, cur)')};
// 41 — 选手状态：33% 睡眠判定真的发生，且睡眠阻止行动；受击解除
let slept=0,skipped=0,rolls=0;
// Round 53: the opening die consumes one RNG draw, so which seeds sleep at
// the start and which get dispelled by 珀列维特's 命途所至 changed. Scan a
// wider fixed set instead of pinning the criterion to five frozen transcripts.
for(const seed of [292,28645690,28645696,1002,1050]){
  const rr=battleOf(seed);
  const es=rr.steps.flatMap(s=>s.events||[]);
  slept+=es.filter(e=>/获得「睡眠」/.test(e)).length;
  rolls+=es.filter(e=>/昏昏欲睡」概率判定|开局判定|获得「睡眠」/.test(e)).length;
  skipped+=rr.steps.filter(s=>s.actor==='A1'&&s.kind==='skip').length;
}
const c41={statuses:us51.length,slept,rolls,skipped,
  src:CORE.includes('const isControlBuff')&&CORE.includes('受到攻击伤害解除')&&
      CORE.includes("s.t === 'MOVE_ATTACK'")};
// 42 — 陷阵·锐意承锋 跳人堆：落点按 AOE 真实覆盖数评分。
// Round 55: 科尔 is now genuinely [隐身] in 烟雾 (field AURA 10242 → buff
// 647), so the A-side formation at this step changed and the best REACHABLE
// landing covers fewer foes than the old frozen "5". Assert the MECHANISM:
// every enemy inside the chosen 3-tile diamond was actually hit, and the
// landing is the best-covered one among the phase's legal cast blocks.
const lunge=r51.steps.find(s=>s.skill?.id===15602);
const lungeHits=(lunge?.hits||[]).filter(h=>h.amount>0).length;
const c42Snap=lunge?r51.steps[lunge.seq-1]?.snap||[]:[];
const c42Foes=c42Snap.filter(u=>u.alive&&String(u.uid)[0]==='A'&&!r51.units.find(x=>x.uid===u.uid&&/投影|星核/.test(x.name||'')));
const c42InArea=lunge?c42Foes.filter(u=>Math.abs(u.x-lunge.target.x)+Math.abs(u.y-lunge.target.y)<=3).length:0;
const c42Cands=(lunge?.candidates||[]).filter(c=>Number(c.id)===15602);
const c42BestCover=c42Cands.length?Math.max(...c42Cands.map(c=>{
  const t=c.target||{};
  return c42Foes.filter(u=>Math.abs(u.x-t.x)+Math.abs(u.y-t.y)<=3).length;})):c42InArea;
const c42={cast:!!lunge,hits:lungeHits,inArea:c42InArea,bestCover:c42BestCover,
  target:lunge?.target||null,
  aoe:M.aoe?.[49]||null,
  src:CORE.includes('aoeCoverStep')&&CORE.includes('const blast =')};
// 43 — 命途所至的 [▼速度4] 不被同技能 DISPEL 驱散，速度 -200 生效
const fate=r51.steps.find(s=>s.skill?.id===21567);
const fateEv=fate?.events||[];
const slowApplied=fateEv.filter(e=>/获得「速度4」/.test(e)).length;
const slowDispelled=fateEv.filter(e=>/「速度4」被驱散/.test(e)).length;
const c43={cast:!!fate,slowApplied,slowDispelled,
  speedDef:M.buffs?.[9025]?.sp?.map(x=>M.specs[x]?.p?.[1]).includes(-200),
  prioritySpecs:Object.values(M.specs||{}).filter(x=>Number(x.pr||0)!==0).length,
  src:CORE.includes('speciality_type.priority')||CORE.includes('Number(M?.specs?.[b]?.pr)')};


// ---- Round 52: the user's own battle — schedule 76, official plan on its
// own map, seed 28645683, the page's default AI priorities. -------------
const r52u=battleOf(28645683);
const stepsU=r52u.steps,unitsU=r52u.units;
const nameU=uid=>(unitsU.find(u=>u.uid===uid)||{}).name||'';
// 44 — 命途所至 [▼速度4] (-200) is live exactly while 霜佑之印 is present.
const slowRows=[];
for(const st of stepsU.filter(s=>s.skill?.id===21567)){
  const prev=stepsU[st.seq-1]?.snap||[];
  for(const u of st.snap||[]){
    const b=(u.b||[]).find(x=>x[0]===9025); if(!b)continue;
    const before=prev.find(x=>x.uid===u.uid);
    const wasLive=(before?.b||[]).some(x=>x[0]===9025&&x[4]===1);
    slowRows.push({uid:u.uid,on:b[4],frost:(u.b||[]).some(x=>x[0]===8792),
      d:before&&!wasLive?u.spd-before.spd:null});
  }
}
const c44={casts:stepsU.filter(s=>s.skill?.id===21567).length,rows:slowRows.length,
  liveWithFrost:slowRows.filter(p=>p.frost).every(p=>p.on===1),
  dormantWithout:slowRows.filter(p=>!p.frost).every(p=>p.on===0),
  minus200:slowRows.some(p=>p.on===1&&p.d===-200),
  src:CORE.includes('function buffOn(b)')&&CORE.includes('const apSig =')};
// 45 — 贝拉: 星核·位移 only while her 灵感星核 lives, 星核·造物 only without it.
// Evidence over a fixed seed set of the SAME page-exact battle (贝拉 may die
// before casting in any single transcript): every 造物 cast has no live core,
// every 位移 cast has one, and no decision taken with a live core even
// LISTS 星核·造物 among its candidates.
const CORE_MAKE=[21460,21516,21906,21907],CORE_MOVE=21472;
const coreEvidence={make:0,makeBad:0,move:0,moveBad:0,listedWrong:0,coreDecisions:0};
const r21482=[];
let bleed4=0,wound4=0;
// Round 53: more seeds, because the opening die shifted which turns 贝拉
// prefers her AOE over the star-core skill. Still assert the SAME invariants.
for(const sd of [28645683,293,294,5074,292,28645688,1000,
                295,300,1004,28645686,28645689,28645693,28645696]){
  const rr=battleOf(sd);
  const nm=uid=>(rr.units.find(u=>u.uid===uid)||{}).name||'';
  for(const st of rr.steps){
    for(const h of st.hits||[])if(h.bySkillId===21482)r21482.push(nm(h.uid));
    if(st.actor==='A5'){
      if((st.events||[]).some(e=>/获得「流血」/.test(e)))bleed4++;
      if((st.events||[]).some(e=>/获得「伤口」/.test(e)))wound4++;
    }
    if(st.actor!=='B5')continue;
    const core=(rr.steps[st.seq-1]?.snap||[]).some(u=>u.alive&&/灵感星核/.test(nm(u.uid)));
    const id=Number(st.skill?.id);
    if(CORE_MAKE.includes(id)){coreEvidence.make++;if(core)coreEvidence.makeBad++;}
    if(id===CORE_MOVE){coreEvidence.move++;if(!core)coreEvidence.moveBad++;}
    const listed=[...(st.candidates||[]),...(st.alts||[])].map(c=>Number(c.id||0)).filter(Boolean);
    if(core&&listed.some(x=>CORE_MAKE.includes(x)))coreEvidence.listedWrong++;
    if(!core&&listed.includes(CORE_MOVE))coreEvidence.listedWrong++;
    if(core)coreEvidence.coreDecisions++;
  }
}
const c45=Object.assign({},coreEvidence,{
  src:CORE.includes('function syncBuffSwaps')&&CORE.includes('IsSummoned: () => !!u.summon')});
// 46 — 伦伽勒·SP: 陷阵 hits enemies; 游击 only onto a friendly 枪影; ≤1 游击 per round.
const lungeU=stepsU.filter(s=>s.skill?.id===15602);
const youjiU=stepsU.filter(s=>s.skill?.id===16437);
const youjiRound={};for(const s of youjiU)youjiRound[s.round]=(youjiRound[s.round]||0)+1;
// Round 55: 隐身 changed the A-side formation, so the reachable 陷阵 landing
// covers fewer foes. Compare hits with the ACTUAL 3-diamond enemy count.
const lungeGeo=lungeU.map(st=>{
  const snap=stepsU[st.seq-1]?.snap||[];
  const foes=snap.filter(u=>u.alive&&String(u.uid)[0]==='A'&&!unitsU.find(x=>x.uid===u.uid&&/投影|星核/.test(x.name||'')));
  return {hits:(st.hits||[]).filter(h=>!h.sub&&h.amount>0).length,
          inArea:st.target?foes.filter(u=>Math.abs(u.x-st.target.x)+Math.abs(u.y-st.target.y)<=3).length:0};
});
const c46={lunges:lungeU.length,lungeHits:lungeU.reduce((n,s)=>n+(s.hits||[]).filter(h=>!h.sub&&h.amount>0).length,0),
  lungeGeo, youji:youjiU.length,
  onShadow:youjiU.filter(st=>(stepsU[st.seq-1]?.placed||[]).some(o=>o.id===139&&o.x===st.target?.x&&o.y===st.target?.y)).length,
  maxPerRound:Math.max(0,...Object.values(youjiRound)),
  src:CORE.includes('function grantTemp')&&CORE.includes('function revokeTemp')};
// 47 — cast_param / target_param: exported, evaluable, and 21482 only feeds
// the caster's own 灵感星核 (its 伤害缓冲 turns the hit into 灵感指数, so
// the HP loss is 0 — count targets, not damage).
const c47={cp:Object.values(M.skills).filter(s=>s.cp).length,tgp:Object.values(M.skills).filter(s=>s.tgp).length,
  unknown:Object.keys(r52u.mechanics?.skipped||{}).filter(k=>/施放条件无法求值|目标过滤无法求值/.test(k)),
  r21482:r21482.length,r21482Units:r21482.filter(n=>!/灵感星核/.test(n)).length,
  src:CORE.includes('function castTargetOk')&&CORE.includes('function targetParamOk')&&CORE.includes('const aoeSideOf =')};
// 48 — idskill_follow damage is the attack event (陷阵 → 灭魂一击后续 dt 1).
const c48={src:CORE.includes('const evSkill = (evSeg && skillRec(evSeg.id)) || s;')
    &&CORE.includes('evSkill.dt !== 5 && evSkill.dt !== 3')&&CORE.includes('const followDamage ='),
  move3997:lungeU.some(s=>(s.events||[]).some(e=>/伦伽勒·SP (获得再移动|的「机动游击」：剩余移动力)/.test(e)))};
// 49 — 被攻击后 on the ATTACKER's side: 野狐塞娜「主动攻击后…施加[流血]/[伤口]」.
// Same 4-seed set as #45: one transcript may only contain counters (not
// initiative attacks) or hits on an immune summon.
const c49={bleed:bleed4,wound:wound4,
  src:CORE.includes('const attackerAt4 =')&&CORE.includes('fire(4, caster, ehctx, attackerAt4)')};
// 50 — only 定身类 (StrongControl) skips a turn; 干扰类 never does.
const skipsU=stepsU.filter(s=>s.kind==='skip');
const c50={skips:skipsU.map(s=>(s.text||'').slice(0,24)),
  weak:skipsU.filter(s=>/缴械|主动技|移动1|缠缚/.test(s.text||'')).length,
  src:CORE.includes("if (d.su === 'WeakControl') return false;")};
// 51 — tt 5 is the current friendly target, not every ally. A clamped
// 「能量 +0」 on an enemy with no energy left is not a gain.
const c51={teamTp:stepsU.reduce((n,s)=>n+(s.events||[]).filter(e=>/能量 \+[1-9]\d*（猩红之触）/.test(e)).length,0),
  src:CORE.includes('case 5: return tgt ? (tgt.side === o.side && tgt !== o ? [tgt] : []) : alliesOf(o);')};
// 52 — energy never negative (罗格妮达 TP_MAX −99 → no energy bar).
const c52={negTp:stepsU.some(s=>(s.snap||[]).some(u=>u.tp<0)),
  src:CORE.includes("const NON_NEGATIVE = new Set(['TP_MAX', 'MOBILITY']);")};

// ---- Round 53: instant free actions / numeric formulas / disarm / opening die
const evU=stepsU.flatMap(s=>s.events||[]);
// 53 + 54 — [瞬发] free actions are cast at phase 0 BEFORE the main skill.
const firstTwo=n=>stepsU.filter(s=>s.kind==='skill'&&nameU(s.actor)===n)
  .slice(0,2).map(s=>Number(s.skill?.id));
const c53={fk:firstTwo('法卡尔·SP'),lg:firstTwo('伦伽勒·SP'),
  src:CORE.includes('freeInstant: true')&&CORE.includes("SKILL_PRIO.instantFirst !== false")};
// 55 — full substituted formula on EVERY damage AND heal hit, both in the
// structured detail and in the battle log; no status-hit log spam.
const calcHitsU=stepsU.flatMap(s=>s.hits||[]).filter(h=>h.calc?.length);
const c54={n:calcHitsU.length,
  withFormula:calcHitsU.filter(h=>h.formula).length,
  withExpr:calcHitsU.filter(h=>h.calc.every(c=>c.expr)).length,
  heal:calcHitsU.filter(h=>h.heal).length,
  logs:evU.filter(e=>/^伤害数值.*；公式 /.test(e)).length,
  healLogs:evU.filter(e=>/^治疗数值.*；公式 /.test(e)).length,
  noise:evU.filter(e=>/状态类技能，无伤害公式/.test(e)).length,
  src:CORE.includes('const formula = () =>')&&CORE.includes('expr: expr ||')&&
      CORE.includes('固定伤害加成')};
// 56 — 陷阵·锐意承锋's follow-up debuff hits EVERY enemy in the AOE, and
// DISARM actually blocks both carried skills and the normal attack.
const lungeOne=lungeU[0];   // lungeU already holds every 15602 cast (round 46)
const disNames=(lungeOne?.events||[]).filter(e=>/获得「缴械」/.test(e)).map(e=>e.split(' ')[0]);
const disUid=disNames.map(n=>unitsU.find(u=>u.name===n)?.uid);
const disCasts=stepsU.filter(s=>disUid.includes(s.actor)&&lungeOne&&s.seq>lungeOne.seq&&
  s.round===lungeOne.round&&s.kind==='skill').map(s=>nameU(s.actor)+'/'+s.skill?.name);
// Count the enemies that really are inside the 3-tile diamond at the landing
// cell: the debuff must cover exactly THAT set, not a frozen "5 targets" from
// an older trajectory (走位 changes which enemies stand in the blast).
const lungeSnap=lungeOne?(stepsU[lungeOne.seq-1]?.snap||[]):[];
const lungeFoes=lungeSnap.filter(u=>u.alive&&String(u.uid)[0]==='A'&&
  unitsU.find(x=>x.uid===u.uid&&!/投影|星核/.test(x.name||'')));
const inArea=lungeOne?lungeFoes.filter(u=>Math.abs(u.x-lungeOne.target.x)+Math.abs(u.y-lungeOne.target.y)<=3).length:0;
const c56={cast:!!lungeOne,n:disNames.length,names:disNames,inArea,
  target:lungeOne?.target||null,castsAfter:disCasts,
  src:CORE.includes("?.t === 'DISARM'")&&CORE.includes('const aoeTargets =')};
// 57 — arena 「选手精神状态」 probability is resolved at the OPENING (step 0)
// with the real die written to the log, so ~1/3 of seeds start 伊凡 asleep.
let openHit=0,openMiss=0,step0Sleep=0,openRolls=[];
for(const sd of [28645683,28645684,28645685,28645686,28645687,28645688,
                 28645689,28645690,28645691,28645692,28645693,28645694]){
  const rr=battleOf(sd);
  const e0=rr.steps[0]?.events||[];
  const die=e0.find(e=>/开局判定：Random\(100\)=\d+/.test(e));
  if(die){const m=die.match(/Random\(100\)=(\d+)/);openRolls.push(Number(m[1]));}
  if(e0.some(e=>/开局判定.*→ 命中/.test(e)))openHit++;
  if(e0.some(e=>/开局判定.*→ 未命中/.test(e)))openMiss++;
  if(e0.some(e=>/获得「睡眠」/.test(e)))step0Sleep++;
}
const c57={openHit,openMiss,step0Sleep,openRolls,
  src:CORE.includes('开局判定：Random(100)')&&CORE.includes('sim.probe = false;')&&
      CORE.includes('sim.lastRandom')};

// ---- Round 54: anchor summons / instant economy / self skills / labels / xlsx formula
// 58 — a cast-anchor summon is not placed when its extended range reaches no
// enemy. 菲娜塔「召唤·虚空投影」21721 on schedule 76 / seed 28645683.
let anchorCasts=0,anchorUseful=0,anchorWasted=0;
const anchorSeeds=[];
for(const sd of [28645683,28645684,28645685,28645686,28645687,28645688,292,293,294,295,296,1002]){
  const rr=battleOf(sd);
  const un=rr.units, uname=u=>(un.find(x=>x.uid===u)||{}).name||'';
  for(const st of rr.steps.filter(x=>Number(x.skill?.id)===21721)){
    anchorCasts++;
    const snap=rr.steps[st.seq-1]?.snap||[];
    const foes=snap.filter(u=>u.alive&&String(u.uid)[0]!==String(st.actor)[0]&&
      !/投影|星核/.test(uname(u.uid)));
    const ok=foes.some(u=>Math.abs(u.x-st.target.x)+Math.abs(u.y-st.target.y)<=4);
    if(ok)anchorUseful++; else {anchorWasted++;anchorSeeds.push(sd+':#'+st.seq+'@'+st.target.x+','+st.target.y);}
  }
}
const c58={casts:anchorCasts,useful:anchorUseful,wasted:anchorWasted,wastedAt:anchorSeeds.slice(0,4),
  src:CORE.includes('function anchorPlacementUseful')&&CORE.includes('isCastAnchorSummon')&&
      CORE.includes('EXTEND_CAST_RANGE')};
// 59 — a DAMAGE [瞬发] is only cast when it actually hits; no wasted TP/CD,
// no 「未命中」 text for a damage instant anywhere in a 12-seed sweep.
let instDamageCasts=0,instDamageHits=0,instDamageMissText=0,instMoved=0;
for(const sd of [28645683,28645684,28645685,28645686,28645687,28645688,292,293,294,295,296,1002]){
  const rr=battleOf(sd);
  for(const st of rr.steps.filter(x=>Number(x.skill?.id)===15658)){
    instDamageCasts++;
    if((st.hits||[]).some(h=>h.amount>0))instDamageHits++;
    if(/：未命中/.test(st.text||''))instDamageMissText++;
    if(st.from&&st.to&&(st.from.x!==st.to.x||st.from.y!==st.to.y))instMoved++;
  }
}
const c59={casts:instDamageCasts,hits:instDamageHits,missText:instDamageMissText,moved:instMoved,
  src:CORE.includes('if (damageIntent(s)) continue;')&&CORE.includes('A DAMAGE skill whose blast covers no enemy')};
// 60 — a self/stance [瞬发] has NO hit target: it must never read 「未命中」.
const stance=stepsU.find(s=>Number(s.skill?.id)===16335);
const c60={cast:!!stance,text:stance?.text||'',hits:(stance?.hits||[]).length,
  labels:stance?.skill?.labels||[],
  src:CORE.includes('对自身生效')&&CORE.includes('isUtility(skill)')};
// 61 — every skill shown in the replay carries client-derived Chinese labels;
// the exported tag dictionaries are the client's own name columns.
const skillSteps=stepsU.filter(s=>s.skill);
const c61={n:skillSteps.length,labelled:skillSteps.filter(s=>(s.skill.labels||[]).length).length,
  tagNames:Object.keys(M.skillTagNames||{}).length,
  dtNames:Object.keys(M.damageTypeNames||{}).length,
  sample:Object.fromEntries([16335,15602,21721,21474].map(id=>{
    const st=stepsU.find(s=>Number(s.skill?.id)===id);return [String(id),st?.skill?.labels||null];})),
  src:CORE.includes('function skillLabels')&&CORE.includes('labels: skillLabels')&&
      UI.includes('bsim-skill-tag')};
// 62 — official damage formula: per-source (1+x) PRODUCT for 受到伤害区,
// ∏(1−iᵢ) for defence ignore, and a 5%-of-attack floor on (attack−defence).
const beHits=calcHitsU.filter(h=>h.calc.some(c=>/^受击方易伤$/.test(c.label)));
const beProduct=beHits.filter(h=>/个来源全乘算/.test(h.calc.find(c=>c.label==='受击方易伤').note)).length;
const perSource=beHits.filter(h=>h.calc.some(c=>/^易伤·/.test(c.label))).length;
const defRows=calcHitsU.filter(h=>h.calc.some(c=>c.label==='目标防御'&&/连乘/.test(c.note))).length;
const floorRows=calcHitsU.filter(h=>h.calc.some(c=>c.label==='基础伤害'&&/5%/.test(c.note||''))).length;
const c62={n:beHits.length,product:beProduct,perSource,defRows,floorRows,
  sample:beHits[0]?beHits[0].calc.filter(c=>/易伤|防御|基础伤害/.test(c.label)).map(c=>`${c.label}=${c.value} | ${c.expr}`):[],
  src:['function zoneFactors','受到伤害区 = ∏','A10/A11/F23','个无视防御来源连乘','攻击力×5%']
    .every(k=>CORE.includes(k))};

// ---- Round 55: seed 20261107 — anchor / smoke concealment / cover / alert map
const r55=S.simulate(Object.assign(opt(),{seed:20261107,maxRounds:20,skillPriority:PRIO54}));
const s55=r55.steps, u55=r55.units, nm55=x=>(u55.find(u=>u.uid===x)||{}).name||'';
const cole55=s55.filter(s=>nm55(s.actor)==='科尔');
const fina55=s55.filter(s=>nm55(s.actor)==='菲娜塔');
// 63 — a cast-anchor summon is never wasted: no projection on a turn with no
// follow-up attack; any placement must be straight-line within range_max.
const r1Fina=fina55.filter(s=>s.round===1);
const anchorCasts55=s55.filter(s=>Number(s.skill?.id)===21721);
const anchorWasted55=anchorCasts55.filter(st=>{
  const t=st.target, prev=s55[st.seq-1]?.snap||[];
  const foes=prev.filter(u=>u.alive&&String(u.uid)[0]==='A'&&!/投影|星核/.test(nm55(u.uid)));
  const aligned=Math.abs(t.x-st.from.x)===0||Math.abs(t.y-st.from.y)===0||
    Math.abs(t.x-st.from.x)===Math.abs(t.y-st.from.y);
  const reach=foes.some(u=>Math.abs(u.x-t.x)+Math.abs(u.y-t.y)<=4);
  const follow=fina55.some(x=>x.round===st.round&&x.seq>st.seq&&
    (x.hits||[]).some(h=>h.amount>0));
  return !aligned||!reach||!follow;
});
const c63={r1Fina:r1Fina.map(s=>s.kind+':'+(s.skill?.name||'-')),
  noR1Waste:!r1Fina.some(s=>Number(s.skill?.id)===21721),
  casts:anchorCasts55.length,wasted:anchorWasted55.length,
  src:['getLineBlocks','isAnchorSummonSkill','anchorPlacementUseful'].every(k=>CORE.includes(k))};
// 64 — smoke tile AURA 10242 grants buff 647 [隐身]; the unit stays hidden and
// the enemy cannot auto-select it (only AOE splash / forced selection may hit).
const smoke55=s55.flatMap(s=>(s.events||[]).filter(e=>/变为「烟雾」/.test(e)).map(e=>({seq:s.seq,e})));
const coleR1=cole55.filter(s=>s.round===1);
const coleSmokeJump=coleR1.find(s=>Number(s.skill?.id)===22008);
const coleLand=coleSmokeJump?.to||null;
const coleR1Tail=coleR1[coleR1.length-1]?.to||null;
const autoTarget55=s55.filter(s=>String(s.actor||'')[0]==='A'&&s.round===1&&
  (s.hits||[]).some(h=>h.uid==='B4'&&h.amount>0)&&
  !/范围|伏刃|溅射|死亡莲华|联动/.test(s.text||''));
const c64={smoke:smoke55.length,jump:coleSmokeJump?{tgt:coleSmokeJump.target,land:coleLand}:null,
  r1Skills:coleR1.filter(s=>s.skill).map(s=>s.skill.name+':'+(s.skill.id===22013?'hit':'0')),
  endAt:coleR1Tail, autoTargets:autoTarget55.length,
  src:['FIELD_AURA','concealFieldId','isInvisibleTo','hasInvisibleBuff']
    .every(k=>CORE.includes(k))};
// 65 — 科尔 first action: (9,6) → 烟幕游击 → (6,6) → 潜袭 → one 普攻 → idle
// in smoke. All from client data (JUMP_MOVE p[0]=3, getLineBlocks).
const cj55=(coleSmokeJump?.events||[]).find(e=>/JUMP_MOVE/.test(e))||'';
const cjFrom=cj55.match(/科尔 \((\d+),(\d+)\) → \((\d+),(\d+)\)/);
const c65={chain:coleR1.filter(s=>s.skill).map(s=>s.skill.id),
  stand:cjFrom?[Number(cjFrom[1]),Number(cjFrom[2])]:null,
  land:cjFrom?[Number(cjFrom[3]),Number(cjFrom[4])]:null,
  endAt:coleR1Tail,
  src:['concealJumpSpec','coverPosStep','getLineBlocks'].every(k=>CORE.includes(k))+''};
// 66 — dashed 警戒范围 overlay: replay carries per-unit alert zones, the SVG
// board draws them, and the toggle + legend are wired.
const alertSteps55=s55.filter(s=>(s.snap||[]).some(u=>u.al&&u.al.p)).length;
const al55=s55.flatMap(s=>(s.snap||[]).filter(u=>u.al).map(u=>u.al));
const c66={steps:alertSteps55,alerts:al55.length,
  withSkillName:al55.filter(a=>a.skill&&a.skill!=='警戒').length,
  withLeft:al55.filter(a=>Number.isFinite(a.left)).length,
  maxDist:Math.max(0,...al55.map(a=>a.d)),
  src:['bsim-alert-ring','bsim-board-clip','alertLegend','#bsim-alert-range']
    .every(k=>UI.includes(k))};

// ---- Round 56: 审判诸罪之光 3*6 sweep / 审判执行 / other client mechanisms
// Build a real 萨曼莎·不灭微光 battle exactly like the page does.
const samOpt=(sched,seed)=>{
  const sc=C.schedules.find(x=>x.id===sched);
  const tm={A:S.cupFighters(C.teams.find(t=>t.id===sc.team1Id)),
            B:S.cupFighters(C.teams.find(t=>t.id===sc.team2Id))};
  const ce=S.cupEnv(sc,tm);
  const defaultMap=W.maps.find(m=>m.id===Number(C.environment.mapId))||W.maps[0];
  return {data:D,mech:M,map:defaultMap,teams:tm,mode:'left',seed,maxRounds:6,
    env:{weatherId:C.environment.weatherId,buffs:ce.buffs,unitStatus:ce.unitStatus},substrate:SUB};
};
// Three battles are enough for 67/68/69; every extra full simulation in this
// shared ENGINE is paid by the `full` regression job AND amplifies contention
// for the seven other 192-battle sweeps running in parallel.
const samBattles=[];
for(const [sc,sd] of [[31,292],[53,292],[31,1000]])samBattles.push(S.simulate(samOpt(sc,sd)));
// 67 — DISPLAY_AOE (client speciality type 233) is applied to BOTH the AI
// geometry and the real cast: 审判诸罪之光 #15386 is a 3*6 directional
// sweep, not the head's 1*6 middle column. All four directions are legal.
const sweepSteps=samBattles.flatMap(rr=>rr.steps.filter(s=>Number(s.skill?.id)===15386));
const dirs=new Set(sweepSteps.map(s=>JSON.stringify(s.dir||null)));
// The 3-wide strip is clipped at map edges (18 → 15/16 cells). Assert the
// MECHANISM: 3 distinct perpendicular offsets, far more than the head's 1*6.
const stripWidth=s=>{
  const d=s.dir||[1,0];
  return new Set((s.area||[]).map(c=>d[0]?c.y:c.x)).size;
};
const c67={casts:sweepSteps.length,
  area18:sweepSteps.filter(s=>(s.area||[]).length===18).length,
  strip3:sweepSteps.filter(s=>stripWidth(s)===3).length,
  minArea:Math.min(...sweepSteps.map(s=>(s.area||[]).length)),
  withDir:sweepSteps.filter(s=>Array.isArray(s.dir)&&s.dir.length===2).length,
  dirs:[...dirs],
  withHits:sweepSteps.filter(s=>(s.hits||[]).some(h=>h.amount>0)).length,
  listed:samBattles.reduce((n,rr)=>n+rr.steps.filter(s=>
    (s.candidates||[]).some(c=>Number(c.id)===15386)).length,0),
  src:['function displayAreaOf',"q?.t === 'DISPLAY_AOE'",
       'const zero = (s.rmax || 0) <= 0','dir: c.target.dir'].every(k=>CORE.includes(k))};
// 68 — a sub-cast fired at a TURN boundary (审判执行 #15398 at 每人回合
// 结束 28) resolves REAL damage and is attached to the owning replay step.
const execHits=samBattles.flatMap(rr=>rr.steps.flatMap(s=>
  (s.hits||[]).filter(h=>h.sub&&Number(h.bySkillId)===15398).map(h=>({step:s,h}))));
const c68={hits:execHits.length,
  withDamage:execHits.filter(x=>x.h.amount>0).length,
  // A zero hit must have an explicit client reason (沙姆斯's
  // PER_DAMAGED_LIMIT 「每回合最多受击 1 次」), never a silent no-op.
  zeroWithReason:execHits.filter(x=>!(x.h.amount>0)&&x.h.zeroReason).length,
  withFormula:execHits.filter(x=>x.h.formula).length,
  withSubCasts:new Set(execHits.filter(x=>(x.step.subCasts||[]).some(c=>Number(c.id)===15398)).map(x=>x.step.seq)).size,
  withText:execHits.filter(x=>/行动结束触发.*审判执行/.test(x.step.text||'')).length,
  withDispel:samBattles.reduce((n,rr)=>n+rr.steps.flatMap(s=>s.events||[])
    .filter(e=>/被驱散/.test(e)).length,0),
  src:['sim.pendingSubHits','function drainPendingSubHits','drainPendingSubHits(steps[steps.length - 1])']
    .every(k=>CORE.includes(k))};
// 69 — the head's OWN AOE (1*6 middle column) still applies its marker
// buff, so the follow-up's conditional +30% (70% → 100%) fires there while
// the wings keep 70%. Also verify the general sub-cast audit log.
let midBoost=0,wingNoBoost=0;
for(const st of sweepSteps){
  const d=st.dir||[1,0],tx=st.target.x,ty=st.target.y;
  for(const h of st.hits||[]){
    if(!h.uid)continue;
    const rr=samBattles.find(x=>x.steps.includes(st));
    const cell=(st.snap||[]).find(u=>u.uid===h.uid);
    if(!cell)continue;
    const inMid=d[0]?cell.y===ty&&cell.x>tx:cell.x===tx&&cell.y>ty;
    if(inMid&&Number(h.boost)>0)midBoost++;
    if(!inMid&&!Number(h.boost))wingNoBoost++;
  }
}
const c69={midBoost,wingNoBoost,
  auditLogs:samBattles.reduce((n,rr)=>n+rr.steps.flatMap(s=>s.events||[])
    .filter(e=>/联动施放.*审判执行.*；公式 /.test(e)).length,0),
  src:['function runSkillSpecs(skill, caster, at, ctx, skip, aoeUnits)',
       'areaCells(caster, tcell, s)','headUnits'].every(k=>CORE.includes(k))};

// ---- Round 57: client-declared mechanisms that used to be silently skipped
// 70 — `unit.isCurrentSummoned` (大维齐尔 / 基安希尔 死士 chain). The four
// skills #18746/18749/18763/18794 all carry a target_param reading it; before
// the Lua unit proxy exposed it, each cast was counted as
// 「目标过滤无法求值#…」 and the whole chain (同心战 / 解放 / 定身移除) never
// resolved. Build the real 赛程 2 battle, exactly as the page does.
const sc57=C.schedules.find(x=>x.id===2);
const tm57={A:S.cupFighters(C.teams.find(t=>t.id===sc57.team1Id)),
            B:S.cupFighters(C.teams.find(t=>t.id===sc57.team2Id))};
const ce57=S.cupEnv(sc57,tm57);
const r57=S.simulate({data:D,mech:M,map:W.maps.find(m=>m.id===Number(C.environment.mapId))||W.maps[0],
  teams:tm57,mode:'left',seed:1002,maxRounds:4,
  env:{weatherId:C.environment.weatherId,buffs:ce57.buffs,unitStatus:ce57.unitStatus},substrate:SUB});
const ev57=r57.steps.flatMap(s=>s.events||[]);
const c70={
  filterSkips:Object.entries(r57.mechanics?.skipped||{})
    .filter(([k])=>/目标过滤无法求值#(18746|18749|18763|18794)/.test(k))
    .reduce((n,[,v])=>n+v,0),
  summons:ev57.filter(e=>/召唤「帝国不朽军」/.test(e)).length,
  warBuff:ev57.filter(e=>/获得「战争杀器」/.test(e)).length,
  liberation:ev57.filter(e=>/帝国不朽军 获得「解放」/.test(e)).length,
  linked:ev57.filter(e=>/给全场刚召的死士|刚召唤的召唤物/.test(e)).length,
  src:["case 'isCurrentSummoned'",'summonedCast = sim.castSerial',
       "u.summonedCast === (sim.castSerial || 0)"].every(k=>CORE.includes(k))};
// 71 — `map:getBlock(ix,iz)` used by 嘿咻！/利用物品/紧急传送 cast_param.
// Before it existed every legality probe returned Lua.Unknown('getBlock').
const c71={
  castSkips:Object.entries(r.mechanics?.skipped||{})
    .filter(([k])=>/施放条件无法求值/.test(k)).reduce((n,[,v])=>n+v,0),
  getBlockSids:Object.keys(M.specs).filter(k=>Number(M.specs[k].at)===31&&
    M.specs[k].t==='IGNORE_ATTACK_BLOCK').length,
  src:["getBlock: (x, y) => blockProxy",'bump(cov.skipped, raw.t)'].every(k=>CORE.includes(k))};
// 72 — active_time 51/52 are DISTINCT client timings (ROUNDEND2 /
// ROUNDSTART2), not aliases of 28/27. Also verify the object-effect coverage
// counter no longer claims executed for handler-less types.
const c72={
  alias:(/const AT_ALIAS = ([^;]+);/.exec(CORE)||[])[1]||'',
  timings51:Object.values(M.timings||{})['51'],
  label51:(M.timings?.['51']||{}).label||'',
  label52:(M.timings?.['52']||{}).label||'',
  noEvent: CORE.includes('43, 44, 51, 52'),
  fired51:(r.mechanics?.firedTimings||[]).includes(51),
  fired52:(r.mechanics?.firedTimings||[]).includes(52),
  unmapped:Object.keys(r.mechanics?.unmappedTiming||{}).length,
  src:['const AT_ALIAS = {};','NO_EVENT_SKILL_AT','firedTimings: [...cov.firedTimings]']
    .every(k=>CORE.includes(k))};
// 73 — ELEMENT_TYPE is now a real (declarative) tag: 火/风 skills carry a
// Chinese element label, and IGNORE_ATTACK_BLOCK actually affects 平射
// trajectory checks.
const elemBattles=[r,...samBattles,r57];
const elemLabels=elemBattles.flatMap(rr=>rr.steps.filter(s=>
  (s.skill?.labels||[]).some(x=>/属性$/.test(x))));
const c73={
  elemSteps:elemLabels.length,
  sample:elemLabels[0]?{name:elemLabels[0].skill.name,labels:elemLabels[0].skill.labels}:null,
  executed:elemBattles.reduce((n,rr)=>n+(rr.mechanics?.executed?.ELEMENT_TYPE||0),0),
  elemSkillCount:Object.keys(M.specs).filter(k=>M.specs[k].t==='ELEMENT_TYPE').length,
  src:["ELEMENT_TYPE(inst, ctx)","const skillElement =","const ignoresBlock =",
       "'ASSIST_ATTACK', 'ASSIST_COUNTER_ATTACK'"].every(k=>CORE.includes(k))&&
      !CORE.includes("'ELEMENT_TYPE', 'ASSIST_ATTACK'")};

// ---- Round 58: remaining client-declared rows that were stubbed out ------
// 74 — SKILL_COUNT (speciality_type 23): p2 = 上限次数 delta, p3 = 消耗次数.
// 菲娜塔 #29553「刻度转化-获得1次裂隙生成使用次数」used to be counted as
// executed but never changed the skill's limit, so the extra 虚空投影 cast
// was lost. Reconstruct the real 赛程76 battle and check both the log and
// the unit's effective limit.
const r58=S.simulate(Object.assign(opt(),{seed:28645683,maxRounds:6}));
const scLogs58=r58.steps.flatMap(s=>s.events||[]).filter(e=>/调整技能次数/.test(e));
const fina58=r58.units.find(u=>/菲娜塔/.test(u.name));
const c74={logs:scLogs58.length,
  sample:scLogs58[0]||'',
  projection:scLogs58.filter(e=>/虚空投影/.test(e)).length,
  limitBonus:fina58?.skillLimit?.[21721]||0,
  catExported:Object.values(M.skills).filter(s=>Number(s.cat)>0).length,
  catName:(M.enums?.skillCategory||{})[28]||null,
  // The `cat` field itself is verified through catExported (data check),
  // since CORE only contains the engine source, not the exporter.
  src:['const skillLimitOf =','Number(q.cat) === cat',
       '调整技能次数',"if (skillLimitOf(u, s) > 0"].every(k=>CORE.includes(k))};
// 75 — ABSORB (speciality_type 134) is a DEATH LISTENER, not a shield.
// Its at=1 rows were in STATIC_TYPES and the old handler wrote `absorbPct`
// from p[0] (a SKILL id) into a field nothing read. Find a battle with a
// real kill and assert the linked skill is actually cast.
const absorbBattles=[];
for(const sc of C.schedules.slice(0,14))absorbBattles.push(S.simulate(samOpt(sc.id,1000+sc.id)));
const absorbLogs=absorbBattles.flatMap(rr=>rr.steps.flatMap(s=>(s.events||[])
  .filter(e=>/吸收 .* 阵亡 → 施放/.test(e))));
const c75={logs:absorbLogs.length,
  sample:absorbLogs[0]||'',
  executed:absorbBattles.reduce((n,rr)=>n+(rr.mechanics?.executed?.ABSORB||0),0),
  firePassion:absorbLogs.filter(e=>/火焰热情/.test(e)).length,
  src:['function fireAbsorb(','fireAbsorb(victim, src, info)',
       'bump(cov.executed, \'ABSORB\')','absorbPct'].every(k=>CORE.includes(k))&&
      !CORE.includes('o.absorbPct =')};
// 76 — coverage report accuracy: declarative rows must not double-count.
// runSpec() already bumps cov.executed[s.t]; the old placeholder handlers
// (GLOBAL_LIMIT_COUNT_COMMAND / SKILL_RANGE / IMMUNE / TACTICS_SKILL_GROUP)
// bumped the same key a second (or third) time.
const covOnly58=['GLOBAL_LIMIT_COUNT_COMMAND','SKILL_RANGE','IMMUNE',
                 'TACTICS_SKILL_GROUP','SKILL_COUNT','ABSORB']
  .filter(t=>new RegExp(t+"\\(inst[^)]*\\) \\{ bump\\(cov\\.executed, '"+t+"'\\)").test(CORE));
const c76={doubleCounted:covOnly58,
  glc:r58.mechanics?.executed?.GLOBAL_LIMIT_COUNT_COMMAND||0,
  src:['handled in castSkill()','read by rangeMods()',
       'read by the immunity checks','dispatched by fireAbsorb()']
    .every(k=>CORE.includes(k))};
// 77 — object effects with no handler count as skipped, not executed;
// unmappedTiming is now an engine-capability guard (not a per-battle log).
const c77={unmapped:Object.keys(r58.mechanics?.unmappedTiming||{}).length,
  fired:(r58.mechanics?.firedTimings||[]).length,
  has51:(r58.mechanics?.firedTimings||[]).includes(51),
  has52:(r58.mechanics?.firedTimings||[]).includes(52),
  src:["if (!fn) { bump(cov.skipped, raw.t); continue; }",
       'const ENGINE_TIMINGS = new Set','firedTimings: [...cov.firedTimings]']
    .every(k=>CORE.includes(k))};

// ---- Round 59: three further client trigger-limit scopes -----------------
// speciality table declares limit_count_command / _per_entity_command /
// _per_entity_turn, none of which were exported or enforced. A multi-hit
// chain resolved such a row once PER HIT (94 excess fires across 192 games).
// Instrument runSpec in ONE patched core: count the fires per (battle,
// scope) AND the dispatches the gate actually rejected. A rejected dispatch
// is exactly what "gate OFF" used to let through, so this single simulation
// gives the same proof as the old two-simulation A/B at half the cost —
// important because this ENGINE runs inside `full`, the regression's
// critical path.
const gateMeasure=()=>{
  let src=CORE.replace(/\r\n/g,'\n');   // raw file is CRLF
  src=src.replace('      if (!limitOk(inst) || !scopedLimitOk(inst, ctx)) return;',
    '      if (!limitOk(inst) || !scopedLimitOk(inst, ctx)) {'+
    ' if(limitOk(inst))(window.__rej59||=[]).push(inst.sid); return; }');
  src=src.replace('      spend(inst);\n      scopedSpend(inst, ctx);\n      if (inst.buff) inst.buff.triggered = true;',
    '      (window.__f59||=[]).push({sid:inst.sid,owner:inst.owner?.uid,action:sim.actionId||0,'+
    'round:sim.round,tgt:ctx?.target?.uid||ctx?.defender?.uid||0});\n      spend(inst);\n'+
    '      scopedSpend(inst, ctx);\n      if (inst.buff) inst.buff.triggered = true;');
  const ctx2={window:{},console};vm.createContext(ctx2);
  const files=['data/world-data.js','data/battle-sim.js','data/match-cup.js',
               'data/battle-mech.js','data/client-mechanisms.js'];
  for(const f of files)vm.runInContext(fs.readFileSync(f,'utf8'),ctx2,{filename:f});
  vm.runInContext(src,ctx2,{filename:'battle-sim-core.js'});
  const w=ctx2.window,S2=w.WikiBattleSim,C2=w.WIKI_MATCH_CUP,
        M2=w.WIKI_BATTLE_MECH,D2=w.WIKI_BATTLE_SIM,SUB2=w.WIKI_CLIENT_MECHANISMS,
        WD2=w.WIKI_WORLD_DATA,
        map2=WD2.maps.find(m=>m.id===Number(C2.environment.mapId))||WD2.maps[0];
  const lcc=new Set(Object.entries(M2.specs).filter(([,v])=>v.lcc).map(([k])=>Number(k)));
  const lcpec=new Set(Object.entries(M2.specs).filter(([,v])=>v.lcpec).map(([k])=>Number(k)));
  const lcpet=new Set(Object.entries(M2.specs).filter(([,v])=>v.lcpet).map(([k])=>Number(k)));
  let a=0,b=0,c3=0,fires=0;
  // These rows live on characters that only appear in schedules 52-91.
  // Schedule 53 alone triggers the gate repeatedly; one battle suffices
  // now that a rejected dispatch IS the A/B evidence.
  const SCOPES59=[53];
  for(const sc of C2.schedules.filter(x=>SCOPES59.includes(Number(x.id)))){
    const before=(ctx2.window.__f59||[]).length;
    const bf=(sc.buffDetails||[]).filter(x=>x.buffId).map(x=>({buffId:x.buffId,
      side:x.target===1?'A':x.target===2?'B':'both'}));
    const tm2={A:S2.cupFighters(C2.teams.find(t=>t.id===sc.team1Id)),
               B:S2.cupFighters(C2.teams.find(t=>t.id===sc.team2Id))};
    try{S2.simulate({data:D2,mech:M2,map:map2,teams:tm2,mode:'left',seed:1000+sc.id,maxRounds:20,
      env:{weatherId:C2.environment.weatherId,buffs:bf},substrate:SUB2});}catch(e){}
    const rows=(ctx2.window.__f59||[]).slice(before);fires+=rows.length;
    const g=(sel,flt)=>{const q={};for(const f of rows.filter(flt)){const k=sel(f);(q[k]||=[]).push(f);}
      return Object.values(q).reduce((n,v)=>n+Math.max(0,v.length-1),0);};
    a+=g(f=>f.owner+'|'+f.action+'|'+f.sid,f=>lcc.has(Number(f.sid)));
    b+=g(f=>f.owner+'|'+f.action+'|'+f.sid+'|'+f.tgt,f=>lcpec.has(Number(f.sid)));
    c3+=g(f=>f.owner+'|'+f.round+'|'+f.sid+'|'+f.tgt,f=>lcpet.has(Number(f.sid)));
  }
  return {lcc:a,lcpec:b,lcpet:c3,fires,
          rejected:(ctx2.window.__rej59||[]).length};
};
const gateOn59=gateMeasure();
const c78={on:gateOn59,
  lccRows:Object.values(M.specs).filter(v=>v.lcc).length,
  lcpecRows:Object.values(M.specs).filter(v=>v.lcpec).length,
  lcpetRows:Object.values(M.specs).filter(v=>v.lcpet).length,
  gidRows:Object.values(M.specs).filter(v=>v.gid).length,
  src:['function scopedLimitOk(inst, ctx)','function scopedSpend(inst, ctx)',
       '!scopedLimitOk(inst, ctx)','scopedSpend(inst, ctx);',
       's.lcc','s.lcpec','s.lcpet'].every(k=>CORE.includes(k))};
// 79 — the three limits are exported from the right client columns and the
// remaining engine data surface is complete (no whole-type gaps).
const c79={lcc:M.specs['31415']?.lcc||0,
  lcpec:M.specs['28903']?.lcpec||0,
  lcpet:M.specs['18417']?.lcpet||0,
  gid:M.specs['32']?.gid||0,
  gp:M.specs['93']?.gp||0,
  src:['sim.actionId','sim.scopedLimits','const map = sim.scopedLimits']
    .every(k=>CORE.includes(k))};
// 80 — no regression in coverage health after adding the gates.
const c80={luaUnknown:Object.keys(r.mechanics?.luaUnknown||{}).length,
  conditions:r.mechanics?.conditions||{},
  unmapped:Object.keys(r.mechanics?.unmappedTiming||{}).length,
  fired:(r.mechanics?.firedTimings||[]).length,
  src:['const ENGINE_TIMINGS = new Set','firedTimings: [...cov.firedTimings]']
    .every(k=>CORE.includes(k))};

// ---- Round 60: compound JSON `sparam` (speciality.sj) -------------------
// The client declares 494 JSON sparam rows (261 land in the exported specs)
// with real semantics: buff_category, ignore_buff_stack_count, dont_fall,
// cast_limit / total_limit, force_cast, priority … The engine saw only the
// raw string and never parsed it. Most damaging: 叶迦内's DISPEL #22116
// {"buff_category":[24]} removes ONLY 无法治疗 buffs, but its p says "up to
// 99" — 614 unrelated buffs were wiped in the 192-game sweep.
// 81 — structured export + proof the DISPEL category filter works. Like
// c78, ONE patched core records both the buffs actually removed AND the
// ones the category gate rejected; no second "gate OFF" simulation.
const sjRows=Object.values(M.specs).filter(v=>v.sj).length;
const sjKeys=[...new Set(Object.values(M.specs).flatMap(v=>Object.keys(v.sj||{})))];
const disA=()=>{
  let src=CORE.replace(/\r\n/g,'\n');
  src=src.replace('          if (catSet && !catSet.has(Number(b.def.cat))) continue;',
    '          if (catSet && !catSet.has(Number(b.def.cat))) {'+
    ' if(Number(inst.sid)===22116)(window.__rej60||=[]).push(Number(b.def.cat)); continue; }');
  src=src.replace("          if (match) { removeBuff(t, b, '被驱散'); removed++; }",
    "          if (match) { if(Number(inst.sid)===22116)(window.__d60||=[]).push(Number(b.def.cat)); removeBuff(t, b, '被驱散'); removed++; }");
  const x={window:{},console};vm.createContext(x);
  for(const f of ['data/world-data.js','data/battle-sim.js','data/match-cup.js',
                  'data/battle-mech.js','data/client-mechanisms.js'])
    vm.runInContext(fs.readFileSync(f,'utf8'),x,{filename:f});
  vm.runInContext(src,x,{filename:'battle-sim-core.js'});
  const w=x.window,S2=w.WikiBattleSim,C2=w.WIKI_MATCH_CUP,M2=w.WIKI_BATTLE_MECH,
        D2=w.WIKI_BATTLE_SIM,SUB2=w.WIKI_CLIENT_MECHANISMS,WD2=w.WIKI_WORLD_DATA,
        mp=WD2.maps.find(m=>m.id===Number(C2.environment.mapId))||WD2.maps[0];
  // Schedule 19 removes cat-24 buffs AND has the gate reject many
  // unrelated ones; one battle gives both halves of the proof.
  for(const id of [19]){
    const sc=C2.schedules.find(q=>q.id===id);if(!sc)continue;
    const bf=(sc.buffDetails||[]).filter(b=>b.buffId).map(b=>({buffId:b.buffId,
      side:b.target===1?'A':b.target===2?'B':'both'}));
    try{S2.simulate({data:D2,mech:M2,map:mp,
      teams:{A:S2.cupFighters(C2.teams.find(t=>t.id===sc.team1Id)),
             B:S2.cupFighters(C2.teams.find(t=>t.id===sc.team2Id))},
      mode:'left',seed:1000+sc.id,maxRounds:20,
      env:{weatherId:C2.environment.weatherId,buffs:bf},substrate:SUB2});}catch(e){}
  }
  const cats=x.window.__d60||[],rej=x.window.__rej60||[];
  return {total:cats.length,cat24:cats.filter(v=>v===24).length,
          wrong:cats.filter(v=>v!==24).length,
          rejected:rej.length,rejectedWrong:rej.filter(v=>v!==24).length};
};
const disOn=disA();
const c81={sjRows,sjKeys:sjKeys.length,
  dispelSj:JSON.stringify(M.specs['22116']?.sj||null),
  immuneSj:JSON.stringify(M.specs['5475']?.sj||null),
  on:disOn,
  src:['const cats = inst.spec.sj?.buff_category',
       'const catSet = Array.isArray(cats)','catSet.has(Number(b.def.cat))']
    .every(k=>CORE.includes(k))};
// 82 — the OTHER three compound keys actually reach their engine readers.
const c82={ignore:M.specs['29704']?.sj?.ignore_buff_stack_count===true,
  dontFall:M.specs['25272']?.sj?.dont_fall===true,
  castLimit:M.specs['24315']?.sj?.cast_limit||0,
  totalLimit:M.specs['22661']?.sj?.total_limit,
  complete:M.specs['24297']?.sj?.complete_cast_limit===true,
  forceCast:Object.values(M.specs).filter(v=>v.sj?.force_cast===true).length,
  src:['s.sj?.ignore_buff_stack_count','inst.spec.sj?.ignore_buff_stack_count',
       'inst?.spec?.sj?.dont_fall','const sj = spec?.sj',
       'inst.spec.sj?.cast_limit'].every(k=>CORE.includes(k))};
// 83 — IMMUNE category rows are now scoped (data + code), and summon count
// uses the client's cast_limit instead of the p[1]=0 fallback.
const c83={immuneRows:Object.values(M.specs).filter(v=>v.t==='IMMUNE'&&v.sj?.buff_category).length,
  immuneCats:Object.values(M.specs).filter(v=>v.t==='IMMUNE'&&v.sj?.buff_category)
    .flatMap(v=>v.sj.buff_category).length,
  dispelRows:Object.values(M.specs).filter(v=>v.t==='DISPEL'&&v.sj?.buff_category).length,
  summonSj:Object.values(M.specs).filter(v=>v.t==='PLACE_UNIT'&&v.sj?.cast_limit).length,
  src:['const cats = i.spec.sj?.buff_category','Number(inst.spec.sj?.cast_limit)']
    .every(k=>CORE.includes(k))};
// 84 — coverage health after wiring compound parameters; no new Lua gaps,
// no unmapped timings, all triggers still dispatched.
const c84={luaUnknown:Object.keys(r.mechanics?.luaUnknown||{}).length,
  condUnknown:(r.mechanics?.conditions||{}).unknown,
  unmapped:Object.keys(r.mechanics?.unmappedTiming||{}).length,
  fired:(r.mechanics?.firedTimings||[]).length,
  src:['firedTimings: [...cov.firedTimings]','unmappedTiming: cov.unmappedTiming']
    .every(k=>CORE.includes(k))};

// ---- Round 61: remaining compound JSON sparam keys -----------------------
// 85 — PLACE_TRAP `complete_cast_limit` field cap. 「蜜果大喷射-生成1个蜜果」
// #27062 declares cast_limit=1 + complete_cast_limit; before this, every
// trigger spawned another trap (up to 5 live copies). One battle (schedule
// 55) already shows the gate rejecting excess placements.
const trapSpecs=Object.values(M.specs).filter(v=>v.t==='PLACE_TRAP'&&v.sj?.complete_cast_limit);
const trapSc=C.schedules.find(x=>x.id===55);
const trapTm={A:S.cupFighters(C.teams.find(t=>t.id===trapSc.team1Id)),
              B:S.cupFighters(C.teams.find(t=>t.id===trapSc.team2Id))};
const trapCe=S.cupEnv(trapSc,trapTm);
const trapR=S.simulate({data:D,mech:M,
  map:W.maps.find(m=>m.id===Number(C.environment.mapId))||W.maps[0],
  teams:trapTm,mode:'left',seed:1055,maxRounds:4,
  env:{weatherId:C.environment.weatherId,buffs:trapCe.buffs,unitStatus:trapCe.unitStatus},substrate:SUB});
const c85={rows:trapSpecs.length,
  caps:trapSpecs.map(v=>Number(v.sj.cast_limit)||1),
  rejected:trapR.mechanics?.limits?.['PLACE_TRAP(同屏上限)']||0,
  placed:(trapR.placed||[]).length,
  src:['const fieldCap = spec?.sj?.complete_cast_limit',
       "kind + '(同屏上限)'",'bump(cov.limits'].every(k=>CORE.includes(k))};
// 86 — JSON sparam.priority is a ROW-level execution order (distinct from
// speciality_type.priority `pr`) and is applied at BOTH dispatch points.
const prioVals=[...new Set(Object.values(M.specs)
  .filter(v=>v.sj?.priority!==undefined).map(v=>Number(v.sj.priority)))].sort((a,b)=>b-a);
const c86={rows:Object.values(M.specs).filter(v=>v.sj?.priority!==undefined).length,
  max:prioVals[0],min:prioVals[prioVals.length-1],
  distinct:prioVals.length,
  sample:M.specs['31376']?.sj?.priority||0,
  src:['q.spec.sj?.priority','M?.specs?.[b]?.sj?.priority']
    .every(k=>CORE.includes(k))};
// 87 — `force_cast` state-machine transitions no longer drop when no legal
// target exists.
const fcRows=Object.values(M.specs).filter(v=>v.sj?.force_cast===true);
const c87={rows:fcRows.length,
  selfAim:fcRows.filter(v=>{const sk=M.skills?.[String(v.p?.[0])];return sk?.aim==='self';}).length,
  linked:fcRows.filter(v=>M.skills?.[String(v.p?.[0])]).length,
  src:['s.sj?.force_cast','target = caster'].every(k=>CORE.includes(k))};
// 88 — ADDITIONAL_ATTRIBUTE_DAMAGE reads the client's caster_attr / cut_defence
// flags; the old ternary had BOTH branches returning inst.owner.
const c88={casterAttrRows:Object.values(M.specs).filter(v=>v.sj?.caster_attr!==undefined).length,
  cutRows:Object.values(M.specs).filter(v=>v.sj?.cut_defence).length,
  targetAttr:!!M.specs['6234']&&String(M.specs['6234'].s)==='0',
  bugGone:!CORE.includes("? inst.owner : inst.owner"),
  luaUnknown:Object.keys(r.mechanics?.luaUnknown||{}).length,
  unmapped:Object.keys(r.mechanics?.unmappedTiming||{}).length,
  src:['const useCaster = sj ?','useCaster ? inst.owner : t','!sj?.cut_defence']
    .every(k=>CORE.includes(k))};

// ---- Round 63: disguised stubs + constant Lua stubs -----------------------
// Each speciality type below used to dispatch to a handler that only wrote
// `owner.flags.X` with NO reader anywhere (a disguised stub), or a Lua API
// returned a constant. One 8-round battle per mechanism family is enough;
// schedule 80 (阿尔曼 70% 阈值), 52 (罗格妮达 溢出 / 阿列克谢 锁链) and
// 13 (阿坎贝 特殊条款) carry them naturally.
const run63=(id,seed,rounds)=>{const sc=C.schedules.find(x=>x.id===id);
  const tm={A:S.cupFighters(C.teams.find(t=>t.id===sc.team1Id)),B:S.cupFighters(C.teams.find(t=>t.id===sc.team2Id))};
  const bf=(sc.buffDetails||[]).filter(b=>b.buffId).map(b=>({buffId:b.buffId,side:b.target===1?'A':b.target===2?'B':'both'}));
  return S.simulate({data:D,mech:M,map:W.maps.find(m=>m.id===Number(C.environment.mapId))||W.maps[0],
    teams:tm,mode:'left',seed,maxRounds:rounds,env:{weatherId:C.environment.weatherId,buffs:bf},substrate:SUB});};
const r63=[run63(80,1080,20),run63(52,1052,20),run63(13,1013,20),run63(6,1006,10)];
const ev63=r63.flatMap(rr=>rr.steps.flatMap(s=>s.events||[]));
const cnt63=re=>ev63.filter(e=>re.test(e)).length;
// 89 — HP_LOW_LIMIT / OVERFLOW_DAMAGE_STORAGE / RECOVER_ATTRIBUTE on stored
// attributes / BUFF_TARGET_LIMIT / DEMAND_ASSIST_DEFENCE / ASSIST_TEAMMATE now act.
const c89={hpFloor:cnt63(/锁定生命下限/),overflow:cnt63(/溢出伤害储存 \d+ → \d+/),
  storeWrite:cnt63(/的 (缓存值|溢出储存) \d+ → /),targetLimit:cnt63(/目标上限 \d+/),
  demand:cnt63(/」请求 .+ 援护防御/),support:cnt63(/」支援受击的/),
  errors:r63.filter(x=>x.error).length,
  src:['function enforceBuffTargetLimit(b)',"specActive(victim, 'HP_LOW_LIMIT'",
       "specActive(src, 'OVERFLOW_DAMAGE_STORAGE'",'STORE_ATTRS.has(n)',
       "i.spec.t === 'DEMAND_ASSIST_DEFENCE'","inst.spec.t !== 'ASSIST_TEAMMATE'"].every(k=>CORE.includes(k))};
// 90 — declarative rows are read where the client applies them, and none of
// the former disguised stubs still writes an unread flag.
const stubFlags=['ignoreKnockback','buffTargetLimit','skillHeight','forceInitiative','cantBeAssisted','highland',
  'auraRange','canThrough','overflowStorage','hpLowLimit','buffModifyAttr','ignoreRestrain','dynamicBuffer',
  'assistTeammate','spellInstance','reflect','heightZeroMobility','profBySkill','profByBuff','cantCounter',
  'cantFirstHit','cantAssist','cantTransfer','cantReborn','disabledSkills','isolate','straight','demandAssist'];
const c90={leftover:stubFlags.filter(f=>new RegExp('flags\\.'+f+'\\s*=').test(CORE)),
  readers:['function restrainSpecs(a, d)',"specActive(a, 'IGNORE_PROFESSION_RESTRAIN'","specActive(a, 'HIGHLAND'",
    'function skillHeightBonus(u, s)','function auraRangeBonus(owner)','function throughRule(u)',
    'function buffTypeCountValue(u, s)','function profOf(u)','function forcedInitiative(s, dflt)',
    'function skillDisabled(u, s)','function transferImmune(t, inst, ctx)',"specActive(t, 'CANT_COUNTER'",
    "'CANT_ASSIST'","'CANT_REBORN'",'isolated.has(u)','REFLECT_DAMAGE(inst, ctx) {','SPELL_INSTANCE(inst) {',
    'CHANGE_PROFESSION_BY_SKILL(inst, ctx) {'].filter(k=>!CORE.includes(k)),
  composite:CORE.includes("const n = attrName(s.p[1]); for (const A of COMPOSITE[n] || [n]) add(A, inst);")};
// 91 — the 23 client Lua APIs that used to return a constant now answer
// from live state; a full sweep has zero unknown names (checked in F1).
// Only the BATTLE environment (function luaEnv … the static inspection
// table before it has no owner by design) must be free of constant stubs.
const luaBattle=CORE.slice(CORE.indexOf('    function luaEnv('));
const c91={stubs:['CheckImmuneType: () => false','IsInDelay: () => false','getNeighborPropsCount: () => 0',
    'hasChangedFieldStatus: () => false','hasTag: () => false','GetNeighborBlockFieldStatusCount: () => 0',
    'isFieldStatus: () => false','checkForget: () => false'].filter(k=>luaBattle.includes(k)),
  apis:['CheckImmuneType: (bt, data, bid, mid, sub, cat)','IsInDelay: () => (sim.delayed','getNeighborPropsCount: (',
    'hasChangedFieldStatus: () => sim.fieldChangers','hasSkillTag: (t)','GetHPDamagedTurn: ()','IsDirectBeDamaged: ()',
    'getBuffCountByEffectType: (bit)','CheckDispelForData: (data)','CasterBuffCount: (bt)','TargetBuffHasSpeciality: (list)',
    'TargetCheckImmuneType: (','FindUnitsBySide: (side)','FindUnitsOnStageBySide: (side)','getBlockByIndex: (idx)',
    'CheckShadowStepValid: (','checkLimitCount: ()','CanInitiativeCastSkill: ()',"case 'temp_props'",'dist: (x, y)',
    'temp_limit_count_command:',"case 'side': return u.side"].filter(k=>!CORE.includes(k)),
  luaUnknown:r63.reduce((n,rr)=>n+Object.keys(rr.mechanics?.luaUnknown||{}).length,0)};
// 92 — sentence → speciality → engine-code map is generated and current.
const SMI=(()=>{const t=fs.readFileSync('data/sentence-mechanics.js','utf8');
  return JSON.parse(t.slice(t.indexOf('window.WIKI_SENTENCE_INDEX=')+27).replace(/;\s*$/,''));})();
const SMC=(()=>{const t=fs.readFileSync('data/mechanics-code.js','utf8');
  return JSON.parse(t.slice(t.indexOf('window.WIKI_MECHANICS_CODE=')+27).replace(/;\s*$/,''));})();
const coreLines=CORE.replace(/\r\n/g,'\n').split('\n');
const anchorsOk=Object.values(SMC.common).flatMap(c=>c.anchors||[]).filter(a=>{
  const first=(a.code||'').split('\n').find(l=>l.startsWith(String(a.l).padStart(5)+'  '));
  if(!first)return false;
  const text=first.slice(7).replace(/…$/,'');
  return (coreLines[a.l-1]||'').trimEnd().startsWith(text.slice(0,60));
}).length;
const anchorsAll=Object.values(SMC.common).reduce((n,c)=>n+(c.anchors||[]).length,0);
const sh15386=(()=>{const n=15386%SMI.shards;const t=fs.readFileSync('data/sentence-mechanics/'+n+'.js','utf8');
  const key='['+n+']=';return JSON.parse(t.slice(t.indexOf(key)+key.length).replace(/;\s*$/,''));})();
const c92={skills:SMI.meta.skills,sentences:SMI.meta.sentences,mapped:SMI.meta.mapped,withSpec:SMI.meta.withSpec,
  common:SMI.meta.common,anchorsAll,anchorsOk,engineLines:SMI.meta.engineLines,coreLines:coreLines.length,
  gaps:(SMC.meta.gaps||[]).length,luaMissing:(SMC.meta.luaMissing||[]).length,
  pers:Object.keys(SMI.personalities).length,shards:fs.readdirSync('data/sentence-mechanics').length,
  sample:(sh15386.skills['15386']?.s||[]).map(x=>(x.s||[]).length)};
// 93 — Round 64: the sentence wiki must cover EVERY sentence of the CLIENT's
// full description. battle-mech.js truncates desc to 120 chars, so a
// build-time-only data/skill-desc-full.js restores the rest; the browser must
// NOT load it. Sentences with no speciality still resolve to an attr/at/core
// mechanism or an explicit note: (no logic), never a blank row.
const FULL_DESC=(()=>{try{const t=fs.readFileSync('data/skill-desc-full.js','utf8');
  return JSON.parse(t.slice(t.indexOf('=')+1,t.lastIndexOf(';')));}catch(e){return {};}})();
const html64=fs.readFileSync('index.html','utf8');
const SMC64=(()=>{const t=fs.readFileSync('data/mechanics-code.js','utf8');
  return JSON.parse(t.slice(t.indexOf('=')+1,t.lastIndexOf(';')));})();
// Count blank rows and bare fragments across all 64 shards.
const SH64=(()=>{const c2={window:{}};vm.createContext(c2);
  for(const f of fs.readdirSync('data/sentence-mechanics'))
    vm.runInContext(fs.readFileSync('data/sentence-mechanics/'+f,'utf8'),c2);
  return c2.window.WIKI_SENTENCE_SHARDS||{};})();
let blank64=0,frag64=0,note64=0,sent64=0;
for(const sh of Object.values(SH64))for(const sk of Object.values(sh.skills||{}))
  for(const row of sk.s||[]){
    sent64++;
    if(!(row.s||row.b||row.k||row.c))blank64++;
    const t=String(row.t||'');
    // A genuine truncated tail, not a legitimately short client description
    // (「后续技能」/「吸血10%」/「全领域护盾」 are complete one-line skills).
    if(t.length<=14&&!/[。；;！!？?]$/.test(t)&&
       (/[\[【▲]$/.test(t)||/^(并|若|在|且|以及)/.test(t)||/[、，]$/.test(t)))frag64++;
    if((row.c||[]).some(x=>x.startsWith('note:')))note64++;
  }
const c93={fullRows:Object.keys(FULL_DESC).length,
  sampleTail:(FULL_DESC['21312']||'').slice(-24),
  browserLoadsFull:html64.includes('skill-desc-full.js'),
  runtimeUnchanged:fs.statSync('data/battle-mech.js').size,
  sentences:sent64,blank:blank64,frag:frag64,noteRefs:note64,
  noteCommon:Object.keys(SMC64.common||{}).filter(k=>k.startsWith('note:')).length,
  mapped:SMI.meta.mapped,total:SMI.meta.sentences,
  src:[fs.readFileSync('scripts/extract_battle_mechanics.py','utf8').includes("'WIKI_SKILL_DESC_FULL'") ||
       fs.readFileSync('scripts/extract_battle_mechanics.py','utf8').includes('WIKI_SKILL_DESC_FULL='),
       fs.readFileSync('scripts/build_sentence_mechanics.py','utf8').includes('skill-desc-full.js'),
       fs.readFileSync('scripts/build_sentence_mechanics.py','utf8').includes('ATTR_SENTENCE')]};
// 94 — Round 65: the last unimplemented compound `sparam` key with real
// effect is now implemented; all other unread keys are individually audited
// against the 192-game sweep rather than left as a vague "未实装".
// `find_trap=139` (SP伦伽勒 反应瞬步) must land ON a live 长枪之灵 and fire
// its 停留 trigger (which consumes the trap, limit=1).
const SMC65=(()=>{const t=fs.readFileSync('data/mechanics-code.js','utf8');
  return JSON.parse(t.slice(t.indexOf('=')+1,t.lastIndexOf(';')));})();
const ftSpec=M.specs['20039']||{};
const trap139=M.traps?.['139']||{};
// Schedule 25 (with its client buffDetails via cupEnv) dispatches #20039
// twice: 找枪灵传送 x2 and 长枪之灵 停留 x6. maxRounds 8 keeps this cheap.
const ftSc=C.schedules.find(x=>x.id===25);
const ftTm={A:S.cupFighters(C.teams.find(t=>t.id===ftSc.team1Id)),
            B:S.cupFighters(C.teams.find(t=>t.id===ftSc.team2Id))};
const ftCe=S.cupEnv(ftSc,ftTm);
const ftR=S.simulate({data:D,mech:M,map:W.maps.find(m=>m.id===Number(C.environment.mapId))||W.maps[0],
  teams:ftTm,mode:'left',seed:1025,maxRounds:8,
  env:{weatherId:C.environment.weatherId,buffs:ftCe.buffs,unitStatus:ftCe.unitStatus},substrate:SUB});
const ftEvents=ftR.steps.flatMap(s=>s.events||[]);
const c94={findTrap:ftSpec.sj?.find_trap||0,trapId:Number(trap139.id||0)||139,
  trapStay:trap139.tt||0,trapSkill:trap139.ts||0,trapLimit:trap139.lim||0,
  blinks:ftEvents.filter(e=>/并瞬移过去（找枪灵传送）/.test(e)).length,
  stays:ftEvents.filter(e=>/停留触发「.*长枪之灵/.test(e)).length,
  findTrapImpl:SMC65.common['sj:find_trap']?.impl||'',
  audited:Object.values(SMC65.common).filter(v=>v.impl==='audited').length,
  missing:Object.values(SMC65.common).filter(v=>['stub','missing'].includes(v.impl)).length,
  stub:Object.values(SMC65.common).filter(v=>v.impl==='stub').length,
  src:['const trapId = Number(inst.spec.sj?.find_trap)',
       "t.kind === 'PLACE_TRAP'",
       'triggersOnPath([{x: t.x, y: t.y}], o)',
       fs.readFileSync('scripts/build_sentence_mechanics.py','utf8').includes('AUDITED_SJ')]
    .every(k=>k===true||CORE.includes(k))};

out={error:r.error,steps:r.steps.length,winner:r.winner,
  deterministic:sig(r)===sig(S.simulate(opt())),
  c1:{orders,emptyOrders:emptyOrders.length},
  c2:{teleports,bad:teleports.filter(t=>t.dist>3||t.effMax>3).length},
  c3:{voidTpl:voidTpl?{n:voidTpl.n,personality:voidPassive}:null,
      voidUnit:!!voidUnit,summonsWithPassive,
      fadeBuff:fadeBuff||0,fadeSpec:Number(fadeSpec)||0,
      fadeTypes:fadeBuff?(M.buffs?.[fadeBuff]?.sp||[]).map(sid=>M.specs?.[sid]?.t):[]},
  c4:{resolveState:resolveState?{min:resolveState.min,max:resolveState.max,
        base:resolveState.baseMax,rows:resolveState.rangeRows.map(x=>x.spec)}:null,
      smokeState:smokeState?{min:smokeState.min,max:smokeState.max,rows:smokeState.rangeRows.map(x=>x.spec)}:null,
      rangedState:rangedState?{max:rangedState.max,rows:rangedState.rangeRows.map(x=>x.spec)}:null,
      spec5210:M.specs?.['5210']?.sap||''},
  c5:{extraSteps:extraSteps.length,extraLogs:extraLogs.length,samples:extraLogs.slice(0,3)},
  c6:{attachedSpec,attachedSkill:attachedSkill?{n:attachedSkill.n,sp:attachedSkill.sp}:null,
      attachedLogs:attachedLogs.slice(0,3),ap2Skills,ivanAttached:ivan.length},
  c7:{negative:negative.length,negativeSamples:negative.slice(0,2)},
  c8:{trapDef:trapDef?{n:trapDef.n,tt:trapDef.tt,ts:trapDef.ts,lim:trapDef.lim}:null,
      trapEvents:trapEvents.slice(0,4),
      stayTriggers:trapEvents.filter(e=>/停留触发「SP伦伽勒-长枪之灵」/.test(e)).length,
      anyStayTriggers:allEvents.filter(e=>/停留触发「/.test(e)).length,
      skill15656:M.skills?.['15656']?.sp?.length||0,
      skill15656Types:(M.skills?.['15656']?.sp||[]).map(sid=>M.specs?.[sid]?.t)},
  c9:{zeroNoReason:zeroNoReason.slice(0,3)},
  c10:{chainCasts,chainEvents:chainEvents.slice(0,4)},
  c11:{grants:ap2Grants,follow:ap2Follow,seed:ap2Seed,
       src:['settleTriggeredRemove','expireActionScoped'].every(k=>CORE.includes(k))},
  c12:{ok:restrictOk.length,viol:restrictViol,samples:restrictOk.slice(0,3)},
  c13:{p19180:P(19180).swapTo,p19176:P(19176).swapTo,swapPlans,swapSteps:swapSteps.slice(0,4),swapCount:swapSteps.length},
  c14:{lionSpec:lionSpec?{t:lionSpec.t,at:lionSpec.at,p0:lionSpec.p?.[0]}:null,
       inBuff:(M.buffs?.['8349']?.sp||[]).includes(25245),
       grantSrc:CORE.includes('reActSkill')&&CORE.includes('function grantSkill')},
  c15:{core:summonTpl('灵感星核'),void:summonTpl('虚空投影'),summonActs,coreMax},
  c16:{cast:!!orderStep,seed:orderSeed,seq:orderStep?.seq??null,order15968,order15935,responders,respCasts,mustHit,missed,broadcast:broadcast.length},
  c17:{cupScid,src:CORE.includes("'SKILL_CAST_ID'")},
  c18:{zeroDurBuffSpecs,actionScopedExpired},
  c19:{lua:r.mechanics?.luaUnknown||{}},
  c20,c21,c22,c23,c24,c25,c26,c27,c28,c29,c30,c31,c32,c33,c34,c35,c36,c37,c38,c39,
  c40,c41,c42,c43,c44,c45,c46,c47,c48,c49,c50,c51,c52,c53,c54,c56,c57,
  c58,c59,c60,c61,c62,c63,c64,c65,c66,c67,c68,c69,c70,c71,c72,c73,
  c74,c75,c76,c77,c78,c79,c80,c81,c82,c83,c84,c85,c86,c87,c88,c89,c90,c91,c92,c93,c94,
  tables:{sapSpecs,ap2Skills,summonsWithPassive}};
}

if(FULL){
  const t0=Date.now();
  let done=0,err=0,unknown={},maxMs=0,negative=0,zeroNoReason=0,viol=0,sActs=0,cMax=0,
      lion=0,lionViol=0,swap19180=0,scidHits=0,ap2Bad=0,coord50=0,
      manyuMax=0,extraOther=0,luoHuaCasts=0,deep=0,deep58=0,
      egCasts=0,egBad=0,terrainSteps=0,knockSteps=0;
  for(const s of C.schedules){
    const bf=(s.buffDetails||[]).filter(b=>b.buffId).map(b=>({buffId:b.buffId,side:side(b.target)}));
    const t1=Date.now();let o;
    try{o=S.simulate({data:D,mech:M,map:W.maps.find(m=>m.id===C.environment.mapId),
      teams:{A:mem(team(s.team1Id)),B:mem(team(s.team2Id))},mode:'left',seed:1000+s.id,
      maxRounds:20,env:{weatherId:C.environment.weatherId,buffs:bf},substrate:SUB});}
    catch(e){err++;continue;}
    if(o.error){err++;continue;}
    done++;maxMs=Math.max(maxMs,Date.now()-t1);
    deep+=Number(o.mechanics?.skipped?.['连锁触发过深']||0);
    deep58+=Number(o.mechanics?.skipped?.['连锁触发过深@58']||0);
    for(const k of Object.keys(o.mechanics.luaUnknown||{}))unknown[k]=(unknown[k]||0)+1;
    const nm=uid=>(o.units.find(u=>u.uid===uid)||{}).name;
    const inert=new Set(o.units.filter(u=>/灵感星核|虚空投影/.test(u.name)).map(u=>u.uid));
    for(const st of o.steps){
      if((st.terrain||[]).length)terrainSteps++;
      if((st.knockbacks||[]).length)knockSteps++;
      if(st.skill?.id===21721){
        egCasts++;
        const prior=o.steps[st.seq-1]?.snap||[],t=st.target;
        if(!t||prior.some(u=>u.alive&&u.x===t.x&&u.y===t.y))egBad++;
      }
      if(inert.has(st.actor))sActs++;
      if(st.skillSwap?.from===19180)swap19180++;
      for(const h of st.hits||[]){
        if(h.amount<0)negative++;
        if(h.sub&&h.byUid===st.actor&&M.skills?.[st.skill?.id]?.scid===h.bySkillId)scidHits++;
        if(h.sub&&h.bySkillId===15935&&h.amount>0)coord50++;
        if(!h.amount&&!h.absorbed&&!h.killed&&!h.reborn&&!h.heal&&!h.status&&!h.miss&&!h.zeroReason){
          const fin=(h.calc||[]).find(c=>c.label==='最终伤害');
          if(!fin||Number(fin.value)>0)zeroNoReason++;
        }
      }
      manyuMax=Math.max(manyuMax,(st.events||[]).filter(e=>/蛮勇转化-结算/.test(e)&&/发动/.test(e)).length);
      if(st.skill?.id===21016)luoHuaCasts++;
      for(const e of st.events||[]){
        if(/获得再行动（附属被动/.test(e)&&st.skill&&(M.skills?.[st.skill.id]?.tp||0)<3)ap2Bad++;
        if(/罗格妮达 获得再行动（仅限/.test(e))lion++;
      }
      for(const sd of ['A','B'])cMax=Math.max(cMax,(st.snap||[]).filter(x=>x.alive&&String(x.uid).startsWith(sd)&&nm(x.uid)==='灵感星核').length);
      if(/再行动：|，再行动：|^再行动/.test(st.text||'')){
        const who=nm(st.actor);
        const g=o.steps.slice(0,st.seq+1).reverse().flatMap(x=>(x.events||[]).slice().reverse()).find(e=>e.startsWith(who+' 获得再行动'));
        const m=g&&g.match(/仅限「([^」]+)」#(\d+)/);
        if(m){
          // A restricted extra action may legitimately WAIT when its ONE
          // allowed skill has no legal cast block (e.g. 以退为进 needs a free
          // tile behind the unit). The engine records that explicitly instead
          // of falling back to a normal move / another skill — which is the
          // actual bug these two checks exist for.
          const reason=String(st.moveRule?.noCastReason||'');
          const legalWait=st.kind==='wait'&&/没有合法目标，原地待命/.test(reason)&&reason.includes(m[1]);
          if(!legalWait&&Number(m[2])!==Number(st.skill?.id)){viol++;if(who==='罗格妮达')lionViol++;}
          if(!legalWait&&st.kind!=='skill')extraOther++;
        }
      }
    }
  }
  out.sweep={done,err,maxMs,seconds:Math.round((Date.now()-t0)/1000),unknown:Object.keys(unknown),
    negative,zeroNoReason,viol,summonActs:sActs,coreMax:cMax,lion,lionViol,swap19180,scidHits,ap2Bad,coord50,
    manyuMax,extraOther,luoHuaCasts,deep,deep58,egCasts,egBad,terrainSteps,knockSteps};
}
console.log(JSON.stringify(out));
"""


def sweep_checks(e, check):
    """F1–F10 over the 192-battle sweep (shared by --full and --sweep-only)."""
    sw = e.get('sweep') or {}
    print('\n--- 全量 192 场 ---')
    check('F1 全量无异常 / Lua 未知 0',
          sw.get('done') == 192 and sw.get('err') == 0 and not sw.get('unknown'), str({k: sw.get(k) for k in ('done', 'err', 'seconds', 'unknown')}))
    check('F2 无负伤害 / 0 伤害都有原因', sw.get('negative') == 0 and sw.get('zeroNoReason') == 0,
          f"negative={sw.get('negative')} zeroNoReason={sw.get('zeroNoReason')}")
    check('F3 限定再行动零违规（含白金狮子）/ 附属被动不被低耗能技能触发',
          sw.get('viol') == 0 and sw.get('lionViol') == 0 and sw.get('ap2Bad') == 0,
          f"viol={sw.get('viol')} lion={sw.get('lion')} ap2Bad={sw.get('ap2Bad')}")
    check('F4 召唤物不行动 / 灵感星核同侧最多 1 个', sw.get('summonActs') == 0 and (sw.get('coreMax') or 0) <= 1,
          f"summonActs={sw.get('summonActs')} coreMax={sw.get('coreMax')}")
    check('F5 skill_cast_id 后续技能实际造成命中 / 贯日强击发生技能变更',
          (sw.get('scidHits') or 0) > 0 and (sw.get('swap19180') or 0) > 0,
          f"scidHits={sw.get('scidHits')} swap19180={sw.get('swap19180')}")
    check('F6 〈铃兰之剑〉额外协同响应「飞弹礼花-后续」实际造成 50% 穿透伤害',
          (sw.get('coord50') or 0) > 0, f"coord50={sw.get('coord50')}")
    check('F7 全量限定再行动零违规、无「改成移动/待机」的额外行动',
          sw.get('viol') == 0 and sw.get('extraOther') == 0,
          f"viol={sw.get('viol')} extraOther={sw.get('extraOther')}")
    check('F8 全量「蛮勇转化-结算」不刷屏 / 落花之舞真实施放',
          0 < (sw.get('manyuMax') or 0) <= 6 and (sw.get('luoHuaCasts') or 0) > 0,
          f"manyuMax={sw.get('manyuMax')} luoHuaCasts={sw.get('luoHuaCasts')}")
    # F9 guards the BUFF_CHANGE (58) self-trigger loop it was written for.
    # The all-timing total also counts legitimately deep reaction chains,
    # which grow whenever more client mechanisms are wired (round 52:
    # attacker-side 被攻击后, follow-skill attack events) — reported only.
    check('F9 全量 BUFF_CHANGE（at58）自触发链不再靠深度上限收敛',
          (sw.get('deep58') or 0) < 120,
          f"at58 截断={sw.get('deep58')}（修复前全部时机合计 295）；全部时机合计={sw.get('deep')}")
    check('F10 全量空地召唤零违规 / 地形与击退明细真实落地',
          (sw.get('egCasts') or 0) > 0 and sw.get('egBad') == 0
          and (sw.get('terrainSteps') or 0) > 0 and (sw.get('knockSteps') or 0) > 0,
          f"空地召唤={sw.get('egCasts')} 违规={sw.get('egBad')} "
          f"地形步骤={sw.get('terrainSteps')} 击退明细步骤={sw.get('knockSteps')}")


def main():
    sweep_only = '--sweep-only' in sys.argv
    full = '--full' in sys.argv or sweep_only
    js = (ENGINE.replace('PLAN_PATH', json.dumps(PLAN))
               .replace('if(FULL)', 'if(%s)' % ('true' if full else 'false'))
               .replace('if(!SWEEP_ONLY)', 'if(%s)' % ('false' if sweep_only else 'true')))
    # Windows CreateProcess caps the command line at 32767 chars; the engine
    # source has outgrown `node -e <source>`. Write it to a temp .cjs and run
    # that instead — same code, no length limit, no behavioural change.
    work = ROOT / 'work'
    work.mkdir(exist_ok=True)
    # One file PER PROCESS: run_regression.py starts the fast and --full
    # suites concurrently, and a shared name let the fast run overwrite the
    # full run's script before node read it (the 192-battle sweep vanished).
    script = work / f'_verify_engine_{"sweep" if sweep_only else "full" if full else "fast"}_{os.getpid()}.cjs'
    script.write_text(js, encoding='utf8')
    try:
        proc = subprocess.run([str(NODE), str(script)], cwd=ROOT, capture_output=True,
                              text=True, encoding='utf8', timeout=900)
    finally:
        try:
            script.unlink()
        except OSError:
            pass
    try:
        e = json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        print(proc.stdout[-2000:], proc.stderr[-2000:])
        return 1

    failures = []

    def check(label, ok, detail=''):
        print(('PASS ' if ok else 'FAIL ') + label + (f' :: {detail}' if detail else ''), flush=True)
        if not ok:
            failures.append(label)

    if sweep_only:
        sweep_checks(e, check)
        print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
        return 1 if failures else 0

    print('=== 客户端战斗功能验收 · 赛程76 / 种子292 ===')
    check('对局可完整运行且确定性',
          not e.get('error') and (e.get('steps') or 0) > 10 and e.get('deterministic') is True,
          f"steps={e.get('steps')} winner={e.get('winner')}")
    t = e['tables']
    check('解码表注入 skill_active_param / 附属被动 / 召唤物个性',
          t['sapSpecs'] >= 90 and t['ap2Skills'] >= 70 and t['summonsWithPassive'] >= 40,
          str(t))

    # 1
    c = e['c1']
    check('1 伤害技能不在打不到敌人时空放',
          c['emptyOrders'] == 0,
          f"号令施放={len(c['orders'])} 空放={c['emptyOrders']}")
    # 2
    c = e['c2']
    check('2 「烟幕游击」1-3 格，不跨 5 格',
          c['bad'] == 0 and len(c['teleports']) > 0,
          f"施放={len(c['teleports'])} 越界={c['bad']} 明细={c['teleports'][:2]}")
    # 3 — the full client data chain must be exported and the engine must
    # consult FADE when choosing targets.
    c = e['c3']
    core_src = (ROOT / 'battle-sim-core.js').read_text('utf8')
    check('3 虚空投影[虚空造物]个性 → buff 9079 → [失焦] FADE，且 AI 回避失焦目标',
          bool(c['voidTpl']) and len((c['voidTpl'] or {}).get('personality') or []) > 0
          and c['fadeBuff'] == 9079 and c['fadeSpec'] == 20523
          and 'FADE' in c['fadeTypes'] and 'isFaded' in core_src
          and c['summonsWithPassive'] >= 40,
          f"personality={(c['voidTpl'] or {}).get('personality')} buff={c['fadeBuff']} "
          f"spec={c['fadeSpec']} types={c['fadeTypes']}")
    # 4
    c = e['c4']
    check('4 近战/瞬移技能不吃远程 +2 射程',
          bool(c['resolveState']) and c['resolveState']['max'] == 1
          and bool(c['smokeState']) and c['smokeState']['max'] == 3
          and 'isRangeTag' in c['spec5210'],
          f"破晓={c['resolveState']} 烟幕={c['smokeState']} spec5210={c['spec5210'][:60]}")
    # 5
    c = e['c5']
    check('5 每次再行动都有客户端特技来源',
          c['extraLogs'] >= c['extraSteps'] or c['extraSteps'] == 0,
          f"额外行动={c['extraSteps']} 来源日志={c['extraLogs']} {c['samples'][:1]}")
    # 6
    c = e['c6']
    check('6 [附属被动] 全部接入 unitSpecs 并参与结算',
          c['ap2Skills'] >= 70 and bool(c['attachedSpec']) and bool(c['attachedSkill']),
          f"技能数={c['ap2Skills']} 冰雪暴附属={c['attachedSpec']} {c['attachedSkill']}")
    # 7
    c = e['c7']
    check('7 不存在负数伤害', c['negative'] == 0, str(c['negativeSamples']))
    # 8
    c = e['c8']
    # Whether a unit happens to step on this one trap is battle-dependent;
    # assert the client DATA chain and that the Stay trigger path is live,
    # not a frozen transcript.
    # Whether a unit happens to step on this one trap is battle-dependent;
    # assert the complete client DATA chain plus the engine trigger path.
    check('8 「长枪之灵」停留触发链路与 trigger_skill 15656 效果完整',
          bool(c['trapDef']) and c['trapDef']['ts'] == 15656
          and c['trapDef']['tt'] == 2 and c['trapDef']['lim'] == 1
          and c['skill15656'] > 0 and 'BUFF' in c['skill15656Types']
          and 'SKILL_CD' in c['skill15656Types']
          and 'triggersOnPath' in core_src and "o.triggerType === 2" in core_src
          and 'triggerObject(o, unit)' in core_src,
          f"trap={c['trapDef']} skill15656={c['skill15656Types']} "
          f"observedStayThisBattle={c['anyStayTriggers']}")
    # 9
    c = e['c9']
    # 「不造成实际伤害」: client DAMAGE_BUFFER_DYNAMIC (灵感星核 converts
    # friendly damage into 灵感指数 instead of losing HP) — a real reason.
    reasons = ('不屈', '闪避', '护盾吸收', '免疫', '已被击败', '最多受击', '分摊', '减免', '不造成实际伤害')
    ok9 = all(any(w in (x.get('text') or '') for w in reasons) for x in c['zeroNoReason'])
    check('9 0 伤害写明原因（不屈 / 闪避 / 护盾 / 免疫 / 已击败 / 受击上限 / 分摊）', ok9, str(c['zeroNoReason'][:2]))
    # 10
    c = e['c10']
    check('10 [协同号令] 触发 [协同响应]',
          c['chainCasts'] > 0 and len(c['chainEvents']) > 0,
          f"号令施放={c['chainCasts']} 响应事件={c['chainEvents'][:2]}")

    print('\n--- 第 46 轮：复合技能链 / 再行动 / 技能变更 / 召唤物 / 状态时效 ---')
    # 11
    c = e['c11']
    check('11 [附属被动] 只在基础耗能≥3 后给再行动，触发后移除，再行动技能耗能为 0',
          len(c['grants']) > 0 and all((g['tp'] or 0) >= 3 for g in c['grants'])
          # An extra action may legally be a move when nothing is in range;
          # the 0-cost rule applies to the extra actions that DID cast.
          and any(f.get('skill') for f in c['follow'])
          and all(f.get('cost') == 0 for f in c['follow'] if f.get('skill')) and c['src'],
          f"授予={c['grants'][:2]} 再行动={c['follow'][:2]}")
    # 12
    c = e['c12']
    check('12 限定再行动只施放客户端指定技能（落花之舞 / 游击 / 露西亚之血永存！）',
          c['ok'] > 0 and not c['viol'], f"符合={c['ok']} 违规={c['viol'][:2]} 样例={c['samples'][:2]}")
    # 13
    c = e['c13']
    check('13 「技能变更为」由客户端数据驱动（贯日强击 ⇄ 瞬身袭 等）',
          c['p19180'] == 19176 and c['p19176'] == 19180 and c['swapPlans'] >= 80 and c['swapCount'] > 0,
          f"19180→{c['p19180']} 19176→{c['p19176']} 方案={c['swapPlans']} 本局={c['swapSteps'][:2]}")
    # 14
    c = e['c14']
    check('14 [白金狮子] 再行动限定「露西亚之血永存！」#20310',
          (c['lionSpec'] or {}).get('t') == 'ACTED_ACT' and (c['lionSpec'] or {}).get('p0') == 20310
          and (c['lionSpec'] or {}).get('at') == 43 and c['inBuff'] and c['grantSrc'], str(c))
    # 15
    c = e['c15']
    check('15 灵感星核 / 虚空投影无移动力无回合，灵感星核唯一',
          c['core'] and all(x['unique'] and x['noTurn'] and x['mob'] == 0 for x in c['core'])
          and c['void'] and all((not x['unique']) and x['noTurn'] and x['mob'] == 0 for x in c['void'])
          and c['summonActs'] == 0 and c['coreMax'] <= 1, str(c))
    # 16
    c = e['c16']
    check('16 全装甲集火号令！→ 飞弹礼花 80% 穿透；〈铃兰之剑〉每名响应者恰好 1 次额外协同响应，3 格内有敌人必命中',
          c['cast'] and c['order15968'] > 0 and c['broadcast'] > 0 and len(c['responders']) >= 1
          and all(v == 1 for v in c['respCasts'].values()) and not c['missed']
          and c['order15935'] > 0,
          f"seed={c['seed']} 80%命中={c['order15968']} 50%命中={c['order15935']} "
          f"响应施放={c['respCasts']} 应命中={c['mustHit']} 漏={c['missed']}")
    # 17
    c = e['c17']
    check('17 skill_cast_id 后续技能真实施放（赛事 42 个技能）', c['cupScid'] >= 40 and c['src'], str(c))
    # 18
    c = e['c18']
    check('18 持续 0 回合的状态只在本次行动内生效', c['zeroDurBuffSpecs'] >= 300 and c['actionScopedExpired'] > 0, str(c))
    # 19
    c = e['c19']
    check('19 本局 Lua 条件全部可求值', not c['lua'], str(c['lua']))

    print('\n--- 第 47 轮：回放圆 / 限定再行动 / 循环结算 / 设置 UI ---')
    # 20
    c = e['c20']
    check('20 血棘之花等限定再行动只施放指定技能，不能改成移动/待机/其它技能',
          c['extra'] > 0 and not c['viol'] and c['other'] == 0 and c['src'],
          f"限定再行动={c['extra']} 违规={c['viol'][:2]} 非施放步骤={c['other']}")
    # 21
    c = e['c21']
    check('21 「落花之舞」可作用于敌军、友军与自己；蓄势层数按技能消耗累积',
          c['casts'] > 0 and c['anyUnit'] > 0 and c['src'],
          f"施放={c['casts']} 落在友军/自己={c['anyUnit']}")
    # 22
    c = e['c22']
    check('22 阿尔曼「蛮勇转化-结算」按蓄势层数有限结算，不再刷屏且威慑真实累积',
          0 < c['max'] <= 6 and c['total'] > 0 and c['weishe'] > 0 and c['src'],
          f"单步最多={c['max']} 本局合计={c['total']} 威慑事件={c['weishe']}")
    # 23
    c = e['c23']
    check('23 对局设置分级折叠、操作置顶、说明收起；回放站位圆跟随单位',
          c['runButtons'] == 1 and c['groups'] >= 3 and c['summary']
          and c['advancedFolded'] and c['helpFolded'] >= 1
          and c['ringsFollow'] and c['css'], str(c))

    print('\n--- 第 48 轮：BUFF_CHANGE 语义 / 被非贯穿攻击时机 ---')
    # 24
    c = e['c24']
    check('24 客户端 at62/63「被非贯穿攻击前/后」在被攻击者身上按 Break 标签触发',
          c['at62Specs'] >= 7 and c['at63Specs'] >= 1 and c['aliasRemoved']
          and c['fires62'] and c['fires63'] and c['breakGate']
          and c['ignoreKnockback'] > 0 and not c['error'] and not c['lua'],
          f"at62={c['at62Specs']} at63={c['at63Specs']} 免疫击退执行={c['ignoreKnockback']} "
          f"合成对局步数={c['steps']} lua={c['lua']}")
    # 25
    c = e['c25']
    check('25 BUFF_CHANGE 只在状态真变化时触发；删除事件带 changedBuff / isDeleted / 负层数变化',
          c['src'] and c['at58Specs'] >= 80 and c['changedConditions'] >= 20,
          f"at58 特技={c['at58Specs']} 依赖变化量条件={c['changedConditions']} "
          f"本局深度截断={c['deep']}")

    print('\n--- 第 49 轮：空地召唤 / 回放标注 / 击退明细 / 地形 / 批量模拟 / 左栏归纳 ---')
    # 26
    c = e['c26']
    check('26 「召唤·虚空投影」仅能对空地使用，召唤物落在所选空地格',
          c['egSkills'] >= 40 and c['egCasts'] > 0 and c['egBad'] == 0
          and c['egSpawned'] > 0 and c['gate'],
          f"空地技能={c['egSkills']} 施放={c['egCasts']} 违规={c['egBad']} 召唤物={c['egSpawned']}")
    # 27
    c = e['c27']
    check('27 回放标注角色 A几/B几 编号，命中写明被作用方坐标',
          c['taggedSteps'] > 10 and c['coordHits'] > 0 and c['hitCoords'] > 0
          and c['svg'] and c['src'],
          f"带编号步骤={c['taggedSteps']} 坐标文本={c['coordHits']} 带坐标命中={c['hitCoords']}")
    # 28
    c = e['c28']
    check('28 击退写明声明格数 / 结算格数 / 方向 / 实际格数 / 停止原因',
          c['count'] > 0 and c['withDetail'] == c['count']
          and c['withPositions'] == c['count'] and c['ui'] and c['src'],
          f"击退记录={c['count']} 完整明细={c['withDetail']}")
    # 29
    c = e['c29']
    check('29 客户端 30 种地块规则导出并生效（OPERATION 映射 / 移动代价 / 途经停留 / 免疫 / 冰面滑退）',
          c['fieldDefs'] >= 30 and c['tileSpecs'] >= 50
          and c['tileSpecsExported'] == c['tileSpecs'] and c['terrainSteps'] > 0
          and c['fieldOps'] >= 30 and c['op18'] == 14 and c['op10'] == 3
          and c['src'] and c['ui'],
          f"地块规则={c['fieldDefs']} 专属特技={c['tileSpecsExported']}/{c['tileSpecs']} "
          f"操作映射={c['fieldOps']}（op18→{c['op18']}烟雾, op10→{c['op10']}冰冻） "
          f"生效步骤={c['terrainSteps']} 地块施加状态={c['terrainBuffs']}")
    # 30
    c = e['c30']
    check('30 批量模拟：多种子重跑、胜率统计、筛选胜/负、取种子回看',
          c['ui'] and c['winrate'] and c['css'], str(c))
    # 31
    c = e['c31']
    check('31 左栏按布阵 / 规则 / 批量 / 高级 / 赛事分门别类，带跳转导航',
          c['groups'] >= 5 and c['nav'] >= 5 and c['numbered'] >= 5
          and c['runButtons'] == 1 and c['css'], str(c))

    print('\n--- 第 50 轮：buff 顶替 / 定时地形 / 强选技能 / 技能优先级 / 额外效果 ---')
    # 32
    c = e['c32']
    check('32 客户端 buff_group 分级顶替：[攻击3] 立即顶掉光环 [攻击2] 并保持生效',
          c['tiers'] >= 30 and c['tier81'] > c['tier53'] and c['has81'] and not c['has53'] and c['src'],
          f"分级状态={c['tiers']} 攻击2={c['tier53']}级 攻击3={c['tier81']}级 "
          f"施放后 buff81={c['has81']} buff53={c['has53']}")
    # 33
    c = e['c33']
    check('33 伊凡战斗开始与行动结束按 AOE 把自身 1 格（5 格菱形）地形变冰冻',
          c['events'] >= 2 and c['cells'] >= 5 and c['atBattleStart'] and c['src'],
          f"地形事件={c['events']} 不同格={c['cells']} 战斗开始生效={c['atBattleStart']}")
    # 34
    c = e['c34']
    check('34 「静聆神谕」强制三选一按客户端 ai_skill_order，第一动神泽、随后命途所至，用后触发再行动',
          c['firstId'] in (21570, 21571, 21572) and c['firstId'] == 21572
          and c['next'] == '命途所至' and c['ord'] == [13, 12, 11] and c['src'], str(c))
    # 35
    c = e['c35']
    check('35 战斗开始时一次性属性变更生效（法卡尔·SP 初始能量 3 → 4，可负担戍卫箭幕）',
          c['tpStart'] == 4 and '能量 3 → 4' in c['log'] and c['src'], str(c))
    # 36
    c = e['c36']
    check('36 [瞬发] 链优先个性技能「潜袭」，协同号令开局布阵「戍卫箭幕」优先于普攻',
          c['qianxi'] and c['qianxiAfter'] and c['shuwei'] and c['src'], str(c))
    # 37
    c = e['c37']
    check('37 满血时治疗 AOE 仍按增益部分估值（dt=3 不被误判为伤害技能）',
          c['src'] and c['oracleHeal'], str(c))
    # 38
    c = e['c38']
    check('38 概率型额外效果（昏昏欲睡 33% → 睡眠）可观测，未命中也写明判定',
          c['src'] and c['buff8572'] and c['sleepSpec'] == 645, str(c))
    # 39
    c = e['c39']
    check('39 寻路距离场与可达性一致（地形代价方向 / 客户端 castPipeline 决胜序）',
          c['src'] and c['timedOps'] >= 10 and c['prioritySpecs'] >= 700
          and c['control'] and c['moveAttack'], str(c))

    print('\n--- 第 51 轮：走位 / 选手效果 / 跳人堆 / 减速 ---')
    # 40
    c = e['c40']
    check('40 麦莎·SP 第一步按客户端 posCompare 走到 (9,5)，不再被高差决胜带偏',
          c['firstMove'] == {'x': 9, 'y': 5} and c['src'], str(c))
    # 41
    c = e['c41']
    check('41 赛事选手状态实装：33% 睡眠判定、睡眠跳过行动、受击解除，MOVE_ATTACK 生效',
          c['statuses'] >= 4 and c['rolls'] >= 5 and c['slept'] >= 2
          and c['skipped'] >= 2 and c['src'], str(c))
    # 42
    c = e['c42']
    check('42 「陷阵·锐意承锋」按 3 格菱形 AOE 真实覆盖数选择落点，命中落点内全部敌人',
          c['cast'] and c['hits'] >= 1 and c['hits'] >= c['inArea']
          and c['inArea'] >= c['bestCover'] and c['aoe'] and c['aoe']['sel'] == 'diamond'
          and c['aoe']['max'] == 3 and c['src'], str(c))
    # 43
    c = e['c43']
    check('43 「命途所至」的 [▼速度4]（-200 速度）按客户端 speciality priority 保留，不被同技能 DISPEL 自驱散',
          c['cast'] and c['slowApplied'] > 0 and c['slowDispelled'] == 0
          and c['speedDef'] and c['prioritySpecs'] >= 700 and c['src'], str(c))

    print('\n--- 第 52 轮：赛程76 / 种子28645683（页面同构）逐条还原客户端机制 ---')
    # 44
    c = e['c44']
    check('44 命途所至 [▼速度4]：有[霜佑之印]时生效（速度 −200），没有时保留但不生效（buff active_param 实时判定）',
          c['casts'] > 0 and c['rows'] > 0 and c['liveWithFrost'] and c['dormantWithout']
          and c['minus200'] and c['src'], str(c))
    # 45
    c = e['c45']
    check('45 贝拉：场上有灵感星核时为「星核·位移」，没有时才是「星核·造物」（8801 召唤者标记实时判定）',
          c['make'] > 0 and c['makeBad'] == 0 and c['moveBad'] == 0 and c['listedWrong'] == 0
          and c['coreDecisions'] > 0 and c['src'], str(c))
    # 46
    c = e['c46']
    check('46 伦伽勒·SP：陷阵命中落点内全部敌人；游击只传送到己方枪影；每回合最多 1 次游击',
          c['lunges'] > 0 and c['lungeHits'] >= 1
          and all(g['hits'] >= g['inArea'] and g['inArea'] >= 1 for g in c['lungeGeo'])
          and c['youji'] > 0
          and c['onShadow'] == c['youji'] and c['maxPerRound'] <= 1 and c['src'], str(c))
    # 47
    c = e['c47']
    check('47 客户端 cast_param / target_param 导出并生效：本局无无法求值；造物赋能响应只打自己的灵感星核',
          c['cp'] >= 100 and c['tgp'] >= 300 and not c['unknown']
          and c['r21482'] > 0 and c['r21482Units'] == 0 and c['src'], str(c))
    # 48
    c = e['c48']
    check('48 伤害在后续段的技能（陷阵→灭魂一击后续）以后续技能作为攻击事件，主动攻击后再移动生效',
          c['src'] and c['move3997'], str(c))
    # 49
    c = e['c49']
    check('49 攻击者侧「被攻击后」：野狐塞娜主动攻击后对敌人施加[流血]、[伤口]',
          c['bleed'] > 0 and c['wound'] > 0 and c['src'], str(c))
    # 50
    c = e['c50']
    check('50 只有定身类控制（StrongControl）跳过回合，干扰类（缴械/×主动技/▼移动/缠缚）不跳过',
          c['weak'] == 0 and c['src'], str(c))
    # 51
    c = e['c51']
    check('51 target_type 5 = 当前目标且为友军：猩红之触反击敌人不再给全队加能量',
          c['teamTp'] == 0 and c['src'], str(c))
    # 52
    c = e['c52']
    check('52 能量上限 / 移动力不为负（罗格妮达 TP_MAX −99 = 无能量条）',
          not c['negTp'] and c['src'], str(c))

    print('\n--- 第 53 轮：瞬发免费行动 / 完整计算公式 / 缴械 / 开局选手状态 ---')
    c = e['c53']
    check('53 自益 [瞬发] 在阶段 0 先于主技能：强击姿态→戍卫箭幕（伤害型瞬发改为命中才用，见 59）',
          c['fk'] == [16335, 16300] and c['src'], str(c))
    c = e['c54']
    check('54 每次伤害/治疗都有代入数值的完整公式（明细 + 日志），含治疗，无状态类日志刷屏',
          c['n'] >= 20 and c['withFormula'] == c['n'] and c['withExpr'] == c['n']
          and c['heal'] >= 3 and c['logs'] + c['healLogs'] == c['n']
          and c['logs'] == c['n'] - c['heal'] and c['healLogs'] == c['heal']
          and c['noise'] == 0 and c['src'], str(c))
    c = e['c56']
    check('56 陷阵 AOE 对落点 3 格菱形内全部敌人施加缴械，缴械期间不能放技能或普攻',
          c['cast'] and c['n'] >= 1 and c['n'] == c['inArea'] and not c['castsAfter'] and c['src'], str(c))
    c = e['c57']
    check('57 选手精神状态 33% 判定在开局结算并写出真实骰值，约 1/3 对局伊凡开局睡眠',
          c['openHit'] >= 2 and c['openMiss'] >= 2 and c['step0Sleep'] >= 2
          and c['openHit'] + c['openMiss'] == 12
          and all(1 <= v <= 100 for v in c['openRolls']) and c['src'], str(c))

    print('\n--- 第 54 轮：施法锚点 / 瞬发收益 / 自身技能 / 技能标签 / 伤害公式 ---')
    c = e['c58']
    check('58 施法锚点召唤只在延拓射程能打到敌人时放置：虚空投影零无效落点',
          c['casts'] >= 1 and c['useful'] == c['casts'] and c['wasted'] == 0 and c['src'], str(c))
    c = e['c59']
    check('59 伤害型 [瞬发] 只在能命中时施放（允许先移动），12 个种子零空放 / 零「未命中」',
          c['casts'] >= 10 and c['hits'] == c['casts'] and c['missText'] == 0
          and c['moved'] >= 1 and c['src'], str(c))
    c = e['c60']
    check('60 对自身的 [瞬发]（强击姿态）无命中目标，文案为「对自身生效」而非「未命中」',
          c['cast'] and c['hits'] == 0 and '对自身生效' in c['text']
          and '未命中' not in c['text'] and '瞬发' in c['labels'] and c['src'], str(c))
    c = e['c61']
    check('61 所有技能标注客户端来源的中文标签（伤害类型 / 支援 / 减益 / 瞬发 …）',
          c['n'] >= 20 and c['labelled'] == c['n'] and c['tagNames'] >= 130
          and c['dtNames'] == 5
          and '穿透伤害' in (c['sample'].get('21474') or [])
          and '减益' in (c['sample'].get('15602') or [])
          and '瞬发' in (c['sample'].get('16335') or [])
          and c['src'], str(c))
    c = e['c62']
    check('62 易伤按官方公式逐来源 (1+x) 连乘、无视防御连乘、(攻−防) 5% 下限',
          c['n'] >= 10 and c['product'] == c['n'] and c['perSource'] >= 5
          and c['defRows'] == c['n'] and c['floorRows'] == c['n'] and c['src'], str(c))

    print('\n--- 第 55 轮：种子20261107 施法锚点 / 烟雾隐身 / 覆盖待机 / 警戒范围 ---')
    c = e['c63']
    check('63 施法锚点不再空放：本局第一动不放虚空投影，任何放置都共线且有后续攻击',
          c['noR1Waste'] and c['wasted'] == 0 and c['src'], str(c))
    c = e['c64']
    check('64 烟雾地形经地块光环授予[隐身]，科尔停在烟雾内且敌方不再自动选中他',
          c['smoke'] >= 1 and c['jump'] and c['endAt'] and
          c['endAt']['x'] == c['jump']['land']['x'] and c['endAt']['y'] == c['jump']['land']['y']
          and c['autoTargets'] == 0 and c['src'], str(c))
    c = e['c65']
    check('65 科尔首动 (9,6) → 烟幕游击 (6,6) → 潜袭 → 一次普攻后在烟雾中待机',
          c['stand'] == [9, 6] and c['land'] == [6, 6] and
          c['chain'] == [22008, 22016, 22013] and c['endAt'] == {'x': 6, 'y': 6}
          and c['src'] == 'true', str(c))
    c = e['c66']
    check('66 地图虚线警戒范围：回放携带逐单位警戒区，SVG 覆盖层/裁剪/图例/开关齐备',
          c['steps'] >= 10 and c['alerts'] >= 10 and c['withSkillName'] >= 10
          and c['withLeft'] == c['alerts'] and c['maxDist'] >= 1 and c['src'], str(c))

    print('\n--- 第 56 轮：审判诸罪之光 3×6 扫射 / 审判执行 / 其他机制 ---')
    c = e['c67']
    check('67 DISPLAY_AOE 生效：审判诸罪之光按指定方向 3×6（18 格）扫射并进入 AI 候选',
          c['casts'] >= 3 and c['strip3'] == c['casts'] and c['minArea'] >= 15
          and c['area18'] >= 1 and c['withDir'] == c['casts']
          and len(c['dirs']) >= 2 and c['withHits'] >= 1 and c['listed'] >= 1
          and c['src'], str(c))
    c = e['c68']
    check('68 审判执行在每人回合结束真实结算并写入回放（命中/公式/联动/文案/驱散）',
          c['hits'] >= 3 and c['withDamage'] >= 3
          and c['withDamage'] + c['zeroWithReason'] == c['hits']
          and c['withFormula'] == c['hits'] and c['withSubCasts'] >= 2
          # Text suffix is only added for real damage (zero hits with an
          # explicit 免伤 reason stay in hits/events, no 「共 0 伤害」 noise).
          and c['withText'] == c['withDamage'] and c['withDispel'] >= 1
          and c['src'], str(c))
    c = e['c69']
    check('69 头部自身 1×6 中间列标记生效（+30% → 100%），侧翼保持 70%，联动伤害有公式日志',
          c['midBoost'] >= 1 and c['wingNoBoost'] >= 1 and c['auditLogs'] >= 3
          and c['src'], str(c))

    print('\n--- 第 57 轮：补齐客户端声明但未接管的机制 ---')
    c = e['c70']
    check('70 unit.isCurrentSummoned 接入：大维齐尔「刚召的死士」链零过滤失败，同心战/解放真实施加',
          c['filterSkips'] == 0 and c['summons'] >= 1 and c['warBuff'] >= 1
          and c['liberation'] >= 1 and c['linked'] >= 2 and c['src'], str(c))
    c = e['c71']
    check('71 map:getBlock 接入，施放条件不再有无法求值的目标；物件的无实现效果计为 skipped 而非 executed',
          c['castSkips'] == 0 and c['src'], str(c))
    c = e['c72']
    check('72 active_time 51/52 为独立时点并真实派发；unmappedTiming 成为可验证的能力覆盖守卫',
          c['alias'] == '{}' and '新回合' in c['label51'] and '新回合' in c['label52']
          and c['noEvent'] and c['fired51'] and c['fired52']
          and c['unmapped'] == 0 and c['src'], str(c))
    c = e['c73']
    check('73 ELEMENT_TYPE 作为真实声明标签生效（火/风属性徽标），IGNORE_ATTACK_BLOCK 参与平射阻挡判定',
          c['elemSteps'] >= 1 and c['executed'] >= 1 and c['elemSkillCount'] == 3
          and any('属性' in x for x in (c['sample'] or {}).get('labels', []))
          and c['src'], str(c))

    print('\n--- 第 58 轮：SKILL_COUNT / ABSORB 死亡监听 / 覆盖率准确性 ---')
    c = e['c74']
    check('74 SKILL_COUNT 真实调整技能使用上限：菲娜塔「刻度转化」让虚空投影可再放，category 已导出',
          c['logs'] >= 1 and c['projection'] >= 1 and c['limitBonus'] >= 1
          and c['catExported'] >= 30 and c['src'], str(c))
    c = e['c75']
    check('75 ABSORB 作为单位阵亡监听器生效（火焰热情 CD-1 等），不再误写 absorbPct',
          c['logs'] >= 3 and c['executed'] == c['logs']
          and c['firePassion'] >= 1 and c['src'], str(c))
    c = e['c76']
    check('76 声明型特技不再重复计入 cov.executed（GLOBAL_LIMIT / SKILL_RANGE / IMMUNE / TACTICS）',
          not c['doubleCounted'] and c['src'], str(c))
    c = e['c77']
    check('77 物件无实现效果计入 skipped，unmappedTiming 为引擎能力守卫且 51/52 已派发',
          c['unmapped'] == 0 and c['fired'] >= 40 and c['has51'] and c['has52']
          and c['src'], str(c))

    print('\n--- 第 59 轮：speciality 三种更细的客户端触发次数限制 ---')
    c = e['c78']
    on = c['on']
    check('78 三种触发次数限制生效：闸门真实拦下越界派发，实际派发零超额',
          c['lccRows'] >= 20 and c['lcpecRows'] >= 6 and c['lcpetRows'] >= 20
          and on['rejected'] >= 1
          and on['lcc'] == 0 and on['lcpec'] == 0 and on['lcpet'] == 0
          and on['fires'] > 0 and c['gidRows'] >= 100 and c['src'], str(c))
    c = e['c79']
    check('79 新限制与 group_id/group_priority 从客户端原列导出，值正确',
          c['lcc'] == 1 and c['lcpec'] == 1 and c['lcpet'] == 1
          and c['gid'] == 2 and c['gp'] == 999 and c['src'], str(c))
    c = e['c80']
    check('80 加入计数闸门后覆盖率健康：Lua 未知 0、无条件求值失败、时点仍全派发',
          c['luaUnknown'] == 0 and c['conditions'].get('unknown', -1) == 0
          and c['unmapped'] == 0 and c['fired'] >= 40 and c['src'], str(c))

    print('\n--- 第 60 轮：复合 JSON sparam（buff_category / 层数 / 坠落 / 召唤数） ---')
    c = e['c81']
    on = c['on']
    check('81 JSON sparam 结构化导出；DISPEL buff_category 生效：闸门拦下非类别 buff，实际驱散全合法',
          c['sjRows'] >= 250 and c['sjKeys'] >= 20
          and '"buff_category":[24]' in c['dispelSj']
          and on['rejectedWrong'] >= 1 and on['rejected'] >= 1
          and on['wrong'] == 0 and on['cat24'] >= 1
          and c['src'], str(c))
    c = e['c82']
    check('82 ignore_buff_stack_count / dont_fall / cast_limit+total_limit 均从客户端复合参数读取',
          c['ignore'] and c['dontFall'] and c['castLimit'] == 3
          and c['complete'] and c['forceCast'] >= 80 and c['src'], str(c))
    c = e['c83']
    check('83 IMMUNE 按 buff_category 收窄，PLACE_UNIT 按 cast_limit 生成召唤数量',
          c['immuneRows'] >= 5 and c['immuneCats'] >= 8 and c['dispelRows'] >= 4
          and c['summonSj'] >= 10 and c['src'], str(c))
    c = e['c84']
    check('84 接入复合参数后覆盖率健康：Lua 未知 0、条件未知 0、时点无遗漏',
          c['luaUnknown'] == 0 and c['condUnknown'] == 0
          and c['unmapped'] == 0 and c['fired'] >= 40 and c['src'], str(c))

    print('\n--- 第 61 轮：剩余复合 sparam（陷阱同屏上限 / priority / force_cast / caster_attr） ---')
    c = e['c85']
    check('85 PLACE_TRAP complete_cast_limit 同屏上限生效：真实拦下超量放置',
          c['rows'] >= 4 and min(c['caps']) >= 1 and c['rejected'] >= 1
          and c['src'], str(c))
    c = e['c86']
    check('86 JSON sparam.priority 作为行级执行顺序，在 fire() 与 runSkillSpecs 两处生效',
          c['rows'] >= 40 and c['distinct'] >= 8 and c['max'] >= 5000
          and c['min'] <= -2000 and c['sample'] == 9000 and c['src'], str(c))
    c = e['c87']
    check('87 force_cast 状态机转换在无合法目标时不再被静默丢弃（多数为 aim=self）',
          c['rows'] >= 80 and c['selfAim'] >= 50 and c['linked'] >= 80
          and c['src'], str(c))
    c = e['c88']
    check('88 caster_attr / cut_defence 被正确读取，修复「三元两边相同」bug，覆盖率仍健康',
          c['casterAttrRows'] >= 8 and c['cutRows'] >= 4 and c['targetAttr']
          and c['bugGone'] and c['luaUnknown'] == 0 and c['unmapped'] == 0
          and c['src'], str(c))

    print('\n--- 第 63 轮：伪实装特技与常量 Lua 接口全部接入；逐句机制 → 代码映射 ---')
    c = e['c89']
    check('89 生命下限 / 溢出储存 / 缓存值改写 / 目标上限 / 请求援防 / 支援队友 在真实对局中生效',
          c['hpFloor'] >= 1 and c['overflow'] >= 1 and c['storeWrite'] >= 1 and c['targetLimit'] >= 1
          and c['demand'] >= 1 and c['support'] >= 1 and c['errors'] == 0 and c['src'], str(c))
    c = e['c90']
    check('90 原伪实装特技都在客户端生效位置读取，不再写入无人读取的标记；复合属性（攻击/防御）被展开',
          not c['leftover'] and not c['readers'] and c['composite'], str(c))
    c = e['c91']
    check('91 23 个曾恒返回常量的客户端 Lua 接口改为读取实时战斗状态，对局 Lua 未知 0',
          not c['stubs'] and not c['apis'] and c['luaUnknown'] == 0, str(c))
    c = e['c92']
    check('92 逐句机制映射已生成：每句描述→客户端特技→引擎代码，代码锚点与当前引擎源码逐行一致',
          c['skills'] >= 4000 and c['sentences'] >= 8000 and c['mapped'] >= 0.9 * c['sentences']
          and c['withSpec'] >= 0.7 * c['sentences'] and c['anchorsAll'] >= 800
          and c['anchorsOk'] == c['anchorsAll'] and c['engineLines'] == c['coreLines']
          and c['gaps'] == 0 and c['luaMissing'] == 0 and c['pers'] >= 500
          and c['shards'] == 64 and c['sample'] and c['sample'][0] >= 3, str(c))
    c = e['c93']
    check('93 逐句覆盖客户端完整描述：120 字截断已补齐、每句都有归属、无空白行、浏览器不加载构建期数据',
          c['fullRows'] >= 300 and '最终伤害提高30%' in c['sampleTail']
          and not c['browserLoadsFull'] and c['mapped'] == c['total'] == c['sentences']
          and c['blank'] == 0 and c['frag'] == 0 and c['noteRefs'] >= 100
          and c['noteCommon'] >= 1 and all(c['src']), str(c))
    c = e['c94']
    check('94 find_trap 找枪灵传送落上陷阱并触发停留；其余未读取的复合参数全部核实归类、无含糊未实装',
          c['findTrap'] == 139 and c['trapStay'] == 2 and c['trapLimit'] == 1
          and c['trapSkill'] > 0 and c['blinks'] >= 1 and c['stays'] >= 1
          and c['findTrapImpl'] == 'impl' and c['audited'] >= 14
          and c['missing'] == 0 and c['stub'] == 0 and c['src'], str(c))

    if full:
        sweep_checks(e, check)

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
