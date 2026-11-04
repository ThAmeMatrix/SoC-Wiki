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
        assert len(totals) == 5, totals
        print('panel default totals:', ' / '.join(totals))
        expected = page.evaluate("()=>{const P=window.WIKI_PANEL_DATA,C=window.WikiPanelCalc;return C.calculate(C.defaults(P),P).total.map(String)}")
        assert [t.replace(',', '') for t in totals] == expected, (totals, expected)
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

        # Per-rank skill-line branches.
        rank_buttons = page.locator('[data-line-rank]')
        assert rank_buttons.count() >= 4, 'skill-line rank buttons missing'
        before_lines = page.locator('.panel-total-grid strong').all_inner_texts()
        page.locator('[data-line-rank="1"][data-line-pick="right"]').click()
        after_lines = page.locator('.panel-total-grid strong').all_inner_texts()
        assert after_lines != before_lines, 'per-rank skill-line pick had no effect'
        print('skill-line pick:', ' / '.join(before_lines), '->', ' / '.join(after_lines))

        # Both talent trees.
        assert page.locator('[data-path="talent.star"]').count() == 1
        assert page.locator('[data-path="talent.pioneer"]').count() == 1
        before_talent = page.locator('.panel-total-grid strong').all_inner_texts()
        page.locator('[data-path="talent.star"]').select_option('1')
        after_talent = page.locator('.panel-total-grid strong').all_inner_texts()
        assert after_talent != before_talent, 'talent level had no effect'
        assert page.locator('#panel-steps').inner_text().find('星辰') >= 0
        print('talent Lv.1  :', ' / '.join(after_talent))
        page.locator('[data-path="talentAdjust.0"]').fill('100')
        assert page.locator('.panel-total-grid strong').all_inner_texts() != after_talent
        page.locator('[data-path="talent.star"]').select_option('0')
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

        page.locator('#panel-preset-name').fill('probe')
        page.locator('[data-tool="save-panel"]').click()
        assert page.locator('[data-panel-preset]').count() == 1, 'preset not saved'
        print('preset save: ok')

        # Character detail tabs: full-colour sprites and portrait expressions.
        page.goto(BASE + '#/page/2165')
        page.locator('.detail-heading').wait_for()
        page.locator('[data-detail-tab="anim"]').click()
        page.locator('.sprite-lab').wait_for()
        frames = page.locator('.sprite-strip img')
        assert frames.count() > 0, 'no sprite frames rendered'
        print('anim tab frames:', frames.count())
        colour = page.locator('[data-sprite-colour="color"]')
        mask = page.locator('[data-sprite-colour="mask"]')
        assert colour.count() == 1 and not colour.is_disabled(), 'full-colour option missing'
        assert '/color/' in colour.evaluate('(e)=>e.closest(".sprite-lab").querySelector(".sprite-frame").src'), 'default is not full colour'
        mask.click()
        assert '/color/' not in page.locator('.sprite-frame').get_attribute('src'), 'mask switch failed'
        colour.click()
        assert '/color/' in page.locator('.sprite-frame').get_attribute('src'), 'colour switch failed'
        print('full-colour / mask toggle: ok')
        page.locator('.sprite-nav-btn').nth(1).click()
        assert page.locator('.sprite-strip img').count() > 0, 'action switch lost frames'
        page.locator('[data-sprite-facing="front"]').click()
        page.locator('[data-sprite-mirror]').click()
        assert page.locator('[data-sprite-mirror]').get_attribute('aria-pressed') == 'true'
        page.locator('[data-sprite-speed="1.8"]').click()
        page.locator('.sprite-strip img').nth(1).click()
        assert page.locator('[data-sprite-play]').inner_text() == '播放', 'frame click should pause'
        page.locator('[data-sprite-play]').click()
        assert page.locator('[data-sprite-play]').inner_text() == '暂停', 'play button should resume'
        print('anim interactions: ok')

        page.locator('[data-detail-tab="faces"]').click()
        page.locator('.face-grid').wait_for()
        faces = page.locator('.face-item img')
        assert faces.count() > 0, 'no expression images'
        page.wait_for_function("()=>[...document.querySelectorAll('.face-item img')].every(i=>i.complete)")
        broken = page.evaluate("()=>[...document.querySelectorAll('.face-item:not([hidden]) img')].filter(i=>i.naturalWidth===0).map(i=>i.getAttribute('src'))")
        assert not broken, 'broken expression images: ' + repr(broken[:5])
        forms = page.locator('.face-item img[alt^="立绘形态"]')
        print('faces tab images:', faces.count(), 'form cards:', forms.count())
        faces.first.click()
        page.locator('#image-dialog').wait_for(state='visible')
        print('expression lightbox: ok')
        page.keyboard.press('Escape')

        # A character with portrait form sheets: all of them must now resolve.
        page.goto(BASE + '#/page/8592')       # 贝拉•魔术师
        page.locator('.detail-heading').wait_for()
        page.locator('[data-detail-tab="faces"]').click()
        page.locator('.face-grid').first.wait_for()
        form_imgs = page.locator('.face-item img[alt^="立绘形态"]')
        assert form_imgs.count() > 0, 'no portrait form sheets rendered'
        page.wait_for_function("()=>[...document.querySelectorAll('.face-item img[alt^=\"立绘形态\"]')].every(i=>i.complete)")
        form_broken = page.evaluate("()=>[...document.querySelectorAll('.face-item:not([hidden]) img[alt^=\"立绘形态\"]')].filter(i=>i.naturalWidth===0).map(i=>i.getAttribute('src'))")
        assert not form_broken, 'broken portrait form sheets: ' + repr(form_broken[:5])
        print('portrait form sheets:', form_imgs.count(), 'all loaded')

        # The infographic workshop shares the same character picker.
        page.goto(BASE + '#/tools/infographic')
        page.locator('[data-ig-pick="character"]').first.wait_for()
        page.locator('[data-ig-pick="character"]').first.click()
        page.locator('.char-picker').wait_for()
        assert page.locator('.char-picker-card').count() > 20, 'shared picker empty in workshop'
        page.locator('.char-picker-search').fill('贝拉')
        page.wait_for_timeout(120)
        assert page.locator('.char-picker-card').count() < 20, 'shared picker search failed in workshop'
        page.keyboard.press('Escape')
        page.locator('.char-picker').wait_for(state='detached')
        print('infographic shared picker: ok')

        print('\npage/console errors:', len(errors))
        for e in errors[:8]:
            print('  ', e[:200])
        print('failed requests:', len(failed))
        for f in failed[:8]:
            print('  ', f[-120:])
        print('bad responses:', len(bad_status))
        for s, u in bad_status[:8]:
            print('  ', s, u[-120:])
        browser.close()
    assert not errors, 'page or console errors'
    assert not failed, 'failed requests'
    assert not bad_status, 'missing local files'
    print('\nALL PASS')


if __name__ == '__main__':
    main()
