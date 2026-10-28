"""Check original pixel retention and the usable character-name font deliverables."""
from pathlib import Path
import base64, io, json, sys
import numpy as np
from PIL import Image, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.tools/python-fonts'))
from fontTools.ttLib import TTFont


def load(path):
    text = path.read_text(encoding='utf-8')
    return json.JSONDecoder().raw_decode(text[text.index('=') + 1:])[0]


def main():
    catalog = load(ROOT / 'data/infographic.js')
    sources = json.loads((ROOT / 'data/raw/infographic-portraits.json').read_text(encoding='utf-8'))
    assert catalog['portraitSizes'].keys() == sources.keys()
    upgraded = 0
    font_only='--font-only' in sys.argv
    for path, original in ([] if font_only else sources.items()):
        payload = (ROOT / catalog['assets'][path]).read_text(encoding='utf-8')
        encoded = payload.split('data:image/webp;base64,')[1].split('"')[0]
        with Image.open(io.BytesIO(base64.b64decode(encoded))) as poster, Image.open(ROOT / original['file']) as raw, Image.open(ROOT / path) as old:
            assert poster.size == raw.size == (original['width'], original['height']), path
            assert catalog['portraitSizes'][path] == {'width': raw.width, 'height': raw.height}
            upgraded += poster.width > old.width or poster.height > old.height
            actual, expected = np.array(poster.convert('RGBA')), np.array(raw.convert('RGBA'))
            assert np.array_equal(actual[:, :, 3], expected[:, :, 3]), (path, 'alpha')
            visible = expected[:, :, 3] > 0
            assert np.array_equal(actual[:, :, :3][visible], expected[:, :, :3][visible]), (path, 'visible RGB')
    pages = load(ROOT / 'data/index.js')['pages']
    names = [page['name'] for page in pages if page['type'] == 'character']
    payload=(ROOT / catalog['nameFont']['script']).read_text(encoding='utf8')
    font=TTFont(io.BytesIO(base64.b64decode(json.loads(payload.split('=',1)[1].rstrip(';\n')))))
    original=TTFont(ROOT / '.tools/fonts/SourceHanSerifSC-Heavy.otf')
    cmap=font.getBestCmap()
    assert len(cmap)==catalog['nameFont']['glyphs'] and cmap==original.getBestCmap()
    assert font['name'].getDebugName(1)=='Source Han Serif SC Heavy'
    from fontTools.pens.recordingPen import RecordingPen
    for ch in set(''.join(names)+'龘龍鳳凰𠮷霁月'):
        glyph=cmap[ord(ch)];a,b=RecordingPen(),RecordingPen()
        font.getGlyphSet()[glyph].draw(a);original.getGlyphSet()[glyph].draw(b)
        assert a.value==b.value,(ch,'modified glyph')
    report = {'status': 'passed', 'losslessNativePortraits': 0 if font_only else len(sources), 'higherResolutionPortraits': upgraded,
              'characterNamesCovered': len(names), 'glyphs': catalog['nameFont']['glyphs'], 'formats': ['embedded WOFF2'], 'originalGlyphsUnmodified':True}
    (ROOT / ('test-results/infographic-normal-font-verification.json' if font_only else 'test-results/infographic-quality-verification.json')).write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
