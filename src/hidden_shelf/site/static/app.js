/* 藏片阁 站点入口：hash 路由单页。数据来自 window.__shelf.*（由 <script src> 载入），纯逻辑在 ShelfCore。
 * 从 file:// 打开，不 fetch、不加载外网资源。文案全部走 t(key)。 */
(function () {
  'use strict';

  var core = window.ShelfCore || {};
  var dict = window.ShelfI18n || { zh: {}, en: {} };
  var PAGE_SIZE = 120;
  var PAGINATE_OVER = 200;
  var RELATED_MAX = 12;
  var DEBOUNCE_MS = 150;

  /* ---------- 持久化偏好 ---------- */
  function readPref(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
  function writePref(key, value) {
    try { if (value == null) localStorage.removeItem(key); else localStorage.setItem(key, value); } catch (e) { /* 私密模式 */ }
  }

  var LANGS = ['zh', 'en', 'ja'];
  var LANG_TAGS = { zh: 'zh-CN', en: 'en', ja: 'ja' };
  var LANG_SHORT = { zh: 'CH', en: 'EN', ja: 'JP' };
  var lang = (function () {
    var saved = readPref('lang');
    if (LANGS.indexOf(saved) !== -1) return saved;
    var fromBody = document.body && document.body.getAttribute('data-language');
    if (LANGS.indexOf(fromBody) !== -1) return fromBody;
    var nav = navigator.language || '';
    return /^zh/i.test(nav) ? 'zh' : /^ja/i.test(nav) ? 'ja' : 'en';
  })();
  function nextLang() { return LANGS[(LANGS.indexOf(lang) + 1) % LANGS.length]; }
  /** 语言按钮：CH / EN / JP 三段，当前那段高亮；点一下切到下一种。 */
  function langSwitch() {
    var parts = [];
    LANGS.forEach(function (code, i) {
      if (i) parts.push(h('span', { class: 'lang-sep', 'aria-hidden': 'true', text: ' / ' }));
      parts.push(h('span', { class: 'lang-opt' + (code === lang ? ' on' : ''), text: LANG_SHORT[code] }));
    });
    return parts;
  }

  function t(key, vars) {
    var table = dict[lang] || {};
    var text = table[key] != null ? table[key] : (dict.zh && dict.zh[key] != null ? dict.zh[key] : key);
    if (vars) {
      Object.keys(vars).forEach(function (name) { text = text.split('{' + name + '}').join(String(vars[name])); });
    }
    return text;
  }

  function applyLang() {
    document.documentElement.lang = LANG_TAGS[lang] || 'en';
    document.title = t('app.name');
    localizeData();
  }

  function themePref() { var saved = readPref('theme'); return saved === 'light' || saved === 'dark' ? saved : 'system'; }
  function applyTheme(value) {
    if (value === 'light' || value === 'dark') { document.documentElement.dataset.theme = value; writePref('theme', value); }
    else { delete document.documentElement.dataset.theme; writePref('theme', null); }
  }

  /* ---------- DOM 小工具 ---------- */
  function h(tag, attrs) {
    var el = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (name) {
        var value = attrs[name];
        if (value == null || value === false) return;
        if (name === 'class') el.className = value;
        else if (name === 'text') el.textContent = value;
        else if (name === 'html') el.innerHTML = value;
        else if (name.indexOf('on') === 0 && typeof value === 'function') el.addEventListener(name.slice(2), value);
        else if (name === 'dataset') Object.keys(value).forEach(function (k) { el.dataset[k] = value[k]; });
        else el.setAttribute(name, value === true ? '' : value);
      });
    }
    for (var i = 2; i < arguments.length; i++) append(el, arguments[i]);
    return el;
  }
  function append(parent, child) {
    if (child == null || child === false) return;
    if (Array.isArray(child)) { child.forEach(function (c) { append(parent, c); }); return; }
    parent.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
  }
  function icon(name) {
    var paths = ICONS[name] || '';
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + paths + '</svg>';
    var span = h('span', { class: 'icon', html: svg });
    return span;
  }
  var ICONS = {
    grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    building: '<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M9 22v-4h6v4"/><path d="M8 6h.01M16 6h.01M12 6h.01M12 10h.01M8 10h.01M16 10h.01M12 14h.01M8 14h.01M16 14h.01"/>',
    layers: '<path d="m12 2 10 5-10 5L2 7l10-5z"/><path d="m2 12 10 5 10-5"/><path d="m2 17 10 5 10-5"/>',
    tag: '<path d="M20.59 13.41 13.42 20.58a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><circle cx="7" cy="7" r="1.5"/>',
    help: '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
    chart: '<path d="M3 3v18h18"/><path d="M7 15v-4"/><path d="M12 15V7"/><path d="M17 15v-2"/>',
    monitor: '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
    moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9z"/>',
    search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>',
    menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    play: '<polygon points="6 3 20 12 6 21 6 3"/>',
    copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    film: '<rect x="2" y="2" width="20" height="20" rx="2"/><path d="M7 2v20M17 2v20M2 12h20M2 7h5M2 17h5M17 17h5M17 7h5"/>',
    clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    drive: '<path d="M22 12H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/><path d="M6 16h.01M10 16h.01"/>',
    alert: '<circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/>',
    back: '<path d="m15 18-6-6 6-6"/>',
    image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>'
  };

  /* ---------- 数据 ---------- */
  var data = window.__shelf || {};
  var works = data.works || [];
  var entities = data.entities || { performers: [], studios: [], series: [], tags: [] };
  var unrecognized = data.unrecognized || [];
  var meta = data.meta || {};
  var byId = {};
  works.forEach(function (work) { byId[work.id] = work; });
  var names = { performers: {}, tags: {} };
  var avatars = {};
  (entities.performers || []).forEach(function (p) { names.performers[p.id] = p.name; if (p.avatar) avatars[p.id] = p.avatar; });
  function avatarOf(pid) { return avatars[pid] || null; }
  names.tagsSearch = {};
  (entities.tags || []).forEach(function (tg) {
    names.tags[tg.id] = tg.name;
    var all = [tg.name].concat(tg.names ? [tg.names.zh, tg.names.en, tg.names.ja] : []);
    names.tagsSearch[tg.id] = all.filter(function (v, i) { return v && all.indexOf(v) === i; }).join(' ');
  });
  /* 未识别视频上墙时的哨兵（build.py 写的）：按当前语言换成「未识别」「素人」。切换语言后要再调一次。 */
  var UNRECOGNIZED = '__unrecognized__';
  var AMATEUR = '__amateur__';
  function isUnrecognizedFacet(value) { return value === UNRECOGNIZED; }
  function localizeData() {
    (entities.performers || []).forEach(function (p) { if (p.id === 0 || p.name === AMATEUR) { p.name = t('placeholder.amateur'); names.performers[p.id] = p.name; } });
    ['studios', 'series'].forEach(function (kind) {
      (entities[kind] || []).forEach(function (item) { if (item.id === UNRECOGNIZED) item.name = t('placeholder.unrecognized'); });
    });
    // 标签按当前语言显示（build.py 给的 names = {zh, en, ja}；表里没有的三种一样）。
    (entities.tags || []).forEach(function (tg) {
      var localized = tg.names && tg.names[lang] ? tg.names[lang] : tg.name;
      names.tags[tg.id] = localized;
      tg.name = localized;
    });
  }
  var probe = document.createElement('video');
  var canPlayType = probe && probe.canPlayType ? function (mime) { return probe.canPlayType(mime); } : null;

  function loadErrors() {
    var errors = (window.__shelfLoadErrors || []).slice();
    var expected = meta.dataFiles || [];
    if (!window.__shelf) errors.push('data/*.js');
    expected.forEach(function (name) {
      if (name.indexOf('works') === 0 && !data.works) errors.push(name);
    });
    return errors.filter(function (name, index, list) { return list.indexOf(name) === index; });
  }

  /* ---------- 路由 ---------- */
  function parseHash() {
    var raw = location.hash.replace(/^#/, '') || '/';
    var q = raw.indexOf('?');
    var path = q === -1 ? raw : raw.slice(0, q);
    var query = q === -1 ? '' : raw.slice(q + 1);
    var parts = path.split('/').filter(Boolean).map(function (p) { try { return decodeURIComponent(p); } catch (e) { return p; } });
    return { path: path, parts: parts, query: core.parseQuery ? core.parseQuery(query) : {} };
  }
  function href(path, state) {
    var query = state && core.buildQuery ? core.buildQuery(state) : '';
    return '#' + path + (query ? '?' + query : '');
  }
  function navigate(path, state) { location.hash = href(path, state).slice(1); }

  /* ---------- 壳：侧栏 + 内容 ---------- */
  var app = document.getElementById('app');
  var drawerOpen = false;
  var themeMenuOpen = false;

  function renderShell(route) {
    app.innerHTML = '';
    app.setAttribute('aria-busy', 'false');
    var errors = loadErrors();
    var main = h('main', { class: 'content', id: 'main', tabindex: '-1' });
    app.appendChild(h('div', { class: 'layout' + (drawerOpen ? ' drawer-open' : '') },
      h('button', { class: 'menu-button', 'data-ripple': true, 'aria-label': t('menu.open'), onclick: function () { drawerOpen = true; render(); } }, icon('menu')),
      drawerOpen ? h('div', { class: 'overlay', onclick: function () { drawerOpen = false; render(); } }) : null,
      renderSidebar(route),
      main));
    if (errors.length) { main.appendChild(renderError(errors)); return; }
    if (!works.length && !unrecognized.length && route.parts[0] !== 'stats') { main.appendChild(renderEmptyLibrary()); return; }
    main.appendChild(renderRoute(route));
  }

  var NAV = [
    { path: '/', key: 'nav.home', icon: 'grid', match: function (r) { return !r.parts.length; } },
    { path: '/performers', key: 'nav.performers', icon: 'users', match: function (r) { return r.parts[0] === 'performers' || r.parts[0] === 'performer'; } },
    { path: '/studios', key: 'nav.studios', icon: 'building', match: function (r) { return r.parts[0] === 'studios' || r.parts[0] === 'studio'; } },
    { path: '/series', key: 'nav.series', icon: 'layers', match: function (r) { return r.parts[0] === 'series'; } },
    { path: '/tags', key: 'nav.tags', icon: 'tag', match: function (r) { return r.parts[0] === 'tags' || r.parts[0] === 'tag'; } },
    { path: '/unrecognized', key: 'nav.unrecognized', icon: 'help', match: function (r) { return r.parts[0] === 'unrecognized'; } },
    { path: '/stats', key: 'nav.stats', icon: 'chart', match: function (r) { return r.parts[0] === 'stats'; } }
  ];

  function renderSidebar(route) {
    var theme = themePref();
    var themeIcon = theme === 'light' ? 'sun' : theme === 'dark' ? 'moon' : 'monitor';
    return h('aside', { class: 'sidebar', 'aria-label': t('app.name') },
      h('div', { class: 'brand' }, icon('film'), h('span', { class: 'brand-name', text: t('app.name') }),
        h('button', { class: 'icon-button drawer-close', 'data-ripple': true, 'aria-label': t('menu.close'), onclick: function () { drawerOpen = false; render(); } }, icon('x'))),
      h('nav', { class: 'nav' }, NAV.map(function (item) {
        var active = item.match(route);
        return h('a', { class: 'nav-item' + (active ? ' active' : ''), href: '#' + item.path, 'data-ripple': true, 'aria-current': active ? 'page' : null,
          onclick: function () { drawerOpen = false; } }, icon(item.icon), h('span', { text: t(item.key) }));
      })),
      h('div', { class: 'sidebar-footer' },
        h('div', { class: 'theme-wrap' },
          h('button', { class: 'footer-button', 'data-ripple': true, 'aria-haspopup': 'menu', 'aria-expanded': themeMenuOpen ? 'true' : 'false', 'aria-label': t('theme.label'),
            onclick: function (e) { e.stopPropagation(); themeMenuOpen = !themeMenuOpen; render(); } }, icon(themeIcon), h('span', { text: t('theme.' + theme) })),
          themeMenuOpen ? h('div', { class: 'menu', role: 'menu' }, ['system', 'light', 'dark'].map(function (value) {
            return h('button', { class: 'menu-item', role: 'menuitemradio', 'aria-checked': theme === value ? 'true' : 'false', 'data-ripple': true,
              onclick: function () { applyTheme(value); themeMenuOpen = false; render(); } },
              icon(value === 'light' ? 'sun' : value === 'dark' ? 'moon' : 'monitor'), h('span', { text: t('theme.' + value) }),
              theme === value ? icon('check') : null);
          })) : null),
        h('button', { class: 'footer-button', 'data-ripple': true, 'aria-label': t('lang.label'),
          onclick: function () { lang = nextLang(); writePref('lang', lang); applyLang(); render(); } }, langSwitch()),
        h('div', { class: 'version', text: t('version') + ' ' + (meta.version || document.body.getAttribute('data-version') || '') })));
  }

  function renderError(files) {
    return h('section', { class: 'card state state-error', role: 'alert' },
      h('div', { class: 'state-icon danger' }, icon('alert')),
      h('h2', { class: 'state-title', text: t('error.title') }),
      h('p', { class: 'state-body', text: t('error.body', { files: files.join(', ') }) }),
      h('button', { class: 'button secondary', 'data-ripple': true, onclick: function () { location.reload(); } }, t('error.retry')));
  }

  function renderEmptyLibrary() {
    return h('section', { class: 'card state' },
      h('div', { class: 'state-icon' }, icon('film')),
      h('h2', { class: 'state-title', text: t('empty.library.title') }),
      h('p', { class: 'state-body', text: t('empty.library.body') }));
  }

  function renderRoute(route) {
    var head = route.parts[0];
    if (!head) return renderWall(route.query, null);
    if (head === 'work') return renderWork(route.parts[1]);
    if (head === 'performers') return renderRoster('performers', route.query);
    if (head === 'performer') return renderWall(Object.assign({}, route.query, { performers: [parseInt(route.parts[1], 10)] }), { kind: 'performers', value: parseInt(route.parts[1], 10) });
    if (head === 'studios') return renderRoster('studios', route.query);
    if (head === 'studio') return renderWall(Object.assign({}, route.query, { studios: [route.parts[1]] }), { kind: 'studios', value: route.parts[1] });
    if (head === 'series' && route.parts.length === 1) return renderRoster('series', route.query);
    if (head === 'series') return renderWall(Object.assign({}, route.query, { series: [route.parts[1]] }), { kind: 'series', value: route.parts[1] });
    if (head === 'tags') return renderRoster('tags', route.query);
    if (head === 'tag') return renderWall(Object.assign({}, route.query, { tags: [parseInt(route.parts[1], 10)] }), { kind: 'tags', value: parseInt(route.parts[1], 10) });
    if (head === 'unrecognized') return renderUnrecognized(route.query);
    if (head === 'stats') return renderStats();
    return renderWall(route.query, null);
  }

  /* ---------- 海报墙 ---------- */
  var FACET_DIMS = ['performers', 'studios', 'series', 'years', 'tags', 'kinds'];
  var expandedFacets = {};

  function facetLabel(dim, value) {
    if (dim === 'performers') return names.performers[value] || String(value);
    if (dim === 'tags') return names.tags[value] || String(value);
    if (dim === 'years') return value === 'none' ? t('filter.year.none') : String(value);
    if (dim === 'kinds') return t('kind.' + value);
    if (isUnrecognizedFacet(value)) return t('placeholder.unrecognized');
    return String(value);
  }

  function renderWall(state, fixed) {
    state = state || {};
    var sortKey = state.sort || 'date';
    var sortDir = state.dir || 'desc';
    var searched = core.searchWorks(works, state.q || '', { performers: names.performers, tags: names.tagsSearch });
    var filtered = core.filterWorks(searched, state);
    var sorted = core.sortWorks(filtered, sortKey, sortDir);
    var paged = sorted.length > PAGINATE_OVER ? core.paginate(sorted, state.page || 1, PAGE_SIZE) : { page: 1, pages: 1, items: sorted };
    var basePath = fixed ? location.hash.replace(/^#/, '').split('?')[0] : '/';

    function update(patch) {
      var next = Object.assign({}, state, patch);
      if (!('page' in patch)) delete next.page;
      Object.keys(next).forEach(function (key) {
        var value = next[key];
        if (value == null || value === '' || value === false || (Array.isArray(value) && !value.length)) delete next[key];
      });
      if (fixed) delete next[fixed.kind];
      navigate(basePath, next);
    }

    var title = t('nav.home');
    if (fixed) title = facetLabel(fixed.kind, fixed.value);

    var searchTimer = null;
    var searchInput = h('input', { class: 'input search-input', type: 'search', value: state.q || '', placeholder: t('search.placeholder'), 'aria-label': t('search.label'),
      oninput: function (e) {
        var value = e.target.value;
        clearTimeout(searchTimer);
        searchTimer = setTimeout(function () { update({ q: value }); }, DEBOUNCE_MS);
      } });

    var sortSelect = h('select', { class: 'input select', 'aria-label': t('sort.label'), onchange: function (e) {
      var pair = e.target.value.split(':'); update({ sort: pair[0], dir: pair[1] });
    } }, [['date', 'desc'], ['date', 'asc'], ['added', 'desc'], ['added', 'asc'], ['duration', 'desc'], ['duration', 'asc'], ['code', 'asc'], ['code', 'desc']].map(function (pair) {
      var value = pair.join(':');
      return h('option', { value: value, selected: value === sortKey + ':' + sortDir, text: t('sort.' + pair[0]) + ' · ' + t('sort.' + pair[1]) });
    }));

    var filterPanel = h('aside', { class: 'filters card', 'aria-label': t('filter.title') },
      h('div', { class: 'filters-head' }, h('h2', { class: 'card-title', text: t('filter.title') }),
        hasFilters(state) ? h('button', { class: 'button ghost small', 'data-ripple': true, onclick: function () { navigate(basePath, state.q ? { q: state.q, sort: state.sort, dir: state.dir } : { sort: state.sort, dir: state.dir }); } }, t('filter.clear')) : null),
      h('label', { class: 'check-row', 'data-ripple': true },
        h('input', { type: 'checkbox', checked: state.playable === true, onchange: function (e) { update({ playable: e.target.checked ? true : null }); } }),
        h('span', { text: t('filter.playable') })),
      FACET_DIMS.filter(function (dim) { return !fixed || fixed.kind !== dim; }).map(function (dim) {
        var counts = core.facetCounts(searched, dim);
        if (!counts.length) return null;
        var selected = state[dim] || [];
        var expanded = expandedFacets[dim];
        var shown = expanded ? counts : counts.slice(0, 8);
        return h('section', { class: 'facet' },
          h('h3', { class: 'facet-title', text: t('filter.' + dim) }),
          h('div', { class: 'facet-list' }, shown.map(function (entry) {
            var on = selected.indexOf(entry.value) !== -1;
            return h('label', { class: 'check-row' + (on ? ' on' : ''), 'data-ripple': true },
              h('input', { type: 'checkbox', checked: on, onchange: function (e) {
                var next = selected.filter(function (v) { return v !== entry.value; });
                if (e.target.checked) next.push(entry.value);
                var patch = {}; patch[dim] = next; update(patch);
              } }),
              h('span', { class: 'check-label', text: facetLabel(dim, entry.value), title: facetLabel(dim, entry.value) }),
              h('span', { class: 'count tabular', text: String(entry.count) }));
          })),
          counts.length > 8 ? h('button', { class: 'button ghost small', 'data-ripple': true, onclick: function () { expandedFacets[dim] = !expanded; render(); } }, expanded ? t('filter.less') : t('filter.more')) : null);
      }));

    var grid = paged.items.length
      ? h('div', { class: 'wall-grid' }, paged.items.map(renderCard))
      : h('div', { class: 'card state' },
        h('div', { class: 'state-icon' }, icon('search')),
        h('h2', { class: 'state-title', text: t('empty.title') }),
        h('p', { class: 'state-body', text: t('empty.body') }),
        h('button', { class: 'button soft', 'data-ripple': true, onclick: function () { navigate(basePath, {}); } }, t('filter.clear')));

    var pager = paged.pages > 1 ? h('nav', { class: 'pager', 'aria-label': t('list.page', { page: paged.page, pages: paged.pages }) },
      h('button', { class: 'button secondary', 'data-ripple': true, disabled: paged.page <= 1, onclick: function () { update({ page: paged.page - 1 }); } }, t('list.prev')),
      h('span', { class: 'pager-text tabular', text: t('list.page', { page: paged.page, pages: paged.pages }) }),
      h('button', { class: 'button secondary', 'data-ripple': true, disabled: paged.page >= paged.pages, onclick: function () { update({ page: paged.page + 1 }); } }, t('list.next'))) : null;

    return h('div', { class: 'page wall-page' },
      h('header', { class: 'page-head' },
        h('div', null, h('h1', { class: 'page-title', text: title }), h('p', { class: 'page-sub tabular', text: t('list.count', { n: sorted.length }) })),
        h('div', { class: 'toolbar' }, h('div', { class: 'search-wrap' }, icon('search'), searchInput), sortSelect)),
      h('div', { class: 'wall-layout' }, h('div', { class: 'wall-main' }, grid, pager), filterPanel));
  }

  function hasFilters(state) {
    return FACET_DIMS.some(function (dim) { return state[dim] && state[dim].length; }) || state.playable === true;
  }

  function imageOrPlaceholder(src, alt, className) {
    if (src) return h('img', { class: className, src: core.encodeMediaPath(src), alt: alt, loading: 'lazy', decoding: 'async',
      onerror: function (e) { var ph = placeholder(className); e.target.replaceWith(ph); } });
    return placeholder(className);
  }
  function placeholder(className) { return h('div', { class: className + ' placeholder', 'aria-label': t('image.none') }, icon('image')); }

  function badge(text, kind) { return h('span', { class: 'pill ' + (kind || ''), text: text }); }

  function playBadge(verdict) {
    if (verdict === 'yes') return badge(t('play.yes'), 'success');
    if (verdict === 'maybe') return badge(t('play.maybe'), 'warning');
    return badge(t('play.no'), 'danger');
  }

  function renderCard(work) {
    var performers = (work.performers || []).slice(0, 3).map(function (id) { return names.performers[id]; }).filter(Boolean);
    var verdict = core.workPlayability(work, canPlayType);
    // 图集用横版官方封面（cover），竖版海报（poster）只在没有封面时兜底。
    return h('a', { class: 'work-card card', href: '#/work/' + encodeURIComponent(work.id), 'data-ripple': true },
      h('div', { class: 'cover-wrap' },
        imageOrPlaceholder(work.cover || work.poster, work.code + ' ' + (work.title || ''), 'cover'),
        h('div', { class: 'cover-badges' }, work.definition ? badge(work.definition, 'neutral') : null, badge(t('kind.' + (work.kind || 'other')), 'primary')),
        (work.parts || []).length > 1 ? h('div', { class: 'cover-parts tabular', text: '×' + work.parts.length }) : null),
      h('div', { class: 'work-body' },
        h('div', { class: 'work-code mono', text: work.code || t('placeholder.unrecognized') }),
        h('div', { class: 'work-title', text: work.title || t('work.untitled'), title: work.title || '' }),
        performers.length ? h('div', { class: 'work-meta', text: performers.join('、') }) : null,
        h('div', { class: 'work-foot' }, h('span', { class: 'tabular', text: core.formatDuration(work.duration) }), playBadge(verdict))));
  }

  /* ---------- 详情 ---------- */
  var currentPart = {};
  function basePathOnDisk() {
    var base = location.href.split('#')[0].replace(/index\.html?$/i, '');
    var path = base.replace(/^file:\/\//i, '');
    try { path = decodeURIComponent(path); } catch (e) { /* 保留原样 */ }
    if (/^\/[A-Za-z]:\//.test(path)) path = path.slice(1).replace(/\//g, '\\');
    return path;
  }
  function absolutePath(rel) {
    var base = basePathOnDisk();
    return /\\/.test(base) ? base + rel.replace(/\//g, '\\') : base + rel;
  }

  function copyPath(text, button) {
    function done(ok) {
      var label = button.querySelector('.label');
      var old = label.textContent;
      label.textContent = ok ? t('play.copied') : t('play.copyFailed');
      setTimeout(function () { label.textContent = old; }, 1500);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { done(true); }, function () { done(false); });
    } else done(false);
  }

  function renderPlayer(part, parts, onSwitch, label) {
    var verdict = core.canPlay(part, canPlayType);
    var box = h('section', { class: 'card player' });
    if (parts.length > 1) {
      box.appendChild(h('div', { class: 'segmented', role: 'tablist', 'aria-label': t('work.parts') }, parts.map(function (p, index) {
        var on = p === part;
        return h('button', { class: 'segment' + (on ? ' on' : ''), role: 'tab', 'aria-selected': on ? 'true' : 'false', 'data-ripple': true, onclick: function () { onSwitch(index); } },
          t('work.part', { n: p.part || index + 1 }));
      })));
    }
    if (verdict === 'maybe') box.appendChild(h('p', { class: 'hint warning-text', text: t('play.hint.maybe') }));
    if (verdict !== 'no') {
      box.appendChild(h('video', { class: 'video', controls: true, preload: 'metadata', src: core.encodeMediaPath(part.path), 'aria-label': label }));
    } else {
      box.appendChild(h('p', { class: 'hint', text: t('play.hint.no', { container: part.container || t('unknown'), vcodec: part.vcodec || t('unknown'), acodec: part.acodec || t('unknown') }) }));
    }
    var absolute = absolutePath(part.path);
    var button = h('button', { class: 'button secondary', 'data-ripple': true }, icon('copy'), h('span', { class: 'label', text: t('play.copy') }));
    button.addEventListener('click', function () { copyPath(absolute, button); });
    box.appendChild(h('div', { class: 'path-row' }, button, h('code', { class: 'path mono', text: absolute })));
    return box;
  }

  function renderWork(id) {
    var work = byId[id];
    if (!work) {
      return h('div', { class: 'page' }, h('div', { class: 'card state' }, h('div', { class: 'state-icon' }, icon('help')),
        h('h2', { class: 'state-title', text: t('work.notFound') }),
        h('a', { class: 'button soft', href: '#/', 'data-ripple': true }, t('work.back'))));
    }
    var parts = work.parts || [];
    var index = Math.min(currentPart[id] || 0, Math.max(0, parts.length - 1));
    var part = parts[index] || {};
    var label = work.code + ' ' + (work.title || '');

    function rows() {
      var list = [
        ['work.code', h('span', { class: 'mono', text: work.code || t('placeholder.unrecognized') })],
        ['work.title', work.title || t('work.untitled')],
        work.originalTitle ? ['work.originalTitle', work.originalTitle] : null,
        ['work.studio', work.studio ? h('a', { href: '#/studio/' + encodeURIComponent(work.studio), text: facetLabel('studios', work.studio) }) : t('unknown')],
        work.series ? ['work.series', h('a', { href: '#/series/' + encodeURIComponent(work.series), text: facetLabel('series', work.series) })] : null,
        ['work.date', work.date || t('unknown')],
        ['work.duration', core.formatDuration(work.duration) || t('unknown')],
        ['work.resolution', work.width && work.height ? work.width + '×' + work.height + (work.definition ? ' · ' + work.definition : '') : t('unknown')],
        ['work.codec', [part.container, part.vcodec, part.acodec].filter(Boolean).join(' / ') || t('unknown')],
        ['work.kind', t('kind.' + (work.kind || 'other'))],
        ['work.files', core.formatBytes(work.size) || t('unknown')]
      ].filter(Boolean);
      return h('dl', { class: 'info' }, list.map(function (row) {
        return [h('dt', { text: t(row[0]) }), h('dd', null, row[1])];
      }));
    }

    var performers = (work.performers || []).map(function (pid) {
      var name = names.performers[pid] || String(pid);
      var avatar = avatarOf(pid);
      return h('a', { class: 'chip-link', href: '#/performer/' + pid, 'data-ripple': true },
        avatar ? h('img', { class: 'avatar', src: core.encodeMediaPath(avatar), alt: '' }) : h('span', { class: 'avatar', text: name.charAt(0) }),
        h('span', { text: name }));
    });
    var tags = (work.tags || []).map(function (tid) {
      return h('a', { class: 'pill primary link', href: '#/tag/' + tid, text: names.tags[tid] || String(tid) });
    });
    // 出处是外链（新开标签），不是资源加载：站点自己不请求外网。
    var sources = (work.sources || []).filter(function (s) { return s && /^https:\/\//.test(s.url); }).map(function (s) {
      return h('a', { class: 'pill link', href: s.url, target: '_blank', rel: 'noopener noreferrer', text: s.source });
    });

    var player = renderPlayer(part, parts, function (next) { currentPart[id] = next; render(); }, label);

    var sheetSrc = part.sheet || work.sheet;
    var sheet = sheetSrc ? h('section', { class: 'card' },
      h('h2', { class: 'card-title', text: t('work.sheet') }),
      h('button', { class: 'sheet-button', 'data-ripple': true, 'aria-label': t('work.sheet'), onclick: function () { openOverlay(sheetSrc, label); } },
        imageOrPlaceholder(sheetSrc, t('work.sheet') + ' ' + work.code, 'sheet'))) : null;

    function related(labelKey, predicate) {
      var items = works.filter(function (other) { return other.id !== work.id && predicate(other); }).slice(0, RELATED_MAX);
      if (!items.length) return null;
      return h('section', { class: 'related' }, h('h2', { class: 'card-title', text: t(labelKey) }),
        h('div', { class: 'related-row' }, items.map(renderCard)));
    }
    var performerSet = work.performers || [];

    return h('div', { class: 'page work-page' },
      h('header', { class: 'page-head' },
        h('div', null,
          h('a', { class: 'back-link', href: '#/', 'data-ripple': true }, icon('back'), h('span', { text: t('work.back') })),
          h('h1', { class: 'page-title', text: work.code || t('placeholder.unrecognized') }),
          h('p', { class: 'page-sub', text: work.title || t('work.untitled') }))),
      h('div', { class: 'work-top' },
        h('section', { class: 'card cover-card' }, imageOrPlaceholder(work.cover || work.poster, t('image.cover') + ' ' + work.code, 'cover')),
        h('section', { class: 'card info-card' }, rows(),
          performers.length ? h('div', { class: 'info-block' }, h('h3', { class: 'facet-title', text: t('work.performers') }), h('div', { class: 'chips' }, performers)) : null,
          tags.length ? h('div', { class: 'info-block' }, h('h3', { class: 'facet-title', text: t('work.tags') }), h('div', { class: 'chips' }, tags)) : null,
          work.plot ? h('div', { class: 'info-block' }, h('h3', { class: 'facet-title', text: t('work.plot') }), h('p', { class: 'plot', text: work.plot })) : null,
          sources.length ? h('div', { class: 'info-block' }, h('h3', { class: 'facet-title', text: t('work.sources') }), h('div', { class: 'chips' }, sources)) : null)),
      player,
      sheet,
      performerSet.length ? related('work.related.performer', function (o) { return (o.performers || []).some(function (p) { return performerSet.indexOf(p) !== -1; }); }) : null,
      work.series ? related('work.related.series', function (o) { return o.series === work.series; }) : null,
      work.studio ? related('work.related.studio', function (o) { return o.studio === work.studio; }) : null);
  }

  function openOverlay(src, label) {
    var overlay = h('div', { class: 'image-overlay', role: 'dialog', 'aria-modal': 'true', 'aria-label': label, tabindex: '-1' });
    function close() { overlay.remove(); document.removeEventListener('keydown', onKey); }
    function onKey(e) { if (e.key === 'Escape') close(); }
    overlay.appendChild(h('button', { class: 'icon-button overlay-close', 'data-ripple': true, 'aria-label': t('overlay.close'), onclick: close }, icon('x')));
    overlay.appendChild(h('img', { src: core.encodeMediaPath(src), alt: label }));
    overlay.addEventListener('click', function (e) { if (e.target === overlay) close(); });
    document.addEventListener('keydown', onKey);
    document.body.appendChild(overlay);
    overlay.focus();
  }

  /* ---------- 名册 ---------- */
  var ROSTER = {
    performers: { title: 'nav.performers', link: function (item) { return '#/performer/' + item.id; } },
    studios: { title: 'nav.studios', link: function (item) { return '#/studio/' + encodeURIComponent(item.id); } },
    series: { title: 'nav.series', link: function (item) { return '#/series/' + encodeURIComponent(item.id); } },
    tags: { title: 'nav.tags', link: function (item) { return '#/tag/' + item.id; } }
  };

  function renderRoster(kind, state) {
    var spec = ROSTER[kind];
    var items = entities[kind] || [];
    var query = (state.q || '').toLowerCase();
    var shown = query ? items.filter(function (item) { return String(item.name).toLowerCase().indexOf(query) !== -1; }) : items;
    var timer = null;
    var input = h('input', { class: 'input search-input', type: 'search', value: state.q || '', placeholder: t('roster.search'), 'aria-label': t('roster.search'),
      oninput: function (e) { var value = e.target.value; clearTimeout(timer); timer = setTimeout(function () { navigate('/' + kind, value ? { q: value } : {}); }, DEBOUNCE_MS); } });
    return h('div', { class: 'page' },
      h('header', { class: 'page-head' },
        h('div', null, h('h1', { class: 'page-title', text: t(spec.title) }), h('p', { class: 'page-sub tabular', text: String(items.length) })),
        h('div', { class: 'toolbar' }, h('div', { class: 'search-wrap' }, icon('search'), input))),
      shown.length ? h('div', { class: 'roster-grid' }, shown.map(function (item) {
        return h('a', { class: 'roster-item card', href: spec.link(item), 'data-ripple': true },
          item.avatar ? h('img', { class: 'avatar large', src: core.encodeMediaPath(item.avatar), alt: item.name }) : h('span', { class: 'avatar large', text: String(item.name || '?').charAt(0) }),
          h('div', { class: 'roster-text' }, h('div', { class: 'roster-name', text: item.name, title: item.name }), h('div', { class: 'roster-count', text: t('roster.count', { n: item.count }) })));
      })) : h('div', { class: 'card state' }, h('div', { class: 'state-icon' }, icon('search')), h('h2', { class: 'state-title', text: query ? t('empty.title') : t('roster.empty') }),
        query ? h('button', { class: 'button soft', 'data-ripple': true, onclick: function () { navigate('/' + kind, {}); } }, t('filter.clear')) : null));
  }

  /* ---------- 未识别 ---------- */
  var selectedUnrecognized = null;
  function renderUnrecognized(state) {
    var query = (state.q || '').toLowerCase();
    var shown = query ? unrecognized.filter(function (item) { return (item.name + ' ' + item.path).toLowerCase().indexOf(query) !== -1; }) : unrecognized;
    var timer = null;
    var input = h('input', { class: 'input search-input', type: 'search', value: state.q || '', placeholder: t('roster.search'), 'aria-label': t('roster.search'),
      oninput: function (e) { var value = e.target.value; clearTimeout(timer); timer = setTimeout(function () { navigate('/unrecognized', value ? { q: value } : {}); }, DEBOUNCE_MS); } });
    var selected = shown.filter(function (item) { return item.id === selectedUnrecognized; })[0] || null;
    var table = shown.length ? h('div', { class: 'table-wrap card' }, h('table', { class: 'table' },
      h('thead', null, h('tr', null, [t('unrecognized.name'), t('unrecognized.path'), t('unrecognized.size'), t('unrecognized.duration'), t('unrecognized.play')].map(function (label, i) {
        return h('th', { class: i >= 2 ? 'num' : '', text: label });
      }))),
      h('tbody', null, shown.map(function (item) {
        var verdict = core.canPlay(item, canPlayType);
        return h('tr', { class: 'row-button' + (item.id === selectedUnrecognized ? ' on' : ''), tabindex: '0', 'data-ripple': true,
          onclick: function () { selectedUnrecognized = item.id; render(); },
          onkeydown: function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectedUnrecognized = item.id; render(); } } },
          h('td', { class: 'mono', text: item.name }), h('td', { class: 'mono path-cell', text: item.path, title: item.path }),
          h('td', { class: 'num tabular', text: core.formatBytes(item.size) }), h('td', { class: 'num tabular', text: core.formatDuration(item.duration) }),
          h('td', { class: 'num' }, playBadge(verdict)));
      })))) : h('div', { class: 'card state' }, h('div', { class: 'state-icon' }, icon('help')), h('h2', { class: 'state-title', text: t('unrecognized.empty') }));
    return h('div', { class: 'page' },
      h('header', { class: 'page-head' },
        h('div', null, h('h1', { class: 'page-title', text: t('unrecognized.title') }), h('p', { class: 'page-sub', text: t('unrecognized.body') + ' ' + t('list.count', { n: shown.length }) })),
        h('div', { class: 'toolbar' }, h('div', { class: 'search-wrap' }, icon('search'), input))),
      selected ? renderPlayer(selected, [selected], function () {}, selected.name) : null,
      table);
  }

  /* ---------- 统计 ---------- */
  function renderStats() {
    var total = works.length;
    var duration = meta.totalDuration != null ? meta.totalDuration : works.reduce(function (s, w) { return s + (w.duration || 0); }, 0);
    var bytes = meta.totalBytes != null ? meta.totalBytes : works.reduce(function (s, w) { return s + (w.size || 0); }, 0);
    var cards = [
      ['stats.works', String(total), 'film', 'blue'],
      ['stats.duration', core.formatDuration(duration) || '0:00', 'clock', 'success'],
      ['stats.bytes', core.formatBytes(bytes) || '0 B', 'drive', 'warning'],
      ['stats.performers', String((entities.performers || []).length), 'users', 'primary']
    ];
    function table(titleKey, headKey, rows) {
      return h('section', { class: 'card' }, h('h2', { class: 'card-title', text: t(titleKey) }),
        h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
          h('thead', null, h('tr', null, h('th', { text: t(headKey) }), h('th', { class: 'num', text: t('stats.count') }))),
          h('tbody', null, rows.map(function (row) { return h('tr', null, h('td', { text: row[0] }), h('td', { class: 'num tabular', text: String(row[1]) })); })))));
    }
    var kinds = core.facetCounts(works, 'kinds').map(function (e) { return [t('kind.' + e.value), e.count]; });
    var years = core.facetCounts(works, 'years').sort(function (a, b) { return a.value === 'none' ? 1 : b.value === 'none' ? -1 : b.value - a.value; })
      .map(function (e) { return [e.value === 'none' ? t('filter.year.none') : String(e.value), e.count]; });
    return h('div', { class: 'page' },
      h('header', { class: 'page-head' }, h('div', null, h('h1', { class: 'page-title', text: t('stats.title') }),
        h('p', { class: 'page-sub', text: t('stats.builtAt') + ' ' + (meta.builtAt || '') }))),
      h('div', { class: 'stat-grid' }, cards.map(function (card) {
        return h('section', { class: 'card stat-card' }, h('div', { class: 'stat-icon ' + card[3] }, icon(card[2])),
          h('div', { class: 'stat-label', text: t(card[0]) }), h('div', { class: 'stat-value tabular', text: card[1] }));
      })),
      h('div', { class: 'two-col' }, table('stats.byKind', 'stats.kind', kinds), table('stats.byYear', 'stats.year', years)));
  }

  /* ---------- 启动 ---------- */
  function render() {
    var route = parseHash();
    renderShell(route);
    if (!drawerOpen) window.scrollTo(0, 0);
  }
  document.addEventListener('click', function (e) {
    if (themeMenuOpen && !e.target.closest('.theme-wrap')) { themeMenuOpen = false; render(); }
  });
  window.addEventListener('hashchange', function () { drawerOpen = false; themeMenuOpen = false; render(); });
  window.addEventListener('keydown', function (e) {
    if (e.key === '/' && document.activeElement && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) {
      var box = document.querySelector('.search-input');
      if (box) { e.preventDefault(); box.focus(); }
    }
  });
  applyLang();
  render();
})();
