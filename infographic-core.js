/* Shared selection rules for the offline character poster. */
(function(root,factory){
  if(typeof module==='object'&&module.exports)module.exports=factory();
  else root.WikiInfographicRules=factory();
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  const axes=['DOT','直伤','穿伤','辅助','生存','控制'];
  const ranks=[[11,'十一'],[9,'九'],[7,'七'],[5,'五'],[3,'三'],[1,'一']];
  const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
  const number=(v,min,max,def)=>Number.isFinite(Number(v))?Math.min(max,Math.max(min,Number(v))):def;
  const short=(v,n,def='')=>typeof v==='string'?v.slice(0,n):def;
  function treeNames(fields){
    return [...ranks.map(([rank,cn])=>({rank,names:[fields[cn+'阶技能左']||'',fields[cn+'阶技能右']||'']})),
      {rank:0,names:[fields['初始普攻']||'',fields['初始技能']||'']}];
  }
  function kind(raw,initialBasic=false){
    if(initialBasic)return 'basic';
    const text=String(raw['技能描述']||'').trim();
    const category=String(raw['技能类别']||'')+' '+(text.match(/^[（(]([^）)]+)[）)]/)||[])[1];
    return /普攻/.test(category)?'basic':/反应/.test(category)?'reaction':'skill';
  }
  function pool(model,slot){return model.skills.filter(s=>s.kind===(slot===0?'basic':slot===1?'reaction':'skill'));}
  function defaults(model){
    return {version:6,background:{portrait:model.character.portraits?.some(p=>p.key==='awakened')?'awakened':'base',x:0,y:0,scale:1},customTitle:null,titleName:'',titleMode:model.character.id===9296?'reference':'text',titleFont:'serif',bodyFont:'sans',bodyBold:false,bodyItalic:false,bodyOutlineWidth:0,bodyOutlineColor:'#071018',titleItalic:false,titleBold:false,titleScale:1,titleOutlineWidth:0,titleOutlineColor:'#08121b',titleShadow:true,generatedDate:'',datePrefix:'',roleText:'',layout:{},topText:'',topTextX:1000,topTextY:152,topTextSize:22,topTextColor:'#e8dbc0',branchWidth:1.5,branchLength:100,titleImageTint:false,characterId:model.character.id,subtitle:'角色养成一图流',titleColor:'#ef9b73',treeNotes:'',author:'',notes:'',
      backgroundOpacity:.65,panelOpacity:.92,markWidth:3,exclusive:null,marks:{},loadouts:Array.from({length:3},(_,i)=>({name:'搭配 '+(i+1),slots:[model.initialBasic||null,null,null,null,null]})),
      weapons:[null],accessories:[null],tarot:[null],engravings:[],gearNotes:{weapons:[''],accessories:[''],tarot:['']},groupNotes:{weapons:'',accessories:'',tarot:''},scores:[0,0,0,0,0,0],rated:false,scoreText:''};
  }
  function restore(value,model,catalog){
    const state=defaults(model);
    if(!object(value)||![1,2,3,4,5,6].includes(value.version)||value.characterId!==model.character.id)return state;
    const equipment=new Map(catalog.equipment.map(p=>[p.id,p]));
    const validEquipment=(id,accessory=false)=>equipment.has(id)&&((equipment.get(id).weapon==='防具')===accessory);
    const list=(v,valid)=>{const used=new Set();return Array.from({length:Math.max(1,Math.min(12,Array.isArray(v)?v.length:1))},(_,i)=>{const id=Array.isArray(v)?v[i]:null;if(valid(id)&&!used.has(id)){used.add(id);return id;}return null;});};
    state.subtitle=short(value.subtitle,48,state.subtitle);if(state.subtitle==='角色养成 · 一图流')state.subtitle='角色养成一图流';
    state.titleName=Array.from(short(value.titleName,96).replace(/[\u0000-\u001f\u007f]/g,'').trim()).slice(0,24).join('');
    state.titleColor=/^#[0-9a-f]{6}$/i.test(value.titleColor||'')?value.titleColor.toLowerCase():state.titleColor;state.treeNotes=short(value.treeNotes,160);
    state.roleText=short(value.roleText,100);
    if(object(value.layout))for(const key of layoutKeys)if(object(value.layout[key]))state.layout[key]=layoutRect(value.layout[key]);
    state.author=short(value.author,24);state.notes=short(value.notes,320);
    const background=object(value.background)?value.background:{};
    if(['base','awakened'].includes(background.portrait)&&model.character.portraits?.some(p=>p.key===background.portrait))state.background.portrait=background.portrait;
    state.background.x=number(background.x,-3840,3840,0);state.background.y=number(background.y,-2160,2160,0);state.background.scale=number(background.scale,.15,4,1);
    if(typeof value.customTitle==='string'&&value.customTitle.length<=1000000&&/^data:image\/(png|webp);base64,[a-z0-9+/]+=*$/i.test(value.customTitle))state.customTitle=value.customTitle;
    const reference=model.character.id===9296&&(!state.titleName||state.titleName===model.character.name);
    state.titleMode=['text','image','reference'].includes(value.titleMode)?value.titleMode:state.customTitle?'image':reference?'reference':'text';
    if(state.titleMode==='reference'&&!reference)state.titleMode='text';
    if(['sans','serif'].includes(value.titleFont))state.titleFont=value.titleFont;
    state.titleImageTint=value.titleImageTint===true;
    if(['sans','serif'].includes(value.bodyFont))state.bodyFont=value.bodyFont;state.bodyBold=value.bodyBold===true;state.bodyItalic=value.bodyItalic===true;state.bodyOutlineWidth=number(value.bodyOutlineWidth,0,2,0);state.bodyOutlineColor=/^#[0-9a-f]{6}$/i.test(value.bodyOutlineColor||'')?value.bodyOutlineColor:state.bodyOutlineColor;
    state.titleItalic=value.titleItalic===true;state.titleBold=value.titleBold===true;state.titleShadow=value.titleShadow!==false;
    state.titleScale=number(value.titleScale,.5,1,1);state.titleOutlineWidth=number(value.titleOutlineWidth,0,8,0);
    state.titleOutlineColor=/^#[0-9a-f]{6}$/i.test(value.titleOutlineColor||'')?value.titleOutlineColor:state.titleOutlineColor;
    state.branchWidth=number(value.branchWidth,.5,5,1.5);state.branchLength=number(value.branchLength,0,100,100);
    state.generatedDate=validDate(value.generatedDate)?value.generatedDate:'';state.datePrefix=short(value.datePrefix,24).replace(/[\r\n]/g,' ');
    state.topText=short(value.topText,80).replace(/[\r\n]/g,' ');state.topTextX=number(value.topTextX,24,1850,1000);state.topTextY=number(value.topTextY,8,158,152);state.topTextSize=number(value.topTextSize,12,40,22);
    state.topTextColor=/^#[0-9a-f]{6}$/i.test(value.topTextColor||'')?value.topTextColor:state.topTextColor;
    state.backgroundOpacity=number(value.backgroundOpacity??value.brightness,0,1,.65);state.panelOpacity=number(value.panelOpacity,0,1,.92);state.markWidth=number(value.markWidth,1,6,3);state.exclusive=validEquipment(value.exclusive)?value.exclusive:null;
    if(object(value.marks))for(const skill of [...model.skills,...(model.liberations||[])])if(canMark(model,skill.id)&&['required','optional'].includes(value.marks[skill.id]))state.marks[skill.id]=value.marks[skill.id];
    state.loadouts=state.loadouts.map((row,i)=>{
      const saved=value.loadouts?.[i];if(!object(saved))return row;
      const used=new Set();return {name:short(saved.name,24,row.name),slots:row.slots.map((fallback,j)=>{
        const id=saved.slots?.[j];if(id===null)return null;
        if(pool(model,j).some(s=>s.id===id)&&!used.has(id)){used.add(id);return id;}
        return fallback;
      })};
    });
    state.weapons=list(value.weapons,id=>validEquipment(id));state.accessories=list(value.accessories,id=>validEquipment(id,true));
    state.tarot=list(value.tarot,id=>catalog.tarot.some(t=>t.id===id));
    const selections=Array.isArray(value.engravings)?value.engravings:(value.engraving?[{id:value.engraving,note:''}]:[]),seen=new Set();
    for(const item of selections){if(!object(item)||seen.has(item.id)||!catalog.engravings.some(e=>e.id===item.id))continue;seen.add(item.id);state.engravings.push({id:item.id,note:short(item.note,200)});}
    for(const key of ['weapons','accessories','tarot']){state.gearNotes[key]=Array.from({length:state[key].length},(_,i)=>short(value.gearNotes?.[key]?.[i],24));state.groupNotes[key]=short(value.groupNotes?.[key],80);}
    state.scores=axes.map((_,i)=>Math.round(number(value.scores?.[i],0,5,0)*2)/2);state.rated=value.rated===true;
    state.scoreText=short(value.scoreText,320);
    return state;
  }
  function canMark(model,id){
    const initial=model.initialSkillIds||model.tiers?.find(t=>t.rank===0)?.skills.filter(Boolean).map(s=>s.id)||[model.initialBasic];
    return !!id&&((model.liberations||[]).some(s=>s.id===id)||model.skills.some(s=>s.id===id)&&!initial.includes(id));
  }
  function cycleMark(state,model,id){
    if(!canMark(model,id))return false;
    const next={required:'optional',optional:null}[state.marks[id]]??(state.marks[id]==='optional'?null:'required');
    if(next)state.marks[id]=next;else delete state.marks[id];return true;
  }
  function setSlot(state,model,row,index,id){
    if(!Number.isInteger(row)||row<0||row>2||!Number.isInteger(index)||index<0||index>4)return false;
    if(id!==null&&!pool(model,index).some(s=>s.id===id))return false;
    const slots=state.loadouts[row].slots,old=slots[index],other=id===null?-1:slots.indexOf(id);
    slots[index]=id;if(other!==-1&&other!==index)slots[other]=old;return true;
  }
  function moveSlot(state,row,index,delta){
    const target=index+delta;if(row<0||row>2||index<2||index>4||target<2||target>4)return false;
    const s=state.loadouts[row].slots;[s[index],s[target]]=[s[target],s[index]];return true;
  }
  const layoutKeys=['logo','title','subtitle','cv','sprite','badges','role','topText','tree','trait','exclusive','loadouts','gear','scores','stats','engravings','notes','author','date'];
  function layoutRect(v){const w=number(v.w,20,1920,200),h=number(v.h,16,1080,100);return {x:number(v.x,0,1920-w,0),y:number(v.y,0,1080-h,0),w,h};}
  // edges: {x:-1|0|1, y:-1|0|1} — -1 moves the leading edge, 1 the trailing edge, 0 leaves the axis alone.
  function snapLayout(rect,others,resize=false,enabled=true,edges=null){
    const r=layoutRect(rect),guides=[];if(!enabled)return {rect:r,guides};
    const axis=(key,fallback)=>resize?Math.sign(Number(edges?.[key]??fallback)||0):0;
    for(const [key,size,limit,edge] of [['x','w',1920,axis('x',1)],['y','h',1080,axis('y',1)]]){
      const targets=[0,limit/2,limit,...others.flatMap(o=>[o[key],o[key]+o[size]/2,o[key]+o[size]])];
      const sources=edge>0?[r[key]+r[size]]:edge<0?[r[key]]:[r[key],r[key]+r[size]/2,r[key]+r[size]];
      let best=9,delta=0,guide=null;
      for(const source of sources)for(const target of targets){const d=target-source;if(Math.abs(d)<best){best=Math.abs(d);delta=d;guide=target;}}
      if(guide===null)continue;
      if(edge>0)r[size]+=delta;
      else if(edge<0){const start=Math.max(0,r[key]+delta);r[size]=Math.max(20,r[key]+r[size]-start);r[key]=start;}
      else r[key]+=delta;
      guides.push({axis:key,value:guide});
    }
    return {rect:layoutRect(r),guides};
  }
  const baseStatDefinitions=[['attack','物攻'],['magic','魔攻'],['agility','速度'],['movement','移动'],['jump','跳跃']];
  function baseStats(character,fields={}){const text=v=>String(v??'').trim();return {attack:text(character.stats?.['物攻']||fields['满级满星物攻']),magic:text(character.stats?.['魔攻']||fields['满级满星魔攻']),agility:text(character.stats?.['敏捷']||fields['满级满星敏捷']||fields['初始敏捷']),movement:text(fields['移动']),jump:text(fields['跳跃高度']),jumpFar:text(fields['跳跃远度'])};}
  function statRatio(value,max){const n=Number(value),m=Number(max);return String(value??'').trim()!==''&&Number.isFinite(n)&&n>=0&&Number.isFinite(m)&&m>0?Math.min(100,n/m*100):null;}
  function validDate(value){if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value))return false;const d=new Date(value+'T12:00:00Z');return Number.isFinite(d.getTime())&&d.toISOString().slice(0,10)===value;}
  function posterDate(state,now=new Date()){return validDate(state.generatedDate)?state.generatedDate:[now.getFullYear(),String(now.getMonth()+1).padStart(2,'0'),String(now.getDate()).padStart(2,'0')].join('-');}
  function branchEnds(center,cx,width=3,length=100){const sign=Math.sign(cx-center),start=center+sign*22,limit=cx-sign*(30.5+width/2+3);return {start,end:start+(limit-start)*length/100};}
  function branchSpan(rank){return [1,5,9].includes(rank)?65:rank===0?89:109;}
  function backgroundRect(width,height,background){
    const base=Math.max(1250/width,1080/height),baseW=width*base,baseH=height*base;
    const cx=1325+background.x,cy=-(baseH-1080)*.24+baseH/2+background.y;
    const w=baseW*background.scale,h=baseH*background.scale;
    return {x:cx-w/2,y:cy-h/2,w,h,naturalWidth:width,naturalHeight:height};
  }
  function zoomBackground(background,rect,factor,anchor){
    const scale=number(background.scale*factor,.15,4,background.scale),ratio=scale/background.scale;
    return {...background,scale,x:number(background.x+(1-ratio)*(anchor.x-(rect.x+rect.w/2)),-3840,3840,0),y:number(background.y+(1-ratio)*(anchor.y-(rect.y+rect.h/2)),-2160,2160,0)};
  }
  return {baseStatDefinitions,baseStats,statRatio,layoutKeys,layoutRect,snapLayout,axes,ranks,treeNames,kind,pool,defaults,restore,canMark,cycleMark,setSlot,moveSlot,branchSpan,branchEnds,posterDate,validDate,backgroundRect,zoomBackground};
});
