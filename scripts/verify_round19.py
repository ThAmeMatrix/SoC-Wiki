"""Round 19: smooth map camera, theme-aware ordered stat bars, archive layout.

    python -X utf8 scripts/verify_round19.py
"""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / 'index.html').as_uri()
failures = []


def check(name, ok, detail=''):
    print(('PASS ' if ok else 'FAIL ') + name + (f' :: {detail}' if detail else ''), flush=True)
    if not ok:
        failures.append(name)


ORDER = ['物攻', '魔攻', '物防', '魔防', '生命', '速度']


def main():
    sb = (ROOT / 'stat-bars.js').read_text('utf8')
    wu = (ROOT / 'world-ui.js').read_text('utf8')

    # ---- 1. static perf guarantees ----
    check('camera uses rAF coalescing', 'requestAnimationFrame(flushCam)' in wu)
    check('zoom does not rebuild DOM', 'frame.replaceWith' not in wu)
    check('generated map markup is cached', '_isoCache' in wu and '_isoKey' in wu)
    # Round 20 replaced quadrant display toggling with compositor backface
    # culling, so rotating never changes any wall's display state.
    check('walls culled by backface, not display toggling',
          "data-quad=\"0\"] .world-iso-wall" not in (ROOT / 'refinements.css').read_text('utf8'))
    check('search input is throttled', 'searchFrame' in wu)
    check('picker reuses buttons', 'dataset.ids' in wu)

    errors, failed = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(offline=True, viewport={'width': 1440, 'height': 900}).new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))

        # ---- 1. runtime ----
        page.goto(BASE + '#/maps')
        page.locator('#world-map-picker').wait_for()
        cam = page.evaluate("""()=>{
            const f=document.querySelector('[data-world-iso-view]');
            const first=f.querySelector('.world-iso-block');
            f.dispatchEvent(new PointerEvent('pointerdown',{clientX:400,clientY:400,pointerId:1,bubbles:true}));
            const t0=performance.now();
            for(let i=0;i<60;i++) f.dispatchEvent(new PointerEvent('pointermove',
                {clientX:400+i*3,clientY:400+i,pointerId:1,bubbles:true}));
            const dragMs=performance.now()-t0;
            f.dispatchEvent(new PointerEvent('pointerup',{pointerId:1,bubbles:true}));
            const t1=performance.now();
            for(let i=0;i<10;i++) f.dispatchEvent(new WheelEvent('wheel',
                {deltaY:-100,bubbles:true,cancelable:true}));
            const wheelMs=performance.now()-t1;
            return {sameNode:first===f.querySelector('.world-iso-block'),
                    dragMs:Math.round(dragMs),wheelMs:Math.round(wheelMs),
                    hidden:[...f.querySelectorAll('.world-iso-wall')]
                      .filter(e=>getComputedStyle(e).display==='none').length,
                    walls:f.querySelectorAll('.world-iso-wall').length,
                    frameW:f.getBoundingClientRect().width,
                    frameH:f.getBoundingClientRect().height};}""")
        check('drag and zoom never rebuild the map DOM', cam['sameNode'], str(cam))
        check('60 pointer moves stay within one frame budget', cam['dragMs'] < 32, str(cam['dragMs']) + 'ms')
        check('10 zoom steps are effectively free', cam['wheelMs'] < 32, str(cam['wheelMs']) + 'ms')
        check('no wall display toggling during drag', cam['hidden'] == 0, str(cam))
        check('map frame is square and enlarged',
              cam['frameH'] >= 600 and abs(cam['frameW'] - cam['frameH']) < 3, str(cam))
        page.wait_for_timeout(120)
        check('camera label updated through rAF',
              '水平' in page.locator('.world-iso-cam').first.inner_text())
        # biggest map
        big = page.evaluate("()=>window.WIKI_WORLD_DATA.maps.reduce((a,m)=>m.cells.length>a.cells.length?m:a).id")
        page.evaluate("""id=>{const b=document.querySelector('[data-world-pick="'+id+'"]');if(b)b.click();}""", big)
        page.wait_for_timeout(250)
        big_info = page.evaluate("""()=>{const f=document.querySelector('[data-world-iso-view]');
            const first=f.querySelector('.world-iso-block');const t0=performance.now();
            for(let i=0;i<20;i++) f.dispatchEvent(new WheelEvent('wheel',
                {deltaY:i%2?-100:100,bubbles:true,cancelable:true}));
            return {ms:Math.round(performance.now()-t0),same:first===f.querySelector('.world-iso-block'),
                    cells:f.querySelectorAll('.world-iso-block').length};}""")
        check('largest map (700+ cells) zooms without rebuild',
              big_info['same'] and big_info['ms'] < 32 and big_info['cells'] > 600, str(big_info))
        # near horizon shows all walls
        page.evaluate("""()=>{const W=window.WIKI_WORLD_DATA;
            const f=document.querySelector('[data-world-iso-view]');
            f.dispatchEvent(new PointerEvent('pointerdown',{clientX:400,clientY:400,pointerId:2,bubbles:true}));
            f.dispatchEvent(new PointerEvent('pointermove',{clientX:360,clientY:200,pointerId:2,bubbles:true}));
            f.dispatchEvent(new PointerEvent('pointerup',{pointerId:2,bubbles:true}));}""")
        page.wait_for_timeout(120)
        horizon = page.evaluate("""()=>{const f=document.querySelector('[data-world-iso-view]');
            return {quad:f.dataset.quad,tilt:Number(f.dataset.tilt),
                    hidden:[...f.querySelectorAll('.world-iso-wall')]
                      .filter(e=>getComputedStyle(e).display==='none').length};}""")
        check('near-horizon keeps every wall visible',
              horizon['hidden'] == 0 and horizon['tilt'] >= 70, str(horizon))

        # ---- 2. panel: order + day/night ----
        page.goto(BASE + '#/tools/panel')
        page.locator('#panel-output').wait_for()
        labels = page.locator('#panel-output .ig-stat-label').all_inner_texts()
        check('panel shows six stats in infographic order', labels == ORDER, str(labels))
        vals = page.locator('#panel-output .ig-stat-current').all_inner_texts()
        check('speed is shown', len(vals) == 6 and vals[5] != '—', str(vals))
        check('paired two-column grid',
              len(page.evaluate("()=>getComputedStyle(document.querySelector('#panel-output .ig-stat-grid')).gridTemplateColumns.split(' ')")) == 2)
        def panel_colours(dark):
            page.evaluate("d=>document.body.classList.toggle('dark',d)", dark)
            page.wait_for_timeout(120)
            return page.evaluate("""()=>{const e=document.querySelector('#panel-output .ig-stat-card');
                const v=document.querySelector('#panel-output .ig-stat-current');
                return {bg:getComputedStyle(e).backgroundColor,val:getComputedStyle(v).color};}""")
        light, dark = panel_colours(False), panel_colours(True)
        check('panel card colours switch with theme', light['bg'] != dark['bg'], f'{light} vs {dark}')
        check('panel value colours switch with theme', light['val'] != dark['val'], f'{light} vs {dark}')
        check('panel light theme follows surface', '242' in light['bg'], light['bg'])
        check('panel dark theme uses infographic navy', '29, 53, 64' in dark['bg'], dark['bg'])
        # no clipping in narrow column
        overflow = page.evaluate("""()=>{const g=document.querySelector('#panel-output .ig-stat-grid');
            const c=document.querySelector('#panel-output .ig-stat-card');
            return {grid:g.scrollWidth-g.clientWidth,card:c.scrollWidth-c.clientWidth};}""")
        check('panel cards do not overflow right column', overflow['card'] <= 2 and overflow['grid'] <= 2,
              str(overflow))

        # ---- 3. archive: layout + theme ----
        idx = (ROOT / 'data/index.js').read_text('utf8')
        pages = json.JSONDecoder().raw_decode(idx[idx.index('=') + 1:])[0]['pages']
        cid = next(x['id'] for x in pages if x.get('type') == 'character' and not x.get('redirect'))
        page.goto(BASE + '#/page/' + str(cid))
        page.locator('.profile-stats-bars').wait_for()
        outer = page.evaluate("()=>getComputedStyle(document.querySelector('.profile-stats.profile-stats-bars')).display")
        check('legacy 3-column grid no longer splits the bars', outer == 'block', outer)
        alabels = page.locator('.profile-stats-bars .ig-stat-label').all_inner_texts()
        check('archive uses the same six-stat order', alabels == ORDER, str(alabels))
        check('archive cards are plain tiles (no bevel)',
              page.evaluate("()=>getComputedStyle(document.querySelector('.profile-stats-bars .ig-stat-card')).clipPath") == 'none')
        def archive_colours(dark):
            page.evaluate("d=>document.body.classList.toggle('dark',d)", dark)
            page.wait_for_timeout(120)
            return page.evaluate("""()=>{const e=document.querySelector('.profile-stats-bars .ig-stat-card');
                const v=document.querySelector('.profile-stats-bars .ig-stat-current');
                return {bg:getComputedStyle(e).backgroundColor,val:getComputedStyle(v).color};}""")
        al, ad = archive_colours(False), archive_colours(True)
        check('archive card colours switch with theme', al['bg'] != ad['bg'], f'{al} vs {ad}')
        check('archive value colours switch with theme', al['val'] != ad['val'], f'{al} vs {ad}')
        check('archive light theme matches wiki surfaces', '242' in al['bg'], al['bg'])
        before = page.locator('.profile-stats-bars .ig-stat-current').first.inner_text()
        page.locator('[data-level="base"]').click()
        page.wait_for_timeout(250)
        after = page.locator('.profile-stats-bars .ig-stat-current').first.inner_text()
        check('initial/max switch still works', before != after, f'{before} -> {after}')

        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
