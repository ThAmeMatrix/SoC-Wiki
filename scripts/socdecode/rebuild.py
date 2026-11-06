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
    ('统一技能范围图为蓝底射程 / 红底作用范围', ['scripts/rebuild_range_images.py']),
    ('导出战斗地图与自动战斗 AI', ['scripts/extract_world_data.py']),
    ('导出客户端地形块贴图', ['scripts/extract_terrain.py']),
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
    pages = json.JSONDecoder().raw_decode(text[text.index('=') + 1:])[0]['pages']
    data = pinyin.build(pages)
    (ROOT / 'data' / 'pinyin.js').write_text(
        'window.WIKI_PINYIN=' + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n', 'utf8')
    log(f'  拼音索引已重建，覆盖 {len(data)} 个页面。')


VOICE_DIR = ROOT / 'assets' / 'voice'
VOICE_SUFFIXES = ('.mp3', '.ogg', '.wav', '.m4a', '.webm')



def rebuild_equipment_stars(log=print):
    """Give every equipment page the same 1→5 star diff as character traits.

    BWIKI-sourced equipment pages are merged in by ``plan_update`` without going
    through ``record_equipment()``, so they carry the five star-skill fields but
    no ``starComparison`` and fall back to the whole raw article. Recomputing the
    diff here (from the already-written page files) needs neither the client nor
    BWIKI, and leaves client-generated pages untouched.
    """
    import importlib.util
    helper = ROOT / 'scripts' / 'character_data.py'
    if not helper.is_file():
        return
    spec = importlib.util.spec_from_file_location('socwiki_rebuild_equipment', helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    pages = ROOT / 'data' / 'pages'
    if not pages.is_dir():
        return
    fixed = 0
    for path in sorted(pages.glob('*.js')):
        try:
            text = path.read_text('utf8')
        except OSError:
            continue
        if '一星技能' not in text or '=' not in text:
            continue
        try:
            doc = json.loads(text[text.index('=') + 1:].rstrip().rstrip(';'))
        except (ValueError, IndexError):
            continue
        fields = doc.get('fields') or {}
        if not all(key in fields for key in EQUIPMENT_STAR_KEYS):
            continue
        current = doc.get('starComparison')
        if current and any(level.get('html') for level in current.get('levels', [])):
            continue
        try:
            comparison = module.star_comparison(fields, list(EQUIPMENT_STAR_KEYS))
        except (ValueError, TypeError, AttributeError):
            comparison = None
        # Levels may all be empty when every paragraph is a common effect. When
        # the archive has no star text at all, star_comparison returns None: keep
        # the same comparison frame with "not recorded" placeholders so every
        # equipment page presents its star skills the same way.
        if not comparison or len(comparison.get('levels') or []) != 5:
            if any(str(fields.get(key) or '').strip() for key in EQUIPMENT_STAR_KEYS):
                continue
            comparison = {'keys': list(EQUIPMENT_STAR_KEYS), 'common': '',
                          'levels': [{'star': star, 'available': False, 'html': '', 'removed': [],
                                      'previous': None, 'changed': False} for star in range(1, 6)]}
        doc['starComparison'] = comparison
        prefix = text[:text.index('=')]
        path.write_text(prefix + '=' + json.dumps(doc, ensure_ascii=False, separators=(',', ':')) + ';\n', 'utf8')
        fixed += 1
    if fixed:
        log(f'  装备星级差分已补齐 {fixed} 页（与角色个性同一套五星对照）。')


def rebuild_choice_pages(log=print):
    """Refresh battle rules and give every 抉择 branch a linkable skill page.

    Runs after ``plan_update`` has written the index, so the generated entries
    survive an update. The extractor keeps existing files when no client or
    archive is available; this step is idempotent.
    """
    for name in ('extract_battle_rules', 'build_choice_pages'):
        path = ROOT / 'scripts' / f'{name}.py'
        if not path.is_file():
            return
        result = subprocess.run([sys.executable, '-X', 'utf8', str(path)], cwd=str(ROOT),
                                capture_output=True, text=True, encoding='utf8', errors='replace')
        for line in (result.stdout or '').splitlines():
            if line.strip():
                log('  ' + line.strip())
        if result.returncode:
            log(f'  {name} 失败：{(result.stderr or "").strip()[-200:]}')
            return
    log('  战斗常量、抉择技能词条与机制规则已重建。')


def run(log=print):
    ensure_asset_map(log)
    # 语音 / 像素动作 / 立绘表情已从离线包移除，不再重建。
    try:
        rebuild_equipment_stars(log)
    except Exception as error:      # never abort the update over a presentation detail
        log('  装备星级差分未能补齐：' + str(error))
    try:
        rebuild_choice_pages(log)
    except Exception as error:      # never abort the update over optional skill pages
        log('  抉择技能词条未能重建：' + str(error))
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
