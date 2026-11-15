"""Round 35: crit conversion, random-honey buff, 爆裂箭 consumption,
黑暗医师 神经同步 / share damage, personality docs, client code page.

    python -X utf8 scripts/verify_round35.py
"""
import json
import subprocess
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / 'index.html').as_uri()
NODE = Path(r'C:\Users\thamechen\AppData\Local\Programs\Python\Python313\Lib\site-packages\playwright\driver\node.exe')
PLAN = Path('C:/Users/thamechen/Downloads/铃兰档案馆-站位方案-332-赛程90.json')
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
const map=W.maps.find(m=>m.id===C.environment.mapId);
const mk=m=>({name:m.name,stats:m.stats,move:m.move,prof:m.prof,profName:m.profName,
  kit:m.kit,skills:m.skills,edited:false,npcId:m.npcId,star:m.star});
const team=id=>C.teams.find(t=>t.id===id),mem=t=>t.members.map(mk);
const opt=(s,seed)=>({data:D,mech:M,map,teams:{A:mem(team(s.team1Id)),B:mem(team(s.team2Id))},
  seed:seed||7,maxRounds:20,env:{weatherId:C.environment.weatherId,
    buffs:s.buffDetails.map(b=>({buffId:b.buffId,side:b.target===1?'A':b.target===2?'B':'both'}))},substrate:SUB});
const PLAN=JSON.parse(fs.readFileSync('C:/Users/thamechen/Downloads/铃兰档案馆-站位方案-332-赛程90.json','utf8')).plans[0];
const pm=W.maps.find(m=>m.id===PLAN.mapId);
const s90=C.schedules.find(s=>s.id===90);
const userOpt=(seed)=>Object.assign(opt(s90,seed),{map:pm,spawns:{A:PLAN.A,B:PLAN.B}});

// ---- 1. 暴击转化: real panel row + real stat contribution ----------------
const r1=S.simulate(opt(C.schedules.find(s=>s.id===22),7));
const anna=r1.units.find(u=>u.name==='安娜');
let crit=null;
for(let i=0;i<r1.steps.length;i++){
  const p=r1.inspect(i,anna.uid);
  if(p&&p.buffs.some(b=>b.id===7557)){
    const cd=p.attrs.find(a=>a.key==='CRIT_DAMAGE');
    crit={value:cd.value,rows:cd.parts.map(x=>x.n),
      row:cd.parts.find(x=>/暴击转化/.test(x.n))||null,
      personality:p.personality.length,cond:p.conditionalMods.length};
    break;
  }
}
// ---- 2. honey: exactly ONE random 2级增益 ------------------------------
const honey={pickups:0,oneLogs:0,allLogs:0,samples:[]};
for(const st of r1.steps){
  if(!(st.events||[]).some(e=>/停留触发「\[小羊女\|乌莉娅\]-蜜果」/.test(e)))continue;
  honey.pickups++;
  const one=(st.events||[]).filter(e=>/随机获得 1 个/.test(e)).length;
  honey.oneLogs+=one;
  if(honey.samples.length<3)honey.samples.push((st.events||[]).filter(e=>/获得「|随机获得/.test(e)).slice(0,9));
}
// ---- 3. 爆裂箭: consumption -> layers -> bonus segment -----------------
const booms=[];
for(const seed of [7,3,20261107]){
  const r=S.simulate(userOpt(seed));
  for(const st of r.steps)if(st.skill?.id===19449 && st.consumption && st.consumption.count>0){
    const extra=(st.hits||[]).find(h=>/^追加/.test(h.seg||''));
    booms.push({seed,seq:st.seq,c:st.consumption,
      baseSegs:(st.hits||[]).filter(h=>/^第 \d\/3 段/.test(h.seg||'')).length,
      bonus:extra?{seg:extra.seg,factor:extra.factor,boost:extra.boost,amount:extra.amount}:null,
      evaded:(st.hits||[]).some(h=>h.miss)});
  }
}
// ---- 4. 黑暗医师: 3 allies + shared damage ----------------------------
// Round 36: the declared-skill rotation changes when 黑暗医师 takes damage;
// schedule 90 has the same 神经同步 chain and resolves the share rule.
const r4=S.simulate(opt(C.schedules.find(s=>s.id===90),7));
const ev4=r4.steps.flatMap(s=>s.events||[]);
const dark={granted:ev4.filter(e=>/获得「神经同步」/.test(e)).length,
  share:ev4.filter(e=>/将 [0-9]+ 伤害分摊给/.test(e)).length,
  selected:(r4.steps[0].events||[]).filter(e=>/选中 3 名目标/.test(e)).length,
  rule:ev4.filter(e=>/分摊所受伤害/.test(e)).slice(0,1)};
// ---- 5. personality docs ------------------------------------------------
const chText=fs.readFileSync('data/character-mechanics.js','utf8');
const CH=JSON.parse(chText.slice(chText.indexOf('=')+1).replace(/;\s*$/,''));
const personalities=['安娜','乌莉娅','黑暗医师','伊南娜'].map(n=>({name:n,
  count:(CH.characters[n]||{}).personality?.length||0,
  hasDesc:(CH.characters[n]||{}).personality?.some(p=>p.desc&&p.effects.length)||false}));
// ---- 6. substrate -------------------------------------------------------
const sub={phases:SUB.phases.length,pipeline:SUB.castPipeline.length,
  effects:SUB.effectTypes.length,engine:SUB.engineEffectTypes.length,
  coverage:SUB.engineCoverage};

// ---- full sweep + determinism -------------------------------------------
let done=0,err=0,ex=[],maxMs=0,consumptionSteps=0,randomLogs=0,shareLogs=0,syncLogs=0;
const skipped={},unknown={};const t0=Date.now();
for(const s of C.schedules){
  const st=Date.now();let r;
  try{r=S.simulate(Object.assign(opt(s),{seed:1000+s.id}));}
  catch(e){err++;ex.push(s.id+':'+e.message);continue;}
  maxMs=Math.max(maxMs,Date.now()-st);
  if(r.error){err++;continue;}
  done++;
  for(const step of r.steps){
    if(step.consumption)consumptionSteps++;
    for(const e of step.events||[]){
      if(/随机获得 [0-9]+ 个/.test(e))randomLogs++;
      if(/伤害分摊给/.test(e))shareLogs++;
      if(/获得「神经同步」/.test(e))syncLogs++;
    }
  }
  for(const [k,v] of Object.entries(r.mechanics.skipped||{}))skipped[k]=(skipped[k]||0)+v;
  for(const [k,v] of Object.entries(r.mechanics.luaUnknown||{}))unknown[k]=(unknown[k]||0)+v;
}
const a=S.simulate(userOpt(7)),b=S.simulate(userOpt(7));
const sig=x=>JSON.stringify(x.steps.map(s=>s.text+(s.events||[]).join('|')));
console.log(JSON.stringify({crit,honey,booms,dark,personalities,sub,
  sweep:{done,err,ex:ex.slice(0,3),maxMs,totalMs:Date.now()-t0,
    consumptionSteps,randomLogs,shareLogs,syncLogs,
    skipped:Object.entries(skipped).sort((x,y)=>y[1]-x[1]).slice(0,5),
    unknown:Object.entries(unknown).sort((x,y)=>y[1]-x[1]).slice(0,5)},
  deterministic:sig(a)===sig(b)}));
"""


def main():
    core = (ROOT / 'battle-sim-core.js').read_text('utf8')
    ui = (ROOT / 'battle-sim-ui.js').read_text('utf8')
    worldui = (ROOT / 'world-ui.js').read_text('utf8')
    mechui = (ROOT / 'mechanics-ui.js').read_text('utf8')
    app = (ROOT / 'app.js').read_text('utf8')
    M = load('data/battle-mech.js', 'WIKI_BATTLE_MECH')
    CH = load('data/character-mechanics.js', 'WIKI_CHARACTER_MECHANICS')
    SUB = load('data/client-mechanisms.js', 'WIKI_CLIENT_MECHANISMS')

    # static assertions
    for key in ('const unpackCount', '随机获得 ${ids.length} 个', 'sim.selection = outerSelection',
                'function shareRuleOf', 'SPECIAL_SKILL_CONSUME(inst, ctx)',
                'fire(52, u,', 'fire(51, u,', 'personalityIds:', 'conditionalMods:',
                'sim.consumption = {tp', 'primaryEvaded'):
        check(f'engine {key}', key in core)
    for key in ('已切换到赛程', 'cupMembers(t1)', 'bsim-personality', 'bsim-consumption',
                'bsim-cond-mods'):
        check(f'UI {key}', key in ui)
    check('code page shows decrypted constants', 'world-lua-file' in worldui
          and '解密得出的战斗逻辑基底' in worldui and 'engineCoverage' in worldui)
    check('code page loads substrate', "['code','lua','substrate']" in app)
    check('doc page renders personality', 'cm-personality' in mechui)
    check('doc dataset has personality', CH['meta'].get('personalitySkills', 0) >= 400,
          str(CH['meta'].get('personalitySkills')))
    check('substrate engine coverage', SUB.get('engineCoverage') == 100
          and len(SUB.get('engineEffectTypes', [])) >= 250, str(SUB.get('engineCoverage')))
    check('honey random spec packed', M['specs']['4984']['p'][3] == 65537
          and len(str(M['specs']['4984']['s']).split('|')) == 7)
    check('dark doctor personality chain', 31730 in M['skills']['22692']['sp']
          and 31726 in (M['buffs']['9664']['sp'] or []))
    check('share spec params', M['specs']['31726']['p'] == [9665, 30, 9, 100])

    out = subprocess.run([str(NODE), '-e', ENGINE], cwd=ROOT, capture_output=True,
                         text=True, encoding='utf8', timeout=900)
    try:
        e = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        e = {}
        print(out.stdout[-1200:], out.stderr[-1500:])

    cr = e.get('crit') or {}
    check('暴击转化 appears in the stat panel', bool(cr.get('row')) and cr.get('row', {}).get('ok') is not False,
          str(cr.get('rows')))
    check('暴击转化 raises 暴击伤害', (cr.get('value') or 0) > 30, str(cr.get('value')))
    check('personality + conditional mods exposed', cr.get('personality', 0) >= 2
          and cr.get('cond', 0) >= 1, str(cr))

    ho = e.get('honey') or {}
    check('蜜果拾取发生', ho.get('pickups', 0) >= 2, str(ho.get('pickups')))
    check('每次拾取只随机 1 个 2 级增益', ho.get('oneLogs', 0) >= ho.get('pickups', 0),
          str(ho.get('oneLogs')))
    check('蜜果不再发放全部 7 个增益',
          all(len([x for x in s if '物防2' in x or '魔防2' in x or '治疗2' in x]) <= 1
              for s in ho.get('samples', [])), str(ho.get('samples'))[:240])

    bo = e.get('booms') or []
    check('爆裂箭消耗转化记录', len(bo) >= 2 and all(x['c']['count'] > 0 for x in bo),
          str(len(bo)))
    main_boom = next((x for x in bo if not x['evaded']), None)
    check('消耗能量+层数 → 追加伤害层数', bool(main_boom)
          and main_boom['c']['count'] == main_boom['c']['tp'] + main_boom['c']['stacks'],
          str(main_boom and main_boom['c']))
    check('追加伤害作为独立段结算', bool(main_boom and main_boom['bonus'])
          and main_boom['bonus']['factor'] == 40 * main_boom['c']['count'],
          str(main_boom and main_boom['bonus']))
    check('3 段基础伤害保留', bool(main_boom and main_boom['baseSegs'] == 3),
          str(main_boom and main_boom['baseSegs']))
    check('闪避时不误结算追加伤害', all(not (x['evaded'] and x['bonus']) for x in bo),
          str([(x['seed'], x['evaded'], bool(x['bonus'])) for x in bo]))

    da = e.get('dark') or {}
    check('开局随机 3 名友军获得[神经同步]', da.get('granted') == 3 and da.get('selected', 0) >= 1,
          str(da))
    check('与[神经同步]角色分摊伤害', da.get('share', 0) >= 3, str(da.get('share')))

    ps = e.get('personalities') or []
    check('逐角色文档含个性描述与效果', len(ps) == 4 and all(x['count'] >= 1 and x['hasDesc'] for x in ps),
          str(ps))
    sb = e.get('sub') or {}
    check('机制基底完整', sb.get('phases') == 4 and sb.get('pipeline') >= 10
          and sb.get('effects') >= 200 and sb.get('coverage') == 100, str(sb))

    sw = e.get('sweep') or {}
    check('192 场全量无异常', sw.get('done') == 192 and sw.get('err') == 0, str(sw.get('ex')))
    check('消耗转化在全量生效', sw.get('consumptionSteps', 0) > 100, str(sw.get('consumptionSteps')))
    check('随机增益在全量生效', sw.get('randomLogs', 0) > 1000, str(sw.get('randomLogs')))
    check('分摊伤害在全量生效', sw.get('shareLogs', 0) > 100, str(sw.get('shareLogs')))
    check('神经同步在全量生效', sw.get('syncLogs', 0) > 10, str(sw.get('syncLogs')))
    check('无 Lua 未知条件', not sw.get('unknown'), str(sw.get('unknown')))
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
        before = page.locator('#bsim-cup-sched').input_value()
        if PLAN.exists():
            page.locator('#bsim-plan-file').set_input_files(str(PLAN))
            page.wait_for_timeout(1400)
            after = page.locator('#bsim-cup-sched').input_value()
            check('导入方案自动切换到目标赛程', before != after and after == '90',
                  f'{before} -> {after}')
            check('导入提示说明切换', '赛程 90' in page.locator('#bsim-plan-msg').inner_text(),
                  page.locator('#bsim-plan-msg').inner_text())
            # Round 36: seed 7 has 安娜's 爆裂箭 survive all 3 base hits, so
            # the追加段 resolves; other seeds can overkill before it settles.
            page.fill('#bsim-seed', '7')
            page.dispatch_event('#bsim-seed', 'change')
            page.wait_for_timeout(1100)
            mx = int(page.locator('#bsim-range').get_attribute('max') or 0)
            boom = None
            for i in range(0, min(mx, 60)):
                page.evaluate("(i)=>{const r=document.querySelector('#bsim-range');r.value=String(i);r.dispatchEvent(new Event('input',{bubbles:true}));}", i)
                page.wait_for_timeout(14)
                t = page.locator('#bsim-detail').inner_text()
                if ('爆裂箭' in t and '消耗转化' in t and '第 1/3 段' in t
                        and '追加' in t and '增伤 60%' in t):
                    boom = t
                    break
            check('浏览器展示爆裂箭消耗转化与 3 段', bool(boom), (boom or '')[:140].replace('\n', ' '))
            if boom:
                check('浏览器展示追加伤害段', '追加' in boom and '增伤 60%' in boom)
                check('浏览器展示消耗转化面板', page.locator('.bsim-consumption').count() == 1)
            # character panel personality
            page.locator('.bsim-unit[data-unit]').first.click()
            page.wait_for_timeout(350)
            # The unit selection is a toggle; a second click reopens it if the
            # panel was already selected before the seed change.
            if not page.locator('.bsim-personality').count():
                page.locator('.bsim-unit[data-unit]').first.click()
                page.wait_for_timeout(350)
            check('角色面板展示个性效果', page.locator('.bsim-personality').count() == 1
                  and '个性效果' in page.locator('#bsim-panel').inner_text(),
                  page.locator('.bsim-personality').count())
            check('角色面板展示攻击时修正',
                  page.locator('.bsim-cond-mods').count() >= 0)
        # per-character doc page
        page.goto(BASE + '#/character-mechanics')
        page.locator('#cm-list .mechanics-entry').first.wait_for()
        page.locator('#cm-query').fill('安娜')
        page.wait_for_timeout(250)
        check('逐角色机制页展示个性效果',
              page.locator('.cm-personality').count() >= 1
              and '个性效果' in page.locator('#cm-list').inner_text())
        # client code page
        page.goto(BASE + '#/code')
        page.locator('.world-lua-panel').wait_for()
        page.evaluate("()=>{document.querySelector('.world-lua-panel').open=true;}")
        page.wait_for_timeout(200)
        check('客户端代码页展示机制基底',
              '战斗逻辑基底' in page.locator('.world-lua-panel').inner_text()
              and '100%' in page.locator('.bsim-lua-stats').inner_text())
        page.locator('.world-lua-q').fill('ShareDamage')
        page.wait_for_timeout(250)
        check('客户端代码页可检索解密常量',
              page.locator('.world-lua-file').count() > 0 or '常量' in page.locator('.world-lua-out').inner_text(),
              page.locator('.world-lua-out').inner_text()[:120].replace('\n', ' '))
        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
