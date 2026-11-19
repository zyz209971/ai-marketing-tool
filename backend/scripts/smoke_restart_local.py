"""Offline HTTP acceptance: process restart, durable questions, stopped snapshot restore.

Uses an isolated directory and random loopback port. No private env files or model calls.
Only processes started by this script are terminated; the user's server is untouched.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import sysconfig
import time
from uuid import uuid4
import httpx
from snapshot_runtime import snapshot

ROOT=Path(__file__).resolve().parents[2]


class Server:
    def __init__(self,runtime,port):
        self.runtime=runtime
        self.port=port
        self.process=None
        self.log=None

    def start(self):
        self.runtime.mkdir(parents=True,exist_ok=True)
        env={**os.environ,'APP_SKIP_DOTENV':'true','AUTH_MODE':'local','USE_MOCK':'true',
             'APP_DATA_DIR':str(self.runtime),'BRAND_DATABASE_URL':'sqlite:///'+(self.runtime/'brand-knowledge.db').as_posix(),
             'BRAND_STORAGE_DIR':str(self.runtime/'brand-files'),'AGENT_CHECKPOINT_URL':'',
             'WORKSPACE_LOCAL_ONLY':'true','APP_ACCESS_KEY':'','SEED_DEMO_DATA':'false',
             'PYTHONPATH':os.pathsep.join([str(ROOT/'backend'),sysconfig.get_path('purelib')])}
        for key in list(env):
            if key.endswith('API_KEY') or key=='APP_ENV_FILE':env.pop(key,None)
        self.log=(self.runtime/'smoke-server.log').open('ab')
        # Windows venv redirectors may spawn a child. Use the base interpreter with
        # this venv's packages so terminate()/wait() own the actual serving process.
        executable=getattr(sys,'_base_executable',sys.executable) if os.name=='nt' else sys.executable
        self.process=subprocess.Popen([executable,'-m','uvicorn','app.main:app','--host','127.0.0.1',
            '--port',str(self.port),'--no-proxy-headers'],cwd=ROOT/'backend',env=env,
            stdout=self.log,stderr=self.log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        until=time.monotonic()+30
        while time.monotonic()<until:
            if self.process.poll() is not None:raise AssertionError('Isolated server exited; inspect smoke-server.log')
            try:
                if httpx.get(f'http://127.0.0.1:{self.port}/api/health',timeout=1,trust_env=False).status_code==200:return
            except httpx.RequestError:pass
            time.sleep(.2)
        raise AssertionError('Isolated server startup timed out')

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)
        if self.log:self.log.close()


def main():
    root=ROOT/'.local-data'/('restart-smoke-'+uuid4().hex[:8])
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=Server(root/'runtime',port)
    client=httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=20,trust_env=False)
    def request(method,path,**kwargs):
        response=client.request(method,path,**kwargs)
        assert response.is_success,(path,response.status_code,response.text[:250])
        return response.json()
    def wait(run_id):
        until=time.monotonic()+20
        while time.monotonic()<until:
            value=request('GET','/api/agent/runs/'+run_id)
            if value['status']=='succeeded':return
            assert value['status']!='failed',value['error']
            time.sleep(.1)
        raise AssertionError('Offline run timed out')
    def task(ident):return request('GET','/api/agent/conversations/'+ident)
    def say(current,text):
        result=request('POST','/api/agent/conversations/'+current['id']+'/messages',json={
            'request_id':uuid4().hex,'expected_revision':current['revision'],'text':text})
        wait(result['run_id']);return task(current['id'])
    try:
        server.start()
        t=request('POST','/api/agent/conversations',json={})
        path='/api/agent/conversations/'+t['id']
        source='品牌名称：重启测试茶铺（虚构）\n产品名称：桂花茶\n价格：18元'
        attachment=request('POST',path+'/attachments?kind=knowledge',files={'file':('brand.txt',source.encode(),'text/plain')})
        t=task(t['id']);questions=t['state']['input_request']
        assert len(questions['questions'])==2
        before_revision=t['revision']
        server.stop();server.start()
        restored=task(t['id'])
        assert restored['revision']==before_revision and restored['state']['input_request']==questions
        t=say(restored,'品牌介绍：校园茶饮品牌；商品卖点：桂花香气')
        assert not t['attachments'][0]['payload']['missing_fields']
        assert not t['catalog'],'Unconfirmed draft was activated'
        server.stop()
        # Snapshot includes checkpoint DB and attachments, not just business rows.
        snapshot(root/'runtime',root/'snapshot')
        server=Server(root/'snapshot',port);server.start()
        restored=task(t['id'])
        assert restored['revision']==t['revision']
        assert restored['attachments'][0]['id']==attachment['id']
        request('POST',path+'/attachments/'+attachment['id']+'/confirm',json={'expected_revision':restored['revision']})
        confirmed=task(t['id']);assert len(confirmed['catalog'])==1
        document=attachment['payload']['document_id'];brand=confirmed['state']['brief']['brand_id']
        assert client.get(f'/api/knowledge/brands/{brand}/documents/{document}/file').status_code==200
        print('PASS: real process restart retains question IDs/revision; stopped snapshot restores attachment and confirmation')

        # Separate synthetic task exercises approval persistence without requiring LLM.
        strategy=say(request('POST','/api/agent/conversations',json={'demo':True}),
            '主推茉莉鲜奶茶，小红书，2026-11-21到2026-11-22，预算200元，预计花费200元，预计销量160杯，优惠组数20组，第二杯半价')
        assert strategy['state']['stage']=='awaiting_confirmation'
        sid=strategy['state']['strategy']['id'];version=strategy['state']['strategy']['version']
        server.stop();server.start()
        strategy=task(strategy['id']);assert strategy['state']['strategy']['id']==sid
        endpoint='/api/agent/conversations/'+strategy['id']+'/confirm'
        payload={'request_id':uuid4().hex,'expected_revision':strategy['revision'],'strategy_id':sid,'strategy_version':version}
        result=request('POST',endpoint,json=payload);wait(result['run_id'])
        completed=task(strategy['id']);assert completed['state']['stage']=='completed' and len(completed['state']['artifacts'])==1
        assert request('POST',endpoint,json=payload)['run_id']==result['run_id']
        assert len(task(strategy['id'])['state']['artifacts'])==1
        print('PASS: strategy approval resumes after process restart; repeated receipt does not generate twice')
        (root/'result.json').write_text(json.dumps({'status':'passed','cases':['question_restart','snapshot_restore','approval_restart','duplicate_confirmation']},indent=2),encoding='utf-8')
        print('Isolated evidence: '+str(root))
    finally:
        client.close();server.stop()


if __name__=='__main__':main()
