"""Real offline OCR, image masks, editor controls and portable name modes."""
from pathlib import Path
import base64, io, json
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'test-results'


def ready(page):
    page.wait_for_function("()=>document.querySelector('#ig-canvas')?.width===1920&&!document.querySelector('[data-ig=export]')?.disabled",timeout=60000)


def stored(page):
    return page.evaluate("JSON.parse(localStorage.getItem('socwiki.infographic.draft.9296'))")


def cutout(page):
    return page.locator('.ig-cutout-output').evaluate('(c)=>c.toDataURL()')


def read_png(uri):
    return Image.open(io.BytesIO(base64.b64decode(uri.split(',')[1]))).convert('RGBA')


def fixture():
    face=ImageFont.truetype(str(ROOT/'.tools/fonts/SourceHanSerifSC-Heavy.otf'),100)
    ink=Image.new('RGBA',(1200,700))
    ImageDraw.Draw(ink).text((105,410),'歌洛莉亚',font=face,fill='#efbe7e')
    poster=Image.new('RGB',ink.size,'#122331')
    d=ImageDraw.Draw(poster)
    d.rectangle((45,45,1155,655),outline='#615344',width=3)
    d.text((85,60),'铃兰之剑',font=ImageFont.truetype(str(ROOT/'.tools/fonts/SourceHanSerifSC-Heavy.otf'),42),fill='#8195a0')
    poster.paste(ink,mask=ink.getchannel('A'))
    poster.save(OUT/'title-import-fixture.jpg',quality=95)
    return ink


def main():
    expected=fixture();errors=[];remote=[];checks=[]
    with sync_playwright() as p:
        browser=p.chromium.launch()
        context=browser.new_context(offline=True,viewport={'width':1480,'height':1000},accept_downloads=True)
        page=context.new_page()
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:remote.append(r.url) if r.url.startswith(('https:','http:')) else None)
        page.goto((ROOT/'index.html').as_uri()+'#/tools/infographic');ready(page)
        assert page.locator('[data-ig-title-mode=reference]').get_attribute('aria-pressed')=='true'
        page.get_by_label('角色显示名',exact=True).fill('歌洛莉亚');ready(page)
        assert stored(page)['titleMode']=='text'
        page.get_by_label('名字普通字体',exact=True).select_option('sans');ready(page)
        assert stored(page)['titleFont']=='sans'
        page.locator('[data-ig-title-mode=image]').click();ready(page)
        assert '尚未导入' in page.locator('[data-ig-title-status]').inner_text()
        page.locator('#ig-title-file').set_input_files(OUT/'title-import-fixture.jpg')
        page.wait_for_function("()=>document.querySelector('[data-cut=locate]')?.disabled===false&&document.querySelector('.ig-cutout-source')?.width===1200",timeout=120000)
        crop=page.locator('[data-crop]').evaluate_all('(els)=>Object.fromEntries(els.map(e=>[e.dataset.crop,+e.value]))')
        actual=np.array(read_png(cutout(page)))[:,:,3]>128
        truth=np.array(expected.crop((crop['x'],crop['y'],crop['x']+crop['w'],crop['y']+crop['h'])))[:,:,3]>128
        iou=(actual&truth).sum()/max(1,(actual|truth).sum())
        assert iou>.92, (iou,crop)
        assert actual.mean()<.55 and actual.mean()>.05
        page.locator('.ig-cutout-dialog').screenshot(path=str(OUT/'infographic-v17-extraction.png'))
        checks.append(f'Offline JPG OCR found the name; extracted alpha overlaps the original glyphs by {iou:.1%}')
        # The pending strength render must finish before applying, without discarding later brush edits.
        page.get_by_label('去背景强度',exact=True).fill('48');page.wait_for_timeout(160)
        original=cutout(page)
        page.get_by_label('局部修整',exact=True).select_option('erase')
        pixels=np.array(read_png(original));ys,xs=np.where(pixels[:,:,3]>240);index=len(xs)//2
        bounds=page.locator('.ig-cutout-output').bounding_box()
        point=(bounds['x']+xs[index]/pixels.shape[1]*bounds['width'],bounds['y']+ys[index]/pixels.shape[0]*bounds['height'])
        page.mouse.click(*point);assert cutout(page)!=original
        page.locator('[data-cut=undo]').click();assert cutout(page)==original
        page.mouse.click(*point)
        edited=page.locator('.ig-cutout-output').evaluate('(c)=>WikiTitleImage.encode(c)')
        page.locator('[data-cut=apply]').click();ready(page)
        assert stored(page)['customTitle']==edited and stored(page)['titleMode']=='image'
        assert stored(page)['titleImageTint'] is False
        page.locator('[data-ig-title-mode=text]').click();ready(page)
        assert stored(page)['customTitle']==edited
        page.locator('[data-ig-title-mode=image]').click();ready(page)
        page.reload();ready(page);assert stored(page)['customTitle']==edited
        with page.expect_download() as plan:page.locator('[data-ig=save-plan]').click()
        plan_path=OUT/'infographic-v17-image-plan.json';plan.value.save_as(plan_path)
        page.locator('[data-ig=title-reset]').click();ready(page)
        assert stored(page)['titleMode']=='reference'
        page.locator('#ig-import-file').set_input_files(plan_path)
        page.wait_for_function("()=>JSON.parse(localStorage.getItem('socwiki.infographic.draft.9296'))?.titleMode==='image'");ready(page)
        assert stored(page)['customTitle']==edited
        with page.expect_download() as exported:page.locator('[data-ig=export-title]').click()
        exported.value.save_as(OUT/'infographic-v17-imported-title.png')
        image=Image.open(OUT/'infographic-v17-imported-title.png');assert image.mode=='RGBA' and image.getchannel('A').getextrema()==(0,255)
        checks.append('Brush erase/undo/apply, image/text toggle, reload, JSON roundtrip and transparent PNG export')
        # Transparent imports preserve the actual pixels, including letter counters.
        before=stored(page)['customTitle']
        page.locator('#ig-title-file').set_input_files(ROOT/'assets/brand/vipera-reference-title.png')
        page.locator('[data-cut=apply]:enabled').wait_for()
        assert page.get_by_label('去背景方式',exact=True).input_value()=='alpha'
        original_image=Image.open(ROOT/'assets/brand/vipera-reference-title.png').convert('RGBA')
        a,b=np.array(read_png(cutout(page))),np.array(original_image)
        assert a.shape==b.shape and np.array_equal(a[:,:,3],b[:,:,3])
        assert np.array_equal(a[:,:,:3][b[:,:,3]>0],b[:,:,:3][b[:,:,3]>0])
        page.keyboard.press('Escape');page.locator('.ig-cutout-dialog').wait_for(state='detached')
        assert stored(page)['customTitle']==before
        checks.append('Transparent PNG is preserved exactly; cancelling leaves the saved title intact')
        # A complex supplied poster can be corrected with actual pointer cropping and color controls.
        reference=Path('C:/Users/thamechen/Downloads/坏女人字体样板.png')
        if reference.exists():
            page.get_by_label('角色显示名',exact=True).fill('薇佩拉')
            page.locator('#ig-title-file').set_input_files(reference)
            page.wait_for_function("()=>document.querySelector('[data-cut=locate]')?.disabled===false&&document.querySelector('.ig-cutout-source')?.width===1080",timeout=120000)
            auto=page.locator('[data-crop]').evaluate_all('(els)=>Object.fromEntries(els.map(e=>[e.dataset.crop,+e.value]))')
            assert auto['y']>1200 and auto['x']<270 and auto['x']+auto['w']>860,auto
            (OUT/'title-reference-auto-crop.json').write_text(json.dumps(auto),encoding='utf8')
            box=page.locator('.ig-cutout-source').bounding_box()
            page.mouse.move(box['x']+160/1080*box['width'],box['y']+1370/1920*box['height']);page.mouse.down()
            page.mouse.move(box['x']+910/1080*box['width'],box['y']+1690/1920*box['height'],steps=8);page.mouse.up()
            page.get_by_label('去背景方式',exact=True).select_option('light')
            page.get_by_label('去背景强度',exact=True).fill('66');page.wait_for_timeout(200)
            assert not page.locator('[data-cut=apply]').is_disabled()
            page.locator('.ig-cutout-dialog').screenshot(path=str(OUT/'infographic-v17-reference-extraction.png'))
            page.keyboard.press('Escape')
            checks.append('Reference poster: automatic candidate plus pointer crop and strength adjustment')
        # Mobile picker and native-style modal dismissal; no clipping outside the screen.
        page.set_viewport_size({'width':390,'height':844})
        page.locator('#ig-title-file').set_input_files(ROOT/'assets/brand/vipera-reference-title.png')
        page.locator('[data-cut=apply]:enabled').wait_for()
        page.locator('.ig-cutout-dialog').evaluate('(d)=>d.scrollTop=d.scrollHeight')
        assert page.locator('.ig-cutout-dialog').evaluate('(d)=>d.scrollWidth<=d.clientWidth+1')
        page.screenshot(path=str(OUT/'infographic-v17-extraction-mobile.png'))
        page.keyboard.press('Escape')
        # Missing engine still leaves working crop/matte controls and an actionable explanation.
        fallback=browser.new_context(offline=True,viewport={'width':1100,'height':900});other=fallback.new_page()
        other.on('pageerror',lambda e:errors.append(str(e)))
        other.route('**/assets/ocr/title-ocr.js',lambda route:route.abort())
        other.goto((ROOT/'index.html').as_uri()+'#/tools/infographic');ready(other)
        other.locator('#ig-title-file').set_input_files(OUT/'title-import-fixture.jpg')
        other.wait_for_function("()=>document.querySelector('.ig-cutout-status')?.textContent.includes('未找到离线识别文件')")
        for key,value in {'x':96,'y':428,'w':418,'h':119}.items():other.locator(f'[data-crop={key}]').fill(str(value))
        other.locator('[data-cut=apply]:enabled').click();ready(other)
        assert stored(other)['titleMode']=='image'
        checks.append('Mobile modal fits; missing OCR engine retains functional manual cropping and matting')
        assert not remote,remote
        assert not errors,errors
        browser.close()
    report={'status':'passed','checks':checks,'networkRequests':remote,'pageErrors':errors,'maskIoU':float(iou)}
    (OUT/'title-import-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
