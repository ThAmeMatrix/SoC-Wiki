"""Convert the game's restricted TMP markup into safe offline Wiki HTML."""
from html import escape
import re
from .model import plain

COLORS={'red':('#ff0000','red'),'purple':('#d68fe2','purple'),'green':('#58cb48','green'),
        'blue':('#54b4db','blue'),'brown':('#a0522d','brown'),'C4':('#f3c156','gold'),'C5':('#f3c156','gold')}
TOKEN=re.compile(r'\[[^\[\]]+\]|<[^>]+>|\n')

def render(text,links=None):
    links=links or {};result=[];pos=0;stack=[]
    for match in TOKEN.finditer(text or ''):
        result.append(escape(text[pos:match.start()]));token=match[0];pos=match.end()
        if token.startswith('['):
            label=token[1:-1];target=links.get(plain(label));body='['+render(label)+']'
            result.append(f'<a class="term-link" href="#/page/{int(target)}">{body}</a>' if target else body)
        elif token=='\n':result.append('<br>')
        elif token.startswith('<sprite'):
            converted=plain(token)
            result.append(escape(converted if '<' not in converted else '〔图标〕'))
        elif token.startswith('<style='):
            color,group=COLORS.get(token[7:-1].strip('"'),('#f3c156','gold'))
            result.append(f'<span class="wiki-color-{group}" data-source-color="{color}">');stack.append('span')
        elif token in ('<b>','<i>'):
            tag='strong' if token=='<b>' else 'em';result.append('<'+tag+'>');stack.append(tag)
        elif token in ('</style>','</b>','</i>'):
            if stack:result.append('</'+stack.pop()+'>')
        else:
            # Unknown markup is escaped rather than interpreted as HTML.
            result.append(escape(token))
    result.append(escape((text or '')[pos:]));result.extend('</'+tag+'>' for tag in reversed(stack))
    return ''.join(result)
