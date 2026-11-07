/* Choice-skill branches and decoded client mechanics, shown on skill pages and
 * in a searchable rule browser.
 *
 * Data comes from scripts/extract_battle_rules.py:
 *   WIKI_CHOICE_SKILLS  - parent skill id -> child skills (+ page links)
 *   WIKI_SKILL_MECHANICS - skill id -> decoded speciality chain and rules
 *   WIKI_COMBAT_DATA    - constants, restraint matrix and formula sources
 */
'use strict';
window.WikiMechanics = (() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g,
    c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

  const choices = () => window.WIKI_CHOICE_SKILLS || null;
  const mechanics = () => window.WIKI_SKILL_MECHANICS || null;

  /** Client skill pages use 100000000 + skill id; online pages match by name. */
  function skillIdOf(page, doc) {
    const source = doc?.clientSource;
    if (source?.rowId && source.table === 'skill') return Number(source.rowId);
    if (doc?.choiceSkillId) return Number(doc.choiceSkillId);
    if (page?.id >= 100000000 && page.type === 'skill') return page.id - 100000000;
    const groups = choices()?.groups || [];
    const hit = groups.find(g => g.name === page?.name);
    return hit ? hit.id : null;
  }

  function choiceGroup(page, doc) {
    const data = choices();
    if (!data) return null;
    const sid = skillIdOf(page, doc);
    // ``groups`` carries the full skill text; ``branches`` carries page links
    // and previews. Merge both so a card always shows the real description.
    const source = data.groups?.find(g => g.id === sid || g.name === page?.name);
    if (!source) return null;
    const branch = data.branches?.[String(source.id)];
    return { ...source, pageId: branch?.pageId,
      children: (source.children || []).map((child, index) => ({
        ...child,
        pageId: branch?.children?.[index]?.pageId || child.pageId,
        preview: branch?.children?.[index]?.preview || data.previews?.[String(child.id)] || {},
      })) };
  }

  function choiceBlock(page, doc) {
    const group = choiceGroup(page, doc);
    if (!group || !group.children?.length) return '';
    const data = choices();
    const allMechanics = mechanics()?.skills || {};
    const cards = group.children.map((child, index) => {
      const target = child.pageId;
      const preview = child.preview || data?.previews?.[String(child.id)] || {};
      const desc = child.desc || child.keywordDesc || '客户端未提供该分支的详细说明。';
      const facts = [
        child.cost != null ? `消耗 ${esc(child.cost)}` : '',
        child.cooldown != null ? `冷却 ${esc(child.cooldown)}` : '',
        Array.isArray(child.range) && child.range.some(Boolean) ? `射程 ${esc(child.range[0])}~${esc(child.range[1])}` : '',
        preview.facts?.['类别'] ? `类别 ${esc(preview.facts['类别'])}` : '',
      ].filter(Boolean).join(' · ');
      const rules = (allMechanics[String(child.id)]?.rules || []).slice(0, 6);
      const title = `<div class="choice-card-head">
        ${preview.iconFile ? `<img class="choice-card-icon" src="${esc(preview.iconFile)}" alt="" width="48" height="48">` : ''}
        <div class="choice-card-title"><span class="choice-index">${index + 1}</span>
          <strong>${esc(child.name)}</strong>
          <small>${esc(preview.rangeLabel || '技能分支')}</small></div>
        ${target ? '<span class="choice-arrow" aria-hidden="true">↗</span>' : ''}</div>`;
      const head = target
        ? `<a class="choice-card-link" href="#/page/${target}" aria-label="查看技能词条：${esc(child.name)}">${title}</a>`
        : `<div class="choice-card-link">${title}</div>`;
      const rangeFigure = preview.rangeImage
        ? `<figure class="choice-range"><figcaption>作用范围 · ${esc(preview.rangeLabel || '')}</figcaption>
             <img src="${esc(preview.rangeImage)}" alt="技能作用范围 ${esc(preview.rangeLabel || '')}" width="160" height="160"></figure>`
        : `<p class="choice-range-text">作用范围：${esc(preview.rangeLabel || '见技能说明')}</p>`;
      const previewBody = `<div class="choice-preview-body">
          <div class="choice-preview-main">
            <h4>技能效果原文</h4><p class="choice-desc-full">${esc(desc)}</p>
            ${rules.length ? `<h4>客户端机制</h4><ul class="mechanics-rules choice-rules">${rules.map(r => `<li>${esc(r)}</li>`).join('')}</ul>` : ''}
            <p class="small-text muted">${esc(preview.rangeText || '')}</p>
          </div>${rangeFigure}</div>`;
      return `<article class="choice-card">${head}
        <p class="choice-desc">${esc(desc.slice(0, 132))}${desc.length > 132 ? '…' : ''}</p>
        ${facts ? `<p class="choice-facts">${facts}</p>` : ''}
        <details class="choice-preview"><summary>预览技能效果与作用范围</summary>${previewBody}</details>
        ${target ? `<a class="choice-full" href="#/page/${target}">打开完整技能档案 ↗</a>` : ''}</article>`;
    }).join('');
    return `<section class="content-card choice-panel"><h2>可选择的技能 <span class="heading-count">${group.children.length}</span></h2>
      <p class="small-text muted">这是一个抉择技能，使用时只能选其中一项。点击卡片标题或底部链接进入该技能的完整词条；展开下方预览可直接看到效果原文、客户端机制与作用范围图。</p>
      <div class="choice-grid">${cards}</div></section>`;
  }

  function parentBlock(page, doc) {
    const parent = doc?.choiceParent;
    if (!parent) return '';
    const link = parent.pageId ? `<a class="button secondary small" href="#/page/${parent.pageId}">返回「${esc(parent.name)}」 ↗</a>` : '';
    return `<div class="source-notice choice-backlink">${esc(page?.name || '')}是「${esc(parent.name)}」的可选择分支之一。${link}</div>`;
  }

  function mechanicBlock(page, doc) {
    const data = mechanics();
    if (!data) return '';
    const sid = skillIdOf(page, doc);
    // A 抉择 branch (or a season variant) may share its name with the
    // canonical entry; fall back to the name so its skill page still shows
    // the authoritative rules instead of an empty panel.
    let item = sid != null ? data.skills?.[String(sid)] : null;
    let canonicalId = sid;
    if (!item && page?.name) {
        const hit = Object.entries(data.skills || {}).find(([, s]) => s.name === page.name);
        if (hit) {
          canonicalId = hit[0];
          item = hit[1];
        }
    }
    if (!item) return '';
    const details = item.details || (item.rules || []).map(summary => ({ summary, detail: '', original: '' }));
    if (!details.length) return '';
    const kindLabel = {target: '目标', range: '射程', aoe: '范围', gather: '聚拢', buff: '状态',
                       choice: '抉择', knockback: '击退', other: '机制'};
    const blocks = details.map(rule => `<article class="mechanics-detail">
        <h3><span class="mech-kind mech-kind-${esc(rule.kind || 'other')}">${esc(kindLabel[rule.kind] || '机制')}</span>${esc(rule.summary)}</h3>
        ${rule.detail ? `<p class="mech-explain">${esc(rule.detail)}</p>` : ''}
        ${rule.original ? `<blockquote class="mech-original"><span>配置表原文</span>${esc(rule.original)}</blockquote>` : ''}
        ${rule.source ? `<p class="mech-source">来源 ${esc(rule.source)}</p>` : ''}
      </article>`).join('');
    const chain = (item.chain || []).map(step => {
      const params = (step.params || []).filter(p => p.value || p.display).map(p =>
        `<span class="mech-param">${esc(p.name || '参数')}：<strong>${esc(p.display || p.value)}</strong></span>`).join('');
      return `<tr><td><span class="mech-type">${esc(step.name || step.type || step.typeId)}</span>
        <small>${esc(step.editorName || '')}</small></td><td>${params || '<span class="muted">—</span>'}</td>
        <td class="mech-source">${esc(step.source || '')}</td></tr>`;
    }).join('');
    const authority = item.authority
      ? `<p class="mech-authority"><span class="mech-authority-badge mech-confidence-${esc(item.confidence || 'inferred')}">权威词条</span>
          ${esc(item.authority)}${item.variantCount ? ` · 另有 ${item.variantCount} 个同名变体` : ''}</p>` : '';
    return `<section class="content-card mechanics-panel"><h2>客户端机制解析 <span class="heading-count">${details.length}</span></h2>
      ${authority}
      <p class="small-text muted">每条规则先给结论，再解释客户端实际如何结算，最后附上未改动的配置表原文与行号。规则由技能特效链（speciality → speciality_type / aoe_param / buff / range_select）反解。</p>
      <div class="mechanics-detail-list">${blocks}</div>
      <details class="mechanics-chain"><summary>查看技能原文与完整特效链</summary>
        <blockquote class="mech-original"><span>技能描述原文 · skill#${esc(canonicalId ?? '—')}</span>${esc(item.original?.skillDesc || item.desc || '')}</blockquote>
        <div class="table-scroll"><table class="data-table"><thead><tr><th>机制</th><th>参数</th><th>配置表来源</th></tr></thead>
        <tbody>${chain}</tbody></table></div></details></section>`;
  }

  /** Standalone rule browser at #/mechanics.
   * The toolbar is rendered ONCE and only the result list is repainted on
   * input: rebuilding the input mid-IME-composition is what made Chinese
   * typing impossible. Composition events are honoured explicitly too.
   */
  function render(root, helpers = {}) {
    const data = mechanics();
    const combat = window.WIKI_COMBAT_DATA;
    if (!data) {
      root.innerHTML = `<div class="page-intro"><div><div class="eyebrow">CLIENT RULES</div><h1>机制规则</h1>
        <p>还没有机制数据，请在「本地更新」里完成一次更新。</p></div></div>`;
      return;
    }
    const all = Object.entries(data.skills || {});
    const typeNames = [...new Set(all.flatMap(([, s]) => (s.details || []).map(d => d.kind).filter(Boolean)))].sort();
    const kindLabel = {target: '目标', range: '射程', aoe: '范围', gather: '聚拢', buff: '状态',
                       choice: '抉择', knockback: '击退', other: '机制'};
    let query = '', kind = '', composing = false;

    const norm = value => String(value || '').toLowerCase().replace(/\s+/g, '');
    const pinyinHit = (s, q) => {
      // Only pure latin/digit queries go through pinyin; exact/full/initials
      // matching mirrors semantic-ui.js pinyinScore.
      if (!/^[a-z0-9]+$/.test(q)) return false;
      const full = norm(s.py), initials = norm(s.ini);
      return [full, initials].some(text => text === q || text.startsWith(q) || text.includes(q));
    };
    const rows = () => all.filter(([, s]) => {
      if (kind && !(s.details || []).some(d => d.kind === kind)) return false;
      if (!query) return true;
      // `details[].detail` is a shared explanatory template repeated on every
      // skill (it mentions 聚拢/击退/范围 all over). Including it made every
      // common term match all 1,213 rows, so search only discriminating text:
      // name, description, decoded rules, per-skill summaries and raw config.
      const hay = (s.name + ' ' + (s.desc || '') + ' ' + (s.rules || []).join(' ') + ' '
                   + (s.details || []).map(d => (d.summary || '') + ' ' + (d.original || '')).join(' ')).toLowerCase();
      return hay.includes(query) || pinyinHit(s, query);
    });

    const constants = Object.entries(combat?.constants || {}).map(([key, c]) =>
      `<tr><td><strong>${esc(c.label)}</strong><small>${esc(key)}</small></td><td>${esc(c.value)}</td>
       <td>${esc(c.note || '')}</td><td class="mech-source">${esc(c.source)}</td></tr>`).join('');
    const restraints = (combat?.restraints || []).map(r =>
      `<tr><td>${esc(r.fromName)}</td><td>${esc(r.toName)}</td><td>${esc(r.percent)}%</td>
       <td class="mech-source">${esc(r.source)}</td></tr>`).join('');

    const listMarkup = hits => {
      const shown = hits.slice(0, 120);
      return shown.map(([sid, s]) => {
        const tags = [...new Set((s.chain || []).map(c => c.name).filter(Boolean))].slice(0, 4);
        const keyRules = (s.rules || []).filter(r => /聚拢|击退|传送|可选择|范围判定/.test(r));
        const rules = (keyRules.length ? keyRules : (s.rules || [])).slice(0, 3)
          .map(r => `<li>${esc(r)}</li>`).join('');
        const detail = (s.details || []).find(d => /聚拢|击退|范围判定/.test(d.summary)) || (s.details || [])[0];
        const authority = s.authority
          ? `<p class="mech-authority"><span class="mech-authority-badge mech-confidence-${esc(s.confidence || 'inferred')}">权威词条</span>
               ${esc(s.authority)}${s.variantCount ? ` · 另有 ${s.variantCount} 个同名变体` : ''}</p>` : '';
        const variants = (s.variants || []).length
          ? `<details class="mech-variants"><summary>查看 ${s.variants.length} 个同名变体（活动 / 强化 / 分段版本）</summary>
               <ul>${s.variants.map(v => `<li><code>#${esc(v.id)}</code> ${esc(v.editorName || v.desc || '无描述')}
                 ${v.range.some(Boolean) ? `<small>射程 ${esc(v.range[0])}~${esc(v.range[1])}</small>` : ''}</li>`).join('')}</ul>
               <p class="small-text muted">同名变体不是独立词条：客户端为不同活动、星级或二段施法各存一行配置，机制解析只采用上方标注的权威 id。</p></details>` : '';
        return `<article class="content-card mechanics-entry"><h2>${esc(s.name)} <small>技能 ${esc(sid)}</small></h2>
          ${authority}
          <div class="tag-list">${tags.map(t => `<span class="mech-tag">${esc(t)}</span>`).join('')}</div>
          <ul class="mechanics-rules">${rules}</ul>
          ${detail?.detail ? `<p class="mech-explain">${esc(detail.detail.slice(0, 260))}${detail.detail.length > 260 ? '…' : ''}</p>` : ''}
          ${s.original?.skillDesc ? `<blockquote class="mech-original"><span>技能描述原文</span>${esc(s.original.skillDesc.slice(0, 200))}</blockquote>` : ''}
          ${variants}
          <a class="button secondary small" href="#/page/${100000000 + Number(sid)}">查看技能页 ↗</a></article>`;
      }).join('') || '<p class="muted">没有匹配的规则，换个关键词试试。</p>';
    };

    root.innerHTML = `<div class="page-intro"><div><div class="eyebrow">CLIENT RULES</div><h1>机制规则</h1>
        <p>从客户端配置表反解的技能机制：范围形状、聚拢/传送、击退、状态施加与抉择分支。数值下方标明来源表与行号。</p></div></div>
      <div class="content-card mechanics-toolbar">
        <label class="tool-field"><span>搜索技能 / 规则</span>
          <input id="mechanics-query" type="search" placeholder="技能名 / 机制 / 拼音 / 首字母，例如：击退 / 菱形 / maishachongfeng / mscf" autocomplete="off" aria-label="搜索机制规则"></label>
          <p class="small-text muted mechanics-hint">可搜技能名、机制词（击退 / 传送 / 燃烧）、客户端字段原文，也支持全拼与拼音首字母；结果按相关度显示。</p>
        <label class="tool-field"><span>机制类型</span><select id="mechanics-kind"><option value="">全部</option>
          ${typeNames.map(n => `<option value="${esc(n)}">${esc(kindLabel[n] || n)}</option>`).join('')}</select></label>
        <p class="small-text muted" id="mechanics-count"></p>
      </div>
      <div class="mechanics-list" id="mechanics-list"></div>
      <details class="content-card tool-help"><summary>伤害与面板公式的数值来源</summary><div class="rich-text">
        ${(combat?.formulas || []).map(f => `<h3>${esc(f.title)}</h3><p><code>${esc(f.expr)}</code></p>
          <p>${esc(f.source)}</p><ol>${(f.steps || []).map(s => `<li>${esc(s)}</li>`).join('')}</ol>`).join('')}
        <h3>战斗常量（const_param）</h3><div class="table-scroll"><table class="data-table"><thead><tr><th>名称</th><th>值</th><th>说明</th><th>来源</th></tr></thead><tbody>${constants}</tbody></table></div>
        <h3>职业克制矩阵（profession_restrain）</h3><div class="table-scroll"><table class="data-table"><thead><tr><th>攻击方</th><th>防守方</th><th>系数</th><th>来源</th></tr></thead><tbody>${restraints}</tbody></table></div>
        <h3>参与公式的配置表</h3><ul>${(combat?.references || []).map(r => `<li><code>${esc(r.table)}</code> — ${esc(r.provides)}（${esc(r.bundle)}）</li>`).join('')}</ul>
      </div></details>
      <div class="source-footer"><span>全部取自本地游戏客户端配置表 · 完全离线</span><a href="#/tools/panel">打开局外面板计算器 →</a></div>`;

    const input = root.querySelector('#mechanics-query');
    const select = root.querySelector('#mechanics-kind');
    const list = root.querySelector('#mechanics-list');
    const count = root.querySelector('#mechanics-count');

    function refresh() {
      const hits = rows();
      list.innerHTML = listMarkup(hits);
      count.textContent = `共 ${all.length.toLocaleString('zh-CN')} 个技能 · 当前匹配 ${hits.length.toLocaleString('zh-CN')} 个`
        + (hits.length > 120 ? '（仅显示前 120 个）' : '')
        + (query && /^[a-z0-9]+$/.test(query) ? ' · 已包含拼音首字母匹配' : '');
      select.value = kind;
    }
    input.addEventListener('compositionstart', () => { composing = true; });
    input.addEventListener('compositionend', () => {
      composing = false;
      query = input.value.trim().toLowerCase();
      refresh();
    });
    input.addEventListener('input', e => {
      // Ignore the intermediate latin keystrokes of an IME composition; a
      // repaint here would cancel the composition and break Chinese input.
      if (composing || e.isComposing) return;
      query = input.value.trim().toLowerCase();
      refresh();
    });
    select.addEventListener('change', e => { kind = e.target.value; refresh(); });
    refresh();
  }

  return { choiceBlock, parentBlock, mechanicBlock, render, skillIdOf, choiceGroup };
})();
