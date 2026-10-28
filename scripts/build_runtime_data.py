"""Small local indexes for semantic search and revision-based runtime updates."""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]
def load_js(path):
    s=path.read_text(encoding='utf8');return json.JSONDecoder().raw_decode(s[s.index('=')+1:])[0]
def write(name,key,value):
    (ROOT/'data'/name).write_text('window.'+key+'='+json.dumps(value,ensure_ascii=False,separators=(',',':')).replace('</script','<\\/script')+';\n',encoding='utf8')
def main():
    data=load_js(ROOT/'data/index.js');records={};revisions={}
    for page in data['pages']:
        doc=load_js(ROOT/f"data/pages/{page['id']}.js");revisions[str(page['id'])]=doc['revision']
        if page['type'] in ('character','skill','talent','equipment','status'):
            records[str(page['id'])]={'fields':doc['rawFields'],'related':doc.get('related',[])}
    write('advanced-search.js','WIKI_ADVANCED_DATA',records)
    images=json.loads((ROOT/'data/raw/images.json').read_text(encoding='utf8'))
    mapped=json.loads((ROOT/'data/raw/asset-map.json').read_text(encoding='utf8'))
    by_name={item['name']:item for item in images}
    for name,item in mapped.items():
        raw=by_name.get(name,{})
        item.update(size=raw.get('size',0),mime=raw.get('mime','image/png'))
    captured=json.loads((ROOT/'data/raw/sync-report.json').read_text(encoding='utf8'))['capturedAt']
    write('update-baseline.js','WIKI_UPDATE_BASELINE',{'capturedAt':captured,'revisions':revisions,'images':mapped})
    print(f'Built runtime indexes: {len(records)} search records, {len(revisions)} revisions, {len(mapped)} image mappings')
if __name__=='__main__':main()
