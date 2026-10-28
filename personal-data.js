/* Versioned personal backups. Validation completes before any storage is changed. */
(function(root,factory){
  if(typeof module==='object'&&module.exports)module.exports=factory(require('./tools-core.js'));
  else root.WikiPersonal=factory(root.WikiToolRules);
})(typeof globalThis!=='undefined'?globalThis:this,function(R){
  'use strict';
  const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
  const own=(o,k)=>Object.prototype.hasOwnProperty.call(o,k);
  function fail(message){throw new Error(message);}
  function damageValues(value){
    if(!object(value))fail('伤害方案格式不正确');
    const result={};
    for(const [key,defaultValue] of Object.entries(R.defaults)){
      const v=own(value,key)?value[key]:defaultValue;
      if(key==='hornBuff'){if(typeof v!=='boolean')fail('号角选项格式不正确');result[key]=v;}
      else{if(!['string','number'].includes(typeof v)||String(v).length>250)fail('伤害方案参数格式不正确');result[key]=String(v);}
    }
    const classes=['none','crusher','defender','raider','watcher','destroyer'];
    if(!classes.includes(result.atkClass)||!classes.includes(result.defClass))fail('伤害方案职业无效');
    if(!['0','20','40','60'].includes(result.defDebuff))fail('防御减益选项无效');
    R.calculateDamage(result);return result;
  }
  function damageData(value){
    if(!object(value)||!Array.isArray(value.presets)||value.presets.length>20)fail('计算方案备份格式不正确（最多 20 个方案）');
    const names=new Set();
    const presets=value.presets.map(p=>{
      if(!object(p)||typeof p.name!=='string'||!p.name.trim()||p.name.length>40)fail('计算方案名称无效');
      const name=p.name.trim();if(names.has(name))fail('备份中存在重复的计算方案名称');names.add(name);
      return {name,values:damageValues(p.values)};
    });
    return {current:damageValues(value.current),presets};
  }
  function gachaData(value,data){
    if(!object(value)||value.sourceRevision!==data.revision)fail('邂逅记录的卡池版本与当前资料包不同，无法恢复该记录');
    if(!data.pools.some(p=>p.id===value.poolId))fail('邂逅记录的卡池无效');
    const saved=value.state;
    if(!object(saved)||saved.version!==1||!Number.isSafeInteger(saved.total)||saved.total<0||saved.total>1e9)fail('邂逅记录格式不正确');
    const restored=R.restoreSimulation(saved,data);
    if(restored.total!==saved.total||restored.pity!==saved.pity||
      Object.keys(restored.counts).some(k=>restored.counts[k]!==saved.counts?.[k])||
      data.pools.some(p=>restored.special[p.id]!==saved.special?.[p.id]))fail('邂逅记录计数不一致');
    if(!Array.isArray(saved.history)||saved.history.length>200||restored.history.length!==saved.history.length)fail('邂逅记录中含有无效的角色或历史条目');
    if(!object(saved.legendStats)||Object.values(restored.legendStats).reduce((a,b)=>a+b,0)!==saved.counts.legend)fail('传说角色统计与总数不一致');
    if(!Array.isArray(saved.owned)||saved.owned.some(n=>!data.characters.legend.some(c=>c.name===n)))fail('已获得角色名单无效');
    return {poolId:value.poolId,sourceRevision:value.sourceRevision,state:restored};
  }
  function parse(value,pages,tools){
    if(!object(value))fail('不是有效的备份文件');
    if(value.format==='socwiki-gacha')return {gacha:gachaData({sourceRevision:value.sourceRevision,poolId:value.poolId,state:value},tools)};
    if(value.format==='socwiki-damage'&&value.version===1)return {damage:damageData(value)};
    if(value.format!=='socwiki-personal'||![1,2].includes(value.version)||!Array.isArray(value.favorites)||!object(value.notes))fail('不是有效的铃兰档案馆备份文件');
    const ids=new Set(pages.map(p=>p.id)),characters=new Set(pages.filter(p=>p.type==='character').map(p=>p.id));
    const validIds=v=>Array.isArray(v)?[...new Set(v.filter(id=>Number.isInteger(id)&&ids.has(id)))]:[];
    const notes={};
    for(const [id,note] of Object.entries(value.notes)){
      if(!/^\d+$/.test(id)||!ids.has(Number(id)))continue;
      if(typeof note!=='string'||note.length>30000)fail('笔记格式无效或超过 30,000 字符');
      notes[id]=note;
    }
    const result={favorites:validIds(value.favorites),history:validIds(value.history).slice(0,50),notes};
    if(own(value,'comparison'))result.comparison=validIds(value.comparison).filter(id=>characters.has(id)).slice(0,3);
    if(value.version===2){
      if(object(value.preferences)){
        if(['light','dark'].includes(value.preferences.theme))result.theme=value.preferences.theme;
        if(Number.isInteger(value.preferences.readerFont)&&value.preferences.readerFont>=12&&value.preferences.readerFont<=22)result.readerFont=value.preferences.readerFont;
      }
      if(own(value,'tools')){
        if(!object(value.tools))fail('工具备份格式不正确');
        if(own(value.tools,'damage'))result.damage=damageData(value.tools.damage);
        if(own(value.tools,'gacha'))result.gacha=gachaData(value.tools.gacha,tools);
      }
    }
    return result;
  }
  function mergePresets(existing,incoming){
    const names=new Set(incoming.map(p=>p.name));
    return [...incoming,...(Array.isArray(existing)?existing:[]).filter(p=>p&&typeof p.name==='string'&&!names.has(p.name))].slice(0,20);
  }
  function commit(storage,entries){
    const previous=new Map(),written=[];
    try{
      for(const key of Object.keys(entries))previous.set(key,storage.getItem('socwiki.'+key));
      for(const [key,value] of Object.entries(entries)){storage.setItem('socwiki.'+key,JSON.stringify(value));written.push(key);}
    }catch(error){
      for(const key of written.reverse())try{const value=previous.get(key);if(value===null)storage.removeItem('socwiki.'+key);else storage.setItem('socwiki.'+key,value);}catch{}
      throw new Error('浏览器无法保存导入数据，请检查本地存储空间或权限');
    }
  }
  return {parse,damageValues,damageData,gachaData,mergePresets,commit};
});
