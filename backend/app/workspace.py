"""Single shared workspace. Legacy user columns remain storage keys, not identities."""
import json
import os
import time
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, text
from . import knowledge as kb

router = APIRouter(prefix='/api/knowledge')


def local_only():
    return os.getenv('WORKSPACE_LOCAL_ONLY', 'true').lower() != 'false'


async def middleware(request, call_next):
    if local_only():
        local = {'localhost','127.0.0.1','::1'}
        origin = request.headers.get('origin')
        same_origin = not origin or (urlsplit(origin).netloc==request.headers.get('host') and urlsplit(origin).scheme in ('http','https'))
        forwarded = any(h in request.headers for h in ('forwarded','x-forwarded-for','x-forwarded-host','x-forwarded-proto'))
        if not request.client or request.client.host not in local or request.url.hostname not in local or forwarded or not same_origin:
            return JSONResponse({'detail':'当前共享工作空间仅允许本机直接访问。'},status_code=403)
    return await call_next(request)


def migrate_legacy():
    """Keep brands/works/files and merge draft namespaces before removing credentials."""
    tables = set(inspect(kb.engine).get_table_names())
    legacy = {'kb_users','kb_sessions','kb_members','kb_identities','kb_phone_codes','kb_phone_cooldown','kb_auth_limits','kb_invitations'}
    with kb.engine.begin() as c:
        kb.lock_workspace(c)
        c.execute(text('CREATE TABLE IF NOT EXISTS kb_migration_archive (id TEXT PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL,created BIGINT NOT NULL)'))
        drafts = c.execute(text('SELECT * FROM kb_drafts ORDER BY updated DESC,revision DESC,user_id')).mappings().all()
        chosen = {}
        for row in drafts:
            if row['brand_id'] not in chosen:
                chosen[row['brand_id']] = dict(row)
            elif row['user_id'] != kb.SHARED_WORKSPACE or chosen[row['brand_id']]['user_id'] != kb.SHARED_WORKSPACE:
                c.execute(text('INSERT INTO kb_migration_archive(id,kind,payload,created) VALUES(:id,\'legacy_draft\',:payload,:now)'), {'id':kb.ident(),'payload':json.dumps(dict(row),ensure_ascii=False),'now':time.time_ns()})
        if any(row['user_id']!=kb.SHARED_WORKSPACE for row in drafts):
            c.execute(text('DELETE FROM kb_drafts'))
            for row in chosen.values():
                c.execute(text('INSERT INTO kb_drafts(user_id,brand_id,payload,revision,updated) VALUES(:user,:brand,:payload,:revision,:updated)'),{'user':kb.SHARED_WORKSPACE,'brand':row['brand_id'],'payload':row['payload'],'revision':row['revision']+1,'updated':row['updated']})
        for row in c.execute(text('SELECT id FROM kb_jobs WHERE user_id<>:user'),{'user':kb.SHARED_WORKSPACE}).mappings():
            c.execute(text('UPDATE kb_jobs SET user_id=:user,request_key=:key WHERE id=:id'),{'user':kb.SHARED_WORKSPACE,'key':'migrated:'+row['id'],'id':row['id']})
        c.execute(text('UPDATE kb_brands SET owner_id=:user WHERE owner_id<>:user'),{'user':kb.SHARED_WORKSPACE})
        if tables & legacy:
            c.execute(text('DELETE FROM kb_revisions'))
            kb.bump_revision(c,kb.SHARED_WORKSPACE)
        for table in sorted(tables & legacy):
            c.execute(text('DROP TABLE '+table))


@router.get('/workspace-info')
def info():
    from .config import USE_MOCK,USE_IMAGE_MOCK
    tables = set(inspect(kb.engine).get_table_names())
    with kb.engine.connect() as c:
        brands = c.execute(text('SELECT COUNT(*) FROM kb_brands')).scalar_one()
        products = c.execute(text('SELECT COUNT(*) FROM kb_products')).scalar_one()
        images = c.execute(text("SELECT COUNT(*) FROM kb_products WHERE image_document_id<>''")).scalar_one()
    return {'id':kb.SHARED_WORKSPACE,'name':'共享品牌工作空间','reference_data':'local_catalog_sources' in tables,'local_only':local_only(),'brands':brands,'products':products,'product_images':images,'copy_mock':USE_MOCK,'image_mock':USE_IMAGE_MOCK,'note':'资料由当前工作空间共享；历史来源价格发布前请核对。'}


@router.get('/brands/{brand_id}/catalog-sources')
def sources(brand_id: str, workspace_id: str = Depends(kb.get_workspace)):
    with kb.engine.connect() as c:
        kb.owned(c,brand_id,workspace_id)
        if 'local_catalog_sources' not in inspect(kb.engine).get_table_names():
            return {'sources':[]}
        rows = c.execute(text('SELECT s.* FROM local_catalog_sources s JOIN kb_products p ON p.id=s.product_id WHERE p.brand_id=:brand'),{'brand':brand_id}).mappings().all()
    return {'sources':[dict(row) for row in rows]}
