"""Extract the supplied Vipera lettering and bundle an offline signature font."""
from pathlib import Path
import base64, io, json, shutil, sys

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.tools/python-fonts'))
from fontTools.ttLib import TTFont


def main():
    reference = ROOT / 'data/raw/infographic-wordmark-reference.png'
    if not reference.exists():
        source = Path('C:/Users/thamechen/Downloads/坏女人字体样板.png')
        with Image.open(source) as image:
            image.crop((160, 1370, 910, 1690)).save(reference)
    image = np.array(Image.open(reference).convert('RGB'))
    r, g, b = [channel.astype(float) for channel in cv2.split(image)]
    selected = ((r > g * 1.12) & (g > b * 1.15) & (r > 165) & (g > 65)) | ((r > 225) & (g > 180))
    selected[:30] = False
    mask = cv2.morphologyEx(selected.astype('uint8') * 255, cv2.MORPH_CLOSE, np.ones((3, 3), 'uint8'))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    mask = np.uint8(np.isin(labels, [i for i in range(1, count) if stats[i, 4] >= 110])) * 255
    # Restore tiny texture holes, retaining the large counters inside the letters.
    count, labels, stats, _ = cv2.connectedComponentsWithStats(255 - mask)
    for i in range(1, count):
        if stats[i, 4] < 160:
            mask[labels == i] = 255
    output = Image.fromarray(np.dstack([image, mask]), 'RGBA')
    output = output.crop(output.getbbox())
    destination = ROOT / 'assets/brand/vipera-reference-title.png'
    output.save(destination)
    # A real cursive CJK font keeps the signature consistent on Android and Windows.
    font = TTFont(ROOT / '.tools/fonts/ZhiMangXing-Regular.ttf')
    font.flavor = 'woff2'
    buffer = io.BytesIO()
    font.save(buffer)
    encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
    folder = ROOT / 'assets/fonts'
    folder.mkdir(exist_ok=True)
    (folder / 'infographic-signature.js').write_text('window.WIKI_SIGNATURE_FONT=' + json.dumps(encoded) + ';\n', encoding='utf-8')
    shutil.copyfile(ROOT / '.tools/fonts/ZhiMangXing-OFL.txt', ROOT / 'assets/licenses/ZhiMangXing-OFL.txt')
    latin = TTFont(ROOT / '.tools/fonts/DancingScript-Variable.ttf')
    latin.flavor = 'woff2'
    latin_bytes = io.BytesIO()
    latin.save(latin_bytes)
    (folder / 'infographic-signature-latin.js').write_text('window.WIKI_SIGNATURE_LATIN_FONT=' + json.dumps(base64.b64encode(latin_bytes.getvalue()).decode('ascii')) + ';\n', encoding='utf-8')
    shutil.copyfile(ROOT / '.tools/fonts/DancingScript-OFL.txt', ROOT / 'assets/licenses/DancingScript-OFL.txt')
    (ROOT / 'assets/licenses/infographic-reference.txt').write_text(
        'Vipera title: extracted from the image supplied by the user (坏女人字体样板.png).\n'
        'Chinese signature font: Zhi Mang Xing, SIL OFL 1.1. https://github.com/googlefonts/zhimangxing\n'
        'Latin signature font: Dancing Script, SIL OFL 1.1. https://github.com/googlefonts/DancingScript\n', encoding='utf-8')
    print(f'Extracted reference lettering {output.size}; signature font {len(buffer.getvalue()) / 1024:.0f} KiB.')


if __name__ == '__main__':
    main()
