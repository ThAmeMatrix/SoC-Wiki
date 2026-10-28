"""Exercise isolated update transactions, resume, rollback, sanitization and local semantic search."""
from pathlib import Path
from urllib.parse import urlsplit,parse_qs,unquote
import base64,json,io,sys,mimetypes
from PIL import Image
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
def load(path):
    s=path.read_text(encoding='utf8');return json.JSONDecoder().raw_decode(s[s.index('=')+1:])[0]
baseline=load(ROOT/'data/update-baseline.js')
png=io.BytesIO();Image.new('RGB',(8,8),(25,140,180)).save(png,format='PNG');png=png.getvalue()
state={'broken':True,'parse':0,'image':0}
newid=100001;url='https://patchwiki.biligame.com/images/llzj/a/ab/update-verification.png'
inventory=[{'pageid':9296,'title':'角色图鉴库/薇佩拉'},{'pageid':newid,'title':'技能图鉴库/离线更新验证'},{'pageid':100002,'title':'角色图鉴库/更新测试角色'},{'pageid':968,'title':'角色图鉴库'},{'pageid':2736,'title':'附魔图鉴库'}]
parsed={'pageid':newid,'title':inventory[1]['title'],'revid':999999,'wikitext':'{{技能\n|技能名称=离线更新验证\n|技能图标=离线更新验证\n|技能类别=支援\n|技能描述=驱散友军2个减益，造成20%持续伤害。\n}}','categories':[],'sections':[],'text':f'<div><script>window.pwned=1</script><img src="{url}" onerror="window.pwned=2"><a href="javascript:alert(1)">坏链接</a><p>更新后内容<span style="color: #f3c156">剧毒</span><font color="red">20%</font></p></div>'}
fixtures={newid:parsed,
  100002:{'title':'角色图鉴库/更新测试角色','wikitext':'{{角色\n|角色职业=突袭者\n|稀有度=传说\n|所属阵营=法皇国,锐疾如风\n|满级满星物攻=3000\n|初始物攻=100\n|跳跃高度=2\n}}','text':'<p>更新测试角色</p>'},
  968:{'title':'角色图鉴库','wikitext':'{{角色列表}}','text':'<a title="角色图鉴库/更新测试角色">更新测试角色</a><a title="角色图鉴库/薇佩拉">薇佩拉</a>'},
  2736:{'title':'附魔图鉴库','wikitext':'刻印列表','text':'<table><tr><th>宝剑+宝剑</th><td>更新后的刻印说明 <font color="red">20%</font></td></tr></table>'}}
for id,fixture in fixtures.items():fixture.update(pageid=id,revid=999999,categories=[],sections=[])
with sync_playwright() as pw:
    browser=pw.chromium.launch();context=browser.new_context(viewport={'width':1440,'height':1000});p=context.new_page();errors=[];p.on('pageerror',lambda e:errors.append(str(e)))
    def route(r):
        u=urlsplit(r.request.url)
        if u.hostname=='patchwiki.biligame.com':
            state['image']+=1;r.fulfill(body=b'invalid-image' if state['broken'] else png,content_type='image/png');return
        q={k:v[0] for k,v in parse_qs(u.query).items()}
        if q.get('list')=='allpages':d={'query':{'allpages':inventory}}
        elif q.get('prop')=='info|revisions':d={'query':{'pages':[{'pageid':x['pageid'],'title':x['title'],'lastrevid':baseline['revisions']['9296'] if x['pageid']==9296 else 999999,'revisions':[{'timestamp':'2026-10-28T00:00:00Z'}]} for x in inventory]}}
        elif q.get('list')=='recentchanges':d={'query':{'recentchanges':[]}}
        elif q.get('list')=='allimages':d={'query':{'allimages':[{'name':'技能_离线更新验证.png','url':url,'size':len(png),'mime':'image/png','sha1':'fixture-v1','width':8,'height':8,'timestamp':'2026-10-28T00:00:00Z'}]}}
        elif q.get('action')=='parse':state['parse']+=1;d={'parse':fixtures[int(q['pageid'])]}
        else:raise AssertionError(q)
        r.fulfill(json=d,headers={'Access-Control-Allow-Origin':'*'})
    context.route('https://wiki.biligame.com/llzj/api.php**',route);context.route('https://patchwiki.biligame.com/**',route)
    if '--android' in sys.argv:
        assets=ROOT/'android/app/build/generated/wikiAssets'
        def local_asset(r):
            path=(assets/unquote(urlsplit(r.request.url).path).removeprefix('/assets/')).resolve()
            assert path.is_relative_to(assets.resolve()) and path.is_file(),path
            r.fulfill(path=path,content_type={'js':'text/javascript'}.get(path.suffix.lstrip('.'),mimetypes.guess_type(path)[0] or 'application/octet-stream'))
        context.route('https://appassets.androidplatform.net/**',local_asset)
        base='https://appassets.androidplatform.net/assets/wiki/index.html'
    else:base=(ROOT/'index.html').as_uri()
    p.goto(base+'#/archive');p.locator('[data-update=start]').wait_for()
    star_check=p.evaluate("""()=>{
      const C=WikiUpdateConvert,values=[1,2,3,4,5].map(n=>'<p>公共效果。</p><p>伤害提高<span class="wiki-color-red">'+n*10+'%</span>。</p>'+(n>2?'<p><span class="wiki-color-gold">剧毒</span>持续'+n+'回合。</p>':''));
      const merged=C.combineStars(values),fields=Object.fromEntries(values.map((v,i)=>['个性描述'+(i+1),v]));
      const p=C.convert({pageid:999,title:'个性/测试',wikitext:'{{个性\\n'+values.map((v,i)=>'|个性描述'+(i+1)+'='+v).join('\\n')+'\\n}}',text:'<p>测试</p>',categories:[],sections:[],revid:1},{revisions:[]},{},{},null);
      return {merged,comparison:p.doc.starComparison};
    }""")
    assert '10%/20%/30%/40%/50%' in star_check['merged']['html']
    assert '0/0/3/4/5' in star_check['merged']['html'] and 'wiki-color-gold' in star_check['merged']['html']
    assert '公共效果' in star_check['comparison']['common']
    assert '公共效果' not in star_check['comparison']['levels'][0]['html']
    assert 'star-change' in star_check['comparison']['levels'][0]['html']
    assert p.locator('[data-update=cancel]').is_hidden() and p.locator('[data-update=reload]').is_hidden()
    # A minimal baseline isolates this scenario without touching any real user's storage.
    p.evaluate("()=>{WIKI_UPDATE_BASELINE.revisions={'9296':WIKI_UPDATE_BASELINE.revisions['9296'],'9350':WIKI_UPDATE_BASELINE.revisions['9350']};localStorage.setItem('socwiki.favorites','[9296]');localStorage.setItem('socwiki.infographic.draft.9296',JSON.stringify({version:6,characterId:9296,author:'保留作者'}));}")
    p.locator('[data-update=start]').click();p.locator('[data-update=cancel]').click();p.wait_for_function("()=>WikiUpdates.status().phase==='cancelled'",timeout=30000)
    assert not p.evaluate(f"WIKI_DATA.pages.some(p=>p.id==={newid})")
    p.locator('[data-update=start]').click();p.wait_for_function("()=>WikiUpdates.status().phase==='error'",timeout=30000)
    assert not p.evaluate(f"WIKI_DATA.pages.some(p=>p.id==={newid})")
    assert state['parse']==4
    state['broken']=False
    with p.expect_navigation(wait_until='load',timeout=30000):p.locator('[data-update=start]').click()
    assert state['parse']==4,'retry should reuse parsed page'
    p.locator('[data-update=start]').wait_for()
    assert p.evaluate(f"WIKI_DATA.pages.some(p=>p.id==={newid})")
    assert p.evaluate('WIKI_DATA.pages.find(p=>p.id===100002).sourceOrder')==0
    assert p.evaluate('WIKI_DATA.pages.find(p=>p.id===9296).sourceOrder')==1
    p.evaluate("()=>{WIKI_UPDATE_BASELINE.revisions={'9296':WIKI_UPDATE_BASELINE.revisions['9296'],'9350':WIKI_UPDATE_BASELINE.revisions['9350']};}")
    with p.expect_navigation(wait_until='load',timeout=30000):p.locator('[data-update=start]').click()
    p.locator('[data-update=start]').wait_for()
    assert '0 个页面' in p.locator('.update-status').inner_text() and state['parse']==4
    assert not p.evaluate('WIKI_DATA.pages.some(p=>p.id===9350)')
    assert p.evaluate("JSON.parse(localStorage.getItem('socwiki.favorites'))")==[9296]
    assert p.evaluate("JSON.parse(localStorage.getItem('socwiki.infographic.draft.9296')).author")=='保留作者'
    p.goto(base+f'#/page/{newid}');p.locator('h1',has_text='离线更新验证').wait_for()
    assert p.evaluate('window.pwned===undefined')
    assert p.locator('.wiki-content [data-source-color=red]').count()>0
    assert p.locator('.wiki-content .wiki-color-gold[data-source-color]').count()>0
    assert not p.locator('a[href^="javascript:"]').count()
    assert p.evaluate(f"WIKI_PAGES[{newid}].html.includes('blob:')")
    context.set_offline(True);p.reload();p.locator('h1',has_text='离线更新验证').wait_for()
    p.goto(base+'#/search?q=离线更新验证');p.locator('.search-result').first.wait_for()
    assert '更新后的刻印说明' in p.evaluate('WikiUpdates.catalog(WIKI_INFOGRAPHIC_DATA).engravings[0].description')
    assert p.evaluate('WikiUpdates.catalog(WIKI_INFOGRAPHIC_DATA).engravings[0].id')=='engraving-1'
    p.locator('#search-page-query').fill('离线更新验证');p.wait_for_timeout(300);assert p.locator('.search-result').count()==1
    p.locator('#search-page-query').fill('持续伤害');p.wait_for_timeout(300);assert p.locator('.search-result').count()>0
    p.locator('[data-search-type=character]').click();p.locator('summary',has_text='角色阵营').click();p.locator('[data-search-camp="法皇国"]').check();p.locator('[data-search-camp="锐疾如风"]').check()
    assert '薇佩拉' in p.locator('#search-page-results').inner_text()
    p.set_viewport_size({'width':390,'height':844});assert p.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    p.screenshot(path=str(ROOT/'test-results/semantic-search-mobile.png'))
    p.goto(base+'#/archive');p.locator('[data-update=rollback]').click();p.wait_for_timeout(500);p.locator('[data-update=start]').wait_for()
    assert not p.evaluate(f"WIKI_DATA.pages.some(p=>p.id==={newid})")
    assert p.evaluate('WIKI_DATA.pages.some(p=>p.id===9350)')
    assert not errors,errors
    browser.close()
print('PASS cancel; unchanged update; atomic failed-image rollback; resumed page download; added/deleted pages; sanitized HTML; persistent offline image; local semantic corpus refresh; preserved personal data; mobile filters; manual rollback')
