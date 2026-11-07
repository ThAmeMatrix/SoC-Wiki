/* Client world data: battle maps and auto-battle AI.
 * Routes: #/maps, #/ai. Pure DOM, no network. */
(function () {
  'use strict';
  const W = () => window.WIKI_WORLD_DATA;
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt = n => Number(n || 0).toLocaleString('zh-CN');

  function intro(eyebrow, title, desc) {
    return `<div class="page-intro"><div><div class="eyebrow">${esc(eyebrow)}</div><h1>${esc(title)}</h1><p>${esc(desc)}</p></div></div>`;
  }

  /* ---------------- Shared pagination ---------------- */
  /* ---------------- Shared pagination ---------------- */
  const PAGE_SIZES = [8, 12, 16, 24, 48];
  function pagerHtml(id, page, pages, total, perPage, sizes = PAGE_SIZES) {
    const sizeOptions = sizes.map(n => `<option value="${n}" ${n === perPage ? 'selected' : ''}>${n} 条/页</option>`).join('');
    const nums = [];
    const from = Math.max(1, Math.min(page - 2, pages - 4));
    const to = Math.min(pages, Math.max(4, page + 2));
    for (let i = from; i <= to; i++) nums.push(i);
    return `<nav class="world-pager" id="${id}" data-pager="${id}" aria-label="翻页">
      <button type="button" data-page="first" ${page <= 1 ? 'disabled' : ''} title="首页">«</button>
      <button type="button" data-page="prev" ${page <= 1 ? 'disabled' : ''}>上一页</button>
      ${nums.map(i => `<button type="button" data-page="${i}" class="${i === page ? 'active' : ''}"
        aria-current="${i === page ? 'page' : 'false'}">${i}</button>`).join('')}
      <button type="button" data-page="next" ${page >= pages ? 'disabled' : ''}>下一页</button>
      <button type="button" data-page="last" ${page >= pages ? 'disabled' : ''} title="末页">»</button>
      <label class="world-pager-jump">跳至<input type="number" min="1" max="${pages}" value="${page}" data-page-input="${id}" aria-label="页码">/ ${pages} 页</label>
      <select data-page-size="${id}" aria-label="每页显示条数">${sizeOptions}</select>
      <span class="small-text muted">共 ${fmt(total)} 条</span>
    </nav>`;
  }
  /** Delegated on the page root, so replacing the pager markup on repaint
   * never drops the listener. Page changes deliberately do NOT scroll: the
   * caller keeps its own scroll position. */
  function bindPager(root, id, onPage, onSize) {
    root.addEventListener('click', e => {
      const nav = e.target.closest(`[data-pager="${id}"]`);
      if (!nav) return;
      const btn = e.target.closest('[data-page]');
      if (!btn || btn.disabled) return;
      onPage(btn.dataset.page);
    });
    root.addEventListener('change', e => {
      const sel = e.target.closest(`[data-page-size="${id}"]`);
      if (sel) { onSize(Number(sel.value)); return; }
      const input = e.target.closest(`[data-page-input="${id}"]`);
      if (input) onPage(String(Math.max(1, Number(input.value) || 1)));
    });
    root.addEventListener('keydown', e => {
      const input = e.target.closest(`[data-page-input="${id}"]`);
      if (input && e.key === 'Enter') {
        e.preventDefault();
        onPage(String(Math.max(1, Number(input.value) || 1)));
      }
    });
  }
  /** Re-render a pager without detaching the <nav> itself: replacing the
   * element while its own number input fires `change` throws in Chrome. */
  function updatePager(id, page, pages, total, perPage, root = document) {
    const nav = root.querySelector('#' + id);
    if (!nav) return;
    const markup = pagerHtml(id, page, pages, total, perPage);
    const temp = document.createElement('div');
    temp.innerHTML = markup;
    const fresh = temp.firstElementChild;
    if (!fresh) return;
    // Preserve the focused control so a jump input keeps working after repaint.
    const active = document.activeElement;
    const focusSel = active && nav.contains(active) && active.dataset.pageInput
      ? `[data-page-input="${id}"]` : null;
    nav.innerHTML = fresh.innerHTML;
    nav.className = fresh.className;
    // Keep the delegation attributes: bindPager matches on [data-pager=...].
    for (const attr of [...fresh.attributes]) {
      if (attr.name !== 'id' && attr.name !== 'class') nav.setAttribute(attr.name, attr.value);
    }
    if (focusSel) {
      const input = nav.querySelector(focusSel);
      if (input) { input.focus(); input.select(); }
    }
  }
  function pageAction(value, page, pages) {
    if (value === 'first') return 1;
    if (value === 'last') return pages;
    if (value === 'prev') return Math.max(1, page - 1);
    if (value === 'next') return Math.min(pages, page + 1);
    return Math.min(pages, Math.max(1, Number(value) || 1));
  }

  /* ---------------- Maps ---------------- */
  /* ---------------- Maps ---------------- */
  // Categorical palette with strong contrast; terrain ids are client numbers
  // (we deliberately do not invent names for them).
  const TERRAIN_COLOURS = ['#3f7d5a','#c8a24a','#4a7fa8','#a65a4c','#7a6bb0',
                           '#4f9c93','#b07a3d','#86604a','#5c8a3f','#a34f7c',
                           '#4e6fa1','#8f8f4a'];
  const terrainColour = id => TERRAIN_COLOURS[Math.abs(Number(id) || 0) % TERRAIN_COLOURS.length];

  const isPitTerrain = id => !!TERRAIN_BY_ID(id)?.pit;
  const terrainImage = id => TERRAIN_BY_ID(id)?.image || '';
  const terrainFace = (id, face) => TERRAIN_BY_ID(id)?.[face === 'top' ? 'topImage' : 'wallImage'] || '';
  const terrainStyle = id => {
    const img = terrainFace(id, 'top') || terrainImage(id);
    return img ? `background-image:url('${img}');background-size:100% 100%;background-position:center;`
               : `background:${terrainColour(id)};`;
  };
  const wallStyle = (id, tone) => {
    const img = terrainFace(id, 'wall');
    if (!img) { const c = shadeRgb(terrainColour(id), tone); return `background:linear-gradient(180deg,${c.top},${c.bottom})`; }
    // Client dirt/stone side rectified into a flat texture; darken by aspect.
    return `background-image:linear-gradient(180deg,rgba(0,0,0,${(1 - tone).toFixed(2)}),rgba(0,0,0,${(1 - tone * .7).toFixed(2)})),url('${img}');`
         + 'background-size:100% 100%;background-position:center;';
  };
  const TERRAIN_BY_ID = id => (W()?.mapMeta?.fieldTypes || []).find(x => x.id === Number(id));
  const terrainName = id => TERRAIN_BY_ID(id)?.name || `地形 ${id}`;
  const terrainDesc = id => TERRAIN_BY_ID(id)?.desc || '';

  /** Isometric 3D projection of the same client grid. ``h`` is the client's
   * height marker, drawn as a raised block with a lighter top and two shaded
   * sides. Depth sorting (back to front) keeps overlaps correct. */
  /** CSS-3D map view, following SoCxiezhouTool/app/js/map.js:
   *   .map-scroll.view3d { perspective: 1600px; perspective-origin: 50% 30% }
   *   .map-canvas.view3d { transform: rotateX(var(--tilt)) rotateZ(var(--yaw)) }
   * The frame keeps a FIXED size; rotateX gives vertical (tilt) rotation and
   * rotateZ gives horizontal (yaw) rotation. The browser's preserve-3d depth
   * sorting handles occlusion, which the old SVG re-projection got wrong.
   * Dragging right decreases yaw; dragging up increases tilt (same feel as
   * the reference tool). */
  /** Stacked isometric blocks, following the in-game look: every cell is a
   * solid cube with a client terrain sprite on top and stone-textured side
   * walls. The cube has a FIXED base thickness plus one layer per height unit,
   * so low ground still reads as a block and high ground stacks visibly.
   * Camera is CSS-3D (rotateX tilt / rotateZ yaw) with browser depth sorting. */
  const _isoCache = new Map();
  const _isoKey = (map, cellSize, hidden) =>
    `${map.id}|${cellSize}|${[...hidden].sort().join(',')}`;
  function gridIso(map, cellSize, hiddenTerrains, yaw = 45, tilt = 54, scale = 1) {
    const key = _isoKey(map, cellSize, hiddenTerrains);
    const cached = _isoCache.get(key);
    // Reuse the built markup when only the camera or zoom changed: those are
    // pure CSS-variable updates and must not rebuild thousands of DOM nodes.
    if (cached) {
      return cached;
    }
    const cells = (map.cells || []).filter(c => !hiddenTerrains.has(c[3]));
    if (!(map.cells || []).length) return gridSvg(map, cellSize, hiddenTerrains);
    const w = Math.max(1, map.width), h = Math.max(1, map.height);
    const cell = Math.max(8, Math.round(cellSize));
    const lift = Math.max(5, Math.round(cell * 0.42));
    const rawZ = c => Math.min(6, Math.round(Number(c[2] || 0) / 3));
    const cellAt = new Map(cells.map(c => [`${c[0]},${c[1]}`, c]));
    const heights = new Map(cells.map(c => [`${c[0]},${c[1]}`, rawZ(c)]));
    // Water / Forbidden cells are pits. Their field2 is pit depth, not a
    // stackable height, so place the surface BELOW the lowest neighbouring
    // ground cell and give it no solid side walls.
    // Pit surfaces must sit BELOW every adjacent ground cell. The previous
    // default (2, then max(0, n-1)) left isolated water at ground level or
    // above it (e.g. stage_city-os-ni00501), so use the global ground floor.
    let groundFloor = Infinity;
    for (const c of cells) {
      if (isPitTerrain(c[3])) continue;
      groundFloor = Math.min(groundFloor, rawZ(c));
    }
    if (!Number.isFinite(groundFloor)) groundFloor = 0;
    const pitInfo = new Map();
    for (const c of cells) {
      if (!isPitTerrain(c[3])) continue;
      let lowest = groundFloor;
      for (const [dx, dy] of [[1,0],[-1,0],[0,1],[0,-1]]) {
        const neighbour = cellAt.get(`${c[0]+dx},${c[1]+dy}`);
        if (!neighbour || isPitTerrain(neighbour[3])) continue;
        lowest = Math.min(lowest, heights.get(`${c[0]+dx},${c[1]+dy}`) ?? groundFloor);
      }
      pitInfo.set(`${c[0]},${c[1]}`, lowest - 1);
    }
    const zOf = (x, y, terrain) => {
      const key = `${x},${y}`;
      if (pitInfo.has(key)) return pitInfo.get(key);
      return heights.get(key) || 0;
    };
    const grid = [];
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      grid.push(`<div class="world-iso-empty" style="grid-column:${x + 1};grid-row:${y + 1}"></div>`);
    }
    const blocks = cells.map(c => {
      const [x, y, height, terrain] = c;
      const z = zOf(x, y, terrain);
      const pit = pitInfo.has(`${x},${y}`);
      const fill = terrainColour(terrain);
      const img = terrainImage(terrain);
      // Walls are drawn on every exposed edge; the browser's preserve-3d
      // depth sorting hides the ones behind neighbouring blocks when rotated.
      // All four walls live in the DOM, but only the two camera-facing ones
      // are displayed (see [data-quad] CSS). Switching quadrants is a single
      // attribute change instead of rebuilding thousands of 3D nodes.
      const dirs = [
        {dx: 0, dy: 1, cls: 'w-front', tone: .52},
        {dx: 1, dy: 0, cls: 'w-right', tone: .36},
        {dx: 0, dy: -1, cls: 'w-back', tone: .66},
        {dx: -1, dy: 0, cls: 'w-left', tone: .44},
      ];
      const walls = dirs.map(d => {
        const nCell = cellAt.get(`${x + d.dx},${y + d.dy}`);
        const nz = nCell ? zOf(nCell[0], nCell[1], nCell[3]) : -1;
        // A pit shows the exposed INNER wall of its higher neighbours plus a
        // thin rim of its own, so water reads as a recessed basin, not a hole.
        const exposed = pit ? Math.max(0, Math.max(0, nz) - z) : z - Math.max(0, nz);
        const wallH = (pit ? lift * .6 : lift) + Math.max(0, exposed) * lift;
        if (wallH <= 0) return '';
        const tone = pit ? d.tone * .82 : d.tone;
        return `<i class="world-iso-wall ${d.cls}${pit ? ' is-water-wall' : ''}" style="--wall:${wallH}px;
          ${wallStyle(terrain, tone)}"></i>`;
      }).join('');
      return `<div class="world-iso-cell world-iso-block ${pit ? 'is-pit' : ''} ${z ? 'is-raised' : ''} ${img ? 'has-art' : ''}" data-x="${x}" data-y="${y}"
          data-h="${height}" data-t="${terrain}" data-info="坐标 ${x}, ${y} · ${terrainName(terrain)} · ${pit ? `下沉坑（字段值 ${height} 为坑深）` : `高度标记 ${height}（约 ${z} 层）`}${terrainDesc(terrain) ? ' · ' + terrainDesc(terrain) : ''}"
          style="grid-column:${x + 1};grid-row:${y + 1};--h:${z};--lift:${lift}px;${terrainStyle(terrain)}">
          ${walls}<span class="world-iso-top"></span></div>`;
    }).join('');
    const quad = Math.floor((((yaw % 360) + 360) % 360) / 90);
    const markup = `<div class="world-iso-frame" data-world-iso-view="${map.id}"
        data-yaw="${yaw}" data-tilt="${tilt}" data-scale="${scale}" data-quad="${quad}"
        style="--zoom:${scale}">
      <div class="world-iso-stage" style="width:${w * cell}px;height:${h * cell}px;--cell:${cell}px">
        <div class="world-iso-canvas view3d" style="--tilt:${tilt}deg;--yaw:${yaw}deg;--lift:${lift}px;
            grid-template-columns:repeat(${w},var(--cell));grid-template-rows:repeat(${h},var(--cell))">
          <div class="world-iso-base" style="--slab:${Math.round(cell * 0.9)}px"></div>
          ${grid.join('')}${blocks}
        </div>
      </div>
      <div class="world-iso-hint">拖动旋转（左右 / 上下）· 滚轮缩放 · 地形块按客户端高度标记堆叠</div>
      <div class="world-iso-cam"><span>水平 ${Math.round(yaw)}°</span><span>俯仰 ${Math.round(tilt)}°</span><span>${Math.round(scale * 100)}%</span></div>
    </div>`;
    if (_isoCache.size > 16) _isoCache.delete(_isoCache.keys().next().value);
    _isoCache.set(key, markup);
    return markup;
  }
  function shadeRgb(hex, tone) {
    const n = parseInt(String(hex).slice(1), 16);
    if (Number.isNaN(n)) return {top: '#555', bottom: '#333'};
    const ch = k => Math.max(0, Math.min(255, Math.round((n >> k & 255) * tone)));
    const lo = k => Math.max(0, Math.min(255, Math.round((n >> k & 255) * tone * 0.72)));
    return {top: `rgb(${ch(16)},${ch(8)},${ch(0)})`,
            bottom: `rgb(${lo(16)},${lo(8)},${lo(0)})`};
  }
  function shade(hex) {
    const c = shadeRgb(hex, .52);
    return c.top;
  }

  function gridSvg(map, cellSize, hiddenTerrains) {
    const cells = (map.cells || []).filter(c => !hiddenTerrains.has(c[3]));
    if (!(map.cells || []).length) {
      return '<div class="world-grid-empty">该地图没有网格数据（多为过场 / 场景模型）。</div>';
    }
    const w = Math.max(1, map.width), h = Math.max(1, map.height);
    const size = cellSize, pad = 26;
    const W = w * size + pad * 2, H = h * size + pad * 2;
    // Background chessboard makes empty cells and holes obvious.
    const background = [];
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      background.push(`<rect x="${pad + x * size}" y="${pad + y * size}" width="${size}" height="${size}"
        fill="${(x + y) % 2 ? '#ffffff08' : '#00000010'}"/>`);
    }
    const grid = [];
    for (let x = 0; x <= w; x++) grid.push(`<line x1="${pad + x * size}" y1="${pad}" x2="${pad + x * size}" y2="${pad + h * size}" class="world-grid-line"/>`);
    for (let y = 0; y <= h; y++) grid.push(`<line x1="${pad}" y1="${pad + y * size}" x2="${pad + w * size}" y2="${pad + y * size}" class="world-grid-line"/>`);
    const labels = [];
    for (let x = 0; x < w; x += 2) labels.push(`<text class="world-axis" x="${pad + x * size + size / 2}" y="${pad - 8}" text-anchor="middle">${x}</text>`);
    for (let y = 0; y < h; y += 2) labels.push(`<text class="world-axis" x="${pad - 8}" y="${pad + y * size + size / 2 + 3}" text-anchor="end">${y}</text>`);
    const patterns = [...new Set(cells.map(c => c[3]))].map(tt => {
      const img = terrainFace(tt, 'top') || terrainImage(tt);
      return img ? `<pattern id="wt-${map.id}-${tt}" width="1" height="1" patternContentUnits="objectBoundingBox">
          <image href="${img}" x="0" y="0" width="1" height="1" preserveAspectRatio="xMidYMid slice"/></pattern>` : '';
    }).join('');
    const rects = cells.map(c => {
      const [x, y, height, terrain] = c;
      const fill = terrainColour(terrain);
      const img = terrainFace(terrain, 'top') || terrainImage(terrain);
      return `<g class="world-cell" data-x="${x}" data-y="${y}" data-h="${height}" data-t="${terrain}"
          data-info="坐标 ${x}, ${y} · ${terrainName(terrain)}（地形 ${terrain}） · 高度标记 ${height}${terrainDesc(terrain) ? ' · ' + terrainDesc(terrain) : ''}">
        <rect x="${pad + x * size}" y="${pad + y * size}" width="${size}" height="${size}" fill="${img ? `url(#wt-${map.id}-${terrain})` : fill}"/>
        ${height ? `<rect x="${pad + x * size + 2}" y="${pad + y * size + 2}" width="${size - 4}" height="${size - 4}"
            fill="none" stroke="#ffffff" stroke-opacity=".55" stroke-width="1.5" pointer-events="none"/>` : ''}
        ${size >= 22 ? `<text class="world-cell-h" x="${pad + x * size + size / 2}" y="${pad + y * size + size / 2 + 3}"
            text-anchor="middle" pointer-events="none">${height || ''}</text>` : ''}
      </g>`;
    }).join('');
    return `<div class="world-grid-scroll"><svg class="world-grid" viewBox="0 0 ${W} ${H}"
        width="${W}" height="${H}" role="img" aria-label="${esc(map.name)} 地形网格">
        <defs>${patterns}</defs>${background.join('')}${grid.join('')}${labels.join('')}${rects}</svg></div>`;
  }

  function mapCard(m, state) {
    const terrains = [...new Set((m.cells || []).map(c => c[3]))].sort((a, b) => a - b);
    const legend = terrains.map(tt =>
      `<button type="button" class="world-terrain-toggle${state.hidden.has(tt) ? ' is-off' : ''}"
        data-world-terrain="${tt}" title="点击隐藏 / 显示该地形">
        <i style="${terrainStyle(tt)}"></i>${terrainName(tt)}<small>${tt}</small></button>`).join('');
    return `<article class="content-card world-map-card" data-world-map="${m.id}">
      <div class="world-map-head"><div>
        <h2>${esc((m.stages || [])[0] || m.name || '(未命名)')} <small>#${m.id}</small></h2>
        ${(m.stages || []).length > 1 ? `<p class="world-stage-names small-text">关卡别名：${m.stages.slice(1).map(esc).join('、')}</p>` : ''}
        <p class="small-text muted world-model-name">${esc(m.name)}${m.scene ? ' · ' + esc(m.scene) : ''}</p>
        <div class="tag-list">
          <span class="mech-tag">${esc(m.weather || '无天气')}</span>
          ${m.weatherType ? `<span class="mech-tag">${esc(m.weatherType)}</span>` : ''}
          <span class="mech-tag">时段 ${esc(m.timeSlot)}</span>
          <span class="mech-tag">${fmt((m.cells || []).length)} 格 · ${m.width}×${m.height}</span>
        </div>
        <p class="small-text muted">模型 <code>${esc(m.model)}</code>${m.bgm ? ` · BGM ${esc(m.bgm)}` : ''}</p>
        ${m.weatherDesc ? `<p class="small-text">${esc(m.weatherDesc)}</p>` : ''}
      </div>
      <div class="world-map-actions">
        <button type="button" class="button secondary small" data-world-zoom="-1" aria-label="缩小">−</button>
        <span class="world-zoom-value">${state.size}px</span>
        <button type="button" class="button secondary small" data-world-zoom="1" aria-label="放大">+</button>
        <button type="button" class="button secondary small" data-world-reset="${m.id}" title="恢复水平 45° / 俯仰 54° / 100%">重置视角</button>
        <button type="button" class="button secondary small" data-world-view="${m.id}">${state.view === '3d' ? '2D 俯视' : '3D 立体'}</button>
        <button type="button" class="button secondary small" data-world-fullscreen="${m.id}">大图</button>
      </div></div>
      ${state.view === '3d' ? gridIso(m, state.size, state.hidden, state.yaw, state.tilt, state.scale) : gridSvg(m, state.size, state.hidden)}
      <div class="world-legend world-terrain-legend">${legend}</div>
      <p class="world-cell-info small-text muted">把鼠标移到格子上可查看坐标、地形名称与效果说明、高度标记。</p>
    </article>`;
  }

  /* ---------------- Shared code rendering ---------------- */
  const LUA_KEYWORDS = /\b(local|function|end|if|then|else|elseif|for|in|pairs|ipairs|do|while|return|and|or|not|nil|true|false|repeat|until|break)\b/g;
  function luaHtml(code) {
    const safe = esc(code);
    return safe
      .replace(/(--[^\n]*)/g, '<span class="lua-comment">$1</span>')
      .replace(/(&quot;[^&]*?&quot;|&#39;[^&]*?&#39;)/g, '<span class="lua-string">$1</span>')
      .replace(LUA_KEYWORDS, '<span class="lua-keyword">$1</span>')
      .replace(/\b(\d+(?:\.\d+)?)\b/g, '<span class="lua-number">$1</span>')
      .replace(/\b(owner|map|target|unit|block|param|spell|buff|dmg|hp)\b/g, '<span class="lua-var">$1</span>');
  }
  function codeBlock(code, cls = '') {
    return `<pre class="world-lua ${cls}"><code>${luaHtml(code)}</code></pre>`;
  }
  function kindBadge(kind) {
    const cls = kind === '技能决策' ? 'is-decision' : kind === '目标排序' ? 'is-target'
      : kind === 'AI 参数' ? 'is-param' : '';
    return `<span class="world-kind ${cls}">${esc(kind)}</span>`;
  }

  function renderMaps(root, helpers = {}) {
    const data = W();
    if (!data) {
      root.innerHTML = intro('CLIENT WORLD', '战斗地图', '还没有地图数据，请在「本地更新」里完成一次更新。');
      return;
    }
    const maps = data.maps || [];
    let query = '', onlyGrid = true, selected = null;
    const meta = data.mapMeta || {};
    const state = {size: 26, hidden: new Set(), view: '3d', yaw: 45, tilt: 54, scale: 1};
    const stage = () => root.querySelector('#world-map-stage');
    const picker = () => root.querySelector('#world-map-picker');
    const stats = () => root.querySelector('#world-map-count');
    const statusTerms = q => (meta.terrainStatuses || []).filter(st =>
      st.name && st.name.toLowerCase().includes(q));
    const searchText = m => [m.name, m.model, m.weather, m.weatherDesc, m.weatherType,
      m.scene, m.id, ...(m.stages || []), ...(m.terrainNames || []),
      ...(m.terrainDescs || []),
      ...(meta.terrainStatuses || []).filter(st =>
        (m.terrainNames || []).some(n => n && (st.name.includes(n) || st.desc.includes(n))))
        .map(st => st.name + ' ' + st.desc)].join(' ').toLowerCase();
    const matchesStatus = (m, q) => {
      const states = statusTerms(q);
      if (!states.length) return false;
      const flammable = states.some(st => /燃烧|灼烧|火/.test(st.name));
      if (flammable) return (m.terrainDescs || []).some(d => d.includes('点燃'));
      return states.some(st => (m.terrainNames || []).some(n => n && st.desc.includes(n)));
    };
    const filtered = () => maps.filter(m => {
      if (onlyGrid && !(m.cells || []).length) return false;
      if (!query) return true;
      return searchText(m).includes(query) || matchesStatus(m, query);
    });
    const mapTitle = m => (m.stages || [])[0] || m.name || `地图 ${m.id}`;
    const paintPicker = () => {
      const hits = filtered();
      stats().textContent = `${fmt(hits.length)} / ${fmt(maps.length)} 张地图`;
      if (!hits.some(m => String(m.id) === String(selected))) {
        selected = hits.length ? String(hits[0].id) : null;
      }
      // Rebuild the picker only when the result set actually changes; a
      // selection change just toggles one class.
      const ids = hits.map(m => String(m.id)).join(',');
      if (picker().dataset.ids !== ids) {
        picker().dataset.ids = ids;
        picker().innerHTML = hits.map(m => `<button type="button"
            class="world-pick-item ${String(m.id) === String(selected) ? 'is-active' : ''}"
            data-world-pick="${m.id}" title="${esc(mapTitle(m))}">
            <span class="world-pick-id">#${m.id}</span>
            <span class="world-pick-name">${esc(mapTitle(m))}</span>
            <span class="world-pick-sub">${esc(m.scene || m.model || '')} · ${fmt((m.cells || []).length)} 格</span>
          </button>`).join('') || '<p class="muted small-text">没有匹配的地图。</p>';
      }
      for (const btn of picker().querySelectorAll('.world-pick-item'))
        btn.classList.toggle('is-active', btn.dataset.worldPick === String(selected));
      const active = picker().querySelector('.is-active');
      if (active) active.scrollIntoView({block: 'nearest'});
    };
    const fitMaps = frame => {
      const st = frame?.querySelector('.world-iso-stage');
      if (!st) return;
      const w = st.offsetWidth || 1, h = st.offsetHeight || 1;
      // The 3D projection compresses the grid vertically; leave headroom for
      // raised blocks and the floating slab.
      const fit = Math.min(frame.clientWidth / w, frame.clientHeight / h) * 0.82;
      frame.style.setProperty('--fit', Math.max(0.35, Math.min(3, fit)).toFixed(3));
    };
    const fitAll = () => root.querySelectorAll('[data-world-iso-view]').forEach(fitMaps);
    const paintStage = () => {
      const m = maps.find(x => String(x.id) === String(selected));
      stage().innerHTML = m ? mapCard(m, state)
        : '<p class="result-empty">左侧选择一张地图即可查看。</p>';
      // Cached markup carries the camera values from when it was built; apply
      // the current camera to every freshly inserted frame.
      for (const frame of stage().querySelectorAll('[data-world-iso-view]')) {
        const canvas = frame.querySelector('.world-iso-canvas');
        if (canvas) {
          canvas.style.setProperty('--yaw', state.yaw + 'deg');
          canvas.style.setProperty('--tilt', state.tilt + 'deg');
        }
        frame.dataset.yaw = state.yaw; frame.dataset.tilt = state.tilt;
        frame.dataset.scale = state.scale;
        frame.dataset.quad = Math.floor((((state.yaw % 360) + 360) % 360) / 90);
        frame.style.setProperty('--zoom', state.scale);
        const spans = frame.querySelector('.world-iso-cam')?.children;
        if (spans) {
          if (spans[0]) spans[0].textContent = `水平 ${Math.round(state.yaw)}°`;
          if (spans[1]) spans[1].textContent = `俯仰 ${Math.round(state.tilt)}°`;
          if (spans[2]) spans[2].textContent = `${Math.round(state.scale * 100)}%`;
        }
      }
      fitAll();
    };
    const paint = () => { paintPicker(); paintStage(); };

    root.innerHTML = `<div class="world-sticky-head world-sticky-compact">
        <div class="world-toolbar">
          <input type="search" id="world-map-query" placeholder="搜索关卡 / 场景 / 地形 / 天气 / 模型 / id" aria-label="搜索地图">
          <label class="tool-check"><input type="checkbox" id="world-map-grid" checked><span>有网格</span></label>
          <button type="button" class="button secondary small" id="world-map-zoom-all">放大</button>
          <button type="button" class="button secondary small" id="world-map-view-all">2D / 3D</button>
          <span class="small-text muted" id="world-map-count"></span>
          <details class="world-head-more"><summary>说明</summary>
            <div class="world-head-more-body">
              <p>战斗地图取自客户端 <code>map</code> / <code>weather</code> / <code>field_type</code> 表，
                 地形块直接使用客户端 <code>terrain_atlas</code> 贴图；拖动旋转（左右 / 上下）、滚轮缩放，立柱表示高度标记。</p>
              <p>深水 / 浅水 / 禁行在客户端是「可被推落的坑」，其字段记录坑深而非堆叠高度，因此显示为下沉水面。</p>
              <p>共 ${fmt(maps.length)} 张地图、${fmt((meta.terrainTypes || []).reduce((a, x) => a + x.cells, 0))} 个地块；
                 地形类型 ${fmt((meta.terrainTypes || []).length)} 种，带网格 ${fmt(maps.filter(m => (m.cells || []).length).length)} 张。</p>
              <div class="world-legend">${(meta.terrainTypes || []).slice(0, 12).map(x =>
                `<span title="${esc(x.desc || '')}"><i style="${terrainStyle(x.id)}"></i>${esc(x.name || '地形 ' + x.id)} · ${fmt(x.cells)} 格</span>`).join('')}</div>
            </div></details>
        </div></div>
        <div class="world-map-workspace">
          <nav class="world-picker" id="world-map-picker" aria-label="地图列表"></nav>
          <div id="world-map-list" class="world-map-stage" role="region" aria-label="当前地图">
            <div id="world-map-stage"></div>
          </div>
        </div>
        <dialog id="world-map-dialog" class="world-dialog"><div class="world-dialog-head">
          <strong id="world-dialog-title">地形大图</strong>
          <button type="button" class="button secondary small" id="world-dialog-close">关闭</button></div>
          <div id="world-dialog-body"></div></dialog>`;
    paint();
    if (window.__wikiMapResize) window.removeEventListener('resize', window.__wikiMapResize);
    window.__wikiMapResize = () => { if (root && root.isConnected) fitAll(); };
    window.addEventListener('resize', window.__wikiMapResize);
    let searchFrame = 0;
    root.querySelector('#world-map-query').addEventListener('input', e => {
      query = e.target.value.trim().toLowerCase();
      if (searchFrame) return;
      searchFrame = requestAnimationFrame(() => { searchFrame = 0; paint(); });
    });
    root.querySelector('#world-map-grid').addEventListener('change', e => {
      onlyGrid = e.target.checked; paint();
    });
    root.querySelector('#world-map-view-all').addEventListener('click', () => {
      state.view = state.view === '3d' ? '2d' : '3d'; paintStage();
    });
    root.querySelector('#world-map-zoom-all').addEventListener('click', () => {
      state.size = state.size >= 30 ? 16 : 30;
      root.querySelector('#world-map-zoom-all').textContent = state.size >= 30 ? '缩小' : '放大';
      paintStage();
    });
    picker().addEventListener('click', e => {
      const btn = e.target.closest('[data-world-pick]');
      if (!btn) return;
      selected = btn.dataset.worldPick;
      for (const item of picker().querySelectorAll('.world-pick-item'))
        item.classList.toggle('is-active', item.dataset.worldPick === selected);
      paintStage();
    });
    // Delegate the map card controls (zoom / terrain toggles / view / dialog).
    const list = () => root.querySelector('#world-map-list');
    list().addEventListener('click', e => {
      const zoom = e.target.closest('[data-world-zoom]');
      if (zoom) {
        state.size = Math.max(12, Math.min(48, state.size + Number(zoom.dataset.worldZoom) * 6));
        paintStage(); return;
      }
      const tt = e.target.closest('[data-world-terrain]');
      if (tt) {
        const id = Number(tt.dataset.worldTerrain);
        if (state.hidden.has(id)) state.hidden.delete(id); else state.hidden.add(id);
        paintStage(); return;
      }
      const reset = e.target.closest('[data-world-reset]');
      if (reset) { state.yaw = 45; state.tilt = 54; state.scale = 1; paintStage(); return; }
      const view = e.target.closest('[data-world-view]');
      if (view) { state.view = state.view === '3d' ? '2d' : '3d'; paintStage(); return; }
      const full = e.target.closest('[data-world-fullscreen]');
      if (full) {
        const m = maps.find(x => String(x.id) === String(full.dataset.worldFullscreen));
        if (!m) return;
        root.querySelector('#world-dialog-title').textContent = mapTitle(m);
        root.querySelector('#world-dialog-body').innerHTML = state.view === '3d'
          ? gridIso(m, 34, state.hidden, state.yaw, state.tilt, state.scale) : gridSvg(m, 34, state.hidden);
        root.querySelector('#world-map-dialog').showModal();
        requestAnimationFrame(() => {
          const dlg = root.querySelector('#world-map-dialog');
          for (const f of dlg.querySelectorAll('[data-world-iso-view]')) fitMaps(f);
        });
      }
    });
    root.querySelector('#world-dialog-close').addEventListener('click', () =>
      root.querySelector('#world-map-dialog').close());
    // CSS-3D camera. NOTHING is rebuilt while dragging or zooming: we only
    // mutate CSS custom properties, which the compositor handles directly.
    // A single rAF coalesces pointermove bursts into one style write per frame.
    let drag = null, camFrame = 0, pendingCam = null;
    const applyCam = frame => {
      const canvas = frame.querySelector('.world-iso-canvas');
      if (canvas) {
        canvas.style.setProperty('--yaw', state.yaw + 'deg');
        canvas.style.setProperty('--tilt', state.tilt + 'deg');
      }
      frame.dataset.yaw = state.yaw;
      frame.dataset.tilt = state.tilt;
      frame.dataset.scale = state.scale;
      frame.dataset.quad = Math.floor((((state.yaw % 360) + 360) % 360) / 90);
      frame.style.setProperty('--zoom', state.scale);
      const cam = frame.querySelector('.world-iso-cam');
      if (cam) {
        const spans = cam.children;
        if (spans[0]) spans[0].textContent = `水平 ${Math.round(state.yaw)}°`;
        if (spans[1]) spans[1].textContent = `俯仰 ${Math.round(state.tilt)}°`;
        if (spans[2]) spans[2].textContent = `${Math.round(state.scale * 100)}%`;
      }
    };
    const flushCam = () => {
      camFrame = 0;
      const frame = pendingCam; pendingCam = null;
      if (frame && frame.isConnected) applyCam(frame);
    };
    const scheduleCam = frame => {
      pendingCam = frame;
      if (!camFrame) camFrame = requestAnimationFrame(flushCam);
    };
    const orbitDown = e => {
      const frame = e.target.closest('[data-world-iso-view]');
      if (!frame || e.target.closest('button')) return;
      drag = {frame, x: e.clientX, y: e.clientY, yaw: state.yaw, tilt: state.tilt};
      frame.classList.add('is-dragging');
    };
    const orbitMove = e => {
      if (!drag) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      state.yaw = ((drag.yaw - dx * 0.4) % 360 + 360) % 360;
      state.tilt = Math.max(0, Math.min(85, drag.tilt - dy * 0.35));
      scheduleCam(drag.frame);
    };
    const orbitUp = () => {
      if (!drag) return;
      drag.frame.classList.remove('is-dragging');
      drag = null;
    };
    for (const host of [list(), root.querySelector('#world-dialog-body')]) {
      host.addEventListener('pointerdown', orbitDown);
    }
    // Re-rendering replaces the previous window listeners instead of stacking.
    const prev = window.__wikiMapOrbit;
    if (prev) {
      window.removeEventListener('pointermove', prev.move);
      window.removeEventListener('pointerup', prev.up);
      window.removeEventListener('pointercancel', prev.up);
    }
    window.__wikiMapOrbit = {move: orbitMove, up: orbitUp};
    window.addEventListener('pointermove', orbitMove);
    window.addEventListener('pointerup', orbitUp);
    window.addEventListener('pointercancel', orbitUp);
    const zoomHandler = e => {
      const frame = e.target.closest('[data-world-iso-view]');
      if (!frame) return;
      e.preventDefault();
      state.scale = Math.max(0.4, Math.min(2, state.scale + (e.deltaY < 0 ? 0.1 : -0.1)));
      scheduleCam(frame);
    };
    for (const host of [list(), root.querySelector('#world-dialog-body')]) {
      host.addEventListener('wheel', zoomHandler, {passive: false});
    }
    list().addEventListener('mouseover', e => {
      const cell = e.target.closest('[data-info]');
      const info = root.querySelector('#world-map-list .world-cell-info');
      if (cell && info) info.textContent = cell.dataset.info;
    });
  }

  /* ---------------- AI ---------------- */
  function sequenceTimeline(seq) {
    if (!seq.length) return '';
    return `<div class="world-timeline">${seq.slice(0, 24).map((s, i) =>
      `<span class="world-timeline-step" title="第 ${i + 1} 步 · 技能 #${s.id}"><em>${i + 1}</em>${esc(s.name)}</span>`).join('')}</div>`;
  }

  function unitCard(u, expanded) {
    const mode = u.byOrder ? '按技能顺序' : u.sorted ? '按优先级排序' : '默认决策';
    const modeCls = u.byOrder ? 'is-order' : u.sorted ? 'is-priority' : '';
    return `<article class="content-card world-ai-card" data-world-ai="${u.id}">
      <div class="world-ai-head"><h2>${esc(u.name || '(未命名)')} <small>#${u.id}</small></h2>
        <span class="world-kind ${modeCls}">${mode}</span></div>
      <p class="small-text muted">${esc(u.editor || '')}</p>
      <div class="tag-list">
        ${u.bossMode ? '<span class="mech-tag world-tag-boss">BOSS 固定序列</span>' : ''}
        ${u.personality ? `<span class="mech-tag">个性：${esc(u.personality)}</span>` : ''}
        <span class="mech-tag">${(u.skills || []).length} 技能</span>
        ${u.sequence.length ? `<span class="mech-tag">${u.sequence.length} 步序列</span>` : ''}
      </div>
      <dl class="calculation-steps">
        <div><dt>普攻 / 反应 / 队长技</dt><dd>${[u.melee, u.reactive, u.leader].map(x => x ? `#${x}` : '—').join(' / ')}</dd></div>
        <div><dt>携带技能</dt><dd>${(u.skills || []).map(s => `${esc(s.name)} (#${s.id})`).join('、') || '—'}</dd></div>
      </dl>
      ${u.sequence.length ? `<details class="world-timeline-fold"${expanded ? ' open' : ''}><summary>行动序列（${u.sequence.length} 步）</summary>${sequenceTimeline(u.sequence)}</details>` : ''}
    </article>`;
  }

  function scriptCard(s) {
    const meta = [
      s.order ? `优先级 ${esc(s.order)}` : '',
      s.moveClose ? `移动 ${esc(s.moveClose)}` : '',
      s.skillType ? esc(s.skillType) : '',
    ].filter(Boolean).join(' · ');
    return `<article class="content-card world-lua-card"><div class="world-ai-head">
        <h2>${esc(s.name)} <small>技能 #${s.id}</small></h2>${kindBadge(s.kind)}</div>
      <div class="tag-list"><span class="mech-tag">${esc(s.field)}</span>${meta ? `<span class="mech-tag">${meta}</span>` : ''}</div>
      ${s.lua ? `<details open><summary>客户端 ${esc(s.kind)}脚本（Lua 原文）</summary>${codeBlock(s.lua)}</details>`
              : '<p class="small-text muted">该技能只有数值型 AI 参数，没有 Lua 脚本。</p>'}
    </article>`;
  }

  function aiGuideHtml(quick, title, intro) {
    if (!quick || !quick.length) return '';
    return `<section class="ai-guide"><div class="ai-guide-head"><h3>${esc(title)}</h3>
        <p>${esc(intro)}</p></div>
      <div class="ai-guide-flow">${quick.map((q, i) => `<article class="ai-guide-card">
        <div class="ai-guide-num">${i + 1}</div>
        <div class="ai-guide-body"><h4>${esc(q.title)}</h4>
          ${q.summary ? `<p class="ai-guide-summary">${esc(q.summary)}</p>` : ''}
          ${q.text ? `<p class="ai-guide-summary">${esc(q.text)}</p>` : ''}
          ${q.steps ? `<ol class="ai-guide-steps">${q.steps.map(s => `<li>${esc(s)}</li>`).join('')}</ol>` : ''}
          <div class="tag-list">${(q.fields || []).map(f => `<code class="mech-tag">${esc(f)}</code>`).join('')}</div>
        </div></article>`).join('')}</div></section>`;
  }

  function renderAI(root, helpers = {}) {
    const data = W();
    if (!data) {
      root.innerHTML = intro('CLIENT AI', '自动战斗 AI', '还没有 AI 数据，请在「本地更新」里完成一次更新。');
      return;
    }
    const units = [...(data.aiUnits || [])].sort((a, b) =>
      (b.sequence?.length || 0) - (a.sequence?.length || 0));
    const scripts = data.aiScripts || [];
    const meta = data.aiMeta || {};
    let query = '', tab = 'units', page = 1, perPage = 12, kindFilter = '';
    const list = () => root.querySelector('#world-ai-list');
    const count = () => root.querySelector('#world-ai-count');
    const filtered = () => (tab === 'scripts' ? scripts : units).filter(x => {
      if (kindFilter && tab === 'scripts' && x.kind !== kindFilter) return false;
      if (!query) return true;
      const hay = (x.name + ' ' + (x.editor || '') + ' ' + (x.personality || '') + ' '
                   + (x.lua || '') + ' ' + x.id).toLowerCase();
      return hay.includes(query);
    });
    const paintList = () => {
      const hits = filtered();
      const pages = Math.max(1, Math.ceil(hits.length / perPage));
      page = Math.min(page, pages);
      count().textContent = `${fmt(hits.length)} / ${fmt(tab === 'scripts' ? scripts.length : units.length)} 条`;
      list().innerHTML = hits.slice((page - 1) * perPage, page * perPage)
          .map(x => tab === 'scripts' ? scriptCard(x) : unitCard(x, false)).join('')
        || '<p class="muted">没有匹配结果。</p>';
      updatePager('world-ai-pager', page, pages, hits.length, perPage);
    };
    const kinds = Object.keys(meta.kinds || {});
    root.innerHTML = intro('CLIENT AI', '自动战斗 AI',
        'AI 每回合做三件事：走到哪、放哪个技能、打谁。下面用三步图讲清规则，再往下查看单位配置与原始 Lua 决策脚本。')
      + `<div class="world-stat-grid">
          <div><strong>${fmt(units.length)}</strong><span>客户端单位</span></div>
          <div><strong>${fmt(meta.bossUnits || 0)}</strong><span>BOSS 固定序列</span></div>
          <div><strong>${fmt(meta.luaScripts || 0)}</strong><span>Lua 决策脚本</span></div>
          <div><strong>${fmt(scripts.length)}</strong><span>AI 相关记录</span></div>
        </div>
        <div class="content-card world-toolbar">
          <div class="world-tabs"><button type="button" data-world-tab="units" class="active">单位配置（${fmt(units.length)}）</button>
            <button type="button" data-world-tab="scripts">AI 代码（${fmt(scripts.length)}）</button></div>
          <label class="tool-field"><span>搜索</span><input type="search" id="world-ai-query" placeholder="单位名 / 编辑名 / 个性 / Lua 内容"></label>
          <select id="world-ai-kind" class="world-kind-select" hidden>${kinds.map(k => `<option value="${esc(k)}">${esc(k)}</option>`).join('')}</select>
          <span class="small-text muted" id="world-ai-count"></span>
        </div>
        ${aiGuideHtml(meta.pathfinding?.quick, '走路与选目标 · 三步看懂',
          '自动战斗每回合先决定走到哪，再决定放哪个技能、打谁。三步都只用配置表里的字段与打分脚本。')}
        <details class="content-card world-priority-card"><summary><h3>技术细节：寻路与选人的全部字段</h3></summary>
          <ol class="world-priority-steps">${(meta.pathfinding?.explanation || []).map(esc).map(x => `<li>${x}</li>`).join('')}</ol>
          <div class="world-pf-grid">
            <div><h4>移动规则 move_type</h4>${(meta.pathfinding?.moveTypes || []).map(x =>
              `<span title="${esc(x.desc)}">${esc(x.name)}</span>`).join('')}</div>
            <div><h4>移动力分布 unit.mobility</h4>${(meta.pathfinding?.mobility || []).map(x =>
              `<span>${esc(x.value)} 格 · ${fmt(x.units)} 单位</span>`).join('')}</div>
            <div><h4>目标方法 target_method（使用数）</h4>${(meta.pathfinding?.targetMethods || []).slice(0, 10).map(x =>
              `<span>${esc(x.name)} · ${fmt(x.skills)}</span>`).join('')}</div>
            <div><h4>范围形状 range_select</h4>${(meta.pathfinding?.rangeSelects || []).map(x =>
              `<span>${esc(x.name)}</span>`).join('')}</div>
            <div><h4>地形通行代价 field_type.mobility</h4>${(meta.pathfinding?.terrainCost || []).slice(0, 12).map(x =>
              `<span title="${esc(x.type)}">${esc(x.name)} ${esc(x.mobility)}${x.rainMobility ? ' / 雨 ' + esc(x.rainMobility) : ''}</span>`).join('')}</div>
            <div><h4>地图 Lua API（出现次数）</h4>${(meta.pathfinding?.luaApis || []).slice(0, 12).map(x =>
              `<span>${esc(x.api)} · ${fmt(x.times)}</span>`).join('')}</div>
          </div>
          <p class="small-text muted">统计：${fmt(meta.pathfinding?.targetFilterScripts || 0)} 段目标过滤 Lua ·
            ${fmt(meta.pathfinding?.targetOrderScripts || 0)} 段目标排序 Lua ·
            ${fmt(meta.pathfinding?.aiOrderScripts || 0)} 段技能决策 Lua ·
            ${(meta.pathfinding?.aiMoveClose || []).length} 个技能带站位偏好。
            最短路求解器在客户端编译代码中，配置表只记录输入与打分脚本。</p>
        </details>
        ${aiGuideHtml(meta.priority?.quick, '技能优先级 · 三步看懂',
          '技能不是随便放的：先按静态优先级排队，再用战场状态打分，最后选得分最高的技能与目标。')}
        <details class="content-card world-priority-card"><summary><h3>技术细节：优先级评分的完整链路</h3></summary>
          <ol class="world-priority-steps">${(meta.priority?.explanation || []).map(esc).map(x => `<li>${x}</li>`).join('')}</ol>
          <div class="world-priority-grid">
            <div><h4>静态优先级 ai_skill_order</h4>
              ${(meta.priority?.baseOrder || []).slice(0, 8).map(x =>
                `<span>优先级 ${esc(x.order)}：${fmt(x.skills)} 个技能</span>`).join('')}</div>
            <div><h4>Lua 动态权重（return 值）</h4>
              ${(meta.priority?.luaWeights || []).slice(0, 8).map(x =>
                `<span class="${x.weight <= -10000 ? 'is-veto' : x.weight > 0 ? 'is-boost' : ''}">${esc(x.weight)} ×${fmt(x.times)}${x.weight <= -10000 ? '（否决）' : x.weight > 0 ? '（加权）' : ''}</span>`).join('')}</div>
          </div>
          <p class="small-text muted">统计：${fmt(meta.priority?.staticOrderSkills || 0)} 个技能配置静态优先级 ·
            ${fmt(meta.priority?.luaScripts || 0)} 段决策 Lua ·
            ${fmt(meta.priority?.sortedUnits || 0)} 个单位按优先级排序 ·
            ${fmt(meta.priority?.bossSequenceUnits || 0)} 个 BOSS 使用固定序列。
            完整分析与代码位置见本地 <code>output/client-code/AI_PRIORITY.md</code>。</p>
        </details>
        <div class="content-card world-summary"><h3>行动逻辑说明</h3>
          <p>技能顺序模式：${Object.entries(meta.orderModes || {}).map(([k, v]) => `${esc(k)} ${fmt(v)}`).join('、')}。
             BOSS 单位按 <code>boss_skill_sequence</code> 逐步循环施放；展开单位卡片可看时间线。
             Lua 脚本里的 <code>owner</code> 是当前单位、<code>map</code> 是战场，返回值是技能权重（负数通常表示不选）。原文完整保留，未做改写。</p></div>
        <div id="world-ai-list"></div>
        <nav class="world-pager" id="world-ai-pager" aria-label="翻页"></nav>`;
    paintList();
    root.querySelector('#world-ai-query').addEventListener('input', e => {
      query = e.target.value.trim().toLowerCase(); page = 1; paintList();
    });
    root.querySelector('#world-ai-kind').addEventListener('change', e => {
      kindFilter = e.target.value; page = 1; paintList();
    });
    bindPager(root, 'world-ai-pager', value => {
      const pages = Math.max(1, Math.ceil(filtered().length / perPage));
      page = pageAction(value, page, pages);
      paintList();
    }, size => { perPage = size; page = 1; paintList(); });
    root.querySelector('.world-tabs').addEventListener('click', e => {
      const btn = e.target.closest('[data-world-tab]');
      if (!btn) return;
      tab = btn.dataset.worldTab; page = 1; kindFilter = '';
      for (const b of root.querySelectorAll('[data-world-tab]')) b.classList.toggle('active', b === btn);
      const sel = root.querySelector('#world-ai-kind');
      sel.hidden = tab !== 'scripts'; sel.value = '';
      root.querySelector('#world-ai-query').placeholder = tab === 'scripts'
        ? '技能名 / Lua 内容 / 字段' : '单位名 / 编辑名 / 个性';
      paintList();
    });
  }

  /* ---------------- Client code browser ---------------- */
  function renderCode(root, helpers = {}) {
    const data = window.WIKI_CLIENT_CODE;
    if (!data) {
      root.innerHTML = intro('CLIENT CODE', '客户端代码', '还没有客户端代码数据，请在「本地更新」里完成一次更新。');
      return;
    }
    const scripts = data.scripts || [], meta = data.meta || {};
    let query = '', field = '', onlyAI = false, page = 1, perPage = 16;
    const list = () => root.querySelector('#world-code-list');
    const count = () => root.querySelector('#world-code-count');
    const filtered = () => scripts.filter(s => {
      if (field && `${s.table}.${s.field}` !== field) return false;
      if (onlyAI && !s.ai) return false;
      if (!query) return true;
      return (s.name + ' ' + s.code + ' ' + s.table + ' ' + s.field + ' ' + s.id).toLowerCase().includes(query);
    });
    const paintList = () => {
      const hits = filtered();
      const pages = Math.max(1, Math.ceil(hits.length / perPage));
      page = Math.min(page, pages);
      count().textContent = `${fmt(hits.length)} / ${fmt(scripts.length)} 段`;
      list().innerHTML = hits.slice((page - 1) * perPage, page * perPage).map(s => `<article class="content-card world-code-card">
          <div class="world-ai-head"><h2>${esc(s.name)} <small>${esc(s.table)} #${s.id}</small></h2>
            ${s.ai ? '<span class="world-kind is-decision">AI 相关</span>' : `<span class="world-kind">${esc(s.label)}</span>`}</div>
          <div class="tag-list"><span class="mech-tag">${esc(s.table)}.${esc(s.field)}</span>
            <span class="mech-tag">${s.refs.length} 处引用</span>
            ${s.type != null ? `<span class="mech-tag">类型 ${esc(s.type)}</span>` : ''}</div>
          <details open><summary>Lua 原文</summary>${codeBlock(s.code)}</details>
        </article>`).join('') || '<p class="muted">没有匹配的代码。</p>';
      updatePager('world-code-pager', page, pages, hits.length, perPage);
    };
    root.innerHTML = intro('CLIENT CODE', '客户端代码',
        '把散落在客户端配置表各字段里的 Lua 脚本整理成可检索的代码库：特效触发条件、动态参数、状态条件、目标选择、AI 决策等。相同脚本已按内容去重并保留全部引用位置；原文未做改写。全部代码已按「表 / 字段」输出为本地 .lua 文件，见 output/client-code/。')
      + `<div class="content-card world-local-notice"><strong>本地代码目录</strong>
          <p><code>output/client-code/&lt;表&gt;/&lt;字段&gt;/&lt;id&gt;-&lt;名称&gt;.lua</code> · 共 ${fmt(meta.unique || 0)} 个文件，
          每个目录有 <code>index.md</code>，顶层有 <code>README.md</code>、<code>manifest.json</code> 与
          <code>AI_PRIORITY.md</code>（AI 优先级机制分析）。文件头注释保留配置表、id、引用位置与内容哈希。</p></div>`
      + `<div class="world-stat-grid">
          <div><strong>${fmt(meta.unique || 0)}</strong><span>去重代码段</span></div>
          <div><strong>${fmt(meta.references || 0)}</strong><span>配置表引用</span></div>
          <div><strong>${fmt((meta.fields || []).length)}</strong><span>代码字段</span></div>
          <div><strong>${fmt(meta.ai || 0)}</strong><span>AI 相关</span></div>
        </div>
        <div class="content-card world-toolbar">
          <label class="tool-field"><span>搜索代码</span><input type="search" id="world-code-query" placeholder="函数名 / 变量 / owner: / 表字段 / id"></label>
          <label class="tool-field"><span>字段分类</span><select id="world-code-field"><option value="">全部字段</option>
            ${(meta.fields || []).map(f => `<option value="${esc(f.table + '.' + f.field)}">${esc(f.label)}（${esc(f.table + '.' + f.field)}）</option>`).join('')}</select></label>
          <label class="tool-check"><input type="checkbox" id="world-code-ai"><span>仅 AI 相关</span></label>
          <span class="small-text muted" id="world-code-count"></span>
        </div>
        <div id="world-code-list"></div>
        <nav class="world-pager" id="world-code-pager" aria-label="翻页"></nav>`;
    paintList();
    root.querySelector('#world-code-query').addEventListener('input', e => {
      query = e.target.value.trim().toLowerCase(); page = 1; paintList();
    });
    root.querySelector('#world-code-field').addEventListener('change', e => {
      field = e.target.value; page = 1; paintList();
    });
    root.querySelector('#world-code-ai').addEventListener('change', e => {
      onlyAI = e.target.checked; page = 1; paintList();
    });
    bindPager(root, 'world-code-pager', value => {
      const pages = Math.max(1, Math.ceil(filtered().length / perPage));
      page = pageAction(value, page, pages);
      paintList();
    }, size => { perPage = size; page = 1; paintList(); });
  }

  /* ---------------- Enhancement & numeric random rules ---------------- */
  function renderEnhance(root, helpers = {}) {
    const D = window.WIKI_ENHANCE_DATA;
    if (!D || !D.tables?.length) {
      root.innerHTML = intro('CLIENT RULES', '强化与随机', '还没有探查数据，请在「本地更新」里完成一次更新。');
      return;
    }
    let query = '', page = 1, perPage = 4, openTable = '';
    const list = () => root.querySelector('#enhance-list');
    const count = () => root.querySelector('#enhance-count');
    const filtered = () => D.tables.filter(x => {
      if (openTable && x.table !== openTable) return false;
      if (!query) return true;
      return (x.table + ' ' + x.label + ' ' + x.note + ' ' + x.fields.join(' ')
              + ' ' + JSON.stringify(x.sample)).toLowerCase().includes(query);
    });
    const rangeRows = x => Object.entries(x.ranges || {}).map(([k, v]) =>
      `<tr><td><code>${esc(k)}</code></td><td class="enh-num">${fmt(v.min)}</td>
        <td class="enh-num">${fmt(v.max)}</td><td class="enh-num">${fmt(v.distinct)}</td></tr>`).join('');
    const fieldRows = x => x.fields.map(k =>
      `<tr><td><code>${esc(k)}</code></td><td>${esc(JSON.stringify(x.sample[k]))}</td></tr>`).join('');
    const tableCard = x => {
      const ranges = Object.entries(x.ranges || {});
      return `<article class="content-card enhance-card" data-enhance-table="${esc(x.table)}">
        <header class="enh-head">
          <div><h2>${esc(x.label)}</h2><p class="enh-note">${esc(x.note)}</p></div>
          <span class="enh-count"><strong>${fmt(x.rows)}</strong><small>行记录</small></span>
        </header>
        <div class="enh-meta"><code>${esc(x.table)}</code>
          <span>${fmt(x.fields.length)} 个字段</span><span>${fmt(ranges.length)} 个数值字段</span></div>
        <div class="enh-tags">${x.numericFields.slice(0, 9).map(k =>
          `<span class="mech-tag">${esc(k)}</span>`).join('')}</div>
        ${ranges.length ? `<details class="enh-fold" open><summary>数值取值范围<span>${ranges.length} 项</span></summary>
          <div class="enh-table-wrap"><table class="enh-table"><thead><tr>
            <th>字段</th><th>最小</th><th>最大</th><th>取值数</th></tr></thead>
            <tbody>${rangeRows(x)}</tbody></table></div></details>` : ''}
        <details class="enh-fold"><summary>字段与首行样例<span>${x.fields.length} 项</span></summary>
          <div class="enh-table-wrap"><table class="enh-table"><thead><tr>
            <th>字段</th><th>首行值</th></tr></thead>
            <tbody>${fieldRows(x)}</tbody></table></div></details>
      </article>`;
    };
    const paint = () => {
      const hits = filtered();
      const pages = Math.max(1, Math.ceil(hits.length / perPage));
      page = Math.min(page, pages);
      count().textContent = `${fmt(hits.length)} / ${fmt(D.tables.length)} 张表`;
      list().innerHTML = hits.slice((page - 1) * perPage, page * perPage)
          .map(tableCard).join('') || '<p class="muted">没有匹配的表。</p>';
      updatePager('enhance-pager', page, pages, hits.length, perPage);
    };
    root.innerHTML = `<div class="world-sticky-head">` + intro('CLIENT RULES', '强化与随机',
        '探查本地客户端配置表中与「装备强化、数值随机」相关的字段与规则：哪些是确定性成长、哪些按区间 / 步长 / 权重抽取，以及配置表里查不到的部分。')
      + `<div class="content-card world-toolbar">
          <label class="tool-field"><span>搜索字段 / 表名</span><input type="search" id="enhance-query" placeholder="例如：weight / 词条 / 精炼 / min"></label>
          <label class="tool-field"><span>表</span><select id="enhance-table"><option value="">全部表</option>
            ${D.tables.map(x => `<option value="${esc(x.table)}">${esc(x.label)}</option>`).join('')}</select></label>
          <span class="small-text muted" id="enhance-count"></span></div>
        <section class="content-card enhance-summary">
          <div class="enh-summary-head"><h2>探查结论</h2>
            <p>下面 ${fmt(D.rules.length)} 条只依据本地客户端配置表里能直接读到的字段与数值。</p></div>
          <ol class="enh-rules">${D.rules.map((r, i) => `<li><span class="enh-rule-num">${i + 1}</span>
            <div>${esc(r).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')}</div></li>`).join('')}</ol>
          <p class="enh-source">来源：${esc(D.source)}。配置表给出区间、步长、权重与上限；伪随机种子、分布与保底规则在编译代码中，未作反推。</p>
        </section></div>
        <div id="enhance-list"></div>
        <nav class="world-pager" id="enhance-pager" aria-label="翻页"></nav>`;
    paint();
    let composing = false;
    const eq = root.querySelector('#enhance-query');
    eq.addEventListener('compositionstart', () => { composing = true; });
    eq.addEventListener('compositionend', e => {
      composing = false; query = e.target.value.trim().toLowerCase(); page = 1; paint();
    });
    eq.addEventListener('input', e => {
      if (composing || e.isComposing) return;
      query = e.target.value.trim().toLowerCase(); page = 1; paint();
    });
    root.querySelector('#enhance-table').addEventListener('change', e => {
      openTable = e.target.value; page = 1; paint();
    });
    bindPager(root, 'enhance-pager', value => {
      const pages = Math.max(1, Math.ceil(filtered().length / perPage));
      page = pageAction(value, page, pages); paint();
    }, size => { perPage = size; page = 1; paint(); });
  }

  window.WikiWorld = {renderMaps, renderAI, renderCode, renderEnhance};

})();
