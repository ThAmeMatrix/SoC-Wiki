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
    else if(type==='panel')panel();
    else if(type==='gacha')gacha();
    else if(type==='equipment')equipment();
    else root.innerHTML=`${intro('THE TRAVELER’S WORKBENCH','让每一步，都心中有数。','制作角色一图流，计算战斗伤害与局外面板，模拟卡池结果。所有操作均在本机完成。')}<div class="tool-grid">${[
      ['infographic','feather','一图流工坊','以觉醒立绘为底，标注技能加点、编辑三套搭配，搭配专武、塔罗与刻印，制作自己的角色攻略。','技能树 · 六维能力 · 高清图片导出'],
      ['damage','compare','伤害计算器','逐项设置攻击、防御与伤害区间，实时查看普通伤害、暴击伤害和计算过程。','实时计算 · 方案保存 · 结果导出'],
      ['panel','grid','局外面板计算器','选择角色星级等级、技能轴与好感度，配置武器装具、刻印与塔罗，算出局外五维面板。','客户端数值 · 公式分解 · 完全离线'],
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
    function panel(){
      const P=window.WIKI_PANEL_DATA, C=window.WikiPanelCalc;
      if(!P||!C){root.innerHTML=`${back}${intro('PANEL LAB','面板，算得明明白白。','')}<div class="empty-state"><h1>面板数据未能载入</h1><p>请完整解压离线包，保留 data/panel-data.js 与 panel-calc.js。</p></div>`;return;}
      const labels=P.statLabels, five=P.stats.length, zero=()=>new Array(five).fill(0);
      const options=(from,to,suffix='')=>Array.from({length:to-from+1},(_,i)=>[from+i,String(from+i)+suffix]);
      const normName=s=>String(s||'').replace(/[·•‧・]/g,'-').trim();
      const starOptions=options(1,5,' 星'), levelOptions=options(1,P.maxLevel,' 级');
      const rankOptions=options(0,P.maxRank,' 阶'), friendOptions=options(0,5,' 级');
      const rarityOptions=Object.entries(P.charmRarities).map(([id,r])=>[id,r[0]]);

      // Shared character picker: only characters the client actually has numbers
      // for, plus synthetic entries for client-only units without a wiki page.
      const wikiPages=(h.pages||[]).filter(p=>p.type==='character'&&!p.redirect);
      const pickerPages=P.characters.map(c=>{
        const page=wikiPages.find(p=>normName(p.name)===c.key);
        return page?{...page,panelKey:c.key}:
          {id:'client:'+c.key,name:c.name,title:c.name,aliases:'',summary:'',rarity:'',
           class:'',faction:'',image:'',panelKey:c.key};
      });
      const pageId=key=>pickerPages.find(p=>p.panelKey===key)?.id;

      function defaultPicks(char){
        const ranks=P.lineRanks?.[char?.line]||[],out={};
        for(const r of ranks)out[r]='left';
        return out;
      }
      function normalize(raw){
        const d=C.defaults(P), src=raw&&typeof raw==='object'&&!Array.isArray(raw)?raw:{};
        const c={...d,...src};
        for(const slot of ['weapon','offhand']){
          const s=src[slot]||{}, en=s.enchant||{};
          c[slot]={...d[slot],...s,enchant:{...d[slot].enchant,...en,
            values:zero().map((_,i)=>C.int(Array.isArray(en.values)?en.values[i]:0)),
            percents:zero().map((_,i)=>C.int(Array.isArray(en.percents)?en.percents[i]:0))}};
        }
        const cs=src.charm||{};
        c.charm={...d.charm,...cs,entries:Array.isArray(cs.entries)?cs.entries.slice(0,8):[]};
        const char=C.findCharacter(P,c.character)||P.characters[0];
        const supplied=src.linePicks&&typeof src.linePicks==='object'?src.linePicks:{};
        c.linePicks=defaultPicks(char);
        for(const r of Object.keys(c.linePicks)){
          const v=Array.isArray(supplied)?supplied[r]:supplied[r]??supplied[String(r)];
          if(['none','left','right','both'].includes(v))c.linePicks[r]=v;
        }
        c.talent={star:0,pioneer:0,...(src.talent||{})};
        // Older saved presets predate the talent-node UI (or were saved while
        // empty). Default both trees to fully lit unless the player has
        // explicitly changed them in this build.
        // A preset written by an older build has no explicit marker; re-seed
        // it to the all-lit default rather than inheriting a partial/empty set.
        c.talentNodesExplicit=!!src.talentNodesExplicit;
        c.talentNodes=c.talentNodesExplicit
          ?{star:{...(src.talentNodes?.star||{})},pioneer:{...(src.talentNodes?.pioneer||{})}}
          :C.defaultTalentNodes(P,char);
        c.talentView={star:0,pioneer:0,...(src.talentView||{})};
        c.talentAdjust=zero().map((_,i)=>C.int(Array.isArray(src.talentAdjust)?src.talentAdjust[i]:0));
        c.talentAdjustFlat=zero().map((_,i)=>C.int(Array.isArray(src.talentAdjustFlat)?src.talentAdjustFlat[i]:0));
        c.combat={...C.damageDefaults(window.WIKI_COMBAT_DATA),...(src.combat||{})};
        return c;
      }
      const NO_ITEM=[[0,'不带（无加成）','不带 无 空']];
      let cfg=normalize(h.read('panel.current',null));
      // Battle-power formula is not recoverable from the client config; keep
      // the player's chosen candidate / calibration across result repaints.
      const battlePowerState={method:'permille-final',scale:1,calibration:0};
      // A restored preset may name a weapon the current character cannot equip.
      function fixEquipment(){
        const wo=weaponOptions(C.findCharacter(P,cfg.character)),oo=offhandOptions(),co=charmOptions();
        const valid=(id,opts)=>!id||['0','none',''].includes(String(id))||opts.some(o=>String(o[0])===String(id));
        if(!valid(cfg.weapon.id,wo))cfg.weapon.id=wo[0]?.[0]??0;
        if(!valid(cfg.offhand.id,oo))cfg.offhand.id=oo[0]?.[0]??0;
        if(!valid(cfg.charm.id,co))cfg.charm.id=co[0]?.[0]??0;
      }
      fixEquipment();
      let presets=h.read('panel.presets',[]);
      if(!Array.isArray(presets))presets=[];
      presets=presets.filter(p=>p&&typeof p.name==='string'&&p.config).slice(0,20);

      const sel=(path,label,opts,value)=>`<label class="tool-field"><span>${label}</span><select data-path="${path}">${opts.map(([v,t])=>`<option value="${esc(v)}" ${String(value)===String(v)?'selected':''}>${esc(t)}</option>`).join('')}</select></label>`;
      const num=(path,label,value,min,max,hint='')=>`<label class="tool-field"><span>${label}</span><input data-path="${path}" type="number" min="${min}" max="${max}" step="1" value="${esc(value)}"><small>${hint}</small></label>`;
      const heading=(n,title,note)=>`<div class="tool-section-heading"><span class="step-dot">${n}</span><h2>${title}</h2><span>${note}</span></div>`;
      const combat=window.WIKI_COMBAT_DATA||{};
      const catOptions=(combat.categories||[{id:1,name:'防御者'}]).map(c=>[c.id,c.name]);
      const dmg=(path,label,value,min,max,hint='')=>num('combat.'+path,label,value,min,max,hint);

      function weaponOptions(char){
        const allowed=new Set((char?.weaponTypes||[]).filter(t=>Number(t)!==2));
        return [...NO_ITEM,...P.weapons.filter(w=>allowed.has(Number(w.typeId)))
          .map(w=>[w.id,`${w.name} · ${w.type}`,w.name+' '+w.type])];
      }
      function offhandOptions(){
        return [...NO_ITEM,...P.weapons.filter(w=>Number(w.typeId)===2)
          .map(w=>[w.id,`${w.name} · ${w.type}`,w.name+' '+w.type])];
      }
      function charmOptions(){return [...NO_ITEM,...P.charms.map(c=>[c.id,c.name,c.name])];}
      function comboOptions(path){
        if(path==='weapon.id')return weaponOptions(C.findCharacter(P,cfg.character));
        if(path==='offhand.id')return offhandOptions();
        if(path==='charm.id')return charmOptions();
        return [];
      }
      const combo=(path,label,opts,value,hint='')=>{
        const empty=!value||['0','none'].includes(String(value));
        const hit=opts.find(o=>String(o[0])===String(value))||(empty?NO_ITEM[0]:null);
        return `<div class="tool-field panel-combo-field"><span>${label}</span>
          <input type="text" class="panel-combo-input" data-combo="${path}" role="combobox"
                 aria-autocomplete="list" aria-expanded="false" placeholder="输入名称搜索…" autocomplete="off"
                 value="${esc(hit?hit[1]:'')}">
          <input type="hidden" data-path="${path}" value="${esc(value)}">
          <div class="panel-combo-list" role="listbox" hidden></div>
          ${hint?`<small>${hint}</small>`:''}</div>`;
      };
      function showCombo(input,query){
        const field=input.closest('.panel-combo-field'), list=field?.querySelector('.panel-combo-list');
        if(!list)return;
        const q=String(query||'').trim().toLowerCase();
        const opts=comboOptions(input.dataset.combo);
        const hits=opts.filter(o=>!q||String(o[1]+' '+(o[2]||'')).toLowerCase().includes(q)).slice(0,60);
        const chosen=field.querySelector('[data-path]').value;
        list.innerHTML=hits.length?hits.map(o=>`<button type="button" role="option" data-combo-value="${esc(o[0])}" data-combo-label="${esc(o[1])}" aria-selected="${String(o[0])===String(chosen)}">${esc(o[1])}</button>`).join(''):'<p class="small-text muted">没有匹配项</p>';
        list.hidden=false;input.setAttribute('aria-expanded','true');
      }
      function closeCombos(){
        for(const list of root.querySelectorAll('.panel-combo-list'))list.hidden=true;
        for(const input of root.querySelectorAll('[data-combo]'))input.setAttribute('aria-expanded','false');
      }

      function characterButton(){
        const char=C.findCharacter(P,cfg.character)||P.characters[0];
        const type=(char?.weaponTypes||[]).find(t=>Number(t)!==2);
        return `<button type="button" class="panel-character" data-tool="pick-character" aria-label="选择角色">
          <span><small>当前角色 · 点击更换</small><strong>${esc(char?.name||'选择角色')}</strong>
          <em>${char?.wiki?'资料馆角色':'客户端角色'}${type?` · ${esc(P.weaponTypeNames?.[String(type)]||'')}武器`:''}</em></span>
          ${h.icon('chevron',19)}</button>`;
      }
      function equipmentBaseInner(slot){
        const info=C.equipmentBase(P,slot,cfg[slot]);
        if(!info)return '<p class="small-text muted">未装备 · 基础值 0</p>';
        return `<div class="panel-equip-base"><span>基础数值 <small>${esc(info.label)}</small></span>
          <div>${labels.map((lb,i)=>`<span><em>${esc(lb)}</em><strong>${fmt(info.values[i])}</strong></span>`).join('')}</div></div>`;
      }
      function equipmentBaseLine(slot){
        return `<div id="panel-equip-base-${slot}">${equipmentBaseInner(slot)}</div>`;
      }
      function refreshEquipmentBases(){
        for(const slot of ['weapon','offhand','charm']){
          const box=root.querySelector(`#panel-equip-base-${slot}`);
          if(box)box.innerHTML=equipmentBaseInner(slot);
        }
      }
      function lineOn(rank,side){
        const v=cfg.linePicks?.[rank]||'left';
        return v==='both'||v===side;
      }
      function linePicksBlock(){
        const char=C.findCharacter(P,cfg.character)||P.characters[0];
        const ranks=P.lineRanks?.[char?.line]||[];
        if(!ranks.length)return '<p class="small-text muted">该技能轴没有属性加成节点。</p>';
        // Same tier / node / mark visuals as the infographic skill tree, with
        // the archived skill icons instead of a generic glyph. Nodes still
        // have only two states: lit or not (no 必点/选点 cycle).
        const skills=P.lineSkills?.[char?.key]||{};
        const covered=Object.values(skills).reduce((n,sides)=>n+sides.filter(s=>s&&s.image).length,0);
        const tree=[...ranks].sort((a,b)=>b-a).map(r=>{
          const nodes=['left','right'].map((side,j)=>{
            const on=lineOn(r,side);
            const info=skills[String(r)]?.[j];
            const axis=side==='left'?(char.tier1||'左'):(char.tier2||'右');
            const label=info?.name||axis;
            const icon=info?.image
              ? `<img class="panel-node-icon panel-node-img" src="${esc(info.image)}" alt="" width="54" height="54">`
              : `<span class="panel-node-icon">${h.icon(on?'check':'spark',26)}</span>`;
            return `<div class="ig-tree-node panel-tree-node${on?'':' unavailable'}" data-mark="${on?'on':''}">
              <button type="button" class="ig-node-select panel-node-select" data-line-node="${r}" data-line-side="${side}"
                      aria-pressed="${on}" aria-label="${r} 阶 ${esc(label)}：${on?'已点':'未点'}，点击切换"
                      title="${esc(info?.full||label)} · ${esc(axis)}轴">
                ${icon}
                <strong>${esc(label)}</strong><small>${on?'● 已点':'○ 未点'}</small></button></div>`;
          }).join('');
          return `<div class="ig-tier panel-tree-tier"><span class="ig-rank">${r} 阶</span>${nodes}</div>`;
        }).join('');
        return `<div class="ig-mark-legend panel-tree-legend"><span>○ 未点</span><i>→</i><span class="required">● 已点</span><i>→</i><span>○ 未点</span></div>
          <p class="ig-hint">与一图流技能树相同的节点与图标（取自角色档案的逐阶技能页），但每个节点只有「点 / 不点」两态；左右可同时点亮，属性加成按客户端百分比表逐阶累加。当前角色收录 ${covered} 张技能图。</p>
          <div class="panel-skill-tree">${tree}</div>`;
      }
      function talentViewOptions(tree,key){
        const list=key==='star'?(tree.grades||[]).map(g=>[g.id,`${g.name} · 累计 ${fmt(g.exp)} 经验`]):
          (tree.groups||[]).map(g=>[g.id,`第 ${g.name} 图`]);
        return list.length?list:[[0,'全部节点']];
      }
      function talentLevelRows(key,node){
        return node.levels.map((lv,i)=>{
          const parts=[];
          for(let j=0;j<labels.length;j++){
            if(lv.flat[j])parts.push(`${labels[j]}+${lv.flat[j]}`);
            if(lv.perm[j])parts.push(`${labels[j]}+${pctText(lv.perm[j])}`);
          }
          return `<tr><td>Lv.${i+1}</td><td>${esc(parts.join(' · ')||'—')}</td>
            <td>${lv.exp?fmt(lv.exp)+' 经验':'—'}</td>
            <td>${esc(C.talentCostLabel(P,key,lv.cost))}</td>
            <td>${lv.reqLevel?lv.reqLevel+' 级':'—'}</td></tr>`;
        }).join('');
      }
      function talentTopology(key,nodes,picks){
        // Mirrors the in-game tech panel: 星辰 uses (lane, col) / grade rows,
        // 开拓 uses the literal (x, y) grid. One SVG holds both nodes and the
        // prerequisite arrows so the dependency chain is visible at a glance.
        // Client y grows upwards (y=1 physical branch at the bottom, y=3
        // magical branch on top), so the pioneer y axis is flipped for display.
        const pos=new Map();
        for(const n of nodes){
          const x=key==='star'?n.col:n.x;
          const y=key==='star'?n.lane:(4-(n.y||2));
          pos.set(String(n.id),{x:Math.max(0,x||0),y:Math.max(0,y),n});
        }
        const xs=[...pos.values()].map(p=>p.x), ys=[...pos.values()].map(p=>p.y);
        const minX=Math.min(0,...xs),maxX=Math.max(1,...xs),minY=Math.min(0,...ys),maxY=Math.max(1,...ys);
        const CW=132,CH=104,PAD=58;
        const W=(maxX-minX+1)*CW+PAD*2,H=(maxY-minY+1)*CH+PAD*2+42;
        const cx=v=>PAD+(v-minX)*CW+CW/2, cy=v=>PAD+(v-minY)*CH+CH/2;
        const lines=[];
        for(const n of nodes){
          const to=pos.get(String(n.id));if(!to)continue;
          for(const prev of n.prev||[]){
            const from=pos.get(String(prev));
            if(from){
              lines.push(`<path class="panel-topo-link${C.int(picks[prev],0)>0&&C.int(picks[n.id],0)>0?' is-active':''}"
                d="M${cx(from.x)},${cy(from.y)} C${cx(from.x)},${(cy(from.y)+cy(to.y))/2} ${cx(to.x)},${(cy(from.y)+cy(to.y))/2} ${cx(to.x)},${cy(to.y)}"/>`);
            }else{
              // Prerequisite lives in another grade / 图: stub arrow from the edge.
              lines.push(`<path class="panel-topo-link is-external" d="M${PAD/2},${cy(to.y)} L${cx(to.x)-CW/3},${cy(to.y)}"/>`);
              lines.push(`<text class="panel-topo-edge" x="${PAD/2}" y="${cy(to.y)-8}">前置 ${esc(prev)}</text>`);
            }
          }
        }
        // Lane legend: the flipped y makes the physical branch sit at the
        // bottom; label the three rows so the layout is unambiguous.
        const laneNames=key==='star'?[]
          :[[1,'魔法道'],[2,'中间'],[3,'物理道']].map(([row,label])=>
              `<text class="panel-topo-lane" x="${W-8}" y="${cy(row)+4}" text-anchor="end">${label}</text>`).join('');
        const circles=nodes.map(n=>{
          const p=pos.get(String(n.id));if(!p)return '';
          const lit=C.int(picks[n.id],0)>0, full=C.int(picks[n.id],0)>=n.levels.length;
          const missing=(n.prev||[]).some(prev=>!C.int(picks[prev],0));
          return `<g class="panel-topo-node${lit?' is-lit':''}${full?' is-full':''}${n.attr?'':' is-utility'}${missing?' is-blocked':''}"
              data-topo-node="${n.id}" data-topo-tree="${key}" transform="translate(${cx(p.x)},${cy(p.y)})" role="button" tabindex="0"
              aria-label="${esc(n.name)}，${lit?'已点亮 Lv.'+C.int(picks[n.id],0):'未点亮'}">
            <circle class="panel-topo-ring" r="27"></circle>
            <circle class="panel-topo-core" r="21"></circle>
            <text class="panel-topo-level" text-anchor="middle" dy="4">${lit?'Lv.'+C.int(picks[n.id],0):'○'}</text>
            <text class="panel-topo-name" text-anchor="middle" y="46">${esc(n.name.slice(0,7))}</text>
            <title>${esc(n.name)} · ${esc(n.kind||'')}${n.prev?.length?' · 前置 '+n.prev.join('、'):''}</title></g>`;
        }).join('');
        return `<div class="panel-topo-scroll"><svg class="panel-topo" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}"
            role="group" aria-label="${key==='star'?'星辰':'开拓'}天赋拓扑图">${lines.join('')}${laneNames}${circles}</svg></div>`;
      }
      function talentNodeMarkup(key,node,picks){
        const level=C.clamp(C.int(picks?.[node.id],0),0,node.levels.length);
        const lit=level>0;
        const missing=(node.prev||[]).filter(prev=>!C.int(picks?.[prev],0));
        const bonus=node.levels[Math.max(0,level-1)]||{flat:[0,0,0,0,0],perm:[0,0,0,0,0]};
        const parts=[];
        for(let i=0;i<labels.length;i++){
          if(bonus.flat[i])parts.push(`${labels[i]}+${bonus.flat[i]}`);
          if(bonus.perm[i])parts.push(`${labels[i]}+${pctText(bonus.perm[i])}`);
        }
        const prereq=missing.length?`<span class="panel-node-warn" title="前置节点未点亮">需先点亮 ${missing.length} 个前置</span>`:'';
        const picker=node.levels.length>1
          ? `<select class="panel-node-level" data-talent-level="${node.id}" data-talent-tree="${key}" aria-label="${esc(node.name)}等级">
               ${node.levels.map((_,i)=>`<option value="${i}" ${i===level?'selected':''}>${i===0?'未点':'Lv.'+i}</option>`).join('')}</select>`:'';
        const cost=C.talentCostLabel(P,key,node.levels[Math.max(0,level-1)]?.cost);
        return `<div class="panel-talent-node${lit?' is-lit':''}${node.attr?'':' is-utility'}" data-talent-card="${node.id}">
          <button type="button" class="panel-talent-toggle" data-talent-node="${node.id}" data-talent-tree="${key}"
                  aria-pressed="${lit}" title="${esc(node.kind||'')}${node.prev?.length?' · 前置 '+node.prev.join('、'):''}">
            <span class="panel-talent-dot">${lit?'●':'○'}</span><strong>${esc(node.name)}</strong>
            <small>${node.attr?esc(parts.join(' · ')||'属性节点'):esc(node.kind||'技能节点')}${lit?' · 累计':''}</small></button>
          ${picker}
          <p class="panel-node-cost"><span>本级消耗</span>${esc(cost)}</p>
          ${node.levels.length?`<details class="panel-node-levels"><summary>逐级累计加成与材料（${node.levels.length} 级）</summary>
            <div class="table-scroll"><table class="data-table panel-node-level-table"><thead><tr>
              <th>等级</th><th>升到该级的累计加成</th><th>本级经验</th><th>本级点亮材料</th><th>角色等级</th></tr></thead>
              <tbody>${talentLevelRows(key,node)}</tbody></table></div>
            <p class="small-text muted">「累计加成」是该节点升到此等级后的总效果，不是逐级叠加的增量；合计只取当前等级那一行。经验与材料为每一级分别消耗，点满需累加各级。</p></details>`:''}
          ${prereq}</div>`;
      }
      function talentBonusCells(vec,percent){
        const cells=labels.map((lb,i)=>{
          const flat=vec.flat[i],perm=percent?vec.perm[i]:vec.permillage[i];
          if(!flat&&!perm)return '';
          return `<span><small>${esc(lb)}</small><strong>+${fmt(flat)}${perm?' / +'+(perm/10).toFixed(1)+'%':''}</strong></span>`;
        }).join('');
        return cells||'<span class="muted">未点亮</span>';
      }
      function talentBonusSummary(progress,breakdown){
        const perTree=['star','pioneer'].map(key=>{
          const b=breakdown[key]||{flat:[0,0,0,0,0],perm:[0,0,0,0,0],lit:0};
          return `<div class="panel-talent-bonus-row"><h4>${key==='star'?'星辰天赋':'开拓天赋'} <small>${b.lit} 个节点${b.globalLit?' · 含 '+b.globalLit+' 个全职业节点':''}</small></h4>
            <div class="panel-talent-bonus-grid">${talentBonusCells(b,true)}</div></div>`;
        }).join('');
        return `${perTree}<div class="panel-talent-bonus-row is-total"><h4>天赋总加成</h4>
          <div class="panel-talent-bonus-grid">${talentBonusCells(breakdown.total,true)}</div></div>`;
      }
      function talentNodeGroups(key,nodes,picks){
        if(!nodes.length)return '<p class="small-text muted">该分组暂无节点。</p>';
        // The client stores each 图 on three lanes. Show them in game order
        // (魔法道 → 中间 → 物理道, physical last / at the bottom) and inside a
        // lane sort by x so the prerequisite chain reads left to right.
        const lanes=key==='star'?null:new Map([[3,'物理道'],[2,'中间'],[1,'魔法道']]);
        const groups=new Map();
        for(const n of nodes){
          const lane=lanes?(4-(n.y||2)):0;
          if(!groups.has(lane))groups.set(lane,[]);
          groups.get(lane).push(n);
        }
        const ordered=[...groups.entries()].sort((a,b)=>a[0]-b[0]);
        return `<div class="panel-talent-lanes">${ordered.map(([lane,list])=>{
          list.sort((a,b)=>(a.x||0)-(b.x||0)||(a.id-b.id));
          return `<section class="panel-talent-lane" data-lane="${lane}">
            ${lanes?`<h4>${lanes.get(lane)||'中间'}</h4>`:''}
            <div class="panel-talent-nodes">${list.map(n=>talentNodeMarkup(key,n,picks)).join('')}</div></section>`;
        }).join('')}</div>`;
      }
      function talentsBlock(){
        const char=C.findCharacter(P,cfg.character)||P.characters[0];
        const progress=C.talentProgress(P,char,cfg);
        const starGrade=C.talentGrade(P,char,'star',progress.exp);
        const blocks=['star','pioneer'].map(key=>{
          const meta=P.talents?.[key];
          const tree=C.talentTree(P,key,char);
          if(!meta||!tree)return '';
          const options=talentViewOptions(tree,key);
          const current=cfg.talentView?.[key]??options[0][0];
          const active=options.some(o=>String(o[0])===String(current))?current:options[0][0];
          const picks=cfg.talentNodes?.[key]||{};
          const nodes=tree.nodes.filter(n=>key==='star'?n.grade===Number(active):n.unlockGroup===Number(active));
          const lit=nodes.filter(n=>C.int(picks[n.id],0)>0).length;
          const allLit=nodes.every(n=>C.int(picks[n.id],0)>=n.levels.length);
          return `<section class="panel-talent-tree"><div class="panel-talent-head">
              <h3>${esc(meta.name)} <small>${esc(tree.name)}</small></h3>
              <label class="tool-field"><span>${key==='star'?'品阶':'开拓图'}</span>
                <select data-path="talentView.${key}">${options.map(([v,l])=>`<option value="${v}" ${String(v)===String(active)?'selected':''}>${esc(l)}</option>`).join('')}</select></label>
              <span class="small-text muted">已点亮 ${lit} / ${nodes.length} 个节点</span>
              <div class="panel-talent-actions">
                <button type="button" class="button secondary small" data-talent-fill="${key}" data-talent-group="${active}"
                  ${allLit?'disabled':''}>${allLit?'本组已全点':'一键全点本组'}</button>
                <button type="button" class="button secondary small" data-talent-fill-all="${key}">全树全点</button>
                <button type="button" class="button secondary small" data-talent-clear-group="${key}" data-talent-group="${active}">清空本${key==='star'?'品阶':'图'}</button>
                <button type="button" class="button secondary small" data-talent-clear="${key}">清空全树</button></div></div>
            ${talentTopology(key,nodes,picks)}
            <p class="small-text muted">拓扑图按客户端 ${key==='star'?'品阶 + 战术 / 进攻 / 生存 分道与列坐标':'x / y 网格坐标'}绘制，曲线为 <code>prev_id</code> / <code>afk_prev_ids</code> 前置关系；灰色节点为技能类（不直接加五维），点节点即可点亮 / 取消，左侧箭头表示前置位于其它分组。</p>
            ${talentNodeGroups(key,nodes,picks)}</section>`;
        }).join('');
        const costs=Object.entries(progress.cost).map(([label,amount])=>{
          const [type,param]=label.split(':');
          const m=P.talents?.star?.materials?.[type]||P.talents?._materials?.[type]||{};
          const name=(param&&m.paramNames?.[param])||m.name||('资源 '+type);
          return `${name} ×${fmt(amount)}`;
        }).join(' · ');
        return `<div class="panel-talent-summary"><strong>天赋投入合计</strong>
            <span>已点亮 ${fmt(progress.nodes)} 个节点</span><span>经验 ${fmt(progress.exp)}</span>
            <span>需角色等级 ${fmt(progress.reqLevel)}</span>
            ${starGrade?`<span>对应品阶 ${esc(starGrade.name)}（累计 ${fmt(starGrade.exp)} 经验）</span>`:''}
            ${costs?`<span class="small-text muted">材料：${esc(costs)}</span>`:''}</div>
          <div class="panel-talent-bonus"><h3>点亮后的效果加成</h3>
            ${talentBonusSummary(progress,C.talentBreakdown(P,char,cfg))}
            <p class="small-text muted">两套天赋分别统计后相加为总加成；<code>upgrade_type=51</code> 的「全职业」节点虽位于其它职业座，加成对所有角色生效，已单独计入。固定值直接加到面板，百分比与装备、刻印、微调一同进入全局乘区。</p></div>
          ${blocks}
          <div class="panel-affix-head panel-affix-head-percent"><span>天赋微调</span><span>百分比 %</span><span>固定值</span></div>
          ${labels.map((lb,i)=>`<div class="panel-affix-row panel-adjust-row"><span>${esc(lb)}</span>
            <label class="panel-percent-input"><input data-path="talentAdjust.${i}" data-percent="10" type="number" step="0.1" value="${esc((C.int(cfg.talentAdjust[i])/10)||0)}" aria-label="${esc(lb)}天赋微调百分比"><em>%</em></label>
            <input data-path="talentAdjustFlat.${i}" type="number" step="1" value="${esc(cfg.talentAdjustFlat[i]||0)}" aria-label="${esc(lb)}天赋微调固定值"></div>`).join('')}
          <p class="small-text muted">微调默认按百分比填写（内部自动转千分比），也可直接填固定值，用于补齐游戏内额外的加成。节点、品阶、经验门槛、等级要求、前置链与材料消耗全部取自客户端 online_tech_* 表；材料名来自 treasure_type / online_tech_material / online_afk_material。</p>`;
      }
      function enchantBlock(slot){
        const ench=cfg[slot].enchant, caps=C.enchantCaps(P,ench.element);
        const elementOptions=P.elements.map(e=>[e.id,e.name]);
        return `<div class="panel-sub"><div class="panel-sub-head">${slot==='weapon'?'武器':'装具'}刻印</div>
          <div class="tool-fields">${sel(`${slot}.enchant.element`,'刻印元素',elementOptions,ench.element)}</div>
          <div class="panel-affix-head panel-affix-head-percent"><span>属性</span><span>百分比 %</span><span>固定值</span></div>
          ${labels.map((lb,i)=>`<div class="panel-affix-row"><span>${lb}</span>
            <label class="panel-percent-input"><input data-path="${slot}.enchant.percents.${i}" data-percent="10" type="number" min="0" max="${(caps.percent[i]/10).toFixed(1)}" step="0.1" value="${esc((C.int(ench.percents[i])/10)||0)}" aria-label="${lb}刻印百分比"><em>%</em></label>
            <input data-path="${slot}.enchant.values.${i}" type="number" min="0" max="${caps.flat[i]}" step="1" value="${esc(ench.values[i]||0)}" aria-label="${lb}刻印固定值"></div>`).join('')}
          <p class="small-text muted">按 % 填写（如 10%），内部换算为客户端定点数参与计算；上限取自客户端刻印属性表（百分比上限 ${caps.percent.map(v=>v/10).join('/')}%、固定值 ${caps.flat.join('/')}）。</p></div>`;
      }
      function entriesBlock(){
        const r=P.charmRarities[cfg.charm.rarity]||['',100,0,60];
        const count=C.clamp(C.int(cfg.charm.entryCount,r[2]),0,r[2]);
        if(!count)return '<p class="small-text muted">该稀有度没有可配置的词条。</p>';
        const typeOptions=P.entryTypes.map(t=>[t.id,`${t.label}（${t.percent?'百分比':'固定值'}）`]);
        return Array.from({length:count},(_,i)=>{
          const e=cfg.charm.entries[i]||{type:P.entryTypes[0]?.id||1,value:0};
          const t=P.entryTypes.find(x=>String(x.id)===String(e.type))||P.entryTypes[0]||{percent:false,stat:0};
          const cap=C.entryCap(P,cfg.charm.rarity,t);
          const pct=!!t.percent;
          const shown=pct?(C.int(e.value)/10):e.value;
          const shownMax=pct?(cap.max/10):cap.max;
          return `<div class="panel-entry-row"><span class="panel-entry-index">${i+1}</span>${sel(`charm.entries.${i}.type`,'词条属性',typeOptions,e.type)}
            ${pct?`<label class="panel-percent-input"><input data-path="charm.entries.${i}.value" data-percent="10" type="number" min="0" max="${shownMax}" step="0.1" value="${esc(shown)}" aria-label="第${i+1}条百分比"><em>%</em></label>`
                 :num(`charm.entries.${i}.value`,'固定值',e.value,0,cap.max,`0 ~ ${cap.max}（0 表示未洗出）`)}</div>`;
        }).join('');
      }
      function showPresets(){
        const list=root.querySelector('#panel-preset-list');if(!list)return;
        list.innerHTML=presets.length?presets.map((p,i)=>`<div class="preset-row"><button type="button" data-panel-preset="${i}">${esc(p.name)}</button><button type="button" data-panel-delete="${i}" aria-label="删除方案 ${esc(p.name)}">×</button></div>`).join(''):'<p class="small-text muted">保存后可在此一键恢复。仅保存在当前浏览器。</p>';
      }
      function paint(focusPath){
        // A full innerHTML rebuild resets the page scroll and the horizontal
        // offset of every topology viewport. Remember both (plus the focused
        // control) so clicking a talent node keeps the reader in place.
        const scrollY=window.scrollY||document.documentElement.scrollTop||0;
        const topoScroll=[...root.querySelectorAll('.panel-topo-scroll')].map((el,i)=>({i,left:el.scrollLeft,top:el.scrollTop}));
        const active=document.activeElement;
        const focusKey=active&&root.contains(active)
          ? (active.dataset?.talentNode!==undefined?'node:'+active.dataset.talentTree+':'+active.dataset.talentNode
             :active.dataset?.topoNode!==undefined?'topo:'+active.dataset.topoTree+':'+active.dataset.topoNode
             :active.dataset?.talentFill!==undefined?'fill:'+active.dataset.talentFill
             :active.dataset?.talentFillAll!==undefined?'fillAll:'+active.dataset.talentFillAll
             :active.dataset?.talentClear!==undefined?'clear:'+active.dataset.talentClear
             :active.dataset?.path||null)
          : null;
        const char=C.findCharacter(P,cfg.character)||P.characters[0];
        const r=P.charmRarities[cfg.charm.rarity]||['',100,0,60];
        root.innerHTML=`${back}${intro('PANEL LAB','面板，算得明明白白。','按角色星级、等级、技能轴、好感度与两套天赋，配合武器装具、刻印与塔罗，逐项算出局外五维面板。数值全部取自本地客户端配置表。')}
          <div class="damage-layout panel-layout panel-layout-three"><nav class="content-card panel-jump ig-nav" aria-label="局外面板计算器区块导航"><h3>快速跳转</h3><div class="panel-jump-links"><a href="#panel-sec-01" data-panel-jump="01"><span>01</span>角色 · 星级 · 技能轴</a><a href="#panel-sec-02" data-panel-jump="02"><span>02</span>武器 · 刻印</a><a href="#panel-sec-03" data-panel-jump="03"><span>03</span>装具 · 刻印</a><a href="#panel-sec-04" data-panel-jump="04"><span>04</span>塔罗 · 词条</a><a href="#panel-sec-05" data-panel-jump="05"><span>05</span>天赋拓扑图</a><a href="#panel-sec-07" data-panel-jump="07"><span>07</span>局外面板结果</a><a href="#panel-damage-result" data-panel-jump="06"><span>06</span>伤害预估结果</a></div><p class="small-text muted">点节点或选项后页面会保持当前位置；点这里可直接跳到对应区块。</p></nav><form id="panel-form" novalidate>
            <section class="content-card" id="panel-sec-01" data-panel-section="01">${heading('01','角色','成长 · 星级 · 技能轴 · 好感度')}${characterButton()}
              <div class="tool-fields">${sel('star','星级',starOptions,cfg.star)}${sel('level','等级',levelOptions,cfg.level)}${sel('rank','已解锁阶数',rankOptions,cfg.rank)}${sel('friendship','好感度',friendOptions,cfg.friendship)}
                <label class="tool-check"><input data-path="enhance" type="checkbox" ${cfg.enhance?'checked':''}><span>极限解放技能轴<small>塔罗角色等拥有强化技能轴时启用</small></span></label></div>
              <div class="panel-lines-head"><h3>技能轴 · 逐阶左右</h3><span class="small-text muted">${esc(char?.tier1||'左')} / ${esc(char?.tier2||'右')}</span></div>
              ${linePicksBlock()}</section>
            <section class="content-card" id="panel-sec-02" data-panel-section="02">${heading('02','武器','按角色武器类型筛选 · 星级 · 等级 · 刻印')}
              <div class="tool-fields">${combo('weapon.id','武器',weaponOptions(char),cfg.weapon.id,'可选「不带」；其余仅显示该角色可装备的武器类型')}${sel('weapon.star','星级',starOptions,cfg.weapon.star)}${sel('weapon.level','等级',levelOptions,cfg.weapon.level)}</div>${equipmentBaseLine('weapon')}${C.int(cfg.weapon.id)?enchantBlock('weapon'):''}</section>
            <section class="content-card" id="panel-sec-03" data-panel-section="03">${heading('03','装具','通用副武器 · 星级 · 等级 · 刻印')}
              <div class="tool-fields">${combo('offhand.id','装具',offhandOptions(),cfg.offhand.id,'可选「不带」；其余仅保留通用副武器类型')}${sel('offhand.star','星级',starOptions,cfg.offhand.star)}${sel('offhand.level','等级',levelOptions,cfg.offhand.level)}</div>${equipmentBaseLine('offhand')}${C.int(cfg.offhand.id)?enchantBlock('offhand'):''}</section>
            <section class="content-card" id="panel-sec-04" data-panel-section="04">${heading('04','塔罗','牌面 · 稀有度 · 等级 · 词条')}
              <div class="tool-fields">${combo('charm.id','塔罗',charmOptions(),cfg.charm.id,'输入牌名可搜索')}${sel('charm.rarity','稀有度',rarityOptions,cfg.charm.rarity)}${sel('charm.level','等级',levelOptions,cfg.charm.level)}${sel('charm.entryCount','词条数',options(0,r[2]),cfg.charm.entryCount)}</div>
              ${equipmentBaseLine('charm')}${C.int(cfg.charm.id)?`<div class="panel-entries">${entriesBlock()}</div>`:''}</section>
            <section class="content-card" id="panel-sec-05" data-panel-section="05">${heading('05','天赋','星辰天赋 · 开拓天赋 · 手动校准')}${talentsBlock()}</section>
            <section class="content-card" id="panel-sec-06" data-panel-section="06">${heading('06','伤害预估','把上方局外面板代入客户端战斗公式')}
              <p class="small-text muted">克制、暴击、易伤上限与高低差全部取自本地配置表，点「公式与数值来源」查看每一项的出处。</p>
              <div class="tool-fields">${sel('combat.stat','攻击属性',[['phys','物攻'],['mag','魔攻']],cfg.combat.stat)}
                ${sel('combat.attackCategory','攻击方职业',catOptions,cfg.combat.attackCategory)}
                ${sel('combat.defenseCategory','防守方职业',catOptions,cfg.combat.defenseCategory)}
                ${sel('combat.highGround','高低差',[['flat','平地'],['up','高出 2 格以上'],['down','低于 2 格以上']],cfg.combat.highGround)}
                ${dmg('defense','目标防御力',cfg.combat.defense,0,1e7)}
                ${dmg('defenseDown','降防 %',cfg.combat.defenseDown,0,100)}
                ${dmg('ignoreDefense','无视防御 %',cfg.combat.ignoreDefense,0,100)}
                ${dmg('skillMult','技能倍率 %',cfg.combat.skillMult,0,100000)}
                ${dmg('damageBonus','增伤 %',cfg.combat.damageBonus,-100,1000)}
                ${dmg('vulnerability','易伤 %',cfg.combat.vulnerability,-100,1000)}
                ${dmg('attackBonusPercent','攻击加成 %',cfg.combat.attackBonusPercent,-100,1000)}
                ${dmg('attackBonusFlat','攻击固定加成',cfg.combat.attackBonusFlat,-1e7,1e7)}</div>
            </section>
          </form><aside class="damage-aside panel-aside" id="panel-sec-07" data-panel-section="07">
            <section class="damage-result" aria-label="局外面板结果"><div class="eyebrow">OUT-OF-BATTLE PANEL</div><h2>局外面板</h2><div id="panel-error" role="alert" hidden></div><div id="panel-output" aria-live="polite"></div><button class="button" type="button" data-tool="export-panel">${h.icon('download',15)}导出计算结果</button></section>
            <details class="content-card panel-aside-fold"><summary><h3>计算分解</h3><span class="fold-hint">展开查看逐项</span></summary><div id="panel-steps"></div></details>
            <section class="content-card" id="panel-damage-result" aria-label="伤害预估结果"><h3>伤害预估</h3><div id="panel-damage" aria-live="polite"></div></section>
            <details class="content-card preset-card panel-aside-fold"><summary><h3>我的面板方案</h3><span class="fold-hint">展开保存 / 载入</span></summary><label class="tool-field"><span>方案名称</span><input id="panel-preset-name" maxlength="40" placeholder="例如：贝拉 · 满配"></label><button class="button secondary small" type="button" data-tool="save-panel">保存当前方案</button><div id="panel-preset-list"></div><div class="tool-backup-actions"><button class="button secondary small" type="button" data-tool="export-panel-plans">导出方案 JSON</button><button class="button secondary small" type="button" data-tool="import-panel-plans">导入方案 JSON</button><button class="button secondary small" type="button" data-tool="reset-panel">恢复默认配置</button></div><input type="file" id="panel-plan-file" accept="application/json,.json" hidden></details>
          </aside></div>
          <details class="content-card tool-help"><summary>公式与使用说明</summary><div class="rich-text"><p>角色基础 = ⌊等级成长 × 稀有度调整 × (100% + 星级% + 技能轴% + 好感度%)⌋ + 已解锁各阶的固定加成，与客户端 <code>CalculateAttributeByType</code> 的定点数算法一致。</p><p>技能轴按每一阶独立选择左 / 右 / 都点 / 未点；只有该阶存在属性节点时才会影响面板。极限解放会用配置表中的强化行替换同阶普通行。</p><p>星辰天赋与开拓天赋来自客户端 <code>online_tech_node</code> / <code>online_tech_node_level</code> 系列表。每一行是「升到该等级后的累计加成」（如黑铁攻击强化 Lv.1 +5、Lv.2 +10），因此点满只取最高等级那一行，不会把各级累加成 +15；经验与材料则是每一级分别消耗，点满需累加。合计按各节点当前等级相加，固定值直接进面板、千分比进全局乘区，可用微调校准游戏内的额外加成。</p><p>武器、装具与塔罗按同样的百分位约定计算等级成长；刻印固定值、天赋固定值与塔罗词条固定值直接累加；刻印 / 词条 / 天赋与微调的百分比对合计统一结算：最终值 = ⌊角色白板值 × (100% + 百分比)⌋ + 装备 / 天赋 / 词条的固定值。</p><p>星级、技能轴、好感度作用于角色成长本身，装备与天赋的百分比作用于最终合计，是两个不同的乘区。敏捷来自客户端单位表，不参与上述计算。结果不含战斗内增益、技能被动与阵营加成；游戏实际结算如有额外取整，以实机为准。</p></div></details>
          <details class="content-card tool-help"><summary>公式与数值来源</summary><div class="rich-text">
            ${(combat.formulas||[]).map(f=>`<section class="formula-block"><h3>${esc(f.title)}</h3>
              <p class="formula-expr"><code>${esc(f.expr)}</code></p><p>${esc(f.source)}</p>
              <ol class="formula-steps">${(f.steps||[]).map(s=>`<li>${esc(s)}</li>`).join('')}</ol>
              ${(f.variables||[]).length?`<div class="table-scroll"><table class="data-table formula-vars"><thead><tr><th>符号</th><th>含义</th><th>单位</th><th>来源表</th><th>说明</th></tr></thead><tbody>
                ${f.variables.map(v=>`<tr><td><strong>${esc(v.symbol)}</strong></td><td>${esc(v.name)}</td><td>${esc(v.unit)}</td><td class="mech-source">${esc(v.source)}</td><td>${esc(v.note||'')}</td></tr>`).join('')}
              </tbody></table></div>`:''}</section>`).join('')}
            <h3>战斗常量 · const_param</h3><div class="table-scroll"><table class="data-table"><thead><tr><th>名称</th><th>值</th><th>说明</th><th>来源</th></tr></thead><tbody>
              ${Object.entries(combat.constants||{}).map(([k,c])=>`<tr><td><strong>${esc(c.label)}</strong><small>${esc(k)}</small></td><td>${esc(c.value)}</td><td>${esc(c.note||'')}</td><td class="mech-source">${esc(c.source)}</td></tr>`).join('')}
            </tbody></table></div>
            <h3>职业克制 · profession_restrain</h3><div class="table-scroll"><table class="data-table"><thead><tr><th>攻击方</th><th>防守方</th><th>系数</th><th>来源</th></tr></thead><tbody>
              ${(combat.restraints||[]).map(r=>`<tr><td>${esc(r.fromName)}</td><td>${esc(r.toName)}</td><td>${esc(r.percent)}%</td><td class="mech-source">${esc(r.source)}</td></tr>`).join('')}
            </tbody></table></div>
            <h3>参与计算的配置表</h3><ul>${(combat.references||[]).map(r=>`<li><code>${esc(r.table)}</code> — ${esc(r.provides)}（${esc(r.bundle)}）</li>`).join('')}</ul>
            <p><a href="#/mechanics">打开机制规则图鉴 ↗</a>，可查阅技能范围、聚拢与击退等配置表规则。</p>
          </div></details>
          <div class="source-footer"><span>数值取自本地游戏客户端配置表 · 完全离线运行</span><a href="#/archive">查看资料馆信息 →</a></div>`;
        showPresets();update();
        const topo=[...root.querySelectorAll('.panel-topo-scroll')];
        for(const saved of topoScroll){const el=topo[saved.i];if(el){el.scrollLeft=saved.left;el.scrollTop=saved.top;}}
        // The wiki sets html{scroll-behavior:smooth}; an animated restore would
        // look like a jump back to the top and lands too late. Force instant.
        window.scrollTo({top:scrollY,left:0,behavior:'instant'});
        if(focusPath){const el=root.querySelector(`[data-path="${focusPath}"]`);el?.focus({preventScroll:true});}
        else if(focusKey){
          const [kind,a,b]=focusKey.split(':');
          const el=kind==='node'?root.querySelector(`[data-talent-node="${b}"][data-talent-tree="${a}"]`)
            :kind==='topo'?root.querySelector(`[data-topo-node="${b}"][data-topo-tree="${a}"]`)
            :kind==='fill'?root.querySelector(`[data-talent-fill="${a}"]`)
            :kind==='fillAll'?root.querySelector(`[data-talent-fill-all="${a}"]`)
            :kind==='clear'?root.querySelector(`[data-talent-clear="${a}"]`)
            :root.querySelector(`[data-path="${focusKey}"]`);
          el?.focus?.({preventScroll:true});
        }
      }
      function setPath(obj,path,value){
        const keys=path.split('.');let cur=obj;
        for(let i=0;i<keys.length-1;i++){
          if(cur[keys[i]]==null||typeof cur[keys[i]]!=='object')cur[keys[i]]={};
          cur=cur[keys[i]];
        }
        cur[keys[keys.length-1]]=value;
      }
      function readForm(){
        const form=root.querySelector('#panel-form');if(!form)return;
        for(const el of form.querySelectorAll('[data-path]')){
          let value;
          if(el.type==='checkbox')value=el.checked;
          else if(el.dataset.percent)value=Math.round(Number(el.value||0)*Number(el.dataset.percent));
          else if(el.type==='number')value=C.int(el.value);
          else value=el.value;
          setPath(cfg,el.dataset.path,value);
        }
      }
      const pct=v=>(Number(v||0)/10);
      const pctText=v=>`${Number.isInteger(pct(v))?pct(v):pct(v).toFixed(1)}%`;
      const jumpNum=(value,section,label)=>`<button type="button" class="formula-num" data-formula-jump="${section}"
        title="${esc(label)} · 点击跳转到来源区块">${fmt(value)}</button>`;
      const formulaMarkup=r=>{
        const f=r.formula;
        if(!f)return '';
        const options=r.labels.map((lb,i)=>`<option value="${i}">${esc(lb)}</option>`).join('');
        const rows=r.labels.map((lb,i)=>{
          const fixed=f.terms.map(term=>`<span class="formula-term"><em>${esc(term.label)}</em>${jumpNum(term.values[i],term.section,term.label)}</span>`).join('<b>+</b>');
          const white=r.whiteboard?.[i]??r.base[i];
          const addend=r.addends?.[i]??(r.flat[i]-white);
          const addParts=f.terms.filter(x=>x.key!=='base').map(term=>`<span class="formula-term"><em>${esc(term.label)}</em>${jumpNum(term.values[i],term.section,term.label)}</span>`).join('<b>+</b>');
          return `<div class="formula-row" data-stat="${i}"${i?' hidden':''}>
            <code><em>⌊ 白板</em> ${jumpNum(white,'01','角色白板值')} × ( 100% + ${pctText(r.permillage[i])} ) <em>⌋ + (</em> ${addParts||'0'} <em>) =</em> <strong>${fmt(r.total[i])}</strong></code>
            <div class="formula-per-parts">${f.permParts.map(part=>`<button type="button" class="formula-num" data-formula-jump="${part.section}" title="${esc(part.label)} · 点击跳转">${esc(part.label)} +${pctText(part.values[i])}</button>`).join('')}</div></div>`;
        }).join('');
        return `<details class="panel-formula"><summary><h3>面板计算公式 <small>点任意数字跳到产生它的区块</small></h3></summary>
          <label class="tool-field"><span>查看属性</span><select data-formula-stat>${options}</select></label>
          ${rows}
          <p class="small-text muted">百分比只乘在<strong>角色白板值</strong>上（客户端：卸下所有装备、再减去天赋所增加的属性后的值；见塔罗图鉴库 / 附魔图鉴库），装备与天赋的固定值在乘区之外相加。客户端内部按千分比结算，界面统一显示 %；每个数字与来源标签都可点击跳转。</p></details>`;
      };
      function update(){
        readForm();
        refreshEquipmentBases();
        const cr=P.charmRarities[cfg.charm.rarity]||['',100,0,60];
        cfg.charm.entryCount=C.clamp(C.int(cfg.charm.entryCount,cr[2]),0,cr[2]);
        const error=root.querySelector('#panel-error'), output=root.querySelector('#panel-output'), steps=root.querySelector('#panel-steps');
        if(!output)return;
        try{
          const r=C.calculate(cfg,P);h.persist('panel.current',cfg);error.hidden=true;
          const world=window.WIKI_WORLD_DATA||{};
          const bp=C.battlePower(r,world,P,{...battlePowerState});
          output.innerHTML=`<div class="panel-total-grid panel-total-grid-pairs"><div class="panel-total-hp"><span>${labels[0]}</span><strong>${fmt(r.total[0])}</strong></div><div class="panel-total-pair"><span>${labels[1]} / ${labels[2]}</span><strong>${fmt(r.total[1])} / ${fmt(r.total[2])}</strong></div><div class="panel-total-pair"><span>${labels[3]} / ${labels[4]}</span><strong>${fmt(r.total[3])} / ${fmt(r.total[4])}</strong></div></div>
            <div class="panel-battle-power"><span>战斗力 <small>公式未确证 · 可切换 / 校准</small></span><strong>${fmt(bp.total)}</strong></div>
            <section class="panel-bp-detail panel-bp-formula"><h3>战斗力计算公式 <small>先列证据与候选，再代入数值</small></h3>
              <div class="panel-bp-warning">已穷举本地客户端配置表、Lua 片段与 IL2CPP 元数据：
                <strong>只找到系数，没有找到把系数装配成最终战力的公式</strong>（逻辑在编译后的 <code>GameAssembly.dll</code> 中）。
                下面列出全部可查证据与 4 种候选，可切换对照，也可填入游戏内实际战力反推倍率。</div>
              <details class="panel-bp-evidence" open><summary>客户端证据清单（${bp.evidence.length} 条）</summary>
                <ol>${bp.evidence.map(x=>`<li>${esc(x)}</li>`).join('')}</ol></details>
              <div class="panel-bp-controls">
                <label class="tool-field"><span>候选公式</span><select data-bp-method>
                  ${bp.candidates.map(c=>`<option value="${esc(c.id)}" ${c.id===bp.method?'selected':''}>${esc(c.label)}</option>`).join('')}
                </select></label>
                <label class="tool-field"><span>倍率（校准用）</span><input type="number" data-bp-scale step="0.01" min="0.01" value="${bp.scale}"></label>
                <label class="tool-field"><span>游戏内实际战力（反推倍率）</span><input type="number" data-bp-calibration min="0" step="1" value="${bp.calibration||''}" placeholder="填入后可反推"></label>
              </div>
              <p class="panel-bp-expr">${esc(bp.candidates.find(c=>c.id===bp.method)?.expr||bp.formula)}</p>
              <p class="small-text muted">${esc(bp.candidates.find(c=>c.id===bp.method)?.basis||'')}</p>
              ${bp.impliedScale?`<p class="panel-bp-implied">按填入的 ${fmt(bp.calibration)} 反推，客户端等效倍率约为 <strong>${bp.impliedScale.toFixed(4)}</strong>（当前公式取 ${bp.scale}）。</p>`:''}
              <ol class="panel-bp-steps">
                <li><b>①</b> 取局外面板五维：
                  ${labels.map((lb,i)=>`<span>${esc(lb)} <strong>${fmt(bp.stats[i])}</strong></span>`).join('')}
                  <em>来源：局外面板最终结果</em></li>
                <li><b>②</b> 按 <code>const_param#${esc(bp.constId)} = ${bp.hpWeight}|${bp.otherWeight}</code> 加权：
                  ${labels.map((lb,i)=>`<span>${esc(lb)} ${fmt(bp.stats[i])} × ${i===0?bp.hpWeight:bp.otherWeight}‰ = <strong>${fmt(Math.round(bp.parts[i]*100)/100)}</strong></span>`).join('')}
                  <em>120 / 200 是千分比权重，不是除数</em></li>
                <li><b>③</b> 合计基础得分：
                  <span>${bp.parts.map(v=>fmt(Math.round(v*100)/100)).join(' + ')} = <strong>${fmt(Math.round(bp.base*100)/100)}</strong></span></li>
                <li><b>④</b> 乘稀有度修正：
                  <span>${fmt(Math.round(bp.base*100)/100)} × ${bp.rarity}% = <strong>${fmt(Math.round(bp.base*bp.rarity/100*100)/100)}</strong></span>
                  <em>${esc(bp.rarityName||'角色稀有度')} · unit_rarity.battle_power_adjust</em></li>
                <li><b>⑤</b> 乘职业修正并取整：
                  <span>${fmt(Math.round(bp.base*bp.rarity/100*100)/100)} × ${bp.profession}% → <strong>${fmt(bp.total)}</strong></span>
                  <em>battle_power_coefficient.percent</em></li>
              </ol>
              <dl class="calculation-steps">
                <div><dt>系数出处</dt><dd>const_param#${esc(bp.constId)} OnlineRoleUnitBattlePowerCoefficient</dd></div>
                <div><dt>量级校准</dt><dd>${esc(bp.calibration)}</dd></div>
              </dl>
              <p class="small-text muted">${esc(bp.source)}。装配公式位于客户端编译代码中，配置表只给出系数与上述参考数值；<strong>本项结果未经游戏内数值验证</strong>，请用上方校准框对照实机。</p></section>
            <dl class="calculation-steps"><div><dt>敏捷</dt><dd>${fmt(r.speed)}</dd></div><div><dt>最终百分比</dt><dd>${r.permillage.map(v=>'+'+pctText(v)).join(' / ')}</dd></div></dl>
            ${formulaMarkup(r)}`;
          steps.innerHTML=`<dl class="calculation-steps panel-step-list">${r.extras.map(e=>`<div><dt>${esc(e.label)}</dt><dd>${e.values.map((v,i)=>labels[i]+' '+fmt(v)).join(' · ')}${e.permillage?` · ${e.permillage.map(v=>'+'+pctText(v)).join(' / ')}`:''}</dd></div>`).join('')}</dl><p class="small-text muted">顺序：${esc(labels.join(' / '))}。角色基础已含星级、技能轴与好感度加成。</p>`;
          const dmgBox=root.querySelector('#panel-damage');
          if(dmgBox){
            const d=C.damage(r,combat,cfg.combat);
            dmgBox.innerHTML=`<div class="panel-damage-total"><span>普通伤害</span><strong>${fmt(d.damage)}</strong></div>
              <dl class="calculation-steps"><div><dt>暴击伤害</dt><dd>${fmt(d.criticalDamage)}（基础暴击 ${Math.round(d.criticalChance*100)}%）</dd></div>
              <div><dt>有效攻击</dt><dd>${fmt(Math.round(d.attack*d.restraint*d.height))}（克制 ${d.restraint.toFixed(2)} × 高低差 ${d.height.toFixed(2)}）</dd></div>
              <div><dt>有效防御</dt><dd>${fmt(Math.round(d.defense))}</dd></div>
              <div><dt>差值 × 倍率</dt><dd>${fmt(Math.round(d.base))} × ${d.skill.toFixed(2)} × ${d.bonus.toFixed(2)} × ${d.vulnerability.toFixed(2)}</dd></div></dl>
              <p class="small-text muted">克制 ${esc(d.sources.restraint)} · 高低差 ${esc(d.sources.highGround)} · 暴击 ${esc(d.sources.critical)}</p>
              <details class="formula-live"><summary>当前配置的公式变量</summary>
                <dl class="calculation-steps"><div><dt>② 角色五维（G × P + K）</dt><dd>${r.base.map(fmt).join(' / ')}</dd></div>
                <div><dt>③ 固定值合计 F</dt><dd>${r.flat.map((v,i)=>fmt(v-r.base[i])).join(' / ')}</dd></div>
                <div><dt>④ 全局百分比 Q</dt><dd>${r.permillage.map(v=>'+'+pctText(v)).join(' / ')}</dd></div>
                <div><dt>A 有效攻击</dt><dd>${fmt(Math.round(d.attack*d.restraint*d.height))} = ${fmt(Math.round(d.attack))} × ${d.restraint.toFixed(2)} × ${d.height.toFixed(2)}</dd></div>
                <div><dt>D 有效防御</dt><dd>${fmt(Math.round(d.defense))}</dd></div></dl></details>`;
          }
          const btn=root.querySelector('[data-tool="export-panel"]');if(btn)btn.dataset.ready='1';
        }catch(e){error.textContent=e.message;error.hidden=false;output.innerHTML='<p class="result-empty">修正输入后即可继续计算。</p>';steps.innerHTML='';}
      }
      on('submit',e=>e.preventDefault());
      on('input',e=>{
        const comboInput=e.target.closest?.('[data-combo]');
        if(comboInput){showCombo(comboInput,comboInput.value);return;}
        if(e.target.closest?.('#panel-form'))update();
      });
      on('change',e=>{
        const bpEl=e.target.closest?.('[data-bp-method],[data-bp-scale],[data-bp-calibration]');
        if(bpEl){
          if(bpEl.dataset.bpMethod!==undefined)battlePowerState.method=bpEl.value;
          if(bpEl.dataset.bpScale!==undefined)battlePowerState.scale=Number(bpEl.value)||1;
          if(bpEl.dataset.bpCalibration!==undefined)battlePowerState.calibration=Number(bpEl.value)||0;
          update();return;
        }
        if(e.target.id==='panel-plan-file'){
          const file=e.target.files?.[0];e.target.value='';
          if(!file)return;
          if(file.size>2*1024*1024){h.toast('方案文件过大（上限 2 MB）');return;}
          file.text().then(text=>{
            let payload;
            try{payload=JSON.parse(text);}catch(err){h.toast('不是有效的 JSON 文件');return;}
            if(payload.format&&payload.format!=='socwiki-panel-plans'&&payload.format!=='socwiki-panel'){
              h.toast('文件格式不符：需要 socwiki-panel-plans');return;
            }
            const incoming=Array.isArray(payload.presets)?payload.presets:[];
            const valid=incoming.filter(x=>x&&typeof x.name==='string'&&x.config&&typeof x.config==='object')
              .slice(0,20).map(x=>({name:x.name.slice(0,40),config:x.config}));
            if(!valid.length&&!payload.config&&!payload.current){
              h.toast('文件里没有可导入的方案');return;
            }
            for(const item of valid){
              const i=presets.findIndex(p=>p.name===item.name);
              if(i<0&&presets.length>=20)break;
              if(i<0)presets.push(item);else presets[i]=item;
            }
            h.persist('panel.presets',presets);
            const next=payload.config||payload.current;
            if(next){
              cfg=normalize(next);fixEquipment();
            }
            showPresets();paint();
            h.toast(`已导入 ${valid.length} 个方案${next?'并载入当前配置':''}`);
          }).catch(err=>h.toast('读取失败：'+err.message));
          return;
        }
        if(e.target.closest?.('[data-formula-stat]')){
          const v=e.target.value;
          for(const row of root.querySelectorAll('.formula-row'))row.hidden=row.dataset.stat!==v;
          return;
        }
        const el=e.target;if(!el.closest||!el.closest('#panel-form'))return;
        const path=el.dataset.path||'';
        if(el.dataset.talentLevel!==undefined){
          cfg.talentNodes=cfg.talentNodes||{};
          cfg.talentNodes[el.dataset.talentTree]=cfg.talentNodes[el.dataset.talentTree]||{};
          cfg.talentNodes[el.dataset.talentTree][el.dataset.talentLevel]=C.int(el.value);
          cfg.talentNodesExplicit=true;
          paint();return;
        }
        if(path==='charm.rarity'||path==='charm.entryCount'||path.endsWith('.enchant.element')||path.endsWith('.type')||path.startsWith('talent.')||path.startsWith('talentView.')){readForm();paint(path);}
        else update();
      });
      on('click',e=>{
        if(!e.target.closest?.('.panel-combo-field'))closeCombos();
        const formulaStat=e.target.closest?.('[data-formula-stat]');
        if(formulaStat){return;}
        const formulaNum=e.target.closest?.('[data-formula-jump]');
        if(formulaNum){
          e.preventDefault();
          const sec=root.querySelector(`#panel-sec-${formulaNum.dataset.formulaJump}`);
          if(sec){
            sec.scrollIntoView({behavior:'smooth',block:'start'});
            sec.classList.remove('panel-sec-flash');void sec.offsetWidth;sec.classList.add('panel-sec-flash');
            for(const a of root.querySelectorAll('[data-panel-jump]'))
              a.classList.toggle('active',a.dataset.panelJump===formulaNum.dataset.formulaJump);
          }
          return;
        }
        const jump=e.target.closest?.('[data-panel-jump]');
        if(jump){
          e.preventDefault();
          const target=jump.dataset.panelJump==='06'
            ? root.querySelector('#panel-damage-result')
            : root.querySelector(`#panel-sec-${jump.dataset.panelJump}`);
          if(target){
            // 06 lives at the very bottom of the right column: force the page
            // all the way down so the card is fully in view.
            if(jump.dataset.panelJump==='06'){
              window.scrollTo({top:document.documentElement.scrollHeight,behavior:'smooth'});
              const aside=root.querySelector('.damage-aside');
              if(aside)aside.scrollTo({top:aside.scrollHeight,behavior:'smooth'});
              target.classList.remove('panel-sec-flash');void target.offsetWidth;target.classList.add('panel-sec-flash');
            }else{
              target.scrollIntoView({behavior:'smooth',block:'start'});
            }
            for(const a of root.querySelectorAll('[data-panel-jump]'))a.classList.toggle('active',a===jump);
          }
          return;
        }
        const topo=e.target.closest?.('[data-topo-node]');
        if(topo){
          const key=topo.dataset.topoTree,id=topo.dataset.topoNode;
          const tree=C.talentTree(P,key,C.findCharacter(P,cfg.character));
          const node=(tree?.nodes||[]).find(n=>String(n.id)===String(id));
          cfg.talentNodes=cfg.talentNodes||{};
          cfg.talentNodes[key]=cfg.talentNodes[key]||{};
          cfg.talentNodesExplicit=true;
          const current=C.int(cfg.talentNodes[key][id],0);
          cfg.talentNodes[key][id]=current>0?0:(node?.levels.length||1);
          paint();return;
        }
        const comboInput=e.target.closest?.('[data-combo]');
        if(comboInput){showCombo(comboInput,'');return;}
        const option=e.target.closest?.('[data-combo-value]');
        if(option){
          const field=option.closest('.panel-combo-field'),hidden=field.querySelector('[data-path]'),input=field.querySelector('[data-combo]');
          hidden.value=option.dataset.comboValue;input.value=option.dataset.comboLabel;
          field.querySelector('.panel-combo-list').hidden=true;input.setAttribute('aria-expanded','false');
          // Choosing / clearing an item changes which sub-forms exist, so a
          // repaint (not just an update) is needed to show or hide 刻印/词条.
          readForm();
          paint();return;
        }
        const target=e.target.closest('button');if(!target)return;
        if(target.dataset.lineRank!==undefined){
          cfg.linePicks=cfg.linePicks||{};
          cfg.linePicks[target.dataset.lineRank]=target.dataset.linePick;
          paint();return;
        }
        if(target.dataset.lineNode!==undefined){
          const rank=target.dataset.lineNode,side=target.dataset.lineSide;
          cfg.linePicks=cfg.linePicks||{};
          const left=lineOn(rank,'left'),right=lineOn(rank,'right');
          const nextLeft=side==='left'?!left:left,nextRight=side==='right'?!right:right;
          cfg.linePicks[rank]=nextLeft&&nextRight?'both':nextLeft?'left':nextRight?'right':'none';
          paint();return;
        }
        if(target.dataset.talentNode!==undefined){
          const key=target.dataset.talentTree,id=target.dataset.talentNode;
          const tree=C.talentTree(P,key,C.findCharacter(P,cfg.character));
          const node=(tree?.nodes||[]).find(n=>String(n.id)===String(id));
          cfg.talentNodes=cfg.talentNodes||{};
          cfg.talentNodes[key]=cfg.talentNodes[key]||{};
          cfg.talentNodesExplicit=true;
          const current=C.int(cfg.talentNodes[key][id],0);
          cfg.talentNodes[key][id]=current>0?0:(node?.levels.length||1);
          paint();return;
        }
        if(target.dataset.talentFill!==undefined||target.dataset.talentFillAll!==undefined||
           target.dataset.talentClear!==undefined||target.dataset.talentClearGroup!==undefined){
          const key=target.dataset.talentFill||target.dataset.talentFillAll||target.dataset.talentClear||target.dataset.talentClearGroup;
          const char=C.findCharacter(P,cfg.character);
          cfg.talentNodes=cfg.talentNodes||{};
          cfg.talentNodes[key]=cfg.talentNodes[key]||{};
          cfg.talentNodesExplicit=true;
          if(target.dataset.talentClear!==undefined){
            cfg.talentNodes[key]={};
            h.toast(key === 'star' ? '已清空星辰天赋全树' : '已清空开拓天赋全树');
          }else if(target.dataset.talentClearGroup!==undefined){
            const tree=C.talentTree(P,key,char);
            const gid=Number(target.dataset.talentGroup);
            let removed=0;
            for(const n of tree?.nodes||[]){
              const inGroup=key==='star'?n.grade===gid:n.unlockGroup===gid;
              if(inGroup&&cfg.talentNodes[key][n.id]){delete cfg.talentNodes[key][n.id];removed++;}
            }
            h.toast(`已清空本${key==='star'?'品阶':'图'}的 ${removed} 个节点`);
          }else{
            const group=target.dataset.talentFill===undefined?null:target.dataset.talentGroup;
            const changed=C.talentFillAll(P,char,cfg,key,group,true);
            h.toast(changed?`已点亮 ${changed} 个节点`:'这些节点已经全部点亮');
          }
          paint();return;
        }
        if(target.dataset.tool==='pick-character'){
          window.WikiCharacterPicker?.open({pages:pickerPages,current:pageId(cfg.character),title:'选择角色',
            note:'仅列出客户端提供局外面板数值的角色；与角色图鉴共用筛选、排序与拼音搜索规则。'})
            .then(page=>{
              if(!page||!page.panelKey)return;
              cfg.character=page.panelKey;
              const char=C.findCharacter(P,cfg.character);
              cfg.weapon.id=weaponOptions(char)[0]?.[0]??0;
              cfg.offhand.id=offhandOptions()[0]?.[0]??0;
              cfg.linePicks=defaultPicks(char);
              if(!cfg.talentNodesExplicit)cfg.talentNodes=C.defaultTalentNodes(P,char);
              paint();
            }).catch(()=>{});
          return;
        }
        if(target.dataset.panelPreset!==undefined){const p=presets[Number(target.dataset.panelPreset)];if(p){cfg=normalize(p.config);fixEquipment();paint();root.querySelector('#panel-preset-name').value=p.name;h.toast('已载入方案：'+p.name);}}
        if(target.dataset.panelDelete!==undefined){presets.splice(Number(target.dataset.panelDelete),1);h.persist('panel.presets',presets);showPresets();h.toast('已删除面板方案');}
        if(target.dataset.tool==='reset-panel'){cfg=normalize(null);fixEquipment();paint();h.toast('已恢复默认配置');}
        if(target.dataset.tool==='save-panel'){
          const name=root.querySelector('#panel-preset-name').value.trim();
          if(!name){root.querySelector('#panel-preset-name').focus();h.toast('先为方案起个名字');return;}
          const i=presets.findIndex(p=>p.name===name);
          if(i<0&&presets.length>=20){h.toast('最多保存 20 个方案');return;}
          const item={name,config:JSON.parse(JSON.stringify(cfg))};
          if(i<0)presets.push(item);else presets[i]=item;
          h.persist('panel.presets',presets);showPresets();h.toast(i<0?'方案已保存':'同名方案已更新');
        }
        if(target.dataset.tool==='export-panel-plans'){
          const typed=root.querySelector('#panel-preset-name')?.value.trim()||'';
          const planName=typed||(presets.length===1?presets[0].name:'')||'局外面板方案';
          const safe=planName.replace(/[\\/:*?"<>|\r\n]/g,'_').slice(0,60).trim()||'局外面板方案';
          download(`铃兰档案馆-${safe}.json`,JSON.stringify({
            format:'socwiki-panel-plans',version:1,exportedAt:new Date().toISOString(),
            planName,current:cfg,presets},null,2));
          h.toast(`已以「${planName}」导出 ${presets.length} 个方案`);return;
        }
        if(target.dataset.tool==='import-panel-plans'){
          root.querySelector('#panel-plan-file')?.click();return;
        }
        if(target.dataset.tool==='export-panel'){
          try{
            const r=C.calculate(cfg,P);
            download('铃兰档案馆-局外面板.json',JSON.stringify({format:'socwiki-panel',version:2,exportedAt:new Date().toISOString(),config:cfg,
              labels:r.labels,total:r.total,base:r.base,weapon:r.weapon,offhand:r.offhand,tarot:r.tarot,
              talent:r.talent,permillage:r.permillage,speed:r.speed,steps:r.extras},null,2));
          }catch(err){h.toast(err.message);}
        }
      });
      paint();
    }
    function equipment(){
      const data=D.equipment,order={'SSR':0,'SR':1,'R':2,'N':3},rarities=[...new Set(data.rows.map(r=>r.rarity))].sort((a,b)=>(order[a]??9)-(order[b]??9)),weapons=[...new Set(data.rows.map(r=>r.weapon))];
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
