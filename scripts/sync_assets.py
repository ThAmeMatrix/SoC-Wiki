"""Mirror the public image library; retain diagrams at their original resolution."""
from __future__ import annotations
import argparse, concurrent.futures as cf, hashlib, html, json, pathlib, re, shutil, threading, time
from io import BytesIO
import requests
from PIL import Image

ROOT=pathlib.Path(__file__).resolve().parents[1]
RAW=ROOT/'data'/'raw'
DEST=ROOT/'assets'/'wiki'
LOCAL=threading.local()
LOCK=threading.Lock()
NEXT=0.0

def asset_path(item):
    ext='.gif' if item.get('mime')=='image/gif' else '.webp'
    if item.get('mime')=='image/svg+xml': ext='.svg'
    return 'assets/wiki/'+hashlib.sha1(item['url'].encode()).hexdigest()[:20]+ext

def download(item):
    global NEXT
    target=ROOT/asset_path(item)
    if target.exists() and target.stat().st_size: return
    if not hasattr(LOCAL,'session'):
        LOCAL.session=requests.Session()
        LOCAL.session.headers.update({'User-Agent':'SoC-OfflineWiki/1.0 (personal archive)','Referer':'https://wiki.biligame.com/llzj/'})
    for attempt in range(5):
        with LOCK:
            delay=max(0,NEXT-time.monotonic());NEXT=max(NEXT,time.monotonic())+1/6
        if delay:time.sleep(delay)
        try:
            r=LOCAL.session.get(item['url'],timeout=90);r.raise_for_status()
            temp=target.with_suffix('.tmp')
            if target.suffix in ('.gif','.svg'): temp.write_bytes(r.content)
            else:
                im=Image.open(BytesIO(r.content))
                if im.mode not in ('RGB','RGBA'):im=im.convert('RGBA')
                art=item['name'].startswith(('立绘_','大立绘_'))
                if art:im.thumbnail((1400,1800))
                im.save(temp,format='WEBP',lossless=not art,quality=90,method=3)
            temp.replace(target)
            return
        except Exception:
            if attempt==4:raise
            time.sleep(min(2**attempt,12))

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--refresh',action='store_true',help='Refresh the complete source image inventory')
    args=parser.parse_args()
    DEST.mkdir(parents=True,exist_ok=True)
    if args.refresh or not (RAW/'images.json').exists():
        from sync_wiki import api,save
        items=[];continuation={}
        while True:
            data=api(action='query',list='allimages',ailimit=500,aiprop='url|size|mime',**continuation)
            items.extend(data['query']['allimages'])
            if 'continue' not in data:break
            continuation=data['continue']
        save(RAW/'images.json',items)
    else:items=json.loads((RAW/'images.json').read_text(encoding='utf-8'))
    mapping=json.loads((RAW/'asset-map.json').read_text(encoding='utf-8')) if (RAW/'asset-map.json').exists() else {}
    mapping.update({x['name']:{'path':asset_path(x),'url':x['url'],'width':x['width'],'height':x['height']} for x in items})
    known={x['url'] for x in items}
    # Some old rendered images remain available even though allimages no longer lists them.
    for path in (RAW/'pages').glob('*.json'):
        document=json.loads(path.read_text(encoding='utf-8'))['parse']['text']
        for source in re.findall(r'<img\b[^>]*\bsrc="([^"]+)"',document):
            source=html.unescape(source).split('?')[0]
            if source.startswith('//'):source='https:'+source
            if '/thumb/' in source:source='/'.join(source.replace('/thumb/','/').split('/')[:-1])
            if source.startswith('https://patchwiki.biligame.com/images/llzj/') and source not in known:
                existing=next((k for k,v in mapping.items() if v['url']==source),None)
                item={'name':existing or '补录_'+hashlib.sha1(source.encode()).hexdigest()[:12]+'.png','url':source,'width':0,'height':0,'size':0,'mime':'image/png'}
                items.append(item);known.add(source)
                mapping[item['name']]={'path':asset_path(item),'url':source,'width':0,'height':0}
    (RAW/'asset-map.json').write_text(json.dumps(mapping,ensure_ascii=False),encoding='utf-8')
    featured=['歌洛莉亚','贝拉','伊南娜','索菲亚','麦莎','拉维耶','科尔','奥古斯特','薇佩拉','君士坦丁']
    items.sort(key=lambda x:(0 if x['name'].startswith('立绘_') and any(x['name']=='立绘_'+n+'.png' for n in featured) else 1 if x['name'].startswith('立绘_') else 2,x['size']))
    failed=[]
    with cf.ThreadPoolExecutor(max_workers=5) as pool:
        futures={pool.submit(download,x):x for x in items}
        for i,f in enumerate(cf.as_completed(futures),1):
            try:f.result()
            except Exception as e:failed.append({'name':futures[f]['name'],'url':futures[f]['url'],'error':str(e)})
            if i%100==0 or i==len(items):print(f'Images: {i}/{len(items)}; failures: {len(failed)}',flush=True)
    # A renamed upload can retain the same immutable blob id under another directory.
    recovered=[]
    for failure in failed[:]:
        item=next(x for x in items if x['name']==failure['name'])
        alternate=next((x for x in items if x['url']!=item['url'] and x['url'].split('/')[-1]==item['url'].split('/')[-1] and all(x.get(k)==item.get(k) for k in ('size','width','height')) and (ROOT/asset_path(x)).exists()),None)
        if alternate:
            shutil.copyfile(ROOT/asset_path(alternate),ROOT/asset_path(item))
            recovered.append({'name':item['name'],'originalUrl':item['url'],'recoveredFrom':alternate['url']})
            failed.remove(failure)
    (RAW/'asset-report.json').write_text(json.dumps({'expected':len(items),'saved':len(items)-len(failed),'failed':failed,'recovered':recovered},ensure_ascii=False,indent=2),encoding='utf-8')
    if failed:raise SystemExit(1)

if __name__=='__main__':main()
