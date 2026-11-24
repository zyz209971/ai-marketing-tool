"""Order import, shared calculations, approved simulations and reviews."""
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4

RUNTIME = tempfile.TemporaryDirectory()
os.environ.update(APP_SKIP_DOTENV="true", APP_DATA_DIR=RUNTIME.name, USE_MOCK="true",
                  BRAND_DATABASE_URL="sqlite:///"+(Path(RUNTIME.name)/"brand.db").as_posix(),
                  BRAND_STORAGE_DIR=str(Path(RUNTIME.name)/"files"), WORKSPACE_LOCAL_ONLY="false",
                  APP_ACCESS_KEY="", SEED_DEMO_DATA="false")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app import knowledge as kb, operations
from app.marketing_agent import business, store
from app.marketing_agent.contracts import Brief
from app.marketing_agent.graph import dependency


DATASET = Path(__file__).parents[2]/"合成数据+人工答案+商品图片+csv+json"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as value:
        yield value
    kb.engine.dispose()


@pytest.fixture(scope="module")
def prepared(client):
    brand = client.post("/api/knowledge/brands", json={"name": "瑞幸咖啡经营演示", "intro": "课程合成经营数据"}).json()
    for data_type, relative in (("products", "products.csv"), ("costs", "costs.csv"), ("orders", "orders.csv")):
        raw = (DATASET/relative).read_bytes()
        preview = client.post("/api/operations/imports/preview",
            data={"brand_id": brand["id"], "data_type": data_type,
                  "source": "brandpilot-luckin-operations-synthetic-v2", "synthetic": "true"},
            files={"file": (Path(relative).name, raw, "text/csv")})
        assert preview.status_code == 201, preview.text
        body = preview.json()
        assert body["error_count"] == 0 and body["synthetic"] is True
        if data_type == "products":
            # Operating product input is only an SKU mapping. Product master
            # price/selling/category remain owned by 产品知识库.csv.
            assert not ({"list_price_minor", "selling", "category"} & set(body["preview"][0]))
        confirmed = client.post(f'/api/operations/imports/{body["import_id"]}/confirm')
        assert confirmed.status_code == 200, confirmed.text
    return brand


def test_team_dataset_matches_human_answers(client, prepared):
    result = client.get(f'/api/operations/brands/{prepared["id"]}/summary',
                        params={"start": "2026-10-12", "end": "2026-11-09"}).json()
    metrics = result["metrics"]
    assert metrics["order_count"] == 913
    assert metrics["sales_quantity"] == 1500
    assert metrics["gmv_minor"] == 2_832_200
    assert metrics["revenue_minor"] == 2_826_300
    assert metrics["variable_cost_minor"] == 1_278_660
    assert metrics["product_contribution_minor"] == 1_547_640
    assert metrics["synthetic"] is True


def test_duplicate_import_is_idempotent(client, prepared):
    before = client.get(f'/api/operations/brands/{prepared["id"]}/summary',
                        params={"start": "2026-10-12", "end": "2026-11-09"}).json()["metrics"]
    preview = client.post("/api/operations/imports/preview",
        data={"brand_id": prepared["id"], "data_type": "orders",
              "source": "brandpilot-luckin-operations-synthetic-v2", "synthetic": "true"},
        files={"file": ("orders.csv", (DATASET/"orders.csv").read_bytes(), "text/csv")}).json()
    assert preview["reused"] is True and preview["status"] == "confirmed"
    repeated = client.post(f'/api/operations/imports/{preview["import_id"]}/confirm').json()
    assert repeated["success_count"] == 0 and repeated["duplicate_count"] == 1158
    after = client.get(f'/api/operations/brands/{prepared["id"]}/summary',
                       params={"start": "2026-10-12", "end": "2026-11-09"}).json()["metrics"]
    assert after == before


def test_missing_amount_is_not_zero(client, prepared):
    raw = ("order_id,line_id,date,store_id,sku_id,fulfilled_qty,list_amount_minor,customer_paid_minor,"
           "merchant_discount_minor,platform_subsidy_minor,refund_minor,channel_fee_minor,variable_cost_minor,"
           "sales_channel,status,campaign_id,campaign_version,simulation_run_id,data_source,synthetic\n"
           "missing-1,P001,2026-12-01,s,P001,1,2000,,0,0,0,0,810,pickup,completed,,,,manual,false\n")
    preview = client.post("/api/operations/imports/preview",
        data={"brand_id": prepared["id"], "data_type": "orders", "source": "missing-test", "synthetic": "false"},
        files={"file": ("missing.csv", raw.encode(), "text/csv")}).json()
    client.post(f'/api/operations/imports/{preview["import_id"]}/confirm')
    metrics = client.get(f'/api/operations/brands/{prepared["id"]}/summary',
                         params={"start": "2026-12-01", "end": "2026-12-02"}).json()["metrics"]
    assert metrics["revenue_minor"] is None
    assert metrics["product_contribution_minor"] is None
    assert metrics["incomplete_fields"]["customer_paid_minor"] == 1


def test_high_cost_offer_is_blocked(client):
    response = client.post("/api/operations/campaigns/risk-check", json={
        "list_price_minor": 1800, "variable_cost_minor": 1500,
        "offer": {"type": "second_cup_discount", "pay_bps": 5000}})
    assert response.status_code == 200
    result = response.json()
    assert result["blocked"] is True and result["pair_contribution_minor"] == -300
    assert result["reasons"]


def _approved_campaign(client, brand):
    # Use the same P002 identifier as the team order source without changing the
    # existing product-management API or frontend.
    with kb.engine.begin() as c:
        c.execute(text("""INSERT INTO kb_products
            (id,brand_id,name,price,selling,image_document_id,spec,price_confirmed_at,category,archived,updated)
            VALUES('P002',:brand,'鲜萃轻轻茉莉','18元','茉莉花香','','大杯／冰','','轻乳茶',0,0)"""), {"brand": brand["id"]})
    brief = Brief(brand_id=brand["id"], sku_id="P002", platform="xiaohongshu",
                  start_date="2026-11-09", end_date="2026-11-11", budget_minor=10000,
                  spend_minor=10000, scenario_qty=40, promotion_pairs=10,
                  variable_cost_override_minor=650, min_contribution_override_minor=0,
                  offer={"type": "second_cup_discount", "pay_bps": 5000}).model_dump(mode="json")
    strategy_id, task_id = uuid4().hex, uuid4().hex
    strategy = {"id": strategy_id, "version": 1, "status": "approved", "dependency": dependency(brief)}
    state = {"brief": brief, "strategy": strategy,
             "approvals": [{"strategy_id": strategy_id, "version": 1}], "messages": [], "artifacts": []}
    with kb.engine.begin() as c:
        c.execute(text("INSERT INTO agent_tasks(id,revision,state,active_run,updated,workspace_id) VALUES(:id,0,:state,NULL,'now',:workspace)"),
                  {"id": task_id, "state": json.dumps(state, ensure_ascii=False), "workspace": kb.get_workspace()})
    response = client.post("/api/operations/campaigns/from-approved-strategy", json={
        "task_id": task_id, "strategy_id": strategy_id, "strategy_version": 1,
        "campaign_id": "acceptance-campaign", "baseline_start": "2026-11-02", "baseline_end": "2026-11-04"})
    assert response.status_code == 201, response.text
    return response.json()


def test_activity_plan_and_actual_review(client, prepared):
    campaign = _approved_campaign(client, prepared)
    estimate = client.post("/api/operations/campaigns/estimate", json={
        "list_price_minor": 1800, "variable_cost_minor": 650, "sales_quantity": 40,
        "promotion_pairs": 10, "marketing_spend_minor": 10000,
        "baseline_contribution_minor": 23000,
        "offer": {"type": "second_cup_discount", "pay_bps": 5000}}).json()
    assert estimate["revenue_minor"] == 63000
    assert estimate["product_contribution_minor"] == 37000
    assert estimate["contribution_after_marketing_minor"] == 27000
    assert estimate["incremental_vs_baseline_minor"] == 4000

    changed = client.post(f'/api/operations/campaigns/{campaign["campaign_id"]}/simulate', json={
        "scenario": "underperforming", "actual_qty": 24, "promotion_pairs": 12,
        "offer": {"type": "second_cup_discount", "pay_bps": 7000}})
    assert changed.status_code == 409

    simulated = client.post(f'/api/operations/campaigns/{campaign["campaign_id"]}/simulate', json={
        "scenario": "underperforming", "seed": 20261109, "actual_qty": 24,
        "promotion_pairs": 12, "marketing_spend_minor": 10000})
    assert simulated.status_code == 201, simulated.text
    meta = simulated.json()
    assert meta["synthetic"] is True and meta["actual_qty"] == 24
    csv_result = client.get(meta["csv_url"])
    assert csv_result.status_code == 200
    preview = client.post("/api/operations/imports/preview",
        data={"brand_id": prepared["id"], "data_type": "orders", "source": "acceptance-simulation", "synthetic": "true"},
        files={"file": ("actual.csv", csv_result.content, "text/csv")}).json()
    confirmed = client.post(f'/api/operations/imports/{preview["import_id"]}/confirm')
    assert confirmed.status_code == 200, confirmed.text
    review = client.get(f'/api/operations/campaigns/{campaign["campaign_id"]}/review').json()
    assert review["baseline"]["sales_quantity"] == 20
    assert review["baseline"]["revenue_minor"] == 36000
    assert review["baseline"]["variable_cost_minor"] == 13000
    assert review["baseline"]["product_contribution_minor"] == 23000
    assert review["expected"]["incremental_vs_baseline_minor"] == 4000
    assert review["actual"]["sales_quantity"] == 24
    assert review["actual"]["revenue_minor"] == 32400
    assert review["actual"]["variable_cost_minor"] == 15600
    assert review["actual"]["product_contribution_minor"] == 16800
    assert review["actual"]["contribution_after_marketing_minor"] == 6800
    assert review["actual"]["incremental_vs_baseline_minor"] == -16200
    assert review["conclusion_code"] == "volume_up_contribution_down"
    assert "营销优惠和宣传成本" in review["conclusion"]
    assert review["causal_claim"] is False and review["synthetic"] is True


def test_cross_brand_isolation_and_shared_dashboard_agent_math(client, prepared):
    other = client.post("/api/knowledge/brands", json={"name": "其他品牌", "intro": "隔离测试"}).json()
    empty = client.get(f'/api/operations/brands/{other["id"]}/summary').json()["metrics"]
    assert empty["sales_quantity"] == 0 and empty["revenue_minor"] == 0
    foreign = client.post("/api/operations/imports/preview",
        data={"brand_id": other["id"], "data_type": "orders", "source": "foreign", "synthetic": "true"},
        files={"file": ("orders.csv", (DATASET/"orders.csv").read_bytes(), "text/csv")}).json()
    assert foreign["valid_count"] == 0 and foreign["error_count"] == 1158

    agent = business.get_sales_summary(__import__("app.marketing_agent.contracts", fromlist=["SalesRequest"]).SalesRequest(
        brand_id=prepared["id"], sku_id="P002"))
    start, end = agent["result"]["current_period"]
    dashboard = client.get(f'/api/operations/brands/{prepared["id"]}/summary', params={"start": start, "end": end}).json()
    product = client.get(f'/api/operations/brands/{prepared["id"]}/products', params={"start": start, "end": end}).json()
    p002 = next(item for item in product["products"] if item["sku_id"] == "P002")
    metric = agent["result"]["metrics"][0]
    assert metric["current_revenue_minor"] == p002["revenue_minor"]
    assert dashboard["metrics"]["revenue_minor"] is None
    assert dashboard["metrics"]["incomplete_fields"]["customer_paid_minor"] == 1


def test_all_scenarios_are_repeatable(client):
    campaign_id = "acceptance-campaign"
    for scenario in ("stable", "declining_sales", "high_cost", "underperforming"):
        first = client.post(f"/api/operations/campaigns/{campaign_id}/simulate", json={"scenario": scenario, "seed": 7}).json()
        second = client.post(f"/api/operations/campaigns/{campaign_id}/simulate", json={"scenario": scenario, "seed": 7}).json()
        normalize = lambda rows: [{k: v for k, v in row.items() if k not in {"order_id", "line_id", "simulation_run_id"}} for row in rows]
        assert first["actual_qty"] == second["actual_qty"]
        assert normalize(first["preview"]) == normalize(second["preview"])
        assert first["synthetic"] is True
