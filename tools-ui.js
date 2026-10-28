/* UI for local tools. No third-party scripts, requests, accounts or payments. */
(() => {
  'use strict';
  const R=window.WikiToolRules, D=window.WIKI_TOOLS_DATA;
  let cleanup=()=>{};
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt=n=>Number(n||0).toLocaleString('zh-CN',{maximumFractionDigits:3});
  const rarityNames={legend:'传说',epic:'史诗',elite:'精英',common:'普通'};
  function download(name,text,type='application/json') {
    const url=URL.createObjectURL(new Blob([text],{type}));
    const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  const source=(id,title)=>`<div class="source-footer"><span>基于 BWIKI 原站工具快照重建 · 完全离线运行</span><a href="https://wiki.biligame.com/llzj/index.php?curid=${id}" target="_blank" rel="noopener noreferrer">${title}原站 ↗（需联网）</a></div>`;
  function render(type,root,h) {
    cleanup();const controller=new AbortController();cleanup=()=>controller.abort();
    const on=(event,fn)=>root.addEventListener(event,fn,{signal:controller.signal});
    const intro=(eyebrow,title,desc)=>h.intro(eyebrow,title,desc);
    const back='<a href="#/tools" class="page-back">← 返回离线工具</a>';
    if(!R||!D){root.innerHTML='<div class="empty-state"><h1>工具数据未能载入</h1><p>请完整解压离线包，保留 tools-core.js、tools-ui.js 和 data/tools.js。</p></div>';return;}
    if(type==='infographic'){const dispose=window.WikiInfographic.mount(root,h);cleanup=()=>{controller.abort();dispose();};}
    else if(type==='damage')damage();
    else if(type==='gacha')gacha();
    else if(type==='equipment')equipment();
    else root.innerHTML=`${intro('THE TRAVELER’S WORKBENCH','让每一步，都心中有数。','制作角色一图流，计算战斗伤害，模拟卡池结果。所有操作均在本机完成。')}<div class="tool-grid">${[
      ['infographic','feather','一图流工坊','以觉醒立绘为底，标注技能加点、编辑三套搭配，搭配专武、塔罗与刻印，制作自己的角色攻略。','技能树 · 六维能力 · 高清图片导出'],
      ['damage','compare','伤害计算器','逐项设置攻击、防御与伤害区间，实时查看普通伤害、暴击伤害和计算过程。','实时计算 · 方案保存 · 结果导出'],
      ['gacha','spark','邂逅模拟器','使用原站快照中的角色与卡池，单次或批量模拟，查看保底进度和完整统计。','双卡池 · 共享保底 · 本地记录'],
      ['equipment','sword','装备属性参考','按类型与稀有度查看原站记录的满级满星属性，直接定位同类装备。','原站数据 · 收录情况 · 快速查表'],
      ['compare','users','角色对比','从角色图鉴选择至多三位伙伴，横向对比满级满星属性与阵营信息。','176 位角色 · 属性对比']
    ].map(([key,ic,title,desc,tags])=>`<a class="tool-card" href="${key==='compare'?'#/compare':'#/tools/'+key}"><div class="tool-emblem">${h.icon(ic,28)}</div><span class="eyebrow">OFFLINE TOOL</span><h2>${title}</h2><p>${desc}</p><div class="tool-card-bottom"><small>${tags}</small>${h.icon('arrow',20)}</div></a>`).join('')}</div><div class="source-notice">${h.icon('archive',18)}卡池与公式按已收录规则计算；角色与条目资料可在资料馆信息中联网更新。每个工具内提供适用规则与原站出处。</div>`;

    function damage() {
      const saved=h.read('damage.current',{});
      let values={...R.defaults,...(saved&&typeof saved==='object'&&!Array.isArray(saved)?saved:{})};
      let presets=h.read('damage.presets',[]);
      if(!Array.isArray(presets))presets=[];
      presets=presets.filter(p=>p&&typeof p.name==='string'&&p.values&&typeof p.values==='object').slice(0,20);
      let result;
      const classes=[['none','无克制 / 异士'],['crusher','粉碎者'],['defender','防御者'],['raider','突袭者'],['watcher','守望者'],['destroyer','毁灭者']];
      const select=(id,label,options)=>`<label class="tool-field"><span>${label}</span><select id="${id}" name="${id}">${options.map(([v,t])=>`<option value="${v}" ${String(values[id])===v?'selected':''}>${t}</option>`).join('')}</select></label>`;
      const field=(id,label,hint,unit='%',single=false)=>`<label class="tool-field" for="${id}"><span>${label}${unit?`<small>${unit}</small>`:''}</span><input id="${id}" name="${id}" type="text" ${single?'inputmode="decimal"':''} value="${esc(values[id])}" maxlength="250" autocomplete="off" aria-describedby="${id}-hint"><small id="${id}-hint">${hint}</small></label>`;
      root.innerHTML=`${back}${intro('DAMAGE LAB','伤害，拆开来看。','填写面板与加成，普通和暴击伤害即时计算。多个效果用中英文逗号分隔，如 20, 30。')}<div class="damage-layout"><form id="damage-form" novalidate><section class="content-card"><div class="tool-section-heading"><span class="step-dot">01</span><h2>攻击方</h2><span>数值以战斗中面板为准</span></div><div class="tool-fields">${select('atkClass','攻击方职业',classes)}${field('atkPanel','攻击面板','按技能类型填写物攻或魔攻','',true)}${field('atkBonusPct','攻击加成','加算；不含面板中已计入的加成')}${field('atkBonusFlat','固定攻击加成','加算，可填写负值','')}${field('skillMult','技能倍率','150 代表 150%','%',true)}${field('critDmgPct','暴击伤害','默认 130；额外爆伤可填 130, 30')}</div></section><section class="content-card"><div class="tool-section-heading"><span class="step-dot">02</span><h2>防御方</h2></div><div class="tool-fields">${select('defClass','防御方职业',classes)}${field('defBase','防御面板','填写与伤害类型对应的物防或魔防','',true)}${field('ignoreDefPct','无视防御','乘算；两个 50 合计无视 75%')}${field('defReduceFlat','固定防御减少','威压等固定减防数值','',true)}${select('defDebuff','防御减益',[['0','无减益'],['20','防御下降 I · 20%'],['40','防御下降 II · 40%'],['60','防御下降 III · 60%']])}<label class="tool-check"><input id="hornBuff" name="hornBuff" type="checkbox" ${values.hornBuff===true?'checked':''}><span>决战号角<small>减防 20% · 易伤 × 1.8</small></span></label></div></section><section class="content-card"><div class="tool-section-heading"><span class="step-dot">03</span><h2>伤害区间</h2></div><div class="tool-fields">${field('dmgZone','增伤','加算，倍率最低 0.5；背击可填 30')}${field('vulnZone','易伤','乘算，含号角的总倍率最高 3')}${field('finalDmgZone','最终增伤','各效果独立乘算')}${field('finalVulnZone','最终易伤','各效果独立乘算')}</div></section></form><aside class="damage-aside"><section class="damage-result" aria-label="伤害结果"><div class="eyebrow">EXPECTED DAMAGE</div><h2>本次攻击</h2><div id="damage-error" role="alert" hidden></div><div id="damage-output" aria-live="polite"></div><button class="button" type="button" data-tool="export-damage">${h.icon('download',15)}导出结果图片</button></section><section class="content-card preset-card"><h3>我的计算方案</h3><label class="tool-field"><span>方案名称</span><input id="preset-name" maxlength="40" placeholder="例如：贝拉 · 高地爆发"></label><button class="button secondary small" type="button" data-tool="save-preset">保存当前方案</button><div id="preset-list"></div><div class="tool-backup-actions"><button class="button secondary small" type="button" data-tool="export-damage-plans">导出方案</button><button class="button secondary small" type="button" data-tool="import-tool">导入方案</button></div><button class="text-link" type="button" data-tool="reset-damage">恢复示例参数</button></section></aside></div><details class="content-card tool-help"><summary>公式与使用说明</summary><div class="rich-text"><p>伤害 = max(0, 实际攻击 × 职业克制 − 有效防御) × 技能倍率 × 增伤 × 易伤 × 最终增伤 × 最终易伤。暴击结果再乘暴击伤害倍率，最终四舍五入。</p><p>有效防御 = max(0, 防御面板 − 防御减益 − 号角减防 − 固定减防) × 各项 (1 − 无视防御)。防御减益和号角均按原始防御面板计算。</p><p>粉碎 → 防御 → 突袭 → 粉碎：优势 ×1.3，逆向 ×0.7。守望 → 毁灭：×1.4，逆向 ×0.6。其他组合 ×1。</p><p>高地 / 低地高低差 ≥2 时，可在攻击加成填写 15 / -10。受伤 / 濒死的攻击方可在增伤填写 -20 / -30；防御方可在易伤填写 20 / 30。面板已经计入的效果请勿重复填写。</p><p>按原站计算器规则还原，适用于其覆盖的直接伤害区间；特殊技能、固定伤害、取整阶段等以游戏实际结算为准。默认 3000 攻击、1200 防御、150% 技能为可修改的示例。原工具作者：颜笑丶、铃LLan。</p><p><a href="#/page/${h.find('伤害公式汇总')?.id||7523}">查看离线伤害公式资料 →</a></p></div></details>${source(7523,'伤害计算器')}`;
      const form=root.querySelector('#damage-form');
      function readForm(){for(const key of Object.keys(R.defaults)){const el=form.elements.namedItem(key);values[key]=el.type==='checkbox'?el.checked:el.value;}}
      function update(){
        readForm();form.querySelectorAll('[aria-invalid]').forEach(el=>el.removeAttribute('aria-invalid'));
        const error=root.querySelector('#damage-error'),output=root.querySelector('#damage-output');
        try{
          result=R.calculateDamage(values);error.hidden=true;h.persist('damage.current',values);
          output.innerHTML=`<div class="damage-number"><span>普通伤害</span><strong>${fmt(result.damage)}</strong></div><div class="damage-number critical"><span>暴击伤害 <small>× ${fmt(result.critical)}</small></span><strong>${fmt(result.criticalDamage)}</strong></div><dl class="calculation-steps">${[['实际攻击',result.attack],['职业克制','× '+fmt(result.restraint)],['有效防御',result.defense],['扣防后伤害',result.base],['技能倍率','× '+fmt(result.skill)],['增伤 / 易伤','× '+fmt(result.bonus)+' / × '+fmt(result.vulnerability)],['最终增伤 / 易伤','× '+fmt(result.finalBonus)+' / × '+fmt(result.finalVulnerability)]].map(([k,v])=>`<div><dt>${k}</dt><dd>${typeof v==='number'?fmt(v):v}</dd></div>`).join('')}</dl>`;
        }catch(e){result=null;error.textContent=e.message;error.hidden=false;output.innerHTML='<p class="result-empty">修正输入后即可继续计算。</p>';form.elements.namedItem(e.field)?.setAttribute('aria-invalid','true');}
        root.querySelector('[data-tool="export-damage"]').disabled=!result;
      }
      function showPresets(){root.querySelector('#preset-list').innerHTML=presets.length?presets.map((p,i)=>`<div class="preset-row"><button type="button" data-preset="${i}">${esc(p.name)}</button><button type="button" data-delete-preset="${i}" aria-label="删除方案 ${esc(p.name)}">×</button></div>`).join(''):'<p class="small-text muted">保存后可在此一键恢复。仅保存在当前浏览器。</p>';}
      function apply(v){for(const key of Object.keys(R.defaults)){const el=form.elements.namedItem(key);if(el.type==='checkbox')el.checked=v[key]===true;else el.value=v[key]??R.defaults[key];}update();}
      on('submit',e=>e.preventDefault());
      on('input',e=>{if(form.contains(e.target))update();});
      on('change',e=>{if(form.contains(e.target))update();});
      on('click',e=>{
        const target=e.target.closest('button');if(!target)return;
        if(target.dataset.preset!==undefined){const p=presets[Number(target.dataset.preset)];apply(p.values);root.querySelector('#preset-name').value=p.name;h.toast('已载入方案：'+p.name);}
        if(target.dataset.deletePreset!==undefined){const i=Number(target.dataset.deletePreset);presets.splice(i,1);h.persist('damage.presets',presets);showPresets();h.toast('已删除计算方案');}
        if(target.dataset.tool==='reset-damage')apply(R.defaults);
        if(target.dataset.tool==='import-tool')h.importFile();
        if(target.dataset.tool==='export-damage-plans'){
          if(!result){h.toast('请先修正输入');return;}
          download('铃兰档案馆-计算方案.json',JSON.stringify({format:'socwiki-damage',version:1,exportedAt:new Date().toISOString(),current:values,presets},null,2));
        }
        if(target.dataset.tool==='save-preset'){
          if(!result){h.toast('请先修正输入');return;}
          const name=root.querySelector('#preset-name').value.trim();
          if(!name){root.querySelector('#preset-name').focus();h.toast('先为方案起个名字');return;}
          const existing=presets.findIndex(p=>p.name===name);
          if(existing<0&&presets.length>=20){h.toast('最多保存 20 个方案，请先删除不再使用的方案');return;}
          const p={name,values:{...values}};if(existing<0)presets.push(p);else presets[existing]=p;
          if(h.persist('damage.presets',presets))h.toast(existing<0?'方案已保存':'同名方案已更新');showPresets();
        }
        if(target.dataset.tool==='export-damage'&&result){
          const canvas=document.createElement('canvas');canvas.width=960;canvas.height=1230;
          const c=canvas.getContext('2d');c.fillStyle='#f5f4ed';c.fillRect(0,0,960,1230);c.fillStyle='#244437';
          c.font='bold 38px sans-serif';c.fillText('铃兰档案馆 · 伤害计算',60,85);
          c.font='22px sans-serif';c.fillText('普通伤害  '+fmt(result.damage)+'      暴击伤害  '+fmt(result.criticalDamage),60,150);
          let y=220;c.font='20px sans-serif';
          for(const [key,label] of Object.entries(R.labels)) {const text=String(values[key]);c.fillText(label+'：'+(text.length>54?text.slice(0,51)+'…':text),60,y);y+=48;}
          c.fillText('克制倍率：'+result.restraint+'    决战号角：'+(values.hornBuff?'启用':'关闭'),60,y);y+=70;
          c.fillStyle='#6b7967';c.font='18px sans-serif';c.fillText('基于 BWIKI 计算规则 · '+new Date().toLocaleString('zh-CN'),60,y);
          c.fillText('直接伤害估算，特殊技能以游戏实际结算为准。',60,y+36);
          canvas.toBlob(blob=>{if(!blob)return;const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='铃兰档案馆-伤害计算.png';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);},'image/png');
        }
      });
      showPresets();update();
    }
    function equipment(){
      const data=D.equipment,rarities=['传说','史诗','卓越','普通'],weapons=[...new Set(data.rows.map(r=>r.weapon))];
      let weapon=weapons[0],rarity=rarities[0];
      function paint(){
        const row=data.rows.find(r=>r.weapon===weapon&&r.rarity===rarity);
        const matching=h.pages.filter(p=>p.type==='equipment'&&!p.redirect&&p.weapon===weapon&&p.rarity===rarity);
        root.innerHTML=`${back}${intro('EQUIPMENT REFERENCE','装备属性，一眼可查。','直接读取原站满级满星属性表。技能加成另行计算，未收录的组合明确标出。')}
          <section class="content-card equipment-reference"><div class="reference-filters"><div><h2>武器与装具</h2><div class="filter-chips" role="group" aria-label="选择装备类型">${weapons.map(w=>`<button class="chip ${w===weapon?'active':''}" data-ref-weapon="${esc(w)}" aria-pressed="${w===weapon}">${esc(w)}</button>`).join('')}</div></div><div><h2>稀有度</h2><div class="filter-chips" role="group" aria-label="选择装备稀有度">${rarities.map(r=>`<button class="chip ${r===rarity?'active':''}" data-ref-rarity="${r}" aria-pressed="${r===rarity}">${r}</button>`).join('')}</div></div></div>
          <div class="reference-heading"><span class="badge gold">${rarity}</span><h3>${weapon}</h3><span>满级满星基础属性</span></div>
          ${row.recorded?`<div class="reference-stats">${Object.entries(row.stats).map(([k,v])=>`<div><span>${k}</span><strong>${fmt(v)}</strong></div>`).join('')}</div>`:'<div class="reference-unrecorded">原站此组合的五项属性均填为 0，暂不作为有效数值展示。可继续查阅装备技能与完整原表。</div>'}
          <p class="small-text muted">按装备种类和稀有度记录，不含装备技能、角色个性及战斗增益；此表不提供任意等级或星级的推算。</p></section>
          <section class="content-card"><div class="section-heading"><h2>同类装备</h2><span class="muted small-text">${matching.length} 件档案</span></div>${matching.length?`<div class="reference-equipment-list">${matching.map(p=>`<a href="#/page/${p.id}"><img src="${p.image||'assets/brand/placeholder.svg'}" alt="" loading="lazy"><span>${esc(p.name)}</span>${h.icon('chevron',14)}</a>`).join('')}</div>`:'<p class="muted small-text">当前资料库没有该组合的装备页面。</p>'}</section>
          <details class="content-card"><summary>全部组合与原站收录情况</summary><div class="table-scroll"><table class="data-table reference-table"><thead><tr><th>类型</th><th>稀有度</th>${['物攻','魔攻','物防','魔防','生命'].map(k=>`<th>${k}</th>`).join('')}<th>收录情况</th></tr></thead><tbody>${data.rows.map(r=>`<tr><td>${r.weapon}</td><td>${r.rarity}</td>${Object.values(r.stats).map(n=>`<td>${r.recorded?fmt(n):'—'}</td>`).join('')}<td>${r.recorded?'已记录':'原表全为 0'}</td></tr>`).join('')}</tbody></table></div></details>
          <div class="source-footer"><span>原站更新 ${esc(data.date)} · 版本 ${data.revision}</span><a href="#/page/2710">查看离线装备原表 →</a></div>`;
      }
      on('click',e=>{const b=e.target.closest('button');if(!b)return;let selector;
        if(b.dataset.refWeapon){weapon=b.dataset.refWeapon;selector='[data-ref-weapon="'+weapon+'"]';}
        if(b.dataset.refRarity){rarity=b.dataset.refRarity;selector='[data-ref-rarity="'+rarity+'"]';}
        if(selector){paint();root.querySelector(selector)?.focus({preventScroll:true});}
      });paint();
    }
    function gacha(){
      let state=R.restoreSimulation(h.read('gacha.state',null),D);
      let poolId=h.read('gacha.pool','chuyu');if(!D.pools.some(p=>p.id===poolId))poolId='chuyu';
      let last=[];
      const charMap=new Map(Object.values(D.characters).flat().map(c=>[c.name,c]));
      function paint(){
        const pool=D.pools.find(p=>p.id===poolId);
        const resultCard=item=>{const c=charMap.get(item.name);return `<a class="summon-card rarity-${item.rarity}" href="${c?.id?'#/page/'+c.id:'#/search?q='+encodeURIComponent(item.name)}"><div class="summon-rarity">${rarityNames[item.rarity]}${item.isUp?' · UP':''}</div><img src="${c?.image||'assets/brand/placeholder.svg'}" alt="" loading="lazy"><strong>${esc(item.name)}</strong><small>${item.guarantee==='up'?'UP 保底':item.guarantee==='legend'?'传说保底':'第 '+fmt(item.number)+' 次'}</small></a>`;};
        root.innerHTML=`${back}${intro('A MOMENT OF ENCOUNTER','下一位，会是谁。','离线模拟邂逅，保留你的每一次期待。卡池来自原站快照，不代表当前游戏卡池。')}<div class="pool-tabs" role="group" aria-label="选择模拟卡池">${D.pools.map(p=>`<button type="button" class="${p.id===poolId?'active':''}" data-pool="${p.id}" aria-pressed="${p.id===poolId}"><span>${p.label}</span><strong>${esc(p.name)}</strong><small>${p.up.map(esc).join(' / ')}</small></button>`).join('')}</div><div class="gacha-layout"><div><section class="pool-banner"><div class="pool-artwork">${pool.up.map(name=>`<img src="${h.find('角色图鉴库/'+name)?.image||pool.image}" alt="${esc(name)}立绘">`).join('')}</div><div class="pool-caption"><span class="eyebrow">${pool.label} · 资料快照</span><h2>${esc(pool.name)}</h2><p>UP ${pool.up.map(esc).join(' · ')}</p></div></section><div class="summon-controls"><button class="button secondary" data-draw="1">邂逅一次</button><button class="button" data-draw="10">邂逅十次 ${h.icon('spark',17)}</button><button class="button secondary" data-draw="100">模拟 100 次</button></div><section class="content-card summon-results" aria-live="polite"><div class="section-heading"><h2>${last.length?'本次邂逅':'等待一场相遇'}</h2><span class="muted small-text">${last.length>20?'展示本批最后 20 次':last.length?'点击角色查看档案':'支持单次、十连与批量模拟'}</span></div>${last.length?`<div class="summon-grid">${last.slice(-20).map(resultCard).join('')}</div>`:'<div class="summon-empty">'+h.icon('spark',42)+'<p>选择卡池，开始你的离线邂逅。</p><span>全部角色与图片均来自本地资料库</span></div>'}</section></div><aside class="gacha-aside"><section class="content-card pity-card"><div class="eyebrow">YOUR JOURNEY</div><h2>邂逅进度</h2><div class="pity-label"><span>共享传说保底</span><b>${state.pity} / 100</b></div><progress value="${state.pity}" max="100" aria-label="共享传说保底"></progress><small>最多再 ${100-state.pity} 次获得传说</small><div class="pity-label"><span>${pool.label} UP 保底</span><b>${state.special[poolId]} / 180</b></div><progress value="${state.special[poolId]}" max="180" aria-label="当前卡池 UP 保底"></progress><small>最多再 ${180-state.special[poolId]} 次获得 UP</small><p>获得任意传说重置共享计数；获得当前池 UP 重置该池计数。</p></section><section class="content-card simulation-stats"><h3>我的模拟记录</h3><div class="simulation-total"><strong>${fmt(state.total)}</strong><span>累计邂逅</span></div>${Object.entries(rarityNames).map(([k,label])=>`<div class="archive-row"><span><i class="rarity-dot rarity-${k}"></i>${label}</span><strong>${fmt(state.counts[k])}<small>${state.total?' · '+(state.counts[k]/state.total*100).toFixed(1)+'%':''}</small></strong></div>`).join('')}<div class="simulation-actions"><button class="button secondary small" data-tool="export-gacha" ${state.total?'':'disabled'}>导出模拟记录</button><button class="button secondary small" data-tool="import-tool">导入记录</button><button class="text-link" data-tool="reset-gacha">清空模拟记录</button></div><small class="muted">自动保存在当前浏览器。刷新或切换卡池不丢失进度。</small></section></aside></div>${state.counts.legend?`<details class="content-card"><summary>已获得的传说 · ${Object.keys(state.legendStats).length} 位</summary><div class="legend-collection">${Object.entries(state.legendStats).sort((a,b)=>b[1]-a[1]).map(([name,count])=>{const c=charMap.get(name);return `<a href="${c?.id?'#/page/'+c.id:'#/search?q='+encodeURIComponent(name)}"><img src="${c?.image||'assets/brand/placeholder.svg'}" alt="" loading="lazy"><span>${esc(name)}</span><b>× ${count}</b></a>`;}).join('')}</div></details>`:''}<details class="content-card"><summary>最近 200 次记录${state.history.length?' · 已保存 '+state.history.length+' 条':''}</summary>${state.history.length?`<div class="table-scroll"><table class="data-table summon-history"><thead><tr><th>次数</th><th>角色</th><th>稀有度</th><th>卡池</th><th>标记</th></tr></thead><tbody>${state.history.map(item=>`<tr><td>${fmt(item.number)}</td><td>${esc(item.name)}</td><td>${rarityNames[item.rarity]}</td><td>${D.pools.find(p=>p.id===item.pool).label}</td><td>${item.guarantee==='up'?'UP 保底':item.guarantee==='legend'?(item.isUp?'UP · 传说保底':'传说保底'):item.isUp?'UP':'—'}</td></tr>`).join('')}</tbody></table></div>`:'<p class="muted">尚未开始模拟。</p>'}</details><details class="content-card tool-help"><summary>概率、卡池名单与模拟规则</summary><div class="rich-text"><p>普通随机抽取的基础概率：传说 2%、史诗 20%、精英 40%、普通 38%。保底会改变长期统计比例。</p><p>初遇获得传说时有 50% 为 UP；重逢获得传说时有 75% 为两位 UP（各 37.5%）。两个卡池共享 100 次传说保底，各自保留 180 次 UP 保底；重逢触发 UP 保底时优先尚未在本次模拟中获得的 UP。UP 保底优先结算，任何传说都重置共享计数。</p><p>遵循原站模拟器的名单与筛选方式：非 UP 传说候选中排除这两个池展示的全部 UP。名单含 ${D.characters.legend.length} 位传说；仅部分角色属于当前候选池。此工具复现 Wiki 模拟规则，不接入游戏账号。</p><p>快照页面更新日期：${esc(D.sourceDate)}，版本 ${D.revision}。原站工具署名：铃LLan。导出文件包含累计统计、传说获取次数和最近 200 次记录。</p>${Object.entries(rarityNames).map(([k,label])=>`<details><summary>${label}角色 · ${D.characters[k].length} 位</summary><p>${D.characters[k].map(c=>esc(c.name)).join('、')}</p></details>`).join('')}</div></details>${source(8027,'邂逅模拟器')}`;
      }
      on('click',e=>{
        const b=e.target.closest('button');if(!b)return;
        if(b.dataset.pool){poolId=b.dataset.pool;last=[];h.persist('gacha.pool',poolId);paint();}
        if(b.dataset.draw){const result=R.draw(state,poolId,Number(b.dataset.draw),D);state=result.state;last=result.results;h.persist('gacha.state',state);paint();const button=root.querySelector(`[data-draw="${b.dataset.draw}"]`);button?.focus({preventScroll:true});h.toast('完成 '+result.results.length+' 次邂逅，本次传说 '+last.filter(i=>i.rarity==='legend').length+' 位');}
        if(b.dataset.tool==='reset-gacha'&&confirm('清空两个卡池的模拟记录和保底进度？')){state=R.newSimulation(D);last=[];h.persist('gacha.state',state);paint();h.toast('模拟记录已清空');}
        if(b.dataset.tool==='import-tool')h.importFile();
        if(b.dataset.tool==='export-gacha')download('铃兰档案馆-邂逅模拟.json',JSON.stringify({format:'socwiki-gacha',exportedAt:new Date().toISOString(),sourceRevision:D.revision,poolId,...state},null,2));
      });
      paint();
    }
  }
  window.WikiTools={render,unmount:()=>cleanup()};
})();
