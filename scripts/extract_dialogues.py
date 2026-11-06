"""Build a browsable story dialogue archive from the game client.

The client keeps dialogue as a localisation dictionary rather than a script:

* ``translation`` (123,630 rows) maps ``(table_name, sub_table_name,
  col_name, idvalue) -> text``. The two big dialogue pairs are
  ``mission / event_section_action / dialogue_content`` + ``specker_name``
  and ``performance / actions / text`` + ``name``.
* ``performance`` (3,091 rows) carries the演出 order: ``data`` is an embedded
  JSON blob with ``sections[].actions`` (an id sequence) and ``actions[]``
  (type 1 = a spoken line) whose ``face`` field names the exact portrait
  variant, e.g. ``hirialadymunafset03_cry``.
* ``scenario`` / ``online_main_quest_chapter`` provide human-readable names.

``idvalue`` high bits group lines into scenes (``idvalue // 1e10``), and the
low bits order them, so no binary script parsing is needed. Two sources are
supported, mirroring extract_art.py: the already-unpacked JSON tables under
``output/archive/library/当前版本/配置表/`` when present, otherwise the client's
own ``lua_dbtemplate*.unity3d`` bundles read directly (about 12 seconds).

Portraits come from ``data/expressions.js`` (character name -> half-body face)
plus the exact ``face`` variant from performance actions. Speakers without a
portrait (NPC names, placeholders) simply show a name plate.

Output: ``data/dialogues.js`` -> ``window.WIKI_DIALOGUES``. Never writes an
empty index over an existing one when the client or tables are unavailable.

Usage:
    python -X utf8 scripts/extract_dialogues.py --dry-run
    python -X utf8 scripts/extract_dialogues.py --source client
    python -X utf8 scripts/extract_dialogues.py --limit-scenes 50
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

ARCHIVE_CFG = ROOT / 'output' / 'archive' / 'library' / '当前版本' / '配置表'
OUTPUT = ROOT / 'data' / 'dialogues.js'
SCENE_BASE = 10_000_000_000

TEXT_KEYS = {
    ('mission', 'event_section_action', 'dialogue_content'),
    ('performance', 'actions', 'text'),
    ('capital_event', 'secondary_perform_action', 'dialogue_content'),
}
SPEAKER_KEYS = {
    ('mission', 'event_section_action', 'specker_name'),
    ('performance', 'actions', 'name'),
    ('capital_event', 'secondary_perform_action', 'specker_name'),
}
GROUPS = {
    'translation': 'lua_dbtemplatetranslation',
    'performance': 'lua_dbtemplateperformance',
    'scenario': 'lua_dbtemplate',
    'scenario_text': 'lua_dbtemplate',
    'online_main_quest_chapter': 'lua_dbtemplateonline',
}
CHAPTER = re.compile(r'^(第[零一二三四五六七八九十百\d]+[章节幕篇][^\-—－]{0,20})')
# Client editor names carry the story line: 「前传线线索墙_…」, 「埃拉曼线下：…」,
# 「骑士团线共通P6-…」, 「大活四线索墙_…」. Group by that instead of dumping
# 3,500 scenes into one undifferentiated list.
CHAPTER_RULES = (
    ('前传', '前传线'), ('骑士团线', '骑士团线'), ('共通线', '共通线'),
    ('埃拉曼', '埃拉曼线'), ('露西亚历史', '露西亚历史篇'), ('光辉线', '光辉线'),
    ('绯红', '绯红之夜'), ('冰与火', '冰与火'), ('命运螺旋', '命运螺旋'),
    ('大活', '大型活动'), ('小偷贵族', '小偷贵族'), ('线索墙', '线索墙推理'),
    ('对话或自言自语', '角色闲谈'), ('随机报答', '角色闲谈'),
    ('秘密基地', '秘密基地'), ('测试', '测试演出'),
)
TEST_SCENE = re.compile(r'^(独角戏测试|示例板子|fddsf|dfd|\d{4}/\d+/\d+测试演出|.*测试演出)')


def norm(name: str) -> str:
    return re.sub(r'[·•‧・]', '-', name or '').strip()


class Tables:
    """Read the needed tables from the archive, or straight from the client."""

    def __init__(self, game: Path, source: str):
        self.game = game
        self.source = source
        self.cache = {}
        self.vm = None
        self.bundles = {}
        self.mode = 'archive' if source in ('auto', 'archive') and ARCHIVE_CFG.is_dir() else 'client'
        if self.mode == 'client':
            from socdecode.client import LuaTables, text_assets
            self.vm = LuaTables(game / 'SoC_Data' / 'Plugins' / 'x86_64' / 'slua.dll')
            self.vm.setup(text_assets(game / 'assets' / 'lua' / 'lua_db.unity3d'))
            self.text_assets = text_assets
        elif source == 'archive' and not ARCHIVE_CFG.is_dir():
            print('没有找到已解密的配置表目录，改为直接读取游戏客户端资源包。')
            self.mode = 'client'
            from socdecode.client import LuaTables, text_assets
            self.vm = LuaTables(game / 'SoC_Data' / 'Plugins' / 'x86_64' / 'slua.dll')
            self.vm.setup(text_assets(game / 'assets' / 'lua' / 'lua_db.unity3d'))
            self.text_assets = text_assets

    def close(self):
        if self.vm:
            self.vm.close()

    def get(self, name):
        if name in self.cache:
            return self.cache[name]
        group = GROUPS[name]
        path = ARCHIVE_CFG / group / f'{name}.json'
        if self.mode == 'archive' and path.is_file():
            rows = json.loads(path.read_text('utf8'))
        else:
            if group not in self.bundles:
                self.bundles[group] = self.text_assets(self.game / 'assets' / 'lua' / f'{group}.unity3d')
            scripts = self.bundles[group]
            rows = self.vm.table(name, scripts[name]) if name in scripts else []
        self.cache[name] = rows
        return rows


def skip(reason, *hint):
    print(f'跳过剧情对话提取：{reason}。')
    for line in hint:
        print(f'  {line}')
    print('  这是可选内容，已有的 data/dialogues.js 保持不变。')


def portrait_map():
    """Character name -> a neutral half-body portrait, plus all known files."""
    path = ROOT / 'data' / 'expressions.js'
    if not path.is_file():
        return {}, set()
    try:
        text = path.read_text('utf8')
        art = json.loads(text[text.index('=') + 1:].rstrip().rstrip(';'))
    except (ValueError, OSError, IndexError):
        return {}, set()
    by_name, files = {}, set()
    for name, info in art.items():
        faces = info.get('faces') or []
        for item in faces:
            files.add(item['file'])
        neutral = next((item for item in faces if item.get('key') == 'base' and not item.get('skin')), None)
        if neutral is None:
            neutral = next((item for item in faces if not item.get('skin')), None)
        if neutral:
            by_name[norm(name)] = neutral['file']
        for skin in {item.get('skin') for item in faces if item.get('skin')}:
            by_name.setdefault(norm(skin), neutral['file'] if neutral else '')
    return by_name, files


def scene_names(tables):
    perf = {row['id']: row for row in tables.get('performance')}
    scenario = {row['id']: row for row in tables.get('scenario')}
    chapters = [c.get('name') or '' for c in tables.get('online_main_quest_chapter')]

    def title(gid):
        for row in (perf.get(gid), scenario.get(gid)):
            if not row:
                continue
            name = (row.get('editor_name') or row.get('name') or '').strip()
            if name and not re.fullmatch(r'[\w\d\s]+', name):
                return name[:60]
            if row.get('name'):
                return str(row['name'])[:60]
        return f'剧情片段 {gid}'

    def chapter(name):
        match = CHAPTER.match(name)
        if match:
            return match.group(1)
        for needle, label in CHAPTER_RULES:
            if needle in name:
                return label
        for text in chapters:
            if text and (text in name or name in text):
                return text[:24]
        return '剧情片段' if name.startswith('剧情片段') else '其它剧情'

    return perf, title, chapter


def performance_faces(tables):
    """(performance id, action id) -> exact portrait variant name."""
    result = {}
    for row in tables.get('performance'):
        raw = row.get('data')
        try:
            data = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (ValueError, TypeError):
            continue
        for action in data.get('actions') or []:
            if action.get('type') == 1 and action.get('face'):
                result[(row['id'], str(action.get('id')))] = str(action['face'])
    return result


def build(tables, limit_scenes=0):
    texts, speakers = {}, {}
    for row in tables.get('translation'):
        key = (row.get('table_name'), row.get('sub_table_name'), row.get('col_name'))
        value = row.get('idvalue')
        text = row.get('original') or ''
        if key in TEXT_KEYS:
            texts[value] = text
        elif key in SPEAKER_KEYS:
            speakers[value] = text
    print(f'台词字典 {len(texts):,} 条 · 说话人 {len(speakers):,} 条')

    _, title_of, chapter_of = scene_names(tables)
    faces_of = performance_faces(tables)
    by_name, known_files = portrait_map()
    print(f'立绘映射 {len(by_name):,} 个名字 · {len(known_files):,} 张表情图')

    grouped = defaultdict(list)
    for value, text in texts.items():
        clean = (text or '').strip()
        if not clean or clean in ('-', '0', 'None'):
            continue
        grouped[value // SCENE_BASE].append((value, clean, speakers.get(value, '')))

    scenes, lines, speakers_list, portraits = [], [], [], []
    speaker_index, portrait_index = {}, {}

    def speaker_id(name):
        name = (name or '').strip() or '旁白'
        if name not in speaker_index:
            speaker_index[name] = len(speakers_list)
            speakers_list.append(name)
        return speaker_index[name]

    def portrait_id(name):
        if not name:
            return -1
        if name not in portrait_index:
            portrait_index[name] = len(portraits)
            portraits.append(name)
        return portrait_index[name]

    with_portrait = 0
    filtered = 0
    for gid in sorted(grouped):
        if limit_scenes and len(scenes) >= limit_scenes:
            break
        rows = sorted(grouped[gid])
        name = title_of(gid)
        if TEST_SCENE.match(name):
            filtered += len(rows)
            continue
        scene_index = len(scenes)
        scenes.append([gid, name, chapter_of(name), len(rows)])
        for value, text, speaker in rows:
            face = ''
            exact = faces_of.get((gid, str(value % SCENE_BASE)))
            if exact:
                candidate = f'{exact}.png'
                if candidate in known_files:
                    face = candidate
            if not face:
                face = by_name.get(norm(speaker), '')
            if not face and speaker in ('{玩家昵称}', '团长'):
                face = next((f for f in known_files if f.startswith('playerm') and '_' not in f[len('playerm'):]), '') \
                    or next((f for f in known_files if f.startswith('hplayermercenaryboymset01')), '')
            if face:
                with_portrait += 1
            lines.append([scene_index, speaker_id(speaker), text, portrait_id(face)])
    return {
        'v': 1,
        'scenes': scenes,
        'lines': lines,
        'speakers': speakers_list,
        'portraits': portraits,
        'stats': {'lines': len(lines), 'scenes': len(scenes), 'withPortrait': with_portrait,
                  'speakers': len(speakers_list), 'filtered': filtered},
    }


def main():
    parser = argparse.ArgumentParser(description='提取客户端剧情文本与立绘，生成可查阅的对话')
    parser.add_argument('--game', help='游戏客户端目录（默认读本地配置）')
    parser.add_argument('--source', choices=('auto', 'archive', 'client'), default='auto',
                        help='auto：有归档用归档，否则直接读客户端')
    parser.add_argument('--dry-run', action='store_true', help='只统计，不写文件')
    parser.add_argument('--limit-scenes', type=int, default=0, help='只导出前 N 个场景（调试用）')
    args = parser.parse_args()

    from socdecode.client import game_root
    from socdecode.config import game_path
    try:
        game = game_root(Path(args.game) if args.game else game_path())
    except (ValueError, OSError) as error:
        skip('没有找到游戏客户端', str(error), '请在「设置」里指定客户端目录后重试。')
        return
    if args.source == 'archive' and not ARCHIVE_CFG.is_dir():
        skip('没有找到已解密的配置表目录', f'期望位置：{ARCHIVE_CFG}',
             '去掉 --source archive 可直接读取游戏客户端。')
        return

    tables = Tables(game, args.source)
    try:
        print('数据来源：' + ('本地资源归档（已解密配置表）' if tables.mode == 'archive' else '游戏客户端 Lua 资源包'))
        if not tables.get('translation'):
            skip('客户端里没有台词字典 translation')
            return
        data = build(tables, args.limit_scenes)
    finally:
        tables.close()
    stats = data['stats']
    print(f"场景 {stats['scenes']:,} 个 · 对白 {stats['lines']:,} 条 · "
          f"说话人 {stats['speakers']:,} 位 · 带立绘 {stats['withPortrait']:,} 条")
    for scene in data['scenes'][:5]:
        print(f"  {scene[1][:36]:<36} {scene[3]:>4} 条  [{scene[2]}]")
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    print(f'数据大小 {len(payload.encode("utf8")) / 1048576:.1f} MB')
    if args.dry_run:
        return
    if not data['lines']:
        skip('这次没有匹配到任何对白')
        return
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text('/* Generated by scripts/extract_dialogues.py from local client dialogue tables. */\n'
                      'window.WIKI_DIALOGUES=' + payload + ';\n', 'utf8')
    print(f'已写入 {OUTPUT}')


if __name__ == '__main__':
    main()
