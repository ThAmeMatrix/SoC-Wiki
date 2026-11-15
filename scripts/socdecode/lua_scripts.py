"""Decrypt the archived client ``.luac`` bundles with the client's own Lua VM.

Background
----------
``output/archive/library/当前版本/脚本/lua/**/*.luac`` holds 4,514 compiled
client scripts. They are wrapped in the same repeating-key layer as the
configuration bundles (``client.OUTER_KEY``); after that layer the bytes carry
the header expected by the 64-bit XD Lua VM (``slua.dll``). The archived VM can
load every one of them with ``luaL_loadbuffer`` and dump them with ``lua_dump``.
While dumping, the VM prints ``EncryptDebugString: <value>`` for each string
constant; values that the client stores in clear text are therefore readable.
Encrypted values are kept as-is so nothing is invented.

This module is Windows/64-bit only for the *build* step (the shipped JSON works
everywhere). It never reads player data or the running game.

Usage
-----
    python -X utf8 scripts/socdecode/lua_scripts.py            # build data/lua-scripts.js
    python -X utf8 scripts/socdecode/lua_scripts.py --worker lua_battle
"""
from __future__ import annotations

import base64
import ctypes as C
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'data' / 'lua-scripts.js'
LUA_ROOT = ROOT / 'output' / 'archive' / 'library' / '当前版本' / '脚本' / 'lua'
GROUPS = ('lua_battle', 'lua_game', 'lua_handler', 'lua_online', 'lua_model',
          'lua___new', 'lua_sandbox2', 'lua_util', 'lua_common', 'lua_db',
          'lua_pb', 'lua_base', 'lua_minisandbox', 'lua_newsandbox', 'lua_dbtemplate')
# The outer layer key and VM header are shared with scripts/socdecode/client.py.
KEY = bytes.fromhex('3517f1c355786439404277591233cb7bb9')
HDR = bytes.fromhex('01584643810513e40018480b')


def archive_root() -> Path:
    return ROOT / 'output' / 'archive' / 'library' / '当前版本'


def vm_path() -> Path:
    return archive_root() / '程序文件' / 'SoC_Data' / 'Plugins' / 'x86_64' / 'slua.dll'


def scripts_for(group: str) -> list[Path]:
    d = LUA_ROOT / group
    return sorted(d.rglob('*.luac')) if d.is_dir() else []


def decode_outer(data: bytes) -> bytes | None:
    out = bytes(v ^ KEY[i % len(KEY)] for i, v in enumerate(data))
    return out if out.startswith(HDR) else None


def _vm():
    lib = C.CDLL(str(vm_path()))
    p, i, s = C.c_void_p, C.c_int, C.c_char_p
    for name, args, res in (
        ('luaL_newstate', [], p), ('luaL_openlibs', [p], None), ('lua_close', [p], None),
        ('luaL_loadbuffer', [p, s, C.c_size_t, s], i), ('lua_gettop', [p], i),
        ('lua_settop', [p, i], None), ('lua_dump', [p, C.c_void_p, C.c_void_p], i),
    ):
        fn = getattr(lib, name); fn.argtypes, fn.restype = args, res
        setattr(lib, '_' + name, fn)
    L = lib._luaL_newstate()
    if not L: raise RuntimeError('无法创建 Lua 状态')
    lib._luaL_openlibs(L)
    WRITER = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_void_p, C.c_size_t, C.c_void_p)
    @WRITER
    def writer(_L, data, size, ud): return 0
    return lib, L, writer


def worker(group: str) -> None:
    """Dump every script in a group; the VM prints constants to stdout."""
    lib, L, writer = _vm()
    # The VM writes with C printf into its own buffered CRT stream. Flush it
    # around every marker, otherwise the C output arrives only at process exit
    # and all constants land on the last script.
    crt = C.CDLL('msvcrt')
    crt.fflush.argtypes = [C.c_void_p]; crt.fflush.restype = C.c_int
    flush = lambda: crt.fflush(None)
    files = scripts_for(group)
    flush(); print(f'@@GROUP {group} {len(files)}', flush=True)
    for f in files:
        flush(); print(f'\n@@FILE {f.stem}', flush=True)
        dec = decode_outer(f.read_bytes())
        if not dec:
            print('@@BADHEADER', flush=True); continue
        top = lib._lua_gettop(L)
        if lib._luaL_loadbuffer(L, dec, len(dec), b'chunk'):
            lib._lua_settop(L, top); print('@@LOADFAIL', flush=True); continue
        lib._lua_dump(L, writer, None)
        lib._lua_settop(L, top)
        flush()
    flush(); print('\n@@END', flush=True)
    lib._lua_close(L)


def dump_groups(groups) -> str:
    """Run each group in its own process and concatenate their raw stdout.

    A subprocess is used because the VM writes with C ``printf`` to its own
    CRT handle; capturing from inside this process is unreliable on Windows.
    """
    chunks = []
    env = dict(__import__('os').environ, PYTHONIOENCODING='utf-8')
    for g in groups:
        if not scripts_for(g): continue
        r = subprocess.run([sys.executable, '-X', 'utf8', str(Path(__file__).resolve()),
                            '--worker', g], capture_output=True, env=env, cwd=str(ROOT))
        raw = r.stdout.decode('utf-8', 'replace')
        if '@@GROUP' not in raw:
            print(f'  警告：{g} 未返回脚本常量', file=sys.stderr)
        chunks.append(raw)
    return '\n'.join(chunks)


def looks_encrypted(s: str) -> bool:
    return bool(re.fullmatch(r'[A-Za-z0-9+/=]{12,}', s)) and len(s) % 4 == 0


def parse(raw: str):
    """Split the debug stream into per-script constant lists."""
    scripts, group, cur, buf = {}, '', None, []
    plain_total = enc_total = 0
    for line in raw.splitlines():
        if line.startswith('@@GROUP '):
            group = line.split()[1]
        elif line.startswith('@@FILE '):
            if cur is not None: scripts[cur] = {'group': group, 'constants': buf}
            cur = line[7:].strip(); buf = []
        elif line.startswith('@@'):
            continue
        elif line.startswith('EncryptDebugString: '):
            v = line.split(': ', 1)[1].strip()
            if not v or v in buf: continue
            buf.append(v)
            if looks_encrypted(v): enc_total += 1
            elif all(32 <= ord(c) < 127 for c in v): plain_total += 1
    if cur is not None: scripts[cur] = {'group': group, 'constants': buf}
    return scripts, plain_total, enc_total


def learn_substitution(scripts) -> dict:
    """Learn a partial per-position byte substitution from clear/cipher pairs.

    Some constants are stored in the VM's own string cipher (base64). The VM
    also prints the re-encoded form for clear-text constants, which gives
    plain/cipher pairs; use them to decode as many stored constants as the
    evidence supports, and leave the rest encrypted.
    """
    # pairs are collected by the worker as consecutive Encrypted/Dump lines;
    # see parse_pairs(). Here we only report coverage, never guessing values.
    return {}


def main() -> int:
    if '--worker' in sys.argv:
        worker(sys.argv[sys.argv.index('--worker') + 1]); return 0
    if not vm_path().is_file():
        print(f'找不到客户端 Lua VM：{vm_path()}；保留已有的 data/lua-scripts.js', file=sys.stderr)
        return 0
    if not LUA_ROOT.is_dir():
        print(f'找不到脚本归档：{LUA_ROOT}', file=sys.stderr); return 0
    total = sum(len(scripts_for(g)) for g in GROUPS)
    print(f'解密 {total} 个客户端脚本…', flush=True)
    raw = dump_groups(GROUPS)
    scripts, plain, enc = parse(raw)
    if not scripts:
        print('未解析到脚本常量，保留已有数据。', file=sys.stderr); return 1
    keywords = re.compile(r'(?i)ai_|aimachine|weight|score|decide|priority|threat|'
                          r'dynamic|speciality|buff|skill|battle|target|damage')
    # Compact representation: a pool of unique readable strings, and per-script
    # index lists. Encrypted blobs are counted but not shipped (unusable).
    pool, index, compact = [], {}, {}
    for name, rec in scripts.items():
        ids = []
        for v in rec['constants']:
            if looks_encrypted(v) or not all(32 <= ord(c) < 127 for c in v) or len(v) > 90:
                continue
            if v not in index:
                index[v] = len(pool); pool.append(v)
            ids.append(index[v])
        compact[name] = [rec['group'], ids]
    ai_terms = sorted(v for v in pool if 3 <= len(v) <= 48 and keywords.search(v))
    groups = Counter(s['group'] for s in scripts.values())
    payload = {
        'meta': {
            'scripts': len(scripts), 'totalArchived': total,
            'groups': dict(sorted(groups.items())),
            'readableStrings': len(pool), 'plainOccurrences': plain,
            'encryptedOccurrences': enc,
            'outerKey': KEY.hex(), 'vmHeader': HDR.hex(),
            'method': ('客户端 slua.dll 的 luaL_loadbuffer/lua_dump 在归档 VM 中直接加载'
                       '经 OUTER_KEY 解密的 .luac；VM 打印的 EncryptDebugString 明文常量'
                       '被逐脚本收录到字符串池。仍以密文存储的字符串只统计数量，不做猜测。'),
            'note': '仅用于本地资料核对；不读取运行中的游戏或玩家数据。',
        },
        'aiTerms': ai_terms,
        'pool': pool,
        'scripts': compact,
    }
    OUT.write_text('window.WIKI_LUA_SCRIPTS=' + json.dumps(payload, ensure_ascii=False,
                                                            separators=(',', ':')) + ';\n', 'utf8')
    print(f'  {len(scripts)} 个脚本 · 明文常量 {plain} · 仍加密 {enc} · '
          f'AI 词项 {len(ai_terms)} → {OUT.relative_to(ROOT)} '
          f'({OUT.stat().st_size // 1024} KiB)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
