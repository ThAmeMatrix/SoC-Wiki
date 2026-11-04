"""Prepare an SoCwiki update without changing its raw BWIKI archive."""
from __future__ import annotations
from pathlib import Path
from collections import Counter, defaultdict
from copy import deepcopy
import base64
import hashlib
import html
import importlib.util
import io
import json
import os
import re

from bs4 import BeautifulSoup
from PIL import Image
from .assets import Assets
from .model import RANK_NAMES, STAT_BASIS, plain, ids
from .pedestal import pedestal_image, compose as compose_pedestal, encode as encode_webp
from . import ranges, rangetiles, pinyin
from .richtext import render
from .transaction import sha

def dumps(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':')).replace('</script','<\\/script')

def _thumbnail(job):
    """Worker for the infographic pass: shrink one image and encode it as a base64 WebP URI."""
    path,content=job
    try:
        with Image.open(io.BytesIO(content)) as image:
            width,height=image.size
            image.thumbnail((1800,1800) if max(image.size)>1000 else (192,192),Image.Resampling.LANCZOS)
            output=io.BytesIO();image.save(output,format='WEBP',lossless=True,method=4)
        return path,'data:image/webp;base64,'+base64.b64encode(output.getvalue()).decode('ascii'),width,height
    except Exception:
        return path,None,0,0

def _run_thumbnails(pairs, workers):
    """Encode post-images in worker processes; whatever fails is redone in-process."""
    results={}
    if len(pairs)>8 and workers>1:
        try:
            from concurrent.futures import ProcessPoolExecutor, as_completed
            with ProcessPoolExecutor(max_workers=workers) as pool:
                futures={pool.submit(_thumbnail,pair):pair[0] for pair in pairs}
                for future in as_completed(futures):
                    try:
                        path,encoded,width,height=future.result()
                        results[path]=(path,encoded,width,height)
                    except Exception:pass
        except Exception:pass
    for path,content in pairs:
        if path not in results:results[path]=_thumbnail((path,content))
    return [results[path] for path,_ in pairs]

def load_js(path):
    text=path.read_text('utf8')
    return json.JSONDecoder().raw_decode(text[text.index('=')+1:])[0]

def js(key,value,suffix=''):
    return (key+'='+dumps(value)+';'+suffix+'\n').encode('utf8')

def module(path,name):
    import sys
    spec=importlib.util.spec_from_file_location(name,path);result=importlib.util.module_from_spec(spec)
    sys.modules[name]=result;spec.loader.exec_module(result);return result

def visible(text):return BeautifulSoup(text or '', 'html.parser').get_text(' ',strip=True)

# Client-imported pages sort after every archived page.
ORDER_BASE = 1_000_000

def patch_ui(wiki,files,observed):
    """Small compatibility changes; refuse an unfamiliar app instead of guessing."""
    def read(name):
        raw=(wiki/name).read_bytes();observed[name]=sha(raw)
        return raw.decode('utf8').replace('\r\n','\n')
    app=read('app.js')
    if 'doc.clientSource' not in app:
        start='  function sourceFooter(doc){return '
        if app.count(start)!=1:raise ValueError('Wiki 的来源显示函数已改变，需适配后才能更新')
        replacement='''  function sourceFooter(doc){
    if(doc.clientSource){const s=doc.clientSource;return `<div class="source-footer"><span>游戏客户端配置 · 资源版本 ${esc(s.changeNumber)} · 提取 ${esc(s.extractedAt.slice(0,10))}${s.availableAt?' · 配置开放时间 '+esc(s.availableAt.slice(0,16).replace('T',' ')):''}</span>${doc.source?`<a href="${esc(doc.source)}" target="_blank" rel="noopener noreferrer">Wiki 原始记录 ↗</a>`:'<a href="data/client-provenance.json" download>数据来源记录</a>'}</div>`;}
    return '''
        app=app.replace(start,replacement)
    marker='${profile}<nav class="detail-tabs"'
    if 'doc.clientStatBasis' not in app:
        if app.count(marker)!=1:raise ValueError('Wiki 的角色属性区域已改变，需适配后才能更新')
        app=app.replace(marker,'${profile}${doc.clientStatBasis?`<p class="source-notice">满级属性口径：${esc(doc.clientStatBasis)}</p>`:\'\'}<nav class="detail-tabs"')
    files['app.js']=app.encode('utf8')
    character=read('character-ui.js')
    before='const node = {key:layer.rank+\'-\'+side, name, side, rank:layer.rank, page};'
    after='const node = {key:layer.rank+\'-\'+side, name:page?.name || name, side, rank:layer.rank, page};'
    if after not in character:
        if character.count(before)!=1:raise ValueError('Wiki 的技能树节点结构已改变，需适配后才能更新')
        character=character.replace(before,after)
    files['character-ui.js']=character.encode('utf8')
    # 纯客户端解析的资料馆没有联网增量更新（wiki-updates.js 已移除），跳过这段兼容补丁。
    if (wiki/'wiki-updates.js').is_file():
        updates=read('wiki-updates.js')
        if 'function preserveClientPages' not in updates:
            before='    active=snapshot;if(!active)return;let downloadedBytes=0;'
            if updates.count(before)!=1:raise ValueError('Wiki 的在线更新结构已改变，需适配后才能更新')
            helper='''  // Locally imported client pages take precedence over cached BWIKI revisions.
  function preserveClientPages(snapshot){
    if(!snapshot)return snapshot;
    const local=new Set(window.WIKI_DATA.pages.filter(p=>p.clientManaged).map(p=>p.id));
    return {...snapshot,records:Object.fromEntries(Object.entries(snapshot.records||{}).filter(([id])=>!local.has(Number(id)))),deleted:(snapshot.deleted||[]).filter(id=>!local.has(Number(id)))};
  }
'''
            updates=updates.replace('  async function activate(snapshot){',helper+'  async function activate(snapshot){')
            updates=updates.replace(before,'    active=preserveClientPages(snapshot);if(!active)return;let downloadedBytes=0;')
        files['wiki-updates.js']=updates.encode('utf8')

def plan_update(wiki: Path, game: Path, snapshot: dict, names=None, all_existing=False, refresh=False,
                sprite_variant='base', progress=None):
    """``progress(message, done, total)`` receives stage lines and throttled item counts."""
    import time as _time
    last=[0.0]
    def say(message,done=None,total=None,force=True):
        if progress is None:
            if force:print(message,flush=True)
            return
        now=_time.monotonic()
        if not force and done!=total and now-last[0]<0.5:return
        last[0]=now;progress(message,done,total)
    observed={}
    index=wiki/'data/index.js'
    if not index.is_file():
        # No offline snapshot present yet: bootstrap a minimal but valid wiki
        # index so the pulled client resources can be written in one click
        # instead of failing with "not a SoCwiki archive".
        (wiki/'data').mkdir(parents=True, exist_ok=True)
        index.write_text(
            'window.WIKI_DATA=' + json.dumps(
                {'pages': [], 'titles': {}, 'archive': {'expectedPages': 0, 'wikiSnapshotExpectedPages': 0}},
                ensure_ascii=False, separators=(',', ':')) + ';window.WIKI_PAGES={};\n',
            encoding='utf-8')
        (wiki/'data/search.js').write_text('window.WIKI_SEARCH={};\n', encoding='utf-8')
        (wiki/'data/advanced-search.js').write_text('window.WIKI_ADVANCED_DATA={};\n', encoding='utf-8')
        print('资料馆还没有 data/index.js，已用客户端资源初始化空索引，稍后将写入角色数据。')
    def read_json(name,assignment=False):
        raw=(wiki/name).read_bytes();observed[name]=sha(raw);text=raw.decode('utf8')
        return json.JSONDecoder().raw_decode(text[text.index('=')+1:])[0] if assignment else json.loads(text)
    say('读取资料馆索引 data/index.js…')
    data=read_json('data/index.js',True);by_id={p['id']:p for p in data['pages']}
    # 资料馆里同一批角色名的分隔符并不统一（既有「科尔•破晓之影」也有「萨曼莎·不灭微光」）。
    # 客户端只有塔罗图标会换成「•」，其余都是「·」，所以按折叠后的名字匹配，避免同名条目分裂成两份。
    def fold(name):
        """归一化名字里写法不一致的分隔符与逗号，用于匹配资料馆既有条目。"""
        return (name or '').replace('•','·').replace('，',',')

    def name_variants(name):
        out={name or ''}
        for a,b in (('•','·'),('，',',')):
            for variant in list(out):
                out.add(variant.replace(a,b));out.add(variant.replace(b,a))
        return out
    by_name=defaultdict(list)
    folded=defaultdict(list)
    for page in data['pages']:
        if page['type']=='character' and not page.get('redirect'):
            by_name[page['name']].append(page);folded[fold(page['name'])].append(page)
    def lookup(name):
        exact=by_name.get(name)
        if exact:return exact
        return folded.get(fold(name)) or []
    current={c['name']:c for c in snapshot['characters']}
    if names:
        absent=set(names)-current.keys()
        if absent:raise ValueError('客户端没有这些角色（请查看 output/characters.json）：'+', '.join(sorted(absent)))
        selected=[current[name] for name in dict.fromkeys(names)]
    elif all_existing:
        if data['pages']:
            selected=[c for c in snapshot['characters']
                      if c['available'] and (c['name'] in by_name or fold(c['name']) in folded)]
        else:
            # Fresh wiki (just bootstrapped from the client): populate every available character.
            selected=[c for c in snapshot['characters'] if c['available']]
    else:raise ValueError('请指定 --character，或使用 --all 更新已匹配并开放的角色')
    if not selected:raise ValueError('没有可更新的角色')
    duplicate=[c['name'] for c in selected if len(lookup(c['name']))>1]
    if duplicate:raise ValueError('Wiki 存在同名角色，无法唯一匹配：'+', '.join(duplicate))
    say(f'已选择 {len(selected)} 个角色；资料馆现有 {len(data["pages"])} 个页面')

    old_manifest_path=wiki/'data/client-manifest.json'
    manifest=read_json('data/client-manifest.json') if old_manifest_path.exists() else {'schemaVersion':1,'ids':{},'characters':{}}
    if not old_manifest_path.exists():observed['data/client-manifest.json']=None
    files={};docs={};report={'characters':[],'fieldChanges':[],'conflicts':[],'missingAssets':[],
        'unmatchedWikiCharacters':sorted(set(by_name)-set(current)),
        'clientFingerprint':snapshot['client']['fingerprint'],'clientVersion':snapshot['client']['version'],
        'warnings':list(snapshot['warnings'])}
    say('打开客户端资源目录（asset_bundle）…')
    assets=Assets(game)
    # 差量更新：上一轮已经解出的贴图直接复用（输出仍在且客户端包未变），不必重新解码。
    prior_assets=(read_json('data/client-provenance.json') or {}).get('assets') if (wiki/'data/client-provenance.json').exists() else None
    reused=assets.reuse(prior_assets,wiki)
    if reused:say(f'复用已提取资源：{reused} 个')
    say('读取战斗地块贴图…')
    tiles=rangetiles.set(game)
    pedestal_cache={}
    def pedestal_for():
        if 'value' not in pedestal_cache:
            pedestal_cache['value']=pedestal_image()
        return pedestal_cache['value']
    skills={int(k):v for k,v in snapshot['skills'].items()}
    traits={int(k):v for k,v in snapshot['traits'].items()}
    statuses={int(k):v for k,v in snapshot['statuses'].items()}
    weapons={int(k):v for k,v in snapshot.get('weapons',{}).items()}
    search=read_json('data/search.js',True);advanced=read_json('data/advanced-search.js',True)
    char_helpers=module(wiki/'scripts/character_data.py','socwiki_character_data')
    star_helpers=module(wiki/'scripts/infographic_stars.py','socwiki_infographic_stars')
    infographic=read_json('data/infographic.js',True) if (wiki/'data/infographic.js').exists() else None
    source={'changeNumber':snapshot['client']['version']['change_number'],
        'fingerprint':snapshot['client']['fingerprint'],'extractedAt':snapshot['extractedAt']}

    def document(pid):
        if pid not in docs:
            path=wiki/f'data/pages/{pid}.js'
            if not path.exists():observed[f'data/pages/{pid}.js']=None
            docs[pid]=read_json(f'data/pages/{pid}.js',True) if path.exists() else {'id':pid,'fields':{},'rawFields':{},'related':[],
                'recoveredFields':[],'revision':0,'sections':[],'source':'','hasOnlineMedia':False}
        return docs[pid]

    def retitle(entry,prefix,name):
        """Adopt a name the client filled in after this entry was first filed.

        Weapons in particular ship with a placeholder (装备 251 was once listed as
        「SSR副武器251」) and only receive their real name in a later client build.
        The page body follows the new name but the catalogue entry kept the old one,
        so the gallery and search showed the placeholder. Leave the entry alone when
        the new title already belongs to a different page.
        """
        title=prefix+'/'+name
        if entry.get('name')==name:return
        if data['titles'].get(title,entry['id'])!=entry['id']:return
        say(f"条目改名：{entry['title']} → {title}")
        data['titles'].pop(entry['title'],None)
        data['titles'][title]=entry['id']
        entry['title']=title;entry['name']=name
        document(entry['id'])['title']=title

    def record(kind,gid,name,owner):
        identity=kind+':'+str(gid)
        prefix={'skill':'技能图鉴库','talent':'个性','status':'中括号介绍','character':'角色图鉴库',
            'equipment':'装备图鉴库','liberation':'极限解放'}[kind]
        if identity in manifest['ids'] and manifest['ids'][identity] in by_id:
            pid=manifest['ids'][identity]
            retitle(by_id[pid],prefix,name)
            return by_id[pid],document(pid)
        title=prefix+'/'+name
        # 装备名与极限解放名在资料馆里是唯一的，已有一个同名条目时直接复用它，
        # 否则会另建「装备图鉴库/长夜流光（长夜流光）」这类副本，而真正被链接指向的
        # 旧条目永远拿不到客户端数据（装备贴图就是这么错位的）。
        # 「技能名+」是塔罗右支的加强技能，同理复用。
        shared=data['titles'].get(title)
        reuse=shared is not None and (kind in ('liberation','equipment') or (kind=='skill' and name.endswith('+')))
        if shared is None:
            # 名字里的分隔符／标点不统一（客户端「圣启·第七号角」↔ 资料馆「圣启•第七号角」，
            # 「全员，向中间看齐！」↔「全员,向中间看齐！」），换写法再找一次；
            # 否则同一个技能／解放／装备会分裂成两个条目。
            for alt in name_variants(name)-{name}:
                shared=data['titles'].get(prefix+'/'+alt)
                if shared is not None:
                    reuse=kind in ('liberation','equipment','skill')
                    break
        if reuse:
            manifest['ids'][identity]=shared
            return by_id[shared],document(shared)
        if title in data['titles']:title+='（'+owner+'）'
        if title in data['titles']:title+='·'+str(gid)
        pid={'skill':100_000_000,'talent':200_000_000,'status':300_000_000,'character':400_000_000,
            'equipment':500_000_000,'liberation':600_000_000}[kind]+gid
        if pid in by_id:raise ValueError('客户端页面 ID 与现有页面冲突：'+str(pid))
        entry={'id':pid,'title':title,'name':name,'type':'talent' if kind=='liberation' else kind,'image':'','date':snapshot['extractedAt'][:10],
            'summary':'','categories':['极限解放','客户端资料'] if kind=='liberation' else ['客户端资料'],'class':'','rarity':'','faction':'','weapon':'','aliases':'','redirect':False,
            # Imported pages follow the whole archive instead of jumping to the front.
            'sourceOrder':ORDER_BASE+pid}
        by_id[pid]=entry;data['pages'].append(entry);data['titles'][title]=pid
        manifest['ids'][identity]=pid;doc=document(pid);doc['title']=title
        return entry,doc

    def record_equipment(weapon, owner, related_pid=None):
        """为单把武器生成（或更新）装备图鉴页面。related_pid 仅在由角色专武调用时传入，
        用于把角色页关联回去；纯武器条目传 None，避免覆盖已有的关联集合。"""
        we,wd=record('equipment',weapon['id'],weapon['name'],owner)
        star_names=('一','二','三','四','五')
        stars=weapon.get('stars') or {}
        raw_weapon={'装备名称':weapon['name'],'装备类型':weapon['type'],'稀有度':weapon['rarity'],'装备描述':weapon['desc']}
        for index,star in enumerate(star_names):
            item=stars.get(str(index+1))
            raw_weapon[star+'星技能']=item['description'] if item else ''
        fields_weapon={key:html.escape(value) for key,value in raw_weapon.items()}
        for index,star in enumerate(star_names):
            item=stars.get(str(index+1))
            if item:fields_weapon[star+'星技能']=render(item['rawDescription'],links)
        stat_row=''.join('<div><dt>'+html.escape(key)+'</dt><dd>'+html.escape(str(value))+'</dd></div>'
            for key,value in weapon.get('stats',{}).items())
        # 装备的五个星级同样做逐星对照：公共效果与每星的变化，和个性页一个看法。
        comparison=char_helpers.star_comparison(fields_weapon,[star+'星技能' for star in star_names])
        wd.update(fields=fields_weapon,rawFields=raw_weapon,
            html='<h2>游戏客户端装备资料</h2><p class="source-notice">等级属性取自客户端等级表（等级 '+html.escape(str(weapon['stats'].get('等级','')))+'），未包含星级与突破加成。</p><dl class="fact-grid">'+stat_row+'</dl>'
                +''.join('<h3>'+star+'技能</h3>'+fields_weapon[star+'星技能'] for star in star_names if fields_weapon.get(star+'星技能')),
            starComparison=comparison,
            clientSource={**source,'table':'online_weapon','rowId':weapon['id']})
        if related_pid is not None:
            wd['related']=sorted(set(wd.get('related',[])+[related_pid]))
        weapon_art=assets.get(weapon.get('art',''))
        we.update({'summary':weapon['desc'][:220],'rarity':weapon['rarity'],'weapon':weapon['type'],
            'image':weapon_art or ''})
        return we,wd

    selected_pids={}
    pedestal_info={}
    for char in selected:
        if lookup(char['name']):entry=lookup(char['name'])[0];doc=document(entry['id'])
        else:entry,doc=record('character',char['id'],char['name'],char['name'])
        selected_pids[char['id']]=entry['id']
        # 折叠后匹配上的（如客户端「科尔·破晓之影」↔ 资料馆「科尔•破晓之影」）以资料馆写法为准，
        # 免得同一个角色出现两套名字。
        if fold(entry['name'])==fold(char['name']):char['name']=entry['name']

    # 同一个极限解放（尤其是通用模组）可被多个角色习得，先汇总再生成页面。
    pid_by_name={char['name']:selected_pids[char['id']] for char in selected}
    liberation_owners=defaultdict(list)
    for char in selected:
        for item in char.get('liberations') or []:
            levels=sorted((item.get('levels') or []),key=lambda row:row.get('level') or 0)[:3]
            if not levels:continue
            owners=liberation_owners[levels[0]['skillId']]
            if char['name'] not in owners:owners.append(char['name'])

    def cost_text(level):
        """一级极限解放的升级消耗：资金 + 各材料数量，全部取自客户端配置。"""
        parts=[]
        if level.get('money'):parts.append(f"{level.get('moneyName') or '资金'} {level['money']}")
        for material in level.get('materials') or []:
            parts.append(f"{material['name']} ×{material['count']}")
        return '，'.join(parts)

    # Exclusive weapons matched by the client's own editor naming (…[角色名|…]专武N).
    char_weapons={}
    for char in selected:
        matches=[w for w in weapons.values() if w['stars'] and char['name'] in w['owners']]
        if len(matches)>1:raise ValueError('客户端数据把 '+char['name']+' 匹配到多把专武，请人工确认：'+', '.join(w['name'] for w in matches))
        if matches:char_weapons[char['id']]=matches[0]

    # Resolve the transitive glossary just for this update.
    status_by_name=defaultdict(list)
    for kid,item in statuses.items():status_by_name[item['name']].append(kid)
    wanted=set()
    # Which characters actually bring a keyword up: a glossary entry is far more
    # useful when it points back at its holders (「法皇圣权」→ 君士坦丁).
    status_characters=defaultdict(set)
    char_id_by_name={char['name']:char['id'] for char in selected}
    def keywords(text,explicit=(),owner=None):
        wanted.update(k for k in explicit if k in statuses)
        for term in re.findall(r'\[([^\[\]]+)\]',plain(text)):
            found=status_by_name.get(term,[])
            if len(found)==1:
                wanted.add(found[0])
                if owner is not None:status_characters[found[0]].add(owner)
    needed_skills={}
    skill_classes={}
    enhanced_skills=set()
    for char in selected:
        for node in char['tree']:
            needed_skills[node['skillId']]=char['name']
            # 塔罗右支是左支的加强版，客户端里两者同名；资料馆沿用「技能名+」区分。
            if node.get('enhanced'):enhanced_skills.add(node['skillId'])
            if char.get('class'):skill_classes.setdefault(node['skillId'],set()).add(char['class'])
        trait=traits.get(char['personalityId'])
        if trait:
            for level in trait['stars'].values():
                keywords(level['description'],owner=char['id'])
                for sid in level['skillIds']:
                    row=skills.get(sid)
                    if row:keywords(row['desc'],ids(row.get('keyword_ids')),char['id'])
        weapon=char_weapons.get(char['id'])
        if weapon:
            for star in weapon['stars'].values():
                keywords(star['rawDescription'],owner=char['id'])
    # 被「技能替换」换上来的技能（如 神怒·断）不在任何技能树上，但页面上要能点进去，
    # 所以按来源技能的归属一并建页。
    queue=list(needed_skills)
    while queue:
        sid=queue.pop()
        for switch in skills.get(sid,{}).get('switches') or []:
            if switch['skillId'] not in needed_skills:
                needed_skills[switch['skillId']]=needed_skills[sid];queue.append(switch['skillId'])
    for sid,owner in needed_skills.items():
        row=skills.get(sid)
        if row:keywords(row['desc'],ids(row.get('keyword_ids')),char_id_by_name.get(owner))
    seen=set()
    while wanted-seen:
        kid=min(wanted-seen);seen.add(kid);keywords(statuses[kid]['description'])
    links={};status_records={}
    for kid in sorted(wanted):
        item=statuses[kid];entry,doc=record('status',kid,item['name'],selected[0]['name'])
        status_records[kid]=(entry,doc);links[item['name']]=entry['id']
    say(f'生成关键词页面：{len(status_records)} 个')
    for index,(kid,(entry,doc)) in enumerate(status_records.items(),1):
        say(f'关键词页面 {index}/{len(status_records)}',index,len(status_records),False)
        item=statuses[kid];description=render(item['description'],links)
        # 词条页的「关联」指向引用它的角色；按角色在客户端里的顺序排，读起来稳定。
        holders=sorted({selected_pids[cid] for cid in status_characters.get(kid,()) if cid in selected_pids})
        doc.update(fields={'介绍':description},rawFields={'介绍':plain(item['description'])},
            html='<div class="definition">'+description+'</div>',clientSource={**source,'table':item['sourceTable'],'rowId':item['ref_text_id'],'keywordId':kid},
            related=holders)
        entry['summary']=plain(item['description'])[:220]
        # Keyword icons can refer to skill or buff bundles.
        folder='buff' if item['sourceTable']=='buff' else 'skill'
        entry['image']=assets.get('icon/'+folder+'/'+item['icon']) if item['icon'] else ''

    skill_records={}
    say(f'生成技能页面与范围图：{len(needed_skills)} 个')
    for index,(sid,owner) in enumerate(sorted(needed_skills.items()),1):
        say(f'技能页面 {index}/{len(needed_skills)}',index,len(needed_skills),False)
        item=skills[sid]
        if not item['name']:raise ValueError(f'技能树 {sid} 缺少显示名称')
        name=plain(item['name'])+('+' if sid in enhanced_skills else '')
        entry,doc=record('skill',sid,name,owner);skill_records[sid]=(entry,doc)
        classes=sorted(skill_classes.get(sid,set()))
        if classes:entry['categories']=['客户端资料',*(c+'技能' for c in classes)]
        is_passive=item['type']==3 or item['class_type'] in (2,3,6,7)
        distance='/' if is_passive else ('特殊（见说明）' if item['range_max']>=99 else str(item['range_min']) if item['range_min']==item['range_max'] else f"{item['range_min']}-{item['range_max']}")
        clean=plain(item['desc'])
        area='单体' if '单体' in clean or (item['class_type']==1 and '范围' not in clean) else '见技能说明'
        raw={'技能名称':entry['name'],'技能描述':clean,'技能消耗':'/' if is_passive else str(item['tp']),
            '技能冷却':'/' if is_passive else str(item['cooldown']),'技能射程':distance,'技能范围':'/' if is_passive else area,
            '技能类别':clean.partition('）')[0].removeprefix('（') if clean.startswith('（') else '技能'}
        fields={k:html.escape(v) for k,v in raw.items()};fields['技能描述']=render(item['desc'],links)
        if item.get('switches'):
            raw['变更后技能']='、'.join(sw['name'] for sw in item['switches'])
            fields['变更后技能']=html.escape(raw['变更后技能'])
        entry['image']=assets.get('icon/skill/'+item['icon']) if item['icon'] else ''
        entry['summary']=clean[:220]
        doc.update(fields=fields,rawFields=raw,html='<div class="ability-description">'+fields['技能描述']+'</div>',
            clientSource={**source,'table':'skill','rowId':sid,'displayRowId':item['displayId']})
        doc['clientRange']={k:item[k] for k in ('range_min','range_max','range_width','target_method','target_select','target_width','target_param','attack_up','attack_down')}
        # 范围图仅在客户端字段/描述惯例能确定形状时绘制，否则保留文本。
        diagram=ranges.plan(item)
        if diagram:
            content=ranges.render_png(diagram,tiles)
            # The Wiki only lifts a range figure out of doc.html when the file
            # lives under assets/wiki/ or assets/updates/ and the alt starts
            # with “技能范围 ” (see character-ui.js rangeImage).
            relative='assets/updates/range-'+sha(content)[:24]+'.webp'
            assets.files[relative]=content
            doc['clientRange']['image']=relative
            doc['clientRange']['label']=diagram['label']
            # A figure carried over from the online wiki would otherwise come first
            # in doc.html and win in character-ui.js rangeImage().
            doc['html']=re.sub(r'<img[^>]*alt="[^"]*技能范围[^"]*"[^>]*>','',doc['html'])
            if raw['技能范围'] in ('/','单体','见技能说明'):
                raw['技能范围']=diagram['label']
                fields['技能范围']=html.escape(diagram['label'])
                doc['rawFields']['技能范围']=diagram['label'];doc['fields']['技能范围']=fields['技能范围']
            doc['html']+='<h3>技能范围</h3><p class="source-notice">范围图用客户端战斗地块贴图（技能范围/攻击范围/目标标记）按范围字段与技能说明拼合。</p><img class="range-diagram" src="'+relative+'" alt="技能范围 '+entry['name']+'" width="280">'

    # 「使用后技能变更」要等所有技能页都建好，才能把目标技能链成链接（目标可能排在后面）。
    switch_from={}
    for sid,item in skills.items():
        for switch in item.get('switches') or []:
            switch_from.setdefault(switch['skillId'],[]).append(
                {'skillId':sid,'name':plain(item['name']),'via':switch.get('via') or '',
                 'turns':switch.get('turns') or 0,'mode':switch.get('mode') or 'buff'})
    def switch_note(switch):
        """括号里的来源说明：带持续回合的 BUFF、挂在某个切换技能上、或用完撤下的 BUFF。"""
        via=switch.get('via') or ''
        if switch.get('mode')=='direct':
            return '（经「%s」切换）'%html.escape(via) if via else ''
        if switch.get('mode')=='revert':
            return '（移除「%s」）'%html.escape(via) if via else ''
        note=via
        if switch.get('turns'):note+='，保留 %s 回合'%switch['turns']
        return '（%s）'%html.escape(note) if note else ''
    def note_markup(note):
        return '<span class="switch-note">%s</span>'%note if note else ''
    for sid,(entry,doc) in skill_records.items():
        switches=skills[sid].get('switches') or []
        sources=switch_from.get(sid) or []
        if not switches and not sources:continue
        def switch_link(skill_id,label):
            """把关联技能链成链接；没有页面的（未收录的技能）就只留名字。"""
            target=skill_records.get(skill_id)
            if not target:return html.escape(label)
            doc['related']=sorted(set(doc.get('related',[])+[target[0]['id']]))
            return '<a href="#/page/%d">%s</a>'%(target[0]['id'],html.escape(label))
        rows=[];inline=[]
        for switch in switches:
            suffix=note_markup(switch_note(switch))
            link=switch_link(switch['skillId'],switch['name'])
            rows.append('<div>'+link+suffix+'</div>')
            # 撤下切换 BUFF 的那种是「变回去」，措辞上跟换到下一段区分开。
            verb='恢复为' if switch.get('mode')=='revert' else '变更为'
            inline.append('使用后'+verb+' '+link+suffix)
        if switches:
            doc['html']+='<h3>使用后技能变更</h3><div class="skill-switches">'+''.join(rows)+'</div>'
        # 反向：这个技能是被别的技能换上来的，也把来源标出来。
        back=[];back_inline=[]
        for origin in sources:
            suffix=note_markup(switch_note(origin))
            link=switch_link(origin['skillId'],origin['name'])
            back.append('<div>'+link+suffix+'</div>');back_inline.append('由 '+link+' 变更而来'+suffix)
        if back:
            doc['html']+='<h3>由其它技能变更而来</h3><div class="skill-switches">'+''.join(back)+'</div>'
        # 技能页的正文只渲染 fields['技能描述']（doc.html 收在折叠的「完整原文」里），
        # 所以把这段也接在描述后面，打开技能页就能看到。
        notes=inline+back_inline
        if notes:
            doc['fields']['技能描述']+=''.join(
                '<div class="skill-switch-line">%s</div>'%note for note in notes)

    # 立绘解码（Unity 贴图 + 无损 WebP）是整轮最贵的一步，先把角色与武器需要的贴图
    # 交给多个进程并行解出，下面的顺序循环就只命中缓存。
    pending=[]
    for char in selected:
        for picture in char['portraits']:
            pending.append(picture['asset'])
            if picture.get('fallback'):pending.append(picture['fallback'])
        for key in ('avatar','sprite'):
            if char.get(key):pending.append(char[key])
        for variant in (char.get('spriteVariants') or []):
            if variant.get('asset'):pending.append(variant['asset'])
        trait=traits.get(char['personalityId'])
        if trait and trait.get('icon'):pending.append('icon/unitpersonality/'+trait['icon'])
        for item in (char.get('liberations') or []):
            if item.get('icon'):pending.append('icon/skill/'+item['icon'])
    for weapon in weapons.values():
        if weapon.get('art'):pending.append(weapon['art'])
    assets.prefetch(pending,log=lambda message:say(message))
    say(f'生成角色页面、立绘与像素小人：{len(selected)} 个')
    for index,char in enumerate(selected,1):
        say(f'角色 {index}/{len(selected)}：{char["name"]}',index,len(selected),False)
        pid=selected_pids[char['id']];entry=by_id[pid];doc=document(pid)
        trait=traits.get(char['personalityId']);trait_leaf=''
        if trait:
            te,td=record('talent',trait['id'],plain(trait['name']),char['name']);trait_leaf=te['title'].split('/',1)[1]
            # 个性效果文案以客户端 skills[skillId].desc 为准（含 <style> 配色与 [词条] 链接），
            # 通过 traits[].stars[].skillIds 逐星取到对应技能描述后拼接。
            fields={};raw={}
            for star in range(1,6):
                sv=trait['stars'].get(str(star),{})
                parts=[]
                for sid in (sv.get('skillIds') or []):
                    row=skills.get(sid)
                    if row and row.get('desc'):parts.append(row['desc'])
                text='\n'.join(parts) or sv.get('description','')
                fields['个性描述'+str(star)]=render(text,links)
                raw['个性描述'+str(star)]=plain(text)
            td.update(fields=fields,rawFields=raw,html=''.join(f'<h3>{n} 星</h3>'+fields['个性描述'+str(n)] for n in range(1,6)),
                starComparison=char_helpers.star_comparison(fields),clientSource={**source,'table':'unit_personality','rowId':trait['id'],'stars':trait['stars']})
            td['related']=sorted(set(td.get('related',[])+[pid]));te['summary']=raw['个性描述5'][:220]
            te['image']=assets.get('icon/unitpersonality/'+trait['icon']) if trait['icon'] else ''
            if infographic:infographic['starEffects'][str(te['id'])]=star_helpers.combine_stars(list(fields.values()))
        weapon=char_weapons.get(char['id'])
        if weapon:
            record_equipment(weapon,char['name'],pid)
        # 极限解放：one page per liberation skill, listing its three client levels.
        liberation_names=[]
        for item in char.get('liberations') or []:
            levels=sorted((item.get('levels') or []),key=lambda row:row.get('level') or 0)[:3]
            if not levels:continue
            gid=levels[0]['skillId']
            le,ld=record('liberation',gid,item['name'],char['name'])
            # 极限解放描述以 skills[skillId].desc 为准（含配色与词条链接）
            descs=[]
            for level in levels:
                sid=level.get('skillId');row=skills.get(sid) if sid else None
                descs.append(row['desc'] if row and row.get('desc') is not None else level['desc'])
            owners=liberation_owners.get(gid) or []
            raw_liberation={'极限解放名称':item['name'],'极限解放图标':item['name'],
                '可习得角色':'、'.join(owners)}
            for index,desc in enumerate(descs):raw_liberation['极限解放描述'+str(index+1)]=plain(desc)
            for index,level in enumerate(levels):raw_liberation['极限解放材料'+str(index+1)]=cost_text(level)
            # 复用资料馆已有的解放条目时，保留它原有的事实字段（如主/副解放材料），只覆盖客户端解析出的部分。
            raw_liberation={**(ld.get('rawFields') or {}),**raw_liberation}
            fields_liberation={key:html.escape(value) for key,value in raw_liberation.items()}
            for index,desc in enumerate(descs):fields_liberation['极限解放描述'+str(index+1)]=render(desc,links)
            # 可习得角色：用像素小人头像并给出链接，便于从解放页回溯（不需要可放大的大图）。
            def owner_card(name):
                target=pid_by_name.get(name);page=by_id.get(target) if target else None
                art=html.escape((page or {}).get('sprite') or (page or {}).get('avatar') or '')
                image=f'<img src="{art}" alt="" loading="lazy">' if art else ''
                label=f'<span>{html.escape(name)}</span>'
                if target:return f'<a class="liberation-owner" href="#/page/{target}">{image}{label}</a>'
                return f'<span class="liberation-owner">{image}{label}</span>'
            owners_html=('<h3>可习得角色</h3><div class="liberation-owners">'
                         +''.join(owner_card(name) for name in owners)+'</div>') if owners else ''
            # 升级消耗只写在对应等级下面（每级材料不同），不再单独列一张总表。
            def cost_markup(level):
                parts=[]
                if level.get('money'):
                    parts.append('<span class="cost-item">'+html.escape(level.get('moneyName') or '资金')
                                 +' '+str(level['money'])+'</span>')
                for material in level.get('materials') or []:
                    src=assets.get('icon/material/'+material['icon']) if material.get('icon') else ''
                    image=f'<img class="material-icon" src="{html.escape(src)}" alt="" loading="lazy">' if src else ''
                    parts.append('<span class="cost-item">'+image+html.escape(material['name'])
                                 +' ×'+str(material['count'])+'</span>')
                return '<p class="liberation-cost">升级消耗：'+''.join(parts)+'</p>' if parts else ''
            levels_html=''.join(
                '<h3>'+str(index+1)+' 级</h3>'+fields_liberation['极限解放描述'+str(index+1)]
                +cost_markup(level)
                for index,level in enumerate(levels))
            ld.update(fields=fields_liberation,rawFields=raw_liberation,
                html='<h2>游戏客户端极限解放资料</h2><p class="source-notice">取自客户端模组技能链，按客户端的等级效果原样呈现。</p>'
                    +owners_html+levels_html,
                clientSource={**source,'table':'online_module_skill','rowId':gid})
            ld['related']=sorted(set(ld.get('related',[])+[pid]))
            liberation_art=assets.get('icon/skill/'+item.get('icon','')) if item.get('icon') else ''
            le.update({'summary':(levels[0]['desc'] or '')[:220],'image':liberation_art})
            liberation_names.append(item['name'])
        changes={'角色名称':char['name'],'显示名称':char['name'],'角色职业':char['class'],'武器类型':char['weapon'],
            '特职':char['profession'],'稀有度':char['rarity'],'所属阵营':'，'.join(char['factions']),
            '移动':str(char['movement']),'跳跃高度':str(char['jumpUp']),'跳跃远度':str(char['jumpDown']),
            '性别':char['gender'],'中文CV':char['cv']['zh'],'日文CV':char['cv']['ja'],'角色生平':char['story'],'个性':trait_leaf}
        changes.update({'初始'+key:str(value) for key,value in char['baseStats'].items()})
        changes.update({'满级满星'+key:str(value) for key,value in char['stats'].items()})
        if weapon:changes['专武']=weapon['name']
        if liberation_names:changes['极限解放']='，'.join(liberation_names)
        for node in char['tree']:
            se,sd=skill_records[node['skillId']]
            if node['rank']==0:
                if node['side']>1:
                    report['warnings'].append(char['name']+'有额外初始技能，已保留于导出 JSON');continue
                key=['初始普攻','初始技能'][node['side']]
            elif node['rank'] in RANK_NAMES:key=RANK_NAMES[node['rank']]+'阶技能'+['左','右'][node['side']]
            else:continue
            changes[key]=se['title'].split('/',1)[1];sd['related']=sorted(set(sd.get('related',[])+[pid]))
        # Clear phantom right-side skill fields: characters whose tree has a left (side=0) branch
        # at a rank but no right (side=1) branch (e.g. tarot characters) must not keep a stale
        # right-skill name from a previous generation — otherwise the infographic's right node
        # would display the left skill's effect.
        present_sides={}
        for node in char['tree']:present_sides.setdefault(node['rank'],set()).add(node['side'])
        for rank,right_key in ((0,'初始技能'),*((r,RANK_NAMES[r]+'阶技能右') for r in RANK_NAMES)):
            if rank not in present_sides or 1 not in present_sides[rank]:
                if right_key not in changes:changes[right_key]=''
        previous=set(doc.get('clientFields',[]));owned=set(previous)
        for key,new in changes.items():
            if not new:
                # explicit clear of a phantom field previously managed by the client pipeline
                if key in previous:
                    old=doc['rawFields'].get(key,'')
                    if old:
                        report['fieldChanges'].append({'character':char['name'],'field':key,'before':old,'after':''})
                        doc['rawFields'][key]='';doc['fields'][key]='';owned.discard(key)
                continue
            old=doc['rawFields'].get(key,'')
            if refresh or key in previous or old in ('','？','?','—'):
                if old!=new:report['fieldChanges'].append({'character':char['name'],'field':key,'before':old,'after':new})
                doc['rawFields'][key]=new;doc['fields'][key]=render(new);owned.add(key)
            elif old!=new:
                report['conflicts'].append({'character':char['name'],'field':key,'wiki':old,'client':new,'action':'preserved'})
        doc['clientFields']=sorted(owned)
        doc['clientSource']={**source,'availableAt':char['availableAt'],'sourceRows':char['sourceRows']}
        if all('满级满星'+key in owned for key in char['stats']):doc['clientStatBasis']=char['statBasis']
        r=doc['rawFields'];entry.update({'class':r['角色职业'],'rarity':r['稀有度'],'faction':r['所属阵营'],'weapon':r['武器类型'],
            'stats':{key:r.get('满级满星'+key,'') for key in char['stats']},'summary':r.get('角色生平','')[:220],
            'clientUnitId':char['unitId'],'clientRoleUnitId':char['id']})
        if entry['id']>=400_000_000:
            # Imported characters are appended after the whole archive, ordered by client id.
            entry['sourceOrder']=ORDER_BASE+entry['id']
        entry.setdefault('unitNumber','');entry.setdefault('professionIcon','')
        # 职业徽记：客户端没有独立贴图，用该职业分类的队伍技能徽记（五种分类图形与配色都不同）。
        class_icon=assets.get(char['classIcon']) if char.get('classIcon') else ''
        if class_icon:entry['professionIcon']=class_icon
        # 阵营徽记：icon/unittag/unittag_*，缺贴图的阵营保持只有文字。
        faction_badges={}
        for tag_name,tag_asset in (char.get('factionIcons') or {}).items():
            tag_path=assets.get(tag_asset)
            if tag_path:faction_badges[tag_name]=tag_path
        if faction_badges:entry['factionIcons']=faction_badges
        extracted_portraits=[]
        for picture in char['portraits']:
            path=assets.get(picture['asset']);label=picture['label']
            if not path and picture.get('fallback'):
                path=assets.get(picture['fallback']);label+='（卡面）'
            if path:extracted_portraits.append({'key':picture['key'],'label':label,'src':path})
        old_pictures={p['key']:p for p in entry.get('portraits',[])}
        old_pictures.update({p['key']:p for p in extracted_portraits});entry['portraits']=list(old_pictures.values())
        if extracted_portraits:entry['image']=next((p['src'] for p in extracted_portraits if p['key']=='base'),entry.get('image',''))
        for key in ('avatar','sprite'):
            path=assets.get(char[key])
            if path:entry[key]=path
        # 像素小人可选版本（默认形象 / 某个皮肤形象），缺资源时回落到默认形象。
        variants=char.get('spriteVariants') or [{'key':'base','asset':char['sprite']}]
        chosen=next((v for v in variants if v['key']==sprite_variant),variants[0])
        figure_path=assets.get(chosen['asset']) or (assets.get(char['sprite']) if chosen['key']!='base' else '')
        if figure_path:
            entry['sprite']=figure_path
            entry['spriteVariant']=chosen['key'] if assets.get(chosen['asset']) else 'base'
            report['spriteVariants']=report.get('spriteVariants',{})
            report['spriteVariants'][char['name']]={'key':entry['spriteVariant'],
                'label':next((v['label'] for v in variants if v['key']==entry['spriteVariant']),'默认形象')}
        pedestal_sprite=False
        if entry.get('sprite') and char['rarity']=='传说':
            try:
                pedestal_img,ped_provenance=pedestal_for()
                composed=compose_pedestal(Image.open(io.BytesIO(assets.content(entry['sprite']))),pedestal_img)
                content=encode_webp(composed)
                relative='assets/client/sprite-'+sha(content)[:24]+'.webp'
                assets.files[relative]=content
                entry['spriteFigure']=entry['sprite'];entry['sprite']=relative
                pedestal_sprite=True
                pedestal_info={'base':ped_provenance.get('source'),'baseSize':ped_provenance.get('size'),
                    'placement':ped_provenance.get('placement')}
            except (ValueError,OSError) as error:
                report['warnings'].append(char['name']+' 台座合成失败，保留原始像素小人：'+str(error))
        entry['date']=snapshot['extractedAt'][:10]
        # 纯客户端解析的资料馆（已删除 BWIKI 快照）不保留「导入前的 Wiki 原文」；
        # 之前保留过的也要一并清掉，否则会留下指向 assets/wiki/ 的死图。
        keep_original=(wiki/'data/raw/pages').is_dir()
        original=doc.get('clientOriginalHtml',doc.get('html','')) if keep_original else ''
        if keep_original:doc['clientOriginalHtml']=original
        else:doc.pop('clientOriginalHtml',None)
        fact_keys=['角色职业','武器类型','特职','所属阵营','移动','跳跃高度','中文CV','日文CV',*['初始'+k for k in char['stats']],*['满级满星'+k for k in char['stats']]]
        facts='<dl class="fact-grid">'+''.join('<div><dt>'+html.escape(k)+'</dt><dd>'+doc['fields'].get(k,'—')+'</dd></div>' for k in fact_keys)+'</dl>'
        doc['html']='<h2>游戏客户端角色资料</h2><p>'+html.escape(char['statBasis'])+'</p>'+facts+'<h3>角色生平</h3>'+doc['fields'].get('角色生平','')
        if original:doc['html']+='<details><summary>导入前的 Wiki 原文</summary>'+original+'</details>'
        doc['clientModules']=char['modules'];doc['clientSandboxSkills']=char['sandboxSkills']
        report['characters'].append({'name':char['name'],'wikiId':pid,'clientId':char['id'],'unitId':char['unitId'],
            'stats':char['stats'],'treeNodes':len(char['tree']),'traitStars':5 if trait else 0,'portraits':len(extracted_portraits),
            'availableAt':char['availableAt'],'availableAtExtraction':char['available'],
            'weapon':weapon['name'] if weapon else '','pedestalSprite':pedestal_sprite})
        manifest['characters'][str(pid)]={'clientId':char['id'],'name':char['name'],'fingerprint':source['fingerprint']}

    # 装备图鉴：为客户端已知的所有武器生成页面，而不只是角色专武。
    # record_equipment 内部按武器 id 去重，角色专武已在循环里建好并关联回角色页，
    # 这里补齐其余武器（含无名无主武器），确保所有装备都有对应条目。
    say(f'生成装备图鉴页面：{len(weapons)} 把武器')
    for weapon in weapons.values():
        record_equipment(weapon,weapon.get('name') or '',None)

    say(f'序列化页面与搜索索引：{len(docs)} 个')
    for index,(pid,doc) in enumerate(docs.items(),1):
        say(f'序列化页面 {index}/{len(docs)}',index,len(docs),False)
        doc['date']=snapshot['extractedAt'][:10];entry=by_id[pid]
        entry['clientManaged']=True
        entry['date']=doc['date']
        files[f'data/pages/{pid}.js']=js(f'window.WIKI_PAGES[{pid}]',doc)
        search[str(pid)]=entry['title']+' '+' '.join(doc['rawFields'].values())+' '+visible(doc['html'])
        advanced[str(pid)]={'fields':doc['rawFields'],'related':doc.get('related',[])}
    # 页面改过 id（如从 wiki 的 4 位编号迁到客户端编号）后，旧键会留在索引里，
    # 搜索结果因此会指向已经不存在的页面；这里按现有页面收一遍。
    live={str(p['id']) for p in data['pages']}
    for stale in [key for key in search if key not in live]:
        search.pop(stale,None);advanced.pop(stale,None)

    if infographic:
        say(f'生成一图流缩略图：{len(assets.files)} 张')
        pairs=list(assets.files.items())
        workers=min(8,(os.cpu_count() or 2))
        thumbnails=_run_thumbnails(pairs,workers)
        for index,(path,encoded,width,height) in enumerate(thumbnails,1):
            say(f'一图流缩略图 {index}/{len(thumbnails)}',index,len(thumbnails),False)
            if encoded is None:continue
            body=('window.WIKI_POSTER_IMAGES=window.WIKI_POSTER_IMAGES||{};window.WIKI_POSTER_IMAGES['+dumps(path)+']='+dumps(encoded)+';\n').encode('utf8')
            name='data/infographic-assets/client-'+sha(body)[:24]+'.js';files[name]=body;infographic['assets'][path]=name
            if max(width,height)>1000:infographic.setdefault('portraitSizes',{})[path]={'width':width,'height':height}
        files['data/infographic.js']=js('window.WIKI_INFOGRAPHIC_DATA',infographic)
    files.update(assets.files)
    counts=dict(Counter(p['type'] for p in data['pages']))
    data['archive'].update(pages=len(data['pages']),counts=counts)
    # Keep the original snapshot accounting separate from client supplements.
    data['archive'].setdefault('wikiSnapshotExpectedPages',data['archive'].get('expectedPages'))
    data['archive']['expectedPages']=data['archive']['wikiSnapshotExpectedPages']+len(manifest['ids'])
    if not data['archive']['wikiSnapshotExpectedPages']:
        # 纯客户端解析的资料馆没有 BWIKI 快照基线：收录页数就是预期页数，
        # 打包脚本检查的 archive.complete 才有意义。
        data['archive']['expectedPages']=len(data['pages'])
        data['archive']['complete']=True
    data['archive']['clientSupplement']={'characters':len(manifest['characters']),'version':source['changeNumber']}
    files['data/index.js']=js('window.WIKI_DATA',data,'window.WIKI_PAGES={};')
    files['data/search.js']=js('window.WIKI_SEARCH',search)
    files['data/advanced-search.js']=js('window.WIKI_ADVANCED_DATA',advanced)
    if pinyin.available():files['data/pinyin.js']=js('window.WIKI_PINYIN',pinyin.build(data['pages']))
    files['data/archive.json']=json.dumps(data['archive'],ensure_ascii=False,indent=2).encode('utf8')
    files['data/client-manifest.json']=json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf8')
    prior_provenance=wiki/'data/client-provenance.json'
    provenance=read_json('data/client-provenance.json') if prior_provenance.exists() else {'characters':{},'assets':{}}
    if not prior_provenance.exists():observed['data/client-provenance.json']=None
    provenance.update(client=snapshot['client'],extractedAt=snapshot['extractedAt'],statBasis=STAT_BASIS)
    if pedestal_info:provenance['pedestalSprite']=pedestal_info
    for char in selected:provenance['characters'][str(char['id'])]=char
    provenance['assets'].update(assets.manifest)
    files['data/client-provenance.json']=json.dumps(provenance,ensure_ascii=False,indent=2).encode('utf8')
    patch_ui(wiki,files,observed)
    report['missingAssets']=sorted(set(assets.missing))
    report['newPages']=[pid for pid in docs if not (wiki/f'data/pages/{pid}.js').exists()]
    report['scope']='fill missing and previously managed fields' if not refresh else 'refresh client fields'
    say(f'比对资料馆现有文件：{len(files)} 个')
    expected={name:sha((wiki/name).read_bytes()) if (wiki/name).is_file() else None for name in files}
    expected.update({name:value for name,value in observed.items() if name in files})
    report['files']=[{'path':name,'bytes':len(content),'before':expected[name],'after':sha(content)} for name,content in files.items() if expected[name]!=sha(content)]
    report['changedFiles']=len(report['files'])
    say(f'生成完成：共 {len(files)} 个文件，其中 {len(report["files"])} 个与现有内容不同；缺失客户端资源 {len(report["missingAssets"])} 个')
    return files,expected,report
