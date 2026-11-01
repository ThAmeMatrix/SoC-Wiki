"""Local client update entry point for SoCwiki.

Reads the installed Sword of Convallaria client on this machine and writes the
characters, skills, traits and exclusive weapons into this offline wiki. The
``archive`` commands keep a versioned copy of every client resource instead.

    python -X utf8 scripts/update_client.py characters --missing
    python -X utf8 scripts/update_client.py diff            # 差量：补缺失与新角色，冲突以本地为准
    python -X utf8 scripts/update_client.py full            # 全覆盖：已匹配角色全部按客户端重算
    python -X utf8 scripts/update_client.py archive scan    # 解析全部资源并记录版本（有变化才生成）
    python -X utf8 scripts/update_client.py archive serve   # 可视化浏览资源、比较任意两个版本
    python -X utf8 scripts/update_client.py gui             # 打开图形界面
"""
from __future__ import annotations

import multiprocessing
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from socdecode.cli import main  # noqa: E402
from socdecode.config import OUTPUT, ROOT, game_path  # noqa: E402

MODES = {'full': ['update', '--all', '--refresh']}


def missing_characters(game=None):
    """Client characters the wiki does not contain yet, with the resolved game root."""
    from socdecode import cli
    args = cli.parser().parse_args(['characters', '--missing', '--game', str(game or game_path()),
                                    '--output', str(OUTPUT), '--wiki', str(ROOT)])
    root, snapshot = cli.extract(args)
    have = cli.wiki_names(ROOT)
    names = list(dict.fromkeys(c['name'] for c in snapshot['characters'] if c['name'] not in have))
    return root, names


def main_entry(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == 'gui':
        from update_client_gui import launch
        return launch()
    if args and args[0] == 'archive':
        from socdecode.archive.cli import main as archive_main
        return archive_main(args[1:])
    if args and args[0] == 'client-path':
        print(game_path())
        return 0
    if args and args[0] in ('diff', 'new'):
        from socdecode import cli
        game = game_path()
        passthrough = []
        rest = args[1:]
        for index, value in enumerate(rest):
            if value == '--game' and index + 1 < len(rest):
                game = Path(rest[index + 1])
            elif not value.startswith('--game='):
                passthrough.append(value)
        root, names = missing_characters(game)
        if not names:
            print('没有客户端新增的角色；可改用 full 全覆盖刷新已收录角色。')
            return 0
        argv = ['add']
        for name in names:
            argv += ['--character', name]
        argv += ['--refresh', '--game', str(root)] + passthrough
        return cli.main(argv)
    if args and args[0] in MODES:
        args = MODES[args[0]] + args[1:]
    if not args:
        print(__doc__)
        print(f'资料馆：{ROOT}\n客户端：{game_path()}')
        return 0
    return main(args)


if __name__ == '__main__':
    multiprocessing.freeze_support()
    raise SystemExit(main_entry())
