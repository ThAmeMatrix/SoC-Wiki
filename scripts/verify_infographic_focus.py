"""Check real tall portraits, padded artwork, face visibility and background gestures offline."""
from pathlib import Path
import json
import sys
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'android/app/build/generated/wikiAssets/wiki' if '--android' in sys.argv else ROOT
OUT = ROOT / 'test-results'
OUT.mkdir(exist_ok=True)


def ready(p):
    p.wait_for_function("()=>document.querySelector('#ig-canvas')?.width>=480&&!document.querySelector('[data-ig=export]')?.disabled", timeout=60000)


def stored(p, character):
    return p.evaluate('(id)=>JSON.parse(localStorage.getItem("socwiki.infographic.draft."+id))', character)


# Face rectangles are manually checked against the original images, normalized
# to the entire source including transparent margins (not inferred by the code).
CASES = [
    (9295, 'base', 'constantine', (.39, .025, .11, .09)),
    (3637, 'base', 'assassin', (.39, .025, .21, .10)),
    (9296, 'base', 'vipera-base', (.46, .25, .10, .11)),
    (9296, 'awakened', 'vipera-awakened', (.49, .30, .07, .09)),
]
report, thumbs, errors = [], [], []
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    p = browser.new_page(offline=True, viewport={'width': 1600, 'height': 1000}, reduced_motion='reduce', accept_downloads=True)
    p.on('pageerror', lambda e: errors.append(str(e)))
    p.goto((BASE / 'index.html').as_uri() + '#/tools/infographic')
    ready(p)
    p.evaluate("(()=>{const draw=WikiInfographicCanvas.draw;WikiInfographicCanvas.draw=async(...args)=>{const r=await draw(...args);window.focusResult={...r,canvas:null,characterId:args[0].character.id,portrait:args[1].background.portrait};return r}})()")
    for size in [{'width': 1920, 'height': 1080}, {'width': 1280, 'height': 1920}]:
        for character, art, name, face in CASES:
            state = {'version': 6, 'characterId': character, 'canvas': size,
                     'background': {'portrait': art, 'x': 90, 'y': -200, 'scale': 2},
                     'notes': '保留养成手记与技能资料', 'treeNotes': '优先核心技能', 'roleText': '输出 / 辅助'}
            p.locator('#ig-import-file').set_input_files({'name': 'focus-plan.json', 'mimeType': 'application/json',
                'buffer': json.dumps({'format': 'socwiki-infographic', 'version': 6, 'state': state}, ensure_ascii=False).encode('utf8')})
            p.wait_for_function('([id,art])=>window.focusResult?.characterId===id&&window.focusResult?.portrait===art', arg=[character, art])
            ready(p)
            p.locator('[data-ig=portrait-focus]').click(); ready(p)
            result = p.evaluate('focusResult')
            rect, hero = result['backgroundRect'], result['heroArea']
            x, y = rect['x'] + rect['w'] * face[0], rect['y'] + rect['h'] * face[1]
            w, h = rect['w'] * face[2], rect['h'] * face[3]
            assert x >= hero['x'] and y >= hero['y'], (name, size, 'cropped top/left', [x, y, w, h], hero)
            assert x+w <= hero['x']+hero['w'] and y+h <= hero['y']+hero['h'], (name, size, 'cropped right/bottom')
            # The wide scene keeps its established framing; only tall artwork
            # reserves the entire header boxes (which include unused text space).
            bounds = rect['contentBounds']
            for region in result['layoutRegions'] if bounds['h'] > bounds['w'] else []:
                if region['key'] not in ['title', 'subtitle', 'cv', 'sprite', 'badges']:
                    continue
                overlap = max(0, min(x+w, region['x']+region['w'])-max(x, region['x'])) * max(0, min(y+h, region['y']+region['h'])-max(y, region['y']))
                assert overlap < 1, (name, size, 'header obscures face', region['key'])
            current = stored(p, character)
            for key in ['notes', 'treeNotes', 'roleText']:
                assert current[key] == state[key]
            assert current['background'] == {'portrait': art, 'x': 0, 'y': 0, 'scale': 1}
            with p.expect_download() as dl:
                p.locator('[data-ig=export]').first.click()
            output = OUT / f'infographic-v118-focus-{name}-{size["width"]}.png'
            dl.value.save_as(output)
            im = Image.open(output).convert('RGB')
            assert im.size == (result['width'], result['height'])
            im.thumbnail((640, 600)); thumbs.append((name, im.copy()))
            report.append({'name': name, 'canvas': current['canvas'], 'face': [x, y, w, h]})

    # On a tall, padded source, all editor paths must use the same transform as
    # export. Check zoom around the pointer and undo/reload after real gestures.
    p.locator('.ig-nav [data-ig-jump=canvas]').click()
    p.get_by_label('画布宽度', exact=True).fill('1600')
    p.get_by_label('画布高度', exact=True).fill('900')
    p.locator('[data-ig=canvas-apply]').click(); ready(p)
    p.locator('[data-ig=portrait-focus]').click(); ready(p)
    p.locator('.ig-nav [data-ig-jump=background]').click()
    p.locator('.ig-editor [data-ig-art=base]').click(); ready(p)
    p.locator('[data-ig=background-edit]').first.click()
    stage = p.locator('#ig-background-canvas').bounding_box()
    before = p.evaluate('focusResult.backgroundRect')
    pixel = {'x': stage['x'] + stage['width']*.62, 'y': stage['y'] + stage['height']*.2}
    anchor = {'x': p.evaluate('focusResult.width')*.62, 'y': p.evaluate('focusResult.height')*.2}
    p.mouse.move(pixel['x'], pixel['y']); p.mouse.wheel(0, -100)
    p.wait_for_function('(scale)=>JSON.parse(localStorage.getItem("socwiki.infographic.draft.9296")).background.scale>scale', arg=1)
    ready(p); after = p.evaluate('focusResult.backgroundRect')
    for key, dim in [('x', 'w'), ('y', 'h')]:
        assert abs((anchor[key]-before[key])/before[dim] - (anchor[key]-after[key])/after[dim]) < .001
    base = stored(p, 9296)['background']
    p.mouse.down(); p.mouse.move(pixel['x']+24, pixel['y']+15, steps=4); p.mouse.up(); ready(p)
    moved = stored(p, 9296)['background']
    assert abs(moved['x']-base['x']-24*p.evaluate('focusResult.width')/stage['width']) < 2
    assert abs(moved['y']-base['y']-15*p.evaluate('focusResult.height')/stage['height']) < 2
    p.locator('[data-ig=background-done]').click()
    p.reload(); ready(p)
    assert stored(p, 9296)['background'] == moved
    assert p.locator('.ig-editor>.ig-section').first.get_attribute('data-module') == 'character'
    assert p.locator('[data-ig-nav-group]').first.get_attribute('data-ig-nav-group') == 'character'
    assert p.locator('.ig-section').first.locator('.ig-step').inner_text() == '01'
    assert not errors, errors
    browser.close()

sheet = Image.new('RGB', (1280, 640*((len(thumbs)+1)//2)), '#152329')
draw = ImageDraw.Draw(sheet)
for i, (label, im) in enumerate(thumbs):
    x, y = (i%2)*640, (i//2)*640
    sheet.paste(im, (x, y+24)); draw.text((x+10, y+6), label, fill='white')
sheet.save(OUT / 'infographic-v118-focus-review.jpg')
(OUT / 'infographic-focus-verification.json').write_text(json.dumps({'status': 'passed', 'cases': report, 'errors': errors}, ensure_ascii=False, indent=2), encoding='utf8')
print('PASS eight offline portrait exports with visible faces, tall and padded artwork, landscape/portrait canvases, anchored zoom, dragging, reload and character-first navigation')
