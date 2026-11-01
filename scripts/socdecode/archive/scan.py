"""Scan the installed client and record a new archive version when anything changed.

Stages, each reported through ``progress``:

1. walk      – list client files (account data, battle reports and preferences excluded)
2. plan      – reuse everything whose size, time and hash match the last scan
3. extract   – parse the rest in parallel processes; results are cached per file
               content, so a cancelled or crashed run resumes where it stopped
4. version   – merge, compare with the previous version, write manifest and diff
5. organise  – refresh the categorised folders (hard links, no extra space)
"""
from __future__ import annotations

import collections
import concurrent.futures as futures
import json
import math
import os
import threading
import time
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

from . import diff, extract
from .catalog import BUNDLE_CATEGORIES, KEYS, LABELS, classify_loose, excluded, is_bundle, is_table_bundle
from .store import Store, blob_hash, file_hash

STAGES = (('walk', '扫描客户端文件'), ('plan', '比对上次结果'), ('extract', '解析资源'),
          ('version', '生成版本与差分'), ('organise', '整理分类目录'))
STAGE_LABELS = dict(STAGES)
LUA_DB = 'assets/lua/lua_db.unity3d'
LUA_DLL = 'SoC_Data/Plugins/x86_64/slua.dll'


class Cancelled(Exception):
    pass


def default_workers() -> int:
    return max(2, min(16, (os.cpu_count() or 4) - 2))


def locate(path) -> Path:
    path = Path(path)
    for root in (path, path / 'SwordOfConvallaria', path / 'SoCLauncher/SwordOfConvallaria'):
        if (root / LUA_DB).is_file() and (root / LUA_DLL).is_file():
            return root.resolve()
    raise ValueError(f'未找到游戏客户端：{path}。请指定 SoCLauncher 或 SwordOfConvallaria 目录。')


class Reporter:
    """Throttled progress events with rate and remaining time."""

    def __init__(self, sink, log):
        self.sink, self.log_sink = sink, log
        self.stage, self.started, self.last = None, time.time(), 0.0
        self.stage_started = time.time()

    def log(self, text):
        if self.log_sink:
            self.log_sink(text)

    def begin(self, stage):
        self.stage, self.stage_started = stage, time.time()
        self.emit(force=True)

    def emit(self, done=0, total=0, size_done=0, size_total=0, detail='', stats=None, force=False):
        now = time.time()
        if not self.sink or (not force and now - self.last < .1):
            return
        self.last = now
        elapsed = now - self.stage_started
        rate = size_done / elapsed if elapsed > .5 and size_done else 0
        eta = (size_total - size_done) / rate if rate and size_total else None
        index = [key for key, _ in STAGES].index(self.stage) + 1 if self.stage else 0
        self.sink({'stage': self.stage, 'label': STAGE_LABELS.get(self.stage, ''), 'step': index, 'steps': len(STAGES),
                   'done': done, 'total': total, 'bytesDone': size_done, 'bytesTotal': size_total, 'rate': rate,
                   'eta': eta, 'elapsed': now - self.started, 'detail': detail, 'stats': stats or {}})


def walk(root: Path, reporter: Reporter):
    files = []
    root_text = str(root)
    for folder, dirs, names in os.walk(root):
        relative = os.path.relpath(folder, root_text).replace('\\', '/')
        relative = '' if relative == '.' else relative + '/'
        dirs[:] = sorted(d for d in dirs if not excluded(relative + d + '/'))
        for name in sorted(names):
            rel = relative + name
            if excluded(rel):
                continue
            try:
                info = os.stat(os.path.join(folder, name))
            except OSError:
                continue
            files.append((rel, info.st_size, info.st_mtime_ns))
        if len(files) % 2000 < len(names):
            reporter.emit(done=len(files), detail=relative)
    return files


def _wanted(rel: str, categories: set) -> bool:
    if is_bundle(rel):
        return bool(categories & BUNDLE_CATEGORIES) or (is_table_bundle(rel) and 'table' in categories)
    return classify_loose(rel)[0] in categories


def _batches(items, limit_bytes, limit_count):
    batch, size = [], 0
    for item in items:
        if batch and (size + item['size'] > limit_bytes or len(batch) >= limit_count):
            yield batch
            batch, size = [], 0
        batch.append(item)
        size += item['size']
    if batch:
        yield batch


def _game_version(root: Path):
    try:
        from ..client import text_assets
        data = json.loads(text_assets(root / 'assets/resource_version.unity3d')['resource_version'])
        return {'changeNumber': data.get('change_number'), 'resourceVersion': data}
    except Exception:
        return {'changeNumber': None, 'resourceVersion': None}


def scan(game, archive, *, workers=None, categories=None, organise=True, progress=None, log=None,
         cancel: threading.Event | None = None) -> dict:
    started = time.time()
    reporter = Reporter(progress, log)
    root = locate(game)
    store = Store(archive)
    store.root.mkdir(parents=True, exist_ok=True)
    categories = set(categories or KEYS)
    workers = max(1, int(workers or default_workers()))

    def check():
        if cancel is not None and cancel.is_set():
            raise Cancelled('已取消；已完成的部分会在下次解析时直接复用。')

    # 1 -- walk -----------------------------------------------------------------
    reporter.begin('walk')
    files = walk(root, reporter)
    wanted = [f for f in files if _wanted(f[0], categories)]
    reporter.log(f'客户端：{root}\n文件 {len(files):,} 个（{sum(f[1] for f in files) / 2**30:.2f} GB），'
                 f'本次解析范围 {len(wanted):,} 个。')
    check()

    # 2 -- plan -----------------------------------------------------------------
    reporter.begin('plan')
    state = store.load_state()
    known = state.get('files', {})
    previous = store.latest()
    previous_ok = bool(previous) and set(previous.get('categories', [])) >= categories \
        and previous.get('extractor') == extract.EXTRACTOR
    previous_sources = store.source_list(previous['id']) if previous_ok else {}
    by_source = collections.defaultdict(list)
    previous_errors = collections.defaultdict(list)
    if previous_ok:
        for entry in store.manifest(previous['id']):
            by_source[entry[6]].append(entry)
        for message in (store.changes(previous['id']) or {}).get('errors', []):
            # Messages start with their source: "<client file> <object>: <reason>".
            previous_errors[message.split(' ', 1)[0].rstrip(':')].append(message)

    def known_hash(rel, size, mtime):
        record = known.get(rel)
        return record[2] if record and record[0] == size and record[1] == mtime else None

    # Objects that could not be decoded stay listed in every version that still contains them.
    errors = []
    entries, sources, hashes = [], {}, {}
    bundle_items, loose_items = [], []
    reused = cached = 0
    for index, (rel, size, mtime) in enumerate(wanted):
        digest = known_hash(rel, size, mtime)
        if digest and previous_sources.get(rel, [None, None])[1] == digest:
            entries += by_source.get(rel, [])
            errors += previous_errors.get(rel, [])
            sources[rel] = [size, digest]
            hashes[rel] = [size, mtime, digest]
            reused += 1
            continue
        if is_bundle(rel):
            hit = store.cache_get(extract.cache_key('bundle', digest)) if digest else None
            if hit is not None:
                entries += hit['entries']
                errors += hit.get('errors', [])
                sources[rel] = [size, digest]
                hashes[rel] = [size, mtime, digest]
                cached += 1
                continue
            bundle_items.append({'rel': rel, 'size': size, 'mtime': mtime, 'hash': digest})
        else:
            loose_items.append({'rel': rel, 'size': size, 'mtime': mtime, 'hash': digest})
        if index % 500 == 0:
            reporter.emit(done=index, total=len(wanted))

    # Tables depend on their bundle, the loader bundle and the Lua runtime together.
    table_jobs = []
    if 'table' in categories:
        stats = {rel: (size, mtime) for rel, size, mtime in files}

        def current_hash(rel):
            size, mtime = stats[rel]
            return known_hash(rel, size, mtime) or file_hash(root / rel)
        loader = blob_hash(f'{current_hash(LUA_DB)}|{current_hash(LUA_DLL)}'.encode())
        for rel, size, mtime in wanted:
            if not is_table_bundle(rel):
                continue
            pseudo = rel + extract.TABLE_SOURCE
            key = blob_hash(f'{current_hash(rel)}|{loader}'.encode())
            sources[pseudo] = [size, key]
            if previous_sources.get(pseudo, [None, None])[1] == key:
                entries += by_source.get(pseudo, [])
                errors += previous_errors.get(pseudo, [])
                reused += 1
                continue
            hit = store.cache_get(extract.cache_key('tables', key))
            if hit is not None:
                entries += hit['entries']
                errors += hit.get('errors', [])
                cached += 1
                continue
            parts = max(1, min(workers, math.ceil(size / (4 * 2**20))))
            table_jobs.append({'rel': rel, 'size': size, 'key': key, 'parts': parts, 'hash': current_hash(rel),
                               'loader': loader})
    todo_bytes = sum(i['size'] for i in bundle_items + loose_items) + sum(j['size'] for j in table_jobs)
    reporter.log(f'复用上次结果 {reused:,} 个、命中缓存 {cached:,} 个；需要解析：资源包 {len(bundle_items):,} 个、'
                 f'散件 {len(loose_items):,} 个、配置表包 {len(table_jobs)} 个（{todo_bytes / 2**30:.2f} GB）。')
    check()

    # 3 -- extract --------------------------------------------------------------
    reporter.begin('extract')
    tasks = []
    for job in table_jobs:
        for part in range(job['parts']):
            tasks.append({'kind': 'tables', 'bundle': job['rel'], 'part': part, 'parts': job['parts'],
                          'bundleHash': job['hash'], 'dbHash': job['loader'], 'size': job['size'] / job['parts']})
    for batch in _batches(sorted(bundle_items, key=lambda i: -i['size']), 48 * 2**20, 24):
        tasks.append({'kind': 'bundle', 'items': batch, 'size': sum(i['size'] for i in batch)})
    for batch in _batches(loose_items, 256 * 2**20, 300):
        tasks.append({'kind': 'loose', 'items': batch, 'size': sum(i['size'] for i in batch)})
    for task in tasks:
        task.update(root=str(store.root), game=str(root), attempt=0)

    stats = {'processed': 0, 'reused': reused, 'cached': cached, 'newBlobs': 0, 'writtenBytes': 0, 'errors': len(errors)}
    table_parts = collections.defaultdict(list)
    table_meta = {job['rel']: job for job in table_jobs}
    done_bytes = 0
    done_items = 0
    total_items = len(bundle_items) + len(loose_items) + sum(j['parts'] for j in table_jobs)

    def accept(task, result):
        nonlocal done_bytes, done_items
        for item in result.get('results', []):
            entries.extend(item['entries'])
            sources[item['rel']] = [item['size'], item['hash']]
            hashes[item['rel']] = [item['size'], item['mtime'], item['hash']]
            stats['processed'] += 0 if item.get('cached') else 1
            stats['cached'] += 1 if item.get('cached') else 0
            stats['newBlobs'] += item['blobs']
            stats['writtenBytes'] += item['written']
            if item['errors']:
                stats['errors'] += len(item['errors'])
                errors.extend(item['errors'][:20])
            done_items += 1
        part = result.get('tables')
        if part:
            table_parts[part['bundle']].append(part)
            stats['newBlobs'] += part['blobs']
            stats['writtenBytes'] += part['written']
            stats['errors'] += len(part['errors'])
            errors.extend(part['errors'])
            done_items += 1
            job = table_meta[part['bundle']]
            if len(table_parts[part['bundle']]) == job['parts']:
                shares = table_parts[part['bundle']]
                produced = [e for share in shares for e in share['entries']]
                entries.extend(produced)
                store.cache_put(extract.cache_key('tables', job['key']),
                                {'entries': produced, 'errors': [m for share in shares for m in share['errors']]})
                stats['processed'] += 1
                reporter.log(f"配置表 {Path(job['rel']).stem}：{sum(s['count'] for s in shares)} 张")
        done_bytes += task['size']

    def fail(task, message):
        nonlocal done_bytes, done_items
        errors.append(message)
        stats['errors'] += 1
        done_bytes += task['size']
        done_items += len(task.get('items', [])) or 1

    queue = collections.deque(tasks)
    running = {}
    pool = None
    try:
        while queue or running:
            check()
            if pool is None:
                pool = futures.ProcessPoolExecutor(max_workers=workers, max_tasks_per_child=64)
            while queue and len(running) < workers * 2:
                task = queue.popleft()
                running[pool.submit(extract.run, task)] = task
            finished, _ = futures.wait(running, timeout=.25, return_when=futures.FIRST_COMPLETED)
            broken = False
            for future in finished:
                task = running.pop(future)
                try:
                    accept(task, future.result())
                except BrokenProcessPool:
                    broken = True
                    queue.appendleft(task)
                except Exception as error:
                    fail(task, f"{task['kind']} {(task.get('items') or [{}])[0].get('rel', task.get('bundle'))}: "
                               f"{type(error).__name__}: {error}"[:300])
            if broken:
                # A worker died (native decoder crash). Retry the unfinished work in a
                # fresh pool, one file at a time; a file that crashes twice is skipped.
                pool.shutdown(wait=False, cancel_futures=True)
                pool = None
                retry = list(running.values()) + list(queue)
                running.clear()
                queue.clear()
                for task in retry:
                    task['attempt'] += 1
                    items = task.get('items')
                    if items and len(items) > 1:
                        for item in items:
                            queue.append({**task, 'items': [item], 'size': item['size']})
                    elif task['attempt'] >= 3:
                        fail(task, f"跳过导致解析进程崩溃的文件：{(items or [{}])[0].get('rel', task.get('bundle'))}")
                    else:
                        queue.append(task)
                reporter.log('一个解析进程意外退出，已重新启动并逐个重试未完成的文件。')
            reporter.emit(done=done_items, total=total_items, size_done=done_bytes, size_total=todo_bytes,
                          detail=f'{len(running)} 个任务进行中', stats=stats)
    finally:
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)
    reporter.emit(done=total_items, total=total_items, size_done=todo_bytes, size_total=todo_bytes, stats=stats, force=True)
    check()

    # 4 -- version ----------------------------------------------------------------
    reporter.begin('version')
    unique = {}
    for entry in entries:
        if entry[1] not in categories:
            continue
        path = entry[0]
        if path in unique and unique[path][6] != entry[6]:
            entry = [f'{path}@{entry[6]}', *entry[1:]]
        unique[entry[0]] = entry
    entries = sorted(unique.values(), key=lambda e: e[0])
    for rel in list(hashes):
        known[rel] = hashes[rel]
    present = {f[0] for f in files}
    state['files'] = {rel: value for rel, value in known.items() if rel in present}

    previous_entries = store.manifest(previous['id']) if previous else []
    compared = categories & set(previous.get('categories', [])) if previous else categories
    changes = diff.compare(previous_entries, entries, compared) if previous else \
        [('added', None, entry) for entry in entries]
    source_changes = diff.compare_sources(store.source_list(previous['id']) if previous else {}, sources)
    same_scope = previous and set(previous.get('categories', [])) == categories
    if previous and same_scope and not changes:
        store.save_state(state)
        result = {'status': 'unchanged', 'version': previous['id'], 'label': previous['label'],
                  'seconds': time.time() - started, 'stats': stats, 'errors': errors[:50]}
        reporter.log(f"与上一版本（{previous['label']}）完全一致，未生成新版本。用时 {result['seconds']:.1f} 秒。")
        if organise:
            _organise(store, previous['id'], reporter)
        return result

    now = time.localtime()
    vid = store.new_version_id(time.strftime('%Y%m%d-%H%M%S', now))
    counts = {}
    for entry in entries:
        bucket = counts.setdefault(entry[1], {'n': 0, 'size': 0})
        bucket['n'] += 1
        bucket['size'] += entry[4]
    summary = diff.summarize(changes)
    meta = {
        'id': vid, 'label': time.strftime('%Y-%m-%d %H:%M:%S', now), 'time': time.strftime('%Y-%m-%dT%H:%M:%S%z', now),
        'parent': previous['id'] if previous else None, 'game': {'root': str(root), **_game_version(root)},
        'categories': [key for key in KEYS if key in categories], 'compared': sorted(compared),
        'counts': {key: counts[key] for key in KEYS if key in counts},
        'entries': len(entries), 'bytes': sum(e[4] for e in entries), 'sources': len(sources),
        'durationSeconds': round(time.time() - started, 1), 'stats': stats, 'extractor': extract.EXTRACTOR,
        'changes': {**summary['total'], 'total': summary['changes']},
        'sourceChanges': source_changes['counts'], 'errors': len(errors),
    }
    store.write_version(meta, entries, sources,
                        {'parent': meta['parent'], 'summary': summary, 'sources': source_changes, 'errors': errors[:5000]},
                        diff.report(meta, summary, changes, source_changes, LABELS))
    state['version'] = vid
    store.save_state(state)
    reporter.log(f"已生成版本 {meta['label']}：{len(entries):,} 项资源，"
                 + (f"相比 {previous['label']} 新增 {summary['total']['added']:,}、修改 {summary['total']['modified']:,}、"
                    f"删除 {summary['total']['removed']:,}、改名 {summary['total']['renamed']:,}。" if previous else '首个版本。'))
    if errors:
        reporter.log(f'有 {len(errors)} 个对象未能解析（已跳过，详见版本记录 changes.json）：')
        for message in errors[:5]:
            reporter.log('  ' + message)
    if organise:
        _organise(store, vid, reporter)
    meta['seconds'] = time.time() - started
    return {'status': 'created', 'version': vid, 'label': meta['label'], 'meta': meta,
            'seconds': meta['seconds'], 'stats': stats, 'errors': errors[:50]}


def _organise(store: Store, vid: str, reporter: Reporter):
    reporter.begin('organise')
    folder, linked, removed = store.materialize(
        vid, progress=lambda done, total: reporter.emit(done=done, total=total, detail='链接分类目录'))
    reporter.log(f'分类目录已更新：{folder}（新链接 {linked:,}，移除 {removed:,}）')
