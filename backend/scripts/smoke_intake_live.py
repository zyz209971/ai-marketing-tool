"""Real-provider smoke test (3 calls by default; --full also exercises the marketing loop)."""
import logging
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'backend'))
from app.environment import load_environment
load_environment()
runtime = ROOT/'.local-data'/('intake-live-'+uuid4().hex[:8])
runtime.mkdir(parents=True)
os.environ.update(APP_SKIP_DOTENV='true', APP_DATA_DIR=str(runtime),
                  BRAND_DATABASE_URL='sqlite:///'+(runtime/'brand.db').as_posix(),
                  BRAND_STORAGE_DIR=str(runtime/'files'), USE_MOCK='false',
                  APP_ACCESS_KEY='', WORKSPACE_LOCAL_ONLY='false', SEED_DEMO_DATA='false')
from app.config import AGENT_USE_MOCK, USE_MOCK
if AGENT_USE_MOCK or USE_MOCK:
    raise SystemExit('Configure the text and Agent API credentials before running this live test.')
logging.disable(logging.CRITICAL)
from fastapi.testclient import TestClient
from app.main import app
from app.marketing_agent import api
app.dependency_overrides[api.require_local] = lambda: None

def main():
    with TestClient(app) as client:
        def complete_run(run_id):
            for _ in range(180):
                run=client.get('/api/agent/runs/'+run_id).json()
                if run['status'] in ('succeeded','failed'):
                    if run['status']=='failed':
                        print('Application error: '+run['error'])
                    assert run['status']=='succeeded', 'Live run failed'
                    return
                time.sleep(1)
            raise AssertionError('Live run timed out')

        def say(value):
            current=client.get(path).json()
            result=client.post(path+'/messages',json={'request_id':uuid4().hex,'text':value,'expected_revision':current['revision']})
            assert result.status_code==202
            complete_run(result.json()['run_id'])
            return client.get(path).json()

        task=client.post('/api/agent/conversations').json()
        path='/api/agent/conversations/'+task['id']
        source='品牌名称：上传测试小站（虚构）\n产品名称：桂花鲜奶茶\n价格：18元'
        r=client.post(path+'/attachments?kind=knowledge',files={'file':('brand.txt',source.encode(),'text/plain')})
        if r.status_code!=201:
            # This is our own sanitized API error, not the raw provider response.
            print('Upload status: '+str(r.status_code))
            print('Application error: '+str(r.json().get('detail','')))
            raise AssertionError('Upload failed')
        item=r.json()
        assert any(f['path']=='products.0.selling' for f in item['payload']['missing_fields']), 'Missing selling point was not retained'
        task=client.get(path).json()
        assert len(task['state']['input_request']['questions'])==2
        task=say('品牌介绍：校园花香茶饮测试品牌；这款产品的可核实卖点是桂花香气与鲜奶风味。')
        assert not task['attachments'][0]['payload']['missing_fields'], 'Required fields remain missing'
        assert not task['catalog'], 'Draft became an active fact before confirmation'
        r=client.post(path+'/attachments/'+item['id']+'/confirm',json={'expected_revision':task['revision']})
        assert r.status_code==200, f'Confirm status {r.status_code}'
        task=client.get(path).json()
        assert len(task['catalog'])==1 and next(iter(task['catalog'].values()))['price']==1800
        print('PASS: real upload extraction, missing-field question, batched natural-language supplement, confirmed brand creation')
        if '--full' in sys.argv:
            pid=next(iter(task['catalog']))
            task=say('先只写一篇小红书的桂花鲜奶茶商品介绍，不做优惠活动，不需要经营分析。')
            assert task['state']['stage']=='completed' and task['state']['artifacts'][-1]['kind']=='content','Ordinary copy path failed'
            assert not task['state']['strategy'] and not task['state']['pending_fields']
            print('PASS: real ordinary copy without ROI, dates or budget requirements',flush=True)
            csv='product_id,current_start,current_end,previous_start,previous_end,current_qty,previous_qty,variable_cost_minor,min_contribution_minor\n'+pid+',2026-11-02,2026-11-16,2026-10-19,2026-11-02,140,200,,500\n'
            result=client.post(path+'/attachments?kind=business',files={'file':('sales.csv',csv.encode(),'text/csv')})
            assert result.status_code==201
            business_item=result.json()
            task=say('6.5元')
            assert task['attachments'][-1]['payload']['rows'][0]['variable_cost_minor']==650
            result=client.post(path+'/attachments/'+business_item['id']+'/confirm',json={'expected_revision':task['revision']})
            assert result.status_code==200
            task=say('主推桂花鲜奶茶，在小红书推广。活动从2026-11-21到2026-11-22，包含这两天。预算上限200元，预计实际花费200元，假设卖出160杯，其中20组同单两杯参加第二杯半价，其余按原价，帮我测算情景ROI并制定方案。')
            assert task['state']['stage']=='awaiting_confirmation', 'Strategy not ready'
            expected={'sku_id':pid,'platform':'xiaohongshu','start_date':'2026-11-21','end_date':'2026-11-23',
                      'budget_minor':20000,'spend_minor':20000,'scenario_qty':160}
            assert all(task['state']['brief'][k]==v for k,v in expected.items()), 'Explicit activity conditions were not preserved'
            s=task['state']['strategy']
            assert s['evaluation']['result']['average_contribution_minor']==700
            result=client.post(path+'/confirm',json={'request_id':uuid4().hex,'expected_revision':task['revision'],
                                                    'strategy_id':s['id'],'strategy_version':s['version']})
            assert result.status_code==202
            complete_run(result.json()['run_id'])
            task=client.get(path).json()
            assert task['state']['stage']=='completed' and task['state']['artifacts'][-1]['body']
            print('PASS: real short-answer cost collection, tool decisions, ROI calculation, approval and copy generation')
        print('Isolated runtime: '+str(runtime))

if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        # Never print provider response bodies or credentials.
        print('FAIL: '+type(exc).__name__)
        if isinstance(exc, AssertionError):
            print('Check: '+str(exc))
        if hasattr(exc, 'status_code'):
            print('HTTP status: '+str(exc.status_code))
            body=getattr(exc, 'body', {})
            error=body.get('error', body) if isinstance(body, dict) else {}
            message=str(error.get('message','')) if isinstance(error, dict) else ''
            from app.config import WORD_API_KEY, AGENT_API_KEY
            for secret in (WORD_API_KEY, AGENT_API_KEY):
                if secret:
                    message=message.replace(secret, '[redacted]')
            print('Provider message: '+message[:400])
        raise SystemExit(1)
