"""Browser check for equipment star diffs and structured skill cards.

    python -X utf8 scripts/verify_equipment.py
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
    pages = ROOT / 'data' / 'pages'
    equipment = []
    for path in pages.glob('*.js'):
        text = path.read_text('utf8')
        if '一星技能' not in text:
            continue
        try:
            equipment.append((path.stem, json.loads(text[text.index('=') + 1:].rstrip().rstrip(';'))))
        except (ValueError, IndexError):
            continue
    with_cmp = [item for item in equipment if item[1].get('starComparison')]
    with_cards = [item for item in equipment if item[1].get('equipmentSkills')]
    check('all equipment pages have a star comparison', len(with_cmp) == len(equipment),
          f'{len(with_cmp)}/{len(equipment)}')
    check('client equipment pages have skill cards', len(with_cards) > 100, str(len(with_cards)))

    errors, failed = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(offline=True, viewport={'width': 1440, 'height': 1000}).new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))
        for pid in (2917, 500000251, 2990, 8651):
            page.goto(BASE + f'#/page/{pid}')
            page.locator('#main').wait_for()
            page.wait_for_timeout(220)
            levels = page.locator('.trait-levels .trait-level').count()
            check(f'page {pid} shows five star levels', levels == 5, str(levels))
            body = page.locator('#main').inner_text()
            check(f'page {pid} wording fits equipment', '此个性' not in body)
            cards = page.locator('.equipment-skill').count()
            if cards:
                check(f'page {pid} has skill cards', cards == 5, str(cards))
                check(f'page {pid} has skill facts',
                      page.locator('.equipment-skill:not([hidden]) .ability-facts div').count() > 0)
                page.locator('[data-equip-star-btn="3"]').click()
                shown = page.locator('.equipment-skill:not([hidden])')
                check(f'page {pid} switches to 3 stars',
                      shown.count() == 1 and shown.first.get_attribute('data-equip-star') == '3')
        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()
    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
