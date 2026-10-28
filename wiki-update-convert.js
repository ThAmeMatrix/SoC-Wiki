/* Convert public MediaWiki parse results to the same document format as the bundled archive. */
window.WikiUpdateConvert=(()=>{
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const text=s=>{const t=document.createElement('template');t.innerHTML=s;return t.content.textContent.trim();};
  const canonical=s=>{try{let u=new URL(s,'https://wiki.biligame.com');if(u.hostname!=='patchwiki.biligame.com'||!u.pathname.startsWith('/images/llzj/'))return '';u.search='';if(u.pathname.includes('/thumb/'))u.pathname=u.pathname.replace('/thumb/','/').split('/').slice(0,-1).join('/');return u.href;}catch{return '';}};
  function fields(source){const lines=source.replace(/<!--[\s\S]*?-->/g,'').split('\n'),out={};let key='';for(const line of lines){const m=line.match(/^\s*\|{1,2}\s*([^=|]+?)\s*=(.*)$/);if(m&&m[1].length<40){key=m[1].trim();out[key]=m[2];}else if(/^\s*}}/.test(line))key='';else if(key)out[key]+='\n'+line;}for(const k of Object.keys(out))out[k]=out[k].trim();return out;}
  function kind(title,cats){const p=title.split('/')[0];return title.includes('/')&&({'角色图鉴库':'character','装备图鉴库':'equipment','技能图鉴库':'skill','技能图鉴':'skill','技能':'skill','中括号介绍':'status','魔物图鉴库':'monster','个性':'talent','天赋':'talent','天赋图标库':'talent','极限解放':'talent','特性':'talent'}[p])||(/维护内容|资源统计表/.test(title)||cats.some(c=>['公告','新闻','维护','统计','PV'].includes(c))?'news':'guide');}
  function effectDocument(html){
    const t=document.createElement('template');t.innerHTML=html;
    t.content.querySelectorAll('br').forEach(br=>br.replaceWith('\n'));
    t.content.querySelectorAll('p,div,li').forEach(block=>block.append('\n'));
    return t.content;
  }
  function sliceHTML(doc,start,end,changes=[]){
    let offset=0;const out=document.createElement('div');
    function clone(node){
      if(node.nodeType===Node.TEXT_NODE){const lo=offset,hi=offset+node.length;offset=hi;const a=Math.max(start,lo),b=Math.min(end,hi);if(a>=b)return [];
        const points=new Set([a,b]);for(const [x,y] of changes)if(x<b&&y>a){points.add(Math.max(a,x));points.add(Math.min(b,y));}
        const ranges=[...points].sort((x,y)=>x-y),result=[];for(let i=1;i<ranges.length;i++){const x=ranges[i-1],y=ranges[i],n=document.createTextNode(node.textContent.slice(x-lo,y-lo));if(changes.some(([c,d])=>c<=x&&y<=d)){const mark=document.createElement('mark');mark.className='star-change';mark.append(n);result.push(mark);}else result.push(n);}return result;
      }
      if(node.nodeType!==Node.ELEMENT_NODE)return [];
      const children=[...node.childNodes].flatMap(clone);if(!children.length)return [];const copy=node.cloneNode(false);copy.append(...children);return [copy];
    }
    out.append(...[...doc.childNodes].flatMap(clone));return out.innerHTML.trim();
  }
  function segments(html){
    const doc=effectDocument(html),full=doc.textContent;
    return [...full.matchAll(/[^。！？；;\r\n]+[。！？；;]?/g)].filter(m=>m[0].trim()).map(m=>({text:m[0],key:m[0].replace(/\s+/g,''),html:sliceHTML(doc,m.index,m.index+m[0].length),start:m.index,end:m.index+m[0].length}));
  }
  function differences(before,after){
    const tokenize=s=>[...s.matchAll(/\d+(?:\.\d+)?[%％]?|[a-zA-Z]+|[^\s]/g)],a=tokenize(before),b=tokenize(after),width=b.length+1,dp=new Uint16Array((a.length+1)*width);
    for(let i=a.length-1;i>=0;i--)for(let j=b.length-1;j>=0;j--)dp[i*width+j]=a[i][0]===b[j][0]?1+dp[(i+1)*width+j+1]:Math.max(dp[(i+1)*width+j],dp[i*width+j+1]);
    const changed=[],oldChanged=[],removed=[];let i=0,j=0,old=[],added=[];
    function flush(){if(added.length)changed.push([added[0].index,added.at(-1).index+added.at(-1)[0].length]);if(old.length){oldChanged.push([old[0].index,old.at(-1).index+old.at(-1)[0].length]);if(!added.length)removed.push(old.map(t=>t[0]).join(''));}old=[];added=[];}
    while(i<a.length||j<b.length){if(i<a.length&&j<b.length&&a[i][0]===b[j][0]){flush();i++;j++;}else if(j<b.length&&(i===a.length||dp[i*width+j+1]>=dp[(i+1)*width+j]))added.push(b[j++]);else old.push(a[i++]);}flush();return {changed,oldChanged,removed};
  }
  function starComparison(fields){
    const prefix=['个性描述','天赋描述','特性描述'].find(p=>[1,2,3,4,5].some(n=>fields[p+n]));if(!prefix)return null;
    const values=[1,2,3,4,5].map(n=>fields[prefix+n]||''),docs=values.map(effectDocument),plain=docs.map(d=>d.textContent),groups=values.map(segments),counts=rows=>rows.reduce((m,r)=>(m[r.key]=(m[r.key]||0)+1,m),{}),commonCounts=counts(groups[0]);
    for(const group of groups.slice(1)){const current=counts(group);for(const key of Object.keys(commonCounts))commonCounts[key]=Math.min(commonCounts[key],current[key]||0);}
    const left={...commonCounts},common=groups[0].filter(row=>left[row.key]>0&&left[row.key]--).map(r=>'<div class="star-paragraph">'+r.html+'</div>').join('');let previous=null;
    const levels=groups.map((rows,i)=>{
      if(!plain[i].trim())return {star:i+1,available:false,html:'',removed:[],previous:null,changed:false};
      const diff=previous===null?{changed:plain.slice(i+1).filter(s=>s.trim()).flatMap(s=>differences(plain[i],s).oldChanged),removed:[]}:differences(plain[previous],plain[i]),left={...commonCounts};
      const html=rows.filter(row=>!(left[row.key]>0&&left[row.key]--)).map(row=>'<div class="star-paragraph">'+sliceHTML(docs[i],row.start,row.end,diff.changed)+'</div>').join('');
      const level={star:i+1,available:true,html,removed:diff.removed,previous:previous===null?null:previous+1,changed:previous!==null&&plain[i].replace(/\s+/g,'')!==plain[previous].replace(/\s+/g,'')};previous=i;return level;
    });return {prefix,common,levels};
  }
  function combineStars(values){
    const docs=values.map(segments),available=docs.map(d=>d.length>0),groups=new Map();
    // Exact sentence skeletons align quantities; different mechanisms remain explicitly separated.
    for(let i=4;i>=0;i--){const seen=new Map();for(const row of docs[i]){const skeleton=row.text.replace(/\s+/g,'').replace(/\d+(?:\.\d+)?[%％]?/g,'#'),ordinal=seen.get(skeleton)||0;seen.set(skeleton,ordinal+1);const key=skeleton+'@'+ordinal;if(!groups.has(key))groups.set(key,Array(5).fill(null));groups.get(key)[i]=row;}}
    const html=[...groups.values()].map(rows=>{const reference=[...rows].reverse().find(Boolean),nums=rows.map(r=>r?.text.match(/\d+(?:\.\d+)?[%％]?/g)||[]);let index=0;
      if(nums.some(n=>n.length)){
        const t=document.createElement('template');t.innerHTML=reference.html;const walker=document.createTreeWalker(t.content,NodeFilter.SHOW_TEXT),nodes=[];let node;while(node=walker.nextNode())nodes.push(node);
        for(const node of nodes){const frag=document.createDocumentFragment();let start=0;for(const m of node.textContent.matchAll(/\d+(?:\.\d+)?[%％]?/g)){frag.append(node.textContent.slice(start,m.index));const n=index++,values=rows.map((r,i)=>available[i]?(nums[i][n]||'0'):'未收录');if(new Set(values).size===1)frag.append(values[0]);else{const span=document.createElement('span');span.className='wiki-color-red';span.dataset.sourceColor='red';span.textContent=values.join('/');frag.append(span);}start=m.index+m[0].length;}frag.append(node.textContent.slice(start));node.replaceWith(frag);}
        return '<div>✦'+t.innerHTML+'</div>';
      }
      return '<div>✦'+(rows.every(Boolean)?reference.html:'效果（1→5星）：'+rows.map((r,i)=>r?.html||esc(available[i]?'0':'未收录')).join(' / '))+'</div>';
    }).join('');return {html,available};
  }
  function sanitizer(images,titles,id){
    const colorGroups={gold:['#f3c156','#bdb76b','#b88646','orange','#ffcc66','#c49a6c','#d2b48c'],orange:['#ed7950','#d2691e'],red:['red','#ff0000','rgb(255,0,0)'],blue:['#54b4db','blue','deepskyblue','#1e90ff'],green:['#58cb48','green','limegreen','#00cc66','#006600','#808000'],purple:['#d68fe2','purple'],brown:['brown','#a0522d','#5a4328'],neutral:['white','black','gray','grey','#fff','#ffffff','#000','#000000','#cccccc']};
    const byURL=new Map(Object.values(images).map(v=>[canonical(v.url),v.path]));
    function sanitize(html){
      const template=document.createElement('template');template.innerHTML=html;
      template.content.querySelectorAll('script,style,link,meta,base,object,embed,iframe,audio,video,form,input,button,select,textarea,svg,math,.mw-editsection,.noprint').forEach(e=>e.remove());
      for(const el of [...template.content.querySelectorAll('*')]){
        let color=el.getAttribute('color')||el.style.color; color=color.toLowerCase().replace(/\s+/g,'').replace('##','#');if(/^[0-9a-f]{6}$/.test(color))color='#'+color;const rgb=color.match(/^rgb\((\d+),(\d+),(\d+)\)$/);if(rgb)color='#'+rgb.slice(1).map(v=>Number(v).toString(16).padStart(2,'0')).join('');const style=el.getAttribute('style')||'',href=el.getAttribute('href'),src=el.getAttribute('src'),oldId=el.id;
        for(const attr of [...el.attributes])if(!['class','title','alt','colspan','rowspan','data-name','data-type','data-file-width','data-file-height'].includes(attr.name))el.removeAttribute(attr.name);
        if(oldId)el.id='source-'+id+'-'+oldId;
        if(color&&/^(?:#[0-9a-f]{3,8}|[a-z]{1,24}|rgba?\([\d.,%\s]+\))$/i.test(color)){
          const group=Object.entries(colorGroups).find(([,values])=>values.includes(color))?.[0]||'custom';el.dataset.sourceColor=color;el.classList.add('wiki-color-'+group);if(group==='custom')el.style.setProperty('--source-color',color);
        }
        if(/font-weight:\s*(bold|[6-9]00)/i.test(style))el.style.fontWeight='bold';
        if(el.tagName==='IMG'){const path=byURL.get(canonical(src));el.setAttribute('src',path||'assets/brand/placeholder.svg');el.setAttribute('loading','lazy');}
        if(el.tagName==='A'&&href){
          if(href.startsWith('#'))el.setAttribute('href','#/page/'+id+'?section='+encodeURIComponent(href.slice(1)));
          else try{const u=new URL(href,'https://wiki.biligame.com/llzj/');if(u.hostname==='wiki.biligame.com'&&u.pathname.startsWith('/llzj/')){const title=u.searchParams.get('title')||decodeURIComponent(u.pathname.slice(6));if(/^(?:文件|File):/i.test(title)&&images[title.split(':').slice(1).join(':').replaceAll(' ','_')]){el.setAttribute('href',images[title.split(':').slice(1).join(':').replaceAll(' ','_')].path);el.dataset.lightbox='true';}else{el.setAttribute('href',titles[title]?'#/page/'+titles[title]:'#/search?q='+encodeURIComponent(title));if(title.startsWith('中括号介绍/'))el.classList.add('term-link');}}else if(u.protocol==='https:'){el.setAttribute('href',u.href);el.setAttribute('target','_blank');el.setAttribute('rel','noopener noreferrer');}}catch{}
        }
      }
      for(const el of template.content.querySelectorAll('.bili-tt,.wiki-color-gold')){const term=el.dataset.name||el.textContent.trim(),target=titles['中括号介绍/'+term];if(target&&!el.closest('a')&&!el.querySelector('a')){const link=document.createElement('a');link.href='#/page/'+target;link.className='term-link';link.title='查看状态：'+term;el.replaceWith(link);link.append(el);}}
      for(const table of template.content.querySelectorAll('table')){const w=document.createElement('div');w.className='table-scroll';table.replaceWith(w);w.append(table);}
      return template.innerHTML;
    }
    return sanitize;
  }
  function convert(parsed,meta,images,titles,old){
    const id=parsed.pageid,title=parsed.title,cats=(parsed.categories||[]).map(c=>c.category||c['*']),type=kind(title,cats),sanitize=sanitizer(images,titles,id),raw=fields(parsed.wikitext),htmlFields={};
    const link=title=>titles[title]?'#/page/'+titles[title]:'#/search?q='+encodeURIComponent(title);
    for(const [key,value] of Object.entries(raw))htmlFields[key]=sanitize(value.replace(/\{\{中括号介绍\|([^{}|]+)(?:\|[^{}]*)?\}\}/g,(_,n)=>`<a href="https://wiki.biligame.com/llzj/${esc(n.includes('/')?n:'中括号介绍/'+n)}">[${esc(n)}]</a>`).replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g,(_,n,label)=>`<a href="https://wiki.biligame.com/llzj/${esc(n)}">${esc(label||n)}</a>`).replace(/'''([\s\S]*?)'''/g,'<strong>$1</strong>'));
    const props=Object.fromEntries(Object.entries(htmlFields).map(([k,v])=>[k,text(v)]));
    let html=sanitize(parsed.text);if(type==='status'&&htmlFields['介绍'])html='<div class="definition">'+htmlFields['介绍']+'</div>'+html;
    if(type==='character'){
      const table=document.createElement('template');table.innerHTML=html;
      for(const row of table.content.querySelectorAll('tr')){const label=row.querySelector('th')?.textContent.trim();if(['生命','物攻','魔攻','物防','魔防','敏捷'].includes(label))for(const [cls,prefix] of [['.pre_val','初始'],['.max_val','满级满星']])if(!props[prefix+label])props[prefix+label]=row.querySelector(cls)?.textContent.trim()||'';}
    }
    const named=name=>{for(const ext of ['.png','.jpg','.gif','.webp','.jpeg'])if(images[name.replaceAll(' ','_')+ext])return images[name.replaceAll(' ','_')+ext].path;return '';};
    const name=title.split('/').pop(),redirect=parsed.wikitext.match(/^\s*#(?:REDIRECT|重定向)\s*\[\[(.*?)\]\]/i),date=(meta.revisions?.[0]?.timestamp||'').slice(0,10);
    const description=['角色生平','装备描述','技能描述','介绍','个性描述5','天赋描述5','魔物解析'].map(k=>props[k]).find(Boolean)||text(html);
    const image=(type==='character'?named('立绘_'+name):type==='equipment'?named('装备全图_'+name):type==='skill'?named('技能_'+(props['技能图标']||name)):type==='talent'?named('个性_'+(props['个性图标']||name))||named('天赋_'+name):'')||old?.image||'';
    const entry={...old,id,title,name,type,image,date,summary:description.slice(0,220),categories:cats,class:props['角色职业']||'',rarity:props['稀有度']||'',faction:props['所属阵营']||'',weapon:props['武器类型']||props['装备类型']||'',aliases:props['角色绰号']||'',redirect:!!redirect};
    if(type==='character'){
      entry.stats=Object.fromEntries(['生命','物攻','魔攻','物防','魔防','敏捷'].map(k=>[k,props['满级满星'+k]||'']));entry.avatar=named('头像_'+name)||old?.avatar||'';entry.sprite=named('像素人物_'+name)||old?.sprite||'';entry.professionIcon=named('职业图标_'+entry.class)||old?.professionIcon||'';entry.sourceOrder=old?.sourceOrder??100000+id;entry.unitNumber=props.ID||'';
      entry.portraits=[...(old?.portraits||[])];for(const [key,n] of [['base','立绘_'+name],['awakened','立绘_'+name+'（五星）']]){const src=named(n);if(src){const i=entry.portraits.findIndex(p=>p.key===key),v={key,label:key==='base'?'初始立绘':'觉醒立绘',src};i<0?entry.portraits.push(v):entry.portraits.splice(i,1,v);}}
    }
    const related=[...new Set([...parsed.text.matchAll(/title="(角色图鉴库\/[^"<>]+)"/g)].map(m=>titles[m[1]]).filter(Boolean))];
    const doc={id,title,html,fields:htmlFields,rawFields:props,related,revision:parsed.revid,date,sections:parsed.sections||[],source:'https://wiki.biligame.com/llzj/index.php?title='+encodeURIComponent(title)+'&oldid='+parsed.revid,hasOnlineMedia:/<(?:iframe|video|audio)\b/.test(parsed.text)};
    const comparison=starComparison(htmlFields);if(comparison)doc.starComparison=comparison;
    return {entry,doc,redirect:redirect?titles[redirect[1]]||0:0,search:title+' '+Object.values(props).join(' ')+' '+text(html)};
  }
  return {canonical,fields,kind,convert,sanitizer,combineStars};
})();
