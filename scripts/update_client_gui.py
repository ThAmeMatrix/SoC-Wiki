"""Windows interface for the local client update.

Choose the installed game directory once, then pull characters, skills, traits
and exclusive weapons into this offline wiki with one click. Packaged as
``SoCwiki本地更新.exe`` by ``scripts/build_client_updater.py``.
"""
from __future__ import annotations

import io
import queue
import sys
import threading
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import tkinter as tk  # noqa: E402
from tkinter import filedialog, messagebox, scrolledtext, ttk  # noqa: E402

from socdecode import cli  # noqa: E402
from socdecode.config import OUTPUT, ROOT, game_path, last_backup, save  # noqa: E402


class QueueWriter(io.TextIOBase):
    def __init__(self, sink):
        self.sink = sink

    def write(self, text):
        if text:
            self.sink(text)
        return len(text)

    def flush(self):
        return None


class Updater(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('SoCwiki 本地更新')
        self.geometry('820x620')
        self.minsize(720, 520)
        self.messages = queue.Queue()
        self.running = False
        self.game = tk.StringVar(value=str(game_path()))
        self.mode = tk.StringVar(value='diff')
        self.rebuild = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value='就绪')
        self.build()
        self.pump()

    def build(self):
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='从本机安装的铃兰之剑客户端读取资料，写入这个离线资料馆。',
                  wraplength=760).pack(anchor='w')
        ttk.Label(frame, text=f'资料馆：{ROOT}', foreground='#557').pack(anchor='w', pady=(2, 8))

        row = ttk.Frame(frame)
        row.pack(fill='x')
        ttk.Label(row, text='客户端目录').pack(side='left')
        entry = ttk.Entry(row, textvariable=self.game)
        entry.pack(side='left', fill='x', expand=True, padx=6)
        ttk.Button(row, text='选择…', command=self.choose).pack(side='left')
        ttk.Button(row, text='自动识别', command=self.detect).pack(side='left', padx=(6, 0))

        modes = ttk.LabelFrame(frame, text='更新方式', padding=8)
        modes.pack(fill='x', pady=(10, 6))
        ttk.Radiobutton(modes, text='差量更新（只补缺失内容与客户端新增角色；冲突以本地为准）',
                        value='diff', variable=self.mode).pack(anchor='w')
        ttk.Radiobutton(modes, text='全覆盖（已匹配角色全部按客户端重算并覆盖；攻略、署名与备份保留）',
                        value='full', variable=self.mode).pack(anchor='w')
        ttk.Checkbutton(frame, text='更新后重建搜索索引与一图流数据（推荐）',
                        variable=self.rebuild).pack(anchor='w', pady=(0, 8))

        buttons = ttk.Frame(frame)
        buttons.pack(fill='x')
        self.buttons = {}
        for key, (label, action) in {
            'check': ('检查新角色', self.check),
            'preview': ('预览差异', self.preview),
            'run': ('一键拉取并更新', self.run_update),
            'rollback': ('回滚上次更新', self.rollback),
        }.items():
            button = ttk.Button(buttons, text=label, command=action)
            button.pack(side='left', padx=(0, 6))
            self.buttons[key] = button

        self.log = scrolledtext.ScrolledText(frame, height=18, wrap='word', font=('Consolas', 10))
        self.log.pack(fill='both', expand=True, pady=(10, 6))
        self.log.configure(state='disabled')
        ttk.Label(frame, textvariable=self.status).pack(anchor='w')

    # -- helpers ---------------------------------------------------------
    def append(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', text)
        self.log.see('end')
        self.log.configure(state='disabled')

    def pump(self):
        try:
            while True:
                self.append(self.messages.get_nowait())
        except queue.Empty:
            pass
        self.after(120, self.pump)

    def choose(self):
        folder = filedialog.askdirectory(initialdir=self.game.get() or str(ROOT), title='选择游戏客户端目录')
        if folder:
            self.game.set(folder)
            save(game=folder)

    def detect(self):
        candidates = [self.game.get(), r'C:\Game\SwordofConvallaria\SoCLauncher', str(ROOT)]
        for base in candidates:
            if not base:
                continue
            path = Path(base)
            for option in (path, path / 'SwordOfConvallaria', path / 'SoCLauncher' / 'SwordOfConvallaria'):
                if (option / 'assets/lua/lua_db.unity3d').is_file() and (option / 'SoC_Data/Plugins/x86_64/slua.dll').is_file():
                    self.game.set(str(option))
                    save(game=str(option))
                    self.append(f'已识别客户端：{option}\n')
                    return
        messagebox.showwarning('未找到客户端', '没有在常见位置找到游戏配置，请手动选择目录。')

    def worker(self, label, job):
        if self.running:
            return
        self.running = True
        for button in self.buttons.values():
            button.configure(state='disabled')
        self.status.set(label + '…')

        def target():
            writer = QueueWriter(lambda text: self.messages.put(text))
            original = sys.stdout
            sys.stdout = writer
            try:
                job()
                self.messages.put(f'\n{label}完成。\n')
            except SystemExit as exit_code:
                self.messages.put(f'\n{label}结束（退出码 {exit_code.code}）。\n')
            except BaseException:
                self.messages.put('\n' + traceback.format_exc())
            finally:
                sys.stdout = original

        def finish():
            if self.running:
                self.running = False
                for button in self.buttons.values():
                    button.configure(state='normal')
                self.status.set('就绪')
            else:
                self.after(120, finish)

        threading.Thread(target=target, daemon=True).start()
        self.after(150, finish)

    def arguments(self, *extra):
        return [*extra, '--game', self.game.get(), '--output', str(OUTPUT), '--wiki', str(ROOT)]

    def snapshot(self):
        args = cli.parser().parse_args(self.arguments('characters', '--missing'))
        game, snap = cli.extract(args)
        have = cli.wiki_names(ROOT)
        names = list(dict.fromkeys(c['name'] for c in snap['characters'] if c['name'] not in have))
        return game, snap, names

    # -- actions ---------------------------------------------------------
    def check(self):
        self.worker('检查新角色', lambda: cli.main(self.arguments('characters', '--missing')))

    def preview(self):
        def job():
            game, snap, names = self.snapshot()
            if self.mode.get() == 'diff':
                if not names:
                    print('没有客户端新增的角色；可改用「全覆盖」刷新已收录角色。')
                    return
                argv = ['add']
                for name in names:
                    argv += ['--character', name]
                argv += ['--dry-run', '--refresh', '--game', str(game), '--output', str(OUTPUT), '--wiki', str(ROOT)]
                cli.main(argv)
            else:
                cli.main(self.arguments('plan', '--all', '--refresh'))
        self.worker('预览差异', job)

    def run_update(self):
        def job():
            game, snap, names = self.snapshot()
            if self.mode.get() == 'diff':
                if not names:
                    print('没有客户端新增的角色；可改用「全覆盖」刷新已收录角色。')
                    return
                argv = ['add']
                for name in names:
                    argv += ['--character', name]
                argv += ['--refresh', '--game', str(game), '--output', str(OUTPUT), '--wiki', str(ROOT)]
                argv += [] if self.rebuild.get() else ['--no-rebuild']
                cli.main(argv)
            else:
                argv = ['update', '--all', '--refresh', '--game', str(game), '--output', str(OUTPUT), '--wiki', str(ROOT)]
                argv += [] if self.rebuild.get() else ['--no-rebuild']
                cli.main(argv)
        self.worker('一键拉取并更新', job)

    def rollback(self):
        def job():
            folder = last_backup()
            if not folder:
                print('还没有可回滚的备份。')
                return
            argv = ['rollback', str(folder)]
            argv += [] if self.rebuild.get() else ['--no-rebuild']
            cli.main(argv)
        self.worker('回滚上次更新', job)


def launch():
    if len(sys.argv) > 1:
        sys.path.insert(0, str(HERE))
        from update_client import main_entry
        return main_entry(sys.argv[1:])
    Updater().mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(launch())
