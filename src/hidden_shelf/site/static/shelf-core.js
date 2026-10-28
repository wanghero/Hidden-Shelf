/* 藏片阁 前端纯逻辑（UMD）：路径编码、搜索、筛选、排序、分面计数、可播放判定、格式化、hash 查询串。
 * 不碰 DOM，node --test 可测。浏览器挂 window.ShelfCore。 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.ShelfCore = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /** 相对盘根的 POSIX 路径 → 可放进 src 的 URL：逐段 encodeURIComponent，保留 `/`。 */
  function encodeMediaPath(rel) {
    if (!rel) return '';
    return String(rel).split('/').map(function (segment) { return encodeURIComponent(segment); }).join('/');
  }

  function lower(value) { return String(value == null ? '' : value).toLowerCase(); }

  /** 番号去掉分隔符后的比较形，让 `abp758` 搜得到 `ABP-758`。 */
  function compactCode(code) { return lower(code).replace(/[^a-z0-9]/g, ''); }

  function haystack(work, names) {
    var parts = [work.code, work.id, work.title, work.originalTitle, work.studio, work.series];
    var performers = (names && names.performers) || {};
    var tags = (names && names.tags) || {};
    (work.performers || []).forEach(function (id) { parts.push(performers[id]); });
    (work.tags || []).forEach(function (id) { parts.push(tags[id]); });
    return lower(parts.filter(Boolean).join('\n'));
  }

  /** 多词 AND，不区分大小写；空串返回全部。`names` = {performers:{id:name}, tags:{id:name}}。 */
  function searchWorks(works, query, names) {
    var terms = lower(query).split(/\s+/).filter(Boolean);
    if (!terms.length) return works.slice();
    return works.filter(function (work) {
      var text = haystack(work, names);
      var compact = compactCode(work.code || work.id);
      return terms.every(function (term) {
        return text.indexOf(term) !== -1 || (compact && compact.indexOf(compactCode(term)) !== -1 && /[a-z0-9]/.test(term));
      });
    });
  }

  function yearOf(work) { return work.year == null ? 'none' : work.year; }

  function hintOf(part) { return (part && part.play_hint) || ''; }

  function partPlayable(part) { return hintOf(part) === 'native' || hintOf(part) === 'check' || hintOf(part) === ''; }

  /** 同维度 OR，维度之间 AND。`years` 里的 `"none"` 匹配没有年份的作品。 */
  function filterWorks(works, filters) {
    filters = filters || {};
    function has(list) { return Array.isArray(list) && list.length > 0; }
    return works.filter(function (work) {
      if (has(filters.performers) && !(work.performers || []).some(function (id) { return filters.performers.indexOf(id) !== -1; })) return false;
      if (has(filters.tags) && !(work.tags || []).some(function (id) { return filters.tags.indexOf(id) !== -1; })) return false;
      if (has(filters.studios) && filters.studios.indexOf(work.studio) === -1) return false;
      if (has(filters.series) && filters.series.indexOf(work.series) === -1) return false;
      if (has(filters.years) && filters.years.indexOf(yearOf(work)) === -1) return false;
      if (has(filters.kinds) && filters.kinds.indexOf(work.kind) === -1) return false;
      if (filters.playable === true && !(work.parts || []).some(partPlayable)) return false;
      return true;
    });
  }

  var SORT_KEYS = {
    date: function (work) { return work.date || null; },
    added: function (work) { return work.addedAt || null; },
    duration: function (work) { return work.duration == null ? null : Number(work.duration); },
    code: function (work) { return work.code || work.id || null; }
  };

  /** 空值永远排最后，无论升降序。返回新数组。 */
  function sortWorks(works, key, dir) {
    var pick = SORT_KEYS[key] || SORT_KEYS.date;
    var sign = dir === 'asc' ? 1 : -1;
    return works.slice().sort(function (a, b) {
      var left = pick(a), right = pick(b);
      if (left == null && right == null) return 0;
      if (left == null) return 1;
      if (right == null) return -1;
      if (left < right) return -sign;
      if (left > right) return sign;
      return 0;
    });
  }

  var FACETS = {
    performers: function (work) { return work.performers || []; },
    tags: function (work) { return work.tags || []; },
    studios: function (work) { return work.studio ? [work.studio] : []; },
    series: function (work) { return work.series ? [work.series] : []; },
    years: function (work) { return [yearOf(work)]; },
    kinds: function (work) { return work.kind ? [work.kind] : []; }
  };

  /** 某维度各取值的作品数，按 count 降序、同 count 按取值排。 */
  function facetCounts(works, dim) {
    var pick = FACETS[dim];
    if (!pick) return [];
    var counts = new Map();
    works.forEach(function (work) {
      pick(work).forEach(function (value) { counts.set(value, (counts.get(value) || 0) + 1); });
    });
    var out = [];
    counts.forEach(function (count, value) { out.push({ value: value, count: count }); });
    return out.sort(function (a, b) {
      if (b.count !== a.count) return b.count - a.count;
      var left = String(a.value), right = String(b.value);
      if (a.value === 'none') return 1;
      if (b.value === 'none') return -1;
      return left < right ? -1 : left > right ? 1 : 0;
    });
  }

  var MIME = { mp4: 'video/mp4', m4v: 'video/mp4', mov: 'video/quicktime', webm: 'video/webm' };
  var VCODEC = { h264: 'avc1.640028', hevc: 'hvc1.1.6.L153.B0', h265: 'hvc1.1.6.L153.B0', av1: 'av01.0.08M.08', vp9: 'vp09.00.10.08', vp8: 'vp8' };
  var ACODEC = { aac: 'mp4a.40.2', mp3: 'mp4a.40.34', opus: 'opus', ac3: 'ac-3', eac3: 'ec-3', flac: 'flac', alac: 'alac', vorbis: 'vorbis' };

  function mimeFor(part) {
    var container = lower(part.container);
    var base = MIME[container] || ('video/' + (container || 'mp4'));
    var codecs = [];
    if (VCODEC[lower(part.vcodec)]) codecs.push(VCODEC[lower(part.vcodec)]);
    if (part.acodec && ACODEC[lower(part.acodec)]) codecs.push(ACODEC[lower(part.acodec)]);
    return codecs.length ? base + '; codecs="' + codecs.join(', ') + '"' : base;
  }

  /** `native` → yes；`check` → 用 canPlayType 探，probably/maybe → maybe，否则 no；`unsupported` → no。 */
  function canPlay(part, canPlayType) {
    var hint = hintOf(part);
    if (hint === 'native') return 'yes';
    if (hint === 'unsupported') return 'no';
    if (typeof canPlayType !== 'function') return 'maybe';
    var answer;
    try { answer = canPlayType(mimeFor(part)); } catch (e) { answer = ''; }
    return answer === 'probably' || answer === 'maybe' ? 'maybe' : 'no';
  }

  /** 一部作品的可播放性：有一碟 yes 就 yes；否则有 maybe 就 maybe；否则 no。 */
  function workPlayability(work, canPlayType) {
    var best = 'no';
    (work.parts || []).forEach(function (part) {
      var verdict = canPlay(part, canPlayType);
      if (verdict === 'yes') best = 'yes';
      else if (verdict === 'maybe' && best === 'no') best = 'maybe';
    });
    return best;
  }

  function pad(n) { return n < 10 ? '0' + n : String(n); }

  /** 秒 → `1:23:45` / `12:34` / `0:05`；空值返回空串。 */
  function formatDuration(seconds) {
    if (seconds == null || isNaN(seconds)) return '';
    var total = Math.max(0, Math.round(Number(seconds)));
    var h = Math.floor(total / 3600), m = Math.floor((total % 3600) / 60), s = total % 60;
    return h ? h + ':' + pad(m) + ':' + pad(s) : m + ':' + pad(s);
  }

  var UNITS = ['B', 'KB', 'MB', 'GB', 'TB'];

  function formatBytes(bytes) {
    if (bytes == null || isNaN(bytes)) return '';
    var value = Number(bytes), unit = 0;
    while (value >= 1024 && unit < UNITS.length - 1) { value /= 1024; unit += 1; }
    return (unit === 0 ? String(Math.round(value)) : value.toFixed(1)) + ' ' + UNITS[unit];
  }

  var LIST_KEYS = { performers: 'int', tags: 'int', studios: 'str', series: 'str', years: 'year', kinds: 'str' };

  function parseValue(kind, raw) {
    if (kind === 'int') { var n = parseInt(raw, 10); return isNaN(n) ? undefined : n; }
    if (kind === 'year') { if (raw === 'none') return 'none'; var y = parseInt(raw, 10); return isNaN(y) ? undefined : y; }
    return raw;
  }

  /** `a=1&a=2&q=x` → 筛选状态。认不出的键与值丢掉。 */
  function parseQuery(query) {
    var state = {};
    if (!query) return state;
    String(query).replace(/^[?#]/, '').split('&').forEach(function (pair) {
      if (!pair) return;
      var eq = pair.indexOf('=');
      var key = decodeURIComponent(eq === -1 ? pair : pair.slice(0, eq));
      var raw = eq === -1 ? '' : decodeURIComponent(pair.slice(eq + 1).replace(/\+/g, ' '));
      if (LIST_KEYS[key]) {
        var value = parseValue(LIST_KEYS[key], raw);
        if (value === undefined || raw === '') return;
        (state[key] = state[key] || []).push(value);
      } else if (key === 'q' && raw) state.q = raw;
      else if (key === 'sort' && SORT_KEYS[raw]) state.sort = raw;
      else if (key === 'dir' && (raw === 'asc' || raw === 'desc')) state.dir = raw;
      else if (key === 'page') { var p = parseInt(raw, 10); if (p > 0) state.page = p; }
      else if (key === 'playable' && raw === '1') state.playable = true;
    });
    return state;
  }

  /** 筛选状态 → 查询串（不含 `?`）。空状态给空串。 */
  function buildQuery(state) {
    state = state || {};
    var parts = [];
    function add(key, value) { parts.push(encodeURIComponent(key) + '=' + encodeURIComponent(String(value))); }
    if (state.q) add('q', state.q);
    Object.keys(LIST_KEYS).forEach(function (key) {
      (state[key] || []).forEach(function (value) { add(key, value); });
    });
    if (state.playable === true) add('playable', '1');
    if (state.sort) add('sort', state.sort);
    if (state.dir) add('dir', state.dir);
    if (state.page && state.page > 1) add('page', state.page);
    return parts.join('&');
  }

  /** 分页：页码越界夹到范围内；空列表也算 1 页。 */
  function paginate(items, page, size) {
    size = size || 120;
    var pages = Math.max(1, Math.ceil(items.length / size));
    var current = Math.min(Math.max(1, page || 1), pages);
    var start = (current - 1) * size;
    return { page: current, pages: pages, size: size, total: items.length, items: items.slice(start, start + size) };
  }

  return {
    encodeMediaPath: encodeMediaPath,
    searchWorks: searchWorks,
    filterWorks: filterWorks,
    sortWorks: sortWorks,
    facetCounts: facetCounts,
    canPlay: canPlay,
    workPlayability: workPlayability,
    mimeFor: mimeFor,
    formatDuration: formatDuration,
    formatBytes: formatBytes,
    parseQuery: parseQuery,
    buildQuery: buildQuery,
    paginate: paginate
  };
});
