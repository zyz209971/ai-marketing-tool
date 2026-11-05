import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

tempdir = tempfile.TemporaryDirectory()
os.environ['BRAND_DATABASE_URL'] = 'sqlite:///' + (Path(tempdir.name) / 'test.db').as_posix()
os.environ['BRAND_STORAGE_DIR'] = str(Path(tempdir.name) / 'files')
os.environ['APP_DATA_DIR'] = str(Path(tempdir.name)/'runtime')
os.environ['WORKSPACE_LOCAL_ONLY'] = 'false'
os.environ['QUOTA_PER_USER'] = '10000'
os.environ['QUOTA_TOTAL'] = '100000'
os.environ['USE_MOCK'] = 'true'
os.environ['APP_ACCESS_KEY'] = ''
os.environ['EMBED_API_KEY'] = ''
os.environ['EMBED_MODEL'] = ''

from fastapi.testclient import TestClient
from app.main import app
from app import knowledge

def tearDownModule():
    knowledge.engine.dispose()
    tempdir.cleanup()


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        from uuid import uuid4
        self.client = TestClient(app)
        self.other = TestClient(app)
        self.username = uuid4().hex
        r = self.client.post('/api/knowledge/brands', json={'name': '青禾', 'intro': '一家茶饮品牌'})
        self.assertEqual(r.status_code, 201)
        self.brand = r.json()['id']
        self.path = '/api/knowledge/brands/' + self.brand

    def test_confirm_version_shared_access_and_deletion(self):
        response = self.client.post(self.path+'/documents', files={'file': ('brand.txt', '青禾品牌的桂花乌龙采用乌龙茶底，提供清香口感。'.encode(), 'text/plain')})
        self.assertEqual(response.status_code, 201)
        doc, version = response.json()['id'], response.json()['version_id']
        base = self.path+'/documents/'+doc+'/versions/'+version
        self.assertEqual(self.client.get(base).json()['version']['status'], 'pending_confirmation')
        self.assertEqual(self.client.get(self.path+'/search', params={'q': '桂花乌龙'}).json()['results'], [])
        self.assertEqual(self.other.get(self.path+'/documents').status_code, 200)
        self.assertEqual(self.client.post(base+'/confirm').status_code, 200)
        self.assertTrue(self.client.get(self.path+'/search', params={'q': '桂花乌龙'}).json()['results'])
        update = self.client.post(self.path+'/documents?document_id='+doc, files={'file': ('bad.txt', b'\xff\xfe', 'text/plain')}).json()
        bad = self.path+'/documents/'+doc+'/versions/'+update['version_id']
        self.assertEqual(self.client.get(bad).json()['version']['status'], 'failed')
        self.assertTrue(self.client.get(self.path+'/search', params={'q': '桂花乌龙'}).json()['results'])
        self.assertEqual(self.client.delete(self.path+'/documents/'+doc).status_code, 200)
        self.assertEqual(self.client.get(self.path+'/search', params={'q': '桂花乌龙'}).json()['results'], [])

    def test_authoritative_product_and_generation(self):
        product = self.client.post(self.path+'/products', json={'name': '桂花乌龙', 'selling': '清香、茶底', 'price': '18元'}).json()
        payload = {'brand': {'id': self.brand, 'name': '伪造品牌', 'description': '伪造介绍'}, 'marketing_goal': 'new_product', 'products': [{'id': product['id'], 'name': '伪造产品', 'selling_points': ['伪造'], 'price': '1元'}], 'platforms': ['xiaohongshu']}
        with patch('app.providers.campaign.generate', return_value=[]) as gen:
            response = self.client.post('/api/v2/copywriting', json=payload, headers={'X-Visitor-Id': self.username})
        self.assertEqual(response.status_code, 200)
        used = gen.call_args.args[0]
        self.assertEqual(used['brand']['name'], '青禾')
        self.assertEqual(used['products'][0]['price'], '18元')
        self.assertEqual(self.other.post('/api/v2/copywriting', json=payload).status_code, 200)

    def test_no_user_verification_endpoints(self):
        from sqlalchemy import inspect
        self.assertEqual(TestClient(app).get('/api/knowledge/brands').status_code,200)
        self.assertEqual(self.client.post('/api/knowledge/brands',headers={'Origin':'https://evil.example'},json={'name':'X','intro':'Y'}).status_code,403)
        for path in ('register','login','logout','phone/code','phone/login','phone/bind','invitations/accept'):
            self.assertIn(self.client.post('/api/knowledge/'+path,json={}).status_code,(404,405))
        for path in ('me','auth/options'):
            self.assertEqual(self.client.get('/api/knowledge/'+path).status_code,404)
        self.assertFalse({'kb_users','kb_sessions','kb_members','kb_identities'} & set(inspect(knowledge.engine).get_table_names()))
        self.assertNotIn('set-cookie',self.client.get('/api/knowledge/workspace').headers)
        self.assertFalse(self.client.cookies)

    def test_workspace_server_roundtrip(self):
        revision = self.client.get('/api/knowledge/workspace').json()['revision']
        workspace = {'revision': revision, 'brands': [{'id': self.brand, 'name': '青禾', 'intro': '茶饮', 'preference': '亲切'}], 'products': [{'id': 'product-'+self.username, 'brand': self.brand, 'name': '产品', 'selling': '好喝'}], 'works': [{'id': 'work-'+self.username, 'brand': self.brand, 'result': {'title': '标题'}}]}
        self.assertEqual(self.client.post('/api/knowledge/workspace/sync', json=workspace).status_code, 200)
        data = self.client.get('/api/knowledge/workspace').json()
        self.assertEqual(next(b for b in data['brands'] if b['id']==self.brand)['preference'], '亲切')
        self.assertEqual(len([p for p in data['products'] if p['brand']==self.brand]), 1)
        self.assertEqual(next(w for w in data['works'] if w['brand']==self.brand)['result']['title'], '标题')
        self.assertEqual(self.client.post('/api/knowledge/workspace/sync', json=workspace).status_code, 409)
        workspace['revision'] = self.other.get('/api/knowledge/workspace').json()['revision']
        self.assertEqual(self.other.post('/api/knowledge/workspace/sync', json=workspace).status_code, 200)

    def test_csv_products_require_confirmation(self):
        content = '产品名,价格,卖点\n茉莉茶,12元,花香清新\n'.encode('utf-8')
        response = self.client.post(self.path+'/documents', files={'file': ('products.csv', content, 'text/csv')}).json()
        base = self.path+'/documents/'+response['id']+'/versions/'+response['version_id']
        preview = self.client.get(base).json()
        self.assertEqual(preview['product_candidates'][0]['price'], '12元')
        self.assertEqual(self.client.get(self.path+'/products').json()['products'], [])
        result = self.client.post(base+'/confirm', json={'products': [{'name': '茉莉茶', 'price': '13元', 'selling': '已确认花香'}]})
        self.assertEqual(result.json()['imported_products'], 1)
        self.assertEqual(self.client.get(self.path+'/products').json()['products'][0]['price'], '13元')

    def test_vector_index_and_source_in_generation(self):
        with patch('app.knowledge.rag._embedding_enabled', return_value=True), patch('app.knowledge.rag._embed_many', return_value=[[1.0, 0.0]]), patch('app.knowledge.rag._embed_query', return_value=(1.0, 0.0)), patch('app.knowledge.rag.EMBED_MODEL', 'test-embedding'):
            doc = self.client.post(self.path+'/documents', files={'file': ('brand.txt', '品牌使用桂花乌龙茶底，主打清新的植物香气。'.encode(), 'text/plain')}).json()
            base = self.path+'/documents/'+doc['id']+'/versions/'+doc['version_id']
            self.assertEqual(self.client.post(base+'/confirm').status_code, 200)
            self.assertEqual(self.client.get(self.path+'/search', params={'q': '植物香气'}).json()['results'][0]['document_id'], doc['id'])
            payload = {'brand': {'id': self.brand, 'name': '青禾', 'description': '茶饮'}, 'marketing_goal': 'brand_awareness', 'theme': '植物香气', 'products': [], 'platforms': ['xiaohongshu']}
            with patch('app.providers.campaign.generate', return_value=[]) as gen:
                self.assertEqual(self.client.post('/api/v2/copywriting', json=payload, headers={'X-Visitor-Id': self.username}).status_code, 200)
            self.assertEqual(gen.call_args.args[0]['brand_references'][0]['document_id'], doc['id'])

    def test_uploaded_image_shared_access(self):
        png = b'\x89PNG\r\n\x1a\n' + b'test'
        response = self.client.post(self.path+'/documents', files={'file': ('product.png', png, 'image/png')})
        self.assertEqual(response.status_code, 201)
        url = self.path+'/documents/'+response.json()['id']+'/file'
        self.assertEqual(self.other.get(url).status_code, 200)
        self.assertEqual(self.client.get(url).headers['content-type'], 'image/png')

    def test_product_search_in_shared_workspace(self):
        self.client.post(self.path+'/products', json={'name': '独家商品', 'selling': '特殊风味'})
        payload = {'client_brand_id': self.brand, 'query': '独家商品'}
        with patch('app.v2.rag.search_products', return_value=[]):
            own = self.client.post('/api/v2/products/search', json=payload)
            other = self.other.post('/api/v2/products/search', json=payload)
        self.assertEqual(own.status_code, 200)
        self.assertEqual(own.json()['products'][0]['name'], '独家商品')
        self.assertEqual(other.status_code, 200)


class StudioTests(unittest.TestCase):
    setUp = KnowledgeTests.setUp

    def test_knowledge_documents_exclude_product_photos_and_support_filters(self):
        photo=self.client.post(self.path+'/documents?purpose=product_image', files={'file':('product.png',b'\x89PNG\r\n\x1a\ntest','image/png')}).json()
        for i in range(12):
            response=self.client.post(self.path+'/documents?category=活动规则',files={'file':(f'campaign-{i}.txt','活动仅限周末'.encode(),'text/plain')})
            self.assertEqual(response.status_code,201)
        first=self.client.get(self.path+'/documents',params={'purpose':'knowledge','page_size':10}).json()
        self.assertEqual(first['total'],12)
        self.assertEqual(len(first['documents']),10)
        self.assertEqual(first['pages'],2)
        second=self.client.get(self.path+'/documents',params={'purpose':'knowledge','page':2,'page_size':10}).json()
        self.assertEqual(len(second['documents']),2)
        self.assertNotIn(photo['id'],[r['id'] for r in first['documents']+second['documents']])
        self.assertEqual(self.client.get(self.path+'/documents',params={'purpose':'knowledge','category':'产品说明'}).json()['total'],0)
        self.assertEqual(self.client.get(self.path+'/documents',params={'purpose':'knowledge','q':'campaign-11'}).json()['total'],1)
        self.assertEqual(self.other.get(self.path+'/documents?purpose=knowledge').status_code,200)
        self.assertEqual(self.client.get(self.path+'/documents?page_size=1000').status_code,422)

    def test_product_lifecycle_current_price_and_memory(self):
        product = self.client.post(self.path+'/products', json={'name':'桂花乌龙','selling':'花香','price':'18元','category':'茶饮'}).json()
        self.client.put(self.path+'/products/'+product['id'], json={'name':'桂花乌龙','selling':'花香','price':'20元','category':'茶饮'})
        found = self.client.get(self.path+'/search', params={'q':'桂花乌龙价格'}).json()['results']
        self.assertIn('20元', found[0]['text'])
        self.assertNotIn('18元', found[0]['text'])
        memory = self.client.post(self.path+'/memories', json={'kind':'prohibited','content':'不要声称治疗疾病'}).json()
        self.assertEqual(len(self.client.get(self.path+'/memories').json()['memories']), 1)
        self.assertEqual(self.other.get(self.path+'/memories').status_code, 200)
        self.client.delete(self.path+'/memories/'+memory['id'])
        self.assertEqual(self.client.get(self.path+'/memories').json()['memories'], [])
        self.client.put(self.path+'/products/'+product['id'], json={'name':'桂花乌龙','selling':'花香','archived':True})
        self.assertEqual(self.client.get(self.path+'/search', params={'q':'桂花乌龙'}).json()['results'], [])

    def test_draft_version_and_shared_access(self):
        draft = {'revision':0,'payload':{'view':'create','note':'未完成的活动'}}
        self.assertEqual(self.client.put(self.path+'/draft', json=draft).status_code, 200)
        self.assertEqual(self.client.put(self.path+'/draft', json=draft).status_code, 409)
        self.assertEqual(self.other.get(self.path+'/draft').status_code, 200)
        self.assertEqual(self.client.get(self.path+'/draft').json()['payload']['note'],'未完成的活动')

    def test_organization_requires_confirmation_and_updates_product(self):
        from app import organization
        doc = self.client.post(self.path+'/documents', files={'file':('brand.txt','品牌名称：新品牌\n品牌介绍：自然茶饮\n产品名称：乌龙茶\n价格：20元\n卖点：清香'.encode(),'text/plain')}).json()
        with patch('app.organization.USE_MOCK', True):
            organization.analyze(self.brand, doc['version_id'], self.client.get('/api/knowledge/workspace-info').json()['id'])
        self.assertEqual(self.client.get(self.path+'/products').json()['products'], [])
        base = self.path+'/documents/'+doc['id']+'/versions/'+doc['version_id']
        preview = self.client.get(base).json()
        self.assertEqual(preview['brand_candidate']['name'],'新品牌')
        self.assertEqual(self.client.post(base+'/confirm', json={'products':preview['product_candidates']}).status_code,200)
        self.assertEqual(self.client.post(base+'/confirm').status_code,409)
        self.assertEqual(self.client.get(self.path+'/products').json()['products'][0]['price'],'20元')

    def test_photo_gallery_assets_and_export(self):
        import io, zipfile
        from PIL import Image
        from app import materials
        raw = io.BytesIO()
        Image.new('RGB',(200,300),'green').save(raw,'PNG')
        doc = self.client.post(self.path+'/documents', files={'file':('product.png',raw.getvalue(),'image/png')}).json()
        product = self.client.post(self.path+'/products', json={'name':'乌龙茶','selling':'茶香','price':'20元','image_document_id':doc['id']}).json()
        user = self.client.get('/api/knowledge/workspace-info').json()['id']
        gallery = materials.photo_gallery(self.brand,user,{'title':'茶饮新品','platform':'xiaohongshu'},[product['id']],3)
        self.assertEqual(len(gallery['gallery']),3)
        self.assertEqual(self.client.get(gallery['image']['url']).status_code,200)
        self.assertEqual(self.other.get(gallery['image']['url']).status_code,200)
        workspace = self.client.get('/api/knowledge/workspace').json()
        workspace['works']=[{'id':'export-'+self.username,'brand':self.brand,'result':{'title':'<script>alert(1)</script>','body':'正文','gallery':gallery['gallery']}}]
        self.assertEqual(self.client.post('/api/knowledge/workspace/sync',json=workspace).status_code,200)
        exported = self.client.get(self.path+'/works/export-'+self.username+'/export')
        self.assertEqual(exported.status_code,200)
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            self.assertEqual(len([n for n in archive.namelist() if n.endswith('.png')]),3)
            self.assertNotIn('<script>',archive.read('文章.html').decode())

    def test_job_idempotency_and_restart_recovery(self):
        from app import jobs
        from sqlalchemy import text
        payload={'brand':{'id':self.brand,'name':'品牌','description':'茶饮'},'marketing_goal':'brand_awareness','theme':'茶饮','platforms':['xiaohongshu']}
        req={'brand_id':self.brand,'kind':'copy','payload':payload,'request_key':self.username}
        first = self.client.post('/api/knowledge/jobs',json=req)
        self.assertEqual(first.status_code,202,first.text)
        jid=first.json()['id']
        self.assertEqual(self.client.post('/api/knowledge/jobs',json=req).json()['id'],jid)
        self.assertEqual(self.other.get('/api/knowledge/jobs/'+jid).status_code,200)
        with patch('app.providers.campaign.generate',return_value=[{'title':'结果','body':'正文'}]):
            jobs.run_once()
        self.assertEqual(self.client.get('/api/knowledge/jobs/'+jid).json()['status'],'succeeded')
        with knowledge.engine.begin() as c:
            c.execute(text("UPDATE kb_jobs SET status='running',heartbeat=0 WHERE id=:id"),{'id':jid})
        jobs.run_once()
        self.assertEqual(self.client.get('/api/knowledge/jobs/'+jid).json()['status'],'failed')
        self.assertEqual(self.client.post('/api/knowledge/jobs/'+jid+'/retry').status_code,200)


class SharedWorkspaceTests(unittest.TestCase):
    setUp = KnowledgeTests.setUp

    def test_legacy_migration_preserves_business_and_archives_conflicting_drafts(self):
        import json
        from sqlalchemy import text, inspect
        from app import workspace
        shared=knowledge.SHARED_WORKSPACE
        with knowledge.engine.begin() as c:
            c.execute(text('CREATE TABLE kb_users(id TEXT PRIMARY KEY,password_hash TEXT)'))
            c.execute(text('CREATE TABLE kb_sessions(token_hash TEXT PRIMARY KEY,user_id TEXT,expires BIGINT)'))
            c.execute(text("INSERT INTO kb_users VALUES('old-user','old-hash')"))
            c.execute(text("UPDATE kb_brands SET owner_id='old-user' WHERE id=:brand"),{'brand':self.brand})
            for owner,updated in [(shared,1),('old-user',2)]:
                c.execute(text('INSERT INTO kb_drafts(user_id,brand_id,payload,revision,updated) VALUES(:owner,:brand,:payload,1,:updated)'),{'owner':owner,'brand':self.brand,'payload':json.dumps({'note':owner}),'updated':updated})
            before=c.execute(text('SELECT COUNT(*) FROM kb_products')).scalar_one()
        workspace.migrate_legacy()
        self.assertFalse({'kb_users','kb_sessions'} & set(inspect(knowledge.engine).get_table_names()))
        with knowledge.engine.connect() as c:
            self.assertEqual(c.execute(text('SELECT COUNT(*) FROM kb_products')).scalar_one(),before)
            self.assertEqual(c.execute(text('SELECT owner_id FROM kb_brands WHERE id=:brand'),{'brand':self.brand}).scalar_one(),shared)
            archived=c.execute(text("SELECT COUNT(*) FROM kb_migration_archive WHERE kind='legacy_draft'")).scalar_one()
            self.assertGreaterEqual(archived,1)
        draft=self.client.get(self.path+'/draft').json()
        self.assertEqual(draft['payload']['note'],'old-user')
        workspace.migrate_legacy()
        self.assertEqual(self.client.get(self.path+'/draft').json(),draft)

    def test_brand_ids_still_bound_product_and_file_operations(self):
        other_brand=self.client.post('/api/knowledge/brands',json={'name':'其他品牌','intro':'独立产品资料'}).json()['id']
        product=self.client.post(self.path+'/products',json={'name':'品牌产品','selling':'商品事实'}).json()
        payload={'brand':{'id':other_brand,'name':'其他品牌','description':'资料'},'marketing_goal':'new_product','products':[{'id':product['id'],'name':'伪造','selling_points':['伪造']}],'platforms':['xiaohongshu']}
        self.assertEqual(self.client.post('/api/v2/copywriting',json=payload).status_code,404)

    def test_local_only_is_transport_policy_not_login(self):
        from fastapi.testclient import TestClient
        class Loopback:
            async def __call__(self,scope,receive,send):
                await app(dict(scope,client=('127.0.0.1',12345)),receive,send)
        with patch.dict(os.environ,{'WORKSPACE_LOCAL_ONLY':'true'}):
            with TestClient(Loopback(),base_url='http://127.0.0.1') as local:
                self.assertEqual(local.get('/api/knowledge/workspace').status_code,200)
                self.assertFalse(local.cookies)
                self.assertEqual(local.get('/api/knowledge/workspace',headers={'X-Forwarded-For':'127.0.0.1'}).status_code,403)
            self.assertEqual(self.client.get('/api/knowledge/workspace').status_code,403)


if __name__ == '__main__':
    unittest.main()
