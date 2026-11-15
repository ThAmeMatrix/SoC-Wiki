/* Loading-performance helpers shared by every page.
 *
 * WikiImg   picks the light web variant of a heavy image when one was built by
 *           scripts/build_image_variants.py (data/image-variants.js), and falls
 *           back to the original otherwise. Originals stay untouched and are
 *           still what the lightbox / download button opens.
 *             thumb(src)    long side <= 480 px — cards, lists, search results
 *             display(src)  <= 1280 px wide    — detail views, rich text
 *             optimizeHtml  rewrites <img> in archived page HTML to the display
 *                           variant (keeping data-full) and adds lazy loading.
 * WikiData  loads page-specific data scripts on demand instead of making every
 *           visit download ~18 MB of dialogue / map / code / mechanics data.
 * A service worker is registered on http(s) only (GitHub Pages); file:// keeps
 * working exactly as before.
 */
'use strict';
(function () {
  let sets = null;
  const variants = () => {
    if (sets) return sets;
    const v = window.WIKI_IMAGE_VARIANTS || {};
    sets = {thumb: new Set(v.thumb || []), display: new Set(v.display || [])};
    return sets;
  };
  const variant = kind => src => {
    if (typeof src !== 'string' || !src.startsWith('assets/')) return src;
    const rel = src.slice(7);
    if (!variants()[kind].has(rel)) return src;
    return 'assets/' + kind + '/' + rel.replace(/\.[a-z0-9]+$/i, '.webp');
  };
  const thumb = variant('thumb');
  const display = variant('display');

  function optimizeHtml(html) {
    if (typeof html !== 'string' || html.indexOf('<img') < 0) return html;
    return html.replace(/<img\b([^>]*?)(\/?)>/gi, (tag, attrs, slash) => {
      let out = attrs;
      const m = out.match(/\ssrc="([^"]+)"/i);
      if (m && !/\sdata-full=/i.test(out)) {
        const better = display(m[1]);
        if (better !== m[1]) out = out.replace(m[0], ` src="${better}" data-full="${m[1]}"`);
      }
      if (!/\sloading=/i.test(out)) out += ' loading="lazy"';
      if (!/\sdecoding=/i.test(out)) out += ' decoding="async"';
      return '<img' + out + slash + '>';
    });
  }

  // Rewrite every HTML-bearing string of an archived page once.
  function optimizeDoc(doc) {
    if (!doc || doc.__imgOptimized) return doc;
    if (typeof doc.html === 'string') doc.html = optimizeHtml(doc.html);
    for (const group of [doc.fields, doc.rawFields]) {
      if (!group || typeof group !== 'object') continue;
      for (const k of Object.keys(group)) if (typeof group[k] === 'string') group[k] = optimizeHtml(group[k]);
    }
    try { Object.defineProperty(doc, '__imgOptimized', {value: true}); } catch { /* frozen */ }
    return doc;
  }

  window.WikiImg = {thumb, display, optimizeHtml, optimizeDoc};

  /* ---------- on-demand data ---------- */
  const DATASETS = {
    dialogues: ['data/dialogues.js', 'WIKI_DIALOGUES'],
    world: ['data/world-data.js', 'WIKI_WORLD_DATA'],
    code: ['data/client-code.js', 'WIKI_CLIENT_CODE'],
    mechanics: ['data/skill-mechanics.js', 'WIKI_SKILL_MECHANICS'],
    enhance: ['data/enhance-data.js', 'WIKI_ENHANCE_DATA'],
    battle: ['data/battle-sim.js', 'WIKI_BATTLE_SIM'],
    cup: ['data/match-cup.js', 'WIKI_MATCH_CUP'],
    mech: ['data/battle-mech.js', 'WIKI_BATTLE_MECH'],
    lua: ['data/lua-scripts.js', 'WIKI_LUA_SCRIPTS'],
    substrate: ['data/client-mechanisms.js', 'WIKI_CLIENT_MECHANISMS'],
    charmech: ['data/character-mechanics.js', 'WIKI_CHARACTER_MECHANICS'],
  };
  const pending = new Map();
  function loadOne(name) {
    const entry = DATASETS[name];
    if (!entry) return Promise.reject(new Error('未知数据集：' + name));
    const [src, global] = entry;
    if (window[global]) return Promise.resolve(window[global]);
    if (!pending.has(name)) {
      pending.set(name, new Promise((resolve, reject) => {
        const s = document.createElement('script');
        s.src = src;
        s.onload = () => { s.remove(); window[global] ? resolve(window[global]) : reject(new Error('数据文件内容不完整：' + src)); };
        s.onerror = () => { s.remove(); pending.delete(name); reject(new Error('本地文件载入失败：' + src)); };
        document.head.appendChild(s);
      }));
    }
    return pending.get(name);
  }
  window.WikiData = {
    datasets: DATASETS,
    ensure: names => Promise.all((names || []).map(loadOne)),
    loaded: name => !!window[DATASETS[name]?.[1]],
  };

  /* ---------- service worker (GitHub Pages / any http server) ---------- */
  if ('serviceWorker' in navigator && /^https?:$/.test(location.protocol)) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('sw.js').catch(() => { /* optional */ });
    });
  }
})();
