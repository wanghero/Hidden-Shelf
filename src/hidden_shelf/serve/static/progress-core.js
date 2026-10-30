/* 藏片阁 进度网页纯逻辑（UMD）：事件归约成步状态、`[i/total]` 百分比、耗时格式、日志过滤、步摘要。
 * 不碰 DOM，node --test 可测。与后端 `serve/runner.reduce_state` 是同一套规则。浏览器挂 window.ShelfProgressCore。 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.ShelfProgressCore = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var STATUS = { waiting: 'waiting', running: 'running', done: 'done', failed: 'failed', skipped: 'skipped' };
  var PERCENT = /^\[(\d+)\/(\d+)\]/;
  var CANCEL_MARK = '收到停止请求';

  function stepRow() {
    return { status: STATUS.waiting, message: null, stats: null, error: null, startedAt: null, finishedAt: null, percent: null };
  }

  /** 一次运行开始前的状态。`stepsOrder` 是六步的顺序。 */
  function initialState(stepsOrder) {
    var steps = {};
    (stepsOrder || []).forEach(function (name) { steps[name] = stepRow(); });
    return { run: null, root: null, options: null, running: false, cancelRequested: false, result: null,
      startedAt: null, finishedAt: null, steps: steps, order: (stepsOrder || []).slice(), lastSeq: 0 };
  }

  function clone(state) {
    var copy = JSON.parse(JSON.stringify(state));
    return copy;
  }

  /** `[3/12] 九宫格 x` → 25；对不上 → null；总数 0 → null。 */
  function percentOf(message) {
    var found = PERCENT.exec(String(message == null ? '' : message));
    if (!found) return null;
    var total = parseInt(found[2], 10);
    if (!total) return null;
    return Math.max(0, Math.min(100, Math.round(parseInt(found[1], 10) / total * 100)));
  }

  /** 一条事件 → 新状态（不改旧状态）。未知步的事件忽略；`run.start` 把全部步重置为等待。 */
  function reduce(state, event) {
    var next = clone(state);
    if (!event || !event.kind) return next;
    if (typeof event.seq === 'number') next.lastSeq = event.seq;
    if (event.kind === 'run.start') {
      next.order.forEach(function (name) { next.steps[name] = stepRow(); });
      next.run = event.run || null;
      next.root = event.stats && event.stats.root ? event.stats.root : null;
      next.options = event.stats && event.stats.options ? event.stats.options : null;
      next.startedAt = event.ts || null;
      next.finishedAt = null;
      next.running = true;
      next.cancelRequested = false;
      next.result = null;
      return next;
    }
    if (event.kind === 'run.done' || event.kind === 'run.cancelled') {
      next.running = false;
      next.finishedAt = event.ts || null;
      next.result = Object.assign({}, event.stats || {}, { cancelled: event.kind === 'run.cancelled' });
      return next;
    }
    var row = next.steps[event.step];
    if (!row) {
      if (event.kind === 'step.progress' && event.level === 'warning' && String(event.message || '').indexOf(CANCEL_MARK) === 0) next.cancelRequested = true;
      return next;
    }
    if (event.kind === 'step.start') {
      row.status = STATUS.running; row.startedAt = event.ts || null; row.message = null; row.percent = null;
    } else if (event.kind === 'step.progress') {
      if (event.level === 'warning' && String(event.message || '').indexOf(CANCEL_MARK) === 0) next.cancelRequested = true;
      // 已完成、失败、跳过的步不再被后来的消息改写（停止请求那条警告挂在哪一步都不算它的进度）。
      if (row.status === STATUS.running) {
        row.message = event.message == null ? row.message : event.message;
        var percent = percentOf(event.message);
        if (percent != null) row.percent = percent;
      }
    } else if (event.kind === 'step.done') {
      row.status = STATUS.done; row.stats = event.stats || {}; row.finishedAt = event.ts || null; row.percent = 100;
    } else if (event.kind === 'step.failed') {
      row.status = STATUS.failed; row.error = event.message || ''; row.finishedAt = event.ts || null;
    } else if (event.kind === 'step.skipped') {
      row.status = STATUS.skipped; row.message = event.message || null; row.finishedAt = event.ts || null;
    }
    return next;
  }

  /** 一串事件从头归约。 */
  function reduceAll(stepsOrder, events) {
    return (events || []).reduce(reduce, initialState(stepsOrder));
  }

  /** 毫秒 → `1 分 5 秒` / `1m 5s`。小于一秒显示 0 秒。 */
  function formatElapsed(ms, lang) {
    var total = Math.max(0, Math.floor((Number(ms) || 0) / 1000));
    var hours = Math.floor(total / 3600);
    var minutes = Math.floor((total % 3600) / 60);
    var seconds = total % 60;
    var zh = lang === 'zh';
    if (hours) return zh ? hours + ' 小时 ' + minutes + ' 分' : hours + 'h ' + minutes + 'm';
    if (minutes) return zh ? minutes + ' 分 ' + seconds + ' 秒' : minutes + 'm ' + seconds + 's';
    return zh ? seconds + ' 秒' : seconds + 's';
  }

  /** 日志行：只要 `step.progress`/`step.failed`/`step.skipped`；`step` 为 'all' 或空给全部。 */
  function filterLog(events, step) {
    return (events || []).filter(function (event) {
      if (event.kind !== 'step.progress' && event.kind !== 'step.failed' && event.kind !== 'step.skipped') return false;
      if (!step || step === 'all') return true;
      return event.step === step;
    });
  }

  /** 完成的步一句摘要；`t(key, vars)` 由调用方给。没有模板或 stats 为空回空串。 */
  function summaryOf(step, stats, t) {
    if (!stats || typeof stats !== 'object') return '';
    if (stats.skipped === true) return String(stats.reason || '');
    // 预演的归位 stats 是 preview_organize 的返回（move/unchanged/skip），用自己的模板。
    var key = 'summary.' + step + (stats.dry_run === true ? '.dry_run' : '');
    var template = t(key, {});
    if (!template || template === key) return '';
    var vars = {};
    Object.keys(stats).forEach(function (name) {
      var value = stats[name];
      vars[name] = value == null ? 0 : (typeof value === 'object' ? (Array.isArray(value) ? value.length : '') : value);
    });
    return t(key, vars).replace(/\{[a-z_]+\}/g, '0');
  }

  /* ---------- 目录选择器 ---------- */
  var WIN_DRIVE = /^[A-Za-z]:\\/;

  /** 绝对路径 → 面包屑段 `[{name, path}]`。POSIX 第一段是 `/`；Windows 第一段是盘符 `D:\`。空给 `[]`。 */
  function breadcrumbs(path) {
    var text = String(path == null ? '' : path);
    if (!text) return [];
    var crumbs = [];
    if (WIN_DRIVE.test(text)) {
      var drive = text.slice(0, 3);
      crumbs.push({ name: drive, path: drive });
      var current = drive;
      text.slice(3).split(/[\\/]/).forEach(function (part) {
        if (!part) return;
        current = current === drive ? drive + part : current + '\\' + part;
        crumbs.push({ name: part, path: current });
      });
      return crumbs;
    }
    if (text.charAt(0) !== '/') return [{ name: text, path: text }];
    crumbs.push({ name: '/', path: '/' });
    var acc = '';
    text.split('/').forEach(function (part) {
      if (!part) return;
      acc += '/' + part;
      crumbs.push({ name: part, path: acc });
    });
    return crumbs;
  }

  /** 按名字排序（数字感知、不分大小写），返回新数组。 */
  function sortEntries(entries) {
    return (entries || []).slice().sort(function (a, b) {
      return String(a.name).localeCompare(String(b.name), undefined, { numeric: true, sensitivity: 'base' });
    });
  }

  /** `/api/browse` 的查询串：path 空就不带 `path=`。 */
  function browseUrl(path, showHidden) {
    var query = [];
    if (path) query.push('path=' + encodeURIComponent(String(path)));
    if (showHidden) query.push('show_hidden=1');
    return '/api/browse' + (query.length ? '?' + query.join('&') : '');
  }

  return { STATUS: STATUS, initialState: initialState, reduce: reduce, reduceAll: reduceAll, percentOf: percentOf,
    formatElapsed: formatElapsed, filterLog: filterLog, summaryOf: summaryOf,
    breadcrumbs: breadcrumbs, sortEntries: sortEntries, browseUrl: browseUrl };
});
