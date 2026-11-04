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

  /** Cumulative bonuses of both account-wide talent trees for this character. */
  function talentBonuses(data, character, config) {
    const flat = zeroes(), permillage = zeroes();
    const category = String(int(character?.professionCategory, 0));
    for (const key of ['star', 'pioneer']) {
      const tree = data.talents?.[key];
      if (!tree) continue;
      const level = clamp(int(config?.talent?.[key], 0), 0, tree.maxLevel);
      const row = (lookup(tree.byCategory, category) || [])[level];
      if (!row) continue;
      for (let i = 0; i < N; i++) {
        flat[i] += int(row.flat?.[i]);
        permillage[i] += int(row.perm?.[i]);
      }
    }
    return { flat, permillage };
  }

  /** Lookup helper for the UI: one tree's cumulative row at a given level. */
  function talentRow(data, treeKey, category, level) {
    const tree = data.talents?.[treeKey];
    if (!tree) return null;
    return (lookup(tree.byCategory, category) || [])[clamp(int(level, 0), 0, tree.maxLevel)] || null;
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

  function defaults(data) {
    const character = (data.characters || []).find(c => c.wiki) || data.characters?.[0];
    const weapon = (data.weapons || []).find(w => w.main) || data.weapons?.[0];
    const offhand = (data.weapons || []).find(w => !w.main);
    const charm = data.charms?.[0];
    return {
      character: character?.key || '', star: 5, level: data.maxLevel,
      rank: data.maxRank, tier: 1, enhance: false, friendship: 5,
      linePicks: null, talent: { star: 0, pioneer: 0 }, talentAdjust: zeroes(),
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
      extras.push({ key: 'talent', label: '星辰 / 开拓天赋', values: talent.flat.slice(),
                    permillage: talent.permillage.slice() });
    }

    const adjust = Array.isArray(config.talentAdjust) ? config.talentAdjust : [];
    const flat = zeroes(), permillage = zeroes(), total = zeroes();
    for (let i = 0; i < N; i++) {
      flat[i] = base[i] + weapon.flat[i] + offhand.flat[i] + charm.flat[i] + talent.flat[i];
      permillage[i] = weapon.permillage[i] + offhand.permillage[i] + charm.permillage[i]
                    + talent.permillage[i] + int(adjust[i]);
      total[i] = Math.floor(flat[i] * (1000 + permillage[i]) / 1000);
    }
    return {
      labels: LABELS.slice(), fields: FIELDS.slice(),
      base, weapon: weapon.flat, offhand: offhand.flat, tarot: charm.flat, talent,
      flat, permillage, total, extras,
      speed: int(character.speed),
      character,
    };
  }

  const api = { FIELDS, LABELS, calculate, defaults, findCharacter, enchantCaps, entryCap,
                starPermillage, friendshipPermillage, skillLinePermillage, rankAdditions,
                talentBonuses, talentRow, clamp, int };
  (typeof window !== 'undefined' ? window : globalThis).WikiPanelCalc = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})();
