"""Round 26: per-match map/spawns, WT speed, prewar provenance, SP科尔 mobility,
crit base, choice options, and the deep carried-skill search.

    python -X utf8 scripts/verify_round26.py
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
const arena=W.maps.find(m=>m.id===C.environment.mapId);
const team=id=>C.teams.find(t=>t.id===id);
const mem=t=>t.members.map(m=>({name:m.name,stats:m.stats,move:m.move,prof:m.prof,profName:m.profName,
  kit:m.kit,skills:m.skills,edited:false,npcId:m.npcId,star:m.star}));
const target=C.schedules.find(s=>[s.team1Id,s.team2Id].some(id=>(team(id)?.members||[]).some(m=>m.npcId===9027)));
const opts={data:D,mech:M,map:arena,teams:{A:mem(team(target.team1Id)),B:mem(team(target.team2Id))},
  seed:7,maxRounds:20,env:{weatherId:C.environment.weatherId}};
const r=S.simulate(opts);
const u=r.units.find(x=>x.name==='科尔'&&x.side==='B')||r.units.find(x=>x.name==='科尔');
const p=r.inspect(0,u.uid);
const get=k=>p.attrs.find(a=>a.key===k);
const spd=get('SPEED'),mob=get('MOBILITY'),cr=get('CRIT_RATIO'),cd=get('CRIT_DAMAGE');
// WT ordering: the first actor should have the LOWEST final WT among all alive units
const first=r.steps.find(s=>s.actor&&s.kind!=='start'&&s.kind!=='end');
const wtOf=(uid,seq)=>{const x=r.inspect(seq,uid);return x?x.attrs.find(a=>a.key==='SPEED').value:1e9;};
const firstSpd=wtOf(first.actor,first.seq);
const others=r.units.filter(x=>x.uid!==first.actor).map(x=>wtOf(x.uid,first.seq));
// custom spawns
const custom={A:[{x:1,y:9},{x:2,y:9}],B:[{x:15,y:1}]};
const rc=S.simulate({...opts,spawns:custom});
// determinism with inspect
const a=S.simulate(opts),b=S.simulate(opts);
for(let i=0;i<8;i++)a.inspect(i,a.units[i%a.units.length].uid);
const sig=x=>JSON.stringify(x.steps.map(s=>s.text+(s.events||[]).join('|')));
// crit formula base
const hitStep=r.steps.find(s=>(s.hits||[]).some(h=>h.calc?.some(c=>c.label==='暴击率')));
const critRow=hitStep?hitStep.hits.find(h=>h.calc?.some(c=>c.label==='暴击率')).calc.find(c=>c.label==='暴击率'):null;
const critDmgRow=hitStep?hitStep.hits.find(h=>h.calc?.some(c=>c.label==='暴击伤害')).calc.find(c=>c.label==='暴击伤害'):null;
// prewar provenance somewhere in the roster
let prewarCount=0,prewarSample=null;
for(const x of r.units){
 const q=r.inspect(0,x.uid);
 for(const at of q.attrs) if(at.prewarParts?.length){prewarCount++;if(!prewarSample)prewarSample=at.prewarParts[0];}
}
// choice options data
const allsk=[].concat(...C.teams.map(t=>t.members.map(m=>m.allSkills)));
const flat=[].concat(...allsk);
const roles={};for(const s of flat)roles[s.role]=(roles[s.role]||0)+1;
console.log(JSON.stringify({
 err:r.error||null,winner:r.winner,steps:r.steps.length,
 sp:{mob:mob.value,mobParts:mob.parts.length,spdValue:spd.value,spdLabel:spd.label,spdWt:spd.wt,
     spdParts:spd.parts.map(x=>({n:x.n,flat:x.flat,displayFlat:x.displayFlat,ok:x.ok})),
     crit:cr.value,critBase:cr.critBase,critDmg:cd.value,critDmgBase:cd.critBase,
     critConstant:cr.parts.some(x=>x.src==='constant'),panelCritBase:p.critBaseChance,panelCritDmg:p.critBaseDamage},
 spdOrder:{first:first.actor,firstSpd,maxOther:Math.max(...others),ok:firstSpd>=Math.max(...others)-0.01},
 spawns:rc.spawns,
 deterministic:sig(a)===sig(b),
 critFormula:critRow?{rate:critRow.value,note:critRow.note}:null,
 critDmgFormula:critDmgRow?{dmg:critDmgRow.value,note:critDmgRow.note}:null,
 prewarCount,prewarSample,
 roles,choiceTotal:C.teams.reduce((x,t)=>x+t.members.reduce((y,m)=>y+(m.kit.choice||[]).length,0),0),
 derivedTotal:C.teams.reduce((x,t)=>x+t.members.reduce((y,m)=>y+(m.kit.derived||[]).length,0),0),
 refFighters:C.teams.reduce((x,t)=>x+t.members.filter(m=>(m.referenceSlots||[]).length).length,0),
 maps:C.schedules.filter(s=>s.mapId).length,schedules:C.schedules.length,
 spawnEditable:C.spawnEditable,speedNote:C.speedNote,
 activeParams:C.teams.reduce((x,t)=>x+t.members.reduce((y,m)=>y+m.allSkills.filter(s=>s.activeParam).length,0),0),
}));
"""


def main():
    C = load('data/match-cup.js', 'WIKI_MATCH_CUP')
    M = load('data/battle-mech.js', 'WIKI_BATTLE_MECH')
    ui = (ROOT / 'battle-sim-ui.js').read_text('utf8')
    core = (ROOT / 'battle-sim-core.js').read_text('utf8')
    exp = (ROOT / 'scripts/extract_match_cup.py').read_text('utf8')
    mech_ids = {int(k) for k in M['skills']}

    # ---------- 1. map + editable spawns ----------
    check('every schedule records an inferred map',
          all(s.get('mapId') and s.get('mapName') and s.get('mapSource') for s in C['schedules']),
          f"{sum(1 for s in C['schedules'] if s.get('mapId'))}/{len(C['schedules'])}")
    check('every schedule records both formations',
          all(s.get('formation', {}).get('A') and s.get('formation', {}).get('B') for s in C['schedules']))
    check('client boundary documented (no per-match map / spawn)',
          '客户端赛程表无地图 id' in C['notes'][-2] or any('没有逐场战斗地图 id' in n for n in C['notes']))
    check('spawn editor wired', 'spawnEditable' in C and 'paintSpawnEditor' in ui and 'data-spawn-apply' in ui)
    check('engine validates custom spawns', 'customApplied' in core and 'opts.spawns' in core)

    # ---------- 2. WT speed ----------
    # Round 27: the client stores SPEED mods as wait-time deltas; the mech
    # exporter converts them to plain speed bonuses. Higher speed acts first.
    check('client speed semantics exported',
          '速度越大越先行动' in C.get('speedNote', '') and '+200' in C.get('speedNote', ''))
    check('mech exporter converts WT deltas to speed deltas',
          'converted' in M.get('speedConversion', {}) and M['speedConversion']['converted'] > 0,
          str(M.get('speedConversion')))
    check('turn order uses descending speed', 'b.spd - a.spd' in core and 'a.wt - b.wt' not in core)
    check('panel shows speed without WT wording', 'displayFlat' not in core and 'WT 行动等待' not in core)
    check('Lua wait_time stays inverse to speed', "wait_time: 10000 / Math.max(1, attr(u, 'SPEED'))" in core)

    # ---------- 3. prewar provenance ----------
    check('prewar detail recorded', 'u.prewarParts' in core and 'prewarParts' in core)
    check('prewar rows rendered in panel', 'prewarRow' in ui and '开局修正明细' in ui)

    # ---------- 4. activation conditions / SP科尔 ----------
    check('skill + buff activation params exported', 'ap' in core and "'ap'" in
          (ROOT / 'scripts/extract_battle_mechanics.py').read_text('utf8'))
    check('non-castable active skills only keep at=1 effects', 'timedActive' in core)
    # Round 52: the SMOG-only special case was replaced by the general rule —
    # every buff's active_param is evaluated LIVE (buffOn), so 10008's
    # 「移动力=0」 stays dormant until its holder actually stands on 烟雾.
    check('SMOG-gated cup buff documented',
          'function buffOn(b)' in core and "spec.t !== 'REMOVE'" in core)

    # ---------- 5. crit base ----------
    k = M['constants']
    check('client crit constants exported', k.get('CritBaseChance') == 10 and k.get('CritBaseDamage') == 30, str(k))
    check('panel shows crit base as a source', 'critBase' in core and '客户端常量' in ui)
    check('damage formula lists both crit bases', "CritBaseChance" in core and "CritBaseDamage" in core)

    # ---------- 6. choice options ----------
    allsk = [s for t in C['teams'] for m in t['members'] for s in m['allSkills']]
    roles = Counter(s['role'] for s in allsk)
    kits = [m['kit'] for t in C['teams'] for m in t['members']]
    check('choice options exported into kits', sum(len(k.get('choice', [])) for k in kits) >= 20,
          str(sum(len(k.get('choice', [])) for k in kits)))
    check('choice options appear in allSkills', roles.get('抉择选项', 0) >= 20, str(roles.get('抉择选项')))
    check('engine casts choice options', "kit.choice || []" in core and 'choiceIds' in core)
    check('choice options resolved in mechanics data',
          all(o in mech_ids for k in kits for o in k.get('choice', []) if o),
          str(len({o for k in kits for o in k.get('choice', [])})))

    # ---------- 7. deep carried-skill search ----------
    check('no tournament-specific carried skill table, documented',
          any('没有「赛事专属携带技能表」' in n for n in C['notes']))
    check('player-version phantom slots exported as reference only',
          any('referenceSlots' in n for n in C['notes']) and 'referenceSlots' in exp)
    check('effect-released skills parsed', sum(len(k.get('derived', [])) for k in kits) >= 300,
          str(sum(len(k.get('derived', [])) for k in kits)))
    check('activation conditions exported per skill', any(s.get('activeParam') for s in allsk),
          str(sum(1 for s in allsk if s.get('activeParam'))))
    check('derived skills compact (payload bounded)', (ROOT / 'data/match-cup.js').stat().st_size < 5_000_000,
          str(round((ROOT / 'data/match-cup.js').stat().st_size / 1024)) + ' KiB')

    # ---------- engine ----------
    out = subprocess.run([str(NODE), '-e', ENGINE], cwd=ROOT, capture_output=True, text=True,
                         encoding='utf8', timeout=600)
    try:
        e = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        e = {}
        print(out.stdout[-900:], out.stderr[-1200:])
    sp = e.get('sp', {})
    check('cup battle simulates', not e.get('err') and e.get('steps', 0) > 20)
    check('SP科尔 opening mobility restored', sp.get('mob') == 5, str(sp.get('mob')))
    check('speed label is plain 速度 and deltas are positive',
          sp.get('spdLabel') == '速度' and not sp.get('spdWt') and
          all(x.get('flat', 0) > 0 for x in sp.get('spdParts', []) if x.get('flat')),
          str(sp.get('spdParts')))
    check('first actor has the highest speed', e.get('spdOrder', {}).get('ok') is True, str(e.get('spdOrder')))
    check('crit panel values are the client bases', sp.get('crit') == 10 and sp.get('critDmg') == 30
          and sp.get('critBase') == 10 and sp.get('critDmgBase') == 30, str(sp))
    check('crit base listed as a source, not double-counted', sp.get('critConstant') is True)
    check('damage formula shows both crit bases',
          e.get('critFormula') and '10' in e['critFormula']['note'] and
          e.get('critDmgFormula') and '30' in e['critDmgFormula']['note'], str(e.get('critFormula')))
    check('prewar provenance available in panels', e.get('prewarCount', 0) >= 1, str(e.get('prewarSample'))[:160])
    check('custom spawns applied', e.get('spawns', {}).get('custom', 0) >= 1, str(e.get('spawns')))
    check('inspection remains deterministic', e.get('deterministic') is True)
    check('all 192 schedules have a map', e.get('maps') == e.get('schedules'), f"{e.get('maps')}/{e.get('schedules')}")

    # ---------- browser ----------
    errors, failed = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(offline=True, viewport={'width': 1600, 'height': 1000}).new_page()
        page.set_default_timeout(30000)
        page.on('pageerror', lambda x: errors.append(str(x)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))
        page.goto(BASE + '#/tools/battle')
        page.locator('#bsim-board svg').wait_for()
        page.evaluate("()=>{document.querySelector('.bsim-cup').open=true;}")
        page.wait_for_timeout(200)
        check('left setup column has its own scrollbar',
              page.evaluate("""()=>{const e=document.querySelector('.bsim-setup');
                return getComputedStyle(e).overflowY==='auto' && e.scrollHeight>e.clientHeight}"""))
        check('cup info shows this match map', '对战地图' in page.locator('#bsim-cup-info').inner_text())
        page.evaluate("()=>{document.querySelector('#bsim-spawn-edit').open=true;}")
        page.wait_for_timeout(200)
        check('spawn editor lists both formations', page.locator('.bsim-spawn-row').count() == 14,
              str(page.locator('.bsim-spawn-row').count()))
        check('spawn editor has a map selector', page.locator('#bsim-spawn-map').count() == 1)
        check('spawn rows use map-pick buttons, not numeric inputs',
              page.locator('[data-spawn-pick]').count() == 14 and
              page.locator('[data-spawn$=":x"]').count() == 0)
        page.locator('[data-spawn-pick="A:0"]').click()
        page.wait_for_timeout(150)
        check('pick mode shows a hint and arms the board',
              page.locator('.bsim-pick-hint').count() == 1 and
              'is-spawn-picking' in (page.locator('#bsim-board').get_attribute('class') or ''))
        cell = page.evaluate("""()=>{const c=document.querySelector('.bsim-cell[data-x="15"][data-y="1"]');
          return c?{x:c.dataset.x,y:c.dataset.y}:null}""")
        page.locator(f'.bsim-cell[data-x="{cell["x"]}"][data-y="{cell["y"]}"]').first.click()
        page.wait_for_timeout(400)
        check('clicking a map cell sets the coordinate',
              page.locator('.bsim-pick-hint').count() == 0 and
              '(15, 1)' in page.locator('.bsim-spawn-row').first.locator('.bsim-spawn-coord').inner_text(),
              page.locator('.bsim-spawn-row').first.locator('.bsim-spawn-coord').inner_text())
        check('board shows the spawn marker', page.locator('.bsim-spawn-mark').count() >= 1)
        page.locator('[data-spawn-apply]').click()
        page.wait_for_timeout(1800)
        check('applying a formation re-runs the battle', page.locator('.bsim-result').count() == 1)
        page.locator('[data-cup-load="both"]').click()
        page.wait_for_timeout(2000)
        page.locator('.bsim-unit[data-unit]').first.click()
        page.wait_for_timeout(300)
        check('panel hint explains speed conversion and crit bases',
              '取反' in page.locator('.bsim-panel-hint').inner_text() and
              '10%' in page.locator('.bsim-panel-hint').inner_text())
        speed = page.locator('.bsim-attr').filter(has_text='速度').first
        check('speed row uses plain 速度 label, no WT',
              speed.count() == 1 and 'WT' not in speed.locator('summary').inner_text(),
              speed.locator('summary').inner_text()[:60])
        speed.locator('summary').click()
        page.wait_for_timeout(120)
        check('speed deltas shown as plain positive bonuses',
              all('加速' not in x and 'WT' not in x for x in speed.locator('.bsim-part').all_inner_texts()),
              str(speed.locator('.bsim-part').all_inner_texts()[:2]))
        crit = page.locator('.bsim-attr').filter(has_text='暴击率').first
        check('crit row shows base 10', '10' in crit.locator('summary').inner_text(),
              crit.locator('summary').inner_text()[:60])
        critd = page.locator('.bsim-attr').filter(has_text='暴击伤害').first
        check('crit damage row shows base 30', '30' in critd.locator('summary').inner_text(),
              critd.locator('summary').inner_text()[:60])
        page.evaluate("()=>{document.querySelector('.bsim-cup-roster').open=true;}")
        page.wait_for_timeout(200)
        check('reference slots shown in roster', page.locator('.bsim-ref-slots').count() > 0)
        check('elite compensation documented and off by default',
              page.locator('.bsim-elite-note').count() == 1 and
              not page.locator('#bsim-elite-comp').is_checked())
        page.evaluate("()=>{document.querySelector('.bsim-elite-note').open=true;}")
        check('elite note explains source and evidence',
              'unit_personality_skill' in page.locator('.bsim-elite-note').inner_text() and
              '9686' in page.locator('.bsim-elite-note').inner_text())
        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
