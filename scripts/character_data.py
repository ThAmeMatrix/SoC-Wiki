"""Preserve source catalog order, artwork variants and exact star-effect comparisons."""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
from difflib import SequenceMatcher
import re
from bs4 import BeautifulSoup, NavigableString, Tag


def catalog_order(source: str, titles: dict) -> dict:
    soup = BeautifulSoup(source, 'html.parser')
    result = {}
    for link in soup.select('a[title]'):
        title = link['title']
        if title.startswith('角色图鉴库/') and title in titles and title not in result:
            result[title] = len(result)
    return result


def character_images(name: str, skins: str, named_image) -> dict:
    portraits = []
    base = named_image('立绘_' + name)
    if base:
        portraits.append({'key': 'base', 'label': '初始立绘', 'src': base})
    awakened = named_image('立绘_' + name + '（五星）')
    if awakened:
        portraits.append({'key': 'awakened', 'label': '觉醒立绘', 'src': awakened})
    for skin in re.split(r'[，,、]', skins):
        skin = skin.strip()
        path = named_image('立绘_' + skin) if skin else ''
        if path and not any(x['src'] == path for x in portraits):
            label = skin.removeprefix(name).strip('（）() ') or skin
            portraits.append({'key': 'skin-' + str(len(portraits)), 'label': label, 'src': path})
    return {'sprite': named_image('像素人物_' + name), 'portraits': portraits}


def effect_document(source: str):
    soup = BeautifulSoup(source, 'html.parser')
    for br in soup.find_all('br'):
        br.replace_with(NavigableString('\n'))
    for block in soup.find_all(['p', 'div', 'li']):
        block.append(NavigableString('\n'))
    return soup, soup.get_text()


def normalized(text: str) -> str:
    return re.sub(r'\s+', '', text)


def sentences(text: str):
    start = 0
    for match in re.finditer(r'[。！？；;]|[\r\n]+', text):
        end = match.end()
        if normalized(text[start:end]):
            yield start, end, normalized(text[start:end])
        start = end
    if normalized(text[start:]):
        yield start, len(text), normalized(text[start:])


def tokens(text: str):
    return list(re.finditer(r'\d+(?:\.\d+)?[%％]?|[a-zA-Z]+|[^\s]', text))


def differences(previous: str, current: str):
    before, after = tokens(previous), tokens(current)
    changes, deletions, old_changes = [], [], []
    matcher = SequenceMatcher(None, [m[0] for m in before], [m[0] for m in after], autojunk=False)
    for tag, a, b, c, d in matcher.get_opcodes():
        if tag == 'equal':
            continue
        if c < d:
            changes.append((after[c].start(), after[d - 1].end()))
        if a < b:
            old_changes.append((before[a].start(), before[b - 1].end()))
        if tag == 'delete':
            removed = previous[before[a].start():before[b - 1].end()].strip('。！？；;，, \r\n')
            if re.search(r'[\w\u4e00-\u9fff]', removed):
                deletions.append(removed)
    return changes, deletions, old_changes


def html_slice(soup, start: int, end: int, changes=()) -> str:
    """Slice visible text while cloning its links and original semantic color spans."""
    output = BeautifulSoup('', 'html.parser')
    cursor = 0

    def clone(node):
        nonlocal cursor
        if isinstance(node, NavigableString):
            value = str(node)
            lo, hi = cursor, cursor + len(value)
            cursor = hi
            a, b = max(start, lo), min(end, hi)
            if a >= b:
                return []
            points = {a, b}
            for x, y in changes:
                if x < b and y > a:
                    points.update((max(a, x), min(b, y)))
            points = sorted(points)
            result = []
            for x, y in zip(points, points[1:]):
                piece = NavigableString(value[x-lo:y-lo])
                if any(c <= x and y <= d for c, d in changes):
                    mark = output.new_tag('mark', attrs={'class': 'star-change'})
                    mark.append(piece)
                    result.append(mark)
                else:
                    result.append(piece)
            return result
        if not isinstance(node, Tag):
            return []
        children = [new for child in node.children for new in clone(child)]
        if not children:
            return []
        tag = output.new_tag(node.name, attrs=deepcopy(node.attrs))
        for child in children:
            tag.append(child)
        return [tag]

    for node in soup.contents:
        for child in clone(node):
            output.append(child)
    return str(output).strip()


def star_comparison(fields: dict):
    prefix = next((p for p in ('个性描述', '天赋描述', '特性描述') if any(fields.get(p + str(n)) for n in range(1, 6))), None)
    if not prefix:
        return None
    documents = [effect_document(fields.get(prefix + str(n), '')) for n in range(1, 6)]
    groups = [list(sentences(text)) for _, text in documents]
    common_counts = Counter(k for _, _, k in groups[0])
    for group in groups[1:]:
        common_counts &= Counter(k for _, _, k in group)
    common_html, common_left = [], common_counts.copy()
    for a, b, key in groups[0]:
        if common_left[key]:
            common_left[key] -= 1
            common_html.append(html_slice(documents[0][0], a, b))
    levels = []
    previous = None
    for i, (soup, text) in enumerate(documents):
        if not normalized(text):
            levels.append({'star': i + 1, 'available': False, 'html': '', 'removed': [], 'previous': None, 'changed': False})
            continue
        changed, removed, old = differences(documents[previous][1], text) if previous is not None else ([], [], [])
        if previous is None:
            for _, later in documents[i+1:]:
                if normalized(later):
                    changed.extend(differences(text, later)[2])
        remaining, left = [], common_counts.copy()
        for a, b, key in groups[i]:
            if left[key]:
                left[key] -= 1
            else:
                remaining.append(html_slice(soup, a, b, changed))
        levels.append({'star': i + 1, 'available': True,
                       'html': ''.join('<div class="star-paragraph">' + value + '</div>' for value in remaining),
                       'removed': removed, 'previous': previous + 1 if previous is not None else None,
                       'changed': previous is not None and normalized(documents[previous][1]) != normalized(text)})
        previous = i
    return {'prefix': prefix, 'common': ''.join('<div class="star-paragraph">' + value + '</div>' for value in common_html), 'levels': levels}
