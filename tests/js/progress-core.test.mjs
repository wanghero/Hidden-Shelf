// 进度网页纯逻辑测试：node --test "tests/js/**/*.test.mjs"
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const core = require(path.join(here, '..', '..', 'src', 'hidden_shelf', 'serve', 'static', 'progress-core.js'));
const dict = require(path.join(here, '..', '..', 'src', 'hidden_shelf', 'serve', 'static', 'i18n.js'));

const ORDER = ['scan', 'import', 'scrape', 'organize', 'media', 'build'];
let seq = 0;
function ev(kind, extra) { return Object.assign({ seq: ++seq, ts: '2026-10-29T00:00:0' + (seq % 10) + '.000+00:00', run: 'r1', kind, step: null, level: null, message: null, stats: null }, extra); }
function t(key, vars) {
  let text = dict.zh[key] != null ? dict.zh[key] : key;
  Object.keys(vars || {}).forEach((name) => { text = text.split('{' + name + '}').join(String(vars[name])); });
  return text;
}

test('reduce walks a step through start, progress, done', () => {
  let state = core.initialState(ORDER);
  assert.equal(Object.keys(state.steps).length, 6);
  assert.equal(state.steps.scan.status, 'waiting');
  state = core.reduce(state, ev('run.start', { stats: { root: '/disk', options: { offline: true } } }));
  assert.equal(state.running, true);
  assert.equal(state.root, '/disk');
  assert.equal(state.options.offline, true);
  state = core.reduce(state, ev('step.start', { step: 'scan' }));
  assert.equal(state.steps.scan.status, 'running');
  state = core.reduce(state, ev('step.progress', { step: 'scan', level: 'info', message: '[3/12] 登记 a.mp4' }));
  assert.equal(state.steps.scan.message, '[3/12] 登记 a.mp4');
  assert.equal(state.steps.scan.percent, 25);
  state = core.reduce(state, ev('step.done', { step: 'scan', stats: { added: 3 } }));
  assert.equal(state.steps.scan.status, 'done');
  assert.deepEqual(state.steps.scan.stats, { added: 3 });
  assert.equal(state.steps.scan.percent, 100);
  assert.equal(state.lastSeq, seq);
});

test('failed, skipped, cancel request and run end are reflected; run.start resets', () => {
  let state = core.reduceAll(ORDER, [
    ev('run.start', { stats: { root: '/d' } }),
    ev('step.start', { step: 'scrape' }),
    ev('step.failed', { step: 'scrape', level: 'error', message: 'RuntimeError: 炸了' }),
    ev('step.start', { step: 'organize' }),
    ev('step.skipped', { step: 'organize', message: '--offline' }),
    ev('step.progress', { step: 'organize', level: 'warning', message: '收到停止请求：当前步完成后不再继续' }),
    ev('run.cancelled', { stats: { ok: true } }),
  ]);
  assert.equal(state.steps.scrape.status, 'failed');
  assert.equal(state.steps.scrape.error, 'RuntimeError: 炸了');
  assert.equal(state.steps.organize.status, 'skipped');
  assert.equal(state.steps.organize.message, '--offline');
  assert.equal(state.cancelRequested, true);
  assert.equal(state.running, false);
  assert.deepEqual(state.result, { ok: true, cancelled: true });
  assert.equal(state.steps.build.status, 'waiting');
  const reset = core.reduce(state, ev('run.start', { run: 'r2', stats: {} }));
  assert.equal(reset.run, 'r2');
  assert.equal(reset.steps.scrape.status, 'waiting');
  assert.equal(reset.cancelRequested, false);
  assert.equal(reset.result, null);
  // 未知步与坏事件忽略，不抛。
  const same = core.reduce(reset, ev('step.start', { step: 'hentai' }));
  assert.equal(same.steps.scan.status, 'waiting');
  assert.deepEqual(core.reduce(reset, null).steps, reset.steps);
  // 不改旧状态。
  assert.equal(state.steps.scrape.status, 'failed');
});

test('percentOf reads the [i/total] prefix only', () => {
  assert.equal(core.percentOf('[3/12] 九宫格 x'), 25);
  assert.equal(core.percentOf('[12/12] 完成'), 100);
  assert.equal(core.percentOf('[0/0] 空'), null);
  assert.equal(core.percentOf('扫描 [1/2]'), null);
  assert.equal(core.percentOf(''), null);
  assert.equal(core.percentOf(null), null);
});

test('formatElapsed in both languages', () => {
  assert.equal(core.formatElapsed(65000, 'zh'), '1 分 5 秒');
  assert.equal(core.formatElapsed(65000, 'en'), '1m 5s');
  assert.equal(core.formatElapsed(42000, 'zh'), '42 秒');
  assert.equal(core.formatElapsed(42000, 'en'), '42s');
  assert.equal(core.formatElapsed(3720000, 'zh'), '1 小时 2 分');
  assert.equal(core.formatElapsed(3720000, 'en'), '1h 2m');
  assert.equal(core.formatElapsed(-5, 'en'), '0s');
  assert.equal(core.formatElapsed(undefined, 'zh'), '0 秒');
});

test('filterLog keeps log-worthy kinds and filters by step', () => {
  const events = [
    ev('run.start', {}), ev('step.start', { step: 'scan' }),
    ev('step.progress', { step: 'scan', message: 'a' }), ev('step.progress', { step: 'media', message: 'b' }),
    ev('step.failed', { step: 'build', message: 'c' }), ev('step.skipped', { step: 'scrape', message: 'd' }), ev('run.done', {}),
  ];
  assert.deepEqual(core.filterLog(events, 'all').map((e) => e.message), ['a', 'b', 'c', 'd']);
  assert.deepEqual(core.filterLog(events, '').map((e) => e.message), ['a', 'b', 'c', 'd']);
  assert.deepEqual(core.filterLog(events, 'media').map((e) => e.message), ['b']);
  assert.deepEqual(core.filterLog(events, 'organize'), []);
  assert.deepEqual(core.filterLog(null, 'all'), []);
});

test('summaryOf fills the per-step template and tolerates odd stats', () => {
  const scan = core.summaryOf('scan', { added: 3, vanished: 1, unrecognized: 0, rescan: {} }, t);
  assert.ok(scan.includes('3') && scan.includes('1') && scan.includes('未识别 0'), scan);
  assert.equal(core.summaryOf('scrape', { asked: 2, settled: 1, covers: 1, avatars: 0, paused: ['javdb'] }, t), '问了 2 次，落库 1，封面 1，头像 0');
  assert.equal(core.summaryOf('organize', { moved: 4 }, t), '移动 4，跳过 0', '缺的键补 0');
  assert.equal(core.summaryOf('scrape', { skipped: true, reason: '--offline' }, t), '--offline');
  assert.equal(core.summaryOf('bogus', { x: 1 }, t), '');
  assert.equal(core.summaryOf('scan', null, t), '');
  assert.equal(core.summaryOf('build', { works: 12, performers: 3, unrecognized: 1 }, t), '作品 12，艺人 3，未识别 1');
});

test('zh and en dictionaries share the same keys', () => {
  assert.deepEqual(Object.keys(dict.zh).sort(), Object.keys(dict.en).sort());
  assert.ok(Object.keys(dict.zh).length > 50);
});

test('breadcrumbs splits POSIX and Windows paths into clickable segments', () => {
  assert.deepEqual(core.breadcrumbs('/Volumes/我的盘/30、下载'), [
    { name: '/', path: '/' },
    { name: 'Volumes', path: '/Volumes' },
    { name: '我的盘', path: '/Volumes/我的盘' },
    { name: '30、下载', path: '/Volumes/我的盘/30、下载' },
  ]);
  assert.deepEqual(core.breadcrumbs('/'), [{ name: '/', path: '/' }]);
  assert.deepEqual(core.breadcrumbs('/a/'), [{ name: '/', path: '/' }, { name: 'a', path: '/a' }], '尾部斜杠忽略');
  assert.deepEqual(core.breadcrumbs('D:\\a\\b'), [
    { name: 'D:\\', path: 'D:\\' },
    { name: 'a', path: 'D:\\a' },
    { name: 'b', path: 'D:\\a\\b' },
  ]);
  assert.deepEqual(core.breadcrumbs('D:\\'), [{ name: 'D:\\', path: 'D:\\' }]);
  assert.deepEqual(core.breadcrumbs(''), []);
  assert.deepEqual(core.breadcrumbs(null), []);
});

test('sortEntries is numeric-aware and case-insensitive, and does not mutate', () => {
  const entries = ['10', '2', 'b', 'A'].map((name) => ({ name, path: '/' + name, has_shelf: false }));
  const sorted = core.sortEntries(entries);
  assert.deepEqual(sorted.map((e) => e.name), ['2', '10', 'A', 'b']);
  assert.deepEqual(entries.map((e) => e.name), ['10', '2', 'b', 'A'], '原数组不动');
  assert.deepEqual(core.sortEntries(null), []);
});

test('browseUrl encodes the path and omits it when empty', () => {
  assert.equal(core.browseUrl('/Volumes/我的盘/30、下载 #1', false),
    '/api/browse?path=' + encodeURIComponent('/Volumes/我的盘/30、下载 #1'));
  assert.ok(core.browseUrl('/a b#c', false).indexOf('%23') > 0, '# 必须编码');
  assert.equal(core.browseUrl('/a', true), '/api/browse?path=%2Fa&show_hidden=1');
  assert.equal(core.browseUrl('', false), '/api/browse');
  assert.equal(core.browseUrl(null, true), '/api/browse?show_hidden=1');
});
