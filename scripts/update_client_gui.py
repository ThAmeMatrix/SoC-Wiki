"""Windows interface for the local client tools.

* 资源归档 – extract every client resource into a versioned archive, with live
  progress; a new version is recorded only when something changed.
* 版本库   – every version with its changes; browse one or compare any two in
  the visual browser, export organised folders, remove old versions.
* Wiki 更新 – pull characters, skills, traits and weapons into this wiki.

Packaged as ``SoCwiki本地更新.exe`` by ``scripts/build_client_updater.py``.
"""
from __future__ import annotations

import io
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
        self.status = tk.StringVar(value='就绪')
        self.build()
        self.after(100, self.pump)
        self.after(300, self.refresh_versions)

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
        ttk.Label(tab, text='从本机客户端读取角色、技能、个性与专武，写入这个离线资料馆。写入前自动备份，可一键回滚。',
                  foreground='#4a5761').pack(anchor='w')
        ttk.Label(tab, text=f'资料馆：{ROOT}', foreground='#7a8790').pack(anchor='w', pady=(2, 8))
        modes = ttk.LabelFrame(tab, text='更新方式', padding=8)
        modes.pack(fill='x', pady=(4, 6))
        ttk.Radiobutton(modes, text='差量更新（只补缺失内容与客户端新增角色；冲突以本地客户端为准）', value='diff', variable=self.mode).pack(anchor='w')
        ttk.Radiobutton(modes, text='全覆盖（已匹配角色全部按客户端重算并覆盖；攻略、署名与备份保留）', value='full', variable=self.mode).pack(anchor='w')
        ttk.Checkbutton(tab, text='更新后重建一图流数据（推荐）', variable=self.rebuild).pack(anchor='w', pady=(0, 8))
        buttons = ttk.Frame(tab)
        buttons.pack(fill='x')
        self.wiki_buttons = []
        for text, action in (('检查新角色', self.check), ('预览差异', self.preview), ('一键拉取并更新', self.run_update),
                             ('回滚上次更新', self.rollback)):
            button = ttk.Button(buttons, text=text, command=action)
            button.pack(side='left', padx=(0, 6))
            self.wiki_buttons.append(button)
        self.wiki_log = self.log_box(tab, 18)

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
                elif kind == 'call':
                    payload[0]()
        except queue.Empty:
            pass
        self.after(100, self.pump)

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
                    self.busy = None
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
    def wiki_job(self, label, job):
        def wrapped():
            writer = QueueWriter(lambda text: self.messages.put(('log', self.wiki_log, text)))
            original = sys.stdout
            sys.stdout = writer
            try:
                job()
                print(f'\n{label}完成。')
            finally:
                sys.stdout = original
        for button in self.wiki_buttons:
            button.configure(state='disabled')
        if not self.thread(label, wrapped, lambda _: [b.configure(state='normal') for b in self.wiki_buttons], self.wiki_log):
            for button in self.wiki_buttons:
                button.configure(state='normal')

    def arguments(self, *extra):
        return [*extra, '--game', self.game.get(), '--output', str(OUTPUT), '--wiki', str(ROOT)]

    def snapshot(self):
        args = cli.parser().parse_args(self.arguments('characters', '--missing'))
        game, snap = cli.extract(args)
        have = cli.wiki_names(ROOT)
        names = list(dict.fromkeys(c['name'] for c in snap['characters'] if c['name'] not in have))
        return game, snap, names

    def check(self):
        self.wiki_job('检查新角色', lambda: cli.main(self.arguments('characters', '--missing')))

    def update_argv(self, game, names, dry):
        if self.mode.get() == 'diff':
            argv = ['add']
            for name in names:
                argv += ['--character', name]
            argv += ['--refresh', '--game', str(game), '--output', str(OUTPUT), '--wiki', str(ROOT)]
            argv += ['--dry-run'] if dry else ([] if self.rebuild.get() else ['--no-rebuild'])
            return argv
        if dry:
            return self.arguments('plan', '--all', '--refresh')
        return ['update', '--all', '--refresh', '--game', str(game), '--output', str(OUTPUT), '--wiki', str(ROOT)] + \
            ([] if self.rebuild.get() else ['--no-rebuild'])

    def preview(self):
        def job():
            game, _, names = self.snapshot()
            if self.mode.get() == 'diff' and not names:
                print('没有客户端新增的角色；可改用「全覆盖」刷新已收录角色。')
                return
            cli.main(self.update_argv(game, names, True))
        self.wiki_job('预览差异', job)

    def run_update(self):
        def job():
            game, _, names = self.snapshot()
            if self.mode.get() == 'diff' and not names:
                print('没有客户端新增的角色；可改用「全覆盖」刷新已收录角色。')
                return
            cli.main(self.update_argv(game, names, False))
        self.wiki_job('一键拉取并更新', job)

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
