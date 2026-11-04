"""汉字转拼音，供离线 Wiki 做拼音模糊搜索。

pypinyin 是可选依赖：缺失时 spell() 返回空串，构建照常完成，只是搜索不再支持拼音。
"""
from __future__ import annotations
import re

try:
    from pypinyin import lazy_pinyin, Style
    _AVAILABLE = True
except Exception:      # pragma: no cover - optional dependency
    lazy_pinyin = None
    Style = None
    _AVAILABLE = False

_NON_PINYIN = re.compile(r'[^a-z0-9]')


def available() -> bool:
    return _AVAILABLE


def _clean(text: str) -> str:
    return _NON_PINYIN.sub('', str(text).lower())


def spell(text):
    """返回 (全拼, 首字母)；无拼音库或输入为空时返回 ('', '')。"""
    if not _AVAILABLE or not text:
        return '', ''
    full = _clean(''.join(lazy_pinyin(text, style=Style.NORMAL)))
    initials = _clean(''.join(lazy_pinyin(text, style=Style.FIRST_LETTER)))
    return full, initials


def build(pages):
    """为每个页面生成拼音索引：{pid: '全拼…|首字母…'}。"""
    if not _AVAILABLE:
        return {}
    out = {}
    for page in pages:
        text = entry(page.get('name'), *(str(page.get('aliases') or '').split('、')),
                     page.get('title'))
        if text:
            out[str(page['id'])] = text
    return out


def entry(*parts):
    """把名称、别名、标题等拼成一段可检索的拼音串：全拼 与 首字母，用 | 分隔。

    每个来源单独成词（空格分隔），这样以角色名开头的拼音也能前缀命中。
    """
    fulls, initials = [], []
    for part in parts:
        if not part:
            continue
        full, initial = spell(part)
        if full and full not in fulls:
            fulls.append(full)
        if initial and initial not in initials:
            initials.append(initial)
    if not fulls and not initials:
        return ''
    return ' '.join(fulls) + '|' + ' '.join(initials)
