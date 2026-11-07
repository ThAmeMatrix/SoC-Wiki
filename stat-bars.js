/* Shared "基础属性" stat bars, extracted from the infographic workshop.
 * Both the character archive and the out-of-battle panel calculator render
 * their five stats with this exact markup, so the two views look identical.
 *
 *   window.WikiStatBars.render(values, options)
 *     values: {hp, physicAttack, spellAttack, physicDefence, spellDefence}
 *     options: {maxima, heading, note, icons, compact}
 */
(function () {
  'use strict';
  // Order follows the infographic workshop's combatStatDefinitions:
  // 物攻/魔攻 → 物防/魔防 → 生命/速度 (three paired rows in a 2-col grid).
  var DEFS = [
    ['physicAttack', '物攻', 'attack'], ['spellAttack', '魔攻', 'magic'],
    ['physicDefence', '物防', 'defense'], ['spellDefence', '魔防', 'resistance'],
    ['hp', '生命', 'health'], ['agility', '速度', 'agility']
  ];
  var FALLBACK_PATHS = {
    hp: 'M13 2C9 6 5 9 5 14a8 8 0 0 0 16 0c0-5-4-8-8-12Z',
    physicAttack: 'M4 22 19 7l-2-2 3-3 4 4-3 3 2 2L8 26Z',
    spellAttack: 'M13 1 15 9l8 4-8 4-2 8-2-8-8-4 8-4Z',
    physicDefence: 'M13 2 22 5v8c0 6-4 9-9 11-5-2-9-5-9-11V5Z',
    spellDefence: 'M13 2 21 6v7c0 5-3 8-8 11-5-3-8-6-8-11V6Z'
  };
  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
    });
  }
  function ratio(v, max) {
    var a = Number(v), b = Number(max);
    return (Number.isFinite(a) && Number.isFinite(b) && b > 0) ? Math.max(0, Math.min(100, a / b * 100)) : null;
  }
  function iconFor(def, icons) {
    var key = def[0], label = def[1], alias = def[2] || key;
    var src = icons && (icons[alias] || icons[key]);
    if (src) {
      return '<img class="ig-stat-icon" src="' + esc(src) + '" alt="" title="' + esc(label) + '">';
    }
    var path = (window.WikiInfographicRules && window.WikiInfographicRules.statIconPaths || {})[alias]
      || FALLBACK_PATHS[alias] || FALLBACK_PATHS[key] || FALLBACK_PATHS.attack;
    return '<svg class="ig-stat-icon" viewBox="0 0 26 26" aria-hidden="true"><path d="' +
      esc(path) + '"/></svg>';
  }
  function render(values, options) {
    var o = options || {}, v = values || {}, maxima = o.maxima || {}, icons = o.icons;
    var defs = o.definitions || DEFS;
    var heading = o.heading === undefined ? '基础属性' : o.heading;
    var cards = defs.map(function (d) {
      var key = d[0], label = d[1], value = v[key], max = maxima[key];
      var pct = ratio(value, max);
      return '<div class="ig-stat-card" data-stat-key="' + key + '">' +
        '<div class="ig-stat-value">' + iconFor(d, icons) +
        '<small class="ig-stat-label">' + label + '</small>' +
        '<b class="ig-stat-current">' + esc(value == null || value === '' ? '—' : value) + '</b></div>' +
        '<div class="ig-stat-comparison"><small class="ig-stat-max">/ ' + esc(max == null ? '—' : max) + '</small>' +
        '<em>' + (pct === null ? '—' : pct.toFixed(1) + '%') + '</em></div>' +
        '<progress max="100" value="' + (pct === null ? 0 : pct) + '" aria-label="' + label +
        ' 占参考最高值"></progress></div>';
    }).join('');
    return '<div class="ig-base-stats ig-stat-bars' + (o.compact ? ' ig-stat-compact' : '') +
        (o.variant ? ' stat-bars-' + esc(o.variant) : '') + '" data-stat-bars>' +
      (heading ? '<div class="ig-stat-heading"><strong>' + esc(heading) + '</strong>' +
        '<small>' + esc(o.subtitle || '当前 / 参考最高 · 占比') + '</small></div>' : '') +
      '<div class="ig-stat-grid">' + cards + '</div>' +
      (o.note ? '<small class="ig-stat-note">' + esc(o.note) + '</small>' : '') + '</div>';
  }
  window.WikiStatBars = {render: render, definitions: DEFS, ratio: ratio};
})();
