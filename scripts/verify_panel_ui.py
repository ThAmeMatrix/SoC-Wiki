"""Browser smoke check for the panel calculator and the sprite/face tabs."""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / 'index.html').as_uri()
errors, failed, bad_status = [], [], []


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(offline=True, viewport={'width': 1440, 'height': 1000})
        page = context.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))
        page.on('response', lambda r: bad_status.append((r.status, r.url)) if r.status >= 400 and r.url.startswith('file:') else None)

        page.goto(BASE + '#/tools')
        page.locator('.tool-grid').wait_for()
        card = page.locator('.tool-card', has_text='局外面板计算器')
        assert card.count() == 1, 'panel card missing'
        card.click()
        page.locator('#panel-output .panel-total-grid').wait_for()
        totals = page.locator('.panel-total-grid strong').all_inner_texts()
        assert len(totals) == 3, totals
        print('panel default totals:', ' / '.join(totals))
        expected = page.evaluate("()=>{const P=window.WIKI_PANEL_DATA,C=window.WikiPanelCalc;const r=C.calculate(C.defaults(P),P).total;return [String(r[0]),r[1]+' / '+r[2],r[3]+' / '+r[4]]}")
        norm = lambda s: s.replace(',', '').replace(' ', '')
        assert [norm(x) for x in totals] == [norm(x) for x in expected], (totals, expected)
        print('defaults match pure calculation:', ' / '.join(expected))
        assert page.locator('#panel-steps .panel-step-list > div').count() >= 3

        page.locator('[data-path="star"]').select_option('1')
        low = page.locator('.panel-total-grid strong').all_inner_texts()
        assert low != totals, 'star change did not update'
        print('after 1 star   :', ' / '.join(low))
        page.locator('[data-path="star"]').select_option('5')

        page.locator('[data-path="weapon.enchant.percents.1"]').fill('100')
        boosted = page.locator('.panel-total-grid strong').all_inner_texts()
        assert boosted != totals, 'enchant did not update'
        print('after enchant  :', ' / '.join(boosted))
        page.locator('[data-path="weapon.enchant.percents.1"]').fill('0')

        # Skill-axis tree: same tier/node visuals as the infographic, but every
        # node only toggles between lit and unlit (no 必点/选点 cycle).
        tree_nodes = page.locator('[data-line-node]')
        assert tree_nodes.count() >= 8, 'skill-axis tree nodes missing'
        assert page.locator('.panel-tree-tier').count() >= 4, 'skill-axis tiers missing'
        before_lines = page.locator('.panel-total-grid strong').all_inner_texts()
        right_node = page.locator('[data-line-node="1"][data-line-side="right"]')
        assert right_node.count() == 1, 'rank-1 right node missing'
        assert right_node.get_attribute('aria-pressed') == 'false', 'default right node should be unlit'
        right_node.click()
        assert page.locator('[data-line-node="1"][data-line-side="right"]').get_attribute('aria-pressed') == 'true'
        after_lines = page.locator('.panel-total-grid strong').all_inner_texts()
        assert after_lines != before_lines, 'skill-axis node click had no effect'
        print('skill-axis node:', ' / '.join(before_lines), '->', ' / '.join(after_lines))
        page.locator('[data-line-node="1"][data-line-side="right"]').click()
        assert page.locator('.panel-total-grid strong').all_inner_texts() == before_lines, 'node did not toggle back'

        # Real talent trees: grade / 图 grouping, per-node investment, exp totals.
        assert page.locator('.panel-talent-tree').count() == 2, 'star and pioneer trees missing'
        assert page.locator('[data-path="talentView.star"]').count() == 1
        assert page.locator('[data-path="talentView.pioneer"]').count() == 1
        assert page.locator('[data-talent-node]').count() > 4, 'no talent nodes rendered'
        summary = page.locator('.panel-talent-summary').inner_text()
        assert '品阶' in summary and '经验' in summary, summary
        before_talent = page.locator('.panel-total-grid strong').all_inner_texts()
        before_summary = page.locator('.panel-talent-summary').inner_text()
        # Pick a lit-capable attribute node and check the panel reacts.
        attr_node = page.locator('.panel-talent-node:not(.is-utility) [data-talent-node]').first
        assert attr_node.count() == 1, 'no attribute talent node'
        attr_node.click()
        after_talent = page.locator('.panel-total-grid strong').all_inner_texts()
        assert after_talent != before_talent, 'lighting a talent node had no effect'
        lit_summary = page.locator('.panel-talent-summary').inner_text()
        # Both trees start fully lit; clicking a node turns one OFF.
        assert lit_summary != before_summary, (before_summary[:60], lit_summary[:60])
        # The breakdown lives in a collapsed <details> to keep the right
        # column readable, so expand it before reading its text.
        page.locator('.panel-aside-fold').first.evaluate('e=>{e.open=true}')
        assert page.locator('#panel-steps').inner_text().find('星辰') >= 0
        print('talent node toggled:', ' / '.join(after_talent))
        # Level selector on multi-level nodes.
        level_select = page.locator('[data-talent-level]').first
        if level_select.count():
            level_select.select_option('1')
            assert page.locator('.panel-total-grid strong').all_inner_texts(), 'level select broke the panel'
        attr_node = page.locator('.panel-talent-node:not(.is-utility) [data-talent-node]').first
        attr_node.click()
        assert page.locator('.panel-total-grid strong').all_inner_texts() == before_talent, 'talent node did not toggle back'
        page.locator('[data-path="talentAdjust.0"]').fill('100')
        assert page.locator('.panel-total-grid strong').all_inner_texts() != before_talent
        page.locator('[data-path="talentAdjust.0"]').fill('0')

        # Searchable weapon / offhand / tarot selectors.
        for path, keyword in (('weapon.id', ''), ('offhand.id', ''), ('charm.id', '')):
            field = page.locator(f'[data-combo="{path}"]')
            field.click()
            assert field.get_attribute('aria-expanded') == 'true', path + ' list did not open'
            count = page.locator(f'[data-combo="{path}"] ~ .panel-combo-list [data-combo-value]').count()
            assert count > 0, path + ' has no options'
            if keyword:
                field.fill(keyword)
            option = page.locator(f'[data-combo="{path}"] ~ .panel-combo-list [data-combo-value]').last
            label = option.inner_text()
            option.click()
            assert field.input_value() == label, path + ' selection not reflected'
            print(f'combo {path}: {count} options, picked {label[:24]}')

        # Weapons must be filtered by the character's weapon type; offhand is common only.
        weapon_ids = page.evaluate("""()=>{
          const P=window.WIKI_PANEL_DATA;
          const char=P.characters.find(c=>c.key===document.querySelector('.panel-character strong').textContent.trim());
          const allowed=(char?.weaponTypes||[]).map(Number).filter(t=>t!==2);
          return [allowed, P.weapons.filter(w=>allowed.includes(Number(w.typeId))).map(w=>String(w.id))];
        }""")
        weapon_value = page.locator('[data-path="weapon.id"]').input_value()
        assert weapon_value in weapon_ids[1], (weapon_value, weapon_ids[0], weapon_ids[1][:5])
        print('weapon restricted to character types', weapon_ids[0], ':', weapon_value)
        offhand_ids = page.evaluate("""()=>{
          const P=window.WIKI_PANEL_DATA;
          return P.weapons.filter(w=>Number(w.typeId)===2).map(w=>String(w.id));
        }""")
        offhand_value = page.locator('[data-path="offhand.id"]').input_value()
        assert offhand_value in offhand_ids, (offhand_value, offhand_ids[:5])
        print('offhand restricted to common offhand type:', offhand_value)

        # Shared character picker.
        page.locator('[data-tool="pick-character"]').click()
        page.locator('.char-picker').wait_for()
        assert page.locator('.char-picker-card').count() > 20, 'picker did not list characters'
        page.locator('.char-picker-search').fill('贝拉')
        page.wait_for_timeout(120)
        hits = page.locator('.char-picker-card', has_text='贝拉')
        assert 0 < hits.count() < 20, 'picker search did not filter'
        name = hits.first.locator('strong').inner_text()
        hits.first.click()
        page.locator('.char-picker').wait_for(state='detached')
        swapped = page.locator('.panel-total-grid strong').all_inner_texts()
        assert swapped, 'character switch broke the calculator'
        norm = lambda s: s.replace('·', '-').replace('•', '-').replace('‧', '-').replace('・', '-')
        assert norm(name) == norm(page.locator('.panel-character strong').inner_text()), (name, page.locator('.panel-character strong').inner_text())
        print('shared picker picked', name, '->', ' / '.join(swapped))

        page.locator('.preset-card').evaluate('e=>{e.open=true}')
        page.locator('#panel-preset-name').fill('probe')
        page.locator('[data-tool="save-panel"]').click()
        assert page.locator('[data-panel-preset]').count() == 1, 'preset not saved'
        print('preset save: ok')

        # Character detail tabs: only core wiki tabs remain after the extra
        # pixel-animation / expression assets were removed.
        # Character detail lives at #/page/<id>; pick the first character id
        # from the offline index so the detail tabs exist.
        import json as _json
        _raw = (ROOT / 'data' / 'index.js').read_text('utf8')
        _pages = _json.JSONDecoder().raw_decode(_raw[_raw.index('=') + 1:])[0]['pages']
        cid = next((x['id'] for x in _pages if x.get('type') == 'character' and not x.get('redirect')), None)
        assert cid, 'no character page in the offline index'
        page.goto(BASE + '#/page/' + str(cid))
        page.locator('[data-detail-tab]').first.wait_for()
        tabs = page.locator('[data-detail-tab]').all_inner_texts()
        assert '档案总览' in tabs and '技能与成长' in tabs and '角色故事' in tabs, tabs
        assert '像素动作' not in tabs and '立绘表情' not in tabs, tabs
        print('core detail tabs:', tabs)
        page.locator('[data-detail-tab="skills"]').click()
        page.locator('#detail-body').wait_for()
        assert page.locator('#detail-body').inner_text(), 'skills tab empty'
        print('skills tab: ok')

        assert not errors, '; '.join(errors[:3])
        assert not failed, '; '.join(failed[:3])
        browser.close()
    print('ALL PASS')


if __name__ == '__main__':
    main()
