"""Parallel regression runner.

Runs the full acceptance suite and every historical round concurrently instead
of in two serial background chains. Each job is an independent OS process, so
the GIL and node's single-threaded VM never serialise the 192-battle sweeps.

    python -X utf8 scripts/run_regression.py                 # all jobs
    python -X utf8 scripts/run_regression.py --jobs 12       # override concurrency
    python -X utf8 scripts/run_regression.py --only 40,42    # subset
    python -X utf8 scripts/run_regression.py --no-full       # skip the 192-field full sweep

Writes per-job logs to work/_reg_<name>.txt and a machine-readable timing
report to work/_reg_summary.json.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'work'
ROUNDS = [21, 22, 23, 24, 25, 26, 37, 38, 39, 40, 41, 42, 43]
PHYSICAL_CORES = int(os.environ.get('REG_PHYSICAL_CORES') or
                     max(1, (int(os.environ.get('NUMBER_OF_PROCESSORS', '8')) + 1) // 2))
# Eight heavy jobs (full + r37..r43) each contain their own 192-battle sweep.
# Running all of them at full physical-core concurrency makes them contend for
# memory bandwidth: measured 10 workers -> 658.9s, 8 workers -> 623.4s on the
# same 10-core box, with identical ALL-PASS results. Leave two cores free.
DEFAULT_JOBS = max(1, PHYSICAL_CORES - 2)


def jobs(no_full: bool, only: str | None):
    out = []
    if only:
        for tok in only.split(','):
            tok = tok.strip()
            out.append((tok, [sys.executable, '-X', 'utf8', f'scripts/verify_round{tok}.py']))
        return out
    if not no_full:
        # `verify_battle.py --full` runs the SAME assertions as the fast
        # suite PLUS the 192-battle sweep — it is a strict superset. Running
        # both concurrently duplicated ~200s of CPU work and made every other
        # job contend for cores. Keep only the superset.
        out.append(('full', [sys.executable, '-X', 'utf8', 'scripts/verify_battle.py', '--full']))
    else:
        out.append(('fast', [sys.executable, '-X', 'utf8', 'scripts/verify_battle.py']))
    for n in ROUNDS:
        out.append((f'r{n}', [sys.executable, '-X', 'utf8', f'scripts/verify_round{n}.py']))
    # Wiki term-jump regressions (抉择 / 变化技能词条) — 7s, mostly browser idle.
    out.append(('rules', [sys.executable, '-X', 'utf8', 'scripts/verify_battle_rules.py']))
    return out


def run_one(name, cmd):
    log = WORK / f'_reg_{name}.txt'
    t0 = time.perf_counter()
    with log.open('w', encoding='utf8', errors='replace') as fh:
        p = subprocess.run(cmd, cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT)
    wall = time.perf_counter() - t0
    text = log.read_text(encoding='utf8', errors='replace')
    status = 'ALL PASS' if 'ALL PASS' in text else (
        'FAILED' if ('FAILED' in text or p.returncode != 0) else 'UNKNOWN')
    detail = ''
    for line in text.splitlines():
        if line.startswith('FAIL') or 'FAILED:' in line or 'Traceback' in line:
            detail = line[:220]
            break
    return {'name': name, 'wall': round(wall, 1), 'status': status,
            'returncode': p.returncode, 'log': str(log.relative_to(ROOT)), 'detail': detail}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=DEFAULT_JOBS)
    ap.add_argument('--only', default=None)
    ap.add_argument('--no-full', action='store_true')
    args = ap.parse_args()
    WORK.mkdir(exist_ok=True)
    todo = jobs(args.no_full, args.only)
    t0 = time.perf_counter()
    print(f'parallel regression: {len(todo)} jobs, {args.jobs} concurrent processes '
          f'(physical cores={PHYSICAL_CORES})', flush=True)
    results = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futs = {pool.submit(run_one, name, cmd): name for name, cmd in todo}
        for f in as_completed(futs):
            r = f.result()
            results.append(r)
            print(f"  [{time.perf_counter()-t0:6.1f}s] {r['name']:6s} "
                  f"{r['wall']:7.1f}s  {r['status']:8s} {r['detail']}", flush=True)
    wall = time.perf_counter() - t0
    serial = sum(r['wall'] for r in results)
    summary = {'jobs': args.jobs, 'wall': round(wall, 1), 'serial_sum': round(serial, 1),
               'speedup': round(serial / max(wall, .001), 2),
               'within_10min': wall <= 600,
               'over_10min_jobs': [r['name'] for r in results if r['wall'] > 600],
               'results': sorted(results, key=lambda x: -x['wall'])}
    (WORK / '_reg_summary.json').write_text(json.dumps(summary, indent=1), 'utf8')
    print(f"\nWALL {wall:.1f}s | serial sum {serial:.1f}s | speedup {summary['speedup']}x | "
          f"within 10 min: {summary['within_10min']}", flush=True)
    print('slowest:', ', '.join(f"{r['name']}={r['wall']}s" for r in summary['results'][:6]), flush=True)
    bad = [r for r in results if r['status'] != 'ALL PASS']
    if bad:
        print('NOT PASS:', ', '.join(f"{r['name']}:{r['detail'][:80]}" for r in bad), flush=True)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
