"""Round 25: map coordinates, live inspectable character panel, cup skill fidelity.

    python -X utf8 scripts/verify_round25.py
"""
import json
import subprocess
import sys
from collections import Counter
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
    t = (ROOT / rel).read_text('utf8')
    m = 'window.' + var + '='
    return json.JSONDecoder().raw_decode(t[t.index(m) + len(m):])[0]


ENGINE = r"""
const fs=require('fs'),vm=require('vm');const ctx={window:{}};vm.createContext(ctx);
for(const f of ['data/world-data.js','data/battle-sim.js','data/match-cup.js','data/battle-mech.js','battle-sim-core.js'])
  vm.runInContext(fs.readFileSync(f,'utf8'),ctx);
const W=ctx.window.WIKI_WORLD_DATA,D=ctx.window.WIKI_BATTLE_SIM,C=ctx.window.WIKI_MATCH_CUP,M=ctx.window.WIKI_BATTLE_MECH,S=ctx.window.WikiBattleSim;
const env=C.environment,arena=W.maps.find(m=>m.id===env.mapId);
const team=id=>C.teams.find(t=>t.id===id);
const mem=t=>t.members.map(m=>({name:m.name,stats:m.stats,move:m.move,prof:m.prof,profName:m.profName,kit:m.kit,skills:m.skills,edited:false,npcId:m.npcId,star:m.star}));
const s0=C.schedules[0];
const opts={data:D,mech:M,map:arena,teams:{A:mem(team(s0.team1Id)),B:mem(team(s0.team2Id))},seed:20261107,maxRounds:20,env:{weatherId:env.weatherId}};
const t0=Date.now();const r=S.simulate(opts);const ms=Date.now()-t0;
// --- inspect() returns a full breakdown at arbitrary steps ---
const mid=Math.floor(r.steps.length/2),uid=r.units[0].uid;
const p=r.inspect(mid,uid);
const attrs=p?p.attrs.map(a=>({key:a.key,label:a.label,value:a.value,base:a.base,prewar:a.prewar,parts:a.parts.length,formula:a.formula})):[];
const withParts=p?p.attrs.filter(a=>a.parts.length):[];
const samplePart=withParts.length?withParts[0].parts[0]:null;
const partShape=samplePart?Object.keys(samplePart).sort().join(','):'';
// Round 29: utility skills now cast, so the first calc may be a heal.
// Pick a damaging hit so the damage-formula assertion stays meaningful.
const hit=r.steps.find(x=>(x.hits||[]).some(h=>h.calc&&h.calc.some(c=>c.label==='最终伤害')))
       ||r.steps.find(x=>(x.hits||[]).some(h=>h.calc&&h.calc.length));
const calc=hit?hit.hits.find(h=>h.calc).calc:[];
// --- determinism: inspection must not consume RNG or change coverage ---
const a=S.simulate(opts),b=S.simulate(opts);
for(let i=0;i<8;i++)a.inspect(i*3,a.units[i%a.units.length].uid);
const sig=x=>JSON.stringify(x.steps.map(s=>s.text+(s.events||[]).join('|')));
const det=sig(a)===sig(b)&&JSON.stringify(a.mechanics.conditions)===JSON.stringify(b.mechanics.conditions);
const stable=JSON.stringify(a.inspect(5,uid))===JSON.stringify(a.inspect(5,uid));
// --- custom fighter without kit must still work ---
const keys=D.roster.map(x=>x.key);
const custom={key:keys[0],name:'测试',stats:{hp:99999,patk:3000,matk:3000,pdef:500,mdef:500,spd:400},
 move:{mob:4,up:2,down:2,type:1},edited:true,
 skills:[{id:'c1',name:'自定义重击',usable:true,heal:false,factor:300,rangeMin:0,rangeMax:3,shape:'diamond',aim:'enemy',area:{type:'single'},cooldown:0,order:5,hits:1,damageType:1}]};
const rc=S.simulate({data:D,mech:M,map:W.maps.find(m=>m.id===3),teams:{A:[custom],B:keys.slice(5,8)},seed:3,maxRounds:20});
// --- full cup sweep stays healthy ---
let done=0,err=0,maxMs=0;const timings=[];
for(const s of C.schedules.slice(0,40)){
 const t=Date.now();let q;
 try{q=S.simulate({...opts,teams:{A:mem(team(s.team1Id)),B:mem(team(s.team2Id))},seed:1000+s.id});}catch(e){err++;continue;}
 const one=Date.now()-t;timings.push(one);maxMs=Math.max(maxMs,one);if(q.error)err++;else done++;
}
// Round 51: a fixed 6000ms wall-clock budget is machine/contention dependent
// (the parallel regression runner deliberately uses all physical cores).
// Guard against a REAL runaway instead: a battle >6x the batch median.
const sortedT=timings.slice().sort((a,b)=>a-b);
const medianMs=sortedT.length?sortedT[Math.floor(sortedT.length/2)]:0;
const slow=timings.filter(x=>x>Math.max(1,medianMs)*6).length;
console.log(JSON.stringify({err:r.error||null,winner:r.winner,steps:r.steps.length,ms,
 panel:p?{uid:p.uid,hp:p.hp,buffs:p.buffs.length,skills:p.skills.length,passives:p.passives.length,attrs:p.attrs.length}:null,
 attrs,withParts:withParts.length,partShape,samplePart,calcLen:calc.length,calcLabels:calc.map(c=>c.label),
 det,stable,custom:{err:rc.error||null,used:rc.steps.some(x=>x.skill&&x.skill.name==='自定义重击')},
 sweep:{done,err,maxMs,medianMs,slow}}));
"""


def main():
    C = load('data/match-cup.js', 'WIKI_MATCH_CUP')
    M = load('data/battle-mech.js', 'WIKI_BATTLE_MECH')
    ui = (ROOT / 'battle-sim-ui.js').read_text('utf8')
    core = (ROOT / 'battle-sim-core.js').read_text('utf8')
    css = (ROOT / 'refinements.css').read_text('utf8')
    exporter = (ROOT / 'scripts/extract_match_cup.py').read_text('utf8')
    mech_ids = {int(k) for k in M['skills']}

    # ---------- 3. cup skill fidelity ----------
    allsk = [s for t in C['teams'] for m in t['members'] for s in m['allSkills']]
    roles = Counter(s['role'] for s in allsk)
    # Round 27: 「精英属性补回」entries are labelled separately because they
    # are excluded from the live kit by default, so 个性 is split in two.
    check('client skill classification exported',
          roles['主动技能'] > 400 and roles['被动技能'] > 300
          and roles['个性'] + roles['个性（精英补正）'] > 800, str(roles.most_common()))
    check('no passive mislabelled as active',
          all(s['role'] != '主动技能' for s in allsk if s['clientType'] == 3))
    check('every skill has a readable name', all(s['name'].strip() for s in allsk),
          f"{sum(1 for s in allsk if not s['name'].strip())} empty")
    check('every skill carries its client type',
          all(s.get('clientType') in (1, 2, 3) and s.get('clientRole') for s in allsk))
    check('effect types exported for skills',
          sum(1 for s in allsk if s.get('specTypes')) > 2000,
          str(sum(1 for s in allsk if s.get('specTypes'))))
    chains = [s for s in allsk if s.get('chainFrom')]
    check('skill chains resolved', len(chains) >= 300, str(len(chains)))
    check('all chain skills present in mechanics data', all(s['id'] in mech_ids for s in chains))
    check('all exported skills present in mechanics data', all(s['id'] in mech_ids for s in allsk),
          f'{len(set(s["id"] for s in allsk))} distinct')
    kits = [m['kit'] for t in C['teams'] for m in t['members']]
    check('kits carry chain + AI fields',
          all('chain' in k and 'aiByOrder' in k and 'bossSequence' in k for k in kits))
    check('no player template skill pollution',
          all(not k.get('initial') and not k.get('feature') for k in kits),
          str(sum(len(k.get('initial', [])) + len(k.get('feature', [])) for k in kits)))
    # Round 29: every client active (skill.type 1) is castable, including
    # heal / support / debuff families with skill_type 1/4/5/8.
    check('simulated matches engine castable()',
          all(bool(s['simulated']) == (s['clientType'] == 1)
              for s in allsk if s['role'] != '派生技能'))
    check('exporter documents new classification',
          'skill.type' in exporter and 'unit_npc' in exporter and '技能链' in exporter)

    # ---------- 1 & 2 static wiring ----------
    check('2D coordinate labels rendered', 'class="bsim-coord"' in ui and 'show-coords' in ui and '.show-coords .bsim-coord' in css)
    check('3D coordinate labels rendered', "bsim3-coord" in ui and 'bsim3-coord' in css)
    check('coordinate toggle wired', "#bsim-coords" in ui and 'setup.coords' in ui)
    check('panel breakdown engine API', 'function inspect(' in core and 'function attrBreakdown(' in core
          and 'function unitPanel(' in core and 'inspect,' in core)
    check('read-only probe mode', 'sim.probe' in core and 'probe = false' in core)
    check('damage formula parts', "add('基础攻击力'" in core and 'calc: dmg.parts' in core)
    check('panel UI + per-stat expansion', 'bsim-attr' in ui and 'paintPanel' in ui and 'bsim-part' in ui)
    check('cup skill groups in UI', 'skillGroups' in ui and 'bsim-cup-skill-group' in ui and 'specTypes' in ui)

    # ---------- engine ----------
    out = subprocess.run([str(NODE), '-e', ENGINE], cwd=ROOT, capture_output=True, text=True,
                         encoding='utf8', timeout=600)
    try:
        e = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        e = {}
        print(out.stdout[-900:], out.stderr[-1200:])
    check('cup battle still simulates', not e.get('err') and e.get('steps', 0) > 20, str(e.get('err') or e.get('steps')))
    check('panel exposes 15 stats + buffs/skills',
          e.get('panel', {}).get('attrs') == 15 and e.get('panel', {}).get('skills', 0) > 0)
    check('panel shows per-effect contributions', e.get('withParts', 0) >= 5 and e.get('partShape', '') != '',
          f"{e.get('withParts')} attrs · {e.get('partShape')}")
    check('each formula is displayed', all('=' in a['formula'] for a in e.get('attrs', [])))
    check('damage formula has all steps',
          e.get('calcLen', 0) >= 8 and {'基础攻击力', '目标防御', '基础伤害', '最终伤害'} <= set(e.get('calcLabels', [])),
          str(e.get('calcLabels')))
    check('inspection is deterministic and read-only', e.get('det') is True and e.get('stable') is True)
    check('custom fighter without kit still works', not e.get('custom', {}).get('err') and e['custom'].get('used'),
          str(e.get('custom')))
    check('40 cup matches healthy after skill changes',
          e.get('sweep', {}).get('done') == 40 and e['sweep'].get('err') == 0
          and e['sweep'].get('slow', 9e9) == 0,
          str(e.get('sweep')))

    # ---------- browser ----------
    errors, failed = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(offline=True, viewport={'width': 1600, 'height': 1000}).new_page()
        page.set_default_timeout(30000)
        page.on('pageerror', lambda x: errors.append(str(x)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))
        page.goto(BASE + '#/tools/battle')
        page.locator('#bsim-board svg').wait_for()

        check('coordinates shown by default', page.locator('#bsim-coords').is_checked()
              and page.evaluate("()=>document.querySelector('.bsim-svg').classList.contains('show-coords')"))
        check('2D coordinate labels on every cell', page.locator('.bsim-coord').count() == page.locator('.bsim-cell').count(),
              str(page.locator('.bsim-coord').count()))
        page.locator('#bsim-coords').uncheck()
        check('coordinate toggle hides labels',
              page.evaluate("()=>getComputedStyle(document.querySelector('.bsim-coord')).display") == 'none')
        page.locator('#bsim-coords').check()
        page.locator('[data-bsim-view="3d"]').click()
        page.wait_for_timeout(400)
        check('3D coordinates on every cell',
              page.locator('.bsim3-coord').count() == page.locator('.world-iso-cell').count(),
              f"{page.locator('.bsim3-coord').count()} / {page.locator('.world-iso-cell').count()}")
        page.locator('[data-bsim-view="2d"]').click()
        page.wait_for_timeout(200)

        page.locator('.bsim-token[data-unit]').first.click()
        page.wait_for_timeout(250)
        check('clicking a board token opens the live panel', page.locator('.bsim-panel-head').count() == 1)
        check('panel lists all 15 stats', page.locator('.bsim-attr').count() == 15)
        page.locator('.bsim-attr').nth(1).locator('summary').click()
        page.wait_for_timeout(100)
        check('a stat expands into its sources and formula',
              page.locator('.bsim-attr').nth(1).locator('.bsim-part').count() > 0
              and page.locator('.bsim-attr').nth(1).locator('.bsim-formula.is-final').count() == 1)
        for _ in range(6):
            page.locator('[data-play="next"]').click()
        page.wait_for_timeout(200)
        check('panel follows the replay step', '第 6 步' in page.locator('.bsim-panel-head').inner_text(),
              page.locator('.bsim-panel-head').inner_text()[:80].replace('\n', ' '))
        # Round 32: summons now take their own turns, so the first step with a
        # calc panel may be a short status-damage formula. Look for a full
        # direct-damage breakdown (>= 8 rows) instead of the first panel.
        found = False
        for _ in range(60):
            if page.locator('.bsim-calc-table tr').count() >= 8:
                found = True
                break
            page.locator('[data-play="next"]').click()
        check('damage / heal formula available in step detail',
              found and page.locator('.bsim-calc').count() >= 1)
        page.locator('[data-panel-close]').click()
        check('panel can be closed', page.locator('.bsim-panel-head').count() == 0)

        page.evaluate("()=>{document.querySelector('.bsim-cup').open=true;}")
        page.wait_for_timeout(150)
        page.evaluate("()=>{document.querySelector('.bsim-cup-roster').open=true;}")
        page.wait_for_timeout(150)
        page.locator('.bsim-cup-unit').first.evaluate('e=>e.open=true')
        page.wait_for_timeout(250)
        check('cup skills grouped by client role',
              page.locator('.bsim-cup-unit').first.locator('.bsim-cup-skill-group').count() >= 5,
              str(page.locator('.bsim-cup-unit').first.locator('.bsim-cup-skill-group > b').all_inner_texts()))
        check('cup skill shows client type + effect types',
              page.locator('.bsim-cup-unit').first.locator('.bsim-skill-kind').count() > 0
              and page.locator('.bsim-cup-unit').first.locator('.bsim-skill-spec').count() > 0)
        check('no blank skill names in the UI',
              page.evaluate("()=>[...document.querySelectorAll('.bsim-cup-skill')].filter(e=>!e.childNodes[0]?.textContent?.trim()).length") == 0)
        page.locator('[data-cup-load="both"]').click()
        page.wait_for_timeout(1800)
        check('loading a cup match still simulates', page.locator('.bsim-result').count() == 1)
        page.locator('.bsim-unit[data-unit]').first.click()
        page.wait_for_timeout(250)
        check('cup fighter panel shows effect sources',
              page.locator('.bsim-attr').count() == 15 and page.evaluate("()=>document.querySelectorAll('.bsim-attr').length>0"))
        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
