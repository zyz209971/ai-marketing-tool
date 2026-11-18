"""Keep the team's documented fixture aligned with the actual deterministic tools."""
import json
from pathlib import Path
from test_marketing_agent import client, brand_setup, accept_attachment, upload_brand, message
from app.marketing_agent.business import evaluate_promotion
from app.marketing_agent.contracts import Brief, EvaluationRequest
import csv
import io


def test_documented_brand_upload_and_supplement(client):
    root=Path(__file__).resolve().parents[2]/'docs/examples/marketing-case'
    task=client.post('/api/agent/conversations',json={}).json()
    task,item=upload_brand(client,task,(root/'01-brand-incomplete.txt').read_text(encoding='utf-8'))
    assert {x['path'] for x in item['payload']['missing_fields']}=={'brand.intro','products.0.selling'}
    task=message(client,task,'品牌介绍：服务校园学生的茶饮小店；可核实的商品卖点：桂花香气与鲜奶搭配。')
    item=task['attachments'][-1]
    assert not item['payload']['missing_fields']
    task=accept_attachment(client,task,item)
    assert task['brand_name']=='山茶小站' and len(task['catalog'])==1
    assert next(iter(task['catalog'].values()))['price'] is None
    task,item=upload_brand(client,task,(root/'02-brand-complete.txt').read_text(encoding='utf-8'))
    assert not item['payload']['missing_fields']
    task=accept_attachment(client,task,item)
    assert len(task['catalog'])==1 and next(iter(task['catalog'].values()))['price']==1800


def test_documented_marketing_scenarios(client):
    root=Path(__file__).resolve().parents[2]/'docs/examples/marketing-case'
    values=json.loads((root/'03-business-values.json').read_text(encoding='utf-8'))['csv_values']
    scenarios=json.loads((root/'04-scenarios.json').read_text(encoding='utf-8'))
    brand,product,task=brand_setup(client)
    row={'product_id':product['id'],**values}
    output=io.StringIO();writer=csv.DictWriter(output,fieldnames=list(row));writer.writeheader();writer.writerow(row)
    response=client.post('/api/agent/conversations/'+task['id']+'/attachments?kind=business',files={'file':('sales.csv',output.getvalue().encode(),'text/csv')})
    assert response.status_code==201,response.text
    accept_attachment(client,task,response.json())
    for case in scenarios['cases']:
        brief=Brief(brand_id=brand['id'],sku_id=product['id'],**(scenarios['shared_brief']|case['patch']))
        result=evaluate_promotion(EvaluationRequest(brief=brief))
        assert result['status']=='ok',case['name']
        for key,value in case['expected'].items():
            assert result['result'][key]==value,(case['name'],key,result['result'][key],value)
