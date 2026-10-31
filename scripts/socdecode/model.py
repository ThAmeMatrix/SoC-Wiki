"""Join the client tables by IDs; preserve display overrides and growth provenance."""
from __future__ import annotations
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

CN_TIME=timezone(timedelta(hours=8))
STATS={'hp':'生命','physic_attack':'物攻','spell_attack':'魔攻','physic_defence':'物防','spell_defence':'魔防'}
RANK_NAMES={1:'一',3:'三',5:'五',7:'七',9:'九',11:'十一'}
STAT_BASIS='60级、五星、13阶、左右技能全部解锁；不含装备、天赋、好感、模组及战斗个性增益'
SPRITES={0:'★',1:'×',2:'▲',3:'▼',4:'护盾',5:'攻击',6:'正位',7:'逆位',8:'正位',9:'逆位',10:'•',11:'时间',12:'SP',16:'↑',17:'↑'}

def ids(value):
    if not value:return []
    return [int(x) for x in str(value).split('|') if x and int(x)>0]

def plain(text):
    text=re.sub(r'<sprite=(\d+)>',lambda m:SPRITES.get(int(m[1]),f'〔图标{m[1]}〕'),text or '')
    text=re.sub(r'<sprite="text_sprites" name="sp">','SP',text)
    tarot={19:'太阳',20:'审判',21:'世界'}
    text=re.sub(r'<sprite="text_tarot" name="tarot_(\d+)">',lambda m:'·'+tarot.get(int(m[1]),'塔罗'+m[1]),text)
    return re.sub(r'</?(?:style|color|size|b|i)(?:=[^>]*)?>','',text).strip()

def grouped(rows,key):
    result=defaultdict(list)
    for row in rows:result[row[key]].append(row)
    return result

def attributes(growth,rarity,star,ranks,lines):
    """Client CalculateAttributeByType: fixed hundredths, then rank additions.

    floor((floor(level * rarityPercent * (1000+starPermille+skillPermille)/1000)
           + rankAdd*100)/100). Archive comparisons are recorded separately;
    existing Wiki differences are not silently overwritten.
    """
    result={}
    for field,label in STATS.items():
        permille=star['permillage_'+field]+sum(row['permillage_'+field] for row in lines)
        scaled=growth[field]*rarity['base_attribute_adjust']
        adjusted=scaled*(1000+permille)//1000
        result[label]=(adjusted+100*sum(row[field+'_add'] for row in ranks))//100
    return result

def build_snapshot(tables,meta,as_of=None):
    now=as_of or datetime.now(CN_TIME)
    db={name:{row['id']:row for row in rows} for name,rows in tables.items()}
    grows={(r['idonline_unit_modify'],r['level']):r for r in tables['online_unit_modify_level']}
    ranks=grouped(tables['online_unit_rank_modify_rank'],'idonline_unit_rank_modify')
    lines=grouped(tables['online_unit_rank_skill_line_modify'],'idonline_unit_rank_skill_line')
    personality_skills=grouped(tables['unit_personality_skill'],'idunit_personality')
    stories=grouped(tables['online_role_life_story'],'idonline_role')
    voices=grouped(tables['unit_voice_language'],'idunit')
    skins=grouped(tables['unit_skin'],'idunit')
    pool=grouped(tables['unit_pool_skill'],'idunit')
    characters=[]; skill_out={};traits={};warnings=[]

    def skill(sid):
        if sid in skill_out:return skill_out[sid]
        source=db['skill'][sid];display=source;seen={sid}
        while display.get('overwritten_skill_id'):
            target=display['overwritten_skill_id']
            if target in seen:raise ValueError(f'技能展示覆盖循环：{sid}')
            seen.add(target);display=db['skill'][target]
        row=dict(display)
        row.update(id=sid,displayId=display['id'],sourceTable='skill',raw=source)
        if not row['desc'] and row.get('name'):warnings.append(f"技能 {sid} {row['name']} 没有展示描述")
        skill_out[sid]=row
        return row

    for online in tables['online_role_unit']:
        if online['idunit'] not in db['unit']:raise ValueError(f"角色 {online['id']} 的单位不存在")
        unit=db['unit'][online['idunit']];role=db['online_role'][online['idonline_role']]
        name=plain(online.get('sp_name') or role['name'])
        growth=grows.get((online['online_unit_modify_id'],60))
        initial=grows.get((online['online_unit_modify_id'],1))
        if not growth or not initial:
            warnings.append(f'角色 {online["id"]} {name} 缺少成长记录');continue
        rank_list=sorted(ranks[online['online_unit_rank_modify_id']],key=lambda r:r['rank'])
        rank_config=db['online_unit_rank_modify'][online['online_unit_rank_modify_id']]
        line_list=[r for r in lines[rank_config['skill_line_id']] if not r['is_enhance'] and r['rank']<=13]
        rarity=db['unit_rarity'][online['rarity']]
        base=attributes(initial,rarity,db['online_unit_star'][1],[],[])
        maximum=attributes(growth,rarity,db['online_unit_star'][5],rank_list,line_list)
        base['敏捷']=maximum['敏捷']=unit['speed']
        personality=db['unit_personality'].get(unit['personality_id'])
        trait_id=None
        if personality:
            trait_id=personality['id'];levels={}
            for star in range(1,6):
                groups={}
                for row in sorted(personality_skills[trait_id],key=lambda r:(r['star'],r['id'])):
                    if row['star']<=star:groups[row['skill_group_id']]=row
                selected=[groups[k] for k in sorted(groups)]
                levels[str(star)]={'skillIds':[r['skill_id'] for r in selected],
                    'description':'\n'.join(r['desc'] or skill(r['skill_id'])['desc'] for r in selected).strip(),
                    'sourceRows':[r['id'] for r in selected]}
            traits[trait_id]={**personality,'stars':levels}
        tree=[]
        initial_skills=[unit['melee_skill'],*ids(unit['default_skills'])]
        for side,sid in enumerate(initial_skills):
            if sid:skill(sid);tree.append({'rank':0,'side':side,'skillId':sid})
        for rank in rank_list:
            for side in (0,1):
                sid=rank[f'skill{side+1}_id']
                if sid:skill(sid);tree.append({'rank':rank['rank'],'side':side,'skillId':sid})
        modules=[]
        for rank in rank_list:
            for mid in ids(rank.get('module_skill_ids')):
                chain=[];seen=set()
                while mid:
                    if mid in seen:raise ValueError('模组技能链循环')
                    seen.add(mid);m=db['online_module_skill'][mid];skill(m['skill_id'])
                    chain.append(m);mid=m['next_id']
                modules.append(chain)
        model=db['unit_model'].get(unit['unit_model_id'],{})
        art=unit['icon'] or model.get('icon') or model.get('model') or unit['model']
        portrait_specs=[{'key':'base','label':'初始立绘','asset':f'icon/card_full/card_{art}'}]
        # Every skin that carries its own model art also has its own pixel figure;
        # the base figure is the default, a skin figure can be selected instead.
        sprite_variants=[{'key':'base','label':'默认形象','asset':f'icon/character/character_{art}'}]
        for skin in skins[unit['id']]:
            key='awakened' if skin['type']==1 else 'skin-'+str(skin['id'])
            portrait_specs.append({'key':key,'label':'觉醒立绘' if key=='awakened' else skin['name'],
                'asset':'icon/skin_card_full/'+skin['icon_card'],
                'fallback':'icon/skin_card/'+skin['icon_card'], 'sourceId':skin['id']})
            if skin.get('icon'):
                sprite_variants.append({'key':key,'label':skin['name'],
                    'asset':f"icon/character/character_{skin['icon']}"})
        profession=db['profession'][unit['profession']]
        weapon=[db['weapon_type'][n]['name'] for n in ids(unit['weapon_type_ids']) if db['weapon_type'][n]['main_hand']]
        cv={r['voice_lang']:r['cv_actor'] for r in voices[unit['id']]}
        launch=db['timestamp'].get(online['enable_time_id'])
        launch_time=launch['timestamp'] if launch else None
        life='\n\n'.join(r['content'] for r in sorted(stories[role['id']],key=lambda r:r['sort_id']))
        extra=sorted({r['skill_id'] for r in pool[unit['id']] if r['skill_id'] in db['skill']})
        characters.append({'id':online['id'],'unitId':unit['id'],'roleId':role['id'],'name':name,
            'enabled':online['enable'],'availableAt':datetime.fromtimestamp(launch_time,CN_TIME).isoformat() if launch_time else None,
            'available':bool(online['enable'] and launch_time and launch_time<=now.timestamp()),
            'class':db['profession_category'][profession['category']]['name'],'profession':profession['name'],
            'rarity':rarity['name'],'weapon':'、'.join(weapon),'gender':{1:'男',2:'女'}.get(unit['gender'],''),
            'factions':[db['unit_tag'][tag]['name'] for tag in ids(unit['unit_tag_ids'])],
            'movement':unit['mobility'],'jumpUp':unit['jump_up'],'jumpDown':unit['jump_down'],
            'baseStats':base,'stats':maximum,'statBasis':STAT_BASIS,
            'statsSource':{'initial':initial,'level60':growth,'rarity':rarity['base_attribute_adjust'],
                'star':db['online_unit_star'][5],'ranks':rank_list,'skillLines':line_list},
            'tree':tree,'personalityId':trait_id,'cv':{'zh':cv.get(1,''),'ja':cv.get(2,'')},
            'story':life,'portraits':portrait_specs,'avatar':f'icon/face/face_{art}',
            'sprite':f'icon/character/character_{art}','spriteVariants':sprite_variants,'modules':modules,
            # 极限解放 is the client's module skill chain: one name, three levels.
            'liberations':[{'name':plain(db['skill'][chain[0]['skill_id']]['name']),'icon':db['skill'][chain[0]['skill_id']].get('icon',''),
                'levels':[{'level':row.get('level'),'skillId':row['skill_id'],
                    'desc':plain(db['skill'][row['skill_id']]['desc'])} for row in chain if row['skill_id'] in db['skill']]}
                for chain in modules if chain and chain[0]['skill_id'] in db['skill'] and plain(db['skill'][chain[0]['skill_id']]['name'])],
            'sandboxSkills':[{'id':r['skill_id'],'name':plain(db['skill'][r['skill_id']]['name']),
                'state':r['state'],'sourceId':r['id']} for r in pool[unit['id']] if r['skill_id'] in db['skill']],
            'sourceRows':{'online_role':role['id'],'online_role_unit':online['id'],'unit':unit['id'],
                'unit_personality':unit['personality_id'],'online_unit_modify':online['online_unit_modify_id'],
                'online_unit_rank_modify':online['online_unit_rank_modify_id']}})

    # Exclusive weapons (online_weapon): star skills carry the owner's name in
    # the client's own editor_name (e.g. 网游装备技能-[君士坦丁|法皇]专武1).
    weapons={}
    weapon_levels={}
    for row in tables['online_weapon_modify_level']:
        weapon_levels.setdefault(row['idonline_weapon_modify'],{})[row['level']]=row
    weapon_stars=grouped(tables['online_weapon_personality_skill'],'idonline_weapon_personality')
    weapon_rarities={r['id']:r for r in tables['online_weapon_rarity']}
    type_names={n['id']:n['name'] for n in tables['weapon_type']}
    weapon_personalities={r['id']:r for r in tables['online_weapon_personality']}
    for row in tables['online_weapon']:
        stars={};owners=set()
        for entry in sorted(weapon_stars.get(row['personality_id'],[]),key=lambda r:(r['star'],r['id'])):
            if not 1<=entry['star']<=5 or entry['skill_id'] not in db['skill']:continue
            item=skill(entry['skill_id'])
            stars[str(entry['star'])]={'skillId':entry['skill_id'],'name':plain(item['name']),
                'description':plain(item['desc']),'rawDescription':item['desc']}
            owners.update(part.strip() for part in
                re.findall(r'\[([^\[\]|]+)',item['raw'].get('editor_name') or ''))
        levels=weapon_levels.get(row['online_weapon_modify_id'],{})
        top=levels.get(max(levels)) if levels else None
        personality=weapon_personalities.get(row['personality_id'])
        weapons[row['id']]={'id':row['id'],'name':plain(row['name']),'desc':(row['desc'] or '').strip(),
            'type':type_names.get(row['type'],str(row['type'])),'typeId':row['type'],
            'rarity':weapon_rarities[row['rarity']]['name'] if row['rarity'] in weapon_rarities else str(row['rarity']),
            'personalityName':plain(personality['name']) if personality else '',
            'stats':{'等级':top['level'],'生命':top['hp'],'物攻':top['physic_attack'],'魔攻':top['spell_attack'],
                '物防':top['physic_defence'],'魔防':top['spell_defence']} if top else {},
            'stars':stars,'owners':sorted(owners),
            'art':'icon/weapon_full/weapon_full_%04d'%row['id'],'icon':'icon/weapon/weapon_%04d'%row['id']}

    # Descriptions and recursive keyword definitions include mechanics referred to
    # by traits, passive effects and skills, not only directly selected skills.
    keywords=db['skill_keyword'];needed=set()
    by_name=defaultdict(list)
    for row in keywords.values():by_name[plain(row['name'])].append(row['id'])
    def collect(description,explicit=()):
        needed.update(explicit)
        for term in re.findall(r'\[([^\[\]]+)\]',plain(description)):
            candidates=by_name.get(term,[])
            if len(candidates)==1:needed.add(candidates[0])
    # Personality stars reference skills the tree does not contain; keep them for keywords.
    for trait in traits.values():
        for level in trait['stars'].values():
            for sid in level['skillIds']:
                if sid in db['skill']:skill(sid)
    for row in skill_out.values():collect(row['desc'],ids(row.get('keyword_ids')))
    for trait in traits.values():
        for level in trait['stars'].values():collect(level['description'])
    statuses={};visited=set()
    while needed-visited:
        kid=min(needed-visited);visited.add(kid)
        if kid not in keywords:continue
        kw=keywords[kid];ref=db['buff'].get(kw['ref_text_id']) if kw['ref_text_type']==2 else db['skill'].get(kw['ref_text_id'])
        description=kw['desc'] or (ref or {}).get('desc','')
        if description:
            statuses[kid]={**kw,'name':plain(kw['name']),'description':description,'icon':(ref or {}).get('icon',''),
                'sourceTable':'buff' if kw['ref_text_type']==2 else 'skill'}
            collect(description,ids((ref or {}).get('keyword_ids')))
    return {'schemaVersion':1,'extractedAt':now.isoformat(),'client':meta,'characters':characters,
        'skills':skill_out,'traits':traits,'statuses':statuses,'weapons':weapons,'warnings':sorted(set(warnings)),
        'statBasis':STAT_BASIS}
