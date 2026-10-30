"""Build infographic choices and compact, origin-safe canvas image payloads offline."""
from pathlib import Path
import base64, hashlib, io, json, re, sys
from infographic_stars import combine_stars
from bs4 import BeautifulSoup
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
def load(path):
    text=path.read_text(encoding='utf8')
    return json.JSONDecoder().raw_decode(text[text.index('=')+1:])[0]
def dump(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'))

def main():
    data=load(ROOT/'data/index.js')
    original=json.loads((ROOT/'data/raw/asset-map.json').read_text(encoding='utf8'))
    tarot=[]
    soup=BeautifulSoup(load(ROOT/'data/pages/2729.js')['html'],'html.parser')
    for row in soup.select('table.CardSelect tr'):
        cells=row.find_all('td',recursive=False)
        if len(cells)!=5:continue
        tarot.append({'id':f'tarot-{len(tarot)+1}','name':cells[1].get_text(strip=True),
                      'image':cells[0].img['src'],'description':cells[2].decode_contents().strip(),
                      'special':cells[3].decode_contents().strip(),'sourceId':2729})
    engravings=[]
    soup=BeautifulSoup(load(ROOT/'data/pages/2736.js')['html'],'html.parser')
    for row in soup.select('table')[-1].select('tr'):
        cells=row.find_all(['td','th'],recursive=False)
        if len(cells)!=2:continue
        name=cells[0].get_text(strip=True)
        if '+' not in name:continue
        parts=name.split('+')
        engravings.append({'id':f'engraving-{len(engravings)+1}','name':name,'parts':parts,
                          'images':[original[p+'刻印.png']['path'] for p in parts],
                          'description':cells[1].decode_contents().strip(),'sourceId':2736})
    assert len(tarot)==22 and len(engravings)==10
    assert len({tuple(sorted(e['parts'])) for e in engravings})==10
    equipment_icons={str(p['id']):original.get('装备_'+p['name']+'.png',{}).get('path',p['image']) for p in data['pages'] if p['type']=='equipment'}
    logo=original['铃兰之剑logo.png']['path']
    badges={kind:{name[len(prefix):-4]:asset['path'] for name,asset in original.items() if name.startswith(prefix) and name.endswith('.png')}
            for kind,prefix in [('rarities','文字_'),('professions','职业图标_'),('professionBackgrounds','职业图标背景_'),('factions','阵营图标_')]}
    stat_icons={key:original['Icon_'+name+'.png']['path'] for key,name in [('attack','物攻'),('magic','魔攻'),('defense','物防'),('resistance','魔防'),('health','生命')]}
    reference_titles={'9296':'assets/brand/vipera-reference-title.png','9295':'assets/brand/constantine-reference-title.png'}
    portraits=json.loads((ROOT/'data/raw/infographic-portraits.json').read_text(encoding='utf8'))
    limits={logo:640,**{path:1600 for path in reference_titles.values()}}
    def add(path,limit):
        if path and (ROOT/path).is_file():limits[path]=max(limit,limits.get(path,0))
    for page in data['pages']:
        if page['type']=='character':
            art=next((p['src'] for p in page.get('portraits',[]) if p['key']=='awakened'),next((p['src'] for p in page.get('portraits',[]) if p['key']=='base'),None))
            for p in page.get('portraits',[]):
                if p['key'] in ('base','awakened'):add(p['src'],1800)
            add(page.get('sprite'),192);add(page.get('professionIcon'),128)
        elif page['type'] in ('skill','equipment','talent'):add(page['image'],192)
    for group in badges.values():
        for path in group.values():add(path,160)
    for path in stat_icons.values():add(path,64)
    for path in equipment_icons.values():add(path,192)
    for t in tarot:add(t['image'],192)
    for e in engravings:
        for path in e['images']:add(path,128)
    folder=ROOT/'data/infographic-assets';folder.mkdir(exist_ok=True)
    assets={};total=0
    cached=load(ROOT/'data/infographic.js').get('assets',{}) if any(flag in sys.argv for flag in ('--metadata-only','--refresh-portraits')) else {}
    completed_portraits=0
    for path,limit in sorted(limits.items()):
        if path in cached and (ROOT/cached[path]).is_file() and ('--metadata-only' in sys.argv or path not in portraits):
            assets[path]=cached[path];total+=(ROOT/cached[path]).stat().st_size;continue
        original=portraits.get(path)
        with Image.open(ROOT/(original['file'] if original else path)) as image:
            image=image.convert('RGBA')
            if not original:image.thumbnail((limit,limit),Image.Resampling.LANCZOS)
            buf=io.BytesIO();image.save(buf,format='WEBP',quality=85,method=3 if original else 4,lossless=bool(original) or path in reference_titles.values())
        encoded='data:image/webp;base64,'+base64.b64encode(buf.getvalue()).decode('ascii')
        content='window.WIKI_POSTER_IMAGES=window.WIKI_POSTER_IMAGES||{};window.WIKI_POSTER_IMAGES['+dump(path)+']='+dump(encoded)+';\n'
        digest=hashlib.sha256((path+content).encode('utf8')).hexdigest()[:24]
        relative=f'data/infographic-assets/{digest}.js'
        destination=ROOT/relative
        if not destination.exists():destination.write_text(content,encoding='utf8')
        assets[path]=relative;total+=len(content.encode('utf8'))
        if original:
            completed_portraits+=1
            if completed_portraits%25==0 or completed_portraits==len(portraits):print(f'Lossless native portraits: {completed_portraits}/{len(portraits)}',flush=True)
    star_effects={}
    for page in data['pages']:
        if page['type']=='equipment' or page['title'].startswith('个性/'):
            fields=load(ROOT/f"data/pages/{page['id']}.js")['fields']
            stars=[fields.get(n+'星技能','') for n in '一二三四五'] if page['type']=='equipment' else [fields.get('个性描述'+str(n),'') for n in range(1,6)]
            if any(stars):star_effects[str(page['id'])]=combine_stars(stars)
    font_manifest=json.loads((ROOT/'data/raw/infographic-normal-font-manifest.json').read_text(encoding='utf8'))
    ranges=[]
    for code in sorted(map(ord,font_manifest['charset'])):
        if ranges and ranges[-1][1]+1==code:ranges[-1][1]=code
        else:ranges.append([code,code])
    result={'version':7,'signatureFont':'assets/fonts/infographic-signature.js','signatureLatinFont':'assets/fonts/infographic-signature-latin.js','nameFont':{'family':font_manifest['family'],'glyphs':font_manifest['glyphCount'],'script':font_manifest['script'],'version':font_manifest['version'],'ranges':ranges},'portraitSizes':{path:{'width':p['width'],'height':p['height']} for path,p in portraits.items()},'referenceTitles':reference_titles,'logo':logo,'statIcons':stat_icons,'badges':badges,'tarot':tarot,'engravings':engravings,'equipmentIcons':equipment_icons,'starEffects':star_effects,'assets':assets}
    (ROOT/'data/infographic.js').write_text('window.WIKI_INFOGRAPHIC_DATA='+dump(result)+';\n',encoding='utf8')
    print(f'Built {len(tarot)} tarot cards, {len(engravings)} engraving combinations, {len(assets)} canvas images ({total/1024/1024:.1f} MiB).',flush=True)

if __name__=='__main__':main()
