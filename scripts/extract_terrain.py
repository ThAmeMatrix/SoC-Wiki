"""Export the client's terrain block sprites for the map browser.

    python -X utf8 scripts/extract_terrain.py [--dry-run]

Reads ``assets/atlas/terrain_atlas.unity3d`` from the installed client with
UnityPy and writes one PNG per sprite into ``assets/terrain/``. The sprite
names (``terrain1`` .. ``terrain28`` plus ``terrain_buff_*``) are exactly the
values of ``field_type.icon`` / ``field_status`` in the client config tables,
so the map UI can use them as real client artwork instead of flat colours.

If the atlas is unavailable the existing files are left untouched, so the
offline package keeps working.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'assets' / 'terrain'
CONFIG = ROOT / 'output' / 'archive' / 'library' / '当前版本' / '配置表'


def table(name):
    for folder in [CONFIG / 'lua_dbtemplateonline', CONFIG / 'lua_dbtemplate',
                   *[p for p in CONFIG.iterdir() if p.is_dir()]] if CONFIG.is_dir() else []:
        p = folder / f'{name}.json'
        if p.is_file():
            try:
                return json.loads(p.read_text('utf8'))
            except (ValueError, OSError):
                pass
    return []


def client_path():
    try:
        sys.path.insert(0, str(ROOT / 'scripts'))
        from socdecode.client import game_root  # noqa: E402
        from socdecode.config import game_path  # noqa: E402
        return game_root(game_path()) / 'assets' / 'atlas' / 'terrain_atlas.unity3d'
    except Exception:
        return None


def rectify_face(image, face):
    """Inverse-project one face of the client's isometric cube sprite.

    A 64x51 sprite has a diamond top with corners (W/2,0), (W,H*0.34),
    (W/2,H*0.68), (0,H*0.34) and two side walls below it. We map the four
    source corners to a square/rectangle so CSS can stretch it over the whole
    face (background-size:100% 100%) without distortion.
    """
    try:
        from PIL import Image
    except ImportError:
        return None
    w, h = image.size
    cx, mid, low, end = w / 2.0, h * 0.34, h * 0.68, h
    if face == 'top':
        # ul, ll, lr, ur in SOURCE coordinates
        quad = (cx, 0, 0, mid, cx, low, w, mid)
        size = (64, 64)
    else:
        # left wall: parallelogram -> rectangle
        quad = (0, mid, 0, low, cx, end, cx, low)
        size = (64, 32)
    src = image.convert('RGBA')
    out = src.transform(size, Image.Transform.QUAD, quad,
                        resample=Image.Resampling.BICUBIC)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    src = client_path()
    if not src or not src.is_file():
        print('未找到客户端地形图集，保留现有 assets/terrain 不变。')
        return
    try:
        import UnityPy
    except ImportError:
        print('缺少 UnityPy，跳过地形贴图导出。')
        return
    env = UnityPy.load(str(src))
    sprites = {}
    for obj in env.objects:
        if obj.type.name != 'Sprite':
            continue
        try:
            data = obj.read()
            name = getattr(data, 'm_Name', '')
            if not name.startswith('terrain'):
                continue
            image = data.image
            if image is not None:
                sprites[name] = image.convert('RGBA')
        except Exception:
            continue
    if not sprites:
        print('地形图集里没有可导出的 Sprite，保留现有文件。')
        return
    icons = {r.get('icon') for r in table('field_type') if r.get('icon')}
    matched = len([n for n in sprites if n in icons])
    print(f'地形贴图 {len(sprites)} 张，其中 {matched}/{len(icons)} 个 field_type.icon 命中')
    if args.dry_run:
        return
    OUT.mkdir(parents=True, exist_ok=True)
    top_dir, wall_dir = OUT / 'top', OUT / 'wall'
    top_dir.mkdir(exist_ok=True)
    wall_dir.mkdir(exist_ok=True)
    for name, image in sprites.items():
        image.save(OUT / (name + '.png'))
        # The client sprite is a full isometric CUBE: a diamond top plus two
        # trapezoidal side walls. Rectify each face into a flat texture so the
        # CSS-3D cube can map the top diamond onto its square top face and the
        # stone/dirt sides onto its rectangular walls, covering each face fully.
        for face, target in (('top', top_dir), ('wall', wall_dir)):
            rect = rectify_face(image, face)
            if rect is not None:
                rect.save(target / (name + '.png'))
    # Manifest for the UI and for regenerating without the client installed.
    field_types = [{'id': r['id'], 'name': r.get('name') or '', 'icon': r.get('icon') or '',
                    'material': r.get('material_name') or '', 'type': r.get('type') or ''}
                   for r in table('field_type')]
    (OUT / 'manifest.json').write_text(json.dumps({
        'source': 'assets/atlas/terrain_atlas.unity3d (client Unity AssetBundle)',
        'sprites': sorted(sprites),
        'faces': {n: {'top': f'assets/terrain/top/{n}.png',
                      'wall': f'assets/terrain/wall/{n}.png'} for n in sprites},
        'fieldTypes': field_types,
    }, ensure_ascii=False, indent=2) + '\n', 'utf8')
    print('已写入', OUT.relative_to(ROOT), f'({len(sprites)} 个 PNG + manifest.json)')


if __name__ == '__main__':
    main()
