"""Exercise recovered data, source controls, equipment reference and backup portability offline."""
from __future__ import annotations
import json,pathlib
from playwright.sync_api import sync_playwright
from verify import load_assignment

ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'test-results';OUT.mkdir(exist_ok=True)
data=load_assignment(ROOT/'data/index.js');tooldata=load_assignment(ROOT/'data/tools.js')
reports=[];errors=[];network=[];failed=[]

def run():
    assert len(tooldata['equipment']['rows'])==24
    assert sum(r['recorded'] for r in tooldata['equipment']['rows'])==7
    for pid,life,speed in [(2207,'3671','187'),(9289,'继承','244'),(6079,'5054','100')]:
        fields=load_assignment(ROOT/'data/pages'/f'{pid}.js')['rawFields']
        assert fields['满级满星生命']==life and fields['满级满星敏捷']==speed
    reports.append('Recorded character stats recovered from raw tables; 24 equipment combinations retain 7 meaningful rows')
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(offline=True,viewport={'width':1440,'height':1000},accept_downloads=True)
        page=context.new_page()
        def observe(pg):
            pg.on('pageerror',lambda e:errors.append(str(e)))
            pg.on('request',lambda r:network.append(r.url) if r.url.startswith(('http:','https:')) else None)
            pg.on('requestfailed',lambda r:failed.append(r.url))
        observe(page)
        base=(ROOT/'index.html').as_uri()
        def route(fragment,ready):
            page.goto(base+fragment);page.locator(ready).first.wait_for();page.locator('.loading').wait_for(state='hidden')
        def fit(label):assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),label
        def screenshot(name):
            page.evaluate("()=>{document.activeElement?.blur();scrollTo({top:0,behavior:'instant'});for(const i of document.images)if(i.getBoundingClientRect().top<innerHeight)i.loading='eager'}")
            page.evaluate('''async()=>{await Promise.all([...document.images].filter(i=>i.getAttribute('src')&&i.getBoundingClientRect().top<innerHeight).map(i=>i.decode()));await new Promise(requestAnimationFrame)}''')
            page.screenshot(path=str(OUT/(name+'.png')),animations='disabled')
        route('#/characters','#catalog-results')
        assert page.locator('[data-filter="rarity"][data-value="卓越"]').count()==0
        page.locator('[data-filter="rarity"][data-value="R"]').click()
        assert '20' in page.locator('#catalog-count').inner_text()
        assert page.locator('.character-card').count()==20
        for source,kind in [(968,'角色图鉴'),(2701,'角色图鉴'),(7199,'魔物图鉴')]:
            route('#/page/'+str(source),'#catalog-results');assert kind in page.locator('h1').inner_text()
        reports.append('Elite rarity filter returns all 20 characters; old catalog links open functional offline catalogs')
        route('#/page/9289','.character-profile')
        assert page.locator('.profile-stats').inner_text().count('继承')==5
        assert '244' in page.locator('.profile-stats').inner_text()
        assert '防御者' in page.locator('.profile-info').inner_text()
        route('#/page/2207','.character-profile');assert '3671' in page.locator('.profile-stats').inner_text()
        page.locator('[data-detail-tab="source"]').click()
        table=page.locator('table[data-stat-panel]').first
        assert table.locator('.pre_val').first.is_visible()
        assert not table.locator('.max_val').first.is_visible()
        table.locator('[data-source-stat="max"]').click()
        assert table.locator('.max_val').first.is_visible()
        assert not table.locator('.pre_val').first.is_visible()
        assert table.locator('.max_val').first.inner_text().strip()=='3671'
        route('#/page/2710','#article-content')
        table=page.locator('.wiki-content table.sortable').first
        table.locator('[data-source-sort="2"]').click();table.locator('[data-source-sort="2"]').click()
        assert table.locator('tr').nth(1).locator('td').nth(2).inner_text().strip()=='474'
        reports.append('Original character panel toggles and equipment table numeric sorting work without source scripts')

        route('#/tools/equipment','.equipment-reference')
        page.locator('[data-ref-weapon="弓弩"]').click()
        assert '390' in page.locator('.reference-stats').inner_text()
        assert '885' in page.locator('.reference-stats').inner_text()
        page.locator('[data-ref-rarity="SR"]').click();assert page.locator('.reference-unrecorded').is_visible()
        page.locator('[data-ref-weapon="防具"]').click();assert '181' in page.locator('.reference-stats').inner_text()
        page.locator('[data-ref-rarity="SSR"]').click();screenshot('continued-equipment-desktop')
        page.locator('.reference-equipment-list a').first.click();page.locator('.equipment-profile').wait_for()
        assert '213' in page.locator('.reference-stats').inner_text()
        reports.append('Equipment reference and detail cards show recorded values and explicitly label zero-filled combinations')

        route('#/page/2207','.character-profile')
        page.locator('[data-compare]').first.click();page.locator('#page-notes').fill('迁移测试：伊奇 3671 生命')
        page.locator('[data-action="theme"]').click()
        route('#/page/9346','#article-content');page.locator('[data-action="font-up"]').click()
        route('#/tools/damage','#damage-form')
        page.locator('#atkPanel').fill('3579');page.locator('#preset-name').fill('继续测试的方案');page.locator('[data-tool="save-preset"]').click()
        with page.expect_download() as info:page.locator('[data-tool="export-damage-plans"]').click()
        info.value.save_as(OUT/'continued-damage-backup.json')
        route('#/tools/gacha','.pool-tabs');page.locator('[data-draw="10"]').click()
        route('#/archive','.archive-hero')
        with page.expect_download() as info:page.locator('[data-action="export"]').click()
        backup=OUT/'continued-full-backup.json';info.value.save_as(backup)
        saved=json.loads(backup.read_text(encoding='utf-8'))
        assert saved['version']==2 and saved['tools']['gacha']['state']['total']==10
        assert saved['comparison']==[2207]
        second=browser.new_context(offline=True,viewport={'width':1440,'height':1000},accept_downloads=True)
        page=second.new_page();observe(page)
        route('#/archive','.archive-hero');page.locator('#import-file').set_input_files(backup)
        page.locator('#toast').filter(has_text='备份已导入').wait_for()
        assert page.locator('body').evaluate("e=>e.classList.contains('dark')")
        assert page.evaluate("JSON.parse(localStorage.getItem('socwiki.readerFont'))")==15
        route('#/compare','.compare-table');assert '伊奇' in page.locator('.compare-name').inner_text()
        route('#/page/2207','.character-profile');assert page.locator('#page-notes').input_value()=='迁移测试：伊奇 3671 生命'
        route('#/tools/damage','#damage-form');assert page.locator('#atkPanel').input_value()=='3579'
        assert '继续测试的方案' in page.locator('#preset-list').inner_text()
        route('#/tools/gacha','.pool-tabs');assert page.locator('.simulation-total strong').inner_text()=='10'
        legacy=OUT/'continued-legacy-backup.json'
        legacy.write_text(json.dumps({'format':'socwiki-personal','version':1,'favorites':[9296],'notes':{},'history':[]}),encoding='utf-8')
        page.locator('[data-tool="import-tool"]').click();page.locator('#import-file').set_input_files(legacy)
        page.locator('#toast').filter(has_text='备份已导入').wait_for();assert page.locator('.simulation-total strong').inner_text()=='10'
        invalid=OUT/'continued-invalid-backup.json';saved['tools']['damage']['current']['atkPanel']='oops';saved['notes']['2207']='不应写入'
        invalid.write_text(json.dumps(saved,ensure_ascii=False),encoding='utf-8')
        page.locator('#import-file').set_input_files(invalid);page.locator('#toast').filter(has_text='导入失败').wait_for()
        assert page.evaluate("JSON.parse(localStorage.getItem('socwiki.notes'))['2207']")=='迁移测试：伊奇 3671 生命'
        assert page.locator('.simulation-total strong').inner_text()=='10'
        reports.append('Fresh-browser full backup restores notes, comparison, preferences, plans and simulation; v1 preserves tools; invalid import changes nothing')
        page.locator('[data-action="theme"]').click()
        for width in (1440,1024,768,390,320):
            page.set_viewport_size({'width':width,'height':1000})
            for fragment,ready in [('#/','.home-tools'),('#/tools','.tool-grid'),('#/tools/equipment','.reference-stats'),('#/page/9289','.character-profile'),('#/page/2710','#article-content')]:
                route(fragment,ready);fit((width,fragment))
                if width==1440 and fragment=='#/':screenshot('continued-home-desktop')
                if width==390 and fragment=='#/tools/equipment':screenshot('continued-equipment-mobile')
        reports.append('25 page/viewport combinations fit from 320 to 1440px, including original equipment tables')
        assert not errors,errors
        assert not network,network
        assert not failed,failed
        second.close();context.close();browser.close()
    (OUT/'continuation-verification.json').write_text(json.dumps({'status':'passed','reports':reports,'network':'disabled'},ensure_ascii=False,indent=2),encoding='utf-8')
    for report in reports:print('PASS '+report,flush=True)
    print('PASS no JavaScript errors, failed files or network requests',flush=True)

if __name__=='__main__':run()
