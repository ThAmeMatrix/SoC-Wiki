
 function getRestraint(atk, def) {
  if (atk === "none" || def === "none") return 1.0;
  if (atk === def) return 1.0;
  var map = {
    crusher_defender: 1.3,
    defender_crusher: 0.7,
    defender_raider: 1.3,
    raider_defender: 0.7,
    raider_crusher: 1.3,
    crusher_raider: 0.7,
    watcher_destroyer: 1.4,
    destroyer_watcher: 0.6
  };
  var key = atk + "_" + def;
  return map[key] !== undefined ? map[key] : 1.0;
}

var classNames = {
  none: "--",
  crusher: "粉碎者",
  defender: "防御者",
  raider: "突袭者",
  destroyer: "毁灭者",
  watcher: "守望者"
};

function num(id) {
  var el = document.getElementById(id);
  if (!el) return 0;
  var v = parseFloat(el.value);
  return isNaN(v) ? 0 : v;
}

function sumComma(id) {
  var el = document.getElementById(id);
  if (!el) return 0;
  var val = (el.value || "").trim();
  val = val.replace(/，/g, ',');
  return val.split(",").reduce(function(s, p) {
    var n = parseFloat(p);
    return s + (isNaN(n) ? 0 : n);
  }, 0);
}

function mulComma(id) {
  var el = document.getElementById(id);
  if (!el) return 1;
  var val = (el.value || "").trim();
  val = val.replace(/，/g, ',');
  return val.split(",").reduce(function(m, p) {
    var n = parseFloat(p);
    return m * (isNaN(n) ? 1 : 1 + n / 100);
  }, 1);
}

function ignoreDefMul(id) {
  var el = document.getElementById(id);
  if (!el) return 1;
  var val = (el.value || "").trim();
  val = val.replace(/，/g, ',');
  return val.split(",").reduce(function(m, p) {
    var n = parseFloat(p);
    return m * (isNaN(n) ? 1 : 1 - n / 100);
  }, 1);
}

function calculate() {
  try {
    var atkClass = document.getElementById("atkClass");
    var defClass = document.getElementById("defClass");
    var defDebuffEl = document.getElementById("defDebuff");
    var hornBuffEl = document.getElementById("hornBuff");

    atkClass = atkClass ? atkClass.value : "none";
    defClass = defClass ? defClass.value : "none";

    var atkPanel = num("atkPanel");
    var atkBonusPct = sumComma("atkBonusPct");
    var atkBonusFlat = sumComma("atkBonusFlat");
    var skillMult = num("skillMult");
    var critDmgPct = sumComma("critDmgPct");
    var defBase = num("defBase");
    var ignoreDefMulVal = ignoreDefMul("ignoreDefPct");
    var defReduceFlat = sumComma("defReduceFlat");
    var defDebuff = defDebuffEl ? parseFloat(defDebuffEl.value) || 0 : 0;
    var hornBuff = hornBuffEl ? hornBuffEl.checked : false;
    var dmgZone = sumComma("dmgZone");
    var vulnZoneEl = document.getElementById("vulnZone");
    var vulnZone = vulnZoneEl ? (vulnZoneEl.value || "") : "";
    var finalDmgZone = sumComma("finalDmgZone");
    var finalVulnMult = mulComma("finalVulnZone");

    var restraint = getRestraint(atkClass, defClass);

    var infoEl = document.getElementById("restraintInfo");
    if (infoEl) {
      if (atkClass === "none") {
        infoEl.innerHTML = "";
      } else if (defClass === "none") {
        infoEl.innerHTML = "";
      } else if (defClass === "noClass") {
        infoEl.innerHTML = (classNames[atkClass] || "--") + " 对 无职业: 无克制 ×1.0";
      } else {
        var label = (classNames[atkClass] || "--") + " 对 " + (classNames[defClass] || "--") + ": ";
        if (restraint > 1) {
          infoEl.innerHTML = label + '<span class="advantage">克制 ×' + restraint + '</span>';
        } else if (restraint < 1) {
          infoEl.innerHTML = label + '<span class="disadvantage">被克制 ×' + restraint + '</span>';
        } else {
          infoEl.innerHTML = label + '<span class="neutral">无克制 ×1.0</span>';
        }
      }
    }

    var effectiveAtk = atkPanel * (1 + atkBonusPct / 100) + atkBonusFlat;
    var afterRestraint = effectiveAtk * restraint;
    var defDebuffValue = defBase * (defDebuff / 100);
    var hornDefValue = hornBuff ? defBase * 0.2 : 0;
    var defAfterReduce = Math.max(0, defBase - defDebuffValue - hornDefValue - defReduceFlat);
    var effectiveDef = defAfterReduce * ignoreDefMulVal;
    var baseDmg = Math.max(0, afterRestraint - effectiveDef);
    var dmgMult = Math.max(0.5, 1 + dmgZone / 100);
    var finalDmgMult = mulComma("finalDmgZone");
    var baseVulnVal = vulnZone.trim().replace(/，/g, ',');
    var vulnMult = baseVulnVal.split(",").reduce(function(m, p) {
      var n = parseFloat(p);
      return m * (isNaN(n) ? 1 : 1 + n / 100);
    }, 1);
    if (hornBuff) { vulnMult = vulnMult * 1.8; }
    vulnMult = Math.min(vulnMult, 3.0);
    var skill = skillMult / 100;
    var singleHit = baseDmg * skill * dmgMult * vulnMult * finalDmgMult * finalVulnMult;
    var critSingle = singleHit * (critDmgPct / 100);
    singleHit = Math.max(0, singleHit);
    critSingle = Math.max(0, critSingle);

    var singleDmgEl = document.getElementById("singleDmg");
    var critSingleDmgEl = document.getElementById("critSingleDmg");
    var formulaBreakdownEl = document.getElementById("formulaBreakdown");

    if (singleDmgEl) singleDmgEl.textContent = Math.round(singleHit).toLocaleString();
    if (critSingleDmgEl) critSingleDmgEl.textContent = Math.round(critSingle).toLocaleString();

    var br = "";
    br += "有效攻击力       = " + atkPanel + " × (1 + " + atkBonusPct + "%) + " + atkBonusFlat + " = " + effectiveAtk.toFixed(2) + "\n";
    br += "克制后攻击力     = " + effectiveAtk.toFixed(2) + " × " + restraint + " = " + afterRestraint.toFixed(2) + "\n\n";
    br += "【防御计算】\n";
    br += "黑字防御         = " + defBase + "\n";
    if (defDebuff > 0) {
      br += "防御减益(-" + defDebuff + "%)  = " + defBase + " × " + (defDebuff/100) + " = -" + defDebuffValue.toFixed(2) + "\n";
    }
    if (hornBuff) {
      br += "号角防御(-20%)   = " + defBase + " × 0.2 = -" + hornDefValue.toFixed(2) + "\n";
    }
    if (defReduceFlat > 0) {
      br += "固定防御减少     = -" + defReduceFlat + "\n";
    }
    br += "防御减少后       = " + defAfterReduce.toFixed(2) + "\n";
    br += "无视防御系数     = " + ignoreDefMulVal.toFixed(4) + " (乘算)\n";
    br += "有效防御力       = " + defAfterReduce.toFixed(2) + " × " + ignoreDefMulVal.toFixed(4) + " = " + effectiveDef.toFixed(2) + "\n";
    br += "基础伤害         = " + afterRestraint.toFixed(2) + " - " + effectiveDef.toFixed(2) + " = " + baseDmg.toFixed(2) + "\n\n";
    br += "【伤害计算】\n";
    br += "技能倍率         = " + skillMult + "% = " + skill.toFixed(4) + "\n";
    br += "增伤区间（加算） = " + dmgZone + "% → " + dmgMult.toFixed(4) + " [下限-50%]\n";
    br += "易伤区间（乘算） = 系数 " + vulnMult.toFixed(4) + " [上限3.0]";
    if (hornBuff) { br += " (含号角+80%)"; }
    br += "\n";
    br += "最终增伤（乘算） = 系数 " + finalDmgMult.toFixed(4) + " [无上限]\n";
    br += "最终易伤（乘算） = 系数 " + finalVulnMult.toFixed(4) + " [无上限]\n\n";
    br += "单段伤害         = " + Math.round(singleHit) + "\n";
    br += "暴击伤害总和     = " + critDmgPct + "%\n";
    br += "暴击单段         = " + Math.round(critSingle);

    if (formulaBreakdownEl) formulaBreakdownEl.textContent = br;
  } catch (e) {
    console.error("计算错误:", e);
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", calculate);
} else {
  calculate();
}

const RecordManager = {
  storageKey: 'sword_of_convallaria_damage_records',
  records: [],
  
  init() {
    this.loadRecords();
    this.createModal();
    this.bindEvents();
  },
  
  loadRecords() {
    const stored = localStorage.getItem(this.storageKey);
    this.records = stored ? JSON.parse(stored) : [];
  },
  
  saveRecords() {
    localStorage.setItem(this.storageKey, JSON.stringify(this.records));
  },
  
  getCurrentConfig() {
    return {
      atkClass: document.getElementById('atkClass').value,
      atkPanel: document.getElementById('atkPanel').value,
      atkBonusPct: document.getElementById('atkBonusPct').value,
      atkBonusFlat: document.getElementById('atkBonusFlat').value,
      skillMult: document.getElementById('skillMult').value,
      critDmgPct: document.getElementById('critDmgPct').value,
      defClass: document.getElementById('defClass').value,
      defBase: document.getElementById('defBase').value,
      ignoreDefPct: document.getElementById('ignoreDefPct').value,
      defReduceFlat: document.getElementById('defReduceFlat').value,
      defDebuff: document.getElementById('defDebuff').value,
      hornBuff: document.getElementById('hornBuff').checked,
      dmgZone: document.getElementById('dmgZone').value,
      vulnZone: document.getElementById('vulnZone').value,
      finalDmgZone: document.getElementById('finalDmgZone').value,
      finalVulnZone: document.getElementById('finalVulnZone').value,
      singleDmg: document.getElementById('singleDmg').textContent,
      critSingleDmg: document.getElementById('critSingleDmg').textContent
    };
  },
  
  setConfig(config) {
    document.getElementById('atkClass').value = config.atkClass || 'none';
    document.getElementById('atkPanel').value = config.atkPanel || '0';
    document.getElementById('atkBonusPct').value = config.atkBonusPct || '0';
    document.getElementById('atkBonusFlat').value = config.atkBonusFlat || '0';
    document.getElementById('skillMult').value = config.skillMult || '100';
    document.getElementById('critDmgPct').value = config.critDmgPct || '130';
    document.getElementById('defClass').value = config.defClass || 'none';
    document.getElementById('defBase').value = config.defBase || '0';
    document.getElementById('ignoreDefPct').value = config.ignoreDefPct || '0';
    document.getElementById('defReduceFlat').value = config.defReduceFlat || '0';
    document.getElementById('defDebuff').value = config.defDebuff || '0';
    document.getElementById('hornBuff').checked = config.hornBuff || false;
    document.getElementById('dmgZone').value = config.dmgZone || '0';
    document.getElementById('vulnZone').value = config.vulnZone || '0';
    document.getElementById('finalDmgZone').value = config.finalDmgZone || '0';
    document.getElementById('finalVulnZone').value = config.finalVulnZone || '0';
    calculate();
  },
  
  addRecord(name) {
    const config = this.getCurrentConfig();
    const record = {
      id: Date.now(),
      name: name || `配置 ${this.records.length + 1}`,
      time: new Date().toLocaleString('zh-CN'),
      config: config
    };
    this.records.unshift(record);
    this.saveRecords();
    this.showToast('记录已保存');
    return record;
  },
  
  deleteRecord(id) {
    this.records = this.records.filter(r => r.id !== id);
    this.saveRecords();
    this.renderRecordsList();
    this.showToast('记录已删除');
  },
  
  clearAllRecords() {
    if (confirm('确定要清空所有记录吗？此操作不可恢复。')) {
      this.records = [];
      this.saveRecords();
      this.renderRecordsList();
      this.showToast('所有记录已清空');
    }
  },
  
  resetDefault() {
    document.getElementById('atkClass').value = 'none';
    document.getElementById('atkPanel').value = '0';
    document.getElementById('atkBonusPct').value = '0';
    document.getElementById('atkBonusFlat').value = '0';
    document.getElementById('skillMult').value = '100';
    document.getElementById('critDmgPct').value = '130';
    document.getElementById('defClass').value = 'none';
    document.getElementById('defBase').value = '0';
    document.getElementById('ignoreDefPct').value = '0';
    document.getElementById('defReduceFlat').value = '0';
    document.getElementById('defDebuff').value = '0';
    document.getElementById('hornBuff').checked = false;
    document.getElementById('dmgZone').value = '0';
    document.getElementById('vulnZone').value = '0';
    document.getElementById('finalDmgZone').value = '0';
    document.getElementById('finalVulnZone').value = '0';
    calculate();
    this.showToast('已恢复默认设置');
  },
  
  createModal() {
    const modalHTML = `
      <div id="recordsModal" class="modal-overlay">
        <div class="modal-content">
          <div class="modal-header">
            <h2><img src="https://patchwiki.biligame.com/images/llzj/7/79/1cavtuyjuyglrrnee69v7y01hzmex5v.png" class="modal-header-icon" alt="">数据库 (无上限)</h2>
            <button class="modal-close" onclick="RecordManager.closeModal()">×</button>
          </div>
          <div class="modal-body">
            <div id="recordsList"></div>
          </div>
        </div>
      </div>
      
      <div id="nameModal" class="modal-overlay">
        <div class="modal-content" style="max-width: 400px;">
          <div class="modal-header">
            <h2><img src="https://patchwiki.biligame.com/images/llzj/9/98/kx0akko30kul0jemcyfqitclkkm3bsv.png" class="modal-header-icon" alt="">保存记录</h2>
            <button class="modal-close" onclick="RecordManager.closeNameModal()">×</button>
          </div>
          <div class="modal-body">
            <p style="color: #5a4328; margin-bottom: 8px;">为本次记录命名 (最多20字)</p>
            <input type="text" id="recordNameInput" class="name-input" placeholder="配置 1" maxlength="20">
            <div class="modal-actions">
              <button class="modal-btn secondary" onclick="RecordManager.closeNameModal()">取消</button>
              <button class="modal-btn primary" onclick="RecordManager.confirmSave()">确定</button>
            </div>
          </div>
        </div>
      </div>
      
      <div id="viewModal" class="modal-overlay">
        <div class="modal-content table-modal-content">
          <div class="modal-header">
            <h2><img src="https://patchwiki.biligame.com/images/llzj/a/a9/abs45fkpnewex091qqvafa7ynzndejo.png" class="modal-header-icon" alt="">配置详情</h2>
            <button class="modal-close" onclick="RecordManager.closeViewModal()">×</button>
          </div>
          <div class="modal-body">
            <div id="viewContent"></div>
          </div>
        </div>
      </div>
      
      <div id="toast" class="toast"></div>
    `;
    
    document.body.insertAdjacentHTML('beforeend', modalHTML);
  },
  
  bindEvents() {
    const resultsSection = document.querySelector('.results-section');
    const buttonsHTML = `
      <div class="record-buttons">
        <button class="record-btn" onclick="RecordManager.openNameModal()"><img src="https://patchwiki.biligame.com/images/llzj/d/de/4tfw9hhcf4do0mjejj67xr9so5959oe.png" class="btn-icon" alt="">记录结果</button>
        <button class="record-btn secondary" onclick="RecordManager.openModal()"><img src="https://patchwiki.biligame.com/images/llzj/7/79/qa9mb6y1qnbxxrgu6z0xnr02e7nbjye.png" class="btn-icon" alt="">查询记录</button>
        <button class="record-btn danger" onclick="RecordManager.clearAllRecords()"><img src="https://patchwiki.biligame.com/images/llzj/1/15/cp0a46jw2uu8d2tvnym6pki73xl59cf.png" class="btn-icon" alt="">清空记录</button>
        <button class="record-btn reset-default" onclick="RecordManager.resetDefault()"><img src="https://patchwiki.biligame.com/images/llzj/8/81/ob52g0qz2rc73xh87qtxz091uwagm1k.png" class="btn-icon" alt="">重置默认</button>
      </div>
    `;
    resultsSection.insertAdjacentHTML('beforeend', buttonsHTML);
  },
  
  openModal() {
    document.getElementById('recordsModal').classList.add('active');
    this.renderRecordsList();
  },
  
  closeModal() {
    document.getElementById('recordsModal').classList.remove('active');
  },
  
  openNameModal() {
    const defaultName = `配置 ${this.records.length + 1}`;
    document.getElementById('recordNameInput').value = '';
    document.getElementById('recordNameInput').placeholder = defaultName;
    document.getElementById('nameModal').classList.add('active');
    setTimeout(() => document.getElementById('recordNameInput').focus(), 100);
  },
  
  closeNameModal() {
    document.getElementById('nameModal').classList.remove('active');
  },
  
  confirmSave() {
    const input = document.getElementById('recordNameInput');
    const name = input.value.trim() || input.placeholder;
    this.addRecord(name);
    this.closeNameModal();
  },
  
  openViewModal(record) {
    const content = document.getElementById('viewContent');
    const c = record.config;
    const classNames = {
      none: '--', noClass: '无职业', crusher: '粉碎者', 
      defender: '防御者', raider: '突袭者', destroyer: '毁灭者', watcher: '守望者'
    };
    
    const defDebuffVal = parseFloat(c.defDebuff) || 0;
    const hornDefVal = c.hornBuff ? 20 : 0;
    const defReduceFlatRaw = c.defReduceFlat || '0';
    const fixedDefReduce = parseFloat(defReduceFlatRaw) || 0;
    const totalDefReducePercent = defDebuffVal + hornDefVal;
    
    const hasValue = (val, defaultVal = '0') => {
      if (val === undefined || val === null) return false;
      const str = String(val).trim();
      if (str === '' || str === '0' || str === defaultVal) return false;
      return true;
    };
    
    let tableRows = [];
    tableRows.push(`<tr><th>攻方黑字攻击</th><td>${c.atkPanel}</td></tr>`);
    tableRows.push(`<tr><th>攻方职业</th><td>${classNames[c.atkClass] || '--'}</td></tr>`);
    tableRows.push(`<tr><th>守方职业</th><td>${classNames[c.defClass] || '--'}</td></tr>`);
    tableRows.push(`<tr><th>职业克制倍率</th><td>${this.getRestraintText(c.atkClass, c.defClass)}</td></tr>`);
    
    if (hasValue(c.atkBonusPct)) {
      tableRows.push(`<tr><th>百分比攻击加成</th><td>${c.atkBonusPct}%</td></tr>`);
    }
    if (hasValue(c.atkBonusFlat)) {
      tableRows.push(`<tr><th>固定数值加成</th><td>${c.atkBonusFlat}</td></tr>`);
    }
    
    tableRows.push(`<tr><th>技能倍率</th><td>${c.skillMult}%</td></tr>`);
    tableRows.push(`<tr><th>暴击伤害</th><td>${c.critDmgPct}%</td></tr>`);
    
    if (hasValue(c.defBase)) {
      tableRows.push(`<tr><th>守方黑字防御</th><td>${c.defBase}</td></tr>`);
    }
    if (hasValue(c.ignoreDefPct)) {
      tableRows.push(`<tr><th>无视防御</th><td>${c.ignoreDefPct}%</td></tr>`);
    }
    
    if (fixedDefReduce > 0 || totalDefReducePercent > 0) {
      let defReduceDisplay = defReduceFlatRaw !== '0' ? defReduceFlatRaw : '0';
      if (totalDefReducePercent > 0) {
        defReduceDisplay += ` (含减益${totalDefReducePercent}%)`;
      }
      tableRows.push(`<tr><th>固定防御减少</th><td>${defReduceDisplay}</td></tr>`);
    }
    
    if (hasValue(c.dmgZone)) {
      tableRows.push(`<tr><th>增伤区间</th><td>${c.dmgZone}%</td></tr>`);
    }
    if (hasValue(c.vulnZone) || c.hornBuff) {
      tableRows.push(`<tr><th>易伤区间</th><td>${c.vulnZone}% ${c.hornBuff ? '(含号角+80%)' : ''}</td></tr>`);
    }
    if (hasValue(c.finalDmgZone)) {
      tableRows.push(`<tr><th>最终增伤区间</th><td>${c.finalDmgZone}%</td></tr>`);
    }
    if (hasValue(c.finalVulnZone)) {
      tableRows.push(`<tr><th>最终易伤区间</th><td>${c.finalVulnZone}%</td></tr>`);
    }
    
    tableRows.push(`<tr style="background: linear-gradient(135deg, rgba(196,162,101,0.1), rgba(160,120,48,0.1));"><th>预计伤害</th><td style="color: #c0641e; font-weight: bold;">${c.singleDmg}</td></tr>`);
    tableRows.push(`<tr style="background: linear-gradient(135deg, rgba(192,57,43,0.1), rgba(160,40,32,0.1));"><th>预计暴击伤害</th><td style="color: #c0392b; font-weight: bold;">${c.critSingleDmg}</td></tr>`);
    
    content.innerHTML = `
      <div style="text-align: center; margin-bottom: 16px;">
        <div style="font-size: 18px; font-weight: bold; color: #6b4c1e; margin-bottom: 4px;">
          📌 ${record.name}
        </div>
        <div style="font-size: 12px; color: #8a7350;">${record.time}</div>
      </div>
      <table class="config-table" id="configTable">
        ${tableRows.join('')}
      </table>
      <button class="save-image-btn" onclick="RecordManager.saveAsImage()"><img src="https://patchwiki.biligame.com/images/llzj/0/0f/6stciiwkrhn2jpkhrejyrfvvno0a5dc.png" alt="">保存为图片</button>
    `;
    document.getElementById('viewModal').classList.add('active');
  },
  
  closeViewModal() {
    document.getElementById('viewModal').classList.remove('active');
  },
  
  getRestraintText(atk, def) {
    if (atk === 'none' || def === 'none' || def === 'noClass') return '×1.0 (无克制)';
    const restraint = getRestraint(atk, def);
    if (restraint > 1) return `×${restraint} (克制)`;
    if (restraint < 1) return `×${restraint} (被克制)`;
    return '×1.0 (无克制)';
  },
  
  saveAsImage() {
    const table = document.getElementById('configTable');
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    
    const rows = table.querySelectorAll('tr');
    const rowHeight = 42;
    const headerHeight = 100;
    const footerHeight = 50;
    const totalHeight = headerHeight + (rows.length * rowHeight) + footerHeight;
    
    canvas.width = 600;
    canvas.height = Math.max(400, totalHeight);
    
    const gradient = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
    gradient.addColorStop(0, '#fffdf5');
    gradient.addColorStop(1, '#f5f0e0');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    
    ctx.strokeStyle = '#c4a265';
    ctx.lineWidth = 4;
    ctx.strokeRect(10, 10, canvas.width - 20, canvas.height - 20);
    
    ctx.fillStyle = '#6b4c1e';
    ctx.font = 'bold 24px Microsoft YaHei';
    ctx.textAlign = 'center';
    ctx.fillText('铃兰之剑伤害计算器', canvas.width / 2, 50);
    
    const configName = document.querySelector('#viewContent div div').textContent.trim();
    ctx.font = 'bold 20px Microsoft YaHei';
    ctx.fillStyle = '#a07830';
    ctx.fillText(configName.replace('📌 ', ''), canvas.width / 2, 85);
    
    let y = 130;
    
    rows.forEach((row, index) => {
      const th = row.querySelector('th');
      const td = row.querySelector('td');
      
      if (!th || !td) return;
      
      if (index >= rows.length - 2) {
        ctx.fillStyle = index === rows.length - 2 ? 'rgba(196,162,101,0.15)' : 'rgba(192,57,43,0.15)';
        ctx.fillRect(30, y - 25, canvas.width - 60, rowHeight);
      } else if (index % 2 === 0) {
        ctx.fillStyle = 'rgba(196,162,101,0.05)';
        ctx.fillRect(30, y - 25, canvas.width - 60, rowHeight);
      }
      
      ctx.fillStyle = '#5a4328';
      ctx.font = 'bold 14px Microsoft YaHei';
      ctx.textAlign = 'left';
      ctx.fillText(th.textContent, 50, y);
      
      ctx.fillStyle = index >= rows.length - 2 ? (index === rows.length - 2 ? '#c0641e' : '#c0392b') : '#3a2a14';
      ctx.font = index >= rows.length - 2 ? 'bold 16px Microsoft YaHei' : '14px Microsoft YaHei';
      ctx.textAlign = 'right';
      ctx.fillText(td.textContent, canvas.width - 50, y);
      
      if (index < rows.length - 1) {
        ctx.strokeStyle = '#e8e0d0';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(30, y + 10);
        ctx.lineTo(canvas.width - 30, y + 10);
        ctx.stroke();
      }
      
      y += rowHeight;
    });
    
    ctx.fillStyle = '#8a7350';
    ctx.font = '12px Microsoft YaHei';
    ctx.textAlign = 'center';
    ctx.fillText('铃兰之剑BWIKI伤害计算器', canvas.width / 2, canvas.height - 30);
    
    const link = document.createElement('a');
    link.download = `铃兰之剑配置_${new Date().getTime()}.png`;
    link.href = canvas.toDataURL();
    link.click();
    
    this.showToast('图片已保存');
  },
  
  renderRecordsList() {
    const container = document.getElementById('recordsList');
    
    if (this.records.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">📭</div>
          <div>暂无记录</div>
          <div style="font-size: 12px; margin-top: 8px;">点击"记录结果"保存当前配置</div>
        </div>
      `;
      return;
    }
    
    container.innerHTML = `
      <div class="records-grid">
        ${this.records.map(record => {
          let timeDisplay = record.time;
          try {
            const date = new Date(record.time);
            if (!isNaN(date.getTime())) {
              const hours = date.getHours().toString().padStart(2, '0');
              const minutes = date.getMinutes().toString().padStart(2, '0');
              timeDisplay = `${hours}:${minutes}`;
            }
          } catch (e) {}
          
          return `
          <div class="record-card">
            <div class="record-header">
              <span class="record-pin">📌</span>
              <span class="record-name">${record.name}</span>
              <span class="record-time">${timeDisplay}</span>
            </div>
            <div class="record-values">
              <div class="record-value-item">
                <span class="icon">⚔️</span>
                <span class="num">${record.config.singleDmg}</span>
              </div>
              <div class="record-value-item">
                <span class="icon">💥</span>
                <span class="num">${record.config.critSingleDmg}</span>
              </div>
            </div>
            <div class="record-actions">
              <button class="record-action-btn" onclick="RecordManager.viewRecord(${record.id})">🔍 详情</button>
              <button class="record-action-btn" onclick="RecordManager.loadRecord(${record.id})">📥 填入</button>
              <button class="record-action-btn delete" onclick="RecordManager.deleteRecordById(${record.id})">🗑️ 删除</button>
            </div>
          </div>
        `}).join('')}
      </div>
    `;
  },
  
  viewRecord(id) {
    const record = this.records.find(r => r.id === id);
    if (record) this.openViewModal(record);
  },
  
  loadRecord(id) {
    const record = this.records.find(r => r.id === id);
    if (record) {
      this.setConfig(record.config);
      this.closeModal();
      this.showToast('配置已填入计算器');
    }
  },
  
  deleteRecordById(id) {
    if (confirm('确定要删除这条记录吗？')) {
      this.deleteRecord(id);
    }
  },
  
  showToast(message) {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 2500);
  }
};

document.addEventListener('DOMContentLoaded', () => {
  RecordManager.init();
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && document.getElementById('nameModal').classList.contains('active')) {
    RecordManager.confirmSave();
  }
});
