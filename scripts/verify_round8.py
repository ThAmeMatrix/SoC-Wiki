"""Round 8: left sticky nav, default all-lit trees, global talent nodes,
per-group clear, percent-first inputs, paired results, dual adjustment.

    python -X utf8 scripts/verify_round8.py
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
    check('global talent vector exported',
          P['talents']['star']['global']['flat'][0] == 60
          and P['talents']['star']['global']['perm'][0] == 50,
          str(P['talents']['star']['global']))
    flags = sum(1 for tree in P['talents']['star']['trees'].values()
                for n in tree['nodes'] if n.get('global'))
    check('all-profession nodes flagged', flags == 10, str(flags))

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

        # ---- 3. Watcher star tree = 810 / 30% ----
        watcher = page.evaluate("""()=>{
          const P=window.WIKI_PANEL_DATA,C=window.WikiPanelCalc;
          const ch=P.characters.find(c=>c.professionCategory===5);
          const cfg={...C.defaults(P),character:ch.key,talentNodes:C.defaultTalentNodes(P,ch)};
          const b=C.talentBreakdown(P,ch,cfg);
          return {star:b.star,total:b.total,starKeys:Object.keys(cfg.talentNodes.star).length,
                  pioneerKeys:Object.keys(cfg.talentNodes.pioneer).length};
        }""")
        check('watcher star HP matches in-game 810', watcher['star']['flat'][0] == 810,
              str(watcher['star']['flat'][0]))
        check('watcher star HP permillage matches 30%', watcher['star']['perm'][0] == 300,
              str(watcher['star']['perm'][0]))
        check('defaults light every node in both trees',
              watcher['starKeys'] >= 80 and watcher['pioneerKeys'] >= 260,
              f"{watcher['starKeys']}/{watcher['pioneerKeys']}")

        # ---- 2. Both trees all-lit by default; split + total display ----
        bonus = page.locator('.panel-talent-bonus').inner_text()
        check('star and pioneer bonuses shown separately',
              '星辰天赋' in bonus and '开拓天赋' in bonus)
        check('combined talent total shown', '天赋总加成' in bonus)
        check('all-profession nodes mentioned', '全职业节点' in bonus)
        check('topology starts fully lit',
              page.locator('.panel-topo-node.is-lit').count() > 0,
              str(page.locator('.panel-topo-node.is-lit').count()))

        # ---- 1. Left sticky sidebar, visible at 伤害预估 ----
        check('nav is the first child of the layout grid',
              page.evaluate("()=>document.querySelector('.panel-layout').firstElementChild.classList.contains('panel-jump')"))
        check('nav is sticky', page.evaluate("()=>getComputedStyle(document.querySelector('.panel-jump')).position") == 'sticky')
        cols = page.evaluate("()=>getComputedStyle(document.querySelector('.panel-layout')).gridTemplateColumns")
        # Round 18 restored the compact right result column.
        check('three-column layout with nav first', len(cols.split()) == 3, cols)
        page.evaluate("()=>document.querySelector('[data-panel-jump=\"06\"]').click()")
        page.wait_for_timeout(650)
        nav = page.evaluate("""()=>{const r=document.querySelector('.panel-jump').getBoundingClientRect();
          return {top:Math.round(r.top),visible:r.top<innerHeight&&r.bottom>0,y:Math.round(scrollY)}}""")
        # Round 17: results moved above the form, so the jump no longer
        # scrolls thousands of pixels; the nav must simply stay visible.
        check('nav stays visible at 伤害预估', nav['visible'] and nav['top'] < 200,
              str(nav))
        page.evaluate("()=>window.scrollTo({top:document.body.scrollHeight,behavior:'instant'})")
        page.wait_for_timeout(250)
        check('nav stays visible at page bottom',
              page.evaluate("""()=>{const r=document.querySelector('.panel-jump').getBoundingClientRect();
                return r.top<innerHeight&&r.bottom>0}"""))

        # ---- 6. Paired result rows ----
        # Round 16: results now reuse the infographic stat-bar component with
        # one card per stat instead of two paired rows.
        # Round 19: six stats in the infographic workshop's paired order.
        cards = page.locator('#panel-output .ig-stat-card')
        check('six stat cards', cards.count() == 6, str(cards.count()))
        check('attack stats present',
              '物攻' in cards.nth(0).inner_text() and '魔攻' in cards.nth(1).inner_text(),
              cards.nth(0).inner_text()[:40])
        check('defence stats present',
              '物防' in cards.nth(2).inner_text() and '魔防' in cards.nth(3).inner_text(),
              cards.nth(2).inner_text()[:40])

        # ---- 5. Percent-first inputs (internally per-mille) ----
        pct = page.locator('[data-percent="10"]')
        check('percent inputs present', pct.count() >= 10, str(pct.count()))
        first = pct.first
        first.fill('10')
        first.dispatch_event('input')
        page.wait_for_timeout(200)
        stored = page.evaluate("""()=>{const c=JSON.parse(localStorage.getItem('socwiki.panel.current'));
          return c.weapon.enchant.percents[0]}""")
        check('10% is stored as 100 per-mille', stored == 100, str(stored))
        check('enchant header shows percent before fixed',
              page.evaluate("""()=>{const h=[...document.querySelectorAll('.panel-affix-head-percent')][0];
                return h?[...h.children].map(x=>x.textContent).join('|'):''}""") .find('百分比') <
              page.evaluate("""()=>{const h=[...document.querySelectorAll('.panel-affix-head-percent')][0];
                return h?[...h.children].map(x=>x.textContent).join('|'):''}""").find('固定值'))
        first.fill('0')
        first.dispatch_event('input')

        # ---- 7. Talent adjustment supports percent AND flat ----
        adjust = page.locator('.panel-adjust-row').first
        percent_input = adjust.locator('[data-percent]')
        flat_input = adjust.locator('[data-path^="talentAdjustFlat."]')
        check('adjust row has percent input', percent_input.count() == 1)
        check('adjust row has flat input', flat_input.count() == 1)
        percent_input.fill('5')
        percent_input.dispatch_event('input')
        flat_input.fill('120')
        flat_input.dispatch_event('input')
        page.wait_for_timeout(200)
        adj = page.evaluate("""()=>{const c=JSON.parse(localStorage.getItem('socwiki.panel.current'));
          return {perm:c.talentAdjust[0],flat:c.talentAdjustFlat[0]}}""")
        check('adjust percent stored as per-mille', adj['perm'] == 50, str(adj))
        check('adjust flat stored directly', adj['flat'] == 120, str(adj))
        percent_input.fill('0'); percent_input.dispatch_event('input')
        flat_input.fill('0'); flat_input.dispatch_event('input')

        # ---- 4. Clear one grade / one 图 ----
        clear_group = page.locator('[data-talent-clear-group="star"]')
        check('per-grade clear button present', clear_group.count() == 1)
        before = page.evaluate("""()=>Object.keys(JSON.parse(localStorage.getItem('socwiki.panel.current')).talentNodes.star).length""")
        clear_group.evaluate('e=>e.click()')
        page.wait_for_timeout(300)
        after = page.evaluate("""()=>Object.keys(JSON.parse(localStorage.getItem('socwiki.panel.current')).talentNodes.star).length""")
        check('clearing one grade removes only its nodes', 0 < after < before, f'{before} -> {after}')
        check('all-tree clear button present', page.locator('[data-talent-clear="star"]').count() == 1)
        check('per-图 clear button present', page.locator('[data-talent-clear-group="pioneer"]').count() == 1)

        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
