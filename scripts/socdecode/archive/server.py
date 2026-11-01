"""Local web server behind the visual resource browser and version diff.

Binds to 127.0.0.1 only. Manifests, comparisons and decoded tables are cached
in memory so switching versions or categories stays instant.
"""
from __future__ import annotations

import collections
import io
import json
import mimetypes
import os
import re
import subprocess
import threading
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import diff
from .catalog import CATEGORIES, LABELS, TABLE_GROUPS
from .store import Store

VIEWER = Path(__file__).resolve().parent / 'viewer'
HASH = re.compile(r'^[0-9a-f]{32}$')
EXT = re.compile(r'^(\.[A-Za-z0-9_]{1,12})?$')
TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.webp': 'image/webp', '.json': 'application/json',
         '.txt': 'text/plain; charset=utf-8', '.obj': 'text/plain; charset=utf-8', '.mp4': 'video/mp4',
         '.webm': 'video/webm', '.ttf': 'font/ttf', '.otf': 'font/otf', '.wav': 'audio/wav', '.ogg': 'audio/ogg',
         '.mp3': 'audio/mpeg', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
         '.html': 'text/html; charset=utf-8', '.svg': 'image/svg+xml'}


class LRU:
    def __init__(self, size):
        self.size, self.data, self.lock = size, collections.OrderedDict(), threading.Lock()

    def get(self, key, make):
        with self.lock:
            if key in self.data:
                self.data.move_to_end(key)
                return self.data[key]
        value = make()
        with self.lock:
            self.data[key] = value
            self.data.move_to_end(key)
            while len(self.data) > self.size:
                self.data.popitem(last=False)
        return value


class Archive:
    def __init__(self, root):
        self.store = Store(root)
        self.manifests = LRU(6)
        self.comparisons = LRU(6)
        self.tables = LRU(4)
        self.texts = LRU(8)

    def versions(self):
        return self.store.index()

    def meta(self, vid):
        meta = self.store.version(vid)
        if not meta:
            raise LookupError('版本不存在：' + vid)
        return meta

    def manifest(self, vid):
        def make():
            entries = self.store.manifest(vid)
            tree = collections.defaultdict(collections.Counter)
            sizes = collections.Counter()
            for entry in entries:
                tree[entry[1]][entry[2]] += 1
                sizes[entry[1]] += entry[4]
            return {'entries': entries, 'by_path': {e[0]: e for e in entries}, 'tree': tree, 'sizes': sizes}
        return self.manifests.get(vid, make)

    def comparison(self, a, b):
        def make():
            old, new = self.meta(a), self.meta(b)
            scope = set(old.get('categories', [])) & set(new.get('categories', []))
            changes = diff.compare(self.manifest(a)['entries'], self.manifest(b)['entries'], scope)
            sources = diff.compare_sources(self.store.source_list(a), self.store.source_list(b))
            return {'changes': changes, 'summary': diff.summarize(changes), 'sources': sources, 'scope': sorted(scope)}
        return self.comparisons.get((a, b), make)

    def blob(self, digest, ext) -> Path:
        if not HASH.match(digest or '') or not EXT.match(ext or ''):
            raise LookupError('资源标识无效')
        path = self.store.blob_path(digest, ext)
        if not path.is_file():
            raise LookupError('资源文件不存在（可能已被清理）')
        return path

    def table(self, digest):
        return self.tables.get(digest, lambda: json.loads(self.blob(digest, '.json').read_text('utf8')))

    def text(self, digest, ext):
        def make():
            raw = self.blob(digest, ext).read_bytes()
            return diff.pretty(raw.decode('utf8', 'replace'), ext)
        return self.texts.get((digest, ext), make)


def _entry(e):
    return {'path': e[0], 'cat': e[1], 'group': e[2], 'hash': e[3], 'size': e[4], 'ext': e[5], 'src': e[6],
            'meta': e[7] or {}}


def _match(entry, query):
    return not query or query in entry[0].lower()


class Handler(BaseHTTPRequestHandler):
    archive: Archive = None
    server_version = 'SoCArchive/1'

    def log_message(self, *args):  # quiet console
        pass

    # -- plumbing ----------------------------------------------------------
    def send_json(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, content_type=None, immutable=False, name=None):
        size = path.stat().st_size
        start, end = 0, size - 1
        header = self.headers.get('Range')
        status = 200
        if header and header.startswith('bytes='):
            first, _, last = header[6:].split(',')[0].partition('-')
            try:
                if first:
                    start, end = int(first), int(last) if last else size - 1
                else:
                    start, end = max(0, size - int(last)), size - 1
                end = min(end, size - 1)
                status = 206 if start <= end else 416
            except ValueError:
                start, end = 0, size - 1
        if status == 416:
            self.send_response(416)
            self.send_header('Content-Range', f'bytes */{size}')
            self.end_headers()
            return
        self.send_response(status)
        self.send_header('Content-Type', content_type or TYPES.get(path.suffix.lower()) or
                         mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(end - start + 1))
        if status == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        if name:
            self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + urllib.parse.quote(name))
        self.send_header('Cache-Control', 'public, max-age=31536000, immutable' if immutable else 'no-cache')
        self.end_headers()
        with open(path, 'rb') as stream:
            stream.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                block = stream.read(min(1 << 20, remaining))
                if not block:
                    break
                try:
                    self.wfile.write(block)
                except (ConnectionError, OSError):
                    return
                remaining -= len(block)

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        query = {k: v[-1] for k, v in urllib.parse.parse_qs(url.query).items()}
        try:
            if url.path in ('/', '/index.html'):
                return self.send_file(VIEWER / 'index.html')
            if url.path.startswith('/static/'):
                target = (VIEWER / url.path[len('/static/'):]).resolve()
                if VIEWER.resolve() not in target.parents or not target.is_file():
                    raise LookupError('文件不存在')
                return self.send_file(target)
            if url.path.startswith('/blob/'):
                name = url.path[len('/blob/'):]
                digest, ext = name[:32], name[32:]
                return self.send_file(self.archive.blob(digest, ext), immutable=True, name=query.get('download'))
            if url.path.startswith('/thumb/'):
                name = url.path[len('/thumb/'):]
                return self.thumb(name[:32], name[32:])
            route = getattr(self, 'api_' + url.path[len('/api/'):], None) if url.path.startswith('/api/') else None
            if not route:
                raise LookupError('接口不存在')
            return self.send_json(route(query))
        except LookupError as error:
            self.send_json({'error': str(error)}, HTTPStatus.NOT_FOUND)
        except (ValueError, KeyError) as error:
            self.send_json({'error': f'{type(error).__name__}: {error}'}, HTTPStatus.BAD_REQUEST)
        except (ConnectionError, BrokenPipeError):
            pass
        except Exception as error:  # keep the browser informed instead of hanging
            self.send_json({'error': f'{type(error).__name__}: {error}'}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def thumb(self, digest, ext):
        source = self.archive.blob(digest, ext)
        target = self.archive.store.thumbs / digest[:2] / f'{digest}.png'
        if not target.is_file():
            from PIL import Image
            with Image.open(source) as image:
                image.thumbnail((160, 160))
                stream = io.BytesIO()
                image.save(stream, 'PNG', compress_level=1)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(stream.getvalue())
        return self.send_file(target, 'image/png', immutable=True)

    # -- API ---------------------------------------------------------------
    def api_info(self, q):
        store = self.archive.store
        return {'root': str(store.root.resolve()), 'categories': [{'key': k, 'label': v} for k, v in CATEGORIES],
                'tableGroups': TABLE_GROUPS, 'kinds': diff.KIND_LABELS, 'library': str(store.library.resolve())}

    def api_versions(self, q):
        return {'versions': self.archive.versions()}

    def api_version(self, q):
        vid = q['id']
        meta = self.archive.meta(vid)
        data = self.archive.manifest(vid)
        tree = [{'key': key, 'label': LABELS.get(key, key), 'count': sum(groups.values()), 'size': data['sizes'][key],
                 'groups': [{'key': g, 'count': n} for g, n in sorted(groups.items())]}
                for key, groups in sorted(data['tree'].items(), key=lambda kv: [k for k, _ in CATEGORIES].index(kv[0])
                                          if kv[0] in LABELS else 99)]
        changes = self.archive.store.changes(vid) or {}
        # The page needs only the error list; per-group change counts come from /api/compare.
        return {'meta': meta, 'tree': tree, 'changes': {'errors': changes.get('errors', [])}}

    def api_entries(self, q):
        data = self.archive.manifest(q['v'])
        cat, group, needle = q.get('cat'), q.get('group'), q.get('q', '').strip().lower()
        offset, limit = int(q.get('offset', 0)), min(500, int(q.get('limit', 200)))
        rows = [e for e in data['entries'] if (not cat or e[1] == cat) and (not group or e[2] == group) and _match(e, needle)]
        return {'total': len(rows), 'offset': offset, 'entries': [_entry(e) for e in rows[offset:offset + limit]]}

    def api_entry(self, q):
        entry = self.archive.manifest(q['v'])['by_path'].get(q['path'])
        if not entry:
            raise LookupError('该版本没有这个资源')
        return {'entry': _entry(entry)}

    def api_compare(self, q):
        a, b = q['a'], q['b']
        result = self.archive.comparison(a, b)
        summary = result['summary']
        categories = [{'key': key, 'label': LABELS.get(key, key), **value,
                       'groups': [{'key': g, **counts} for g, counts in value['groups'].items()]}
                      for key, value in sorted(summary['categories'].items(),
                                               key=lambda kv: [k for k, _ in CATEGORIES].index(kv[0]) if kv[0] in LABELS else 99)]
        return {'a': self.archive.meta(a), 'b': self.archive.meta(b), 'total': summary['total'],
                'changes': summary['changes'], 'categories': categories, 'scope': result['scope'],
                'sources': result['sources']['counts']}

    def api_changes(self, q):
        result = self.archive.comparison(q['a'], q['b'])
        cat, group, kind = q.get('cat'), q.get('group'), q.get('kind')
        needle = q.get('q', '').strip().lower()
        offset, limit = int(q.get('offset', 0)), min(500, int(q.get('limit', 200)))
        rows = []
        for change_kind, old, new in result['changes']:
            entry = new or old
            if cat and entry[1] != cat or group and entry[2] != group or kind and change_kind != kind:
                continue
            if needle and needle not in entry[0].lower() and not (old and needle in old[0].lower()):
                continue
            rows.append((change_kind, old, new))
        page = rows[offset:offset + limit]
        return {'total': len(rows), 'offset': offset,
                'changes': [{'kind': k, 'old': _entry(o) if o else None, 'new': _entry(n) if n else None} for k, o, n in page]}

    def api_sources(self, q):
        result = self.archive.comparison(q['a'], q['b'])['sources']
        kind = q.get('kind') or 'modified'
        offset, limit = int(q.get('offset', 0)), min(500, int(q.get('limit', 200)))
        old, new = self.archive.store.source_list(q['a']), self.archive.store.source_list(q['b'])
        rows = result.get(kind, [])
        return {'total': len(rows), 'kind': kind,
                'files': [{'rel': rel, 'before': old.get(rel, [None])[0], 'after': new.get(rel, [None])[0]}
                          for rel in rows[offset:offset + limit]]}

    def api_table(self, q):
        rows = self.archive.table(q['h'])
        rows = rows if isinstance(rows, list) else [rows]
        needle = q.get('q', '').strip().lower()
        offset, limit = int(q.get('offset', 0)), min(1000, int(q.get('limit', 200)))
        columns = list(dict.fromkeys(k for row in rows[:2000] if isinstance(row, dict) for k in row))
        if 'id' in columns:
            columns.remove('id')
            columns.insert(0, 'id')
        if needle:
            rows = [row for row in rows if needle in json.dumps(row, ensure_ascii=False).lower()]
        return {'total': len(rows), 'offset': offset, 'columns': columns, 'rows': rows[offset:offset + limit]}

    def api_tablediff(self, q):
        result = diff.table_diff(self.archive.table(q['a']), self.archive.table(q['b']), limit=int(q.get('limit', 2000)))
        return result

    def api_textdiff(self, q):
        ext = q.get('ext', '')
        left, right = self.archive.text(q['a'], ext), self.archive.text(q['b'], ext)
        return diff.text_diff(left, right, context=int(q.get('context', 3)))

    def api_text(self, q):
        text = self.archive.text(q['h'], q.get('ext', ''))
        limit = int(q.get('limit', 400000))
        return {'text': text[:limit], 'truncated': len(text) > limit, 'length': len(text)}

    def api_reveal(self, q):
        path = self.archive.blob(q['h'], q.get('ext', ''))
        if os.name == 'nt':
            subprocess.Popen(['explorer', '/select,', str(path)])
        return {'path': str(path)}

    def api_export(self, q):
        meta = self.archive.meta(q['v'])
        folder, linked, removed = self.archive.store.materialize(meta['id'], self.archive.store.library / meta['id'])
        if os.name == 'nt' and q.get('open'):
            subprocess.Popen(['explorer', str(folder)])
        return {'folder': str(folder), 'linked': linked, 'removed': removed}


def serve(root, port=0, open_browser=True, query='', host='127.0.0.1'):
    """Start the browser server in a background thread; returns (server, url)."""
    handler = type('BoundHandler', (Handler,), {'archive': Archive(root)})
    server = None
    for candidate in ([port] if port else [8765, 8766, 8767, 0]):
        try:
            server = ThreadingHTTPServer((host, candidate), handler)
            break
        except OSError:
            continue
    if server is None:
        raise OSError('无法启动本地资源浏览服务')
    server.daemon_threads = True
    url = f'http://{host}:{server.server_address[1]}/'
    threading.Thread(target=server.serve_forever, daemon=True, name='archive-viewer').start()
    if open_browser:
        webbrowser.open(url + (('#' + query) if query else ''))
    return server, url
