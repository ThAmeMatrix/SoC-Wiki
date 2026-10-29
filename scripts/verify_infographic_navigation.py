"""Exercise editor search, actual preview clicks and custom date labels offline."""
from pathlib import Path
import json
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'test-results'

def ready(page):
    page.wait_for_function("()=>document.querySelector('#ig-canvas')?.width===1920&&!document.querySelector('[data-ig=export]')?.disabled",timeout=60000)

def stored(page):
    return page.evaluate("JSON.parse(localStorage.getItem('socwiki.infographic.draft.9296'))")

def main():
    errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch()
        context=browser.new_context(offline=True,viewport={'width':1600,'height':1000},reduced_motion='reduce',accept_downloads=True)
        page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        page.add_init_script("window.navTexts=[];const fill=CanvasRenderingContext2D.prototype.fillText;CanvasRenderingContext2D.prototype.fillText=function(t,...args){if(this.canvas.width===1920)window.navTexts.push(String(t));return fill.call(this,t,...args);};")
        page.goto((ROOT/'index.html').as_uri()+'#/tools/infographic');ready(page)
        assert page.locator('.ig-nav').bounding_box()['x']<page.locator('#ig-editor').bounding_box()['x']
        search=page.get_by_label('搜索修改区域',exact=True)
        search.fill('不存在的区域');assert '没有匹配' in page.locator('.ig-nav-list').inner_text()
        search.fill('群号');assert page.locator('.ig-nav-list button').count()==1
        search.press('Enter')
        assert page.get_by_label('顶部自定义文字',exact=True).evaluate("(e)=>e===document.activeElement")
        assert page.locator('.ig-nav-list [aria-current]').get_attribute('data-ig-jump')=='topText'
        search.fill('描边');search.press('Enter');assert page.locator('.ig-typography').get_attribute('open') is not None
        search.fill('');keys=page.locator('.ig-nav-list button').evaluate_all('(els)=>els.map(e=>e.dataset.igJump)')
        for key in keys:
            page.locator(f'.ig-nav-list [data-ig-jump={key}]').click()
            assert page.locator('.ig-nav-list [aria-current]').get_attribute('data-ig-jump')==key
            assert page.locator('.ig-jump-highlight').is_visible()
        page.evaluate('scrollTo(0,0)')
        page.screenshot(path=str(OUT/'infographic-v110-navigation.png'))
        # Hotspots are DOM-only and aligned with the canvas, including small previews.
        before=page.locator('#ig-canvas').evaluate('(c)=>c.toDataURL()')
        page.locator('.ig-hotspots [data-ig-jump=loadouts]').hover()
        assert before==page.locator('#ig-canvas').evaluate('(c)=>c.toDataURL()')
        page.locator('.ig-hotspots [data-ig-jump=loadouts]').click()
        assert page.locator('.ig-nav-list [aria-current]').get_attribute('data-ig-jump')=='loadouts'
        page.locator('.ig-hotspots [data-ig-jump=liberation]').click()
        assert page.locator('.ig-lib-mark').first.evaluate("(e)=>e===document.activeElement")
        page.locator('.ig-hotspots [data-ig-jump=date]').click()
        prefix=page.get_by_label('日期前面的文字',exact=True);assert prefix.evaluate("(e)=>e===document.activeElement")
        prefix.fill('最后更新于');page.get_by_label('生成日期',exact=True).fill('2026-11-08');ready(page)
        assert page.evaluate("navTexts.includes('最后更新于 2026-11-08')")
        assert stored(page)['datePrefix']=='最后更新于'
        with page.expect_download() as plan:page.locator('[data-ig=save-plan]').click()
        plan_path=OUT/'infographic-v110-date-plan.json';plan.value.save_as(plan_path)
        prefix.fill('');ready(page)
        assert page.evaluate("navTexts.includes('2026-11-08')")
        page.locator('#ig-import-file').set_input_files(plan_path)
        page.wait_for_function("()=>JSON.parse(localStorage.getItem('socwiki.infographic.draft.9296'))?.datePrefix==='最后更新于'");ready(page)
        page.reload();ready(page);assert stored(page)['datePrefix']=='最后更新于'
        # Full preview uses actual scaled canvas coordinates and closes before jumping.
        page.locator('[data-ig=enlarge]').click()
        full=page.locator('#ig-full-canvas').bounding_box()
        page.mouse.click(full['x']+600/1920*full['width'],full['y']+250/1080*full['height'])
        assert not page.locator('.ig-full-preview').is_visible()
        assert page.locator('.ig-nav-list [aria-current]').get_attribute('data-ig-jump')=='trait'
        for width in [1100,820,390,360]:
            page.set_viewport_size({'width':width,'height':900});page.wait_for_timeout(100)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            canvas=page.locator('#ig-canvas').bounding_box()
            if canvas:
                overlay=page.locator('.ig-canvas-wrap .ig-hotspots').bounding_box()
                assert abs(overlay['height']-canvas['height'])<2 and abs(overlay['width']-canvas['width'])<2
        page.locator('[data-ig-view=preview]').click()
        page.locator('.ig-hotspots [data-ig-jump=tree]').click()
        assert page.locator('.ig-workspace').get_attribute('data-ig-mode')=='edit'
        assert page.locator('[data-section="02"]').get_attribute('open') is not None
        page.evaluate('scrollTo(0,0)')
        details=page.locator('.ig-nav details')
        if details.get_attribute('open') is None:details.locator('summary').click()
        page.get_by_label('搜索修改区域',exact=True).fill('日期');page.get_by_label('搜索修改区域',exact=True).press('Enter')
        assert page.get_by_label('日期前面的文字',exact=True).evaluate("(e)=>e===document.activeElement")
        assert page.get_by_label('日期前面的文字',exact=True).input_value()=='最后更新于'
        page.screenshot(path=str(OUT/'infographic-v110-navigation-mobile.png'))
        with page.expect_download() as png:page.locator('[data-ig=export]').first.click()
        png.value.save_as(OUT/'infographic-v110-date-prefix.png')
        assert not errors,errors
        browser.close()
    report={'status':'passed','checks':[f'{len(keys)} searchable navigation destinations, aliases, no results and keyboard Enter','main preview hotspot jumps without altering PNG pixels','full preview coordinates and modal dismissal','mobile preview returns to editor and expands target','360–1600px layout and hotspot alignment','custom/empty date prefix in canvas, saved draft and JSON roundtrip'],'errors':errors}
    (OUT/'infographic-navigation-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
