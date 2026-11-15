"""Round 37: comprehensive client AIMachine / alert / speciality application.

    python -X utf8 scripts/verify_round37.py
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


def load(rel, var):
    t = (ROOT / rel).read_text('utf8'); m = 'window.' + var + '='
    return json.JSONDecoder().raw_decode(t[t.index(m) + len(m):])[0]


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
const map332=W.maps.find(m=>m.id===332);
const sc=C.schedules.find(x=>x.id===90);
const buffs=(sc.buffDetails||[]).filter(b=>b.buffId).map(b=>({buffId:b.buffId,side:side(b.target)}));
const teams={A:mem(team(sc.team1Id)),B:mem(team(sc.team2Id))};
const unitStatus=[];
for(const st of sc.unitStatus||[]){const s=st.teamIndex===1?'A':'B';
  const i=teams[s].findIndex(m=>Number(m.npcId)===Number(st.npcId));
  if(i>=0&&st.buffId)unitStatus.push({buffId:st.buffId,side:s,index:i});}
const userOpt=(seed,rounds)=>({data:D,mech:M,map:map332,teams,mode:'left',seed,maxRounds:rounds||4,
  env:{weatherId:C.environment.weatherId,buffs,unitStatus},spawns:{A:PLAN.A,B:PLAN.B},substrate:SUB});
const r=S.simulate(userOpt(20261107,4));
const nameOf=uid=>(r.units.find(u=>u.uid===uid)||{}).name||'';
const steps=r.steps.slice(1,6).map(st=>({name:nameOf(st.actor),from:st.from,to:st.to,kind:st.kind,
  skill:st.skill?.name||null,target:st.target||null,alts:(st.alts||[]).map(a=>a.skill),
  candidates:st.candidates||[],alert:st.alert||null,alertHit:st.alertHit||null,
  alertHits:st.alertHits||[],teleport:st.teleport||null,charge:st.charge||null,
  path:st.path||[],text:st.text||'',events:st.events||[],moveRule:st.moveRule||{}}));
const alertEvents=r.steps.flatMap(s=>(s.events||[]).filter(e=>/警戒/.test(e)));
const inspect3=r.inspect(3,'B1');
const inspect4=r.inspect(4,'A2');

// Ally pass-through probe: a friendly unit stands between start and goal.
const passThrough=(()=>{
  const st=r.steps[3];
  return {from:st.from,to:st.to,path:st.path||[]};
})();

// Full 192-match sweep
const mapDefault=W.maps.find(m=>m.id===C.environment.mapId);
let done=0,err=0,ex=[],alerts=0,triggers=0,shares=0,teleports=0,cands=0,
    alertBonuses=0,propsCasts=0,skills=0,moves=0,maxMs=0;
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
    if(st.kind==='skill')skills++;if(st.kind==='move')moves++;
    if(st.teleport)teleports++;
    if(st.candidates?.length)cands+=st.candidates.length;
    if(st.consumption)propsCasts++;
    if(st.alertHit){triggers++;if(st.alertHit.countBonus)alertBonuses++;}
    for(const e of st.events||[]){
      if(/展开警戒/.test(e))alerts++;
      if(/将 [0-9]+ 伤害分摊给/.test(e))shares++;
    }
  }
  for(const [k,v] of Object.entries(o.mechanics.skipped||{}))skipped[k]=(skipped[k]||0)+v;
  for(const [k,v] of Object.entries(o.mechanics.luaUnknown||{}))unknown[k]=(unknown[k]||0)+v;
}
const a=S.simulate(userOpt(20261107,3)),b=S.simulate(userOpt(20261107,3));
const sig=x=>JSON.stringify(x.steps.map(s=>s.text+(s.events||[]).join('|')));
console.log(JSON.stringify({steps,alertEvents,inspect3:{alert:inspect3?.alert,ai:inspect3?.ai},
  inspect4:{alert:inspect4?.alert},passThrough,
  substrate:{specialityTypes:SUB.specialityTypes,clientMechanisms:SUB.clientMechanisms,
    targetSorts:SUB.targetSorts,countRows:SUB.specialityCountTurnRows,
    effectCoverage:SUB.engineCoverage},
  sweep:{done,err,ex:ex.slice(0,3),maxMs,alerts,triggers,shares,teleports,cands,alertBonuses,
    propsCasts,skills,moves,unknown:Object.entries(unknown).sort((a,b)=>b[1]-a[1]).slice(0,4),
    skipped:Object.entries(skipped).sort((a,b)=>b[1]-a[1]).slice(0,4)},
  deterministic:sig(a)===sig(b)}));
"""


def main():
    core = (ROOT / 'battle-sim-core.js').read_text('utf8')
    ui = (ROOT / 'battle-sim-ui.js').read_text('utf8')
    SUB = load('data/client-mechanisms.js', 'WIKI_CLIENT_MECHANISMS')
    M = load('data/battle-mech.js', 'WIKI_BATTLE_MECH')

    # ---- 5/6: client mechanisms actually implemented -------------------
    mechanisms = ['all_skill_list', 'cur_skill', 'skill_orders', 'boss_skill_mode',
                  'bossRotation', 'countBonusOf', 'SPECIALITY_COUNT_TURN',
                  'PathAlert', 'CollectAlertBlocks', 'FindAlertTargetBlocks',
                  'checkAlert(mover, cell)', 'JUMP_MOVE', 'sim.teleport',
                  'target_order_param', 'hide_alert_preivew', 'ALERT_ATTACK_DISPLAY',
                  'STRENGTHEN_ALERT', 'FORCE_STOP', 'sortByPropsCountNoFade',
                  'sortByMoveAndTargetDist', 'posCompare', 'getQuadrant',
                  'skill_list_tag', 'ai_move_close', 'move_steps', 'prev_block_min',
                  'offset_moves', 'alert_dist', 'alert_points']
    for k in mechanisms:
        check(f'client mechanism {k}', k in core)
    check('ally pass-through is side-aware',
          'if (blocker && blocker.side !== unit.side) continue;' in core)
    check('no exclusive per-action skill rotation',
          'declaredRotation' not in core and 'bossRotation' in core)
    decide = core[core.index('function decide(unit, reachOverride) {'):
                  core.index('function inRange(u, target, s, counter) {')]
    for name in ('安娜', '阿列克谢', '科尔', '乌莉娅', '玛莎', '黑暗医师'):
        check(f'no hard-coded {name} in decide()', name not in decide)

    # ---- substrate data --------------------------------------------------
    st = SUB.get('specialityTypes') or {}
    check('speciality type ids are client-derived',
          st.get('ALERT_ATTACK') == 29 and st.get('COUNTER_ATTACK') == 12
          and st.get('FIRST_HIT') == 13, str(st))
    check('SPECIALITY_COUNT_TURN rows counted', (SUB.get('specialityCountTurnRows') or 0) >= 12,
          str(SUB.get('specialityCountTurnRows')))
    cm = SUB.get('clientMechanisms') or {}
    for k in ('allSkillList', 'curSkill', 'pathAlert', 'collectAlertBlocks',
              'specialityCountTurn', 'jumpMove', 'hideAlertPreview', 'alliesPassable'):
        check(f'substrate mechanism {k}', cm.get(k) is True, str(cm.get(k)))
    check('alert count aura exists in client data',
          M['specs']['7709']['p'][1] == 29 and M['buffs']['7739']['sp'] == [7709]
          and 25612 in M['skills']['19451']['sp'])
    check('JUMP_MOVE is on 烟幕游击',
          any(M['specs'][str(x)]['t'] == 'JUMP_MOVE' for x in M['skills']['22008']['sp']))
    check('UI exposes all candidates', 'step.candidates' in ui and 'bsim-candidate' in ui)
    check('UI shows alert point breakdown', 'alertBasePoints' in ui or 'step.alert.countBonus' in ui)
    check('UI shows reaction + teleport', 'bsim-alert-hit' in ui and 'bsim-teleport' in ui)

    out = subprocess.run([str(NODE), '-e', ENGINE], cwd=ROOT, capture_output=True,
                         text=True, encoding='utf8', timeout=900)
    try:
        e = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        e = {}
        print(out.stdout[-1500:], out.stderr[-1500:])

    s = e.get('steps') or []

    # ---- 1. Anna walks AND casts 爆裂箭 ---------------------------------
    check('1 · 安娜第一步走到 (7,5)',
          len(s) > 1 and s[1]['name'] == '安娜' and s[1]['to'] == {'x': 7, 'y': 5},
          str(s[1] if len(s) > 1 else s))
    check('1 · 安娜同时施放「爆裂箭」（走打，不是只走）',
          len(s) > 1 and s[1]['skill'] == '爆裂箭' and s[1]['kind'] == 'skill',
          str(s[1].get('skill') if len(s) > 1 else s))
    # Round 46: the 3 hits are now the client's own skill_cast_id chain
    # (19449 → 18975 → 18976), each its own cast; the 「第 1/3 段」label of the
    # description-derived plan no longer exists. Assert the client facts: 3
    # direct hits from the chain + the 消耗转化 bonus is settled.
    ev1 = ' '.join(s[1].get('events') or []) if len(s) > 1 else ''
    check('1 · 爆裂箭按 3 段（skill_cast_id 链）+ 消耗追加伤害结算',
          len(s) > 1 and s[1]['text'].count('造成') >= 3
          and ('追加' in s[1]['text'] or '消耗转化' in ev1),
          s[1]['text'][:160] if len(s) > 1 else '')
    check('1 · all_skill_list 含抉择选项',
          len(s) > 1 and {'爆裂箭', '彻甲箭', '裂伤箭'} <= {c['skill'] for c in s[1]['candidates']},
          str([c['skill'] for c in s[1]['candidates']]) if len(s) > 1 else '')

    # ---- 2. Alexei landing + ally pass-through --------------------------
    check('2 · 阿列克谢·SP 第一步走到 (9,5)',
          len(s) > 2 and s[2]['name'] == '阿列克谢·SP' and s[2]['to'] == {'x': 9, 'y': 5},
          str(s[2] if len(s) > 2 else s))
    check('2 · 友军格可穿越（引擎按 side 判定，非全体阻断）',
          'if (blocker && blocker.side !== unit.side) continue;' in core)
    check('2 · 乌莉娅仍走到 (12,3) 施放「天降蜜果啦！」',
          len(s) > 0 and s[0]['to'] == {'x': 12, 'y': 3} and s[0]['skill'] == '天降蜜果啦！',
          str(s[0] if s else s))

    # ---- 3. all skill candidates ----------------------------------------
    check('3 · 科尔第一步使用「烟幕游击」',
          len(s) > 3 and s[3]['name'] == '科尔' and s[3]['skill'] == '烟幕游击',
          str(s[3] if len(s) > 3 else s))
    check('3 · 科尔有多个技能候选（all_skill_list）',
          len(s) > 3 and len(s[3]['candidates']) >= 2
          and any(c['skill'] != '烟幕游击' for c in s[3]['candidates']),
          str([(c['skill'], c['score']) for c in s[3]['candidates']]) if len(s) > 3 else '')
    check('3 · 候选带站位、目标、声明优先级',
          len(s) > 3 and all({'stand', 'target', 'priority', 'declared'} <= set(c)
                             for c in s[3]['candidates']),
          str(s[3]['candidates'][:1]) if len(s) > 3 else '')
    check('3 · moveRule 暴露 allSkillList / curSkill / 优先级',
          len(s) > 3 and (s[3]['moveRule'].get('allSkillList') or [])
          and 'priority' in s[3]['moveRule'], str(s[3]['moveRule'])[:200] if len(s) > 3 else '')

    # ---- 4. alert hits Cole, aura count included ------------------------
    check('4 · 安娜展开警戒', any('展开警戒' in x for x in e.get('alertEvents', [])),
          str(e.get('alertEvents', [])[:2]))
    check('4 · 警戒次数 = 基础 2 + 光环 1 = 3',
          len(s) > 1 and s[1]['alert'] and s[1]['alert']['points'] == 3
          and s[1]['alert']['basePoints'] == 2 and s[1]['alert']['countBonus'] == 1,
          str(s[1]['alert'] if len(s) > 1 else ''))
    # Round 55: 烟幕游击's JUMP_MOVE is now a straight line (client #30951
    # 「专属_线性传送」), so Cole walks a different path before the teleport.
    # The mechanism to assert is that the alert fires on a block of COLE'S
    # ACTUAL WALK PATH, not on a frozen coordinate.
    check('4 · 科尔瞬移落地触发安娜警戒（触发格在其真实走位路径上）',
          len(s) > 3 and (s[3]['alertHit'] or {}).get('owner') == '安娜'
          and any(p.get('x') == (s[3]['alertHit'] or {}).get('cell', {}).get('x')
                  and p.get('y') == (s[3]['alertHit'] or {}).get('cell', {}).get('y')
                  for p in s[3].get('path', [])),
          str({'cell': (s[3]['alertHit'] or {}).get('cell') if len(s) > 3 else None,
               'path': s[3].get('path') if len(s) > 3 else None}))
    # Round 40: the client walks into the alert zone BEFORE the [瞬发]
    # JUMP_MOVE, so the teleport no longer lands on (7,9) from the spawn tile.
    check('4 · 科尔先走进警戒范围、再瞬移（JUMP_MOVE 落地）',
          len(s) > 3 and bool(s[3]['teleport'])
          and s[3]['from'] != s[3]['teleport']['from']
          and s[3]['teleport']['to'] != s[3]['from'],
          str({'from': s[3]['from'] if len(s) > 3 else None,
               'teleport': s[3]['teleport'] if len(s) > 3 else None}))
    check('4 · 一次行动触发 2 次警戒共 4 段伤害',
          len(s) > 3 and len(s[3]['alertHits']) == 2
          and sum(h.get('segmentCount', h.get('hits', 1)) for h in s[3]['alertHits']) == 4,
          str(s[3]['alertHits'] if len(s) > 3 else ''))
    check('4 · 角色面板显示警戒次数加成',
          ((e.get('inspect3') or {}).get('alert') or {}).get('countBonus') == 1,
          str((e.get('inspect3') or {}).get('alert')))
    check('4 · 警戒反应记录剩余次数',
          len(s) > 3 and (s[3]['alertHit'] or {}).get('left') == 2,
          str(s[3]['alertHit'] if len(s) > 3 else ''))

    # ---- 5/6: scale ------------------------------------------------------
    sw = e.get('sweep') or {}
    check('192 场全量无异常', sw.get('done') == 192 and sw.get('err') == 0, str(sw.get('ex')))
    check('无 Lua 未知条件', not sw.get('unknown'), str(sw.get('unknown')))
    check('全量候选可见', (sw.get('cands') or 0) > 5000, str(sw.get('cands')))
    check('瞬移在全量生效', (sw.get('teleports') or 0) > 20, str(sw.get('teleports')))
    check('警戒与光环加成在全量生效',
          (sw.get('triggers') or 0) > 50 and (sw.get('alertBonuses') or 0) > 50,
          f"triggers={sw.get('triggers')} bonuses={sw.get('alertBonuses')}")
    check('分摊伤害等既有机制未被破坏', (sw.get('shares') or 0) > 100, str(sw.get('shares')))
    check('消耗转化等既有机制未被破坏', (sw.get('propsCasts') or 0) > 20, str(sw.get('propsCasts')))
    check('确定性保持', e.get('deterministic') is True)

    # ---- browser ---------------------------------------------------------
    errors, failed = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        c = browser.new_context(offline=True, viewport={'width': 1600, 'height': 1000})
        page = c.new_page()
        page.set_default_timeout(40000)
        page.on('pageerror', lambda x: errors.append(str(x)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda rq: failed.append(rq.url))
        page.goto(BASE + '#/tools/battle')
        page.locator('#bsim-board svg').wait_for()
        page.evaluate("()=>{document.querySelector('.bsim-cup').open=true;}")
        page.evaluate("()=>{document.querySelector('#bsim-spawn-edit').open=true;}")
        if PLAN.exists():
            page.locator('#bsim-plan-file').set_input_files(str(PLAN))
            page.wait_for_timeout(1500)
            check('浏览器导入方案切换到赛程 90',
                  page.locator('#bsim-cup-sched').input_value() == '90')
            mx = int(page.locator('#bsim-range').get_attribute('max') or 0)
            hits = {'anna': '', 'candidates': '', 'alert': '', 'jump': ''}
            cand_max = 0
            for i in range(0, min(mx, 8)):
                page.evaluate("(i)=>{const r=document.querySelector('#bsim-range');r.value=String(i);r.dispatchEvent(new Event('input',{bubbles:true}));}", i)
                page.wait_for_timeout(20)
                cand_max = max(cand_max, page.locator('.bsim-candidate').count())
                d = page.locator('#bsim-detail').inner_text()
                # Round 46: 3 段 now come from the client's skill_cast_id
                # chain (19449 → 18975 → 18976) as three separate casts, so
                # the old 「第 1/3 段」label is gone. Check the walk-and-cast
                # plus the linked-cast markers the replay panel now shows.
                if '爆裂箭' in d and '移动到 (7,5)' in d and (
                        '连射2' in d or 'skill_cast_id' in d or '造成' in d):
                    hits['anna'] = d[:220]
                if 'all_skill_list' in d:
                    hits['candidates'] = d[:220]
                if '基础 2 + 光环/特技 1' in d or '每回合 3 次' in d:
                    hits['alert'] = d[:220]
                if 'JUMP_MOVE' in d and '瞬移' in d:
                    hits['jump'] = d[:220]
            check('浏览器显示安娜走打爆裂箭', bool(hits['anna']), hits['anna'][:90])
            check('浏览器显示全部技能候选', bool(hits['candidates']), hits['candidates'][:90])
            check('浏览器显示警戒次数拆分', bool(hits['alert']), hits['alert'][:90])
            check('浏览器显示瞬移与警戒反应', bool(hits['jump']), hits['jump'][:90])
            check('候选面板 DOM 存在', cand_max >= 2, str(cand_max))
        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
