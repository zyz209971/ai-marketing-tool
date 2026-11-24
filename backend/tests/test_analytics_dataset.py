"""Validate dashboard formulas against the checked-in synthetic answer key."""
import json
import os
import tempfile
from pathlib import Path
import atexit

RUNTIME = tempfile.TemporaryDirectory()
DATASET = Path(__file__).resolve().parents[2] / '合成数据+人工答案+商品图片+csv+json'
os.environ.update(
    APP_SKIP_DOTENV='true',
    APP_DATA_DIR=RUNTIME.name,
    ANALYTICS_DATABASE_URL='sqlite:///' + (Path(RUNTIME.name) / 'analytics.db').as_posix(),
    BRAND_DATABASE_URL='sqlite:///' + (Path(RUNTIME.name) / 'brand.db').as_posix(),
    BRAND_STORAGE_DIR=str(Path(RUNTIME.name) / 'files'),
    WORKSPACE_LOCAL_ONLY='false',
    APP_ACCESS_KEY='',
    USE_MOCK='true',
    SEED_DEMO_DATA='false',
)
from fastapi.testclient import TestClient
from app.main import app
from app import analytics

atexit.register(analytics.engine.dispose)
from app import knowledge
atexit.register(knowledge.engine.dispose)
IMPORTED = analytics.import_dataset(DATASET)


def test_dataset_totals_match_expected_answers():
    result = IMPORTED
    assert result['products'] == 5
    assert result['campaigns'] == 2
    assert result['history_orders'] == 1158
    assert result['feedback_orders'] == 324

    expected = json.loads((DATASET / 'expected_answers.json').read_text(encoding='utf-8'))
    history = expected['stage_totals']['history_28d']
    feedback = expected['stage_totals']['feedback_7d']

    with TestClient(app) as client:
        history_response = client.get('/api/analytics/summary', params={
            'start': '2026-10-12', 'end': '2026-11-08'}).json()
        feedback_response = client.get('/api/analytics/summary', params={
            'start': '2026-11-09', 'end': '2026-11-15'}).json()

    for actual, wanted in ((history_response, history), (feedback_response, feedback)):
        assert actual['order_count'] == wanted['order_count']
        assert actual['line_count'] == wanted['line_count']
        assert actual['cups'] == wanted['cups']
        assert actual['gross_revenue_fen'] == wanted['gross_fen']
        assert actual['discount_fen'] == wanted['discount_fen']
        assert actual['refund_fen'] == wanted['refund_fen']
        assert actual['net_revenue_fen'] == wanted['net_revenue_fen']
        assert actual['variable_cost_fen'] == wanted['variable_cost_fen']
        assert actual['contribution_fen'] == wanted['contribution_fen']
        assert actual['contribution_complete'] is True


def test_campaign_review_matches_expected_answers():
    expected = json.loads((DATASET / 'expected_answers.json').read_text(encoding='utf-8'))
    with TestClient(app) as client:
        campaigns = client.get('/api/analytics/campaigns').json()['campaigns']
    by_id = {campaign['campaign_id']: campaign for campaign in campaigns}

    historical = expected['review']['historical_campaign_reviews']['BP-C20261019']
    actual = by_id['BP-C20261019']
    assert actual['order_count'] == historical['actual']['order_count']
    assert actual['cups'] == historical['actual']['cups']
    assert actual['net_revenue_fen'] == historical['actual']['net_revenue_fen']
    assert actual['contribution_fen'] == historical['actual']['contribution_fen']
    assert actual['actual_spend_minor'] == historical['marketing_spend_fen']
    assert actual['contribution_after_spend_fen'] == historical['contribution_after_spend_fen']
    assert actual['participating_cups'] == historical['redeemed']['cups']

    review = expected['review']['seven_day_review']
    actual = by_id['BP-C20261109']
    assert actual['order_count'] == review['actual']['order_count']
    assert actual['cups'] == review['actual']['cups']
    assert actual['net_revenue_fen'] == review['actual']['net_revenue_fen']
    assert actual['contribution_fen'] == review['actual']['contribution_fen']
    assert actual['actual_spend_minor'] == review['marketing_spend_fen']
    assert actual['contribution_after_spend_fen'] == review['contribution_after_spend_fen']
    assert actual['participating_cups'] == review['redeemed']['cups']
    assert actual['baseline'] is None
    assert actual['incremental_contribution_fen'] is None


def test_product_totals_and_known_zero_match_expected_answers():
    expected = json.loads((DATASET / 'expected_answers.json').read_text(encoding='utf-8'))
    p001 = next(row for row in expected['sku_totals'] if row['sku'] == 'P001')['history_28d']
    with TestClient(app) as client:
        product = client.get('/api/analytics/products/P001', params={
            'start': '2026-10-12', 'end': '2026-11-08'}).json()['product']
        zero = client.get('/api/analytics/trend', params={
            'start': '2026-10-27', 'end': '2026-10-27', 'sku': 'P004'}).json()['points'][0]
    assert product['cups'] == p001['cups']
    assert product['net_revenue_fen'] == p001['net_revenue_fen']
    assert product['variable_cost_fen'] == p001['variable_cost_fen']
    assert product['contribution_fen'] == p001['contribution_fen']
    assert zero['state'] == 'zero'
    assert zero['cups'] == 0
    assert zero['contribution_fen'] == 0


def test_config_reports_dataset_version_and_complete_coverage():
    with TestClient(app) as client:
        config = client.get('/api/analytics/config').json()
        quality = client.get('/api/analytics/quality', params={
            'start': '2026-10-12', 'end': '2026-11-15'}).json()
    assert config['dataset_version'] == 'brandpilot-luckin-operations-synthetic-v2'
    assert config['min_contribution_fen'] == 500
    assert config['data_kind'] == 'synthetic'
    assert quality['coverage']['complete'] is True
    assert quality['coverage']['expected_days'] == 35
    assert quality['missing_cost_skus'] == []
