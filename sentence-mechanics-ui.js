/* Sentence-level mechanisms: every sentence of a skill / personality
   description -> client speciality rows -> the battle-engine code that runs
   them (data built by scripts/build_sentence_mechanics.py).

   window.WikiSentence.attach(host, skillId, {compact})
     Renders the sentence list into `host` (lazy-loads one shard).
   window.WikiSentence.personality(host, rowId)
     Renders a personality's skills per star level.
   window.WikiSentence.mechanismsView()
     Full catalog of shared mechanisms with code (route #/sentence-mechanics). */
(function () {
  'use strict';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const INDEX = () => window.WIKI_SENTENCE_INDEX || null;
  const CODE = () => window.WIKI_MECHANICS_CODE || null;
  const SHARDS = () => window.WIKI_SENTENCE_SHARDS || (window.WIKI_SENTENCE_SHARDS = {});
  const pending = new Map();

  function script(src, ready) {
    if (ready()) return Promise.resolve();
    if (!pending.has(src)) {
      pending.set(src, new Promise((resolve, reject) => {
        const s = document.createElement('script');
        s.src = src;
        s.onload = () => { s.remove(); ready() ? resolve() : reject(new Error('数据文件内容不完整：' + src)); };
        s.onerror = () => { s.remove(); pending.delete(src); reject(new Error('本地文件载入失败：' + src)); };
        document.head.appendChild(s);
      }));
    }
    return pending.get(src);
  }
  const loadIndex = () => script('data/sentence-mechanics.js', () => !!INDEX());
  const loadCode = () => script('data/mechanics-code.js', () => !!CODE());
  async function loadShard(skillId) {
    await loadIndex();
    const n = Number(skillId) % (INDEX().shards || 64);
    await script(`data/sentence-mechanics/${n}.js`, () => !!SHARDS()[n]);
    return SHARDS()[n];
  }

  const STATUS = {
    impl: ['已实装', 'ok'], decl: ['声明型·已接入读取点', 'ok'], visual: ['纯表现（无战斗效果）', 'muted'],
    tag: ['分类标签', 'muted'], stub: ['未实装', 'bad'], missing: ['未实装', 'bad'], 'timing-missing': ['时点未派发', 'bad'],
    note: ['无需结算逻辑', 'muted'], audited: ['已核实·无需实现', 'ok'],
  };
  const statusChip = st => {
    const [label, tone] = STATUS[st] || [st || '未知', 'muted'];
    return `<span class="sm-status sm-${tone}">${esc(label)}</span>`;
  };
  const commonLabel = (id) => {
    const c = CODE()?.common?.[id];
    if (c) return c.label;
    const [kind, key] = id.split(':');
    return {core: key, type: key, at: '时点 ' + key, attr: key, eff: key, lua: 'Lua ' + key, sj: 'sparam.' + key, id: '#' + key}[kind] || id;
  };
  const refChip = id => `<button type="button" class="sm-ref" data-sm-ref="${esc(id)}" title="查看实现代码">${esc(commonLabel(id))}</button>`;

  function specBlock(shard, sid, depth = 0) {
    const e = shard.specs?.[sid];
    if (!e) return '';
    const refs = (e.refs || []).map(refChip).join('');
    const buffs = (e.buffs || []).map(bid => {
      const b = shard.buffs?.[bid];
      if (!b) return '';
      const kids = depth < 2 ? (b.sp || []).map(x => specBlock(shard, x, depth + 1)).join('') : '';
      return `<div class="sm-buff"><div class="sm-buff-head">状态 <b>[${esc(b.n)}]</b> <small>#${esc(bid)}</small>${(b.refs || []).map(refChip).join('')}</div>` +
        (b.d ? `<p class="sm-buff-desc">${esc(b.d)}</p>` : '') + kids + '</div>';
    }).join('');
    const kids = depth < 2 ? (e.kids || []).map(x => specBlock(shard, x, depth + 1)).join('') : '';
    const link = e.link ? `<div class="sm-link">联动施放技能 <a href="#/page/${100000000 + Number(e.link)}">#${esc(e.link)}</a></div>` : '';
    return `<div class="sm-spec" data-depth="${depth}">
      <div class="sm-spec-head"><code>#${esc(sid)}</code><b>${esc(e.t)}</b>${statusChip(e.st)}<span class="sm-spec-text">${esc(e.text)}</span></div>
      ${e.n ? `<div class="sm-spec-name">客户端编辑名：${esc(e.n)}</div>` : ''}
      ${e.c ? `<details class="sm-cond"><summary>触发条件（客户端 Lua）</summary><pre>${esc(e.c)}</pre></details>` : ''}
      ${e.dp ? `<details class="sm-cond"><summary>动态参数（客户端 Lua）</summary><pre>${esc(e.dp)}</pre></details>` : ''}
      <div class="sm-refs">${refs}</div>${link}${buffs}${kids}</div>`;
  }

  function sentenceRows(shard, skillId) {
    const sk = shard.skills?.[skillId];
    if (!sk) return '';
    const rows = sk.s.map((r, i) => {
      const specs = (r.s || []).map(x => specBlock(shard, x)).join('');
      const buffs = (r.b || []).filter(b => !(r.s || []).some(x => (shard.specs[x]?.buffs || []).includes(b))).map(bid => {
        const b = shard.buffs?.[bid];
        return b ? `<div class="sm-buff"><div class="sm-buff-head">提及状态 <b>[${esc(b.n)}]</b> <small>#${esc(bid)}</small>${(b.refs || []).map(refChip).join('')}</div>${(b.sp || []).map(x => specBlock(shard, x, 1)).join('')}</div>` : '';
      }).join('');
      const skills = (r.k || []).map(k => `<a class="sm-skill-link" href="#/page/${100000000 + Number(k)}">技能 #${esc(k)}</a>`).join('');
      const common = (r.c || []).map(refChip).join('');
      const count = (r.s || []).length;
      const refs = r.c || [];
      const noteOnly = !count && !r.b && !r.k && refs.length > 0 && refs.every(x => x.startsWith('note:'));
      const tag = count ? `<span class="sm-count">${count} 条客户端特技</span>`
        : noteOnly ? '<span class="sm-count is-none">描述性文字</span>'
        : (refs.length || r.b || r.k) ? '<span class="sm-count is-soft">通用机制</span>'
        : '<span class="sm-count is-none">描述性文字</span>';
      return `<li class="sm-sentence"><details${i === 0 && count ? ' open' : ''}><summary><span class="sm-index">${i + 1}</span><span class="sm-text">${esc(r.t)}</span>${tag}</summary>
        <div class="sm-body">${common ? `<div class="sm-common"><span>共性机制</span>${common}</div>` : ''}${specs}${buffs}${skills ? `<div class="sm-skills">${skills}</div>` : ''}</div></details></li>`;
    }).join('');
    const extra = (sk.x || []).length ? `<details class="sm-extra"><summary>描述中未直接提及、但技能实际携带的 ${sk.x.length} 条特技</summary>${sk.x.map(x => specBlock(shard, x)).join('')}</details>` : '';
    return `<ol class="sm-list">${rows}</ol>${extra}`;
  }

  async function attach(host, skillId, opts = {}) {
    if (!host || !skillId) return;
    host.innerHTML = '<p class="sm-loading">正在载入逐句机制…</p>';
    let shard;
    try { shard = await loadShard(skillId); } catch (e) { host.innerHTML = `<p class="sm-loading">逐句机制未能载入：${esc(e.message)}</p>`; return; }
    if (!host.isConnected) return;
    const sk = shard?.skills?.[skillId];
    if (!sk) { host.innerHTML = opts.compact ? '' : '<p class="sm-loading">此技能没有可归纳的客户端描述。</p>'; return; }
    const meta = INDEX()?.meta || {};
    host.innerHTML = `${opts.compact ? '' : `<p class="sm-intro">把技能描述逐句拆开，每句对应到客户端特技（<code>speciality</code> 表）与自动对局引擎中执行它的代码。点击带色标签查看共性机制的实现代码（${esc(meta.engine || 'battle-sim-core.js')}，共 ${esc(meta.engineLines || '')} 行，行号随引擎每次构建自动更新）。</p>`}${sentenceRows(shard, String(skillId))}`;
  }

  async function personality(host, rowId) {
    if (!host) return;
    await loadIndex().catch(() => null);
    const p = INDEX()?.personalities?.[rowId];
    if (!p) { host.innerHTML = ''; return; }
    const stars = Object.keys(p.stars).map(Number).sort((a, b) => b - a);
    host.innerHTML = `<div class="sm-stars" role="tablist">${stars.map((s, i) => `<button type="button" class="sm-star${i === 0 ? ' is-active' : ''}" data-sm-star="${s}">${s} 星</button>`).join('')}</div><div class="sm-star-body"></div>`;
    const body = host.querySelector('.sm-star-body');
    const show = async star => {
      host.querySelectorAll('[data-sm-star]').forEach(b => b.classList.toggle('is-active', Number(b.dataset.smStar) === star));
      const ids = p.stars[star] || [];
      body.innerHTML = ids.map(id => `<section class="sm-pers-skill"><h4><a href="#/page/${100000000 + Number(id)}">个性技能 #${esc(id)}</a></h4><div data-sm-host="${esc(id)}"></div></section>`).join('') || '<p class="sm-loading">该星级没有个性技能。</p>';
      for (const id of ids) {
        const h = body.querySelector(`[data-sm-host="${id}"]`);
        await attach(h, id, {compact: true});
        const shard = SHARDS()[Number(id) % (INDEX().shards || 64)];
        const name = shard?.skills?.[id]?.n;
        if (name) h.previousElementSibling.querySelector('a').textContent = name;
      }
    };
    host.addEventListener('click', e => { const b = e.target.closest('[data-sm-star]'); if (b) show(Number(b.dataset.smStar)); });
    show(stars[0]);
  }

  /* ---------- shared mechanism popover with code ---------- */
  function codeMarkup(c) {
    const anchors = (c.anchors || []).map(a => `<figure class="sm-anchor"><figcaption><code>${esc(a.f)}:${esc(a.l)}</code> <b>${esc(a.sym)}</b> <span>${esc(a.role)}</span></figcaption><pre>${esc(a.code)}</pre></figure>`).join('');
    const client = c.client ? `<p class="sm-client">客户端 speciality_type #${esc(c.client.speciality_type)}　参数：${(c.client.params || []).map((x, i) => x ? `p${i}=${esc(x)}` : '').filter(Boolean).join('　') || '—'}${c.client.sparam ? '　sparam=' + esc(c.client.sparam) : ''}</p>` : '';
    const tail = anchors || (c.impl === 'note'
      ? '<p class="sm-loading">这一句没有对应的结算代码；上方说明了它在客户端数据里的性质。</p>'
      : c.impl === 'audited'
        ? '<p class="sm-loading">该参数没有独立处理器；上方给出 192 场全量扫描的核实结论。</p>'
        : '<p class="sm-loading">没有可定位的代码。</p>');
    return `<div class="sm-pop-head"><h3>${esc(c.label)}</h3>${statusChip(c.impl)}</div>${c.doc ? `<p class="sm-doc">${esc(c.doc)}</p>` : ''}${client}${tail}`;
  }
  let pop = null;
  async function openRef(id, anchor) {
    if (!pop) {
      pop = document.createElement('div');
      pop.className = 'sm-pop'; pop.setAttribute('role', 'dialog'); pop.setAttribute('aria-label', '机制实现代码');
      document.body.appendChild(pop);
      pop.addEventListener('click', e => { if (e.target.closest('[data-sm-close]')) closePop(); });
    }
    pop.innerHTML = '<button type="button" class="sm-close" data-sm-close aria-label="关闭">×</button><p class="sm-loading">正在载入实现代码…</p>';
    pop.hidden = false;
    try { await loadCode(); } catch (e) { pop.innerHTML = `<button type="button" class="sm-close" data-sm-close>×</button><p>${esc(e.message)}</p>`; return; }
    const c = CODE().common[id];
    pop.innerHTML = '<button type="button" class="sm-close" data-sm-close aria-label="关闭">×</button>' + (c ? codeMarkup(c) : `<p>未找到机制 ${esc(id)}。</p>`) +
      `<a class="sm-all" href="#/sentence-mechanics?m=${encodeURIComponent(id)}">在机制总表中查看</a>`;
  }
  function closePop() { if (pop) pop.hidden = true; }
  document.addEventListener('click', e => {
    const b = e.target.closest?.('[data-sm-ref]');
    if (b) { e.preventDefault(); openRef(b.dataset.smRef, b); return; }
    if (pop && !pop.hidden && !e.target.closest('.sm-pop')) closePop();
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closePop(); });

  /* ---------- #/sentence-mechanics catalog ---------- */
  const CATS = {core: '核心规则', type: '客户端特技类型', at: '触发时点', attr: '属性', eff: '状态效果类型', lua: 'Lua 条件 API', sj: '复合参数 sparam', id: '角色/技能专属处理', note: '说明性归类（无结算逻辑）'};
  async function mechanismsView(main, params) {
    main.innerHTML = '<div class="data-loading" role="status"><span></span>正在载入机制总表…</div>';
    try { await Promise.all([loadCode(), loadIndex()]); } catch (e) { main.innerHTML = `<p>${esc(e.message)}</p>`; return; }
    const C = CODE(), meta = C.meta || {};
    const groups = {};
    for (const [id, c] of Object.entries(C.common)) (groups[id.split(':')[0]] ||= []).push([id, c]);
    const counts = {};
    for (const c of Object.values(C.common)) counts[c.impl] = (counts[c.impl] || 0) + 1;
    const focus = params?.get?.('m') || '';
    main.innerHTML = `<header class="page-heading"><span class="eyebrow">MECHANICS → CODE</span><h1>逐句机制与实现代码</h1>
      <p>${esc(meta.skills)} 个技能、${esc(meta.sentences)} 句描述（${esc(meta.mapped)} 句已映射，${esc(meta.withSpec)} 句直接命中客户端特技），${esc(meta.specs)} 条特技、${esc(meta.buffs)} 个状态，归纳为 ${esc(meta.common)} 个共性机制、${esc(meta.anchors)} 处代码锚点。代码行号对应 <code>${esc(meta.engine)}</code>（${esc(meta.engineLines)} 行），随每次构建重新计算。</p>
      <p class="sm-summary">${Object.entries(counts).map(([k, n]) => `${statusChip(k)} ${n}`).join('　')}${(meta.gaps || []).length ? `　未覆盖 ${meta.gaps.length} 类` : '　<b>无未覆盖的客户端类型</b>'}</p></header>
      <div class="sm-filter"><input type="search" placeholder="筛选机制（名称 / 类型 / 函数名）" aria-label="筛选机制" value="${esc(focus)}"></div>
      ${Object.keys(CATS).filter(k => groups[k]).map(k => `<section class="content-card sm-cat"><h2>${CATS[k]} <span class="heading-count">${groups[k].length}</span></h2>
        ${groups[k].sort((a, b) => a[1].label.localeCompare(b[1].label, 'zh')).map(([id, c]) => `<details class="sm-mech" data-sm-id="${esc(id)}" data-sm-search="${esc((id + ' ' + c.label + ' ' + (c.anchors || []).map(a => a.sym).join(' ')).toLowerCase())}"${id === focus ? ' open' : ''}><summary><b>${esc(c.label)}</b>${statusChip(c.impl)}<small>${(c.anchors || []).length} 处代码</small></summary>${codeMarkup(c)}</details>`).join('')}</section>`).join('')}`;
    const input = main.querySelector('.sm-filter input');
    const apply = () => {
      const q = input.value.trim().toLowerCase();
      for (const d of main.querySelectorAll('.sm-mech')) d.hidden = !!q && !d.dataset.smSearch.includes(q);
    };
    input.addEventListener('input', apply); apply();
    if (focus) main.querySelector(`[data-sm-id="${CSS.escape(focus)}"]`)?.scrollIntoView({block: 'center'});
  }

  window.WikiSentence = {attach, personality, mechanismsView, loadShard, loadCode};
})();
