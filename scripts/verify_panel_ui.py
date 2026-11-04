"""Browser smoke check for the panel calculator and the new sprite/face tabs."""
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

        other = page.locator('[data-path="character"] option').nth(1).get_attribute('value')
        page.locator('[data-path="character"]').select_option(other)
        page.locator('#panel-output .panel-total-grid').wait_for()
        swapped = page.locator('.panel-total-grid strong').all_inner_texts()
        assert swapped, 'character switch broke the calculator'
        print('after char swap:', ' / '.join(swapped))

        page.locator('#panel-preset-name').fill('probe')
        page.locator('[data-tool="save-panel"]').click()
        assert page.locator('[data-panel-preset]').count() == 1, 'preset not saved'
        print('preset save: ok')

        # Character detail tabs added for sprite actions and portrait expressions.
        page.goto(BASE + '#/page/2165')
        page.locator('.detail-heading').wait_for()
        page.locator('[data-detail-tab="anim"]').click()
        page.locator('.sprite-lab').wait_for()
        print('sprite lab html len:', page.locator('.sprite-lab').evaluate('(e)=>e.innerHTML.length'))
        print('strip imgs:', page.locator('.sprite-strip img').count(), 'frame:', page.locator('.sprite-frame').count())
        print('sprite keys:', page.evaluate("()=>Object.keys(window.WIKI_SPRITES||{}).filter(k=>k.includes('艾达'))"))
        print('detail body:', page.locator('#detail-body').inner_text()[:160].replace('\n', ' | '))
        frames = page.locator('.sprite-strip img')
        assert frames.count() > 0, 'no sprite frames rendered'
        print('anim tab frames:', frames.count())
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
        print('faces tab images:', faces.count())
        page.locator('.face-item').first.click()
        page.locator('#image-dialog').wait_for(state='visible')
        print('expression lightbox: ok')
        page.keyboard.press('Escape')

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
