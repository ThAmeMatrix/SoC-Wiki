'use strict';
/* SoC 资源档案馆 — browse any archived version and compare any two of them. */
const $ = (s, r = document) => r.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const num = n => Number(n || 0).toLocaleString('zh-CN');
const size = b => {
  let v = Math.abs(Number(b || 0)), i = 0;
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return (i ? v.toFixed(v >= 100 ? 0 : 1) : v) + ' ' + u[i];
};
const signed = b => (b > 0 ? '+' : b < 0 ? '−' : '±') + size(b);
const KIND = {added: '新增', removed: '删除', modified: '修改', renamed: '改名'};
const SYM = {added: '+', removed: '−', modified: '~', renamed: '↔'};
const ICON = {table: '▦', image: '▣', sprite: '✦', text: '¶', data: '⧉', script: 'λ', audio: '♪', video: '▶',
  font: 'A', model: '△', bundle: '◫', program: '⚙', __sources: '⛁'};
const IMAGE = new Set(['.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif']);
const PAGE = 200;

const S = {info: null, versions: [], byId: {}, mode: 'browse', v: null, a: null, b: null, cat: null, group: null,
  kind: null, q: '', rows: [], total: 0, selected: -1, view: null, compare: null, seq: 0, labels: {}};

async function api(path, params = {}) {
  const query = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')).toString();
  const res = await fetch('/api/' + path + (query ? '?' + query : ''));
  const data = await res.json().catch(() => ({error: res.statusText}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}
const blobUrl = (e, download) => `/blob/${e.hash}${e.ext}` + (download ? '?download=' + encodeURIComponent(baseName(e.path)) : '');
const thumbUrl = e => `/thumb/${e.hash}${e.ext}`;
const baseName = p => String(p).split('/').pop();
const dirName = p => String(p).split('/').slice(0, -1).join('/');
const label = key => S.labels[key] || key;
function toast(text) {
  const el = $('#toast');
  el.textContent = text; el.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => { el.hidden = true; }, 3200);
}
function kindOf(e) {
  if (e.meta && e.meta.noblob) return 'missing';
  if (e.cat === 'table') return 'table';
  if (IMAGE.has(e.ext)) return 'image';
  if (e.ext === '.mp4' || e.ext === '.webm') return 'video';
  if (['.wav', '.ogg', '.mp3'].includes(e.ext)) return 'sound';
  if (e.cat === 'audio') return 'audio';
  if (e.ext === '.ttf' || e.ext === '.otf') return 'font';
  if (e.ext === '.obj') return 'model';
  if (['text', 'bundle'].includes(e.cat) || ['.json', '.txt', '.xml', '.ini', '.lua', '.csv', '.config'].includes(e.ext)) return 'text';
  return 'binary';
}

/* -- versions & routing ----------------------------------------------------- */
async function loadVersions() {
  S.versions = (await api('versions')).versions;
  S.byId = Object.fromEntries(S.versions.map(v => [v.id, v]));
  $('#version-count').textContent = S.versions.length ? `${S.versions.length} 个` : '';
  const options = [...S.versions].reverse().map(v => `<option value="${esc(v.id)}">${esc(v.label)}${v.game?.changeNumber ? ' · ' + esc(v.game.changeNumber) : ''}</option>`).join('');
  $('#pick-a').innerHTML = options; $('#pick-b').innerHTML = options;
}
function writeHash() {
  const p = new URLSearchParams();
  if (S.mode === 'browse') p.set('v', S.v); else { p.set('a', S.a); p.set('b', S.b); }
  if (S.cat) p.set('cat', S.cat);
  if (S.group) p.set('group', S.group);
  if (S.kind) p.set('kind', S.kind);
  if (S.q) p.set('q', S.q);
  const row = S.rows[S.selected];
  if (row) p.set('path', pathOf(row));
  history.replaceState(null, '', '#' + p.toString());
}
const pathOf = row => row.entry ? row.entry.path : row.change ? (row.change.new || row.change.old).path : row.file.rel;
function renderModes() {
  document.querySelectorAll('.modes button').forEach(b => b.setAttribute('aria-selected', String(b.dataset.mode === S.mode)));
  $('#compare-bar').style.visibility = S.versions.length > 1 ? 'visible' : 'hidden';
  if (S.mode === 'compare') { $('#pick-a').value = S.a; $('#pick-b').value = S.b; }
}
function renderTimeline() {
  const current = S.mode === 'browse' ? [S.v] : [S.a, S.b];
  $('#versions').innerHTML = [...S.versions].reverse().map(v => {
    const c = v.changes || {};
    const badges = v.parent
      ? (['added', 'modified', 'removed', 'renamed'].filter(k => c[k]).map(k => `<span class="badge ${k}" title="${KIND[k]}">${SYM[k]}${num(c[k])}</span>`).join('') || '<span class="badge">资源无变化</span>')
      : '<span class="badge first">首个版本</span>';
    const [date, time] = v.label.split(' ');
    const on = k => S.mode === 'compare' && S[k] === v.id ? ' on' : '';
    return `<li class="version${current.includes(v.id) ? ' current' : ''}" data-v="${esc(v.id)}">
      <div class="when">${esc(date)}<small>${esc(time || '')}</small></div>
      <div class="facts">游戏资源 ${esc(v.game?.changeNumber ?? '—')} · ${num(v.entries)} 项 · ${size(v.bytes)}</div>
      <div class="badges">${badges}</div>
      <div class="pick"><button type="button" class="${on('a')}" data-pick="a">设为基准</button><button type="button" class="${on('b')}" data-pick="b">设为目标</button>${v.parent ? '<button type="button" data-prev>对比上一版</button>' : ''}</div>
    </li>`;
  }).join('') || '<li class="empty">还没有版本</li>';
}
function filtersFrom(h) {
  S.cat = h?.get('cat') || null; S.group = h?.get('group') || null; S.kind = h?.get('kind') || null; S.q = h?.get('q') || '';
  $('#search').value = S.q;
}
async function openBrowse(vid, h) {
  S.mode = 'browse'; S.v = vid; filtersFrom(h); S.kind = null;
  S.view = await api('version', {id: vid});
  renderModes(); renderTimeline(); renderTree(); renderKinds();
  await loadList(true, h?.get('path'));
}
async function openCompare(a, b, h) {
  if (!a || !b) return;
  if (a === b) { toast('请选择两个不同的版本'); return; }
  S.mode = 'compare'; S.a = a; S.b = b; filtersFrom(h);
  $('#detail').innerHTML = '<div class="spin">正在比较…</div>';
  S.compare = await api('compare', {a, b});
  renderModes(); renderTimeline(); renderTree(); renderKinds();
  await loadList(true, h?.get('path'));
}

/* -- category tree ------------------------------------------------------------ */
function bar(counts, cls = 'mini') {
  const total = ['added', 'modified', 'removed', 'renamed'].reduce((s, k) => s + (counts[k] || 0), 0) || 1;
  return `<span class="${cls}">${['added', 'modified', 'removed', 'renamed'].map(k => counts[k] ? `<i class="${k}" style="width:${(counts[k] / total * 100).toFixed(1)}%"></i>` : '').join('')}</span>`;
}
const changeTotal = c => (c.added || 0) + (c.removed || 0) + (c.modified || 0) + (c.renamed || 0);
function renderTree() {
  const tree = $('#tree');
  if (S.mode === 'browse') {
    $('#tree-title').textContent = '分类 · ' + (S.byId[S.v]?.label || '');
    const cats = S.view.tree, total = cats.reduce((s, c) => s + c.count, 0);
    tree.innerHTML = `<div class="cat"><button type="button" data-cat="" aria-current="${!S.cat}"><span>◇</span><span class="name">全部资源</span><span class="count">${num(total)}</span></button></div>` +
      cats.map(c => `<div class="cat"><button type="button" data-cat="${esc(c.key)}" aria-current="${S.cat === c.key && !S.group}"><span>${ICON[c.key] || '•'}</span><span class="name">${esc(c.label)}</span><span class="count">${num(c.count)}</span></button>${S.cat === c.key ? `<div class="groups">${c.groups.slice(0, 600).map(g => `<button type="button" class="group" data-cat="${esc(c.key)}" data-group="${esc(g.key)}" aria-current="${S.group === g.key}" title="${esc(g.key)}"><span class="name">${esc(groupLabel(c.key, g.key))}</span><span class="count">${num(g.count)}</span></button>`).join('')}</div>` : ''}</div>`).join('');
    return;
  }
  const cmp = S.compare;
  $('#tree-title').textContent = '变化分类';
  tree.innerHTML = `<div class="cat"><button type="button" data-cat="" aria-current="${!S.cat}"><span>◇</span><span class="name">全部变化</span>${bar(cmp.total)}<span class="count">${num(cmp.changes)}</span></button></div>` +
    cmp.categories.map(c => `<div class="cat"><button type="button" data-cat="${esc(c.key)}" aria-current="${S.cat === c.key && !S.group}"><span>${ICON[c.key] || '•'}</span><span class="name">${esc(c.label)}</span>${bar(c.counts)}<span class="count">${num(changeTotal(c.counts))}</span></button>${S.cat === c.key ? `<div class="groups">${c.groups.slice(0, 600).map(g => `<button type="button" class="group" data-cat="${esc(c.key)}" data-group="${esc(g.key)}" aria-current="${S.group === g.key}" title="${esc(g.key)}"><span class="name">${esc(groupLabel(c.key, g.key))}</span>${bar(g)}<span class="count">${num(changeTotal(g))}</span></button>`).join('')}</div>` : ''}</div>`).join('') +
    (changeTotal(cmp.sources) ? `<div class="cat"><button type="button" data-cat="__sources" aria-current="${S.cat === '__sources'}"><span>${ICON.__sources}</span><span class="name">客户端文件</span>${bar(cmp.sources)}<span class="count">${num(changeTotal(cmp.sources))}</span></button></div>` : '');
}
const groupLabel = (cat, group) => cat === 'table' && S.info.tableGroups[group] ? `${S.info.tableGroups[group]}（${group}）` : group;
function renderKinds() {
  const box = $('#kinds');
  if (S.mode !== 'compare') { box.innerHTML = ''; return; }
  let counts = S.compare.total;
  if (S.cat === '__sources') counts = S.compare.sources;
  else if (S.cat) {
    const c = S.compare.categories.find(x => x.key === S.cat);
    counts = c ? (S.group ? (c.groups.find(g => g.key === S.group) || {}) : c.counts) : {};
  }
  const kinds = S.cat === '__sources' ? ['modified', 'added', 'removed'] : ['added', 'modified', 'removed', 'renamed'];
  if (S.cat === '__sources' && !S.kind) S.kind = 'modified';
  box.innerHTML = (S.cat === '__sources' ? '' : `<button type="button" data-kind="" aria-pressed="${!S.kind}">全部 ${num(changeTotal(counts))}</button>`) +
    kinds.map(k => `<button type="button" data-kind="${k}" aria-pressed="${S.kind === k}"${counts[k] ? '' : ' disabled'}>${KIND[k]} ${num(counts[k] || 0)}</button>`).join('');
}

/* -- list --------------------------------------------------------------------- */
async function loadList(reset, selectPath) {
  const seq = ++S.seq;
  if (reset) { S.rows = []; S.selected = -1; $('#rows').innerHTML = ''; $('#list-status').textContent = '加载中…'; }
  const offset = S.rows.length;
  let rows, total;
  try {
    if (S.mode === 'browse') {
      const data = await api('entries', {v: S.v, cat: S.cat, group: S.group, q: S.q, offset, limit: PAGE});
      rows = data.entries.map(entry => ({entry})); total = data.total;
    } else if (S.cat === '__sources') {
      const data = await api('sources', {a: S.a, b: S.b, kind: S.kind || 'modified', offset, limit: PAGE});
      rows = data.files.filter(f => !S.q || f.rel.toLowerCase().includes(S.q.toLowerCase())).map(file => ({file})); total = data.total;
    } else {
      const data = await api('changes', {a: S.a, b: S.b, cat: S.cat, group: S.group, kind: S.kind, q: S.q, offset, limit: PAGE});
      rows = data.changes.map(change => ({change})); total = data.total;
    }
  } catch (error) {
    if (seq === S.seq) $('#list-status').innerHTML = `<span class="err">${esc(error.message)}</span>`;
    return;
  }
  if (seq !== S.seq) return;
  const start = S.rows.length;
  S.rows.push(...rows); S.total = total;
  $('#rows').insertAdjacentHTML('beforeend', rows.map((r, i) => rowHtml(r, start + i)).join(''));
  $('#more').hidden = S.rows.length >= S.total;
  $('#more').textContent = `加载更多（还有 ${num(S.total - S.rows.length)} 项）`;
  const where = [S.cat === '__sources' ? '客户端文件' : S.cat ? label(S.cat) : (S.mode === 'browse' ? '全部资源' : '全部变化'), S.group].filter(Boolean).join(' / ');
  $('#list-status').textContent = `${where} · ${num(S.total)} 项${S.q ? ` · 搜索“${S.q}”` : ''}`;
  if (reset) {
    const index = selectPath ? S.rows.findIndex(r => pathOf(r) === selectPath) : -1;
    if (index >= 0) select(index); else { overview(); writeHash(); }
  }
}
function rowHtml(row, index) {
  if (row.file) {
    const f = row.file;
    return `<div class="row" role="option" data-i="${index}" aria-selected="false"><div class="icon">${ICON.__sources}</div><div class="text"><div class="name">${esc(baseName(f.rel))}</div><div class="path">${esc(dirName(f.rel))}</div></div><div class="side">${f.before == null ? '' : size(f.before)}${f.before != null && f.after != null ? ' → ' : ''}${f.after == null ? '' : size(f.after)}</div></div>`;
  }
  const e = row.entry || row.change.new || row.change.old;
  const k = row.change?.kind;
  const thumb = kindOf(e) === 'image' ? `<img loading="lazy" src="${thumbUrl(e)}" alt="">` : (ICON[e.cat] || '•');
  const side = row.change
    ? `<span class="badge ${k}">${KIND[k]}</span><div>${k === 'modified' ? signed(row.change.new.size - row.change.old.size) : size(e.size)}</div>`
    : `${size(e.size)}${e.meta?.w ? `<div>${e.meta.w}×${e.meta.h}</div>` : e.meta?.rows != null ? `<div>${num(e.meta.rows)} 行</div>` : ''}`;
  const path = k === 'renamed' ? `${row.change.old.path} → ${dirName(e.path)}` : dirName(e.path);
  return `<div class="row" role="option" data-i="${index}" aria-selected="false"><div class="icon">${thumb}</div><div class="text"><div class="name">${esc(baseName(e.path))}</div><div class="path" title="${esc(e.path)}">${esc(path)}</div></div><div class="side">${side}</div></div>`;
}
function select(index) {
  if (index < 0 || index >= S.rows.length) return;
  document.querySelectorAll('.row[aria-selected=true]').forEach(r => r.setAttribute('aria-selected', 'false'));
  S.selected = index;
  const el = document.querySelector(`.row[data-i="${index}"]`);
  if (el) { el.setAttribute('aria-selected', 'true'); el.scrollIntoView({block: 'nearest'}); }
  const row = S.rows[index];
  if (row.entry) detailEntry(row.entry);
  else if (row.change) detailChange(row.change);
  else detailFile(row.file);
  writeHash();
}

/* -- overviews ------------------------------------------------------------------ */
function overview() {
  S.selected = -1;
  if (S.mode === 'browse') overviewVersion(); else overviewCompare();
}
function overviewVersion() {
  const {meta, tree, changes} = S.view, st = meta.stats || {};
  const parent = meta.parent && S.byId[meta.parent];
  const t = meta.changes || {};
  $('#detail').innerHTML = `<h2>版本 ${esc(meta.label)}</h2><div class="sub">${esc(meta.id)} · 客户端 ${esc(meta.game?.root || '')}</div>
    <dl class="facts-grid"><dt>游戏资源版本</dt><dd>${esc(meta.game?.changeNumber ?? '未知')}</dd>
    <dt>资源</dt><dd>${num(meta.entries)} 项 · ${size(meta.bytes)}</dd><dt>客户端文件</dt><dd>${num(meta.sources)} 个</dd>
    <dt>解析耗时</dt><dd>${meta.durationSeconds} 秒（新解析 ${num(st.processed)} · 复用 ${num(st.reused)} · 缓存 ${num(st.cached)}）</dd>
    <dt>新写入</dt><dd>${num(st.newBlobs)} 个文件 · ${size(st.writtenBytes)}</dd>${meta.errors ? `<dt>未能解析</dt><dd class="err">${num(meta.errors)} 个对象</dd>` : ''}</dl>
    ${parent ? `<div class="banner note">相比上一版本 <b>${esc(parent.label)}</b>：<span class="totals">${['added', 'modified', 'removed', 'renamed'].map(k => `<span class="badge ${k}">${KIND[k]} ${num(t[k] || 0)}</span>`).join('')}</span><button type="button" class="primary" data-compare-parent>查看差分</button></div>` : '<div class="banner note">这是首个版本，之后每次解析出不同内容都会生成新版本，可与任意版本比较。</div>'}
    <div class="cards">${tree.map(c => `<button type="button" class="card" data-cat="${esc(c.key)}"><b>${ICON[c.key] || ''} ${esc(c.label)}</b><div class="big">${num(c.count)}</div><small>${size(c.size)} · ${c.groups.length} 个分组</small></button>`).join('')}</div>
    <div class="actions"><button type="button" data-export>导出为分类目录</button><span class="stat">在「${esc(S.info.library)}」下按分类建立文件夹（硬链接，不额外占用空间）。</span></div>
    ${changes?.errors?.length ? `<details><summary>未能解析的对象（${num(changes.errors.length)}）</summary><div class="hex">${esc(changes.errors.join('\n'))}</div></details>` : ''}`;
}
function overviewCompare() {
  const c = S.compare;
  const onlyOne = [...new Set([...(c.a.categories || []), ...(c.b.categories || [])])].filter(k => !c.scope.includes(k));
  $('#detail').innerHTML = `<h2>${esc(c.a.label)} → ${esc(c.b.label)}</h2><div class="sub">游戏资源版本 ${esc(c.a.game?.changeNumber ?? '—')} → ${esc(c.b.game?.changeNumber ?? '—')}</div>
    ${c.changes ? `<div class="totals">${['added', 'modified', 'removed', 'renamed'].map(k => `<span class="badge ${k}">${KIND[k]} ${num(c.total[k])}</span>`).join('')}<span class="badge">共 ${num(c.changes)} 处</span></div>` : '<div class="banner note">两个版本的资源完全一致。</div>'}
    <div class="cards">${c.categories.map(x => `<button type="button" class="card" data-cat="${esc(x.key)}"><b>${ICON[x.key] || ''} ${esc(x.label)}</b><div class="big">${num(changeTotal(x.counts))}</div><small>${['added', 'modified', 'removed', 'renamed'].filter(k => x.counts[k]).map(k => `${KIND[k]} ${num(x.counts[k])}`).join(' · ')}<br>体积 ${signed(x.bytes)}</small>${bar(x.counts, 'bar')}</button>`).join('')}
    ${changeTotal(c.sources) ? `<button type="button" class="card" data-cat="__sources"><b>${ICON.__sources} 客户端文件</b><div class="big">${num(changeTotal(c.sources))}</div><small>${['modified', 'added', 'removed'].filter(k => c.sources[k]).map(k => `${KIND[k]} ${num(c.sources[k])}`).join(' · ')}</small>${bar(c.sources, 'bar')}</button>` : ''}</div>
    ${onlyOne.length ? `<div class="banner note">只有一个版本解析了：${onlyOne.map(label).join('、')}，这些分类不参与比较。</div>` : ''}
    ${c.a.extractor !== c.b.extractor ? `<div class="banner note">两个版本由不同版本的解析器生成（${esc(c.a.extractor)} → ${esc(c.b.extractor)}），部分差异可能来自解析工具升级而非游戏更新。</div>` : ''}
    <div class="stat">从左侧选择分类或在列表中点选具体资源，查看图片对比、配置表逐行逐字段差异和文本逐行差异。</div>`;
}

/* -- detail ---------------------------------------------------------------------- */
function facts(e) {
  const m = e.meta || {};
  const rows = [['分类', `${label(e.cat)} / ${groupLabel(e.cat, e.group)}`], ['大小', size(e.size)]];
  if (m.w) rows.push(['尺寸', `${m.w} × ${m.h}${m.format ? ' · ' + m.format : ''}${m.alias ? ' · 与同名贴图相同' : ''}`]);
  if (m.rows != null) rows.push(['表格', `${num(m.rows)} 行 · ${num(m.cols)} 列${m.key ? ' · 主键 ' + m.key : ''}`]);
  if (m.lines) rows.push(['行数', num(m.lines)]);
  if (m.vertices) rows.push(['顶点', num(m.vertices)]);
  if (m.objects) rows.push(['对象', num(m.objects)]);
  if (m.codec) rows.push(['音频', `${m.codec} · ${m.channels} 声道 · ${m.rate} Hz${m.duration ? ' · 约 ' + m.duration + ' 秒' : ''}`]);
  if (m.error) rows.push(['说明', `<span class="err">${esc(m.error)}</span>`]);
  rows.push(['来源', esc(String(e.src).replace('#tables', '（解码后的配置表）'))], ['指纹', `<code>${e.hash}</code>`]);
  return `<dl class="facts-grid">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>`;
}
const actions = e => e.meta?.noblob ? '' : `<div class="actions"><a href="${blobUrl(e, true)}"><button type="button">下载</button></a><button type="button" data-reveal="${e.hash}" data-ext="${esc(e.ext)}">在文件夹中显示</button></div>`;
function detailEntry(e) {
  $('#detail').innerHTML = `<h2>${esc(baseName(e.path))}</h2><div class="sub">${esc(e.path)}</div>${facts(e)}${actions(e)}<div id="preview"></div>`;
  preview(e, $('#preview'));
}
function detailChange(c) {
  const e = c.new || c.old;
  const head = `<h2>${esc(baseName(e.path))}</h2><div class="sub">${esc(e.path)}</div>`;
  if (c.kind === 'added' || c.kind === 'removed' || c.kind === 'renamed') {
    const banner = c.kind === 'renamed' ? `改名：${esc(c.old.path)} → ${esc(c.new.path)}（内容相同）` : `${KIND[c.kind]}的资源${c.kind === 'removed' ? '（显示的是基准版本中的内容）' : ''}`;
    $('#detail').innerHTML = `${head}<div class="banner ${c.kind}">${banner}</div>${facts(e)}${actions(e)}<div id="preview"></div>`;
    preview(e, $('#preview'));
    return;
  }
  const o = c.old, n = c.new;
  $('#detail').innerHTML = `${head}<div class="banner modified">修改：${size(o.size)} → ${size(n.size)}（${signed(n.size - o.size)}）</div>
    <dl class="facts-grid"><dt>分类</dt><dd>${esc(label(n.cat))} / ${esc(groupLabel(n.cat, n.group))}</dd><dt>修改前</dt><dd><code>${o.hash}</code></dd><dt>修改后</dt><dd><code>${n.hash}</code></dd><dt>来源</dt><dd>${esc(String(n.src).replace('#tables', '（解码后的配置表）'))}</dd></dl>
    <div class="actions"><a href="${blobUrl(o, true)}"><button type="button">下载修改前</button></a><a href="${blobUrl(n, true)}"><button type="button">下载修改后</button></a></div><div id="preview"></div>`;
  const box = $('#preview'), kind = kindOf(n);
  if (o.meta?.noblob || n.meta?.noblob) return preview(n, box);
  if (kind === 'image') return imageCompare(o, n, box);
  if (kind === 'table') return tableDiff(o, n, box);
  if (kind === 'text' || kind === 'model') return textDiff(o, n, box);
  return binaryCompare(o, n, box);
}
function detailFile(f) {
  $('#detail').innerHTML = `<h2>${esc(baseName(f.rel))}</h2><div class="sub">${esc(f.rel)}</div>
    <dl class="facts-grid"><dt>修改前</dt><dd>${f.before == null ? '（不存在）' : size(f.before)}</dd><dt>修改后</dt><dd>${f.after == null ? '（不存在）' : size(f.after)}</dd></dl>
    <div class="banner note">这是客户端里的原始文件。它解析出的资源变化在对应分类中列出（资源包的对象构成见「资源包清单」）。</div>`;
}

/* -- previews ----------------------------------------------------------------------- */
function preview(e, box) {
  const kind = kindOf(e);
  if (kind === 'missing') { box.innerHTML = `<div class="banner note">此对象未能解码（${esc(e.meta.error || '格式不受支持')}），只记录了指纹用于比较。</div>`; return; }
  if (kind === 'image') {
    box.innerHTML = `<div class="tabs"><button type="button" data-fit aria-pressed="false">原始大小</button></div><div class="picture checker"><img src="${blobUrl(e)}" alt="${esc(baseName(e.path))}"></div>`;
    return;
  }
  if (kind === 'table') return tableView(e, box);
  if (kind === 'text') return textView(e, box);
  if (kind === 'model') return modelView(e, box);
  if (kind === 'font') return fontView(e, box);
  if (kind === 'video') { box.innerHTML = `<video controls preload="metadata" src="${blobUrl(e)}"></video>`; return; }
  if (kind === 'sound') { box.innerHTML = `<audio controls preload="metadata" src="${blobUrl(e)}"></audio>`; return; }
  if (kind === 'audio') { box.innerHTML = '<div class="banner note">客户端的 Wwise 音频经过加密，浏览器无法直接播放；可下载原始文件，或在不同版本间比较其是否变化。</div>'; return; }
  return hexView(e, box);
}
const cell = v => v === null || v === undefined ? '<span class="stat">—</span>' : typeof v === 'object' ? esc(JSON.stringify(v)) : esc(v);
const cellTitle = v => v === null || v === undefined ? '' : esc(typeof v === 'object' ? JSON.stringify(v) : String(v));
async function tableView(e, box) {
  const st = {q: '', offset: 0};
  box.innerHTML = '<input type="search" placeholder="在表中搜索" aria-label="在表中搜索"><div class="pager"></div><div class="grid-wrap"><div class="spin">读取中…</div></div>';
  const load = async () => {
    const data = await api('table', {h: e.hash, q: st.q, offset: st.offset, limit: 100});
    const cols = data.columns.slice(0, 60);
    box.querySelector('.pager').innerHTML = `${num(data.total)} 行 · 第 ${num(st.offset + 1)}–${num(Math.min(data.total, st.offset + 100))} 行 <button type="button" data-p="-1"${st.offset ? '' : ' disabled'}>上一页</button><button type="button" data-p="1"${st.offset + 100 < data.total ? '' : ' disabled'}>下一页</button>${data.columns.length > 60 ? ` · 仅显示前 60 列（共 ${data.columns.length}）` : ''}`;
    box.querySelector('.grid-wrap').innerHTML = `<table class="grid"><thead><tr>${cols.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${data.rows.map(r => `<tr>${cols.map((c, i) => `<td class="${i === 0 && c === 'id' ? 'key' : ''}" title="${cellTitle(r[c])}">${cell(r[c])}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  };
  box.querySelector('input').addEventListener('input', debounce(ev => { st.q = ev.target.value.trim(); st.offset = 0; load(); }, 300));
  box.querySelector('.pager').addEventListener('click', ev => { const p = ev.target.dataset.p; if (p) { st.offset = Math.max(0, st.offset + Number(p) * 100); load(); } });
  load().catch(error => { box.querySelector('.grid-wrap').innerHTML = `<div class="spin err">${esc(error.message)}</div>`; });
}
async function textView(e, box) {
  box.innerHTML = '<div class="spin">读取中…</div>';
  try {
    const data = await api('text', {h: e.hash, ext: e.ext});
    const lines = data.text.split('\n');
    const shown = lines.slice(0, 6000);
    box.innerHTML = `<div class="code"><table>${shown.map((l, i) => `<tr><td class="ln">${i + 1}</td><td>${esc(l)}</td></tr>`).join('')}</table></div>${lines.length > shown.length || data.truncated ? `<div class="stat">仅显示前 ${num(shown.length)} 行（共 ${num(lines.length)} 行${data.truncated ? '，文件已截断' : ''}），完整内容请下载。</div>` : ''}`;
  } catch (error) { box.innerHTML = `<div class="spin err">${esc(error.message)}</div>`; }
}
async function hexView(e, box) {
  box.innerHTML = '<div class="spin">读取中…</div>';
  try {
    const res = await fetch(blobUrl(e), {headers: {Range: 'bytes=0-767'}});
    const bytes = new Uint8Array(await res.arrayBuffer());
    box.innerHTML = `<div class="banner note">二进制内容（${esc(e.ext || '无扩展名')}），显示前 ${bytes.length} 字节。</div><div class="hex">${esc(hex(bytes))}</div>`;
  } catch (error) { box.innerHTML = `<div class="spin err">${esc(error.message)}</div>`; }
}
function hex(bytes) {
  const out = [];
  for (let i = 0; i < bytes.length; i += 16) {
    const row = [...bytes.slice(i, i + 16)];
    out.push(i.toString(16).padStart(6, '0') + '  ' + row.map(b => b.toString(16).padStart(2, '0')).join(' ').padEnd(48) + '  ' + row.map(b => b >= 32 && b < 127 ? String.fromCharCode(b) : '.').join(''));
  }
  return out.join('\n');
}
async function fontView(e, box) {
  const family = 'f' + e.hash;
  try {
    const face = new FontFace(family, `url(${blobUrl(e)})`);
    await face.load(); document.fonts.add(face);
    box.innerHTML = `<div class="font-sample" style="font-family:'${family}'">铃兰之剑 Sword of Convallaria<small>ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyz 0123456789 ，。！？</small></div>`;
  } catch (error) { box.innerHTML = `<div class="banner note">浏览器无法加载这个字体（${esc(error.message)}），可下载后查看。</div>`; }
}
async function modelView(e, box) {
  box.innerHTML = '<canvas class="model" width="900" height="420" aria-label="模型线框预览"></canvas><div class="stat">拖动旋转，滚轮缩放。</div>';
  const text = (await api('text', {h: e.hash, ext: e.ext})).text;
  const v = [], edges = [];
  for (const line of text.split('\n')) {
    if (line.startsWith('v ')) { const [, x, y, z] = line.trim().split(/\s+/).map(Number); v.push([x, y, z]); }
    else if (line.startsWith('f ') && edges.length < 120000) {
      const ids = line.trim().split(/\s+/).slice(1).map(t => parseInt(t, 10) - 1);
      for (let i = 0; i < ids.length; i++) edges.push([ids[i], ids[(i + 1) % ids.length]]);
    }
  }
  const canvas = box.querySelector('canvas'), ctx = canvas.getContext('2d');
  if (!v.length) { box.innerHTML = '<div class="banner note">模型没有顶点数据。</div>'; return; }
  const min = [0, 1, 2].map(i => Math.min(...v.map(p => p[i]))), max = [0, 1, 2].map(i => Math.max(...v.map(p => p[i])));
  const center = min.map((m, i) => (m + max[i]) / 2), radius = Math.max(...max.map((m, i) => m - min[i])) / 2 || 1;
  let yaw = .6, pitch = .35, zoom = 1, drag = null;
  const draw = () => {
    const w = canvas.width = canvas.clientWidth * devicePixelRatio, h = canvas.height = canvas.clientHeight * devicePixelRatio;
    ctx.clearRect(0, 0, w, h); ctx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue('--accent2'); ctx.lineWidth = devicePixelRatio * .6;
    const s = Math.min(w, h) * .42 / radius * zoom, cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
    const pts = v.map(([x, y, z]) => { x -= center[0]; y -= center[1]; z -= center[2]; const x1 = x * cy - z * sy, z1 = x * sy + z * cy; const y1 = y * cp - z1 * sp; return [w / 2 + x1 * s, h / 2 - y1 * s]; });
    ctx.beginPath();
    for (const [a, b] of edges) { const p = pts[a], q = pts[b]; if (p && q) { ctx.moveTo(p[0], p[1]); ctx.lineTo(q[0], q[1]); } }
    if (!edges.length) for (const p of pts) ctx.rect(p[0], p[1], 1, 1);
    ctx.stroke();
  };
  canvas.addEventListener('pointerdown', ev => { drag = [ev.clientX, ev.clientY]; canvas.setPointerCapture(ev.pointerId); });
  canvas.addEventListener('pointermove', ev => { if (!drag) return; yaw += (ev.clientX - drag[0]) / 120; pitch += (ev.clientY - drag[1]) / 120; drag = [ev.clientX, ev.clientY]; draw(); });
  canvas.addEventListener('pointerup', () => { drag = null; });
  canvas.addEventListener('wheel', ev => { ev.preventDefault(); zoom *= ev.deltaY < 0 ? 1.12 : 1 / 1.12; draw(); }, {passive: false});
  draw();
}

/* -- comparisons -------------------------------------------------------------------- */
function imageCompare(o, n, box) {
  const modes = [['side', '并排'], ['slide', '滑动'], ['blink', '闪烁'], ['diff', '差异高亮']];
  box.innerHTML = `<div class="tabs">${modes.map(([k, t]) => `<button type="button" data-mode-img="${k}">${t}</button>`).join('')}</div><div class="stage"></div>
    <div class="stat">修改前 ${o.meta?.w || '?'}×${o.meta?.h || '?'} · ${size(o.size)} → 修改后 ${n.meta?.w || '?'}×${n.meta?.h || '?'} · ${size(n.size)}</div>`;
  const stage = box.querySelector('.stage');
  let timer = null;
  const show = mode => {
    clearInterval(timer);
    box.querySelectorAll('[data-mode-img]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.modeImg === mode)));
    if (mode === 'side') {
      stage.innerHTML = `<div class="pair"><figure><figcaption>修改前</figcaption><div class="picture checker"><img src="${blobUrl(o)}" alt="修改前"></div></figure><figure><figcaption>修改后</figcaption><div class="picture checker"><img src="${blobUrl(n)}" alt="修改后"></div></figure></div>`;
    } else if (mode === 'slide') {
      stage.innerHTML = `<div class="picture checker"><div class="slider"><img class="base" src="${blobUrl(n)}" alt="修改后"><div class="over" style="width:50%"><img src="${blobUrl(o)}" alt="修改前"></div></div></div><input class="range" type="range" min="0" max="100" value="50" aria-label="对比位置"><div class="stat">◀ 修改前 ｜ 修改后 ▶ 拖动滑杆比较</div>`;
      const base = stage.querySelector('.base'), over = stage.querySelector('.over'), top = over.querySelector('img');
      const fit = () => { top.style.width = base.clientWidth + 'px'; top.style.height = base.clientHeight + 'px'; };
      base.addEventListener('load', fit); new ResizeObserver(fit).observe(base);
      stage.querySelector('.range').addEventListener('input', ev => { over.style.width = ev.target.value + '%'; });
    } else if (mode === 'blink') {
      stage.innerHTML = `<div class="picture checker"><img src="${blobUrl(o)}" alt="对比"></div><div class="stat" aria-live="off">修改前</div>`;
      const img = stage.querySelector('img'), note = stage.querySelector('.stat');
      let flip = false;
      timer = setInterval(() => { flip = !flip; img.src = blobUrl(flip ? n : o); note.textContent = flip ? '修改后' : '修改前'; }, 700);
    } else {
      stage.innerHTML = '<div class="picture checker"><canvas aria-label="差异高亮"></canvas></div><div class="stat">计算中…</div>';
      pixelDiff(o, n, stage.querySelector('canvas'), stage.querySelector('.stat'));
    }
  };
  box.querySelector('.tabs').addEventListener('click', ev => { const m = ev.target.dataset.modeImg; if (m) show(m); });
  show('side');
}
const loadImage = src => new Promise((resolve, reject) => { const img = new Image(); img.onload = () => resolve(img); img.onerror = () => reject(new Error('图片加载失败')); img.src = src; });
async function pixelDiff(o, n, canvas, note) {
  try {
    const [a, b] = await Promise.all([loadImage(blobUrl(o)), loadImage(blobUrl(n))]);
    const w = Math.max(a.naturalWidth, b.naturalWidth), h = Math.max(a.naturalHeight, b.naturalHeight);
    const read = img => { const c = document.createElement('canvas'); c.width = w; c.height = h; const x = c.getContext('2d'); x.drawImage(img, 0, 0); return x.getImageData(0, 0, w, h).data; };
    const pa = read(a), pb = read(b);
    canvas.width = w; canvas.height = h;
    const ctx = canvas.getContext('2d'), out = ctx.createImageData(w, h), d = out.data;
    let changed = 0, x0 = w, y0 = h, x1 = -1, y1 = -1;
    for (let i = 0, p = 0; i < pa.length; i += 4, p++) {
      const delta = Math.abs(pa[i] - pb[i]) + Math.abs(pa[i + 1] - pb[i + 1]) + Math.abs(pa[i + 2] - pb[i + 2]) + Math.abs(pa[i + 3] - pb[i + 3]);
      if (delta > 24) {
        d[i] = 255; d[i + 1] = 48; d[i + 2] = 72; d[i + 3] = 255; changed++;
        const x = p % w, y = (p / w) | 0; if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
      } else {
        const g = (pb[i] * .3 + pb[i + 1] * .59 + pb[i + 2] * .11) * .45; d[i] = d[i + 1] = d[i + 2] = g; d[i + 3] = Math.max(60, pb[i + 3] * .7);
      }
    }
    ctx.putImageData(out, 0, 0);
    const dims = a.naturalWidth !== b.naturalWidth || a.naturalHeight !== b.naturalHeight ? `尺寸由 ${a.naturalWidth}×${a.naturalHeight} 变为 ${b.naturalWidth}×${b.naturalHeight}（按左上角对齐）· ` : '';
    note.textContent = changed ? `${dims}变化像素 ${num(changed)}（${(changed / (w * h) * 100).toFixed(2)}%）· 范围 (${x0}, ${y0}) – (${x1}, ${y1})，红色为变化处` : `${dims}像素完全一致（仅编码不同）`;
  } catch (error) { note.innerHTML = `<span class="err">${esc(error.message)}</span>`; }
}
async function tableDiff(o, n, box) {
  box.innerHTML = '<div class="spin">逐行比较中…</div>';
  let data;
  try { data = await api('tablediff', {a: o.hash, b: n.hash}); } catch (error) { box.innerHTML = `<div class="spin err">${esc(error.message)}</div>`; return; }
  const c = data.counts;
  const tabs = [['changed', '修改行', c.changed], ['added', '新增行', c.added], ['removed', '删除行', c.removed]];
  box.innerHTML = `<div class="totals"><span class="badge modified">修改 ${num(c.changed)} 行</span><span class="badge added">新增 ${num(c.added)} 行</span><span class="badge removed">删除 ${num(c.removed)} 行</span><span class="badge">${num(c.rowsBefore)} → ${num(c.rowsAfter)} 行</span>${data.key ? `<span class="badge">主键 ${esc(data.key)}</span>` : '<span class="badge">无唯一主键，按行号比较</span>'}</div>
    ${data.addedColumns.length || data.removedColumns.length ? `<div class="banner note">${data.addedColumns.length ? `新增列：${data.addedColumns.map(esc).join('、')}　` : ''}${data.removedColumns.length ? `删除列：${data.removedColumns.map(esc).join('、')}` : ''}</div>` : ''}
    <div class="tabs">${tabs.map(([k, t, v]) => `<button type="button" data-tab="${k}"${v ? '' : ' disabled'}>${t} ${num(v)}</button>`).join('')}</div><div class="pager"></div><div class="grid-wrap"></div>`;
  const st = {tab: tabs.find(t => t[2])?.[0] || 'changed', offset: 0};
  const per = 100;
  const draw = () => {
    box.querySelectorAll('[data-tab]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.tab === st.tab)));
    const list = data[st.tab], page = list.slice(st.offset, st.offset + per), total = c[st.tab];
    box.querySelector('.pager').innerHTML = `${num(total)} 项${total > list.length ? `（列出前 ${num(list.length)}）` : ''} · 第 ${num(Math.min(list.length, st.offset + 1))}–${num(Math.min(list.length, st.offset + per))} 项 <button type="button" data-p="-1"${st.offset ? '' : ' disabled'}>上一页</button><button type="button" data-p="1"${st.offset + per < list.length ? '' : ' disabled'}>下一页</button>`;
    const wrap = box.querySelector('.grid-wrap');
    if (st.tab === 'changed') {
      wrap.innerHTML = `<table class="grid"><thead><tr><th>${esc(data.key || '行号')}</th><th>字段</th><th>修改前</th><th>修改后</th></tr></thead><tbody>${page.map(row => row.fields.map((f, i) => `<tr>${i ? '' : `<td class="key" rowspan="${row.fields.length}" title="${cellTitle(row.key)}">${cell(row.key)}</td>`}<td>${esc(f[0])}</td><td class="old" title="${cellTitle(f[1])}">${cell(f[1])}</td><td class="new" title="${cellTitle(f[2])}">${cell(f[2])}</td></tr>`).join('')).join('')}</tbody></table>`;
    } else {
      const cols = (data.columns.length ? data.columns : Object.keys(page[0] || {})).slice(0, 40);
      wrap.innerHTML = `<table class="grid"><thead><tr>${cols.map(k => `<th>${esc(k)}</th>`).join('')}</tr></thead><tbody>${page.map(r => `<tr class="${st.tab}">${cols.map((k, i) => `<td class="${i === 0 && k === data.key ? 'key' : ''}" title="${cellTitle(r?.[k])}">${cell(r?.[k])}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
    }
  };
  box.querySelector('.tabs').addEventListener('click', ev => { const t = ev.target.dataset.tab; if (t) { st.tab = t; st.offset = 0; draw(); } });
  box.querySelector('.pager').addEventListener('click', ev => { const p = ev.target.dataset.p; if (p) { st.offset = Math.max(0, st.offset + Number(p) * per); draw(); } });
  draw();
}
function inline(l, r) {
  let a = 0; while (a < l.length && a < r.length && l[a] === r[a]) a++;
  let b = 0; while (b < l.length - a && b < r.length - a && l[l.length - 1 - b] === r[r.length - 1 - b]) b++;
  const part = (s, cls) => esc(s.slice(0, a)) + (s.length - b > a ? `<mark class="${cls}">${esc(s.slice(a, s.length - b))}</mark>` : '') + esc(s.slice(s.length - b));
  return [part(l, 'l'), part(r, 'r')];
}
async function textDiff(o, n, box) {
  box.innerHTML = '<div class="spin">逐行比较中…</div>';
  let data;
  try { data = await api('textdiff', {a: o.hash, b: n.hash, ext: n.ext}); } catch (error) { box.innerHTML = `<div class="spin err">${esc(error.message)}</div>`; return; }
  if (!data.hunks.length) { box.innerHTML = '<div class="banner note">文本内容一致（仅空白或编码不同）。</div>'; return; }
  let rows = 0;
  const body = data.hunks.map(h => {
    const head = `<tr class="gap"><td colspan="4">⋯ 修改前第 ${h.a[0]}–${h.a[1]} 行 ｜ 修改后第 ${h.b[0]}–${h.b[1]} 行</td></tr>`;
    return head + h.rows.map(r => {
      rows++;
      let l = r.l == null ? '' : esc(r.l), rr = r.r == null ? '' : esc(r.r);
      if (r.t === 'r' && r.l != null && r.r != null) [l, rr] = inline(r.l, r.r);
      return `<tr class="${r.t}"><td class="ln">${r.a ?? ''}</td><td class="l">${l}</td><td class="ln">${r.b ?? ''}</td><td class="r">${rr}</td></tr>`;
    }).join('');
  }).join('');
  box.innerHTML = `<div class="totals"><span class="badge added">+${num(data.added)} 行</span><span class="badge removed">−${num(data.removed)} 行</span><span class="badge">${num(data.linesBefore)} → ${num(data.linesAfter)} 行</span>${data.truncated ? '<span class="badge">内容过长，已截断比较</span>' : ''}</div><div class="code diff"><table><colgroup><col class="ln"><col><col class="ln"><col></colgroup>${body}</table></div><div class="stat">共 ${data.hunks.length} 处差异块，${num(rows)} 行。</div>`;
}
async function binaryCompare(o, n, box) {
  box.innerHTML = '<div class="banner note">二进制内容不同，下面是两个版本开头的字节。</div><div class="pair"><figure><figcaption>修改前</figcaption><div class="hex" data-a>…</div></figure><figure><figcaption>修改后</figcaption><div class="hex" data-b>…</div></figure></div>';
  const head = async e => new Uint8Array(await (await fetch(blobUrl(e), {headers: {Range: 'bytes=0-255'}})).arrayBuffer());
  try {
    const [a, b] = await Promise.all([head(o), head(n)]);
    box.querySelector('[data-a]').textContent = hex(a).split('\n').map(l => l.slice(0, 56)).join('\n');
    box.querySelector('[data-b]').textContent = hex(b).split('\n').map(l => l.slice(0, 56)).join('\n');
  } catch (error) { box.querySelector('[data-a]').textContent = error.message; }
}

/* -- events ---------------------------------------------------------------------------- */
function debounce(fn, ms) { let t; return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); }; }
function setFilter(cat, group) {
  const wasSources = S.cat === '__sources';
  S.cat = cat || null; S.group = group || null;
  // Client files only know added / modified / removed; resource filters are kept across categories.
  if (S.cat === '__sources') S.kind = 'modified'; else if (wasSources) S.kind = null;
  renderTree(); renderKinds(); loadList(true);
}
function defaultPair() {
  const ids = S.versions.map(v => v.id);
  const b = S.mode === 'browse' && S.v ? S.v : ids[ids.length - 1];
  const a = S.byId[b]?.parent || ids[ids.indexOf(b) - 1] || ids[ids.length - 2];
  return [a, b];
}
function bind() {
  document.querySelector('.modes').addEventListener('click', ev => {
    const mode = ev.target.dataset.mode;
    if (!mode || mode === S.mode) return;
    if (mode === 'browse') openBrowse(S.b || S.versions[S.versions.length - 1].id);
    else {
      if (S.versions.length < 2) { toast('需要至少两个版本才能比较；再次解析出不同内容后就会生成新版本。'); return; }
      openCompare(...defaultPair());
    }
  });
  $('#versions').addEventListener('click', ev => {
    const card = ev.target.closest('.version');
    if (!card) return;
    const id = card.dataset.v;
    if (ev.target.dataset.pick) {
      const [a, b] = S.mode === 'compare' ? [S.a, S.b] : defaultPair();
      const pair = ev.target.dataset.pick === 'a' ? [id, b === id ? a : b] : [a === id ? b : a, id];
      openCompare(...pair);
    } else if (ev.target.dataset.prev !== undefined) openCompare(S.byId[id].parent, id);
    else openBrowse(id);
  });
  $('#go-compare').addEventListener('click', () => openCompare($('#pick-a').value, $('#pick-b').value));
  $('#pick-a').addEventListener('change', () => openCompare($('#pick-a').value, $('#pick-b').value));
  $('#pick-b').addEventListener('change', () => openCompare($('#pick-a').value, $('#pick-b').value));
  $('#swap').addEventListener('click', () => openCompare($('#pick-b').value, $('#pick-a').value));
  $('#tree').addEventListener('click', ev => {
    const btn = ev.target.closest('[data-cat]');
    if (!btn) return;
    const cat = btn.dataset.cat, group = btn.dataset.group;
    if (!group && cat && cat === S.cat && !S.group) setFilter(null, null); else setFilter(cat, group);
  });
  $('#kinds').addEventListener('click', ev => {
    const btn = ev.target.closest('[data-kind]');
    if (!btn || btn.disabled) return;
    S.kind = btn.dataset.kind || null; renderKinds(); loadList(true);
  });
  $('#search').addEventListener('input', debounce(ev => { S.q = ev.target.value.trim(); loadList(true); }, 260));
  $('#rows').addEventListener('click', ev => { const row = ev.target.closest('.row'); if (row) select(Number(row.dataset.i)); });
  $('#more').addEventListener('click', () => loadList(false));
  $('#detail').addEventListener('click', async ev => {
    const t = ev.target.closest('button');
    if (!t) return;
    if (t.dataset.cat !== undefined && t.classList.contains('card')) return setFilter(t.dataset.cat);
    if (t.dataset.compareParent !== undefined) return openCompare(S.view.meta.parent, S.view.meta.id);
    if (t.dataset.fit !== undefined) {
      const pic = t.closest('#preview').querySelector('.picture');
      pic.classList.toggle('actual'); t.setAttribute('aria-pressed', String(pic.classList.contains('actual')));
    }
    if (t.dataset.reveal) { try { await api('reveal', {h: t.dataset.reveal, ext: t.dataset.ext}); } catch (error) { toast(error.message); } }
    if (t.dataset.export !== undefined) {
      t.disabled = true; t.textContent = '整理中…';
      try { const r = await api('export', {v: S.view.meta.id, open: 1}); toast(`已整理到 ${r.folder}`); } catch (error) { toast(error.message); }
      t.disabled = false; t.textContent = '导出为分类目录';
    }
  });
  document.addEventListener('keydown', ev => {
    const typing = ['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName);
    if (ev.key === '/' && !typing) { ev.preventDefault(); $('#search').focus(); return; }
    if (typing) return;
    if (ev.key === 'ArrowDown' || ev.key === 'j') { ev.preventDefault(); select(Math.min(S.rows.length - 1, S.selected + 1)); }
    if (ev.key === 'ArrowUp' || ev.key === 'k') { ev.preventDefault(); select(Math.max(0, S.selected - 1)); }
    if (ev.key === 'Escape') { document.querySelectorAll('.row[aria-selected=true]').forEach(r => r.setAttribute('aria-selected', 'false')); overview(); writeHash(); }
  });
  $('#theme').addEventListener('click', () => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next; localStorage.setItem('soc-archive-theme', next);
  });
}
async function init() {
  document.documentElement.dataset.theme = localStorage.getItem('soc-archive-theme') || 'dark';
  bind();
  try {
    S.info = await api('info');
    S.labels = Object.fromEntries(S.info.categories.map(c => [c.key, c.label]));
    $('#root-path').textContent = S.info.root;
    await loadVersions();
  } catch (error) { $('#detail').innerHTML = `<div class="empty err">无法连接资源服务：${esc(error.message)}</div>`; return; }
  if (!S.versions.length) {
    renderModes();
    $('#detail').innerHTML = '<div class="empty">归档里还没有版本。<br>在「SoCwiki 本地更新」里点击「开始解析」，或运行<br><code>python -X utf8 scripts/update_client.py archive scan</code></div>';
    return;
  }
  await route();
  // Links pasted into the address bar (or back / forward) open the same view.
  window.addEventListener('hashchange', route);
}
async function route() {
  const h = new URLSearchParams(location.hash.slice(1));
  try {
    if (h.get('a') && h.get('b') && S.byId[h.get('a')] && S.byId[h.get('b')]) await openCompare(h.get('a'), h.get('b'), h);
    else await openBrowse(S.byId[h.get('v')] ? h.get('v') : S.versions[S.versions.length - 1].id, h);
  } catch (error) { $('#detail').innerHTML = `<div class="empty err">${esc(error.message)}</div>`; }
}
init();
