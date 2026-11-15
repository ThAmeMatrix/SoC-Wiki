"""Round 39: 一段警戒 2 段伤害 / 客户端 range_select 技能范围 / 角色面板误跳 pages/0.

    python -X utf8 scripts/verify_round39.py

Uses 赛程 90 · 地图 332 的站位方案 plus the full 192 schedule sweep and a
browser pass over the right-hand unit cards.
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
const alerts=r.steps.filter(s=>s.alertHit).map(s=>({hit:s.alertHit,
  events:(s.events||[]).filter(e=>/警戒|段|闪避|CloneClone|强制停止/.test(e))}));

// ---- client range_select geometry -------------------------------------
const meteor=M.skills['11495'], arrow=M.skills['19449'];
const meteorShape=S.castShape(meteor), meteorCells=S.castRangeCells(meteor,1,3);
const diamondCells=S.castRangeOffsets(1,3,'diamond',1);
const directionId=Object.entries(M.skills).find(([id,s])=>s.ts===4&&s.rmax>1)?.[0];
const directionRec=directionId?M.skills[directionId]:null;
const directionCells=directionRec?S.castRangeCells(directionRec,1,3):[];
const geometry={meteor:{id:11495,n:meteor.n,ts:meteor.ts,rt:meteor.rt,shape:meteorShape,
    rmin:meteor.rmin,rmax:meteor.rmax,cells:meteorCells.length,
    diagonals:meteorCells.filter(([x,y])=>x!==0&&y!==0).length},
  diamond:{shape:S.castShape(arrow),cells:diamondCells.length,
    diagonals:diamondCells.filter(([x,y])=>x!==0&&y!==0).length},
  direction:{id:Number(directionId)||0,n:directionRec?.n||'',shape:directionRec?S.castShape(directionRec):'',
    cells:directionCells.length,diagonals:directionCells.filter(([x,y])=>x!==0&&y!==0).length},
  shapes:S.RANGE_SELECT};

// ---- full sweep: line-shaped casts never aim at a diagonal ------------
const mapDefault=W.maps.find(m=>m.id===C.environment.mapId);
const LINE=new Set(['cross_line','direction','rect','side_line','horizontal_line']);
let done=0,err=0,ex=[],lineCandidates=0,diagonalViolations=0,meteorCasts=0,meteorDiagonal=0,maxMs=0;
const violations=[],shapeUse={};
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
    if(st.skill?.id===11495){meteorCasts++;const c=(st.candidates||[]).find(x=>Number(x.id)===11495);
      if(c&&c.stand.x!==c.target.x&&c.stand.y!==c.target.y)meteorDiagonal++;}
    for(const c of (st.candidates||[])){
      if(!LINE.has(c.shape))continue;
      lineCandidates++;shapeUse[c.shape]=(shapeUse[c.shape]||0)+1;
      if(c.stand.x!==c.target.x&&c.stand.y!==c.target.y){
        diagonalViolations++;if(violations.length<4)violations.push({id:c.id,skill:c.skill,shape:c.shape,stand:c.stand,target:c.target});
      }
    }
  }
}
console.log(JSON.stringify({alerts,geometry,
  sweep:{done,err,ex:ex.slice(0,3),maxMs,lineCandidates,diagonalViolations,violations,
         meteorCasts,meteorDiagonal,shapeUse}}));
"""


def main():
    core = (ROOT / 'battle-sim-core.js').read_text('utf8')
    ui = (ROOT / 'battle-sim-ui.js').read_text('utf8')

    # ---- static ----------------------------------------------------------
    for k in ('RANGE_SELECT', 'castRangeOffsets', 'castRangeCells', 'castShape',
              'WHOLE_FIELD_SHAPES', 'damageSegmentsOf', 'linkedDamageFactors',
              'triggers: 1', 'segmentCount:', 'segmentDefs',
              '一段警戒造成 2 段伤害', 'range_select'):
        check(f'engine implements {k}', k in core)
    check('引擎按 target_select 而非 range_tag 取形状',
          "const shape = castShape(s);" in core and "cellRing(lo, hi, s.rt, s.legacy)" not in core)
    check('UI 不再生成 #/page/${u.pageId} 链接',
          'href="#/page/${u.pageId}"' not in ui and 'wikiPage > 0' in ui)
    for k in ('bsim-unit-page', 'bsim-unit-title', '一段警戒造成', 'segmentCount',
              'c.shape', 'step.moveRule.castShape'):
        check(f'UI exposes {k}', k in ui)

    out = subprocess.run([str(NODE), '-e', ENGINE], cwd=ROOT, capture_output=True,
                         text=True, encoding='utf8', timeout=900)
    try:
        e = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        e = {}
        print(out.stdout[-1200:], out.stderr[-1200:])

    alerts = e.get('alerts') or []
    anna = [a for a in alerts if a['hit']['owner'] == '安娜']
    hits = anna[0]['hit'] if anna else {}

    # ---- 1. 一段警戒造成 2 段伤害 -----------------------------------------
    check('1 · 安娜警戒有触发记录', bool(anna), str(len(alerts)))
    check('1 · 一次触发只消耗 1 次警戒次数',
          hits.get('triggers') == 1 and hits.get('points', 0) - hits.get('left', -1) == 1,
          str({k: hits.get(k) for k in ('triggers', 'points', 'left')}))
    check('1 · 明确区分「次数」与「伤害段」',
          hits.get('points') == 3 and hits.get('segmentCount') == 2
          and hits.get('hits') == 2, str({k: hits.get(k) for k in ('points', 'segmentCount', 'hits')}))
    segs = hits.get('segments') or []
    check('1 · 两段伤害都在一次警戒里登记',
          len(segs) == 2 and all(s.get('factor') == 35 and '段' in str(s.get('seg')) for s in segs),
          str(segs))
    check('1 · 一段警戒不打断行动',
          hits.get('forced') is False and hits.get('interrupts') is False)
    check('1 · 日志写明「一段警戒造成 2 段伤害」',
          any('一段警戒造成 2 段伤害' in ev for ev in (anna[0].get('events') if anna else [])),
          str(anna[0].get('events')[:3] if anna else ''))
    check('1 · 没有幻影第二次施放',
          not any('CloneCloneClone' in ev for a in alerts for ev in a['events']))

    # ---- 2. 客户端 range_select 技能范围 ---------------------------------
    g = e.get('geometry') or {}
    meteor = g.get('meteor') or {}
    check('2 · 贯穿天际的必胜流星是十字（直线）范围',
          meteor.get('n') == '贯穿天际的必胜流星' and meteor.get('shape') == 'cross_line'
          and meteor.get('ts') == 2, str(meteor))
    check('2 · 11495 射程 1-3 只有 12 个直线格、无斜角',
          meteor.get('cells') == 12 and meteor.get('diagonals') == 0, str(meteor))
    check('2 · 菱形范围仍含斜角（未被一刀切）',
          (g.get('diamond') or {}).get('shape') == 'diamond'
          and (g.get('diamond') or {}).get('diagonals', 0) > 0, str(g.get('diamond')))
    check('2 · 单向线 / 矩形等同样只能走直线',
          (g.get('direction') or {}).get('shape') == 'direction'
          and (g.get('direction') or {}).get('diagonals') == 0, str(g.get('direction')))
    check('2 · range_select 表覆盖 11 种形状', len(g.get('shapes') or {}) == 11,
          str(len(g.get('shapes') or {})))

    sw = e.get('sweep') or {}
    check('2 · 192 场全量无异常', sw.get('done') == 192 and sw.get('err') == 0, str(sw.get('ex')))
    check('2 · 全量有直线范围候选参与决策', (sw.get('lineCandidates') or 0) > 0,
          str(sw.get('shapeUse')))
    check('2 · 全量直线范围技能从不瞄斜角',
          sw.get('diagonalViolations') == 0 and sw.get('meteorDiagonal') == 0,
          str(sw.get('violations')))

    # ---- 3. 浏览器：右侧角色卡片不再跳 pages/0 ---------------------------
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
            page.wait_for_timeout(1200)
        bad = page.locator('#bsim-units a[href="#/page/0"], #bsim-units a[href="#/page/undefined"]').count()
        check('3 · 角色卡片无 #/page/0 / undefined 链接', bad == 0, str(bad))
        links = page.locator('#bsim-units a[href^="#/page/"]').all()
        hrefs = [a.get_attribute('href') for a in links]
        check('3 · 存在的角色页链接都指向有效词条',
              all(h and h != '#/page/0' and h.rsplit('/', 1)[-1].isdigit()
                  and int(h.rsplit('/', 1)[-1]) > 0 for h in hrefs), str(hrefs[:4]))
        titles = page.locator('#bsim-units .bsim-unit-title')
        check('3 · 角色名改为非链接文本', titles.count() >= 1, str(titles.count()))
        name = titles.first
        name.click()
        page.wait_for_timeout(400)
        check('3 · 点击名字不离开对局页',
              page.evaluate('location.hash') == '#/tools/battle',
              str(page.evaluate('location.hash')))
        check('3 · 点击名字改为打开角色面板',
              page.locator('#bsim-panel').inner_text().strip() != ''
              and page.locator('.bsim-unit.is-selected').count() >= 1)
        # The right-hand half of a card (HP / skills / passives) must not
        # navigate either — that was the reported pages/0 symptom.
        page.locator('#bsim-units .bsim-unit').nth(1).locator('.bsim-unit-hp').click()
        page.wait_for_timeout(250)
        check('3 · 点击卡片右侧同样不跳页',
              page.evaluate('location.hash') == '#/tools/battle',
              str(page.evaluate('location.hash')))
        panel = page.locator('#bsim-panel')
        if panel.locator('.bsim-attrs').count():
            panel.locator('.bsim-attrs').first.click()
            page.wait_for_timeout(200)
        check('3 · 点开的角色面板内部也不跳页',
              page.evaluate('location.hash') == '#/tools/battle',
              str(page.evaluate('location.hash')))
        # Roster units DO have a Wiki page: keep an explicit ↗ link that points
        # at the real page id (never 0), while the name itself stays a panel click.
        expected = page.evaluate("""() => {
          const r = window.WIKI_BATTLE_SIM.roster.find(x => Number(x.pageId) > 0);
          if (!r) return 0;
          localStorage.setItem('socwiki.battle.setup', JSON.stringify({A: [r.key], B: [r.key], mode: 'left'}));
          return Number(r.pageId);
        }""")
        if expected:
            page.reload()
            page.locator('#bsim-board svg').wait_for()
            page.wait_for_timeout(600)
            good = page.locator(f'#bsim-units a.bsim-unit-page[href="#/page/{expected}"]').count()
            check('3 · 有词条的角色保留指向真实词条的 ↗ 链接', good >= 1,
                  f'pageId={expected} links={good}')
            page.locator('#bsim-units .bsim-unit-title').first.click()
            page.wait_for_timeout(300)
            check('3 · 图鉴角色点名字同样只打开面板',
                  page.evaluate('location.hash') == '#/tools/battle',
                  str(page.evaluate('location.hash')))
        check('浏览器 · 无页面错误', not errors, '; '.join(errors[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
