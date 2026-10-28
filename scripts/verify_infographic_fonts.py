"""Exercise fresh English-only signatures and font-loading recovery under the offline CSP."""
from pathlib import Path
import json
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    plan = json.loads((ROOT / 'test-results/infographic-example.json').read_text(encoding='utf-8'))['state']
    plan['author'] = 'Aurelia Nightingale'
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(offline=True)
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script('localStorage.setItem("socwiki.infographic.draft.9296",' + json.dumps(json.dumps(plan, ensure_ascii=False)) + ');localStorage.setItem("socwiki.infographic.last","9296");')
        blocked = [False]

        def fail_once(route):
            if not blocked[0]:
                blocked[0] = True
                route.abort()
            else:
                route.continue_()

        page.route('**/assets/fonts/infographic-signature-latin.js', fail_once)
        page.goto((ROOT / 'index.html').as_uri() + '#/tools/infographic')
        page.wait_for_selector('.ig-retry:not([hidden])', timeout=60000)
        assert page.locator('[data-ig=export]').first.is_disabled()
        assert '签名字体' in page.locator('.ig-render-status').inner_text()
        page.locator('[data-ig=retry-render]').click()
        page.wait_for_function("()=>!document.querySelector('[data-ig=export]').disabled", timeout=60000)
        faces = page.evaluate("Array.from(document.fonts).map(f=>({family:f.family,status:f.status}))")
        assert {'family': 'WikiSignatureLatin', 'status': 'loaded'} in faces
        assert not any(face['family'] == 'WikiSignature' for face in faces)
        # An unseen character id and name must render without per-character baked art.
        title_context = browser.new_context(offline=True)
        title_page = title_context.new_page()
        title_page.on('pageerror', lambda error: errors.append(str(error)))
        title_plan = {**plan, 'author': '', 'titleName': '霁月·瑟蕾妮娅', 'titleMode':'text'}
        title_page.add_init_script('localStorage.setItem("socwiki.infographic.draft.9296",' + json.dumps(json.dumps(title_plan, ensure_ascii=False)) + ');localStorage.setItem("socwiki.infographic.last","9296");')
        title_blocked = [False]
        def fail_title_once(route):
            if not title_blocked[0]:
                title_blocked[0] = True
                route.abort()
            else:
                route.continue_()
        title_page.route('**/assets/fonts/infographic-normal-font.js', fail_title_once)
        title_page.goto((ROOT / 'index.html').as_uri() + '#/tools/infographic')
        title_page.wait_for_selector('.ig-retry:not([hidden])', timeout=60000)
        assert '题名字体' in title_page.locator('.ig-render-status').inner_text()
        assert title_page.locator('[data-ig=export-title]').is_disabled()
        title_page.locator('[data-ig=retry-render]').click()
        title_page.wait_for_function("()=>!document.querySelector('[data-ig=export-title]').disabled", timeout=60000)
        assert title_page.evaluate("Array.from(document.fonts).some(f=>f.family==='WikiTitleNormal'&&f.status==='loaded')")
        future = title_page.evaluate("""async()=>{
          const result=await WikiInfographicCanvas.titleArtwork({character:{id:999999,name:'龘龍鳳凰𠮷·霁月'}},{titleName:'',titleColor:'#79d1f2'},WIKI_INFOGRAPHIC_DATA);
          return {source:result.source,missing:result.missing,width:result.width,height:result.height,name:result.name};
        }""")
        assert future['source'] == 'font' and future['missing'] == [] and future['width'] > 200
        title_page.get_by_label('角色显示名', exact=True).fill('🦄')
        title_page.wait_for_function("()=>!document.querySelector('[data-ig=export-title]').disabled", timeout=60000)
        assert '不在内置字库中' in title_page.locator('[data-ig-title-status]').inner_text()
        assert not errors, errors
        browser.close()
    report = {'status': 'passed', 'checks': ['Fresh English signature loads the Latin font offline', 'Missing Latin font blocks export with an explanation', 'Retry recovers without a Chinese-font dependency', 'Missing title font blocks export and recovers on retry', 'Unknown future character id, traditional characters and supplementary-plane glyphs render offline', 'Unsupported characters receive an explicit fallback notice'], 'errors': errors}
    (ROOT / 'test-results/infographic-font-verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('PASS legible English, full title font, future character names, rare glyphs, missing-font recovery and offline CSP.')


if __name__ == '__main__':
    main()
