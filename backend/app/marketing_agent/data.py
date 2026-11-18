"""Confirmed brand/catalog facts and single-store pickup summaries. No silent fixtures."""
import csv
import io
import json
import re
from datetime import date
from hashlib import sha256
from sqlalchemy import text
from pydantic import Field, model_validator
from .contracts import Contract
from .. import knowledge as kb


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def init_db():
    with kb.engine.begin() as c:
        c.execute(text('CREATE TABLE IF NOT EXISTS agent_business_data (brand_id TEXT PRIMARY KEY, version TEXT NOT NULL, payload TEXT NOT NULL)'))
        c.execute(text('CREATE TABLE IF NOT EXISTS agent_attachments (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL)'))


def price_minor(value):
    # Reject ranges/spec variants rather than guessing which price the user meant.
    match = re.fullmatch(r'\s*[¥￥]?\s*(\d+(?:\.\d{1,2})?)\s*(?:元(?:/杯)?)?\s*', str(value))
    if not match:
        return None
    from decimal import Decimal
    return int(Decimal(match[1])*100)


def snapshot(brand_id):
    with kb.engine.connect() as c:
        brand = kb.owned(c, brand_id, kb.get_workspace())
        rows = c.execute(text('SELECT * FROM kb_products WHERE brand_id=:id AND archived=0 ORDER BY id'), {'id': brand_id}).mappings().all()
        versions = c.execute(text("SELECT d.id,d.name,d.active_version FROM kb_documents d JOIN kb_versions v ON v.id=d.active_version WHERE d.brand_id=:id AND v.status='active' ORDER BY d.id"), {'id': brand_id}).mappings().all()
        entry = c.execute(text('SELECT payload,version FROM agent_business_data WHERE brand_id=:id'), {'id': brand_id}).mappings().first()
    products = {p['id']: {'name': p['name'], 'spec': p['spec'], 'price_confirmed_at':p['price_confirmed_at'], 'price': price_minor(p['price']),
                         'selling': [p['selling']], 'updated': p['updated']} for p in rows}
    value = {'brand': kb.brand_row(brand), 'products': products, 'documents': [dict(v) for v in versions],
             'business': json.loads(entry['payload']) if entry else None, 'business_version': entry['version'] if entry else None}
    value['version'] = digest(value)
    return value


class BusinessRow(Contract):
    product_id: str = Field(min_length=1, max_length=100)
    current_start: date
    current_end: date
    previous_start: date
    previous_end: date
    current_qty: int | None = Field(default=None, ge=0, le=10000000)
    previous_qty: int | None = Field(default=None, ge=0, le=10000000)
    variable_cost_minor: int | None = Field(default=None, ge=0, le=10000000)
    min_contribution_minor: int | None = Field(default=None, ge=0, le=10000000)
    daily_capacity: int | None = Field(default=None, ge=1, le=10000000)

    @model_validator(mode='after')
    def periods(self):
        days = (self.current_end-self.current_start).days
        if not 1 <= days <= 366 or (self.previous_end-self.previous_start).days != days or self.previous_end > self.current_start:
            raise ValueError('两期必须为不重叠、同长度的有效日期区间，含开始不含结束。')
        return self


class BusinessDraft(BusinessRow):
    current_start: date | None = None
    current_end: date | None = None
    previous_start: date | None = None
    previous_end: date | None = None

    @model_validator(mode='after')
    def periods(self):
        if all((self.current_start, self.current_end, self.previous_start, self.previous_end)):
            super().periods()
        return self


def parse_csv(raw, brand_id, allow_partial=False):
    try:
        reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    except UnicodeError:
        raise ValueError('请使用 UTF-8 CSV。') from None
    allowed = set(BusinessRow.model_fields)
    if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames) or set(reader.fieldnames)-allowed:
        raise ValueError('表头不符合模板，请先下载当前品牌的经营表模板。')
    snap = snapshot(brand_id)
    rows, seen, periods = [], set(), set()
    for line in reader:
        if None in line:
            raise ValueError('CSV 某行列数超过表头，请检查引号与逗号。')
        if len(rows) >= 500:
            raise ValueError('单次最多 500 款商品。')
        fields = {k: v.strip() for k, v in line.items() if k and v and v.strip()}
        row = (BusinessDraft if allow_partial else BusinessRow).model_validate(fields).model_dump(mode='json')
        pid = row['product_id']
        if pid not in snap['products'] or pid in seen:
            raise ValueError('商品不属于当前品牌、已归档或在表格中重复。')
        seen.add(pid)
        periods.add(tuple(row[k] for k in ('current_start','current_end','previous_start','previous_end')))
        rows.append(row)
    if not rows or len(periods) != 1:
        raise ValueError('请提供至少一行商品，且各行统计区间必须一致。')
    return {'rows': rows, 'catalog_version': digest(snap['products']), 'previous_business_version': snap['business_version'], 'data_kind': 'user_provided',
            'scope': '单门店自提、净完成杯数；所有金额为分；空值表示未知；导入会替换本品牌上一批经营汇总。'}


def save_business(brand_id, payload):
    # Serialize with catalog writers; a preview cannot silently adopt a changed catalog.
    with kb.engine.begin() as c:
        kb.lock_workspace(c)
        snap = snapshot(brand_id)
        if digest(snap['products']) != payload['catalog_version']:
            raise ValueError('商品资料已变化，请重新上传并核对经营表。')
        if snap['business_version'] != payload.get('previous_business_version'):
            raise ValueError('其他对话已更新经营数据，请重新预览后确认，避免覆盖。')
        c.execute(text('INSERT INTO agent_business_data(brand_id,version,payload) VALUES(:id,:version,:payload) ON CONFLICT(brand_id) DO UPDATE SET version=:version,payload=:payload'),
                  {'id': brand_id, 'version': digest(payload), 'payload': json.dumps(payload, ensure_ascii=False)})


def business_row(snap, sku):
    return next((r for r in (snap.get('business') or {}).get('rows', []) if r['product_id'] == sku), {})


def context(brief):
    if not brief.get('brand_id'):
        return {'name': '模拟门店', 'style': '', 'references': [], 'version': 'demo', 'data_kind': 'synthetic'}
    snap = snapshot(brief['brand_id'])
    product = snap['products'].get(brief.get('sku_id'), {})
    refs = kb.search_brand(brief['brand_id'], kb.get_workspace(), product.get('name', '')+' '+brief.get('goal', ''), limit=4)
    from .memory import preferences
    return {**snap['brand'], 'references': [{**r, 'knowledge_type': 'brand_fact', 'brand_id': brief['brand_id']} for r in refs],
            'memories': preferences(brief['brand_id']), 'version': snap['version'], 'data_kind': 'user_provided'}
