/* Roster browsing rules shared by the character catalog and the infographic picker.
   Both views must agree: same facet values, same filter wording, same sort orders. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.WikiCatalog = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const PROFESSIONS = ['守望者', '粉碎者', '突袭者', '防御者', '毁灭者', '异士'];
  const RARITY_ORDER = ['SSR', 'SR', 'R', 'N'];
  const RARITY_RANK = {'SSR':0, 'SR':1, 'R':2, 'N':3, '传说':0, '史诗':1, '精英':2, '卓越':2, '普通':3};
  const STAT_KEYS = ['生命', '物攻', '魔攻', '物防', '魔防', '敏捷'];
  const SPLIT = /[，,、]/;
  const ORDER_BASE = 1000000;
  const normalize = s => String(s ?? '').toLowerCase().replace(/[·•・\s]/g, '');
  const rarityRank = p => RARITY_RANK[p.rarity] ?? 4;
  const seqOf = p => p.sourceOrder ?? ORDER_BASE + p.id;
  // 原站收录的角色带目录序号；纯客户端导入的角色没有，只能拿 id 兜底，两类分开排。
  const isWiki = p => seqOf(p) < ORDER_BASE;
  const clientOrder = (a, b) => (rarityRank(a) - rarityRank(b)) || (seqOf(b) - seqOf(a));
  const sourceOrder = (a, b) => isWiki(a) !== isWiki(b) ? (isWiki(a) ? -1 : 1)
    : (isWiki(a) ? seqOf(a) - seqOf(b) : clientOrder(a, b));
  const statValue = (p, key) => /^[\d.]+$/.test(String(p.stats?.[key] ?? '')) ? Number(p.stats[key]) : NaN;
  const factionsOf = p => String(p.faction ?? '').split(SPLIT).map(s => s.trim()).filter(Boolean);

  // 只列资料馆里真有的取值，免得点出空结果。
  function facets(list) {
    return {
      rarities: RARITY_ORDER.filter(r => list.some(p => p.rarity === r)),
      professions: PROFESSIONS.filter(c => list.some(p => p.class === c)),
      factions: [...new Set(list.flatMap(factionsOf))]
    };
  }

  function filter(list, options, pinyinHit) {
    const {q = '', rarity = '', profession = '', faction = ''} = options || {};
    const query = normalize(q);
    return list.filter(p => !p.redirect
      && (!query || normalize(p.title + ' ' + p.aliases + ' ' + p.summary).includes(query) || (pinyinHit && pinyinHit(p, query)))
      && (!rarity || p.rarity === rarity)
      && (!profession || p.class === profession)
      && (!faction || factionsOf(p).includes(faction)));
  }

  // source 的口径交给调用方：角色按原站目录优先，装备按稀有度 + 序号。
  function sort(list, mode, descending = false, bySource = sourceOrder) {
    const out = [...list];
    // 每项都拿目录顺序兜底，同样条件的两条永远排成同一个样子（跟列表原本的先后无关）。
    if (mode === 'source') out.sort(bySource);
    else if (mode === 'updated') out.sort((a, b) => (b.date || '').localeCompare(a.date || '') || bySource(a, b));
    else if (mode === 'name') out.sort((a, b) => (descending ? -1 : 1) * a.name.localeCompare(b.name, 'zh-CN') || bySource(a, b));
    else if (mode === 'rarity') out.sort((a, b) => rarityRank(a) - rarityRank(b) || bySource(a, b));
    else if (String(mode).startsWith('stat:')) {
      const key = mode.slice(5);
      out.sort((a, b) => {
        const av = statValue(a, key), bv = statValue(b, key);
        if (Number.isNaN(av)) return Number.isNaN(bv) ? bySource(a, b) : 1;
        if (Number.isNaN(bv)) return -1;
        return (descending ? -1 : 1) * (av - bv) || bySource(a, b);
      });
    }
    return out;
  }

  const SORT_OPTIONS = [
    {value: 'source', label: '原站角色顺序'},
    {value: 'updated', label: '最近更新'},
    {value: 'name', label: '名称排序'},
    {value: 'rarity', label: '稀有度排序'},
    ...STAT_KEYS.map(key => ({value: 'stat:' + key, label: (key === '敏捷' ? '速度' : key) + '排序'}))
  ];

  return {PROFESSIONS, RARITY_ORDER, RARITY_RANK, STAT_KEYS, SORT_OPTIONS, ORDER_BASE,
    normalize, facets, filter, sort, sourceOrder, clientOrder, statValue, factionsOf, rarityRank};
});
