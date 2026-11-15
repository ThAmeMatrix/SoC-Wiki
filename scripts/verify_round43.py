"""Round 43: decoded composite skills, ghost-circle removal, position in the
character panel and skill-caused displacement attribution.

    python -X utf8 scripts/verify_round43.py
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
const opt=(extra)=>Object.assign({data:D,mech:M,map:map332,teams,mode:'left',
  seed:20261107,maxRounds:8,env:{weatherId:C.environment.weatherId,buffs,unitStatus},
  spawns:{A:PLAN.A,B:PLAN.B},substrate:SUB},extra||{});
const r=S.simulate(opt());
const sig=x=>JSON.stringify(x.steps.map(s=>s.text+(s.events||[]).join('|')));
const deterministic=sig(r)===sig(S.simulate(opt()));

// ---- 1. decoded composite chain data ------------------------------------
const p11450=M.skillPlans?.['11450']||{};
const chain11450=p11450.chain||[];
const multiChains=Object.values(M.skillPlans||{}).filter(x=>x.chain?.length>1).length;
const boostRows=Object.values(M.skillPlans||{}).reduce((n,x)=>
  n+(x.chain||[]).reduce((m,c)=>m+c.boost.length,0),0);
const effectRows=Object.values(M.skillPlans||{}).reduce((n,x)=>
  n+(x.chain||[]).reduce((m,c)=>m+c.effects.length,0),0);
const luaConditions=(chain11450[1]?.boost||[]).map(b=>b.when);

// ---- 4/5. synthetic 百无禁忌 cast ---------------------------------------
const fighter=(name,skills)=>({name,
  stats:{hp:100000,patk:2000,matk:0,pdef:200,mdef:200,spd:100},
  move:{mob:3,up:2,down:2,type:1},prof:6,profName:'无属性',
  skills,edited:false,kit:null,custom:true});
const lab=S.simulate({data:D,mech:M,map:map332,
  teams:{A:[fighter('猎魔人',[{id:11450}])],B:[fighter('靶子',[{id:11761}])]},
  mode:'left',seed:11,maxRounds:3,env:{weatherId:0},
  spawns:{A:[{x:6,y:11}],B:[{x:7,y:11}]},substrate:SUB});
const cast=lab.steps.find(s=>s.skill?.id===11450)||{};
const labHits=(cast.hits||[]).map(h=>({seg:h.seg,amount:h.amount,boost:h.boost,
  boostSpecs:h.boostSpecs,chainSkill:h.chainSkill}));
const labBoostEvents=(cast.events||[]).filter(e=>/客户端条件倍率/.test(e));
const labComposition=cast.plan?.composition||null;

// ---- 5. composition covers EVERY skill -----------------------------------
const cupIds=new Set();
for(const t of C.teams)for(const m of t.members)
  for(const x of (m.skills||[]))cupIds.add(Number(x.id||x));
let compOk=0,compFail=0,compEffects=0,compSegments=0;
for(const id of cupIds){
  const s=skillForTest(id);
  if(!s)continue;
  const c=compForTest(s);
  if(c&&c.segments.length>=1){compOk++;compEffects+=c.effectTotal;compSegments+=c.damageSegments;}
  else compFail++;
}
// Read compositions through the engine's own inspect() (no private access).
const inspect0=r.inspect(0,'A4')||{};
const state11450=(inspect0.skillStates||[]).find(x=>x.id===11450)||null;
function skillForTest(id){return M.skills[id]?Object.assign({id:Number(id)},M.skills[id]):null;}
function compForTest(s){
  // Mirror of the engine's runtime compiler, using only decoded client data.
  const chain=[];let cur=Number(s.id),seen=new Set();
  for(let g=0;cur&&!seen.has(cur)&&g<10;g++){
    seen.add(cur);const sk=M.skills[cur];if(!sk)break;
    chain.push({id:cur,n:sk.n,factor:Number(sk.df)||0,
      effects:(sk.sp||[]).filter(sid=>M.specs[sid]).map(sid=>({spec:sid,t:M.specs[sid].t}))});
    cur=Number(sk.fl)||0;
  }
  return {segments:chain,damageSegments:chain.filter(x=>x.factor>0).length,
          effectTotal:chain.reduce((n,x)=>n+x.effects.length,0)};
}

// ---- 3. displacement caused by a skill ----------------------------------
const tele=r.steps.find(s=>s.teleport)||{};
const chg=r.steps.find(s=>s.charge)||{};
const teleport=tele.teleport||{},charge=chg.charge||{};

// ---- 6. full sweep health ------------------------------------------------
const mapDefault=W.maps.find(m=>m.id===C.environment.mapId);
let done=0,err=0,ex=[],unknown={},skipped={},boostEvents=0,compositeCasts=0,maxMs=0;
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
  for(const k of Object.keys(o.mechanics.luaUnknown||{}))unknown[k]=(unknown[k]||0)+1;
  for(const [k,v] of Object.entries(o.mechanics.skipped||{}))skipped[k]=(skipped[k]||0)+v;
  for(const st of o.steps){
    if(st.plan?.composition)compositeCasts++;
    for(const e of st.events||[])if(/客户端条件倍率/.test(e))boostEvents++;
  }
}
console.log(JSON.stringify({
  data:{g:p11450.g,chainLength:chain11450.length,
    factors:chain11450.map(x=>x.df),boost:chain11450[1]?.boost||[],
    luaConditions,multiChains,boostRows,effectRows,
    planCount:Object.keys(M.skillPlans||{}).length},
  lab:{hits:labHits,boostEvents:labBoostEvents,composition:labComposition,
    text:(cast.text||'').slice(0,220)},
  composition:{cupSkills:cupIds.size,compOk,compFail,compEffects,compSegments,
    inspect11450:state11450?.composition||null},
  displacement:{teleport,teleText:(tele.text||'').slice(0,240),
    teleTo:tele.to||null,teleSeq:tele.seq??null,
    charge,chgText:(chg.text||'').slice(0,240)},
  sweep:{done,err,ex:ex.slice(0,3),maxMs,unknown:Object.keys(unknown),
    skipped:Object.entries(skipped).sort((a,b)=>b[1]-a[1]).slice(0,5),
    boostEvents,compositeCasts,deterministic}}));
"""


def main():
    core = (ROOT / 'battle-sim-core.js').read_text('utf8')
    ui = (ROOT / 'battle-sim-ui.js').read_text('utf8')
    css = (ROOT / 'refinements.css').read_text('utf8')
    plan_src = (ROOT / 'scripts/skill_mechanics.py').read_text('utf8')
    extract_src = (ROOT / 'scripts/extract_battle_mechanics.py').read_text('utf8')

    # ---- static / source of truth ----------------------------------------
    check('6 · 数据由客户端 idskill_follow / active_param 编译',
          'idskill_follow' in plan_src and 'DAMAGE_FACTOR_TYPES' in plan_src
          # Round 46 added `unit_tags` as a 5th argument (faction tags used by
          # 〈铃兰之剑〉协同响应); assert the call, not a frozen signature.
          and 'derive_plans(out_skills, out_specs, out_buffs, attrs' in extract_src
          and 'function compileChain' in core and 'chainOf' in core)
    check('1 · 地图不再画 step.from 的残留圆圈',
          'class="bsim-ghost"' not in ui and 'polyline class="bsim-path"' in ui)
    check('2 · 角色面板状态块带当前位置',
          '当前状态（${p.buffs.length}） · 位置' in ui and '当前所在位置' in ui)
    check('5 · 复合态视图覆盖段与效果',
          'compositionOf' in core and 'bsim-composition' in ui
          and 'composition: compositionOf' in core)
    check('CSS 隐藏旧 ghost 圈并支撑新块',
          '.bsim-ghost{display:none}' in css and '.bsim-composition' in css)

    out = subprocess.run([str(NODE), '-e', ENGINE], cwd=ROOT, capture_output=True,
                         text=True, encoding='utf8', timeout=900)
    try:
        e = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        e = {}
        print(out.stdout[-1800:], out.stderr[-1800:])

    d = e.get('data') or {}
    # ---- 6 / 4 / 5 data ---------------------------------------------------
    check('6 · 客户端技能链写入 skillPlans（439 条多级链）',
          d.get('multiChains', 0) >= 400 and d.get('boostRows', 0) > 100
          and d.get('effectRows', 0) > 1000,
          f"multi={d.get('multiChains')} boost={d.get('boostRows')} effects={d.get('effectRows')}")
    check('4 · 「百无禁忌」编译为 40% + 100% 两段',
          d.get('g') == [[1, 40], [1, 100]] and d.get('factors') == [40, 100],
          f"g={d.get('g')} factors={d.get('factors')}")
    check('4 · 第二段条件倍率来自客户端 Lua 原文（无硬编码）',
          len(d.get('boost') or []) == 3
          and [b.get('pct') for b in d['boost']] == [30, 60, 90]
          and all('tp_max' in w for w in (d.get('luaConditions') or [])),
          str(d.get('luaConditions')))

    lab = e.get('lab') or {}
    hits = lab.get('hits') or []
    check('4 · 合成对局确实结算两段伤害',
          len(hits) == 2 and '40%' in str(hits[0].get('seg')) and '100%' in str(hits[1].get('seg'))
          and hits[0]['amount'] > 0 and hits[1]['amount'] > 0,
          str(hits))
    check('4 · 第二段按目标缺少能量命中 +60% 条件倍率',
          any((h.get('boost') or 0) > 0 and h.get('boostSpecs') for h in hits)
          and any('客户端条件倍率' in x and 'tp_max' in x for x in (lab.get('boostEvents') or [])),
          str((lab.get('boostEvents') or [])[:1]))
    check('5 · 复合态含全部效果（BUFF/回能/条件倍率）',
          (lab.get('composition') or {}).get('effectTotal', 0) >= 5
          and (lab.get('composition') or {}).get('chainLength') == 2,
          str({k: (lab.get('composition') or {}).get(k) for k in
               ('chainLength', 'damageSegments', 'effectTotal')}))

    comp = e.get('composition') or {}
    check('5 · 赛事闭包内每个技能都有复合态',
          comp.get('compFail', 1) == 0 and (comp.get('compOk') or 0) > 400
          and (comp.get('inspect11450') or {}).get('damageSegments') == 2,
          f"cup={comp.get('cupSkills')} ok={comp.get('compOk')} fail={comp.get('compFail')} "
          f"inspect11450={(comp.get('inspect11450') or {}).get('damageSegments')} "
          f"effects={comp.get('compEffects')}")

    # ---- 3 displacement ---------------------------------------------------
    tp, cg = (e.get('displacement') or {}).get('teleport') or {}, (e.get('displacement') or {}).get('charge') or {}
    check('3 · 瞬移标记为「由技能触发」且带技能/特技编号',
          tp.get('trigger') == 'skill' and tp.get('skillId') == 22008
          and tp.get('specId', 0) > 0 and bool(tp.get('specName'))
          and '由技能「烟幕游击」' in (e.get('displacement') or {}).get('teleText', ''),
          f"skillId={tp.get('skillId')} spec=#{tp.get('specId')}")
    check('3 · 冲锋标记为「由技能触发」且带技能/特技编号',
          cg.get('trigger') == 'skill' and cg.get('skillId') == 11495
          and cg.get('specId', 0) > 0
          and '由技能「贯穿天际的必胜流星」' in (e.get('displacement') or {}).get('chgText', ''),
          f"skillId={cg.get('skillId')} spec=#{cg.get('specId')}")
    check('3 · step.text 顺序为「走位 → 使用技能 → 技能触发位移」',
          (e.get('displacement') or {}).get('teleText', '').find('使用「烟幕游击」')
          < (e.get('displacement') or {}).get('teleText', '').find('触发位移机制'),
          str((e.get('displacement') or {}).get('teleText', '')[:120]))

    sw = e.get('sweep') or {}
    check('6 · 192 场全量无异常 / 确定性 / Lua 未知 0',
          sw.get('done') == 192 and sw.get('err') == 0 and sw.get('deterministic') is True
          and not sw.get('unknown'),
          str({k: sw.get(k) for k in ('done', 'err', 'unknown')}))
    check('6 · 复合态与条件倍率在全量里真实执行',
          (sw.get('compositeCasts') or 0) > 1000 and (sw.get('boostEvents') or 0) > 0,
          f"casts={sw.get('compositeCasts')} boosts={sw.get('boostEvents')}")

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
        # Scrub to Cole's walk+teleport step.
        page.evaluate("()=>{const r=document.querySelector('#bsim-range');r.value='4';r.dispatchEvent(new Event('input',{bubbles:true}));}")
        page.wait_for_timeout(300)
        check('浏览器 · 移动后没有残留起点圆圈',
              page.locator('#bsim-dyn .bsim-ghost').count() == 0
              and page.locator('#bsim-dyn .bsim-path').count() > 0,
              f"ghost={page.locator('#bsim-dyn .bsim-ghost').count()}")
        detail = page.locator('#bsim-detail').inner_text()
        check('浏览器 · 步骤详情标明「由技能触发位移」与技能复合态',
              '由技能「烟幕游击」' in detail and '触发位移机制 JUMP_MOVE' in detail
              and '技能复合态' in detail,
              detail[:200].replace('\n', ' '))
        card = page.locator('#bsim-units .bsim-unit[data-unit="A2"]')
        if card.count():
            card.first.click()
            page.wait_for_timeout(300)
        # The 当前状态 <details> is collapsed, so inner_text() omits it.
        # Round 55: 烟幕游击's JUMP_MOVE is a straight line (client #30951
        # 「专属_线性传送」), so Cole's landing moved from (7,6) to (5,4).
        # Derive the expected position from THIS replay step instead of a
        # frozen coordinate.
        tele_pos = (e.get('displacement') or {}).get('teleTo') or {}
        expect_pos = f"({tele_pos.get('x')},{tele_pos.get('y')})"
        panel = page.locator('#bsim-panel').text_content() or ''
        check('浏览器 · 角色面板状态块显示当前所在位置',
              '当前状态' in panel and '当前所在位置' in panel
              and tele_pos and expect_pos in panel,
              panel[:220].replace('\n', ' ') + f' | expected {expect_pos}')
        check('浏览器 · 无页面错误', not errors, '; '.join(errors[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
