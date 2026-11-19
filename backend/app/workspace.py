"""Workspace-scoped metadata and optional loopback transport protection."""
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
    """Historical workspace merging is disabled; migration must preserve ownership."""
    return


@router.get('/workspace-info')
def info(user: str = Depends(kb.get_workspace)):
    from .config import USE_MOCK,USE_IMAGE_MOCK
    tables = set(inspect(kb.engine).get_table_names())
    with kb.engine.connect() as c:
        brands = c.execute(text('SELECT COUNT(*) FROM kb_brands WHERE owner_id=:user'), {'user':user}).scalar_one()
        products = c.execute(text('SELECT COUNT(*) FROM kb_products WHERE brand_id IN (SELECT id FROM kb_brands WHERE owner_id=:user)'), {'user':user}).scalar_one()
        images = c.execute(text("SELECT COUNT(*) FROM kb_products WHERE image_document_id<>'' AND brand_id IN (SELECT id FROM kb_brands WHERE owner_id=:user)"), {'user':user}).scalar_one()
    return {'id':user,'name':'共享品牌工作空间','reference_data':'local_catalog_sources' in tables,'local_only':local_only(),'brands':brands,'products':products,'product_images':images,'copy_mock':USE_MOCK,'image_mock':USE_IMAGE_MOCK,'note':'资料由当前工作空间共享；历史来源价格发布前请核对。'}


@router.get('/brands/{brand_id}/catalog-sources')
def sources(brand_id: str, workspace_id: str = Depends(kb.get_workspace)):
    with kb.engine.connect() as c:
        kb.owned(c,brand_id,workspace_id)
        if 'local_catalog_sources' not in inspect(kb.engine).get_table_names():
            return {'sources':[]}
        rows = c.execute(text('SELECT s.* FROM local_catalog_sources s JOIN kb_products p ON p.id=s.product_id WHERE p.brand_id=:brand'),{'brand':brand_id}).mappings().all()
    return {'sources':[dict(row) for row in rows]}
