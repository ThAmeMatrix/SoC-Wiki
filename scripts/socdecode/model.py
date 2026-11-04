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

# 大阿尔卡纳牌名；客户端用 <sprite="text_tarot" name="tarot_NN"> 内嵌牌名图形（NN 为两位数序号）。
# 塔罗角色的显示名统一写作「角色•牌名」，与资料馆既有的塔罗角色条目（如「贝拉•魔术师」）一致。
TAROT={0:'愚者',1:'魔术师',2:'女祭司',3:'女皇',4:'皇帝',5:'法皇',6:'恋人',7:'战车',8:'力量',9:'隐者',
       10:'命运之轮',11:'正义',12:'倒吊人',13:'死神',14:'节制',15:'恶魔',16:'高塔',17:'星星',18:'月亮',
       19:'太阳',20:'审判',21:'世界'}
TAROT_MARK='•'

def ids(value):
    if not value:return []
    return [int(x) for x in str(value).split('|') if x and int(x)>0]

def plain(text):
    text=re.sub(r'<sprite=(\d+)>',lambda m:SPRITES.get(int(m[1]),f'〔图标{m[1]}〕'),text or '')
    text=re.sub(r'<sprite="text_sprites" name="sp">','SP',text)
    text=re.sub(r'<sprite="text_tarot" name="tarot_(\d+)">',
                lambda m:TAROT_MARK+TAROT.get(int(m.group(1)),'塔罗'+m.group(1)),text)
    # 客户端 sp_name 常在塔罗图标之后再写一次牌名（如「萨曼莎<塔罗20>审判」），
    # 直接拼接会得到「萨曼莎•审判审判」；去掉紧随图标后重复的牌名。
    for card in set(TAROT.values()):
        text=text.replace(TAROT_MARK+card+card,TAROT_MARK+card)
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

    # 极限解放的升级消耗：consume_type 是 treasure_type 的 id，其 param0_type 指出
    # consume_param0 该去哪张表查名字，consume_param1 是数量。
    treasure_types={row['id']:row for row in tables['treasure_type']}
    boss_materials={row['id']:row for row in tables['online_boss_challenge_material']}
    money_name=next((row['name'] for row in treasure_types.values() if row.get('type')=='money'),'金币')

    # 「使用后技能变更」在客户端里一共三种写法，全部从 speciality 表自发推出来，
    # 不针对任何具体技能写死：
    #   a) 直接挂：技能自己带 speciality(REPLACE_SKILL, A, X)。它只是个切换动作
    #      （如「自动扬旗」），改的是 A 那个技能而不是自己，所以边是 A -> X。
    #   b) 经 BUFF：skill -> speciality(BUFF, param0=buff, param1=持续回合) ->
    #      buff -> speciality(REPLACE_SKILL, A, X)。边归给谁要看施加者：
    #      * 施加者本身就是被 A 换上来的那一环（A -> 施加者 这条边已存在），
    #        链是往下走的，边 = 施加者 -> X。神怒·断(6735) 施加的「技能切换」里写的是
    #        REPLACE_SKILL(6734, 6736)，6734 只是链头，下一段其实是 6735 -> 6736。
    #      * 否则边 = A -> X。裁决·一骑当先(14456) 自己没有任何替换特效，切换 BUFF
    #        由另一个技能(14557) 施加，所以变更仍应记在 14456 身上。
    #   c) 用完撤销：skill -> speciality(REMOVE_BUFF, param2=buff)，而那个 BUFF 正是
    #      把 A 换成该技能的 BUFF。移除它就恢复原技能，边 = 该技能 -> A。
    #      神怒·烈斩(6736) 移除「技能切换」(1278) -> 变回 神怒·瞬(6734)。
    specs={row['id']:row for row in tables['speciality']}
    spec_types={row['id']:row for row in tables['speciality_type']}
    def spec_kind(spec):return (spec_types.get(spec['type']) or {}).get('type','')
    def buff_replacements(buff_id):
        """BUFF 里挂的「技能替换」特效：[(原技能, 替换技能)]。"""
        buff=db['buff'].get(buff_id)
        return [(s.get('param0'),s.get('param1')) for s in
                (specs.get(i) for i in ids((buff or {}).get('speciality_ids')))
                if s and spec_kind(s)=='REPLACE_SKILL']
    switches={}
    def add_switch(origin,target,via,turns,mode):
        row=db['skill'].get(target)
        if not row or origin==target:return
        source=db['skill'].get(origin)
        # 换上来的技能跟原来同名（同名不同 id 的换皮）没有信息量，不展示。
        if source and plain(source['name'])==plain(row['name']):return
        bucket=switches.setdefault(origin,[])
        # 同一个技能可能由几个特效指向同一个下一段（甚至同名不同 id），按名字去重。
        if any(item['name']==plain(row['name']) for item in bucket):return
        bucket.append({'skillId':target,'name':plain(row['name']),
            'via':via,'turns':turns or 0,'mode':mode})

    # 先扫一遍，把两种替换都收上来，边暂时都记成 原技能 -> 替换技能。
    direct=[];via_buff=[]
    for sid,row in db['skill'].items():
        for spec_id in ids(row.get('speciality_ids')):
            spec=specs.get(spec_id)
            if not spec:continue
            kind=spec_kind(spec)
            if kind=='REPLACE_SKILL':
                direct.append((spec.get('param0'),spec.get('param1'),sid))
            elif kind=='BUFF':
                buff=db['buff'].get(spec.get('param0'))
                if not buff:continue
                for origin,target in buff_replacements(buff['id']):
                    via_buff.append((origin,target,sid,plain(buff['name']),spec.get('param1') or 0))
    # 谁被换成了谁。b) 要靠它判断施加者是不是链上的下一环。
    switched_to={}
    for origin,target,_ in direct:switched_to.setdefault(origin,set()).add(target)
    for origin,target,_,_,_ in via_buff:switched_to.setdefault(origin,set()).add(target)

    for origin,target,sid in direct:
        add_switch(origin,target,plain(db['skill'][sid]['name']),0,'direct')
    for origin,target,sid,via,turns in via_buff:
        # 施加者自己就是被换上来的那一环时，变更记在施加者身上（链往下走一段）。
        add_switch(sid if sid in switched_to.get(origin,()) else origin,target,via,turns,'buff')
    # c) 用完撤销：移除的那个 BUFF 正是把原技能换成自己的 BUFF。
    for sid,row in db['skill'].items():
        for spec_id in ids(row.get('speciality_ids')):
            spec=specs.get(spec_id)
            if not spec or spec_kind(spec)!='REMOVE_BUFF':continue
            buff=db['buff'].get(spec.get('param2'))
            if not buff:continue
            for origin,target in buff_replacements(buff['id']):
                if target==sid:add_switch(sid,origin,plain(buff['name']),0,'revert')

    def consume(ctype,param0,param1):
        """(类型, 参数0, 参数1) -> 材料名与数量；认不出材料表时退回收费类型自己的名字。"""
        if not ctype or not param0:return None
        kind=treasure_types.get(ctype) or {}
        name=None;icon=None
        if kind.get('param0_type')=='online_boss_challenge_material':
            row=boss_materials.get(param0)
            if row:
                name=plain(row['name'])
                # 客户端的材料图标（icon/material/material_bosschallengeNN），供页面直接展示。
                icon=row.get('icon') or None
        if not name:name=kind.get('name') or '材料'+str(param0)
        return {'name':plain(name),'count':param1 or 0,'typeId':ctype,'param0':param0,'icon':icon}

    def liberation(chain):
        """一条模组技能链 = 一个极限解放；返回名称、专属性与各级描述与消耗。"""
        if not chain or chain[0]['skill_id'] not in db['skill']:return None
        head=db['skill'][chain[0]['skill_id']];name=plain(head['name'])
        if not name:return None
        levels=[]
        for row in chain:
            sid=row['skill_id']
            if sid not in db['skill']:continue
            materials=[]
            for item in (consume(row.get('consume_type'),row.get('consume_param0'),row.get('consume_param1')),
                         consume(row.get('consume1_type'),row.get('consume1_param0'),row.get('consume1_param1'))):
                if item:materials.append(item)
            levels.append({'level':row.get('level'),'skillId':sid,
                'desc':plain(db['skill'][sid]['desc']),
                'money':row.get('consume_money') or 0,'moneyName':plain(money_name),
                'materials':materials})
        return {'name':name,'icon':head.get('icon',''),
            'exclusiveUnitId':chain[0].get('exclusive_unit_id') or 0,'levels':levels}

    def skill(sid):
        if sid in skill_out:return skill_out[sid]
        source=db['skill'][sid];display=source;seen={sid}
        while display.get('overwritten_skill_id'):
            target=display['overwritten_skill_id']
            if target in seen:raise ValueError(f'技能展示覆盖循环：{sid}')
            seen.add(target);display=db['skill'][target]
        row=dict(display)
        row.update(id=sid,displayId=display['id'],sourceTable='skill',raw=source,
            # 使用后变更为的其它技能（客户端的「技能替换」特效）。
            switches=switches.get(sid,[]))
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
                sid=rank.get(f'skill{side+1}_id') or 0;enhanced=False
                if not sid and side==1:
                    # 塔罗角色没有独立的右支技能（skill2_id 为空）：右侧放的是本阶左支的
                    # 加强版（enhance_skill1_id），技能名与左支相同但效果更强（如 22907→22838）。
                    sid=rank.get('enhance_skill1_id') or 0;enhanced=bool(sid)
                if sid:skill(sid);tree.append({'rank':rank['rank'],'side':side,'skillId':sid,'enhanced':enhanced})
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
        category=db['profession_category'][profession['category']]
        tags=[db['unit_tag'][tag] for tag in ids(unit['unit_tag_ids']) if tag in db['unit_tag']]
        # 客户端没有单独的「职业分类图标」贴图，用的是该分类的队伍技能徽记
        # （icon/skill/icon_skill_teamskill<type>），五种分类颜色与图形都不同；阵营则各有
        # 一枚 icon/unittag/unittag_* 徽记。
        characters.append({'id':online['id'],'unitId':unit['id'],'roleId':role['id'],'name':name,
            'enabled':online['enable'],'availableAt':datetime.fromtimestamp(launch_time,CN_TIME).isoformat() if launch_time else None,
            'available':bool(online['enable'] and launch_time and launch_time<=now.timestamp()),
            'class':category['name'],'classIcon':'icon/skill/icon_skill_teamskill'+str(category['type']).lower(),
            'profession':profession['name'],
            'rarity':rarity['name'],'weapon':'、'.join(weapon),'gender':{1:'男',2:'女'}.get(unit['gender'],''),
            'factions':[tag['name'] for tag in tags],
            'factionIcons':{tag['name']:'icon/unittag/'+tag['icon'] for tag in tags if tag.get('icon')},
            'movement':unit['mobility'],'jumpUp':unit['jump_up'],'jumpDown':unit['jump_down'],
            'baseStats':base,'stats':maximum,'statBasis':STAT_BASIS,
            'statsSource':{'initial':initial,'level60':growth,'rarity':rarity['base_attribute_adjust'],
                'star':db['online_unit_star'][5],'ranks':rank_list,'skillLines':line_list},
            'tree':tree,'personalityId':trait_id,'cv':{'zh':cv.get(1,''),'ja':cv.get(2,'')},
            'story':life,'portraits':portrait_specs,'avatar':f'icon/face/face_{art}',
            'sprite':f'icon/character/character_{art}','spriteVariants':sprite_variants,'modules':modules,
            # 极限解放 is the client's module skill chain: one name, three levels.
            'liberations':[item for item in (liberation(chain) for chain in modules) if item],
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
            # editor_name is written as 「…-[称号|角色名]-…」; both sides of the pipe
            # name whoever the skill belongs to. Taking only the part before the pipe
            # loses the character on entries like 「[圣典枢机卿|卡珊德拉]」, which then
            # never gets its exclusive weapon attached.
            for tag in re.findall(r'\[([^\[\]]+)',item['raw'].get('editor_name') or ''):
                owners.update(part.strip() for part in tag.split('|'))
        # 贴图编号（icon）与数据库主键（id）是两套编号，取不到时才回退到 id。
        icon_key=(row.get('icon') or '').strip() if isinstance(row.get('icon'),str) else ''
        if not icon_key:icon_key='%04d'%row['id']
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
            # 贴图必须按 online_weapon.icon 取，不能按 id：两套编号不同（id 从 77 起且
            # 有缺号，icon 是连续的 0001…），按 id 拼会让每把武器用到别人的立绘。
            'art':'icon/weapon_full/weapon_full_%s'%icon_key,'icon':'icon/weapon/weapon_%s'%icon_key}

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
    # 被「技能替换」换上来的技能不在技能树上（如 神怒·断），但资料馆要给它建页并让
    # 来源技能链过去，所以顺着替换链一并纳入快照。
    queue=list(skill_out)
    while queue:
        sid=queue.pop()
        for switch in skill_out[sid].get('switches') or []:
            if switch['skillId'] in db['skill'] and switch['skillId'] not in skill_out:
                skill(switch['skillId']);queue.append(switch['skillId'])
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
