"""Settings remembered between local client updates."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _root() -> Path:
    """The wiki folder. A packaged exe runs from a temporary unpack folder, so it
    looks beside itself (e.g. ``<wiki>/dist/``) instead of at its own sources."""
    if getattr(sys, 'frozen', False):
        here = Path(sys.executable).resolve().parent
        for folder in (here, *here.parents):
            if (folder / 'index.html').is_file() and (folder / 'data').is_dir():
                return folder
        return here
    return Path(__file__).resolve().parents[2]


ROOT = _root()                                        # SoCwiki project root
WIKI = ROOT
OUTPUT = ROOT / 'output'
CONFIG = OUTPUT / 'client-update.json'
DEFAULT_GAME = Path(r'C:\Game\SwordofConvallaria\SoCLauncher')
DEFAULT_ARCHIVE = OUTPUT / 'archive'


def load() -> dict:
    try:
        return json.loads(CONFIG.read_text('utf8'))
    except (OSError, ValueError):
        return {}


def save(**values) -> dict:
    data = load()
    data.update(values)
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2), 'utf8')
    return data


def game_path() -> Path:
    """The last client directory used, or the default installation path."""
    value = load().get('game')
    return Path(value) if value else DEFAULT_GAME


def remember_game(path) -> None:
    save(game=str(path))


def archive_path() -> Path:
    """Where extracted resources and versions live (``output/archive`` by default)."""
    value = load().get('archive')
    return Path(value) if value else DEFAULT_ARCHIVE


def last_backup():
    marker = OUTPUT / 'last-backup.txt'
    if not marker.is_file():
        return None
    value = marker.read_text('utf8').strip()
    return Path(value) if value else None
