"""Exercise a disposable copy of the clean local workspace without browser authentication."""
import argparse
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.request import urlopen
from playwright.sync_api import sync_playwright

BACKEND=Path(__file__).resolve().parents[1]


def run(source, screenshot):
    with tempfile.TemporaryDirectory(prefix='clean-preview-check-') as folder:
        data=Path(folder)/'data'
        shutil.copytree(source/'data',data)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0))
            port=sock.getsockname()[1]
        base=f'http://127.0.0.1:{port}'
        env=dict(os.environ,APP_DATA_DIR=str(data),BRAND_DATABASE_URL='sqlite:///'+(data/'brand-knowledge.db').as_posix(),BRAND_STORAGE_DIR=str(data/'brand-files'),WORKSPACE_LOCAL_ONLY='true',APP_ENV='development',USE_MOCK='true',APP_ACCESS_KEY='',SEED_DEMO_DATA='false',EMBED_API_KEY='',EMBED_MODEL='')
        with (Path(folder)/'server.log').open('w',encoding='utf-8') as log:
            server=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port),'--no-proxy-headers'],cwd=BACKEND,env=env,stdout=log,stderr=log)
            try:
                for _ in range(150):
                    if server.poll() is not None:
                        raise RuntimeError('Server stopped')
                    try:
                        urlopen(base+'/api/health',timeout=1).close()
                        break
                    except OSError:time.sleep(.1)
                with sync_playwright() as p:
                    browser=p.chromium.launch(channel='msedge',headless=True)
                    page=browser.new_page(viewport={'width':1440,'height':1000})
                    page.set_default_timeout(30000)
                    errors=[]
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(base)
                    page.locator('#workspaceStatus').wait_for()
                    assert page.locator('#accountName').count()==0
                    assert page.locator('#phoneNumber').count()==0
                    assert page.get_by_role('button',name='退出账户',exact=True).count()==0
                    assert page.get_by_role('button',name='填入示例资料',exact=True).count()==0
                    ws=page.request.get(base+'/api/knowledge/workspace').json()
                    assert len(ws['brands'])==7 and len(ws['products'])==678
                    assert not ws['works']
                    assert all('示例' not in r['name'] and '测试' not in r['name'] for r in ws['brands']+ws['products'])
                    assert not browser.contexts[0].cookies()
                    if screenshot:page.screenshot(path=screenshot.replace('.png','-brands.png'))
                    page.locator('#brandQuery').fill('星巴克')
                    page.get_by_role('button',name='搜索品牌',exact=True).click()
                    assert page.locator('.brand-tile').count()==1
                    page.locator('.brand-tile').filter(has=page.get_by_role('heading',name='星巴克',exact=True)).get_by_role('button',name='进入品牌知识页',exact=True).click()
                    page.get_by_role('heading',name='星巴克 · 品牌知识',exact=True).wait_for()
                    brand=next(b for b in ws['brands'] if b['name']=='星巴克')
                    photo=next(p for p in ws['products'] if p['brand']==brand['id'] and p['image_document_id'])
                    if screenshot:page.screenshot(path=screenshot.replace('.png','-knowledge.png'))
                    page.get_by_role('button',name='待补充资料',exact=True).click()
                    page.locator('#bp').fill('日常咖啡场景')
                    page.locator('#bs').fill('简洁自然')
                    page.get_by_role('button',name='保存品牌补充',exact=True).click()
                    page.get_by_text('品牌资料已保存到服务端',exact=True).wait_for()
                    page.get_by_role('button',name='知识资料',exact=True).click()
                    page.get_by_text('暂无符合条件的知识资料。产品图片已归入对应产品，不在这里重复展示。',exact=True).wait_for()
                    assert page.locator('.document-row').count()==0
                    page.get_by_role('button',name='＋ 补充资料',exact=True).click()
                    page.locator('#uploadCategory').select_option(label='活动规则')
                    page.locator('#brandFile').set_input_files({'name':'活动说明.txt','mimeType':'text/plain','buffer':'活动时间：周末。活动规则：指定饮品第二杯半价。'.encode()})
                    page.get_by_role('button',name='上传并解析',exact=True).click()
                    page.locator('.document-row').get_by_text('活动说明.txt',exact=True).wait_for()
                    page.get_by_role('button',name='查看详情',exact=True).click()
                    page.get_by_role('button',name='核对并确认',exact=True).click()
                    page.get_by_role('button',name='确认并启用',exact=True).click()
                    page.get_by_text('品牌资料已启用',exact=True).wait_for()
                    page.get_by_role('button',name='▦　产品库',exact=True).click()
                    assert page.locator('.catalog-product').count()==20
                    if screenshot:page.screenshot(path=screenshot.replace('.png','-library.png'))
                    page.locator('.bulkProduct').first.check()
                    page.locator('#libraryResults').get_by_role('button',name='下一页',exact=True).first.click()
                    assert page.locator('.catalog-product').count()==20
                    page.locator('.bulkProduct').first.check()
                    assert '已选 2 款' in page.locator('#bulkCount').inner_text()
                    page.locator('#libraryResults').get_by_role('button',name='上一页',exact=True).first.click()
                    assert page.locator('.bulkProduct').first.is_checked()
                    page.get_by_role('button',name='列表',exact=True).click()
                    assert page.locator('.catalog-list').count()==1
                    page.get_by_role('button',name='＋ 添加产品',exact=True).click()
                    page.locator('#addProductQuery').fill(photo['name'])
                    page.get_by_role('button',name='编辑已有产品',exact=True).first.click()
                    assert page.locator('#pn').input_value()==photo['name']
                    page.locator('#pp').fill('25.50元')
                    page.get_by_role('button',name='保存产品',exact=True).click()
                    page.locator('#pn').wait_for(state='detached')
                    assert next(p for p in page.request.get(base+'/api/knowledge/workspace').json()['products'] if p['id']==photo['id'])['price']=='25.50元'
                    page.locator('#libraryQuery').fill('不存在的产品')
                    page.get_by_role('button',name='搜索产品',exact=True).click()
                    assert page.locator('.catalog-product').count()==0
                    page.get_by_role('button',name='重置',exact=True).click()
                    page.get_by_role('button',name='开始营销创作 →',exact=True).click()
                    assert page.locator('[name=product]').count()==0
                    assert page.locator('.selected-product').count()==0
                    page.get_by_role('button',name='选择产品',exact=True).click()
                    assert page.locator('[name=pickerProduct]').count()==20
                    page.locator('[name=pickerProduct]').first.check()
                    page.locator('#pickerResults').get_by_role('button',name='下一页',exact=True).click()
                    page.locator('[name=pickerProduct]').first.check()
                    page.get_by_role('button',name='已选产品',exact=True).click()
                    assert page.locator('[name=pickerProduct]:checked').count()==2
                    if screenshot:page.screenshot(path=screenshot.replace('.png','-picker.png'))
                    page.get_by_role('button',name='确认加入',exact=True).click()
                    assert page.locator('.selected-product').count()==2
                    for _ in range(2):
                        page.locator('.selected-product').first.get_by_role('button',name='移除',exact=True).click()
                    page.get_by_role('button',name='选择产品',exact=True).click()
                    page.locator('#pickerQuery').fill(photo['name'])
                    page.get_by_role('button',name='筛选产品',exact=True).click()
                    page.locator('[name=pickerProduct][value="'+photo['id']+'"]').check()
                    page.get_by_role('button',name='确认加入',exact=True).click()
                    assert page.locator('.selected-product').count()==1
                    page.locator('[name=platform][value="微信公众号"]').check()
                    page.locator('#format').select_option(label='图文')
                    page.get_by_role('button',name='✧ 开始创作 →',exact=True).click()
                    page.get_by_role('heading',name='把灵感，打磨成满意的作品').wait_for(timeout=60000)
                    page.get_by_role('button',name='生成图片',exact=True).click()
                    page.locator('.result-image').wait_for(timeout=60000)
                    with page.expect_download() as download:
                        page.get_by_role('button',name='保存并打包导出',exact=True).click()
                    archive_path=Path(folder)/'materials.zip'
                    download.value.save_as(archive_path)
                    with zipfile.ZipFile(archive_path) as archive:
                        assert len([n for n in archive.namelist() if n.endswith('.png')])==3
                        assert '文章.html' in archive.namelist()
                        assert photo['name'] in archive.read('文案.txt').decode()
                    if screenshot:page.screenshot(path=screenshot,full_page=True)
                    page.get_by_role('button',name='微信公众号 · '+photo['name'],exact=True).click()
                    page.get_by_role('button',name='生成图片',exact=True).click()
                    page.locator('.result-image').wait_for(timeout=60000)
                    url=page.locator('.result-image').get_attribute('src')
                    from PIL import Image
                    raw=page.request.get(base+url).body()
                    assert Image.open(io.BytesIO(raw)).size==(1200,510)
                    page.locator('#rb').fill('本次临时验收草稿，不进入实际预览环境。')
                    page.wait_for_timeout(2200)
                    page.reload()
                    page.get_by_role('button',name='恢复上次草稿',exact=True).click()
                    page.locator('#rb').wait_for()
                    assert page.locator('#rb').input_value()=='本次临时验收草稿，不进入实际预览环境。'
                    page.get_by_role('button',name='◈　品牌资料',exact=True).click()
                    page.get_by_role('button',name='＋ 新建我的品牌',exact=True).click()
                    page.locator('#bn').wait_for()
                    assert page.locator('#bi').is_visible()
                    page.set_viewport_size({'width':390,'height':844})
                    page.get_by_role('button',name='← 返回品牌库',exact=True).click()
                    page.locator('.brand-tile').filter(has=page.get_by_role('heading',name='星巴克',exact=True)).get_by_role('button',name='进入品牌知识页',exact=True).click()
                    page.get_by_role('button',name='完善已有产品',exact=True).click()
                    page.get_by_role('button',name='开始营销创作 →',exact=True).click()
                    page.get_by_role('button',name='选择产品',exact=True).click()
                    assert page.locator('.wide-modal').bounding_box()['width']<=390
                    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
                    if screenshot:page.screenshot(path=screenshot.replace('.png','-mobile.png'))
                    assert not errors,errors
                    browser.close()
                    print('PASS: brand search/knowledge/new form, separated document upload/confirmation, 20-item library pages, cross-page selection, duplicate lookup, campaign picker, generation/export/draft recovery; disposable copy only')
            finally:
                if os.name=='nt':
                    subprocess.run(['taskkill','/PID',str(server.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
                else:server.terminate()
                server.wait(timeout=15)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--screenshot',default='')
    args=parser.parse_args()
    run(args.runtime.resolve(),args.screenshot)
