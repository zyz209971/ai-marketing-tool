"""Live smoke for natural-language brand setup and the independent unit-cost path."""
import logging
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from app.environment import load_environment
load_environment()
runtime=ROOT/'.local-data'/('paths-live-'+uuid4().hex[:8]);runtime.mkdir()
os.environ.update(APP_SKIP_DOTENV='true',APP_DATA_DIR=str(runtime),BRAND_DATABASE_URL='sqlite:///'+(runtime/'brand.db').as_posix(),
    BRAND_STORAGE_DIR=str(runtime/'files'),USE_MOCK='false',APP_ACCESS_KEY='',WORKSPACE_LOCAL_ONLY='false',SEED_DEMO_DATA='false')
logging.disable(logging.CRITICAL)
from app.config import AGENT_USE_MOCK,USE_MOCK
if AGENT_USE_MOCK or USE_MOCK:raise SystemExit('Real text and Agent credentials are required.')
from fastapi.testclient import TestClient
from app.main import app
from app.marketing_agent import api
app.dependency_overrides[api.require_local]=lambda:None


def main():
    with TestClient(app) as c:
        t=c.post('/api/agent/conversations',json={}).json();path='/api/agent/conversations/'+t['id']
        def say(message):
            current=c.get(path).json()
            r=c.post(path+'/messages',json={'request_id':uuid4().hex,'expected_revision':current['revision'],'text':message})
            assert r.status_code==202
            for _ in range(240):
                run=c.get('/api/agent/runs/'+r.json()['run_id']).json()
                if run['status']=='failed':raise AssertionError('Application run failed: '+run['error'])
                if run['status']=='succeeded':return c.get(path).json()
                time.sleep(1)
            raise AssertionError('Run timed out')
        t=say('我的茶饮店叫山茶小站，是一家面向大学生的校园茶饮品牌。请帮我写一篇微信公众号的品牌介绍文案。')
        item=t['attachments'][-1]
        assert not item['payload']['missing_fields'],'Brand facts were not fully extracted'
        assert not t['catalog']
        r=c.post(path+'/attachments/'+item['id']+'/confirm',json={'expected_revision':t['revision']})
        assert r.status_code==200
        t=c.get(path).json()
        assert t['state']['stage']=='completed' and t['state']['artifacts'][-1]['kind']=='content','Original brand-copy request did not resume'
        assert len(t['attachments'])==1 and not t['state'].get('active_attachment_id')
        assert not t['state']['strategy'] and not t['catalog']
        print('PASS: natural brand facts -> draft -> approval -> original brand copy request resumed without invented products',flush=True)
        p=c.post('/api/knowledge/brands/'+t['state']['brief']['brand_id']+'/products',json={'name':'桂花鲜奶茶','spec':'500ml','price':'18元','selling':'桂花香气与鲜奶风味'})
        assert p.status_code==201
        t=say('我只想检查桂花鲜奶茶第二杯半价的单位收益。单杯成本6.5元，没有最低贡献标准，先只展示计算结果。')
        assert t['state']['brief']['task_kind']=='unit_economics' and t['state']['stage']=='completed'
        result=t['state']['unit_result']['result']
        assert result['average_contribution_minor']==700 and result['feasible'] is None
        assert not t['state']['pending_fields'] and not t['state']['strategy']
        print('PASS: real unit-cost intent, known cost, unknown minimum, no campaign-form questions',flush=True)
        print('Isolated runtime: '+str(runtime))


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('FAIL: '+type(exc).__name__)
        if isinstance(exc,AssertionError):print(str(exc))
        raise SystemExit(1)
