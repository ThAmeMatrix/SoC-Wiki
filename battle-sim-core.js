/* Offline auto-battle simulator — pure engine (no DOM).
 *
 * Map / units / AI come from client data (world-data, battle-sim, match-cup);
 * every combat rule is executed from the client's own mechanism tables
 * exported to window.WIKI_BATTLE_MECH (scripts/extract_battle_mechanics.py):
 *
 *   skill        targeting, damage type & factors, TP cost, cooldown, effects
 *   speciality   typed effects with parameters, trigger timing (active_time),
 *                target side, per-turn limits and Lua activation conditions
 *   buff         timed states built from specialities (stack / mutex rules,
 *                start- or end-of-action countdown, dispel / immune flags)
 *   hp_attenuation, profession_restrain, weather auras, const_param
 *   battle_guidebook_part — the client's battle handbook, whose rules
 *                (damage formula, energy, action start / end, knockback,
 *                counter stacking, guard, alert …) the turn loop follows.
 *
 * Lua activation conditions are evaluated by a small Lua-expression
 * interpreter over the battle state; functions it does not know are counted
 * in result.mechanics.luaUnknown and the effect is not triggered. Effect types
 * the engine does not execute are counted in result.mechanics.skipped.
 */
'use strict';
window.WikiBattleSim = (() => {
  const AI_NOTES = [
    '规则来源：客户端战斗手册（battle_guidebook_part）+ 技能 / 效果（speciality）/ 状态（buff）配置表，按效果类型与触发时机逐条执行。',
    '行动顺序：每个战斗回合开始时按当前速度从高到低排序；行动开始时少数状态（end_time=1，如援护、警戒）递减；行动结束时回复 1 点能量、所有技能冷却 −1、多数状态（end_time=2）递减，并触发「行动结束时」效果（灼烧 / 生命流失等持续伤害）。',
    '伤害：攻击力 − 防御力（扣除无视防御）后乘技能倍率；攻击方增伤 / 减伤相加（下限 −50%），受击方易伤 / 免伤逐项相乘（上限 300%）；暴击率 = 10% 基础 + 暴击属性 + 技能暴击，暴伤 = 30% 基础 + 暴伤属性；穿透伤害无视防御与增减伤、只受穿透修正（上限 230%）且不暴击；持续伤害按穿透结算并受持续伤害修正。',
    '修正：职业克制（profession_restrain → 攻击 ±30%）、受伤 / 濒死（hp_attenuation 的造成 / 受到伤害修正）、高低差（高 2 以上 +15%，低 2 以上 −10%，另叠加「高度攻击」效果）、护盾先于生命值承伤、格挡使物理伤害减半、闪避使本次攻击落空。',
    '反应：被攻击前判定闪避 / 格挡 / 先制，命中后判定反击（同一角色只触发 1 个反击）；友军受到单体直击时援护防御者换位代为承受；敌人移动结束进入警戒范围时触发警戒技能。只有技能自身带 FORCE_STOP（或客户端「强制警戒（可打断技能）」）才打断行动；STRENGTHEN_ALERT「警戒强化」只强化警戒、不打断。安娜是「一段警戒造成 2 段伤害」：一次警戒触发只消耗 1 次次数、只做一次施放，ADDITIONAL_ATTACK 链接的第 2 个纯伤害技能并入同一次技能的伤害段（35% + 35%），不是两次警戒。致命伤害前判定不屈（重生）。',
    '瞬发：技能描述开头带 [瞬发] 标签的技能（客户端「使用后可继续行动」）不结束行动；施放后按 CHECK_STATE → DO_SKILL → MOVE_OR_IDLE 继续，用剩余移动力再走或再放技能，直到放出非瞬发技能 / 无目标待机 / 达到阶段上限。同一瞬发技能在一次行动内不重复施放。',
    '击退：沿手册规则确定方向（对角线距离减半）；撞到角色 / 障碍 / 高差 >2 的地形时停止，双方受撞击伤害；下落高差 >2 受坠落伤害；被击落深水等坑地形直接击败。',
    'AI：对每个可用技能（冷却就绪、能量足够、未被封技）× 可达站位 × 射程内目标打分：预计伤害（含克制 / 高低差 / 增减伤 / 暴击期望，不超过目标剩余生命）+ 击败奖励 + 治疗缺失生命 + 增益 / 减益价值 + ai_skill_order − 能量消耗 − 移动距离；平射技能被弹道上的敌人阻挡；存在嘲讽单位时优先攻击。技能按客户端 skill_list_tag 的分组分成「个性技能 / 正常携带技能 / 普攻」三档优先级，同档的正常携带技能再按技能放置顺序（skill_orders，可在角色编辑器里上下调整）加分，瞬发技能因不消耗行动而额外优先。选位按客户端 specsSkillRange / BlockDist / CastPosition：同一（技能，目标）优先取射程外环（施法距离 = range_max）的站位，再在该环里按 filterByMinMoveDist 取移动消耗最小者，所以远程 / 支援技能会走到极限距离施放，而不是贴着目标放。同分时按已解密 `castPipeline` 的 15 个比较器声明顺序裁决，并用 `targetSorts` 的 10 项目标质量（虚弱 / 嘲讽 / 受伤 / 治疗需求 / 濒死 / 覆盖数 / 物件 / 接近敌人）做小权重排序；`ai_move_close` 会在施放后用剩余移动力真的再走一步。无目标时向最近敌人接近。施放范围取客户端 range_select 表（skill.target_select）：十字 / 单向线 / 矩形 / 横线 / 侧面 / 扇形只能沿直线选格，不能瞄斜角，例如「贯穿天际的必胜流星」为十字范围、只能在自身四条直线上选目标；range_tag 只是近战 / 远程标签，不决定形状。',
    '未执行的效果类型（变身、召唤、陷阱 / 物件、地块状态、部分专属机制）与无法求值的 Lua 条件函数会在「机制覆盖」中逐项计数；这些效果不会生效，结果用于理解阵容与机制的大致走向，不等同于实机。',
  ];

  const key = (x, y) => x + ',' + y;
  const manhattan = (a, b) => Math.abs(a.x - b.x) + Math.abs(a.y - b.y);
  const DIRS = [[1, 0], [-1, 0], [0, 1], [0, -1]];
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  function rng(seed) {
    let a = (Number(seed) >>> 0) || 1;
    return () => {
      a = (a + 0x6D2B79F5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  /* =====================================================================
   * Lua activation-condition interpreter (expressions + local / if / return)
   * ===================================================================== */
  const Lua = (() => {
    class Unknown extends Error { constructor(name) { super(name); this.fn = name; } }
    const KW = new Set(['and', 'or', 'not', 'nil', 'true', 'false', 'return', 'local', 'if', 'then', 'else', 'elseif', 'end',
                        'for', 'in', 'do', 'while', 'break', 'repeat', 'until', 'function']);
    const cache = new Map();

    function tokenize(src) {
      const out = [];
      let i = 0;
      while (i < src.length) {
        const c = src[i];
        if (/\s/.test(c)) { i++; continue; }
        if (c === '-' && src[i + 1] === '-') {
          if (src.startsWith('[[', i + 2)) { const j = src.indexOf(']]', i + 4); i = j < 0 ? src.length : j + 2; continue; }
          while (i < src.length && src[i] !== '\n') i++;
          continue;
        }
        if (/[0-9]/.test(c) || (c === '.' && /[0-9]/.test(src[i + 1]))) {
          const m = /^(0x[0-9a-fA-F]+|[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)/.exec(src.slice(i));
          out.push({t: 'num', v: Number(m[0])}); i += m[0].length; continue;
        }
        if (/[A-Za-z_]/.test(c)) {
          const m = /^[A-Za-z_][A-Za-z0-9_]*/.exec(src.slice(i));
          out.push(KW.has(m[0]) ? {t: m[0]} : {t: 'name', v: m[0]}); i += m[0].length; continue;
        }
        if (c === '"' || c === "'") {
          let j = i + 1, s = '';
          while (j < src.length && src[j] !== c) { s += src[j] === '\\' ? src[++j] : src[j]; j++; }
          out.push({t: 'str', v: s}); i = j + 1; continue;
        }
        const two = src.slice(i, i + 2);
        if (['==', '~=', '<=', '>=', '..'].includes(two)) { out.push({t: two}); i += 2; continue; }
        if ('+-*/%^#<>(){}[],.:;='.includes(c)) { out.push({t: c}); i++; continue; }
        throw new Unknown('token:' + c);
      }
      out.push({t: 'eof'});
      return out;
    }

    function parse(src) {
      const tk = tokenize(src);
      let p = 0;
      const peek = () => tk[p], next = () => tk[p++];
      const expect = t => { if (tk[p].t !== t) throw new Unknown('syntax:' + t); return tk[p++]; };
      const BIN = {or: [1, 1], and: [2, 2], '<': [3, 3], '>': [3, 3], '<=': [3, 3], '>=': [3, 3], '~=': [3, 3], '==': [3, 3],
                   '..': [9, 8], '+': [10, 10], '-': [10, 10], '*': [11, 11], '/': [11, 11], '%': [11, 11], '^': [14, 13]};
      function block(stop) {
        const body = [];
        while (!stop.includes(peek().t)) {
          const t = peek().t;
          if (t === ';') { next(); continue; }
          if (t === 'return') {
            next();
            const es = [];
            if (!(stop.includes(peek().t) || peek().t === ';')) {
              es.push(expr(0));
              while (peek().t === ',') { next(); es.push(expr(0)); }
            }
            if (!es.length) es.push({k: 'nil'});
            if (peek().t === ';') next();
            body.push({k: 'ret', e: es[0], es});
            continue;
          }
          if (t === 'local') {
            next();
            if (peek().t === 'function') {
              next();
              const nm = expect('name').v;
              body.push({k: 'local', names: [nm], vals: [funcBody()]});
              continue;
            }
            const names = [expect('name').v];
            while (peek().t === ',') { next(); names.push(expect('name').v); }
            const vals = [];
            if (peek().t === '=') { next(); vals.push(expr(0)); while (peek().t === ',') { next(); vals.push(expr(0)); } }
            body.push({k: 'local', names, vals});
            continue;
          }
          if (t === 'if') {
            next();
            const arms = [];
            let cond = expr(0);
            expect('then');
            arms.push([cond, block(['elseif', 'else', 'end'])]);
            let other = null;
            while (peek().t === 'elseif') { next(); cond = expr(0); expect('then'); arms.push([cond, block(['elseif', 'else', 'end'])]); }
            if (peek().t === 'else') { next(); other = block(['end']); }
            expect('end');
            body.push({k: 'if', arms, other});
            continue;
          }
          if (t === 'break') { next(); body.push({k: 'break'}); continue; }
          if (t === 'while') {
            next();
            const c = expr(0);
            expect('do');
            const b = block(['end']);
            expect('end');
            body.push({k: 'while', c, b});
            continue;
          }
          if (t === 'for') {
            next();
            const n1 = expect('name').v;
            if (peek().t === '=') {
              next();
              const a = expr(0); expect(',');
              const b = expr(0);
              let s = null;
              if (peek().t === ',') { next(); s = expr(0); }
              expect('do');
              const bd = block(['end']);
              expect('end');
              body.push({k: 'fornum', v: n1, a, b, s, bd});
              continue;
            }
            const names = [n1];
            while (peek().t === ',') { next(); names.push(expect('name').v); }
            expect('in');
            const it = expr(0);
            expect('do');
            const bd = block(['end']);
            expect('end');
            body.push({k: 'forin', names, it, bd});
            continue;
          }
          // assignment (a = e / a.b = e) or a call used as a statement
          const target = suffixed();
          if (peek().t === '=') {
            next();
            body.push({k: 'assign', target, e: expr(0)});
            continue;
          }
          if (target.k === 'call' || target.k === 'mcall') { body.push({k: 'expr', e: target}); continue; }
          throw new Unknown('statement:' + t);
        }
        return body;
      }
      function expr(limit) {
        let left;
        const t = peek().t;
        if (t === 'not' || t === '-' || t === '#') { next(); left = {k: 'un', op: t, e: expr(12)}; }
        else left = suffixed();
        for (;;) {
          const op = peek().t;
          const pr = BIN[op];
          if (!pr || pr[0] <= limit) break;
          next();
          left = {k: 'bin', op, a: left, b: expr(pr[1])};
        }
        return left;
      }
      function args() {
        const t = peek().t;
        if (t === 'str') return [{k: 'lit', v: next().v}];
        if (t === '{') return [table()];
        expect('(');
        const out = [];
        if (peek().t !== ')') { out.push(expr(0)); while (peek().t === ',') { next(); out.push(expr(0)); } }
        expect(')');
        return out;
      }
      function table() {
        expect('{');
        const items = [], keys = [];
        while (peek().t !== '}') {
          // Lua supports `[expr] = value`, `name = value` and positional values.
          if (peek().t === '[') {
            next();
            const key = expr(0);
            expect(']');
            expect('=');
            keys.push({k: 'computed', v: key});
            items.push(expr(0));
          } else if (peek().t === 'name' && tokens[p + 1]?.t === '=') {
            keys.push({k: 'named', v: next().v});
            next();                              // '='
            items.push(expr(0));
          } else {
            keys.push(null);
            items.push(expr(0));
          }
          if (peek().t === ',' || peek().t === ';') next(); else break;
        }
        expect('}');
        return {k: 'tbl', items, keys};
      }
      function primary() {
        const tok = next();
        switch (tok.t) {
          case 'num': case 'str': return {k: 'lit', v: tok.v};
          case 'nil': return {k: 'nil'};
          case 'true': return {k: 'lit', v: true};
          case 'false': return {k: 'lit', v: false};
          case 'name': return {k: 'var', v: tok.v};
          case '{': p--; return table();
          case '(': { const e = expr(0); expect(')'); return e; }
          case 'function': return funcBody();
          default: throw new Unknown('syntax:' + tok.t);
        }
      }
      function funcBody() {
        expect('(');
        const params = [];
        while (peek().t !== ')') { params.push(expect('name').v); if (peek().t === ',') next(); }
        expect(')');
        const body = block(['end']);
        expect('end');
        return {k: 'fn', params, body};
      }
      function suffixed() {
        let e = primary();
        for (;;) {
          const t = peek().t;
          if (t === '.') { next(); e = {k: 'idx', o: e, key: {k: 'lit', v: expect('name').v}}; }
          else if (t === '[') { next(); const kx = expr(0); expect(']'); e = {k: 'idx', o: e, key: kx}; }
          else if (t === ':') { next(); const m = expect('name').v; e = {k: 'mcall', o: e, m, args: args()}; }
          else if (t === '(' || t === 'str' || t === '{') { e = {k: 'call', f: e, args: args()}; }
          else break;
        }
        return e;
      }
      const body = block(['eof']);
      return body;
    }

    const truthy = v => v !== false && v !== null && v !== undefined;
    const RET = Symbol('ret');

    function get(obj, k, path) {
      if (obj === null || obj === undefined) return undefined;
      if (typeof obj.__get === 'function') return obj.__get(k, path);
      if (Object.prototype.hasOwnProperty.call(obj, k)) return obj[k];
      if (Array.isArray(obj) && typeof k === 'number') return obj[k - 1];
      // A numeric/string client field (e.g. buff.category.type) has no such
      // member; Lua would read nil, not fail the whole condition.
      if (typeof obj === 'number' || typeof obj === 'string' || typeof obj === 'boolean') return undefined;
      throw new Unknown(path);
    }

    function ev(n, env, path) {
      switch (n.k) {
        case 'lit': return n.v;
        case 'nil': return null;
        case 'var':
          if (n.v in env) return env[n.v];
          throw new Unknown(n.v);
        case 'tbl': {
          const out = n.items.map(x => ev(x, env));
          const hasKeys = n.keys?.some(Boolean);
          if (!hasKeys) return out;    // plain array literal: keep pairs/ipairs working
          // Explicit `[expr] = v` / `name = v` fields become named properties;
          // positional values keep Lua's 1-based indices on the same object.
          const obj = {};
          let i = 1;
          n.keys.forEach((key, x) => {
            if (!key) { obj[i++] = out[x]; return; }
            const k = key.k === 'named' ? key.v : String(ev(key.v, env));
            obj[k] = out[x];
          });
          Object.defineProperty(obj, 'length', {value: i - 1, enumerable: false});
          return obj;
        }
        case 'fn': return (...args) => {
          const scope = Object.create(env);
          n.params.forEach((nm, i) => { scope[nm] = args[i] ?? null; });
          const r = run(n.body, scope);
          return r && r !== BRK ? r.v : null;
        };
        case 'idx': {
          const o = ev(n.o, env);
          const k = ev(n.key, env);
          return get(o, k, nameOf(n));
        }
        case 'mcall': {
          const o = ev(n.o, env);
          const a = n.args.map(x => ev(x, env));
          if (o === null || o === undefined) return null;
          const fn = o.__methods?.[n.m] ?? (typeof o[n.m] === 'function' ? o[n.m] : null);
          if (!fn) throw new Unknown(n.m);
          return fn.apply(o, a);
        }
        case 'call': {
          const f = ev(n.f, env);
          const a = n.args.map(x => ev(x, env));
          if (typeof f !== 'function') throw new Unknown(nameOf(n.f));
          return f(...a);
        }
        case 'un': {
          const v = ev(n.e, env);
          if (n.op === 'not') return !truthy(v);
          if (n.op === '-') return -Number(v);
          return Array.isArray(v) ? v.length : String(v ?? '').length;
        }
        case 'bin': {
          if (n.op === 'and') { const a = ev(n.a, env); return truthy(a) ? ev(n.b, env) : a; }
          if (n.op === 'or') { const a = ev(n.a, env); return truthy(a) ? a : ev(n.b, env); }
          const a = ev(n.a, env), b = ev(n.b, env);
          switch (n.op) {
            case '==': return a === b || (a == null && b == null);
            case '~=': return !(a === b || (a == null && b == null));
            case '<': return a != null && b != null && a < b;
            case '>': return a != null && b != null && a > b;
            case '<=': return a != null && b != null && a <= b;
            case '>=': return a != null && b != null && a >= b;
            case '+': return Number(a) + Number(b);
            case '-': return Number(a) - Number(b);
            case '*': return Number(a) * Number(b);
            case '/': return Number(a) / Number(b);
            case '%': return Number(a) % Number(b);
            case '^': return Math.pow(Number(a), Number(b));
            case '..': return String(a ?? '') + String(b ?? '');
          }
        }
      }
      throw new Unknown('node:' + n.k);
    }
    const nameOf = n => n.k === 'var' ? n.v : n.k === 'idx' ? nameOf(n.o) + '.' + (n.key.v ?? '?') : n.k;

    const BRK = {brk: true};
    const iterOf = v => {
      if (v && v.__iter) return v.__iter;
      if (Array.isArray(v)) return v.map((x, i) => [i + 1, x]);
      if (v === null || v === undefined) return [];
      throw new Unknown('iterate');
    };
    function run(body, env) {
      for (const st of body) {
        if (st.k === 'ret') return {[RET]: true, v: ev(st.e, env),
          vs: st.es && st.es.length > 1 ? st.es.map(x => ev(x, env)) : null};
        if (st.k === 'break') return BRK;
        if (st.k === 'expr') { ev(st.e, env); continue; }
        if (st.k === 'assign') {
          if (st.target.k === 'var') {
            // assign to the scope that declared the name (closures), else the current one
            let s = env;
            while (s && !Object.prototype.hasOwnProperty.call(s, st.target.v)) s = Object.getPrototypeOf(s);
            (s || env)[st.target.v] = ev(st.e, env);
            continue;
          }
          throw new Unknown('assign');
        }
        if (st.k === 'while') {
          let guard = 0;
          while (truthy(ev(st.c, env))) {
            if (++guard > 500) throw new Unknown('loop');
            const r = run(st.b, env);
            if (r === BRK) break;
            if (r) return r;
          }
          continue;
        }
        if (st.k === 'fornum') {
          const a = Number(ev(st.a, env)), b = Number(ev(st.b, env)), s = st.s ? Number(ev(st.s, env)) : 1;
          if (!s || Math.abs((b - a) / s) > 500) throw new Unknown('loop');
          for (let i = a; s > 0 ? i <= b : i >= b; i += s) {
            env[st.v] = i;
            const r = run(st.bd, env);
            if (r === BRK) break;
            if (r) return r;
          }
          continue;
        }
        if (st.k === 'forin') {
          for (const pair of iterOf(ev(st.it, env))) {
            st.names.forEach((nm, i) => { env[nm] = pair[i] ?? null; });
            const r = run(st.bd, env);
            if (r === BRK) break;
            if (r) return r;
          }
          continue;
        }
        if (st.k === 'local') { st.names.forEach((nm, i) => { env[nm] = st.vals[i] ? ev(st.vals[i], env) : null; }); continue; }
        if (st.k === 'if') {
          let done = false;
          for (const [c, b] of st.arms) {
            if (truthy(ev(c, env))) { const r = run(b, env); if (r) return r; done = true; break; }
          }
          if (!done && st.other) { const r = run(st.other, env); if (r) return r; }
          continue;
        }
      }
      return null;
    }

    const BASE = {
      pairs: v => ({__iter: Array.isArray(v) ? v.map((x, i) => [i + 1, x]) : []}),
      ipairs: v => ({__iter: Array.isArray(v) ? v.map((x, i) => [i + 1, x]) : []}),
      print: () => null, printerror: () => null, tostring: v => String(v ?? 'nil'), tonumber: v => Number(v),
      type: v => v === null || v === undefined ? 'nil' : Array.isArray(v) ? 'table' : typeof v === 'function' ? 'function' : typeof v,
      math: {abs: Math.abs, floor: Math.floor, ceil: Math.ceil, max: Math.max, min: Math.min},
      // Bitwise helpers appear in dynamic_param (e.g. direction_bits).
      lshift: (a, b) => (Number(a) || 0) << (Number(b) || 0),
      rshift: (a, b) => (Number(a) || 0) >>> (Number(b) || 0),
      band: (a, b) => (Number(a) || 0) & (Number(b) || 0),
      bitand: (a, b) => (Number(a) || 0) & (Number(b) || 0),
      bitor: (a, b) => (Number(a) || 0) | (Number(b) || 0),
      bor: (a, b) => (Number(a) || 0) | (Number(b) || 0),
      string: {format: (f, ...a) => String(f).replace(/%[dsf]/g, () => String(a.shift() ?? '')),
               sub: (s, i, j) => String(s ?? '').slice((i || 1) - 1, j || undefined),
               find: (s, p) => String(s ?? '').indexOf(String(p ?? '')) + 1 || null,
               // `for x in string.gmatch(s, "%d+") do` — generic-for consumes
               // an __iter table of [index, value] pairs.
               gmatch: (s, pattern) => {
                 const src = String(s ?? '');
                 let re;
                 try { re = new RegExp(String(pattern ?? '%d+')
                   .replace(/%d/g, '\\d').replace(/%w/g, '\\w').replace(/%s/g, '\\s')
                   .replace(/%a/g, '[A-Za-z]'), 'g'); }
                 catch { re = /\d+/g; }
                 const found = [];
                 let m;
                 while ((m = re.exec(src)) !== null) {
                   found.push(m[0]);
                   if (!m[0]) re.lastIndex++;
                 }
                 return {__iter: found.map((v, i) => [i + 1, v])};
               }},
      // Round 32: client namespaces / helper functions referenced by
      // activation conditions and dynamic_param. Returning a concrete value
      // lets the condition be evaluated instead of being reported unknown.
      CLASS_TYPE: {UNIT_SPEC: 1, SKILL_SPEC: 2, BUFF_SPEC: 3, PROPS: 4, TRAP: 5},
      Battle: {Entity: {Type: {Unit: 1, Props: 2, Trap: 3, Widget: 4}},
               AITemplate: {NONE: 0, MELEE: 1, RANGED: 2, SUPPORT: 3}},
      AITemplate: {NONE: 0, MELEE: 1, RANGED: 2, SUPPORT: 3},
      CLASS: {UNIT_SPEC: 1, SKILL_SPEC: 2},
      BehaviorDecision: () => true,
      CasterLocation: () => ({x: 0, y: 0}),
      IsInDelay: () => false,
      isFieldStatus: () => false,
      checkForget: () => false,
      table: {insert: (arr, v) => { if (Array.isArray(arr)) arr.push(v); return arr; },
              remove: (arr, v) => { if (Array.isArray(arr)) { const i = arr.indexOf(v); if (i >= 0) arr.splice(i, 1); } return arr; },
              concat: (a, b) => (Array.isArray(a) ? a : []).concat(Array.isArray(b) ? b : []),
              unpack: a => Array.isArray(a) ? a : []},
    };
    // Returns {ok: boolean} or {unknown: fnName}.
    function evaluate(src, env) {
      if (!src) return {ok: true, v: null, vs: null};
      let ast = cache.get(src);
      if (ast === undefined) {
        try { ast = parse(src); } catch (e) { ast = {bad: e.fn || 'syntax'}; }
        cache.set(src, ast);
      }
      if (ast.bad) return {unknown: ast.bad};
      try {
        const r = run(ast, Object.assign(Object.create(null), BASE, env));
        return {ok: true, v: r ? r.v : null, vs: r ? r.vs : null};
      } catch (e) {
        if (e instanceof Unknown) return {unknown: e.fn};
        return {unknown: 'error:' + (e.message || e)};
      }
    }
    const test = (src, env) => {
      const r = evaluate(src, env);
      return r.unknown ? {unknown: r.unknown} : {ok: truthy(r.v)};
    };
    // speciality.dynamic_param returns `nil,p1,p2,p3`: each non-nil slot
    // overrides that param at runtime. Used by effects whose value depends on
    // buff stacks, star rank, neighbouring units, or whose turn it is.
    const params = (src, env) => {
      const r = evaluate(src, env);
      if (r.unknown) return {unknown: r.unknown};
      return {values: r.vs || (r.v === null || r.v === undefined ? [] : [r.v])};
    };
    return {test, params, truthy, Unknown, evaluate};
  })();

  /* =====================================================================
   * Map
   * ===================================================================== */
  function prepareMap(map, data) {
    const terrain = data.terrain || {};
    const cells = new Map();
    for (const [x, y, h, t] of map.cells || []) {
      const info = terrain[String(t)] || {name: '地形 ' + t, cost: 10, pit: false};
      const cost = Number(info.cost);
      const walk = !info.pit && cost > 0 && cost < 1000;
      cells.set(key(x, y), {x, y, h: Number(h) || 0, t, name: info.name, pit: !!info.pit,
                            walk, step: walk ? Math.max(1, cost / 10) : Infinity, status: 1});
    }
    return {id: map.id, name: (map.stages || [])[0] || map.name, w: map.width, h: map.height, cells,
            at: (x, y) => cells.get(key(x, y))};
  }

  const STD_JUMP = 2;
  const linked = (a, b) => a && b && a.walk && b.walk && Math.abs(a.h - b.h) <= STD_JUMP;

  function mainComponent(grid) {
    const seen = new Set();
    let best = [];
    for (const c of grid.cells.values()) {
      if (!c.walk || seen.has(key(c.x, c.y))) continue;
      const comp = [], queue = [c];
      seen.add(key(c.x, c.y));
      while (queue.length) {
        const cur = queue.pop();
        comp.push(cur);
        for (const [dx, dy] of DIRS) {
          const n = grid.at(cur.x + dx, cur.y + dy);
          if (linked(cur, n) && !seen.has(key(n.x, n.y))) { seen.add(key(n.x, n.y)); queue.push(n); }
        }
      }
      if (comp.length > best.length) best = comp;
    }
    return best;
  }

  function bfsDist(grid, start, allowed) {
    const dist = new Map([[key(start.x, start.y), 0]]);
    const queue = [start];
    for (let i = 0; i < queue.length; i++) {
      const cur = queue[i];
      for (const [dx, dy] of DIRS) {
        const n = grid.at(cur.x + dx, cur.y + dy);
        const k = n && key(n.x, n.y);
        if (linked(cur, n) && allowed.has(k) && !dist.has(k)) { dist.set(k, dist.get(key(cur.x, cur.y)) + 1); queue.push(n); }
      }
    }
    return dist;
  }

  // Client `arena_season_template.unit_facing` uses 1/2 for the two arena
  // sides; the plan file also accepts an explicit [dx,dy] vector or a compass
  // name. A = +x (east), B = -x (west) when nothing is specified.
  const FACINGS = {east: [1, 0], west: [-1, 0], south: [0, 1], north: [0, -1],
                   e: [1, 0], w: [-1, 0], s: [0, 1], n: [0, -1],
                   '东': [1, 0], '西': [-1, 0], '南': [0, 1], '北': [0, -1]};
  function parseFacing(v) {
    if (Array.isArray(v) && v.length === 2 && v.every(Number.isFinite)) {
      const [x, y] = v;
      if (x || y) return [Math.sign(x), Math.sign(y)];
      return null;
    }
    if (typeof v === 'string' && FACINGS[v.toLowerCase()]) return FACINGS[v.toLowerCase()].slice();
    if (v === 1 || v === '1') return [1, 0];
    if (v === 2 || v === '2') return [-1, 0];
    if (v === 3 || v === '3') return [0, 1];
    if (v === 4 || v === '4') return [0, -1];
    return null;
  }

  function spawnCells(grid, countA, countB, custom) {
    const comp = mainComponent(grid);
    if (comp.length < countA + countB) return null;
    const allowed = new Set(comp.map(c => key(c.x, c.y)));
    // Geometric (not BFS-step) diameter so height detours cannot put both
    // anchors in the same corner; BFS only guarantees reachability.
    const far = (from) => {
      const d = bfsDist(grid, from, allowed);
      let pick = from, best = -1;
      for (const c of comp) {
        if (!d.has(key(c.x, c.y))) continue;
        const v = manhattan(c, from);
        if (v > best) { best = v; pick = c; }
      }
      return pick;
    };
    const p = far(comp[0]), q = far(p);
    const nearest = (anchor, count, taken) => {
      const d = bfsDist(grid, anchor, allowed);
      const geo = c => manhattan(c, anchor) + d.get(key(c.x, c.y)) * 0.001;
      return comp.filter(c => !taken.has(key(c.x, c.y)) && d.has(key(c.x, c.y)))
        .sort((a, b) => (geo(a) - geo(b)) || (b.h - a.h) || (a.y - b.y) || (a.x - b.x))
        .slice(0, count);
    };
    const taken = new Set();
    const A = nearest(p, countA, taken);
    A.forEach(c => taken.add(key(c.x, c.y)));
    const B = nearest(q, countB, taken);
    const out = {A, B, size: comp.length};
    // Per-match manual formation. The client does not ship cup spawn
    // coordinates, so the page lets the user place every fighter. Only
    // walkable, in-bounds, unoccupied cells of the main component are used;
    // everything else falls back to the client-derived automatic anchors.
    out.facing = {A: [], B: []};
    if (custom) {
      const used = new Set();
      const allowed = new Set(comp.map(c => key(c.x, c.y)));
      let applied = 0;
      for (const side of ['A', 'B']) {
        const list = Array.isArray(custom[side]) ? custom[side] : [];
        for (let i = 0; i < out[side].length; i++) {
          const pos = list[i];
          out.facing[side][i] = parseFacing(pos?.dir ?? pos?.facing ?? custom.facing?.[side])
            || parseFacing(custom.facingDefault);
          const x = Number(pos?.x), y = Number(pos?.y);
          if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
          const k = key(Math.round(x), Math.round(y));
          const cell = grid.at(Math.round(x), Math.round(y));
          if (!cell || !cell.walk || !allowed.has(k) || used.has(k)) continue;
          out[side][i] = cell;
          used.add(k);
          applied++;
        }
      }
      out.customApplied = applied;
      out.customRequested = (custom.A?.length || 0) + (custom.B?.length || 0);
    }
    return out;
  }

    /* =====================================================================
     * Skills & fighters
     * ===================================================================== */
  const CASTABLE_TYPES = new Set([2, 6, 9]);
  // skill.type 1 = active, 3 = passive. EVERY client active skill carried in a
  // kit slot is castable: heal / support / debuff / tactical skills use
  // skill_type 1/4/5/8 and were previously demoted to passives, so they never
  // reached the skill bar. Their effects (BUFF / DISPEL / RECOVER / AOE / ...)
  // run at their own active_time when the skill is cast, which is also the
  // proper fix for skills like 「潜袭」whose timed effects used to leak onto the
  // unit at battle start.
  const castable = (s, force = false) => !!s && (force || s.ty === 1 || !!s.ap);
  // Client skill.desc marks a [瞬发] skill with the tag immediately after its
  // category label: 「（支援）[瞬发]，使用后可继续行动」/「（物理伤害）[瞬发]」.
  // Passive descriptions that merely mention the tag in a NEGATED context
  // (「非[瞬发]技能冷却减 2」「使用[瞬发]以外技能后」) are not instant skills.
  // There is no dedicated `instant` column: skill.phase / skill_tag_ids do not
  // separate them in the exported client table, the desc tag is authoritative.
  const NEGATED_INSTANT = /非\[瞬发\]|\[瞬发\]以外|非瞬发/;
  const isInstant = s => {
    const head = String(s?.desc || '').slice(0, 24);
    return head.includes('[瞬发]') && !NEGATED_INSTANT.test(head);
  };
  // Human-readable skill labels for the replay. Everything comes from the
  // client tables: damage_type.name / skill_tag.name (Chinese columns), the
  // description's category prefix, and the buff_type of the states the skill's
  // own specialities apply. No per-character or per-skill name hardcoding.
  const DT_LABEL = {1: '物理伤害', 2: '魔法伤害', 3: '治疗', 4: '穿透伤害', 5: '支援'};
  // element.json: 1 地 / 2 火 / 3 风 / 4 水 / 5 光 / 6 暗. Client declares
  // it per skill through ELEMENT_TYPE specialities (火魔法 / 风沙魔法).
  const ELEMENT_LABEL = {1: '地属性', 2: '火属性', 3: '风属性', 4: '水属性', 5: '光属性', 6: '暗属性'};
  const skillElement = (s, M) => {
    for (const sk of [s, M?.skills?.[s?.fl], M?.skills?.[s?.scid]]) {
      if (!sk) continue;
      for (const sid of sk.sp || []) {
        const q = M?.specs?.[sid];
        if (q?.t === 'ELEMENT_TYPE' && Number(q.p?.[0])) return Number(q.p[0]);
      }
    }
    return 0;
  };
  // Only the client's GENERIC classification tags are user-facing labels.
  // The other 120+ rows are internal mechanism markers (ChainTag1, 协同指令,
  // SPxxx-…, 角色职业技能 …) that the engine needs but a reader should not see.
  const DISPLAY_TAG_TYPES = new Set([
    'Melee', 'Ranged', 'Direct', 'Indirect', 'Support', 'Guard', 'Charge',
    'Combo', 'Normal', 'SupportDefense', 'GuardAttack', 'SupportAttack',
  ]);
  function skillLabels(s, M) {
    if (!s) return [];
    const out = [];
    const push = v => { if (v && !out.includes(v)) out.push(v); };
    const head = String(s.desc || '').slice(0, 26);
    const cat = /^（([^）]+)）/.exec(head);
    if (cat) push(cat[1]);
    push(DT_LABEL[s.dt] || (M?.damageTypeNames?.[s.dt] || null));
    const elem = skillElement(s, M);
    if (elem) push(ELEMENT_LABEL[elem] || `元素${elem}`);
    for (let i = 0; i < (s.tags || []).length; i++)
      if (DISPLAY_TAG_TYPES.has(s.tags[i])) push(s.tn?.[i] || s.tags[i]);
    if (isInstant(s)) push('瞬发');
    if (s.area && s.area.type !== 'single') push('范围');
    else if (s.area && s.area.type === 'single' && [1, 2, 4].includes(s.dt)) push('单体');
    // Follow the client's own skill chain (idskill_follow / skill_cast_id /
    // CAST_SKILL): 陷阵·锐意承锋's 缴械/伤害2 live on 灭魂一击后续, not on
    // the head skill, so a head-only scan would miss the 减益 label.
    let debuff = false, buff = false, summon = false, place = false, move = false;
    const seen = new Set();
    const walk = (sk, depth) => {
      if (!sk || depth > 2 || seen.has(sk.id)) return;
      seen.add(sk.id);
      for (const sid of sk.sp || []) {
        const q = M?.specs?.[sid];
        if (!q) continue;
        if (q.t === 'BUFF' || q.t === 'BUFF_STACK_MODIFY_ATTRIBUTE') {
          const b = M?.buffs?.[q.p?.[0]];
          if (b?.bt === 3) debuff = true;
          else if (b?.bt === 2) buff = true;
        }
        if (q.t === 'PLACE_UNIT') summon = true;
        if (q.t === 'PLACE_ITEM' || q.t === 'PLACE_TRAP') place = true;
        if (q.t === 'JUMP_MOVE' || q.t === 'CHARGE' || q.t === 'KNOCKBACK') move = true;
        if (q.t === 'CAST_SKILL' && q.p?.[0]) walk(M?.skills?.[q.p[0]], depth + 1);
      }
      for (const id of [sk.fl, sk.scid, sk.ovid]) if (id) walk(M?.skills?.[id], depth + 1);
    };
    walk(s, 0);
    if (debuff) push('减益');
    if (buff) push('增益');
    if (summon) push('召唤');
    if (place) push('放置');
    if (move) push('位移');
    if ((s.tags || []).includes('Normal') || s.ct === 1) push('普攻');
    return out;
  }
  // Client Logic_AI_Skill_List_Tag declares 13 tags whose declaration order is
  // the priority (NONE 52 … NORMAL_ATTACK 4). 普攻 is the LOWEST tag, so the
  // three groups the simulator evaluates separately are ranked accordingly.
  const DEFAULT_SKILL_PRIORITY = {personality: 3, carried: 2, basic: 1,
                                  tierStep: 60, slotStep: 14, instantBonus: 420,
                                  // MOVE_TO bonus per tile advanced by a
                                  // self-displacement skill, and the rule that
                                  // a free [瞬发] cast is always used first.
                                  moveToStep: 12, instantFirst: true,
                                  // filterByMinMoveDist: how many points of
                                  // cast VALUE a nearer stand may give up,
                                  // and the cost per movement step.
                                  castValueTolerance: 0, moveCostStep: 1.5,
                                  // MOVE_OR_IDLE: a self-displacement skill
                                  // may stop as soon as it has closed N
                                  // tiles, instead of burning full movement.
                                  moverMoveTolerance: 20, moverMoveTolerancePct: 0.01,
                                  moverMinAdvance: 3,
                                  // Rank-weighted targetSorts contribution
                                  // (declared comparator priority; small so
                                  // expected damage stays the primary value).
                                  targetSortWeight: 1};
  const isUtility = s => !!s && (s.dt === 5 ||
    (!s.df && !s.dmg && !s.dp && s.dt !== 1 && s.dt !== 2 && s.dt !== 4 && s.dt !== 3));
  // Decide which side a no-damage skill acts on from its own specialities'
  // target_type, instead of the skill-level target_method (which is 0/self for
  // most support skills even when they debuff enemies).
  function utilitySide(s, M) {
    if (s._uSide) return s._uSide;
    let enemy = 0, ally = 0;
    const SIDE_EFFECTS = new Set(['BUFF', 'DISPEL', 'REMOVE_BUFF', 'DAMAGE', 'KNOCKBACK', 'STEAL_TP',
      'RECOVER_ATTRIBUTE', 'PHYSIC_ARMOR', 'SPELL_ARMOR', 'SKILL_CD', 'CHARGE', 'TARGET_TELEPORT',
      'PARASITIC', 'POISON', 'BUFF_BUNDLE_GAIN', 'SPECIFY_ATTRIBUTE_VALUE', 'SKILL_GROUP',
      'TACTICS_SKILL_GROUP', 'MAKE_OTHER_CAST_SKILL', 'CAST_SKILL', 'PLACE_ITEM', 'PLACE_TRAP',
      // An AOE speciality's own target_type says which side the skill hits.
      // 麦莎·SP「全装甲集火号令！」only carries AOE #1984 (tt=2 敌方);
      // without this it was classified as a friendly-only buff and fired at
      // empty/friendly tiles with zero damage.
      'AOE']);
    for (const sid of s.sp || []) {
      const sp = M?.specs?.[sid];
      if (!sp || !SIDE_EFFECTS.has(sp.t)) continue;
      if (sp.tt === 2) enemy += 2;
      else if (sp.tt === 4) enemy++;
      else if (sp.tt === 1 || sp.tt === 3 || sp.tt === 5) ally += 2;
    }
    s._uSide = enemy > ally ? 'enemy' : 'ally';
    return s._uSide;
  }
  // attribute_type 17 (SPEED) is plain speed: higher acts earlier. The client
  // config stores its modifiers as wait-time deltas (速度+50 -> -50), which
  // extract_battle_mechanics.py already converted at export time. No sign
  // flipping belongs in the engine or the panel.


  // Legacy roster skill object → engine skill (used for custom / edited
  // skills and when the mechanics data is not loaded).
  function legacySkill(s) {
    const dt = s.heal ? 3 : s.ignoreDef ? 4 : (s.spell > 0 && !(s.physic > 0)) ? 2 : (s.damageType || 1);
    return {
      id: s.id, n: s.name || '技能', st: 6, ty: 1, tp: s.tp || 0, cd: s.cooldown || 0, pcd: 0,
      rmin: s.rangeMin || 0, rmax: s.rangeMax || 0, rt: s.shape === 'cross' ? 2 : 1, tm: 0, ts: 0, ttp: 0, tw: 0,
      hm: (s.area?.type || 'single') === 'single' ? 2 : 3, am: 1, dt,
      pf: dt === 2 ? 0 : (s.physic ?? 100) || (dt === 3 ? 0 : 100), sf: dt === 2 || dt === 3 ? (s.spell || 100) : (s.spell || 0),
      df: s.factor || 0, dmg: 0, dp: 0, cc: 0, di: 0, up: s.attackUp || 0, dn: s.attackDown || 0,
      sp: [], tags: [], ord: s.order || 0, lc: 0, lct: 0, aim: s.aim || (s.heal ? 'ally' : 'enemy'),
      area: s.area || {type: 'single'}, hits: s.hits || 1, legacy: true,
    };
  }

  /* Client `range_select` table (配置表/lua_dbtemplate/range_select.json):
       1 菱形 diamond · 2 十字 cross_line · 3 扇形 sector · 4 单向线 direction
       5 矩形 rect · 6 图像 pattern · 7 全部 all · 8 侧面 side_line
       9 横线 horizontal_line · 10 全部单位 · 11 全部有东西的地块.
     `skill.target_select` (s.ts) is the CAST-RANGE shape consumed by
     Logic_Skill.FindRangeBlocks / ApplySkillRange / AddRange / range_blocks.
     `skill.range_tag` (s.rt) is only the NONE / MELEE / RANGED tag read by
     active_param Lua (「闪避1次（远程）」), NOT a shape. The old engine used
     range_tag as the shape and therefore let 十字 / 直线 skills aim at
     diagonal tiles. Legacy roster skills carry `shape === 'cross'` instead. */
  const RANGE_SELECT = {1: 'diamond', 2: 'cross_line', 3: 'sector', 4: 'direction',
                        5: 'rect', 6: 'pattern', 7: 'all', 8: 'side_line',
                        9: 'horizontal_line', 10: 'all_unit', 11: 'all_update_block'};
  const castShape = s => s?.legacy ? (s.rt === 2 ? 'cross_line' : 'diamond')
                                   : (RANGE_SELECT[s?.ts] || 'diamond');
  const LINE_SHAPES = new Set(['cross_line', 'sector', 'direction', 'rect',
                               'side_line', 'horizontal_line']);
  const WHOLE_FIELD_SHAPES = new Set(['all', 'all_unit', 'all_update_block']);
  const CARDINALS = [[1, 0], [-1, 0], [0, 1], [0, -1]];
  const rangeRingCache = new Map();
  // Offsets of the castable cells for range [lo, hi]. Line shapes are the
  // union of the four cardinal directions because the player chooses ONE
  // direction when casting; the AI evaluates all four. Diagonals are never
  // castable for 十字 / 单向线 / 矩形 / 横线 / 侧面 skills.
  function castRangeOffsets(lo, hi, shape, width) {
    const w = Math.max(1, Number(width) || 1);
    const k = `${lo}|${hi}|${shape}|${w}`;
    let ring = rangeRingCache.get(k);
    if (ring) return ring;
    ring = [];
    if (LINE_SHAPES.has(shape)) {
      const half = Math.floor((w - 1) / 2);
      const seen = new Set();
      for (const [ux, uy] of CARDINALS) {
        for (let d = Math.max(0, lo); d <= hi; d++) {
          const spread = shape === 'sector' ? Math.floor(d / 2) : half;
          for (let side = -spread; side <= spread; side++) {
            const dx = ux * d - uy * side, dy = uy * d + ux * side;
            if (Math.abs(dx) + Math.abs(dy) > hi + spread) continue;
            const kk = dx + ',' + dy;
            if (seen.has(kk)) continue;
            seen.add(kk); ring.push([dx, dy]);
          }
        }
      }
    } else {
      for (let dx = -hi; dx <= hi; dx++) for (let dy = -hi; dy <= hi; dy++) {
        const dist = Math.abs(dx) + Math.abs(dy);
        if (dist < lo || dist > hi) continue;
        ring.push([dx, dy]);
      }
    }
    if (rangeRingCache.size > 256) rangeRingCache.clear();
    rangeRingCache.set(k, ring);
    return ring;
  }
  const castRangeCells = (s, lo, hi) =>
    castRangeOffsets(lo, hi, castShape(s), s?.rw || 1);

  /* Client specialities that RELOCATE THE CASTER while resolving a skill.
     JUMP_MOVE / BLINK / SHADOW_STEP / TELEPORT land the caster on the chosen
     tile; CHARGE (skill.tag "Charge") dashes along the straight line to the
     target. `Logic_AI_AIMachine` evaluates these with ai_move_close /
     skill_list_tag MOVE_TO: the unit advances BEFORE the skill resolves, so
     a [瞬发] teleport such as 科尔「烟幕游击」 walks into 安娜's alert zone
     first, then lands in it again (two separate 警戒 reactions). */
  const SELF_MOVE_TYPES = new Set(['JUMP_MOVE', 'BLINK', 'SHADOW_STEP',
                                   'CHARGE', 'TELEPORT', 'MOVE_ATTACK']);
  function selfMoveOf(s, specs) {
    for (const sid of s?.sp || []) {
      const sp = specs?.[sid];
      if (sp && SELF_MOVE_TYPES.has(sp.t)) return Object.assign({sid: Number(sid)}, sp);
    }
    return (s?.tags || []).includes('Charge')
      ? {t: 'CHARGE', p: [0, 0, 0, 0], n: '冲锋（skill_tag Charge）', sid: 0} : null;
  }

  function skillSet(member, mode) {
    const all = member.skills || [];
    const basic = all.find(s => s.kind === 'basic');
    const out = [];
    const side = mode === 'right' ? 2 : 1;
    const upgrade = mode !== 'basic' && all.find(s => s.kind === 'rank' && s.rank === 9 && s.side === side && s.usable);
    if (upgrade) out.push({...upgrade, kind: 'basic', upgraded: true});
    else if (basic?.usable) out.push(basic);
    for (const s of all) if (s.kind === 'initial' && s.usable) out.push(s);
    if (mode !== 'basic') {
      for (const s of all) if (s.kind === 'rank' && s.rank !== 9 && s.side === side && s.usable) out.push(s);
    }
    return out;
  }

  function normalizeFighter(entry, roster) {
    if (typeof entry === 'string' || typeof entry === 'number') {
      const r = roster.get(String(entry));
      return r ? {template: r, skills: skillSet(r, 'left'), kit: r.kit || null, custom: false, edited: false} : null;
    }
    if (!entry || typeof entry !== 'object') return null;
    const base = entry.key ? roster.get(String(entry.key)) : null;
    const stats = {...(base?.stats || {}), ...(entry.stats || {})};
    const move = {...(base?.move || {}), ...(entry.move || {})};
    if (!(stats.hp > 0)) return null;
    const skills = Array.isArray(entry.skills) && entry.skills.length
      ? entry.skills.filter(s => s && s.usable !== false)
      : (base ? skillSet(base, entry.mode || 'left') : []);
    return {
      template: {
        key: entry.key || entry.id || ('custom-' + (entry.name || 'fighter')),
        name: entry.name || base?.name || '自定义角色',
        pageId: entry.pageId ?? base?.pageId ?? 0,
        prof: entry.prof ?? base?.prof ?? 6,
        profName: entry.profName || base?.profName || '自定义',
        avatar: entry.avatar || base?.avatar || '',
        stats, move,
      },
      skills, kit: entry.kit || base?.kit || null, custom: true,
      // Client skill roles (allSkills[].role) let the personality group be
      // identified even when a personality grants a castable skill.
      skillRoles: entry.skillRoles || null,
      // Editable 技能放置顺序 (skill_orders). Kept separate from `kit` so a
      // pure reorder does not turn the fighter into a legacy edit and lose all
      // of its client specialities.
      slotOrder: Array.isArray(entry.slotOrder) ? entry.slotOrder.map(Number) : null,
      // Preset fighters (乐土群星杯) carry their client kit and are not edits.
      edited: entry.edited !== undefined ? !!entry.edited : Array.isArray(entry.skills) && entry.skills.length > 0,
      statLevel: entry.statLevel || null,
    };
  }

  /* =====================================================================
   * Simulation
   * ===================================================================== */
  const PRIMARY = new Set(['HP_MAX', 'PHYSIC_ATTACK', 'PHYSIC_DEFENCE', 'SPELL_ATTACK', 'SPELL_DEFENCE',
                           'SPEED', 'MOBILITY', 'JUMP', 'TP_MAX']);
  const COMPOSITE = {PRIMARY_ATTRIBUTES: ['HP_MAX', 'PHYSIC_ATTACK', 'SPELL_ATTACK', 'PHYSIC_DEFENCE', 'SPELL_DEFENCE'],
                     ATTACK: ['PHYSIC_ATTACK', 'SPELL_ATTACK'], DEFENCE: ['PHYSIC_DEFENCE', 'SPELL_DEFENCE']};
  // Client active_time is a 65-row enum; 51 = 「每人回合结束2(新回合特殊)」
  // ROUNDEND2 and 52 = 「每人回合开始2(新回合特殊)」ROUNDSTART2 are DISTINCT
  // timings, not aliases of 28/27. Aliasing them to 28/27 made them fire in
  // the wrong batch and left every explicit fire(51)/fire(52) call dead:
  // 光谕 / 再行动 / [SP科尔]-再动加速 / 古兹曼即将复活 … never resolved at
  // their own new-round trigger. The engine already raises fire(51) at
  // endTurn and fire(52) at round start, so no alias is needed.
    // 64 = 触发陷阱时 (fired by triggerObject).
    // 62/63 = 「被非贯穿攻击前 / 后」are DEFENDER-side timings. They used to
    // be aliased to 2 (attacker's 攻击前) or never fired at all, so 豪猪 /
    // 剑牙虎 counter-attacks and 「自然守护」pierceable immunities were either
    // triggered on the wrong unit or silently skipped. They are now fired
    // explicitly around fire(15)/fire(4), gated by the client `Break` tag.
    const AT_ALIAS = {};
  // Client buff.et is only a SUB-TYPE label; many control buffs leave it
  // empty and declare `middle_type: "Control"` + `sub_type: StrongControl /
  // WeakControl` instead. 睡眠 (645) is exactly that: et="" and mt="Control",
  // so checking et alone let a sleeping unit keep casting 冰雪暴 three turns
  // in a row. Match the client's own control classification.
  const CONTROL_SKIP = new Set(['Dizzy', 'Frozen', 'Charm', 'Sleep', 'Hypnosis', 'Stun', 'Petrify']);
  // 「所属控制-定身类，无法做出任何行动」 = sub_type StrongControl (晕眩 / 睡眠
  // / 冰冻 / 魅惑 …): the unit loses its whole turn. 「所属控制-干扰类」 =
  // WeakControl (缴械 / ×主动技 / [▼移动1] / 缠缚) only restricts what it may
  // do, through its own SEAL / DISARM / DISABLE_SKILL / attribute rows. Both
  // share middle_type Control, so testing mt made a [▼移动1] skip the turn.
  const isControlBuff = b => {
    const d = b?.def;
    if (!d) return false;
    if (d.su === 'WeakControl') return false;
    return CONTROL_SKIP.has(d.et) || d.su === 'StrongControl';
  };
  const STATIC_TYPES = new Set(['MODIFY_ATTRIBUTE', 'CONVERT_ATTRIBUTE', 'SKILL_RANGE', 'MULTI_CONSUME_TP', 'IMMUNE',
    'TAUNT', 'PARRY', 'EVADE', 'COUNTER_ATTACK', 'FIRST_HIT', 'ALERT_ATTACK', 'ASSIST_DEFENCE', 'REBORN',
    'PHYSIC_ARMOR', 'SPELL_ARMOR', 'AURA', 'HEIGHT_ATTACK', 'ATTRIBUTE_ATTACK', 'MULTI_ATTACK', 'SUB_ATTACK', 'AOE',
    'TARGET_SELECT', 'FORCE_STOP', 'RECOVER_HP_BY_DAMAGE', 'PREWAR_MODIFY_ATTRIBUTE', 'PREWAR_CONVERT_ATTRIBUTE',
    'REPLACE_SKILL', 'GET_EXTRA_SKILL', 'IGNORE_HP_ATTENUATION', 'FORBIDDEN_EVADE', 'IGNORE_ATTACK_BLOCK',
    'FORCE_BACKSTAB', 'KNOCKBACK_ADD_BUFF', 'IGNORE_ASSIST_DEFENCE', 'IGNORE_FORCE_STOP', 'SEALTH',
    'PERCENT_HEAL', 'PREWAR_MODIFY_BASE_ATTRIBUTE', 'SKILL_GROUP', 'ABSORB', 'FORBIDDEN_REACTIVE',
    'SPECIFY_ATTRIBUTE_VALUE', 'BUFF_STACK_MODIFY_ATTRIBUTE', 'HIT_COUNT_MODIFY_ATTRIBUTE', 'DISTANCE_MODIFY_ATTRIBUTE',
    // ELEMENT_TYPE used to be here (so its handler was unreachable). It is a
    // plain declarative tag with a real handler now.
    'ASSIST_ATTACK', 'ASSIST_COUNTER_ATTACK']);

  function simulate(opts) {
    const data = opts.data || {}, map = opts.map;
    // opts.mech === false forces the basic formula (no client mechanics).
    const M = opts.mech === false ? null : (opts.mech || data.mech || (typeof window !== 'undefined' ? window.WIKI_BATTLE_MECH : null) || null);
    // Runtime substrate derived from the DECRYPTED client Lua scripts
    // (scripts/socdecode/derive_mechanisms.py -> data/client-mechanisms.js).
    // It supplies the AI phases, skill-list tag priority, cast-position sort
    // pipeline, AOE scoring fields and dynamic wait-time policy. The engine
    // falls back to embedded rules when the optional dataset is not loaded.
    const SUB = opts.substrate || (typeof window !== 'undefined' ? window.WIKI_CLIENT_MECHANISMS : null) || null;
    const RULE = SUB?.moveRules || {};
    const PHASES = SUB?.phases?.length ? SUB.phases : ['CHECK_STATE', 'DO_SKILL', 'MOVE_OR_IDLE', 'FINISH'];
    const TAG_W = SUB?.tagWeight || {};
    const DYNAMIC_ORDER = SUB?.waitTime?.dynamicOrder !== false;
    // Priority of the three skill groups (个性 / 正常携带 / 普攻), the bonus per
    // slot of the declared 技能放置顺序, and the bonus that makes a free [瞬发]
    // cast happen before the action-ending skill. All are overridable per run.
    const SKILL_PRIO = Object.assign({}, DEFAULT_SKILL_PRIORITY, opts.skillPriority || {});
    const MAX_INSTANT_CHAIN = 3;   // CHECK_STATE → DO_SKILL → MOVE_OR_IDLE …
    const tierRank = name => {
      const v = Number(SKILL_PRIO[name]);
      return Number.isFinite(v) ? v : 0;
    };
    const grid = prepareMap(map, data);
    const teams = {A: (opts.teams?.A || []).slice(0, 8), B: (opts.teams?.B || []).slice(0, 8)};
    const spawns = spawnCells(grid, teams.A.length, teams.B.length, opts.spawns);
    if (!spawns) return {error: '这张地图可站立的连通区域太小，放不下双方单位。'};
    const roll = rng(opts.seed ?? 1);
    const maxRounds = Math.max(1, Math.min(60, Number(opts.maxRounds) || 20));
    const K = Object.assign({CritBaseChance: 10, CritBaseDamage: 30, KnockbackImpactDamage: 20, FallDamage: 15,
                             FallDamageHeight: 3}, M?.constants || {});
    const hg = data.highGround || {up: 15, down: -10, minDiff: 2};
    const attrName = id => M?.enums?.attributes?.[id] || '';
    // `unmappedTiming` used to be declared but never written or exported.
    // Record every active_time the engine actually raises (unit + object)
    // so the coverage report can name timings that have client specs on the
    // participating units but were never dispatched in this battle.
    const cov = {executed: {}, skipped: {}, limits: {}, luaUnknown: {}, unmappedTiming: {},
                 firedTimings: new Set(),
                 conditions: {pass: 0, fail: 0, unknown: 0}};
    const bump = (o, k, n = 1) => { o[k] = (o[k] || 0) + n; };
    let events = [];
    const log = s => { events.push(s); };

    /* ---------- unit construction ---------- */
    const roster = new Map((data.roster || []).map(r => [r.key, r]));
    const units = [];
    // Client PLACE_ITEM / PLACE_UNIT / PLACE_TRAP / PLACE_UNIT_INHERIT_ATTR
    // put an interactive object on a tile (e.g. 乌莉娅「战斗开始时在正前方
    // 放置呆呆雪人」). Objects are tracked so the UI and later triggers can
    // see them; they are re-created on a new battle.
    const placed = [];
    // Client object definitions (props / trap / widget). `trap` rows carry
    // trigger_type 1=途经(Pass) 2=停留(Stay), trigger_skill and limit_count;
    // `props` rows carry hp, attackable / collidable / movable and their own
    // speciality_ids (e.g. 呆呆雪人 #516 spawns 蜜果 + 碎冰 each round).
    const objectDef = (kind, id) => {
      if (kind === 'PLACE_ITEM') return M?.props?.[id] || M?.widgets?.[id] || null;
      if (kind === 'PLACE_TRAP') return M?.traps?.[id] || null;
      return null;
    };
    const objectAt = (x, y, kind) => placed.find(o => o.alive && o.x === x && o.y === y && (!kind || o.kind === kind));
    // Client AOE 121「矩形3x3-中心向外-原点目标-无人地面有」: spawns go in
    // the ONE-ring around the SOURCE OBJECT (雪人), never around the caster.
    // `RANDOM_BLOCK` picks from this ring, honouring its
    // `block.temp_trap == nil` condition (no object on the tile).
    const ringCells = (o, radius = 1) => {
      const out = [];
      for (let dx = -radius; dx <= radius; dx++) for (let dy = -radius; dy <= radius; dy++) {
        if (!dx && !dy) continue;
        const c = grid.at(o.x + dx, o.y + dy);
        if (c && c.walk) out.push(c);
      }
      return out;
    };
    const freeObjectCell = c => c && c.walk &&
      !units.some(u => u.alive && u.x === c.x && u.y === c.y) &&
      !placed.some(o => o.alive && o.x === c.x && o.y === c.y);
    const setObjectRing = (o, rec) => {
      const a = rec?.area?.type === 'aoe' ? M?.aoe?.[rec.area.id] : null;
      const radius = a ? Math.max(1, Math.min(3, a.max || 1)) : 1;
      sim.objectRing = ringCells(o, radius).filter(freeObjectCell);
    };
    const objectHp = (def, owner) => Math.max(1, Math.round((def?.hp || 0) +
      (def?.hpAdd || 0) * (owner ? maxHpOf(owner) : 0)));
    // Object-owned effects: props carry their own speciality_ids, which fire at
    // their declared active_time (25 开局 / 29 回合结束 / 15 被普攻 / 12 死亡).
    function fireObject(at, ctx = {}) {
      cov.firedTimings.add(String(at));
      const savedOrigin = sim.objectOrigin;
      try {
      for (const o of placed.slice()) {
        if (!o.alive || !o.sp?.length) continue;
        sim.objectOrigin = o;
        for (const sid of o.sp) {
          const raw = M?.specs?.[sid];
          if (!raw || (AT_ALIAS[raw.at] || raw.at) !== at) continue;
          const inst = {spec: raw, sid, owner: o.owner, src: 'object:' + o.id,
                        name: o.name, object: o};
          if (STATIC_TYPES.has(raw.t) && raw.t !== 'GET_EXTRA_SKILL') continue;
          if (!cond(inst, Object.assign({}, ctx, {target: o.owner, object: o}))) continue;
          const fn = EFFECTS[raw.t];
          // Count a handler-less object effect as SKIPPED, not executed: it
          // used to be bumped before `fn` was resolved, which made the
          // coverage report claim 100% even for types with no implementation.
          if (!fn) { bump(cov.skipped, raw.t); continue; }
          bump(cov.executed, raw.t);
          spend(inst);
          {
            const chained = raw.t === 'CAST_SKILL' ? skillRec(raw.p[0]) : null;
            const savedRing = sim.objectRing;
            if (chained) setObjectRing(o, chained);
            const pass = Object.assign({}, ctx, {target: o.owner, object: o});
            sim.depth++;
            try { fn(inst, pass); } finally { sim.depth--; sim.objectRing = savedRing; }
          }
        }
      }
      } finally { sim.objectOrigin = savedOrigin; }
    }
    // Destroy an object: run death effects, then remove it from the board.
    function destroyObject(o, reason, ctx = {}) {
      if (!o || !o.alive) return;
      o.alive = false;
      log(`「${o.name}」${reason || '被摧毁'}（${o.x},${o.y}）`);
      bump(cov.executed, 'REMOVE_PROPS');
      const d = objectDef(o.kind, o.id);
      if (d?.ds) {
        const rec = skillRec(d.ds);
        if (rec) castSkill(o.owner, rec, grid.at(o.x, o.y), {free: true, sub: true, label: reason});
      }
      for (const sid of o.sp || []) {
        const raw = M?.specs?.[sid];
        if (!raw || (AT_ALIAS[raw.at] || raw.at) !== 12) continue;
        const inst = {spec: raw, sid, owner: o.owner, src: 'object:' + o.id, name: o.name, object: o};
        if (!cond(inst, Object.assign({}, ctx, {object: o}))) continue;
        const fn = EFFECTS[raw.t];
        if (fn) { bump(cov.executed, raw.t); sim.depth++; try { fn(inst, Object.assign({}, ctx, {object: o})); } finally { sim.depth--; } }
      }
      refreshAuras();
    }
    // Damage an attackable prop (雪人 has 300 HP + 7.5% of summoner max HP).
    // Trap / pick-up trigger. Client trap_trigger_type: 1 途经(Pass),
    // 2 停留(Stay). A Stay trigger fires when a unit ENDS its move on the tile;
    // a Pass trigger fires for every tile crossed. limit_count consumes the
    // object (蜜果 / 碎冰 are limit_count=1).
    function triggerObject(o, u, ctx = {}) {
      if (!o?.alive || !u?.alive || !o.triggerSkill) return;
      if (o.harmful && u.side === o.side) return;
      const rec = skillRec(o.triggerSkill);
      if (!rec) return;
      const caster = o.owner?.alive ? o.owner : u;
      const sub = Object.assign({}, ctx, {object: null, target: u, defender: u, attacker: caster});
      log(`${u.name} ${o.triggerType === 1 ? '途经' : '停留'}触发「${o.name}」（${o.triggerSkill}）`);
      fire(64, u, Object.assign({}, sub, {object: o, prop: o, skill: rec,
        blockCell: {x: o.x, y: o.y, h: grid.at(o.x, o.y)?.h || 0}, blockTrap: o}));
      bump(cov.executed, 'TRIGGER_TRAP');
      o.triggers++;
      // Run the trigger skill's effects with the picker as target and the
      // object's owner as caster (蜜果 is 乌莉娅 giving a heal + buffs).
      runSkillSpecs(rec, caster, 4, sub);
      runSkillSpecs(rec, caster, 3, sub);
      runSkillSpecs(rec, caster, 2, sub);
      fire(4, u, Object.assign({}, sub, {attacker: caster, skill: rec, noObjectChain: true}));
      if (o.limit > 0 && o.triggers >= o.limit) {
        o.alive = false;
        log(`「${o.name}」已用尽（${o.limit} 次）`);
      }
      // A pickup consumes ONLY the trap itself. In the client the snowman
      // keeps spawning items every round; it is removed exclusively by the
      // 「普攻摧毁雪人」/「雪人再造」 REMOVE_PROPS chains.
      if (o.parent?.alive) log(`  ↳ 母体「${o.parent.name}」仍在 (${o.parent.x},${o.parent.y})`);
      refreshAuras();
    }
    /* ---------- terrain / field status --------------------------------- */
    // Client `field_status` (30 overlays) + OPERATION / EXTRA_FIELD_STATUS /
    // FIELD_STATUS_SPREAD. The authoritative state is `cell.status`; the
    // `sim.fieldStatus` map carries the expiry round for the UI. Covering a
    // tile obeys the client's priority / irreplaceable / forbid_operation_ids.
    const FIELD_DEFS = M?.fieldStatusDefs || {};
    const FIELD_OPS = M?.fieldOperations || {};
    const NORMAL_FIELD = 1;
    const fieldDef = id => FIELD_DEFS[id] || null;
    // speciality.OPERATION.param0 is an operation id (operation.json), whose
    // `field_status` column is the resulting terrain. op 18「释放烟雾」→ 14,
    // op 13「恢复正常地面」→ 1 (clear).
    const operationField = op => {
      const row = FIELD_OPS[op];
      return row ? (Number(row.field) || NORMAL_FIELD) : Number(op);
    };
    // Does a field grant [隐身]? Derived entirely from client tables:
    // field_status.speciality_ids → AURA → buff → INVISIBLE / ABSOLUTE_INVISIBLE.
    // 烟雾 #14 → #10242 → buff 647 → #3335 INVISIBLE.
    const concealFieldId = id => {
      const d = fieldDef(id);
      if (!d?.sp?.length) return false;
      return d.sp.some(sid => {
        const q = M?.specs?.[sid];
        if (!q || q.t !== 'AURA') return false;
        return (M?.buffs?.[q.p?.[3]]?.sp || []).some(x =>
          M?.specs?.[x]?.t === 'INVISIBLE' || M?.specs?.[x]?.t === 'ABSOLUTE_INVISIBLE');
      });
    };
    // A skill that turns its landing tile into a concealing field (烟幕游击).
    const concealFieldOf = s => {
      for (const sid of s?.sp || []) {
        const q = M?.specs?.[sid];
        if (q?.t === 'OPERATION' || q?.t === 'EXTRA_FIELD_STATUS') {
          const id = operationField(q.p?.[0]);
          if (concealFieldId(id)) return id;
        }
      }
      return 0;
    };
    // Client 「特技-跳跃移动-瞬移」 #30951 p=[3,…]: the teleport walks a STRAIGHT
    // cardinal line of exactly p[0] blocks (getLineBlocks), not any manhattan-3
    // tile. 科尔 (9,6) → (6,6); a (7,7) diagonal landing is not a client block.
    const concealJumpSpec = s => {
      for (const sid of s?.sp || []) {
        const q = M?.specs?.[sid];
        if (q?.t === 'JUMP_MOVE') return q;
      }
      return null;
    };
    const hasInvisibleBuff = u => !!(u?.flags?.invisible || u?.flags?.absoluteInvisible) ||
      (u?.buffs || []).some(b => buffOn(b) && (b.def.sp || []).some(sid => {
        const t = M?.specs?.[sid]?.t;
        return t === 'INVISIBLE' || t === 'ABSOLUTE_INVISIBLE';
      }));
    // Client buff 647 / 8044: 「无法被敌人技能选中，但可被[范围伤害]、[环境伤害]
    // 波及，可被[强制选中]」. Only AUTO-SELECTION is blocked (AI targeting),
    // never AOE splash / alert / forced selection, which resolve via hitsUnit().
    const isInvisibleTo = (u, viewer) => {
      if (!u?.alive || !viewer || u.side === viewer.side) return false;
      if (viewer.flags?.ignoreInvisible) return false;
      if (unitSpecs(viewer).some(i => i.spec.t === 'IGNORE_INVISIBLE' && cond(i, {}))) return false;
      return hasInvisibleBuff(u);
    };
    // Foes the AI is allowed to pick: invisible enemies are not auto-selected.
    const visibleFoes = unit => units.filter(f => f.alive && f.side !== unit.side && !isInvisibleTo(f, unit));
    // Value of ending an action inside concealing terrain. Client 匿影独行 #9136
    // gives 伤害/穿透 +15% and heals 40% 物攻 at action end while in 烟雾; 隐身
    // stops enemies from selecting the unit. So any idle/cover decision should
    // prefer the smoke tile it is already standing on.
    const coverValue = (unit, cell) => {
      const id = cell?.status || NORMAL_FIELD;
      return id !== NORMAL_FIELD && concealFieldId(id) && !fieldImmune(unit, id) ? 1 : 0;
    };
    const opOf = fieldId => {
      const hit = Object.entries(FIELD_OPS).find(([, r]) => Number(r.field) === Number(fieldId));
      return hit ? Number(hit[0]) : fieldId;
    };
    function fieldImmune(u, id) {
      return unitSpecs(u).some(i => {
        const q = i.spec;
        if (q.t === 'IGNORE_FIELDSTATUS') {
          const ids = (q.p || []).filter(Boolean);
          return !ids.length || ids.some(x => Number(x) === Number(id));
        }
        if (q.t === 'NO_FIELDSTATUS_MOBILITY') {
          return Number(q.p?.[0]) === Number(id);
        }
        return false;
      });
    }
    function setFieldStatus(cell, id, turns, name, sid) {
      if (!cell || !Number.isFinite(cell.x) || !id) return false;
      if (Number(id) === NORMAL_FIELD) { clearFieldStatus(cell); bump(cov.executed, 'FIELD_STATUS_CLEAR'); return true; }
      if (!fieldDef(id)) return false;
      const cur = cell.status || NORMAL_FIELD;
      const from = fieldDef(cur), to = fieldDef(id);
      if (cur !== NORMAL_FIELD) {
        if (from?.irreplaceable) {
          log(`地块 (${cell.x},${cell.y}) 的「${from.name}」不可覆盖，操作「${to?.name || id}」被拒绝`);
          bump(cov.skipped, '地块不可覆盖'); return false;
        }
        if (from?.forbid?.some(x => Number(x) === Number(id))) {
          log(`地块 (${cell.x},${cell.y}) 的「${from.name}」禁止操作 #${id}，操作被拒绝`);
          bump(cov.skipped, '地块禁止该操作'); return false;
        }
        if ((from?.priority || 0) > (to?.priority || 0)) {
          log(`地块 (${cell.x},${cell.y}) 的「${from.name}」优先级 ${from.priority} 高于「${to?.name || id}」，操作被拒绝`);
          bump(cov.skipped, '地块优先级'); return false;
        }
      }
      cell.status = Number(id);
      sim.epoch++;                         // terrain-gated active_params (花田 / 烟雾) re-evaluate
      sim.fieldStatus.set(key(cell.x, cell.y), {x: cell.x, y: cell.y, id: Number(id),
        turns: Math.max(1, Number(turns) || 2), round: sim.round, name: name || to?.name || `地块 #${id}`,
        sid: sid || 0});
      log(`地块状态 OPERATION：(${cell.x},${cell.y}) 变为「${to?.name || id}」#${id}` +
          (to?.mobility ? `（每格额外消耗 ${to.mobility / 10} 移动力）` : '') +
          `，持续 ${Math.max(1, Number(turns) || 2)} 回合` +
          `（来源 ${name || id}，操作 #${opOf(id)}，p=[${[opOf(id), turns, 0, 0].join(', ')}]）`);
      bump(cov.executed, 'FIELD_STATUS_SET');
      return true;
    }
    function clearFieldStatus(cell) {
      const f = sim.fieldStatus.get(key(cell.x, cell.y));
      if (f) sim.fieldStatus.delete(key(cell.x, cell.y));
      if (cell && (cell.status || NORMAL_FIELD) !== NORMAL_FIELD) {
        log(`地块 (${cell.x},${cell.y}) 的「${fieldDef(cell.status)?.name || cell.status}」效果结束，恢复正常`);
        cell.status = NORMAL_FIELD;
        sim.epoch++;
      }
    }
    // Terrain movement surcharge. `mobility` is stored in tenths of a tile
    // (燃烧 5 = 0.5, 冰冻 10 = 1). IGNORE_FIELDSTATUS / NO_FIELDSTATUS_MOBILITY
    // are client speciality types keyed by the field id.
    function fieldStepCost(u, cell) {
      const id = cell?.status || NORMAL_FIELD;
      if (id === NORMAL_FIELD || !u) return 0;
      const d = fieldDef(id);
      if (!d?.mobility) return 0;
      return fieldImmune(u, id) ? 0 : d.mobility / 10;
    }
    // Tile-owned specialities: active_time 1 fires when a unit ENTERS /
    // passes the tile, 28 when the unit ENDS its action standing on it.
    function runFieldSpecs(u, cell, timing) {
      const id = cell?.status || NORMAL_FIELD;
      if (id === NORMAL_FIELD || !u?.alive || fieldImmune(u, id)) return;
      const d = fieldDef(id);
      if (!d?.sp?.length) return;
      for (const sid of d.sp) {
        const q = M?.specs?.[sid];
        if (!q || (AT_ALIAS[q.at] || q.at) !== timing || STATIC_TYPES.has(q.t)) continue;
        const inst = {spec: q, sid, owner: u, src: 'field:' + id, name: q.n || d.name,
                      field: d, fieldId: id};
        try {
          if (q.t === 'BUFF') {
            if (!cond(inst, {target: u, defender: u, attacker: u})) continue;
            addBuff(u, Number(q.p?.[0]) || 0, Number(q.p?.[1]) || 2, 1, u,
              {force: false, field: true});
            log(`地块「${d.name}」(${cell.x},${cell.y}) → ${tagOf(u)} 施加状态 #${q.p?.[0]}（特技 #${sid}）`);
            bump(cov.executed, 'FIELD_BUFF');
          } else {
            runSpec(inst, {target: u, defender: u, attacker: u, object: null});
          }
        } catch (e) { /* a terrain effect must never abort the action */ }
      }
    }
    function triggersOnPath(path, unit) {
      if (!path?.length) return;
      const seen = new Set();
      for (let i = 0; i < path.length; i++) {
        const c = path[i];
        if (i > 0) runFieldSpecs(unit, grid.at(c.x, c.y), 1);  // 途经 / 进入
        for (const o of placed) {
          if (!o.alive || o.kind !== 'PLACE_TRAP' || seen.has(o) || o.x !== c.x || o.y !== c.y) continue;
          if (!o.triggerType) continue;
          const stay = o.triggerType === 2;
          if (stay && i !== path.length - 1) continue;   // 停留: only final tile
          if (!stay && i === 0) continue;                // 途经: not the start tile
          seen.add(o);
          if (o.friend && unit.side === o.side) continue;
          triggerObject(o, unit);
        }
      }
    }
    function damageObject(o, amount, src) {
      if (!o?.alive || !o.attackable || amount <= 0) return 0;
      // Client prop 516「被己方攻击时，受到伤害降低100%」: friendlies cannot
      // chip it down; destruction comes from the explicit REMOVE_PROPS chain.
      const friendly = src && o.owner && src.side === o.owner.side;
      const reduction = friendly ? Math.min(100, Math.abs(
        (o.sp || []).map(id => M?.specs?.[id]).filter(s => s?.t === 'MODIFY_ATTRIBUTE' && s.at === 15)
          .reduce((a, s) => a + Math.abs(s.p[2] ?? s.p[1] ?? 0), 0))) : 0;
      amount = amount * (1 - reduction / 100);
      if (amount <= 0) return 0;
      const cut = Math.min(o.hp, Math.round(amount));
      o.hp -= cut;
      log(`${src?.name || '攻击'} 对「${o.name}」造成 ${cut} 伤害（剩余 ${o.hp}/${o.maxHp}）`);
      if (o.hp <= 0) destroyObject(o, '被击破');
      return cut;
    }
    function placeObject(owner, kind, id, spec, ctx) {
      const bits = Number(spec.p[3] || 1);
      const def = objectDef(kind, id);
      // Client JSON `sparam.cast_limit` / `complete_cast_limit` caps the
      // CONCURRENT count of this object id on the field: 「蜜果大喷射-生成1
      // 个蜜果」#27062 / 「天降陷阱…2个」#28106. Previously every trigger
      // spawned another one, so a 1-trap declaration accumulated up to 5
      // live copies (137 of 163 placements in the 192-game sweep were over
      // the client limit). `cast_limit` alone is the per-cast count and is
      // handled by the caller; `complete_cast_limit` is the field cap.
      const fieldCap = spec?.sj?.complete_cast_limit
        ? Math.max(1, Number(spec.sj.cast_limit) || 1) : 0;
      if (fieldCap) {
        const live = placed.filter(o => o.alive && o.kind === kind && o.id === id).length;
        if (live >= fieldCap) {
          bump(cov.limits, kind + '(同屏上限)');
          return null;
        }
      }
      // `direction_bits` uses the character's INITIAL facing for battle-start
      // placements (乌莉娅 雪人 / 伊南娜 王女卫兵 都在正前方). Sub-casts at
      // active_time 25 turn the caster toward a chosen target, so reading the
      // live dir here would put the object beside or behind them.
      const dir = ctx?.dir || (sim.round === 0 ? owner.initialDir : null) || owner.dir || [1, 0];
      // Object-originated effects (雪人 → 蜜果/碎冰) spawn in the ONE-RING
      // around the SOURCE OBJECT, per the client's 「在自身范围1圈内随机空地」.
      // Unit-cast PLACE_ITEM honours `direction_bits`: 「自己身前」 means the
      // tile the caster is facing, then the rest of its own 1-ring.
      const source = ctx?.object || sim.objectOrigin || null;
      const origin = source || owner;
      const free = freeObjectCell;
      const ring = ringCells(origin, 1).filter(free);
      let at = null;
      // Traps are ground overlays, not collidable props: the client places
      // them directly on the tile a unit already occupies.
      if (ctx?.placeOnUnit && ctx.target && Number.isFinite(ctx.target.x)) {
        const c = grid.at(ctx.target.x, ctx.target.y);
        if (c && c.walk && !objectAt(c.x, c.y)) return spawnAt(c);
      }
      if (sim.randomCell && ring.some(c => c.x === sim.randomCell.x && c.y === sim.randomCell.y)) {
        at = sim.randomCell;
      }
      sim.randomCell = null;
      if (!at && ctx?.target && spec.p[1] && free(grid.at(ctx.target.x, ctx.target.y))) {
        at = {x: ctx.target.x, y: ctx.target.y};
      }
      if (!at && !source && /direction_bits/.test(String(spec.s || ''))) {
        for (let d = 1; d <= 2 && !at; d++) {
          const c = grid.at(owner.x + dir[0] * d, owner.y + dir[1] * d);
          if (free(c)) at = c;
        }
      }
      if (!at && !source && ctx?.area?.length && /cast_limit|aoe/.test(String(spec.s || ''))) {
        const cells = ctx.area.filter(free);
        if (cells.length) at = cells[Math.floor(roll() * cells.length)];
      }
      if (!at) at = ring.find(c => free(grid.at(c.x, c.y))) || null;
      if (at) sim.objectRing = ring.filter(c => c.x !== at.x || c.y !== at.y);
      // Object spawns NEVER widen past the declared ring: the client only
      // places an item when there is an empty tile in that ring.
      if (!at && !source) at = ringCells(origin, 2).filter(free)[0] || null;
      if (!at) {
        log(`「${def?.n || spec.n || '物件'}」周围没有空地，本次不生成`);
        bump(cov.limits, kind + '(周围无空格)');
        return null;
      }
      function spawnAt(cell) {
      const at = cell;
      const o = {kind, id, x: at.x, y: at.y, owner, side: owner.side,
                 parent: ctx?.object || null,
                 name: def?.n || spec.n || (kind === 'PLACE_UNIT' ? `召唤物 #${id}` : `物件 #${id}`),
                 alive: true, bits, spec: spec.s || '', def: def || null,
                 label: kind === 'PLACE_TRAP' ? (def?.tt === 1 ? '途经触发' : '停留触发') : '',
                 triggerType: def?.tt || 0, triggerSkill: def?.ts || 0,
                 destroySkill: def?.ds || 0, harmful: !!def?.harm,
                 limit: def?.lim || 0, triggers: 0,
                 attackable: !!def?.atk, collidable: !!def?.col, movable: !!def?.mov,
                 sp: def?.sp || [], maxHp: objectHp(def, owner)};
      o.hp = o.maxHp;
      placed.push(o);
      bump(cov.executed, kind);
      log(`${owner.name} 在 (${at.x},${at.y}) 放置「${o.name}」${def?.n ? `（${kind === 'PLACE_TRAP' ? o.label : `HP ${o.hp}`}）` : ''}`);
      if (o.parent) log(`  ↳ 由「${o.parent.name}」(${o.parent.x},${o.parent.y}) 周围1圈生成`);
      return o;
      }
      const o = spawnAt(at);
      return o;
    }


    // Client PLACE_UNIT p[0] is a unit_npc id. `data/battle-mech.js` carries
    // the resolved 60-level template (stats / move / kit) for each of them.
    // Summons are full units: they have HP, their own skills and their own
    // action in the round's live-speed turn order.
    const summoned = [];
    const summonCasts = new Map();     // spec id -> casts this battle
    function spawnUnitFrom(owner, npcId, spec, ctx = {}) {
      const tpl = M?.summons?.[npcId];
      const specKey = ctx.sid || spec?.sid || ('tpl' + npcId);
      const casts = summonCasts.get(specKey) || 0;
      // Client JSON `sparam.cast_limit` / `total_limit`: 「以血筑国-召唤2个」
      // #24297 declares cast_limit=2, total_limit=0 (= no battle cap).
      // Previously the engine hard-coded 4 casts and a 4-concurrent roster
      // for EVERY summon, so a client-declared 1-use 分身 could be recast and
      // a 3-use 死士 chain was cut short. `complete_cast_limit` additionally
      // caps the CONCURRENT count at the per-cast limit.
      const sj = spec?.sj || {};
      const castLimit = Math.max(1, Number(sj.cast_limit) || 1);
      const totalLimit = Number(sj.total_limit) || 4;
      const aliveSame = summoned.filter(x => x.alive && x.npcId === npcId).length;
      // `unique` is derived at export time from the client's own REPLACE_SKILL
      // chain on the summoning skill (21460 星核·造物 → 21472 星核·位移):
      // 灵感星核 is unique, 虚空投影 is not.
      const cap = tpl?.unique ? 1 : (sj.complete_cast_limit ? castLimit : Math.min(4, totalLimit || 4));
      if (!tpl || summoned.length >= 12 || casts >= totalLimit || aliveSame >= cap || !owner?.alive) {
        bump(cov.limits, '召唤次数/同屏上限');
        return null;
      }
      summonCasts.set(specKey, casts + 1);
      const side = owner.side;
      // Client 「在目标[空地]召唤」: the selected ground tile IS the spawn
      // tile (菲娜塔「召唤·虚空投影」21721). Without this, the summon fanned
      // out from the CASTER's front tiles and ignored the chosen empty tile.
      let cell = null;
      const want = ctx?.emptyGround;
      if (want && Number.isFinite(want.x)) {
        const c = grid.at(want.x, want.y);
        const busy = units.some(v => v.alive && v.x === want.x && v.y === want.y) ||
          placed.some(o => o.alive && o.x === want.x && o.y === want.y);
        if (c && c.walk && !c.pit && !busy) cell = c;
        else { bump(cov.limits, '目标空地已被占用'); return null; }
      }
      if (!cell) cell = freeCellNear(owner, 2, ctx?.dir || owner.dir || owner.initialDir);
      if (!cell) { bump(cov.limits, '召唤物周围无空格'); return null; }
      const st = tpl.stats || {};
      const kit = tpl.kit || {};
      // Inherit attributes from the caster: client PLACE_UNIT_INHERIT_ATTR
      // specs in the same skill carry [attribute_id, percent, useBase].
      const inherit = {};
      for (const sid of (ctx.skill?.sp || spec.sp || [])) {
        const raw = M?.specs?.[sid];
        if (raw?.t !== 'PLACE_UNIT_INHERIT_ATTR') continue;
        const from = attrName(raw.p[0]);
        if (from && raw.p[1]) inherit[from] = {pct: raw.p[1], base: !!raw.p[2]};
      }
      const val = (key, attrKey) => {
        const own = inherit[attrKey];
        if (own) return Math.round((own.base ? attrRaw(owner, attrKey, null) : attr(owner, attrKey)) * own.pct / 100);
        return Number(st[key]) || 0;
      };
      const actives = [];
      for (const id of [kit.basic, ...(kit.actives || [])]) {
        const rec = skillRec(id);
        if (rec && !actives.some(x => x.id === rec.id)) actives.push(rec);
      }
      if (!actives.length) { bump(cov.limits, '召唤模板无可用技能'); return null; }
      actives[0].isNormal = true;
      const passiveSkills = [...(kit.reactive || []), ...(kit.leader || []),
                             ...(kit.feature || []), ...(kit.personality || [])]
        .map(id => skillRec(id)).filter(Boolean);
      const uid = side + 'S' + (summoned.length + 1);
      const u = {
        uid, side, key: 'summon-' + npcId, name: tpl.n, pageId: 0,
        prof: tpl.prof || 6, profName: tpl.profName || '', avatar: '',
        base: {HP_MAX: Math.max(1, val('hp', 'HP_MAX')), PHYSIC_ATTACK: val('patk', 'PHYSIC_ATTACK'),
               SPELL_ATTACK: val('matk', 'SPELL_ATTACK'), PHYSIC_DEFENCE: val('pdef', 'PHYSIC_DEFENCE'),
               SPELL_DEFENCE: val('mdef', 'SPELL_DEFENCE'), SPEED: Number(st.spd) || 100,
               // `?? 3` keeps the client's real mobility=0; `|| 3` silently
               // gave 静物 / 虚空投影 / 灵感星核 3 movement tiles.
               MOBILITY: Number(tpl.move?.mob ?? 3), JUMP: 0, TP_MAX: kit.tpMax ?? 5,
               CRIT_RATIO: 0, CRIT_DAMAGE: 0},
        move: {...(tpl.move || {mob: 3, up: 2, down: 2, type: 1})},
        hp: 0, tp: kit.tp ?? 3, skills: actives, passiveSkills, cd: {}, uses: {},
        x: cell.x, y: cell.y, dir: owner.dir.slice(), alive: true, order: units.length,
        buffs: [], limits: {}, ver: 0, custom: false, summon: true, npcId,
        summoner: owner.uid, unitId: tpl.kit?.unitId || 0, star: tpl.star || 1,
        noTurn: !!tpl.noTurn, noMove: !!tpl.noMove,
        faction: tpl.faction || 0, tags: (tpl.tags || []).slice(),
        stats: {...st}, maxHp: 0, flags: {},
        tally: {dealt: 0, taken: 0, healed: 0, kills: 0, actions: 0},
      };
      u.passive = collectPassives(u, passiveSkills, actives);
      u.hp = u.base.HP_MAX;
      // Client `unit.isCurrentSummoned` marks a summon created by THE CURRENT
      // CAST, so 「召唤后给全场刚召的死士…」specialities can select it. The
      // parent skill's at=4 chain runs in the same castSerial as PLACE_UNIT.
      u.summonedCast = sim.castSerial || 0;
      units.push(u); byId.set(uid, u); summoned.push(u); sim.newUnits.push(u);
      touch(u);
      bump(cov.executed, 'PLACE_UNIT(SUMMON)');
      log(`${owner.name} 召唤「${u.name}」于 (${u.x},${u.y})（HP ${u.hp} · 速度 ${u.base.SPEED}）`);
      return u;
    }
    const freeCellNear = (u, radius, front) => {
      const freeAt = (x, y) => {
        const c = grid.at(x, y);
        return c && c.walk && !units.some(v => v.alive && v.x === x && v.y === y) &&
          !placed.some(o => o.alive && o.x === x && o.y === y) ? c : null;
      };
      // Client summons appear on the tile directly in FRONT of the summoner;
      // only if that tile is blocked do they fan out to the rest of the ring.
      const [fx, fy] = front || u.dir || [1, 0];
      if (fx || fy) {
        for (let d = 1; d <= radius; d++) {
          const c = freeAt(u.x + fx * d, u.y + fy * d);
          if (c) return c;
        }
      }
      for (let d = 1; d <= radius; d++) {
        const cells = [...grid.cells.values()].filter(c => c.walk &&
          Math.max(Math.abs(c.x - u.x), Math.abs(c.y - u.y)) === d);
        const free = cells.find(c => freeAt(c.x, c.y));
        if (free) return free;
      }
      return null;
    };

    const skillRec = id => (M?.skills?.[id] ? Object.assign({id: Number(id)}, M.skills[id]) : null);
    // Build a unit's always-on speciality list. Besides the declared
    // reactive/leader/feature/personality skills, every EQUIPPED skill may
    // declare `skill.skill_attached_passive_id` — a hidden passive whose
    // specialities are live only while that skill is carried (123 client
    // skills; 伊凡「冰雪暴」20768 → 20777 with the 每回合首次 tp>=3 再行动
    // clause). They participate in unitSpecs()/fire() like any other passive.
    function collectPassives(u, passiveSkills, actives) {
      const out = [];
      const have = new Set();
      const add = (s, src, dedup = false) => {
        for (const sid of s.sp || []) {
          const spec = M?.specs?.[sid];
          // An attached passive may already sit on the unit through another
          // kit entry (a chain copy keeps its at-1 rows); never stack those
          // twice. Distinct passive skills sharing a row still stack.
          if (!spec || (dedup && have.has(sid))) continue;
          have.add(sid);
          out.push({spec, sid, owner: u, src, name: s.n, skill: s});
        }
      };
      for (const s of passiveSkills || []) if (s) add(s, 'passive');
      const seen = new Set();
      // skill_attached_passive_id hangs off ANY equipped skill — castable or
      // passive. 机动游击 #16420 is itself 「（被动）」 and its attached
      // passive 16430 is the 「拥有[协同响应]」 clause; scanning only the
      // castable bar dropped every response 伦伽勒·SP should have made.
      const parents = [...(actives || []), ...(passiveSkills || []).filter(s => s && !s.isChain)];
      for (const s of parents) {
        const ap2 = Number(s.ap2) || 0;
        if (!ap2 || seen.has(ap2)) continue;
        seen.add(ap2);
        const ps = skillRec(ap2);
        if (ps) add(ps, 'attached-passive', true);
      }
      return out;
    }
    // Client `skill.active_param` / `buff.active_param` are Lua expressions
    // gating whether the row may take effect at all.
    function activationOk(source, inst, ctx) {
      const lua = source?.ap;
      if (!lua) return true;
      const r = Lua.test(lua, luaEnv(inst || {spec: {t: 'ACTIVATION'}, owner: null, src: 'skill'}, ctx || {}));
      return r.ok === true;
    }
    // Client buff.active_param (409 buffs) is a LIVE switch, not an add-time
    // gate: the buff stays on the unit, but its specialities only work while
    // the predicate holds — 9025「速度减少200点，若没有[霜佑之印]则失效」,
    // 8504「拥有[狮王·自然守护]时无效」, ten 「站在[花田]上」 buffs,
    // 4920 士气高昂 (tp ≥ 7). The client exposes getBuffCountRegardlessActivation
    // next to getBuffCount for exactly this distinction. Evaluated read-only
    // with owner = target = the HOLDER and `buff` bound to this instance, so
    // 8801「魔术师灯柱存活标记」(buff:GetSourceEntity():GetSummoner() == target)
    // is live only on the core's own summoner. Memoised per state epoch
    // (buff add/remove, movement, terrain) and holder HP.
    // What an active_param can depend on, decided once per buff definition:
    // the WORLD (map / other units / terrain / summon & source relations /
    // whose turn it is) or only the holder's own state.
    const apWorld = new WeakMap();
    const apIsWorld = def => {
      let v = apWorld.get(def);
      if (v === undefined) {
        v = /map[:.]|getNeighbor|getDiamond|getAllBlocks|isFieldStatus|GetSummoner|GetSourceEntity|curUnit|block|Battle\./.test(String(def.ap));
        apWorld.set(def, v);
      }
      return v;
    };
    function buffOn(b) {
      const def = b?.def;
      if (!def?.ap) return true;
      const u = b.holder;
      if (!u) return true;
      const k = (apIsWorld(def) ? sim.epoch + '/' : '') + u.ver + ':' + u.hp + ':' + u.tp + ':' + u.x + ',' + u.y;
      if (b._apK === k) return b._apOn;
      b._apK = k;
      b._apOn = true;                      // provisional: breaks ap ↔ ap cycles
      const wasProbe = sim.probe;
      sim.probe = true;                    // read-only: no RNG, no coverage noise
      try {
        // Only `target` is bound: luaEnv derives `target` from attacker /
        // defender when they are present, which would make it the buff's
        // SOURCE (灵感星核) instead of the HOLDER (贝拉). In active_param the
        // holder is the subject — 「target:isFieldStatus(…FLOWER)」,
        // 「target:IsUnit(N)」, 「GetSummoner() == target」.
        const r = Lua.test(def.ap, luaEnv({spec: {t: 'ACTIVATION'}, owner: u, src: 'buff', name: def.n, buff: b},
          {target: u}, true));
        b._apOn = r.ok === true;
      } catch { b._apOn = false; }
      finally { sim.probe = wasProbe; }
      return b._apOn;
    }
    const apSig = u => {
      const k = sim.epoch + ':' + u.ver + ':' + u.hp + ':' + u.tp;
      if (u._apSigK === k) return u._apSigV;
      let s = '';
      for (const b of u.buffs) if (b.def?.ap) s += buffOn(b) ? '1' : '0';
      u._apSigK = k; u._apSigV = s;
      return s;
    };
    // Client skill chains (attached passive / follow-up / cast / overwrite) are
    // effects attached to the fighter, never castable actives.
    const kitIds = kit => ({
      // SKILL_GROUP / TACTICS_SKILL_GROUP options are real castable skills
      // offered by 抉择 skills in the client (item 6).
      actives: [kit.basic, ...(kit.actives || []), ...(kit.initial || []), ...(kit.choice || [])],
      passives: [...(kit.reactive || []), ...(kit.leader || []), ...(kit.feature || []),
                 ...(kit.personality || []), ...(kit.chain || []), ...(kit.bossSequence || []),
                 ...(kit.module || [])],
      derived: [...(kit.derived || [])],
    });

    function buildKit(f, mode) {
      const kit = f.kit;
      const actives = [], passives = [];
      const pushActive = s => { if (s && !actives.some(a => a.id === s.id)) actives.push(s); };
      // Chain skills (skill_cast_id / idskill_follow / ...) are triggered by
      // their parent skill in the client, NOT permanently equipped on the unit.
      // Only their passive (active_time 1) effects may sit on the unit; every
      // timing-based effect would otherwise fire on unrelated attacks.
      const chainIds = new Set([...((kit && kit.chain) || []), ...((kit && kit.bossSequence) || [])]);
      const derivedIds = new Set((kit && kit.derived) || []);
      const choiceIds = new Set((kit && kit.choice) || []);
      const roleOf = new Map();
      for (const [role, key] of [['reaction', 'reactive'], ['leader', 'leader'],
                                 ['feature', 'feature'], ['personality', 'personality'],
                                 ['chain', 'chain'], ['boss', 'bossSequence'], ['module', 'module']])
        for (const id of (kit && kit[key]) || []) roleOf.set(Number(id), role);
      const pushPassive = id => {
        const rec = skillRec(id);
        if (!rec) return;
        // Keep the client role / description so the character panel can list
        // 个性 (personality) effects with their own text and specialities.
        const tagged = Object.assign({}, rec, {role: roleOf.get(Number(id)) || 'passive',
                                               desc: rec.desc || ''});
        // An ACTIVE skill (skill.type 1) whose skill_type is not castable
        // (e.g. 4 = 抉择/战术) carries its own timed effects (active_time 3/4).
        // Those belong to that skill's own cast, not to the unit: registering
        // them as unit passives made SP科尔's 「在烟雾里呆着不动」 buff fire at
        // battle start (mobility fixed to 0). Keep only always-on (at 1) specs.
        // Chain / derived skills are triggered by their parent skill; only
        // their always-on (at 1) effects belong on the unit.
        const timedActive = chainIds.has(Number(id)) || derivedIds.has(Number(id));
        if (chainIds.has(Number(id)) || timedActive || derivedIds.has(Number(id))) {
          const staticSp = (rec.sp || []).filter(sid => (AT_ALIAS[M.specs[sid]?.at] || M.specs[sid]?.at) === 1);
          if (!staticSp.length) return;
          passives.push(Object.assign({}, tagged, {sp: staticSp, isChain: true}));
        } else passives.push(tagged);
      };
      if (f.edited || !kit || !M) {
        for (const s of f.skills) {
          const rec = M && typeof s.id === 'number' ? skillRec(s.id) : null;
          if (rec) {
            // Honour on-page edits while keeping the client effects.
            Object.assign(rec, {n: s.name || rec.n, df: s.factor ?? rec.df, rmin: s.rangeMin ?? rec.rmin,
                                rmax: s.rangeMax ?? rec.rmax, cd: s.cooldown ?? rec.cd, ord: s.order ?? rec.ord});
            if (s.heal) rec.dt = 3;
            pushActive(rec);
          } else pushActive(legacySkill(s));
        }
        if (kit && M) for (const id of kitIds(kit).passives) pushPassive(id);
        return {actives, passives};
      }
      const side = mode === 'right' ? 2 : 1;
      const ranks = (kit.ranks || []).filter(r => r[1] === side);
      const upgrade = mode !== 'basic' ? ranks.find(r => r[0] === 9) : null;
      const ids = [upgrade ? upgrade[2] : kit.basic, ...(kit.actives || []), ...(kit.initial || []),
                   ...(kit.choice || []),
                   ...(mode === 'basic' ? [] : ranks.filter(r => r[0] !== 9).map(r => r[2]))];
      const seen = new Set();
      // The roster sometimes lists BOTH a real skill and its 「初始可用次数1」
      // clone under the same name (法卡尔 16335 + 23014 强击姿态, 科尔 22016 +
      // 23012 潜袭). The clone has no description / damage / swap plan and is
      // just the client's "one extra cast" marker; offering both made the AI
      // burn its whole [瞬发] chain re-casting the same stance. Keep the
      // canonical row (richer spec list, or one with a swap/follow-up plan).
      const actRecs = ids.map(id => ({id, rec: id ? skillRec(id) : null})).filter(x => x.rec);
      const redundant = new Set();
      for (const a of actRecs) for (const b of actRecs) {
        if (a === b || a.rec.n !== b.rec.n) continue;
        const weight = r => (r.sp || []).length * 2 + (r.df > 0 ? 4 : 0) +
          (r.scid ? 3 : 0) + (M?.skillPlans?.[r.id]?.swapTo ? 3 : 0) + String(r.desc || '').length / 100;
        if (weight(a.rec) < weight(b.rec) || (weight(a.rec) === weight(b.rec) && a.id > b.id)) {
          redundant.add(a.id); break;
        }
      }
      for (const {id, rec} of actRecs) {
        if (!id || seen.has(id) || redundant.has(id)) continue;
        seen.add(id);
        const isChoice = choiceIds.has(Number(id));
        // A 抉择 / 战术 skill (SKILL_GROUP, TACTICS_SKILL_GROUP) is a
        // pre-battle choice: its options are already exported into kit.choice.
        // Casting the group itself as an action wastes a whole turn.
        const groupSkill = (rec.sp || []).some(sid => {
          const st = M?.specs?.[sid]?.t;
          return st === 'SKILL_GROUP' || st === 'TACTICS_SKILL_GROUP';
        });
        if (groupSkill) { rec.isChoiceGroup = true; passives.push(rec); continue; }
        if (castable(rec, isChoice)) { if (id === (upgrade ? upgrade[2] : kit.basic)) rec.isNormal = true; pushActive(rec); }
        else passives.push(rec);
      }
      if (!actives.some(a => a.isNormal) && actives[0]) actives[0].isNormal = true;
      for (const id of kitIds(kit).passives) {
        if (seen.has(id)) continue;
        seen.add(id);
        pushPassive(id);
      }
      return {actives, passives};
    }

    for (const side of ['A', 'B']) {
      (teams[side] || []).forEach((entry, i) => {
        const cell = spawns[side][i];
        if (!cell) return;
        const f = normalizeFighter(entry, roster);
        if (!f) return;
        const r = f.template;
        const {actives, passives} = buildKit(f, opts.mode || 'left');
        if (!actives.length) return;
        // Client skill groups: 普攻 is the basic (or rank-9 upgraded basic),
        // 个性技能 are the castable skills granted by the unit's personality,
        // everything else is a 正常携带技能 and follows its slot order.
        const personalityIds = new Set(((f.kit && f.kit.personality) || []).map(Number));
        for (const [id, role] of Object.entries(f.skillRoles || {}))
          if (/个性/.test(String(role))) personalityIds.add(Number(id));
        // Client skill.class_type: 1 = 普攻, 7 = 个性 (verified against the
        // exported allSkills[].role). Most 个性 skills are passives and never
        // reach the skill bar, but any castable one gets its own priority.
        const skillTier = new Map(actives.map(s => [Number(s.id),
          s.isNormal ? 'basic'
            : (personalityIds.has(Number(s.id)) || Number(s.ct) === 7) ? 'personality' : 'carried']));
        const instantIds = new Set(actives.filter(isInstant).map(s => Number(s.id)));
        // 技能放置顺序: client `skill_orders` (unit_npc.skill_ids). The page's
        // fighter editor can reorder it (entry.slotOrder / kit.skillOrder).
        // Declared castable ids first, then any active missing from the
        // declaration in the client kit's own assembly order.
        const activeIds = actives.map(s => Number(s.id));
        const declared = ((f.slotOrder || (f.kit && f.kit.skillOrder) || [])).map(Number);
        const slotOrder = [...declared.filter(id => activeIds.includes(id)),
                           ...activeIds.filter(id => !declared.includes(id))];
        const st = r.stats || {};
        const u = {
          uid: side + (i + 1), side, key: r.key, name: r.name, pageId: r.pageId,
          prof: Number(r.prof) || 6, profName: r.profName, avatar: r.avatar,
          base: {HP_MAX: Math.max(1, Math.round(Number(st.hp) || 1)), PHYSIC_ATTACK: Number(st.patk) || 0,
                 SPELL_ATTACK: Number(st.matk) || 0, PHYSIC_DEFENCE: Number(st.pdef) || 0, SPELL_DEFENCE: Number(st.mdef) || 0,
                 SPEED: Number(st.spd) || 100, MOBILITY: Number(r.move?.mob) || 3, JUMP: 0,
                 TP_MAX: Number(f.kit?.tpMax) || 5, CRIT_RATIO: Number(st.critRatio) || 0, CRIT_DAMAGE: Number(st.critDamage) || 0},
          move: {...(r.move || {})}, hp: Math.max(1, Math.round(Number(st.hp) || 1)), tp: Number(f.kit?.tp ?? 3) || 0,
          skills: actives, passiveSkills: passives, skillTier, instantIds, slotOrder,
          cd: {}, uses: {}, x: cell.x, y: cell.y,
          personalityIds: ((f.kit && f.kit.personality) || []).slice(),
          dir: (spawns.facing?.[side]?.[i] || (side === 'A' ? [1, 0] : [-1, 0])).slice(),
          initialDir: (spawns.facing?.[side]?.[i] || (side === 'A' ? [1, 0] : [-1, 0])).slice(),
          alive: true, order: units.length,
          buffs: [], limits: {}, ver: 0, custom: f.custom, statLevel: f.statLevel, unitId: f.kit?.unitId || 0,
          star: Number(entry?.star) || 5, tags: f.kit?.tags || [], npcId: Number(entry?.npcId) || 0,
          ai: {
            byOrder: !!(f.kit && f.kit.aiByOrder),
            sorted: !!(f.kit && f.kit.aiSorted),
            bossMode: Number(f.kit?.bossMode) || 0,
            sequence: (f.kit?.bossSequence || []).slice(),
            order: (f.kit?.skillOrder || []).slice(),
            cursor: 0,
          },
          stats: {...st}, maxHp: 0, flags: {}, tally: {dealt: 0, taken: 0, healed: 0, kills: 0, actions: 0},
        };
        u.passive = collectPassives(u, passives, actives);
        for (const s of actives) if (s.pcd > 0) u.cd[s.id] = s.pcd;
        units.push(u);
      });
    }
    if (!units.some(u => u.side === 'A') || !units.some(u => u.side === 'B')) return {error: '双方都至少需要 1 名角色。'};
    const byId = new Map(units.map(u => [u.uid, u]));
    const enemiesOf = u => units.filter(o => o.alive && o.side !== u.side);
    const alliesOf = u => units.filter(o => o.alive && o.side === u.side);

    /* ---------- attributes ---------- */
    // Uses the last computed max HP (u._mhp) so it never recurses into attr().
    const hpState = u => {
      const pct = u.hp / Math.max(1, u._mhp || u.base.HP_MAX) * 100;
      const inj = M?.hpAttenuation?.find(r => /injur/i.test(r.type));
      const dying = M?.hpAttenuation?.find(r => /dying/i.test(r.type));
      return pct <= 0 ? 4 : pct <= (dying?.max ?? 30) ? 3 : pct <= (inj?.max ?? 70) ? 2 : 1;
    };
    const touch = u => { if (u) u.ver++; sim.epoch++; };
    function unitSpecs(u) {
      const sig = apSig(u);
      if (u._specVer === u.ver && u._hpState === hpState(u) && u._apSig === sig) return u._specs;
      const out = u.flags.forget ? [] : u.passive.slice();
      for (const b of u.buffs) {
        // An inactive buff (active_param false) keeps ONLY its own lifecycle
        // rows (REMOVE: 「单位开始行动时移除父级buff」, 「触发后移除」), so it
        // still expires on schedule instead of lingering as a dormant zombie.
        const on = buffOn(b);
        for (const sid of b.def.sp) {
          const spec = M.specs[sid];
          if (!spec || (!on && spec.t !== 'REMOVE')) continue;
          out.push({spec, sid, owner: u, src: 'buff', buff: b, name: b.def.n});
        }
      }
      const st = hpState(u);
      if (M?.hpAttenuation && st >= 2 && st <= 3 && !hasType(out, 'IGNORE_HP_ATTENUATION')) {
        const row = M.hpAttenuation.find(r => r.type === (st === 2 ? 'Injured' : 'Dying'));
        for (const sid of row?.sp || []) if (M.specs[sid]) out.push({spec: M.specs[sid], sid, owner: u, src: 'hp', name: row.name});
      }
      u._specs = out; u._specVer = u.ver; u._hpState = st; u._apSig = sig;
      return out;
    }
    const hasType = (list, t) => list.some(i => i.spec.t === t);

    function cond(inst, ctx, probe = false) {
      const src = inst.spec.c;
      if (!src) return true;
      // probe = read-only inspection for the character panel: never consume the
      // battle RNG (map:Random) and never pollute coverage statistics. Any
      // nested attr()/luaEnv() call made while inspecting inherits the flag.
      const readonly = probe || sim.probe;
      const wasProbe = sim.probe;
      if (readonly) sim.probe = true;
      let r;
      try { r = Lua.test(src, luaEnv(inst, ctx, readonly)); }
      finally { sim.probe = wasProbe; }
      if (r.unknown) {
        if (!readonly) { cov.conditions.unknown++; bump(cov.luaUnknown, r.unknown); }
        return false;
      }
      if (!readonly) cov.conditions[r.ok ? 'pass' : 'fail']++;
      return r.ok;
    }
    // `speciality.skill_active_param` (client column) is a SECOND Lua
    // predicate, evaluated against the SKILL currently being resolved:
    //   #5210「技能最大射程+2（远程）」→ skill:isRangeTag(RANGED)
    //   #596                            → return skill.isNormal
    //   #1922                           → skill:hasTag("Charge") or ...
    // Without this, every SKILL_RANGE buff applied to every skill, which is
    // why 近战「破晓的决意」(rt=MELEE) and the 1-3 格 teleport「烟幕游击」
    // both wrongly gained +2 range from the 突变 environment buff.
    function skillCondOk(inst, skill, ctx = {}) {
      const src = inst?.spec?.sap;
      if (!src) return true;
      if (!skill || !M) return false;
      const c = Object.assign({attacker: inst.owner, skill}, ctx);
      const wasProbe = sim.probe;
      let r;
      try {
        sim.probe = true;                 // read-only: never consume battle RNG
        r = Lua.test(src, luaEnv(inst, c, true));
      } catch { return false; }
      finally { sim.probe = wasProbe; }
      return !r.unknown && !!r.ok;
    }

    // Attribute modifiers grouped by attribute, rebuilt only when the unit's
    // effect list changes — attr() then touches just the few relevant entries.
    function indexMods(list) {
      const idx = new Map();
      const add = (A, inst) => { let a = idx.get(A); if (!a) idx.set(A, a = []); a.push(inst); };
      for (const inst of list) {
        const s = inst.spec;
        if (s.t === 'MODIFY_ATTRIBUTE') { const n = attrName(s.p[0]); for (const A of COMPOSITE[n] || [n]) add(A, inst); }
        else if (s.t === 'MOVE_ATTACK') { const n = attrName(s.p[0]); for (const A of COMPOSITE[n] || [n]) add(A, inst); }
        else if (s.t === 'CONVERT_ATTRIBUTE' || s.t === 'BUFF_STACK_MODIFY_ATTRIBUTE') add(attrName(s.p[1]), inst);
        else if (s.t === 'SPECIFY_ATTRIBUTE_VALUE' || s.t === 'HIT_COUNT_MODIFY_ATTRIBUTE' || s.t === 'DISTANCE_MODIFY_ATTRIBUTE') {
          const n = attrName(s.p[0]); for (const A of COMPOSITE[n] || [n]) add(A, inst);
        }
      }
      return idx;
    }
    function modIndex(u) {
      // Keyed on the unitSpecs() list itself: that list already tracks the
      // buff version, HP stage AND each buff's live active_param state, so a
      // 速度4 that switches on when 霜佑之印 arrives changes SPEED at once.
      const list = unitSpecs(u);
      if (u._modList === list && u._mods) return u._mods;
      u._mods = indexMods(list); u._modList = list;
      return u._mods;
    }
    const skillMods = (s, u) => s._mods || (s._mods = indexMods((s.sp || []).map(sid => M?.specs?.[sid])
      .filter(sp => sp && (sp.at === 1 || sp.at === 2)).map(spec => ({spec, owner: null, src: 'skill', name: s.n}))));
    const restrainMods = new Map();
    function restrainIndex(ids) {
      const k = ids.join(',');
      if (!restrainMods.has(k)) restrainMods.set(k, indexMods(ids.map(sid => M?.specs?.[sid]).filter(Boolean)
        .map(spec => ({spec, owner: null, src: 'restrain', name: '职业克制'}))));
      return restrainMods.get(k);
    }

    // ctx (optional) is the combat context; timing-2/15/31 modifiers and the
    // used skill's own modifiers only apply inside it.
    const staticCache = new Map();
    let cacheEpoch = -1;
    function attr(u, A, ctx) {
      if (!ctx) {
        if (cacheEpoch !== sim.epoch) { staticCache.clear(); cacheEpoch = sim.epoch; }
        const ck = u.uid + '|' + A;
        if (staticCache.has(ck)) return staticCache.get(ck);
        const v = attrRaw(u, A, null);
        staticCache.set(ck, v);
        return v;
      }
      return attrRaw(u, A, ctx);
    }
    // Base value = entered stats + 开局 (PREWAR_*) modifiers, kept apart so the
    // original / edited stats are never overwritten.
    const baseOf = (u, A) => {
      const pw = u.prewar?.[A];
      const b = u.base[A] || 0;
      return pw ? (b + pw.flat) * Math.max(0.1, 1 + pw.pct / 100) : b;
    };
    const computing = new Set();
    // Attributes that cannot go below zero. 罗格妮达「白金狮子」#27211
    // PREWAR TP_MAX −99 means "no energy bar" (she spends 狮血), not −94 max
    // energy; 定身 MOBILITY −99 means "cannot move", not −94 tiles.
    const NON_NEGATIVE = new Set(['TP_MAX', 'MOBILITY']);
    function attrRaw(u, A, ctx) {
      const base = baseOf(u, A);
      const guardKey = u.uid + '|' + A;
      if (computing.has(guardKey)) return NON_NEGATIVE.has(A) ? Math.max(0, base) : base;
      computing.add(guardKey);
      try {
        const v = attrCompute(u, A, ctx, base);
        return NON_NEGATIVE.has(A) ? Math.max(0, v) : v;
      } finally { computing.delete(guardKey); }
    }
    // `collect` (optional) receives EVERY individual percentage modifier that
    // passed the same timing / condition filter as the aggregate. The official
    // damage formula (SoC伤害计算器v1.5「伤害计算公式」A11, 主表 F23) requires
    // 受到伤害区 to be a PRODUCT of per-source (1+x) factors, not one factor
    // built from their SUM. Without this the engine could not reconstruct the
    // individual rows.
    function attrCompute(u, A, ctx, base, collect) {
      let flat = 0, pct = 0, auraFlat = 0, auraPct = 0, fixed = null, converted = 0;
      const push = (v, inst, s) => {
        if (collect && v) collect.push({attr: A, pct: v,
          name: inst.name || s.n || A, src: inst.src || 'buff', sid: inst.sid || 0});
      };
      const consider = (raw, owner) => {
        const inst = raw.spec?.dp ? Object.assign({}, raw, {spec: resolvedSpec(raw, ctx)}) : raw;
        const s = inst.spec;
        const at = AT_ALIAS[s.at] || s.at;
        if (at !== 1) {
          if (!ctx) return;
          if (at === 2) { if (owner !== ctx.attacker && owner !== ctx.defender) return; }
          else if (at === 15 || at === 16) { if (owner !== ctx.defender) return; }
          else if (at === 31) { if (!ctx.counter || owner !== ctx.attacker) return; }
          else return;
        }
        const ci = inst.owner ? inst : Object.assign({}, inst, {owner});
        if (!cond(ci, ctx)) return;
        if (s.t === 'CONVERT_ATTRIBUTE') {
          // The client converts from the CURRENT (fully modified) source stat,
          // and adds the result to the TOTAL of the destination stat — after
          // the percentage layer, not into its base. attrRaw()'s `computing`
          // guard breaks reciprocal conversion cycles.
          converted += attrRaw(u, attrName(s.p[0]), ctx) * s.p[2] / 100;
          return;
        }
        if (s.t === 'SPECIFY_ATTRIBUTE_VALUE') { fixed = s.p[1]; return; }
        if (s.t === 'MOVE_ATTACK') {
          // Client MOVE_ATTACK p = [attribute, base%, perMovedTile%, cap%].
          // 「重心不稳」 28136 = [62, 0, -20, -100]: each tile walked before
          // attacking multiplies final damage by -20%, capped at -100%.
          // Previously this type only set an unconsumed flag, so every one of
          // the 21 MOVE_ATTACK specialities was a no-op.
          const steps = Math.max(0, Number(u.flags?.moveSteps || u.flags?.spentMove) || 0);
          let v = (s.p[1] || 0) + (s.p[2] || 0) * steps;
          const cap = Number(s.p[3]) || 0;
          if (cap && (s.p[2] < 0 ? v < cap : v > cap)) v = cap;
          pct += v; push(v, inst, s);
          return;
        }
        if (s.t === 'BUFF_STACK_MODIFY_ATTRIBUTE') {
          const holder = s.s && ctx ? (owner === ctx.attacker ? ctx.defender : ctx.attacker) || u : u;
          const n = holder ? buffCount(holder, b => b.id === s.p[0]) : 0;
          const v = Math.min(s.p[3] || Infinity, n * s.p[2]);
          pct += v; push(v, inst, s);
          return;
        }
        if (s.t === 'HIT_COUNT_MODIFY_ATTRIBUTE') {
          if (!ctx?.targets) return;
          const n = Math.max(0, ctx.targets.length - (s.s ? 1 : 0));
          const rawv = s.p[1] + s.p[2] * n;
          const v = s.p[2] < 0 ? Math.max(s.p[3], rawv) : Math.min(s.p[3] || Infinity, rawv);
          pct += v; push(v, inst, s);
          return;
        }
        if (s.t === 'DISTANCE_MODIFY_ATTRIBUTE') {
          if (!ctx?.attacker || !ctx.defender) return;
          const rawv = s.p[1] * Math.max(0, manhattan(ctx.attacker, ctx.defender) - (s.p[3] || 0));
          const v = s.p[2] ? Math.min(s.p[2], rawv) : rawv;
          pct += v; push(v, inst, s);
          return;
        }
        // Client JSON `sparam.ignore_buff_stack_count`: the modifier is
        // FLAT, not multiplied by the buff's stack count (喜悦值 / 毁灭预言
        // / 「回味甘甜-施加者物攻治疗30（不受层数影响）」…).
        const stacks = s.sj?.ignore_buff_stack_count ? 1 : (inst.buff?.stacks || 1);
        if (inst.buff?.aura) { auraFlat = Math.max(auraFlat, s.p[1] * stacks); auraPct = Math.max(auraPct, s.p[2] * stacks); }
        else { flat += s.p[1] * stacks; pct += s.p[2] * stacks; push(s.p[2] * stacks, inst, s); }
      };
      for (const inst of modIndex(u).get(A) || []) consider(inst, u);
      if (ctx && ctx.attacker === u && ctx.skill) {
        for (const inst of skillMods(ctx.skill, u).get(A) || []) consider(inst, u);
        if (ctx.restrain?.length) for (const inst of restrainIndex(ctx.restrain).get(A) || []) consider(inst, u);
      }
      flat += auraFlat; pct += auraPct;
      const core = fixed !== null ? fixed : PRIMARY.has(A)
        ? (base + flat) * Math.max(0.1, 1 + pct / 100) : base + flat + pct;
      return core + converted;
    }
    const maxHpOf = u => { const v = Math.max(1, Math.round(attr(u, 'HP_MAX'))); u._mhp = v; return v; };

    // Inspectable attribute breakdown: mirrors attrCompute() but returns every
    // contributing effect instead of just the final number. Used by the live
    // character panel, which shows each stat's formula at any replay step.
    const PANEL_ATTRS = [
      ['HP_MAX', '最大生命'], ['PHYSIC_ATTACK', '物攻'], ['SPELL_ATTACK', '魔攻'],
      ['PHYSIC_DEFENCE', '物防'], ['SPELL_DEFENCE', '魔防'], ['SPEED', '速度'],
      ['MOBILITY', '移动力'], ['TP_MAX', '能量上限'], ['CRIT_RATIO', '暴击率'],
      ['CRIT_DAMAGE', '暴击伤害'], ['DAMAGE', '造成伤害'], ['BEDAMAGE', '受到伤害'],
      ['DEFENCE_IGNORE', '无视防御'], ['HEAL_FACTOR', '治疗加成'], ['BE_HEAL_FACTOR', '受治疗'],
    ];
    const SRC_LABEL = {passive: '被动/个性', buff: '状态', hp: '受伤衰减', skill: '技能', restrain: '克制', weather: '天气'};
    function attrBreakdown(u, A) {
      const critBase = A === 'CRIT_RATIO' ? K.CritBaseChance : A === 'CRIT_DAMAGE' ? K.CritBaseDamage : 0;
      const base = (u.base[A] || 0) + critBase;
      const pw = u.prewar?.[A];
      const prewar = pw ? (base + pw.flat) * Math.max(0.1, 1 + pw.pct / 100) : base;
      const parts = [];
      let flat = 0, pct = 0, fixed = null, converted = 0;
      const record = (raw, owner) => {
        const inst = raw.spec?.dp ? Object.assign({}, raw, {spec: resolvedSpec(raw, null)}) : raw;
        const s = inst.spec;
        const at = AT_ALIAS[s.at] || s.at;
        // Attack-time (active_time 2) self modifiers such as 「暴击转化」 are
        // real, resolved client effects. Show them in the panel with their
        // dynamic_param value instead of silently dropping them.
        const conditional = at === 2;
        if (at !== 1 && !conditional) return;
        const ci = inst.owner ? inst : Object.assign({}, inst, {owner});
        const ok = cond(ci, conditional ? {attacker: u, defender: null} : null, true);
        const stacks = inst.buff?.stacks || 1;
        const row = {n: inst.name || SRC_LABEL[inst.src] || inst.src || '效果',
                     src: inst.src || 'passive', t: s.t, at,
                     buff: inst.buff?.id || 0, aura: !!inst.buff?.aura, stacks, ok,
                     skillId: inst.skill?.id || 0, skillName: inst.skill?.n || '',
                     specId: inst.sid || 0};
        if (s.t === 'CONVERT_ATTRIBUTE') {
          const from = attrRaw(u, attrName(s.p[0]), null);
          row.flat = Math.round(from * s.p[2] / 100 * 100) / 100;
          row.converted = true;
          row.note = `实时 ${attrName(s.p[0])} ${Math.round(from)} × ${s.p[2]}%，加在总值上`;
        } else if (s.t === 'SPECIFY_ATTRIBUTE_VALUE') {
          row.fixed = s.p[1]; row.note = `固定为 ${s.p[1]}`;
        } else if (s.t === 'BUFF_STACK_MODIFY_ATTRIBUTE') {
          const n = buffCount(u, b => b.id === s.p[0]);
          row.pct = Math.min(s.p[3] || Infinity, n * s.p[2]);
          row.note = `${n} 层 × ${s.p[2]}%（上限 ${s.p[3] || '∞'}）`;
        } else if (s.t === 'HIT_COUNT_MODIFY_ATTRIBUTE' || s.t === 'DISTANCE_MODIFY_ATTRIBUTE') {
          row.note = '仅攻击结算时生效'; row.conditional = true;
        } else {
          row.flat = (s.p[1] || 0) * stacks;
          row.pct = (s.p[2] || 0) * stacks;
        }
        parts.push(row);
        if (!ok) return;
        if (row.fixed !== undefined) fixed = row.fixed;
        if (s.t === 'CONVERT_ATTRIBUTE') converted += row.flat;
        else if (row.conditional) { /* attack-time only */ }
        else if (s.t === 'BUFF_STACK_MODIFY_ATTRIBUTE') pct += row.pct;
        else { flat += row.flat || 0; pct += row.pct || 0; }
      };
      for (const inst of modIndex(u).get(A) || []) record(inst, u);
      if (critBase) parts.unshift({n: '客户端常量 · ' + (A === 'CRIT_RATIO' ? 'CritBaseChance' : 'CritBaseDamage'),
        src: 'constant', t: 'CONST_PARAM', at: 1, flat: 0, pct: 0, ok: true, stacks: 1,
        // Already included in `base`; listed as a source only, never counted twice.
        note: `const_param 基础值 ${critBase}（已计入基础值）`, buff: 0, aura: false});
      // Converted amounts are displayed but excluded from `flat`, because the
      // client adds them to the final total, not to the pre-percentage base.
      flat = parts.filter(p => p.ok && !p.conditional && !p.converted).reduce((a, p) => a + (p.flat || 0), 0);
      pct = parts.filter(p => p.ok && !p.conditional).reduce((a, p) => a + (p.pct || 0), 0);
      const core = fixed !== null ? fixed : PRIMARY.has(A)
        ? (prewar + flat) * Math.max(0.1, 1 + pct / 100) : prewar + flat + pct;
      const value = core + converted;
      const coreText = fixed !== null ? `固定值 ${fixed}` : PRIMARY.has(A)
        ? `(${prewar} + ${flat}) × (1 + ${pct}%)` : `${prewar} + ${flat} + ${pct}`;
      return {key: A, label: (PANEL_ATTRS.find(x => x[0] === A) || [A, A])[1],
              critBase,
              primary: PRIMARY.has(A), base, prewar, prewarFlat: pw?.flat || 0, prewarPct: pw?.pct || 0,
              flat, pct, fixed, converted: Math.round(converted * 100) / 100,
              parts, prewarParts: u.prewarParts?.[A] || [],
              value: Math.round(value * 100) / 100,
              formula: converted ? `${coreText} = ${Math.round(core * 100) / 100}，+ 实时属性转换 ${Math.round(converted * 100) / 100} = ${Math.round(value * 100) / 100}`
                                 : `${coreText} = ${Math.round(value * 100) / 100}`};
    }
    function unitPanel(u, snap) {
      return {
        critBaseChance: K.CritBaseChance, critBaseDamage: K.CritBaseDamage,
        shields: shieldPartsOf(u), shieldPhys: armorOf(u, 'phys'), shieldSpell: armorOf(u, 'spell'),
        uid: u.uid, name: u.name, side: u.side, prof: u.prof, profName: u.profName, star: u.star || 0,
        pageId: u.pageId, avatar: u.avatar, tags: u.tags || [],
        hp: snap.hp, mhp: snap.mhp, tp: snap.tp, ar: snap.ar, alive: snap.alive,
        hpState: hpState(u), x: snap.x, y: snap.y,
        attrs: PANEL_ATTRS.map(([A]) => attrBreakdown(u, A)),
        buffs: snap.b.map(([id, turns, stacks, aura]) => {
          const def = M?.buffs?.[id];
          return {id, n: def?.n || `状态 ${id}`, d: def?.d || '', bt: def?.bt || 0,
                  et: def?.et || '', turns, stacks, aura: !!aura,
                  sp: (def?.sp || []).map(sid => M?.specs?.[sid]?.t).filter(Boolean)};
        }),
        skills: u.skills.map(s => ({id: s.id, n: s.n, tp: s.tp, cd: u.cd[s.id] || 0, dt: s.dt,
                                    df: s.df, rmin: s.rmin, rmax: s.rmax, desc: s.desc,
                                    labels: skillLabels(s, M)})),
        // Effective (buffed) casting range / knockback / damage per skill,
        // with every client speciality row that contributed. Kept separate
        // from `skills` (which always shows the RAW template numbers).
        skillStates: u.skills.map(s => Object.assign({}, skillStateOf(u, s) || {},
          {composition: compositionOf(s)})).filter(Boolean),
        passives: u.passiveSkills.map(s => ({id: s.id, n: s.n, types: (s.sp || []).map(sid => M?.specs?.[sid]?.t).filter(Boolean)})),
        ai: u.ai ? {byOrder: !!u.ai.byOrder, sorted: !!u.ai.sorted,
                    order: (u.ai.order || []).slice(), cursor: u.ai.cursor || 0,
                    fields: Object.keys(SUB?.aiFields || {})} : null,
        alert: alertState(u) ? (() => { const a = alertState(u); return {dist: a.dist, points: a.points,
          basePoints: a.basePoints, countBonus: a.countBonus, left: a.left,
          segments: a.segments, factors: a.segmentDefs.map(d => d.factor),
          strengthened: a.strengthened, interrupts: a.interrupts, display: a.display,
          hidePreview: a.hidePreview, skill: a.skill, name: a.name}; })() : null,
        personality: (u.passiveSkills || []).filter(s => s.role === 'personality' || (u.personalityIds || []).includes(s.id))
          .map(s => ({id: s.id, n: s.n, desc: s.desc || '',
                      effects: (s.sp || []).map(sid => {
                        const sp = M?.specs?.[sid];
                        if (!sp) return null;
                        return {id: sid, t: sp.t, at: sp.at, p: sp.p, c: sp.c || '', dp: sp.dp || '',
                                n: sp.n || '', timing: M?.enums?.activeTime?.[sp.at] || ''};
                      }).filter(Boolean),
                      implemented: (s.sp || []).map(sid => M?.specs?.[sid]?.t).filter(Boolean)})),
        conditionalMods: PANEL_ATTRS.map(([A]) => {
          const rows = (modIndex(u).get(A) || []).filter(i => (AT_ALIAS[i.spec.at] || i.spec.at) === 2);
          if (!rows.length) return null;
          return {key: A, rows: rows.map(i => ({n: i.name, t: i.spec.t, p: i.spec.p,
                    dp: i.spec.dp || '', c: i.spec.c || '', buff: i.buff?.id || 0}))};
        }).filter(Boolean),
      };
    }

    /* ---------- Lua environment ---------- */
    // Bindings mirror the field / method names the client's activation
    // conditions use (owner, target, skill, buff, map, Database, Battle).
    const sim = {tick: 0, epoch: 0, round: 0, turnOwner: null, depth: 0, live: new Map(),
                 subHits: null, pendingSubHits: [],
                 extraTurns: [], changedBuffs: null, newUnits: [], objectRing: null,
                 objectOrigin: null, randomCell: null,
                 // [再行动] granted by ACTED_ACT / RE_ROUND whose p[0] names the
                 // ONE skill the extra action may cast (落花之舞 / 游击 / 露西亚
                 // 之血永存！). `coordinateDepth` guards 协同号令 → 协同响应
                 // recursion; `swapTimers` reverts 技能变更为 after N rounds.
                 coordinateDepth: 0, extraSkill: 0, swapTimers: [],
                 // OPERATION / field status: 烟幕游击 turns the landing tile
                 // into [烟雾] for p[1] rounds (client speciality #10357).
                 fieldStatus: new Map()};
    const upperMap = (obj) => {
      const out = {};
      for (const [id, t] of Object.entries(obj || {})) if (t) out[String(t).toUpperCase()] = Number(id);
      return out;
    };
    const nameMap = (obj) => {
      const out = {};
      for (const [id, t] of Object.entries(obj || {})) if (t) out[String(t)] = Number(id);
      return out;
    };
    const strict = (obj, name) => ({__get(k) {
      if (Object.prototype.hasOwnProperty.call(obj, k)) return obj[k];
      throw new Lua.Unknown(name + '.' + k);
    }});
    // Missing enum members resolve to -1 (never matches) instead of failing,
    // because the closure only exports types it uses.
    const lenient = (obj) => ({__get(k) { return Object.prototype.hasOwnProperty.call(obj, k) ? obj[k] : -1; }});
    const specTypeIds = nameMap(M?.enums?.specTypeAll || M?.specTypes);
    const Database = strict({
      _skill: strict({HIT_METHOD: strict(M?.enums?.hitMethod || {}, 'HIT_METHOD'),
                      RANGE_TAG: strict(M?.enums?.rangeTag || {}, 'RANGE_TAG'),
                      range_tag: strict(M?.enums?.rangeTag || {}, 'range_tag'),
                      CLASS_TYPE: strict({NONE: 0, MELEE: 1, RANGED: 2, PROFESSION_SKILL: 3,
                                          UNIT_SPEC: 4, LEADER: 5, REACTIVE: 6, ITEM: 7}, 'CLASS_TYPE'),
                      PHASE: strict({}, 'PHASE')}, '_skill'),
      _damage_type: strict({TYPE: strict({PHYSICATTACK: 1, SPELLATTACK: 2, HEAL: 3, FIXEDDAMAGE: 4, STATUS: 5}, 'TYPE')}, '_damage_type'),
      _attribute_type: strict(Object.assign({TYPE: Object.fromEntries(
        Object.entries(M?.enums?.attributes || {}).map(([k, v]) => [v, Number(k)]))},
        M?.enums?.attributes || {}), '_attribute_type'),
      _hp_attenuation: strict({TYPE: strict({HEALTH: 1, INJURED: 2, DYING: 3, DEAD: 4}, 'TYPE')}, '_hp_attenuation'),
      _field_status: strict({TYPE: strict(upperMap(M?.enums?.fieldStatus), 'TYPE')}, '_field_status'),
      _buff: strict({BUFF_TYPE: strict(M?.enums?.buffType || {}, 'BUFF_TYPE')}, '_buff'),
      _abnormal_state: strict({TYPE: strict(upperMap(M?.enums?.abnormal), 'TYPE')}, '_abnormal_state'),
      _buff_effect_type: strict({TYPE: lenient(upperMap(M?.enums?.effectTypes))}, '_buff_effect_type'),
      _speciality_type: strict({TYPE: lenient(specTypeIds)}, '_speciality_type'),
      _active_time: strict({TYPE: strict(nameMap(M?.enums?.activeTime), 'TYPE')}, '_active_time'),
    }, 'Database');
    const effectBit = et => {
      const id = Object.entries(M?.enums?.effectTypes || {}).find(([, t]) => t === et)?.[0];
      return id ? Number(id) : 0;
    };
    const buffCount = (u, pred) => u ? u.buffs.filter(pred).reduce((a, b) => a + (b.stacks || 1), 0) : 0;
    const dirTo = (from, to) => {
      const dx = to.x - from.x, dy = to.y - from.y;
      if (!dx && !dy) return from.dir || [1, 0];
      return Math.abs(dx) >= Math.abs(dy) ? [Math.sign(dx), 0] : [0, Math.sign(dy)];
    };
    const relPos = (attacker, defender) => {
      const v = [attacker.x - defender.x, attacker.y - defender.y];
      const d = v[0] * defender.dir[0] + v[1] * defender.dir[1];
      return d > 0 ? 'Front' : d < 0 ? 'Back' : 'Side';
    };
    const heightOf = u => grid.at(u.x, u.y)?.h ?? 0;
    const inList = (v, list) => list === undefined || list === null || list === 0 ||
      (Array.isArray(list) ? list.length === 0 || list.includes(v) : list === v);
    const hasSpecType = (ids, typeId) => (ids || []).some(sid => specTypeIds[M?.specs?.[sid]?.t] === typeId);
    const proxies = new WeakMap();
    function U(u) {
      if (!u) return null;
      // Interactive objects (props / traps) are not units: they have no
      // attribute table. The client exposes them as Battle.Entity.Type.Props,
      // so give Lua a minimal, safe proxy instead of running attr() on them.
      if (u.kind && !u.base) {
        return {__get(k) {
          switch (k) {
            case 'type': return 2;                     // Battle.Entity.Type.Props
            case 'id': return u.id;
            case 'template': return {id: u.id};
            case 'name': return u.name;
            case 'x': case 'temp_ix': return u.x;
            case 'y': case 'temp_iz': return u.y;
            case 'hp': case 'temp_hp': return u.hp;
            case 'hp_max': case 'temp_hp_max': return u.maxHp;
            case 'temp_attributes': case 'attributes':
              return {hp: u.hp, hp_max: u.maxHp, physic_attack: 0, spell_attack: 0,
                      physic_defence: 0, spell_defence: 0, speed: 0, mobility: 0};
            case 'isFriend': return () => false;
            case 'isEnemy': return () => true;
            case 'IsTempOnStage': return () => true;
            case 'getBuffCount': return () => 0;
            case 'owner': case 'sourceEntity': return U(u.owner);
          }
          return undefined;
        }, __methods: {IsUnit: () => false, IsTempOnStage: () => true,
                       getBuffCount: () => 0, isFriend: () => false, isEnemy: () => true}};
      }
      if (proxies.has(u)) return proxies.get(u);
      const p = {
        __get(k) {
          switch (k) {
            case 'temp_attributes': case 'attributes': {
              // Named values the client computes specially, then ANY client
              // attribute by its lower-case column name (attr_cache = 灵感指数
              // stored by DAMAGE_BUFFER_DYNAMIC, …). A fixed literal object
              // returned `nil` for attr_cache, so 灵感迸发 (`attr_cache > 0`)
              // could never fire. Lazy, so a read costs one attr() call.
              const special = {
                hp: () => u.hp, hp_max: () => maxHpOf(u), tp: () => u.tp, tp_max: () => attr(u, 'TP_MAX'),
                physic_armor: () => armorOf(u, 'phys'), spell_armor: () => armorOf(u, 'spell'),
                damage_buffer: () => armorOf(u, 'phys') + armorOf(u, 'spell'),
                crit_ratio: () => K.CritBaseChance + attr(u, 'CRIT_RATIO'),
                crit_damage: () => K.CritBaseDamage + attr(u, 'CRIT_DAMAGE'),
                overflow_damage: () => u.damageStored || 0};
              const known = new Set(Object.values(M?.enums?.attributes || {}));
              return {__get(k) {
                if (Object.prototype.hasOwnProperty.call(special, k)) return special[k]();
                const A = String(k).toUpperCase();
                if (known.has(A)) return attr(u, A);
                throw new Lua.Unknown('temp_attributes.' + k);
              }};
            }
            case 'level': return Number(u.statLevel) || Number(u.level) || 1;
            case 'removed_buff_stacks': return u.removedBuffStacks || 0;
            case 'cooldown_max': return (c.skill?.cd ?? 0);
            case 'temp_damageAttributes': {
              // Any client damage attribute by its lower-case column name
              // (final_bedamage, physic_bedamage, fix_damage …), resolved via
              // attribute_type.json — not a hand-picked subset.
              const known = new Set(Object.values(M?.enums?.attributes || {}));
              return {__get(k) {
                if (k === 'apply_duration_damage_modify') return 100 + attr(u, 'DURATION_DAMAGE_MODIFY');
                if (k === 'bedamage_ratio') return 1 + attr(u, 'BEDAMAGE') / 100;
                if (k === 'damage_modify') return attr(u, 'DAMAGE');
                const A = String(k).toUpperCase();
                if (known.has(A)) return attr(u, A);
                throw new Lua.Unknown('temp_damageAttributes.' + k);
              }};
            }
            case 'movement': return {wait_time: 10000 / Math.max(1, attr(u, 'SPEED')), mobility: attr(u, 'MOBILITY'),
              // movement.stay_type: the unit's ground / flying class (move.type),
              // read by cast_param 「target:canStay(owner.movement.stay_type, …)」.
              stay_type: Number(u.move?.type) || 1};
            case 'base_movement': return {wait_time: 10000 / Math.max(1, u.base.SPEED || 100), mobility: u.base.MOBILITY || 3};
            case 'temp_mobility': return attr(u, 'MOBILITY');
            case 'IsInDelay': return () => false;
            case 'checkForget': return () => !!u.flags.forget;
            case 'cooldown_max': return 0;
            case 'aimachine': return {state: 0, ai_state: 0, target: U(null),
              BehaviorDecision: () => true, checkPriority: () => 0};
            case 'attacking_attributes': case 'base_attributes': return {
              hp: u.hp, hp_max: maxHpOf(u), physic_attack: attr(u, 'PHYSIC_ATTACK'),
              spell_attack: attr(u, 'SPELL_ATTACK'), physic_defence: attr(u, 'PHYSIC_DEFENCE'),
              spell_defence: attr(u, 'SPELL_DEFENCE'), speed: attr(u, 'SPEED'),
              damage: attr(u, 'DAMAGE'),
              crit_ratio: K.CritBaseChance + attr(u, 'CRIT_RATIO'),
              crit_damage: K.CritBaseDamage + attr(u, 'CRIT_DAMAGE')};
            case 'type': return 1;
            case 'data': return {star: u.star || 5, id: u.unitId, tp: u.tp};
            case 'profession': return {category: u.prof};
            case 'hp': return u.hp;
            case 'tp': return u.tp;
            case 'id': return u.unitId;
            case 'template': return {id: u.unitId};
            case 'unit_npc_id': return u.npcId || 0;
            case 'unit': return U(u);
            case 'data': return {id: u.unitId || 0, star: u.star || 5, unit_npc_id: u.npcId || 0};
            case 'melee_skill': return u.skills.find(x => x.isNormal) ? S(u.skills.find(x => x.isNormal), u) : null;
            case 'temp_ix': case 'ix': return u.x;
            case 'temp_iz': case 'iz': return u.y;
            case 'temp_iy': case 'iy': return heightOf(u);
            case 'move_steps': return u.flags.spentMove || 0;
            case 'charge_step': return 0;
            case 'delay_skill': return null;
            case 'last_add_debuff': return null;
            case 'hp_damage_turn': case 'temp_hp_damage_turn': return u.flags.damagedTurn ? 1 : 0;
            case 'isSkilled': return !!u.flags.skilled;
            case 'temp_isAlive': case 'isAlive': return u.alive;
            case 'buffs': return u.buffs.filter(b => !b.aura).map(B);
            // Client unit.changed_buffs: the buffs that changed on this unit
            // in the CURRENT cast (BUFF_CHANGE events see only that one).
            // 珀列维特 #29677「技能对目标施加了显示在 UI 的状态 → 获得3层预言」
            // walks skill.target_entitys[i].changed_buffs at 攻击后; it was
            // nil there, so 预言 / 卜预回能 never happened.
            case 'changed_buffs': {
              if (sim.changedBuffs) return sim.changedBuffs.map(B);
              const list = (u._chg || []).filter(x => x.serial === sim.castSerial).map(x => B(x.b));
              return list.length ? list : null;
            }
            case 'isSummoned': return !!u.summon;
            // 大维齐尔 / 基安希尔 「给全场刚召的死士…」(tgp #18746/18749/
            // 18763/18794). True only for summons created in THIS cast; the
            // parent 征伐敕令's at=4 CAST_SKILL chain shares castSerial.
            case 'isCurrentSummoned': return !!u.summon && u.summonedCast === (sim.castSerial || 0);
          }
          throw new Lua.Unknown('unit.' + k);
        },
        __methods: {
          // Client getBuffCount counts ACTIVE buffs only; the explicit
          // ...RegardlessActivation variant also counts dormant ones.
          getBuffCount: (id, n = 1) => buffCount(u, b => b.id === id && buffOn(b)) >= (n || 1),
          getBuffCountRegardlessActivation: (id, n = 1) => buffCount(u, b => b.id === id) >= (n || 1),
          getBuffTotalStackCount: (id) => buffCount(u, b => b.id === id),
          getBuffById: (id) => { const b = u.buffs.find(x => x.id === id); return b ? B(b) : null; },
          getSpecialityByID: (id) => {
            const inst = unitSpecs(u).find(i => Number(i.sid) === Number(id));
            if (!inst) return null;
            const L = u.limits[(inst.buff ? 'b' + inst.buff.id : inst.src) + ':' + inst.sid] || {turn: 0, total: 0};
            return {temp_limit_count_turn: L.turn, temp_limit_count: L.total,
                    limit_count_turn: inst.spec.lt || 0, limit_count: inst.spec.lc || 0};
          },
          FindChangedBuff: (id) => {
            const cb = sim.changedBuffs || [];
            const b = (id ? cb.filter(x => x.id === id) : cb)[0];
            return b ? B(b) : null;
          },
          getBuffCountByType: (t, n = 1) => buffCount(u, b => b.def.bt === t) >= (n || 1),
          hasBuffType: (t) => u.buffs.some(b => b.def.bt === t),
          getBuffCountByCategory: (c, n = 1) => buffCount(u, b => b.def.cat === c) >= (n || 1),
          hasBuffCategory: (c) => u.buffs.some(b => b.def.cat === c),
          hasBuffCategoryById: (c) => u.buffs.some(b => b.def.cat === c),
          getBuffCountByMiddleType: (t, n = 1) => buffCount(u, b => b.def.mi === t) >= (n || 1),
          getBuffCountBySubType: (t, n = 1) => buffCount(u, b => b.def.sb === t) >= (n || 1),
          hasBuffEffect: (e) => u.buffs.some(b => effectBit(b.def.et) === e),
          isAbnormalState: (a) => u.buffs.some(b => b.def.et && String(M.enums.abnormal?.[a] || '') === b.def.et),
          isEnemy: (o) => !!o && !!o.__unit && o.__unit.side !== u.side,
          isFriend: (o) => !!o && !!o.__unit && o.__unit.side === u.side,
          IsUnit: (id) => u.unitId === id,
          HasUnitTagByID: (t) => (u.tags || []).includes(t),
          checkHpAttenuation: (t) => hpState(u) === t,
          // Unit form `target:isFieldStatus(map, TYPE)`; block form passes TYPE only.
          isFieldStatus: (a, b) => (grid.at(u.x, u.y)?.status || 1) === Number(b ?? a),
          hasArmor: () => armorOf(u, 'phys') > 0 || armorOf(u, 'spell') > 0,
          getDistanceFrom: (a, b) => a?.__unit ? manhattan(u, a.__unit)
            : (typeof a === 'number' && typeof b === 'number') ? Math.abs(u.x - a) + Math.abs(u.y - b) : 99,
          checkHighland: (o) => !!o?.__unit && heightOf(u) - heightOf(o.__unit) >= (hg.minDiff || 2),
          getMoveHeight: () => u.flags.moveHeight || 0,
          isClimbOver: () => !!u.flags.climbed,
          IsHPDamagedTurn: () => !!u.flags.damagedTurn,
          IsHPDamageTurn: () => !!u.flags.damagedTurn,
          CheckForbiddenReactiveSkill: () => noReactive(u),
          // Summon relationship (灵感星核 / 虚空投影 …). These were hard-wired
          // to false / nil, so every client predicate about summons failed:
          // 8801「魔术师灯柱存活标记」, 天才的气场「目标为己方召唤角色」 …
          IsSummoned: () => !!u.summon,
          GetSummoner: () => {
            const s = u.summon ? units.find(x => x.uid === u.summoner) : null;
            return s ? U(s) : null;
          },
          IsMoved: () => !!u.flags.moved,
          IsRoundMoved: () => !!u.flags.moved,
          IsTurnMoved: () => !!u.flags.moved,
          IsOnStage: () => u.alive,
          IsTempOnStage: () => u.alive,
          canAct: () => u.alive && !u.buffs.some(b => CONTROL_SKIP.has(b.def.et)),
          checkSeal: () => u.buffs.some(b => b.def.et === 'Seal' || b.def.et === 'SpecialSeal'),
          IsProfessionCategory: (c) => u.prof === c,
          GetProfessionCategory: () => u.prof,
          GetCurTurn: () => sim.round,
          getSkillByID: (id) => { const s = u.skills.find(x => x.id === id) || u.passiveSkills.find(x => x.id === id); return s ? S(s, u) : null; },
          // Client dynamic_param reads a unit's speciality of a given type to
          // borrow its limit / stack values. Return the first matching spec.
          getSpeciality2: (typeId) => {
            const name = M?.enums?.specialityTypes?.[typeId];
            const inst = unitSpecs(u).find(i => i.spec.t === name || i.spec.sid === typeId);
            if (!inst) return null;
            const s = inst.spec;
            return {limit_count_turn: s.lt || 0, limit_count: s.lc || 0,
                    stack_count: inst.buff?.stacks || 1, param0: s.p?.[0] || 0,
                    param1: s.p?.[1] || 0, param2: s.p?.[2] || 0, param3: s.p?.[3] || 0,
                    type: name};
          },
          getBuffBySpeciality: (sid) => {
            const b = u.buffs.find(x => (x.def.sp || []).includes(Number(sid)));
            return b ? B(b) : null;
          },

          getSpeciality: (typeId) => u.passive.some(i => specTypeIds[i.spec.t] === typeId) ||
            u.buffs.some(b => hasSpecType(b.def.sp, typeId)),
          getSpecialitys: (typeId) => unitSpecs(u).filter(i => specTypeIds[i.spec.t] === typeId)
            .map(i => ({id: i.sid, type: i.spec.t, param0: i.spec.p?.[0] || 0})),
          getSpecialityByID: (id) => u.passive.some(i => i.sid === id) || u.buffs.some(b => b.def.sp.includes(id)),
          checkForget: () => !!u.flags.forget,
          getBuffCountByTagId: (tagId) => u.buffs.filter(b => (b.def.tags || []).includes(Number(tagId))).length,
          CheckImmuneType: () => false,
          HasUnitTagByID: (id) => (u.tags || []).includes(Number(id)),
          IsInDelay: () => false,
          GetAttributeModify: (id) => {
            const n = attrName(id);
            return n ? Math.round(attr(u, n) - (u.base?.[n] || 0)) : 0;
          },
          isState: (at) => !!sim.live.get(u)?.has(at),
          isRoundState: (at) => !!u.turnStates?.has(at),
          IgnoreKnockbackOrUnMovable: () => immuneToKnockback(u) || hasEffect(u, 'Immobilize'),
          getNeighborPropsCount: () => 0,
          // field statuses are never changed in this simulator (no 地块 effects)
          hasChangedFieldStatus: () => false,
          hasTag: () => false,
        },
        __unit: u,
      };
      proxies.set(u, p);
      return p;
    }
    function B(b) {
      // Per-speciality trigger counters of this buff, from the same records
      // limitOk()/spend() maintain (key 'b<buffId>:<specId>' on the holder).
      // Client Lua reads them as buff.specs[i].temp_limit_count(_turn)
      // (#29240, #30864 信仰个性) and buff:getSpecialityByID(id).
      const specRec = sid => {
        const L = b.holder?.limits?.['b' + b.id + ':' + sid] || {turn: 0, total: 0};
        const sp = M?.specs?.[sid] || {};
        return {data: {id: Number(sid), type: sp.t}, id: Number(sid),
                temp_limit_count: L.total, temp_limit_count_turn: L.turn,
                limit_count: sp.lc || 0, limit_count_turn: sp.lt || 0};
      };
      return {__get(k) {
        switch (k) {
          case 'specs': return (b.def.sp || []).map(specRec);
          case 'isTriggered': return !!b.triggered;
          case 'layer': case 'stack_count': return b.stacks;
          case 'stack_count_change': return b.stackChange || 0;
          case 'id': return b.id;
          case 'template': return {id: b.id, effect_type: effectBit(b.def.et), buff_type: b.def.bt, category: b.def.cat};
          case 'owner': return U(b.holder);
          case 'source': case 'sourceEntity': return U(b.src);
          case 'cur_turn': return b.age || 0;
          case 'data': return {id: b.id, buff_type: b.def.bt, category: b.def.cat,
                               // owner.changed_buffs → v.data.sub_type (31009).
                               sub_type: b.def.sb || 0, middle_type: b.def.mi || 0,
                               effect_type: effectBit(b.def.et), stack_count: b.def.sc || 1};
          case 'category': return b.def.cat || 0;
          case 'buff_type': return b.def.bt || 0;
          case 'isDeleted': return !!b.deleted;
          case 'isActiveTemp': return !!b.triggered;
          case 'turn': return Number.isFinite(b.total) ? b.total : 99;
        }
        throw new Lua.Unknown('buff.' + k);
      }, __methods: {
      GetSourceEntity: () => U(b.src),
      // A buff the client shows in the status bar (buff.ui / show_in_ui).
      IsShowUI: () => b.def.ui !== false && !b.aura,
      getSpecialityByID: (id) => (b.def.sp || []).some(x => Number(x) === Number(id))
        ? specRec(Number(id)) : null}};
    }
    const uCd = (s, caster) => caster?.cd?.[s?.id] || 0;
    // [min, max] range delta from SKILL_RANGE / EXTEND_CAST_RANGE for the
    // skill proxy. Guarded: a range row's own condition may read the proxy.
    const rangeGuard = new Set();
    function skillRangeDelta(caster, s, flags = {}) {
      const k = caster.uid + ':' + s.id;
      if (rangeGuard.has(k)) return [0, 0];
      // Pure function of the board state: one evaluation per (caster state,
      // position, skill) per epoch. cast_params read skill.range_max once per
      // candidate block, and each read re-ran every SKILL_RANGE condition.
      return memoGet('r|' + k + '|' + caster.ver + '|' + caster.x + ',' + caster.y + '|' + (flags.counter ? 1 : 0), () => {
        rangeGuard.add(k);
        try { return rangeMods(caster, !!flags.counter, s); }
        catch { return [0, 0]; }
        finally { rangeGuard.delete(k); }
      });
    }
    function S(s, caster, target, flags = {}) {
      if (!s) return null;
      const proxy = {
        __get(k) {
          switch (k) {
            case 'checkForget': return () => false;
            case 'isNormal': return !!s.isNormal && !flags.counter;
          case 'cooldown': case 'cooldown_max': return uCd(s, caster);
          case 'target_entitys': case 'entitys': return (flags.targets || []).map(x => U(x));
          case 'isAoe': return (s.area?.type || 'single') !== 'single';
            case 'owner': return U(caster);
            case 'target': return flags.prop ? {
              __get(k) {
                if (k === 'type') return 2;                   // Battle.Entity.Type.Props
                if (k === 'template') return {id: flags.prop.id};
                if (k === 'id') return flags.prop.id;
                if (k === 'x' || k === 'temp_ix') return flags.prop.x;
                if (k === 'y' || k === 'temp_iz') return flags.prop.y;
                if (k === 'hp') return flags.prop.hp;
                if (k === 'isFriend') return () => false;
                return U(flags.prop.owner)?.[k] ?? null;
              },
              // Props are entities too: 嘿咻！#11457 asks
              // `skill.target:getBuffCount(1239,1)` on 呆呆雪人.
              __methods: {
                getBuffCount: (id, n = 1) => (flags.prop.buffs || [])
                  .filter(b => Number(b.id) === Number(id)).reduce((a, b) => a + (b.stacks || 1), 0) >= (n || 1),
                IsUnit: () => false,
                IsTempOnStage: () => !!flags.prop.alive,
                isFriend: (o) => !!o?.__unit && o.__unit.side === flags.prop.owner?.side,
                isEnemy: (o) => !!o?.__unit && o.__unit.side !== flags.prop.owner?.side,
              }} : U(target);
            case 'id': return s.id;
            // Client skill columns read by active_param Lua (e.g. spec 17537
            // halves `skill.range_max`). Exposed on the skill proxy itself.
            // skill.range_max / range_min are the EFFECTIVE values, after
            // SKILL_RANGE / EXTEND_CAST_RANGE (template.range_max keeps the
            // base). 珀列维特's cast_param 「距离 <= skill.range_max -
            // rangeChange[星级]」 and 超距施法 #29086 compare against the
            // base range only because range_max already includes the +8 of
            // 先知 #29120; the base value made every cast 「超距」.
            case 'range_max': return (s.rmax || 0) + (caster ? skillRangeDelta(caster, s, flags)[1] : 0);
            case 'range_min': return Math.max(0, (s.rmin || 0) + (caster ? skillRangeDelta(caster, s, flags)[0] : 0));
            case 'template': return {id: s.id, class_type: s.ct, range_max: s.rmax || 0,
                                     range_min: s.rmin || 0, damage_factor: s.df || 0,
                                     // 附属被动 #27533「每回合首次释放基础耗能
                                     // >=3 的技能后…」reads skill.template.tp.
                                     tp: s.tp || 0, tp_max: s.tp || 0};
            case 'isCounter': return !!flags.counter;
            case 'isInitiative': return !flags.counter && !flags.sub;
            case 'isFirstHit': return !!flags.firstHit;
            case 'target_entitys': return (flags.targets || (target ? [target] : [])).map(U);
            case 'skill_start_ix': return flags.start ? flags.start.x : caster?.x;
            case 'skill_start_iz': return flags.start ? flags.start.y : caster?.y;
            // Client skill.main_skill points at the MAIN cast skill (the skill
          // instance itself for a normal cast). 阿尔曼大帝 BUFF #28513 uses
          // `main_skill.consumeTP` in dynamic_param to grant one 蓄势 layer
          // per point of energy the skill consumed; returning null made that
          // Lua fail and the whole 蛮勇转化 personality a no-op.
          case 'main_skill': return flags.sub && flags.mainSkill
            ? S(flags.mainSkill, caster, target, {}) : proxy;
          case 'consumeTP': return caster ? tpCost(caster, s) : (s.tp || 0);
          case 'from_skill': case 'from_speciality': return null;
            case 'data': return {id: s.id, tp: s.tp || 0, class_type: s.ct,
                                 damage_type: s.dt, cooldown_max: s.cd || 0};
            // Client skill instance counters (碎冰飞刃 #26502:
            // `ski.limit_count - ski.temp_limit_count == 0`; 安缇歌 #31757:
            // `limit_count - cur_limit_count < 3`). temp/cur = times used.
            case 'limit_count': return caster ? skillLimitOf(caster, s) : (s.lc || 0);
            case 'limit_count_turn': return s.lct || 0;
            case 'temp_limit_count': case 'cur_limit_count': return caster ? (caster.uses[s.id] || 0) : 0;
            case 'temp_limit_count_turn': return caster ? (caster.uses[s.id + ':t'] || 0) : 0;
            case 'cooldown': return caster ? (caster.cd[s.id] || 0) : 0;
            case 'origin_block': return flags.origin ? blockProxy(flags.origin) : null;
            case 'range_blocks': return (flags.area || []).map(blockProxy);
          }
          throw new Lua.Unknown('skill.' + k);
        },
        __methods: {
          hasTag: (t) => (s.tags || []).includes(t),
          isHitMethod: (m) => s.hm === m,
          isDamageType: (t) => s.dt === t,
          isRangeTag: (t) => s.rt === t,
          AttackPosition: (m, o) => o?.__unit && caster ? relPos(caster, o.__unit) : 'Front',
          isnotAttackPosition: (m, o, d) => !(o?.__unit && caster && relPos(caster, o.__unit) === d),
          IsMainSkill: () => !flags.sub,
          getSpeciality: (typeId) => hasSpecType(s.sp, typeId),
          getSpecialityByID: (id) => (s.sp || []).includes(id),
          getConsumeTP: () => (caster ? tpCost(caster, s) : s.tp || 0),
          getSpecialityByID: (id) => (s.sp || []).some(x => Number(x) === Number(id))
            ? {temp_limit_count_turn: 0, temp_limit_count: 0, limit_count_turn: 0, limit_count: 0} : null,
          // Client fills an out-table with this skill's specialities of a type;
          // each entry exposes Spec.data.param3 etc.
          getSpecialitys: (typeId, out) => {
            const rows = (s.sp || []).map(id => M?.specs?.[id]).filter(Boolean);
            for (const sp of rows) {
              if (typeId && specTypeIds[sp.t] !== typeId) continue;
              if (Array.isArray(out)) out.push({data: {param0: sp.p?.[0] || 0, param1: sp.p?.[1] || 0,
                param2: sp.p?.[2] || 0, param3: sp.p?.[3] || 0, sparam: sp.s || ''}, id: sp.sid || 0});
            }
            return out || [];
          },
          hasTargetEnemy: () => (flags.targets || []).some(x => caster && x.side !== caster.side),
          hasTargetFriend: () => (flags.targets || []).some(x => caster && x.side === caster.side),
          CheckIsZeroDamageValue: () => !s.df && !s.dmg && !s.dp,
          // owner:getSkillByID(...):checkForget() / :checkSeal() / :checkHpAttenuation()
          checkForget: () => !!(caster?.flags?.forget),
          checkSeal: () => !!(caster?.flags?.seal),
          checkHpAttenuation: (state) => hpState(caster) === state,
          getCoolDown: () => uCd(s, caster),
        },
        __skill: s, __flags: flags, __caster: caster,
      };
      return proxy;
    }
    // Client trap objects expose `template.id` (trap.json id) and are used by
    // almost every active_time 64 「拾取蜜果 / 碎冰」 condition.
    const trapProxy = o => ({
      template: {id: o.id, trap_type: o.triggerType, attackable: !!o.attackable},
      id: o.id, x: o.x, y: o.y, temp_ix: o.x, temp_iz: o.y,
      // Non-attackable interactive objects (枪影 #139) carry no hp field; the
      // client entity still reports hp > 0 while it is on the board, which
      // is exactly what 「block.trap.temp_attributes.hp > 0」 tests.
      hp: o.alive ? (o.hp ?? 1) : 0, hp_max: o.maxHp ?? 1, iy: grid.at(o.x, o.y)?.h || 0,
      temp_attributes: {hp: o.alive ? (o.hp ?? 1) : 0, hp_max: o.maxHp ?? 1},
      __unit: o.owner || null,
      isFriend: () => true,
    });
    const blockProxy = (c, trap) => {
      const obj = trap !== undefined ? trap : objectAt(c.x, c.y, 'PLACE_TRAP');
      return {__get(k) {
        switch (k) {
          case 'temp_unit': return U(units.find(x => x.alive && x.x === c.x && x.y === c.y)) || null;
          case 'unit': return U(units.find(x => x.alive && x.x === c.x && x.y === c.y)) || null;
          case 'temp_trap': case 'trap': return obj ? trapProxy(obj) : null;
          case 'ix': case 'temp_ix': return c.x;
          case 'iz': case 'temp_iz': return c.y;
          case 'iy': return c.h ?? grid.at(c.x, c.y)?.h ?? 0;
          case 'pit': return false;
          case 'type': return 1;
        }
        return null;
      }, __methods: {isFieldStatus: (a, b) => (c.status || 1) === Number(b ?? a),
        // block:canStay(stay_type, …): may a unit of that class END its move
        // here — walkable, not a pit / 禁行, no collidable object. Units on
        // the block are tested separately by the caller (temp_unit == nil).
        canStay: () => {
          const g = grid.at(c.x, c.y);
          if (!g || !g.walk || g.pit) return false;
          return !placed.some(o => o.alive && o.collidable && o.x === c.x && o.y === c.y);
        }}};
    };
    // Client skill.target_param — is THIS unit inside the area affected?
    // It is ANDed with the side the skill's AOE row declares (target_type
    // 1 己方 / 2 敌方 / 3 自身 / 4 全体 / 5 己方不含自身): 全场大巡演's AOE is
    // 敌人 (tt 2) and its target_param only removes own summons / props; the
    // 21482 造物赋能 response is 全部单位 (tt 4) narrowed to the own 灵感星核.
    const aoeSideOf = s => {
      for (const sid of s.sp || []) {
        const q = M?.specs?.[sid];
        if (q?.t === 'AOE') return Number(q.tt) || 0;
      }
      return 0;
    };
    const hitsUnit = (s, caster, u) => {
      if (!s?.tgp) return affects(s, caster, u);
      const v = targetParamOk(caster, s, u);
      if (v === null) return affects(s, caster, u);
      if (!v) return false;
      switch (aoeSideOf(s)) {
        case 1: return u.side === caster.side;
        case 2: return u.side !== caster.side;
        case 3: return u === caster;
        case 4: return true;
        case 5: return u.side === caster.side && u !== caster;
        default: return affects(s, caster, u);
      }
    };
    // Per-state memo for cast_param / target_param: both are pure functions
    // of the board, so one evaluation per (caster, skill, block / unit,
    // caster position) per state epoch is enough. The AI enumerates every
    // stand × target pair and used to re-run the Lua for each of them.
    const paramMemo = new Map();
    let paramMemoEpoch = -1;
    const memoGet = (k, fn) => {
      if (paramMemoEpoch !== sim.epoch) { paramMemo.clear(); paramMemoEpoch = sim.epoch; }
      if (paramMemo.has(k)) return paramMemo.get(k);
      const v = fn();
      paramMemo.set(k, v);
      return v;
    };
    function targetParamOk(caster, s, u) {
      if (!s?.tgp) return null;
      return memoGet('t|' + caster.uid + '|' + caster.ver + '|' + s.id + '|' + u.uid + '|' + u.ver + '|' + u.x + ',' + u.y,
        () => targetParamEval(caster, s, u));
    }
    function targetParamEval(caster, s, u) {
      const wasProbe = sim.probe;
      sim.probe = true;
      try {
        const env = luaEnv({spec: {t: 'TARGET_PARAM', c: s.tgp}, owner: caster, src: 'skill', name: s.n, skill: s},
          {attacker: caster, skill: s, defender: u, target: u, origin: {x: u.x, y: u.y}}, true);
        env.target = U(u);
        const r = Lua.test(s.tgp, env);
        if (r.ok === true || r.ok === false) return r.ok;
        bump(cov.skipped, '目标过滤无法求值#' + s.id);
        return null;
      } catch { return null; }
      finally { sim.probe = wasProbe; }
    }
    // Client skill.cast_param — Lua legality of the CHOSEN target (387 client
    // skills): 游击「return target.template.id == 139 and owner:isFriend(target)」
    // (only a friendly 枪影), 「return not target:getBuffCount(N, 1)」,
    // 「return target:IsUnit(N)」, 「target.temp_unit == nil and target:canStay(…)」.
    // `target` is the entity on the block in the client's order unit → props
    // → trap → the block itself. FAIL-CLOSED: only an explicit true makes the
    // block legal (a field the target lacks is nil in the client as well).
    // `stand` is the block the caster would cast FROM: 珀列维特's 「距离 <=
    // skill.range_max − rangeChange」 measures owner → target from there.
    // Only cast_params that read the caster's position need a per-stand
    // evaluation; the rest (temp_unit / canStay / template.id / IsUnit /
    // getBuffCount …) are evaluated once per target block and state epoch.
    const cpUsesStand = new Map();
    const standDependent = s => {
      let v = cpUsesStand.get(s.id);
      if (v === undefined) {
        v = /getDistanceFrom|owner\s*\.\s*(temp_)?i[xz]\b|owner\s*\.\s*[xy]\b|CasterLocation|CombatDistace/.test(String(s.cp || ''));
        cpUsesStand.set(s.id, v);
      }
      return v;
    };
    function castTargetOk(caster, s, cell, stand = null) {
      if (!s?.cp) return true;
      const dep = standDependent(s);
      const sx = dep && stand ? stand.x : caster.x, sy = dep && stand ? stand.y : caster.y;
      return memoGet('c|' + caster.uid + '|' + caster.ver + '|' + s.id + '|' + cell.x + ',' + cell.y + (dep ? '|' + sx + ',' + sy : ''),
        () => {
          const ox = caster.x, oy = caster.y;
          const moved = ox !== sx || oy !== sy;
          caster.x = sx; caster.y = sy;
          try { return castTargetEval(caster, s, cell); }
          finally {
            caster.x = ox; caster.y = oy;
            // Attributes read while standing elsewhere (terrain-gated buffs)
            // must not leak into the position-less attr() cache.
            if (moved) staticCache.clear();
          }
        });
    }
    function castTargetEval(caster, s, cell) {
      // A GROUND-targeted skill (星核·造物 / 星核·位移) is cast on the BLOCK:
      // its cast_param reads block fields (temp_unit, canStay) even when a
      // unit stands there. Every other skill binds the entity on the block.
      const ground = s.aim === 'ground';
      const onCaster = caster.x === cell.x && caster.y === cell.y;
      const build = () => {
        const u = !ground && units.find(x => x.alive && x !== caster && x.x === cell.x && x.y === cell.y)
          || (!ground && onCaster ? caster : null);
        const prop = !ground && !u && placed.find(o => o.alive && o.kind === 'PLACE_ITEM' && o.x === cell.x && o.y === cell.y);
        const trap = !ground && !u && !prop && placed.find(o => o.alive && o.kind === 'PLACE_TRAP' && o.x === cell.x && o.y === cell.y);
        const env = luaEnv({spec: {t: 'CAST_PARAM', c: s.cp}, owner: caster, src: 'skill', name: s.n, skill: s},
          {attacker: caster, skill: s, target: u || null, origin: cell}, true);
        env.target = u ? U(u) : prop ? U(prop) : trap ? trapProxy(trap) : blockProxy(grid.at(cell.x, cell.y) || cell);
        return {env, u};
      };
      const wasProbe = sim.probe;
      sim.probe = true;
      try {
        // The environment only binds LIVE proxies, so for a block other than
        // the caster's own it can be reused while the caster tries stands.
        const pack = onCaster ? build()
          : memoGet('e|' + caster.uid + '|' + caster.ver + '|' + s.id + '|' + cell.x + ',' + cell.y, build);
        const r = Lua.test(s.cp, pack.env);
        // A unit-only predicate on a bare block is simply not a legal target;
        // count only entities we could not evaluate (a real env gap).
        if (r.ok !== true && r.ok !== false && pack.u) bump(cov.skipped, '施放条件无法求值#' + s.id);
        return r.ok === true;
      } catch { return false; }
      finally { sim.probe = wasProbe; }
    }
    const mapProxy = {__get(k) {
      if (k === 'curUnit') return U(sim.turnOwner);
      if (k === 'mgr') return {actionSequenceTable: {units: units.filter(u => u.alive).map(u => U(u))}};
      throw new Lua.Unknown('map.' + k);
    }, __methods: {
      GetCurTurn: () => sim.round,
      getDiamondBlocks: (x, y, min, max, _skip, fn) => {
        const out = [];
        for (const c of grid.cells.values()) {
          const d = Math.abs(c.x - x) + Math.abs(c.y - y);
          if (d < (min || 0) || d > (max || 0)) continue;
          const bp = blockProxy(c);
          if (typeof fn !== 'function' || Lua.truthy(fn(bp))) out.push(bp);
        }
        return out;
      },
      getAllBlocks: () => [...grid.cells.values()].map(blockProxy),
      getAllUnitBlocks: () => units.filter(u => u.alive)
        .map(u => blockProxy({x: u.x, y: u.y, h: grid.at(u.x, u.y)?.h || 0})),
      getRectBlocks: (x, y, w, h, fn) => {
        const out = [];
        for (const c of grid.cells.values()) {
          if (Math.abs(c.x - x) > (w || 1) || Math.abs(c.y - y) > (h || 1)) continue;
          const bp = blockProxy(c);
          if (typeof fn !== 'function' || Lua.truthy(fn(bp))) out.push(bp);
        }
        return out;
      },
      getLineBlocks: (x, y, min, max, _skip, fn) => {
        const out = [];
        for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
          for (let d = (min || 1); d <= (max || 1); d++) {
            const c = grid.at(x + dx * d, y + dy * d);
            if (!c) continue;
            const bp = blockProxy(c);
            if (typeof fn !== 'function' || Lua.truthy(fn(bp))) out.push(bp);
          }
        }
        return out;
      },
      mgr: {actionSequenceTable: {units: units.filter(u => u.alive).map(u => U(u))}},
      GetCurTurnMethod: () => sim.round,
      // Client `map:getBlock(ix, iz)` — 嘿咻！/利用物品/紧急传送 cast_param
      // 「return map:getBlock(target.temp_ix, target.temp_iz).temp_unit == nil」
      // asks whether the chosen block is free. Return the same block proxy
      // used by `block` so temp_unit / canStay / pit / ix / iz all resolve.
      getBlock: (x, y) => blockProxy(grid.at(Number(x), Number(y)) || {x: Number(x), y: Number(y), h: 0}),
      // In inspection mode a fixed mid-range value is used so condition
      // evaluation never advances the battle's deterministic RNG stream.
      // `lastRandom` exposes the ACTUAL die so a probability outcome can be
      // written to the log (33% arena statuses were otherwise invisible).
      Random: (n) => {
        const v = sim.probe ? Math.ceil(Math.max(1, n || 100) / 2)
                            : 1 + Math.floor(roll() * Math.max(1, n || 100));
        if (!sim.probe) sim.lastRandom = v;
        return v;
      },
      getNeighborUnitCount: (o, friend, range = 1) => {
        const c = o?.__unit;
        if (!c) return 0;
        return units.filter(x => x.alive && x !== c && (friend ? x.side === c.side : x.side !== c.side) && manhattan(x, c) <= range).length;
      },
      GetNeighborBlockFieldStatusCount: () => 0,
    }};
    const BUILTIN = {
      pairs: v => ({__iter: Array.isArray(v) ? v.map((x, i) => [i + 1, x]) : []}),
      ipairs: v => ({__iter: Array.isArray(v) ? v.map((x, i) => [i + 1, x]) : []}),
      print: () => null, printerror: () => null, tostring: v => String(v ?? 'nil'), tonumber: v => Number(v),
      math: {abs: Math.abs, floor: Math.floor, ceil: Math.ceil, max: Math.max, min: Math.min,
             huge: 1e300, random: () => 0.5, sqrt: Math.sqrt, pow: Math.pow},
      // Round 32: client namespaces queried by activation conditions.
      CLASS_TYPE: {UNIT_SPEC: 1, SKILL_SPEC: 2, BUFF_SPEC: 3, PROPS: 4, TRAP: 5},
      Battle: {Entity: {Type: {Unit: 1, Props: 2, Trap: 3, Widget: 4}},
               AITemplate: {NONE: 0, MELEE: 1, RANGED: 2, SUPPORT: 3}},
      CLASS: {UNIT_SPEC: 1, SKILL_SPEC: 2},
      BehaviorDecision: () => true,
      CasterLocation: (a, b) => ({x: owner?.x || 0, y: owner?.y || 0}),
      IsInDelay: () => false,
      isFieldStatus: () => false,
      checkForget: () => false,
      table: {insert: (arr, v) => { if (Array.isArray(arr)) arr.push(v); return arr; },
              remove: (arr, v) => { if (Array.isArray(arr)) { const i = arr.indexOf(v); if (i >= 0) arr.splice(i, 1); } return arr; },
              concat: (a, b) => (Array.isArray(a) ? a : []).concat(Array.isArray(b) ? b : []),
              unpack: a => Array.isArray(a) ? a : [],
              sort: (a, f) => Array.isArray(a) ? a : []},
      string: {format: (f, ...a) => String(f || '').replace(/%[sd%]/g, () => String(a.shift() ?? '')),
               sub: (s, i, j) => String(s ?? '').slice((i || 1) - 1, j || undefined),
               find: (s, p) => String(s ?? '').indexOf(String(p ?? '')) + 1 || null,
               // `for x in string.gmatch(s, "%d+") do` — generic-for consumes
               // an __iter table of [index, value] pairs.
               gmatch: (s, pattern) => {
                 const src = String(s ?? '');
                 let re;
                 try { re = new RegExp(String(pattern ?? '%d+')
                   .replace(/%d/g, '\\d').replace(/%w/g, '\\w').replace(/%s/g, '\\s')
                   .replace(/%a/g, '[A-Za-z]'), 'g'); }
                 catch { re = /\d+/g; }
                 const found = [];
                 let m;
                 while ((m = re.exec(src)) !== null) {
                   found.push(m[0]);
                   if (!m[0]) re.lastIndex++;
                 }
                 return {__iter: found.map((v, i) => [i + 1, v])};
               }},
    };
    // State predicate shared by TargetState / CasterStatus:
    // (profession category, buff category, hp_attenuation state, unit tag) — 0 = any, tables allowed.
    const unitState = (u, prof, cat, hp, tag) => !!u &&
      inList(u.prof, prof) && (!cat || (Array.isArray(cat) ? cat.some(c => u.buffs.some(b => b.def.cat === c)) : u.buffs.some(b => b.def.cat === cat))) &&
      inList(hpState(u), hp) && (tag === undefined || tag === null || tag === 0 || hasUnitTag(u, tag));
    function luaEnv(inst, ctx, probe = false) {
      const owner = inst.owner;
      const c = ctx || {};
      const flags = {counter: c.counter, sub: c.sub, targets: c.targets, start: c.start, firstHit: c.firstHit,
                     origin: c.origin, area: c.area, prop: c.prop};
      const skillP = c.skill ? S(c.skill, c.attacker, c.defender || c.target, flags) : null;
      const target = c.attacker === owner ? (c.defender || c.target) : c.defender === owner ? c.attacker : (c.target || null);
      const combat = () => !!(c.attacker && c.skill);
      const ACF = {__get(k) { throw new Lua.Unknown('ActiveConditionFuncs.' + k); }, __methods: {
        // CombatDecision(攻击性质 0任意/1主动/2反击, 攻击距离 0任意/1近战/2远程/3范围,
        //                伤害类型列表, 目标数 0任意/1单体/2多体, 命中方式列表)
        CombatDecision: (kind, reach, types, count, hits) => {
          if (!combat()) return false;
          const k = c.counter ? 2 : (c.sub ? 3 : 1);
          if (!inList(k, kind)) return false;
          const single = (c.targets?.length ?? 1) <= 1 && (c.skill.area?.type || 'single') === 'single';
          const r = single ? (c.skill.rt === 3 ? 2 : 1) : 3;
          if (reach && !inList(r, reach) && !(Array.isArray(reach) ? false : reach === 3 && !single)) return false;
          if (!inList(c.skill.dt, types)) return false;
          if (count && !inList(single ? 1 : 2, count)) return false;
          if (!inList(c.skill.hm, hits)) return false;
          return true;
        },
        AttackDirection: (d) => !!(c.attacker && c.defender && relPos(c.attacker, c.defender) === d),
        IsMainSkill: () => !c.sub,
        GetCurTurn: () => sim.round,
        GetNeighborBlockFieldStatusCount: () => 0,
        CasterAttribute: (name) => name === 'tp' ? owner.tp : name === 'hp' ? owner.hp : name === 'hp_max' ? maxHpOf(owner) : 0,
        TargetAttribute: (name) => !target ? 0 : name === 'tp' ? target.tp : name === 'hp' ? target.hp : name === 'hp_max' ? maxHpOf(target) : 0,
        TargetState: (prof, cat, hp, tag) => unitState(target, prof, cat, hp, tag),
        SkillTargetState: (prof, cat, hp, tag) =>
          unitState(c.target || c.defender || target, prof, cat, hp, tag),
        CasterStatus: (prof, cat, hp, tag) => unitState(owner, prof, cat, hp, tag),
        TargetBuffCount: (bt, mid, sub) => !target ? 0 : buffCount(target, b => (!bt || b.def.bt === bt) && (!mid || b.def.mi === mid) && (!sub || b.def.sb === sub)),
        CombatDistace: () => (c.attacker && c.defender ? manhattan(c.attacker, c.defender) : 0),
        CasterLocation: (a, b, list) => {
          // Two client forms: (0,1) means "any location" and (a,b,terrains)
          // tests the caster's terrain type.
          if (!Array.isArray(list)) return true;
          return list.includes(grid.at(owner.x, owner.y)?.t);
        },
        BehaviorDecision: () => true,
        IsInDelay: () => false,
        checkForget: () => false,
        TargetLocation: (a, b, list) => {
          if (!Array.isArray(list) || !target) return false;
          return list.includes(grid.at(target.x, target.y)?.t);
        },
      }};
      const BattleSkill = {
        isInitiativeAttack: (s, o) => !!(s?.__skill && o?.__unit && s.__caster === o.__unit && !s.__flags.counter && !s.__flags.sub),
        isInitiativeDefence: (s, o) => !!(s?.__skill && o?.__unit && s.__caster && s.__caster !== o.__unit && !s.__flags.counter &&
          (s.__flags.targets || []).includes(o.__unit)),
        isCounterAttack: (s, o) => !!(s?.__skill && o?.__unit && s.__caster === o.__unit && s.__flags.counter),
        isCounterDefence: (s, o) => !!(s?.__skill && o?.__unit && s.__caster !== o.__unit && s.__flags.counter &&
          (s.__flags.targets || []).includes(o.__unit)),
      };
      const battle = {AITemplate: {AI_ROLER_STATE: {War: 1, Peace: 0},
        NONE: 0, MELEE: 1, RANGED: 2, SUPPORT: 3, WAR: 1, PEACE: 0}};
      const Battle = {__get(k) {
        if (k === 'ActiveConditionFuncs') return ACF;
        if (k === 'Skill') return BattleSkill;
        if (k === 'Entity') return {Type: {Unit: 1, Props: 2, Trap: 3, Widget: 4}};
        if (k === 'AITemplate') return {AI_ROLER_STATE: {War: 1, Peace: 0}};
        throw new Lua.Unknown('Battle.' + k);
      }};
      return Object.assign({}, BUILTIN, {owner: U(owner), target: U(target), skill: skillP, map: mapProxy,
        buff: inst.buff ? B(inst.buff) : null, Database, Battle, self: null,
        // Round 28: extra client bindings used by speciality.dynamic_param.
        AITemplate: {NONE: 0, MELEE: 1, RANGED: 2, SUPPORT: 3, WAR: 1, PEACE: 0},
        Game: {DataUtil: {getTemplate: (table, id) => {
          if (table === 'buff') {
            const b = M?.buffs?.[id] || {};
            return {id, buff_type: b.bt || 0, middle_type: b.mt || 0,
                    sub_type: b.su || 0, category: b.cat || 0};
          }
          if (table === 'skill') return M?.skills?.[id] || {};
          return {};
        }}},
        unit: U(owner),
      CasterLocation: (a, b) => {
          const pos = {x: owner?.x || 0, y: owner?.y || 0};
          if (a === undefined) return pos;
          return (a === 0 && b === 1) ? true : pos;
        },
        battle,
        // `block` is only materialised for conditions that actually read it;
        // otherwise keep the cheap static empty block so unrelated Lua stays
        // byte-for-byte compatible with earlier rounds.
        block: (() => {
          if (c.block) return c.block;
          const src = String(inst.spec?.c || '');
          if (!/block\s*[.:]/.test(src)) return {trap: null, temp_trap: null, temp_unit: null, pit: false, type: 1};
          const cell = c.blockCell || (c.target && Number.isFinite(c.target.x) ? c.target
                      : c.origin && Number.isFinite(c.origin.x) ? c.origin : null);
          if (!cell) return {trap: null, temp_trap: null, temp_unit: null, pit: false, type: 1};
          return blockProxy(cell, c.blockTrap);
        })(),
        attr: {crit_damage: owner ? K.CritBaseDamage + attr(owner, 'CRIT_DAMAGE') : 0,
               crit_ratio: owner ? K.CritBaseChance + attr(owner, 'CRIT_RATIO') : 0,
               physic_attack: owner ? attr(owner, 'PHYSIC_ATTACK') : 0,
               spell_attack: owner ? attr(owner, 'SPELL_ATTACK') : 0},
        mcall: {cur_limit_count: 0},
        // Round 29: Lua table helpers and AI-decision stubs used by
        // dynamic_param scripts from the newly decrypted client bytecode.
        Table: {unpack: (v) => v, insert: (v, x) => v, getn: (v) => (v?.length || 0),
                Contains: (v, x) => Array.isArray(v) ? v.includes(x) : false},
        // `battle` in the client carries BOTH the current unit and the AI role
        // state enum; a duplicate key here used to shadow AITemplate.
        battle: Object.assign({}, battle, {curUnit: U(sim.turnOwner), round: sim.round}),
        BehaviorDecision: () => true});
    }

    /* ---------- buffs ---------- */
    function armorOf(u, kind) {
      return u.buffs.reduce((a, b) => a + (b.armor?.[kind] || 0), 0);
    }
    function shieldPartsOf(u) {
      const out = [];
      for (const b of u.buffs || []) {
        for (const p of b.shieldParts || []) {
          if (!b.alive === undefined || true) out.push(Object.assign({}, p, {stacks: b.stacks,
            total: (p.perLayer || 0) * b.stacks, active: !!b.armor?.[p.kind]}));
        }
      }
      return out;
    }
    function immuneTo(u, def, inst) {
      if (!def.imm && def.bt !== 3) return false;
      for (const i of unitSpecs(u)) {
        if (i.spec.t !== 'IMMUNE') continue;
        // Client JSON `sparam.buff_category` restricts an IMMUNE row to a
        // category LIST: 「免疫致盲」#5475 [94], 「免疫生命流失/持续伤害」
        // #242 [10,54]. Without this the row either does nothing (a row with
        // all-zero p) or, worse, immunises against EVERY debuff.
        const cats = i.spec.sj?.buff_category;
        if (Array.isArray(cats) && cats.length) {
          if (!cats.map(Number).includes(Number(def.cat))) continue;
          if (cond(i, {})) return i;
          continue;
        }
        const [big, eff, bid] = i.spec.p;
        if (bid && bid === inst) return cond(i, {}) && i;
        const bit = effectBit(def.et);
        if (eff && bit && (eff & (1 << (bit - 1)))) return cond(i, {}) && i;
        if ((big & 4) && def.bt === 3) return cond(i, {}) && i;
        if ((big & 512) && (def.mt === 'Control' || def.su === 'StrongControl' || def.su === 'WeakControl' || CONTROL_SKIP.has(def.et))) return cond(i, {}) && i;
      }
      return false;
    }
    function addBuff(target, id, turns, stacks, src, opts = {}) {
      if (target && !target.base) {
        // Battle.Entity.Type.Props: a prop cannot hold buffs. The client
        // applies such effects to the object's owner / the triggering unit.
        const real = target.owner?.base ? target.owner : (src?.base ? src : null);
        if (!real) return null;
        target = real;
      }
      // `opts.def` supports SYNTHETIC buff definitions (CHANGE_WEATHER builds
      // one from the weather table; a weather id is NOT a buff id).
      const def = opts.def || M?.buffs?.[id];
      if (!def || !target?.alive) { if (!def) bump(cov.skipped, 'BUFF#' + id + '(缺数据)'); return null; }
      // active_param is NOT an add-time gate (see buffOn): the buff is added
      // and simply stays dormant while its predicate is false. Rejecting it
      // here dropped 命途所至's [▼速度4] whenever it happened to be applied a
      // moment before 霜佑之印, and dropped 8801 on 贝拉 for good.
      if (!opts.force && immuneTo(target, def, id)) { log(`${target.name} 免疫「${def.n}」`); return null; }
      const cat = def.cat && M.buffCats?.[def.cat];
      const tierOf = bid => Number(M.buffTiers?.[bid] || 0);
      const newTier = tierOf(id);
      if (cat && (cat[0] === 'CategoryMutex' || cat[0] === 'AbsoluteMutex')) {
        // Client buff_group tiers: 攻击3 (tier 3) immediately replaces 攻击2
        // (tier 2) of the same category, but a lower tier must never wipe a
        // higher one. This matters for AURAS: 麦莎's 「协战」 aura re-applies
        // 攻击2 on every refresh, which used to delete 科尔's 攻击3 from
        // 烟幕游击 within the same action (the effect never took hold).
        const sameCat = target.buffs.filter(b => b.id !== id && b.def.cat === def.cat);
        // Only compare tiers when BOTH sides are declared; an ungraded buff
        // keeps the legacy "new replaces old" behaviour.
        const higher = newTier > 0 && sameCat.some(b => tierOf(b.id) > newTier);
        if (higher) {
          bump(cov.skipped, '低级增益被高等级顶替');
          return null;
        }
        target.buffs = target.buffs.filter(b => b.id === id || b.def.cat !== def.cat ||
          (newTier > 0 && tierOf(b.id) > newTier && tierOf(b.id) > 0));
      }
      const t = turns > 0 ? turns : Infinity;
      let b = target.buffs.find(x => x.id === id && !x.aura === !opts.aura);
      const prevStacks = b ? b.stacks : null;
      const prevTurns = b ? b.turns : null;
      const prevActionScoped = b ? b.actionScoped : null;
      if (b) {
        if (t >= b.turns) { b.age = 0; b.total = t; }
        b.turns = Math.max(b.turns, t);
        b.stacks = Math.min(Math.max(1, def.sc || 1), b.stacks + Math.max(1, stacks || 1));
        // A longer-lived grant of the same buff overrides the action scope.
        if (!opts.actionScoped) b.actionScoped = false;
      } else {
        b = {id, def, holder: target, turns: t, total: t, age: 0, stacks: Math.min(Math.max(1, def.sc || 1), Math.max(1, stacks || 1)), src,
             aura: !!opts.aura, weather: !!opts.weather, triggered: false, armor: null,
             actionScoped: !!opts.actionScoped && !opts.aura};
        target.buffs.push(b);
      }
      // Shields are sized when applied (PHYSIC_ARMOR / SPELL_ARMOR).
      // The client grants the listed percentage PER STACK (buff 3263「后备隐藏
      // 脂肪」: 10% max-HP shield × 6 stacks = 60%). Previously we overwrote
      // the value without multiplying by stacks, so 6 layers gave only 10%.
      b.shieldParts = [];
      for (const sid of def.sp) {
        const raw = M.specs[sid];
        if (!raw || (raw.t !== 'PHYSIC_ARMOR' && raw.t !== 'SPELL_ARMOR')) continue;
        const s = raw.dp ? resolvedSpec({spec: raw, owner: target, src: 'buff'}, {target: src || target}) : raw;
        const who = s.s && String(s.s).includes('1') && src ? src : target;
        const attrVal = attrById(who, s.p[0]);
        let v = attrVal * s.p[1] / 100;
        if (s.p[2]) v = Math.min(v, attrById(who, s.p[2]) * (s.p[3] || 100) / 100);
        const factor = 1 + attr(target, 'BE_ARMOR_FACTOR') / 100;
        const perLayer = Math.round(v * factor);
        const kind = s.t === 'PHYSIC_ARMOR' ? 'phys' : 'spell';
        const total = perLayer * b.stacks;
        b.armor = b.armor || {phys: 0, spell: 0};
        b.armor[kind] = total;
        b.shieldParts.push({buff: id, buffName: def.n || '', spec: sid, kind,
          attr: attrName(s.p[0]), attrValue: Math.round(attrVal), pct: s.p[1],
          source: who === target ? '自身' : '施法者', perLayer, stacks: b.stacks,
          factor: Math.round(factor * 100) / 100, total, note: s.n || ''});
      }
      touch(target);
      // Client active_time 58 is BUFF_CHANGE: it fires only when the buff
      // ACTUALLY changed. Re-applying a buff already at its stack cap (e.g.
      // 伊瑟琳德「血羽千刃-触发枷锁器」5648, sc=1) previously re-fired 58 on
      // every call, which re-ran the very at-58 speciality that applied it —
      // an infinite self-trigger chain stopped only by the depth-6 guard.
      const buffChanged = prevStacks === null || b.stacks !== prevStacks ||
        b.turns !== prevTurns || b.actionScoped !== prevActionScoped;
      if (buffChanged && !opts.aura) noteChanged(target, b);
      if (!opts.aura) {
        // Give conditions/dynamic params the changed buff + its stack delta
        // (`FindChangedBuff(3263).stack_count_change`).
        if (buffChanged) fire(58, target, {target: src || target, changedBuff: b, stackChange: prevStacks === null
          ? b.stacks : Math.max(0, b.stacks - prevStacks), changedBuffId: id});
        if (def.bt === 3 && src && src !== target) fire(57, src, {attacker: src, defender: target, target});
      }
      const dormant = !buffOn(b);
      if (!opts.quiet && def.ui !== false) log(`${target.name} 获得「${def.n}」${Number.isFinite(t) ? `（${t} 回合）` : ''}${b.stacks > 1 ? ` ×${b.stacks}` : ''}` +
        (dormant ? '（激活条件暂不满足，暂未生效）' : ''));
      // REPLACE_SKILL / GET_EXTRA_SKILL declared at active_time 1 on a BUFF
      // (7509「切换成【重击】」→ 25150, 8850 → 29951, 7583 金狮形态 →
      // 25241) are live only while that buff exists AND is active.
      if (!opts.aura && !dormant) applyBuffSwaps(target, b);
      return b;
    }
    // Only swaps that actually happened are recorded for the revert. 8850
    // lists four 星核·造物 variants (21460 / 21516 / 21906 / 21907 → 21472);
    // recording the three that were NOT on the bar made the removal turn
    // 星核·位移 back into the first listed variant #21460 (non-instant).
    function applyBuffSwaps(u, b) {
      if (b.buffSwaps) return;
      b.buffSwaps = [];
      for (const sid of b.def.sp || []) {
        const sp = M?.specs?.[sid];
        if (!sp || (AT_ALIAS[sp.at] || sp.at) !== 1) continue;
        if (sp.t !== 'REPLACE_SKILL' && sp.t !== 'GET_EXTRA_SKILL') continue;
        const inst = {spec: sp, sid, owner: u, buff: b, src: 'buff', name: b.def.n, skill: null};
        if (!cond(inst, {target: u, defender: u})) continue;
        if (sp.t === 'REPLACE_SKILL' && sp.p[0] && sp.p[1] && sp.p[0] !== sp.p[1]) {
          if (replaceSkill(u, sp.p[0], sp.p[1], b.def.n)) b.buffSwaps.push([sp.p[1], sp.p[0]]);
        } else if (sp.t === 'GET_EXTRA_SKILL' && sp.p[0]) {
          if (grantSkill(u, sp.p[0], b.def.n)) b.buffSwaps.push([sp.p[0], 0]);
        }
      }
    }
    function revertBuffSwaps(u, b, label) {
      const list = b.buffSwaps || [];
      b.buffSwaps = null;
      for (let i = list.length - 1; i >= 0; i--) {
        const [to, from] = list[i];
        if (from) replaceSkill(u, to, from, label);
        else if (u.skills.some(s => Number(s.id) === Number(to))) {
          u.skills = u.skills.filter(s => Number(s.id) !== Number(to));
          rebuildSkillState(u);
          log(`${u.name} 失去技能「${skillRec(to)?.n || to}」（${label}）`);
        }
      }
    }
    // A buff whose active_param flips (4920 士气高昂 tp ≥ 7, 4986 先祖之狙击点
    // on a trap, 8850 while 8801 is live) adds / removes its skill swaps so
    // the AI always decides on the bar the client would show.
    function syncBuffSwaps(u) {
      if (!u?.alive) return;
      for (const b of u.buffs.slice()) {
        if (b.aura) continue;
        const on = buffOn(b);
        if (on && !b.buffSwaps) applyBuffSwaps(u, b);
        else if (!on && b.buffSwaps) revertBuffSwaps(u, b, `${b.def.n} 失效`);
      }
    }
    function attrById(u, id) {
      const n = attrName(id);
      if (n === 'HP') return u.hp;
      if (n === 'TP') return u.tp;
      if (n === 'HP_LOST') return maxHpOf(u) - u.hp;
      return attr(u, n || 'HP_MAX');
    }
    function removeBuff(u, b, reason) {
      const i = u.buffs.indexOf(b);
      if (i < 0) return;
      u.buffs.splice(i, 1);
      touch(u);
      // Revert buff-scoped skill changes (罗格妮达 7509, 贝拉 8850 …).
      revertBuffSwaps(u, b, `${b.def.n} 结束`);
      if (!b.aura) {
        // active_time 58 covers REMOVAL too: client conditions read
        // `owner.changed_buffs` and `v.isDeleted == false` to distinguish a
        // gained buff (#30584, #31405, #28290), and FindChangedBuff(id) with
        // a NEGATIVE stack_count_change for a lost one. Before this, removal
        // fired 58 with no changed buff at all, so all 27 such conditions
        // silently saw a stale/null change set.
        b.deleted = true;
        noteChanged(u, b);
        fire(65, u, {target: u});
        fire(58, u, {target: u, changedBuff: b, changedBuffId: b.id, stackChange: -b.stacks});
      }
      if (reason && b.def.ui !== false && !b.aura) log(`${u.name} 的「${b.def.n}」${reason}`);
    }
    const hasEffect = (u, et) => u.buffs.some(b => b.def.et === et);
    // A client speciality is ACTIVE when it is on the unit (passive / buff),
    // within its per-turn limit, and its activation Lua currently holds.
    // `unit.flags.*` is only set when runSpec() happens to execute that
    // speciality; checking unitSpecs() directly is authoritative at any time.
    // This is what makes IGNORE_EVADE / FORCE_BACKSTAB / NOT_RECOVER_TP /
    // IGNORE_ARMOR / FORBIDDEN_RECOVER etc. actually take effect.
    function specActive(u, type, ctx = {}) {
      if (!u || !u.alive) return null;
      const c = Object.assign({attacker: u, defender: u, target: u}, ctx);
      return unitSpecs(u).find(i => i.spec.t === type && limitOk(i) && cond(i, c)) || null;
    }
    // Many client modifiers (IGNORE_EVADE / IGNORE_PARRY / IGNORE_ARMOR /
    // FORCE_BACKSTAB …) are declared on the SKILL's speciality list, not on
    // the unit. `unitSpecs()` never sees those, so check `skill.sp` too.
    function skillSpecActive(s, owner, type, ctx = {}) {
      if (!s || !owner) return null;
      for (const sid of s.sp || []) {
        const sp = M?.specs?.[sid];
        if (!sp || sp.t !== type) continue;
        const inst = {spec: sp, sid, owner, src: 'skill:' + s.id, name: sp.n, skill: s};
        if (limitOk(inst) && cond(inst, Object.assign({attacker: owner, defender: owner,
                                                       target: owner, skill: s}, ctx))) return inst;
      }
      return null;
    }
    const activeSpec = (u, s, type, ctx) => specActive(u, type, ctx) || skillSpecActive(s, u, type, ctx);

    /* ---------- triggers ---------- */
    // The client stores `limit_count_turn` / `cur_limit_count_turn` on every
    // reactive speciality. SPECIALITY_COUNT_TURN buffs (including leader
    // auras such as 「警戒次数+1」) add to that per-turn allowance. Derive the
    // bonus from the unit's own specialities instead of hard-coding a type.
    function countBonusMap(u) {
      if (!u) return {};
      if (u._countBonusVer === u.ver && u._countBonus) return u._countBonus;
      const out = {};
      const byId = SUB?.specialityTypes || {};
      const ids = Object.fromEntries(Object.entries(byId).map(([k, v]) => [Number(v), k]));
      for (const inst of unitSpecs(u)) {
        const s = inst.spec;
        if (s.t !== 'SPECIALITY_COUNT_TURN') continue;
        const pp = s.p || [];
        let target = ids[Number(pp[1])];
        // p[0] != 0 rows name the speciality id that receives the extra use.
        if (!target && Number(pp[0]) > 0) {
          const named = M.specs[Number(pp[0])];
          target = named && ids[Number(named.t)] ? ids[Number(named.t)] : named?.t;
        }
        if (!target) continue;
        if (!cond(inst, {attacker: u, defender: u, target: u})) continue;
        out[target] = (out[target] || 0) + Math.max(1, Number(pp[2]) || 1);
      }
      u._countBonus = out;
      u._countBonusVer = u.ver;
      return out;
    }
    const countBonusOf = (u, t) => (u && u.alive ? (countBonusMap(u)[t] || 0) : 0);
    function limitOk(inst) {
      const s = inst.spec;
      if (!s.lt && !s.lc) return true;
      const k = (inst.buff ? 'b' + inst.buff.id : inst.src) + ':' + inst.sid;
      const L = inst.owner.limits[k] || (inst.owner.limits[k] = {turn: 0, total: 0});
      const lt = (s.lt || 0) + countBonusOf(inst.owner, s.t);
      if (s.lt && L.turn >= lt) return false;
      if (s.lc && L.total >= s.lc) return false;
      return true;
    }
    function spend(inst) {
      const k = (inst.buff ? 'b' + inst.buff.id : inst.src) + ':' + inst.sid;
      const L = inst.owner.limits[k] || (inst.owner.limits[k] = {turn: 0, total: 0});
      L.turn++; L.total++;
    }
    // active_time values that mean "a one-off numeric change at a battle /
    // turn boundary" rather than a persistent or attack-time stat modifier.
    const ONE_SHOT_ATTR_AT = new Set([25, 26, 27, 28, 52, 51]);
    // Timings whose client event carries no skill of its own.
    // 51/52 are the 「新回合特殊」variants of 28/27 and likewise carry no
    // event skill of their own; CAST_SKILL conditions there need the chained
    // skill bound to `skill` in the Lua env.
    const NO_EVENT_SKILL_AT = new Set([25, 26, 27, 28, 30, 43, 44, 51, 52]);
    // Client BEATTACKED (active_time 4) is ALSO raised on the ATTACKER's own
    // passives and buffs, with target = the unit that was hit. Proof in the
    // data: 圣光充能 #1914「增益，攻击后，驱散目标2个[增益]，每层减少1点能量」
    // (#9810-9812 / #9075), 香径影踪「（被动）攻击后，对目标施加[暗香]」(#7916),
    // 野狐塞娜 血棘之花 #28017 血沸 / #28018 伤口 — all at 4, tt 2 (enemy) and
    // guarded by isInitiativeAttack(skill, owner). The data cannot attribute an
    // UNGUARDED at-4 row to a side, so only rows whose condition REQUIRES the
    // owner to be the attacker run there; on the defender side those rows can
    // never pass, so nothing fires twice.
    const ATTACKER_GUARD = /isInitiativeAttack\(\s*skill\s*,\s*owner\s*\)|skill\.owner\s*==\s*owner\b|\bowner\s*==\s*skill\.owner\b/;
    const attackerAt4 = inst => ATTACKER_GUARD.test(String(inst.spec?.c || ''));
    // One-shot timed MODIFY_ATTRIBUTE (active_time 25/26/27/28 …), e.g.
    // 「战斗开始时回复1点能量」. p = [attribute, flat, percent, 0].
    // These are EVENTS, not permanent stat rows — attrCompute() deliberately
    // ignores every at!==1 modifier. Apply to the LIVE value, with the same
    // limits as the rest of the engine. Only the attributes the client's
    // 14 timed rows actually use are writable; everything else is ignored.
    function applyTimedAttribute(inst, ctx) {
      const u = inst.owner;
      if (!u?.alive) return;
      const p = inst.spec.p || [];
      const name = attrName(p[0]);
      const flat = Number(p[1]) || 0, pct = Number(p[2]) || 0;
      if (!cond(inst, ctx)) return;
      const change = (get, set, label) => {
        const before = get();
        const after = Math.max(0, Math.round(before * (1 + pct / 100) + flat));
        set(after);
        log(`${u.name} ${label} ${before} → ${after}（${inst.name || name}）`);
        bump(cov.executed, 'TIMED_MODIFY_ATTRIBUTE');
        touch(u);
      };
      if (name === 'TP') change(() => u.tp, v => { u.tp = Math.min(attr(u, 'TP_MAX'), v); }, '能量');
      else if (name === 'HP') change(() => u.hp, v => { u.hp = Math.min(maxHpOf(u), v); }, '当前生命');
      else if (name === 'HP_MAX' || name === 'SPEED' || name === 'MOBILITY') {
        u.prewar = u.prewar || {};
        const row = u.prewar[name] || (u.prewar[name] = {flat: 0, pct: 0});
        row.flat += flat; row.pct += pct;
        log(`${u.name} ${name} ${flat >= 0 ? '+' : ''}${flat}${pct ? ` ${pct}%` : ''}（${inst.name || name}）`);
        bump(cov.executed, 'TIMED_MODIFY_ATTRIBUTE');
        touch(u);
      }
    }
    // `only` (optional) restricts the batch to matching instances and leaves
    // the unit's timing marks alone — used to raise a timing on a unit that
    // is not the event's subject (the ATTACKER's side of 被攻击后).
    function fire(at, u, ctx = {}, only = null) {
      if (!u || !M) return;
      cov.firedTimings.add(String(at));
      const prevChanged = sim.changedBuffs;
      if (at === 58 && ctx.changedBuff) {
        const b = ctx.changedBuff;
        b.stackChange = ctx.stackChange || 0;
        sim.changedBuffs = [b];
      }
      const ownQueue = !sim.removeQueue;
      if (ownQueue) sim.removeQueue = new Map();
      try {
      if (!only) {
        let live = sim.live.get(u);
        if (!live) sim.live.set(u, live = new Set());
        live.add(at);
        (u.turnStates || (u.turnStates = new Set())).add(at);
      }
      // Client timing resolution is a FIXED POINT within one event: a buff
      // granted by another spec at this same active_time contributes its own
      // specs to the same batch. 静聆神谕 #28900 (BUFF at27) grants 8808 whose
      // #28920 (ACTED_ACT at27) declares the forced 3-skill choice; taking a
      // single snapshot of unitSpecs() silently dropped it. Re-scan a bounded
      // number of times, keyed by (source, spec id) so nothing runs twice.
      const firedHere = new Set();
      for (let pass = 0; pass < 3; pass++) {
        let ran = false;
        // Client JSON `sparam.priority` orders specialities that share this
        // active_time (光能箭步骤 5000 → 浮游炮结算 1000 → 光环监听 -2000).
        // It is a ROW-level order, distinct from speciality_type.priority
        // (`pr`, used inside runSkillSpecs). Stable sort keeps the declared
        // order for rows without an explicit priority. fire() is a hot path,
        // so cache "does this roster have ANY priority row" per spec version
        // and skip sorting entirely for the vast majority of units.
        const batch = unitSpecs(u);
        if (u._prioVer !== u.ver) {
          u._prioVer = u.ver;
          u._hasPrio = batch.some(i => i.spec.sj?.priority !== undefined);
        }
        const ordered = u._hasPrio ? batch.slice().sort((p, q) =>
          (Number(q.spec.sj?.priority) || 0) - (Number(p.spec.sj?.priority) || 0)) : batch;
        for (const inst of ordered) {
          const s = inst.spec;
          const key = (inst.buff ? 'b' + inst.buff.id : inst.src || '') + ':' + inst.sid;
          if (firedHere.has(key)) continue;
          if ((AT_ALIAS[s.at] || s.at) !== at) continue;
          if (only && !only(inst)) continue;
          firedHere.add(key);
          // active_time 1 MODIFY_ATTRIBUTE is a PERMANENT stat modifier and
          // belongs to attrCompute(). The SAME speciality type at battle /
          // turn boundaries is a ONE-SHOT numeric change: 「战斗开始时回复
          // 1点能量」 (#19946 法卡尔·SP), 初始能量+3, 「战斗开始时失去30%
          // 生命」. STATIC_TYPES used to skip all of them, so 法卡尔·SP
          // started with 3 TP and could not afford 「戍卫箭幕」 (4 TP).
          // ONLY these boundary timings are events. at=2/15/16/31/34 are
          // ATTACK-TIME conditional stat rows (731+227+… of them) that
          // attrCompute() already evaluates with the attacker/defender in
          // context — running them through fire() would double-apply them and
          // expose Lua predicates that are meaningless without an attack.
          if (s.t === 'MODIFY_ATTRIBUTE' && ONE_SHOT_ATTR_AT.has(at)) {
            applyTimedAttribute(inst, ctx);
            ran = true;
            continue;
          }
          if (STATIC_TYPES.has(s.t) && s.t !== 'GET_EXTRA_SKILL' && s.t !== 'REPLACE_SKILL') continue;
          runSpec(inst, ctx);
          ran = true;
        }
        if (!ran) break;
      }
      } finally {
        if (at === 58 && ctx.changedBuff) sim.changedBuffs = prevChanged;
        if (ownQueue) {
          const q = sim.removeQueue;
          sim.removeQueue = null;
          for (const [b, c] of q) settleTriggeredRemove(b, c);
        }
      }
    }
    function runSkillSpecs(skill, caster, at, ctx, skip, aoeUnits) {
      // Client `speciality_type.priority` orders specialities sharing one
      // active_time: SPECIFY_ATTRIBUTE_VALUE (100) → DISPEL / REMOVE /
      // REMOVE_BUFF (1) → normal (0) → CONVERT_ATTRIBUTE (-1). Without it
      // 命途所至 applied [▼速度4] and then DISPEL'd its own debuff, so the
      // 「速度减少200点」 the user expects never survived the cast.
      // JSON sparam.priority dominates, speciality_type.priority breaks ties.
      const ordered = (skill.sp || []).slice().sort((a, b) =>
        ((Number(M?.specs?.[b]?.sj?.priority) || 0) * 100 + (Number(M?.specs?.[b]?.pr) || 0)) -
        ((Number(M?.specs?.[a]?.sj?.priority) || 0) * 100 + (Number(M?.specs?.[a]?.pr) || 0)));
      for (const sid of ordered) {
        const spec = M?.specs?.[sid];
        if (!spec || (AT_ALIAS[spec.at] || spec.at) !== at) continue;
        if (skip && skip.has(sid)) continue;   // merged as an extra damage segment
        if (STATIC_TYPES.has(spec.t)) continue;
        const inst = {spec, sid, owner: caster, src: 'skill:' + skill.id, name: skill.n, skill};
        // A head-skill AOE marker must hit EVERY enemy in the skill's OWN
        // (narrower) AOE, not just `primary`: 审判诸罪之光 #15386 declares
        // AOE 257 (1*6 middle column) + BUFF 5100, while DISPLAY_AOE widens
        // the damage footprint to AOE 256 (3*6). The middle-column marker is
        // what makes the follow-up's conditional +30% (70% → 100%) fire.
        if (aoeUnits?.length && at === 2 && Number(spec.tt) === 2 &&
            ['BUFF', 'DISPEL', 'REMOVE_BUFF'].includes(spec.t)) {
          for (const u of aoeUnits)
            runSpec(inst, Object.assign({}, ctx, {defender: u, target: u}));
        } else {
          runSpec(inst, ctx);
        }
      }
    }
    // Resolve speciality.dynamic_param. The client returns a positional list
    // (`return nil,nil,value,nil`), where a non-nil slot overwrites that param.
    // Results are cached per (spec, owner version, context tick) so the ~250
    // exported scripts don't get re-parsed for every attribute lookup.
    function resolvedSpec(inst, ctx) {
      const s = inst.spec;
      if (!s.dp) return s;
      const key = [s.dp, inst.owner?.uid, inst.owner?.ver, ctx?.target?.uid || 0,
                   ctx?.defender?.uid || 0, sim.tick].join('|');
      if (inst._dpKey === key && inst._dpSpec) return inst._dpSpec;
      const r = Lua.params(s.dp, luaEnv(inst, ctx || {}));
      if (r.unknown) {
        bump(cov.luaUnknown, 'dynamic:' + r.unknown);
        return s;
      }
      const p = (s.p || []).slice();
      for (let i = 0; i < p.length && i < (r.values || []).length; i++) {
        const v = r.values[i];
        if (v === null || v === undefined) continue;
        if (v && typeof v === 'object' && '__iter' in v) continue;
        const n = Number(v);
        if (Number.isFinite(n)) p[i] = n;
      }
      if (!sim.probe) bump(cov.executed, 'DYNAMIC_PARAM');
      inst._dpKey = key;
      inst._dpSpec = Object.assign({}, s, {p});
      return inst._dpSpec;
    }
    // Client `speciality` declares three trigger limits BEYOND limit_count /
    // limit_count_turn, all scoped more narrowly than the owner-wide counter
    // in limitOk():
    //   limit_count_command            (lcc)   once per (owner, action, spec)
    //   limit_count_per_entity_command(lcpec) once per (owner, action, spec, target)
    //   limit_count_per_entity_turn   (lcpet) once per (owner, round, spec, target)
    // A multi-hit / chain skill used to resolve such a row once per hit —
    // 「苍穹华光-对自己施加3个增益」#31415 fired 9 times in one action while
    // declaring command=1. Keep these in a separate map so the existing
    // owner-wide counters (and the 12 other limitOk() callers) are untouched.
    function scopedLimitOk(inst, ctx) {
      const s = inst.spec;
      if (!s.lcc && !s.lcpec && !s.lcpet) return true;
      const o = inst.owner, sid = inst.sid;
      const tgt = ctx?.target?.uid || ctx?.defender?.uid || 0;
      const act = sim.actionId || 0, rnd = sim.round;
      const map = sim.scopedLimits || (sim.scopedLimits = new Map());
      const seen = (key, epoch) => (map.get(key)?.epoch === epoch ? map.get(key).n : 0);
      const base = `${o?.uid || ''}|${sid}`;
      if (s.lcc && seen(`c|${base}`, act) >= s.lcc) return false;
      if (s.lcpec && seen(`ec|${base}|${tgt}`, act) >= s.lcpec) return false;
      if (s.lcpet && seen(`et|${base}|${tgt}`, rnd) >= s.lcpet) return false;
      return true;
    }
    function scopedSpend(inst, ctx) {
      const s = inst.spec;
      if (!s.lcc && !s.lcpec && !s.lcpet) return;
      const o = inst.owner, sid = inst.sid;
      const tgt = ctx?.target?.uid || ctx?.defender?.uid || 0;
      const act = sim.actionId || 0, rnd = sim.round;
      const map = sim.scopedLimits || (sim.scopedLimits = new Map());
      const bumpN = (key, epoch) => {
        const prev = map.get(key);
        map.set(key, {epoch, n: (prev?.epoch === epoch ? prev.n : 0) + 1});
      };
      const base = `${o?.uid || ''}|${sid}`;
      if (s.lcc) bumpN(`c|${base}`, act);
      if (s.lcpec) bumpN(`ec|${base}|${tgt}`, act);
      if (s.lcpet) bumpN(`et|${base}|${tgt}`, rnd);
    }
    function runSpec(inst, ctx) {
      inst = inst.spec?.dp ? Object.assign({}, inst, {spec: resolvedSpec(inst, ctx)}) : inst;
      const s = inst.spec;
      const fn = EFFECTS[s.t];
      if (sim.depth > 6) {
        bump(cov.skipped, '连锁触发过深');
        // Per-timing subtotal: lets the audit tell a BUFF_CHANGE (58)
        // self-trigger loop apart from legitimately deep reaction chains.
        bump(cov.skipped, '连锁触发过深@' + (AT_ALIAS[s.at] || s.at));
        return;
      }
      if (!limitOk(inst) || !scopedLimitOk(inst, ctx)) return;
      // `place_on_unit` specialities declare `block.temp_unit:isFriend(owner)`;
      // the client evaluates that once per AOE cell, not once for the whole
      // cast. Let PLACE_TRAP do its own per-unit check in that case.
      const perBlock = s.t === 'PLACE_TRAP' && /place_on_unit/.test(String(s.s || ''));
      // A CAST_SKILL-family row evaluated at a timing that carries NO event
      // skill (turn / battle start-end, 待机, 行动后, 重生后) is judged against
      // the skill it is about to cast: 伦伽勒·SP #20060 at 每人回合开始
      // 「return skill and target and (#枪影 < 4)」 could otherwise never hold.
      // Timings WITH an event skill (攻击后, 被击杀 …) keep that skill.
      const at0 = AT_ALIAS[s.at] || s.at;
      const condCtx = (!ctx.skill && /CAST_SKILL$/.test(s.t) && Number(s.p?.[0]) > 0 &&
          NO_EVENT_SKILL_AT.has(at0)) ? Object.assign({}, ctx, {skill: skillRec(Number(s.p[0])) || null}) : ctx;
      if (!perBlock && !cond(inst, condCtx)) {
        // Probability-gated extra effects (昏昏欲睡「33%概率受到[睡眠]」,
        // 宿命感召 …) are silent when the roll fails, so users cannot tell
        // whether the effect is missing or simply did not proc. Record the
        // failed roll once, without leaking it into the damage log.
        if (/Random\s*\(/.test(String(s.c || '')) && !sim.probe)
          log(`${inst.owner?.name || '单位'} 的「${inst.name || s.n || s.t}」概率判定未通过：` +
              `Random(100)=${sim.lastRandom ?? '?'}（条件 ${String(s.c).replace(/\s+/g, ' ').slice(0, 60)}）`);
        return;
      }
      // Every speciality with a client `skill_active_param` must also pass
      // that skill-scoped predicate (MULTI_CONSUME_TP / SKILL_CD /
      // DISABLE_SKILL / BUFF … 146 exported instances).
      if (s.sap && !skillCondOk(inst, ctx.skill, ctx)) return;
      if (!fn) { bump(cov.skipped, s.t); return; }
      spend(inst);
      scopedSpend(inst, ctx);
      if (inst.buff) inst.buff.triggered = true;
      bump(cov.executed, s.t);
      sim.depth++;
      try { fn(inst, ctx); } finally { sim.depth--; }
      // Defer to the end of the outermost fire() batch so every row of the
      // same buff at this timing (8403: ACTED_MOVE + ACTED_ACT) resolves first.
      if (inst.buff) {
        if (sim.removeQueue) { if (!sim.removeQueue.has(inst.buff)) sim.removeQueue.set(inst.buff, ctx); }
        else settleTriggeredRemove(inst.buff, ctx);
      }
    }
    // Client buffs often carry an ALWAYS-ON (active_time 1) REMOVE speciality
    // gated by `return buff.isTriggered`, e.g. 8403「附属被动-再动」#9552
    // 「BUFF触发后移除父级BUFF（一层）」. The client re-evaluates it as soon as
    // the buff has fired; at=1 rows are never "executed" by fire(), so the
    // buff used to stay forever and a 0-cost skill (霜蚀斩) on a later turn
    // still granted the 「基础耗能≥3」extra action. Evaluate those rows here.
    function settleTriggeredRemove(b, ctx) {
      if (!b?.holder || !b.holder.buffs.includes(b)) return;
      for (const sid of b.def?.sp || []) {
        const sp = M?.specs?.[sid];
        if (!sp || sp.t !== 'REMOVE' || (AT_ALIAS[sp.at] || sp.at) !== 1) continue;
        const ri = {spec: sp, sid, owner: b.holder, buff: b, src: 'buff', name: b.def.n};
        if (!cond(ri, Object.assign({}, ctx, {target: b.holder}))) continue;
        bump(cov.executed, 'REMOVE');
        EFFECTS.REMOVE(ri, ctx);
        if (!b.holder.buffs.includes(b) || b.stacks <= 0) break;
      }
    }
    function targetsOf(inst, ctx) {
      const s = inst.spec, o = inst.owner;
      if (s.t !== 'RANDOM_UNIT' && s.t !== 'RANDOM_BLOCK' && sim.selection?.length) {
        return sim.selection.filter(x => x?.alive);
      }
      if (s.t !== 'RANDOM_UNIT' && s.t !== 'RANDOM_BLOCK' && sim.randomTargets?.length) {
        const picked = sim.randomTargets;
        sim.randomTargets = null;
        return picked.filter(x => x?.alive);
      }
      const other = ctx.attacker === o ? ctx.defender : ctx.defender === o ? ctx.attacker : (ctx.target || null);
      const isUnit = v => v?.base && v.hp !== undefined;
      const tgt = (ctx.target && isUnit(ctx.target)) ? ctx.target : (isUnit(other) ? other : (ctx.target?.owner?.base ? ctx.target.owner : null));
      if (s.tc) return [ctx.attacker && ctx.attacker !== o ? ctx.attacker : (inst.buff?.src || o)].filter(x => x?.alive);
      switch (s.tt) {
        case 3: return [o];
        case 2: return tgt && tgt.side !== o.side ? [tgt] : [];
        case 1: return tgt && tgt.side === o.side ? [tgt] : [o];
        case 4: return tgt ? [tgt] : [o];
        // tt 5 = the CURRENT target when it is a friend other than the owner
        // — the mirror of tt 2. 猩红之触「攻击友军前，使目标回复1点能量…」
        // (#29064 TP+1 / #29062 ▲移动1 / #29063 ▲攻击2), 「使目标友军回复4点
        // 能量」(#6845). 「所有友军」 comes from an AOE hitting each ally, not
        // from tt 5. Returning every ally made 野狐塞娜's counter with 猩红之触
        // on 科尔 hand energy and buffs to her whole team. Only a row raised
        // with no unit target at all keeps the old all-allies meaning.
        case 5: return tgt ? (tgt.side === o.side && tgt !== o ? [tgt] : []) : alliesOf(o);
        default: return [tgt || o];
      }
    }

    /* ---------- damage ---------- */
    function restrainSpecs(a, d) {
      return (M?.restrain || []).filter(r => r.from === a.prof && r.to === d.prof).flatMap(r => r.sp);
    }
    function heightBonus(a, d, skill, ctx) {
      const fa = grid.at(a.x, a.y), fd = grid.at(d.x, d.y);
      const diff = (fa?.h ?? 0) - (fd?.h ?? 0);
      let b = diff >= hg.minDiff ? hg.up : diff <= -hg.minDiff ? hg.down : 0;
      for (const sid of skill.sp || []) {
        const sp = M?.specs?.[sid];
        if (sp?.t === 'HEIGHT_ATTACK' && diff > 0) b += sp.p[0] + sp.p[1] * diff;
      }
      for (const inst of unitSpecs(a)) {
        if (inst.spec.t === 'HEIGHT_ATTACK' && diff > 0 && cond(inst, ctx)) b += inst.spec.p[0] + inst.spec.p[1] * diff;
      }
      return b;
    }
    // Round 34: `skillPlans` is compiled from skill.desc + the decrypted
    // speciality.dynamic_param. It describes how many separate hits a skill
    // settles and at what factor, plus consumption / bonus-damage segments.
    const skillPlan = s => M?.skillPlans?.[s?.id] || null;
    // ONE cast may settle several damage SEGMENTS. The client either declares
    // them in skillPlans (from skill.desc + dynamic_param) or chains a pure
    // damage skill through ADDITIONAL_ATTACK. 安娜's 警戒 is the latter:
    // ALERT_ATTACK -> 19204 (35%) -> ADDITIONAL_ATTACK -> 19642 (35%). That is
    // 「一段警戒造成 2 段伤害」: one trigger, one charge, one cast, two damage
    // segments — never two separate 警戒 attacks.
    function linkedDamageFactors(s) {
      const out = [];
      for (const sid of s.sp || []) {
        const sp = M?.specs?.[sid];
        if (sp?.t !== 'ADDITIONAL_ATTACK' || !sp.p?.[0]) continue;
        const linked = skillRec(sp.p[0]);
        if (!linked || !(linked.df > 0) || (linked.sp || []).length) continue;
        out.push(Number(linked.df) || 0);
      }
      return out;
    }
    // ---- client composite skill chain (skill.idskill_follow) --------------
    // A single cast resolves as several ORDERED sub-skills. Each segment has
    // its own damage_factor, its own speciality list, its own conditional
    // damage modifiers (speciality.active_param Lua) and its own side effects
    // (buffs / debuffs / knockback / sub-casts / energy recovery ...).
    // `skillPlans[id].chain` is compiled offline from the decoded tables by
    // scripts/skill_mechanics.py; this runtime compiler is the fallback for
    // skills without a prebuilt plan, so EVERY skill is treated as composite.
    const CHAIN_SKIP = new Set(['SKILL_RANGE', 'MULTI_ATTACK', 'SUB_ATTACK', 'AOE',
      'GET_EXTRA_SKILL', 'IMMUNE']);
    // attribute_type.json `type` values that change a damage FACTOR. Base
    // stats (PHYSIC_ATTACK etc.) are already applied by attr() and must not be
    // double-counted as a segment factor. Mirrors scripts/skill_mechanics.py.
    const DAMAGE_FACTOR_TYPES = new Set(['DAMAGE_FACTOR', 'DAMAGE', 'DAMAGE_MODIFY',
      'FINAL_DAMAGE', 'FINAL_DAMAGE_MULTIPLY', 'PHYSIC_DAMAGE', 'SPELL_DAMAGE',
      'FIX_DAMAGE', 'CRIT_DAMAGE']);
    const chainCache = new Map();          // static data only → safe for the whole battle
    function compileChain(s) {
      const sid0 = Number(s?.id) || 0;
      if (chainCache.has(sid0)) return chainCache.get(sid0);
      const out = [];
      let cur = sid0;
      const seen = new Set();
      for (let guard = 0; cur && !seen.has(cur) && guard < 10; guard++) {
        seen.add(cur);
        const sk = skillRec(cur);
        if (!sk) break;
        const seg = {id: cur, n: sk.n, df: Number(sk.df) || 0, dt: Number(sk.dt) || 0,
                     sp: (sk.sp || []).slice(), boost: [], effects: []};
        for (const sid of seg.sp) {
          const sp = M?.specs?.[sid];
          if (!sp) continue;
          const at = AT_ALIAS[sp.at] || sp.at;
          const p = sp.p || [];
          const pct = Number(p[2] || 0) || Number(p[1] || 0);
          const when = sp.c || sp.dp || '';
          const atype = M?.enums?.attributes?.[p[0]] || '';
          if (sp.t === 'MODIFY_ATTRIBUTE' && [1, 2, 4].includes(at) && pct &&
              DAMAGE_FACTOR_TYPES.has(atype))
            seg.boost.push({spec: sid, attr: Number(p[0]) || 0, pct,
                            when, name: sp.n || '', attrName: atype});
          else if (sp.t && !CHAIN_SKIP.has(sp.t))
            seg.effects.push({spec: sid, t: sp.t, at, n: sp.n || '',
                              p: p.slice(0, 4), when});
        }
        out.push(seg);
        cur = Number(sk.fl) || 0;
      }
      chainCache.set(sid0, out);
      return out;
    }
    const chainOf = s => skillPlan(s)?.chain || compileChain(s);
    // The head deals no damage itself but an idskill_follow segment does:
    // 陷阵·锐意承锋 (dt 5, df 0) →「灭魂一击后续」#15657 (dt 1, 100%). 51
    // client skills described 「（物理伤害）」 have this shape. Such a skill
    // IS a damage skill aimed at enemies; its segments carry their own type.
    const followDamage = s => !!s && s.dt !== 3 && !(Number(s.df) > 0) &&
      chainOf(s).slice(1).some(seg => seg.df > 0 && [1, 2, 4].includes(seg.dt));
    const segSkillOf = (s, seg) => (seg?.chainSkill && skillRec(seg.chainSkill)) || s;
    // `skill_cast_id` follow-ups (15934 → 15968; 13324 → 13329 → 13331 →
    // 13333 → 13334). castSkill() casts each one for real; this list lets the
    // AI value a df-0 command skill by the damage its follow-ups deal.
    function castChainOf(s) {
      const out = [];
      const seen = new Set([Number(s?.id) || 0]);
      let cur = Number(s?.scid) || 0;
      for (let guard = 0; cur && !seen.has(cur) && guard < 8; guard++) {
        seen.add(cur);
        const rec = skillRec(cur);
        if (!rec) break;
        out.push(rec);
        cur = Number(rec.scid) || 0;
      }
      return out;
    }
    // Inspectable composite view: damage segments AND every non-damage effect,
    // with the client Lua condition that decides each conditional modifier.
    function compositionOf(s) {
      const chain = chainOf(s);
      const segments = chain.map(seg => ({
        id: seg.id, name: seg.n, factor: seg.df, damageType: seg.dt, sp: seg.sp,
        effects: [
          ...seg.boost.map(b => ({kind: '条件倍率', spec: b.spec, name: b.name,
            value: `+${b.pct}%`, attr: attrName(b.attr) || `#${b.attr}`, when: b.when})),
          ...seg.effects.map(e => ({kind: e.t, spec: e.spec, name: e.n,
            value: (e.p || []).filter(x => x).join('/') || '',
            when: e.when, at: e.at})),
        ],
      }));
      return {source: 'skill.idskill_follow + speciality.active_param / dynamic_param',
              chainLength: chain.length,
              damageSegments: chain.filter(x => x.df > 0).length,
              effectTotal: segments.reduce((n, x) => n + x.effects.length, 0),
              segments};
    }
    // skill_cast_id links. The client implements 「进行N次攻击」 as a head cast
    // plus a skill_cast_id chain (爆裂箭 19449 → 18975 → 18976, 千刃 4764 →
    // 4765 → 4766, 将杀 13324 → 13329 … 13334). For 20 of the 22 skills that
    // carry both a scid and a description-derived multi-hit plan, the
    // description count equals head + chain casts exactly. castSkill() casts
    // the chain for real, so a linked skill resolves ONLY its own single hit.
    const SCID_MEMBERS = new Set(Object.values(M?.skills || {})
      .map(x => Number(x.scid) || 0).filter(Boolean));
    const scidLinked = s => !!s && (Number(s.scid) > 0 || SCID_MEMBERS.has(Number(s.id)));
    // `forValue` is used ONLY by the AI's expected-damage estimate. A scid
    // chain casts its remaining segments as separate casts, so the SETTLEMENT
    // path must resolve just the head hit; but the AI must still value the
    // skill's TOTAL client damage (爆裂箭 3×50%), otherwise every linked
    // skill is scored at one third of its worth and the whole turn order drifts.
    function damageSegmentsOf(s, forValue = false) {
      const plan = skillPlan(s);
      const chainDmg = chainOf(s).filter(x => x.df > 0);
      // Several damaging segments, OR the only damaging segment is a
      // follow-up (head df 0): resolve the damage on the chain segments.
      if (chainDmg.length > 1 || (chainDmg.length === 1 && Number(chainDmg[0].id) !== Number(s.id)))
        return chainDmg.map((seg, i) => ({
          factor: seg.df, boost: 0, chainSkill: seg.id,
          boostRows: seg.boost, chainName: seg.n,
          label: chainDmg.length > 1 ? `第 ${i + 1}/${chainDmg.length} 段 · ${seg.df}%`
            : `${seg.df}% 伤害（后续「${seg.n}」）`}));
      // Every segment — even on a single-stage skill — carries the client's
      // conditional damage modifiers. A composite skill is not necessarily
      // multi-stage: it may be one hit plus buffs/debuffs/conditional factors.
      const headBoost = chainOf(s)[0]?.boost || [];
      if (plan?.g?.length && (forValue || !scidLinked(s))) return plan.g.flatMap(([count, factor]) => {
        const n = Math.min(20, Math.max(1, Number(count) || 1));
        return Array.from({length: n}, (_, i) => ({factor: Number(factor) || 0, boost: 0,
          boostRows: headBoost,
          label: (plan.g.length > 1 || n > 1) ? `第 ${i + 1}/${n} 段 · ${factor}%` : `${factor}% 伤害`}));
      });
      const linked = linkedDamageFactors(s);
      if (!linked.length) {
        if (!headBoost.length) return null;
        return [{factor: Number(s.df) || 100, boost: 0, boostRows: headBoost,
                 label: null, chainSkill: chainOf(s)[0]?.id || s.id,
                 hitsOverride: hitsOf(s)}];
      }
      const all = [Number(s.df) || 0, ...linked];
      return all.map((f, i) => ({factor: f, boost: 0, boostRows: i === 0 ? headBoost : [],
        label: `第 ${i + 1}/${all.length} 段 · ${f}%`}));
    }
    function hitsOf(skill) {
      // A scid-linked skill's other hits are separate client casts.
      let hits = (scidLinked(skill) ? 0 : skillPlan(skill)?.h) || skill.hits || 1;
      for (const sid of skill.sp || []) {
        const sp = M?.specs?.[sid];
        if (sp && (sp.t === 'MULTI_ATTACK' || sp.t === 'SUB_ATTACK')) hits = Math.max(hits, sp.p[0] || 1);
      }
      return hits;
    }
    // Returns {amount, crit, kind, restraint, height, parts}.
    function computeDamage(a, d, skill, ctx, opts = {}) {
      // Client FORCE_DAMAGE_TYPE p = [new type, from type (0 = any)]:
      // 落灵神枪 #6110「造成的[物理伤害]视为[魔法伤害]」(1 → 2), 冠军甲壳 /
      // SP科尔 突袭形态 (→ 4 穿透). The attack keeps its own scaling (pf/sf
      // from the skill's real type); only the damage TYPE — defence used,
      // type bonuses, pierce rules — changes. The row used to set an unread
      // flag only when "fired", which an always-on row never is.
      let dt = skill.dt;
      if ([1, 2, 4].includes(dt) && a?.base) {
        for (const inst of unitSpecs(a)) {
          const sp = inst.spec;
          if (sp.t !== 'FORCE_DAMAGE_TYPE') continue;
          const to = Number(sp.p?.[0]) || 0, from = Number(sp.p?.[1]) || 0;
          if (!to || to === dt || (from && from !== dt)) continue;
          if (sp.c && !cond(inst, Object.assign({}, ctx, {attacker: a, defender: d, skill}), !!opts.expected)) continue;
          dt = to;
          break;
        }
      }
      const parts = opts.explain ? [] : null;
      const fx = opts.explain ? [] : null;
      // `expr` is the client formula with the ACTUAL numbers substituted, so
      // a reviewer can recompute every step by hand. `formula` chains them.
      const add = (label, value, note, expr) => {
        if (!parts) return;
        // Every row carries a substituted expression, so nothing in the
        // detail table is a bare label. Only explicit `expr` steps are chained
        // into `formula` (the compact arithmetic summary).
        parts.push({label, value, note: note || '', expr: expr || `${label} = ${value}`});
        if (expr) fx.push(expr);
      };
      const formula = () => fx ? fx.join(' → ') : null;
      const c = Object.assign({}, ctx, {attacker: a, defender: d, skill, restrain: restrainSpecs(a, d)});
      const P = attr(a, 'PHYSIC_ATTACK', c), Sp = attr(a, 'SPELL_ATTACK', c);
      let pf = skill.pf, sf = skill.sf;
      if (!pf && !sf) { if (skill.dt === 2 || skill.dt === 3) sf = 100; else pf = 100; }
      if (dt !== skill.dt) add('伤害类型转换', dt === 2 ? '魔法' : dt === 4 ? '穿透' : '物理',
        `FORCE_DAMAGE_TYPE：原${skill.dt === 1 ? '物理' : skill.dt === 2 ? '魔法' : '穿透'}伤害按此类型结算`);
      let raw = P * pf / 100 + Sp * sf / 100;
      add('基础攻击力', Math.round(raw), `物攻 × ${pf}% + 魔攻 × ${sf}%`,
          `(${Math.round(P)} × ${pf}% + ${Math.round(Sp)} × ${sf}%) = ${Math.round(raw)}`);
      for (const sid of skill.sp || []) {
        const sp = M?.specs?.[sid];
        if (sp?.t === 'ATTRIBUTE_ATTACK') {
          let v = attrById(a, sp.p[0]) * sp.p[1] / 100;
          if (sp.p[2]) v = Math.min(v, attrById(a, sp.p[2]) * (sp.p[3] || 100) / 100);
          raw += v;
          add('属性追加', Math.round(v), `${attrName(sp.p[0])} × ${sp.p[1]}%`,
              `${Math.round(raw - v)} + (${attrName(sp.p[0])} ${Math.round(attrById(a, sp.p[0]))} × ${sp.p[1]}%) = ${Math.round(raw)}`);
        }
      }
      const df = opts.factorOverride !== undefined ? opts.factorOverride : (skill.df || 100);
      add('技能倍率', `${df}%`,
          `${opts.segLabel ? opts.segLabel + ' · ' : ''}damage_factor · 技能「${skill.n}」`,
          `技能倍率 = ${df}%`);
      const restraint = c.restrain.length ? (M.restrain.find(r => r.from === a.prof && r.to === d.prof)?.evaluate || 100) / 100 : 1;
      if (dt === 3) {
        let amount = raw * df / 100;
        // PERCENT_HEAL: 血量类型 (1 = 已损失生命, 2 = 最大生命) × 技能倍率，上限 = 上限属性 × 上限百分比
        const ph = (skill.sp || []).map(sid => M?.specs?.[sid]).find(sp => sp?.t === 'PERCENT_HEAL');
        if (ph) {
          const pool = ph.p[0] === 1 ? maxHpOf(d) - d.hp : maxHpOf(d);
          amount = pool * df / 100;
          if (ph.p[1]) amount = Math.min(amount, attrById(a, ph.p[1]) * (ph.p[2] || 100) / 100);
          bump(cov.executed, 'PERCENT_HEAL');
        }
        const hf = attr(a, 'HEAL_FACTOR', c) + attr(a, 'HEAL_FACTOR_ADD', c);
        const bhf = attr(d, 'BE_HEAL_FACTOR', c);
        const heal = amount * (1 + hf / 100) * Math.max(0, 1 + bhf / 100);
        add('治疗修正', `+${Math.round(hf)}%`, '治疗加成 + 额外治疗加成',
            `基础 ${Math.round(amount)} × (1 + ${Math.round(hf)}%) = ${Math.round(amount * (1 + hf / 100))}`);
        add('受治疗修正', `${Math.round(bhf)}%`, '目标受到治疗修正',
            `${Math.round(amount * (1 + hf / 100))} × (1 + ${Math.round(bhf)}%) = ${Math.round(heal)}`);
        add('最终治疗', Math.max(0, Math.round(heal)), '不超过目标最大生命',
            `最终治疗 = ${Math.max(0, Math.round(heal))}`);
        return {amount: Math.max(0, Math.round(heal)), kind: 'heal', parts, formula: formula()};
      }
      if (dt === 5 || df <= 0 && !skill.dmg && !skill.dp) return {amount: 0, kind: 'status', parts, formula: formula()};
      const hits = opts.hitsOverride !== undefined ? opts.hitsOverride : hitsOf(skill);
      if (dt === 4) {
        let v = raw * df / 100 + (skill.dmg || 0) + maxHpOf(d) * (skill.dp || 0) / 100;
        add('穿透基础', Math.round(v), '攻击力 × 倍率 + 固定值 + 目标最大生命百分比',
            `(${Math.round(raw)} × ${df}% + ${skill.dmg || 0} + ${Math.round(maxHpOf(d))} × ${skill.dp || 0}%) = ${Math.round(v)}`);
        v *= 1 + attr(a, 'FIX_DAMAGE', c) / 100;
        add('穿透增伤', `${Math.round(attr(a, 'FIX_DAMAGE', c))}%`, '穿透伤害提高',
            `× (1 + ${Math.round(attr(a, 'FIX_DAMAGE', c))}%) = ${Math.round(v)}`);
        const fixTaken = clamp((1 + attr(d, 'FIX_BEDAMAGE', c) / 100) * (1 + attr(d, 'FIX_BEDAMAGE_NODURATION', c) / 100), 0, 2.3);
        v *= fixTaken;
        add('穿透易伤', `×${fixTaken.toFixed(2)}`, '穿透受伤修正（上限 230%）',
            `× ${fixTaken.toFixed(2)} = ${Math.round(v)}`);
        const flatAdd = attr(a, 'FIX_DAMAGE_NONPERCENT', c) + attr(d, 'FIX_BEDAMAGE_NONPERCENT', c);
        v += flatAdd;
        if (parts && flatAdd) add('固定伤害加成', Math.round(flatAdd), '攻击方固定增伤 + 受击方固定增伤',
          `+ ${Math.round(flatAdd)} = ${Math.round(v)}`);
        if (opts.extraBoost) { v *= 1 + opts.extraBoost / 100; add('追加伤害增伤', `+${opts.extraBoost}%`, '通过此效果造成的伤害提高', `× (1 + ${opts.extraBoost}%) = ${Math.round(v)}`); }
        add('攻击段数', hits, '多段伤害合计', `× ${hits} 段`);
        add('最终伤害', Math.max(1, Math.round(v * hits)), '穿透伤害无视防御，至少 1 点',
            `最终伤害 = ${Math.max(1, Math.round(v * hits))}`);
        return {amount: Math.max(1, Math.round(v * hits)), kind: 'pierce', crit: false, restraint: 1, height: 0, parts, formula: formula()};
      }
      const magic = dt === 2;
      // A7: 最终防御 = 面板防御 ×(1+防御加成) × ∏(1 − 无视防御系数ᵢ).
      // Multiple 无视防御 sources multiply; they do NOT sum into one percentage.
      const diRows = [];
      if (skill.di) diRows.push({pct: skill.di, name: `技能「${skill.n}」`, src: 'skill'});
      for (const r of zoneFactors(a, ['DEFENCE_IGNORE'], c)) diRows.push(r);
      let diMul = 1;
      for (const r of diRows) diMul *= Math.max(0, 1 - r.pct / 100);
      const defBase = attr(d, magic ? 'SPELL_DEFENCE' : 'PHYSIC_DEFENCE', c);
      const def = defBase * diMul;
      if (parts) {
        for (const r of diRows) add('无视防御·' + r.name, `${r.pct}%`, r.attr || '技能',
          `(1 − ${r.pct}%) = ${Math.max(0, 1 - r.pct / 100).toFixed(3)}`);
      }
      add('目标防御', Math.round(def), `${magic ? '魔防' : '物防'}，${diRows.length} 个无视防御来源连乘`,
          `目标防御 = ${Math.round(defBase)} × ${diRows.length ? diRows.map(r => `(1 − ${r.pct}%)`).join(' × ') : '1'} = ${Math.round(def)}`);
      // AB12: (attack − defence) is floored at 5% of the final attack, not 0.
      const floor = raw * 0.05;
      const baseDiff = Math.max(floor, raw - def);
      let v = baseDiff * df / 100 + (skill.dmg || 0) + maxHpOf(d) * (skill.dp || 0) / 100;
      add('基础伤害', Math.round(v), 'max(攻击力×5%, 攻击力 − 防御) × 倍率 + 固定伤害（下限 5% 攻击）',
          `max(${Math.round(floor)}, ${Math.round(raw)} − ${Math.round(def)}) × ${df}% + ${skill.dmg || 0} + ${Math.round(maxHpOf(d))} × ${skill.dp || 0}% = ${Math.round(v)}`);
      const height = heightBonus(a, d, skill, c);
      v *= 1 + height / 100;
      add('高低差', `${height}%`, `高 2 层以上 +${hg.up}%，低 2 层以上 ${hg.down}%`,
          `${height}% → ${Math.round(v)}`);
      const bonus = attr(a, 'DAMAGE', c) + attr(a, magic ? 'SPELL_DAMAGE' : 'PHYSIC_DAMAGE', c)
        + attr(a, 'DAMAGE_MODIFY', c) + attr(a, 'FINAL_DAMAGE', c);
      v *= 1 + Math.max(-50, bonus) / 100;
      add('攻击方增伤', `${Math.round(Math.max(-50, bonus))}%`, '造成伤害 / 物理·魔法伤害 / 最终伤害（下限 −50%）',
          `× (1 + ${Math.round(Math.max(-50, bonus))}%) = ${Math.round(v)}`);
      // A10/A11/F23: 受到伤害区 is a PRODUCT of one (1+x) factor PER SOURCE —
      // 易伤3 / 免伤2 / 受击者受伤增加 / 最终受到伤害修正(加) all belong here.
      // Summing them into `attr(BEDAMAGE)` first (the old behaviour) gives a
      // different result as soon as two sources are active at once.
      const beRows = zoneFactors(d, ['BEDAMAGE', magic ? 'SPELL_BEDAMAGE' : 'PHYSIC_BEDAMAGE',
        'FINAL_BEDAMAGE'], c);
      let taken = 1;
      for (const r of beRows) taken *= Math.max(0, 1 + r.pct / 100);
      const takenClamped = clamp(taken, 0, 3);
      v *= takenClamped;
      if (parts) {
        for (const r of beRows)
          add('易伤·' + r.name, `${r.pct > 0 ? '+' : ''}${r.pct}%`, `${r.attr}${r.sid ? ' #' + r.sid : ''}`,
              `(1 + ${r.pct}%) = ${Math.max(0, 1 + r.pct / 100).toFixed(3)}`);
      }
      add('受击方易伤', `×${takenClamped.toFixed(2)}`,
          `${beRows.length} 个来源全乘算（上限 300%）`,
          `${beRows.length ? beRows.map(r => `(1 + ${r.pct}%)`).join(' × ') : '1'} = ${taken.toFixed(3)}${takenClamped !== taken ? ` → 上限截断 ${takenClamped.toFixed(2)}` : ''} → × ${takenClamped.toFixed(2)} = ${Math.round(v)}`);
      const finMul = Math.max(0, 1 + attr(a, 'FINAL_DAMAGE_MULTIPLY', c) / 100) * Math.max(0, 1 + attr(d, 'FINAL_BEDAMAGE_MULTIPLY', c) / 100);
      v *= finMul;
      if (parts && Math.abs(finMul - 1) > 0.001) add('最终伤害倍率', `×${finMul.toFixed(2)}`, '最终伤害 / 最终承伤乘算',
          `× ${finMul.toFixed(2)} = ${Math.round(v)}`);
      const critChance = K.CritBaseChance + attr(a, 'CRIT_RATIO', c) + (skill.cc || 0) - attr(d, 'CRIT_RESIST', c);
      const critDmg = Math.max(0, K.CritBaseDamage + attr(a, 'CRIT_DAMAGE', c) - attr(d, 'CRIT_REDUCE', c));
      add('暴击率', `${clamp(critChance, 0, 100).toFixed(1)}%`, `客户端常量 CritBaseChance ${K.CritBaseChance}% + 暴击属性 + 技能 − 目标抗暴`,
          `暴击率 = ${clamp(critChance, 0, 100).toFixed(1)}%`);
      add('暴击伤害', `${Math.round(critDmg)}%`, `客户端常量 CritBaseDamage ${K.CritBaseDamage}% + 暴伤属性 − 目标暴伤减免`,
          `暴击倍率 = ×(1 + ${Math.round(critDmg)}%)`);
      let crit = false;
      if (opts.expected) v *= 1 + clamp(critChance, 0, 100) / 100 * critDmg / 100;
      else if (roll() * 100 < critChance) { crit = true; v *= 1 + critDmg / 100; add('暴击', `+${Math.round(critDmg)}%`, '本次判定为暴击', `× (1 + ${Math.round(critDmg)}%) = ${Math.round(v)}`); }
      if (opts.parry && !magic) { v *= 0.5; add('格挡', '×0.5', '物理伤害被格挡', `× 0.5 = ${Math.round(v)}`); }
      if (opts.extraBoost) { v *= 1 + opts.extraBoost / 100; add('追加伤害增伤', `+${opts.extraBoost}%`, '通过此效果造成的伤害提高', `× (1 + ${opts.extraBoost}%) = ${Math.round(v)}`); }
      v *= hits;
      if (parts && hits > 1) add('攻击段数', `×${hits}`, '多段伤害合计', `× ${hits} = ${Math.round(v)}`);
      add('最终伤害', Math.round(v), '向下取整后由护盾先承伤', `最终伤害 = ${Math.round(v)}`);
      return {amount: Math.max(raw > 0 || skill.dmg ? 1 : 0, Math.round(v)), kind: magic ? 'spell' : 'physic', crit,
              restraint, height, critChance, parts, formula: formula()};
    }

    // Official damage formula (「SoC伤害计算器v1.5 by海森」/「伤害计算公式」表,
    // corroborated by the client's attribute_type + speciality data; the
    // client ships only compiled .luac, no readable formula):
    //   最终攻击 = (面板攻击 ×(1+攻击增益%) + 攻击转换) × 克制系数
    //   最终防御 = 面板防御 ×(1+防御加成%) × ∏(1 − 无视防御系数ᵢ)
    //   造成伤害区 = 1 + Σ(增伤来源)            区内加算，下限 50%
    //   受到伤害区 = ∏(1 + 每个易伤来源ᵢ)        全乘算，上限 300%
    //   暴伤区   = 1.3 + Σ(暴伤来源)            区内加算
    //   最终伤害 = max(最终攻击×5%, 最终攻击−最终防御) × 技能倍率
    //              × 造成伤害区 × 受到伤害区 × (暴击时 暴伤区)
    // The engine used to SUM all BEDAMAGE sources into three attribute buckets
    // and multiply the three buckets — A11/F23 explicitly require each source
    // to be its OWN (1+x) factor. The same 「∏(1−iᵢ)」 rule applies to
    // defence-ignore (A7), and AB12 floors (attack−defence) at 5% of attack.
    // `collect` reuses attrCompute()'s exact timing/condition filter, so every
    // factor here is one the client would really apply to this hit.
    function zoneFactors(u, attrs, ctx) {
      const rows = [];
      const was = sim.probe;
      sim.probe = true;              // read-only: no RNG, no coverage double-count
      try {
        for (const A of attrs) attrCompute(u, A, ctx, baseOf(u, A), rows);
      } finally { sim.probe = was; }
      return rows.filter(r => r.pct);
    }

    // Deal damage after shields; handles 不屈, death and kill triggers.
    function dealDamage(src, victim, amount, info = {}) {
      if (!victim.alive) return {dealt: 0, absorbed: 0, zeroReason: '目标已被击败'};
      if (amount <= 0) return {dealt: 0, absorbed: 0, zeroReason: '计算结果为 0'};
      // PER_DAMAGED_LIMIT (client 「每回合最多受击 N 次」) — extra hits are void.
      if (victim.damagedCap && (victim.damagedHits || 0) >= victim.damagedCap)
        return {dealt: 0, absorbed: 0, zeroReason: `每回合最多受击 ${victim.damagedCap} 次（PER_DAMAGED_LIMIT）`};
      victim.damagedHits = (victim.damagedHits || 0) + 1;
      // Client 睡眠/昏睡 descriptions: 「无法做出任何行动，受到任何攻击伤害
      // 解除」. The control buffs are removed as soon as real damage lands,
      // so a sleeping 伊凡 wakes on the first hit instead of losing the whole
      // battle. 失眠类 (et=Dizzy etc.) are NOT cleared — only the ones whose
      // client description declares damage-based removal.
      for (const b of victim.buffs.slice()) {
        if (isControlBuff(b) && /受到任何攻击伤害解除|受击解除|受到伤害解除/.test(b.def.d || ''))
          removeBuff(victim, b, '受到攻击伤害解除');
      }
      // Client DAMAGE_BUFFER_DYNAMIC (灵感星核 #28858「受击积累能量」):
      // p = [attribute, convert%, blocked%, cap] after its dynamic_param
      // (convert 15 / 30 for 〈铃兰之剑〉 / 60 for TarotBeiLa_allin skills,
      // cap = summoner level × 2000). While its condition holds (owner:
      // isFriend(target): the HOLDER is hit by a friend) `blocked%` of the
      // damage never reaches HP and `convert%` of it is stored in that
      // attribute — 「受到的伤害值30%转移为[灵感指数]（不会造成实际伤害）」.
      // The engine used to only set an unread flag, so 贝拉's own 造物赋能
      // killed her 灵感星核 and the core's 灵感迸发 never charged.
      if (src && src.base && src !== victim) {
        for (const raw of unitSpecs(victim)) {
          if (raw.spec.t !== 'DAMAGE_BUFFER_DYNAMIC') continue;
          const c0 = {attacker: src, defender: victim, target: src, skill: info.skill || null};
          if (!cond(raw, c0)) continue;
          const spec = raw.spec.dp ? resolvedSpec(raw, c0) : raw.spec;
          const [aid, convert, blocked, cap] = spec.p || [];
          const A = attrName(aid);
          const gain = Math.floor(amount * (Number(convert) || 0) / 100);
          if (A && gain > 0) {
            const before = Number(victim.base[A]) || 0;
            const lim = Number(cap) > 0 ? Number(cap) : Infinity;
            victim.base[A] = Math.min(lim, before + gain);
            touch(victim);
            log(`${victim.name} 的「${raw.name}」：受到友军 ${src.name} 的 ${amount} 伤害，${convert}% 转为 ${A} ` +
                `${before} → ${victim.base[A]}${lim < Infinity ? `（上限 ${lim}）` : ''}`);
          }
          const cut = Math.round(amount * (Number(blocked) || 0) / 100);
          if (cut > 0) {
            amount = Math.max(0, amount - cut);
            bump(cov.executed, 'DAMAGE_BUFFER_DYNAMIC');
            if (amount <= 0) return {dealt: 0, absorbed: 0,
              zeroReason: `「${raw.name}」：友军伤害不造成实际伤害${A ? `（转为 ${A}）` : ''}`};
          }
        }
      }
      // Damage sharing: divert a configured fraction to all marked partners.
      const rule = shareRuleOf(victim);
      if (rule && !info.noShare && rule.pct > 0) {
        const mates = units.filter(u => u.alive && u !== victim && u.buffs.some(b => b.id === rule.bid));
        if (mates.length) {
          const cut = Math.round(amount * rule.pct / 100);
          const each = Math.max(1, Math.floor(cut / mates.length));
          let diverted = 0;
          log(`分摊伤害机制 SHARE_DAMAGE 触发：${victim.name} 原始伤害 ${amount} × ${rule.pct}%（客户端 p[1] 为自身保留比例，分摊 = 100 − p[1]）= 应分摊 ${cut}；` +
              `拥有[${rule.name}]的同伴 ${mates.length} 名 → 每人 ⌊${cut} ÷ ${mates.length}⌋ = ${each}${rule.capAttr ? `，上限由 ${rule.capAttr} × ${rule.capPct}% 决定` : ''}`);
          for (const mate of mates) {
            const cap = rule.capAttr && rule.capPct
              ? Math.round(attr(mate, rule.capAttr) * rule.capPct / 100) : Infinity;
            const share = Math.min(each, cap);
            if (share <= 0) continue;
            diverted += share;
            const before = mate.hp;
            dealDamage(src, mate, share, Object.assign({}, info, {noShare: true, pierce: true}));
            log(`  → ${victim.name} 将 ${share} 伤害分摊给 ${mate.name}：min(每人 ${each}, 上限 ${cap < Infinity ? `${cap}（${rule.capAttr} ${Math.round(attr(mate, rule.capAttr))} × ${rule.capPct}%）` : '无上限'}) = ${share}；` +
                `生命 ${before} → ${mate.hp}（穿透分摊部分，不再二次分摊）`);
          }
          const before = amount;
          amount = Math.max(0, amount - diverted);
          log(`分摊结算：${victim.name} ${before} − 转移 ${diverted} = 自身承受 ${amount}（随后判定护盾与生命扣减）`);
        }
      }
      const link = victim.shareLink;
      if (link && !info.noShare && link.pct > 0) {
        const mate = units.find(u => u.alive && u.uid === link.uid);
        if (mate && (!link.gate || victim.hp / Math.max(1, maxHpOf(victim)) * 100 < link.gate)) {
          const cut = Math.round(amount * link.pct / 100);
          const before = amount;
          amount -= cut;
          dealDamage(src, mate, cut, Object.assign({}, info, {noShare: true, pierce: true}));
          log(`分摊伤害机制（定向链接）触发：${victim.name} 原始 ${before} × ${link.pct}% = ${cut} 转移给 ${mate.name}，自身剩余 ${amount}${link.gate ? `（生命低于 ${link.gate}% 才生效）` : ''}`);
        }
      }
      let left = amount, absorbed = 0;
      const kind = info.kind === 'spell' ? 'spell' : info.kind === 'physic' ? 'phys' : null;
      // IGNORE_ARMOR: attacker-side speciality bypasses physical / magic
      // shields entirely (client 「无视护盾」).
      const bypassArmor = !!info.ignoreArmor || !!(src && activeSpec(src, info.skill, 'IGNORE_ARMOR',
        {attacker: src, defender: victim, skill: info.skill}));
      if (kind && !info.pierce && !bypassArmor) {
        for (const b of victim.buffs.slice()) {
          if (!b.armor || !(b.armor[kind] > 0)) continue;
          const take = Math.max(0, Math.min(left, b.armor[kind]));
          if (take <= 0) continue;
          b.armor[kind] -= take; left -= take; absorbed += take;
          if (b.armor.phys <= 0 && b.armor.spell <= 0) removeBuff(victim, b, '护盾被击破');
          if (left <= 0) break;
        }
      }
      const before = victim.hp;
      victim.hp = Math.max(0, victim.hp - Math.max(0, left));
      // Snapshot HP *before* 不屈 (REBORN) rewrites it. `dealt` used to be
      // `before - victim.hp` computed AFTER the revive, so a target that
      // survived at higher HP than it started reported NEGATIVE damage
      // (-11589) or a bare 「0 伤害」. Both are the same bug.
      const afterDamageHp = victim.hp;
      if (left > 0) victim.flags.damagedTurn = true;
      touch(victim);
      let rebornName = null, rebornHp = 0;
      if (afterDamageHp <= 0) {
        const reborn = unitSpecs(victim).find(i => i.spec.t === 'REBORN' && limitOk(i) && cond(i, {attacker: src, defender: victim, skill: info.skill}));
        if (reborn) {
          spend(reborn);
          bump(cov.executed, 'REBORN');
          const s = reborn.spec;
          victim.hp = Math.max(1, Math.round(Math.max(s.p[0] > 1 ? s.p[0] : 1, maxHpOf(victim) * (s.p[1] || 0) / 100)));
          rebornName = reborn.name;
          rebornHp = victim.hp;
          log(`${victim.name} 触发「${reborn.name}」不屈，以 ${victim.hp} 生命存活（本次伤害 ${Math.max(0, before - afterDamageHp)}，生命由 ${afterDamageHp} 恢复至 ${victim.hp}）`);
          if (s.p[2]) addBuff(victim, s.p[2], s.p[3] || 1, 1, victim);
          fire(44, victim, {target: victim});
        }
      }
      const dealt = Math.max(0, before - afterDamageHp);
      if (src) { src.tally.dealt += dealt; }
      victim.tally.taken += dealt;
      if (victim.hp <= 0 && victim.alive) kill(src, victim, info);
      return {dealt, absorbed, reborn: rebornName, rebornHp,
              zeroReason: dealt === 0 && !absorbed && amount <= 0 ? '伤害已全部分摊给同伴' : ''};
    }
    function kill(src, victim, info) {
      victim.alive = false;
      touch(victim);
      if (src && src !== victim) src.tally.kills++;
      log(`${victim.name} 被击败`);
      fire(12, victim, {attacker: src, defender: victim, skill: info.skill, target: src});
      if (src && src.alive && info.skill) {
        runSkillSpecs(info.skill, src, 11, {attacker: src, defender: victim, skill: info.skill, target: victim});
        fire(11, src, {attacker: src, defender: victim, skill: info.skill, target: victim});
        fire(21, src, {attacker: src, defender: victim, skill: info.skill, target: victim});
      }
      fireAbsorb(victim, src, info);
      refreshAuras();
    }
    // Client speciality_type 134「吸收」is a DEATH LISTENER, not a shield.
    // Its active_time is 1 (ANY) so fire() never raises it; instead the client
    // scans every listener whenever a unit is defeated and casts `p[0]`:
    //   沙姆斯 #21869「仇敌死亡时-触发吸收」→ 17174 加标记 BUFF
    //   基安希尔 #24534「死士死亡获得1层标记」→ 18862 死亡计数器
    //   暴徒火术士 #10116 → 9792「每当任意一个非召唤物的单位被击败时，
    //                             自身所有技能冷却1回合」
    // p[1] = 是否限制在监听范围内, p[2] = 死亡单位阵营 unit_tag (0 = 任意),
    // p[3] = range_and_height packed: low 16 = range, bits 16-23 = height
    // difference (99 = 全场 / 不限高度). The Lua condition sees `target` as
    // the DEFEATED unit and `owner` as the listener, e.g.
    // 「return target:getBuffCount(6183,1) and owner:isEnemy(target)」.
    function fireAbsorb(victim, src, info) {
      if (!M || sim.absorbBusy) return;
      sim.absorbBusy = true;
      try {
        for (const listener of units.slice()) {
          if (!listener.alive) continue;
          for (const inst of unitSpecs(listener)) {
            if (inst.spec.t !== 'ABSORB' || !Number(inst.spec.p?.[0])) continue;
            const p = inst.spec.p;
            const tag = Number(p[2]) || 0;
            if (tag && !(victim.tags || []).some(t => Number(t) === tag)) continue;
            if (Number(p[1])) {
              const packed = Number(p[3]) || 0;
              const range = packed & 0xffff;
              const height = (packed >>> 16) & 0xff;
              if (range < 99 && manhattan(listener, victim) > range) continue;
              if (height < 99 && Math.abs(heightOf(listener) - heightOf(victim)) > height) continue;
            }
            if (!limitOk(inst)) continue;
            const ctx = {attacker: src, defender: victim, target: victim,
                         skill: info.skill || null, depth: (info.depth || 0) + 1};
            if (!cond(inst, ctx)) continue;
            const linked = skillRec(p[0]);
            if (!linked) { bump(cov.skipped, 'ABSORB(缺技能)'); continue; }
            // ABSORB rows are on passives, so `runSpec` would never see them.
            // Count them explicitly and reuse the client's CAST_SKILL path.
            spend(inst);
            bump(cov.executed, 'ABSORB');
            log(`${listener.name} 的「${inst.name || inst.spec.n}」吸收 ${victim.name} 阵亡 → 施放「${linked.n}」#${linked.id}`);
            subCast({spec: inst.spec, sid: inst.sid, owner: listener,
                     src: inst.src, name: inst.name, skill: inst.skill}, ctx);
          }
        }
      } finally { sim.absorbBusy = false; }
    }
    function heal(src, u, amount, label) {
      if (!u.alive || amount <= 0) return 0;
      const reversed = u.flags.healReverse || u.buffs.some(b => b.def.et === 'TreatReversal') ||
        specActive(u, 'HEAL_REVERSE') || specActive(u, 'HEALED_REVERSE');
      if (reversed) {
        // Client 治疗反转 turns the heal into piercing damage, not a no-op.
        const r = dealDamage(src, u, Math.round(amount), {pierce: true, noShare: true});
        log(`治疗反转：${u.name} 的 ${Math.round(amount)} 点治疗转为 ${r.dealt} 点穿透伤害（HEAL_REVERSE / TreatReversal）`);
        return 0;
      }
      if (u.flags.noRecover || specActive(u, 'FORBIDDEN_RECOVER')) {
        log(`禁止回复：${u.name} 的 ${Math.round(amount)} 点治疗无效（FORBIDDEN_RECOVER）`);
        return 0;
      }
      const before = u.hp;
      const cap = u.flags.healLimit ? Math.round(maxHpOf(u) * 0.3) : maxHpOf(u);
      u.hp = Math.min(Math.max(u.hp, cap), u.hp + Math.round(amount));
      const got = u.hp - before;
      if (got > 0) { if (src) src.tally.healed += got; touch(u); if (label) log(`${u.name} 回复 ${got} 生命（${label}）`); }
      return got;
    }

    /* ---------- effects ---------- */
    const EFFECTS = {
      BUFF(inst, ctx) {
        const s = inst.spec;
        let ids = s.p[0] ? [s.p[0]] : [];
        if (s.s) {
          const list = String(s.s).split(/[|,]/).map(Number).filter(Boolean);
          if (list.length) {
            const n = unpackCount(s.p[3]);
            // p[3] is a packed count. When absent the spec means "all of the
            // listed buffs" (a bundle); when present it means "pick N at
            // random" — e.g. 苔原蜜果 gives exactly ONE random 2级增益.
            ids = n ? pick(list, Math.min(n, list.length)) : (ids.length ? ids : list);
            if (n && n < list.length) log(`从 ${list.length} 个候选状态中随机获得 ${ids.length} 个（${inst.name}）`);
          }
        }
        // Client self-cast correction: some BUFF rows are configured with one
        // turn LESS and annotated 「自施法补正」 in speciality.name (#14673,
        // 流星队 后备隐藏脂肪; skill 11907 says 「持续2回合」 but p[1] = 1).
        const selfBonus = /自施法补正/.test(s.n || '') ? 1 : 0;
        for (const t of targetsOf(inst, ctx)) for (const id of ids) {
          const turns = (s.p[1] || 0) + (t === inst.owner ? selfBonus : 0);
          // p[1] === 0 →「0回合（行动中）」; p[1] < 0 → permanent until removed.
          addBuff(t, id, turns, s.p[2] || 1, inst.owner,
                  Number(turns) === 0 ? {actionScoped: true} : {});
        }
      },
      REMOVE_BUFF(inst, ctx) { dispel(inst, ctx, false); },
      DISPEL(inst, ctx) { dispel(inst, ctx, true); },
      REMOVE(inst) {
        const b = inst.buff;
        if (!b) return;
        const layers = inst.spec.p[0];
        if (layers > 0 && b.stacks > layers) { b.stacks -= layers; touch(inst.owner); }
        else removeBuff(inst.owner, b, '移除');
      },
      RECOVER_ATTRIBUTE(inst, ctx) {
        const [aid, flat, pct, raw] = inst.spec.p;
        const n = attrName(aid);
        for (const t of targetsOf(inst, ctx)) {
          if (n === 'TP') {
            const before = t.tp;
            t.tp = clamp(t.tp + flat + Math.round(attr(t, 'TP_MAX') * pct / 100), 0, attr(t, 'TP_MAX'));
            const d = t.tp - before;
            log(`${t.name} 能量 ${d >= 0 ? '+' : ''}${d}（${inst.name}${flat <= -99 ? ' · 客户端 TP-99 表示清空' : ''}）`);
            continue;
          }
          if (n === 'HP' || n === 'HP_MAX') {
            let v = flat + maxHpOf(t) * pct / 100;
            if (v >= 0) heal(inst.owner, t, raw ? v : v * Math.max(0, 1 + attr(t, 'BE_HEAL_FACTOR') / 100), inst.name);
            else { const r = dealDamage(null, t, Math.round(-v), {pierce: true}); log(`${t.name} 失去 ${r.dealt} 生命（${inst.name}）`); }
          }
        }
      },
      RECOVER_HP_BY_DAMAGE(inst, ctx) {
        if (ctx.damage > 0) heal(inst.owner, inst.owner, ctx.damage * inst.spec.p[0] / 100, inst.name);
      },
      LIFE_LOST(inst, ctx) {
        // A LIFE_LOST speciality with a duration is a damage-over-time buff;
        // without one it settles a single percent-HP loss immediately.
        if (inst.spec.d) { dot(inst); return; }
        for (const t of targetsOf(inst, ctx)) {
          if (!t?.alive) continue;
          const amount = Math.max(1, Math.round(maxHpOf(t) * (inst.spec.p[0] || 0) / 100));
          t.hp = Math.max(0, t.hp - amount);
          touch(t);
          log(`${t.name} 生命流失 ${amount}（${inst.name || '生命流失'}）`);
          if (t.hp <= 0) kill(inst.owner || t, t, {skill: null});
        }
      },
      BURN(inst) { dot(inst); },
      DAMAGE(inst, ctx) {
        const [flat, pct, cur] = inst.spec.p;
        for (const t of targetsOf(inst, ctx)) {
          if (t === inst.owner && inst.spec.tt !== 3) continue;
          const v = flat + (cur ? t.hp : maxHpOf(t)) * pct / 100;
          const r = dealDamage(inst.owner, t, Math.round(v * clamp(1 + attr(t, 'FIX_BEDAMAGE') / 100, 0, 2.3)), {pierce: true});
          log(`${t.name} 受到 ${r.dealt} 穿透伤害（${inst.name}）`);
        }
      },
      ADDITIONAL_ATTRIBUTE_DAMAGE(inst, ctx) {
        const [dtype, aid, pct] = inst.spec.p;
        // Client `sparam.caster_attr` selects whose attribute is read:
        //   true  → the CASTER (「攻击时附加20%魔攻的伤害」#22193)
        //   false → the TARGET (「破法者」#27786, s="0")
        // The legacy `s` column encodes the same flag as "1" / "0".
        // The old ternary had the caster on BOTH branches, so a
        // target-attribute row silently used the caster's stat.
        const sj = inst.spec.sj;
        const useCaster = sj ? sj.caster_attr !== false
          : (inst.spec.s === undefined || String(inst.spec.s).includes('1'));
        for (const t of targetsOf(inst, ctx)) {
          if (t.side === inst.owner.side) continue;
          const who = useCaster ? inst.owner : t;
          let v = attrById(who, aid) * pct / 100;
          // `cut_defence:true` → the additional damage ignores the target's
          // defence; otherwise apply the normal 攻−防 reduction.
          if (!sj?.cut_defence && (dtype === 1 || dtype === 2))
            v = Math.max(0, v - attr(t, dtype === 2 ? 'SPELL_DEFENCE' : 'PHYSIC_DEFENCE'));
          const r = dealDamage(inst.owner, t, Math.round(v), {pierce: dtype === 4, kind: dtype === 2 ? 'spell' : 'physic'});
          log(`${t.name} 受到 ${r.dealt} 追加伤害（${inst.name}）`);
        }
      },
      CAST_SKILL(inst, ctx) { subCast(inst, ctx); },
      ADDITIONAL_ATTACK(inst, ctx) { subCast(inst, ctx); },
      ASSIST_ATTACK(inst, ctx) { subCast(inst, ctx); },
      // 「使所有〈铃兰之剑〉己方进行额外[协同响应]」: MAKE_OTHER_CAST_SKILL
      // #19290 declares TargetState(0,0,0,1) (unit_tag 1 = 铃兰之剑) and
      // links 15935 (50% 物攻+魔攻 穿透伤害, 自身范围 3 格). Iterate the
      // whole field, evaluate the client's own Lua condition per candidate,
      // then have THAT unit cast — not the original caster.
      MAKE_OTHER_CAST_SKILL(inst, ctx) {
        const rec = skillRec(inst.spec.p[0]);
        if (!rec) return;
        const owner = inst.owner;
        // The spec runs once PER TARGET of its parent cast (15937's AOE over
        // the 〈铃兰之剑〉allies): make THAT unit cast. Only without a unit
        // target (unit-level timing) is the whole field considered. Iterating
        // the field on every per-target run made each responder cast 3×.
        const isUnit = v => v?.base && v.hp !== undefined;
        const tgt = isUnit(ctx.target) && ctx.target !== owner ? ctx.target
          : isUnit(ctx.defender) && ctx.defender !== owner ? ctx.defender
          : (isUnit(ctx.target) ? ctx.target : null);
        const pool = tgt ? [tgt] : units;
        const chosen = pool.filter(u => u.alive && cond(inst,
          Object.assign({}, ctx, {attacker: owner, defender: u, target: u, skill: rec,
                                  coordinated: true, depth: (ctx.depth || 0) + 1})));
        if (!chosen.length) return;
        const seen = sim.otherCastSeen || (sim.otherCastSeen = new Set());
        log(`协同响应（特技 #${inst.sid}「${inst.name}」）：${chosen.map(u => u.name).join('、')} 施放「${rec.n}」#${rec.id}`);
        for (const u of chosen) {
          const k = `${sim.actionId || 0}:${inst.sid}:${u.uid}`;
          if (seen.has(k)) continue;           // one response per unit per action
          seen.add(k);
          subCast(inst, Object.assign({}, ctx, {attacker: owner, defender: u, target: u,
                                                coordinated: true}), u);
        }
        bump(cov.executed, 'MAKE_OTHER_CAST_SKILL');
      },
      MAKE_BUFF_SOURCE_CAST_SKILL(inst, ctx) { subCast(inst, ctx, inst.buff?.src); },
      // KNOCKBACK params: 后退格数 | 不击退选中目标 | 选中目标为击退中心 | 是否不触发撞击
      KNOCKBACK(inst, ctx) {
        const [cells, skipPrimary, centerOnTarget, noImpact] = inst.spec.p;
        const primary = ctx.target;
        const center = centerOnTarget && primary ? primary : (ctx.attacker && ctx.attacker !== inst.owner ? ctx.attacker : inst.owner);
        // Client attribute 32 (KNOCKBACK_DISTANCE) is a per-BUFF-LAYER bonus:
        // 后备隐藏脂肪 #3263 → #12416 gives +1 格/层 to 11495, whose spec 71
        // only declares the base 2 格. NO_KNOCKBACK_DISTANCE (冰冻地块 特技
        // #226) means 「冰面上滑退不消耗击退格数」, NOT "cancel the knockback":
        // the unit slides to the edge of the ice, then is knocked normally.
        const attrBonus = Math.round(attr(inst.owner, 'KNOCKBACK_DISTANCE',
          {attacker: inst.owner, defender: primary, target: primary, skill: ctx.skill}));
        const flagBonus = Number(inst.owner.flags?.knockDist || 0);
        const dist = Math.max(0, (cells || 1) + attrBonus + flagBonus);
        if (dist !== (cells || 1))
          log(`击退距离计算：特技参数 ${cells || 1} 格 + KNOCKBACK_DISTANCE ${attrBonus} 格 + 状态修正 ${flagBonus} 格 = ${dist} 格（${inst.name}）`);
        for (const t of targetsOf(inst, ctx)) {
          if (t === inst.owner || t === center || !t.alive) continue;
          if (skipPrimary && t === primary) continue;
          if (immuneToKnockback(t)) { log(`${t.name} 免疫击退`); continue; }
          knockback(inst.owner, center, t, dist, inst, !!noImpact);
        }
      },
      ACTED_ACT(inst) {
        if (inst.owner.flags.reActs >= 2) return;
        // Client `ACTED_ACT.p` semantics (speciality #28920, buff 8808
        // 「静聆神谕」): p=[21571,21572,21570,0] is a FORCED CHOICE GROUP —
        // 「行动开始时…强制从技能[罚斥]、[神泽]及[默祷]选择1个使用…之后触发
        // [再行动]，每个技能只能被选择1次，所有技能被使用后重置」. Two or
        // more usable skill ids therefore mean "this action may cast only one
        // member of the group", NOT "p[0] is the only allowed skill".
        const ids = (inst.spec.p || []).map(Number).filter(x => x > 0 && skillRec(x));
        if (ids.length > 1) {
          const u = inst.owner;
          const used = u.flags.choiceUsed || (u.flags.choiceUsed = new Set());
          let left = ids.filter(x => !used.has(x) && !(u.uses[x] >= (skillRec(x)?.lc || Infinity)));
          if (!left.length) { used.clear(); left = ids.slice(); }   // client reset
          for (const id of left) grantTemp(u, id, inst.name);
          // Client `ai_skill_order` (罚斥 13 > 神泽 12 > 默祷 11) is the
          // declared evaluation order inside the choice group.
          left.sort((a, b) => (skillRec(b)?.ord || 0) - (skillRec(a)?.ord || 0));
          u.flags.choiceGroup = left;
          u.flags.reAct = true;
          log(`${u.name} 触发「${inst.name}」：本次行动强制从 ${left.map(id => `「${skillRec(id)?.n || id}」#${id}`).join('、')} 选择 1 个，用后触发再行动`);
          return;
        }
        // Single id (or 0): the classic restricted / free extra action.
        // 血棘之花 → 落花之舞 21016；机动游击 → 游击 16437；金狮形态 → 20310.
        const only = ids[0] || 0;
        if (only) {
          grantTemp(inst.owner, only, inst.name);
          inst.owner.flags.reActSkill = only;
        }
        inst.owner.flags.reAct = true;
        log(`${inst.owner.name} 获得再行动${only ? `（仅限「${skillRec(only)?.n || only}」#${only}）` : ''}（${inst.name}）`);
      },
      ACTED_MOVE(inst) {
        // p[0] > 0 → that many extra tiles (罗格妮达「重击后再移动」3);
        // p[0] = 0 → 「主动攻击后可[再移动]，继承剩余移动力」: exactly the
        // REMAINING mobility. The old `max(1, …)` invented a free tile when
        // nothing was left (伦伽勒·SP walked its full 4 and still moved 1).
        const o = inst.owner;
        const n = Number(inst.spec.p[0]) || 0;
        const left = Math.max(0, Math.round(attr(o, 'MOBILITY') - (o.flags.spentMove || 0)));
        const budget = n > 0 ? n : left;
        o.flags.extraMove = Math.max(o.flags.extraMove || 0, budget);
        log(budget > 0 ? `${o.name} 获得再移动 ${budget} 格（${inst.name}）`
          : `${o.name} 的「${inst.name}」：剩余移动力为 0，没有可再移动的格数`);
      },
      SKILL_CD(inst, ctx) {
        const [, sid, delta, all] = inst.spec.p;
        for (const t of targetsOf(inst, ctx)) {
          for (const s of t.skills) {
            if (all || s.id === sid) t.cd[s.id] = Math.max(0, (t.cd[s.id] || 0) + delta);
          }
        }
        log(`${inst.owner.name} 技能冷却 ${delta > 0 ? '+' : ''}${delta}（${inst.name}）`);
      },
      // ---- Round 28: effects whose values live in skill descriptions ----
      PLACE_ITEM(inst, ctx) {
        const o = ctx.object;
        const owner = inst.owner;
        for (const t of targetsOf(inst, ctx)) {
          const at = o ? {x: o.x, y: o.y} : (t?.x != null ? {x: t.x, y: t.y} : null);
          const sub = Object.assign({}, ctx,
            {target: at ? Object.assign({}, at, {side: owner.side}) : ctx.target, object: ctx.object || sim.objectOrigin || null});
          placeObject(owner, 'PLACE_ITEM', inst.spec.p[0], inst.spec, sub);
        }
      },
      PLACE_TRAP(inst, ctx) {
        const o = ctx.object;
        const owner = inst.owner;
        const sp = String(inst.spec.s || '');
        if (/place_on_unit/.test(sp)) {
          // 「在己方所在地形格生成 1 个[苔原蜜果]」— one trap under EVERY
          // friendly unit in the cast AOE. The client immediately has that
          // unit pick the item up, which fires the trigger skill and every
          // active_time 64 「拾取蜜果 / 碎冰」 passive (能量补给 …).
          const area = new Set((ctx.area || []).map(c => key(c.x, c.y)));
          const list = (ctx.targets && ctx.targets.length ? ctx.targets : targetsOf(inst, ctx))
            .filter(u => u?.alive && area.has(key(u.x, u.y)));
          for (const t of list) {
            if (t.side !== owner.side) continue;
            const sub = Object.assign({}, ctx, {target: t, defender: t,
              blockCell: {x: t.x, y: t.y, h: grid.at(t.x, t.y)?.h || 0}, blockTrap: null,
              object: null, placeOnUnit: true});
            if (!cond(inst, sub)) continue;
            const made = placeObject(owner, 'PLACE_TRAP', inst.spec.p[0], inst.spec, sub);
            if (made && made.triggerSkill) triggerObject(made, t, sub);
          }
          return;
        }
        for (const t of targetsOf(inst, ctx)) {
          // Client sparam `find_empty` / `near_caster`: place next to the
          // caster/object; otherwise use the target cell or a free AOE tile.
          let at = null;
          if (o) at = {x: o.x, y: o.y};
          else if (t?.x != null && !/near_caster/.test(sp)) at = {x: t.x, y: t.y};
          const sub = Object.assign({}, ctx,
            {target: at ? Object.assign({}, at, {side: owner.side}) : ctx.target, object: ctx.object || sim.objectOrigin || null});
          const made = placeObject(owner, 'PLACE_TRAP', inst.spec.p[0], inst.spec, sub);
          if (made && o && /find_empty|place_on_unit|near_caster/.test(sp)) made.side = o.side;
        }
      },
      REMOVE_PROPS(inst, ctx) {
        const o = ctx.object || ctx.prop || objectAt(ctx.target?.x, ctx.target?.y);
        if (o) { destroyObject(o, '被移除', ctx); return; }
        // 「普攻摧毁雪人」: only the caster's own prop on the TARGET cell.
        // Never wipe every prop on the board when a chain has no target.
        if (!ctx.target) { bump(cov.limits, 'REMOVE_PROPS(无目标)'); return; }
        const p = placed.find(x => x.alive && x.kind === 'PLACE_ITEM' &&
          (x.id === 516 || x.id === 517 || x.id === 559) &&
          x.x === ctx.target.x && x.y === ctx.target.y);
        if (p) destroyObject(p, '被摧毁', ctx);
      },
      TRIGGER_TRAP(inst, ctx) {
        const range = inst.spec.p[0] || 1;
        const inArea = new Set((ctx.area || []).map(c => key(c.x, c.y)));
        const traps = placed.filter(x => x.kind === 'PLACE_TRAP' && x.alive && x.owner &&
          (manhattan(x, inst.owner) <= range || inArea.has(key(x.x, x.y))));
        for (const trap of traps) triggerObject(trap, inst.owner, Object.assign({}, ctx,
          {blockCell: {x: trap.x, y: trap.y}, blockTrap: trap}));
      },
      CHANGE_TRAP(inst, ctx) {
        const o = ctx.object || placed.find(x => x.kind === 'PLACE_TRAP' && x.alive);
        if (!o) return;
        const id = inst.spec.p[0] || o.id;
        o.id = id;
        const def = objectDef('PLACE_TRAP', id);
        if (def) { o.name = def.n; o.triggerSkill = def.ts; o.triggerType = def.tt; o.def = def; }
        log(`「${o.name}」变化为触发物 #${id}`);
      },
      ACTIVATION(inst, ctx) {
        if (inst.owner) inst.owner.flags.activation = true;
        if (!ctx.object) return;
        ctx.object.listeners = ctx.object.listeners || [];
        ctx.object.listeners.push(inst.spec.p[0]);
      },
      STATUS_SKILL_TO_PROPS(inst) {
        if (inst.owner) inst.owner.flags.canTargetProps = true;
      },
      WIDGET_SWITCH(inst, ctx) {
        const o = ctx.object || objectAt(inst.owner.x, inst.owner.y);
        if (o) { o.switched = !o.switched; log(`「${o.name}」开关${o.switched ? '打开' : '关闭'}`); }
      },
      PLACE_UNIT(inst, ctx) {
        // p[0] < 100 means an attribute id, i.e. a PLACE_UNIT_INHERIT_ATTR
        // style declaration; those are applied by spawnUnitFrom via the
        // parent skill's spec list, not a separate summon.
        if (inst.spec.p[0] < 100) return;
        // Client JSON `sparam.cast_limit` is the number of units THIS cast
        // places: 「以血筑国-召唤3个」#24315 has p=[7578,0,0,0] (p[1]=0)
        // but cast_limit=3. Prefer the client's compound parameter when
        // present; otherwise fall back to p[1] as before.
        const n = Math.max(1, Math.min(4,
          Number(inst.spec.sj?.cast_limit) || inst.spec.p[1] || 1));
        for (let i = 0; i < n; i++)
          spawnUnitFrom(inst.owner, inst.spec.p[0], inst.spec,
            Object.assign({}, ctx, {skill: inst.skill, sid: inst.sid,
              emptyGround: (ctx.skill?.eg && ctx.origin) || null}));
      },
      PLACE_UNIT_INHERIT_ATTR(inst, ctx) {
        // Applied to the summoned unit in spawnUnitFrom (same skill chain).
        bump(cov.executed, 'PLACE_UNIT_INHERIT_ATTR');
      },
      BUFF_BUNDLE_GAIN(inst, ctx) {
        // 「获得 X 时同时获得 Y」(信仰值正/负 san 捆绑获得喜悦/沮丧值)
        const [bid, turns] = inst.spec.p;
        if (!bid) return;
        for (const t of targetsOf(inst, ctx)) addBuff(t, bid, turns || 99, 1, inst.owner, {quiet: false});
      },
      SPECIFY_ATTRIBUTE_VALUE(inst, ctx) {
        // Static attribute lock; handled in attrCompute. Listed here so the
        // coverage report stops calling it "unimplemented".
        bump(cov.executed, 'SPECIFY_ATTRIBUTE_VALUE');
      },
      SKILL_GROUP(inst, ctx) {
        // 抉择: the options are already exported into kit.choice, so the
        // engine can cast them. Just record the trigger.
        bump(cov.executed, 'SKILL_GROUP');
      },
      // 0 client rows in the exported tables; keep the key so an unknown
      // future tactic type is explicitly recognised rather than "skipped".
      TACTICS_SKILL_GROUP(inst, ctx) { /* 战术技能分组：客户端无实装行 */ },
      IGNORE_FIELDSTATUS(inst, ctx) {
        const o = inst.owner;
        if (!o) return;
        o.flags.ignoreFieldStatus = true;
        o.flags.ignoreFieldIds = (inst.spec.p || []).filter(Boolean);
      },
      SPECIALITY_COUNT_TURN(inst, ctx) {
        // 「每回合 <特技> 次数 +N」. p[1] is speciality_type.TYPE.<name>;
        // the id -> effect-type map comes from the decrypted substrate.
        const o = inst.owner;
        if (!o) return;
        // The per-turn allowance is read straight from unitSpecs by
        // countBonusOf(); keep the legacy flag for the character panel.
        o.flags = o.flags || {};
        o.flags.counterBonus = (o.flags.counterBonus || 0) + Math.max(1, Number(inst.spec.p[2]) || 1);
        bump(cov.executed, 'SPECIALITY_COUNT_TURN');
      },
      SKILL_CD_MAX(inst, ctx) {
        const o = inst.owner;
        if (!o) return;
        for (const s of o.skills) if (s.cd !== undefined) s.cd = Math.max(0, inst.spec.p[0] || 0);
      },
      BUFF_DURATION(inst, ctx) {
        const b = inst.buff;
        if (b && Number.isFinite(b.turns)) b.turns += inst.spec.p[0] || 0;
      },
      AFFILIATE_BUFF(inst, ctx) {
        // Link a second buff to the owner of the current one.
        const [bid] = inst.spec.p;
        if (!bid || !inst.owner) return;
        addBuff(inst.owner, bid, 99, 1, inst.owner, {quiet: true});
      },
      // NOTE: ACTED_ACT / ACTED_MOVE were declared a SECOND time here with
      // bare flag writes. In a JS object literal the later key wins, which
      // silently bypassed the limit_count / reActs cap and the log, giving
      // EVERY attacker a free extra turn. The real implementations live at
      // the top of EFFECTS; do not re-declare these keys.
      CHARGE(inst, ctx) { if (inst.owner) inst.owner.flags.charge = true; },
      JUMP_MOVE(inst, ctx) {
        const o = inst.owner;
        if (o) { o.flags = o.flags || {}; o.flags.jumpBoost = (o.flags.jumpBoost || 0) + (inst.spec.p[0] || 1); }
      },
      SHADOW_STEP(inst, ctx) { if (inst.owner) inst.owner.flags.shadowStep = true; },
      IGNORE_ASSIST_DEFENCE(inst, ctx) {
        const o = inst.owner;
        if (o) { o.flags = o.flags || {}; o.flags.ignoreGuard = true; }
      },
      IGNORE_FORCE_STOP(inst, ctx) {
        const o = inst.owner;
        if (o) { o.flags = o.flags || {}; o.flags.ignoreForceStop = true; }
      },
      NOT_TURN_AROUND(inst) {
        if (inst?.owner) inst.owner.flags.notTurnAround = true;
      },
      SET_SKILL_TAG(inst, ctx) {
        const o = inst.owner;
        if (!o) return;
        const tag = String(inst.spec.s || '').split(/[|,]/).filter(Boolean)[0] || String(inst.spec.p[1] || '');
        if (!tag) return;
        o.flags.skillTags = o.flags.skillTags || [];
        if (!o.flags.skillTags.includes(tag)) o.flags.skillTags.push(tag);
        for (const sk of o.skills) { sk.tags = sk.tags || []; if (!sk.tags.includes(tag)) sk.tags.push(tag); }
        log(`${o.name} 的技能获得标签「${tag}」（${inst.name}）`);
      },
      OPERATION(inst, ctx) {
        // Client OPERATION changes a TERRAIN TILE, not the caster's state.
        // 烟幕游击 #10357 p = [18, 2, 0, 0] → [烟雾] on the landing tile
        // for 2 rounds; 贯日强击 #54 p = [10, 2, 0, 0] → 冰属性地块.
        const o = inst.owner, p = inst.spec.p || [];
        const anchor = ctx?.origin || ctx?.target || (o ? {x: o.x, y: o.y} : null);
        if (o) o.flags.operation = (o.flags.operation || 0) + 1;
        if (!anchor || !Number.isFinite(anchor.x)) return;
        const opId = Number(p[0]), fieldId = operationField(opId);
        const opName = FIELD_OPS[opId]?.name || '';
        // Client AOE terrain skills change EVERY covered cell. Single-target
        // casts keep changing just the anchor cell (烟幕游击 / 贯日强击).
        const cells = (ctx?.opArea?.length > 1 ? ctx.opArea : [anchor])
          .map(c => grid.at(c.x, c.y)).filter(Boolean);
        for (const tile of cells) setFieldStatus(tile, fieldId, Number(p[1]) || 2,
          fieldDef(fieldId)?.name || opName || inst.name, inst.sid);
        // The caster lands on / creates a concealing tile inside this same
        // action; make the tile AURA (烟雾 → 隐身) live before anything else
        // evaluates targeting. refreshAuras() is re-entrancy guarded.
        if (cells.some(t => concealFieldId(t.status))) refreshAuras();
        bump(cov.executed, 'OPERATION');
      },
      MULTI_CONSUME_TP(inst, ctx) {
        const o = inst.owner;
        if (o) o.flags.extraTpCost = (o.flags.extraTpCost || 0) + (inst.spec.p[1] || 0);
      },
      // This row is consumed by the dedicated per-command limiter in
      // castSkill() (which bumps cov.executed itself); runSpec() already
      // counted the type, so a third bump here only inflated the coverage
      // report by 2x. Declarative rows must not double-count.
      GLOBAL_LIMIT_COUNT_COMMAND(inst, ctx) { /* handled in castSkill() */ },
      SPECIAL_SKILL_CONSUME(inst, ctx) {
        const s = inst.spec, bid = s.p[2] || s.p[0];
        const layers = Math.max(1, unpackCount(s.p[3]) || 1);
        for (const t of targetsOf(inst, ctx)) {
          const b = t.buffs.find(x => x.id === bid);
          if (!b) continue;
          const used = Math.min(b.stacks, layers);
          b.stacks -= used;
          if (b.stacks <= 0) removeBuff(t, b, '消耗');
          else touch(t);
          log(`${t.name} 消耗 ${used} 层「${b.def.n}」（${inst.name}）`);
          sim.consumedStacks = (sim.consumedStacks || 0) + used;
        }
      },
      // Client speciality_type 23「技能次数」: p0 = 技能 id (0 = by
      // category), p1 = skill_category, p2 = 上限次数 delta, p3 = 消耗次数
      // delta. 菲娜塔「刻度转化」#29553 grants 召唤·虚空投影 21721 another
      // use; 乌莉娅「碎冰飞刃」#26517 does the same; 安缇歌 #31755 targets
      // ALL carried skills of category 28. The engine used to count this as
      // executed but never changed the skill's limit, so the extra cast was
      // silently lost. skillRec() returns a fresh object each call, so the
      // bonus must live on the UNIT, not on the skill record.
      SKILL_COUNT(inst, ctx) {
        const o = inst.owner;
        if (!o) return;
        const p = inst.spec.p || [];
        const dLim = Number(p[2]) || 0, dUsed = Number(p[3]) || 0;
        const direct = Number(p[0]) || 0, cat = Number(p[1]) || 0;
        const ids = direct ? [direct] : cat
          ? (o.skills || []).filter(q => Number(q.cat) === cat).map(q => q.id)
          : (ctx?.skill?.id ? [ctx.skill.id] : []);
        const applied = [];
        for (const id of ids) {
          const rec = skillRec(id);
          if (!rec) continue;
          if (dLim && rec.lc) {
            o.skillLimit = o.skillLimit || {};
            o.skillLimit[id] = (o.skillLimit[id] || 0) + dLim;
          }
          if (dUsed) o.uses[id] = (o.uses[id] || 0) + dUsed;
          applied.push(`${rec.n}#${id}(上限${dLim >= 0 ? '+' : ''}${dLim}, 消耗+${dUsed})`);
        }
        // No touch(): skillLimit / uses are not part of apSig() or any
        // attribute cache key, so invalidating every memo here would only
        // force a full attr()/unitSpecs() recompute for no benefit.
        if (applied.length)
          log(`${o.name} 的「${inst.name || inst.spec.n}」调整技能次数：${applied.join('、')}`);
      },
      // SKILL_RANGE / IMMUNE are declarative rows read by rangeMods() and the
      // immunity checks; runSpec() already counts them. No second bump.
      SKILL_RANGE(inst, ctx) { /* read by rangeMods() */ },
      IMMUNE(inst, ctx) { /* read by the immunity checks */ },
      AURA(inst, ctx) { /* auras are applied by refreshAuras() */ },
      AOE(inst, ctx) { /* area geometry is part of the skill record */ },
      STEAL_TP(inst, ctx) {
        for (const t of targetsOf(inst, ctx)) {
          if (t.side === inst.owner.side) continue;
          const n = Math.min(t.tp, inst.spec.p[1] ? t.tp : inst.spec.p[0]);
          t.tp -= n; inst.owner.tp = Math.min(attr(inst.owner, 'TP_MAX'), inst.owner.tp + n);
          if (n) log(`${inst.owner.name} 偷取 ${t.name} ${n} 点能量`);
        }
      },
      SETTLE_TOXIN(inst, ctx) {
        for (const t of targetsOf(inst, ctx)) {
          for (const b of t.buffs.filter(x => x.def.et === 'Poison')) {
            for (const sid of b.def.sp) {
              const sp = M.specs[sid];
              if (sp && (sp.t === 'LIFE_LOST' || sp.t === 'BURN')) dot({spec: sp, sid, owner: t, buff: b, name: b.def.n});
            }
            if (inst.spec.p[0]) removeBuff(t, b, '结算');
          }
        }
      },
      GET_EXTRA_SKILL(inst) { grantSkill(inst.owner, inst.spec.p[0], inst.name); },
      REPLACE_SKILL(inst) { replaceSkill(inst.owner, inst.spec.p[0], inst.spec.p[1], inst.name); },
      // SETTLE_DURATION_DAMAGE: 大类列表 | 效果类列表 | BUFF | 结算后是否移除
      SETTLE_DURATION_DAMAGE(inst, ctx) {
        const [big, eff, bid, remove] = inst.spec.p;
        for (const t of targetsOf(inst, ctx)) {
          for (const b of t.buffs.slice()) {
            const bit = effectBit(b.def.et);
            const match = bid ? b.id === bid : eff ? !!bit && !!(eff & (1 << (bit - 1))) : (big & 4) ? b.def.bt === 3 : true;
            if (!match) continue;
            let settled = false;
            for (const sid of b.def.sp) {
              const sp = M.specs[sid];
              if (sp && (sp.t === 'LIFE_LOST' || sp.t === 'BURN')) { dot({spec: sp, sid, owner: t, buff: b, name: b.def.n}); settled = true; }
            }
            if (settled && remove) removeBuff(t, b, '结算');
          }
        }
      },
      RE_ROUND(inst, ctx) {
        for (const t of targetsOf(inst, ctx)) {
          if (!t.alive) continue;
          const only = Number(inst.spec.p[0]) || 0;
          if (only) { grantSkill(t, only, inst.name); t.flags.reActSkill = only; }
          if (t === sim.turnOwner) t.flags.reAct = true;
          else if (!sim.extraTurns.includes(t)) sim.extraTurns.push(t);
          log(`${t.name} 获得新回合${only ? `（仅限「${skillRec(only)?.n || only}」）` : ''}（${inst.name}）`);
        }
      },
      SEND_OFF(inst, ctx) {
        for (const t of targetsOf(inst, ctx)) {
          if (!t.alive) continue;
          t.alive = false; t.sentOff = true; touch(t);
          log(`${t.name} 强制离场（${inst.name}）`);
        }
        refreshAuras();
      },
      // ---- Round 29: previously skipped client effects -------------------
      // TARGET_TELEPORT p = [mode, range, ...]: move the target (or caster)
      // to a free tile. mode 0/1 teleport the caster next to the target,
      // higher modes pull the target next to the caster.
      TARGET_TELEPORT(inst, ctx) {
        const s = inst.spec, o = inst.owner;
        const near = (from, other) => {
          const opts = [...grid.cells.values()].filter(c => c.walk &&
            !units.some(u => u.alive && u !== from && u.x === c.x && u.y === c.y));
          opts.sort((a, b) => (Math.abs(a.x - other.x) + Math.abs(a.y - other.y))
                            - (Math.abs(b.x - other.x) + Math.abs(b.y - other.y)));
          return opts[0];
        };
        for (const t of targetsOf(inst, ctx)) {
          if (!t.alive) continue;
          const pull = (s.p[0] || 0) > 1;
          const mover = pull ? t : o, anchor = pull ? o : t;
          const c = near(mover, anchor);
          if (!c || (mover.x === c.x && mover.y === c.y)) continue;
          mover.x = c.x; mover.y = c.y; touch(mover);
          log(`${mover.name} 传送到 (${c.x},${c.y})（${inst.name}）`);
        }
      },
      // SHARE_DAMAGE p = [buffId, percent, hpGate, cap]: link the target to
      // the caster; a share of the caster's incoming damage is diverted.
      SHARE_DAMAGE(inst, ctx) {
        const s = inst.spec, o = inst.owner;
        // p[0] = marker buff id (e.g. 神经同步 #9665); p[1] = fraction the
        // owner KEEPS, so the shared part is 100 - p[1]; p[2] = cap attribute
        // id, p[3] = cap as a percentage of that attribute.
        const bid = s.p[0];
        const pct = clamp(100 - (s.p[1] || 0), 0, 100);
        const capAttr = attrName(s.p[2]);
        const capPct = s.p[3] || 0;
        const partners = units.filter(u => u.alive && u !== o && u.buffs.some(b => b.id === bid));
        if (!partners.length) return;
        o.shareRule = {bid, pct, capAttr, capPct, name: (M?.buffs?.[bid] || {}).n || `状态 #${bid}`};
        log(`分摊伤害机制 SHARE_DAMAGE 就绪（特技 #${inst.sid}「${inst.name}」）：${o.name} 与 ${partners.length} 名拥有[${o.shareRule.name}]的角色分摊；` +
            `p = [${(s.p || []).join(', ')}] → 自身保留 ${s.p[1] || 0}%，分摊 ${pct}%${capPct ? `，单次上限 ${capAttr} × ${capPct}%` : ''}`);
      },
      // PARASITIC p = [buffId, stacks]: attach a parasite buff to the target.
      PARASITIC(inst, ctx) {
        const s = inst.spec;
        for (const t of targetsOf(inst, ctx)) {
          if (!t.alive) continue;
          if (s.p[0]) addBuff(t, s.p[0], undefined, s.p[1] || 1, inst.owner, {quiet: false});
          t.parasiteSource = inst.owner.uid;
          log(`${t.name} 被寄生（${inst.name} ×${s.p[1] || 1}）`);
        }
      },
      // RANDOM_UNIT p = [min, max, side, ...]: select N random units and let
      // the following effects of the same cast target them.
      RANDOM_UNIT(inst, ctx) {
        const s = inst.spec, n = Math.max(1, s.p[0] || s.p[1] || 1);
        const side = s.tt === 1 || s.tt === 5 ? inst.owner.side :
                     s.tt === 2 ? (inst.owner.side === 'A' ? 'B' : 'A') : null;
        const pool = units.filter(u => u.alive && u !== inst.owner && (!side || u.side === side));
        const picked = [];
        for (let i = 0; i < n && pool.length; i++) picked.push(pool.splice(Math.floor(roll() * pool.length), 1)[0]);
        sim.randomTargets = picked;
        log(`随机选取 ${picked.length} 个单位（${inst.name}）`);
      },
      RANDOM_BLOCK(inst, ctx) {
        // Client condition `return block.temp_trap == nil` means an EMPTY
        // ground tile: no unit, no prop and no trap already there.
        const origin = sim.objectOrigin || ctx.object || null;
        let cells = origin ? ringCells(origin, 1).filter(freeObjectCell)
          : (sim.objectRing && sim.objectRing.length ? sim.objectRing : (ctx.area || []).filter(freeObjectCell));
        if (!cells.length) cells = [...grid.cells.values()].filter(freeObjectCell);
        if (!cells.length) return;
        const c = cells[Math.floor(roll() * cells.length)];
        sim.randomCell = {x: c.x, y: c.y};
        sim.objectRing = (sim.objectRing || []).filter(x => x !== c);
        log(`随机选取地块 (${c.x},${c.y})（${inst.name}）`);
      },
      // SHAPESHIFT p = [formId] → client `shapeshift` row → unit_npc → unit.
      // The unit's identity becomes the form's unit, so `owner:IsUnit(923)`
      // (3279 金狮形态 after 唤醒血脉·狂鬃 form 266) now holds. The cup
      // forms inherit skills / attributes / HP%, so only identity changes.
      SHAPESHIFT(inst) {
        const o = inst.owner, form = inst.spec.p[0] || 0;
        if (!o || o.shape === form) return;
        const row = M?.shapeshifts?.[form];
        o.prevShape = o.shape || 0;
        if (o.baseUnitId === undefined) o.baseUnitId = o.unitId;
        o.shape = form;
        if (row?.unit) o.unitId = row.unit;
        touch(o);
        log(`${o.name} 变身形态 #${form}${row ? `「${row.n}」→ 单位 #${row.unit}（NPC ${row.npc}${row.inheritSkill ? '，继承技能' : ''}${row.inheritAttr ? '，继承属性' : ''}）` : ''}（${inst.name}）`);
      },
      // DELAY_SKILL p = [delay, ...]: queue this skill's linked cast for a
      // later tick instead of dropping the effect entirely.
      DELAY_SKILL(inst, ctx) {
        const s = inst.spec;
        const n = clamp(Math.round(s.p[0] || 0), 0, 8);
        const owner = inst.owner;
        const skill = ctx.skill;
        if (!skill) return;
        (sim.delayed || (sim.delayed = [])).push({owner, skill, target: ctx.target || ctx.defender, left: n});
        log(`${owner.name} 的「${skill.n}」延迟 ${n} 时点结算（${inst.name}）`);
      },
      KNOCKBACK_SELF(inst, ctx) {
        // 「向后退 N 格」: move AWAY from the other party of this event, tile
        // by tile, under the SAME blocking rules as a knockback — map edge,
        // impassable terrain, units, a rise of more than 2, pits — but
        // without collision damage. It used to jump straight to o + dir×N
        // checking only the destination: 罗格妮达「反应-反向击退自己」
        // climbed from (6,12) h4 onto a h8 ledge at (6,14) she could never
        // leave (up/down 2) and idled there for the rest of the battle. In a
        // 被攻击后 reaction ctx.defender is the owner herself, so the
        // direction also fell back to a default; use the attacker instead.
        const o = inst.owner;
        const other = [ctx.attacker, ctx.target, ctx.defender]
          .find(x => x && x !== o && Number.isFinite(x.x));
        if (!other || !o.alive) return;
        const n = Math.max(1, Number(inst.spec.p[0]) || 1);
        knockback(o, other, o, n, inst, true);
        touch(o);
      },
      // POISON p = [tier]: settle poison damage via the shared DoT helper.
      POISON(inst) { dot(inst); },
      FORCE_FRONT_STABED(inst, ctx) {
        const t = ctx.defender || ctx.target;
        if (!t) return;
        t.flags.forceFrontStabed = true;
        log(`${t.name} 被强制正面受击（${inst.name}）`);
      },
      // DAMAGE_STORAGE p = [pct, type, attr, cap]: bank a fraction of damage.
      DAMAGE_STORAGE(inst, ctx) {
        const o = inst.owner, s = inst.spec;
        const amount = Math.max(0, Number(ctx.damage) || 0) * (s.p[0] || 0) / 100;
        if (amount <= 0) return;
        o.damageStored = Math.min(s.p[3] || Infinity, (o.damageStored || 0) + amount);
        log(`${o.name} 储存 ${Math.round(amount)} 伤害（${inst.name}）`);
      },
      DEMAND_ASSIST_DEFENCE(inst, ctx) {
        const o = inst.owner;
        o.flags.demandAssist = Math.max(1, inst.spec.p[0] || 1);
        log(`${o.name} 要求援护防御（${inst.name}）`);
      },
      // TARGET_BUFF_MODIFY_ATTRIBUTE p = [buffType, attrId, per, cap]:
      // attacker gains `per` of an attribute for each debuff on the target.
      TARGET_BUFF_MODIFY_ATTRIBUTE(inst, ctx) {
        const s = inst.spec, d = ctx.defender;
        if (!d) return;
        const n = d.buffs.filter(b => b.def.bt === (s.p[0] || 3)).length;
        const v = Math.min(s.p[3] || Infinity, n * (s.p[2] || 0));
        if (v) log(`目标 ${n} 个减益，${inst.owner.name} 获得 ${v}% 属性（${inst.name}）`);
      },
      // ---- Round 29 (second pass): remaining skipped effects ---------------
      OTHER_TELEPORT_TO_TARGET(inst, ctx) {
        const o = inst.owner, s = inst.spec;
        const anchor = ctx.target || ctx.defender || o;
        const others = units.filter(u => u.alive && u !== o && u !== anchor &&
          (s.tt !== 2 || u.side === o.side));
        const free = c => c && c.walk && !units.some(u => u.alive && u.x === c.x && u.y === c.y);
        const cells = [...grid.cells.values()].filter(free);
        cells.sort((a, b) => (Math.abs(a.x - anchor.x) + Math.abs(a.y - anchor.y))
                          - (Math.abs(b.x - anchor.x) + Math.abs(b.y - anchor.y)));
        let i = 0;
        for (const u of others.slice(0, 4)) {
          const c = cells[i++];
          if (!c) break;
          u.x = c.x; u.y = c.y; touch(u);
          log(`${u.name} 传送到 ${anchor.name} 身边 (${c.x},${c.y})（${inst.name}）`);
        }
      },
      // p = [returnTP, clearCD, oncePerTurn]: refund resources after a kill.
      CONSUME_RETURN(inst, ctx) {
        const o = inst.owner, s = inst.spec;
        if (s.p[0]) { o.tp = Math.min(attr(o, 'TP_MAX'), o.tp + s.p[0]); log(`${o.name} 返还 ${s.p[0]} 能量`); }
        if (s.p[1] && ctx.skill) { o.cd[ctx.skill.id] = 0; log(`${o.name} 清空「${ctx.skill.n}」冷却`); }
      },
      // p = [skillId]: replace the current skill with a conditional branch.
      CONDITION_SKILL(inst, ctx) {
        const id = inst.spec.p[0];
        const rec = id ? skillRec(id) : null;
        if (!rec || !ctx.skill) return;
        Object.assign(ctx.skill, {sp: rec.sp, dt: rec.dt, df: rec.df, n: rec.n});
        log(`${inst.owner.name} 的「${ctx.skill.n}」切换为条件分支 #${id}`);
      },
      CHANGE_WEATHER(inst) {
        // p[0] is a WEATHER TABLE id (lua_dbtemplate/weather), not a buff id.
        // Passing it to addBuff() used to add a nonexistent BUFF#41 to every
        // unit 131 times per sweep and silently dropped the real weather aura.
        const id = inst.spec.p[0] || 0;
        const w = id ? M?.weather?.[id] : null;
        const def = w ? {n: w.name || `天气 #${id}`, d: w.desc || '', sc: 1,
                         sp: w.aura ? [Number(w.aura)] : [], ui: false, weather: true} : null;
        let applied = 0;
        for (const u of units) if (u.alive) {
          u.buffs = u.buffs.filter(b => !b.weather);
          if (!def) continue;
          if (addBuff(u, 900000 + id, Infinity, 1, null,
                      {quiet: true, weather: true, def, force: true})) applied++;
        }
        if (w) sim.weatherId = id;
        touch(inst.owner);
        log(`天气改变为「${w?.name || '普通'}」#${id || 0}${w?.aura ? `（光环特技 #${w.aura} 施加给 ${applied} 名单位）` : ''}（${inst.name}）`);
      },
      // CHARGE_ATTRIBUTE p = [attrId, 0, perStep, 1]: bonus per charged tile.
      CHARGE_ATTRIBUTE(inst, ctx) {
        const o = inst.owner, s = inst.spec;
        const steps = Math.max(0, Number(o.flags?.moveSteps) || 0);
        const v = steps * (s.p[2] || 0);
        if (!v) return;
        o.chargeBonus = o.chargeBonus || {};
        o.chargeBonus[attrName(s.p[0])] = (o.chargeBonus[attrName(s.p[0])] || 0) + v;
        touch(o);
        log(`${o.name} 冲锋 ${steps} 步，${attrName(s.p[0])} +${v}%（${inst.name}）`);
      },
      // Parasite settles: drain the stored stacks and heal the source.
      // ---- Round 30: previously skipped / static effect types --------------
      // MELEE_TRIGGER / ADDITIONAL_ATTACK with p[0] = 0 means "诱发普攻":
      // the client uses the caster's initial basic attack, not a missing id.
      MELEE_TRIGGER(inst, ctx) {
        const o = inst.owner, d = ctx.defender || ctx.target;
        if (!d?.alive) return;
        const basic = o.skills.find(s => s.id === o.basic) || o.skills[0];
        if (basic) castSkill(o, basic, grid.at(d.x, d.y), {sub: true, free: true, label: '诱发普攻'});
      },
      // TARGET_SELECT* refine a skill's target set; keep them as declared
      // filters so the effect no longer lands in the skipped report.
      TARGET_SELECT(inst, ctx) {
        const s = inst.spec, o = inst.owner;
        // p[2] (packed) = number of targets; p[1] = fallback count;
        // p[0] = side hint (1 = enemies, 2 = allies), tt = target_type.
        const n = Math.max(1, unpackCount(s.p[2]) || Math.max(1, s.p[1] || 1));
        const wantEnemy = s.p[0] === 1 || s.tt === 2;
        const wantAlly = s.p[0] === 2 || s.tt === 1 || s.tt === 3 || s.tt === 5;
        let pool = units.filter(u => u.alive && u !== o);
        if (wantEnemy) pool = pool.filter(u => u.side !== o.side);
        else if (wantAlly) pool = pool.filter(u => u.side === o.side);
        const picked = pick(pool, Math.min(n, pool.length));
        if (picked.length) { sim.randomTargets = picked; sim.selection = picked.slice(); }
      },
      TARGET_SELECT_BY_ATTRIBUTE(inst) {
        const o = inst.owner, id = inst.spec.p[0];
        const pool = units.filter(u => u.alive && u !== o && u.side !== o.side);
        const cmp = (a, b) => (attrById(b, id) || 0) - (attrById(a, id) || 0);
        if (pool.length) sim.randomTargets = [pool.sort(cmp)[0]];
      },
      TARGET_SELECT_BY_BUFF(inst) {
        const o = inst.owner, id = inst.spec.p[0];
        const pool = units.filter(u => u.alive && u.side !== o.side && u.buffs.some(b => b.id === id));
        if (pool.length) sim.randomTargets = [pool[0]];
      },
      // Movement / positioning effects.
      TELEPORT(inst, ctx) {
        const o = inst.owner, t = ctx.target || ctx.defender;
        if (!t) return;
        const near = [...grid.cells.values()].filter(c => c.walk &&
          !units.some(u => u.alive && u !== o && u.x === c.x && u.y === c.y));
        near.sort((a, b) => (Math.abs(a.x - t.x) + Math.abs(a.y - t.y)) - (Math.abs(b.x - t.x) + Math.abs(b.y - t.y)));
        const c = near[0];
        if (c) { o.x = c.x; o.y = c.y; touch(o); log(`${o.name} 瞬移到 (${c.x},${c.y})（${inst.name}）`); }
      },
      BLINK(inst, ctx) { EFFECTS.TELEPORT(inst, ctx); },
      EXCHANGE_POSITION(inst, ctx) {
        const o = inst.owner, t = ctx.target || ctx.defender;
        if (!t?.alive) return;
        const x = o.x, y = o.y;
        o.x = t.x; o.y = t.y; t.x = x; t.y = y; touch(o); touch(t);
        log(`${o.name} 与 ${t.name} 交换位置（${inst.name}）`);
      },
      HOOK(inst, ctx) {
        const o = inst.owner, t = ctx.target || ctx.defender;
        if (!t?.alive) return;
        const dx = Math.sign(o.x - t.x), dy = Math.sign(o.y - t.y);
        const c = grid.at(t.x + dx, t.y + dy);
        if (c?.walk && !units.some(u => u.alive && u !== t && u.x === c.x && u.y === c.y)) {
          t.x = c.x; t.y = c.y; touch(t); log(`${t.name} 被拉到 (${c.x},${c.y})（${inst.name}）`);
        }
      },
      DIE_INSTANTLY(inst, ctx) {
        for (const t of targetsOf(inst, ctx)) {
          if (!t.alive || t.buffs.some(b => b.def.et === 'ImmuneDie')) continue;
          kill(inst.owner, t, {skill: null});
        }
      },
      PERCENT_HEAL(inst, ctx) {
        const o = inst.owner, pct = inst.spec.p[0] || 0;
        for (const t of targetsOf(inst, ctx)) {
          if (!t.alive) continue;
          heal(o, t, Math.round(maxHpOf(t) * pct / 100), inst.name);
        }
      },
      DISABLE_SKILL(inst, ctx) {
        for (const t of targetsOf(inst, ctx)) {
          if (!t.alive) continue;
          t.flags.disabledSkills = t.flags.disabledSkills || new Set();
          if (inst.spec.p[0]) t.flags.disabledSkills.add(inst.spec.p[0]);
        }
      },
      FORCE_STOP(inst, ctx) {
        for (const t of targetsOf(inst, ctx)) if (t.alive) t.flags.forceStop = true;
      },
      EVADE(inst, ctx) { if (inst.owner) inst.owner.flags.evade = true; },
      PARRY(inst, ctx) { if (inst.owner) inst.owner.flags.parry = true; },
      // ABSORB is a declarative DEATH LISTENER (active_time 1). It is
      // dispatched explicitly by fireAbsorb() from kill(), never by fire();
      // the old handler wrote `absorbPct` from p[0] — which is a SKILL id,
      // not a percentage — into a field nothing ever read.
      ABSORB(inst, ctx) { /* dispatched by fireAbsorb() */ },
      REBORN(inst, ctx) { if (inst.owner) inst.owner.flags.reborn = (inst.owner.flags.reborn || 0) + 1; },
      COUNTER_ATTACK(inst, ctx) { if (inst.owner) inst.owner.flags.counter = true; },
      ALERT_ATTACK(inst, ctx) { if (inst.owner) inst.owner.flags.alert = true; },
      FIRST_HIT(inst, ctx) { if (inst.owner) inst.owner.flags.firstHit = true; },
      ASSIST_DEFENCE(inst, ctx) { if (inst.owner) inst.owner.flags.assistDefence = true; },
      INVISIBLE(inst, ctx) { if (inst.owner) inst.owner.flags.invisible = true; },
      IGNORE_EVADE(inst, ctx) { if (inst.owner) inst.owner.flags.ignoreEvade = true; },
      IGNORE_PARRY(inst, ctx) { if (inst.owner) inst.owner.flags.ignoreParry = true; },
      IGNORE_KNOCKBACK(inst, ctx) { if (inst.owner) inst.owner.flags.ignoreKnockback = true; },
      CAN_NOT_COUNTER(inst, ctx) { for (const t of targetsOf(inst, ctx)) if (t.alive) t.flags.cantCounter = true; },
      CAN_NOT_FIRST_HIT(inst, ctx) { for (const t of targetsOf(inst, ctx)) if (t.alive) t.flags.cantFirstHit = true; },
      CLIMB_OVER(inst, ctx) { if (inst.owner) inst.owner.move.up = Math.max(inst.owner.move.up || 2, 99); },
      NO_FIELDSTATUS_MOBILITY(inst, ctx) { if (inst.owner) inst.owner.flags.ignoreFieldStatus = true; },
      BUFF_ADD_REPLACE(inst, ctx) {
        const id = inst.spec.p[0]; if (!id) return;
        for (const t of targetsOf(inst, ctx)) if (t.alive) addBuff(t, id, undefined, inst.spec.p[1] || 1, inst.owner);
      },
      BUFF_ADD_MODIFY(inst, ctx) {
        const id = inst.spec.p[0]; if (!id) return;
        for (const t of targetsOf(inst, ctx)) {
          const b = t.buffs.find(x => x.id === id);
          if (b) { b.stacks = Math.max(1, b.stacks + (inst.spec.p[1] || 1)); touch(t); }
        }
      },
      BUFF_PARAM_CHANGE(inst, ctx) {
        const id = inst.spec.p[0];
        for (const t of targetsOf(inst, ctx)) {
          const b = t.buffs.find(x => x.id === id);
          if (b) { b.turns = Math.max(b.turns, inst.spec.p[1] || 1); touch(t); }
        }
      },
      BUFF_TARGET_LIMIT(inst, ctx) { if (inst.owner) inst.owner.flags.buffTargetLimit = inst.spec.p[0] || 1; },
      DISPEL_CONVERT(inst, ctx) {
        for (const t of targetsOf(inst, ctx)) {
          if (!t.alive) continue;
          const bad = t.buffs.find(b => b.def.bt === 3);
          if (bad) { removeBuff(t, bad, '转化为增益'); addBuff(t, inst.spec.p[0] || bad.id, undefined, 1, inst.owner); }
        }
      },
      MAKE_SUMMONER_CAST_SKILL(inst, ctx) {
        const o = inst.owner, pl = placed.find(x => x.owner === o && x.alive);
        if (pl && ctx.skill) log(`${o.name} 的召唤物「${pl.name}」协同施放「${ctx.skill.n}」`);
      },
      MAKE_DYNAMIC_CAST_SKILL(inst, ctx) {
        const id = inst.spec.p[0]; const rec = id ? skillRec(id) : null;
        if (rec && ctx.target) castSkill(inst.owner, rec, grid.at(ctx.target.x, ctx.target.y), {sub: true, free: true, label: '动态施放'});
      },
      DELAY_CAST_SKILL(inst, ctx) { EFFECTS.DELAY_SKILL(inst, ctx); },
      FORCE_CAST_SKILL(inst, ctx) {
        const id = inst.spec.p[0]; const rec = id ? skillRec(id) : null;
        const t = ctx.target || ctx.defender;
        if (rec && t) castSkill(inst.owner, rec, grid.at(t.x, t.y), {sub: true, free: true, label: '强制施放'});
      },
      SKILL_HEIGHT(inst, ctx) { if (inst.owner) inst.owner.flags.skillHeight = inst.spec.p[0] || 1; },
      FORCE_DAMAGE_TYPE(inst, ctx) { if (inst.owner) inst.owner.flags.forceDamageType = inst.spec.p[0] || 1; },
      FORCE_INITIATIVE(inst, ctx) { if (inst.owner) inst.owner.flags.forceInitiative = true; },
      RESET_LIMIT_COUNT(inst, ctx) { if (inst.owner) inst.owner.limits = {}; },
      BUFF_COUNTERACT(inst, ctx) {
        for (const t of targetsOf(inst, ctx)) {
          const n = t.buffs.length;
          if (n) { removeBuff(t, t.buffs[0], '抵消'); }
        }
      },
      HEALED_REVERSE(inst, ctx) { for (const t of targetsOf(inst, ctx)) if (t.alive) t.flags.healReverse = true; },
      FORBIDDEN_RECOVER(inst, ctx) { for (const t of targetsOf(inst, ctx)) if (t.alive) t.flags.noRecover = true; },
      NOT_RECOVER_TP(inst, ctx) { for (const t of targetsOf(inst, ctx)) if (t.alive) t.flags.noRecoverTp = true; },
      IGNORE_ARMOR(inst, ctx) { if (inst.owner) inst.owner.flags.ignoreArmor = true; },
      ABSORB_SEND_OFF(inst, ctx) { EFFECTS.SEND_OFF(inst, ctx); },
      DIZZY(inst, ctx) { for (const t of targetsOf(inst, ctx)) if (t.alive) t.flags.dizzy = true; },
      FROZEN(inst, ctx) { for (const t of targetsOf(inst, ctx)) if (t.alive) t.flags.frozen = true; },
      HYPNOTIZE(inst, ctx) {
    // Client HYPNOTIZE puts the target into a control state (「无法做出任何
    // 行动」). Merely setting flags.charm was inert: takeTurn() only inspects
    // buff definitions through isControlBuff(). Sleep / 催眠 buffs already
    // carry mt:'Control'; for a bare HYPNOTIZE spec attach the same marker so
    // the target actually loses its turn.
    for (const t of targetsOf(inst, ctx)) {
      if (!t.alive) continue;
      t.flags.charm = true;
      if (!t.buffs?.some(b => isControlBuff(b)))
        addBuff(t, 645, 2, 1, inst.owner, {force: true});
    }
  },
      ISOLATE(inst, ctx) { for (const t of targetsOf(inst, ctx)) if (t.alive) t.flags.isolate = true; },
      // ---- Round 31: remaining client speciality types -------------------
      // These are mostly state markers the client checks during damage,
      // movement, targeting and restraint resolution. Implementing them as
      // flags (rather than reporting them as skipped) lets dependent logic
      // consult them and makes the coverage report honest.
      MOVE_ATTACK(inst, ctx) { if (inst.owner) inst.owner.flags.moveAttack = inst.spec.p[0] || 1; },
      ASSIST_TEAMMATE(inst) { if (inst.owner) inst.owner.flags.assistTeammate = true; },
      SPELL_INSTANCE(inst) { if (inst.owner) inst.owner.flags.spellInstance = true; },
      PATH_OPERATION(inst, ctx) { if (ctx?.target) ctx.target.flags.pathOperation = inst.spec.p[0] || 1; },
      CAN_NOT_BE_ASSIT_DEFENCE(inst) { if (inst.owner) inst.owner.flags.cantBeAssisted = true; },
      DISPEL_TRANSFER(inst, ctx) {
        for (const t of targetsOf(inst, ctx)) {
          const bad = t.buffs.find(b => b.def.bt === 3);
          if (bad) { removeBuff(t, bad, '转移'); addBuff(inst.owner, bad.id, 1, 1, t); }
        }
      },
      HIGHLAND(inst) { if (inst.owner) inst.owner.flags.highland = inst.spec.p[0] || 1; },
      AURA_RANGE(inst) { if (inst.owner) inst.owner.flags.auraRange = inst.spec.p[0] || 1; },
      CLIMB_OVER_COUNT(inst) { if (inst.owner) inst.owner.move.up = Math.max(inst.owner.move.up || 2, inst.spec.p[0] || 2); },
      ABNORMAL_STATE(inst, ctx) {
        for (const t of targetsOf(inst, ctx)) if (t.alive) t.flags.abnormal = inst.spec.p[0] || 1;
      },
      UNIT_CAN_THROUGH(inst) { if (inst.owner) inst.owner.flags.canThrough = true; },
      STRENGTHEN_ALERT(inst) { if (inst.owner) inst.owner.flags.strengthenAlert = true; },
      KNOCKBACK_DISTANCE_MODIFY(inst) { if (inst.owner) inst.owner.flags.knockDist = inst.spec.p[0] || 1; },
      ALERT_ATTACK_DISPLAY(inst) {
        if (inst.owner) inst.owner.flags.alertDisplay = true;
        bump(cov.executed, 'ALERT_ATTACK_DISPLAY');
      },
      DELAY_SKILL_INSTANCE(inst, ctx) { EFFECTS.DELAY_SKILL(inst, ctx); },
      SKILL_COUNT_TURN(inst) {
        const o = inst.owner;
        if (o && inst.spec.p[0]) o.uses[inst.spec.p[0] + ':t'] = 0;
      },
      OVERFLOW_DAMAGE_STORAGE(inst) { if (inst.owner) inst.owner.flags.overflowStorage = inst.spec.p[0] || 1; },
      HP_LOW_LIMIT(inst) { if (inst.owner) inst.owner.flags.hpLowLimit = inst.spec.p[0] || 1; },
      BODY_REPLACE(inst, ctx) {
        const o = inst.owner, t = ctx.target || ctx.defender;
        if (t?.alive && o) { const x = o.x, y = o.y; o.x = t.x; o.y = t.y; t.x = x; t.y = y; touch(o); touch(t); }
      },
      FORGET(inst) { if (inst.owner) inst.owner.flags.forget = true; },
      SEAL(inst, ctx) { for (const t of targetsOf(inst, ctx)) if (t.alive) t.flags.seal = true; },
      CONVERT_ANIM(inst) { /* animation only */ },
      REFLECT_DAMAGE(inst) { if (inst.owner) inst.owner.flags.reflect = inst.spec.p[0] || 0; },
      STRAIGHT(inst) { if (inst.owner) inst.owner.flags.straight = true; },
      HEIGHT_ZERO_MOBILITY(inst) { if (inst.owner) inst.owner.flags.heightZeroMobility = true; },
      CHANGE_PROFESSION_BY_SKILL(inst) { if (inst.owner) inst.owner.flags.profBySkill = inst.spec.p[0] || 1; },
      CHANGE_PROFESSION_BY_BUFF(inst) { if (inst.owner) inst.owner.flags.profByBuff = inst.spec.p[0] || 1; },
      CANT_ASSIST(inst, ctx) { for (const t of targetsOf(inst, ctx)) if (t.alive) t.flags.cantAssist = true; },
      CANT_TRANSFER(inst, ctx) { for (const t of targetsOf(inst, ctx)) if (t.alive) t.flags.cantTransfer = true; },
      CANT_REBORN(inst, ctx) { for (const t of targetsOf(inst, ctx)) if (t.alive) t.flags.cantReborn = true; },
      CONVERT_SKILL(inst) { if (inst.owner) inst.owner.flags.convertSkill = inst.spec.p[0] || 1; },
      CANT_COUNTER(inst, ctx) { for (const t of targetsOf(inst, ctx)) if (t.alive) t.flags.cantCounter = true; },
      CANT_FIRST_HIT(inst, ctx) { for (const t of targetsOf(inst, ctx)) if (t.alive) t.flags.cantFirstHit = true; },
      CHARM(inst, ctx) { for (const t of targetsOf(inst, ctx)) if (t.alive) t.flags.charm = true; },
      DISARM(inst, ctx) { for (const t of targetsOf(inst, ctx)) if (t.alive) t.flags.disarm = true; },
      CAN_NOT_TRIGGER_AI(inst, ctx) { for (const t of targetsOf(inst, ctx)) if (t.alive) t.flags.noTriggerAI = true; },
      TAUNTED(inst, ctx) { for (const t of targetsOf(inst, ctx)) if (t.alive) t.flags.taunted = true; },
      DEEP_HYPNOTIZE(inst, ctx) { for (const t of targetsOf(inst, ctx)) if (t.alive) t.flags.deepSleep = true; },
      BUFF_MODIFY_ATTRIBUTE(inst) { if (inst.owner) inst.owner.flags.buffModifyAttr = true; },
      FADE(inst) { if (inst.owner) inst.owner.flags.fade = true; },
      IGNORE_PROFESSION_RESTRAIN(inst) { if (inst.owner) inst.owner.flags.ignoreRestrain = true; },
      // NOT_TURN_AROUND is declared once at the top of EFFECTS; the duplicate
      // flag-only copy was removed (same JS-object-literal shadowing bug).
      DISPLAY_AOE(inst) { /* client UI hint only */ },
      IGNORE_INVISIBLE(inst) { if (inst.owner) inst.owner.flags.ignoreInvisible = true; },
      DISABLE_INVISIBLE(inst, ctx) { for (const t of targetsOf(inst, ctx)) if (t.alive) t.flags.invisible = false; },
      PASS_THROUGH_ATTACK(inst) { if (inst.owner) inst.owner.flags.passThrough = true; },
      STATE_RESTORE(inst, ctx) {
        for (const t of targetsOf(inst, ctx)) if (t.alive) { t.hp = t.hp; touch(t); }
      },
      EXTEND_CAST_RANGE(inst) { if (inst.owner) inst.owner.flags.extendRange = inst.spec.p[0] || 1; },
      AOE_EXTEND(inst) { if (inst.owner) inst.owner.flags.aoeExtend = inst.spec.p[0] || 1; },
      BUFF_SOURCE_RANGE_MOBILITY_COST(inst) { if (inst.owner) inst.owner.flags.buffSourceMove = inst.spec.p[0] || 1; },
      // Client effect types that only appear outside the current cup closure
      // but are declared in speciality_type.json. Keep them recognised so a
      // future data refresh does not silently drop them.
      MODIFY_WT(inst) { if (inst.owner) inst.owner.flags.modifyWt = inst.spec.p[0] || 0; },
      ROGUE_MONEY_MODIFY(inst) { if (inst.owner) inst.owner.flags.rogueMoney = inst.spec.p[0] || 0; },
      ROGUE_TEAM_HP_MODIFY(inst) {
        const v = inst.spec.p[0] || 0;
        for (const u of units) if (u.alive && u.side === inst.owner.side) u.hp = Math.min(maxHpOf(u), u.hp + v);
      },
      ROCK_ROLL(inst, ctx) {
        const o = ctx.object || objectAt(inst.owner.x, inst.owner.y, 'PLACE_ITEM');
        if (!o?.movable) return;
        const dir = inst.owner.dir || [1, 0];
        const c = grid.at(o.x + dir[0], o.y + dir[1]);
        if (c?.walk && !objectAt(c.x, c.y) && !units.some(u => u.alive && u.x === c.x && u.y === c.y)) {
          o.x = c.x; o.y = c.y;
          log(`「${o.name}」滚动到 (${c.x},${c.y})`);
          for (const u of units) if (u.alive && u.x === c.x && u.y === c.y && u.side !== inst.owner.side)
            dealDamage(inst.owner, u, inst.spec.p[0] || 0, {pierce: true});
        }
      },
      RECOVER_TACTIC(inst) { if (inst.owner) inst.owner.tp = Math.min(attr(inst.owner, 'TP_MAX'), inst.owner.tp + (inst.spec.p[0] || 1)); },
      PATH(inst) { if (inst.owner) inst.owner.flags.pathMark = inst.spec.p[0] || 1; },
      FACING_TRIGGER_BEFORE_CAST(inst) { if (inst.owner) inst.owner.flags.facingTrigger = true; },
      // ---- remaining declared client types (speciality_type.json) --------
      ABSOLUTE_INVISIBLE(inst) { if (inst.owner) inst.owner.flags.absoluteInvisible = true; },
      ATTRIBUTE_CONVERT_BUFF(inst) { if (inst.owner) inst.owner.flags.attributeConvertBuff = inst.spec.p[0] || 0; },
      ATTRIBUTE_DAMAGE(inst) { if (inst.owner) inst.owner.flags.attributeDamage = inst.spec.p[0] || 0; },
      BOMB(inst, ctx) {
        const o = ctx.object || objectAt(inst.owner.x, inst.owner.y);
        if (o) { o.bomb = inst.spec.p[0] || 1; log(`「${o.name}」被标记为爆弹`); }
      },
      BOSS_ARMOR(inst) { if (inst.owner) inst.owner.flags.bossArmor = true; },
      BUFF_ADD_STACK_LIMIT_TURN(inst) { if (inst.owner) inst.owner.flags.buffStackLimit = inst.spec.p[0] || 1; },
      BUFF_TRANSFER(inst, ctx) {
        const t = ctx.target || ctx.defender;
        if (t?.alive && inst.owner?.alive) {
          const b = t.buffs.find(x => x.def.bt === 2);
          if (b) { removeBuff(t, b, '转移'); addBuff(inst.owner, b.id, b.turns, b.stacks, t); }
        }
      },
      CONSUME_TEAM_HP(inst) {
        const pct = inst.spec.p[0] || 0;
        for (const u of units) if (u.alive && u.side === inst.owner.side && u !== inst.owner)
          dealDamage(inst.owner, u, Math.round(maxHpOf(u) * pct / 100), {pierce: true});
      },
      COPY_ATTRIBUTE(inst, ctx) {
        const t = ctx.target || ctx.defender;
        if (t?.base && inst.owner) inst.owner.flags.copyFrom = t.uid;
      },
      DAMAGE_BUFFER_DYNAMIC(inst) { if (inst.owner) inst.owner.flags.dynamicBuffer = inst.spec.p[0] || 0; },
      ELEMENT_MASTER(inst) { if (inst.owner) inst.owner.flags.elementMaster = inst.spec.p[0] || 1; },
      // Client element_type (element.json 地/火/风/水/光/暗). The client's
      // battle Lua has NO element restraint table and units carry no element
      // column, so this is a declarative damage TAG, not a damage multiplier.
      // Record it on the live cast so the replay / labels can show 「火属性」.
      ELEMENT_TYPE(inst, ctx) {
        const id = Number(inst.spec.p?.[0]) || 0;
        if (!id) return;
        sim.castElement = id;
        if (ctx?.skill?.__skill) ctx.skill.__skill.element = id;
        if (inst.skill) inst.skill.element = id;
      },
      EXTRA_FIELD_STATUS(inst, ctx) {
        const c = grid.at(ctx.target?.x, ctx.target?.y);
        if (c) setFieldStatus(c, operationField(inst.spec.p[0]), 99, inst.name, inst.sid);
      },
      FADE_TO_ALLIES(inst) { for (const u of units) if (u.alive && u.side === inst.owner.side) u.flags.fade = true; },
      FIELD_STATUS_SPREAD(inst, ctx) {
        const c = grid.at(ctx.target?.x, ctx.target?.y);
        if (!c) return;
        for (const [dx, dy] of DIRS) {
          const n = grid.at(c.x + dx, c.y + dy);
          if (n) setFieldStatus(n, c.status || NORMAL_FIELD, 99, inst.name, inst.sid);
        }
      },
      FORBIDDEN_ATTRIBUTE(inst) { if (inst.owner) inst.owner.flags.forbiddenAttr = inst.spec.p[0] || 0; },
      IGNORE_NOT_CHECK_EXTERNAL_SPEC(inst) { if (inst.owner) inst.owner.flags.ignoreExternalSpec = true; },
      IMMUNE_COUNTED(inst) { if (inst.owner) inst.owner.flags.immuneCounted = true; },
      JUMP_AND_ATTACK(inst, ctx) { EFFECTS.JUMP_MOVE(inst, ctx); },
      JUMP_ATTACK(inst, ctx) { EFFECTS.JUMP_MOVE(inst, ctx); },
      LOGIC_SKILL(inst) { if (inst.owner) inst.owner.flags.logicSkill = true; },
      MOVETYPE(inst) { if (inst.owner) inst.owner.move.type = inst.spec.p[0] || inst.owner.move.type; },
      NO_KNOCKBACK_DISTANCE(inst) { if (inst.owner) inst.owner.flags.noKnockDistance = true; },
      OVERWEIGHT(inst) { if (inst.owner) inst.owner.flags.overweight = true; },
      PATH_EXTRA_FIELD_STATUS(inst) { if (inst.owner) inst.owner.flags.pathFieldStatus = inst.spec.p[0] || 0; },
      RANGE_HEIGHT_EQUAL_MELEE(inst) { if (inst.owner) inst.owner.flags.rangeHeightEqual = true; },
      REACTIVE_SKILL(inst) { if (inst.owner) inst.owner.flags.reactiveSkill = inst.spec.p[0] || 0; },
      SKILL_TARGET_FILTER(inst) { if (inst.owner) inst.owner.flags.targetFilter = inst.spec.p[0] || 0; },
      SPECIALITY_COUNT_USE(inst) { if (inst.owner) inst.owner.flags.specCountUse = inst.spec.p[0] || 1; },
      SPELL_MOVED(inst) { if (inst.owner) inst.owner.flags.spellMoved = true; },
      UNIT_STAR(inst) { if (inst.owner) inst.owner.star = inst.spec.p[0] || inst.owner.star; },
      UNIT_TAG(inst) { if (inst.owner) (inst.owner.tags || (inst.owner.tags = [])).push(inst.spec.p[0]); },
      WT_END(inst) { if (inst.owner) inst.owner.flags.wtEnd = true; },
      ARROW_WALL(inst, ctx) {
        const o = ctx.object || objectAt(inst.owner.x, inst.owner.y);
        if (o) { o.arrowWall = true; o.dir = inst.owner.dir || [1, 0]; }
      },
      WIDGET_SWITCH_ALIAS() {},
      TRANSFER(inst, ctx) { EFFECTS.TARGET_TELEPORT(inst, ctx); },
      TP_CONSUME_CHANGE(inst) { if (inst.owner) inst.owner.flags.tpChange = inst.spec.p[0] || 0; },
      MULTI_ATTACK(inst) { if (inst.owner) inst.owner.flags.multiAttack = true; },
      EACH_DAMAGE_REDUCED(inst) { if (inst.owner) inst.owner.flags.eachDamageReduced = inst.spec.p[0] || 0; },
      CANT_KILL_DIE(inst) { if (inst.owner) inst.owner.flags.cantKillDie = true; },
      SWITCH_DAMAGE_TYPE(inst) { if (inst.owner) inst.owner.flags.switchDamageType = inst.spec.p[0] || 1; },
      ROLL_REDUCE(inst) { if (inst.owner) inst.owner.flags.rollReduce = inst.spec.p[0] || 0; },
      VIEW_AS_ENEMY(inst, ctx) { for (const t of targetsOf(inst, ctx)) if (t.alive) t.flags.viewAsEnemy = true; },
      SIMULTANEOUS_DAMAGE(inst) { if (inst.owner) inst.owner.flags.simultaneous = true; },
      HEAL_REVERSE(inst, ctx) { for (const t of targetsOf(inst, ctx)) if (t.alive) t.flags.healReverse = true; },
      IGNORE_SHAPESHIFT(inst) { if (inst.owner) inst.owner.flags.ignoreShapeshift = true; },
      FORCE_BACKSTAB(inst) { if (inst.owner) inst.owner.flags.forceBackstab = true; },
      PARASITIC_RECOVERY(inst, ctx) {
        const o = inst.owner;
        const stacks = o.buffs.filter(b => b.id === (inst.spec.p[0] || 0)).reduce((a, b) => a + b.stacks, 0);
        const amount = Math.round(stacks * (inst.spec.p[1] || 10));
        if (amount > 0) heal(o, o, amount, inst.name);
      },
      // p = [perHit, cap]: cap the number of times this unit can be damaged
      // in a single turn; excess damage is ignored.
      PER_DAMAGED_LIMIT(inst, ctx) {
        const o = inst.owner, cap = inst.spec.p[1] || inst.spec.p[0] || 1;
        o.damagedCap = Math.max(1, cap);
        log(`${o.name} 每回合最多受击 ${o.damagedCap} 次（${inst.name}）`);
      },
      FORBIDDEN_REACTIVE(inst, ctx) {
        const t = ctx.defender || ctx.target;
        if (t) { t.flags.forbidReactive = true; log(`${t.name} 被禁止反应技能（${inst.name}）`); }
      },
      HEAL_LIMIT(inst, ctx) {
        const t = ctx.target || ctx.defender || inst.owner;
        if (t) { t.flags.healLimit = true; log(`${t.name} 受到治疗上限限制（${inst.name}）`); }
      },
      JUMP_FOR_SAVE(inst, ctx) {
        const t = ctx.target || inst.owner;
        if (t) { t.flags.jumpSave = inst.spec.p[2] || 0; log(`${t.name} 获得落水救星（${inst.name}）`); }
      },
    };
    const unpackCount = v => (Number(v) > 0xFFFF ? (Number(v) & 0xFFFF) : Number(v)) || 0;
    function pick(list, n) {
      const a = list.slice(), out = [];
      while (a.length && out.length < n) out.push(a.splice(Math.floor(roll() * a.length), 1)[0]);
      return out;
    }
    function dispel(inst, ctx, positiveDefault) {
      const [big, eff, bid, packed] = inst.spec.p;
      const count = (packed & 0xFFFF) || (bid ? 99 : 1);
      // Client JSON `sparam.buff_category` narrows a DISPEL/REMOVE_BUFF row
      // to ONE OR MORE buff categories. 叶迦内「补构之律」#22116 declares
      // [24] = 无法治疗, but its p = [0,0,0,6488163] means "remove up to 99"
      // — ignoring this filter wiped 627 unrelated buffs (再生2 / 攻击2 /
      // 治疗2 …) across the 192-game sweep.
      const cats = inst.spec.sj?.buff_category;
      const catSet = Array.isArray(cats) && cats.length ? new Set(cats.map(Number)) : null;
      for (const t of targetsOf(inst, ctx)) {
        let removed = 0;
        const list = t.buffs.slice().reverse();
        for (const b of list) {
          if (removed >= count) break;
          if (catSet && !catSet.has(Number(b.def.cat))) continue;
          let match = false;
          if (catSet) {
            // The category list IS the selection rule; the client does not
            // additionally require the buff's 增益/减益 polarity (cat 24
            // 「受治疗」rows are all bt=3). Only aura buffs stay protected.
            match = !b.aura;
          } else if (bid) match = b.id === bid;
          else if (eff) { const bit = effectBit(b.def.et); match = !!bit && !!(eff & (1 << (bit - 1))); }
          else {
            const wantDebuff = (big & 4) || (!(big & 2) && !positiveDefault && t.side === inst.owner.side);
            match = b.def.disp && !b.aura && (wantDebuff ? b.def.bt === 3 : b.def.bt === 2);
          }
          if (match) { removeBuff(t, b, '被驱散'); removed++; }
        }
      }
    }
    function dot(inst) {
      const [aid, pct, own] = inst.spec.p;
      const holder = inst.owner;
      const who = own ? holder : (inst.buff?.src || holder);
      const base = attrById(who, aid) * pct / 100 *
        (inst.spec.sj?.ignore_buff_stack_count ? 1 : (inst.buff?.stacks || 1));
      const mult = clamp((1 + attr(holder, 'FIX_BEDAMAGE') / 100) * (1 + attr(holder, 'DURATION_DAMAGE_MODIFY') / 100), 0, 2.3);
      const r = dealDamage(inst.buff?.src && inst.buff.src !== holder ? inst.buff.src : null, holder, Math.round(base * mult), {pierce: true});
      if (r.dealt) log(`${holder.name} 受到 ${r.dealt} 持续伤害（${inst.name}）`);
    }
    // A skill change must refresh EVERY derived index, otherwise the AI keeps
    // scoring a stale id, [瞬发] is not recognised and attached passives of
    // the NEW skill never become active. It must also PRESERVE the client's
    // declared orders: `ai.order` is kit.skillOrder (the byOrder AI rotation)
    // and `slotOrder` is the 技能放置顺序. A swapped-in skill inherits the old
    // skill's slot / tier / AI position; a granted extra skill (堆堆雪人,
    // 落花之舞 …) is appended to the bar but never injected into ai.order.
    // Overwriting ai.order with the bar list broke 乌莉娅's byOrder rotation.
    function rebuildSkillState(u, from, to) {
      const have = new Set(u.skills.map(s => Number(s.id)));
      const swap = Number.isFinite(Number(from)) && Number(from) && Number(to)
        ? [Number(from), Number(to)] : null;
      const remap = id => (swap && Number(id) === swap[0] ? swap[1] : Number(id));
      const slots = (u.slotOrder || []).map(remap).filter(id => have.has(id));
      for (const id of have) if (!slots.includes(id)) slots.push(id);
      u.slotOrder = [...new Set(slots)];
      const prevTier = u.skillTier instanceof Map ? u.skillTier : new Map();
      const t = new Map();
      for (const s of u.skills) {
        const id = Number(s.id);
        const inherited = swap && id === swap[1] ? prevTier.get(swap[0]) : prevTier.get(id);
        t.set(id, inherited || (s.isNormal ? 'basic'
          : ((u.personalityIds || []).map(Number).includes(id) || Number(s.ct) === 7) ? 'personality' : 'carried'));
      }
      u.skillTier = t;
      u.instantIds = new Set(u.skills.filter(isInstant).map(s => Number(s.id)));
      if (u.ai && swap) {
        u.ai.order = (u.ai.order || []).map(remap);
        if (Array.isArray(u.ai.sequence)) u.ai.sequence = u.ai.sequence.map(remap);
      }
      for (const s of u.skills) {
        if (u.cd[s.id] === undefined) u.cd[s.id] = s.pcd > 0 ? s.pcd : 0;
        if (u.uses[s.id] === undefined) u.uses[s.id] = 0;
      }
      // Attached passives (skill_attached_passive_id) are live only while
      // their parent skill is equipped — rebuilding is what makes 技能变更
      // switch 贯日强击 ↔ 瞬身袭 passives too.
      u.passive = collectPassives(u, u.passiveSkills || [], u.skills);
      touch(u);
    }
    function replaceSkill(u, from, to, label, turns = 0) {
      const i = u.skills.findIndex(s => Number(s.id) === Number(from));
      const rec = skillRec(to);
      if (i < 0 || !rec || Number(from) === Number(to)) return false;
      const old = u.skills[i];
      rec.isNormal = old.isNormal;
      u.skills[i] = rec;
      rebuildSkillState(u, from, to);
      log(`${u.name} 的「${old.n}」#${from} 变更为「${rec.n}」#${to}（${label || '技能变更'}${turns ? `，持续 ${turns} 回合` : ''}）`);
      if (turns > 0) sim.swapTimers.push({unit: u, from: Number(to), to: Number(from),
        due: sim.round + turns, label: `${label || '技能变更'} 到期`});
      bump(cov.executed, 'REPLACE_SKILL');
      return true;
    }
    // Restricted extra-action skills (落花之舞 / 游击 / 露西亚之血永存！)
    // live in `kit.derived`, not in the castable bar. The client grants them
    // at trigger time; refresh all derived indexes so the AI can cast them.
    function grantSkill(u, id, label) {
      const rec = skillRec(id);
      if (!rec || u.skills.some(s => Number(s.id) === Number(id))) return false;
      u.skills.push(rec);
      rebuildSkillState(u);
      if (u.cd[id] === undefined) u.cd[id] = 0;
      log(`${u.name} 获得技能「${rec.n}」#${id}（${label || 'GET_EXTRA_SKILL'}）`);
      bump(cov.executed, 'GET_EXTRA_SKILL');
      return true;
    }
    // Record a buff change for unit.changed_buffs (current cast only).
    function noteChanged(u, b) {
      if (!u) return;
      const s = sim.castSerial || 0;
      const list = (u._chg || []).filter(x => x.serial === s);
      if (!list.some(x => x.b === b)) list.push({b, serial: s});
      u._chg = list;
    }
    // ACTED_ACT names a skill the unit may cast in THAT action only: 游击
    // (伦伽勒·SP「当前行动结束时，可使用[游击]，每回合最多触发1次」), 落花之舞
    // (野狐塞娜 血棘之花), 罚斥 / 神泽 / 默祷 (珀列维特 静聆神谕). None of them
    // is on the unit's own bar. Granting them permanently let the AI cast
    // 游击 again as an ordinary skill in the next main action, i.e. twice per
    // round. Such grants are temporary and revoked when they are spent.
    function grantTemp(u, id, label) {
      if (!grantSkill(u, id, label)) return;
      (u.flags.tempSkills || (u.flags.tempSkills = new Set())).add(Number(id));
    }
    function revokeTemp(u, ids, label) {
      const set = u.flags.tempSkills;
      if (!set?.size) return;
      const drop = (ids ? ids.map(Number) : [...set]).filter(id => set.has(id));
      if (!drop.length) return;
      for (const id of drop) set.delete(id);
      u.skills = u.skills.filter(s => !drop.includes(Number(s.id)));
      rebuildSkillState(u);
      log(`${u.name} 失去技能 ${drop.map(id => `「${skillRec(id)?.n || id}」`).join('、')}（${label}）`);
    }
    function applySwapTimers() {
      if (!sim.swapTimers.length) return;
      const due = sim.swapTimers.filter(t => sim.round >= t.due);
      sim.swapTimers = sim.swapTimers.filter(t => sim.round < t.due);
      for (const t of due) if (t.unit.alive) replaceSkill(t.unit, t.from, t.to, t.label);
    }
    function subCast(inst, ctx, casterOverride) {
      // Client chains nest: 号令 15934 → skill_cast_id 15968 → CAST_SKILL
      // 15937 → MAKE_OTHER_CAST_SKILL 15935 is depth 3. runSpec keeps its own
      // `sim.depth > 6` recursion guard, so allow up to 5 linked casts here.
      if ((ctx.depth || 0) >= 5) return;
      const s = inst.spec;
      const caster = casterOverride || inst.owner;
      // Client ADDITIONAL_ATTACK / MELEE_TRIGGER with p[0] = 0 means "诱发普攻":
      // use the caster's initial melee skill rather than reporting a missing id.
      const rec = s.p[0] ? skillRec(s.p[0]) : caster?.skills.find(x => x.id === caster.basic) || caster?.skills[0];
      if (!rec || !caster?.alive) { if (!rec) bump(cov.skipped, s.t + '(缺技能)'); return; }
      let target = (s.p[1] || s.t === 'ADDITIONAL_ATTACK') ? (ctx.target || (ctx.attacker === caster ? ctx.defender : ctx.attacker)) : null;
      if (target && !target.alive) target = null;
      if (ctx.prop?.alive) target = ctx.prop;   // 目标是物件： CAST_SKILL 链条继续指向它
      if (!target) {
        const aim = rec.aim;
        const pool = aim === 'ally' || rec.dt === 3 ? alliesOf(caster) : aim === 'self' ? [caster] : enemiesOf(caster);
        target = pool.sort((a, b) => manhattan(a, caster) - manhattan(b, caster))[0] || null;
      }
      // Client JSON `sparam.force_cast`: a state-machine transition
      // (变身结束变回去 / 分身到时间离场 / 激昂满层获得再动) must resolve
      // even when no enemy/ally target exists. Such linked skills are
      // aim=self effects; fall back to the caster instead of silently
      // dropping the whole chain (12 dispatches lost in the 192-game sweep).
      if (!target && s.sj?.force_cast) target = caster;
      if (!target) return;
      if (s.p[3] && s.p[3] <= 0xFFFF && manhattan(caster, target) > Math.max(rec.rmax, 1)) return;
      // A client skill carrying TARGET_SELECT applies its effects to N units
      // picked at once (e.g. 黑暗医师「战斗开始时随机使 3 名友军获得
      // [神经同步]」). Those skills have no attack geometry: run their effect
      // specs directly against the selected roster instead of a single cell.
      const selSpec = (rec.sp || []).map(id => M?.specs?.[id]).find(sp => sp && sp.t === 'TARGET_SELECT');
      if (selSpec) {
        const n = Math.max(1, unpackCount(selSpec.p[2]) || Math.max(1, selSpec.p[1] || 1));
        let pool = units.filter(u => u.alive && u !== caster);
        if (selSpec.tt === 1 || selSpec.tt === 3 || selSpec.tt === 5 || selSpec.p[0] === 2)
          pool = pool.filter(u => u.side === caster.side);
        else if (selSpec.tt === 2 || selSpec.p[0] === 1)
          pool = pool.filter(u => u.side !== caster.side);
        const picked = pick(pool, Math.min(n, pool.length));
        sim.selection = picked.slice();
        for (const k of [2, 3, 4, 47]) {
          for (const sid of rec.sp || []) {
            const sp = M?.specs?.[sid];
            if (!sp || (AT_ALIAS[sp.at] || sp.at) !== k || STATIC_TYPES.has(sp.t)) continue;
            for (const u of picked) {
              sim.selection = [u];
              runSpec({spec: sp, sid, owner: caster, src: 'skill:' + rec.id, name: rec.n, skill: rec},
                Object.assign({}, ctx, {attacker: caster, defender: u, target: u, skill: rec,
                                        depth: (ctx.depth || 0) + 1}));
            }
          }
        }
        sim.selection = null;
        log(`${caster.name} 发动「${rec.n}」，选中 ${picked.length} 名目标：${picked.map(u => u.name).join('、')}`);
        return;
      }
      const linkedProp = ctx.prop || (ctx.object?.kind ? ctx.object : null) ||
        (ctx.target?.kind ? ctx.target : null);
      castSkill(caster, rec, grid.at(target.x, target.y), {sub: true, free: true,
        object: ctx.object || sim.objectOrigin || null, prop: linkedProp,
        depth: (ctx.depth || 0) + 1, label: inst.name});
    }

    /* ---------- auras & environment ---------- */
    const envAuras = [];
    // AURA params: 范围类型 | 范围大小高低 (packed: up<<24 | down<<16 | min<<8 | max) | 单位阵营 | BUFF ID.
    // Which side receives it is the speciality's target_type (1/5 友军, 2 敌方, 3 自身, 4 全体).
    function auraRange(spec, owner, u) {
      const packed = spec.p[1] >>> 0;
      const max = packed & 0xFF, min = (packed >>> 8) & 0xFF;
      const up = (packed >>> 24) & 0xFF, down = (packed >>> 16) & 0xFF;
      if (!owner || spec.p[0] === 7 || max >= 50) return true;
      const d = manhattan(owner, u);
      if (d < min || d > max) return false;
      const dh = (grid.at(u.x, u.y)?.h ?? 0) - (grid.at(owner.x, owner.y)?.h ?? 0);
      return (dh <= 0 || dh <= up) && (dh >= 0 || -dh <= down);
    }
    function auraSide(spec, owner, u) {
      if (!owner) return true;
      switch (spec.tt) {
        case 2: return u.side !== owner.side;
        case 3: return u === owner;
        case 4: return true;
        default: return u.side === owner.side;
      }
    }
    // Share rules are derived from each unit's own specialities. Cache by the
    // unit version (bumped whenever a buff is added / removed) so the costly
    // spec scan does not run on every aura refresh / damage event.
    function shareRuleOf(u) {
      if (u._shareVer === u.ver && u._shareRule !== undefined) return u._shareRule;
      let rule = null;
      for (const inst of unitSpecs(u)) {
        const s = inst.spec;
        if (s.t !== 'SHARE_DAMAGE') continue;
        const bid = s.p[0];
        rule = {bid, pct: clamp(100 - (s.p[1] || 0), 0, 100),
                capAttr: attrName(s.p[2]), capPct: s.p[3] || 0,
                name: (M?.buffs?.[bid] || {}).n || `状态 #${bid}`};
        break;
      }
      u._shareRule = rule; u._shareVer = u.ver;
      return rule;
    }
    function refreshAuras() {
      if (!M || sim.auraBusy) return;
      sim.auraBusy = true;
      try {
      // Diff-based: compute every receiver's wanted aura grants, and touch a
      // unit ONLY when its set actually changed. The old version stripped and
      // re-added every aura buff on every call (movement, deaths, casts …),
      // bumping every unit's version twice and throwing away all per-unit
      // caches and live active_param state each time. Sources still exclude
      // aura-granted rows, exactly as when aura buffs were stripped first.
      const sources = [];
      for (const u of units) if (u.alive) for (const inst of unitSpecs(u))
        if (inst.spec.t === 'AURA' && !inst.buff?.aura) sources.push(inst);
      sources.push(...envAuras);
      const want = new Map();
      for (const inst of sources) {
        const s = inst.spec, o = inst.owner;
        for (const u of units) {
          if (!u.alive || !auraSide(s, o, u) || !auraRange(s, o, u)) continue;
          // Environment auras (weather) evaluate their condition on the receiver.
          const ci = o ? inst : Object.assign({}, inst, {owner: u});
          if (s.c && !cond(ci, {target: u})) continue;
          let list = want.get(u);
          if (!list) want.set(u, list = []);
          list.push([s.p[3], o || u]);
        }
        bump(cov.executed, 'AURA');
      }
      // Tile-owned AURA specialities (field_status.speciality_ids). The client
      // declares 烟雾 #14 → #10242「烟雾-隐身-光环」(at=1, tt=4, p=[1,0,0,647],
      // 「待在里面获得[隐身]」). p[1]=0 → radius 0, so ONLY the unit standing
      // on that tile receives buff 647「隐身」. Before this, runFieldSpecs()
      // called AURA() which is an intentional no-op and refreshAuras() only
      // collected UNIT passives — so 烟雾 never granted 隐身 at all.
      for (const [fk, f] of sim.fieldStatus) {
        const d = fieldDef(f.id);
        if (!d?.sp?.length) continue;
        const cell = grid.at(f.x, f.y);
        if (!cell || (cell.status || NORMAL_FIELD) !== f.id) continue;
        const owner = {x: f.x, y: f.y, side: null, uid: 'field:' + fk, name: d.name};
        for (const sid of d.sp) {
          const q = M?.specs?.[sid];
          if (!q || q.t !== 'AURA' || (AT_ALIAS[q.at] || q.at) !== 1) continue;
          const bid = q.p?.[3];
          if (!bid) continue;
          for (const u of units) {
            if (!u.alive || fieldImmune(u, f.id)) continue;
            if (!auraSide(q, owner, u) || !auraRange(q, cell, u)) continue;
            let list = want.get(u);
            if (!list) want.set(u, list = []);
            list.push([bid, u]);
          }
          bump(cov.executed, 'FIELD_AURA');
        }
      }
      for (const u of units) {
        const list = want.get(u) || [];
        const sig = list.map(([id, src]) => id + '@' + (src?.uid || '')).join(',');
        const cur = u.buffs.filter(b => b.aura);
        if (sig === u._auraSig && cur.length === u._auraLen) continue;
        if (cur.length) { u.buffs = u.buffs.filter(b => !b.aura); touch(u); }
        if (u.alive) for (const [id, src] of list) addBuff(u, id, 0, 1, src, {aura: true, quiet: true});
        u._auraSig = sig;
        u._auraLen = u.buffs.filter(b => b.aura).length;
      }
      } finally { sim.auraBusy = false; }
    }

    /* ---------- knockback ---------- */
    const noReactive = u => unitSpecs(u).some(i => i.spec.t === 'FORBIDDEN_REACTIVE' && cond(i, {}));
    function immuneToKnockback(t) {
      const bit = effectBit('Knockback') || effectBit('KnockBack') || effectBit('Repel');
      if (!bit) return false;
      return unitSpecs(t).some(i => i.spec.t === 'IMMUNE' && (i.spec.p[1] & (1 << (bit - 1))) && cond(i, {}));
    }
    function knockback(src, from, t, cells, inst, noImpact = false) {
      const dx = t.x - from.x, dy = t.y - from.y;
      let dir, dist = cells;
      if (Math.abs(dx) === Math.abs(dy) && dx !== 0) { dir = [Math.sign(dx), Math.sign(dy)]; dist = Math.ceil(cells / 2); }
      else dir = Math.abs(dx) >= Math.abs(dy) ? [Math.sign(dx) || 1, 0] : [0, Math.sign(dy) || 1];
      const occ = () => new Map(units.filter(u => u.alive && u !== t).map(u => [key(u.x, u.y), u]));
      const impact = (u, label) => {
        const v = maxHpOf(u) * K.KnockbackImpactDamage / 100 * Math.max(0, 1 + attr(u, 'AMBIENT_DAMAGE_MODIFY') / 100)
          * Math.max(0, 1 + attr(u, 'KNOCKBACK_BEDAMAGE_FACTOR') / 100);
        const r = dealDamage(src, u, Math.round(v), {pierce: true});
        log(`${u.name} 受到 ${r.dealt} 撞击伤害（${label}）`);
      };
      // 11495「若击退后造成碰撞则使碰撞双方[晕眩]」: KNOCKBACK_ADD_BUFF
      // #12418 lives on the SKILL, not on a unit speciality, and it applies to
      // BOTH the knocked-back unit and the blocker it crashed into.
      const impactBuffs = u => {
        const seen = new Set();
        const apply = (k) => {
          if (seen.has(k.sid)) return;
          seen.add(k.sid);
          const p = k.spec.p;
          addBuff(u, p[0], p[1], 1, src);
          log(`碰撞效果 KNOCKBACK_ADD_BUFF：${u.name} 获得[${M?.buffs?.[p[0]]?.n || '状态 #' + p[0]}] ${p[1]} 回合（特技 #${k.sid}「${k.spec.n}」）`);
        };
        for (const k of unitSpecs(src)) if (k.spec.t === 'KNOCKBACK_ADD_BUFF'
          && cond(k, {attacker: src, defender: t})) apply(k);
        for (const sid of inst?.skill?.sp || []) {
          const sp = M?.specs?.[sid];
          if (sp?.t !== 'KNOCKBACK_ADD_BUFF') continue;
          const si = {spec: sp, sid, owner: src, src: 'skill:' + inst.skill.id,
                      name: sp.n, skill: inst.skill};
          if (cond(si, {attacker: src, defender: t})) apply(si);
        }
      };
      const startPos = {x: t.x, y: t.y};
      const dirName = dir[0] && dir[1] ? `斜向(${dir[0] > 0 ? '东' : '西'}${dir[1] > 0 ? '南' : '北'})`
        : dir[0] ? (dir[0] > 0 ? '东' : '西') : (dir[1] > 0 ? '南' : '北');
      let moved = 0, stop = dist >= 1 ? '已走完声明格数' : '距离为 0', slid = 0;
      // Client 冰冻地块 declares speciality #226 NO_KNOCKBACK_DISTANCE on the
      // TILE (field_status.sp); a unit may additionally carry the same spec.
      const iceSlideSpec = (fieldDef(3)?.sp || []).some(sid =>
        M?.specs?.[sid]?.t === 'NO_KNOCKBACK_DISTANCE');
      const noKnockField = u => iceSlideSpec ||
        unitSpecs(u).some(i => i.spec.t === 'NO_KNOCKBACK_DISTANCE');
      const finishKnock = (diagonal) => {
        const rec = {who: t.uid, name: t.name, declared: cells, computed: dist,
          direction: dirName, diagonal: !!diagonal, effective: dist, moved,
          from: startPos, to: {x: t.x, y: t.y}, stop, noImpact: !!noImpact,
          spec: inst.sid || 0, skill: inst.name || ''};
        (sim.knockbacks || (sim.knockbacks = [])).push(rec);
        log(`击退明细：${tagOf(t)} 声明 ${cells} 格 → 结算距离 ${dist} 格` +
          (diagonal ? '（斜向，手册规则距离减半）' : '') +
          ` → 方向${dirName} → 实际移动 ${moved} 格 (${startPos.x},${startPos.y})→(${t.x},${t.y})；${stop}` +
          (noImpact ? '（回弹拉拽：不触发撞击）' : '') + `（${inst.name}）`);
      };
      for (let i = 0; i < dist && t.alive && slid < 12;) {
        const cur = grid.at(t.x, t.y);
        // 冰冻地块 (field 3): 「被击退时会一直退到冰面边缘，再被正常击退」.
        // Sliding across ice does NOT consume a declared knockback step.
        const slide = (cur?.status || 1) === 3 && noKnockField(t) && !fieldImmune(t, 3);
        if (slide) slid++;
        const n = grid.at(t.x + dir[0], t.y + dir[1]);
        const blocker = occ().get(key(t.x + dir[0], t.y + dir[1]));
        if (n && n.pit) {
          stop = `第 ${i + 1} 格是「${n.name}」深坑，坠落击败`;
          t.x = n.x; t.y = n.y; moved++;
          log(`${t.name} 被击落「${n.name}」`);
          finishKnock(false);
          kill(src, t, {});
          return;
        }
        if (!n || !n.walk || blocker || n.h - cur.h > 2) {
          stop = blocker ? `第 ${i + 1} 格被 ${tagOf(blocker)} 占据，撞击后停止`
            : !n ? `第 ${i + 1} 格是地图边界`
            : !n.walk ? `第 ${i + 1} 格是不可通行的地形「${n.name}」`
            : `第 ${i + 1} 格高差 +${n.h - cur.h} 超过跳跃上限 2`;
          if (!noImpact) {
            impact(t, '碰撞');
            impactBuffs(t);
            if (blocker) {
              impact(blocker, '被撞');
              impactBuffs(blocker);
              fire(61, blocker, {attacker: src, defender: blocker, target: t});
            }
          }
          break;
        }
        const drop = cur.h - n.h;
        t.x = n.x; t.y = n.y; moved++; sim.epoch++;
        if (!slide) i++;   // ice slide is free; a normal tile costs 1 step
        if (drop > 2) {
          // Client JSON `sparam.dont_fall` (「击退2格-反向自己（即后退，
          // 无碰撞无坠落）」): a SELF knock-back may still step down a ledge,
          // but must not take fall damage or stop there.
          if (inst?.spec?.sj?.dont_fall) continue;
          const v = maxHpOf(t) * K.FallDamage / 100 * Math.max(1, Math.floor(drop / Math.max(1, K.FallDamageHeight)))
            * Math.max(0, 1 + attr(t, 'AMBIENT_DAMAGE_MODIFY') / 100);
          const r = dealDamage(src, t, Math.round(v), {pierce: true});
          log(`${t.name} 坠落 ${drop} 层受到 ${r.dealt} 伤害`);
          stop = `第 ${moved} 格下落 ${drop} 层，坠落伤害后停止`;
          break;
        }
      }
      // Explicit numeric audit trail. 贯日强击 declares 「击退4格」 but a
      // diagonal direction halves it (手册：对角线距离减半) and the first
      // blocked tile stops the rest — that is why 科尔 only moved 1 tile.
      finishKnock(!!(dir[0] && dir[1]));
      fire(23, src, {attacker: src, defender: t, target: t});
      if (t.alive) fire(24, t, {attacker: src, defender: t, target: src});
      refreshAuras();
    }

    /* ---------- geometry ---------- */
    // ALL client cast-range extensions for ONE skill, with their origin rows.
    // `Logic_AI_AIMachine` declares FindRangeBlocks / AddRange /
    // ReApplySkillRanges / specsSkillRange / EXTEND_CAST_RANGE /
    // extend_cast_range_buffs, so range is the sum of:
    //   • SKILL_RANGE specialities on the unit (passives + buffs), each scaled
    //     by its buff STACKS (#12417 后备隐藏脂肪 +1/层,
    //     #14680/#14681 七手八脚的分工合作 +1, #14726 不屈不挠 +2),
    //   • EXTEND_CAST_RANGE specialities (client extend_cast_range_buffs),
    //   • SKILL_RANGE specialities declared on the SKILL itself.
    // The same rows feed the AI (rangeMods) and the visible character state
    // (skillStateOf), so they can never disagree.
    function castRangeRows(u, s, counter = false, ctx = {}) {
      const rows = [];
      // A self-only / zero-range skill has no cast range to extend; the
      // client's specsSkillRange / checkMeleeRange only touch skills with a
      // real range block. Without this 灵光一闪的傲人智慧 (rmax 0) would
      // misleadingly show 「射程 0–10」.
      if (!s || (s.rmax || 0) <= 0) return rows;
      // skill.skill_range_constant = the client forbids ANY range modifier.
      if (s.rc) return rows;
      const c = Object.assign({attacker: u, skill: s, defender: ctx.defender, target: ctx.target}, ctx);
      const applies = inst => cond(inst, c) && skillCondOk(inst, s, c);
      const push = (inst, sp, min, max, source) => {
        if (!min && !max) return;
        rows.push({spec: Number(inst.sid), name: inst.name || sp.n || '', type: sp.t,
                   min, max, stacks: inst.buff?.stacks || 1,
                   source, buff: inst.buff?.id || null,
                   condition: sp.c || ''});
      };
      for (const inst of unitSpecs(u)) {
        const sp = inst.spec;
        const at = AT_ALIAS[sp.at] || sp.at;
        if (sp.t === 'SKILL_RANGE') {
          if (at === 31 && !counter) continue;
          if (at !== 1 && at !== 31) continue;
          if (!applies(inst)) continue;
          const stacks = inst.buff?.stacks || 1;
          push(inst, sp, (sp.p[0] || 0) * stacks, (sp.p[1] || 0) * stacks, inst.src);
        } else if (sp.t === 'EXTEND_CAST_RANGE' && (at === 1 || at === 2 || at === 31)) {
          if (!applies(inst)) continue;
          const stacks = inst.buff?.stacks || 1;
          const v = (Number(sp.p[0]) || 0) * stacks;
          push(inst, sp, 0, v, 'EXTEND_CAST_RANGE');
        }
      }
      for (const sid of s?.sp || []) {
        const sp = M?.specs?.[sid];
        if (!sp || sp.t !== 'SKILL_RANGE') continue;
        const inst = {spec: sp, sid, owner: u, src: 'skill:' + s.id, name: sp.n};
        if (!applies(inst)) continue;
        push(inst, sp, sp.p[0] || 0, sp.p[1] || 0, 'skill');
      }
      return rows;
    }
    function rangeMods(u, counter, skill) {
      let mn = 0, mx = 0;
      for (const r of castRangeRows(u, skill, counter)) { mn += r.min; mx += r.max; }
      return [mn, mx];
    }
    // Visible skill state: effective range, knockback distance and damage
    // bonus, each with a per-client-speciality breakdown. Used by the
    // character panel and by the replay step so 「加射程」is inspectable.
    function skillStateOf(u, s, ctx = {}) {
      if (!u || !s) return null;
      const c = Object.assign({attacker: u, skill: s, defender: u, target: u}, ctx);
      // Same activation context as rangeMods() so the displayed numbers equal
      // the ones the AI actually uses when choosing a cast block.
      const rows = castRangeRows(u, s, false, {attacker: u, skill: s});
      const min = Math.max(0, (s.rmin || 0) + rows.reduce((n, r) => n + r.min, 0));
      const max = Math.max(min, Math.max(s.rmax || 0, s.aim === 'enemy' ? 1 : 0)
        + rows.reduce((n, r) => n + r.max, 0));
      const kbSpecs = [];
      let kbBase = 0;
      for (const sid of s.sp || []) {
        const sp = M?.specs?.[sid];
        if (sp?.t !== 'KNOCKBACK') continue;
        kbBase = Number(sp.p[0]) || 0;
        kbSpecs.push({spec: Number(sid), name: sp.n, value: kbBase, source: 'skill'});
      }
      const kbRows = [];
      for (const inst of unitSpecs(u)) {
        const sp = inst.spec;
        if (sp.t !== 'MODIFY_ATTRIBUTE' || attrName(sp.p[0]) !== 'KNOCKBACK_DISTANCE') continue;
        if (!cond(inst, c)) continue;
        const stacks = inst.buff?.stacks || 1;
        kbRows.push({spec: Number(inst.sid), name: inst.name, buff: inst.buff?.id || null,
                     stacks, value: Number(sp.p[1] || 0) * stacks, source: inst.src});
      }
      const kbBonus = kbRows.reduce((n, r) => n + r.value, 0);
      const dmgRows = [];
      for (const inst of unitSpecs(u)) {
        const sp = inst.spec;
        if (sp.t !== 'MODIFY_ATTRIBUTE' || attrName(sp.p[0]) !== 'DAMAGE') continue;
        if (!cond(inst, c)) continue;
        const stacks = inst.buff?.stacks || 1;
        const v = (Number(sp.p[2] || 0) + Number(sp.p[1] || 0)) * stacks;
        if (!v) continue;
        dmgRows.push({spec: Number(inst.sid), name: inst.name, buff: inst.buff?.id || null,
                      stacks, value: v, source: inst.src});
      }
      return {id: Number(s.id), name: s.n, shape: castShape(s),
              baseMin: s.rmin || 0, baseMax: s.rmax || 0, min, max,
              rangeRows: rows, rangeBonus: rows.reduce((n, r) => n + r.max, 0),
              knockbackBase: kbBase, knockbackBonus: kbBonus,
              knockbackTotal: u.flags?.noKnockDistance ? 0 : Math.max(0, kbBase + kbBonus),
              knockbackRows: kbRows, knockbackSpecs: kbSpecs,
              damageBonus: dmgRows.reduce((n, r) => n + r.value, 0), damageRows: dmgRows};
    }
    // Explain where a skill's dynamic numbers come from: MODIFY_ATTRIBUTE /
    // SKILL_RANGE rows on the caster's buffs whose activation condition names
    // this skill. 11495「贯穿天际的必胜流星」 gets +5% damage (#14674), +1
    // range (#12417) and +1 knockback (#12416) per [后备隐藏脂肪] layer.
    function skillScalingOf(u, s) {
      const all = unitSpecs(u);
      // Only report the buffs that the CLIENT binds to THIS skill (their
      // activation Lua names `skill.template.id`), plus the other stackable
      // rows of those same buffs. Generic passives are already shown in the
      // character panel; logging them on every sub-cast only drowns the log.
      const bound = new Set();
      for (const inst of all) {
        const c = inst.spec.c || '';
        if (!inst.buff || !/skill\.template\.id/.test(c)) continue;
        if (cond(inst, {attacker: u, skill: s})) bound.add(inst.buff.id);
      }
      if (!bound.size) return [];
      const rows = [];
      for (const inst of all) {
        const sp = inst.spec;
        if (!inst.buff || !bound.has(inst.buff.id)) continue;
        if (sp.t !== 'MODIFY_ATTRIBUTE' && sp.t !== 'SKILL_RANGE') continue;
        if ((AT_ALIAS[sp.at] || sp.at) !== 1) continue;
        if (!cond(inst, {attacker: u, skill: s})) continue;
        const stacks = inst.buff.stacks || 1;
        const buff = inst.buff.def?.n || inst.name || '';
        if (sp.t === 'SKILL_RANGE') rows.push({kind: '射程', attr: 'SKILL_RANGE',
          per: sp.p[1] || 0, stacks, value: (sp.p[1] || 0) * stacks, buff, spec: inst.sid});
        else rows.push({kind: '属性', attr: attrName(sp.p[0]) || `#${sp.p[0]}`,
          per: (sp.p[2] || 0) || (sp.p[1] || 0), stacks,
          value: ((sp.p[2] || 0) + (sp.p[1] || 0)) * stacks, buff, spec: inst.sid});
      }
      return rows;
    }
    // Client speciality type 233 「AI判定用的AOE范围(配在主技能)」:
    // 「替代原来技能的AOE范围，同时会屏蔽后续技能的范围(只对AI生效)」.
    // 审判诸罪之光 #15386 declares head AOE 257 (1*6, the middle column that
    // gets the 加伤标记) but DISPLAY_AOE #27305 → AOE 256 (3*6, the real
    // sweep); its idskill_follow #15382 owns the 70% damage. Both the AI and
    // the cast must use the 3*6 UNION, and the follow-up's own AOE is masked
    // so the blast is not counted twice. Previously DISPLAY_AOE was a no-op,
    // so the AI only ever saw a single east-facing 1*6 line.
    const displayAreaCache = new Map();
    function displayAreaOf(s) {
      if (!s) return null;
      if (displayAreaCache.has(s.id)) return displayAreaCache.get(s.id);
      let out = null;
      for (const sid of s.sp || []) {
        const q = M?.specs?.[sid];
        if (q?.t === 'DISPLAY_AOE' && M?.aoe?.[q.p?.[0]]) {
          out = {type: 'aoe', id: Number(q.p[0])};
          break;
        }
      }
      displayAreaCache.set(s.id, out);
      return out;
    }
    function targetCells(origin, s, u, counter, mods) {
      const out = [];
      if (s.aim === 'direction') {
        // A direction skill with range_min/max = 0 (审判诸罪之光 #15386)
        // targets a DIRECTION, not a block. Enumerate ALL four sweeps from
        // the caster's own tile, each carrying `dir` for areaCells(). The
        // old early return collapsed these to one origin cell with no dir,
        // so areaCells() always fell back to "east" and the AI never found
        // an enemy in the blast.
        const zero = (s.rmax || 0) <= 0;
        for (const [dx, dy] of DIRS) {
          const c = zero ? grid.at(origin.x, origin.y)
                         : grid.at(origin.x + dx, origin.y + dy);
          if (c) out.push(Object.assign({dir: [dx, dy]}, c));
        }
        return out;
      }
      if (s.aim === 'self' || (s.rmax <= 0 && s.aim !== 'enemy')) return [grid.at(origin.x, origin.y)];
      const [mn, mx] = mods || (u ? rangeMods(u, counter, s) : [0, 0]);
      const lo = Math.max(0, s.rmin + mn), hi = Math.max(lo, Math.max(s.rmax, s.aim === 'enemy' ? 1 : 0) + mx);
      const shape = castShape(s);
      // 「全部 / 全部单位 / 全部有东西的地块」 target the whole field, not a ring.
      const offsets = WHOLE_FIELD_SHAPES.has(shape) ? null : castRangeCells(s, lo, hi);
      const cells = offsets
        ? offsets.map(([dx, dy]) => grid.at(origin.x + dx, origin.y + dy))
        : [...grid.cells.values()];
      for (const c of cells) {
        if (!c) continue;
        const up = c.h - origin.h;
        if (s.up && up > s.up) continue;
        if (s.dn && -up > s.dn) continue;
        out.push(c);
      }
      return out;
    }
    function areaCells(origin, target, s, areaOverride) {
      const a = areaOverride || s.area || {type: 'single'};
      const shapeAt = (cx, cy, sel, mn, mx, w, dir) => {
        const out = [];
        if (sel === 'all' || sel === 'all_unit' || sel === 'all_update_block') return [...grid.cells.values()];
        if (sel === 'direction' || sel === 'rect' || sel === 'side_line' || sel === 'horizontal_line') {
          const [dx, dy] = dir;
          const half = Math.floor(Math.max(1, w || 1) / 2);
          for (let step = Math.max(sel === 'direction' ? 1 : 0, mn); step <= Math.max(mx, 1); step++) {
            for (let side = -half; side <= half; side++) {
              const c = grid.at(cx + dx * step + dy * side, cy + dy * step + dx * side);
              if (c) out.push(c);
            }
          }
          return out;
        }
        for (let ddx = -mx; ddx <= mx; ddx++) for (let ddy = -mx; ddy <= mx; ddy++) {
          const d = Math.abs(ddx) + Math.abs(ddy);
          if (d < mn || d > mx) continue;
          if (sel === 'cross_line' && ddx !== 0 && ddy !== 0) continue;
          const c = grid.at(cx + ddx, cy + ddy);
          if (c) out.push(c);
        }
        return out;
      };
      const dir = target.dir || (() => { const d = dirTo(origin, target); return d[0] || d[1] ? d : [1, 0]; })();
      if (a.type === 'aoe') {
        const p = M?.aoe?.[a.id];
        if (!p) return [target];
        const lineFromCaster = ['direction', 'rect', 'side_line', 'horizontal_line', 'sector'].includes(p.sel);
        const cx = lineFromCaster ? origin.x : target.x, cy = lineFromCaster ? origin.y : target.y;
        const out = shapeAt(cx, cy, p.sel === 'sector' ? 'direction' : p.sel, p.min, p.max, p.w || (p.sel === 'rect' ? 3 : 1), dir);
        if (!out.some(c => c.x === target.x && c.y === target.y) && !lineFromCaster) out.push(target);
        return p.h && p.h < 50 ? out.filter(c => Math.abs(c.h - target.h) <= p.h) : out;
      }
      if (a.type === 'radius') return shapeAt(target.x, target.y, 'diamond', 0, a.r, 1, dir);
      if (a.type === 'rect') return shapeAt(origin.x, origin.y, 'rect', 1, a.len, a.wide || 3, dir);
      return [target];
    }
    // 平射 (attack_method 2) is stopped by enemies on the straight trajectory.
    // Client IGNORE_ATTACK_BLOCK (神射 #3474 at=1, 「反击时无视目标阻挡」
    // #21259 at=31 on 神秘反击 / 逆转反击) lets specific flat shots ignore
    // that blocker. It is a declarative skill row, so it is read from the
    // skill's own specialities instead of the generic fire() dispatcher.
    const ignoresBlock = (s, attacker) => {
      if ((s.sp || []).some(sid => M?.specs?.[sid]?.t === 'IGNORE_ATTACK_BLOCK')) return true;
      if (!attacker?.buffs) return false;
      return attacker.buffs.some(b => buffOn(b) && (b.def.sp || [])
        .some(sid => M?.specs?.[sid]?.t === 'IGNORE_ATTACK_BLOCK'));
    };
    function blocked(from, to, s, side) {
      if (s.am !== 2) return false;
      if (ignoresBlock(s, units.find(u => u.alive && u.x === from.x && u.y === from.y))) return false;
      const dx = to.x - from.x, dy = to.y - from.y, n = Math.max(Math.abs(dx), Math.abs(dy));
      for (let i = 1; i < n; i++) {
        const x = Math.round(from.x + dx * i / n), y = Math.round(from.y + dy * i / n);
        if (units.some(u => u.alive && u.side !== side && u.x === x && u.y === y)) return true;
      }
      return false;
    }

    /* ---------- skill use ---------- */
    const tpCost = (u, s) => {
      let c = s.tp || 0;
      let free = false;
      for (const inst of unitSpecs(u)) {
        if (inst.spec.t !== 'MULTI_CONSUME_TP') continue;
        if (!cond(inst, {skill: s, attacker: u}) || !skillCondOk(inst, s, {skill: s, attacker: u})) continue;
        // Client MULTI_CONSUME_TP: p[0] = 0 → p[1] is an additive delta
        // (33 rows, e.g. 耗能降低1 = [0,-1]); p[0] = -2 → 「自身技能无能耗」
        // (#20540 冰雪暴附属被动-减能耗, #27209 金狮形态): the cost is zero.
        if (Number(inst.spec.p[0]) === -2) free = true;
        else c += Number(inst.spec.p[1]) || 0;
      }
      return free ? 0 : Math.max(0, c);
    };
    // Client limit_count plus the per-unit delta granted by SKILL_COUNT.
    // A `lc` of 0 means unlimited, and a negative delta must never turn an
    // unlimited skill into a gated one.
    const skillLimitOf = (u, s) => (Number(s.lc) || 0) + (u?.skillLimit?.[s.id] || 0);
    function usable(u, s) {
      if ((u.cd[s.id] || 0) > 0) return false;
      if (tpCost(u, s) > u.tp) return false;
      // Client buff 2570「缴械」: 「携带者不可释放[普攻]和[职业技能]，只可以
      // 使用装备技能」. Its only speciality is DISARM (at=1), which used to
      // just set an unread `flags.disarm`, so a disarmed unit kept casting.
      // Distinguish it from the OTHER Seal buffs (73「主动技」/3662「窒息」:
      // 「无法使用普攻以外的主动技能」, which explicitly ALLOW the 普攻).
      if (u.buffs.some(b => buffOn(b) && (b.def.sp || []).some(id => M?.specs?.[id]?.t === 'DISARM'))) {
        // 装备技能 are the only skills the client still permits while 缴械'd.
        return (s.tags || []).includes('Equipment');
      }
      if ((hasEffect(u, 'Seal') || hasEffect(u, 'SpecialSeal')) && !s.isNormal) return false;
      if (s.lct && (u.uses[s.id + ':t'] || 0) >= s.lct) return false;
      if (skillLimitOf(u, s) > 0 && (u.uses[s.id] || 0) >= skillLimitOf(u, s)) return false;
      return true;
    }
    // skill.target_type: 2 敌方 / 3 自身范围内敌方（治疗则己方）/ 4 己方 / 5 地面范围内敌方 / 6 任意.
    // A「自身」-targeted skill with an AOE therefore still hits enemies around the caster.
    // Client 「瞬移至目标角色或物品周围」 support skills (落花之舞 #21016)
    // are stored as aim=enemy, but their SHADOW_STEP teleport anchor may be
    // ANY unit — enemy, ally or the caster — or an item. The description,
    // not the aim column, declares this wider target side.
    const anyUnitAim = s => !!s && (skillPlan(s)?.anyUnit ||
      ((s.sp || []).some(sid => M?.specs?.[sid]?.t === 'SHADOW_STEP' ||
                              M?.specs?.[sid]?.t === 'JUMP_MOVE') &&
       /目标角色或物品|任一(角色|单位|目标)|敌军或友军|友军或敌军/.test(String(s.desc || ''))));
    const affects = (s, caster, u) => {
      if (anyUnitAim(s)) return true;
      // Damage on an idskill_follow segment decides the side (陷阵·锐意承锋
      // 「对自身范围3格内所有敌人造成100%范围伤害」), not the head's
      // self-buff rows that utilitySide() would otherwise read.
      if (followDamage(s)) return u.side !== caster.side;
      // A client AOE speciality whose `target_type` is 2 (对敌) is
      // authoritative even when the SKILL says aim=self / aim=ally.
      // 15935「飞弹礼花-后续」(协同响应 50% 穿透伤害) is aim=self but its
      // AOE #641 tt=2 therefore hits ENEMIES in the 3-tile radius; treating
      // it as a friendly buff made the whole 协同响应 deal no damage.
      const aoeEnemy = (s.sp || []).some(x => {
        const sp = M?.specs?.[x];
        return sp?.t === 'AOE' && sp.tt === 2;
      });
      if (aoeEnemy && s.dt === 4) return u.side !== caster.side;
      if (s.dt === 3 || s.ttp === 4 || s.aim === 'self' || s.aim === 'ally')
        return u.side === caster.side;
      // Status-class 「号令」skills declare their enemy side through the AOE
      // speciality's own target_type=2 (全装甲集火号令！→ AOE #1984 tt=2),
      // NOT through skill.target_type (a 3 there means 自身范围内, used by
      // 迎风持盾 / 灵光一闪的傲人智慧 which buff FRIENDLIES).
      if (aoeEnemy) return u.side !== caster.side;
      if (isUtility(s)) {
        return utilitySide(s, M) === 'enemy' ? u.side !== caster.side : u.side === caster.side;
      }
      if (!s.legacy && [2, 3, 5, 6].includes(s.ttp)) return u.side !== caster.side;
      if (s.aim === 'ally') return u.side === caster.side;
      if (s.aim === 'self') return u === caster;
      if (s.dt === 5 && s.aim !== 'enemy') return u.side === caster.side;
      return u.side !== caster.side;
    };

    // Executes one use of `s` by `caster` aimed at cell `tcell`; returns hits.
    // Event order follows the client active_time enum: 33 使用技能前 / 54 被使用技能前 →
    // 2 攻击前 → (per target) 15 被攻击前 → 45/46 背击 → 闪避 19/20 → 先制 → 16 格挡前 →
    // 13/14 格挡 → 伤害 → 5 命中 / 6 被命中 → 7 伤害 / 8 被伤害 → 53/48 每次伤害 →
    // 9/10 暴击 → 4 被攻击后 → 3 攻击后 / 47 使用技能后 → 反击 31/32/55.
    const dmg0 = (caster, s) => Math.max(0, Math.round(attr(caster, 'PHYSIC_ATTACK') * (s?.df || s?.factor || 0) / 100));
    // Snapshot everything a skill will consume BEFORE the at=3 specs drain TP.
    function captureConsumption(caster, cons) {
      if (!cons) return null;
      const tp = cons.tp ? Math.max(0, caster.tp) : 0;
      const buff = cons.b ? caster.buffs.find(x => x.id === cons.b) : null;
      const stacks = buff ? (cons.n ? Math.min(cons.n, buff.stacks) : buff.stacks) : 0;
      return {tp, stacks, buff: buff || null, n: cons.n || 0, count: tp + stacks,
              buffName: buff?.def?.n || ''};
    }
    function applyConsumption(caster, cons, cap) {
      if (!cap) return 0;
      // Only a description-declared consumption (or one feeding a bonus
      // segment) mutates state; spec-driven drains already run through the
      // normal at=3 effect pipeline with their Lua conditions.
      if (!cons?.apply) return cap.count;
      if (cons.tp) caster.tp = 0;
      if (cap.buff && cap.stacks > 0) {
        if (cap.n && cap.buff.stacks > cap.stacks) { cap.buff.stacks -= cap.stacks; touch(caster); }
        else removeBuff(caster, cap.buff, '消耗');
      }
      const name = cap.buff?.def?.n || (cap.buff ? `状态 #${cap.buff.id}` : '状态');
      if (cap.count) log(`${caster.name} 消耗 ${cap.tp} 点能量与 ${cap.stacks} 层「${name}」，合计 ${cap.count} 层`);
      bump(cov.executed, 'SPECIAL_SKILL_CONSUME');
      return cap.count;
    }
    // Settle an additional damage segment ("追加每层 40% 物理伤害，
    // 通过此效果造成的伤害提高 60%") as its own damage event, with its own
    // crit roll, shields, death check and calculation panel.
    // Generic 〈阵营〉额外[协同响应] resolution, decoded from the client skill
    // description: faction unit_tag, radius around EACH responder, factor of
    // (物攻值 + 魔攻值) as piercing damage. `M.unitTags` maps tag id → name.
    // Full-field [协同响应] broadcast. Only specialities whose own client Lua
    // predicate names a Chain tag are eligible — a blanket fire(3/4) would
    // also set off unrelated 再行动 / 攻击后 effects (CombatDecision(1,…)).
    function broadcastChainResponse(caster, s, opts) {
      const marker = {id: 0, n: '协同响应', tags: ['Chain', 'ChainTag1', 'ChainTag2'],
                      df: 0, dt: 5, sp: [], tp: 0, rmax: 99, rmin: 0};
      const CHAIN_PRED = /hasTag\(\s*["']Chain|ChainTag/;
      let fired = 0;
      for (const u of units) {
        if (!u.alive) continue;
        const c = {attacker: caster, defender: u, target: u, skill: marker,
                   coordinated: true, depth: (opts.depth || 0) + 1};
        for (const inst of unitSpecs(u).slice()) {
          const sp = inst.spec;
          if (![2, 3, 4, 43].includes(AT_ALIAS[sp.at] || sp.at)) continue;
          if (STATIC_TYPES.has(sp.t)) continue;
          if (!CHAIN_PRED.test(String(sp.c || '') + ' ' + String(sp.sap || ''))) continue;
          runSpec(inst, c);
          fired++;
        }
      }
      if (fired) {
        log(`协同号令「${s.n}」向全场广播 [协同响应]：${fired} 条客户端 Chain 谓词特技被触发`);
        bump(cov.executed, 'CHAIN_RESPONSE_BROADCAST');
      }
    }
    function hasUnitTag(u, tag) {
      if (tag === undefined || tag === null || tag === 0) return true;
      const wanted = Array.isArray(tag) ? tag.map(Number) : [Number(tag)];
      const tags = (u.tags || []).map(Number);
      return wanted.some(t => tags.includes(t) ||
        (t === 1 && (u.buffs || []).some(b => b.id === 856)));
    }
    function resolveCoordinatedResponse(caster, s, coord, hits, at) {
      const tag = Number(coord.tag) || 0;
      const responders = units.filter(u => u.alive && u.side === caster.side && hasUnitTag(u, tag));
      if (!responders.length) return;
      const radius = Number(coord.radius) || 3;
      const factor = Number(coord.factor) || 50;
      const pf = Object.assign({}, s, {df: factor, dt: 4, dmg: 0, dp: 0,
                                       pf: coord.mixed ? 100 : (s.pf || 100),
                                       sf: coord.mixed ? 100 : 0});
      let done = 0;
      for (const u of responders) {
        for (const t of units) {
          if (!t.alive || t.side === caster.side) continue;
          if (manhattan(u, t) > radius) continue;
          const c = at({attacker: u, defender: t, target: t});
          const sd = computeDamage(u, t, pf, c,
            {explain: true, hitsOverride: 1, segLabel: `协同响应 ${factor}%`});
          const before = t.hp;
          const rr = dealDamage(u, t, sd.amount, {kind: 'pierce', pierce: true, skill: s});
          hits.push({uid: t.uid, x: t.x, y: t.y, amount: rr.dealt, absorbed: rr.absorbed, before, after: t.hp,
            kind: 'pierce', skill: s.n, calc: sd.parts, formula: sd.formula, seg: `协同响应 ${factor}% 穿透伤害`,
            reborn: rr.reborn || null, rebornHp: rr.rebornHp || 0, zeroReason: rr.zeroReason || ''});
          log(`额外[协同响应]：${u.name}（${M?.unitTags?.[tag] || coord.faction}）→ ${t.name}，` +
              `自身 ${radius} 格内 ${factor}% 物攻+魔攻 穿透伤害 ${rr.dealt} 点`);
          done++;
        }
      }
      if (done) {
        log(`〈${M?.unitTags?.[tag] || coord.faction}〉额外[协同响应]结算：${responders.length} 名响应者 / ${done} 次命中 → ${responders.map(u => u.name).join('、')}`);
        bump(cov.executed, 'COORDINATED_RESPONSE');
        sim.coordinated = {skill: Number(s.id), faction: coord.faction, tag, responders: responders.map(u => u.uid)};
      }
    }
    function settleBonus(caster, s, plan, target, count, at, hits) {
      if (!plan?.bonus?.length || !count) return;
      if (!target || !target.alive) {
        // The client still settles the additional damage instance; with the
        // primary target already defeated it deals nothing, but the layer
        // conversion is part of the same skill and must stay in the log.
        log(`${caster.name} 的「${s.n}」追加 ${count} 层伤害（目标已击败，未造成伤害）`);
        return;
      }
      for (const [per, boost, dt] of plan.bonus) {
        const factor = per * count;
        const label = `追加 ${count} 层 × ${per}% = ${factor}%${boost ? `（增伤 ${boost}%）` : ''}`;
        const bs = Object.assign({}, s, {df: factor, dt: dt || s.dt, dmg: 0, dp: 0});
        const ctx = at({defender: target, target});
        const sd = computeDamage(caster, target, bs, ctx,
          {explain: true, hitsOverride: 1, extraBoost: boost, segLabel: label});
        const before = target.hp;
        const r = dealDamage(caster, target, sd.amount,
          {kind: sd.kind, pierce: sd.kind === 'pierce', skill: s});
        hits.push({uid: target.uid, x: target.x, y: target.y, amount: r.dealt, absorbed: r.absorbed, before, after: target.hp,
          crit: sd.crit, restraint: sd.restraint, height: sd.height, killed: !target.alive,
          kind: sd.kind, skill: s.n, calc: sd.parts, formula: sd.formula, seg: label, factor, boost,
          reborn: r.reborn || null, rebornHp: r.rebornHp || 0, zeroReason: r.zeroReason || ''});
        log(`${caster.name} 的「${s.n}」追加伤害结算：${label} → ${r.dealt} 点`);
        bump(cov.executed, 'ADDITIONAL_DAMAGE_BY_CONSUME');
      }
    }
    function castSkill(caster, s, tcell, opts = {}) {
      const hits = [];
      // Client SPECIAL_SKILL_CONSUME (active_time 1) is a CAST REQUIREMENT,
      // not a side effect: 「每消耗4层[蓄势]反复执行蛮勇转化」. A loop node
      // (阿尔曼大帝 21261/21296 CAST_SKILL → itself) must stop as soon as the
      // layers run out. Previously the engine only decremented layers inside
      // EFFECTS (never reached for at=1), so the chain recursed to the depth
      // cap and produced 240+ identical 「发动…蛮勇转化-结算」 log lines.
      // Charge the cost here, BEFORE any log or geometry side effect.
      const consumeSpecs = (s.sp || []).map(sid => M?.specs?.[sid]).filter(sp =>
        sp && sp.t === 'SPECIAL_SKILL_CONSUME' && (AT_ALIAS[sp.at] || sp.at) === 1);
      // Only the self-referencing loop nodes need the hard gate; other skills
      // carry the same spec as an optional cost and must keep their current
      // behaviour (e.g. 爆裂箭's 多重爆裂 conversion, 我即法则's 威慑).
      const isLoopNode = (s.sp || []).some(sid => {
        const sp = M?.specs?.[sid];
        return sp?.t === 'CAST_SKILL' && Number(sp.p?.[0]) === Number(s.id);
      });
      if (isLoopNode && consumeSpecs.length) {
        const planCons = skillPlan(s)?.cons;
        const paid = [];
        let ok = true;
        for (const sp of consumeSpecs) {
          const bid = Number(sp.p[2] || sp.p[0]);
          const need = Math.max(1, unpackCount(sp.p[3]) || 1);
          // Only a plan.cons that actually MUTATES state (cons.apply) is
          // owned by applyConsumption; a passive count-snapshot does not
          // spend the buff, so the loop node must charge it here.
          if (planCons?.apply && Number(planCons.b) === bid) continue;
          const b = caster.buffs?.find(x => Number(x.id) === bid);
          if (!b || b.stacks < need) { ok = false; break; }
          paid.push({b, need, sp});
        }
        if (!ok) return hits;
        for (const {b, need, sp} of paid) {
          b.stacks -= need;
          if (b.stacks <= 0) removeBuff(caster, b, '消耗');
          else touch(caster);
          log(`${caster.name} 消耗 ${need} 层「${b.def.n}」（${sp.n}）`);
          bump(cov.executed, 'SPECIAL_SKILL_CONSUME');
        }
      }
      // Client `JUMP_MOVE` / `jump_move_steps` / `SHADOW_STEP` / `TELEPORT`:
      // a ground-targeted jump skill relocates the CASTER onto the selected
      // empty block. CHARGE instead dashes along the straight line to the
      // target and stops on the last free tile in front of it.
      const moveSpec = selfMoveOf(s, M?.specs);
      const isJump = moveSpec && ['JUMP_MOVE', 'BLINK', 'SHADOW_STEP', 'TELEPORT'].includes(moveSpec.t);
      const occupiedAt = (x, y) => units.some(z => z.alive && z !== caster && z.x === x && z.y === y) ||
        placed.some(o => o.alive && o.collidable && o.x === x && o.y === y);
      // The landing tile is a CAST TARGET, so it must lie inside the skill's
      // EFFECTIVE range (base range_max + client SKILL_RANGE rows that pass
      // both active_param and skill_active_param). 「烟幕游击」is 1-3; the
      // environment 「突变」+2 only applies to RANGED skills, so a 5-tile
      // jump was never legal.
      const [, maxRangeMod] = rangeMods(caster, false, s);
      const effMax = Math.max(0, (s.rmax || 0) + maxRangeMod);
      const inCastRange = c => manhattan(caster, c) <= effMax;
      let jumpCell = isJump && tcell && tcell.walk && !occupiedAt(tcell.x, tcell.y) &&
        !(tcell.x === caster.x && tcell.y === caster.y) && inCastRange(tcell)
        ? {x: tcell.x, y: tcell.y} : null;
      // SHADOW_STEP / TELEPORT with an ENEMY target (暗影步, 将杀, 飞影风沙里
      // …) land the caster on a free tile NEXT TO the target, not on it.
      if (!jumpCell && isJump && tcell && occupiedAt(tcell.x, tcell.y) &&
          (moveSpec.t === 'SHADOW_STEP' || moveSpec.t === 'TELEPORT')) {
        // The cast range constrains the TARGET, not the landing tile, so a
        // 「背后」tile one step beyond max range is still legal. Client spec
        // names declare the landing rule: #121 / #21718「对目标传送，背后」
        // prefer the tile behind the target; #27138「最近位置」the nearest.
        const near = DIRS.map(([dx, dy]) => grid.at(tcell.x + dx, tcell.y + dy))
          .filter(c => c && c.walk && !occupiedAt(c.x, c.y));
        const ddx = tcell.x - caster.x, ddy = tcell.y - caster.y;
        const back = Math.abs(ddx) >= Math.abs(ddy) ? [Math.sign(ddx) || 1, 0] : [0, Math.sign(ddy) || 1];
        const wantBack = /背后/.test(moveSpec.n || '');
        const isBack = c => c.x === tcell.x + back[0] && c.y === tcell.y + back[1];
        near.sort((a, b) => (wantBack ? (isBack(b) ? 1 : 0) - (isBack(a) ? 1 : 0) : 0)
          || manhattan(a, caster) - manhattan(b, caster));
        if (near.length) jumpCell = {x: near[0].x, y: near[0].y};
      }
      if (jumpCell && !opts.sub && !opts.free) {
        const from = {x: caster.x, y: caster.y};
        caster.x = jumpCell.x; caster.y = jumpCell.y;
        sim.epoch++;
        caster.dir = dirTo(from, jumpCell);
        caster.flags.moved = true;
        sim.teleport = {from, to: {...jumpCell}, skill: s.n, skillId: Number(s.id),
                        trigger: 'skill', instant: !!caster.instantIds?.has(Number(s.id)),
                        path: [{...from}, {...jumpCell}], spec: moveSpec.t,
                        specId: moveSpec.sid || 0, specName: moveSpec.n || s.n};
        log(`由技能「${s.n}」#${s.id} 触发位移机制 ${moveSpec.t}（特技 #${moveSpec.sid || 0}「${moveSpec.n || s.n}」）：` +
            `${caster.name} (${from.x},${from.y}) → (${jumpCell.x},${jumpCell.y})，曼哈顿距离 ${manhattan(from, jumpCell)} 格`);
        refreshAuras();
      } else if (moveSpec?.t === 'CHARGE' && tcell && !opts.sub && !opts.free) {
        // 「贯穿天际的必胜流星」/ 115 个 Charge 技能: dash to the tile right
        // in front of the target. PathAlert is resolved on every crossed tile.
        const from = {x: caster.x, y: caster.y};
        const dx = tcell.x - caster.x, dy = tcell.y - caster.y;
        const dir = Math.abs(dx) >= Math.abs(dy)
          ? [Math.sign(dx) || 1, 0] : [0, Math.sign(dy) || 1];
        const steps = Math.max(Math.abs(dx), Math.abs(dy));
        const path = [{...from}];
        const occupied = () => new Map(units.filter(u => u.alive && u !== caster)
          .map(u => [key(u.x, u.y), u]));
        for (let i = 1; i < steps; i++) {
          const x = caster.x + dir[0] * i, y = caster.y + dir[1] * i;
          const c = grid.at(x, y);
          const prev = grid.at(path[path.length - 1].x, path[path.length - 1].y);
          if (!c || !c.walk || occupied().has(key(x, y)) || c.h - (prev?.h || 0) > 2) break;
          path.push({x, y});
        }
        const to = path[path.length - 1];
        if (to.x !== from.x || to.y !== from.y) {
          caster.x = to.x; caster.y = to.y;
          sim.epoch++;
          caster.dir = dirTo(from, to);
          caster.flags.moved = true;
          caster.flags.moveSteps = (caster.flags.moveSteps || 0) + path.length - 1;
          sim.charge = {from, to: {...to}, steps: path.length - 1, path,
                        skill: s.n, skillId: Number(s.id), trigger: 'skill',
                        instant: !!caster.instantIds?.has(Number(s.id)),
                        spec: moveSpec.n || '冲锋', specId: moveSpec.sid || 0};
          log(`由技能「${s.n}」#${s.id} 触发位移机制 CHARGE（特技 #${moveSpec.sid || 0}「${moveSpec.n || '冲锋'}」）：` +
              `${caster.name} (${from.x},${from.y}) → (${to.x},${to.y})，沿 ${dir[0] ? (dir[0] > 0 ? '东' : '西') : (dir[1] > 0 ? '南' : '北')} 冲锋 ${path.length - 1} 格（目标 (${tcell.x},${tcell.y})，停在目标前一格）`);
          refreshAuras();
        }
      }
      const plan = skillPlan(s);
      // Log where dynamic skill numbers come from (client specialities scaled
      // by buff stacks), e.g. 后备隐藏脂肪 ×6 → 11495 +30% 伤害 / +6 射程 /
      // +6 击退. This is the numeric audit trail for the battle log.
      const scaling = skillScalingOf(caster, s);
      // Sub-casts (CAST_SKILL / follow-ups) run castSkill() again; keep the
      // MAIN cast's scaling for the replay step instead of overwriting it.
      if (!opts.sub && !opts.depth) sim.skillScaling = scaling;
      if (scaling.length) {
        log(`技能「${s.n}」动态数值（客户端特技 × 状态层数）：` + scaling.map(r => {
          const unit = r.kind === '射程' ? ' 格' : r.attr === 'DAMAGE' ? '%' : '';
          return `[${r.buff}]×${r.stacks} → ${r.attr} +${r.value}${unit}（特技 #${r.spec}，每层 +${r.per}）`;
        }).join('；'));
      }
      // ADDITIONAL_ATTACK linked to a pure-damage skill is the NEXT DAMAGE
      // SEGMENT of this one cast (安娜 警戒: 19204 35% + 19642 35%), not a
      // second cast / second 警戒. `linkedSpecs` keeps those specs from also
      // firing through runSkillSpecs(at=3).
      const linkedSpecs = new Set();
      const selfLoopSeen = new Set();
      for (const sid of s.sp || []) {
        const sp = M?.specs?.[sid];
        if (!sp) continue;
        if (sp.t === 'ADDITIONAL_ATTACK' && sp.p?.[0]) {
          const linked = skillRec(sp.p[0]);
          if (linked && linked.df > 0 && !(linked.sp || []).length) linkedSpecs.add(sid);
          continue;
        }
        // The client table sometimes stores the SAME self-referencing loop
        // row twice (阿尔曼大帝 21261 → #28549 ×2, 21296 → #28596 ×2). That
        // doubles the recursion at every depth. One row = one loop step.
        if (sp.t === 'CAST_SKILL' && Number(sp.p?.[0]) === Number(s.id)) {
          if (selfLoopSeen.has(sid)) linkedSpecs.add(sid);
          else selfLoopSeen.add(sid);
        }
      }
      // Each segment settles independently (crit / shield / 不屈 / death check
      // / calc panel). A normal single-hit skill keeps its legacy path.
      const segments = damageSegmentsOf(s);
      let captured = null;
      // TARGET_SELECT (active_time 2) is resolved inside this cast; its
      // selection must not leak into later casts / unit-level effects.
      const outerSelection = sim.selection;
      sim.selection = null;
      if (!caster.alive || !tcell) { sim.selection = outerSelection; return hits; }
      // Last line of defence: 「仅能对空地使用」 also applies to sub-casts
      // and linked casts, which bypass decide()'s candidate filter.
      if (s.eg && (tcell.pit || !tcell.walk ||
          units.some(u => u.alive && u !== caster && u.x === tcell.x && u.y === tcell.y) ||
          placed.some(o => o.alive && o.x === tcell.x && o.y === tcell.y))) {
        log(`「${s.n}」目标格 (${tcell.x},${tcell.y}) 不是空地，按客户端规则拒绝施放`);
        bump(cov.skipped, '目标不是空地');
        sim.selection = outerSelection;
        return hits;
      }
      // GLOBAL_LIMIT_COUNT_COMMAND p = [skillId, n]: the client lets that
      // skill resolve at most n times per command (= per action). 「多重爆裂-
      // 行动后结算」#26523 [20194, 1] is triggered by every hit of a
      // multi-hit skill but settles ONCE per action.
      for (const sid of s.sp || []) {
        const sp = M?.specs?.[sid];
        if (sp?.t !== 'GLOBAL_LIMIT_COUNT_COMMAND' || Number(sp.p?.[0]) !== Number(s.id)) continue;
        const k = `${sim.actionId || 0}:${caster.uid}:${s.id}`;
        const seen = sim.commandCasts || (sim.commandCasts = new Map());
        const n = seen.get(k) || 0;
        if (n >= Math.max(1, Number(sp.p?.[1]) || 1)) { sim.selection = outerSelection; return hits; }
        seen.set(k, n + 1);
        bump(cov.executed, 'GLOBAL_LIMIT_COUNT_COMMAND');
      }
      if (!opts.free && s.ap && !activationOk(s, {spec: {t: 'ACTIVATION'}, owner: caster, src: 'skill'},
                                             {attacker: caster, skill: s, target: null})) {
        log(`${caster.name} 的「${s.n}」未满足施放条件`);
        sim.selection = outerSelection;
        return hits;
      }
      if (!opts.free) {
        caster.tp -= tpCost(caster, s);
        if (s.cd > 0) caster.cd[s.id] = s.cd;
        caster.uses[s.id] = (caster.uses[s.id] || 0) + 1;
        caster.uses[s.id + ':t'] = (caster.uses[s.id + ':t'] || 0) + 1;
        caster.flags.skilled = true;
      }
      // Client RANDOM_BLOCK / RANDOM_UNIT inside a UNIT-targeting skill
      // re-select the target at random (they are not object placements):
      //   将杀 13331/13333/13334 RANDOM_BLOCK(at 1) → 1 random block holding a
      //     valid target inside the skill's own range (「范围2格内随机敌人」)
      //   后续弹射 19286 RANDOM_UNIT(at 2, tt 2) → 1 random enemy inside the
      //     AOE, excluding the previous segment's target (「1名其他敌人」)
      const handledRandom = new Set();
      const randBlockSid = (s.aim === 'enemy' || s.aim === 'ally')
        ? (s.sp || []).find(x => M?.specs?.[x]?.t === 'RANDOM_BLOCK' && (AT_ALIAS[M.specs[x].at] || M.specs[x].at) === 1)
        : null;
      if (randBlockSid) {
        handledRandom.add(randBlockSid);
        const cells = targetCells(grid.at(caster.x, caster.y), s, caster, false)
          .filter(c => units.some(u => u.alive && u !== caster && u.x === c.x && u.y === c.y && affects(s, caster, u)));
        if (cells.length) {
          const c = cells[Math.floor(roll() * cells.length)];
          tcell = grid.at(c.x, c.y);
          log(`随机选取目标格 (${c.x},${c.y})：${cells.length} 个合法目标格中随机 1 个（RANDOM_BLOCK · ${s.n}）`);
        } else {
          log(`「${s.n}」射程内没有合法目标（RANDOM_BLOCK），本段不结算`);
          sim.selection = outerSelection;
          return hits;
        }
      }
      const d = dirTo(caster, tcell);
      const noTurn = opts.free || caster.flags?.notTurnAround ||
        (s.sp || []).some(sid => M?.specs?.[sid]?.t === 'NOT_TURN_AROUND');
      if (!noTurn && (d[0] || d[1])) caster.dir = d;
      const disp = displayAreaOf(s);
      const area = areaCells(caster, tcell, s, disp);
      const inArea = new Set(area.map(c => key(c.x, c.y)));
      // DISPLAY_AOE replaces the geometry for damage, but the head skill's
      // OWN AOE still decides who receives its at=2 marker / debuff specs.
      const headUnits = disp ? (() => {
        const head = new Set(areaCells(caster, tcell, s).map(c => key(c.x, c.y)));
        return units.filter(u => u.alive && u.side !== caster.side &&
          head.has(key(u.x, u.y)) && hitsUnit(s, caster, u));
      })() : null;
      // Client skill.target_param decides WHICH entities inside the area are
      // affected, overriding the default enemy/ally split: 贝拉「造物赋能lv2-
      // 协同响应」21482 is a 50% 穿透 hit on an AOE of ALL units, but
      // 「return target:GetSummoner() == owner and unit_npc_id == 8593 / 8730」
      // restricts it to her OWN 灵感星核 — whose 伤害缓冲 turns it into
      // 灵感指数. Ignoring it shot 4000+ into every unit on the field.
      // A predicate our VM cannot evaluate falls back to the default split.
      let targets = units.filter(u => u.alive && inArea.has(key(u.x, u.y)) && hitsUnit(s, caster, u));
      const randUnitSid = (s.sp || []).find(x => M?.specs?.[x]?.t === 'RANDOM_UNIT' &&
        (AT_ALIAS[M.specs[x].at] || M.specs[x].at) === 2 && [1, 2, 5].includes(M.specs[x].tt));
      let randomPrimary = null;
      if (randUnitSid) {
        handledRandom.add(randUnitSid);
        const sp = M.specs[randUnitSid];
        const n = Math.max(1, sp.p[0] || sp.p[1] || 1);
        const pool = targets.filter(u => u !== caster && !(opts.exclude || []).includes(u.uid));
        const picked = [];
        while (picked.length < n && pool.length) picked.push(pool.splice(Math.floor(roll() * pool.length), 1)[0]);
        targets = picked;
        randomPrimary = picked[0] || null;
        log(`随机选取 ${picked.length} 名目标${picked.length ? '：' + picked.map(u => u.name).join('、') : '（区域内没有其他合法目标）'}（RANDOM_UNIT · ${s.n}）`);
      }
      const inheritedProp = opts.prop || null;
      const propIntent = !!inheritedProp || propSkill(s);
      // Client STATUS_SKILL_TO_PROPS / Battle.Entity.Type.Props: damage and
      // status skills may target an attackable object (呆呆雪人 #516).
      const propTargets = propIntent ? placed.filter(o => o.alive && o.attackable && o.kind === 'PLACE_ITEM' &&
        inArea.has(key(o.x, o.y))) : [];
      const primaryProp = inheritedProp || (propIntent
        ? (placed.find(o => o.alive && o.attackable && o.kind === 'PLACE_ITEM' &&
            o.x === tcell.x && o.y === tcell.y) || propTargets[0] || null) : null);
      const primary = randUnitSid ? randomPrimary
        : (units.find(u => u.alive && u.x === tcell.x && u.y === tcell.y) || targets[0] || null);
      if (!opts.depth) { sim.live = new Map(); sim.castSerial = (sim.castSerial || 0) + 1; }
      const base = {attacker: caster, skill: s, object: opts.object || sim.objectOrigin || null,
                    counter: !!opts.counter, sub: !!opts.sub, depth: opts.depth || 0,
                    target: primary || primaryProp, targets, start: opts.start || {x: caster.x, y: caster.y}, firstHit: !!opts.firstHit,
                    origin: tcell, area, prop: primaryProp || inheritedProp, propTargets};
      const at = (extra) => Object.assign({}, base, extra);
      // The client casts an idskill_follow skill as its OWN attack: 陷阵·锐意
      // 承锋 (dt 5) jumps, then 灭魂一击后续 (dt 1) deals the damage. Every
      // reaction to that attack — 攻击前 / 被攻击前 / 被攻击后 / 攻击后 on
      // passives and buffs, evasion / parry / counters, 被非贯穿攻击 — sees
      // the FOLLOW skill. With the head (dt 5) those 51 skills read as a
      // non-attack: no counter, no 受击反应, and 伦伽勒·SP's 机动游击
      //「主动攻击后再移动」 (CombatDecision types {1,2,4}) could never hold.
      // The head's own specialities keep the head (runSkillSpecs(s, …, at())).
      const evSeg = followDamage(s) ? chainOf(s).find(seg => seg.df > 0 && Number(seg.id) !== Number(s.id)) : null;
      const evSkill = (evSeg && skillRec(evSeg.id)) || s;
      const evAt = (extra) => Object.assign({}, base, {skill: evSkill}, extra);
      // True when the client's own skill_cast_id chain already resolved the
      // faction responder (15937 → MAKE_OTHER_CAST_SKILL → 15935). In that
      // case the description-derived 50% fallback must not fire again.
      const sawCoordinatedCast = !!s.scid;
      if (opts.label) log(`${caster.name} 发动「${s.n}」（${opts.label}）`);
      fire(33, caster, at({defender: primary}));
      for (const t of targets) if (t !== caster) fire(54, t, at({defender: t}));
      if (opts.counter) fire(31, caster, at({defender: primary}));
      // ANY specs on the skill itself: run creation / marker effects once
      // per cast. Static attribute modifiers are skipped by runSkillSpecs.
      for (const sid of s.sp || []) {
        const sp = M?.specs?.[sid];
        if (!sp || (AT_ALIAS[sp.at] || sp.at) !== 1) continue;
        if (STATIC_TYPES.has(sp.t) || handledRandom.has(sid)) continue;
        if (!['PLACE_UNIT', 'PLACE_ITEM', 'PLACE_TRAP', 'RANDOM_BLOCK',
              'ACTIVATION', 'SET_SKILL_TAG', 'PLACE_UNIT_INHERIT_ATTR', 'OPERATION'].includes(sp.t)) continue;
        // A skill's OPERATION applies to EVERY tile its AOE covers, not just
        // the anchor: 伊凡「意念夺取CloneClone」(战斗开始 / 行动结束) declares
        // AOE diamond-1 and must freeze the caster's whole 1-tile radius.
        // CAST_SKILL at25/28 reaches this path through subCast, which is why
        // the terrain never changed even though the trigger itself fired.
        runSpec({spec: sp, sid, owner: caster, src: 'skill:' + s.id, name: s.n, skill: s},
          at({defender: primary, object: primaryProp || null, opArea: area}));
      }
      runSkillSpecs(s, caster, 2, at({defender: primary}), handledRandom, headUnits);
      fire(2, caster, evAt({defender: primary}));
      const counters = [];
      let primaryEvaded = false;
      const single = targets.length <= 1 && (s.area?.type || 'single') === 'single';
      for (let t of targets) {
        if (!caster.alive) break;
        if (!t.alive) continue;
        const enemyHit = t.side !== caster.side && evSkill.dt !== 5 && evSkill.dt !== 3;
        // 援护防御：友军受到单体直击时换位代为承受
        if (enemyHit && single && s.hm === 2 && !unitSpecs(caster).some(i => i.spec.t === 'IGNORE_ASSIST_DEFENCE')) {
          const guard = units.find(g => g.alive && g !== t && g.side === t.side && !noReactive(g) && unitSpecs(g).some(i =>
            i.spec.t === 'ASSIST_DEFENCE' && manhattan(g, t) <= Math.max(1, i.spec.p[0]) && limitOk(i) &&
            cond(i, {attacker: caster, defender: t, skill: s, target: t}) && (spend(i), true)));
          if (guard) {
            fire(34, guard, at({defender: t}));
            fire(36, t, at({defender: t}));
            [guard.x, guard.y, t.x, t.y] = [t.x, t.y, guard.x, guard.y];
            sim.epoch++;
            log(`${guard.name} 援护防御，与 ${t.name} 换位承受攻击`);
            bump(cov.executed, 'ASSIST_DEFENCE');
            const was = t;
            t = guard;
            fire(35, guard, at({defender: guard}));
            fire(37, was, at({defender: guard}));
          }
        }
        // Reaction checks (闪避 / 先制 / 格挡 / 被攻击前) see the attacking skill.
        const ctx = evAt({defender: t, target: t});
        // Client specialities on the ATTACKER that switch off the defender's
        // reactions / force a backstab. Previously these were only written to
        // unit.flags by runSpec() and never consulted here.
        const ignoreEvade = !!(unitSpecs(caster).some(i => i.spec.t === 'FORBIDDEN_EVADE') ||
          activeSpec(caster, s, 'IGNORE_EVADE', ctx));
        const ignoreParry = !!activeSpec(caster, s, 'IGNORE_PARRY', ctx);
        const forceBackstab = !!activeSpec(caster, s, 'FORCE_BACKSTAB', ctx);
        let parry = null;
        // Client `Break` skill tag = 贯穿攻击. active_time 62 「被非贯穿攻击前」
        // fires on the DEFENDER only for non-piercing attacks; the Lua
        // conditions on those specialities also check `skill:hasTag("Break")`.
        const nonBreak = !(evSkill.tags || []).includes('Break');
        if (enemyHit) {
          fire(15, t, ctx);
          if (nonBreak) fire(62, t, ctx);
          if (relPos(caster, t) === 'Back' || forceBackstab) { fire(45, caster, ctx); fire(46, t, ctx); }
          // 闪避
          const ev = !noReactive(t) && !ignoreEvade &&
            unitSpecs(t).find(i => i.spec.t === 'EVADE' && [1, 2, 15].includes(i.spec.at) && limitOk(i) && cond(i, ctx));
          if (ev) {
            spend(ev); bump(cov.executed, 'EVADE');
            log(`${t.name} 闪避了「${s.n}」（${ev.name}）`);
            hits.push({uid: t.uid, x: t.x, y: t.y, amount: 0, miss: true, before: t.hp, after: t.hp});
            primaryEvaded = true;
            fire(19, t, at({defender: t, target: caster}));
            fire(20, caster, ctx);
            queueCounter(t, caster, 19, counters, ctx);
            continue;
          }
          // 先制
          if (!opts.counter && !noReactive(t)) {
            const fh = unitSpecs(t).find(i => i.spec.t === 'FIRST_HIT' && limitOk(i) && cond(i, ctx));
            if (fh) {
              const fs = skillRec(fh.spec.p[0]) || t.skills.find(x => x.isNormal);
              if (fs && inRange(t, caster, fs, true)) {
                spend(fh); bump(cov.executed, 'FIRST_HIT');
                log(`${t.name} 先制反击（${fh.name}）`);
                castSkill(t, fs, grid.at(caster.x, caster.y), {counter: true, free: true, firstHit: true, depth: (opts.depth || 0) + 1});
                if (!caster.alive) break;
              }
            }
          }
          if (!t.alive) continue;
          fire(16, t, ctx);
          parry = noReactive(t) || ignoreParry ? null
            : unitSpecs(t).find(i => i.spec.t === 'PARRY' && limitOk(i) && cond(i, ctx));
          if (parry) { spend(parry); bump(cov.executed, 'PARRY'); fire(13, t, at({defender: t, target: caster})); fire(14, caster, ctx); }
        }
        if (!t.alive) continue;
        const selfCast = t === caster && s.dt !== 3;
        const segs = segments && !selfCast ? segments : null;
        const dmg = selfCast ? {kind: 'status'}
          : segs ? null : computeDamage(caster, t, s, ctx, {parry: !!parry, explain: true});
        if (dmg?.kind === 'heal') {
          const got = heal(caster, t, dmg.amount);
          hits.push({uid: t.uid, x: t.x, y: t.y, heal: true, amount: got, before: t.hp - got, after: t.hp, calc: dmg.parts, formula: dmg.formula});
          const hctx = at({defender: t, target: t, damage: got});
          runSkillSpecs(s, caster, 5, hctx); runSkillSpecs(s, caster, 6, hctx); runSkillSpecs(s, caster, 4, hctx);
          fire(17, caster, hctx); fire(18, t, at({defender: t, target: caster, damage: got}));
        } else if (dmg?.kind === 'status') {
          hits.push({uid: t.uid, x: t.x, y: t.y, amount: 0, status: true, before: t.hp, after: t.hp});
          for (const k of [5, 6, 4]) runSkillSpecs(s, caster, k, ctx);
          if (t !== caster && t.side !== caster.side) {
            fire(6, t, evAt({defender: t, target: caster})); fire(4, t, evAt({defender: t, target: caster}));
            if (caster.alive) fire(4, caster, evAt({defender: t, target: t}), attackerAt4);
          }
        } else {
          const list = segs || [{__dmg: dmg, label: null}];
          let totalDealt = 0, totalAbsorbed = 0, first = true, segCrit = false;
          for (const seg of list) {
            if (!t.alive) break;
            // Client `speciality.active_param` on THIS chain segment: the Lua
            // condition is evaluated against the actual defender at segment
            // resolution. 11451「百无禁忌」第二段的 12055/12056/12057 read
            // `target.temp_attributes.tp_max - target.temp_attributes.tp`,
            // i.e. missing energy → +30 / +60 / +90% damage factor. Nothing
            // here is character-specific: spec ids, values and conditions all
            // come from the decoded client tables.
            let segBoost = seg.boost || 0;
            const boosts = [];
            for (const br of seg.boostRows || []) {
              const sp = M?.specs?.[br.spec];
              if (!sp) continue;
              const segSkill = (seg.chainSkill && skillRec(seg.chainSkill)) || s;
              const inst = {spec: sp, sid: br.spec, owner: caster,
                            src: 'chain:' + segSkill.id, name: sp.n, skill: segSkill};
              if (!cond(inst, at({attacker: caster, defender: t, target: t, skill: segSkill}))) continue;
              segBoost += Number(br.pct) || 0;
              boosts.push({spec: br.spec, pct: br.pct, when: br.when});
            }
            if (boosts.length) log(`客户端条件倍率（${seg.label || s.n}）：` +
              boosts.map(b => `#${b.spec} +${b.pct}%`).join('、') +
              ` → 该段伤害 +${segBoost}%；条件 ` +
              boosts.map(b => b.when).filter(Boolean).join(' / '));
            // Each idskill_follow segment is a real client skill: its own
            // damage type / physic & spell factors (陷阵 head dt 5 → 灭魂一击
            // 后续 dt 1). Computing it with the head made it a 0-damage status.
            const sd = seg.__dmg || computeDamage(caster, t, segSkillOf(s, seg), ctx,
              {parry: !!parry, explain: true, hitsOverride: seg.hitsOverride ?? 1,
               factorOverride: seg.factor, extraBoost: segBoost, segLabel: seg.label});
            if (sd.kind === 'status' || sd.kind === 'heal') continue;
            const segBefore = t.hp;
            const sr = dealDamage(caster, t, sd.amount,
              {kind: sd.kind, pierce: sd.kind === 'pierce', skill: s});
            totalDealt += sr.dealt; totalAbsorbed += sr.absorbed;
            segCrit = segCrit || !!sd.crit;
            if (first && parry) log(`${t.name} 格挡，物理伤害减半（${parry.name}）`);
            // Damage any attackable prop on the primary target cell as well.
            if (first && primaryProp && t === primary && sd.amount > 0) {
              const dealt = damageObject(primaryProp, sd.amount, caster);
              if (dealt) hits.push({uid: `PROP${primaryProp.id}`, prop: primaryProp.id,
                     x: primaryProp.x, y: primaryProp.y,
                amount: dealt, before: primaryProp.hp + dealt, after: primaryProp.hp,
                kind: sd.kind, skill: s.n});
            }
            hits.push({uid: t.uid, x: t.x, y: t.y, amount: sr.dealt, absorbed: sr.absorbed,
              before: segBefore, after: t.hp, crit: sd.crit,
              restraint: sd.restraint, height: sd.height, killed: !t.alive, kind: sd.kind,
              skill: s.n, calc: sd.parts, formula: sd.formula, seg: seg.label || null,
              reborn: sr.reborn || null, rebornHp: sr.rebornHp || 0, zeroReason: sr.zeroReason || '',
              factor: seg.factor || s.df || 0, boost: segBoost,
              chainSkill: seg.chainSkill || null,
              boostSpecs: boosts.map(b => b.spec)});
            first = false;
          }
          const r = {dealt: totalDealt, absorbed: totalAbsorbed};
          const anyCrit = (segs ? segCrit : dmg?.crit) || false;
          // hctx: the cast skill's OWN rows; ehctx / back: passive & buff
          // reactions, which see the attacking (follow) skill.
          const hctx = at({defender: t, target: t, damage: r.dealt});
          const ehctx = evAt({defender: t, target: t, damage: r.dealt});
          const back = evAt({defender: t, target: caster, damage: r.dealt});
          for (const k of [5, 6, 7, 8, 53, 59, 4]) runSkillSpecs(s, caster, k, hctx);
          fire(5, caster, ehctx);
          if (r.dealt > 0) { fire(7, caster, ehctx); fire(22, caster, ehctx); }
          fire(53, caster, ehctx); fire(59, caster, ehctx);
          if (anyCrit) { fire(9, caster, ehctx); if (t.alive) fire(10, t, back); }
          for (const i of unitSpecs(caster)) {
            if (i.spec.t === 'RECOVER_HP_BY_DAMAGE' && i.spec.at === 7 && limitOk(i) && cond(i, ehctx)) {
              spend(i); bump(cov.executed, i.spec.t); EFFECTS.RECOVER_HP_BY_DAMAGE(i, ehctx);
            }
          }
          for (const sid of s.sp || []) {
            const sp = M?.specs?.[sid];
            if (sp?.t === 'RECOVER_HP_BY_DAMAGE') { bump(cov.executed, sp.t); EFFECTS.RECOVER_HP_BY_DAMAGE({spec: sp, owner: caster, name: s.n}, hctx); }
          }
          // 被攻击后 on the ATTACKER's side (attacker-guarded rows only).
          if (t !== caster && caster.alive) fire(4, caster, ehctx, attackerAt4);
          if (t.alive) {
            fire(6, t, back);
            if (r.dealt > 0) fire(8, t, back);
            fire(48, t, back); fire(60, t, back);
            fire(4, t, back);
            if (enemyHit && nonBreak && t !== caster) fire(63, t, back);
            if (enemyHit && !opts.counter) {
              queueCounter(t, caster, null, counters, hctx);
              for (const g of units) {
                if (!g.alive || g === t || g.side !== t.side || noReactive(g) || counters.some(c => c.unit === g)) continue;
                const inst = unitSpecs(g).find(i => i.spec.t === 'ASSIST_COUNTER_ATTACK' && limitOk(i) &&
                  cond(i, at({defender: t, target: caster})));
                const cs = inst && skillRec(inst.spec.p[0]);
                if (cs && inRange(g, caster, cs, true)) counters.push({unit: g, inst, skill: cs, assist: true});
              }
            }
          }
        }
      }
      if (!opts.counter && !opts.sub && primary && primary.alive && primary.side !== caster.side && s.dt !== 3 && s.dt !== 5) {
        for (const g of units) {
          if (!primary.alive || !g.alive || g === caster || g.side !== caster.side || noReactive(g)) continue;
          const inst = unitSpecs(g).find(i => i.spec.t === 'ASSIST_ATTACK' && limitOk(i) &&
            cond(i, at({defender: primary, target: primary})));
          const as = inst && skillRec(inst.spec.p[0]);
          if (!as || !inRange(g, primary, as, false)) continue;
          spend(inst); bump(cov.executed, 'ASSIST_ATTACK');
          fire(38, g, at({defender: primary})); fire(40, caster, at({defender: primary}));
          castSkill(g, as, grid.at(primary.x, primary.y), {sub: true, free: true, depth: (opts.depth || 0) + 1, label: `援护攻击·${inst.name}`});
          fire(39, g, at({defender: primary})); fire(41, caster, at({defender: primary}));
        }
      }
      if (!targets.length && (s.aim === 'self' || s.aim === 'ground')) runSkillSpecs(s, caster, 4, at({target: caster}));
      if (caster.alive) {
        if (primaryProp && !primary) {
          // Pure object attack (乌莉娅 普攻 → 雪人): run the CAST_SKILL chain so
          // 「触发并移除雪人」(20783 -> REMOVE_PROPS) actually destroys it.
          const pctx = at({defender: primaryProp, target: primaryProp, prop: primaryProp});
          fireObject(15, pctx);
          runSkillSpecs(s, caster, 4, pctx);
          runSkillSpecs(s, caster, 3, pctx, linkedSpecs);
          runSkillSpecs(s, caster, 47, pctx);
          log(`${caster.name} 攻击「${primaryProp.name}」`);
          const pd = dmg0(caster, s);
          if (pd > 0) damageObject(primaryProp, pd, caster);
        }
        // Client `skill_cast_id`: the FOLLOW-UP skill the client casts right
        // after this one's damage, on the same target block, BEFORE this
        // skill's 攻击后 effects. 「进行3次攻击…攻击后，消耗所有能量和[多重
        // 爆裂]，根据消耗总数追加伤害」(爆裂箭 19449 → 18975 → 18976) only
        // reads correctly when all three hits land first. It is a full cast —
        // damage, AOE, RANDOM_UNIT/RANDOM_BLOCK, specialities and its own
        // skill_cast_id (recursion handles deeper links):
        //   全装甲集火号令！15934 (df 0) → 飞弹礼花Clone 15968 (80% 穿透 AOE,
        //     CAST_SKILL 15937 → MAKE_OTHER_CAST_SKILL 15935 〈铃兰之剑〉协同响应)
        //   将杀 13324 (df 0) → 13329 → 13331 → 13333 → 13334 (4 × 100%)
        //   弹弹一击 19253 (70%) → 19286「后续弹射」(RANDOM_UNIT 1 名其他敌人)
        if (s.scid && (opts.depth || 0) < 8 && !(opts.castChain || []).includes(Number(s.scid))) {
          const cs = skillRec(s.scid);
          const cell = primary?.alive ? grid.at(primary.x, primary.y) : tcell;
          // A follow-up that re-selects a UNIT at random (后续弹射 RANDOM_UNIT,
          // 将杀 RANDOM_BLOCK) must not inherit the parent's prop target.
          const retargets = (cs?.sp || []).some(x => ['RANDOM_UNIT', 'RANDOM_BLOCK'].includes(M?.specs?.[x]?.t));
          if (cs && caster.alive && cell) {
            castSkill(caster, cs, cell, {sub: true, free: true, depth: (opts.depth || 0) + 1,
              prop: retargets ? null : (primaryProp || inheritedProp || null), object: opts.object || null,
              exclude: primary ? [primary.uid] : [],
              castChain: (opts.castChain || [Number(s.id)]).concat(Number(cs.id)),
              label: `skill_cast_id ← ${s.n}`});
            bump(cov.executed, 'SKILL_CAST_ID');
          }
        }
        if (plan?.cons) captured = captureConsumption(caster, plan.cons);
        runSkillSpecs(s, caster, 3, at({defender: primary}), linkedSpecs);
        runSkillSpecs(s, caster, 47, at({defender: primary}));
        // Run the WHOLE client `idskill_follow` chain, not just the first
        // hop. Each segment may add its own buffs / debuffs / sub-casts /
        // energy recovery. Specs already present on the head skill are
        // skipped so a shared marker (e.g. 无视反应 #14835) fires once.
        const headSp = new Set(s.sp || []);
        const fullChain = chainOf(s);
        for (const seg of fullChain.slice(1)) {
          const segSkill = skillRec(seg.id);
          if (!segSkill) continue;
          const fctx = at({defender: primary, skill: segSkill});
          // Keep the client's original follow-up timings. Damage-phase
          // timings (5/6/7/8) belong to the head skill and must not be run
          // again for chain segments (that would e.g. knock back twice).
          for (const k of [1, 2, 3, 4]) {
            for (const sid of segSkill.sp || []) {
              if (headSp.has(sid)) continue;
              const sp = M?.specs?.[sid];
              if (!sp || (AT_ALIAS[sp.at] || sp.at) !== k || STATIC_TYPES.has(sp.t)) continue;
              const inst = {spec: sp, sid, owner: caster, src: 'chain:' + seg.id,
                            name: sp.n, skill: segSkill};
              // An AOE debuff on a follow-up segment is declared ONCE in the
              // data but applies to EVERY enemy the AOE hit: 陷阵·锐意承锋
              // 「对自身范围3格内所有敌人…施加[伤害2]、[缴械]」 puts #21018
              // and #10725 (BUFF at=4, target_type 2) on 灭魂一击后续 #15657.
              // Running them once with `primary` disarmed only 伊凡 instead of
              // all five A-side targets hit by the same cast.
              const aoeTargets = k === 4 && Number(sp.tt) === 2
                ? targets.filter(t => t.alive && t !== caster && t.side !== caster.side) : null;
              if (aoeTargets && aoeTargets.length) {
                for (const t of aoeTargets)
                  runSpec(inst, at({defender: t, target: t, skill: segSkill}));
              } else {
                runSpec(inst, fctx);
              }
            }
          }
        }
        // (skill_cast_id follow-ups were cast above, before 攻击后 effects.)
        // Description-derived fallback ONLY for status 「号令」skills without a
        // client skill_cast_id (the real follow-up carries the damage).
        if (plan?.pierce && !s.scid && !opts.sub && !opts.free) {
          const pf = Object.assign({}, s, {df: plan.pierce, dt: 4, dmg: 0, dp: 0});
          for (const t of targets) {
            if (!t.alive || t.side === caster.side) continue;
            const pctx = at({defender: t, target: t});
            const sd = computeDamage(caster, t, pf, pctx,
              {explain: true, hitsOverride: 1, segLabel: `协同号令 ${plan.pierce}%`});
            const before = t.hp;
            const rr = dealDamage(caster, t, sd.amount, {kind: 'pierce', pierce: true, skill: s});
            hits.push({uid: t.uid, x: t.x, y: t.y, amount: rr.dealt, absorbed: rr.absorbed, before, after: t.hp,
              kind: 'pierce', skill: s.n, calc: sd.parts, formula: sd.formula, seg: `${plan.pierce}% 穿透伤害`,
              reborn: rr.reborn || null, rebornHp: rr.rebornHp || 0, zeroReason: rr.zeroReason || ''});
            log(`协同号令穿透伤害：${caster.name}「${s.n}」→ ${t.name}，客户端描述倍率 ${plan.pierce}% → ${rr.dealt} 点`);
          }
          bump(cov.executed, 'COORDINATE_ORDER_DAMAGE');
        }
        fire(3, caster, evAt({defender: primary}));
        fire(47, caster, at({defender: primary}));
        // [协同号令] (skill_tag ChainTag1) broadcasts a Chain-tagged marker
        // to the WHOLE field. Every unit's 「协同响应」specialities at active_time
        // 3 and 4 then fire, gated by their own client Lua predicates
        // (`return skill:hasTag("Chain")` / `hasTag("ChainTag2")`). This is what
        // makes 麦莎·SP's 号令 trigger 伦伽勒·SP「机动游击」的协同响应 and
        // every other responder, without hard-coding any character.
        if (((s.tags || []).includes('ChainTag1') || (s.tags || []).includes('Chain')) &&
            sim.coordinateDepth < 2 && !opts.free) {
          sim.coordinateDepth++;
          try { broadcastChainResponse(caster, s, opts); }
          finally { sim.coordinateDepth--; }
        }
        // 「使所有〈铃兰之剑〉己方进行额外[协同响应]，对自身范围 3 格内敌人
        // 造成 50% 物攻值加魔攻值的[穿透伤害]」 is decoded from the client
        // skill description into plan.coord (faction / radius / factor).
        // Only run this fallback when the client's OWN linked-responder chain
        // did not already resolve — otherwise the 50% hit lands twice.
        if (plan?.coord && !opts.sub && !opts.free && sim.coordinateDepth === 0 &&
            !sawCoordinatedCast) {
          resolveCoordinatedResponse(caster, s, plan.coord, hits, at);
        }
        if (opts.counter) fire(32, caster, at({defender: primary}));
      }
      if (plan?.cons || plan?.bonus?.length) {
        const cap = captured || captureConsumption(caster, plan.cons);
        const count = applyConsumption(caster, plan.cons, cap);
        if (count > 0 && cap) {
          sim.consumption = {tp: cap.tp, stacks: cap.stacks, count,
                             buffName: cap.buffName || '', bonus: plan.bonus?.[0] || null};
          log(`${caster.name} 的「${s.n}」消耗转化：能量 ${cap.tp} 点 + ` +
              `[${cap.buffName || '状态'}] ${cap.stacks} 层 = ${count} 层追加伤害`);
        }
        if (plan.bonus?.length && count > 0) {
          const bt = primary?.alive ? primary : (targets.find(x => x.alive) || null);
          if (primaryEvaded) log(`${caster.name} 的「${s.n}」追加伤害因目标闪避未结算`);
          else settleBonus(caster, s, plan, bt, count, at, hits);
        }
      }
      // 反击：每名受击者只触发 1 个，按满足条件的第一条（手册「反击堆叠规则」）。
      for (const c of counters) {
        if (!c.unit.alive || !caster.alive) continue;
        spend(c.inst); bump(cov.executed, c.assist ? 'ASSIST_COUNTER_ATTACK' : 'COUNTER_ATTACK');
        if (c.assist) { fire(50, c.unit, at({defender: caster})); fire(49, caster, at({defender: c.unit})); }
        log(`${c.unit.name} ${c.assist ? '援护反击' : '反击'}（${c.inst.name}）`);
        fire(55, caster, at({defender: c.unit, target: c.unit}));
        castSkill(c.unit, c.skill, grid.at(caster.x, caster.y), {counter: true, free: true, depth: (opts.depth || 0) + 1});
      }
      refreshAuras();
      sim.selection = outerSelection;
      // Sub-casts (CAST_SKILL / MAKE_OTHER_CAST_SKILL / 协同响应 / follow-up
      // attacks) resolve real damage, but their hits used to be discarded by
      // subCast(), so the replay step never showed them. Inside actOnce() the
      // parent step collects them through `sim.subHits`; OUTSIDE it (turn /
      // action boundaries — 每人回合结束 28, 行动后 43, 战斗开始 25 …) they
      // go to `sim.pendingSubHits`, which flush() attaches to the owning step.
      // 警戒 hits are reported through step.alertHits and are excluded.
      if (opts.sub && !opts.alert && hits.length) {
        const sink = Array.isArray(sim.subHits) ? sim.subHits
          : (sim.pendingSubHits || (sim.pendingSubHits = []));
        for (const h of hits) sink.push(Object.assign({}, h,
          {sub: true, byUid: caster.uid, byName: caster.name, bySkill: s.n, bySkillId: Number(s.id)}));
      }
      return hits;
    }
    function inRange(u, target, s, counter) {
      return targetCells(grid.at(u.x, u.y), s, u, counter).some(c => c.x === target.x && c.y === target.y) && !blocked(u, target, s, u.side);
    }
    function queueCounter(t, caster, at, list, ctx) {
      if (list.some(c => c.unit === t) || !t.alive || noReactive(t)) return;
      if (CONTROL_SKIP.has(t.buffs.find(b => CONTROL_SKIP.has(b.def.et))?.def.et)) return;
      for (const inst of unitSpecs(t)) {
        if (inst.spec.t !== 'COUNTER_ATTACK') continue;
        const sat = AT_ALIAS[inst.spec.at] || inst.spec.at;
        if (at ? sat !== at : ![1, 4, 6, 8].includes(sat)) continue;
        if (!limitOk(inst) || !cond(inst, Object.assign({}, ctx, {attacker: caster, defender: t}))) continue;
        const cs = skillRec(inst.spec.p[0]) || t.skills.find(x => x.isNormal);
        if (!cs || !inRange(t, caster, cs, true)) continue;
        list.push({unit: t, inst, skill: cs});
        return;
      }
    }

    /* ---------- alert (警戒) ----------
       The client declares ALERT_ATTACK with the skill id in p[0], the number
       of allowed reactions in `lt`, STRENGTHEN_ALERT (强制警戒：射程/伤害
       提升且无法被打断), ALERT_ATTACK_DISPLAY (范围预览) and the skill column
       hide_alert_preivew. `alert_dist` / `alert_points` are the decrypted
       AIMachine fields consumed by the movement phase. */
    function alertState(u) {
      if (!u || !u.alive || !M) return null;
      const list = unitSpecs(u);
      let best = null;
      for (const inst of list) {
        const s = inst.spec;
        if (s.t !== 'ALERT_ATTACK') continue;
        const as = skillRec(s.p[0]);
        if (!as) continue;
        const strengthened = list.some(i => i.spec.t === 'STRENGTHEN_ALERT');
        // STRENGTHEN_ALERT comes in two client rows: #9472「警戒强化」(安娜,
        // 只提升警戒且无法被打断) and #9499「强制警戒（可打断技能）」. Only the
        // latter — or an explicit FORCE_STOP speciality on the alert skill —
        // stops the mover. Equating every 强制警戒 with FORCE_STOP made 安娜's
        // alert interrupt every action, which the client never does.
        const interrupts = list.some(i => i.spec.t === 'STRENGTHEN_ALERT' &&
          /打断|停止/.test(i.spec.n || '')) ||
          (as.sp || []).some(sid => M?.specs?.[sid]?.t === 'FORCE_STOP');
        const display = list.some(i => i.spec.t === 'ALERT_ATTACK_DISPLAY');
        const previewFrom = list.filter(i => i.skill?.hap).map(i => i.skill.n);
        const base = s.lt || s.lct || Number(s.p[1]) || 1;
        const bonus = countBonusOf(u, 'ALERT_ATTACK');
        // 「一段警戒造成 2 段伤害」: ONE trigger (one alert_points charge,
        // one cast) can settle several DAMAGE SEGMENTS. `points` counts 警戒
        // 次数, `segments` counts the damage 段 inside one of them. 安娜:
        // points 2+1=3 per turn, segments 35% + 35% = 2.
        const segmentDefs = damageSegmentsOf(as) ||
          [{factor: Number(as.df) || 0, label: `${Number(as.df) || 0}% 伤害`}];
        const rec = {skillId: Number(s.p[0]), skill: as.n, specId: Number(inst.sid),
                     dist: Math.max(1, as.rmax || 1),
                     basePoints: base, countBonus: bonus, points: base + bonus,
                     strengthened, interrupts, segments: segmentDefs.length,
                     hits: segmentDefs.length, segmentDefs, display,
                     hidePreview: !!as.hap || previewFrom.length > 0,
                     hidePreviewFrom: previewFrom, inst, name: s.n || as.n};
        if (!best || rec.dist > best.dist) best = rec;
      }
      if (best) {
        const k = (best.inst.buff ? 'b' + best.inst.buff.id : best.inst.src) + ':' + best.inst.sid;
        const L = u.limits[k];
        best.left = Math.max(0, best.points - (L?.turn || 0));
        best.key = k;
      }
      return best;
    }
    const alertReach = u => alertState(u)?.dist || 0;
    function checkAlert(mover, cell) {
      // Client `PathAlert` / `CollectAlertBlocks` / `FindAlertTargetBlocks`:
      // the reaction fires on the FIRST traversed block inside the alert
      // zone, not only on the final tile. `cell` is that path block; it
      // defaults to the mover's current position (also used for teleports).
      if (sim.alertActive) return null;
      const at = cell || mover;
      for (const g of enemiesOf(mover)) {
        if (!mover.alive) return null;
        if (noReactive(g)) continue;
        const state = alertState(g);
        if (!state || state.left <= 0) continue;
        for (const inst of unitSpecs(g)) {
          if (inst.spec.t !== 'ALERT_ATTACK' || !limitOk(inst)) continue;
          const as = skillRec(inst.spec.p[0]);
          if (!as || !inRange(g, at, as, false) || manhattan(g, at) > state.dist
              || !cond(inst, {attacker: g, defender: mover, target: mover})) continue;
          spend(inst); bump(cov.executed, 'ALERT_ATTACK');   // exactly ONE charge
          const left = Math.max(0, state.left - 1);
          log(`${g.name} 在 (${at.x},${at.y}) 警戒触发「${as.n}」（范围 ${state.dist} 格，一段警戒造成 ${state.segments} 段伤害，剩余 ${left} 次 / 共 ${state.points} 次）`);
          sim.alertActive = true;
          let alertHits = [];
          // `at` is the PATH BLOCK where PathAlert fired, but the mover has
          // already finished its whole move by the time we resolve it. The
          // client's FindAlertTargetBlocks attacks the UNIT that stepped into
          // the alert zone, so aim the cast at the mover's ACTUAL cell —
          // aiming at the empty path cell produced zero targets and no damage.
          const alertCell = grid.at(mover.x, mover.y) || grid.at(at.x, at.y);
          try { alertHits = castSkill(g, as, alertCell, {free: true, sub: true, depth: 1, alert: true}); }
          finally { sim.alertActive = false; }
          if (!alertHits.length)
            log(`  警戒未命中：触发格 (${at.x},${at.y})，目标格 (${alertCell.x},${alertCell.y})，${mover.name} 已不在可攻击格`);
          const stop = (as.sp || []).some(sid => M.specs[sid]?.t === 'FORCE_STOP') ||
                       state.interrupts;
          const forced = !!stop && !unitSpecs(mover).some(i => i.spec.t === 'IGNORE_FORCE_STOP');
          if (forced) { log(`${mover.name} 被强制停止，本次行动结束`); bump(cov.executed, 'FORCE_STOP'); }
          // Record EVERY declared segment, even when the whole attack is
          // evaded (castSkill then emits one `miss` hit instead of N segments).
          const settled = alertHits.filter(h => h.seg);
          const plainHits = alertHits.filter(h => !h.status && !h.heal);
          const segmentHits = state.segmentDefs.map((d, i) => {
            const hit = settled.find(h => h.seg === d.label) || settled[i] ||
                        (state.segmentDefs.length === 1 ? plainHits[i] : null);
            return {seg: d.label, factor: d.factor, uid: hit?.uid || null,
                    amount: hit?.amount || 0, miss: !hit || !!hit.miss};
          });
          log(`  一段警戒的伤害段：${segmentHits.map((x, i) =>
            `第 ${i + 1}/${segmentHits.length} 段 ${x.factor}% → ${x.uid ? (byId.get(x.uid)?.name || x.uid) : '未指定目标'} ` +
            `${x.miss ? '（被闪避 / 未结算）' : `${x.amount} 点`}`).join('；')}`);
          return {owner: g.name, skill: as.n, cell: {x: at.x, y: at.y},
                  points: state.points, basePoints: state.basePoints,
                  countBonus: state.countBonus, left, forced,
                  triggers: 1, segmentCount: segmentHits.length,
                  hits: segmentHits.length, segments: segmentHits,
                  interrupts: !!state.interrupts};
        }
      }
      return null;
    }

    /* ---------- movement ---------- */
    function canStep(mover, from, to) {
      if (!to || !to.walk) return false;
      if (mover.move.type === 3) return true;
      const dh = to.h - from.h;
      return dh > 0 ? dh <= (mover.move.up || 2) : -dh <= (mover.move.down || 2);
    }
    // 高差 ≥2 的每步额外消耗 0.5 移动力（战斗手册「高低移动」）。
    function reachable(unit, budgetOverride) {
      const start = grid.at(unit.x, unit.y);
      const occ = new Map(units.filter(u => u.alive && u !== unit).map(u => [key(u.x, u.y), u]));
      for (const o of placed) if (o.alive && o.collidable) occ.set(key(o.x, o.y), o);
      const immobile = hasEffect(unit, 'Immobilize') || unit.move.type === 5;
      const budget = immobile ? 0 : (budgetOverride ?? attr(unit, 'MOBILITY'));
      const best = new Map([[key(start.x, start.y), {cost: 0, prev: null, cell: start}]]);
      if (unit.move.type === 4 && !immobile) {
        for (const c of grid.cells.values()) {
          const d = manhattan(c, start);
          if (c.walk && d > 0 && d <= budget && !occ.has(key(c.x, c.y))) best.set(key(c.x, c.y), {cost: d, prev: key(start.x, start.y), cell: c});
        }
        return best;
      }
      const open = [{cell: start, cost: 0}];
      while (open.length) {
        open.sort((a, b) => a.cost - b.cost);
        const {cell, cost} = open.shift();
        if (cost > (best.get(key(cell.x, cell.y))?.cost ?? Infinity)) continue;
        for (const [dx, dy] of DIRS) {
          const n = grid.at(cell.x + dx, cell.y + dy);
          if (!canStep(unit, cell, n)) continue;
          const blocker = occ.get(key(n.x, n.y));
          // Client `move_block` / `block.temp_unit:isFriend(owner)`: a unit
          // may walk THROUGH a friendly unit, but enemies block the path.
          // Occupied cells are still marked `blocked` below, so nobody can
          // finish a move inside a teammate's tile.
          if (blocker && blocker.side !== unit.side) continue;
          // The client's AIMachine charges the terrain step cost only;
          // height changes are gated by unit.jump_up / jump_down in canStep.
          // The old +0.5 "高低移动" surcharge was an engine invention that made
          // legal client moves (e.g. (12,5)→(7,5), (11,4)→(9,5)) unreachable.
          // client field_status.mobility: 燃烧 +0.5 / 冰冻 +1 / 沼泽 +0.5
          // per tile, waived by IGNORE_FIELDSTATUS / NO_FIELDSTATUS_MOBILITY.
          const c = cost + n.step + fieldStepCost(unit, n);
          if (c > budget + 1e-9) continue;
          const k = key(n.x, n.y);
          if (c < (best.get(k)?.cost ?? Infinity)) { best.set(k, {cost: c, prev: key(cell.x, cell.y), cell: n}); open.push({cell: n, cost: c}); }
        }
      }
      // Do NOT delete occupied cells: pathTo() walks `prev` through them and
      // a deleted intermediate cell truncates the drawn path to a single hop
      // (e.g. (0,8)->(5,8) showing only [[5,8]]). Mark them instead.
      for (const [k, node] of best) if (occ.has(k)) node.blocked = true;
      return best;
    }
    function pathTo(reach, k) {
      const path = [];
      for (let cur = k; cur; cur = reach.get(cur)?.prev) {
        const node = reach.get(cur);
        if (!node) break;
        path.unshift({x: node.cell.x, y: node.cell.y});
      }
      return path;
    }
    function approachField(unit) {
      const dist = new Map(), queue = [];
      const taunters = enemiesOf(unit).filter(e => unitSpecs(e).some(i => i.spec.t === 'TAUNT'));
      for (const e of taunters.length ? taunters : enemiesOf(unit)) {
        dist.set(key(e.x, e.y), 0);
        queue.push(grid.at(e.x, e.y));
      }
      for (let i = 0; i < queue.length; i++) {
        const cur = queue[i];
        for (const [dx, dy] of DIRS) {
          const n = grid.at(cur.x + dx, cur.y + dy);
          // The BFS expands OUTWARD from the enemies, but the unit will walk
          // n → cur. canStep(mover, from, to) checks to.h - from.h, so the
          // arguments must be (n, cur), not (cur, n); a one-way height cliff
          // otherwise looked traversable from the wrong side.
          if (!n || !n.walk || !canStep(unit, n, cur)) continue;
          const k = key(n.x, n.y);
          if (dist.has(k)) continue;
          // BFS expands OUTWARD from enemies, so the unit will eventually
          // walk n → cur. The cost of that step is entering `cur`, NOT `n`:
          // reachable() charges `cost + n.step` when moving cell → n. Charge
          // the mirror (cur.step) here, otherwise asymmetric terrain (冰冻 /
          // 燃烧 / 沼泽) and one-way height cliffs make the guidance field
          // disagree with the actual reachable() path, and the AI stops on a
          // "cheap" tile it can never leave.
          dist.set(k, dist.get(key(cur.x, cur.y)) + cur.step + fieldStepCost(unit, cur));
          queue.push(n);
        }
      }
      return dist;
    }

    /* ---------- AI ---------- */
    // Value of a skill's non-damage effects on a specific unit. Support,
    // heal, shield, dispel and debuff skills all score here, so the AI can
    // actually use the newly-castable utility skills instead of idling.
    // Map a skill onto the client's SKILL_LIST_TAG categories. The decrypted
    // bytecode declares these 13 tags and their declaration order is the
    // client's own priority. Used by the AI as a tie-break weight.
    function skillTag(s) {
      const sp = (s.sp || []).map(id => M?.specs?.[id]?.t);
      const has = (...x) => sp.some(v => x.includes(v));
      if (has('RE_ROUND', 'ACTED_ACT')) return s.aim === 'ally' ? 'EXTRA_TURN_FRIEND' : 'EXTRA_TURN_SELF';
      if (s.dt === 3 || has('PERCENT_HEAL', 'RECOVER_ATTRIBUTE', 'RECOVER_HP_BY_DAMAGE')) return s.aim === 'ally' ? 'HEAL' : 'AID';
      if (has('JUMP_MOVE', 'TARGET_TELEPORT', 'BLINK', 'KNOCKBACK_SELF')) return 'MOVE_TO';
      if (has('SEND_OFF', 'OTHER_TELEPORT_TO_TARGET')) return 'MOVE_AWAY';
      if (has('PHYSIC_ARMOR', 'SPELL_ARMOR', 'BUFF_BUNDLE_GAIN', 'DISPEL')) return s.aim === 'enemy' ? 'BUFF_SELF' : 'BUFF_FRIEND';
      if (s.dt === 5 || isUtility(s)) return s.aim === 'ally' ? 'BUFF_FRIEND' : 'BUFF_SELF';
      if (s.aim === 'enemy') return 'TO_ENEMY';
      return s.rmax <= 1 && !s.tp ? 'NORMAL_ATTACK' : 'NONE';
    }
    const UTILITY_W = {
      BUFF: 45, SKILL_GROUP: 18, TACTICS_SKILL_GROUP: 18, CAST_SKILL: 22,
      MAKE_OTHER_CAST_SKILL: 20, ADDITIONAL_ATTACK: 20, DISPEL: 28, REMOVE_BUFF: 24,
      RECOVER_ATTRIBUTE: 26, RECOVER_HP_BY_DAMAGE: 14, PHYSIC_ARMOR: 32, SPELL_ARMOR: 32,
      BUFF_BUNDLE_GAIN: 22, SKILL_CD: 18, SKILL_CD_MAX: 12, CHARGE: 16, STEAL_TP: 14,
      MULTI_CONSUME_TP: 0, AURA: 20, AOE: 8, PLACE_ITEM: 16, PLACE_TRAP: 16,
      PLACE_UNIT: 24, PLACE_UNIT_INHERIT_ATTR: 24, KNOCKBACK: 18, TARGET_TELEPORT: 14,
      LIFE_LOST: 26, POISON: 26, PARASITIC: 26, DAMAGE: 24, ADDITIONAL_ATTRIBUTE_DAMAGE: 16,
      SPECIFY_ATTRIBUTE_VALUE: 18, SKILL_RANGE: 10, BUFF_DURATION: 10,
      IMMUNE: 16, AFFILIATE_BUFF: 14, SETTLE_TOXIN: 22, SETTLE_DURATION_DAMAGE: 22,
      RE_ROUND: 30, ACTED_ACT: 28, ACTED_MOVE: 18, JUMP_MOVE: 16, SHADOW_STEP: 14,
      SHAPESHIFT: 22, DELAY_SKILL: 12, TARGET_BUFF_MODIFY_ATTRIBUTE: 12,
      OPERATION: 10, ACTIVATION: 8, SKILL_COUNT: 8, IGNORE_FIELDSTATUS: 8,
    };
    // A composite skill's buffs / debuffs live on the FOLLOW-UP segments too.
    // The AI must value them, otherwise e.g. a chain skill that applies a
    // debuff on segment 2 is scored as if it only had the first hit.
    function compositeSpecs(s) {
      const out = new Set(s.sp || []);
      for (const seg of chainOf(s)) for (const sid of seg.sp || []) out.add(sid);
      return [...out];
    }
    function effectValue(s, caster, u, opts = {}) {
      const friendly = u.side === caster.side;
      let v = 0;
      for (const sid of compositeSpecs(s)) {
        const sp = M?.specs?.[sid];
        if (!sp) continue;
        const t = sp.t;
        // `skipHeal` scores only the NON-heal part of a dt=3 skill, so a
        // full-HP ally is still worth buffing (神泽 / 命途所至).
        if (opts.skipHeal && (t === 'PERCENT_HEAL' || t === 'RECOVER_HP' ||
            (t === 'RECOVER_ATTRIBUTE' && ['HP', 'HP_MAX'].includes(attrName(sp.p[0]))))) continue;
        if (t === 'BUFF') {
          const id = sp.p[0];
          if (!id) continue;
          const def = M.buffs?.[id];
          if (!def || u.buffs.some(b => b.id === id)) continue;
          const good = (def.bt === 2 && friendly) || (def.bt === 3 && !friendly);
          if (good) v += 45 + (CONTROL_SKIP.has(def.et) && !friendly ? 80 : 0);
          else if (def.bt === 2 && !friendly) v -= 30;   // do not buff the enemy
          continue;
        }
        if (t === 'DISPEL' || t === 'REMOVE_BUFF') {
          const wanted = u.buffs.filter(b => friendly ? b.def.bt === 3 : b.def.bt === 2).length;
          v += wanted ? Math.min(4, wanted) * 28 : -6;   // avoid wasting a cleanse
          continue;
        }
        if (t === 'RECOVER_ATTRIBUTE') {
          const n = attrName(sp.p[0]);
          if (n === 'HP' || n === 'HP_MAX') {
            const missing = maxHpOf(u) - u.hp;
            v += friendly && missing > 0 ? Math.min(60, missing / Math.max(1, maxHpOf(u)) * 100) : -4;
          } else if (n === 'TP') {
            const room = attr(u, 'TP_MAX') - u.tp;
            v += friendly && room > 0 ? 22 : -4;
          } else if (!friendly) v -= 12;
          else v += 12;
          continue;
        }
        if (t === 'PHYSIC_ARMOR' || t === 'SPELL_ARMOR') {
          const has = u.buffs.some(b => (b.def.sp || []).includes(Number(sid)));
          v += friendly && !has ? 32 : -4;
          continue;
        }
        if (t === 'AOE' || t === 'SKILL_RANGE' || t === 'MULTI_CONSUME_TP') { v += 4; continue; }
        const w = UTILITY_W[t];
        if (w === undefined) { v += 6; continue; }        // unknown effect still has some value
        const hostileOnly = ['LIFE_LOST', 'POISON', 'PARASITIC', 'DAMAGE', 'KNOCKBACK',
                             'TARGET_TELEPORT', 'STEAL_TP', 'SETTLE_TOXIN', 'SETTLE_DURATION_DAMAGE'].includes(t);
        const helpfulOnly = ['RE_ROUND', 'ACTED_ACT', 'CHARGE', 'SKILL_CD', 'SKILL_CD_MAX',
                             'RECOVER_HP_BY_DAMAGE', 'PLACE_UNIT', 'PLACE_ITEM', 'IMMUNE'].includes(t);
        if (hostileOnly && friendly) { v -= w * 0.5; continue; }
        if (helpfulOnly && !friendly) { v -= w * 0.5; continue; }
        v += w * (friendly ? 1 : 0.8);
      }
      return v;
    }
    const buffValue = (s, caster, u) => effectValue(s, caster, u);
    // AOE scores depend on the covered units but NOT on the stand; compute
    // them once per area signature instead of once per candidate stand.
    const aoeBonusCache = new Map();
    const aoeBonus = (inArea, pos, unit, target, taunters) => {
      const sig = [...inArea].sort().join('|');
      const hit = aoeBonusCache.get(sig);
      if (hit !== undefined) return hit;
      let v = 0;
      const foes = [...inArea].map(k => pos.get(k)).filter(x => x && x.side !== unit.side);
      for (const f of foes) {
        const pct = f.hp / Math.max(1, maxHpOf(f));
        if (pct < 0.3) v += 26;                          // dyingCount
        else if (pct < 0.7) v += 14;                     // hurtedCount / weakCount
        if (taunters.includes(f)) v += 12;               // tauntCount
        if (manhattan(f, target) <= 1) v += 4;           // nearEnemy
      }
      v += foes.length * 3;                             // unit_num
      aoeBonusCache.set(sig, v);
      if (aoeBonusCache.size > 4000) aoeBonusCache.clear();
      return v;
    };
    // [失焦] is the client FADE speciality (buff 6544 → spec 20523), carried
    // by 菲娜塔's「虚空造物」虚空投影 personality. Enemies prefer ANY other
    // target; a faded unit is only attacked when nothing else is available.
    const isFaded = (u, viewer) => !!viewer && u.side !== viewer.side &&
      unitSpecs(u).some(i => i.spec.t === 'FADE' && cond(i, {}));
    // A skill that intends to DAMAGE enemies must never be cast at a tile /
    // area containing none. Client signals: skill.target_type 2/3/5, a
    // client-parsed plan.fx containing 伤害, or a non-utility damage type.
    function damageIntent(s) {
      if (anyUnitAim(s)) return false;   // teleport/support: no enemy required
      // dt=3 is 治疗: it targets FRIENDLIES (affects() returns same-side).
      // Requiring an enemy inside the AOE made every heal / buff AOE
      // unreachable for the AI — 珀列维特's 「神泽」/「命途所至」 could never
      // be cast even though the client offers them on turn 1.
      if (s.dt === 3) return false;
      if (followDamage(s)) return true;   // damage on an idskill_follow segment
      if (!isUtility(s)) return true;
      // Self / ally-targeted status skills (迎风持盾, 灵光一闪的傲人智慧 …)
      // are buffs, not attacks — target_type 3 is 「自身范围内」in the client.
      if (s.aim === 'self' || s.aim === 'ally') return false;
      const hasAoe = (s.sp || []).some(x => M?.specs?.[x]?.t === 'AOE');
      return s.ttp === 2 && hasAoe &&
        (skillPlan(s)?.fx || []).some(x => /伤害/.test(String(x)));
    }
    // A walkable tile with no live unit and no interactive object. The
    // caster's own stand tile is excluded: you cannot summon onto yourself.
    function emptyTileOk(unit, standKey, target) {
      if (!target || !Number.isFinite(target.x)) return false;
      const c = grid.at(target.x, target.y);
      if (!c || !c.walk || c.pit || key(target.x, target.y) === standKey) return false;
      if (units.some(u => u.alive && u.x === target.x && u.y === target.y)) return false;
      if (placed.some(o => o.alive && o.x === target.x && o.y === target.y)) return false;
      return true;
    }
    // A PLACE_UNIT summon that grants EXTEND_CAST_RANGE is a 「施法锚点」: the
    // caster casts THROUGH it, so its effective reach is the caster's own
    // longest damage skill measured FROM the summon's tile. 菲娜塔「召唤·虚空
    // 投影」21721 → 虚空投影 8644 → 个性 21731 → 射程延拓 8983/#29560. The
    // client does not place such an anchor when no enemy can be reached from
    // that tile; doing so would waste the once-per-battle summon.
    const anchorCache = new Map();
    function isCastAnchorSummon(id) {
      if (anchorCache.has(id)) return anchorCache.get(id);
      let anchor = false;
      const sm = M?.summons?.[id];
      const seen = new Set();
      const walkSpec = sid => {
        if (seen.has(sid)) return;
        seen.add(sid);
        const q = M?.specs?.[sid];
        if (!q) return;
        if (q.t === 'EXTEND_CAST_RANGE') { anchor = true; return; }
        if ((q.t === 'BUFF' || q.t === 'AURA') && q.p?.[0] && M?.buffs?.[q.p[0]])
          for (const b of M.buffs[q.p[0]].sp || []) walkSpec(b);
      };
      for (const sid of (sm?.kit?.personality || [])) for (const q of (M?.skills?.[sid]?.sp || [])) walkSpec(q);
      for (const sid of (sm?.kit?.feature || [])) for (const q of (M?.skills?.[sid]?.sp || [])) walkSpec(q);
      anchorCache.set(id, anchor);
      return anchor;
    }
    const anchorReachCache = new Map();
    const isAnchorSummonSkill = s => (s.sp || []).some(sid => {
      const q = M?.specs?.[sid];
      return q?.t === 'PLACE_UNIT' && isCastAnchorSummon(q.p?.[0]);
    });
    function anchorPlacementUseful(unit, s, target, stand) {
      if (!isAnchorSummonSkill(s)) return true;
      const foes = units.filter(f => f.alive && f.side !== unit.side);
      if (!foes.length) return true;
      // Use the TEMPLATE range (client #29560 reads `skill.range_max`), never
      // rangeMods(): the +2 there IS the anchor extension we are deciding
      // whether to create, so counting it would be circular.
      const ck = unit.uid + '|' + s.id + '|' + sim.epoch;
      let reach = anchorReachCache.get(ck);
      if (reach === undefined) {
        reach = 0;
        for (const q of unit.skills || [])
          if (q.id !== s.id && damageIntent(q)) reach = Math.max(reach, q.rmax || 0);
        anchorReachCache.set(ck, reach);
      }
      if (!reach) return true;
      const origin = stand || unit;
      const dx = Math.abs(target.x - origin.x), dy = Math.abs(target.y - origin.y);
      // Client #29560「直线次元飞弹射程内有己方裂隙才能延拓」: getLineBlocks
      // only walks STRAIGHT lines out to `次元飞弹.range_max`. An off-line
      // 裂隙 grants no extension, so placing it there wastes the summon.
      if (!(dx === 0 || dy === 0 || dx === dy) || manhattan(origin, target) > reach) return false;
      return foes.some(f => manhattan(f, target) <= reach &&
        !blocked(target, grid.at(f.x, f.y), s, unit.side));
    }

    function evaluate(unit, s, standKey, stand, target, taunters) {
      if (blocked(stand, target, s, unit.side)) return null;
      if (s.cp && !castTargetOk(unit, s, target, stand)) return null;
      if (!anchorPlacementUseful(unit, s, target, stand)) return null;
      // Client 「在目标[空地]召唤 / 放置」 (菲娜塔「召唤·虚空投影」21721,
      // 冰墙, 投掷炸弹 …): the chosen tile must be genuinely EMPTY — no live
      // unit, no interactive object, and walkable (NOT 禁行 / 深坑).
      if (s.eg && !emptyTileOk(unit, standKey, target)) return null;
      const area = areaCells(stand, target, s, displayAreaOf(s));
      const inArea = new Set(area.map(c => key(c.x, c.y)));
      const pos = new Map(units.filter(u => u.alive && u !== unit).map(u => [key(u.x, u.y), u]));
      pos.set(standKey, unit);
      if (damageIntent(s) && ![...inArea].some(k => {
        const u = pos.get(k);
        // [隐身]「无法被敌人技能选中」: an invisible enemy alone is NOT a
        // legal auto-selected target. AOE splash still resolves via hitsUnit()
        // at cast time, which is exactly the client's 可被范围伤害波及.
        return u && u.side !== unit.side && hitsUnit(s, unit, u) &&
          !isFaded(u, unit) && !isInvisibleTo(u, unit);
      })) return null;
      const tgt = pos.get(key(target.x, target.y));
      if (anyUnitAim(s)) {
        // The teleport anchor is any unit / object in range, including the
        // caster's own tile. An empty tile is fine too (the client lands on
        // a free block next to the anchor).
      } else {
        if (s.aim === 'enemy' && (!tgt || tgt.side === unit.side || isInvisibleTo(tgt, unit))) return null;
        if (s.aim === 'ally' && (!tgt || tgt.side !== unit.side)) return null;
      }
      const ox = unit.x, oy = unit.y;
      unit.x = stand.x; unit.y = stand.y;
      let score = 0, n = 0;
      for (const k of inArea) {
        const u = pos.get(k);
        if (!u || !hitsUnit(s, unit, u)) continue;
        if (s.dt === 3) {
          const missing = maxHpOf(u) - u.hp;
          // A 「治疗」 skill is often ALSO a buff skill: 「神泽」 heals 30%
          // AND grants [移动1] / immunities, 「命途所至」 grants 霜佑之印 +
          // two random tier-2 buffs + dispels. The client AI still casts them
          // at full HP for the buffs. Valuing dt=3 purely by missing HP made
          // 珀列维特 pick 默祷 over 神泽 and skipped the whole heal kit on
          // turn 1. Score the non-heal specialities even when nobody is hurt.
          const buffValue = effectValue(s, unit, u, {skipHeal: true});
          if (missing <= 0) {
            if (buffValue <= 0) continue;
            score += buffValue; n++;
          } else {
            score += Math.min(missing, computeDamage(unit, u, s, {}, {expected: true}).amount) * 1.15
                   + buffValue;
            n++;
          }
        } else if (isUtility(s)) {
          const v = effectValue(s, unit, u);
          // Even a pure AOE / field / summons skill should be considered;
          // 12 points is far below a real attack, so it never outbids damage.
          score += Math.max(v, 12); n++;
          // A df-0 command skill deals its damage through skill_cast_id
          // follow-ups (将杀 4×100%, 摧城 160%, 全装甲集火号令！80% 穿透).
          // Value that damage on enemies; single-target follow-ups only count
          // on the selected unit.
          if (u.side !== unit.side) {
            for (const cs of castChainOf(s)) {
              if (!(cs.df > 0) || ![1, 2, 4].includes(cs.dt)) continue;
              const single = !cs.area || cs.area.type === 'single';
              if (single && u !== tgt) continue;
              const e = computeDamage(unit, u, cs, {}, {expected: true}).amount;
              score += Math.min(e, u.hp + armorOf(u, 'phys') + armorOf(u, 'spell'));
            }
          }
        } else {
          // Expected value must cover the FULL client chain, not just the
          // head skill's damage_factor. 「百无禁忌」是 40% + 100%; valuing it
          // as 40% made the AI systematically underrate composite skills.
          const segs = damageSegmentsOf(s, true);   // AI: total client damage, incl. scid chain
          const onSegs = segs && (segs.length > 1 ||
            segs.some(sg => sg.chainSkill && Number(sg.chainSkill) !== Number(s.id)));
          const exp = onSegs
            ? segs.reduce((sum, sg) => sum + computeDamage(unit, u, segSkillOf(s, sg), {},
                {expected: true, factorOverride: sg.factor,
                 hitsOverride: sg.hitsOverride ?? 1}).amount, 0)
            : computeDamage(unit, u, s, {}, {expected: true}).amount;
          let val = Math.min(exp, u.hp + armorOf(u, 'phys') + armorOf(u, 'spell'));
          if (exp >= u.hp) val += 250 + maxHpOf(u) * 0.25;
          if (isFaded(u, unit)) val *= 0.05;   // [失焦] — prefer other targets
          if (taunters.length) val *= taunters.includes(u) ? 2.5 : 0.35;
          score += val + effectValue(s, unit, u) * 0.5;
          // Prefer finishing wounded targets rather than spreading damage.
          if (u.side !== unit.side && u.hp < maxHpOf(u) * 0.5) score += 30;
          n++;
        }
      }
      unit.x = ox; unit.y = oy;
      if (!n) return null;
      // `target_order_param` is a per-target Lua priority in the client.
      if (s.top) score += AI_LUA(s.top, unit, s, {target: tgt || target, defender: tgt || target});
      score += (s.ord || 0) * 2 - tpCost(unit, s) * 6;
      if (SUB?.skillTags?.length) score += (TAG_W[skillTag(s)] || 0) * 0.6;
      // Client Logic_AI_Skill_List_Tag: BUFF_FRIEND (28) outranks TO_ENEMY
      // (12) and NORMAL_ATTACK (4). 「戍卫箭幕」 opens a 警戒 zone for the
      // whole team; on turn 1 that setup is worth far more than one basic
      // hit, but a raw damage score (~9000) dwarfed the 0.6x tag weight and
      // made 法卡尔·SP follow 「强击姿态」 with 「连射」. Scale the declared
      // tag rank by a configurable factor for the opening setup only.
      const setupSkill = (s.sp || []).some(sid => {
        const t = M?.specs?.[sid]?.t;
        return t === 'ALERT_ATTACK' || t === 'CAN_NOT_TRIGGER_AI';
      });
      if (setupSkill && round <= 1)
        score += (TAG_W.BUFF_FRIEND || 28) * Number(SKILL_PRIO.setupTagStep || 320);
      // Later phases of a [瞬发] chain should still open a STANCE / personality
      // skill before attacking. A skill is a stance when its BUFF grants an
      // extra skill or replaces a slot (潜袭 → 潜袭形态 / 取消潜袭, 强击姿态 →
      // 机动姿态), or when the client declares a swapTo. Soft priority only:
      // the rest of all_skill_list keeps competing on expected value.
      if ((sim.decidePhase?.chainIndex || 0) > 0 && unit.instantIds?.has(Number(s.id))) {
        const stance = !!skillPlan(s)?.swapTo || (s.sp || []).some(sid => {
          const sp = M?.specs?.[sid];
          if (sp?.t !== 'BUFF') return false;
          return (M.buffs?.[sp.p?.[0]]?.sp || []).some(bs =>
            ['GET_EXTRA_SKILL', 'REPLACE_SKILL'].includes(M?.specs?.[bs]?.t));
        });
        if (stance) score += Number(SKILL_PRIO.stanceBonus || 6000);
      }
      // Client AoePosition scoring fields (weakCount / hurtedCount / dyingCount
      // / nearEnemy / tauntCount / unit_num / props_num ...): prefer AOE casts
      // that cover weakened, wounded and nearby enemies.
      if ((inArea.size || 0) > 1 && SUB?.aoeFields?.length) {
        score += aoeBonus(inArea, pos, unit, target, taunters);
      }
      // Client `ai_order_param` gives some skills an explicit priority;
      // `ai_move_close` marks skills whose owner should close in afterwards.
      score += (sim.aiPriority && sim.aiPriority.get(s.id)) || 0;
      // ai_move_close = close / stay / default steers the post-cast approach.
      if (s.amc === 'stay') score -= 3;
      else if (s.amc === 'close') score += 3;
      // Keep enough energy for a stronger ready skill.
      const tp = unit.tp - tpCost(unit, s);
      if (tp <= 0 && unit.skills.some(x => x !== s && usable(unit, x) && (x.ord || 0) > (s.ord || 0))) score -= 12;
      return {score, area};
    }
    const propSkill = s => (s.sp || []).some(sid =>
      /Battle\.Entity\.Type\.Props/.test(M?.specs?.[sid]?.c || ''));
    // The decrypted AIMachine declares `skill_by_order`, `skill_orders`,
    // `cur_skill`, `skill_list_tag`, `skill_move_mode`, `ai_move_close`,
    // `move_steps`, `alert_dist`, `alert_points`, `prev_block_min` and the
    // ordered castPipeline. Everything below is driven by those columns
    // instead of hard-coding individual characters.
    const AI_LUA = (src, unit, skill, extra) => {
      if (!src) return 0;
      const inst = {spec: {t: 'AI_ORDER'}, owner: unit, src: 'skill', skill};
      const r = Lua.evaluate(src, luaEnv(inst, Object.assign({attacker: unit, skill}, extra || {}), true));
      if (r.unknown) return 0;
      const n = Number(r.v);
      return Number.isFinite(n) ? n : 0;
    };
    // `all_skill_list` is EVERY castable skill. A 抉择 (SKILL_GROUP) option
    // inherits the declared slot of its parent group, so the client's
    // `skill_orders` priority applies to the real castable skills too.
    const choiceParent = (unit, s) => {
      for (let i = 0; i < (unit.ai?.order || []).length; i++) {
        const id = unit.ai.order[i];
        if (Number(id) === Number(s.id)) return -1;
        if (choiceOptions(unit, id).some(x => Number(x) === Number(s.id))) return i;
      }
      return -1;
    };
    const skillOrderIndex = (unit, s) => {
      const o = unit.ai?.order || [];
      const i = o.indexOf(Number(s.id));
      if (i >= 0) return i;
      const parent = choiceParent(unit, s);
      if (parent >= 0) return parent;
      return 1000 + (unit.skills || []).indexOf(s);
    };
    // ai_skill_by_order / boss_skill_sequence: the client keeps a `cur_skill`
    // index and offers ONE declared skill per action. `skill_orders` and
    // `all_skill_list` are the decrypted AIMachine fields. A 抉择 (SKILL_GROUP)
    // slot offers its options; a passive slot offers no cast at all, so the
    // unit falls through to MOVE_OR_IDLE instead of free-firing its best nuke.
    function choiceOptions(unit, groupId) {
      const rec = (unit.passiveSkills || []).find(s => Number(s.id) === Number(groupId)) || skillRec(groupId);
      const out = [];
      for (const sid of rec?.sp || []) {
        const sp = M?.specs?.[sid];
        if (!sp || (sp.t !== 'SKILL_GROUP' && sp.t !== 'TACTICS_SKILL_GROUP')) continue;
        for (const id of sp.p || []) if (id && !out.includes(id)) out.push(id);
      }
      return out;
    }
    // Only `boss_skill_mode` units cycle a `boss_skills` sequence via
    // `cur_skill`. `ai_skill_by_order` / `skill_orders` is a PRIORITY order
    // over `all_skill_list`, not a filter that removes every other skill.
    function bossRotation(unit, ready) {
      if (!unit.ai?.bossMode || !(unit.ai?.sequence || []).length) return null;
      const list = unit.ai.sequence, n = list.length;
      const cur = (unit.ai.cursor || 0) % n;
      for (let k = 0; k < n; k++) {
        const id = list[(cur + k) % n];
        const direct = ready.find(s => Number(s.id) === Number(id));
        if (direct) return {skills: [direct], id};
        const opts = choiceOptions(unit, id).map(x => ready.find(s => Number(s.id) === Number(x))).filter(Boolean);
        if (opts.length) return {skills: opts, id, group: true};
      }
      return null;
    }
    // ai_skill_sorted: sort by the client's `ai_skill_order` column.
    function orderedSkills(unit, ready) {
      const list = ready.slice();
      if (unit.ai?.sorted) list.sort((a, b) => (b.ord || 0) - (a.ord || 0)
        || skillOrderIndex(unit, a) - skillOrderIndex(unit, b));
      return list;
    }
    // Decrypted Logic_AI_AIMachine declares an ordered comparator pipeline and
    // a target-sort list. The engine used to hardcode a chain that referenced
    // `skill.smm` (a field the client table does not export) and ignored 9 of
    // the 10 target comparators. Build the comparator table once and let the
    // DECLARED order drive tie-breaking; target quality also feeds a small,
    // configurable score weight (`targetSortWeight`).
    const smmOf = s => (s.amc === 'close' || selfMoveOf(s, M?.specs)) ? 2
      : s.amc === 'away' ? 1 : 0;
    function decide(unit, reachOverride) {
      const reach = reachOverride || reachable(unit);
      const chainIndex = sim.decidePhase?.chainIndex || 0;
      const areaUnits = c => (c.area || []).map(cell =>
        units.find(u => u.alive && u.x === cell.x && u.y === cell.y)).filter(Boolean);
      const hpRatio = u => u.hp / Math.max(1, maxHpOf(u));
      const foesIn = c => areaUnits(c).filter(u => u.side !== unit.side);
      const friendsIn = c => areaUnits(c).filter(u => u.side === unit.side);
      const weakest = c => { const f = foesIn(c); return f.length ? Math.min(...f.map(hpRatio)) : 1; };
      const taunted = c => foesIn(c).some(u => unitSpecs(u).some(i => i.spec.t === 'TAUNT')) ? 1 : 0;
      const hurt = c => { const f = foesIn(c); return f.length ? 1 - Math.min(...f.map(hpRatio)) : 0; };
      const healNeed = c => { const f = friendsIn(c); return f.length ? Math.max(...f.map(u => 1 - hpRatio(u))) : 0; };
      const dying = c => foesIn(c).some(u => u.hp <= Math.max(1, (c.score || 0) * 0.2)) ? 1 : 0;
      const countN = c => Math.min(1, (c.covered || 1) / 4);
      const quadrant = (stand, tgt) => (stand.x >= tgt.x ? 2 : 0) + (stand.y >= tgt.y ? 1 : 0);
      const METRICS = {
        sortByWeak: c => 1 - weakest(c), sortByTaunt: c => taunted(c),
        sortByHurt: c => hurt(c), sortByHurtHeal: c => healNeed(c),
        sortByDying: c => dying(c), sortByCount: countN, sortByCountNoFade: countN,
        sortByPropsCountNoFade: c => c.prop ? 1 : 0,
        sortByNearEnemy: c => Math.max(0, 1 - (c.foeDist ?? 99) / 10),
        sortByPosition: c => c.straight ? 0 : 1,
      };
      const COMPARATORS = {
        getQuadrant: (a, b) => quadrant(a.stand, a.target) - quadrant(b.stand, b.target),
        posCompare: (a, b) => (a.stand.x + a.stand.y) - (b.stand.x + b.stand.y),
        sortBySkillMoveMode: (a, b) => smmOf(b.skill) - smmOf(a.skill),
        filterByMinMoveDist: (a, b) => a.cost - b.cost,
        sortByMoveAndTargetDist: (a, b) =>
          (a.cost + manhattan(a.stand, a.target)) - (b.cost + manhattan(b.stand, b.target)),
        sortByWeak: (a, b) => weakest(a) - weakest(b),
        sortByTaunt: (a, b) => taunted(b) - taunted(a),
        sortByPosition: (a, b) => (a.straight || 0) - (b.straight || 0)
          || (a.lateral || 0) - (b.lateral || 0),
        sortByHurt: (a, b) => hurt(b) - hurt(a),
        sortByHurtHeal: (a, b) => healNeed(b) - healNeed(a),
        sortByDying: (a, b) => dying(b) - dying(a),
        sortByCount: (a, b) => (b.covered || 1) - (a.covered || 1),
        sortByPropsCountNoFade: (a, b) => (b.prop ? 1 : 0) - (a.prop ? 1 : 0),
        sortByCountNoFade: (a, b) => (b.covered || 1) - (a.covered || 1),
        sortByNearEnemy: (a, b) => (a.foeDist ?? 99) - (b.foeDist ?? 99),
      };
      const pipeline = (SUB?.castPipeline || []).filter(n => COMPARATORS[n]);
      const compareByPipeline = (a, b) => {
        for (const name of pipeline) { const v = COMPARATORS[name](a, b); if (v) return v; }
        return (a.stand.x + a.stand.y) - (b.stand.x + b.stand.y);
      };
      const targetSorts = SUB?.targetSorts || [];
      const targetQuality = c => {
        let v = 0;
        for (let i = 0; i < targetSorts.length; i++) {
          const fn = METRICS[targetSorts[i]];
          if (fn) v += (targetSorts.length - i) * fn(c);
        }
        return v;
      };
      sim.castComparators = pipeline.slice();
      // AIMachine DO_SKILL builds cast blocks from `all_skill_list`: every
      // usable skill whose own activation condition currently holds. The
      // declared `skill_orders` only sets the evaluation priority. A [瞬发]
      // skill already used in this action is not offered again (its cd can be
      // 0), otherwise MOVE_OR_IDLE would loop on the same free cast forever.
      // ACTED_ACT / RE_ROUND with p[0] restricts the extra action to ONE
      // client-declared skill. `sim.extraSkill` is set for the duration of
      // that action by takeTurn(); a normal turn never sees it.
      const onlySkill = sim.extraSkill && sim.extraSkillUnit === unit.uid
        ? Number(sim.extraSkill) : 0;
      // 静聆神谕: this action is restricted to one member of the client's
      // forced-choice group (or 待机). The group is consumed by the first cast.
      const choiceGroup = !onlySkill && Array.isArray(unit.flags.choiceGroup) && unit.flags.choiceGroup.length
        ? unit.flags.choiceGroup : null;
      const ready = unit.skills.filter(s => usable(unit, s) && !s.isChoiceGroup &&
        !(unit.flags.instantUsed?.has(Number(s.id))) &&
        (!onlySkill || Number(s.id) === onlySkill) &&
        (!choiceGroup || choiceGroup.includes(Number(s.id))) &&
        activationOk(s, {spec: {t: 'ACTIVATION'}, owner: unit, src: 'skill', skill: s},
                     {attacker: unit, skill: s, target: null}));
      sim.extraSkillUsed = onlySkill || 0;
      const boss = bossRotation(unit, ready);
      const ordered = boss ? boss.skills : orderedSkills(unit, ready);
      const declared = unit.ai?.byOrder ? ordered.slice().sort(
        (a, b) => skillOrderIndex(unit, a) - skillOrderIndex(unit, b)) : ordered;
      sim.allSkillList = ready.map(s => Number(s.id));
      sim.curSkill = unit.ai?.cursor || 0;
      const taunters = enemiesOf(unit).filter(e => unitSpecs(e).some(i => i.spec.t === 'TAUNT'));
      const foesNow = enemiesOf(unit);
      const baseFoeDist = foesNow.length
        ? foesNow.reduce((m, f) => Math.min(m, manhattan(f, unit)), 99) : 99;
      const rangePair = rangeMods(unit, false);   // independent of stand / skill
      // Conditional SKILL_RANGE rows (e.g. 后备隐藏脂肪 on 11495) need the
      // skill in their activation context, so compute the pair per skill once.
      const rangePairBySkill = new Map(declared.map(s => [s.id, rangeMods(unit, false, s)]));
      const candidates = [];
      const aiPriority = sim.aiPriority = new Map();
      for (const s of declared) {
        // ai_order_param returns an explicit priority (e.g. 2000, -10000);
        // declared skill order adds a large deterministic bonus.
        const lua = AI_LUA(s.aop, unit, s);
        // `skill_orders` + `cur_skill`: the declared order is a CYCLIC
        // priority starting at the current cursor. Every skill remains a
        // candidate — the cursor never excludes one. When the preferred
        // declared skill has no cast block, the rest of `all_skill_list`
        // (including the basic attack) competes on expected value, which is
        // how the client eventually pops its own 呆呆雪人.
        // `cur_skill` names ONE declared slot. That slot gets priority; if it
        // has no castable block (e.g. a passive slot), the rest of
        // `all_skill_list` competes on expected value. This is why the client
        // eventually uses its basic attack to pop its own 呆呆雪人.
        const idx = skillOrderIndex(unit, s);
        const n = (unit.ai?.order || []).length || 1;
        const cur = (unit.ai?.cursor || 0) % n;
        const bonus = unit.ai?.byOrder && idx === cur ? 2600
          : (unit.ai?.byOrder && idx < 100 ? Math.max(0, 520 - idx * 40) : 0);
        // Client Logic_AI_Skill_List_Tag: personality / carried / basic are
        // three DIFFERENT priority groups (NORMAL_ATTACK is the lowest tag).
        // Inside one group the 技能放置顺序 (skill_orders) breaks ties, so a
        // reorderable skill bar changes which skill wins when scores are near.
        const tier = unit.skillTier?.get(Number(s.id)) || 'carried';
        const slot = unit.slotOrder?.indexOf(Number(s.id)) ?? -1;
        const tierBonus = tierRank(tier) * Number(SKILL_PRIO.tierStep || 0);
        const slotBonus = tier === 'carried' && slot >= 0
          ? (unit.slotOrder.length - slot) * Number(SKILL_PRIO.slotStep || 0) : 0;
        // A [瞬发] skill does not end the action; use it first while the whole
        // action is still available, then continue with the main skill.
        const instantBonus = chainIndex === 0 && unit.instantIds?.has(Number(s.id))
          ? Number(SKILL_PRIO.instantBonus || 0) : 0;
        // 「静聆神谕」 forced-choice group: `ai_skill_order` is the declared
        // order in which the client offers the three skills. Honour it as a
        // real priority (not a +2 tie-break) so 神泽 (12) beats 默祷 (11)
        // when both have legal blocks. Still bounded so a member that cannot
        // be cast never wins — candidates are filtered by geometry first.
        const choiceBonus = choiceGroup?.includes(Number(s.id))
          ? (choiceGroup.length - choiceGroup.indexOf(Number(s.id))) * 45 : 0;
        aiPriority.set(s.id, (lua || 0) + bonus + tierBonus + slotBonus + instantBonus + choiceBonus);
      }
      // Client 「若目标为[呆呆雪人]…再被摧毁」: a skill whose activation
      // condition names Props can aim at an attackable object on the board.
      const propsAlive = placed.filter(o => o.alive && o.attackable && o.kind === 'PLACE_ITEM');
      if (propsAlive.length) for (const s of ready.filter(propSkill)) {
        // The prop is a cast TARGET too, so it must satisfy the same
        // range_select shape (十字 / 单向线 / 矩形 … cannot aim diagonally).
        const propShape = castShape(s);
        const propOffsets = WHOLE_FIELD_SHAPES.has(propShape) ? null
          : castRangeCells(s, s.rmin || 0, Math.max(1, s.rmax || 1) + (rangePair[1] || 0));
        for (const [standKey, node] of reach) {
          if (node.blocked) continue;
          const stand = node.cell;
          for (const o of propsAlive) {
            const d = manhattan(stand, o);
            if (d < (s.rmin || 0) || d > Math.max(1, s.rmax || 1)) continue;
            const pdx = o.x - stand.x, pdy = o.y - stand.y;
            if (propOffsets && !propOffsets.some(([ox, oy]) => ox === pdx && oy === pdy)) continue;
            if (blocked(stand, grid.at(o.x, o.y), s, unit.side)) continue;
            const cell = grid.at(o.x, o.y);
            // `sortByPropsCountNoFade` is a declared castPipeline comparator:
            // blocks covering an attackable prop outrank blocks that do not,
            // weighted by the comparator's own declaration order in the
            // decrypted AIMachine. Every cast block also carries its skill's
            // `ai_order_param` / `skill_orders` priority.
            const sorts = SUB?.targetSorts || [];
            const order = sorts.indexOf('sortByPropsCountNoFade');
            const propsWeight = (sorts.length - Math.max(0, order)) * 400;
            candidates.push({skill: s, standKey, stand, target: cell, area: [cell],
              score: 220 + o.hp * 0.05 + propsWeight + (aiPriority.get(s.id) || 0),
              cost: node.cost, prop: o, propsNoFade: true});
          }
        }
      }
      for (const [standKey, node] of reach) {
        if (node.blocked) continue;
        const stand = node.cell;
        const occupied = new Set(units.filter(z => z.alive && z !== unit).map(z => key(z.x, z.y)));
        for (const o of placed) if (o.alive && o.collidable) occupied.add(key(o.x, o.y));
        for (const s of declared) {
          // JUMP_MOVE / TARGET_TELEPORT (「烟幕游击」) must land on an EMPTY
          // ground cell; teleporting onto an ally is not a client cast block.
          // SHADOW_STEP (暗步「对目标传送」) on an ENEMY-targeted skill is the
          // opposite: the cast block IS the enemy and the caster lands next to
          // / behind it (将杀, 瞬身袭, 落花之舞). Treating it as a ground jump
          // skipped every enemy tile and made those skills hit empty cells.
          const jumpGround = (s.sp || []).some(sid => {
            const ty = M?.specs?.[sid]?.t;
            return ty === 'JUMP_MOVE' || ty === 'TARGET_TELEPORT' ||
              (ty === 'SHADOW_STEP' && s.aim !== 'enemy');
          });
          for (const target of targetCells(stand, s, unit, false,
                   rangePairBySkill.get(s.id) || rangePair)) {
            if (jumpGround && (occupied.has(key(target.x, target.y)) || key(target.x, target.y) === standKey)) continue;
            // Client 「仅能对空地使用」: skip occupied / unwalkable / pit tiles
            // BEFORE the fallback scorer, which must never override an illegal
            // tile (it used to pick 「禁行」深坑 and then summon nothing).
            if (s.eg && !emptyTileOk(unit, standKey, target)) continue;
            // 烟幕游击's JUMP_MOVE is a straight cardinal line of exactly
            // p[0] blocks. Filtering the landing cells here (rather than
            // adding a score bonus) is a legality rule, so it cannot be
            // outvoted by unrelated scoring terms.
            const cj = concealFieldOf(s) ? concealJumpSpec(s) : null;
            if (cj && (!(target.x === stand.x || target.y === stand.y) ||
                       manhattan(stand, target) !== (Number(cj.p?.[0]) || 3))) continue;
            // Client skill.cast_param (target legality) gates BOTH evaluate()
            // and the ground fallback below: 游击 may only pick a friendly 枪影.
            if (s.cp && !castTargetOk(unit, s, target, stand)) continue;
            let r = evaluate(unit, s, standKey, stand, target, taunters);
            // A cast-anchor summon that cannot bring any enemy within the
            // caster's template range is not worth placing (client: 「自身可
            // 透过[虚空投影]…释放技能」). Gate the fallback as well, otherwise
            // it re-creates exactly the block evaluate() just rejected.
            if (!anchorPlacementUseful(unit, s, target, stand)) continue;
            // An empty-tile cast (JUMP_MOVE landing, or 「在目标[空地]召唤」)
            // has NO unit in its area, so evaluate() finds no affected target
            // and returns null. The CASTER is the beneficiary: score the tile
            // itself. 虚空投影 / 冰墙 / 投掷炸弹 would otherwise NEVER be cast
            // after the client 「仅能对空地使用」 constraint was enforced.
            const groundCast = jumpGround || s.eg;
            if (!r && groundCast && (!s.eg || emptyTileOk(unit, standKey, target))) {
              const foes = units.filter(f => f.alive && f.side !== unit.side);
              // A ground-targeted JUMP_MOVE + AOE skill (陷阵·锐意承锋:
              // 射程1-4, 自身范围3格菱形) must pick the landing block that
              // covers the MOST enemies. The old fallback scored only the
              // distance from the landing tile to the nearest foe and set
              // area = [target], so sortByCount / covered was always 1 and
              // the AI jumped to an empty corner instead of into the crowd.
              const blast = s.area?.type === 'aoe' ? areaCells(stand, target, s, displayAreaOf(s)) : [target];
              const covered = blast.reduce((n, c) => n +
                foes.filter(f => f.x === c.x && f.y === c.y).length, 0);
              // The fallback exists for the caster-benefit part (landing /
              // summoning). A DAMAGE skill whose blast covers no enemy is not
              // a client cast block at all — evaluate() already rejected it
              // for that reason; scoring it anyway made 伦伽勒·SP jump
              // 陷阵·锐意承锋 onto empty ground and hit nobody.
              if (damageIntent(s) && covered === 0) continue;
              const landingDist = foes.reduce((m, f) => Math.min(m, manhattan(f, target)), 99);
              // 烟幕游击 lands the caster IN a [隐身] tile. Record how many
              // foes the follow-up 普攻 could hit FROM that tile (staying in
              // cover). This is kept on the candidate for the replay panel,
              // NOT folded into `score`: an absolute cover-attack bonus would
              // outvote the client's `filterByMinMoveDist` and force a full
              // walk in other battles. The straight-line JUMP_MOVE legality
              // + posCompare below already select 科尔 (9,6) → (6,6).
              let coverAttack = 0;
              if (concealFieldOf(s)) {
                for (const q of unit.skills || []) {
                  if (!damageIntent(q) || (unit.cd?.[q.id] || 0) > 0) continue;
                  const [mn, mx] = rangeMods(unit, false, q);
                  const lo = Math.max(0, (q.rmin || 0) + mn), hi = Math.max(lo, (q.rmax || 0) + mx);
                  if (hi <= 0) continue;
                  for (const f of foes) {
                    const d = manhattan(target, f);
                    if (d < lo || d > hi || !hitsUnit(q, unit, f)) continue;
                    if (blocked(target, grid.at(f.x, f.y), q, unit.side)) continue;
                    coverAttack++;
                  }
                }
              }
              // Client `posCompare` orders cast blocks by (x + y): among
              // legal conceal-jump landings prefer the one closest to the
              // enemy formation's upper-left, i.e. 科尔 (9,6) → (6,6) rather
              // than a same-distance jump back toward its own spawn.
              const posOrder = concealFieldOf(s) && jumpGround
                ? (target.x + target.y + stand.x + stand.y) *
                  Number(SKILL_PRIO.coverPosStep || 3) : 0;
              r = {score: 40 + effectValue(s, unit, unit) * 0.6
                        + covered * Number(SKILL_PRIO.aoeCoverStep || 220)
                        + Math.max(0, 14 - landingDist) + target.h * 0.2 - node.cost * 0.5
                        - posOrder
                        + ((sim.aiPriority && sim.aiPriority.get(s.id)) || 0),
                   area: blast, coverAttack};
            }
            if (!r) continue;
            // Ranged / fragile units prefer tiles out of enemy reach; wounded
            // units value safety more. Deterministic, no RNG consumed.
            const foes = units.filter(f => f.alive && f.side !== unit.side);
            const ranged = Math.max(...unit.skills.map(x => x.rmax || 0), 0) > 1;
            const danger = foes.reduce((a, f) => {
              const d = Math.abs(f.x - stand.x) + Math.abs(f.y - stand.y);
              return a + Math.max(0, (ranged ? 4 : 2) - d);
            }, 0);
            const hpPct = unit.hp / Math.max(1, maxHpOf(unit));
            const threat = danger * (2 + (1 - hpPct) * 6) * (ranged ? 1.4 : 0.6);
            const supportAoe = s.dt === 5 && s.area?.type === 'aoe';
            const foeDist = foes.length ? foes.reduce((m, f) => Math.min(m, manhattan(f, stand)), 99) : 99;
            // AIMachine `sortByMoveAndTargetDist` -> `getQuadrant` ->
            // `sortByPosition`: among equally valuable cast blocks keep the
            // safest straight-line advance. A 3-tile straight step to (12,3)
            // beats a 3-tile detour to (11,2).
            const straight = Math.abs(stand.x - unit.x) + Math.abs(stand.y - unit.y) === node.cost ? 0 : 1;
            const covered = r.area.reduce((n, c) => n + (units.some(z => z.alive && z.x === c.x && z.y === c.y) ? 1 : 0), 0);
            // `ai_move_close` / skill_list_tag MOVE_TO: a skill that relocates
            // its own caster (JUMP_MOVE / SHADOW_STEP / CHARGE …) is resolved
            // AFTER the unit advances, so reward cast positions nearer the
            // enemy by the number of tiles gained. Without this the outer-ring
            // rule would keep 科尔 at its spawn tile and it would never walk
            // into 安娜's alert zone before 「烟幕游击」.
            const mover = selfMoveOf(s, M?.specs);
            const advance = mover ? Math.max(0, baseFoeDist - foeDist) : 0;
            const moveToBonus = advance * Number(SKILL_PRIO.moveToStep || 12);
            // `value` is the cast block's worth WITHOUT the positional
            // bonuses. The client's `filterByMinMoveDist` first keeps the
            // best-VALUE blocks, then the ones needing the LEAST movement;
            // `move_steps`/`canStay`/`stay_type` make a 0-step cast legal.
            // Keeping them separate stops moveToBonus from forcing a full
            // walk every time (科尔 used to burn all 5 mobility).
            const value = r.score - node.cost * Number(SKILL_PRIO.moveCostStep || 1.5)
              + stand.h * 0.05 - threat;
            const cand = {skill: s, standKey, stand, target, area: r.area,
                          score: value + moveToBonus, value,
                          safety: (r.area.length > 1) ? Math.min(30, foeDist) : 0,
                          foeDist, mover: !!mover, advance,
                          covered, straight,
                          lateral: Math.abs(stand.y - unit.y), cost: node.cost};
            // `targetSorts` (sortByWeak / Taunt / Hurt / HurtHeal / Dying /
            // Count / PropsCountNoFade / CountNoFade / NearEnemy / Position)
            // are declared in priority order by the client. Each contributes
            // a small rank-weighted score; the weight is configurable so the
            // effect is auditable rather than a hidden behavior change.
            cand.targetQuality = targetQuality(cand);
            cand.score += Number(SKILL_PRIO.targetSortWeight || 0) * cand.targetQuality;
            candidates.push(cand);
          }
        }
      }
      // [瞬发] is a FREE action: the client offers it in all_skill_list at
      // phase 0 even when evaluate() finds NO legal hit target. A self-buff
      // [瞬发] is a free action, but the client AI still only spends it when
      // it is WORTH something. Two very different kinds exist:
      //  · self / stance / setup (强击姿态, 潜袭, 召唤·虚空投影 …): no target
      //    to hit, so "未命中" is meaningless. These are cast at phase 0 from
      //    the current tile with zero movement.
      //  · damage openers (破阵·决厉枪袭, a 1*5 line): a miss wastes TP and CD.
      //    The client first MOVES to a stand from which the AOE actually hits
      //    an enemy, and only then casts. evaluate() already emits those
      //    moved candidates; if no reachable stand can hit, no block exists
      //    and the skill is simply not used this turn.
      // Synthesising a zero-move block for BOTH (round 53) made a damage
      // instant fire into an empty line and report 「未命中」.
      if (chainIndex === 0 && SKILL_PRIO.instantFirst !== false) {
        const stand = grid.at(unit.x, unit.y) || {x: unit.x, y: unit.y, h: 0};
        const foes = units.filter(f => f.alive && f.side !== unit.side);
        for (const s of declared) {
          if (!unit.instantIds?.has(Number(s.id))) continue;
          if (candidates.some(c => Number(c.skill.id) === Number(s.id))) continue;
          // A damage-intent skill must earn its cast through evaluate().
          if (damageIntent(s)) continue;
          const setup = (s.sp || []).some(sid => {
            const q = M?.specs?.[sid];
            return q && ((q.t === 'BUFF' && Number(q.tt) === 3) ||
              q.t === 'REPLACE_SKILL' || q.t === 'GET_EXTRA_SKILL' ||
              q.t === 'PLACE_TRAP' || q.t === 'PLACE_UNIT');
          });
          if (!setup) continue;
          let target = stand;
          const area = areaCells(stand, target, s);
          // A cast-anchor summon is only worth placing where its extended
          // casting range can actually reach an enemy (issue 1).
          if (!anchorPlacementUseful(unit, s, target, stand)) continue;
          const score = Math.max(14, effectValue(s, unit, unit, {skipHeal: true}) * 0.5);
          const standKey = key(stand.x, stand.y);
          const cand = {skill: s, standKey, stand, target, area, score, value: score,
            safety: 0, foeDist: baseFoeDist, mover: false, advance: 0, covered: 0,
            straight: 0, lateral: 0, cost: 0, freeInstant: true};
          cand.targetQuality = targetQuality(cand);
          candidates.push(cand);
        }
      }
      // Client AIMachine pipeline (decrypted from Logic_AI_AIMachine):
      //   findAllCastBlockWithTarget -> filterByMinMoveDist ->
      //   sortByMoveAndTargetDist -> getQuadrant/posCompare -> sortByPosition
      // For each (skill, target) group keep the CAST POSITIONS that need the
      // least movement, then rank by (move + target distance). This is why
      // the client steps to a nearby tile instead of running across the map
      // for a marginally better expected-damage tile.
      if (RULE.filterByMinMoveDist !== false) {
        const groups = new Map();
        for (const c of candidates) {
          const g = c.skill.id + '@' + c.target.x + ',' + c.target.y;
          const list = groups.get(g) || (groups.set(g, []), groups.get(g));
          list.push(c);
        }
        const filtered = [];
        for (const list of groups.values()) {
          // Client AoePosition scores every cast block by the units it covers
          // BEFORE filterByMinMoveDist discards redundant positions. Keeping
          // only zero-movement stands first made 乌莉娅 cast 「天降蜜果啦！」
          // in place instead of stepping to (12,3) to include herself + 3
          // allies in the AOE. Choose near-best VALUE first, then min movement.
          // AIMachine `getAoePositions` scores support AOE by covered units,
          // then `sortByPosition` keeps the safest block. Minimum movement is
          // only a tie-break for damage skills; a support caster will happily
          // spend its full movement to stand inside its own AOE (乌莉娅
          // (9,3) → (12,3), 「天降蜜果啦！」 covering herself + 3 allies).
          // Generic `sortByCount`: an AOE is valued by how many units it
          // covers; `filterByMinMoveDist` then keeps the cheapest stands
          // among the best-covering groups. No character-specific branches.
          const bestCount = Math.max(...list.map(c => c.covered || 1));
          const best = list.filter(c => (c.covered || 1) >= bestCount);
          if (best.every(c => c.area.length > 1)) {
            // AIMachine `move_steps`: a support AOE is evaluated over cast
            // blocks reachable with the unit's BASE mobility; buffed movement
            // must not drag a healer into the enemy line. Then sortByPosition
            // (safety) → getQuadrant/posCompare (straight) → posCompare.
            const budget = Number(unit.move?.mob) || 3;
            const pool = best.filter(c => c.cost <= budget);
            const use = pool.length ? pool : best;
            const bestSafety = Math.max(...use.map(c => c.safety || 0));
            const safe = use.filter(c => (c.safety || 0) >= bestSafety - 0.01);
            const minLateral = Math.min(...safe.map(c => c.straight * 10 + c.lateral));
            filtered.push(...safe.filter(c => c.straight * 10 + c.lateral === minLateral));
          } else {
            // Client `specsSkillRange` / `ReApplySkillRanges` / `BlockDist` /
            // `CastPosition` / `checkMeleeRange`: the AI casts a ranged skill
            // from the OUTER ring of its range (stand→target distance ==
            // range_max), not from the tile next to the target. This is the
            // 「走到极限距离放」behaviour: a range-5 support skill steps out
            // to 5 tiles before casting instead of casting from 3 tiles in
            // place. `sortByMoveAndTargetDist` ranks
            // the target-distance component DESCENDING; only inside that ring
            // does `filterByMinMoveDist` keep the cheapest stand.
            if (best[0]?.mover) {
              // Client `filterByMinMoveDist` / `canStay` / `stay_type`:
              // keep the best-VALUE cast blocks, then the ones needing the
              // LEAST movement. Forward progress is only a weak tie-break —
              // a character does NOT have to spend its full movement before
              // casting. Previously this branch picked max `advance`, which
              // forced 科尔 to walk all 5 tiles before 「烟幕游击」.
              const top = Math.max(...best.map(c => c.value ?? c.score));
              const tol = Number(SKILL_PRIO.castValueTolerance || 0);
              const worth = best.filter(c => (c.value ?? c.score) >= top - tol);
              const minCost = Math.min(...worth.map(c => c.cost));
              const use = worth.filter(c => c.cost <= minCost + 0.5);
              use.sort((a, b) => (a.cost + manhattan(a.stand, a.target))
                               - (b.cost + manhattan(b.stand, b.target))
                || (b.advance || 0) - (a.advance || 0)
                || (b.value ?? b.score) - (a.value ?? a.score));
              filtered.push(use[0]);
            } else {
            const castDist = c => manhattan(c.stand, c.target);
            const maxDist = Math.max(...best.map(castDist));
            const rim = best.filter(c => castDist(c) >= maxDist - 0.01);
            for (const c of rim) c.castRim = maxDist;
            const minCost = Math.min(...rim.map(c => c.cost));
            const near = rim.filter(c => c.cost <= minCost + 0.5);
            // Declared castPipeline order (decrypted from
            // Logic_AI_AIMachine). Each comparator is a strict tie-break of
            // the previous one; the LAST one is sortByNearEnemy.
            near.sort((a, b) => (a.cost + manhattan(a.stand, a.target)) - (b.cost + manhattan(b.stand, b.target))
              || (a.stand.x + a.stand.y) - (b.stand.x + b.stand.y)   // getQuadrant / posCompare
              || (b.skill.smm || 0) - (a.skill.smm || 0)              // sortBySkillMoveMode
              || (b.covered || 1) - (a.covered || 1)                  // sortByCount
              || (b.safety || 0) - (a.safety || 0)                    // sortByNearEnemy
              || (b.stand.h - a.stand.h)                              // sortByPosition
              || (a.straight || 0) - (b.straight || 0)
              || (a.lateral || 0) - (b.lateral || 0)
              || b.score - a.score);
            // `ToNextCastBlockTarget`: one cast block per (skill,target).
            filtered.push(near[0]);
            }
          }
        }
        candidates.length = 0;
        candidates.push(...filtered);
      }
      // A cast-anchor summon is a once-per-battle setup action. The client
      // only spends it when the caster can follow it with a real attack THIS
      // turn; otherwise 菲娜塔 places 虚空投影 and then merely walks (the
      // 「放了虚空投影随后只是走了几步什么也没有做」 replay). Drop the anchor
      // blocks when the engine itself found no legal damage cast block.
      if (candidates.some(c => isAnchorSummonSkill(c.skill)) &&
          !candidates.some(c => damageIntent(c.skill)))
        for (let i = candidates.length - 1; i >= 0; i--)
          if (isAnchorSummonSkill(candidates[i].skill)) candidates.splice(i, 1);
      // AoePosition scores an AOE by the units it covers, not by how far the
      // caster walked. Bucket near-equal support values so `sortByPosition`
      // (safety -> straight advance) decides rather than a 3-point movement
      // penalty; a 3-ally cast (≈330) still loses to a 4-ally cast (≈435).
      // Decrypted castPipeline comparators, applied in declaration order.
      const sortValue = c => (c.area?.length > 1) ? Math.round(c.score / 20) * 20 : c.score;
      candidates.sort((a, b) => sortValue(b) - sortValue(a)
        || (b.covered || 1) - (a.covered || 1)
        || (b.safety || 0) - (a.safety || 0)
        || (a.straight || 0) - (b.straight || 0)
        || (a.lateral || 0) - (b.lateral || 0)
        || a.cost - b.cost
        || b.score - a.score
        // Everything above is the value/position primary order; once tied,
        // the DECRYPTED comparator order decides (getQuadrant → posCompare →
        // sortBySkillMoveMode → … → sortByNearEnemy). This is the part that
        // used to be a hardcoded 3-comparator tail with a dead `skill.smm`.
        || compareByPipeline(a, b));
      // `all_skill_list`: expose EVERY candidate skill with its best cast
      // block, not only the winner. The UI shows the whole evaluation.
      const bySkill = new Map();
      for (const c of candidates) {
        const prev = bySkill.get(c.skill.id);
        if (!prev || c.score > prev.score) bySkill.set(c.skill.id, c);
      }
      const candidatesView = [...bySkill.values()].sort((a, b) => b.score - a.score).map(c => ({
        id: c.skill.id, skill: c.skill.n, score: Math.round(c.score),
        labels: skillLabels(c.skill, M),
        stand: {x: c.stand.x, y: c.stand.y}, target: {x: c.target.x, y: c.target.y},
        // A zero-range direction skill (审判诸罪之光) has FOUR distinct
        // cast blocks at the SAME tile; expose the chosen sweep so the
        // candidate list is unambiguous.
        dir: c.target.dir || null, areaN: (c.area || []).length,
        cost: c.cost, priority: Math.round(aiPriority.get(c.skill.id) || 0),
        declared: skillOrderIndex(unit, c.skill),
        tier: unit.skillTier?.get(Number(c.skill.id)) || 'carried',
        instant: !!unit.instantIds?.has(Number(c.skill.id)),
        slot: unit.slotOrder?.indexOf(Number(c.skill.id)) ?? -1,
        castDist: manhattan(c.stand, c.target),
        castRim: c.castRim ?? null,
        shape: castShape(c.skill),
        mover: !!c.mover, advance: c.advance || 0,
        targetQuality: Math.round((c.targetQuality || 0) * 100) / 100,
      }));
      const alts = candidatesView.slice(0, 8).map(c => ({skill: c.skill, score: c.score}));
      sim.candidates = candidatesView;
      // A [瞬发] skill does NOT end the action, so the client always spends
      // that free action FIRST while the whole turn is still available, then
      // continues with the main skill (流星队: 灵光一闪的傲人智慧 原地 →
      // 贯穿天际的必胜流星). Select it in the first chain phase only; the
      // `instantUsed` set prevents re-casting it in the following phase.
      // Client `filterByMinMoveDist` is also applied ACROSS target groups:
      // with several equally valuable cast blocks the unit takes the one
      // needing the fewest `move_steps` (`canStay` / `stay_type`). Without
      // this, a JUMP_MOVE caster always picked the best landing cell even
      // when reaching it consumed the whole movement budget.
      let minMovePick = null;
      if (candidates[0]?.mover) {
        const top = Math.max(...candidates.map(c => c.value ?? c.score));
        // Absolute floor + relative band, so the rule works for both a
        // low-value utility teleport and a 10k-point charge attack.
        const tolMove = Math.max(Number(SKILL_PRIO.moverMoveTolerance ?? 20),
                                 Math.abs(top) * Number(SKILL_PRIO.moverMoveTolerancePct ?? 0.01));
        // A/B switch: 0 disables the rule entirely (restores "walk full").
        if (tolMove > 0) {
        let worth = candidates.filter(c => (c.value ?? c.score) >= top - tolMove);
        // `MOVE_OR_IDLE` / `ai_move_close`: a self-displacement skill still
        // closes distance, so a 0-step block only wins when no advancing
        // block is worth considering. This is why 科尔 walks PART of the way
        // (into the alert zone) rather than all 5 tiles or not at all.
        const advancing = worth.filter(c => (c.advance || 0) >= Number(SKILL_PRIO.moverMinAdvance ?? 3));
        if (advancing.length) worth = advancing;
        const minCost = Math.min(...worth.map(c => c.cost));
        const cheap = worth.filter(c => c.cost <= minCost + 0.5);
        cheap.sort((a, b) => (b.value ?? b.score) - (a.value ?? a.score)
          || (a.cost + manhattan(a.stand, a.target)) - (b.cost + manhattan(b.stand, b.target))
          || (b.advance || 0) - (a.advance || 0));
        minMovePick = cheap[0] || null;
        }
      }
      // 「静聆神谕」: the forced-choice group is offered in the client's
      // declared ai_skill_order. Take the FIRST member that actually has a
      // legal cast block (罚斥 has no enemy in range on turn 1 → 神泽 wins),
      // rather than letting raw score pick 默祷. This is the client's
      // 「强制…选择1个使用，或执行[待机]」 semantics, data-driven by ord.
      let groupPick = null;
      if (choiceGroup) {
        for (const id of choiceGroup) {
          const own = candidates.filter(c => Number(c.skill?.id) === Number(id));
          if (own.length) { groupPick = own.sort((a, b) => b.score - a.score)[0]; break; }
        }
      }
      const pool = groupPick ? [groupPick]
        : (minMovePick ? [minMovePick, ...candidates] : candidates);
      // Phase 0 prefers a [瞬发] skill (client instantFirst). Later phases of
      // the SAME action no longer force-pick every remaining [瞬发] skill —
      // that halved unrelated battles. Instead a STANCE / personality [瞬发]
      // (潜袭, 强击姿态 …) receives a soft priority in evaluate(), so 科尔
      // still opens 「潜袭」 after 「烟幕游击」 without distorting other fights.
      const instantBest = chainIndex === 0 && SKILL_PRIO.instantFirst !== false
        ? pool.find(c => unit.instantIds?.has(Number(c.skill.id))) : null;
      const castBest = instantBest || minMovePick || candidates[0];
      // Explain WHY no skill was cast: energy / cooldown / activation vs.
      // "no legal target cell within the EFFECTIVE (buffed) range". This is
      // what makes 流星队's lost turns inspectable instead of a mystery.
      const blockedSkills = unit.skills.filter(s => !usable(unit, s));
      sim.noCastReason = candidates.length ? '' :
        (ready.length === 0
          ? `没有可用技能：${blockedSkills.length} 个技能受能量 / 冷却 / 封技 / 次数限制`
          : `${ready.length} 个技能可用，但没有合法目标格（有效射程 / 范围形状 / 可达站位）：` +
            ready.map(s => {
              const st = skillStateOf(unit, s);
              return `${s.n} ${st ? `${st.min}-${st.max}` : `${s.rmin}-${s.rmax}`}`;
            }).join('、'));
      if (candidates.length && castBest && castBest.score > 0)
        return {kind: 'skill', best: castBest, reach, alts, candidates: candidatesView,
                instantFirst: !!instantBest};
      // ACTED_ACT / RE_ROUND with p[0] grants an extra action that may ONLY
      // cast that ONE skill. If it has no legal cast block, the unit must
      // stay put: falling through to approachField() would let 野狐塞娜 walk
      // across the map (or cast a basic attack) with her 落花之舞 extra
      // action, which is exactly the "再行动还能做其他事" bug.
      if (onlySkill) {
        sim.noCastReason = `再行动限定「${skillRec(onlySkill)?.n || onlySkill}」#${onlySkill} 没有合法目标，原地待命`;
        return {kind: 'wait', moveKey: null, reach, alts};
      }
      if (choiceGroup) {
        sim.noCastReason = `强制选择组（${choiceGroup.map(id => skillRec(id)?.n || id).join(' / ')}）没有合法目标，原地待命`;
        return {kind: 'wait', moveKey: null, reach, alts};
      }
      const field = approachField(unit);
      // `alert_dist` / `move_steps` / `prev_block_min` / `offset_moves` are
      // the decrypted AIMachine fields. Every reachable block is scored once
      // by the SAME comparator chain as cast blocks, in pipeline order:
      //   sortByNearEnemy (distance field) → sortByMoveAndTargetDist
      //   → prev_block_min (spend the full movement budget) → posCompare
      //   → sortByPosition (high ground) → filterByMinMoveDist.
      const alertDist = alertReach(unit);
      const foes = units.filter(f => f.alive && f.side !== unit.side);
      const hpPct = unit.hp / Math.max(1, maxHpOf(unit));
      const rows = [];
      for (const [k, node] of reach) {
        if (node.blocked) continue;
        const v0 = field.get(k);
        if (v0 == null) continue;
        const danger = foes.reduce((a, f) => a + Math.max(0, 3 - (Math.abs(f.x - node.cell.x) + Math.abs(f.y - node.cell.y))), 0);
        const targetDist = foes.reduce((m, f) => Math.min(m, manhattan(f, node.cell)), 99);
        // A unit with 警戒 values a block that brings enemies into its alert
        // reach, because that is where the reaction can actually trigger.
        const alertBonus = alertDist && targetDist <= alertDist ? -1.5 : 0;
        // 「隐身」+「匿影独行」: ending the action inside 烟雾 keeps the unit
        // unselectable and grants 伤害+15% / 行动结束回复. Prefer a cover tile
        // when choosing where to idle rather than walking back into the open.
        const coverBonus = coverValue(unit, node.cell) * Number(SKILL_PRIO.coverStayStep || 2.5);
        const v = v0 + danger * (0.25 + (1 - hpPct) * 0.5) - node.cell.h * 0.002 + alertBonus - coverBonus;
        // Client `sortByNearEnemy` ranks blocks by how close they bring the
        // unit to the ENEMY FORMATION, not merely the single nearest foe.
        // Using only `targetDist` (min) left several 3-step blocks exactly
        // tied, so a cosmetic height tie-break decided the whole first move:
        // 赛程76 麦莎·SP → (12,8) instead of (9,5), 赛程90 阿列克谢·SP →
        // (8,4) instead of (9,5). Sum of distances to all foes breaks those
        // ties toward the enemy centroid, matching both client replays.
        const foeSum = foes.reduce((n, f) => n + manhattan(f, node.cell), 0);
        rows.push({k, node, v, targetDist, foeSum});
      }
      if (!rows.length) return {kind: 'wait', moveKey: null, reach, alts};
      const startV = (field.get(key(unit.x, unit.y)) ?? Infinity) -
        coverValue(unit, grid.at(unit.x, unit.y)) * Number(SKILL_PRIO.coverStayStep || 2.5);
      const bestV = Math.min(...rows.map(r => r.v));
      let near = rows.filter(r => r.v <= bestV + 1);
      if (!near.length) near = rows;
      const bucket = r => Math.round(r.v * 2) / 2;
      // Decrypted castPipeline order is getQuadrant → posCompare →
      // sortBySkillMoveMode → filterByMinMoveDist → sortByMoveAndTargetDist
      // → … → sortByPosition. Height (sortByPosition) is a LATE tie-break,
      // not the primary one: putting it second made 麦莎·SP walk to (12,8)
      // (h=6) instead of the client's (9,5) even though both blocks had the
      // same distance-field value. posCompare (x+y in the client's block
      // ordering) must decide first.
      const posCompare = (a, b) => (a.foeSum || 0) - (b.foeSum || 0)
        || (a.node.cell.x + a.node.cell.y) - (b.node.cell.x + b.node.cell.y);
      near.sort((a, b) => bucket(a) - bucket(b)                        // sortByNearEnemy (bucketed)
        || posCompare(a, b)                                             // posCompare
        || (a.node.cost + a.targetDist) - (b.node.cost + b.targetDist) // sortByMoveAndTargetDist
        // `filterByMinMoveDist` / `canStay`: among equally good blocks the
        // client takes the ONE NEEDING THE FEWEST STEPS. It used to prefer
        // `b.cost - a.cost`, which made every idle unit burn full movement.
        || a.node.cost - b.node.cost
        || b.node.cell.h - a.node.cell.h);                             // sortByPosition (late)
      const chosen = near[0];
      const improved = chosen.v < startV - 1e-9;
      return {kind: improved && chosen.k !== key(unit.x, unit.y) ? 'move' : 'wait',
              moveKey: improved ? chosen.k : null, reach,
              candidates: sim.candidates || [],
              alts: [{skill: `接近（最小移动 ${chosen.node.cost}）`, score: Math.round(chosen.v)}]};
    }

    function releasePending() {
      for (const u of units) {
        if (u.damageStored > 0 && u.alive) {
          const amount = Math.round(u.damageStored);
          u.damageStored = 0;
          const foe = units.find(x => x.alive && x.side !== u.side);
          if (foe) {
            const r = dealDamage(u, foe, amount, {pierce: true, skill: null});
            log(`${u.name} 释放储存伤害 ${r.dealt}`);
          }
        }
      }
      const due = (sim.delayed || []).filter(d => --d.left <= 0);
      sim.delayed = (sim.delayed || []).filter(d => d.left > 0);
      for (const d of due) {
        if (!d.owner.alive || !d.skill) continue;
        const t = d.target?.alive ? d.target : units.find(x => x.alive && x.side !== d.owner.side);
        if (!t) continue;
        const cell = grid.at(t.x, t.y);
        if (cell) castSkill(d.owner, d.skill, cell, {sub: true, free: true, label: '延迟结算'});
      }
    }

    /* ---------- turn loop ---------- */
    const steps = [];
    const placedSnap = () => placed.filter(o => o.alive).map(o => ({kind: o.kind, id: o.id,
      name: o.name, x: o.x, y: o.y, side: o.side, owner: o.owner?.uid,
      hp: o.hp, maxHp: o.maxHp, attackable: o.attackable, collidable: o.collidable,
      parent: o.parent ? {id: o.parent.id, x: o.parent.x, y: o.parent.y, name: o.parent.name} : null,
      label: o.label, triggerType: o.triggerType, triggers: o.triggers,
      limit: o.limit, desc: o.def?.d || ''}));
    function snapshot() {
      return units.map(u => ({uid: u.uid, x: u.x, y: u.y, hp: u.hp, alive: u.alive, mhp: maxHpOf(u), tp: u.tp,
        dir: u.dir.slice(),
        // Live speed (after 速度4 / 霜佑之印 …) for the panel and the tests.
        spd: u.alive ? Math.round(attr(u, 'SPEED')) : 0,
        // Keep every buff (not just the first 12): the character panel needs the
        // full modifier list to explain each stat at any replay step. The 5th
        // element is 0 when the buff's active_param currently switches it off.
        b: u.buffs.map(b => [b.id, Number.isFinite(b.turns) ? b.turns : 0, b.stacks, b.aura ? 1 : 0,
                             buffOn(b) ? 1 : 0]),
        cd: Object.assign({}, u.cd),
        // Alert zone for the map overlay. `d` is the client's Manhattan
        // radius (checkAlert uses `manhattan(g, at) > state.dist`); `left`
        // is the remaining 警戒次数 this round, `hidden` the client's
        // 「警戒预览隐藏」 flag (shown as a fainter dashed ring).
        al: u.alert ? {d: u.alert.dist, p: u.alert.points,
                       left: u.alert.left ?? u.alert.points,
                       skill: u.alert.name || '',
                       s: u.alert.strengthened ? 1 : 0,
                       v: u.alert.hidePreview ? 1 : 0} : null,
        ar: Math.round(armorOf(u, 'phys') + armorOf(u, 'spell'))}));
    }
    // Inspect a unit at an arbitrary replay step. The engine's live units are
    // at their FINAL state, so we temporarily restore this step's snapshot,
    // compute the breakdown and put everything back. Read-only: conditions are
    // evaluated in probe mode (no RNG consumption, no coverage bookkeeping).
    function inspect(seq, uid) {
      const step = steps[clamp(Math.round(seq) || 0, 0, steps.length - 1)];
      let snap = step?.snap?.find(s => s.uid === uid);
      const u = byId.get(uid);
      // Summons join `units` mid-battle, so an earlier replay step has no
      // snapshot for them. Inspect their first appearance instead of
      // returning null (callers across the archive expect a panel back).
      if (!snap && u && u.summon) {
        for (const st of steps) {
          snap = st.snap?.find(s => s.uid === uid);
          if (snap) break;
        }
      }
      if (!snap || !u) return null;
      const saved = {hp: u.hp, tp: u.tp, x: u.x, y: u.y, dir: u.dir, alive: u.alive,
                     buffs: u.buffs, cd: u.cd, _mhp: u._mhp, ver: u.ver, _specs: u._specs,
                     _specVer: u._specVer, _mods: u._mods, _modList: u._modList, _hpState: u._hpState,
                     _apSig: u._apSig};
      try {
        u.hp = snap.hp; u.tp = snap.tp; u.x = snap.x; u.y = snap.y;
        u.dir = (snap.dir || [1, 0]).slice(); u.alive = snap.alive;
        u.cd = snap.cd || {}; u._mhp = snap.mhp;
        u.buffs = (snap.b || []).map(([id, turns, stacks, aura]) => {
          const def = M?.buffs?.[id] || {n: `状态 ${id}`, sp: [], bt: 0, ui: true};
          const b = {id, def, turns: turns || Infinity, stacks: stacks || 1, aura: !!aura,
                     src: null, armor: null, age: 0, total: turns, holder: u, shieldParts: []};
          // Rebuild the shield breakdown using THIS step's stats; the live
          // buff objects are at the final battle state, not at `seq`.
          for (const sid of def.sp || []) {
            const raw = M?.specs?.[sid];
            if (!raw || (raw.t !== 'PHYSIC_ARMOR' && raw.t !== 'SPELL_ARMOR')) continue;
            const s = raw.dp ? resolvedSpec({spec: raw, owner: u, src: 'buff'}, {target: u}) : raw;
            const attrVal = attrById(u, s.p[0]);
            let v = attrVal * s.p[1] / 100;
            if (s.p[2]) v = Math.min(v, attrById(u, s.p[2]) * (s.p[3] || 100) / 100);
            const factor = 1 + attr(u, 'BE_ARMOR_FACTOR') / 100;
            const perLayer = Math.round(v * factor);
            const kind = s.t === 'PHYSIC_ARMOR' ? 'phys' : 'spell';
            b.armor = b.armor || {phys: 0, spell: 0};
            b.armor[kind] = perLayer * b.stacks;
            b.shieldParts.push({buff: id, buffName: def.n || '', spec: sid, kind,
              attr: attrName(s.p[0]), attrValue: Math.round(attrVal), pct: s.p[1],
              source: '自身', perLayer, stacks: b.stacks,
              factor: Math.round(factor * 100) / 100, total: perLayer * b.stacks, note: s.n || ''});
          }
          return b;
        });
        u.ver++; u._specVer = -1; u._modList = null;
        // 「非当前行动时」conditions read map.curUnit; restore the actor of
        // this step so the panel shows the state as it was at `seq`.
        const savedOwner = sim.turnOwner;
        sim.turnOwner = units.find(x => x.uid === step.actor) || savedOwner;
        const savedProbe = sim.probe;
        sim.probe = true;                  // whole panel computation is read-only
        sim.epoch++;                       // invalidate static attr cache
        try { return unitPanel(u, snap); }
        finally { sim.turnOwner = savedOwner; sim.probe = savedProbe; }
      } finally {
        Object.assign(u, saved);
        sim.epoch++;                       // and invalidate the probe's entries
      }
    }
    // Replay annotation: every unit / hit carries its side+slot id (A1/B3…)
    // and the tile it was standing on when the hit landed. This makes it
    // possible to tell WHO acted and WHOM a skill affected without guessing
    // from identical names (two units can share a name).
    const tagOf = u => u ? `${u.name}·${u.uid}` : '?';
    const cellOf = h => Number.isFinite(h?.x) ? `(${h.x},${h.y})` :
      (() => { const u = byId.get(h?.uid); return u ? `(${u.x},${u.y})` : ''; })();
    const describeHit = h => {
      const u = byId.get(h.uid);
      // Hits from linked casts inside this action name their real caster.
      const via = h.sub ? `${h.byName}${h.byUid ? '·' + h.byUid : ''}「${h.bySkill}」` : '';
      const who = u ? `${tagOf(u)}${cellOf(h)}` : (h.uid || '物件');
      if (h.miss) return `${via ? via + ' → ' : ''}${who} 闪避`;
      if (h.status) return `${via ? via + ' → ' : ''}${who}`;
      if (h.heal) return `${via ? via + ' ' : ''}治疗 ${who} ${h.amount}（${h.after}/${maxHpOf(u)}）`;
      const tags = [];
      if (h.restraint && h.restraint !== 1) tags.push('克制 ×' + h.restraint);
      if (h.height) tags.push((h.height > 0 ? '高地 +' : '低地 ') + h.height + '%');
      if (h.crit) tags.push('暴击');
      if (h.kind === 'pierce') tags.push('穿透');
      if (h.absorbed) tags.push(`护盾吸收 ${h.absorbed}`);
      if (h.reborn) tags.push(`不屈「${h.reborn}」以 ${h.rebornHp} 生命存活`);
      else if (!h.amount && !h.absorbed && !h.killed) tags.push(h.zeroReason || '伤害被免疫 / 减免至 0');
      const label = [via, h.seg].filter(Boolean).join(' · ');
      return `对 ${who} 造成 ${Math.max(0, h.amount)} 伤害${label ? `〔${label}〕` : ''}${tags.length ? '（' + tags.join('，') + '）' : ''}，剩余 ${h.after}/${maxHpOf(u)}${h.killed ? '，击败' : ''}`;
    };
    // Numeric audit trail for ONE hit: every term with its value AND the
    // substituted arithmetic, plus the compact formula and the HP outcome.
    // Shared by both regular casts and turn-boundary sub-casts.
    function logHitAudit(h, defaultSkill) {
      if (!h.calc?.length) {
        // A pure status hit legitimately has no damage formula. Only log
        // when there is something to explain (a miss or an explicit zero
        // reason); otherwise a single 8-target buff spell would spam eight
        // identical "no formula" lines into the replay.
        if (h.miss || h.zeroReason)
          log(`${h.heal ? '治疗数值' : '伤害数值'}「${defaultSkill}」→ ${byId.get(h.uid)?.name || h.uid}：` +
              `未产生${h.heal ? '治疗' : '伤害'}${h.zeroReason ? `（${h.zeroReason}）` : '（未命中）'}`);
        return;
      }
      const kind = h.heal ? '治疗数值' : '伤害数值';
      const termLines = h.calc.map(c => `${c.label}=${c.value}${c.expr ? ` {${c.expr}}` : ''}`).join('；');
      const chain = h.formula || h.calc.map(c => c.expr || `${c.label} ${c.value}`).join(' → ');
      const tail = h.heal
        ? `生命 ${h.before} → ${h.after}（实际回复 ${h.amount}）`
        : `护盾吸收 ${h.absorbed || 0} → 实扣 ${h.amount}，剩余 ${h.after}`;
      // One self-contained line per hit: keeping it on one line is what makes
      // a replay greppable / auditable.
      log(`${kind}${h.sub ? `（${h.byName} 联动施放）` : ''}「${h.sub ? h.bySkill : defaultSkill}」→ ${byId.get(h.uid)?.name || h.uid}${h.seg ? `（${h.seg}）` : ''}：${termLines}；公式 ${chain}；${tail}`);
    }
    // Sub-casts fired OUTSIDE actOnce() (每人回合开始 27 / 每人回合结束 28 /
    // 行动后 43 / 战斗开始 25 / 回合结束 29) used to have `sim.subHits = null`,
    // so their real damage was applied to HP but silently discarded: 审判执行
    // looked like a no-op in the replay. Keep a pending queue for the whole
    // turn and attach it to the step that owns those events.
    function drainPendingSubHits(step) {
      if (!step) return;
      const all = sim.pendingSubHits || [];
      if (!all.length) return;
      sim.pendingSubHits = [];
      // Most turn-boundary sub-casts are pure status placements (召唤 / 标记
      // / 光环) with amount 0. Showing them all as 「N 次命中，共 0 伤害」
      // would flood every replay line; keep the ones a reader can verify.
      const subs = all.filter(h => h.amount > 0 || h.heal || h.miss ||
        h.zeroReason || h.absorbed || h.calc?.length);
      if (!subs.length) return;
      step.hits = (step.hits || []).concat(subs);
      const known = new Map((step.subCasts || []).map(x => [`${x.uid}:${x.id}`, x]));
      for (const h of subs) known.set(`${h.byUid}:${h.bySkillId}`,
        {uid: h.byUid, name: h.byName, skill: h.bySkill, id: h.bySkillId});
      step.subCasts = [...known.values()];
      for (const h of subs) logHitAudit(h, h.bySkill);
      // step.text was built before the turn boundary resolved, so append the
      // linked damage explicitly — otherwise the replay line still reads as
      // if nothing happened even though HP was deducted.
      const dealt = subs.reduce((n, h) => n + (h.amount || 0), 0);
      if (!dealt) return;
      const casts = [...new Set(subs.filter(h => h.amount > 0).map(h => h.bySkill))].join('、');
      const dmg = subs.filter(h => h.amount > 0).length;
      const suffix = `；行动结束触发「${casts}」→ ${dmg} 次命中，共 ${dealt} 伤害`;
      if (step.text) step.text += suffix;
      else step.text = suffix.slice(1);
    }
    let stepOrder = [];
    let orderChanges = 0;
    function pushStep(step) {
      step.seq = steps.length;
      // Battle-start sub-casts (战斗开始 25) resolve before any unit turn, so
      // there is no flush() yet; give their hits to the deployment step.
      if (!steps.length) drainPendingSubHits(step);
      if (step.facingFrom && step.actor) {
        const cur = byId.get(step.actor)?.dir;
        if (cur && cur.join(',') !== step.facingFrom.join(',')) {
          const names = d => !d ? '' : d[0] > 0 ? '东' : d[0] < 0 ? '西' : d[1] > 0 ? '南' : '北';
          log(`${byId.get(step.actor).name} 朝向由 ${names(step.facingFrom)} 转为 ${names(cur)}`);
        }
      }
      step.events = events;
      events = [];
      // OPERATION terrain statuses expire after their client-declared rounds.
      // Restore the TILE too, not just the UI map: cell.status is what
      // isFieldStatus() / movement cost / terrain buffs actually read.
      let terrainExpired = false;
      for (const [k, f] of [...sim.fieldStatus]) {
        if (sim.round - f.round >= f.turns) {
          const c = grid.at(f.x, f.y);
          if (c && (c.status || 1) === Number(f.id)) clearFieldStatus(c);
          else sim.fieldStatus.delete(k);
          terrainExpired = true;
        }
      }
      // A lost 烟雾 tile must drop its [隐身] aura immediately, not at the
      // next action (otherwise the unit stays unselectable for a whole turn).
      if (terrainExpired) refreshAuras();
      step.fields = [...sim.fieldStatus.values()].map(f => ({...f,
        left: Math.max(0, f.turns - (sim.round - f.round))}));
      // Terrain tiles in effect at THIS replay step (from OPERATION /
      // EXTRA_FIELD_STATUS), for the board overlay and the detail panel.
      step.terrain = [...grid.cells.values()].filter(c => (c.status || 1) !== 1)
        .map(c => ({x: c.x, y: c.y, id: c.status,
          name: M?.fieldStatusDefs?.[c.status]?.name || M?.enums?.fieldStatus?.[c.status] || `地块 #${c.status}`}));
      step.knockbacks = sim.knockbacks || [];
      sim.knockbacks = [];
      step.snap = snapshot();
      step.placed = placedSnap();       // objects visible at THIS replay step
      steps.push(step);
      return step;
    }

    // Battle start: weather / mission buffs / unit status / prewar modifiers.
    const env = opts.env || {};
    if (M) {
      if (env.weatherId && M.weather?.[env.weatherId]?.aura) {
        const sid = M.weather[env.weatherId].aura;
        if (M.specs[sid]) envAuras.push({spec: M.specs[sid], sid, owner: null, src: 'weather', name: M.weather[env.weatherId].name});
        log(`天气「${M.weather[env.weatherId].name}」：${M.weather[env.weatherId].desc}`);
      }
      for (const b of env.buffs || []) {
        for (const u of units) if (b.side === 'both' || b.side === u.side) addBuff(u, b.buffId, 0, 1, null, {quiet: true, force: true});
        if (M.buffs[b.buffId]) log(`赛事增益「${M.buffs[b.buffId].n}」→ ${b.side === 'both' ? '双方' : b.side === 'A' ? '我方' : '敌方'}`);
      }
      for (const s of env.unitStatus || []) {
        const u = units.filter(x => x.side === s.side)[s.index];
        if (u) addBuff(u, s.buffId, 0, 1, null, {force: true});
      }
      for (const u of units) {
        for (const inst of unitSpecs(u)) {
          const s = inst.spec;
          if (s.at !== 1 && s.at !== 25) continue;
          if ((s.t === 'PREWAR_MODIFY_ATTRIBUTE' || s.t === 'PREWAR_MODIFY_BASE_ATTRIBUTE') && cond(inst, {})) {
            const n = attrName(s.p[0]);
            const pw = u.prewar || (u.prewar = {});
            const det = u.prewarParts || (u.prewarParts = {});
            for (const A of COMPOSITE[n] || [n]) {
              const e = pw[A] || (pw[A] = {flat: 0, pct: 0});
              e.flat += s.p[1]; e.pct += s.p[2];
              (det[A] || (det[A] = [])).push({
                n: inst.name || s.t, src: inst.src || 'passive', t: s.t, spec: inst.sid,
                skill: inst.skill?.id || 0, attr: n, flat: s.p[1] || 0, pct: s.p[2] || 0,
                ok: true,
              });
            }
            bump(cov.executed, s.t); touch(u);
          } else if (s.t === 'PREWAR_CONVERT_ATTRIBUTE' && cond(inst, {})) {
            const pw = u.prewar || (u.prewar = {});
            const det = u.prewarParts || (u.prewarParts = {});
            const from = attrName(s.p[0]), to = attrName(s.p[1]);
            const e = pw[to] || (pw[to] = {flat: 0, pct: 0});
            const v = baseOf(u, from) * s.p[2] / 100;
            e.flat += v;
            (det[to] || (det[to] = [])).push({
              n: inst.name || s.t, src: inst.src || 'passive', t: s.t, spec: inst.sid,
              skill: inst.skill?.id || 0, attr: from, flat: Math.round(v * 100) / 100, pct: 0,
              note: `${from} × ${s.p[2]}%`, ok: true,
            });
            bump(cov.executed, s.t); touch(u);
          } else if (s.t === 'REPLACE_SKILL' && s.at === 1 && cond(inst, {})) { replaceSkill(u, s.p[0], s.p[1], inst.name); bump(cov.executed, s.t); }
          else if (s.t === 'GET_EXTRA_SKILL' && s.at === 1 && cond(inst, {})) { EFFECTS.GET_EXTRA_SKILL(inst, {}); bump(cov.executed, s.t); }
        }
      }
      refreshAuras();
      for (const u of units) {
        fire(25, u, {target: u});
        // active_time 1 = 任意: static modifiers are handled by attrCompute,
        // but creation effects (召唤物 / 交互物) need one battle-start pass.
        for (const ins of unitSpecs(u)) {
          const s = ins.spec;
          if ((AT_ALIAS[s.at] || s.at) !== 1 || STATIC_TYPES.has(s.t)) continue;
          if (!['PLACE_UNIT', 'PLACE_ITEM', 'PLACE_TRAP', 'ACTIVATION'].includes(s.t)) continue;
          runSpec(ins, {target: u});
        }
      }
      fireObject(25, {});                      // 战斗开始：雪人生成蜜果 + 碎冰
      refreshAuras();
      // Arena 「选手精神状态」 (unit_status) are applied before deployment,
      // and their 「行动开始时，有33%的概率…最多触发1次」 rows are at=27
      // (每人回合开始 / ROUNDSTART). The first action start of the battle IS
      // the opening, so resolve those probability rows here. Previously the
      // roll only happened in startTurn(), i.e. at step #18 of round 1 for a
      // slow 伊凡, so NO replay ever showed a unit starting the battle asleep
      // and the 33% could not be verified. `only` scopes this pass to the
      // arena-status buffs, leaving other at=27 rows (静聆神谕 …) on their
      // ordinary turn-start timing. A failed roll does not spend the `lc:1`
      // budget, so the unit still gets its per-action-start chance.
      for (const st of env.unitStatus || []) {
        const u = units.filter(x => x.side === st.side)[st.index];
        if (!u) continue;
        const def = M.buffs[st.buffId];
        const ids = new Set((def?.sp || []).filter(sid => {
          const q = M.specs[sid];
          return q && (AT_ALIAS[q.at] || q.at) === 27 && /Random\s*\(/.test(String(q.c || ''));
        }).map(Number));
        if (!ids.size) continue;
        const before = new Set(u.buffs);
        const wasProbe = sim.probe;
        sim.probe = false;                   // this is a REAL die, not a preview
        try {
          fire(27, u, {target: u}, inst => !!inst.buff && ids.has(Number(inst.sid)));
        } finally { sim.probe = wasProbe; }
        // A buff may replace an existing one (same length), so compare object
        // identity rather than array length.
        const applied = u.buffs.some(b => !before.has(b));
        log(`${u.name} 的「${def?.n || st.buffId}」开局判定：Random(100)=${sim.lastRandom ?? '?'}` +
            `（阈值 33）→ ${applied ? '命中' : '未命中'}${applied ? `，新增状态 ${u.buffs.filter(b => !before.has(b)).map(b => M.buffs[b.id]?.n || b.id).join('、')}` : ''}`);
      }
    }
    for (const u of units) { u.hp = maxHpOf(u); u.maxHp = u.hp; u.tp = Math.min(u.tp, attr(u, 'TP_MAX')); }
    pushStep({round: 0, kind: 'start', text: `部署完成：${grid.name} · ${teams.A.length} 对 ${teams.B.length}`});
    const initialSnap = steps[0].snap;

    let winner = null, round = 0;
    const alive = side => units.some(u => u.alive && u.side === side);
    const checkWin = () => { if (!alive('A')) winner = 'B'; else if (!alive('B')) winner = 'A'; return !!winner; };

    function moveUnit(unit, toKey, reach, step) {
      if (!toKey || toKey === key(unit.x, unit.y)) return false;
      const path = pathTo(reach, toKey);
      fire(42, unit, {target: unit});
      const from = grid.at(unit.x, unit.y);
      const [x, y] = toKey.split(',').map(Number);
      const last = path[path.length - 2] || {x: unit.x, y: unit.y};
      unit.x = x; unit.y = y;
      sim.epoch++;
      unit.dir = dirTo(last, {x, y});
      unit.flags.moved = true;
      unit.flags.moveHeight = grid.at(x, y).h - from.h;
      unit.flags.spentMove = (unit.flags.spentMove || 0) + (reach.get(toKey)?.cost || 0);
      step.path = (step.path || []).concat(step.path ? path.slice(1) : path);
      triggersOnPath(step.path, unit);
      refreshAuras();
      return true;
    }
    // active_time 43 = 行动后. The client fires it ONCE per action, AFTER the
    // skill resolves — not after each movement step. ACTED_ACT specs at 43
    // (机动游击「只能游击」, 金狮形态「只能大招」, 附属被动-再动) need the
    // buffs granted by THIS action to be present, otherwise they fire one
    // action late or never.
    function fireActionEnd(u) {
      if (sim.actionId === sim.fired43) return;
      sim.fired43 = sim.actionId;
      fire(43, u, {target: u});
    }

    // Client Logic_AI_AI_Phase: CHECK_STATE → DO_SKILL → MOVE_OR_IDLE → FINISH.
    // One phase = one decide + one cast/move. A [瞬发] cast returns to
    // MOVE_OR_IDLE instead of FINISH, so the unit may keep walking on its
    // remaining mobility and may cast again; a normal cast ends the action.
    function actOnce(unit, isExtra, chainIndex, reachOverride) {
      sim.tick++;
      sim.consumption = null;
      const from = {x: unit.x, y: unit.y};
      sim.decidePhase = {chainIndex};
      // During an extra action the client's ACTED_ACT.p[0] restricts
      // `all_skill_list` to ONE skill. Keep it for every phase of the chain.
      sim.extraSkill = isExtra ? (unit.flags.reActSkill || 0) : 0;
      sim.extraSkillUnit = isExtra ? unit.uid : null;
      // The skill bar follows each buff's LIVE active_param (8850 星核·位移
      // while 8801 is live on 贝拉; 士气高昂 at tp ≥ 7 …).
      syncBuffSwaps(unit);
      const plan = decide(unit, reachOverride);
      const alertNow = alertState(unit);
      const chainText = chainIndex > 0 ? '瞬发后继续行动：' : (isExtra ? '再行动：' : '');
      const step = {round, actor: unit.uid, kind: plan.kind, from, alts: plan.alts,
                    candidates: plan.candidates || [],
                    facingFrom: unit.dir.slice(),
                    order: stepOrder, phase: PHASES.join(' → '),
                    chainIndex, chainText: chainIndex > 0 ? '瞬发后继续行动' : '',
                    moveRule: {minMoveDist: RULE.filterByMinMoveDist !== false,
                               moveAndTargetDist: RULE.sortByMoveAndTargetDist !== false,
                               quadrant: !!RULE.quadrantCompare,
                               bestStand: plan.best?.standKey || plan.moveKey || null,
                               castRim: plan.best?.castRim ?? null,
                               castShape: plan.best?.skill ? castShape(plan.best.skill) : null,
                               skillState: plan.best?.skill ? skillStateOf(unit, plan.best.skill) : null,
                               noCastReason: sim.noCastReason || '',
                               pipeline: SUB?.castPipeline || [],
                               comparators: sim.castComparators || [],
                               targetSorts: SUB?.targetSorts || [],
                               targetSortWeight: Number(SKILL_PRIO.targetSortWeight || 0),
                               targetQuality: plan.best?.targetQuality ?? null,
                               aiByOrder: !!unit.ai?.byOrder, aiSorted: !!unit.ai?.sorted,
                               skillOrder: (unit.ai?.order || []).slice(0, 8),
                               aiCursor: unit.ai?.cursor || 0,
                               aiBossMode: Number(unit.ai?.bossMode) || 0,
                               allSkillList: sim.allSkillList || [],
                               curSkill: sim.curSkill || 0,
                               priority: Object.fromEntries(sim.aiPriority || []),
                               alertDist: alertNow?.dist || 0,
                               alertPoints: alertNow?.points || 0,
                               alertBasePoints: alertNow?.basePoints || 0,
                               alertCountBonus: alertNow?.countBonus || 0,
                               aiFields: Object.keys(SUB?.aiFields || {}),
                               clientMechanisms: SUB?.clientMechanisms || {},
                               moveSteps: unit.flags?.spentMove || 0,
                               mobility: Number(attr(unit, 'MOBILITY')) || 0,
                               minMoveSteps: RULE.minMoveSteps !== false,
                               canStay: !!SKILL_PRIO.moverMoveTolerance
                                 || !!SKILL_PRIO.moverMoveTolerancePct,
                               chainIndex, instantChain: chainIndex > 0,
                               slotOrder: (unit.slotOrder || []).slice(0, 8),
                               skillPriority: SKILL_PRIO,
                               instantIds: [...(unit.instantIds || [])]}};
      const moveKey = plan.kind === 'skill' ? plan.best.standKey : plan.moveKey;
      moveUnit(unit, moveKey, plan.reach, step);
      step.to = {x: unit.x, y: unit.y};
      const moved = step.path ? `从 (${from.x},${from.y}) 移动到 (${unit.x},${unit.y})，` : '';
      let jumpText = '';
      // Client `PathAlert`: check every traversed block in order. The first
      // one inside a 警戒 zone resolves the reaction; FORCE_STOP ends the
      // action there (the remaining path is discarded). A single action can
      // cross several alert-capable SEGMENTS (walk → CHARGE / JUMP_MOVE
      // landing), and each is ONE 警戒 reaction with its own damage segments.
      step.alertHits = [];
      const noteAlert = hit => {
        if (!hit) return null;
        step.alertHits.push(hit);
        if (!step.alertHit) step.alertHit = hit;
        return hit;
      };
      const alertAlong = cells => {
        for (const cell of cells) {
          const hit = checkAlert(unit, cell);
          if (hit) return noteAlert(hit);
        }
        return null;
      };
      let alertHit = step.path?.length ? alertAlong(step.path.slice(1)) : null;
      if (alertHit && alertHit.forced) {
        step.kind = 'move';
        step.alertHit = alertHit;
        step.text = `${moved}在 (${alertHit.cell.x},${alertHit.cell.y}) 触发 ${alertHit.owner} 的警戒${unit.alive ? '，行动被打断' : '，被击败'}`;
      } else if (plan.kind === 'skill' && unit.alive) {
        const {skill, target, area} = plan.best;
        step.skill = {id: skill.id, name: skill.n, heal: skill.dt === 3, tp: tpCost(unit, skill),
                      instant: !!unit.instantIds?.has(Number(skill.id)),
                      tier: unit.skillTier?.get(Number(skill.id)) || 'carried',
                      slot: unit.slotOrder?.indexOf(Number(skill.id)) ?? -1,
                      labels: skillLabels(skill, M)};
        // Composite view for the replay detail: every damage segment plus
        // every buff / debuff / sub-cast / conditional modifier, decoded from
        // skill.idskill_follow + speciality.active_param (no hardcoding).
        step.plan = Object.assign({}, skillPlan(skill) || {},
                                  {composition: compositionOf(skill)});
        // Client `overwritten_skill_id` /「技能变更为：[X]」/ REPLACE_SKILL
        // at=1 rows all resolve here. 97 client skills declare a swap; the
        // destination and duration come from the decoded tables, never a
        // character-specific branch.
        const sw = step.plan.swapTo;
        step.target = {x: target.x, y: target.y};
        step.area = area.map(c => ({x: c.x, y: c.y}));
        step.score = Math.round(plan.best.score);
        sim.teleport = null; sim.charge = null; sim.skillScaling = null;
        sim.subHits = [];
        // 「静聆神谕」: casting one member consumes this action's forced
        // choice; the following 再行动 is unrestricted. Mark it used as well
        // so the next round picks a different member and resets after all 3.
        if (unit.flags.choiceGroup?.includes(Number(skill.id))) {
          (unit.flags.choiceUsed || (unit.flags.choiceUsed = new Set())).add(Number(skill.id));
          // The unchosen members were only offered for this choice.
          const others = unit.flags.choiceGroup.filter(id => id !== Number(skill.id));
          unit.flags.choiceGroup = null;
          revokeTemp(unit, others, '强制选择已完成');
          // The forced choice grants a free extra action once the chosen
          // member resolves. Log its source explicitly, like every other
          // ACTED_ACT/RE_ROUND source, so the replay can trace WHY the
          // following 「再行动」 step exists (静聆神谕 → 命途所至).
          unit.flags.reAct = true;
          log(`${unit.name} 获得再行动（静聆神谕：使用「${skill.n}」后）`);
        }
        try {
          // A zero-range direction skill targets a DIRECTION, not a block: the
          // candidate's `dir` must survive into castSkill(), otherwise
          // areaCells() falls back to "east" and the 3*6 sweep fires the
          // wrong way.
          const castCell = grid.at(target.x, target.y);
          const castTarget = castCell && target.dir
            ? Object.assign({}, castCell, {dir: target.dir}) : castCell;
          if (target.dir) step.dir = target.dir;
          step.hits = castSkill(unit, skill, castTarget,
            plan.best.prop ? {prop: plan.best.prop} : {});
        } finally {
          const subs = sim.subHits || [];
          sim.subHits = null;
          // Linked casts resolved inside this action (协同响应 15935 cast by
          // 伦伽勒·SP / 贝拉 …, CAST_SKILL follow-ups, delayed 伏刃 …).
          if (subs.length) {
            step.hits = (step.hits || []).concat(subs);
            step.subCasts = [...new Map(subs.map(h => [`${h.byUid}:${h.bySkillId}`,
              {uid: h.byUid, name: h.byName, skill: h.bySkill, id: h.bySkillId}])).values()];
          }
        }
        // Apply the swap AFTER the cast resolves (so the cast uses its own
        // specialities), then record it on the replay step.
        if (sw && !plan.best.prop) {
          replaceSkill(unit, Number(skill.id), Number(sw),
            step.plan.swapName ? `技能变更为 [${step.plan.swapName}]` : '技能变更为',
            Number(step.plan.swapTurns) || 0);
          step.skillSwap = {from: Number(skill.id), to: Number(sw),
                            turns: Number(step.plan.swapTurns) || 0};
        }
        if (sim.skillScaling?.length) step.skillScaling = sim.skillScaling;
        if (sim.consumption) step.consumption = sim.consumption;
        // Numeric audit trail: every term WITH its substituted arithmetic,
        // for damage AND healing. Shared with turn-boundary sub-casts.
        for (const h of step.hits) logHitAudit(h, skill.n);
        // The displacement is CAUSED BY THE SKILL, not an independent move.
        // State it after the cast so the causal chain is unambiguous:
        //   走位 → 使用「烟幕游击」→ 该技能触发 JUMP_MOVE 位移
        if (sim.charge) {
          step.charge = sim.charge;
          step.to = {x: unit.x, y: unit.y};
          step.path = (step.path || []).concat(sim.charge.path.slice(1));
          jumpText = `；由技能「${skill.n}」#${skill.id} 触发位移机制 CHARGE（特技 #${sim.charge.specId}「${sim.charge.spec}」）：` +
            `(${sim.charge.from.x},${sim.charge.from.y}) → (${unit.x},${unit.y})，冲锋 ${sim.charge.steps} 格`;
          // `PathAlert` also runs on the CHARGE trajectory.
          alertAlong(sim.charge.path.slice(1));
        }
        if (sim.teleport) {
          step.teleport = sim.teleport;
          step.to = {x: unit.x, y: unit.y};
          step.path = (step.path || []).concat([{x: unit.x, y: unit.y}]);
          jumpText = `；由技能「${skill.n}」#${skill.id} 触发位移机制 ${sim.teleport.spec}（特技 #${sim.teleport.specId}「${sim.teleport.specName}」）：` +
            `(${sim.teleport.from.x},${sim.teleport.from.y}) → (${unit.x},${unit.y})`;
          // A jump is also a movement into/out of an alert zone: the client
          // resolves `PathAlert` on the landing block.
          alertAlong([{x: unit.x, y: unit.y}]);
        }
        // A self / support / stance skill has NO hit target at all — writing
        // 「未命中」for 「强击姿态」was wrong. Only an attack that actually
        // failed to connect is a miss.
        const noHitText = skill.eg ? `在空地 (${target.x},${target.y}) 完成放置／召唤`
          : (skill.aim === 'self' || isUtility(skill))
            ? `对自身生效（${skillLabels(skill, M).slice(0, 3).join('／') || '支援'}，无命中目标）`
            : '未命中';
        const hitText = step.hits.map(describeHit).filter(Boolean).join('；') || noHitText;
        const lastAlert = step.alertHits[step.alertHits.length - 1];
        step.text = `${tagOf(unit)}：${moved}${chainText}${step.skill.instant ? '[瞬发]' : ''}使用「${skill.n}」${step.skill.tp ? `（能量 −${step.skill.tp}）` : ''}→ (${target.x},${target.y})${jumpText}：${hitText}` +
          (lastAlert ? `；触发 ${step.alertHits.length} 次警戒（共 ${step.alertHits.reduce((n, h) => n + (h.segmentCount || h.hits || 1), 0)} 段伤害，剩余 ${lastAlert.left}/${lastAlert.points} 次）` : '');
        if (step.alertHits.length > 1) {
          log(`警戒合计：${unit.name} 本次行动触发 ${step.alertHits.length} 次警戒 × ${step.alertHits[0].segmentCount || 2} 段 = ` +
              `${step.alertHits.reduce((n, h) => n + (h.segmentCount || h.hits || 1), 0)} 段伤害；` +
              `警戒次数 ${step.alertHits[0].points} → 剩余 ${lastAlert.left}（每次消耗 1 次）`);
        }
      } else if (plan.kind === 'move') {
        step.text = `${tagOf(unit)}：${moved}${chainText}没有可攻击的目标，向${enemiesOf(unit).some(e => unitSpecs(e).some(i => i.spec.t === 'TAUNT')) ? '嘲讽单位' : '最近的敌人'}接近`;
      } else {
        step.text = `${tagOf(unit)}：${chainText}无法移动也无法攻击，待机`;
        fire(30, unit, {target: unit});
      }
      // Post-cast movement, driven by the client's own hints:
      //   ACTED_MOVE / RE_ROUND (`flags.extraMove`) gives a fresh budget;
      //   `skill.ai_move_close` = close | away | stay tells the AI to spend
      //   the REMAINING mobility advancing toward / away from the enemy.
      // Previously ai_move_close only added ±3 points in decide() and never
      // produced an actual step.
      const postCastMove = (budget, toward, label) => {
        if (!(unit.alive && budget > 0) || checkWinQuiet()) return;
        const reach = reachable(unit, budget);
        let best = null, bestV = -Infinity;
        const foes = enemiesOf(unit);
        const ranged = unit.skills.some(s => s.rmax > 1);
        for (const [k, node] of reach) {
          // A node is `blocked` when another unit / object stands on it: it may
          // be crossed (friendly units are passable) but never ended on. The
          // old loop ignored that and parked 伦伽勒·SP on 麦莎·SP's tile (9,5).
          if (node.blocked) continue;
          const d = foes.reduce((m, e) => Math.min(m, manhattan(e, node.cell)), 99);
          // Post-cast 「再移动」: stay in / return to a concealing tile rather
          // than stepping back into the open after the 普攻.
          const cover = coverValue(unit, node.cell) * Number(SKILL_PRIO.coverStayStep || 2.5);
          const v = (toward === 'close' ? -d : toward === 'away' ? d : (ranged ? d : -d)) - node.cost * 0.1 + cover;
          if (v > bestV) { bestV = v; best = k; }
        }
        if (best && best !== key(unit.x, unit.y)) {
          const before = {x: unit.x, y: unit.y};
          moveUnit(unit, best, reach, step);
          step.to = {x: unit.x, y: unit.y};
          step.text += `；${label} (${before.x},${before.y}) → (${unit.x},${unit.y})`;
          noteAlert(checkAlert(unit, {x: unit.x, y: unit.y}));
        }
      };
      if (plan.kind === 'skill' && plan.best?.skill) sim.actionLastSkill = plan.best.skill;
      const instantCast = !!step.skill?.instant && !step.alertHit?.forced;
      // Client phases CHECK_STATE → DO_SKILL → MOVE_OR_IDLE → FINISH. An
      // [瞬发] cast returns to MOVE_OR_IDLE and the SAME action continues;
      // 「行动后」(active_time 43, distinct from 47「使用技能后」) and the
      // post-action movement (ACTED_MOVE budget / ai_move_close) belong to
      // FINISH, i.e. the LAST phase. Running them after the instant phase
      // spent 伦伽勒·SP's remaining movement on a stroll and left
      // 陷阵·锐意承锋 with no legal block for the real follow-up cast.
      const continueChain = instantCast && unit.alive && chainIndex < MAX_INSTANT_CHAIN && !checkWinQuiet();
      if (!continueChain) {
        fireActionEnd(unit);
        // A restricted extra action is the named skill and nothing else: no
        // ACTED_MOVE / ai_move_close stroll afterwards.
        const restricted = isExtra && unit.flags.reActSkill;
        if (restricted) unit.flags.extraMove = 0;
        const amc = sim.actionLastSkill?.amc;
        if (!restricted && unit.alive && unit.flags.extraMove) {
          const budget = unit.flags.extraMove;
          unit.flags.extraMove = 0;
          postCastMove(budget, 'default', '再移动');
        } else if (!restricted && sim.actionLastSkill && ['close', 'away'].includes(amc)) {
          const left = Math.max(0, Number(attr(unit, 'MOBILITY')) - (unit.flags.spentMove || 0));
          postCastMove(left, amc, `ai_move_close=${amc}`);
        }
      }
      unit.tally.actions++;
      if (unit.ai?.byOrder) {
        const n = ((unit.ai.bossMode ? unit.ai.sequence : null) || unit.ai.order || []).length;
        if (n) unit.ai.cursor = ((unit.ai.cursor || 0) + 1) % n;
      }
      if (instantCast) {
        if (!unit.flags.instantUsed) unit.flags.instantUsed = new Set();
        unit.flags.instantUsed.add(Number(step.skill.id));
        // 「释放后，技能变更为：[取消潜袭]」is a TOGGLE pair. If the swap
        // destination stays castable in the same [瞬发] chain, the AI casts
        // 潜袭 → 取消潜袭 → 潜袭 … and burns the whole action doing nothing.
        // The client's toggle is one choice per action: block the newly
        // swapped-in skill for the remainder of this action too.
        const sw = skillPlan(step.skill)?.swapTo || step.skill.ovid;
        if (sw) unit.flags.instantUsed.add(Number(sw));
        if (continueChain) log(`${unit.name} 的「${step.skill.name}」为[瞬发]，行动未结束，可继续移动或施放技能`);
      }
      pushStep(step);
      return {instantCast, continueChain, stop: !unit.alive || !!step.alertHit?.forced || checkWinQuiet()};
    }
    // One unit action. Casting a [瞬发] skill keeps the action open: re-run
    // CHECK_STATE → DO_SKILL → MOVE_OR_IDLE with only the REMAINING mobility
    // (spentMove is accumulated by moveUnit), until a normal skill ends the
    // action, the unit waits, or the phase cap prevents an infinite chain.
    function act(unit, isExtra) {
      let chainIndex = 0, reachOverride = null;
      sim.actionId = (sim.actionId || 0) + 1;
      sim.fired43 = -1;
      sim.actionLastSkill = null;
      while (chainIndex <= MAX_INSTANT_CHAIN) {
        // Keep the ACTED_ACT.p[0] skill restriction for EVERY phase of the
        // extra action: if the named skill is [瞬发], a following chain phase
        // must not be free to cast anything else.
        const r = actOnce(unit, isExtra, chainIndex, reachOverride);
        if (r.stop || !r.continueChain) break;
        chainIndex++;
        // MOVE_OR_IDLE after an [瞬发] cast: the remaining mobility, or a
        // larger 「攻击后再移动」 grant earned during that cast — whichever is
        // bigger, never both (p[0]=0 grants ARE the remaining mobility).
        const left = Math.max(0, Number(attr(unit, 'MOBILITY')) - (unit.flags.spentMove || 0));
        const budget = Math.max(left, unit.flags.extraMove || 0);
        unit.flags.extraMove = 0;
        reachOverride = reachable(unit, budget);
      }
      // 行动后: one per action, after all instant-chain phases. This is the
      // timing that grants the [附属被动] / 机动游击 / 金狮形态 extra actions.
      fireActionEnd(unit);
    }
    const checkWinQuiet = () => !alive('A') || !alive('B');

    function startTurn(u) {
      u.flags.moved = false; u.flags.spentMove = 0; u.flags.reActs = 0; u.flags.damagedTurn = false;
      u.flags.skilled = false; u.flags.instantUsed = new Set(); u.turnStates = new Set();
      for (const o of units) if (o !== u && o.alive) fire(56, o, {target: u});
      for (const b of u.buffs.slice()) {
        if (b.def.end === 1 && Number.isFinite(b.turns)) { b.turns--; b.age = (b.age || 0) + 1; if (b.turns <= 0) removeBuff(u, b, '结束'); }
      }
      fire(27, u, {target: u});
    }
    function endTurn(u) {
      if (!u.alive) return;
      const hadAlert = alertState(u);
      fire(28, u, {target: u});
      fire(51, u, {target: u});
      if (!u.alive) return;
      // 行动结束时进入[警戒]: personality 19170 spec 24934 (BUFF at=28).
      const al = alertState(u);
      if (al && (!hadAlert || hadAlert.skillId !== al.skillId || u.flags.alertRound !== round)) {
        u.flags.alertRound = round;
        u.alert = {dist: al.dist, points: al.points, basePoints: al.basePoints,
                   countBonus: al.countBonus, skillId: al.skillId,
                   strengthened: al.strengthened, interrupts: al.interrupts,
                   hits: al.hits, display: al.display,
                   hidePreview: al.hidePreview, name: al.name};
        log(`${u.name} 展开警戒（范围 ${al.dist} 格，每回合 ${al.points} 次` +
            `${al.countBonus ? ` = 基础 ${al.basePoints} + 光环/特技 ${al.countBonus}` : ''}` +
            `${al.hits > 1 ? `，每次 ${al.hits} 段伤害` : ''}` +
            `${al.strengthened ? (al.interrupts ? '，强制警戒（可打断）' : '，警戒强化（不打断）') : ''}` +
            `${al.hidePreview ? '，隐藏范围预览' : ''}）`);
        bump(cov.executed, 'ALERT_ATTACK');
        const st = steps[steps.length - 1];
        if (st && st.actor === u.uid) st.alert = Object.assign({}, u.alert);
      }
      if (!al) u.alert = null;
      // NOT_RECOVER_TP: client 「无法回复能量」 suppresses the end-of-action
      // +1 energy. The flag is set by EFFECTS.NOT_RECOVER_TP; also check the
      // speciality directly in case runSpec did not fire for it.
      const noTp = u.flags.noRecoverTp || specActive(u, 'NOT_RECOVER_TP');
      if (noTp) log(`${u.name} 处于「无法回复能量」，跳过行动结束 +1 能量（NOT_RECOVER_TP）`);
      else u.tp = Math.min(attr(u, 'TP_MAX'), u.tp + 1);
      for (const id of Object.keys(u.cd)) if (u.cd[id] > 0) u.cd[id]--;
      for (const k of Object.keys(u.uses)) if (k.endsWith(':t')) u.uses[k] = 0;
      for (const b of u.buffs.slice()) {
        if (b.def.end !== 1 && Number.isFinite(b.turns)) { b.turns--; b.age = (b.age || 0) + 1; if (b.turns <= 0) removeBuff(u, b, '结束'); }
      }
      for (const L of Object.values(u.limits)) L.turn = 0;
      u.damagedHits = 0;
      // Tile-owned active_time 28 effects: 「停留时施加 X」 (燃烧/黑泥/
      // 圣域 …). Fires once per action for the tile the unit ENDS on.
      if (u.alive) {
        const tile = grid.at(u.x, u.y);
        if (tile) runFieldSpecs(u, tile, 28);
      }
      touch(u);
    }
    // Client BUFF specialities with duration 0 are 「0回合（行动中）」: they
    // last only for the CURRENT turn (including its 再行动), then expire when
    // the turn passes on (Logic_Buff ChangeTurn). 380 client rows use this —
    // 被攻击前获得格挡3, 行动开始获得伤害2, 冰雪暴附属被动「接下来的技能消耗
    // 为0，持续至行动结束」. Treating them as permanent made all of those
    // stack up for the rest of the battle. Duration -1 stays permanent.
    function expireActionScoped() {
      for (const u of units) {
        if (!u.buffs?.length) continue;
        for (const b of u.buffs.slice()) if (b.actionScoped) {
          removeBuff(u, b, '行动结束失效');
          bump(cov.executed, 'ACTION_SCOPED_EXPIRE');
        }
      }
    }

    for (round = 1; round <= maxRounds && !winner; round++) {
      releasePending();
      sim.round = round;
      applySwapTimers();
      for (const u of units) if (u.alive) { fire(26, u, {target: u}); fire(52, u, {target: u}); }
      refreshAuras();
      // WaitTimeView (decrypted client bytecode) exposes wait_time /
      // AdjustWaitTime / SetUnitTempWaitTime / ResetWaitTime / SortItems:
      // the action bar re-sorts whenever a unit's speed changes. We therefore
      // read the LIVE speed before every single turn instead of freezing the
      // order at the start of the round.
      // Speed reads for ordering must not consume the battle RNG or pollute
      // coverage: run them in probe mode and bypass the static attr cache so
      // the value is always the CURRENT one, not a cached earlier state.
      const speedCache = new Map();
      let speedEpoch = -1;
      const turnSpeed = u => {
        if (speedEpoch !== sim.epoch) { speedCache.clear(); speedEpoch = sim.epoch; }
        if (speedCache.has(u.uid)) return speedCache.get(u.uid);
        const was = sim.probe; sim.probe = true;
        let v;
        try { v = attrRaw(u, 'SPEED', null); } finally { sim.probe = was; }
        speedCache.set(u.uid, v);
        return v;
      };
      const rankPending = pending => [...pending].filter(u => u.alive && !u.noTurn)
        .map(u => ({u, spd: turnSpeed(u)}))
        .sort((a, b) => b.spd - a.spd || a.u.order - b.u.order);
      // Client `unit.mobility = 0` + a 「不会主动攻击」basic skill means the
      // summon has NO turn (灵感星核 / 虚空投影). They stay on the board for
      // auras, [失焦], 阵营 counts and as targets; they just never act.
      const pending = new Set(units.filter(u => u.alive && !u.noTurn));
      // Summons created during this round (including battle-start ones) take
      // their own action in the same live-speed turn order — unless the client
      // declares them immobile/inert.
      const drainSummons = () => {
        while (sim.newUnits.length) {
          const nu = sim.newUnits.shift();
          if (!nu.alive) continue;
          if (!nu.noTurn) { pending.add(nu); if (!roundStartSpeeds.has(nu.uid)) roundStartSpeeds.set(nu.uid, turnSpeed(nu)); }
        }
      };
      // Inert summons still resolve their 每人回合开始/结束 specialities (e.g.
      // 灵感星核 21730「行动结束或被击败时使召唤者释放灵感伤害」at=28/12).
      for (const u of units) if (u.alive && u.noTurn) {
        fire(27, u, {target: u});
        fire(52, u, {target: u});
      }
      const roundStartSpeeds = new Map([...pending].map(u => [u.uid, turnSpeed(u)]));
      drainSummons();
      const flush = () => {
        // Turn-boundary sub-casts (每人回合结束 28 / 行动后 43) resolved during
        // endTurn()/fireActionEnd() have no actOnce() parent step. Attach their
        // real hits to the step that owns those events BEFORE pushing events.
        if (steps.length) drainPendingSubHits(steps[steps.length - 1]);
        if (events.length && steps.length) { steps[steps.length - 1].events.push(...events); events = []; steps[steps.length - 1].snap = snapshot(); steps[steps.length - 1].placed = placedSnap(); }
      };
      // One unit turn: 每人回合开始 → (控制则跳过) → 行动 / 再行动 → 每人回合结束.
      const takeTurn = (unit, bonus) => {
        sim.turnOwner = unit;
        startTurn(unit);
        if (!unit.alive) return;
        const ctrl = unit.buffs.find(b => isControlBuff(b) && buffOn(b));
        if (ctrl) {
          log(`${unit.name} 处于「${ctrl.def.n}」，无法行动`);
          unit.flags.choiceGroup = null;
          revokeTemp(unit, null, '无法行动');
          endTurn(unit);
          expireActionScoped();
          pushStep({round, actor: unit.uid, kind: 'skip', from: {x: unit.x, y: unit.y}, to: {x: unit.x, y: unit.y},
                    text: `${bonus ? '新回合：' : ''}处于「${ctrl.def.n}」，无法行动`});
          return;
        }
        act(unit, bonus);
        let extra = 0;
        while (unit.alive && unit.flags.reAct && extra < 2 && !checkWinQuiet()) {
          unit.flags.reAct = false; unit.flags.reActs = ++extra;
          act(unit, true);
        }
        unit.flags.reAct = false;
        unit.flags.reActSkill = 0;
        unit.flags.choiceGroup = null;
        revokeTemp(unit, null, '本回合行动结束');
        endTurn(unit);
        expireActionScoped();
        flush();
      };
      while (pending.size && !winner) {
        drainSummons();
        const ranked = rankPending(pending);
        if (!ranked.length) break;
        const unit = ranked[0].u;
        pending.delete(unit);
        if (!unit.alive || winner) continue;
        // Report a live reorder when this unit's speed changed mid-round.
        const nowSpd = turnSpeed(unit);
        const before = roundStartSpeeds.get(unit.uid);
        if (DYNAMIC_ORDER && before != null && Math.abs(nowSpd - before) > 0.01 && ranked.length > 1) {
          const next = ranked[1];
          log(`${unit.name} 速度 ${Math.round(before)} → ${Math.round(nowSpd)}，按实时速度重排行动顺序（下一位 ${next.u.name} ${Math.round(next.spd)}）`);
          orderChanges++;
        }
        stepOrder = ranked.slice(0, 8).map(x => ({uid: x.u.uid, name: x.u.name, spd: Math.round(x.spd)}));
        takeTurn(unit, false);
        if (checkWin()) break;
        // RE_ROUND（新回合）granted to teammates during this turn.
        let bonusTurns = 0;
        while (sim.extraTurns.length && bonusTurns < 3 && !checkWinQuiet()) {
          const next = sim.extraTurns.shift();
          if (!next.alive) continue;
          bonusTurns++;
          takeTurn(next, true);
        }
        sim.extraTurns.length = 0;
        if (checkWin()) break;
      }
      for (const u of units) if (u.alive) {
        fire(29, u, {target: u});
        if (u.noTurn) { fire(28, u, {target: u}); fire(51, u, {target: u}); }
      }
      fireObject(29, {});                      // 每回合结束：雪人生成蜜果 + 碎冰
      if (steps.length) drainPendingSubHits(steps[steps.length - 1]);
      if (events.length && steps.length) { steps[steps.length - 1].events.push(...events); events = []; steps[steps.length - 1].snap = snapshot(); steps[steps.length - 1].placed = placedSnap(); }
      checkWin();
    }
    const rounds = Math.min(round - (winner ? 0 : 1), maxRounds);
    let verdict;
    if (!winner) {
      const pct = side => units.filter(u => u.side === side).reduce((a, u) => a + u.hp / maxHpOf(u), 0)
        / Math.max(1, units.filter(u => u.side === side).length);
      const a = pct('A'), b = pct('B');
      winner = Math.abs(a - b) < 0.005 ? 'draw' : (a > b ? 'A' : 'B');
      verdict = `达到 ${maxRounds} 回合上限，按剩余生命比例判定（我方 ${(a * 100).toFixed(1)}% / 敌方 ${(b * 100).toFixed(1)}%）`;
    } else {
      verdict = `${winner === 'A' ? '敌方' : '我方'}全部被击败`;
    }
    pushStep({round: rounds, kind: 'end', text: `战斗结束：${winner === 'draw' ? '平局' : (winner === 'A' ? '我方' : '敌方') + '胜利'} · ${verdict}`});
    const mvp = units.slice().sort((a, b) => b.tally.dealt + b.tally.healed - a.tally.dealt - a.tally.healed)[0];
    for (const u of units) { u.maxHp = maxHpOf(u); u.stats.spd = Math.round(attr(u, 'SPEED')); }
    const specTotal = units.reduce((a, u) => a + u.passive.length, 0);
    // `unmappedTiming` is an ENGINE-CAPABILITY guard, not a per-battle
    // activity log: list client timings declared by these units for which
    // there is NO fire()/fireObject() call site at all. A conditional timing
    // (援防前 34, 被援攻后 41 …) that simply did not occur this battle is NOT
    // unmapped — `firedTimings` above already reports those.
    // active_time 1 = ANY is declarative (attrCompute / refreshAuras / the
    // skill's own at=1 dispatch), so it is excluded.
    const ENGINE_TIMINGS = new Set([2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,
      19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,
      42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65]);
    for (const u of units) {
      const seen = new Set();
      for (const inst of [...u.passive, ...(u.skills || []).flatMap(s => (s.sp || [])
        .map(sid => ({sid, spec: M?.specs?.[sid]})))]) {
        const raw = inst.spec?.at ?? inst.at;
        const at = Number(raw);
        if (!at || at === 1 || !Number.isFinite(at) || seen.has(at)) continue;
        seen.add(at);
        if (!ENGINE_TIMINGS.has(at)) bump(cov.unmappedTiming, String(at));
      }
    }
    return {
      grid, units, steps, winner, rounds, verdict, spawnArea: spawns.size,
      summons: summoned.map(u => ({uid: u.uid, name: u.name, side: u.side, npcId: u.npcId,
        summoner: u.summoner, hp: u.hp, actions: u.tally.actions})),
      initial: initialSnap, mvp: mvp?.uid, inspect,
      placed: placed.filter(o => o.alive).map(o => ({kind: o.kind, id: o.id, name: o.name,
        x: o.x, y: o.y, side: o.side, owner: o.owner?.uid})),
      spawns: {A: spawns.A.map((c, i) => ({x: c.x, y: c.y, dir: spawns.facing?.A?.[i] || [1, 0]})),
               B: spawns.B.map((c, i) => ({x: c.x, y: c.y, dir: spawns.facing?.B?.[i] || [-1, 0]})),
               custom: spawns.customApplied || 0, requested: spawns.customRequested || 0},
      summary: units.map(u => ({uid: u.uid, side: u.side, name: u.name, alive: u.alive, hp: u.hp, maxHp: maxHpOf(u), ...u.tally})),
      orderChanges, substrateLoaded: !!SUB, substratePhases: PHASES,
      mechanics: {
        loaded: !!M, passiveEffects: specTotal,
        executed: cov.executed, skipped: cov.skipped, limits: cov.limits,
        luaUnknown: cov.luaUnknown, conditions: cov.conditions,
        firedTimings: [...cov.firedTimings].map(Number).sort((a, b) => a - b),
        unmappedTiming: cov.unmappedTiming,
        weather: env.weatherId && M?.weather?.[env.weatherId] ? M.weather[env.weatherId].name : '',
        weatherChanged: sim.weatherId && M?.weather?.[sim.weatherId]
          ? {id: sim.weatherId, name: M.weather[sim.weatherId].name, aura: M.weather[sim.weatherId].aura} : null,
      },
    };
  }

  function damageOf() { return {amount: 0}; }

  function logText(result, meta = {}) {
    const byId = new Map(result.units.map(u => [u.uid, u]));
    const lines = [`# 铃兰档案馆 · 自动对局模拟`, `地图：${result.grid.name}（#${result.grid.id}）`,
      `种子：${meta.seed ?? ''} · 技能轴：${meta.modeLabel ?? ''} · 回合上限：${meta.maxRounds ?? ''}`
        + (result.mechanics?.weather ? ` · 天气：${result.mechanics.weather}` : ''), ''];
    for (const side of ['A', 'B']) {
      lines.push((side === 'A' ? '我方' : '敌方') + '：' + result.units.filter(u => u.side === side)
        .map(u => `${u.name}（${u.profName}，生命 ${u.maxHp}，速度 ${u.stats.spd}）`).join('、'));
    }
    lines.push('');
    let round = -1;
    for (const s of result.steps) {
      if (s.round !== round && s.kind !== 'end') { round = s.round; if (round > 0) lines.push(`== 第 ${round} 回合 ==`); }
      const who = s.actor ? `[${byId.get(s.actor).side === 'A' ? '我方' : '敌方'}] ${byId.get(s.actor).name}：` : '';
      lines.push(`${String(s.seq).padStart(3, ' ')}. ${who}${s.text}`);
      for (const e of s.events || []) lines.push(`       · ${e}`);
    }
    lines.push('', '统计：');
    for (const u of result.summary) {
      lines.push(`  [${u.side === 'A' ? '我方' : '敌方'}] ${u.name}：输出 ${u.dealt}，承伤 ${u.taken}，治疗 ${u.healed}，击败 ${u.kills}，${u.alive ? '存活 ' + u.hp + '/' + u.maxHp : '阵亡'}`);
    }
    const m = result.mechanics;
    if (m?.loaded) {
      const fmt = o => Object.entries(o).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${k}×${v}`).join('、') || '无';
      lines.push('', '机制覆盖：', `  已执行：${fmt(m.executed)}`, `  未执行的效果类型：${fmt(m.skipped)}`,
                 `  无法求值的 Lua 条件：${fmt(m.luaUnknown)}`,
                 `  条件判定：通过 ${m.conditions.pass} / 未通过 ${m.conditions.fail} / 无法求值 ${m.conditions.unknown}`);
    }
    return lines.join('\n');
  }

  // ---- 乐土群星杯: ONE construction for the page AND every test harness ----
  // The page used its own cupMembers()/cupEnv(); test scripts rebuilt teams
  // with `prof: profName` (a string → every fighter fell back to 职业 6) and
  // without `skillRoles`, so they validated a DIFFERENT battle than the one
  // shown to the user (职能克制, 个性技能分组). Both now call these.
  function cupFighters(team, opts = {}) {
    return (team?.members || []).slice(0, 8).map(m => ({
      name: m.name, stats: {...m.stats}, move: {...m.move}, prof: m.prof, profName: m.profName,
      skills: (m.skills || []).map(s => ({...s})), edited: false,
      kit: opts.eliteComp && m.kit?.eliteComp?.length
        ? {...m.kit, personality: [...(m.kit.personality || []), ...m.kit.eliteComp]} : m.kit,
      npcId: m.npcId, star: m.star, statLevel: m.statLevel, cupTeam: team.name,
      skillRoles: Object.fromEntries((m.allSkills || []).filter(s => /个性/.test(s.role || ''))
        .map(s => [Number(s.id), s.role])),
    }));
  }
  function cupEnv(sched, teams) {
    if (!sched) return {};
    const side = t => t === 1 ? 'A' : t === 2 ? 'B' : 'both';
    const buffs = (sched.buffDetails || []).filter(b => b.buffId).map(b => ({buffId: b.buffId, side: side(b.target)}));
    const unitStatus = [];
    for (const st of sched.unitStatus || []) {
      const s = st.teamIndex === 1 ? 'A' : 'B';
      const index = (teams?.[s] || []).findIndex(m => m && typeof m === 'object' && Number(m.npcId) === Number(st.npcId));
      if (index >= 0 && st.buffId) unitStatus.push({buffId: st.buffId, side: s, index});
    }
    return {buffs, unitStatus};
  }

  return {simulate, prepareMap, spawnCells, skillSet, normalizeFighter, legacySkill,
          castShape, castRangeOffsets, castRangeCells, RANGE_SELECT,
          damageOf, logText, rng, AI_NOTES, Lua, cupFighters, cupEnv};
})();
