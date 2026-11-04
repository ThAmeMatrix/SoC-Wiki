"""Windows interface for the local client tools.

* 资源归档 – extract every client resource into a versioned archive, with live
  progress; a new version is recorded only when something changed.
* 版本库   – every version with its changes; browse one or compare any two in
  the visual browser, export organised folders, remove old versions.
* Wiki 更新 – pull characters, skills, traits and weapons into this wiki.

Packaged as ``SoCwiki本地更新.exe`` by ``scripts/build_client_updater.py``.
"""
from __future__ import annotations

import argparse
import io
import json
import multiprocessing
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import tkinter as tk  # noqa: E402
from tkinter import filedialog, messagebox, scrolledtext, ttk  # noqa: E402

from socdecode import cli  # noqa: E402
from socdecode.archive.catalog import CATEGORIES, KEYS  # noqa: E402
from socdecode.archive.scan import STAGES, Cancelled, default_workers, locate  # noqa: E402
from socdecode.archive.store import Store  # noqa: E402
from socdecode.config import OUTPUT, ROOT, archive_path, game_path, last_backup, load, save  # noqa: E402
from socdecode.client import game_root  # noqa: E402
from socdecode.wiki import plan_update  # noqa: E402
from socdecode.transaction import apply  # noqa: E402
from socdecode.rebuild import run as rebuild_wiki  # noqa: E402


class QueueWriter(io.TextIOBase):
    def __init__(self, sink):
        self.sink = sink

    def write(self, text):
        if text:
            self.sink(text)
        return len(text)

    def flush(self):
        return None


def size_text(value) -> str:
    value = float(value or 0)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if abs(value) < 1024 or unit == 'TB':
            return f'{value:.0f} {unit}' if unit == 'B' else f'{value:.1f} {unit}'
        value /= 1024
    return f'{value:.1f} TB'


def clock(seconds) -> str:
    if seconds is None:
        return '--:--'
    seconds = int(seconds)
    return f'{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}' if seconds >= 3600 else f'{seconds // 60:02d}:{seconds % 60:02d}'


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('SoCwiki 本地更新与资源档案')
        self.geometry('1120x780')
        self.minsize(940, 640)
        self.messages = queue.Queue()
        self.busy = None
        self.busy_since = None
        self.last_log = None
        self.cancel = None
        self.server = None
        self.server_root = None
        settings = load()
        self.game = tk.StringVar(value=str(game_path()))
        self.archive = tk.StringVar(value=str(archive_path()))
        self.workers = tk.IntVar(value=int(settings.get('workers') or default_workers()))
        self.organise = tk.BooleanVar(value=settings.get('organise', True))
        chosen = set(settings.get('categories') or KEYS)
        self.categories = {key: tk.BooleanVar(value=key in chosen) for key in KEYS}
        self.mode = tk.StringVar(value='diff')
        self.rebuild = tk.BooleanVar(value=True)
        self.force_extract = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value='就绪')
        self.pulls = {}          # fingerprint -> (label, game, snapshot)
        self.pull_items = []     # [(fingerprint, (label, game))] sorted by time
        self.pull_label = tk.StringVar(value='')
        self.build()
        self.after(100, self.pump)
        self.after(300, self.refresh_versions)
        self.after(350, self.safe_refresh_pulls)

    # -- layout ---------------------------------------------------------------
    def build(self):
        style = ttk.Style(self)
        try:
            style.theme_use('vista')
        except tk.TclError:
            pass
        style.configure('Stage.TLabel', foreground='#7a8790')
        style.configure('Now.TLabel', foreground='#b07a12', font=('Microsoft YaHei UI', 9, 'bold'))
        style.configure('Done.TLabel', foreground='#2f8a4a')
        style.configure('Head.TLabel', font=('Microsoft YaHei UI', 11, 'bold'))
        paths = ttk.Frame(self, padding=(12, 10, 12, 4))
        paths.pack(fill='x')
        self.path_row(paths, 0, '客户端目录', self.game, self.choose_game, [('自动识别', self.detect)])
        self.path_row(paths, 1, '归档目录', self.archive, self.choose_archive, [('打开', lambda: self.open_folder(self.archive.get()))])
        paths.columnconfigure(1, weight=1)
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill='both', expand=True, padx=12, pady=(4, 0))
        self.archive_tab = ttk.Frame(self.tabs, padding=10)
        self.versions_tab = ttk.Frame(self.tabs, padding=10)
        self.wiki_tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(self.archive_tab, text='  资源归档  ')
        self.tabs.add(self.versions_tab, text='  版本库  ')
        self.tabs.add(self.wiki_tab, text='  Wiki 更新  ')
        self.build_archive()
        self.build_versions()
        self.build_wiki()
        ttk.Label(self, textvariable=self.status, padding=(14, 4)).pack(fill='x')

    def path_row(self, parent, row, label, variable, choose, extra):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky='w', pady=2)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky='ew', padx=6, pady=2)
        ttk.Button(parent, text='选择…', command=choose).grid(row=row, column=2, pady=2)
        for index, (text, action) in enumerate(extra):
            ttk.Button(parent, text=text, command=action).grid(row=row, column=3 + index, padx=(6, 0), pady=2)

    def build_archive(self):
        tab = self.archive_tab
        ttk.Label(tab, text='解析客户端里的全部资源，按分类保存为可直接查看的文件；与上一版本不同时以当前时间记录一个新版本，'
                            '并自动生成差分。未变化的文件直接复用，中途取消也会保留已完成的部分。',
                  wraplength=1040, foreground='#4a5761').pack(anchor='w')
        options = ttk.Frame(tab)
        options.pack(fill='x', pady=(8, 4))
        ttk.Label(options, text='并行进程').pack(side='left')
        ttk.Spinbox(options, from_=1, to=max(2, os.cpu_count() or 4), width=4, textvariable=self.workers).pack(side='left', padx=(4, 16))
        ttk.Checkbutton(options, text='解析后刷新分类目录（硬链接，不额外占用空间）', variable=self.organise).pack(side='left')
        scope = ttk.LabelFrame(tab, text='解析范围', padding=(10, 6))
        scope.pack(fill='x', pady=4)
        for index, (key, label) in enumerate(CATEGORIES):
            ttk.Checkbutton(scope, text=label, variable=self.categories[key]).grid(row=index // 6, column=index % 6, sticky='w', padx=(0, 18), pady=1)
        quick = ttk.Frame(scope)
        quick.grid(row=0, column=6, rowspan=2, sticky='e', padx=(20, 0))
        ttk.Button(quick, text='全选', command=lambda: [v.set(True) for v in self.categories.values()]).pack(side='left')
        ttk.Button(quick, text='仅配置表与图片', command=lambda: [v.set(k in ('table', 'image', 'sprite')) for k, v in self.categories.items()]).pack(side='left', padx=(6, 0))
        ttk.Label(scope, text='账号记录、启动器数据库、战斗回放（assets/Report）与玩家偏好设置始终不读取。',
                  foreground='#7a8790').grid(row=2, column=0, columnspan=7, sticky='w', pady=(4, 0))
        buttons = ttk.Frame(tab)
        buttons.pack(fill='x', pady=(8, 6))
        self.scan_button = ttk.Button(buttons, text='开始解析', command=self.start_scan)
        self.scan_button.pack(side='left')
        self.cancel_button = ttk.Button(buttons, text='取消', command=self.cancel_scan, state='disabled')
        self.cancel_button.pack(side='left', padx=6)
        ttk.Button(buttons, text='打开资源浏览器', command=lambda: self.open_viewer('')).pack(side='left', padx=(18, 0))
        ttk.Button(buttons, text='查看最新差分', command=self.latest_diff).pack(side='left', padx=6)
        ttk.Button(buttons, text='打开分类目录', command=lambda: self.open_folder(Path(self.archive.get()) / 'library' / '当前版本')).pack(side='left')
        progress = ttk.LabelFrame(tab, text='进度', padding=(10, 6))
        progress.pack(fill='x', pady=4)
        steps = ttk.Frame(progress)
        steps.pack(fill='x')
        self.stage_labels = {}
        for index, (key, label) in enumerate(STAGES):
            item = ttk.Label(steps, text=f'○ {index + 1}. {label}', style='Stage.TLabel')
            item.pack(side='left', padx=(0, 18))
            self.stage_labels[key] = item
        self.bar = ttk.Progressbar(progress, maximum=1000)
        self.bar.pack(fill='x', pady=(6, 4))
        self.line1 = tk.StringVar(value='尚未开始')
        self.line2 = tk.StringVar(value='')
        ttk.Label(progress, textvariable=self.line1, style='Head.TLabel').pack(anchor='w')
        ttk.Label(progress, textvariable=self.line2, foreground='#4a5761').pack(anchor='w')
        self.archive_log = self.log_box(tab, 12)

    def build_versions(self):
        tab = self.versions_tab
        head = ttk.Frame(tab)
        head.pack(fill='x')
        self.usage = tk.StringVar(value='')
        ttk.Label(head, text='每个版本以解析时间命名；选中一个浏览，选中两个比较（任意两个都可以）。', foreground='#4a5761').pack(side='left')
        ttk.Label(head, textvariable=self.usage, foreground='#7a8790').pack(side='right')
        columns = (('label', '解析时间', 150), ('game', '游戏资源版本', 100), ('entries', '资源数', 90), ('size', '体积', 90),
                   ('added', '新增', 70), ('modified', '修改', 70), ('removed', '删除', 70), ('renamed', '改名', 60),
                   ('sources', '客户端文件变化', 110), ('time', '耗时', 70))
        frame = ttk.Frame(tab)
        frame.pack(fill='both', expand=True, pady=6)
        self.tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show='headings', selectmode='extended', height=12)
        for key, text, width in columns:
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, anchor='w' if key == 'label' else 'e', stretch=key == 'label')
        scroll = ttk.Scrollbar(frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side='left', fill='both', expand=True)
        scroll.pack(side='left', fill='y')
        self.tree.bind('<<TreeviewSelect>>', lambda _: self.show_version())
        self.tree.bind('<Double-1>', lambda _: self.browse_selected())
        buttons = ttk.Frame(tab)
        buttons.pack(fill='x')
        for text, action in (('刷新', self.refresh_versions), ('浏览所选版本', self.browse_selected),
                             ('与上一版本比较', self.compare_previous), ('比较所选两个版本', self.compare_selected),
                             ('打开版本报告', self.open_report), ('导出分类目录', self.export_selected),
                             ('删除所选版本', self.delete_selected), ('清理未引用文件', self.collect)):
            ttk.Button(buttons, text=text, command=action).pack(side='left', padx=(0, 6))
        self.version_info = scrolledtext.ScrolledText(tab, height=9, wrap='word', font=('Microsoft YaHei UI', 9))
        self.version_info.pack(fill='both', expand=False, pady=(8, 0))
        self.version_info.configure(state='disabled')

    def build_wiki(self):
        tab = self.wiki_tab
        ttk.Label(tab, text='纯本地客户端解析，无需联网 wiki：从本机客户端读取角色、技能、个性与专武，生成离线资料馆的 data/ 与 assets/。所有页面与一图流均由客户端数据构建，BWIKI 专有装饰（标题 Logo、稀有度/职业/阵营徽章、属性图标、塔罗/刻印原图、自定义字体）在缺失时自动留空，不影响资料馆使用。写入前自动备份，可一键回滚。',
                  foreground='#4a5761', wraplength=1040).pack(anchor='w')
        ttk.Label(tab, text=f'资料馆：{ROOT}', foreground='#7a8790').pack(anchor='w', pady=(2, 6))
        modes = ttk.LabelFrame(tab, text='更新方式', padding=8)
        modes.pack(fill='x', pady=(4, 6))
        ttk.Radiobutton(modes, text='差量更新（只补缺失与空白字段；手动修改与署名保留）', value='diff', variable=self.mode).pack(anchor='w')
        ttk.Radiobutton(modes, text='全覆盖（全部已匹配角色按客户端重算并覆盖；攻略、署名与备份保留）', value='full', variable=self.mode).pack(anchor='w')
        ttk.Checkbutton(tab, text='更新后重建索引与一图流数据（推荐）', variable=self.rebuild).pack(anchor='w', pady=(0, 6))
        ttk.Checkbutton(tab, text='强制重新解析客户端（忽略已缓存的配置表）', variable=self.force_extract).pack(anchor='w', pady=(0, 8))
        select = ttk.LabelFrame(tab, text='解析出的版本（一键拉取后在此选择；已拉取的版本无需重复拉取）', padding=8)
        select.pack(fill='x', pady=(4, 6))
        self.pull_choice = ttk.Combobox(select, textvariable=self.pull_label, state='readonly', width=72)
        self.pull_choice.pack(side='left', padx=(0, 6))
        ttk.Button(select, text='刷新列表', command=self.safe_refresh_pulls).pack(side='left')
        buttons = ttk.Frame(tab)
        buttons.pack(fill='x')
        self.wiki_buttons = []
        for text, action in (('检查新角色', self.check), ('补充新角色', self.add_new), ('预览差异', self.preview),
                             ('一键拉取', self.pull), ('更新', self.update_wiki), ('回滚上次更新', self.rollback)):
            button = ttk.Button(buttons, text=text, command=action)
            button.pack(side='left', padx=(0, 6))
            self.wiki_buttons.append(button)
        prog = ttk.LabelFrame(tab, text='当前进度', padding=(10, 6))
        prog.pack(fill='x', pady=(4, 6))
        self.wiki_step = tk.StringVar(value='就绪')
        self.wiki_elapsed = tk.StringVar(value='')
        ttk.Label(prog, textvariable=self.wiki_step, style='Now.TLabel', wraplength=1040).pack(anchor='w')
        self.wiki_bar = ttk.Progressbar(prog, maximum=1000, mode='determinate')
        self.wiki_bar.pack(fill='x', pady=(4, 0))
        foot = ttk.Frame(prog)
        foot.pack(fill='x', pady=(4, 0))
        ttk.Label(foot, textvariable=self.wiki_elapsed, foreground='#4a5761').pack(side='left')
        ttk.Button(foot, text='打开日志目录', command=lambda: self.open_folder(OUTPUT / 'logs')).pack(side='right')
        ttk.Button(foot, text='打开本次日志', command=self.open_last_log).pack(side='right', padx=(0, 6))
        self.wiki_log = self.log_box(tab, 16)

    def log_box(self, parent, height):
        box = scrolledtext.ScrolledText(parent, height=height, wrap='word', font=('Consolas', 9))
        box.pack(fill='both', expand=True, pady=(8, 0))
        box.configure(state='disabled')
        return box

    # -- plumbing ---------------------------------------------------------------
    def append(self, box, text):
        box.configure(state='normal')
        box.insert('end', text)
        box.see('end')
        box.configure(state='disabled')

    def pump(self):
        try:
            for _ in range(400):
                kind, *payload = self.messages.get_nowait()
                if kind == 'log':
                    self.append(*payload)
                elif kind == 'progress':
                    self.show_progress(payload[0])
                elif kind == 'wikistep':
                    self.wiki_step.set(payload[0])
                    self.set_bar(None if len(payload) > 1 and payload[1] else 0, 1)
                elif kind == 'wikiprog':
                    text, done, total = payload
                    self.wiki_step.set(text)
                    self.set_bar(done, total)
                elif kind == 'call':
                    payload[0]()
        except queue.Empty:
            pass
        if self.busy and self.busy_since:
            self.wiki_elapsed.set(f'{self.busy} · 已用时 {clock(time.monotonic() - self.busy_since)}')
        self.after(100, self.pump)

    def set_bar(self, done, total):
        """done=None: indeterminate (busy, unknown length); otherwise determinate."""
        if done is None:
            if str(self.wiki_bar.cget('mode')) != 'indeterminate':
                self.wiki_bar.configure(mode='indeterminate')
                self.wiki_bar.start(25)
            return
        self.wiki_bar.stop()
        self.wiki_bar.configure(mode='determinate', value=int(done / total * 1000) if total else 0)

    def later(self, fn):
        self.messages.put(('call', fn))

    def log_to(self, box):
        return lambda text: self.messages.put(('log', box, text if text.endswith('\n') else text + '\n'))

    def remember(self):
        save(game=self.game.get(), archive=self.archive.get(), workers=int(self.workers.get() or default_workers()),
             organise=bool(self.organise.get()), categories=[k for k, v in self.categories.items() if v.get()])

    def choose_game(self):
        folder = filedialog.askdirectory(initialdir=self.game.get() or str(ROOT), title='选择游戏客户端目录')
        if folder:
            self.game.set(folder)
            self.remember()

    def choose_archive(self):
        folder = filedialog.askdirectory(initialdir=self.archive.get() or str(OUTPUT), title='选择资源归档目录')
        if folder:
            self.archive.set(folder)
            self.remember()
            self.refresh_versions()

    def detect(self):
        for base in (self.game.get(), r'C:\Game\SwordofConvallaria\SoCLauncher', r'D:\Game\SwordofConvallaria\SoCLauncher'):
            if not base:
                continue
            try:
                root = locate(base)
            except ValueError:
                continue
            self.game.set(str(root))
            self.remember()
            self.status.set(f'已识别客户端：{root}')
            return
        messagebox.showwarning('未找到客户端', '没有在常见位置找到游戏客户端，请手动选择目录。')

    def open_folder(self, folder):
        folder = Path(folder)
        if not folder.exists():
            messagebox.showinfo('目录不存在', f'{folder}\n\n还没有生成，先完成一次解析。')
            return
        if os.name == 'nt':
            subprocess.Popen(['explorer', str(folder)])

    def thread(self, label, job, on_done=None, box=None):
        if self.busy:
            messagebox.showinfo('请稍候', f'「{self.busy}」还在进行中。')
            return False
        self.busy = label
        self.busy_since = time.monotonic()
        self.status.set(label + '…')
        box = box or self.archive_log

        def target():
            result = None
            try:
                result = job()
            except Cancelled as error:
                self.messages.put(('log', box, f'\n{error}\n'))
            except SystemExit:
                pass
            except BaseException:
                self.messages.put(('log', box, '\n' + traceback.format_exc()))
            finally:
                def finish():
                    if self.busy_since:
                        self.wiki_elapsed.set(f'{self.busy} 结束 · 用时 {clock(time.monotonic() - self.busy_since)}')
                    self.busy = None
                    self.busy_since = None
                    self.status.set('就绪')
                    if on_done:
                        on_done(result)
                self.later(finish)

        threading.Thread(target=target, daemon=True).start()
        return True

    # -- archive ------------------------------------------------------------------
    def start_scan(self):
        categories = [k for k, v in self.categories.items() if v.get()]
        if not categories:
            messagebox.showwarning('没有选择分类', '至少选择一个要解析的分类。')
            return
        self.remember()
        self.cancel = threading.Event()
        for item in self.stage_labels.values():
            item.configure(style='Stage.TLabel', text='○' + item.cget('text')[1:])
        self.bar.configure(value=0)
        log = self.log_to(self.archive_log)
        log(f"—— {time.strftime('%Y-%m-%d %H:%M:%S')} 开始解析 ——")
        game, archive, workers = self.game.get(), self.archive.get(), int(self.workers.get() or default_workers())
        organise = bool(self.organise.get())

        def job():
            from socdecode.archive.scan import scan
            return scan(game, archive, workers=workers, categories=categories, organise=organise, log=log,
                        progress=lambda event: self.messages.put(('progress', event)), cancel=self.cancel)

        def done(result):
            self.scan_button.configure(state='normal')
            self.cancel_button.configure(state='disabled')
            self.refresh_versions()
            if not result:
                self.line1.set('已停止')
                return
            for item in self.stage_labels.values():
                item.configure(style='Done.TLabel', text='✓' + item.cget('text')[1:])
            self.bar.configure(value=1000)
            if result['status'] == 'unchanged':
                self.line1.set(f"与上一版本一致（{result['label']}），未生成新版本 · 用时 {clock(result['seconds'])}")
                return
            meta = result['meta']
            changes = meta.get('changes', {})
            self.line1.set(f"已生成版本 {meta['label']} · {meta['entries']:,} 项资源 · 用时 {clock(result['seconds'])}")
            if meta.get('parent'):
                self.line2.set(f"相比上一版本：新增 {changes.get('added', 0):,} · 修改 {changes.get('modified', 0):,} · "
                               f"删除 {changes.get('removed', 0):,} · 改名 {changes.get('renamed', 0):,}")
                if changes.get('total') and messagebox.askyesno('发现新内容', f"本次解析与上一版本相比有 {changes['total']:,} 处变化。\n\n现在打开差分查看吗？"):
                    self.open_viewer(f"a={meta['parent']}&b={meta['id']}")
            else:
                self.line2.set('首个版本已记录；之后每次解析出不同内容都会生成新版本，可与任意版本比较。')

        if self.thread('解析资源', job, done):
            self.scan_button.configure(state='disabled')
            self.cancel_button.configure(state='normal')

    def cancel_scan(self):
        if self.cancel:
            self.cancel.set()
            self.status.set('正在取消，等待进行中的文件完成…')

    def show_progress(self, event):
        current = event['stage']
        reached = True
        for key, item in self.stage_labels.items():
            text = item.cget('text')[1:]
            if key == current:
                item.configure(style='Now.TLabel', text='●' + text)
                reached = False
            elif reached:
                item.configure(style='Done.TLabel', text='✓' + text)
            else:
                item.configure(style='Stage.TLabel', text='○' + text)
        total, done = event['bytesTotal'] or event['total'], event['bytesDone'] if event['bytesTotal'] else event['done']
        self.bar.configure(value=int(done / total * 1000) if total else 0)
        parts = [f"第 {event['step']}/{event['steps']} 步 · {event['label']}"]
        if event['total']:
            parts.append(f"{event['done']:,} / {event['total']:,}")
        if event['bytesTotal']:
            parts.append(f"{size_text(event['bytesDone'])} / {size_text(event['bytesTotal'])}")
        if event['rate']:
            parts.append(f"{size_text(event['rate'])}/s")
        if event['eta'] is not None:
            parts.append('剩余约 ' + clock(event['eta']))
        self.line1.set(' · '.join(parts))
        stats = event['stats']
        detail = [f"已用时 {clock(event['elapsed'])}"]
        if stats:
            detail.append(f"新写入 {stats.get('newBlobs', 0):,} 个文件（{size_text(stats.get('writtenBytes'))}）")
            detail.append(f"复用 {stats.get('reused', 0):,} · 缓存 {stats.get('cached', 0):,}")
            if stats.get('errors'):
                detail.append(f"未能解析 {stats['errors']:,}")
        if event.get('detail'):
            detail.append(event['detail'])
        self.line2.set(' · '.join(detail))

    # -- versions -----------------------------------------------------------------
    def store(self):
        return Store(self.archive.get())

    def refresh_versions(self):
        versions = self.store().index()
        self.tree.delete(*self.tree.get_children())
        for meta in reversed(versions):
            c, s = meta.get('changes', {}), meta.get('sourceChanges', {})
            first = not meta.get('parent')
            self.tree.insert('', 'end', iid=meta['id'], values=(
                meta['label'], meta.get('game', {}).get('changeNumber') or '-', f"{meta['entries']:,}", size_text(meta['bytes']),
                '首个版本' if first else f"{c.get('added', 0):,}", '' if first else f"{c.get('modified', 0):,}",
                '' if first else f"{c.get('removed', 0):,}", '' if first else f"{c.get('renamed', 0):,}",
                '' if first else f"{sum(s.values()):,}", clock(meta.get('durationSeconds'))))
        self.usage.set(f'{len(versions)} 个版本')
        root = self.archive.get()

        def measure():
            used = Store(root).disk_usage()
            self.later(lambda: self.usage.set(f'{len(versions)} 个版本 · 归档占用 {size_text(used)}'))
        threading.Thread(target=measure, daemon=True).start()

    def selected(self):
        versions = {v['id']: v for v in self.store().index()}
        return [versions[i] for i in sorted(self.tree.selection()) if i in versions]

    def show_version(self):
        chosen = self.selected()
        if not chosen:
            return
        meta = chosen[-1]
        store = self.store()
        changes = store.changes(meta['id']) or {}
        lines = [f"版本 {meta['label']}（{meta['id']}）· 游戏资源版本 {meta.get('game', {}).get('changeNumber') or '未知'}",
                 f"资源 {meta['entries']:,} 项 · {size_text(meta['bytes'])} · 客户端文件 {meta.get('sources', 0):,} 个 · 解析用时 {clock(meta.get('durationSeconds'))}",
                 '分类：' + '，'.join(f"{dict(CATEGORIES).get(k, k)} {v['n']:,}" for k, v in meta.get('counts', {}).items())]
        summary = changes.get('summary') or {}
        if meta.get('parent') and summary:
            lines.append('')
            lines.append(f"相比上一版本 {meta['parent']}：")
            for key, value in summary.get('categories', {}).items():
                counts = value['counts']
                lines.append(f"  {dict(CATEGORIES).get(key, key)}：新增 {counts['added']:,} · 修改 {counts['modified']:,} · "
                             f"删除 {counts['removed']:,} · 改名 {counts['renamed']:,}")
        if changes.get('errors'):
            lines.append(f"\n未能解析的对象 {len(changes['errors'])} 个，例如：{changes['errors'][0]}")
        if len(chosen) == 2:
            lines.insert(0, f"已选两个版本：{chosen[0]['label']} 与 {chosen[1]['label']}，点「比较所选两个版本」查看差分。\n")
        self.version_info.configure(state='normal')
        self.version_info.delete('1.0', 'end')
        self.version_info.insert('end', '\n'.join(lines))
        self.version_info.configure(state='disabled')

    def open_viewer(self, query):
        root = self.archive.get()
        if not self.store().index():
            messagebox.showinfo('还没有版本', '先在「资源归档」里完成一次解析。')
            return
        try:
            if self.server is None or self.server_root != root:
                from socdecode.archive.server import serve
                if self.server:
                    self.server.shutdown()
                self.server, self.url = serve(root, open_browser=False)
                self.server_root = root
            webbrowser.open(self.url + ('#' + query if query else ''))
            self.status.set(f'资源浏览器：{self.url}')
        except OSError as error:
            messagebox.showerror('无法启动资源浏览器', str(error))

    def latest_diff(self):
        latest = self.store().latest()
        if latest and latest.get('parent'):
            self.open_viewer(f"a={latest['parent']}&b={latest['id']}")
        elif latest:
            messagebox.showinfo('只有一个版本', '再次解析出不同内容后会生成新版本，届时即可比较。')
            self.open_viewer(f"v={latest['id']}")
        else:
            messagebox.showinfo('还没有版本', '先完成一次解析。')

    def browse_selected(self):
        chosen = self.selected()
        if chosen:
            self.open_viewer(f"v={chosen[-1]['id']}")

    def compare_previous(self):
        chosen = self.selected()
        if not chosen:
            return
        meta = chosen[-1]
        if not meta.get('parent'):
            messagebox.showinfo('首个版本', '首个版本没有上一版本，请再选一个版本比较。')
            return
        self.open_viewer(f"a={meta['parent']}&b={meta['id']}")

    def compare_selected(self):
        chosen = self.selected()
        if len(chosen) != 2:
            messagebox.showinfo('选择两个版本', '按住 Ctrl 选中任意两个版本后再比较。')
            return
        older, newer = sorted(chosen, key=lambda v: v['id'])
        self.open_viewer(f"a={older['id']}&b={newer['id']}")

    def open_report(self):
        chosen = self.selected()
        if chosen and os.name == 'nt':
            report = self.store().versions_dir / chosen[-1]['id'] / 'report.md'
            if report.is_file():
                os.startfile(report)

    def export_selected(self):
        chosen = self.selected()
        if not chosen:
            return
        meta = chosen[-1]
        store = self.store()
        log = self.log_to(self.archive_log)

        def job():
            folder, linked, removed = store.materialize(meta['id'], store.library / meta['id'])
            log(f"已整理版本 {meta['label']}：{folder}（链接 {linked:,}）")
            return folder
        self.thread('导出分类目录', job, lambda folder: folder and self.open_folder(folder))

    def delete_selected(self):
        chosen = self.selected()
        if not chosen or not messagebox.askyesno('删除版本', '删除所选的 %d 个版本记录？\n资源文件要在「清理未引用文件」后才会释放。' % len(chosen)):
            return
        store = self.store()
        for meta in chosen:
            store.delete_version(meta['id'])
        self.refresh_versions()

    def collect(self):
        store = self.store()
        log = self.log_to(self.archive_log)

        def job():
            files, freed = store.gc()
            log(f'已清理 {files:,} 个不再被任何版本引用的文件，释放 {size_text(freed)}。')
        self.thread('清理未引用文件', job, lambda _: self.refresh_versions())

    # -- wiki --------------------------------------------------------------------------
    def wiki_job(self, label, job, context=()):
        """Run ``job`` on a worker; every line goes to the GUI log and to output/logs/<time>-<label>.log."""
        if self.busy:
            messagebox.showinfo('请稍候', f'「{self.busy}」还在进行中，进度见下方日志。')
            return
        logs = OUTPUT / 'logs'
        logs.mkdir(parents=True, exist_ok=True)
        path = logs / f"{time.strftime('%Y%m%d-%H%M%S')}-{label}.log"
        self.last_log = path
        stream = open(path, 'a', encoding='utf-8', buffering=1)

        def sink(text):
            self.messages.put(('log', self.wiki_log, text))
            try:
                stream.write(text)
            except (OSError, ValueError):
                pass
        sink(f"\n—— {time.strftime('%Y-%m-%d %H:%M:%S')} 开始「{label}」 ——\n日志文件：{path}\n")
        for line in context:
            sink(f'  {line}\n')
        self.wiki_step.set(f'「{label}」已开始…')
        self.set_bar(None, 1)
        started = time.monotonic()

        def wrapped():
            writer = QueueWriter(sink)
            original = sys.stdout, sys.stderr
            sys.stdout = sys.stderr = writer
            try:
                job()
                print(f"[{time.strftime('%H:%M:%S')}] 「{label}」完成，用时 {clock(time.monotonic() - started)}。")
            except BaseException as error:
                print(f"[{time.strftime('%H:%M:%S')}] 「{label}」失败：{type(error).__name__}：{error}")
                print(traceback.format_exc())
                self.messages.put(('wikistep', f'出错：{type(error).__name__}：{error}（详见日志）', False))
            finally:
                sys.stdout, sys.stderr = original
                try:
                    stream.close()
                except OSError:
                    pass
        for button in self.wiki_buttons:
            button.configure(state='disabled')
        if not self.thread(label, wrapped, lambda _: [b.configure(state='normal') for b in self.wiki_buttons], self.wiki_log):
            stream.close()
            for button in self.wiki_buttons:
                button.configure(state='normal')

    def open_last_log(self):
        if self.last_log and Path(self.last_log).is_file() and os.name == 'nt':
            os.startfile(self.last_log)
        else:
            self.open_folder(OUTPUT / 'logs')

    def progress(self, message, done=None, total=None):
        """Progress callback for worker code: updates the label/bar and logs a timestamped line."""
        self.messages.put(('wikiprog', message, done, total))
        print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)

    def arguments(self, *extra):
        return [*extra, '--game', self.game.get(), '--output', str(OUTPUT), '--wiki', str(ROOT)]

    def extract_args(self):
        argv = ['extract', '--game', self.game.get(), '--output', str(OUTPUT)]
        if self.force_extract.get():
            argv.append('--force-extract')
        return cli.parser().parse_args(argv)

    def do_extract(self):
        """Pull (extract) client configuration; returns (game, snapshot)."""
        return cli.extract(self.extract_args(), progress=lambda msg: self.progress(msg))

    def set_pulled(self, game, snapshot):
        fp = snapshot['client']['fingerprint']
        label = f"{snapshot['extractedAt'][:19]} · {fp[:12]} · {len(snapshot['characters'])} 角色"
        self.pulls[fp] = (label, str(game), snapshot)
        (OUTPUT / 'pulls').mkdir(parents=True, exist_ok=True)
        (OUTPUT / 'pulls' / (fp + '.json')).write_text(
            json.dumps(snapshot, ensure_ascii=False, separators=(',', ':')), 'utf8')
        self.later(lambda: self.safe_refresh_pulls(select=fp))

    def safe_refresh_pulls(self, select=None):
        try:
            self.refresh_pulls(select)
            self.append(self.wiki_log, f"已载入 {len(self.pull_items)} 个可用版本。\n")
        except Exception:
            self.append(self.wiki_log, '读取已拉取版本失败：\n' + traceback.format_exc())

    def refresh_pulls(self, select=None):
        try:
            default_game = str(game_root(Path(self.game.get())))
        except (ValueError, OSError):
            default_game = str(self.game.get())
        found = {}
        pulls_dir = OUTPUT / 'pulls'
        candidates = sorted(pulls_dir.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True) \
            if pulls_dir.is_dir() else []
        cd = OUTPUT / 'client-data.json'
        if cd.is_file():
            candidates.insert(0, cd)
        for f in candidates:
            try:
                snap = json.loads(f.read_text('utf8'))
            except (OSError, ValueError):
                continue
            fp = snap.get('client', {}).get('fingerprint') or f.stem
            if fp in found:
                continue
            game = str(snap.get('client', {}).get('game') or default_game)
            tag = '（库内快照）' if f is cd else '（已保存）'
            label = f"{snap['extractedAt'][:19]} · {fp[:12]} · {len(snap['characters'])} 角色{tag}"
            found[fp] = (label, game, snap)
        for fp, (label, game, snap) in self.pulls.items():
            found.setdefault(fp, (label, game, snap))
        ordered = sorted(found.items(), key=lambda kv: kv[1][0], reverse=True)
        self.pulls = {fp: v for fp, v in ordered}
        self.pull_items = ordered
        self.pull_choice['values'] = [v[0] for _, v in ordered]
        if select:
            for index, (fp, _) in enumerate(ordered):
                if fp == select or fp.startswith(select):
                    self.pull_choice.current(index)
                    break
        elif ordered and self.pull_choice.current() < 0:
            self.pull_choice.current(0)

    def current_pull(self):
        # Main-thread only: reads the version selector and resolves it to (game, snapshot).
        index = self.pull_choice.current()
        if index < 0 or index >= len(self.pull_items):
            return None
        fp = self.pull_items[index][0]
        if fp in self.pulls:
            _, game, snapshot = self.pulls[fp]
            return game, snapshot
        return self.load_pull(fp)

    def load_pull(self, fp):
        path = OUTPUT / 'pulls' / (fp + '.json')
        if not path.is_file():
            return None
        snap = json.loads(path.read_text('utf8'))
        game = str(snap.get('client', {}).get('game') or self.game.get())
        self.pulls[fp] = (f"{snap['extractedAt'][:19]} · {fp[:12]} · {len(snap['characters'])} 角色 (磁盘)", game, snap)
        return game, snap

    def step(self, text, busy=True):
        self.messages.put(('wikistep', text, busy))
        print(f"[{time.strftime('%H:%M:%S')}] {text}", flush=True)

    def context(self, label, chosen=None):
        index = self.pull_choice.current()
        version = self.pull_items[index][1][0] if 0 <= index < len(self.pull_items) else '（未选择，将现场解析客户端）'
        lines = [f'版本：{version}', f'资料馆：{ROOT}', f'客户端：{self.game.get()}',
                 f"方式：{'全覆盖' if self.mode.get() == 'full' else '差量更新'} · 重建索引：{'是' if self.rebuild.get() else '否'}"]
        if chosen:
            lines.append(f'解析用客户端目录：{chosen[0]}')
        return lines

    def pull(self):
        def job():
            self.step('正在读取客户端配置表…')
            game, snapshot = self.do_extract()
            self.set_pulled(game, snapshot)
            self.step(f"拉取完成：{len(snapshot['characters'])} 个角色 · "
                       f"{len(snapshot['skills'])} 条技能 · {len(snapshot['statuses'])} 个关联词条", False)
        self.wiki_job('一键拉取', job)

    def check(self):
        chosen = self.current_pull()
        def job():
            if chosen:
                game, snapshot = chosen
            else:
                self.step('正在读取客户端配置表…')
                game, snapshot = self.do_extract()
                self.set_pulled(game, snapshot)
            self.step('正在比对已收录角色…')
            have = cli.wiki_names(ROOT)
            counts = {}
            for char in snapshot['characters']:
                counts[char['name']] = counts.get(char['name'], 0) + 1
            missing = [c for c in snapshot['characters'] if c['name'] not in have]
            print(f"客户端共 {len(snapshot['characters'])} 个成长配置完整的角色；"
                  f"资料馆已收录 {len(have)} 个；客户端有而资料馆缺 {len(missing)} 个。")
            for char in sorted(missing, key=lambda c: c['name']):
                print(f"  缺：{char['name']}（{'同名重复' if counts[char['name']] > 1 else char['rarity']}）")
            self.step(f"检查完成：资料馆缺 {len(missing)} 个客户端角色。", False)
        self.wiki_job('检查新角色', job)

    def add_new(self):
        """Import the characters the client has and the wiki does not.

        「检查新角色」only lists them; this runs the same one-shot import the
        ``add`` command performs, so a new character never needs the console.
        """
        chosen = self.current_pull()
        def job():
            if chosen:
                game, snapshot = chosen
            else:
                self.step('正在读取客户端配置表…')
                game, snapshot = self.do_extract()
                self.set_pulled(game, snapshot)
            self.step('正在比对已收录角色…')
            have = cli.wiki_names(ROOT)
            counts = {}
            for char in snapshot['characters']:
                counts[char['name']] = counts.get(char['name'], 0) + 1
            missing = [c['name'] for c in snapshot['characters']
                       if c['name'] not in have and c.get('enabled', True)]
            names = [name for name in dict.fromkeys(missing) if counts[name] == 1]
            ambiguous = [name for name in dict.fromkeys(missing) if counts[name] > 1]
            for name in ambiguous:
                print(f'  跳过：{name}（客户端有多个同名角色，需先用命令行指定完整名称）')
            if not names:
                self.step('资料馆已收录客户端全部角色，没有需要补录的新角色。', False)
                return
            upcoming = [c['name'] for c in snapshot['characters']
                        if c['name'] in names and not c.get('available')]
            print(f'待补录 {len(names)} 个角色：' + '、'.join(names))
            for name in upcoming:
                print(f'  尚未开放（已按客户端配置收录）：{name}')
            args = argparse.Namespace(character=names, wiki=ROOT, output=OUTPUT,
                                      refresh=self.mode.get() == 'full', sprite_variant='base',
                                      dry_run=False, no_rebuild=not self.rebuild.get())
            self.step(f'正在导入 {len(names)} 个新角色（先备份，耗时数分钟）…')
            cli.add_character(args, Path(game), snapshot)
            self.step(f'补录完成：{len(names)} 个新角色已写入资料馆。', False)
        self.wiki_job('补充新角色', job, self.context('补充新角色', chosen))

    def preview(self):
        chosen = self.current_pull()
        def job():
            if chosen:
                game, snapshot = chosen
            else:
                self.step('正在读取客户端配置表…')
                game, snapshot = self.do_extract()
                self.set_pulled(game, snapshot)
            self.step('正在生成预览（不写入）…')
            refresh = self.mode.get() == 'full'
            # 客户端已启用、只是开放时间还没到的角色也要收录：配置是完整的，
            # 只是还没上线（新角色常常提前进包）。只有 enable=0 的废案才跳过。
            names = [c['name'] for c in snapshot['characters'] if c.get('enabled', True)]
            if not names:
                self.step('该版本没有可更新的角色（客户端配置可能不完整），请重新「一键拉取」。', False)
                return
            files, expected, report = plan_update(ROOT, Path(game), snapshot, names, False, refresh, 'base',
                                                  progress=self.progress)
            print(f"预览：将更新 {len(report['characters'])} 个角色 · "
                  f"页面 {sum(1 for f in report['files'] if f['path'].startswith('data/pages/'))} 个 · "
                  f"图片 {sum(1 for f in report['files'] if f['path'].startswith('assets/'))} 张 · "
                  f"字段差异 {len(report['conflicts'])} · 缺失原资源 {len(report['missingAssets'])}")
            print('预览完成，Wiki 未写入。')
            self.step('预览完成，Wiki 未写入。', False)
        self.wiki_job('预览差异', job, self.context('预览差异', chosen))

    def update_wiki(self):
        chosen = self.current_pull()
        if not chosen:
            messagebox.showinfo('还没有拉取的版本',
                                '请先点「一键拉取」解析客户端；或在上方版本列表里选择一个已拉取的版本。')
            return
        game, snapshot = chosen

        refresh = self.mode.get() == 'full'
        rebuild = self.rebuild.get()

        def job():
            # 客户端已启用、只是开放时间还没到的角色也要收录：配置是完整的，
            # 只是还没上线（新角色常常提前进包）。只有 enable=0 的废案才跳过。
            names = [c['name'] for c in snapshot['characters'] if c.get('enabled', True)]
            upcoming = [c['name'] for c in snapshot['characters'] if c.get('enabled', True) and not c.get('available')]
            self.step(f'第 1/3 步：生成角色、技能、个性与专武页面（{len(names)} 个角色，耗时数分钟）…')
            if not names:
                self.step('该版本没有可更新的角色（客户端配置可能不完整），请重新「一键拉取」。', False)
                return
            files, expected, report = plan_update(ROOT, Path(game), snapshot, names, False, refresh, 'base',
                                                  progress=self.progress)
            self.step('第 2/3 步：写入 data/ 与 assets/（先备份）…')
            backup = apply(ROOT, files, expected, OUTPUT / 'backups', progress=self.progress)
            (OUTPUT / 'update-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf8')
            (OUTPUT / 'update-report.md').write_text(cli.report_markdown(report), 'utf8')
            if not backup:
                self.step('数据已是当前版本，data/ 与 assets/ 无需修改。', False)
                return
            (backup / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf8')
            (backup / 'report.md').write_text(cli.report_markdown(report), 'utf8')
            (OUTPUT / 'last-backup.txt').write_text(str(backup), 'utf8')
            print(f'备份：{backup}')
            if rebuild:
                self.step('第 3/3 步：重建搜索索引与一图流数据…')
                try:
                    rebuild_wiki(print)
                except Exception as error:
                    print('重建索引出错（data/ 与 assets/ 已写入，可忽略或稍后重试）：', error)
                    self.step(f'更新完成，但重建索引失败：{error}（data/ 与 assets/ 已落地，可重试「更新」）', False)
                    return
            else:
                self.step('第 3/3 步：已按设置跳过重建索引。')
            pages = sum(1 for f in report['files'] if f['path'].startswith('data/pages/'))
            images = sum(1 for f in report['files'] if f['path'].startswith('assets/'))
            self.step(f"更新完成：{len(report['characters'])} 个角色 · 页面 {pages} 个 · 图片 {images} 张"
                      f" · 字段差异 {len(report['conflicts'])} · 缺失原资源 {len(report['missingAssets'])}", False)
            for name in upcoming:
                print('  尚未开放（已按客户端配置收录）：' + name)
            for line in cli.missing_lines(report['missingAssets']):
                print('  ' + line)
            print(f"报告：{OUTPUT / 'update-report.md'}")
        self.wiki_job('更新 Wiki', job, self.context('更新 Wiki', chosen))

    def rollback(self):
        def job():
            folder = last_backup()
            if not folder:
                print('还没有可回滚的备份。')
                return
            cli.main(['rollback', str(folder)] + ([] if self.rebuild.get() else ['--no-rebuild']))
        self.wiki_job('回滚上次更新', job)


def attach_console():
    """The packaged exe is windowed, so it starts without stdout. When it is run
    with arguments from a terminal, write to that terminal; otherwise to a log."""
    if sys.stdout is None or sys.stderr is None:
        stream = None
        if os.name == 'nt':
            try:
                import ctypes
                if ctypes.windll.kernel32.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
                    stream = open('CONOUT$', 'w', encoding='utf-8', errors='replace', buffering=1)
            except OSError:
                stream = None
        if stream is None:
            OUTPUT.mkdir(parents=True, exist_ok=True)
            stream = open(OUTPUT / 'client-update.log', 'a', encoding='utf-8', errors='replace', buffering=1)
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream
    # Redirected output is UTF-8, the same as ``python -X utf8``.
    for item in (sys.stdout, sys.stderr):
        try:
            if not item.isatty():
                item.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError, OSError):
            pass


def launch():
    multiprocessing.freeze_support()
    if len(sys.argv) > 1 and not sys.argv[1].startswith('--multiprocessing'):
        attach_console()
        from update_client import main_entry
        return main_entry(sys.argv[1:])
    App().mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(launch())
