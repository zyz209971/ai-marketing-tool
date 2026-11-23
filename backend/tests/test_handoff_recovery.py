"""Product entry and submission recovery contracts in an isolated runtime."""
from test_marketing_agent import client, brand_setup, wait
from uuid import uuid4
from test_marketing_agent import message


def test_initial_product_binding_works_with_offline_unit_and_title_paths(client):
    b,p,_=brand_setup(client)
    created=client.post('/api/agent/conversations',json={'brand_id':b['id'],'sku_id':p['id']})
    assert created.status_code==201
    t=created.json()
    t=message(client,t,'只展示两杯收入、成本和贡献收益，第二杯半价，单杯变动成本：8元。')
    assert t['state']['brief']['sku_id']==p['id']
    assert t['state']['unit_result']['result']['pair_contribution_minor']==1100
    t=message(client,t,'写一篇小红书普通商品介绍，不做优惠活动')
    before=t['state']['artifacts'][-1]
    t=message(client,t,'只把标题改为“桂花遇见乌龙，日常一杯茶”，正文保持不变。')
    after=t['state']['artifacts'][-1]
    assert after['title']=='桂花遇见乌龙，日常一杯茶'
    assert after['body']==before['body']


def test_product_bound_before_first_message_and_survives_reload(client):
    b, p, _ = brand_setup(client)
    r = client.post('/api/agent/conversations', json={'brand_id': b['id'], 'sku_id': p['id']})
    assert r.status_code == 201
    task = r.json()
    loaded = client.get('/api/agent/conversations/' + task['id']).json()
    assert loaded['state']['brief']['sku_id'] == p['id']
    assert loaded['catalog'][p['id']]['name'] == p['name']
    assert len(loaded['state']['messages']) == 1
    assert loaded['active_run'] is None


def test_invalid_product_does_not_create_task(client):
    b, p, _ = brand_setup(client)
    other, _, _ = brand_setup(client)
    before = client.get('/api/agent/conversations').json()
    for payload in ({'sku_id': p['id']}, {'brand_id': other['id'], 'sku_id': p['id']},
                    {'brand_id': b['id'], 'sku_id': 'missing-product'}):
        assert client.post('/api/agent/conversations', json=payload).status_code in (404, 422)
    assert client.get('/api/agent/conversations').json() == before


def test_archived_product_is_rejected(client):
    b, p, _ = brand_setup(client)
    assert client.put('/api/knowledge/brands/' + b['id'] + '/products/' + p['id'],
                      json={**p, 'archived': True}).status_code == 200
    assert client.post('/api/agent/conversations', json={'brand_id': b['id'], 'sku_id': p['id']}).status_code == 422


def test_submission_receipt_is_scoped_and_retry_is_idempotent(client):
    t = client.post('/api/agent/conversations', json={'demo': True}).json()
    key = uuid4().hex
    path = '/api/agent/conversations/' + t['id']
    assert client.get(path + '/submissions/' + key).json() == {'found': False}
    payload = {'request_id': key, 'text': '你好', 'expected_revision': t['revision']}
    first = client.post(path + '/messages', json=payload)
    assert first.status_code == 202
    receipt = client.get(path + '/submissions/' + key).json()
    assert receipt['found'] and receipt['run_id'] == first.json()['run_id']
    assert set(receipt) == {'found', 'run_id', 'status'}
    assert client.post(path + '/messages', json=payload).json() == first.json()
    assert client.post(path + '/messages', json={**payload, 'text': '不同内容'}).status_code == 409
    other = client.post('/api/agent/conversations', json={}).json()
    assert client.get('/api/agent/conversations/' + other['id'] + '/submissions/' + key).json() == {'found': False}
    assert client.get('/api/agent/conversations/missing/submissions/' + key).status_code == 404


def test_other_workspace_cannot_bind_product_or_read_receipt(client, monkeypatch):
    from app import auth
    monkeypatch.setenv('AUTH_MODE', 'session')
    monkeypatch.setenv('COOKIE_SECURE', 'false')
    suffix = uuid4().hex[:8]
    for name in ('a', 'b'):
        auth.provision(name + suffix, 'valid-test-password', 'workspace-' + name + suffix)
    client.cookies.clear()
    try:
        assert client.post('/api/auth/login', json={'username': 'a' + suffix, 'password': 'valid-test-password'}).status_code == 200
        b, p, t = brand_setup(client)
        key = uuid4().hex
        path = '/api/agent/conversations/' + t['id']
        run = client.post(path + '/messages', json={'request_id': key, 'text': '你好', 'expected_revision': t['revision']}).json()
        wait(client, run['run_id'])
        assert client.post('/api/auth/logout').status_code == 200
        assert client.post('/api/auth/login', json={'username': 'b' + suffix, 'password': 'valid-test-password'}).status_code == 200
        assert client.get(path + '/submissions/' + key).status_code == 404
        assert client.post('/api/agent/conversations', json={'brand_id': b['id'], 'sku_id': p['id']}).status_code == 404
    finally:
        client.cookies.clear()
