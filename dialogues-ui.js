/* Browsable story dialogue: scenes, speakers, portraits and full-text search.
 *
 * Data comes from data/dialogues.js (scripts/extract_dialogues.py):
 *   scenes   = [[groupId, title, chapter, lineCount], ...]
 *   lines    = [[sceneIndex, speakerIndex, text, portraitIndex], ...]
 *   speakers / portraits are deduplicated lookup tables.
 * Everything is local; no page data is fetched at runtime.
 */
'use strict';
window.WikiDialogues = (() => {
  let root = null;
  let cleanup = () => {};
  let state = {scene: -1, chapter: '', query: '', hits: []};
  const esc = value => String(value ?? '').replace(/[&<>"']/g,
    c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const fmt = value => Number(value || 0).toLocaleString('zh-CN');

  function displayName(name) {
    return ({'{玩家昵称}': '你（团长）', '{黑猫昵称}': '黑猫'})[name] || name || '旁白';
  }

  function textHtml(text) {
    return esc(text).replace(/\r?\n/g, '<br>');
  }

  function data() { return window.WIKI_DIALOGUES || null; }

  function index(D) {
    if (D._sceneLines) return D;
    const sceneLines = new Map(), chapters = new Map();
    D.lines.forEach((line, i) => {
      if (!sceneLines.has(line[0])) sceneLines.set(line[0], []);
      sceneLines.get(line[0]).push(i);
    });
    D.scenes.forEach((scene, i) => {
      const key = scene[2] || '其它剧情';
      if (!chapters.has(key)) chapters.set(key, []);
      chapters.get(key).push(i);
    });
    D._sceneLines = sceneLines;
    D._chapters = chapters;
    return D;
  }

  function search(D, query, limit = 80) {
    const needle = query.trim().toLowerCase();
    if (!needle) return [];
    const hits = [];
    for (let i = 0; i < D.lines.length && hits.length < limit; i++) {
      const line = D.lines[i];
      const speaker = D.speakers[line[1]] || '';
      if (line[2].toLowerCase().includes(needle) || speaker.toLowerCase().includes(needle)) {
        hits.push({index: i, scene: line[0], speaker, text: line[2]});
      }
    }
    return hits;
  }

  function sceneList(D) {
    const chapters = [...D._chapters.keys()].sort((a, b) =>
      (D._chapters.get(b).length - D._chapters.get(a).length) || a.localeCompare(b, 'zh-CN'));
    const chosen = state.chapter ? [state.chapter] : chapters;
    const chips = `<div class="dialogue-chips" role="group" aria-label="按剧情线筛选">
      <button type="button" data-dlg-chapter="" aria-pressed="${!state.chapter}">全部 <small>${fmt(D.scenes.length)}</small></button>
      ${chapters.map(key => `<button type="button" data-dlg-chapter="${esc(key)}" aria-pressed="${state.chapter === key}">${esc(key)} <small>${fmt(D._chapters.get(key).length)}</small></button>`).join('')}
    </div>`;
    let scenes = [];
    for (const key of chosen) scenes.push(...(D._chapters.get(key) || []));
    scenes.sort((a, b) => a - b);
    const shown = scenes.slice(0, 240);
    const list = shown.map(i => {
      const scene = D.scenes[i];
      return `<button type="button" class="dialogue-scene ${state.scene === i ? 'active' : ''}" data-dlg-scene="${i}" aria-pressed="${state.scene === i}">
        <strong>${esc(scene[1])}</strong><span>${esc(scene[2])} · ${scene[3]} 句</span></button>`;
    }).join('');
    return `${chips}<div class="dialogue-scenes">${list || '<p class="dialogue-empty">这个分类里还没有对白。</p>'}</div>
      ${scenes.length > shown.length ? `<p class="dialogue-more">仅显示前 ${shown.length} 个场景，共 ${fmt(scenes.length)} 个。用上方搜索可以直接找到台词。</p>` : ''}`;
  }

  function transcript(D) {
    if (state.hits.length) {
      return `<div class="dialogue-transcript-head"><h2>搜索结果</h2><span>${fmt(state.hits.length)} 条（最多 80 条）</span></div>
        <div class="dialogue-lines">${state.hits.map(hit => `<div class="dialogue-line dialogue-hit" role="button" tabindex="0" data-dlg-scene="${hit.scene}">
          <div class="dialogue-line-name">${esc(displayName(hit.speaker))}<small>${esc(D.scenes[hit.scene]?.[1] || '')}</small></div>
          <div class="dialogue-line-text">${textHtml(hit.text)}</div></div>`).join('')}</div>`;
    }
    if (state.scene < 0 || !D.scenes[state.scene]) {
      return `<div class="dialogue-placeholder"><div class="eyebrow">STORY ARCHIVE</div>
        <h2>从客户端里读出的剧情台词</h2>
        <p>左侧按剧情线挑选一段演出，或在上方搜索角色名与台词。带立绘的台词会显示对应的半身表情差分。</p>
        <p class="small-text muted">共 ${fmt(D.scenes.length)} 段场景 · ${fmt(D.lines.length)} 条对白 · ${fmt(D.stats.withPortrait)} 条带立绘。</p></div>`;
    }
    const scene = D.scenes[state.scene];
    const indices = D._sceneLines.get(state.scene) || [];
    const lines = indices.map(i => {
      const line = D.lines[i];
      const speaker = D.speakers[line[1]] || '';
      const portrait = line[3] >= 0 ? D.portraits[line[3]] : '';
      return `<div class="dialogue-line ${portrait ? 'has-portrait' : ''}">
        ${portrait ? `<span class="dialogue-portrait-mark" title="${esc(displayName(speaker))} · 立绘表情差分已归档">◈</span>` : ''}
        <div class="dialogue-line-body"><div class="dialogue-line-name">${esc(displayName(speaker))}</div>
        <div class="dialogue-line-text">${textHtml(line[2])}</div></div></div>`;
    }).join('');
    return `<div class="dialogue-transcript-head"><div><span class="eyebrow">${esc(scene[2])}</span><h2>${esc(scene[1])}</h2></div>
      <span>${indices.length} 句对白</span></div><div class="dialogue-lines">${lines}</div>`;
  }

  function paint(options) {
    if (!root) return;
    const preserve = options?.preserveScroll !== false;
    // Rebuilding innerHTML resets every scroll container and the window scroll.
    // Remember them so selecting a scene keeps the reader where they clicked.
    const before = preserve ? {
      y: window.scrollY,
      scenes: root.querySelector('.dialogue-scenes')?.scrollTop ?? 0,
      lines: root.querySelector('.dialogue-lines')?.scrollTop ?? 0,
    } : null;
    const D = data();
    if (!D || !D.lines?.length) {
      root.innerHTML = `<div class="page-intro"><div><div class="eyebrow">STORY ARCHIVE</div><h1>剧情对话</h1>
        <p>还没有剧情对白数据。</p></div></div><div class="content-card"><p>请在「本地更新」里完成一次更新，或运行
        <code>python -X utf8 scripts/extract_dialogues.py</code> 生成本地剧情索引。</p></div>`;
      return;
    }
    index(D);
    const query = state.query || root.querySelector('#dialogue-query')?.value || '';
    root.innerHTML = `<div class="page-intro"><div><div class="eyebrow">STORY ARCHIVE</div><h1>剧情对话</h1>
        <p>从游戏客户端台词表还原的剧情对白：按剧情线浏览演出，或用角色名、台词全文搜索。</p></div></div>
      <div class="content-card dialogue-toolbar">
        <label class="dialogue-search"><span>搜索台词 / 说话人</span>
          <input id="dialogue-query" type="search" placeholder="例如：拉维耶、放心交给我吧" value="${esc(query)}" autocomplete="off"></label>
        <div class="dialogue-stats"><span>${fmt(D.scenes.length)} 段场景</span><span>${fmt(D.lines.length)} 条对白</span>
          <span>${fmt(D.speakers.length)} 位说话人</span><span>${fmt(D.stats.withPortrait)} 条带立绘</span></div>
      </div>
      <div class="dialogue-layout"><aside class="content-card dialogue-side">${sceneList(D)}</aside>
        <section class="content-card dialogue-main">${transcript(D)}</section></div>
      <div class="source-footer"><span>文本与立绘取自本地游戏客户端 · 完全离线</span></div>`;
    if (before) {
      const sc = root.querySelector('.dialogue-scenes');
      const ln = root.querySelector('.dialogue-lines');
      if (sc) sc.scrollTop = before.scenes;
      if (ln) ln.scrollTop = before.lines;
      window.scrollTo({top: before.y, behavior: 'instant'});
    }
  }

  function wire() {
    let timer = null;
    let composing = false;
    let pendingValue = '';
    const runSearch = () => {
      clearTimeout(timer);
      const value = pendingValue;
      state.query = value;
      state.hits = search(data(), value);
      state.scene = -1;
      // Only repaint the transcript / scene list; the search input itself must
      // stay mounted or an IME composition (Chinese, Japanese) is cancelled.
      const D = data();
      if (!D) return;
      const main = root.querySelector('.dialogue-main');
      if (main) main.innerHTML = transcript(D);
      const side = root.querySelector('.dialogue-side');
      if (side) side.innerHTML = sceneList(D);
      const scenes = root.querySelector('.dialogue-scenes');
      if (scenes) scenes.scrollTop = 0;
    };
    const onChange = e => {
      const field = e.target;
      if (field.id !== 'dialogue-query') return;
      pendingValue = field.value;
      // input events during composition carry the intermediate pinyin; ignore
      // them and let compositionend supply the committed Chinese text.
      if (composing || e.isComposing) return;
      clearTimeout(timer);
      timer = setTimeout(runSearch, 220);
    };
    const onCompositionStart = e => {
      if (e.target.id === 'dialogue-query') { composing = true; clearTimeout(timer); }
    };
    const onCompositionEnd = e => {
      if (e.target.id !== 'dialogue-query') return;
      composing = false;
      pendingValue = e.target.value;
      clearTimeout(timer);
      timer = setTimeout(runSearch, 60);
    };
    const onClick = e => {
      const target = e.target.closest('button, [role="button"]');
      if (!target) return;
      if (target.dataset.dlgChapter !== undefined) {
        state.chapter = target.dataset.dlgChapter;
        state.hits = [];
        state.query = '';
        const q = root.querySelector('#dialogue-query'); if (q) q.value = '';
        paint();
        return;
      }
      if (target.dataset.dlgScene !== undefined) {
        state.scene = Number(target.dataset.dlgScene);
        state.hits = [];
        state.query = '';
        const q = root.querySelector('#dialogue-query'); if (q) q.value = '';
        history.replaceState(null, '', `#/dialogues?scene=${state.scene}`);
        // Keep the reader at the clicked item: paint() restores scroll.
        paint();
      }
    };
    const onKey = e => {
      if (e.key === 'Enter' && e.target.matches?.('[role="button"]')) e.target.click();
    };
    root.addEventListener('input', onChange);
    root.addEventListener('compositionstart', onCompositionStart);
    root.addEventListener('compositionend', onCompositionEnd);
    root.addEventListener('click', onClick);
    root.addEventListener('keydown', onKey);
    cleanup = () => {
      clearTimeout(timer);
      root.removeEventListener('input', onChange);
      root.removeEventListener('compositionstart', onCompositionStart);
      root.removeEventListener('compositionend', onCompositionEnd);
      root.removeEventListener('click', onClick);
      root.removeEventListener('keydown', onKey);
    };
  }

  return {
    render(element, params) {
      unmount();
      root = element;
      const requested = Number(params?.get?.('scene'));
      state = {scene: Number.isInteger(requested) && requested >= 0 ? requested : -1,
               chapter: '', query: '', hits: []};
      paint();
      wire();
    },
    unmount,
  };

  function unmount() {
    cleanup();
    cleanup = () => {};
    root = null;
  }
})();
