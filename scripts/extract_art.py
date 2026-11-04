"""Pull pixel-sprite animation frames and portrait expression variants.

Three client asset families land here, all offline, all from the resource
archive (``output/archive``) that ``archive/extract.py`` already unpacked:

* ``sprite/share/tex/share_texN/<unit>_<action>_<frame>.png`` — battle pixel
  sprites, one frame per file. ``unit.palette`` minus its ``_palette`` suffix
  names the unit (e.g. ``HplayerLeaderadaFset01``). Frames are duplicated per
  unit: a true-colour copy and an Alpha8 shading mask (RGB all black). The
  PNG colour-type byte tells them apart without decoding.
* Facing: the frame numbers of one action split into a front-facing run and a
  back-facing run (verified on idle/walk/attack: camelot idle 0-3 face the
  camera, 4-7 show the back; left/right is a horizontal mirror in game). The
  split point is the halfway frame and is stored as ``front`` so the UI can
  offer front/back/mirror views.
* ``image/icon/face/icon_faceN/face_<art>[_<emotion>].png`` — half-body
  portrait expression variants (anger/cry/happy/rage/sad/shock/...), 288px.
* ``image/ui/dynamic_card_full/skin_card_<art>/*.png`` — portrait form
  variants (alternate art states), keyed off ``unit_skin.icon``.

Outputs are shared by every copy of the wiki and indexed by character *name*
(unit table), so no per-copy page-id regeneration is needed:

* ``assets/sprites/<art>/<action>_<frame>.png``
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
import json
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

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


def png_colour_type(path: Path) -> int:
    """IHDR colour type: 6/2 = true colour, 0/4 = greyscale (Alpha8 masks)."""
    with open(path, 'rb') as fh:
        return fh.read(26)[25]


def load_manifest(archive: Path):
    versions = sorted((p.name for p in (archive / 'versions').iterdir() if p.is_dir()), reverse=True)
    if not versions:
        raise SystemExit('未找到资源归档（output/archive/versions），先运行 archive/extract.py。')
    data = json.loads(gzip.decompress((archive / 'versions' / versions[0] / 'manifest.json.gz').read_bytes()))
    return [dict(zip(data['fields'], e)) for e in data['entries']], archive / 'objects'


def object_path(objects: Path, row) -> Path:
    return objects / row['hash'][:2] / (row['hash'] + row['ext'])


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


def main():
    parser = argparse.ArgumentParser(description='提取像素小人动作帧与立绘表情差分')
    parser.add_argument('--character', action='append', help='只处理指定角色，可重复')
    parser.add_argument('--dry-run', action='store_true', help='只统计，不写文件')
    args = parser.parse_args()

    from socdecode.config import game_path
    from socdecode.client import game_root
    game = game_root(game_path())
    prefixes = character_prefixes(game)
    wanted = [norm_name(n) for n in (args.character or page_names())]
    missing = [n for n in wanted if n not in prefixes]
    if missing:
        print(f'注意：{len(missing)} 个角色没有动作帧前缀（跳过）：{missing[:8]}')

    rows, objects = load_manifest(ROOT / 'output' / 'archive')
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
            if len(parts) == 2 and parts[1].endswith('.png'):
                forms[parts[0].lower()][parts[1][:-4]] = row

    sprites_out, expressions_out = {}, {}
    copied = total_bytes = 0
    if not args.dry_run:
        (ROOT / 'assets' / 'sprites').mkdir(parents=True, exist_ok=True)
        (ROOT / 'assets' / 'expressions').mkdir(parents=True, exist_ok=True)

    for name in wanted:
        info = prefixes.get(name)
        if not info:
            continue
        folder, art = info['folder'], info['folder'].lower()
        acts = frames.get(folder) or frames.get(folder.lower()) or {}

        action_payload = []
        for action in sorted(acts):
            files = []
            for frame_no in sorted(acts[action]):
                candidates = acts[action][frame_no]
                colour = [c for c in candidates
                          if object_path(objects, c).exists()
                          and png_colour_type(object_path(objects, c)) in (2, 6)]
                picked = colour[0] if colour else next(
                    (c for c in candidates if object_path(objects, c).exists()), None)
                if picked is None:
                    continue
                src = object_path(objects, picked)
                file_name = f'{action}_{frame_no}.png'
                files.append(file_name)
                if not args.dry_run:
                    dst = ROOT / 'assets' / 'sprites' / art / file_name
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if not dst.exists():
                        shutil.copy(src, dst)
                        copied += 1
                    total_bytes += dst.stat().st_size
            if files:
                action_payload.append({'action': action, 'label': ACTION_LABELS.get(action, action),
                                       'frames': files,
                                       'front': (len(files) + 1) // 2})

        face_payload = []
        for skin_art in [art] + [s.lower() for s in info['skins']]:
            for key in sorted(faces.get(skin_art, {})):
                src = object_path(objects, faces[skin_art][key])
                if not src.exists():
                    continue
                file_name = f'{skin_art}_{key}.png' if key != 'base' else f'{skin_art}.png'
                face_payload.append({'key': key, 'label': FACE_LABELS.get(key, key),
                                     'skin': skin_art if skin_art != art else None,
                                     'file': file_name})
                if not args.dry_run:
                    dst = ROOT / 'assets' / 'expressions' / file_name
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if not dst.exists():
                        shutil.copy(src, dst)
                        copied += 1
                    total_bytes += dst.stat().st_size

        form_payload = []
        for skin_art in [art] + [s.lower() for s in info['skins']]:
            for key in sorted(forms.get(skin_art, {})):
                src = object_path(objects, forms[skin_art][key])
                if not src.exists():
                    continue
                file_name = f'{skin_art}_form_{key}.png'
                form_payload.append({'key': key, 'file': file_name})
            if not args.dry_run:
                dst = ROOT / 'assets' / 'expressions' / file_name
                if not dst.exists():
                    shutil.copy(src, dst)
                    copied += 1
                total_bytes += dst.stat().st_size

        if action_payload:
            sprites_out[name] = {'art': art, 'actions': action_payload}
        if face_payload or form_payload:
            expressions_out[name] = {'art': art, 'faces': face_payload, 'forms': form_payload}

    if args.dry_run:
        total_frames = sum(len(a['frames']) for v in sprites_out.values() for a in v['actions'])
        total_faces = sum(len(v['faces']) for v in expressions_out.values())
        print(f'{len(sprites_out)} 个角色有动作帧（{total_frames} 帧）；'
              f'{len(expressions_out)} 个角色有表情差分（{total_faces} 张）。')
        for name in list(sprites_out)[:12]:
            acts = sprites_out[name]['actions']
            print(f'  {name}: {len(acts)} 种动作 {sum(len(a["frames"]) for a in acts)} 帧'
                  f'，如 {[a["action"] for a in acts[:8]]}')
        return

    (ROOT / 'data' / 'sprites.js').write_text(
        'window.WIKI_SPRITES=' + json.dumps(sprites_out, ensure_ascii=False, separators=(',', ':')) + ';\n', 'utf8')
    (ROOT / 'data' / 'expressions.js').write_text(
        'window.WIKI_EXPRESSIONS=' + json.dumps(expressions_out, ensure_ascii=False, separators=(',', ':')) + ';\n', 'utf8')
    print(f'完成：新复制 {copied} 个文件，目录总大小 {total_bytes / 1048576:.1f} MB；'
          f'{len(sprites_out)} 个角色 / {sum(len(v["actions"]) for v in sprites_out.values())} 种动作入索引，'
          f'{len(expressions_out)} 个角色表情差分。')


if __name__ == '__main__':
    main()
