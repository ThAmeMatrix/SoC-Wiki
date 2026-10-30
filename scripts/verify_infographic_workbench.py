"""Exercise sticky actions, grouped settings and portable author artwork entirely offline."""
from pathlib import Path
import base64
import json
import sys
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'android/app/build/generated/wikiAssets/wiki' if '--android' in sys.argv else ROOT
OUT = ROOT / 'test-results'
OUT.mkdir(exist_ok=True)
FONT = Path('C:/Windows/Fonts/arial.ttf')
fixture = OUT / 'author-lettering-fixture.jpg'
im = Image.new('RGB', (1200, 600), '#112631')
d = ImageDraw.Draw(im)
d.text((100, 180), 'ThAme', font=ImageFont.truetype(str(FONT), 180), fill='#f2dbab')
im.save(fixture, quality=95)


def ready(p):
    p.wait_for_function("()=>document.querySelector('#ig-canvas')?.width>=480&&document.querySelector('[data-ig=export]')?.disabled===false", timeout=60000)


def stored(p):
    return p.evaluate("JSON.parse(localStorage.getItem('socwiki.infographic.draft.9296'))")


def nav(p, key):
    if p.locator('.ig-nav details').get_attribute('open') is None:
        p.locator('.ig-nav summary').click()
    p.locator(f'.ig-nav [data-ig-jump={key}]').click()


def export(p, name):
    with p.expect_download() as dl:
        p.locator('[data-ig=export]').first.click()
    dl.value.save_as(OUT / name)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    p = browser.new_page(offline=True, viewport={'width': 1600, 'height': 1000}, reduced_motion='reduce', accept_downloads=True)
    errors = []
    p.on('pageerror', lambda e: errors.append(str(e)))
    p.goto((BASE / 'index.html').as_uri() + '#/tools/infographic')
    ready(p)
    p.evaluate("(()=>{const draw=WikiInfographicCanvas.draw;WikiInfographicCanvas.draw=async(...args)=>{const r=await draw(...args);window.workbenchResult={...r,canvas:null};return r}})()")
    modules = p.locator('.ig-editor>.ig-section').evaluate_all('(els)=>els.map(e=>e.dataset.module)')
    groups = p.locator('[data-ig-nav-group]').evaluate_all('(els)=>els.map(e=>e.dataset.igNavGroup)')
    assert modules == groups == ['character', 'workspace', 'background', 'skills', 'equipment', 'assessment', 'publication']
    for selector in ['[data-ig-art=base]', '[data-ig-art=awakened]', '[data-ig-style=backgroundOpacity]']:
        assert p.locator('.ig-editor ' + selector).first.evaluate("e=>e.closest('[data-module]').dataset.module") == 'background'
    assert p.locator('.ig-editor [data-ig-style=markWidth]').evaluate("e=>e.closest('[data-module]').dataset.module") == 'skills'
    assert p.locator('[data-ig=portrait-focus]').count() == p.locator('[data-ig=layout-arrange]').count() == 1
    # Search keeps module context, and all matching background controls are co-located.
    p.get_by_label('搜索修改区域', exact=True).fill('背景')
    assert p.locator('[data-ig-nav-group]').count() == 1
    assert p.locator('[data-ig-nav-group]').get_attribute('data-ig-nav-group') == 'background'
    p.get_by_label('搜索修改区域', exact=True).fill('')
    nav(p, 'author')
    p.get_by_label('制作人名字', exact=True).fill('ThAme'); ready(p)
    assert stored(p)['authorFont'] == 'signature'
    p.locator('[data-ig=portrait-focus]').click(); ready(p)
    original = stored(p)
    p.locator('[data-ig=layout-arrange]').click(); ready(p)
    arranged = stored(p)
    assert arranged['composition'] == 'information' and arranged['layout'] == {}
    for key in ['background', 'backgroundOpacity', 'author', 'marks', 'loadouts', 'weapons', 'accessories', 'tarot', 'engravings']:
        assert arranged[key] == original[key], key
    result = p.evaluate('workbenchResult')
    assert result['heroArea'] is None and result['minTextSize'] >= 10.9
    parts = [r for r in result['layoutRegions'] if r['key'] in ['tree', 'trait', 'exclusive', 'loadouts', 'gear', 'scores', 'stats', 'engravings', 'notes', 'author']]
    for i, a in enumerate(parts):
        for b in parts[i + 1:]:
            overlap = max(0, min(a['x']+a['w'], b['x']+b['w'])-max(a['x'], b['x'])) * max(0, min(a['y']+a['h'], b['y']+b['h'])-max(a['y'], b['y']))
            assert overlap < 1, (a['key'], b['key'])
    nav(p, 'layout')
    p.locator('.ig-editor [data-ig=layout-undo]').click(); ready(p)
    assert stored(p)['composition'] == 'spotlight'
    p.locator('.ig-editor [data-ig=layout-redo]').click(); ready(p)
    assert stored(p)['composition'] == 'information'
    export(p, 'infographic-v117-information.png')
    nav(p, 'author')
    for value in ['serif', 'sans', 'signature']:
        p.get_by_label('作者字体', exact=True).select_option(value); ready(p)
        assert stored(p)['authorFont'] == value
        export(p, 'infographic-v117-author-' + value + '.png')
    p.locator('#ig-author-font-file').set_input_files(FONT)
    p.wait_for_function("()=>JSON.parse(localStorage.getItem('socwiki.infographic.draft.9296'))?.authorFont==='custom'"); ready(p)
    custom = stored(p)['authorCustomFont']
    assert custom['name'] == 'arial.ttf' and custom['data'].startswith('data:font/ttf;base64,')
    assert p.evaluate("Array.from(document.fonts).some(f=>f.family.startsWith('WikiAuthor')&&f.status==='loaded')")
    # Invalid files cannot replace the last valid font.
    bad = OUT / 'invalid-author-font.woff2'; bad.write_bytes(b'invalid font')
    p.locator('#ig-author-font-file').set_input_files(bad)
    p.wait_for_function("()=>document.querySelector('#toast').textContent.includes('字体无法加载')")
    assert stored(p)['authorCustomFont'] == custom
    # Shared OCR/cutout path uses author-specific labels and preserves an actual alpha mask.
    p.locator('#ig-author-file').set_input_files(fixture)
    p.get_by_role('dialog', name='提取作者签名', exact=True).wait_for()
    p.wait_for_function("()=>document.querySelector('[data-cut=locate]')?.disabled===false&&document.querySelector('.ig-cutout-source')?.width===1200", timeout=120000)
    assert not p.locator('[data-cut=apply]').is_disabled()
    p.locator('[data-cut=apply]').click()
    p.wait_for_function("()=>JSON.parse(localStorage.getItem('socwiki.infographic.draft.9296'))?.authorMode==='image'"); ready(p)
    author_image = stored(p)['authorImage']
    assert author_image.startswith('data:image/png;base64,') and len(author_image) < 1000000
    image_path = OUT / 'infographic-v117-author-cutout.png'
    image_path.write_bytes(base64.b64decode(author_image.split(',')[1]))
    alpha = Image.open(image_path).getchannel('A')
    assert alpha.getextrema()[0] == 0 and alpha.getextrema()[1] > 200
    export(p, 'infographic-v117-author-image.png')
    p.locator('[data-ig-author-mode=text]').click(); ready(p)
    assert stored(p)['authorImage'] == author_image and stored(p)['authorFont'] == 'custom'
    p.locator('[data-ig-author-mode=image]').click(); ready(p)
    # PNG, JSON and reload keep the independent author art and custom font.
    with p.expect_download() as dl:
        p.locator('[data-ig=save-plan]').click()
    plan = OUT / 'infographic-v117-author-plan.json'; dl.value.save_as(plan)
    p.locator('[data-ig=author-image-reset]').click(); ready(p)
    assert stored(p)['authorImage'] is None
    p.locator('#ig-import-file').set_input_files(plan)
    p.wait_for_function("()=>JSON.parse(localStorage.getItem('socwiki.infographic.draft.9296'))?.authorMode==='image'"); ready(p)
    assert stored(p)['authorImage'] == author_image and stored(p)['authorCustomFont'] == custom
    p.reload(); ready(p)
    assert stored(p)['composition'] == 'information' and stored(p)['authorImage'] == author_image
    # Both actions stay on screen at desktop, tablet and phone widths after long scrolling.
    for width in [1600, 1100, 390]:
        p.set_viewport_size({'width': width, 'height': 900})
        nav(p, 'author')
        p.locator('.ig-author-controls').scroll_into_view_if_needed()
        p.wait_for_timeout(100)
        toolbar = p.locator('.ig-toolbar').bounding_box()
        header = p.locator('.topbar').bounding_box()
        assert toolbar['y'] >= header['height'] - 1 and toolbar['y'] + toolbar['height'] < 400, toolbar
        for action in ['portrait-focus', 'layout-arrange']:
            assert p.locator(f'[data-ig={action}]').evaluate("e=>{const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}"), action
        assert p.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        p.screenshot(path=str(OUT / f'infographic-v117-workbench-{width}.png'))
    assert not errors, errors
    browser.close()

print('PASS seven grouped modules, coherent background controls, sticky actions at desktop/tablet/phone widths, readable information layout, reversible actions, author fonts/local font validation, offline OCR/alpha extraction, PNG/JSON/reload and independent author artwork')
