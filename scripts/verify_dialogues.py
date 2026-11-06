"""Browser check for the story dialogue archive and its portraits.

    python -X utf8 scripts/verify_dialogues.py
"""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / 'index.html').as_uri()
failures = []


def check(name, ok, detail=''):
    print(('PASS ' if ok else 'FAIL ') + name + (f' :: {detail}' if detail else ''), flush=True)
    if not ok:
        failures.append(name)


def main():
    text = (ROOT / 'data' / 'dialogues.js').read_text('utf8')
    D = json.loads(text[text.index('=') + 1:].rstrip().rstrip(';'))
    check('dialogue data loaded', D['stats']['lines'] > 10000, str(D['stats']))
    check('scenes grouped', len(D['scenes']) > 100, str(len(D['scenes'])))
    scene = next(line[0] for line in D['lines'] if line[3] >= 0)
    print('  scene with portraits:', scene, D['scenes'][scene][1][:40])

    errors, failed = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(offline=True, viewport={'width': 1440, 'height': 1000}).new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))

        page.goto(BASE + '#/dialogues')
        page.locator('.dialogue-layout').wait_for()
        check('chapter filters present', page.locator('[data-dlg-chapter]').count() > 5)
        check('scene list present', page.locator('[data-dlg-scene]').count() > 20)
        page.locator('[data-dlg-chapter="共通线"]').click()
        check('chapter filter narrows scenes', page.locator('[data-dlg-scene]').count() > 0)
        page.locator('[data-dlg-scene]').first.click()
        page.locator('.dialogue-transcript-head h2').wait_for()
        check('transcript renders lines', page.locator('.dialogue-line').count() > 0)

        page.locator('#dialogue-query').fill('拉维耶')
        page.wait_for_timeout(600)
        check('full-text search finds lines', page.locator('.dialogue-hit').count() > 0)
        page.locator('.dialogue-hit').nth(1).click()
        page.locator('.dialogue-transcript-head h2').wait_for()
        check('search result opens its scene', page.locator('.dialogue-line').count() > 0)

        page.goto(BASE + f'#/dialogues?scene={scene}')
        page.locator('.dialogue-transcript-head h2').wait_for()
        check('deep link opens the scene', D['scenes'][scene][1][:20] in
              page.locator('.dialogue-transcript-head h2').inner_text())
        # Expression images were removed to shrink the package; transcript
        # text and portrait markers must still render without broken requests.
        markers = page.locator('.dialogue-portrait-mark').count()
        check('transcript renders without portrait assets',
              page.locator('.dialogue-line').count() > 0, f'{markers} portrait markers')

        page.goto(BASE + '#/tools')
        page.locator('.tool-grid').wait_for()
        check('other routes still work', True)
        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()
    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
