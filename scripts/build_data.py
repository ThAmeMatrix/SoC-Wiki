"""Build portable scripts (also work under file://) from the saved wiki snapshot."""
from __future__ import annotations
import collections, hashlib, html, json, pathlib, re, warnings
from datetime import datetime, timezone, timedelta
from urllib.parse import unquote, urlparse, parse_qs
from bs4 import BeautifulSoup, Comment, MarkupResemblesLocatorWarning
from character_data import catalog_order, character_images, star_comparison
warnings.filterwarnings('ignore', category=MarkupResemblesLocatorWarning)

ROOT=pathlib.Path(__file__).resolve().parents[1]
RAW=ROOT/'data'/'raw'
OUT=ROOT/'data'/'pages'
IMAGES=json.loads((RAW/'asset-map.json').read_text(encoding='utf-8'))
INVENTORY=json.loads((RAW/'pages.json').read_text(encoding='utf-8'))
TITLES={p['title']:p['pageid'] for p in INVENTORY}
META=json.loads((RAW/'metadata.json').read_text(encoding='utf-8'))
BY_URL={v['url']:v['path'] for v in IMAGES.values()}
MISSING_IMAGES=set()
EXTERNAL_PAGES=set()
TYPE_NAMES={'character':'角色图鉴','equipment':'装备图鉴','skill':'技能图鉴','status':'状态词条','monster':'魔物图鉴','talent':'天赋与个性','guide':'攻略与资料','news':'资讯与公告'}
COLOR_GROUPS={
    'gold':{'#f3c156','#bdb76b','#b88646','orange','#ffcc66','#c49a6c','#d2b48c'},
    'orange':{'#ed7950','#d2691e'},
    'red':{'red','#ff0000','rgb(255,0,0)'},
    'blue':{'#54b4db','blue','deepskyblue','#1e90ff'},
    'green':{'#58cb48','green','limegreen','#00cc66','#006600','#808000'},
    'purple':{'#d68fe2','purple'},
    'brown':{'brown','#a0522d','#5a4328'},
}

def source_color(value):
    value=re.sub(r'\s+','',value.lower()).replace('##','#')
    if re.fullmatch('[0-9a-f]{6}',value):value='#'+value
    if not re.fullmatch(r'#[0-9a-f]{3}(?:[0-9a-f]{3})?|[a-z]+|rgba?\([\d.,%]+\)',value):return None
    for group,values in COLOR_GROUPS.items():
        if value in values:return value,group
    if value in {'white','black','gray','grey','#fff','#ffffff','#000','#000000','#cccccc'} or value.startswith('rgba(0,0,0'):return value,'neutral'
    return value,'custom'

def dumps(obj):return json.dumps(obj,ensure_ascii=False,separators=(',',':')).replace('</script','<\\/script')

def image_path(url):
    if url.startswith('//'):url='https:'+url
    url=url.split('?')[0]
    if '/thumb/' in url:
        url='/'.join(url.replace('/thumb/','/').split('/')[:-1])
    if url in BY_URL:return BY_URL[url]
    return ''

def named_image(name):
    name=name.replace(' ','_')
    for ext in ('.png','.jpg','.gif','.jpeg','.webp'):
        if name+ext in IMAGES:return IMAGES[name+ext]['path']
    return ''

def local_link(title):
    title=unquote(title).replace('_',' ')
    if title not in TITLES and title.replace(' ','_') in TITLES:title=title.replace(' ','_')
    if title in TITLES:return '#/page/'+str(TITLES[title])
    from urllib.parse import quote
    return '#/search?q='+quote(title)

def sanitize(source,pageid=0):
    soup=BeautifulSoup(source,'html.parser')
    if pageid in (8027,7541):
        for el in soup.select('#widget-params,header,.desktop-container,#details-modal'):
            el.decompose()
    equipment_control=soup.select_one('#equipement_level')
    if equipment_control:
        controls=equipment_control.parent.parent
        notice=soup.new_tag('p',attrs={'class':'source-notice'})
        notice.string='原站装备属性公式尚未完成，等级属性暂不可计算。装备星级技能可在详情页切换。'
        controls.replace_with(notice)
    for el in soup.select('#PNN'):
        el.decompose()
    for el in soup.select('[data-bind^="text:"]'):
        if not el.get_text(strip=True):el.string='—'
    for comment in soup.find_all(string=lambda x:isinstance(x,Comment)):comment.extract()
    for el in soup.select('script,style,link,meta,base,object,embed,bstyle,.mw-editsection,.bread-edit,.resourceLoader,.noprint,form,input,button,select,.mw-empty-elt,#widget-params,.calculator-wrap,.gacha-container'):
        el.decompose()
    for el in soup.find_all(['iframe','audio','video']):
        src=el.get('src','')
        if src.startswith('//'):src='https:'+src
        a=soup.new_tag('a',href=src);a.string='打开原站媒体（需要联网）';el.replace_with(a)
    for el in soup.find_all(True):
        original_color=el.get('color','')
        original_style=el.get('style','')
        for attr in list(el.attrs):
            if attr.lower().startswith('on') or attr in ('srcset','sizes','background','srcdoc','data-src','data-original','data-srcset','align','bgcolor','face','color','id') or (attr in ('width','height') and el.name!='img'):
                if attr=='id':
                    el['id']='source-'+str(pageid)+'-'+el[attr]
                else:del el[attr]
        safe=[]
        for rule in original_style.split(';'):
            k,sep,v=rule.partition(':')
            k=k.strip().lower();v=v.strip()
            if not sep:continue
            if k=='color':original_color=v
            if k in ('text-align','font-weight','font-style','vertical-align') and re.fullmatch(r'[\w\s-]+',v):safe.append(k+':'+v)
            if k=='width' and el.name in ('table','td','th') and re.fullmatch(r'(?:100|\d{1,2})(?:\.\d+)?%',v):safe.append(k+':'+v)
            if k=='display' and v in ('flex','inline-flex'):safe.extend(['display:'+v,'flex-wrap:wrap','gap:8px'])
        color=source_color(original_color)
        if color:
            value,group=color;el['data-source-color']=value;el['class']=el.get('class',[])+['wiki-color-'+group]
            if group=='custom':safe.append('--source-color:'+value)
        if safe:el['style']=';'.join(safe)
        elif 'style' in el.attrs:del el['style']
        if el.name=='img':
            for dimension in ('width','height'):
                if dimension in el.attrs and not re.fullmatch(r'\d{1,5}',str(el[dimension])):del el[dimension]
            src=el.get('src','');path=image_path(src)
            if not path:
                MISSING_IMAGES.add(src)
                el['src']='assets/brand/placeholder.svg';el['title']='原站图片未能收录：'+el.get('alt','')
            else:el['src']=path
            el['loading']='lazy';el['decoding']='async'
        if el.name=='a':
            href=el.get('href','')
            if href.startswith('//'):href='https:'+href
            if href.startswith('#'):
                el['href']='#/page/'+str(pageid)+'?section='+href[1:]
            elif href.startswith('/llzj/') or href.startswith('https://wiki.biligame.com/llzj/'):
                parsed=urlparse(href);title=unquote(parsed.path.split('/llzj/',1)[-1])
                if title=='index.php':
                    q=parse_qs(parsed.query)
                    title=q.get('title',[''])[0]
                    if q.get('action',['view'])[0]!='view':el.unwrap();continue
                if title.startswith(('文件:','File:','档案:')):
                    filename=title.split(':',1)[1].replace(' ','_')
                    if filename in IMAGES:el['href']=IMAGES[filename]['path'];el['data-lightbox']='true'
                    else:el.unwrap();continue
                elif title.startswith(('特殊:','Special:','MediaWiki:','模板:','Template:')):
                    el.unwrap();continue
                else:el['href']=local_link(title)
            elif href.startswith(('http://','https://')):
                if image_path(href):el['href']=image_path(href);el['data-lightbox']='true'
                else:el['href']=href;el['target']='_blank';el['rel']='noopener noreferrer';el['data-online']='true';EXTERNAL_PAGES.add(pageid)
            elif not href.startswith(('assets/','mailto:')):
                el.attrs.pop('href',None)
    # Source hover terms become normal offline links, also usable with keyboard/touch.
    for el in soup.select('.bili-tt,.wiki-color-gold'):
        term=el.get('data-name') or el.get_text(strip=True)
        title='中括号介绍/'+term
        if title in TITLES and not el.find_parent('a') and not el.find('a'):
            a=soup.new_tag('a',href=local_link(title));a['class']='term-link';a['title']='查看状态：'+term;el.wrap(a)
    for el in soup.find_all('p'):
        if not el.get_text(strip=True) and not el.find(['img','audio','video','iframe']):el.decompose()
    for el in soup.find_all(['html','body']):el.unwrap()
    for table in soup.find_all('table'):
        # Replace server-side panel widgets with small local controls.
        if table.select_one('.pre_val') and table.select_one('.max_val'):
            table['data-stat-panel']='base'
            controls=table.select('.set_pre_val,.set_max_val')
            if controls:
                switch=soup.new_tag('span',attrs={'class':'source-stat-switch','role':'group','aria-label':'原文属性面板'})
                for value,label in [('base','初始面板'),('max','满级面板')]:
                    button=soup.new_tag('button',attrs={'type':'button','data-source-stat':value,'aria-pressed':str(value=='base').lower()})
                    button.string=label;switch.append(button)
                controls[0].replace_with(switch)
                for el in controls[1:]:el.decompose()
        wrapper=soup.new_tag('div',attrs={'class':'table-scroll'});table.wrap(wrapper)
    return str(soup)

def fields(source):
    source=re.sub(r'<!--.*?-->','',source,flags=re.S)
    result={}
    for m in re.finditer(r'^[ \t]*\|{1,2}\s*([^=|\n]+?)\s*=(.*?)(?=^[ \t]*\|{1,2}[^=|\n]+?=|^[ \t]*\}\}|\Z)',source,re.M|re.S):
        key=m[1].strip();value=m[2].strip()
        if len(key)<40 and key not in ('style','class','colspan','rowspan','align','width','height','id'):result[key]=value
    return result

def recover_character_fields(parsed,values):
    """Read facts present in older hand-written pages without guessing growth formulas."""
    soup=BeautifulSoup(parsed,'html.parser');recovered=[]
    def add(key,value):
        value=value.strip()
        if not values.get(key) and value:
            values[key]=html.escape(value);recovered.append(key)
    for row in soup.select('tr'):
        heading=row.find('th',recursive=False)
        if not heading:continue
        label=heading.get_text('',strip=True)
        if label in ('生命','物攻','魔攻','物防','魔防','敏捷'):
            for cls,prefix in [('.pre_val','初始'),('.max_val','满级满星')]:
                cell=row.select_one(cls)
                if cell:add(prefix+label,cell.get_text(' ',strip=True))
        if label in ('移动力','移动','跳跃力','跳跃高度'):
            cell=row.find('td',recursive=False)
            if cell and re.fullmatch(r'\d+',cell.get_text(strip=True)):
                add('移动' if label in ('移动力','移动') else '跳跃高度',cell.get_text(strip=True))
    for image in soup.select('img[alt]'):
        match=re.fullmatch(r'职业图标[ _](.+)\.\w+',image['alt'])
        if match:add('角色职业',match[1])
    return recovered

def inline(value,pageid):
    value=re.sub(r'\{\{中括号介绍\|([^{}|]+)(?:\|[^{}]*)?\}\}',lambda m:'<a href="'+html.escape('https://wiki.biligame.com/llzj/中括号介绍/'+m[1])+'">['+html.escape(m[1])+']</a>',value)
    value=re.sub(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]',lambda m:'<a href="'+html.escape('https://wiki.biligame.com/llzj/'+m[1])+'">'+html.escape(m[2] or m[1])+'</a>',value)
    value=re.sub(r"'''(.*?)'''",r'<strong>\1</strong>',value,flags=re.S)
    return sanitize(value,pageid)

def plain(value):return BeautifulSoup(value,'html.parser').get_text(' ',strip=True)

def kind(title,cats):
    prefix=title.split('/')[0]
    if '/' in title:
        for p,t in [('角色图鉴库','character'),('装备图鉴库','equipment'),('技能图鉴库','skill'),('技能图鉴','skill'),('技能','skill'),('中括号介绍','status'),('魔物图鉴库','monster'),('个性','talent'),('天赋','talent'),('天赋图标库','talent'),('极限解放','talent'),('特性','talent')]:
            if prefix==p:return t
    if any(c in cats for c in ['公告','新闻','维护','统计','PV']) or re.search(r'维护内容|资源统计表',title):return 'news'
    return 'guide'

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    index=[];search={};redirects={};counts=collections.Counter();sources=[]
    character_catalog=json.loads((RAW/'pages'/'968.json').read_text(encoding='utf-8'))['parse']
    character_order=catalog_order(character_catalog['text'],TITLES)
    files=[RAW/'pages'/(str(p['pageid'])+'.json') for p in INVENTORY if (RAW/'pages'/(str(p['pageid'])+'.json')).exists()]
    for n,path in enumerate(files,1):
        raw=json.loads(path.read_text(encoding='utf-8'));p=raw['parse'];pid=p['pageid'];title=p['title'];source=p['wikitext'];f=fields(source)
        cats=[c['category'] for c in p['categories']];t=kind(title,cats);label=title.split('/')[-1] or title
        recovered=recover_character_fields(p['text'],f) if t=='character' else []
        body=sanitize(p['text'],pid)
        ff={k:inline(v,pid) for k,v in f.items()}
        # Semantic MediaWiki properties are invisible in the parsed page. Materialize them offline.
        if t=='status' and f.get('介绍'):body='<div class="definition">'+ff['介绍']+'</div>'+body
        if t=='talent' and len(plain(body))<30 and ff:
            body='<dl>'+''.join('<dt>'+html.escape(k)+'</dt><dd>'+v+'</dd>' for k,v in ff.items())+'</dl>'+body
        text=plain(body)
        props={k:plain(v) for k,v in ff.items()}
        image=''
        if t=='character':image=named_image('立绘_'+props.get('角色名称',label))
        elif t=='equipment':image=named_image('装备全图_'+props.get('装备名称',label))
        elif t=='skill':image=named_image('技能_'+props.get('技能图标',label))
        elif t=='monster':image=named_image('魔物_'+label) or named_image('立绘_'+label)
        elif t=='talent':image=named_image('个性_'+props.get('个性图标',label)) or named_image('天赋_'+label)
        imgs=BeautifulSoup(body,'html.parser').find_all('img')
        if not image and imgs:image=imgs[0].get('src','')
        revision=META.get(str(pid),{}).get('revisions',[{}])[0]
        date=revision.get('timestamp','')[:10]
        redirect=re.match(r'\s*#(?:REDIRECT|重定向)\s*\[\[(.*?)\]\]',source,re.I)
        if redirect:redirects[str(pid)]=TITLES.get(redirect[1],0)
        description=next((props[k] for k in ('角色生平','装备描述','技能描述','介绍','个性描述5','天赋描述5','魔物解析') if props.get(k)),text)
        entry={'id':pid,'title':title,'name':label,'type':t,'image':image,'date':date,'summary':description[:220],'categories':cats,'class':props.get('角色职业',''),'rarity':props.get('稀有度',''),'faction':props.get('所属阵营',''),'weapon':props.get('武器类型',props.get('装备类型','')),'aliases':props.get('角色绰号',''),'redirect':bool(redirect)}
        if t=='character':
            entry['stats']={s:props.get('满级满星'+s,'') for s in ('生命','物攻','魔攻','物防','魔防','敏捷')}
            entry['avatar']=named_image('头像_'+props.get('角色名称',label))
            entry.update(character_images(props.get('角色名称',label),props.get('皮肤',''),named_image))
            entry['sourceOrder']=character_order.get(title,100000+pid)
            entry['unitNumber']=props.get('ID','')
            entry['professionIcon']=named_image('职业图标_'+props.get('角色职业',''))
        index.append(entry);counts[t]+=1
        search[str(pid)]=title+' '+ ' '.join(props.values())+' '+text
        related=[]
        if t in ('skill','talent'):
            related=list(dict.fromkeys(TITLES[name] for name in re.findall(r'title="(角色图鉴库/[^"<>]+)"',p['text']) if name in TITLES))
        doc={'id':pid,'title':title,'html':body,'fields':ff,'rawFields':props,'related':related,'recoveredFields':recovered,'revision':p.get('revid'),'date':date,'sections':p.get('sections',[]),'source':'https://wiki.biligame.com/llzj/index.php?title='+title+'&oldid='+str(p.get('revid','')),'hasOnlineMedia':pid in EXTERNAL_PAGES}
        comparison=star_comparison(ff) if t=='talent' else None
        if comparison:doc['starComparison']=comparison
        (OUT/(str(pid)+'.js')).write_text('window.WIKI_PAGES['+str(pid)+']='+dumps(doc)+';\n',encoding='utf-8')
        sources.append({'id':pid,'title':title,'revision':p.get('revid'),'date':date})
        if n%500==0:print(f'Built {n}/{len(files)}',flush=True)
    index.sort(key=lambda x:(x['date'],x['id']),reverse=True)
    assets=[ROOT/v['path'] for v in IMAGES.values() if (ROOT/v['path']).exists()]
    unavailable=[{'name':k,'url':v['url']} for k,v in IMAGES.items() if not (ROOT/v['path']).exists()]
    archive={'builtAt':datetime.now(timezone(timedelta(hours=8))).isoformat(),'source':'https://wiki.biligame.com/llzj','expectedPages':len(INVENTORY),'pages':len(index),'expectedImages':len(IMAGES),'images':len(assets),'bytes':sum(x.stat().st_size for x in assets),'counts':dict(counts),'missingImages':sorted(MISSING_IMAGES),'unavailableImages':unavailable,'onlineMediaPages':len(EXTERNAL_PAGES),'types':TYPE_NAMES,'complete':len(index)==len(INVENTORY) and not MISSING_IMAGES and not unavailable}
    data={'pages':index,'titles':TITLES,'redirects':redirects,'archive':archive}
    (ROOT/'data'/'index.js').write_text('window.WIKI_DATA='+dumps(data)+';window.WIKI_PAGES={};\n',encoding='utf-8')
    (ROOT/'data'/'search.js').write_text('window.WIKI_SEARCH='+dumps(search)+';\n',encoding='utf-8')
    (ROOT/'data'/'archive.json').write_text(json.dumps(archive,ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'data'/'sources.json').write_text(json.dumps(sources,ensure_ascii=False),encoding='utf-8')
    from build_tools import build_tools
    build_tools()
    from build_runtime_data import main as build_runtime_data
    build_runtime_data()
    print(json.dumps(archive,ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':main()
