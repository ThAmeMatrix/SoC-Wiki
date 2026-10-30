import tempfile
from pathlib import Path
from unittest import TestCase,main,mock

from socdecode.client import decode_outer,OUTER_KEY
from socdecode.model import attributes,plain
from socdecode.richtext import render
from socdecode.transaction import apply,rollback,sha,within

class DecodeTests(TestCase):
    def test_header_checked(self):
        header=bytes.fromhex('01584643810513e40018480b')
        encoded=bytes(v^OUTER_KEY[i%17] for i,v in enumerate(header))
        self.assertEqual(decode_outer(encoded),header)
        with self.assertRaises(ValueError):decode_outer(b'unknown game format')

class ContentTests(TestCase):
    def test_sprites_preserve_buff_direction_and_prohibition(self):
        self.assertEqual(plain('<sprite=1>被动技'), '×被动技')
        self.assertEqual(plain('<sprite=2>攻击2'), '▲攻击2')
        self.assertEqual(plain('<sprite=3>魔防3'), '▼魔防3')

    def test_html_escape_and_link_scope(self):
        result=render('[<style=C5>神识</style>]提高<style=red>25%</style>。<script>alert(1)</script>',{'神识':42})
        self.assertIn('href="#/page/42"',result)
        self.assertIn('wiki-color-red',result)
        self.assertNotIn('<script>',result)
        self.assertIn('&lt;script&gt;',result)

    def test_confirmed_gloria_stat_formula_and_rounding(self):
        values={'hp':1741,'physic_attack':694,'spell_attack':486,'physic_defence':245,'spell_defence':199}
        rank={'hp_add':1143,'physic_attack_add':425,'spell_attack_add':300,'physic_defence_add':151,'spell_defence_add':123}
        star={'permillage_'+k:120 for k in values};lines=[dict(star)]
        self.assertEqual(attributes(values,{'base_attribute_adjust':115},star,[rank],lines),
            {'生命':3625,'物攻':1414,'魔攻':993,'物防':500,'魔防':406})
        self.assertEqual(attributes({k:177 for k in values},{'base_attribute_adjust':115},
            {'permillage_'+k:0 for k in values},[],[])['物攻'],203)

class TransactionTests(TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'wiki';self.root.mkdir();self.backups=Path(self.temp.name)/'backups'
        (self.root/'existing.js').write_bytes(b'original')

    def test_apply_noop_and_rollback(self):
        files={'existing.js':b'updated','data/new.js':b'new'}
        backup=apply(self.root,files,{'existing.js':sha(b'original'),'data/new.js':None},self.backups)
        self.assertIsNone(apply(self.root,files,{k:sha(v) for k,v in files.items()},self.backups))
        self.assertEqual(rollback(backup),2)
        self.assertEqual((self.root/'existing.js').read_bytes(),b'original')
        self.assertFalse((self.root/'data/new.js').exists())

    def test_rollback_preserves_later_work(self):
        backup=apply(self.root,{'existing.js':b'updated'},{'existing.js':sha(b'original')},self.backups)
        (self.root/'existing.js').write_bytes(b'new user work')
        with self.assertRaises(RuntimeError):rollback(backup)
        self.assertEqual((self.root/'existing.js').read_bytes(),b'new user work')

    def test_reject_concurrent_edit_before_any_write(self):
        with self.assertRaises(RuntimeError):
            apply(self.root,{'data/new.js':b'new','existing.js':b'updated'},
                {'data/new.js':None,'existing.js':sha(b'old version')},self.backups)
        self.assertFalse((self.root/'data/new.js').exists())

    def test_partial_failure_restores_written_files(self):
        from socdecode import transaction
        original=transaction.atomic
        def failing(path,data):
            if path==self.root/'failed.js':raise OSError('simulated disk failure')
            return original(path,data)
        with mock.patch.object(transaction,'atomic',side_effect=failing):
            with self.assertRaises(OSError):
                apply(self.root,{'existing.js':b'updated','failed.js':b'new'},
                    {'existing.js':sha(b'original'),'failed.js':None},self.backups)
        self.assertEqual((self.root/'existing.js').read_bytes(),b'original')

    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError):within(self.root,'../outside')

if __name__=='__main__':main()
