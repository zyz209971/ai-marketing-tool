"""Generate deterministic dashboard CSV/JSON fixtures from the team catalog.

The generated expected results use a small independent calculator rather than
the production operations module. API tests import the CSV files and reconcile
the real dashboard response against these snapshots.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
TEAM_DATA = REPO / "合成数据+人工答案+商品图片+csv+json"
PRODUCT_CATALOG = REPO / "产品知识库.csv"
CATALOG_BRAND = "瑞幸咖啡经营演示"
DEFAULT_OUTPUT = REPO / ".local-data" / "dashboard-fixtures"
FIELDS = (
    "order_id", "line_id", "date", "store_id", "sku_id", "fulfilled_qty",
    "list_amount_minor", "customer_paid_minor", "merchant_discount_minor",
    "platform_subsidy_minor", "refund_minor", "channel_fee_minor",
    "variable_cost_minor", "sales_channel", "status", "campaign_id",
    "campaign_version", "simulation_run_id", "data_source", "synthetic",
)
START = date(2026, 9, 28)
END = date(2026, 11, 2)
BASE_QTY = {"P001": 10, "P002": 8, "P003": 6, "P004": 7, "P005": 5}
DESCRIPTIONS = {
    "stable": "35 天销量和经营贡献稳定，用于正常看板与无告警状态。",
    "declining_sales": "P002 连续下降，用于销量趋势和下降告警。",
    "high_cost": "P002 单位成本 15 元且第二杯半价，用于负商品贡献展示。",
    "underperforming": "P002 活动期销量低于基线并打折，用于活动未达预期展示。",
    "missing_values": "存在未知实付金额，用于 null、缺失提示和不可用贡献展示。",
    "empty": "只有商品与成本，没有订单，用于看板空状态。",
}


def minor(value: str) -> int:
    return int(Decimal(value) * 100)


def read_team_inputs() -> tuple[list[dict], dict[str, int], dict[str, str], dict[str, int]]:
    with (TEAM_DATA / "products.csv").open(encoding="utf-8-sig", newline="") as handle:
        products = list(csv.DictReader(handle))
    costs: dict[str, int] = {}
    with (TEAM_DATA / "costs.csv").open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            costs[row["商品编号"]] = sum(minor(row[field]) for field in
                                          ("每杯原料成本", "每杯包材成本", "每杯其他变动成本"))
    names = {row["商品编号"]: row["商品名称"] for row in products}
    with PRODUCT_CATALOG.open(encoding="utf-8-sig", newline="") as handle:
        catalog = {(row["品牌"].strip(), row["产品名"].strip()): row for row in csv.DictReader(handle)}
    prices = {}
    for sku, name in names.items():
        record = catalog.get((CATALOG_BRAND, name))
        if not record:
            raise ValueError(f"产品知识库.csv 缺少 {CATALOG_BRAND}/{name}，不能生成看板案例。")
        raw_price = record["价格"].strip()
        if not raw_price.endswith("元"):
            raise ValueError(f"产品知识库.csv 中 {name} 的价格必须使用“数字+元”。")
        prices[sku] = minor(raw_price[:-1])
    return products, costs, names, prices


def order_row(case: str, day: date, sku: str, quantity: int, price: int, cost: int,
              paid: int | None = None, campaign_id: str = "") -> dict:
    gross = price * quantity
    customer_paid = gross if paid is None else paid
    suffix = f"{day:%Y%m%d}-{sku}"
    return {
        "order_id": f"fixture-{case}-{suffix}", "line_id": sku, "date": day.isoformat(),
        "store_id": f"fixture-{case}-store", "sku_id": sku, "fulfilled_qty": quantity,
        "list_amount_minor": gross, "customer_paid_minor": customer_paid,
        "merchant_discount_minor": None if customer_paid is None else gross - customer_paid,
        "platform_subsidy_minor": 0, "refund_minor": 0, "channel_fee_minor": 0,
        "variable_cost_minor": cost, "sales_channel": "pickup", "status": "completed",
        "campaign_id": campaign_id, "campaign_version": None, "simulation_run_id": None,
        "data_source": f"dashboard-fixture:{case}", "synthetic": True,
    }


def core_rows(case: str, prices: dict[str, int], costs: dict[str, int]) -> list[dict]:
    rows = []
    for index in range((END - START).days):
        day = START + timedelta(days=index)
        for offset, sku in enumerate(BASE_QTY):
            quantity = BASE_QTY[sku] + ((index + offset) % 3 - 1)
            cost = costs[sku]
            paid = None
            # Dashboard fixtures are descriptive operating cases, not approved
            # Agent campaign feedback. Keep campaign fields empty instead of
            # fabricating an approval version; the source field carries the case.
            campaign = ""
            if case == "declining_sales" and sku == "P002":
                quantity = max(2, 18 - index // 2)
            elif case == "high_cost" and sku == "P002":
                quantity = 10
                cost = 1500
                pairs = quantity // 2
                paid = (quantity - pairs) * prices[sku] + pairs * (prices[sku] // 2)
            elif case == "underperforming" and sku == "P002":
                if index < 21:
                    quantity = 10
                else:
                    quantity = 4
                    pairs = quantity // 2
                    paid = (quantity - pairs) * prices[sku] + pairs * (prices[sku] // 2)
            rows.append(order_row(case, day, sku, quantity, prices[sku], cost, paid, campaign))
    return rows


def missing_rows(prices: dict[str, int], costs: dict[str, int]) -> list[dict]:
    price = prices["P001"]
    first = order_row("missing_values", START, "P001", 2, price, costs["P001"])
    second = order_row("missing_values", START + timedelta(days=1), "P001", 2, price,
                       costs["P001"], paid=0)
    second["customer_paid_minor"] = None
    second["merchant_discount_minor"] = None
    return [first, second]


def sum_complete(rows: list[dict], field: str) -> tuple[int | None, int]:
    missing = sum(row[field] is None for row in rows)
    return (None if missing else sum(row[field] for row in rows), missing)


def metrics(rows: list[dict]) -> dict:
    gmv, missing_gmv = sum_complete(rows, "list_amount_minor")
    paid, missing_paid = sum_complete(rows, "customer_paid_minor")
    subsidy, missing_subsidy = sum_complete(rows, "platform_subsidy_minor")
    refunds, missing_refund = sum_complete(rows, "refund_minor")
    missing_cost = sum(row["variable_cost_minor"] is None for row in rows)
    cost = None if missing_cost else sum(row["variable_cost_minor"] * row["fulfilled_qty"] for row in rows)
    revenue = None if missing_paid or missing_subsidy or missing_refund else paid + subsidy - refunds
    contribution = revenue - cost if revenue is not None and cost is not None else None
    incomplete = {
        key: value for key, value in {
            "list_amount_minor": missing_gmv, "customer_paid_minor": missing_paid,
            "platform_subsidy_minor": missing_subsidy, "refund_minor": missing_refund,
            "variable_cost_minor": missing_cost,
        }.items() if value
    }
    return {
        "currency": "CNY", "money_unit": "minor",
        "order_count": len({row["order_id"] for row in rows}),
        "sales_quantity": sum(row["fulfilled_qty"] for row in rows),
        "gmv_minor": gmv, "revenue_minor": revenue, "variable_cost_minor": cost,
        "product_contribution_minor": contribution,
        "contribution_rate": contribution / revenue if contribution is not None and revenue else None,
        "incomplete_fields": incomplete,
        "synthetic": bool(rows) and all(row["synthetic"] for row in rows),
        "mixed_synthetic": any(row["synthetic"] for row in rows) and not all(row["synthetic"] for row in rows),
    }


def period_key(stamp: str, granularity: str) -> str:
    current = date.fromisoformat(stamp)
    if granularity == "day":
        return current.isoformat()
    if granularity == "week":
        return (current - timedelta(days=current.weekday())).isoformat()
    return current.replace(day=1).isoformat()


def trend_points(rows: list[dict], granularity: str) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[period_key(row["date"], granularity)].append(row)
    return [{"period_start": key, **metrics(grouped[key])} for key in sorted(grouped)]


def product_result(rows: list[dict], names: dict[str, str]) -> dict:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["sku_id"]].append(row)
    observed = sorted({date.fromisoformat(row["date"]) for row in rows})
    midpoint = observed[0] + timedelta(days=((observed[-1] - observed[0]).days + 1) // 2) if observed else None
    products = []
    for sku, items in grouped.items():
        previous = sum(row["fulfilled_qty"] for row in items if midpoint and date.fromisoformat(row["date"]) < midpoint)
        current = sum(row["fulfilled_qty"] for row in items if midpoint and date.fromisoformat(row["date"]) >= midpoint)
        ratio = (current - previous) / previous if previous else None
        trend = "insufficient"
        if ratio is not None:
            trend = "declining" if ratio <= -0.1 else "increasing" if ratio >= 0.1 else "stable"
        products.append({"sku_id": sku, "name": names.get(sku, sku), **metrics(items),
                         "previous_half_quantity": previous, "current_half_quantity": current,
                         "change_ratio": ratio, "trend": trend})
    products.sort(key=lambda item: (item["product_contribution_minor"] is not None,
                                    item["product_contribution_minor"] or -1,
                                    item["sales_quantity"]), reverse=True)
    for rank, item in enumerate(products, 1):
        item["contribution_rank"] = rank
    alerts = [{"code": "sales_decline", "sku_id": item["sku_id"], "name": item["name"],
               "change_ratio": item["change_ratio"],
               "message": "连续对比期销量下降，请结合库存、渠道和活动信息进一步核查。"}
              for item in products if item["trend"] == "declining"]
    return {"money_unit": "minor",
            "comparison_method": "所选区间等分为前后两期；仅描述趋势，不推断原因。",
            "products": products, "alerts": alerts}


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: "" if row.get(field) is None else
                             str(row.get(field)).lower() if isinstance(row.get(field), bool) else row.get(field, "")
                             for field in FIELDS})


def build_expected(case: str, rows: list[dict], names: dict[str, str]) -> dict:
    case_end = END if rows and case not in {"missing_values"} else START + timedelta(days=2)
    if case == "empty":
        case_end = END
    return {
        "schema_version": "1.0", "case_id": case, "brand_name": f"看板案例-{case}",
        "description": DESCRIPTIONS[case], "source": "team catalog + deterministic fixture generator",
        "synthetic": True, "query": {"start": START.isoformat(), "end": case_end.isoformat(),
                                        "granularity": "day"},
        "expected": {
            "summary_metrics": metrics(rows),
            "trend_points": {grain: trend_points(rows, grain) for grain in ("day", "week", "month")},
            "products": product_result(rows, names),
        },
    }


def generate(output: Path) -> dict:
    _products, costs, names, prices = read_team_inputs()
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": "1.0", "generated_from": str(TEAM_DATA.relative_to(REPO)).replace("\\", "/"),
                "shared_sources": {"product_catalog": "产品知识库.csv",
                                   "sku_mapping": "products.csv", "costs": "costs.csv"},
                "cases": []}
    for case in DESCRIPTIONS:
        case_dir = output / case
        case_dir.mkdir(parents=True, exist_ok=True)
        if case in {"stable", "declining_sales", "high_cost", "underperforming"}:
            rows = core_rows(case, prices, costs)
        elif case == "missing_values":
            rows = missing_rows(prices, costs)
        else:
            rows = []
        write_csv(case_dir / "orders.csv", rows)
        expected = build_expected(case, rows, names)
        (case_dir / "expected_dashboard.json").write_text(
            json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8")
        case_info = {"case_id": case, "description": DESCRIPTIONS[case], "order_lines": len(rows),
                     "date_start": expected["query"]["start"], "date_end_exclusive": expected["query"]["end"],
                     "has_orders": bool(rows), "synthetic": True}
        (case_dir / "manifest.json").write_text(json.dumps(case_info, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest["cases"].append(case_info)
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = generate(args.output.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
