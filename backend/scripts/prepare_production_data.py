"""Offline, non-destructive production data export. Backups and review never enter deploy ZIP."""
import argparse
import csv
import hashlib
import json
import re
import shutil
import sqlite3
import sys
import zipfile
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app import rag

SOURCES = ('产品.jsonl', '推文.jsonl', '小红书推文.jsonl')
MARKER = re.compile(r'（示例）|\(示例\)|示例品牌|测试品牌|测试饮品|测试产品|测试商品|^测试-|^test[-_ ]|^demo[-_ ]|mock\s*占位', re.I)
NOISE = {'已下线', '区域限定', '门店限定', '新品', '产品', '商品', '饮品菜单'}


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False)+'\n')


def rows_db(path, table):
    with closing(sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True)) as c:
        c.row_factory = sqlite3.Row
        return [dict(row) for row in c.execute('SELECT * FROM "'+table+'"')]


def counts(path):
    with closing(sqlite3.connect(path)) as c:
        assert c.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%fts%' AND name NOT LIKE '%_config' AND name NOT LIKE '%_data' AND name NOT LIKE '%_idx' AND name NOT LIKE '%_docsize'")]
        return {t: c.execute('SELECT COUNT(*) FROM "'+t+'"').fetchone()[0] for t in tables}


def file_manifest(folder):
    return {p.relative_to(folder).as_posix(): {'sha256': sha(p), 'bytes': p.stat().st_size} for p in sorted(folder.rglob('*')) if p.is_file() and p.name != 'manifest.json'}


def snapshot(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix == '.db':
        with closing(sqlite3.connect(f'{source.as_uri()}?mode=ro', uri=True)) as original, closing(sqlite3.connect(destination)) as target:
            original.backup(target)
        counts(destination)
    else:
        shutil.copy2(source, destination)


def build(output):
    output.mkdir(parents=True, exist_ok=False)
    backup, review, production = [output/n for n in ('private-backup', 'review', 'production')]
    backup.mkdir(); review.mkdir(); production.mkdir()
    # Snapshot DBs via SQLite API (including committed WAL data); never copy live DB bytes.
    inputs = list((ROOT/'backend/data').rglob('*')) + [ROOT/'产品知识库.csv'] + list((ROOT/'marketing').rglob('*')) + list((ROOT/'backend/eval').rglob('*'))
    before = {}
    for source in sorted(inputs):
        if not source.is_file() or source.name.endswith(('-wal','-shm','-journal')):
            continue
        rel = source.relative_to(ROOT)
        before[rel.as_posix()] = sha(source)
        snapshot(source, backup/rel)
    write_json(backup/'manifest.json', {'created': datetime.now(timezone.utc).isoformat(), 'private': True, 'note': '含原账户和运行记录，仅限本地备份；禁止部署或公开。', 'files': file_manifest(backup)})
    audit, raw_review, accepted, all_raw, merchants = [], [], {}, [], []
    def decide(source, line, identifier, status, reason, record=None):
        entry = {'source': source, 'line_or_id': line, 'record_id': identifier, 'decision': status, 'reason': reason}
        audit.append(entry)
        if record is not None and status != 'keep':
            raw_review.append({**entry, 'record': record})
    for filename in SOURCES:
        kept, seen_id, seen_content = [], set(), set()
        for number, line in enumerate((backup/'backend/data'/filename).read_text(encoding='utf-8-sig').splitlines(),1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError('非对象')
            except (ValueError, TypeError):
                decide(filename, number, '', 'review', '无法解析的 JSON 记录', {'raw': line})
                continue
            all_raw.append((filename, record))
            norm = rag.normalize_record(record)
            label = ' '.join(str(record.get(k,'')) for k in ('商家名称','品牌','产品名称','标题','name','brand'))
            parsed = urlsplit(norm['source_url'])
            identity = norm['document_id']
            content_key = hashlib.sha256(json.dumps({k:norm[k] for k in ('record_type','brand','product_name','title','chunks')},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
            if MARKER.search(label):
                status, reason = 'exclude', '明确测试或示例标记'
            elif filename=='产品.jsonl' and identity.startswith('MERCHANT_') and norm['brand'] and not norm['product_name'] and parsed.scheme in ('http','https') and parsed.hostname:
                merchants.append(record)
                decide(filename,number,identity,'keep_reference','商家官网介绍，单独保留为品牌参考，不误当产品入库')
                continue
            elif not norm['chunks'] or not norm['title'] or (norm['record_type']=='product' and (not norm['brand'] or norm['product_name'] in NOISE)):
                status, reason = 'review', '正文/名称/品牌缺失或名称为页面标签'
            elif parsed.scheme not in ('http','https') or not parsed.hostname or parsed.hostname in ('localhost','example.com','example.org'):
                status, reason = 'review', '来源链接缺失或为占位地址'
            elif identity in seen_id or content_key in seen_content:
                status, reason = 'review', '重复标识或内容，保留首条并记录其余版本'
            else:
                status, reason = 'keep', '既有带来源业务资料；非示例，未重新验证时效'
                seen_id.add(identity); seen_content.add(content_key)
                kept.append(record)
            decide(filename,number,identity,status,reason,record)
        accepted[filename]=kept
        write_jsonl(production/'backend/data'/filename, kept)
    # The old CSV is a derived catalog; use only exact, price-consistent source matches.
    lookup = defaultdict(list)
    for record in accepted['产品.jsonl']:
        lookup[(record.get('商家名称',''),record.get('产品名称',''))].append(record)
    with (backup/'产品知识库.csv').open(encoding='utf-8-sig',newline='') as handle:
        csv_rows=list(csv.DictReader(handle))
    for number, record in enumerate(csv_rows,2):
        key = (record.get('品牌',''),record.get('产品名',''))
        if not key[0] and key[1] in {'招牌珍珠奶茶','杨枝甘露','芝士葡萄','柠檬绿茶','黑糖波波鲜奶'}:
            decide('产品知识库.csv',number,'|'.join(key),'exclude','与代码预置示例一致',record)
        elif key not in lookup or key[1] in NOISE:
            decide('产品知识库.csv',number,'|'.join(key),'review','派生 CSV 无可精确对应的原始来源；不丢弃',record)
        else:
            decide('产品知识库.csv',number,'|'.join(key),'deduplicated','由带来源原始产品记录取代；CSV 历史价格仍保存在备份',record)
    # Legacy database contains only demonstrably seeded/test records in this snapshot.
    for record in rows_db(backup/'backend/data/products.db','products'):
        demo = not record['brand'] and record['name'] in {'招牌珍珠奶茶','杨枝甘露','芝士葡萄','柠檬绿茶','黑糖波波鲜奶'}
        decide('products.db',record['id'],record['name'],'exclude' if demo or MARKER.search(record['brand']+' '+record['name']) else 'review','代码预置示例或明确测试标记' if demo or MARKER.search(record['brand']+' '+record['name']) else '无法确认归属和来源，待核对',record)
    # Preserve a production-compatible empty workspace schema; no identities/sessions/test jobs.
    source_brand=backup/'backend/data/brand-knowledge.db'
    brand_rows=rows_db(source_brand,'kb_brands')
    for record in brand_rows:
        status='exclude' if MARKER.search(record['name']) else 'review'
        decide('brand-knowledge.db/kb_brands',record['id'],record['name'],status,'明确示例品牌及其关联运行数据' if status=='exclude' else '品牌归属与真实性待确认',record)
    workspace = production/'backend/data/brand-knowledge.db'
    with closing(sqlite3.connect(source_brand)) as original, closing(sqlite3.connect(workspace)) as target:
        schemas=original.execute("SELECT sql FROM sqlite_master WHERE type IN ('table','index') AND sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY CASE type WHEN 'table' THEN 0 ELSE 1 END").fetchall()
        for row in schemas:
            if any(name in row[0] for name in ('kb_users','kb_sessions','kb_members','kb_identities','kb_phone_codes','kb_phone_cooldown','kb_auth_limits','kb_invitations')):
                continue
            target.execute(row[0])
        target.commit()
    # Rebuild the search index solely from retained records, offline. Preserve exact vector matches.
    rag.DB_PATH=production/'backend/data/marketing.db'
    rag.EMBED_API_KEY=''; rag.EMBED_MODEL=''
    records=[row for filename in SOURCES for row in accepted[filename]]
    index_stats=rag.ingest_records(records)
    old_vectors={}
    with closing(sqlite3.connect(backup/'backend/data/marketing.db')) as c:
        for row in c.execute("SELECT document_id,chunk_id,text,embedding_model,vec FROM rag_chunks WHERE vec IS NOT NULL AND vec<>'' AND embedding_model<>''"):
            old_vectors[(row[0],row[1],row[2])]=row[3:]
    restored=0
    with closing(sqlite3.connect(rag.DB_PATH)) as c:
        for rid, doc, ordinal, content in c.execute('SELECT id,document_id,chunk_id,text FROM rag_chunks').fetchall():
            vector=old_vectors.get((doc,ordinal,content))
            if vector:
                c.execute('UPDATE rag_chunks SET embedding_model=?,vec=? WHERE id=?',(*vector,rid));restored+=1
        c.commit()
    # Product autocomplete catalog is built from originals, never from the seeded old DB.
    catalog=[]
    for record in accepted['产品.jsonl']:
        catalog.append({'source_id':record['product_id'],'brand':record['商家名称'],'name':record['产品名称'],'price':str(record.get('价格') or ''),'selling_points':str(record.get('卖点') or ''),'category':record.get('产品类别',''),'source_url':record.get('来源链接',''),'price_status':'历史来源价格，使用前核对'})
    groups=defaultdict(list)
    for row in catalog:groups[(row['brand'],row['name'])].append(row)
    catalog_path=production/'backend/data/products.db'
    with closing(sqlite3.connect(catalog_path)) as c:
        c.execute("CREATE TABLE products (id INTEGER PRIMARY KEY AUTOINCREMENT,brand TEXT DEFAULT '',name TEXT NOT NULL,selling_points TEXT,price TEXT,category TEXT,UNIQUE(brand,name))")
        for key, group in groups.items():
            facts={(r['price'],r['selling_points']) for r in group}
            if len(facts)>1:
                decide('derived_catalog','|'.join(key),'','review','同名产品存在冲突价格/卖点，保留来源记录，不写自动补全表',group)
                continue
            r=group[0]
            c.execute('INSERT INTO products(brand,name,selling_points,price,category) VALUES(?,?,?,?,?)',(r['brand'],r['name'],r['selling_points'],r['price'],r['category']))
        c.commit()
    write_jsonl(production/'catalog-with-provenance.jsonl',catalog)
    write_jsonl(production/'merchant-references.jsonl',merchants)
    write_jsonl(review/'decisions.jsonl',audit)
    write_jsonl(review/'excluded-and-review-records.jsonl',raw_review)
    for path in (backup/'marketing').rglob('*'):
        if path.is_file():
            decide('marketing/'+path.name,'file','','exclude','独立示例文档，已完整备份')
    write_jsonl(review/'decisions.jsonl',audit)
    original_counts={name:counts(backup/'backend/data'/name) for name in ('brand-knowledge.db','products.db','marketing.db','quota.db')}
    production_counts={name:counts(production/'backend/data'/name) for name in ('brand-knowledge.db','products.db','marketing.db')}
    assert not any(production_counts['brand-knowledge.db'].values())
    for name in SOURCES:
        assert len(accepted[name])==sum(a['source']==name and a['decision']=='keep' for a in audit)
    assert all(sha(ROOT/rel)==value for rel,value in before.items()), '原始资料在整理期间发生变化，请重新备份生成。'
    summary={'created':datetime.now(timezone.utc).isoformat(),'source_unchanged':True,'retained':{**{k:len(v) for k,v in accepted.items()},'merchant-references.jsonl':len(merchants)},'decisions':dict(Counter(a['decision'] for a in audit)),'original_databases':original_counts,'production_databases':production_counts,'index':index_stats,'restored_vectors':restored,'network_requests':0,'auth_and_runtime_records_exported':False,'source_verification':'保留已有来源与准入标记；没有重新联网验证、核价或提升资料可信等级。','deployment_ready':False,'deployment_note':'这是干净的数据包，不是完整可上线应用；需真实模型、访问配置、来源价格确认和部署验收。'}
    write_json(output/'summary.json',summary)
    write_json(production/'data-summary.json',summary)
    (production/'production.env.example').write_text('APP_ENV=production\nUSE_MOCK=false\nSEED_DEMO_DATA=false\n',encoding='utf-8')
    (production/'使用说明.txt').write_text('生产数据包（不含应用代码、密钥、账户或测试数据）\n\n1. 使用已修改为默认不植入示例的应用版本，设置 SEED_DEMO_DATA=false。\n2. 停止目标服务，先备份目标数据库和文件目录，再把 backend/data 中三个数据库及三个 JSONL 放入对应目录。禁止覆盖已有生产用户库；本包用户库为空，仅适用于首次部署。\n3. 若配置 BRAND_DATABASE_URL 为 PostgreSQL，不能直接导入此 SQLite 文件，需另行迁移。\n4. 配置真实模型、HTTPS、存储和访问入口后验收。当前包不含 quota.db，会由应用创建全新额度记录。\n5. 产品库是外部品牌参考目录，不会自动加入自有品牌；保留历史来源价格，发布前核对。营销案例仅供结构参考，原严格准入标记保持不变。\n6. 清理明细和不确定记录位于包外 review；原始账户与运行数据仅在 private-backup。不要部署这两个目录。\n7. manifest.json 列出全部交付文件 SHA256。恢复本地环境时从 private-backup 还原，先停止服务；SQLite 备份是独立快照，不应混用旧 WAL 文件。\n',encoding='utf-8')
    write_json(production/'manifest.json',{'files':file_manifest(production)})
    archive=output/'production-data.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(production.rglob('*')):
            if p.is_file():z.write(p,p.relative_to(production).as_posix())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert all(not name.startswith(('review/','private-backup/')) for name in z.namelist())
    write_json(output/'delivery-checksums.json',{'production-data.zip':sha(archive),'backup_manifest':sha(backup/'manifest.json'),'production_manifest':sha(production/'manifest.json')})
    print(json.dumps({'output':str(output),'retained':summary['retained'],'decisions':summary['decisions'],'production_counts':production_counts,'index':index_stats,'restored_vectors':restored},ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    build(args.output.resolve())
