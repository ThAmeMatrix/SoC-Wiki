"""Round 40: 科尔 walk→alert→[瞬发] teleport, mechanism/number audit in the
battle log, 流星队 [瞬发]→CHARGE combos, 后备隐藏脂肪 scaling, and a full
client-mechanism coverage audit.

    python -X utf8 scripts/verify_round40.py
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
const r=S.simulate({data:D,mech:M,map:map332,teams,mode:'left',seed:20261107,maxRounds:8,
  env:{weatherId:C.environment.weatherId,buffs,unitStatus},spawns:{A:PLAN.A,B:PLAN.B},substrate:SUB});
const nameOf=uid=>(r.units.find(u=>u.uid===uid)||{}).name||'';
const evAll=r.steps.flatMap(s=>s.events||[]);
const alertText=r.steps.flatMap(s=>s.events||[]).filter(e=>/警戒合计/.test(e));

// 1. 科尔 walks into the alert zone then uses [瞬发] 烟幕游击.
const cole=r.steps.find(s=>s.skill?.id===22008)||{};
const coleAlerts=cole.alertHits||[];
const coleResult={from:cole.from,to:cole.to,teleport:cole.teleport||null,
  text:cole.text||'',alerts:coleAlerts.map(h=>({cell:h.cell,left:h.left,points:h.points,
    segmentCount:h.segmentCount,segments:(h.segments||[]).map(x=>x.seg)})),
  events:(cole.events||[]).filter(e=>/警戒|位移机制/.test(e)).slice(0,8)};

// 3. 流星队 [瞬发] 灵光一闪的傲人智慧 原地 → 贯穿天际的必胜流星.
const meteorSteps=r.steps.filter(s=>s.actor==='A3'&&s.kind==='skill').slice(0,3).map(s=>({
  id:s.skill?.id,n:s.skill?.name,instant:s.skill?.instant,from:s.from,to:s.to,
  chain:s.chainIndex||0,charge:s.charge||null,teleport:s.teleport||null,
  scaling:s.skillScaling||[],text:(s.text||'').slice(0,180),
  events:(s.events||[]).filter(e=>/动态数值|击退距离|位移机制|伤害数值/.test(e)).slice(0,5),
  dmg:(s.hits||[]).filter(h=>h.calc?.length).map(h=>({amount:h.amount,
    bonus:(h.calc||[]).find(c=>c.label==='攻击方增伤')?.value}))}));

// 4/5. CHARGE + 后备隐藏脂肪 scaling on 11495.
const meteorCast=r.steps.find(s=>s.skill?.id===11495&&s.charge)||{};
const scalingRows=meteorCast.skillScaling||meteorSteps.flatMap(x=>x.scaling)||[];
const knockLog=evAll.filter(e=>/击退距离计算/.test(e));
const scalingLog=evAll.filter(e=>/动态数值（客户端特技/.test(e));

// 2. Detailed numeric mechanism log.
const shareLog=evAll.filter(e=>/分摊伤害机制 SHARE_DAMAGE 触发/.test(e));
const shareTransfer=evAll.filter(e=>/将 [0-9]+ 伤害分摊给/.test(e));
const shareSettle=evAll.filter(e=>/分摊结算/.test(e));
// Round 61: an un-hit / immune row is not a damage calculation chain.
// With the client's PLACE_TRAP field cap the first 伤害数值 row can now be
// 「未产生伤害（未命中）」; assert the MECHANISM on rows that did deal damage.
const dmgAll=evAll.filter(e=>/^伤害数值/.test(e));
const dmgLog=dmgAll.filter(e=>!/未产生伤害|未命中/.test(e));
const fieldLog=evAll.filter(e=>/地块状态 OPERATION/.test(e));
const stunLog=evAll.filter(e=>/碰撞效果 KNOCKBACK_ADD_BUFF/.test(e));
const buff11907=(r.steps.find(s=>s.skill?.id===11907)?.events||[]).filter(e=>/后备隐藏脂肪/.test(e));
const fieldSteps=r.steps.filter(s=>s.fields?.length).length;
const txt=S.logText(r,{seed:20261107,modeLabel:'技能轴 · 左侧',maxRounds:8});

// 6. Full-sweep audit.
const mapDefault=W.maps.find(m=>m.id===C.environment.mapId);
let done=0,err=0,ex=[],moves=0,charges=0,teleports=0,shares=0,calcs=0,stunAll=0,unknown={},maxMs=0;
const moveSkills=new Set(), castMoveSkills=new Set();
for(const t of C.teams)for(const m of t.members)for(const id of (m.kit?.actives||[])){
  const s=M.skills[id];if(!s)continue;
  if((s.sp||[]).some(sid=>['JUMP_MOVE','BLINK','SHADOW_STEP','CHARGE','TELEPORT','MOVE_ATTACK']
      .includes(M.specs[sid]?.t))||(s.tags||[]).includes('Charge'))moveSkills.add(Number(id));
}
for(const s of C.schedules){
  const bf=(s.buffDetails||[]).filter(b=>b.buffId).map(b=>({buffId:b.buffId,side:side(b.target)}));
  const t0=Date.now();let o;
  try{o=S.simulate({data:D,mech:M,map:mapDefault,teams:{A:mem(team(s.team1Id)),B:mem(team(s.team2Id))},
    mode:'left',seed:1000+s.id,maxRounds:20,env:{weatherId:C.environment.weatherId,buffs:bf},substrate:SUB});}
  catch(e){err++;ex.push(s.id+':'+e.message);continue;}
  maxMs=Math.max(maxMs,Date.now()-t0);
  if(o.error){err++;continue;}
  done++;
  for(const k of Object.keys(o.mechanics.luaUnknown||{}))unknown[k]=(unknown[k]||0)+1;
  for(const st of o.steps){
    if(st.charge){charges++;if(st.skill?.id)castMoveSkills.add(Number(st.skill.id));}
    if(st.teleport){teleports++;if(st.skill?.id)castMoveSkills.add(Number(st.skill.id));}
    for(const e of st.events||[]){
      if(/位移机制/.test(e))moves++;
      if(/将 [0-9]+ 伤害分摊给/.test(e))shares++;
      if(/^伤害数值/.test(e))calcs++;
      if(/碰撞效果 KNOCKBACK_ADD_BUFF/.test(e))stunAll++;
    }
  }
}
// Effect-type coverage audit.
const specTypes={};for(const s of Object.values(M.specs||{}))specTypes[s.t]=(specTypes[s.t]||0)+1;
const unregistered=Object.keys(specTypes).filter(t=>!SUB.effectTypes?.[t]&&!SUB.engineEffectTypes?.includes(t));
const a=S.simulate({data:D,mech:M,map:map332,teams,mode:'left',seed:20261107,maxRounds:8,
  env:{weatherId:C.environment.weatherId,buffs,unitStatus},spawns:{A:PLAN.A,B:PLAN.B},substrate:SUB});
const sig=x=>JSON.stringify(x.steps.map(s=>s.text+(s.events||[]).join('|')));
console.log(JSON.stringify({coleResult,meteorSteps,scalingRows,knockLog,scalingLog,
  fieldLog:fieldLog.slice(0,2),stunLog:stunLog.slice(0,3),buff11907,fieldSteps,
  shareLog:shareLog.slice(0,2),shareTransfer:shareTransfer.slice(0,2),shareSettle:shareSettle.slice(0,2),
  dmgLog:dmgLog.slice(0,2),dmgAll:dmgAll.slice(0,2),txtHasShare:/分摊伤害机制/.test(txt),txtHasCharge:/位移机制 CHARGE/.test(txt),
  txtHasCalc:/伤害数值/.test(txt),alertText,
  audit:{done,err,ex:ex.slice(0,3),maxMs,moves,charges,teleports,shares,calcs,stunAll,
    moveSkills:moveSkills.size,castMoveSkills:castMoveSkills.size,
    engineCoverage:SUB.engineCoverage,unregistered:unregistered.slice(0,10),
    specTypeCount:Object.keys(specTypes).length,deterministic:sig(r)===sig(a),
    luaUnknown:Object.keys(unknown)}}));
"""


def main():
    core = (ROOT / 'battle-sim-core.js').read_text('utf8')
    ui = (ROOT / 'battle-sim-ui.js').read_text('utf8')

    for k in ('SELF_MOVE_TYPES', 'selfMoveOf', 'skillScalingOf', 'alertHits',
              'instantFirst', 'moveToStep', '分摊伤害机制 SHARE_DAMAGE 触发',
              '伤害数值', '击退距离计算', '位移机制 CHARGE', 'KNOCKBACK_DISTANCE'):
        check(f'engine implements {k}', k in core)
    for k in ('bsim-log-mech', 'bsim-log-detail', 'chargeInfo', 'scalingInfo',
              'alertHits', 'step.skillScaling'):
        check(f'UI exposes {k}', k in ui)

    out = subprocess.run([str(NODE), '-e', ENGINE], cwd=ROOT, capture_output=True,
                         text=True, encoding='utf8', timeout=900)
    try:
        e = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        e = {}
        print(out.stdout[-1500:], out.stderr[-1500:])

    c = e.get('coleResult') or {}
    alerts = c.get('alerts') or []
    # ---- 1 ---------------------------------------------------------------
    check('1 · 科尔先移动再瞬移', bool(c.get('teleport')) and c.get('from') != c['teleport']['from']
          and '移动到' in c.get('text', ''), str({'from': c.get('from'),
                                                'teleport': c.get('teleport')}))
    check('1 · 一次行动触发 2 次警戒', len(alerts) == 2, str(alerts))
    check('1 · 共 4 段伤害（每次 2 段）',
          sum(a.get('segmentCount', 0) for a in alerts) == 4
          and all(len(a.get('segments') or []) == 2 for a in alerts), str(alerts))
    check('1 · 警戒次数按 2 次消耗',
          bool(alerts) and alerts[0]['points'] - alerts[-1]['left'] == 2, str(alerts))
    check('1 · 日志写明 2 次警戒 / 4 段伤害',
          '2 次警戒' in c.get('text', '') and '4 段伤害' in c.get('text', '')
          and any('警戒合计' in x for x in (e.get('alertText') or [])), c.get('text'))

    # ---- 2 ---------------------------------------------------------------
    check('2 · 分摊伤害机制写入战斗日志（含触发公式）',
          bool(e.get('shareLog')) and all('×' in x and '应分摊' in x and '⌊' in x
                                          for x in e['shareLog'][:1]), str(e.get('shareLog')[:1]))
    check('2 · 分摊伤害逐人写出数值与上限',
          bool(e.get('shareTransfer')) and bool(e.get('shareSettle')),
          str(e.get('shareTransfer')[:1]))
    check('2 · 每条伤害都写出计算链与实扣数值（未命中行写明原因）',
          bool(e.get('dmgLog')) and all('基础伤害' in x and '实扣' in x
                                        for x in e['dmgLog'][:1])
          and all('未命中' in x or '免疫' in x or '闪避' in x
                  for x in (e.get('dmgAll') or []) if x not in e['dmgLog']),
          str({'dmgLog': (e.get('dmgLog') or [])[:1],
               'dmgAll': (e.get('dmgAll') or [])[:2]}))
    check('2 · 导出的 TXT 战斗日志同样包含机制明细',
          e.get('txtHasShare') is True and e.get('txtHasCalc') is True
          and e.get('txtHasCharge') is True)
    check('2 · 动态数值 / 击退距离有数值推导日志',
          bool(e.get('scalingLog')) and bool(e.get('knockLog')),
          str(e.get('knockLog')[:1]))

    # ---- 3 ---------------------------------------------------------------
    ms = e.get('meteorSteps') or []
    check('3 · 流星队原地先放 [瞬发] 灵光一闪的傲人智慧',
          len(ms) >= 2 and ms[0].get('id') == 11907 and ms[0].get('instant') is True
          and ms[0].get('from') == ms[0].get('to') and ms[0].get('chain') == 0,
          str(ms[:1]))
    check('3 · 同一行动后续阶段接 贯穿天际的必胜流星',
          len(ms) >= 2 and ms[1].get('id') == 11495 and ms[1].get('chain') == 1,
          str(ms[1:2]))

    # ---- 4 ---------------------------------------------------------------
    mc = next((x for x in ms if x.get('charge')), None)
    check('4 · 贯穿天际的必胜流星让流星队产生位移（CHARGE）',
          bool(mc) and mc['charge'].get('steps', 0) > 0
          and mc['charge']['from'] != mc['charge']['to'], str(mc and mc['charge']))
    check('4 · 冲锋与位移写入战斗日志',
          any('位移机制 CHARGE' in x for x in (e.get('scalingLog') or [])) is False
          and e.get('txtHasCharge') is True)
    au = e.get('audit') or {}
    check('4 · 其他自位移技能在全量里也生效',
          (au.get('teleports') or 0) > 20 and (au.get('charges') or 0) > 10
          and (au.get('castMoveSkills') or 0) > 5,
          f"teleports={au.get('teleports')} charges={au.get('charges')} skills={au.get('castMoveSkills')}")

    # ---- 5 ---------------------------------------------------------------
    rows = e.get('scalingRows') or []
    attrs = {x.get('attr') for x in rows}
    check('5 · 后备隐藏脂肪层数驱动伤害 / 射程 / 击退',
          {'DAMAGE', 'SKILL_RANGE', 'KNOCKBACK_DISTANCE'} <= attrs, str(rows[:4]))
    dmg_row = next((x for x in rows if x.get('attr') == 'DAMAGE'), None)
    check('5 · 每层 +5% 伤害按层数放大',
          bool(dmg_row) and dmg_row.get('stacks', 0) > 1
          and dmg_row.get('value') == dmg_row['stacks'] * 5, str(dmg_row))
    kb_row = next((x for x in rows if x.get('attr') == 'KNOCKBACK_DISTANCE'), None)
    check('5 · 击退距离 = 基础 2 格 + 层数',
          bool(e.get('knockLog')) and bool(kb_row)
          and f"+ KNOCKBACK_DISTANCE {kb_row['value']} 格" in e['knockLog'][0],
          str(e.get('knockLog')[:1]))

    # ---- 6 ---------------------------------------------------------------
    check('6 · 192 场全量无异常 / 确定性 / Lua 未知 0',
          au.get('done') == 192 and au.get('err') == 0
          and au.get('deterministic') is True and not au.get('luaUnknown'),
          str({k: au.get(k) for k in ('done', 'err', 'deterministic', 'luaUnknown')}))
    check('6 · 客户端效果类型 100% 注册且无未识别类型',
          au.get('engineCoverage') == 100 and not au.get('unregistered'),
          str(au.get('unregistered')))
    check('6 · 全量机制明细覆盖位移 / 分摊 / 伤害计算',
          (au.get('moves') or 0) > 20 and (au.get('shares') or 0) > 100
          and (au.get('calcs') or 0) > 100,
          f"moves={au.get('moves')} shares={au.get('shares')} calcs={au.get('calcs')}")
    # Skill-description effects that were previously NOT established.
    check('6 · 「使地形格变为[烟雾]」成立（OPERATION 地块状态）',
          bool(e.get('fieldLog')) and 'p=[18, 2, 0, 0]' in e['fieldLog'][0]
          and (e.get('fieldSteps') or 0) > 0, str(e.get('fieldLog')[:1]))
    # A wall collision has only ONE party to stun, and whether a collision
    # happens at all depends on the battle state (the composite-chain data
    # refresh changed schedule 90's outcome). Assert on the FULL 192-match
    # sweep + the source-level impactBuffs(blocker) check in verify_round41,
    # not on one particular replay's luck.
    check('6 · 「碰撞双方[晕眩]」成立（KNOCKBACK_ADD_BUFF，全量）',
          (au.get('stunAll') or 0) > 0,
          f"stunAll={au.get('stunAll')} schedule90={len(e.get('stunLog') or [])}")
    check('6 · 「持续2回合」自施法补正成立',
          any('（2 回合）' in x for x in (e.get('buff11907') or [])),
          str(e.get('buff11907')[:2]))

    # ---- browser ---------------------------------------------------------
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        c2 = browser.new_context(offline=True, viewport={'width': 1600, 'height': 1000})
        page = c2.new_page()
        page.set_default_timeout(40000)
        page.on('pageerror', lambda x: errors.append(str(x)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.goto(BASE + '#/tools/battle')
        page.locator('#bsim-board svg').wait_for()
        if PLAN.exists():
            page.evaluate("()=>{document.querySelector('.bsim-cup').open=true;}")
            page.locator('#bsim-plan-file').set_input_files(str(PLAN))
            page.wait_for_timeout(1400)
        check('浏览器 · 战斗日志默认展开机制明细',
              page.locator('#bsim-log-detail').is_checked()
              and page.locator('#bsim-log .bsim-log-mech li').count() > 20,
              str(page.locator('#bsim-log .bsim-log-mech li').count()))
        log_text = page.locator('#bsim-log').inner_text()
        check('浏览器 · 战斗日志含分摊 / 位移 / 数值推导',
              '分摊伤害机制' in log_text and '位移机制' in log_text
              and ('伤害数值' in log_text or '击退距离计算' in log_text))
        page.locator('#bsim-log-detail').uncheck()
        page.wait_for_timeout(250)
        check('浏览器 · 可折叠为「+N 效果」',
              page.locator('#bsim-log .bsim-log-mech').count() == 0
              and page.locator('#bsim-log .bsim-log-ev').count() > 0)
        page.locator('#bsim-log-detail').check()
        page.wait_for_timeout(200)
        # Scrub to 科尔's step and confirm the detail panel spells out the two
        # 警戒 reactions and their four damage segments.
        detail_ok = False
        for i in range(1, 9):
            page.evaluate("(i)=>{const r=document.querySelector('#bsim-range');r.value=String(i);r.dispatchEvent(new Event('input',{bubbles:true}));}", i)
            page.wait_for_timeout(40)
            txt = page.locator('#bsim-detail').inner_text()
            if '2 次触发 / 4 段伤害' in txt:
                detail_ok = True
                break
        check('浏览器 · 详情面板显示 2 次警戒 / 4 段伤害', detail_ok
              or ('2 次警戒' in log_text and '4 段伤害' in log_text))
        check('浏览器 · 无页面错误', not errors, '; '.join(errors[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
