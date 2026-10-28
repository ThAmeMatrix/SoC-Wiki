/* Portable local UI. Network access is opt-in through the update panel. */
'use strict';
(async () => {
  await window.WikiUpdates?.ready;
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt = n => Number(n || 0).toLocaleString('zh-CN');
  const paths = {
    home:'M3 10 12 3l9 7M5 9v12h5v-7h4v7h5V9',
    users:'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M16 3a4 4 0 0 1 0 8M22 21v-2a4 4 0 0 0-3-3.87M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0',
    sword:'m14 3 7 0 0 7-12 12-7-7L14 3Zm-8 14-3 4m3-9 6 6M14 10l5-5',
    spark:'m12 3 2.2 6.8L21 12l-6.8 2.2L12 21l-2.2-6.8L3 12l6.8-2.2L12 3ZM20 2v4M18 4h4',
    shield:'M12 3 3 7v5c0 5 9 10 9 10s9-5 9-10V7l-9-4Zm-4 9 3 3 5-6',
    monster:'M5 6 3 2l7 4h4l7-4-2 4 2 6-5 9H8l-5-9 2-6Zm2 5 3 2m7-2-3 2m-4 4h4',
    tree:'M12 21V9M12 13c-6-1-9-5-9-9 6-1 10 3 9 9Zm0 4c6-1 9-5 9-9-6-1-10 3-9 9ZM7 22h10',
    book:'M12 7C8 3 3 4 2 4v15s6-1 10 3c4-4 10-3 10-3V4s-6-1-10 3Zm0 0v15',
    news:'M4 3h14v18H4V3Zm14 5h4v11a2 2 0 0 1-4 0M7 7h8M7 11h8M7 15h3M12 15h3M7 18h8',
    bookmark:'M5 3h14v19l-7-5-7 5V3Z',
    clock:'M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0ZM12 6v6l4 2',
    archive:'M3 4h18v4H3V4Zm2 4v13h14V8M9 12h6',
    search:'m21 21-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
    sun:'M12 3V1m0 22v-2M3 12H1m22 0h-2M4 4l2 2m12 12 2 2M4 20l2-2M18 6l2-2M17 12a5 5 0 1 1-10 0 5 5 0 0 1 10 0',
    moon:'M21 13A9 9 0 0 1 11 3 9 9 0 1 0 21 13Z',
    arrow:'M4 12h16m-6-6 6 6-6 6',
    back:'M20 12H4m6-6-6 6 6 6',
    chevron:'m9 5 7 7-7 7',
    check:'m5 12 4 4L20 5',
    compare:'M3 3v18h18M7 17V9m5 8V4m5 13v-6',
    grid:'M3 3h7v7H3V3Zm11 0h7v7h-7V3ZM3 14h7v7H3v-7Zm11 0h7v7h-7v-7Z',
    list:'M8 5h13M8 12h13M8 19h13M3 5h1M3 12h1M3 19h1',
    menu:'M3 6h18M3 12h18M3 18h18',
    download:'M12 3v13m-5-5 5 5 5-5M3 16v5h18v-5',
    upload:'M12 17V4m-5 5 5-5 5 5M3 16v5h18v-5',
    close:'m6 6 12 12M6 18 18 6',
    pin:'M12 22s8-8 8-14a8 8 0 1 0-16 0c0 6 8 14 8 14Zm3-14a3 3 0 1 1-6 0 3 3 0 0 1 6 0',
    feather:'M20 2c-7-1-13 4-13 11v4h4C18 17 23 8 20 2ZM3 22 16 8M7 17h7',
    info:'M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0ZM12 11v6m0-11v1',
    folder:'M3 5h7l2 3h9v13H3V5Z',
    enter:'M20 4v11H4m5-5-5 5 5 5',
    expand:'M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5',
    heart:'M20 4c-3-3-7-1-8 2-1-3-5-5-8-2-5 5 1 11 8 17 7-6 13-12 8-17Z'
  };
  const icon = (name, size = 18, cls = '') => `<svg class="${cls}" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[name] || paths.book}"/></svg>`;
  if (!window.WIKI_DATA) {
    $('#main').innerHTML = '<div class="empty-state"><h1>资料文件未能载入</h1><p>请完整解压离线包，并保持 index.html 与 data、assets 文件夹在同一目录。</p><button class="button" id="reload-app">重新加载</button></div>';
    $('#reload-app').onclick = () => location.reload(); return;
  }
  const DATA = window.WIKI_DATA, pages = DATA.pages, byId = new Map(pages.map(p => [p.id, p]));
  const types = DATA.archive.types;
  const typeIcons = {character:'users',equipment:'sword',skill:'spark',status:'shield',monster:'monster',talent:'tree',guide:'book',news:'news'};
  const routeFor = type => type === 'character' ? '#/characters' : `#/library/${type}`;
  const href = p => `#/page/${typeof p === 'object' ? p.id : p}`;
  const find = title => byId.get(DATA.titles[title]);
  const resolvePage = page => {const seen=new Set();while(DATA.redirects[page.id]&&!seen.has(page.id)){seen.add(page.id);page=byId.get(DATA.redirects[page.id])||page;}return page;};
  const linkTo = title => find(title) ? href(find(title)) : `#/search?q=${encodeURIComponent(title)}`;
  let storageOK = true;
  const read = (key, fallback) => { try {const v = JSON.parse(localStorage.getItem('socwiki.' + key));return v ?? fallback;} catch {storageOK = false;return fallback;} };
  const persist = (key, value) => { try {localStorage.setItem('socwiki.' + key, JSON.stringify(value));return true;} catch {storageOK = false;toast('浏览器未允许本地保存，可导出备份保留记录');return false;} };
  const validIds = value => Array.isArray(value) ? value.filter(id => Number.isInteger(id) && byId.has(id)) : [];
  let favorites = new Set(validIds(read('favorites', [])));
  let history = validIds(read('history', []));
  let comparison = validIds(read('comparison', [])).filter(id => byId.get(id)?.type === 'character').slice(0, 3);
  let notes = read('notes', {}); if (!notes || typeof notes !== 'object' || Array.isArray(notes)) notes = {};
  const initialTheme = read('theme', 'light');
  document.body.classList.toggle('dark', initialTheme === 'dark');
  let activeRoute = '', renderToken = 0, currentPage = null, detailTab = 'overview', statLevel = 'max', starLevel = 5, readerFont = Math.max(12,Math.min(22,Number(read('readerFont',14))||14)), toastTimer, quickTimer, quickCursor = -1;
  let catalog = {}, lastCatalogKey = '', searchType = '', searchPage = 1;
  let searchFilters={weapon:'',camps:new Set(),hitKind:''},searchReady=false,searchPageTimer;
  const searchComposing=new Set();
  let traitMode = 'compare';
  const portraitChoices = new Map();
  const pendingPages = new Map(); let searchPromise;
  const classes = ['守望者','粉碎者','突袭者','防御者','毁灭者','异士'];
  const classIcon = c => ({'守望者':'spark','粉碎者':'sword','突袭者':'feather','防御者':'shield','毁灭者':'monster','异士':'tree'}[c] || 'users');
  function toast(message) { clearTimeout(toastTimer);$('#toast').textContent = message;$('#toast').classList.add('show');toastTimer = setTimeout(() => $('#toast').classList.remove('show'), 2700); }
  function setBreadcrumb(text) { $('#breadcrumb').innerHTML = `<a href="#/">资料馆</a><span>/</span><b>${esc(text)}</b>`; }
  function nav() {
    const items = [['#/', 'home', '资料馆总览', ''], ...Object.keys(types).map(t => [routeFor(t), typeIcons[t], types[t], DATA.archive.counts[t]]), ['#/search','search','全站搜索',''],['#/tools','compare','离线工具',''],['#/archive','download','资料更新','']];
    $('#sidebar').innerHTML = `<a href="#/" class="brand"><svg class="brand-mark" viewBox="0 0 42 52" fill="none" stroke="currentColor" stroke-width="1.3" aria-hidden="true"><path d="M21 2 4 12v22l17 16 17-16V12L21 2Z"/><path d="M21 10v31M15 39h12M12 44h18M21 22C7 9 7 25 18 26M21 30c14-13 14 3 3 4M17 15l4-5 4 5"/></svg><div><div class="brand-name">铃兰档案馆</div><div class="brand-sub">SWORD OF CONVALLARIA</div></div></a><div class="edition"><span>离线 WIKI</span> 旅人的随行百科</div><div class="nav-label">探索资料库</div><nav class="nav-group">${items.map(([url,ic,label,count]) => `<a href="${url}" class="nav-item ${activeRoute === url ? 'active' : ''}" ${activeRoute === url ? 'aria-current="page"' : ''}>${icon(ic,17)}<span>${label}</span>${count ? `<span class="nav-count">${fmt(count)}</span>` : ''}</a>`).join('')}</nav><div class="nav-rule"></div><div class="nav-label">我的冒险</div><nav class="nav-group"><a href="#/favorites" class="nav-item ${activeRoute === '#/favorites' ? 'active' : ''}">${icon('bookmark',17)}我的收藏<span class="nav-count" id="favorite-count">${favorites.size || ''}</span></a><a href="#/history" class="nav-item ${activeRoute === '#/history' ? 'active' : ''}">${icon('clock',17)}最近浏览</a><a href="#/compare" class="nav-item ${activeRoute === '#/compare' ? 'active' : ''}">${icon('compare',17)}角色对比</a></nav><div class="sidebar-bottom"><a href="#/archive" class="archive-mini">${icon('archive',23)}<div><strong>${DATA.archive.complete ? '完整资料，安心离线' : '资料快照已保存在本机'}</strong><span>${DATA.archive.updatedAt?'更新于':'收录于'} ${(DATA.archive.updatedAt||DATA.archive.builtAt).slice(0,10).replaceAll('-','.')}</span></div></a><div class="sidebar-source">源自 BWIKI · 由热爱记录</div></div>`;
  }
  function intro(eyebrow, title, description, action = '') { return `<div class="page-intro"><div><div class="eyebrow">${eyebrow}</div><h1>${title}</h1><p>${description}</p></div>${action}</div>`; }
  function favoriteButton(p) { return `<button class="icon-button favorite-button ${favorites.has(p.id) ? 'is-saved' : ''}" data-favorite="${p.id}" aria-label="${favorites.has(p.id) ? '取消收藏' : '收藏'}${esc(p.name)}" aria-pressed="${favorites.has(p.id)}" title="${favorites.has(p.id) ? '取消收藏' : '加入收藏'}">${icon('bookmark',15)}</button>`; }
  function characterCard(p, i = 0, mode = 'portrait') {
    const selected = comparison.includes(p.id);
    const sprite = mode==='sprite';
    return `<article class="character-card ${sprite?'sprite-card':''}" data-character-id="${p.id}"><a href="${href(p)}" class="portrait-wrap ${['','blue','rose'][i % 3]}" aria-label="查看${esc(p.name)}"><span class="class-mark" title="${esc(p.class)}">${icon(classIcon(p.class),14)}</span>${sprite&&!p.sprite?'<span class="sprite-missing">暂无像素形象</span>':`<img src="${(sprite?p.sprite:p.image) || 'assets/brand/placeholder.svg'}" alt="${esc(p.name)}${sprite?'像素形象':'立绘'}" loading="lazy" decoding="async">`}${sprite&&p.unitNumber?`<span class="unit-number">NO. ${esc(p.unitNumber)}</span>`:''}</a>${favoriteButton(p)}<div class="character-info"><div class="rarity-line"><span class="rarity-diamond">◆</span> ${esc(p.rarity || '角色')} <span>· ${p.rarity === '传说' ? 'LEGENDARY' : p.rarity === '史诗' ? 'EPIC' : 'ARCHIVE'}</span></div><a href="${href(p)}" class="character-name">${esc(p.name)}</a><div class="character-sub">${esc(p.class || '—')} <span>·</span> ${esc(p.faction.split(/[，,、]/)[0] || '其他角色')}</div><div class="card-bottom"><button class="compare-check ${selected ? 'selected' : ''}" data-compare="${p.id}" aria-pressed="${selected}">${icon(selected ? 'check' : 'compare',12)}${selected ? '已加入对比' : '加入对比'}</button><a href="${href(p)}" aria-label="打开${esc(p.name)}">${icon('arrow',14)}</a></div></div></article>`;
  }
  function equipmentCard(p) { return `<article class="equipment-card">${favoriteButton(p)}<a href="${href(p)}"><div class="equipment-image"><img src="${p.image || 'assets/brand/placeholder.svg'}" alt="${esc(p.name)}" loading="lazy"></div><div class="rarity-line">◆ ${esc(p.rarity || '装备')} · EQUIPMENT</div><h3>${esc(p.name)}</h3><p>${esc(p.summary)}</p><div class="equipment-type"><span>${esc(p.weapon || '装备资料')}</span>${icon('arrow',14)}</div></a></article>`; }
  function entryCard(p) { return `<article class="entry-card"><a href="${href(p)}" class="entry-card-icon" tabindex="-1" aria-hidden="true">${p.image ? `<img src="${p.image}" alt="" loading="lazy">` : icon(typeIcons[p.type],23)}</a><div class="entry-content"><a href="${href(p)}"><div class="entry-type">${esc(types[p.type])}</div><h3>${esc(p.name)}</h3><p>${esc(p.summary || '点击查看完整资料与原文内容。')}</p><div class="entry-date">原站更新 ${esc(p.date || '未记录')}</div></a></div>${favoriteButton(p)}</article>`; }
  function empty(title, text, link = '#/characters', label = '探索角色图鉴', ic = 'book') { return `<div class="empty-state">${icon(ic,40)}<h2>${esc(title)}</h2><p>${esc(text)}</p><a class="button" href="${link}">${label}${icon('arrow',15)}</a></div>`; }
  function home() {
    const counts = DATA.archive.counts;
    const featured = ['歌洛莉亚','贝拉','伊南娜','麦莎'].map(n => find('角色图鉴库/' + n)).filter(Boolean);
    const guides = [['book','新手入门','从第一场冒险开始','新手攻略之开服前期流程'],['sword','战斗与伤害','理解每一次攻击的意义','伤害公式汇总'],['spark','养成与搭配','让每一份成长都有方向','精品合集'],['feather','角色秘录','寻找与你并肩的伙伴','角色秘录'],['tree','命运螺旋','书写属于你的故事','命运螺旋']];
    const date = new Date();
    return `${intro('THE TRAVELER’S COMPANION','团长，欢迎回到铃兰。','让每一次探索，都有迹可循。',`<div class="date-note"><span>你的随行资料馆</span><b>${date.toLocaleDateString('zh-CN',{month:'2-digit',day:'2-digit'}).replace('/',' / ')}</b></div>`)}<section class="hero" aria-label="铃兰之剑离线资料馆"><div class="hero-content"><div class="hero-tag">${icon('spark',13)} 为这和平的世界 · 离线珍藏</div><h2>风起铃兰，<br>与你共赴下一段旅程。</h2><p>角色、装备、技能与攻略，一座随时相伴的资料馆。</p><div class="hero-actions"><a href="#/characters" class="button light">探索角色图鉴${icon('arrow',15)}</a><a href="#/library/guide" class="hero-link">翻阅冒险指南${icon('arrow',14)}</a></div></div><span class="hero-caption">${icon('pin',12)} 伊利亚 · 旅程的起点</span></section><div class="stat-grid">${[['users',counts.character,'角色档案','#/characters'],['sword',counts.equipment,'装备收藏',routeFor('equipment')],['spark',counts.skill,'技能资料',routeFor('skill')],['book',DATA.archive.pages,'收录词条','#/archive']].map(([ic,count,label,url])=>`<a class="stat-card" href="${url}"><div class="stat-icon">${icon(ic,22)}</div><div><div class="stat-value">${fmt(count)}</div><div class="stat-label">${label}</div></div>${icon('chevron',13,'arrow')}</a>`).join('')}</div><div class="home-columns"><section><div class="section-heading"><div><h2>与你并肩的伙伴</h2><div class="section-sub">CHARACTER ARCHIVE</div></div><a href="#/characters" class="text-link">全部角色${icon('arrow',13)}</a></div><div class="character-grid">${featured.map(characterCard).join('')}</div></section><section class="home-guide"><div class="section-heading"><div><h2>冒险指南</h2><div class="section-sub">A LITTLE GUIDANCE</div></div><a href="${routeFor('guide')}" class="text-link">更多${icon('arrow',13)}</a></div><div class="guide-panel">${guides.map(([ic,title,sub,target])=>`<a class="guide-shortcut" href="${linkTo(target)}"><span class="guide-icon">${icon(ic,18)}</span><span><strong>${title}</strong><small>${sub}</small></span>${icon('chevron',13,'arrow')}</a>`).join('')}</div></section></div><div class="home-tools"><a href="#/tools/damage">${icon('compare',20)}<span><strong>伤害计算</strong><small>实时结果与方案</small></span>${icon('chevron',14)}</a><a href="#/tools/gacha">${icon('spark',20)}<span><strong>邂逅模拟</strong><small>双卡池与保底记录</small></span>${icon('chevron',14)}</a><a href="#/tools/equipment">${icon('sword',20)}<span><strong>装备属性</strong><small>满级满星原站数据</small></span>${icon('chevron',14)}</a></div><div class="home-bottom"><section class="home-note">${icon('tree',47,'note-emblem')}<div><h3>把整座资料馆，带在身边。</h3><p>无需网络，也能随时查阅。<br>收藏心仪的角色，记下灵感，让下一场冒险更从容。</p></div></section><section class="recent-panel"><div class="section-heading"><h2>最近翻阅</h2><a href="#/history" class="text-link">查看记录${icon('arrow',13)}</a></div>${history.length ? `<div class="recent-links">${history.slice(0,5).map(id=>`<a href="${href(id)}">${esc(byId.get(id).name)}</a>`).join('')}</div>` : '<p class="muted small-text">旅途的书签，从你翻开的第一份档案开始。</p>'}</section></div>`;
  }
  function filterRow(key, label, values) { return `<div class="filter-row"><span class="filter-label">${label}</span><div class="filter-chips">${['',...values].map(v=>`<button class="chip ${catalog[key] === v ? 'active' : ''}" data-filter="${key}" data-value="${esc(v)}" aria-pressed="${catalog[key] === v}">${esc(v || '全部')}</button>`).join('')}</div></div>`; }
  function catalogView(key) {
    if (lastCatalogKey !== key) {catalog={type:key,q:'',rarity:'',class:'',faction:'',weapon:'',prefix:'',page:1,sort:key==='character'?'source':'updated',descending:false,view:'grid'};lastCatalogKey=key;}
    const english={character:'THE COMPANIONS',equipment:'THE ARMORY',skill:'ARTS OF BATTLE',status:'BATTLE GLOSSARY',monster:'CREATURES OF THE WORLD',talent:'GROWTH & POTENTIAL',guide:'THE ADVENTURER’S HANDBOOK',news:'LETTERS FROM ILIA'};
    const descriptions={character:'每一位同行者，都有属于自己的故事。按职业、阵营与稀有度寻找你的伙伴。',equipment:'利刃与守护，皆为旅途所需。查阅装备效果、星级技能与产出来源。',skill:'从基础攻击到关键一击，查阅完整的技能描述与关联角色。',status:'弄清每一种状态、增益、减益与战斗术语。',monster:'了解对手的特性，为下一场战斗做好准备。',talent:'个性、天赋与极限解放，记录成长的每一种可能。',guide:'从初次启程到深入探索，翻阅社区积累的知识与经验。',news:'保存原站资讯与更新记录，按资料日期回溯旅程。'};
    const pool=pages.filter(p=>p.type===key);
    let filters='';
    if(key==='character'||key==='equipment')filters+=filterRow('rarity','稀有度',(key==='character'?['传说','史诗','精英','普通']:['传说','史诗','卓越','普通']).filter(r=>pool.some(p=>p.rarity===r)));
    if(key==='character'){
      filters+=filterRow('class','职业',classes.filter(c=>pool.some(p=>p.class===c)));
      filters+=filterRow('faction','阵营',[...new Set(pool.flatMap(p=>p.faction.split(/[，,、]/).map(s=>s.trim())).filter(Boolean))]);
    }
    if(key==='equipment')filters+=filterRow('weapon','类型',[...new Set(pool.map(p=>p.weapon).filter(Boolean))]);
    if(key==='talent')filters+=filterRow('prefix','分类',[...new Set(pool.map(p=>p.title.split('/')[0]))]);
    if(key==='skill')filters+=filterRow('class','职业',classes.slice(0,5));
    $('#main').innerHTML=`${intro(english[key]||'ARCHIVE',types[key],descriptions[key]||'',key==='character'?'<a href="#/compare" class="button secondary small">'+icon('compare',15)+'角色对比</a>':'')}${filters?`<section class="catalog-tools" aria-label="筛选资料">${filters}<button class="text-link" data-action="reset-filters">重置筛选</button></section>`:''}<div class="catalog-toolbar"><div class="catalog-result" id="catalog-count"></div><div class="toolbar-controls"><label class="input-wrap">${icon('search',15)}<input id="catalog-query" type="search" placeholder="搜索${types[key]}…" aria-label="搜索${types[key]}" value="${esc(catalog.q)}"></label><select id="catalog-sort" aria-label="排序方式">${key==='character'?'<option value="source">原站角色顺序</option>':''}<option value="updated">最近更新</option><option value="name">名称排序</option><option value="rarity">稀有度排序</option>${key==='character'?['生命','物攻','魔攻','物防','魔防','敏捷'].map(s=>`<option value="stat:${s}">${s==='敏捷'?'速度':s}排序</option>`).join(''):''}</select>${key==='character'?`<div class="view-toggle catalog-view-switch" role="group" aria-label="角色图鉴展示方式"><button data-view="grid" aria-label="像素图鉴">${icon('grid',15)}<span>像素图鉴</span></button><button data-view="list" aria-label="单位列表">${icon('list',15)}<span>单位列表</span></button></div>`:''}</div></div><div id="catalog-results"></div><div id="catalog-pagination"></div>`;
    $('#catalog-sort').value=catalog.sort;updateCatalog();
  }
  const normalize = s => String(s).toLowerCase().replace(/[·•・\s]/g,'');
  function pagination(total,page,kind,size=24){const max=Math.ceil(total/size);if(max<=1)return '';const nums=[...new Set([1,...Array.from({length:5},(_,i)=>page-2+i).filter(n=>n>=1&&n<=max),max])].sort((a,b)=>a-b);return `<nav class="pagination" aria-label="分页"><button data-${kind}-page="${page-1}" ${page===1?'disabled':''} aria-label="上一页">‹</button>${nums.map((n,i)=>`${i&&n>nums[i-1]+1?'<span class="muted">…</span>':''}<button data-${kind}-page="${n}" class="${n===page?'active':''}" ${n===page?'aria-current="page"':''}>${n}</button>`).join('')}<button data-${kind}-page="${page+1}" ${page===max?'disabled':''} aria-label="下一页">›</button><span class="pagination-info">共 ${max} 页</span></nav>`;}
  function updateCatalog(){
    const query=normalize(catalog.q);
    let matches=pages.filter(p=>p.type===catalog.type&&!p.redirect&&(!query||normalize(p.title+' '+p.aliases+' '+p.summary).includes(query))&&(!catalog.rarity||p.rarity===catalog.rarity)&&(!catalog.class||(catalog.type==='skill'?p.categories.includes(catalog.class+'技能'):p.class===catalog.class))&&(!catalog.faction||p.faction.split(/[，,、]/).map(s=>s.trim()).includes(catalog.faction))&&(!catalog.weapon||p.weapon===catalog.weapon)&&(!catalog.prefix||p.title.startsWith(catalog.prefix+'/')));
    const sourceOrder=(a,b)=>(a.sourceOrder??100000+a.id)-(b.sourceOrder??100000+b.id);
    if(catalog.type==='character')matches.sort(sourceOrder);
    if(catalog.sort==='updated')matches.sort((a,b)=>(b.date||'').localeCompare(a.date||''));
    if(catalog.sort==='name')matches.sort((a,b)=>(catalog.descending?-1:1)*a.name.localeCompare(b.name,'zh-CN'));
    if(catalog.sort==='rarity'){const rank={'传说':0,'史诗':1,'精英':2,'卓越':2,'普通':3};matches.sort((a,b)=>(rank[a.rarity]??4)-(rank[b.rarity]??4));}
    if(catalog.sort.startsWith('stat:')){const key=catalog.sort.slice(5),value=p=>/^[\d.]+$/.test(String(p.stats?.[key]??''))?Number(p.stats[key]):NaN;matches.sort((a,b)=>{const av=value(a),bv=value(b);return Number.isNaN(av)?Number.isNaN(bv)?sourceOrder(a,b):1:Number.isNaN(bv)?-1:(catalog.descending?-1:1)*(av-bv)||sourceOrder(a,b);});}
    const total=matches.length;catalog.page=Math.min(catalog.page,Math.max(1,Math.ceil(total/24)));
    $('#catalog-count').innerHTML=`找到 <b>${fmt(total)}</b> 份${types[catalog.type]} <span class="muted">· 点击档案，展开完整资料</span>`;
    matches=matches.slice((catalog.page-1)*24,catalog.page*24);
    let result='';
    if(!matches.length)result=empty('暂未找到这份档案','试试更短的关键词，或清除筛选条件。','#/search?q='+encodeURIComponent(catalog.q),'搜索全部资料','search');
    else if(catalog.type==='character'&&catalog.view==='grid')result=`<div class="character-grid catalog-grid sprite-grid">${matches.map((p,i)=>characterCard(p,i,'sprite')).join('')}</div>`;
    else if(catalog.type==='character')result=unitTable(matches);
    else if(catalog.type==='equipment')result=`<div class="equipment-grid">${matches.map(equipmentCard).join('')}</div>`;
    else result=`<div class="entry-grid">${matches.map(entryCard).join('')}</div>`;
    $('#catalog-results').innerHTML=result;$('#catalog-pagination').innerHTML=pagination(total,catalog.page,'catalog');
    $$('[data-filter]').forEach(b=>{const on=catalog[b.dataset.filter]===b.dataset.value;b.classList.toggle('active',on);b.setAttribute('aria-pressed',String(on));});
    $$('[data-view]').forEach(b=>{const active=catalog.view===b.dataset.view;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));});
  }
  function unitTable(matches){
    const stats=['生命','物攻','魔攻','物防','魔防','敏捷'];
    const heading=(key,label)=>`<th scope="col" aria-sort="${catalog.sort===key?catalog.descending?'descending':'ascending':'none'}"><button data-unit-sort="${key}">${label}<span aria-hidden="true">${catalog.sort===key?catalog.descending?'↓':'↑':'↕'}</span></button></th>`;
    return `<div class="unit-list-heading"><span>单位列表</span><small>属性为满级满星 · 点击数值表头排序 · 横向滚动查看全部</small></div><div class="catalog-table-wrap unit-table-wrap" tabindex="0" role="region" aria-label="角色单位列表，可横向滚动"><table class="data-table unit-table"><thead><tr>${heading('name','角色')}<th scope="col">像素形象</th><th scope="col">稀有度</th><th scope="col">职业</th><th scope="col">阵营</th><th scope="col">武器</th>${stats.map(s=>heading('stat:'+s,s==='敏捷'?'速度':s)).join('')}<th scope="col">操作</th></tr></thead><tbody>${matches.map(p=>`<tr data-character-id="${p.id}"><td><a class="unit-identity" href="${href(p)}"><img class="unit-avatar" src="${esc(p.avatar||p.sprite||'assets/brand/placeholder.svg')}" alt="" loading="lazy"><span><strong>${esc(p.name)}</strong>${p.unitNumber?`<small>NO. ${esc(p.unitNumber)}</small>`:''}</span></a></td><td class="unit-sprite">${p.sprite?`<a href="${href(p)}" aria-label="查看${esc(p.name)}"><img src="${esc(p.sprite)}" alt="${esc(p.name)}像素形象" loading="lazy"></a>`:'—'}</td><td><span class="unit-rarity">${esc(p.rarity||'—')}</span></td><td><span class="unit-profession">${p.professionIcon?`<img src="${esc(p.professionIcon)}" alt="" loading="lazy">`:''}${esc(p.class||'—')}</span></td><td><div class="unit-factions">${p.faction.split(/[，,、]/).filter(Boolean).map(f=>`<span>${esc(f)}</span>`).join('')||'—'}</div></td><td>${esc(p.weapon||'—')}</td>${stats.map(s=>`<td class="unit-stat">${esc(p.stats?.[s]||'—')}</td>`).join('')}<td><div class="unit-actions">${favoriteButton(p)}<button class="icon-button" data-compare="${p.id}" aria-label="对比${esc(p.name)}" aria-pressed="${comparison.includes(p.id)}">${icon(comparison.includes(p.id)?'check':'compare',16)}</button></div></td></tr>`).join('')}</tbody></table></div>`;
  }
  function loadScript(src){return new Promise((resolve,reject)=>{const s=document.createElement('script');s.src=src;s.onload=()=>{s.remove();resolve();};s.onerror=()=>{s.remove();reject(new Error('本地文件载入失败：'+src));};document.head.appendChild(s);});}
  function loadPage(id){if(window.WIKI_PAGES[id])return Promise.resolve(window.WIKI_PAGES[id]);if(!pendingPages.has(id))pendingPages.set(id,loadScript(`data/pages/${id}.js`).then(()=>{if(!window.WIKI_PAGES[id])throw new Error('资料文件内容不完整');window.WIKI_PAGES[id]=window.WikiUpdates?.resolve(window.WIKI_PAGES[id])||window.WIKI_PAGES[id];return window.WIKI_PAGES[id];}).catch(e=>{pendingPages.delete(id);throw e;}));return pendingPages.get(id);}
  function loadSearch(){if(!searchPromise)searchPromise=Promise.all([window.WIKI_SEARCH?Promise.resolve():loadScript('data/search.js').then(()=>window.WikiUpdates?.patchSearch()),window.WikiSearch.prepare(pages)]).catch(e=>{searchPromise=null;throw e;});return searchPromise;}
  function saveHistory(id){history=[id,...history.filter(x=>x!==id)].slice(0,50);persist('history',history);}
  function sourceFooter(doc){return `<div class="source-footer"><span>原站更新 ${esc(doc.date||'未记录')} · 版本 ${doc.revision} · 来源：BWIKI 铃兰小站</span><a href="${esc(doc.source)}" target="_blank" rel="noopener noreferrer">查看原站 ↗（需联网）</a></div>`;}
  function notesBox(id){return `<section class="content-card notes-box"><label for="page-notes">${icon('feather',16)}团长笔记</label><textarea id="page-notes" data-note="${id}" placeholder="记下配队思路、养成计划，或下一次冒险的灵感…" maxlength="30000">${esc(typeof notes[id]==='string'?notes[id]:'')}</textarea><small id="note-status">${storageOK?'自动保存在当前浏览器，可在资料馆设置导出备份。':'当前浏览器限制本地保存，请及时导出备份。'}</small></section>`;}
  function actions(p){return `<div class="detail-actions">${p.type==='character'?`<button class="button secondary small" data-compare="${p.id}">${icon('compare',16)}<span>${comparison.includes(p.id)?'移出对比':'加入对比'}</span></button>`:''}${favoriteButton(p)}</div>`;}
  function detailHeading(p){return `<a class="page-back" href="${routeFor(p.type)}">${icon('back',14)}返回${types[p.type]}</a><div class="detail-heading"><div><div class="eyebrow">${p.type==='character'?'CHARACTER DOSSIER':p.type==='equipment'?'EQUIPMENT ARCHIVE':'FROM THE ARCHIVE'}</div><h1>${esc(p.name)}</h1></div>${actions(p)}</div>`;}
  function starButtons(){return `<div class="star-selector" role="group" aria-label="选择星级">${[1,2,3,4,5].map(n=>`<button data-star="${n}" class="${starLevel===n?'active':''}" aria-pressed="${starLevel===n}">${n} 星</button>`).join('')}</div>`;}
  function characterDetail(p,doc){
    const f=doc.rawFields;
    const rawName=f['显示名称']||p.name;
    const englishName=rawName.replace(p.name,'').trim();
    const stats=['生命','物攻','物防','魔攻','魔防','敏捷'];
    const profile=`<section class="character-profile"><div class="profile-art profile-gallery">${window.WikiCharacter.galleryMarkup(p,portraitChoices.get(p.id))}</div><div class="profile-info"><div class="rarity-line">◆ ${esc(p.rarity||'角色档案')} · ${p.rarity==='传说'?'LEGENDARY':'COMPANION'}</div><h2>${esc(p.name)}</h2><div class="profile-name-en">${esc(englishName||'SWORD OF CONVALLARIA')}</div><div class="badges"><span class="badge gold">${icon(classIcon(p.class),12)} ${esc(p.class||'其他角色')}</span>${p.faction.split(/[，,、]/).filter(Boolean).map(x=>`<span class="badge">${esc(x)}</span>`).join('')}</div><div class="profile-stats-heading"><span>角色基础属性</span><div class="segmented"><button data-level="base" class="${statLevel==='base'?'active':''}">初始</button><button data-level="max" class="${statLevel==='max'?'active':''}">满级满星</button></div></div><div class="profile-stats">${stats.map(s=>`<div class="profile-stat"><div class="stat-name">${s==='敏捷'?'速度':s}</div><div class="stat-number">${esc(f[(statLevel==='max'?'满级满星':'初始')+s]||'—')}</div></div>`).join('')}</div><div class="profile-meta"><span>移动 <b>${esc(f['移动']||'—')}</b></span><span>跳跃 <b>${esc(f['跳跃高度']||'—')}</b></span><span>武器 <b>${esc(p.weapon||'—')}</b></span><span>特职 <b>${esc(f['特职']||'—')}</b></span></div></div></section>`;
    $('#main').innerHTML=`${detailHeading(p)}${profile}<nav class="detail-tabs" aria-label="角色详情">${[['overview','档案总览'],['skills','技能与成长'],['story','角色故事'],['source','完整原文']].map(([id,t])=>`<button data-detail-tab="${id}" class="${detailTab===id?'active':''}" aria-pressed="${detailTab===id}">${t}</button>`).join('')}</nav><div id="detail-body"></div>${sourceFooter(doc)}`;
    characterPanel(p,doc);
  }
  function skillMini(name,prefix='技能图鉴库'){
    if(!name)return '<div class="skill-mini"><span class="skill-missing">原站未提供该技能</span></div>';
    const p=find(prefix+'/'+name)||find('技能图鉴库/'+name)||find('技能/'+name)||find('极限解放/'+name);
    return `<a class="skill-mini" href="${p?href(p):'#/search?q='+encodeURIComponent(name)}">${p?.image?`<img src="${p.image}" alt="" loading="lazy">`:icon('spark',29)}<div><h3>${esc(name)}</h3><p>${esc(p?.summary||'查看关联资料')}</p></div></a>`;
  }
  function characterPanel(p,doc){
    window.WikiCharacter.unmount();
    const f=doc.fields,r=doc.rawFields;
    if(detailTab==='overview'){
      $('#detail-body').innerHTML=`<div class="detail-panels"><div><section class="content-card"><h2>个性 · ${esc(r['个性']||'角色个性')}</h2><div id="personality-content" class="rich-text">${r['个性']?`<a href="${linkTo('个性/'+r['个性'])}">查看个性详情 ${icon('arrow',14)}</a>`:'原站暂未收录。'}</div></section><section class="content-card"><h2>配置与养成建议</h2><div class="rich-text">${f['配置推荐']||'原站暂未提供配置建议。'}</div>${f['角色攻略']?`<h3 style="margin-top:23px">技能加点</h3><div class="rich-text">${f['角色攻略']}</div>`:''}<p class="muted small-text" style="margin-top:17px">保留原站建议，请结合版本与实际阵容参考。</p></section></div><aside>${notesBox(p.id)}<section class="content-card"><h3>档案索引</h3><div class="tag-list"><a href="#/library/equipment">装备图鉴</a><a href="${linkTo('角色秘录')}">角色秘录</a><a href="${linkTo('天赋系统')}">天赋系统</a></div></section></aside></div>`;
      $('#personality-content').closest('.content-card').classList.add('personality-card');
      const personality=find('个性/'+r['个性'])||find('天赋/'+r['个性']);
      if(personality){const token=renderToken;loadPage(personality.id).then(d=>{if(token!==renderToken||detailTab!=='overview'||currentPage?.id!==p.id)return;const el=$('#personality-content');if(el)el.innerHTML=`${window.WikiCharacter.traitMarkup(d,traitMode,starLevel,starButtons())}<a class="text-link" style="margin-top:20px" href="${href(personality)}">完整个性资料${icon('arrow',14)}</a>`;}).catch(()=>{});}
    }else if(detailTab==='skills'){
      $('#detail-body').innerHTML=`<section class="growth-explorer" aria-label="角色技能成长树"></section>${r['极限解放']?`<section class="content-card" style="margin-top:20px"><h2>极限解放</h2><div class="entry-grid">${r['极限解放'].split(/[，,、]/).map(s=>skillMini(s.trim(),'极限解放')).join('')}</div></section>`:''}${r['门内可习得技能']?`<section class="content-card" style="margin-top:20px"><h2>门内可额外习得技能</h2><div class="tag-list">${r['门内可习得技能'].split(/[，,、]/).map(s=>`<a href="${linkTo('技能图鉴库/'+s.trim())}">${esc(s.trim())}</a>`).join('')}</div></section>`:''}`;
      window.WikiCharacter.mountTree($('.growth-explorer'),r,{find,resolve:resolvePage,loadPage,icon});
    }else if(detailTab==='story'){
      $('#detail-body').innerHTML=`<section class="content-card"><h2>角色故事</h2><div class="prose-section rich-text">${f['角色生平']||'原站暂未收录角色生平。'}</div><dl class="fact-grid" style="margin-top:25px">${['角色绰号','性别','中文CV','日文CV'].map(k=>`<div><dt>${k}</dt><dd>${f[k]||'—'}</dd></div>`).join('')}</dl>${f['配音展示']?`<h3>配音展示</h3><div class="rich-text">${f['配音展示']}</div>`:''}</section>`;
    }else $('#detail-body').innerHTML=`<div class="source-notice">${icon('info',16)}包含原站立绘、像素模型、表格和补充内容。点击图片可放大；外部视频链接需要联网。</div><section class="content-card wiki-content">${doc.html}</section>`;
  }
  function equipmentReference(p){
    const row=window.WIKI_TOOLS_DATA?.equipment?.rows.find(r=>r.weapon===p.weapon&&r.rarity===p.rarity);
    if(!row)return '';
    return `<section class="content-card"><h2>满级满星基础属性</h2>${row.recorded?`<div class="reference-stats compact">${Object.entries(row.stats).map(([k,v])=>`<div><span>${k}</span><strong>${fmt(v)}</strong></div>`).join('')}</div>`:'<p class="muted small-text">原站此类型、稀有度的属性表全为 0，暂不展示推算值。</p>'}<p class="muted small-text">来自同类型、同稀有度装备属性表，不包含装备技能加成。</p><a class="text-link" href="#/tools/equipment">查看全部装备属性 ${icon('arrow',14)}</a></section>`;
  }
  function equipmentDetail(p,doc){const f=doc.fields;const n=['','一','二','三','四','五'][starLevel];$('#main').innerHTML=`${detailHeading(p)}<section class="equipment-profile"><img src="${p.image||'assets/brand/placeholder.svg'}" alt="${esc(p.name)}"><div><div class="rarity-line">◆ ${esc(p.rarity)}</div><h2>${esc(p.name)}</h2><div class="badges"><span class="badge">${esc(p.weapon)}</span></div><p>获取来源：${f['产出来源']||'原站未注明'}</p></div></section><div class="detail-panels"><div>${equipmentReference(p)}<section class="content-card"><h2>装备技能</h2>${starButtons()}<div class="ability-description rich-text">${f[n+'星技能']||'原站暂未收录此星级的效果。'}</div></section><section class="content-card"><h2>装备故事</h2><div class="rich-text">${f['装备描述']||'原站暂未收录。'}</div>${f['装备评价']?'<h3 style="margin-top:20px">装备评价</h3><div class="rich-text">'+f['装备评价']+'</div>':''}</section><details class="content-card"><summary>查看完整原文与补充资料</summary><div class="wiki-content">${doc.html}</div></details></div><aside><section class="content-card"><h2>适合角色</h2><div class="tag-list">${doc.rawFields['适合角色']?doc.rawFields['适合角色'].split(/[，,、]/).map(n=>`<a href="${linkTo('角色图鉴库/'+n.trim())}">${esc(n.trim())}</a>`).join(''):'<span class="muted small-text">原站暂未提供推荐。</span>'}</div></section>${notesBox(p.id)}</aside></div>${sourceFooter(doc)}`;}
  function genericDetail(p,doc){
    const f=doc.fields;let custom='';
    const abilityTitle=label=>`<div class="ability-title">${p.image?`<img src="${p.image}" alt="" width="64" height="64">`:icon('spark',40)}<div><span class="eyebrow">${esc(p.rarity||types[p.type])}</span><h2>${label}</h2></div></div>`;
    if(f['技能描述'])custom=`<article class="content-card ability-card" id="article-content">${abilityTitle('技能效果')}<div class="ability-facts">${['技能类别','技能消耗','技能冷却','攻击方式','技能射程','射程高低','技能范围','范围高低'].filter(k=>f[k]).map(k=>`<div><span>${k.replace('技能','')}</span><strong>${f[k]}</strong></div>`).join('')}</div><div class="ability-description rich-text">${f['技能描述']}</div>${window.WikiCharacter.rangeFigure(doc)}</article>`;
    const starPrefix=['个性描述','天赋描述','特性描述'].find(pre=>[1,2,3,4,5].some(n=>f[pre+n]));
    if(starPrefix)custom=`<article class="content-card ability-card" id="article-content">${abilityTitle('效果与成长')}${window.WikiCharacter.traitMarkup(doc,traitMode,starLevel,starButtons())}</article>`;
    if([7507,7541,2292].includes(p.id))custom=`<article class="content-card" id="article-content"><h2>原站工具测试页</h2><p class="rich-text">此页是原站保留的测试或草稿内容。已完成的离线工具可从下方打开。</p><a class="button" href="${p.id===7541?'#/tools/gacha':p.id===7507?'#/tools/damage':'#/tools'}">打开${p.id===7541?'邂逅模拟器':p.id===7507?'伤害计算器':'离线工具'} ${icon('arrow',16)}</a></article>`;
    const related=(doc.related||[]).map(id=>byId.get(id)).filter(Boolean);
    const relations=related.length?`<section class="content-card"><h2>关联角色 <span class="heading-count">${related.length}</span></h2><div class="related-characters">${related.map(c=>`<a href="${href(c)}"><img src="${c.avatar||c.image||'assets/brand/placeholder.svg'}" alt="" loading="lazy"><span><strong>${esc(c.name)}</strong><small>${esc(c.class)} · ${esc(c.rarity)}</small></span>${icon('chevron',15)}</a>`).join('')}</div></section>`:'';
    const content=custom?custom+relations+`<details class="content-card source-details"><summary>完整原文与补充资料</summary><div class="wiki-content">${doc.html}</div></details>`:`<article class="content-card wiki-content" id="article-content">${doc.html}</article>`;
    const sections=doc.sections.filter(s=>+s.toclevel<=2).slice(0,25);
    $('#main').innerHTML=`${detailHeading(p)}${doc.hasOnlineMedia?`<div class="source-notice">${icon('info',16)}正文与已收录图片可离线阅读。原文中的外部视频、网页链接需要联网。</div>`:''}<div class="reader-toolbar"><span>阅读字号</span><button class="icon-button" data-action="font-down" aria-label="缩小字号">A−</button><button class="icon-button" data-action="font-up" aria-label="放大字号">A+</button><button class="button secondary small" data-action="reading">${icon('expand',13)}${document.body.classList.contains('reading')?'退出专注阅读':'专注阅读'}</button></div><div class="reader-layout"><div>${content}${sourceFooter(doc)}</div><aside class="reader-aside">${sections.length?`<nav class="toc" aria-label="本页目录"><h3>本页目录</h3>${sections.map(s=>`<a href="${href(p)}?section=${encodeURIComponent(s.anchor)}">${esc(s.line.replace(/<[^>]*>/g,''))}</a>`).join('')}</nav>`:''}${notesBox(p.id)}<div class="source-notice small-text">${icon('archive',15)}本页保存在离线资料库。数据以原站标注日期为准。</div></aside></div>`;
  }
  function prepareSourceTables(){
    for(const table of $$('.wiki-content table.sortable')){
      const rows=[...table.rows],header=rows[0];
      if(!header||header.cells.length<2||[...header.cells].some(c=>c.tagName!=='TH')||
        rows.slice(1).some(r=>r.cells.length!==header.cells.length||[...r.cells].some(c=>c.colSpan!==1||c.rowSpan!==1)))continue;
      for(const [i,cell] of [...header.cells].entries()){
        if(cell.querySelector('[data-source-sort]'))continue;
        const button=document.createElement('button');button.type='button';button.dataset.sourceSort=i;
        button.textContent=cell.textContent.trim();button.title='点击排序';cell.replaceChildren(button);cell.setAttribute('aria-sort','none');
      }
    }
  }
  function displayDetail(){if(!currentPage)return;window.WikiCharacter.unmount();const p=byId.get(currentPage.id);if(p.type==='character')characterDetail(p,currentPage);else if(p.type==='equipment')equipmentDetail(p,currentPage);else genericDetail(p,currentPage);document.documentElement.style.setProperty('--reader-font',readerFont+'px');prepareSourceTables();}
  async function detail(id,token,params){
    if(id===7523||id===8027){saveHistory(id);toolView(id===7523?'damage':'gacha');return;}
    const catalogAlias={968:'character',2701:'character',7199:'monster'}[id];
    if(catalogAlias&&!params.has('original')){activeRoute=routeFor(catalogAlias);setBreadcrumb(types[catalogAlias]);catalogView(catalogAlias);$('#main').insertAdjacentHTML('beforeend',`<div class="source-footer"><span>使用离线图鉴浏览原站收录内容。</span><a href="#/page/${id}?original=1">查看图鉴原文 →</a></div>`);return;}
    let seen=new Set();while(DATA.redirects[id]&&!seen.has(id)){seen.add(id);id=DATA.redirects[id];}
    const p=byId.get(id);if(!p){$('#main').innerHTML=empty('没有找到这份档案','此链接对应的页面未在本次快照中收录。','#/search','搜索资料馆','search');return;}
    activeRoute=routeFor(p.type);nav();setBreadcrumb(p.name);document.title=p.name+' · 铃兰档案馆';
    $('#main').innerHTML='<div class="loading" role="status">正在翻开档案…</div>';
    try{const doc=await loadPage(id);if(token!==renderToken)return;currentPage=doc;if(params.get('section')&&p.type==='character')detailTab='source';saveHistory(id);displayDetail();if(params.get('section'))setTimeout(()=>{const el=document.getElementById('source-'+id+'-'+params.get('section'));if(el){let parent=el.parentElement;while(parent){if(parent.tagName==='DETAILS')parent.open=true;parent=parent.parentElement;}el.scrollIntoView({behavior:'smooth'});}},30);}
    catch(e){if(token!==renderToken)return;$('#main').innerHTML=empty('这份档案未能打开','请确认离线包已完整解压，data/pages 文件夹没有被移动。',href(p),'重新打开档案','archive');}
  }
  function toggleFavorite(id){if(!byId.has(id))return;favorites.has(id)?favorites.delete(id):favorites.add(id);persist('favorites',[...favorites]);$$(`[data-favorite="${id}"]`).forEach(b=>{b.classList.toggle('is-saved',favorites.has(id));b.setAttribute('aria-pressed',String(favorites.has(id)));b.setAttribute('aria-label',(favorites.has(id)?'取消收藏':'收藏')+byId.get(id).name);b.title=favorites.has(id)?'取消收藏':'加入收藏';});if($('#favorite-count'))$('#favorite-count').textContent=favorites.size||'';toast(favorites.has(id)?'已放入你的收藏夹':'已移出收藏夹');if(activeRoute==='#/favorites')collection('favorites');}
  function toggleCompare(id){if(byId.get(id)?.type!=='character')return;if(comparison.includes(id))comparison=comparison.filter(x=>x!==id);else if(comparison.length<3)comparison.push(id);else{toast('最多同时对比 3 位角色，请先移除一位');return;}persist('comparison',comparison);updateDock();$$(`[data-compare="${id}"]`).forEach(b=>{const yes=comparison.includes(id);b.classList.toggle('selected',yes);b.setAttribute('aria-pressed',String(yes));if(b.classList.contains('compare-check'))b.innerHTML=icon(yes?'check':'compare',12)+(yes?'已加入对比':'加入对比');else if(b.classList.contains('button'))b.innerHTML=icon('compare',16)+'<span>'+(yes?'移出对比':'加入对比')+'</span>';else b.innerHTML=icon(yes?'check':'compare',16);});if(activeRoute==='#/compare')compareView();}
  function updateDock(){const visible=comparison.length>0&&activeRoute!=='#/compare';$('#compare-dock').innerHTML=visible?`<div class="compare-dock-inner"><span class="compare-dock-label">${icon('compare',15)} 角色对比</span>${comparison.map(id=>`<div class="compare-chip"><span>${esc(byId.get(id).name)}</span><button data-compare="${id}" aria-label="移除${esc(byId.get(id).name)}">×</button></div>`).join('')}<a href="#/compare" class="button small">开始对比 ${comparison.length}/3${icon('arrow',13)}</a></div>`:'';}
  function compareView(){
    const selected=comparison.map(id=>byId.get(id));
    $('#main').innerHTML=intro('SIDE BY SIDE','并肩，也能细细比较。','最多对比 3 位角色。属性直接来自原站「满级满星」字段，未提供的数值显示为 —。','<a href="#/characters" class="button secondary small">'+icon('users',15)+'选择角色</a>')+(selected.length?`<div class="catalog-table-wrap"><table class="data-table compare-table"><thead><tr><th>角色档案</th>${selected.map(p=>`<td><img class="compare-portrait" src="${p.image||'assets/brand/placeholder.svg'}" alt="${esc(p.name)}"><a href="${href(p)}" class="compare-name">${esc(p.name)}</a><div style="margin-top:12px"><button class="text-link" data-compare="${p.id}">移出对比</button></div></td>`).join('')}</tr></thead><tbody>${[['职业','class'],['稀有度','rarity'],['所属阵营','faction'],['武器类型','weapon']].map(([label,key])=>`<tr><th>${label}</th>${selected.map(p=>`<td>${esc(p[key]||'—')}</td>`).join('')}</tr>`).join('')}${['生命','物攻','魔攻','物防','魔防','敏捷'].map(s=>{const vals=selected.map(p=>Number(p.stats?.[s])||0);const max=Math.max(...vals);return `<tr><th>满级${s==='敏捷'?'速度':s}</th>${selected.map((p,i)=>`<td class="${max>0&&vals[i]===max&&selected.length>1?'best':''}">${esc(p.stats?.[s]||'—')}</td>`).join('')}</tr>`;}).join('')}</tbody></table></div><p class="muted small-text" style="margin-top:17px">高亮为当前对比中的最高数值。基础属性不包含装备、天赋和战斗增益。</p>`:empty('为你的阵容挑选伙伴','在角色卡片点击「加入对比」，就能并排查看属性与阵营。','#/characters','前往角色图鉴','compare'));
  }
  function collection(key){const saved=key==='favorites';const ids=saved?[...favorites].reverse():history;$('#main').innerHTML=intro(saved?'YOUR COLLECTION':'THE PAGES YOU TURNED',saved?'珍藏旅途中的每一份灵感。':'走过的路，都有记录。',saved?'收藏角色、技能和攻略，让常用的资料触手可及。':'最近 50 份浏览档案保存在当前浏览器，按最近打开排序。',`<div class="intro-actions">${saved?'<button class="button secondary small" data-action="export">'+icon('download',14)+'导出备份</button>':'<button class="button secondary small" data-action="clear-history">清空记录</button>'}</div>`)+(ids.length?`<div class="catalog-result" style="margin-bottom:20px">共 <b>${ids.length}</b> 份档案</div><div class="entry-grid">${ids.map(id=>entryCard(byId.get(id))).join('')}</div>`:empty(saved?'收藏夹，等待一段相遇。':'还没有翻阅记录。',saved?'点击档案上的书签图标，把需要的资料放在这里。':'打开任意一份档案后，就能在这里继续阅读。','#/characters','寻找你的伙伴',saved?'bookmark':'clock'));}
  function syncSearchClear(input){
    const button=document.querySelector(`[data-search-clear="${input.id}"]`);if(button)button.hidden=!input.value;
  }
  function scheduleSearch(input,immediate=false){
    const page=input.id==='search-page-query',query=input.value;syncSearchClear(input);
    clearTimeout(page?searchPageTimer:quickTimer);if(searchComposing.has(input.id))return;
    const run=()=>{if(!input.isConnected)return;if(page){if(activeRoute==='#/search'){searchPage=1;updateSearchPage(query);}}else quickResults(query);};
    if(immediate)run();else if(page)searchPageTimer=setTimeout(run,120);else quickTimer=setTimeout(run,100);
  }
  function searchResults(query,type='',filters={}){return window.WikiSearch.search(query,{type,...filters});}
  const highlighted=(text,query)=>window.WikiSearch.highlight(text,query);
  function searchAddress(query){
    const params=new URLSearchParams();if(query.trim())params.set('q',window.WikiSearch.clean(query));if(searchType)params.set('type',searchType);
    if(searchFilters.weapon)params.set('weapon',searchFilters.weapon);if(searchFilters.hitKind)params.set('hit',searchFilters.hitKind);for(const camp of searchFilters.camps)params.append('camp',camp);if(searchPage>1)params.set('page',searchPage);
    return '#/search'+(params.size?'?'+params:'');
  }
  function searchControls(){
    const available=window.WikiSearch.filters(),characterFilter=!searchType||searchType==='character';
    $('#search-filters').innerHTML=`<div class="global-search-filters"><label>武器 / 装备<select id="search-weapon"><option value="">全部类型</option>${available.weapons.map(w=>`<option${searchFilters.weapon===w?' selected':''}>${esc(w)}</option>`).join('')}</select></label><label>角色命中位置<select id="search-hit"${characterFilter?'':' disabled'}><option value="">全部位置</option>${['技能','个性','抉择分支'].map(v=>`<option${searchFilters.hitKind===v?' selected':''}>${v}</option>`).join('')}</select></label><button class="text-button" data-search-reset>清除筛选</button></div><details class="search-camp-filter"${searchFilters.camps.size?' open':''}><summary>角色阵营（多选时同时满足）${searchFilters.camps.size?' · 已选 '+searchFilters.camps.size+' 项':''}</summary><fieldset${characterFilter?'':' disabled'}><legend class="visually-hidden">筛选角色所属阵营</legend>${available.camps.map(c=>`<label><input type="checkbox" data-search-camp="${esc(c)}"${searchFilters.camps.has(c)?' checked':''}>${window.WikiSearch.badge(c)?`<img src="${esc(window.WikiSearch.badge(c))}" alt="">`:''}<span>${esc(c)}</span></label>`).join('')}</fieldset></details>`;
  }
  async function searchView(query,token){
    query=window.WikiSearch.clean(query);searchReady=false;
    $('#main').innerHTML=`${intro('FIND YOUR NEXT DISCOVERY','每个问题，都有线索。','搜索名称、别名或效果描述，找到相关角色、技能、装备及全部资料。')}<form id="search-page-form" class="search-page-form" role="search"><div class="input-wrap search-input-wrap">${icon('search',20)}<input id="search-page-query" type="search" maxlength="60" value="${esc(query)}" placeholder="例如：旗女、驱散我方减益、持续伤害…" aria-label="搜索全部资料" aria-describedby="search-live-hint" enterkeyhint="search"><button type="button" class="search-clear" data-search-clear="search-page-query" aria-label="清空搜索关键词" title="清空关键词，保留筛选条件"${query?'':' hidden'}>${icon('close',16)}<span>清空</span></button></div></form><p id="search-live-hint" class="search-live-hint">输入即搜索</p><div class="search-examples"><span>试试效果</span>${['持续伤害','控制','定身','驱散我方减益','驱散敌方增益','百分比伤害','吸血'].map(q=>`<button class="chip" data-search-example="${q}">${q}</button>`).join('')}</div><div class="search-categories">${['',...Object.keys(types)].map(t=>`<button class="chip ${searchType===t?'active':''}" data-search-type="${t}" aria-pressed="${searchType===t}">${types[t]||'全部档案'}</button>`).join('')}</div><section id="search-filters" aria-label="搜索筛选"></section><div id="search-page-results"><div class="loading">正在准备本机搜索资料…</div></div><p class="search-attribution">语义匹配参考 <a href="https://github.com/evangelpeach/llzj" target="_blank" rel="noopener noreferrer">evangelpeach/llzj</a>，使用本项目离线资料。支持同义词、效果分类、敌我方约束及完整星级数据。</p>`;
    try{await loadSearch();if(token!==renderToken)return;searchReady=true;searchControls();updateSearchPage($('#search-page-query').value);}catch{if(token===renderToken)$('#search-page-results').innerHTML=empty('搜索资料未能打开','请检查 data/search.js 和 data/advanced-search.js 是否完整。','#/search','重新加载搜索','search');}
  }
  function searchResultMarkup(result,query){
    const {p,hits}=result,S=window.WikiSearch,excerpt=hits[0]?.text||p.summary,displayHits=hits.filter(hit=>hit.type!=='全文').slice(0,4);
    return `<article class="search-result" data-search-id="${p.id}"><a class="search-identity" href="${href(p)}">${p.avatar||p.image?`<img src="${esc(p.avatar||p.image)}" alt="" loading="lazy">`:`<span class="search-type-icon">${icon(typeIcons[p.type],24)}</span>`}<div><span class="entry-type">${types[p.type]}${p.class?' · '+esc(p.class):''} · ${esc(p.date)}</span><h3>${highlighted(p.name,query)}</h3></div>${icon('arrow',18,'search-open')}</a>${p.faction?`<div class="search-faction-labels">${p.faction.split(/[，,、]/).filter(Boolean).map(c=>`<span>${S.badge(c)?`<img src="${esc(S.badge(c))}" alt="">`:''}${esc(c)}</span>`).join('')}</div>`:''}${displayHits.length?displayHits.map(hit=>`<div class="search-hit"><a href="${href(hit.id)}">${esc(hit.type)}${hit.name!==p.name?' · '+highlighted(hit.name,query):''}${hit.label?' · '+esc(hit.label):''}</a><p>${highlighted(S.snippet(hit.text,query,170),query)} ${S.groupTag(hit.text,query)}</p></div>`).join(''):`<p class="search-excerpt">${highlighted(S.snippet(excerpt,query,180),query)}</p>`}${hits.length>displayHits.length&&displayHits.length?`<a class="search-more" href="${href(p)}">查看完整资料及其他命中 →</a>`:''}</article>`;
  }
  function updateSearchPage(query){
    clearTimeout(searchPageTimer);if($('#search-page-query'))syncSearchClear($('#search-page-query'));
    if(!searchReady||!$('#search-page-results'))return;query=window.WikiSearch.clean(query);
    const filtered=searchType||searchFilters.weapon||searchFilters.hitKind||searchFilters.camps.size,matches=query||filtered?searchResults(query,searchType,searchFilters):[],total=matches.length;
    searchPage=Math.min(searchPage,Math.max(1,Math.ceil(total/25)));const results=matches.slice((searchPage-1)*25,searchPage*25);
    $('#search-page-results').innerHTML=query||filtered?`<div class="catalog-result" role="status">${query?'为「'+esc(query)+'」':''}找到 <b>${fmt(total)}</b> 份资料</div>${total?`<div class="search-result-list">${results.map(r=>searchResultMarkup(r,query)).join('')}</div>${pagination(total,searchPage,'search',25)}`:empty('暂未找到相关档案','尝试更短的效果关键词，或减少筛选条件。','#/search','清空搜索与筛选','search')}`:empty('从一个关键词开始探索。','输入「旗女」寻找角色，或输入「驱散我方减益」寻找具备对应效果的角色与技能。也可先按分类、武器或阵营筛选。','#/library/guide','翻阅冒险指南','search');
    $$('[data-search-type]').forEach(b=>{b.classList.toggle('active',b.dataset.searchType===searchType);b.setAttribute('aria-pressed',String(b.dataset.searchType===searchType));});
    window.history.replaceState(null,'',searchAddress(query));
  }
  function openSearch(){const d=$('#search-dialog');if(!d.open)d.showModal();$('#quick-search').value='';quickCursor=-1;quickResults('');$('#quick-search').focus();loadSearch().catch(()=>toast('部分搜索资料未能载入，请检查离线文件是否完整'));}
  async function quickResults(query){
    syncSearchClear($('#quick-search'));
    if(!query.trim()){quickCursor=-1;const suggestions=history.slice(0,4).map(id=>byId.get(id));const featured=suggestions.length?suggestions:['歌洛莉亚','贝拉','伊南娜'].map(n=>find('角色图鉴库/'+n)).filter(Boolean);$('#quick-results').innerHTML=`<div class="quick-label">${suggestions.length?'继续翻阅':'从这些伙伴开始'}</div>${featured.map(p=>quickResult({p,hits:[]},'')).join('')}<a href="#/search" class="quick-result" data-quick-result>${icon('search',18)}<strong>打开全站搜索与筛选</strong>${icon('arrow',16,'quick-enter')}</a><div class="quick-label">可直接搜索效果：持续伤害、驱散我方减益、百分比伤害…</div>`;return;}
    $('#quick-results').innerHTML='<div class="quick-label" role="status">正在搜索本机资料…</div>';
    try{await loadSearch();}catch{}
    if($('#quick-search').value!==query||!$('#search-dialog').open)return;
    const found=searchResults(query);quickCursor=-1;
    $('#quick-results').innerHTML=`<div class="quick-label quick-summary"><span role="status">找到 ${fmt(found.length)} 份资料</span><a href="#/search?q=${encodeURIComponent(query)}" data-quick-all>全部结果与筛选 →</a></div>${found.slice(0,7).map(result=>quickResult(result,query)).join('')}<a href="#/search?q=${encodeURIComponent(query)}" class="quick-result" data-quick-result>${icon('search',18)}<strong>查看全部搜索结果与筛选</strong>${icon('arrow',16,'quick-enter')}</a>${found.length?'':'<div class="quick-label">试试其他名称、别名或更短的关键词。</div>'}`;
  }
  function quickResult({p,hits},q){const hit=hits.find(h=>h.type!=='全文');return `<a class="quick-result" href="${href(p)}" data-quick-result data-search-id="${p.id}">${icon(typeIcons[p.type],21)}<span><strong>${highlighted(p.name,q)}</strong><small>${types[p.type]}${p.class?' · '+esc(p.class):''}${hit?' · '+esc(hit.type)+(hit.name!==p.name?' · '+esc(hit.name):''):''}</small>${hit?`<span class="quick-hit">${highlighted(window.WikiSearch.snippet(hit.text,q,56),q)}</span>`:''}</span>${icon('enter',14,'quick-enter')}</a>`;}
  function archiveView(){const a=DATA.archive;const countMax=Math.max(...Object.values(a.counts));$('#main').innerHTML=`${intro('THE ARCHIVE, PRESERVED','一座可以带走的资料馆。','关于这份离线快照、资料来源，以及只属于你的冒险记录。')}<div class="archive-hero">${icon('archive',49)}<div><h2>${a.pages===a.expectedPages?'正文已完整收录，随时离线查阅。':'本地资料快照'}</h2><p>${fmt(a.pages)} 份页面 · ${fmt(a.images)} 张图片 · 无需账号，无需网络<br>快照日期 ${a.builtAt.slice(0,10)}，内容保留原站各页面的更新时间。</p></div></div><div class="archive-grid"><section class="content-card"><h2>资料库概况</h2>${[['正文页面',fmt(a.pages)+' / '+fmt(a.expectedPages)],['本地图片',fmt(a.images)+' / '+fmt(a.expectedImages)],['图片占用空间',(a.bytes/1024/1024).toFixed(1)+' MB'],['数据来源','BWIKI · 铃兰小站'],['离线方式','直接打开本地 index.html']].map(([k,v])=>`<div class="archive-row"><span>${k}</span><strong>${v}</strong></div>`).join('')}<div class="archive-copy" style="margin-top:18px">${a.unavailableImages?.length?'<p>原站有 '+a.unavailableImages.length+' 张图片链接已失效，已在数据报告中单独记录：'+a.unavailableImages.map(x=>esc(x.name)).join('、')+'。</p>':''}正文、状态说明、技能、表格和图片已保存到本机。视频和第三方网页保留原链接，需联网打开。部分原站页面本身未填写的字段仍显示为空，不补写猜测数据。</div></section><section class="content-card"><h2>收录范围</h2>${Object.entries(a.counts).map(([k,n])=>`<a href="${routeFor(k)}" class="coverage-row"><span>${types[k]}</span><div class="coverage-bar"><i style="width:${Math.max(3,n/countMax*100)}%"></i></div><b>${fmt(n)}</b></a>`).join('')}<p class="muted small-text">覆盖原站正文命名空间；跳转页保留并自动指向对应资料。分类列表隐藏重复跳转条目。</p></section><section class="content-card"><h2>属于你的冒险记录</h2><div class="archive-copy"><p>已收藏 ${favorites.size} 份档案，记录 ${Object.keys(notes).filter(k=>notes[k]).length} 份笔记。收藏、笔记、角色对比、阅读设置及工具记录仅保存在当前浏览器中。</p><p>更换浏览器或移动资料包前，可以导出备份；导入时合并收藏、对比、浏览记录和计算方案；同名笔记、方案与邂逅进度以备份为准。兼容旧版个人备份及工具导出文件。</p></div><div class="backup-actions"><button class="button small" data-action="export">${icon('download',15)}导出个人备份</button><button class="button secondary small" data-action="import">${icon('upload',15)}导入备份</button></div></section><section class="content-card"><h2>致谢与来源</h2><div class="archive-copy"><p>游戏图片、角色设定及相关资料归原权利人所有。Wiki 内容来自 <a href="https://wiki.biligame.com/llzj" target="_blank" rel="noopener noreferrer">BWIKI 铃兰之剑 Wiki ↗</a> 与灵灵妖攻略组、社区创作者。</p><p>保留原文中的作者署名及出处。原站声明禁止将其资料用于商业用途；此离线资料馆用于个人查阅。每份档案底部均附有原站版本链接。</p><p>本快照不包含讨论页、用户页、编辑历史及外站视频文件。可在上方一键联网更新；日常阅读与语义搜索无需网络。</p></div></section></div>`;}
  function exportBackup(){
    try{
      const D=window.WIKI_TOOLS_DATA,R=window.WikiToolRules,P=window.WikiPersonal;
      const backup={format:'socwiki-personal',version:2,exportedAt:new Date().toISOString(),favorites:[...favorites],history,comparison,notes,
        preferences:{theme:document.body.classList.contains('dark')?'dark':'light',readerFont},
        tools:{damage:P.damageData({current:read('damage.current',R.defaults),presets:read('damage.presets',[])}),
          gacha:{sourceRevision:D.revision,poolId:read('gacha.pool','chuyu'),state:R.restoreSimulation(read('gacha.state',null),D)}}};
      const blob=new Blob([JSON.stringify(backup,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');
      a.href=url;a.download='铃兰档案馆-完整备份-'+new Date().toISOString().slice(0,10)+'.json';document.body.appendChild(a);a.click();a.remove();
      setTimeout(()=>URL.revokeObjectURL(url),1000);toast('完整备份已导出，含收藏、笔记、对比与工具记录');
    }catch(e){toast('备份导出失败：'+e.message);}
  }
  async function importBackup(file){
    if(!file)return;
    try{
      if(file.size>5*1024*1024)throw new Error('备份文件过大（上限 5 MB）');
      const value=window.WikiPersonal.parse(JSON.parse(await file.text()),pages,window.WIKI_TOOLS_DATA),changes={};
      if(value.favorites)changes.favorites=[...new Set([...favorites,...value.favorites])];
      if(value.history)changes.history=[...new Set([...value.history,...history])].slice(0,50);
      if(value.notes)changes.notes={...notes,...value.notes};
      if(value.comparison)changes.comparison=[...new Set([...value.comparison,...comparison])].slice(0,3);
      if(value.theme)changes.theme=value.theme;
      if(value.readerFont)changes.readerFont=value.readerFont;
      if(value.damage){changes['damage.current']=value.damage.current;changes['damage.presets']=window.WikiPersonal.mergePresets(read('damage.presets',[]),value.damage.presets);}
      if(value.gacha){changes['gacha.state']=value.gacha.state;changes['gacha.pool']=value.gacha.poolId;}
      window.WikiPersonal.commit(localStorage,changes);
      if(changes.favorites)favorites=new Set(changes.favorites);
      if(changes.history)history=changes.history;
      if(changes.notes)notes=changes.notes;
      if(changes.comparison)comparison=changes.comparison;
      if(changes.theme){document.body.classList.toggle('dark',changes.theme==='dark');updateThemeIcon();}
      if(changes.readerFont){readerFont=changes.readerFont;document.documentElement.style.setProperty('--reader-font',readerFont+'px');}
      await route();toast('备份已导入，记录已恢复到当前浏览器');
    }catch(e){toast('导入失败：'+e.message);}
    finally{$('#import-file').value='';}
  }
  function openImage(src,caption){$('#lightbox-image').src=src;$('#lightbox-image').alt=caption;$('#image-caption').textContent=caption;$('#image-download').href=src;$('.image-stage').classList.remove('zoom');$('#image-dialog').showModal();}
  function toolView(type=''){activeRoute='#/tools';const title=type==='damage'?'伤害计算器':type==='gacha'?'邂逅模拟器':type==='equipment'?'装备属性参考':type==='infographic'?'一图流工坊':'离线工具';setBreadcrumb(title);document.title=title+' · 铃兰档案馆';window.WikiTools.render(type,$('#main'),{intro,icon,read,persist,toast,find,pages,loadPage,resolvePage,importFile:()=>$('#import-file').click()});}
  let updateCleanup=()=>{};
  async function route(){
    updateCleanup();updateCleanup=()=>{};clearTimeout(searchPageTimer);searchComposing.clear();searchReady=false;
    window.WikiCharacter.unmount();
    window.WikiTools?.unmount();
    clearTimeout(toastTimer);$('#toast').classList.remove('show');
    const hash=location.hash||'#/';const [path,query='']=hash.split('?');const params=new URLSearchParams(query);const token=++renderToken;
    if(path==='#/tools/advanced'){location.replace('#/search'+(query?'?'+query:''));return;}
    document.body.classList.remove('nav-open');document.body.classList.remove('reading');currentPage=null;detailTab='overview';starLevel=5;statLevel='max';activeRoute=path;
    window.scrollTo({top:0,behavior:'instant'});document.title='铃兰档案馆 · 离线 Wiki';nav();updateDock();setBreadcrumb('总览');
    if(path==='#/'||path==='#')$('#main').innerHTML=home();
    else if(path==='#/characters'){setBreadcrumb(types.character);catalogView('character');}
    else if(path.startsWith('#/library/')){const type=path.split('/')[2];if(types[type]){setBreadcrumb(types[type]);catalogView(type);}else $('#main').innerHTML=empty('这条路还没有档案。','返回资料馆，继续探索。','#/','返回总览');}
    else if(path.startsWith('#/page/')){await detail(Number(path.split('/')[2]),token,params);updateDock();}
    else if(path==='#/search'){setBreadcrumb('全站搜索');document.title='全站搜索 · 铃兰档案馆';searchPage=Math.max(1,Number(params.get('page'))||1);searchType=types[params.get('type')]?params.get('type'):'';searchFilters={weapon:params.get('weapon')||'',camps:new Set(params.getAll('camp')),hitKind:['技能','个性','抉择分支'].includes(params.get('hit'))?params.get('hit'):''};await searchView(params.get('q')||'',token);}
    else if(path==='#/favorites'||path==='#/history'){setBreadcrumb(path==='#/favorites'?'我的收藏':'最近浏览');collection(path.slice(2));}
    else if(path==='#/compare'){setBreadcrumb('角色对比');compareView();}
    else if(path==='#/tools'||path==='#/tools/damage'||path==='#/tools/gacha'||path==='#/tools/equipment'||path==='#/tools/infographic')toolView(path.split('/')[2]||'');
    else if(path==='#/archive'){setBreadcrumb('资料馆信息');archiveView();const update=document.createElement('div');$('#main').prepend(update);updateCleanup=window.WikiUpdates.mount(update);}
    else $('#main').innerHTML=empty('这条路还没有档案。','返回资料馆，继续探索。','#/','返回总览');
    if(token===renderToken)nav();
  }
  document.addEventListener('click',e=>{
    const target=e.target instanceof Element?e.target:null;if(!target)return;
    const sourceStat=target.closest('[data-source-stat]');if(sourceStat){const table=sourceStat.closest('table');table.dataset.statPanel=sourceStat.dataset.sourceStat;$$('[data-source-stat]',table).forEach(b=>b.setAttribute('aria-pressed',String(b===sourceStat)));return;}
    const sourceSort=target.closest('[data-source-sort]');if(sourceSort){
      const table=sourceSort.closest('table'),cell=sourceSort.closest('th'),column=Number(sourceSort.dataset.sourceSort);
      const direction=cell.getAttribute('aria-sort')==='ascending'?'descending':'ascending';
      $$('th[aria-sort]',table).forEach(th=>th.setAttribute('aria-sort',th===cell?direction:'none'));
      const rows=[...table.rows].slice(1),sign=direction==='ascending'?1:-1;
      rows.sort((a,b)=>a.cells[column].textContent.trim().localeCompare(b.cells[column].textContent.trim(),'zh-CN',{numeric:true})*sign);
      for(const row of rows)row.parentElement.appendChild(row);return;
    }
    if(target.closest('.skip-link')){e.preventDefault();$('#main').focus();$('#main').scrollIntoView();return;}
    const fav=target.closest('[data-favorite]');if(fav){e.preventDefault();toggleFavorite(Number(fav.dataset.favorite));return;}
    const compare=target.closest('[data-compare]');if(compare){e.preventDefault();toggleCompare(Number(compare.dataset.compare));return;}
    const filter=target.closest('[data-filter]');if(filter){catalog[filter.dataset.filter]=filter.dataset.value;catalog.page=1;updateCatalog();return;}
    const view=target.closest('[data-view]');if(view){catalog.view=view.dataset.view;updateCatalog();return;}
    const unitSort=target.closest('[data-unit-sort]');if(unitSort){const key=unitSort.dataset.unitSort;catalog.descending=catalog.sort===key?!catalog.descending:key.startsWith('stat:');catalog.sort=key;catalog.page=1;$('#catalog-sort').value=key;updateCatalog();$(`[data-unit-sort="${key}"]`)?.focus({preventScroll:true});return;}
    const page=target.closest('[data-catalog-page]');if(page){catalog.page=Number(page.dataset.catalogPage);updateCatalog();$('.catalog-toolbar').scrollIntoView({behavior:'smooth',block:'start'});return;}
    const clearSearch=target.closest('[data-search-clear]');if(clearSearch){const input=document.getElementById(clearSearch.dataset.searchClear);if(input){input.value='';searchComposing.delete(input.id);scheduleSearch(input,true);input.focus();}return;}
    const sp=target.closest('[data-search-page]');if(sp){searchPage=Number(sp.dataset.searchPage);updateSearchPage($('#search-page-query').value);$('#search-page-form').scrollIntoView({behavior:'smooth'});return;}
    const searchFilter=target.closest('[data-search-type]');if(searchFilter){searchType=searchFilter.dataset.searchType;if(searchType&&searchType!=='character'){searchFilters.camps.clear();searchFilters.hitKind='';}searchPage=1;if(searchReady)searchControls();updateSearchPage($('#search-page-query').value);return;}
    const searchExample=target.closest('[data-search-example]');if(searchExample){$('#search-page-query').value=searchExample.dataset.searchExample;searchPage=1;updateSearchPage($('#search-page-query').value);return;}
    if(target.closest('[data-search-reset]')){searchType='';searchFilters={weapon:'',camps:new Set(),hitKind:''};searchPage=1;searchControls();updateSearchPage($('#search-page-query').value);return;}
    const tab=target.closest('[data-detail-tab]');if(tab){detailTab=tab.dataset.detailTab;displayDetail();return;}
    const level=target.closest('[data-level]');if(level){statLevel=level.dataset.level;displayDetail();return;}
    const star=target.closest('[data-star]');if(star){starLevel=Number(star.dataset.star);if(byId.get(currentPage?.id)?.type==='character')characterPanel(byId.get(currentPage.id),currentPage);else displayDetail();return;}
    const portrait=target.closest('[data-portrait]');if(portrait){const p=byId.get(currentPage?.id);if(p){portraitChoices.set(p.id,portrait.dataset.portrait);$('.profile-gallery').innerHTML=window.WikiCharacter.galleryMarkup(p,portrait.dataset.portrait);$('.portrait-variants [aria-pressed="true"]')?.focus({preventScroll:true});}return;}
    const trait=target.closest('[data-trait-mode]');if(trait){traitMode=trait.dataset.traitMode;if(byId.get(currentPage?.id)?.type==='character')characterPanel(byId.get(currentPage.id),currentPage);else displayDetail();queueMicrotask(()=>$(`[data-trait-mode="${traitMode}"]`)?.focus({preventScroll:true}));return;}
    const quick=target.closest('[data-quick-result],[data-quick-all]');if(quick)$('#search-dialog').close();
    const light=target.closest('[data-lightbox]');if(light){e.preventDefault();openImage(light.getAttribute('href'),$('img',light)?.alt||'原站图片');return;}
    const articleImg=target.closest('.wiki-content img');if(articleImg){e.preventDefault();openImage(articleImg.src,articleImg.alt||'原站图片');return;}
    if(target===$('#lightbox-image')){$('.image-stage').classList.toggle('zoom');return;}
    const action=target.closest('[data-action]')?.dataset.action;
    if(action==='search')openSearch();
    if(action==='close-search')$('#search-dialog').close();
    if(action==='close-image')$('#image-dialog').close();
    if(action==='zoom-image')$('.image-stage').classList.toggle('zoom');
    if(action==='menu')document.body.classList.toggle('nav-open');
    if(action==='theme'){document.body.classList.toggle('dark');persist('theme',document.body.classList.contains('dark')?'dark':'light');updateThemeIcon();}
    if(action==='reset-filters'){catalog={...catalog,q:'',rarity:'',class:'',faction:'',weapon:'',prefix:'',page:1};$('#catalog-query').value='';updateCatalog();}
    if(action==='clear-history'&&confirm('清空当前浏览器中的最近浏览记录？')){history=[];persist('history',history);collection('history');toast('浏览记录已清空');}
    if(action==='export')exportBackup();
    if(action==='import')$('#import-file').click();
    if(action==='font-up'||action==='font-down'){readerFont=Math.max(12,Math.min(22,readerFont+(action==='font-up'?1:-1)));persist('readerFont',readerFont);document.documentElement.style.setProperty('--reader-font',readerFont+'px');}
    if(action==='reading'){document.body.classList.toggle('reading');const b=target.closest('[data-action]');b.innerHTML=icon('expand',13)+(document.body.classList.contains('reading')?'退出专注阅读':'专注阅读');}
    const same=target.closest('a[href^="#/"]');if(same&&same.getAttribute('href')===location.hash&&!quick&&!light){e.preventDefault();route();}
  });
  document.addEventListener('input',e=>{
    if(e.target.id==='catalog-query'){catalog.q=e.target.value;catalog.page=1;updateCatalog();}
    if(['search-page-query','quick-search'].includes(e.target.id)){syncSearchClear(e.target);if(!e.isComposing)scheduleSearch(e.target);}
    if(e.target.dataset.note){const id=e.target.dataset.note;notes[id]=e.target.value;const ok=persist('notes',notes);if($('#note-status'))$('#note-status').textContent=ok?'已自动保存在本机':'当前内容尚未保存，请导出备份。';}
  });
  document.addEventListener('compositionstart',e=>{if(['search-page-query','quick-search'].includes(e.target.id)){searchComposing.add(e.target.id);clearTimeout(e.target.id==='search-page-query'?searchPageTimer:quickTimer);}});
  document.addEventListener('compositionend',e=>{if(['search-page-query','quick-search'].includes(e.target.id)){searchComposing.delete(e.target.id);scheduleSearch(e.target,true);}});
  document.addEventListener('change',e=>{
    if(e.target.id==='catalog-sort'){catalog.sort=e.target.value;catalog.descending=catalog.sort.startsWith('stat:');catalog.page=1;updateCatalog();}if(e.target.id==='import-file')importBackup(e.target.files?.[0]);
    if(e.target.id==='search-weapon'||e.target.id==='search-hit'||e.target.dataset.searchCamp){if(e.target.id==='search-weapon')searchFilters.weapon=e.target.value;else if(e.target.id==='search-hit')searchFilters.hitKind=e.target.value;else if(e.target.checked)searchFilters.camps.add(e.target.dataset.searchCamp);else searchFilters.camps.delete(e.target.dataset.searchCamp);searchPage=1;const summary=$('.search-camp-filter summary');if(summary)summary.textContent='角色阵营（多选时同时满足）'+(searchFilters.camps.size?' · 已选 '+searchFilters.camps.size+' 项':'');updateSearchPage($('#search-page-query').value);}
  });
  document.addEventListener('submit',e=>{if(e.target.id==='search-page-form'){e.preventDefault();if(!searchComposing.has('search-page-query'))scheduleSearch($('#search-page-query'),true);}});
  document.addEventListener('keydown',e=>{
    if(e.isComposing||e.keyCode===229||searchComposing.has(document.activeElement?.id))return;
    const typing=/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName||'');
    if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'||e.key==='/'&&!typing){e.preventDefault();openSearch();}
    if(e.key==='Escape')document.body.classList.remove('nav-open');
    if($('#search-dialog').open&&document.activeElement?.id==='quick-search'&&['ArrowDown','ArrowUp','Enter'].includes(e.key)){const links=$$('[data-quick-result]');if(!links.length)return;e.preventDefault();if(e.key==='Enter'){(links[Math.max(0,quickCursor)]||links[0]).click();return;}quickCursor=e.key==='ArrowDown'?(quickCursor+1)%links.length:(quickCursor-1+links.length)%links.length;links.forEach((a,i)=>a.classList.toggle('active',i===quickCursor));links[quickCursor].scrollIntoView({block:'nearest'});}
  });
  $('#nav-scrim').onclick=()=>document.body.classList.remove('nav-open');
  for(const dialog of [$('#search-dialog'),$('#image-dialog')])dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();}});
  function updateThemeIcon(){const dark=document.body.classList.contains('dark');$('[data-action="theme"]').innerHTML=icon(dark?'sun':'moon',17);$('[data-action="theme"]').setAttribute('aria-label',dark?'切换浅色模式':'切换深色模式');}
  $('#search-icon').innerHTML=icon('search',14);$('#dialog-search-icon').innerHTML=icon('search',22);$('[data-action="menu"]').innerHTML=icon('menu',19);updateThemeIcon();
  window.addEventListener('hashchange',route);
  window.addEventListener('storage',e=>{if(e.key?.startsWith('socwiki.')){favorites=new Set(validIds(read('favorites',[])));notes=read('notes',{});history=validIds(read('history',[]));nav();if(activeRoute==='#/favorites')collection('favorites');}});
  document.addEventListener('error',e=>{if(e.target instanceof HTMLImageElement&&!e.target.src.endsWith('/assets/brand/placeholder.svg')){e.target.src='assets/brand/placeholder.svg';e.target.title='原站图片暂不可用';}},true);
  route();
})();
