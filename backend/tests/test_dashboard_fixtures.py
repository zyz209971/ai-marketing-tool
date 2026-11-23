"""Reconcile generated dashboard cases through the real HTTP import and API paths."""
import json
import os
from pathlib import Path
import tempfile

import pytest

RUNTIME = tempfile.TemporaryDirectory()
os.environ.update(APP_SKIP_DOTENV="true", APP_DATA_DIR=RUNTIME.name, USE_MOCK="true",
                  BRAND_DATABASE_URL="sqlite:///"+(Path(RUNTIME.name)/"brand.db").as_posix(),
                  BRAND_STORAGE_DIR=str(Path(RUNTIME.name)/"files"), WORKSPACE_LOCAL_ONLY="false",
                  APP_ACCESS_KEY="", SEED_DEMO_DATA="false")

from fastapi.testclient import TestClient

from app.main import app
from app import knowledge as kb
from scripts.generate_dashboard_fixtures import generate, read_team_inputs, TEAM_DATA


CASES = Path(RUNTIME.name) / "dashboard-cases"
CASE_IDS = ("stable", "declining_sales", "high_cost", "underperforming", "missing_values", "empty")


@pytest.fixture(scope="module")
def client():
    generate(CASES)
    with TestClient(app) as value:
        yield value
    kb.engine.dispose()


def import_case(client: TestClient, case_id: str) -> tuple[str, dict]:
    folder = CASES / case_id
    expected = json.loads((folder / "expected_dashboard.json").read_text(encoding="utf-8"))
    brand = client.post("/api/knowledge/brands", json={"name": expected["brand_name"],
                                                        "intro": expected["description"]})
    assert brand.status_code == 201, brand.text
    brand_id = brand.json()["id"]
    for data_type in ("products", "costs", "orders"):
        if data_type == "orders" and not json.loads((folder / "manifest.json").read_text(encoding="utf-8"))["has_orders"]:
            continue
        path = folder / "orders.csv" if data_type == "orders" else TEAM_DATA / f"{data_type}.csv"
        preview = client.post("/api/operations/imports/preview",
            data={"brand_id": brand_id, "data_type": data_type,
                  "source": f"dashboard-fixture:{case_id}", "synthetic": "true"},
            files={"file": (f"{data_type}.csv", path.read_bytes(), "text/csv")})
        assert preview.status_code == 201, preview.text
        preview_body = preview.json()
        assert preview_body["error_count"] == 0, preview_body
        confirmed = client.post(f'/api/operations/imports/{preview_body["import_id"]}/confirm')
        assert confirmed.status_code == 200, confirmed.text
    return brand_id, expected


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_dashboard_case_matches_independent_snapshot(client, case_id):
    brand_id, expected = import_case(client, case_id)
    query = expected["query"]
    actual = client.get(f"/api/operations/brands/{brand_id}/dashboard", params=query)
    assert actual.status_code == 200, actual.text
    body = actual.json()
    assert body["summary"]["metrics"] == expected["expected"]["summary_metrics"]
    assert body["trends"]["points"] == expected["expected"]["trend_points"]["day"]
    expected_products = expected["expected"]["products"]
    assert body["products"]["products"] == expected_products["products"]
    assert body["products"]["alerts"] == expected_products["alerts"]
    for grain in ("week", "month"):
        trends = client.get(f"/api/operations/brands/{brand_id}/trends",
                            params={"start": query["start"], "end": query["end"], "granularity": grain})
        assert trends.status_code == 200
        assert trends.json()["points"] == expected["expected"]["trend_points"][grain]


def test_cases_cover_required_dashboard_states():
    snapshots = {case_id: json.loads((CASES / case_id / "expected_dashboard.json").read_text(encoding="utf-8"))
                 for case_id in CASE_IDS}
    assert snapshots["stable"]["expected"]["products"]["alerts"] == []
    decline_alerts = snapshots["declining_sales"]["expected"]["products"]["alerts"]
    assert any(item["sku_id"] == "P002" for item in decline_alerts)
    high_cost = next(item for item in snapshots["high_cost"]["expected"]["products"]["products"]
                     if item["sku_id"] == "P002")
    assert high_cost["product_contribution_minor"] < 0
    underperforming = next(item for item in snapshots["underperforming"]["expected"]["products"]["products"]
                          if item["sku_id"] == "P002")
    assert underperforming["trend"] == "declining"
    missing = snapshots["missing_values"]["expected"]["summary_metrics"]
    assert missing["revenue_minor"] is None and missing["incomplete_fields"]["customer_paid_minor"] == 1
    empty = snapshots["empty"]["expected"]["summary_metrics"]
    assert empty["order_count"] == 0 and empty["sales_quantity"] == 0


def test_fixture_prices_come_from_canonical_product_catalog():
    _, _, names, prices = read_team_inputs()
    assert names["P002"] == "鲜萃轻轻茉莉"
    assert prices == {"P001": 2000, "P002": 1800, "P003": 2300, "P004": 1600, "P005": 2100}
