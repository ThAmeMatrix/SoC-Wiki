"""Index battle-sim-core.js so every client mechanism can cite real code lines.

The sentence-level mechanism wiki (scripts/build_sentence_mechanics.py) must
point each sentence of a skill / personality description at the exact engine
code that executes it. Line numbers drift with every edit, so nothing here is
hard-coded: the engine source is parsed on each build and the anchors are
re-derived from stable code shapes:

  EFFECTS handlers        `      BUFF(inst, ctx) {` inside `const EFFECTS = {`
  declarative consumers   `i.spec.t === 'PARRY'`, `t === 'EVADE'` … outside STATIC_TYPES
  timing dispatch         `fire(3, …)`, `fireObject(29, …)`, `runSkillSpecs(s, c, 2, …)`
  attributes              `attr(u, 'PHYSIC_ATTACK')`
  buff effect types       `hasEffect(u, 'Dizzy')`, `def.et === 'TreatReversal'`
  Lua API                 `getBuffCount: (…) =>`, `case 'isCurrentSummoned':`
  JSON sparam keys        `sj?.buff_category`
  skill/spec specifics    comments / literals naming `#15386`, `sid === 22116`

Each anchor carries the line, the enclosing symbol and a short snippet, so the
wiki can show the code without loading the 550 KB engine source.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / 'battle-sim-core.js'
ENGINE_NAME = 'battle-sim-core.js'

RE_FUNC = re.compile(r'^(\s*)(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(')
RE_ARROW = re.compile(r'^(\s*)(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>')
RE_HANDLER = re.compile(r'^(      )([A-Z][A-Z0-9_]+)\s*\((?:inst|\))')
RE_METHOD = re.compile(r'^(\s+)([a-zA-Z_][\w]*)\s*:\s*(?:\([^)]*\)|[a-zA-Z_]\w*)\s*=>')
RE_LUA_ANY = re.compile(r'\b([a-zA-Z_]\w*)\s*:\s*(?:\([^)]*\)\s*=>|[a-zA-Z_]\w*\s*=>|Math\.\w+|function\b)')
# Plain data fields handed to Lua (`temp_limit_count_command: scoped ? …`).
RE_LUA_FIELD = re.compile(r'\b((?:temp|limit|cur)_[a-z_]+)\s*:')
# Stub handlers name their real reader in a trailing comment:
#   `IMMUNE(inst, ctx) { /* read by the immunity checks */ }`
RE_READ_BY = re.compile(r'(?:read by|summed by|enforced by|banked by|handled in|dispatched by|queued after[^:/]*?in|see)\s+([A-Za-z_]\w*)\(\)')
RE_CASE = re.compile(r"case '([a-zA-Z_][\w]*)':")
RE_FIRE = re.compile(r'\b(fire|fireObject)\(\s*(\d+)\s*,')
RE_RUNSPECS = re.compile(r'\brunSkillSpecs\([^,()]+,\s*[^,()]+,\s*(\d+)\s*,')
RE_ATTR = re.compile(r"\battr(?:ById)?\(\s*[\w.?]+\s*,\s*'([A-Z][A-Z0-9_]+)'")
RE_EFFECT = re.compile(r"\b(?:hasEffect\(\s*[\w.?]+\s*,\s*|\.et\s*===\s*|et\s*===\s*)'([A-Z][A-Za-z]+)'")
RE_SJ = re.compile(r'\bsj\??\.([a-z_]+)')
RE_HASHID = re.compile(r'#(\d{3,6})\b')
RE_LITID = re.compile(r'(?:===|==|!==)\s*(\d{4,6})\b|\b(\d{4,6})\s*===')


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(' '))


class EngineIndex:
    def __init__(self, path: Path = ENGINE):
        self.src = path.read_text('utf8').replace('\r\n', '\n')
        self.lines = self.src.split('\n')
        self._defs = []            # (line_no, indent, name)
        self._scan_defs()
        self.handlers: dict[str, int] = {}
        self.handler_end: dict[str, int] = {}
        self.static_types: set[str] = set()
        self.static_line = 0
        self.consumers: dict[str, list[int]] = defaultdict(list)
        self.timings: dict[int, list[int]] = defaultdict(list)
        self.attrs: dict[str, list[int]] = defaultdict(list)
        self.effects: dict[str, list[int]] = defaultdict(list)
        self.lua: dict[str, list[int]] = defaultdict(list)
        self.sj: dict[str, list[int]] = defaultdict(list)
        self.ids: dict[int, list[int]] = defaultdict(list)
        self._scan()

    # ---- definitions ------------------------------------------------------
    def _scan_defs(self):
        in_effects = False
        for no, line in enumerate(self.lines, 1):
            if line.startswith('    const EFFECTS = {'):
                in_effects = True
            elif in_effects and line.startswith('    };'):
                in_effects = False
            mf, ma = RE_FUNC.match(line), RE_ARROW.match(line)
            # Only definitions that OPEN a block are enclosing scopes; a
            # one-liner `const combat = () => !!x;` must not swallow the lines
            # that follow it. Multi-line `function f(a,\n b) {` still counts.
            opens = line.count('{') > line.count('}')
            if (mf and (opens or '{' not in line)) or (ma and opens):
                m = mf or ma
                self._defs.append((no, len(m.group(1)), m.group(2)))
                continue
            if in_effects:
                m = RE_HANDLER.match(line)
                if m:
                    self._defs.append((no, 6, 'EFFECTS.' + m.group(2)))

    def symbol(self, line_no: int) -> str:
        """Nearest enclosing definition: the closest preceding def whose
        indentation is shallower than the anchor line."""
        target = _indent(self.lines[line_no - 1]) if 0 < line_no <= len(self.lines) else 0
        best = ''
        for no, ind, name in reversed(self._defs):
            if no > line_no:
                continue
            if no == line_no or ind < target or (ind == 6 and name.startswith('EFFECTS.') and target >= 6):
                best = name
                break
        return best or '(顶层)'

    def snippet(self, line_no: int, before: int = 1, after: int = 5, width: int = 150) -> str:
        lo, hi = max(1, line_no - before), min(len(self.lines), line_no + after)
        out = []
        for no in range(lo, hi + 1):
            text = self.lines[no - 1].rstrip()
            if len(text) > width:
                text = text[:width] + '…'
            out.append(f'{no:>5}  {text}')
        return '\n'.join(out)

    def comment_before(self, line_no: int, limit: int = 6) -> str:
        """Comment block directly above (or first comment lines inside) a def."""
        out = []
        no = line_no - 1
        while no >= 1 and len(out) < limit:
            s = self.lines[no - 1].strip()
            if s.startswith('//'):
                out.append(s[2:].strip())
                no -= 1
                continue
            if s.startswith('*') or s.startswith('/*'):
                out.append(s.lstrip('/*').strip())
                no -= 1
                continue
            break
        out.reverse()
        if not out:
            no = line_no + 1
            while no <= len(self.lines) and len(out) < limit:
                s = self.lines[no - 1].strip()
                if not s.startswith('//'):
                    break
                out.append(s[2:].strip())
                no += 1
        return ' '.join(x for x in out if x)

    # ---- anchors ----------------------------------------------------------
    def _scan(self):
        lines = self.lines
        eff_start = next(i for i, l in enumerate(lines, 1) if l.startswith('    const EFFECTS = {'))
        eff_end = next(i for i, l in enumerate(lines, 1) if i > eff_start and l.startswith('    };'))
        current = None
        for no in range(eff_start, eff_end + 1):
            m = RE_HANDLER.match(lines[no - 1])
            if m:
                if current:
                    self.handler_end[current] = no - 1
                current = m.group(2)
                self.handlers[current] = no
        if current:
            self.handler_end[current] = eff_end
        self.static_line = next(i for i, l in enumerate(lines, 1) if 'const STATIC_TYPES = new Set(' in l)
        static_end = next(i for i, l in enumerate(lines, 1) if i >= self.static_line and ']);' in l)
        for no in range(self.static_line, static_end + 1):
            self.static_types |= set(re.findall(r"'([A-Z][A-Z0-9_]+)'", lines[no - 1]))
        method_lines = [i for i, l in enumerate(lines, 1) if '__methods' in l]
        lua_lo = (method_lines[0] - 120) if method_lines else 0
        lua_hi = (method_lines[-1] + 260) if method_lines else 0
        handler_lines = set(self.handlers.values())
        for no, line in enumerate(lines, 1):
            stripped = line.lstrip()
            is_comment = stripped.startswith(('//', '/*', '*'))
            code = '' if is_comment else line.split('//', 1)[0]
            comment = line if is_comment else line[len(code):]
            if code:
                for m in RE_FIRE.finditer(code):
                    self.timings[int(m.group(2))].append(no)
                for m in RE_RUNSPECS.finditer(code):
                    self.timings[int(m.group(1))].append(no)
                for m in RE_ATTR.finditer(code):
                    self.attrs[m.group(1)].append(no)
                for m in RE_EFFECT.finditer(code):
                    self.effects[m.group(1)].append(no)
                # Every CamelCase string literal ('Dizzy', 'StrongControl' …);
                # the builder keeps only the client buff_effect_type names.
                for tok in re.findall(r"'([A-Z][a-z][A-Za-z]+)'", code):
                    if no not in self.effects[tok]:
                        self.effects[tok].append(no)
                for m in RE_SJ.finditer(code):
                    self.sj[m.group(1)].append(no)
                # The older text form reads the raw sparam string:
                # `/find_empty|place_on_unit/.test(s)`, `.includes('near_caster')`.
                for m in re.finditer(r"/([a-z_|]+)/\.test\(", code):
                    for k in m.group(1).split('|'):
                        if '_' in k and no not in self.sj[k]:
                            self.sj[k].append(no)
                for k in re.findall(r"includes\('([a-z]+_[a-z_]+)'\)", code):
                    if no not in self.sj[k]:
                        self.sj[k].append(no)
                if not (self.static_line <= no <= static_end) and no not in handler_lines:
                    for t in re.findall(r"'([A-Z][A-Z0-9_]{2,})'", code):
                        self.consumers[t].append(no)
                if lua_lo <= no <= lua_hi:
                    # Methods may sit anywhere on the line, including nested
                    # one-liners such as `Game: {DataUtil: {getTemplate: (t, id) =>`
                    # and library aliases `abs: Math.abs`.
                    for m in RE_LUA_ANY.finditer(code):
                        if no not in self.lua[m.group(1)]:
                            self.lua[m.group(1)].append(no)
                    for m in RE_LUA_FIELD.finditer(code):
                        if no not in self.lua[m.group(1)]:
                            self.lua[m.group(1)].append(no)
                    for name in RE_CASE.findall(code):
                        self.lua[name].append(no)
                for a, b in RE_LITID.findall(code):
                    self.ids[int(a or b)].append(no)
            for m in RE_HASHID.finditer(comment):
                ident = int(m.group(1))
                if no not in self.ids[ident]:
                    self.ids[ident].append(no)

    def handler_is_stub(self, t: str) -> bool:
        start = self.handlers.get(t)
        if not start:
            return True
        body = '\n'.join(self.lines[start - 1:self.handler_end.get(t, start)])
        body = re.sub(r'/\*.*?\*/', '', body, flags=re.S)
        body = re.sub(r'//[^\n]*', '', body)
        inner = body[body.find('{') + 1:body.rfind('}')]
        inner = re.sub(r"bump\(cov\.\w+,\s*'[A-Z_]+'\);?", '', inner)
        return not inner.strip(' \n;,')

    def handler_readers(self, t: str) -> list[int]:
        """Definition lines of the functions a stub handler's comment names
        as its real reader (`/* read by rangeMods() */`)."""
        start = self.handlers.get(t)
        if not start:
            return []
        body = '\n'.join(self.lines[start - 1:self.handler_end.get(t, start)])
        out = []
        for name in RE_READ_BY.findall(body):
            no = self.first_def(name)
            if no and no not in out:
                out.append(no)
        return out

    def handler_flags(self, t: str) -> dict[str, list[int]]:
        """Flags a handler writes (`owner.flags.X = …`) mapped to the lines
        that READ them elsewhere. A handler whose only effect is a flag that
        nothing reads is a disguised stub."""
        start = self.handlers.get(t)
        if not start:
            return {}
        body = '\n'.join(self.lines[start - 1:self.handler_end.get(t, start)])
        code = re.sub(r'//[^\n]*', '', body)
        written = set(re.findall(r'\bflags\.(\w+)\s*(?:=(?!=)|\+=|\|\|=)', code))
        out = {}
        for flag in written:
            reads = []
            pat = re.compile(r'\bflags\??\.' + re.escape(flag) + r'\b(?!\s*(?:=(?!=)|\+=|\|\|=))')
            for no, line in enumerate(self.lines, 1):
                if start <= no <= self.handler_end.get(t, start):
                    continue
                c = line.split('//', 1)[0]
                if pat.search(c):
                    reads.append(no)
            out[flag] = reads
        return out

    def handler_only_flags(self, t: str) -> bool:
        """True when the handler body does nothing except write flags."""
        start = self.handlers.get(t)
        if not start:
            return False
        body = '\n'.join(self.lines[start - 1:self.handler_end.get(t, start)])
        code = re.sub(r'/\*.*?\*/', '', re.sub(r'//[^\n]*', '', body), flags=re.S)
        inner = code[code.find('{') + 1:code.rfind('}')]
        inner = re.sub(r'\bif\s*\(\s*(?:inst\.owner|o|owner)\s*\)\s*', '', inner)
        inner = re.sub(r'(?:inst\.owner|o|owner)\.flags\.\w+\s*(?:=|\+=|\|\|=)[^;]+;', '', inner)
        inner = re.sub(r'const\s+o\s*=\s*inst\.owner;|if\s*\(!o\)\s*return;', '', inner)
        return bool(self.handler_flags(t)) and not inner.strip(' \n;{},')

    def anchor(self, line_no: int, role: str = '', before: int = 1, after: int = 5) -> dict:
        return {'f': ENGINE_NAME, 'l': line_no, 'sym': self.symbol(line_no), 'role': role,
                'code': self.snippet(line_no, before, after)}

    def first_def(self, name: str) -> int:
        for no, _ind, n in self._defs:
            if n == name:
                return no
        return 0

    def find(self, needle: str) -> int:
        for no, line in enumerate(self.lines, 1):
            if needle in line:
                return no
        return 0


def spread(lines: list[int], index: EngineIndex, limit: int = 4) -> list[int]:
    """Pick up to `limit` anchor lines from distinct enclosing symbols."""
    seen, out = set(), []
    for no in lines:
        sym = index.symbol(no)
        if sym in seen:
            continue
        seen.add(sym)
        out.append(no)
        if len(out) >= limit:
            break
    return out
