"""Build lightweight web variants of heavy wiki images.

The offline archive keeps every original image untouched (portraits up to
3676x3500 / 12 MB). Served from GitHub Pages those originals made list pages
and detail pages download hundreds of MB. This script writes two derived sets
that the UI prefers when present, falling back to the original otherwise:

  assets/thumb/<dir>/<name>.webp    long side <= 480 px, used by cards / lists
  assets/display/<dir>/<name>.webp  width <= 1280 and height <= 2048 (long
                                    strips only cap the width), used by detail
                                    views and rich text; the lightbox and the
                                    download button still open the original.

A variant is only kept when it is meaningfully smaller than its source, so
small icons are never duplicated. The list of available variants is written to
data/image-variants.js for the front end.

    python -X utf8 scripts/build_image_variants.py            # incremental
    python -X utf8 scripts/build_image_variants.py --force    # rebuild all
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'assets'
SOURCES = ('client', 'wiki')
THUMB_SIDE = 480
THUMB_QUALITY = 76
DISPLAY_WIDTH = 1280
DISPLAY_HEIGHT = 2048
DISPLAY_QUALITY = 78
THUMB_MIN_BYTES = 60 * 1024        # smaller covers are already cheap
DISPLAY_MIN_BYTES = 600 * 1024     # only heavy images get a display copy
KEEP_RATIO = 0.7                   # variant must be < 70 % of the source


def cover_refs() -> set[str]:
    """Images used as cards / list covers (page.image, avatar, portraits)."""
    text = (ROOT / 'data' / 'index.js').read_text('utf8')
    data = json.JSONDecoder().raw_decode(text[text.index('=') + 1:])[0]
    refs = set()
    for page in data.get('pages', []):
        for key in ('image', 'avatar'):
            if page.get(key):
                refs.add(page[key])
        for item in page.get('portraits') or []:
            if item.get('src'):
                refs.add(item['src'])
    return {r for r in refs if r.startswith(tuple(f'assets/{d}/' for d in SOURCES))}


def _variant(job):
    """Worker: returns (kind, rel, status, src_bytes, out_bytes)."""
    kind, rel, force = job
    from PIL import Image
    src = ROOT / rel
    sub = Path(rel).relative_to('assets')
    out = ASSETS / kind / sub.with_suffix('.webp')
    try:
        src_size = src.stat().st_size
        if not force and out.is_file() and out.stat().st_mtime >= src.stat().st_mtime:
            return kind, rel, 'kept', src_size, out.stat().st_size
        with Image.open(src) as im:
            if getattr(im, 'is_animated', False):
                return kind, rel, 'animated', src_size, 0
            w, h = im.size
            if kind == 'thumb':
                scale = min(1.0, THUMB_SIDE / max(w, h))
                quality = THUMB_QUALITY
            else:
                long_strip = h / max(1, w) > 2.2
                scale = min(1.0, DISPLAY_WIDTH / w) if long_strip else \
                    min(1.0, DISPLAY_WIDTH / w, DISPLAY_HEIGHT / h)
                quality = DISPLAY_QUALITY
            target = (max(1, round(w * scale)), max(1, round(h * scale)))
            frame = im.convert('RGBA') if im.mode in ('P', 'LA', 'RGBA') else im.convert('RGB')
            if target != (w, h):
                frame = frame.resize(target, Image.LANCZOS)
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix('.tmp')
            frame.save(tmp, 'WEBP', quality=quality, method=4)
        size = tmp.stat().st_size
        if size >= src_size * KEEP_RATIO:
            tmp.unlink()
            if out.is_file():
                out.unlink()
            return kind, rel, 'not-smaller', src_size, 0
        os.replace(tmp, out)
        return kind, rel, 'built', src_size, size
    except Exception as exc:  # pragma: no cover - reported, never fatal
        return kind, rel, f'error: {exc}', 0, 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--force', action='store_true', help='rebuild every variant')
    parser.add_argument('--workers', type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = parser.parse_args(argv)
    try:
        import PIL  # noqa: F401
    except ImportError:
        print('跳过图片变体：未安装 Pillow（pip install pillow）。')
        return 0

    covers = cover_refs()
    jobs = []
    for rel in sorted(covers):
        p = ROOT / rel
        if p.is_file() and p.suffix.lower() != '.gif' and p.stat().st_size > THUMB_MIN_BYTES:
            jobs.append(('thumb', rel, args.force))
    for d in SOURCES:
        for p in sorted((ASSETS / d).glob('*')):
            if p.is_file() and p.suffix.lower() in ('.webp', '.png', '.jpg', '.jpeg') \
                    and p.stat().st_size > DISPLAY_MIN_BYTES:
                jobs.append(('display', p.relative_to(ROOT).as_posix(), args.force))
    print(f'图片变体：缩略图候选 {sum(1 for j in jobs if j[0] == "thumb")} 张，'
          f'展示图候选 {sum(1 for j in jobs if j[0] == "display")} 张，{args.workers} 进程', flush=True)

    available = {'thumb': [], 'display': []}
    totals = {'thumb': [0, 0], 'display': [0, 0]}
    status_count = {}
    started = time.time()
    done = 0
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(_variant, job) for job in jobs]
        for fut in as_completed(futures):
            kind, rel, status, src_size, out_size = fut.result()
            done += 1
            status_count[status.split(':')[0]] = status_count.get(status.split(':')[0], 0) + 1
            if status in ('built', 'kept'):
                available[kind].append(rel[len('assets/'):])
                totals[kind][0] += src_size
                totals[kind][1] += out_size
            elif status.startswith('error'):
                print('  ', rel, status, flush=True)
            if done % 100 == 0 or done == len(jobs):
                print(f'  {done}/{len(jobs)}  {time.time() - started:5.0f}s', flush=True)

    # Drop stale variants whose source no longer qualifies.
    keep = {(k, r) for k in available for r in available[k]}
    for kind in ('thumb', 'display'):
        base = ASSETS / kind
        if not base.is_dir():
            continue
        for p in base.rglob('*.webp'):
            rel = p.relative_to(base).as_posix()
            if not any((kind, rel.rsplit('.', 1)[0] + ext) in keep
                       for ext in ('.webp', '.png', '.jpg', '.jpeg')):
                p.unlink()

    for kind in available:
        available[kind].sort()
    manifest = {'v': 1, 'thumb': available['thumb'], 'display': available['display']}
    (ROOT / 'data' / 'image-variants.js').write_text(
        'window.WIKI_IMAGE_VARIANTS=' + json.dumps(manifest, ensure_ascii=False, separators=(',', ':')) + ';\n',
        'utf8')
    for kind in ('thumb', 'display'):
        src, out = totals[kind]
        print(f'{kind}: {len(available[kind])} 张，原图 {src / 1048576:.1f} MiB → 变体 {out / 1048576:.1f} MiB')
    print('状态：', status_count)
    print('已写入 data/image-variants.js')
    return 0


if __name__ == '__main__':
    sys.exit(main())
