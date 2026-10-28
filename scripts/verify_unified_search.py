"""Exercise semantic search through the site's existing global and full-page search."""
from pathlib import Path
from urllib.parse import quote,urlsplit,unquote
import json,re,sys
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
ANDROID='--android' in sys.argv
checks=[];errors=[];network=[]
with sync_playwright() as pw:
    browser=pw.chromium.launch()
    context=browser.new_context(offline=not ANDROID,viewport={'width':1440,'height':1000})
    p=context.new_page();p.on('pageerror',lambda e:errors.append(str(e)))
    if ANDROID:
        assets=(ROOT/'android/app/build/generated/wikiAssets').resolve()
        def serve(r):
            u=urlsplit(r.request.url)
            if u.netloc!='appassets.androidplatform.net':network.append(r.request.url);r.abort();return
            path=(assets/unquote(u.path).removeprefix('/assets/')).resolve()
            assert path.is_relative_to(assets) and path.is_file(),path
            mime={'.js':'text/javascript','.html':'text/html','.css':'text/css','.svg':'image/svg+xml','.webp':'image/webp','.png':'image/png'}.get(path.suffix,'application/octet-stream')
            r.fulfill(path=path,content_type=mime)
        context.route('**/*',serve)
        base='https://appassets.androidplatform.net/assets/wiki/index.html'
    else:
        base=(ROOT/'index.html').as_uri()
        p.on('request',lambda r:network.append(r.url) if r.url.startswith(('http:','https:')) else None)
    def go(fragment):
        p.goto(base+fragment);p.locator('#search-page-query').wait_for();p.locator('.loading').wait_for(state='hidden')
    def fill(query):
        p.locator('#search-page-query').fill(query);p.wait_for_function("q=>(new URLSearchParams(location.hash.split('?')[1]||'').get('q')||'')===q.trim().slice(0,60)",arg=query)
    p.goto(base+'#/');p.locator('.hero').wait_for()
    p.keyboard.press('Control+k');p.locator('#quick-search').fill('驱散我方减益')
    p.locator('.quick-summary').wait_for()
    quick_ids=p.locator('#quick-results [data-search-id]').evaluate_all('(els)=>els.map(e=>Number(e.dataset.searchId))')
    assert p.evaluate('(ids)=>ids.some(id=>WIKI_DATA.pages.find(p=>p.id===id)?.type==="character")',quick_ids)
    assert p.locator('.quick-hit mark').count()>0
    clear=p.locator('[data-search-clear="quick-search"]');assert clear.is_visible()
    clear.focus();p.keyboard.press('Enter')
    assert p.locator('#search-dialog').is_visible() and p.locator('#quick-search').input_value()==''
    assert clear.is_hidden() and p.locator('#quick-search').evaluate('(e)=>e===document.activeElement')
    p.locator('#quick-search').fill('驱散我方减益');p.locator('.quick-summary').wait_for()
    quick_count=int(re.search(r'找到 ([\d,]+)',p.locator('.quick-summary').inner_text())[1].replace(',',''))
    p.screenshot(path=str(ROOT/'test-results/unified-search-dialog.png'))
    p.locator('[data-quick-all]').click();p.locator('.search-result').first.wait_for()
    assert not p.locator('#search-dialog').is_visible()
    assert p.locator('#search-page-query').input_value()=='驱散我方减益'
    assert int(p.locator('#search-page-results .catalog-result b').inner_text().replace(',',''))==quick_count
    page_ids=p.locator('.search-result').evaluate_all('(els)=>els.map(e=>Number(e.dataset.searchId))')
    assert page_ids[:len(quick_ids)]==quick_ids
    checks.append('Top search uses semantic effects, shows matching skills and opens identical full search results')

    assert p.locator('#search-page-form button[type=submit]').count()==0
    # A Chinese IME may end composition without sending another non-composing input event.
    p.locator('#search-page-query').evaluate("el=>{el.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));el.value='持续伤害';el.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true,data:'持续伤害'}));}")
    p.wait_for_timeout(220)
    assert p.evaluate("new URLSearchParams(location.hash.split('?')[1]).get('q')")=='驱散我方减益'
    p.locator('#search-page-query').evaluate("el=>el.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'持续伤害'}))")
    p.wait_for_function("()=>new URLSearchParams(location.hash.split('?')[1]).get('q')==='持续伤害'")
    p.locator('[data-search-type=character]').click()
    clear=p.locator('[data-search-clear="search-page-query"]');assert clear.is_visible()
    normal=clear.evaluate('(e)=>getComputedStyle(e).backgroundColor');clear.hover();p.wait_for_timeout(180)
    assert clear.evaluate('(e)=>getComputedStyle(e).cursor')=='pointer'
    assert clear.evaluate('(e)=>getComputedStyle(e).backgroundColor')!=normal
    p.screenshot(path=str(ROOT/'test-results/search-live-clear.png'))
    clear.click()
    assert p.locator('#search-page-query').input_value()=='' and clear.is_hidden()
    assert p.locator('#search-page-query').evaluate('(e)=>e===document.activeElement')
    assert p.locator('[data-search-type=character]').get_attribute('aria-pressed')=='true'
    checks.append('Input-only live search, Chinese IME completion, no submit button, clear hover/keyboard/focus and preserved filters')

    # Faction intersection, equipment type and hit position share URL state and survive refresh/back.
    fill('持续伤害');p.locator('[data-search-type=character]').click()
    p.locator('#search-weapon').select_option('单手剑')
    p.locator('#search-hit').select_option('个性')
    p.locator('.search-camp-filter summary').click()
    p.locator('[data-search-camp="法皇国"]').check();p.locator('[data-search-camp="锐疾如风"]').check()
    assert '薇佩拉' in p.locator('#search-page-results').inner_text()
    ids=p.locator('.search-result').evaluate_all('(els)=>els.map(e=>Number(e.dataset.searchId))')
    assert p.evaluate('(ids)=>ids.every(id=>{const p=WIKI_DATA.pages.find(p=>p.id===id);return p.type==="character"&&p.weapon==="单手剑"&&p.faction.includes("法皇国")&&p.faction.includes("锐疾如风")})',ids)
    assert '1星' in p.locator('.search-hit').first.inner_text()
    assert p.locator('.search-faction-labels img').count()>0
    saved=p.url;p.reload();p.locator('.search-result').first.wait_for()
    assert p.locator('#search-weapon').input_value()=='单手剑' and p.locator('#search-hit').input_value()=='个性'
    assert p.locator('[data-search-camp="法皇国"]').is_checked()
    p.locator('.search-result[data-search-id="9296"] .search-identity').click();p.locator('.character-profile').wait_for()
    p.go_back();p.locator('.search-result').first.wait_for();assert p.url==saved
    p.screenshot(path=str(ROOT/'test-results/unified-search-filters.png'))
    checks.append('Faction icons, multiple faction intersection, weapon and personality/star matches persist through reload and navigation')

    p.locator('[data-search-reset]').click();fill('控制');p.locator('[data-search-type=character]').click()
    total=int(p.locator('.catalog-result b').inner_text().replace(',',''));assert total>25
    p.locator('[data-search-page="2"]').first.click();second=p.locator('.search-result').first.get_attribute('data-search-id')
    p.reload();p.locator('.search-result').first.wait_for();assert p.locator('.search-result').first.get_attribute('data-search-id')==second
    checks.append('Search pagination survives refresh')

    p.locator('[data-search-reset]').click();fill('');p.locator('[data-search-type=guide]').click()
    assert p.locator('.search-result').count()>0
    assert all('攻略与资料' in v for v in p.locator('.search-result .entry-type').all_text_contents())
    fill('伤害公式汇总');assert p.locator('.search-result h3').first.inner_text()=='伤害公式汇总'
    # A fragment from a guide's full text remains searchable, although absent from the semantic corpus.
    sample=p.evaluate("()=>{const p=WIKI_DATA.pages.find(p=>p.title==='刻印攻略');return {id:p.id,fragment:WIKI_SEARCH[p.id].slice(700,725).trim()}}")
    fill(sample['fragment']);assert p.locator(f'.search-result[data-search-id="{sample["id"]}"]').count()==1
    p.locator('[data-search-reset]').click();fill('百分比伤害')
    assert p.locator('.search-hit mark').count()>0
    checks.append('Guide full-text, all archive types, blank-query filtering and percentage semantic mapping remain available')

    p.keyboard.press('Control+k');p.locator('#quick-search').fill('旗女')
    p.locator('.quick-summary').wait_for();p.locator('#quick-results').get_by_text('歌洛莉亚',exact=True).wait_for()
    assert p.locator('#quick-results [data-search-id] strong').first.inner_text()=='歌洛莉亚'
    p.keyboard.press('ArrowDown');p.keyboard.press('Enter');p.locator('.character-profile').wait_for()
    checks.append('Alias ranking and original keyboard navigation are preserved')

    go('#/tools/advanced?q='+quote('吸血'));assert '#/search?' in p.url and p.locator('#search-page-query').input_value()=='吸血'
    p.goto(base+'#/tools');p.locator('.tool-grid').wait_for();assert not p.locator('a[href="#/tools/advanced"]').count()
    p.locator('#sidebar a[href="#/search"]').click();p.locator('#search-page-query').wait_for();p.locator('.loading').wait_for(state='hidden')
    fill('驱散我方减益');p.locator('[data-search-type=character]').click()
    p.set_viewport_size({'width':390,'height':844})
    assert p.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    p.screenshot(path=str(ROOT/'test-results/unified-search-mobile.png'))
    p.locator('[data-action=theme]').click();p.screenshot(path=str(ROOT/'test-results/unified-search-mobile-dark.png'))
    p.keyboard.press('Control+k');p.locator('#quick-search').fill('持续伤害');p.locator('.quick-summary').wait_for()
    assert p.locator('[data-quick-all]').is_visible()
    assert p.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    p.keyboard.press('Escape');fill('<img src=x onerror=alert(1)>')
    assert not p.locator('#main img[src=x]').count()
    checks.append('Legacy tool link redirects to site search; mobile light/dark layouts and escaped query text')
    assert not errors,errors
    assert not network,network
    browser.close()
report={'status':'passed','entrypoint':'APK packaged assets' if ANDROID else 'file://','checks':checks,'errors':errors,'externalRequests':network}
(ROOT/'test-results'/('unified-search-android.json' if ANDROID else 'unified-search-verification.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
for check in checks:print('PASS '+check,flush=True)
