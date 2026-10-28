/* Character growth trees and original, locally archived skill range diagrams. */
'use strict';
window.WikiCharacter = (() => {
  let cleanup = () => {};
  const rangeCache = new Map();
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const ranks = [['一',1],['三',3],['五',5],['七',7],['九',9],['十一',11]];
  function galleryMarkup(page, selected = 'base') {
    const pictures = Array.isArray(page.portraits) ? page.portraits : page.image ? [{key:'base',label:'初始立绘',src:page.image}] : [];
    const current = pictures.find(p=>p.key===selected) || pictures[0];
    if (!current) return '<div class="portrait-unavailable">原站暂未收录此角色立绘</div>';
    return `<div class="portrait-gallery-label"><span>CHARACTER ART</span><span>${esc(current.label)}</span></div><a class="portrait-stage" href="${esc(current.src)}" data-lightbox="true" aria-label="放大${esc(page.name)}${esc(current.label)}"><img src="${esc(current.src)}" alt="${esc(page.name)} · ${esc(current.label)}" decoding="async"><span class="portrait-zoom">＋ 查看大图</span></a><div class="portrait-variants" role="group" aria-label="选择角色立绘">${pictures.map(p=>`<button type="button" data-portrait="${esc(p.key)}" class="${current.key===p.key?'active':''}" aria-pressed="${current.key===p.key}">${esc(p.label)}</button>`).join('')}</div>`;
  }
  function traitMarkup(doc, mode, star, buttons) {
    const data = doc.starComparison;
    const prefix = data?.prefix || ['个性描述','天赋描述','特性描述'].find(p=>[1,2,3,4,5].some(n=>doc.fields[p+n]));
    if (!prefix) return `<div class="ability-description rich-text">${doc.html}</div>`;
    const compare = mode!=='single' && data;
    const controls = `<div class="trait-view-switch" role="group" aria-label="个性展示方式"><button type="button" data-trait-mode="compare" aria-pressed="${!!compare}" ${data?'':'disabled'}>五星对照</button><button type="button" data-trait-mode="single" aria-pressed="${!compare}">单星全文</button></div>`;
    if (!compare) return `${controls}${buttons}<div class="ability-description trait-single rich-text">${doc.fields[prefix+star]||'原站暂未收录此星级的效果。'}</div>`;
    return `${controls}<section class="trait-common"><div class="trait-section-heading"><span>公共效果</span><small>各星级均生效</small></div><div class="rich-text">${data.common||'<p class="trait-common-empty">此个性没有五个星级完全相同的完整段落，全部效果列于下方。</p>'}</div></section><div class="trait-legend"><span class="change-swatch" aria-hidden="true"></span><p>公共效果与对应星级文本共同构成完整个性。底色与下划线标出变化；1 星标出成长项，后续标出相较上一已收录星级的调整。</p></div><div class="trait-levels">${data.levels.map(level=>`<section class="trait-level ${level.available?'':'is-unavailable'}" data-trait-star="${level.star}"><div class="trait-star-label"><strong>${level.star}<span> 星</span></strong><span class="trait-star-dots" aria-hidden="true">${'★'.repeat(level.star)}${'☆'.repeat(5-level.star)}</span><small>${!level.available?'未收录':!level.previous?'初始效果':level.changed?'较 '+level.previous+' 星调整':'与 '+level.previous+' 星相同'}</small></div><div class="trait-level-effect rich-text">${level.available?level.html||'<p class="trait-common-empty">同公共效果，无额外变化。</p>':'<p class="trait-common-empty">原站暂未收录此星级的效果。</p>'}${level.removed.length?`<div class="trait-removed"><span>较 ${level.previous} 星移除</span>${level.removed.map(t=>`<del>${esc(t)}</del>`).join('；')}</div>`:''}</div></section>`).join('')}</div>`;
  }
  function rangeImage(doc) {
    if (!rangeCache.has(doc.id)) {
      const original = new DOMParser().parseFromString(doc.html || '', 'text/html');
      const image = [...original.querySelectorAll('img')].find(i => /^技能范围[ _]/.test(i.alt) && /^(?:assets\/(?:wiki|updates)\/|blob:)/.test(i.getAttribute('src') || ''));
      rangeCache.set(doc.id, image ? {src:image.getAttribute('src'), alt:image.alt.replace(/\.(png|jpg|webp)$/i, '')} : null);
    }
    return rangeCache.get(doc.id);
  }
  function rangeFigure(doc) {
    const image = rangeImage(doc);
    if (!image) return '';
    return `<figure class="skill-range"><div class="range-heading"><span>技能范围</span><small>点击放大</small></div><a class="range-map" href="${esc(image.src)}" data-lightbox="true" aria-label="放大${esc(image.alt)}"><img src="${esc(image.src)}" alt="${esc(image.alt)}" width="180" height="180"></a><figcaption>原站范围示意</figcaption></figure>`;
  }
  function kind(doc) {
    const r = doc?.rawFields || {}, text = r['技能描述'] || '';
    const label = text.match(/^[（(]([^）)]+)[）)]/)?.[1] || r['技能类别'] || '技能';
    const tone = /物理|普攻/.test(label) ? 'physical' : /魔法/.test(label) ? 'magic' : /治疗|支援/.test(label) ? 'support' : /反应/.test(label) ? 'reaction' : /被动|光环/.test(label) ? 'passive' : 'special';
    return {label, tone};
  }
  function skillFacts(doc) {
    const f = doc.fields || {};
    return `<div class="skill-facts">${[['技能消耗','消耗'],['技能冷却','冷却'],['技能射程','射程'],['技能范围','范围']].filter(([key])=>f[key]).map(([key,label])=>`<div><span>${label}</span><strong>${f[key]==='/'?'—':f[key]}</strong></div>`).join('')}</div>`;
  }
  function mountTree(root, fields, h) {
    cleanup();
    let disposed = false, selected = '', docs = new Map(), failed = new Set();
    const layers = [{rank:0, label:'初始', names:[fields['初始普攻'], fields['初始技能']]}];
    for (const [word, rank] of ranks) {
      const names = [fields[word+'阶技能左'], fields[word+'阶技能右']];
      if (names.some(Boolean)) layers.push({rank, label:rank+' 阶', names});
    }
    layers.sort((a,b)=>b.rank-a.rank);
    const nodes = [];
    for (const layer of layers) layer.nodes = layer.names.map((name, side) => {
      let page = name && (h.find('技能图鉴库/'+name) || h.find('技能/'+name) || h.find('技能图鉴/'+name));
      if (page) page = h.resolve(page);
      const node = {key:layer.rank+'-'+side, name, side, rank:layer.rank, page};
      nodes.push(node); return node;
    });
    const available = nodes.filter(n=>n.name);
    if (!available.length) {
      root.innerHTML = '<div class="growth-empty">此角色的原站档案尚未收录技能分支，可查看完整原文中的补充资料。</div>';
      return;
    }
    selected = available[0].key;
    const media = window.matchMedia('(min-width: 1280px)');
    const inspector = document.createElement('aside');
    inspector.className = 'skill-inspector';
    inspector.setAttribute('aria-label', '选中技能详情');
    function nodeMarkup(n) {
      if (!n.name) return `<div class="skill-node skill-node-missing node-${n.side}"><span>此分支未收录</span></div>`;
      const doc = docs.get(n.page?.id), r = doc?.rawFields || {}, type = kind(doc);
      const meta = [['技能消耗','消耗'],['技能冷却','冷却']].filter(([k])=>r[k] && r[k]!=='/').map(([k,label])=>`<span>${label} <b>${esc(r[k])}</b></span>`).join('');
      return `<button type="button" class="skill-node node-${n.side}${selected===n.key?' is-active':''}" data-skill-key="${n.key}" aria-pressed="${selected===n.key}" aria-label="查看${n.rank?n.rank+'阶':'初始'}技能：${esc(n.name)}"><span class="skill-node-top">${n.page?.image?`<img src="${esc(n.page.image)}" alt="" width="42" height="42">`:h.icon('spark',32)}<span><span class="skill-node-name">${esc(n.name)}</span><span class="skill-kind kind-${type.tone}">${doc?esc(type.label):'技能资料'}</span></span></span><span class="skill-node-meta">${meta || '<span>'+esc(r['技能类别']||'点选查看效果')+'</span>'}<span class="node-detail-arrow" aria-hidden="true">↗</span></span></button>`;
    }
    function paint() {
      const focused = root.contains(document.activeElement) ? document.activeElement.dataset.skillKey : '';
      root.innerHTML = `<div class="growth-heading"><div><span class="eyebrow">SKILL PATH</span><h2>技能与成长</h2><p>由下向上成长，11 阶位于树冠；点选技能查看详情。</p></div><span class="growth-count">${available.length} 项技能</span></div><div class="growth-layout"><div class="growth-tree skill-tree is-reversed"><div class="growth-tree-label"><span>左侧技能</span><span>成长阶位</span><span>右侧技能</span></div><div class="growth-rows">${layers.map(layer=>{
        const branch = layer.rank && layer.rank!==9;
        return `<section class="growth-tier skill-tier ${branch?'is-branch':layer.rank===9?'is-basic':'is-initial'}" data-rank="${layer.rank}"><h3 class="growth-rank" aria-label="${layer.label}${layer.rank===9?'普攻进阶':''}">${layer.rank?`<strong>${layer.rank}</strong><span>阶</span>`:'<span>初始</span>'}</h3>${branch?layer.nodes.map(nodeMarkup).join(''):`<div class="growth-choice-pair">${layer.rank===9?'<div class="basic-label">普攻进阶</div>':''}${layer.nodes.map(nodeMarkup).join('')}</div>`}</section>`;
      }).join('')}</div><p class="growth-footnote">连线表示成长阶位；左右技能按原站位置排列。点选卡片查看效果。</p></div><div class="growth-inspector-host"></div></div>`;
      updateSelection();
      if (focused) root.querySelector(`[data-skill-key="${focused}"]`)?.focus({preventScroll:true});
    }
    function relocate() {
      if (disposed || !root.isConnected) return;
      const target = media.matches ? root.querySelector('.growth-inspector-host') : root.querySelector(`[data-skill-key="${selected}"]`)?.closest('.growth-tier');
      if (target && inspector.parentNode!==target) target.append(inspector);
    }
    function updateSelection() {
      const node = nodes.find(n=>n.key===selected), doc = docs.get(node.page?.id);
      for (const button of root.querySelectorAll('[data-skill-key]')) {
        const active = button.dataset.skillKey===selected;
        button.classList.toggle('is-active',active); button.setAttribute('aria-pressed',String(active));
      }
      const type = kind(doc);
      const fullLink = node.page ? '#/page/'+node.page.id : '#/search?q='+encodeURIComponent(node.name);
      inspector.innerHTML = `<div class="inspector-label"><span>${node.rank?node.rank+' 阶 · '+(node.rank===9?'普攻进阶':node.side?'右侧分支':'左侧分支'):'初始 · '+(node.side?'职业技能':'普攻')}</span><span class="inspector-dot"></span></div><div class="inspector-title">${node.page?.image?`<img src="${esc(node.page.image)}" alt="" width="52" height="52">`:''}<div><h3>${esc(node.name)}</h3>${doc?`<span class="skill-kind kind-${type.tone}">${esc(type.label)}</span>`:''}</div></div><div class="skill-inspector-content" aria-live="polite" aria-busy="${!!node.page&&!doc&&!failed.has(node.page.id)}">${doc?`${skillFacts(doc)}<div class="skill-effect rich-text">${doc.fields['技能描述']||'<p>原站未收录技能描述。</p>'}</div>${rangeFigure(doc)}<div class="skill-terrain">${['攻击方式','射程高低','范围高低'].filter(k=>doc.rawFields[k] && doc.rawFields[k]!=='/').map(k=>`<span><small>${k==='射程高低'?'射程高低差':k==='范围高低'?'范围高低差':k}</small>${esc(doc.rawFields[k])}</span>`).join('')}</div>`:!node.page?'<p class="skill-loading">此技能暂无独立档案，可以搜索关联资料。</p>':failed.has(node.page.id)?'<p class="skill-loading">本地技能资料暂未加载成功。</p><button class="text-link" data-skill-retry>重新加载</button>':'<p class="skill-loading">正在读取本地技能资料…</p>'}</div><a class="skill-full-link" href="${fullLink}">打开完整技能档案 ${h.icon('arrow',15)}</a>`;
      relocate();
    }
    async function load() {
      const ids = [...new Set(available.map(n=>n.page?.id).filter(Boolean))];
      const results = await Promise.allSettled(ids.map(id=>h.loadPage(id)));
      if (disposed || !root.isConnected) return;
      results.forEach((result,i)=>{
        if (result.status==='fulfilled') {docs.set(ids[i],result.value);failed.delete(ids[i]);}
        else failed.add(ids[i]);
      });
      paint();
      root.dataset.ready = 'true';
    }
    const click = e => {
      const button = e.target.closest('[data-skill-key]');
      if (button) {selected=button.dataset.skillKey;updateSelection();}
      if (e.target.closest('[data-skill-retry]')) {failed.clear();updateSelection();load();}
    };
    root.addEventListener('click',click);
    media.addEventListener('change',relocate);
    cleanup = () => {disposed=true;root.removeEventListener('click',click);media.removeEventListener('change',relocate);};
    paint(); load();
  }
  return {galleryMarkup, traitMarkup, rangeFigure, mountTree, unmount:()=>{cleanup();cleanup=()=>{};}};
})();
