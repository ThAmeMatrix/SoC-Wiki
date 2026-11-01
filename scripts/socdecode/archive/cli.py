"""Command line for the resource archive.

    python -X utf8 scripts/update_client.py archive scan            # 解析并记录新版本（无变化时不生成）
    python -X utf8 scripts/update_client.py archive versions        # 列出全部版本
    python -X utf8 scripts/update_client.py archive diff A B        # 比较任意两个版本（省略则比较最新与上一版）
    python -X utf8 scripts/update_client.py archive serve           # 打开可视化资源浏览与差分工具
    python -X utf8 scripts/update_client.py archive export VERSION  # 把某个版本整理成分类目录
    python -X utf8 scripts/update_client.py archive unexport FOLDER # 删除 export 生成的分类目录
    python -X utf8 scripts/update_client.py archive delete VERSION  # 删除版本记录（gc 后释放空间）
    python -X utf8 scripts/update_client.py archive gc              # 清理不再被任何版本引用的文件
"""
from __future__ import annotations

import argparse
import multiprocessing
import sys
import threading
import time
from pathlib import Path

from ..config import archive_path, game_path
from . import diff
from .catalog import KEYS, LABELS
from .scan import Cancelled, default_workers, scan
from .store import Store


def _size(value: float) -> str:
    for unit in ('B', 'KB', 'MB', 'GB'):
        if abs(value) < 1024 or unit == 'GB':
            return f'{value:,.1f} {unit}' if unit != 'B' else f'{int(value)} B'
        value /= 1024
    return f'{value:.1f} GB'


def _clock(seconds) -> str:
    if seconds is None:
        return '--:--'
    seconds = int(seconds)
    return f'{seconds // 3600:d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}' if seconds >= 3600 else f'{seconds // 60:02d}:{seconds % 60:02d}'


class ConsoleProgress:
    def __init__(self):
        # A windowed build may have no stdout at all.
        self.tty = bool(sys.stdout and sys.stdout.isatty())
        self.last = 0.0
        self.stage = None

    def __call__(self, event):
        now = time.time()
        if event['stage'] != self.stage:
            if self.tty and self.stage:
                print()
            self.stage = event['stage']
            print(f"[{event['step']}/{event['steps']}] {event['label']}", flush=True)
            self.last = now
            return
        if now - self.last < (0.2 if self.tty else 5):
            return
        self.last = now
        parts = []
        if event['total']:
            parts.append(f"{event['done']:,}/{event['total']:,}")
        if event['bytesTotal']:
            parts.append(f"{_size(event['bytesDone'])}/{_size(event['bytesTotal'])}")
        if event['rate']:
            parts.append(f"{_size(event['rate'])}/s")
        if event['eta'] is not None:
            parts.append('剩余 ' + _clock(event['eta']))
        if event['stats'].get('newBlobs'):
            parts.append(f"新文件 {event['stats']['newBlobs']:,}")
        line = '  ' + ' · '.join(parts)
        if self.tty:
            print('\r' + line.ljust(100), end='', flush=True)
        else:
            print(line, flush=True)


def parser():
    p = argparse.ArgumentParser(prog='archive', description='铃兰之剑客户端资源归档：解析、版本记录与差分。')
    p.add_argument('--archive', type=Path, default=None, help=f'归档目录（默认 {archive_path()}）')
    subs = p.add_subparsers(dest='command', required=True)
    s = subs.add_parser('scan', help='解析客户端全部资源；与上一版本不同时记录新版本')
    s.add_argument('--game', type=Path, default=None, help='游戏安装或启动器目录')
    s.add_argument('--workers', type=int, default=None, help=f'并行进程数（默认 {default_workers()}）')
    s.add_argument('--only', default='', help='只解析这些分类，逗号分隔：' + ','.join(KEYS))
    s.add_argument('--no-organise', action='store_true', help='不刷新分类目录')
    subs.add_parser('versions', help='列出全部版本')
    d = subs.add_parser('diff', help='比较两个版本')
    d.add_argument('base', nargs='?', help='基准版本（默认：目标的上一版本）')
    d.add_argument('target', nargs='?', help='目标版本（默认：最新）')
    d.add_argument('--limit', type=int, default=40, help='每个分类最多列出的条目')
    v = subs.add_parser('serve', help='打开可视化资源浏览与差分')
    v.add_argument('--port', type=int, default=0)
    v.add_argument('--no-browser', action='store_true')
    e = subs.add_parser('export', help='把某个版本整理成分类目录（硬链接）')
    e.add_argument('version')
    e.add_argument('folder', nargs='?', type=Path)
    u = subs.add_parser('unexport', help='删除 export 生成的分类目录（资源本身保留）')
    u.add_argument('folder', type=Path)
    x = subs.add_parser('delete', help='删除一个版本记录')
    x.add_argument('version')
    subs.add_parser('gc', help='清理不再被任何版本引用的文件')
    return p


def resolve(store: Store, value: str | None):
    versions = store.index()
    if not versions:
        raise ValueError('归档里还没有版本，请先运行 archive scan。')
    if not value:
        return versions[-1]
    for meta in versions:
        if meta['id'] == value or meta['label'] == value:
            return meta
    matches = [meta for meta in versions if meta['id'].startswith(value)]
    if len(matches) == 1:
        return matches[0]
    raise ValueError(f'找不到版本 {value}；用 archive versions 查看全部版本。')


def main(argv=None) -> int:
    multiprocessing.freeze_support()
    args = parser().parse_args(argv)
    root = args.archive or archive_path()
    store = Store(root)
    try:
        if args.command == 'scan':
            game = args.game or game_path()
            only = [c.strip() for c in args.only.split(',') if c.strip()] or None
            unknown = set(only or []) - set(KEYS)
            if unknown:
                raise ValueError('未知分类：' + ', '.join(sorted(unknown)))
            # Command-line options apply to this run only; the GUI is where folders are remembered.
            cancel = threading.Event()
            try:
                result = scan(game, root, workers=args.workers, categories=only, organise=not args.no_organise,
                              progress=ConsoleProgress(), log=lambda text: print('\n' + text, flush=True), cancel=cancel)
            except KeyboardInterrupt:
                cancel.set()
                raise
            print(f"\n完成（{result['seconds']:.1f} 秒）：" + ('无变化' if result['status'] == 'unchanged' else f"新版本 {result['label']}"))
            if result['status'] == 'created':
                print(f"报告：{store.versions_dir / result['version'] / 'report.md'}")
            return 0
        if args.command == 'versions':
            versions = store.index()
            if not versions:
                print('归档里还没有版本。')
                return 0
            print(f"{'版本时间':<21}{'游戏资源版本':<14}{'资源数':>10}{'体积':>12}  {'新增':>7}{'修改':>7}{'删除':>7}{'改名':>7}  耗时")
            for meta in versions:
                c = meta.get('changes', {})
                print(f"{meta['label']:<21}{str(meta.get('game', {}).get('changeNumber') or '-'):<14}"
                      f"{meta['entries']:>10,}{_size(meta['bytes']):>12}  {c.get('added', 0):>7,}{c.get('modified', 0):>7,}"
                      f"{c.get('removed', 0):>7,}{c.get('renamed', 0):>7,}  {meta['durationSeconds']:.0f}s")
            print(f'\n归档目录：{root}（对象文件 {_size(store.disk_usage())}）')
            return 0
        if args.command == 'diff':
            target = resolve(store, args.target)
            base = resolve(store, args.base) if args.base else (resolve(store, target['parent']) if target.get('parent') else None)
            if not base:
                raise ValueError('目标是首个版本，请指定要比较的基准版本。')
            categories = set(base.get('categories', [])) & set(target.get('categories', []))
            changes = diff.compare(store.manifest(base['id']), store.manifest(target['id']), categories)
            summary = diff.summarize(changes)
            total = summary['total']
            print(f"{base['label']} → {target['label']}：共 {summary['changes']:,} 处变化"
                  f"（新增 {total['added']:,} · 修改 {total['modified']:,} · 删除 {total['removed']:,} · 改名 {total['renamed']:,}）")
            grouped = {}
            for change in changes:
                grouped.setdefault((change[2] or change[1])[1], []).append(change)
            for key, items in grouped.items():
                print(f"\n■ {LABELS.get(key, key)}（{len(items):,}）")
                for kind, old, new in items[:args.limit]:
                    path = f'{old[0]} → {new[0]}' if kind == 'renamed' else (new or old)[0]
                    print(f'  {diff.KIND_LABELS[kind]}  {path}')
                if len(items) > args.limit:
                    print(f'  ……另有 {len(items) - args.limit:,} 项')
            return 0
        if args.command == 'serve':
            from .server import serve
            server, url = serve(root, port=args.port, open_browser=not args.no_browser)
            print(f'资源浏览器：{url}  （Ctrl+C 结束）', flush=True)
            try:
                while True:
                    time.sleep(3600)
            except KeyboardInterrupt:
                server.shutdown()
            return 0
        if args.command == 'export':
            meta = resolve(store, args.version)
            folder = args.folder or store.library / meta['id']
            path, linked, removed = store.materialize(meta['id'], folder)
            print(f'已整理：{path}（链接 {linked:,}，移除 {removed:,}）')
            return 0
        if args.command == 'unexport':
            print(f'已删除分类目录 {args.folder}（{store.unmaterialize(args.folder):,} 个链接）。')
            return 0
        if args.command == 'delete':
            meta = resolve(store, args.version)
            store.delete_version(meta['id'])
            print(f"已删除版本 {meta['label']}；运行 archive gc 释放不再引用的文件。")
            return 0
        if args.command == 'gc':
            files, freed = store.gc()
            print(f'已清理 {files:,} 个文件，释放 {_size(freed)}。')
            return 0
    except Cancelled as error:
        print('\n' + str(error), file=sys.stderr)
        return 130
    except KeyboardInterrupt:
        print('\n已取消；已完成的部分会在下次解析时直接复用。', file=sys.stderr)
        return 130
    except (ValueError, RuntimeError, OSError) as error:
        print('错误：' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
