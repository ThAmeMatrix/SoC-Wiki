"""Work done inside the extraction processes.

Each task is a small batch of client files. Workers write resources straight
into the object store and return the manifest entries they produced, so the
coordinating process only merges lists. Everything here must stay importable
at module level for ``ProcessPoolExecutor`` on Windows.
"""
from __future__ import annotations

import collections
import ctypes as C
import gc
import io
import json
import math
import re
import struct
import time
from pathlib import Path

from .catalog import EXTRACTOR, classify_loose, group_of, inner, is_table_bundle, loose_path, safe_name
from .store import Store, blob_hash, file_hash

PNG_LEVEL = 1
TABLE_SOURCE = '#tables'
# UnityPy's message when a sprite's texture sits in a bundle that is not loaded.
EXTERNAL_TEXTURE = re.compile(r'File cab-[0-9a-f]+ not found in ', re.I)
ASSET_TYPES = ('Texture2D', 'Sprite', 'SpriteAtlas', 'TextAsset', 'Font', 'Mesh', 'AudioClip', 'VideoClip',
               'AnimationClip', 'AnimatorController', 'Material', 'Shader')


def cache_key(kind: str, digest: str) -> str:
    return blob_hash(f'{EXTRACTOR}|{kind}|{digest}'.encode())


def canonical(value):
    """JSON-ready value with a stable key order (numbers numerically, then text)."""
    if isinstance(value, dict):
        def order(key):
            if isinstance(key, (int, float)) and not isinstance(key, bool):
                return (0, key, '')
            return (1, 0, str(key))
        return {str(key): canonical(item) for key, item in sorted(value.items(), key=lambda kv: order(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [canonical(item) for item in value]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return str(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def json_bytes(value) -> bytes:
    text = json.dumps(canonical(value), ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    return text.encode('utf8', 'replace')


def run(task: dict) -> dict:
    store = Store(task['root'])
    game = Path(task['game'])
    started = time.perf_counter()
    if task['kind'] == 'tables':
        result = _tables(store, game, task)
    else:
        handler = _bundle if task['kind'] == 'bundle' else _loose
        result = {'results': [handler(store, game, item) for item in task['items']]}
    result['seconds'] = time.perf_counter() - started
    return result


# -- loose files -------------------------------------------------------------

def _looks_text(path: Path) -> bool:
    with open(path, 'rb') as stream:
        head = stream.read(65536)
    if b'\x00' in head:
        return False
    try:
        head.decode('utf8')
        return True
    except UnicodeDecodeError as error:
        # A multi-byte character cut at the end of the sample is still text.
        return error.start >= len(head) - 4


def _loose(store: Store, game: Path, item: dict) -> dict:
    rel = item['rel']
    path = game / rel
    digest = item.get('hash') or file_hash(path)
    cat, ext = classify_loose(rel)
    if cat == 'text' and not _looks_text(path):
        cat = 'data'  # e.g. the client's .proto files are encrypted, not readable text
    written = store.put_file(path, ext, digest)
    meta = None
    try:
        if ext == '.wem':
            meta = _riff_meta(path)
        elif ext == '.bnk':
            meta = _bank_meta(path)
        elif cat == 'text' and item['size'] < 8 * 1024 * 1024:
            meta = {'lines': path.read_bytes().count(b'\n') + 1}
    except (OSError, ValueError, struct.error):
        meta = None
    entry = [loose_path(cat, rel), cat, group_of(rel), digest, item['size'], ext, rel, meta]
    return {'rel': rel, 'size': item['size'], 'mtime': item['mtime'], 'hash': digest, 'entries': [entry],
            'written': written, 'blobs': 1 if written else 0, 'errors': [], 'cached': False}


def _riff_meta(path: Path):
    with open(path, 'rb') as stream:
        head = stream.read(4096)
    if head[:4] not in (b'RIFF', b'RIFX') or head[8:12] != b'WAVE':
        return None
    order = '<' if head[:4] == b'RIFF' else '>'
    position, fmt, size = 12, None, None
    while position + 8 <= len(head):
        chunk = head[position:position + 4]
        length = struct.unpack(order + 'I', head[position + 4:position + 8])[0]
        body = head[position + 8:position + 8 + min(length, 64)]
        if chunk == b'fmt ' and len(body) >= 12:
            fmt = struct.unpack(order + 'HHII', body[:12])
        if chunk == b'data':
            size = length
            break
        position += 8 + length + (length & 1)
    if not fmt:
        return None
    tag, channels, rate, per_second = fmt
    codec = {0x0001: 'PCM', 0xFFFE: 'PCM', 0x0002: 'ADPCM', 0xFFFF: 'Wwise Vorbis', 0x3040: 'Wwise Opus',
             0x3041: 'Wwise Opus'}.get(tag, f'0x{tag:04X}')
    meta = {'codec': codec, 'channels': channels, 'rate': rate}
    if size and per_second:
        meta['duration'] = round(size / per_second, 2)
    return meta


def _bank_meta(path: Path):
    meta = {}
    with open(path, 'rb') as stream:
        for _ in range(16):
            header = stream.read(8)
            if len(header) < 8:
                break
            chunk, length = header[:4], struct.unpack('<I', header[4:])[0]
            if chunk == b'BKHD':
                body = stream.read(min(length, 8))
                if len(body) == 8:
                    meta['version'], meta['bank'] = struct.unpack('<II', body)
                stream.seek(length - len(body), 1)
            elif chunk == b'DIDX':
                meta['embedded'] = length // 12
                stream.seek(length, 1)
            else:
                stream.seek(length, 1)
    return meta or None


# -- Unity bundles -----------------------------------------------------------

def _bundle(store: Store, game: Path, item: dict) -> dict:
    rel = item['rel']
    path = game / rel
    digest = item.get('hash') or file_hash(path)
    key = cache_key('bundle', digest)
    cached = store.cache_get(key)
    base = {'rel': rel, 'size': item['size'], 'mtime': item['mtime'], 'hash': digest}
    if cached is not None:
        return {**base, 'entries': cached['entries'], 'written': 0, 'blobs': 0,
                'errors': cached.get('errors', []), 'cached': True}
    entries, errors, written, blobs = _extract_bundle(store, path, rel)
    store.cache_put(key, {'entries': entries, 'errors': errors[:20]})
    gc.collect()
    return {**base, 'entries': entries, 'written': written, 'blobs': blobs, 'errors': errors, 'cached': False}


def _name(obj, fallback: str) -> str:
    try:
        name = obj.peek_name()
    except Exception:
        name = None
    return safe_name(name, fallback)


def _extract_bundle(store: Store, path: Path, rel: str):
    import UnityPy

    location, group = inner(rel), group_of(rel)
    entries, errors = [], []
    counters = {'written': 0, 'blobs': 0}

    def put(cat, name, data, ext, meta=None):
        digest, size, new = store.put_bytes(data, ext)
        counters['written'] += new
        counters['blobs'] += 1 if new else 0
        entries.append([f'{cat}/{location}/{name}{ext}', cat, group, digest, size, ext, rel, meta])
        return digest

    try:
        env = UnityPy.load(str(path))
        objects = list(env.objects)
    except Exception as error:  # damaged or unknown bundle: record it, keep going
        errors.append(f'{rel}: {type(error).__name__}: {error}'[:300])
        put('bundle', 'bundle', json_bytes({'source': rel, 'error': str(error)[:300]}), '.json', {'error': 1})
        entries[-1][0] = f'bundle/{location}.json'
        return entries, errors, counters['written'], counters['blobs']

    containers = {}
    try:
        for container_path, obj in env.container.items():
            containers.setdefault(obj.path_id, container_path)
    except Exception:
        pass
    lua = rel.lower().startswith('assets/lua/')
    tables = is_table_bundle(rel)
    plan = []
    for obj in objects:
        kind = obj.type.name
        if kind == 'Texture2D':
            plan.append(('image', obj))
        elif kind == 'Sprite':
            plan.append(('sprite', obj))
        elif kind == 'TextAsset' and not tables:
            plan.append(('script' if lua else 'text', obj))
        elif kind == 'Font':
            plan.append(('font', obj))
        elif kind == 'Mesh':
            plan.append(('model', obj))
        elif kind == 'AudioClip':
            plan.append(('audio', obj))
        elif kind == 'VideoClip':
            plan.append(('video', obj))
        elif kind == 'MonoBehaviour' and obj.path_id in containers:
            plan.append(('data', obj))
    named = [(cat, _name(obj, f'{obj.type.name}_{obj.path_id}'), obj) for cat, obj in plan]
    # Same-named objects of one kind get their object id, so every path stays unique.
    taken = collections.Counter((cat, name.lower()) for cat, name, _ in named)
    resolved = []
    for cat, name, obj in named:
        if taken[(cat, name.lower())] > 1:
            name = f'{name}~{obj.path_id}'
        resolved.append((cat, name, obj))

    textures = {}
    sprite_refs = 0
    order = {'image': 0}
    for cat, name, obj in sorted(resolved, key=lambda item: order.get(item[0], 1)):
        try:
            if cat == 'image':
                data = obj.read()
                width, height = int(data.m_Width or 0), int(data.m_Height or 0)
                if not width or not height:
                    continue
                meta = {'w': width, 'h': height, 'format': _texture_format(data)}
                try:
                    picture = data.image
                except Exception as error:
                    # Keep a fingerprint so the object still takes part in comparisons, and report it.
                    message = f'{type(error).__name__}: {error}'[:160]
                    errors.append(f'{rel} image:{name}: {message}'[:300])
                    raw = obj.get_raw_data()
                    entries.append([f'image/{location}/{name}.png', 'image', group, blob_hash(raw), len(raw), '.png',
                                    rel, {**meta, 'noblob': 1, 'error': message}])
                    continue
                stream = io.BytesIO()
                picture.save(stream, 'PNG', compress_level=PNG_LEVEL)
                digest = put('image', name, stream.getvalue(), '.png', meta)
                textures[obj.path_id] = (digest, width, height)
            elif cat == 'sprite':
                data = obj.read()
                render = data.m_RD
                texture = render.texture
                atlas = getattr(data, 'm_SpriteAtlas', None)
                if not texture.m_PathID and not getattr(atlas, 'm_PathID', 0):
                    sprite_refs += 1  # resolved by a sprite atlas elsewhere; counted in the bundle list
                    continue
                rect = render.textureRect
                own = textures.get(texture.m_PathID) if texture.m_FileID == 0 else None
                if own and not (render.settingsRaw & 1) and rect.x < .5 and rect.y < .5 \
                        and abs(rect.width - own[1]) < .5 and abs(rect.height - own[2]) < .5:
                    # The sprite is the whole texture: point at the same picture.
                    entries.append([f'sprite/{location}/{name}.png', 'sprite', group, own[0],
                                    store.blob_path(own[0], '.png').stat().st_size, '.png', rel,
                                    {'w': own[1], 'h': own[2], 'alias': 1}])
                    continue
                try:
                    picture = data.image
                except FileNotFoundError as error:
                    # Only UnityPy's "File cab-… not found in …" means the texture lives in another
                    # bundle (archived there); any other missing file is a real failure.
                    if not EXTERNAL_TEXTURE.match(str(error)):
                        raise
                    sprite_refs += 1
                    continue
                stream = io.BytesIO()
                picture.save(stream, 'PNG', compress_level=PNG_LEVEL)
                put('sprite', name, stream.getvalue(), '.png', {'w': picture.width, 'h': picture.height})
            elif cat in ('text', 'script'):
                data = obj.read()
                script = data.m_Script
                raw = script.encode('utf8', 'surrogateescape') if isinstance(script, str) else bytes(script)
                if cat == 'script':
                    put('script', name, raw, '.luac')
                    continue
                try:
                    text = raw.decode('utf8')
                    printable = sum(1 for ch in text[:4096] if ch.isprintable() or ch in '\r\n\t') / max(1, min(len(text), 4096))
                except UnicodeDecodeError:
                    printable = 0
                if printable >= .95:
                    put('text', name, raw, '.txt', {'lines': raw.count(b'\n') + 1})
                else:
                    put('data', name, raw, '.bytes')
            elif cat == 'font':
                data = obj.read()
                raw = bytes(data.m_FontData or b'')
                if raw:
                    put('font', name, raw, '.otf' if raw[:4] == b'OTTO' else '.ttf')
            elif cat == 'model':
                data = obj.read()
                text = data.export()
                if text:
                    raw = text.encode('utf8')
                    put('model', name, raw, '.obj', {'vertices': raw.count(b'\nv ') + raw.startswith(b'v ')})
            elif cat == 'audio':
                data = obj.read()
                try:
                    samples = data.samples
                except Exception:
                    samples = {}
                if samples:
                    for index, (sample_name, wav) in enumerate(samples.items()):
                        put('audio', name if index == 0 else safe_name(f'{name}-{sample_name}', name), wav, '.wav')
                else:
                    raw = bytes(getattr(data, 'm_AudioData', b'') or b'')
                    if raw:
                        put('audio', name, raw, '.bin')
            elif cat == 'video':
                data = obj.read()
                raw = bytes(getattr(data, 'm_VideoData', b'') or b'')
                if raw:
                    suffix = Path(str(getattr(data, 'm_OriginalPath', '') or '')).suffix.lower() or '.bin'
                    put('video', name, raw, suffix)
            elif cat == 'data':
                tree = obj.read_typetree()
                put('data', name, json_bytes(tree), '.json')
        except Exception as error:
            errors.append(f'{rel} {cat}:{name}: {type(error).__name__}: {error}'[:300])

    counts = collections.Counter(obj.type.name for obj in objects)
    kinds = {obj.path_id: obj.type.name for obj in objects}
    listing = collections.defaultdict(list)
    for obj in objects:
        if obj.type.name in ASSET_TYPES:
            listing[obj.type.name].append(_name(obj, str(obj.path_id)))
    # The inventory holds only what the bundle contains, so tool changes never look like game changes.
    inventory = {
        'source': rel,
        'objects': dict(sorted(counts.items())),
        'container': sorted([path_, kinds.get(pid, '')] for pid, path_ in containers.items()),
        'assets': {kind: sorted(names) for kind, names in sorted(listing.items())},
    }
    digest, size, new = store.put_bytes(json_bytes(inventory), '.json')
    counters['written'] += new
    counters['blobs'] += 1 if new else 0
    meta = {'objects': len(objects)}
    if sprite_refs:
        meta['spriteReferences'] = sprite_refs
    if errors:
        meta['errors'] = len(errors)
    entries.append([f'bundle/{location}.json', 'bundle', group, digest, size, '.json', rel, meta])
    del env, objects
    return entries, errors, counters['written'], counters['blobs']


def _texture_format(data) -> str:
    value = getattr(data, 'm_TextureFormat', None)
    try:
        from UnityPy.enums import TextureFormat
        return TextureFormat(value).name
    except Exception:
        return str(value)


# -- configuration tables ------------------------------------------------------

_VM = {'key': None, 'vm': None}
_SCRIPTS = {'key': None, 'scripts': None}
TOLERANT = r'''
-- Tables whose loaders call helpers this reader does not provide get a no-op.
local function lenient(t) return setmetatable(t, {__index=function() return function() return {} end end}) end
lenient(Database.db_loader); lenient(Global)
'''


def _lua(game: Path, db_hash: str):
    from ..client import LuaTables, text_assets

    class ArchiveLua(LuaTables):
        def string(self, index):
            length = C.c_size_t()
            pointer = self.lua_tolstring(self.L, index, C.byref(length))
            # Binary strings inside a few tables are kept readable instead of failing.
            return C.string_at(pointer, length.value).decode('utf8', 'backslashreplace') if pointer else None

    if _VM['key'] != db_hash:
        if _VM['vm']:
            _VM['vm'].close()
        vm = ArchiveLua(game / 'SoC_Data/Plugins/x86_64/slua.dll')
        vm.setup(text_assets(game / 'assets/lua/lua_db.unity3d'))
        vm.run(TOLERANT, 'tolerant')
        _VM.update(key=db_hash, vm=vm)
    return _VM['vm']


def _scripts(game: Path, rel: str, digest: str):
    from ..client import text_assets
    if _SCRIPTS['key'] != (rel, digest):
        _SCRIPTS.update(key=(rel, digest), scripts=text_assets(game / rel))
    return _SCRIPTS['scripts']


def table_key(rows):
    if rows and all(isinstance(row, dict) for row in rows):
        for column in ('id', 'ID', 'Id', 'key'):
            values = [row.get(column) for row in rows]
            if all(value is not None for value in values):
                hashed = [json.dumps(value, sort_keys=True, default=str) for value in values]
                if len(set(hashed)) == len(hashed):
                    return column
    return None


def _tables(store: Store, game: Path, task: dict) -> dict:
    """One share of a table bundle: every ``parts``-th table by size, from ``part``."""
    rel, stem = task['bundle'], Path(task['bundle']).stem
    # Decoded tables depend on the loader too, so they are tracked as their own source.
    source = rel + TABLE_SOURCE
    vm = _lua(game, task['dbHash'])
    scripts = _scripts(game, rel, task['bundleHash'])
    ordered = [name for _, name in sorted(((-len(data), name) for name, data in scripts.items()))]
    names = [name for name in ordered if name in vm.schema][task['part']::task['parts']]
    raw = [name for name in ordered if name not in vm.schema] if task['part'] == 0 else []
    entries, errors = [], []
    written = blobs = 0
    for name in names:
        data = scripts[name]
        try:
            rows = vm.table(name, data)
            payload = json_bytes(rows)
            columns = sorted({key for row in rows if isinstance(row, dict) for key in row})
            digest, size, new = store.put_bytes(payload, '.json')
            entries.append([f'table/{stem}/{safe_name(name, "table")}.json', 'table', stem, digest, size, '.json',
                            source, {'rows': len(rows), 'cols': len(columns), 'key': table_key(rows)}])
        except Exception as error:
            message = f'{type(error).__name__}: {error}'[:200]
            errors.append(f'{source} {name}: {message}')
            digest, size, new = store.put_bytes(data, '.luac')
            entries.append([f'script/lua/{stem}/{safe_name(name, "script")}.luac', 'script', 'lua/' + stem, digest,
                            size, '.luac', source, {'error': message}])
        written += new
        blobs += 1 if new else 0
    for name in raw:
        digest, size, new = store.put_bytes(scripts[name], '.luac')
        entries.append([f'script/lua/{stem}/{safe_name(name, "script")}.luac', 'script', 'lua/' + stem, digest,
                        size, '.luac', source, None])
        written += new
        blobs += 1 if new else 0
    return {'tables': {'bundle': rel, 'part': task['part'], 'entries': entries, 'errors': errors,
                       'written': written, 'blobs': blobs, 'count': len(names)}}
