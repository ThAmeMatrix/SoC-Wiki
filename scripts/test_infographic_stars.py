"""Verify complete five-star vectors and conservative treatment of prose changes."""
from pathlib import Path
import json,unittest
from bs4 import BeautifulSoup
from infographic_stars import combine_stars

ROOT=Path(__file__).resolve().parents[1]
def load(relative):
    raw=(ROOT/relative).read_text(encoding='utf8');return json.JSONDecoder().raw_decode(raw[raw.index('=')+1:])[0]
def text(result):return BeautifulSoup(result['html'],'html.parser').get_text()
def fields(id):return load(f'data/pages/{id}.js')['fields']
def trait(id):return combine_stars([fields(id).get('个性描述'+str(n),'') for n in range(1,6)])

class StarEffects(unittest.TestCase):
    def test_reference_character(self):
        result=trait(9334);s=text(result)
        for expected in ['5%/10%/10%/15%/20%','10%/20%/20%/30%/30%','10/20/30/40/50','0/0/0/0/15%','[剧毒]层数补充至1/1/1/2/2层','[感染]层数补充至0/1/1/1/2层','持续回合减0/0/1/1/1','冷却回合减0/0/1/1/1']:
            self.assertIn(expected,s)
        self.assertEqual(result['fallbacks'],0)
        self.assertIn('wiki-color-gold',result['html']);self.assertIn('wiki-color-blue',result['html']);self.assertIn('wiki-color-red',result['html'])
    def test_exclusive_effect_and_buff_levels(self):
        f=fields(9337);result=combine_stars([f[n+'星技能'] for n in '一二三四五']);s=text(result)
        self.assertEqual(s.count('12%/16%/16%/20%/24%'),2)
        self.assertIn('[▼物防1/1/2/2/2]',s);self.assertIn('[▼魔防1/1/2/2/2]',s)
        self.assertIn('持续2回合',s);self.assertNotIn('2/2/2/2/2回合',s)
    def test_later_unlock_within_existing_sentence(self):
        s=text(trait(3367));self.assertIn('移动力额外增加0/0/2/2/2格',s);self.assertIn('无视目标0/0/0/0/50%防御',s)
    def test_identical_effect_not_repeated(self):
        result=combine_stars(['伤害提高10%。']*5);self.assertEqual(text(result),'✦伤害提高10%。')
    def test_unknown_archive_record_is_not_zero(self):
        result=combine_stars(['','伤害提高10%。','伤害提高20%。','伤害提高30%。','伤害提高40%。'])
        self.assertIn('未收录/10%/20%/30%/40%',text(result));self.assertIn('星级资料未收录：1星',text(result))
    def test_non_numeric_mechanism_is_explicit(self):
        result=combine_stars(['对[濒死]敌人生效。']*2+['对[受伤]敌人生效。']*3)
        self.assertEqual(result['fallbacks'],1);self.assertEqual(text(result).count('[濒死]'),2);self.assertEqual(text(result).count('[受伤]'),3)
    def test_pure_unlock_retains_five_positions(self):
        result=combine_stars(['攻击提高5%。']*4+['攻击提高5%。获得[跳跃]。'])
        self.assertIn('0 / 0 / 0 / 0 / 获得[跳跃]',text(result))
    def test_decimal_negative_units_and_repeated_values(self):
        result=combine_stars([f'伤害提高{n}%，冷却减少{c}回合。' for n,c in [('1.5',1),('2.5',1),('2.5',2),('3.5',2),('4.5',3)]])
        self.assertIn('1.5%/2.5%/2.5%/3.5%/4.5%',text(result));self.assertIn('1/1/2/2/3',text(result))
    def test_generated_data_matches_every_source(self):
        data=load('data/infographic.js');index=load('data/index.js');count=0
        for p in index['pages']:
            if not (p['type']=='equipment' or p['title'].startswith('个性/')):continue
            f=fields(p['id']);stars=[f.get(n+'星技能','') for n in '一二三四五'] if p['type']=='equipment' else [f.get('个性描述'+str(n),'') for n in range(1,6)]
            if not any(stars):continue
            self.assertEqual(data['starEffects'][str(p['id'])],combine_stars(stars),p['title']);count+=1
        self.assertEqual(count,335)

if __name__=='__main__':unittest.main(verbosity=2)
