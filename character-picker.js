/* Shared character picker for the offline tools.
 *
 * One implementation for every tool that needs to choose a character: it uses
 * the same WikiCatalog facets / filter / sort rules as the main roster, the
 * same pinyin search as the global search box, and the same avatar cards.
 *
 *   const page = await WikiCharacterPicker.open({ current, pages, title, note });
 *   // -> the selected page object, or null when dismissed.
 *
 * ``pages`` defaults to the character pages of WIKI_DATA; callers may pass a
 * subset (e.g. only characters the panel calculator has numbers for).
 */
(() => {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g,
    c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

  let host = null, resolvePick = null, current = null, pages = [], state = null;

  function defaults() {
    return {q: '', rarity: '', profession: '', faction: '', sort: 'source'};
  }

  function sourcePages(provided) {
    const list = provided || (window.WIKI_DATA?.pages || []).filter(p => p.type === 'character' && !p.redirect);
    return list.map(p => ({
      ...p,
      title: p.title || p.name || '',
      aliases: p.aliases || '',
      summary: p.summary || '',
      rarity: p.rarity || '',
      class: p.class || '',
      faction: p.faction || '',
    }));
  }

  function pinyinHit(p, q) {
    try { return window.WikiSearch?.pinyinHit?.(p, q) || false; }
    catch (_) { return false; }
  }

  function visible() {
    const C = window.WikiCatalog;
    if (!C) {
      const q = state.q.trim().toLowerCase();
      return pages.filter(p => !q || String(p.name).toLowerCase().includes(q));
    }
    return C.sort(C.filter(pages, {
      q: state.q, rarity: state.rarity, profession: state.profession, faction: state.faction,
    }, pinyinHit), state.sort, false);
  }

  function facetsMarkup() {
    const C = window.WikiCatalog;
    if (!C) return '';
    const f = C.facets(pages);
    const row = (key, label, values) => `<div class="char-picker-facet"><span>${label}</span><div>${['', ...values].map(v =>
      `<button type="button" class="chip${state[key] === v ? ' active' : ''}" data-cp-facet="${key}" data-value="${esc(v)}" aria-pressed="${state[key] === v}">${esc(v || '全部')}</button>`).join('')}</div></div>`;
    return `<div class="char-picker-facets">${row('rarity', '稀有度', f.rarities)}${row('profession', '职业', f.professions)}${row('faction', '阵营', f.factions)}</div>`;
  }

  function shell(title, note) {
    const C = window.WikiCatalog;
    const sorts = C?.SORT_OPTIONS || [{value: 'source', label: '原站角色顺序'}];
    host = document.createElement('div');
    host.className = 'char-picker-backdrop';
    host.innerHTML = `<section class="char-picker" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <header class="char-picker-head"><div><span class="eyebrow">CHARACTER PICKER</span><h2>${esc(title)}</h2></div>
        <button type="button" class="char-picker-close" data-cp-close aria-label="关闭">×</button></header>
      <div class="char-picker-tools"><input class="char-picker-search" type="search" placeholder="搜索名称、别名或关键词（支持拼音首字母）" aria-label="搜索角色" autocomplete="off">
        <label>排序<select class="char-picker-sort" aria-label="排序方式">${sorts.map(o => `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join('')}</select></label></div>
      ${facetsMarkup()}
      <div class="char-picker-meta"><span data-cp-count></span><button type="button" class="text-button" data-cp-reset>重置筛选与排序</button></div>
      <div class="char-picker-grid" data-cp-grid></div>
      <footer class="char-picker-foot">${esc(note || '与角色图鉴共用筛选、排序与拼音搜索规则。')}</footer>
    </section>`;
    document.body.appendChild(host);
    return host;
  }

  function render() {
    if (!host) return;
    const list = visible();
    const count = host.querySelector('[data-cp-count]');
    const grid = host.querySelector('[data-cp-grid]');
    if (count) count.textContent = `${list.length} 位角色`;
    host.querySelectorAll('[data-cp-facet]').forEach(btn => {
      const on = state[btn.dataset.cpFacet] === btn.dataset.value;
      btn.classList.toggle('active', on);
      btn.setAttribute('aria-pressed', String(on));
    });
    const sortBox = host.querySelector('.char-picker-sort');
    if (sortBox && sortBox.value !== state.sort) sortBox.value = state.sort;
    if (!grid) return;
    grid.innerHTML = list.length ? list.map(p => {
      const img = p.sprite || p.avatar || p.image || '';
      const selected = current != null && String(current) === String(p.id);
      return `<button type="button" class="char-picker-card${selected ? ' selected' : ''}" data-cp-id="${esc(p.id)}" aria-pressed="${selected}">
        ${img ? `<img loading="lazy" src="${esc(img)}" alt="">` : '<span class="char-picker-placeholder"></span>'}
        <strong>${esc(p.name)}</strong><small>${esc(p.class || p.rarity || '角色')}</small>
        ${selected ? '<em>已选</em>' : ''}</button>`;
    }).join('') : '<p class="char-picker-empty">没有匹配的角色，试试更换关键词或重置筛选。</p>';
  }

  function finish(value) {
    if (!host) return;
    host.remove();
    host = null;
    document.removeEventListener('keydown', onKey, true);
    const done = resolvePick;
    resolvePick = null;
    current = null;
    pages = [];
    state = null;
    if (done) done(value);
  }

  function onKey(e) {
    if (e.key === 'Escape') { e.preventDefault(); finish(null); }
  }

  function open(options = {}) {
    if (host) finish(null);
    state = defaults();
    pages = sourcePages(options.pages);
    current = options.current ?? null;
    const title = options.title || '选择角色';
    shell(title, options.note);

    return new Promise(resolve => {
      resolvePick = resolve;
      host.addEventListener('click', e => {
        const target = e.target.closest('button');
        if (!target) {
          if (e.target === host) finish(null);
          return;
        }
        if (target.hasAttribute('data-cp-close')) { finish(null); return; }
        if (target.hasAttribute('data-cp-reset')) { state = defaults(); host.querySelector('.char-picker-search').value = ''; render(); return; }
        const facet = target.dataset.cpFacet;
        if (facet) { state[facet] = target.dataset.value; render(); return; }
        if (target.dataset.cpId !== undefined) {
          const page = pages.find(p => String(p.id) === String(target.dataset.cpId));
          if (page) finish(page);
        }
      });
      host.addEventListener('input', e => {
        if (e.target.classList.contains('char-picker-search')) { state.q = e.target.value; render(); }
      });
      host.addEventListener('change', e => {
        if (e.target.classList.contains('char-picker-sort')) { state.sort = e.target.value; render(); }
      });
      document.addEventListener('keydown', onKey, true);
      render();
      host.querySelector('.char-picker-search')?.focus();
    });
  }

  window.WikiCharacterPicker = {open};
})();
