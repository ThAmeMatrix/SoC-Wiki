"""Round 20: square map + walls/water, summon-free maxima, dialogue scroll/IME,
mechanics search examples, enhance readability.

    python -X utf8 scripts/verify_round20.py
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


def main():
    css = (ROOT / 'refinements.css').read_text('utf8')
    wu = (ROOT / 'world-ui.js').read_text('utf8')
    du = (ROOT / 'dialogues-ui.js').read_text('utf8')
    mx = (ROOT / 'mechanics-ui.js').read_text('utf8')
    ap = (ROOT / 'app.js').read_text('utf8')

    check('map frame is square', 'aspect-ratio:1/1' in css)
    check('auto-fit added', 'const fitMaps' in wu and '--fit' in wu)
    check('walls culled by compositor', '.world-iso-wall{backface-visibility:hidden}' in css)
    check('no quadrant display toggling', "data-quad=\"0\"] .world-iso-wall" not in css)
    check('pit depth uses ground floor', 'groundFloor' in wu)
    check('pits get walls', 'is-water-wall' in wu)
    check('archive excludes summons', "includes('召唤物')" in ap)
    check('dialogue IME handlers present', 'compositionend' in du and 'isComposing' in du)
    check('dialogue preserves scroll', 'preserveScroll' in du)
    check('dialogue no forced scrollIntoView', 'scrollIntoView' not in du)
    check('mechanics search excludes template details', "d.summary || ''" in mx)
    check('mechanics example updated', 'maishachongfeng' in mx)
    check('enhance uses tables', '.enh-table' in css and 'enh-table' in wu)

    errors, failed = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(offline=True, viewport={'width': 1440, 'height': 900}).new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))

        # ---- 1 ----
        page.goto(BASE + '#/maps')
        page.locator('#world-map-picker').wait_for()
        page.evaluate("""()=>{const W=window.WIKI_WORLD_DATA;
            const m=W.maps.find(x=>x.name.includes('city-os-ni00501'));
            const b=document.querySelector('[data-world-pick="'+m.id+'"]');if(b)b.click();}""")
        page.wait_for_timeout(300)
        frame = page.locator('[data-world-iso-view]').first
        bb = frame.bounding_box()
        check('map frame is square at runtime', abs(bb['width'] - bb['height']) < 3,
              f"{round(bb['width'])}x{round(bb['height'])}")
        check('frame is enlarged', bb['width'] >= 600, str(round(bb['width'])))
        check('auto-fit set', bool(page.evaluate("()=>document.querySelector('[data-world-iso-view]').style.getPropertyValue('--fit')")))
        r = page.evaluate("""()=>{const f=document.querySelector('[data-world-iso-view]');
            const pits=[...f.querySelectorAll('.world-iso-block.is-pit')];
            const zs=pits.map(e=>Number(e.style.getPropertyValue('--h')));
            const ground=[...f.querySelectorAll('.world-iso-block:not(.is-pit)')]
                .map(e=>Number(e.style.getPropertyValue('--h')));
            return {pits:pits.length,
                    pitWalls:pits.reduce((a,e)=>a+e.querySelectorAll('.world-iso-wall').length,0),
                    pitMax:Math.max(...zs),groundMin:Math.min(...ground),
                    grassWithWalls:[...f.querySelectorAll('.world-iso-block:not(.is-pit)')]
                        .filter(e=>e.querySelector('.world-iso-wall')).length,
                    grassTotal:f.querySelectorAll('.world-iso-block:not(.is-pit)').length};}""")
        check('problem map water is below every ground cell',
              r['pits'] > 0 and r['pitMax'] < r['groundMin'], str(r))
        check('water cells have side walls', r['pitWalls'] >= r['pits'] * 2, str(r))
        check('grass cells have side walls', r['grassWithWalls'] == r['grassTotal'], str(r))
        # drag -> walls never toggle display
        cx, cy = bb['x'] + bb['width'] / 2, bb['y'] + bb['height'] / 2
        page.mouse.move(cx, cy); page.mouse.down()
        page.mouse.move(cx - 120, cy + 50, steps=10); page.mouse.up()
        page.wait_for_timeout(180)
        drag = page.evaluate("""()=>{const f=document.querySelector('[data-world-iso-view]');
            const walls=[...f.querySelectorAll('.world-iso-wall')];
            const before=f.querySelector('.world-iso-block');
            return {none:walls.filter(e=>getComputedStyle(e).display==='none').length,
                    backface:getComputedStyle(walls[0]).backfaceVisibility,
                    sameNode:before===f.querySelector('.world-iso-block')};}""")
        check('rotating never toggles wall display', drag['none'] == 0, str(drag))
        check('backface culling active', drag['backface'] == 'hidden', str(drag))
        check('rotating rebuilds nothing', drag['sameNode'], str(drag))

        # ---- 2 ----
        idx = (ROOT / 'data/index.js').read_text('utf8')
        pages = json.JSONDecoder().raw_decode(idx[idx.index('=') + 1:])[0]['pages']
        cid = next(x['id'] for x in pages if x.get('type') == 'character' and not x.get('redirect'))
        page.goto(BASE + '#/page/' + str(cid))
        page.locator('.profile-stats-bars').wait_for()
        shown = page.locator('.profile-stats-bars .ig-stat-card[data-stat-key="hp"] .ig-stat-max').inner_text()
        nums = [int((x.get('stats') or {}).get('生命') or 0) for x in pages
                if x.get('type') == 'character' and not x.get('redirect')
                and '召唤物' not in (x.get('categories') or [])
                and str((x.get('stats') or {}).get('生命') or '0').isdigit()]
        check('archive max excludes summons', str(max(nums)) in shown, f'{shown} vs {max(nums)}')
        check('summon-only max not used', '6397' not in shown, shown)
        check('note explains the exclusion', '不含召唤物' in
              page.locator('.profile-stats-bars .ig-stat-note').inner_text())

        # ---- 3 ----
        page.goto(BASE + '#/dialogues')
        page.wait_for_timeout(350)
        page.evaluate("()=>window.scrollTo(0,500)")
        page.wait_for_timeout(120)
        before = page.evaluate("()=>({y:scrollY,sc:document.querySelector('.dialogue-scenes')?.scrollTop})")
        page.evaluate("""()=>{const l=document.querySelector('.dialogue-scenes');l.scrollTop=180;
            const b=[...l.querySelectorAll('.dialogue-scene')][6];if(b)b.click();}""")
        page.wait_for_timeout(280)
        after = page.evaluate("()=>({y:scrollY,sc:document.querySelector('.dialogue-scenes')?.scrollTop})")
        check('scene list scroll stays at clicked position',
              abs(after['sc'] - before['sc']) < 220 and after['sc'] > 0, f'{before} -> {after}')
        check('page scroll does not jump to top', after['y'] > 0, f'{before} -> {after}')

        # ---- 4 ----
        page.goto(BASE + '#/dialogues')
        page.wait_for_timeout(250)
        inp = page.locator('#dialogue-query')
        inp.click()
        page.evaluate("""()=>{const i=document.querySelector('#dialogue-query');
            i.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true,data:''}));
            i.value='ju';i.dispatchEvent(new InputEvent('input',{bubbles:true,data:'ju',isComposing:true}));
            i.value='拉维耶';
            i.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'拉维耶'}));}""")
        page.wait_for_timeout(380)
        check('IME composition keeps the input mounted',
              page.locator('#dialogue-query').count() == 1 and inp.input_value() == '拉维耶',
              inp.input_value())
        check('IME commit produces search hits', page.locator('.dialogue-hit').count() > 0,
              str(page.locator('.dialogue-hit').count()))
        inp.fill('放心交给我吧'); page.wait_for_timeout(380)
        check('direct Chinese search works', inp.input_value() == '放心交给我吧')

        # ---- 5 ----
        page.goto(BASE + '#/mechanics')
        page.locator('#mechanics-query').wait_for()
        ph = page.locator('#mechanics-query').get_attribute('placeholder')
        check('placeholder uses real examples', 'maishachongfeng' in ph and '聚拢 / jvlong' not in ph, ph)
        counts = {}
        for q in ('聚拢', '击退', 'maishachongfeng', 'mscf'):
            page.locator('#mechanics-query').fill(q)
            page.wait_for_timeout(180)
            counts[q] = page.locator('#mechanics-count').inner_text()
        check('聚拢 now has a discriminating result',
              '1,213 个（仅显示前 120 个）' not in counts['聚拢'], counts['聚拢'])
        check('example pinyin matches', '匹配 1 个' in counts['maishachongfeng'], counts['maishachongfeng'])
        check('example initials matches', '匹配 1 个' in counts['mscf'], counts['mscf'])

        # ---- 6 ----
        page.goto(BASE + '#/enhance')
        page.locator('#enhance-list').wait_for()
        check('conclusions are numbered cards', page.locator('.enh-rules>li').count() == 7,
              str(page.locator('.enh-rules>li').count()))
        check('ranges are real tables', page.locator('table.enh-table').count() > 0)
        check('table headers are sticky', page.evaluate(
            "()=>getComputedStyle(document.querySelector('.enh-table th')).position") == 'sticky')
        check('card has readable head + note',
              page.locator('.enhance-card .enh-head h2').count() > 0
              and page.locator('.enhance-card .enh-note').count() > 0)

        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
