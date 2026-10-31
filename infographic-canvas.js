/* Canvas renderer uses local script image payloads so file:// exports remain origin-clean. */
'use strict';
window.WikiInfographicCanvas=(()=>{
  const imageCache=new Map(),portraitCache=new Map();
  const portraitBoundsCache=new WeakMap();
  const colors={gold:'#f5d477',orange:'#ff997d',red:'#ff9292',blue:'#79d1f2',green:'#a7dea0',purple:'#d7b1f3',white:'#edf2f0'};
  const ink='#e9efed',muted='#9ab1b9',gold='#e7c479',cyan='#85d5e7';
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function loadImage(path,data){
    if(!path)return Promise.resolve(null);
    const live=window.WikiUpdates?.image(path)||path;if(live.startsWith('blob:')||live.startsWith('data:'))return inlineImage(live);
    const cache=data.portraitSizes?.[path]?portraitCache:imageCache,limit=cache===portraitCache?2:100;
    if(cache.has(path)){const image=cache.get(path);cache.delete(path);cache.set(path,image);return image;}
    const promise=new Promise((resolve,reject)=>{
      const source=data.assets[path];if(!source){reject(new Error('成图素材未收录：'+path));return;}
      const script=document.createElement('script');let done=false;
      const finish=(error,image)=>{if(done)return;done=true;clearTimeout(timer);script.remove();delete window.WIKI_POSTER_IMAGES?.[path];error?reject(error):resolve(image);};
      const timer=setTimeout(()=>finish(new Error('成图素材加载超时，请重试')),20000);
      script.src=source;script.onerror=()=>finish(new Error('成图素材文件缺失，请完整解压离线包'));
      script.onload=()=>{const url=window.WIKI_POSTER_IMAGES?.[path];if(!url){finish(new Error('成图素材格式不正确'));return;}
        const image=new Image();image.onload=()=>finish(null,image);image.onerror=()=>finish(new Error('成图素材无法解码'));image.src=url;};
      document.head.append(script);
    });
    cache.set(path,promise);promise.catch(()=>cache.delete(path));
    while(cache.size>limit)cache.delete(cache.keys().next().value);
    return promise;
  }
  const signatureFonts=new Map();
  function signatureFont(source,family,variable,label='签名字体',descriptors={}){
    if(!signatureFonts.has(family))signatureFonts.set(family,new Promise((resolve,reject)=>{
      const script=document.createElement('script');let timer,done=false;
      const finish=error=>{if(done)return;done=true;clearTimeout(timer);script.remove();if(error){signatureFonts.delete(family);reject(error);}else resolve();};
      timer=setTimeout(()=>finish(new Error(label+'加载超时，请重试')),45000);
      script.src=source;script.onerror=()=>finish(new Error(label+'文件缺失，请完整解压离线包'));
      script.onload=async()=>{try{const binary=atob(window[variable]||''),bytes=new Uint8Array(binary.length);delete window[variable];for(let i=0;i<binary.length;i++)bytes[i]=binary.charCodeAt(i);const face=await new FontFace(family,bytes,descriptors).load();if(done)return;document.fonts.add(face);finish();}catch(error){finish(new Error(label+'无法读取，请重试'));}};document.head.append(script);
    }));return signatureFonts.get(family);
  }
  function inlineImage(source){
    if(imageCache.has(source))return imageCache.get(source);
    const promise=new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>resolve(image);image.onerror=()=>reject(new Error('导入的角色字标无法读取'));image.src=source;});
    imageCache.set(source,promise);promise.catch(()=>imageCache.delete(source));return promise;
  }
  function portraitBounds(image){
    if(portraitBoundsCache.has(image))return portraitBoundsCache.get(image);
    // Sample once at a small size. Ignore almost transparent pixels and isolated
    // edge specks left by asset conversion, while keeping hats and tall hair.
    const ratio=Math.min(1,384/Math.max(image.width,image.height)),canvas=document.createElement('canvas');
    canvas.width=Math.max(1,Math.round(image.width*ratio));canvas.height=Math.max(1,Math.round(image.height*ratio));
    const c=canvas.getContext('2d',{willReadFrequently:true});c.drawImage(image,0,0,canvas.width,canvas.height);
    const pixels=c.getImageData(0,0,canvas.width,canvas.height).data,rows=new Uint16Array(canvas.height),cols=new Uint16Array(canvas.width);
    for(let y=0;y<canvas.height;y++)for(let x=0;x<canvas.width;x++)if(pixels[(y*canvas.width+x)*4+3]>=40){rows[y]++;cols[x]++;}
    const ys=Array.from(rows,(_,i)=>i).filter(i=>rows[i]>=Math.max(2,canvas.width*.01)),xs=Array.from(cols,(_,i)=>i).filter(i=>cols[i]>=Math.max(2,canvas.height*.01));
    const bounds=xs.length&&ys.length?{x:xs[0]*image.width/canvas.width,y:ys[0]*image.height/canvas.height,w:(xs.at(-1)-xs[0]+1)*image.width/canvas.width,h:(ys.at(-1)-ys[0]+1)*image.height/canvas.height}:{x:0,y:0,w:image.width,h:image.height};
    portraitBoundsCache.set(image,bounds);return bounds;
  }
  const importedFonts=new Map();
  async function authorFontFace(custom){
    if(!custom?.data)return null;
    if(!importedFonts.has(custom.data)){
      const promise=(async()=>{
        const binary=atob(custom.data.split(',')[1]),bytes=Uint8Array.from(binary,ch=>ch.charCodeAt(0));
        const digest=await crypto.subtle.digest('SHA-256',bytes),family='WikiAuthor'+Array.from(new Uint8Array(digest).slice(0,12),n=>n.toString(16).padStart(2,'0')).join('');
        const face=await new FontFace(family,bytes).load();document.fonts.add(face);return family;
      })();
      importedFonts.set(custom.data,promise);promise.catch(()=>importedFonts.delete(custom.data));
      while(importedFonts.size>4)importedFonts.delete(importedFonts.keys().next().value);
    }
    return importedFonts.get(custom.data);
  }
  function authorArtwork(c,state,image,family,x,y,w,h){
    if(state.authorMode==='image'&&image){
      c.save();const height=Math.min(h-8,72),bySize=Math.min(30,height*.46),gap=12;
      c.font=`700 ${bySize}px Arial, sans-serif`;c.textBaseline='alphabetic';
      const byW=c.measureText('by').width,scale=Math.max(.01,Math.min((w-byW-gap)/image.width,height/image.height)),iw=image.width*scale,ih=image.height*scale,left=x+w-iw-byW-gap;
      c.fillStyle='#fff8e5';c.strokeStyle='#071018';c.lineWidth=2;c.strokeText('by',left,y+h/2+bySize*.35);c.fillText('by',left,y+h/2+bySize*.35);
      c.drawImage(image,left+byW+gap,y+(h-ih)/2,iw,ih);c.restore();return;
    }
    if(!state.author.trim())return;
    if(state.authorFont==='signature'){signature(c,state.author,x,y,w,h);return;}
    c.save();c.bodyStyle=null;const face=state.authorFont==='serif'?'"WikiTitleNormal", serif':state.authorFont==='custom'&&family?`"${family}", "Microsoft YaHei", sans-serif`:'"Microsoft YaHei", sans-serif';
    c.font=`48px ${face}`;c.textBaseline='alphabetic';const m=c.measureText(state.author),left=Math.max(0,m.actualBoundingBoxLeft||0),right=Math.max(m.width,m.actualBoundingBoxRight||0),ascent=m.actualBoundingBoxAscent||48,descent=Math.max(0,m.actualBoundingBoxDescent||0),byW=43,gap=12,scale=Math.max(.01,Math.min(1,(w-byW-gap)/(left+right+4),(h-12)/(ascent+descent)));
    const ix=x+w-(left+right+4)*scale,iy=y+(h-(ascent+descent)*scale)/2+ascent*scale;
    c.font='700 28px Arial, sans-serif';c.fillStyle='#fff8e5';c.strokeStyle='#071018';c.lineWidth=2;c.strokeText('by',ix-byW-gap,y+h/2+10);c.fillText('by',ix-byW-gap,y+h/2+10);
    c.translate(ix+left*scale,iy);c.scale(scale,scale);c.font=`48px ${face}`;c.strokeText(state.author,0,0);c.fillText(state.author,0,0);c.restore();
  }
  function runs(html){
    const box=document.createElement('div');box.innerHTML=html||'';const result=[];
    function walk(node,color=ink){
      if(node.nodeType===3){result.push({text:node.textContent.replace(/[\t\r\n]+/g,' '),color});return;}
      if(node.nodeType!==1)return;
      if(node.tagName==='BR'){result.push({text:'\n',color});return;}
      const match=String(node.className||'').match(/wiki-color-(\w+)/);if(match)color=colors[match[1]]||color;
      for(const child of node.childNodes)walk(child,color);
      if(['DIV','P','LI'].includes(node.tagName))result.push({text:'\n',color});
    }
    for(const child of box.childNodes)walk(child);
    return result;
  }
  // Free text keeps its inline markup: **bold**, *italic* and {金|coloured}.
  const rich=(text,base)=>window.WikiInfographicRules.richRuns(text,base);
  // Free text may hold an HTML snippet from the notes editor; plain markup still works.
  function richHtml(html,base,size){
    const source=String(html??'');
    if(!/[<>]/.test(source))return rich(source,base);
    const doc=new DOMParser().parseFromString('<body>'+source,'text/html');
    const runs=[];
    const push=(text,bold,italic,color,scale)=>{if(text)runs.push({text,bold,italic,color,scale});};
    const walk=(node,bold,italic,color,scale)=>{
      for(const child of node.childNodes){
        if(child.nodeType===3){push(child.nodeValue.replace(/[\t\r\n]+/g,' '),bold,italic,color,scale);continue;}
        if(child.nodeType!==1)continue;
        const tag=child.tagName.toLowerCase();
        if(tag==='br'){push('\n',bold,italic,color,scale);continue;}
        const block=tag==='div'||tag==='p'||tag==='li';
        if(block&&runs.length&&!runs[runs.length-1].text.endsWith('\n'))push('\n',bold,italic,color,scale);
        let nextColor=color,nextScale=scale,style=child.getAttribute('style')||'';
        const colorMatch=/(?:^|;)\s*color\s*:\s*([^;]+)/i.exec(style);
        if(colorMatch)nextColor=colorMatch[1].trim();
        const sizeMatch=/(?:^|;)\s*font-size\s*:\s*(\d+(?:\.\d+)?)px/i.exec(style);
        if(sizeMatch)nextScale=Math.max(.6,Math.min(2.4,Number(sizeMatch[1])/(size||15)));
        const weightMatch=/(?:^|;)\s*font-weight\s*:\s*([^;]+)/i.exec(style),slantMatch=/(?:^|;)\s*font-style\s*:\s*([^;]+)/i.exec(style);
        const heavy=weightMatch&&(weightMatch[1].trim()==='bold'||Number(weightMatch[1].trim())>=600);
        walk(child,bold||tag==='b'||tag==='strong'||heavy,italic||tag==='i'||tag==='em'||(slantMatch&&/italic/i.test(slantMatch[1])),nextColor,nextScale);
        if(block&&runs.length&&!runs[runs.length-1].text.endsWith('\n'))push('\n',bold,italic,color,scale);
      }
    };
    walk(doc.body,false,false,base,1);
    return runs.length?runs:rich(source.replace(/<[^>]*>/g,''),base);
  }
  const notesParts=(html,base,size)=>richHtml(html,base,size);
  function styledText(c,...args){const style=c.bodyStyle;if(style?.bodyOutlineWidth&&!/WikiSignature|Arial/.test(c.font)){c.save();c.strokeStyle=style.bodyOutlineColor;c.lineWidth=style.bodyOutlineWidth*2;c.lineJoin='round';c.strokeText(...args);c.restore();}c.fillText(...args);}
  function font(c,size,weight=400,italic=null){const style=c.bodyStyle;c.font=`${(italic===null?!!style?.bodyItalic:!!italic)?'italic ':''}${style?.bodyBold||weight>=600?Math.max(600,weight):weight} ${size}px ${style?.bodyFont==='serif'?'"WikiTitleNormal", serif':'"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif'}`;c.textBaseline='top';}
  // A run may carry its own font size (from pasted HTML); lines grow to the tallest one.
  const runScale=part=>part.scale||1;
  function wrap(c,parts,width,size,lineHeight=size*1.45){
    font(c,size);const lines=[[]];let used=0;const scales=[1];
    const next=()=>{lines.push([]);scales.push(1);used=0;};
    const grow=scale=>{scales[scales.length-1]=Math.max(scales[scales.length-1],scale);};
    for(const part of parts){const scale=runScale(part);font(c,size*scale,part.bold?700:400,part.italic);for(const unit of part.text.match(/[A-Za-z0-9][A-Za-z0-9.%+_:/-]*|[\s\S]/gu)||[])for(const char of (c.measureText(unit).width>width?Array.from(unit):[unit])){
      if(char==='\n'){next();continue;}
      const w=c.measureText(char).width;
      if(used+w>width&&used>0){
        const previousLine=lines[lines.length-1],previous=previousLine[previousLine.length-1];
        const closing=/^[，。、！？；：）】》」』〕〉,.;:!?)]$/.test(char);
        const tail=closing&&previous?(previous.text.match(/[A-Za-z0-9][A-Za-z0-9.%+_:/-]*$|.$/u)||[])[0]:'';
        if(tail&&c.measureText(tail).width+w<=width){
          const tailWidth=c.measureText(tail).width,color=previous.color;
          previous.text=previous.text.slice(0,-tail.length);previous.width-=tailWidth;if(!previous.text)previousLine.pop();
          next();grow(scale);lines[lines.length-1].push({text:tail,width:tailWidth,color,scale});used=tailWidth;
        }else next();
      }
      if(char===' '&&used===0)continue;
      grow(scale);
      const line=lines[lines.length-1],last=line[line.length-1];
      const same=last&&last.color===part.color&&!!last.bold===!!part.bold&&!!last.italic===!!part.italic&&runScale(last)===scale;
      if(same){last.text+=char;last.width+=w;}else line.push({text:char,width:w,color:part.color,bold:!!part.bold,italic:!!part.italic,scale});used+=w;
      }
    }
    while(lines.length>1&&!lines[lines.length-1].length)lines.pop();
    const heights=lines.map((line,index)=>lineHeight*scales[index]);
    return {lines,size,lineHeight,heights,height:heights.reduce((sum,h)=>sum+h,0)};
  }
  function paintText(c,layout,x,y){font(c,layout.size);layout.lines.forEach((line,index)=>{let left=x;for(const p of line){c.fillStyle=p.color;font(c,layout.size*runScale(p),p.bold?700:400,p.italic);styledText(c,p.text,left,y);left+=p.width;}font(c,layout.size);y+=layout.heights?.[index]??layout.lineHeight;});return y;}
  function plain(c,text,x,y,width,size=22,color=ink,weight=400){
    const layout=wrap(c,[{text:String(text??''),color}],width,size);font(c,size,weight);
    layout.lines.forEach((line,index)=>{let left=x;for(const p of line){c.fillStyle=p.color;styledText(c,p.text,left,y);left+=p.width;}y+=layout.heights?.[index]??layout.lineHeight;});return layout.height;
  }
  function line(c,x1,y1,x2,y2,color='#345460',width=2,dash=[]){c.beginPath();c.strokeStyle=color;c.lineWidth=width;c.setLineDash(dash);c.moveTo(x1,y1);c.lineTo(x2,y2);c.stroke();c.setLineDash([]);}
  function round(c,x,y,w,h,r=18){c.beginPath();c.moveTo(x+r,y);c.arcTo(x+w,y,x+w,y+h,r);c.arcTo(x+w,y+h,x,y+h,r);c.arcTo(x,y+h,x,y,r);c.arcTo(x,y,x+w,y,r);c.closePath();}
  function paintPanel(c,x,y,w,h,opacity){round(c,x,y,w,h,Math.max(2,Math.min(18,w/2,h/2)));c.fillStyle=`rgba(6,17,25,${opacity})`;c.fill();c.strokeStyle='#31545e';c.lineWidth=2;c.stroke();}
  function title(c,label,x,y,note=''){font(c,25,700);c.fillStyle=cyan;styledText(c,label,x,y);if(note){font(c,17);c.fillStyle=muted;styledText(c,note,x+c.measureText(label).width+68,y+7);}}
  function fit(c,text,x,y,width,size=60,color=cyan){while(size>8){font(c,size,700);if(c.measureText(text).width<=width)break;size-=2;}c.fillStyle=color;styledText(c,text,x,y);}
  function contain(c,image,x,y,w,h){if(!image)return;const scale=Math.min(w/image.width,h/image.height);c.drawImage(image,x+(w-image.width*scale)/2,y+(h-image.height*scale)/2,image.width*scale,image.height*scale);}
  function labelLayout(c,text,w,color=ink,size=19,maxLines=2){
    let layout=wrap(c,[{text:String(text||''),color}],w,size,size*1.3);
    while(layout.lines.length>maxLines&&size>8){size--;layout=wrap(c,[{text:String(text||''),color}],w,size,size*1.3);}
    return layout;
  }
  function smallLabel(c,text,x,y,w,color=ink,size=19,maxLines=2){
    const layout=labelLayout(c,text,w,color,size,maxLines);paintCentered(c,layout,x+w/2,y);return layout.height;
  }
  function skillIcon(c,image,cx,cy,size,mark='',placeholder='＋',dim=false,width=3){
    const r=size/2;c.save();c.beginPath();c.arc(cx,cy,r,0,Math.PI*2);c.clip();c.fillStyle='#172a36';c.fillRect(cx-r,cy-r,size,size);
    if(image){if(dim)c.filter='grayscale(1) brightness(.5)';contain(c,image,cx-r+3,cy-r+3,size-6,size-6);c.filter='none';}
    else{font(c,size*.3);c.fillStyle=muted;c.textAlign='center';styledText(c,placeholder,cx,cy-size*.17);c.textAlign='left';}
    c.restore();c.save();c.strokeStyle=mark==='required'?gold:mark==='optional'?cyan:'#38525f';c.lineWidth=mark?width:2;
    if(mark==='optional'){
      const count=Math.max(12,Math.round(2*Math.PI*(r+4)/(width*2.8)));c.fillStyle=cyan;
      for(let i=0;i<count;i++){const angle=-Math.PI/2+i*2*Math.PI/count;c.beginPath();c.arc(cx+Math.cos(angle)*(r+4),cy+Math.sin(angle)*(r+4),width/2,0,Math.PI*2);c.fill();}
    }else{c.beginPath();c.arc(cx,cy,r+4,0,Math.PI*2);c.stroke();}c.restore();
  }
  function paintCentered(c,layout,cx,y){
    font(c,layout.size);layout.lines.forEach((line,index)=>{let x=cx-line.reduce((sum,part)=>sum+part.width,0)/2;for(const part of line){c.fillStyle=part.color;font(c,layout.size*runScale(part),part.bold?700:400,part.italic);styledText(c,part.text,x,y);x+=part.width;}font(c,layout.size);y+=layout.heights?.[index]??layout.lineHeight;});return y;
  }
  // One radar chart: grid, axis labels and the scored polygon. Used by the built-in
  // rating block and by the custom radar block.
  function radarChartArt(c,chart,cx,cy,rr,left,right,labelSize=14){
    const sides=Math.max(3,chart.axes.length),angle=i=>-Math.PI/2+i*2*Math.PI/sides;
    const max=chart.max||5,limitOf=axis=>axis.max||max;
    // A chart may count in its own units or show how far each axis reaches.
    const read=axis=>axis.name+(chart.rated?' '+(chart.unit==='percent'?Math.round((axis.score||0)/limitOf(axis)*100)+'%':String(axis.score)):' —');
    const point=(i,radius)=>[cx+Math.cos(angle(i))*radius,cy+Math.sin(angle(i))*radius];
    for(let n=1;n<=5;n++){c.beginPath();for(let i=0;i<sides;i++){const [px,py]=point(i,rr*n/5);i?c.lineTo(px,py):c.moveTo(px,py);}c.closePath();c.strokeStyle=n===5?'#67848d':'#324f59';c.lineWidth=1;c.stroke();}
    for(let i=0;i<sides;i++){
      const [px,py]=point(i,rr);line(c,cx,cy,px,py,'#36535d',1);
      const [lx,ly]=point(i,rr+22),cos=Math.cos(angle(i));
      let align=Math.abs(cos)<.25?'center':cos>0?'left':'right',labelX=lx;
      if(labelX<left){labelX=left;align='left';}
      if(labelX>right){labelX=right;align='right';}
      font(c,labelSize,600);c.fillStyle=ink;c.textAlign=align;
      styledText(c,read(chart.axes[i]),labelX,ly-7);c.textAlign='left';
    }
    if(chart.rated&&chart.axes.some(axis=>axis.score)){
      c.beginPath();
      for(let i=0;i<sides;i++){const limit=limitOf(chart.axes[i]);const [px,py]=point(i,rr*Math.max(0,Math.min(limit,chart.axes[i].score||0))/limit);i?c.lineTo(px,py):c.moveTo(px,py);}
      c.closePath();c.fillStyle='rgba(114,207,224,.28)';c.fill();c.strokeStyle=cyan;c.lineWidth=2;c.stroke();
    }
  }
  function signature(c,name,x,y,width,height=78){
    c.save();c.translate(x,y);
    // Shape Latin words together: per-letter rotations and fake joins break cursive ligatures.
    const units=(name.match(/[\p{Script=Latin}\p{M}0-9]+(?:[’'._-][\p{Script=Latin}\p{M}0-9]+)*|[\s\S]/gu)||[]).map(text=>{
      const latin=/[\p{Script=Latin}0-9\s.,'’_-]/u.test(text),face=latin?'600 60px "WikiSignatureLatin", cursive':'62px "WikiSignature", "KaiTi", cursive';
      c.font=face;const measured=c.measureText(text);return {text,latin,face,width:measured.width*(latin?1:.88),left:measured.actualBoundingBoxLeft||0,right:measured.actualBoundingBoxRight||measured.width};
    });
    const byWidth=58,textWidth=units.reduce((sum,unit)=>sum+unit.width,0),last=units[units.length-1],tail=Math.max(14,last?last.right-last.width+10:0);
    const scale=Math.min(1,width/(textWidth+byWidth+tail),height/85);c.translate(width-(textWidth+byWidth+tail)*scale,0);c.scale(scale,scale);
    const start=byWidth,baseline=61;
    c.lineCap='round';c.lineJoin='round';c.shadowColor='#03090d';c.shadowBlur=4;c.shadowOffsetY=2;
    // Thin joining strokes run behind the brush lettering, with a rising flourish.
    let cursor=start;
    for(let i=0;i<units.length-1;i++){
      const current=units[i],next=units[i+1],end=cursor+current.width;
      if(!current.latin&&!next.latin&&!/\s/.test(current.text+next.text)){
        c.beginPath();c.moveTo(cursor+current.width*.73,baseline-8);c.bezierCurveTo(end+4,baseline+1,end+next.width*.16,baseline-20,end+next.width*.30,baseline-17);
        c.strokeStyle='#02080d';c.lineWidth=5;c.stroke();c.strokeStyle='#f9f3df';c.lineWidth=1.65;c.stroke();
      }cursor=end;
    }
    cursor=start;c.textBaseline='alphabetic';
    for(let i=0;i<units.length;i++){
      const unit=units[i];c.save();c.translate(cursor,baseline-(unit.latin?0:(i%3)*1.7));if(!unit.latin)c.rotate((i%2?-.025:.012));c.font=unit.face;c.strokeStyle='#02080d';c.lineWidth=unit.latin?2.5:4;c.strokeText(unit.text,0,0);c.fillStyle='#fff8e5';styledText(c,unit.text,0,0);c.restore();cursor+=unit.width;
    }
    c.font='700 32px Arial, sans-serif';c.strokeStyle='#02080d';c.lineWidth=2;c.strokeText('by',4,61);c.fillStyle='#fff8e5';styledText(c,'by',4,61);
    c.shadowBlur=0;c.shadowOffsetY=0;
    if(units.some(unit=>unit.latin&&/\S/.test(unit.text))){
      c.beginPath();c.moveTo(20,82);c.quadraticCurveTo((start+cursor)/2,77,cursor-3,81);c.strokeStyle=gold;c.lineWidth=1.2;c.stroke();
    }else{
      c.beginPath();c.moveTo(14,78);c.bezierCurveTo(start+40,53,cursor+16,87,cursor+5,58);c.bezierCurveTo(cursor-6,47,cursor-30,73,cursor-9,78);c.strokeStyle='#03090d';c.lineWidth=6;c.stroke();c.strokeStyle='#fff6dc';c.lineWidth=2;c.stroke();
      c.beginPath();c.moveTo(start+12,83);c.quadraticCurveTo(cursor*.65,69,cursor-24,86);c.strokeStyle=gold;c.lineWidth=1.4;c.stroke();
    }c.restore();
  }

  function effectColumns(c,parts,width,size){
    const groups=[[]];
    for(const part of parts)part.text.split('\n').forEach((text,i)=>{if(i)groups.push([]);if(text)groups[groups.length-1].push({...part,text});});
    const paragraphs=groups.filter(g=>g.length),join=groups=>groups.flatMap((g,i)=>i?[{text:'\n',color:ink},...g]:g);
    const full=wrap(c,parts,width,size,size*1.36),columnWidth=(width-28)/2;
    let result={parts:[parts],width,height:full.height};
    if(paragraphs.length<4)return result;
    for(let split=1;split<paragraphs.length;split++){
      const columns=[join(paragraphs.slice(0,split)),join(paragraphs.slice(split))],height=Math.max(...columns.map(p=>wrap(c,p,columnWidth,size,size*1.36).height));
      if(height+20<full.height&&height<result.height)result={parts:columns,width:columnWidth,height};
    }
    return result;
  }
  // Blocks keep their font size when resized: spacing tightens first, glyphs only shrink as a last resort.
  function fitted(c,parts,width,height,size=18){
    let layout=wrap(c,parts,width,size,size*1.36);
    if(layout.height<=height){layout.scale=1;return layout;}
    for(const ratio of [1.28,1.2,1.12,1.04]){
      const tight=wrap(c,parts,width,size,size*ratio);
      if(tight.height<=height){tight.scale=1;return tight;}
    }
    do{layout=wrap(c,parts,width,size,size*1.36);if(layout.height<=height||size<=7)break;size-=.5;}while(true);
    layout.scale=Math.min(1,height/layout.height);return layout;
  }
  function textBox(c,layout,x,y){c.save();c.translate(x,y);c.scale(1,layout.scale||1);paintText(c,layout,0,0);c.restore();}
  const titleCache=new Map();
  function titleText(model,state){return (state.titleName?.trim()||model.character.name).normalize('NFC');}
  function titleMissing(text,data){return [...new Set(Array.from(text).filter(ch=>! /\s/.test(ch)&&!data.nameFont.ranges.some(([a,b])=>ch.codePointAt(0)>=a&&ch.codePointAt(0)<=b)))];}
  function generatedTitle(name,color,maxWidth,height,density,font='serif',style={}){
    const family=(style.titleItalic?'italic ':'')+(font==='sans'?`${style.titleBold?'900':'700'} 400px "Microsoft YaHei", "Noto Sans CJK SC", "WikiTitleNormal", sans-serif`:`${style.titleBold?'700':'400'} 400px "WikiTitleNormal", serif`);
    const scratch=document.createElement('canvas'),measure=scratch.getContext('2d');measure.font=family;const metrics=measure.measureText(name);
    const pad=Math.max(height*.035,(style.titleOutlineWidth||0)+3),inkWidth=Math.max(1,metrics.actualBoundingBoxLeft+metrics.actualBoundingBoxRight),inkHeight=Math.max(1,metrics.actualBoundingBoxAscent+metrics.actualBoundingBoxDescent);
    const ratio=Math.min((maxWidth-2*pad)/inkWidth,(height-2*pad)/inkHeight),canvas=document.createElement('canvas');
    canvas.width=Math.ceil((inkWidth*ratio+2*pad)*density);canvas.height=Math.ceil((inkHeight*ratio+2*pad)*density);
    const c=canvas.getContext('2d');c.font=family.replace('400px',400*ratio*density+'px');c.fillStyle=color;c.textBaseline='alphabetic';
    c.shadowColor='#05090cbc';c.shadowBlur=style.titleShadow===false?0:2*density;c.shadowOffsetY=style.titleShadow===false?0:density;
    if(style.titleOutlineWidth){c.strokeStyle=style.titleOutlineColor||'#08121b';c.lineJoin='round';c.lineWidth=style.titleOutlineWidth*2*density;c.strokeText(name,(pad+metrics.actualBoundingBoxLeft*ratio)*density,(pad+metrics.actualBoundingBoxAscent*ratio)*density);}
    styledText(c,name,(pad+metrics.actualBoundingBoxLeft*ratio)*density,(pad+metrics.actualBoundingBoxAscent*ratio)*density);return canvas;
  }
  async function titleArtwork(model,state,data,{maxWidth=695,height=143,density=2}={}){
    maxWidth*=state.titleScale??1;height*=state.titleScale??1;
    const name=titleText(model,state),mode=state.titleMode||(state.customTitle?'image':data.referenceTitles?.[model.character.id]&&name===model.character.name?'reference':'text');
    const reference=mode==='reference'&&name===model.character.name?data.referenceTitles?.[model.character.id]:null;
    const uploaded=mode==='image'?state.customTitle:null;
    const key=[name,state.titleColor,mode,state.titleFont,state.titleImageTint,state.titleItalic,state.titleBold,state.titleScale,state.titleOutlineWidth,state.titleOutlineColor,state.titleShadow,uploaded||reference||data.nameFont.version,maxWidth,height,density].join('|');
    if(titleCache.has(key))return titleCache.get(key);
    const image=uploaded?await inlineImage(uploaded):reference?await loadImage(reference,data):null;
    let canvas,missing=[];
    if(image){const ratio=Math.min(maxWidth/image.width,height/image.height);canvas=document.createElement('canvas');canvas.width=Math.ceil(image.width*ratio*density);canvas.height=Math.ceil(image.height*ratio*density);referenceName(canvas.getContext('2d'),image,uploaded&&!state.titleImageTint?'#ef9b73':state.titleColor,0,0,canvas.width,canvas.height,state.titleShadow!==false);}
    else{await signatureFont(data.nameFont.script,'WikiTitleNormal','WIKI_NORMAL_TITLE_FONT','题名字体');missing=titleMissing(name,data);canvas=generatedTitle(name,state.titleColor,maxWidth,height,density,state.titleFont,state);}
    if(image&&state.titleOutlineWidth){
      const radius=state.titleOutlineWidth*density,pad=Math.ceil(radius+2),out=document.createElement('canvas');out.width=canvas.width+pad*2;out.height=canvas.height+pad*2;const o=out.getContext('2d'),mask=document.createElement('canvas');mask.width=canvas.width;mask.height=canvas.height;const m=mask.getContext('2d');m.drawImage(canvas,0,0);m.globalCompositeOperation='source-in';m.fillStyle=state.titleOutlineColor||'#08121b';m.fillRect(0,0,mask.width,mask.height);
      for(let i=0;i<32;i++){const a=i*Math.PI/16;o.drawImage(mask,pad+Math.cos(a)*radius,pad+Math.sin(a)*radius);}o.drawImage(canvas,pad,pad);canvas=out;
    }
    const shrink=Math.min(1,maxWidth*density/canvas.width,height*density/canvas.height);
    if(shrink<1){const fitted=document.createElement('canvas');fitted.width=Math.max(1,Math.floor(canvas.width*shrink));fitted.height=Math.max(1,Math.floor(canvas.height*shrink));fitted.getContext('2d').drawImage(canvas,0,0,fitted.width,fitted.height);canvas=fitted;}
    const result={canvas,width:canvas.width/density,height:canvas.height/density,missing,name,source:image?'image':'font'};
    titleCache.set(key,result);while(titleCache.size>8)titleCache.delete(titleCache.keys().next().value);return result;
  }
  function referenceName(c,image,color,x,y,maxWidth,height,shadow=true){
    const scale=Math.min(maxWidth/image.width,height/image.height),w=image.width*scale,h=image.height*scale;
    const tinted=document.createElement('canvas');tinted.width=image.width;tinted.height=image.height;const t=tinted.getContext('2d');t.drawImage(image,0,0);
    if(color!=='#ef9b73'){t.globalCompositeOperation='color';t.fillStyle=color;t.fillRect(0,0,tinted.width,tinted.height);t.globalCompositeOperation='destination-in';t.drawImage(image,0,0);}
    c.save();c.shadowColor='#070b10';c.shadowBlur=shadow?3:0;c.shadowOffsetY=shadow?2:0;c.drawImage(tinted,x,y,w,h);c.restore();return w;
  }
  function branch(c,center,cy,cx,mark,initial,state){
    if(state.branchLength===0)return;
    const ends=window.WikiInfographicRules.branchEnds(center,cx,state.markWidth??3,state.branchLength??100);
    line(c,ends.start,cy,ends.end,cy,mark==='required'?gold:mark==='optional'?cyan:initial?'#6b786d':'#3d4b53',state.branchWidth??1.5,mark==='optional'?[3,4]:[]);
  }
  function gildedPanel(c,x,y,w,h,opacity,decoration){
    if(decoration?.style==='plain'){paintPanel(c,x,y,w,h,opacity);return;}
    const strength=decoration?.intensity??.65,cut=Math.min(10,w/8,h/8);
    const frame=(inset)=>{const l=x+inset,t=y+inset,r=x+w-inset,b=y+h-inset;c.beginPath();c.moveTo(l+cut,t);c.lineTo(r-cut,t);c.lineTo(r,t+cut);c.lineTo(r,b-cut);c.lineTo(r-cut,b);c.lineTo(l+cut,b);c.lineTo(l,b-cut);c.lineTo(l,t+cut);c.closePath();};
    c.save();frame(1);c.fillStyle=`rgba(5,15,22,${opacity})`;c.fill();c.strokeStyle=`rgba(201,171,104,${.35+strength*.45})`;c.lineWidth=1.2;c.stroke();
    frame(5);c.strokeStyle=`rgba(165,130,65,${strength*.3})`;c.lineWidth=.7;c.stroke();
    if(strength>0)for(const [px,py,flipX,flipY] of [[x+7,y+7,1,1],[x+w-7,y+7,-1,1],[x+7,y+h-7,1,-1],[x+w-7,y+h-7,-1,-1]]){c.save();c.translate(px,py);c.scale(flipX,flipY);c.strokeStyle=`rgba(239,210,139,${strength})`;c.lineWidth=.8;c.beginPath();c.moveTo(0,16);c.lineTo(0,4);c.lineTo(4,0);c.lineTo(24,0);c.stroke();c.fillStyle=`rgba(220,186,110,${strength*.8})`;c.beginPath();c.moveTo(2,2);c.lineTo(8,2);c.lineTo(2,8);c.fill();c.restore();}
    c.restore();
  }
  function posterOrnaments(c,W,H,decoration){
    if(decoration?.style==='plain')return;const strength=decoration?.intensity??.65;if(!strength)return;
    c.save();c.strokeStyle=`rgba(205,170,98,${strength*.65})`;c.lineWidth=1;c.strokeRect(9,9,W-18,H-18);c.strokeStyle=`rgba(205,170,98,${strength*.25})`;c.strokeRect(15,15,W-30,H-30);
    for(const [x,y,sx,sy] of [[19,19,1,1],[W-19,19,-1,1],[19,H-19,1,-1],[W-19,H-19,-1,-1]]){c.save();c.translate(x,y);c.scale(sx,sy);c.strokeStyle=`rgba(240,207,129,${strength})`;c.beginPath();c.moveTo(0,55);c.lineTo(0,15);c.lineTo(15,0);c.lineTo(82,0);c.stroke();c.beginPath();c.moveTo(9,30);c.lineTo(9,13);c.lineTo(13,9);c.lineTo(42,9);c.stroke();c.restore();}
    c.globalAlpha=strength*.22;c.strokeStyle='#d7b36b';c.lineWidth=.7;
    for(const r of [84,95,146,153]){c.beginPath();c.arc(95,100,r,-Math.PI*.75,Math.PI*.75);c.stroke();}
    for(let i=0;i<16;i++){const a=-1.8+i*.23;const px=95+Math.cos(a)*153,py=100+Math.sin(a)*153;c.beginPath();c.moveTo(px,py);c.lineTo(95+Math.cos(a)*161,100+Math.sin(a)*161);c.stroke();}
    c.restore();
  }
  function gearContent(c,state,w,equipmentMap,tarotMap){
    // Icon size follows the editor setting; the column pitch still keeps them apart.
    const gearCols=Math.max(1,Math.min(8,Math.round((w-70)/108)||1)),gearPitch=Math.min(108,(w-70)/gearCols),gearCell=Math.min(92,gearPitch-6),gearIconSize=Math.min(state.gearIconSize||40,gearPitch-6);
    const gearRows=[['weapons','武器',equipmentMap],['accessories','装具',equipmentMap],['tarot','塔罗',tarotMap]].map(([key,label,map])=>{
      const items=state[key].map((id,j)=>{const item=map.get(id),name=labelLayout(c,item?.name||'待选择',gearCell,item?ink:muted,12.5,2),caption=state.gearNotes[key][j]?wrap(c,[{text:state.gearNotes[key][j],color:colors.red}],gearCell,12.5,16):null;return {item,name,caption,bottom:gearIconSize+4+name.height+(caption?1+caption.height:0)};});
      const cellH=Math.max(...items.map(item=>item.bottom))+8,contentH=cellH*Math.ceil(items.length/gearCols),group=state.groupNotes[key]?wrap(c,[{text:state.groupNotes[key],color:colors.red}],w-40,14,18):null;
      return {label,items,cellH,group,groupY:contentH+2,height:contentH+(group?2+group.height:0)+6};
    });
    return {gearCols,gearPitch,gearCell,gearIconSize,gearRows};
  }
  function posterFrames(c,state,W,H,traitParts,weaponParts,engravings,equipmentMap,tarotMap){
    const portrait=H>W,spotlight=state.composition==='spotlight',information=state.composition==='information',frames={},m=24,gap=14;
    if(!portrait&&!spotlight&&!information)return {frames,hero:null,minHeight:0};
    let minBody=0;
    const flow=(items,x,y,w,h)=>{minBody=Math.max(minBody,items.reduce((n,item)=>n+item[1],0)+gap*(items.length-1));const free=Math.max(30,h-gap*(items.length-1)),sum=items.reduce((n,item)=>n+item[1],0),flex=items.filter(([key])=>['tree','trait','gear','notes','loadoutNotes'].includes(key)).length;let py=y;for(const [key,weight] of items){const rh=free<=sum||!flex?free*weight/sum:weight+(['tree','trait','gear','notes','loadoutNotes'].includes(key)?(free-sum)/flex:0);frames[key]={x,y:py,w,h:rh};py+=rh+gap;}};
    const traitWeight=w=>{const columns=effectColumns(c,traitParts,w-36,20);return Math.max(145,Math.max(...columns.parts.map(parts=>wrap(c,parts,columns.width,14,19.04).height))+61);};
    const weaponWeight=w=>Math.max(115,wrap(c,weaponParts,Math.max(40,w-124),14,19.04).height+57);
    const gearWeight=w=>48+gearContent(c,state,w,equipmentMap,tarotMap).gearRows.reduce((n,row)=>n+row.height,0);
    const engravingWeight=w=>{
      if(!engravings.length)return 100;
      const maxCols=Math.max(1,Math.floor((w-32)/180)),cols=Math.min(engravings.length<=3?engravings.length:Math.ceil(engravings.length/2),maxCols),rows=Math.ceil(engravings.length/cols),cellW=(w-32)/cols;
      return 51+rows*(38+Math.max(...engravings.map(e=>wrap(c,[...runs(e.description),...(e.note?[{text:'\n'+e.note,color:ink}]:[])],cellW-14,14,19.04).height)));
    };
    const textWeight=(text,w)=>Math.max(68,wrap(c,[{text:text||'',color:ink}],w-32,14,19.04).height+52);
    const buildWeight=w=>{const cols=Math.max(1,Math.min(Math.floor((w-24)/330),Math.ceil(state.loadouts.length/4)));return 48+Math.ceil(state.loadouts.length/cols)*82;};
    let hero=null,informationHeader=0;
    const hasAuthor=state.author.trim()||state.authorMode==='image'&&state.authorImage;
    const radarCharts=window.WikiInfographicRules.radarCharts(state.radarCharts),radarItems=radarCharts.length?[['radar',210]]:[];
    if(information){
      const header=portrait?270:Math.max(186,H*.17),bodyY=header+14,bodyH=H-bodyY-40,usable=W-2*m-2*gap,leftW=usable*(portrait?0.29:0.22),centerW=usable*(portrait?0.40:0.46),rightW=usable-leftW-centerW,cx=m+leftW+gap,rx=cx+centerW+gap;
      informationHeader=header;
      flow([['tree',850],['engravings',engravingWeight(leftW)]],m,bodyY,leftW,bodyH);
      flow([['trait',traitWeight(centerW)],['exclusive',weaponWeight(centerW)],['loadouts',buildWeight(centerW)],...(state.loadoutCommentary.enabled?[['loadoutNotes',textWeight(state.loadoutCommentary.text,centerW)]]:[]),['notes',textWeight(state.notes,centerW)]],cx,bodyY,centerW,bodyH);
      flow([['scores',260],...radarItems,['gear',gearWeight(rightW)],['stats',245],['author',hasAuthor?95:55]],rx,bodyY,rightW,bodyH);
      frames.topText={x:portrait?W*.57:1000,y:header-38,w:portrait?W*.40:460,h:30};
      if(portrait){
        frames.logo={x:m,y:20,w:110,h:110};frames.title={x:150,y:12,w:W*.43,h:135};frames.subtitle={x:m,y:153,w:W*.68,h:65};frames.cv={x:m,y:header-38,w:W*.52,h:25};
        frames.sprite={x:W-205,y:16,w:180,h:190};frames.badges={x:W-420,y:36,w:190,h:60};frames.role={x:W-420,y:112,w:190,h:80};
      }
    }else if(portrait){
      const header=Math.min(H*.32,spotlight?570:390),bodyY=header+18,bodyH=Math.max(500,H-bodyY-45),usable=W-2*m-2*gap,leftW=usable*.29,centerW=usable*.40,rightW=usable-leftW-centerW,cx=m+leftW+gap,rx=cx+centerW+gap;
      hero={x:W*.51,y:15,w:W*.47,h:header,focusScale:3,focusY:header*.4};
      frames.logo={x:m,y:28,w:100,h:100};frames.title={x:142,y:25,w:W*.53-142,h:150};frames.subtitle={x:m+10,y:183,w:W*.57-32,h:65};frames.cv={x:m+10,y:header-64,w:W*.58,h:25};frames.topText={x:m+10,y:header-33,w:W*.58,h:25};
      frames.sprite={x:W-215,y:20,w:180,h:215};frames.badges={x:W-238,y:244,w:210,h:55};frames.role={x:W-305,y:305,w:280,h:50};
      flow([['tree',850],['engravings',engravingWeight(leftW)]],m,bodyY,leftW,bodyH);
      flow([['trait',traitWeight(centerW)],['exclusive',weaponWeight(centerW)],['loadouts',buildWeight(centerW)],...(state.loadoutCommentary.enabled?[['loadoutNotes',textWeight(state.loadoutCommentary.text,centerW)]]:[]),['notes',textWeight(state.notes,centerW)]],cx,bodyY,centerW,bodyH);
      flow([['scores',310],...radarItems,['gear',gearWeight(rightW)],['stats',245],['author',hasAuthor?95:55]],rx,bodyY,rightW,bodyH);
    }else{
      const bodyY=Math.max(186,H*.17),bodyH=H-bodyY-40,usable=W-2*m-3*gap,treeW=usable*.17,infoW=usable*.30,heroW=usable*.30,rightW=usable-treeW-infoW-heroW,ix=m+treeW+gap,hx=ix+infoW+gap,rx=hx+heroW+gap;
      hero={x:hx,y:0,w:heroW,h:H,focusScale:1.65,focusY:-H*.10,focusTop:bodyY-20};frames.topText={x:Math.min(570,ix+infoW*.3),y:bodyY-44,w:ix+infoW-Math.min(570,ix+infoW*.3),h:32};minBody=Math.max(minBody,850);frames.tree={x:m,y:bodyY,w:treeW,h:bodyH};
      flow([['trait',traitWeight(infoW)],['exclusive',weaponWeight(infoW)],['loadouts',buildWeight(infoW)],...(state.loadoutCommentary.enabled?[['loadoutNotes',textWeight(state.loadoutCommentary.text,infoW)]]:[]),['engravings',engravingWeight(infoW)]],ix,bodyY,infoW,bodyH);
      flow([['scores',240],...radarItems,['gear',gearWeight(rightW)],['stats',235],['notes',textWeight(state.notes,rightW)],['author',hasAuthor?85:20]],rx,bodyY,rightW,bodyH);
    }
    frames.date={x:W-624,y:H-29,w:600,h:24};
    return {frames,hero,minHeight:information?(portrait?minBody+informationHeader+54:Math.max(minBody+240,(minBody+54)/.83)):portrait?minBody+Math.min(H*.32,spotlight?570:390)+63:Math.max(minBody+226,(minBody+40)/.83)};
  }
  async function draw(model,state,data,exclusive){
    const outputSize=window.WikiInfographicRules.canvasSize(state.canvas),W=outputSize.height>outputSize.width?1280:1920,outputScale=outputSize.width/W,H=outputSize.height/outputScale;
    state={...state,layout:Object.fromEntries(Object.entries(state.layout||{}).map(([key,r])=>[key,Object.fromEntries(Object.entries(r).map(([axis,n])=>[axis,n/outputScale]))])),background:{...state.background,x:state.background.x/outputScale,y:state.background.y/outputScale},topTextX:state.topTextX/outputScale,topTextY:state.topTextY/outputScale};
    const panel=(c,x,y,w,h)=>gildedPanel(c,x,y,w,h,state.panelOpacity??.92,state.decoration);
    const icon=(c,image,cx,cy,size,mark='',placeholder='＋',dim=false)=>skillIcon(c,image,cx,cy,size,mark,placeholder,dim,state.markWidth??3);
    const margin=24,treeW=330,x=370,right=1526,top=186,bottom=1056;
    const character=model.character,skillMap=new Map(model.skills.map(s=>[s.id,s]));
    const equipmentMap=new Map(model.equipment.map(e=>[e.id,e])),tarotMap=new Map(data.tarot.map(e=>[e.id,e]));
    const engravings=state.engravings.map(item=>({...data.engravings.find(e=>e.id===item.id),note:item.note})).filter(e=>e.id);
    // A uploaded background wins over the archived portraits; it is stored with the draft.
    const customArt=state.background.portrait==='custom'?state.backgroundImage:null;
    const portrait=customArt||model.character.portraits?.find(p=>p.key===state.background.portrait)?.src||model.portrait,liberations=model.liberations||[];
    const referenceTitle=!state.titleName?.trim()||titleText(model,state)===character.name?data.referenceTitles?.[character.id]:null;
    const paths=new Set([data.logo,portrait,referenceTitle,character.sprite,...model.badges.flatMap(b=>[b.background,b.image]),...Object.values(data.statIcons||{}),model.trait?.image,...liberations.map(s=>s.image)]);
    for(const skill of model.skills)paths.add(skill.image);
    for(const id of [state.exclusive,...state.weapons,...state.accessories])paths.add(equipmentMap.get(id)?.image);
    for(const id of state.tarot)paths.add(tarotMap.get(id)?.image);
    for(const e of engravings)for(const path of e.images)paths.add(path);
    const images=new Map(await Promise.all([...paths].filter(Boolean).map(async path=>[path,await loadImage(path,data)])));
    const authorImage=state.authorMode==='image'&&state.authorImage?await inlineImage(state.authorImage):null;
    const customAuthorFamily=!authorImage&&state.authorFont==='custom'&&state.authorCustomFont?await authorFontFace(state.authorCustomFont):null;
    if(state.author.trim()&&!authorImage&&state.authorFont==='signature')await Promise.all([
      signatureFont(data.signatureLatinFont,'WikiSignatureLatin','WIKI_SIGNATURE_LATIN_FONT','签名字体',{weight:'400 700'}),
      ...(/[^\u0000-\u024f]/u.test(state.author)?[signatureFont(data.signatureFont,'WikiSignature','WIKI_SIGNATURE_FONT')]:[])
    ]);
    if(state.bodyFont==='serif'||state.authorFont==='serif'||state.loadoutCommentary?.enabled&&state.loadoutCommentary.font==='serif')await signatureFont(data.nameFont.script,'WikiTitleNormal','WIKI_NORMAL_TITLE_FONT','正文字体');
    const titleResult=await titleArtwork(model,state,data);
    const canvas=document.createElement('canvas');canvas.width=outputSize.width;canvas.height=outputSize.height;const c=canvas.getContext('2d');c.scale(outputScale,outputScale);c.bodyStyle=state;
    const layoutRegions=[];let compositionFrames={},heroArea=null,minHeight=0;
    let box=null;
    // A block is a frame, not a zoom lens: content keeps its own size and reflows inside the frame,
    // so stretching a block rearranges its contents instead of scaling them.
    function block(key,x,y,w,h){
      const base={x,y,w,h},rect=state.layout?.[key]||compositionFrames[key]||(key==='topText'?base:{x:x*W/1920,y:y*H/1080,w:w*W/1920,h:h*H/1080});
      layoutRegions.push({key,...rect,base});
      c.save();c.beginPath();c.rect(rect.x,rect.y,rect.w,rect.h);c.clip();c.translate(rect.x-x,rect.y-y);
      return box={key,x,y,w:rect.w,h:rect.h,base};
    }
    function endBlock(){c.restore();box=null;}
    function mapped(region,key=region.key){const b=layoutRegions.find(b=>b.key===key);if(!b)return region;const a=b.base;return {...region,x:b.x+(region.x-a.x),y:b.y+(region.y-a.y),w:region.w,h:region.h};}
    const rectOf=key=>{const b=layoutRegions.find(b=>b.key===key);return b?{x:b.x,y:b.y,w:b.w,h:b.h}:{x:0,y:0,w:0,h:0};};
    let minTextSize=18;
    const content=(parts,px,py,w,h,size=18)=>{const box=fitted(c,parts,w,h,size);minTextSize=Math.min(minTextSize,box.size*box.scale);textBox(c,box,px,py);return box;};
    const heading=(label,px,py)=>{font(c,20,700);c.fillStyle=state.decoration?.style==='plain'?cyan:'#efe4c9';styledText(c,label,px,py);};
    const traitParts=runs(data.starEffects?.[model.trait?.id]?.html||'当前离线资料未收录个性星级描述。');
    const weaponParts=runs(data.starEffects?.[state.exclusive]?.html||(state.exclusive?'当前离线资料未收录装备星级技能。':'选择专武，展示图标和完整星级效果。'));
    const traitColumns=effectColumns(c,traitParts,right-36,20);
    const traitH=Math.max(124,Math.min(268,traitColumns.height+60));
    const weaponH=Math.max(94,Math.min(158,wrap(c,weaponParts,right-124,18,24.48).height+54));
    const weaponY=top+traitH+12,middleY=weaponY+weaponH+12,remaining=bottom-middleY;
    const middleH=Math.min(342,Math.max(252,remaining*.62)),footerY=middleY+middleH+12,footerH=bottom-footerY;
    ({frames:compositionFrames,hero:heroArea,minHeight}=posterFrames(c,state,W,H,traitParts,weaponParts,engravings,equipmentMap,tarotMap));
    // A fixed frame always contains the complete text. Dense selections receive an editor notice.
    c.fillStyle='#08121b';c.fillRect(0,0,W,H);
    const art=images.get(portrait);
    const backgroundRect=art?window.WikiInfographicRules.backgroundRect(art.width,art.height,state.background,{width:W,height:H},heroArea,heroArea?portraitBounds(art):null):null;
    if(art){c.save();c.imageSmoothingEnabled=true;c.imageSmoothingQuality='high';c.globalAlpha=state.backgroundOpacity??state.brightness??.65;c.drawImage(art,backgroundRect.x,backgroundRect.y,backgroundRect.w,backgroundRect.h);c.restore();}
    const shade=c.createLinearGradient(0,0,W,0);shade.addColorStop(0,'rgba(4,12,19,.88)');shade.addColorStop(.35,state.composition==='spotlight'?'rgba(4,12,19,.12)':'rgba(4,12,19,.30)');shade.addColorStop(.65,state.composition==='spotlight'?'rgba(4,12,19,0)':'rgba(4,12,19,.12)');shade.addColorStop(1,'rgba(4,12,19,.25)');c.fillStyle=shade;c.fillRect(0,0,W,H);
    c.fillStyle='#25404b';c.fillRect(0,0,W,5);c.fillStyle=gold;c.fillRect(24,0,180,5);posterOrnaments(c,W,H,state.decoration);
    const logoBox=block('logo',24,24,132,118);contain(c,images.get(data.logo),24,24,logoBox.w,logoBox.h);endBlock();
    line(c,166,34,166,148,'#42606a',1);
    const titleBox=block('title',185,5,titleResult.width+12,145),titleScale=Math.min((titleBox.w-10)/Math.max(1,titleResult.width),(titleBox.h-10)/Math.max(1,titleResult.height));
    c.drawImage(titleResult.canvas,190,10,titleResult.width*titleScale,titleResult.height*titleScale);endBlock();
    const artWidth=titleResult.width;
    const suffix=state.subtitle||'角色养成一图流',suffixX=190+artWidth+25;
    const subtitleBox=block('subtitle',suffixX-10,60,Math.max(40,1470-suffixX+10),85);
    font(c,58,700);c.fillStyle=gold;styledText(c,'·',suffixX-10,71);
    fit(c,suffix,suffixX+29,74,Math.max(40,subtitleBox.w-39),57,'#e8dbc0');
    endBlock();const cvBox=block('cv',193,150,1260,30);plain(c,`CV  中：${model.cvZh||'未收录'}    日：${model.cvJa||'未收录'}`,193,157,cvBox.w,17,ink);
    endBlock();const spriteBox=block('sprite',1505,0,210,190);c.save();c.imageSmoothingEnabled=false;contain(c,images.get(character.sprite),1505,0,spriteBox.w,spriteBox.h);c.restore();
    endBlock();const badgeBox=block('badges',1718,50,178,65),badges=model.badges.filter(b=>b.kind!=='rarity'),gap=8;
    const badgeSize=Math.max(1,Math.min(56,(badgeBox.w-Math.max(0,badges.length-1)*gap)/Math.max(1,badges.length),badgeBox.h-8)),badgeY=50+(badgeBox.h-badgeSize)/2;
    badges.forEach((b,i)=>{const bx=1718+badgeBox.w-badges.length*badgeSize-(badges.length-1)*gap+i*(badgeSize+gap);
      if(b.background){const size=badgeSize*.82,offset=(badgeSize-size)/2,inset=size*.18;contain(c,images.get(b.background),bx+offset,badgeY+offset,size,size);contain(c,images.get(b.image),bx+offset+inset,badgeY+offset+inset,size-inset*2,size-inset*2);}
      else contain(c,images.get(b.image),bx,badgeY,badgeSize,badgeSize);
    });
    endBlock();const roleBox=block('role',1718,120,178,54);if(state.roleText?.trim())content(rich(state.roleText,ink),1720,122,Math.max(20,roleBox.w-4),Math.max(20,roleBox.h-4),20);endBlock();
    const topBox=block('topText',state.topText?.trim()?state.topTextX:980,state.topText?.trim()?state.topTextY:144,state.topText?.trim()?Math.max(20,Math.min(W-24-state.topTextX,Math.max(120,state.topText.length*state.topTextSize))):500,state.topText?.trim()?state.topTextSize+6:34);
    if(state.topText?.trim()){
      c.save();font(c,state.topTextSize??22,600);c.textBaseline='alphabetic';c.strokeStyle='#071019';c.lineWidth=3;c.lineJoin='round';
      const tx=topBox.x,ty=topBox.y,m=c.measureText(state.topText),pad=4,ascent=m.actualBoundingBoxAscent||state.topTextSize,descent=Math.max(0,m.actualBoundingBoxDescent||0),left=Math.max(0,m.actualBoundingBoxLeft||0),width=Math.max(m.width,left+(m.actualBoundingBoxRight||m.width));
      const ratio=Math.max(.01,Math.min(1,(topBox.w-pad*2)/Math.max(1,width),(topBox.h-pad*2)/Math.max(1,ascent+descent)));
      c.translate(tx+pad+left*ratio,ty+pad+ascent*ratio);c.scale(ratio,ratio);c.strokeText(state.topText,0,0);c.fillStyle=state.topTextColor||'#e8dbc0';styledText(c,state.topText,0,0);c.restore();
    }
    endBlock();    const treeBox=block('tree',margin,top,treeW,bottom-top);
    // Straight alternating branches retain the original left/right skill assignments.
    panel(c,margin,top,treeBox.w,treeBox.h);heading('技能加点',margin+16,top+16);
    font(c,12);c.fillStyle=gold;styledText(c,'● 必点',margin+treeBox.w*.40,top+23);c.fillStyle=cyan;styledText(c,'◌ 选点',margin+treeBox.w*.59,top+23);c.fillStyle=muted;styledText(c,'○ 未点亮',margin+treeBox.w*.77,top+23);
    const center=margin+treeBox.w/2,libY=top+87,libPitch=Math.min(99,Math.max(34,(treeBox.w-30)/Math.max(1,liberations.length||1))),libLabel=Math.min(92,libPitch-6);
    font(c,13,700);c.fillStyle=gold;c.textAlign='center';styledText(c,'极限解放',center,top+49);c.textAlign='left';
    if(liberations.length){liberations.forEach((s,i)=>{const cx=center+(i-(liberations.length-1)/2)*libPitch;const dx=cx-center,dy=libY-(top+139),distance=Math.hypot(dx,dy),clearance=26.5+(state.markWidth??3)/2+3;line(c,center,top+139,cx-dx/distance*clearance,libY-dy/distance*clearance,state.marks[s.id]==='required'?gold:state.marks[s.id]==='optional'?cyan:'#506565',state.branchWidth??1.5);icon(c,images.get(s.image),cx,libY,45,state.marks[s.id]||'','?',!state.marks[s.id]);smallLabel(c,s.name,cx-libLabel/2,libY+32,libLabel,ink,13,2);});}
    else smallLabel(c,'暂无解放技能资料',margin+16,libY-3,treeBox.w-32,muted,14,2);
    // Rows share the free height: a shorter block tightens the spacing before anything shrinks.
    const rowStart=top+179,step=Math.max(46,Math.min(110,(treeBox.h-384)/6)),rootY=rowStart+step*6+39,tierIcon=Math.min(53,step-14),tierLabel=Math.min(120,(treeBox.w-16)/2);
    line(c,center,top+135,center,rowStart+6*step,'#506565',3);
    model.tiers.forEach((tier,i)=>{const cy=rowStart+i*step;
      tier.skills.forEach((skill,j)=>{const span=Math.min(window.WikiInfographicRules.branchSpan(tier.rank),treeBox.w/2-tierIcon/2-8),cx=center+(j===0?-span:span),mark=tier.rank===0?'':state.marks[skill?.id]||'';
        branch(c,center,cy,cx,mark,tier.rank===0,state);
        icon(c,images.get(skill?.image),cx,cy,tierIcon,mark,skill?'?':'—',tier.rank!==0&&!mark);
        smallLabel(c,skill?.name||tier.names[j]||'未收录',cx-tierLabel/2,cy+tierIcon/2+8.5,tierLabel,tier.rank===0||mark?ink:muted,12,1);
      });
      c.beginPath();c.ellipse(center,cy,20,13,0,0,Math.PI*2);c.fillStyle='#182b33';c.fill();c.strokeStyle='#687774';c.lineWidth=1;c.stroke();
      font(c,13,700);c.textAlign='center';c.fillStyle='#d3cfbb';styledText(c,tier.rank?tier.rank+'阶':'初始',center,cy-8);c.textAlign='left';
    });
    const noteY=rootY+25;
    line(c,margin+16,noteY,margin+treeBox.w-16,noteY,'#40535b',1);
    font(c,14,700);c.fillStyle=gold;styledText(c,'加点补充',margin+16,noteY+12);
    if(state.treeNotes)content(rich(state.treeNotes,ink),margin+16,noteY+37,treeBox.w-32,Math.max(24,top+treeBox.h-noteY-49),15);
    endBlock();const traitBox=block('trait',x,top,right,traitH);panel(c,x,top,traitBox.w,traitBox.h);contain(c,images.get(model.trait?.image),x+16,top+12,27,27);heading(`个性 · ${model.trait?.name||'未收录'}`,x+52,top+14);
    // Columns follow the block width; the auto flow below keeps using the default width.
    const traitFlow=Math.abs(traitBox.w-right)<8?traitColumns:effectColumns(c,traitParts,traitBox.w-36,20);
    traitFlow.parts.forEach((parts,i)=>content(parts,x+18+i*(traitFlow.width+28),top+47,traitFlow.width,traitBox.h-59,20));
    if(traitFlow.parts.length===2)line(c,x+traitBox.w/2,top+48,x+traitBox.w/2,top+traitBox.h-15,'#2e4852',1);
    endBlock();const weaponBox=block('exclusive',x,weaponY,right,weaponH);panel(c,x,weaponY,weaponBox.w,weaponBox.h);const weaponIcon=Math.min(74,weaponBox.h-16,weaponBox.w/3);
    contain(c,images.get(equipmentMap.get(state.exclusive)?.image),x+17,weaponY+22,weaponIcon,weaponIcon);
    heading(state.exclusive?'专武 · '+equipmentMap.get(state.exclusive)?.name:'专武 · 待选择',x+106,weaponY+12);
    content(weaponParts,x+106,weaponY+43,Math.max(40,weaponBox.w-124),Math.max(24,weaponBox.h-53),18);
    // Loadouts grow with the chosen count; an optional independent text frame follows below.
    const buildsW=690,gearX=1072,gearW=520,radarX=1604,radarW=292,note=state.loadoutCommentary||{enabled:false};
    const noteReserve=note.enabled?Math.min(136,Math.max(90,middleH*.38))+12:0,defaultBuildH=Math.min(middleH-noteReserve,48+90*state.loadouts.length);
    endBlock();const loadoutBox=block('loadouts',x,middleY,buildsW,defaultBuildH);panel(c,x,middleY,loadoutBox.w,loadoutBox.h);heading('技能搭配',x+16,middleY+13);
    font(c,13);c.fillStyle=muted;styledText(c,'普攻 / 反应 / 三项技能',x+122,middleY+19);
    const buildCols=Math.max(1,Math.min(Math.floor((loadoutBox.w-24)/330),Math.ceil(state.loadouts.length/4))),buildRows=Math.ceil(state.loadouts.length/buildCols),buildW=(loadoutBox.w-24-(buildCols-1)*12)/buildCols;
    const rowH=Math.max(4,(loadoutBox.h-48)/buildRows),nameW=Math.max(40,Math.min(128,buildW*.22)),slotW=Math.max(25,buildW-nameW-12),pitch=Math.min(105,slotW/5),slotIcon=Math.max(3,Math.min(49,pitch-8,rowH*.56)),labelSize=Math.max(3,Math.min(12,rowH*.18)),slotLabel=Math.min(98,pitch-6);
    state.loadouts.forEach((row,i)=>{const px=x+12+(i%buildCols)*(buildW+12),y=middleY+48+Math.floor(i/buildCols)*rowH;
      smallLabel(c,row.name||'搭配 '+(i+1),px,y+slotIcon*.32,nameW,cyan,Math.min(16,rowH*.24),3);
      row.slots.forEach((id,j)=>{const cx=px+nameW+12+(slotW-pitch*5)/2+(j+.5)*pitch,skill=skillMap.get(id);icon(c,images.get(skill?.image),cx,y+slotIcon/2,slotIcon,window.WikiInfographicRules.canMark(model,id)?state.marks[id]:'');smallLabel(c,skill?.name||['普攻','反应','技能 1','技能 2','技能 3'][j],cx-slotLabel/2,y+slotIcon+Math.min(7,rowH*.08),slotLabel,skill?ink:muted,labelSize,2);});
      if(Math.floor(i/buildCols)<buildRows-1)line(c,px,y+rowH-3,px+buildW,y+rowH-3,'#2c424b',1);
    });
    if(note.enabled){
      const builds=rectOf('loadouts'),baseNotes={x:x,y:middleY+defaultBuildH+12,w:buildsW,h:Math.max(96,middleH-defaultBuildH-12)};
      endBlock();const noteBox=block('loadoutNotes',baseNotes.x,baseNotes.y,baseNotes.w,baseNotes.h);panel(c,baseNotes.x,baseNotes.y,noteBox.w,noteBox.h);font(c,16,600);c.fillStyle=cyan;styledText(c,'搭配解说',baseNotes.x+16,baseNotes.y+12);
      c.bodyStyle={bodyFont:note.font,bodyBold:note.bold,bodyItalic:note.italic,bodyOutlineWidth:note.outlineWidth,bodyOutlineColor:note.outlineColor};
      const textW=Math.max(8,noteBox.w-32),textH=Math.max(4,noteBox.h-46);let size=note.size,paragraph=wrap(c,[{text:note.text,color:note.color}],textW,size,size*note.lineHeight);
      while(paragraph.height>textH&&size>6){size-=.5;paragraph=wrap(c,[{text:note.text,color:note.color}],textW,size,size*note.lineHeight);}
      minTextSize=Math.min(minTextSize,size);font(c,size);let py=baseNotes.y+37;
      for(const row of paragraph.lines){const width=row.reduce((sum,part)=>sum+part.width,0);let px=baseNotes.x+16+(note.align==='center'?(textW-width)/2:note.align==='right'?textW-width:0);for(const part of row){c.fillStyle=part.color;styledText(c,part.text,px,py);px+=part.width;}py+=paragraph.lineHeight;}
      c.bodyStyle=state;
    }
    endBlock();const gearBox=block('gear',gearX,middleY,gearW,middleH);panel(c,gearX,middleY,gearBox.w,gearBox.h);heading('装备 · 塔罗推荐',gearX+16,middleY+13);
    // Columns follow the available width; a narrower block stacks the same picks instead of shrinking them.
    const {gearCols,gearPitch,gearCell,gearIconSize,gearRows}=gearContent(c,state,gearBox.w,equipmentMap,tarotMap);
    const gearScale=Math.min(1,Math.max(40,gearBox.h-46)/Math.max(1,gearRows.reduce((a,b)=>a+b.height,0)));minTextSize=Math.min(minTextSize,12.5*gearScale);
    c.save();c.translate(gearX+gearBox.w*(1-gearScale)/2,middleY+45);c.scale(gearScale,gearScale);let gy=0;
    for(const row of gearRows){plain(c,row.label,10,gy+18,Math.min(38,gearCell),15,gold);
      row.items.forEach(({item,name,caption},j)=>{const px=70+(j%gearCols)*gearPitch,iy=gy+Math.floor(j/gearCols)*row.cellH,ix=px+5+gearIconSize/2;round(c,ix-gearIconSize/2,iy,gearIconSize,gearIconSize,7);c.fillStyle='#172e39';c.fill();c.strokeStyle='#567078';c.lineWidth=1;c.stroke();contain(c,images.get(item?.image),ix-gearIconSize/2+2,iy+2,gearIconSize-4,gearIconSize-4);if(!item){font(c,gearIconSize*.45);c.fillStyle=muted;styledText(c,'＋',ix-gearIconSize*.225,iy+gearIconSize*.275);}const end=paintCentered(c,name,ix,iy+gearIconSize+4);if(caption)paintCentered(c,caption,ix,end+1);});
      if(row.group)paintCentered(c,row.group,gearBox.w/2,gy+row.groupY);gy+=row.height;
    }c.restore();
    endBlock();const scoreBox=block('scores',radarX,middleY,radarW,middleH);panel(c,radarX,middleY,scoreBox.w,scoreBox.h);heading('角色评级',radarX+16,middleY+13);
    // The built-in six-axis radar keeps its original geometry; custom charts get their own block.
    const rules=window.WikiInfographicRules;
    const scoreText=(state.scoreText||'').trim();
    const builtIn={name:'',rated:state.rated,axes:rules.axes.map((name,i)=>({name,score:state.scores[i]}))};
    const captionH=scoreText?58:26;
    const areaTop=middleY+41,areaH=Math.max(60,scoreBox.h-49-captionH);
    const cx=radarX+scoreBox.w/2,cy=areaTop+areaH/2;
    const rr=Math.max(8,Math.min(70,(areaH-46)/2,scoreBox.w/2-46));
    radarChartArt(c,builtIn,cx,cy,rr,radarX+14,radarX+scoreBox.w-14,14);
    const rcx=radarX+scoreBox.w/2;
    if(scoreText){
      const caption=fitted(c,rich(scoreText,ink),Math.max(40,scoreBox.w-32),captionH,12),captionTop=middleY+scoreBox.h-22-(caption.lines.length-1)*caption.lineHeight;
      paintCentered(c,caption,rcx,Math.max(middleY+scoreBox.h-58,captionTop));
    }else{font(c,12);c.fillStyle=muted;c.textAlign='center';styledText(c,'玩家评估 · 0—5',rcx,middleY+scoreBox.h-22);c.textAlign='left';}
    // The footer row keeps the journal at the far right; the base stats slot opens up beside it.
    // Custom radar charts become their own block here instead of crowding the rating block.
    const radarCharts=rules.radarCharts(state.radarCharts),radarBlockW=radarCharts.length?236:0;
    const engravingW=842-radarBlockW-(radarBlockW?12:0),radarBlockX=x+engravingW+12;
    const statsX=(radarBlockW?radarBlockX+radarBlockW+12:x+engravingW+12),statsW=260,notesX=statsX+statsW+22,notesW=394;
    endBlock();const engravingBox=block('engravings',x,footerY,engravingW,footerH);panel(c,x,footerY,engravingBox.w,engravingBox.h);heading('刻印共鸣',x+16,footerY+13);
    if(!engravings.length)plain(c,'从全部组合中选择，可多选并添加说明。',x+16,footerY+52,Math.max(40,engravingBox.w-32),16,muted);
    const engravingMaxCols=Math.max(1,Math.floor((engravingBox.w-32)/180));
    const cols=engravings.length?Math.min(engravings.length<=3?Math.max(1,engravings.length):Math.ceil(engravings.length/2),engravingMaxCols):1;
    const rows=Math.ceil(engravings.length/cols),cellW=(engravingBox.w-32)/cols,cellH=(engravingBox.h-47)/Math.max(1,rows);
    engravings.forEach((e,i)=>{const px=x+16+(i%cols)*cellW,py=footerY+45+Math.floor(i/cols)*cellH;
      contain(c,images.get(e.images[0]),px,py,24,24);contain(c,images.get(e.images[1]),px+33,py,24,24);font(c,14);c.fillStyle=gold;styledText(c,'+',px+25,py+5);
      fit(c,e.name,px+66,py+4,Math.max(30,cellW-77),15,gold);
      const parts=[...runs(e.description),...(e.note?rich('\n'+e.note,'#ffd3a0'):[])];content(parts,px,py+30,Math.max(20,cellW-14),Math.max(20,cellH-36),16);
      if(i%cols!==cols-1)line(c,px+cellW-7,py,px+cellW-7,py+cellH-10,'#2d454f',1);
    });
    if(radarBlockW){
      endBlock();const radarBox=block('radar',radarBlockX,footerY,radarBlockW,footerH);panel(c,radarBlockX,footerY,radarBox.w,radarBox.h);
      heading(state.radarTitle?.trim()||'自定义雷达图',radarBlockX+12,footerY+13);
      const radarTop=footerY+38,radarAreaH=Math.max(60,radarBox.h-48);
      const radarCols=radarCharts.length<=1?1:2,radarRows=Math.ceil(radarCharts.length/radarCols);
      const radarCellW=(radarBox.w-20)/radarCols,radarCellH=radarAreaH/radarRows;
      radarCharts.forEach((chart,index)=>{
        const chartX=radarBlockX+10+radarCellW*((index%radarCols)+.5),chartY=radarTop+radarCellH*(Math.floor(index/radarCols)+.5);
        const titleH=chart.name?16:0;
        if(chart.name){font(c,11.5,700);c.fillStyle=cyan;c.textAlign='center';styledText(c,chart.name,chartX,chartY-radarCellH/2+2);c.textAlign='left';}
        // The top vertex label sits above the centre, so the title needs its own band.
        const radius=Math.max(8,Math.min(70,(radarCellH-24-titleH*2)/2,radarCellW/2-30));
        // Keep max/unit: the chart draws in its own ceiling and display mode.
        radarChartArt(c,{...chart,rated:true,name:''},chartX,chartY+titleH/2+titleH/2,radius,radarBlockX+8,radarBlockX+radarBox.w-8,11.5);
      });
    }
    endBlock();const notesBox=block('notes',notesX,footerY,notesW,footerH);panel(c,notesX,footerY,notesBox.w,notesBox.h);heading('养成手记',notesX+16,footerY+13);
    const signatureH=(state.author.trim()||authorImage)&&!compositionFrames.author?81:8;
    if(state.notes)content(notesParts(state.notes,ink,state.notesSize||15),notesX+16,footerY+41,Math.max(40,notesBox.w-32),Math.max(24,notesBox.h-48-signatureH),state.notesSize||15);
    endBlock();const authorBox=block('author',notesX+12,bottom-85,notesW-24,83);authorArtwork(c,state,authorImage,customAuthorFamily,notesX+24,bottom-83,Math.max(40,authorBox.w-18),Math.max(24,authorBox.h-4));
    endBlock();const statsBox=block('stats',statsX,footerY,statsW,footerH);panel(c,statsX,footerY,statsBox.w,statsBox.h);heading('基础属性',statsX+12,footerY+12);
    {const base=model.baseStats||{},statRows=window.WikiInfographicRules.combatStatDefinitions;
    const statGap=6,innerW=Math.max(28,statsBox.w-24),cellW=(innerW-statGap)/2,gridY=footerY+37,cellH=Math.max(25,Math.min(54,(statsBox.h-87)/3)),valueSize=Math.min(18,cellH*.49,cellW*.17),detailSize=Math.min(10,cellH*.26,cellW*.09);
    function statShape(px,py,w,h){const bevel=Math.min(9,h*.28);c.beginPath();c.moveTo(px+bevel,py);c.lineTo(px+w-bevel,py);c.lineTo(px+w,py+h/2);c.lineTo(px+w-bevel,py+h);c.lineTo(px+bevel,py+h);c.lineTo(px,py+h/2);c.closePath();}
    statRows.forEach(([key,label],i)=>{
      const px=statsX+12+(i%2)*(cellW+statGap),py=gridY+Math.floor(i/2)*(cellH+3),value=base[key],maximum=model.statMaxima?.[key],pct=window.WikiInfographicRules.statRatio(value,maximum);
      statShape(px,py,cellW,cellH);c.fillStyle=`rgba(20,42,53,${Math.max(.35,state.panelOpacity??.92)})`;c.fill();c.strokeStyle='#3a5d67';c.lineWidth=.8;c.stroke();
      const iconSize=Math.min(20,cellH*.52,cellW*.18),iconX=px+7,iconY=py+4,source=images.get(data.statIcons?.[key]);
      c.save();c.translate(iconX,iconY);c.fillStyle='#9ebfc7';
      if(source){const mask=document.createElement('canvas');mask.width=26;mask.height=26;const mc=mask.getContext('2d');mc.drawImage(source,0,0,26,26);mc.globalCompositeOperation='source-in';mc.fillStyle='#9ebfc7';mc.fillRect(0,0,26,26);c.drawImage(mask,0,0,iconSize,iconSize);}
      else{c.scale(iconSize/26,iconSize/26);c.fill(new Path2D(window.WikiInfographicRules.speedIconPath));}c.restore();
      // Compact labels identify the icons while the current value remains the visual focus.
      c.save();c.bodyStyle={...state,bodyOutlineWidth:0};font(c,Math.min(8,detailSize),500);c.fillStyle='#adc4c9';c.textAlign='left';styledText(c,label,iconX+iconSize+2,py+5);
      font(c,valueSize,700);c.fillStyle='#e7c479';c.textAlign='right';styledText(c,String(value||'—'),px+cellW-9,py+3);
      const detailY=py+cellH-detailSize-5; font(c,detailSize,500);c.fillStyle='#91aab2';c.textAlign='left';styledText(c,`/ ${maximum||'—'}`,px+9,detailY);
      font(c,detailSize,600);c.fillStyle='#85d5e7';c.textAlign='right';styledText(c,pct===null?'—':pct.toFixed(1)+'%',px+cellW-9,detailY);c.textAlign='left';c.restore();
      const barX=px+9,barY=py+cellH-3,barW=cellW-18;c.fillStyle='#25424d';c.fillRect(barX,barY,barW,2);if(pct!==null){c.fillStyle='#6badbb';c.fillRect(barX,barY,barW*pct/100,2);}
    });
    const mobilityY=gridY+3*(cellH+3)+4;
    window.WikiInfographicRules.mobilityStatDefinitions.forEach(([key,label],i)=>{const px=statsX+12+i*(cellW+statGap);font(c,11,500);c.fillStyle=muted;styledText(c,label,px+9,mobilityY);font(c,14,700);c.fillStyle=gold;c.textAlign='right';styledText(c,String(base[key]||'—'),px+cellW-9,mobilityY-1);c.textAlign='left';});
    plain(c,'最高值不含召唤物 · 高亮为当前值',statsX+12,footerY+statsBox.h-14,innerW,8,muted);}
    endBlock();const dateBox=block('date',1304,1057,600,23);c.save();font(c,14,500);c.fillStyle='#cbd9de';c.textAlign='right';c.strokeStyle='#08121b';c.lineWidth=2;const dateText=(state.datePrefix?.trim()?state.datePrefix.trim()+' ':'')+window.WikiInfographicRules.posterDate(state),dateX=1304+dateBox.w-8;c.strokeText(dateText,dateX,1062);styledText(c,dateText,dateX,1062);const dateHitWidth=Math.max(220,c.measureText(dateText).width+8);c.restore();
    endBlock();
    // Hit regions follow the same measured layout as the PNG, but are never painted.
    const hitRegions=[
      {key:'background',x:0,y:0,w:W,h:H,absolute:true},
      ...['logo','cv','sprite','badges'].map(key=>({key:'character',...rectOf(key),absolute:true})),
      {key:'title',...rectOf('title'),absolute:true},
      {key:'subtitle',...rectOf('subtitle'),absolute:true},
      {key:'role',...rectOf('role'),absolute:true},
      {key:'topText',...rectOf('topText'),absolute:true},
      {key:'tree',...rectOf('tree'),absolute:true},
      {key:'liberation',x:margin+5,y:top+42,w:treeBox.w-10,h:106},
      {key:'treeNotes',x:margin+10,y:noteY+5,w:treeBox.w-20,h:top+treeBox.h-noteY-10},
      {key:'trait',...rectOf('trait'),absolute:true},
      {key:'exclusive',...rectOf('exclusive'),absolute:true},
      {key:'loadouts',...rectOf('loadouts'),absolute:true},
      ...(note.enabled?[{key:'loadoutNotes',...rectOf('loadoutNotes'),absolute:true}]:[]),
      {key:'gear',...rectOf('gear'),absolute:true},
      {key:'scores',...rectOf('scores'),absolute:true},
      ...(radarBlockW?[{key:'radar',...rectOf('radar'),absolute:true}]:[]),
      {key:'stats',...rectOf('stats'),absolute:true},
      {key:'engravings',...rectOf('engravings'),absolute:true},
      {key:'notes',...rectOf('notes'),absolute:true},
      {key:'author',...rectOf('author'),absolute:true},
      {key:'date',...rectOf('date'),absolute:true}
    ];
    const scaled=r=>({...r,x:r.x*outputScale,y:r.y*outputScale,w:r.w*outputScale,h:r.h*outputScale,...(r.focusY!==undefined?{focusY:r.focusY*outputScale}:{}),...(r.focusTop!==undefined?{focusTop:r.focusTop*outputScale}:{})});
    return {canvas,width:outputSize.width,height:outputSize.height,recommendedHeight:Math.ceil(minHeight*outputScale/16)*16,layoutRegions:layoutRegions.map(r=>({...scaled(r),base:scaled(r.base)})),hitRegions:hitRegions.map(r=>scaled(r.absolute?r:mapped(r,'tree'))),dense:minTextSize*outputScale<11,minTextSize:minTextSize*outputScale,heroArea:heroArea?scaled(heroArea):null,backgroundRect:backgroundRect?scaled(backgroundRect):null,titleMissing:titleResult.missing,titleSource:titleResult.source};
  }
  return {draw,runs,wrap,titleArtwork,titleText,authorFontFace};
})();
