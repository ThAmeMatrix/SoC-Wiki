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
import re

from bs4 import BeautifulSoup
from PIL import Image
from .assets import Assets
from .model import RANK_NAMES, STAT_BASIS, plain, ids
from .pedestal import pedestal_image, compose as compose_pedestal, encode as encode_webp
from . import ranges, rangetiles
from .richtext import render
from .transaction import sha

def dumps(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':')).replace('</script','<\\/script')

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
                sprite_variant='base'):
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
    data=read_json('data/index.js',True);by_id={p['id']:p for p in data['pages']}
    by_name=defaultdict(list)
    for page in data['pages']:
        if page['type']=='character' and not page.get('redirect'):by_name[page['name']].append(page)
    current={c['name']:c for c in snapshot['characters']}
    if names:
        absent=set(names)-current.keys()
        if absent:raise ValueError('客户端没有这些角色（请查看 output/characters.json）：'+', '.join(sorted(absent)))
        selected=[current[name] for name in dict.fromkeys(names)]
    elif all_existing:
        if data['pages']:
            selected=[c for c in snapshot['characters'] if c['name'] in by_name and c['available']]
        else:
            # Fresh wiki (just bootstrapped from the client): populate every available character.
            selected=[c for c in snapshot['characters'] if c['available']]
    else:raise ValueError('请指定 --character，或使用 --all 更新已匹配并开放的角色')
    if not selected:raise ValueError('没有可更新的角色')
    duplicate=[c['name'] for c in selected if len(by_name.get(c['name'],[]))>1]
    if duplicate:raise ValueError('Wiki 存在同名角色，无法唯一匹配：'+', '.join(duplicate))

    old_manifest_path=wiki/'data/client-manifest.json'
    manifest=read_json('data/client-manifest.json') if old_manifest_path.exists() else {'schemaVersion':1,'ids':{},'characters':{}}
    if not old_manifest_path.exists():observed['data/client-manifest.json']=None
    files={};docs={};report={'characters':[],'fieldChanges':[],'conflicts':[],'missingAssets':[],
        'unmatchedWikiCharacters':sorted(set(by_name)-set(current)),
        'clientFingerprint':snapshot['client']['fingerprint'],'clientVersion':snapshot['client']['version'],
        'warnings':list(snapshot['warnings'])}
    assets=Assets(game)
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

    def record(kind,gid,name,owner):
        identity=kind+':'+str(gid)
        if identity in manifest['ids'] and manifest['ids'][identity] in by_id:
            pid=manifest['ids'][identity]
            return by_id[pid],document(pid)
        prefix={'skill':'技能图鉴库','talent':'个性','status':'中括号介绍','character':'角色图鉴库',
            'equipment':'装备图鉴库','liberation':'极限解放'}[kind]
        title=prefix+'/'+name
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

    selected_pids={}
    pedestal_info={}
    for char in selected:
        if by_name.get(char['name']):entry=by_name[char['name']][0];doc=document(entry['id'])
        else:entry,doc=record('character',char['id'],char['name'],char['name'])
        selected_pids[char['id']]=entry['id']

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
    def keywords(text,explicit=()):
        wanted.update(k for k in explicit if k in statuses)
        for term in re.findall(r'\[([^\[\]]+)\]',plain(text)):
            found=status_by_name.get(term,[])
            if len(found)==1:wanted.add(found[0])
    needed_skills={}
    for char in selected:
        for node in char['tree']:needed_skills[node['skillId']]=char['name']
        trait=traits.get(char['personalityId'])
        if trait:
            for level in trait['stars'].values():
                keywords(level['description'])
                for sid in level['skillIds']:
                    row=skills.get(sid)
                    if row:keywords(row['desc'],ids(row.get('keyword_ids')))
        weapon=char_weapons.get(char['id'])
        if weapon:
            for star in weapon['stars'].values():
                keywords(star['rawDescription'])
    for sid in needed_skills:
        row=skills.get(sid)
        if row:keywords(row['desc'],ids(row.get('keyword_ids')))
    seen=set()
    while wanted-seen:
        kid=min(wanted-seen);seen.add(kid);keywords(statuses[kid]['description'])
    links={};status_records={}
    for kid in sorted(wanted):
        item=statuses[kid];entry,doc=record('status',kid,item['name'],selected[0]['name'])
        status_records[kid]=(entry,doc);links[item['name']]=entry['id']
    for kid,(entry,doc) in status_records.items():
        item=statuses[kid];description=render(item['description'],links)
        doc.update(fields={'介绍':description},rawFields={'介绍':plain(item['description'])},
            html='<div class="definition">'+description+'</div>',clientSource={**source,'table':item['sourceTable'],'rowId':item['ref_text_id'],'keywordId':kid})
        entry['summary']=plain(item['description'])[:220]
        # Keyword icons can refer to skill or buff bundles.
        folder='buff' if item['sourceTable']=='buff' else 'skill'
        entry['image']=assets.get('icon/'+folder+'/'+item['icon']) if item['icon'] else ''

    skill_records={}
    for sid,owner in sorted(needed_skills.items()):
        item=skills[sid]
        if not item['name']:raise ValueError(f'技能树 {sid} 缺少显示名称')
        entry,doc=record('skill',sid,plain(item['name']),owner);skill_records[sid]=(entry,doc)
        is_passive=item['type']==3 or item['class_type'] in (2,3,6,7)
        distance='/' if is_passive else ('特殊（见说明）' if item['range_max']>=99 else str(item['range_min']) if item['range_min']==item['range_max'] else f"{item['range_min']}-{item['range_max']}")
        clean=plain(item['desc'])
        area='单体' if '单体' in clean or (item['class_type']==1 and '范围' not in clean) else '见技能说明'
        raw={'技能名称':entry['name'],'技能描述':clean,'技能消耗':'/' if is_passive else str(item['tp']),
            '技能冷却':'/' if is_passive else str(item['cooldown']),'技能射程':distance,'技能范围':'/' if is_passive else area,
            '技能类别':clean.partition('）')[0].removeprefix('（') if clean.startswith('（') else '技能'}
        fields={k:html.escape(v) for k,v in raw.items()};fields['技能描述']=render(item['desc'],links)
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

    for char in selected:
        pid=selected_pids[char['id']];entry=by_id[pid];doc=document(pid)
        trait=traits.get(char['personalityId']);trait_leaf=''
        if trait:
            te,td=record('talent',trait['id'],plain(trait['name']),char['name']);trait_leaf=te['title'].split('/',1)[1]
            fields={'个性描述'+str(star):render(trait['stars'][str(star)]['description'],links) for star in range(1,6)}
            raw={'个性描述'+str(star):plain(trait['stars'][str(star)]['description']) for star in range(1,6)}
            td.update(fields=fields,rawFields=raw,html=''.join(f'<h3>{n} 星</h3>'+fields['个性描述'+str(n)] for n in range(1,6)),
                starComparison=char_helpers.star_comparison(fields),clientSource={**source,'table':'unit_personality','rowId':trait['id'],'stars':trait['stars']})
            td['related']=sorted(set(td.get('related',[])+[pid]));te['summary']=raw['个性描述5'][:220]
            te['image']=assets.get('icon/unitpersonality/'+trait['icon']) if trait['icon'] else ''
            if infographic:infographic['starEffects'][str(te['id'])]=star_helpers.combine_stars(list(fields.values()))
        weapon=char_weapons.get(char['id'])
        if weapon:
            we,wd=record('equipment',weapon['id'],weapon['name'],char['name'])
            star_names=('一','二','三','四','五')
            raw_weapon={'装备名称':weapon['name'],'装备类型':weapon['type'],'稀有度':weapon['rarity'],'装备描述':weapon['desc']}
            for index,star in enumerate(star_names):
                item=weapon['stars'].get(str(index+1))
                raw_weapon[star+'星技能']=item['description'] if item else ''
            fields_weapon={key:html.escape(value) for key,value in raw_weapon.items()}
            for index,star in enumerate(star_names):
                item=weapon['stars'].get(str(index+1))
                if item:fields_weapon[star+'星技能']=render(item['rawDescription'],links)
            stat_row=''.join('<div><dt>'+html.escape(key)+'</dt><dd>'+html.escape(str(value))+'</dd></div>'
                for key,value in weapon['stats'].items())
            wd.update(fields=fields_weapon,rawFields=raw_weapon,
                html='<h2>游戏客户端装备资料</h2><p class="source-notice">等级属性取自客户端等级表（等级 '+html.escape(str(weapon['stats'].get('等级','')))+'），未包含星级与突破加成。</p><dl class="fact-grid">'+stat_row+'</dl>'
                    +''.join('<h3>'+star+'技能</h3>'+fields_weapon[star+'星技能'] for star in star_names if fields_weapon.get(star+'星技能')),
                clientSource={**source,'table':'online_weapon','rowId':weapon['id']})
            wd['related']=sorted(set(wd.get('related',[])+[pid]))
            weapon_art=assets.get(weapon.get('art',''))
            we.update({'summary':weapon['desc'][:220],'rarity':weapon['rarity'],'weapon':weapon['type'],
                'image':weapon_art or ''})
        # 极限解放：one page per liberation skill, listing its three client levels.
        liberation_names=[]
        for item in char.get('liberations') or []:
            levels=sorted((item.get('levels') or []),key=lambda row:row.get('level') or 0)[:3]
            if not levels:continue
            le,ld=record('liberation',levels[0]['skillId'],item['name'],char['name'])
            raw_liberation={'极限解放名称':item['name'],'极限解放图标':item['name']}
            for index,level in enumerate(levels):raw_liberation['极限解放描述'+str(index+1)]=level['desc']
            fields_liberation={key:html.escape(value) for key,value in raw_liberation.items()}
            for index,level in enumerate(levels):fields_liberation['极限解放描述'+str(index+1)]=render(level['desc'],links)
            ld.update(fields=fields_liberation,rawFields=raw_liberation,
                html='<h2>游戏客户端极限解放资料</h2><p class="source-notice">取自客户端模组技能链，按客户端的等级效果原样呈现。</p>'
                    +''.join('<h3>'+str(index+1)+' 级</h3>'+fields_liberation['极限解放描述'+str(index+1)] for index in range(len(levels))),
                clientSource={**source,'table':'online_module_skill','rowId':levels[0]['skillId']})
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
        previous=set(doc.get('clientFields',[]));owned=set(previous)
        for key,new in changes.items():
            if not new:continue
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
                composed=compose_pedestal(Image.open(io.BytesIO(assets.files[entry['sprite']])),pedestal_img)
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
        original=doc.get('clientOriginalHtml',doc.get('html',''));doc['clientOriginalHtml']=original
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

    for pid,doc in docs.items():
        doc['date']=snapshot['extractedAt'][:10];entry=by_id[pid]
        entry['clientManaged']=True
        entry['date']=doc['date']
        files[f'data/pages/{pid}.js']=js(f'window.WIKI_PAGES[{pid}]',doc)
        search[str(pid)]=entry['title']+' '+' '.join(doc['rawFields'].values())+' '+visible(doc['html'])
        advanced[str(pid)]={'fields':doc['rawFields'],'related':doc.get('related',[])}

    if infographic:
        for path,content in assets.files.items():
            with Image.open(io.BytesIO(content)) as image:
                width,height=image.size;image.thumbnail((1800,1800) if max(image.size)>1000 else (192,192),Image.Resampling.LANCZOS)
                output=io.BytesIO();image.save(output,format='WEBP',lossless=True,method=4)
            encoded='data:image/webp;base64,'+base64.b64encode(output.getvalue()).decode('ascii')
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
    data['archive']['clientSupplement']={'characters':len(manifest['characters']),'version':source['changeNumber']}
    files['data/index.js']=js('window.WIKI_DATA',data,'window.WIKI_PAGES={};')
    files['data/search.js']=js('window.WIKI_SEARCH',search)
    files['data/advanced-search.js']=js('window.WIKI_ADVANCED_DATA',advanced)
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
    expected={name:sha((wiki/name).read_bytes()) if (wiki/name).is_file() else None for name in files}
    expected.update({name:value for name,value in observed.items() if name in files})
    report['files']=[{'path':name,'bytes':len(content),'before':expected[name],'after':sha(content)} for name,content in files.items() if expected[name]!=sha(content)]
    report['changedFiles']=len(report['files'])
    return files,expected,report
