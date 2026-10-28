"""Build Convallaria Blade: an OFL display font and the matching offline name outlines.

This is a new derivative design, inspired by the supplied title's sharp terminals,
curved stems and long tapered strokes. It is not the game's original typeface.
"""
from pathlib import Path
import json, shutil, sys, math, zipfile, base64

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.tools/python-fonts'))
from fontTools.ttLib import TTFont
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.basePen import BasePen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.reverseContourPen import ReverseContourPen
from fontTools.ttLib.removeOverlaps import removeOverlaps
from fontTools.pens.areaPen import AreaPen


def warp(point):
    x, y = point
    # Narrow, rising letter bodies with a pronounced bend through the stems.
    # This reshapes the strokes themselves, not just the ends of the serifs.
    bend = 124 * math.sin((y + 110) / 1100 * math.pi)
    return (500 + (x - 500) * .88 + .30 * (y - 400) + bend,
            y * 1.08 + .072 * (x - 500) + 23 * math.sin(x / 1000 * math.pi))


class BladePen(BasePen):
    def __init__(self, target):
        super().__init__(None)
        self.target = target

    def _moveTo(self, point): self.target.moveTo(warp(point))
    def _lineTo(self, point):
        start = self._getCurrentPoint()
        dx, dy = point[0]-start[0], point[1]-start[1]
        pieces = max(1, math.ceil(math.hypot(dx,dy)/250))
        def tangent(p):
            x,y=p
            return (.88*dx+(.30+124*math.pi/1100*math.cos((y+110)/1100*math.pi))*dy,
                    ( .072+23*math.pi/1000*math.cos(x/1000*math.pi))*dx+1.08*dy)
        for i in range(pieces):
            a=(start[0]+dx*i/pieces,start[1]+dy*i/pieces)
            b=(start[0]+dx*(i+1)/pieces,start[1]+dy*(i+1)/pieces)
            wa,wb,da,db=warp(a),warp(b),tangent(a),tangent(b)
            self.target.curveTo((wa[0]+da[0]/(3*pieces),wa[1]+da[1]/(3*pieces)),
                                (wb[0]-db[0]/(3*pieces),wb[1]-db[1]/(3*pieces)),wb)
    def _curveToOne(self, a, b, c): self.target.curveTo(warp(a), warp(b), warp(c))
    def _closePath(self): self.target.closePath()
    def _endPath(self): self.target.endPath()


def add_shape(target, draw):
    recording = RecordingPen()
    draw(recording)
    area = AreaPen()
    recording.replay(area)
    recording.replay(ReverseContourPen(target) if area.value < 0 else target)


def draw_blade(glyph, pen, decorate=True):
    recording = RecordingPen()
    glyph.draw(recording)
    if not decorate:
        recording.replay(BladePen(pen))
        return
    contours, contour = [], RecordingPen()
    for operation, coordinates in recording.value:
        getattr(contour, operation)(*coordinates)
        if operation in ('closePath', 'endPath'):
            contours.append(contour)
            contour = RecordingPen()
    endpoints, crowns, peaks = [], [], []
    for contour in contours:
        bounds = BoundsPen(None)
        contour.replay(bounds)
        if not bounds.bounds:
            continue
        l, t, r, b = bounds.bounds
        # Crown dots become substantial, curved wedges rather than small added horns.
        crown = t > 580 and b > 740 and 25 < r-l < 270 and 35 < b-t < 280
        if crown:
            cx, cy = (l+r)/2, (t+b)/2
            crowns.append(cx)
            def crown_shape(p):
                p.moveTo(warp((cx-105, cy+77)))
                p.curveTo(warp((cx+12,cy+78)),warp((cx+112,cy+53)),warp((cx+155,cy-37)))
                p.curveTo(warp((cx+44,cy+1)),warp((cx-1,cy-11)),warp((cx-39,cy-79)))
                p.curveTo(warp((cx-16,cy+8)),warp((cx-24,cy+50)),warp((cx-105,cy+77)))
                p.closePath()
            add_shape(pen, crown_shape)
        else:
            contour.replay(BladePen(pen))
        points=[points[-1] for op, points in contour.value if op in ('moveTo','lineTo','curveTo') and points]
        endpoints.extend(points)
        for i,point in enumerate(points):
            if point[1]>720 and point[1]>points[i-1][1]+5 and point[1]>=points[(i+1)%len(points)][1]+5:
                peaks.append(point)
    chosen=[]
    for point in sorted(peaks,key=lambda p:-p[1]):
        if any(abs(point[0]-cx)<175 for cx in crowns+chosen):continue
        x,y=warp(point)
        def upper_blade(p):
            p.moveTo((x-22,y-43))
            p.curveTo((x+15,y+45),(x-38,y+115),(x-122,y+132))
            p.curveTo((x-26,y+132),(x+63,y+101),(x+114,y+40))
            p.curveTo((x+48,y+45),(x+22,y+8),(x-22,y-43))
            p.closePath()
        add_shape(pen,upper_blade)
        chosen.append(point[0])
        if len(chosen)==2:break
    lower = [p for p in endpoints if p[1] < 230 and p[0] < 530]
    right = [p for p in endpoints if p[1] < 200 and p[0] > 570]
    if lower:
        x, y = warp(min(lower, key=lambda p: p[1] + p[0]*.20))
        def descending(p):
            p.moveTo((x+43,y+86))
            p.curveTo((x+13,y-13),(x-36,y-96),(x-212,y-174))
            p.curveTo((x-92,y-71),(x-40,y+17),(x+8,y+101))
            p.closePath()
        add_shape(pen, descending)
    if right:
        x, y = warp(max(right, key=lambda p:p[0]-p[1]*.30))
        def return_stroke(p):
            p.moveTo((x-47,y+43))
            p.curveTo((x+21,y+13),(x+96,y+30),(x+113,y+102))
            p.curveTo((x+119,y-11),(x+23,y-84),(x-156,y-100))
            p.curveTo((x-55,y-69),(x+12,y-25),(x+16,y+1))
            p.curveTo((x-3,y-9),(x-27,y-5),(x-47,y+43))
            p.closePath()
        add_shape(pen, return_stroke)


def main():
    source = ROOT / '.tools/fonts/SourceHanSerifSC-Heavy.otf'
    source_font = TTFont(source)
    source_glyphs, source_cmap = source_font.getGlyphSet(), source_font.getBestCmap()
    raw = (ROOT / 'data/index.js').read_text(encoding='utf-8')
    data = json.JSONDecoder().raw_decode(raw[raw.index('=') + 1:])[0]
    names = [p['name'] for p in data['pages'] if p['type'] == 'character']
    proof = '--proof' in sys.argv
    charset = sorted(set(''.join(names) + '霁月瑟蕾妮娅苍穹旅人龘龍鳳凰𠮷' + ''.join(chr(n) for n in range(32,127)))) if proof else [chr(n) for n in sorted(source_cmap)]
    font_builder = FontBuilder(1000, isTTF=True)
    glyph_order = ['.notdef'] + [f'uni{ord(char):04X}' for char in charset]
    font_builder.setupGlyphOrder(glyph_order)
    font_builder.setupCharacterMap({ord(char): name for char, name in zip(charset, glyph_order[1:])})
    outlines, metrics = {}, {}
    for index, (char, name) in enumerate([('', '.notdef')] + list(zip(charset, glyph_order[1:]))):
        glyph = source_glyphs[source_cmap[ord(char)] if char else '.notdef']
        pen = TTGlyphPen(None)
        draw_blade(glyph, Cu2QuPen(pen, max_err=.7, reverse_direction=True), decorate=bool(char and (0x3400 <= ord(char) <= 0x9fff or 0x20000 <= ord(char) <= 0x323af)))
        outlines[name] = pen.glyph()
        outlines[name].recalcBounds(None)
        metrics[name] = (int(glyph.width * .94), getattr(outlines[name], 'xMin', 0))
        if index and index % 4000 == 0: print(f'Display glyphs: {index}/{len(charset)}', flush=True)
    font_builder.setupGlyf(outlines)
    font_builder.setupHorizontalMetrics(metrics)
    font_builder.setupHorizontalHeader(ascent=1300, descent=-500)
    font_builder.setupOS2(sTypoAscender=1300, sTypoDescender=-500, usWinAscent=1500, usWinDescent=700,
                         sxHeight=520, sCapHeight=800, usWeightClass=700, fsSelection=0x40)
    font_builder.setupNameTable({'familyName': 'Convallaria Blade', 'styleName': 'Regular',
        'uniqueFontIdentifier': 'SoCwiki:ConvallariaBlade:2.0', 'fullName': 'Convallaria Blade',
        'psName': 'ConvallariaBlade-Regular', 'version': 'Version 2.000',
        'copyright': source_font['name'].getDebugName(0) + '\nModified display outlines Copyright 2026 SoCwiki contributors.',
        'description': 'A full-cmap display font with sculpted curved strokes, crescent crowns and sweeping terminals for arbitrary names. Inspired by the supplied reference; not the original game typeface.',
        'licenseDescription': 'Licensed under the SIL Open Font License, Version 1.1.',
        'licenseInfoURL': 'https://openfontlicense.org'})
    font_builder.font['name'].setName('铃兰刃光', 1, 3, 1, 0x804)
    font_builder.font['name'].setName('铃兰刃光 Regular', 4, 3, 1, 0x804)
    font_builder.setupPost(italicAngle=-13)
    font_builder.setupMaxp()
    removeOverlaps(font_builder.font)
    folder = ROOT / ('test-results/title-proof' if proof else 'assets/fonts')
    folder.mkdir(parents=True, exist_ok=True)
    ttf = folder / 'ConvallariaBlade-Regular.ttf'
    font_builder.save(ttf)
    font_builder.font.flavor = 'woff2'
    font_builder.save(folder / 'ConvallariaBlade-Regular.woff2')
    if proof:
        print(f'Built proof font with {len(charset)} characters.')
        return
    encoded=base64.b64encode((folder / 'ConvallariaBlade-Regular.woff2').read_bytes()).decode('ascii')
    (folder / 'infographic-title-font.js').write_text('window.WIKI_TITLE_FONT='+json.dumps(encoded)+';\n', encoding='utf-8')
    notices = ROOT / 'assets/licenses'
    notices.mkdir(exist_ok=True)
    shutil.copyfile(ROOT / '.tools/fonts/LICENSE.txt', notices / 'SourceHanSerif-OFL.txt')
    (notices / 'infographic-title-art.txt').write_text(
        'Convallaria Blade / 铃兰刃光, version 2.000. SIL OFL 1.1.\n'
        'A new display derivative of Adobe Source Han Serif SC Heavy.\n'
        'https://github.com/adobe-fonts/source-han-serif\n'
        'Rebuilt curved stems, crescent crown contours and wide sweeping terminals are baked into the outlines.\n'
        'The poster adds color, metallic texture, outlines, and highlights. Not the original game typeface.\n', encoding='utf-8')
    readme = folder / 'ConvallariaBlade-README.txt'
    readme.write_text(f'铃兰刃光 / Convallaria Blade 2.0\n\n基于参考图的尖锋、弧形笔势与细长收笔设计的新字形，非官方原字体。\n'
        f'包含 {len(charset)} 个字符，覆盖档案中的全部 {len(names)} 个角色名及基本英文、数字。\n'
        '保留基础字体的完整 Unicode 映射，覆盖基本汉字区、扩展 A、部分扩展区、简繁体及拉丁字母；新增名字无需重新烘焙。未收录字符会明确提示。\n'
        'Windows/macOS 安装 TTF；网页可使用 WOFF2。正文请继续使用常规字体。\n'
        '字体本身为单色轮廓，金属渐变与纹理由一图流工坊自动叠加；在其他软件中可自行添加颜色效果。\n'
        '字形派生自 Adobe Source Han Serif SC Heavy，按 SIL OFL 1.1 许可发布，已使用新的字体名称。\n\n'
        '收录字符：\n' + ''.join(charset) + '\n', encoding='utf-8')
    release = ROOT / 'release'
    release.mkdir(exist_ok=True)
    with zipfile.ZipFile(release / 'ConvallariaBlade-fonts-2.0.zip', 'w', zipfile.ZIP_DEFLATED) as package:
        for file in [ttf, folder / 'ConvallariaBlade-Regular.woff2', readme, notices / 'SourceHanSerif-OFL.txt', notices / 'infographic-title-art.txt']:
            package.write(file, 'ConvallariaBlade/' + file.name)
    (ROOT / 'data/raw/infographic-font-manifest.json').write_text(json.dumps({'family': 'Convallaria Blade', 'glyphCount': len(charset), 'characters': len(names), 'charset': ''.join(charset), 'script': 'assets/fonts/infographic-title-font.js', 'version': '2.0'}, ensure_ascii=False), encoding='utf-8')
    print(f'Built Convallaria Blade: {len(charset)} glyphs, {len(names)} currently archived character names, TTF + WOFF2 + font package.')


if __name__ == '__main__':
    main()
