"""Round two: actual offline paths, not real model quality assertions."""
import pytest
from test_marketing_agent import client, brand_setup, message, upload_brand
from app.marketing_agent import model


def ordinary(client):
    b,p,t=brand_setup(client)
    t=message(client,t,'写普通商品介绍',fields={'task_kind':'content','sku_id':p['id'],'platform':'xiaohongshu'})
    assert t['state']['stage']=='completed'
    return b,p,t


def test_brand_inline_sentence_extracts_explicit_facts_without_inventing_position(client):
    t=client.post('/api/agent/conversations',json={}).json()
    text='我要建立一个测试品牌。品牌名称：验收测试茶铺1122；品牌介绍：一家面向大学生的单门店茶饮店，主要提供自提服务，表达风格自然、简洁。先不要生成营销文案，也不要创建促销活动。'
    t=message(client,t,text)
    candidate=t['attachments'][-1]['payload']['preview']['brand_candidate']
    assert candidate['name']=='验收测试茶铺1122'
    assert '面向大学生' in candidate['intro'] and '自提服务' in candidate['intro']
    assert '不要' not in candidate['intro']
    assert candidate['style']=='自然、简洁'
    assert not candidate.get('position')
    assert not t['state']['artifacts']
    assert not t['attachments'][-1]['payload']['missing_fields']


def test_line_and_inline_product_facts_keep_product_boundaries(client):
    _,_,t=brand_setup(client)
    text='品牌名称：测试茶铺\n品牌介绍：茶饮自提\n表达风格：简洁\n产品名称：桂花茶；规格：500mL；价格：18元；卖点：桂花风味\n产品名称：红茶；规格：300mL；价格：12元；卖点：红茶茶底'
    t,item=upload_brand(client,t,text)
    products=item['payload']['preview']['product_candidates']
    assert [(p['name'],p.get('spec'),p['price']) for p in products]==[('桂花茶','500mL','18元'),('红茶','300mL','12元')]


def test_unit_request_does_not_collect_campaign_fields(client):
    _,p,t=brand_setup(client)
    t=message(client,t,f'帮我检查{p["name"]}的第二杯半价：原价每杯18元，单杯变动成本8元，同一订单同款两杯，不叠加其他优惠。暂不设最低贡献标准，只展示两杯的收入、变动成本和贡献收益，不生成营销文案。')
    s=t['state'];assert s['brief']['task_kind']=='unit_economics'
    assert s['stage']=='completed' and not s['pending_fields'] and not s['artifacts']
    u=s['unit_result']['result']
    assert (u['pair_revenue_minor'],u['pair_variable_cost_minor'],u['pair_contribution_minor'],u['average_contribution_minor'])==(2700,1600,1100,550)
    assert u['feasible'] is None
    assert not any(m.get('sales') for m in s['messages'])


@pytest.mark.parametrize('answer',['单杯变动成本：8元。','单杯成本8元','每杯成本：8元','8元'])
def test_cost_followup_uses_page_wording(client,answer):
    _,p,t=brand_setup(client)
    t=message(client,t,'只检查第二杯半价，不设最低贡献标准',fields={'task_kind':'unit_economics','sku_id':p['id'],'offer':{'type':'second_cup_discount','pay_bps':5000},'assess_minimum':False})
    assert 'variable_cost_override_minor' in t['state']['pending_fields']
    t=message(client,t,answer)
    assert t['state']['brief']['variable_cost_override_minor']==800
    assert t['state']['stage']=='completed'


@pytest.mark.parametrize('text',['单杯变动成本：-8元','单杯成本8.123元','每杯成本8到10元','单杯成本大概8元'])
def test_ambiguous_or_invalid_cost_is_not_silently_parsed(text):
    assert 'variable_cost_override_minor' not in model.demo_patch(text,'variable_cost_override_minor',{})


def test_exact_title_edit_changes_only_title_and_archived_work(client):
    b,_,t=ordinary(client);before=t['state']['artifacts'][-1];style=t['state']['brief']['style']
    t=message(client,t,'只把标题改成“桂花遇见乌龙，日常一杯茶”。正文保持不变，不新增价格、优惠或商品特点。')
    after=t['state']['artifacts'][-1]
    assert after['title']=='桂花遇见乌龙，日常一杯茶'
    for key in ('body','summary','hashtags','locked_terms'):assert after[key]==before[key]
    assert after['parent_artifact_id']==before['id'] and after['version']==before['version']+1
    assert t['state']['brief']['style']==style
    works=client.get('/api/knowledge/workspace').json()['works']
    work=next(w for w in works if w.get('agent_origin',{}).get('artifact_id')==after['id'])
    assert work['result']['title']==after['title']
    from app.marketing_agent.data import context
    assert context(t['state']['brief'])['memories']==[]


def test_identical_title_does_not_make_a_new_success_version(client):
    _,_,t=ordinary(client);before=t['state']['artifacts'][-1]
    t=message(client,t,'只把标题改成“'+before['title']+'”，正文保持不变。')
    assert t['state']['artifacts'][-1]['id']==before['id']
    assert '无需修改' in t['state']['reply']


def test_unsupported_title_edit_does_not_claim_success(client):
    _,_,t=ordinary(client);before=t['state']['artifacts'][-1]
    t=message(client,t,'只把标题改得像雨后散步的感觉，正文保持不变。')
    assert t['state']['artifacts'][-1]['id']==before['id']
    assert '离线' in t['state']['reply'] and '标题' in t['state']['reply']


def test_concrete_title_with_tone_word_is_not_a_style_candidate(client):
    _,_,t=ordinary(client);style=t['state']['brief']['style']
    t=message(client,t,'只把标题改为“温柔的一杯茶”，正文不变。')
    assert t['state']['artifacts'][-1]['title']=='温柔的一杯茶'
    assert t['state']['brief']['style']==style


def test_campaign_and_reusable_style_remain_supported(client):
    patch=model.demo_patch('制定下周促销方案，预算200元',None,{})
    assert patch['task_kind']=='campaign' and patch['budget_minor']==20000
    _,_,t=ordinary(client);t=message(client,t,'语气简短一点')
    assert '简短' in t['state']['brief']['style']
    assert '欢迎到店' in t['state']['artifacts'][-1]['body']


@pytest.mark.parametrize('value,expected',[('单杯变动成本：0元。',0),('每杯变动成本: 8.25元',825),('单杯成本8元；每杯成本9元',None)])
def test_cost_zero_decimal_and_conflicting_values(value,expected):
    result=model.demo_patch(value,'variable_cost_override_minor',{})
    assert result.get('variable_cost_override_minor')==expected


def test_conflicting_brand_name_stays_missing(client):
    t=client.post('/api/agent/conversations',json={}).json()
    t,item=upload_brand(client,t,'品牌名称：甲店；品牌名称：乙店；品牌介绍：茶饮自提')
    assert 'brand.name' in {x['path'] for x in item['payload']['missing_fields']}


def test_literal_title_does_not_switch_offer_or_platform(client):
    _,_,t=ordinary(client)
    t=message(client,t,'只把标题改成“小红书里的温柔茶香”，正文不变。')
    assert t['state']['artifacts'][-1]['title']=='小红书里的温柔茶香'
    assert t['state']['brief']['style']=='自然、简洁，不夸大功效'
    before=t['state']['artifacts'][-1]
    t=message(client,t,'只把标题改成“第二杯半价”，正文不变。')
    assert t['state']['artifacts'][-1]['id']==before['id']
    assert t['state']['brief']['offer'] is None
    assert '离线' in t['state']['reply']


def test_only_numbers_do_not_require_a_minimum(client):
    _,p,t=brand_setup(client)
    t=message(client,t,p['name']+'第二杯半价，单杯成本8元，只计算两杯收入和成本，不生成文案。')
    assert t['state']['stage']=='completed'
    assert t['state']['unit_result']['result']['feasible'] is None


def test_suggested_title_colon_syntax_is_usable(client):
    _,_,t=ordinary(client)
    t=message(client,t,'只把标题改为：桂花遇见乌龙，日常一杯茶。正文保持不变。')
    assert t['state']['artifacts'][-1]['title']=='桂花遇见乌龙，日常一杯茶'


def test_ambiguous_multi_product_supplement_does_not_fill_every_row():
    from app.marketing_agent import intake
    item={'kind':'knowledge','payload':{'preview':{'brand_candidate':{},'product_candidates':[
        {'name':'乌龙茶','spec':'500mL','selling':''},{'name':'乌龙茶','spec':'300mL','selling':''}]}}}
    updates=intake.extract_updates(item,'卖点：茶香',[])
    assert not any(x.path.startswith('products.') for x in updates)
    updates=intake.extract_updates(item,'乌龙茶500mL的卖点：茶香',[])
    assert [x.path for x in updates]==['products.0.selling']
