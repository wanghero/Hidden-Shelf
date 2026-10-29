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
  var lang = (function () {
    var saved = readPref('lang');
    if (saved === 'zh' || saved === 'en') return saved;
    return /^zh/i.test(navigator.language || '') ? 'zh' : 'en';
  })();
  function t(key, vars) {
    var table = dict[lang] || {};
    var text = table[key] != null ? table[key] : (dict.zh && dict.zh[key] != null ? dict.zh[key] : key);
    if (vars) Object.keys(vars).forEach(function (name) { text = text.split('{' + name + '}').join(String(vars[name])); });
    return text;
  }
  function applyLang() { document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en'; document.title = t('app.name') + ' · ' + t('page.title'); }
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
    info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>'
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
      else if (state.result && state.result.ok) toast('success', t('toast.done'));
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
    var root = refs.root.value.trim();
    if (!root) { showFieldError(t('form.root.required')); refs.root.focus(); return; }
    showFieldError('');
    starting = true;
    update();
    api('POST', '/api/run', { root: root, move_unrecognized: refs.move.checked, offline: refs.offline.checked, force_scrape: refs.force.checked })
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
          refs.root.focus();
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
    var root = state.root || refs.root.value.trim();
    api('POST', '/api/open', { root: root }).then(function (response) {
      if (response.ok) toast('success', t('toast.open.ok'));
      else toast('danger', response.data.error || t('toast.open.failed'), true);
    }).catch(function (error) { toast('danger', t('toast.request.failed', { error: String(error && error.message || error) }), true); });
  }
  function showFieldError(text) {
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

  /* ---------- 渲染：外壳一次，局部更新 ---------- */
  function buildShell() {
    var app = document.getElementById('app');
    clear(app);
    app.className = 'layout' + (drawerOpen ? ' drawer-open' : '');
    refs = {};
    app.appendChild(h('button', { class: 'menu-button', 'data-ripple': true, 'aria-label': t('menu.open'), onclick: function () { drawerOpen = true; buildShell(); update(); } }, icon('menu')));
    if (drawerOpen) app.appendChild(h('div', { class: 'overlay', onclick: function () { drawerOpen = false; buildShell(); update(); } }));
    app.appendChild(renderSidebar());
    var page = h('div', { class: 'page' });
    refs.headSub = h('p', { class: 'page-sub' });
    page.appendChild(h('header', { class: 'page-head' }, h('div', null, h('h1', { class: 'page-title', text: t('page.title') }), refs.headSub)));
    var columns = h('div', { class: 'two-col' });
    columns.appendChild(renderForm());
    columns.appendChild(renderSteps());
    page.appendChild(columns);
    page.appendChild(renderLogCard());
    refs.toasts = h('div', { class: 'toasts', 'aria-live': 'polite' });
    page.appendChild(refs.toasts);
    app.appendChild(h('main', { class: 'content' }, page));
    renderLogLines();
  }

  function renderSidebar() {
    var theme = themePref();
    var themeIcon = theme === 'light' ? 'sun' : theme === 'dark' ? 'moon' : 'monitor';
    return h('aside', { class: 'sidebar', 'aria-label': t('app.name') },
      h('div', { class: 'brand' }, icon('film'), h('span', { class: 'brand-name', text: t('app.name') }),
        h('button', { class: 'icon-button drawer-close', 'data-ripple': true, 'aria-label': t('menu.close'), onclick: function () { drawerOpen = false; buildShell(); update(); } }, icon('x'))),
      h('nav', { class: 'nav' }, h('a', { class: 'nav-item active', href: '#', 'data-ripple': true, 'aria-current': 'page', onclick: function (e) { e.preventDefault(); drawerOpen = false; buildShell(); update(); } }, icon('terminal'), h('span', { text: t('nav.run') }))),
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
          onclick: function () { lang = lang === 'zh' ? 'en' : 'zh'; writePref('lang', lang); applyLang(); buildShell(); update(); } }, h('span', { text: t('lang.toggle') })),
        h('div', { class: 'version', text: t('version') + ' ' + (boot.version || document.body.getAttribute('data-version') || '') })));
  }

  function renderForm() {
    var list = h('datalist', { id: 'recent-roots' });
    refs.recent = list;
    refs.root = h('input', { class: 'input mono', id: 'root', type: 'text', list: 'recent-roots', placeholder: t('form.root.placeholder'), autocomplete: 'off', spellcheck: 'false',
      value: refs.rootValue || state.root || recentRoots[0] || '', onkeydown: function (e) { if (e.key === 'Enter' && !state.running) { e.preventDefault(); start(); } }, oninput: function () { refs.rootValue = refs.root.value; showFieldError(''); } });
    refs.rootError = h('p', { class: 'field-error', hidden: true, role: 'alert' });
    function toggle(key, labelKey, checked) {
      var input = h('input', { type: 'checkbox' });
      input.checked = checked;
      refs[key] = input;
      return h('label', { class: 'switch', 'data-ripple': true }, input, h('span', { class: 'track', 'aria-hidden': 'true' }), h('span', { text: t(labelKey) }));
    }
    refs.startButton = h('button', { class: 'button large', 'data-ripple': true, type: 'button', onclick: function () { if (state.running) stop(); else start(); } });
    refs.openButton = h('button', { class: 'button soft', 'data-ripple': true, type: 'button', hidden: true, onclick: openResult }, icon('external'), h('span', { text: t('form.open') }));
    refs.formNote = h('span', { class: 'form-note tabular' });
    return h('section', { class: 'card' },
      h('div', { class: 'card-head' }, h('div', null, h('h2', { class: 'card-title', text: t('form.title') }), h('p', { class: 'card-sub', text: t('form.sub') }))),
      h('div', { class: 'field' }, h('label', { class: 'label', for: 'root', text: t('form.root') }), refs.root, list, refs.rootError, h('p', { class: 'help', text: t('form.root.help') })),
      h('div', { class: 'switches' },
        toggle('move', 'form.move', refs.moveValue == null ? true : refs.moveValue),
        toggle('offline', 'form.offline', !!refs.offlineValue),
        toggle('force', 'form.force', !!refs.forceValue)),
      h('div', { class: 'form-actions' }, refs.startButton, refs.openButton, refs.formNote));
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
    if (!refs.root) return;
    // 页头状态
    var headKey = state.running ? 'page.running' : !state.result ? 'page.idle' : state.result.cancelled ? 'page.cancelled' : state.result.ok ? 'page.done' : 'page.failed';
    var headDot = state.running ? 'running' : !state.result ? '' : state.result.cancelled ? 'skipped' : state.result.ok ? 'done' : 'failed';
    clear(refs.headSub);
    refs.headSub.appendChild(h('span', { class: 'dot ' + headDot, 'aria-hidden': 'true' }));
    refs.headSub.appendChild(h('span', { text: t(headKey) + (state.root ? ' · ' + state.root : '') }));
    // 表单：刷新页面后把正在跑／上次跑的盘根目录填回去（用户自己改过的不动）。
    clear(refs.recent);
    recentRoots.forEach(function (root) { refs.recent.appendChild(h('option', { value: root })); });
    if (!refs.rootValue && !refs.root.value) refs.root.value = state.root || recentRoots[0] || '';
    var busy = state.running || starting;
    [refs.root, refs.move, refs.offline, refs.force].forEach(function (input) { input.disabled = busy; });
    refs.moveValue = refs.move.checked; refs.offlineValue = refs.offline.checked; refs.forceValue = refs.force.checked;
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
    // 步骤
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
      var text = result.cancelled ? t('result.cancelled') : result.ok ? t('result.ok') : t('result.failed', { step: stepLabel(result.failed_step), error: result.error || '' });
      refs.resultBox.appendChild(h('h3', { class: 'card-title', text: t('result.title') }));
      refs.resultBox.appendChild(h('p', { class: 'result-text' + (result.ok ? '' : ' failed'), text: text }));
      if (result.log_path) refs.resultBox.appendChild(h('div', { class: 'result-path', text: t('result.log', { path: result.log_path }) }));
    }
    // 日志三态
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
  setInterval(function () { if (state.running && refs.root) update(); }, 1000);
  document.addEventListener('click', function () { if (themeMenuOpen) { themeMenuOpen = false; buildShell(); update(); } });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && (themeMenuOpen || drawerOpen)) { themeMenuOpen = false; drawerOpen = false; buildShell(); update(); } });
  if (window.initRipple) window.initRipple();
})();
