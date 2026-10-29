"""Verify enlarged layout editing, coordinate scaling, history and offline badge layers."""
from pathlib import Path
import json
import sys
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'android/app/build/generated/wikiAssets/wiki' if '--android' in sys.argv else ROOT
OUT=ROOT/'test-results'

def ready(p):
    p.wait_for_function("()=>document.querySelector('#ig-canvas')?.width===1920&&!document.querySelector('[data-ig=export]')?.disabled",timeout=60000)

def stored(p):
    return p.evaluate("JSON.parse(localStorage.getItem('socwiki.infographic.draft.9296'))")

def rect(p):
    return {key:float(p.locator(f'.ig-full-preview [data-ig-rect={key}]').input_value()) for key in ['x','y','w','h']}

def aligned(p):
    a=p.locator('#ig-full-canvas').bounding_box();b=p.locator('.ig-full-hotspots').bounding_box()
    assert all(abs(a[key]-b[key])<1 for key in ['x','y','width','height']),(a,b)
    return a

def drag(p,key,dx,dy,handle=None):
    scale=aligned(p)['width']/1920
    target=p.locator(f'.ig-full-preview [data-ig-layout-select={key}]'+(f' .ig-handle-{handle}' if handle else ''))
    target.scroll_into_view_if_needed();box=target.bounding_box()
    x=box['x']+box['width']/2;y=box['y']+box['height']/2
    p.mouse.move(x,y);p.mouse.down();p.mouse.move(x+dx*scale,y+dy*scale,steps=5);p.mouse.up();ready(p)

with sync_playwright() as pw:
    browser=pw.chromium.launch();context=browser.new_context(offline=True,viewport={'width':1600,'height':1000},reduced_motion='reduce',accept_downloads=True)
    p=context.new_page();errors=[];requests=[]
    p.add_init_script("window.badgeBounds=[];const draw=CanvasRenderingContext2D.prototype.drawImage;CanvasRenderingContext2D.prototype.drawImage=function(image,...a){if(this.canvas.width===1920&&a.length===4&&a[0]>=1600&&a[1]>40&&a[1]<150)window.badgeBounds.push(a);return draw.call(this,image,...a);};")
    p.on('pageerror',lambda e:errors.append(str(e)));p.on('request',lambda r:requests.append(r.url))
    p.goto((BASE/'index.html').as_uri()+'#/tools/infographic');ready(p)
    # Both archived layers are loaded for the current profession, with all seven backgrounds bundled.
    data=p.evaluate('WIKI_INFOGRAPHIC_DATA');assert len(data['badges']['professionBackgrounds'])==7
    bg=data['badges']['professionBackgrounds']['突袭者']
    assert p.locator('.ig-profession-badge img').count()==2
    assert p.locator('.ig-profession-badge img').first.get_attribute('src')==bg
    assert any(data['assets'][bg] in url for url in requests)
    assert all(x>=1718 and x+w<=1896.1 and y>=50 and y+h<=115.1 for x,y,w,h in p.evaluate('badgeBounds')),p.evaluate('badgeBounds')
    p.locator('[data-ig=enlarge]').click()
    assert p.locator('[data-ig-full-mode=view]').get_attribute('aria-pressed')=='true'
    p.locator('[data-ig-full-mode=layout]').click()
    assert p.locator('.ig-full-preview [data-ig-layout-select]').count()==19
    aligned(p)
    p.locator('[data-ig-full-select]').select_option('stats')
    p.locator('[data-ig-full-snap]').uncheck()
    # Numerically position a block where it remains visible in both fit and native size views.
    for key,value in [('x','800'),('y','400'),('w','300'),('h','230')]:
        p.locator(f'.ig-full-preview [data-ig-rect={key}]').fill(value);ready(p)
    assert stored(p)['layout']['stats']=={'x':800,'y':400,'w':300,'h':230}
    before=rect(p);drag(p,'stats',60,30);moved=stored(p)['layout']['stats']
    assert abs(moved['x']-before['x']-60)<2 and abs(moved['y']-before['y']-30)<2,moved
    assert p.locator('.ig-full-preview').is_visible()
    before=moved.copy();drag(p,'stats',40,20,'se');resized=stored(p)['layout']['stats']
    assert abs(resized['w']-before['w']-40)<2 and abs(resized['h']-before['h']-20)<2,resized
    p.locator('.ig-full-preview [data-ig=layout-undo]').click();ready(p);assert stored(p)['layout']['stats']==before
    p.locator('.ig-full-preview [data-ig=layout-redo]').click();ready(p);assert stored(p)['layout']['stats']==resized
    # Magnetic guides and source-space coordinates also work within the modal.
    p.locator('[data-ig-full-select]').select_option('trait')
    p.locator('.ig-full-preview [data-ig-rect=w]').fill('1100');ready(p)
    p.locator('.ig-full-preview [data-ig-rect=x]').fill('450');ready(p)
    p.locator('[data-ig-full-snap]').check();r=rect(p);scale=aligned(p)['width']/1920
    box=p.locator('.ig-full-preview [data-ig-layout-select=trait]').bounding_box();x=box['x']+box['width']/2;y=box['y']+box['height']/2
    p.mouse.move(x,y);p.mouse.down();p.mouse.move(x+(365-r['x'])*scale,y,steps=5)
    assert p.locator('.ig-full-preview .ig-layout-guide').count()>0
    p.mouse.up();ready(p);assert abs(stored(p)['layout']['trait']['x']-370)<1,stored(p)['layout']['trait']
    p.locator('[data-ig-full-select]').select_option('stats');p.locator('[data-ig-full-snap]').uncheck()
    p.locator('[data-ig=zoom-preview]').click();assert p.locator('.ig-full-stage').get_attribute('class').endswith('actual-size')
    assert abs(aligned(p)['width']-1920)<1
    before=stored(p)['layout']['stats'].copy();drag(p,'stats',32,24)
    assert abs(stored(p)['layout']['stats']['x']-before['x']-32)<2
    p.locator('[data-ig=zoom-preview]').click();aligned(p)
    p.screenshot(path=str(OUT/'infographic-v114-full-layout.png'))
    # View mode removes all layout handles without changing the image or exiting the modal.
    pixels=p.locator('#ig-full-canvas').evaluate('c=>c.toDataURL()')
    p.locator('[data-ig-full-mode=view]').click()
    assert not p.locator('.ig-full-layout-tools').is_visible()
    assert p.locator('.ig-full-preview [data-ig-layout-select]').count()==0
    assert pixels==p.locator('#ig-full-canvas').evaluate('c=>c.toDataURL()')
    p.locator('[data-ig-full-mode=layout]').click();assert p.locator('.ig-full-preview [data-ig-layout-select]').count()==19
    assert pixels==p.locator('#ig-full-canvas').evaluate('c=>c.toDataURL()')
    with p.expect_download() as dl:p.locator('.ig-full-preview [data-ig=export]').click()
    dl.value.save_as(OUT/'infographic-v114-full-layout-export.png')
    saved=stored(p)['layout'];p.locator('[data-ig=close-preview]').click()
    assert p.locator('.ig-canvas-wrap [data-ig-layout-select=stats]').count()==1
    p.reload();ready(p);assert stored(p)['layout']==saved
    # A phone can enter both modes, edit numerically and inspect the 1920px canvas by scrolling.
    p.set_viewport_size({'width':390,'height':844});p.locator('[data-ig-view=preview]').click();p.locator('[data-ig=enlarge]').click();p.locator('[data-ig-full-mode=layout]').click()
    aligned(p);p.locator('[data-ig-full-select]').select_option('stats');p.locator('.ig-full-preview [data-ig-rect=w]').fill('340');ready(p)
    assert stored(p)['layout']['stats']['w']==340
    p.locator('[data-ig=zoom-preview]').click();aligned(p)
    p.locator('.ig-full-stage').evaluate('el=>{el.scrollLeft=700;el.scrollTop=300}')
    assert p.locator('.ig-full-stage').evaluate('el=>el.scrollLeft')>0
    p.locator('[data-ig=zoom-preview]').click();p.screenshot(path=str(OUT/'infographic-v114-full-mobile.png'))
    assert p.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    p.locator('[data-ig-full-mode=view]').click();p.keyboard.press('Escape')
    assert not p.locator('.ig-full-preview').is_visible()
    # A four-icon row must retain the left edge of the destroyer's diamond.
    p.set_viewport_size({'width':1600,'height':1000});p.locator('[data-ig-pick=character]').click();p.locator('#ig-picker-search').fill('贝拉');p.locator('[data-ig-choice="887"]').click();ready(p)
    assert p.locator('.ig-profession-badge img').first.get_attribute('src')==data['badges']['professionBackgrounds']['毁灭者']
    assert all(x>=1718 and x+w<=1896.1 and y>=50 and y+h<=115.1 for x,y,w,h in p.evaluate('badgeBounds')),p.evaluate('badgeBounds')
    with p.expect_download() as dl:p.locator('[data-ig=export]').first.click()
    dl.value.save_as(OUT/'infographic-v114-bella.png')
    assert not errors,errors
    browser.close()
print('PASS complete profession source layers; enlarged fit/native drag, resize, snapping, numeric coordinates, undo/redo, mode switching, PNG, saved layout and mobile scroll')
