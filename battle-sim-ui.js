/* Offline auto-battle simulator — UI.
 *
 * Route: #/tools/battle. Data (data/battle-sim.js + data/world-data.js +
 * data/battle-mech.js + data/match-cup.js) is loaded on demand by the router.
 * The engine lives in battle-sim-core.js; this
 * file only handles setup, board rendering, step playback and log export.
 * Playback follows the reference timeline tool: a cursor over the list of
 * actions, first / prev / play / next / last, an interval selector and a
 * scrubber; the board always shows the state AFTER the selected action.
 */
'use strict';
window.WikiBattle = (() => {
  let cleanup = () => {};
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const fmt = v => Number(v || 0).toLocaleString('zh-CN');
  const CELL = 32;
  const MODES = {left: '技能轴 · 左侧', right: '技能轴 · 右侧', basic: '仅普攻与初始技能'};
  const SIDE = {A: '我方', B: '敌方'};

  function render(root, h = {}) {
    cleanup();
    const D = window.WIKI_BATTLE_SIM, W = window.WIKI_WORLD_DATA, S = window.WikiBattleSim;
    const MECH = window.WIKI_BATTLE_MECH || null;
    const buffName = id => MECH?.buffs?.[id]?.n || `状态 ${id}`;
    const weatherList = Object.entries(MECH?.weather || {}).filter(([, w]) => w.aura).map(([id, w]) => ({id: Number(id), ...w}));
    const intro = (h.intro || ((a, b, c) => `<div class="page-intro"><div><div class="eyebrow">${a}</div><h1>${b}</h1><p>${c}</p></div></div>`));
    const back = '<a href="#/tools" class="page-back">← 返回离线工具</a>';
    if (!D || !W || !S) {
      root.innerHTML = back + intro('AUTO BATTLE', '自动对局模拟', '还没有对局数据。请在「本地更新」里完成一次更新，或运行 <code>python -X utf8 scripts/extract_battle_sim.py</code>。');
      return;
    }
    const read = h.read || ((k, d) => { try { return JSON.parse(localStorage.getItem('socwiki.' + k)) ?? d; } catch { return d; } });
    const persist = h.persist || ((k, v) => { try { localStorage.setItem('socwiki.' + k, JSON.stringify(v)); } catch { /* quota */ } });
    const roster = D.roster || [];
    const byKey = new Map(roster.map(r => [r.key, r]));
    const fieldTypes = new Map((W.mapMeta?.fieldTypes || []).map(f => [f.id, f]));
    const walkable = (x, y, fallbackT) => {
      if (result?.grid?.at) {
        const c = result.grid.at(x, y);
        if (c) return !!c.walk;
      }
      const info = (D.terrain || {})[String(fallbackT)];
      const cost = Number(info?.cost ?? 10);
      return !info?.pit && cost > 0 && cost < 1000;
    };
    const maps = (W.maps || []).filter(m => (m.cells || []).length >= 40)
      .map(m => ({id: m.id, label: `#${m.id} ${(m.stages || [])[0] || m.name}`, cells: m.cells.length,
                  size: `${m.width}×${m.height}`, search: [(m.stages || []).join(' '), m.name, m.scene, m.id].join(' ').toLowerCase(), raw: m}));
    const mapById = new Map(maps.map(m => [String(m.id), m]));

    // Deterministic defaults so the first visit immediately shows a battle.
    const defaultMap = (maps.find(m => m.raw.stages?.length && m.cells >= 120 && m.cells <= 320) || maps[0])?.id;
    const shuffle = (list, seed) => { const r = S.rng(seed); const a = list.slice(); for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(r() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
    const strong = roster.filter(r => (r.rarity || 0) >= 3).map(r => r.key);
    const pool = shuffle(strong.length >= 8 ? strong : roster.map(r => r.key), 20261107);
    const saved = read('battle.setup', null);
    const setup = Object.assign({mapId: defaultMap, A: pool.slice(0, 4), B: pool.slice(4, 8), mode: 'left',
                                 seed: 20261107, maxRounds: 20, interval: 800, heights: false,
                                 view: '2d', yaw: 45, tilt: 54, zoom: 1, cupId: 0,
                                 weather: 0, cupEnvId: 0, cupEnvOn: true,
                                 coords: true, panelUid: '', spawns: {}, eliteComp: false,
                                 alertRange: true,
                                 skillPriority: {personality: 3, carried: 2, basic: 1,
                                                 tierStep: 60, slotStep: 14, instantBonus: 420}}, saved || {});
    setup.skillPriority = Object.assign({personality: 3, carried: 2, basic: 1,
                                        tierStep: 60, slotStep: 14, instantBonus: 420}, setup.skillPriority || {});
    if (![400, 800, 1200, 2000].includes(Number(setup.interval))) setup.interval = 800;
    // A slot is either a roster key (string) or a full custom fighter object
    // (from the editor or a 乐土群星杯 preset) — keep both kinds.
    const validSlot = s => (typeof s === 'string' && byKey.has(s)) ||
      (s && typeof s === 'object' && s.stats && s.stats.hp > 0);
    setup.A = (setup.A || []).filter(validSlot);
    setup.B = (setup.B || []).filter(validSlot);
    if (!mapById.has(String(setup.mapId))) setup.mapId = defaultMap;
    const CUP = window.WIKI_MATCH_CUP || null;
    // Read lazily: data/client-mechanisms.js is loaded on demand by WikiData.
    const substrate = () => window.WIKI_CLIENT_MECHANISMS || null;
    const cupTeamById = new Map((CUP?.teams || []).map(x => [x.id, x]));

    let result = null, cursor = 0, timer = null, mapQuery = '', camFrame = 0;
    const $ = sel => root.querySelector(sel);

    root.innerHTML = `${back}${intro('AUTO BATTLE', '自动对局模拟',
      '在客户端战斗地图上布阵，双方按客户端战斗规则逐回合行动：技能、被动、反应、光环、状态、天气与地形效果都从客户端配置表逐条结算。可以逐步回放每一次行动与触发的效果，并导出完整战斗日志。')}
      <div class="bsim-layout">
        <aside class="content-card bsim-setup" aria-label="对局设置">
          <div class="bsim-setup-quick">
            <h2>对局设置</h2>
            <p class="small-text muted" id="bsim-setup-summary"></p>
            <button type="button" class="button bsim-run" data-run>开始模拟</button>
            <nav class="bsim-fold-nav" aria-label="设置分组">
              <button type="button" class="text-link" data-fold-go="bsim-fold-setup">① 布阵</button>
              <button type="button" class="text-link" data-fold-go="bsim-fold-options">② 规则</button>
              <button type="button" class="text-link" data-fold-go="bsim-batch">③ 批量</button>
              <button type="button" class="text-link" data-fold-go="bsim-advanced">④ 高级</button>
              <button type="button" class="text-link" data-fold-go="bsim-fold-cup">⑤ 赛事</button>
            </nav>
          </div>
          <details class="bsim-fold" id="bsim-fold-setup" open><summary><i class="bsim-fold-idx">①</i>布阵与地图
            <small>选地图 · 编我方 / 敌方阵容</small></summary>
          <label class="tool-field"><span>地图</span><input type="search" id="bsim-map-q" placeholder="搜索名称 / 场景 / id" autocomplete="off"></label>
          <select id="bsim-map" class="bsim-map-select" size="3" aria-label="选择地图"></select>
          <p class="small-text muted" id="bsim-map-meta"></p>
          ${['A', 'B'].map(side => `<div class="bsim-team" data-team="${side}">
            <div class="bsim-team-head"><strong class="bsim-side-${side}">${SIDE[side]}</strong><small id="bsim-count-${side}"></small>
              <span><button type="button" class="text-link" data-random="${side}">随机</button> · <button type="button" class="text-link" data-clear="${side}">清空</button></span></div>
            <div class="bsim-chips" id="bsim-chips-${side}"></div>
            <div class="bsim-add"><input type="search" list="bsim-roster" id="bsim-add-${side}" placeholder="添加角色（最多 8 名）" autocomplete="off">
              <button type="button" class="button secondary small" data-add="${side}">添加</button>
              <button type="button" class="button secondary small" data-new="${side}" title="从零创建或修改属性与技能">自定义</button></div>
          </div>`).join('')}
          <datalist id="bsim-roster">${roster.map(r => `<option value="${esc(r.name)}">${esc(r.profName)}</option>`).join('')}</datalist>
          </details>
          <details class="bsim-fold" id="bsim-fold-options" open><summary><i class="bsim-fold-idx">②</i>对局规则
            <small>技能配置 · 回合 · 种子 · 天气</small></summary>
          <div class="bsim-options">
            <label class="tool-field"><span>技能配置</span><select id="bsim-mode">${Object.entries(MODES).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select></label>
            <label class="tool-field"><span>回合上限</span><input type="number" id="bsim-rounds" min="1" max="60"></label>
            <label class="tool-field"><span>随机种子</span><span class="bsim-seed"><input type="number" id="bsim-seed"><button type="button" class="button secondary small" data-reseed title="换一个种子">换</button></span></label>
            <label class="tool-field"><span>天气</span><select id="bsim-weather"><option value="0">无</option>${weatherList.map(w =>
              `<option value="${w.id}" title="${esc(w.desc)}">${esc(w.name)}</option>`).join('')}</select></label>
          </div>
          </details>
          <details class="bsim-fold" id="bsim-batch" open><summary><i class="bsim-fold-idx">③</i>批量模拟 · 胜率统计
            <small>同一场对局换随机种子重跑</small></summary>
          <div class="bsim-batch-row">
            <label class="tool-field"><span>模拟场数</span><input type="number" id="bsim-batch-n" min="2" max="200" value="20"></label>
            <button type="button" class="button secondary small" data-batch-run>开始批量模拟</button>
          </div>
          <p class="small-text muted">只用当前地图 / 阵容 / 选项，逐场更换随机种子；不改动上方设置。点表格里的「观看」把该种子载入回放。</p>
          <div class="bsim-batch-filter" role="group" aria-label="筛选结果">
            <button type="button" class="button secondary small" data-batch-filter="all">全部</button>
            <button type="button" class="button secondary small" data-batch-filter="A">我方胜</button>
            <button type="button" class="button secondary small" data-batch-filter="B">敌方胜</button>
            <button type="button" class="button secondary small" data-batch-filter="draw">平局</button>
          </div>
          <div id="bsim-batch-result" class="bsim-batch-result"></div>
          </details>
          <details class="bsim-fold" id="bsim-advanced"><summary><i class="bsim-fold-idx">④</i>高级设置
            <small>AI 技能使用优先级</small></summary>
          <details class="bsim-skill-prio" id="bsim-skill-prio"><summary>技能使用优先级
            <small>个性 / 普攻 / 携带技能分开</small></summary>
            <div class="bsim-prio-grid">
              ${[['personality', '个性技能'], ['basic', '普攻'], ['carried', '正常携带技能']].map(([k, label]) =>
                `<label class="tool-field"><span>${label}</span><input type="number" data-prio="${k}" min="0" max="9" step="1" value="${Number(setup.skillPriority[k])}"></label>`).join('')}
            </div>
            <div class="bsim-prio-grid">
              <label class="tool-field"><span>组间每档权重</span><input type="number" data-prio="tierStep" min="0" max="400" value="${Number(setup.skillPriority.tierStep)}"></label>
              <label class="tool-field"><span>每个槽位权重</span><input type="number" data-prio="slotStep" min="0" max="200" value="${Number(setup.skillPriority.slotStep)}"></label>
              <label class="tool-field"><span>[瞬发] 优先加权</span><input type="number" data-prio="instantBonus" min="0" max="4000" value="${Number(setup.skillPriority.instantBonus)}"></label>
            </div>
            <button type="button" class="button secondary small" data-prio-reset>恢复默认优先级</button>
            <details class="bsim-help"><summary>优先级规则说明</summary><p class="small-text muted">数值越大越优先（对应客户端 skill_list_tag 的分组优先级，普攻是最低的 NORMAL_ATTACK 标签）。同组的携带技能按<b>技能放置顺序</b>打破同分：点角色右侧的 ✎ 打开编辑器，用 ↑ / ↓ 调整技能槽顺序。[瞬发] 技能施放后不结束行动，可用剩余移动力继续走 / 继续放技能；只有技能自身带 FORCE_STOP 或客户端「强制警戒（可打断技能）」才打断行动。远程技能按客户端射程外环选位，走到极限距离施放。</p></details>
          </details>
          </details>
          ${MECH ? '' : '<p class="small-text bsim-error">没有战斗机制数据（data/battle-mech.js），只能按基础伤害公式模拟。请运行 <code>python -X utf8 scripts/extract_battle_mechanics.py</code>。</p>'}
          <details class="bsim-fold bsim-cup" id="bsim-fold-cup" ${setup.cupId ? 'open' : ''}><summary><i class="bsim-fold-idx">⑤</i>乐土群星杯 · 赛事数据
            <small>载入对阵 · 推演赛果 · 站位编辑 · 选手资料</small></summary>
            ${CUP ? `<div class="bsim-cup-body">
              <label class="tool-field"><span>活动期次</span><select id="bsim-cup-act">${CUP.activities.map(a =>
                `<option value="${a.id}">${esc(a.name)}（${a.teamIds.length} 队 · ${a.unitLevel} 级）</option>`).join('')}</select></label>
              <label class="tool-field"><span>赛程</span><select id="bsim-cup-sched"></select></label>
              <div class="bsim-cup-info" id="bsim-cup-info"></div>
              ${CUP.environment ? `<div class="bsim-cup-env small-text">
                <b>默认对战环境</b>：地图「${esc(CUP.environment.mapName)}」· 天气「${esc(CUP.environment.weatherName)}」
                <details><summary>推定依据</summary><ul>${CUP.environment.evidence.map(e => `<li>${esc(e)}</li>`).join('')}</ul>
                <p class="muted">${esc(CUP.environment.caveat)}</p></details></div>` : ''}
              <label class="tool-check"><input type="checkbox" id="bsim-cup-env" ${setup.cupEnvOn ? 'checked' : ''}><span>应用本场赛事增益与选手状态</span></label>
              ${CUP.eliteCompensation ? `<details class="bsim-elite-note"><summary>精英属性补回 · 来源与处理
                  <small>默认不启用</small></summary>
                <div class="rich-text small-text">
                  <p><b>加成内容</b>：${CUP.eliteCompensation.effects.map(esc).join('；')}。</p>
                  <p><b>来源链路</b>：<code>${esc(CUP.eliteCompensation.source)}</code>，挂在 ${CUP.eliteCompensation.fighters} 名选手的个性第 2 技能组上。</p>
                  <p><b>对照</b>：${esc(CUP.eliteCompensation.alternative)}。</p>
                  <p><b>为何不生效</b>：${esc(CUP.eliteCompensation.eliteBuff)} 才是客户端的精英属性来源；
                    ${esc(CUP.eliteCompensation.evidence)}，因此赛事对局里这些选手没有这项修正。</p>
                  <label class="tool-check"><input type="checkbox" id="bsim-elite-comp" ${setup.eliteComp ? 'checked' : ''}>
                    <span>仍要启用精英属性补回（用于对照，非客户端实际表现）</span></label>
                </div></details>` : ''}
              ${CUP.arenaMaps?.length ? `<label class="tool-field"><span>赛事地图</span><select id="bsim-cup-map">
                ${CUP.arenaMaps.map(m => `<option value="${m.id}">${esc(m.name)} · ${m.width}×${m.height} · ${m.cells} 格</option>`).join('')}
              </select></label>` : ''}
              <details class="bsim-spawn-edit" id="bsim-spawn-edit"><summary>本场地图与初始站位
                <small>客户端无逐场地图 / 站位，可直接编辑</small></summary>
                <div id="bsim-spawn-body"></div></details>
              <div class="bsim-cup-actions">
                <button type="button" class="button secondary small" data-cup-load="both">载入本场对阵</button>
                <button type="button" class="button secondary small" data-cup-load="A">只载入我方</button>
                <button type="button" class="button secondary small" data-cup-load="B">只载入敌方</button>
                <button type="button" class="button secondary small" data-cup-predict="one">推演本场胜负 / 回合</button>
                <button type="button" class="button secondary small" data-cup-predict="all">推演全部赛程</button>
              </div>
              <div class="bsim-cup-result" id="bsim-cup-result"></div>
              <details class="bsim-cup-roster"><summary>双方阵容 · 选手属性与全量技能</summary>
                <div id="bsim-cup-roster"></div></details>
              <p class="small-text muted">${CUP.schedules.length} 场赛程 · ${CUP.teams.length} 支队伍 · ${CUP.modes.length} 个赛制 · ${CUP.bets.length} 组赔率。
                选手属性取自客户端 60 级成长表，与图鉴口径不同，建议赛事队伍互相对阵。</p>
              <details><summary>赛事说明与数据边界</summary><div class="rich-text small-text">
                ${CUP.rules.map(r => `<p>${esc(r)}</p>`).join('')}
                <ul>${CUP.notes.map(n => `<li>${esc(n)}</li>`).join('')}</ul>
                <p class="muted">来源：${CUP.sources.map(esc).join('；')}。</p>
              </div></details>
            </div>` : '<p class="small-text muted">没有赛事数据，请运行 <code>python -X utf8 scripts/extract_match_cup.py</code> 并在「本地更新」里完成一次更新。</p>'}
          </details>
          <details class="bsim-help"><summary>对局说明</summary>
            <p class="small-text muted">同一张地图、阵容与种子总会得到同一场对局，方便对比调整。编队、站位、AI 优先级与赛事数据都只影响下一次「开始模拟」。</p></details>
        </aside>
        <section class="bsim-stage" aria-label="对局回放">
          <div class="content-card bsim-board-card">
            <div class="bsim-board-head"><strong id="bsim-title">—</strong>
              <span class="bsim-board-tools">
                <label class="tool-check"><input type="checkbox" id="bsim-heights"><span>显示高度</span></label>
                <label class="tool-check"><input type="checkbox" id="bsim-coords"><span>显示坐标</span></label>
                <label class="tool-check" title="在棋盘上用虚线画出每个单位的警戒范围"><input type="checkbox" id="bsim-alert-range"><span>警戒范围</span></label>
                <button type="button" class="button secondary small" data-bsim-view="2d" aria-pressed="true">2D</button>
                <button type="button" class="button secondary small" data-bsim-view="3d" aria-pressed="false">3D</button>
                <button type="button" class="button secondary small" data-cam-reset title="恢复默认视角">⟲</button>
              </span></div>
            <p class="bsim-cam-hint small-text muted" id="bsim-cam-hint">3D：拖动旋转（水平 / 上下）、滚轮缩放</p>
            <div class="bsim-board" id="bsim-board"></div>
            <div class="bsim-play" role="group" aria-label="回放控制">
              <button type="button" class="icon-button" data-play="first" title="回到开局（Home）">⏮</button>
              <button type="button" class="icon-button" data-play="prev" title="上一步（←）">◀</button>
              <button type="button" class="icon-button bsim-toggle" data-play="toggle" title="播放 / 暂停（空格）">▶</button>
              <button type="button" class="icon-button" data-play="next" title="下一步（→）">▶▏</button>
              <button type="button" class="icon-button" data-play="last" title="跳到结束（End）">⏭</button>
              <input type="range" id="bsim-range" min="0" value="0" aria-label="回放进度">
              <span class="bsim-pos" id="bsim-pos"></span>
              <select id="bsim-interval" aria-label="播放间隔">${[400, 800, 1200, 2000].map(ms => `<option value="${ms}">${(ms / 1000).toFixed(1)}s</option>`).join('')}</select>
            </div>
          </div>
          <div class="content-card bsim-detail" id="bsim-detail" aria-live="polite"></div>
          <div class="content-card bsim-panel" id="bsim-panel" aria-live="polite"></div>
          <div class="content-card bsim-summary" id="bsim-summary"></div>
        </section>
        <aside class="bsim-side">
          <div class="content-card bsim-units" id="bsim-units"></div>
          <div class="content-card bsim-log-card">
            <div class="bsim-log-head"><h3>战斗日志</h3>
              <span><label class="tool-check bsim-log-toggle"><input type="checkbox" id="bsim-log-detail" ${setup.logDetail !== false ? 'checked' : ''}><span>机制明细与数值</span></label>
              <button type="button" class="button secondary small" data-export="txt">导出 TXT</button>
              <button type="button" class="button secondary small" data-export="json">导出 JSON</button></span></div>
            <ol class="bsim-log" id="bsim-log"></ol>
          </div>
        </aside>
      </div>
      <details class="content-card tool-help"><summary>模拟规则与数据来源</summary><div class="rich-text">
        <ol>${S.AI_NOTES.map(n => `<li>${esc(n)}</li>`).join('')}</ol>
        ${MECH?.rules?.length ? `<details class="bsim-handbook"><summary>客户端战斗手册（${MECH.rules.length} 条，battle_guidebook_part）</summary>
          <dl>${MECH.rules.map(r => `<dt>${esc(r.name)}</dt><dd>${esc(r.text)}</dd>`).join('')}</dl></details>` : ''}
        <p class="small-text muted">数据来源：${[...(D.sources || []), ...(MECH?.sources || [])].map(esc).join('；')}。</p>
      </div></details>
      <dialog id="bsim-editor" class="bsim-editor"><form method="dialog" id="bsim-editor-form">
        <div class="bsim-editor-head"><strong id="bsim-editor-title">自定义角色</strong>
          <button type="button" class="button secondary small" data-editor-close>关闭</button></div>
        <div class="bsim-editor-body" id="bsim-editor-body"></div>
        <div class="bsim-editor-foot"><span class="small-text muted" id="bsim-editor-hint"></span>
          <span><button type="button" class="button secondary small" data-editor-reset>恢复默认</button>
          <button type="button" class="button" data-editor-save>保存并重新模拟</button></span></div>
      </form></dialog>`;

    /* ---------- setup controls ---------- */
    const paintMaps = () => {
      const q = mapQuery.trim().toLowerCase();
      const list = maps.filter(m => !q || m.search.includes(q)).slice(0, 400);
      $('#bsim-map').innerHTML = list.map(m => `<option value="${m.id}" ${String(m.id) === String(setup.mapId) ? 'selected' : ''}>${esc(m.label)} · ${m.cells} 格</option>`).join('');
      const cur = mapById.get(String(setup.mapId));
      $('#bsim-map-meta').textContent = cur ? `当前：${cur.label} · ${cur.size} · ${cur.cells} 格` : '';
      paintSetupSummary();
    };
    // One-line "what will I simulate" summary, so the common case never needs
    // to open any of the folded setup groups.
    const paintSetupSummary = () => {
      const el = $('#bsim-setup-summary');
      if (!el) return;
      const cur = mapById.get(String(setup.mapId));
      const w = weatherList.find(x => x.id === Number(setup.weather));
      el.textContent = `${cur ? (cur.raw.stages || [])[0] || cur.label : '未选地图'} · ` +
        `${setup.A.length} vs ${setup.B.length} · ${setup.maxRounds} 回合 · 种子 ${setup.seed}` +
        (w ? ` · ${w.name}` : '');
    };
    const paintTeams = () => {
      for (const side of ['A', 'B']) {
        $('#bsim-chips-' + side).innerHTML = setup[side].map((slot, i) => {
          const r = typeof slot === 'string' ? byKey.get(slot) : slot;
          if (!r) return '';
          const custom = typeof slot !== 'string';
          return `<span class="bsim-chip side-${side}${custom ? ' is-custom' : ''}" title="${custom ? '自定义单位：可编辑属性与技能' : esc(r.profName || '')}">
            ${r.avatar ? `<img src="${esc(r.avatar)}" alt="" loading="lazy" decoding="async">` : ''}${esc(r.name)}<small>${esc(r.profName || r.stats?.hp || '')}</small>
            <button type="button" class="bsim-edit" data-edit="${side}:${i}" title="编辑属性与技能">✎</button>
            <button type="button" data-remove="${side}:${i}" aria-label="移除 ${esc(r.name)}">×</button></span>`;
        }).join('') || '<span class="small-text muted">还没有角色</span>';
        $('#bsim-count-' + side).textContent = `${setup[side].length} / 8`;
      }
      paintSetupSummary();
    };
    const save = () => persist('battle.setup', setup);
    const findRole = name => {
      const n = String(name || '').trim();
      if (!n) return null;
      return roster.find(r => r.name === n) || roster.find(r => r.name.includes(n));
    };
    const addRole = side => {
      const input = $('#bsim-add-' + side);
      const r = findRole(input.value);
      if (!r) { h.toast?.('没有找到这名角色'); return; }
      if (setup[side].length >= 8) { h.toast?.('每方最多 8 名角色'); return; }
      setup[side].push(r.key);
      input.value = '';
      paintTeams(); save();
    };

    /* ---------- board ---------- */
    const unitMeta = () => new Map(result.units.map(u => [u.uid, u]));
    const byIdName = uid => unitMeta().get(uid)?.name || uid;
    function staticBoard() {
      if (setup.view === '3d') return staticBoard3D();
      return staticBoard2D();
    }
    function staticBoard2D() {
      const g = result.grid;
      const used = new Set([...g.cells.values()].map(c => c.t));
      const defs = [...used].map(t => {
        const f = fieldTypes.get(Number(t)) || fieldTypes.get(t);
        const img = f?.topImage || f?.image;
        return img ? `<pattern id="bt-${t}" width="1" height="1" patternContentUnits="objectBoundingBox"><image href="${esc(img)}" width="1" height="1" preserveAspectRatio="none"/></pattern>` : '';
      }).join('');
      let maxH = 0, minH = Infinity;
      for (const c of g.cells.values()) if (c.walk) { maxH = Math.max(maxH, c.h); minH = Math.min(minH, c.h); }
      const span = Math.max(1, maxH - minH);
      const cells = [...g.cells.values()].map(c => {
        const x = c.x * CELL, y = c.y * CELL;
        const f = fieldTypes.get(Number(c.t));
        const fill = f?.topImage || f?.image ? `url(#bt-${c.t})` : (c.pit ? '#1f4d66' : '#55624d');
        const shade = c.walk ? (1 - (c.h - minH) / span) * 0.42 : 0.55;
        return `<g class="bsim-cell${c.pit ? ' is-pit' : ''}${c.walk ? '' : ' is-block'}" data-x="${c.x}" data-y="${c.y}">
          <rect x="${x}" y="${y}" width="${CELL}" height="${CELL}" fill="${fill}"/>
          <rect x="${x}" y="${y}" width="${CELL}" height="${CELL}" class="bsim-shade" fill-opacity="${shade.toFixed(2)}"/>
          <title>(${c.x},${c.y}) ${esc(c.name)} · 高度 ${c.h}${c.walk ? '' : ' · 不可进入'}</title>
          <text x="${x + 2}" y="${y + 9}" class="bsim-coord">${c.x},${c.y}</text>
          <text x="${x + CELL - 3}" y="${y + CELL - 4}" class="bsim-h">${c.h}</text></g>`;
      }).join('');
      $('#bsim-board').innerHTML = `<svg class="bsim-svg${setup.heights ? ' show-heights' : ''}${setup.coords ? ' show-coords' : ''}" viewBox="0 0 ${g.w * CELL} ${g.h * CELL}" role="img" aria-label="${esc(g.name)} 对局棋盘">
        <defs>${defs}<clipPath id="bsim-board-clip"><rect x="0" y="0" width="${g.w * CELL}" height="${g.h * CELL}"/></clipPath>
          <marker id="bsim-arrow" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z"/></marker></defs>
        <g class="bsim-static">${cells}</g><g class="bsim-dyn" id="bsim-dyn"></g></svg>`;
    }

    /* ---------- 3D board ----------
       The terrain is NOT reimplemented here: we call the battle-map page's
       gridIso() so the simulator gets exactly the same height layers, exposed
       side walls, recessed water, client top/wall textures and floating slab.
       Only the units / highlights are ours, appended into its 3D canvas. */
    const B3 = 30;
    const key3 = (x, y) => x + ',' + y;
    const rawMap = () => mapById.get(String(setup.mapId))?.raw;
    let zByKey = new Map(), liftPx = 12;

    function staticBoard3D() {
      const map = rawMap();
      const iso = window.WikiWorld?.gridIso;
      if (!map || !iso) {                     // graceful fallback
        $('#bsim-board').innerHTML = '<p class="small-text muted">3D 地形组件未载入。</p>';
        return;
      }
      $('#bsim-board').innerHTML = iso(map, B3, new Set(), setup.yaw, setup.tilt, setup.zoom);
      const frame = $('#bsim-board .world-iso-frame');
      const canvas = frame?.querySelector('.world-iso-canvas');
      if (!frame || !canvas) return;
      frame.classList.add('is-bsim');
      // Read the exact z layer the map renderer decided for each cell (it
      // handles pits / water separately), so tokens sit on the real surface.
      zByKey = new Map();
      for (const cell of canvas.querySelectorAll('.world-iso-cell[data-x]')) {
        const z = Number(cell.style.getPropertyValue('--h') || 0);
        const lift = Number(cell.style.getPropertyValue('--lift')?.replace('px', '') || 0);
        if (lift) liftPx = lift;
        zByKey.set(key3(cell.dataset.x, cell.dataset.y), z);
        const top = cell.querySelector('.world-iso-top');
        if (setup.heights) {
          const b = document.createElement('b');
          b.className = 'bsim3-h';
          b.textContent = cell.dataset.h;
          top?.appendChild(b);
        }
        if (setup.coords) {
          const b = document.createElement('b');
          b.className = 'bsim3-coord';
          b.textContent = `${cell.dataset.x},${cell.dataset.y}`;
          top?.appendChild(b);
        }
      }
      const dyn = document.createElement('div');
      dyn.className = 'bsim3-dyn';
      dyn.id = 'bsim3-dyn';
      canvas.appendChild(dyn);
      applyCam3D();
      fit3D();
    }

    function fit3D() {
      const f = $('#bsim-board .world-iso-frame'), st = f?.querySelector('.world-iso-stage');
      if (!f || !st) return;
      const fit = Math.min(f.clientWidth / Math.max(1, st.offsetWidth),
                           f.clientHeight / Math.max(1, st.offsetHeight)) * .82;
      f.style.setProperty('--fit', Math.max(.3, Math.min(3, fit)).toFixed(3));
    }

    function dynamicBoard3D(step) {
      const meta = unitMeta();
      const zOf = (x, y) => (zByKey.get(key3(x, y)) ?? 0) * liftPx;
      const area = new Set((step.area || []).map(c => key3(c.x, c.y)));
      const hitBy = aggregateHits(step);
      const path = new Set((step.path || []).map(p => key3(p.x, p.y)));
      // Same dashed 警戒范围 idea in 3D: mark the tiles inside each alert
      // diamond so the isometric board shows the zone too.
      const alert = new Set();
      if (setup.alertRange !== false) for (const s of step.snap || []) {
        if (!s.al || !s.alive || !s.al.p) continue;
        const d = Math.min(Number(s.al.d) || 0, 24);
        for (let dx = -d; dx <= d; dx++)
          for (let dy = -d; dy <= d; dy++)
            if (Math.abs(dx) + Math.abs(dy) === d) alert.add(key3(s.x + dx, s.y + dy));
      }
      let out = '';
      for (const o of step.placed || []) {
        const look = objectLook(o);
        out += `<div class="bsim3-placed ${look.cls} side-${esc(o.side)}"
            style="left:${o.x * B3 + B3 / 2}px;top:${o.y * B3 + B3 / 2}px;--z:${zOf(o.x, o.y) + liftPx}px"
            title="${esc(o.name)} · ${esc(look.label)} · (${o.x},${o.y})${o.maxHp > 1 ? ` · HP ${o.hp}/${o.maxHp}` : ''}${o.label ? ` · ${esc(o.label)}` : ''}"><b>${look.glyph}</b><small>${esc(o.name).slice(0, 8)}</small></div>`;
      }
      for (const s of step.snap) {
        const u = meta.get(s.uid);
        if (!u) continue;
        const hit = hitBy.get(s.uid), pct = Math.max(0, s.hp / u.maxHp);
        out += `<div class="bsim3-unit side-${u.side}${s.alive ? '' : ' is-dead'}${step.actor === s.uid ? ' is-actor' : ''}"
            style="left:${s.x * B3 + B3 / 2}px;top:${s.y * B3 + B3 / 2}px;--z:${zOf(s.x, s.y) + liftPx}px">
            <span class="bsim3-token" title="${esc(u.name)} · ${s.hp}/${u.maxHp}">
              ${u.avatar ? `<img src="${esc(u.avatar)}" alt="" loading="lazy">` : `<b>${esc(s.uid)}</b>`}
              <i class="bsim3-hp" style="--pct:${(pct * 100).toFixed(0)}%"></i>
              <small>${esc(s.uid)}</small>
              ${(s.dir || u.initialDir) ? `<i class="bsim3-facing" data-dir="${esc((s.dir || u.initialDir).join(','))}"></i>` : ''}
              ${hit ? `<em class="${hit.heal ? 'is-heal' : ''}${hit.crit ? ' is-crit' : ''}">${hit.heal ? '+' : '−'}${hit.amount}</em>` : ''}
              ${s.alive ? '' : '<span class="bsim3-dead">×</span>'}
            </span></div>`;
      }
      for (const cell of $('#bsim-board').querySelectorAll('.world-iso-cell[data-x]')) {
        const k = key3(cell.dataset.x, cell.dataset.y);
        cell.classList.toggle('is-area', area.has(k));
        cell.classList.toggle('is-target', !!step.target && key3(step.target.x, step.target.y) === k);
        cell.classList.toggle('is-path', path.has(k));
        cell.classList.toggle('is-alert', alert.has(k));
      }
      const dyn = $('#bsim3-dyn');
      if (dyn) dyn.innerHTML = out;
    }

    function applyCam3D() {
      const f = $('#bsim-board .world-iso-frame');
      if (!f) return;
      const canvas = f.querySelector('.world-iso-canvas');
      if (canvas) {
        canvas.style.setProperty('--yaw', setup.yaw + 'deg');
        canvas.style.setProperty('--tilt', setup.tilt + 'deg');
      }
      f.style.setProperty('--zoom', setup.zoom);
      f.dataset.yaw = setup.yaw; f.dataset.tilt = setup.tilt; f.dataset.scale = setup.zoom;
      const cam = f.querySelector('.world-iso-cam');
      if (cam) {
        const s = cam.children;
        if (s[0]) s[0].textContent = `水平 ${Math.round(setup.yaw)}°`;
        if (s[1]) s[1].textContent = `俯仰 ${Math.round(setup.tilt)}°`;
        if (s[2]) s[2].textContent = `${Math.round(setup.zoom * 100)}%`;
      }
    }
    const scheduleCam3D = () => {
      if (camFrame) return;
      camFrame = requestAnimationFrame(() => { camFrame = 0; applyCam3D(); });
    };

    function dynamicBoard(step) {
      if (setup.view === '3d') return dynamicBoard3D(step);
      return dynamicBoard2D(step);
    }
    function dynamicBoard2D(step) {
      const meta = unitMeta();
      const center = p => [p.x * CELL + CELL / 2, p.y * CELL + CELL / 2];
      let out = '';
      // 警戒范围: the client's ALERT_ATTACK zone is a Manhattan diamond of
      // radius `al.d` around its owner (checkAlert uses manhattan(g, at) <=
      // dist). Draw each active zone as a DASHED outline, clipped to the
      // board, so two overlapping alerts remain distinguishable.
      if (setup.alertRange !== false) {
        const gw = result?.grid?.w || 0, gh = result?.grid?.h || 0;
        let rings = '';
        for (const s of step.snap || []) {
          if (!s.al || !s.alive || !s.al.p) continue;
          const u = meta.get(s.uid);
          if (!u) continue;
          const side = String(s.uid).startsWith('A') ? 'A' : 'B';
          const d = Number(s.al.d) || 0;
          if (d <= 0) continue;
          const name = esc(u.name);
          const skill = esc(s.al.skill || '警戒');
          const cls = `bsim-alert-ring side-${side}${s.al.v ? ' is-hidden' : ''}${s.al.s ? ' is-strong' : ''}`;
          const tip = `<title>${name} · 「${skill}」 警戒范围 ${d} 格 · 剩余 ${s.al.left}/${s.al.p} 次${s.al.v ? ' · 客户端隐藏预览' : ''}</title>`;
          // A client range_max of 99 means "the whole field". A diamond of
          // that radius has no visible edge inside the viewBox, so draw the
          // board outline instead and label it 全场.
          if (d >= Math.max(gw, gh)) {
            rings += `<rect class="${cls} is-full" x="2" y="2" width="${gw * CELL - 4}" height="${gh * CELL - 4}">${tip}</rect>`;
            continue;
          }
          const [cx, cy] = center(s);
          const r = d * CELL;
          const pts = `${cx},${cy - r} ${cx + r},${cy} ${cx},${cy + r} ${cx - r},${cy}`;
          rings += `<polygon class="${cls}"
              points="${pts}">${tip}</polygon>`;
        }
        if (rings) out += `<g class="bsim-alert-ranges" clip-path="url(#bsim-board-clip)">${rings}</g>`;
      }
      // Client terrain overlays active at THIS replay step. Drawn beneath the
      // area / target highlight so the board shows 燃烧 / 冰冻 / 烟雾 … tiles.
      if (step.terrain?.length) {
        out += `<g class="bsim-terrain">${step.terrain.map(f =>
          `<g class="bsim-terrain-cell" data-field="${esc(f.id)}">
            <rect x="${f.x * CELL + 1}" y="${f.y * CELL + 1}" width="${CELL - 2}" height="${CELL - 2}"/>
            <text x="${f.x * CELL + CELL / 2}" y="${f.y * CELL + CELL - 7}">${esc(f.name)}</text>
            <title>(${f.x},${f.y}) ${esc(f.name)} · 地块 #${esc(f.id)}</title></g>`).join('')}</g>`;
      }
      if (step.area?.length) {
        out += step.area.map(c => `<rect class="bsim-area${step.skill?.heal ? ' is-heal' : ''}" x="${c.x * CELL + 1}" y="${c.y * CELL + 1}" width="${CELL - 2}" height="${CELL - 2}"/>`).join('');
      }
      if (step.target) out += `<rect class="bsim-target" x="${step.target.x * CELL + 2}" y="${step.target.y * CELL + 2}" width="${CELL - 4}" height="${CELL - 4}"/>`;
      if (step.path?.length > 1) {
        // Only the trajectory is drawn. A ghost circle on `step.from` made it
        // look as if the unit was still standing on its old tile after the
        // move; the unit token is drawn exclusively from `step.snap`.
        out += `<polyline class="bsim-path" points="${step.path.map(p => center(p).join(',')).join(' ')}" marker-end="url(#bsim-arrow)"/>`;
      }
      const hitBy = aggregateHits(step);
      // PLACE_ITEM / PLACE_UNIT / PLACE_TRAP (乌莉娅的雪人、蜜果、陷阱…).
      for (const o of step.placed || []) {
        const [cx, cy] = center(o);
        const look = objectLook(o);
        const hpPct = o.maxHp > 1 ? Math.max(0, Math.min(1, o.hp / o.maxHp)) : null;
        out += `<g class="bsim-placed ${look.cls} side-${esc(o.side)}" transform="translate(${cx},${cy})" data-placed="${esc(o.id)}">
          <title>${esc(o.name)} · ${esc(look.label)} #${o.id} · (${o.x},${o.y})${o.maxHp > 1 ? ` · HP ${o.hp}/${o.maxHp}` : ''}${o.label ? ` · ${esc(o.label)}` : ''}
施放者 ${esc(o.owner || '环境')}${o.desc ? `
${esc(o.desc)}` : ''}</title>
          ${o.kind === 'PLACE_UNIT' || look.cls === 'is-snowman'
            ? `<circle class="bsim-obj-body" cy="-4" r="${CELL * 0.2}"/><circle class="bsim-obj-body" cy="5" r="${CELL * 0.27}"/>`
            : look.cls === 'is-trap'
              ? `<path class="bsim-obj-body" d="M0 ${-CELL * 0.26}L${CELL * 0.26} ${CELL * 0.2}L${-CELL * 0.26} ${CELL * 0.2}Z"/>`
              : `<rect class="bsim-obj-body" x="${-CELL * 0.2}" y="${-CELL * 0.2}" width="${CELL * 0.4}" height="${CELL * 0.4}" transform="rotate(45)"/>`}
          <text class="bsim-obj-label" y="3">${look.glyph}</text>
          ${hpPct !== null ? `<rect class="bsim-obj-hp-bg" x="${-CELL * 0.28}" y="${CELL * 0.28}" width="${CELL * 0.56}" height="3"/>
            <rect class="bsim-obj-hp" x="${-CELL * 0.28}" y="${CELL * 0.28}" width="${CELL * 0.56 * hpPct}" height="3"/>` : ''}
          <text class="bsim-obj-pos" y="${CELL * 0.44}">${o.x},${o.y}</text>
        </g>`;
      }
      for (const s of step.snap) {
        const u = meta.get(s.uid);
        const [cx, cy] = center(s);
        const r = CELL * 0.4, pct = Math.max(0, s.hp / u.maxHp);
        const hit = hitBy.get(s.uid);
        out += `<g class="bsim-token side-${u.side}${s.alive ? '' : ' is-dead'}${step.actor === s.uid ? ' is-actor' : ''}${setup.panelUid === s.uid ? ' is-selected' : ''}" data-unit="${esc(s.uid)}" transform="translate(${cx},${cy})">
          <title>${esc(u.name)} · ${esc(u.profName)} · ${s.hp}/${u.maxHp} · 点击查看面板</title>
          <circle class="bsim-ring" r="${r + 2}"/>
          <clipPath id="bsim-clip-${s.uid}"><circle r="${r}"/></clipPath>
          ${u.avatar ? `<image href="${esc(u.avatar)}" x="${-r}" y="${-r}" width="${2 * r}" height="${2 * r}" clip-path="url(#bsim-clip-${s.uid})" preserveAspectRatio="xMidYMid slice"/>` : `<circle r="${r}" class="bsim-fill"/>`}
          <rect class="bsim-hpbg" x="${-r}" y="${r + 1}" width="${2 * r}" height="4" rx="1"/>
          <rect class="bsim-hp" x="${-r}" y="${r + 1}" width="${(2 * r * pct).toFixed(1)}" height="4" rx="1"/>
          <text class="bsim-tag" y="${-r - 3}"><tspan x="0">${esc(u.name)}</tspan><tspan x="0" dy="8" class="bsim-tag-uid">${esc(s.uid)} (${s.x},${s.y})</tspan></text>
          ${(() => { const d = s.dir || u.initialDir || [1, 0]; if (!d[0] && !d[1]) return '';
             return `<path class="bsim-unit-facing" d="${facingArrow(d, r + 8, r + 1, 4)}"/>`; })()}
          ${hit ? `<text class="bsim-float${hit.heal ? ' is-heal' : ''}${hit.crit ? ' is-crit' : ''}" y="${-r - 12}">${hit.heal ? '+' : '−'}${hit.amount}${hit.crit ? '!' : ''}</text>` : ''}
          ${s.alive ? '' : `<path class="bsim-x" d="M${-r * 0.6} ${-r * 0.6}L${r * 0.6} ${r * 0.6}M${r * 0.6} ${-r * 0.6}L${-r * 0.6} ${r * 0.6}"/>`}
        </g>`;
      }
      const dyn = $('#bsim-dyn');
      if (dyn) dyn.innerHTML = out;
    }

    /* ---------- panels ---------- */
    function paintUnits(step) {
      const meta = unitMeta();
      const snap = new Map(step.snap.map(s => [s.uid, s]));
      // Summons join `units` mid-battle; at earlier replay steps they have no
      // snapshot yet, so hide them until the step they appear on.
      $('#bsim-units').innerHTML = ['A', 'B'].map(side => `<div class="bsim-unit-group"><h3 class="bsim-side-${side}">${SIDE[side]}</h3>
        ${result.units.filter(u => u.side === side && snap.has(u.uid)).map(u => {
          const s = snap.get(u.uid), mhp = s.mhp || u.maxHp, pct = Math.max(0, s.hp / mhp * 100);
          const buffs = (s.b || []).map(([id, turns, stacks, aura, on]) => {
            const def = MECH?.buffs?.[id];
            const kind = def?.bt === 3 ? 'is-debuff' : def?.bt === 2 ? 'is-buff' : '';
            const left = turns && turns <= 20 ? `<small>${turns} 回合</small>` : '';
            // on === 0: the client keeps the buff but its active_param is false
            // (速度4「若没有[霜佑之印]则失效」) — shown, but marked dormant.
            const dormant = on === 0;
            return `<span class="bsim-buff ${kind}${aura ? ' is-aura' : ''}${dormant ? ' is-dormant' : ''}" title="${esc(def?.d || '')}${turns > 20 ? '（长期）' : ''}${dormant ? '（激活条件不满足，暂未生效）' : ''}">${esc(buffName(id))}${stacks > 1 ? ` ×${stacks}` : ''}${left}${dormant ? '<small>未生效</small>' : ''}</span>`;
          }).join('');
          // 赛事选手 / 自定义角色没有 Wiki 词条（pageId = 0）。整张卡片都用于
          // 打开角色面板；只有确实存在词条时才附一个独立的「↗ 角色页」链接，
          // 否则点击名字会跳到 #/page/0（pages/0 空档案）。
          const wikiPage = Number(u.pageId) || 0;
          const pageLink = wikiPage > 0
            ? `<a class="bsim-unit-page" href="#/page/${wikiPage}" title="打开「${esc(u.name)}」角色页" aria-label="打开「${esc(u.name)}」角色页">↗</a>` : '';
          return `<div class="bsim-unit${s.alive ? '' : ' is-dead'}${step.actor === u.uid ? ' is-actor' : ''}${setup.panelUid === u.uid ? ' is-selected' : ''}" data-unit="${esc(u.uid)}" role="button" tabindex="0" title="点击查看角色面板">
            ${u.avatar ? `<img src="${esc(u.avatar)}" alt="" loading="lazy" decoding="async">` : '<span></span>'}
            <div><div class="bsim-unit-name"><div class="bsim-unit-title-row"><span class="bsim-unit-title">${esc(u.name)}</span>${pageLink}</div><small>${esc(u.uid)} · ${esc(u.profName)} · 速度 ${s.spd != null ? s.spd : u.stats.spd} · 点开面板</small></div>
              <div class="bsim-bar"><i style="width:${pct.toFixed(1)}%"></i></div>
              <small class="bsim-unit-hp">${fmt(s.hp)} / ${fmt(mhp)}${s.ar ? ` · 护盾 ${fmt(s.ar)}` : ''}${s.tp != null ? ` · 能量 ${s.tp}` : ''}${s.alive ? '' : ' · 阵亡'}</small>
              ${buffs ? `<div class="bsim-buffs">${buffs}</div>` : ''}
              <div class="bsim-skills">${u.skills.map(k => `<span title="${esc(k.desc || '')}">${esc(k.n || k.name)}${k.tp ? `<small>能${k.tp}</small>` : ''}${(k.cd ?? k.cooldown) ? `<small>CD${k.cd ?? k.cooldown}</small>` : ''}</span>`).join('')}</div>
              ${u.passiveSkills?.length ? `<div class="bsim-passives" title="被动 / 反应 / 队长 / 个性 / 特性技能（按效果结算）">${u.passiveSkills.map(k => esc(k.n)).join(' · ')}</div>` : ''}</div></div>`;
        }).join('')}</div>`).join('');
      void meta;
    }

    // Live character panel: every stat is expandable down to the individual
    // client effects (and their flat / percent contributions) that produced it.
    const SRC_NAME = {passive: '被动/个性', buff: '状态', hp: '受伤衰减', skill: '技能',
                      restrain: '克制', weather: '天气', constant: '客户端常量'};
    const partRow = p => {
      const num = v => v ? `${v > 0 ? '+' : ''}${v}` : '';
      const val = p.fixed !== undefined ? `固定 ${p.fixed}`
        : [num(p.flat), p.pct ? `${num(p.pct)}%` : '', p.note || ''].filter(Boolean).join(' · ') || '—';
      const title = [p.t, p.skillName ? `来源技能：${p.skillName} (#${p.skillId})` : '',
                     p.specId ? `效果 #${p.specId}` : '', p.buff ? `状态 #${p.buff}` : ''].filter(Boolean).join(' · ');
      return `<div class="bsim-part${p.ok ? '' : ' is-off'}${p.aura ? ' is-aura' : ''}">
        <span class="bsim-part-src">${esc(SRC_NAME[p.src] || p.src)}${p.aura ? '·光环' : ''}${p.stacks > 1 ? ` ×${p.stacks}` : ''}</span>
        <span class="bsim-part-name" title="${esc(title)}">${esc(p.n)}${p.skillName ? `<em>${esc(p.skillName)}</em>` : ''}</span>
        <span class="bsim-part-val">${esc(val)}</span>
        <span class="bsim-part-ok">${p.conditional ? '攻击时' : p.ok ? '生效' : '未满足'}</span></div>`;
    };
    const prewarRow = p => `<div class="bsim-part is-prewar">
        <span class="bsim-part-src">开局修正</span>
        <span class="bsim-part-name" title="效果 #${p.spec} · ${esc(p.t)}">${esc(p.n)}</span>
        <span class="bsim-part-val">${esc(p.note || [p.flat ? `${p.flat > 0 ? '+' : ''}${p.flat}` : '',
                      p.pct ? `×(1+${p.pct}%)` : ''].filter(Boolean).join(' · ') || '—')}</span>
        <span class="bsim-part-ok">战前</span></div>`;
    function paintPanel(step) {
      const box = $('#bsim-panel');
      if (!box) return;
      if (!setup.panelUid || !result.inspect) { box.innerHTML = ''; return; }
      const p = result.inspect(step.seq, setup.panelUid);
      if (!p) { box.innerHTML = ''; return; }
      const state = ['', '健康', '受伤', '濒死', '阵亡'][p.hpState] || '';
      const attrs = p.attrs.map(a => `<details class="bsim-attr">
          <summary><span>${esc(a.label)}</span><b>${fmt(Math.round(a.value))}</b><small>${a.parts.length} 项修正</small></summary>
          <div class="bsim-attr-body">
            <div class="bsim-formula"><b>图鉴 / 成长表基础值</b> ${fmt(a.base)}
              ${a.critBase ? `<em>含客户端常量基础 ${a.critBase}</em>` : ''}

              ${a.prewarFlat || a.prewarPct ? `<em>开局修正 ${a.prewarFlat ? `+${a.prewarFlat}` : ''}${a.prewarPct ? ` ×(1+${a.prewarPct}%)` : ''} → ${fmt(Math.round(a.prewar * 100) / 100)}</em>` : ''}</div>
            ${a.prewarParts?.length ? `<div class="bsim-parts-head">开局修正明细（${a.prewarParts.length}）<span>每条效果的来源与数值</span></div>
              ${a.prewarParts.map(prewarRow).join('')}` : ''}
            ${a.parts.length ? `<div class="bsim-parts-head">客户端效果（${a.parts.length}）<span>来源 / 效果 / 贡献 / 条件</span></div>
              ${a.parts.map(partRow).join('')}` : '<p class="small-text muted">没有额外效果修正，直接取基础值。</p>'}
            <div class="bsim-formula is-final"><b>计算公式</b> ${esc(a.formula)}</div>
          </div></details>`).join('');
      const buffs = p.buffs.length ? `<div class="bsim-panel-buffs">${p.buffs.map(b => `<span class="bsim-buff ${b.bt === 3 ? 'is-debuff' : b.bt === 2 ? 'is-buff' : ''}${b.aura ? ' is-aura' : ''}" title="${esc(b.d)}">${esc(b.n)}${b.stacks > 1 ? ` ×${b.stacks}` : ''}${b.turns && b.turns <= 20 ? `<small>${b.turns} 回合</small>` : ''}</span>`).join('')}</div>`
        : '<p class="small-text muted">当前没有状态。</p>';
      box.innerHTML = `<div class="bsim-panel-head"><div><strong>角色面板 · ${esc(p.name)}</strong>
          <small>第 ${step.seq} 步 · <span class="bsim-side-${p.side}">${SIDE[p.side]}</span> ${esc(p.profName)}${p.star ? ` · ${p.star} 星` : ''} · 位置 (${p.x},${p.y}) · ${state}</small></div>
          <button type="button" class="button secondary small" data-panel-close>关闭</button></div>
        <div class="bsim-panel-stats">
          <span>生命 <b>${fmt(p.hp)} / ${fmt(p.mhp)}</b></span><span>能量 <b>${p.tp}</b></span>
          <span title="物理 ${fmt(p.shieldPhys)} / 魔法 ${fmt(p.shieldSpell)}">护盾 <b>${fmt(p.shieldPhys + p.shieldSpell)}</b></span>
          <span>状态 <b>${p.buffs.length}</b></span>
          <span>技能 <b>${p.skills.length}</b></span><span>被动 <b>${p.passives.length}</b></span></div>
        ${p.shields?.length ? `<details class="bsim-panel-block bsim-shield-block" open><summary>护盾来源明细（${p.shields.length}）</summary>
          <div class="bsim-shield-list">${p.shields.map(s => `<div class="bsim-shield-row">
            <b>${esc(s.buffName)} <small>#${s.buff} · ${s.kind === 'phys' ? '物理护盾' : '魔法护盾'}</small></b>
            <span>${esc(s.attr)} ${fmt(s.attrValue)} × ${s.pct}% = 每层 ${fmt(s.perLayer)}</span>
            <span>× ${s.stacks} 层${s.factor !== 1 ? ` × 受护盾系数 ${s.factor}` : ''} = <em>${fmt(s.total)}</em></span>
            <small>${esc(s.note || '')} · speciality #${s.spec} · 取值${esc(s.source)}</small>
          </div>`).join('')}</div>
          <p class="small-text muted">合计：物理 ${fmt(p.shieldPhys)} / 魔法 ${fmt(p.shieldSpell)}。
            客户端按「每层 10% 生命 × 层数」计算，不是只算一层。</p></details>` : ''}
        <p class="bsim-panel-hint small-text muted">点开任意一项查看它由哪些客户端效果叠加而成；"未满足"表示该效果的 Lua 激活条件在此时不成立。
          ${CUP?.speedNote ? `<br>${esc(CUP.speedNote)}` : ''}
          <br>暴击率 / 暴击伤害含客户端常量基础值 ${p.critBaseChance}% / ${p.critBaseDamage}%（const_param），已作为独立来源列出。</p>
        <div class="bsim-attrs">${attrs}</div>
        <details class="bsim-panel-block"><summary>当前状态（${p.buffs.length}） · 位置 (${p.x},${p.y})</summary>
          <p class="small-text bsim-pos-line">当前所在位置 <b>(${p.x},${p.y})</b> · 第 ${step.seq} 步${step.from && (step.from.x !== p.x || step.from.y !== p.y) ? ` · 本步从 (${step.from.x},${step.from.y}) 移动到此` : ' · 本步未移动'}</p>
          ${buffs}</details>
        <details class="bsim-panel-block"><summary>技能（${p.skills.length}）</summary><div class="bsim-panel-skills">${p.skills.map(s =>
          `<span title="${esc(s.desc || '')}">${esc(s.n)}${(s.labels || []).length ? `<span class="bsim-skill-labels">${s.labels.map(x => `<i class="bsim-skill-tag">${esc(x)}</i>`).join('')}</span>` : ''}<small>${s.dt === 3 ? '治疗' : `倍率${s.df}%`} · 射程${s.rmin}-${s.rmax}${s.tp ? ` · 能${s.tp}` : ''}${s.cd ? ` · CD${s.cd}` : ''}</small></span>`).join('')}</div></details>
        <details class="bsim-panel-block"><summary>被动 / 反应 / 个性（${p.passives.length}）</summary><div class="bsim-panel-skills">${p.passives.map(s =>
          `<span title="${esc((s.types || []).join('、'))}">${esc(s.n)}<small>${(s.types || []).slice(0, 3).join('、') || '效果'}</small></span>`).join('')}</div></details>
        ${(p.skillStates || []).length ? `<details class="bsim-panel-block bsim-skill-state" open><summary>技能实际射程 / 击退 / 增伤（${p.skillStates.length} 项，含客户端增益拆分）</summary>
          ${p.skillStates.map(st => `<div class="bsim-pers-row"><b>${esc(st.name)} <small>#${st.id} · ${esc(st.shape)}</small></b>
            <p class="small-text">射程 <em>${st.min}–${st.max}</em> 格 = 模板 ${st.baseMin}–${st.baseMax} + 增益 ${st.rangeBonus} ·
              击退 <em>${st.knockbackTotal}</em> 格 = 基础 ${st.knockbackBase} + 增益 ${st.knockbackBonus}${st.damageBonus ? ` · 伤害 +${st.damageBonus}%` : ''}</p>
            ${st.rangeRows.length ? `<div class="bsim-mech-list">${st.rangeRows.map(r =>
              `<span class="is-ok" title="${esc(r.condition || '')}">射程 +${r.max}${r.min ? ` / 最小 +${r.min}` : ''} · #${r.spec} ${esc(r.name)}${r.buff ? ` · [${esc(String(r.buff))}] ×${r.stacks}` : ''} · ${esc(r.source)}</span>`).join('')}</div>` : ''}
            ${st.knockbackRows.length ? `<div class="bsim-mech-list">${st.knockbackRows.map(r =>
              `<span class="is-ok">击退 +${r.value} · #${r.spec} ${esc(r.name)}${r.buff ? ` · ×${r.stacks}` : ''}</span>`).join('')}</div>` : ''}
            ${st.damageRows.length ? `<div class="bsim-mech-list">${st.damageRows.map(r =>
              `<span class="is-ok">伤害 +${r.value}% · #${r.spec} ${esc(r.name)}${r.buff ? ` · ×${r.stacks}` : ''}</span>`).join('')}</div>` : ''}
            ${st.composition ? `<p class="small-text">复合态：${st.composition.chainLength} 段链路 / ${st.composition.damageSegments} 段伤害 / ${st.composition.effectTotal} 项效果
              （${st.composition.segments.map(sg => `${sg.factor ? sg.factor + '%' : '无伤害'}·${sg.effects.length}项`).join(' → ')}）</p>` : ''}
          </div>`).join('')}
          <small class="muted">「七手八脚的分工合作」#14680/#14681、「不屈不挠的流星意志」#14726 与[后备隐藏脂肪] #12417 的射程加成逐项累加；#12416 每层 +1 击退距离、#14674 每层 +5% 伤害。</small></details>` : ''}
        ${(p.personality || []).length ? `<details class="bsim-panel-block bsim-personality" open><summary>个性效果（${p.personality.length}）</summary>
          ${p.personality.map(ps => `<div class="bsim-pers-row"><b>${esc(ps.n)}</b>
            ${ps.desc ? `<p class="small-text">${esc(ps.desc)}</p>` : ''}
            <div class="bsim-mech-list">${ps.effects.map(e => `<span class="is-ok" title="${esc(e.c || e.dp || '')}">${esc(e.t)} · ${esc(e.timing || ('时机' + e.at))}${e.p && e.p.some(x => x) ? ` · ${esc(e.p.filter(x => x).join('/'))}` : ''}</span>`).join('')}</div></div>`).join('')}</details>` : ''}
        ${p.alert ? `<details class="bsim-panel-block bsim-alert-panel" open><summary>警戒状态</summary>
          <div class="bsim-pers-row"><b>范围 ${p.alert.dist} 格 · 每回合 ${p.alert.points} 次警戒${p.alert.segments > 1 ? ` · 一段警戒造成 ${p.alert.segments} 段伤害` : ''}</b>
            <p class="small-text">剩余 ${p.alert.left} 次${p.alert.factors?.length > 1 ? ` · 伤害段 ${p.alert.factors.map(f => f + '%').join(' + ')}` : ''}${p.alert.strengthened ? ` · 警戒强化（射程提升、伤害提高，${p.alert.interrupts ? '可打断技能' : '不打断行动'}）` : ''}${p.alert.display ? ' · 范围预览' : ''}${p.alert.hidePreview ? ' · 隐藏预览' : ''}</p>
            <p class="small-text">一次触发消耗 1 次次数、只施放 1 次；ADDITIONAL_ATTACK 链接的纯伤害技能并入这次施放的伤害段。</p>
            <div class="bsim-mech-list"><span class="is-ok">ALERT_ATTACK</span><span class="is-ok">STRENGTHEN_ALERT</span><span>alert_dist</span><span>alert_points</span><span>ADDITIONAL_ATTACK</span></div></div></details>` : ''}
        ${p.ai ? `<details class="bsim-panel-block"><summary>客户端 AI 决策（${p.ai.byOrder ? '按声明顺序' : p.ai.sorted ? '按 ai_skill_order 排序' : '评分择优'}）</summary>
          <div class="bsim-pers-row"><b>技能顺序 <code>#${(p.ai.order || []).join(' #')}</code></b>
            <p class="small-text">当前序号 ${p.ai.cursor}；该顺序来自 unit_npc.skill_ids。</p></div></details>` : ''}
        ${(p.conditionalMods || []).length ? `<details class="bsim-panel-block bsim-cond-mods"><summary>攻击时生效的修正（${p.conditionalMods.reduce((n, m) => n + m.rows.length, 0)}）</summary>
          ${p.conditionalMods.map(m => `<div class="bsim-pers-row"><b>${esc(m.key)}</b>
            <div class="bsim-mech-list">${m.rows.map(r => `<span title="${esc(r.c || r.dp || '')}">${esc(r.n)}${r.dp ? ' · 动态参数' : ''}${r.buff ? ` · 状态 #${r.buff}` : ''}</span>`).join('')}</div></div>`).join('')}</details>` : ''}`;
    }

    function paintDetail(step) {
      const meta = unitMeta();
      const u = step.actor && meta.get(step.actor);
      const head = step.kind === 'start' ? '开局部署' : step.kind === 'end' ? '战斗结束'
        : `第 ${step.round} 回合 · <span class="bsim-side-${u.side}">${SIDE[u.side]}</span> ${esc(u.name)}`;
      const actorDir = (step.snap || []).find(z => z.uid === step.actor)?.dir;
      const facingInfo = step.kind === 'start' || step.kind === 'end' || !actorDir ? '' :
        `<div class="bsim-facing-note">行动后朝向 <b>${DIR_NAMES(actorDir)}</b>` +
        `${step.facingFrom && step.facingFrom.join(',') !== actorDir.join(',') ?
          `（原 ${DIR_NAMES(step.facingFrom)}）` : ''}` +
        `<small>移动取路径最后一段、施放技能取目标方向；带「不转向」特技的技能保持原朝向。</small></div>`;
      // `all_skill_list`: every evaluated skill is a candidate, with its
      // declared-order priority and the winning cast block.
      const cands = (step.candidates || []);
      const TIER_LABEL = {personality: '个性技能', basic: '普攻', carried: '携带技能'};
      const alts = cands.length ? `<details class="bsim-candidates" open><summary>AI 候选 · all_skill_list（${cands.length} 个技能）</summary>
        <div class="bsim-candidate-grid">${cands.map((c, i) => `<div class="bsim-candidate ${i === 0 && step.kind === 'skill' ? 'is-pick' : ''}">
          <b>${esc(c.skill)}</b>${(c.labels || []).length ? ` <span class="bsim-skill-labels">${c.labels.map(x => `<i class="bsim-skill-tag">${esc(x)}</i>`).join('')}</span>` : ''} <span>#${esc(String(c.id))} · 评分 <em>${fmt(c.score)}</em></span>
          <small>${esc(TIER_LABEL[c.tier] || '携带技能')}${c.instant ? ' · [瞬发]' : ''}${c.slot >= 0 ? ` · 槽位 ${c.slot + 1}` : ''} ·
          站位 (${c.stand.x},${c.stand.y}) → 目标 (${c.target.x},${c.target.y})${c.dir ? ` · 扫射 ${c.dir[0] > 0 ? '东' : c.dir[0] < 0 ? '西' : c.dir[1] > 0 ? '南' : '北'} ${fmt(c.areaN)} 格` : ''} · 施法距离 ${fmt(c.castDist ?? 0)} 格 · 移动 ${fmt(c.cost)} ·
          skill_orders 序号 ${c.declared < 100 ? c.declared : '—'} · 优先级 ${fmt(c.priority)}${c.castRim != null ? ` · 可达射程外环 ${fmt(c.castRim)} 格` : ''}${c.shape && c.shape !== 'diamond' ? ` · 范围形状 <code>${esc(c.shape)}</code>` : ''}${c.targetQuality ? ` · 目标质量 ${fmt(c.targetQuality)}` : ''}</small></div>`).join('')}</div>
        <small class="muted">客户端 <code>ai_skill_by_order</code> 用 <code>skill_orders</code> 设定 <code>all_skill_list</code> 的评价优先级；
          个性技能 / 普攻 / 正常携带技能分三档，携带技能同档再按技能放置顺序加分，[瞬发] 因不结束行动而额外优先。
          选位取射程外环（施法距离 = range_max）再按最小移动过滤；可选目标格按客户端 <code>range_select</code>（<code>skill.target_select</code>）展开，十字 / 单向线 / 矩形 / 横线 / 侧面 / 扇形只能沿直线，不能瞄斜角。抉择（SKILL_GROUP）的选项继承所属组的序号，只有 <code>boss_skill_mode</code> 才按 <code>cur_skill</code> 轮换。</small></details>` : '';
      const objs = (step.placed || []).length ? `<details class="bsim-objects" open><summary>场上交互物（${step.placed.length}）</summary>
        <div class="bsim-object-grid">${step.placed.map(o => {
          const look = objectLook(o);
          return `<div class="bsim-object-row ${look.cls}"><b>${look.glyph} ${esc(o.name)}</b>
            <span>${esc(look.label)} · <code>(${o.x},${o.y})</code>${o.maxHp > 1 ? ` · HP ${o.hp}/${o.maxHp}${o.attackable ? ' · 可攻击' : ''}` : ''}${o.label ? ` · ${esc(o.label)}` : ''}</span>
            ${o.triggerSkill ? `<small>触发技能 #${o.triggerSkill}${o.limit ? ` · 限 ${o.limit - o.triggers} 次` : ''}</small>` : ''}
            ${o.desc ? `<small class="muted">${esc(o.desc.slice(0, 110))}</small>` : ''}</div>`;
        }).join('')}</div></details>` : '';
      const order = step.order?.length ? `<details class="bsim-order"><summary>行动顺序（按实时速度）</summary><div class="bsim-order-list">${step.order.map((o, i) =>
        `<em class="${o.uid === step.actor ? 'is-now' : ''}">${i + 1}. ${esc(o.name)} <b>${o.spd}</b></em>`).join('')}</div>
        <small class="muted">客户端 WaitTimeView 在速度变化时调用 AdjustWaitTime / ResetSortItems 重排行动条，本模拟器在每次行动前按实时速度重新排序。</small></details>` : '';
      const moveRule = step.moveRule?.pipeline?.length ? `<details class="bsim-move-rule"><summary>为什么走到这里</summary>
        <p class="small-text">站位 <b>${esc(step.moveRule.bestStand || '原地')}</b> · 移动 <b>${fmt(step.moveRule.moveSteps || 0)} / ${fmt(step.moveRule.mobility || 0)}</b> 格
          （客户端 <code>move_steps</code> / <code>filterByMinMoveDist</code>${step.moveRule.canStay ? ' · <code>canStay</code> 已启用' : ''}，不强制走满）${step.moveRule.castShape ? ` · 施放范围 <code>${esc(step.moveRule.castShape)}</code>（客户端 range_select）` : ''} ·
          最小移动 ${step.moveRule.minMoveDist ? '启用' : '关闭'} · 移动+目标距离 ${step.moveRule.moveAndTargetDist ? '启用' : '关闭'} ·
          象限比较 ${step.moveRule.quadrant ? '启用' : '关闭'} ·
          移动步数 ${step.moveRule.moveSteps || 0}</p>
        ${step.moveRule.aiByOrder ? `<p class="small-text">客户端 <code>ai_skill_by_order</code>：<code>skill_orders</code> 只是 <code>all_skill_list</code> 的评价优先级（<code>#${(step.moveRule.skillOrder || []).join(' #')}</code>），
          所有可施放技能都参与选位；<code>cur_skill</code> 仅对 <code>boss_skill_mode</code>（本单位 ${step.moveRule.aiBossMode || 0}）轮换，当前 ${step.moveRule.curSkill}。</p>` : ''}
        ${(step.moveRule.allSkillList || []).length ? `<p class="small-text">本回合 <code>all_skill_list</code>：<code>#${step.moveRule.allSkillList.join(' #')}</code>（${step.moveRule.allSkillList.length} 个）；
          声明优先级 ${Object.entries(step.moveRule.priority || {}).map(([k, v]) => `<code>#${esc(k)}:${fmt(v)}</code>`).join(' ') || '无'}。</p>` : ''}
        ${(step.moveRule.slotOrder || []).length ? `<p class="small-text">技能放置顺序 <code>#${step.moveRule.slotOrder.join(' #')}</code>（角色编辑器 ✎ 可上下调整） ·
          分组优先级：个性 ${step.moveRule.skillPriority?.personality ?? 3} / 携带 ${step.moveRule.skillPriority?.carried ?? 2} / 普攻 ${step.moveRule.skillPriority?.basic ?? 1}
          · 每档 ${step.moveRule.skillPriority?.tierStep ?? 60} 分 · 每槽 ${step.moveRule.skillPriority?.slotStep ?? 14} 分 · [瞬发] +${step.moveRule.skillPriority?.instantBonus ?? 420} 分
          ${step.moveRule.instantChain ? ` · 瞬发链第 ${step.moveRule.chainIndex + 1} 阶段` : ''}。</p>` : ''}
        ${step.moveRule.alertPoints ? `<p class="small-text">警戒：<code>alert_dist</code> ${step.moveRule.alertDist} 格 ·
          <code>alert_points</code> ${step.moveRule.alertPoints} 次 = 基础 <code>limit_count_turn</code> ${step.moveRule.alertBasePoints} +
          <code>SPECIALITY_COUNT_TURN</code> 光环/特技 ${step.moveRule.alertCountBonus}。</p>` : ''}
        <div class="bsim-mech-list">${step.moveRule.pipeline.map(x => `<span class="is-ok">${esc(x)}</span>`).join('')}</div>
        ${step.moveRule.skillState ? `<p class="small-text">本次技能<b>有效射程 ${step.moveRule.skillState.min}–${step.moveRule.skillState.max}</b> 格（模板 ${step.moveRule.skillState.baseMin}–${step.moveRule.skillState.baseMax} + 增益 ${step.moveRule.skillState.rangeBonus}，
          来源 ${step.moveRule.skillState.rangeRows.map(r => `#${r.spec} +${r.max}${r.buff ? `×${r.stacks}` : ''}`).join('、') || '无'}）·
          击退 ${step.moveRule.skillState.knockbackTotal} 格（基础 ${step.moveRule.skillState.knockbackBase} + 增益 ${step.moveRule.skillState.knockbackBonus}）${step.moveRule.skillState.damageBonus ? ` · 伤害 +${step.moveRule.skillState.damageBonus}%` : ''}。</p>` : ''}
        ${step.moveRule.noCastReason ? `<p class="small-text bsim-no-cast">本步未施放技能：${esc(step.moveRule.noCastReason)}</p>` : ''}
        ${(step.moveRule.comparators || []).length ? `<p class="small-text">实际生效的排序比较器（按客户端 <code>castPipeline</code> 声明顺序，共 ${step.moveRule.comparators.length} 个）：
          <code>${step.moveRule.comparators.map(esc).join(' → ')}</code>。目标质量 <code>targetSorts</code> ${step.moveRule.targetSorts?.length || 0} 项，权重 ${fmt(step.moveRule.targetSortWeight || 0)}，
          本步最优候选评分 ${fmt(step.moveRule.targetQuality || 0)}。</p>` : ''}
        ${(step.moveRule.aiFields || []).length ? `<div class="bsim-mech-list">${step.moveRule.aiFields.map(x => `<span>${esc(x)}</span>`).join('')}</div>` : ''}
        ${Object.entries(step.moveRule.clientMechanisms || {}).filter(([, v]) => v).length
          ? `<div class="bsim-mech-list">${Object.entries(step.moveRule.clientMechanisms).filter(([, v]) => v).map(([k]) => `<span class="is-ok">${esc(k)}</span>`).join('')}</div>` : ''}
        <small class="muted">流水线与字段来自已解密的客户端 Logic_AI_AIMachine；友军格可穿越但不可停留、敌军格阻断，逐格 Dijkstra 回溯路径。
          JUMP_MOVE / PathAlert / SPECIALITY_COUNT_TURN / target_order_param 均按客户端特技结算。</small></details>` : '';
      // Legend for the dashed map overlay: list the alert zones currently in
      // effect so the rings are identifiable without hovering every polygon.
      const alertLegend = (() => {
        if (setup.alertRange === false) return '';
        const list = (step.snap || []).filter(s => s.al && s.alive && s.al.p);
        if (!list.length) return '';
        return `<details class="bsim-alert-legend"><summary>地图警戒范围（${list.length} 个 · 虚线）</summary>
          <div class="bsim-mech-list">${list.map(s => {
            const u = meta.get(s.uid);
            const side = String(s.uid).startsWith('A') ? 'A' : 'B';
            return `<span class="bsim-alert-key side-${side}">${esc(u?.name || s.uid)} · ${esc(s.al.skill || '警戒')} · ${s.al.d >= 99 ? '全场' : `${s.al.d} 格`} · ${s.al.left}/${s.al.p} 次${s.al.v ? ' · 预览隐藏' : ''}</span>`;
          }).join('')}</div>
          <small class="muted">棋盘上以虚线菱形画出每个单位的警戒范围（曼哈顿距离，与客户端 checkAlert 判定一致）；我方蓝色、敌方橙色，虚线较淡者客户端隐藏预览；范围 99 覆盖全场时画棋盘外框。</small></details>`;
      })();
      const composition = step.plan?.composition;
      const compositionInfo = composition ? `<details class="bsim-composition" open><summary>技能复合态（${composition.chainLength} 段链路 / ${composition.damageSegments} 段伤害 / ${composition.effectTotal} 项效果）</summary>
        <p class="small-text muted">来源：${esc(composition.source)}。一次施放按客户端 idskill_follow 依次结算，每段有自己的倍率、条件倍率与状态效果。</p>
        ${composition.segments.map((sg, i) => `<div class="bsim-pers-row"><b>第 ${i + 1} 段 · ${esc(sg.name || '子技能')} #${sg.id}${sg.factor ? ` · 倍率 ${sg.factor}%` : ' · 无伤害段'}</b>
          ${sg.effects.length ? `<div class="bsim-mech-list">${sg.effects.map(e =>
            `<span class="${e.kind === '条件倍率' ? 'is-ok' : ''}" title="${esc(e.when || '')}">${esc(e.kind)} · #${e.spec} ${esc(e.name || '')}${e.value ? ` · ${esc(String(e.value))}` : ''}${e.when ? ` · 条件 ${esc(String(e.when).slice(0, 60))}` : ''}</span>`).join('')}</div>` : '<span class="small-text muted">无额外效果</span>'}
        </div>`).join('')}</details>` : '';
      const skillPlanInfo = step.plan ? `<details class="bsim-skill-plan"><summary>技能结算方案（${esc(step.skill?.name || (step.plan.g || []).map(g => g[0] + '×' + g[1] + '%').join(' + '))}）</summary>
        <div class="bsim-mech-list">${(step.plan.fx || []).map(x => `<span class="is-ok">${esc(x)}</span>`).join('')}</div>
        ${step.plan.cons || step.plan.bonus ? `<p class="small-text">每段独立结算暴击、护盾、防御与击败判定；${step.plan.bonus ? '消耗总量决定追加伤害段数' : '攻击后消耗能量/层数'}。</p>` : ''}
        ${step.plan.from?.length ? `<small class="muted">解密 speciality 依据：#${step.plan.from.join('、#')}</small>` : ''}</details>${compositionInfo}` : '';
      const consumption = step.consumption && step.consumption.count > 0 ?
        `<div class="bsim-consumption"><b>消耗转化 · ${esc(step.skill?.name || '技能')}</b>
          <span>能量 ${step.consumption.tp} 点 + [${esc(step.consumption.buffName || '状态')}] ${step.consumption.stacks} 层 = <em>${step.consumption.count} 层</em></span>
          ${step.consumption.bonus ? `<span>每层 ${step.consumption.bonus[0]}% × ${step.consumption.count} 层 = ${step.consumption.bonus[0] * step.consumption.count}%${step.consumption.bonus[1] ? `（增伤 ${step.consumption.bonus[1]}%）` : ''}，已作为独立伤害段结算</span>` : ''}</div>` : '';
      const alertInfo = step.alert ? `<div class="bsim-alert-note"><b>展开警戒 · ${esc(step.actor && (meta.get(step.actor)?.name || ''))}</b>
          <span>范围 <em>${step.alert.dist} 格</em> · 每回合 <em>${step.alert.points} 次</em>警戒${step.alert.countBonus
            ? `（基础 ${step.alert.basePoints} + 光环/特技 ${step.alert.countBonus}）` : ''}${step.alert.hits > 1 ? ` · 一段警戒造成 <em>${step.alert.hits} 段</em>伤害` : ''}${step.alert.strengthened ? ` · 警戒强化（${step.alert.interrupts ? '可打断' : '不打断'}）` : ''}${step.alert.hidePreview ? ' · 隐藏范围预览' : ''}</span>
          <small>次数与伤害段是两件事：<code>alert_points</code>（ALERT_ATTACK 的 <code>limit_count_turn</code> + <code>SPECIALITY_COUNT_TURN</code> 光环）是每回合可触发的<b>警戒次数</b>；
          一次触发只消耗 1 次、只施放 1 次，ADDITIONAL_ATTACK 链接的纯伤害技能并入这次施放的<b>伤害段</b>（安娜 35% + 35% = 2 段），不是两次警戒。
          只有 FORCE_STOP 或客户端「强制警戒（可打断技能）」才打断行动，STRENGTHEN_ALERT「警戒强化」只强化警戒。</small></div>` : '';
      const alertHits = step.alertHits?.length ? step.alertHits : (step.alertHit ? [step.alertHit] : []);
      const totalSegments = alertHits.reduce((n, h) => n + (h.segmentCount || h.hits || 1), 0);
      const reactionInfo = alertHits.length ? `<div class="bsim-alert-hit"><b>警戒反应 · ${esc(alertHits[0].owner)}「${esc(alertHits[0].skill)}」 · 本次行动 ${alertHits.length} 次触发 / ${totalSegments} 段伤害</b>
          ${alertHits.map((h, i) => `<span>第 ${i + 1}/${alertHits.length} 次：触发格 (${h.cell.x},${h.cell.y}) · 剩余 <em>${h.left}/${h.points}</em> 次
            （基础 ${h.basePoints} + 加成 ${h.countBonus}）${h.segmentCount || h.hits > 1 ? ` · 一段警戒造成 <em>${h.segmentCount || h.hits} 段</em>伤害` : ''}${h.forced ? ' · 强制停止，行动被打断' : ' · 不打断行动'}</span>
            ${(h.segments || []).length ? `<span>　伤害段：${h.segments.map(x =>
              `${esc(x.seg)}${x.miss ? '' : ` → ${fmt(x.amount)}`}`).join('；')}${h.segments.every(x => x.miss) ? '（本次警戒被闪避，均未结算）' : ''}</span>` : ''}`).join('')}
          <small>客户端 PathAlert 在移动路径逐格调用 CollectAlertBlocks / FindAlertTargetBlocks；先走进警戒范围会触发一次，随后 JUMP_MOVE / CHARGE 落地格再触发一次，每次只消耗 1 次警戒次数、各自结算 2 段。</small></div>` : '';
      const chainInfo = step.chainIndex > 0 || step.skill?.instant ? `<div class="bsim-instant-note"><b>${step.skill?.instant ? '[瞬发] 技能' : '瞬发后续行动'}</b>
          <span>${step.chainIndex > 0 ? `第 ${step.chainIndex + 1} 个行动阶段（CHECK_STATE → DO_SKILL → MOVE_OR_IDLE）` : '本次施放不结束行动'} ·
          已用移动 ${step.moveRule?.moveSteps || 0} 格${step.chainIndex > 0 ? '，按剩余移动力继续' : '，可用剩余移动力继续走 / 继续放技能'}</span>
          <small>只有施放非瞬发技能、待机或被 FORCE_STOP 打断才进入 FINISH；同一瞬发技能在一次行动内不重复施放。</small></div>` : '';
      const teleportInfo = step.teleport ? `<div class="bsim-teleport"><b>由技能「${esc(step.teleport.skill)}」#${step.teleport.skillId || ''} 触发位移机制 ${esc(step.teleport.spec || 'JUMP_MOVE')}</b>
          <span>(${step.teleport.from.x},${step.teleport.from.y}) → (${step.teleport.to.x},${step.teleport.to.y}) · 自位移 ${Math.abs(step.teleport.to.x - step.teleport.from.x) + Math.abs(step.teleport.to.y - step.teleport.from.y)} 格</span>
          <small>客户端特技 #${step.teleport.specId || 0}「${esc(step.teleport.specName || '')}」声明在「${esc(step.teleport.skill)}」的 speciality_ids 中；${step.teleport.instant ? '该技能是[瞬发]，因此位移后行动不结束' : '位移由技能结算产生，不是独立移动'}。</small></div>` : '';
      const knockInfo = step.knockbacks?.length ? `<details class="bsim-knock" open><summary>击退明细（${step.knockbacks.length}）</summary>
        <div class="bsim-mech-list">${step.knockbacks.map(k => `<div class="bsim-pers-row">
          <b>${esc(k.name)}·${esc(k.who)}：声明 ${k.declared} 格 → 实际 ${k.moved} 格</b>
          <span>结算距离 ${k.computed} 格${k.diagonal ? '（斜向减半）' : ''} · 方向 ${esc(k.direction)} ·
            (${k.from.x},${k.from.y}) → (${k.to.x},${k.to.y}) · ${esc(k.stop)}${k.noImpact ? ' · 回弹拉拽不触发撞击' : ''}</span></div>`).join('')}</div>
        <small class="muted">「击退 4 格」是特技声明值；斜向按手册减半，撞到角色 / 障碍 / 边界 / 高差 &gt;2 会提前停止，因此实际格数可能更少。</small></details>` : '';
      const fieldInfo = step.fields?.length ? `<details class="bsim-fields" open><summary>地块状态（${step.fields.length}）</summary>
        ${step.fields.map(f => `<div class="bsim-pers-row"><b>(${f.x},${f.y}) · ${esc(f.name)}</b>
          <span>地块 #${f.id} · 持续 ${f.turns} 回合，剩余 ${f.left} 回合 · 客户端 OPERATION / EXTRA_FIELD_STATUS</span></div>`).join('')}
        <small class="muted">地块规则来自客户端 field_status：燃烧每格额外消耗 0.5 移动力并施加[灼烧]，冰冻 1 移动力且滑退不消耗击退格数；IGNORE_FIELDSTATUS / NO_FIELDSTATUS_MOBILITY 可免疫。</small></details>` : '';
      const chargeInfo = step.charge ? `<div class="bsim-charge-note"><b>由技能「${esc(step.charge.skill)}」#${step.charge.skillId || ''} 触发位移机制 CHARGE</b>
          <span>(${step.charge.from.x},${step.charge.from.y}) → (${step.charge.to.x},${step.charge.to.y}) · 沿直线冲 ${step.charge.steps} 格，停在目标前一格</span>
          <small>客户端特技 #${step.charge.specId || 0}「${esc(step.charge.spec)}」声明在「${esc(step.charge.skill)}」上；冲锋是技能结算的一部分，不是先冲锋再放技能。冲锋路径逐格触发 PathAlert。</small></div>` : '';
      const scalingInfo = step.skillScaling?.length ? `<details class="bsim-scaling" open><summary>技能动态数值（客户端特技 × 状态层数，${step.skillScaling.length} 项）</summary>
        <div class="bsim-mech-list">${step.skillScaling.map(r => `<span class="is-ok">[${esc(r.buff)}] ×${r.stacks} → ${esc(r.attr)} +${r.value}${r.kind === '射程' ? ' 格' : r.attr === 'DAMAGE' ? '%' : ''}（#${r.spec}，每层 +${r.per}）</span>`).join('')}</div>
        <small class="muted">「贯穿天际的必胜流星」每 1 层[后备隐藏脂肪]：伤害 +5%、最大射程 +1 格、击退距离 +1 格；攻击后驱散全部层数。</small></details>` : '';
      const events = step.events?.length ? `<details class="bsim-events" ${step.events.length <= 12 ? 'open' : ''}><summary>触发的效果（${step.events.length}）</summary>
        <ul>${step.events.map(e => `<li>${esc(e)}</li>`).join('')}</ul></details>` : '';
      const calcs = (step.hits || []).filter(h => h.calc?.length);
      const damage = calcs.length ? `<details class="bsim-calc"><summary>伤害 / 治疗计算过程（${calcs.length}）</summary>
        ${calcs.map(h => `<div class="bsim-calc-hit"><b>${esc(byIdName(h.uid))} · ${esc(h.skill || (h.heal ? '治疗' : '伤害'))} → ${fmt(h.amount)}${h.absorbed ? `（护盾吸收 ${fmt(h.absorbed)}）` : ''}</b>
          ${h.formula ? `<div class="bsim-calc-expr">计算式：${esc(h.formula)}</div>` : ''}
          <table class="bsim-calc-table"><tbody>${h.calc.map(c => `<tr><td>${esc(c.label)}</td><td>${esc(String(c.value))}</td>${c.expr ? `<td class="bsim-calc-expr">${esc(c.expr)}</td>` : '<td></td>'}<td>${esc(c.note)}</td></tr>`).join('')}</tbody></table></div>`).join('')}</details>` : '';
      const skillTags = step.skill?.labels?.length
        ? `<div class="bsim-skill-labels bsim-detail-tags">使用技能「${esc(step.skill.name)}」${step.skill.labels.map(x => `<i class="bsim-skill-tag">${esc(x)}</i>`).join('')}</div>` : '';
      // A direction skill with range 0 targets a DIRECTION (审判诸罪之光's
      // 3*6 sweep). Show which of the four sweeps the AI chose; the shaded
      // area on the board is the rendered footprint.
      const DIR_NAME = d => !d ? '' : d[0] > 0 ? '东' : d[0] < 0 ? '西' : d[1] > 0 ? '南' : '北';
      const dirInfo = step.dir
        ? `<div class="bsim-detail-tags">扫射方向：<i class="bsim-skill-tag">向${DIR_NAME(step.dir)} · ${(step.area || []).length} 格</i></div>` : '';
      // Linked casts resolved at a turn boundary (审判执行 at 每人回合结束)
      // deal real damage but have no step of their own.
      const linkedInfo = step.subCasts?.length
        ? `<div class="bsim-detail-tags">行动结束联动施放：${step.subCasts.map(x =>
            `<i class="bsim-skill-tag">${esc(x.name)} · ${esc(x.skill)} #${esc(String(x.id))}</i>`).join('')}</div>` : '';
      $('#bsim-detail').innerHTML = `<div class="bsim-detail-head"><strong>${head}</strong><small>第 ${step.seq} / ${result.steps.length - 1} 步</small></div>
        ${skillTags}${dirInfo}${linkedInfo}<p>${esc(step.text)}</p>${facingInfo}${chainInfo}${alertInfo}${alertLegend}${reactionInfo}${teleportInfo}${chargeInfo}${knockInfo}${fieldInfo}${scalingInfo}${consumption}${skillPlanInfo}${alts}${objs}${moveRule}${order}${damage}${events}`;
    }

    function paintLog() {
      const meta = unitMeta();
      const detail = setup.logDetail !== false;
      let round = -1;
      $('#bsim-log').innerHTML = result.steps.map(s => {
        let head = '';
        if (s.round !== round && s.kind !== 'end') { round = s.round; if (round > 0) head = `<li class="bsim-log-round">第 ${round} 回合</li>`; }
        const u = s.actor && meta.get(s.actor);
        // The battle log itself carries every mechanism trigger with its
        // numeric derivation (分摊伤害 / 警戒段 / 冲锋位移 / 伤害链 / 层数).
        const mech = s.events?.length
          ? (detail ? `<ul class="bsim-log-mech">${s.events.map(e => `<li>${esc(e)}</li>`).join('')}</ul>`
                    : `<small class="bsim-log-ev">+${s.events.length} 效果</small>`) : '';
        return `${head}<li class="bsim-log-item${s.kind === 'end' ? ' is-end' : ''}" data-step="${s.seq}">
          ${u ? `<b class="bsim-side-${u.side}">${esc(u.name)}</b>` : ''}<span>${esc(s.text)}</span>${mech}</li>`;
      }).join('');
    }

    function paintSummary() {
      const win = result.winner === 'draw' ? '平局' : `${SIDE[result.winner]}胜利`;
      const rows = result.summary.slice().sort((a, b) => a.side.localeCompare(b.side) || (b.dealt + b.healed) - (a.dealt + a.healed));
      $('#bsim-summary').innerHTML = `<div class="bsim-result bsim-win-${result.winner}"><strong>${win}</strong><span>${esc(result.verdict)} · 共 ${result.rounds} 回合 · ${result.steps.length - 2} 次行动</span></div>
        <div class="table-scroll"><table class="data-table bsim-table"><thead><tr><th>单位</th><th>输出</th><th>承伤</th><th>治疗</th><th>击败</th><th>结果</th></tr></thead>
        <tbody>${rows.map(r => `<tr class="${r.uid === result.mvp ? 'is-mvp' : ''}"><td><span class="bsim-side-${r.side}">${esc(r.uid)}</span> ${esc(r.name)}${r.uid === result.mvp ? ' <em>MVP</em>' : ''}</td>
          <td>${fmt(r.dealt)}</td><td>${fmt(r.taken)}</td><td>${fmt(r.healed)}</td><td>${r.kills}</td><td>${r.alive ? `${fmt(r.hp)}/${fmt(r.maxHp)}` : '阵亡'}</td></tr>`).join('')}</tbody></table></div>
        ${mechPanel(result.mechanics)}`;
    }

    // Client object ids from props / trap tables: 呆呆雪人 516, 大号雪球 517,
    // 苔原蜜果 153, 碎冰 151. Give each a distinct glyph + colour and label.
    const OBJECT_IDS = {516: 'snowman', 559: 'snowman', 515: 'snowman', 517: 'snowball',
                        153: 'honey', 151: 'ice', 155: 'ice', 164: 'ice'};
    function objectLook(o) {
      const key = OBJECT_IDS[o.id] || (o.id === 153 ? 'honey' : o.id === 151 ? 'ice' : '');
      if (key === 'snowman' || key === 'snowball') return {cls: 'is-snowman', glyph: key === 'snowman' ? '雪' : '球', label: key === 'snowman' ? '可攻击物件（呆呆雪人）' : '可推动物件（雪球）'};
      if (key === 'honey') return {cls: 'is-honey', glyph: '果', label: '触发物（苔原蜜果）'};
      if (key === 'ice') return {cls: 'is-ice', glyph: '冰', label: '触发物（碎冰）'};
      if (o.kind === 'PLACE_UNIT') return {cls: 'is-snowman', glyph: '召', label: '召唤物'};
      if (o.kind === 'PLACE_TRAP') return {cls: 'is-trap', glyph: '陷', label: '陷阱'};
      return {cls: 'is-item', glyph: '物', label: '交互物'};
    }

    function mechPanel(m) {
      const SUB = substrate();
      if (!m?.loaded) return '<p class="small-text muted">未载入战斗机制数据，本局只按基础伤害公式结算。</p>';
      const list = o => Object.entries(o || {}).sort((a, b) => b[1] - a[1]);
      const chips = (o, cls) => list(o).map(([k, v]) => `<span class="${cls}">${esc(k)}<b>${fmt(v)}</b></span>`).join('') || '<span class="muted">无</span>';
      const c = m.conditions || {};
      const total = (c.pass || 0) + (c.fail || 0) + (c.unknown || 0);
      return `<details class="bsim-mech"><summary>机制覆盖 · 执行 ${fmt(list(m.executed).reduce((a, [, v]) => a + v, 0))} 次效果 ·
          未执行 ${list(m.skipped).length} 类 · 条件可求值 ${total ? ((1 - (c.unknown || 0) / total) * 100).toFixed(1) : 100}%</summary>
        <p class="small-text muted">被动 / 光环 / 状态效果共 ${fmt(m.passiveEffects)} 条挂在上场单位上；Lua 激活条件判定 ${fmt(total)} 次（通过 ${fmt(c.pass)} / 未通过 ${fmt(c.fail)} / 无法求值 ${fmt(c.unknown)}）。</p>
        <h4>已执行的效果类型</h4><div class="bsim-mech-list">${chips(m.executed, 'is-ok')}</div>
        <h4>未执行的效果类型（本模拟器未实现，不会生效）</h4><div class="bsim-mech-list">${chips(m.skipped, 'is-skip')}</div>
        <h4>无法求值的条件函数 / 字段（相关效果按不满足处理）</h4><div class="bsim-mech-list">${chips(m.luaUnknown, 'is-skip')}</div>
        ${SUB ? `<h4>运行机制基底 · 来自已解密客户端脚本</h4>
          <p class="small-text">${SUB.meta.scriptsDecrypted} 个脚本 / ${fmt(SUB.meta.readableStrings)} 条明文常量导出；
            配置表的 ${SUB.meta.effectTypesDeclared} 类效果里有 <b>${SUB.effectTypes.length}</b> 类在客户端字节码中被直接引用。</p>
          <div class="bsim-mech-list"><span class="is-ok">AI 阶段<b>${SUB.phases.length}</b></span>
            <span class="is-ok">技能标签<b>${SUB.skillTags.length}</b></span>
            <span class="is-ok">选位流水线<b>${SUB.castPipeline.length}</b></span>
            <span class="is-ok">AOE 评分字段<b>${SUB.aoeFields.length}</b></span>
            <span class="is-ok">实时行动顺序<b>${SUB.waitTime.dynamicOrder ? '开' : '关'}</b></span></div>
          <p class="small-text muted">阶段：${SUB.phases.map(esc).join(' → ')}<br>
            选位：${SUB.castPipeline.map(esc).join(' → ')}<br>
            ${result.orderChanges ? `本局因速度变化重排行动顺序 ${fmt(result.orderChanges)} 次。` : '本局未发生速度变化导致的重排。'}</p>` : ''}
        <h4>已解密的客户端脚本</h4>
        <div class="bsim-lua"><button type="button" class="button secondary small" data-lua-load>载入解密索引</button>
          <span class="bsim-lua-stat small-text muted"></span>
          <div class="bsim-lua-body"></div></div>
        </details>`;
    }

    function show(i) {
      if (!result) return;
      cursor = Math.max(0, Math.min(result.steps.length - 1, i));
      const step = result.steps[cursor];
      dynamicBoard(step);
      paintUnits(step);
      paintDetail(step);
      paintPanel(step);
      paintSpawnMarkers(step);   // deployment rings follow the live unit positions
      $('#bsim-range').value = String(cursor);
      $('#bsim-pos').textContent = `${cursor} / ${result.steps.length - 1}`;
      const log = $('#bsim-log');
      log.querySelectorAll('.is-current').forEach(el => el.classList.remove('is-current'));
      const cur = log.querySelector(`[data-step="${cursor}"]`);
      if (cur) {
        cur.classList.add('is-current');
        // Scroll only the log box, never the page.
        const top = cur.offsetTop - log.offsetTop;
        if (top < log.scrollTop || top > log.scrollTop + log.clientHeight - cur.offsetHeight) log.scrollTop = Math.max(0, top - log.clientHeight / 3);
      }
    }

    const pause = () => { clearInterval(timer); timer = null; $('.bsim-toggle').textContent = '▶'; };
    const play = () => {
      if (!result) return;
      if (cursor >= result.steps.length - 1) show(0);
      $('.bsim-toggle').textContent = '❚❚';
      timer = setInterval(() => { if (cursor >= result.steps.length - 1) pause(); else show(cursor + 1); }, Number(setup.interval) || 900);
    };

    // Battle environment: weather aura + (optionally) the loaded 乐土群星杯
    // match's mission buffs (target 1 = team1 → 我方, 2 = team2 → 敌方, 3 = 双方)
    // and per-fighter statuses (unit_status_data).
    function cupEnv(sched, teams) {
      // Shared with every test harness (battle-sim-core.js cupEnv).
      return S.cupEnv(sched, teams);
    }
    function buildEnv(teams = {A: setup.A, B: setup.B}) {
      const env = {weatherId: Number(setup.weather) || 0};
      const sched = setup.cupEnvOn && setup.cupEnvId && (CUP?.schedules || []).find(s => Number(s.id) === Number(setup.cupEnvId));
      if (sched) Object.assign(env, cupEnv(sched, teams));
      return env;
    }
    // One battle configuration, parameterised by seed. Both the single replay
    // and the multi-seed sweep use THIS, so a picked seed replays exactly the
    // same battle that produced the recorded result.
    function battleOpts(seed) {
      const map = mapById.get(String(setup.mapId))?.raw;
      if (!map) return null;
      return {data: D, mech: MECH, map, teams: {A: setup.A, B: setup.B}, mode: setup.mode, seed,
              maxRounds: setup.maxRounds, env: buildEnv(),
              spawns: getSpawnEdit(currentSched()) || undefined,
              skillPriority: setup.skillPriority};
    }
    function run() {
      pause();
      const opts = battleOpts(setup.seed);
      if (!opts) { $('#bsim-detail').innerHTML = '<p>请选择一张地图。</p>'; return; }
      const out = S.simulate(opts);
      if (out.error) {
        result = null;
        $('#bsim-detail').innerHTML = `<p class="bsim-error">${esc(out.error)}</p>`;
        $('#bsim-board').innerHTML = ''; $('#bsim-log').innerHTML = ''; $('#bsim-summary').innerHTML = '';
      $('#bsim-units').innerHTML = ''; $('#bsim-panel').innerHTML = '';
        return;
      }
      result = out;
      $('#bsim-title').textContent = `${out.grid.name} · ${out.grid.w}×${out.grid.h} · 种子 ${setup.seed}${out.mechanics?.weather ? ' · ' + out.mechanics.weather : ''}`;
      $('#bsim-range').max = String(out.steps.length - 1);
      staticBoard();
      paintLog();
      paintSummary();
      show(0);
    }

    const PLAN_FORMAT = 'socwiki-spawn-plan';
    // dir = client-facing vector [dx,dy]; 'auto' keeps the side default.
    function aggregateHits(step) {
      const out = new Map();
      for (const hh of step.hits || []) {
        const prev = out.get(hh.uid);
        if (!prev) { out.set(hh.uid, Object.assign({}, hh)); continue; }
        prev.amount += hh.amount || 0;
        prev.absorbed = (prev.absorbed || 0) + (hh.absorbed || 0);
        prev.crit = prev.crit || !!hh.crit;
        prev.after = hh.after;
        prev.killed = prev.killed || !!hh.killed;
      }
      return out;
    }
    const DIR_NAMES = d => !d ? '默认' : d[0] > 0 ? '东' : d[0] < 0 ? '西' : d[1] > 0 ? '南' : '北';
    // tip = dir * outer, base = dir * inner ± perpendicular * halfWidth.
    // The old spawn marker hard-coded its tip at (0, -0.42*CELL), so choosing
    // 南 drew a north-pointing arrow inside the character circle.
    function facingArrow(d, outer, inner, halfW) {
      const len = Math.hypot(d[0], d[1]) || 1;
      const ux = d[0] / len, uy = d[1] / len, px = -uy, py = ux;
      const P = (a, b) => `${a.toFixed(1)},${b.toFixed(1)}`;
      return `M${P(ux * outer, uy * outer)} L${P(ux * inner + px * halfW, uy * inner + py * halfW)} ` +
             `L${P(ux * inner - px * halfW, uy * inner - py * halfW)} Z`;
    }
    const FACINGS = [['auto', '默认'], ['1,0', '→ 东'], ['-1,0', '← 西'],
                     ['0,1', '↓ 南'], ['0,-1', '↑ 北']];
    const facingKey = v => Array.isArray(v) && v.length === 2 && (v[0] || v[1])
      ? `${v[0]},${v[1]}` : 'auto';
    const facingVec = k => k === 'auto' ? null : k.split(',').map(Number);
    const planMap = id => mapById.get(String(id));
    // Build a portable plan document for the current schedule, or for every
    // saved schedule when `all` is set. Coordinates stay per-map so a plan can
    // be shared without dragging along the whole local setup.
    const planCell = c => {
      if (!c) return null;
      const has = Number.isFinite(c.x) && Number.isFinite(c.y);
      const dir = facingKey(c.dir) !== 'auto' ? c.dir : null;
      if (!has && !dir) return null;
      return {...(has ? {x: c.x, y: c.y} : {}), ...(dir ? {dir} : {})};
    };
    function buildPlan(sched, all = false) {
      const one = s => {
        const ed = getSpawnEdit(s) || {A: [], B: []};
        const mapId = Number(ed.mapId || s.mapId || CUP?.environment?.mapId || setup.mapId);
        return {scheduleId: s.id, mapId, mapName: planMap(mapId)?.label || s.mapName || '',
                A: (ed.A || []).map(planCell),
                B: (ed.B || []).map(planCell),
                formation: {A: (s.formation?.A || []).map(m => m.name),
                            B: (s.formation?.B || []).map(m => m.name)}};
      };
      return {format: PLAN_FORMAT, version: 2,
              exportedAt: new Date().toISOString().slice(0, 10),
              note: '铃兰档案馆 · 初始站位方案；坐标 (x,y) 以地图左上角为原点，dir 为初始朝向 [dx,dy]。',
              plans: all ? (CUP?.schedules || []).filter(s => getSpawnEdit(s)).map(one)
                         : [one(sched)]};
    }
    function validCell(mapId, c) {
      if (c == null) return true;
      // A facing-only entry has no coordinate: the engine keeps its inferred
      // spawn tile but applies the chosen initial facing.
      if (c.x === undefined && c.y === undefined) return true;
      if (!Number.isInteger(c?.x) || !Number.isInteger(c?.y)) return false;
      const raw = planMap(mapId)?.raw;
      const cell = (raw?.cells || []).find(v => v[0] === c.x && v[1] === c.y);
      if (!cell) return false;
      const info = (D.terrain || {})[String(cell[3])];
      const cost = Number(info?.cost ?? 10);
      return !info?.pit && cost > 0 && cost < 1000;
    }
    function applyPlan(doc, sched) {
      if (!doc || doc.format !== PLAN_FORMAT || !Array.isArray(doc.plans)) throw new Error('不是有效的站位方案文件');
      let applied = 0, skipped = 0, firstTarget = null;
      for (const p of doc.plans) {
        const target = p.scheduleId != null && (CUP?.schedules || []).some(s => String(s.id) === String(p.scheduleId))
          ? (CUP.schedules.find(s => String(s.id) === String(p.scheduleId))) : sched;
        if (!target) { skipped++; continue; }
        const mapId = Number(p.mapId || target.mapId || setup.mapId);
        if (!planMap(mapId)) { skipped++; continue; }
        for (const side of ['A', 'B']) {
          const list = Array.isArray(p[side]) ? p[side] : [];
          if (!list.every(c => validCell(mapId, c))) throw new Error(`赛程 ${target.id} 的 ${side} 侧含不可站立坐标`);
          const taken = new Set();
          for (const c of list) if (c && Number.isFinite(c.x) && Number.isFinite(c.y)) {
            const k = `${c.x},${c.y}`;
            if (taken.has(k)) throw new Error(`赛程 ${target.id} 的 ${side} 侧坐标重复：${k}`);
            taken.add(k);
          }
        }
        const dirOf = c => {
          if (!c) return null;
          if (Array.isArray(c.dir)) return c.dir;
          if (typeof c.dir === 'string' || typeof c.dir === 'number') {
            const v = {east: [1, 0], west: [-1, 0], south: [0, 1], north: [0, -1],
                       东: [1, 0], 西: [-1, 0], 南: [0, 1], 北: [0, -1],
                       1: [1, 0], 2: [-1, 0], 3: [0, 1], 4: [0, -1]}[String(c.dir).toLowerCase()];
            return v || null;
          }
          return null;
        };
        const readCell = c => c ? {...(Number.isFinite(c.x) && Number.isFinite(c.y) ? {x: c.x, y: c.y} : {}),
                                    ...(dirOf(c) ? {dir: dirOf(c)} : {})} : {};
        const ed = {A: (p.A || []).map(readCell), B: (p.B || []).map(readCell), mapId};
        setSpawnEdit(target, ed);
        if (!firstTarget) firstTarget = target;
        applied++;
      }
      if (!applied) throw new Error('方案里没有可应用的赛程');
      return {applied, skipped, first: firstTarget};
    }
    function download(name, text, type) {
      const blob = new Blob([text], {type});
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = name;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 800);
    }

    /* ---------- custom fighter editor ---------- */
    const STAT_FIELDS = [['hp', '生命'], ['patk', '物攻'], ['matk', '魔攻'],
                         ['pdef', '物防'], ['mdef', '魔防'], ['spd', '速度']];
    const SKILL_FIELDS = [['name', '技能名', 'text'], ['factor', '倍率 %', 'number'],
                          ['rangeMin', '最小射程', 'number'], ['rangeMax', '最大射程', 'number'],
                          ['cooldown', '冷却', 'number'], ['order', 'AI 优先级', 'number'],
                          ['hits', '段数', 'number']];
    let editing = null;   // {side, index, fighter, dirty}
    // 技能放置顺序: the client `skill_orders` (unit_npc.skill_ids) plus any
    // castable skill missing from the declaration, in the kit's own order.
    const skillSlotRows = f => {
      const declared = ((f.slotOrder && f.slotOrder.length ? f.slotOrder : (f.kit?.skillOrder || []))).map(Number);
      const extra = (f.skills || []).map(s => Number(s.id)).filter(id => id && !declared.includes(id));
      return [...declared, ...extra].filter((id, i, a) => a.indexOf(id) === i).map(id => {
        const own = (f.skills || []).find(s => Number(s.id) === id);
        const rec = MECH?.skills?.[id];
        const desc = rec?.desc || own?.desc || '';
        return {id, name: own?.name || rec?.n || `技能 #${id}`,
                instant: /^[^，。；]{0,18}\[瞬发\]/.test(desc) && !/非\[瞬发\]|\[瞬发\]以外|非瞬发/.test(desc.slice(0, 24)),
                role: own?.role || ''};
      });
    };
    const slotFighter = (side, index) => {
      const slot = setup[side][index];
      if (slot && typeof slot === 'object') return JSON.parse(JSON.stringify(slot));
      const r = byKey.get(slot) || roster[0];
      if (!r) return null;
      return {
        key: r.key, name: r.name, pageId: r.pageId, avatar: r.avatar,
        prof: r.prof, profName: r.profName,
        stats: {...r.stats}, move: {...r.move},
        skills: S.skillSet(r, setup.mode).map(s => ({...s})),
      };
    };
    function editorHtml(f) {
      const slotRows = skillSlotRows(f);
      const stats = STAT_FIELDS.map(([k, label]) => `<label class="bsim-ef"><span>${label}</span>
          <input type="number" data-stat="${k}" value="${f.stats[k] ?? 0}" min="0"></label>`).join('');
      const move = [['mob', '移动'], ['up', '上跳'], ['down', '下跳'], ['type', '移动类型']].map(([k, label]) =>
        `<label class="bsim-ef"><span>${label}</span><input type="number" data-move="${k}" value="${f.move[k] ?? 0}" min="0"></label>`).join('');
      const skills = f.skills.map((s, i) => `<div class="bsim-eskill" data-skill="${i}">
          <div class="bsim-eskill-head"><label><input type="checkbox" data-sk="usable" ${s.usable === false ? '' : 'checked'}> 启用</label>
            <label><input type="checkbox" data-sk="heal" ${s.heal ? 'checked' : ''}> 治疗</label>
            <button type="button" class="text-link" data-skill-del="${i}">删除</button></div>
          <div class="bsim-eskill-grid">${SKILL_FIELDS.map(([k, label, type]) =>
            `<label class="bsim-ef"><span>${label}</span><input type="${type}" data-sk="${k}" value="${esc(s[k] ?? '')}"></label>`).join('')}
            <label class="bsim-ef"><span>射程形状</span><select data-sk="shape">
              <option value="diamond" ${s.shape === 'diamond' ? 'selected' : ''}>菱形</option>
              <option value="cross" ${s.shape === 'cross' ? 'selected' : ''}>十字</option></select></label>
            <label class="bsim-ef"><span>目标</span><select data-sk="aim">${['enemy', 'ally', 'self', 'ground', 'direction', 'other'].map(a =>
              `<option value="${a}" ${s.aim === a ? 'selected' : ''}>${a}</option>`).join('')}</select></label>
            <label class="bsim-ef"><span>范围</span><select data-sk="areaType">
              <option value="single" ${s.area?.type !== 'radius' && s.area?.type !== 'rect' ? 'selected' : ''}>单体</option>
              <option value="radius" ${s.area?.type === 'radius' ? 'selected' : ''}>周围 N 格</option>
              <option value="rect" ${s.area?.type === 'rect' ? 'selected' : ''}>朝向矩形</option></select></label>
            <label class="bsim-ef"><span>范围值</span><input type="number" data-sk="areaValue" min="1" value="${s.area?.r ?? s.area?.len ?? 1}"></label>
          </div></div>`).join('');
      return `<div class="bsim-editor-sec"><h3>基础信息</h3>
          <label class="bsim-ef"><span>名称</span><input type="text" data-basic="name" value="${esc(f.name)}"></label>
          <label class="bsim-ef"><span>职业</span><select data-basic="prof">${Object.entries(D.categories || {6: '无属性'}).map(([k, v]) =>
            `<option value="${k}" ${Number(f.prof) === Number(k) ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select></label></div>
        <div class="bsim-editor-sec"><h3>六维属性</h3><div class="bsim-ef-grid">${stats}</div></div>
        <div class="bsim-editor-sec"><h3>移动</h3><div class="bsim-ef-grid">${move}</div></div>
        <div class="bsim-editor-sec"><h3>技能 <button type="button" class="button secondary small" data-skill-add>＋ 添加技能</button></h3>
          ${skills || '<p class="small-text muted">没有技能，点「添加技能」新建一个。</p>'}</div>
        <div class="bsim-editor-sec"><h3>技能放置顺序 <small class="muted">同优先级时靠前的先放</small></h3>
          ${slotRows.length ? `<div class="bsim-slot-list">${slotRows.map((r, i) =>
            `<div class="bsim-slot-row"><span class="bsim-slot-idx">${i + 1}</span>
              <b>${esc(r.name)}</b><small>#${r.id}${r.role ? ` · ${esc(r.role)}` : ''}${r.instant ? ' · [瞬发]' : ''}</small>
              <span class="bsim-slot-move">
                <button type="button" class="button secondary small" data-slot-up="${i}" ${i === 0 ? 'disabled' : ''} title="上移">↑</button>
                <button type="button" class="button secondary small" data-slot-down="${i}" ${i === slotRows.length - 1 ? 'disabled' : ''} title="下移">↓</button>
              </span></div>`).join('')}</div>
            <p class="small-text muted">来自客户端 <code>skill_orders</code>（unit_npc.skill_ids）。调整后只改变同优先级携带技能的先后顺序，
              不改动倍率 / 射程等客户端技能数据；个性技能、普攻仍有各自的分组优先级。</p>`
            : '<p class="small-text muted">这个角色还没有可调整的技能槽。</p>'}</div>`;
    }
    function readEditor(f) {
      const body = $('#bsim-editor-body');
      body.querySelectorAll('[data-basic]').forEach(el => {
        const k = el.dataset.basic;
        f[k] = k === 'prof' ? Number(el.value) : el.value.trim() || f[k];
      });
      f.profName = (D.categories || {})[f.prof] || '自定义';
      body.querySelectorAll('[data-stat]').forEach(el => { f.stats[el.dataset.stat] = Math.max(0, Number(el.value) || 0); });
      body.querySelectorAll('[data-move]').forEach(el => { f.move[el.dataset.move] = Math.max(0, Number(el.value) || 0); });
      f.skills = [...body.querySelectorAll('.bsim-eskill')].map((box, i) => {
        const s = {...(f.skills[i] || {id: 'c' + Date.now() + i, name: '新技能', heal: false,
                    ignoreDef: false, damageType: 1, attackUp: 0, attackDown: 0, order: 0,
                    hits: 1, cooldown: 0, rangeMin: 0, rangeMax: 1, shape: 'diamond', aim: 'enemy',
                    area: {type: 'single'}, factor: 100})};
        box.querySelectorAll('[data-sk]').forEach(el => {
          const k = el.dataset.sk;
          if (k === 'usable' || k === 'heal') s[k] = el.checked;
          else if (k === 'name' || k === 'shape' || k === 'aim') s[k] = el.value;
          else if (k === 'areaType') {
            const v = Number(box.querySelector('[data-sk="areaValue"]')?.value || 1);
            s.area = el.value === 'radius' ? {type: 'radius', r: Math.max(1, v)}
                   : el.value === 'rect' ? {type: 'rect', len: Math.max(1, v), wide: 3}
                   : {type: 'single'};
          } else if (k !== 'areaValue') s[k] = Number(el.value) || 0;
        });
        s.usable = s.usable !== false;
        return s;
      });
      return f;
    }
    function openEditor(side, index) {
      const f = slotFighter(side, index);
      if (!f) return;
      editing = {side, index, fighter: f, dirty: false};
      $('#bsim-editor-title').textContent = `自定义角色 · ${SIDE[side]} ${index + 1}`;
      $('#bsim-editor-hint').textContent = '调整「技能放置顺序」只改同优先级携带技能的先后，不改客户端技能数据；修改倍率 / 射程等才会按自定义技能结算。角色自身的被动 / 个性 / 特性效果仍会在开局按客户端规则叠加。';
      $('#bsim-editor-body').innerHTML = editorHtml(f);
      $('#bsim-editor').showModal();
    }
    function commitEditor() {
      if (!editing) return;
      const f = readEditor(editing.fighter);
      if (!(f.stats.hp > 0)) { h.toast?.('生命必须大于 0'); return; }
      // A pure slot reorder is NOT a fighter edit: keep the client kit so all
      // specialities / AI hints stay in effect. Only an actual stat or skill
      // field change (or a fighter without a kit) becomes a legacy edit.
      f.edited = !!(editing.dirty || !f.kit);
      setup[editing.side][editing.index] = f;
      $('#bsim-editor').close();
      editing = null;
      paintTeams(); save(); run();
    }

    /* ---------- 乐土群星杯 presets ---------- */
    const cupScheds = () => {
      const act = Number($('#bsim-cup-act')?.value || CUP?.activities?.[0]?.id || 0);
      return (CUP?.schedules || []).filter(s => Number(s.activityId) === act);
    };
    const paintCup = () => {
      if (!CUP) return;
      const sel = $('#bsim-cup-sched');
      if (!sel) return;
      const list = cupScheds();
      sel.innerHTML = list.map(s => `<option value="${s.id}" ${Number(setup.cupId) === Number(s.id) ? 'selected' : ''}>${esc(s.name)} · ${esc(s.team1)} vs ${esc(s.team2)}</option>`).join('');
      if (!list.some(s => Number(s.id) === Number(setup.cupId))) setup.cupId = list[0]?.id || 0;
      sel.value = String(setup.cupId);
      const cur = list.find(s => Number(s.id) === Number(setup.cupId));
      const info = $('#bsim-cup-info');
      if (!info) return;
      if (!cur) { info.innerHTML = '<p class="small-text muted">这一期没有可用赛程。</p>'; return; }
      const t1 = cupTeamById.get(cur.team1Id), t2 = cupTeamById.get(cur.team2Id);
      const odds = (CUP.bets || []).slice(0, 2).map(b => `${esc(b.name || '押注')} 胜赔 ${b.options?.[0]?.winOdds ?? '—'}`).join('；');
      const quest = cur.quest || {};
      const buffs = cur.buffDetails || [];
      const statuses = cur.unitStatus || [];
      info.innerHTML = `<div class="bsim-cup-match"><strong>${esc(t1?.name || cur.team1)}</strong><em>vs</em><strong>${esc(t2?.name || cur.team2)}</strong></div>
        <p class="small-text">第 ${cur.day} 天 · 分组 ${cur.group} · ${esc(cur.modeName || '')} · 我方 ${t1?.members.length || 0} 人 / 敌方 ${t2?.members.length || 0} 人</p>
        <p class="small-text">赛程关卡：<b>${esc(quest.name || '未关联')}</b>（id ${quest.id || '—'}${quest.level ? ` · ${quest.level} 级` : ''}）${quest.turnLimit ? ` · 关卡回合上限 ${quest.turnLimit}` : ''}${cur.roundCount ? ` · 赛制 ${cur.roundCount} 轮` : ''}</p>
        <p class="small-text">对战地图：<b>${esc(cur.mapName || CUP.environment?.mapName || '未推定')}</b>
          （#${cur.mapId || CUP.environment?.mapId || '—'} · ${esc(cur.mapSource || '推定')}）·
          我方 ${cur.formation?.A?.length || 0} 人 / 敌方 ${cur.formation?.B?.length || 0} 人</p>
        <p class="small-text muted">客户端赛程表只有 mission_id（剧情关卡），不存战斗地图 id 与出生点；
          下方「本场地图与初始站位」可逐格指定每位选手的坐标。</p>
        ${quest.scenario ? `<p class="small-text muted">${esc(quest.scenario)}</p>` : ''}
        ${buffs.length ? `<p class="small-text muted">赛事增益：${buffs.map(b => `${esc(b.name)}${b.effect ? `（${esc(b.effect)}）` : ''}`).join('；')}</p>` : ''}
        ${statuses.length ? `<p class="small-text muted">选手状态：${statuses.map(s => `[${s.teamIndex === 1 ? '我方' : '敌方'}] ${esc(s.name)}（${esc(s.effect)}）`).join('；')}</p>` : ''}
        ${odds ? `<p class="small-text muted">押注参考：${odds}（不参与模拟）</p>` : ''}
        <p class="small-text muted">官方逐场胜负 / 持续回合数未公开：比赛由服务器结算并只提供游戏内回放，
          下方是本模拟器按客户端阵容与技能做的可复现推演，<b>不是官方赛果</b>。</p>`;
      paintCupRoster(t1, t2);
    };
    // Per-match formation editor. The client doesn't store cup spawn tiles,
    // so any coordinate here is a user override; the engine validates it and
    // falls back to its own anchors for illegal / occupied cells.
    const currentSched = () => (CUP?.schedules || []).find(s => Number(s.id) === Number(setup.cupId))
      || CUP?.schedules?.[0] || null;
    const spawnKey = sched => `s${sched?.id || 0}`;
    const getSpawnEdit = sched => (setup.spawns || {})[spawnKey(sched)] || null;
    const setSpawnEdit = (sched, val) => {
      setup.spawns = setup.spawns || {};
      if (val) setup.spawns[spawnKey(sched)] = val;
      else delete setup.spawns[spawnKey(sched)];
    };
    // "Pick on map" mode: instead of typing x/y, the user clicks a fighter's
    // row then clicks a board tile. Works in both 2D and 3D (both cell
    // renderers expose data-x / data-y).
    let spawnPick = null;   // {side, idx} — transient, never persisted
    const writeSpawnCell = (side, idx, x, y) => {
      const sched = currentSched();
      if (!sched) return;
      const prev = getSpawnEdit(sched) || {A: [], B: []};
      prev[side] = prev[side] || [];
      prev[side][idx] = Object.assign({}, prev[side][idx] || {}, {x, y});
      prev.A = prev.A || []; prev.B = prev.B || [];
      setSpawnEdit(sched, prev);
    };
    const clearSpawnCell = (side, idx) => {
      const sched = currentSched();
      if (!sched) return;
      const prev = getSpawnEdit(sched);
      if (!prev) return;
      if (prev[side]) delete prev[side][idx];
      setSpawnEdit(sched, prev);
    };
    const setSpawnPick = (side, idx) => {
      spawnPick = side === null ? null : {side, idx};
      const board = $('#bsim-board');
      board?.classList.toggle('is-spawn-picking', !!spawnPick);
      paintSpawnEditor();
    };
    const spawnMarkers = (step) => {
      const sched = currentSched();
      const edit = getSpawnEdit(sched);
      // During replay the numbered deployment rings belong to the UNITS, not
      // to their starting tiles: follow each unit's live position. Only the
      // spawn editor (no step) shows the declared deployment cells, so a
      // moved unit never leaves a "kernel circle" behind on its old tile.
      const live = (step && !spawnPick)
        ? new Map((step.snap || []).filter(s => s.alive).map(s => [s.uid, s])) : null;
      const out = [];
      for (const side of ['A', 'B']) {
        const list = edit?.[side] || [];
        list.forEach((p, i) => {
          if (!p || !Number.isFinite(p.x) || !Number.isFinite(p.y)) return;
          const uid = `${side}${i + 1}`;
          const at = live?.get(uid);
          if (live && !at) return;                 // unit gone: no ghost ring
          out.push({side, i, x: at ? at.x : p.x, y: at ? at.y : p.y,
                    dir: p.dir || null, uid,
                    name: sched?.formation?.[side]?.[i]?.name || uid});
        });
      }
      return out;
    };
    const paintSpawnMarkers = (step) => {
      const marks = spawnMarkers(step);
      const dyn = $('#bsim-dyn');
      if (dyn) {
        dyn.querySelectorAll('.bsim-spawn-mark').forEach(n => n.remove());
        if (!marks.length) return;
        dyn.insertAdjacentHTML('beforeend', marks.map(m => {
          const cx = m.x * CELL + CELL / 2, cy = m.y * CELL + CELL / 2;
          return `<g class="bsim-spawn-mark side-${m.side}${spawnPick?.side === m.side && spawnPick?.idx === m.i ? ' is-active' : ''}" transform="translate(${cx},${cy})">
            <title>${esc(m.name)} · (${m.x},${m.y})${m.dir ? ` · 朝向 ${DIR_NAMES(m.dir)}` : ''}</title>
            <circle r="${CELL * 0.33}"/><text y="3">${esc(m.side)}${m.i + 1}</text>
            ${m.dir ? `<path class="bsim-facing-arrow" d="${facingArrow(m.dir, CELL * 0.46, CELL * 0.19, CELL * 0.13)}"/>` : ''}</g>`;
        }).join(''));
      }
      const dyn3 = $('#bsim3-dyn');
      if (dyn3) {
        $('#bsim-board')?.querySelectorAll('.bsim3-spawn').forEach(n => n.remove());
        for (const m of marks) {
          const cell = $('#bsim-board')?.querySelector(`.world-iso-cell[data-x="${m.x}"][data-y="${m.y}"] .world-iso-top`);
          if (cell) {
            const b = document.createElement('b');
            b.className = `bsim3-spawn side-${m.side}${spawnPick?.side === m.side && spawnPick?.idx === m.i ? ' is-active' : ''}`;
            b.textContent = `${m.side}${m.i + 1}`;
            b.title = `${m.name} · (${m.x},${m.y})${m.dir ? ` · 朝向 ${m.dir[0] > 0 ? '东' : m.dir[0] < 0 ? '西' : m.dir[1] > 0 ? '南' : '北'}` : ''}`;
            if (m.dir) b.dataset.dir = m.dir.join(',');
            cell.appendChild(b);
          }
        }
      }
    };
    const paintSpawnEditor = () => {
      const box = $('#bsim-spawn-body');
      if (!box || !CUP) return;
      const sched = currentSched();
      if (!sched) { box.innerHTML = '<p class="small-text muted">没有赛程。</p>'; return; }
      const edit = getSpawnEdit(sched);
      const map = mapById.get(String(edit?.mapId || sched.mapId || CUP.environment?.mapId || setup.mapId))?.raw;
      const cells = (map?.cells || []).filter(c => walkable(c[0], c[1], c[3]));
      const valid = new Set(cells.map(c => `${c[0]},${c[1]}`));
      const rows = (side, members, label) => `<h4 class="bsim-side-${side}">${label}</h4>
        <div class="bsim-spawn-rows">${members.map((m, i) => {
          const v = edit?.[side]?.[i] || {};
          const has = Number.isFinite(v.x) && Number.isFinite(v.y);
          const ok = has ? valid.has(`${v.x},${v.y}`) : false;
          const picking = spawnPick?.side === side && spawnPick?.idx === i;
          return `<div class="bsim-spawn-row ${has ? (ok ? 'is-ok' : 'is-bad') : ''}${picking ? ' is-picking' : ''}">
            <span title="npc #${m.npcId}">${esc(m.name)}</span>
            <button type="button" class="button secondary small bsim-spawn-pick" data-spawn-pick="${side}:${i}"
              title="点击后在地图上选择格子">${picking ? '正在点选…' : has ? '重新点选' : '地图点选'}</button>
            <code class="bsim-spawn-coord">${has ? `(${v.x}, ${v.y})` : '自动'}</code>
            <select class="bsim-spawn-dir" data-spawn-dir="${side}:${i}" title="初始朝向：决定雪人、召唤物等生成在角色正前方">
              ${FACINGS.map(([k, label]) => `<option value="${k}" ${facingKey(v.dir) === k ? 'selected' : ''}>${label}</option>`).join('')}
            </select>
            <small>${has ? (ok ? '可站立' : '不可站立') : '推定'}</small>
            ${has ? `<button type="button" class="bsim-spawn-clear" data-spawn-clear-one="${side}:${i}" title="恢复自动站位">×</button>` : ''}
          </div>`;
        }).join('')}</div>`;
      const pickingName = spawnPick
        ? (sched.formation?.[spawnPick.side]?.[spawnPick.idx]?.name || `${spawnPick.side}${spawnPick.idx + 1}`)
        : '';
      box.innerHTML = `${spawnPick ? `<div class="bsim-pick-hint"><b>正在为「${esc(pickingName)}」选择初始格子</b>
          <span>在下方地图上点一个可站立的格子；按 Esc 或再点一次按钮取消。</span>
          <button type="button" class="button secondary small" data-spawn-pick-cancel>取消点选</button></div>` : ''}
        <p class="small-text">本场推定地图「${esc(sched.mapName || CUP.environment?.mapName || '')}」
          （${esc(sched.mapSource || '推定')}）。${esc(sched.formation?.spawnSource || '')}</p>
        <label class="tool-field"><span>改用地图</span><select id="bsim-spawn-map">
          ${maps.filter(m => m.cells >= 40).map(m => `<option value="${m.id}" ${String(m.id) === String(edit?.mapId || sched.mapId || setup.mapId) ? 'selected' : ''}>${esc(m.label)}</option>`).join('')}
        </select></label>
        <div class="bsim-spawn-grid">${rows('A', sched.formation?.A || [], '我方')}${rows('B', sched.formation?.B || [], '敌方')}</div>
        <p class="small-text muted">点「地图点选」后在棋盘上直接选格；<b>初始朝向</b>决定「自己身前」类交互物与召唤物的生成格
          （如乌莉娅的雪人、伊南娜的王女卫兵）。未指定的选手使用引擎推定的站位与朝向。
          坐标必须落在可站立格且不与他人重叠，非法值会自动回退。
          ${CUP.facing ? `朝向线索：${esc(CUP.facing.source)}` : ''}</p>
        <div class="bsim-cup-actions"><button type="button" class="button secondary small" data-spawn-apply>应用站位并重算</button>
          <button type="button" class="button secondary small" data-spawn-clear>清除自定义站位</button></div>
        <div class="bsim-plan-io"><span class="small-text muted">站位方案（按地图 / 赛程保存）：</span>
          <button type="button" class="button secondary small" data-plan="export">导出本场</button>
          <button type="button" class="button secondary small" data-plan="export-all">导出全部方案</button>
          <button type="button" class="button secondary small" data-plan="import">导入方案…</button>
          <button type="button" class="button secondary small" data-plan="copy">复制到剪贴板</button>
          <input type="file" id="bsim-plan-file" accept=".json,application/json">
          <span class="small-text muted" id="bsim-plan-msg"></span></div>`;
    };
    const skillLine = s => {
      const meta = [
        esc(s.role),
        s.clientRole ? `<i class="bsim-skill-kind k${s.clientType}">${esc(s.clientRole)}</i>` : '',
        s.factor ? `${s.factor}%` : '',
        s.rangeMax ? `射程${s.rangeMin}-${s.rangeMax}` : '',
        s.tp ? `能量${s.tp}` : '',
        s.chainFrom ? `链自 #${s.chainFrom}` : '',
      ].filter(Boolean).join(' · ');
      const tip = [s.desc, s.editorName, s.specTypes?.length ? `效果：${s.specTypes.join('、')}（${s.specCount} 条）` : '',
                   s.tags?.length ? `标签：${s.tags.join('、')}` : ''].filter(Boolean).join('\n');
      return `<span class="bsim-cup-skill${s.simulated ? ' is-sim' : ''}${s.chainFrom ? ' is-chain' : ''}${s.notApplied ? ' is-not-applied' : ''}" title="${esc([tip, s.notApplied].filter(Boolean).join('\n'))}">
        ${esc(s.name)}${s.notApplied ? '<i class="bsim-skill-na">未生效</i>' : ''}<small>${meta}</small>${s.specTypes?.length ? `<em class="bsim-skill-spec">${esc(s.specTypes.slice(0, 2).join('·'))}${s.specCount > 2 ? `+${s.specCount - 2}` : ''}</em>` : ''}</span>`;
    };
    const skillGroups = list => {
      const order = ['普攻', '主动技能', '抉择选项', '被动技能', '反应技', '队长技', '个性', '个性（精英补正）',
                     '附属被动', '连携技能', '施放技能', '替换技能', '衍生技能', '派生技能'];
      const groups = new Map();
      for (const s of list) {
        if (!groups.has(s.role)) groups.set(s.role, []);
        groups.get(s.role).push(s);
      }
      return [...groups.entries()].sort((a, b) => {
        const ia = order.indexOf(a[0]), ib = order.indexOf(b[0]);
        return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
      }).map(([role, ss]) => `<div class="bsim-cup-skill-group"><b>${esc(role)}</b><span class="muted">${ss.length}</span>
        <div class="bsim-cup-skills">${ss.map(skillLine).join('')}</div></div>`).join('');
    };
    const paintCupRoster = (t1, t2) => {
      const box = $('#bsim-cup-roster');
      if (!box) return;
      const teamHtml = (team, side) => `<h4 class="bsim-side-${side}">${esc(team?.name || '')}
          <small>${(team?.members || []).length} 名选手</small></h4>
        ${(team?.members || []).map(m => `<details class="bsim-cup-unit"><summary>${esc(m.name)}
            <small>${m.personality ? esc(m.personality) + ' · ' : ''}生命 ${fmt(m.stats.hp)} · 速度 ${m.stats.spd} · ${m.allSkills.length} 技能</small></summary>
          <div class="bsim-cup-unit-body">
            <p class="small-text">${m.editorName ? `来源：${esc(m.editorName)} · ` : ''}60 级成长表：生命 ${fmt(m.stats.hp)} / 物攻 ${fmt(m.stats.patk)} / 魔攻 ${fmt(m.stats.matk)} / 物防 ${fmt(m.stats.pdef)} / 魔防 ${fmt(m.stats.mdef)} / 速度 ${m.stats.spd}</p>
            ${m.statSource ? `<details class="bsim-stat-src"><summary>基础值来源与口径</summary>
              <p class="small-text">unit_npc.unit_modify_id <b>${m.statSource.modifyId}</b>（${esc(m.statSource.modifyName)}）· 等级 <b>${m.statSource.level}</b> 的 unit_modify_level 行：
                生命 ${fmt(m.statSource.row.hp)} / 物攻 ${fmt(m.statSource.row.physic_attack)} / 魔攻 ${fmt(m.statSource.row.spell_attack)} /
                物防 ${fmt(m.statSource.row.physic_defence)} / 魔防 ${fmt(m.statSource.row.spell_defence)}。</p>
              <p class="small-text muted">${esc(m.statSource.note)}<br>
                unit 表自身基础：物攻 ${fmt(m.statSource.unitBase.physic_attack)} · 玩家模板成长表 #${m.statSource.unitModifyId} 未用于赛事选手。
                客户端 unit_rarity.base_attribute_adjust 可选倍率：${Object.entries(m.statSource.rarityAdjust || {}).map(([k, v]) => `${k}:${v}%`).join(' / ')}（赛事未启用）。
                如游戏内物攻显示 2388 且为红色，说明真实基础值高于该数值；当前导出的 ${fmt(m.stats.patk)} 是成长表原值，可据此核对口径。</p></details>` : ''}
            <p class="small-text muted">移动 ${m.move.mob} · 上跳 ${m.move.up} / 下跳 ${m.move.down} · 个性 ${esc(m.personality || '—')} · ${m.aiByOrder ? '按序放技能' : 'AI 评分放技能'}</p>
            <p class="small-text muted">客户端技能编组：普攻 #${m.kit.basic} · 主动 ${m.kit.actives.length} · 抉择选项 ${(m.kit.choice || []).length}
              · 反应 ${m.kit.reactive.length} · 个性 ${m.kit.personality.length}（${m.star} 星）· 技能链 ${(m.kit.chain || []).length}
              · 效果派生 ${(m.kit.derived || []).length}${m.kit.aiByOrder ? ' · 按序放技能' : ''}</p>
            ${(m.referenceSlots || []).length ? `<p class="small-text bsim-ref-slots"><b>同角色玩家版技能槽（仅对照，不并入赛事编组）</b>：
              ${m.referenceSlots.map(row => row.map(esc).join(' / ')).join('；')}</p>` : ''}
            ${skillGroups(m.allSkills)}
          </div></details>`).join('')}`;
      box.innerHTML = teamHtml(t1, 'A') + teamHtml(t2, 'B');
    };
    // Shared with every test harness (battle-sim-core.js cupFighters), so the
    // acceptance suite validates exactly the battle the page shows.
    const cupMembers = team => S.cupFighters(team, {eliteComp: setup.eliteComp});
    const loadCup = which => {
      const cur = (CUP?.schedules || []).find(s => Number(s.id) === Number(setup.cupId));
      if (!cur) { h.toast?.('请先选择一场赛程'); return; }
      const t1 = cupTeamById.get(cur.team1Id), t2 = cupTeamById.get(cur.team2Id);
      if (which === 'both' || which === 'A') setup.A = cupMembers(t1);
      if (which === 'both' || which === 'B') setup.B = cupMembers(t2);
      setup.cupEnvId = cur.id;
      if (CUP.environment?.weatherId) { setup.weather = CUP.environment.weatherId; const w = $('#bsim-weather'); if (w) w.value = String(setup.weather); }
      const spawnEdit = getSpawnEdit(cur);
      const chosen = Number(spawnEdit?.mapId || $('#bsim-cup-map')?.value || cur.mapId || CUP.environment?.mapId || 0);
      if (chosen && mapById.has(String(chosen))) {
        setup.mapId = chosen;
        $('#bsim-map').value = String(chosen);
        paintMaps();
      }
      save(); paintTeams(); run();
    };

    /* ---------- 乐土群星杯：可复现推演（非官方赛果） ----------
       The client ships schedules/teams/buffs but not results; servers settle
       each match and only expose an in-game replay. We therefore run the SAME
       simulation engine with a fixed seed and publish winner + rounds here,
       clearly labelled as an offline prediction. */
    const predictionMap = () => W.maps?.find(m => String(m.id) === String($('#bsim-cup-map')?.value || ''))
      || W.maps?.find(m => String(m.id) === String(CUP?.environment?.mapId || CUP?.arenaMaps?.[0]?.id || ''))
      || mapById.get(String(setup.mapId))?.raw;
    const predictOne = (sched, map) => {
      if (!CUP || !sched || !map) return null;
      const a = cupTeamById.get(sched.team1Id), b = cupTeamById.get(sched.team2Id);
      if (!a || !b) return null;
      const teams = {A: cupMembers(a), B: cupMembers(b)};
      const env = Object.assign({weatherId: CUP.environment?.weatherId || 0}, setup.cupEnvOn ? cupEnv(sched, teams) : {});
      const spawnEdit = getSpawnEdit(sched);
      const opts = {data: D, mech: MECH, map, teams, env,
        mode: setup.mode, seed: 1000 + Number(sched.id), maxRounds: 20,
        spawns: spawnEdit || undefined};
      let r = S.simulate(opts);
      if (r.error) {
        // Some arena maps have a walkable component too small for 7v7; retry
        // on the largest playable client map so every scheduled match is
        // still covered (the chosen map is recorded in the result).
        const fallback = (W.maps || []).filter(m => (m.cells || []).length > (map.cells || []).length
            && (m.cells || []).length <= 500)
          .sort((x, y) => y.cells.length - x.cells.length)[0];
        if (fallback) { map = fallback; r = S.simulate({...opts, map}); }
      }
      if (r.error) return {error: r.error};
      return {
        id: sched.id, name: sched.name, day: sched.day,
        team1: a.name, team2: b.name,
        winner: r.winner, rounds: r.rounds, actions: r.steps.length - 2,
        verdict: r.verdict, map: map.id, mapName: (map.stages || [])[0] || map.name,
        survivorA: r.summary.filter(u => u.side === 'A' && u.alive).length,
        survivorB: r.summary.filter(u => u.side === 'B' && u.alive).length,
        damageA: r.summary.filter(u => u.side === 'A').reduce((x, u) => x + u.dealt, 0),
        damageB: r.summary.filter(u => u.side === 'B').reduce((x, u) => x + u.dealt, 0),
      };
    };
    const renderPredictions = (rows, note) => {
      const box = $('#bsim-cup-result');
      if (!box) return;
      if (!rows.length) { box.innerHTML = '<p class="small-text muted">没有可推演的赛程。</p>'; return; }
      const win = r => r.winner === 'draw' ? '平局' : (r.winner === 'A' ? esc(r.team1) : esc(r.team2));
      box.innerHTML = `<div class="bsim-pred-head"><strong>离线推演结果</strong>
          <span>${esc(note)} · 固定种子 1000+场次 id · <b>非官方赛果</b></span></div>
        <div class="bsim-pred-scroll"><table class="data-table bsim-pred-table"><thead><tr>
          <th>场次</th><th>对阵</th><th>推演胜方</th><th>持续回合</th><th>行动数</th><th>输出 我/敌</th><th>存活 我/敌</th></tr></thead>
        <tbody>${rows.map(r => `<tr><td>${esc(r.name)}</td>
          <td>${esc(r.team1)} vs ${esc(r.team2)}</td>
          <td class="bsim-side-${r.winner === 'B' ? 'B' : 'A'}">${win(r)}</td>
          <td>${r.rounds}</td><td>${r.actions}</td>
          <td>${fmt(r.damageA)} / ${fmt(r.damageB)}</td>
          <td>${r.survivorA} / ${r.survivorB}</td></tr>`).join('')}</tbody></table></div>`;
    };
    const predictCup = which => {
      if (!CUP) return;
      let map = predictionMap();
      const cur = currentSched();
      const curMap = cur && getSpawnEdit(cur)?.mapId;
      if (curMap && mapById.has(String(curMap))) map = mapById.get(String(curMap)).raw;
      if (!map) { h.toast?.('请先选择一张赛事地图'); return; }
      const list = which === 'all' ? (CUP.schedules || [])
        : (CUP.schedules || []).filter(s => Number(s.id) === Number(setup.cupId));
      const box = $('#bsim-cup-result');
      if (box) box.innerHTML = `<p class="small-text muted">正在推演 ${list.length} 场…</p>`;
      // Chunk with rAF so a full 192-match sweep never freezes the page.
      const rows = [];
      let i = 0;
      const step = () => {
        const end = Math.min(list.length, i + 4);
        for (; i < end; i++) {
          const r = predictOne(list[i], map);
          if (r && !r.error) rows.push(r);
        }
        renderPredictions(rows, `${rows.length}/${list.length} 场 · 地图 ${(map.stages || [])[0] || map.name}`);
        if (i < list.length) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    };

    /* ---------- multi-seed sweep (同场对局 × 不同随机数) ------------------ */
    // Each row is a FULL battle with a different seed. Results are kept in
    // `batchRows`; clicking 观看 sets setup.seed and replays that exact match.
    let batchRows = [], batchFilter = 'all', batchRunning = false;
    const renderBatch = (done = 0, total = 0) => {
      const box = $('#bsim-batch-result');
      if (!box) return;
      const n = batchRows.length;
      const count = w => batchRows.filter(r => r.winner === w).length;
      const a = count('A'), b = count('B'), d = count('draw');
      const pct = v => n ? (v * 100 / n).toFixed(1) + '%' : '—';
      const shown = batchFilter === 'all' ? batchRows : batchRows.filter(r => r.winner === batchFilter);
      const name = w => w === 'draw' ? '平局' : w === 'A' ? '我方胜' : '敌方胜';
      box.innerHTML = `<div class="bsim-batch-head">
          <strong>${batchRunning ? `模拟中 ${done}/${total}` : `完成 ${n} 场`}</strong>
          <span>我方胜率 <b class="bsim-side-A">${pct(a)}</b>（${a}） ·
            敌方胜率 <b class="bsim-side-B">${pct(b)}</b>（${b}） · 平局 ${d}（${pct(d)}）</span></div>
        <div class="bsim-batch-scroll"><table class="data-table bsim-batch-table"><thead><tr>
          <th>随机种子</th><th>结果</th><th>回合</th><th>行动</th><th>输出 我/敌</th><th>存活 我/敌</th><th></th></tr></thead>
          <tbody>${shown.length ? shown.map(r => `<tr data-seed="${r.seed}">
            <td><code>${r.seed}</code></td>
            <td class="bsim-side-${r.winner === 'B' ? 'B' : 'A'}">${name(r.winner)}</td>
            <td>${r.rounds}</td><td>${r.actions}</td>
            <td>${fmt(r.damageA)} / ${fmt(r.damageB)}</td>
            <td>${r.survivorA} / ${r.survivorB}</td>
            <td><button type="button" class="button secondary small" data-batch-watch="${r.seed}">观看</button></td>
            </tr>`).join('') : `<tr><td colspan="7" class="muted">${batchRunning ? '正在模拟…' : '暂无结果，点「开始批量模拟」'}</td></tr>`}</tbody></table></div>`;
    };
    const runBatch = () => {
      if (batchRunning) return;
      const box = $('#bsim-batch-result');
      if (!box) return;
      // Derive a deterministic spread of seeds from the current one so the
      // sweep is reproducible and never reuses the exact same RNG stream.
      const n = Math.max(2, Math.min(200, Number($('#bsim-batch-n')?.value) || 20));
      const base = Math.abs(Math.floor(Number(setup.seed) || 1));
      const seeds = Array.from({length: n}, (_, i) => base + i * 7919 + 1);
      batchRows = []; batchRunning = true;
      let i = 0;
      const step = () => {
        const end = Math.min(seeds.length, i + 2);
        for (; i < end; i++) {
          const seed = seeds[i];
          const opts = battleOpts(seed);
          if (!opts) { batchRunning = false; renderBatch(); return; }
          let r;
          try { r = S.simulate(opts); } catch (e) { r = {error: e.message}; }
          if (r.error) { batchRows.push({seed, winner: 'error', rounds: 0, actions: 0,
            damageA: 0, damageB: 0, survivorA: 0, survivorB: 0, error: r.error}); continue; }
          const sum = r.summary || [];
          batchRows.push({seed, winner: r.winner || 'draw', rounds: r.rounds || 0,
            actions: Math.max(0, (r.steps || []).length - 2),
            damageA: sum.filter(u => u.side === 'A').reduce((x, u) => x + u.dealt, 0),
            damageB: sum.filter(u => u.side === 'B').reduce((x, u) => x + u.dealt, 0),
            survivorA: sum.filter(u => u.side === 'A' && u.alive).length,
            survivorB: sum.filter(u => u.side === 'B' && u.alive).length});
        }
        renderBatch(Math.min(i, seeds.length), seeds.length);
        if (i < seeds.length) requestAnimationFrame(step);
        else { batchRunning = false; renderBatch(seeds.length, seeds.length); }
      };
      renderBatch(0, seeds.length);
      requestAnimationFrame(step);
    };
    const watchSeed = seed => {
      setup.seed = Math.abs(Math.floor(Number(seed) || 1));
      $('#bsim-seed').value = setup.seed;
      save(); paintSetupSummary(); run();
      $('#bsim-title')?.scrollIntoView({behavior: 'smooth', block: 'start'});
    };

    /* ---------- wiring ---------- */
    const controller = new AbortController();
    const on = (el, ev, fn) => el.addEventListener(ev, fn, {signal: controller.signal});
    $('#bsim-mode').value = setup.mode;
    $('#bsim-rounds').value = setup.maxRounds;
    $('#bsim-seed').value = setup.seed;
    if ($('#bsim-weather')) $('#bsim-weather').value = String(setup.weather || 0);
    $('#bsim-interval').value = String(setup.interval);
    $('#bsim-heights').checked = !!setup.heights;
    $('#bsim-coords').checked = !!setup.coords;
    $('#bsim-alert-range').checked = setup.alertRange !== false;
    paintMaps();
    paintTeams();
    renderBatch();
    for (const b of root.querySelectorAll('[data-batch-filter]'))
      b.classList.toggle('is-active', b.dataset.batchFilter === 'all');

    // Progressive disclosure: opening a nested <details> (e.g. the AI
    // priority panel inside 高级设置, or the cup's spawn editor) must also
    // reveal its folded ancestors, otherwise the inner controls stay hidden.
    // `toggle` is non-bubbling, so listen in the capture phase.
    document.addEventListener('toggle', e => {
      const d = e.target;
      if (!(d instanceof HTMLDetailsElement) || !d.open) return;
      for (let p = d.parentElement; p; p = p.parentElement) {
        if (p instanceof HTMLDetailsElement && !p.open) p.open = true;
      }
    }, {capture: true, signal: controller.signal});

    on($('#bsim-map-q'), 'input', e => { mapQuery = e.target.value; paintMaps(); });
    on($('#bsim-map'), 'change', e => { setup.mapId = e.target.value; save(); paintMaps(); run(); });
    on($('#bsim-mode'), 'change', e => { setup.mode = e.target.value; save(); run(); });
    on($('#bsim-rounds'), 'change', e => { setup.maxRounds = Math.max(1, Math.min(60, Number(e.target.value) || 20)); e.target.value = setup.maxRounds; save(); run(); });
    on($('#bsim-seed'), 'change', e => { setup.seed = Math.abs(Math.floor(Number(e.target.value) || 1)); e.target.value = setup.seed; save(); run(); });
    on($('#bsim-weather'), 'change', e => { setup.weather = Number(e.target.value) || 0; save(); run(); });
    on($('#bsim-interval'), 'change', e => { setup.interval = Number(e.target.value); save(); if (timer) { pause(); play(); } });
    on($('#bsim-heights'), 'change', e => {
      setup.heights = e.target.checked; save();
      const svg = $('.bsim-svg');
      if (svg) svg.classList.toggle('show-heights', setup.heights);
      else if (result) staticBoard3D(), show(cursor);   // 3D: rebuild tops with height labels
    });
    on($('#bsim-coords'), 'change', e => {
      setup.coords = e.target.checked; save();
      const svg = $('.bsim-svg');
      if (svg) svg.classList.toggle('show-coords', setup.coords);
      else if (result) staticBoard3D(), show(cursor);   // 3D: rebuild tops with coordinate labels
    });
    on($('#bsim-alert-range'), 'change', e => {
      setup.alertRange = !!e.target.checked; save();
      if (result) { if (setup.view === '3d') staticBoard3D(); show(cursor); }
    });
    on($('#bsim-range'), 'input', e => { pause(); show(Number(e.target.value)); });
    on($('#bsim-log-detail'), 'change', e => {
      setup.logDetail = !!e.target.checked; save(); paintLog();
    });
    on(root, 'change', e => {
      const p = e.target.closest?.('[data-prio]');
      if (!p) return;
      const k = p.dataset.prio, v = Math.max(0, Number(p.value) || 0);
      setup.skillPriority[k] = v;
      p.value = String(v);
      save(); run();
    });
    // Any real field edit in the fighter editor turns the slot into a legacy
    // custom fighter; a mere ↑/↓ slot reorder must not.
    on(root, 'input', e => {
      if (editing && e.target.closest?.('#bsim-editor-body')) editing.dirty = true;
    });
    for (const side of ['A', 'B']) {
      on($('#bsim-add-' + side), 'keydown', e => { if (e.key === 'Enter') { e.preventDefault(); addRole(side); } });
    }
    const selectUnit = card => {
      if (!card || !result) return;
      setup.panelUid = setup.panelUid === card.dataset.unit ? '' : card.dataset.unit;
      save(); paintUnits(result.steps[cursor]); paintPanel(result.steps[cursor]);
    };
    on($('#bsim-units'), 'click', e => {
      if (e.target.closest('a,button')) return;
      selectUnit(e.target.closest('[data-unit]'));
    });
    on($('#bsim-board'), 'click', e => {
      if (spawnPick) {
        const cell = e.target.closest('[data-x][data-y]');
        if (!cell) return;
        const x = Number(cell.dataset.x), y = Number(cell.dataset.y);
        if (!Number.isFinite(x) || !Number.isFinite(y)) return;
        const sched = currentSched();
        const mapId = getSpawnEdit(sched)?.mapId || sched?.mapId || setup.mapId;
        const mr = mapById.get(String(mapId));
        const raw = (mr?.raw?.cells || []).find(c => c[0] === x && c[1] === y);
        if (!walkable(x, y, raw?.[3])) { h.toast?.('这一格不可站立，请选其他格子'); return; }
        writeSpawnCell(spawnPick.side, spawnPick.idx, x, y);
        setSpawnPick(null, 0);
        save(); paintSpawnMarkers(); run();
        return;
      }
      const card = e.target.closest('.bsim-token[data-unit], [data-unit]');
      if (!card) return;
      selectUnit(card);
      // Re-render the board so the selection outline is visible in 2D too.
      dynamicBoard(result.steps[cursor]);
    });
    on(document, 'keydown', e => {
      if (e.key === 'Escape' && spawnPick) { setSpawnPick(null, 0); paintSpawnMarkers(); }
    });
    on($('#bsim-units'), 'keydown', e => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      const card = e.target.closest('[data-unit]');
      if (!card || !result) return;
      e.preventDefault();
      setup.panelUid = setup.panelUid === card.dataset.unit ? '' : card.dataset.unit;
      save(); paintUnits(result.steps[cursor]); paintPanel(result.steps[cursor]);
    });
    on($('#bsim-summary'), 'click', async e => {
      if (!e.target.closest('[data-lua-load]')) return;
      const box = $('#bsim-summary .bsim-lua');
      if (!box) return;
      const stat = box.querySelector('.bsim-lua-stat'), body = box.querySelector('.bsim-lua-body');
      try {
        if (!window.WIKI_LUA_SCRIPTS) await window.WikiData?.ensure(['lua']);
        const L = window.WIKI_LUA_SCRIPTS;
        if (!L) { stat.textContent = '解密索引未随离线包提供。'; return; }
        const m = L.meta;
        stat.innerHTML = `已解密 <b>${fmt(m.scripts)}</b> / ${fmt(m.totalArchived)} 个客户端脚本 · ` +
          `可读常量 <b>${fmt(m.readableStrings)}</b> 条 · AI 相关 <b>${fmt(L.aiTerms.length)}</b> 条。` +
          `<br>${esc(m.method)}`;
        body.innerHTML = `<p class="small-text">按脚本组：${Object.entries(m.groups).map(([g, n]) => `${esc(g)} ${fmt(n)}`).join(' · ')}</p>
          <label class="tool-field"><span>检索脚本内常量</span><input type="search" class="bsim-lua-q" placeholder="例如 ai_dict / dynamicParam / BattleRequire"></label>
          <div class="bsim-lua-results"></div>
          <details><summary>AI / 机制相关词项（${fmt(L.aiTerms.length)}）</summary>
            <div class="bsim-mech-list">${L.aiTerms.slice(0, 250).map(x => `<span class="is-ok">${esc(x)}</span>`).join('')}</div></details>`;
        const q = body.querySelector('.bsim-lua-q'), out = body.querySelector('.bsim-lua-results');
        const search = () => {
          const term = (q.value || '').trim().toLowerCase();
          if (!term) { out.innerHTML = ''; return; }
          const hits = Object.entries(L.scripts).filter(([name, [g, ids]]) =>
            name.toLowerCase().includes(term) || ids.some(i => L.pool[i].toLowerCase().includes(term))).slice(0, 30);
          out.innerHTML = hits.length ? `<div class="bsim-lua-hits">${hits.map(([name, [g]]) =>
            `<span class="bsim-lua-file" title="${esc(g)}">${esc(name)}<small>${esc(g)}</small></span>`).join('')}</div>`
            : '<p class="small-text muted">没有匹配的脚本。</p>';
        };
        on(q, 'input', search);
      } catch (err) { stat.textContent = '载入失败：' + (err?.message || err); }
    });
    on($('#bsim-panel'), 'click', e => {
      if (!e.target.closest('[data-panel-close]')) return;
      setup.panelUid = ''; save();
      paintUnits(result.steps[cursor]); paintPanel(result.steps[cursor]);
    });
    const paintViewButtons = () => {
      root.querySelectorAll('[data-bsim-view]').forEach(b =>
        b.setAttribute('aria-pressed', String(b.dataset.bsimView === setup.view)));
      const hint = $('#bsim-cam-hint');
      if (hint) hint.hidden = setup.view !== '3d';
    };
    const setView = v => {
      setup.view = v === '3d' ? '3d' : '2d';
      save(); paintViewButtons();
      if (result) { staticBoard(); show(cursor); }
    };
    paintViewButtons();
    if (CUP) {
      paintCup();
      paintSpawnEditor();
      on($('#bsim-cup-act'), 'change', () => { setup.cupId = 0; paintCup(); save(); });
      on($('#bsim-cup-sched'), 'change', e => {
        setup.cupId = Number(e.target.value); paintCup(); paintSpawnEditor(); save();
      });
      on($('#bsim-spawn-body'), 'change', e => {
        const f = e.target.dataset?.spawn;
        const sched = currentSched();
        if (!f || !sched || f === 'map') return;
        const [side, idx, axis] = f.split(':');
        const prev = getSpawnEdit(sched) || {A: [], B: []};
        prev[side] = prev[side] || [];
        prev[side][Number(idx)] = prev[side][Number(idx)] || {};
        const raw = e.target.value.trim();
        if (raw === '') delete prev[side][Number(idx)][axis];
        else prev[side][Number(idx)][axis] = Math.max(0, Number(raw) || 0);
        if (!Object.keys(prev[side][Number(idx)]).length) delete prev[side][Number(idx)];
        prev.A = prev.A || []; prev.B = prev.B || [];
        setSpawnEdit(sched, prev);
        // live validity feedback for this row (no full redraw keeps focus)
        const row = e.target.closest('.bsim-spawn-row');
        if (row) {
          const xs = row.querySelector('[data-spawn$=":x"]')?.value;
          const ys = row.querySelector('[data-spawn$=":y"]')?.value;
          const both = xs !== '' && ys !== '';
          const ed = getSpawnEdit(sched);
          const mapId = ed?.mapId || sched.mapId || setup.mapId;
          const mr = mapById.get(String(mapId));
          const cell = both ? (mr?.raw?.cells || []).find(c => c[0] === +xs && c[1] === +ys) : null;
          const ok = !!cell && walkable(+xs, +ys, cell[3]);
          row.classList.toggle('is-ok', !!both && ok);
          row.classList.toggle('is-bad', !!both && !ok);
          row.querySelector('small').textContent = !both ? '推定' : ok ? '可站立' : '不可站立';
        }
      });
      on($('#bsim-spawn-body'), 'input', e => {
        if (e.target.id !== 'bsim-spawn-map') return;
        const sched = currentSched();
        if (!sched) return;
        const prev = getSpawnEdit(sched) || {A: [], B: []};
        prev.mapId = Number(e.target.value);
        setSpawnEdit(sched, prev);
      });
      on($('#bsim-spawn-body'), 'click', e => {
        const sched = currentSched();
        if (!sched) return;
        if (e.target.closest('[data-spawn-pick-cancel]')) { setSpawnPick(null, 0); paintSpawnMarkers(); return; }
        const pick = e.target.closest('[data-spawn-pick]');
        if (pick) {
          const [side, idx] = pick.dataset.spawnPick.split(':');
          const same = spawnPick?.side === side && spawnPick?.idx === Number(idx);
          setSpawnPick(same ? null : side, Number(idx));
          paintSpawnMarkers();
          if (!same) {
            // Scroll the board into view so the map is right there to click.
            $('#bsim-board')?.scrollIntoView({behavior: 'smooth', block: 'center'});
          }
          return;
        }
        const one = e.target.closest('[data-spawn-clear-one]');
        if (one) {
          const [side, idx] = one.dataset.spawnClearOne.split(':');
          clearSpawnCell(side, Number(idx));
          paintSpawnEditor(); paintSpawnMarkers(); save(); run(); return;
        }
        if (e.target.closest('[data-spawn-clear]')) {
          setSpawnEdit(sched, null); setSpawnPick(null, 0); paintSpawnMarkers(); save(); run(); return;
        }
        if (e.target.closest('[data-spawn-apply]')) { save(); paintSpawnEditor(); run(); return; }
        const plan = e.target.closest('[data-plan]');
        if (plan) {
          const mode = plan.dataset.plan;
          const msg = $('#bsim-plan-msg');
          const say = s => { if (msg) msg.textContent = s; };
          try {
            if (mode === 'export' || mode === 'export-all') {
              const doc = buildPlan(sched, mode === 'export-all');
              const label = mode === 'export-all' ? '全部站位方案' : `站位方案-${doc.plans[0].mapId}-赛程${sched.id}`;
              download(`铃兰档案馆-${label}.json`, JSON.stringify(doc, null, 2), 'application/json');
              say(`已导出 ${doc.plans.length} 套方案`);
            } else if (mode === 'copy') {
              navigator.clipboard?.writeText(JSON.stringify(buildPlan(sched), null, 2));
              say('已复制 JSON 到剪贴板');
            } else if (mode === 'import') {
              $('#bsim-plan-file')?.click();
            }
          } catch (err) { say('导出失败：' + (err?.message || err)); }
          return;
        }
      });
      on($('#bsim-spawn-body'), 'change', async e => {
        const facing = e.target.closest?.('[data-spawn-dir]');
        if (facing) {
          const sched = currentSched();
          if (!sched) return;
          const [side, idx] = facing.dataset.spawnDir.split(':');
          const prev = getSpawnEdit(sched) || {A: [], B: []};
          prev[side] = prev[side] || [];
          const cell = Object.assign({}, prev[side][Number(idx)] || {});
          const v = facingVec(facing.value);
          if (v) cell.dir = v; else delete cell.dir;
          prev[side][Number(idx)] = cell;
          prev.A = prev.A || []; prev.B = prev.B || [];
          setSpawnEdit(sched, prev);
          save(); paintSpawnMarkers(); run();
          return;
        }
        if (e.target.id !== 'bsim-plan-file') return;
        const file = e.target.files?.[0];
        const msg = $('#bsim-plan-msg');
        if (!file) return;
        try {
          const doc = JSON.parse(await file.text());
          const r = applyPlan(doc, currentSched());
          // A plan belongs to a specific cup schedule. Importing it must show
          // THAT match (teams + map), otherwise the saved formation is stored
          // but the user keeps watching an unrelated battle.
          const target = r.first;
          if (target && Number(setup.cupId) !== Number(target.id)) {
            setup.cupId = Number(target.id);
            const act = $('#bsim-cup-act');
            if (act && target.activityId != null) act.value = String(target.activityId);
            paintCup();
            const t1 = cupTeamById.get(target.team1Id), t2 = cupTeamById.get(target.team2Id);
            if (t1) setup.A = cupMembers(t1);
            if (t2) setup.B = cupMembers(t2);
            setup.cupEnvId = target.id;
            const pm = Number(doc.plans[0]?.mapId || target.mapId || CUP.environment?.mapId || 0);
            if (pm && mapById.has(String(pm))) { setup.mapId = pm; paintMaps(); }
          }
          save(); paintTeams(); paintSpawnEditor(); paintSpawnMarkers(); run();
          const fresh = $('#bsim-plan-msg');   // editor was re-rendered
          if (fresh) fresh.textContent = `已导入 ${r.applied} 套方案` +
            (target ? ` · 已切换到赛程 ${target.id}` : '') + (r.skipped ? `（跳过 ${r.skipped}）` : '');
        } catch (err) {
          const fresh = $('#bsim-plan-msg') || msg;
          if (fresh) fresh.textContent = '导入失败：' + (err?.message || err);
        }
        e.target.value = '';
      });
      on($('#bsim-cup-env'), 'change', e => { setup.cupEnvOn = e.target.checked; save(); if (setup.cupEnvId) run(); });
      if ($('#bsim-elite-comp')) on($('#bsim-elite-comp'), 'change', e => {
        setup.eliteComp = e.target.checked; save(); run();
      });
    }
    const applyCamDefaults = () => {
      setup.yaw = 45; setup.tilt = 54; setup.zoom = 1;
      applyCam3D();   // synchronous so the reset is visible immediately
      save();
    };
    // 3D orbit: only CSS variables change, never the cube DOM.
    let drag3 = null;
    const frameEl = () => $('#bsim-board .world-iso-frame');
    on($('#bsim-board'), 'pointerdown', e => {
      if (setup.view !== '3d' || e.target.closest('button, input')) return;
      const f = frameEl();
      if (!f) return;
      drag3 = {x: e.clientX, y: e.clientY, yaw: setup.yaw, tilt: setup.tilt};
      f.classList.add('is-dragging');
    });
    // These must live on document (the `on` helper above binds to root).
    const winMove = e => {
      if (!drag3 || !root.isConnected) return;
      setup.yaw = ((drag3.yaw - (e.clientX - drag3.x) * .4) % 360 + 360) % 360;
      setup.tilt = Math.max(0, Math.min(85, drag3.tilt - (e.clientY - drag3.y) * .35));
      scheduleCam3D();
    };
    const winUp = () => {
      if (!drag3) return;
      drag3 = null;
      frameEl()?.classList.remove('is-dragging');
      save();
    };
    const winResize = () => { if (root.isConnected && setup.view === '3d') fit3D(); };
    document.addEventListener('pointermove', winMove);
    document.addEventListener('pointerup', winUp);
    document.addEventListener('pointercancel', winUp);
    window.addEventListener('resize', winResize);
    on($('#bsim-board'), 'wheel', e => {
      if (setup.view !== '3d') return;
      const f = frameEl();
      if (!f) return;
      e.preventDefault();
      setup.zoom = Math.max(.5, Math.min(2, setup.zoom + (e.deltaY < 0 ? .1 : -.1)));
      scheduleCam3D(); save();
    }, {passive: false});
    on(root, 'click', e => {
      const t = e.target.closest('button, [data-step]');
      if (!t || !root.contains(t)) return;
      if (t.dataset.bsimView) { setView(t.dataset.bsimView); return; }
      if (t.dataset.camReset !== undefined) { applyCamDefaults(); return; }
      if (t.dataset.cupLoad) { loadCup(t.dataset.cupLoad); return; }
      if (t.dataset.cupPredict) { predictCup(t.dataset.cupPredict); return; }
      if (t.dataset.foldGo) {
        const d = document.getElementById(t.dataset.foldGo);
        if (d) { d.open = true; d.scrollIntoView({behavior: 'smooth', block: 'start'}); }
        return;
      }
      if (t.dataset.batchRun !== undefined) { runBatch(); return; }
      if (t.dataset.batchWatch !== undefined) { watchSeed(t.dataset.batchWatch); return; }
      if (t.dataset.batchFilter) {
        batchFilter = t.dataset.batchFilter;
        for (const b of root.querySelectorAll('[data-batch-filter]'))
          b.classList.toggle('is-active', b.dataset.batchFilter === batchFilter);
        renderBatch(batchRows.length, batchRows.length);
        return;
      }
      if (t.dataset.edit) {
        const [side, i] = t.dataset.edit.split(':');
        openEditor(side, Number(i));
        return;
      }
      if (t.dataset.new) {
        const side = t.dataset.new;
        if (setup[side].length >= 8) { h.toast?.('每方最多 8 名角色'); return; }
        const base = slotFighter(side, 0) || {name: '自定义角色', stats: {hp: 3000, patk: 1200, matk: 800,
          pdef: 500, mdef: 500, spd: 100}, move: {mob: 3, up: 2, down: 2, type: 1},
          prof: 6, profName: '无属性', skills: []};
        setup[side].push({...base, name: base.name + ' · 副本', key: undefined});
        openEditor(side, setup[side].length - 1);
        return;
      }
      if (t.dataset.editorClose !== undefined) { $('#bsim-editor').close(); editing = null; return; }
      if (t.dataset.editorSave !== undefined) { commitEditor(); return; }
      if (t.dataset.editorReset !== undefined) {
        if (!editing) return;
        const slot = setup[editing.side][editing.index];
        if (typeof slot === 'string') {
          setup[editing.side][editing.index] = slot;
        } else if (slot?.key && byKey.has(slot.key)) {
          setup[editing.side][editing.index] = slot.key;
          $('#bsim-editor').close(); paintTeams(); save(); run();
          return;
        }
        $('#bsim-editor-body').innerHTML = editorHtml(slotFighter(editing.side, editing.index));
        return;
      }
      if (t.dataset.skillAdd !== undefined) {
        if (!editing) return;
        const f = readEditor(editing.fighter);
        f.skills.push({id: 'c' + Date.now(), name: '新技能', usable: true, heal: false,
          factor: 100, rangeMin: 0, rangeMax: 2, shape: 'diamond', aim: 'enemy',
          area: {type: 'single'}, cooldown: 0, order: 0, hits: 1, damageType: 1,
          ignoreDef: false, attackUp: 0, attackDown: 0, desc: '自定义技能'});
        editing.fighter = f;
        $('#bsim-editor-body').innerHTML = editorHtml(f);
        return;
      }
      if (t.dataset.skillDel !== undefined) {
        if (!editing) return;
        const f = readEditor(editing.fighter);
        f.skills.splice(Number(t.dataset.skillDel), 1);
        editing.fighter = f;
        $('#bsim-editor-body').innerHTML = editorHtml(f);
        return;
      }
      if (t.dataset.prioReset !== undefined) {
        setup.skillPriority = {personality: 3, carried: 2, basic: 1,
                               tierStep: 60, slotStep: 14, instantBonus: 420};
        root.querySelectorAll('[data-prio]').forEach(el => {
          el.value = String(setup.skillPriority[el.dataset.prio]);
        });
        save(); run(); return;
      }
      if (t.dataset.slotUp !== undefined || t.dataset.slotDown !== undefined) {
        if (!editing) return;
        const f = readEditor(editing.fighter);
        const rows = skillSlotRows(f);
        const i = Number(t.dataset.slotUp ?? t.dataset.slotDown);
        const j = t.dataset.slotUp !== undefined ? i - 1 : i + 1;
        if (j < 0 || j >= rows.length) return;
        [rows[i], rows[j]] = [rows[j], rows[i]];
        f.slotOrder = rows.map(r => r.id);
        editing.fighter = f;
        $('#bsim-editor-body').innerHTML = editorHtml(f);
        return;
      }
      if (t.dataset.run !== undefined) { save(); run(); return; }
      if (t.dataset.reseed !== undefined) { setup.seed = Math.floor(Math.random() * 1e9); $('#bsim-seed').value = setup.seed; save(); run(); return; }
      if (t.dataset.add) { addRole(t.dataset.add); return; }
      if (t.dataset.remove) { const [side, i] = t.dataset.remove.split(':'); setup[side].splice(Number(i), 1); paintTeams(); save(); return; }
      if (t.dataset.clear) { setup[t.dataset.clear] = []; paintTeams(); save(); return; }
      if (t.dataset.random) {
        const side = t.dataset.random, other = side === 'A' ? 'B' : 'A';
        const pick = shuffle(roster.map(r => r.key).filter(k => !setup[other].includes(k)), Date.now() & 0xffff).slice(0, 4);
        setup[side] = pick; paintTeams(); save(); return;
      }
      if (t.dataset.play) {
        const a = t.dataset.play;
        if (a === 'toggle') { if (timer) pause(); else play(); return; }
        pause();
        if (a === 'first') show(0); else if (a === 'last') show(result ? result.steps.length - 1 : 0);
        else if (a === 'prev') show(cursor - 1); else if (a === 'next') show(cursor + 1);
        return;
      }
      if (t.dataset.export && result) {
        const meta = {seed: setup.seed, modeLabel: MODES[setup.mode], maxRounds: setup.maxRounds};
        const stamp = `${result.grid.id}-${setup.seed}`;
        if (t.dataset.export === 'txt') download(`铃兰档案馆-自动对局-${stamp}.txt`, S.logText(result, meta), 'text/plain;charset=utf-8');
        else download(`铃兰档案馆-自动对局-${stamp}.json`, JSON.stringify({
          format: 'socwiki-battle-sim', version: 1, setup: {...setup, mapName: result.grid.name},
          winner: result.winner, rounds: result.rounds, verdict: result.verdict, summary: result.summary,
          steps: result.steps.map(({snap, ...rest}) => ({...rest, snap})),
        }, null, 1), 'application/json');
        return;
      }
      if (t.dataset.step !== undefined) { pause(); show(Number(t.dataset.step)); }
    });
    on(document, 'keydown', e => {
      if (!root.isConnected || !result) return;
      if (e.target.closest?.('input, select, textarea')) return;
      if (e.key === 'ArrowRight') { pause(); show(cursor + 1); e.preventDefault(); }
      else if (e.key === 'ArrowLeft') { pause(); show(cursor - 1); e.preventDefault(); }
      else if (e.key === 'Home') { pause(); show(0); e.preventDefault(); }
      else if (e.key === 'End') { pause(); show(result.steps.length - 1); e.preventDefault(); }
      else if (e.key === ' ' && e.target === document.body) { if (timer) pause(); else play(); e.preventDefault(); }
    });
    cleanup = () => {
      pause(); controller.abort();
      document.removeEventListener('pointermove', winMove);
      document.removeEventListener('pointerup', winUp);
      document.removeEventListener('pointercancel', winUp);
      window.removeEventListener('resize', winResize);
    };
    run();
  }

  return {render, unmount: () => { cleanup(); cleanup = () => {}; }};
})();
