"""Conservatively merge five archived star descriptions for infographic display.

Numbers align only within matching effects. Textual replacements stay explicit;
missing archive records are never interpreted as a zero-valued game effect.
"""
import collections
from dataclasses import dataclass
from difflib import SequenceMatcher
from html import escape
import re
from bs4 import BeautifulSoup, NavigableString, Tag

# Star progressions never hinge on punctuation; it follows the highest star.
PUNCTUATION=set('。，、；：！？…～·—()《》〈〉「」『』【】〖〗')

NUMBER=re.compile(r'\d+(?:\.\d+)?[%％]?')
TOKEN=re.compile(r'\d+(?:\.\d+)?[%％]?|[A-Za-z]+|[^\s]')

@dataclass(frozen=True)
class Token:
    text:str
    color:str=''
    @property
    def numeric(self):return NUMBER.fullmatch(self.text) is not None
    @property
    def key(self):return '#' if self.numeric else '。' if self.text in '。；;' else self.text

def tokenize(html):
    soup=BeautifulSoup(html or '', 'html.parser');chars=[];colors=[]
    def visit(node,color=''):
        if isinstance(node,NavigableString):
            for char in str(node):
                if not char.isspace():chars.append(char);colors.append(color)
        elif isinstance(node,Tag):
            classes=node.get('class',[])
            color=next((c.removeprefix('wiki-color-') for c in classes if c.startswith('wiki-color-')),color)
            if node.name=='br':chars.append('\n');colors.append('');return
            for child in node.children:visit(child,color)
    for child in soup.children:visit(child)
    text=''.join(chars)
    return [Token(m[0],colors[m.start()]) for m in TOKEN.finditer(text)]

def normalize(tokens):
    """Expand shared stack counts into their equivalent per-status clauses."""
    text=''.join(t.text for t in tokens)
    pattern=r'\[([^\[\]]+)\]、\[([^\[\]]+)\]层数补充至(\d+)层'
    for match in list(re.finditer(pattern,text))[::-1]:
        a,b=match.group(1),match.group(2)
        def colored(value):
            start=text.find('['+value+']',match.start());pos=0
            for t in tokens:
                if pos>=start+1:return t.color
                pos+=len(t.text)
            return 'gold'
        fragment='['+a+']层数补充至'+match.group(3)+'层、['+b+']层数补充至'+match.group(3)+'层'
        before=token_text_slice(tokens,0,match.start());after=token_text_slice(tokens,match.end(),len(text))
        middle=[Token(m[0], 'orange' if NUMBER.fullmatch(m[0]) else colored(a) if m[0] in a else colored(b) if m[0] in b else '') for m in TOKEN.finditer(fragment)]
        tokens=before+middle+after;text=''.join(t.text for t in tokens)
    # The singular stack recipient in older prose is implicit in the duration.
    if '[剧毒]层数补充至' in text and '[感染]' not in text and '，持续' in text:
        pos=text.index('，持续')+1
        tokens=token_text_slice(tokens,0,pos)+[Token('['),Token('剧','gold'),Token('毒','gold'),Token(']')]+token_text_slice(tokens,pos,len(text))
    return tokens

def token_text_slice(tokens,start,end):
    result=[];cursor=0
    for token in tokens:
        lo,hi=max(start,cursor),min(end,cursor+len(token.text))
        if lo<hi:result.append(Token(token.text[lo-cursor:hi-cursor],token.color))
        cursor+=len(token.text)
    return result

def sentences(tokens):
    rows=[];row=[];depth=0
    for t in tokens:
        if t.text in '✦★' and depth==0:
            if row:rows.append(row);row=[]
            continue
        row.append(t)
        if t.text=='[':depth+=1
        if t.text==']':depth=max(0,depth-1)
        if t.text in '。！？；;' and depth==0:rows.append(row);row=[]
    if row:rows.append(row)
    return rows

def keys(tokens):return [t.key for t in tokens]
def similarity(a,b):return SequenceMatcher(None,keys(a),keys(b),autojunk=False).ratio()

def align_rows(groups,incoming,star):
    """Order-preserving sequence alignment, with a gap preferred to weak matches."""
    n,m=len(groups),len(incoming);score=[[0]*(m+1) for _ in range(n+1)];move={}
    for i in range(1,n+1):score[i][0]=-i*.44;move[i,0]='delete'
    for j in range(1,m+1):score[0][j]=-j*.44;move[0,j]='insert'
    for i in range(1,n+1):
        ref=next(v for v in reversed(groups[i-1]) if v)
        for j in range(1,m+1):
            sim=similarity(ref,incoming[j-1]);pair=score[i-1][j-1]+(sim if sim>=.6 else -2)
            choices=[(pair,'pair'),(score[i-1][j]-.44,'delete'),(score[i][j-1]-.44,'insert')]
            score[i][j],move[i,j]=max(choices,key=lambda p:p[0])
    result=[];i,j=n,m
    while i or j:
        action=move[i,j]
        if action=='pair':row=list(groups[i-1]);row[star]=incoming[j-1];result.append(row);i-=1;j-=1
        elif action=='delete':result.append(groups[i-1]);i-=1
        else:row=[None]*5;row[star]=incoming[j-1];result.append(row);j-=1
    return result[::-1]

def render(tokens):
    result=[];last=None;buffer=''
    for token in tokens:
        if token.color!=last:
            if buffer:result.append(span(buffer,last))
            buffer='';last=token.color
        buffer+=token.text
    if buffer:result.append(span(buffer,last))
    return ''.join(result)
def span(text,color):
    safe=escape(text)
    return f'<span class="wiki-color-{color}">{safe}</span>' if color else safe

def merge_group(group,available):
    present=[i for i,v in enumerate(group) if v]
    base=present[-1];grid=[[None]*5 for _ in group[base]]
    for col,t in zip(grid,group[base]):col[base]=t
    for star in reversed(present[:-1]):
        current=group[star];ref=[next(v for v in reversed(c) if v) for c in grid];merged=[]
        for tag,a,b,c,d in SequenceMatcher(None,keys(ref),keys(current),autojunk=False).get_opcodes():
            if tag=='replace':
                # The wording itself changed. Each side becomes one reading of the
                # same column, so 自身范围3格内 is compared whole with 场上所有
                # instead of character by character.
                left,right=grid[a:b],current[c:d]
                column=[None]*5
                for i in range(5):
                    parts=[source[i] for source in left if source[i] is not None]
                    if parts:column[i]=Token(''.join(t.text for t in parts),parts[0].color)
                if right:column[star]=Token(''.join(t.text for t in right),right[0].color)
                merged.append(column)
                continue
            if tag=='equal':
                for col,t in zip(grid[a:b],current[c:d]):new=list(col);new[star]=t;merged.append(new)
            elif tag=='delete':merged.extend(grid[a:b])
            elif tag=='insert':
                for t in current[c:d]:new=[None]*5;new[star]=t;merged.append(new)
        grid=merged
    # Added prose must include a quantity to express absence as zero. A pure
    # textual unlock instead gets an explicit five-star variant, below.
    segments=[];segment=[];mask=None
    for col in grid:
        current_mask=tuple(i for i in present if col[i] is not None)
        if current_mask!=mask:
            if segment:segments.append((mask,segment))
            segment=[];mask=current_mask
        segment.append(col)
    if segment:segments.append((mask,segment))
    for mask,segment in segments:
        if len(mask)!=len(present):
            ref=[next(v for v in reversed(c) if v) for c in segment]
            if any(re.search(r'[\w\u4e00-\u9fff]',t.text) for t in ref) and not any(t.numeric for t in ref):return None
    if len(present)<sum(available) and not any(t.numeric for t in group[base]):return None
    if not all(available):
        # A missing star keeps the plain five-position reading; numbers still
        # carry 未收录 instead of a zero.
        output=[]
        for column in grid:
            reference=next((v for v in reversed(column) if v),None)
            if reference is None:continue
            if reference.numeric:
                values=[(token.text if token else '0') if available[i] else '未收录' for i,token in enumerate(column)]
                changed=len(set(values))>1
                output.append(Token('/'.join(values) if changed else reference.text,'red' if changed else reference.color))
            else:output.append(reference)
        return render(output)

    def readings(column):
        reference=next((v for v in reversed(column) if v),None)
        absent='0' if reference and reference.numeric else ''
        return [((token.text if token else absent) if available[i] else '未收录') for i,token in enumerate(column)]
    def varies(column):
        reference=next((v for v in reversed(column) if v),None)
        if reference is None:return False
        # Punctuation follows the highest recorded star instead of being listed
        # five times; it never carries the star's meaning.
        if reference.text and all(ch in PUNCTUATION for ch in reference.text):return False
        if reference.numeric:return True
        # Only wording every recorded star states differently is a variant; a
        # passage some stars merely lack keeps its own text, with the quantity
        # beside it carrying the zeroes.
        return len(set(readings(column)))>1 and all(column[i] is not None for i in range(5) if available[i])
    output=[];index=0
    while index<len(grid):
        column=grid[index];reference=next((v for v in reversed(column) if v),None)
        if reference is None or not varies(column):
            if reference:output.append(reference)
            index+=1;continue
        end=index
        while end<len(grid) and varies(grid[end]):end+=1

        # A changed passage is listed once per star, not as five whole sentences.
        # A zero only replaces a quantity that is itself the progression; inside a
        # reworded passage the missing word is simply absent.
        run=grid[index:end]
        reworded=any(not next((v for v in reversed(column) if v),None).numeric for column in run)
        per_star=[]
        for star in range(5):
            parts=[]
            for column in run:
                token=column[star]
                if token:parts.append(token.text)
                elif not reworded and next((v for v in reversed(column) if v),None).numeric:parts.append('0')
            per_star.append(''.join(parts))
        if len(set(per_star))==1:output.append(Token(per_star[0],reference.color))
        else:output.append(Token('/'.join(per_star),'red'))
        index=end
    return render(output)

def combine_stars(htmls):
    docs=[sentences(normalize(tokenize(html))) for html in htmls];available=[bool(d) for d in docs]
    if not any(available):return {'html':'当前离线资料未收录星级效果。','available':available,'fallbacks':0}
    groups=[]
    for i in range(4,-1,-1):
        if docs[i]:groups=align_rows(groups,docs[i],i)
    result=[];fallbacks=0
    for group in groups:
        merged=merge_group(group,available)
        if merged is None:
            fallbacks+=1
            # All five positions remain visible, including repeated and absent
            # values; no mechanism is guessed from prose differences.
            parts=[render(tokens) if tokens else span('0' if available[i] else '未收录','red') for i,tokens in enumerate(group)]
            merged='效果（1→5星）：'+' / '.join(parts)
        result.append('<div>✦'+merged+'</div>')
    if not all(available):result.append('<div>星级资料未收录：'+ '/'.join(str(i+1)+'星' for i,ok in enumerate(available) if not ok)+'</div>')
    return {'html':''.join(result),'available':available,'fallbacks':fallbacks}
