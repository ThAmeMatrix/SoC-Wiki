"""Semantic regressions for separating common effects without losing original text."""
from collections import Counter
from bs4 import BeautifulSoup
from character_data import star_comparison, effect_document, sentences, normalized, catalog_order, character_images


def plain(source):
    return BeautifulSoup(source, 'html.parser').get_text()


def test():
    descriptions = {
        '个性描述1': '攻击提高<font data-source-color="red">5%</font>。<br>获得<a href="#/page/42">[扬旗]</a>。',
        '个性描述2': '攻击提高<font data-source-color="red">10%</font>。<br>获得<a href="#/page/42">[扬旗]</a>。',
        '个性描述3': '攻击提高<font data-source-color="red">10%</font>。额外移动2格。<br>获得<a href="#/page/42">[扬旗]</a>。',
        '个性描述4': '攻击提高<font data-source-color="red">20%</font>。额外移动2格。<br>获得<a href="#/page/42">[扬旗]</a>。',
        '个性描述5': '攻击提高<font data-source-color="red">20%</font>。<br>获得<a href="#/page/42">[扬旗]</a>。',
    }
    result = star_comparison(descriptions)
    assert plain(result['common']) == '获得[扬旗]。'
    assert '#/page/42' in result['common']
    assert '额外移动2格' in result['levels'][4]['removed']
    assert [m.get_text() for m in BeautifulSoup(result['levels'][1]['html'], 'html.parser').select('mark')]==['10%']
    assert BeautifulSoup(result['levels'][1]['html'], 'html.parser').select_one('font[data-source-color] mark')
    for n, level in enumerate(result['levels'], 1):
        original = Counter(x[2] for x in sentences(effect_document(descriptions['个性描述'+str(n)])[1]))
        combined = Counter(x[2] for x in sentences(plain(result['common']) + plain(level['html'])))
        assert original == combined, (n, original, combined)
    print('PASS common sentences and per-star text reconstruct the source; links/colors and full numeric changes survive')
    same = star_comparison({'个性描述'+str(n): '免疫[灼烧]。免疫[灼烧]。' for n in range(1,6)})
    assert plain(same['common'])=='免疫[灼烧]。免疫[灼烧]。'
    assert all(not x['html'] and not x['changed'] for x in same['levels'])
    partial = star_comparison({'个性描述1': '回复5点。', '个性描述5': '回复10点。'})
    assert not partial['common'] and [x['available'] for x in partial['levels']]==[True,False,False,False,True]
    assert partial['levels'][4]['previous']==1
    assert star_comparison({'技能描述': '效果'}) is None
    print('PASS identical, repeated and missing star descriptions are handled without invented effects')
    order = catalog_order('<a title="角色图鉴库/B"></a><a title="角色图鉴库/A"></a><a title="角色图鉴库/B"></a>', {'角色图鉴库/A':1,'角色图鉴库/B':2})
    assert order=={'角色图鉴库/B':0,'角色图鉴库/A':1}
    images = {'立绘_角色':'base.webp','立绘_角色（五星）':'five.webp','立绘_角色（夏日）':'summer.webp','像素人物_角色':'sprite.webp'}
    meta=character_images('角色','角色（五星），角色（夏日），不存在',lambda n:images.get(n,''))
    assert [x['src'] for x in meta['portraits']]==['base.webp','five.webp','summer.webp']
    assert meta['sprite']=='sprite.webp'
    assert character_images('未收录','',lambda n:'')=={'sprite':'','portraits':[]}
    print('PASS catalog order follows original links; artwork has no duplicates or fabricated missing variants')

if __name__=='__main__':test()
