"""Package the local client updater as one Windows executable.

    python -X utf8 scripts/build_client_updater.py

The result is ``dist/SoCwiki本地更新.exe``: open it, choose the game directory
once, archive every client resource with version diffs, and pull client data
into this offline wiki.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = 'SoCwiki本地更新'
PACKAGE = ROOT / 'scripts' / 'socdecode'


def main():
    data = [(PACKAGE / 'archive' / 'viewer', 'socdecode/archive/viewer'), (PACKAGE / 'data', 'socdecode/data')]
    command = [
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed',
        '--name', NAME,
        '--paths', str(ROOT / 'scripts'),
        '--collect-all', 'UnityPy',
        # UnityPy loads fmod.dll through ctypes; without it sprites and meshes fail to decode.
        '--collect-all', 'fmod_toolkit',
        # The texture decoders pick a CPU build through archspec, which reads its JSON database.
        '--collect-data', 'archspec',
        '--hidden-import', 'bs4',
        '--hidden-import', 'PIL',
        '--hidden-import', 'numpy',
        '--hidden-import', 'socdecode',
        # Spawned extraction processes import these by name.
        '--hidden-import', 'socdecode.archive.extract',
        '--hidden-import', 'socdecode.archive.server',
        '--hidden-import', 'update_client',
        *[arg for source, target in data for arg in ('--add-data', f'{source}{os.pathsep}{target}')],
        '--distpath', str(ROOT / 'dist'),
        '--workpath', str(ROOT / 'build' / 'client-updater'),
        '--specpath', str(ROOT / 'build'),
        str(ROOT / 'scripts' / 'update_client_gui.py'),
    ]
    print('打包中：' + ' '.join(command[3:]))
    result = subprocess.run(command, cwd=str(ROOT))
    if result.returncode:
        raise SystemExit(result.returncode)
    target = ROOT / 'dist' / f'{NAME}.exe'
    print(f'完成：{target}（{target.stat().st_size/1024/1024:.1f} MiB）' if target.is_file() else '未生成可执行文件')


if __name__ == '__main__':
    main()
