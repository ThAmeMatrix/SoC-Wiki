/* Shared local search index for the global search dialog and full search page. */
window.WikiSearch=(()=>{
  'use strict';
  const M=window.WikiSemantic,esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const clean=s=>String(s??'').trim().slice(0,60),normalize=s=>String(s??'').toLowerCase().replace(/[·•・\s]/g,'');
  let preparation,rows=[],linked=new Map(),badges={},lastKey='',lastResults=[];
  function script(path,key){return new Promise((resolve,reject)=>{
    if(window[key])return resolve(window[key]);const node=document.createElement('script');node.src=path;
    node.onload=()=>{node.remove();resolve(window[key]);};node.onerror=()=>{node.remove();reject(new Error('搜索资料未能载入：'+path));};document.head.append(node);
  });}
  function fieldLabel(key){const star=key.match(/(?:个性|天赋|特性)描述([1-5])/);if(star)return star[1]+'星';const equipment=key.match(/^([一二三四五])星技能$/);return equipment?'一二三四五'.indexOf(equipment[1])+1+'星':key;}
  function prepare(pages){return preparation??=(async()=>{
    const [original,catalog]=await Promise.all([script('data/advanced-search.js','WIKI_ADVANCED_DATA'),script('data/infographic.js','WIKI_INFOGRAPHIC_DATA').catch(()=>({}))]);
    const data={...original};for(const [id,doc] of Object.entries(window.WikiUpdates?.documents()||{}))data[id]={fields:doc.rawFields,related:doc.related};
    badges=(window.WikiUpdates?.catalog(catalog)||catalog).badges?.factions||{};
    rows=pages.filter(p=>!p.redirect).map(p=>{const fields=data[p.id]?.fields||{},parts=Object.entries(fields).filter(([key,value])=>value&&/描述|介绍|效果|星技能|抉择/.test(key)).map(([key,value])=>({label:fieldLabel(key),text:String(value)}));return {p,fields,parts};});
    const byTitle=new Map(rows.map(r=>[r.p.title,r])),byName=new Map();for(const r of rows){if(!byName.has(r.p.name))byName.set(r.p.name,[]);byName.get(r.p.name).push(r);}
    function named(name,kind){return byTitle.get(name)||byTitle.get((kind==='talent'?'个性/':'技能图鉴库/')+name)||(byName.get(name)||[]).find(r=>r.p.type===kind);}
    const skillNames=new Set(rows.filter(r=>r.p.type==='skill').map(r=>r.p.name));linked=new Map();
    for(const r of rows.filter(r=>r.p.type==='character')){
      const found=[],seen=new Set();
      function add(name,type,depth=0){
        const target=named(name,type==='个性'?'talent':'skill')||byTitle.get('极限解放/'+name);if(!target||depth>3||seen.has(type+':'+target.p.id))return;
        seen.add(type+':'+target.p.id);found.push({row:target,type});
        for(const [key,value] of Object.entries(target.fields))if(/抉择|关联技能/.test(key))for(const name of String(value).split(/[，,、]/))add(name.trim(),'抉择分支',depth+1);
        for(const part of target.parts)for(const match of part.text.matchAll(/\[([^\]]+)\]/g))if(skillNames.has(match[1].trim()))add(match[1].trim(),type.startsWith('个性')?'个性技能':'抉择分支',depth+1);
      }
      if(r.fields['个性'])add(r.fields['个性'],'个性');
      for(const [key,value] of Object.entries(r.fields))if(/阶技能|初始普攻|初始技能|极限解放/.test(key))for(const name of String(value).split(/[，,、]/))add(name.trim(),'技能');
      linked.set(r.p.id,found);
    }
    lastKey='';return true;
  })().catch(error=>{preparation=null;throw error;});}
  function queryMatch(text,query){
    const {camp,rest}=M.parseCamp(query);if(camp&&!M.matchWithCamp(text,'',camp))return false;
    return rest.split(/\s+/).filter(Boolean).every(term=>term.length>28?normalize(text).includes(normalize(term)):M.findMatches(text,term).length>0);
  }
  function search(value,options={}){
    const query=clean(value),camps=[...(options.camps||[])].sort(),key=JSON.stringify([query,options.type||'',options.weapon||'',options.hitKind||'',camps]);
    if(key===lastKey)return lastResults;
    const output=[],memo=new Map(),ownHits=new Map(),terms=query.toLowerCase().split(/\s+/).filter(Boolean),q=normalize(query);
    const matches=text=>{text=String(text||'');if(!memo.has(text))memo.set(text,queryMatch(text,query));return memo.get(text);};
    function effects(row){
      if(!ownHits.has(row.p.id)){
        const found=[];for(const part of row.parts)if(matches(row.p.name+' '+part.text))found.push({id:row.p.id,name:row.p.name,label:part.label,text:part.text});
        ownHits.set(row.p.id,found);
      }return ownHits.get(row.p.id);
    }
    const source=rows.length?rows:(window.WIKI_DATA?.pages||[]).filter(p=>!p.redirect).map(p=>({p,parts:[],fields:{}}));
    for(const r of source){
      const p=r.p;if(options.type&&p.type!==options.type||options.weapon&&p.weapon!==options.weapon)continue;
      if(camps.length&&(p.type!=='character'||!camps.every(c=>String(p.faction).split(/[，,、]/).includes(c))))continue;
      if(options.hitKind&&p.type!=='character')continue;
      let hits=[],score=0;
      if(query){
        if(!options.hitKind){
          const aliases=normalize(p.aliases).split(/[、,，]/),identity=p.title+' '+p.aliases+' '+p.faction;
          if(normalize(p.name)===q)score=1000;else if(aliases.includes(q))score=950;else if(normalize(p.name).startsWith(q))score=850;else if(normalize(identity).includes(q))score=750;else if(matches(identity))score=300;
          for(const hit of effects(r))hits.push({...hit,type:p.type==='equipment'?'装备效果':p.type==='talent'?'个性 / 天赋':'正文'});
        }
        if(p.type==='character')for(const source of linked.get(p.id)||[]){
          if(options.hitKind&&!source.type.includes(options.hitKind))continue;
          for(const hit of effects(source.row))hits.push({...hit,type:source.type});
        }
        if(hits.length)score=Math.max(score,p.type==='character'?500:400);
        // Keep exact full-text AND matching for every archive category, including guides and news.
        if(!options.hitKind&&!score){const full=String(window.WIKI_SEARCH?.[p.id]||p.title+' '+p.summary);if(terms.every(t=>full.toLowerCase().includes(t)||normalize(p.title+' '+p.aliases).includes(normalize(t)))){score=200;hits.push({id:p.id,name:p.name,type:'全文',label:'',text:full});}}
        if(!score)continue;
      }else if(options.hitKind&&!(linked.get(p.id)||[]).some(s=>s.type.includes(options.hitKind)))continue;
      output.push({p,score,hits});
    }
    const typeOrder={character:0,equipment:1,skill:2,talent:3,status:4,guide:5,monster:6,news:7};
    output.sort((a,b)=>b.score-a.score||(typeOrder[a.p.type]??8)-(typeOrder[b.p.type]??8)||(a.p.sourceOrder??1e6)-(b.p.sourceOrder??1e6)||String(b.p.date).localeCompare(String(a.p.date))||a.p.id-b.p.id);
    lastKey=key;lastResults=output;return output;
  }
  function highlight(text,query){
    text=String(text??'');query=clean(query);if(!query)return esc(text);if(!/\s/.test(query)&&query.length<=28)return M.hl(text,query);
    const ranges=query.split(/\s+/).filter(Boolean).flatMap(term=>term.length>28?(()=>{const at=text.toLowerCase().indexOf(term.toLowerCase());return at<0?[]:[{idx:at,len:term.length}];})():M.findMatches(text,term)).sort((a,b)=>a.idx-b.idx),merged=[];
    for(const r of ranges){const last=merged.at(-1);if(last&&r.idx<=last.idx+last.len)last.len=Math.max(last.len,r.idx+r.len-last.idx);else merged.push({...r});}
    let out='',pos=0;for(const r of merged){out+=esc(text.slice(pos,r.idx))+'<mark>'+esc(text.slice(r.idx,r.idx+r.len))+'</mark>';pos=r.idx+r.len;}return out+esc(text.slice(pos));
  }
  function snippet(text,query,length=160){
    text=String(text??'');query=clean(query);if(query.length>28){const at=text.toLowerCase().indexOf(query.toLowerCase()),start=Math.max(0,at-20);return (start?'…':'')+text.slice(start,start+length)+(text.length>start+length?'…':'');}
    const word=query.split(/\s+/).find(part=>part&&M.findMatches(text,part).length)||query;return M.snippet(text,word,length);
  }
  function filters(){return {weapons:[...new Set(rows.map(r=>r.p.weapon).filter(Boolean))],camps:[...new Set(rows.filter(r=>r.p.type==='character').flatMap(r=>String(r.p.faction).split(/[，,、]/)).filter(Boolean))]};}
  return {prepare,search,highlight,snippet,clean,filters,badge:name=>badges[name]||'',groupTag:M.groupHitTag};
})();
