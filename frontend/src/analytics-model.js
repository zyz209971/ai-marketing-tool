// Pure formatting and geometry helpers for the operating dashboard.
export function formatFen(value, {signed = false} = {}) {
  if (value == null || !Number.isFinite(Number(value))) return '—';
  const number = Number(value);
  const sign = number < 0 ? '-' : signed && number > 0 ? '+' : '';
  return sign + '¥' + (Math.abs(number) / 100).toFixed(2);
}

export function formatCups(value) {
  if (value == null || !Number.isFinite(Number(value))) return '—';
  return Number(value).toLocaleString('zh-CN');
}

export function formatPercent(value) {
  if (value == null || !Number.isFinite(Number(value))) return '—';
  return (Number(value) * 100).toFixed(1) + '%';
}

export function dateLabel(value) {
  return typeof value === 'string' ? value.slice(5) : '';
}

export function chartBounds(values) {
  const finite = values.filter(value => value != null && Number.isFinite(Number(value))).map(Number);
  if (!finite.length) return {min: 0, max: 1};
  const min = Math.min(0, ...finite);
  const max = Math.max(0, ...finite);
  return min === max ? {min: 0, max: 1} : {min, max};
}

export function seriesPoints(values, {width, height, padX = 38, padY = 22, min, max} = {}) {
  const bounds = chartBounds(values);
  const low = min ?? bounds.min;
  const high = max ?? bounds.max;
  const innerWidth = Math.max(1, width - padX * 2);
  const innerHeight = Math.max(1, height - padY * 2);
  return values.map((value, index) => ({
    x: padX + (values.length <= 1 ? innerWidth / 2 : innerWidth * index / (values.length - 1)),
    y: value == null ? null : padY + innerHeight - ((Number(value) - low) / (high - low)) * innerHeight,
    value: value == null ? null : Number(value),
    index,
  }));
}

export function splitSegments(points) {
  const segments = [];
  let current = [];
  for (const point of points) {
    if (point.y == null || point.value == null) {
      if (current.length) segments.push(current);
      current = [];
      continue;
    }
    current.push(point);
  }
  if (current.length) segments.push(current);
  return segments;
}

export function barSeries(values, {width, height, padX = 38, padY = 22, max} = {}) {
  const bounds = chartBounds(values);
  const high = max ?? (bounds.max || 1);
  const innerWidth = Math.max(1, width - padX * 2);
  const innerHeight = Math.max(1, height - padY * 2);
  const slot = innerWidth / Math.max(1, values.length);
  const barWidth = Math.max(3, Math.min(22, slot * 0.58));
  return values.map((value, index) => {
    const number = value == null ? null : Math.max(0, Number(value));
    const barHeight = number == null ? 0 : Math.max(number === 0 ? 1 : 2, (number / high) * innerHeight);
    return {
      x: padX + slot * index + (slot - barWidth) / 2,
      y: padY + innerHeight - barHeight,
      width: barWidth,
      height: barHeight,
      value: number,
      index,
    };
  });
}

export function sortProductRows(rows, sort) {
  const key = {cups: 'cups', revenue: 'net_revenue_fen', contribution: 'contribution_fen'}[sort] || 'net_revenue_fen';
  return [...rows].sort((left, right) => {
    const a = left[key], b = right[key];
    if (a == null && b == null) return String(left.name).localeCompare(String(right.name), 'zh-CN');
    if (a == null) return 1;
    if (b == null) return -1;
    return Number(b) - Number(a);
  });
}

export function coverageLabel(coverage) {
  if (!coverage) return '完整性未知';
  if (coverage.outside_dates?.length) return `超出数据范围 ${coverage.outside_dates.length} 天`;
  if (coverage.complete) return '日期覆盖完整';
  return `缺 ${coverage.missing_dates?.length || 0} 天`;
}
