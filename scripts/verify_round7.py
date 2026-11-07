"""Round 7: panel jump sidebar, scroll stability, cumulative talent bonuses.

    python -X utf8 scripts/verify_round7.py
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
    # ---- 3. Cumulative (not incremental) talent bonuses ----
    P = load('data/panel-data.js', 'WIKI_PANEL_DATA')
    # Every client node's level rows are monotonic cumulative values.
    monotonic = all(
        all(all(b['flat'][s] >= a['flat'][s] and b['perm'][s] >= a['perm'][s]
                for s in range(5))
            for a, b in zip(n['levels'], n['levels'][1:]))
        for key in ('star', 'pioneer')
        for tree in P['talents'][key]['trees'].values()
        for n in tree['nodes'])
    check('client level rows are cumulative/monotonic', monotonic)
    client = (ROOT / 'panel-calc.js').read_text('utf8')
    check('talentBonuses reads only the invested level',
          'const current = node.levels[usable - 1]' in client)
    check('experience is still summed per level',
          'for (let i = 0; i < usable; i++) spent += int(node.levels[i].exp)' in client)
    check('progress uses the same cumulative row',
          client.count('const current = node.levels[usable - 1]') == 2,
          str(client.count('const current = node.levels[usable - 1]')))

    # Node-level numeric proof via the calculator itself.
    errors, failed = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(offline=True, viewport={'width': 1440, 'height': 900}).new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))
        page.goto(BASE + '#/tools/panel')
        page.locator('#panel-output [data-stat-bars]').wait_for()

        proof = page.evaluate("""()=>{
          const P=window.WIKI_PANEL_DATA,C=window.WikiPanelCalc;
          const ch=P.characters.find(c=>c.professionCategory===2)||P.characters[0];
          const tree=C.talentTree(P,'star',ch);
          const out={};
          for(const id of [203,207,210]){
            const n=tree.nodes.find(x=>x.id===id); if(!n)continue;
            const top=n.levels.length;
            const cfg={...C.defaults(P),talentNodes:{star:{[id]:top},pioneer:{}}};
            const b=C.talentBonuses(P,ch,cfg), pr=C.talentProgress(P,ch,cfg);
            out[id]={name:n.name,level:top,flat:b.flat,perm:b.permillage,
                     expectFlat:n.levels[top-1].flat,expectPerm:n.levels[top-1].perm,
                     progressFlat:pr.flat,exp:pr.exp,
                     expectExp:n.levels.reduce((a,l)=>a+(l.exp||0),0)};
          }
          // legacy tier must not triple-count either
          out.legacy=P.talents.star.byCategory['2'][1];
          return out;
        }""")
        for nid, want in ((203, [0, 10, 10, 0, 0]), (207, [0, 50, 50, 0, 0]), (210, [50, 0, 0, 0, 0])):
            r = proof.get(str(nid))
            check(f'node {nid} bonus is the level row (not summed)',
                  bool(r) and r['flat'] == want == r['expectFlat'],
                  r and f"{r['name']} Lv.{r['level']}: {r['flat']} expected {want}")
            check(f'node {nid} progress matches',
                  bool(r) and r['progressFlat'] == want)
            check(f'node {nid} experience still accumulates',
                  bool(r) and r['exp'] == r['expectExp'],
                  r and f"{r['exp']} vs {r['expectExp']}")
        check('legacy tier no longer inflates bonuses',
              proof['legacy']['flat'][1] < 100, str(proof['legacy']))

        # ---- 1. Sidebar jump navigation ----
        nav = page.locator('.panel-jump')
        check('jump sidebar present', nav.count() == 1)
        links = page.locator('[data-panel-jump]')
        check('all seven sections have jump links', links.count() == 7, str(links.count()))
        check('sections carry anchor ids',
              page.locator('[data-panel-section]').count() >= 7,
              str(page.locator('[data-panel-section]').count()))
        page.evaluate('window.scrollTo(0,0)')
        links.nth(4).click()
        page.wait_for_timeout(700)
        jumped = page.evaluate('window.scrollY')
        check('jump scrolls to the target section', jumped > 200, str(jumped))
        check('active link highlighted',
              page.locator('[data-panel-jump].active').count() == 1)
        check('hash routing is unchanged',
              page.evaluate('location.hash').startswith('#/tools/panel'),
              page.evaluate('location.hash'))

        # ---- 2. Clicking a topology node keeps the scroll position ----
        page.locator('[data-panel-jump="05"]').click()
        page.wait_for_timeout(700)
        before = page.evaluate('window.scrollY')
        topo_before = page.evaluate("()=>{const e=document.querySelector('.panel-topo-scroll');return e?e.scrollLeft:0}")
        page.evaluate("()=>document.querySelector('[data-topo-node]').dispatchEvent(new MouseEvent('click',{bubbles:true}))")
        page.wait_for_timeout(300)
        after = page.evaluate('window.scrollY')
        topo_after = page.evaluate("()=>{const e=document.querySelector('.panel-topo-scroll');return e?e.scrollLeft:0}")
        check('page scroll preserved after node click', abs(after - before) < 40,
              f'{before} -> {after}')
        check('topology horizontal offset preserved', abs(topo_after - topo_before) < 4,
              f'{topo_before} -> {topo_after}')
        check('node click still toggles the build',
              page.locator('.panel-topo-node.is-lit').count() > 0)

        # Scroll down and click a card-level node too.
        page.evaluate("()=>window.scrollTo({top:1500,behavior:'instant'})")
        page.wait_for_timeout(250)
        deep_before = page.evaluate('window.scrollY')
        # DOM click avoids Playwright's own scrollIntoView, so this measures
        # only what our paint() does to the scroll position.
        page.evaluate("()=>document.querySelector('[data-talent-node]').click()")
        page.wait_for_timeout(300)
        deep_after = page.evaluate('window.scrollY')
        check('card node click preserves deep scroll', abs(deep_after - deep_before) < 40,
              f'{deep_before} -> {deep_after}')

        # One-click fill must also stay put and show the corrected totals.
        page.locator('[data-panel-jump="05"]').click()
        page.wait_for_timeout(600)
        page.evaluate("()=>window.scrollTo({top:2600,behavior:'instant'})")
        page.wait_for_timeout(250)
        fill_before = page.evaluate('window.scrollY')
        page.evaluate("()=>document.querySelector('[data-talent-fill]').click()")
        page.wait_for_timeout(300)
        check('fill-all preserves scroll',
              abs(page.evaluate('window.scrollY') - fill_before) < 40)
        bonus = page.locator('.panel-talent-bonus-row.is-total .panel-talent-bonus-grid').inner_text()
        check('bonus summary shows plausible totals', '+' in bonus,
              bonus[:160].replace('\n', ' '))
        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
