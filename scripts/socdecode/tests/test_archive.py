"""Archive: categories, diffs, storage and an end-to-end versioned scan."""
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from socdecode.archive import diff  # noqa: E402
from socdecode.archive.catalog import classify_loose, excluded, group_of, safe_name  # noqa: E402
from socdecode.archive.extract import EXTERNAL_TEXTURE, canonical, json_bytes  # noqa: E402
from socdecode.archive.scan import scan  # noqa: E402
from socdecode.archive.store import Store  # noqa: E402


def entry(path, digest, cat='image', group='icon/card', ext='.png', size=10):
    return [path, cat, group, digest, size, ext, 'assets/x.unity3d', None]


class Catalog(unittest.TestCase):
    def test_private_files_are_never_read(self):
        for rel in ('account3', 'GameInstallationRecord.db', '.GameInstallationRecord.dat', 'assets/player_prefs.ini',
                    'assets/Report/1080003902_29090.bytes', 'assets/Report/x/y.bytes'):
            self.assertTrue(excluded(rel), rel)
        for rel in ('assets/icon/card/a.unity3d', 'assets/audio/Media/1.wem', 'assets/ReportCard.unity3d'):
            self.assertFalse(excluded(rel), rel)

    def test_groups_and_categories(self):
        self.assertEqual(group_of('assets/icon/card/icon_card12.unity3d'), 'icon/card')
        self.assertEqual(group_of('assets/shared.unity3d'), '(根目录)')
        self.assertEqual(group_of('SoC_Data/Plugins/x86_64/slua.dll'), 'SoC_Data')
        self.assertEqual(classify_loose('assets/audio/Media/1.wem'), ('audio', '.wem'))
        self.assertEqual(classify_loose('assets/movie/a.mp4'), ('video', '.mp4'))
        self.assertEqual(classify_loose('GameAssembly.dll'), ('program', '.dll'))
        self.assertEqual(classify_loose('assets/file_hash.txt'), ('text', '.txt'))

    def test_names_survive_windows_folders(self):
        self.assertEqual(safe_name('a/b:c*?', 'x'), 'a_b_c__')
        self.assertEqual(safe_name('CON', 'x'), '_CON')
        self.assertEqual(safe_name(' . ', 'fallback'), 'fallback')


class Canonical(unittest.TestCase):
    def test_stable_order_numbers_before_text(self):
        value = {'b': 1, 10: 'x', 2: 'y', 'a': {3: 1, 1: 2}}
        self.assertEqual(list(canonical(value)), ['2', '10', 'a', 'b'])
        self.assertEqual(json_bytes(value), json_bytes(dict(reversed(list(value.items())))))

    def test_odd_values_are_json(self):
        self.assertEqual(canonical({'n': float('nan'), 'b': b'\x01\xff'}), {'b': '01ff', 'n': 'nan'})

    def test_only_unitypy_cross_bundle_errors_count_as_sprite_references(self):
        # A missing decoder data file must surface as an error, not as "texture in another bundle".
        self.assertTrue(EXTERNAL_TEXTURE.match('File cab-5a6e56723ba448baf1e166be8e3fd8a2 not found in C:\\Game\\assets'))
        self.assertFalse(EXTERNAL_TEXTURE.match("[Errno 2] No such file or directory: 'x\\archspec\\json\\cpu\\microarchitectures.json'"))
        self.assertFalse(EXTERNAL_TEXTURE.match("Could not find module 'fmod.dll' (or one of its dependencies)"))


class Compare(unittest.TestCase):
    def test_added_removed_modified_renamed(self):
        old = [entry('image/a.png', '1' * 32), entry('image/b.png', '2' * 32), entry('image/c.png', '3' * 32)]
        new = [entry('image/a.png', '1' * 32), entry('image/b.png', '9' * 32), entry('image/d.png', '3' * 32),
               entry('image/e.png', '4' * 32)]
        kinds = {(k, (n or o)[0]) for k, o, n in diff.compare(old, new)}
        self.assertEqual(kinds, {('modified', 'image/b.png'), ('renamed', 'image/d.png'), ('added', 'image/e.png')})
        summary = diff.summarize(diff.compare(old, new))
        self.assertEqual(summary['total'], {'added': 1, 'removed': 0, 'modified': 1, 'renamed': 1})

    def test_only_shared_categories_are_compared(self):
        old = [entry('image/a.png', '1' * 32)]
        new = [entry('image/a.png', '1' * 32), entry('audio/x.wem', '5' * 32, cat='audio', ext='.wem')]
        self.assertEqual(diff.compare(old, new, {'image'}), [])

    def test_table_rows_and_fields(self):
        before = [{'id': 1, 'name': '甲', 'hp': 10}, {'id': 2, 'name': '乙', 'hp': 20}, {'id': 3, 'name': '丙', 'hp': 30}]
        after = [{'id': 1, 'name': '甲', 'hp': 12, 'new': 1}, {'id': 3, 'name': '丙', 'hp': 30}, {'id': 4, 'name': '丁', 'hp': 40}]
        result = diff.table_diff(before, after)
        self.assertEqual(result['key'], 'id')
        self.assertEqual(result['counts'], {'rowsBefore': 3, 'rowsAfter': 3, 'added': 1, 'removed': 1, 'changed': 1})
        self.assertEqual(result['changed'][0]['fields'], [['hp', 10, 12], ['new', None, 1]])
        self.assertEqual(result['addedColumns'], ['new'])

    def test_text_hunks(self):
        left = '\n'.join(f'line {i}' for i in range(30))
        right = left.replace('line 5', 'line five').replace('line 20\n', '')
        result = diff.text_diff(left, right)
        self.assertEqual((result['added'], result['removed']), (1, 2))
        self.assertEqual(len(result['hunks']), 2)
        self.assertIn({'t': 'r', 'a': 6, 'b': 6, 'l': 'line 5', 'r': 'line five'}, result['hunks'][0]['rows'])


class Archive(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix='soc-archive-'))
        self.game, self.root = self.folder / 'game', self.folder / 'archive'
        for rel, data in {'assets/lua/lua_db.unity3d': b'stub', 'SoC_Data/Plugins/x86_64/slua.dll': b'stub',
                          'assets/file_hash.txt': 'a|1\nb|2\nc|3\n'.encode(), 'assets/audio/Media/1.wem': b'\x01' * 50,
                          'assets/audio/Media/2.wem': b'\x02' * 70, 'assets/PB/Packets.proto': b'\xc7\x00\x01binary',
                          'assets/Report/9_1.bytes': b'never', 'account3': b'never'}.items():
            path = self.game / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def tearDown(self):
        os.system(f'attrib -R "{self.folder}\\*" /S /D >nul 2>&1') if os.name == 'nt' else None
        shutil.rmtree(self.folder, ignore_errors=True)

    def run_scan(self):
        return scan(self.game, self.root, workers=2, categories=['text', 'data', 'audio'], organise=True)

    def test_versions_diffs_reuse_and_cleanup(self):
        first = self.run_scan()
        self.assertEqual(first['status'], 'created')
        store = Store(self.root)
        paths = {e[0]: e for e in store.manifest(first['version'])}
        self.assertEqual(set(paths), {'text/file_hash.txt', 'audio/audio/Media/1.wem', 'audio/audio/Media/2.wem',
                                      'data/PB/Packets.proto'})  # encrypted proto is data, private files absent
        self.assertTrue(store.blob_path(paths['text/file_hash.txt'][3], '.txt').is_file())
        library = store.library / '当前版本'
        self.assertEqual((library / '文本' / 'file_hash.txt').read_bytes(), b'a|1\nb|2\nc|3\n')

        again = self.run_scan()
        self.assertEqual(again['status'], 'unchanged')
        # Nothing is parsed again: four loose files and the loader bundle all come from the last version.
        self.assertEqual((again['stats']['processed'], again['stats']['reused']), (0, 5))

        time.sleep(.05)
        (self.game / 'assets/file_hash.txt').write_text('a|1\nb|9\nc|3\n', encoding='utf8')
        (self.game / 'assets/audio/Media/2.wem').rename(self.game / 'assets/audio/Media/2b.wem')
        (self.game / 'assets/audio/Media/1.wem').unlink()
        second = self.run_scan()
        self.assertEqual(second['status'], 'created')
        self.assertEqual(second['meta']['parent'], first['version'])
        self.assertEqual(second['meta']['changes'], {'added': 0, 'removed': 1, 'modified': 1, 'renamed': 1, 'total': 3})
        self.assertEqual(store.changes(second['version'])['sources']['counts'], {'added': 1, 'removed': 2, 'modified': 1})
        self.assertIn('修改 `text/file_hash.txt`', (store.versions_dir / second['version'] / 'report.md').read_text('utf8'))
        self.assertEqual((library / '文本' / 'file_hash.txt').read_text('utf8'), 'a|1\nb|9\nc|3\n')
        self.assertFalse((library / '音频' / 'audio/Media/1.wem').exists())

        # Any two versions compare, and deleting one then collecting frees its own files only.
        old_text = paths['text/file_hash.txt']
        store.delete_version(second['version'])
        self.assertEqual([v['id'] for v in store.index()], [first['version']])
        removed, _ = store.gc()
        self.assertGreaterEqual(removed, 1)
        self.assertTrue(store.blob_path(old_text[3], '.txt').is_file())


if __name__ == '__main__':
    unittest.main()
