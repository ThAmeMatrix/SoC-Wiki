"""Verify the archive keeps exactly one real copy of every resource.

    python -X utf8 scripts/verify_archive_space.py

Builds a tiny throwaway archive, then checks that materialize() uses hard
links, that a failed link is skipped instead of silently copying the blob,
and that disk_report()/gc() account for real copies and thumbnail caches.
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from socdecode.archive.store import Store  # noqa: E402
from socdecode.archive.catalog import LABELS  # noqa: E402

failures = []


def check(name, ok, detail=''):
    print(('PASS ' if ok else 'FAIL ') + name + (f' :: {detail}' if detail else ''), flush=True)
    if not ok:
        failures.append(name)


def main():
    tmp = Path(tempfile.mkdtemp(prefix='socspace-'))
    store = Store(tmp)
    digest, size, _ = store.put_bytes(b'hello archive world', '.png')
    entry = ['image/demo/a.png', 'image', 'demo', digest, size, '.png', 'demo.unity3d', {}]
    store.write_version({'id': 'v1', 'label': 'v1', 'categories': ['image'], 'entries': 1,
                         'bytes': size, 'changes': {}, 'counts': {}},
                        [entry], {}, {}, 'report')
    label = LABELS.get('image', 'image')
    relative = f'{label}/demo/a.png'

    folder, linked, removed = store.materialize('v1')
    target = folder / relative
    check('materialize made a link', target.is_file(), str(target))
    check('linked count reported', linked == 1, str((linked, removed)))
    check('link shares the blob inode', target.stat().st_nlink > 1,
          f"nlink={target.stat().st_nlink}")
    check('no silent copies', store.last_materialize['skipped'] == 0, str(store.last_materialize))

    # A second identical run should not re-create anything.
    _, linked2, _ = store.materialize('v1')
    check('refresh is incremental', linked2 == 0, str(linked2))

    # disk_report separates hard links from real copies (before any monkeypatch).
    copy_dir = tmp / 'library' / 'copy'
    copy_dir.mkdir(parents=True, exist_ok=True)
    (copy_dir / 'real.png').write_bytes(b'x' * 500)
    thumb_dir = tmp / 'thumbs' / 'ab'
    thumb_dir.mkdir(parents=True, exist_ok=True)
    (thumb_dir / f'{digest}.png').write_bytes(b'thumb')
    (thumb_dir / 'deadbeef.png').write_bytes(b'orphan')
    report = store.disk_report()
    check('objects counted', report['objects'] >= size, str(report))
    check('real copies counted', report['libraryCopies'] >= 500, str(report))
    check('hard links reported separately', report['libraryLinks'] >= size, str(report))
    check('thumbnails counted', report['thumbs'] >= 9, str(report))
    check('total = objects + copies + thumbs',
          report['total'] == report['objects'] + report['libraryCopies'] + report['thumbs'])

    # Simulate a volume where hard links are impossible: no copyfile fallback.
    with mock.patch('os.link', side_effect=OSError('cross-device link')):
        other, _, _ = store.materialize('v1', tmp / 'library' / 'other')
    skipped_target = other / relative
    check('failed link does not copy the blob', not skipped_target.exists(), str(skipped_target))
    check('skipped entries are reported', store.last_materialize['skipped'] == 1,
          str(store.last_materialize))
    tree = (other / '.tree.json').read_text('utf8')
    check('skipped entry omitted from .tree.json', relative not in tree, tree[:120])

    store.gc()
    check('gc removes orphan thumbnails', not (thumb_dir / 'deadbeef.png').exists())
    check('gc keeps referenced thumbnails', (thumb_dir / f'{digest}.png').exists())
    check('gc did not delete the blob', store.blob_path(digest, '.png').is_file())

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    print('\nALL PASS' if not failures else f'\n{len(failures)} FAILED: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
