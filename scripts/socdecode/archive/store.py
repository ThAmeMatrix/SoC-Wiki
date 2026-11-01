"""Content-addressed storage for extracted resources and timestamped versions.

Layout under the archive root::

    objects/ab/<hash>.<ext>      every distinct resource once, read-only
    sources/ab/<key>.json.gz      what one source file produced (resume / reuse)
    versions/<id>/version.json    when, which client, counts and timings
    versions/<id>/manifest.json.gz  every resource path → hash in that version
    versions/<id>/sources.json.gz   every client file → size, hash
    versions/<id>/changes.json    difference to the previous version
    versions/<id>/report.md       the same, readable
    index.json                    all versions, newest last
    state.json                    file sizes / times / hashes of the last scan
    library/                      organised folders (hard links into objects/)
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import stat
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .catalog import EXTRACTOR, LABELS

FIELDS = ('path', 'cat', 'group', 'hash', 'size', 'ext', 'src', 'meta')
HASH_BYTES = 16
_lock = threading.Lock()


def blob_hash(data: bytes) -> str:
    return hashlib.blake2b(data, digest_size=HASH_BYTES).hexdigest()


def file_hash(path: Path, chunk=4 * 1024 * 1024) -> str:
    digest = hashlib.blake2b(digest_size=HASH_BYTES)
    with open(path, 'rb') as stream:
        while True:
            block = stream.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix='.tmp-')
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(data)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def write_json(path: Path, value, compress=False) -> None:
    text = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf8')
    _atomic_write(path, gzip.compress(text, 6) if compress else text)


def read_json(path: Path, default=None):
    try:
        data = path.read_bytes()
    except OSError:
        return default
    if path.suffix == '.gz':
        data = gzip.decompress(data)
    return json.loads(data.decode('utf8'))


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.objects = self.root / 'objects'
        self.sources = self.root / 'sources'
        self.versions_dir = self.root / 'versions'
        self.library = self.root / 'library'
        self.thumbs = self.root / 'thumbs'

    # -- blobs -------------------------------------------------------------
    def blob_path(self, digest: str, ext: str) -> Path:
        return self.objects / digest[:2] / f'{digest}{ext}'

    def has_blob(self, digest: str, ext: str) -> bool:
        return self.blob_path(digest, ext).is_file()

    def put_bytes(self, data: bytes, ext: str) -> tuple[str, int, int]:
        """Store ``data`` once; returns (hash, size, bytes newly written)."""
        digest = blob_hash(data)
        target = self.blob_path(digest, ext)
        if target.is_file():
            return digest, len(data), 0
        try:
            _atomic_write(target, data)
        except PermissionError:
            # Another worker finished the same blob first.
            if not target.is_file():
                raise
            return digest, len(data), 0
        _read_only(target)
        return digest, len(data), len(data)

    def put_file(self, source: Path, ext: str, digest: str) -> int:
        """Copy a client file whose hash is known; returns bytes newly written."""
        target = self.blob_path(digest, ext)
        if target.is_file():
            return 0
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=target.parent, prefix='.tmp-')
        os.close(handle)
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, target)
        except PermissionError:
            _unlink(Path(temporary))
            if not target.is_file():
                raise
            return 0
        except BaseException:
            _unlink(Path(temporary))
            raise
        _read_only(target)
        return target.stat().st_size

    # -- per-source cache --------------------------------------------------
    def cache_path(self, key: str) -> Path:
        return self.sources / f'v{EXTRACTOR}' / key[:2] / f'{key}.json.gz'

    def cache_get(self, key: str):
        return read_json(self.cache_path(key))

    def cache_put(self, key: str, payload) -> None:
        write_json(self.cache_path(key), payload, compress=True)

    # -- versions ----------------------------------------------------------
    def index(self) -> list[dict]:
        data = read_json(self.root / 'index.json')
        if isinstance(data, list):
            return data
        rebuilt = []
        if self.versions_dir.is_dir():
            for folder in sorted(self.versions_dir.iterdir()):
                meta = read_json(folder / 'version.json')
                if meta:
                    rebuilt.append(meta)
        return rebuilt

    def latest(self):
        versions = self.index()
        return versions[-1] if versions else None

    def version(self, vid: str):
        return read_json(self.versions_dir / vid / 'version.json')

    def manifest(self, vid: str) -> list[list]:
        data = read_json(self.versions_dir / vid / 'manifest.json.gz', {})
        return data.get('entries', []) if isinstance(data, dict) else []

    def source_list(self, vid: str) -> dict:
        data = read_json(self.versions_dir / vid / 'sources.json.gz', {})
        return data if isinstance(data, dict) else {}

    def changes(self, vid: str):
        return read_json(self.versions_dir / vid / 'changes.json')

    def new_version_id(self, stamp: str) -> str:
        vid, n = stamp, 2
        while (self.versions_dir / vid).exists():
            vid = f'{stamp}-{n}'
            n += 1
        return vid

    def write_version(self, meta: dict, entries: list, sources: dict, changes: dict, report: str) -> None:
        folder = self.versions_dir / meta['id']
        folder.mkdir(parents=True, exist_ok=True)
        write_json(folder / 'manifest.json.gz', {'fields': FIELDS, 'entries': entries}, compress=True)
        write_json(folder / 'sources.json.gz', sources, compress=True)
        write_json(folder / 'changes.json', changes)
        _atomic_write(folder / 'report.md', report.encode('utf8'))
        # version.json last: a version only exists once everything above is on disk.
        write_json(folder / 'version.json', meta)
        with _lock:
            versions = [v for v in self.index() if v['id'] != meta['id']]
            versions.append(meta)
            versions.sort(key=lambda v: v['id'])
            write_json(self.root / 'index.json', versions)

    def delete_version(self, vid: str) -> bool:
        folder = self.versions_dir / vid
        if not folder.is_dir():
            return False
        with _lock:
            versions = [v for v in self.index() if v['id'] != vid]
            # Children now compare against the version before the removed one.
            for index, meta in enumerate(versions):
                meta['parent'] = versions[index - 1]['id'] if index else None
            write_json(self.root / 'index.json', versions)
        shutil.rmtree(folder, ignore_errors=True)
        return True

    # -- scan state --------------------------------------------------------
    def load_state(self) -> dict:
        data = read_json(self.root / 'state.json', {})
        return data if isinstance(data, dict) else {}

    def save_state(self, state: dict) -> None:
        write_json(self.root / 'state.json', state)

    # -- housekeeping ------------------------------------------------------
    def referenced(self) -> set[str]:
        keep = set()
        for meta in self.index():
            for entry in self.manifest(meta['id']):
                keep.add(f'{entry[3]}{entry[5]}')
        return keep

    def gc(self, progress=None) -> tuple[int, int]:
        """Remove resources no remaining version refers to, and caches of older
        extractors; returns (files, bytes)."""
        keep = self.referenced()
        doomed = []
        if self.objects.is_dir():
            for folder in self.objects.iterdir():
                if folder.is_dir():
                    for item in os.scandir(folder):
                        if item.name.startswith('.tmp-') or item.name not in keep:
                            doomed.append((item.path, item.stat().st_size))
        if self.sources.is_dir():
            for folder in self.sources.iterdir():
                if folder.is_dir() and folder.name != f'v{EXTRACTOR}':
                    for parent, _, names in os.walk(folder):
                        doomed += [(os.path.join(parent, name), os.path.getsize(os.path.join(parent, name))) for name in names]
        # Deletes are slow on some volumes (security filters), so they run in parallel.
        with ThreadPoolExecutor(max_workers=16) as pool:
            for done, _ in enumerate(pool.map(lambda pair: _unlink(pair[0]), doomed, chunksize=32), 1):
                if progress and done % 1000 == 0:
                    progress(done, len(doomed))
        if self.sources.is_dir():
            for folder in self.sources.iterdir():
                if folder.is_dir() and folder.name != f'v{EXTRACTOR}':
                    shutil.rmtree(folder, ignore_errors=True)
        return len(doomed), sum(size for _, size in doomed)

    def disk_usage(self) -> int:
        total = 0
        if self.objects.is_dir():
            for folder in self.objects.iterdir():
                if folder.is_dir():
                    for item in os.scandir(folder):
                        total += item.stat().st_size
        return total

    def materialize(self, vid: str, target: Path | None = None, progress=None) -> tuple[Path, int, int]:
        """Organised folders ``<分类>/<位置>/<文件>`` for one version.

        Files are hard links into ``objects`` (no extra space, read-only); the
        tree is updated in place, so refreshing after a scan only touches what
        changed. Returns (folder, linked, removed).
        """
        target = Path(target) if target else self.library / '当前版本'
        target.mkdir(parents=True, exist_ok=True)
        record = target / '.tree.json'
        before = read_json(record, {}) or {}
        wanted = {}
        for entry in self.manifest(vid):
            path, cat, _, digest, _, ext = entry[:6]
            if (entry[7] or {}).get('noblob'):
                continue
            relative = LABELS.get(cat, cat) + '/' + path.split('/', 1)[1] if '/' in path else path
            wanted[relative] = f'{digest}{ext}'
        base = os.path.abspath(target)
        objects = os.path.abspath(self.objects)
        stale = [(relative, blob) for relative, blob in before.items() if wanted.get(relative) != blob]

        def drop(item):
            relative, blob = item
            _unlink(_long(base, relative))
            # Links share attributes with the blob: unlinking cleared its read-only flag.
            _read_only(_long(objects, f'{blob[:2]}/{blob}'))
        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(drop, stale, chunksize=32))
        removed = len(stale)
        made = set()
        pending = []
        for relative, blob in wanted.items():
            destination = _long(base, relative)
            if before.get(relative) == blob and os.path.exists(destination):
                continue
            folder = os.path.dirname(destination)
            if folder not in made:
                os.makedirs(folder, exist_ok=True)
                made.add(folder)
            pending.append((_long(objects, f'{blob[:2]}/{blob}'), destination))

        def link(pair):
            source, destination = pair
            # A hard link shares the blob's read-only attribute, so one call is enough.
            try:
                os.link(source, destination)
            except FileExistsError:
                _unlink(destination)
                os.link(source, destination)
            except OSError:
                shutil.copyfile(source, destination)
                _read_only(destination)

        # Creating directory entries is latency-bound (and scanned by antivirus), so overlap them.
        with ThreadPoolExecutor(max_workers=16) as pool:
            for done, _ in enumerate(pool.map(link, pending, chunksize=64), 1):
                if progress and done % 2000 == 0:
                    progress(done, len(pending))
        linked = len(pending)
        write_json(record, wanted)
        write_json(target / '.version.json', {'version': vid})
        return target, linked, removed

    def unmaterialize(self, target: Path) -> int:
        """Delete an organised folder made by ``materialize``; the resources stay."""
        target = Path(target)
        record = read_json(target / '.tree.json', None)
        if record is None:
            raise ValueError(f'{target} 不是分类目录（缺少 .tree.json），未删除。')
        base, objects = os.path.abspath(target), os.path.abspath(self.objects)

        def drop(item):
            relative, blob = item
            _unlink(_long(base, relative))
            _read_only(_long(objects, f'{blob[:2]}/{blob}'))
        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(drop, record.items(), chunksize=64))
        shutil.rmtree(target, ignore_errors=True)
        return len(record)


def _long(base: str, relative: str) -> str:
    """Absolute path that still works past Windows' 260-character limit."""
    text = os.path.join(base, relative.replace('/', os.sep))
    if os.name == 'nt' and len(text) > 240 and not text.startswith('\\\\?\\'):
        return '\\\\?\\' + text
    return text


def _read_only(path: Path) -> None:
    try:
        os.chmod(path, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
    except OSError:
        pass


def _unlink(path) -> None:
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError:
        pass
