"""Operating dashboard aggregation and API contracts (isolated SQLite)."""
import json
import os
import tempfile
from datetime import date
from pathlib import Path
import atexit

RUNTIME = tempfile.TemporaryDirectory()
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
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import analytics

atexit.register(analytics.engine.dispose)
from app import knowledge
atexit.register(knowledge.engine.dispose)


@pytest.fixture(scope='module')
def client():
    with TestClient(app) as instance:
        yield instance
    analytics.engine.dispose()
    from app import knowledge
    knowledge.engine.dispose()


def write_dataset(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'products.csv').write_text(
        '商品编号,商品名称,规格,当前售价,卖点,分类\n'
        'P001,测试茶,大杯,10.00,清爽,茶\n'
        'P002,测试咖啡,大杯,20.00,香浓,咖啡\n'
        'P003,无成本商品,大杯,15.00,待补成本,其他\n', encoding='utf-8')
    (root / 'costs.csv').write_text(
        '商品编号,成本生效日期,每杯原料成本,每杯包材成本,每杯其他变动成本\n'
        'P001,2026-01-01,2.00,1.00,0.50\n'
        'P002,2026-01-01,5.00,1.00,1.00\n', encoding='utf-8')
    (root / 'orders.csv').write_text(
        '订单号,订单日期,商品编号,商品数量,当时单杯原价,优惠总额,退款总额,活动编号\n'
        'O1,2026-01-01,P001,2,10.00,0,0,\n'
        'O1,2026-01-01,P002,1,20.00,0,0,\n'
        'O2,2026-01-01,P001,1,10.00,2.00,0,C1\n'
        'O3,2026-01-02,P003,1,15.00,0,0,\n'
        'O4,2026-01-03,P002,1,20.00,0,0,\n', encoding='utf-8')
    feedback = root / 'campaign_feedback'
    feedback.mkdir()
    (feedback / 'orders.csv').write_text(
        '订单号,订单日期,商品编号,商品数量,当时单杯原价,优惠总额,退款总额,活动编号\n',
        encoding='utf-8')
    (root / 'demo_context.json').write_text(json.dumps({
        'dataset_version': 'test-dashboard-v1',
        'brand': '测试品牌',
        'source': '合成数据',
        'history_period': ['2026-01-01', '2026-01-03'],
        'feedback_period': ['2026-01-04', '2026-01-04'],
        'minimum_unit_contribution_fen': 500,
        'new_item_launch_on': {'P003': '2026-01-02'},
        'campaigns': [{
            'campaign_id': 'C1', 'sku': 'P001', 'period': ['2026-01-01', '2026-01-01'],
            'rule': 'per_cup_discount', 'discount_per_cup_fen': 200,
            'planned_marketing_spend_fen': 1000, 'actual_marketing_spend_fen': 800,
            'basis': '测试活动',
        }],
    }, ensure_ascii=False), encoding='utf-8')


@pytest.fixture(scope='module')
def dataset(tmp_path_factory):
    root = tmp_path_factory.mktemp('dashboard-data')
    write_dataset(root)
    analytics.import_dataset(root)
    return root


def test_import_is_idempotent(dataset):
    first = analytics._summary(date(2026, 1, 1), date(2026, 1, 3))
    analytics.import_dataset(dataset)
    second = analytics._summary(date(2026, 1, 1), date(2026, 1, 3))
    assert first == second
    assert first['order_count'] == 4
    assert first['line_count'] == 5
    assert first['cups'] == 6
    assert first['net_revenue_fen'] == 8300
    assert first['discount_fen'] == 200
    assert first['contribution_fen'] is None
    assert first['missing_cost_skus'] == ['P003']


def test_summary_respects_cost_known_and_product_filter(dataset):
    response = analytics._summary(date(2026, 1, 1), date(2026, 1, 3), 'P001')
    assert response['net_revenue_fen'] == 2800
    assert response['cups'] == 3
    assert response['order_count'] == 2
    assert response['variable_cost_fen'] == 1050
    assert response['contribution_fen'] == 1750
    assert response['coverage']['zero_dates'] == ['2026-01-02', '2026-01-03']


def test_trend_distinguishes_zero_missing_and_not_on_sale(dataset):
    points = {point['date']: point for point in analytics._trend(
        date(2026, 1, 1), date(2026, 1, 4), 'P001')}
    assert points['2026-01-01']['state'] == 'ok'
    assert points['2026-01-02']['state'] == 'zero'
    assert points['2026-01-03']['state'] == 'zero'
    assert points['2026-01-04']['state'] == 'missing'
    assert points['2026-01-04']['net_revenue_fen'] is None

    p003 = {point['date']: point for point in analytics._trend(
        date(2026, 1, 1), date(2026, 1, 3), 'P003')}
    assert '2026-01-01' not in p003  # 新品上架前不伪造零销量/缺失点。
    assert p003['2026-01-02']['state'] == 'ok'
    assert p003['2026-01-02']['contribution_fen'] is None
    assert p003['2026-01-02']['contribution_complete'] is False


def test_product_ranking_keeps_missing_contribution_last(client):
    response = client.get('/api/analytics/products', params={
        'start': '2026-01-01', 'end': '2026-01-03', 'sort': 'contribution'})
    assert response.status_code == 200
    products = response.json()['products']
    assert [row['product_id'] for row in products] == ['P002', 'P001', 'P003']
    assert products[-1]['contribution_fen'] is None

    filtered = client.get('/api/analytics/products', params={
        'start': '2026-01-01', 'end': '2026-01-03', 'sku': 'P001', 'sort': 'revenue'}).json()['products']
    assert [row['product_id'] for row in filtered] == ['P001']


def test_campaign_actuals_and_unconfigured_baseline(client):
    response = client.get('/api/analytics/campaigns')
    assert response.status_code == 200
    campaign = response.json()['campaigns'][0]
    assert campaign['campaign_id'] == 'C1'
    assert campaign['cups'] == 3
    assert campaign['participating_cups'] == 1
    assert campaign['net_revenue_fen'] == 2800
    assert campaign['contribution_fen'] == 1750
    assert campaign['actual_spend_minor'] == 800
    assert campaign['contribution_after_spend_fen'] == 950
    assert campaign['baseline'] is None
    assert campaign['incremental_contribution_fen'] is None
    assert campaign['baseline_status'] == 'not_configured'

    filtered = client.get('/api/analytics/campaigns', params={'sku': 'P002'}).json()['campaigns']
    assert filtered == []


def test_quality_reports_missing_dates_and_costs(client):
    response = client.get('/api/analytics/quality', params={'start': '2026-01-01', 'end': '2026-01-04'})
    assert response.status_code == 200
    quality = response.json()
    assert quality['coverage']['missing_dates'] == ['2026-01-04']
    assert quality['coverage']['complete'] is False
    assert quality['missing_cost_skus'] == ['P003']
    assert '活动基线' in quality['notes'][1]


def test_config_and_empty_range(client):
    config = client.get('/api/analytics/config').json()
    assert config['loaded'] is True
    assert config['min_contribution_fen'] == 500
    assert config['launch_dates'] == {'P003': '2026-01-02'}
    assert len(config['products']) == 3

    empty = client.get('/api/analytics/summary', params={'start': '2026-01-04', 'end': '2026-01-04'}).json()
    assert empty['net_revenue_fen'] is None
    assert empty['coverage']['missing_dates'] == ['2026-01-04']

    outside = client.get('/api/analytics/summary', params={'start': '2026-01-01', 'end': '2026-01-05'}).json()
    assert outside['coverage']['complete'] is False
    assert outside['coverage']['outside_dates'] == ['2026-01-05']


def test_invalid_filters(client):
    assert client.get('/api/analytics/summary', params={'start': '2026-01-03', 'end': '2026-01-01'}).status_code == 422
    assert client.get('/api/analytics/summary', params={'start': 'bad'}).status_code == 422
    assert client.get('/api/analytics/products/missing').status_code == 404
