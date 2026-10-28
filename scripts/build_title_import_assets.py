"""Bundle unmodified text type and local OCR, including file:// compatible payloads."""
from pathlib import Path
import base64, gzip, hashlib, io, json, shutil, sys, tarfile, urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.tools/python-fonts'))
from fontTools.ttLib import TTFont


def main():
    font = TTFont(ROOT / '.tools/fonts/SourceHanSerifSC-Heavy.otf')
    charset = ''.join(chr(code) for code in sorted(font.getBestCmap()))
    font.flavor = 'woff2'
    buffer = io.BytesIO()
    font.save(buffer)
    (ROOT / 'assets/fonts/infographic-normal-font.js').write_text(
        'window.WIKI_NORMAL_TITLE_FONT=' + json.dumps(base64.b64encode(buffer.getvalue()).decode()) + ';\n', encoding='utf8')
    manifest = {'family': 'Source Han Serif SC', 'version': 'original-2.003', 'glyphCount': len(charset),
                'script': 'assets/fonts/infographic-normal-font.js', 'charset': charset}
    (ROOT / 'data/raw/infographic-normal-font-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf8')
    shutil.copyfile(ROOT / '.tools/fonts/LICENSE.txt', ROOT / 'assets/licenses/SourceHanSerif-OFL.txt')
    vendor = ROOT / '.tools/ocr'
    for package,version in [('tesseract.js','6.0.1'),('tesseract.js-core','6.0.0')]:
        target=vendor/package
        if not (target/'package/package.json').exists():
            target.mkdir(parents=True,exist_ok=True)
            raw=urllib.request.urlopen(f'https://registry.npmjs.org/{package}/-/{package}-{version}.tgz',timeout=60).read()
            with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as archive:archive.extractall(target,filter='data')
    core = (vendor / 'tesseract.js-core/package/tesseract-core-lstm.wasm.js').read_text(encoding='utf8')
    worker = (vendor / 'tesseract.js/package/dist/worker.min.js').read_text(encoding='utf8').split('//# sourceMappingURL=')[0]
    langs, hashes = [], {}
    for code in ['chi_sim', 'chi_tra', 'eng']:
        path = vendor / (code + '.traineddata')
        if not path.exists():
            path.write_bytes(urllib.request.urlopen('https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/4.1.0/' + path.name, timeout=60).read())
        raw = path.read_bytes()
        langs.append({'code': code, 'data': base64.b64encode(gzip.compress(raw, mtime=0)).decode()})
        hashes[path.name] = hashlib.sha256(raw).hexdigest()
    target = ROOT / 'assets/ocr'
    target.mkdir(exist_ok=True)
    # The embedded core already contains its WASM. Direct language buffers avoid all fetches.
    (target / 'title-ocr.js').write_text('window.WIKI_TITLE_OCR=' + json.dumps({'version': '6.0.1', 'source': core + '\n;\n' + worker, 'langs': langs}, separators=(',', ':')) + ';\n', encoding='utf8')
    shutil.copyfile(vendor / 'tesseract.js/package/dist/worker.min.js.LICENSE.txt', ROOT / 'assets/licenses/Tesseract-worker-dependencies.txt')
    shutil.copyfile(vendor / 'tesseract.js-core/package/LICENSE', ROOT / 'assets/licenses/Tesseract-Apache-2.0.txt')
    (ROOT / 'assets/licenses/title-ocr.txt').write_text(
        'Tesseract.js 6.0.1: https://github.com/naptha/tesseract.js\n'
        'Tesseract.js-core 6.0.0: https://github.com/naptha/tesseract.js-core\n'
        'Tessdata fast 4.1.0 (chi_sim, chi_tra, eng): https://github.com/tesseract-ocr/tessdata_fast\n'
        'Apache License 2.0. Unmodified distributions embedded for offline use.\n' + json.dumps(hashes, indent=2) + '\n', encoding='utf8')
    print(f'Original font: {len(charset)} glyphs; offline OCR: {(target / "title-ocr.js").stat().st_size / 1024 / 1024:.1f} MiB', flush=True)


if __name__ == '__main__':
    main()
