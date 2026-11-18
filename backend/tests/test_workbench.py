from test_marketing_agent import client, brand_setup, message


def test_conversation_summaries_filter_brand_and_search_with_pagination(client):
    b,p,t=brand_setup(client)
    other,_,other_task=brand_setup(client)
    t=message(client,t,'独特文案检索词',fields={'task_kind':'content','sku_id':p['id'],'platform':'xiaohongshu'})
    result=client.get('/api/agent/conversations',params={'brand_id':b['id'],'q':'独特文案检索词','limit':1}).json()
    assert len(result['conversations'])==1
    row=result['conversations'][0]
    assert row['id']==t['id'] and row['brand_id']==b['id'] and row['brand_name']==b['name']
    assert row['task_kind']=='content' and not row['active_run'] and result['has_more'] is False
    assert not client.get('/api/agent/conversations',params={'brand_id':other['id'],'q':'独特文案检索词'}).json()['conversations']
    assert not client.get('/api/agent/conversations',params={'brand_id':b['id'],'offset':1}).json()['conversations']


def test_conversation_page_bounds(client):
    assert client.get('/api/agent/conversations?limit=0').status_code==422
    assert client.get('/api/agent/conversations?offset=-1').status_code==422


def test_conversation_page_has_more_and_offsets(client):
    b,_,t=brand_setup(client)
    newer=client.post('/api/agent/conversations',json={'brand_id':b['id']}).json()
    first=client.get('/api/agent/conversations',params={'brand_id':b['id'],'limit':1}).json()
    second=client.get('/api/agent/conversations',params={'brand_id':b['id'],'limit':1,'offset':1}).json()
    assert first['has_more'] and not second['has_more']
    assert {first['conversations'][0]['id'],second['conversations'][0]['id']}=={t['id'],newer['id']}
