"""Check typography, safe branch endpoints, liberation marks and publication labels."""
from pathlib import Path
import json
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'test-results'

def ready(page):
    page.wait_for_function("()=>document.querySelector('#ig-canvas')?.width===1920&&!document.querySelector('[data-ig=export]')?.disabled",timeout=60000)

def state(page):
    return page.evaluate("JSON.parse(localStorage.getItem('socwiki.infographic.draft.9296'))")

def main():
    errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch()
        context=browser.new_context(offline=True,viewport={'width':1480,'height':1000},accept_downloads=True)
        page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        page.add_init_script("""window.publicationText=[];const fill=CanvasRenderingContext2D.prototype.fillText;CanvasRenderingContext2D.prototype.fillText=function(t,x,y,...rest){if(this.canvas.width===1920)window.publicationText.push({text:String(t),font:this.font,color:this.fillStyle,x,y});return fill.call(this,t,x,y,...rest);};""")
        page.goto((ROOT/'index.html').as_uri()+'#/tools/infographic');ready(page)
        today=page.evaluate("WikiInfographicRules.posterDate({})")
        assert page.evaluate('(date)=>publicationText.some(t=>t.text===date)',today)
        lib=page.locator('.ig-lib-mark');id=lib.get_attribute('data-ig-mark')
        for expected in ['required','optional',None]:
            lib.click();ready(page);assert state(page)['marks'].get(id)==expected
        lib.click();ready(page)
        page.locator('[data-ig-liberation]').click();assert '3 级' in page.locator('.ig-skill-detail').inner_text();page.keyboard.press('Escape')
        page.get_by_label('技能树横线粗细',exact=True).fill('1')
        page.get_by_label('技能树横线长度',exact=True).fill('75');ready(page)
        assert state(page)['branchWidth']==1 and state(page)['branchLength']==75
        # Check the actual responsive SVG paths against the visible icon borders.
        validate="""()=>[...document.querySelectorAll('.ig-tier')].every(t=>{const svg=t.querySelector('svg'),b=svg.getBoundingClientRect(),nodes=[...t.querySelectorAll('.ig-node-select>img')];return [...svg.querySelectorAll('path')].every((path,i)=>{if(!nodes[i])return true;const values=path.getAttribute('d').match(/[-.\\d]+/g).map(Number),end=b.left+values[2]/300*b.width,r=nodes[i].getBoundingClientRect();return i===0?end>r.right+2:end<r.left-2;});})"""
        assert page.evaluate(validate)
        page.locator('[data-ig-title-mode=text]').click();ready(page)
        page.locator('.ig-title-typography summary').click()
        page.locator('.ig-typography summary').click()
        page.get_by_label('加粗名字',exact=True).check();page.get_by_label('名字斜体',exact=True).check()
        page.get_by_label('名字描边宽度',exact=True).fill('3')
        page.get_by_label('名字描边颜色',exact=True).fill('#18455b')
        page.get_by_label('名字大小比例',exact=True).fill('0.85');ready(page)
        assert state(page)['titleItalic'] and state(page)['titleBold'] and state(page)['titleOutlineWidth']==3
        normal=page.locator('#ig-canvas').evaluate('(c)=>c.toDataURL()')
        page.get_by_label('名字投影',exact=True).uncheck();ready(page)
        assert normal!=page.locator('#ig-canvas').evaluate('(c)=>c.toDataURL()')
        page.get_by_label('正文字体',exact=True).select_option('serif')
        page.get_by_label('正文加粗',exact=True).check()
        page.get_by_label('正文斜体',exact=True).check()
        page.get_by_label('正文描边宽度',exact=True).fill('0.5');ready(page)
        assert state(page)['bodyFont']=='serif' and state(page)['bodyOutlineWidth']==.5
        assert page.evaluate("publicationText.some(t=>t.font.includes('WikiTitleNormal')&&t.font.includes('italic')&&t.text.includes('个性'))")
        page.get_by_label('正文字体',exact=True).select_option('sans')
        page.get_by_label('正文斜体',exact=True).uncheck()
        page.get_by_label('正文加粗',exact=True).uncheck()
        page.get_by_label('正文描边宽度',exact=True).fill('0');ready(page)
        page.locator('summary',has_text='生成日期与顶部自定义文字').click()
        page.get_by_label('日期前面的文字',exact=True).fill('更新于')
        page.get_by_label('生成日期',exact=True).fill('2025-12-24')
        page.get_by_label('顶部自定义文字',exact=True).fill('交流群：123456789')
        page.get_by_label('顶部文字横向位置',exact=True).fill('1050')
        page.get_by_label('顶部文字纵向位置',exact=True).fill('146')
        page.get_by_label('顶部文字字号',exact=True).fill('24')
        page.get_by_label('顶部文字颜色',exact=True).fill('#b5e6ed')
        page.locator('[data-ig-field=author]').fill('Coney');ready(page)
        assert page.evaluate("publicationText.some(t=>t.text==='更新于 2025-12-24')")
        assert page.evaluate("publicationText.some(t=>t.text==='by'&&t.font.includes('Arial'))")
        assert page.evaluate("publicationText.some(t=>t.text==='交流群：123456789')")
        with page.expect_download() as png:page.locator('[data-ig=export]').first.click()
        png.value.save_as(OUT/'infographic-v19-publication.png')
        with page.expect_download() as plan:page.locator('[data-ig=save-plan]').click()
        plan_path=OUT/'infographic-v19-publication.json';plan.value.save_as(plan_path)
        before=state(page);page.reload();ready(page);assert state(page)==before
        page.locator('summary',has_text='生成日期与顶部自定义文字').click()
        page.locator('[data-ig=date-auto]').click();ready(page);assert state(page)['generatedDate']==''
        page.locator('#ig-import-file').set_input_files(plan_path)
        page.wait_for_function("()=>JSON.parse(localStorage.getItem('socwiki.infographic.draft.9296'))?.generatedDate==='2025-12-24'");ready(page)
        assert state(page)==before
        # Image lettering outline must fit inside the title region and remain exportable.
        page.locator('[data-ig-title-mode=reference]').click();ready(page)
        image_style=page.evaluate("""async()=>{const s=JSON.parse(localStorage.getItem('socwiki.infographic.draft.9296'));const a=await WikiInfographicCanvas.titleArtwork({character:{id:9296,name:'薇佩拉'}},{...s,titleScale:1,titleOutlineWidth:8},WIKI_INFOGRAPHIC_DATA);return {w:a.width,h:a.height,png:a.canvas.toDataURL().length};}""")
        assert image_style['w']<=695 and image_style['h']<=143 and image_style['png']>1000
        page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(100)
        assert page.evaluate(validate)
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        assert not errors,errors
        browser.close()
    report={'status':'passed','checks':['normal typography, body typography and image outline fit','branch thickness/length and responsive endpoints outside circles','liberation three-state marking and separate details','readable by prefix','automatic/custom date','custom top text position/size/color','reload and JSON roundtrip','390px layout'],'errors':errors}
    (OUT/'infographic-publication-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
