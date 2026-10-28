"""Create a portable release with no interpreter or server dependency."""
from __future__ import annotations
import hashlib, json, pathlib, zipfile

ROOT=pathlib.Path(__file__).resolve().parents[1]

def main():
    archive=json.loads((ROOT/'data'/'archive.json').read_text(encoding='utf-8'))
    if not archive['complete']:raise SystemExit('Archive is incomplete. Check data/archive.json before packaging.')
    release=ROOT/'release';release.mkdir(exist_ok=True)
    name='SoCwiki-offline-'+archive['builtAt'][:10]+'.zip'
    destination=release/name
    files=[ROOT/p for p in ['semantic-core.js','semantic-ui.js','wiki-update-convert.js','wiki-updates.js','updates-search.css','data/advanced-search.js','data/update-baseline.js','THIRD_PARTY_NOTICES.md','index.html','app.js','styles.css','refinements.css','character-ui.css','character-ui.js','tools-core.js','tools-ui.js','personal-data.js','infographic-core.js','infographic-canvas.js','infographic-ui.js','infographic-title-image.js','infographic.css','data/infographic.js','start.cmd','README.md','data/index.js','data/tools.js','data/search.js','data/archive.json','data/sources.json']]
    catalog_text=(ROOT/'data/infographic.js').read_text(encoding='utf8')
    catalog=json.JSONDecoder().raw_decode(catalog_text[catalog_text.index('=')+1:])[0]
    files+=list((ROOT/'assets').rglob('*'))+list((ROOT/'data'/'pages').glob('*.js'))+[ROOT/path for path in sorted(set(catalog['assets'].values()))]
    files=[p for p in files if p.is_file() and not p.name.startswith('ConvallariaBlade-') and p.name!='infographic-title-font.js']
    with zipfile.ZipFile(destination,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=5) as z:
        for path in files:z.write(path,'SoCwiki/'+path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(destination) as z:
        bad=z.testzip()
        if bad:raise SystemExit('ZIP validation failed: '+bad)
    digest=hashlib.sha256()
    with destination.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):digest.update(chunk)
    (release/(name+'.sha256')).write_text(digest.hexdigest()+'  '+name+'\n',encoding='utf-8')
    print(f'Packaged {len(files)} files; {destination.stat().st_size/1024/1024:.1f} MiB\n{destination}\nSHA256 {digest.hexdigest()}',flush=True)

if __name__=='__main__':main()
