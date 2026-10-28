"""Cache the archived original portraits for lossless, full-resolution poster export."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib, json, threading, time
import requests
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw'
LOCK = threading.Lock()
NEXT = 0.0
LOCAL = threading.local()


def load(path):
    text = path.read_text(encoding='utf-8')
    return json.JSONDecoder().raw_decode(text[text.index('=') + 1:])[0]


def download(entry):
    global NEXT
    source, metadata = entry
    name = hashlib.sha256(metadata['url'].encode()).hexdigest()[:24] + '.png'
    destination = RAW / 'infographic-portraits' / name
    if not destination.exists():
        if not hasattr(LOCAL, 'session'):
            LOCAL.session = requests.Session()
            LOCAL.session.headers.update({'User-Agent': 'SoC-OfflineWiki/1.5 (personal archive)', 'Referer': 'https://wiki.biligame.com/llzj/'})
        for attempt in range(4):
            with LOCK:
                delay = max(0, NEXT - time.monotonic())
                NEXT = max(NEXT, time.monotonic()) + .3
            if delay:
                time.sleep(delay)
            try:
                response = LOCAL.session.get(metadata['url'], timeout=60)
                response.raise_for_status()
                temporary = destination.with_suffix('.tmp')
                temporary.write_bytes(response.content)
                with Image.open(temporary) as image:
                    image.verify()
                temporary.replace(destination)
                break
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
    with Image.open(destination) as image:
        width, height = image.size
    assert (width, height) == (metadata['width'], metadata['height']), source
    return source, {'file': destination.relative_to(ROOT).as_posix(), 'width': width, 'height': height,
                    'url': metadata['url'], 'sha256': hashlib.sha256(destination.read_bytes()).hexdigest()}


def main():
    (RAW / 'infographic-portraits').mkdir(exist_ok=True)
    pages = load(ROOT / 'data/index.js')['pages']
    paths = {art['src'] for page in pages if page['type'] == 'character'
             for art in page.get('portraits', []) if art['key'] in ('base', 'awakened')}
    assets = json.loads((RAW / 'asset-map.json').read_text(encoding='utf-8'))
    sources = {item['path']: item for item in assets.values() if item['path'] in paths}
    assert sources.keys() == paths
    result, failures = {}, []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(download, item): item[0] for item in sources.items()}
        for i, future in enumerate(as_completed(futures), 1):
            try:
                source, item = future.result()
                result[source] = item
            except Exception as error:
                failures.append({'source': futures[future], 'error': str(error)})
            if i % 25 == 0 or i == len(sources):
                print(f'Original portraits: {i}/{len(sources)}; failures: {len(failures)}', flush=True)
    if failures:
        (RAW / 'infographic-portrait-errors.json').write_text(json.dumps(failures, indent=2), encoding='utf-8')
        raise SystemExit('Portrait download incomplete; existing release data was not replaced.')
    (RAW / 'infographic-portraits.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'PASS {len(result)} original portraits retained without resizing.', flush=True)


if __name__ == '__main__':
    main()
