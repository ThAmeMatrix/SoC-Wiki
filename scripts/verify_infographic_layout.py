from pathlib import Path
import json
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'test-results'
def ready(p):
    p.wait_for_function("()=>document.querySelector('#ig-canvas')?.width===1920&&!document.querySelector('[data-ig=export]')?.disabled",timeout=60000)
def draft(p):return p.evaluate("JSON.parse(localStorage.getItem('socwiki.infographic.draft.9296'))")
with sync_playwright() as pw:
    b=pw.chromium.launch();ctx=b.new_context(offline=True,viewport={'width':1600,'height':1100},reduced_motion='reduce',accept_downloads=True);p=ctx.new_page();errors=[];p.on('pageerror',lambda e:errors.append(str(e)))
    p.goto((ROOT/'index.html').as_uri()+'#/tools/infographic');ready(p)
    for key in ['weapons','accessories','tarot']:
        assert p.locator(f'[data-ig-pick={key}]').count()==1
    p.get_by_label('角色定位',exact=True).fill('持续伤害 / 控场辅助');ready(p)
    p.locator('.ig-nav [data-ig-jump=gear]').click()
    for key in ['weapons','accessories','tarot']:
        p.locator(f'[data-ig-add-gear={key}]').click();ready(p)
        assert p.locator(f'[data-ig-pick={key}]').count()==2
        p.locator(f'[data-ig-gear-note={key}]').nth(1).fill('保留第二位备注')
        p.locator(f'[data-ig-remove-gear={key}]').first.click();ready(p)
        assert draft(p)['gearNotes'][key]==['保留第二位备注']
        assert p.locator(f'[data-ig-remove-gear={key}]').first.is_disabled()
    p.locator('.ig-nav [data-ig-jump=layout]').click()
    p.locator('#ig-layout-select').select_option('trait')
    for key,value in [('w','1100'),('h','240'),('x','500'),('y','220')]:
        p.locator(f'[data-ig-rect={key}]').fill(value);ready(p)
    assert draft(p)['layout']['trait']=={'x':500,'y':220,'w':1100,'h':240}
    p.locator('.ig-preview [data-ig=layout-toggle]').click()
    assert p.locator('[data-ig-layout-select]').count()==19
    assert p.locator('[data-ig-layout-select=stats]').count()==1
    box=p.locator('[data-ig-layout-select=trait]').bounding_box();before=draft(p)['layout']['trait'].copy()
    p.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2);p.mouse.down();p.mouse.move(box['x']+box['width']/2+20,box['y']+box['height']/2+10,steps=4)
    assert 'px' in p.locator('.ig-layout-readout').inner_text()
    p.mouse.up();ready(p);assert draft(p)['layout']['trait']['x']>before['x']
    handle=p.locator('[data-ig-layout-select=trait] .ig-handle-se').bounding_box();before=draft(p)['layout']['trait'].copy()
    p.mouse.move(handle['x']+7,handle['y']+7);p.mouse.down();p.mouse.move(handle['x']+30,handle['y']+20,steps=4);p.mouse.up();ready(p)
    assert draft(p)['layout']['trait']['w']>before['w']
    # All eight handles are live: dragging the west edge grows the block to the left.
    assert p.locator('[data-ig-layout-select=trait] .ig-layout-handle').count()==8
    before=draft(p)['layout']['trait'].copy()
    west=p.locator('[data-ig-layout-select=trait] .ig-handle-w').bounding_box()
    p.mouse.move(west['x']+7,west['y']+7);p.mouse.down();p.mouse.move(west['x']-40,west['y']+7,steps=4);p.mouse.up();ready(p)
    stretched=draft(p)['layout']['trait'];assert stretched['w']>before['w'] and stretched['x']<before['x']
    # Undo and redo walk the layout history.
    p.locator('[data-ig=layout-undo]').click();ready(p);assert draft(p)['layout']['trait']==before
    p.locator('[data-ig=layout-redo]').click();ready(p);assert draft(p)['layout']['trait']==stretched
    p.locator('[data-ig=layout-undo]').click();ready(p);assert draft(p)['layout']['trait']==before
    # Drag near another panel's left edge and check the visible magnetic guide.
    box=p.locator('[data-ig-layout-select=trait]').bounding_box();canvas=p.locator('#ig-canvas').bounding_box();r=draft(p)['layout']['trait']
    sx=box['x']+box['width']/2;sy=box['y']+box['height']/2
    p.mouse.move(sx,sy);p.mouse.down();p.mouse.move(sx+(365-r['x'])*canvas['width']/1920,sy,steps=5)
    assert p.locator('.ig-layout-guide').count()>0
    p.wait_for_timeout(180)
    assert p.locator('.ig-layout-block.selected').is_visible()
    p.mouse.up();ready(p);assert abs(draft(p)['layout']['trait']['x']-370)<1
    p.locator('#ig-layout-select').select_option('role')
    for key,value in [('x','1400'),('y','120'),('w','400'),('h','50')]:p.locator(f'[data-ig-rect={key}]').fill(value);ready(p)
    p.evaluate('scrollTo(0,0)');p.screenshot(path=str(OUT/'infographic-v111-layout.png'))
    with p.expect_download() as dl:p.locator('[data-ig=save-plan]').click()
    plan=OUT/'infographic-v111-plan.json';dl.value.save_as(plan)
    saved=draft(p);p.reload();ready(p);assert draft(p)['layout']==saved['layout'];assert draft(p)['roleText']==saved['roleText']
    p.locator('#ig-import-file').set_input_files(plan);ready(p)
    with p.expect_download() as dl:p.locator('[data-ig=export]').first.click()
    dl.value.save_as(OUT/'infographic-v111-export.png')
    p.set_viewport_size({'width':390,'height':844});p.locator('[data-ig-view=preview]').click();p.locator('.ig-preview [data-ig=layout-toggle]').click()
    assert p.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    p.screenshot(path=str(OUT/'infographic-v111-mobile.png'))
    assert not errors,errors
    b.close()
print('PASS layout numeric edit, drag/resize, 19 blocks, undo/redo, role text, variable recommendation slots, minimum one, notes pairing, JSON/reload, mobile and PNG export')
