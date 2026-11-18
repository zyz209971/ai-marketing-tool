"""Database-backed local worker. Queued jobs survive restart; abandoned work needs explicit retry."""
import base64
import io
import json
import os
import socket
import ipaddress
import threading
import time
from urllib.parse import urlsplit
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pydantic import ValidationError
from typing import Literal
from sqlalchemy import text
from . import knowledge as kb, quota, materials, organization
from .providers import campaign, image
from .v2 import Campaign, ImageRequest, require_access

router = APIRouter(prefix='/api/knowledge', dependencies=[Depends(require_access)])
STOP = threading.Event()
WORKER = None


def init_db():
    with kb.engine.begin() as c:
        c.execute(text('CREATE TABLE IF NOT EXISTS kb_jobs (id TEXT PRIMARY KEY,user_id TEXT NOT NULL,brand_id TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL,context TEXT NOT NULL,status TEXT NOT NULL,result TEXT NOT NULL,error TEXT NOT NULL,created BIGINT NOT NULL,heartbeat BIGINT NOT NULL,request_key TEXT NOT NULL,UNIQUE(user_id,request_key))'))


class JobInput(BaseModel):
    brand_id: str
    kind: Literal['copy', 'image', 'organize']
    payload: dict
    context: dict = Field(default_factory=dict)
    request_key: str = Field(min_length=8, max_length=100)


@router.post('/jobs', status_code=202)
def create(req: JobInput, user: str = Depends(kb.get_workspace)):
    serialized = json.dumps(req.payload, ensure_ascii=False)
    context = json.dumps(req.context, ensure_ascii=False)
    if len(serialized.encode()) + len(context.encode()) > 12000000:
        raise HTTPException(422, '任务内容过大。')
    try:
        model = Campaign.model_validate(req.payload) if req.kind == 'copy' else ImageRequest.model_validate(req.payload).campaign if req.kind == 'image' else None
    except ValidationError:
        raise HTTPException(422, '创作参数不完整，请核对品牌、产品和活动信息。') from None
    if model:
        if model.brand.id != req.brand_id:
            raise HTTPException(422, '品牌不匹配。')
    with kb.engine.begin() as c:
        kb.lock_workspace(c)
        kb.owned(c, req.brand_id, user)
        prior = c.execute(text('SELECT id,brand_id,kind,payload FROM kb_jobs WHERE user_id=:user AND request_key=:key'), {'user': user, 'key': req.request_key}).mappings().first()
        if prior:
            if prior['brand_id'] != req.brand_id or prior['kind'] != req.kind or prior['payload'] != serialized:
                raise HTTPException(409, '请求标识已用于其他任务。')
            return {'id': prior['id']}
        if c.execute(text("SELECT COUNT(*) FROM kb_jobs WHERE user_id=:user AND status IN ('queued','running')"), {'user': user}).scalar_one() >= 5:
            raise HTTPException(429, '最多同时提交 5 个任务。')
        jid = kb.ident()
        c.execute(text("INSERT INTO kb_jobs(id,user_id,brand_id,kind,payload,context,status,result,error,created,heartbeat,request_key) VALUES(:id,:user,:brand,:kind,:payload,:context,'queued','{}','',:now,:now,:key)"), {'id': jid, 'user': user, 'brand': req.brand_id, 'kind': req.kind, 'payload': serialized, 'context': context, 'now': int(time.time()), 'key': req.request_key})
    return {'id': jid}


def visible(c, jid, user):
    row = c.execute(text('SELECT * FROM kb_jobs WHERE id=:id AND user_id=:user'), {'id': jid, 'user': user}).mappings().first()
    if not row:
        raise HTTPException(404, '任务不存在。')
    kb.owned(c, row['brand_id'], user)
    return dict(row)


@router.get('/jobs/{job_id}')
def detail(job_id: str, user: str = Depends(kb.get_workspace)):
    with kb.engine.connect() as c:
        row = visible(c, job_id, user)
    return {k: json.loads(row[k]) if k in ('context', 'result') else row[k] for k in ('id','kind','status','error','created','context','result')}


@router.get('/brands/{brand_id}/jobs')
def listing(brand_id: str, user: str = Depends(kb.get_workspace)):
    with kb.engine.connect() as c:
        kb.owned(c, brand_id, user)
        rows = c.execute(text('SELECT id,kind,status,error,created FROM kb_jobs WHERE brand_id=:brand AND user_id=:user ORDER BY created DESC LIMIT 30'), {'brand': brand_id, 'user': user}).mappings().all()
    return {'jobs': [dict(row) for row in rows]}


@router.post('/jobs/{job_id}/retry')
def retry(job_id: str, user: str = Depends(kb.get_workspace)):
    with kb.engine.begin() as c:
        kb.lock_workspace(c)
        row = visible(c, job_id, user)
        if row['status'] != 'failed':
            raise HTTPException(409, '只有失败任务可以重试。')
        if c.execute(text("SELECT COUNT(*) FROM kb_jobs WHERE user_id=:user AND status IN ('queued','running')"), {'user': user}).scalar_one() >= 5:
            raise HTTPException(429, '请等待已有任务完成后重试。')
        c.execute(text("UPDATE kb_jobs SET status='queued',error='',heartbeat=:now WHERE id=:id"), {'id': job_id, 'now': int(time.time())})
    return {'id': job_id}


def persist_ai(brand_id, result):
    if result.get('error') or result.get('mock'):
        raise ValueError('真实生图服务尚未配置或生成失败；可选择产品实拍排版。')
    if result.get('base64'):
        if len(result['base64']) > 20000000:
            raise ValueError('图片超过 15MB。')
        raw = base64.b64decode(result['base64'], validate=True)
    else:
        url = result.get('url', '')
        parsed = urlsplit(url)
        allowed = os.getenv('BRAND_IMAGE_ALLOWED_HOSTS', '').split(',')
        if parsed.scheme != 'https' or parsed.hostname not in [h.strip() for h in allowed] or parsed.username or parsed.password:
            raise ValueError('请把生图返回的可信图片域名配置到 BRAND_IMAGE_ALLOWED_HOSTS 后重试。')
        for address in socket.getaddrinfo(parsed.hostname, 443):
            if not ipaddress.ip_address(address[4][0]).is_global:
                raise ValueError('图片来源地址不可用。')
        output = io.BytesIO()
        with httpx.stream('GET', url, timeout=30, follow_redirects=False, trust_env=False) as response:
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError('图片下载失败。')
            for chunk in response.iter_bytes():
                output.write(chunk)
                if output.tell() > 15000000:
                    raise ValueError('图片超过 15MB。')
        raw = output.getvalue()
    return materials.store(brand_id, raw)


def execute(row):
    payload, user, brand = json.loads(row['payload']), row['user_id'], row['brand_id']
    with kb.engine.connect() as c:
        kb.owned(c, brand, user)
    if row['kind'] == 'organize':
        return organization.analyze(brand, payload.get('version_id'), user)
    if not quota.check_quota('workspace:'+user)['allowed']:
        raise ValueError('生成额度不足。')
    if row['kind'] == 'copy':
        verified = kb.resolve_campaign(Campaign.model_validate(payload).model_dump(), user)
        result = {'contents': campaign.generate(verified)}
        quota.consume('workspace:'+user)
        return result
    req = ImageRequest.model_validate(payload)
    verified = kb.resolve_campaign(req.campaign.model_dump(), user)
    ids = req.content.product_ids or [p['id'] for p in verified['products']]
    if any(pid not in {p['id'] for p in verified['products']} for pid in ids):
        raise ValueError('配图产品不在本次创作中。')
    if payload.get('image_mode', 'photo') == 'photo':
        return materials.photo_gallery(brand, user, req.content.model_dump(), ids, min(6, max(1, int(payload.get('image_count', 3)))))
    prompt = json.dumps({'品牌': verified['brand'], '产品': verified['products'], '活动': verified, '文案': req.content.model_dump(), '要求': '按平台生成营销配图，仅使用已提供的事实。'}, ensure_ascii=False)
    asset = persist_ai(brand, image.generate_image(prompt))
    quota.consume('workspace:'+user)
    return {'gallery': [asset], 'image': asset, 'method': 'ai', 'mock': False, 'final_prompt': prompt}


def run_once():
    now = int(time.time())
    with kb.engine.begin() as c:
        kb.lock_workspace(c)
        c.execute(text("UPDATE kb_jobs SET status='failed',error='服务中断，请确认后重试。' WHERE status='running' AND heartbeat<:old"), {'old': now-180})
        row = c.execute(text("SELECT * FROM kb_jobs WHERE status='queued' ORDER BY created LIMIT 1")).mappings().first()
        if not row:
            return False
        row = dict(row)
        c.execute(text("UPDATE kb_jobs SET status='running',heartbeat=:now WHERE id=:id"), {'now': now, 'id': row['id']})
    done = threading.Event()
    def heartbeat():
        while not done.wait(10):
            with kb.engine.begin() as c:
                c.execute(text('UPDATE kb_jobs SET heartbeat=:now WHERE id=:id'), {'id': row['id'], 'now': int(time.time())})
    pulse = threading.Thread(target=heartbeat, daemon=True)
    pulse.start()
    try:
        result = execute(row)
        with kb.engine.begin() as c:
            kb.owned(c, row['brand_id'], row['user_id'])
            c.execute(text("UPDATE kb_jobs SET status='succeeded',result=:result,error='' WHERE id=:id"), {'id': row['id'], 'result': json.dumps(result, ensure_ascii=False)})
    except Exception as exc:
        error = exc.detail if isinstance(exc, HTTPException) else str(exc) if isinstance(exc, ValueError) else '任务执行失败，请检查模型配置后重试。'
        with kb.engine.begin() as c:
            c.execute(text("UPDATE kb_jobs SET status='failed',error=:error WHERE id=:id"), {'id': row['id'], 'error': error[:500]})
    finally:
        done.set()
        pulse.join(timeout=2)
    return True


def start():
    global WORKER
    STOP.clear()
    def loop():
        while not STOP.is_set():
            try:
                if not run_once():
                    STOP.wait(1)
            except Exception:
                STOP.wait(2)
    WORKER = threading.Thread(target=loop, daemon=True)
    WORKER.start()


def stop():
    STOP.set()
    if WORKER:
        WORKER.join(timeout=2)


init_db()
