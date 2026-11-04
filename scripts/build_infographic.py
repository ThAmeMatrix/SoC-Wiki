"""Build infographic choices and compact, origin-safe canvas image payloads.

This step is intentionally client-only. The canvas is assembled from the pages
that ``plan_update`` already wrote out of the local game client (character
portraits, pixel sprites, skill/equipment icons) plus the game's own texture
assets, and needs no BWIKI snapshot, asset map, or network access.

BWIKI-sourced extras that the client does not carry -- the title logo, rarity/
profession/faction text badges, stat icons, tarot/engraving artwork, and the
custom name font -- simply stay empty when their files are absent, so a pure
client rebuild still produces a complete, navigable wiki (every character page,
skill, piece of equipment, and the one-page canvas all render from client data).
"""
from pathlib import Path
import base64, hashlib, io, json, sys
from infographic_stars import combine_stars
from bs4 import BeautifulSoup
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]

def load_js(path):
    """Load a window.X=... JS data file, or None when it is missing."""
    try:
        text=path.read_text(encoding='utf8')
    except OSError:
        return None
    return json.JSONDecoder().raw_decode(text[text.index('=')+1:])[0]

def load_json(path, default=None):
    """Load a plain JSON file, or ``default`` when it is missing."""
    try:
        return json.loads(path.read_text(encoding='utf8'))
    except OSError:
        return default

def dump(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'))

def discover_client_portraits(data):
    """Build the lossless-portrait map from the client-sourced wiki pages.

    ``plan_update`` records each character's portrait on the page itself
    (``portraits`` for base/awakened, plus ``image``), every entry pointing at an
    ``assets/client/*.webp`` file it decoded straight from the game client.
    Reusing those as the infographic's lossless originals means the canvas needs
    no BWIKI ``asset-map.json`` and no synced portrait dump to stay sharp.
    """
    portraits={}
    for page in data.get('pages', []):
        if page.get('type')!='character':
            continue
        sources=[]
        for p in page.get('portraits', []) or []:
            if p.get('src'):
                sources.append(p['src'])
        if page.get('image'):
            sources.append(page['image'])
        for src in sources:
            path=ROOT/str(src)
            if not path.is_file():
                continue
            key=str(src)
            if key in portraits:
                continue
            try:
                with Image.open(path) as image:
                    portraits[key]={'file':str(src),'width':image.width,'height':image.height}
            except OSError:
                continue
    return portraits

def main():
    data=load_js(ROOT/'data/index.js') or {'pages':[]}
    # The BWIKI-sourced assets map only exists when a wiki was seeded from the
    # online archive. A pure client rebuild has none of it; missing entries
    # simply degrade to empty rather than aborting the build.
    original=load_json(ROOT/'data/raw/asset-map.json', {}) or {}

    tarot=[]
    soup=load_js(ROOT/'data/pages/2729.js')
    if soup is not None:
        soup=BeautifulSoup(soup['html'],'html.parser')
        for row in soup.select('table.CardSelect tr'):
            cells=row.find_all('td',recursive=False)
            if len(cells)!=5:
                continue
            tarot.append({'id':f'tarot-{len(tarot)+1}','name':cells[1].get_text(strip=True),
                          'image':cells[0].img['src'],'description':cells[2].decode_contents().strip(),
                          'special':cells[3].decode_contents().strip(),'sourceId':2729})
    engravings=[]
    soup=load_js(ROOT/'data/pages/2736.js')
    if soup is not None:
        soup=BeautifulSoup(soup['html'],'html.parser')
        for row in soup.select('table')[-1].select('tr'):
            cells=row.find_all(['td','th'],recursive=False)
            if len(cells)!=2:
                continue
            name=cells[0].get_text(strip=True)
            if '+' not in name:
                continue
            parts=name.split('+')
            engravings.append({'id':f'engraving-{len(engravings)+1}','name':name,'parts':parts,
                              'images':[original.get(p+'刻印.png',{}).get('path') for p in parts],
                              'description':cells[1].decode_contents().strip(),'sourceId':2736})
    if tarot and engravings:
        assert len(tarot)==22 and len(engravings)==10
        assert len({tuple(sorted(e['parts'])) for e in engravings})==10

    equipment_icons={}
    logo=original.get('铃兰之剑logo.png',{}).get('path') if original else None
    if not logo:
        logo=next((v['path'] for v in original.values() if v.get('path','').endswith('logo.png')),None)
    badges={kind:{name[len(prefix):-4]:asset['path'] for name,asset in original.items() if name.startswith(prefix) and name.endswith('.png')}
            for kind,prefix in [('rarities','文字_'),('professions','职业图标_'),('professionBackgrounds','职业图标背景_'),('factions','阵营图标_')]}
    stat_icons={key:(original.get('Icon_'+name+'.png',{}) or {}).get('path') for key,name in [('attack','物攻'),('magic','魔攻'),('defense','物防'),('resistance','魔防'),('health','生命')]}
    # A wiki that was purged of its BWIKI download keeps asset-map.json but not the
    # images under assets/wiki/. Pointing the canvas at those names makes it report
    # "成图素材未收录", so every BWIKI-derived path is checked against the disk and
    # dropped when the file is gone (the front-end then falls back to vector art or
    # to the client asset recorded on the page itself).
    def existing(path):
        return path if path and (ROOT/path).is_file() else None

    logo=existing(logo)
    badges={kind:{name:path for name,path in group.items() if existing(path)} for kind,group in badges.items()}
    stat_icons={key:path for key,path in stat_icons.items() if existing(path)}
    # Client-side replacements for the badges the archive no longer ships: the
    # profession uses the client's team-skill emblem, factions their unittag emblem.
    for page in data['pages']:
        if page.get('type')!='character':
            continue
        if page.get('class') and page.get('professionIcon') and not badges['professions'].get(page['class']):
            badges['professions'][page['class']]=page['professionIcon']
        for name,path in (page.get('factionIcons') or {}).items():
            if path and not badges['factions'].get(name):
                badges['factions'][name]=path
    for t in tarot:t['image']=existing(t['image'])
    for e in engravings:e['images']=[existing(p) for p in (e['images'] or [])]
    # Brand reference titles ship with the offline wiki front-end; only include
    # them when the file actually exists so the canvas never points at nothing.
    # Keyed by character name, never by page id: the same wordmark has to resolve
    # in archives that use BWIKI ids and in ones that use client-side ids.
    reference_titles={'薇佩拉':'assets/brand/vipera-reference-title.png','君士坦丁':'assets/brand/constantine-reference-title.png'}
    reference_titles={k:v for k,v in reference_titles.items() if (ROOT/v).is_file()}

    # Lossless portrait originals: prefer a BWIKI-synced dump, otherwise fall
    # back to the client-sourced portraits already written onto each page.
    portraits=load_json(ROOT/'data/raw/infographic-portraits.json', None)
    if not portraits:
        portraits=discover_client_portraits(data)

    limits={}
    if logo and (ROOT/logo).is_file():
        limits[logo]=640
    for path in reference_titles.values():
        limits[path]=1600
    def add(path,limit):
        if not path:
            return
        if (ROOT/path).is_file():
            limits[path]=max(limit,limits.get(path,0))
    for page in data['pages']:
        if page['type']=='character':
            for p in page.get('portraits', []) or []:
                if p.get('key') in ('base','awakened'):
                    add(p['src'],1800)
            add(page.get('sprite'),192)
            add(page.get('professionIcon'),128)
            for path in (page.get('factionIcons') or {}).values():
                add(path,160)
        elif page['type'] in ('skill','equipment','talent'):
            add(page.get('image'),192)
    for p in data['pages']:
        if p['type']=='equipment':
            equipment_icons[str(p['id'])]=existing((original.get('装备_'+p['name']+'.png',{}) or {}).get('path')) or existing(p['image'])
    for group in badges.values():
        for path in group.values():
            add(path,160)
    for path in stat_icons.values():
        add(path,64)
    for path in equipment_icons.values():
        add(path,192)
    for t in tarot:
        add(t['image'],192)
    for e in engravings:
        for path in (e['images'] or []):
            if isinstance(path, list):
                for sub in path:
                    add(sub, 128)
            else:
                add(path, 128)

    folder=ROOT/'data/infographic-assets';folder.mkdir(exist_ok=True)
    assets={};total=0
    loaded=load_js(ROOT/'data/infographic.js')
    cached=loaded.get('assets',{}) if loaded and any(flag in sys.argv for flag in ('--metadata-only','--refresh-portraits')) else {}
    completed_portraits=0
    for path,limit in sorted(limits.items()):
        if path in cached and (ROOT/cached[path]).is_file() and ('--metadata-only' in sys.argv or path not in portraits):
            assets[path]=cached[path];total+=(ROOT/cached[path]).stat().st_size;continue
        original_entry=portraits.get(path)
        with Image.open(ROOT/(original_entry['file'] if original_entry else path)) as image:
            image=image.convert('RGBA')
            if not original_entry:
                image.thumbnail((limit,limit),Image.Resampling.LANCZOS)
            buf=io.BytesIO();image.save(buf,format='WEBP',quality=85,method=3 if original_entry else 4,lossless=bool(original_entry) or path in reference_titles.values())
        encoded='data:image/webp;base64,'+base64.b64encode(buf.getvalue()).decode('ascii')
        content='window.WIKI_POSTER_IMAGES=window.WIKI_POSTER_IMAGES||{};window.WIKI_POSTER_IMAGES['+dump(path)+']='+dump(encoded)+';\n'
        digest=hashlib.sha256((path+content).encode('utf8')).hexdigest()[:24]
        relative=f'data/infographic-assets/{digest}.js'
        destination=ROOT/relative
        if not destination.exists():
            destination.write_text(content,encoding='utf8')
        assets[path]=relative;total+=len(content.encode('utf8'))
        if original_entry:
            completed_portraits+=1
            if completed_portraits%25==0 or completed_portraits==len(portraits):
                print(f'Lossless native portraits: {completed_portraits}/{len(portraits)}',flush=True)

    star_effects={}
    for page in data['pages']:
        if page['type']=='equipment' or page['title'].startswith('个性/'):
            fields=load_js(ROOT/f"data/pages/{page['id']}.js")
            if not fields:
                continue
            fields=fields['fields']
            stars=[fields.get(n+'星技能','') for n in '一二三四五'] if page['type']=='equipment' else [fields.get('个性描述'+str(n),'') for n in range(1,6)]
            if any(stars):
                star_effects[str(page['id'])]=combine_stars(stars)

    font_manifest=load_json(ROOT/'data/raw/infographic-normal-font-manifest.json', None) or {'family':'','glyphCount':0,'script':'','version':'','charset':''}
    ranges=[]
    for code in sorted(map(ord,font_manifest.get('charset',''))):
        if ranges and ranges[-1][1]+1==code:
            ranges[-1][1]=code
        else:
            ranges.append([code,code])
    result={'version':7,'signatureFont':'assets/fonts/infographic-signature.js','signatureLatinFont':'assets/fonts/infographic-signature-latin.js','nameFont':{'family':font_manifest.get('family',''),'glyphs':font_manifest.get('glyphCount',0),'script':font_manifest.get('script',''),'version':font_manifest.get('version',''),'ranges':ranges},'portraitSizes':{path:{'width':p['width'],'height':p['height']} for path,p in portraits.items()},'referenceTitles':reference_titles,'logo':logo,'statIcons':stat_icons,'badges':badges,'tarot':tarot,'engravings':engravings,'equipmentIcons':equipment_icons,'starEffects':star_effects,'assets':assets}
    (ROOT/'data/infographic.js').write_text('window.WIKI_INFOGRAPHIC_DATA='+dump(result)+';\n',encoding='utf8')
    print(f'Built {len(tarot)} tarot cards, {len(engravings)} engraving combinations, {len(assets)} canvas images ({total/1024/1024:.1f} MiB).',flush=True)

if __name__=='__main__':
    main()
