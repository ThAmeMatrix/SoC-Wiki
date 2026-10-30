"""Settings remembered between local client updates."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # SoCwiki project root
WIKI = ROOT
OUTPUT = ROOT / 'output'
CONFIG = OUTPUT / 'client-update.json'
DEFAULT_GAME = Path(r'C:\Game\SwordofConvallaria\SoCLauncher')


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


def last_backup():
    marker = OUTPUT / 'last-backup.txt'
    if not marker.is_file():
        return None
    value = marker.read_text('utf8').strip()
    return Path(value) if value else None
