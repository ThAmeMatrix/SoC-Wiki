/* Local name lettering extraction. No uploads, remote models or network requests. */
'use strict';
window.WikiTitleImage=(()=>{
  const canvas=(w,h)=>Object.assign(document.createElement('canvas'),{width:Math.max(1,Math.round(w)),height:Math.max(1,Math.round(h))});
  const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
  let payloadPromise;
  function payload(){
    if(window.WIKI_TITLE_OCR)return Promise.resolve(window.WIKI_TITLE_OCR);
    if(!payloadPromise)payloadPromise=new Promise((resolve,reject)=>{
      const s=document.createElement('script');s.src='assets/ocr/title-ocr.js';
      const end=error=>{clearTimeout(timer);s.remove();if(error){payloadPromise=null;reject(error);}else resolve(window.WIKI_TITLE_OCR);};
      const timer=setTimeout(()=>end(new Error('离线识别文件加载超时')),45000);
      s.onload=()=>end(window.WIKI_TITLE_OCR?null:new Error('离线识别文件不完整'));s.onerror=()=>end(new Error('未找到离线识别文件'));document.head.append(s);
    });return payloadPromise;
  }
  const bytes=base64=>{const raw=atob(base64),out=new Uint8Array(raw.length);for(let i=0;i<raw.length;i++)out[i]=raw.charCodeAt(i);return out;};
  async function recognize(source,signal,progress){
    const data=await payload();if(signal.aborted)throw new DOMException('已取消','AbortError');
    const url=URL.createObjectURL(new Blob([data.source],{type:'text/javascript'})),jobs=new Map();let serial=0,worker;
    try{worker=new Worker(url);}catch(error){URL.revokeObjectURL(url);throw new Error('当前设备无法启动离线识别，可手动圈选名字');}
    const dispose=()=>{worker.terminate();URL.revokeObjectURL(url);for(const job of jobs.values()){clearTimeout(job.timer);job.reject(new DOMException('已取消','AbortError'));}jobs.clear();};
    signal.addEventListener('abort',dispose,{once:true});
    worker.onmessage=({data:m})=>{const job=jobs.get(m.jobId);if(!job)return;if(m.status==='progress'){if(m.data.status==='recognizing text')progress('正在定位名字… '+Math.round(m.data.progress*100)+'%');return;}jobs.delete(m.jobId);clearTimeout(job.timer);m.status==='resolve'?job.resolve(m.data):job.reject(new Error(m.data));};
    worker.onerror=()=>{for(const job of jobs.values()){clearTimeout(job.timer);job.reject(new Error('离线识别暂不可用，可直接圈选名字'));}jobs.clear();};
    const run=(action,payload)=>new Promise((resolve,reject)=>{const jobId=String(++serial),timer=setTimeout(()=>{jobs.delete(jobId);reject(new Error('自动定位耗时较长，可直接圈选名字'));},60000);jobs.set(jobId,{resolve,reject,timer});worker.postMessage({workerId:'title',jobId,action,payload});});
    try{
      progress('正在准备离线文字识别…');
      await run('load',{options:{lstmOnly:true,logging:false}});
      await run('loadLanguage',{langs:data.langs.map(l=>({code:l.code,data:bytes(l.data)})),options:{cacheMethod:'none',lstmOnly:true}});
      await run('initialize',{langs:'chi_sim+chi_tra+eng',oem:1,config:{load_system_dawg:'0',load_freq_dawg:'0'}});
      await run('setParameters',{params:{tessedit_pageseg_mode:'11',user_defined_dpi:'150'}});
      const scale=Math.min(1,1600/Math.max(source.width,source.height)),sample=canvas(source.width*scale,source.height*scale);sample.getContext('2d').drawImage(source,0,0,sample.width,sample.height);
      const blob=await new Promise(resolve=>sample.toBlob(resolve,'image/png'));
      const result=await run('recognize',{image:new Uint8Array(await blob.arrayBuffer()),options:{},output:{text:true,blocks:true}});
      return (result.blocks||[]).flatMap(b=>(b.paragraphs||[]).flatMap(p=>p.lines||[])).map(line=>({text:line.text,confidence:line.confidence,rect:{x:line.bbox.x0/scale,y:line.bbox.y0/scale,w:(line.bbox.x1-line.bbox.x0)/scale,h:(line.bbox.y1-line.bbox.y0)/scale}}));
    }finally{signal.removeEventListener('abort',dispose);dispose();}
  }
  function bounded(rect,source){const x=clamp(Math.round(rect.x),0,source.width-1),y=clamp(Math.round(rect.y),0,source.height-1);return {x,y,w:clamp(Math.round(rect.w),1,source.width-x),h:clamp(Math.round(rect.h),1,source.height-y)};}
  function choose(lines,name,source){
    const normalize=s=>String(s||'').normalize('NFKC').replace(/[^\p{L}\p{N}]/gu,'').toLowerCase(),target=normalize(name);
    const scored=lines.filter(l=>l.rect.w>10&&l.rect.h>8&&normalize(l.text)).map(line=>{
      const text=normalize(line.text),a=Array.from(target),b=Array.from(text),dp=Array(b.length+1).fill(0);
      for(const ch of a){let prev=0;for(let j=1;j<=b.length;j++){const old=dp[j];dp[j]=ch===b[j-1]?prev+1:Math.max(dp[j],dp[j-1]);prev=old;}}
      const match=2*dp[b.length]/Math.max(1,a.length+b.length);
      return {...line,match,score:match*5+Math.min(1,line.rect.h/source.height*8)+Math.min(1,line.rect.w/source.width)*.25};
    }).sort((a,b)=>b.score-a.score);
    let best=scored[0];if(!best)return null;
    // Ornate names are often split into unrelated OCR fragments. Rejoin nearby
    // large fragments before falling back to an isolated piece of the artwork.
    if(best.match<.55){
      const fragments=lines.filter(l=>l.rect.h>source.height*.022&&l.rect.h<source.height*.19&&l.rect.x>source.width*.06&&l.rect.x+l.rect.w<source.width*.94);
      const groups=fragments.map(anchor=>{
        const center=anchor.rect.y+anchor.rect.h/2,parts=fragments.filter(l=>Math.abs(l.rect.y+l.rect.h/2-center)<Math.max(l.rect.h,anchor.rect.h)*1.1);
        const x=Math.min(...parts.map(l=>l.rect.x)),y=Math.min(...parts.map(l=>l.rect.y)),w=Math.max(...parts.map(l=>l.rect.x+l.rect.w))-x,h=Math.max(...parts.map(l=>l.rect.y+l.rect.h))-y;
        // Portrait posters usually reserve the lower wide band for the large
        // name. This is only a fallback; a matching OCR name always wins.
        return {parts,rect:{x,y,w,h},score:h*w*(source.height>source.width*1.3?(.15+center/source.height)**3:1)};
      }).filter(g=>g.parts.length>=3&&g.rect.w>source.width*.4&&g.rect.w/g.rect.h>2&&g.rect.h<source.height*.2).sort((a,b)=>b.score-a.score);
      if(groups.length){const g=groups[0],px=g.rect.h*.3,py=g.rect.h*.16;return {rect:bounded({x:g.rect.x-px,y:g.rect.y-py,w:g.rect.w+px*2,h:g.rect.h+py*2},source),matched:false,text:'',match:0};}
    }
    const pad=Math.max(4,best.rect.h*.12);return {...best,rect:bounded({x:best.rect.x-pad,y:best.rect.y-pad,w:best.rect.w+2*pad,h:best.rect.h+2*pad},source),matched:best.match>=.55};
  }
  function bounds(source){
    const p=source.getContext('2d').getImageData(0,0,source.width,source.height).data;let x0=source.width,y0=source.height,x1=-1,y1=-1,transparent=0;
    for(let y=0;y<source.height;y++)for(let x=0;x<source.width;x++){const a=p[(y*source.width+x)*4+3];if(a<240)transparent++;if(a>8){x0=Math.min(x0,x);y0=Math.min(y0,y);x1=Math.max(x1,x);y1=Math.max(y1,y);}}
    return {rect:x1<0?null:{x:x0,y:y0,w:x1-x0+1,h:y1-y0+1},transparent:transparent/(source.width*source.height)>.03};
  }
  function otsu(hist,total){let sum=0;for(let i=0;i<256;i++)sum+=i*hist[i];let count=0,left=0,best=0,threshold=127;for(let i=0;i<255;i++){count+=hist[i];left+=i*hist[i];if(!count||count===total)continue;const variance=count*(total-count)*(left/count-(sum-left)/(total-count))**2;if(variance>best){best=variance;threshold=i;}}return threshold;}
  function extract(source,rect,{mode='auto',strength=50,color='#ffffff',clean=true}={}){
    rect=bounded(rect,source);const scale=Math.min(1,1400/rect.w,600/rect.h),out=canvas(rect.w*scale,rect.h*scale),ctx=out.getContext('2d',{willReadFrequently:true});ctx.drawImage(source,rect.x,rect.y,rect.w,rect.h,0,0,out.width,out.height);
    if(mode==='alpha')return out;
    const data=ctx.getImageData(0,0,out.width,out.height),p=data.data,N=out.width*out.height,hist=new Uint32Array(256),edges=[];
    const lum=(i)=>p[i]*.299+p[i+1]*.587+p[i+2]*.114;
    for(let y=0;y<out.height;y++)for(let x=0;x<out.width;x++){const i=(y*out.width+x)*4;hist[Math.round(lum(i))]++;if((x<2||y<2||x>=out.width-2||y>=out.height-2)&&p[i+3]>128)edges.push([p[i],p[i+1],p[i+2]]);}
    const median=values=>values.sort((a,b)=>a-b)[Math.floor(values.length/2)]||0,bg=[0,1,2].map(k=>median(edges.map(e=>e[k]))),bgLum=bg[0]*.299+bg[1]*.587+bg[2]*.114;
    const distance=(r,g,b,c)=>Math.hypot(r-c[0],g-c[1],b-c[2]);
    const flat=edges.length&&edges.filter(e=>distance(...e,bg)<30).length/edges.length>.85;
    const selected=[1,3,5].map(i=>parseInt(color.slice(i,i+2),16));
    if(mode==='auto')mode=flat?'remove-border':bgLum<145?'light':'dark';
    let cut=otsu(hist,N);if(mode==='light')cut=clamp(cut,35,215);if(mode==='dark')cut=clamp(cut,40,225);
    for(let i=0;i<p.length;i+=4){let delta;
      if(mode==='remove-border'||mode==='background')delta=distance(p[i],p[i+1],p[i+2],mode==='background'?selected:bg)-(8+strength*1.5);
      else if(mode==='color')delta=(180-strength*1.6)-distance(p[i],p[i+1],p[i+2],selected);
      else delta=(mode==='light'?lum(i)-cut:cut-lum(i))-(strength-50)*2.3;
      p[i+3]=Math.round(p[i+3]*clamp((delta+4)/8,0,1));
    }
    if(clean){
      const seen=new Uint8Array(N),queue=new Int32Array(N),minimum=Math.max(3,Math.round(N/70000));
      for(let start=0;start<N;start++){if(seen[start]||p[start*4+3]<32)continue;let count=1,head=0;queue[0]=start;seen[start]=1;
        while(head<count){const v=queue[head++],x=v%out.width;for(const n of [x?v-1:-1,x<out.width-1?v+1:-1,v-out.width,v+out.width])if(n>=0&&n<N&&!seen[n]&&p[n*4+3]>=32){seen[n]=1;queue[count++]=n;}}
        if(count<minimum)for(let j=0;j<count;j++)p[queue[j]*4+3]=0;
      }
    }
    ctx.putImageData(data,0,0);return out;
  }
  async function decode(file){
    if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>15*1024*1024)throw new Error('请选择 15 MB 以内的 PNG、JPG 或 WebP 图片');
    const url=URL.createObjectURL(file);let image;
    try{image=await new Promise((resolve,reject)=>{const img=new Image();img.onload=()=>resolve(img);img.onerror=()=>reject(new Error('图片无法读取，请换一张图片'));img.src=url;});}finally{URL.revokeObjectURL(url);}
    if(image.width*image.height>24000000)throw new Error('图片超过 2400 万像素，请先缩小图片');
    const scale=Math.min(1,2400/Math.max(image.width,image.height)),out=canvas(image.width*scale,image.height*scale);out.getContext('2d').drawImage(image,0,0,out.width,out.height);return out;
  }
  function encode(source){
    const box=bounds(source).rect;if(!box)throw new Error('当前结果为空，请降低去背景强度或重新圈选名字');
    let scale=Math.min(1,1400/box.w,600/box.h),out;
    for(let i=0;i<9;i++){out=canvas(box.w*scale,box.h*scale);out.getContext('2d').drawImage(source,box.x,box.y,box.w,box.h,0,0,out.width,out.height);const uri=out.toDataURL('image/png');if(uri.length<=1000000)return uri;scale*=.8;}
    throw new Error('字标内容过多，请缩小名字区域');
  }
  async function edit(file,{name,onApply,signal,kind='character'}){
    const title=kind==='author'?'提取作者签名':'提取角色名字';
    const abort=new AbortController();let disposed=false,source,output,rect,gesture=null,picking=false,manual=false,revision=0,renderTimer,history=[];
    const dialog=document.createElement('dialog');dialog.className='ig-cutout-dialog';dialog.setAttribute('aria-label',title);
    dialog.innerHTML=`<div class="ig-cutout-header"><div><span class="ig-eyebrow">NAME LETTERING</span><h2>${title}</h2><p>图片仅在本机处理，支持完全离线使用。</p></div><button type="button" class="icon-button" data-cut="cancel" aria-label="取消字标提取">×</button></div><p class="ig-cutout-status" role="status">正在读取图片…</p><div class="ig-cutout-grid"><section><h3>① 圈选名字区域 <small>在图片上拖动框选</small></h3><canvas class="ig-cutout-source" aria-label="原图：拖动圈选名字" tabindex="0"></canvas><div class="ig-crop-fields">${[['x','左'],['y','上'],['w','宽'],['h','高']].map(([key,label])=>`<label>${label}<input type="number" data-crop="${key}" aria-label="裁剪${label}" min="0" step="1"></label>`).join('')}</div><div class="ig-cutout-actions"><button type="button" class="text-button" data-cut="locate">重新自动定位</button><button type="button" class="text-button" data-cut="full">选择整张图</button><button type="button" class="text-button" data-cut="sample">从原图取色</button></div></section><section><h3>② 透明字标预览 <small>保留原图颜色与纹理</small></h3><div class="ig-cutout-result"><canvas class="ig-cutout-output" aria-label="透明字标预览"></canvas></div><label class="ig-label">去背景方式<select data-cut-option="mode" aria-label="去背景方式"><option value="auto">自动判断</option><option value="light">保留亮色字</option><option value="dark">保留深色字</option><option value="color">保留指定字色</option><option value="background">去除指定背景色</option><option value="alpha">保留原有透明度</option></select></label><div class="ig-cutout-settings"><label>颜色<input type="color" data-cut-option="color" value="#ffffff" aria-label="抠图取色"></label><label>去背景强度 <output data-cut-strength>50</output><input type="range" data-cut-option="strength" min="0" max="100" value="50" aria-label="去背景强度"></label></div><label class="ig-cutout-check"><input type="checkbox" data-cut-option="clean" checked>清除细小杂点</label><div class="ig-cutout-brush"><label>局部修整<select data-cut-option="brush" aria-label="局部修整"><option value="none">仅预览</option><option value="erase">擦除残留背景</option><option value="restore">恢复字的笔画</option></select></label><label>笔刷大小<input type="range" min="3" max="80" value="18" data-cut-option="radius" aria-label="笔刷大小"></label><button type="button" class="text-button" data-cut="undo" disabled>撤销笔刷</button></div><p class="ig-cutout-tip">复杂背景可重新圈选，再调强度或用笔刷修整。切换去背景设置会重新生成结果。</p></section></div><div class="ig-cutout-footer"><span data-cut-size></span><button type="button" class="button secondary" data-cut="cancel">取消</button><button type="button" class="button" data-cut="apply" disabled>使用这个字标</button></div>`;
    document.body.append(dialog);dialog.showModal();
    const $=s=>dialog.querySelector(s),status=s=>{if(!disposed)$('.ig-cutout-status').textContent=s;},opt=key=>$(`[data-cut-option="${key}"]`),sourceView=$('.ig-cutout-source'),resultView=$('.ig-cutout-output');
    const close=()=>{if(disposed)return;disposed=true;abort.abort();clearTimeout(renderTimer);signal?.removeEventListener('abort',close);if(dialog.open)dialog.close();dialog.remove();source=output=null;history=[];};
    signal?.addEventListener('abort',close,{once:true});dialog.addEventListener('close',close);if(signal?.aborted){close();return;}
    function showSource(){if(!source)return;sourceView.width=source.width;sourceView.height=source.height;const c=sourceView.getContext('2d');c.drawImage(source,0,0);c.fillStyle='#03090aa8';c.beginPath();c.rect(0,0,source.width,source.height);c.rect(rect.x,rect.y,rect.w,rect.h);c.fill('evenodd');c.strokeStyle='#ffd78d';c.lineWidth=Math.max(2,source.width/350);c.strokeRect(rect.x,rect.y,rect.w,rect.h);for(const el of dialog.querySelectorAll('[data-crop]'))el.value=rect[el.dataset.crop];}
    function showResult(){if(!output)return;resultView.width=output.width;resultView.height=output.height;resultView.getContext('2d').drawImage(output,0,0);$('[data-cut-size]').textContent=output.width+' × '+output.height+' · 透明背景';$('[data-cut="apply"]').disabled=!bounds(output).rect;}
    function render(){if(!source||disposed)return;clearTimeout(renderTimer);renderTimer=null;output=extract(source,rect,{mode:opt('mode').value,strength:Number(opt('strength').value),color:opt('color').value,clean:opt('clean').checked});history=[];$('[data-cut="undo"]').disabled=true;showSource();showResult();}
    function touched(){manual=true;revision++;}
    async function locate(){
      if(!source||disposed)return;const token=++revision;manual=false;$('[data-cut="locate"]').disabled=true;
      try{const lines=await recognize(source,abort.signal,s=>{if(token===revision)status(s);});if(disposed||token!==revision||manual)return;const found=choose(lines,name,source);if(found){rect=found.rect;render();status(found.matched?(kind==='author'?'已定位到作者署名。请检查透明预览，再应用。':'已定位到角色名字。请检查透明预览，再应用字标。'):'已选出可能的名字区域。请确认是否正确，或拖动重新圈选。');}else status('未识别到清晰文字，请在原图上圈选名字区域。');}
      catch(error){if(!disposed&&token===revision)status(error.message+'。可在原图上圈选后直接抠图。');}
      finally{if(!disposed)$('[data-cut="locate"]').disabled=false;}
    }
    const point=(e,el)=>{const r=el.getBoundingClientRect();return {x:clamp((e.clientX-r.left)/r.width*el.width,0,el.width-1),y:clamp((e.clientY-r.top)/r.height*el.height,0,el.height-1)};};
    sourceView.addEventListener('pointerdown',e=>{if(!source)return;e.preventDefault();touched();const p=point(e,sourceView);if(picking){const rgb=source.getContext('2d').getImageData(p.x,p.y,1,1).data;opt('color').value='#'+Array.from(rgb.slice(0,3)).map(n=>n.toString(16).padStart(2,'0')).join('');if(!['color','background'].includes(opt('mode').value))opt('mode').value='color';picking=false;sourceView.classList.remove('picking');render();status('已取色，可调整强度或改为去除指定背景色。');return;}sourceView.setPointerCapture(e.pointerId);gesture={start:p};});
    sourceView.addEventListener('pointermove',e=>{if(!gesture||!source)return;const p=point(e,sourceView),a=gesture.start;rect=bounded({x:Math.min(p.x,a.x),y:Math.min(p.y,a.y),w:Math.abs(p.x-a.x),h:Math.abs(p.y-a.y)},source);showSource();});
    const endCrop=()=>{if(gesture){gesture=null;render();status('已重新圈选名字区域，请检查右侧透明预览。');}};
    sourceView.addEventListener('pointerup',endCrop);sourceView.addEventListener('pointercancel',endCrop);
    let stroke=null;
    function brush(e){const p=point(e,resultView),c=output.getContext('2d'),radius=Number(opt('radius').value)*output.width/resultView.getBoundingClientRect().width/2;c.save();c.beginPath();c.arc(p.x,p.y,radius,0,Math.PI*2);c.clip();c.clearRect(0,0,output.width,output.height);if(opt('brush').value==='restore')c.drawImage(source,rect.x,rect.y,rect.w,rect.h,0,0,output.width,output.height);c.restore();showResult();}
    resultView.addEventListener('pointerdown',e=>{if(!output||opt('brush').value==='none')return;e.preventDefault();touched();history.push(output.getContext('2d').getImageData(0,0,output.width,output.height));if(history.length>10)history.shift();$('[data-cut="undo"]').disabled=false;stroke=e.pointerId;resultView.setPointerCapture(e.pointerId);brush(e);});
    resultView.addEventListener('pointermove',e=>{if(stroke===e.pointerId)brush(e);});
    resultView.addEventListener('pointerup',()=>stroke=null);resultView.addEventListener('pointercancel',()=>stroke=null);
    dialog.addEventListener('input',e=>{
      if(!source)return;if(e.target.dataset.crop){touched();const key=e.target.dataset.crop,value=Number(e.target.value);if(Number.isFinite(value)){rect=bounded({...rect,[key]:value},source);render();}return;}
      const key=e.target.dataset.cutOption;if(!key)return;if(['brush','radius'].includes(key))return;touched();$('[data-cut-strength]').textContent=opt('strength').value;clearTimeout(renderTimer);renderTimer=setTimeout(render,80);
    });
    dialog.addEventListener('click',e=>{const action=e.target.closest('[data-cut]')?.dataset.cut;if(action==='cancel'){close();return;}if(!source)return;
      if(action==='full'){touched();rect={x:0,y:0,w:source.width,h:source.height};render();}
      if(action==='sample'){picking=true;sourceView.classList.add('picking');status('请点击原图里的字色；去除背景色时可在右侧切换模式。');}
      if(action==='locate')locate();
      if(action==='undo'&&history.length){output.getContext('2d').putImageData(history.pop(),0,0);showResult();$('[data-cut="undo"]').disabled=!history.length;}
      if(action==='apply')try{if(renderTimer)render();const result=encode(output);onApply(result);close();}catch(error){status(error.message);}
    });
    try{source=await decode(file);if(disposed)return;const alpha=bounds(source);if(!alpha.rect)throw new Error('这张图片完全透明，请换一张含名字的图片');rect=alpha.rect;if(alpha.transparent)opt('mode').value='alpha';render();
      if(alpha.transparent)status('已保留图片原有透明度。请检查字标，也可以重新圈选。');else locate();
    }catch(error){if(!disposed)status(error.message);}
  }
  return {edit,decode,extract,choose,bounds,encode,recognize};
})();
