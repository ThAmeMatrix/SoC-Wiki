"""Check connected character trees against the archived data, entirely offline."""
from pathlib import Path
import json
from playwright.sync_api import sync_playwright
from verify import load_assignment

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'test-results'
DATA=load_assignment(ROOT/'data/index.js')

def run():
    errors=[];remote=[];failed=[];reports=[]
    with sync_playwright() as p:
        browser=p.chromium.launch()
        context=browser.new_context(offline=True,viewport={'width':1440,'height':1050})
        page=context.new_page()
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:remote.append(r.url) if r.url.startswith(('http:','https:')) else None)
        page.on('requestfailed',lambda r:failed.append(r.url))
        base=(ROOT/'index.html').as_uri()
        def route(pid):
            page.goto(base+'#/page/'+str(pid))
            page.locator('.detail-heading').wait_for()
            page.locator('.loading').wait_for(state='hidden')
        def tree():
            page.locator('[data-detail-tab="skills"]').click()
            page.locator('.growth-explorer[data-ready="true"]').wait_for()
        def fit(label):
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),label
        def shot(name,selector=None):
            page.evaluate('''async()=>{document.activeElement?.blur();await Promise.all([...document.images].filter(i=>i.getBoundingClientRect().top<innerHeight).map(i=>{i.loading='eager';return i.decode().catch(()=>{})}));await new Promise(requestAnimationFrame)}''')
            if selector:page.locator(selector).screenshot(path=str(OUT/(name+'.png')),animations='disabled',style='.topbar{visibility:hidden!important}')
            else:page.screenshot(path=str(OUT/(name+'.png')),animations='disabled')
        vipera=DATA['titles']['角色图鉴库/薇佩拉']
        for name in ('薇佩拉','歌洛莉亚','贝拉'):
            pid=DATA['titles']['角色图鉴库/'+name]
            raw=load_assignment(ROOT/'data/pages'/f'{pid}.js')['rawFields']
            route(pid);tree()
            assert page.locator('.is-branch').evaluate_all('(es)=>es.map(e=>Number(e.dataset.rank))')==[11,7,5,3,1]
            assert page.locator('.growth-tier').evaluate_all('(es)=>es.map(e=>Number(e.dataset.rank))')==[11,9,7,5,3,1,0]
            assert page.locator('[data-skill-key]').count()==14
            for word,rank in [('一',1),('三',3),('五',5),('七',7),('九',9),('十一',11)]:
                for side,cn in [(0,'左'),(1,'右')]:
                    button=page.locator(f'[data-skill-key="{rank}-{side}"]')
                    assert button.locator('.skill-node-name').inner_text()==raw[f'{word}阶技能{cn}']
                    button.click()
                    assert button.get_attribute('aria-pressed')=='true'
                    assert page.locator('.inspector-title h3').inner_text()==raw[f'{word}阶技能{cn}']
                    assert page.locator('.skill-inspector-content').get_attribute('aria-busy')=='false'
            assert '普攻进阶' in page.locator('[data-rank="9"]').inner_text()
        reports.append('Three full character trees match every archived left/right branch; 9th-rank basic attacks remain available')
        page.locator('[data-skill-key="7-0"]').click()
        assert page.locator('.inspector-title h3').inner_text()=='烈焰星陨'
        image=page.locator('.skill-inspector .range-map img')
        assert image.get_attribute('src')=='assets/wiki/5c7c63802a2c7625ced2.webp'
        assert '2-3' in page.locator('.skill-facts').inner_text()
        page.locator('.skill-inspector .range-map').click()
        assert page.locator('#image-dialog').is_visible()
        page.keyboard.press('Escape')
        page.locator('.skill-full-link').click();page.locator('.ability-card').wait_for()
        assert page.locator('.ability-card .range-map img').get_attribute('src')=='assets/wiki/5c7c63802a2c7625ced2.webp'
        reports.append('Skill tree and full detail show the original local range image; image zoom and full-page navigation work')
        route(vipera)
        page.locator('#personality-content [data-source-color]').first.wait_for()
        shot('character-profile-desktop')
        tree()
        page.locator('[data-skill-key="3-1"]').click()
        page.locator('.growth-explorer').scroll_into_view_if_needed()
        shot('character-tree-desktop','.growth-explorer')
        for theme in ('light','dark'):
            if theme=='dark':page.locator('[data-action="theme"]').click()
            for width in (1440,1280,1024,768,390,320):
                page.set_viewport_size({'width':width,'height':1000})
                fit((theme,width,'growth tree'))
                for key in ('1-0','5-1','9-1','11-0'):
                    page.locator(f'[data-skill-key="{key}"]').click()
                    fit((theme,width,key))
                    host=page.locator('.skill-inspector').evaluate('(e)=>e.parentElement.className')
                    assert ('growth-inspector-host' in host)==(width>=1280),(width,host)
                for row in page.locator('.is-branch').all():
                    left=row.locator('.node-0').bounding_box();right=row.locator('.node-1').bounding_box();rank=row.locator('.growth-rank').bounding_box()
                    assert left['x']+left['width']<right['x'] and left['y']+left['height']<rank['y'],(theme,width,'branch collision')
                page.locator('[data-skill-key="3-1"]').click()
                colors=page.locator('.skill-effect [data-source-color]').evaluate_all('(es)=>es.map(e=>getComputedStyle(e).color)')
                assert len(set(colors))>=2,colors
                if width==390:
                    page.locator('[data-rank="3"]').scroll_into_view_if_needed()
                    shot('character-tree-mobile-'+theme,'[data-rank="3"]')
                if theme=='dark' and width==1440:shot('character-tree-dark','.growth-explorer')
                page.locator('[data-detail-tab="overview"]').click()
                page.locator('#personality-content [data-source-color]').first.wait_for()
                fit((theme,width,'profile'))
                tree()
        reports.append('Both themes pass 320–1440px layout checks; branches do not overlap and the detail panel follows the selected node on narrow screens')
        page.set_viewport_size({'width':1440,'height':1000})
        # Partial summon archives must not acquire invented progression branches.
        route(9289)
        page.locator('[data-detail-tab="skills"]').click()
        assert page.locator('.growth-explorer').is_visible()
        assert not errors,errors
        assert not remote,remote
        assert not failed,failed
        browser.close()
    result={'status':'passed','reports':reports,'network':'disabled','errors':errors,'failedAssets':failed}
    (OUT/'character-ui-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    for report in reports:print('PASS '+report,flush=True)
    print('PASS no JavaScript errors, missing local files or remote requests',flush=True)

if __name__=='__main__':run()
