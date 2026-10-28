"""Exercise Android-only downloads and navigation with the real packaged web assets."""
import base64
import json
from pathlib import Path
from urllib.parse import urlsplit,unquote
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
ASSETS=ROOT/'android/app/build/generated/wikiAssets'
ORIGIN='https://appassets.androidplatform.net'


def run():
    assert (ASSETS/'wiki/android.js').exists()
    errors=[];saved=[];images=[];external=[];themes=[];requests=[]
    with sync_playwright() as p:
        browser=p.chromium.launch()
        context=browser.new_context(viewport={'width':390,'height':844})
        page=context.new_page()
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.expose_function('nativeSave',lambda name,mime,data:saved.append((name,mime,data)))
        page.expose_function('nativeImage',lambda url,name:images.append((url,name)))
        page.expose_function('nativeExternal',lambda url:external.append(url))
        page.expose_function('nativeTheme',lambda dark:themes.append(dark))
        page.add_init_script('''window.AndroidOffline={saveBase64:(...a)=>nativeSave(...a),saveAsset:(...a)=>nativeImage(...a),openExternal:u=>nativeExternal(u),setDarkTheme:b=>nativeTheme(b)}''')
        def handle(route):
            url=urlsplit(route.request.url)
            requests.append(route.request.url)
            assert url.netloc=='appassets.androidplatform.net'
            path=(ASSETS/unquote(url.path).removeprefix('/assets/')).resolve()
            assert path.is_relative_to(ASSETS.resolve()),path
            if not path.is_file():raise AssertionError(path)
            mime={'.js':'text/javascript','.css':'text/css','.html':'text/html','.json':'application/json','.webp':'image/webp','.svg':'image/svg+xml'}.get(path.suffix,'application/octet-stream')
            route.fulfill(path=path,content_type=mime)
        context.route('**/*',handle)
        def go(hash,selector):
            page.goto(ORIGIN+'/assets/wiki/index.html'+hash)
            page.locator(selector).first.wait_for()
        go('#/page/879','[data-trait-star="5"]')
        page.locator('#page-notes').fill('Android bridge backup test')
        page.locator('.detail-actions [data-favorite]').click()
        go('#/archive','[data-action="export"]')
        assert 'APK 内置资料' in page.locator('#main').inner_text()
        page.locator('[data-action="export"]').click()
        page.wait_for_timeout(100)
        assert saved and saved[-1][1]=='application/json'
        backup=json.loads(base64.b64decode(saved[-1][2]))
        assert backup['format']=='socwiki-personal' and 879 in backup['favorites']
        assert backup['notes']['879']=='Android bridge backup test'
        page.locator('[data-action="theme"]').click()
        page.wait_for_timeout(50)
        assert themes[-1] is True
        go('#/tools/damage','[data-tool="export-damage"]')
        page.locator('[data-tool="export-damage"]').click()
        page.wait_for_timeout(300)
        assert saved[-1][1]=='image/png'
        assert base64.b64decode(saved[-1][2]).startswith(b'\x89PNG\r\n\x1a\n')
        go('#/page/879','[data-portrait="awakened"]')
        page.locator('[data-portrait="awakened"]').click()
        expected=page.locator('.portrait-stage').get_attribute('href')
        page.locator('.portrait-stage').click()
        page.locator('#image-download').click()
        assert images[-1][0]==ORIGIN+'/assets/wiki/'+expected
        assert page.evaluate('WikiAndroid.back()') is True
        assert not page.locator('#image-dialog').is_visible()
        page.locator('.source-footer a[target="_blank"]').click()
        assert external[-1].startswith('https://wiki.biligame.com/')
        assert len(context.pages)==1
        page.locator('[data-action="menu"]').click()
        assert page.evaluate('WikiAndroid.back()') is True
        assert page.evaluate('WikiAndroid.back()') is False
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        go('#/tools/infographic','.ig-character')
        page.wait_for_function("()=>document.querySelector('#ig-canvas').width===1920 && !document.querySelector('[data-ig=export]').disabled",timeout=60000)
        assert page.locator('.ig-stat-max').all_text_contents()==['/ 1718','/ 1718','/ 288','/ 5','/ 3']
        assert page.locator('.ig-stat-current').count()==5
        page.locator('[data-ig-pick=character]').click()
        assert page.evaluate('WikiAndroid.back()') is True
        assert not page.locator('.ig-picker').is_visible()
        assert page.locator('.ig-tier[data-rank="0"] button').count()==0
        mark=page.locator('[data-ig-mark]').first.get_attribute('data-ig-mark')
        for expected in ['required','optional',None]:
            page.locator('[data-ig-mark="'+mark+'"]').click()
            assert page.evaluate('(id)=>JSON.parse(localStorage.getItem("socwiki.infographic.draft.9296")).marks[id]',mark)==expected
        page.locator('[data-ig-engraving]').nth(0).check()
        page.locator('[data-ig-engraving]').nth(1).check()
        page.locator('[data-ig-engraving-note]').first.fill('Android 保存测试')
        page.get_by_label('武器整组红字说明',exact=True).fill('手机方案')
        page.locator('[data-ig-field=titleColor]').fill('#79d1f2')
        page.locator('[data-ig-field=treeNotes]').fill('安卓保存：树底补充文字')
        page.locator('[data-ig=background-edit]').first.click()
        page.locator('#ig-background-choices [data-ig-art=base]').click()
        page.locator('[data-ig-background-scale]').fill('135')
        page.wait_for_function("()=>!document.querySelector('[data-ig=export]').disabled",timeout=60000)
        assert page.evaluate('WikiAndroid.back()') is True
        assert not page.locator('.ig-background-dialog').is_visible()
        page.locator('[data-ig-field=author]').fill('旅行者 Coney')
        page.get_by_label('角色定位',exact=True).fill('持续伤害 / 控场')
        page.locator('.ig-layout-controls summary').click()
        page.locator('#ig-layout-select').select_option('role')
        page.get_by_label('区块宽度',exact=True).fill('250')
        page.get_by_label('区块左上角 X',exact=True).fill('1650')
        page.get_by_label('角色显示名',exact=True).fill('霁月·瑟蕾妮娅')
        page.get_by_label('技能标记圈粗细',exact=True).fill('2.5')
        page.get_by_label('区域底框透明度',exact=True).fill('25')
        page.get_by_label('背景立绘透明度',exact=True).fill('40')
        page.locator('summary',has_text='生成日期与顶部自定义文字').click()
        page.get_by_label('生成日期',exact=True).fill('2026-10-27')
        page.get_by_label('日期前面的文字',exact=True).fill('更新于')
        page.get_by_label('顶部自定义文字',exact=True).fill('交流群：123456789')
        page.get_by_label('技能树横线粗细',exact=True).fill('1')
        page.locator('.ig-lib-mark').first.click()
        page.wait_for_function("()=>!document.querySelector('[data-ig=export]').disabled",timeout=60000)
        page.locator('[data-ig=save-plan]').click()
        page.wait_for_timeout(300)
        plan=json.loads(base64.b64decode(saved[-1][2]))
        assert plan['format']=='socwiki-infographic' and plan['state']['characterId']==9296
        assert plan['version']==6 and len(plan['state']['engravings'])==2
        assert plan['state']['background']['portrait']=='base' and plan['state']['background']['scale']==1.35
        assert page.evaluate("document.fonts.check('62px WikiSignature')")
        assert page.evaluate("Array.from(document.fonts).some(f=>f.family==='WikiSignatureLatin'&&f.status==='loaded')")
        assert plan['state']['author']=='旅行者 Coney'
        assert plan['state']['titleName']=='霁月·瑟蕾妮娅'
        assert plan['state']['markWidth']==2.5 and plan['state']['panelOpacity']==.75 and plan['state']['backgroundOpacity']==.6
        assert page.locator('.ig-badge-rarity').count()==0
        assert plan['state']['generatedDate']=='2026-10-27' and plan['state']['topText']=='交流群：123456789' and plan['state']['branchWidth']==1
        assert plan['state']['datePrefix']=='更新于'
        assert plan['state']['roleText']=='持续伤害 / 控场' and plan['state']['layout']['role']['x']==1650
        assert len(plan['state']['weapons'])==1
        lib_id=page.locator('.ig-lib-mark').first.get_attribute('data-ig-mark');assert plan['state']['marks'][lib_id]=='required'
        assert page.evaluate("Array.from(document.fonts).some(f=>f.family==='WikiTitleNormal'&&f.status==='loaded')")
        assert plan['state']['titleColor']=='#79d1f2' and plan['state']['treeNotes']=='安卓保存：树底补充文字'
        assert plan['state']['engravings'][0]['note']=='Android 保存测试' and plan['state']['groupNotes']['weapons']=='手机方案'
        page.locator('[data-ig=export]').first.click()
        page.wait_for_timeout(1200)
        assert saved[-1][0].endswith('一图流.png') and saved[-1][1]=='image/png'
        png=base64.b64decode(saved[-1][2]);assert png.startswith(b'\x89PNG\r\n\x1a\n')
        assert int.from_bytes(png[16:20],'big')==1920 and int.from_bytes(png[20:24],'big')==1080 and len(png)<16*1024*1024
        (ROOT/'test-results/android-infographic-export.png').write_bytes(png)
        page.locator('[data-ig=export-title]').click()
        page.wait_for_timeout(1200)
        assert saved[-1][0]=='霁月·瑟蕾妮娅-字标.png' and saved[-1][1]=='image/png'
        title_png=base64.b64decode(saved[-1][2])
        assert title_png.startswith(b'\x89PNG\r\n\x1a\n') and int.from_bytes(title_png[16:20],'big')<=2400
        (ROOT/'test-results/android-title-export.png').write_bytes(title_png)
        page.locator('#ig-title-file').set_input_files(ROOT/'test-results/title-import-fixture.jpg')
        page.wait_for_function("()=>document.querySelector('[data-cut=locate]')?.disabled===false&&document.querySelector('.ig-cutout-source')?.width===1200",timeout=120000)
        assert not page.locator('[data-cut=apply]').is_disabled()
        assert page.evaluate('WikiAndroid.back()') is True
        page.locator('.ig-cutout-dialog').wait_for(state='detached')
        page.locator('#ig-title-file').set_input_files(ROOT/'assets/brand/vipera-reference-title.png')
        page.locator('[data-cut=apply]:enabled').click()
        page.wait_for_function("()=>!document.querySelector('[data-ig=export]').disabled",timeout=60000)
        page.locator('[data-ig=save-plan]').click();page.wait_for_timeout(300)
        image_plan=json.loads(base64.b64decode(saved[-1][2]))
        assert image_plan['state']['titleMode']=='image' and image_plan['state']['customTitle'].startswith('data:image/png;base64,')
        page.locator('[data-ig-view=preview]').click()
        page.screenshot(path=str(ROOT/'test-results/android-infographic-preview.png'))
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        assert not errors,errors
        browser.close()
    report={'status':'passed','checks':['JSON backup including notes/favorites','Blob PNG export from detached anchor','Original local image save','External links delegated to browser','Back closes dialog/menu before navigation','Native dark theme synchronization','390px packaged layout','Infographic assets and 1920x1080 PNG/JSON through Android save bridge','Android back closes infographic selector','Infographic v6 background transforms, arbitrary name generation, legible cursive font and saved plan'],'errors':errors,'titleImageImport':'Offline OCR, Android back cancellation and imported PNG in native JSON export passed','requests':'All intercepted from APK assets; no network access'}
    (ROOT/'test-results/android-bridge-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    for check in report['checks']:print('PASS '+check)


if __name__=='__main__':run()
