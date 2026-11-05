"""Reproducible offline retrieval baseline, isolated from development data."""
import json
import os
import sys
import tempfile
from pathlib import Path


def main():
    with tempfile.TemporaryDirectory() as folder:
        os.environ['BRAND_DATABASE_URL'] = 'sqlite:///' + (Path(folder)/'eval.db').as_posix()
        os.environ['BRAND_STORAGE_DIR'] = str(Path(folder)/'files')
        os.environ['APP_DATA_DIR'] = str(Path(folder)/'data')
        os.environ['WORKSPACE_LOCAL_ONLY'] = 'false'
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from app.main import app
        from app import knowledge as kb
        client = TestClient(app)
        other = TestClient(app)
        brand=client.post('/api/knowledge/brands',json={'name':'青禾','intro':'茶饮品牌'}).json()['id']
        base='/api/knowledge/brands/'+brand
        cases=[]
        with patch('app.knowledge.rag._embedding_enabled',return_value=False):
            for name,price in [('桂花乌龙','20元'),('茉莉绿茶','16元'),('原味红茶','12元')]:
                product=client.post(base+'/products',json={'name':name,'price':price,'selling':'现泡茶底'}).json()
                for query in [name,name+'价格']:
                    results=client.get(base+'/search',params={'q':query}).json()['results']
                    rank=next((i+1 for i,r in enumerate(results) if r['document_id']=='product:'+product['id'] and price in r['text']),None)
                    cases.append({'query':query,'hit':rank is not None,'reciprocal_rank':1/rank if rank else 0})
                client.put(base+'/products/'+product['id'],json={'name':name,'price':'25元','selling':'现泡茶底'})
                latest=client.get(base+'/search',params={'q':name+'价格'}).json()['results']
                cases.append({'query':name+'更新价格','hit':bool(latest and '25元' in latest[0]['text'] and price not in latest[0]['text']),'reciprocal_rank':1 if latest and '25元' in latest[0]['text'] else 0})
            shared=other.get(base+'/search',params={'q':'桂花乌龙'}).status_code==200
        report={'cases':cases,'recall_at_4':sum(c['hit'] for c in cases)/len(cases),'mrr':sum(c['reciprocal_rank'] for c in cases)/len(cases),'shared_workspace_access':shared,'generation_evaluated':False,'note':'本基线覆盖精确产品检索、改价和共享访问；未评估真实模型幻觉率、模糊召回或向量检索质量。'}
        print(json.dumps(report,ensure_ascii=False,indent=2))
        client.close();other.close();kb.engine.dispose()
        if not shared or not all(c['hit'] for c in cases):
            raise SystemExit(1)


if __name__=='__main__':
    main()
