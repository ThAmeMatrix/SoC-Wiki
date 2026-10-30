/* Character infographic editor, backed entirely by the archived wiki. */
'use strict';
window.WikiInfographic=(()=>{
  const R=window.WikiInfographicRules;
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const plain=html=>{const el=document.createElement('div');el.innerHTML=html||'';return el.textContent.trim();};
  const markLabel={required:'必点',optional:'选点'};
  let dataPromise;
  function data(){
    if(window.WIKI_INFOGRAPHIC_DATA)return Promise.resolve(window.WIKI_INFOGRAPHIC_DATA);
    if(!dataPromise)dataPromise=new Promise((resolve,reject)=>{const s=document.createElement('script');s.src='data/infographic.js';
      const timer=setTimeout(()=>{s.remove();dataPromise=null;reject(new Error('一图流数据加载超时，请重试'));},20000);
      s.onload=()=>{clearTimeout(timer);s.remove();window.WIKI_INFOGRAPHIC_DATA?resolve(window.WIKI_INFOGRAPHIC_DATA):reject(new Error('一图流数据文件不完整'));};
      s.onerror=()=>{clearTimeout(timer);s.remove();dataPromise=null;reject(new Error('未找到一图流数据，请完整解压离线包'));};document.head.append(s);});
    return dataPromise;
  }
  function download(name,blob){const url=URL.createObjectURL(blob),a=document.createElement('a');a.download=name;a.href=url;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);}
  function mount(root,h){
    const controller=new AbortController(),signal=controller.signal;
    const $=s=>root.querySelector(s),$$=s=>[...root.querySelectorAll(s)];
    const on=(event,fn)=>root.addEventListener(event,fn,{signal});
    const characters=h.pages.filter(p=>p.type==='character'&&!p.redirect).sort((a,b)=>(a.sourceOrder??1e6)-(b.sourceOrder??1e6));
    let equipment=h.pages.filter(p=>p.type==='equipment'&&!p.redirect);
    const byId=new Map(h.pages.map(p=>[p.id,p]));
    let catalog,model,state,picker=null,change=0,renderVersion=0,timer,ready=false,alive=true,currentCanvas=null,currentBackground=null,currentHero=null,canvasReflow=true,fitComposition=false,currentHitRegions=[],navQuery='',activeJump='',highlightTimer,layoutRegions=[],layoutMode=false,layoutSelected='trait',layoutDrag=null,layoutSnap=true,layoutPreviewTimer=null,layoutGuides=[],layoutUndo=[],layoutRedo=[],layoutHistoryKey='',layoutHistoryTime=0,fullResizeObserver=null;
    const layoutHandles=['nw','n','ne','e','se','s','sw','w'];
    const models=new Map();let statMaxima={};
    async function loadStatMaxima(){
      // Some summoned companions are categorized as animals; only the source's recruitable roster is a reference.
      const reference=characters.filter(character=>character.categories?.includes('可邂逅角色')&&!character.categories.includes('召唤物'));
      const rows=await Promise.all(reference.map(async character=>R.baseStats(character,(await h.loadPage(character.id)).rawFields||{})));
      statMaxima=Object.fromEntries(R.baseStatDefinitions.map(([key])=>[key,Math.max(0,...rows.map(row=>Number(row[key])||0))]));
    }
    root.innerHTML=`<a href="#/tools" class="page-back">← 返回离线工具</a>${h.intro('THE PORTRAIT ATELIER','一图流工坊','把你的养成思路，留在一张图里。')}<div class="ig-loading" role="status">正在展开角色资料与创作工具…</div>`;
    function resolve(title){const p=h.find(title);return p?h.resolvePage(p):null;}
    async function loadModel(character){
      if(models.has(character.id))return models.get(character.id);
      const doc=await h.loadPage(character.id),fields=doc.rawFields||{},names=R.treeNames(fields);
      const lookup=name=>name?(resolve('技能图鉴库/'+name)||h.pages.find(p=>p.type==='skill'&&p.name===name&&!p.redirect)):null;
      const nodes=names.map(row=>({...row,pages:row.names.map(lookup)}));
      const unique=[...new Map(nodes.flatMap(t=>t.pages).filter(Boolean).map(p=>[p.id,p])).values()];
      const basic=lookup(fields['初始普攻']);
      const skills=await Promise.all(unique.map(async p=>{const d=await h.loadPage(p.id);return {id:p.id,name:p.name,image:p.image,kind:R.kind(d.rawFields||{},p.id===basic?.id),description:d.fields?.['技能描述']||'',raw:d.rawFields||{}};}));
      const skillMap=new Map(skills.map(s=>[s.id,s]));
      const traitPage=resolve('个性/'+fields['个性']);let trait=null;
      if(traitPage){const d=await h.loadPage(traitPage.id);trait={id:traitPage.id,name:traitPage.name,image:traitPage.image,stars:[1,2,3,4,5].map(n=>d.fields?.['个性描述'+n]||'')};}
      const liberations=await Promise.all((fields['极限解放']||'').split(/[，,、]/).map(s=>s.trim()).filter(Boolean).map(async name=>{const page=resolve('极限解放/'+name);if(!page)return {name};const d=await h.loadPage(page.id);return {id:page.id,name,image:page.image,description:[1,2,3].map(n=>d.fields?.['极限解放描述'+n]||'').filter(Boolean)};}));
      const badges=[{name:character.rarity,image:catalog.badges?.rarities?.[character.rarity],kind:'rarity'},
        {name:character.class,image:catalog.badges?.professions?.[character.class]||character.professionIcon,kind:'profession',background:catalog.badges?.professionBackgrounds?.[character.class]},
        ...(character.faction||'').split(/[，,、]/).map(name=>({name:name.trim(),image:catalog.badges?.factions?.[name.trim()],kind:'faction'}))].filter(b=>b.image&&b.kind!=='rarity');
      const number=field=>String(field??'').trim();
      const result={character,badges,liberations,equipment,skills,tiers:nodes.map(t=>({rank:t.rank,names:t.names,skills:t.pages.map(p=>p?skillMap.get(p.id):null)})),trait,
        baseStats:R.baseStats(character,fields),statMaxima,
        initialBasic:basic?.id,initialSkillIds:nodes.find(t=>t.rank===0).pages.filter(Boolean).map(p=>p.id),cvZh:fields['中文CV'],cvJa:fields['日文CV'],portrait:(character.portraits?.find(p=>p.key==='awakened')||character.portraits?.find(p=>p.key==='base'))?.src||null,awakened:!!character.portraits?.some(p=>p.key==='awakened')};
      models.set(character.id,result);if(models.size>6)models.delete(models.keys().next().value);return result;
    }
    const jumpTargets=[
      {key:'canvas',name:'画布与整体风格',words:'尺寸 宽 高 横版 竖版 金边 装饰',selector:'.ig-canvas-controls'},
      {key:'layout',name:'区块大小与位置',words:'版面 布局 拖动 缩放 对齐 磁吸 宽 高 坐标',selector:'.ig-layout-controls'},
      {key:'role',name:'角色定位',words:'职业 阵营 定位 文本',selector:'[data-ig-field=roleText]'},
      {key:'character',name:'角色选择',words:'小人 职业 阵营 CV',selector:'.ig-character'},
      {key:'title',name:'角色名字与字标',words:'标题 字体 导入 图片 抠图',selector:'[data-ig-field=titleName]'},
      {key:'subtitle',name:'标题后缀',words:'角色养成 一图流',selector:'[data-ig-field=subtitle]'},
      {key:'typography',name:'字体样式与描边',words:'正文 字体 边框 加粗 斜体 投影 颜色',selector:'.ig-typography'},
      {key:'background',name:'背景立绘',words:'初始 觉醒 拖动 缩放 大小 位置',selector:'.ig-background-controls'},
      {key:'appearance',name:'底框透明度',words:'底框 画面样式 透明度',selector:'.ig-panel-style'},
      {key:'backgroundOpacity',name:'立绘透明度',words:'背景 立绘 透明度',selector:'.ig-background-opacity'},
      {key:'marks',name:'技能标记圈',words:'必点 选点 圆圈 粗细 样式',selector:'.ig-mark-style'},
      {key:'titleTypography',name:'名字样式与描边',words:'名字 字体 斜体 投影 描边',selector:'.ig-title-typography'},
      {key:'trait',name:'个性全星级文本',words:'个性 属性 星级 查看',selector:'.ig-trait-info'},
      {key:'tree',name:'技能树与横线',words:'技能 必点 选点 未标记 分支 粗细 长度',selector:'.ig-skill-tree-controls'},
      {key:'liberation',name:'极限解放',words:'解放 必点 选点 未标记',selector:'.ig-liberations'},
      {key:'treeNotes',name:'加点补充',words:'技能树 底部 备注 文字',selector:'[data-ig-field=treeNotes]'},
      {key:'loadouts',name:'技能搭配',words:'普攻 反应 技能 搭配',selector:'[data-section="03"]'},
      {key:'loadoutNotes',name:'搭配解说',words:'说明 文本 字体 字号 描边 对齐 技能搭配',selector:'.ig-loadout-commentary'},
      {key:'exclusive',name:'专武选择',words:'专武 武器 星级',selector:'.ig-exclusive'},
      {key:'gear',name:'装备与塔罗推荐',words:'武器 装具 塔罗 红字 备注',selector:'.ig-gear-label'},
      {key:'engravings',name:'刻印共鸣',words:'刻印 说明 共鸣',selector:'#ig-engraving-editor'},
      {key:'scores',name:'角色评级',words:'雷达图 评级 评分 DOT 直伤 穿伤 辅助 生存 控制 玩家评估',selector:'.ig-scores'},
      {key:'stats',name:'基础信息',words:'物攻 魔攻 物防 魔防 生命 速度 移动 跳跃 属性 基础',selector:'.ig-base-stats'},
      {key:'notes',name:'养成手记',words:'心得 备注 手记',selector:'[data-ig-field=notes]'},
      {key:'author',name:'作者签名',words:'作者 制作人 名字 署名 by 字体 上传 图片 抠图 提取',selector:'.ig-author-controls'},
      {key:'date',name:'日期与前缀',words:'生成 日期 时间 字样 前缀 更新于',selector:'[data-ig-field=datePrefix]'},
      {key:'topText',name:'顶部自定义文字',words:'交流群 群号 QQ 联系方式 顶部 位置',selector:'[data-ig-field=topText]'}
    ];
    const modules=[
      {key:'character',section:'01',name:'角色与题签',children:['character','role','stats','trait','title','titleTypography','subtitle']},
      {key:'workspace',section:'00',name:'画布与布局',children:['canvas','layout','appearance','typography']},
      {key:'background',section:'06',name:'背景立绘',children:['background','backgroundOpacity']},
      {key:'skills',section:'02',name:'技能与搭配',children:['tree','marks','liberation','treeNotes','loadouts','loadoutNotes']},
      {key:'equipment',section:'04',name:'装备与刻印',children:['exclusive','gear','engravings']},
      {key:'assessment',section:'05',name:'评级与手记',children:['scores','notes']},
      {key:'publication',section:'07',name:'作者与发布',children:['author','topText','date']}
    ];
    const layoutNames={logo:'游戏 Logo',title:'角色名字',subtitle:'标题后缀',cv:'CV 信息',sprite:'角色小人',badges:'职业与阵营',role:'角色定位',topText:'顶部自定义文字',tree:'技能树（含解放与补充）',trait:'个性',exclusive:'专武',loadouts:'技能搭配',loadoutNotes:'搭配解说',gear:'装备与塔罗',scores:'角色评级',stats:'基础信息',engravings:'刻印共鸣',notes:'养成手记',author:'作者签名',date:'日期'};
    const canvasSize=()=>R.canvasSize(state?.canvas);
    const layoutOptions=()=>Object.entries(layoutNames).filter(([key])=>key!=='loadoutNotes'||state.loadoutCommentary.enabled);
    function layoutControls(){return `<details class="ig-layout-controls"><summary>区块大小与位置</summary><p class="ig-hint">以成图左上角为 (0, 0)，单位为 px。拖动区块移动，拖动八个边角与四边改变大小；区块内的文字保持字号，内容自动重新排布，区块变小时排布更紧凑。背景立绘在「背景立绘」中调整。</p><button type="button" class="button secondary" data-ig="layout-toggle">${layoutMode?'完成布局':'调整布局'}</button><div class="ig-layout-history"><button type="button" class="text-button" data-ig="layout-undo" aria-label="撤销上一步布局修改"${layoutUndo.length?'':' disabled'}>撤销</button><button type="button" class="text-button" data-ig="layout-redo" aria-label="重做布局修改"${layoutRedo.length?'':' disabled'}>重做</button><small>布局修改可撤销 · Ctrl+Z / Ctrl+Shift+Z</small></div><label class="ig-label">当前区块<select id="ig-layout-select" aria-label="当前区块">${layoutOptions().map(([key,name])=>`<option value="${key}"${key===layoutSelected?' selected':''}>${name}</option>`).join('')}</select></label><div class="ig-layout-fields">${[['x','左上角 X'],['y','左上角 Y'],['w','宽度'],['h','高度']].map(([key,label])=>`<label>${label}<input type="number" step="1" min="${key==='w'?20:key==='h'?16:0}" max="${key==='x'||key==='w'?canvasSize().width:canvasSize().height}" data-ig-rect="${key}" aria-label="区块${label}"></label>`).join('')}</div><label class="ig-label"><span><input type="checkbox" id="ig-layout-snap"${layoutSnap?' checked':''}> 对齐磁吸（按住 Alt 临时关闭）</span></label><div><button type="button" class="text-button" data-ig="layout-reset">恢复当前区块</button><button type="button" class="text-button" data-ig="layout-reset-all">恢复全部布局</button><button type="button" class="text-button" data-ig="composition-auto">恢复默认排版</button></div><small>吸附画布与其他区块的边缘、中心线。重叠区块可通过下拉列表选中；方向键微调，Shift 加速。</small></details>`;}
    const layoutSnapshot=()=>JSON.parse(JSON.stringify({layout:state.layout||{},canvas:state.canvas,composition:state.composition,background:state.background,backgroundOpacity:state.backgroundOpacity,topTextX:state.topTextX,topTextY:state.topTextY}));
    // Keystrokes and repeated arrow nudges coalesce into a single undo step.
    function pushLayoutHistory(snapshot,coalesceKey){
      const now=Date.now();
      if(coalesceKey&&coalesceKey===layoutHistoryKey&&now-layoutHistoryTime<800){layoutHistoryTime=now;return;}
      layoutHistoryKey=coalesceKey||'';layoutHistoryTime=now;
      layoutUndo.push(snapshot);if(layoutUndo.length>60)layoutUndo.shift();layoutRedo.length=0;syncHistoryButtons();
    }
    function syncHistoryButtons(){$$('[data-ig=layout-undo]').forEach(b=>{b.disabled=!layoutUndo.length;});$$('[data-ig=layout-redo]').forEach(b=>{b.disabled=!layoutRedo.length;});}
    function applyLayout(next){fitComposition=false;Object.assign(state,next);layoutHistoryKey='';updateEditor();syncHistoryButtons();syncLayoutInputs();renderHotspots();syncBackgroundControls();queue();}
    function undoLayout(){if(!layoutUndo.length)return;layoutRedo.push(layoutSnapshot());applyLayout(layoutUndo.pop());}
    function redoLayout(){if(!layoutRedo.length)return;layoutUndo.push(layoutSnapshot());applyLayout(layoutRedo.pop());}
    function syncLayoutInputs(){
      const r=state.layout?.[layoutSelected]||layoutRegions.find(r=>r.key===layoutSelected);if(!r)return;
      const caption=$('.ig-preview-caption');if(caption)caption.textContent=layoutMode?'拖动区块移动 · 八个边角均可拉伸 · 对齐磁吸 · Alt 临时关闭吸附':`点击画布区域跳转编辑 · ${canvasSize().width} × ${canvasSize().height} · 离线保存`;
      $$('#ig-layout-select,[data-ig-full-select]').forEach(select=>select.value=layoutSelected);
      const full=$('.ig-full-preview');if(full){full.dataset.mode=layoutMode?'layout':'view';const controls=$('.ig-full-layout-tools');if(controls)controls.hidden=!layoutMode;$$('[data-ig-full-mode]').forEach(button=>button.setAttribute('aria-pressed',String((button.dataset.igFullMode==='layout')===layoutMode)));}
      $$('[data-ig-full-snap],#ig-layout-snap').forEach(input=>input.checked=layoutSnap);
      $$('[data-ig-rect]').forEach(input=>{input.max=['x','w'].includes(input.dataset.igRect)?canvasSize().width:canvasSize().height;if(document.activeElement!==input)input.value=Math.round(r[input.dataset.igRect]);});
      $$('[data-ig=layout-toggle]').forEach(b=>{b.textContent=layoutMode?'完成布局':'调整布局';b.setAttribute('aria-pressed',String(layoutMode));});
      $$('.ig-layout-readout').forEach(el=>{el.hidden=!layoutMode;el.textContent=`${layoutNames[layoutSelected]} · X ${Math.round(r.x)} · Y ${Math.round(r.y)} · ${Math.round(r.w)} × ${Math.round(r.h)} px`;});
      syncHistoryButtons();
    }
    function setLayoutMode(value){layoutMode=value;syncLayoutInputs();renderHotspots();requestAnimationFrame(sizeFullPreview);}
    function renderLayoutOverlay(guides=layoutDrag?layoutGuides:[]){
      for(const layer of $$('.ig-hotspots')){
        if(layer.closest('.ig-full-preview')&&!$('.ig-full-preview').open){layer.innerHTML='';continue;}
        layer.classList.toggle('ig-layout-mode',layoutMode);if(!layoutMode)continue;
        const focused=layer.contains(document.activeElement)?document.activeElement.dataset.igLayoutSelect:null;
        const regions=layoutRegions.map(r=>({...r,...state.layout?.[r.key]}));
        layer.innerHTML=regions.map(r=>`<button type="button" class="ig-layout-block${r.key===layoutSelected?' selected':''}" data-ig-layout-select="${r.key}" aria-label="布局：${layoutNames[r.key]}" style="left:${r.x/canvasSize().width*100}%;top:${r.y/canvasSize().height*100}%;width:${r.w/canvasSize().width*100}%;height:${r.h/canvasSize().height*100}%"><span>${layoutNames[r.key]}</span>${r.key===layoutSelected?layoutHandles.map(dir=>`<i class="ig-layout-handle ig-handle-${dir}" data-layout-resize="${dir}" aria-hidden="true"></i>`).join(''):''}</button>`).join('')+guides.map(g=>`<i class="ig-layout-guide ${g.axis}" style="${g.axis==='x'?'left':'top'}:${g.value/(g.axis==='x'?canvasSize().width:canvasSize().height)*100}%"></i>`).join('');
        if(focused)layer.querySelector(`[data-ig-layout-select="${focused}"]`)?.focus({preventScroll:true});

      }
    }
    on('pointerdown',e=>{
      const button=e.target.closest('[data-ig-layout-select]');if(!layoutMode||!button||!ready||e.button!==0||layoutDrag)return;
      e.preventDefault();layoutSelected=button.dataset.igLayoutSelect;const r=state.layout[layoutSelected]||layoutRegions.find(r=>r.key===layoutSelected),layer=button.closest('.ig-hotspots');
      const handle=e.target.closest('[data-layout-resize]');
      layoutDrag={id:e.pointerId,startX:e.clientX,startY:e.clientY,rect:{...r},saved:state.layout[layoutSelected],snapshot:layoutSnapshot(),resize:layoutHandles.includes(handle?.dataset.layoutResize)?handle.dataset.layoutResize:false,box:layer.getBoundingClientRect()};layer.setPointerCapture(e.pointerId);syncLayoutInputs();renderLayoutOverlay();
    });
    on('pointermove',e=>{
      const d=layoutDrag;if(!d||d.id!==e.pointerId)return;e.preventDefault();const dx=(e.clientX-d.startX)*canvasSize().width/d.box.width,dy=(e.clientY-d.startY)*canvasSize().height/d.box.height;
      let rect=d.resize?{...d.rect}:{...d.rect,x:d.rect.x+dx,y:d.rect.y+dy};
      if(d.resize){
        if(d.resize.includes('e'))rect.w=d.rect.w+dx;
        if(d.resize.includes('w')){rect.x=d.rect.x+dx;rect.w=d.rect.w-dx;}
        if(d.resize.includes('s'))rect.h=d.rect.h+dy;
        if(d.resize.includes('n')){rect.y=d.rect.y+dy;rect.h=d.rect.h-dy;}
        if(rect.w<20){if(d.resize.includes('w'))rect.x=d.rect.x+d.rect.w-20;rect.w=20;}
        if(rect.h<16){if(d.resize.includes('n'))rect.y=d.rect.y+d.rect.h-16;rect.h=16;}
      }
      const dir=d.resize||'',others=layoutRegions.filter(r=>r.key!==layoutSelected).map(r=>({...r,...state.layout[r.key]})),edges={x:dir.includes('e')?1:dir.includes('w')?-1:0,y:dir.includes('s')?1:dir.includes('n')?-1:0};
      const result=R.snapLayout(rect,others,!!dir,layoutSnap&&!e.altKey,edges,state.canvas);
      state.layout[layoutSelected]=result.rect;layoutGuides=result.guides;syncLayoutInputs();renderLayoutOverlay(result.guides);
      if(!layoutPreviewTimer)layoutPreviewTimer=setTimeout(()=>{layoutPreviewTimer=null;if(layoutDrag)queue(false,0);},70);
    });
    function finishLayoutDrag(e){
      if(!layoutDrag||e.pointerId!==layoutDrag.id)return;const d=layoutDrag;layoutDrag=null;clearTimeout(layoutPreviewTimer);layoutPreviewTimer=null;layoutGuides=[];
      if(e.type==='pointercancel'){if(d.saved)state.layout[layoutSelected]=d.saved;else delete state.layout[layoutSelected];}
      else{const now=state.layout[layoutSelected];if(now&&['x','y','w','h'].some(k=>Math.round(now[k])!==Math.round(d.rect[k])))pushLayoutHistory(d.snapshot,null);}
      queue();
    }
    on('pointerup',finishLayoutDrag);on('pointercancel',finishLayoutDrag);on('lostpointercapture',finishLayoutDrag);
    on('keydown',e=>{if(!layoutMode||!e.target.matches('[data-ig-layout-select]')||!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))return;e.preventDefault();layoutSelected=e.target.dataset.igLayoutSelect;const r=state.layout[layoutSelected]||layoutRegions.find(r=>r.key===layoutSelected),n=e.shiftKey?10:1;pushLayoutHistory(layoutSnapshot(),'nudge:'+layoutSelected+':'+e.key);state.layout[layoutSelected]=R.layoutRect({...r,x:r.x+(e.key==='ArrowLeft'?-n:e.key==='ArrowRight'?n:0),y:r.y+(e.key==='ArrowUp'?-n:e.key==='ArrowDown'?n:0)},state.canvas);queue();});
    on('keydown',e=>{
      if(!layoutMode||!(e.ctrlKey||e.metaKey))return;const key=e.key.toLowerCase();if(key!=='z'&&key!=='y')return;
      if(['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName))return;
      e.preventDefault();if(key==='y'||e.shiftKey)redoLayout();else undoLayout();
    });
    function navMarkup(){return `<nav class="ig-nav" aria-label="修改区域导航"><details${matchMedia('(min-width:1280px)').matches?' open':''}><summary>修改区域导航</summary><div class="ig-nav-search"><input type="search" id="ig-nav-search" aria-label="搜索修改区域" placeholder="搜索修改区域…" autocomplete="off"></div><div class="ig-nav-list"></div><small>也可点击画布中的对应区域</small></details></nav>`;}
    function renderNav(){
      const words=navQuery.toLowerCase().trim().split(/\s+/).filter(Boolean);
      const groups=modules.map((group,i)=>{const items=group.children.map(key=>jumpTargets.find(item=>item.key===key)).filter(item=>item&&words.every(word=>(group.name+' '+item.name+' '+item.words).toLowerCase().includes(word)));return {group,items,i};}).filter(item=>item.items.length);
      $('.ig-nav-list').innerHTML=groups.length?groups.map(({group,items,i})=>`<section class="ig-nav-group" data-ig-nav-group="${group.key}"><h3><span>${String(i+1).padStart(2,'0')}</span>${group.name}</h3><div>${items.map(item=>`<button type="button" data-ig-jump="${item.key}"${activeJump===item.key?' aria-current="location"':''}>${esc(item.name)}</button>`).join('')}</div></section>`).join(''):'<p role="status">没有匹配区域，试试「字体」「技能」「日期」或「群号」。</p>';
    }
    function jumpTo(key){
      const item=jumpTargets.find(item=>item.key===key),target=item&&$(item.selector);if(!target)return;
      $('.ig-full-preview').close();$('.ig-workspace').dataset.igMode='edit';$$('[data-ig-view]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.igView==='edit')));
      for(let el=target;el&&el!==root;el=el.parentElement)if(el.tagName==='DETAILS')el.open=true;
      if(!matchMedia('(min-width:1280px)').matches)$('.ig-nav details').open=false;
      activeJump=key;renderNav();clearTimeout(highlightTimer);$$('.ig-jump-highlight').forEach(el=>el.classList.remove('ig-jump-highlight'));
      const anchor=target.closest('label')||target;anchor.classList.add('ig-jump-highlight');anchor.scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
      const focus=target.matches('input,select,textarea,button')?target:target.querySelector('summary,input,select,textarea,button');if(focus)focus.focus({preventScroll:true});else{anchor.tabIndex=-1;anchor.focus({preventScroll:true});}
      highlightTimer=setTimeout(()=>anchor.classList.remove('ig-jump-highlight'),2200);requestAnimationFrame(syncBranches);
    }
    function renderHotspots(){const full=$('.ig-full-hotspots');if(full&&!layoutMode){full.innerHTML='';full.classList.remove('ig-layout-mode');}if(layoutMode){renderLayoutOverlay();return;}const layer=$('.ig-hotspots');if(!layer)return;layer.classList.remove('ig-layout-mode');layer.innerHTML=currentHitRegions.map(region=>{const item=jumpTargets.find(item=>item.key===region.key);return `<button type="button" data-ig-jump="${region.key}" aria-label="修改${esc(item.name)}" title="修改${esc(item.name)}" style="left:${region.x/canvasSize().width*100}%;top:${region.y/canvasSize().height*100}%;width:${region.w/canvasSize().width*100}%;height:${region.h/canvasSize().height*100}%"><span>${esc(item.name)} ↗</span></button>`;}).join('');}
    window.addEventListener('keydown',event=>{if(event.code==='Space'&&layoutMode&&!layoutDrag&&!['INPUT','TEXTAREA','SELECT'].includes(event.target.tagName)&&(!event.target.closest('button')||event.target.closest('.ig-layout-block'))){event.preventDefault();root.classList.add('ig-layout-peek');}},{signal});window.addEventListener('keyup',event=>{if(event.code==='Space')root.classList.remove('ig-layout-peek');},{signal});window.addEventListener('blur',()=>root.classList.remove('ig-layout-peek'),{signal});
    on('keydown',event=>{if(event.target.id!=='ig-nav-search')return;if(event.key==='Enter'){event.preventDefault();$('.ig-nav-list button')?.click();}if(event.key==='Escape'){navQuery='';event.target.value='';renderNav();}});
    on('click',event=>{if(event.target.id!=='ig-full-canvas'||!ready||layoutMode)return;const box=event.target.getBoundingClientRect(),x=(event.clientX-box.left)*canvasSize().width/box.width,y=(event.clientY-box.top)*canvasSize().height/box.height;const region=[...currentHitRegions].reverse().find(r=>x>=r.x&&x<=r.x+r.w&&y>=r.y&&y<=r.y+r.h);if(region)jumpTo(region.key);});
    function shell(){
      root.innerHTML=`<a href="#/tools" class="page-back">← 返回离线工具</a><div class="ig-heading"><div><div class="ig-eyebrow">THE PORTRAIT ATELIER</div><h1>一图流工坊<span>把养成思路，留在一张图里。</span></h1></div><span id="ig-save-status" class="ig-save-status" role="status">本机自动保存</span></div>
      <div class="ig-toolbar"><div class="ig-quick-actions"><button type="button" class="button ig-focus-portrait" data-ig="portrait-focus">一键凸显立绘主体</button><button type="button" class="button secondary" data-ig="layout-arrange">一键整理布局</button></div><div class="ig-mobile-tabs" role="group" aria-label="工坊视图"><button type="button" data-ig-view="edit" aria-pressed="true">编辑方案</button><button type="button" data-ig-view="preview" aria-pressed="false">成图预览</button></div><div class="ig-toolbar-actions"><button type="button" class="button secondary" data-ig="import">导入方案</button><button type="button" class="button secondary" data-ig="save-plan">保存方案</button><button type="button" class="button" data-ig="export" disabled>${h.icon('download',16)}导出 PNG</button></div></div>
      <div class="ig-workspace" data-ig-mode="edit">${navMarkup()}<div class="ig-editor" id="ig-editor"></div><section class="ig-preview" aria-label="一图流预览"><div class="ig-preview-heading"><button type="button" class="text-button" data-ig="layout-toggle">调整布局</button><div><b>画布预览</b><span id="ig-dimensions">正在绘制</span></div><button type="button" class="text-button" data-ig="background-edit">调整背景</button><button type="button" class="text-button" data-ig="enlarge">放大查看 ${h.icon('expand',15)}</button></div><div class="ig-canvas-wrap" aria-busy="true"><canvas id="ig-canvas" aria-label="角色一图流预览"></canvas><div class="ig-hotspots" aria-label="点击预览区域跳转编辑"></div><div class="ig-render-status" role="status">正在绘制一图流…</div></div><output class="ig-layout-readout" hidden></output><p class="ig-preview-caption">点击画布区域跳转编辑 · 1920 × 1080 · 离线保存</p><p class="ig-preview-help">必点用金色实线，选点用青色点圈。未点亮的分支置灰，初始技能仅展示，解放可标记。玩家评估由你自由书写。</p><p class="ig-density-note" role="status" hidden></p><button type="button" class="ig-retry" data-ig="retry-render" hidden>重新生成预览</button></section></div>
      <dialog class="ig-picker" aria-label="选择资料"><div class="ig-picker-header"><div><span class="ig-eyebrow">OFFLINE COLLECTION</span><h2 id="ig-picker-title">选择</h2></div><button type="button" class="icon-button" data-ig="close-picker" aria-label="关闭选择器">×</button></div><div id="ig-picker-body"></div></dialog>
      <dialog class="ig-full-preview" aria-label="放大一图流" data-mode="view"><div class="ig-full-toolbar"><span>一图流预览</span><div class="ig-full-modes" role="group" aria-label="放大预览模式"><button type="button" data-ig-full-mode="view" aria-pressed="true">查看模式</button><button type="button" data-ig-full-mode="layout" aria-pressed="false">调整布局</button></div><button type="button" class="button secondary" data-ig="zoom-preview">原始尺寸</button><button type="button" class="button" data-ig="export" disabled>导出 PNG</button><button type="button" class="icon-button" data-ig="close-preview" aria-label="关闭预览">×</button></div><div class="ig-full-layout-tools" hidden></div><div class="ig-full-stage"><div class="ig-full-surface"><canvas id="ig-full-canvas" aria-label="放大的一图流"></canvas><div class="ig-hotspots ig-full-hotspots" aria-label="放大布局调整"></div></div></div></dialog><dialog class="ig-background-dialog" aria-label="调整背景立绘"><div class="ig-background-toolbar"><b>调整背景立绘</b><div class="ig-art-choices" id="ig-background-choices"></div><button type="button" class="button secondary" data-ig="background-reset">重置位置</button><button type="button" class="button" data-ig="background-done">完成</button></div><div class="ig-background-area"><div class="ig-background-stage" tabindex="0" aria-label="背景调整画布：拖动移动，滚轮或双指缩放，方向键微调"><canvas id="ig-background-canvas"></canvas><div class="ig-background-bounds" aria-hidden="true"></div><button type="button" class="ig-background-handle" aria-label="拖动缩放立绘" title="拖动缩放立绘">⤢</button></div></div><div class="ig-background-footer"><label>立绘大小<input type="range" min="15" max="400" step="1" data-ig-background-scale aria-label="立绘缩放"><output data-ig-background-percent></output></label><p data-ig-background-quality></p><p>拖动画面移动 · 滚轮 / 双指缩放 · 拖动右下角手柄改变大小 · 方向键微调</p></div></dialog><input type="file" accept="image/png,image/jpeg,image/webp" id="ig-title-file" hidden><input type="file" accept="image/png,image/jpeg,image/webp" id="ig-author-file" hidden><input type="file" accept=".ttf,.otf,.woff,.woff2" id="ig-author-font-file" hidden><input type="file" accept="application/json,.json" id="ig-import-file" hidden>`;
      renderNav();
      fullResizeObserver=new ResizeObserver(()=>sizeFullPreview());fullResizeObserver.observe($('.ig-full-stage'));
      $('.ig-full-preview').addEventListener('close',()=>{if(layoutDrag)finishLayoutDrag({pointerId:layoutDrag.id,type:'pointercancel'});$('.ig-full-layout-tools').innerHTML='';$('.ig-full-hotspots').innerHTML='';renderHotspots();},{signal});
      $('.ig-background-dialog').addEventListener('close',()=>{pointers.clear();gesture=null;if(state)save();},{signal});
    }
    const section=(n,title,body)=>{const group=modules.find(g=>g.section===n),index=modules.indexOf(group)+1;return `<details class="ig-section" data-section="${n}" data-module="${group?.key||n}" open><summary><span class="ig-step">${String(index).padStart(2,'0')}</span><b>${title}</b><span class="ig-collapse">⌄</span></summary><div class="ig-section-body">${body}</div></details>`;};
    const subgroup=(title,body,attrs='')=>`<section class="ig-editor-group" ${attrs}><h3>${title}</h3>${body}</section>`;
    const image=(src,cls='')=>src?`<img src="${esc(src)}" alt="" class="${cls}" loading="lazy">`:'<span class="ig-empty-icon">＋</span>';
    function selector(kind,index,item,label){return `<div class="ig-gear-cell"><button type="button" class="ig-item-slot${item?' filled':''}" data-ig-pick="${kind}" data-index="${index}" aria-label="${esc(label)}${index+1}：${esc(item?.name||'选择')}">${image(item?.image)}<span>${esc(item?.name||label+' '+(index+1))}</span></button><input class="ig-red-note" data-ig-gear-note="${kind}" data-index="${index}" aria-label="${label}${index+1}红字备注" maxlength="24" placeholder="红字备注" value="${esc(state.gearNotes[kind][index])}"><button type="button" class="text-button" data-ig-remove-gear="${kind}" data-index="${index}" aria-label="删除${label}${index+1}推荐位"${state[kind].length===1?' disabled':''}>删除推荐位</button></div>`;}
    const backgroundChoices=()=>['base','awakened'].map(key=>`<button type="button" data-ig-art="${key}" aria-pressed="${state.background.portrait===key}"${model.character.portraits?.some(p=>p.key===key)?'':' disabled'}>${key==='base'?'初始立绘':'觉醒立绘'}</button>`).join('');
    function appearanceControl(key,label){const ring=key==='markWidth',value=ring?state[key]:Math.round((1-state[key])*100);return `<label class="ig-label ig-style-control"><span>${label}<output data-ig-style-value="${key}">${value}${ring?' px':'%'}</output></span><input type="range" data-ig-style="${key}" aria-label="${label}" min="${ring?1:0}" max="${ring?6:100}" step="${ring?0.5:1}" value="${value}"></label>`;}
    function authorControls(){return `<div class="ig-author-controls"><h3>作者签名</h3><label class="ig-label">制作人名字<input data-ig-field="author" aria-label="制作人名字" value="${esc(state.author)}" maxlength="24" placeholder="你的名字"></label><div class="ig-author-modes" role="group" aria-label="作者展示方式">${[['text','文字署名'],['image','图片署名']].map(([key,label])=>`<button type="button" data-ig-author-mode="${key}" aria-pressed="${state.authorMode===key}">${label}</button>`).join('')}</div><div class="ig-author-text-options"${state.authorMode==='text'?'':' hidden'}><label class="ig-label">作者字体<select data-ig-field="authorFont" aria-label="作者字体">${[['signature','项目默认 · 连笔签名'],['serif','思源宋体'],['sans','简洁黑体'],...(state.authorCustomFont?[['custom','自定义 · '+state.authorCustomFont.name]]:[])].map(([key,label])=>`<option value="${key}"${state.authorFont===key?' selected':''}>${esc(label)}</option>`).join('')}</select></label><button type="button" class="text-button" data-ig="author-font-upload">导入本地字体</button>${state.authorCustomFont?'<button type="button" class="text-button" data-ig="author-font-reset">移除导入字体</button>':''}<small>支持 TTF / OTF / WOFF / WOFF2，最大 8 MB。字体随方案保存，导入后可离线使用。</small></div><div class="ig-author-image-options">${state.authorImage?`<img class="ig-author-image-preview" src="${esc(state.authorImage)}" alt="作者透明署名预览">`:''}<button type="button" class="button secondary" data-ig="author-upload">上传图片并提取署名</button>${state.authorImage?'<button type="button" class="text-button" data-ig="author-image-reset">移除署名图片</button>':''}<small>沿用角色字标的自动定位、去背景和笔刷修整。清晰的 by 前缀会自动保留；切换展示方式不删除已有内容。</small></div></div>`;}
    function backgroundControls(){return `<div class="ig-background-controls"><b>背景立绘</b><div class="ig-art-choices">${backgroundChoices()}</div><button type="button" class="button secondary" data-ig="background-edit"${model.portrait?'':' disabled'}>拖动调整大小与位置</button><small><span data-ig-background-kind-label>已选${state.background.portrait==='base'?'初始':'觉醒'}</span> · <span data-ig-background-percent>${Math.round(state.background.scale*100)}%</span></small><small data-ig-background-quality></small></div>`;}
    function engravingEditor(){
      return `<div class="ig-engraving-heading"><b>刻印共鸣</b><small>可多选，每组可添加说明</small></div><div class="ig-engraving-options">${catalog.engravings.map(e=>`<label class="ig-engraving-option${state.engravings.some(v=>v.id===e.id)?' selected':''}"><input type="checkbox" data-ig-engraving="${e.id}"${state.engravings.some(v=>v.id===e.id)?' checked':''}>${e.images.map(src=>image(src)).join('<span>+</span>')}<span>${esc(e.name)}</span></label>`).join('')}</div><div class="ig-engraving-notes">${state.engravings.map(item=>{const e=catalog.engravings.find(e=>e.id===item.id);return `<div class="ig-engraving-note"><b>${esc(e.name)}</b><div class="rich-text">${e.description}</div><label class="ig-label">搭配说明<textarea data-ig-engraving-note="${e.id}" aria-label="${esc(e.name)}说明" maxlength="200" rows="2" placeholder="适合什么场景、为何选择这组刻印…">${esc(item.note)}</textarea></label></div>`;}).join('')}</div>`;
    }

    const configRange=(key,label,min,max,step=1,unit='')=>`<label class="ig-label ig-style-control"><span>${label}<output data-ig-config-value="${key}">${state[key]}${unit}</output></span><input type="range" data-ig-config="${key}" aria-label="${label}" min="${min}" max="${max}" step="${step}" value="${state[key]}"></label>`;
    function titleTypographyControls(){return `<details class="ig-effect-preview ig-title-typography"><summary>名字样式与描边</summary><div data-ig-plain-style${state.titleMode!=='text'?' hidden':''}><label class="ig-cutout-check"><input type="checkbox" data-ig-field="titleBold"${state.titleBold?' checked':''}>加粗名字</label><label class="ig-cutout-check"><input type="checkbox" data-ig-field="titleItalic"${state.titleItalic?' checked':''}>名字斜体</label></div>${configRange('titleScale','名字大小比例',.5,1,.05)}${configRange('titleOutlineWidth','名字描边宽度',0,8,.5,' px')}<label class="ig-label ig-title-color">名字描边颜色<input type="color" data-ig-field="titleOutlineColor" aria-label="名字描边颜色" value="${state.titleOutlineColor}"></label><label class="ig-cutout-check"><input type="checkbox" data-ig-field="titleShadow"${state.titleShadow?' checked':''}>名字投影</label><small>图片字标可调大小、描边和投影；字体与斜体仅用于普通文字。</small></details>`;}
    function typographyControls(){return `<details class="ig-effect-preview ig-typography"><summary>字体样式与描边</summary><label class="ig-label">正文字体<select data-ig-field="bodyFont" aria-label="正文字体"><option value="sans"${state.bodyFont==='sans'?' selected':''}>黑体</option><option value="serif"${state.bodyFont==='serif'?' selected':''}>思源宋体</option></select></label><label class="ig-cutout-check"><input type="checkbox" data-ig-field="bodyBold"${state.bodyBold?' checked':''}>正文加粗</label><label class="ig-cutout-check"><input type="checkbox" data-ig-field="bodyItalic"${state.bodyItalic?' checked':''}>正文斜体</label>${configRange('bodyOutlineWidth','正文描边宽度',0,2,.25,' px')}<label class="ig-label ig-title-color">正文描边颜色<input type="color" data-ig-field="bodyOutlineColor" aria-label="正文描边颜色" value="${state.bodyOutlineColor}"></label><small>技能关键词和星级数值保留原有颜色。</small></details>`;}
    function publicationControls(){return `<details class="ig-effect-preview"><summary>生成日期与顶部自定义文字</summary><label class="ig-label">日期前面的文字<input data-ig-field="datePrefix" aria-label="日期前面的文字" maxlength="24" placeholder="例如：生成日期、更新于（可留空）" value="${esc(state.datePrefix)}"></label><label class="ig-label">生成日期<input type="date" data-ig-field="generatedDate" aria-label="生成日期" value="${R.posterDate(state)}"></label><small data-ig-date-mode>${state.generatedDate?'使用指定日期':'自动使用制图当天日期'}</small><button type="button" class="text-button" data-ig="date-auto">恢复自动日期</button><label class="ig-label">顶部自定义文字<input data-ig-field="topText" aria-label="顶部自定义文字" maxlength="80" placeholder="交流群：123456789" value="${esc(state.topText)}"></label>${configRange('topTextX','顶部文字横向位置',0,canvasSize().width-20,1,' px')}${configRange('topTextY','顶部文字纵向位置',0,canvasSize().height-20,1,' px')}${configRange('topTextSize','顶部文字字号',12,40,1,' px')}<label class="ig-label ig-title-color">顶部文字颜色<input type="color" data-ig-field="topTextColor" aria-label="顶部文字颜色" value="${state.topTextColor}"></label><small>位置以当前画布像素为准；可放在顶部空白处，避免遮挡角色名与图标。</small></details>`;}
    function syncBranches(){
      if(!state||!alive)return;
      for(const tier of $$('.ig-tier')){const svg=tier.querySelector('svg'),box=svg.getBoundingClientRect();if(!box.width||!box.height)continue;const nodes=[...tier.querySelectorAll('.ig-node-select>img,.ig-node-select>.ig-empty-icon')];
        [...svg.querySelectorAll('path')].forEach((path,i)=>{const node=nodes[i];if(!node)return;const r=node.getBoundingClientRect(),center=150,edge=((i===0?r.right+4:r.left-4)-box.left)/box.width*300,end=center+(edge-center)*state.branchLength/100,cy=(r.top+r.height/2-box.top)/box.height*100;path.setAttribute('d',`M${center} ${cy} H${end}`);path.style.strokeWidth=state.branchWidth;path.style.display=state.branchLength===0?'none':'';});
      }
    }
    const branchObserver=new ResizeObserver(()=>{syncBranches();const toolbar=$('.ig-toolbar');if(toolbar){root.style.setProperty('--ig-toolbar-height',toolbar.offsetHeight+'px');root.style.setProperty('--ig-topbar-height',(document.querySelector('.topbar')?.offsetHeight||0)+'px');}});
    root.addEventListener('toggle',()=>requestAnimationFrame(syncBranches),{signal,capture:true});
    function baseStatsMarkup(){
      const base=model.baseStats||{};
      const icon=(key,label)=>catalog.statIcons?.[key]?`<img class="ig-stat-icon" src="${esc(catalog.statIcons[key])}" alt="" title="${label}">`:`<svg class="ig-stat-icon" viewBox="0 0 26 26" aria-hidden="true"><path d="${R.speedIconPath}"/></svg>`;
      return `<div class="ig-base-stats ig-stat-bars"><div class="ig-stat-heading"><strong>基础属性</strong><small>当前 / 角色最高 · 占比</small></div><div class="ig-stat-grid">${R.combatStatDefinitions.map(([key,label])=>{
        const value=base[key],max=model.statMaxima?.[key],pct=R.statRatio(value,max);
        return `<div class="ig-stat-card" data-stat-key="${key}"><div class="ig-stat-value">${icon(key,label)}<small class="ig-stat-label">${label}</small><b class="ig-stat-current">${esc(value||'—')}</b></div><div class="ig-stat-comparison"><small class="ig-stat-max">/ ${max||'—'}</small><em>${pct===null?'—':pct.toFixed(1)+'%'}</em></div><progress max="100" value="${pct??0}" aria-label="${label}占角色最高值（不含召唤物）" aria-valuetext="当前 ${esc(value||'未收录')}，角色最高（不含召唤物）${max||'未收录'}${pct===null?'':'，占 '+pct.toFixed(1)+'%'}"></progress></div>`;
      }).join('')}</div><div class="ig-mobility">${R.mobilityStatDefinitions.map(([key,label])=>`<div data-stat-key="${key}"><small>${label}</small><b class="ig-stat-current">${esc(base[key]||'—')}</b></div>`).join('')}</div></div><small>高亮数值为当前角色属性。六项基础属性以可邂逅角色同项最高值为 100%，不含召唤物；移动与跳跃仅展示当前值。属性取满级满星值，跳跃取跳跃高度，缺失值显示 —。</small>`;
    }

    function canvasControls(){const size=canvasSize();return `<div class="ig-canvas-controls"><h4>画布与整体风格</h4><div class="ig-canvas-presets">${[['1920x1080','横版 16:9'],['1280x1920','竖版海报'],['1080x1920','竖版 9:16'],['1920x1920','方形']].map(([value,label])=>`<button type="button" data-ig-canvas-preset="${value}">${label}</button>`).join('')}</div><div class="ig-commentary-pair"><label class="ig-label">画布宽度<input type="number" min="480" max="4096" step="1" data-ig-canvas-size="width" aria-label="画布宽度" value="${size.width}"></label><label class="ig-label">画布高度<input type="number" min="320" max="8192" step="1" data-ig-canvas-size="height" aria-label="画布高度" value="${size.height}"></label></div><label class="ig-cutout-check"><input type="checkbox" data-ig-canvas-reflow${canvasReflow?' checked':''}>尺寸变更时自动重排区块</label><button type="button" class="button secondary" data-ig="canvas-apply">应用画布尺寸</button><small>关闭自动重排可按比例保留当前布局；尺寸与布局修改均可撤销，文字和选择会保留。</small><label class="ig-label">边框风格<select data-ig-decoration="style" aria-label="边框风格"><option value="gilded"${state.decoration.style==='gilded'?' selected':''}>金饰 · 双层细边与角饰</option><option value="plain"${state.decoration.style==='plain'?' selected':''}>简洁 · 原有青色细边</option></select></label><label class="ig-label">装饰强度<input type="range" min="0" max="100" step="5" data-ig-decoration="intensity" aria-label="装饰强度" value="${Math.round(state.decoration.intensity*100)}"></label><small>使用顶部固定工具栏，可一键凸显立绘主体或按完整信息整理布局；内容较多时自动增加画布高度。两种操作均可撤销。</small></div>`;}
    function resizeCanvas(next){
      fitComposition=false;
      pushLayoutHistory(layoutSnapshot(),null);const old=canvasSize(),size=R.canvasSize(next);
      if(canvasReflow)state.layout={};else state.layout=Object.fromEntries(layoutRegions.map(r=>[r.key,R.layoutRect({x:r.x*size.width/old.width,y:r.y*size.height/old.height,w:r.w*size.width/old.width,h:r.h*size.height/old.height},size)]));
      state.background.x*=size.width/old.width;state.background.y*=size.height/old.height;state.topTextX*=size.width/old.width;state.topTextY*=size.height/old.height;state.canvas=size;changed();
    }
    function commentaryControls(){
      const note=state.loadoutCommentary;
      const range=(key,label,min,max,step,suffix='')=>`<label class="ig-label"><span>${label}<output data-ig-commentary-output="${key}">${note[key]}${suffix}</output></span><input type="range" min="${min}" max="${max}" step="${step}" data-ig-commentary="${key}" aria-label="搭配解说${label}" value="${note[key]}"></label>`;
      return `<div class="ig-loadout-commentary"><label class="ig-cutout-check"><input type="checkbox" data-ig-commentary="enabled"${note.enabled?' checked':''}>显示搭配解说</label><small>可选。开启后显示在技能搭配下方，关闭会保留文字与样式。</small><div class="ig-commentary-fields"${note.enabled?'':' hidden'}><label class="ig-label">解说内容<textarea rows="5" maxlength="2400" data-ig-commentary="text" aria-label="搭配解说内容" placeholder="适用场景、出手顺序、技能取舍…">${esc(note.text)}</textarea></label><div class="ig-commentary-pair"><label class="ig-label">字体<select data-ig-commentary="font" aria-label="搭配解说字体"><option value="sans"${note.font==='sans'?' selected':''}>黑体</option><option value="serif"${note.font==='serif'?' selected':''}>思源宋体</option></select></label><label class="ig-label">对齐<select data-ig-commentary="align" aria-label="搭配解说对齐">${[['left','左对齐'],['center','居中'],['right','右对齐']].map(([key,label])=>`<option value="${key}"${note.align===key?' selected':''}>${label}</option>`).join('')}</select></label></div>${range('size','字号',10,48,1,' px')}${range('lineHeight','行距',1,2.4,.1)}<div class="ig-commentary-pair"><label class="ig-cutout-check"><input type="checkbox" data-ig-commentary="bold"${note.bold?' checked':''}>加粗</label><label class="ig-cutout-check"><input type="checkbox" data-ig-commentary="italic"${note.italic?' checked':''}>斜体</label></div><label class="ig-label ig-title-color">文字颜色<input type="color" data-ig-commentary="color" aria-label="搭配解说文字颜色" value="${note.color}"></label>${range('outlineWidth','描边宽度',0,3,.25,' px')}<label class="ig-label ig-title-color">描边颜色<input type="color" data-ig-commentary="outlineColor" aria-label="搭配解说描边颜色" value="${note.outlineColor}"></label><button type="button" class="button secondary" data-ig="commentary-layout">调整解说框大小与位置</button><small>支持普通与放大预览拖动、拉伸，也可输入坐标和尺寸。文字自动换行，空间不足时适当缩小以完整展示。</small></div></div>`;
    }
    function updateEditor(){
      if(!model||!state||!alive)return;
      const oldSections=new Map($$('.ig-section').map(e=>[e.dataset.section,e.open])),oldDetails=new Map($$('#ig-editor details:not(.ig-section)').map(e=>[e.querySelector('summary')?.textContent,e.open]));
      const c=model.character,exclusive=byId.get(state.exclusive),selectedSkill=id=>model.skills.find(s=>s.id===id);
      const missing=!model.awakened?`<p class="ig-notice">${model.portrait?'此角色尚未收录觉醒立绘，成图暂用初始立绘。':'此角色尚未收录立绘，成图使用纯色背景。'}</p>`:'';
      const characterInfo=`<button type="button" class="ig-character" data-ig-pick="character">${image(c.sprite||c.avatar,'ig-pixel')}<span><small>当前角色 · 点击更换</small><strong>${esc(c.name)}</strong><span class="ig-profile-badges">${model.badges.map(b=>b.background?`<span class="ig-profession-badge" title="${esc(b.name)}"><img src="${esc(b.background)}" alt=""><img class="ig-profession-symbol" src="${esc(b.image)}" alt="${esc(b.name)}"></span>`:`<img class="ig-badge-${b.kind}" src="${esc(b.image)}" alt="${esc(b.name)}" title="${esc(b.name)}">`).join('')}</span></span>${h.icon('chevron',19)}</button><div class="ig-cv"><span>中 CV <b>${esc(model.cvZh||'未收录')}</b></span><span>日 CV <b>${esc(model.cvJa||'未收录')}</b></span></div>${baseStatsMarkup()}<label class="ig-label">角色定位<textarea data-ig-field="roleText" aria-label="角色定位" maxlength="100" rows="2" placeholder="例如：持续伤害 / 控场辅助">${esc(state.roleText)}</textarea></label>`;
      const traitInfo=`<p class="ig-hint">个性与专武按 1→5 星完整展示，变化数值以 / 分隔，未解锁效果记为 0。</p><details class="ig-effect-preview ig-trait-info"><summary>查看个性全星级文本</summary><div class="rich-text">${catalog.starEffects?.[model.trait?.id]?.html||'该角色暂无个性星级资料。'}</div></details>`;
      const titleControls=`<label class="ig-label">标题后缀<input data-ig-field="subtitle" value="${esc(state.subtitle)}" maxlength="48" placeholder="角色养成一图流"></label><label class="ig-label">角色显示名<input data-ig-field="titleName" aria-label="角色显示名" value="${esc(state.titleName)}" maxlength="48" placeholder="${esc(c.name)}"><span>留空使用角色名；也可输入其他名字。</span></label><div class="ig-title-controls"><b>名字展示方式</b><div class="ig-title-modes" role="group" aria-label="名字展示方式">${[['text','普通文字'],['image','图片字标'],...(c.id===9296?[['reference','薇佩拉原图']]:[])].map(([key,label])=>`<button type="button" data-ig-title-mode="${key}" aria-pressed="${state.titleMode===key}"${key==='reference'&&state.titleName&&state.titleName!==c.name?' disabled':''}>${label}</button>`).join('')}</div><label class="ig-label" data-ig-font-controls${state.titleMode!=='text'?' hidden':''}>普通字体<select data-ig-field="titleFont" aria-label="名字普通字体"><option value="serif"${state.titleFont==='serif'?' selected':''}>宋体 · 思源宋体</option><option value="sans"${state.titleFont==='sans'?' selected':''}>黑体 · 简洁清晰</option></select></label><label class="ig-label ig-title-color">角色名字颜色<input type="color" data-ig-field="titleColor" aria-label="角色名字颜色" value="${esc(state.titleColor)}"></label><label class="ig-cutout-check" data-ig-image-controls${state.titleMode!=='image'?' hidden':''}><input type="checkbox" data-ig-field="titleImageTint"${state.titleImageTint?' checked':''}>图片字标随名字颜色着色</label><small data-ig-title-status></small><div><button type="button" class="text-button" data-ig="title-upload">从图片提取名字</button><button type="button" class="text-button" data-ig="export-title">导出透明字标</button><button type="button" class="text-button" data-ig="title-reset">恢复默认</button></div></div>${titleTypographyControls()}`;
      const tree=`<div class="ig-mark-legend"><span>○ 未标记</span><i>→</i><span class="required">● 必点</span><i>→</i><span class="optional">◌ 选点</span><i>→</i><span>○ 未标记</span></div><p class="ig-hint">点击技能循环切换标记。未点亮的分支置灰；初始技能仅作展示，解放也可标记。</p>${configRange('branchWidth','技能树横线粗细',.5,5,.5,' px')}${configRange('branchLength','技能树横线长度',0,100,1,'%')}<div class="ig-liberations"><b>极限解放</b><div>${model.liberations.length?model.liberations.map(s=>`<div class="ig-liberation-node" data-mark="${state.marks[s.id]||''}"><button type="button" class="ig-lib-mark" data-ig-mark="${s.id||0}"${s.id?'':' disabled'} aria-label="${esc(s.name)}，${markLabel[state.marks[s.id]]||'未标记'}，点击切换">${image(s.image)}<span>${esc(s.name)}</span><small>${markLabel[state.marks[s.id]]||'未标记'}</small></button><button type="button" class="ig-lib-info" data-ig-liberation="${s.id||0}" aria-label="查看解放技能${esc(s.name)}">详情</button></div>`).join(''):'<span class="ig-hint">暂无解放技能资料</span>'}</div></div><div class="ig-tree">${model.tiers.map(t=>`<div class="ig-tier" data-rank="${t.rank}" data-branch="${[1,5,9].includes(t.rank)?'short':t.rank===0?'initial':'long'}"><svg class="ig-branches" viewBox="0 0 300 100" preserveAspectRatio="none" aria-hidden="true"><path class="ig-branch-${t.rank===0?'initial':state.marks[t.skills[0]?.id]||'off'}" d="M150 38 H${[1,5,9].includes(t.rank)?84:48}"/><path class="ig-branch-${t.rank===0?'initial':state.marks[t.skills[1]?.id]||'off'}" d="M150 38 H${[1,5,9].includes(t.rank)?216:252}"/></svg>${t.skills.map((s,j)=>{
        const selectable=!!s&&t.rank!==0,mark=selectable?state.marks[s.id]||'':'';
        const content=`${image(s?.image)}<strong>${esc(s?.name||t.names[j]||'未收录')}</strong><small>${t.rank===0?'初始自带':markLabel[mark]||'未标记'}</small>`;
        return `${j===1?`<span class="ig-rank">${t.rank?t.rank+'阶':'初始'}</span>`:''}<div class="ig-tree-node${s?'':' unavailable'}${t.rank===0?' ig-initial-node':''}" data-mark="${esc(mark)}">${selectable?`<button type="button" class="ig-node-select" data-ig-mark="${s.id}" aria-label="${esc(s.name)}，${markLabel[mark]||'未标记'}，点击切换">${content}</button><button type="button" class="ig-node-info" data-ig-info="${s.id}" aria-label="查看${esc(s.name)}详情">详情</button>`:`<div class="ig-node-select ig-node-static">${content}</div>`}</div>`;}).join('')}</div>`).join('')}</div><label class="ig-label">技能树底部文字<textarea data-ig-field="treeNotes" rows="4" maxlength="160" placeholder="加点顺序、先后取舍、解放提示…">${esc(state.treeNotes)}</textarea></label>`;
      const loadouts=`<p class="ig-hint">默认一套，至少保留一套，可按需要增加或删除。每套为普攻、反应和三项技能，重复选择会交换位置。</p>${state.loadouts.map((row,i)=>`<div class="ig-loadout"><div class="ig-loadout-title"><span>${String(i+1).padStart(2,'0')}</span><input aria-label="搭配${i+1}名称" maxlength="24" data-ig-loadout="${i}" value="${esc(row.name)}"><button type="button" class="text-button ig-loadout-remove" data-ig-remove-loadout="${i}" aria-label="删除搭配${i+1}"${state.loadouts.length===1?' disabled':''}>删除</button></div><div class="ig-loadout-slots">${row.slots.map((id,j)=>`<div class="ig-loadout-cell"><small>${['普攻','反应','技能 1','技能 2','技能 3'][j]}</small><button type="button" data-ig-pick="skill" data-row="${i}" data-index="${j}" aria-label="搭配${i+1}${['普攻','反应','技能1','技能2','技能3'][j]}：${esc(selectedSkill(id)?.name||'选择')}">${image(selectedSkill(id)?.image)}<span>${esc(selectedSkill(id)?.name||'选择')}</span></button>${j>1?`<div class="ig-slot-moves"><button type="button" data-ig-move="-1" data-row="${i}" data-index="${j}"${j===2?' disabled':''} aria-label="搭配${i+1}技能${j-1}左移">←</button><button type="button" data-ig-move="1" data-row="${i}" data-index="${j}"${j===4?' disabled':''} aria-label="搭配${i+1}技能${j-1}右移">→</button></div>`:''}</div>`).join('')}</div></div>`).join('')}<button type="button" class="button secondary ig-loadout-add" data-ig="loadout-add">＋ 增加技能搭配</button>${commentaryControls()}`;

      const gear=`<div class="ig-exclusive"><button type="button" data-ig-pick="exclusive" aria-label="选择专武">${image(exclusive?.image)}<span><small>专武 · 全星级效果</small><b>${esc(exclusive?.name||'从装备列表选择')}</b></span>${h.icon('chevron',17)}</button></div>${exclusive?`<details class="ig-effect-preview ig-weapon-info"><summary>查看专武全星级文本</summary><div class="rich-text">${catalog.starEffects?.[exclusive.id]?.html||'此装备暂无星级资料。'}</div></details>`:''}${[['weapons','武器'],['accessories','装具'],['tarot','塔罗']].map(([key,label])=>`<div class="ig-gear-label">${label}推荐 <small>${state[key].length} 个备选位 · 可设置 1—12 个</small></div><div class="ig-item-slots">${state[key].map((id,j)=>selector(key,j,key==='tarot'?catalog.tarot.find(t=>t.id===id):byId.get(id),label)).join('')}</div><button type="button" class="text-button" data-ig-add-gear="${key}"${state[key].length>=12?' disabled':''}>＋ 增加${label}推荐位</button><label class="ig-label ig-group-caption">${label}整组说明<input class="ig-red-note" data-ig-group-note="${key}" maxlength="80" aria-label="${label}整组红字说明" value="${esc(state.groupNotes[key])}" placeholder="可选 · 在本组下方居中显示"></label>`).join('')}<div id="ig-engraving-editor">${engravingEditor()}</div>`;
      const scores=`<p class="ig-hint">评分范围 0—5，支持 0.5 分，仅表达你的角色评价；成图右下角按此绘制六维雷达图。</p><div class="ig-scores">${R.axes.map((axis,i)=>`<div class="ig-score"><label for="ig-score-${i}">${axis}</label><input aria-label="${axis}评分滑块" type="range" min="0" max="5" step="0.5" data-ig-axis="${i}" value="${state.scores[i]}"><input id="ig-score-${i}" aria-label="${axis}评分" type="number" inputmode="decimal" min="0" max="5" step="0.5" data-ig-axis="${i}" value="${state.scores[i]}"></div>`).join('')}</div><button type="button" class="text-button" data-ig="clear-scores">清空评分</button><label class="ig-label">玩家评估（替换成图底部字样）<textarea data-ig-field="scoreText" aria-label="玩家评估" rows="4" maxlength="320" placeholder="强度、定位、适用场景、养成优先级…">${esc(state.scoreText||'')}</textarea><span>留空则保留成图里的「玩家评估 · 0—5」字样（最多两行）。</span></label><label class="ig-label">养成手记<textarea data-ig-field="notes" rows="5" maxlength="320" placeholder="加点顺序、装备选择、实战心得…">${esc(state.notes)}</textarea></label>`;
      const bodies={
        workspace:canvasControls()+layoutControls()+subgroup('区域底框',`<div class="ig-panel-style">${appearanceControl('panelOpacity','区域底框透明度')}<small>仅调整底框，文字与图标保持清晰。</small></div>`)+typographyControls(),
        character:subgroup('角色资料',characterInfo+traitInfo)+subgroup('名字与题签',titleControls),
        background:missing+backgroundControls()+`<div class="ig-background-opacity">${appearanceControl('backgroundOpacity','背景立绘透明度')}</div><p class="ig-hint">初始 / 觉醒选择、位置、大小和透明度均在此调整。顶部「凸显立绘主体」可自动安排展示位置。</p>`,
        skills:subgroup('技能加点',`<div class="ig-skill-tree-controls"><div class="ig-mark-style">${appearanceControl('markWidth','技能标记圈粗细')}</div>${tree}</div>`)+subgroup('技能搭配',loadouts,'data-section="03"'),
        equipment:gear,assessment:scores,publication:authorControls()+publicationControls()
      };
      $('#ig-editor').innerHTML=modules.map(group=>section(group.section,group.name,bodies[group.key])).join('');
      $('[data-ig=portrait-focus]').disabled=!model.portrait;
      for(const el of $$('.ig-section'))if(oldSections.has(el.dataset.section))el.open=oldSections.get(el.dataset.section);
      for(const el of $$('#ig-editor details:not(.ig-section)')){const key=el.querySelector('summary')?.textContent;if(oldDetails.has(key))el.open=oldDetails.get(key);}
      root.style.setProperty('--ig-mark-width',state.markWidth+'px');updateTitleStatus();branchObserver.observe($('#ig-editor'));branchObserver.observe($('.ig-toolbar'));requestAnimationFrame(syncBranches);syncLayoutInputs();
    }
    async function selectCharacter(id,imported){
      const character=characters.find(c=>c.id===id);if(!character)throw new Error('未找到该角色');
      const token=++change;renderVersion++;ready=false;$$('[data-ig="export"],[data-ig="export-title"]').forEach(b=>b.disabled=true);
      if($('#ig-save-status'))$('#ig-save-status').textContent='正在载入角色…';
      const next=await loadModel(character);if(!alive||token!==change)return;
      layoutDrag=null;layoutRegions=[];fitComposition=false;model=next;state=R.restore(imported||h.read('infographic.draft.'+id,null),model,{equipment,...catalog});
      h.persist('infographic.last',id);if(imported)h.persist('infographic.draft.'+id,state);
      if(!$('#ig-editor'))shell();updateEditor();queue(false);
    }
    function save(){const ok=h.persist('infographic.draft.'+state.characterId,state);$('#ig-save-status').textContent=ok?'草稿已保存到本机':'草稿未保存，请导出方案';}
    function queue(persist=true,delay=90){
      if(!alive||!model)return;if(persist)save();
      ready=false;const token=++renderVersion;clearTimeout(timer);$$('[data-ig="export"],[data-ig="export-title"]').forEach(b=>b.disabled=true);
      $('.ig-canvas-wrap').setAttribute('aria-busy',String(!layoutDrag));$('.ig-render-status').textContent='正在更新画布…';$('.ig-render-status').hidden=!!layoutDrag;$('.ig-retry').hidden=true;
      timer=setTimeout(async()=>{
        try{
          const snapshot=JSON.parse(JSON.stringify(state)),selectedModel=model;
          const exclusive=snapshot.exclusive?await h.loadPage(snapshot.exclusive):null;
          const result=await window.WikiInfographicCanvas.draw(selectedModel,snapshot,catalog,exclusive);
          if(!alive||token!==renderVersion)return;
          if(fitComposition){const height=Math.min(8192,Math.max(state.canvas.height,result.recommendedHeight));if(height>state.canvas.height+1){state.canvas.height=height;updateEditor();queue();return;}fitComposition=false;}
          const density=$('.ig-density-note');density.hidden=!result.dense;density.textContent=result.dense?'当前文字较密，已缩小以完整放入画布。增加画布高度或放大对应区块可提升可读性；「一键凸显立绘主体」也会自动留足信息空间。':'';
          currentBackground=result.backgroundRect;currentHero=result.heroArea;currentCanvas=result.canvas;currentHitRegions=result.hitRegions||[];layoutRegions=result.layoutRegions||[];syncLayoutInputs();$('.ig-canvas-wrap').classList.add('ig-has-canvas');renderHotspots();updateBackgroundQuality();updateTitleStatus(result.titleMissing);const c=$('#ig-canvas');c.width=result.width;c.height=result.height;c.getContext('2d').drawImage(result.canvas,0,0);c.setAttribute('aria-label',selectedModel.character.name+'一图流预览');
          $('#ig-dimensions').textContent=result.width+' × '+result.height+' px';$('.ig-render-status').hidden=true;$('.ig-canvas-wrap').setAttribute('aria-busy','false');$$('[data-ig="export"],[data-ig="export-title"]').forEach(b=>b.disabled=false);ready=true;
          if($('.ig-full-preview').open)copyFullPreview();
          if($('.ig-background-dialog').open)copyBackgroundPreview();
          $$('[data-ig=background-edit]').forEach(button=>button.disabled=!currentBackground);
          if(!persist)$('#ig-save-status').textContent='本机自动保存 · 按角色保留草稿';
        }catch(error){if(!alive||token!==renderVersion)return;$('.ig-render-status').textContent='成图未完成：'+error.message;$('.ig-retry').hidden=false;$('.ig-canvas-wrap').setAttribute('aria-busy','false');}
      },delay);
    }
    function updateTitleStatus(missing=[]){
      const element=$('[data-ig-title-status]');if(!element)return;
      element.textContent=missing?.length?'以下字不在内置字库中，已使用后备字形：'+missing.join('、')+'。可从图片提取字标。':state.titleMode==='image'?(state.customTitle?'当前使用图片字标，切换普通文字会保留这张字标。':'尚未导入图片，暂用普通文字。点击「从图片提取名字」开始。'):state.titleMode==='reference'?'保留薇佩拉参考原图字标。':'普通文字 · 无锋刃装饰 · 新名字可离线输入';
      $$('[data-ig-title-mode]').forEach(button=>{button.setAttribute('aria-pressed',String(button.dataset.igTitleMode===state.titleMode));if(button.dataset.igTitleMode==='reference')button.disabled=!!state.titleName&&state.titleName!==model.character.name;});
      $('[data-ig-font-controls]').hidden=state.titleMode!=='text';$('[data-ig-plain-style]').hidden=state.titleMode!=='text';$('[data-ig-image-controls]').hidden=state.titleMode!=='image';
      element.classList.toggle('ig-title-warning',!!missing?.length);
    }
    async function exportTitle(){
      if(!ready){h.toast('请等待成图完成后再导出');return;}
      const artwork=await window.WikiInfographicCanvas.titleArtwork(model,JSON.parse(JSON.stringify(state)),catalog,{maxWidth:2400,height:480,density:1});
      const blob=await new Promise((resolve,reject)=>artwork.canvas.toBlob(b=>b?resolve(b):reject(new Error('字标生成失败')),'image/png'));
      download(artwork.name.replace(/[\\/:*?"<>|]/g,'_')+'-字标.png',blob);h.toast('透明字标已生成');
    }
    function syncBackgroundControls(){
      $$('[data-ig-art]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.igArt===state.background.portrait)));
      $$('[data-ig-background-kind-label]').forEach(el=>el.textContent='已选'+(state.background.portrait==='base'?'初始':'觉醒'));
      $$('[data-ig-background-scale]').forEach(el=>el.value=Math.round(state.background.scale*100));
      $$('[data-ig-background-percent]').forEach(el=>el.textContent=Math.round(state.background.scale*100)+'%');
      updateBackgroundQuality();
    }
    function updateBackgroundQuality(){
      const rect=currentBackground;
      $$('[data-ig-background-quality]').forEach(el=>{el.textContent=rect?`原图 ${rect.naturalWidth} × ${rect.naturalHeight} · 无损素材${rect.w>rect.naturalWidth?' · 已超出原图尺寸，缩小可保留更多细节':''}`:'';});
    }
    function backgroundRect(background=state.background){return R.backgroundRect(currentBackground.naturalWidth,currentBackground.naturalHeight,background,state.canvas,currentHero,currentBackground.contentBounds);}
    function setBackground(background,persist=false){
      state.background={...background,x:Math.max(-canvasSize().width*2,Math.min(canvasSize().width*2,background.x)),y:Math.max(-canvasSize().height*2,Math.min(canvasSize().height*2,background.y)),scale:Math.max(.15,Math.min(4,background.scale))};
      syncBackgroundControls();queue(persist,0);
    }
    function copyBackgroundPreview(){
      if(!currentCanvas)return;const canvas=$('#ig-background-canvas');canvas.width=canvasSize().width;canvas.height=canvasSize().height;canvas.getContext('2d').drawImage(currentCanvas,0,0);
      const stage=$('.ig-background-stage');stage.style.aspectRatio=canvasSize().width+'/'+canvasSize().height;stage.style.maxWidth=`min(100%, calc((90dvh - 205px) * ${canvasSize().width/canvasSize().height}))`;
      const box=$('.ig-background-bounds'),rect=currentBackground;if(!rect){box.hidden=true;return;}box.hidden=false;
      Object.assign(box.style,{left:rect.x/canvasSize().width*100+'%',top:rect.y/canvasSize().height*100+'%',width:rect.w/canvasSize().width*100+'%',height:rect.h/canvasSize().height*100+'%'});
    }
    async function importTitle(file){
      const selectedState=state;
      await window.WikiTitleImage.edit(file,{name:state.titleName.trim()||model.character.name,signal,onApply:uri=>{
        if(!alive||selectedState!==state)return;state.customTitle=uri;state.titleMode='image';state.titleImageTint=false;changed();h.toast('已应用透明名字字标');
      }});
    }
    const pointers=new Map();let gesture=null;
    async function importAuthor(file){
      const selectedState=state;
      await window.WikiTitleImage.edit(file,{name:state.author.trim(),kind:'author',signal,onApply:uri=>{
        if(!alive||selectedState!==state)return;state.authorImage=uri;state.authorMode='image';changed();h.toast('已应用透明作者署名');
      }});
    }
    async function importAuthorFont(file){
      const selectedState=state,extension=file.name.split('.').pop().toLowerCase();
      if(!['ttf','otf','woff','woff2'].includes(extension)||file.size>8*1024*1024)throw new Error('请选择 8 MB 以内的 TTF、OTF、WOFF 或 WOFF2 字体');
      const uri=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).replace(/^data:[^;]*;/,'data:font/'+extension+';'));reader.onerror=()=>reject(new Error('字体文件无法读取'));reader.readAsDataURL(file);});
      const custom={name:file.name,data:uri};
      try{await window.WikiInfographicCanvas.authorFontFace(custom);}catch{throw new Error('字体无法加载，请选择有效的字体文件');}
      if(!alive||selectedState!==state)return;state.authorCustomFont=custom;state.authorFont='custom';state.authorMode='text';changed();h.toast('已导入作者字体，可离线使用');
    }
    const canvasPoint=e=>{const rect=$('#ig-background-canvas').getBoundingClientRect();return {x:(e.clientX-rect.left)*canvasSize().width/rect.width,y:(e.clientY-rect.top)*canvasSize().height/rect.height};};
    function beginGesture(resize=false){
      const points=[...pointers.values()];if(!points.length){gesture=null;return;}
      gesture={base:{...state.background},rect:backgroundRect(),start:points[0],resize};
      if(points.length>1){gesture.mid={x:(points[0].x+points[1].x)/2,y:(points[0].y+points[1].y)/2};gesture.distance=Math.max(1,Math.hypot(points[1].x-points[0].x,points[1].y-points[0].y));}
    }
    on('pointerdown',e=>{if(!e.target.closest('.ig-background-stage')||!currentBackground)return;e.preventDefault();pointers.set(e.pointerId,canvasPoint(e));try{$('.ig-background-stage').setPointerCapture(e.pointerId);}catch{}beginGesture(!!e.target.closest('.ig-background-handle'));});
    on('pointermove',e=>{if(!pointers.has(e.pointerId)||!gesture)return;e.preventDefault();pointers.set(e.pointerId,canvasPoint(e));const points=[...pointers.values()],g=gesture;
      if(points.length>1&&g.mid){const mid={x:(points[0].x+points[1].x)/2,y:(points[0].y+points[1].y)/2},distance=Math.hypot(points[1].x-points[0].x,points[1].y-points[0].y);const next=R.zoomBackground(g.base,g.rect,distance/g.distance,g.mid,state.canvas);next.x+=mid.x-g.mid.x;next.y+=mid.y-g.mid.y;setBackground(next);}
      else if(g.resize){const factor=Math.exp(((points[0].x-g.start.x)+(points[0].y-g.start.y))/750);setBackground(R.zoomBackground(g.base,g.rect,factor,{x:g.rect.x+g.rect.w/2,y:g.rect.y+g.rect.h/2},state.canvas));}
      else setBackground({...g.base,x:g.base.x+points[0].x-g.start.x,y:g.base.y+points[0].y-g.start.y});
    });
    const endPointer=e=>{if(!pointers.has(e.pointerId))return;pointers.delete(e.pointerId);save();beginGesture();};on('pointerup',endPointer);on('pointercancel',endPointer);on('lostpointercapture',endPointer);
    root.addEventListener('wheel',e=>{if(!e.target.closest('.ig-background-stage')||!currentBackground)return;e.preventDefault();setBackground(R.zoomBackground(state.background,backgroundRect(),Math.exp(-e.deltaY*.0015),canvasPoint(e),state.canvas),true);},{signal,passive:false});
    on('keydown',e=>{if(!e.target.closest('.ig-background-stage')||!currentBackground)return;const moves={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};if(moves[e.key]){e.preventDefault();const [dx,dy]=moves[e.key],step=e.shiftKey?40:10;setBackground({...state.background,x:state.background.x+dx*step,y:state.background.y+dy*step},true);}});
    function changed(){
      const focused=document.activeElement,attrs=['data-ig-mark','data-ig-pick','data-row','data-index','data-ig-move'];
      const selector=attrs.filter(k=>focused?.hasAttribute(k)).map(k=>`[${k}="${focused.getAttribute(k)}"]`).join('');
      updateEditor();if(selector)$(selector)?.focus({preventScroll:true});queue();
    }
    function openPicker(kind,index=0,row=0){
      if(!state)return;
      const current=kind==='character'?state.characterId:kind==='exclusive'?state.exclusive:kind==='skill'?state.loadouts[row].slots[index]:state[kind][index];
      picker={kind,index,row,current,query:'',compatible:true};
      const title={character:'选择角色',exclusive:'选择专武',weapons:'选择推荐武器',accessories:'选择推荐装具',tarot:'选择推荐塔罗',skill:['选择普攻','选择反应','选择技能','选择技能','选择技能'][index]}[kind];
      $('#ig-picker-title').textContent=title;
      $('#ig-picker-body').innerHTML=`<div class="ig-picker-tools"><input id="ig-picker-search" placeholder="搜索名称、别名或关键词…" aria-label="搜索备选资料" autocomplete="off">${['exclusive','weapons'].includes(kind)&&model.character.weapon?`<label class="ig-compatible"><input type="checkbox" id="ig-compatible" checked>仅显示${esc(model.character.weapon)}</label>`:''}</div><div class="ig-picker-meta"><span id="ig-picker-count"></span>${kind!=='character'?'<button type="button" class="text-button" data-ig="clear-choice">清除此项</button>':'<span>按角色出场顺序</span>'}</div><div id="ig-picker-options"></div>`;
      renderOptions();$('.ig-picker').showModal();$('#ig-picker-search').focus();
    }
    function options(){
      let list=picker.kind==='character'?characters:picker.kind==='tarot'?catalog.tarot:picker.kind==='skill'?R.pool(model,picker.index):equipment.filter(e=>(e.weapon==='防具')===(picker.kind==='accessories'));
      if(['exclusive','weapons'].includes(picker.kind)&&picker.compatible&&model.character.weapon)list=list.filter(e=>e.weapon===model.character.weapon);
      const normalize=s=>String(s||'').toLocaleLowerCase().replace(/[•・]/g,'·'),q=normalize(picker.query.trim());
      const filtered=list.filter(p=>!q||normalize([p.name,p.aliases,p.class,p.weapon,plain(p.description||p.summary)].filter(Boolean).join(' ')).includes(q));
      const score=p=>normalize(p.name)===q?0:normalize(p.name).startsWith(q)?1:normalize(p.name).includes(q)?2:3;
      return q?filtered.sort((a,b)=>score(a)-score(b)):filtered;
    }
    function renderOptions(){
      if(!picker)return;const list=options();$('#ig-picker-count').textContent=list.length+' 项备选';
      $('#ig-picker-options').className='ig-options '+(picker.kind==='skill'?'ig-skill-options':'');
      $('#ig-picker-options').innerHTML=list.length?list.map(p=>`<article class="ig-choice${p.id===picker.current?' selected':''}"><button type="button" data-ig-choice="${esc(p.id)}" aria-pressed="${p.id===picker.current}">${image(picker.kind==='character'?(p.sprite||p.avatar):p.image,picker.kind==='character'?'ig-pixel':'')}<span><b>${esc(p.name)}</b><small>${esc(picker.kind==='skill'?`${p.id===model.initialBasic?'初始普攻':{basic:'普攻',reaction:'反应',skill:'技能'}[p.kind]}${state.marks[p.id]?' · '+markLabel[state.marks[p.id]]:''}`:picker.kind==='character'?p.class||'角色':p.weapon||'塔罗之语')}</small></span><em>${p.id===picker.current?'已选':'选择'}</em></button>${picker.kind==='skill'?`<div class="ig-choice-description rich-text">${p.description||'此技能暂无描述。'}</div>`:picker.kind==='tarot'?`<div class="ig-choice-description rich-text">${p.description}<br><b>特殊词条：</b>${p.special}</div>`:''}</article>`).join(''):'<div class="ig-no-results">没有匹配的资料。可修改关键词或关闭类型筛选。</div>';
    }
    async function choose(id){
      const p=picker;if(!p)return;
      if(id!==null&&!options().some(v=>String(v.id)===String(id)))return;
      const value=id===null?null:(['tarot'].includes(p.kind)?String(id):Number(id));
      $('.ig-picker').close();picker=null;
      if(p.kind==='character'){await selectCharacter(value);return;}
      if(p.kind==='exclusive')state.exclusive=value;
      else if(p.kind==='skill')R.setSlot(state,model,p.row,p.index,value);
      else {const list=state[p.kind],other=value===null?-1:list.indexOf(value),old=list[p.index];list[p.index]=value;if(other!==-1&&other!==p.index){list[other]=old;const notes=state.gearNotes[p.kind];[notes[other],notes[p.index]]=[notes[p.index],notes[other]];}}
      changed();
    }
    function skillInfo(id){
      const skill=model.skills.find(s=>s.id===id);if(!skill)return;picker=null;$('#ig-picker-title').textContent=skill.name;
      $('#ig-picker-body').innerHTML=`<div class="ig-skill-detail">${image(skill.image)}<div class="rich-text">${skill.description||'此技能暂无描述。'}</div><div class="ig-detail-facts">${[['消耗',skill.raw['技能消耗']],['冷却',skill.raw['技能冷却']],['射程',skill.raw['技能射程']],['范围',skill.raw['技能范围']]].filter(([,v])=>v).map(([k,v])=>`<span>${k} <b>${esc(v)}</b></span>`).join('')}</div><div class="ig-detail-marks">${R.canMark(model,id)?`<button type="button" class="button" data-ig-cycle-detail="${id}">当前：${markLabel[state.marks[id]]||'未标记'} · 点击切换</button>`:'<span class="ig-hint">初始自带技能，仅作展示。</span>'}</div></div>`;
      $('.ig-picker').showModal();
    }
    function fullLayoutControls(){return `<label>当前区块<select data-ig-full-select aria-label="放大预览当前区块">${layoutOptions().map(([key,label])=>`<option value="${key}">${label}</option>`).join('')}</select></label>${[['x','X'],['y','Y'],['w','宽'],['h','高']].map(([key,label])=>`<label>${label}<input type="number" data-ig-rect="${key}" aria-label="放大预览区块${label}" min="${key==='w'?20:key==='h'?16:0}" max="${key==='x'||key==='w'?canvasSize().width:canvasSize().height}" step="1"></label>`).join('')}<label class="ig-full-snap"><input type="checkbox" data-ig-full-snap>对齐磁吸</label><button type="button" data-ig="layout-undo">撤销</button><button type="button" data-ig="layout-redo">重做</button><button type="button" data-ig="layout-reset">重置区块</button><small>拖动移动 · 边角拉伸 · Alt 暂停磁吸 · 按住空格临时查看</small><output class="ig-layout-readout"></output>`;}
    function sizeFullPreview(){
      if(!$('.ig-full-preview')?.open)return;const stage=$('.ig-full-stage'),surface=$('.ig-full-surface'),style=getComputedStyle(stage),padX=parseFloat(style.paddingLeft)+parseFloat(style.paddingRight),padY=parseFloat(style.paddingTop)+parseFloat(style.paddingBottom);
      const actual=stage.classList.contains('actual-size'),scale=actual?1:Math.max(.05,Math.min((stage.clientWidth-padX)/canvasSize().width,(stage.clientHeight-padY)/canvasSize().height,1));
      surface.style.width=canvasSize().width*scale+'px';surface.style.height=canvasSize().height*scale+'px';$('[data-ig=zoom-preview]').textContent=actual?'适应屏幕':'原始尺寸';
    }
    function copyFullPreview(){if(!currentCanvas)return;const c=$('#ig-full-canvas');c.width=currentCanvas.width;c.height=currentCanvas.height;c.getContext('2d').drawImage(currentCanvas,0,0);sizeFullPreview();}
    function openFullPreview(){const full=$('.ig-full-preview');$('.ig-full-layout-tools').innerHTML=fullLayoutControls();copyFullPreview();full.showModal();syncLayoutInputs();renderHotspots();sizeFullPreview();}

    async function exportImage(){
      if(!ready||!currentCanvas){h.toast('请等待成图完成后再导出');return;}
      const name=window.WikiInfographicCanvas.titleText(model,state).replace(/[\\/:*?"<>|]/g,'_')+'-一图流.png',canvas=currentCanvas;
      const blob=await new Promise((resolve,reject)=>canvas.toBlob(b=>b?resolve(b):reject(new Error('PNG 生成失败')),'image/png'));
      if(blob.size>16*1024*1024&&window.WikiAndroid)throw new Error('图片超过 Android 保存上限，请减少手记文字后重试');
      download(name,blob);h.toast('图片已生成，请在保存窗口选择位置');
    }
    async function action(event){
      const target=event.target.closest('button');if(!target||!root.contains(target))return;
      if(target.dataset.igCanvasPreset){const [width,height]=target.dataset.igCanvasPreset.split('x').map(Number);resizeCanvas({width,height});return;}
      if(target.hasAttribute('data-ig-remove-loadout')){if(R.removeLoadout(state,Number(target.dataset.igRemoveLoadout)))changed();return;}
      if(target.dataset.igAddGear){const key=target.dataset.igAddGear;if(state[key]?.length<12){state[key].push(null);state.gearNotes[key].push('');changed();}return;}
      if(target.dataset.igRemoveGear){const key=target.dataset.igRemoveGear;if(state[key]?.length>1){const i=Number(target.dataset.index);state[key].splice(i,1);state.gearNotes[key].splice(i,1);changed();}return;}
      if(target.dataset.igFullMode){setLayoutMode(target.dataset.igFullMode==='layout');return;}
      if(target.dataset.igLayoutSelect){layoutSelected=target.dataset.igLayoutSelect;syncLayoutInputs();renderLayoutOverlay();return;}
      if(target.dataset.igJump){jumpTo(target.dataset.igJump);return;}
      if(target.dataset.igLiberation){const skill=model.liberations.find(s=>s.id===Number(target.dataset.igLiberation));if(!skill)return;picker=null;$('#ig-picker-title').textContent=skill.name;$('#ig-picker-body').innerHTML=`<div class="ig-skill-detail">${image(skill.image)}<div class="rich-text">${skill.description.map((text,i)=>`<p><b>${i+1} 级</b> ${text}</p>`).join('')}</div></div>`;$('.ig-picker').showModal();return;}
      if(target.dataset.igArt){state.background.portrait=target.dataset.igArt;syncBackgroundControls();queue();return;}
      if(target.dataset.igPick){openPicker(target.dataset.igPick,Number(target.dataset.index||0),Number(target.dataset.row||0));return;}
      if(target.dataset.igChoice){await choose(target.dataset.igChoice);return;}
      if(target.dataset.igInfo){skillInfo(Number(target.dataset.igInfo));return;}
      if(target.dataset.igMark||target.dataset.igCycleDetail){
        const id=Number(target.dataset.igMark||target.dataset.igCycleDetail);
        if(!R.cycleMark(state,model,id))return;
        if(target.dataset.igCycleDetail)$('.ig-picker').close();changed();return;
      }
      if(target.dataset.igMove){R.moveSlot(state,Number(target.dataset.row),Number(target.dataset.index),Number(target.dataset.igMove));changed();return;}
      if(target.dataset.igView){$('.ig-workspace').dataset.igMode=target.dataset.igView;$$('[data-ig-view]').forEach(b=>b.setAttribute('aria-pressed',String(b===target)));return;}
      if(target.dataset.igAuthorMode){state.authorMode=target.dataset.igAuthorMode;changed();return;}
      if(target.dataset.igTitleMode){state.titleMode=target.dataset.igTitleMode;updateTitleStatus();queue();return;}
      switch(target.dataset.ig){
        case 'canvas-apply':{const width=Number($('[data-ig-canvas-size=width]').value),height=Number($('[data-ig-canvas-size=height]').value);if(width>0&&height>0)resizeCanvas({width,height});break;}
        case 'portrait-focus':pushLayoutHistory(layoutSnapshot(),null);fitComposition=true;state.composition='spotlight';state.layout={};state.background={...state.background,x:0,y:0,scale:1};state.backgroundOpacity=1;changed();h.toast('已突出立绘主体，完整保留信息，布局可撤销');break;
        case 'layout-arrange':pushLayoutHistory(layoutSnapshot(),null);fitComposition=true;state.composition='information';state.layout={};changed();h.toast('已按完整信息整理布局，可撤销');break;
        case 'author-upload':$('#ig-author-file').click();break;
        case 'author-font-upload':$('#ig-author-font-file').click();break;
        case 'author-font-reset':state.authorCustomFont=null;state.authorFont='signature';changed();break;
        case 'author-image-reset':state.authorImage=null;state.authorMode='text';changed();break;
        case 'composition-auto':fitComposition=false;pushLayoutHistory(layoutSnapshot(),null);state.composition='auto';state.layout={};changed();break;
        case 'loadout-add':R.addLoadout(state,model);changed();break;
        case 'commentary-layout':layoutSelected='loadoutNotes';setLayoutMode(true);jumpTo('layout');break;
        case 'layout-toggle':setLayoutMode(!layoutMode);break;
        case 'layout-undo':undoLayout();break;
        case 'layout-redo':redoLayout();break;
        case 'layout-reset':pushLayoutHistory(layoutSnapshot(),null);delete state.layout[layoutSelected];syncLayoutInputs();queue();break;
        case 'layout-reset-all':pushLayoutHistory(layoutSnapshot(),null);state.layout={};syncLayoutInputs();queue();break;
        case 'date-auto':state.generatedDate='';$('[data-ig-field=generatedDate]').value=R.posterDate(state);$('[data-ig-date-mode]').textContent='自动使用制图当天日期';queue();break;
        case 'title-upload':$('#ig-title-file').click();break;
        case 'title-reset':state.customTitle=null;state.titleName='';state.titleMode=model.character.id===9296?'reference':'text';state.titleFont='serif';state.titleImageTint=false;state.titleBold=false;state.titleItalic=false;state.titleScale=1;state.titleOutlineWidth=0;state.titleOutlineColor='#08121b';state.titleShadow=true;changed();break;
        case 'export-title':await exportTitle();break;
        case 'background-edit':if(!currentBackground){h.toast('此角色暂无可用立绘');break;}$('#ig-background-choices').innerHTML=backgroundChoices();syncBackgroundControls();$('.ig-background-dialog').showModal();copyBackgroundPreview();$('.ig-background-stage').focus();break;
        case 'background-done':pointers.clear();gesture=null;save();$('.ig-background-dialog').close();break;
        case 'background-reset':setBackground({...state.background,x:0,y:0,scale:1},true);break;
        case 'close-picker':$('.ig-picker').close();picker=null;break;
        case 'clear-choice':await choose(null);break;
        case 'retry-render':queue(false);break;
        case 'clear-scores':state.scores=R.axes.map(()=>0);state.rated=false;changed();break;
        case 'export':await exportImage();break;
        case 'enlarge':if(ready){openFullPreview();}else h.toast('预览尚未完成');break;
        case 'close-preview':$('.ig-full-preview').close();break;
        case 'zoom-preview':$('.ig-full-stage').classList.toggle('actual-size');sizeFullPreview();break;
        case 'save-plan':download(model.character.name+'-一图流方案.json',new Blob([JSON.stringify({format:'socwiki-infographic',version:6,state},null,2)],{type:'application/json'}));break;
        case 'import':$('#ig-import-file').click();break;
      }
    }
    on('click',e=>{action(e).catch(err=>h.toast(err.message));});
    on('input',e=>{
      const el=e.target;
      if(el.id==='ig-layout-select'||el.hasAttribute('data-ig-full-select')){layoutSelected=el.value;syncLayoutInputs();renderHotspots();return;}
      if(el.id==='ig-layout-snap'||el.hasAttribute('data-ig-full-snap')){layoutSnap=el.checked;syncLayoutInputs();return;}
      if(el.dataset.igRect){const v=Number(el.value),r=layoutRegions.find(r=>r.key===layoutSelected);if(el.value!==''&&Number.isFinite(v)&&r){pushLayoutHistory(layoutSnapshot(),'rect:'+layoutSelected+':'+el.dataset.igRect);state.layout[layoutSelected]=R.layoutRect({...r,...state.layout[layoutSelected],[el.dataset.igRect]:v},state.canvas);syncLayoutInputs();queue();}return;}
      if(el.id==='ig-nav-search'){navQuery=el.value;renderNav();return;}
      if(el.id==='ig-picker-search'){picker.query=el.value;renderOptions();return;}
      if(el.id==='ig-compatible'){picker.compatible=el.checked;renderOptions();return;}
      if(!state)return;
      if(el.hasAttribute('data-ig-canvas-reflow')){canvasReflow=el.checked;return;}
      if(el.dataset.igDecoration){if(el.dataset.igDecoration==='style')state.decoration.style=el.value==='plain'?'plain':'gilded';else state.decoration.intensity=Math.min(1,Math.max(0,Number(el.value)/100));queue();return;}
      if(el.dataset.igCommentary){const key=el.dataset.igCommentary;if(!(key in state.loadoutCommentary))return;const value=el.type==='checkbox'?el.checked:el.type==='range'?Number(el.value):el.value;state.loadoutCommentary=R.commentary({...state.loadoutCommentary,[key]:value});const out=$(`[data-ig-commentary-output="${key}"]`);if(out)out.textContent=state.loadoutCommentary[key]+(['size','outlineWidth'].includes(key)?' px':'');if(key==='enabled'){if(!value&&layoutSelected==='loadoutNotes')layoutSelected='loadouts';changed();}else queue();return;}
      if(el.dataset.igConfig){const key=el.dataset.igConfig,value=Number(el.value);if(!['bodyOutlineWidth','titleScale','titleOutlineWidth','branchWidth','branchLength','topTextX','topTextY','topTextSize'].includes(key)||!Number.isFinite(value))return;state[key]=Math.max(Number(el.min),Math.min(Number(el.max),value));if(key==='topTextX'||key==='topTextY'){const r=state.layout.topText||layoutRegions.find(r=>r.key==='topText');if(r)state.layout.topText=R.layoutRect({...r,[key==='topTextX'?'x':'y']:state[key]},state.canvas);}$(`[data-ig-config-value="${key}"]`).textContent=state[key]+(key==='branchLength'?'%':key==='titleScale'?'':' px');syncBranches();queue();return;}
      if(el.dataset.igStyle){const key=el.dataset.igStyle,value=Number(el.value);if(!['panelOpacity','backgroundOpacity','markWidth'].includes(key))return;state[key]=key==='markWidth'?Math.min(6,Math.max(1,value)):1-Math.min(100,Math.max(0,value))/100;root.style.setProperty('--ig-mark-width',state.markWidth+'px');$(`[data-ig-style-value="${key}"]`).textContent=value+(key==='markWidth'?' px':'%');queue();return;}
      if(el.hasAttribute('data-ig-background-scale')){const rect=backgroundRect();setBackground(R.zoomBackground(state.background,rect,Number(el.value)/100/state.background.scale,{x:rect.x+rect.w/2,y:rect.y+rect.h/2},state.canvas),true);return;}
      if(el.dataset.igAxis!==undefined){const i=Number(el.dataset.igAxis);if(el.value===''||!Number.isFinite(Number(el.value)))return;
        state.scores[i]=Math.min(5,Math.max(0,Math.round(Number(el.value)*2)/2));state.rated=true;
        $$(`[data-ig-axis="${i}"]`).forEach(input=>{input.value=state.scores[i];});queue();return;}
      if(el.dataset.igLoadout!==undefined){state.loadouts[Number(el.dataset.igLoadout)].name=el.value.slice(0,24);queue();return;}
      if(el.dataset.igGearNote){state.gearNotes[el.dataset.igGearNote][Number(el.dataset.index)]=el.value.slice(0,24);queue();return;}
      if(el.dataset.igGroupNote){state.groupNotes[el.dataset.igGroupNote]=el.value.slice(0,80);queue();return;}
      if(el.dataset.igEngravingNote){const item=state.engravings.find(v=>v.id===el.dataset.igEngravingNote);if(item){item.note=el.value.slice(0,200);queue();}return;}
      const field=el.dataset.igField;if(!field)return;
      if(field==='titleName'){state.titleName=Array.from(el.value.normalize('NFC').replace(/[\u0000-\u001f\u007f]/g,'')).slice(0,24).join('');if(state.titleMode==='reference'&&state.titleName&&state.titleName!==model.character.name)state.titleMode='text';updateTitleStatus();}
      else if(field==='authorFont'&&['signature','serif','sans','custom'].includes(el.value)){state.authorFont=el.value;state.authorMode='text';}
      else if(field==='bodyFont'&&['sans','serif'].includes(el.value))state.bodyFont=el.value;
      else if(field==='titleFont'&&['sans','serif'].includes(el.value))state.titleFont=el.value;
      else if(['bodyBold','bodyItalic','titleBold','titleItalic','titleShadow'].includes(field))state[field]=el.checked;
      else if(['bodyOutlineColor','titleOutlineColor','topTextColor'].includes(field)&&/^#[0-9a-f]{6}$/i.test(el.value))state[field]=el.value;
      else if(field==='datePrefix')state.datePrefix=el.value.slice(0,24);
      else if(field==='topText')state.topText=el.value.slice(0,80);
      else if(field==='generatedDate'){state.generatedDate=R.validDate(el.value)?el.value:'';$('[data-ig-date-mode]').textContent=state.generatedDate?'使用指定日期':'自动使用制图当天日期';}
      else if(field==='titleImageTint')state.titleImageTint=el.checked;
      else if(field==='titleColor'&&/^#[0-9a-f]{6}$/i.test(el.value))state.titleColor=el.value.toLowerCase();
      else if(['notes','subtitle','author','treeNotes','roleText','scoreText'].includes(field))state[field]=el.value;
      queue();
    });
    on('focusout',e=>{if(e.target.dataset.igRect){const r=state.layout[layoutSelected];if(r)e.target.value=Math.round(r[e.target.dataset.igRect]);}});
    on('change',async e=>{
      if(e.target.id==='ig-author-file'||e.target.id==='ig-author-font-file'){const isFont=e.target.id==='ig-author-font-file',file=e.target.files[0];e.target.value='';if(file)try{await (isFont?importAuthorFont(file):importAuthor(file));}catch(error){h.toast(error.message);}return;}
      if(e.target.id==='ig-title-file'){const file=e.target.files[0];e.target.value='';if(file)try{await importTitle(file);}catch(error){h.toast(error.message);}return;}
      if(e.target.dataset.igEngraving){const id=e.target.dataset.igEngraving;
        if(e.target.checked){if(!state.engravings.some(v=>v.id===id))state.engravings.push({id,note:''});}
        else state.engravings=state.engravings.filter(v=>v.id!==id);
        $('#ig-engraving-editor').innerHTML=engravingEditor();$(`[data-ig-engraving="${id}"]`)?.focus({preventScroll:true});queue();return;
      }
      if(e.target.dataset.igAxis!==undefined){const i=Number(e.target.dataset.igAxis);e.target.value=state.scores[i];}
      if(e.target.id!=='ig-import-file')return;
      const file=e.target.files[0];e.target.value='';if(!file)return;
      try{if(file.size>16*1024*1024)throw new Error('方案文件过大，请选择工坊导出的 JSON 方案');const parsed=JSON.parse(await file.text());
        if(parsed?.format!=='socwiki-infographic'||![1,2,3,4,5,6].includes(parsed.version)||![1,2,3,4,5,6].includes(parsed.state?.version)||!characters.some(c=>c.id===parsed.state.characterId))throw new Error('不是有效的一图流方案文件');
        await selectCharacter(parsed.state.characterId,parsed.state);h.toast('一图流方案已导入');
      }catch(error){h.toast('导入失败：'+error.message);}
    });
    data().then(async result=>{catalog=window.WikiUpdates?.catalog(result)||result;await loadStatMaxima();if(!alive)return;equipment=equipment.map(p=>({...p,image:result.equipmentIcons[p.id]||p.image}));equipment.forEach(p=>byId.set(p.id,p));const last=h.read('infographic.last',9296);await selectCharacter(characters.some(c=>c.id===last)?last:characters[0].id);}).catch(error=>{
      if(!alive)return;root.innerHTML=`<a href="#/tools" class="page-back">← 返回离线工具</a><div class="empty-state"><h2>工坊暂时无法打开</h2><p>${esc(error.message)}</p><a class="button" href="#/tools">返回工具列表</a></div>`;
    });
    return ()=>{alive=false;change++;renderVersion++;clearTimeout(timer);clearTimeout(highlightTimer);clearTimeout(layoutPreviewTimer);branchObserver.disconnect();fullResizeObserver?.disconnect();controller.abort();for(const dialog of $$('.ig-picker,.ig-full-preview,.ig-background-dialog'))if(dialog.open)dialog.close();};
  }
  return {mount};
})();
