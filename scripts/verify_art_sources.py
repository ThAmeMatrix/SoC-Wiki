"""Exercise extract_art.py end-to-end in a throwaway wiki root.

    python -X utf8 scripts/verify_art_sources.py

Covers the case that broke a GitHub ZIP install: no output/archive/versions
directory. The client bundles must be used instead, and an existing resource
index must never be overwritten with empty data.
"""
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE / 'scripts'))
import extract_art as art  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix='socart-'))
(tmp / 'data').mkdir()
shutil.copy(WORKSPACE / 'data' / 'index.js', tmp / 'data' / 'index.js')
real_root = art.ROOT
art.ROOT = tmp
failures = []
captured = []


def check(name, ok, detail=''):
    print(('PASS ' if ok else 'FAIL ') + name + (f' :: {detail}' if detail else ''), flush=True)
    if not ok:
        failures.append(name)


def run(args):
    """Run main() with the given argv, capturing stdout for assertions."""
    import contextlib
    import io
    old = sys.argv
    sys.argv = ['extract_art.py', *args]
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            art.main()
        return 0, buffer.getvalue()
    except SystemExit as error:
        return error.code or 0, buffer.getvalue()
    finally:
        sys.argv = old
        captured.append(buffer.getvalue())


def index(path):
    return json.loads(path.read_text('utf8').split('=', 1)[1].rstrip().rstrip(';'))


try:
    # 1) Simulate "no archive": auto must fall back to the client and write real files.
    t = time.time()
    code, out = run(['--source', 'client', '--character', '艾达'])
    elapsed = round(time.time() - t, 1)
    check('client source exits 0', code == 0, f'code={code}')
    check('client source chosen', '直接读取游戏客户端' in out)
    sprites_js = tmp / 'data' / 'sprites.js'
    expressions_js = tmp / 'data' / 'expressions.js'
    check('sprites index written', sprites_js.is_file())
    check('expressions index written', expressions_js.is_file())
    sprites, expressions = index(sprites_js), index(expressions_js)
    info = sprites.get('艾达')
    check('sprite entry has colour flag', bool(info and info.get('color')))
    frames = [f for a in (info or {}).get('actions', []) for f in a['frames']]
    folder = (info or {}).get('art', '')
    check('mask frames on disk', all((tmp / 'assets' / 'sprites' / folder / f).is_file() for f in frames), f'{len(frames)} frames')
    check('colour frames baked', all((tmp / 'assets' / 'sprites' / folder / 'color' / f).is_file() for f in frames))
    check('expression files on disk', all((tmp / 'assets' / 'expressions' / f['file']).is_file()
                                          for v in expressions.values() for f in v['faces'] + v['forms']))
    print(f'   one character took {elapsed}s')
    before = (sprites_js.read_bytes(), expressions_js.read_bytes())

    # 2) No usable client: skip cleanly, keep the existing index byte-for-byte.
    from socdecode import config
    real_game_path = config.game_path
    config.game_path = lambda: tmp / 'no-such-client'
    try:
        code, out = run(['--source', 'client', '--character', '艾达'])
    finally:
        config.game_path = real_game_path
    check('missing client exits 0', code == 0, f'code={code}')
    check('missing client explains the skip', '跳过像素动作' in out and '保持不变' in out)
    check('existing indexes untouched', (sprites_js.read_bytes(), expressions_js.read_bytes()) == before)

    # 3) auto with no archive: resources are complete now, so skip the 20k decodes.
    code, out = run(['--character', '艾达'])
    check('auto skips complete resources', code == 0 and '已完整' in out, out.strip().splitlines()[-1] if out.strip() else '')
    check('skip keeps a valid index', index(sprites_js).get('艾达') is not None)

    # 4) --force overrides the shortcut.
    code, out = run(['--force', '--character', '艾达'])
    check('force rebuilds', code == 0 and '完成：' in out)

    # 5) An index from an older package (no 'color' field) must not count as complete.
    old = dict(index(sprites_js))
    old['艾达'] = {k: v for k, v in old['艾达'].items() if k != 'color'}
    sprites_js.write_text('window.WIKI_SPRITES=' + json.dumps(old, ensure_ascii=False) + ';\n', 'utf8')
    check('legacy index is incomplete', not art.resources_complete(['艾达'], {'艾达': {}}))

    # 6) Forcing the archive without one explains the situation instead of crashing.
    code, out = run(['--source', 'archive', '--character', '艾达'])
    check('forced archive explains', code == 1 and '没有找到可用的资源归档' in out, f'code={code}')
finally:
    art.ROOT = real_root
    shutil.rmtree(tmp, ignore_errors=True)

print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
sys.exit(1 if failures else 0)
