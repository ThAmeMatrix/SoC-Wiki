"""Round 21: dialogue search return, image loading for hosted pages, auto-battle simulator.

    python -X utf8 scripts/verify_round21.py
"""
import json
import subprocess
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / 'index.html').as_uri()
NODE = Path(r'C:\Users\thamechen\AppData\Local\Programs\Python\Python313\Lib\site-packages\playwright\driver\node.exe')
failures = []


def check(name, ok, detail=''):
    print(('PASS ' if ok else 'FAIL ') + name + (f' :: {detail}' if detail else ''), flush=True)
    if not ok:
        failures.append(name)


def load(rel):
    t = (ROOT / rel).read_text('utf8')
    return json.JSONDecoder().raw_decode(t[t.index('=') + 1:])[0]


ENGINE_TEST = r"""
const fs=require('fs'),vm=require('vm');const ctx={window:{}};vm.createContext(ctx);
for(const f of ['data/world-data.js','data/battle-sim.js','battle-sim-core.js'])vm.runInContext(fs.readFileSync(f,'utf8'),ctx);
const W=ctx.window.WIKI_WORLD_DATA,D=ctx.window.WIKI_BATTLE_SIM,S=ctx.window.WikiBattleSim;
const maps=W.maps.filter(m=>(m.cells||[]).length>=40);const keys=D.roster.map(r=>r.key);
const map=maps.find(m=>m.id===3)||maps[0];
const teams={A:keys.slice(0,4),B:keys.slice(4,8)};
const a=S.simulate({data:D,map,teams,seed:7,maxRounds:20});
const b=S.simulate({data:D,map,teams,seed:7,maxRounds:20});
let finished=0,errors=0,slow=0,skills=0,moves=0,illegal=0;
for(let i=0;i<20;i++){const m=maps[(i*41)%maps.length];const rr=S.rng(i+3);const sh=keys.slice().sort(()=>rr()-0.5);
 const t=Date.now();const r=S.simulate({data:D,map:m,teams:{A:sh.slice(0,5),B:sh.slice(5,10)},seed:i,maxRounds:20});
 if(Date.now()-t>2000)slow++;if(r.error){errors++;continue;}finished++;
 for(const s of r.steps){if(s.kind==='skill')skills++;if(s.kind==='move')moves++;
  for(const u of s.snap){const c=r.grid.at(u.x,u.y);if(u.alive&&(!c||!c.walk))illegal++;}}}
const occ=a.steps.every(s=>{const seen=new Set();for(const u of s.snap){if(!u.alive)continue;const k=u.x+','+u.y;if(seen.has(k))return false;seen.add(k);}return true;});
console.log(JSON.stringify({winner:a.winner,steps:a.steps.length,det:JSON.stringify(a.steps.map(s=>s.text))===JSON.stringify(b.steps.map(s=>s.text)),
 finished,errors,slow,skills,moves,illegal,occ,log:S.logText(a,{seed:7}).split('\n').length,notes:S.AI_NOTES.length}));
"""


def main():
    # ---------- data / build ----------
    V = load('data/image-variants.js')
    check('thumbnail variants built', len(V['thumb']) > 300, str(len(V['thumb'])))
    check('display variants built', len(V['display']) > 300, str(len(V['display'])))
    missing = [r for r in V['thumb'][:80] if not (ROOT / 'assets/thumb' / r).with_suffix('.webp').is_file()]
    check('every listed thumbnail exists', not missing, str(missing[:3]))
    big_src = sum((ROOT / 'assets' / r).stat().st_size for r in V['display'])
    big_out = sum((ROOT / 'assets/display' / r).with_suffix('.webp').stat().st_size for r in V['display'])
    check('display variants are at least 4x lighter', big_out * 4 < big_src,
          f'{big_src / 1048576:.0f} MiB -> {big_out / 1048576:.0f} MiB')
    over = [r for r in V['thumb'] if (ROOT / 'assets/thumb' / r).with_suffix('.webp').stat().st_size > 200 * 1024]
    check('thumbnails stay small (<200 KiB)', not over, str(over[:3]))
    html = (ROOT / 'index.html').read_text('utf8')
    for name in ('dialogues', 'world-data', 'client-code', 'skill-mechanics', 'enhance-data', 'battle-sim'):
        check(f'{name}.js not loaded eagerly', f'data/{name}.js' not in html)
    check('perf-core + image-variants loaded', 'perf-core.js' in html and 'data/image-variants.js' in html)
    check('service worker only on http(s)', "/^https?:$/.test(location.protocol)" in (ROOT / 'perf-core.js').read_text('utf8'))
    sw = (ROOT / 'sw.js').read_text('utf8')
    check('service worker caches assets only', "includes('/assets/')" in sw and 'html' not in sw.split('fetch')[1][:400])
    pkg = (ROOT / 'scripts/package.py').read_text('utf8')
    check('package includes new modules', all(x in pkg for x in ('perf-core.js', 'battle-sim-core.js', 'data/battle-sim.js', 'data/image-variants.js', 'stat-bars.js', 'nav-config.js')))
    reb = (ROOT / 'scripts/socdecode/rebuild.py').read_text('utf8')
    check('rebuild runs sim + variants', 'extract_battle_sim.py' in reb and 'build_image_variants.py' in reb)

    D = load('data/battle-sim.js')
    check('simulator roster covers the playable cast', len(D['roster']) >= 90, str(len(D['roster'])))
    check('every roster entry has stats and moves', all(r['stats']['hp'] > 0 and r['move']['mob'] > 0 for r in D['roster']))
    check('every roster entry can attack', all(any(s.get('usable') and not s.get('heal') for s in r['skills']) for r in D['roster']))
    src_restraints = load('data/combat-data.js').get('restraints', [])
    check('restraint table matches the client data', len(D['restraints']) == len(src_restraints) > 0,
          f"{len(D['restraints'])} / {len(src_restraints)}")

    # ---------- engine (node, no DOM) ----------
    out = subprocess.run([str(NODE), '-e', ENGINE_TEST], cwd=ROOT, capture_output=True, text=True, encoding='utf8', timeout=240)
    try:
        e = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        e = {}
        print(out.stdout[-800:], out.stderr[-800:])
    check('engine finishes a battle with a winner', e.get('winner') in ('A', 'B', 'draw'), str(e.get('winner')))
    check('engine is deterministic for a seed', e.get('det') is True)
    check('20 random maps / teams all simulate', e.get('finished', 0) >= 18 and e.get('slow', 1) == 0, str(e))
    check('units both move and use skills', e.get('skills', 0) > 100 and e.get('moves', 0) > 20, str(e))
    check('nobody stands on water / blocked cells', e.get('illegal', 1) == 0, str(e.get('illegal')))
    check('no two living units share a cell', e.get('occ') is True)
    check('text log exported', e.get('log', 0) > 20)
    check('simulation rules documented', e.get('notes', 0) >= 6)

    errors, failed = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(offline=True, viewport={'width': 1500, 'height': 950}, accept_downloads=True)
        page = ctx.new_page()
        page.set_default_timeout(20000)
        page.on('pageerror', lambda x: errors.append(str(x)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed.append(r.url))
        reqs = []
        page.on('request', lambda r: reqs.append(r.url))

        # ---------- 2. loading ----------
        page.goto(BASE + '#/')
        page.wait_for_timeout(700)
        heavy = [u for u in reqs if any(k in u for k in ('dialogues.js', 'world-data.js', 'client-code.js', 'skill-mechanics.js', 'battle-sim.js'))]
        check('home page loads no page-specific data', not heavy, str(heavy))
        page.goto(BASE + '#/characters')
        page.wait_for_timeout(700)
        srcs = page.evaluate("()=>[...document.querySelectorAll('#main img')].map(i=>i.getAttribute('src')||'')")
        orig_big = [s for s in srcs if s.startswith('assets/client/') and not s.split('/')[-1].startswith('sprite-')
                    and (ROOT / s).is_file() and (ROOT / s).stat().st_size > 300 * 1024]
        check('character list never loads >300 KiB originals', not orig_big, str(orig_big[:3]))
        idx = load('data/index.js')
        ch = next(x for x in idx['pages'] if x.get('type') == 'character' and x.get('portraits'))
        page.goto(BASE + f"#/page/{ch['id']}")
        page.locator('.portrait-stage img').wait_for()
        src = page.locator('.portrait-stage img').get_attribute('src')
        href = page.locator('.portrait-stage').get_attribute('href')
        check('detail portrait uses the display variant', src.startswith('assets/display/'), src)
        check('lightbox / download still open the original', href.startswith('assets/client/'), href)
        sk = next(x for x in idx['pages'] if x.get('type') == 'skill' and not x.get('redirect'))
        reqs.clear()
        page.goto(BASE + f"#/page/{sk['id']}")
        page.wait_for_timeout(1200)
        check('skill page loads mechanics on demand',
              any('skill-mechanics.js' in u for u in reqs) and page.evaluate('()=>!!window.WIKI_SKILL_MECHANICS'))
        g = next(x for x in idx['pages'] if x.get('type') == 'guide' and x.get('image'))
        page.goto(BASE + f"#/page/{g['id']}")
        page.wait_for_timeout(1000)
        lazy = page.evaluate("()=>{const im=[...document.querySelectorAll('.wiki-content img')];return [im.length,im.filter(i=>i.loading==='lazy').length]}")
        check('archived article images are lazy', lazy[0] > 0 and lazy[0] == lazy[1], str(lazy))

        # ---------- 1. dialogues ----------
        page.goto(BASE + '#/dialogues')
        page.locator('#dialogue-query').fill('拉维耶')
        page.wait_for_timeout(500)
        hits = page.locator('.dialogue-hit').count()
        page.evaluate("()=>{document.querySelector('.dialogue-lines').scrollTop=420}")
        page.locator('.dialogue-hit').nth(8).click()
        page.wait_for_timeout(300)
        check('opening a hit shows「返回搜索结果」', page.locator('[data-dlg-back]').count() == 1)
        check('the matching line is highlighted', page.locator('.dialogue-line.is-focus').count() == 1)
        check('scene URL remembers the search', 'q=' in page.evaluate('location.hash') and 'scene=' in page.evaluate('location.hash'))
        page.locator('[data-dlg-back]').click()
        page.wait_for_timeout(300)
        check('back restores every hit', page.locator('.dialogue-hit').count() == hits, f'{hits}')
        check('back restores the query box', page.locator('#dialogue-query').input_value() == '拉维耶')
        check('back restores the list scroll', abs(page.evaluate("()=>document.querySelector('.dialogue-lines').scrollTop") - 420) < 4)
        page.goto(BASE + '#/dialogues?q=' + '拉维耶')
        page.wait_for_timeout(400)
        check('search URL reopens the result list', page.locator('.dialogue-hit').count() == hits)
        page.goto(BASE + '#/dialogues')
        page.wait_for_timeout(300)
        check('plain route no longer opens scene 0', page.locator('.dialogue-placeholder').count() == 1)

        # ---------- 3. simulator ----------
        page.goto(BASE + '#/tools')
        page.wait_for_timeout(300)
        check('tool card links to the simulator', page.locator('a.tool-card[href="#/tools/battle"]').count() == 1)
        page.goto(BASE + '#/tools/battle')
        page.locator('#bsim-board svg').wait_for(timeout=30000)
        check('board draws the client map', page.locator('.bsim-cell').count() > 40)
        check('units are placed for both sides',
              page.locator('.bsim-token.side-A').count() >= 1 and page.locator('.bsim-token.side-B').count() >= 1)
        total = int(page.locator('#bsim-range').get_attribute('max'))
        check('a full battle log is produced', total > 5 and page.locator('.bsim-log-item').count() == total + 1, str(total))
        check('result + per-unit stats shown', page.locator('.bsim-result').count() == 1 and page.locator('.bsim-table tbody tr').count() >= 2)
        page.locator('[data-play="next"]').click()
        check('stepping highlights the acting unit', page.locator('.bsim-token.is-actor').count() == 1)
        check('step detail explains the decision', len(page.locator('#bsim-detail').inner_text()) > 20)
        found = False
        for _ in range(total):
            page.locator('[data-play="next"]').click()
            if page.locator('.bsim-area').count():
                found = True
                break
        check('skill steps show area + target', found)
        page.locator('.bsim-log-item').nth(3).click()
        check('clicking the log jumps the replay', page.locator('#bsim-pos').inner_text().startswith('3 /'))
        page.locator('[data-play="toggle"]').click()
        page.wait_for_timeout(1900)
        page.locator('[data-play="toggle"]').click()
        check('autoplay advances', not page.locator('#bsim-pos').inner_text().startswith('3 /'))
        with page.expect_download() as dl:
            page.locator('[data-export="txt"]').click()
        text = Path(dl.value.path()).read_text('utf8')
        check('TXT log export', text.startswith('# 铃兰档案馆 · 自动对局模拟') and '统计：' in text)
        with page.expect_download() as dl:
            page.locator('[data-export="json"]').click()
        data = json.loads(Path(dl.value.path()).read_text('utf8'))
        check('JSON log export', data.get('format') == 'socwiki-battle-sim' and len(data.get('steps', [])) == total + 1)
        before = page.locator('#bsim-title').inner_text()
        page.locator('#bsim-seed').fill('99')
        page.locator('#bsim-seed').dispatch_event('change')
        page.wait_for_timeout(300)
        check('changing the seed re-runs', '种子 99' in page.locator('#bsim-title').inner_text() and before != page.locator('#bsim-title').inner_text())
        check('rules + sources documented', page.locator('.tool-help li').count() >= 6)

        check('no page errors', not errors, '; '.join(errors[:3]))
        check('no failed requests', not failed, '; '.join(failed[:3]))
        browser.close()

    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
