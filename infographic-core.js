/* Shared selection rules for the offline character poster. */
(function(root,factory){
  if(typeof module==='object'&&module.exports)module.exports=factory();
  else root.WikiInfographicRules=factory();
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  const axes=['DOT','直伤','穿伤','辅助','生存','控制'];
  const axisLimits={min:3,max:8,label:10};
  const chartLimits={max:3,name:16,scoreMin:1,scoreMax:1000};
  const chartMax=v=>Number.isFinite(Number(v))?Math.min(chartLimits.scoreMax,Math.max(chartLimits.scoreMin,Math.round(Number(v)))):5;
  const chartUnit=v=>v==='percent'?'percent':'number';
  // Chart axes keep their slot even when the name is cleared, so an unnamed axis
  // never removes the whole chart.
  function chartAxes(value,max=5){
    if(!Array.isArray(value))return null;
    const axes=[];
    for(const item of value){
      const source=object(item)?item:{name:item};
      // Every axis may carry its own ceiling; otherwise it follows the chart's.
      const own=source.max===undefined||source.max===null||source.max===''?null:chartMax(source.max);
      const limit=own||max;
      axes.push({name:cleanName(source.name,axisLimits.label),max:limit,score:score(source.score,limit)});
      if(axes.length>=axisLimits.max)break;
    }
    return axes.length>=axisLimits.min?axes:null;
  }
  const RICH_TAGS=new Set(['B','STRONG','I','EM','U','S','SPAN','BR','DIV','P','UL','OL','LI']);
  // Only a small formatting subset survives: the notes editor accepts pasted HTML.
  function sanitizeRich(html){
    let out=String(html??'')
      .replace(/<\s*(script|style|iframe|object|embed|link|meta)[^>]*>[\s\S]*?<\s*\/\s*\1\s*>/gi,'')
      .replace(/<\s*(script|style|iframe|object|embed|link|meta)[^>]*\/?\s*>/gi,'')
      .replace(/\son\w+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi,'')
      .replace(/\s(?:src|href)\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi,'')
      .replace(/<font[^>]*\scolor\s*=\s*("|')?(#[0-9a-fA-F]{3,8}|rgb\([^)]*\)|[a-z]+)\1[^>]*>/gi,'<span style="color:$2">')
      .replace(/<\/font>/gi,'</span>');
    out=out.replace(/<\s*([a-zA-Z0-9]+)([^>]*)>/g,(match,tag,attrs)=>{
      const name=tag.toUpperCase();
      if(!RICH_TAGS.has(name))return '';
      if(name==='SPAN'){
        // The declaration sits inside quotes; read it before matching properties.
        const decl=/(?:^|\s)style\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/i.exec(attrs);
        const value=decl?(decl[1]??decl[2]??decl[3]??''):'';
        const color=/(?:^|;)\s*color\s*:\s*([^;]+)/i.exec(value),size=/(?:^|;)\s*font-size\s*:\s*(\d+(?:\.\d+)?)px/i.exec(value);
        const weight=/(?:^|;)\s*font-weight\s*:\s*([^;]+)/i.exec(value),slant=/(?:^|;)\s*font-style\s*:\s*([^;]+)/i.exec(value);
        const style=[color?'color:'+color[1].trim():'',size?'font-size:'+size[1]+'px':'',
          weight?'font-weight:'+weight[1].trim():'',slant?'font-style:'+slant[1].trim():''].filter(Boolean).join(';');
        return style?'<span style="'+style+'">':'<span>';
      }
      return '<'+name.toLowerCase()+'>';
    });
    return out.replace(/<\s*\/\s*([a-zA-Z0-9]+)\s*>/g,(match,tag)=>RICH_TAGS.has(tag.toUpperCase())?'</'+tag.toLowerCase()+'>':'');
  }
  // Free text understands **bold**, *italic* and {金|coloured}; plain text stays plain.
  const richColors={'金':'#e7c479','红':'#ff9292','橙':'#ff997d','青':'#85d5e7','绿':'#a7dea0','蓝':'#79d1f2','紫':'#d7b1f3','白':'#edf2f0'};
  function richRuns(text,base=null){
    const source=String(text??''),runs=[];
    let buffer='',index=0;
    const flush=(value,bold,italic,color)=>{if(value)runs.push({text:value,bold:!!bold,italic:!!italic,color:color||base});};
    while(index<source.length){
      const rest=source.slice(index);
      if(rest.startsWith('**')){
        const end=source.indexOf('**',index+2);
        if(end>index+1){flush(buffer,false,false,base);buffer='';flush(source.slice(index+2,end),true,false,base);index=end+2;continue;}
      }
      if(source[index]==='*'){
        const end=source.indexOf('*',index+1);
        if(end>index){flush(buffer,false,false,base);buffer='';flush(source.slice(index+1,end),false,true,base);index=end+1;continue;}
      }
      if(source[index]==='{'){
        const bar=source.indexOf('|',index+1),close=source.indexOf('}',index+1);
        if(bar>index&&close>bar){
          const name=source.slice(index+1,bar).trim();
          if(richColors[name]){flush(buffer,false,false,base);buffer='';flush(source.slice(bar+1,close),false,false,richColors[name]);index=close+1;continue;}
        }
      }
      buffer+=source[index];index++;
    }
    flush(buffer,false,false,base);
    return runs.length?runs:[{text:source,bold:false,italic:false,color:base}];
  }
  const imageData=v=>typeof v==='string'&&/^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+$/.test(v)&&v.length<12*1024*1024?v:null;
  const cleanName=(v,limit)=>String(v??'').replace(/[\r\n\t]/g,' ').trim().slice(0,limit);
  const score=(v,max=5)=>Math.round(number(v,0,max,0)*2)/2;
  function radarAxes(value){
    if(!Array.isArray(value))return null;
    const names=[];
    for(const item of value){
      const name=cleanName(typeof item==='string'?item:item?.name,axisLimits.label);
      if(name)names.push(name);
      if(names.length>=axisLimits.max)break;
    }
    return names.length>=axisLimits.min?names:null;
  }
  // Extra radars keep the built-in six untouched: each holds its own name, axes and scores.
  function radarChart(value){
    if(!object(value))return null;
    const max=chartMax(value.max),axes=chartAxes(value.axes,max);
    if(!axes)return null;
    return {name:cleanName(value.name,chartLimits.name),max,unit:chartUnit(value.unit),axes};
  }
  function radarCharts(value){
    const source=Array.isArray(value)?value:value?.radarCharts;
    if(!Array.isArray(source))return [];
    const result=[];
    for(const item of source){const chart=radarChart(item);if(chart)result.push(chart);if(result.length>=chartLimits.max)break;}
    return result;
  }
  function addRadarChart(state,name=''){
    const charts=radarCharts(state.radarCharts);
    if(charts.length>=chartLimits.max)return false;
    let label=cleanName(name,chartLimits.name)||('自定义雷达 '+(charts.length+1)),index=charts.length+2;
    const used=new Set(charts.map(c=>c.name));
    while(used.has(label))label='自定义雷达 '+index++;
    charts.push({name:label,max:5,unit:'number',axes:['维度一','维度二','维度三'].map(name=>({name,score:0}))});
    state.radarCharts=charts;
    return true;
  }
  function removeRadarChart(state,index){
    const charts=radarCharts(state.radarCharts);
    if(!Number.isInteger(index)||index<0||index>=charts.length)return false;
    charts.splice(index,1);state.radarCharts=charts;return true;
  }
  function renameRadarChart(state,index,name){
    const charts=radarCharts(state.radarCharts);
    if(!Number.isInteger(index)||index<0||index>=charts.length)return false;
    charts[index].name=cleanName(name,chartLimits.name);state.radarCharts=charts;return true;
  }
  function addRadarAxis(state,chart,name=''){
    const charts=radarCharts(state.radarCharts),target=charts[chart];
    if(!target||target.axes.length>=axisLimits.max)return false;
    const used=new Set(target.axes.map(a=>a.name));
    let label=cleanName(name,axisLimits.label)||'新维度',index=2;
    while(used.has(label))label='新维度 '+index++;
    target.axes.push({name:label,score:0});state.radarCharts=charts;return true;
  }
  function removeRadarAxis(state,chart,index){
    const charts=radarCharts(state.radarCharts),target=charts[chart];
    if(!target||!Number.isInteger(index)||index<0||index>=target.axes.length||target.axes.length<=axisLimits.min)return false;
    target.axes.splice(index,1);state.radarCharts=charts;return true;
  }
  function renameRadarAxis(state,chart,index,name){
    const charts=radarCharts(state.radarCharts),target=charts[chart];
    if(!target||!Number.isInteger(index)||index<0||index>=target.axes.length)return false;
    target.axes[index].name=cleanName(name,axisLimits.label);state.radarCharts=charts;return true;
  }
  function setRadarScore(state,chart,index,value){
    const charts=radarCharts(state.radarCharts),target=charts[chart];
    if(!target||!Number.isInteger(index)||index<0||index>=target.axes.length)return false;
    const limit=target.axes[index]?.max||target.max||5;
    target.axes[index].score=score(value,limit);state.radarCharts=charts;return true;
  }
  function setRadarMax(state,chart,value){
    const charts=radarCharts(state.radarCharts),target=charts[chart];
    if(!target||!Number.isInteger(chart)||chart<0||chart>=charts.length)return false;
    const max=chartMax(value);target.max=max;
    // The chart ceiling becomes every axis' ceiling; scores stay inside it.
    target.axes=target.axes.map(axis=>({...axis,max,score:score(axis.score,max)}));
    state.radarCharts=charts;return true;
  }
  function setRadarAxisMax(state,chart,index,value){
    const charts=radarCharts(state.radarCharts),target=charts[chart];
    if(!target||!Number.isInteger(index)||index<0||index>=target.axes.length)return false;
    const max=chartMax(value);
    target.axes[index].max=max;target.axes[index].score=score(target.axes[index].score,max);
    state.radarCharts=charts;return true;
  }
  function setRadarUnit(state,chart,value){
    const charts=radarCharts(state.radarCharts),target=charts[chart];
    if(!target)return false;
    target.unit=chartUnit(value);state.radarCharts=charts;return true;
  }
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
  function loadout(model,index=0){return {name:'搭配 '+(index+1),slots:[model.initialBasic||null,null,null,null,null]};}
  function commentary(value={}){
    if(!object(value))value={};const color=(v,fallback)=>/^#[0-9a-f]{6}$/i.test(v||'')?v:fallback;
    return {enabled:value.enabled===true,text:short(value.text,2400),font:['sans','serif'].includes(value.font)?value.font:'sans',size:number(value.size,10,48,18),color:color(value.color,'#e9efed'),bold:value.bold===true,italic:value.italic===true,align:['left','center','right'].includes(value.align)?value.align:'left',lineHeight:number(value.lineHeight,1,2.4,1.5),outlineWidth:number(value.outlineWidth,0,3,0),outlineColor:color(value.outlineColor,'#071018')};
  }
  function addLoadout(state,model){let index=state.loadouts.length;while(state.loadouts.some(row=>row.name==='搭配 '+(index+1)))index++;state.loadouts.push(loadout(model,index));return true;}
  function removeLoadout(state,index){if(!Number.isInteger(index)||index<0||index>=state.loadouts.length||state.loadouts.length<=1)return false;state.loadouts.splice(index,1);return true;}

  function defaults(model){
    return {version:6,canvas:{width:1920,height:1080},composition:'auto',decoration:{style:'gilded',intensity:.65},background:{portrait:model.character.portraits?.some(p=>p.key==='awakened')?'awakened':'base',x:0,y:0,scale:1},customTitle:null,titleName:'',titleMode:model.character.id===9296?'reference':'text',titleFont:'serif',bodyFont:'sans',bodyBold:false,bodyItalic:false,bodyOutlineWidth:0,bodyOutlineColor:'#071018',titleItalic:false,titleBold:false,titleScale:1,titleOutlineWidth:0,titleOutlineColor:'#08121b',titleShadow:true,generatedDate:'',datePrefix:'',roleText:'',layout:{},topText:'',topTextX:1000,topTextY:152,topTextSize:22,topTextColor:'#e8dbc0',branchWidth:1.5,branchLength:100,titleImageTint:false,characterId:model.character.id,subtitle:'角色养成一图流',titleColor:'#ef9b73',treeNotes:'',author:'',authorFont:'signature',authorMode:'text',authorImage:null,authorCustomFont:null,notes:'',
      backgroundOpacity:.65,panelOpacity:.92,markWidth:3,gearIconSize:40,radarTitle:'',notesSize:15,exclusive:null,marks:{},loadouts:[loadout(model)],loadoutCommentary:commentary(),
      weapons:[null],accessories:[null],tarot:[null],engravings:[],gearNotes:{weapons:[''],accessories:[''],tarot:['']},groupNotes:{weapons:'',accessories:'',tarot:''},scores:[0,0,0,0,0,0],rated:false,scoreText:'',radarCharts:[],backgroundImage:null};
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
    state.canvas=canvasSize(value.canvas);state.composition=['auto','spotlight','information'].includes(value.composition)?value.composition:'auto';
    state.decoration={style:value.decoration?.style==='plain'?'plain':'gilded',intensity:number(value.decoration?.intensity,0,1,.65)};
    state.roleText=short(value.roleText,100);
    if(object(value.layout))for(const key of layoutKeys)if(object(value.layout[key]))state.layout[key]=layoutRect(value.layout[key],state.canvas);
    state.author=short(value.author,24);state.notes=short(value.notes,320);
    state.authorMode=value.authorMode==='image'?'image':'text';
    state.authorFont=['signature','serif','sans','custom'].includes(value.authorFont)?value.authorFont:'signature';
    if(typeof value.authorImage==='string'&&value.authorImage.length<=1000000&&/^data:image\/(png|webp);base64,[a-z0-9+/]+=*$/i.test(value.authorImage))state.authorImage=value.authorImage;
    if(object(value.authorCustomFont)&&typeof value.authorCustomFont.data==='string'&&value.authorCustomFont.data.length<=12000000&&/^data:font\/(ttf|otf|woff2?);base64,[a-z0-9+/]+=*$/i.test(value.authorCustomFont.data))state.authorCustomFont={name:short(value.authorCustomFont.name,100,'自定义字体'),data:value.authorCustomFont.data};
    if(state.authorFont==='custom'&&!state.authorCustomFont)state.authorFont='signature';
    const background=object(value.background)?value.background:{};
    if(['base','awakened'].includes(background.portrait)&&model.character.portraits?.some(p=>p.key===background.portrait))state.background.portrait=background.portrait;
    // A custom background only sticks around while its image is still in the draft.
    state.backgroundImage=imageData(value.backgroundImage);
    if(background.portrait==='custom'&&state.backgroundImage)state.background.portrait='custom';
    state.background.x=number(background.x,-state.canvas.width*2,state.canvas.width*2,0);state.background.y=number(background.y,-state.canvas.height*2,state.canvas.height*2,0);state.background.scale=number(background.scale,.15,4,1);
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
    state.topText=short(value.topText,80).replace(/[\r\n]/g,' ');state.topTextX=number(value.topTextX,0,state.canvas.width-20,Math.min(1000,state.canvas.width-20));state.topTextY=number(value.topTextY,0,state.canvas.height-20,152);state.topTextSize=number(value.topTextSize,12,40,22);
    state.topTextColor=/^#[0-9a-f]{6}$/i.test(value.topTextColor||'')?value.topTextColor:state.topTextColor;
    state.backgroundOpacity=number(value.backgroundOpacity??value.brightness,0,1,.65);state.panelOpacity=number(value.panelOpacity,0,1,.92);state.markWidth=number(value.markWidth,1,6,3);state.gearIconSize=number(value.gearIconSize,20,96,40);state.radarTitle=short(value.radarTitle,16);state.notesSize=number(value.notesSize,10,28,15);state.exclusive=validEquipment(value.exclusive)?value.exclusive:null;
    if(object(value.marks))for(const skill of [...model.skills,...(model.liberations||[])])if(canMark(model,skill.id)&&['required','optional'].includes(value.marks[skill.id]))state.marks[skill.id]=value.marks[skill.id];
    state.loadoutCommentary=commentary(value.loadoutCommentary);
    const savedLoadouts=Array.isArray(value.loadouts)&&value.loadouts.length?value.loadouts:[null];
    state.loadouts=savedLoadouts.map((saved,i)=>{
      const row=loadout(model,i);if(!object(saved))return row;
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
    // The built-in radar always keeps its original six axes; extra charts are separate.
    state.scores=axes.map((_,i)=>Math.round(number(value.scores?.[i],0,5,0)*2)/2);state.rated=value.rated===true;
    state.radarCharts=radarCharts(value.radarCharts);
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
    if(!Number.isInteger(row)||row<0||row>=state.loadouts.length||!Number.isInteger(index)||index<0||index>4)return false;
    if(id!==null&&!pool(model,index).some(s=>s.id===id))return false;
    const slots=state.loadouts[row].slots,old=slots[index],other=id===null?-1:slots.indexOf(id);
    slots[index]=id;if(other!==-1&&other!==index)slots[other]=old;return true;
  }
  function moveSlot(state,row,index,delta){
    const target=index+delta;if(!Number.isInteger(row)||row<0||row>=state.loadouts.length||!Number.isInteger(index)||!Number.isInteger(delta)||index<2||index>4||target<2||target>4)return false;
    const s=state.loadouts[row].slots;[s[index],s[target]]=[s[target],s[index]];return true;
  }
  const layoutKeys=['logo','title','subtitle','cv','sprite','badges','role','topText','tree','trait','exclusive','loadouts','loadoutNotes','gear','scores','radar','stats','engravings','notes','author','date'];
  function canvasSize(value={}){return {width:Math.round(number(value?.width,480,4096,1920)),height:Math.round(number(value?.height,320,8192,1080))};}
  function layoutRect(v,canvas){const {width:W,height:H}=canvasSize(canvas),w=number(v.w,20,W,200),h=number(v.h,16,H,100);return {x:number(v.x,0,W-w,0),y:number(v.y,0,H-h,0),w,h};}
  // edges: {x:-1|0|1, y:-1|0|1} — -1 moves the leading edge, 1 the trailing edge, 0 leaves the axis alone.
  function snapLayout(rect,others,resize=false,enabled=true,edges=null,canvas){
    const {width:W,height:H}=canvasSize(canvas),r=layoutRect(rect,canvas),guides=[];if(!enabled)return {rect:r,guides};
    const axis=(key,fallback)=>resize?Math.sign(Number(edges?.[key]??fallback)||0):0;
    for(const [key,size,limit,edge] of [['x','w',W,axis('x',1)],['y','h',H,axis('y',1)]]){
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
    return {rect:layoutRect(r,canvas),guides};
  }
  const combatStatDefinitions=[['attack','物攻'],['magic','魔攻'],['defense','物防'],['resistance','魔防'],['health','生命'],['agility','速度']];
  const mobilityStatDefinitions=[['movement','移动'],['jump','跳跃']];
  const baseStatDefinitions=[...combatStatDefinitions,...mobilityStatDefinitions];
  const speedIconPath='M3 5C10 8 17 6 23 2C21 9 16 13 8 12L11 16C16 16 19 13 21 11C20 17 17 20 13 20L15 25C9 21 5 14 3 5ZM6 6L12 23L10 13Z';
  function baseStats(character,fields={}){const text=v=>String(v??'').trim();return {attack:text(character.stats?.['物攻']||fields['满级满星物攻']),magic:text(character.stats?.['魔攻']||fields['满级满星魔攻']),defense:text(character.stats?.['物防']||fields['满级满星物防']),resistance:text(character.stats?.['魔防']||fields['满级满星魔防']),health:text(character.stats?.['生命']||fields['满级满星生命']),agility:text(character.stats?.['敏捷']||fields['满级满星敏捷']||fields['初始敏捷']),movement:text(fields['移动']),jump:text(fields['跳跃高度']),jumpFar:text(fields['跳跃远度'])};}
  function statRatio(value,max){const n=Number(value),m=Number(max);return String(value??'').trim()!==''&&Number.isFinite(n)&&n>=0&&Number.isFinite(m)&&m>0?Math.min(100,n/m*100):null;}
  function validDate(value){if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value))return false;const d=new Date(value+'T12:00:00Z');return Number.isFinite(d.getTime())&&d.toISOString().slice(0,10)===value;}
  function posterDate(state,now=new Date()){return validDate(state.generatedDate)?state.generatedDate:[now.getFullYear(),String(now.getMonth()+1).padStart(2,'0'),String(now.getDate()).padStart(2,'0')].join('-');}
  function branchEnds(center,cx,width=3,length=100){const sign=Math.sign(cx-center),start=center+sign*22,limit=cx-sign*(30.5+width/2+3);return {start,end:start+(limit-start)*length/100};}
  function branchSpan(rank){return [1,5,9].includes(rank)?65:rank===0?89:109;}
  function backgroundRect(width,height,background,canvas,hero=null,contentBounds=null){
    const {width:W=1920,height:H=1080}=canvas||{},target=hero||{x:W*.365,y:0,w:W*.635,h:H};
    const bounds=contentBounds||{x:0,y:0,w:width,h:height},topAligned=!!hero&&bounds.h>bounds.w;
    let base=hero?Math.max(target.w/width,target.h/height)*(hero.focusScale||1):Math.max(1250/1920*W/width,H/height);
    // Tall artwork is framed from its visible top, not its centre. Bound the zoom
    // so a narrow portrait cannot put the entire upper body outside the viewport.
    if(topAligned)base=Math.min(base,target.h*(target.h>target.w?1.5:1.8)/bounds.h);
    const baseW=width*base,baseH=height*base;
    const cx=(topAligned?target.x+target.w/2+(width/2-bounds.x-bounds.w/2)*base:hero?target.x+target.w/2:1325/1920*W)+background.x;
    const cy=(topAligned?target.y+Math.max(hero.focusTop||0,Math.min(32,Math.max(12,target.h*.04)))-bounds.y*base+baseH/2:hero?target.y+target.h/2+(hero.focusY||0):-(baseH-H)*.24+baseH/2)+background.y;
    const w=baseW*background.scale,h=baseH*background.scale;
    return {x:cx-w/2,y:cy-h/2,w,h,naturalWidth:width,naturalHeight:height,contentBounds};
  }
  function zoomBackground(background,rect,factor,anchor,canvas){
    const {width:W,height:H}=canvasSize(canvas);
    const scale=number(background.scale*factor,.15,4,background.scale),ratio=scale/background.scale;
    return {...background,scale,x:number(background.x+(1-ratio)*(anchor.x-(rect.x+rect.w/2)),-W*2,W*2,0),y:number(background.y+(1-ratio)*(anchor.y-(rect.y+rect.h/2)),-H*2,H*2,0)};
  }
  return {canvasSize,commentary,addLoadout,removeLoadout,richRuns,richColors,richColorNames:Object.keys(richColors),sanitizeRich,radarChart,radarCharts,addRadarChart,removeRadarChart,renameRadarChart,addRadarAxis,removeRadarAxis,renameRadarAxis,setRadarScore,setRadarMax,setRadarAxisMax,setRadarUnit,chartAxes,chartMax,chartUnit,axisLimits,chartLimits,imageData,radarAxes,combatStatDefinitions,mobilityStatDefinitions,speedIconPath,baseStatDefinitions,baseStats,statRatio,layoutKeys,layoutRect,snapLayout,axes,ranks,treeNames,kind,pool,defaults,restore,canMark,cycleMark,setSlot,moveSlot,branchSpan,branchEnds,posterDate,validDate,backgroundRect,zoomBackground};
});
