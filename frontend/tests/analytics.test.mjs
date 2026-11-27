import test from 'node:test';
import assert from 'node:assert/strict';
import {
  barSeries, chartBounds, coverageLabel, formatCups, formatFen, seriesPoints,
  sortProductRows, splitSegments,
} from '../src/analytics-model.js';

test('money and cup formatting keeps unknown separate from zero', () => {
  assert.equal(formatFen(null), '—');
  assert.equal(formatFen(0), '¥0.00');
  assert.equal(formatFen(-16200), '-¥162.00');
  assert.equal(formatFen(500, {signed: true}), '+¥5.00');
  assert.equal(formatCups(0), '0');
  assert.equal(formatCups(null), '—');
});

test('line geometry breaks at missing values instead of joining them', () => {
  const points = seriesPoints([100, null, -100], {width: 300, height: 200, padX: 20, padY: 20});
  assert.equal(points.length, 3);
  assert.equal(points[1].y, null);
  assert.deepEqual(splitSegments(points).map(segment => segment.map(point => point.index)), [[0], [2]]);
  assert.deepEqual(chartBounds([100, null, -100]), {min: -100, max: 100});
});

test('bar geometry distinguishes zero from missing values', () => {
  const bars = barSeries([0, null, 5], {width: 300, height: 200, padX: 20, padY: 20});
  assert.equal(bars[0].height, 1);
  assert.equal(bars[1].value, null);
  assert.ok(bars[2].height > 1);
});

test('product ranking puts unknown contribution last', () => {
  const rows = [
    {name: '成本未知', contribution_fen: null, net_revenue_fen: 100},
    {name: '低贡献', contribution_fen: 100, net_revenue_fen: 500},
    {name: '高贡献', contribution_fen: 300, net_revenue_fen: 400},
  ];
  assert.deepEqual(sortProductRows(rows, 'contribution').map(row => row.name), ['高贡献', '低贡献', '成本未知']);
});

test('coverage label reports missing days', () => {
  assert.equal(coverageLabel({complete: true, missing_dates: []}), '日期覆盖完整');
  assert.equal(coverageLabel({complete: false, missing_dates: ['2026-01-04']}), '缺 1 天');
  assert.equal(coverageLabel({complete: false, outside_dates: ['2026-01-05']}), '超出数据范围 1 天');
  assert.equal(coverageLabel(null), '完整性未知');
});
