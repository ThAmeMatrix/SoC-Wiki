"""Round 9: pioneer lanes, single-counted global nodes, optional equipment,
damage jump, percent-only display, compact aside, clickable formula.

    python -X utf8 scripts/verify_round9.py
"""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / 'index.html').as_uri()
failures = []


def check(name, ok, detail=''):
    print(('PASS ' if ok else 'FAIL ') + name + (f' :: {detail}' if detail else ''), flush=True)
    if not ok:
        failures.append(name)


def load(relative, variable):
    t = (ROOT / relative).read_text('utf8')
    m = 'window.' + variable + '='
    return json.JSONDecoder().raw_decode(t[t.index(m) + len(m):])[0]


def main():
    P = load('data/panel-data.js', 'WIKI_PANEL_DATA')
    check('global talent vector intact',
          P['talents']['star']['global']['flat'][0] == 60 and
          P['talents']['star']['global']['perm'][0] == 50)

    errors, failed = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(offline=True, viewport={'width': 1600, 'height': 900}).new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))
        page.goto(BASE + '#/tools/panel')
        page.locator('#panel-output [data-stat-bars]').wait_for()
        page.locator('.panel-bp-formula').evaluate('e=>{e.open=true}')

        # ---- 2. Global nodes counted exactly once ----
        values = page.evaluate("""()=>{
          const P=window.WIKI_PANEL_DATA,C=window.WikiPanelCalc;
          const ch=P.characters.find(c=>c.professionCategory===5);
          const cfg={...C.defaults(P),character:ch.key,talentNodes:C.defaultTalentNodes(P,ch)};
          const bd=C.talentBreakdown(P,ch,cfg), b=C.talentBonuses(P,ch,cfg);
          const own=C.talentTree(P,'star',ch).nodes.filter(n=>n.global)
            .reduce((a,n)=>a+n.levels.at(-1).flat[4],0);
          return {star:bd.star,bonus:b.flat,ownGlobalFlat:own,
                  global:P.talents.star.global,formula:!!C.calculate(cfg,P).formula};
        }""")
        check('watcher star HP still 810', values['star']['flat'][0] == 810,
              str(values['star']['flat'][0]))
        check('watcher star HP percent still 30%', values['star']['perm'][0] == 300,
              str(values['star']['perm'][0]))
        # own two global nodes add 20 magic defence; 110 own + 20 = 130 (not 150)
        check('magic defence global node counted once',
              values['star']['flat'][4] == 130, str(values['star']['flat'][4]))
        check('magic defence percent counted once',
              values['star']['perm'][4] == 300, str(values['star']['perm'][4]))
        check('calculator agrees with breakdown',
              values['bonus'][4] == values['star']['flat'][4] + 163,
              str(values['bonus'][4]))

        # ---- 1. Pioneer lanes: physical branch at the bottom ----
        page.evaluate("""()=>{const s=document.querySelector('[data-path="talentView.pioneer"]');
          s.selectedIndex=28;s.dispatchEvent(new Event('change',{bubbles:true}))}""")
        page.wait_for_timeout(350)
        lanes = page.eval_on_selector_all('.panel-talent-lane h4', 'els=>els.map(e=>e.textContent)')
        check('pioneer cards grouped into three lanes',
              lanes == ['魔法道', '中间', '物理道'], str(lanes))
        labels = page.eval_on_selector_all('svg.panel-topo:last-of-type .panel-topo-lane',
                                           'els=>els.map(e=>({t:e.textContent,y:Number(e.getAttribute("y"))}))')
        check('physical lane is drawn at the bottom',
              any(x['t'] == '物理道' and x['y'] > 400 for x in labels), str(labels))
        positions = page.evaluate("""()=>[...document.querySelectorAll('svg.panel-topo')[1]
          .querySelectorAll('.panel-topo-node')].map(g=>({
            name:g.querySelector('.panel-topo-name')?.textContent,
            y:Number(g.getAttribute('transform').match(/,([\\d.]+)\\)/)[1])}))""")
        phys = [x['y'] for x in positions if x['name'] and '物攻' in x['name']]
        magic = [x['y'] for x in positions if x['name'] and '魔攻' in x['name']]
        check('物攻 branch below 魔攻 branch',
              bool(phys and magic and min(phys) > max(magic)),
              f'phys={phys} magic={magic}')

        # ---- 3. Optional equipment ----
        page.evaluate("""()=>{const i=document.querySelector('[data-combo="weapon.id"]');i.click();
          [...document.querySelectorAll('[data-combo="weapon.id"] ~ .panel-combo-list [data-combo-value]')]
            .find(x=>x.dataset.comboValue==='0').click()}""")
        page.wait_for_timeout(350)
        heads = page.eval_on_selector_all('.panel-sub-head', 'els=>els.map(e=>e.textContent)')
        check('weapon 刻印 hidden when unequipped',
              '武器刻印' not in heads, str(heads))
        check('offhand 刻印 still available', '装具刻印' in heads, str(heads))
        check('unequipped id persisted',
              page.evaluate("()=>JSON.parse(localStorage.getItem('socwiki.panel.current')).weapon.id") in (0, '0'))
        page.reload()
        page.locator('#panel-output [data-stat-bars]').wait_for()
        page.locator('.panel-bp-formula').evaluate('e=>{e.open=true}')
        check('unequipped state survives reload',
              page.eval_on_selector('[data-combo="weapon.id"]', 'e=>e.value').startswith('不带'))
        # Restore a weapon for the remaining checks.
        page.evaluate("""()=>{const i=document.querySelector('[data-combo="weapon.id"]');i.click();
          const o=[...document.querySelectorAll('[data-combo="weapon.id"] ~ .panel-combo-list [data-combo-value]')]
            .find(x=>x.dataset.comboValue!=='0');o.click()}""")
        page.wait_for_timeout(300)

        # ---- 4. Damage preview is the last jump entry and scrolls into view ----
        nav = page.eval_on_selector_all('[data-panel-jump]', 'els=>els.map(e=>e.dataset.panelJump)')
        check('伤害预估结果 is last in quick jump', nav[-1] == '06', str(nav))
        page.locator('#panel-damage-result').evaluate('e=>{e.open=true}')
        page.locator('[data-panel-jump="06"]').click()
        page.wait_for_timeout(900)
        dmg = page.evaluate("""()=>{const d=document.querySelector('#panel-damage-result').getBoundingClientRect();
          return {visible:d.top<innerHeight&&d.bottom>0,top:Math.round(d.top)}}""")
        check('damage result card visible after jump', dmg['visible'], str(dmg))

        # ---- 5. Percent-only display ----
        # The battle-power formula quotes the client's raw per-mille weights
        # (120‰/200‰); only talent/bonus displays must be plain %.
        bonus = page.locator('#panel-output dl.calculation-steps').last.inner_text()
        check('talent/bonus results use % and no ‰', '%' in bonus and '‰' not in bonus,
              bonus[:120].replace('\n', ' '))
        page.locator('.panel-formula').evaluate('e=>{e.open=true}')
        page.wait_for_timeout(150)
        check('formula uses percent', '100%' in page.locator('.formula-row').first.inner_text(),
              page.locator('.formula-row').first.inner_text()[:120].replace('\n', ' '))
        check('no per-mille in bonus rows', '‰' not in page.locator('#panel-output dl.calculation-steps').last.inner_text())

        # ---- 6. Compact right column ----
        aside = page.evaluate("""()=>{const a=document.querySelector('.damage-aside');
          return {client:a.clientHeight,scroll:a.scrollHeight,rect:Math.round(a.getBoundingClientRect().height)}}""")
        check('aside fits a normal screen', aside['rect'] <= 900, str(aside))
        check('aside scrolls internally', aside['scroll'] > aside['client'], str(aside))
        folds = page.eval_on_selector_all('.panel-aside-fold', 'els=>els.map(e=>e.open)')
        check('long breakdown/presets collapsed by default', folds == [False, False], str(folds))
        page.locator('.panel-aside-fold > summary').first.click()
        page.wait_for_timeout(200)
        check('breakdown can be expanded',
              page.eval_on_selector_all('.panel-aside-fold', 'els=>els[0].open'))

        # ---- 7. Clickable formula with one number per source ----
        page.evaluate("()=>window.scrollTo({top:0,behavior:'instant'})")
        page.wait_for_timeout(150)
        detail = page.locator('.panel-formula')
        if not detail.evaluate('e=>e.open'):
            detail.locator('summary').click()
            page.wait_for_timeout(200)
        nums = page.locator('.formula-num')
        check('formula has clickable numbers', nums.count() >= 10, str(nums.count()))
        check('formula covers every source section',
              page.eval_on_selector_all('.formula-num',
                  'els=>[...new Set(els.map(e=>e.dataset.formulaJump))].sort().join(",")') == '01,02,03,04,05',
              page.eval_on_selector_all('.formula-num',
                  'els=>[...new Set(els.map(e=>e.dataset.formulaJump))].sort().join(",")'))
        page.evaluate("""()=>[...document.querySelectorAll('.formula-num')]
          .find(x=>x.dataset.formulaJump==='05').click()""")
        page.wait_for_timeout(850)
        jumped = page.evaluate("""()=>({y:Math.round(scrollY),
          top:Math.round(document.querySelector('#panel-sec-05').getBoundingClientRect().top),
          flash:document.querySelectorAll('.panel-sec-flash').length})""")
        check('clicking a formula number jumps to its source',
              jumped['y'] > 500 and abs(jumped['top']) < 400 and jumped['flash'] >= 1,
              str(jumped))
        page.select_option('[data-formula-stat]', '2')
        page.wait_for_timeout(150)
        check('formula stat switch works',
              page.eval_on_selector('.formula-row:not([hidden])', 'e=>e.dataset.stat') == '2')

        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
