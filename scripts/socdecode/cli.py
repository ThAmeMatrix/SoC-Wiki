from __future__ import annotations
import argparse
from pathlib import Path
import json
import sys

from .client import game_root,extract_tables
from .config import ROOT,game_path,remember_game
from .model import build_snapshot
from .rebuild import run as rebuild_wiki
from .transaction import apply,rollback
from .wiki import plan_update

def parser():
    p=argparse.ArgumentParser(description='从本地铃兰之剑客户端提取角色资料，并更新 SoCwiki。')
    subs=p.add_subparsers(dest='command',required=True)
    for name,help_ in [('extract','提取全角色结构化 JSON'),('plan','生成差异报告，Wiki 不写入'),('update','提取、备份并更新 Wiki')]:
        sub=subs.add_parser(name,help=help_)
        sub.add_argument('--game',type=Path,default=game_path(),help='游戏安装或启动器目录')
        sub.add_argument('--output',type=Path,default=ROOT/'output',help='JSON、缓存、报告和备份目录')
        sub.add_argument('--force-extract',action='store_true',help='重新解析已缓存的客户端配置')
        if name!='extract':
            sub.add_argument('--wiki',type=Path,default=ROOT,help='离线 Wiki 目录（台座素材来源）')
            group=sub.add_mutually_exclusive_group(required=True)
            group.add_argument('--character',action='append',help='角色名称；可重复。明确指定时允许尚未开放的本地资料。')
            group.add_argument('--all',action='store_true',help='仅更新 Wiki 已有、客户端已开放且同名唯一的角色')
            sub.add_argument('--refresh',action='store_true',help='以客户端替换已有事实字段；默认只补空白和更新本工具管理的字段')
            if name=='update':sub.add_argument('--no-rebuild',action='store_true',help='写入后不重建搜索索引与一图流数据')
    sub=subs.add_parser('rollback',help='恢复更新前备份；有后续修改时拒绝覆盖')
    sub.add_argument('backup',type=Path)
    sub.add_argument('--no-rebuild',action='store_true',help='回滚后不重建搜索索引与一图流数据')
    sub=subs.add_parser('characters',help='列出客户端可导入的角色与 Wiki 收录状态')
    sub.add_argument('--game',type=Path,default=game_path())
    sub.add_argument('--output',type=Path,default=ROOT/'output')
    sub.add_argument('--wiki',type=Path,default=ROOT)
    sub.add_argument('--force-extract',action='store_true')
    sub.add_argument('--missing',action='store_true',help='只显示 Wiki 还没有的角色')
    sub=subs.add_parser('add',aliases=['new'],help='把一个新角色完整导入 Wiki（一键流程）')
    sub.add_argument('--character',action='append',required=True,help='角色名称；可重复')
    sub.add_argument('--game',type=Path,default=game_path())
    sub.add_argument('--output',type=Path,default=ROOT/'output')
    sub.add_argument('--wiki',type=Path,default=ROOT)
    sub.add_argument('--force-extract',action='store_true')
    sub.add_argument('--refresh',action='store_true',help='以客户端替换已有事实字段')
    sub.add_argument('--sprite-variant',default='base',help="像素小人版本：base=默认形象，或皮肤键值（如 skin-160）")
    sub.add_argument('--dry-run',action='store_true',help='只看会改什么，不写入 Wiki')
    sub.add_argument('--no-rebuild',action='store_true',help='写入后不重建搜索索引与一图流数据')
    return p

def extract(args):
    game=game_root(args.game)
    remember_game(args.game)
    args.output.mkdir(parents=True,exist_ok=True)
    tables,meta=extract_tables(game,args.output/'cache',args.force_extract)
    path=args.output/'client-data.json'
    previous=json.loads(path.read_text('utf8')) if path.exists() else None
    snapshot=build_snapshot(tables,meta)
    if previous and previous.get('schemaVersion')==snapshot['schemaVersion'] and previous['client']['fingerprint']==meta['fingerprint']:
        # A repeated extraction of unchanged files has a stable capture timestamp.
        snapshot['extractedAt']=previous['extractedAt']
    path.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),'utf8')
    listing=[{k:c[k] for k in ('name','id','unitId','class','rarity','available','availableAt')} for c in snapshot['characters']]
    (args.output/'characters.json').write_text(json.dumps(listing,ensure_ascii=False,indent=2),'utf8')
    print(f"提取完成：{len(snapshot['characters'])} 个成长配置完整的角色，{len(snapshot['skills'])} 条相关技能，{len(snapshot['statuses'])} 个关联词条。",flush=True)
    return game,snapshot

def report_markdown(report):
    lines=['# 客户端更新差异报告','',f"资源版本：{report['clientVersion']['change_number']}",
           f"变动文件：{report['changedFiles']}；新增页面：{len(report['newPages'])}；字段变化：{len(report['fieldChanges'])}",'']
    for char in report['characters']:
        lines.extend([f"## {char['name']}",'',f"Wiki ID {char['wikiId']} · 客户端角色 {char['clientId']} · 单位 {char['unitId']}",
            f"技能树 {char['treeNodes']} 项 · 个性 {char['traitStars']} 个星级 · 图片 {char['portraits']} 个外观",
            f"专武：{char.get('weapon') or '未匹配'} · 台座像素小人：{'已合成' if char.get('pedestalSprite') else '未合成'}",
            f"客户端开放时间：{char['availableAt'] or '未配置'}",'',
            '| 生命 | 物攻 | 魔攻 | 物防 | 魔防 | 速度 |','| --- | --- | --- | --- | --- | --- |',
            '| '+' | '.join(str(char['stats'][k]) for k in ('生命','物攻','魔攻','物防','魔防','敏捷'))+' |',''])
    lines+=['## 字段变化','','| 角色 | 字段 | 原值 | 新值 |','| --- | --- | --- | --- |']
    for row in report['fieldChanges']:
        clean=lambda x:str(x).replace('|','／').replace('\n','<br>')
        lines.append('| '+' | '.join(clean(row[k]) for k in ('character','field','before','after'))+' |')
    if report['conflicts']:
        lines+=['','## 保留的差异','', '默认模式保留已有 Wiki 事实。使用 `--refresh` 可更新这些事实字段。','']
        for row in report['conflicts']:lines.append(f"- {row['character']} / {row['field']}：Wiki `{row['wiki']}`；客户端 `{row['client']}`")
    if report['missingAssets']:
        lines+=['','## 本地缺失的原始资源','',*['- '+x for x in report['missingAssets']]]
    if report['warnings']:lines+=['','## 提取说明','',*['- '+x for x in report['warnings']]]
    return '\n'.join(lines)+'\n'

def wiki_names(wiki: Path):
    """Names of character pages already in the Wiki."""
    index=wiki/'data/index.js'
    if not index.is_file():return set()
    text=index.read_text('utf8')
    data=json.JSONDecoder().raw_decode(text[text.index('=')+1:])[0]
    return {page['name'] for page in data['pages'] if page.get('type')=='character'}

def list_characters(args,snapshot):
    have=wiki_names(args.wiki.resolve())
    counts={}
    for char in snapshot['characters']:counts[char['name']]=counts.get(char['name'],0)+1
    rows=[]
    for char in sorted(snapshot['characters'],key=lambda c:(c['name'] in have,c['name'])):
        if args.missing and char['name'] in have:continue
        rows.append((char['name'],char['rarity'],char['class'],
            '已收录' if char['name'] in have else '未收录',
            (char['availableAt'] or '未配置')[:16],
            '同名重复' if counts[char['name']]>1 else ''))
    if not rows:print('没有符合条件的角色。');return
    width=max(len(r[0]) for r in rows)+2
    print(f"{'角色'.ljust(width)}{'稀有度'.ljust(8)}{'职业'.ljust(10)}{'Wiki'.ljust(8)}{'客户端开放时间'.ljust(18)}备注")
    for row in rows:
        print(row[0].ljust(width)+row[1].ljust(8)+row[2].ljust(10)+row[3].ljust(8)+row[4].ljust(18)+row[5])
    print(f"\n共 {len(rows)} 个角色；客户端共 {len(snapshot['characters'])} 个成长配置完整的角色。")
    print('导入：python -X utf8 scripts/update_client.py add --character <角色名>，或用本地更新界面一键拉取')

def add_character(args,game,snapshot):
    names=[]
    for name in dict.fromkeys(args.character):
        matches=[c for c in snapshot['characters'] if c['name']==name]
        if not matches:
            similar=[c['name'] for c in snapshot['characters'] if name and name[0]==c['name'][:1]][:8]
            raise ValueError('客户端没有这个角色：'+name+('。相近的名字：'+', '.join(similar) if similar else ''))
        if len(matches)>1:raise ValueError('客户端有多个同名角色，请用 --character 指定完整名称：'+name)
        names.append(name)
    files,expected,report=plan_update(args.wiki.resolve(),game,snapshot,names,False,args.refresh,
        sprite_variant=args.sprite_variant)
    (args.output/'update-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    (args.output/'update-report.md').write_text(report_markdown(report),'utf8')
    backup=None
    if not args.dry_run:
        backup=apply(args.wiki.resolve(),files,expected,args.output/'backups')
        if backup:
            (args.output/'last-backup.txt').write_text(str(backup),'utf8')
            if not args.no_rebuild:rebuild_wiki(print)
            (backup/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
            (backup/'report.md').write_text(report_markdown(report),'utf8')
    pages=[f['path'] for f in report['files'] if f['path'].startswith('data/pages/')]
    print()
    for char in report['characters']:
        print(f"【{char['name']}】Wiki ID {char['wikiId']} · 客户端角色 {char['clientId']}")
        print(f"  技能树 {char['treeNodes']} 项 · 个性 {char['traitStars']} 星 · 立绘 {char['portraits']} 张")
        print(f"  专武：{char.get('weapon') or '未匹配'} · 台座像素小人：{'已合成' if char.get('pedestalSprite') else '未合成'}")
        variant=(report.get('spriteVariants') or {}).get(char['name'])
        if variant:print(f"  像素小人版本：{variant['label']}（{variant['key']}）")
        if not char.get('availableAtExtraction'):
            print(f"  注意：客户端开放时间 {char['availableAt'] or '未配置'}，尚未到开放时间。")
    print(f"\n页面 {len(pages)} 个 · 图片 {sum(1 for f in report['files'] if f['path'].startswith('assets/'))} 张"
          f" · 字段变化 {len(report['fieldChanges'])} 处 · 保留差异 {len(report['conflicts'])} 处")
    for warning in report['warnings']:print('  说明：'+warning)
    for missing in report['missingAssets']:print('  本地缺失资源：'+missing)
    print('报告：'+str(args.output/'update-report.md'))
    if args.dry_run:print('预览完成，Wiki 未写入。')
    elif backup:print('备份：'+str(backup)+'\n回滚：python -X utf8 scripts/update_client.py rollback "'+str(backup)+'"')
    else:print('数据已是当前版本，无需修改。')

def main(argv=None):
    args=parser().parse_args(argv)
    try:
        if args.command=='rollback':
            print(f'回滚完成：恢复 {rollback(args.backup)} 个文件。')
            if not args.no_rebuild:rebuild_wiki(print)
            return 0
        game,snapshot=extract(args)
        if args.command=='extract':print(args.output/'client-data.json');return 0
        if args.command=='characters':list_characters(args,snapshot);return 0
        if args.command in ('add','new'):add_character(args,game,snapshot);return 0
        files,expected,report=plan_update(args.wiki.resolve(),game,snapshot,args.character,args.all,args.refresh)
        (args.output/'update-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
        (args.output/'update-report.md').write_text(report_markdown(report),'utf8')
        if args.command=='update':
            backup=apply(args.wiki.resolve(),files,expected,args.output/'backups')
            if backup:
                (args.output/'last-backup.txt').write_text(str(backup),'utf8')
                (backup/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
                (backup/'report.md').write_text(report_markdown(report),'utf8')
                print('更新完成；备份：'+str(backup))
                if not args.no_rebuild:rebuild_wiki(print)
            else:print('数据已是当前版本，无需修改。')
        else:print('预览完成，Wiki 未写入。')
        print(f"角色：{', '.join(c['name'] for c in report['characters'])}\n变动文件：{report['changedFiles']}；字段差异：{len(report['conflicts'])}；缺失原资源：{len(report['missingAssets'])}")
        print('报告：'+str(args.output/'update-report.md'))
        return 0
    except (ValueError,RuntimeError,OSError,KeyError) as error:
        print('错误：'+str(error),file=sys.stderr);return 1

