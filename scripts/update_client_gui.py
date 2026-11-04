"""铃兰档案馆 · 本地更新 — the Windows interface for the local client tools.

A sidebar with four pages:

* 更新资料馆 – one button reads the client (reusing the cache when it has not
  changed), regenerates character / skill / trait / weapon pages, writes them
  with a backup, rebuilds the search index and extracts sprites, expression
  sheets and panel-calculator numbers. Less common actions sit below it.
* 资源归档   – extract every client resource into a versioned archive.
* 版本库     – browse or compare archived versions, export, clean up.
* 设置       – client and archive folders, logs and backups.

Packaged as ``SoCwiki本地更新.exe`` by ``scripts/build_client_updater.py``.
"""
from __future__ import annotations

import argparse
import io
import json
import multiprocessing
import os
import queue
import re
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
import tkinter.font as tkfont  # noqa: E402
from tkinter import filedialog, messagebox, ttk  # noqa: E402

from socdecode import cli  # noqa: E402
from socdecode.archive.catalog import CATEGORIES, KEYS  # noqa: E402
from socdecode.archive.scan import STAGES, Cancelled, default_workers, locate  # noqa: E402
from socdecode.archive.store import Store  # noqa: E402
from socdecode.config import OUTPUT, ROOT, archive_path, game_path, last_backup, load, save  # noqa: E402
from socdecode.client import game_root  # noqa: E402
from socdecode.wiki import plan_update  # noqa: E402
from socdecode.transaction import apply  # noqa: E402
from socdecode.rebuild import run as rebuild_wiki  # noqa: E402

# -- palette: the same paper / ink / green / gold as the wiki itself -------------
PAPER = '#f7f8f4'
SURFACE = '#ffffff'
SURFACE_ALT = '#f2f3ed'
SIDEBAR = '#fdfdfa'
INK = '#283b32'
MUTED = '#7c847c'
FAINT = '#a6ada3'
LINE = '#e5e8df'
LINE_STRONG = '#d6dbd0'
GREEN = '#2e5543'
GREEN_HOVER = '#264a3a'
GREEN_PRESS = '#1f3d30'
GREEN_SOFT = '#eaf0e6'
NAV_ACTIVE = '#36573f'
GOLD = '#ab8549'
GOLD_SOFT = '#fbf5ea'
RED = '#b4483c'
RED_SOFT = '#fbefed'
LOG_BG = '#fbfcf8'
HOVER = '#f3f5ef'

AUTO_SOURCE = '自动读取当前客户端（推荐）'
SCALE = 1.0


def S(value) -> int:
    """Scale a design pixel value to the screen's DPI."""
    return int(round(value * SCALE))


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


def elide(text, limit=46) -> str:
    text = str(text)
    if len(text) <= limit:
        return text
    half = (limit - 1) // 2
    return text[:half] + '…' + text[-half:]


def number(value) -> str:
    return f'{value:,}' if isinstance(value, int) else str(value)


def enable_dpi_awareness():
    """Render crisply on scaled displays instead of being bitmap-stretched."""
    if os.name != 'nt':
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError, ImportError):
        pass


# Segoe Fluent Icons / Segoe MDL2 Assets code points, with plain fallbacks.
GLYPHS = {
    'update': ('\uE895', '⟳'), 'archive': ('\uE7B8', '▣'), 'versions': ('\uE81C', '◷'),
    'settings': ('\uE713', '⚙'), 'search': ('\uE721', '⌕'), 'add': ('\uE8FA', '+'),
    'preview': ('\uE890', '◉'), 'undo': ('\uE7A7', '↶'), 'folder': ('\uE8B7', '▤'),
    'check': ('\uE73E', '✓'), 'warning': ('\uE7BA', '!'), 'error': ('\uE783', '✕'),
    'info': ('\uE946', 'i'), 'down': ('\uE70D', '▾'), 'up': ('\uE70E', '▴'),
    'right': ('\uE76C', '▸'), 'close': ('\uE711', '×'), 'download': ('\uE896', '↓'),
    'open': ('\uE8A7', '↗'), 'lock': ('\uE72E', '•'),
}


class Tooltip:
    """A small dark hint shown after hovering for a moment."""

    def __init__(self, app, widget, text):
        self.app, self.widget, self.text = app, widget, text
        self.tip = None
        self.job = None
        widget.bind('<Enter>', self.schedule, add='+')
        widget.bind('<Leave>', self.hide, add='+')
        widget.bind('<ButtonPress>', self.hide, add='+')

    def schedule(self, _=None):
        self.cancel()
        self.job = self.widget.after(500, self.show)

    def cancel(self):
        if self.job:
            self.widget.after_cancel(self.job)
            self.job = None

    def show(self):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + S(6)
        self.tip = tk.Toplevel(self.widget)
        self.tip.overrideredirect(True)
        self.tip.attributes('-topmost', True)
        tk.Label(self.tip, text=self.text, bg=INK, fg='#f3f5ee', font=(self.app.ui, 9), padx=S(10), pady=S(6),
                 justify='left', wraplength=S(360)).pack()
        self.tip.geometry(f'+{x}+{y}')

    def hide(self, _=None):
        self.cancel()
        if self.tip:
            self.tip.destroy()
            self.tip = None


class Stepper(tk.Canvas):
    """A horizontal step tracker: pending ○, running (spinning ring), done ✓, skipped –, failed ✕."""

    def __init__(self, app, parent, labels, bg=SURFACE):
        super().__init__(parent, height=S(78), bg=bg, highlightthickness=0, bd=0)
        self.app = app
        self.labels = list(labels)
        self.states = ['pending'] * len(self.labels)
        self.notes = [''] * len(self.labels)
        self.angle = 90
        self.spinning = False
        self.bind('<Configure>', lambda _: self.draw())

    def reset(self):
        self.states = ['pending'] * len(self.labels)
        self.notes = [''] * len(self.labels)
        self.draw()

    def set(self, index, state, note=None):
        if 0 <= index < len(self.states):
            self.states[index] = state
            if note is not None:
                self.notes[index] = note
        self.draw()
        self.spin()

    def set_all(self, states):
        self.states = list(states)
        self.draw()
        self.spin()

    def finish_active(self, state):
        self.states = [state if s == 'active' else s for s in self.states]
        self.draw()

    def spin(self):
        if self.spinning or 'active' not in self.states:
            return
        self.spinning = True

        def tick():
            if 'active' not in self.states or not self.winfo_exists():
                self.spinning = False
                self.draw()
                return
            self.angle = (self.angle - 14) % 360
            self.draw()
            self.after(50, tick)
        tick()

    def draw(self):
        self.delete('all')
        count = len(self.labels)
        width = max(self.winfo_width(), S(320))
        r, cy, margin = S(13), S(19), S(58)
        xs = [margin + i * (width - 2 * margin) / (count - 1) for i in range(count)] if count > 1 else [width / 2]
        for i in range(count - 1):
            done = self.states[i] in ('done', 'skip')
            self.create_line(xs[i] + r + S(6), cy, xs[i + 1] - r - S(6), cy,
                             fill=GREEN if done else LINE_STRONG, width=max(1, S(2)))
        k = SCALE
        for i, x in enumerate(xs):
            state = self.states[i]
            if state == 'done':
                self.create_oval(x - r, cy - r, x + r, cy + r, fill=GREEN, outline=GREEN)
                self.create_line(x - 5.5 * k, cy + 0.2 * k, x - 1.5 * k, cy + 4.2 * k, x + 5.8 * k, cy - 4.4 * k,
                                 fill='white', width=2.2 * k, capstyle='round', joinstyle='round')
                colour = GREEN
            elif state == 'error':
                self.create_oval(x - r, cy - r, x + r, cy + r, fill=RED, outline=RED)
                d = 4.6 * k
                self.create_line(x - d, cy - d, x + d, cy + d, fill='white', width=2.2 * k, capstyle='round')
                self.create_line(x - d, cy + d, x + d, cy - d, fill='white', width=2.2 * k, capstyle='round')
                colour = RED
            elif state == 'skip':
                self.create_oval(x - r, cy - r, x + r, cy + r, fill=SURFACE_ALT, outline=LINE_STRONG, width=max(1, S(1.5)))
                self.create_line(x - 4.5 * k, cy, x + 4.5 * k, cy, fill=FAINT, width=2 * k, capstyle='round')
                colour = FAINT
            elif state == 'active':
                self.create_oval(x - r, cy - r, x + r, cy + r, fill=GOLD_SOFT, outline=GOLD, width=max(1, S(1.5)))
                self.create_text(x, cy, text=str(i + 1), fill=GOLD, font=(self.app.ui, 10, 'bold'))
                g = r + S(4)
                self.create_arc(x - g, cy - g, x + g, cy + g, start=self.angle, extent=110, style='arc',
                                outline=GOLD, width=max(1, S(2)))
                colour = INK
            else:
                self.create_oval(x - r, cy - r, x + r, cy + r, fill=SURFACE, outline=LINE_STRONG, width=max(1, S(1.5)))
                self.create_text(x, cy, text=str(i + 1), fill=FAINT, font=(self.app.ui, 10))
                colour = MUTED
            self.create_text(x, cy + r + S(15), text=self.labels[i], fill=colour,
                             font=(self.app.ui, 10, 'bold' if state == 'active' else 'normal'))
            if self.notes[i]:
                self.create_text(x, cy + r + S(33), text=self.notes[i], fill=MUTED, font=(self.app.ui, 9))


class ScrollPage(tk.Frame):
    """A page whose body scrolls vertically; the scrollbar appears only when needed."""

    def __init__(self, parent, bg=PAPER):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0, yscrollincrement=S(24))
        self.bar = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview, style='Slim.Vertical.TScrollbar')
        self.body = tk.Frame(self.canvas, bg=bg)
        self.window = self.canvas.create_window(0, 0, window=self.body, anchor='nw')
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.canvas.pack(side='left', fill='both', expand=True)
        self.body.bind('<Configure>', self.sync)
        self.canvas.bind('<Configure>', self.sync)

    def sync(self, _=None):
        self.canvas.itemconfigure(self.window, width=self.canvas.winfo_width())
        self.canvas.configure(scrollregion=(0, 0, self.canvas.winfo_width(), self.body.winfo_reqheight()))
        needed = self.body.winfo_reqheight() > self.canvas.winfo_height() + 1
        if needed and not self.bar.winfo_ismapped():
            self.bar.pack(side='right', fill='y', before=self.canvas)
        elif not needed and self.bar.winfo_ismapped():
            self.bar.pack_forget()
            self.canvas.yview_moveto(0)

    def wheel(self, event):
        if self.body.winfo_reqheight() > self.canvas.winfo_height() + 1:
            self.canvas.yview_scroll(int(-event.delta / 120) * 2, 'units')


class Segmented(tk.Frame):
    """Two or more mutually exclusive options shown as one pill-shaped switch."""

    def __init__(self, app, parent, options, variable, command=None):
        super().__init__(parent, bg=LINE_STRONG, padx=1, pady=1)
        self.app, self.variable, self.command = app, variable, command
        self.items = {}
        for index, (value, text) in enumerate(options):
            item = tk.Label(self, text=text, padx=S(18), pady=S(6), cursor='hand2', takefocus=1)
            item.pack(side='left', padx=(1 if index else 0, 0))
            item.bind('<Button-1>', lambda _, v=value: self.choose(v))
            item.bind('<Return>', lambda _, v=value: self.choose(v))
            item.bind('<space>', lambda _, v=value: self.choose(v))
            item.bind('<Enter>', lambda _, v=value: self.hover(v, True))
            item.bind('<Leave>', lambda _, v=value: self.hover(v, False))
            self.items[value] = item
        variable.trace_add('write', lambda *_: self.paint())
        self.paint()

    def choose(self, value):
        self.variable.set(value)
        if self.command:
            self.command()

    def hover(self, value, inside):
        if value != self.variable.get():
            self.items[value].configure(bg=HOVER if inside else SURFACE)

    def paint(self):
        for value, item in self.items.items():
            on = value == self.variable.get()
            item.configure(bg=GREEN if on else SURFACE, fg='white' if on else INK,
                           font=(self.app.ui, 10, 'bold' if on else 'normal'))


class LogPanel:
    """A collapsible log: the header always shows the latest line, the body the full text."""

    def __init__(self, app, parent, title, open_file=None, height=14):
        self.app = app
        self.opened = False
        self.outer, inner = app.card(parent, 0)
        head = tk.Frame(inner, bg=SURFACE, cursor='hand2')
        head.pack(fill='x', padx=S(20), pady=S(13))
        self.arrow = app.icon_label(head, 'right', size=9, fg=MUTED)
        self.arrow.pack(side='left')
        title_label = tk.Label(head, text=title, font=(app.ui, 10, 'bold'), fg=INK, bg=SURFACE)
        title_label.pack(side='left', padx=(S(8), 0))
        for text, action in (('清空', self.clear), *((('打开日志文件', open_file),) if open_file else ())):
            app.link(head, text, action, size=9).pack(side='right', padx=(S(14), 0))
        self.summary = tk.Label(head, text='暂无记录', font=(app.ui, 9), fg=FAINT, bg=SURFACE, anchor='w')
        self.summary.pack(side='left', fill='x', expand=True, padx=(S(14), 0))
        for widget in (head, self.arrow, title_label, self.summary):
            widget.bind('<Button-1>', lambda _: self.toggle())
        self.body = tk.Frame(inner, bg=SURFACE)
        tk.Frame(self.body, bg=LINE, height=1).pack(fill='x')
        holder = tk.Frame(self.body, bg=LOG_BG)
        holder.pack(fill='both', expand=True)
        self.text = tk.Text(holder, height=height, wrap='word', font=(app.mono, 9), bg=LOG_BG, fg=INK,
                            relief='flat', bd=0, padx=S(18), pady=S(12), highlightthickness=0,
                            selectbackground=GREEN_SOFT, selectforeground=INK, insertbackground=INK,
                            spacing1=S(1), spacing3=S(1))
        bar = ttk.Scrollbar(holder, orient='vertical', command=self.text.yview, style='Log.Vertical.TScrollbar')
        self.text.configure(yscrollcommand=bar.set)
        bar.pack(side='right', fill='y')
        self.text.pack(side='left', fill='both', expand=True)
        self.text.tag_configure('time', foreground=FAINT)
        self.text.tag_configure('err', foreground=RED)
        self.text.tag_configure('ok', foreground=GREEN)
        self.text.tag_configure('head', foreground=GOLD, font=(app.mono, 9, 'bold'))
        self.text.configure(state='disabled')

    def toggle(self):
        self.hide() if self.opened else self.show()

    def show(self):
        if self.opened:
            return
        self.opened = True
        self.body.pack(fill='both', expand=True)
        self.arrow.configure(text=self.app.glyph('down'))

    def hide(self):
        if not self.opened:
            return
        self.opened = False
        self.body.pack_forget()
        self.arrow.configure(text=self.app.glyph('right'))

    @staticmethod
    def classify(line):
        if 'Traceback' in line or line.lstrip().startswith('File "') or '失败' in line or '出错' in line or 'Error' in line:
            return 'err'
        if line.startswith('——'):
            return 'head'
        if '完成' in line:
            return 'ok'
        return None

    def append(self, text):
        self.text.configure(state='normal')
        reveal = False
        for piece in text.splitlines(keepends=True):
            stripped = piece.strip()
            tag = self.classify(stripped) if stripped else None
            if stripped and not stripped.startswith('日志文件'):
                self.summary.configure(text=elide(stripped, 96), fg=RED if tag == 'err' else MUTED)
            match = re.match(r'^(\s*\[\d\d:\d\d:\d\d\]\s*)(.*)$', piece, re.S)
            if match:
                self.text.insert('end', match.group(1), ('time',))
                self.text.insert('end', match.group(2), (tag,) if tag else ())
            else:
                self.text.insert('end', piece, (tag,) if tag else ())
            reveal = reveal or (tag == 'err' and ('Traceback' in piece or '失败' in piece))
        self.text.see('end')
        self.text.configure(state='disabled')
        if reveal:
            self.show()

    def clear(self):
        self.text.configure(state='normal')
        self.text.delete('1.0', 'end')
        self.text.configure(state='disabled')
        self.summary.configure(text='暂无记录', fg=FAINT)


class App(tk.Tk):
    PAGES = (('update', '更新资料馆', 'update'), ('archive', '资源归档', 'archive'),
             ('versions', '版本库', 'versions'), ('settings', '设置', 'settings'))
    WIKI_STEPS = ('读取客户端', '生成页面', '写入并备份', '重建索引', '衍生资源')
    MEDIA_SCRIPTS = (
        ('像素动作与立绘表情', 'extract_art.py'),
        ('局外面板计算器数值', 'extract_panel_data.py'),
    )
    MODE_HINTS = {
        'diff': '只补缺失与空白的字段，你手动改过的内容和署名都会保留。日常使用选它即可。',
        'full': '按客户端数据重新生成全部已收录角色并覆盖旧字段；攻略与署名保留，写入前同样会备份。适合客户端大版本更新后使用。',
    }

    def __init__(self):
        enable_dpi_awareness()
        super().__init__()
        global SCALE
        SCALE = max(1.0, self.winfo_fpixels('1i') / 96)
        self.withdraw()
        self.title('铃兰档案馆 · 本地更新')
        self.geometry(f'{S(1180)}x{S(820)}')
        self.minsize(S(980), S(660))
        self.configure(bg=PAPER)
        self.messages = queue.Queue()
        self.busy = None
        self.busy_since = None
        self.last_log = None
        self.cancel = None
        self.server = None
        self.server_root = None
        self.url = ''
        settings = load()
        self.game = tk.StringVar(value=str(game_path()))
        self.archive = tk.StringVar(value=str(archive_path()))
        self.workers = tk.IntVar(value=int(settings.get('workers') or default_workers()))
        self.organise = tk.BooleanVar(value=settings.get('organise', True))
        chosen = set(settings.get('categories') or KEYS)
        self.categories = {key: tk.BooleanVar(value=key in chosen) for key in KEYS}
        self.mode = tk.StringVar(value=settings.get('wikiMode') if settings.get('wikiMode') in ('diff', 'full') else 'diff')
        self.rebuild = tk.BooleanVar(value=settings.get('wikiRebuild', True))
        self.media = tk.BooleanVar(value=settings.get('wikiMedia', True))
        self.voices = tk.BooleanVar(value=settings.get('wikiVoices', False))
        self.force_extract = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value='就绪')
        self.elapsed = tk.StringVar(value='')
        self.source = tk.StringVar(value=AUTO_SOURCE)
        self.pulls = {}          # fingerprint -> (label, game, snapshot)
        self.pull_items = []     # [(fingerprint, (label, game, snapshot))] newest first
        self.pages = {}
        self.nav = {}
        self.current = None
        self.actions = []        # disabled while a job runs
        self.link_fonts = {}
        self.images = []
        self.fonts()
        self.theme()
        self.build()
        self.set_icon()
        self.show_page('update')
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.bind_all('<MouseWheel>', self.on_wheel, add='+')
        for index, (key, _, _) in enumerate(self.PAGES, 1):
            self.bind_all(f'<Control-Key-{index}>', lambda _, k=key: self.show_page(k))
        self.deiconify()
        self.after(100, self.pump)
        self.after(150, self.refresh_overview)
        self.after(300, self.refresh_versions)
        self.after(350, self.safe_refresh_pulls)

    # -- look -------------------------------------------------------------------
    def fonts(self):
        families = set(tkfont.families(self))

        def pick(*names, fallback):
            return next((name for name in names if name in families), fallback)
        self.ui = pick('Microsoft YaHei UI', 'Microsoft YaHei', 'PingFang SC', 'Segoe UI', fallback='TkDefaultFont')
        self.serif = pick('Noto Serif SC', 'Source Han Serif SC', 'Songti SC', 'STSong', 'SimSun', fallback=self.ui)
        self.mono = pick('Cascadia Mono', 'Consolas', 'Courier New', fallback='TkFixedFont')
        self.icons = pick('Segoe Fluent Icons', 'Segoe MDL2 Assets', fallback=None)
        tkfont.nametofont('TkDefaultFont').configure(family=self.ui, size=10)
        tkfont.nametofont('TkTextFont').configure(family=self.ui, size=10)
        tkfont.nametofont('TkMenuFont').configure(family=self.ui, size=10)

    def glyph(self, name):
        pair = GLYPHS.get(name, ('', '•'))
        return pair[0] if self.icons else pair[1]

    def icon_label(self, parent, name, size=12, fg=GREEN, bg=SURFACE):
        font = (self.icons, size) if self.icons else (self.ui, size)
        return tk.Label(parent, text=self.glyph(name), font=font, fg=fg, bg=bg)

    def theme(self):
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', background=PAPER, foreground=INK, font=(self.ui, 10), bordercolor=LINE_STRONG,
                        lightcolor=SURFACE, darkcolor=SURFACE, troughcolor=SURFACE_ALT, focuscolor=GREEN_SOFT,
                        selectbackground=GREEN_SOFT, selectforeground=INK, insertcolor=INK)

        def button(name, bg, fg, border, hover, press, off_bg, off_fg, padding, font):
            style.configure(name, background=bg, foreground=fg, bordercolor=border, lightcolor=bg, darkcolor=bg,
                            focusthickness=0, focuscolor=bg, padding=padding, font=font, relief='solid',
                            borderwidth=1, anchor='center')
            style.map(name,
                      relief=[('pressed', 'solid'), ('!pressed', 'solid')],
                      background=[('disabled', off_bg), ('pressed', press), ('active', hover)],
                      lightcolor=[('disabled', off_bg), ('pressed', press), ('active', hover)],
                      darkcolor=[('disabled', off_bg), ('pressed', press), ('active', hover)],
                      foreground=[('disabled', off_fg)],
                      bordercolor=[('disabled', off_bg if border == bg else LINE),
                                   ('focus', GREEN_PRESS if border == bg else GREEN),
                                   ('active', hover if border == bg else '#c3cabb')])
        bold = (self.ui, 10, 'bold')
        button('Primary.TButton', GREEN, 'white', GREEN, GREEN_HOVER, GREEN_PRESS, '#b9c6bb', '#f4f6f1', (S(18), S(8)), bold)
        button('Accent.TButton', GREEN, 'white', GREEN, GREEN_HOVER, GREEN_PRESS, '#b9c6bb', '#f4f6f1', (S(34), S(11)), (self.ui, 11, 'bold'))
        button('Secondary.TButton', SURFACE, INK, LINE_STRONG, HOVER, '#e9ede4', SURFACE, FAINT, (S(14), S(7)), (self.ui, 10))
        button('Danger.TButton', SURFACE, RED, LINE_STRONG, RED_SOFT, '#f6e2df', SURFACE, FAINT, (S(14), S(7)), (self.ui, 10))

        field = dict(fieldbackground=SURFACE, background=SURFACE, foreground=INK, bordercolor=LINE_STRONG,
                     lightcolor=SURFACE, darkcolor=SURFACE, arrowcolor=MUTED, padding=(S(8), S(6)), insertcolor=INK)
        for name in ('TEntry', 'TCombobox', 'TSpinbox'):
            style.configure(name, **field)
            style.map(name, bordercolor=[('focus', GREEN)], lightcolor=[('focus', GREEN_SOFT)],
                      fieldbackground=[('readonly', SURFACE), ('disabled', SURFACE_ALT)],
                      selectbackground=[('readonly', SURFACE)], selectforeground=[('readonly', INK)],
                      arrowcolor=[('disabled', FAINT), ('active', GREEN)], background=[('active', HOVER)])
        self.option_add('*TCombobox*Listbox.font', (self.ui, 10))
        self.option_add('*TCombobox*Listbox.background', SURFACE)
        self.option_add('*TCombobox*Listbox.foreground', INK)
        self.option_add('*TCombobox*Listbox.selectBackground', GREEN_SOFT)
        self.option_add('*TCombobox*Listbox.selectForeground', INK)
        self.option_add('*TCombobox*Listbox.borderWidth', 0)
        style.configure('TCombobox', arrowsize=S(13))
        style.configure('TSpinbox', arrowsize=S(10))

        style.configure('TCheckbutton', background=SURFACE, foreground=INK, font=(self.ui, 10), focuscolor=SURFACE,
                        indicatorbackground=SURFACE, indicatorforeground='white', indicatormargin=(0, 0, S(8), 0),
                        indicatorsize=S(14), upperbordercolor=LINE_STRONG, lowerbordercolor=LINE_STRONG, padding=(0, S(3)))
        style.map('TCheckbutton',
                  indicatorbackground=[('selected', GREEN), ('active', HOVER)],
                  upperbordercolor=[('selected', GREEN), ('active', GREEN)],
                  lowerbordercolor=[('selected', GREEN), ('active', GREEN)],
                  background=[('active', SURFACE)], foreground=[('disabled', FAINT)])
        self.check_indicator(style)

        style.configure('Treeview', background=SURFACE, fieldbackground=SURFACE, foreground=INK, rowheight=S(34),
                        bordercolor=SURFACE, lightcolor=SURFACE, darkcolor=SURFACE, font=(self.ui, 10), borderwidth=0)
        style.map('Treeview', background=[('selected', GREEN_SOFT)], foreground=[('selected', INK)])
        style.configure('Treeview.Heading', background=SURFACE_ALT, foreground=MUTED, font=(self.ui, 9, 'bold'),
                        relief='flat', bordercolor=LINE, lightcolor=SURFACE_ALT, darkcolor=SURFACE_ALT, padding=(S(10), S(8)))
        style.map('Treeview.Heading', background=[('active', '#e9ece3')])
        style.layout('Treeview', [('Treeview.treearea', {'sticky': 'nswe'})])

        for name, trough in (('Slim', PAPER), ('Log', LOG_BG), ('Card', SURFACE)):
            style.layout(f'{name}.Vertical.TScrollbar', [('Vertical.Scrollbar.trough', {
                'children': [('Vertical.Scrollbar.thumb', {'expand': '1', 'sticky': 'nswe'})], 'sticky': 'ns'})])
            style.configure(f'{name}.Vertical.TScrollbar', gripcount=0, background='#d5dacf', troughcolor=trough,
                            bordercolor=trough, lightcolor='#d5dacf', darkcolor='#d5dacf', arrowsize=S(9))
            style.map(f'{name}.Vertical.TScrollbar', background=[('active', '#bfc6b8')],
                      lightcolor=[('active', '#bfc6b8')], darkcolor=[('active', '#bfc6b8')])

        style.configure('Green.Horizontal.TProgressbar', troughcolor=SURFACE_ALT, background=GREEN,
                        bordercolor=SURFACE_ALT, lightcolor=GREEN, darkcolor=GREEN, thickness=S(6))

    def check_indicator(self, style):
        """Rounded check boxes drawn with Pillow; clam's own indicator is a crude cross."""
        try:
            from PIL import Image, ImageDraw, ImageTk
        except ImportError:
            return

        def rgb(value):
            return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5)) + (255,)
        box, gap, k = S(16), S(9), 4
        big = box * k

        def make(fill, border, tick=None):
            image = Image.new('RGBA', ((box + gap) * k, big), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            line = max(k, int(big * 0.075))
            draw.rounded_rectangle([line // 2, line // 2, big - 1 - line // 2, big - 1 - line // 2],
                                   radius=int(big * 0.24), fill=rgb(fill), outline=rgb(border), width=line)
            if tick:
                draw.line([(big * 0.26, big * 0.52), (big * 0.43, big * 0.69), (big * 0.75, big * 0.33)],
                          fill=rgb(tick), width=int(big * 0.12), joint='curve')
            return ImageTk.PhotoImage(image.resize((box + gap, box), Image.LANCZOS))
        images = {
            'off': make(SURFACE, LINE_STRONG), 'off-hover': make(SURFACE, GREEN),
            'on': make(GREEN, GREEN, '#ffffff'), 'on-hover': make(GREEN_HOVER, GREEN_HOVER, '#ffffff'),
            'off-disabled': make(SURFACE_ALT, LINE), 'on-disabled': make('#b9c6bb', '#b9c6bb', '#ffffff'),
        }
        self.images.extend(images.values())
        try:
            style.element_create('Soc.Checkbutton.indicator', 'image', images['off'],
                                 ('disabled', 'selected', images['on-disabled']), ('disabled', images['off-disabled']),
                                 ('selected', 'active', images['on-hover']), ('selected', images['on']),
                                 ('active', images['off-hover']), sticky='')
        except tk.TclError:
            return
        style.layout('TCheckbutton', [('Checkbutton.padding', {'sticky': 'nswe', 'children': [
            ('Soc.Checkbutton.indicator', {'side': 'left', 'sticky': ''}),
            ('Checkbutton.label', {'side': 'left', 'sticky': 'nswe'})]})])

    def fit(self, label, text):
        """Show ``text`` in ``label``, shortened in the middle with … when it does not fit."""
        label.full_text = str(text)

        def apply(_=None):
            full = label.full_text
            width = label.winfo_width() - S(2)
            font = tkfont.Font(font=label.cget('font'))
            if width <= S(4) or font.measure(full) <= width:
                label.configure(text=full)
                return
            low, high, best = 1, len(full), '…'
            while low <= high:
                middle = (low + high) // 2
                head = middle // 2
                candidate = full[:head] + '…' + full[len(full) - (middle - head):]
                if font.measure(candidate) <= width:
                    best, low = candidate, middle + 1
                else:
                    high = middle - 1
            label.configure(text=best)
        if not getattr(label, 'fit_bound', False):
            label.bind('<Configure>', apply, add='+')
            label.fit_bound = True
        apply()

    def set_icon(self):
        try:
            from PIL import Image, ImageDraw, ImageTk
            logo = Image.open(ROOT / 'assets' / 'brand' / 'logo.webp').convert('RGBA')
        except (ImportError, OSError):
            return

        def badge(size):
            big = size * 4
            base = Image.new('RGBA', (big, big), (0, 0, 0, 0))
            ImageDraw.Draw(base).rounded_rectangle([0, 0, big - 1, big - 1], radius=int(big * 0.24), fill=(46, 85, 67, 255))
            light = Image.new('RGBA', logo.size, (243, 238, 221, 255))
            light.putalpha(logo.getchannel('A'))
            inner = int(big * 0.84)
            light = light.resize((inner, inner), Image.LANCZOS)
            base.alpha_composite(light, ((big - inner) // 2, (big - inner) // 2))
            return ImageTk.PhotoImage(base.resize((size, size), Image.LANCZOS))
        try:
            icons = [badge(64), badge(32), badge(S(40))]
        except (OSError, ValueError):
            return
        self.images.extend(icons)
        self.iconphoto(True, icons[0], icons[1])
        self.brand_icon.configure(image=icons[2], text='', width=S(40), height=S(40))

    # -- small building blocks ---------------------------------------------------
    def card(self, parent, pad=20, bg=SURFACE):
        outer = tk.Frame(parent, bg=bg, highlightthickness=1, highlightbackground=LINE, highlightcolor=LINE)
        inner = tk.Frame(outer, bg=bg)
        inner.pack(fill='both', expand=True, padx=S(pad), pady=S(pad))
        return outer, inner

    def label(self, parent, text='', size=10, weight='normal', fg=INK, bg=SURFACE, font=None, **options):
        return tk.Label(parent, text=text, font=(font or self.ui, size, weight), fg=fg, bg=bg, **options)

    def wrap(self, label, reference=None, pad=0):
        """Wrap ``label`` at its own width. ``width=1`` keeps a long line from
        widening the layout before the first wrap is applied."""
        label.configure(width=1)
        label.bind('<Configure>', lambda e: label.configure(wraplength=max(S(160), e.width - pad)), add='+')

    def link(self, parent, text, command, size=10, fg=GREEN, bg=SURFACE, tip=None):
        normal = self.link_fonts.setdefault((size, False), tkfont.Font(family=self.ui, size=size))
        under = self.link_fonts.setdefault((size, True), tkfont.Font(family=self.ui, size=size, underline=True))
        item = tk.Label(parent, text=text, font=normal, fg=fg, bg=bg, cursor='hand2', takefocus=1)
        item.bind('<Enter>', lambda _: item.configure(font=under), add='+')
        item.bind('<Leave>', lambda _: item.configure(font=normal), add='+')
        item.bind('<Button-1>', lambda _: command())
        item.bind('<Return>', lambda _: command())
        if tip:
            Tooltip(self, item, tip)
        return item

    def header(self, parent, title, subtitle, right=None):
        box = tk.Frame(parent, bg=PAPER)
        box.pack(fill='x', padx=S(36), pady=(S(30), S(18)))
        top = tk.Frame(box, bg=PAPER)
        top.pack(fill='x')
        self.label(top, title, 20, 'bold', bg=PAPER, font=self.serif).pack(side='left')
        if right is not None:
            right(top).pack(side='right', anchor='s')
        text = self.label(box, subtitle, 10, fg=MUTED, bg=PAPER, justify='left', anchor='w')
        text.pack(fill='x', pady=(S(6), 0))
        self.wrap(text, box)
        return box

    def section(self, parent, title, note=None):
        row = tk.Frame(parent, bg=PAPER)
        row.pack(fill='x', padx=S(36), pady=(S(6), S(10)))
        self.label(row, title, 11, 'bold', bg=PAPER).pack(side='left')
        if note:
            self.label(row, note, 9, fg=MUTED, bg=PAPER).pack(side='left', padx=(S(12), 0))
        return row

    def tool_tile(self, parent, icon, title, hint, command):
        tile = tk.Frame(parent, bg=SURFACE, highlightthickness=1, highlightbackground=LINE, highlightcolor=GREEN,
                        cursor='hand2', takefocus=1)
        inner = tk.Frame(tile, bg=SURFACE)
        inner.pack(fill='both', expand=True, padx=S(18), pady=S(16))
        mark = self.icon_label(inner, icon, size=15)
        mark.pack(anchor='w')
        name = self.label(inner, title, 10, 'bold')
        name.pack(anchor='w', pady=(S(10), S(3)))
        note = self.label(inner, hint, 9, fg=MUTED, justify='left', anchor='w')
        note.pack(fill='x')
        tile.bind('<Configure>', lambda e: note.configure(wraplength=max(S(120), e.width - S(40))), add='+')
        parts = (tile, inner, mark, name, note)

        def paint(on):
            tile.configure(highlightbackground=GREEN if on else LINE)
            for part in parts:
                part.configure(bg='#fbfcf8' if on else SURFACE)
        for part in parts:
            part.bind('<Enter>', lambda _: paint(True), add='+')
            part.bind('<Leave>', lambda _: paint(False), add='+')
            part.bind('<Button-1>', lambda _: command())
        tile.bind('<Return>', lambda _: command())
        tile.bind('<space>', lambda _: command())
        return tile

    # -- layout -------------------------------------------------------------------
    def build(self):
        self.sidebar = tk.Frame(self, bg=SIDEBAR, width=S(236))
        self.sidebar.pack(side='left', fill='y')
        self.sidebar.pack_propagate(False)
        tk.Frame(self, bg=LINE, width=1).pack(side='left', fill='y')
        self.content = tk.Frame(self, bg=PAPER)
        self.content.pack(side='left', fill='both', expand=True)
        self.build_sidebar()
        self.build_update_page()
        self.build_archive_page()
        self.build_versions_page()
        self.build_settings_page()
        self.steppers = {'wiki': self.wiki_stepper, 'archive': self.archive_stepper}

    def build_sidebar(self):
        side = self.sidebar
        brand = tk.Frame(side, bg=SIDEBAR)
        brand.pack(fill='x', padx=S(22), pady=(S(28), S(26)))
        self.brand_icon = tk.Label(brand, text='铃', font=(self.serif, 16, 'bold'), fg='white', bg=GREEN, width=2)
        self.brand_icon.pack(side='left')
        words = tk.Frame(brand, bg=SIDEBAR)
        words.pack(side='left', padx=(S(12), 0))
        self.label(words, '铃兰档案馆', 14, 'bold', fg=GREEN, bg=SIDEBAR, font=self.serif).pack(anchor='w')
        self.label(words, '本地更新工具', 9, fg=MUTED, bg=SIDEBAR).pack(anchor='w')
        for key, text, icon in self.PAGES:
            item = tk.Frame(side, bg=SIDEBAR, cursor='hand2', takefocus=1)
            item.pack(fill='x', padx=S(14), pady=S(2))
            bar = tk.Frame(item, bg=SIDEBAR, width=S(3))
            bar.pack(side='left', fill='y')
            mark = self.icon_label(item, icon, size=12, fg=MUTED, bg=SIDEBAR)
            mark.pack(side='left', padx=(S(13), S(12)), pady=S(11))
            name = self.label(item, text, 10, fg='#5f6a5d', bg=SIDEBAR)
            name.pack(side='left')
            self.nav[key] = (item, bar, mark, name)
            for part in (item, mark, name):
                part.bind('<Button-1>', lambda _, k=key: self.show_page(k))
                part.bind('<Enter>', lambda _, k=key: self.hover_nav(k, True), add='+')
                part.bind('<Leave>', lambda _, k=key: self.hover_nav(k, False), add='+')
            item.bind('<Return>', lambda _, k=key: self.show_page(k))
        foot = tk.Frame(side, bg=SIDEBAR)
        foot.pack(side='bottom', fill='x', padx=S(18), pady=S(20))
        box, inner = self.card(foot, 14, bg=SURFACE)
        box.pack(fill='x')
        row = tk.Frame(inner, bg=SURFACE)
        row.pack(fill='x')
        self.busy_dot = tk.Label(row, text='●', font=(self.ui, 9), fg=GREEN, bg=SURFACE)
        self.busy_dot.pack(side='left')
        self.label(row, '', 9, textvariable=self.status, anchor='w').pack(side='left', fill='x', expand=True, padx=(S(6), 0))
        elapsed = self.label(inner, '', 9, fg=MUTED, textvariable=self.elapsed, anchor='w')
        divider = tk.Frame(inner, bg=LINE, height=1)
        divider.pack(fill='x', pady=S(10))

        def toggle_elapsed(*_):
            if self.elapsed.get() and not elapsed.winfo_ismapped():
                elapsed.pack(fill='x', before=divider)
            elif not self.elapsed.get() and elapsed.winfo_ismapped():
                elapsed.pack_forget()
        self.elapsed.trace_add('write', toggle_elapsed)
        self.side_client = self.label(inner, '正在检查客户端…', 9, fg=MUTED, anchor='w', justify='left')
        self.side_client.pack(fill='x')
        self.side_client.bind('<Button-1>', lambda _: self.show_page('settings'))
        self.label(foot, 'Ctrl+1–4 切换页面', 8, fg=FAINT, bg=SIDEBAR).pack(anchor='w', pady=(S(10), 0))

    def hover_nav(self, key, inside):
        if key == self.current:
            return
        item, bar, mark, name = self.nav[key]
        colour = HOVER if inside else SIDEBAR
        for part in (item, bar, mark, name):
            part.configure(bg=colour)

    def show_page(self, key):
        if key == self.current:
            return
        for page in self.pages.values():
            page.pack_forget()
        self.pages[key].pack(fill='both', expand=True)
        self.current = key
        for name, (item, bar, mark, label) in self.nav.items():
            on = name == key
            bg = GREEN_SOFT if on else SIDEBAR
            for part in (item, mark, label):
                part.configure(bg=bg)
            bar.configure(bg=GREEN if on else SIDEBAR)
            mark.configure(fg=GREEN if on else MUTED)
            label.configure(fg=NAV_ACTIVE if on else '#5f6a5d', font=(self.ui, 10, 'bold' if on else 'normal'))

    def on_wheel(self, event):
        widget = event.widget
        try:
            kind = widget.winfo_class()
        except (AttributeError, tk.TclError):
            return
        if kind in ('Text', 'Treeview', 'Listbox', 'TCombobox', 'TSpinbox'):
            return
        page = self.pages.get(self.current)
        if isinstance(page, ScrollPage):
            page.wheel(event)

    # -- page: update -------------------------------------------------------------
    def build_update_page(self):
        page = ScrollPage(self.content)
        self.pages['update'] = page
        body = page.body
        self.header(body, '更新资料馆', '从本机游戏客户端读取角色、技能、个性与专武，写入离线资料馆。每次写入前都会自动备份，可以随时回滚。')

        tiles = tk.Frame(body, bg=PAPER)
        tiles.pack(fill='x', padx=S(36), pady=(0, S(18)))
        self.overview = {}
        for index, (key, title) in enumerate((('client', '游戏客户端'), ('wiki', '资料馆'), ('last', '上次更新'))):
            tiles.columnconfigure(index, weight=1, uniform='overview')
            outer, inner = self.card(tiles, 18)
            outer.grid(row=0, column=index, sticky='nsew', padx=(0 if index == 0 else S(14), 0))
            self.label(inner, title, 9, fg=MUTED).pack(anchor='w')
            value = self.label(inner, '…', 14, 'bold', anchor='w', width=1)
            value.pack(fill='x', pady=(S(6), S(2)))
            sub = self.label(inner, '', 9, fg=MUTED, anchor='w', width=1)
            sub.pack(fill='x')
            self.overview[key] = (value, sub)

        outer, inner = self.card(body, 24)
        outer.pack(fill='x', padx=S(36), pady=(0, S(18)))
        row = tk.Frame(inner, bg=SURFACE)
        row.pack(fill='x')
        self.label(row, '更新方式', 10, 'bold').pack(side='left')
        Segmented(self, row, (('diff', '差量更新'), ('full', '全覆盖')), self.mode, self.on_mode).pack(side='left', padx=(S(16), 0))
        self.mode_hint = self.label(inner, self.MODE_HINTS[self.mode.get()], 9, fg=MUTED, justify='left', anchor='w')
        self.mode_hint.pack(fill='x', pady=(S(10), 0))
        self.wrap(self.mode_hint, inner)
        go = tk.Frame(inner, bg=SURFACE)
        go.pack(fill='x', pady=(S(20), 0))
        self.update_button = ttk.Button(go, text='开始更新', style='Accent.TButton', command=self.start_update)
        self.update_button.pack(side='left')
        self.actions.append(self.update_button)
        self.more_link = self.link(go, '更多选项 ▾', self.toggle_more)
        self.more_link.pack(side='left', padx=(S(22), 0))
        self.label(go, '通常 2–6 分钟；客户端未变化时直接复用缓存', 9, fg=FAINT).pack(side='right')

        self.more = tk.Frame(inner, bg=SURFACE)
        tk.Frame(self.more, bg=LINE, height=1).pack(fill='x', pady=(S(20), S(16)))
        source = tk.Frame(self.more, bg=SURFACE)
        source.pack(fill='x')
        self.label(source, '数据来源', 10, 'bold').pack(side='left')
        self.source_box = ttk.Combobox(source, textvariable=self.source, state='readonly', width=58, values=[AUTO_SOURCE])
        self.source_box.pack(side='left', padx=(S(16), S(12)))
        self.source_box.current(0)
        self.link(source, '立即读取客户端', self.pull, tip='只读取客户端并保存为一个版本，不写入资料馆').pack(side='left')
        hint = self.label(self.more, '默认每次自动读取当前客户端；也可以选择之前读取过的版本来更新。', 9, fg=MUTED, anchor='w')
        hint.pack(fill='x', pady=(S(6), S(12)))
        for text, variable in (('写入后重建搜索索引与一图流数据（推荐）', self.rebuild),
                               ('提取像素动作、立绘表情与局外面板数值（推荐）', self.media),
                               ('重新提取角色语音（需 tools/vgmstream 解码器，耗时较长，通常不需要）', self.voices),
                               ('强制重新解析客户端（忽略缓存，较慢；数据异常时再用）', self.force_extract)):
            ttk.Checkbutton(self.more, text=text, variable=variable, command=self.remember_wiki).pack(anchor='w', pady=S(1))

        self.progress_outer, prog = self.card(body, 24)
        self.progress_outer.pack(fill='x', padx=S(36), pady=(0, S(18)))
        head = tk.Frame(prog, bg=SURFACE)
        head.pack(fill='x')
        self.label(head, '进度', 11, 'bold').pack(side='left')
        self.label(head, '', 9, fg=MUTED, textvariable=self.elapsed).pack(side='right')
        self.wiki_stepper = Stepper(self, prog, self.WIKI_STEPS)
        self.wiki_stepper.pack(fill='x', pady=(S(14), S(8)))
        self.wiki_bar = ttk.Progressbar(prog, style='Green.Horizontal.TProgressbar', maximum=1000)
        self.wiki_bar.pack(fill='x')
        self.wiki_step = tk.StringVar(value='准备就绪。点击「开始更新」，其余步骤会自动完成。')
        step = self.label(prog, '', 10, textvariable=self.wiki_step, justify='left', anchor='w')
        step.pack(fill='x', pady=(S(12), 0))
        self.wrap(step, prog)

        self.result_outer = tk.Frame(body, bg=SURFACE, highlightthickness=1, highlightbackground=LINE)
        self.result_accent = tk.Frame(self.result_outer, bg=GREEN, width=S(4))
        self.result_accent.pack(side='left', fill='y')
        self.result_inner = tk.Frame(self.result_outer, bg=SURFACE)
        self.result_inner.pack(side='left', fill='both', expand=True, padx=S(24), pady=S(20))

        self.section(body, '其他操作', '不常用，需要时再点')
        grid = tk.Frame(body, bg=PAPER)
        grid.pack(fill='x', padx=S(36), pady=(0, S(18)))
        for index, (icon, title, hint, action) in enumerate((
                ('search', '检查新角色', '列出客户端已有、资料馆还没收录的角色。只查看，不写入。', self.check),
                ('add', '补充新角色', '只导入缺少的角色，不改动已有页面。', self.add_new),
                ('preview', '预览变更', '统计一次更新会改动多少页面与图片，不写入。', self.preview),
                ('undo', '回滚上次更新', '把资料馆恢复到上一次更新之前的状态。', self.rollback))):
            grid.columnconfigure(index, weight=1, uniform='tools')
            self.tool_tile(grid, icon, title, hint, action).grid(row=0, column=index, sticky='nsew',
                                                                    padx=(0 if index == 0 else S(14), 0))

        self.wiki_log = LogPanel(self, body, '运行日志', open_file=self.open_last_log)
        self.wiki_log.outer.pack(fill='x', padx=S(36), pady=(0, S(32)))

    def on_mode(self):
        self.mode_hint.configure(text=self.MODE_HINTS[self.mode.get()])
        self.remember_wiki()

    def toggle_more(self):
        if self.more.winfo_ismapped():
            self.more.pack_forget()
            self.more_link.configure(text='更多选项 ▾')
        else:
            self.more.pack(fill='x')
            self.more_link.configure(text='收起选项 ▴')

    def remember_wiki(self):
        save(wikiMode=self.mode.get(), wikiRebuild=bool(self.rebuild.get()),
             wikiMedia=bool(self.media.get()), wikiVoices=bool(self.voices.get()))

    # -- page: archive ------------------------------------------------------------
    def build_archive_page(self):
        page = ScrollPage(self.content)
        self.pages['archive'] = page
        body = page.body
        self.header(body, '资源归档', '把客户端的全部资源解析为可直接查看的文件并按分类整理。内容有变化时，以解析时间记录一个新版本并自动生成差分；没变化的文件直接复用，中途取消也会保留已完成的部分。')

        outer, inner = self.card(body, 24)
        outer.pack(fill='x', padx=S(36), pady=(0, S(18)))
        head = tk.Frame(inner, bg=SURFACE)
        head.pack(fill='x', pady=(0, S(12)))
        self.label(head, '解析范围', 11, 'bold').pack(side='left')
        for text, keys in (('清空', ()), ('仅配置表与图片', ('table', 'image', 'sprite')), ('全选', KEYS)):
            self.link(head, text, lambda keys=keys: [v.set(k in keys) for k, v in self.categories.items()], size=9) \
                .pack(side='right', padx=(S(16), 0))
        boxes = tk.Frame(inner, bg=SURFACE)
        boxes.pack(fill='x')
        for index, (key, label) in enumerate(CATEGORIES):
            boxes.columnconfigure(index % 6, weight=1, uniform='scope')
            ttk.Checkbutton(boxes, text=label, variable=self.categories[key]).grid(row=index // 6, column=index % 6,
                                                                                  sticky='w', pady=S(2))
        self.label(inner, '账号记录、启动器数据库、战斗回放（assets/Report）与玩家偏好设置始终不读取。', 9, fg=FAINT,
                   anchor='w').pack(fill='x', pady=(S(10), 0))
        tk.Frame(inner, bg=LINE, height=1).pack(fill='x', pady=S(16))
        opts = tk.Frame(inner, bg=SURFACE)
        opts.pack(fill='x')
        self.label(opts, '并行进程', 10).pack(side='left')
        ttk.Spinbox(opts, from_=1, to=max(2, os.cpu_count() or 4), width=4, textvariable=self.workers).pack(side='left', padx=(S(10), S(6)))
        self.label(opts, f'本机 {os.cpu_count() or "?"} 线程', 9, fg=FAINT).pack(side='left', padx=(0, S(26)))
        ttk.Checkbutton(opts, text='解析后刷新分类目录（硬链接，不额外占用空间）', variable=self.organise).pack(side='left')

        row = tk.Frame(body, bg=PAPER)
        row.pack(fill='x', padx=S(36), pady=(0, S(18)))
        self.scan_button = ttk.Button(row, text='开始解析', style='Accent.TButton', command=self.start_scan)
        self.scan_button.pack(side='left')
        self.actions.append(self.scan_button)
        self.cancel_button = ttk.Button(row, text='取消', style='Secondary.TButton', command=self.cancel_scan, state='disabled')
        self.cancel_button.pack(side='left', padx=(S(10), 0))
        for text, action in (('打开分类目录', lambda: self.open_folder(Path(self.archive.get()) / 'library' / '当前版本')),
                             ('查看最新差分', self.latest_diff), ('打开资源浏览器', lambda: self.open_viewer(''))):
            ttk.Button(row, text=text, style='Secondary.TButton', command=action).pack(side='right', padx=(S(10), 0))

        outer, prog = self.card(body, 24)
        outer.pack(fill='x', padx=S(36), pady=(0, S(18)))
        self.label(prog, '进度', 11, 'bold', anchor='w').pack(fill='x')
        self.archive_stepper = Stepper(self, prog, [label for _, label in STAGES])
        self.archive_stepper.pack(fill='x', pady=(S(14), S(8)))
        self.bar = ttk.Progressbar(prog, style='Green.Horizontal.TProgressbar', maximum=1000)
        self.bar.pack(fill='x')
        self.line1 = tk.StringVar(value='尚未开始')
        self.line2 = tk.StringVar(value='')
        first = self.label(prog, '', 10, 'bold', textvariable=self.line1, anchor='w', justify='left')
        first.pack(fill='x', pady=(S(12), 0))
        second = self.label(prog, '', 9, fg=MUTED, textvariable=self.line2, anchor='w', justify='left')
        second.pack(fill='x', pady=(S(4), 0))
        self.wrap(first, prog)
        self.wrap(second, prog)

        self.archive_log = LogPanel(self, body, '解析日志')
        self.archive_log.outer.pack(fill='x', padx=S(36), pady=(0, S(32)))

    # -- page: versions -----------------------------------------------------------
    def build_versions_page(self):
        page = tk.Frame(self.content, bg=PAPER)
        self.pages['versions'] = page
        self.usage = tk.StringVar(value='')
        self.header(page, '版本库', '每次解析出不同内容时，会以解析时间记录一个版本。选中一个可以浏览，按住 Ctrl 选中两个可以比较；双击直接浏览。',
                    right=lambda parent: self.label(parent, '', 9, fg=MUTED, bg=PAPER, textvariable=self.usage))
        bar = tk.Frame(page, bg=PAPER)
        bar.pack(fill='x', padx=S(36), pady=(0, S(14)))
        ttk.Button(bar, text='浏览所选版本', style='Primary.TButton', command=self.browse_selected).pack(side='left')
        ttk.Button(bar, text='与上一版本比较', style='Secondary.TButton', command=self.compare_previous).pack(side='left', padx=(S(10), 0))
        ttk.Button(bar, text='比较所选两个', style='Secondary.TButton', command=self.compare_selected).pack(side='left', padx=(S(10), 0))
        self.more_versions = ttk.Button(bar, text='更多操作 ▾', style='Secondary.TButton', command=self.versions_menu)
        self.more_versions.pack(side='right')
        ttk.Button(bar, text='刷新', style='Secondary.TButton', command=self.refresh_versions).pack(side='right', padx=(0, S(10)))

        detail_outer, detail = self.card(page, 0)
        detail_outer.pack(side='bottom', fill='x', padx=S(36), pady=(S(14), S(30)))
        self.version_info = tk.Text(detail, height=7, wrap='word', font=(self.ui, 9), bg=SURFACE, fg=INK, relief='flat',
                                    bd=0, padx=S(20), pady=S(14), highlightthickness=0, spacing1=S(2), spacing3=S(2))
        self.version_info.pack(fill='both', expand=True)
        self.version_info.tag_configure('title', font=(self.ui, 10, 'bold'))
        self.version_info.insert('end', '选中一个版本后，这里会显示它的资源分类与变化。')
        self.version_info.configure(state='disabled', fg=MUTED)

        outer, inner = self.card(page, 0)
        outer.pack(fill='both', expand=True, padx=S(36))
        columns = (('label', '解析时间', 160), ('game', '资源版本', 88), ('entries', '资源数', 86), ('size', '体积', 80),
                   ('added', '新增', 70), ('modified', '修改', 62), ('removed', '删除', 62), ('renamed', '改名', 56),
                   ('sources', '文件变化', 76), ('time', '耗时', 64))
        self.tree = ttk.Treeview(inner, columns=[c[0] for c in columns], show='headings', selectmode='extended')
        for key, text, width in columns:
            self.tree.heading(key, text=text, anchor='w' if key == 'label' else 'e')
            self.tree.column(key, width=S(width), minwidth=S(56), anchor='w' if key == 'label' else 'e', stretch=key == 'label')
        self.tree.tag_configure('odd', background='#fafbf7')
        scroll = ttk.Scrollbar(inner, orient='vertical', command=self.tree.yview, style='Card.Vertical.TScrollbar')
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.tree.pack(side='left', fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', lambda _: self.show_version())
        self.tree.bind('<Double-1>', lambda _: self.browse_selected())
        self.versions_empty = tk.Frame(inner, bg=SURFACE)
        self.label(self.versions_empty, '还没有版本', 12, 'bold').pack()
        self.label(self.versions_empty, '在「资源归档」完成一次解析后，这里会列出每个版本。', 9, fg=MUTED).pack(pady=(S(6), S(14)))
        ttk.Button(self.versions_empty, text='去解析资源', style='Primary.TButton',
                   command=lambda: self.show_page('archive')).pack()

    def versions_menu(self):
        menu = tk.Menu(self, tearoff=0, bg=SURFACE, fg=INK, activebackground=GREEN_SOFT, activeforeground=INK,
                       font=(self.ui, 10), bd=0, relief='flat')
        menu.add_command(label='打开版本报告', command=self.open_report)
        menu.add_command(label='导出所选版本的分类目录', command=self.export_selected)
        menu.add_separator()
        menu.add_command(label='删除所选版本…', command=self.delete_selected)
        menu.add_command(label='清理未引用的文件', command=self.collect)
        button = self.more_versions
        try:
            menu.tk_popup(button.winfo_rootx(), button.winfo_rooty() + button.winfo_height() + S(4))
        finally:
            menu.grab_release()

    # -- page: settings -----------------------------------------------------------
    def build_settings_page(self):
        page = ScrollPage(self.content)
        self.pages['settings'] = page
        body = page.body
        self.header(body, '设置', '这些设置会自动保存，下次打开时沿用。')

        def block(title, hint):
            outer, inner = self.card(body, 24)
            outer.pack(fill='x', padx=S(36), pady=(0, S(16)))
            self.label(inner, title, 11, 'bold', anchor='w').pack(fill='x')
            note = self.label(inner, hint, 9, fg=MUTED, anchor='w', justify='left')
            note.pack(fill='x', pady=(S(4), S(14)))
            self.wrap(note, inner)
            return inner

        inner = block('游戏客户端', '选择《铃兰之剑》的安装目录；SoCLauncher 或 SwordOfConvallaria 文件夹都可以。只读取文件，不会登录或启动游戏。')
        row = tk.Frame(inner, bg=SURFACE)
        row.pack(fill='x')
        entry = ttk.Entry(row, textvariable=self.game)
        entry.pack(side='left', fill='x', expand=True)
        entry.bind('<Return>', lambda _: self.commit_paths())
        entry.bind('<FocusOut>', lambda _: self.commit_paths())
        ttk.Button(row, text='自动识别', style='Secondary.TButton', command=self.detect).pack(side='right', padx=(S(10), 0))
        ttk.Button(row, text='选择…', style='Secondary.TButton', command=self.choose_game).pack(side='right', padx=(S(10), 0))
        self.client_state = self.label(inner, '正在检查…', 9, fg=MUTED, anchor='w', width=1)
        self.client_state.pack(fill='x', pady=(S(10), 0))

        inner = block('资源归档目录', '「资源归档」解析出的文件与版本记录保存在这里，完整解析约占十几 GB。')
        row = tk.Frame(inner, bg=SURFACE)
        row.pack(fill='x')
        entry = ttk.Entry(row, textvariable=self.archive)
        entry.pack(side='left', fill='x', expand=True)
        entry.bind('<Return>', lambda _: self.commit_paths(archive=True))
        entry.bind('<FocusOut>', lambda _: self.commit_paths(archive=True))
        ttk.Button(row, text='打开', style='Secondary.TButton',
                   command=lambda: self.open_folder(self.archive.get())).pack(side='right', padx=(S(10), 0))
        ttk.Button(row, text='选择…', style='Secondary.TButton', command=self.choose_archive).pack(side='right', padx=(S(10), 0))

        inner = block('资料馆', '更新会写入这个文件夹里的 data/ 与 assets/。')
        self.label(inner, str(ROOT), 10, font=self.mono, anchor='w').pack(fill='x', pady=(0, S(14)))
        row = tk.Frame(inner, bg=SURFACE)
        row.pack(fill='x')
        ttk.Button(row, text='在浏览器中打开资料馆', style='Primary.TButton', command=self.open_wiki).pack(side='left')
        ttk.Button(row, text='打开文件夹', style='Secondary.TButton', command=lambda: self.open_folder(ROOT)).pack(side='left', padx=(S(10), 0))

        inner = block('日志与备份', '每次操作都会写一份日志；每次写入资料馆前都会在备份目录保存改动前的文件。')
        row = tk.Frame(inner, bg=SURFACE)
        row.pack(fill='x')
        for text, action in (('打开日志目录', lambda: self.open_folder(OUTPUT / 'logs')),
                             ('打开备份目录', lambda: self.open_folder(OUTPUT / 'backups')),
                             ('打开上次更新报告', self.open_update_report)):
            ttk.Button(row, text=text, style='Secondary.TButton', command=action).pack(side='left', padx=(0, S(10)))

    def commit_paths(self, archive=False):
        self.remember()
        self.refresh_overview()
        if archive:
            self.refresh_versions()

    # -- overview -----------------------------------------------------------------
    def refresh_overview(self):
        game = self.game.get()

        def work():
            try:
                root = game_root(Path(game))
                client = (True, '已就绪', str(root))
            except (ValueError, OSError):
                client = (False, '未找到', '到「设置」里选择客户端目录')
            try:
                wiki = (f'{len(cli.wiki_names(ROOT)):,} 位角色', str(ROOT))
            except (OSError, ValueError, KeyError):
                wiki = ('—', str(ROOT))
            report = OUTPUT / 'update-report.json'
            if report.is_file():
                when = time.strftime('%Y-%m-%d %H:%M', time.localtime(report.stat().st_mtime))
                backup = last_backup()
                last = (when, '有备份，可以回滚' if backup and backup.exists() else '已完成')
            else:
                last = ('尚未更新', '首次更新会生成完整备份')
            self.later(lambda: self.apply_overview(client, wiki, last))
        threading.Thread(target=work, daemon=True).start()

    def apply_overview(self, client, wiki, last):
        ok, value, sub = client
        self.overview['client'][0].configure(text=value, fg=GREEN if ok else RED)
        self.fit(self.overview['client'][1], sub)
        self.overview['wiki'][0].configure(text=wiki[0])
        self.fit(self.overview['wiki'][1], wiki[1])
        self.overview['last'][0].configure(text=last[0])
        self.fit(self.overview['last'][1], last[1])
        self.side_client.configure(text=('客户端已就绪' if ok else '未找到客户端 · 点此设置'), fg=MUTED if ok else RED,
                                   cursor='' if ok else 'hand2')
        self.fit(self.client_state, f'✓  已识别客户端：{sub}' if ok else
                 '⚠  这个目录里没有找到游戏客户端，请重新选择或点「自动识别」。')
        self.client_state.configure(fg=GREEN if ok else RED)

    # -- plumbing -----------------------------------------------------------------
    def pump(self):
        try:
            for _ in range(400):
                kind, *payload = self.messages.get_nowait()
                if kind == 'log':
                    payload[0].append(payload[1])
                elif kind == 'progress':
                    self.show_progress(payload[0])
                elif kind == 'wikistep':
                    self.wiki_step.set(payload[0])
                    self.set_bar(None if len(payload) > 1 and payload[1] else 0, 1)
                elif kind == 'wikiprog':
                    text, done, total = payload
                    self.wiki_step.set(text)
                    self.set_bar(done, total)
                elif kind == 'stepstate':
                    key, index, state, note = payload
                    self.steppers[key].set(index, state, note)
                elif kind == 'call':
                    payload[0]()
        except queue.Empty:
            pass
        if self.busy and self.busy_since:
            self.elapsed.set(f'已用时 {clock(time.monotonic() - self.busy_since)}')
            self.busy_dot.configure(fg=GOLD if int(time.monotonic() * 2) % 2 else '#d9c39d')
        self.after(100, self.pump)

    def set_bar(self, done, total):
        """done=None: indeterminate (busy, unknown length); otherwise determinate."""
        if done is None:
            if str(self.wiki_bar.cget('mode')) != 'indeterminate':
                self.wiki_bar.configure(mode='indeterminate')
                self.wiki_bar.start(18)
            return
        self.wiki_bar.stop()
        self.wiki_bar.configure(mode='determinate', value=int(done / total * 1000) if total else 0)

    def later(self, fn):
        self.messages.put(('call', fn))

    def log_to(self, panel):
        return lambda text: self.messages.put(('log', panel, text if text.endswith('\n') else text + '\n'))

    def mark(self, index, state, note=None, key='wiki'):
        self.messages.put(('stepstate', key, index, state, note))

    def remember(self):
        save(game=self.game.get(), archive=self.archive.get(), workers=int(self.workers.get() or default_workers()),
             organise=bool(self.organise.get()), categories=[k for k, v in self.categories.items() if v.get()])

    def choose_game(self):
        folder = filedialog.askdirectory(initialdir=self.game.get() or str(ROOT), title='选择游戏客户端目录')
        if folder:
            self.game.set(folder)
            self.commit_paths()

    def choose_archive(self):
        folder = filedialog.askdirectory(initialdir=self.archive.get() or str(OUTPUT), title='选择资源归档目录')
        if folder:
            self.archive.set(folder)
            self.commit_paths(archive=True)

    def detect(self):
        for base in (self.game.get(), r'C:\Game\SwordofConvallaria\SoCLauncher', r'D:\Game\SwordofConvallaria\SoCLauncher'):
            if not base:
                continue
            try:
                root = locate(base)
            except ValueError:
                continue
            self.game.set(str(root))
            self.commit_paths()
            self.status.set('已识别客户端')
            return
        messagebox.showwarning('未找到客户端', '没有在常见位置找到游戏客户端，请点「选择…」手动指定目录。')

    def open_folder(self, folder):
        folder = Path(folder)
        if not folder.exists():
            messagebox.showinfo('目录还不存在', f'{folder}\n\n还没有生成，先完成一次相应的操作。')
            return
        if os.name == 'nt':
            subprocess.Popen(['explorer', str(folder)])

    def open_wiki(self):
        webbrowser.open((ROOT / 'index.html').as_uri())

    def open_update_report(self):
        report = OUTPUT / 'update-report.md'
        if report.is_file() and os.name == 'nt':
            os.startfile(report)
        else:
            messagebox.showinfo('还没有更新报告', '完成一次「开始更新」或「预览变更」后会生成报告。')

    def set_busy(self, on):
        for widget in self.actions:
            widget.configure(state='disabled' if on else 'normal')
        if not on:
            self.busy_dot.configure(fg=GREEN)

    def close(self):
        if self.busy and not messagebox.askyesno('仍在进行', f'「{self.busy}」还没有完成，现在退出会中断它。\n\n确定退出吗？'):
            return
        if self.cancel:
            self.cancel.set()
        if self.server:
            try:
                self.server.shutdown()
            except OSError:
                pass
        self.destroy()

    def thread(self, label, job, on_done=None, box=None):
        if self.busy:
            messagebox.showinfo('请稍候', f'「{self.busy}」还在进行中，完成后再试。')
            return False
        self.busy = label
        self.busy_since = time.monotonic()
        self.status.set(label + '…')
        self.set_busy(True)
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
                        self.elapsed.set(f'{self.busy}用时 {clock(time.monotonic() - self.busy_since)}')
                    self.busy = None
                    self.busy_since = None
                    self.status.set('就绪')
                    self.set_busy(False)
                    if on_done:
                        on_done(result)
                self.later(finish)

        threading.Thread(target=target, daemon=True).start()
        return True

    # -- archive ------------------------------------------------------------------
    def start_scan(self):
        categories = [k for k, v in self.categories.items() if v.get()]
        if not categories:
            messagebox.showwarning('没有选择分类', '至少勾选一个要解析的分类。')
            return
        self.remember()
        self.cancel = threading.Event()
        self.archive_stepper.reset()
        self.bar.configure(value=0)
        self.line1.set('正在准备…')
        self.line2.set('')
        log = self.log_to(self.archive_log)
        log(f"—— {time.strftime('%Y-%m-%d %H:%M:%S')} 开始解析 ——")
        game, archive, workers = self.game.get(), self.archive.get(), int(self.workers.get() or default_workers())
        organise = bool(self.organise.get())
        cancel = self.cancel

        def job():
            from socdecode.archive.scan import scan
            return scan(game, archive, workers=workers, categories=categories, organise=organise, log=log,
                        progress=lambda event: self.messages.put(('progress', event)), cancel=cancel)

        def done(result):
            self.cancel_button.configure(state='disabled')
            self.refresh_versions()
            if not result:
                stopped = cancel.is_set()
                self.archive_stepper.finish_active('skip' if stopped else 'error')
                self.line1.set('已停止，已完成的部分下次会直接复用。' if stopped else '解析没有完成，原因见下方日志。')
                if not stopped:
                    self.archive_log.show()
                return
            self.archive_stepper.set_all(['done'] * len(STAGES))
            self.bar.configure(value=1000)
            if result['status'] == 'unchanged':
                self.line1.set(f"与上一版本一致（{result['label']}），没有生成新版本 · 用时 {clock(result['seconds'])}")
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

        if self.thread('解析资源', job, done, self.archive_log):
            self.cancel_button.configure(state='normal')

    def cancel_scan(self):
        if self.cancel:
            self.cancel.set()
            self.status.set('正在取消…')
            self.line1.set('正在取消，等待进行中的文件完成…')

    def show_progress(self, event):
        keys = [key for key, _ in STAGES]
        current = keys.index(event['stage']) if event['stage'] in keys else 0
        self.archive_stepper.set_all(['done' if i < current else 'active' if i == current else 'pending'
                                      for i in range(len(keys))])
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
        for row, meta in enumerate(reversed(versions)):
            c, s = meta.get('changes', {}), meta.get('sourceChanges', {})
            first = not meta.get('parent')
            self.tree.insert('', 'end', iid=meta['id'], tags=('odd',) if row % 2 else (), values=(
                meta['label'], meta.get('game', {}).get('changeNumber') or '-', f"{meta['entries']:,}", size_text(meta['bytes']),
                '首个版本' if first else f"{c.get('added', 0):,}", '' if first else f"{c.get('modified', 0):,}",
                '' if first else f"{c.get('removed', 0):,}", '' if first else f"{c.get('renamed', 0):,}",
                '' if first else f"{sum(s.values()):,}", clock(meta.get('durationSeconds'))))
        if versions:
            self.versions_empty.place_forget()
        else:
            self.versions_empty.place(relx=0.5, rely=0.45, anchor='center')
        self.usage.set(f'{len(versions)} 个版本')
        root = self.archive.get()

        def measure():
            used = Store(root).disk_usage()
            self.later(lambda: self.usage.set(f'{len(versions)} 个版本 · 归档占用 {size_text(used)}'))
        threading.Thread(target=measure, daemon=True).start()

    def selected(self):
        versions = {v['id']: v for v in self.store().index()}
        return [versions[i] for i in sorted(self.tree.selection()) if i in versions]

    def need_selection(self, count=1):
        chosen = self.selected()
        if len(chosen) < count:
            messagebox.showinfo('先选择版本', '先在列表里选中一个版本。' if count == 1 else '按住 Ctrl 选中任意两个版本。')
            return None
        return chosen

    def show_version(self):
        chosen = self.selected()
        if not chosen:
            return
        meta = chosen[-1]
        store = self.store()
        changes = store.changes(meta['id']) or {}
        lines = [f"资源 {meta['entries']:,} 项 · {size_text(meta['bytes'])} · 客户端文件 {meta.get('sources', 0):,} 个 · 解析用时 {clock(meta.get('durationSeconds'))}",
                 '分类：' + '，'.join(f"{dict(CATEGORIES).get(k, k)} {v['n']:,}" for k, v in meta.get('counts', {}).items())]
        summary = changes.get('summary') or {}
        if meta.get('parent') and summary:
            lines.append(f"相比上一版本 {meta['parent']}：")
            for key, value in summary.get('categories', {}).items():
                counts = value['counts']
                lines.append(f"    {dict(CATEGORIES).get(key, key)}：新增 {counts['added']:,} · 修改 {counts['modified']:,} · "
                             f"删除 {counts['removed']:,} · 改名 {counts['renamed']:,}")
        if changes.get('errors'):
            lines.append(f"未能解析的对象 {len(changes['errors'])} 个，例如：{changes['errors'][0]}")
        title = f"版本 {meta['label']} · 游戏资源版本 {meta.get('game', {}).get('changeNumber') or '未知'}"
        if len(chosen) == 2:
            title = f"已选两个版本：{chosen[0]['label']} 与 {chosen[1]['label']} —— 点「比较所选两个」查看差分"
        self.version_info.configure(state='normal', fg=INK)
        self.version_info.delete('1.0', 'end')
        self.version_info.insert('end', title + '\n', ('title',))
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
            self.status.set('资源浏览器已打开')
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
        chosen = self.need_selection()
        if chosen:
            self.open_viewer(f"v={chosen[-1]['id']}")

    def compare_previous(self):
        chosen = self.need_selection()
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
        chosen = self.need_selection()
        if chosen and os.name == 'nt':
            report = self.store().versions_dir / chosen[-1]['id'] / 'report.md'
            if report.is_file():
                os.startfile(report)

    def export_selected(self):
        chosen = self.need_selection()
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
        chosen = self.need_selection()
        if not chosen or not messagebox.askyesno('删除版本', '删除所选的 %d 个版本记录？\n资源文件要在「清理未引用的文件」后才会释放。' % len(chosen)):
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
            self.later(lambda: messagebox.showinfo('清理完成', f'已清理 {files:,} 个文件，释放 {size_text(freed)}。'))
        self.thread('清理未引用文件', job, lambda _: self.refresh_versions())

    # -- wiki: shared ----------------------------------------------------------------
    def wiki_job(self, label, job, context=()):
        """Run ``job`` on a worker; every line goes to the GUI log and to output/logs/<time>-<label>.log."""
        if self.busy:
            messagebox.showinfo('请稍候', f'「{self.busy}」还在进行中，完成后再试。')
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
        self.hide_result()
        self.wiki_step.set(f'「{label}」进行中…')
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
                self.later(lambda: self.wiki_stepper.finish_active('error'))
                self.messages.put(('wikistep', f'「{label}」没有完成：{error}', False))
                self.post_result(f'「{label}」没有完成', note=f'{type(error).__name__}：{error}\n详细信息已展开在下方运行日志中。',
                                 actions=(('打开日志文件', self.open_last_log),), tone='error')
                self.later(self.wiki_log.show)
            finally:
                sys.stdout, sys.stderr = original
                try:
                    stream.close()
                except OSError:
                    pass
        if not self.thread(label, wrapped, lambda _: self.refresh_overview(), self.wiki_log):
            stream.close()

    def open_last_log(self):
        if self.last_log and Path(self.last_log).is_file() and os.name == 'nt':
            os.startfile(self.last_log)
        else:
            self.open_folder(OUTPUT / 'logs')

    def progress(self, message, done=None, total=None):
        """Progress callback for worker code: updates the label/bar and logs a timestamped line."""
        self.messages.put(('wikiprog', message, done, total))
        print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)

    def step(self, text, busy=True):
        self.messages.put(('wikistep', text, busy))
        print(f"[{time.strftime('%H:%M:%S')}] {text}", flush=True)

    def hide_result(self):
        if self.result_outer.winfo_ismapped():
            self.result_outer.pack_forget()

    def post_result(self, title, tiles=(), note='', actions=(), tone='ok'):
        self.later(lambda: self.show_result(title, tiles, note, actions, tone))

    def show_result(self, title, tiles=(), note='', actions=(), tone='ok'):
        for child in self.result_inner.winfo_children():
            child.destroy()
        colour = {'ok': GREEN, 'info': GREEN, 'warn': GOLD, 'error': RED}[tone]
        icon = {'ok': 'check', 'info': 'info', 'warn': 'warning', 'error': 'error'}[tone]
        self.result_accent.configure(bg=colour)
        head = tk.Frame(self.result_inner, bg=SURFACE)
        head.pack(fill='x')
        self.icon_label(head, icon, size=13, fg=colour).pack(side='left')
        self.label(head, title, 12, 'bold').pack(side='left', padx=(S(10), 0))
        self.link(head, '关闭', self.hide_result, size=9, fg=MUTED).pack(side='right')
        if tiles:
            row = tk.Frame(self.result_inner, bg=SURFACE)
            row.pack(fill='x', pady=(S(16), 0))
            for index, (value, label) in enumerate(tiles):
                row.columnconfigure(index, weight=1, uniform='result')
                cell = tk.Frame(row, bg=SURFACE_ALT)
                cell.grid(row=0, column=index, sticky='nsew', padx=(0 if index == 0 else S(10), 0))
                self.label(cell, number(value), 18, 'bold', bg=SURFACE_ALT, font=self.serif).pack(anchor='w', padx=S(14), pady=(S(10), 0))
                self.label(cell, label, 9, fg=MUTED, bg=SURFACE_ALT).pack(anchor='w', padx=S(14), pady=(0, S(10)))
        if note:
            text = self.label(self.result_inner, note, 9, fg=MUTED, justify='left', anchor='w')
            text.pack(fill='x', pady=(S(14), 0))
            self.wrap(text, self.result_inner)
        if actions:
            row = tk.Frame(self.result_inner, bg=SURFACE)
            row.pack(fill='x', pady=(S(16), 0))
            for index, (text, action) in enumerate(actions):
                style = 'Primary.TButton' if index == 0 else 'Danger.TButton' if '回滚' in text else 'Secondary.TButton'
                ttk.Button(row, text=text, style=style, command=action).pack(side='left', padx=(0, S(10)))
        if not self.result_outer.winfo_ismapped():
            self.result_outer.pack(fill='x', padx=S(36), pady=(0, S(18)), after=self.progress_outer)

    # -- wiki: client data -------------------------------------------------------------
    def do_extract(self, game, force=False):
        """Read the client configuration; returns (game, snapshot)."""
        argv = ['extract', '--game', game, '--output', str(OUTPUT)] + (['--force-extract'] if force else [])
        return cli.extract(cli.parser().parse_args(argv), progress=lambda msg: self.progress(msg))

    def set_pulled(self, game, snapshot):
        fp = snapshot['client']['fingerprint']
        label = f"{snapshot['extractedAt'][:19].replace('T', ' ')} · {fp[:12]} · {len(snapshot['characters'])} 位角色"
        self.pulls[fp] = (label, str(game), snapshot)
        (OUTPUT / 'pulls').mkdir(parents=True, exist_ok=True)
        (OUTPUT / 'pulls' / (fp + '.json')).write_text(
            json.dumps(snapshot, ensure_ascii=False, separators=(',', ':')), 'utf8')
        self.later(self.safe_refresh_pulls)

    def safe_refresh_pulls(self, select=None):
        try:
            self.refresh_pulls(select)
        except Exception:
            self.wiki_log.append('读取已保存的客户端版本失败：\n' + traceback.format_exc())

    def selected_fingerprint(self):
        index = self.source_box.current()
        return self.pull_items[index - 1][0] if 0 < index <= len(self.pull_items) else None

    def refresh_pulls(self, select=None):
        keep = select or self.selected_fingerprint()
        try:
            default_game = str(game_root(Path(self.game.get())))
        except (ValueError, OSError):
            default_game = str(self.game.get())
        found = {}
        pulls_dir = OUTPUT / 'pulls'
        candidates = sorted(pulls_dir.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True) \
            if pulls_dir.is_dir() else []
        current = OUTPUT / 'client-data.json'
        if current.is_file():
            candidates.insert(0, current)
        for path in candidates:
            try:
                snap = json.loads(path.read_text('utf8'))
            except (OSError, ValueError):
                continue
            fp = snap.get('client', {}).get('fingerprint') or path.stem
            if fp in found:
                continue
            game = str(snap.get('client', {}).get('game') or default_game)
            label = f"{snap['extractedAt'][:19].replace('T', ' ')} · {fp[:12]} · {len(snap['characters'])} 位角色"
            found[fp] = (label, game, snap)
        for fp, value in self.pulls.items():
            found.setdefault(fp, value)
        ordered = sorted(found.items(), key=lambda kv: kv[1][0], reverse=True)
        self.pulls = dict(ordered)
        self.pull_items = ordered
        self.source_box['values'] = [AUTO_SOURCE] + [value[0] for _, value in ordered]
        index = next((i for i, (fp, _) in enumerate(ordered, 1) if keep and (fp == keep or fp.startswith(keep))), 0)
        self.source_box.current(index)

    def current_pull(self):
        """The chosen saved version as (game, snapshot), or None for 'read the client now'."""
        fp = self.selected_fingerprint()
        if not fp:
            return None
        _, game, snapshot = self.pulls[fp]
        return game, snapshot

    def context(self, chosen=None):
        lines = [f'数据来源：{self.source.get()}', f'资料馆：{ROOT}', f'客户端：{self.game.get()}',
                 f"方式：{'全覆盖' if self.mode.get() == 'full' else '差量更新'} · 重建索引：{'是' if self.rebuild.get() else '否'}"]
        if chosen:
            lines.append(f'解析用客户端目录：{chosen[0]}')
        return lines

    def snapshot_for(self, chosen, game, force):
        """Worker side: the chosen saved version, or a fresh (usually cached) read of the client."""
        if chosen:
            return chosen
        self.step('正在读取客户端配置表（客户端没有变化时直接复用缓存）…')
        game, snapshot = self.do_extract(game, force)
        self.set_pulled(game, snapshot)
        return game, snapshot

    # -- wiki: main flow -----------------------------------------------------------------
    def run_script(self, name, *args):
        """Run one of the client-extraction scripts and stream its output to the log."""
        path = HERE / name
        if not path.is_file():
            raise FileNotFoundError(f'缺少脚本：{path}')
        print(f'  运行 {name} …')
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
        python = sys.executable
        if python.lower().endswith('pythonw.exe'):
            console = python[:-len('pythonw.exe')] + 'python.exe'
            python = console if Path(console).is_file() else python
        proc = subprocess.Popen([python, '-X', 'utf8', str(path), *map(str, args)],
                                cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding='utf-8', errors='replace', creationflags=flags)
        lines = []
        for line in proc.stdout or ():
            text = '  ' + line.rstrip()
            print(text)
            lines.append(text)
        if proc.wait() != 0:
            raise RuntimeError(f'{name} 执行失败（退出码 {proc.returncode}）')
        return lines

    def refresh_media(self, media=True, voices=False, force=False):
        """Regenerate data the wiki pages themselves do not contain (sprite frames,
        expression sheets, voice lines and the panel calculator's numbers).
        Returns the labels of the parts that failed; optional skips go to
        ``self.media_notes`` so they are reported without marking the step red."""
        failed = []
        self.media_notes = []
        if media:
            for label, name in self.MEDIA_SCRIPTS:
                print(f'  · {label}（{name}）')
                try:
                    # --force disables the "bundled resources already complete"
                    # shortcut so a rebuilt client is picked up faithfully.
                    self.run_script(name, *(('--force',) if force and name == 'extract_art.py' else ()))
                except Exception as error:      # noqa: BLE001 - keep the update usable
                    print(f'  {label}提取失败（可稍后重试）：{error}')
                    failed.append(label)
        if voices:
            print('  · 角色语音（extract_voices.py，耗时较长）')
            try:
                output = self.run_script('extract_voices.py') or []
                skipped = next((line.strip() for line in output if '跳过角色语音提取' in line), None)
                if skipped:
                    # Voice lines are optional. Missing decoder / client is a
                    # skip, not a broken update.
                    self.media_notes.append(skipped + '（详情见运行日志）')
                else:
                    from socdecode.rebuild import rebuild_voices
                    rebuild_voices(print)
            except Exception as error:        # noqa: BLE001
                print(f'  角色语音提取失败（可稍后重试）：{error}')
                failed.append('角色语音')
        print('  客户端衍生资源提取结束。')
        return failed

    def start_update(self):
        if self.busy:
            messagebox.showinfo('请稍候', f'「{self.busy}」还在进行中，完成后再试。')
            return
        if self.mode.get() == 'full' and not messagebox.askyesno(
                '确认全覆盖', '全覆盖会按客户端数据重新生成全部已收录角色，覆盖你之前改过的字段（攻略与署名保留，写入前会备份）。\n\n继续吗？'):
            return
        chosen = self.current_pull()
        game, force = self.game.get(), bool(self.force_extract.get())
        refresh, rebuild = self.mode.get() == 'full', bool(self.rebuild.get())
        media, voices = bool(self.media.get()), bool(self.voices.get())
        self.remember_wiki()
        self.wiki_stepper.reset()
        self.media_notes = []
        mark = self.mark

        def job():
            started = time.monotonic()
            mark(0, 'active')
            game_dir, snapshot = self.snapshot_for(chosen, game, force)
            # 客户端已启用、只是开放时间还没到的角色也要收录：配置是完整的，
            # 只是还没上线（新角色常常提前进包）。只有 enable=0 的废案才跳过。
            names = [c['name'] for c in snapshot['characters'] if c.get('enabled', True)]
            upcoming = [c['name'] for c in snapshot['characters'] if c.get('enabled', True) and not c.get('available')]
            mark(0, 'done', f"{len(snapshot['characters'])} 位角色")
            if not names:
                mark(1, 'error')
                self.step('这个版本没有可更新的角色，客户端配置可能不完整。', False)
                self.post_result('没有可更新的角色', note='客户端配置可能不完整。请在「更多选项」里勾选「强制重新解析客户端」后重试。', tone='warn')
                return
            mark(1, 'active')
            self.step(f'正在生成 {len(names)} 位角色的页面（约需数分钟）…')
            files, expected, report = plan_update(ROOT, Path(game_dir), snapshot, names, False, refresh, 'base',
                                                  progress=self.progress)
            pages = sum(1 for f in report['files'] if f['path'].startswith('data/pages/'))
            images = sum(1 for f in report['files'] if f['path'].startswith('assets/'))
            mark(1, 'done', f'{pages:,} 个页面')
            mark(2, 'active')
            self.step('正在写入资料馆（写入前先备份）…')
            backup = apply(ROOT, files, expected, OUTPUT / 'backups', progress=self.progress)
            (OUTPUT / 'update-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf8')
            (OUTPUT / 'update-report.md').write_text(cli.report_markdown(report), 'utf8')
            if backup:
                (backup / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf8')
                (backup / 'report.md').write_text(cli.report_markdown(report), 'utf8')
                (OUTPUT / 'last-backup.txt').write_text(str(backup), 'utf8')
                print(f'备份：{backup}')
            mark(2, 'done', '已备份' if backup else '无需改动')
            index_error = None
            if rebuild and backup:
                mark(3, 'active')
                self.step('正在重建搜索索引与一图流数据…')
                try:
                    rebuild_wiki(print)
                    mark(3, 'done')
                except Exception as error:      # noqa: BLE001 - pages are already written
                    index_error = error
                    print('重建索引出错（data/ 与 assets/ 已写入，可稍后重试）：', error)
                    mark(3, 'error', '失败')
            else:
                mark(3, 'skip', '已跳过' if not rebuild else '无需重建')
            failed = []
            if media or voices:
                mark(4, 'active')
                self.step('正在提取像素动作、立绘表情与局外面板数值…')
                failed = self.refresh_media(media, voices, force)
                mark(4, 'error' if failed else 'done', f'{len(failed)} 项失败' if failed else None)
            else:
                mark(4, 'skip', '已跳过')
            took = clock(time.monotonic() - started)
            notes, tone = [], 'ok'
            notes.append(f'备份位置：{backup}' if backup else '客户端数据与资料馆一致，没有需要写入的文件。')
            if index_error:
                tone = 'warn'
                notes.append(f'重建索引失败：{index_error}。页面已写入，可稍后重试。')
            if failed:
                tone = 'warn'
                notes.append('以下衍生资源提取失败：' + '、'.join(failed) + '，详见运行日志。')
            for note in getattr(self, 'media_notes', []):
                tone = 'warn'
                notes.append(note)
            if upcoming:
                notes.append(f'其中 {len(upcoming)} 位角色尚未开放，已按客户端配置提前收录。')
            self.step(f'更新完成，用时 {took}。', False)
            actions = [('在浏览器中打开资料馆', self.open_wiki), ('查看更新报告', self.open_update_report)]
            if backup:
                actions.append(('回滚本次更新', self.rollback))
            self.post_result('资料馆已更新' if backup else '资料馆已是最新',
                             tiles=((len(report['characters']), '角色'), (pages, '页面'), (images, '图片'),
                                    (len(report['conflicts']), '字段差异'), (len(report['missingAssets']), '缺失原资源')),
                             note='\n'.join(notes), actions=actions, tone=tone)
            for name in upcoming:
                print('  尚未开放（已按客户端配置收录）：' + name)
            for line in cli.missing_lines(report['missingAssets']):
                print('  ' + line)
            print(f"报告：{OUTPUT / 'update-report.md'}")
        self.wiki_job('更新资料馆', job, self.context(chosen))

    # Kept for scripts that drive the old button name.
    update_wiki = start_update

    # -- wiki: other actions -----------------------------------------------------------
    def pull(self):
        game, force = self.game.get(), bool(self.force_extract.get())

        def job():
            self.step('正在读取客户端配置表…')
            game_dir, snapshot = self.do_extract(game, force)
            self.set_pulled(game_dir, snapshot)
            self.step('客户端读取完成。', False)
            self.post_result('已读取客户端', tiles=((len(snapshot['characters']), '角色'), (len(snapshot['skills']), '技能'),
                                                (len(snapshot['statuses']), '关联词条')),
                             note='已保存为一个版本，可在「数据来源」中选择。', tone='info')
        self.wiki_job('读取客户端', job)

    def missing_characters(self, snapshot):
        have = cli.wiki_names(ROOT)
        counts = {}
        for char in snapshot['characters']:
            counts[char['name']] = counts.get(char['name'], 0) + 1
        return have, counts

    def check(self):
        chosen, game, force = self.current_pull(), self.game.get(), bool(self.force_extract.get())

        def job():
            _, snapshot = self.snapshot_for(chosen, game, force)
            self.step('正在比对已收录角色…')
            have, counts = self.missing_characters(snapshot)
            missing = [c for c in snapshot['characters'] if c['name'] not in have]
            print(f"客户端共 {len(snapshot['characters'])} 个成长配置完整的角色；"
                  f"资料馆已收录 {len(have)} 个；客户端有而资料馆缺 {len(missing)} 个。")
            for char in sorted(missing, key=lambda c: c['name']):
                print(f"  缺：{char['name']}（{'同名重复' if counts[char['name']] > 1 else char['rarity']}）")
            names = sorted({c['name'] for c in missing})
            self.step(f'检查完成：资料馆缺 {len(names)} 位客户端角色。', False)
            note = '、'.join(names[:40]) + (f' 等 {len(names)} 位' if len(names) > 40 else '') if names else '资料馆已收录客户端里的全部角色。'
            self.post_result(f'发现 {len(names)} 位新角色' if names else '没有新角色',
                             tiles=((len(snapshot['characters']), '客户端角色'), (len(have), '资料馆已收录'), (len(names), '待补录')),
                             note=note, actions=(('补充这些角色', self.add_new),) if names else (), tone='info')
        self.wiki_job('检查新角色', job)

    def add_new(self):
        """Import the characters the client has and the wiki does not."""
        chosen, game, force = self.current_pull(), self.game.get(), bool(self.force_extract.get())
        refresh, rebuild = self.mode.get() == 'full', bool(self.rebuild.get())

        def job():
            game_dir, snapshot = self.snapshot_for(chosen, game, force)
            self.step('正在比对已收录角色…')
            have, counts = self.missing_characters(snapshot)
            missing = [c['name'] for c in snapshot['characters'] if c['name'] not in have and c.get('enabled', True)]
            names = [name for name in dict.fromkeys(missing) if counts[name] == 1]
            ambiguous = [name for name in dict.fromkeys(missing) if counts[name] > 1]
            for name in ambiguous:
                print(f'  跳过：{name}（客户端有多个同名角色，需先用命令行指定完整名称）')
            if not names:
                self.step('资料馆已收录客户端全部角色，没有需要补录的新角色。', False)
                self.post_result('没有需要补录的角色', note='资料馆已收录客户端里的全部角色。', tone='info')
                return
            upcoming = [c['name'] for c in snapshot['characters'] if c['name'] in names and not c.get('available')]
            print(f'待补录 {len(names)} 个角色：' + '、'.join(names))
            for name in upcoming:
                print(f'  尚未开放（已按客户端配置收录）：{name}')
            args = argparse.Namespace(character=names, wiki=ROOT, output=OUTPUT, refresh=refresh, sprite_variant='base',
                                      dry_run=False, no_rebuild=not rebuild)
            self.step(f'正在导入 {len(names)} 位新角色（先备份，耗时数分钟）…')
            cli.add_character(args, Path(game_dir), snapshot)
            self.step(f'补录完成：{len(names)} 位新角色已写入资料馆。', False)
            note = '、'.join(names)
            if ambiguous:
                note += f'\n跳过 {len(ambiguous)} 位同名角色（需要用命令行指定完整名称）：' + '、'.join(ambiguous)
            self.post_result(f'已补录 {len(names)} 位新角色', note=note,
                             actions=(('在浏览器中打开资料馆', self.open_wiki), ('回滚本次更新', self.rollback)))
        self.wiki_job('补充新角色', job, self.context(chosen))

    def preview(self):
        chosen, game, force = self.current_pull(), self.game.get(), bool(self.force_extract.get())
        refresh = self.mode.get() == 'full'

        def job():
            game_dir, snapshot = self.snapshot_for(chosen, game, force)
            self.step('正在生成预览（不写入）…')
            names = [c['name'] for c in snapshot['characters'] if c.get('enabled', True)]
            if not names:
                self.step('这个版本没有可更新的角色。', False)
                self.post_result('没有可更新的角色', note='客户端配置可能不完整。', tone='warn')
                return
            files, expected, report = plan_update(ROOT, Path(game_dir), snapshot, names, False, refresh, 'base',
                                                  progress=self.progress)
            pages = sum(1 for f in report['files'] if f['path'].startswith('data/pages/'))
            images = sum(1 for f in report['files'] if f['path'].startswith('assets/'))
            print(f"预览：将更新 {len(report['characters'])} 个角色 · 页面 {pages} 个 · 图片 {images} 张 · "
                  f"字段差异 {len(report['conflicts'])} · 缺失原资源 {len(report['missingAssets'])}")
            print('预览完成，资料馆未写入。')
            self.step('预览完成，资料馆没有被改动。', False)
            self.post_result('预览：一次更新会改动这些内容',
                             tiles=((len(report['characters']), '角色'), (pages, '页面'), (images, '图片'),
                                    (len(report['conflicts']), '字段差异'), (len(report['missingAssets']), '缺失原资源')),
                             note=f"按「{'全覆盖' if refresh else '差量更新'}」计算，资料馆没有被改动。确认无误后点「开始更新」。",
                             actions=(('开始更新', self.start_update),), tone='info')
        self.wiki_job('预览变更', job, self.context(chosen))

    def rollback(self):
        folder = last_backup()
        if not folder or not folder.exists():
            messagebox.showinfo('没有可回滚的更新', '还没有可回滚的备份。完成一次更新后才能回滚。')
            return
        if not messagebox.askyesno('回滚上次更新', f'把资料馆恢复到上次更新之前？\n\n备份：{folder}'):
            return
        rebuild = bool(self.rebuild.get())

        def job():
            self.step('正在回滚上次更新…')
            cli.main(['rollback', str(folder)] + ([] if rebuild else ['--no-rebuild']))
            self.step('回滚完成。', False)
            self.post_result('已回滚上次更新', note=f'已从备份恢复：{folder}', tone='info',
                             actions=(('在浏览器中打开资料馆', self.open_wiki),))
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
    enable_dpi_awareness()
    try:
        app = App()
    except Exception:
        # Started without a console (pythonw / the packaged exe): say what went wrong.
        detail = traceback.format_exc()
        try:
            OUTPUT.mkdir(parents=True, exist_ok=True)
            (OUTPUT / 'client-update.log').open('a', encoding='utf-8').write(detail)
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror('本地更新工具无法启动', detail[-1500:])
            root.destroy()
        except Exception:
            pass
        raise
    app.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(launch())
