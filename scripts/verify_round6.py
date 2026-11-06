"""Round 6: canonical mechanic entries, skill-axis icons, talent topology.

    python -X utf8 scripts/verify_round6.py
"""
import json
import sys
from collections import Counter
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
    # ---- 1. One authoritative entry per skill name. ----
    mech = load('data/skill-mechanics.js', 'WIKI_SKILL_MECHANICS')
    skills = mech['skills']
    names = [s['name'] for s in skills.values()]
    check('one entry per skill name', len(names) == len(set(names)),
          f'{len(skills)} entries / {len(set(names))} names')
    check('authority and confidence recorded',
          all(s.get('authority') and s.get('confidence') for s in skills.values()))
    conf = Counter(s['confidence'] for s in skills.values())
    check('most entries have high-confidence authority', conf['high'] > len(skills) * 0.85,
          str(dict(conf)))
    variants = sum(s.get('variantCount', 0) for s in skills.values())
    check('duplicate variants folded into canonical entries', variants > 1000, str(variants))
    target = skills.get('7433')
    check('人为财死 resolves to the choice-branch id', bool(target) and target['name'] == '人为财死'
          and '抉择' in target['authority'] and target['confidence'] == 'high',
          target and target['authority'])
    check('variant details retained', bool(target and target['variants']
          and any(v.get('editorName') for v in target['variants'])))
    check('pinyin still present', bool(target and target.get('ini') == 'rwcs'))
    choice = load('data/choice-skills.js', 'WIKI_CHOICE_SKILLS')
    names_in_mech = {s['name'] for s in skills.values()}
    branch_names = [c['name'] for g in choice['groups'] for c in g['children']]
    covered = sum(1 for n in branch_names if n in names_in_mech)
    check('choice-branch names have a canonical mechanic entry',
          covered > len(branch_names) * 0.8, f'{covered} / {len(branch_names)}')

    # ---- 2. Skill-axis icons. ----
    panel = load('data/panel-data.js', 'WIKI_PANEL_DATA')
    line_skills = panel.get('lineSkills') or {}
    slots = [s for ranks in line_skills.values() for sides in ranks.values() for s in sides if s]
    with_image = [s for s in slots if s.get('image')]
    check('skill-axis names exported for characters', len(line_skills) > 140, str(len(line_skills)))
    check('skill icons cover the axis', len(with_image) > 1600,
          f'{len(with_image)} / {len(slots)}')
    missing_files = [s['image'] for s in with_image if not (ROOT / s['image']).is_file()]
    check('all referenced icons exist', not missing_files, str(missing_files[:3]))

    # ---- 3. Talent topology / materials / fill-all. ----
    star = panel['talents']['star']
    materials = star.get('materials') or {}
    check('material names exported', bool(materials.get('135', {}).get('paramNames', {}).get('1'))
          and bool(materials.get('168', {}).get('paramNames', {}).get('1')))
    cat = star['trees']['2']
    cost_nodes = [n for n in cat['nodes'] if n['levels'][0]['cost']]
    check('each level cost keeps type / material / amount',
          all(len(c) == 3 for n in cost_nodes for lv in n['levels'] for c in lv['cost']))
    check('nodes carry topology coordinates',
          all('grade' in n and 'lane' in n and 'col' in n and 'prev' in n for n in cat['nodes']))
    pioneer = panel['talents']['pioneer']['trees']['2']
    check('pioneer nodes carry x/y grid coords',
          all(n['x'] > 0 and n['y'] > 0 for n in pioneer['nodes'][:50]))

    errors, failed = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(offline=True, viewport={'width': 1440, 'height': 1000}).new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))

        # Mechanics page: one card per name, authority badge and variants.
        page.goto(BASE + '#/mechanics')
        page.locator('#mechanics-query').wait_for()
        search = page.locator('#mechanics-query')
        search.fill('人为财死')
        page.wait_for_timeout(220)
        check('every result card has a distinct name',
              page.evaluate("""()=>{const n=[...document.querySelectorAll('.mechanics-entry h2')]
                .map(h=>h.childNodes[0].textContent.trim());return n.length===new Set(n).size}"""))
        # Full-text search also matches skills whose description mentions the
        # name; the canonical card is the one titled exactly 人为财死.
        card = page.locator('.mechanics-entry').filter(has=page.locator('h2', has_text='人为财死')).first
        check('canonical card exists', card.count() == 1)
        check('authority badge shown', '权威词条' in card.inner_text())
        check('variants collapsed in a details block',
              card.locator('.mech-variants').count() == 1)
        check('variant list has entries',
              card.locator('.mech-variants li').count() >= 4)

        # Panel: skill-axis images.
        page.goto(BASE + '#/tools/panel')
        page.locator('#panel-output .panel-total-grid').wait_for()
        imgs = page.locator('.panel-node-img')
        check('skill axis renders real icons', imgs.count() >= 8, str(imgs.count()))
        page.wait_for_function("()=>[...document.querySelectorAll('.panel-node-img')].every(i=>i.complete)")
        broken = page.evaluate("()=>[...document.querySelectorAll('.panel-node-img')].filter(i=>i.naturalWidth===0).map(i=>i.src)")
        check('skill icons load', not broken, str(broken[:3]))
        check('skill names shown on nodes',
              page.locator('.panel-node-select strong').first.inner_text() not in ('', '技能轴一'))

        # Talent topology.
        svgs = page.locator('svg.panel-topo')
        check('topology graphs render for both trees', svgs.count() == 2, str(svgs.count()))
        check('topology draws prerequisite links',
              page.locator('.panel-topo-link').count() > 4,
              str(page.locator('.panel-topo-link').count()))
        check('topology nodes are clickable',
              page.locator('[data-topo-node]').count() > 4,
              str(page.locator('[data-topo-node]').count()))
        check('per-level material tables present',
              page.locator('.panel-node-levels').count() > 4)
        first_details = page.locator('.panel-node-levels').first
        first_details.locator('summary').click()
        check('per-level rows show material names',
              '星' in first_details.inner_text() or '币' in first_details.inner_text()
              or '微粒' in first_details.inner_text() or '誓言' in first_details.inner_text(),
              first_details.inner_text()[:120].replace('\n', ' '))

        # One-click fill: bonus summary must change and nodes become lit.
        before = page.locator('.panel-talent-bonus-row.is-total .panel-talent-bonus-grid').inner_text()
        # Both trees are fully lit by default: clear this grade first so the
        # one-click fill has something to do.
        page.evaluate("()=>document.querySelector('[data-talent-clear-group]').click()")
        page.wait_for_timeout(200)
        cleared = page.locator('.panel-talent-bonus-row.is-total .panel-talent-bonus-grid').inner_text()
        check('clearing a grade lowers the bonus', cleared != before,
              before[:60].replace('\n', ' ') + ' -> ' + cleared[:60].replace('\n', ' '))
        page.locator('[data-talent-fill="star"]').evaluate('e=>e.click()')
        page.wait_for_timeout(250)
        after = page.locator('.panel-talent-bonus-row.is-total .panel-talent-bonus-grid').inner_text()
        check('fill-all restores the bonus summary', after == before,
              cleared[:60].replace('\n', ' ') + ' -> ' + after[:60].replace('\n', ' '))
        check('fill-all lights the group',
              page.locator('.panel-topo-node.is-lit').count() > 0,
              str(page.locator('.panel-topo-node.is-lit').count()))
        check('bonus grid shows real numbers', '+' in after)
        check('material totals use names', '材料：' in page.locator('.panel-talent-summary').inner_text())
        # Topology node click toggles a node.
        lit_before = page.locator('.panel-topo-node.is-lit').count()
        page.locator('[data-topo-node]').first.click()
        page.wait_for_timeout(220)
        check('topology node click toggles',
              page.locator('.panel-topo-node.is-lit').count() != lit_before)
        page.locator('[data-talent-clear="star"]').click()
        page.wait_for_timeout(220)
        check('clear resets the star tree',
              page.evaluate("()=>{const s=document.querySelectorAll('svg.panel-topo')[0];"
                            "return s?s.querySelectorAll('.panel-topo-node.is-lit').length:0}") == 0)
        # A 抉择 child page whose id was folded into a canonical entry must
        # still show the rules, with a real client id (no "skill#undefined").
        page.goto(BASE + '#/page/3647')
        page.locator('.mechanics-panel').wait_for()
        panel_text = page.locator('.mechanics-panel').inner_text()
        check('choice child page shows canonical mechanics',
              '权威词条' in panel_text and '抉择技能分支' in panel_text)
        page.locator('.mechanics-chain summary').click()
        chain_text = page.locator('.mechanics-chain').inner_text()
        check('canonical client id is shown',
              'skill#7433' in chain_text.lower() and 'undefined' not in chain_text.lower(),
              chain_text[:80].replace('\n', ' '))
        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
