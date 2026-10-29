/* Opt-in differential updates; the active offline snapshot changes in one IndexedDB transaction. */
window.WikiUpdates=(()=>{
  const API='https://wiki.biligame.com/llzj/api.php',C=window.WikiUpdateConvert;
  let database,active=null,busy=false,aborter,progress={phase:'idle',message:'点击更新时才会联网。'},lastRequest=0;
  const urls=new Map(),listeners=new Set(),BASE=window.WIKI_UPDATE_BASELINE;
  const emit=(message,extra={})=>{progress={...progress,message,...extra};listeners.forEach(fn=>fn(progress));};
  const reqPromise=req=>new Promise((resolve,reject)=>{req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error);});
  async function open(){return new Promise((resolve,reject)=>{const req=indexedDB.open('socwiki-content-updates',1);req.onupgradeneeded=()=>{for(const name of ['meta','cache','blobs'])req.result.createObjectStore(name);};req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error);});}
  async function read(store,key){return reqPromise(database.transaction(store).objectStore(store).get(key));}
  async function write(store,key,value){return new Promise((resolve,reject)=>{const t=database.transaction(store,'readwrite');t.objectStore(store).put(value,key);t.oncomplete=resolve;t.onerror=()=>reject(t.error);t.onabort=()=>reject(t.error||new Error('本机存储空间不足'));});}
  function resolveValue(v){
    if(typeof v==='string')return v.replace(/assets\/(?:wiki|updates)\/[^\s"'<>]+/g,path=>urls.get(path)||path);
    if(Array.isArray(v))return v.map(resolveValue);if(v&&typeof v==='object')return Object.fromEntries(Object.entries(v).map(([k,value])=>[k,resolveValue(value)]));return v;
  }
  async function activate(snapshot){
    active=snapshot;if(!active)return;let downloadedBytes=0;
    for(const [path,key] of Object.entries(active.assetKeys||{})){const blob=await read('blobs',key);if(!blob)throw new Error('更新图片缺失，无法启用这份更新');urls.set(path,URL.createObjectURL(blob));downloadedBytes+=blob.size;}
    const data=window.WIKI_DATA,deleted=new Set(active.deleted||[]),entries=new Map(data.pages.filter(p=>!deleted.has(p.id)).map(p=>[p.id,p]));
    for(const [id,record] of Object.entries(active.records||{})){if(!deleted.has(Number(id)))entries.set(Number(id),record.entry);}
    data.pages=[...entries.values()].map(p=>resolveValue(active.characterOrder?.[p.title]===undefined?p:{...p,sourceOrder:active.characterOrder[p.title]}));data.titles=Object.fromEntries(data.pages.map(p=>[p.title,p.id]));
    for(const [id,r] of Object.entries(active.records||{})){delete data.redirects[id];if(r.redirect)data.redirects[id]=r.redirect;}
    for(const id of deleted)delete data.redirects[id];
    data.archive.pages=data.pages.length;data.archive.expectedPages=data.pages.length;data.archive.counts={};for(const p of data.pages)data.archive.counts[p.type]=(data.archive.counts[p.type]||0)+1;
    const assetsByPath=new Map(Object.values({...BASE.images,...active.images}).map(item=>[item.path,item]));data.archive.images=assetsByPath.size;data.archive.expectedImages=assetsByPath.size;data.archive.bytes+=downloadedBytes;
    data.archive.updatedAt=active.checkedAt;data.archive.sourceRevisionCount=Object.keys(active.revisions||{}).length;
    for(const [id,r] of Object.entries(active.records||{}))if(!deleted.has(Number(id)))window.WIKI_PAGES[id]=resolveValue(r.doc);
  }
  const ready=(async()=>{try{database=await open();await activate(await read('meta','active'));emit(active?'上次更新：'+new Date(active.checkedAt).toLocaleString('zh-CN')+' · '+(active.summary?.pages||0)+' 个页面、'+(active.summary?.images||0)+' 张图片；当前已使用更新资料。':'尚未联网更新，正在使用内置资料。');}catch(error){active=null;for(const url of urls.values())URL.revokeObjectURL(url);urls.clear();emit('更新存储暂不可用：'+error.message+'；仍可阅读内置资料。',{storageError:true});}})();
  function allowed(url){const u=new URL(url);return u.protocol==='https:'&&((u.hostname==='wiki.biligame.com'&&u.pathname==='/llzj/api.php')||(u.hostname==='patchwiki.biligame.com'&&u.pathname.startsWith('/images/llzj/')));}
  async function request(url,blob=false){
    if(!allowed(url))throw new Error('更新地址不属于资料源');
    for(let attempt=0;attempt<3;attempt++){
      if(aborter.signal.aborted)throw new DOMException('已取消','AbortError');
      const wait=Math.max(0,lastRequest+700-Date.now());if(wait)await new Promise(r=>setTimeout(r,wait));if(aborter.signal.aborted)throw new DOMException('已取消','AbortError');lastRequest=Date.now();
      const timeout=new AbortController(),stop=()=>timeout.abort();aborter.signal.addEventListener('abort',stop,{once:true});const timer=setTimeout(stop,45000);
      try{const response=await fetch(url,{signal:timeout.signal,credentials:'omit',cache:'no-store',redirect:'error'});if(!response.ok)throw new Error('来源返回 HTTP '+response.status);return blob?await response.blob():await response.json();}
      catch(error){if(aborter.signal.aborted)throw error;if(attempt===2)throw new Error(error.name==='TypeError'?'无法连接资料源（网络异常、原站限流或跨域访问受限），请稍后重试':error.name==='AbortError'?'资料源响应超时，请稍后重试':error.message);await new Promise(r=>setTimeout(r,2000*2**attempt));}
      finally{clearTimeout(timer);aborter.signal.removeEventListener('abort',stop);}
    }
  }
  async function api(params){const data=await request(API+'?'+new URLSearchParams({format:'json',formatversion:'2',origin:'*',...params}));if(data.error)throw new Error(data.error.info||data.error.code);return data;}
  async function enumerate(params,key){const all=[];let next={};do{const data=await api({...params,...next});all.push(...(data.query?.[key]||[]));next=data.continue;}while(next);return all;}
  async function dependencies(since){
    const changed=await enumerate({action:'query',list:'recentchanges',rcnamespace:'10|828',rcprop:'title|timestamp',rclimit:'500',rcstart:since,rcdir:'newer'},'recentchanges');
    const ids=new Set(),seen=new Set(),pending=changed.map(p=>p.title);while(pending.length){const title=pending.shift();if(seen.has(title))continue;seen.add(title);const rows=await enumerate({action:'query',list:'embeddedin',eititle:title,eilimit:'500'},'embeddedin');for(const row of rows){if(row.ns===0)ids.add(row.pageid);else if(row.ns===10||row.ns===828)pending.push(row.title);}}return ids;
  }
  async function update(){
    await ready;if(busy)return;if(!database)throw new Error('浏览器未允许本机数据存储');busy=true;aborter=new AbortController();emit('正在比对在线 Wiki 版本…',{phase:'checking',completed:0,total:0});
    try{
      const begun=new Date().toISOString(),inventory=await enumerate({action:'query',list:'allpages',apnamespace:'0',aplimit:'500'},'allpages');if(!inventory.length)throw new Error('原站返回空目录，本机数据未修改');
      const titles=Object.fromEntries(inventory.map(p=>[p.title,p.pageid])),revisions={},metas={};
      for(let i=0;i<inventory.length;i+=50){const data=await api({action:'query',prop:'info|revisions',pageids:inventory.slice(i,i+50).map(p=>p.pageid).join('|'),rvprop:'ids|timestamp'});for(const p of data.query.pages){if(p.missing)continue;metas[p.pageid]=p;revisions[p.pageid]=p.lastrevid||p.revisions?.[0]?.revid;}emit(`正在比对版本 ${Math.min(i+50,inventory.length)} / ${inventory.length}`,{completed:Math.min(i+50,inventory.length),total:inventory.length});}
      const previous=active?.revisions||BASE.revisions,since=active?.checkedAt||BASE.capturedAt,affected=await dependencies(since),oldTitles=new Map(window.WIKI_DATA.pages.map(p=>[p.id,p.title])),changed=inventory.filter(p=>revisions[p.pageid]!==previous[p.pageid]||affected.has(p.pageid)||oldTitles.get(p.pageid)!==p.title);
      // Template invalidations expire after recentchanges retention. Conservatively reparse on long gaps.
      const stale=(Date.now()-new Date(since).getTime())>28*86400000;if(stale){changed.splice(0,changed.length,...inventory);emit('距离上次更新超过 28 天，将核对全部正文及模板效果。');}
      // New units also invalidate the transcluded character directory even when its own revision is unchanged.
      const directory=inventory.find(p=>p.pageid===968);if(directory&&changed.some(p=>p.title.startsWith('角色图鉴库/'))&&!changed.some(p=>p.pageid===968)){changed.push(directory);affected.add(968);}
      const deleted=Object.keys(BASE.revisions).concat(Object.keys(active?.records||{})).map(Number).filter(id=>!revisions[id]);
      emit(`发现 ${changed.length} 个页面需要更新，正在比对图片…`,{phase:'downloading',total:changed.length,completed:0});
      const remoteImages=await enumerate({action:'query',list:'allimages',ailimit:'500',aiprop:'url|size|mime|sha1|timestamp'},'allimages');
      const oldImages={...BASE.images,...active?.images},images={...oldImages},imageJobs=[],assetKeys={...active?.assetKeys};
      for(const item of remoteImages){const old=oldImages[item.name],path=old?.path||'assets/updates/'+encodeURIComponent(item.name),signature=item.sha1||item.url+'|'+item.size;
        images[item.name]={...item,path,signature};
        if(!old||old.signature&&old.signature!==signature||old.url!==item.url||old.size!==item.size||!old.signature&&new Date(item.timestamp)>new Date(BASE.capturedAt))imageJobs.push(images[item.name]);
      }
      const records={...active?.records};let count=0;
      for(const p of changed){
        const cacheKey='page:'+p.pageid+':'+revisions[p.pageid]+':'+(affected.has(p.pageid)||stale?begun.slice(0,10):''),cached=!affected.has(p.pageid)&&!stale?await read('cache',cacheKey):null;
        const parsed=cached||(await api({action:'parse',pageid:String(p.pageid),prop:'text|wikitext|images|categories|sections|revid|displaytitle'})).parse;
        if(!parsed||!parsed.text||typeof parsed.wikitext!=='string')throw new Error('页面内容不完整：'+p.title);
        if(!cached)await write('cache',cacheKey,parsed);
        // Preserve images referenced by old revisions even if allimages no longer lists them.
        const html=document.createElement('template');html.innerHTML=parsed.text;
        const known=new Set(Object.values(images).map(v=>C.canonical(v.url)));
        for(const el of html.content.querySelectorAll('img[src]')){const url=C.canonical(el.getAttribute('src'));if(url&&!known.has(url)){const name='补录_'+encodeURIComponent(url),item={name,url,path:'assets/updates/'+encodeURIComponent(name),signature:url,mime:'image/png'};images[name]=item;imageJobs.push(item);known.add(url);}}
        records[p.pageid]=C.convert(parsed,metas[p.pageid],images,titles,window.WIKI_DATA.pages.find(x=>x.id===p.pageid));revisions[p.pageid]=parsed.revid;
        emit(`下载正文 ${++count} / ${changed.length}：${p.title}`,{completed:count,total:changed.length});
      }
      count=0;for(const item of imageJobs){const key=item.path+':'+item.signature;let blob=await read('blobs',key);if(!blob){blob=await request(item.url,true);if(!blob.size||blob.size>40*1024*1024)throw new Error('图片大小异常：'+item.name);const valid=await createImageBitmap(blob).then(b=>{b.close();return true;}).catch(()=>false);if(!valid&&item.mime!=='image/svg+xml')throw new Error('图片无法解码：'+item.name);await write('blobs',key,blob);}assetKeys[item.path]=key;emit(`下载图片 ${++count} / ${imageJobs.length}：${item.name}`,{completed:count,total:imageJobs.length});}
      if(aborter.signal.aborted)throw new DOMException('已取消','AbortError');
      let characterOrder=active?.characterOrder||{};
      if(records[968]){const directory=document.createElement('template');directory.innerHTML=records[968].doc.html;const order={};for(const a of directory.content.querySelectorAll('a[title]')){const title=a.title;if(title.startsWith('角色图鉴库/')&&titles[title]&&order[title]===undefined)order[title]=Object.keys(order).length;}if(Object.keys(order).length)characterOrder=order;}
      const snapshot={records,revisions,images,assetKeys,characterOrder,deleted:[...new Set(deleted)],checkedAt:begun,summary:{pages:changed.length,images:imageJobs.length,deleted:new Set(deleted).size}};
      await new Promise((resolve,reject)=>{const t=database.transaction('meta','readwrite'),store=t.objectStore('meta');if(!active||changed.length||imageJobs.length||JSON.stringify(snapshot.deleted)!==JSON.stringify(active.deleted||[]))store.put(active,'previous');store.put(snapshot,'active');t.oncomplete=resolve;t.onerror=()=>reject(t.error);t.onabort=()=>reject(t.error||new Error('保存失败'));});
      emit(`更新完成：${changed.length} 个页面、${imageJobs.length} 张图片。重新载入即可使用。`,{phase:'complete',summary:snapshot.summary});
      return snapshot.summary;
    }catch(error){const cancelled=aborter.signal.aborted;emit(cancelled?'更新已取消，原资料仍可使用；再次点击可复用已下载文件。':'更新未完成：'+error.message+'。原资料仍可使用，可再次点击重试。',{phase:cancelled?'cancelled':'error'});throw error;}
    finally{busy=false;}
  }
  async function rollback(){await ready;if(busy)return;const previous=await read('meta','previous');await write('meta','active',previous||null);location.reload();}
  function documents(){return Object.fromEntries(Object.entries(active?.records||{}).filter(([id])=>!(active.deleted||[]).includes(Number(id))).map(([id,r])=>[id,resolveValue(r.doc)]));}
  function patchSearch(){if(window.WIKI_SEARCH)for(const id of active?.deleted||[])delete window.WIKI_SEARCH[id];if(window.WIKI_SEARCH)for(const [id,r] of Object.entries(active?.records||{}))if(!(active.deleted||[]).includes(Number(id)))window.WIKI_SEARCH[id]=r.search;}
  function catalog(data){
    if(!active)return data;data=resolveValue(data);
    for(const [id,{doc,entry}] of Object.entries(active.records||{})){
      if((active.deleted||[]).includes(Number(id)))continue;
      if(entry.type==='equipment')data.equipmentIcons[id]=entry.image;
      if(entry.type==='equipment'||entry.title.startsWith('个性/')){const stars=entry.type==='equipment'?[...'一二三四五'].map(s=>doc.fields[s+'星技能']||''):[1,2,3,4,5].map(s=>doc.fields['个性描述'+s]||'');data.starEffects[id]=C.combineStars(stars);}
      if(Number(id)===2729){const t=document.createElement('template');t.innerHTML=resolveValue(doc.html);const rows=[...t.content.querySelectorAll('table.CardSelect tr')].map(r=>[...r.children]).filter(c=>c.length===5&&c[0].tagName==='TD');if(rows.length){const byName=new Map(data.tarot.map(t=>[t.name,t.id]));data.tarot=rows.map(c=>({id:byName.get(c[1].textContent.trim())||'tarot-name-'+c[1].textContent.trim(),name:c[1].textContent.trim(),image:c[0].querySelector('img')?.getAttribute('src')||'',description:c[2].innerHTML,special:c[3].innerHTML,sourceId:2729}));}}
    }
    const engravingDoc=active.records?.[2736]?.doc;if(engravingDoc&&!(active.deleted||[]).includes(2736)){
      const t=document.createElement('template');t.innerHTML=engravingDoc.html;const rows=[...t.content.querySelectorAll('table')].at(-1)?.querySelectorAll('tr')||[],byName=new Map(data.engravings.map(e=>[e.name,e]));
      const entries=[...rows].map(r=>[...r.children]).filter(c=>c.length===2&&c[0].textContent.includes('+')).map(c=>{const name=c[0].textContent.trim(),parts=name.split('+').map(s=>s.trim()),old=byName.get(name);return {id:old?.id||'engraving-name-'+name,name,parts,images:parts.map((p,i)=>active.images?.[p+'刻印.png']?.path||BASE.images[p+'刻印.png']?.path||old?.images[i]||''),description:c[1].innerHTML,sourceId:2736};});if(entries.length)data.engravings=entries;
    }
    for(const [name,item] of Object.entries(active.images||{}))for(const [group,prefix] of [['professions','职业图标_'],['professionBackgrounds','职业图标背景_'],['factions','阵营图标_'],['rarities','文字_']])if(name.startsWith(prefix))(data.badges[group]||={})[name.slice(prefix.length).replace(/\.[^.]+$/,'')]=urls.get(item.path)||item.path;
    return resolveValue(data);
  }
  function mount(root){
    root.innerHTML=`<section class="content-card update-panel"><h2>一键更新资料</h2><p>联网检查 BWIKI 的页面版本和图片变化，只下载新增、修改的内容。全部下载成功后自动启用，收藏、笔记和一图流草稿保留在本机。</p><div class="backup-actions"><button class="button" data-update="start">一键更新</button><button class="button secondary" data-update="cancel" hidden>取消更新</button><button class="button" data-update="reload" hidden>使用新资料</button><button class="text-button" data-update="rollback">回退上一份资料</button></div><p role="status" class="update-status"></p><progress max="1" value="0"></progress><small>保持页面开启直到完成。更新失败可重试，已下载文件可复用。回退仅影响资料，不改变个人记录。</small></section>`;
    function show(p){root.querySelector('.update-status').textContent=p.message;root.querySelector('progress').max=p.total||1;root.querySelector('progress').value=p.completed||0;root.querySelector('[data-update=start]').disabled=busy||p.storageError||p.phase==='complete';root.querySelector('[data-update=cancel]').hidden=!busy;root.querySelector('[data-update=reload]').hidden=p.phase!=='complete';root.querySelector('[data-update=rollback]').disabled=busy;}
    const click=e=>{const action=e.target.dataset.update;if(action==='start'){update().then(()=>location.reload()).catch(()=>{}).finally(()=>show(progress));show(progress);}if(action==='cancel')aborter?.abort();if(action==='reload')location.reload();if(action==='rollback')rollback().catch(error=>emit(error.message,{phase:'error'}));};root.addEventListener('click',click);listeners.add(show);show(progress);return ()=>{root.removeEventListener('click',click);listeners.delete(show);};
  }
  window.addEventListener('beforeunload',e=>{if(busy){e.preventDefault();e.returnValue='';}});
  return {ready,update,rollback,mount,resolve:resolveValue,documents,patchSearch,catalog,image:path=>urls.get(path)||path,status:()=>({...progress,busy}),api,allowed};
})();
