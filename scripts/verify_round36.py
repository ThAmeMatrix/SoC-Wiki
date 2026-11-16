"""Round 36: client-accurate AIMachine skill order, walk priority and 警戒.

    python -X utf8 scripts/verify_round36.py
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
PLAN_V1 = Path('C:/Users/thamechen/Downloads/铃兰档案馆-站位方案-332-赛程90.json')
failures = []


def check(name, ok, detail=''):
    print(('PASS ' if ok else 'FAIL ') + name + (f' :: {detail}' if detail else ''), flush=True)
    if not ok:
        failures.append(name)


def load(rel, var):
    t = (ROOT / rel).read_text('utf8'); m = 'window.' + var + '='
    return json.JSONDecoder().raw_decode(t[t.index(m) + len(m):])[0]


ENGINE = r"""
const fs=require('fs'),vm=require('vm');const ctx={window:{}};vm.createContext(ctx);
for(const f of ['data/world-data.js','data/battle-sim.js','data/match-cup.js','data/battle-mech.js',
                'data/client-mechanisms.js','battle-sim-core.js'])
  vm.runInContext(fs.readFileSync(f,'utf8'),ctx);
const W=ctx.window.WIKI_WORLD_DATA,D=ctx.window.WIKI_BATTLE_SIM,C=ctx.window.WIKI_MATCH_CUP,
      M=ctx.window.WIKI_BATTLE_MECH,SUB=ctx.window.WIKI_CLIENT_MECHANISMS,S=ctx.window.WikiBattleSim;
const mk=m=>({name:m.name,stats:m.stats,move:m.move,prof:m.profName,kit:m.kit,skills:m.skills,
  edited:false,npcId:m.npcId,star:m.star,statLevel:m.statLevel});
const team=id=>C.teams.find(t=>t.id===id),mem=t=>t.members.map(mk);
const side=t=>t===1?'A':t===2?'B':'both';
const PLAN=JSON.parse(fs.readFileSync('C:/Users/thamechen/Downloads/铃兰档案馆-站位方案-332-赛程90 (1).json','utf8')).plans[0];
const map332=W.maps.find(m=>m.id===332);
const sched=C.schedules.find(x=>x.id===90);
const buffs=(sched.buffDetails||[]).filter(b=>b.buffId).map(b=>({buffId:b.buffId,side:side(b.target)}));
const teams={A:mem(team(sched.team1Id)),B:mem(team(sched.team2Id))};
const unitStatus=[];
for(const st of sched.unitStatus||[]){
  const s=st.teamIndex===1?'A':'B';
  const i=teams[s].findIndex(m=>Number(m.npcId)===Number(st.npcId));
  if(i>=0&&st.buffId)unitStatus.push({buffId:st.buffId,side:s,index:i});
}
const userOpt=seed=>({data:D,mech:M,map:map332,teams,mode:'left',seed,maxRounds:4,
  env:{weatherId:C.environment.weatherId,buffs,unitStatus},spawns:{A:PLAN.A,B:PLAN.B},substrate:SUB});
const nameOf=(r,uid)=>(r.units.find(u=>u.uid===uid)||{}).name||'';

// ---- 1. The four client replay actions -----------------------------------
const r=S.simulate(userOpt(20261107));
const first=r.steps.slice(1,5).map(st=>({name:nameOf(r,st.actor),to:st.to,skill:st.skill?.name||null,
  kind:st.kind,alert:st.alert||null,alertHit:st.alertHit||null,candidates:st.candidates||[]}));
const alertEvents=r.steps.flatMap(s=>(s.events||[]).filter(e=>/展开警戒|警戒触发/.test(e)));

// ---- 2. 警戒 state on Anna ----------------------------------------------
const p=r.inspect(3,'B1');
const alertPanel={alert:p.alert,ai:p.ai};
const snapAlert=r.steps[2].snap.find(z=>z.uid==='B1')?.al||null;

// ---- 3. 抉择 group is resolved before battle, not cast as an action ------
const choiceCasts=r.steps.filter(s=>s.skill?.name==='猎手素养'||s.skill?.name==='潜袭').length;

// ---- 4. Data-driven AI columns -------------------------------------------
const aiCols={byOrder:teams.B.filter(m=>m.kit?.aiByOrder).length,
  withOrder:teams.B.filter(m=>(m.kit?.skillOrder||[]).length).length};
const subAi=SUB.aiFields||{};
const fullLua=Object.values(M.skills).filter(s=>(s.aop||'').length>120).length;
const alertSpecs=Object.values(M.specs).filter(s=>s.t==='ALERT_ATTACK').length;

// ---- 5. All-unit occupancy vs. pass-through -----------------------------
const occupancyProbe=(()=>{
  // (11,4) is blocked to the west by 玛莎 at (10,4); the client detours.
  const a=S.simulate(userOpt(20261107));
  const st=a.steps[3];
  return {to:st.to,from:st.from};
})();

// ---- 6. Full 192-match sweep ---------------------------------------------
const mapDefault=W.maps.find(m=>m.id===C.environment.mapId);
let done=0,err=0,ex=[],maxMs=0,alerts=0,triggers=0,byOrderSteps=0,shares=0,
    jumps=0,groups=0,moves=0;
const unknown={},skipped={};const t0=Date.now();
for(const s of C.schedules){
  const bf=(s.buffDetails||[]).filter(b=>b.buffId).map(b=>({buffId:b.buffId,side:side(b.target)}));
  const st=Date.now();let o;
  try{o=S.simulate({data:D,mech:M,map:mapDefault,
    teams:{A:mem(team(s.team1Id)),B:mem(team(s.team2Id))},mode:'left',seed:1000+s.id,maxRounds:20,
    env:{weatherId:C.environment.weatherId,buffs:bf},substrate:SUB});}
  catch(e){err++;ex.push(s.id+':'+e.message);continue;}
  maxMs=Math.max(maxMs,Date.now()-st);
  if(o.error){err++;continue;}
  done++;
  for(const step of o.steps){
    if(step.moveRule?.aiByOrder)byOrderSteps++;
    if(step.kind==='move')moves++;
    if(step.skill?.name==='猎手素养'||step.skill?.name==='潜袭')groups++;
    if(step.skill?.name==='烟幕游击')jumps++;
    for(const e of step.events||[]){
      if(/展开警戒/.test(e))alerts++;
      if(/警戒触发/.test(e))triggers++;
      if(/将 [0-9]+ 伤害分摊给/.test(e))shares++;
    }
  }
  for(const [k,v] of Object.entries(o.mechanics.skipped||{}))skipped[k]=(skipped[k]||0)+v;
  for(const [k,v] of Object.entries(o.mechanics.luaUnknown||{}))unknown[k]=(unknown[k]||0)+v;
}
const sweep={done,err,ex:ex.slice(0,3),maxMs,totalMs:Date.now()-t0,alerts,triggers,
  byOrderSteps,shares,jumps,groups,moves,
  unknown:Object.entries(unknown).sort((a,b)=>b[1]-a[1]).slice(0,4),
  skipped:Object.entries(skipped).sort((a,b)=>b[1]-a[1]).slice(0,4)};
const a=S.simulate(userOpt(7)),b=S.simulate(userOpt(7));
const sig=x=>JSON.stringify(x.steps.map(s=>s.text+(s.events||[]).join('|')));
console.log(JSON.stringify({first,alertEvents,alertPanel,snapAlert,choiceCasts,aiCols,
  subAi,fullLua,alertSpecs,occupancyProbe,sweep,deterministic:sig(a)===sig(b)}));
"""


def main():
    core = (ROOT / 'battle-sim-core.js').read_text('utf8')
    ui = (ROOT / 'battle-sim-ui.js').read_text('utf8')
    M = load('data/battle-mech.js', 'WIKI_BATTLE_MECH')
    SUB = load('data/client-mechanisms.js', 'WIKI_CLIENT_MECHANISMS')
    C = load('data/match-cup.js', 'WIKI_MATCH_CUP')

    # 1. Data-driven implementation (no character names in decide())
    for key in ('aiByOrder', 'bossRotation', 'choiceOptions', 'skillOrderIndex',
                'aiFields', 'alertState', 'alertReach', '展开警戒', 'ALERT_ATTACK_DISPLAY',
                'hidePreview', 'sortByNearEnemy', 'prev_block_min',
                '(rule === null && blocker.side !== unit.side)',
                'const c = cost + n.step;', 'jumpGround', 'aiPriority',
                'all_skill_list', 'countBonusOf', 'sim.teleport', 'checkAlert(mover, cell)',
                'sortByPropsCountNoFade', 'target_order_param'):
        check(f'engine {key}', key in core)
    for key in ('bsim-alert-note', 'ai_skill_by_order', 'bsim-alert-panel', 'expand'):
        if key == 'expand':
            continue
        check(f'UI {key}', key in ui)
    decide = core[core.index('function decide(unit, reachOverride) {'):
                  core.index('function inRange(u, target, s, counter) {')]
    for name in ('安娜', '阿列克谢', '科尔', '乌莉娅', '玛莎', '黑暗医师'):
        check(f'no hard-coded {name} in decide()', name not in decide)
    check('AI fields in substrate', len(SUB.get('aiFields', {})) >= 15,
          str(len(SUB.get('aiFields', {}))))
    check('full ai_order_param Lua exported',
          any(len(s.get('aop') or '') > 120 for s in M['skills'].values()))
    check('hide_alert_preivew exported', any(s.get('hap') for s in M['skills'].values()))
    team208 = next(t for t in C['teams'] if t['id'] == 208)
    check('declared skill order exported',
          all((m['kit'].get('skillOrder') or []) for m in team208['members']))
    check('aiByOrder from unit_npc', sum(1 for m in team208['members']
          if m['kit'].get('aiByOrder')) >= 3)

    out = subprocess.run([str(NODE), '-e', ENGINE], cwd=ROOT, capture_output=True,
                         text=True, encoding='utf8', timeout=900)
    try:
        e = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        e = {}
        print(out.stdout[-1200:], out.stderr[-1500:])

    f = e.get('first') or []
    check('step 1 乌莉娅 → (12,3) 天降蜜果啦！',
          len(f) > 0 and f[0]['to'] == {'x': 12, 'y': 3} and f[0]['skill'] == '天降蜜果啦！',
          str(f[0] if f else f))
    # Round 37: the client's all_skill_list keeps 爆裂箭 as a candidate while
    # walking; 安娜 walks to (7,5) AND casts it (走打), rather than only walking.
    check('step 2 安娜 → (7,5) 并施放「爆裂箭」',
          len(f) > 1 and f[1]['name'] == '安娜' and f[1]['to'] == {'x': 7, 'y': 5}
          and f[1]['skill'] == '爆裂箭', str(f[1] if len(f) > 1 else f))
    check('step 3 阿列克谢·SP → (9,5)（纯行走）',
          len(f) > 2 and f[2]['name'] == '阿列克谢·SP' and f[2]['to'] == {'x': 9, 'y': 5}
          and f[2]['kind'] == 'move', str(f[2] if len(f) > 2 else f))
    check('step 4 科尔 首先使用「烟幕游击」',
          len(f) > 3 and f[3]['name'] == '科尔' and f[3]['skill'] == '烟幕游击',
          str(f[3] if len(f) > 3 else f))
    check('安娜回合结束展开警戒', any('展开警戒' in x for x in e.get('alertEvents', [])),
          str(e.get('alertEvents', [])[:2]))
    # Round 37: SPECIALITY_COUNT_TURN from 冰雪中的反抗's 警戒次数+1 aura adds
    # one use: 2 (limit_count_turn) + 1 = 3 (alert_points).
    check('警戒范围 4 格、每回合 3 次（基础 2 + 光环 1）、强制警戒',
          (e.get('first') or [{}])[1].get('alert', {}).get('dist') == 4
          and (e.get('first') or [{}])[1].get('alert', {}).get('points') == 3
          and (e.get('first') or [{}])[1].get('alert', {}).get('strengthened') is True,
          str((e.get('first') or [{}])[1].get('alert')))
    check('警戒次数含光环加成', (e.get('alertPanel') or {}).get('alert', {}).get('countBonus') == 1
          and (e.get('alertPanel') or {}).get('alert', {}).get('basePoints') == 2,
          str((e.get('alertPanel') or {}).get('alert')))
    check('科尔瞬移到 (7,9) 并触发安娜警戒',
          (e.get('first') or [{}])[3].get('alertHit', {}).get('cell') == {'x': 7, 'y': 9},
          str((e.get('first') or [{}])[3].get('alertHit')))
    check('科尔有多个技能候选', len((e.get('first') or [{}])[3].get('candidates') or []) >= 2,
          str((e.get('first') or [{}])[3].get('candidates')))
    check('角色面板暴露警戒状态', (e.get('alertPanel') or {}).get('alert', {}).get('dist') == 4,
          str((e.get('alertPanel') or {}).get('alert')))
    check('角色面板暴露按序 AI', (e.get('alertPanel') or {}).get('ai', {}).get('byOrder') is True)
    check('快照带出警戒状态', (e.get('snapAlert') or {}).get('d') == 4, str(e.get('snapAlert')))
    check('抉择技能在战前解析，不占行动', e.get('choiceCasts') == 0, str(e.get('choiceCasts')))
    check('(11,4) 穿越友军格后落到 (9,5)',
          (e.get('occupancyProbe') or {}).get('to') == {'x': 9, 'y': 5},
          str(e.get('occupancyProbe')))
    check('ALERT_ATTACK 特技存在', (e.get('alertSpecs') or 0) >= 2, str(e.get('alertSpecs')))

    sw = e.get('sweep') or {}
    check('192 场全量无异常', sw.get('done') == 192 and sw.get('err') == 0, str(sw.get('ex')))
    check('无 Lua 未知条件', not sw.get('unknown'), str(sw.get('unknown')))
    check('警戒在规模上生效', (sw.get('alerts') or 0) > 100 and (sw.get('triggers') or 0) > 20,
          f"alerts={sw.get('alerts')} triggers={sw.get('triggers')}")
    check('按序 AI 在规模上生效', (sw.get('byOrderSteps') or 0) > 1000,
          str(sw.get('byOrderSteps')))
    check('分摊伤害等既有机制未被破坏', (sw.get('shares') or 0) > 100, str(sw.get('shares')))
    check('瞬移空地技能仍会施放', (sw.get('jumps') or 0) > 0, str(sw.get('jumps')))
    check('确定性保持', e.get('deterministic') is True)

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
        if PLAN.exists():
            page.locator('#bsim-plan-file').set_input_files(str(PLAN))
            page.wait_for_timeout(1500)
            check('导入方案切换到赛程 90', page.locator('#bsim-cup-sched').input_value() == '90')
            found = {}
            mx = int(page.locator('#bsim-range').get_attribute('max') or 0)
            for i in range(0, min(mx, 8)):
                page.evaluate("(i)=>{const r=document.querySelector('#bsim-range');r.value=String(i);r.dispatchEvent(new Event('input',{bubbles:true}));}", i)
                page.wait_for_timeout(20)
                d = page.locator('#bsim-detail').inner_text()
                if '移动到 (7,5)' in d:
                    found['anna'] = d[:180]
                    found['alertNote'] = page.locator('.bsim-alert-note').count()
                    page.evaluate("()=>{const d=document.querySelector('.bsim-move-rule'); if(d) d.open=true;}")
                    found['aiOrder'] = 'ai_skill_by_order' in \
                        page.locator('#bsim-detail').inner_text()
                if '展开警戒' in d:
                    found['alert'] = d[:220]
                if '烟幕游击' in d:
                    found['jump'] = d[:160]
            check('浏览器显示安娜走到 (7,5)', 'anna' in found, str(found.get('anna', ''))[:90])
            check('浏览器显示展开警戒面板', 'alert' in found
                  and found.get('alertNote', 0) >= 1, str(found.get('alert', ''))[:90])
            check('浏览器显示科尔烟幕游击', 'jump' in found)
            check('步骤详情列出声明技能顺序', found.get('aiOrder') is True,
                  str(found.get('aiOrder')))
        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
