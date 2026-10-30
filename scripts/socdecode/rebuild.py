"""Rebuild the offline snapshots after a client update writes new pages.

Only the infographic data is regenerated: `scripts/build_data.py` rebuilds
`data/index.js` and `data/search.js` from `data/raw` alone and would drop the
client-managed entries that `plan_update` merges in, so it is never run here.
"""
from __future__ import annotations

import subprocess
import sys

from .config import ROOT

STEPS = (
    ('重建一图流数据（星级文本与素材）', ['scripts/build_infographic.py', '--metadata-only']),
)


def run(log=print):
    for label, script in STEPS:
        log(f'{label}…')
        result = subprocess.run([sys.executable, '-X', 'utf8', *script], cwd=str(ROOT),
                                capture_output=True, text=True, encoding='utf8', errors='replace')
        for line in (result.stdout or '').splitlines():
            if line.strip():
                log('  ' + line.strip())
        if result.returncode:
            for line in (result.stderr or '').splitlines():
                if line.strip():
                    log('  ' + line.strip())
            raise RuntimeError(f'{label}失败（退出码 {result.returncode}）')
    log('重建完成：一图流星级文本与素材已同步。索引与搜索条目由本次更新直接合并写入。')
