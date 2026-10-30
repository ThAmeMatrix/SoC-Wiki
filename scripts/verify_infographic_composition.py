"""Verify custom canvas coordinates, readable poster compositions and reversible artwork focus offline."""
from pathlib import Path
import json
import sys
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'android/app/build/generated/wikiAssets/wiki' if '--android' in sys.argv else ROOT
OUT = ROOT / 'test-results'
OUT.mkdir(exist_ok=True)


def ready(p):
    p.wait_for_function("()=>document.querySelector('#ig-canvas')?.width>=480&&document.querySelector('[data-ig=export]')?.disabled===false", timeout=60000)


def saved(p):
    return p.evaluate("JSON.parse(localStorage.getItem('socwiki.infographic.draft.9296'))")


def export(p, name):
    with p.expect_download() as dl:
        p.locator('[data-ig=export]').first.click()
    path = OUT / ('infographic-v116-' + name + '.png')
    dl.value.save_as(path)
    assert Image.open(path).size == tuple(saved(p)['canvas'][k] for k in ['width', 'height'])
    return path


def navigation(p, key):
    p.locator(f'.ig-nav [data-ig-jump={key}]').click()


def metrics(p):
    return p.evaluate('lastComposition')


def frames(p):
    return {r['key']: r for r in metrics(p)['layoutRegions']}


def overlap(a, b):
    return max(0, min(a['x'] + a['w'], b['x'] + b['w']) - max(a['x'], b['x'])) * max(0, min(a['y'] + a['h'], b['y'] + b['h']) - max(a['y'], b['y']))


def complete_layout(p, spotlight=False):
    m = metrics(p)
    parts = frames(p)
    for r in parts.values():
        assert r['x'] >= -.1 and r['y'] >= -.1 and r['x'] + r['w'] <= m['width'] + .1 and r['y'] + r['h'] <= m['height'] + .1, r
    content = [parts[k] for k in ['tree', 'trait', 'exclusive', 'loadouts', 'loadoutNotes', 'scores', 'gear', 'stats', 'engravings', 'notes', 'author']]
    for i, a in enumerate(content):
        for b in content[i + 1:]:
            assert overlap(a, b) < 1, (a['key'], b['key'])
    if spotlight and m['width'] > m['height']:
        for r in content:
            assert overlap(r, m['heroArea']) < 1, r['key']
    assert m['minTextSize'] >= 10.9, m['minTextSize']


example = {
    'format': 'socwiki-infographic', 'version': 6,
    'state': {
        'version': 6, 'characterId': 9296, 'titleColor': '#e7bd60',
        'exclusive': 9337, 'weapons': [9337, 2921], 'accessories': [2989, 2956],
        'tarot': ['tarot-1', 'tarot-8', 'tarot-15', 'tarot-10'],
        'loadouts': [
            {'name': '爆发输出', 'slots': [9323, 9319, 9329, 9328, 9322]},
            {'name': '机动续航', 'slots': [9323, 9319, 9329, 9330, 9322]},
        ],
        'marks': {str(k): 'required' for k in [9323, 9319, 9329, 9328, 9322]},
        'engravings': [{'id': 'engraving-5', 'note': '适合主动移动后的输出场景。'}, {'id': 'engraving-10', 'note': '需要技能循环时选择。'}],
        'gearNotes': {'weapons': ['专武优先', ''], 'accessories': ['补充功能', ''], 'tarot': ['持续伤害', '', '', '']},
        'groupNotes': {'weapons': '按输出需求选择', 'accessories': '生存与输出兼顾', 'tarot': '按战场灵活调整'},
        'author': 'ThAme', 'topText': '铃兰交流群：688575530', 'topTextX': 1000, 'topTextY': 150,
        'roleText': '持续伤害 / 控场辅助', 'treeNotes': '优先解锁核心输出技能，再按战场需要补充控制和生存。',
        'notes': '利用持续伤害压制敌人，搭配机动技能调整站位。\n根据敌方阵容选择输出或辅助装备。',
        'rated': True, 'scores': [4.5, 4, 3, 5, 4.5, 3.5], 'scoreText': '综合评级：T1',
        'panelOpacity': .88, 'backgroundOpacity': .85,
        'loadoutCommentary': {'enabled': True, 'text': '先施加持续伤害，再衔接爆发。需要走位时换入位移技能；高压环境优先保证生存。', 'size': 18, 'color': '#e9deca'},
    },
}
plan = OUT / 'infographic-v116-example-plan.json'
plan.write_text(json.dumps(example, ensure_ascii=False), encoding='utf8')

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    p = browser.new_page(offline=True, viewport={'width': 1600, 'height': 1000}, accept_downloads=True, reduced_motion='reduce')
    errors = []
    p.on('pageerror', lambda e: errors.append(str(e)))
    p.goto((BASE / 'index.html').as_uri() + '#/tools/infographic')
    ready(p)
    p.evaluate("(()=>{const draw=WikiInfographicCanvas.draw;WikiInfographicCanvas.draw=async(...args)=>{const r=await draw(...args);window.lastComposition={...r,canvas:null};return r}})()")
    p.locator('#ig-import-file').set_input_files(plan)
    p.wait_for_function("()=>JSON.parse(localStorage.getItem('socwiki.infographic.draft.9296'))?.author==='ThAme'")
    ready(p)
    original = saved(p)
    assert original['canvas'] == {'width': 1920, 'height': 1080} and original['decoration']['style'] == 'gilded'
    export(p, 'gold')
    navigation(p, 'canvas')
    p.locator('[data-ig=portrait-focus]').click()
    ready(p)
    complete_layout(p, spotlight=True)
    focused = saved(p)
    assert focused['composition'] == 'spotlight' and focused['backgroundOpacity'] == 1
    for key in ['loadouts', 'loadoutCommentary', 'marks', 'weapons', 'accessories', 'tarot', 'engravings', 'notes', 'treeNotes', 'author']:
        assert focused[key] == original[key], key
    export(p, 'spotlight')
    navigation(p, 'layout')
    p.locator('.ig-editor [data-ig=layout-undo]').click()
    ready(p)
    assert saved(p)['canvas'] == original['canvas'] and saved(p)['background'] == original['background'] and saved(p)['composition'] == 'auto'
    p.locator('.ig-editor [data-ig=layout-redo]').click()
    ready(p)
    assert saved(p)['canvas'] == focused['canvas']
    navigation(p, 'canvas')
    p.locator('[data-ig-canvas-preset="1280x1920"]').click()
    ready(p)
    complete_layout(p, spotlight=True)
    export(p, 'portrait-focus')
    navigation(p, 'layout')
    p.locator('[data-ig=composition-auto]').click()
    ready(p)
    complete_layout(p)
    export(p, 'portrait')
    # Both background and dragging coordinates follow the new portrait canvas.
    navigation(p, 'background')
    p.locator('[data-ig=background-edit]').first.click()
    art = p.locator('#ig-background-canvas')
    b = art.bounding_box()
    before = saved(p)['background'].copy()
    x, y = b['x'] + b['width'] * .6, b['y'] + b['height'] * .4
    p.mouse.move(x, y); p.mouse.down(); p.mouse.move(x + 20, y + 20, steps=5); p.mouse.up()
    ready(p)
    after = saved(p)['background']
    assert abs(after['x'] - before['x'] - 20 * 1280 / b['width']) < 2
    assert abs(after['y'] - before['y'] - 20 * 1920 / b['height']) < 2
    p.locator('[data-ig=background-done]').click()
    p.locator('[data-ig=enlarge]').click()
    p.locator('[data-ig-full-mode=layout]').click()
    p.locator('[data-ig-full-select]').select_option('stats')
    p.locator('[data-ig-full-snap]').uncheck()
    for key, value in [('x', '800'), ('y', '900'), ('w', '350'), ('h', '240')]:
        p.locator(f'.ig-full-preview [data-ig-rect={key}]').fill(value); ready(p)
    overlay = p.locator('.ig-full-preview [data-ig-layout-select=stats]')
    b = overlay.bounding_box(); scale = p.locator('#ig-full-canvas').bounding_box()['width'] / 1280
    x, y = b['x'] + b['width'] / 2, b['y'] + b['height'] / 2
    p.mouse.move(x, y); p.mouse.down(); p.mouse.move(x + 40 * scale, y + 60 * scale, steps=5); p.mouse.up(); ready(p)
    assert abs(saved(p)['layout']['stats']['x'] - 840) < 2 and abs(saved(p)['layout']['stats']['y'] - 960) < 2
    pixels = p.locator('#ig-full-canvas').evaluate('c=>c.toDataURL()')
    overlay.focus(); p.keyboard.down('Space')
    assert p.locator('.ig-full-hotspots').evaluate("e=>getComputedStyle(e).visibility==='hidden'")
    p.keyboard.up('Space')
    assert p.locator('.ig-full-hotspots').is_visible()
    assert overlay.evaluate("e=>getComputedStyle(e).backgroundColor==='rgba(0, 0, 0, 0)'")
    assert not p.locator('.ig-full-hotspots .ig-layout-readout').count()
    p.locator('[data-ig-full-mode=view]').click()
    assert pixels == p.locator('#ig-full-canvas').evaluate('c=>c.toDataURL()')
    p.locator('[data-ig=close-preview]').click()
    # A nonstandard size is exact; optional proportional preservation is reversible.
    navigation(p, 'canvas')
    p.locator('[data-ig-canvas-reflow]').uncheck()
    p.get_by_label('画布宽度', exact=True).fill('1400')
    p.get_by_label('画布高度', exact=True).fill('2100')
    before = saved(p)['layout']['stats'].copy()
    p.locator('[data-ig=canvas-apply]').click(); ready(p)
    scaled = saved(p)['layout']['stats']
    assert all(abs(scaled[k] - before[k] * 1.09375) < .1 for k in ['x', 'y', 'w', 'h'])
    assert saved(p)['canvas'] == {'width': 1400, 'height': 2100}
    p.get_by_label('边框风格', exact=True).select_option('plain'); ready(p)
    assert saved(p)['decoration']['style'] == 'plain'
    p.get_by_label('边框风格', exact=True).select_option('gilded'); ready(p)
    navigation(p, 'topText')
    p.locator('[data-ig-config=topTextY]').fill('300'); ready(p)
    assert abs(frames(p)['topText']['y'] - 300) < .1
    export(p, 'custom-size')
    with p.expect_download() as dl:
        p.locator('[data-ig=save-plan]').click()
    result = OUT / 'infographic-v116-saved-plan.json'; dl.value.save_as(result)
    before = saved(p)
    p.reload(); ready(p)
    assert saved(p)['canvas'] == before['canvas'] and saved(p)['layout'] == before['layout']
    p.set_viewport_size({'width': 390, 'height': 844})
    navigation(p, 'canvas')
    assert p.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    p.screenshot(path=str(OUT / 'infographic-v116-mobile.png'))
    assert not errors, errors
    browser.close()

print('PASS offline gold/portrait/focus exports, readable nonoverlapping sections, retained content, automatic height, undo/redo, arbitrary dimensions, proportional layout, portrait dragging, unobstructed preview, persisted plans and mobile controls')
