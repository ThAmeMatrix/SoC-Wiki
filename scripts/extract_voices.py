"""Pull character voice lines (and their dialogue text) out of the game client.

The authoritative mapping comes from three client assets:

* ``assets/lua/lua_dbtemplate.unity3d`` -> table ``unit_voice_collection``:
  one row per voice line, with ``idunit``, ``event_name``, ``title`` and ``text``.
  This covers every playable character, including all legendary units and their
  variants (104 units, 4480 lines).
* ``assets/bnk_events.unity3d`` -> ``bnk_events`` JSON: ``events`` maps an event
  name to its Wwise bank, and ``cn``/``jp`` give each line's declared duration.
* ``assets/audio/<lang>/vo_*.bnk``: the Wwise bank itself. Its HIRC chunk
  connects an event (id = FNV-1 hash of its name) -> action -> sound -> media id,
  which is the index of the embedded clip in DIDX. So every exported clip gets
  its exact title and dialogue text instead of a meaningless sequence number.

Banks and loose ``.wem`` files are XOR-scrambled with ``XD_Audio`` (8-byte
repeating key); after unscrambling, a bank is an ordinary Wwise soundbank and
embedded clips are plain RIFF/WAVE. Do not confuse ``vo_*`` with
``assets/audio/bnk_*.bnk``: those are short combat SFX, not voice lines.

Clips are decoded with vgmstream and re-encoded to Ogg Vorbis, because browsers
cannot play Wwise's Opus container and a straight remux would pitch-shift the
audio (Wwise declares 44.1 kHz while Opus itself is always 48 kHz). Each
character folder gets ``meta.json`` with per-line metadata; ``rebuild_voices``
merges it into ``data/voices.js``. Nothing here touches the network.

Usage:
    python scripts/extract_voices.py                     # cn + jp, all characters
    python scripts/extract_voices.py --lang cn          # Chinese only
    python scripts/extract_voices.py --character 艾达
    python scripts/extract_voices.py --dry-run           # report matches only
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

KEY = b'XD_Audio'
TOOL = ROOT / 'tools' / 'vgmstream' / 'vgmstream-cli.exe'
VOICE_DIR = ROOT / 'assets' / 'voice'
LANG_LABELS = {'cn': '中文', 'jp': '日文'}
LEGACY_NAME = re.compile(r'^(中文|日文) \d{2}\.ogg$')


def unscramble(raw: bytes) -> bytes:
    """Undo the client's XOR obfuscation (key repeats every 8 bytes)."""
    key = (KEY * (len(raw) // len(KEY) + 1))[:len(raw)]
    return (int.from_bytes(raw, 'big') ^ int.from_bytes(key, 'big')).to_bytes(len(raw), 'big')


def fnv1(name: str) -> int:
    """Wwise hashes object names with 32-bit FNV-1 over the lowercase string."""
    value = 0x811c9dc5
    for byte in name.lower().encode():
        value = ((value * 0x01000193) & 0xffffffff) ^ byte
    return value


def chunks_of(bank: bytes):
    pos, chunks = 0, {}
    while pos + 8 <= len(bank):
        tag = bank[pos:pos + 4]
        size = struct.unpack('<I', bank[pos + 4:pos + 8])[0]
        chunks[tag] = (pos + 8, size)
        pos += 8 + size
    return chunks


def parse_bank(path: Path, wanted_events):
    """Return ``(clips, chain)`` for a decrypted Wwise voice bank.

    ``chain`` maps an event name to the 0-based index of its embedded clip by
    walking HIRC: event -> action -> sound -> media id -> DIDX position.
    """
    bank = unscramble(path.read_bytes())
    chunks = chunks_of(bank)
    if b'DIDX' not in chunks or b'DATA' not in chunks or b'HIRC' not in chunks:
        return [], {}
    data_start = chunks[b'DATA'][0]
    index_start, index_size = chunks[b'DIDX']
    entries = [struct.unpack('<III', bank[index_start + i:index_start + i + 12])
               for i in range(0, index_size - 11, 12)]
    media = [entry[0] for entry in entries]
    clips = [bank[data_start + off:data_start + off + size] for _, off, size in entries]
    media_set = set(media)
    media_bytes = {m: struct.pack('<I', m) for m in media}

    hirc_start, hirc_size = chunks[b'HIRC']
    buf = bank[hirc_start:hirc_start + hirc_size]
    count = struct.unpack('<I', buf[:4])[0]
    pos, events, actions, sounds = 4, {}, {}, {}
    while pos + 9 <= len(buf) and count > 0:
        kind = buf[pos]
        size = struct.unpack('<I', buf[pos + 1:pos + 5])[0]
        object_id = struct.unpack('<I', buf[pos + 5:pos + 9])[0]
        data = buf[pos + 9:pos + 5 + size]
        if kind == 4:  # CAkEvent -> action ids
            events[object_id] = [struct.unpack('<I', data[1 + 4 * i:5 + 4 * i])[0]
                                 for i in range(data[0])]
        elif kind == 3:  # CAkAction -> target sound id
            actions[object_id] = struct.unpack('<I', data[2:6])[0]
        elif kind == 2:  # CAkSound -> embedded media id
            found = [m for m, raw in media_bytes.items() if raw in data]
            sounds[object_id] = found[0] if len(found) == 1 else None
        pos += 5 + size
        count -= 1

    by_hash = defaultdict(list)
    for name in wanted_events:
        by_hash[fnv1(name)].append(name)
    chain = {}
    for object_id, names in by_hash.items():
        if object_id not in events:
            continue
        for action_id in events[object_id]:
            sound_id = actions.get(action_id)
            media_id = sounds.get(sound_id)
            if media_id in media_set:
                index = media.index(media_id)
                for name in names:
                    chain[name] = index
                break
    return clips, chain


def to_ogg(wem: bytes, destination: Path, workdir: Path) -> bool:
    """Decode one clip with vgmstream and write it back as Ogg Vorbis.

    libsndfile's Vorbis encoder overflows its stack when handed a long stream in
    one call (a 17-second Wwise "Custom Vorbis" line reliably kills the process).
    Writing in 16k-frame chunks avoids it.
    """
    import soundfile as sf
    source = workdir / 'clip.wem'
    source.write_bytes(wem)
    decoded = workdir / 'clip.wav'
    if decoded.exists():
        decoded.unlink()
    result = subprocess.run([str(TOOL), '-o', str(decoded), str(source)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode or not decoded.exists():
        return False
    data, rate = sf.read(str(decoded), always_2d=True)
    with sf.SoundFile(str(destination), 'w', samplerate=rate, channels=data.shape[1],
                      format='OGG', subtype='VORBIS') as output:
        for offset in range(0, len(data), 16384):
            output.write(data[offset:offset + 16384])
    return True


def client_root(game: Path) -> Path:
    """Find the directory that directly contains ``assets/``."""
    for candidate in (game, game / 'SwordOfConvallaria'):
        if (candidate / 'assets' / 'lua' / 'lua_db.unity3d').is_file():
            return candidate
    raise SystemExit(f'未找到客户端资源目录：{game}')


def load_client_voice_data(root: Path):
    """Read ``bnk_events`` and the ``unit_voice_collection`` config table."""
    from socdecode.client import LuaTables, text_assets
    bank_data = json.loads(text_assets(root / 'assets' / 'bnk_events.unity3d')['bnk_events'].decode('utf8'))
    vm = LuaTables(root / 'SoC_Data' / 'Plugins' / 'x86_64' / 'slua.dll')
    try:
        vm.setup(text_assets(root / 'assets' / 'lua' / 'lua_db.unity3d'))
        scripts = text_assets(root / 'assets' / 'lua' / 'lua_dbtemplate.unity3d')
        rows = vm.table('unit_voice_collection', scripts['unit_voice_collection'])
    finally:
        vm.close()
    return bank_data, rows


def category_of(event_name: str) -> str:
    parts = event_name.split('_')
    if len(parts) > 2:
        if parts[2] == 'bt':
            return '战斗语音'
        if parts[2] == 'sys':
            return '日常语音'
    return '其它语音'


def page_ids():
    """角色名 -> 资料馆角色页 id，用于决定语音放在哪个目录。"""
    index = ROOT / 'data' / 'index.js'
    if not index.exists():
        return {}
    text = index.read_text('utf8')
    payload = json.loads(text[text.index('=') + 1:text.index(';window.WIKI_PAGES')])
    return {page['name']: page['id'] for page in payload['pages'] if page.get('type') == 'character'}


def build_plans(bank_data, voice_rows, snapshot, ids):
    """Return ``(name, page_id, [line, ...])`` for every character with lines."""
    unit_to_char = {c['unitId']: c for c in snapshot['characters']}
    by_unit = defaultdict(list)
    for row in voice_rows:
        by_unit[row['idunit']].append(row)
    plans = []
    for unit_id, rows in by_unit.items():
        char = unit_to_char.get(unit_id)
        if not char or char['name'] not in ids:
            continue
        usable = [row for row in rows if row.get('event_name') in bank_data['events']]
        usable.sort(key=lambda row: row['id'])
        lines, seen = [], set()
        for row in usable:
            event = row['event_name']
            if event in seen:
                continue
            seen.add(event)
            lines.append({
                'event': event,
                'bank': bank_data['events'][event],
                'title': row.get('title') or '',
                'text': row.get('text') or '',
                'category': category_of(event),
            })
        if lines:
            plans.append((char['name'], ids[char['name']], lines))
    plans.sort(key=lambda plan: plan[0])
    return plans


def main():
    parser = argparse.ArgumentParser(description='从客户端音效包提取角色语音与台词')
    parser.add_argument('--character', action='append', help='只处理指定角色，可重复')
    parser.add_argument('--lang', default='cn,jp', help='语言目录，逗号分隔（默认 cn,jp）')
    parser.add_argument('--dry-run', action='store_true', help='只报告匹配结果，不写文件')
    parser.add_argument('--limit', type=int, default=0, help='最多处理的角色数')
    parser.add_argument('--offset', type=int, default=0, help='跳过前 N 个角色，便于分批运行')
    parser.add_argument('--force', action='store_true', help='重新导出已存在的语音')
    args = parser.parse_args()

    if not TOOL.exists():
        raise SystemExit(f'缺少解码工具：{TOOL}\n请下载 vgmstream-win64.zip 并解到该目录（离线使用）。')

    from socdecode.client import game_root
    from socdecode.config import game_path
    root = client_root(game_root(game_path()))
    audio = root / 'assets' / 'audio'
    if not (audio / 'cn').is_dir():
        raise SystemExit(f'未找到客户端语音目录：{audio / "cn"}')

    langs = [x for x in args.lang.split(',') if x in LANG_LABELS]
    bank_data, voice_rows = load_client_voice_data(root)
    snapshot = json.loads((ROOT / 'output' / 'client-data.json').read_text('utf8'))
    plans = build_plans(bank_data, voice_rows, snapshot, page_ids())
    print(f'客户端台词表 {len(voice_rows)} 行；可归属角色 {len(plans)} / {len(snapshot["characters"])}')
    legendary = {c['name'] for c in snapshot['characters'] if c.get('rarity') == '传说'}
    covered = {name for name, _, _ in plans}
    print(f'其中传说角色 {len(legendary & covered)} / {len(legendary)}')

    events_of_bank = defaultdict(set)
    for event, bank in bank_data['events'].items():
        events_of_bank[bank].add(event)
    available = {lang: {p.stem for p in (audio / lang).glob('*.bnk')} for lang in langs}

    only = set(args.character or ())
    targets = [plan for plan in plans if not only or plan[0] in only]
    if args.offset:
        targets = targets[args.offset:]
    if args.limit:
        targets = targets[:args.limit]
    print(f'本次处理：{len(targets)} 个角色 × {len(langs)} 种语言')
    if args.dry_run:
        for name, pid, lines in targets[:30]:
            banks = sorted({line['bank'] for line in lines})
            print(f'  {name:<12} 第 {pid} 页，{len(lines)} 句，包: {", ".join(banks)}')
            print(f'      例：{lines[0]["category"]} / {lines[0]["title"]} / {lines[0]["text"][:32]}')
        return

    # 旧版导出的是「中文 01.ogg」两位序号，新格式三位；清掉以免同页出现两套条目。
    for stale in VOICE_DIR.rglob('*.ogg'):
        if LEGACY_NAME.match(stale.name):
            stale.unlink()

    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    written = failed = skipped = 0
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        for position, (name, pid, lines) in enumerate(targets, 1):
            folder = VOICE_DIR / str(pid)
            folder.mkdir(parents=True, exist_ok=True)
            if args.force:
                for old in folder.glob('*.ogg'):
                    old.unlink()
            cache, meta = {}, {}
            for index, line in enumerate(lines, 1):
                for lang in langs:
                    stem = '%s %03d' % (LANG_LABELS[lang], index)
                    duration = bank_data.get(lang, {}).get(line['event'])
                    try:
                        duration = round(float(duration), 2)
                    except (TypeError, ValueError):
                        duration = None
                    meta[stem] = {'title': line['title'], 'text': line['text'],
                                  'category': line['category'], 'duration': duration}
                    key = (line['bank'], lang)
                    if key not in cache:
                        path = audio / lang / (line['bank'] + '.bnk')
                        cache[key] = (parse_bank(path, events_of_bank[line['bank']])
                                      if line['bank'] in available[lang] and path.is_file() else ([], {}))
                    clips, chain = cache[key]
                    clip_index = chain.get(line['event'])
                    if clip_index is None or clip_index >= len(clips):
                        skipped += 1
                        continue
                    out = folder / (stem + '.ogg')
                    if out.exists() and out.stat().st_size and not args.force:
                        continue
                    if to_ogg(clips[clip_index], out, workdir):
                        written += 1
                    else:
                        failed += 1
            (folder / 'meta.json').write_text(
                json.dumps(meta, ensure_ascii=False, separators=(',', ':')), 'utf8')
            total = sum(1 for _ in folder.glob('*.ogg'))
            print(f'  [{position}/{len(targets)}] {name}: {len(lines)} 句，目录内 {total} 个音频')
    print(f'完成：新导出 {written} 条；缺音频跳过 {skipped} 条；解码失败 {failed} 条。')


if __name__ == '__main__':
    main()
