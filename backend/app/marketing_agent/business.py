"""Synthetic fixtures + real arithmetic. No demand prediction or causal attribution."""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import json
from uuid import uuid4
from .contracts import (Brief, Offer, SalesRequest, ConstraintsRequest, EvaluationRequest,
                        WebSearchRequest, ToolResult, validate_tool)
from .. import config

PRODUCTS = {
    'T001': {'name': '茉莉鲜奶茶', 'spec': '标准杯', 'price': 1600, 'ingredient': 450, 'packaging': 100, 'other': 50, 'selling': ['茉莉茶香', '鲜奶茶饮']},
    'T002': {'name': '乌龙鲜奶茶', 'spec': '标准杯', 'price': 1800, 'ingredient': 500, 'packaging': 100, 'other': 50, 'selling': ['乌龙茶香', '鲜奶茶饮']},
    'T003': {'name': '红茶鲜奶茶', 'spec': '大杯', 'price': 2000, 'ingredient': 550, 'packaging': 120, 'other': 80, 'selling': ['红茶茶香', '鲜奶茶饮']},
}
DATA_VERSION = 'milk-tea-demo-v1'
METHOD_VERSION = 'promotion-v2-explicit-pairs'


def catalog(brief):
    if not brief.get('brand_id'):
        return PRODUCTS
    from .data import snapshot
    return snapshot(brief['brand_id'])['products']


def source_version(brief):
    if not brief.get('brand_id'):
        return DATA_VERSION
    from .data import snapshot
    return snapshot(brief['brand_id'])['version']


def source_envelope(brand_id, tool, result, missing=None):
    from .data import snapshot
    snap = snapshot(brand_id)
    value = envelope(tool, result, missing,
                     ['用户提供的单门店自提资料；销量为净完成杯数，日期含开始不含结束。',
                      '历史平均销量仅作不促销情景参考，不是因果基线或需求预测。'],
                     ['数据由用户确认，未与收银系统自动核验；不得根据排名推断滞销原因。'])
    value.update(data_kind='user_provided', data_version=snap['version'],
                 source_refs=[f'brand:{brand_id}', f'business:{snap["business_version"] or "missing"}'])
    rows = (snap.get('business') or {}).get('rows', [])
    value['as_of'] = (date.fromisoformat(rows[0]['current_end'])-timedelta(days=1)).isoformat() if rows else ''
    value['snapshot_id'] = fingerprint(value['result'] | {'version': snap['version']})
    return validate_tool(value)


def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def records():
    """28 complete synthetic days, order lines preserve pair grouping and quantities."""
    for day in range(28):
        stamp = (date(2026, 10, 19) + timedelta(days=day)).isoformat()
        for sku, product in PRODUCTS.items():
            count = {'T001': 10 if day < 14 else 7, 'T002': 8, 'T003': 5 if day < 14 else 6}[sku]
            for order in range(count):
                yield {'order_id': f'{stamp}-{sku}-{order}', 'line_id': f'{stamp}-{sku}-{order}-1',
                       'date': stamp, 'store_id': 'demo-store', 'sku_id': sku, 'fulfilled_qty': 2,
                       'list_amount_minor': product['price'] * 2, 'customer_paid_minor': product['price'] * 2,
                       'merchant_discount_minor': 0, 'platform_subsidy_minor': 0, 'refund_minor': 0,
                       'channel_fee_minor': 0, 'sales_channel': 'pickup', 'status': 'completed',
                       'campaign_id': None, 'data_kind': 'synthetic'}


def envelope(tool, result, missing=None, assumptions=None, warnings=None):
    value = ToolResult(request_id=uuid4().hex, tool=tool, status='needs_data' if missing else 'ok',
                       snapshot_id=fingerprint({'tool': tool, 'result': result, 'missing': missing,
                                                'data': DATA_VERSION, 'method': METHOD_VERSION}),
                       data_version=DATA_VERSION, method_version=METHOD_VERSION, result=result,
                       missing_fields=missing or [], assumptions=assumptions or [],
                       warnings=warnings or [], source_refs=['synthetic:milk-tea-demo-v1'])
    return validate_tool(value.model_dump(mode='json'))


def get_sales_summary(request: SalesRequest):
    if request.brand_id:
        # Prefer confirmed order-level operating facts. The dashboard uses the same
        # calculator, while the legacy aggregate CSV remains a compatible fallback.
        from .. import operations
        order_summary = operations.sales_summary_for_agent(request.brand_id, request.sku_id)
        if order_summary is not None:
            provenance = operations.orders_provenance(request.brand_id)
            result = envelope('get_sales_summary', order_summary,
                              assumptions=['订单级经营数据按日期左闭右开聚合。'],
                              warnings=['销量与贡献变化是描述性比较，不构成严格因果归因。'])
            result.update(data_kind=provenance['data_kind'], data_version=provenance['data_version'],
                          source_refs=provenance['source_refs'])
            return validate_tool(result)
        from .data import snapshot, business_row
        snap = snapshot(request.brand_id)
        metrics, missing = [], []
        period = None
        for sku in ([request.sku_id] if request.sku_id else snap['products']):
            if sku not in snap['products']:
                raise ValueError('商品不属于当前品牌。')
            r = business_row(snap, sku)
            before, after = r.get('previous_qty'), r.get('current_qty')
            if before is None or after is None:
                missing.append({'path': 'sales:'+sku, 'reason': snap['products'][sku]['name']+'缺少两期销量', 'blocks': ['sales_comparison']})
            if r:
                period = r
            days = (date.fromisoformat(r['current_end'])-date.fromisoformat(r['current_start'])).days if r else 1
            metrics.append({'sku_id': sku, 'name': snap['products'][sku]['name'], 'previous_qty': before, 'current_qty': after,
                            'change_ratio': (after-before)/before if before and after is not None else None,
                            'current_revenue_minor': None, 'daily_baseline_qty': after/days if after is not None else None})
        return source_envelope(request.brand_id, 'get_sales_summary', {
            'previous_period': [period['previous_start'], period['previous_end']] if period else [],
            'current_period': [period['current_start'], period['current_end']] if period else [], 'metrics': metrics}, missing)
    rows = list(records())
    metrics = []
    for sku in ([request.sku_id] if request.sku_id else PRODUCTS):
        previous = [r for r in rows if r['sku_id'] == sku and r['date'] < '2026-11-02']
        current = [r for r in rows if r['sku_id'] == sku and r['date'] >= '2026-11-02']
        before = sum(r['fulfilled_qty'] for r in previous)
        after = sum(r['fulfilled_qty'] for r in current)
        metrics.append({'sku_id': sku, 'name': PRODUCTS[sku]['name'], 'previous_qty': before,
                        'current_qty': after, 'change_ratio': (after-before)/before if before else None,
                        'current_revenue_minor': sum(r['customer_paid_minor'] for r in current),
                        'daily_baseline_qty': after/14})
    return envelope('get_sales_summary', {'previous_period': ['2026-10-19', '2026-11-02'],
                    'current_period': ['2026-11-02', '2026-11-16'], 'metrics': metrics},
                    warnings=['数据为固定模拟样本；销量变化不能证明原因，也不代表未来需求。'])


def get_business_constraints(request: ConstraintsRequest):
    if request.brand_id:
        from .data import snapshot, business_row
        snap = snapshot(request.brand_id)
        if request.sku_id not in snap['products']:
            raise ValueError('商品不属于当前品牌。')
        r = business_row(snap, request.sku_id)
        result = {'sku_id': request.sku_id, 'list_price_minor': snap['products'][request.sku_id]['price'],
                  'variable_cost_minor': r.get('variable_cost_minor'), 'min_contribution_minor': r.get('min_contribution_minor'),
                  'daily_capacity': r.get('daily_capacity'), 'fee_bps': 0, 'currency': 'CNY'}
        missing = [{'path': k, 'reason': label+'尚未提供', 'blocks': ['unit_economics']}
                   for k, label in [('list_price_minor','明确的商品原价'),('variable_cost_minor','单杯变动成本'),('min_contribution_minor','最低每杯贡献要求')]
                   if result[k] is None]
        return source_envelope(request.brand_id, 'get_business_constraints', result, missing)
    p = PRODUCTS[request.sku_id]
    return envelope('get_business_constraints', {'sku_id': request.sku_id, 'list_price_minor': p['price'],
                    'variable_cost_minor': p['ingredient']+p['packaging']+p['other'],
                    'min_contribution_minor': 500, 'daily_capacity': 200, 'fee_bps': 0, 'currency': 'CNY'},
                    assumptions=['模拟门店自提，渠道费为零；贡献收益不含房租与固定工资。'])


def paid_price(price, bps):
    return int((Decimal(price)*Decimal(bps)/10000).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def order_revenue(price, quantity, offer):
    if offer.type == 'none':
        return price * quantity
    discounted = paid_price(price, offer.pay_bps)
    if offer.type == 'percentage':
        return discounted * quantity
    return (quantity//2) * (price+discounted) + (quantity % 2) * price


def scenario_revenue(price, quantity, offer, pairs):
    if offer.type!='second_cup_discount':return order_revenue(price,quantity,offer)
    if pairs is None or not 0<=2*pairs<=quantity:
        raise ValueError('第二杯优惠需要有效的参与组数，不按总杯数自动配对。')
    return (quantity-pairs)*price+pairs*paid_price(price,offer.pay_bps)


def evaluate_promotion(request: EvaluationRequest):
    b = request.brief
    missing = []
    for field in ('sku_id', 'offer'):
        if getattr(b, field) is None:
            missing.append({'path': field, 'reason': '优惠测算需要此字段', 'blocks': ['unit_economics', 'roi']})
    if missing:
        return (source_envelope(b.brand_id, 'evaluate_promotion', {'feasible': None, 'violations': []}, missing)
                if b.brand_id else envelope('evaluate_promotion', {'feasible': None, 'violations': []}, missing))
    limits = get_business_constraints(ConstraintsRequest(sku_id=b.sku_id, brand_id=b.brand_id))['result']
    wrap = (lambda result, missing=None, assumptions=None, warnings=None: source_envelope(b.brand_id, 'evaluate_promotion', result, missing)) if b.brand_id else (lambda result, missing=None, assumptions=None, warnings=None: envelope('evaluate_promotion', result, missing, assumptions, warnings))
    cost = b.variable_cost_override_minor if b.variable_cost_override_minor is not None else limits['variable_cost_minor']
    minimum = b.min_contribution_override_minor if b.min_contribution_override_minor is not None else limits['min_contribution_minor']
    if not b.assess_minimum:minimum=None
    limits['min_contribution_minor'] = minimum
    price = limits['list_price_minor']
    for field, value, label in [('list_price_minor', price, '请在品牌商品中补充明确的单价'),
                                ('variable_cost_override_minor', cost, '这款商品单杯变动成本是多少元？请包含食材和包材'),
                                ('min_contribution_override_minor', minimum, '每杯扣除变动成本后，至少希望保留多少元？')]:
        if value is None and not (field=='min_contribution_override_minor' and not b.assess_minimum):
            missing.append({'path': field, 'reason': label, 'blocks': ['unit_economics']})
    if missing:
        return wrap({'feasible': None, 'violations': []}, missing)
    pair_revenue = order_revenue(price, 2, b.offer)
    pair_contribution = pair_revenue - 2*cost
    violations = []
    if minimum is not None and pair_contribution < 2*minimum:
        violations.append(f'平均每杯贡献收益低于 {minimum/100:g} 元的门店约束。')
    if b.spend_minor is not None and b.budget_minor is not None and b.spend_minor > b.budget_minor:
        violations.append('预计支出超过预算上限。')
    result = {'feasible': (not violations if minimum is not None else None), 'violations': violations, 'pair_revenue_minor': pair_revenue,
              'pair_variable_cost_minor': 2*cost, 'pair_contribution_minor': pair_contribution, 'average_contribution_minor': pair_contribution/2,
              'min_average_price_minor': cost+minimum if minimum is not None else None,
              'roi_reason': 'UNIT_ONLY' if b.roi_mode == 'unit_only' else None}
    # Binary-search integer basis points using the same cent-rounding as actual quotes.
    if minimum is not None and b.offer.type != 'none' and price-cost >= minimum:
        low, high = 0, 10000
        while low < high:
            middle = (low+high)//2
            offer = Offer(type=b.offer.type, pay_bps=middle)
            if order_revenue(price, 2, offer)-2*cost >= 2*limits['min_contribution_minor']:
                high = middle
            else:
                low = middle+1
        result['min_offer_pay_bps'] = low
    assumptions = ['模拟经营数据，不代表真实品牌。', '单位优惠示例按同单同款两杯；活动总量按用户指定优惠组数，剩余杯数原价，不叠加优惠。',
                   '贡献收益扣除食材、包材等变动成本，不含房租与固定工资，不是净利润。',
                   '金额按分四舍五入；优惠已计入收入，不重复记作营销成本。',
                   '基线使用所选本期日均销量，假设活动期间原价销售；不代表因果归因或需求预测。']
    if b.variable_cost_override_minor is not None:
        assumptions.append('单杯成本使用本次用户提供值，不更新产品主数据。')
    if b.roi_mode == 'scenario':
        if b.offer.type=='second_cup_discount' and b.promotion_pairs is None:
            missing.append({'path':'promotion_pairs','reason':'预计多少组同单两杯参加优惠？不知道时可以只看单位收益。','blocks':['roi']})
        for field in ('start_date', 'end_date', 'scenario_qty', 'spend_minor'):
            if getattr(b, field) is None:
                missing.append({'path': field, 'reason': 'ROI 情景需要此字段；也可选择只判断单位收益', 'blocks': ['roi']})
        if not missing:
            days = (b.end_date-b.start_date).days
            quantity = b.scenario_qty
            if limits['daily_capacity'] is not None and quantity > limits['daily_capacity']*days:
                violations.append('预计销量超过当前门店产能上限。')
                result['feasible'] = False
            baseline_daily = get_sales_summary(SalesRequest(sku_id=b.sku_id, brand_id=b.brand_id))['result']['metrics'][0]['daily_baseline_qty']
            baseline_qty = round(baseline_daily*days) if baseline_daily is not None else None
            revenue = scenario_revenue(price, quantity, b.offer,b.promotion_pairs)
            contribution = revenue - quantity*cost
            baseline_contribution = baseline_qty*(price-cost) if baseline_qty is not None else None
            incremental = contribution - baseline_contribution - b.spend_minor if baseline_contribution is not None else None
            result.update(scenario_qty=quantity, scenario_revenue_minor=revenue,
                          scenario_contribution_minor=contribution, baseline_qty=baseline_qty,
                          baseline_contribution_minor=baseline_contribution,
                          incremental_contribution_minor=incremental,
                          incremental_roi=incremental/b.spend_minor if b.spend_minor and incremental is not None else None,
                          roi_reason='MISSING_BASELINE' if baseline_qty is None else None if b.spend_minor else 'ZERO_SPEND')
    candidates = []
    if b.offer.type != 'none' and minimum is not None:
        for bps in (5000, 7000, 8000, 10000):
            offer = Offer(type=b.offer.type, pay_bps=bps)
            average = (order_revenue(price, 2, offer)-2*cost)/2
            candidate = {'pay_bps': bps, 'feasible': average >= limits['min_contribution_minor'],
                         'average_contribution_minor': average}
            if result.get('baseline_contribution_minor') is not None:
                candidate['incremental_contribution_minor'] = (scenario_revenue(price, b.scenario_qty, offer,b.promotion_pairs)
                    - b.scenario_qty*cost - result['baseline_contribution_minor'] - b.spend_minor)
                candidate['feasible'] = candidate['feasible'] and (limits['daily_capacity'] is None or b.scenario_qty <= limits['daily_capacity']*(b.end_date-b.start_date).days)
            if b.spend_minor is not None and b.budget_minor is not None:
                candidate['feasible'] = candidate['feasible'] and b.spend_minor <= b.budget_minor
            candidates.append(candidate)
        result['candidates'] = candidates
        assumptions.append('候选折扣沿用同一销量假设，仅用于收益敏感性比较，不能据此认定最优价格。')
    answer = wrap(result, missing, assumptions,
                    ['单位收益合格不代表活动比不促销更划算。'])
    if b.brand_id:
        answer['assumptions'] += [a for a in assumptions if '模拟' not in a]
        if limits['daily_capacity'] is None:
            answer['warnings'].append('尚未提供产能上限，未校验履约能力。')
    return answer


def web_search(request):
    """Agent 自主联网搜索：需要外部实时信息（竞品、节气热点、平台规则）时由模型决定调用。

    默认 mock 返回确定性结果，避免演示时产生外部网络依赖；配置 TAVILY_API_KEY 后走真实搜索。
    与其它经营工具一致，返回 ToolResult 统一信封，供模型在下一轮决策中继续选择工具或给出答复。
    """
    q = WebSearchRequest.model_validate(request) if isinstance(request, dict) else request
    provider = 'tavily' if config.TAVILY_API_KEY else 'mock'
    if provider == 'tavily':
        return _tavily_search(q.query)
    # 确定性 mock：不编造"实时"事实，明确标注为演示样例，供模型演示"自主调用搜索"的决策链路。
    result = {
        'query': q.query,
        'results': [
            {'title': '（演示样例）搜索能力占位结果', 'url': 'https://example.com/search-demo',
             'snippet': '当前为离线演示模式，联网搜索未接入真实数据源。配置 TAVILY_API_KEY 后返回真实搜索结果。'},
        ],
        'provider': 'mock',
    }
    return envelope('web_search', result,
                    assumptions=['演示模式返回占位结果，不代表真实检索内容。'],
                    warnings=['联网搜索需在部署环境配置搜索服务密钥，否则仅返回占位样例。'])


def _tavily_search(query):
    import urllib.request
    from ..config import TAVILY_API_KEY
    body = json.dumps({'query': query, 'max_results': 5, 'include_answer': False}).encode()
    req = urllib.request.Request('https://api.tavily.com/search', data=body,
                                 headers={'Content-Type': 'application/json',
                                          'Authorization': 'Bearer ' + TAVILY_API_KEY})
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.load(resp)
    results = [{'title': r.get('title', ''), 'url': r.get('url', ''),
                'snippet': r.get('content', '')[:500]} for r in payload.get('results', [])]
    return envelope('web_search', {'query': query, 'results': results, 'provider': 'tavily'},
                    assumptions=['搜索结果来自外部公开来源，仅作参考，不代表事实核验。'],
                    warnings=['联网信息可能过时或有偏，引用前应二次确认。'])


TOOL_NAMES = ('get_sales_summary', 'get_business_constraints', 'evaluate_promotion', 'web_search')


def call_tool(name, brief, query=''):
    b = Brief.model_validate(brief)
    if name == 'get_sales_summary':
        return get_sales_summary(SalesRequest(sku_id=b.sku_id, brand_id=b.brand_id))
    if name == 'get_business_constraints':
        return get_business_constraints(ConstraintsRequest(sku_id=b.sku_id, brand_id=b.brand_id))
    if name == 'evaluate_promotion':
        return evaluate_promotion(EvaluationRequest(brief=b))
    if name == 'web_search':
        return web_search(WebSearchRequest(brand_id=b.brand_id, query=query))
    raise ValueError('不允许调用该工具。')
