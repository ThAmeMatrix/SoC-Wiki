"""The client's own battle-grid art, used to draw skill range diagrams.

The client has no per-skill range picture; the range overlay in battle is built
from these textures (all of them ship in assets/battle/block/grid.unity3d):

  skill_attack  128x128 rounded tile, cream border + translucent fill — 技能范围
  base_attack   128x128 rounded tile, orange border + translucent fill — 攻击/伤害范围
  grid-target2   64x64 framed marker — 目标格
  target01       64x64 thin square frame — 自身/格子框

If the bundle is missing the caller falls back to flat colours, so a diagram is
never silently dropped.
"""
from __future__ import annotations
from pathlib import Path

import UnityPy
from PIL import Image

BUNDLE = 'battle/block/grid.unity3d'
CAST_TILE = 'skill_attack'
AREA_TILE = 'base_attack'
TARGET_TILE = 'grid-target2'
SELF_TILE = 'target01'
_cache: dict[str, dict[str, Image.Image]] = {}


def load(game: Path) -> dict[str, Image.Image]:
    """Read the range tiles out of the client bundle (cached per game path)."""
    key = str(Path(game).resolve())
    if key in _cache:
        return _cache[key]
    tiles = {}
    path = Path(game) / 'assets' / BUNDLE
    if path.is_file():
        env = UnityPy.load(str(path))
        wanted = {CAST_TILE, AREA_TILE, TARGET_TILE, SELF_TILE}
        for obj in env.objects:
            if obj.type.name not in ('Texture2D', 'Sprite'):
                continue
            data = obj.read()
            if data.m_Name in wanted:
                tiles[data.m_Name] = data.image.convert('RGBA')
    _cache[key] = tiles
    return tiles


def set(game: Path):
    """Map the loaded textures onto the roles used by the renderer."""
    tiles = load(game)
    return {'cast': tiles.get(CAST_TILE), 'area': tiles.get(AREA_TILE),
            'target': tiles.get(TARGET_TILE), 'self': tiles.get(SELF_TILE)}
