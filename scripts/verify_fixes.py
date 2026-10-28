"""Regression checks for source colors, responsive layouts and real offline tools."""
from __future__ import annotations
import json,pathlib
from playwright.sync_api import sync_playwright
from verify import load_assignment

ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'test-results';OUT.mkdir(exist_ok=True)
data=load_assignment(ROOT/'data/index.js')
titles=data['titles']
character=load_assignment(ROOT/'data/pages/9296.js')
personality=titles['个性/'+character['rawFields']['个性']]
reports=[];errors=[];remote=[];failed=[]

def run():
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(offline=True,viewport={'width':1440,'height':1000},accept_downloads=True)
        page=context.new_page()
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:remote.append(r.url) if r.url.startswith(('http:','https:')) else None)
        page.on('requestfailed',lambda r:failed.append(r.url))
        base=(ROOT/'index.html').as_uri()
        def route(fragment,ready):
            page.goto(base+fragment);page.locator(ready).first.wait_for();page.locator('.loading').wait_for(state='hidden')
        def overflow(name):
            size=page.evaluate('({w:innerWidth,s:document.documentElement.scrollWidth})')
            assert size['s']<=size['w']+1,(name,size)
        def shot(name,full=False):
            page.evaluate('''()=>{document.documentElement.style.scrollBehavior='auto';document.activeElement?.blur();scrollTo({top:0,behavior:'instant'});for(const i of document.images){const r=i.getBoundingClientRect();if(r.top<innerHeight&&r.bottom>0)i.loading='eager';}}''')
            page.wait_for_function('''()=>[...document.images].every(i=>{const r=i.getBoundingClientRect();return r.top>=innerHeight||r.bottom<=0||i.complete})''',timeout=10000)
            page.screenshot(path=str(OUT/(name+'.png')),full_page=full,animations='disabled')
        def colored(selector):
            colors=page.locator(selector).evaluate_all('(els)=>els.map(e=>({text:e.textContent,color:getComputedStyle(e).color,parent:getComputedStyle(e.parentElement).color}))')
            assert colors,selector
            assert any(c['color']!=c['parent'] for c in colors),colors

        route('#/page/9346','#article-content')
        colored('.ability-description [data-source-color]')
        assert page.locator('.ability-description .wiki-color-orange').count()==3
        assert page.locator('.source-details').get_attribute('open') is None
        assert '薇佩拉' in page.locator('.related-characters').inner_text()
        shot('fix-skill-desktop');overflow('skill desktop')
        page.locator('.source-details summary').click()
        img=page.locator('.wiki-content .jndtb').first.bounding_box();assert img['width']<=80.1,img
        page.locator('[data-action="theme"]').click();colored('.ability-description [data-source-color]');shot('fix-skill-dark')
        page.locator('[data-action="theme"]').click()
        page.locator('.ability-description .term-link').click();page.locator('.definition').wait_for()
        assert '虔诚' in page.locator('#main').inner_text()
        route('#/page/'+str(personality),'.ability-card')
        page.locator('[data-trait-mode="single"]').click()
        for n in (1,5):
            page.locator(f'[data-star="{n}"]').click();colored('.ability-description [data-source-color]')
        shot('fix-personality-desktop')
        route('#/page/9296','.character-profile')
        page.locator('#personality-content [data-source-color]').first.wait_for()
        colored('#personality-content [data-source-color]')
        reports.append('Source colors retained in skill, personality and character pages; dark theme, status links, source disclosure and icon size')

        route('#/page/7523','#damage-form')
        assert '2,700' in page.locator('#damage-output').inner_text()
        page.locator('#atkBonusPct').fill('20，30');page.locator('#ignoreDefPct').fill('50,50')
        assert '6,300' in page.locator('#damage-output').inner_text()
        page.locator('#atkBonusPct').fill('20oops')
        assert page.locator('#damage-error').is_visible()
        assert page.locator('[data-tool="export-damage"]').is_disabled()
        assert page.locator('#atkBonusPct').get_attribute('aria-invalid')=='true'
        page.locator('#atkBonusPct').fill('20，30')
        page.locator('#preset-name').fill('离线测试 · 爆发')
        page.locator('[data-tool="save-preset"]').click()
        page.locator('#atkPanel').fill('4000')
        page.locator('[data-preset="0"]').click()
        assert page.locator('#atkPanel').input_value()=='3000'
        page.reload();page.locator('#damage-form').wait_for()
        assert page.locator('#atkBonusPct').input_value()=='20，30'
        assert '离线测试' in page.locator('#preset-list').inner_text()
        with page.expect_download() as download:page.locator('[data-tool="export-damage"]').click()
        download.value.save_as(OUT/'damage-export-test.png')
        assert (OUT/'damage-export-test.png').stat().st_size>10000
        shot('fix-damage-desktop',True)
        reports.append('Damage source-page routing, arithmetic, invalid input, preset save/load, reload persistence and PNG export')

        route('#/page/8027','.pool-tabs')
        page.locator('[data-draw="10"]').click()
        assert page.locator('.summon-card').count()==10
        assert page.locator('.simulation-total strong').inner_text()=='10'
        page.locator('[data-pool="chongfeng"]').click()
        page.locator('[data-draw="100"]').click()
        assert page.locator('.simulation-total strong').inner_text()=='110'
        assert page.locator('.summon-history tbody tr').count()==110
        assert page.locator('.summon-card').count()==20
        page.reload();page.locator('.pool-tabs').wait_for()
        assert page.locator('[data-pool="chongfeng"]').get_attribute('aria-pressed')=='true'
        assert page.locator('.simulation-total strong').inner_text()=='110'
        with page.expect_download() as download:page.locator('[data-tool="export-gacha"]').click()
        download.value.save_as(OUT/'gacha-export-test.json')
        exported=json.loads((OUT/'gacha-export-test.json').read_text(encoding='utf-8'))
        assert exported['total']==110 and len(exported['history'])==110
        assert sum(exported['counts'].values())==110
        assert 0<=exported['pity']<100
        page.locator('[data-draw="10"]').click();shot('fix-gacha-desktop')
        page.locator('.summon-card[href^="#/page/"]').first.click();page.locator('.detail-heading').first.wait_for()
        reports.append('Gacha source-page routing, ten/100 draws, pool switching, persistent shared state, history, export and character links')

        routes=[('#/page/9346','.ability-card'),('#/page/'+str(personality),'.ability-card'),
            ('#/page/9296','.character-profile'),('#/page/7187','.equipment-profile'),
            ('#/tools','.tool-grid'),('#/tools/damage','#damage-form'),('#/tools/gacha','.pool-tabs'),
            ('#/page/'+str(titles['伤害公式汇总']),'#article-content')]
        for width in (1440,1024,768,390,320):
            page.set_viewport_size({'width':width,'height':900})
            for fragment,ready in routes:
                route(fragment,ready);overflow((width,fragment))
                if width==390 and fragment in ('#/page/9346','#/tools/damage','#/tools/gacha'):
                    shot('fix-'+('skill' if '9346' in fragment else fragment.rsplit('/',1)[-1])+'-mobile',True)
                if fragment=='#/page/9346':
                    page.locator('.source-details summary').click();overflow((width,'skill source'))
                if fragment=='#/page/9296':
                    page.locator('[data-detail-tab="skills"]').click();overflow((width,'skill tree'))
                    page.locator('[data-detail-tab="source"]').click();overflow((width,'character source'))
                    sizes=page.locator('.wiki-content .skill_icon_box').evaluate_all('(es)=>es.slice(0,2).map(e=>({w:e.getBoundingClientRect().width,h:e.getBoundingClientRect().height}))')
                    assert all(s['w']<=85 and s['h']<150 for s in sizes),sizes
        reports.append('40 page/viewport combinations plus expanded source tables and skill trees fit at 320–1440px')
        for pid in (7541,7507,2292):
            route('#/page/'+str(pid),'#article-content');assert '测试页' in page.locator('#article-content').inner_text()
        assert not errors,errors
        assert not remote,remote
        assert not failed,failed
        reports.append('Offline file:// execution: no JavaScript errors, no failed assets, no external requests')
        context.close();browser.close()
    result={'status':'passed','reports':reports,'viewportWidths':[320,390,768,1024,1440],'network':'disabled'}
    (OUT/'fix-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    for report in reports:print('PASS '+report,flush=True)

if __name__=='__main__':run()
