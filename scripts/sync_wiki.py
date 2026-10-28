"""Resumable, rate-limited public MediaWiki snapshot. No credentials required."""
from __future__ import annotations
import argparse, concurrent.futures as cf, json, pathlib, threading, time
from datetime import datetime, timezone
import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / 'data' / 'raw'
PAGES = RAW / 'pages'
API = 'https://wiki.biligame.com/llzj/api.php'
LOCK = threading.Lock()
NEXT = 0.0
LOCAL = threading.local()

def api(**params):
    global NEXT
    if not hasattr(LOCAL, 'session'):
        LOCAL.session = requests.Session()
        LOCAL.session.headers['User-Agent'] = 'SoC-OfflineWiki/1.0 (personal offline archive; 6 requests/sec)'
    for attempt in range(5):
        with LOCK:
            delay = max(0, NEXT - time.monotonic())
            NEXT = max(NEXT, time.monotonic()) + 1 / 6
        if delay: time.sleep(delay)
        try:
            r = LOCAL.session.get(API, params={'format':'json','formatversion':2, **params}, timeout=60)
            r.raise_for_status()
            d = r.json()
            if 'error' in d: raise RuntimeError(str(d['error']))
            return d
        except Exception:
            if attempt == 4: raise
            time.sleep(min(2 ** attempt, 15))

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, separators=(',',':')), encoding='utf-8')
    temp.replace(path)

def list_pages():
    pages, continuation = [], {}
    while True:
        data = api(action='query', list='allpages', apnamespace=0, aplimit=500, **continuation)
        pages.extend(data['query']['allpages'])
        if 'continue' not in data: break
        continuation = data['continue']
    save(RAW/'pages.json', pages)
    return pages

def snapshot(page, force=False):
    path = PAGES / (str(page['pageid']) + '.json')
    if path.exists() and not force: return 'cached'
    data = api(action='parse', pageid=page['pageid'], prop='text|wikitext|images|categories|sections|revid|displaytitle')
    data['capturedAt'] = datetime.now(timezone.utc).isoformat()
    save(path, data)
    return 'downloaded'

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--refresh',action='store_true', help='Refresh the page inventory and changed revisions')
    parser.add_argument('--reparse',action='store_true', help='Re-render all pages, including changes inherited from templates')
    args=parser.parse_args()
    RAW.mkdir(parents=True,exist_ok=True); PAGES.mkdir(parents=True,exist_ok=True)
    pages = list_pages() if args.refresh or not (RAW/'pages.json').exists() else json.loads((RAW/'pages.json').read_text(encoding='utf-8'))
    print(f'Inventory: {len(pages)} content pages',flush=True)
    metadata={}
    for i in range(0,len(pages),50):
        data=api(action='query',prop='info|revisions',pageids='|'.join(str(x['pageid']) for x in pages[i:i+50]),rvprop='ids|timestamp',inprop='url')
        for p in data['query']['pages']:
            metadata[str(p['pageid'])]=p
            path=PAGES/(str(p['pageid'])+'.json')
            if args.refresh and path.exists():
                old=json.loads(path.read_text(encoding='utf-8'))
                if old.get('parse',{}).get('revid')!=p.get('lastrevid'): path.unlink()
    save(RAW/'metadata.json',metadata)
    print('Revision metadata saved',flush=True)
    # Make structured reference pages available early while the remaining archive downloads.
    priority={'角色图鉴库':0,'装备图鉴库':1,'魔物图鉴库':2,'个性':3}
    pages.sort(key=lambda p:(priority.get(p['title'].split('/')[0],4),p['pageid']))
    failed=[]
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(snapshot,p,args.reparse):p for p in pages}
        for i,f in enumerate(cf.as_completed(futures),1):
            try: f.result()
            except Exception as e:
                failed.append({'page':futures[f],'error':str(e)})
            if i%100==0 or i==len(pages):print(f'Pages: {i}/{len(pages)}; failures: {len(failed)}',flush=True)
    save(RAW/'sync-report.json',{'capturedAt':datetime.now(timezone.utc).isoformat(),'expected':len(pages),'saved':len(pages)-len(failed),'failed':failed})
    if failed:raise SystemExit(1)

if __name__=='__main__':main()
