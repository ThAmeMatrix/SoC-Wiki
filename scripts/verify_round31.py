"""Round 31: interactive objects (props / traps / widgets), spawn plan
import/export, and full client effect-type coverage.

    python -X utf8 scripts/verify_round31.py
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


def load(rel, var):
    t = (ROOT / rel).read_text('utf8'); m = 'window.' + var + '='
    return json.JSONDecoder().raw_decode(t[t.index(m) + len(m):])[0]


ENGINE = r"""
const fs=require('fs'),vm=require('vm');const ctx={window:{}};vm.createContext(ctx);
for(const f of ['data/world-data.js','data/battle-sim.js','data/match-cup.js','data/battle-mech.js','data/client-mechanisms.js','battle-sim-core.js'])
  vm.runInContext(fs.readFileSync(f,'utf8'),ctx);
const W=ctx.window.WIKI_WORLD_DATA,D=ctx.window.WIKI_BATTLE_SIM,C=ctx.window.WIKI_MATCH_CUP,
      M=ctx.window.WIKI_BATTLE_MECH,SUB=ctx.window.WIKI_CLIENT_MECHANISMS,S=ctx.window.WikiBattleSim;
const arena=W.maps.find(m=>m.id===C.environment.mapId);
const team=id=>C.teams.find(t=>t.id===id);
const mk=m=>({name:m.name,stats:m.stats,move:m.move,prof:m.prof,profName:m.profName,
  kit:m.kit,skills:m.skills,edited:false,npcId:m.npcId,star:m.star});
const mem=t=>t.members.map(mk);
// ---- object definitions from props / trap / widget tables ----
const defs={props:Object.keys(M.props||{}).length,traps:Object.keys(M.traps||{}).length,
            widgets:Object.keys(M.widgets||{}).length,
            snowman:M.props?.[516]||null,honey:M.traps?.[153]||null,ice:M.traps?.[151]||null};
// ---- 乌莉娅 object lifecycle ----
let ulia,filler;
for(const t of C.teams)for(const m of t.members){if(!ulia&&m.name.includes('乌莉娅'))ulia=m;if(!filler&&m.name.includes('柯瓦雷'))filler=m;}
const f=mk(filler);
const r=S.simulate({data:D,mech:M,map:arena,teams:{A:[mk(ulia),f,f,f],B:[f,f,f,f]},
  seed:7,maxRounds:20,substrate:SUB});
const ever=new Map();
for(const s of r.steps)for(const o of s.placed||[])ever.set(o.kind+':'+o.id+':'+o.x+','+o.y,o);
const events=r.steps.flatMap(s=>s.events||[]);
const snowPlaced=events.filter(e=>/放置「呆呆雪人」/.test(e)).length;
const honeyPlaced=events.filter(e=>/放置「.*蜜果/.test(e)).length;
const icePlaced=events.filter(e=>/放置「碎冰」/.test(e)).length;
const destroyed=events.filter(e=>/呆呆雪人」被/.test(e)).length;
const pickups=events.filter(e=>/停留触发|途经触发/.test(e)).length;
const snowStep=r.steps.find(s=>(s.placed||[]).some(o=>o.id===516));
const snowObj=snowStep?.placed.find(o=>o.id===516);
// ---- Lua table with bracketed keys now parses ----
let badLua=0;for(const s of Object.values(M.specs)){if(!s.c)continue;const rr=S.Lua.test(s.c,{});
  if(rr.unknown&&/^(syntax|statement|token)/.test(rr.unknown))badLua++;}
// ---- 40-schedule sweep ----
let done=0,err=0,exceptions=[];const skipped={},exec={};let objects=0,placedSteps=0,allPickups=0;
for(const s of C.schedules.slice(0,40)){
  const buffs=s.buffDetails.map(b=>({buffId:b.buffId,side:b.target===1?'A':b.target===2?'B':'both'}));
  let q;try{q=S.simulate({data:D,mech:M,map:arena,teams:{A:mem(team(s.team1Id)),B:mem(team(s.team2Id))},
    seed:1000+s.id,maxRounds:20,env:{weatherId:C.environment.weatherId,buffs},substrate:SUB});}
  catch(e){err++;exceptions.push(s.id+':'+e.message);continue;}
  if(q.error){err++;continue;}
  done++;objects+=q.placed.length;
  placedSteps+=q.steps.filter(x=>x.placed?.length).length;
  allPickups+=q.steps.flatMap(x=>x.events||[]).filter(e=>/停留触发|途经触发/.test(e)).length;
  for(const [k,v] of Object.entries(q.mechanics.skipped||{}))skipped[k]=(skipped[k]||0)+v;
  for(const [k,v] of Object.entries(q.mechanics.executed||{}))exec[k]=(exec[k]||0)+v;
}
// determinism
const a=S.simulate({data:D,mech:M,map:arena,teams:{A:[mk(ulia),f,f,f],B:[f,f,f,f]},seed:7,maxRounds:20,substrate:SUB});
const b=S.simulate({data:D,mech:M,map:arena,teams:{A:[mk(ulia),f,f,f],B:[f,f,f,f]},seed:7,maxRounds:20,substrate:SUB});
const sig=x=>JSON.stringify(x.steps.map(s=>s.text+(s.events||[]).join('|')));
console.log(JSON.stringify({
 err:r.error||null,steps:r.steps.length,defs,
 lifecycle:{snowPlaced,honeyPlaced,icePlaced,destroyed,pickups,snowObj,
   kinds:[...new Set([...ever.values()].map(o=>o.id))],
   objectEffects:Object.fromEntries(['PLACE_ITEM','PLACE_TRAP','REMOVE_PROPS','TRIGGER_TRAP'].map(k=>[k,r.mechanics.executed[k]||0]))},
 badLua,
 sweep:{done,err,exceptions:exceptions.slice(0,3),objects,placedSteps,allPickups,
   skippedTotal:Object.values(skipped).reduce((x,y)=>x+y,0),
   topSkipped:Object.entries(skipped).sort((x,y)=>y[1]-x[1]).slice(0,5),
   objectEffects:Object.fromEntries(['PLACE_ITEM','PLACE_TRAP','REMOVE_PROPS','TRIGGER_TRAP'].map(k=>[k,exec[k]||0]))},
 deterministic:sig(a)===sig(b),
}));
"""


def main():
    M = load('data/battle-mech.js', 'WIKI_BATTLE_MECH')
    core = (ROOT / 'battle-sim-core.js').read_text('utf8')
    ui = (ROOT / 'battle-sim-ui.js').read_text('utf8')
    exporter = (ROOT / 'scripts/extract_battle_mechanics.py').read_text('utf8')

    # 1. object data
    check('props exported', len(M.get('props', {})) > 500, str(len(M.get('props', {}))))
    check('traps exported', len(M.get('traps', {})) > 150, str(len(M.get('traps', {}))))
    check('widgets exported', len(M.get('widgets', {})) > 40, str(len(M.get('widgets', {}))))
    p516 = M['props']['516']
    check('snowman definition complete', p516['n'] == '呆呆雪人' and p516['hp'] == 300
          and p516['atk'] and p516['col'] and p516['mov'] and len(p516['sp']) >= 10, str(p516)[:200])
    check('honey trap = 停留触发', M['traps']['153']['tt'] == 2 and M['traps']['153']['ts'] == 19218)
    check('ice trap = 停留触发', M['traps']['151']['tt'] == 2 and M['traps']['151']['ts'] == 18972)
    check('trigger type labels exported', M['trapTriggers'].get('1') == 'Pass' and M['trapTriggers'].get('2') == 'Stay')
    check('skill follow chains exported', any(s.get('fl') for s in M['skills'].values()))
    check('object effects seeded into closure', '19258' in M['skills'] and '24996' in M['specs'])

    # 2. engine object system
    for key in ('objectDef', 'fireObject', 'destroyObject', 'damageObject', 'triggerObject',
                'triggersOnPath', 'objectHp'):
        check(f'engine helper {key}', ('const ' + key + ' =') in core or ('function ' + key + '(') in core)
    for key in ('REMOVE_PROPS', 'TRIGGER_TRAP', 'CHANGE_TRAP', 'ACTIVATION',
                'STATUS_SKILL_TO_PROPS', 'WIDGET_SWITCH'):
        check(f'object handler {key}', f'{key}(inst' in core)
    check('props are attackable targets', 'primaryProp' in core and 'propSkill' in core)
    check('traps trigger on movement', 'triggersOnPath(step.path' in core)
    check('object timings wired', 'fireObject(25' in core and 'fireObject(29' in core)
    check('friendly damage reduction', 'reduction = friendly' in core)
    check('collidable objects block movement', 'o.collidable) occ.set' in core)
    check('Lua bracketed table keys', "'computed'" in core and 'hasKeys' in core)
    check('exporter seeds object specs', 'props.values()' in exporter and "'fl':" in exporter)

    # 3. full client effect-type coverage
    cfg = ROOT / 'output/archive/library/当前版本/配置表'
    st = json.loads(next(cfg.rglob('speciality_type.json')).read_text('utf8'))
    all_types = {r['type'] for r in st if r.get('type')}
    import re
    i = core.index('    const EFFECTS = {'); j = core.index('\n    };', i)
    handlers = set(re.findall(r'^      ([A-Z_]+)\s*\(', core[i:j], re.M))
    si = core.index('const STATIC_TYPES')
    static = set(re.findall(r"'([A-Z_]+)'", core[si:core.index(']);', si)]))
    missing = sorted(all_types - handlers - static)
    check('all client effect types handled', not missing, f'{len(all_types)} types, missing={missing[:6]}')

    # 4. spawn plan import/export
    for key in ('PLAN_FORMAT', 'buildPlan', 'validCell', 'applyPlan', 'data-plan="export"',
                'data-plan="export-all"', 'data-plan="import"', 'data-plan="copy"',
                'bsim-plan-file'):
        check(f'plan feature {key}', key in ui)
    check('plan validates walkable cells', 'validCell(mapId' in ui and '坐标重复' in ui)

    # 5. UI object rendering
    for key in ('objectLook', 'OBJECT_IDS', 'is-honey', 'is-ice', 'bsim-obj-hp',
                'bsim-object-grid', 'bsim3-placed'):
        check(f'UI object {key}', key in ui or key in (ROOT / 'refinements.css').read_text('utf8'))

    out = subprocess.run([str(NODE), '-e', ENGINE], cwd=ROOT, capture_output=True,
                         text=True, encoding='utf8', timeout=900)
    try:
        e = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        e = {}
        print(out.stdout[-1200:], out.stderr[-1500:])
    check('ulia battle simulates', not e.get('err') and e.get('steps', 0) > 20, str(e.get('err')))
    lc = e.get('lifecycle', {})
    check('snowman placed', lc.get('snowPlaced', 0) > 0, str(lc.get('snowPlaced')))
    check('two interactive items generated', lc.get('honeyPlaced', 0) > 0 and lc.get('icePlaced', 0) > 0,
          f"蜜果 {lc.get('honeyPlaced')} / 碎冰 {lc.get('icePlaced')}")
    check('snowman destroyed by 乌莉娅 basic', lc.get('destroyed', 0) > 0, str(lc.get('destroyed')))
    check('snowman has HP + attackable flag', (lc.get('snowObj') or {}).get('maxHp', 0) > 300
          and (lc.get('snowObj') or {}).get('attackable') is True, str(lc.get('snowObj'))[:220])
    check('object types include both pickups', {151, 153, 516} <= set(lc.get('kinds', [])),
          str(lc.get('kinds')))
    check('object effects fire', sum(lc.get('objectEffects', {}).values()) > 10, str(lc.get('objectEffects')))
    check('all Lua conditions parse', e.get('badLua') == 0, str(e.get('badLua')))
    sw = e.get('sweep', {})
    check('40 cup matches clean', sw.get('done') == 40 and sw.get('err') == 0, str(sw.get('exceptions')))
    check('objects visible across many steps', sw.get('placedSteps', 0) > 500, str(sw.get('placedSteps')))
    check('trap pickups fire at scale', sw.get('allPickups', 0) > 10, str(sw.get('allPickups')))
    check('deterministic', e.get('deterministic') is True)

    # browser
    errors, failed = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(offline=True, viewport={'width': 1600, 'height': 1000},
                                  accept_downloads=True)
        page = ctx.new_page()
        page.set_default_timeout(30000)
        page.on('pageerror', lambda x: errors.append(str(x)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))
        page.goto(BASE + '#/tools/battle')
        page.locator('#bsim-board svg').wait_for()
        page.evaluate("()=>{document.querySelector('.bsim-cup').open=true;}")
        page.evaluate("()=>{document.querySelector('#bsim-spawn-edit').open=true;}")
        page.wait_for_timeout(250)
        check('plan buttons present', page.locator('[data-plan]').count() == 4)
        with page.expect_download() as dl:
            page.locator('[data-plan="export"]').click()
        tmp = ROOT / 'work_r31_plan_verify.json'
        dl.value.save_as(str(tmp))
        doc = json.loads(tmp.read_text('utf8'))
        check('exported plan format', doc.get('format') == 'socwiki-spawn-plan' and len(doc['plans']) == 1,
              str(doc.get('format')))
        # pick a cell, re-export, then import back
        page.locator('[data-spawn-pick="A:0"]').click()
        page.wait_for_timeout(120)
        page.locator('.bsim-cell[data-x="15"][data-y="1"]').first.click()
        page.wait_for_timeout(300)
        with page.expect_download() as dl2:
            page.locator('[data-plan="export"]').click()
        dl2.value.save_as(str(tmp))
        doc2 = json.loads(tmp.read_text('utf8'))
        check('exported coordinate', doc2['plans'][0]['A'][0] == {'x': 15, 'y': 1}, str(doc2['plans'][0]['A'][:1]))
        page.locator('#bsim-plan-file').set_input_files(str(tmp))
        page.wait_for_timeout(350)
        check('import applied', '已导入' in page.locator('#bsim-plan-msg').inner_text(),
              page.locator('#bsim-plan-msg').inner_text())
        tmp2 = ROOT / 'work_r31_bad_verify.json'
        tmp2.write_text('{"format":"other","plans":[]}', 'utf8')
        page.locator('#bsim-plan-file').set_input_files(str(tmp2))
        page.wait_for_timeout(250)
        check('invalid plan rejected', '导入失败' in page.locator('#bsim-plan-msg').inner_text())
        # object rendering
        sid = page.evaluate("""()=>{const C=window.WIKI_MATCH_CUP;
          const t=C.teams.find(t=>t.members.some(m=>m.name.includes('乌莉娅')));
          const s=C.schedules.find(s=>s.team1Id===t.id||s.team2Id===t.id);return String(s.id);}""")
        page.locator('#bsim-cup-sched').select_option(sid)
        page.locator('[data-cup-load="both"]').click()
        page.wait_for_timeout(1700)
        classes = set()
        last = int(page.locator('#bsim-range').get_attribute('max') or 0)
        for k in range(0, min(last, 28)):
            page.evaluate("(i)=>{const r=document.querySelector('#bsim-range');r.value=String(i);r.dispatchEvent(new Event('input',{bubbles:true}));}", k)
            page.wait_for_timeout(35)
            classes.update(page.evaluate("()=>[...document.querySelectorAll('.bsim-placed')].map(e=>e.className.baseVal||e.getAttribute('class'))"))
        check('distinct object classes drawn', any('is-honey' in c for c in classes)
              and any('is-ice' in c for c in classes) and any('is-snowman' in c for c in classes),
              str(sorted(classes)[:4]))
        check('object detail panel', page.locator('.bsim-object-row').count() > 0)
        page.locator('[data-bsim-view="3d"]').click()
        page.wait_for_timeout(450)
        check('3D objects drawn', page.locator('.bsim3-placed').count() > 0)
        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        tmp.unlink(missing_ok=True); tmp2.unlink(missing_ok=True)
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
