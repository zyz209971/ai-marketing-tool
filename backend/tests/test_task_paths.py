"""Feature 003 acceptance; shares the isolated marketing test runtime."""
from test_marketing_agent import client, message, wait, brand_setup, upload_brand, accept_attachment, complete
from app.marketing_agent import business
from app.marketing_agent.contracts import Brief, EvaluationRequest
from uuid import uuid4
import pytest


def test_original_price_offer_default_and_invalid_discount():
    from app.marketing_agent.contracts import Offer
    assert Offer(type='none').pay_bps==10000
    with pytest.raises(ValueError):Offer(type='none',pay_bps=5000)


def test_new_user_is_guided_to_upload_without_demo_data(client):
    t=client.post('/api/agent/conversations',json={}).json()
    t=message(client,t,'我第一次使用，想为自己的品牌建立知识库')
    assert t['catalog']=={}
    assert not t['state']['tool_results']
    assert '上传' in t['state']['reply']
    assert not t['state'].get('demo_mode')


def test_brand_only_file_does_not_invent_required_product(client):
    t=client.post('/api/agent/conversations',json={}).json()
    t,item=upload_brand(client,t,'品牌名称：山茶小站\n品牌介绍：校园茶饮品牌')
    assert not item['payload']['missing_fields']
    t=accept_attachment(client,t,item)
    assert t['brand_name']=='山茶小站' and not t['catalog']


def test_plain_content_uses_no_roi_and_is_archived(client):
    b,p,t=brand_setup(client)
    t=message(client,t,'只写一篇小红书商品介绍，不做优惠活动',fields={'task_kind':'content','sku_id':p['id'],'platform':'xiaohongshu'})
    assert t['state']['stage']=='completed'
    assert not t['state']['strategy'] and not t['state']['pending_fields']
    artifact=t['state']['artifacts'][-1]
    assert artifact['kind']=='content' and not artifact['locked_terms']
    works=client.get('/api/knowledge/workspace').json()['works']
    work=next(w for w in works if w.get('agent_origin',{}).get('artifact_id')==artifact['id'])
    assert work['brand']==b['id'] and work['agent_origin']['task_id']==t['id']


def test_unit_check_needs_no_platform_dates_or_budget(client):
    b,p,t=brand_setup(client)
    t=message(client,t,'只检查第二杯半价是否满足成本',fields={
        'task_kind':'unit_economics','sku_id':p['id'],'offer':{'type':'second_cup_discount','pay_bps':5000},
        'variable_cost_override_minor':650,'min_contribution_override_minor':500})
    assert t['state']['stage']=='completed' and not t['state']['strategy']
    assert t['state']['unit_result']['result']['average_contribution_minor']==700


def test_unknown_minimum_can_show_unit_result_without_claiming_pass(client):
    b,p,t=brand_setup(client)
    t=message(client,t,'没有最低收益标准，先只展示计算结果',fields={'task_kind':'unit_economics','sku_id':p['id'],
        'offer':{'type':'second_cup_discount','pay_bps':5000},'variable_cost_override_minor':650,'assess_minimum':False})
    r=t['state']['unit_result']['result']
    assert r['average_contribution_minor']==700 and r['feasible'] is None


def test_promotion_uses_explicit_pairs_not_aggregate_pairing():
    b=Brief(**{**complete(),'promotion_pairs':20})
    r=business.evaluate_promotion(EvaluationRequest(brief=b))['result']
    # 160 cups, 20 discounted cups, 140 full-price cups; demo price is 16 yuan.
    assert r['scenario_revenue_minor']==140*1600+20*800
    with pytest.raises(ValueError):Brief(**{**complete(),'promotion_pairs':81})
    r=business.evaluate_promotion(EvaluationRequest(brief=Brief(**{**complete(),'promotion_pairs':None})))
    assert any(m['path']=='promotion_pairs' for m in r['missing_fields'])
    assert r['result'].get('incremental_roi') is None


def test_changed_price_requires_conflict_acceptance(client):
    b,p,t=brand_setup(client)
    t,item=upload_brand(client,t,'产品名称：桂花鲜奶茶\n价格：20元\n卖点：桂花香气')
    conflicts=item['payload']['conflicts'];assert any(c['field']=='price' for c in conflicts)
    path='/api/agent/conversations/'+t['id']+'/attachments/'+item['id']+'/confirm'
    rejected=client.post(path,json={'expected_revision':t['revision']})
    assert rejected.status_code==409
    r=client.post(path,json={'expected_revision':t['revision'],'accepted_conflicts':[c['id'] for c in conflicts]})
    assert r.status_code==200,r.text
    events=client.get('/api/knowledge/brands/'+b['id']+'/fact-history').json()['events']
    assert events and events[0]['payload']['status']=='user_confirmed'


def test_variants_need_spec_and_preserve_other_variant(client):
    b,p,t=brand_setup(client)
    client.put('/api/knowledge/brands/'+b['id']+'/products/'+p['id'],json={'name':p['name'],'spec':'500ml','price':'18元','selling':'桂花香气'})
    p2=client.post('/api/knowledge/brands/'+b['id']+'/products',json={'name':p['name'],'spec':'700ml','price':'22元','selling':'桂花香气'}).json()
    t,item=upload_brand(client,t,'产品名称：桂花鲜奶茶\n价格：19元\n卖点：桂花香气')
    assert any(x['path']=='products.0.spec' for x in item['payload']['missing_fields'])
    t=message(client,t,'商品规格：500ml')
    item=next(a for a in t['attachments'] if a['id']==item['id'])
    t=accept_attachment(client,t,item)
    assert t['catalog'][p['id']]['price']==1900
    assert t['catalog'][p2['id']]['price']==2200
    assert t['catalog'][p['id']]['price_confirmed_at']


def test_price_optional_for_copy_but_blocks_calculation(client):
    t=client.post('/api/agent/conversations',json={}).json()
    t,item=upload_brand(client,t,'品牌名称：无价格测试\n品牌介绍：校园茶饮\n产品名称：桂花茶\n卖点：桂花香气')
    t=accept_attachment(client,t,item);pid=next(iter(t['catalog']))
    t=message(client,t,'小红书商品介绍',fields={'task_kind':'content','sku_id':pid,'platform':'xiaohongshu'})
    assert t['state']['artifacts'] and not t['state']['strategy']
    t=message(client,t,'只检查第二杯半价成本',fields={'task_kind':'unit_economics','offer':{'type':'second_cup_discount','pay_bps':5000}})
    assert 'products.0.price' in t['state']['pending_fields']
    t=message(client,t,'单杯售价：18元')
    t=accept_attachment(client,t,t['attachments'][-1])
    assert t['catalog'][pid]['price']==1800


def test_archive_revision_is_protected_and_keeps_parent(client):
    b,p,t=brand_setup(client)
    t=message(client,t,'小红书商品介绍',fields={'task_kind':'content','sku_id':p['id'],'platform':'xiaohongshu'})
    first=t['state']['artifacts'][-1]
    t=message(client,t,'只改标题，活泼一点')
    latest=t['state']['artifacts'][-1]
    assert latest['parent_artifact_id']==first['id'] and latest['body']==first['body']
    w=client.get('/api/knowledge/workspace').json()
    found=next(x for x in w['works'] if x['id']==latest['id'])
    found['result']['body']='tampered'
    assert client.post('/api/knowledge/workspace/sync',json=w).status_code==200
    saved=next(x for x in client.get('/api/knowledge/workspace').json()['works'] if x['id']==latest['id'])
    assert saved['result']['body']==latest['body']


def test_chat_can_create_brand_draft(client):
    t=client.post('/api/agent/conversations',json={}).json()
    t=message(client,t,'品牌名称：对话小站\n品牌介绍：校园茶饮')
    assert t['attachments'] and t['state']['brand_setup_pending']
    t=accept_attachment(client,t,t['attachments'][0])
    assert t['brand_name']=='对话小站'
    assert not t['state'].get('active_attachment_id') and len(t['attachments'])==1


def test_archive_and_chat_show_external_fact_change_as_stale(client):
    b,p,t=brand_setup(client)
    t=message(client,t,'小红书商品介绍',fields={'task_kind':'content','sku_id':p['id'],'platform':'xiaohongshu'})
    a=t['state']['artifacts'][-1]
    client.put('/api/knowledge/brands/'+b['id']+'/products/'+p['id'],json={'name':p['name'],'price':'20元','selling':'桂花香气'})
    assert client.get('/api/agent/conversations/'+t['id']).json()['state']['artifacts'][-1]['stale']
    archived=next(w for w in client.get('/api/knowledge/workspace').json()['works'] if w['id']==a['id'])
    assert archived['agent_origin']['stale']


def test_unconfirmed_new_brand_cannot_generate_after_pausing_intake(client):
    t=client.post('/api/agent/conversations',json={}).json()
    t,item=upload_brand(client,t,'品牌名称：草稿品牌\n品牌介绍：校园茶饮')
    t=message(client,t,'先暂停补资料')
    t=message(client,t,'帮我写品牌介绍文案',fields={'task_kind':'content','content_scope':'brand','platform':'xiaohongshu'})
    assert not t['state']['artifacts'] and not t['state']['tool_results']
    assert '待确认草稿' in t['state']['reply']
