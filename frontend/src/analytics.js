import {request} from './services/api.js';
import {
  barSeries, chartBounds, coverageLabel, dateLabel, formatCups, formatFen,
  seriesPoints, sortProductRows, splitSegments,
} from './analytics-model.js';

const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[char]));
const state = {
  config: null, loaded: false, start: '', end: '', sku: '', sort: 'revenue',
  summary: null, points: [], products: [], campaigns: [], quality: null,
  detail: null, loading: false, error: '', request: 0,
};
let initialized = false;

const query = (includeSort = false) => {
  const params = new URLSearchParams({start: state.start, end: state.end});
  if (state.sku) params.set('sku', state.sku);
  if (includeSort) params.set('sort', state.sort);
  return params.toString();
};

const productName = id => state.config?.products?.find(product => product.product_id === id)?.name || id;

function kpi(label, value, note = '') {
  return `<article class="analytics-kpi"><span>${esc(label)}</span><strong>${value}</strong>${note ? `<small>${esc(note)}</small>` : ''}</article>`;
}

function chip(text, tone = '') {
  return `<span class="analytics-chip ${tone}">${esc(text)}</span>`;
}

function yAxis(values, low, high) {
  const ticks = [];
  for (let index = 0; index <= 4; index += 1) {
    const value = low + (high - low) * index / 4;
    ticks.push({value, ratio: index / 4});
  }
  return ticks;
}

function trendChart(points, {width = 760, height = 286, compact = false} = {}) {
  if (!points.length) return '<p class="analytics-empty">当前区间没有可绘制的日数据。</p>';
  const padX = 46, padY = 24;
  const values = points.flatMap(point => [point.net_revenue_fen, point.contribution_fen]);
  const bounds = chartBounds(values);
  const revenue = seriesPoints(points.map(point => point.net_revenue_fen), {width, height, padX, padY, min: bounds.min, max: bounds.max});
  const contribution = seriesPoints(points.map(point => point.contribution_fen), {width, height, padX, padY, min: bounds.min, max: bounds.max});
  const baseline = padY + (height - padY * 2) - ((0 - bounds.min) / (bounds.max - bounds.min)) * (height - padY * 2);
  const path = series => splitSegments(series).map(segment => segment.map((point, index) =>
    `${index ? 'L' : 'M'}${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(' ')).join(' ');
  const tickIndexes = [...new Set([0, Math.floor((points.length - 1) / 4), Math.floor((points.length - 1) / 2),
    Math.floor((points.length - 1) * 3 / 4), points.length - 1])];
  const yTicks = yAxis(values, bounds.min, bounds.max);
  const circles = series => series.filter(point => point.value != null).map(point =>
    `<circle class="analytics-point" cx="${point.x.toFixed(1)}" cy="${point.y.toFixed(1)}" r="2.6"><title>${esc(dateLabel(points[point.index].date))} ${formatFen(point.value)}</title></circle>`).join('');
  return `<div class="analytics-chart-wrap${compact ? ' compact' : ''}">
    <div class="analytics-legend"><span class="legend-revenue">● 净收入</span><span class="legend-contribution">● 贡献</span><span class="legend-missing">虚线空档 = 数据缺失/成本未知</span></div>
    <svg class="analytics-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="每日净收入与贡献趋势">
      ${yTicks.map(tick => `<g><line class="chart-grid" x1="${padX}" x2="${width - padX}" y1="${(padY + (height - padY * 2) * tick.ratio).toFixed(1)}" y2="${(padY + (height - padY * 2) * tick.ratio).toFixed(1)}"/><text class="chart-axis" x="4" y="${(padY + (height - padY * 2) * tick.ratio + 4).toFixed(1)}">${esc(formatFen(tick.value))}</text></g>`).join('')}
      ${bounds.min < 0 ? `<line class="chart-zero" x1="${padX}" x2="${width - padX}" y1="${baseline.toFixed(1)}" y2="${baseline.toFixed(1)}"/>` : ''}
      <path class="chart-line revenue" d="${path(revenue)}"/>
      <path class="chart-line contribution" d="${path(contribution)}"/>
      ${circles(revenue)}${circles(contribution)}
      ${tickIndexes.map(index => `<text class="chart-axis chart-x" x="${revenue[index].x.toFixed(1)}" y="${height - 6}" text-anchor="middle">${esc(dateLabel(points[index].date))}</text>`).join('')}
    </svg>
  </div>`;
}

function cupsChart(points) {
  if (!points.length) return '<p class="analytics-empty">当前区间没有可绘制的日数据。</p>';
  const width = 760, height = 230, padX = 46, padY = 22;
  const values = points.map(point => point.state === 'missing' || point.state === 'not_on_sale' ? null : point.cups);
  const bars = barSeries(values, {width, height, padX, padY});
  const baseline = padY + (height - padY * 2);
  const tickIndexes = [...new Set([0, Math.floor((points.length - 1) / 4), Math.floor((points.length - 1) / 2),
    Math.floor((points.length - 1) * 3 / 4), points.length - 1])];
  return `<div class="analytics-chart-wrap">
    <div class="analytics-legend"><span class="legend-cups">■ 有销量</span><span class="legend-zero">■ 零销量</span><span class="legend-missing">┄ 数据缺失</span></div>
    <svg class="analytics-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="每日交付杯数">
      <line class="chart-grid" x1="${padX}" x2="${width - padX}" y1="${baseline}" y2="${baseline}"/>
      ${bars.map((bar, index) => {
        const point = points[index];
        if (point.state === 'missing') return `<rect class="bar-missing" x="${bar.x.toFixed(1)}" y="${(baseline - 4).toFixed(1)}" width="${bar.width.toFixed(1)}" height="4"><title>${esc(point.date)} 数据缺失</title></rect>`;
        if (point.state === 'zero') return `<rect class="bar-zero" x="${bar.x.toFixed(1)}" y="${(baseline - 1).toFixed(1)}" width="${bar.width.toFixed(1)}" height="1"><title>${esc(point.date)} 零销量</title></rect>`;
        return `<rect class="bar-ok" x="${bar.x.toFixed(1)}" y="${bar.y.toFixed(1)}" width="${bar.width.toFixed(1)}" height="${bar.height.toFixed(1)}"><title>${esc(point.date)} ${formatCups(point.cups)} 杯</title></rect>`;
      }).join('')}
      ${tickIndexes.map(index => `<text class="chart-axis chart-x" x="${bars[index].x.toFixed(1)}" y="${height - 6}" text-anchor="middle">${esc(dateLabel(points[index].date))}</text>`).join('')}
    </svg>
  </div>`;
}

function summaryCards() {
  const summary = state.summary;
  if (!summary) return '';
  const contribution = summary.contribution_fen == null
    ? '<span class="analytics-unknown">成本未知</span>'
    : formatFen(summary.contribution_fen);
  const contributionNote = summary.contribution_complete
    ? '净收入 − 变动成本，不等于净利润'
    : `含缺成本商品：${summary.missing_cost_skus.map(productName).join('、') || '未匹配成本'}`;
  const coverage = summary.coverage;
  return `<section class="analytics-kpis">
    ${kpi('净收入', formatFen(summary.net_revenue_fen), '已扣优惠与退款')}
    ${kpi('交付杯数', formatCups(summary.cups), '退款前交付仍计入')}
    ${kpi('订单数', formatCups(summary.order_count), '按订单号去重')}
    ${kpi('贡献', contribution, contributionNote)}
  </section>
  <section class="analytics-submetrics">
    <span>优惠 ${formatFen(summary.discount_fen)}</span>
    <span>退款 ${formatFen(summary.refund_fen)}</span>
    <span>数据截至 ${esc(state.config.data_as_of || summary.data_as_of || '—')}</span>
    <span class="${coverage?.complete ? 'ok' : 'warn'}">${esc(coverageLabel(coverage))}</span>
    <span class="analytics-source">合成数据 · ${esc(state.config.dataset_version)}</span>
  </section>`;
}

function sortButton(sort, label) {
  return `<button type="button" class="analytics-sort ${state.sort === sort ? 'active' : ''}" data-sort="${sort}">${label}</button>`;
}

function productRanking() {
  const rows = sortProductRows(state.products, state.sort);
  return `<section class="analytics-card">
    <div class="analytics-card-head"><div><h2>商品经营排名</h2><p>同一筛选下按净收入、杯数或贡献排序；贡献未知的商品排在最后。</p></div><div class="analytics-sort-group">${sortButton('revenue', '净收入')}${sortButton('cups', '杯数')}${sortButton('contribution', '贡献')}</div></div>
    <div class="analytics-table-wrap"><table class="analytics-table"><thead><tr><th>商品</th><th>杯数</th><th>订单数</th><th>净收入</th><th>优惠</th><th>退款</th><th>贡献</th></tr></thead><tbody>
      ${rows.map(row => `<tr class="analytics-rank-row" data-product="${esc(row.product_id)}" tabindex="0"><td><strong>${esc(row.name)}</strong><small>${esc(row.category || '未分类')}</small></td><td>${formatCups(row.cups)}</td><td>${formatCups(row.order_count)}</td><td>${formatFen(row.net_revenue_fen)}</td><td>${formatFen(row.discount_fen)}</td><td>${formatFen(row.refund_fen)}</td><td class="${row.contribution_fen == null ? 'unknown' : ''}">${row.contribution_fen == null ? '成本未知' : formatFen(row.contribution_fen)}</td></tr>`).join('') || '<tr><td colspan="7">当前区间没有商品订单。</td></tr>'}
    </tbody></table></div>
  </section>`;
}

function productDetail() {
  if (!state.detail) return '';
  const detail = state.detail;
  const product = detail.product;
  if (!product) return '';
  return `<section class="analytics-card analytics-detail" id="analyticsDetail">
    <div class="analytics-card-head"><div><h2>${esc(product.name)} · 商品明细</h2><p>${esc(product.category || '未分类')} · 数据与上方筛选一致</p></div><button type="button" id="closeAnalyticsDetail">收起</button></div>
    <div class="analytics-detail-kpis">${kpi('杯数', formatCups(product.cups))}${kpi('净收入', formatFen(product.net_revenue_fen))}${kpi('贡献', product.contribution_fen == null ? '成本未知' : formatFen(product.contribution_fen))}</div>
    ${trendChart(detail.points, {width: 680, height: 230, compact: true})}
    <p class="analytics-note">商品明细暂未接入 Agent：当前数据集的商品编号未关联到品牌商品，直接带入会被品牌授权校验拒绝。</p>
  </section>`;
}

function campaignChart() {
  const campaigns = state.campaigns.filter(campaign => campaign.cups > 0);
  if (!campaigns.length) return '';
  const values = campaigns.map(campaign => campaign.contribution_fen == null ? null : campaign.contribution_fen / campaign.cups);
  const minimum = state.config.min_contribution_fen;
  const high = Math.max(1, ...values.filter(value => value != null), minimum ?? 0);
  const width = 720, height = 190, padX = 52, padY = 24;
  const bars = barSeries(values, {width, height, padX, padY, max: high});
  const baseline = padY + (height - padY * 2);
  const minimumY = minimum == null ? null : baseline - (minimum / high) * (height - padY * 2);
  return `<div class="analytics-campaign-chart">
    <div class="analytics-legend"><span class="legend-contribution">■ 活动整体平均每杯贡献</span>${minimum == null ? '' : '<span class="legend-minimum">┄ 最低贡献参考线</span>'}</div>
    <svg class="analytics-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="活动贡献与最低贡献参考线">
      <line class="chart-grid" x1="${padX}" x2="${width - padX}" y1="${baseline}" y2="${baseline}"/>
      ${minimumY == null ? '' : `<line class="chart-minimum" x1="${padX}" x2="${width - padX}" y1="${minimumY.toFixed(1)}" y2="${minimumY.toFixed(1)}"><title>最低贡献 ${formatFen(minimum)}/杯</title></line>`}
      ${bars.map((bar, index) => {
        const campaign = campaigns[index];
        if (bar.value == null) return `<rect class="bar-missing" x="${bar.x.toFixed(1)}" y="${(baseline - 4).toFixed(1)}" width="${bar.width.toFixed(1)}" height="4"><title>${esc(campaign.campaign_id)} 成本未知</title></rect>`;
        return `<rect class="bar-ok" x="${bar.x.toFixed(1)}" y="${bar.y.toFixed(1)}" width="${bar.width.toFixed(1)}" height="${bar.height.toFixed(1)}"><title>${esc(campaign.campaign_id)} ${formatFen(bar.value)}/杯</title></rect>`;
      }).join('')}
      ${bars.map((bar, index) => `<text class="chart-axis chart-x" x="${(bar.x + bar.width / 2).toFixed(1)}" y="${height - 6}" text-anchor="middle">${esc(campaigns[index].campaign_id)}</text>`).join('')}
    </svg>
    <p class="analytics-note">第二杯活动尚未精确拆分“参与两杯平均”，此图显示活动整体平均每杯贡献；最低贡献参考线来自数据集口径。</p>
  </div>`;
}

function campaignTable() {
  if (!state.campaigns.length) return '';
  return `<section class="analytics-card">
    <div class="analytics-card-head"><div><h2>优惠与活动结果</h2><p>活动期内该商品全部订单；宣传费来自活动元数据。基线规则未配置，因此不展示增量。</p></div>${chip('事后比较，不是因果归因')}</div>
    ${campaignChart()}
    <div class="analytics-table-wrap"><table class="analytics-table"><thead><tr><th>活动</th><th>期间</th><th>杯数</th><th>参与杯数</th><th>净收入</th><th>优惠</th><th>贡献</th><th>实际宣传费</th><th>扣费后贡献</th></tr></thead><tbody>
      ${state.campaigns.map(campaign => `<tr><td><strong>${esc(campaign.campaign_id)}</strong><small>${esc(campaign.sku)} · ${esc(campaign.rule)}</small></td><td>${esc(campaign.start)}<br>至 ${esc(campaign.end)}</td><td>${formatCups(campaign.cups)}</td><td>${formatCups(campaign.participating_cups)}</td><td>${formatFen(campaign.net_revenue_fen)}</td><td>${formatFen(campaign.discount_fen)}</td><td>${campaign.contribution_fen == null ? '成本未知' : formatFen(campaign.contribution_fen)}</td><td>${formatFen(campaign.actual_spend_minor)}</td><td>${campaign.contribution_after_spend_fen == null ? '—' : formatFen(campaign.contribution_after_spend_fen)}</td></tr>`).join('')}
    </tbody></table></div>
    <p class="analytics-note">${esc(state.campaigns[0].baseline_status === 'not_configured' ? '基线未配置：需要活动前的等价比较区间和口径，当前不显示增量贡献 / ROI。' : '')}</p>
  </section>`;
}

function qualityCard() {
  const quality = state.quality;
  if (!quality) return '';
  const missing = quality.coverage?.missing_dates || [];
  return `<section class="analytics-card analytics-quality">
    <div class="analytics-card-head"><div><h2>数据质量与口径</h2><p>数据版本 ${esc(quality.dataset_version)} · 导入于 ${esc(quality.imported_at?.slice(0, 19).replace('T', ' '))}</p></div>${chip(quality.data_kind === 'synthetic' ? '合成演示数据' : '用户数据', quality.data_kind === 'synthetic' ? 'warn' : 'ok')}</div>
    <div class="analytics-quality-grid">
      <div><strong>日期覆盖</strong><p>${esc(coverageLabel(quality.coverage))}${missing.length ? '：' + missing.slice(0, 8).map(esc).join('、') + (missing.length > 8 ? '…' : '') : ''}</p></div>
      <div><strong>缺成本商品</strong><p>${quality.missing_cost_skus.length ? quality.missing_cost_skus.map(productName).map(esc).join('、') : '无；贡献可按已匹配成本汇总'}</p></div>
      <div><strong>金额与订单口径</strong><p>金额为整数分；订单数按订单号去重；退款前交付杯数仍计入销量和成本。</p></div>
      <div><strong>未实现项</strong><p>第二杯参与两杯平均、活动基线/增量、收益敏感性曲线。</p></div>
    </div>
    <p class="analytics-note">${esc(quality.notes.join('；'))}</p>
  </section>`;
}

function content() {
  if (!state.loaded) {
    return `<section class="analytics-card analytics-setup"><h2>经营数据尚未导入</h2><p>看板使用订单级数据，和 Agent 的两期经营汇总分开保存。请先导入仓库内的合成演示数据：</p><pre>python backend/scripts/import_analytics.py</pre><p>导入后刷新本页。数据库是本地生成物，不提交 Git。</p></section>`;
  }
  return `${summaryCards()}
    <section class="analytics-card"><div class="analytics-card-head"><div><h2>收入与贡献趋势</h2><p>按日聚合；贡献在某商品缺成本时断开，不按 0 补齐。</p></div></div>${trendChart(state.points)}</section>
    <section class="analytics-card"><div class="analytics-card-head"><div><h2>交付杯数趋势</h2><p>有销量、零销量和数据缺失分开显示。</p></div></div>${cupsChart(state.points)}</section>
    ${productRanking()}${productDetail()}${campaignTable()}${qualityCard()}`;
}

function render() {
  if (!initialized) return;
  const host = $('analyticsContent');
  if (!host) return;
  if (state.loading) {
    host.innerHTML = '<section class="analytics-card analytics-loading">正在读取经营数据…</section>';
    return;
  }
  if (state.error) {
    host.innerHTML = `<section class="analytics-card analytics-error"><h2>读取失败</h2><p>${esc(state.error)}</p><button type="button" id="retryAnalytics">重试</button></section>`;
    $('retryAnalytics').onclick = () => loadConfig(true);
    return;
  }
  host.innerHTML = content();
  bindContent();
}

function bindContent() {
  document.querySelectorAll('[data-sort]').forEach(button => {
    button.onclick = () => {
      state.sort = button.dataset.sort;
      loadAll();
    };
  });
  document.querySelectorAll('[data-product]').forEach(row => {
    const open = () => loadProduct(row.dataset.product);
    row.onclick = open;
    row.onkeydown = event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        open();
      }
    };
  });
  const close = $('closeAnalyticsDetail');
  if (close) close.onclick = () => { state.detail = null; render(); };
}

function populateProducts() {
  const select = $('analyticsSku');
  if (!select) return;
  const options = (state.config?.products || []).map(product =>
    `<option value="${esc(product.product_id)}">${esc(product.name)}${product.spec ? ' · ' + esc(product.spec) : ''}</option>`).join('');
  select.innerHTML = '<option value="">全部商品</option>' + options;
  select.value = state.sku;
}

async function loadConfig(force = false) {
  if (state.loading) return;
  state.loading = true;
  state.error = '';
  render();
  try {
    const config = await request('/api/analytics/config');
    state.config = config;
    state.loaded = Boolean(config.loaded);
    if (state.loaded) {
      if (!state.start || force) state.start = config.default_start;
      if (!state.end || force) state.end = config.default_end;
      if (force) state.sku = '';
      populateProducts();
      $('analyticsStart').value = state.start;
      $('analyticsEnd').value = state.end;
      state.loading = false;
      await loadAll();
      return;
    }
  } catch (error) {
    state.error = error.message;
  }
  state.loading = false;
  render();
}

async function loadAll() {
  if (!state.loaded || state.loading) return;
  const token = ++state.request;
  state.loading = true;
  state.error = '';
  state.detail = null;
  render();
  try {
    const [summary, trend, products, campaigns, quality] = await Promise.all([
      request('/api/analytics/summary?' + query()),
      request('/api/analytics/trend?' + query()),
      request('/api/analytics/products?' + query(true)),
      request('/api/analytics/campaigns?' + query()),
      request('/api/analytics/quality?' + query()),
    ]);
    if (token !== state.request) return;
    state.summary = summary;
    state.points = trend.points || [];
    state.products = products.products || [];
    state.campaigns = campaigns.campaigns || [];
    state.quality = quality;
  } catch (error) {
    if (token === state.request) state.error = error.message;
  } finally {
    if (token === state.request) {
      state.loading = false;
      render();
    }
  }
}

async function loadProduct(productId) {
  state.detail = null;
  render();
  try {
    const detail = await request('/api/analytics/products/' + encodeURIComponent(productId) + '?' + query());
    state.detail = detail;
    render();
    $('analyticsDetail')?.scrollIntoView({behavior: 'smooth', block: 'start'});
  } catch (error) {
    state.error = error.message;
    render();
  }
}

function bindFilters() {
  $('analyticsFilters').onsubmit = event => {
    event.preventDefault();
    state.start = $('analyticsStart').value;
    state.end = $('analyticsEnd').value;
    state.sku = $('analyticsSku').value;
    state.detail = null;
    loadAll();
  };
  $('analyticsReset').onclick = () => {
    state.start = state.config.default_start;
    state.end = state.config.default_end;
    state.sku = '';
    $('analyticsStart').value = state.start;
    $('analyticsEnd').value = state.end;
    $('analyticsSku').value = '';
    state.detail = null;
    loadAll();
  };
  $('analyticsRefresh').onclick = () => loadConfig(true);
}

function init() {
  const host = $('analyticsRoot');
  if (!host) return;
  host.innerHTML = `<div class="analytics-shell">
    <header class="analytics-heading"><div><span class="analytics-eyebrow">经营分析 / 订单级数据</span><h1>经营看板</h1><p>净收入、交付杯数、订单、贡献与商品明细，按同一筛选口径计算。</p></div><span id="analyticsDatasetBadge" class="analytics-chip"></span></header>
    <form id="analyticsFilters" class="analytics-filters">
      <label>开始日期<input type="date" id="analyticsStart"></label>
      <label>结束日期<input type="date" id="analyticsEnd"></label>
      <label>商品<select id="analyticsSku"><option value="">全部商品</option></select></label>
      <button type="submit">应用筛选</button>
      <button type="button" id="analyticsReset">重置</button>
      <button type="button" id="analyticsRefresh">重新读取数据</button>
    </form>
    <div id="analyticsStatus" class="analytics-status" role="status"></div>
    <div id="analyticsContent"></div>
  </div>`;
  initialized = true;
  bindFilters();
}

async function refreshSharedBadge() {
  const badge = $('analyticsDatasetBadge');
  if (!badge) return;
  if (!state.config) {
    badge.textContent = '正在读取…';
    return;
  }
  badge.textContent = state.loaded ? `合成数据 · ${state.config.dataset_version}` : '尚未导入数据';
  badge.className = 'analytics-chip ' + (state.loaded ? 'warn' : '');
}

export async function showAnalytics() {
  if (!initialized) init();
  await refreshSharedBadge();
  if (!state.config) {
    await loadConfig();
    await refreshSharedBadge();
    return;
  }
  if (!state.loaded) {
    render();
    return;
  }
  // Re-read on each entry; the import may have been refreshed while browsing.
  if (!state.summary) await loadAll();
  else render();
}
