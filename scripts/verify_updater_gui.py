"""Drive the real updater window through its flows without writing to the wiki.

    python -X utf8 scripts/verify_updater_gui.py

* 检查新角色 runs for real (reads the client through the cache, read-only).
* 开始更新 runs with plan_update / apply / the media scripts stubbed, into a
  temporary output folder, so the stepper, result card and log are exercised
  end to end without touching data/ or the real reports.
* The failure path and the media-script runner are checked as well.
"""
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import update_client_gui as gui  # noqa: E402

failures = []


def check(name, ok, detail=''):
    print(('PASS ' if ok else 'FAIL ') + name + (f' :: {detail}' if detail else ''), flush=True)
    if not ok:
        failures.append(name)


tmp = Path(tempfile.mkdtemp(prefix='socgui-'))
real_output = gui.OUTPUT
gui.OUTPUT = tmp
gui.messagebox.askyesno = lambda *a, **k: True
gui.messagebox.showinfo = lambda *a, **k: None
app = gui.App()
app.withdraw()
callback_errors = []
app.report_callback_exception = lambda kind, value, tb: callback_errors.append(f'{kind.__name__}: {value}')


def wait_idle(limit=180):
    end = time.time() + limit
    while time.time() < end:
        app.update()
        if not app.busy:
            # Let the queued finish/result callbacks run.
            for _ in range(20):
                app.update()
                time.sleep(0.02)
            return True
        time.sleep(0.05)
    return False


def result_title():
    labels = [w for w in app.result_inner.winfo_children()]
    texts = []
    for frame in labels:
        for child in frame.winfo_children():
            try:
                texts.append(child.cget('text'))
            except Exception:
                pass
    return ' | '.join(t for t in texts if t)


try:
    for _ in range(30):
        app.update()
        time.sleep(0.05)
    check('pages built', set(app.pages) == {'update', 'archive', 'versions', 'settings'}, ','.join(app.pages))
    for key in app.pages:
        app.show_page(key)
        app.update()
        shown = [k for k, p in app.pages.items() if p.winfo_manager()]
        check(f'page {key} shows alone', shown == [key], str(shown))
    app.show_page('update')
    check('source list has the auto entry', app.source_box['values'][0] == gui.AUTO_SOURCE,
          f"{len(app.source_box['values'])} entries")
    check('auto source means read the client', app.current_pull() is None)

    # 1) Real, read-only: check for new characters.
    app.check()
    check('check finished', wait_idle())
    check('check posted a result card', app.result_outer.winfo_ismapped(), result_title()[:120])
    check('check saved the client version', len(app.pull_items) >= 1, f'{len(app.pull_items)} saved versions')
    check('check wrote a log file', app.last_log is not None and Path(app.last_log).is_file())

    # 2) Full update flow with the heavy parts stubbed.
    snapshot = {'characters': [{'name': '甲', 'enabled': True, 'available': True},
                               {'name': '乙', 'enabled': True, 'available': False}],
                'skills': [], 'statuses': [], 'client': {'fingerprint': 'test'}, 'extractedAt': '2026-11-04T00:00:00'}
    report = {'characters': [{'name': '甲'}, {'name': '乙'}],
              'files': [{'path': 'data/pages/1.js'}, {'path': 'data/pages/2.js'}, {'path': 'assets/a.png'}],
              'conflicts': [1], 'missingAssets': [], 'clientVersion': {'change_number': 1}, 'changedFiles': 3,
              'newPages': [], 'fieldChanges': []}
    backup = tmp / 'backups' / 'b1'
    backup.mkdir(parents=True)
    gui.plan_update = lambda *a, **k: ([], {}, report)
    gui.apply = lambda *a, **k: backup
    gui.rebuild_wiki = lambda log=print: log('rebuilt (stub)')
    gui.cli.report_markdown = lambda r: '# stub'
    app.snapshot_for = lambda chosen, game, force: ('C:/game', snapshot)
    calls = []
    app.run_script = lambda name, *a: calls.append(name)
    app.start_update()
    check('update finished', wait_idle())
    states = app.wiki_stepper.states
    check('all five steps done', states == ['done'] * 5, str(states))
    check('step notes filled', app.wiki_stepper.notes[0] == '2 位角色' and app.wiki_stepper.notes[1] == '2 个页面',
          str(app.wiki_stepper.notes))
    check('media scripts ran in order',
          calls == ['extract_panel_data.py', 'extract_dialogues.py',
                    'extract_battle_rules.py'], str(calls))
    title = result_title()
    check('result says updated', '资料馆已更新' in title, title[:160])
    check('last-backup recorded', (tmp / 'last-backup.txt').read_text('utf8') == str(backup))
    check('update buttons re-enabled', str(app.update_button.cget('state')) == 'normal')

    # 3) Nothing to write: index step skipped, title says up to date.
    gui.apply = lambda *a, **k: None
    app.start_update()
    wait_idle()
    check('no-change run skips index', app.wiki_stepper.states[3] == 'skip', str(app.wiki_stepper.states))
    check('no-change title', '资料馆已是最新' in result_title(), result_title()[:120])

    # 4) Failure path: an exception marks the step red and opens the log.
    def boom(*a, **k):
        raise RuntimeError('模拟的失败')
    gui.plan_update = boom
    app.wiki_log.hide()
    app.start_update()
    wait_idle()
    check('failed step marked', 'error' in app.wiki_stepper.states, str(app.wiki_stepper.states))
    check('failure result card', '没有完成' in result_title(), result_title()[:120])
    check('log opened on failure', app.wiki_log.opened)
    check('buttons usable after failure', str(app.update_button.cget('state')) == 'normal')

    # 5) Media runner: failures are collected, not raised.
    def flaky(name, *a):
        if name == 'extract_panel_data.py':
            raise RuntimeError('x')
    app.run_script = flaky
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        failed = app.refresh_media(True, False)
    check('media failures collected', failed == ['局外面板计算器数值'], str(failed))

    # 5b) A missing voice decoder is an optional skip, not a failed step.
    def voice_skipped(name, *a):
        return ['  · 角色语音', '  跳过角色语音提取：缺少 vgmstream 解码器。'] if name == 'extract_voices.py' else []
    app.run_script = voice_skipped
    with contextlib.redirect_stdout(io.StringIO()):
        failed = app.refresh_media(False, True)
    check('voice skip is not a failure', failed == [], str(failed))
    check('voice skip is reported', len(app.media_notes) == 1 and 'vgmstream' in app.media_notes[0], str(app.media_notes))

    # 6) Settings persist.
    app.mode.set('full')
    app.on_mode()
    check('mode hint follows', '覆盖' in app.mode_hint.cget('text'))
    app.mode.set('diff')
    app.on_mode()
    for _ in range(20):
        app.update()
    check('no Tk callback errors', not callback_errors, '; '.join(callback_errors[:3]))
finally:
    app.destroy()
    gui.OUTPUT = real_output
    shutil.rmtree(tmp, ignore_errors=True)

print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
sys.exit(1 if failures else 0)
