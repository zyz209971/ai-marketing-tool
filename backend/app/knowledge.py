"""Shared brand knowledge, source documents and retrieval."""
import io
import json
import logging
import os
import time
import csv
import zipfile
import re
from pathlib import Path
from uuid import uuid4
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text, inspect

from . import rag
from .config import DATA_DIR

logger = logging.getLogger(__name__)
DATA = DATA_DIR
DATA.mkdir(parents=True, exist_ok=True)
STORAGE = Path(os.getenv('BRAND_STORAGE_DIR') or str(DATA / 'brand-files')).resolve()
STORAGE.mkdir(parents=True, exist_ok=True)
DATABASE_URL = os.getenv('BRAND_DATABASE_URL') or f'sqlite:///{(DATA / "brand-knowledge.db").as_posix()}'
engine = create_engine(DATABASE_URL, connect_args={'check_same_thread': False} if DATABASE_URL.startswith('sqlite:') else {}, pool_pre_ping=True)
IS_POSTGRES = engine.dialect.name == 'postgresql'
MAX_FILE = 10 * 1024 * 1024
SHARED_WORKSPACE = 'local-preview-workspace'


def init_db():
    # Metadata and vectors live in the same transactional database. SQLite is a local fallback.
    with engine.begin() as c:
        if IS_POSTGRES:
            c.execute(text('CREATE EXTENSION IF NOT EXISTS vector'))
        vec_type = 'vector' if IS_POSTGRES else 'TEXT'
        for statement in [
            'CREATE TABLE IF NOT EXISTS kb_brands (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL, positioning TEXT NOT NULL, style TEXT NOT NULL, preference TEXT NOT NULL)',
            'CREATE TABLE IF NOT EXISTS kb_products (id TEXT PRIMARY KEY, brand_id TEXT NOT NULL, name TEXT NOT NULL, price TEXT NOT NULL, selling TEXT NOT NULL, image_document_id TEXT NOT NULL)',
            'CREATE TABLE IF NOT EXISTS kb_documents (id TEXT PRIMARY KEY, brand_id TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL, active_version TEXT, created BIGINT NOT NULL)',
            'CREATE TABLE IF NOT EXISTS kb_versions (id TEXT PRIMARY KEY, document_id TEXT NOT NULL, storage_key TEXT NOT NULL, filename TEXT NOT NULL, mime TEXT NOT NULL, status TEXT NOT NULL, error TEXT NOT NULL, created BIGINT NOT NULL)',
            f'CREATE TABLE IF NOT EXISTS kb_chunks (id TEXT PRIMARY KEY, version_id TEXT NOT NULL, ordinal INTEGER NOT NULL, content TEXT NOT NULL, source_label TEXT NOT NULL, embedding {vec_type}, embedding_model TEXT NOT NULL)',
            'CREATE INDEX IF NOT EXISTS kb_brand_owner ON kb_brands(owner_id)',
            'CREATE INDEX IF NOT EXISTS kb_products_brand ON kb_products(brand_id)',
            'CREATE INDEX IF NOT EXISTS kb_documents_brand ON kb_documents(brand_id)',
            'CREATE INDEX IF NOT EXISTS kb_versions_doc ON kb_versions(document_id)',
            'CREATE INDEX IF NOT EXISTS kb_chunks_version ON kb_chunks(version_id)',
            'CREATE TABLE IF NOT EXISTS kb_works (id TEXT PRIMARY KEY, brand_id TEXT NOT NULL, payload TEXT NOT NULL)',
            'CREATE TABLE IF NOT EXISTS kb_revisions (user_id TEXT PRIMARY KEY, revision INTEGER NOT NULL)',
            'CREATE TABLE IF NOT EXISTS kb_write_guard (id INTEGER PRIMARY KEY, marker INTEGER NOT NULL)',
            'INSERT INTO kb_write_guard(id,marker) VALUES(1,0) ON CONFLICT(id) DO NOTHING',
        ]:
            c.execute(text(statement))

    columns = {item['name'] for item in inspect(engine).get_columns('kb_products')}
    with engine.begin() as c:
        for name, definition in [('category', "TEXT NOT NULL DEFAULT ''"), ('archived', 'INTEGER NOT NULL DEFAULT 0'), ('updated', 'BIGINT NOT NULL DEFAULT 0')]:
            if name not in columns:
                c.execute(text(f'ALTER TABLE kb_products ADD COLUMN {name} {definition}'))
    doc_columns = {item['name'] for item in inspect(engine).get_columns('kb_documents')}
    with engine.begin() as c:
        for name, default in [('purpose', 'knowledge'), ('category', '品牌资料')]:
            if name not in doc_columns:
                c.execute(text(f"ALTER TABLE kb_documents ADD COLUMN {name} TEXT NOT NULL DEFAULT '{default}'"))
        c.execute(text("UPDATE kb_documents SET purpose='product_image' WHERE id IN (SELECT image_document_id FROM kb_products WHERE image_document_id<>'')"))


def ident():
    return uuid4().hex


def get_workspace():
    return SHARED_WORKSPACE


def owned(c, brand_id, user):
    row = c.execute(text('SELECT b.* FROM kb_brands b WHERE b.id=:id'), {'id': brand_id}).mappings().first()
    if not row:
        raise HTTPException(404, '品牌不存在。')
    return dict(row)


def brand_row(row, user=None):
    return {'id': row['id'], 'name': row['name'], 'intro': row['description'], 'position': row['positioning'], 'style': row['style'], 'preference': row['preference']}


def lock_workspace(c):
    # Serialize short workspace writes before touching revisions/permissions. This avoids
    # stale cross-page snapshots and inconsistent lock ordering on PostgreSQL.
    c.execute(text('UPDATE kb_write_guard SET marker=marker WHERE id=1'))


def bump_revision(c, user, brand_id=None):
    c.execute(text('INSERT INTO kb_revisions(user_id,revision) VALUES(:user,1) ON CONFLICT(user_id) DO UPDATE SET revision=kb_revisions.revision+1'), {'user': SHARED_WORKSPACE})


def accessible_brands(c, user):
    return c.execute(text('SELECT * FROM kb_brands ORDER BY name')).mappings().all()


class BrandInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    intro: str = Field(min_length=1, max_length=10000)
    position: str = Field(default='', max_length=2000)
    style: str = Field(default='', max_length=2000)
    preference: str = Field(default='', max_length=2000)


class ProductInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    price: str = Field(default='', max_length=100)
    selling: str = Field(min_length=1, max_length=5000)
    image_document_id: str = ''
    category: str = Field(default='', max_length=100)
    archived: bool = False


router = APIRouter(prefix='/api/knowledge', tags=['brand knowledge'])


class WorkspaceSync(BaseModel):
    revision: int = Field(default=0, ge=0)
    brands: list[dict] = Field(default_factory=list, max_length=100)
    products: list[dict] = Field(default_factory=list, max_length=5000)
    works: list[dict] = Field(default_factory=list, max_length=1000)


@router.get('/workspace')
def workspace(user: str = Depends(get_workspace)):
    with engine.begin() as c:
        c.execute(text('INSERT INTO kb_revisions(user_id,revision) VALUES(:user,0) ON CONFLICT(user_id) DO NOTHING'), {'user': user})
        revision = c.execute(text('SELECT revision FROM kb_revisions WHERE user_id=:user'), {'user': user}).scalar_one()
        bs = accessible_brands(c, user)
        brands_out = [brand_row(r, user) for r in bs]
        products_out, works_out = [], []
        for brand in brands_out:
            ps = c.execute(text('SELECT * FROM kb_products WHERE brand_id=:id ORDER BY name'), {'id': brand['id']}).mappings().all()
            products_out += [dict(r, brand=brand['id']) for r in ps]
            works = c.execute(text('SELECT payload FROM kb_works WHERE brand_id=:id'), {'id': brand['id']}).mappings().all()
            works_out += [json.loads(r['payload']) for r in works]
    return {'brands': brands_out, 'products': products_out, 'works': works_out, 'revision': revision}


@router.post('/workspace/sync')
def sync_workspace(req: WorkspaceSync, user: str = Depends(get_workspace)):
    # Legacy identifiers remain stable while all brands belong to the shared workspace.
    with engine.begin() as c:
        lock_workspace(c)
        c.execute(text('INSERT INTO kb_revisions(user_id,revision) VALUES(:user,0) ON CONFLICT(user_id) DO NOTHING'), {'user': user})
        updated = c.execute(text('UPDATE kb_revisions SET revision=revision+1 WHERE user_id=:user AND revision=:revision'), {'user': user, 'revision': req.revision})
        if not updated.rowcount:
            raise HTTPException(409, '资料已在其他设备更新，请刷新后重新修改。')
        for raw in req.brands:
            bid = str(raw.get('id', ''))
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', bid):
                raise HTTPException(422, '品牌标识无效。')
            data = BrandInput.model_validate(raw).model_dump()
            existing = c.execute(text('SELECT owner_id FROM kb_brands WHERE id=:id'), {'id': bid}).first()
            if existing:
                owned(c, bid, user)
                c.execute(text('UPDATE kb_brands SET name=:name,description=:intro,positioning=:position,style=:style,preference=:preference WHERE id=:id'), {'id': bid, **data})
            else:
                c.execute(text('INSERT INTO kb_brands(id,owner_id,name,description,positioning,style,preference) VALUES(:id,:owner,:name,:intro,:position,:style,:preference)'), {'id': bid, 'owner': user, **data})
        for raw in req.products:
            pid, bid = str(raw.get('id', '')), str(raw.get('brand', ''))
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', pid):
                raise HTTPException(422, '产品标识无效。')
            owned(c, bid, user)
            data = {**ProductInput.model_validate(raw).model_dump(), 'updated': time.time_ns()}
            validate_image(c, bid, data['image_document_id'])
            existing = c.execute(text('SELECT brand_id FROM kb_products WHERE id=:id'), {'id': pid}).first()
            if existing and existing[0] != bid:
                raise HTTPException(404, '产品不存在或不属于当前品牌。')
            if existing:
                c.execute(text('UPDATE kb_products SET name=:name,price=:price,selling=:selling,image_document_id=:image_document_id,category=:category,archived=:archived,updated=:updated WHERE id=:id AND brand_id=:brand'), {'id': pid, 'brand': bid, **data})
            else:
                c.execute(text('INSERT INTO kb_products(id,brand_id,name,price,selling,image_document_id,category,archived,updated) VALUES(:id,:brand,:name,:price,:selling,:image_document_id,:category,:archived,:updated)'), {'id': pid, 'brand': bid, **data})
        for raw in req.works:
            wid, bid = str(raw.get('id', '')), str(raw.get('brand', ''))
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', wid):
                raise HTTPException(422, '作品标识无效。')
            owned(c, bid, user)
            serialized = json.dumps(raw, ensure_ascii=False)
            if len(serialized) > 12000000:
                raise HTTPException(422, '作品过大，请缩小参考图片后保存。')
            existing = c.execute(text('SELECT brand_id FROM kb_works WHERE id=:id'), {'id': wid}).first()
            if existing and existing[0] != bid:
                raise HTTPException(404, '作品不存在或不属于当前品牌。')
            if existing:
                c.execute(text('UPDATE kb_works SET payload=:payload WHERE id=:id AND brand_id=:brand'), {'id': wid, 'brand': bid, 'payload': serialized})
            else:
                c.execute(text('INSERT INTO kb_works(id,brand_id,payload) VALUES(:id,:brand,:payload)'), {'id': wid, 'brand': bid, 'payload': serialized})
    return {'ok': True, 'revision': req.revision + 1}


@router.get('/brands')
def brands(user: str = Depends(get_workspace)):
    with engine.connect() as c:
        rows = accessible_brands(c, user)
    return {'brands': [brand_row(r, user) for r in rows]}


@router.post('/brands', status_code=201)
def create_brand(req: BrandInput, user: str = Depends(get_workspace)):
    data = {'id': ident(), 'owner': user, **req.model_dump()}
    with engine.begin() as c:
        lock_workspace(c)
        c.execute(text('INSERT INTO kb_brands(id,owner_id,name,description,positioning,style,preference) VALUES(:id,:owner,:name,:intro,:position,:style,:preference)'), data)
        bump_revision(c, user)
    return {'id': data['id'], **req.model_dump()}


@router.put('/brands/{brand_id}')
def update_brand(brand_id: str, req: BrandInput, user: str = Depends(get_workspace)):
    with engine.begin() as c:
        lock_workspace(c)
        owned(c, brand_id, user)
        c.execute(text('UPDATE kb_brands SET name=:name,description=:intro,positioning=:position,style=:style,preference=:preference WHERE id=:id'), {'id': brand_id, **req.model_dump()})
        bump_revision(c, user, brand_id)
    return {'id': brand_id, **req.model_dump()}


@router.get('/brands/{brand_id}/products')
def products(brand_id: str, user: str = Depends(get_workspace)):
    with engine.connect() as c:
        owned(c, brand_id, user)
        rows = c.execute(text('SELECT * FROM kb_products WHERE brand_id=:brand ORDER BY name'), {'brand': brand_id}).mappings().all()
    return {'products': [dict(row, brand=brand_id) for row in rows]}


@router.post('/brands/{brand_id}/products', status_code=201)
def create_product(brand_id: str, req: ProductInput, user: str = Depends(get_workspace)):
    data = {'id': ident(), 'brand': brand_id, 'updated': time.time_ns(), **req.model_dump()}
    with engine.begin() as c:
        lock_workspace(c)
        owned(c, brand_id, user)
        validate_image(c, brand_id, req.image_document_id)
        c.execute(text('INSERT INTO kb_products(id,brand_id,name,price,selling,image_document_id,category,archived,updated) VALUES(:id,:brand,:name,:price,:selling,:image_document_id,:category,:archived,:updated)'), data)
        bump_revision(c, user, brand_id)
    return data


@router.put('/brands/{brand_id}/products/{product_id}')
def update_product(brand_id: str, product_id: str, req: ProductInput, user: str = Depends(get_workspace)):
    with engine.begin() as c:
        lock_workspace(c)
        owned(c, brand_id, user)
        validate_image(c, brand_id, req.image_document_id)
        result = c.execute(text('UPDATE kb_products SET name=:name,price=:price,selling=:selling,image_document_id=:image_document_id,category=:category,archived=:archived,updated=:updated WHERE id=:id AND brand_id=:brand'), {'id': product_id, 'brand': brand_id, 'updated': time.time_ns(), **req.model_dump()})
        if not result.rowcount:
            raise HTTPException(404, '产品不存在。')
        bump_revision(c, user, brand_id)
    return {'id': product_id, 'brand': brand_id, 'updated': time.time_ns(), **req.model_dump()}


def validate_image(c, brand_id, document_id):
    if document_id:
        row = c.execute(text("SELECT id FROM kb_documents WHERE id=:id AND brand_id=:brand AND kind='image' AND active_version IS NOT NULL"), {'id': document_id, 'brand': brand_id}).first()
        if not row:
            raise HTTPException(422, '产品图片不存在或不属于该品牌。')
        c.execute(text("UPDATE kb_documents SET purpose='product_image' WHERE id=:id AND brand_id=:brand"), {'id':document_id,'brand':brand_id})


def extract(raw: bytes, suffix: str):
    if suffix in ('.txt', '.md', '.csv'):
        return [('正文', raw.decode('utf-8-sig'))]
    if suffix == '.pdf':
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        if len(reader.pages) > 200:
            raise ValueError('PDF 最多支持 200 页。')
        return [(f'第{i+1}页', page.extract_text() or '') for i, page in enumerate(reader.pages)]
    if suffix == '.docx':
        from docx import Document
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if sum(item.file_size for item in archive.infolist()) > 50 * 1024 * 1024:
                raise ValueError('文档解压后超过 50MB。')
        doc = Document(io.BytesIO(raw))
        result = [('文档正文', '\n'.join(p.text for p in doc.paragraphs))]
        for index, table in enumerate(doc.tables):
            result.append((f'表格{index+1}', '\n'.join(' | '.join(cell.text for cell in row.cells) for row in table.rows)))
        return result
    raise ValueError('不支持的文件格式。')


def process_version(version_id):
    with engine.connect() as c:
        row = c.execute(text('SELECT * FROM kb_versions WHERE id=:id'), {'id': version_id}).mappings().first()
    if not row:
        return
    try:
        raw = (STORAGE / row['storage_key']).read_bytes()
        parts = extract(raw, Path(row['filename']).suffix.lower())
        chunks = [(label, chunk) for label, body in parts for chunk in rag._chunk_text(body) if chunk.strip()]
        if not chunks:
            raise ValueError('未提取到文字；扫描件请先进行 OCR。')
        vectors = [None] * len(chunks)
        model = ''
        if rag._embedding_enabled():
            for start in range(0, len(chunks), 16):
                values = rag._embed_many([part[1] for part in chunks[start:start+16]])
                if len(values) != len(chunks[start:start+16]):
                    raise ValueError('向量服务返回数量不匹配。')
                vectors[start:start+16] = values
            model = rag.EMBED_MODEL
        with engine.begin() as c:
            # A deleted version must not be resurrected by a late background job.
            existing = c.execute(text('SELECT id FROM kb_versions WHERE id=:id'), {'id': version_id}).first()
            if not existing:
                return
            c.execute(text('DELETE FROM kb_chunks WHERE version_id=:id'), {'id': version_id})
            for i, ((label, body), vector) in enumerate(zip(chunks, vectors)):
                c.execute(text('INSERT INTO kb_chunks(id,version_id,ordinal,content,source_label,embedding,embedding_model) VALUES(:id,:version,:ordinal,:content,:label,:embedding,:model)'), {'id': ident(), 'version': version_id, 'ordinal': i, 'content': body, 'label': label, 'embedding': json.dumps(vector) if vector else None, 'model': model})
            c.execute(text("UPDATE kb_versions SET status='pending_confirmation',error='' WHERE id=:id"), {'id': version_id})
    except Exception as exc:
        logger.exception('品牌资料解析失败')
        with engine.begin() as c:
            c.execute(text("UPDATE kb_versions SET status='failed',error=:error WHERE id=:id"), {'id': version_id, 'error': str(exc)[:500]})


@router.get('/brands/{brand_id}/documents')
def documents(brand_id: str, purpose: Literal['all','knowledge','product_image'] = 'all', q: str = '', category: str = '', page: int = 1, page_size: int = 10, user: str = Depends(get_workspace)):
    if page < 1 or page_size < 1 or page_size > 100 or len(q) > 200:
        raise HTTPException(422, '分页或搜索参数无效。')
    with engine.connect() as c:
        owned(c, brand_id, user)
        clauses = ['brand_id=:brand']
        params = {'brand': brand_id}
        if purpose != 'all':
            clauses.append('purpose=:purpose')
            params['purpose'] = purpose
        if category:
            clauses.append('category=:category')
            params['category'] = category
        if q.strip():
            clauses.append("LOWER(name) LIKE :q ESCAPE '\\'")
            params['q'] = '%'+q.strip().lower().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        where = ' AND '.join(clauses)
        total = c.execute(text('SELECT COUNT(*) FROM kb_documents WHERE '+where), params).scalar_one()
        pages = max(1,(total+page_size-1)//page_size)
        page = min(page,pages)
        docs = c.execute(text('SELECT * FROM kb_documents WHERE '+where+' ORDER BY created DESC LIMIT :limit OFFSET :offset'), {**params, 'limit':page_size,'offset':(page-1)*page_size}).mappings().all()
        output = []
        for doc in docs:
            versions = c.execute(text('SELECT id,filename,mime,status,error,created FROM kb_versions WHERE document_id=:id ORDER BY created DESC'), {'id': doc['id']}).mappings().all()
            output.append({**dict(doc), 'versions': [dict(v) for v in versions]})
    return {'documents': output, 'total': total, 'page': page, 'pages': pages}


@router.post('/brands/{brand_id}/documents', status_code=201)
async def upload(brand_id: str, background: BackgroundTasks, file: UploadFile = File(...), document_id: str = '', purpose: Literal['knowledge','product_image'] = 'knowledge', category: Literal['品牌资料','产品说明','活动规则','其他'] = '品牌资料', user: str = Depends(get_workspace)):
    filename = Path((file.filename or '').replace('\\', '/')).name
    suffix = Path(filename).suffix.lower()
    if suffix not in ('.txt', '.md', '.csv', '.pdf', '.docx', '.png', '.jpg', '.jpeg', '.webp'):
        raise HTTPException(422, '支持 TXT、Markdown、CSV、PDF、DOCX、PNG、JPEG、WebP。')
    raw = await file.read(MAX_FILE + 1)
    if not raw or len(raw) > MAX_FILE:
        raise HTTPException(422, '文件为空或超过 10MB。')
    kind = 'image' if suffix in ('.png', '.jpg', '.jpeg', '.webp') else 'document'
    if kind == 'image':
        valid = (suffix == '.png' and raw.startswith(b'\x89PNG\r\n\x1a\n')) or (suffix in ('.jpg', '.jpeg') and raw.startswith(b'\xff\xd8\xff')) or (suffix == '.webp' and raw.startswith(b'RIFF') and raw[8:12] == b'WEBP')
        if not valid:
            raise HTTPException(422, '图片格式与文件内容不一致。')
    updating = bool(document_id)
    document_id = document_id or ident()
    version_id, key = ident(), ident()
    target = STORAGE / key
    with engine.begin() as c:
        lock_workspace(c)
        owned(c, brand_id, user)
        existing = c.execute(text('SELECT * FROM kb_documents WHERE id=:id AND brand_id=:brand'), {'id': document_id, 'brand': brand_id}).mappings().first()
        if updating and not existing:
            raise HTTPException(404, '资料不存在。')
        if existing and existing['kind'] != kind:
            raise HTTPException(422, '新版本的文件类型不匹配。')
        if not existing:
            c.execute(text('INSERT INTO kb_documents(id,brand_id,name,kind,active_version,created,purpose,category) VALUES(:id,:brand,:name,:kind,NULL,:created,:purpose,:category)'), {'id': document_id, 'brand': brand_id, 'name': filename, 'kind': kind, 'created': time.time_ns(), 'purpose':purpose,'category':category})
        target.write_bytes(raw)
        try:
            c.execute(text('INSERT INTO kb_versions(id,document_id,storage_key,filename,mime,status,error,created) VALUES(:id,:doc,:key,:filename,:mime,:status,:error,:created)'), {'id': version_id, 'doc': document_id, 'key': key, 'filename': filename, 'mime': file.content_type or 'application/octet-stream', 'status': 'active' if kind == 'image' else 'processing', 'error': '', 'created': time.time_ns()})
            if kind == 'image':
                c.execute(text('UPDATE kb_documents SET active_version=:version WHERE id=:id'), {'version': version_id, 'id': document_id})
        except Exception:
            target.unlink(missing_ok=True)
            raise
    if kind == 'document':
        background.add_task(process_version, version_id)
    return {'id': document_id, 'version_id': version_id, 'status': 'active' if kind == 'image' else 'processing'}


@router.get('/brands/{brand_id}/documents/{doc_id}/versions/{version_id}')
def version_preview(brand_id: str, doc_id: str, version_id: str, user: str = Depends(get_workspace)):
    with engine.connect() as c:
        owned(c, brand_id, user)
        version = c.execute(text('SELECT v.* FROM kb_versions v JOIN kb_documents d ON d.id=v.document_id WHERE v.id=:version AND d.id=:doc AND d.brand_id=:brand'), {'version': version_id, 'doc': doc_id, 'brand': brand_id}).mappings().first()
        if not version:
            raise HTTPException(404, '文件版本不存在。')
        chunks = c.execute(text('SELECT content,source_label FROM kb_chunks WHERE version_id=:version ORDER BY ordinal'), {'version': version_id}).mappings().all()
    candidates = []
    if version['status'] == 'pending_confirmation' and Path(version['filename']).suffix.lower() == '.csv':
        try:
            content = (STORAGE / version['storage_key']).read_text(encoding='utf-8-sig')
            for row in csv.DictReader(io.StringIO(content)):
                name = (row.get('产品名') or row.get('产品名称') or row.get('名称') or row.get('name') or '').strip()
                if name:
                    candidates.append({'name': name, 'price': (row.get('价格') or row.get('price') or '').strip(), 'selling': (row.get('卖点') or row.get('selling') or row.get('selling_points') or '').strip()})
                if len(candidates) >= 100:
                    break
        except (UnicodeError, csv.Error):
            pass
    with engine.connect() as c:
        organized = c.execute(text('SELECT payload,confirmed FROM kb_extractions WHERE version_id=:id'), {'id': version_id}).mappings().first()
    proposal = json.loads(organized['payload']) if organized else {}
    return {'version': {k: version[k] for k in ('id', 'filename', 'status', 'error')}, 'chunks': [dict(r) for r in chunks], 'product_candidates': proposal.get('products', candidates), 'brand_candidate': proposal.get('brand', {}), 'source_text': proposal.get('source_text', ''), 'organized': bool(organized), 'confirmed': bool(organized and organized['confirmed'])}


class ConfirmProduct(ProductInput):
    id: str = ''


class ConfirmDocument(BaseModel):
    brand: BrandInput | None = None
    products: list[ConfirmProduct] = Field(default_factory=list, max_length=100)


@router.post('/brands/{brand_id}/documents/{doc_id}/versions/{version_id}/confirm')
def confirm_version(brand_id: str, doc_id: str, version_id: str, req: ConfirmDocument = ConfirmDocument(), user: str = Depends(get_workspace)):
    with engine.begin() as c:
        lock_workspace(c)
        owned(c, brand_id, user)
        row = c.execute(text('SELECT v.status FROM kb_versions v JOIN kb_documents d ON d.id=v.document_id WHERE v.id=:version AND d.id=:doc AND d.brand_id=:brand'), {'version': version_id, 'doc': doc_id, 'brand': brand_id}).first()
        if not row:
            raise HTTPException(404, '文件版本不存在。')
        extracted = c.execute(text('SELECT payload,confirmed FROM kb_extractions WHERE version_id=:id'), {'id': version_id}).mappings().first()
        if extracted and extracted['confirmed']:
            raise HTTPException(409, '该整理结果已确认。')
        if row[0] != 'pending_confirmation' and not extracted:
            raise HTTPException(409, '该版本尚未准备好确认。')
        c.execute(text("UPDATE kb_versions SET status='superseded' WHERE document_id=:doc AND status='active'"), {'doc': doc_id})
        c.execute(text("UPDATE kb_versions SET status='active' WHERE id=:version"), {'version': version_id})
        c.execute(text('UPDATE kb_documents SET active_version=:version WHERE id=:doc AND brand_id=:brand'), {'version': version_id, 'doc': doc_id, 'brand': brand_id})
        if extracted:
            source = json.loads(extracted['payload']).get('source_text', '')
            c.execute(text('DELETE FROM kb_chunks WHERE version_id=:id'), {'id': version_id})
            for ordinal, offset in enumerate(range(0, len(source), 600)):
                c.execute(text("INSERT INTO kb_chunks(id,version_id,ordinal,content,source_label,embedding,embedding_model) VALUES(:id,:version,:ordinal,:content,'确认资料',NULL,'')"), {'id': ident(), 'version': version_id, 'ordinal': ordinal, 'content': source[offset:offset+700]})
            c.execute(text('UPDATE kb_extractions SET confirmed=1 WHERE version_id=:id'), {'id': version_id})
        if req.brand:
            c.execute(text('UPDATE kb_brands SET name=:name,description=:intro,positioning=:position,style=:style,preference=:preference WHERE id=:id'), {'id': brand_id, **req.brand.model_dump()})
        for product in req.products:
            if product.id:
                existing = c.execute(text('SELECT id,image_document_id FROM kb_products WHERE id=:id AND brand_id=:brand'), {'id': product.id, 'brand': brand_id}).mappings().first()
                if not existing:
                    raise HTTPException(404, '待更新产品不属于当前品牌。')
                image_id = product.image_document_id or existing['image_document_id']
                validate_image(c, brand_id, image_id)
                c.execute(text('UPDATE kb_products SET name=:name,price=:price,selling=:selling,category=:category,archived=:archived,image_document_id=:image_document_id,updated=:updated WHERE id=:id AND brand_id=:brand'), {**product.model_dump(), 'image_document_id': image_id, 'brand': brand_id, 'updated': time.time_ns()})
                continue
            validate_image(c, brand_id, product.image_document_id)
            c.execute(text('INSERT INTO kb_products(id,brand_id,name,price,selling,image_document_id,category,archived,updated) VALUES(:id,:brand,:name,:price,:selling,:image_document_id,:category,:archived,:updated)'), {'id': ident(), 'brand': brand_id, 'updated': time.time_ns(), **product.model_dump(exclude={'id'})})
        if req.products or req.brand:
            bump_revision(c, user, brand_id)
    return {'ok': True, 'imported_products': len(req.products)}


@router.post('/brands/{brand_id}/documents/{doc_id}/versions/{version_id}/retry')
def retry_version(brand_id: str, doc_id: str, version_id: str, background: BackgroundTasks, user: str = Depends(get_workspace)):
    with engine.begin() as c:
        lock_workspace(c)
        owned(c, brand_id, user)
        row = c.execute(text("UPDATE kb_versions SET status='processing',error='' WHERE id=:version AND document_id=:doc AND status='failed' AND EXISTS (SELECT 1 FROM kb_documents WHERE id=:doc AND brand_id=:brand)"), {'version': version_id, 'doc': doc_id, 'brand': brand_id})
        if not row.rowcount:
            raise HTTPException(409, '该版本不存在或不能重试。')
    background.add_task(process_version, version_id)
    return {'status': 'processing'}


@router.get('/brands/{brand_id}/documents/{doc_id}/file')
def get_file(brand_id: str, doc_id: str, user: str = Depends(get_workspace)):
    with engine.connect() as c:
        owned(c, brand_id, user)
        row = c.execute(text('SELECT v.* FROM kb_documents d JOIN kb_versions v ON v.id=d.active_version WHERE d.id=:doc AND d.brand_id=:brand'), {'doc': doc_id, 'brand': brand_id}).mappings().first()
    if not row:
        raise HTTPException(404, '没有可用文件。')
    suffix = Path(row['filename']).suffix.lower()
    image_mime = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}
    return FileResponse(STORAGE / row['storage_key'], media_type=image_mime.get(suffix, 'application/octet-stream'), filename=row['filename'], content_disposition_type='inline' if suffix in image_mime else 'attachment', headers={'X-Content-Type-Options': 'nosniff'})


@router.delete('/brands/{brand_id}/documents/{doc_id}')
def delete_document(brand_id: str, doc_id: str, user: str = Depends(get_workspace)):
    with engine.begin() as c:
        lock_workspace(c)
        owned(c, brand_id, user)
        doc = c.execute(text('SELECT id FROM kb_documents WHERE id=:id AND brand_id=:brand'), {'id': doc_id, 'brand': brand_id}).first()
        if not doc:
            raise HTTPException(404, '资料不存在。')
        versions = c.execute(text('SELECT id,storage_key FROM kb_versions WHERE document_id=:id'), {'id': doc_id}).mappings().all()
        for v in versions:
            c.execute(text('DELETE FROM kb_chunks WHERE version_id=:id'), {'id': v['id']})
        c.execute(text("UPDATE kb_products SET image_document_id='' WHERE brand_id=:brand AND image_document_id=:doc"), {'brand': brand_id, 'doc': doc_id})
        for v in versions:
            c.execute(text('DELETE FROM kb_extractions WHERE version_id=:id'), {'id': v['id']})
        c.execute(text('DELETE FROM kb_versions WHERE document_id=:id'), {'id': doc_id})
        c.execute(text('DELETE FROM kb_documents WHERE id=:id AND brand_id=:brand'), {'id': doc_id, 'brand': brand_id})
        bump_revision(c, user, brand_id)
    for v in versions:
        (STORAGE / v['storage_key']).unlink(missing_ok=True)
    return {'ok': True}


def search_brand(brand_id: str, user: str, query: str, limit=4):
    with engine.connect() as c:
        owned(c, brand_id, user)
        rows = c.execute(text('SELECT c.content,c.source_label,c.embedding,c.embedding_model,d.id AS document_id,d.name AS title,v.id AS version_id FROM kb_documents d JOIN kb_versions v ON v.id=d.active_version JOIN kb_chunks c ON c.version_id=v.id WHERE d.brand_id=:brand AND v.status=\'active\''), {'brand': brand_id}).mappings().all()
    qvec = ()
    if rag._embedding_enabled() and any(r['embedding'] and r['embedding_model'] == rag.EMBED_MODEL for r in rows):
        try:
            qvec = rag._embed_query(query)
        except Exception:
            logger.warning('品牌资料向量检索不可用，回退关键词', exc_info=True)
    results = []
    for row in rows:
        lex = rag._lexical_score(query, row['content'])
        vec = 0.0
        if qvec and row['embedding'] and row['embedding_model'] == rag.EMBED_MODEL:
            try:
                vector = json.loads(row['embedding']) if isinstance(row['embedding'], str) else list(row['embedding'])
                vec = max(0.0, rag._cosine(qvec, vector))
            except (ValueError, TypeError):
                pass
        score = .65 * lex + .35 * vec if qvec else lex
        if score >= .06:
            results.append({'document_id': row['document_id'], 'version_id': row['version_id'], 'title': row['title'], 'source_label': row['source_label'], 'text': row['content'][:1000], 'score': round(score, 4)})
    with engine.connect() as c:
        products = c.execute(text('SELECT * FROM kb_products WHERE brand_id=:brand AND archived=0'), {'brand': brand_id}).mappings().all()
    for product in products:
        if product['name'] in query or query.strip() in product['name']:
            results.append({'document_id': 'product:'+product['id'], 'version_id': str(product['updated']), 'title': product['name'], 'source_label': '当前产品资料', 'text': product['name']+'；当前价格：'+product['price']+'；卖点：'+product['selling'], 'score': 1.0})
    return sorted(results, key=lambda r: r['score'], reverse=True)[:limit]


@router.get('/brands/{brand_id}/search')
def search_endpoint(brand_id: str, q: str, user: str = Depends(get_workspace)):
    if not q.strip() or len(q) > 300:
        raise HTTPException(422, '查询长度应为 1–300 字符。')
    return {'results': search_brand(brand_id, user, q)}


def resolve_campaign(payload, user):
    brand_id = payload['brand']['id']
    with engine.connect() as c:
        b = owned(c, brand_id, user)
        products = []
        for item in payload['products']:
            row = c.execute(text('SELECT * FROM kb_products WHERE id=:id AND brand_id=:brand'), {'id': item['id'], 'brand': brand_id}).mappings().first()
            if not row:
                raise HTTPException(404, '产品不存在或不属于当前品牌。')
            if row['archived']:
                raise HTTPException(409, '所选产品已归档，请重新选择。')
            products.append({'id': row['id'], 'name': row['name'], 'price': row['price'] or None, 'selling_points': [x.strip() for x in row['selling'].replace('，','、').replace(',','、').split('、') if x.strip()]})
    payload['brand'].update({'name': b['name'], 'description': b['description'], 'positioning': b['positioning']})
    payload['products'] = products
    from .studio import memory_context
    payload['brand_memories'] = memory_context(brand_id, user)
    query = ' '.join([b['name'], payload.get('theme',''), payload.get('additional_selling_points',''), *[p['name'] + ' ' + ' '.join(p['selling_points']) for p in products]])
    payload['brand_references'] = search_brand(brand_id, user, query)
    return payload


init_db()
