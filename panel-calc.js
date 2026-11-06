/* Off-panel calculator core. Pure functions, no DOM: usable in the browser and in Node tests.
 *
 * The character formula reproduces the client's CalculateAttributeByType:
 *   floor(growth * rarityAdjust * (1000 + permillage) / 1000 / 100) + sum(rankAdd)
 * where permillage collects star, skill-line and friendship bonuses. Equipment uses
 * the same hundredths convention; flat and permillage affixes are then applied to
 * the summed pre-battle totals. Every step is returned so the UI can show its work.
 */
(() => {
  'use strict';
  const FIELDS = ['hp', 'physic_attack', 'spell_attack', 'physic_defence', 'spell_defence'];
  const LABELS = ['生命', '物攻', '魔攻', '物防', '魔防'];
  const N = FIELDS.length;

  const int = (value, fallback = 0) => {
    const n = Number(value);
    return Number.isFinite(n) ? Math.trunc(n) : fallback;
  };
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  const zeroes = () => new Array(N).fill(0);

  function lookup(map, key) {
    if (!map) return null;
    return map[key] ?? map[String(key)] ?? null;
  }

  /** Star permillage for one level (1..5). */
  function starPermillage(data, star) {
    return lookup(data.stars, clamp(int(star, 1), 1, 5)) || zeroes();
  }

  /** Accumulated friendship permillage for levels 1..level. */
  function friendshipPermillage(data, level) {
    let total = 0;
    for (let i = 1; i <= clamp(int(level, 0), 0, 5); i++) total += int(data.friendship?.[i] ?? data.friendship?.[String(i)]);
    return total;
  }

  /** Skill-line rows unlocked per rank, with an independent left/right choice.
   * ``config.linePicks[rank]`` accepts 'none' | 'left' | 'right' | 'both'.
   * Without it we fall back to the single global ``config.tier`` for compatibility.
   */
  function skillLinePermillage(data, character, config) {
    const rows = lookup(data.lines, character.line) || [];
    const rank = clamp(int(config.rank, 0), 0, data.maxRank);
    const enhance = !!config.enhance;
    const picks = config?.linePicks;
    const fallback = clamp(int(config?.tier, 1), 1, 2);
    const allowed = r => {
      if (!picks) return fallback;
      const v = Array.isArray(picks) ? picks[r] : picks[r] ?? picks[String(r)];
      if (v === 'none' || v === 0 || v === false) return 0;
      if (v === 'both' || v === 'all') return 3;
      if (v === 'left' || v === 1) return 1;
      if (v === 'right' || v === 2) return 2;
      return fallback;
    };
    const chosen = new Map();
    for (const row of rows) {
      const [r, t, isEnhance] = row;
      if (r > rank) continue;
      const allow = allowed(r);
      if (!allow || (allow !== 3 && allow !== t)) continue;
      const key = r + ':' + t;
      const current = chosen.get(key);
      if (!current) { chosen.set(key, row); continue; }
      // Enhanced rows (塔罗技能轴) replace the normal row of the same rank/tier.
      if (!!current[2] !== enhance && !!isEnhance === enhance) chosen.set(key, row);
    }
    const total = zeroes();
    for (const [, , , permillage] of chosen.values()) {
      for (let i = 0; i < N; i++) total[i] += int(permillage?.[i]);
    }
    return total;
  }

  /** Resolve the real client talent tree for a character + system. */
  function talentTree(data, treeKey, character) {
    const tree = data.talents?.[treeKey];
    if (!tree) return null;
    const category = String(int(character?.professionCategory, 0));
    return tree.trees?.[category] || null;
  }

  /** ``upgrade_type`` 51 nodes are "全职业属性调整": they sit in one
   * profession's tree but their bonus applies to every character. Return the
   * full-tree set of those nodes (from every category) plus their total. */
  function globalTalentNodes(data, treeKey) {
    const group = data.talents?.[treeKey];
    if (!group) return {nodes: [], flat: zeroes(), perm: zeroes()};
    const nodes = [];
    for (const tree of Object.values(group.trees || {})) {
      for (const node of tree.nodes || []) {
        if (node.global) nodes.push({...node, category: tree.id});
      }
    }
    const flat = zeroes(), perm = zeroes();
    for (const node of nodes) {
      const top = node.levels?.[node.levels.length - 1];
      if (!top) continue;
      for (let s = 0; s < N; s++) {
        flat[s] += int(top.flat?.[s]);
        perm[s] += int(top.perm?.[s]);
      }
    }
    return {nodes, flat, perm};
  }

  /** Global nodes the player actually lit, across all professions. */
  function globalTalentPicks(data, config, treeKey) {
    const picks = config?.talentNodes?.[treeKey] || {};
    const result = {flat: zeroes(), perm: zeroes(), lit: 0, total: 0};
    const {nodes} = globalTalentNodes(data, treeKey);
    for (const node of nodes) {
      result.total += 1;
      const level = clamp(int(picks[node.id], 0), 0, node.levels.length);
      if (!level) continue;
      const row = node.levels[level - 1];
      for (let s = 0; s < N; s++) {
        result.flat[s] += int(row.flat?.[s]);
        result.perm[s] += int(row.perm?.[s]);
      }
      result.lit += 1;
    }
    return result;
  }

  /** Bonuses from the nodes the player actually lit, with game progression data.
   *
   * ``config.talentNodes[treeKey]`` maps a client node id to the invested
   * level (0 = unlit). Every level up to the invested one contributes its own
   * ``flat`` / ``perm`` row, exactly like spending materials in game. The old
   * ``config.talent[treeKey]`` tier lookup remains as a fallback so saved
   * presets keep working; a node selection always wins when present.
   */
  function talentBonuses(data, character, config) {
    const flat = zeroes(), permillage = zeroes();
    const sources = [];
    let spent = 0, lit = 0, missing = 0;
    for (const key of ['star', 'pioneer']) {
      const tree = talentTree(data, key, character);
      const picks = config?.talentNodes?.[key];
      if (!tree || !picks || typeof picks !== 'object') continue;
      const byId = new Map(tree.nodes.map(n => [String(n.id), n]));
      for (const [nodeId, value] of Object.entries(picks)) {
        const level = clamp(int(value, 0), 0, 99);
        if (!level) continue;
        const node = byId.get(String(nodeId));
        if (!node) continue;
        // ``upgrade_type=51`` nodes are handled once for ALL professions by
        // globalTalentPicks below. Counting them here too double-counts the
        // two nodes that physically live in the current character's tree.
        if (node.global) continue;
        const usable = Math.min(level, node.levels.length);
        // ``upgrade_param1`` is the CUMULATIVE bonus at that level (5, 10,
        // 15 …), not a per-level increment. Only the row for the invested
        // level contributes stats; experience and materials are per-level
        // costs and must still be summed over all levels.
        for (let i = 0; i < usable; i++) spent += int(node.levels[i].exp);
        const current = node.levels[usable - 1];
        for (let s = 0; s < N; s++) {
          flat[s] += int(current.flat?.[s]);
          permillage[s] += int(current.perm?.[s]);
        }
        lit += 1;
        if (level > node.levels.length) missing += level - node.levels.length;
        // A lit node must have all of its prerequisites lit too; report it so
        // the UI can warn instead of silently applying an impossible build.
        for (const prev of node.prev || []) {
          if (!int(picks[String(prev)], 0)) missing += 1;
        }
      }
      // Global (all-profession) nodes may belong to a DIFFERENT profession's
      // tree; count the ones the player lit there once, wherever they are.
      const globals = globalTalentPicks(data, config, key);
      for (let s = 0; s < N; s++) {
        flat[s] += globals.flat[s];
        permillage[s] += globals.perm[s];
      }
      if (lit || globals.lit) sources.push(key);
    }
    if (sources.length) return { flat, permillage, nodeBased: true, spent, lit, missing, sources };

    // Legacy tier mode (kept for older saved presets).
    for (const key of ['star', 'pioneer']) {
      const tree = data.talents?.[key];
      if (!tree) continue;
      const level = clamp(int(config?.talent?.[key], 0), 0, tree.maxLevel);
      const row = (lookup(tree.byCategory, String(int(character?.professionCategory, 0))) || [])[level];
      if (!row) continue;
      for (let i = 0; i < N; i++) {
        flat[i] += int(row.flat?.[i]);
        permillage[i] += int(row.perm?.[i]);
      }
    }
    return { flat, permillage, nodeBased: false, spent: 0, lit: 0, missing: 0, sources: [] };
  }

  /** Lookup helper for the UI  /** Lookup helper for the UI: one tree's cumulative row at a given level. */
  function talentRow(data, treeKey, category, level) {
    const tree = data.talents?.[treeKey];
    if (!tree) return null;
    return (lookup(tree.byCategory, category) || [])[clamp(int(level, 0), 0, tree.maxLevel)] || null;
  }

  /** Total experience and materials for a node selection, plus the highest
   * client player level required. The UI shows these next to the tree so a
   * build can be compared with the in-game talent panel. */
  function talentProgress(data, character, config) {
    const out = {exp: 0, nodes: 0, reqLevel: 1, unavailable: 0, cost: {},
                 flat: zeroes(), permillage: zeroes()};
    for (const key of ['star', 'pioneer']) {
      const tree = talentTree(data, key, character);
      const picks = config?.talentNodes?.[key] || {};
      if (!tree) continue;
      const byId = new Map(tree.nodes.map(n => [String(n.id), n]));
      for (const [nodeId, value] of Object.entries(picks)) {
        const level = clamp(int(value, 0), 0, 99);
        if (!level) continue;
        const node = byId.get(String(nodeId));
        if (!node) continue;
        if (node.global) continue;      // counted once by globalTalentPicks
        out.nodes += 1;
        const usable = Math.min(level, node.levels.length);
        for (let i = 0; i < usable; i++) {
          const row = node.levels[i];
          out.exp += int(row.exp);
          out.reqLevel = Math.max(out.reqLevel, int(row.reqLevel, 1));
          for (const item of row.cost || []) {
            // New format [type, param0, amount]; older exports used [type, amount].
            const type = item[0], amount = item.length >= 3 ? item[2] : item[1];
            const label = String(type) + (item.length >= 3 && item[1] ? ':' + item[1] : '');
            out.cost[label] = (out.cost[label] || 0) + int(amount);
          }
        }
        const current = node.levels[usable - 1];
        for (let s = 0; s < N; s++) {
          out.flat[s] += int(current.flat?.[s]);
          out.permillage[s] += int(current.perm?.[s]);
        }
      }
      const globals = globalTalentPicks(data, config, key);
      for (let s = 0; s < N; s++) {
        out.flat[s] += globals.flat[s];
        out.permillage[s] += globals.perm[s];
      }
      out.global = out.global || {flat: zeroes(), perm: zeroes(), lit: 0, total: 0};
      for (let s = 0; s < N; s++) {
        out.global.flat[s] += globals.flat[s];
        out.global.perm[s] += globals.perm[s];
      }
      out.global.lit += globals.lit;
      out.global.total += globals.total;
    }
    return out;
  }

  /** Separate bonus totals for each talent tree, plus their combined sum. */
  function talentBreakdown(data, character, config) {
    const out = {};
    const total = {flat: zeroes(), perm: zeroes()};
    for (const key of ['star', 'pioneer']) {
      const tree = talentTree(data, key, character);
      const picks = config?.talentNodes?.[key] || {};
      const flat = zeroes(), perm = zeroes();
      let lit = 0;
      if (tree) {
        const byId = new Map(tree.nodes.map(n => [String(n.id), n]));
        for (const [nodeId, value] of Object.entries(picks)) {
          const level = clamp(int(value, 0), 0, 99);
          if (!level) continue;
          const node = byId.get(String(nodeId));
          if (!node) continue;
          if (node.global) continue;    // global nodes are added once below
          const row = node.levels[Math.min(level, node.levels.length) - 1];
          if (!row) continue;
          for (let s = 0; s < N; s++) {
            flat[s] += int(row.flat?.[s]);
            perm[s] += int(row.perm?.[s]);
          }
          lit += 1;
        }
      }
      const globals = globalTalentPicks(data, config, key);
      for (let s = 0; s < N; s++) {
        flat[s] += globals.flat[s];
        perm[s] += globals.perm[s];
        total.flat[s] += flat[s];
        total.perm[s] += perm[s];
      }
      out[key] = {flat, perm, lit, globalLit: globals.lit, globalTotal: globals.total};
    }
    out.total = total;
    return out;
  }

  /** Light every node of one tree (or just one grade/图), respecting the
   * client's own level count per node. Returns the number of nodes changed. */
  function talentFillAll(data, character, config, treeKey, groupId, includeGlobal) {
    const tree = talentTree(data, treeKey, character);
    if (!tree) return 0;
    const picks = config.talentNodes?.[treeKey] || {};
    let changed = 0;
    const light = node => {
      const top = node.levels.length;
      if (int(picks[node.id], 0) !== top) {
        picks[node.id] = top;
        changed += 1;
      }
    };
    for (const node of tree.nodes) {
      const inGroup = groupId == null ||
        (treeKey === 'star' ? node.grade === Number(groupId) : node.unlockGroup === Number(groupId));
      if (inGroup) light(node);
    }
    // A full-tree fill also lights the all-profession nodes that physically
    // live in the other four professions' trees.
    if (includeGlobal && groupId == null) {
      for (const node of globalTalentNodes(data, treeKey).nodes) light(node);
    }
    return changed;
  }

  /** Human-readable cost of one node level, using the client's material names. */
  function talentCostLabel(data, treeKey, cost) {
    if (!cost || !cost.length) return '无消耗';
    const materials = data.talents?.[treeKey]?.materials || data.talents?._materials || {};
    return cost.map(item => {
      const type = item[0], param = item.length >= 3 ? item[1] : 0;
      const amount = item.length >= 3 ? item[2] : item[1];
      const meta = materials[String(type)] || {};
      const name = (param && meta.paramNames?.[String(param)]) || meta.name || ('资源 ' + type);
      return `${name} ×${int(amount)}`;
    }).join(' · ');
  }

  /** The grade / unlock-group the client would show for a given EXP total. */
  function talentGrade(data, character, treeKey, exp) {
    const tree = talentTree(data, treeKey, character);
    if (!tree || treeKey !== 'star') return null;
    const grades = tree.grades || [];
    let current = grades[0] || null;
    for (const grade of grades) if (int(exp) >= int(grade.exp)) current = grade;
    return current;
  }

  /** Sum of the fixed rank add-ons for ranks 1..rank. */
  function rankAdditions(data, character, rank) {
    const rows = lookup(data.rankAdds, character.rankModify) || [];
    const total = zeroes();
    const upto = clamp(int(rank, 0), 0, Math.min(data.maxRank, rows.length));
    for (let r = 0; r < upto; r++) {
      const row = rows[r] || zeroes();
      for (let i = 0; i < N; i++) total[i] += int(row[i]);
    }
    return total;
  }

  /** Client's hundredths computation for one growth/permillage pair. */
  function scaled(growth, adjust, permillage) {
    return Math.floor(growth * adjust * (1000 + permillage) / 1000 / 100);
  }

  function characterBase(data, character, config, extras) {
    const level = clamp(int(config.level, 60), 1, data.maxLevel);
    const growth = (lookup(data.unitGrowth, character.modify) || [])[level - 1] || zeroes();
    const rarity = lookup(data.rarities, character.rarity) || ['', 100];
    const star = starPermillage(data, config.star);
    const line = skillLinePermillage(data, character, config);
    const friend = friendshipPermillage(data, config.friendship);
    const adds = rankAdditions(data, character, config.rank);
    const totals = zeroes();
    const permillage = zeroes();
    for (let i = 0; i < N; i++) {
      permillage[i] = star[i] + line[i] + friend;
      // The client computes floor((adjusted + 100*adds)/100), with adjusted already
      // holding the hundredths. Splitting the two floors is equivalent because adds
      // are integers scaled by exactly 100.
      totals[i] = scaled(growth[i], rarity[1], permillage[i]) + adds[i];
    }
    extras.push({
      key: 'character',
      label: `${character.name} · ${level} 级 · ${config.star} 星 · ${clamp(int(config.rank, 0), 0, data.maxRank)} 阶`,
      values: totals.slice(), permillage,
    });
    return totals;
  }

  function equipment(data, slot, config, extras) {
    if (!config || !config.id) return { flat: zeroes(), permillage: zeroes() };
    const weapon = (data.weapons || []).find(w => String(w.id) === String(config.id));
    if (!weapon) return { flat: zeroes(), permillage: zeroes() };
    const level = clamp(int(config.level, 60), 1, data.maxLevel);
    const growth = (lookup(data.weaponGrowth, weapon.modify) || [])[level - 1] || zeroes();
    const rarity = lookup(data.weaponRarities, weapon.rarity) || ['', 100];
    const star = lookup(data.weaponStars, clamp(int(config.star, 1), 1, 5)) || zeroes();
    const flat = zeroes();
    for (let i = 0; i < N; i++) flat[i] = scaled(growth[i], rarity[1], star[i]);
    extras.push({ key: slot, label: `${slot === 'weapon' ? '武器' : '装具'} · ${weapon.name} · ${level} 级 · ${config.star} 星`, values: flat.slice() });

    const permillage = zeroes();
    const ench = config.enchant;
    if (ench && ench.element) {
      const caps = enchantCaps(data, ench.element);
      const values = Array.isArray(ench.values) ? ench.values : [];
      const percents = Array.isArray(ench.percents) ? ench.percents : [];
      const bonus = zeroes();
      for (let i = 0; i < N; i++) {
        bonus[i] = clamp(int(values[i]), 0, caps.flat[i]);
        permillage[i] = clamp(int(percents[i]), 0, caps.percent[i]);
      }
      const element = (data.elements || []).find(e => String(e.id) === String(ench.element));
      extras.push({ key: slot + '-enchant', label: `${element ? element.name : ''}刻印 · 固定属性`, values: bonus.slice() });
      for (let i = 0; i < N; i++) flat[i] += bonus[i];
    }
    return { flat, permillage };
  }

  function tarot(data, config, extras) {
    const result = { flat: zeroes(), permillage: zeroes() };
    if (!config || !config.id) return result;
    const charm = (data.charms || []).find(c => String(c.id) === String(config.id));
    if (!charm) return result;
    const rarity = lookup(data.charmRarities, config.rarity) || ['', 100, 0, 60];
    const level = clamp(int(config.level, 60), 1, Math.min(data.maxLevel, rarity[3] || data.maxLevel));
    const growth = (lookup(data.charmGrowth, charm.modify) || [])[level - 1] || zeroes();
    for (let i = 0; i < N; i++) result.flat[i] = Math.floor(growth[i] * rarity[1] / 100);
    extras.push({ key: 'tarot', label: `塔罗 · ${charm.name} · ${rarity[0]} · ${level} 级`, values: result.flat.slice() });

    const count = clamp(int(config.entryCount, rarity[2]), 0, rarity[2]);
    const types = new Map((data.entryTypes || []).map(t => [String(t.id), t]));
    const chosen = Array.isArray(config.entries) ? config.entries.slice(0, count) : [];
    const flatBonus = zeroes();
    for (const entry of chosen) {
      const type = types.get(String(entry?.type));
      if (!type) continue;
      const cap = entryCap(data, config.rarity, type);
      // 0 means "affix not rolled"; the table minimum is not a mandatory value.
      const value = clamp(int(entry.value), 0, cap.max);
      if (type.percent) result.permillage[type.stat] += value;
      else flatBonus[type.stat] += value;
    }
    if (chosen.length) extras.push({ key: 'tarot-entries', label: `塔罗词条 · ${chosen.length} 条固定属性`, values: flatBonus.slice() });
    for (let i = 0; i < N; i++) result.flat[i] += flatBonus[i];
    return result;
  }

  /** Upper bound for one enchant stat of a given element (flat and permillage). */
  function enchantCaps(data, element) {
    const flat = zeroes(), percent = zeroes();
    for (const row of data.enchant || []) {
      if (String(row.element) !== String(element)) continue;
      const i = int(row.stat, -1);
      if (i < 0 || i >= N) continue;
      if (row.percent) percent[i] = Math.max(percent[i], int(row.max));
      else flat[i] = Math.max(flat[i], int(row.max));
    }
    return { flat, percent };
  }

  /** Numeric range for a tarot entry of a given rarity/type. */
  function entryCap(data, rarity, type) {
    const candidates = (data.entries || []).filter(e => int(e.rarity) === int(rarity) && String(e.type) === String(type.id));
    if (!candidates.length) return { min: 0, max: type.percent ? 300 : 500 };
    return {
      min: Math.min(...candidates.map(e => int(e.min))),
      max: Math.max(...candidates.map(e => int(e.max))),
    };
  }

  function findCharacter(data, key) {
    return (data.characters || []).find(c => c.key === key || c.name === key) || null;
  }

  /** Default talent state: both trees fully lit, including the all-profession
   * nodes that live in the other four profession trees. */
  function defaultTalentNodes(data, character) {
    const result = {star: {}, pioneer: {}};
    for (const key of ['star', 'pioneer']) {
      const tree = talentTree(data, key, character);
      for (const node of tree?.nodes || []) result[key][node.id] = node.levels.length;
      for (const node of globalTalentNodes(data, key).nodes) {
        result[key][node.id] = node.levels.length;
      }
    }
    return result;
  }

  function defaults(data) {
    const character = (data.characters || []).find(c => c.wiki) || data.characters?.[0];
    // Same weapon whitelist as the UI, so a pure calculation and the rendered
    // form start from the same (legal) equipment.
    const allowed = new Set((character?.weaponTypes || []).map(Number).filter(t => t !== 2));
    const weapon = (data.weapons || []).find(w => allowed.has(Number(w.typeId)))
      || (data.weapons || []).find(w => w.main) || data.weapons?.[0];
    const offhand = (data.weapons || []).find(w => Number(w.typeId) === 2);
    const charm = data.charms?.[0];
    return {
      character: character?.key || '', star: 5, level: data.maxLevel,
      rank: data.maxRank, tier: 1, enhance: false, friendship: 5,
      linePicks: null, talent: { star: 0, pioneer: 0 },
      talentNodes: defaultTalentNodes(data, character), talentAdjust: zeroes(),
      talentAdjustFlat: zeroes(), talentAdjustPercent: zeroes(),
      weapon: { id: weapon?.id || 0, star: 5, level: data.maxLevel,
                enchant: { element: data.elements?.[0]?.id || 0, values: zeroes(), percents: zeroes() } },
      offhand: { id: offhand?.id || weapon?.id || 0, star: 5, level: data.maxLevel,
                 enchant: { element: data.elements?.[0]?.id || 0, values: zeroes(), percents: zeroes() } },
      charm: { id: charm?.id || 0, rarity: 4, level: data.maxLevel, entryCount: 4, entries: [] },
    };
  }

  function calculate(config, data) {
    if (!data || !data.characters) throw new Error('面板数据尚未载入，请完整解压离线包。');
    const character = findCharacter(data, config.character);
    if (!character) throw new Error('请选择一个角色。');
    const extras = [];
    const base = characterBase(data, character, config, extras);
    const weapon = equipment(data, 'weapon', config.weapon, extras);
    const offhand = equipment(data, 'offhand', config.offhand, extras);
    const charm = tarot(data, config.charm, extras);
    const talent = talentBonuses(data, character, config);
    if (talent.flat.some(Boolean) || talent.permillage.some(Boolean)) {
      extras.push({ key: 'talent', label: talent.nodeBased
                      ? `星辰 / 开拓天赋 · ${talent.lit} 个节点`
                      : '星辰 / 开拓天赋（旧档位）',
                    values: talent.flat.slice(), permillage: talent.permillage.slice() });
    }

    const adjust = Array.isArray(config.talentAdjust) ? config.talentAdjust : [];
    // Player-facing percent inputs are stored per-mille internally (10% = 100‰).
    const adjustFlat = Array.isArray(config.talentAdjustFlat) ? config.talentAdjustFlat : [];
    const flat = zeroes(), permillage = zeroes(), total = zeroes();
    for (let i = 0; i < N; i++) {
      flat[i] = base[i] + weapon.flat[i] + offhand.flat[i] + charm.flat[i] + talent.flat[i]
                + int(adjustFlat[i]);
      permillage[i] = weapon.permillage[i] + offhand.permillage[i] + charm.permillage[i]
                    + talent.permillage[i] + int(adjust[i]);
      // The client's percent affixes are relative to the WHITEBOARD value:
      // 「角色白板属性，即角色卸下所有装备后再减去天赋所增加的属性后的属性值」
      // (BWIKI 塔罗图鉴库/附魔图鉴库). So Q multiplies ONLY the character's
      // own base, never equipment/talent flat bonuses. Multiplying the whole
      // flat total (the old behaviour) inflated every geared character.
      const whiteboard = int(base[i]);
      total[i] = Math.floor(whiteboard * (1000 + permillage[i]) / 1000)
                 + flat[i] - whiteboard;
    }
    // ``formula`` is the exact expression behind ``total``. Each term records
    // its section id so the UI can make every number a jump link.
    const formula = {
      terms: [
        {key: 'base', label: '角色基础', section: '01', values: base.slice()},
        {key: 'weapon', label: '武器', section: '02', values: weapon.flat.slice()},
        {key: 'offhand', label: '装具', section: '03', values: offhand.flat.slice()},
        {key: 'tarot', label: '塔罗', section: '04', values: charm.flat.slice()},
        {key: 'talent', label: '天赋固定', section: '05', values: talent.flat.slice()},
        {key: 'adjust', label: '天赋微调', section: '05', values: adjustFlat.slice()},
      ],
      permParts: [
        {key: 'weapon', label: '武器刻印', section: '02', values: weapon.permillage.slice()},
        {key: 'offhand', label: '装具刻印', section: '03', values: offhand.permillage.slice()},
        {key: 'tarot', label: '塔罗词条', section: '04', values: charm.permillage.slice()},
        {key: 'talent', label: '天赋', section: '05', values: talent.permillage.slice()},
        {key: 'adjust', label: '天赋微调', section: '05', values: adjust.slice()},
      ],
      flat, permillage, total,
      whiteboard: base.slice(),
      addends: (() => {
        const out = zeroes();
        for (let i = 0; i < N; i++) out[i] = flat[i] - int(base[i]);
        return out;
      })(),
    };
    return {
      labels: LABELS.slice(), fields: FIELDS.slice(),
      base, weapon: weapon.flat, offhand: offhand.flat, tarot: charm.flat, talent,
      flat, permillage, total, extras, formula,
      whiteboard: base.slice(), addends: formula.addends,
      speed: int(character.speed),
      character,
    };
  }

  /** Out-of-battle combat power derived from the panel result.

   * The client exposes three pieces of the calculation as config data:
   *   - const_param#132 OnlineRoleUnitBattlePowerCoefficient = "120|200":
   *     the divisors that turn raw stats into score points (HP / 120, the
   *     four combat stats / 200, mirroring the two-value coefficient list);
   *   - battle_power_coefficient.percent: profession / weapon multiplier;
   *   - unit_rarity.battle_power_adjust: rarity multiplier.
   * The assembly itself lives in compiled IL2CPP code, so this reconstruction
   * states every term and source explicitly rather than pretending to be an
   * exact disassembly. ``world.battlePower`` comes from WIKI_WORLD_DATA.
   */
  function battlePower(panel, world, data, options = {}) {
    const bp = world?.battlePower || {};
    const divisors = bp.divisors?.length ? bp.divisors.map(Number) : [120, 200];
    const hpWeight = Number(bp.hpWeight ?? divisors[0] ?? 120);
    const otherWeight = Number(bp.otherWeight ?? divisors[1] ?? 200);
    const stats = panel?.total || zeroes();
    const whiteboard = panel?.whiteboard || panel?.base || stats;
    const char = panel?.character || {};
    const rarity = bp.rarity?.[String(char.rarity)]?.percent ?? 100;
    const prof = int(char.professionCategory, 0);
    const weaponType = (char.weaponTypes || []).find(x => Number(x) !== 2);
    const coef = (bp.coefficients || []).find(c => Number(c.profession) === prof
                    && Number(c.weaponType) === Number(weaponType || 0))
      || (bp.coefficients || []).find(c => Number(c.profession) === prof);
    const profession = coef ? int(coef.percent, 100) : 100;
    const method = options.method || 'permille-final';
    const scale = Number(options.scale ?? 1) || 1;

    let base, parts;
    if (method === 'permille-white' || method === 'divisor-final' || method === 'sum-percent') {
      const src = method === 'permille-white' ? whiteboard : stats;
      if (method === 'sum-percent') {
        parts = src.map(v => int(v) / 10);
        base = parts.reduce((a, v) => a + v, 0);
      } else if (method === 'divisor-final') {
        parts = src.map((v, i) => int(v) / (i === 0 ? hpWeight : otherWeight));
        base = parts.reduce((a, v) => a + v, 0);
      } else {
        parts = src.map((v, i) => int(v) * (i === 0 ? hpWeight : otherWeight) / 1000);
        base = parts.reduce((a, v) => a + v, 0);
      }
    } else {
      parts = stats.map((v, i) => int(v) * (i === 0 ? hpWeight : otherWeight) / 1000);
      base = parts.reduce((a, v) => a + v, 0);
    }
    const total = Math.floor(base * rarity / 100 * profession / 100 * scale);
    // Given a known in-game value, derive the multiplier the client would have
    // applied. This lets the player calibrate instead of trusting a guess.
    const calibration = Number(options.calibration) || 0;
    const impliedScale = calibration > 0
      ? calibration / (base * rarity / 100 * profession / 100) : null;
    return {
      total, base, parts, hpWeight, otherWeight, rarity, profession, method, scale,
      stats: stats.slice(), whiteboard: whiteboard.slice(),
      impliedScale, calibration,
      candidates: bp.candidates || [], evidence: bp.evidence || [],
      questPowerCurve: bp.questPowerCurve || [],
      rarityName: bp.rarity?.[String(char.rarity)]?.name || '',
      formula: bp.formula || '', calibrationText: bp.calibration || '',
      source: bp.source || 'const_param#132 · battle_power_coefficient · unit_rarity',
      constId: bp.constId,
      confidence: 'unverified',
    };
  }

  /** Base five-stat value of one equipment slot at its current level/star.
   * This is the raw client growth row (no enchant, no percent bonus) and is
   * what the UI shows next to the equipment selector. */
  function equipmentBase(data, slot, config) {
    if (!config || !config.id) return null;
    if (slot === 'charm') {
      const charm = (data.charms || []).find(c => String(c.id) === String(config.id));
      if (!charm) return null;
      const rarity = lookup(data.charmRarities, config.rarity) || ['', 100, 0, 60];
      const level = clamp(int(config.level, 60), 1, Math.min(data.maxLevel, rarity[3] || data.maxLevel));
      const row = (lookup(data.charmGrowth, charm.modify) || [])[level - 1] || zeroes();
      const values = zeroes();
      for (let i = 0; i < N; i++) values[i] = Math.floor(int(row[i]) * int(rarity[1], 100) / 100);
      return {values, label: `塔罗 · ${charm.name} · ${rarity[0]} · ${level} 级`, rarity: rarity[0], level};
    }
    const weapon = (data.weapons || []).find(w => String(w.id) === String(config.id));
    if (!weapon) return null;
    const level = clamp(int(config.level, 60), 1, data.maxLevel);
    const row = (lookup(data.weaponGrowth, weapon.modify) || [])[level - 1] || zeroes();
    const rarity = lookup(data.weaponRarities, weapon.rarity) || ['', 100];
    const star = lookup(data.weaponStars, clamp(int(config.star, 1), 1, 5)) || zeroes();
    const values = zeroes();
    for (let i = 0; i < N; i++) values[i] = scaled(int(row[i]), int(rarity[1], 100), int(star[i]));
    return {values, label: `${weapon.name} · ${rarity[0]} · ${level} 级 · ${config.star} 星`,
            rarity: rarity[0], level};
  }

  /** Battle damage preview built from the panel result and client constants.
   *
   * ``(attack × restraint × highGround − defense) × skillMult × bonus × vulnerability``
   * mirrors tools-core.js::calculateDamage, but every multiplier that the
   * client exposes comes from ``WIKI_COMBAT_DATA`` (const_param /
   * profession_restrain / 伤害公式汇总) instead of a hard-coded table.
   * ``panel`` is the return value of calculate(); ``combat`` is the combat data.
   */
  function damage(panel, combat, config = {}) {
    const c = combat || {};
    const constants = c.constants || {};
    const value = key => int(constants[key]?.value);
    const stat = config.stat === 'mag' ? 2 : 1;   // 1=物攻, 2=魔攻
    const attack = Math.max(0, int(panel?.total?.[stat]) + int(config.attackBonusFlat)
                            + int(config.attackBonusPercent) * Math.max(0, int(panel?.total?.[stat])) / 100);
    const restraints = c.restraints || [];
    const match = restraints.find(r => Number(r.from) === int(config.attackCategory)
                                && Number(r.to) === int(config.defenseCategory));
    // ``factor`` is the real multiplier from profession_restrain's linked
    // speciality (1.3 / 0.7, or 1.4 / 0.6 for 守望者↔毁灭者). ``evaluate``
    // in that table is only a UI display number and must NOT be used here.
    const restraint = match ? Number(match.factor ?? int(match.percent) / 100)
      : (config.attackCategory && config.defenseCategory && config.attackCategory !== config.defenseCategory
         ? value('RestrainFactor') / 100 : 1);
    const height = config.highGround === 'up' ? 1 + (c.highGround?.up ?? 15) / 100
      : config.highGround === 'down' ? 1 + (c.highGround?.down ?? -10) / 100 : 1;
    const defenseBase = Math.max(0, int(config.defense));
    const reduced = Math.max(0, defenseBase * (1 - int(config.defenseDown) / 100)
                             - int(config.defenseFlatIgnore));
    const defense = reduced * (1 - clamp(int(config.ignoreDefense), 0, 100) / 100);
    const base = Math.max(0, attack * restraint * height - defense);
    const skill = Math.max(0, int(config.skillMult, 100)) / 100;
    const bonus = Math.max(.5, 1 + int(config.damageBonus) / 100);
    const vulnerability = Math.min(value('FixBedamageLimit') / 100 || 3,
                                   Math.max(0, 1 + int(config.vulnerability) / 100));
    const critical = value('CritBaseChance') / 100;
    const criticalDamage = value('CritBaseDamage') / 100;
    const hit = Math.max(0, base * skill * bonus * vulnerability);
    return {
      damage: Math.round(hit), criticalDamage: Math.round(hit * (1 + criticalDamage)),
      attack, restraint, height, defense, base, skill, bonus, vulnerability,
      criticalChance: critical, criticalBonus: criticalDamage,
      sources: {
        restraint: match?.source || 'const_param#22 / profession_restrain',
        highGround: c.highGround?.source || '伤害公式汇总（归档攻略）',
        critical: constants.CritBaseChance?.source || 'const_param#129',
        criticalDamage: constants.CritBaseDamage?.source || 'const_param#64',
        damageCap: constants.FixBedamageLimit?.source || 'const_param#296',
      },
    };
  }

  function damageDefaults(combat) {
    const categories = combat?.categories || [];
    return { stat: 'phys', attackCategory: categories[0]?.id || 1,
             defenseCategory: categories[0]?.id || 1, highGround: 'flat',
             defense: 1000, defenseDown: 0, defenseFlatIgnore: 0, ignoreDefense: 0,
             skillMult: 100, damageBonus: 0, vulnerability: 0,
             attackBonusFlat: 0, attackBonusPercent: 0 };
  }

  const api = { FIELDS, LABELS, calculate, defaults, findCharacter, enchantCaps, entryCap,
                starPermillage, friendshipPermillage, skillLinePermillage, rankAdditions,
                talentBonuses, talentRow, talentTree, talentProgress, talentGrade,
                talentFillAll, talentCostLabel, globalTalentNodes, globalTalentPicks,
                talentBreakdown, defaultTalentNodes, equipmentBase, battlePower,
                damage, damageDefaults, clamp, int };
  (typeof window !== 'undefined' ? window : globalThis).WikiPanelCalc = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})();
