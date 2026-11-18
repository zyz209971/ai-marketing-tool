"""Create an isolated local workspace from a verified production-data directory."""
import argparse
import hashlib
import io
import ipaddress
import json
import os
import shutil
import socket
import sqlite3
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
OWNER = 'local-preview-workspace'


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()[:28]


def verify(source):
    manifest = json.loads((source/'manifest.json').read_text(encoding='utf-8'))['files']
    for rel, entry in manifest.items():
        file = (source/rel).resolve()
        if not file.is_relative_to(source.resolve()) or hashlib.sha256(file.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('生产包校验失败：'+rel)


def backup(destination):
    destination.mkdir(parents=True, exist_ok=False)
    for source in (ROOT/'backend/data').rglob('*'):
        if not source.is_file() or source.name.endswith(('-wal','-shm','-journal')):
            continue
        target = destination/source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix == '.db':
            with closing(sqlite3.connect(f'{source.as_uri()}?mode=ro', uri=True)) as a, closing(sqlite3.connect(target)) as b:
                a.backup(b)
        else:
            shutil.copy2(source, target)
    files = {p.relative_to(destination).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in destination.rglob('*') if p.is_file()}
    (destination/'manifest.json').write_text(json.dumps(files, ensure_ascii=False, indent=2), encoding='utf-8')


def download(url):
    import httpx
    from PIL import Image, ImageOps
    allowed = {'pcmd.starbucks.com.cn','images.qmai.cn','go.cdn.heytea.com',
               'trade-marketing-prod-oss.pin-dao.cn','cdn-product-prod.cotticoffee.com',
               *{f'img{i:02d}.luckincoffeecdn.com' for i in range(1,7)}}
    for _ in range(3):
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname not in allowed or parsed.username or parsed.password or parsed.port not in (None,443):
            raise ValueError('图片地址不在允许的原始品牌 CDN 内')
        if any(not ipaddress.ip_address(item[4][0]).is_global for item in socket.getaddrinfo(parsed.hostname,443)):
            raise ValueError('非公网图片地址')
        with httpx.stream('GET',url,follow_redirects=False,trust_env=False,timeout=httpx.Timeout(12,connect=5),headers={'User-Agent':'Mozilla/5.0'}) as response:
            if response.is_redirect:
                from urllib.parse import urljoin
                url = urljoin(url, response.headers['location'])
                continue
            response.raise_for_status()
            raw = io.BytesIO()
            for chunk in response.iter_bytes():
                raw.write(chunk)
                if raw.tell() > 6000000:
                    raise ValueError('图片超过6MB')
        with Image.open(io.BytesIO(raw.getvalue())) as image:
            if image.width*image.height > 25000000:
                raise ValueError('图片像素过大')
            image = ImageOps.exif_transpose(image).convert('RGB')
            image.thumbnail((1800,1800))
            result = io.BytesIO()
            image.save(result,'PNG')
            return result.getvalue()
    raise ValueError('图片重定向过多')


def prepare(source, runtime, backup_dir, fetch_images):
    verify(source)
    if runtime.exists():
        raise ValueError('运行目录已存在，拒绝覆盖已有创作记录。')
    backup(backup_dir)
    shutil.copytree(source/'backend/data',runtime/'data')
    data = runtime/'data'
    storage = data/'brand-files'
    storage.mkdir()
    rows = [json.loads(line) for line in (data/'产品.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    merchants = [json.loads(line) for line in (source/'merchant-references.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    about = {r['商家名称']: r['商家信息'] for r in merchants}
    c = sqlite3.connect(data/'brand-knowledge.db')
    try:
        for table in ('kb_users','kb_sessions','kb_members','kb_identities','kb_phone_codes','kb_phone_cooldown','kb_auth_limits','kb_invitations'):
            c.execute('DROP TABLE IF EXISTS '+table)
        c.execute('INSERT INTO kb_write_guard(id,marker) VALUES(1,0) ON CONFLICT(id) DO NOTHING')
        c.execute('INSERT INTO kb_revisions(user_id,revision) VALUES(?,1)',(OWNER,))
        for brand in sorted({r['商家名称'] for r in rows}):
            c.execute('INSERT INTO kb_brands VALUES(?,?,?,?,?,?,?)',('brand_'+digest(brand),OWNER,brand,about.get(brand) or f'{brand}现有产品参考资料。价格和产品信息来自历史采集，创作前请核对。','','',''))
        c.execute('CREATE TABLE local_catalog_sources (product_id TEXT PRIMARY KEY,source_id TEXT NOT NULL,source_url TEXT NOT NULL,image_url TEXT NOT NULL,price_status TEXT NOT NULL)')
        for row in rows:
            pid, bid = 'product_'+digest(row['product_id']), 'brand_'+digest(row['商家名称'])
            facts = row.get('卖点') or '；'.join(f'{key}：{row[key]}' for key in ('规格','成分','热量') if row.get(key)) or row.get('产品信息') or row['产品名称']
            c.execute('INSERT INTO kb_products(id,brand_id,name,price,selling,image_document_id,category,archived,updated) VALUES(?,?,?,?,?,?,?,?,?)',(pid,bid,row['产品名称'],str(row.get('价格') or ''),str(facts)[:5000],'',row.get('产品类别',''),0,time.time_ns()))
            c.execute('INSERT INTO local_catalog_sources VALUES(?,?,?,?,?)',(pid,row['product_id'],row.get('来源链接',''),row.get('图片链接',''),'历史来源价格，发布前请核对'))
        c.commit()
        image_report=[]
        if fetch_images:
            def fetch(row):
                try:
                    return row,download(row['图片链接']),None
                except Exception as exc:
                    return row,None,type(exc).__name__
            with ThreadPoolExecutor(max_workers=8) as pool:
                for row, raw, error in pool.map(fetch,rows):
                    pid,bid='product_'+digest(row['product_id']),'brand_'+digest(row['商家名称'])
                    if raw:
                        did,vid,key='photo_'+digest(row['product_id']),'photo_version_'+digest(row['product_id']),digest(row['product_id'])+'.png'
                        (storage/key).write_bytes(raw)
                        c.execute('INSERT INTO kb_documents(id,brand_id,name,kind,active_version,created) VALUES(?,?,?,?,?,?)',(did,bid,row['产品名称']+'原始产品图','image',vid,time.time_ns()))
                        c.execute('INSERT INTO kb_versions VALUES(?,?,?,?,?,?,?,?)',(vid,did,key,row['产品名称']+'.png','image/png','active','',time.time_ns()))
                        c.execute('UPDATE kb_products SET image_document_id=? WHERE id=?',(did,pid))
                    image_report.append({'source_id':row['product_id'],'brand':row['商家名称'],'name':row['产品名称'],'status':'downloaded' if raw else 'unavailable','reason':error})
                    if len(image_report)%50==0:
                        c.commit()
                        print(f'图片检查 {len(image_report)}/{len(rows)}',flush=True)
            c.commit()
        assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        stats = {'brands':c.execute('SELECT COUNT(*) FROM kb_brands').fetchone()[0], 'products':len(rows), 'images':dict(Counter(r['status'] for r in image_report)), 'runtime':str(runtime),'source_unchanged':True,'backup':str(backup_dir),'user_verification':False,'note':'原品牌产品参考目录，不表示经营这些品牌或价格已核实；图片来自原记录CDN，失败不替换成示例图片。'}
        verify(source)
        (runtime/'import-summary.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
        (runtime/'image-report.json').write_text(json.dumps(image_report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(stats,ensure_ascii=False,indent=2))
    finally:
        c.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--backup',type=Path,required=True)
    parser.add_argument('--fetch-images',action='store_true')
    args=parser.parse_args()
    prepare(args.source.resolve(),args.runtime.resolve(),args.backup.resolve(),args.fetch_images)
