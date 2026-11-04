"""Pull pixel-sprite animation frames and portrait expression variants.

Three client asset families land here, all offline:

* ``sprite/share/tex/share_texN/<unit>_<action>_<frame>.png`` — battle pixel
  sprites, one frame per file. ``unit.palette`` minus its ``_palette`` suffix
  names the unit (e.g. ``HplayerLeaderadaFset01``). The client stores the
  sprite as a **mask**, not a colour image: RGB is all black and the alpha
  channel is an index into a separate palette LUT ``<unit>_palette.png``
  (a 16xN strip of RGBA swatches). A shader recolours it at runtime, so the
  raw exported frame looks grey/black. We bake that LUT into a full-colour
  copy under ``assets/sprites/<art>/color/`` while keeping the original mask.
* Facing: the frame numbers of one action split into a front-facing run and a
  back-facing run (verified on idle/walk/attack: camelot idle 0-3 face the
  camera, 4-7 show the back; left/right is a horizontal mirror in game). The
  split point is the halfway frame and is stored as ``front`` so the UI can
  offer front/back/mirror views.
* ``image/icon/face/icon_faceN/face_<art>[_<emotion>].png`` — half-body
  portrait expression variants (anger/cry/happy/rage/sad/shock/...), 288px.
* ``image/ui/dynamic_card_full/skin_card_<art>/*.png`` — portrait form
  variants (alternate art states), keyed off ``unit_skin.icon``.

Two sources, chosen automatically:

* ``output/archive`` — the unpacked resource archive produced by the GUI's
  「资源归档」page. Fast, because the PNGs are already on disk.
* The game client's own ``assets/share/tex/``, ``assets/icon/face/`` and
  ``assets/ui/dynamic_card_full/`` bundles — read directly with UnityPy when
  no archive exists. This is the normal case for a Wiki unzipped from GitHub:
  there is no reason to run a multi-gigabyte archive extraction just to get
  these few thousand images. Only object names are scanned up front; the
  images actually used are decoded on demand, one bundle at a time.

If neither the client nor any usable assets are available, the script leaves
the bundled ``data/sprites.js`` / ``data/expressions.js`` and their images
untouched and exits successfully. Never write an empty index over resources
that are already there.

Outputs are shared by every copy of the wiki and indexed by character *name*
(unit table), so no per-copy page-id regeneration is needed:

* ``assets/sprites/<art>/<action>_<frame>.png`` (original mask)
* ``assets/sprites/<art>/color/<action>_<frame>.png`` (full-colour baked frame)
* ``assets/expressions/<art>[_<emotion>|_form_<key>].png``
* ``data/sprites.js`` + ``data/expressions.js``

Usage:
    python scripts/extract_art.py --dry-run
    python scripts/extract_art.py --character 艾达
    python scripts/extract_art.py            # all character pages in data/index.js
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

ACTION_LABELS = {
    'idle': '待机', 'idle2': '待机 2', 'idle3': '待机 3', 'idlewait': '闲置待机',
    'wait': '警戒', 'wait2': '警戒 2', 'wait3': '警戒 3', 'waitclose': '警戒收势',
    'waitup': '警戒·仰视', 'waitdown': '警戒·俯视', 'waitleft': '警戒·左顾',
    'waitright': '警戒·右盼', 'waitupclose': '仰视收势', 'walk': '行走', 'walk2': '行走 2',
    'run': '奔跑', 'run2': '奔跑 2', 'run3': '奔跑 3', 'move': '移动', 'move2': '移动 2',
    'move3': '移动 3', 'move4': '移动 4', 'move5': '移动 5', 'attack': '攻击',
    'attackhandle': '持械攻击', 'attack1': '攻击一', 'attack2': '攻击二', 'attack3': '攻击三',
    'attack4': '攻击四', 'attack5': '攻击五', 'exskill': '专属技', 'exskill1': '专属技一',
    'exskill2': '专属技二', 'exskill3': '专属技三', 'exskill4': '专属技四', 'exskill5': '专属技五',
    'cast': '施法', 'cast1': '施法一', 'cast2': '施法二', 'cast3': '施法三',
    'cast4': '施法四', 'cast5': '施法五', 'charge': '蓄力', 'block': '格挡',
    'dodge': '闪避', 'throw': '投掷', 'reload': '装填', 'injured': '受击',
    'damage': '受击', 'dying': '濒死', 'dead': '倒地', 'die': '阵亡',
    'die1': '阵亡 1', 'die2': '阵亡 2', 'die3': '阵亡 3', 'die4': '阵亡 4', 'die5': '阵亡 5',
    'cheer': '欢呼', 'nod': '点头', 'shake': '摇头', 'crouch': '蹲伏', 'jump': '跳跃',
    'jumpup': '跃起', 'jumpattack': '跳劈', 'sit': '坐下', 'hurt': '受伤', 'fear': '恐惧',
}
FACE_LABELS = {
    'base': '基础', 'anger': '愤怒', 'cry': '哭泣', 'happy': '开心', 'hate': '憎恨',
    'pain': '痛苦', 'rage': '暴怒', 'sad': '悲伤', 'sadsmile': '苦笑', 'serious': '严肃',
    'shock': '震惊', 'die': '战损', 'embarrass': '窘迫', 'think': '沉思', 'smile': '微笑',
    'surprise': '惊讶', 'shy': '害羞', 'laugh': '大笑', 'sleep': '入睡', 'wink': '眨眼',
    'proud': '自豪', 'shame': '羞愧', 'scare': '惊恐', 'nervous': '紧张', 'tired': '疲惫',
}
FRAME_NAME = re.compile(r'^(?P<unit>.+?)_(?P<action>[a-zA-Z][a-zA-Z0-9]*?)_(?P<frame>\d+)(?:~(?P<pid>-?\d+))?\.png$')
FACE_NAME = re.compile(r'^face_(?P<art>.+?)(?:_(?P<emo>[a-z]+))?\.png$')

# Only these bundle families carry the assets we need.
ASSET_GROUPS = (
    ('share/tex', 'share_tex*.unity3d'),
    ('battle/unit', 'battle_unit*.unity3d'),   # unit palette LUTs for full-colour sprites
    ('icon/face', 'icon_face*.unity3d'),
    ('ui/dynamic_card_full', 'skin_card_*.unity3d'),
)


def png_colour_type(data: bytes) -> int:
    """IHDR colour type: 6/2 = RGB(A) mask, 0/4 = greyscale duplicate."""
    return data[25] if len(data) > 25 else 0


def palette_index(rows):
    """``<palette name>.png`` -> source row (unit palettes only)."""
    out = {}
    for row in rows:
        path = row['path']
        if not path.lower().endswith('_palette.png') or '/weapon/' in path:
            continue
        out.setdefault(path.rsplit('/', 1)[-1].lower(), row)
    return out


def bake_colour(mask: bytes, palette: bytes, destination: Path):
    """Resolve the frame's alpha-as-LUT-index into an RGBA sprite.

    The LUT is a 16xN strip of swatches; its flat pixel order is the index.
    Index 0 is transparent in every unit palette, which matches alpha==0
    (empty pixels) in the mask.
    """
    with Image.open(io.BytesIO(palette)) as image:
        lut = list(image.convert('RGBA').getdata())
    with Image.open(io.BytesIO(mask)) as image:
        frame = image.convert('RGBA')
        coloured = Image.new('RGBA', frame.size)
        coloured.putdata([lut[a] if 0 <= a < len(lut) else (0, 0, 0, 0)
                          for _, _, _, a in frame.getdata()])
    destination.parent.mkdir(parents=True, exist_ok=True)
    coloured.save(destination, 'PNG')


def write_if_changed(destination: Path, data: bytes) -> bool:
    if destination.is_file():
        try:
            if destination.read_bytes() == data:
                return False
        except OSError:
            pass
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return True


def keep_existing(reason: str):
    """Explain a skip, without ever clobbering the bundled resources."""
    have = (ROOT / 'data' / 'sprites.js').is_file() and (ROOT / 'data' / 'expressions.js').is_file()
    print(f'跳过像素动作 / 立绘表情提取：{reason}。')
    if have:
        print('  资料包自带的资源与索引保持不变。')
    else:
        print('  资料包里也没有这些资源；离线 Wiki 仍可正常阅读，这两个标签页会显示为空。')
    print('  如需重新生成，请在「设置」里指定游戏客户端目录后重试。')


def resources_complete(wanted, prefixes) -> bool:
    """The bundled assets already cover every character, full-colour frames
    included. Without a local archive, re-decoding ~20k client images on every
    update wastes minutes and rewrites files for no benefit."""
    sprites_path = ROOT / 'data' / 'sprites.js'
    expressions_path = ROOT / 'data' / 'expressions.js'
    if not (sprites_path.is_file() and expressions_path.is_file()):
        return False
    try:
        sprites = json.loads(sprites_path.read_text('utf8').split('=', 1)[1].rstrip().rstrip(';'))
        expressions = json.loads(expressions_path.read_text('utf8').split('=', 1)[1].rstrip().rstrip(';'))
    except (OSError, ValueError, IndexError, AttributeError):
        return False
    if not sprites:
        return False
    for name in wanted:
        if name not in prefixes:
            continue
        info = sprites.get(name)
        # Older packages have no 'color' field and no baked colour frames.
        if not info or 'color' not in info:
            return False
        base = ROOT / 'assets' / 'sprites' / info['art']
        for action in info['actions']:
            for file_name in action['frames']:
                if not (base / file_name).is_file():
                    return False
                if info['color'] and not (base / 'color' / file_name).is_file():
                    return False
        for item in (expressions.get(name) or {}).get('faces', []) + (expressions.get(name) or {}).get('forms', []):
            if not (ROOT / 'assets' / 'expressions' / item['file']).is_file():
                return False
    return True


# -- asset sources ---------------------------------------------------------------
def load_manifest(archive: Path):
    """Rows + blob directory, or ``None`` when there is no usable archive."""
    versions_dir = archive / 'versions'
    if not versions_dir.is_dir() or not (archive / 'objects').is_dir():
        return None
    versions = sorted((p.name for p in versions_dir.iterdir() if p.is_dir()), reverse=True)
    for version in versions:
        manifest = versions_dir / version / 'manifest.json.gz'
        if not manifest.is_file():
            continue
        try:
            data = json.loads(gzip.decompress(manifest.read_bytes()))
            return [dict(zip(data['fields'], e)) for e in data['entries']], archive / 'objects'
        except (OSError, ValueError, KeyError):
            continue
    return None


def object_path(objects: Path, row) -> Path:
    return objects / row['hash'][:2] / (row['hash'] + row['ext'])


class ArchiveSource:
    """PNGs already unpacked by the archive page."""

    def __init__(self, manifest):
        self.rows, self.objects = manifest

    def prepare(self, rows):
        pass

    def data(self, row):
        try:
            return object_path(self.objects, row).read_bytes()
        except (OSError, KeyError):
            return None


def scan_bundles(game: Path):
    """Build archive-equivalent rows from the client bundles (names only)."""
    import UnityPy
    from socdecode.archive.catalog import inner

    assets = game / 'assets'
    rows = []
    for folder, pattern in ASSET_GROUPS:
        directory = assets / folder
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob(pattern)):
            rel = 'assets/' + path.relative_to(assets).as_posix()
            location = inner(rel)
            try:
                env = UnityPy.load(str(path))
                objects = [o for o in env.objects if o.type.name in ('Texture2D', 'Sprite')]
                named = []
                for obj in objects:
                    category = 'image' if obj.type.name == 'Texture2D' else 'sprite'
                    try:
                        name = obj.peek_name()
                    except Exception:
                        name = None
                    named.append((category, name or f'{obj.type.name}_{obj.path_id}', obj))
            except Exception as error:      # noqa: BLE001 - one bad bundle must not stop us
                print(f'  跳过无法解析的资源包 {path.name}：{type(error).__name__}: {error}')
                continue
            counts = Counter((cat, name.lower()) for cat, name, _ in named)
            for category, name, obj in named:
                final = f'{name}~{obj.path_id}' if counts[(category, name.lower())] > 1 else name
                rows.append({'path': f'{category}/{location}/{final}.png',
                             '_bundle': path, '_pid': obj.path_id})
            del env, objects, named
    return rows


class ClientSource:
    """Decode the needed images straight from the client's bundles.

    ``prepare`` loads each bundle once and decodes only the objects this run
    will use, keeping memory flat and avoiding a full archive extraction.
    """

    def __init__(self, game: Path):
        self.rows = scan_bundles(game)

    def prepare(self, rows):
        import UnityPy
        buckets = defaultdict(list)
        for row in rows:
            if row is not None and '_bundle' in row and '_data' not in row:
                buckets[row['_bundle']].append(row)
        for path, group in buckets.items():
            try:
                env = UnityPy.load(str(path))
                by_id = {obj.path_id: obj for obj in env.objects}
            except Exception as error:      # noqa: BLE001
                print(f'  跳过无法解析的资源包 {Path(path).name}：{type(error).__name__}: {error}')
                continue
            for row in group:
                obj = by_id.get(row['_pid'])
                if obj is None:
                    continue
                try:
                    stream = io.BytesIO()
                    obj.read().image.save(stream, 'PNG', compress_level=1)
                    row['_data'] = stream.getvalue()
                except Exception:
                    pass
            del env, by_id

    def data(self, row):
        return row.get('_data') if row else None


def choose_source(game: Path, archive: Path, mode='auto', manifest=None):
    if manifest is None and mode != 'client':
        manifest = load_manifest(archive)
    if manifest is not None:
        print('资源来源：本地资源归档 output/archive（PNG 已解包，直接复用）')
        return ArchiveSource(manifest)
    if mode == 'archive':
        print('没有找到可用的资源归档 output/archive。')
        print('  可以去掉 --source archive 直接读取游戏客户端，或先在「资源归档」页解析一次。')
        raise SystemExit(1)
    print('资源来源：直接读取游戏客户端资源包（未找到 output/archive，无需先做资源归档）')
    return ClientSource(game)


# -- client tables ---------------------------------------------------------------
def character_prefixes(game: Path):
    """Wiki 页名 -> {folder: 动作帧前缀, skins: [皮肤 art], unitId}。

    页名生成与 model.build_snapshot 一致：plain(online.sp_name or online_role.name)，
    这样变体角色（萨曼莎•审判 / 拉维耶•初夏记忆…）也能对上 unit.palette。
    """
    from socdecode.client import LuaTables, text_assets
    from socdecode.model import plain
    vm = LuaTables(game / 'SoC_Data' / 'Plugins' / 'x86_64' / 'slua.dll')
    try:
        vm.setup(text_assets(game / 'assets' / 'lua' / 'lua_db.unity3d'))
        tables = {}
        for bundle in ('lua_dbtemplate', 'lua_dbtemplateonline'):
            for table, data in text_assets(game / 'assets' / 'lua' / f'{bundle}.unity3d').items():
                if table in ('unit', 'unit_skin', 'online_role', 'online_role_unit'):
                    try:
                        tables[table] = vm.table(table, data)
                    except Exception:
                        pass
    finally:
        vm.close()
    units = {r['id']: r for r in tables.get('unit', [])}
    role_names = {r['id']: r.get('name') or '' for r in tables.get('online_role', [])}
    skins_of_unit = defaultdict(set)
    for row in tables.get('unit_skin', []):
        icon = (row.get('icon') or '').strip()
        if icon:
            skins_of_unit[row.get('idunit')].add(icon)
    out = {}
    for online in tables.get('online_role_unit', []):
        unit = units.get(online['idunit'])
        if not unit:
            continue
        name = plain(online.get('sp_name') or role_names.get(online['idonline_role'], '')).strip()
        palette = (unit.get('palette') or '').strip()
        if not name or not palette.lower().endswith('_palette'):
            continue
        out[norm_name(name)] = {'name': name,
                                'folder': palette[:-len('_palette')],
                                'palette': palette,
                                'skins': sorted(skins_of_unit.get(unit['id'], set())),
                                'unitId': unit['id']}
    return out


def page_names():
    """data/index.js 里角色页的名字，用于限定导出范围。"""
    index = ROOT / 'data' / 'index.js'
    text = index.read_text('utf8')
    payload = json.loads(text[text.index('=') + 1:text.index(';window.WIKI_PAGES')])
    return [page['name'] for page in payload['pages'] if page.get('type') == 'character']


def norm_name(text: str) -> str:
    """归一角色名：中点变体（·•‧・）统一成 -，方便 sp_name 与 Wiki 页名对齐。"""
    return re.sub(r'[·•‧・]', '-', text or '').strip()


# -- main ------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description='提取像素小人动作帧与立绘表情差分')
    parser.add_argument('--character', action='append', help='只处理指定角色，可重复')
    parser.add_argument('--dry-run', action='store_true', help='只统计，不写文件')
    parser.add_argument('--source', choices=('auto', 'archive', 'client'), default='auto',
                        help='资源来源：auto（默认，有归档用归档、否则直接读客户端）、archive、client')
    parser.add_argument('--force', action='store_true',
                        help='即使随包资源已完整，也按当前客户端重新生成')
    args = parser.parse_args()

    from socdecode.config import game_path
    from socdecode.client import game_root
    try:
        game = game_root(game_path())
    except (ValueError, OSError) as error:
        keep_existing(f'没有找到游戏客户端（{error}）')
        return

    try:
        prefixes = character_prefixes(game)
    except Exception as error:              # noqa: BLE001 - a damaged Lua install
        keep_existing(f'读取客户端配置表失败（{type(error).__name__}: {error}）')
        return
    wanted = [norm_name(n) for n in (args.character or page_names())]
    missing = [n for n in wanted if n not in prefixes]
    if missing:
        print(f'注意：{len(missing)} 个角色没有动作帧前缀（跳过）：{missing[:8]}')

    archive = ROOT / 'output' / 'archive'
    manifest = load_manifest(archive) if args.source != 'client' else None
    if (manifest is None and args.source != 'archive' and not args.dry_run
            and not args.force and resources_complete(wanted, prefixes)):
        print('像素动作、立绘表情与形态图已完整（含全彩帧），无需重新提取。')
        print('  如需按当前客户端强制重建，请勾选「强制重新解析客户端」后重试。')
        return
    source = choose_source(game, archive, args.source, manifest)
    rows = source.rows
    if not rows:
        keep_existing('没有找到可用的像素动作 / 表情资源包')
        return
    palettes = palette_index(rows)
    frames = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    faces = defaultdict(dict)
    forms = defaultdict(dict)
    for row in rows:
        path = row['path']
        if path.startswith('sprite/share/tex/'):
            m = FRAME_NAME.match(path.rsplit('/', 1)[-1])
            if m:
                frames[m.group('unit')][m.group('action')][int(m.group('frame'))].append(row)
        elif path.startswith('image/icon/face/'):
            m = FACE_NAME.match(path.rsplit('/', 1)[-1])
            if m:
                faces[m.group('art').lower()][m.group('emo') or 'base'] = row
        elif path.startswith('image/ui/dynamic_card_full/skin_card_'):
            parts = path.split('skin_card_', 1)[1].split('/', 1)
            if len(parts) == 2 and parts[1].lower().endswith('.png'):
                forms[parts[0].lower()][parts[1][:-4]] = row

    # Decode only the rows this run needs, before walking the characters.
    used = []
    for name in wanted:
        info = prefixes.get(name)
        if not info:
            continue
        art = info['folder'].lower()
        acts = frames.get(info['folder']) or frames.get(art) or {}
        for action_frames in acts.values():
            for candidates in action_frames.values():
                used.extend(candidates)
        for skin_art in [art] + [s.lower() for s in info['skins']]:
            used.extend(faces.get(skin_art, {}).values())
            used.extend(forms.get(skin_art, {}).values())
        palette = palettes.get((info['palette'] + '.png').lower())
        if palette:
            used.append(palette)
    source.prepare(used)

    sprites_out, expressions_out = {}, {}
    copied = coloured = total_bytes = 0
    if not args.dry_run:
        (ROOT / 'assets' / 'sprites').mkdir(parents=True, exist_ok=True)
        (ROOT / 'assets' / 'expressions').mkdir(parents=True, exist_ok=True)

    for name in wanted:
        info = prefixes.get(name)
        if not info:
            continue
        folder, art = info['folder'], info['folder'].lower()
        acts = frames.get(folder) or frames.get(art) or {}
        palette_row = palettes.get((info['palette'] + '.png').lower())
        palette_data = source.data(palette_row)

        action_payload = []
        for action in sorted(acts):
            files = []
            for frame_no in sorted(acts[action]):
                candidates = acts[action][frame_no]
                colour = [c for c in candidates
                          if source.data(c) is not None
                          and png_colour_type(source.data(c)) in (2, 6)]
                picked = colour[0] if colour else next(
                    (c for c in candidates if source.data(c) is not None), None)
                if picked is None:
                    continue
                data = source.data(picked)
                file_name = f'{action}_{frame_no}.png'
                files.append(file_name)
                if not args.dry_run:
                    dst = ROOT / 'assets' / 'sprites' / art / file_name
                    if write_if_changed(dst, data):
                        copied += 1
                    total_bytes += dst.stat().st_size
                    if palette_data:
                        colour_dst = ROOT / 'assets' / 'sprites' / art / 'color' / file_name
                        bake_colour(data, palette_data, colour_dst)
                        coloured += 1
                        total_bytes += colour_dst.stat().st_size
            if files:
                action_payload.append({'action': action, 'label': ACTION_LABELS.get(action, action),
                                       'frames': files,
                                       'front': (len(files) + 1) // 2})

        face_payload = []
        for skin_art in [art] + [s.lower() for s in info['skins']]:
            for key in sorted(faces.get(skin_art, {})):
                data = source.data(faces[skin_art][key])
                if data is None:
                    continue
                file_name = f'{skin_art}_{key}.png' if key != 'base' else f'{skin_art}.png'
                face_payload.append({'key': key, 'label': FACE_LABELS.get(key, key),
                                     'skin': skin_art if skin_art != art else None,
                                     'file': file_name})
                if not args.dry_run:
                    dst = ROOT / 'assets' / 'expressions' / file_name
                    if write_if_changed(dst, data):
                        copied += 1
                    total_bytes += dst.stat().st_size

        form_payload = []
        for skin_art in [art] + [s.lower() for s in info['skins']]:
            for key in sorted(forms.get(skin_art, {})):
                data = source.data(forms[skin_art][key])
                if data is None:
                    continue
                file_name = f'{skin_art}_form_{key}.png'
                form_payload.append({'key': key, 'label': key,
                                     'skin': skin_art if skin_art != art else None,
                                     'file': file_name})
                if not args.dry_run:
                    dst = ROOT / 'assets' / 'expressions' / file_name
                    if write_if_changed(dst, data):
                        copied += 1
                    total_bytes += dst.stat().st_size

        if action_payload:
            sprites_out[name] = {'art': art, 'actions': action_payload,
                                 'palette': info['palette'], 'color': bool(palette_data)}
        if face_payload or form_payload:
            expressions_out[name] = {'art': art, 'faces': face_payload, 'forms': form_payload}

    if args.dry_run:
        total_frames = sum(len(a['frames']) for v in sprites_out.values() for a in v['actions'])
        total_faces = sum(len(v['faces']) for v in expressions_out.values())
        with_colour = sum(1 for v in sprites_out.values() if v['color'])
        print(f'{len(sprites_out)} 个角色有动作帧（{total_frames} 帧，其中 {with_colour} 个角色有全彩调色板）；'
              f'{len(expressions_out)} 个角色有表情差分（{total_faces} 张）。')
        for name in list(sprites_out)[:12]:
            acts = sprites_out[name]['actions']
            print(f'  {name}: {len(acts)} 种动作 {sum(len(a["frames"]) for a in acts)} 帧'
                  f'，如 {[a["action"] for a in acts[:8]]}')
        return

    if not sprites_out and not expressions_out:
        keep_existing('这次没有匹配到任何角色资源')
        return
    (ROOT / 'data' / 'sprites.js').write_text(
        'window.WIKI_SPRITES=' + json.dumps(sprites_out, ensure_ascii=False, separators=(',', ':')) + ';\n', 'utf8')
    (ROOT / 'data' / 'expressions.js').write_text(
        'window.WIKI_EXPRESSIONS=' + json.dumps(expressions_out, ensure_ascii=False, separators=(',', ':')) + ';\n', 'utf8')
    print(f'完成：新写入 {copied} 个文件，烘焙全彩帧 {coloured} 张，目录总大小 {total_bytes / 1048576:.1f} MB；'
          f'{len(sprites_out)} 个角色 / {sum(len(v["actions"]) for v in sprites_out.values())} 种动作入索引，'
          f'{len(expressions_out)} 个角色表情差分 / '
          f'{sum(len(v["forms"]) for v in expressions_out.values())} 张形态图。')


if __name__ == '__main__':
    main()
