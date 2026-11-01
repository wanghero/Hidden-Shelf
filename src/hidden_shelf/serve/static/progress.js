/* 藏片阁 进度网页入口：表单、步骤列表、日志、SSE 客户端、toast、主题与语言。纯逻辑在 ShelfProgressCore。
 * 所有 POST 带 X-Shelf-Request: 1（服务端同源防护）。文案全部走 t(key)。 */
(function () {
  'use strict';

  var core = window.ShelfProgressCore;
  var dict = window.ShelfServeI18n || { zh: {}, en: {} };
  var boot = window.__shelfServe || {};
  var STEPS = boot.steps || ['scan', 'import', 'scrape', 'organize', 'media', 'build'];
  var LOG_LIMIT = 5000;
  var DISCONNECT_GRACE_MS = 10000;
  var TOAST_MS = 4000;

  /* ---------- 偏好 ---------- */
  function readPref(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
  function writePref(key, value) { try { if (value == null) localStorage.removeItem(key); else localStorage.setItem(key, value); } catch (e) { /* 私密模式 */ } }
  var LANGS = ['zh', 'en', 'ja'];
  var LANG_TAGS = { zh: 'zh-CN', en: 'en', ja: 'ja' };
  var LANG_SHORT = { zh: 'CH', en: 'EN', ja: 'JP' };
  var lang = (function () {
    var saved = readPref('lang');
    if (LANGS.indexOf(saved) !== -1) return saved;
    var nav = navigator.language || '';
    return /^zh/i.test(nav) ? 'zh' : /^ja/i.test(nav) ? 'ja' : 'en';
  })();
  function nextLang() { return LANGS[(LANGS.indexOf(lang) + 1) % LANGS.length]; }
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
    if (vars) Object.keys(vars).forEach(function (name) { text = text.split('{' + name + '}').join(String(vars[name])); });
    return text;
  }
  function applyLang() { document.documentElement.lang = LANG_TAGS[lang] || 'en'; document.title = t('app.name') + ' · ' + t('page.title'); }
  function themePref() { var saved = readPref('theme'); return saved === 'light' || saved === 'dark' ? saved : 'system'; }
  function applyTheme(value) {
    if (value === 'light' || value === 'dark') { document.documentElement.dataset.theme = value; writePref('theme', value); }
    else { delete document.documentElement.dataset.theme; writePref('theme', null); }
  }

  /* ---------- DOM 小工具 ---------- */
  function h(tag, attrs) {
    var el = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (name) {
      var value = attrs[name];
      if (value == null || value === false) return;
      if (name === 'class') el.className = value;
      else if (name === 'text') el.textContent = value;
      else if (name === 'html') el.innerHTML = value;
      else if (name.indexOf('on') === 0 && typeof value === 'function') el.addEventListener(name.slice(2), value);
      else el.setAttribute(name, value === true ? '' : value);
    });
    for (var i = 2; i < arguments.length; i++) append(el, arguments[i]);
    return el;
  }
  function append(parent, child) {
    if (child == null || child === false) return;
    if (Array.isArray(child)) { child.forEach(function (c) { append(parent, c); }); return; }
    parent.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
  }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }
  //: 本地读不到 CHANGELOG.md 时，空状态里给的外链。
  var CHANGELOG_URL = 'https://github.com/wanghero/Hidden-Shelf/blob/main/CHANGELOG.md';
  var ICONS = {
    film: '<rect x="2" y="2" width="20" height="20" rx="2"/><path d="M7 2v20M17 2v20M2 12h20M2 7h5M2 17h5M17 17h5M17 7h5"/>',
    play: '<polygon points="6 3 20 12 6 21 6 3"/>',
    square: '<rect x="5" y="5" width="14" height="14" rx="2"/>',
    monitor: '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
    moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9z"/>',
    menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    alert: '<circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/>',
    terminal: '<path d="m4 17 6-6-6-6"/><path d="M12 19h8"/>',
    external: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><path d="M15 3h6v6"/><path d="M10 14 21 3"/>',
    down: '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
    loader: '<path d="M21 12a9 9 0 1 1-6.22-8.56"/>',
    info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
    folder: '<path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/>',
    drive: '<path d="M22 12H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/><path d="M6 16h.01M10 16h.01"/>',
    home: '<path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
    up: '<polyline points="14 9 9 4 4 9"/><path d="M20 20h-7a4 4 0 0 1-4-4V4"/>',
    chevron: '<path d="m9 18 6-6-6-6"/>',
    sliders: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3"/><path d="M1 14h6M9 8h6M17 16h6"/>',
    scroll: '<path d="M8 21h12a2 2 0 0 0 2-2v-2H10v2a2 2 0 1 1-4 0V5a2 2 0 1 0-4 0v3h4"/><path d="M19 17V5a2 2 0 0 0-2-2H4"/><path d="M12 9h4M12 13h4"/>'
  };
  function icon(name) {
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (ICONS[name] || '') + '</svg>';
    return h('span', { class: 'icon', html: svg });
  }

  /* ---------- 状态 ---------- */
  var state = core.initialState(STEPS);
  var events = [];
  var recentRoots = [];
  var logFilter = 'all';
  var source = null;
  var connected = false;
  var disconnectTimer = null;
  var logError = false;
  var loading = true;
  var starting = false;
  var following = true;
  var drawerOpen = false;
  var themeMenuOpen = false;
  var refs = {};
  var sourcesInfo = null;        // GET /api/sources 的响应
  var sourcesError = null;
  var sourcesTimer = null;
  /* 三个视图：运行（表单 + 步骤）、设置（盘上选项 + 来源与登录）、日志。用 hash 路由，刷新后停在原页。
     「更新记录」是第四个视图，但不占侧栏一项——入口是侧栏底部的版本号。 */
  var VIEWS = ['run', 'settings', 'log'];
  var EXTRA_VIEWS = ['changelog'];
  var VIEW_ICONS = { run: 'terminal', settings: 'sliders', log: 'scroll' };
  function viewFromHash() {
    var name = (location.hash || '').replace(/^#\/?/, '');
    return VIEWS.indexOf(name) === -1 && EXTRA_VIEWS.indexOf(name) === -1 ? 'run' : name;
  }
  var view = viewFromHash();
  /* 表单值与视图无关，存在这里；切页重建 DOM 时从这里回填。images/sheets 是盘的设置，开始时一并发给服务端写进盘上配置。 */
  var opts = { root: '', move: true, offline: false, dryRun: false, force: false, images: true, sheets: true };

  function api(method, path, body) {
    var options = { method: method, headers: { 'X-Shelf-Request': '1' } };
    if (body !== undefined) { options.headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(body); }
    return fetch(path, options).then(function (response) {
      return response.text().then(function (text) {
        var data = null;
        try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
        return { ok: response.ok, status: response.status, data: data || {} };
      });
    });
  }

  /* ---------- SSE ---------- */
  function connect(runId, fromSeq) {
    disconnect();
    if (!runId) return;
    source = new EventSource('/api/events?run=' + encodeURIComponent(runId));
    var first = true;
    source.onopen = function () {
      connected = true;
      logError = false;
      clearTimeout(disconnectTimer);
      disconnectTimer = null;
      update();
    };
    ['run.start', 'step.start', 'step.progress', 'step.done', 'step.failed', 'step.skipped', 'run.done', 'run.cancelled'].forEach(function (kind) {
      source.addEventListener(kind, function (message) {
        var event;
        try { event = JSON.parse(message.data); } catch (e) { return; }
        if (event.seq <= state.lastSeq && !first) return;
        first = false;
        handle(event);
      });
    });
    source.onerror = function () {
      connected = false;
      if (!state.running) { disconnect(); update(); return; }
      if (!disconnectTimer) disconnectTimer = setTimeout(function () { logError = true; update(); }, DISCONNECT_GRACE_MS);
      update();
    };
    void fromSeq;
  }
  function disconnect() {
    if (source) { source.close(); source = null; }
    connected = false;
  }

  function handle(event) {
    events.push(event);
    if (events.length > LOG_LIMIT + 500) events.splice(0, events.length - LOG_LIMIT);
    var wasRunning = state.running;
    state = core.reduce(state, event);
    if (event.kind === 'run.start') { clearLog(); }
    if (event.kind === 'step.progress' || event.kind === 'step.failed' || event.kind === 'step.skipped') appendLog(event);
    if (event.kind === 'run.done' || event.kind === 'run.cancelled') {
      disconnect();
      if (event.kind === 'run.cancelled') toast('info', t('toast.cancelled'));
      else if (state.result && state.result.ok && state.result.dry_run) toast('success', t('toast.dry_run'));
      else if (state.result && state.result.ok) toast('success', t('toast.done'));
      else if (state.result && !state.result.failed_step) toast('danger', t('toast.failed.setup'), true);
      else toast('danger', t('toast.failed', { step: stepLabel(state.result && state.result.failed_step) }), true);
    }
    void wasRunning;
    update();
  }

  function stepLabel(name) { return name ? t('step.' + name) : ''; }

  /* ---------- 初始化 ---------- */
  function load() {
    loading = true;
    return api('GET', '/api/state').then(function (response) {
      loading = false;
      if (!response.ok) { logError = true; update(); return; }
      var data = response.data;
      recentRoots = data.recent_roots || [];
      if (data.run) {
        events = [];
        clearLog();
        connect(data.run, 0);
      }
      update();
    }).catch(function () { loading = false; logError = true; update(); });
  }

  /* ---------- 动作 ---------- */
  function start() {
    var root = (refs.root ? refs.root.value : opts.root).trim();
    opts.root = root;
    if (!root) { showFieldError(t('form.root.required')); if (refs.root) refs.root.focus(); return; }
    showFieldError('');
    starting = true;
    update();
    api('POST', '/api/run', { root: root, move_unrecognized: opts.move, offline: opts.offline, force_scrape: opts.force, dry_run: opts.dryRun, images_in_work_dir: opts.images, sheets: opts.sheets })
      .then(function (response) {
        starting = false;
        if (response.status === 202) {
          events = [];
          clearLog();
          state = core.initialState(STEPS);
          connect(response.data.run, 0);
          toast('info', t('toast.started', { root: root }));
          if (recentRoots.indexOf(root) === -1) recentRoots.unshift(root);
        } else if (response.status === 409) {
          toast('danger', t('toast.busy'), true);
          load();
        } else {
          showFieldError(response.data.error || String(response.status));
          if (refs.root) refs.root.focus();
        }
        update();
      })
      .catch(function (error) { starting = false; toast('danger', t('toast.request.failed', { error: String(error && error.message || error) }), true); update(); });
  }
  function stop() {
    api('POST', '/api/cancel').then(function (response) {
      if (!response.ok && response.status !== 409) toast('danger', t('toast.request.failed', { error: response.data.error || response.status }), true);
      load();
    }).catch(function (error) { toast('danger', t('toast.request.failed', { error: String(error && error.message || error) }), true); });
  }
  function openResult() {
    var root = state.root || (refs.root ? refs.root.value : opts.root).trim();
    api('POST', '/api/open', { root: root }).then(function (response) {
      if (response.ok) toast('success', t('toast.open.ok'));
      else toast('danger', response.data.error || t('toast.open.failed'), true);
    }).catch(function (error) { toast('danger', t('toast.request.failed', { error: String(error && error.message || error) }), true); });
  }
  function showFieldError(text) {
    if (!refs.rootError) { if (text) toast('danger', text, true); return; }
    refs.rootError.textContent = text;
    refs.rootError.hidden = !text;
    refs.root.classList.toggle('invalid', !!text);
    refs.root.setAttribute('aria-invalid', text ? 'true' : 'false');
  }

  /* ---------- Toast ---------- */
  function toast(kind, text, sticky) {
    var box = refs.toasts;
    if (!box) return;
    while (box.children.length >= 3) box.removeChild(box.firstChild);
    var item = h('div', { class: 'toast ' + kind, role: kind === 'danger' ? 'alert' : 'status' },
      icon(kind === 'success' ? 'check' : kind === 'danger' ? 'alert' : 'info'), h('span', { class: 'toast-text', text: text }),
      h('button', { class: 'icon-button', 'data-ripple': true, 'aria-label': t('menu.close'), onclick: function () { if (item.parentNode) item.parentNode.removeChild(item); } }, icon('x')));
    box.appendChild(item);
    if (!sticky) setTimeout(function () { if (item.parentNode) item.parentNode.removeChild(item); }, TOAST_MS);
  }

  /* ---------- 目录选择弹窗 ----------
   * 列目录由后端 /api/browse 做（浏览器拿不到本机绝对路径）。「选择此目录」选的是当前浏览到的目录（面包屑最后一段）。
   * 壳只在打开与换语言时建一次（buildPicker），导航只刷新面包屑、位置、列表与脚部（updatePicker）。 */
  var picker = { open: false, path: null, listing: null, roots: [], loading: false, error: null, selected: null,
    showHidden: readPref('browse.hidden') === '1', host: null, trigger: null, refs: null, token: 0 };

  function browseErrorText(response) {
    if (response.status === 403) return t('browse.error.403');
    if (response.status === 404) return t('browse.error.404');
    return t('browse.error.generic', { error: (response.data && response.data.error) || response.status });
  }
  function browseFailure(error) { return t('browse.error.generic', { error: String(error && error.message || error) }); }

  function openPicker(trigger) {
    if (picker.open) return;
    picker.open = true; picker.trigger = trigger || null; picker.loading = true; picker.error = null; picker.listing = null; picker.selected = null;
    picker.host = h('div', { class: 'dialog-backdrop', onclick: function (e) { if (e.target === picker.host) closePicker(); } });
    document.body.appendChild(picker.host);
    document.documentElement.classList.add('dialog-open');
    buildPicker();
    var token = ++picker.token;
    api('GET', core.browseUrl(null, false)).then(function (response) {
      if (token !== picker.token) return;
      picker.roots = response.ok ? (response.data.roots || []) : [];
      // 起点：输入框的值 → 上次选的 → 用户目录；前一个打不开就试下一个，全失败就停在第一个并显示它的错。
      var candidates = [refs.root.value.trim(), readPref('browse.last'), picker.roots.length ? picker.roots[0].path : null]
        .filter(function (p, i, all) { return p && all.indexOf(p) === i; });
      return tryCandidates(candidates, 0, null, token);
    }).catch(function (error) { if (token !== picker.token) return; picker.loading = false; picker.error = browseFailure(error); updatePicker(); });
  }
  function tryCandidates(candidates, index, firstFailure, token) {
    if (index >= candidates.length) {
      picker.loading = false;
      if (firstFailure) { picker.path = firstFailure.path; picker.error = firstFailure.error; }
      updatePicker();
      return null;
    }
    var path = candidates[index];
    return api('GET', core.browseUrl(path, picker.showHidden)).then(function (response) {
      if (token !== picker.token) return null;
      if (response.ok) { picker.loading = false; picker.path = path; picker.listing = response.data; picker.error = null; updatePicker(); return null; }
      return tryCandidates(candidates, index + 1, firstFailure || { path: path, error: browseErrorText(response) }, token);
    });
  }
  function navigate(path) {
    var token = ++picker.token;
    picker.loading = true; picker.error = null; picker.selected = null; picker.path = path;
    updatePicker();
    api('GET', core.browseUrl(path, picker.showHidden)).then(function (response) {
      if (token !== picker.token) return;
      picker.loading = false;
      if (response.ok) { picker.listing = response.data; picker.error = null; }
      else { picker.listing = null; picker.error = browseErrorText(response); }
      updatePicker();
      // 焦点落在被重绘掉的元素上（列表项、面包屑）就挪到新列表；在开关、按钮上就不动。
      var active = document.activeElement;
      if (!active || active === document.body || !picker.refs.dialog.contains(active)) focusList();
    }).catch(function (error) { if (token !== picker.token) return; picker.loading = false; picker.listing = null; picker.error = browseFailure(error); updatePicker(); });
  }
  function closePicker() {
    if (!picker.open) return;
    picker.open = false; picker.token++;
    if (picker.host && picker.host.parentNode) picker.host.parentNode.removeChild(picker.host);
    picker.host = null; picker.refs = null;
    document.documentElement.classList.remove('dialog-open');
    var trigger = picker.trigger || refs.browseButton;
    if (trigger && trigger.focus) trigger.focus();
  }
  function choosePicked() {
    if (state.running || picker.loading || picker.error || !picker.path) return;
    opts.root = picker.path;
    if (refs.root) refs.root.value = picker.path;
    refs.root.dispatchEvent(new Event('input', { bubbles: true }));
    writePref('browse.last', picker.path);
    closePicker();
  }
  function parentOfCurrent() {
    if (picker.listing) return picker.listing.parent || null;
    var crumbs = core.breadcrumbs(picker.path);
    return crumbs.length > 1 ? crumbs[crumbs.length - 2].path : null;
  }
  function selectEntry(path) {
    picker.selected = path;
    var items = picker.refs ? picker.refs.listWrap.querySelectorAll('.browse-item') : [];
    for (var i = 0; i < items.length; i++) items[i].setAttribute('aria-selected', items[i].getAttribute('data-path') === path ? 'true' : 'false');
  }
  function focusList() {
    var p = picker.refs; if (!p) return;
    var first = p.listWrap.querySelector('.browse-item');
    (first || p.dialog).focus();
  }
  function listKeydown(e) {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    var items = Array.prototype.slice.call(picker.refs.listWrap.querySelectorAll('.browse-item'));
    if (!items.length) return;
    e.preventDefault();
    var index = items.indexOf(document.activeElement);
    var next = index === -1 ? (e.key === 'ArrowDown' ? 0 : items.length - 1) : (e.key === 'ArrowDown' ? Math.min(items.length - 1, index + 1) : Math.max(0, index - 1));
    items[next].focus();
    selectEntry(items[next].getAttribute('data-path'));
  }
  function trapTab(e) {
    if (e.key !== 'Tab' || !picker.refs) return;
    var focusable = picker.refs.dialog.querySelectorAll('button:not(:disabled), input:not(:disabled)');
    if (!focusable.length) return;
    var first = focusable[0], last = focusable[focusable.length - 1];
    if (e.shiftKey && (document.activeElement === first || document.activeElement === picker.refs.dialog)) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }

  function buildPicker() {
    if (!picker.host) return;
    clear(picker.host);
    var p = {};
    picker.refs = p;
    p.crumbs = h('nav', { class: 'crumbs', 'aria-label': t('browse.title') });
    p.locations = h('div', { class: 'browse-locations' });
    p.listWrap = h('div', { class: 'browse-list-wrap', onkeydown: listKeydown });
    p.hidden = h('input', { type: 'checkbox', onchange: function () { picker.showHidden = p.hidden.checked; writePref('browse.hidden', p.hidden.checked ? '1' : null); if (picker.path) navigate(picker.path); } });
    p.hidden.checked = picker.showHidden;
    p.up = h('button', { class: 'button secondary small', type: 'button', 'data-ripple': true, onclick: function () { var parent = parentOfCurrent(); if (parent) navigate(parent); } }, icon('up'), h('span', { text: t('browse.up') }));
    p.note = h('span', { class: 'browse-note', 'aria-live': 'polite' });
    p.choose = h('button', { class: 'button', type: 'button', 'data-ripple': true, onclick: choosePicked }, icon('check'), h('span', { text: t('browse.choose') }));
    p.dialog = h('div', { class: 'dialog', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'browse-title', tabindex: '-1', onkeydown: trapTab },
      h('div', { class: 'dialog-head' }, h('h2', { class: 'dialog-title', id: 'browse-title', text: t('browse.title') }),
        h('button', { class: 'icon-button', type: 'button', 'data-ripple': true, 'aria-label': t('browse.close'), onclick: closePicker }, icon('x'))),
      p.crumbs,
      h('div', { class: 'browse-body' }, h('div', { class: 'browse-side' }, h('div', { class: 'browse-locations-title', text: t('browse.locations') }), p.locations), p.listWrap),
      h('div', { class: 'dialog-foot' },
        h('label', { class: 'switch compact' }, p.hidden, h('span', { class: 'track', 'aria-hidden': 'true' }), h('span', { text: t('browse.hidden') })),
        p.up, p.note, h('span', { class: 'spacer' }),
        h('button', { class: 'button secondary', type: 'button', 'data-ripple': true, onclick: closePicker }, t('browse.cancel')), p.choose));
    picker.host.appendChild(p.dialog);
    updatePicker();
    p.dialog.focus();
  }

  function updatePicker() {
    var p = picker.refs; if (!p) return;
    clear(p.crumbs);
    var crumbs = core.breadcrumbs(picker.path);
    crumbs.forEach(function (crumb, i) {
      if (i) p.crumbs.appendChild(h('span', { class: 'crumb-sep', 'aria-hidden': 'true' }, icon('chevron')));
      var last = i === crumbs.length - 1;
      p.crumbs.appendChild(h('button', { class: 'crumb', type: 'button', 'data-ripple': !last, title: crumb.path, 'aria-current': last ? 'location' : null, onclick: function () { if (!last) navigate(crumb.path); } }, crumb.name));
    });
    clear(p.locations);
    picker.roots.forEach(function (root, i) {
      var on = picker.path === root.path;
      p.locations.appendChild(h('button', { class: 'browse-location' + (on ? ' on' : ''), type: 'button', 'data-ripple': true, title: root.path, 'aria-pressed': on ? 'true' : 'false', onclick: function () { navigate(root.path); } },
        icon(i === 0 ? 'home' : 'drive'), h('span', { class: 'name', text: root.name }), root.has_shelf ? h('span', { class: 'badge', text: t('browse.has_shelf') }) : null));
    });
    clear(p.listWrap);
    if (picker.loading) {
      p.listWrap.appendChild(h('div', { class: 'skeleton-lines', 'aria-busy': 'true', 'aria-label': t('browse.loading') }, [60, 45, 70, 50, 65].map(function (w) { var s = h('div', { class: 'skeleton' }); s.style.width = w + '%'; return s; })));
    } else if (picker.error) {
      p.listWrap.appendChild(h('div', { class: 'state compact', role: 'alert' }, h('div', { class: 'state-icon danger' }, icon('alert')), h('h3', { class: 'state-title', text: picker.error })));
    } else if (!picker.listing || !picker.listing.entries.length) {
      p.listWrap.appendChild(h('div', { class: 'state compact' }, h('div', { class: 'state-icon' }, icon('folder')), h('h3', { class: 'state-title', text: t('browse.empty') })));
    } else {
      // 子目录可能上千条：一次 DocumentFragment 追加。
      var list = h('div', { class: 'browse-list', role: 'listbox', 'aria-label': picker.path });
      var fragment = document.createDocumentFragment();
      core.sortEntries(picker.listing.entries).forEach(function (entry) {
        fragment.appendChild(h('button', { class: 'browse-item', type: 'button', role: 'option', 'data-ripple': true, 'data-path': entry.path, title: entry.path, 'aria-selected': picker.selected === entry.path ? 'true' : 'false',
          onclick: function () { selectEntry(entry.path); }, ondblclick: function () { navigate(entry.path); },
          onkeydown: function (e) { if (e.key === 'Enter') { e.preventDefault(); navigate(entry.path); } } },
          icon('folder'), h('span', { class: 'name', text: entry.name }), entry.has_shelf ? h('span', { class: 'badge', text: t('browse.has_shelf') }) : null));
      });
      list.appendChild(fragment);
      p.listWrap.appendChild(list);
    }
    var notes = [];
    if (picker.listing && picker.listing.truncated) notes.push(t('browse.truncated', { n: picker.listing.entries.length }));
    if (picker.listing && picker.listing.writable === false) notes.push(t('browse.readonly'));
    p.note.textContent = notes.join(' · ');
    p.up.disabled = picker.loading || !parentOfCurrent();
    updatePickerButtons();
  }
  /** 运行状态变化时只刷新按钮（update() 每秒调用，不重绘列表）。 */
  function updatePickerButtons() {
    var p = picker.refs; if (!p) return;
    p.choose.disabled = state.running || picker.loading || !!picker.error || !picker.path;
    p.choose.title = state.running ? t('browse.running') : '';
  }

  /* ---------- 渲染：外壳一次，局部更新 ---------- */
  function buildShell() {
    var app = document.getElementById('app');
    clear(app);
    app.className = 'layout' + (drawerOpen ? ' drawer-open' : '');
    refs = {};
    app.appendChild(h('button', { class: 'menu-button', 'data-ripple': true, 'aria-label': t('menu.open'), onclick: function () { drawerOpen = true; buildShell(); update(); } }, icon('menu')));
    if (drawerOpen) app.appendChild(h('div', { class: 'overlay', onclick: function () { drawerOpen = false; buildShell(); update(); } }));
    app.appendChild(renderSidebar());
    var page = h('div', { class: 'page view-' + view });
    refs.headSub = h('p', { class: 'page-sub' });
    page.appendChild(h('header', { class: 'page-head' }, h('div', null, h('h1', { class: 'page-title', text: t('nav.' + view) }), refs.headSub)));
    if (view === 'run') {
      var columns = h('div', { class: 'two-col' });
      columns.appendChild(renderForm());
      columns.appendChild(renderSteps());
      page.appendChild(columns);
    } else if (view === 'settings') {
      var cols = h('div', { class: 'two-col settings-cols' });
      cols.appendChild(renderOptionsCard());
      cols.appendChild(renderSourcesCard());
      page.appendChild(cols);
    } else if (view === 'changelog') {
      page.appendChild(renderChangelog());
    } else {
      page.appendChild(renderLogCard());
    }
    refs.toasts = h('div', { class: 'toasts', 'aria-live': 'polite' });
    page.appendChild(refs.toasts);
    app.appendChild(h('main', { class: 'content' }, page));
    renderLogLines();
    renderSourceRows();
    if (picker.open) buildPicker();
  }

  function renderSidebar() {
    var theme = themePref();
    var themeIcon = theme === 'light' ? 'sun' : theme === 'dark' ? 'moon' : 'monitor';
    return h('aside', { class: 'sidebar', 'aria-label': t('app.name') },
      h('div', { class: 'brand' }, icon('film'), h('span', { class: 'brand-name', text: t('app.name') }),
        h('button', { class: 'icon-button drawer-close', 'data-ripple': true, 'aria-label': t('menu.close'), onclick: function () { drawerOpen = false; buildShell(); update(); } }, icon('x'))),
      h('nav', { class: 'nav' }, VIEWS.map(function (name) {
        var active = name === view;
        return h('a', { class: 'nav-item' + (active ? ' active' : ''), href: '#/' + name, 'data-ripple': true, 'aria-current': active ? 'page' : null,
          onclick: function () { drawerOpen = false; } }, icon(VIEW_ICONS[name]), h('span', { class: 'nav-label', text: t('nav.' + name) }),
          name === 'run' && state.running ? h('span', { class: 'nav-dot running', 'aria-hidden': 'true' }) : null);
      })),
      h('div', { class: 'sidebar-footer' },
        h('div', { class: 'theme-wrap' },
          h('button', { class: 'footer-button', 'data-ripple': true, 'aria-haspopup': 'menu', 'aria-expanded': themeMenuOpen ? 'true' : 'false', 'aria-label': t('theme.label'),
            onclick: function (e) { e.stopPropagation(); themeMenuOpen = !themeMenuOpen; buildShell(); update(); } }, icon(themeIcon), h('span', { text: t('theme.' + theme) })),
          themeMenuOpen ? h('div', { class: 'menu', role: 'menu' }, ['system', 'light', 'dark'].map(function (value) {
            return h('button', { class: 'menu-item', role: 'menuitemradio', 'aria-checked': theme === value ? 'true' : 'false', 'data-ripple': true,
              onclick: function () { applyTheme(value); themeMenuOpen = false; buildShell(); update(); } },
              icon(value === 'light' ? 'sun' : value === 'dark' ? 'moon' : 'monitor'), h('span', { text: t('theme.' + value) }), theme === value ? icon('check') : null);
          })) : null),
        h('button', { class: 'footer-button', 'data-ripple': true, 'aria-label': t('lang.label'),
          onclick: function () { lang = nextLang(); writePref('lang', lang); applyLang(); buildShell(); update(); } }, langSwitch()),
        h('a', { class: 'version' + (view === 'changelog' ? ' active' : ''), href: '#/changelog', 'data-ripple': true,
          'aria-current': view === 'changelog' ? 'page' : null, title: t('nav.changelog'),
          onclick: function () { drawerOpen = false; } },
          h('span', { text: t('version') + ' ' + (boot.version || document.body.getAttribute('data-version') || '') }))));
  }

  /* ---------- 更新记录 ---------- */

  /** 条目正文：`` `代码` `` 与 `**粗体**` 建成元素，别的当纯文本——不拼 HTML。 */
  function inlineNodes(text) {
    return core.inlineParts(text).map(function (part) {
      if (part.kind === 'code') return h('code', { text: part.text });
      if (part.kind === 'strong') return h('strong', { text: part.text });
      return document.createTextNode(part.text);
    });
  }

  function renderChangelog() {
    var entries = boot.changelog || [];
    if (!entries.length) {
      return h('div', { class: 'card' }, h('div', { class: 'card-body' },
        h('div', { class: 'state' }, h('div', { class: 'state-icon' }, icon('scroll')),
          h('h3', { class: 'state-title', text: t('changelog.empty.title') }),
          h('p', { class: 'state-body', text: t('changelog.empty.body') }),
          h('a', { class: 'button soft', 'data-ripple': true, href: CHANGELOG_URL, target: '_blank', rel: 'noreferrer noopener' },
            h('span', { text: t('changelog.source') })))));
    }
    var current = boot.version || document.body.getAttribute('data-version') || '';
    return h('div', { class: 'changelog' }, entries.map(function (entry) {
      return h('section', { class: 'card release' },
        h('header', { class: 'release-head' },
          h('h2', { class: 'release-version mono', text: 'v' + entry.version }),
          entry.version === current ? h('span', { class: 'pill primary', text: t('changelog.current') }) : null,
          h('time', { class: 'release-date', datetime: entry.date, text: entry.date })),
        h('div', { class: 'release-body' },
          entry.note ? h('p', { class: 'release-note' }, inlineNodes(entry.note)) : null,
          (entry.groups || []).map(function (group) {
            return h('div', { class: 'release-group' },
              group.title ? h('h3', { class: 'release-group-title', text: group.title }) : null,
              h('ul', { class: 'release-items' }, (group.items || []).map(function (item) {
                return h('li', null, inlineNodes(item));
              })));
          })));
    }));
  }

  function renderForm() {
    var list = h('datalist', { id: 'recent-roots' });
    refs.recent = list;
    refs.root = h('input', { class: 'input mono', id: 'root', type: 'text', list: 'recent-roots', placeholder: t('form.root.placeholder'), autocomplete: 'off', spellcheck: 'false',
      value: opts.root || state.root || recentRoots[0] || '', onkeydown: function (e) { if (e.key === 'Enter' && !state.running) { e.preventDefault(); start(); } }, oninput: function () { opts.root = refs.root.value; showFieldError(''); } });
    refs.rootError = h('p', { class: 'field-error', hidden: true, role: 'alert' });
    refs.browseButton = h('button', { class: 'icon-button bordered', type: 'button', 'data-ripple': true, 'aria-label': t('browse.open'), title: t('browse.open'), 'aria-haspopup': 'dialog',
      onclick: function () { openPicker(refs.browseButton); } }, icon('folder'));
    function toggle(key, labelKey) {
      var input = h('input', { type: 'checkbox', onchange: function () { opts[key] = input.checked; } });
      input.checked = !!opts[key];
      refs[key] = input;
      return h('label', { class: 'switch', 'data-ripple': true }, input, h('span', { class: 'track', 'aria-hidden': 'true' }), h('span', { text: t(labelKey) }));
    }
    refs.startButton = h('button', { class: 'button large', 'data-ripple': true, type: 'button', onclick: function () { if (state.running) stop(); else start(); } });
    refs.openButton = h('button', { class: 'button soft', 'data-ripple': true, type: 'button', hidden: true, onclick: openResult }, icon('external'), h('span', { text: t('form.open') }));
    refs.formNote = h('span', { class: 'form-note tabular' });
    return h('section', { class: 'card' },
      h('div', { class: 'card-head' }, h('div', null, h('h2', { class: 'card-title', text: t('form.title') }), h('p', { class: 'card-sub', text: t('form.sub') }))),
      h('div', { class: 'field' }, h('label', { class: 'label', for: 'root', text: t('form.root') }), h('div', { class: 'input-row' }, refs.root, refs.browseButton), list, refs.rootError, h('p', { class: 'help', text: t('form.root.help') })),
      h('div', { class: 'switches' },
        toggle('move', 'form.move'),
        toggle('offline', 'form.offline'),
        toggle('dryRun', 'form.dry_run'),
        toggle('force', 'form.force')),
      h('p', { class: 'help', text: t('form.settings.hint') }),
      h('div', { class: 'form-actions' }, refs.startButton, refs.openButton, refs.formNote));
  }

  /* 设置页左卡：盘上选项。它们写进盘的 HiddenShelf/config.json，点「开始」时随本次运行一起发过去。 */
  function renderOptionsCard() {
    function toggle(key, labelKey, helpKey) {
      var input = h('input', { type: 'checkbox', onchange: function () { opts[key] = input.checked; } });
      input.checked = !!opts[key];
      refs[key] = input;
      return h('label', { class: 'switch', 'data-ripple': true }, input, h('span', { class: 'track', 'aria-hidden': 'true' }),
        h('span', { class: 'switch-text' }, h('span', { text: t(labelKey) }), helpKey ? h('span', { class: 'switch-help', text: t(helpKey) }) : null));
    }
    refs.optionsNote = h('p', { class: 'help mono-path' });
    return h('section', { class: 'card' },
      h('div', { class: 'card-head' }, h('div', null, h('h2', { class: 'card-title', text: t('options.title') }), h('p', { class: 'card-sub', text: t('options.sub') }))),
      h('div', { class: 'switches' },
        toggle('sheets', 'options.sheets', 'options.sheets.help'),
        toggle('images', 'form.images', 'options.images.help')),
      refs.optionsNote);
  }

  /* ---------- 来源与登录 ---------- */
  function loadSources() {
    var root = refs.root ? refs.root.value.trim() : '';
    return api('GET', '/api/sources' + (root ? '?root=' + encodeURIComponent(root) : '')).then(function (response) {
      if (!response.ok) { sourcesError = response.data.error || ('HTTP ' + response.status); sourcesInfo = null; }
      else { sourcesError = null; sourcesInfo = response.data; }
      renderSourceRows();
      scheduleSourcesPoll();
    }).catch(function (error) { sourcesError = String(error && error.message || error); sourcesInfo = null; renderSourceRows(); });
  }
  /** 有登录在进行时每 2 秒刷一次，没有就不轮询。 */
  function scheduleSourcesPoll() {
    if (sourcesTimer) { clearTimeout(sourcesTimer); sourcesTimer = null; }
    var running = sourcesInfo && sourcesInfo.sources.some(function (row) { return row.login.status === 'running'; });
    if (running) sourcesTimer = setTimeout(loadSources, 2000);
  }
  function toggleSource(row, input) {
    api('POST', '/api/sources', { name: row.name, enabled: input.checked }).then(function (response) {
      if (!response.ok) { input.checked = !input.checked; toast('danger', t('sources.toggle.failed', { error: response.data.error || ('HTTP ' + response.status) })); }
      else loadSources();
    }).catch(function (error) { input.checked = !input.checked; toast('danger', t('toast.request.failed', { error: String(error && error.message || error) })); });
  }
  function startLogin(row) {
    api('POST', '/api/login', { name: row.name }).then(function (response) {
      if (!response.ok) toast('danger', t('sources.login.failed', { error: response.data.error || ('HTTP ' + response.status) }));
      loadSources();
    }).catch(function (error) { toast('danger', t('toast.request.failed', { error: String(error && error.message || error) })); });
  }
  function finishLogin(row) {
    api('POST', '/api/login/finish', { name: row.name }).then(function () { loadSources(); });
  }
  function clearCooldown(row) {
    var root = refs.root ? refs.root.value.trim() : '';
    if (!root) { toast('warning', t('sources.cooldown.root')); return; }
    api('POST', '/api/cooldown/clear', { root: root, name: row ? row.name : '' }).then(function (response) {
      if (!response.ok) { toast('danger', response.data.error || ('HTTP ' + response.status)); return; }
      var names = response.data.cleared || [];
      toast(names.length ? 'success' : 'info', names.length ? t('sources.cooldown.cleared', { names: names.join(', ') }) : t('sources.cooldown.nothing'));
      loadSources();
    });
  }
  function cooldownText(iso) {
    var d = new Date(iso);
    var pad = function (n) { return (n < 10 ? '0' : '') + n; };
    var sameDay = d.toDateString() === new Date().toDateString();
    return (sameDay ? '' : pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ') + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }
  function renderSourcesCard() {
    refs.sourcesBody = h('div', { class: 'sources', 'aria-live': 'polite' });
    refs.sourcesHint = h('p', { class: 'sources-hint', hidden: true });
    var refresh = h('button', { class: 'button secondary small', type: 'button', 'data-ripple': true, onclick: loadSources }, t('sources.refresh'));
    return h('section', { class: 'card' },
      h('div', { class: 'card-head' }, h('div', null, h('h2', { class: 'card-title', text: t('sources.title') }), h('p', { class: 'card-sub', text: t('sources.sub') })), refresh),
      refs.sourcesBody, refs.sourcesHint);
  }
  function renderSourceRows() {
    var body = refs.sourcesBody; if (!body) return;
    clear(body);
    if (sourcesError) {
      body.appendChild(h('div', { class: 'state compact', role: 'alert' }, h('div', { class: 'state-icon danger' }, icon('alert')), h('h3', { class: 'state-title', text: t('sources.error', { error: sourcesError }) })));
      return;
    }
    if (!sourcesInfo) {
      body.appendChild(h('div', { class: 'skeleton-lines', 'aria-busy': 'true', 'aria-label': t('sources.loading') }, [50, 70, 40].map(function (w) { var sk = h('div', { class: 'skeleton' }); sk.style.width = w + '%'; return sk; })));
      return;
    }
    sourcesInfo.sources.forEach(function (row) {
      var input = h('input', { type: 'checkbox', 'aria-label': t('sources.enabled') + ' ' + row.label, onchange: function () { toggleSource(row, input); } });
      input.checked = row.enabled;
      var meta = [];
      if (row.needs_login) meta.push(h('span', { class: 'pill ' + (row.cookie ? 'done' : ''), text: row.cookie ? t('sources.cookie.yes') : t('sources.cookie.no') }));
      else if (row.needs_fingerprint) meta.push(h('span', { class: 'pill ' + (sourcesInfo.fingerprint_available ? 'done' : 'failed'), text: sourcesInfo.fingerprint_available ? t('sources.fingerprint.yes') : t('sources.fingerprint.no') }));
      else meta.push(h('span', { class: 'pill', text: t('sources.cookie.none') }));
      if (row.cooldown_until) meta.push(h('span', { class: 'pill skipped', text: t('sources.cooldown', { time: cooldownText(row.cooldown_until) }) }));
      var actions = [];
      var login = row.login || { status: 'idle', message: '' };
      if (row.needs_login) {
        if (login.status === 'running') {
          actions.push(h('button', { class: 'button small', type: 'button', 'data-ripple': true, 'aria-busy': 'true', onclick: function () { finishLogin(row); } }, icon('loader'), h('span', { text: t('sources.login.finish') })));
        } else {
          actions.push(h('button', { class: 'button small' + (row.cookie ? ' secondary' : ''), type: 'button', 'data-ripple': true, disabled: !sourcesInfo.login_available, onclick: function () { startLogin(row); } }, t('sources.login')));
        }
      }
      if (row.cooldown_until) actions.push(h('button', { class: 'button small secondary', type: 'button', 'data-ripple': true, onclick: function () { clearCooldown(row); } }, t('sources.cooldown.clear')));
      var message = login.status === 'running' ? (login.message || t('sources.login.running')) : (login.status === 'done' || login.status === 'failed') ? login.message : '';
      body.appendChild(h('div', { class: 'source-row', 'data-source': row.name },
        h('label', { class: 'switch compact' }, input, h('span', { class: 'track', 'aria-hidden': 'true' })),
        h('div', { class: 'source-main' }, h('div', { class: 'source-name', text: row.label }), h('div', { class: 'source-meta' }, meta),
          message ? h('div', { class: 'source-message ' + login.status, text: message }) : null),
        h('div', { class: 'source-actions' }, actions)));
    });
    refs.sourcesHint.hidden = sourcesInfo.login_available && sourcesInfo.fingerprint_available;
    clear(refs.sourcesHint);
    if (!sourcesInfo.login_available) {
      var loginLine = h('div', null, h('span', { text: t('sources.login.hint') + ' ' }));
      String(sourcesInfo.login_hint || '').split('\n').slice(1).forEach(function (line, i) {
        if (i) loginLine.appendChild(h('span', { text: ' ' }));
        loginLine.appendChild(h('code', { text: line.trim() }));
      });
      refs.sourcesHint.appendChild(loginLine);
    }
    if (!sourcesInfo.fingerprint_available) {
      refs.sourcesHint.appendChild(h('div', null, h('span', { text: t('sources.fingerprint.hint') + ' ' }), h('code', { text: sourcesInfo.fingerprint_hint || '' })));
    }
  }

  function renderSteps() {
    refs.steps = {};
    var list = h('div', { class: 'steps' });
    STEPS.forEach(function (name) {
      var row = {};
      row.dot = h('span', { class: 'dot', 'aria-hidden': 'true' });
      row.pill = h('span', { class: 'pill' });
      row.time = h('span', { class: 'step-time tabular' });
      row.message = h('div', { class: 'step-message' });
      row.error = h('div', { class: 'step-error', hidden: true });
      row.fill = h('div', { class: 'bar-fill' });
      row.bar = h('div', { class: 'bar', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-label': t('step.' + name) }, row.fill);
      refs.steps[name] = row;
      list.appendChild(h('div', { class: 'step', 'data-step': name }, row.dot,
        h('div', { class: 'step-name' }, h('span', { text: t('step.' + name) }), row.pill), row.time,
        h('div', { class: 'step-body' }, row.bar, row.message, row.error)));
    });
    refs.resultBox = h('div', { class: 'result', hidden: true });
    return h('section', { class: 'card' }, h('div', { class: 'card-head' }, h('h2', { class: 'card-title', text: t('steps.title') })), list, refs.resultBox);
  }

  function renderLogCard() {
    var segments = ['all'].concat(STEPS).map(function (name) {
      return h('button', { class: 'segment' + (logFilter === name ? ' on' : ''), 'data-ripple': true, type: 'button', 'aria-pressed': logFilter === name ? 'true' : 'false',
        onclick: function () { logFilter = name; buildShell(); update(); } }, name === 'all' ? t('log.all') : t('step.' + name));
    });
    refs.logCount = h('span', { class: 'log-count tabular' });
    refs.log = h('pre', { class: 'log', tabindex: '0', 'aria-live': 'off', onscroll: function () {
      var el = refs.log;
      following = el.scrollTop + el.clientHeight >= el.scrollHeight - 8;
      refs.followButton.hidden = following;
    } });
    refs.followButton = h('button', { class: 'button small secondary log-follow', 'data-ripple': true, type: 'button', hidden: true, onclick: function () { following = true; refs.log.scrollTop = refs.log.scrollHeight; refs.followButton.hidden = true; } }, icon('down'), h('span', { text: t('log.follow') }));
    refs.logState = h('div', { class: 'log-state' });
    refs.logWrap = h('div', { class: 'log-wrap' }, refs.log, refs.followButton);
    return h('section', { class: 'card log-card' },
      h('div', { class: 'card-head' }, h('div', null, h('h2', { class: 'card-title', text: t('log.title') }), refs.logCount), h('div', { class: 'segmented', role: 'group', 'aria-label': t('log.title') }, segments)),
      refs.logState, refs.logWrap);
  }

  /* ---------- 日志 ---------- */
  function logLine(event) {
    var time = (event.ts || '').slice(11, 19);
    return h('div', { class: 'log-line ' + (event.level || 'info') }, h('span', { class: 'ts', text: time }), h('span', { class: 'st', text: stepLabel(event.step) }), h('span', { class: 'msg', text: event.message || '' }));
  }
  function clearLog() { if (refs.log) clear(refs.log); }
  function appendLog(event) {
    if (!refs.log) return;
    if (logFilter !== 'all' && event.step !== logFilter) return;
    refs.log.appendChild(logLine(event));
    while (refs.log.children.length > LOG_LIMIT) refs.log.removeChild(refs.log.firstChild);
    if (following) refs.log.scrollTop = refs.log.scrollHeight;
  }
  function renderLogLines() {
    if (!refs.log) return;
    clear(refs.log);
    core.filterLog(events, logFilter).slice(-LOG_LIMIT).forEach(function (event) { refs.log.appendChild(logLine(event)); });
    refs.log.scrollTop = refs.log.scrollHeight;
  }

  /* ---------- 局部更新 ---------- */
  function elapsedOf(start, end) {
    if (!start) return '';
    var from = Date.parse(start);
    var to = end ? Date.parse(end) : Date.now();
    return core.formatElapsed(to - from, lang);
  }

  function update() {
    if (!refs.headSub) return;
    if (view === 'changelog') {
      clear(refs.headSub);
      refs.headSub.appendChild(h('span', { text: t('changelog.sub') }));
      return;
    }
    // 页头状态
    var headKey = state.running ? 'page.running' : !state.result ? 'page.idle' : state.result.cancelled ? 'page.cancelled' : state.result.ok ? (state.result.dry_run ? 'page.dry_run' : 'page.done') : 'page.failed';
    var headDot = state.running ? 'running' : !state.result ? '' : state.result.cancelled ? 'skipped' : state.result.ok ? 'done' : 'failed';
    clear(refs.headSub);
    refs.headSub.appendChild(h('span', { class: 'dot ' + headDot, 'aria-hidden': 'true' }));
    refs.headSub.appendChild(h('span', { text: t(headKey) + (state.root ? ' · ' + state.root : '') }));
    var busy = state.running || starting;
    if (!opts.root) opts.root = state.root || recentRoots[0] || '';
    ['move', 'offline', 'dryRun', 'force', 'images', 'sheets'].forEach(function (key) { if (refs[key]) refs[key].disabled = busy; });
    if (refs.optionsNote) refs.optionsNote.textContent = opts.root ? t('options.note', { path: opts.root }) : t('options.note.empty');
    var runNav = document.querySelector('.nav-item[href="#/run"] .nav-dot');
    if (!!runNav !== !!state.running) { var nav = document.querySelector('.nav'); if (nav) { var item = nav.querySelector('.nav-item[href="#/run"]'); if (item) { if (runNav) item.removeChild(runNav); else item.appendChild(h('span', { class: 'nav-dot running', 'aria-hidden': 'true' })); } } }
    if (refs.root) updateForm(busy);
    if (refs.steps) updateSteps();
    if (refs.log) updateLog();
  }

  function updateForm(busy) {
    // 表单：刷新页面后把正在跑／上次跑的盘根目录填回去（用户自己改过的不动）。
    clear(refs.recent);
    recentRoots.forEach(function (root) { refs.recent.appendChild(h('option', { value: root })); });
    if (!refs.root.value) refs.root.value = opts.root;
    refs.root.disabled = busy;
    clear(refs.startButton);
    refs.startButton.className = 'button large' + (state.running ? ' secondary' : '');
    refs.startButton.setAttribute('aria-busy', starting ? 'true' : 'false');
    refs.startButton.disabled = starting || (state.running && state.cancelRequested) || loading;
    if (starting) { refs.startButton.appendChild(icon('loader')); refs.startButton.appendChild(h('span', { text: t('form.starting') })); }
    else if (state.running) { refs.startButton.appendChild(icon('square')); refs.startButton.appendChild(h('span', { text: t('form.stop') })); }
    else { refs.startButton.appendChild(icon('play')); refs.startButton.appendChild(h('span', { text: t('form.start') })); }
    refs.formNote.textContent = state.running ? (state.cancelRequested ? t('form.stopping') : t('form.stop.help') + ' · ' + t('form.elapsed', { time: elapsedOf(state.startedAt) })) : (state.startedAt ? t('form.elapsed', { time: elapsedOf(state.startedAt, state.finishedAt) }) : '');
    var finishedOk = !state.running && state.result && state.result.ok && state.steps.build && state.steps.build.status === 'done';
    refs.openButton.hidden = !finishedOk;
    updatePickerButtons();
  }

  function updateSteps() {
    STEPS.forEach(function (name) {
      var row = refs.steps[name];
      var data = state.steps[name];
      row.dot.className = 'dot ' + (data.status === 'waiting' ? '' : data.status);
      row.pill.className = 'pill ' + (data.status === 'waiting' ? '' : data.status);
      row.pill.textContent = t('status.' + data.status);
      row.time.textContent = data.startedAt ? elapsedOf(data.startedAt, data.finishedAt || (data.status === 'running' ? null : data.finishedAt)) : '';
      var summary = data.status === 'done' ? core.summaryOf(name, data.stats, t) : '';
      row.message.textContent = summary || data.message || '';
      row.message.title = row.message.textContent;
      row.error.hidden = data.status !== 'failed';
      row.error.textContent = data.error || '';
      row.bar.className = 'bar' + (data.status === 'done' ? ' done' : data.status === 'failed' ? ' failed' : (data.status === 'running' && data.percent == null ? ' indeterminate' : ''));
      var percent = data.status === 'done' ? 100 : data.status === 'running' && data.percent != null ? data.percent : data.status === 'failed' ? 100 : 0;
      row.fill.style.width = (data.status === 'running' && data.percent == null) ? '' : percent + '%';
      if (data.status === 'running' && data.percent == null) row.bar.removeAttribute('aria-valuenow'); else row.bar.setAttribute('aria-valuenow', String(percent));
    });
    // 结果
    clear(refs.resultBox);
    refs.resultBox.hidden = state.running || !state.result;
    if (!refs.resultBox.hidden) {
      var result = state.result;
      // 没有 failed_step 的失败发生在第一步之前（建 HiddenShelf、开库），比如盘是只读的。
      var text = result.cancelled ? t('result.cancelled') : result.ok ? (result.dry_run ? t('result.dry_run') : t('result.ok'))
        : result.failed_step ? t('result.failed', { step: stepLabel(result.failed_step), error: result.error || '' }) : t('result.failed.setup', { error: result.error || '' });
      refs.resultBox.appendChild(h('h3', { class: 'card-title', text: t('result.title') }));
      refs.resultBox.appendChild(h('p', { class: 'result-text' + (result.ok ? '' : ' failed'), text: text }));
      if (result.log_path) refs.resultBox.appendChild(h('div', { class: 'result-path', text: t('result.log', { path: result.log_path }) }));
    }
  }

  function updateLog() {
    clear(refs.logState);
    var lines = core.filterLog(events, logFilter).length;
    refs.logCount.textContent = t('log.lines', { n: lines });
    if (loading) {
      refs.logWrap.hidden = true;
      refs.logState.appendChild(h('div', { class: 'skeleton-lines', 'aria-busy': 'true' }, [70, 55, 80, 40].map(function (w) { var s = h('div', { class: 'skeleton' }); s.style.width = w + '%'; return s; })));
    } else if (logError) {
      refs.logWrap.hidden = true;
      refs.logState.appendChild(h('div', { class: 'state', role: 'alert' }, h('div', { class: 'state-icon danger' }, icon('alert')),
        h('h3', { class: 'state-title', text: t('log.error.title') }), h('p', { class: 'state-body', text: t('log.error.body') }),
        h('button', { class: 'button secondary', 'data-ripple': true, type: 'button', onclick: function () { logError = false; load(); } }, t('log.retry'))));
    } else if (!state.run && !events.length) {
      refs.logWrap.hidden = true;
      refs.logState.appendChild(h('div', { class: 'state' }, h('div', { class: 'state-icon' }, icon('terminal')),
        h('h3', { class: 'state-title', text: t('log.empty.title') }), h('p', { class: 'state-body', text: t('log.empty.body') })));
    } else {
      refs.logWrap.hidden = false;
    }
  }

  /* ---------- 启动 ---------- */
  applyLang();
  buildShell();
  update();
  load();
  loadSources();
  setInterval(function () { if (state.running && refs.headSub) update(); }, 1000);
  window.addEventListener('hashchange', function () { var next = viewFromHash(); if (next !== view) { view = next; themeMenuOpen = false; buildShell(); update(); } });
  document.addEventListener('click', function () { if (themeMenuOpen) { themeMenuOpen = false; buildShell(); update(); } });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    if (picker.open) { closePicker(); return; }
    if (themeMenuOpen || drawerOpen) { themeMenuOpen = false; drawerOpen = false; buildShell(); update(); }
  });
  if (window.initRipple) window.initRipple();
})();
