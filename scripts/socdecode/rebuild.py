"""Rebuild the offline snapshots after a client update writes new pages.

The client updater is the sole source of truth for the wiki: ``plan_update``
reads the local game client and writes every page (characters, skills, talents,
statuses, equipment, liberation) together with ``data/index.js`` /
``data/search.js``. ``build_data.py`` (which rebuilds those from a BWIKI
snapshot) is intentionally never run here -- it would discard the client-managed
entries that ``plan_update`` merges in.

The only remaining step is the infographic canvas, built by
``scripts/build_infographic.py``. That script is itself client-only: it derives
all imagery from the pages ``plan_update`` wrote and the game's texture assets,
and needs no BWIKI ``asset-map.json`` or network access. BWIKI-sourced extras
(logo, badges, stat icons, tarot/engraving art, the custom name font) simply
stay empty when absent, so a pure client rebuild still yields a complete wiki.

No step here contacts the online wiki. A failure must never abort the update --
the pages and assets from ``apply`` are already on disk.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from .config import ROOT

RAW = ROOT / 'data' / 'raw'
STEPS = (
    ('重建一图流数据（星级文本与素材）', ['scripts/build_infographic.py', '--metadata-only']),
)


def ensure_asset_map(log=print):
    """Best-effort local ``data/raw/asset-map.json`` so nothing crashes offline.

    ``build_infographic.py`` degrades gracefully without this file, but a handful
    of BWIKI-sourced decorations (logo, badges, stat icons) resolve through it.
    If it is missing we regenerate a map from whatever already lives under
    ``assets/`` -- purely local, never touching the network. When the real
    BWIKI-sourced map is present it is left untouched.
    """
    if (RAW / 'asset-map.json').exists():
        return
    log('  asset-map.json 缺失，从本地 assets/ 生成离线映射（缺失的 BWIKI 命名资产将留空）。')
    mapping = {}
    if (ROOT / 'assets').is_dir():
        for path in (ROOT / 'assets').rglob('*'):
            if path.is_file():
                mapping[path.name] = {'path': str(path.relative_to(ROOT)).replace('\\', '/')}
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / 'asset-map.json').write_text(json.dumps(mapping, ensure_ascii=False), encoding='utf8')
    log(f'  本地 asset-map 已生成，含 {len(mapping)} 个资源名（仅客户端已有文件）。')


def rebuild_pinyin(log=print):
    """Refresh ``data/pinyin.js`` from the current index so pinyin search stays in sync."""
    from . import pinyin
    if not pinyin.available():
        return
    index = ROOT / 'data' / 'index.js'
    if not index.exists():
        return
    text = index.read_text('utf8')
    pages = json.loads(text[text.index('=') + 1:text.index(';window.WIKI_PAGES')])['pages']
    data = pinyin.build(pages)
    (ROOT / 'data' / 'pinyin.js').write_text(
        'window.WIKI_PINYIN=' + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n', 'utf8')
    log(f'  拼音索引已重建，覆盖 {len(data)} 个页面。')


VOICE_DIR = ROOT / 'assets' / 'voice'
VOICE_SUFFIXES = ('.mp3', '.ogg', '.wav', '.m4a', '.webm')


def rebuild_voices(log=print):
    """Index voice clips under ``assets/voice/<page id>/`` with their dialogue.

    ``scripts/extract_voices.py`` writes ``meta.json`` next to the clips: each
    line's title, Chinese dialogue text, category and duration, keyed by file
    stem. Merging it here keeps the index self-contained, so a rebuild needs no
    client and manually added audio still works (it simply has no metadata).
    """
    data = {}
    if VOICE_DIR.is_dir():
        for folder in sorted(VOICE_DIR.iterdir()):
            if not folder.is_dir():
                continue
            meta = {}
            meta_path = folder / 'meta.json'
            if meta_path.is_file():
                try:
                    meta = json.loads(meta_path.read_text('utf8'))
                except (ValueError, OSError):
                    pass
            clips = []
            for path in sorted(folder.rglob('*')):
                if not path.is_file() or path.suffix.lower() not in VOICE_SUFFIXES:
                    continue
                stem = path.stem
                info = meta.get(stem) or {}
                match = re.match(r'^(中文|日文)\s*', stem)
                clip = {'name': stem, 'src': str(path.relative_to(ROOT)).replace('\\', '/'),
                        'lang': match.group(1) if match else '语音',
                        'title': info.get('title') or '',
                        'text': info.get('text') or '',
                        'category': info.get('category') or '其它语音'}
                if info.get('duration'):
                    clip['duration'] = info['duration']
                clips.append(clip)
            if clips:
                data[folder.name] = clips
    (ROOT / 'data' / 'voices.js').write_text(
        'window.WIKI_VOICES=' + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n', 'utf8')
    if data:
        with_text = sum(1 for clips in data.values() for clip in clips if clip['text'])
        log(f'  语音索引已重建：{len(data)} 个角色，共 {sum(len(v) for v in data.values())} 条语音，'
            f'其中 {with_text} 条带台词文本。')


def run(log=print):
    ensure_asset_map(log)
    rebuild_voices(log)
    try:
        rebuild_pinyin(log)
    except Exception as error:      # never abort the update over an optional index
        log('  拼音索引未能重建：' + str(error))
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
