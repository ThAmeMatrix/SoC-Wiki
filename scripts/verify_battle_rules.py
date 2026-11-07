"""End-to-end check for combat formula sources, choice skills and mechanics.

    python -X utf8 scripts/verify_battle_rules.py
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
    text = (ROOT / relative).read_text('utf8')
    marker = 'window.' + variable + '='
    return json.JSONDecoder().raw_decode(text[text.index(marker) + len(marker):])[0]


def main():
    combat = load('data/combat-data.js', 'WIKI_COMBAT_DATA')
    choices = load('data/choice-skills.js', 'WIKI_CHOICE_SKILLS')
    mechanics = load('data/skill-mechanics.js', 'WIKI_SKILL_MECHANICS')
    check('combat constants sourced', len(combat['constants']) >= 8
          and combat['constants']['CritBaseDamage']['source'].startswith('const_param#'))
    check('restraint matrix sourced', len(combat['restraints']) >= 8
          and all(r['source'].startswith('profession_restrain#') and r.get('specialityId')
                  for r in combat['restraints']))
    watcher = next(r for r in combat['restraints'] if r['fromName'] == '守望者' and r['toName'] == '毁灭者')
    destroyer = next(r for r in combat['restraints'] if r['fromName'] == '毁灭者' and r['toName'] == '守望者')
    check('守望者→毁灭者 is 1.4 (speciality#3326)', watcher['factor'] == 1.4
          and watcher['evaluate'] == 130 and watcher['specialityId'] == 3326, str(watcher['percent']))
    check('毁灭者→守望者 is 0.6 (speciality#3325)', destroyer['factor'] == 0.6
          and destroyer['specialityId'] == 3325, str(destroyer['percent']))
    check('both formulas have tables', len(combat['formulas']) == 2
          and all(f['tables'] and f['source'] for f in combat['formulas']))
    check('formulas expose structured variables',
          all(len(f.get('variables') or []) >= 5 for f in combat['formulas']),
          '/'.join(str(len(f.get('variables') or [])) for f in combat['formulas']))
    check('choice groups exported', len(choices['groups']) >= 100, str(len(choices['groups'])))
    group = choices['branches'].get('7431')
    check('一掷千金 has two branches', group and len(group['children']) == 2,
          str(group and [c['name'] for c in group['children']]))
    check('branch links resolve to pages', group and {c['pageId'] for c in group['children']} == {3646, 3647})
    check('every branch page exists', all(
        (ROOT / 'data' / 'pages' / f"{c['pageId']}.js").is_file()
        for g in choices['branches'].values() for c in g['children']))
    rule = mechanics['skills'].get('7433')
    check('人为财死 has decoded rules', bool(rule and len(rule['rules']) >= 5), str(rule and len(rule['rules'])))
    check('gather rule explains direction bits', bool(rule and any('聚拢规则' in r and '上、下、左、右' in r
                                                                  for r in rule['rules'])))
    check('AOE geometry decoded', bool(rule and any('菱形 3 格' in r for r in rule['rules'])))
    check('buffs decoded with arrows', bool(rule and any('▼移动2' in r for r in rule['rules'])))
    check('rules have detailed explanations', bool(rule and len(rule.get('details') or []) >= 5
          and all(d.get('detail') and d.get('original') for d in rule['details'])))
    check('skill description preserved', bool(rule and rule['original']['skillDesc']))
    check('choice previews carry icons', bool(choices.get('previews') and
          any(v.get('iconFile') for v in choices['previews'].values())))
    check('choice previews carry range diagrams', bool(choices.get('previews') and
          any(v.get('rangeImage') for v in choices['previews'].values())))

    errors, failed = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(offline=True, viewport={'width': 1440, 'height': 1000}).new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))

        page.goto(BASE + '#/tools/panel')
        page.locator('#panel-output [data-stat-bars]').wait_for()
        page.locator('#panel-damage-result').evaluate('e=>{e.open=true}')
        check('damage preview rendered', page.locator('.panel-damage-total strong').count() == 1,
              page.locator('.panel-damage-total strong').inner_text())
        before = int(page.locator('.panel-damage-total strong').inner_text().replace(',', ''))
        page.locator('[data-path="combat.defense"]').fill('0')
        page.locator('[data-path="combat.defense"]').dispatch_event('input')
        page.wait_for_timeout(200)
        after = int(page.locator('.panel-damage-total strong').inner_text().replace(',', ''))
        check('target defense affects damage', after > before, f'{before} -> {after}')
        page.locator('summary', has_text='公式与数值来源').click()
        check('formula source tables shown',
              'profession_restrain' in page.locator('.tool-help', has_text='公式与数值来源').inner_text())
        check('formula variables rendered', page.locator('.formula-vars tbody tr').count() >= 12)
        page.locator('.formula-live summary').click()
        check('live formula variables shown', page.locator('.formula-live .calculation-steps div').count() >= 5)

        page.goto(BASE + '#/page/100007431')
        page.locator('.choice-panel').wait_for()
        cards = page.locator('.choice-card')
        check('one-thousand-gold shows two branch cards', cards.count() == 2)
        links = page.locator('.choice-card-link')
        check('branch cards link to skill pages',
              {links.nth(i).get_attribute('href') for i in range(links.count())} == {'#/page/3647', '#/page/3646'})
        check('branch cards show skill icons', page.locator('.choice-card-icon').count() == 2)
        page.locator('.choice-preview summary').first.click()
        check('expandable preview shows effect text',
              '泼洒金币' in page.locator('.choice-preview-body').first.inner_text())
        check('expandable preview shows range figure', page.locator('.choice-range img').count() >= 1)
        check('parent page shows detailed mechanics', page.locator('.mechanics-detail').count() >= 2)
        check('mechanics keep original text', page.locator('.mech-original').count() >= 2)

        # Skill & growth page: hover keeps the glossary tooltip, click jumps straight to the skill.
        page.goto(BASE + '#/page/3476')
        page.locator('.detail-tabs').wait_for()
        page.locator('[data-detail-tab="skills"]').click()
        page.locator('.growth-explorer').wait_for()
        page.locator('[data-skill-key="3-0"]').click()
        page.wait_for_timeout(220)
        term = page.locator('.skill-inspector a.term-link', has_text='人为财死')
        check('growth page exposes the choice term', term.count() == 1)
        check('term keeps its glossary href for hover', '300000594' in term.first.get_attribute('href'))
        term.first.hover()
        page.wait_for_timeout(400)
        check('hover still shows the glossary effect',
              page.locator('.term-tip').is_visible() and '人为财死' in page.locator('.term-tip').inner_text())
        term.first.click()
        page.wait_for_timeout(350)
        check('clicking the term opens the skill page directly',
              page.evaluate('location.hash') == '#/page/3647', page.evaluate('location.hash'))

        page.goto(BASE + '#/page/3647')
        page.locator('.choice-backlink').wait_for()
        check('child page has parent backlink', '一掷千金' in page.locator('.choice-backlink').inner_text())
        page.goto(BASE + '#/page/100007531')
        page.locator('.detail-heading h1').wait_for()
        check('generated branch page renders', page.locator('.choice-backlink').count() == 1,
              page.locator('.detail-heading h1').inner_text())

        page.goto(BASE + '#/mechanics')
        page.locator('.mechanics-toolbar').wait_for()
        check('mechanics browser lists rules', page.locator('.mechanics-entry').count() > 10)
        page.locator('#mechanics-query').fill('聚拢')
        page.wait_for_timeout(300)
        check('gather rule is searchable', page.locator('.mechanics-entry').count() > 0
              and '聚拢' in page.locator('.mechanics-list').inner_text())
        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()
    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
