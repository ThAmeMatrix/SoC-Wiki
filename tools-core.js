/* Offline rules transcribed from the archived BWIKI widgets. Pure and testable. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.WikiToolRules = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const defaults = Object.freeze({atkClass:'none',atkPanel:'3000',atkBonusPct:'0',atkBonusFlat:'0',
    skillMult:'150',critDmgPct:'130',defClass:'none',defBase:'1200',ignoreDefPct:'0',defReduceFlat:'0',
    defDebuff:'0',hornBuff:false,dmgZone:'0',finalDmgZone:'0',vulnZone:'0',finalVulnZone:'0'});
  const labels = {atkPanel:'攻击面板',atkBonusPct:'攻击加成',atkBonusFlat:'固定攻击',skillMult:'技能倍率',
    critDmgPct:'暴击伤害',defBase:'防御面板',ignoreDefPct:'无视防御',defReduceFlat:'固定减防',
    defDebuff:'防御减益',dmgZone:'增伤区间',finalDmgZone:'最终增伤',vulnZone:'易伤区间',finalVulnZone:'最终易伤'};
  function invalid(field, message) {const e = new Error((labels[field] || field) + '：' + message);e.field = field;throw e;}
  function numbers(value, field, min = -100000, max = 100000) {
    const text = String(value ?? '').trim();
    if (!text) return [0];
    const items = text.split(/[,，]/);
    if (items.length > 30) invalid(field, '最多填写 30 个数值');
    return items.map(item => {
      const s = item.trim();
      if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)%?$/.test(s)) invalid(field, '请填写数字，多个数值用逗号分隔');
      const n = Number(s.replace('%',''));
      if (!Number.isFinite(n) || n < min || n > max) invalid(field, `数值须在 ${min} 到 ${max} 之间`);
      return n;
    });
  }
  function calculateDamage(input) {
    const f = {...defaults, ...input};
    const list = (key, min, max) => numbers(f[key], key, min, max);
    const scalar = (key, max=1e9) => {const a=list(key,0,max);if(a.length!==1)invalid(key,'此项只接受一个数值');return a[0];};
    const sum = a => a.reduce((x,y)=>x+y,0);
    const multiply = a => a.reduce((x,y)=>x*(1+y/100),1);
    const attack = scalar('atkPanel') * (1 + sum(list('atkBonusPct'))/100) + sum(list('atkBonusFlat',-1e9,1e9));
    const matchups = {crusher_defender:1.3,defender_crusher:.7,defender_raider:1.3,raider_defender:.7,
      raider_crusher:1.3,crusher_raider:.7,watcher_destroyer:1.4,destroyer_watcher:.6};
    const restraint = matchups[f.atkClass+'_'+f.defClass] || 1;
    const defenseBase = scalar('defBase');
    const debuff = scalar('defDebuff',100);
    const horn = f.hornBuff === true;
    const defenseReduction = defenseBase*(debuff/100+(horn?.2:0)) + scalar('defReduceFlat');
    const ignore = list('ignoreDefPct',0,100).reduce((n,p)=>n*(1-p/100),1);
    const defense = Math.max(0,defenseBase-defenseReduction)*ignore;
    const base = Math.max(0,attack*restraint-defense);
    const skill = scalar('skillMult',100000)/100;
    const bonus = Math.max(.5,1+sum(list('dmgZone'))/100);
    const finalBonus = multiply(list('finalDmgZone',-100));
    const vulnerability = Math.min(3,multiply(list('vulnZone',-100))*(horn?1.8:1));
    const finalVulnerability = multiply(list('finalVulnZone',-100));
    const critical = sum(list('critDmgPct',-100))/100;
    if (critical<0) invalid('critDmgPct','合计不能小于 0');
    const damage = Math.max(0,base*skill*bonus*finalBonus*vulnerability*finalVulnerability);
    if (!Number.isFinite(damage*critical) || damage*Math.max(1,critical)>Number.MAX_SAFE_INTEGER) invalid('skillMult','结果过大，请检查各区间输入');
    return {damage:Math.round(damage),criticalDamage:Math.round(damage*critical),attack,restraint,defense,
      defenseReduction,ignore,base,skill,bonus,finalBonus,vulnerability,finalVulnerability,critical};
  }
  function newSimulation(data) {
    return {version:1,total:0,pity:0,special:Object.fromEntries(data.pools.map(p=>[p.id,0])),
      counts:{legend:0,epic:0,elite:0,common:0},owned:[],legendStats:{},history:[]};
  }
  function restoreSimulation(saved, data) {
    const fresh = newSimulation(data);
    if (!saved || saved.version!==1) return fresh;
    const integer = (v,max) => Number.isSafeInteger(v)&&v>=0&&v<=max;
    if (!integer(saved.total,1e9) || !integer(saved.pity,99)) return fresh;
    if (!data.pools.every(p=>integer(saved.special?.[p.id],179))) return fresh;
    if (!Object.keys(fresh.counts).every(k=>integer(saved.counts?.[k],saved.total))) return fresh;
    if (Object.values(saved.counts).reduce((a,b)=>a+b,0)!==saved.total) return fresh;
    const legends = new Set(data.characters.legend.map(c=>c.name));
    fresh.total=saved.total;fresh.pity=saved.pity;
    for(const p of data.pools)fresh.special[p.id]=saved.special[p.id];
    for(const k of Object.keys(fresh.counts))fresh.counts[k]=saved.counts[k];
    fresh.owned=Array.isArray(saved.owned)?saved.owned.filter(n=>legends.has(n)):[];
    for(const name of legends)if(integer(saved.legendStats?.[name],saved.total)&&saved.legendStats[name])fresh.legendStats[name]=saved.legendStats[name];
    fresh.history=Array.isArray(saved.history)?saved.history.filter(h=>h && integer(h.number,saved.total) &&
      data.pools.some(p=>p.id===h.pool) && data.characters[h.rarity]?.some(c=>c.name===h.name)).slice(0,200).map(h=>({
        number:h.number,name:h.name,rarity:h.rarity,pool:h.pool,isUp:h.isUp===true,guarantee:['up','legend'].includes(h.guarantee)?h.guarantee:''})):[];
    return fresh;
  }
  function draw(saved, poolId, count, data, random = Math.random) {
    if (![1,10,100].includes(count)) throw new Error('不支持的模拟次数');
    const pool = data.pools.find(p=>p.id===poolId);
    if (!pool) throw new Error('卡池不存在');
    const state = restoreSimulation(saved,data), results=[];
    // The archived widget excludes all displayed UP characters from its non-UP pool.
    const allUp = new Set(data.pools.flatMap(p=>p.up));
    const nonUp = data.characters.legend.filter(c=>!allUp.has(c.name));
    const roll = () => {const n=random();if(!Number.isFinite(n)||n<0||n>=1)throw new Error('随机数超出范围');return n;};
    const pick = array => {if(!array.length)throw new Error('卡池没有可选角色');return array[Math.floor(roll()*array.length)];};
    for(let i=0;i<count;i++) {
      state.total++;state.pity++;state.special[poolId]++;
      let rarity='common',character,guarantee='',isUp=false;
      if(state.special[poolId]>=180) {
        guarantee='up';rarity='legend';
        const unowned=pool.up.filter(n=>!state.owned.includes(n));
        const name=pick(unowned.length?unowned:pool.up);
        character=data.characters.legend.find(c=>c.name===name);isUp=true;
      } else {
        const chance=state.pity>=100?0:roll();
        if(state.pity>=100)guarantee='legend';
        rarity=chance<.02?'legend':chance<.22?'epic':chance<.62?'elite':'common';
        if(rarity==='legend') {
          isUp=roll()<pool.upRate;
          if(isUp){const name=pick(pool.up);character=data.characters.legend.find(c=>c.name===name);}
          else character=pick(nonUp);
        }else character=pick(data.characters[rarity]);
      }
      if(!character)throw new Error('卡池角色数据缺失');
      if(rarity==='legend') {
        state.pity=0;
        if(!state.owned.includes(character.name))state.owned.push(character.name);
        state.legendStats[character.name]=(state.legendStats[character.name]||0)+1;
      }
      if(isUp)state.special[poolId]=0;
      state.counts[rarity]++;
      const item={number:state.total,name:character.name,rarity,pool:poolId,isUp,guarantee};
      results.push(item);state.history.unshift(item);
    }
    state.history=state.history.slice(0,200);
    return {state,results};
  }
  return {defaults,labels,calculateDamage,newSimulation,restoreSimulation,draw};
});
