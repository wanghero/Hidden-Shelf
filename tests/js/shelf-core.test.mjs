// 前端纯逻辑测试：node --test tests/js/
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const core = require(path.join(here, '..', '..', 'src', 'hidden_shelf', 'site', 'static', 'shelf-core.js'));

const works = [
  { id: 'ABP-758', code: 'ABP-758', title: 'Hello 世界', studio: 'Prestige', series: 'S1', date: '2019-05-10', year: 2019,
    performers: [1, 2], tags: [10], duration: 7200, addedAt: '2026-01-02T00:00:00', kind: 'censored',
    parts: [{ play_hint: 'native' }] },
  { id: '259LUXU-1475', code: '259LUXU-1475', title: 'luxu', studio: 'MGS', series: '', date: '', year: null,
    performers: [3], tags: [], duration: null, addedAt: '2026-01-01T00:00:00', kind: 'amateur',
    parts: [{ play_hint: 'check' }, { play_hint: 'unsupported' }] },
  { id: 'ABW-358', code: 'ABW-358', title: '', studio: 'Prestige', series: 'S2', date: '2024-12-01', year: 2024,
    performers: [1], tags: [10, 11], duration: 3600, addedAt: null, kind: 'censored',
    parts: [{ play_hint: 'unsupported' }] },
];
const names = { performers: { 1: '三上悠亜', 2: '乙', 3: 'Mika' }, tags: { 10: '巨乳', 11: '中文字幕' } };

test('encodeMediaPath encodes every segment but keeps slashes', () => {
  assert.equal(core.encodeMediaPath('厂牌/ABP-758/ABP-758 #1 50%.mp4'),
    '%E5%8E%82%E7%89%8C/ABP-758/ABP-758%20%231%2050%25.mp4');
  assert.equal(core.encodeMediaPath('a?b/c.mp4'), 'a%3Fb/c.mp4');
  assert.equal(core.encodeMediaPath(''), '');
  assert.equal(core.encodeMediaPath('.shelf/covers/ABP-758.jpg'), '.shelf/covers/ABP-758.jpg');
});

test('searchWorks is case-insensitive, multi-word AND, empty returns all', () => {
  assert.equal(core.searchWorks(works, '', names).length, 3);
  assert.equal(core.searchWorks(works, '   ', names).length, 3);
  assert.deepEqual(core.searchWorks(works, 'abp', names).map(w => w.id), ['ABP-758']);
  assert.deepEqual(core.searchWorks(works, 'prestige', names).map(w => w.id), ['ABP-758', 'ABW-358']);
  assert.deepEqual(core.searchWorks(works, 'prestige 世界', names).map(w => w.id), ['ABP-758']);
  assert.deepEqual(core.searchWorks(works, '三上', names).map(w => w.id), ['ABP-758', 'ABW-358']);
  assert.deepEqual(core.searchWorks(works, '中文字幕', names).map(w => w.id), ['ABW-358']);
  assert.deepEqual(core.searchWorks(works, 'mika', names).map(w => w.id), ['259LUXU-1475']);
  assert.deepEqual(core.searchWorks(works, 'abp758', names).map(w => w.id), ['ABP-758']);
  assert.equal(core.searchWorks(works, 'nothing', names).length, 0);
});

test('filterWorks ORs inside a dimension and ANDs across dimensions', () => {
  const by = (filters) => core.filterWorks(works, filters).map(w => w.id);
  assert.deepEqual(by({}), ['ABP-758', '259LUXU-1475', 'ABW-358']);
  assert.deepEqual(by({ performers: [1] }), ['ABP-758', 'ABW-358']);
  assert.deepEqual(by({ performers: [2, 3] }), ['ABP-758', '259LUXU-1475']);
  assert.deepEqual(by({ performers: [1], tags: [11] }), ['ABW-358']);
  assert.deepEqual(by({ studios: ['MGS'] }), ['259LUXU-1475']);
  assert.deepEqual(by({ series: ['S1', 'S2'] }), ['ABP-758', 'ABW-358']);
  assert.deepEqual(by({ years: [2019] }), ['ABP-758']);
  assert.deepEqual(by({ years: ['none'] }), ['259LUXU-1475']);
  assert.deepEqual(by({ years: [2024, 'none'] }), ['259LUXU-1475', 'ABW-358']);
  assert.deepEqual(by({ kinds: ['amateur'] }), ['259LUXU-1475']);
  assert.deepEqual(by({ playable: true }), ['ABP-758', '259LUXU-1475']);
  assert.deepEqual(by({ playable: null }), ['ABP-758', '259LUXU-1475', 'ABW-358']);
  assert.deepEqual(by({ studios: ['Prestige'], playable: true }), ['ABP-758']);
});

test('sortWorks puts empty values last in both directions', () => {
  const ids = (key, dir) => core.sortWorks(works, key, dir).map(w => w.id);
  assert.deepEqual(ids('date', 'desc'), ['ABW-358', 'ABP-758', '259LUXU-1475']);
  assert.deepEqual(ids('date', 'asc'), ['ABP-758', 'ABW-358', '259LUXU-1475']);
  assert.deepEqual(ids('duration', 'desc'), ['ABP-758', 'ABW-358', '259LUXU-1475']);
  assert.deepEqual(ids('duration', 'asc'), ['ABW-358', 'ABP-758', '259LUXU-1475']);
  assert.deepEqual(ids('added', 'desc'), ['ABP-758', '259LUXU-1475', 'ABW-358']);
  assert.deepEqual(ids('code', 'asc'), ['259LUXU-1475', 'ABP-758', 'ABW-358']);
  assert.deepEqual(ids('code', 'desc'), ['ABW-358', 'ABP-758', '259LUXU-1475']);
  // 不改原数组
  assert.equal(works[0].id, 'ABP-758');
});

test('facetCounts counts values by count desc then name', () => {
  assert.deepEqual(core.facetCounts(works, 'studios'), [
    { value: 'Prestige', count: 2 }, { value: 'MGS', count: 1 }]);
  assert.deepEqual(core.facetCounts(works, 'performers'), [
    { value: 1, count: 2 }, { value: 2, count: 1 }, { value: 3, count: 1 }]);
  assert.deepEqual(core.facetCounts(works, 'years'), [
    { value: 2019, count: 1 }, { value: 2024, count: 1 }, { value: 'none', count: 1 }]);
  assert.deepEqual(core.facetCounts(works, 'kinds'), [
    { value: 'censored', count: 2 }, { value: 'amateur', count: 1 }]);
  assert.deepEqual(core.facetCounts(works, 'series'), [
    { value: 'S1', count: 1 }, { value: 'S2', count: 1 }]);
});

test('canPlay maps hints through canPlayType', () => {
  const probably = () => 'probably';
  const maybe = () => 'maybe';
  const nope = () => '';
  assert.equal(core.canPlay({ play_hint: 'native' }, nope), 'yes');
  assert.equal(core.canPlay({ play_hint: 'check', container: 'mp4', vcodec: 'hevc', acodec: 'aac' }, probably), 'maybe');
  assert.equal(core.canPlay({ play_hint: 'check', container: 'mp4', vcodec: 'hevc', acodec: 'aac' }, maybe), 'maybe');
  assert.equal(core.canPlay({ play_hint: 'check', container: 'mp4', vcodec: 'hevc', acodec: 'aac' }, nope), 'no');
  assert.equal(core.canPlay({ play_hint: 'unsupported' }, probably), 'no');
  assert.equal(core.canPlay({ play_hint: '' }, probably), 'maybe');
  assert.equal(core.canPlay({ play_hint: 'check' }, null), 'maybe');
  let asked = '';
  core.canPlay({ play_hint: 'check', container: 'mp4', vcodec: 'hevc', acodec: 'aac' }, (mime) => { asked = mime; return ''; });
  assert.match(asked, /^video\/mp4; codecs="hvc1/);
});

test('workPlayability summarises parts', () => {
  const yes = () => 'probably';
  assert.equal(core.workPlayability(works[0], yes), 'yes');
  assert.equal(core.workPlayability(works[1], yes), 'maybe');
  assert.equal(core.workPlayability(works[2], yes), 'no');
  assert.equal(core.workPlayability({ parts: [] }, yes), 'no');
});

test('formatDuration and formatBytes', () => {
  assert.equal(core.formatDuration(3725), '1:02:05');
  assert.equal(core.formatDuration(754), '12:34');
  assert.equal(core.formatDuration(5), '0:05');
  assert.equal(core.formatDuration(0), '0:00');
  assert.equal(core.formatDuration(null), '');
  assert.equal(core.formatBytes(0), '0 B');
  assert.equal(core.formatBytes(1023), '1023 B');
  assert.equal(core.formatBytes(1536), '1.5 KB');
  assert.equal(core.formatBytes(5 * 1024 * 1024 * 1024), '5.0 GB');
  assert.equal(core.formatBytes(null), '');
});

test('parseQuery and buildQuery round-trip the hash filter state', () => {
  const state = { q: 'a b', performers: [1, 2], studios: ['Prestige', 'M/GS'], years: [2019, 'none'],
    kinds: ['censored'], playable: true, sort: 'date', dir: 'asc', page: 3 };
  const query = core.buildQuery(state);
  assert.ok(!query.includes(' '));
  const back = core.parseQuery(query);
  assert.deepEqual(back, state);
  assert.deepEqual(core.parseQuery(''), {});
  assert.equal(core.buildQuery({}), '');
  assert.deepEqual(core.parseQuery('performers=x'), {});
});

test('paginate', () => {
  const items = Array.from({ length: 250 }, (_, i) => i);
  const page = core.paginate(items, 2, 120);
  assert.deepEqual([page.page, page.pages, page.items.length, page.items[0]], [2, 3, 120, 120]);
  assert.deepEqual(core.paginate(items, 99, 120).items.length, 10);
  assert.deepEqual(core.paginate([], 1, 120).pages, 1);
});
