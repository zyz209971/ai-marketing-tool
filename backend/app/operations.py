"""Order-level operating data, deterministic simulations and campaign reviews.

All money values are integer CNY cents. Date ranges are [start, end). The module
shares the brand/workspace database with the existing knowledge and Agent code,
but keeps imported order facts separate from the legacy aggregate CSV snapshot.
"""
from __future__ import annotations

import csv
import io
import json
import random
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import inspect, text

from . import knowledge as kb
from .marketing_agent.business import paid_price
from .marketing_agent.contracts import Offer


METHOD_VERSION = "operations-v1-order-lines"
CANONICAL_FIELDS = (
    "order_id", "line_id", "date", "store_id", "sku_id", "fulfilled_qty",
    "list_amount_minor", "customer_paid_minor", "merchant_discount_minor",
    "platform_subsidy_minor", "refund_minor", "channel_fee_minor",
    "variable_cost_minor", "sales_channel", "status", "campaign_id",
    "campaign_version", "simulation_run_id", "data_source", "synthetic",
)
REQUIRED_FIELDS = {"order_id", "line_id", "date", "sku_id", "fulfilled_qty", "status"}
OPTIONAL_AMOUNT_FIELDS = (
    "list_amount_minor", "customer_paid_minor", "merchant_discount_minor",
    "platform_subsidy_minor", "refund_minor", "channel_fee_minor", "variable_cost_minor",
)
ORDER_HEADER_ALIASES = {
    "订单号": "order_id", "订单日期": "date", "商品编号": "sku_id", "商品数量": "fulfilled_qty",
    "当时单杯原价": "unit_list_price_yuan", "优惠总额": "discount_yuan",
    "退款总额": "refund_yuan", "活动编号": "campaign_id",
}
COST_HEADER_ALIASES = {
    "商品编号": "sku_id", "成本生效日期": "effective_date", "每杯原料成本": "ingredient_yuan",
    "每杯包材成本": "packaging_yuan", "每杯其他变动成本": "other_yuan",
}
PRODUCT_HEADER_ALIASES = {
    "商品编号": "sku_id", "商品名称": "name", "规格": "spec", "当前售价": "price_yuan",
    "卖点": "selling", "分类": "category",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def init_db() -> None:
    with kb.engine.begin() as c:
        for statement in (
            """CREATE TABLE IF NOT EXISTS ops_import_batches (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, brand_id TEXT NOT NULL,
                filename TEXT NOT NULL, source TEXT NOT NULL, synthetic INTEGER NOT NULL,
                data_type TEXT NOT NULL, content_hash TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL,
                created TEXT NOT NULL, confirmed TEXT NOT NULL,
                UNIQUE(workspace_id, brand_id, content_hash)
            )""",
            """CREATE TABLE IF NOT EXISTS ops_orders (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, brand_id TEXT NOT NULL,
                order_id TEXT NOT NULL, line_id TEXT NOT NULL, business_date TEXT NOT NULL,
                store_id TEXT NOT NULL, sku_id TEXT NOT NULL, fulfilled_qty INTEGER NOT NULL,
                list_amount_minor INTEGER, customer_paid_minor INTEGER,
                merchant_discount_minor INTEGER, platform_subsidy_minor INTEGER,
                refund_minor INTEGER, channel_fee_minor INTEGER, variable_cost_minor INTEGER,
                sales_channel TEXT NOT NULL, status TEXT NOT NULL, campaign_id TEXT,
                campaign_version INTEGER, simulation_run_id TEXT, source TEXT NOT NULL,
                synthetic INTEGER NOT NULL, import_batch_id TEXT NOT NULL, created TEXT NOT NULL,
                UNIQUE(workspace_id, brand_id, order_id, line_id)
            )""",
            "CREATE INDEX IF NOT EXISTS ops_orders_brand_date ON ops_orders(workspace_id,brand_id,business_date)",
            "CREATE INDEX IF NOT EXISTS ops_orders_campaign ON ops_orders(workspace_id,brand_id,campaign_id,campaign_version)",
            """CREATE TABLE IF NOT EXISTS ops_skus (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, brand_id TEXT NOT NULL,
                sku_id TEXT NOT NULL, name TEXT NOT NULL, spec TEXT NOT NULL,
                source TEXT NOT NULL, synthetic INTEGER NOT NULL, import_batch_id TEXT NOT NULL,
                created TEXT NOT NULL, UNIQUE(workspace_id,brand_id,sku_id)
            )""",
            "CREATE INDEX IF NOT EXISTS ops_skus_brand ON ops_skus(workspace_id,brand_id,sku_id)",
            """CREATE TABLE IF NOT EXISTS ops_costs (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, brand_id TEXT NOT NULL,
                sku_id TEXT NOT NULL, effective_date TEXT NOT NULL, ingredient_minor INTEGER,
                packaging_minor INTEGER, other_minor INTEGER, total_minor INTEGER,
                source TEXT NOT NULL, synthetic INTEGER NOT NULL, import_batch_id TEXT NOT NULL,
                created TEXT NOT NULL, UNIQUE(workspace_id,brand_id,sku_id,effective_date)
            )""",
            "CREATE INDEX IF NOT EXISTS ops_costs_lookup ON ops_costs(workspace_id,brand_id,sku_id,effective_date)",
            """CREATE TABLE IF NOT EXISTS ops_campaigns (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, brand_id TEXT NOT NULL,
                sku_id TEXT NOT NULL, task_id TEXT NOT NULL, strategy_id TEXT NOT NULL,
                strategy_version INTEGER NOT NULL, offer_json TEXT NOT NULL,
                offer_hash TEXT NOT NULL, list_price_minor INTEGER NOT NULL,
                variable_cost_minor INTEGER NOT NULL, expected_qty INTEGER NOT NULL,
                expected_pairs INTEGER, planned_spend_minor INTEGER NOT NULL,
                start_date TEXT NOT NULL, end_date TEXT NOT NULL,
                baseline_start TEXT NOT NULL, baseline_end TEXT NOT NULL,
                status TEXT NOT NULL, created TEXT NOT NULL,
                UNIQUE(workspace_id, task_id, strategy_id, strategy_version)
            )""",
            """CREATE TABLE IF NOT EXISTS ops_simulations (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, brand_id TEXT NOT NULL,
                campaign_id TEXT NOT NULL, campaign_version INTEGER NOT NULL,
                scenario TEXT NOT NULL, seed INTEGER NOT NULL, actual_qty INTEGER NOT NULL,
                promotion_pairs INTEGER, marketing_spend_minor INTEGER NOT NULL,
                metadata TEXT NOT NULL, rows_json TEXT NOT NULL, created TEXT NOT NULL
            )""",
        ):
            c.execute(text(statement))


def _workspace() -> str:
    return kb.get_workspace()


def authorize_brand(brand_id: str) -> dict:
    with kb.engine.connect() as c:
        return kb.owned(c, brand_id, _workspace())


def _int(value: str | int | None, field: str, *, minimum: int = 0) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    raw = str(value).strip()
    if not raw.lstrip("-").isdigit():
        raise ValueError(f"{field} 必须是整数。")
    result = int(raw)
    if result < minimum:
        raise ValueError(f"{field} 不能小于 {minimum}。")
    return result


def _bool(value: str | bool | None, default: bool) -> bool:
    if value is None or str(value).strip() == "":
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "是"}:
        return True
    if normalized in {"0", "false", "no", "n", "否"}:
        return False
    raise ValueError("synthetic 必须是 true 或 false。")


def _date(value: str, field: str) -> str:
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except (ValueError, AttributeError):
        raise ValueError(f"{field} 必须是 YYYY-MM-DD 日期。") from None


def _yuan_minor(value, field: str) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        decimal = Decimal(str(value).strip())
    except InvalidOperation:
        raise ValueError(f"{field} 必须是最多两位小数的人民币元金额。") from None
    if decimal < 0 or decimal.as_tuple().exponent < -2:
        raise ValueError(f"{field} 必须是非负且最多两位小数的人民币元金额。")
    return int((decimal*100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _translate_headers(reader: csv.DictReader, aliases: dict[str, str]) -> list[dict]:
    return [{aliases.get(key, key): value for key, value in row.items()} for row in reader]


def _normalize_row(raw: dict, *, source: str, synthetic: bool, line_number: int) -> dict:
    fields = {key: (value.strip() if isinstance(value, str) else value) for key, value in raw.items() if key}
    missing = [field for field in REQUIRED_FIELDS if not fields.get(field)]
    if missing:
        raise ValueError("缺少必填字段：" + "、".join(sorted(missing)))
    quantity = _int(fields["fulfilled_qty"], "fulfilled_qty", minimum=0)
    values = {field: _int(fields.get(field), field, minimum=0) for field in OPTIONAL_AMOUNT_FIELDS}
    campaign_version = _int(fields.get("campaign_version"), "campaign_version", minimum=1)
    row = {
        "order_id": fields["order_id"][:200], "line_id": fields["line_id"][:200],
        "date": _date(fields["date"], "date"), "store_id": (fields.get("store_id") or "default-store")[:100],
        "sku_id": fields["sku_id"][:100], "fulfilled_qty": quantity,
        **values, "sales_channel": (fields.get("sales_channel") or "pickup")[:50],
        "status": fields["status"][:50], "campaign_id": (fields.get("campaign_id") or None),
        "campaign_version": campaign_version, "simulation_run_id": fields.get("simulation_run_id") or None,
        "data_source": (fields.get("data_source") or source)[:200],
        "synthetic": _bool(fields.get("synthetic"), synthetic), "line_number": line_number,
    }
    if row["status"] not in {"completed", "refunded", "cancelled"}:
        raise ValueError("status 仅支持 completed、refunded、cancelled。")
    if bool(row["campaign_id"]) != bool(row["campaign_version"]):
        raise ValueError("campaign_id 与 campaign_version 必须同时填写。")
    return row


def parse_orders_csv(raw: bytes, brand_id: str, source: str, synthetic: bool) -> dict:
    authorize_brand(brand_id)
    try:
        decoded = raw.decode("utf-8-sig")
    except UnicodeError:
        raise ValueError("请使用 UTF-8 CSV。") from None
    reader = csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames:
        raise ValueError("CSV 缺少表头。")
    headers = [name.strip() for name in reader.fieldnames if name]
    if len(headers) != len(set(headers)):
        raise ValueError("CSV 表头不能重复。")
    translated_headers = [ORDER_HEADER_ALIASES.get(name, name) for name in headers]
    team_format = set(ORDER_HEADER_ALIASES).issubset(set(headers))
    allowed = set(CANONICAL_FIELDS) | {"unit_list_price_yuan", "discount_yuan", "refund_yuan"}
    unknown = set(translated_headers) - allowed
    missing_headers = ({"order_id", "date", "sku_id", "fulfilled_qty"} if team_format else REQUIRED_FIELDS) - set(translated_headers)
    if unknown or missing_headers:
        parts = []
        if missing_headers:
            parts.append("缺少表头：" + "、".join(sorted(missing_headers)))
        if unknown:
            parts.append("未知表头：" + "、".join(sorted(unknown)))
        raise ValueError("；".join(parts))
    rows, errors, seen = [], [], set()
    translated_rows = _translate_headers(reader, ORDER_HEADER_ALIASES)
    for number, raw_row in enumerate(translated_rows, 2):
        if None in raw_row:
            errors.append({"line": number, "error": "列数超过表头。"})
            continue
        try:
            if team_format:
                quantity = _int(raw_row.get("fulfilled_qty"), "商品数量", minimum=0)
                unit_price = _yuan_minor(raw_row.get("unit_list_price_yuan"), "当时单杯原价")
                discount = _yuan_minor(raw_row.get("discount_yuan"), "优惠总额")
                refund = _yuan_minor(raw_row.get("refund_yuan"), "退款总额")
                if unit_price is None or discount is None or refund is None:
                    raise ValueError("当时单杯原价、优惠总额和退款总额不能为空。")
                gross = unit_price*quantity
                paid = gross-discount
                if paid < 0 or refund > paid:
                    raise ValueError("优惠或退款金额超过该行商品原价金额。")
                source_campaign = raw_row.get("campaign_id") or None
                team_row = {"order_id": raw_row.get("order_id"), "line_id": raw_row.get("sku_id"),
                            "date": raw_row.get("date"), "store_id": "default-store", "sku_id": raw_row.get("sku_id"),
                            "fulfilled_qty": quantity, "list_amount_minor": gross, "customer_paid_minor": paid,
                            "merchant_discount_minor": discount, "platform_subsidy_minor": 0, "refund_minor": refund,
                            "channel_fee_minor": 0, "variable_cost_minor": None, "sales_channel": "pickup",
                            "status": "completed", "campaign_id": None,
                            "campaign_version": None, "simulation_run_id": None, "data_source": source,
                            "synthetic": synthetic}
                # Team source campaigns predate the Agent approval workflow. They remain descriptive
                # historical facts; only simulator-generated feedback requires an approved version.
                row = _normalize_row({**team_row, "campaign_version": ""}, source=source, synthetic=synthetic, line_number=number)
                row["campaign_id"] = source_campaign
                row["campaign_version"] = None
            else:
                row = _normalize_row(raw_row, source=source, synthetic=synthetic, line_number=number)
            key = (row["order_id"], row["line_id"])
            if key in seen:
                raise ValueError("同一文件中 order_id + line_id 重复。")
            seen.add(key)
            rows.append(row)
        except ValueError as exc:
            errors.append({"line": number, "error": str(exc)})
    if not rows and not errors:
        raise ValueError("CSV 没有数据行。")
    product_ids = {row["sku_id"] for row in rows}
    with kb.engine.connect() as c:
        owned = {r[0] for r in c.execute(text("SELECT id FROM kb_products WHERE brand_id=:brand AND archived=0"), {"brand": brand_id})}
        owned |= {r[0] for r in c.execute(text("SELECT sku_id FROM ops_skus WHERE workspace_id=:workspace AND brand_id=:brand"),
                                         {"workspace": _workspace(), "brand": brand_id})}
    for row in list(rows):
        if row["sku_id"] not in owned:
            rows.remove(row)
            errors.append({"line": row["line_number"], "error": "商品不属于当前品牌或已归档。"})
    return {"rows": rows, "errors": sorted(errors, key=lambda item: item["line"]),
            "source": source, "synthetic": synthetic, "brand_id": brand_id,
            "product_ids": sorted(product_ids), "schema_version": "1.0", "data_type": "orders"}


def parse_costs_csv(raw: bytes, brand_id: str, source: str, synthetic: bool) -> dict:
    authorize_brand(brand_id)
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    except UnicodeError:
        raise ValueError("请使用 UTF-8 CSV。") from None
    if not reader.fieldnames:
        raise ValueError("CSV 缺少表头。")
    headers = [name.strip() for name in reader.fieldnames if name]
    translated = [COST_HEADER_ALIASES.get(name, name) for name in headers]
    expected = {"sku_id", "effective_date", "ingredient_yuan", "packaging_yuan", "other_yuan"}
    if set(translated) != expected:
        raise ValueError("成本 CSV 表头不符合团队模板。")
    with kb.engine.connect() as c:
        owned = {r[0] for r in c.execute(text("SELECT id FROM kb_products WHERE brand_id=:brand AND archived=0"), {"brand": brand_id})}
        owned |= {r[0] for r in c.execute(text("SELECT sku_id FROM ops_skus WHERE workspace_id=:workspace AND brand_id=:brand"),
                                         {"workspace": _workspace(), "brand": brand_id})}
    rows, errors, seen = [], [], set()
    for number, raw_row in enumerate(_translate_headers(reader, COST_HEADER_ALIASES), 2):
        try:
            sku = (raw_row.get("sku_id") or "").strip()
            if not sku or sku not in owned:
                raise ValueError("商品不属于当前品牌或已归档。")
            effective = _date(raw_row.get("effective_date") or "", "成本生效日期")
            if (sku, effective) in seen:
                raise ValueError("同一文件中商品和生效日期重复。")
            seen.add((sku, effective))
            parts = {key: _yuan_minor(raw_row.get(key), key) for key in ("ingredient_yuan", "packaging_yuan", "other_yuan")}
            if any(value is None for value in parts.values()):
                raise ValueError("成本分项不能为空；未知值请保留为空并修正后再确认。")
            rows.append({"sku_id": sku, "effective_date": effective,
                         "ingredient_minor": parts["ingredient_yuan"], "packaging_minor": parts["packaging_yuan"],
                         "other_minor": parts["other_yuan"], "total_minor": sum(parts.values()),
                         "data_source": source, "synthetic": synthetic, "line_number": number})
        except ValueError as exc:
            errors.append({"line": number, "error": str(exc)})
    return {"rows": rows, "errors": errors, "source": source, "synthetic": synthetic,
            "brand_id": brand_id, "schema_version": "1.0", "data_type": "costs"}


def parse_products_csv(raw: bytes, brand_id: str, source: str, synthetic: bool) -> dict:
    authorize_brand(brand_id)
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    except UnicodeError:
        raise ValueError("请使用 UTF-8 CSV。") from None
    if not reader.fieldnames:
        raise ValueError("CSV 缺少表头。")
    headers = [name.strip() for name in reader.fieldnames if name]
    translated = [PRODUCT_HEADER_ALIASES.get(name, name) for name in headers]
    expected = {"sku_id", "name", "spec", "price_yuan", "selling", "category"}
    if set(translated) != expected:
        raise ValueError("商品 CSV 表头不符合团队模板。")
    rows, errors, seen = [], [], set()
    for number, raw_row in enumerate(_translate_headers(reader, PRODUCT_HEADER_ALIASES), 2):
        try:
            sku = (raw_row.get("sku_id") or "").strip()
            name = (raw_row.get("name") or "").strip()
            if not sku or not name:
                raise ValueError("商品编号和商品名称不能为空。")
            if sku in seen:
                raise ValueError("同一文件中商品编号重复。")
            seen.add(sku)
            # This import establishes only the operating SKU mapping. Product
            # price/selling/category remain owned by 产品知识库.csv or confirmed
            # brand facts and must not create a second editable product master.
            _yuan_minor(raw_row.get("price_yuan"), "当前售价")
            rows.append({"sku_id": sku[:100], "name": name[:200], "spec": (raw_row.get("spec") or "")[:200],
                         "data_source": source, "synthetic": synthetic, "line_number": number})
        except ValueError as exc:
            errors.append({"line": number, "error": str(exc)})
    return {"rows": rows, "errors": errors, "source": source, "synthetic": synthetic,
            "brand_id": brand_id, "schema_version": "1.0", "data_type": "products"}


def preview_import(raw: bytes, brand_id: str, filename: str, source: str, synthetic: bool, data_type: str = "orders") -> dict:
    init_db()
    if data_type not in {"products", "orders", "costs"}:
        raise ValueError("data_type 仅支持 products、orders 或 costs。")
    parser = {"products": parse_products_csv, "orders": parse_orders_csv, "costs": parse_costs_csv}[data_type]
    payload = parser(raw, brand_id, source, synthetic)
    normalized = [{k: v for k, v in row.items() if k != "line_number"} for row in payload["rows"]]
    content_hash = digest({"brand_id": brand_id, "rows": normalized, "source": source, "synthetic": synthetic})
    workspace = _workspace()
    with kb.engine.begin() as c:
        existing = c.execute(text("SELECT * FROM ops_import_batches WHERE workspace_id=:workspace AND brand_id=:brand AND content_hash=:hash"),
                             {"workspace": workspace, "brand": brand_id, "hash": content_hash}).mappings().first()
        if existing:
            stored = json.loads(existing["payload"])
            return _batch_response(dict(existing), stored, reused=True)
        ident = uuid4().hex
        c.execute(text("""INSERT INTO ops_import_batches
            (id,workspace_id,brand_id,filename,source,synthetic,data_type,content_hash,status,payload,created,confirmed)
            VALUES(:id,:workspace,:brand,:filename,:source,:synthetic,:data_type,:hash,'preview',:payload,:created,'')"""),
                  {"id": ident, "workspace": workspace, "brand": brand_id, "filename": filename[:300],
                   "source": source[:200], "synthetic": int(synthetic), "data_type": data_type, "hash": content_hash,
                   "payload": json.dumps(payload, ensure_ascii=False), "created": now()})
    return _batch_response({"id": ident, "status": "preview", "brand_id": brand_id, "filename": filename,
                            "source": source, "synthetic": int(synthetic), "data_type": data_type, "content_hash": content_hash}, payload)


def _batch_response(batch: dict, payload: dict, reused: bool = False) -> dict:
    return {"import_id": batch["id"], "status": batch["status"], "brand_id": batch["brand_id"],
            "filename": batch["filename"], "source": batch["source"], "synthetic": bool(batch["synthetic"]),
            "data_type": batch.get("data_type") or payload.get("data_type", "orders"),
            "content_hash": batch["content_hash"], "reused": reused,
            "valid_count": len(payload["rows"]), "error_count": len(payload["errors"]),
            "errors": payload["errors"], "preview": payload["rows"][:20]}


def _verify_campaign_rows(c, brand_id: str, rows: list[dict]) -> None:
    workspace = _workspace()
    refs = {(row["campaign_id"], row["campaign_version"]) for row in rows if row.get("campaign_id")}
    for campaign_id, version in refs:
        campaign = c.execute(text("SELECT * FROM ops_campaigns WHERE id=:id AND workspace_id=:workspace AND brand_id=:brand"),
                             {"id": campaign_id, "workspace": workspace, "brand": brand_id}).mappings().first()
        if not campaign or campaign["status"] != "approved" or campaign["strategy_version"] != version:
            raise ValueError("活动回传必须关联当前品牌已经批准的活动版本。")


def confirm_import(import_id: str) -> dict:
    init_db()
    workspace = _workspace()
    with kb.engine.begin() as c:
        batch = c.execute(text("SELECT * FROM ops_import_batches WHERE id=:id AND workspace_id=:workspace"),
                          {"id": import_id, "workspace": workspace}).mappings().first()
        if not batch:
            raise HTTPException(404, "导入预览不存在。")
        kb.owned(c, batch["brand_id"], workspace)
        payload = json.loads(batch["payload"])
        if not payload["rows"]:
            raise ValueError("没有可确认入库的有效记录。")
        data_type = batch["data_type"]
        if data_type == "orders":
            # Imported historical team campaigns have no Agent strategy version. Simulator rows do.
            _verify_campaign_rows(c, batch["brand_id"], [row for row in payload["rows"] if row.get("campaign_version")])
        inserted = 0
        for row in payload["rows"]:
            if data_type == "products":
                product_key = digest([workspace, batch["brand_id"], row["sku_id"]])
                result = c.execute(text("""INSERT INTO ops_skus
                    (id,workspace_id,brand_id,sku_id,name,spec,source,synthetic,import_batch_id,created)
                    VALUES(:id,:workspace,:brand,:sku,:name,:spec,:source,:synthetic,:batch,:created)
                    ON CONFLICT(workspace_id,brand_id,sku_id) DO NOTHING"""),
                    {"id": product_key, "workspace": workspace, "brand": batch["brand_id"], "sku": row["sku_id"],
                     "name": row["name"], "spec": row["spec"], "source": row["data_source"], "synthetic": int(row["synthetic"]),
                     "batch": import_id, "created": now()})
                inserted += max(result.rowcount or 0, 0)
                continue
            if data_type == "costs":
                cost_key = digest([workspace, batch["brand_id"], row["sku_id"], row["effective_date"]])
                result = c.execute(text("""INSERT INTO ops_costs
                    (id,workspace_id,brand_id,sku_id,effective_date,ingredient_minor,packaging_minor,other_minor,total_minor,
                     source,synthetic,import_batch_id,created)
                    VALUES(:id,:workspace,:brand,:sku,:effective,:ingredient,:packaging,:other,:total,:source,:synthetic,:batch,:created)
                    ON CONFLICT(workspace_id,brand_id,sku_id,effective_date) DO NOTHING"""),
                    {"id": cost_key, "workspace": workspace, "brand": batch["brand_id"], "sku": row["sku_id"],
                     "effective": row["effective_date"], "ingredient": row["ingredient_minor"], "packaging": row["packaging_minor"],
                     "other": row["other_minor"], "total": row["total_minor"], "source": row["data_source"],
                     "synthetic": int(row["synthetic"]), "batch": import_id, "created": now()})
                inserted += max(result.rowcount or 0, 0)
                continue
            order_key = digest([workspace, batch["brand_id"], row["order_id"], row["line_id"]])
            params = {**row, "id": order_key, "workspace": workspace, "brand": batch["brand_id"],
                      "source": row.get("data_source") or batch["source"], "synthetic_value": int(row["synthetic"]),
                      "batch": import_id, "created": now()}
            result = c.execute(text("""INSERT INTO ops_orders
                (id,workspace_id,brand_id,order_id,line_id,business_date,store_id,sku_id,fulfilled_qty,
                 list_amount_minor,customer_paid_minor,merchant_discount_minor,platform_subsidy_minor,
                 refund_minor,channel_fee_minor,variable_cost_minor,sales_channel,status,campaign_id,
                 campaign_version,simulation_run_id,source,synthetic,import_batch_id,created)
                VALUES(:id,:workspace,:brand,:order_id,:line_id,:date,:store_id,:sku_id,:fulfilled_qty,
                 :list_amount_minor,:customer_paid_minor,:merchant_discount_minor,:platform_subsidy_minor,
                 :refund_minor,:channel_fee_minor,:variable_cost_minor,:sales_channel,:status,:campaign_id,
                 :campaign_version,:simulation_run_id,:source,:synthetic_value,:batch,:created)
                ON CONFLICT(workspace_id,brand_id,order_id,line_id) DO NOTHING"""), params)
            inserted += max(result.rowcount or 0, 0)
        c.execute(text("UPDATE ops_import_batches SET status='confirmed',confirmed=:now WHERE id=:id"),
                  {"now": now(), "id": import_id})
    valid = len(payload["rows"])
    return {"import_id": import_id, "status": "confirmed", "brand_id": batch["brand_id"],
            "success_count": inserted, "duplicate_count": valid-inserted,
            "error_count": len(payload["errors"]), "errors": payload["errors"],
            "synthetic": bool(batch["synthetic"]), "source": batch["source"], "data_type": batch["data_type"]}


def _rows(brand_id: str, start: date | None = None, end: date | None = None,
          campaign_id: str | None = None, campaign_version: int | None = None) -> list[dict]:
    authorize_brand(brand_id)
    clauses = ["workspace_id=:workspace", "brand_id=:brand", "status='completed'"]
    params = {"workspace": _workspace(), "brand": brand_id}
    if start:
        clauses.append("business_date>=:start")
        params["start"] = start.isoformat()
    if end:
        clauses.append("business_date<:end")
        params["end"] = end.isoformat()
    if campaign_id:
        clauses.append("campaign_id=:campaign")
        params["campaign"] = campaign_id
    if campaign_version:
        clauses.append("campaign_version=:version")
        params["version"] = campaign_version
    with kb.engine.connect() as c:
        rows = c.execute(text("SELECT * FROM ops_orders WHERE " + " AND ".join(clauses) + " ORDER BY business_date,order_id,line_id"), params).mappings().all()
    return _attach_costs([dict(row) for row in rows], brand_id)


def _attach_costs(rows: list[dict], brand_id: str) -> list[dict]:
    if not rows or all(row.get("variable_cost_minor") is not None for row in rows):
        return rows
    with kb.engine.connect() as c:
        cost_rows = c.execute(text("SELECT * FROM ops_costs WHERE workspace_id=:workspace AND brand_id=:brand ORDER BY effective_date"),
                              {"workspace": _workspace(), "brand": brand_id}).mappings().all()
    by_sku: dict[str, list[dict]] = defaultdict(list)
    for item in cost_rows:
        by_sku[item["sku_id"]].append(dict(item))
    for row in rows:
        if row.get("variable_cost_minor") is not None:
            continue
        effective = [item for item in by_sku.get(row["sku_id"], []) if item["effective_date"] <= row["business_date"]]
        if effective:
            row["variable_cost_minor"] = effective[-1]["total_minor"]
    return rows


def has_orders(brand_id: str) -> bool:
    try:
        authorize_brand(brand_id)
    except HTTPException:
        return False
    with kb.engine.connect() as c:
        return bool(c.execute(text("SELECT 1 FROM ops_orders WHERE workspace_id=:workspace AND brand_id=:brand LIMIT 1"),
                              {"workspace": _workspace(), "brand": brand_id}).first())


def orders_provenance(brand_id: str) -> dict:
    authorize_brand(brand_id)
    with kb.engine.connect() as c:
        rows = c.execute(text("SELECT import_batch_id,synthetic FROM ops_orders WHERE workspace_id=:workspace AND brand_id=:brand"),
                         {"workspace": _workspace(), "brand": brand_id}).mappings().all()
    batches = sorted({row["import_batch_id"] for row in rows})
    synthetic = bool(rows) and all(bool(row["synthetic"]) for row in rows)
    return {"data_kind": "synthetic" if synthetic else "user_provided",
            "data_version": digest(batches), "source_refs": ["operations-import:"+item for item in batches]}


def _sum_complete(rows: list[dict], field: str) -> tuple[int | None, int]:
    missing = sum(row[field] is None for row in rows)
    return (None if missing else sum(row[field] for row in rows), missing)


def calculate_metrics(rows: list[dict]) -> dict:
    quantity = sum(row["fulfilled_qty"] for row in rows)
    gmv, missing_gmv = _sum_complete(rows, "list_amount_minor")
    paid, missing_paid = _sum_complete(rows, "customer_paid_minor")
    subsidy, missing_subsidy = _sum_complete(rows, "platform_subsidy_minor")
    refunds, missing_refund = _sum_complete(rows, "refund_minor")
    costs_missing = sum(row["variable_cost_minor"] is None for row in rows)
    cost = None if costs_missing else sum(row["variable_cost_minor"] * row["fulfilled_qty"] for row in rows)
    revenue = None if any((missing_paid, missing_subsidy, missing_refund)) else paid + subsidy - refunds
    contribution = revenue-cost if revenue is not None and cost is not None else None
    return {"currency": "CNY", "money_unit": "minor", "order_count": len({row["order_id"] for row in rows}),
            "sales_quantity": quantity, "gmv_minor": gmv, "revenue_minor": revenue,
            "variable_cost_minor": cost, "product_contribution_minor": contribution,
            "contribution_rate": (contribution/revenue if contribution is not None and revenue else None),
            "incomplete_fields": {key: value for key, value in {
                "list_amount_minor": missing_gmv, "customer_paid_minor": missing_paid,
                "platform_subsidy_minor": missing_subsidy, "refund_minor": missing_refund,
                "variable_cost_minor": costs_missing}.items() if value},
            "synthetic": bool(rows) and all(bool(row["synthetic"]) for row in rows),
            "mixed_synthetic": any(bool(row["synthetic"]) for row in rows) and not all(bool(row["synthetic"]) for row in rows)}


def summary(brand_id: str, start: date | None = None, end: date | None = None) -> dict:
    rows = _rows(brand_id, start, end)
    return {"brand_id": brand_id, "time_range": {"start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None, "semantics": "[start,end)"},
            "method_version": METHOD_VERSION, "metrics": calculate_metrics(rows)}


def _period_key(stamp: str, granularity: str) -> str:
    current = date.fromisoformat(stamp)
    if granularity == "day":
        return current.isoformat()
    if granularity == "week":
        monday = current-timedelta(days=current.weekday())
        return monday.isoformat()
    return current.replace(day=1).isoformat()


def trends(brand_id: str, start: date | None, end: date | None, granularity: str) -> dict:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in _rows(brand_id, start, end):
        grouped[_period_key(row["business_date"], granularity)].append(row)
    return {"brand_id": brand_id, "granularity": granularity, "money_unit": "minor",
            "time_range": {"start": start.isoformat() if start else None, "end": end.isoformat() if end else None},
            "points": [{"period_start": key, **calculate_metrics(grouped[key])} for key in sorted(grouped)]}


def product_analysis(brand_id: str, start: date | None, end: date | None) -> dict:
    all_rows = _rows(brand_id, start, end)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in all_rows:
        grouped[row["sku_id"]].append(row)
    with kb.engine.connect() as c:
        names = {row["id"]: row["name"] for row in c.execute(text("SELECT id,name FROM kb_products WHERE brand_id=:brand"), {"brand": brand_id}).mappings()}
        names.update({row["sku_id"]: row["name"] for row in c.execute(text("SELECT sku_id,name FROM ops_skus WHERE workspace_id=:workspace AND brand_id=:brand"),
                                                                       {"workspace": _workspace(), "brand": brand_id}).mappings()})
    observed = sorted({date.fromisoformat(row["business_date"]) for row in all_rows})
    midpoint = observed[0]+timedelta(days=((observed[-1]-observed[0]).days+1)//2) if observed else None
    products = []
    for sku, rows in grouped.items():
        previous = sum(row["fulfilled_qty"] for row in rows if midpoint and date.fromisoformat(row["business_date"]) < midpoint)
        current = sum(row["fulfilled_qty"] for row in rows if midpoint and date.fromisoformat(row["business_date"]) >= midpoint)
        ratio = (current-previous)/previous if previous else None
        trend = "insufficient"
        if ratio is not None:
            trend = "declining" if ratio <= -0.1 else "increasing" if ratio >= 0.1 else "stable"
        products.append({"sku_id": sku, "name": names.get(sku, sku), **calculate_metrics(rows),
                         "previous_half_quantity": previous, "current_half_quantity": current,
                         "change_ratio": ratio, "trend": trend})
    products.sort(key=lambda item: (item["product_contribution_minor"] is not None,
                                    item["product_contribution_minor"] or -1, item["sales_quantity"]), reverse=True)
    for rank, item in enumerate(products, 1):
        item["contribution_rank"] = rank
    alerts = [{"code": "sales_decline", "sku_id": item["sku_id"], "name": item["name"],
               "change_ratio": item["change_ratio"], "message": "连续对比期销量下降，请结合库存、渠道和活动信息进一步核查。"}
              for item in products if item["trend"] == "declining"]
    return {"brand_id": brand_id, "money_unit": "minor", "comparison_method": "所选区间等分为前后两期；仅描述趋势，不推断原因。",
            "products": products, "alerts": alerts}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RiskPolicy(StrictModel):
    block_negative_unit_contribution: bool = True
    min_pair_contribution_minor: int = Field(default=0, ge=0, le=10000000)


class RiskCheck(StrictModel):
    list_price_minor: int = Field(ge=0, le=10000000)
    variable_cost_minor: int = Field(ge=0, le=10000000)
    offer: Offer
    policy: RiskPolicy = Field(default_factory=RiskPolicy)


def check_risk(request: RiskCheck) -> dict:
    pair_revenue = scenario_revenue(request.list_price_minor, 2, request.offer, 1 if request.offer.type == "second_cup_discount" else None)
    pair_cost = 2*request.variable_cost_minor
    pair_contribution = pair_revenue-pair_cost
    reasons = []
    if request.policy.block_negative_unit_contribution and pair_contribution < 0:
        reasons.append(f"每组优惠订单商品贡献为 {pair_contribution/100:.2f} 元，低于 0 元。")
    if pair_contribution < request.policy.min_pair_contribution_minor:
        reasons.append(f"每组优惠订单商品贡献低于配置下限 {request.policy.min_pair_contribution_minor/100:.2f} 元。")
    return {"approved": not reasons, "blocked": bool(reasons), "reasons": reasons,
            "pair_revenue_minor": pair_revenue, "pair_cost_minor": pair_cost,
            "pair_contribution_minor": pair_contribution, "money_unit": "minor"}


def scenario_revenue(price: int, quantity: int, offer: Offer, pairs: int | None) -> int:
    if offer.type == "none":
        return price*quantity
    if offer.type == "percentage":
        return paid_price(price, offer.pay_bps)*quantity
    if pairs is None or pairs < 0 or 2*pairs > quantity:
        raise ValueError("第二杯优惠需要有效参与组数。")
    return (quantity-pairs)*price + pairs*paid_price(price, offer.pay_bps)


def activity_metrics(price: int, cost: int, quantity: int, offer: Offer, pairs: int | None, spend: int) -> dict:
    revenue = scenario_revenue(price, quantity, offer, pairs)
    variable_cost = quantity*cost
    contribution = revenue-variable_cost
    after_spend = contribution-spend
    return {"sales_quantity": quantity, "revenue_minor": revenue, "variable_cost_minor": variable_cost,
            "product_contribution_minor": contribution, "marketing_spend_minor": spend,
            "contribution_after_marketing_minor": after_spend, "money_unit": "minor"}


def _approved_strategy(task_id: str, strategy_id: str, strategy_version: int) -> tuple[dict, dict]:
    from .marketing_agent.graph import dependency
    workspace = _workspace()
    with kb.engine.connect() as c:
        row = c.execute(text("SELECT state FROM agent_tasks WHERE id=:id AND workspace_id=:workspace"),
                        {"id": task_id, "workspace": workspace}).mappings().first()
    if not row:
        raise HTTPException(404, "营销任务不存在。")
    state = json.loads(row["state"])
    strategy = state.get("strategy") or {}
    approved = any(item.get("strategy_id") == strategy_id and item.get("version") == strategy_version for item in state.get("approvals", []))
    if (strategy.get("id") != strategy_id or strategy.get("version") != strategy_version
            or strategy.get("status") != "approved" or not approved
            or strategy.get("dependency") != dependency(state["brief"])):
        raise HTTPException(409, "活动版本尚未批准或审批已因参数变化失效。")
    return state, strategy


class CampaignCreate(StrictModel):
    task_id: str = Field(min_length=1, max_length=100)
    strategy_id: str = Field(min_length=1, max_length=100)
    strategy_version: int = Field(ge=1)
    campaign_id: str | None = Field(default=None, max_length=100)
    baseline_start: date | None = None
    baseline_end: date | None = None
    policy: RiskPolicy = Field(default_factory=RiskPolicy)


def create_campaign(request: CampaignCreate) -> dict:
    init_db()
    state, strategy = _approved_strategy(request.task_id, request.strategy_id, request.strategy_version)
    brief = state["brief"]
    brand_id, sku_id = brief.get("brand_id"), brief.get("sku_id")
    if not brand_id or not sku_id:
        raise HTTPException(422, "批准策略缺少品牌或商品。")
    authorize_brand(brand_id)
    from .marketing_agent.data import snapshot, business_row
    snap = snapshot(brand_id)
    row = business_row(snap, sku_id)
    price = snap["products"][sku_id]["price"]
    cost = brief.get("variable_cost_override_minor") if brief.get("variable_cost_override_minor") is not None else row.get("variable_cost_minor")
    if price is None or cost is None:
        raise HTTPException(422, "批准策略缺少明确售价或单位变动成本。")
    offer = Offer.model_validate(brief["offer"])
    risk = check_risk(RiskCheck(list_price_minor=price, variable_cost_minor=cost, offer=offer, policy=request.policy))
    if risk["blocked"]:
        raise HTTPException(409, {"message": "活动未通过负贡献风险校验。", "risk": risk})
    start, end = date.fromisoformat(brief["start_date"]), date.fromisoformat(brief["end_date"])
    baseline_start = request.baseline_start or (date.fromisoformat(row["current_start"]) if row else start-(end-start))
    baseline_end = request.baseline_end or (date.fromisoformat(row["current_end"]) if row else start)
    if baseline_end <= baseline_start:
        raise HTTPException(422, "历史基线日期区间无效。")
    campaign_id = request.campaign_id or uuid4().hex
    offer_json = json.dumps(offer.model_dump(mode="json"), sort_keys=True)
    params = {"id": campaign_id, "workspace": _workspace(), "brand": brand_id, "sku": sku_id,
              "task": request.task_id, "strategy": request.strategy_id, "version": request.strategy_version,
              "offer": offer_json, "offer_hash": digest(json.loads(offer_json)), "price": price, "cost": cost,
              "qty": brief["scenario_qty"], "pairs": brief.get("promotion_pairs"), "spend": brief["spend_minor"],
              "start": start.isoformat(), "end": end.isoformat(), "baseline_start": baseline_start.isoformat(),
              "baseline_end": baseline_end.isoformat(), "created": now()}
    with kb.engine.begin() as c:
        prior = c.execute(text("SELECT * FROM ops_campaigns WHERE workspace_id=:workspace AND task_id=:task AND strategy_id=:strategy AND strategy_version=:version"), params).mappings().first()
        if prior:
            return _campaign_dict(dict(prior), reused=True)
        c.execute(text("""INSERT INTO ops_campaigns
            (id,workspace_id,brand_id,sku_id,task_id,strategy_id,strategy_version,offer_json,offer_hash,
             list_price_minor,variable_cost_minor,expected_qty,expected_pairs,planned_spend_minor,
             start_date,end_date,baseline_start,baseline_end,status,created)
            VALUES(:id,:workspace,:brand,:sku,:task,:strategy,:version,:offer,:offer_hash,:price,:cost,
             :qty,:pairs,:spend,:start,:end,:baseline_start,:baseline_end,'approved',:created)"""), params)
    with kb.engine.connect() as c:
        return _campaign_dict(dict(c.execute(text("SELECT * FROM ops_campaigns WHERE id=:id"), {"id": campaign_id}).mappings().one()))


def _campaign_dict(row: dict, reused: bool = False) -> dict:
    return {"campaign_id": row["id"], "brand_id": row["brand_id"], "sku_id": row["sku_id"],
            "task_id": row["task_id"], "strategy_id": row["strategy_id"], "strategy_version": row["strategy_version"],
            "offer": json.loads(row["offer_json"]), "list_price_minor": row["list_price_minor"],
            "variable_cost_minor": row["variable_cost_minor"], "expected_qty": row["expected_qty"],
            "expected_pairs": row["expected_pairs"], "planned_spend_minor": row["planned_spend_minor"],
            "start_date": row["start_date"], "end_date": row["end_date"],
            "baseline_start": row["baseline_start"], "baseline_end": row["baseline_end"],
            "status": row["status"], "synthetic": False, "reused": reused}


def get_campaign(campaign_id: str) -> dict:
    with kb.engine.connect() as c:
        row = c.execute(text("SELECT * FROM ops_campaigns WHERE id=:id AND workspace_id=:workspace"),
                        {"id": campaign_id, "workspace": _workspace()}).mappings().first()
    if not row:
        raise HTTPException(404, "活动不存在。")
    authorize_brand(row["brand_id"])
    return dict(row)


class SimulationRequest(StrictModel):
    scenario: Literal["stable", "declining_sales", "high_cost", "underperforming"]
    seed: int = 42
    actual_qty: int | None = Field(default=None, ge=0, le=100000)
    promotion_pairs: int | None = Field(default=None, ge=0, le=50000)
    marketing_spend_minor: int | None = Field(default=None, ge=0, le=10000000)
    offer: Offer | None = None

    @model_validator(mode="after")
    def pairs_fit(self):
        if self.actual_qty is not None and self.promotion_pairs is not None and 2*self.promotion_pairs > self.actual_qty:
            raise ValueError("优惠组数乘以2不能超过销量。")
        return self


def _split(total: int, count: int, rng: random.Random, trend: bool) -> list[int]:
    if count <= 1:
        return [total]
    weights = [count-i if trend else 1+rng.uniform(-0.08, 0.08) for i in range(count)]
    raw = [total*w/sum(weights) for w in weights]
    result = [int(value) for value in raw]
    for index in sorted(range(count), key=lambda i: raw[i]-result[i], reverse=True)[:total-sum(result)]:
        result[index] += 1
    return result


def _simulation_rows(campaign: dict, request: SimulationRequest, run_id: str) -> tuple[list[dict], int, int | None, int]:
    rng = random.Random(request.seed)
    expected = campaign["expected_qty"]
    defaults = {"stable": expected, "declining_sales": max(0, round(expected*0.7)),
                "high_cost": expected, "underperforming": max(0, round(expected*0.6))}
    total = request.actual_qty if request.actual_qty is not None else defaults[request.scenario]
    offer = Offer.model_validate(json.loads(campaign["offer_json"]))
    pairs = request.promotion_pairs if request.promotion_pairs is not None else campaign["expected_pairs"]
    if offer.type == "second_cup_discount":
        pairs = min(pairs or 0, total//2)
    else:
        pairs = None
    spend = request.marketing_spend_minor if request.marketing_spend_minor is not None else campaign["planned_spend_minor"]
    start, end = date.fromisoformat(campaign["start_date"]), date.fromisoformat(campaign["end_date"])
    days = max((end-start).days, 1)
    daily = _split(total, days, rng, request.scenario == "declining_sales")
    remaining_pairs = pairs or 0
    rows = []
    for day_index, quantity in enumerate(daily):
        stamp = (start+timedelta(days=day_index)).isoformat()
        day_pairs = min(quantity//2, remaining_pairs)
        remaining_pairs -= day_pairs
        order_no = 0
        for _ in range(day_pairs):
            order_no += 1
            price = campaign["list_price_minor"]
            revenue = price+paid_price(price, offer.pay_bps)
            rows.append(_sim_row(campaign, run_id, stamp, order_no, 2, price*2, revenue, request.scenario))
        remaining = quantity-2*day_pairs
        for _ in range(remaining):
            order_no += 1
            price = campaign["list_price_minor"]
            revenue = paid_price(price, offer.pay_bps) if offer.type == "percentage" else price
            rows.append(_sim_row(campaign, run_id, stamp, order_no, 1, price, revenue, request.scenario))
    return rows, total, pairs, spend


def _sim_row(campaign: dict, run_id: str, stamp: str, order_no: int, qty: int, list_amount: int, paid: int, scenario: str) -> dict:
    order_id = f"sim-{run_id[:8]}-{stamp}-{order_no}"
    cost = campaign["variable_cost_minor"]
    if scenario == "high_cost":
        cost = max(cost, campaign["list_price_minor"]-paid_price(campaign["list_price_minor"], 2000))
    return {"order_id": order_id, "line_id": order_id+"-1", "date": stamp,
            "store_id": "simulated-store", "sku_id": campaign["sku_id"], "fulfilled_qty": qty,
            "list_amount_minor": list_amount, "customer_paid_minor": paid,
            "merchant_discount_minor": list_amount-paid, "platform_subsidy_minor": 0,
            "refund_minor": 0, "channel_fee_minor": 0, "variable_cost_minor": cost,
            "sales_channel": "pickup", "status": "completed", "campaign_id": campaign["id"],
            "campaign_version": campaign["strategy_version"], "simulation_run_id": run_id,
            "data_source": f"simulation:{scenario}", "synthetic": True}


def simulate(campaign_id: str, request: SimulationRequest) -> dict:
    campaign = get_campaign(campaign_id)
    approved_offer = Offer.model_validate(json.loads(campaign["offer_json"]))
    if request.offer is not None and request.offer.model_dump() != approved_offer.model_dump():
        raise HTTPException(409, "优惠参数与已批准活动版本不一致，需要重新审批。")
    run_id = uuid4().hex
    rows, total, pairs, spend = _simulation_rows(campaign, request, run_id)
    metadata = {"simulation_run_id": run_id, "campaign_id": campaign_id,
                "campaign_version": campaign["strategy_version"], "brand_id": campaign["brand_id"],
                "scenario": request.scenario, "seed": request.seed, "actual_qty": total,
                "promotion_pairs": pairs, "marketing_spend_minor": spend,
                "data_source": f"simulation:{request.scenario}", "synthetic": True,
                "generated_at": now(), "method_version": METHOD_VERSION}
    with kb.engine.begin() as c:
        c.execute(text("""INSERT INTO ops_simulations
            (id,workspace_id,brand_id,campaign_id,campaign_version,scenario,seed,actual_qty,
             promotion_pairs,marketing_spend_minor,metadata,rows_json,created)
             VALUES(:id,:workspace,:brand,:campaign,:version,:scenario,:seed,:qty,:pairs,:spend,:metadata,:rows,:created)"""),
                  {"id": run_id, "workspace": _workspace(), "brand": campaign["brand_id"], "campaign": campaign_id,
                   "version": campaign["strategy_version"], "scenario": request.scenario, "seed": request.seed,
                   "qty": total, "pairs": pairs, "spend": spend, "metadata": json.dumps(metadata, ensure_ascii=False),
                   "rows": json.dumps(rows, ensure_ascii=False), "created": now()})
    return {**metadata, "order_count": len(rows), "csv_url": f"/api/operations/simulations/{run_id}/orders.csv",
            "preview": rows[:20]}


def simulation_csv(run_id: str) -> str:
    with kb.engine.connect() as c:
        row = c.execute(text("SELECT * FROM ops_simulations WHERE id=:id AND workspace_id=:workspace"),
                        {"id": run_id, "workspace": _workspace()}).mappings().first()
    if not row:
        raise HTTPException(404, "模拟运行不存在。")
    authorize_brand(row["brand_id"])
    rows = json.loads(row["rows_json"])
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CANONICAL_FIELDS)
    writer.writeheader()
    writer.writerows({field: item.get(field, "") if item.get(field) is not None else "" for field in CANONICAL_FIELDS} for item in rows)
    return output.getvalue()


def _baseline_metrics(campaign: dict) -> dict:
    rows = _rows(campaign["brand_id"], date.fromisoformat(campaign["baseline_start"]), date.fromisoformat(campaign["baseline_end"]))
    relevant = [row for row in rows if row["sku_id"] == campaign["sku_id"] and not row.get("campaign_id")]
    metrics = calculate_metrics(relevant)
    return {"sales_quantity": metrics["sales_quantity"], "revenue_minor": metrics["revenue_minor"],
            "variable_cost_minor": metrics["variable_cost_minor"],
            "product_contribution_minor": metrics["product_contribution_minor"], "marketing_spend_minor": 0,
            "contribution_after_marketing_minor": metrics["product_contribution_minor"], "money_unit": "minor"}


def review(campaign_id: str) -> dict:
    campaign = get_campaign(campaign_id)
    baseline = _baseline_metrics(campaign)
    expected = activity_metrics(campaign["list_price_minor"], campaign["variable_cost_minor"], campaign["expected_qty"],
                                Offer.model_validate(json.loads(campaign["offer_json"])), campaign["expected_pairs"],
                                campaign["planned_spend_minor"])
    actual_rows = _rows(campaign["brand_id"], campaign_id=campaign_id, campaign_version=campaign["strategy_version"])
    actual_base = calculate_metrics(actual_rows)
    run_ids = {row["simulation_run_id"] for row in actual_rows if row.get("simulation_run_id")}
    actual_spend = campaign["planned_spend_minor"]
    if len(run_ids) == 1:
        with kb.engine.connect() as c:
            value = c.execute(text("SELECT marketing_spend_minor FROM ops_simulations WHERE id=:id AND workspace_id=:workspace"),
                              {"id": next(iter(run_ids)), "workspace": _workspace()}).scalar()
        if value is not None:
            actual_spend = value
    contribution = actual_base["product_contribution_minor"]
    actual = {"sales_quantity": actual_base["sales_quantity"], "revenue_minor": actual_base["revenue_minor"],
              "variable_cost_minor": actual_base["variable_cost_minor"], "product_contribution_minor": contribution,
              "marketing_spend_minor": actual_spend,
              "contribution_after_marketing_minor": contribution-actual_spend if contribution is not None else None,
              "money_unit": "minor"}
    baseline_after = baseline["contribution_after_marketing_minor"]
    for item in (baseline, expected, actual):
        item["incremental_vs_baseline_minor"] = (item["contribution_after_marketing_minor"]-baseline_after
                                                  if item["contribution_after_marketing_minor"] is not None and baseline_after is not None else None)
    differences = {"sales_quantity": actual["sales_quantity"]-expected["sales_quantity"],
                   "revenue_minor": _difference(actual["revenue_minor"], expected["revenue_minor"]),
                   "contribution_after_marketing_minor": _difference(actual["contribution_after_marketing_minor"], expected["contribution_after_marketing_minor"])}
    conclusion_code = "insufficient_data"
    conclusion = "实际回传数据不完整，暂不能判断经营目标是否达成。"
    if actual["contribution_after_marketing_minor"] is not None and baseline_after is not None:
        if actual["sales_quantity"] > baseline["sales_quantity"] and actual["contribution_after_marketing_minor"] < baseline_after:
            conclusion_code = "volume_up_contribution_down"
            conclusion = "活动销量相比历史基线有所增加，但营销优惠和宣传成本导致经营贡献下降。"
        elif actual["contribution_after_marketing_minor"] >= expected["contribution_after_marketing_minor"]:
            conclusion_code = "target_met"
            conclusion = "实际扣费后经营贡献达到或超过活动预期。"
        else:
            conclusion_code = "target_not_met"
            conclusion = "实际扣费后经营贡献低于活动预期。"
    return {"campaign_id": campaign_id, "campaign_version": campaign["strategy_version"],
            "brand_id": campaign["brand_id"], "money_unit": "minor", "causal_claim": False,
            "causal_note": "该复盘是历史基线、活动计划与实际回传的描述性比较，不构成严格因果归因。",
            "baseline": baseline, "expected": expected, "actual": actual, "actual_vs_expected": differences,
            "goal_met": conclusion_code == "target_met", "conclusion_code": conclusion_code,
            "conclusion": conclusion, "synthetic": bool(actual_rows) and all(bool(row["synthetic"]) for row in actual_rows)}


def _difference(left: int | None, right: int | None) -> int | None:
    return left-right if left is not None and right is not None else None


def sales_summary_for_agent(brand_id: str, sku_id: str | None = None) -> dict | None:
    """Adapter used by the existing Agent tool; dashboard and Agent share arithmetic."""
    if not has_orders(brand_id):
        return None
    rows = _rows(brand_id)
    if not rows:
        return None
    latest = max(date.fromisoformat(row["business_date"]) for row in rows)+timedelta(days=1)
    earliest = min(date.fromisoformat(row["business_date"]) for row in rows)
    span = max((latest-earliest).days//2, 1)
    current_start = latest-timedelta(days=span)
    previous_start = current_start-timedelta(days=span)
    current = [row for row in rows if current_start <= date.fromisoformat(row["business_date"]) < latest]
    previous = [row for row in rows if previous_start <= date.fromisoformat(row["business_date"]) < current_start]
    skus = [sku_id] if sku_id else sorted({row["sku_id"] for row in rows})
    with kb.engine.connect() as c:
        names = {r["id"]: r["name"] for r in c.execute(text("SELECT id,name FROM kb_products WHERE brand_id=:brand"), {"brand": brand_id}).mappings()}
        names.update({r["sku_id"]: r["name"] for r in c.execute(text("SELECT sku_id,name FROM ops_skus WHERE workspace_id=:workspace AND brand_id=:brand"),
                                                                 {"workspace": _workspace(), "brand": brand_id}).mappings()})
    metrics = []
    for sku in skus:
        before_rows = [row for row in previous if row["sku_id"] == sku]
        after_rows = [row for row in current if row["sku_id"] == sku]
        before = sum(row["fulfilled_qty"] for row in before_rows)
        after = sum(row["fulfilled_qty"] for row in after_rows)
        metrics.append({"sku_id": sku, "name": names.get(sku, sku), "previous_qty": before,
                        "current_qty": after, "change_ratio": (after-before)/before if before else None,
                        "current_revenue_minor": calculate_metrics(after_rows)["revenue_minor"],
                        "daily_baseline_qty": after/span})
    return {"previous_period": [previous_start.isoformat(), current_start.isoformat()],
            "current_period": [current_start.isoformat(), latest.isoformat()], "metrics": metrics}
