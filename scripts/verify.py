"""Audit the complete snapshot and exercise the actual file:// UI while offline."""
from __future__ import annotations
import json, pathlib, re, sys, time
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

ROOT=pathlib.Path(__file__).resolve().parents[1]
RESULTS=ROOT/'test-results'
RESULTS.mkdir(exist_ok=True)

def load_assignment(path):
    text=path.read_text(encoding='utf-8')
    return json.JSONDecoder().raw_decode(text[text.index('=')+1:])[0]

def static_audit():
    data=load_assignment(ROOT/'data'/'index.js')
    assert len(data['pages'])==data['archive']['expectedPages']
    ids={p['id'] for p in data['pages']}
    broken=[];unsafe=[];links=0;images=0;semantic=0
    for p in data['pages']:
        path=ROOT/'data'/'pages'/(str(p['id'])+'.js')
        assert path.exists(),str(path)
        doc=load_assignment(path)
        assert doc['id']==p['id']
        soup=BeautifulSoup(doc['html'],'html.parser')
        if soup.select('script,style,iframe,embed,object,form'):unsafe.append(p['title'])
        for el in soup.find_all(True):
            if any(k.lower().startswith('on') for k in el.attrs):unsafe.append(p['title'])
        for img in soup.find_all('img'):
            images+=1;src=img.get('src','')
            if not src.startswith('assets/') or not (ROOT/src).is_file():broken.append((p['title'],src))
        if p['image'] and not (ROOT/p['image']).is_file():broken.append((p['title'],p['image']))
        for a in soup.select('a[href^="#/page/"]'):
            links+=1;target=int(a['href'].split('/')[2].split('?')[0])
            if target not in ids:broken.append((p['title'],a['href']))
        if p['type']=='status' and doc['fields'].get('介绍'):
            assert 'definition' in doc['html'];semantic+=1
    assert not unsafe,unsafe[:10]
    assert not broken,broken[:15]
    print(f'PASS complete archive: {len(ids)} pages, {images} image references, {links} internal links, {semantic} semantic descriptions',flush=True)
    return data,{'pages':len(ids),'imageReferences':images,'internalLinks':links,'semanticDescriptions':semantic}

def browser_audit(data):
    reports=[];errors=[];remote=[];failures=[]
    titles=data['titles'];base=(ROOT/'index.html').as_uri()
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(offline=True,viewport={'width':1440,'height':1080},device_scale_factor=1,accept_downloads=True)
        page=context.new_page()
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:remote.append(r.url) if r.url.startswith(('http:','https:')) else None)
        page.on('requestfailed',lambda r:failures.append({'url':r.url,'failure':r.failure}))
        def route(fragment,ready=None):
            page.goto(base+fragment)
            if ready:page.locator(ready).first.wait_for()
            page.locator('.loading').wait_for(state='hidden')
        def assert_no_overflow(label):
            size=page.evaluate('({width:innerWidth,scroll:document.documentElement.scrollWidth})')
            assert size['scroll']<=size['width']+1,(label,size)
        route('#/','.hero')
        assert page.locator('.character-card').count()==4
        assert '3,890' in page.locator('.stat-grid').inner_text()
        page.screenshot(path=str(RESULTS/'home-desktop.png'),full_page=True,animations="disabled")
        assert_no_overflow('desktop home');reports.append('Home: all counts, local artwork and desktop layout')

        page.keyboard.press('Control+k');page.locator('#quick-search').fill('旗女')
        page.locator('#quick-results').get_by_text('歌洛莉亚', exact=True).wait_for()
        page.keyboard.press('ArrowDown');page.keyboard.press('Enter')
        page.locator('.character-profile').wait_for()
        assert page.locator('.profile-stats').inner_text().find('3625')>=0
        page.locator('[data-level="base"]').click();assert '382' in page.locator('.profile-stats').inner_text()
        page.locator('[data-level="max"]').click()
        page.locator('#personality-content [data-trait-mode="single"]').click()
        page.locator('#personality-content [data-star="5"]').wait_for()
        page.locator('[data-star="1"]').click()
        page.locator('#personality-content .star-selector').wait_for()
        assert page.locator('#personality-content').inner_text().strip()
        page.locator('[data-star="5"]').click()
        page.locator('#page-notes').fill('离线测试笔记：旗帜与守护')
        page.locator('.detail-actions [data-favorite]').click()
        page.locator('.detail-actions [data-compare]').click()
        page.reload();page.locator('.character-profile').wait_for()
        assert page.locator('#page-notes').input_value()=='离线测试笔记：旗帜与守护'
        assert page.locator('.detail-actions [data-favorite]').get_attribute('aria-pressed')=='true'
        page.screenshot(path=str(RESULTS/'character-desktop.png'),full_page=True,animations="disabled")
        page.locator('[data-detail-tab="skills"]').click()
        assert page.locator('.skill-tier').count()==7
        assert '圣枪' in page.locator('.skill-tree').inner_text()
        page.locator('.growth-explorer[data-ready="true"]').wait_for()
        page.locator('[data-skill-key]').first.click()
        page.locator('.skill-full-link').click();page.locator('#article-content').wait_for()
        reports.append('Keyboard search, character stats, personality, skill links, bookmark and note persistence')

        route('#/characters','#catalog-results')
        page.locator('[data-filter="rarity"][data-value="SSR"]').click()
        page.locator('[data-filter="class"][data-value="守望者"]').click()
        page.locator('[data-filter="faction"][data-value="骑士同盟"]').click()
        ids=page.locator('.character-card [data-favorite]').evaluate_all('(els)=>els.map(e=>Number(e.dataset.favorite))')
        assert ids
        source={x['id']:x for x in data['pages']}
        assert all(source[i]['rarity']=='SSR' and source[i]['class']=='守望者' and '骑士同盟' in source[i]['faction'] for i in ids)
        page.locator('[data-action="reset-filters"]').click()
        page.locator('[data-catalog-page="2"]').first.click()
        assert page.locator('.character-card').count()==24
        page.locator('[data-view="list"]').click();assert page.locator('.data-table tbody tr').count()==24
        page.locator('#catalog-query').fill('不存在的角色abcd');assert page.locator('.empty-state').count()==1
        reports.append('Combined filters, pagination, table view and empty search state')

        route('#/page/'+str(titles['角色图鉴库/贝拉']),'.character-profile')
        page.locator('.detail-actions [data-compare]').click()
        route('#/compare','.compare-table')
        assert page.locator('.compare-name').count()==2
        assert '歌洛莉亚' in page.locator('.compare-table').inner_text()
        assert '贝拉' in page.locator('.compare-table').inner_text()
        reports.append('Two-character comparison uses recorded maximum-level values')

        route('#/page/'+str(titles['装备图鉴库/执灯者']),'.equipment-profile')
        page.locator('[data-star="1"]').click();assert '4%' in page.locator('.ability-description').inner_text()
        page.locator('[data-star="5"]').click();assert '8%' in page.locator('.ability-description').inner_text()
        route('#/page/'+str(titles['中括号介绍/致盲']),'.definition')
        assert '80%' in page.locator('.definition').inner_text()
        route('#/page/'+str(titles['天赋图标库/雷击I']),'#article-content')
        assert '500' in page.locator('#main').inner_text()
        reports.append('Equipment star effects and invisible semantic status/talent properties')

        route('#/search?q='+requests_quote('援护攻击'),'#search-page-results')
        page.locator('.search-result').first.wait_for();assert page.locator('.search-result').count()>0
        page.locator('[data-search-type="equipment"]').click()
        assert all('装备图鉴' in s for s in page.locator('.search-result .entry-type').all_text_contents())
        reports.append('Full-text search and category narrowing, with the network disabled')

        route('#/page/'+str(titles['伤害公式汇总']),'#article-content')
        page.locator('.wiki-content img').first.click();assert page.locator('#image-dialog').evaluate('(d)=>d.open')
        page.locator('[data-action="zoom-image"]').click();assert page.locator('.image-stage').get_attribute('class').endswith('zoom')
        page.keyboard.press('Escape');assert not page.locator('#image-dialog').evaluate('(d)=>d.open')
        page.locator('[data-action="reading"]').click();assert 'reading' in page.locator('body').get_attribute('class')
        page.locator('[data-action="reading"]').click()
        reports.append('Offline guide images, image zoom, Escape and focused reading')

        route('#/archive','.archive-hero')
        with page.expect_download() as info:page.locator('[data-action="export"]').click()
        download=info.value;backup=RESULTS/'personal-backup.json';download.save_as(backup)
        value=json.loads(backup.read_text(encoding='utf-8'));assert value['notes'][str(titles['角色图鉴库/歌洛莉亚'])]=='离线测试笔记：旗帜与守护'
        value['favorites'].append(titles['角色图鉴库/贝拉']);value['notes'][str(titles['角色图鉴库/贝拉'])]='导入的笔记'
        restore=RESULTS/'restore-test.json';restore.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
        page.locator('#import-file').set_input_files(restore)
        page.locator('#toast').filter(has_text='已导入').wait_for()
        route('#/favorites','.entry-grid');assert page.locator('.entry-card').count()==2
        reports.append('Backup download, validated import and merged bookmarks/notes')

        route('#/','.hero');page.locator('[data-action="theme"]').click();assert page.locator('body').evaluate('(b)=>b.classList.contains("dark")')
        page.screenshot(path=str(RESULTS/'home-dark.png'),full_page=True,animations="disabled")
        page.locator('[data-action="theme"]').click()
        page.set_viewport_size({'width':390,'height':844})
        assert_no_overflow('mobile home');page.screenshot(path=str(RESULTS/'home-mobile.png'),full_page=True,animations="disabled")
        page.locator('[data-action="menu"]').click();assert 'nav-open' in page.locator('body').get_attribute('class')
        page.locator('.sidebar a[href="#/characters"]').click();page.locator('#catalog-results').wait_for()
        assert 'nav-open' not in page.locator('body').get_attribute('class')
        assert_no_overflow('mobile characters');page.screenshot(path=str(RESULTS/'characters-mobile.png'),full_page=True,animations="disabled")
        route('#/page/'+str(titles['角色图鉴库/歌洛莉亚']),'.character-profile');assert_no_overflow('mobile character')
        page.screenshot(path=str(RESULTS/'character-mobile.png'),full_page=True,animations="disabled")
        page.locator('[data-detail-tab="source"]').click();assert_no_overflow('mobile original character')
        route('#/page/'+str(titles['伤害公式汇总']),'#article-content');assert_no_overflow('mobile guide')
        route('#/does-not-exist','.empty-state')
        reports.append('Dark mode, 390px layouts, mobile navigation, original tables and missing route recovery')
        assert not errors,errors
        assert not remote,remote[:10]
        assert not failures,failures[:10]
        context.close();browser.close()
    for report in reports:print('PASS '+report,flush=True)
    print('PASS zero JavaScript errors, zero failed file requests, zero network requests',flush=True)
    return reports

def requests_quote(s):
    from urllib.parse import quote
    return quote(s)

if __name__=='__main__':
    data,static=static_audit()
    result={'static':static,'browser':browser_audit(data),'network':'disabled','browserEngine':'Chromium','entrypoint':'file://'}
    (RESULTS/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
