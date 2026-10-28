"""Offline regressions for portraits, source-order sprites and complete trait comparisons."""
from collections import Counter
from pathlib import Path
import json
import re
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from verify import load_assignment

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'test-results'
DATA = load_assignment(ROOT / 'data/index.js')
UNITS = {x['id']: x for x in DATA['pages'] if x['type']=='character' and not x.get('redirect')}


def text(source):
    return re.sub(r'\s+', '', BeautifulSoup(source, 'html.parser').get_text())


def audit_data():
    source = json.loads((ROOT/'data/raw/pages/968.json').read_text(encoding='utf-8'))['parse']['text']
    if isinstance(source, dict): source=source['*']
    expected=[]
    for a in BeautifulSoup(source, 'html.parser').select('a[title]'):
        pid=DATA['titles'].get(a['title'])
        if pid in UNITS and pid not in expected: expected.append(pid)
    expected += sorted(set(UNITS)-set(expected))
    actual=[p['id'] for p in sorted(UNITS.values(),key=lambda p:p['sourceOrder'])]
    assert actual==expected, (actual[:5],expected[:5])
    assert [UNITS[i]['name'] for i in actual[:3]]==['君士坦丁','薇佩拉','列奥尼德•寒锋血誓']
    for p in UNITS.values():
        for name in ('sprite','professionIcon'):
            if p.get(name):assert (ROOT/p[name]).is_file(),(p['name'],name)
        assert len({a['src'] for a in p['portraits']})==len(p['portraits'])
        for art in p['portraits']:assert (ROOT/art['src']).is_file(),(p['name'],art)
    count=0
    for path in (ROOT/'data/pages').glob('*.js'):
        doc=load_assignment(path)
        comparison=doc.get('starComparison')
        if not comparison:continue
        count+=1
        assert len(comparison['levels'])==5
        for level in comparison['levels']:
            original=doc['fields'].get(comparison['prefix']+str(level['star']),'')
            assert level['available']==bool(text(original)),path
            if level['available']:
                assert Counter(text(comparison['common']+level['html']))==Counter(text(original)),(path,level['star'])
    assert count>100,count
    return expected,count


def run():
    expected,count=audit_data()
    reports=[f'All {len(UNITS)} catalog entries follow the original BWIKI order; all new images exist',
             f'All five levels of {count} traits preserve every source character after separating common effects']
    errors=[];remote=[];failed=[]
    with sync_playwright() as p:
        browser=p.chromium.launch()
        context=browser.new_context(offline=True,viewport={'width':1440,'height':1050})
        page=context.new_page()
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:remote.append(r.url) if r.url.startswith(('http:','https:')) else None)
        page.on('requestfailed',lambda r:failed.append(r.url))
        base=(ROOT/'index.html').as_uri()
        def route(fragment,ready):
            page.goto(base+fragment)
            page.locator(ready).first.wait_for()
            page.locator('.loading').wait_for(state='hidden')
        def ids():
            return page.locator('#catalog-results [data-character-id]').evaluate_all('(es)=>es.map(e=>Number(e.dataset.characterId))')
        def fit(label):
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),label
        def shot(name,selector=None):
            page.evaluate('''async()=>{document.activeElement?.blur();await Promise.all([...document.images].filter(i=>i.getAttribute('src')&&i.getBoundingClientRect().top<innerHeight).map(i=>{i.loading='eager';return i.decode().catch(()=>{})}));await new Promise(requestAnimationFrame)}''')
            if selector:page.locator(selector).screenshot(path=str(OUT/(name+'.png')),animations='disabled',style='.topbar{visibility:hidden!important}')
            else:page.screenshot(path=str(OUT/(name+'.png')),animations='disabled')
        route('#/characters','.sprite-card')
        assert page.locator('#catalog-sort').input_value()=='source'
        assert ids()==expected[:24]
        assert page.locator('[data-view="grid"]').get_attribute('aria-pressed')=='true'
        assert page.locator('.catalog-tools > .filter-row').count()==3
        assert page.locator('.catalog-tools > [data-action="reset-filters"]').count()==1
        for item in page.locator('.sprite-card').all():
            pid=int(item.get_attribute('data-character-id'))
            assert item.locator('.portrait-wrap img').get_attribute('src')==UNITS[pid]['sprite']
        shot('characters-sprite-desktop')
        # Every page must follow the source, including the transition to non-legendary units.
        collected=ids()
        for n in range(2,(len(expected)+23)//24+1):
            page.locator(f'[data-catalog-page="{n}"]').first.click()
            collected+=ids()
        assert collected==expected
        page.locator('[data-catalog-page="1"]').first.click()
        page.locator('[data-view="list"]').click()
        assert ids()==expected[:24]
        assert page.locator('.unit-table th').count()==13
        for row in page.locator('.unit-table tbody tr').all():
            unit=UNITS[int(row.get_attribute('data-character-id'))]
            assert row.locator('.unit-stat').all_text_contents()==[unit['stats'].get(s) or '—' for s in ('生命','物攻','魔攻','物防','魔防','敏捷')]
        page.locator('[data-unit-sort="stat:物攻"]').click()
        vals=[float(UNITS[i]['stats']['物攻']) for i in ids()]
        assert vals==sorted(vals,reverse=True)
        assert vals[0]==max(float(u['stats']['物攻']) for u in UNITS.values() if str(u['stats'].get('物攻','')).isdigit())
        assert page.locator('[data-unit-sort="stat:物攻"]').locator('..').get_attribute('aria-sort')=='descending'
        page.locator('[data-unit-sort="stat:物攻"]').click()
        vals=[float(UNITS[i]['stats']['物攻']) for i in ids()]
        assert vals==sorted(vals)
        page.locator('#catalog-sort').select_option('source')
        first=expected[0]
        page.locator(f'.unit-actions [data-favorite="{first}"]').click()
        assert page.locator(f'.unit-actions [data-favorite="{first}"]').get_attribute('aria-pressed')=='true'
        page.locator(f'.unit-actions [data-compare="{first}"]').click()
        assert page.locator(f'.unit-actions [data-compare="{first}"]').get_attribute('aria-pressed')=='true'
        page.locator('[data-filter="rarity"][data-value="史诗"]').click()
        filtered=ids()
        assert filtered and all(UNITS[i]['rarity']=='史诗' for i in filtered)
        page.locator('[data-view="grid"]').click();assert ids()==filtered
        page.locator('[data-view="list"]').click();assert ids()==filtered
        page.locator('[data-action="reset-filters"]').click()
        page.locator(f'.unit-actions [data-compare="{first}"]').click()
        page.locator('.catalog-toolbar').scroll_into_view_if_needed()
        shot('characters-units-desktop')
        reports.append('Sprite default, complete source-order pagination, full unit stats, numeric sorting, favorites and shared filters work')
        for name in ('薇佩拉','歌洛莉亚','贝拉'):
            pid=DATA['titles']['角色图鉴库/'+name];unit=UNITS[pid]
            route('#/page/'+str(pid),'.portrait-variants')
            assert page.locator('.portrait-stage img').get_attribute('src')==unit['portraits'][0]['src']
            assert page.locator('[data-trait-star]').count()==5
            for art in unit['portraits']:
                button=page.locator(f'[data-portrait="{art["key"]}"]')
                button.focus();page.keyboard.press('Enter')
                assert page.locator('.portrait-stage img').get_attribute('src')==art['src']
                assert button.get_attribute('aria-pressed')=='true'
                page.locator('.portrait-stage').click()
                assert page.locator('#image-dialog').is_visible()
                assert page.locator('#lightbox-image').get_attribute('src')==art['src']
                page.keyboard.press('Escape')
            page.locator('[data-portrait="awakened"]').click()
            page.locator('[data-level="base"]').click()
            assert page.locator('[data-portrait="awakened"]').get_attribute('aria-pressed')=='true'
            page.locator('[data-level="max"]').click()
        reports.append('Base, awakened and archived skin art switch by button/keyboard, zoom locally and survive stat changes')
        route('#/page/9295','.portrait-unavailable')
        assert page.locator('.profile-gallery img').count()==0
        assert page.locator('[data-portrait]').count()==0
        gloria=DATA['titles']['角色图鉴库/歌洛莉亚']
        route('#/page/'+str(gloria),'[data-trait-star="5"]')
        assert '圣枪技•扬旗' in page.locator('.trait-common').inner_text()
        assert '20%' in page.locator('[data-trait-star="5"]').inner_text()
        assert '50%' in page.locator('[data-trait-star="5"] .star-change').all_text_contents()
        assert page.locator('.trait-common [data-source-color]').count()>0
        page.locator('[data-trait-mode="single"]').click()
        for n in range(1,6):
            page.locator(f'[data-star="{n}"]').click()
            assert '圣枪技•扬旗' in page.locator('.trait-single').inner_text()
        page.locator('[data-trait-mode="compare"]').click()
        assert page.locator('[data-trait-star]').count()==5
        shot('character-traits-desktop','.personality-card')
        page.locator('#personality-content>a.text-link').click()
        page.locator('.ability-card [data-trait-star="5"]').wait_for()
        assert '圣枪技•扬旗' in page.locator('.trait-common').inner_text()
        route('#/page/'+str(DATA['titles']['角色图鉴库/薇佩拉']),'[data-trait-star="5"]')
        assert page.locator('.trait-common .term-link').count()>0
        destination=page.locator('.trait-common .term-link').first.get_attribute('href')
        page.locator('.trait-common .term-link').first.click()
        page.wait_for_url('**'+destination)
        page.locator('.detail-heading').wait_for()
        assert page.url.endswith(destination)
        reports.append('Common effect plus five star texts, highlighted changes, full single-star descriptions and offline term links work')
        for theme in ('light','dark'):
            if theme=='dark':page.locator('[data-action="theme"]').click()
            for width in (1440,1024,768,390,320):
                page.set_viewport_size({'width':width,'height':1000})
                route('#/page/'+str(gloria),'[data-trait-star="5"]')
                fit((theme,width,'portrait and traits'))
                stage=page.locator('.portrait-stage').bounding_box()
                buttons=page.locator('.portrait-variants').bounding_box()
                assert stage['y']+stage['height']<=buttons['y']+1
                assert page.locator('[data-portrait="awakened"]').is_visible()
                page.locator('[data-portrait="awakened"]').click()
                if width==1440:shot('character-gallery-'+theme)
                if width==390:
                    shot('character-gallery-mobile-'+theme)
                    shot('character-traits-mobile-'+theme,'.personality-card')
                route('#/characters','#catalog-results')
                for view in ('grid','list'):
                    page.locator(f'[data-view="{view}"]').click()
                    assert page.locator(f'[data-view="{view}"]').is_visible()
                    fit((theme,width,view))
                    if view=='list':
                        scrolled=page.locator('.unit-table-wrap').evaluate('(e)=>{e.scrollLeft=400;return e.scrollLeft}')
                        assert scrolled>0
                    if width==390:
                        page.locator('.catalog-toolbar').scroll_into_view_if_needed()
                        shot('characters-'+view+'-mobile-'+theme)
        reports.append('Portraits, five-star comparison and both atlas modes fit 320–1440px in light/dark themes; mobile view switch and table scrolling remain usable')
        assert not errors,errors
        assert not remote,remote
        assert not failed,failed
        browser.close()
    result={'status':'passed','reports':reports,'network':'disabled','errors':errors,'failedAssets':failed}
    (OUT/'character-gallery-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    for report in reports:print('PASS '+report,flush=True)
    print('PASS no JavaScript errors, missing local files or remote requests',flush=True)


if __name__=='__main__':run()
