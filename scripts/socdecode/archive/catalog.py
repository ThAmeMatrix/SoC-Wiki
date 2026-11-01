"""Where every file and Unity object of the client belongs in the archive.

Paths are stable keys: ``<category>/<location>/<name>.<ext>``. Categories keep
English keys inside paths so a renamed label never looks like a changed file;
the Chinese labels are only used for display and for the organised folders.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath

# Bump when the extractor output for the same input changes, so caches are rebuilt
# (and caches of older extractors are removed by ``archive gc``).
EXTRACTOR = 2

CATEGORIES = (
    ('table', '配置表'), ('image', '图片'), ('sprite', '精灵'), ('text', '文本'),
    ('data', '数据'), ('script', '脚本'), ('audio', '音频'), ('video', '视频'),
    ('font', '字体'), ('model', '模型'), ('bundle', '资源包清单'), ('program', '程序文件'),
)
LABELS = dict(CATEGORIES)
KEYS = tuple(key for key, _ in CATEGORIES)
# Categories that come out of Unity bundles (bundles are read when any is wanted).
BUNDLE_CATEGORIES = frozenset({'image', 'sprite', 'text', 'data', 'script', 'font', 'model', 'audio', 'video', 'bundle'})

# Account, launcher records, battle reports and player preferences are never read.
EXCLUDED_FILES = frozenset({'account3', 'gameinstallationrecord.db', '.gameinstallationrecord.dat',
                            'assets/player_prefs.ini'})
EXCLUDED_DIRS = ('assets/report/',)
EXCLUDED_SUFFIXES = ('.log', '.tmp', '.crdownload')

TABLE_GROUPS = {
    'lua_dbtemplate': '通用', 'lua_dbtemplateonline': '在线', 'lua_dbtemplateperformance': '表现',
    'lua_dbtemplatesandbox': '沙盒', 'lua_dbtemplateskill': '技能', 'lua_dbtemplatespeciality': '特性',
    'lua_dbtemplatetranslation': '翻译',
}

TEXT_SUFFIXES = frozenset({'.txt', '.json', '.proto', '.ini', '.xml', '.config', '.info', '.map', '.aspx',
                           '.browser', '.csv', '.lua', '.md', '.yaml', '.yml'})
PROGRAM_SUFFIXES = frozenset({'.dll', '.exe', '.pak', '.dat', '.bin', '.vuplex', '.resource'})
IMAGE_SUFFIXES = frozenset({'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tga'})


def excluded(rel: str) -> bool:
    low = rel.lower()
    if low in EXCLUDED_FILES or low.endswith(EXCLUDED_SUFFIXES):
        return True
    return any(low.startswith(prefix) for prefix in EXCLUDED_DIRS)


def is_bundle(rel: str) -> bool:
    return rel.lower().endswith('.unity3d')


def is_table_bundle(rel: str) -> bool:
    name = PurePosixPath(rel).name.lower()
    return rel.lower().startswith('assets/lua/') and name.startswith('lua_dbtemplate') and name.endswith('.unity3d')


def group_of(rel: str) -> str:
    """Two levels under ``assets`` (``icon/card``), or the top folder elsewhere."""
    parts = PurePosixPath(rel).parts
    if parts and parts[0] == 'assets':
        inner = parts[1:-1]
        if not inner:
            return '(根目录)'
        return '/'.join(inner[:2])
    return parts[0] if len(parts) > 1 else '(根目录)'


def inner(rel: str) -> str:
    """Location below ``assets`` without the bundle suffix: ``icon/card/icon_card12``."""
    path = rel[len('assets/'):] if rel.startswith('assets/') else rel
    return path[:-len('.unity3d')] if path.lower().endswith('.unity3d') else path


def classify_loose(rel: str) -> tuple[str, str]:
    suffix = PurePosixPath(rel).suffix.lower()
    inside = rel.startswith('assets/')
    if suffix in ('.wem', '.bnk', '.wav', '.ogg', '.mp3'):
        return 'audio', suffix
    if suffix in ('.mp4', '.webm', '.usm'):
        return 'video', suffix
    if suffix in IMAGE_SUFFIXES:
        return 'image', suffix
    if not inside and (suffix in PROGRAM_SUFFIXES or not suffix):
        return 'program', suffix
    if suffix in TEXT_SUFFIXES:
        return 'text', suffix
    return ('data' if inside else 'program'), suffix


def loose_path(category: str, rel: str) -> str:
    path = rel[len('assets/'):] if rel.startswith('assets/') else rel
    return f'{category}/{path}'


_INVALID = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_RESERVED = frozenset({'con', 'prn', 'aux', 'nul', *(f'com{i}' for i in range(1, 10)), *(f'lpt{i}' for i in range(1, 10))})


def safe_name(name: str, fallback: str) -> str:
    """A file name that survives Windows folders: no reserved names or trailing dots."""
    value = _INVALID.sub('_', str(name or '')).strip().rstrip('. ')
    if not value:
        value = fallback
    if value.split('.')[0].lower() in _RESERVED:
        value = '_' + value
    return value[:150]
