"""Extract the archived widget's actual pool configuration; no live requests."""
import json
from bs4 import BeautifulSoup

def build_tools():
    from build_data import ROOT,RAW,TITLES,image_path,dumps,named_image,META
    raw=json.loads((RAW/'pages'/'8027.json').read_text(encoding='utf-8'))['parse']
    soup=BeautifulSoup(raw['text'],'html.parser')
    values={e['data-key']:e.get_text(strip=True) for e in soup.select('#widget-params [data-key]')}
    database=json.loads(values['character_db'])
    normalize=lambda s:s.replace('•','·').replace('・','·')
    title_map={normalize(k):v for k,v in TITLES.items()}
    chars={}
    for rarity in ('legend','epic','elite','common'):
        names=json.loads(values[rarity+'_names'])
        chars[rarity]=[]
        for name in names:
            entry=database.get(rarity,{}).get(name,{})
            chars[rarity].append({'name':name,'id':title_map.get(normalize('角色图鉴库/'+name)),
                'image':image_path(entry.get('pixelUrl','')) or named_image('头像_'+name),
                'class':entry.get('type','')})
    pools=[{'id':'chuyu','label':'初遇','name':values['chuyu_name'],'up':[values['chuyu_char']],
            'image':image_path(values['chuyu_img']),'upRate':0.5},
           {'id':'chongfeng','label':'重逢','name':values['chongfeng_name'],
            'up':[values['chongfeng_chara'],values['chongfeng_charb']],
            'image':image_path(values['chongfeng_img']),'upRate':0.75}]
    for pool in pools:
        assert pool['image'],pool
        for name in pool['up']:assert any(c['name']==name for c in chars['legend']),name
    date=META.get('8027',{}).get('revisions',[{}])[0].get('timestamp','')[:10]
    equipment=json.loads((RAW/'pages'/'2710.json').read_text(encoding='utf-8'))['parse']
    table=BeautifulSoup(equipment['text'],'html.parser').select_one('#CardSelectTr')
    equipment_stats=[]
    for row in table.select('tr'):
        cells=[e.get_text('',strip=True) for e in row.find_all('td',recursive=False)]
        if len(cells)==7:
            numbers=[int(v) for v in cells[2:]]
            equipment_stats.append({'weapon':cells[0],'rarity':cells[1],
                'stats':dict(zip(('物攻','魔攻','物防','魔防','生命'),numbers)),
                'recorded':any(numbers)})
    assert len(equipment_stats)==24
    result={'pools':pools,'characters':chars,'sourceDate':date,'revision':raw['revid'],'pageId':8027,
        'equipment':{'rows':equipment_stats,'pageId':2710,'revision':equipment['revid'],
            'date':META.get('2710',{}).get('revisions',[{}])[0].get('timestamp','')[:10]}}
    (ROOT/'data'/'tools.js').write_text('window.WIKI_TOOLS_DATA='+dumps(result)+';\n',encoding='utf-8')
    print('Built offline pools:',{k:len(v) for k,v in chars.items()},flush=True)

if __name__=='__main__':build_tools()
