"""Read-only operating dashboard facts and aggregation.

The dashboard uses order-level facts (orders + costs + products). This is
deliberately separate from ``marketing_agent.data.BusinessRow``: BusinessRow is
a two-period summary used by the Agent, while this module keeps daily/order facts
for trend and campaign review.

Money is always integer CNY fen. ``start``/``end`` query parameters are inclusive
dates. Source CSV amounts are yuan and are converted once at import time.
"""
from __future__ import annotations

import csv
import json
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import create_engine, text

from . import knowledge as kb
from .config import DATA_DIR
from .v2 import require_access

ANALYTICS_DATABASE_URL = os.getenv('ANALYTICS_DATABASE_URL') or (
    f"sqlite:///{(DATA_DIR / 'analytics.db').as_posix()}"
)
engine = create_engine(
    ANALYTICS_DATABASE_URL,
    connect_args={'check_same_thread': False} if ANALYTICS_DATABASE_URL.startswith('sqlite:') else {},
    pool_pre_ping=True,
)

router = APIRouter(
    prefix='/api/analytics',
    tags=['operating analytics'],
    dependencies=[Depends(require_access), Depends(kb.get_workspace)],
)

MAX_RANGE_DAYS = 366


def init_db():
    with engine.begin() as c:
        for statement in [
            '''CREATE TABLE IF NOT EXISTS analytics_meta (
                id INTEGER PRIMARY KEY,
                dataset_version TEXT NOT NULL,
                brand TEXT NOT NULL,
                history_start TEXT NOT NULL,
                history_end TEXT NOT NULL,
                feedback_start TEXT NOT NULL,
                feedback_end TEXT NOT NULL,
                min_contribution_minor INTEGER,
                launch_dates TEXT NOT NULL,
                source_dir TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                data_kind TEXT NOT NULL
            )''',
            '''CREATE TABLE IF NOT EXISTS analytics_products (
                product_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                spec TEXT NOT NULL DEFAULT '',
                current_price_minor INTEGER,
                selling TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT ''
            )''',
            '''CREATE TABLE IF NOT EXISTS analytics_orders (
                order_id TEXT NOT NULL,
                order_date TEXT NOT NULL,
                product_id TEXT NOT NULL,
                qty INTEGER NOT NULL,
                unit_price_minor INTEGER NOT NULL,
                discount_minor INTEGER NOT NULL DEFAULT 0,
                refund_minor INTEGER NOT NULL DEFAULT 0,
                campaign_id TEXT NOT NULL DEFAULT '',
                stage TEXT NOT NULL,
                PRIMARY KEY (order_id, product_id)
            )''',
            '''CREATE TABLE IF NOT EXISTS analytics_costs (
                product_id TEXT NOT NULL,
                effective_date TEXT NOT NULL,
                raw_cost_minor INTEGER NOT NULL,
                packaging_cost_minor INTEGER NOT NULL,
                other_cost_minor INTEGER NOT NULL,
                unit_cost_minor INTEGER NOT NULL,
                PRIMARY KEY (product_id, effective_date)
            )''',
            '''CREATE TABLE IF NOT EXISTS analytics_campaigns (
                campaign_id TEXT PRIMARY KEY,
                sku TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                rule TEXT NOT NULL,
                discount_per_cup_minor INTEGER,
                second_cup_discount_minor INTEGER,
                planned_spend_minor INTEGER,
                actual_spend_minor INTEGER,
                basis TEXT NOT NULL DEFAULT ''
            )''',
            'CREATE INDEX IF NOT EXISTS analytics_orders_date ON analytics_orders(order_date)',
            'CREATE INDEX IF NOT EXISTS analytics_orders_product_date ON analytics_orders(product_id, order_date)',
            'CREATE INDEX IF NOT EXISTS analytics_costs_product_date ON analytics_costs(product_id, effective_date)',
        ]:
            c.execute(text(statement))


def startup():
    source = os.getenv('ANALYTICS_DATASET_DIR', '').strip()
    if os.getenv('ANALYTICS_AUTO_IMPORT', '').lower() == 'true' and source:
        try:
            init_db()
            if not loaded():
                import_dataset(source)
        except Exception:
            # A broken optional demo import must not prevent the main app from starting.
            import logging
            logging.getLogger(__name__).exception('经营看板数据自动导入失败：%s', source)


def loaded() -> bool:
    init_db()
    with engine.connect() as c:
        return c.execute(text('SELECT COUNT(*) FROM analytics_meta')).scalar_one() > 0


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


def _read_csv(path: Path) -> tuple[list[dict[str, str]], set[str]]:
    if not path.is_file():
        raise ValueError(f'缺少文件：{path.name}')
    with path.open('r', encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        headers = set(reader.fieldnames or [])
        if not headers:
            raise ValueError(f'{path.name} 没有表头。')
        return ([{key: (value or '').strip() for key, value in row.items() if key}
                 for row in reader], headers)


def _require_headers(headers: set[str], required: Iterable[str], filename: str):
    missing = [name for name in required if name not in headers]
    if missing:
        raise ValueError(f'{filename} 缺少字段：'+'、'.join(missing))


def _int_fen(value: Any, label: str, *, allow_blank: bool = False) -> int | None:
    """Read a value that is already expressed in integer fen (JSON metadata)."""
    raw = '' if value is None else str(value).strip()
    if not raw:
        if allow_blank:
            return None
        raise ValueError(f'{label}不能为空')
    try:
        number = int(Decimal(raw))
    except (InvalidOperation, ValueError):
        raise ValueError(f'{label}必须为整数分：{raw}') from None
    if number < 0:
        raise ValueError(f'{label}必须为非负整数分：{raw}')
    return number


def _cell(row: dict[str, str], name: str) -> str:
    return (row.get(name) or '').strip()


def _fen(value: Any, label: str, *, allow_blank: bool = False, blank: int = 0) -> int:
    raw = '' if value is None else str(value).strip()
    if not raw:
        if allow_blank:
            return blank
        raise ValueError(f'{label}不能为空')
    try:
        value_decimal = Decimal(raw)
    except (InvalidOperation, ValueError):
        raise ValueError(f'{label}不是有效金额：{raw}') from None
    if not value_decimal.is_finite() or value_decimal < 0:
        raise ValueError(f'{label}必须为非负金额：{raw}')
    return int((value_decimal * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def _date(value: Any, label: str) -> date:
    raw = '' if value is None else str(value).strip()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ValueError(f'{label}不是有效日期：{raw}') from None


def _period(value: Any, label: str) -> tuple[date, date]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f'{label}必须是 [开始日期, 结束日期]')
    start, end = _date(value[0], label+'开始日期'), _date(value[1], label+'结束日期')
    if start > end:
        raise ValueError(f'{label}开始日期不能晚于结束日期')
    return start, end


def _historical_period(rows: list[dict[str, str]]) -> tuple[date, date] | None:
    dates = sorted(_date(row['订单日期'], '订单日期') for row in rows if _cell(row, '订单号'))
    if not dates:
        return None
    return dates[0], dates[-1]


def _read_campaigns(source: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = source / 'demo_context.json'
    if not path.is_file():
        return {}, []
    try:
        context = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f'demo_context.json 读取失败：{exc}') from None
    campaigns = []
    for item in context.get('campaigns') or []:
        if not isinstance(item, dict) or not item.get('campaign_id') or not item.get('sku'):
            raise ValueError('活动元数据缺少 campaign_id 或 sku')
        start, end = _period(item.get('period'), item['campaign_id'])
        campaigns.append({
            'campaign_id': str(item['campaign_id']),
            'sku': str(item['sku']),
            'start_date': start.isoformat(),
            'end_date': end.isoformat(),
            'rule': str(item.get('rule') or ''),
            'discount_per_cup_minor': _int_fen(item.get('discount_per_cup_fen'), '每杯优惠', allow_blank=True),
            'second_cup_discount_minor': _int_fen(item.get('second_cup_discount_fen'), '第二杯优惠', allow_blank=True),
            'planned_spend_minor': _int_fen(item.get('planned_marketing_spend_fen'), '计划宣传费', allow_blank=True),
            'actual_spend_minor': _int_fen(item.get('actual_marketing_spend_fen'), '实际宣传费', allow_blank=True),
            'basis': str(item.get('basis') or ''),
        })
    return context, campaigns


def _load_products(source: Path) -> dict[str, dict[str, Any]]:
    rows, headers = _read_csv(source / 'products.csv')
    _require_headers(headers, ('商品编号', '商品名称', '规格', '当前售价', '卖点', '分类'), 'products.csv')
    products: dict[str, dict[str, Any]] = {}
    for row in rows:
        product_id = _cell(row, '商品编号')
        if not product_id:
            raise ValueError('products.csv 存在空商品编号')
        if product_id in products:
            raise ValueError(f'products.csv 商品编号重复：{product_id}')
        current_price = _cell(row, '当前售价')
        products[product_id] = {
            'product_id': product_id,
            'name': _cell(row, '商品名称') or product_id,
            'spec': _cell(row, '规格'),
            'current_price_minor': _fen(current_price, '当前售价') if current_price else None,
            'selling': _cell(row, '卖点'),
            'category': _cell(row, '分类'),
        }
    if not products:
        raise ValueError('products.csv 没有商品')
    return products


def _load_costs(source: Path, products: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows, headers = _read_csv(source / 'costs.csv')
    _require_headers(headers, ('商品编号', '成本生效日期', '每杯原料成本', '每杯包材成本', '每杯其他变动成本'), 'costs.csv')
    costs = []
    seen = set()
    for row in rows:
        product_id = _cell(row, '商品编号')
        if product_id not in products:
            raise ValueError(f'costs.csv 商品不存在：{product_id}')
        effective = _date(_cell(row, '成本生效日期'), '成本生效日期').isoformat()
        key = (product_id, effective)
        if key in seen:
            raise ValueError(f'costs.csv 存在重复生效日期：{product_id} {effective}')
        seen.add(key)
        raw = _fen(_cell(row, '每杯原料成本'), '每杯原料成本')
        packaging = _fen(_cell(row, '每杯包材成本'), '每杯包材成本')
        other = _fen(_cell(row, '每杯其他变动成本'), '每杯其他变动成本')
        costs.append({'product_id': product_id, 'effective_date': effective, 'raw_cost_minor': raw,
                      'packaging_cost_minor': packaging, 'other_cost_minor': other,
                      'unit_cost_minor': raw + packaging + other})
    return costs


def _load_orders(path: Path, stage: str, products: dict[str, dict[str, Any]],
                 seen: set[tuple[str, str]]) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows, headers = _read_csv(path)
    _require_headers(headers, ('订单号', '订单日期', '商品编号', '商品数量', '当时单杯原价', '优惠总额', '退款总额', '活动编号'), path.name)
    orders = []
    for row in rows:
        order_id, product_id = _cell(row, '订单号'), _cell(row, '商品编号')
        if not order_id or not product_id:
            raise ValueError(f'{path.name} 存在空订单号或商品编号')
        if product_id not in products:
            raise ValueError(f'{path.name} 商品不存在：{product_id}')
        qty = _cell(row, '商品数量')
        try:
            qty_value = int(qty)
        except ValueError:
            raise ValueError(f'{path.name} 商品数量不是整数：{qty}') from None
        if qty_value <= 0:
            raise ValueError(f'{path.name} 商品数量必须大于 0：{qty}')
        key = (order_id, product_id)
        if key in seen:
            raise ValueError(f'{path.name} 订单行重复：{order_id} / {product_id}')
        seen.add(key)
        orders.append({
            'order_id': order_id,
            'order_date': _date(_cell(row, '订单日期'), '订单日期').isoformat(),
            'product_id': product_id,
            'qty': qty_value,
            'unit_price_minor': _fen(_cell(row, '当时单杯原价'), '当时单杯原价'),
            'discount_minor': _fen(_cell(row, '优惠总额'), '优惠总额', allow_blank=True, blank=0),
            'refund_minor': _fen(_cell(row, '退款总额'), '退款总额', allow_blank=True, blank=0),
            'campaign_id': _cell(row, '活动编号'),
            'stage': stage,
        })
    return orders


def import_dataset(source_dir: str | Path) -> dict[str, Any]:
    """Import one products/orders/costs bundle. Re-import replaces the snapshot."""
    source = Path(source_dir).expanduser().resolve()
    if not source.is_dir():
        raise ValueError(f'数据集目录不存在：{source}')
    context, campaigns = _read_campaigns(source)
    products = _load_products(source)
    costs = _load_costs(source, products)
    seen: set[tuple[str, str]] = set()
    history = _load_orders(source / 'orders.csv', 'history', products, seen)
    feedback = _load_orders(source / 'campaign_feedback' / 'orders.csv', 'feedback', products, seen)
    if not history and not feedback:
        raise ValueError('orders.csv 没有订单')

    history_period = _period(context.get('history_period'), 'history_period') if context.get('history_period') else _historical_period(history)
    feedback_period = _period(context.get('feedback_period'), 'feedback_period') if context.get('feedback_period') else _historical_period(feedback)
    if history_period is None:
        raise ValueError('缺少历史订单日期范围')
    if feedback_period is None:
        feedback_period = history_period
    launch_dates = context.get('new_item_launch_on') if isinstance(context.get('new_item_launch_on'), dict) else {}
    launch_dates = {str(key): _date(value, '新品上架日期').isoformat() for key, value in launch_dates.items() if key in products}
    source_kind = str(context.get('source') or context.get('source_note') or '')
    data_kind = 'synthetic' if '合成' in source_kind or 'synthetic' in source_kind.lower() else 'user_provided'

    init_db()
    imported_at = datetime.now(timezone.utc).isoformat()
    with engine.begin() as c:
        for table in ('analytics_meta', 'analytics_products', 'analytics_orders', 'analytics_costs', 'analytics_campaigns'):
            c.execute(text(f'DELETE FROM {table}'))
        c.execute(text('''INSERT INTO analytics_meta
            (id,dataset_version,brand,history_start,history_end,feedback_start,feedback_end,min_contribution_minor,launch_dates,source_dir,imported_at,data_kind)
            VALUES (1,:version,:brand,:hs,:he,:fs,:fe,:minimum,:launch,:source,:imported,:kind)'''), {
            'version': str(context.get('dataset_version') or source.name),
            'brand': str(context.get('brand') or '经营数据'),
            'hs': history_period[0].isoformat(), 'he': history_period[1].isoformat(),
            'fs': feedback_period[0].isoformat(), 'fe': feedback_period[1].isoformat(),
            'minimum': _int_fen(context.get('minimum_unit_contribution_fen'), '最低单杯贡献', allow_blank=True) if context.get('minimum_unit_contribution_fen') is not None else None,
            'launch': json.dumps(launch_dates, ensure_ascii=False),
            'source': str(source), 'imported': imported_at, 'kind': data_kind,
        })
        for product in products.values():
            c.execute(text('''INSERT INTO analytics_products
                (product_id,name,spec,current_price_minor,selling,category)
                VALUES (:product_id,:name,:spec,:current_price_minor,:selling,:category)'''), product)
        for cost in costs:
            c.execute(text('''INSERT INTO analytics_costs
                (product_id,effective_date,raw_cost_minor,packaging_cost_minor,other_cost_minor,unit_cost_minor)
                VALUES (:product_id,:effective_date,:raw_cost_minor,:packaging_cost_minor,:other_cost_minor,:unit_cost_minor)'''), cost)
        for campaign in campaigns:
            c.execute(text('''INSERT INTO analytics_campaigns
                (campaign_id,sku,start_date,end_date,rule,discount_per_cup_minor,second_cup_discount_minor,planned_spend_minor,actual_spend_minor,basis)
                VALUES (:campaign_id,:sku,:start_date,:end_date,:rule,:discount_per_cup_minor,:second_cup_discount_minor,:planned_spend_minor,:actual_spend_minor,:basis)'''), campaign)
        for order in history + feedback:
            c.execute(text('''INSERT INTO analytics_orders
                (order_id,order_date,product_id,qty,unit_price_minor,discount_minor,refund_minor,campaign_id,stage)
                VALUES (:order_id,:order_date,:product_id,:qty,:unit_price_minor,:discount_minor,:refund_minor,:campaign_id,:stage)'''), order)
    return {
        'dataset_version': str(context.get('dataset_version') or source.name),
        'brand': str(context.get('brand') or '经营数据'),
        'data_kind': data_kind,
        'history_period': [history_period[0].isoformat(), history_period[1].isoformat()],
        'feedback_period': [feedback_period[0].isoformat(), feedback_period[1].isoformat()],
        'products': len(products), 'costs': len(costs), 'campaigns': len(campaigns),
        'history_orders': len(history), 'feedback_orders': len(feedback),
        'imported_at': imported_at,
    }


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def _meta() -> dict[str, Any] | None:
    init_db()
    with engine.connect() as c:
        row = c.execute(text('SELECT * FROM analytics_meta WHERE id=1')).mappings().first()
    return dict(row) if row else None


def _require_meta() -> dict[str, Any]:
    meta = _meta()
    if not meta:
        raise HTTPException(503, '经营数据尚未导入。请先运行 python backend/scripts/import_analytics.py。')
    return meta


def _parse_date(value: str | None, fallback: date, label: str) -> date:
    if not value:
        return fallback
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(422, f'{label}必须为 YYYY-MM-DD。') from None


def _range(meta: dict[str, Any], start: str | None, end: str | None) -> tuple[date, date]:
    default_start = date.fromisoformat(meta['history_start'])
    default_end = date.fromisoformat(meta['feedback_end'] or meta['history_end'])
    start_date = _parse_date(start, default_start, '开始日期')
    end_date = _parse_date(end, default_end, '结束日期')
    if start_date > end_date:
        raise HTTPException(422, '开始日期不能晚于结束日期。')
    if (end_date - start_date).days + 1 > MAX_RANGE_DAYS:
        raise HTTPException(422, f'单次查询最多 {MAX_RANGE_DAYS} 天。')
    return start_date, end_date


def _dataset_period_dates(meta: dict[str, Any]) -> list[date]:
    periods = []
    for start_key, end_key in (('history_start', 'history_end'), ('feedback_start', 'feedback_end')):
        try:
            start = date.fromisoformat(meta[start_key])
            end = date.fromisoformat(meta[end_key])
        except (TypeError, ValueError):
            continue
        if start <= end:
            periods.append((start, end))
    days = set()
    for start, end in periods:
        cursor = start
        while cursor <= end:
            days.add(cursor)
            cursor += timedelta(days=1)
    return sorted(days)


def _expected_dates(meta: dict[str, Any], start: date, end: date, sku: str | None = None) -> list[date]:
    launch = json.loads(meta.get('launch_dates') or '{}')
    days = [day for day in _dataset_period_dates(meta) if start <= day <= end]
    if sku and launch.get(sku):
        launch_date = date.fromisoformat(launch[sku])
        days = [day for day in days if day >= launch_date]
    return days


def _rows(start: date, end: date, sku: str | None = None) -> list[dict[str, Any]]:
    sql = '''SELECT o.order_id,o.order_date,o.product_id,o.qty,o.unit_price_minor,o.discount_minor,
                    o.refund_minor,o.campaign_id,o.stage,p.name,p.category,p.current_price_minor,
                    (SELECT c.unit_cost_minor FROM analytics_costs c
                     WHERE c.product_id=o.product_id AND c.effective_date<=o.order_date
                     ORDER BY c.effective_date DESC LIMIT 1) AS unit_cost_minor
             FROM analytics_orders o JOIN analytics_products p ON p.product_id=o.product_id
             WHERE o.order_date>=:start AND o.order_date<=:end'''
    params = {'start': start.isoformat(), 'end': end.isoformat()}
    if sku:
        sql += ' AND o.product_id=:sku'
        params['sku'] = sku
    sql += ' ORDER BY o.order_date,o.order_id,o.product_id'
    with engine.connect() as c:
        return [dict(row) for row in c.execute(text(sql), params).mappings()]


def _store_dates(start: date, end: date) -> set[str]:
    with engine.connect() as c:
        rows = c.execute(text('SELECT DISTINCT order_date FROM analytics_orders WHERE order_date>=:start AND order_date<=:end'),
                         {'start': start.isoformat(), 'end': end.isoformat()}).scalars().all()
    return set(rows)


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    order_ids = {row['order_id'] for row in rows}
    cups = sum(row['qty'] for row in rows)
    gross = sum(row['qty'] * row['unit_price_minor'] for row in rows)
    discount = sum(row['discount_minor'] for row in rows)
    refund = sum(row['refund_minor'] for row in rows)
    net = gross - discount - refund
    missing_cost = sorted({row['product_id'] for row in rows if row['unit_cost_minor'] is None})
    variable_cost = None if missing_cost else sum(row['qty'] * row['unit_cost_minor'] for row in rows)
    contribution = None if variable_cost is None else net - variable_cost
    return {
        'order_count': len(order_ids), 'line_count': len(rows), 'cups': cups,
        'gross_revenue_fen': gross, 'discount_fen': discount, 'refund_fen': refund,
        'net_revenue_fen': net, 'variable_cost_fen': variable_cost,
        'contribution_fen': contribution, 'contribution_complete': not missing_cost,
        'missing_cost_skus': missing_cost,
    }


def _coverage(meta: dict[str, Any], start: date, end: date, sku: str | None, rows: list[dict[str, Any]]) -> dict[str, Any]:
    expected = _expected_dates(meta, start, end, sku)
    expected_strings = [day.isoformat() for day in expected]
    dataset_dates = {day.isoformat() for day in _dataset_period_dates(meta)}
    requested = []
    cursor = start
    while cursor <= end:
        requested.append(cursor.isoformat())
        cursor += timedelta(days=1)
    outside = [day for day in requested if day not in dataset_dates]
    store_dates = _store_dates(start, end)
    missing = [day for day in expected_strings if day not in store_dates]
    row_dates = {row['order_date'] for row in rows}
    zero_dates = [day for day in expected_strings if sku and day in store_dates and day not in row_dates]
    return {
        'requested_days': len(requested), 'expected_days': len(expected_strings), 'data_days': len(row_dates),
        'complete': not missing and not outside, 'missing_dates': missing, 'zero_dates': zero_dates,
        'outside_dates': outside,
    }


def _summary(start: date, end: date, sku: str | None = None) -> dict[str, Any]:
    meta = _require_meta()
    rows = _rows(start, end, sku)
    result = _aggregate(rows)
    result.update({
        'start': start.isoformat(), 'end': end.isoformat(), 'sku_id': sku,
        'brand': meta['brand'], 'dataset_version': meta['dataset_version'],
        'data_kind': meta['data_kind'], 'data_as_of': meta['feedback_end'] or meta['history_end'],
        'coverage': _coverage(meta, start, end, sku, rows),
    })
    if not rows and not result['coverage']['complete']:
        result.update(net_revenue_fen=None, cups=None, order_count=None, line_count=None,
                      gross_revenue_fen=None, discount_fen=None, refund_fen=None,
                      variable_cost_fen=None, contribution_fen=None, contribution_complete=False)
    return result


def _trend(start: date, end: date, sku: str | None = None) -> list[dict[str, Any]]:
    meta = _require_meta()
    rows = _rows(start, end, sku)
    by_date: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_date.setdefault(row['order_date'], []).append(row)
    store_dates = _store_dates(start, end)
    launch = json.loads(meta.get('launch_dates') or '{}')
    launch_date = date.fromisoformat(launch[sku]) if sku and launch.get(sku) else None
    points = []
    metric_keys = ('order_count', 'line_count', 'cups', 'gross_revenue_fen', 'discount_fen',
                   'refund_fen', 'net_revenue_fen', 'variable_cost_fen', 'contribution_fen',
                   'contribution_complete', 'missing_cost_skus')
    for day in _expected_dates(meta, start, end, sku):
        key = day.isoformat()
        day_rows = by_date.get(key, [])
        if launch_date and day < launch_date:
            state, values = 'not_on_sale', None
        elif not day_rows:
            state = 'zero' if key in store_dates else 'missing'
            values = ({'order_count': 0, 'line_count': 0, 'cups': 0,
                       'gross_revenue_fen': 0, 'discount_fen': 0, 'refund_fen': 0,
                       'net_revenue_fen': 0, 'variable_cost_fen': 0,
                       'contribution_fen': 0, 'contribution_complete': True,
                       'missing_cost_skus': []} if state == 'zero' else None)
        else:
            state, values = 'ok', _aggregate(day_rows)
        metrics = {name: None for name in metric_keys}
        if values:
            metrics.update(values)
        points.append({'date': key, 'stage': 'feedback' if meta['feedback_start'] and key >= meta['feedback_start'] else 'history',
                       'state': state, **metrics})
    return points


def _products(start: date, end: date, sort: str = 'revenue', sku: str | None = None) -> list[dict[str, Any]]:
    _require_meta()
    rows = _rows(start, end, sku)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row['product_id'], []).append(row)
    result = []
    for product_id, product_rows in grouped.items():
        first = product_rows[0]
        result.append({'product_id': product_id, 'name': first['name'], 'category': first['category'],
                       'current_price_minor': first['current_price_minor'], **_aggregate(product_rows)})
    key = {'cups': 'cups', 'revenue': 'net_revenue_fen', 'contribution': 'contribution_fen'}.get(sort, 'net_revenue_fen')
    result.sort(key=lambda row: (row[key] is None, -(row[key] or 0), row['name']))
    return result


def _campaigns(start: date | None, end: date | None, sku: str | None = None) -> list[dict[str, Any]]:
    _require_meta()
    with engine.connect() as c:
        rows = [dict(row) for row in c.execute(text('SELECT * FROM analytics_campaigns ORDER BY start_date, campaign_id')).mappings()]
    result = []
    for campaign in rows:
        if sku and campaign['sku'] != sku:
            continue
        period_start, period_end = date.fromisoformat(campaign['start_date']), date.fromisoformat(campaign['end_date'])
        if (end and period_start > end) or (start and period_end < start):
            continue
        campaign_rows = _rows(period_start, period_end, campaign['sku'])
        participating = [row for row in campaign_rows if row['campaign_id'] == campaign['campaign_id']]
        actual = _aggregate(campaign_rows)
        spend = campaign['actual_spend_minor']
        actual['campaign_id'] = campaign['campaign_id']
        actual['sku'] = campaign['sku']
        actual['start'] = campaign['start_date']
        actual['end'] = campaign['end_date']
        actual['rule'] = campaign['rule']
        actual['planned_spend_minor'] = campaign['planned_spend_minor']
        actual['actual_spend_minor'] = spend
        actual['contribution_after_spend_fen'] = (
            actual['contribution_fen'] - spend if actual['contribution_fen'] is not None and spend is not None else None
        )
        actual['participating_order_count'] = len({row['order_id'] for row in participating})
        actual['participating_cups'] = sum(row['qty'] for row in participating)
        actual['participating_discount_fen'] = sum(row['discount_minor'] for row in participating)
        actual['baseline'] = None
        actual['incremental_contribution_fen'] = None
        actual['incremental_roi'] = None
        actual['baseline_status'] = 'not_configured'
        result.append(actual)
    return result


def _quality(start: date, end: date) -> dict[str, Any]:
    meta = _require_meta()
    with engine.connect() as c:
        missing_costs = [row[0] for row in c.execute(text(
            'SELECT DISTINCT o.product_id FROM analytics_orders o '
            'WHERE o.order_date>=:start AND o.order_date<=:end '
            'AND NOT EXISTS (SELECT 1 FROM analytics_costs c '
            'WHERE c.product_id=o.product_id AND c.effective_date<=o.order_date)'),
            {'start': start.isoformat(), 'end': end.isoformat()}).all()]
        order_dates = [row[0] for row in c.execute(text(
            'SELECT DISTINCT order_date FROM analytics_orders WHERE order_date>=:start AND order_date<=:end'),
            {'start': start.isoformat(), 'end': end.isoformat()}).scalars()]
    coverage = _coverage(meta, start, end, None, _rows(start, end))
    return {'dataset_version': meta['dataset_version'], 'brand': meta['brand'],
            'data_kind': meta['data_kind'], 'data_as_of': meta['feedback_end'] or meta['history_end'],
            'imported_at': meta['imported_at'], 'coverage': coverage,
            'missing_cost_skus': sorted(missing_costs), 'data_days': len(order_dates),
            'notes': ['缺失日期不按零补齐；缺成本商品的贡献为未知。',
                      '活动基线/增量尚未配置，活动页只展示实际口径。']}


def _config() -> dict[str, Any]:
    meta = _meta()
    if not meta:
        return {'loaded': False}
    products = []
    with engine.connect() as c:
        products = [dict(row) for row in c.execute(text('SELECT product_id,name,spec,category FROM analytics_products ORDER BY name')).mappings()]
    return {'loaded': True, 'dataset_version': meta['dataset_version'], 'brand': meta['brand'],
            'data_kind': meta['data_kind'], 'history_period': [meta['history_start'], meta['history_end']],
            'feedback_period': [meta['feedback_start'], meta['feedback_end']],
            'default_start': meta['history_start'], 'default_end': meta['feedback_end'] or meta['history_end'],
            'data_as_of': meta['feedback_end'] or meta['history_end'],
            'min_contribution_fen': meta['min_contribution_minor'],
            'launch_dates': json.loads(meta['launch_dates'] or '{}'),
            'products': products,
            'notes': ['经营看板使用订单级合成数据；不等于真实经营结果。',
                      '金额为整数分；订单总数按订单号去重。']}


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@router.get('/config')
def config():
    return _config()


@router.get('/summary')
def summary(start: str | None = Query(None), end: str | None = Query(None), sku: str | None = Query(None)):
    start_date, end_date = _range(_require_meta(), start, end)
    return _summary(start_date, end_date, sku or None)


@router.get('/trend')
def trend(start: str | None = Query(None), end: str | None = Query(None), sku: str | None = Query(None)):
    start_date, end_date = _range(_require_meta(), start, end)
    return {'points': _trend(start_date, end_date, sku or None)}


@router.get('/products')
def products(start: str | None = Query(None), end: str | None = Query(None), sort: str = Query('revenue'), sku: str | None = Query(None)):
    start_date, end_date = _range(_require_meta(), start, end)
    if sort not in ('cups', 'revenue', 'contribution'):
        raise HTTPException(422, '排序仅支持 cups、revenue、contribution。')
    return {'products': _products(start_date, end_date, sort, sku or None)}


@router.get('/products/{product_id}')
def product_detail(product_id: str, start: str | None = Query(None), end: str | None = Query(None)):
    meta = _require_meta()
    with engine.connect() as c:
        exists = c.execute(text('SELECT 1 FROM analytics_products WHERE product_id=:id'), {'id': product_id}).first()
    if not exists:
        raise HTTPException(404, '经营商品不存在。')
    start_date, end_date = _range(meta, start, end)
    return {'product': next((item for item in _products(start_date, end_date) if item['product_id'] == product_id), None),
            'summary': _summary(start_date, end_date, product_id),
            'points': _trend(start_date, end_date, product_id)}


@router.get('/campaigns')
def campaigns(start: str | None = Query(None), end: str | None = Query(None), sku: str | None = Query(None)):
    meta = _require_meta()
    start_date, end_date = _range(meta, start, end)
    return {'campaigns': _campaigns(start_date, end_date, sku or None)}


@router.get('/quality')
def quality(start: str | None = Query(None), end: str | None = Query(None)):
    start_date, end_date = _range(_require_meta(), start, end)
    return _quality(start_date, end_date)
