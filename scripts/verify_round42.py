"""Round 42: client-grounded minimum-move AI, real alert damage, and
inspectable effective-range / knockback / damage state.

    python -X utf8 scripts/verify_round42.py
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
const cole=r.steps.find(s=>s.actor==='A2'&&s.skill?.id===22008)||{};
// path[0] = start, path[last] = JUMP_MOVE landing; walk steps = len-2.
const coleWalk=(cole.path||[]).length-2;
const coleMob=teams.A[1].move.mob;
const alertDamage=(cole.alertHits||[]).map(h=>h.segments.reduce((n,x)=>n+(x.amount||0),0));
const alertSettled=(cole.alertHits||[]).map(h=>h.segments.filter(x=>!x.miss&&x.uid).length);
// A/B: disabling the client min-move rule restores "walk full mobility".
const rFull=S.simulate(opt({skillPriority:{moverMoveTolerance:0,moverMoveTolerancePct:0}}));
const coleFull=rFull.steps.find(s=>s.actor==='A2'&&s.skill?.id===22008)||{};
const coleFullWalk=(coleFull.path||[]).length-2;
// Effective skill state (all range / knockback / damage increases), read at
// the step right BEFORE 流星队 casts 灵光一闪的傲人智慧 (11907), i.e. while
// [后备隐藏脂肪] still holds its battle-start 6 layers. A fixed step index
// drifts whenever the turn order legitimately changes.
const pre11907=r.steps.find(s=>s.actor==='A3'&&s.skill?.id===11907);
const st9=r.inspect(pre11907?Math.max(0,pre11907.seq-1):9,'A3')||{};
const states=st9.skillStates||[];
const meteorState=states.find(x=>x.id===11495)||null;
const selfState=states.find(x=>x.id===11907)||null;
const meteorStep=r.steps.find(s=>s.skill?.id===11495)||{};
const stepState=meteorStep.moveRule?.skillState||null;
const noCast=r.steps.filter(s=>s.kind!=='skill'&&s.moveRule?.noCastReason).map(s=>({
  seq:s.seq,actor:s.actor,reason:s.moveRule.noCastReason})).slice(0,4);
const meteorCasts=r.steps.filter(s=>s.actor==='A3'&&s.skill?.id===11495).length;
const meteorMoves=r.steps.filter(s=>s.actor==='A3'&&s.kind==='move').length;
const sig=x=>JSON.stringify(x.steps.map(s=>s.text+(s.events||[]).join('|')));
const deterministic=sig(r)===sig(S.simulate(opt()));

// 192-schedule sweep: health + "not always walking full mobility".
const mapDefault=W.maps.find(m=>m.id===C.environment.mapId);
let done=0,err=0,ex=[],partial=0,full=0,alertDmg=0,unknown={},skipped={},maxMs=0;
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
    for(const h of st.alertHits||[])alertDmg+=h.segments.reduce((n,x)=>n+(x.amount||0),0);
    if(st.kind!=='skill'||st.teleport||st.charge)continue;
    const steps=(st.path||[]).length-1;
    const mob=st.moveRule?.mobility||0;
    if(!mob||steps<=0)continue;
    if(steps<mob-1)partial++;else full++;
  }
}
console.log(JSON.stringify({
  cole:{from:cole.from,to:cole.to,walk:coleWalk,mobility:coleMob,text:(cole.text||'').slice(0,220),
        alerts:(cole.alertHits||[]).length,alertDamage,alertSettled,
        left:(cole.alertHits||[]).map(h=>h.left)},
  coleFull:{walk:coleFullWalk,text:(coleFull.text||'').slice(0,90)},
  meteorState,selfState,stepState,noCast,meteorCasts,meteorMoves,deterministic,
  preStep:pre11907?Math.max(0,pre11907.seq-1):9,
  sweep:{done,err,ex:ex.slice(0,3),maxMs,partial,full,alertDmg,
    unknown:Object.keys(unknown),skipped:Object.entries(skipped).sort((a,b)=>b[1]-a[1]).slice(0,5)}}));
"""


def main():
    core = (ROOT / 'battle-sim-core.js').read_text('utf8')
    ui = (ROOT / 'battle-sim-ui.js').read_text('utf8')

    for k in ('function castRangeRows', 'function skillStateOf', 'EXTEND_CAST_RANGE',
              'moverMoveTolerance', 'moverMinAdvance', 'filterByMinMoveDist',
              'castValueTolerance', 'const alertCell =', 'noCastReason',
              'skillStates:', 'minMoveSteps: RULE.minMoveSteps'):
        check(f'engine implements {k}', k in core)
    check('UI 展示技能实际射程/击退状态',
          'bsim-skill-state' in ui and 'skillStates' in ui and 'noCastReason' in ui)
    check('AI 不再强制走满（move branch 改为最小移动）',
          '|| a.node.cost - b.node.cost' in core)

    out = subprocess.run([str(NODE), '-e', ENGINE], cwd=ROOT, capture_output=True,
                         text=True, encoding='utf8', timeout=900)
    try:
        e = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        e = {}
        print(out.stdout[-1800:], out.stderr[-1800:])

    c = e.get('cole') or {}
    # ---- 1. movement ------------------------------------------------------
    check('1 · 科尔只走部分步数（未走满、也不是 0）',
          0 < c.get('walk', 0) < c.get('mobility', 0),
          f"walk={c.get('walk')}/{c.get('mobility')} · {c.get('text', '')[:70]}")
    check('1 · 关闭客户端最小移动规则才会走满',
          (e.get('coleFull') or {}).get('walk') == c.get('mobility'),
          f"full={e.get('coleFull', {}).get('walk')} default={c.get('walk')}")
    sw = e.get('sweep') or {}
    check('1 · 全量里存在大量「未走满」的施放',
          (sw.get('partial') or 0) > 100 and (sw.get('partial') or 0) > 0,
          f"partial={sw.get('partial')} full={sw.get('full')}")
    check('1 · move_steps / mobility 写进状态', 'mobility: Number(attr(unit' in core
          and 'minMoveSteps: RULE.minMoveSteps' in core)

    # ---- 2. alert damage --------------------------------------------------
    dmg = c.get('alertDamage') or []
    check('2 · 警戒确实结算出伤害',
          len(dmg) >= 2 and sum(dmg) > 0 and dmg[0] > 0,
          f"segments={c.get('alertSettled')} damage={dmg}")
    check('2 · 一次行动 2 次警戒 / 4 段',
          c.get('alerts') == 2 and sum(c.get('alertSettled') or []) + 2 >= 4
          and '4 段伤害' in c.get('text', ''), str(c.get('text', '')[:90]))
    check('2 · 全量警戒伤害 > 0', (sw.get('alertDmg') or 0) > 1000,
          str(sw.get('alertDmg')))

    # ---- 3. effective range state ----------------------------------------
    ms = e.get('meteorState') or {}
    rows = ms.get('rangeRows') or []
    specs = {r.get('spec') for r in rows}
    check('3 · 所有射程增益都累加（七手八脚/不屈不挠/后备隐藏脂肪）',
          # Round 44: the client's skill_active_param on #14680/#14681
          # (hasTag "Ranged") and #14726 (template.id == 11763) does NOT
          # match 「贯穿天际的必胜流星」(tags = Charge). Only #12417
          # (template.id == 11495, +1/层) applies. The earlier +14 was an
          # artifact of the extractor not exporting that column.
          12417 in specs and not ({14680, 14681, 14726} & specs)
          and ms.get('rangeBonus') == 6 and ms.get('max') == 9 and ms.get('baseMax') == 3,
          f"max={ms.get('max')} bonus={ms.get('rangeBonus')} specs={sorted(specs)}")
    check('3 · 击退距离随层数增加并写进状态',
          ms.get('knockbackBase') == 2 and ms.get('knockbackBonus') == 6
          and ms.get('knockbackTotal') == 8,
          f"{ms.get('knockbackBase')} + {ms.get('knockbackBonus')} = {ms.get('knockbackTotal')}")
    check('3 · 伤害加成写进状态', ms.get('damageBonus') == 30, str(ms.get('damageBonus')))
    check('3 · 自身 zero-range 技能不被误加射程',
          (e.get('selfState') or {}).get('max') == 0, str((e.get('selfState') or {}).get('max')))
    # The 11495 cast step has 10 layers (3 + 10 = 13); inspect(9) above is
    # the earlier [瞬发] step with only 6 layers (3 + 6 = 9).
    check('3 · 回放步骤里也能看到有效射程',
          (e.get('stepState') or {}).get('max') == 13
          and len((e.get('stepState') or {}).get('rangeRows') or []) == 1,
          str((e.get('stepState') or {}).get('max')))
    check('3 · 未施放技能的原因写进状态', bool(e.get('noCast')), str(e.get('noCast')[:1]))
    check('3 · 流星队持续施放技能', (e.get('meteorCasts') or 0) >= 2,
          f"casts={e.get('meteorCasts')} moveOnly={e.get('meteorMoves')}")

    # ---- 4. health --------------------------------------------------------
    check('4 · 192 场全量无异常 / 确定性 / Lua 未知 0',
          sw.get('done') == 192 and sw.get('err') == 0
          and e.get('deterministic') is True and not sw.get('unknown'),
          str({k: sw.get(k) for k in ('done', 'err', 'unknown')}))
    check('4 · 无 BUFF 缺数据', not any('BUFF#' in str(k) for k in (sw.get('skipped') or [])),
          str(sw.get('skipped')))

    # ---- browser ----------------------------------------------------------
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
            page.wait_for_timeout(1300)
        # Scrub to the step right before 流星队's [瞬发] 11907 (6 layers).
        pre = int(e.get('preStep') if e.get('preStep') is not None else 9)
        page.evaluate("(i)=>{const r=document.querySelector('#bsim-range');r.value=String(i);r.dispatchEvent(new Event('input',{bubbles:true}));}", pre)
        page.wait_for_timeout(300)
        card = page.locator('#bsim-units .bsim-unit[data-unit="A3"]')
        if card.count() and not page.locator('.bsim-skill-state').count():
            card.first.click()
            page.wait_for_timeout(300)
        block = page.locator('.bsim-skill-state')
        panel = block.inner_text() if block.count() else ''
        check('浏览器 · 角色面板显示实际射程与客户端增益来源',
              '技能实际射程' in panel and '1–9' in panel and '12417' in panel,
              panel[:220].replace('\n', ' '))
        check('浏览器 · 角色面板显示击退与伤害加成',
              '击退' in panel and '8' in panel and '+30%' in panel,
              panel[:220].replace('\n', ' '))
        log_text = page.locator('#bsim-log').inner_text()
        check('浏览器 · 战斗日志里警戒有伤害数值',
              '警戒' in log_text and ('伤害数值' in log_text or '2 次警戒' in log_text))
        check('浏览器 · 无页面错误', not errors, '; '.join(errors[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
