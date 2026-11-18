"""Small-team sessions and workspace context; no public self-registration."""
import hashlib
import hmac
import os
import secrets
import time
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import urlsplit
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

LOCAL_WORKSPACE = 'local-preview-workspace'
CURRENT_WORKSPACE = ContextVar('workspace', default=None)
router = APIRouter(prefix='/api/auth', tags=['session'])


def enabled():
    mode = os.getenv('AUTH_MODE','local')
    if mode not in ('local','session'):
        raise RuntimeError('AUTH_MODE must be local or session')
    return mode == 'session'


def workspace_id():
    current = CURRENT_WORKSPACE.get()
    if current:
        return current
    if enabled():
        raise HTTPException(401,'请先登录。')
    return LOCAL_WORKSPACE


@contextmanager
def workspace_scope(workspace):
    token = CURRENT_WORKSPACE.set(workspace)
    try:
        yield
    finally:
        CURRENT_WORKSPACE.reset(token)


def init_db():
    from .knowledge import engine
    with engine.begin() as c:
        for sql in [
            'CREATE TABLE IF NOT EXISTS auth_users (username TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, password_hash TEXT NOT NULL)',
            'CREATE TABLE IF NOT EXISTS auth_sessions (token_hash TEXT PRIMARY KEY, username TEXT NOT NULL, expires BIGINT NOT NULL)',
            'CREATE TABLE IF NOT EXISTS auth_attempts (id TEXT PRIMARY KEY, attempts INTEGER NOT NULL, window_start BIGINT NOT NULL)',
        ]: c.execute(text(sql))


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    derived = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 260000).hex()
    return salt+':'+derived


def provision(username, password, workspace):
    if not username.strip() or not workspace.strip() or len(password)<12:
        raise ValueError('用户名和工作区不能为空，密码至少12位。')
    from .knowledge import engine
    with engine.begin() as c:
        c.execute(text('INSERT INTO auth_users(username,workspace_id,password_hash) VALUES(:user,:workspace,:hash)'),
                  {'user':username,'workspace':workspace,'hash':password_hash(password)})


class Login(BaseModel):
    username: str = Field(min_length=1,max_length=100)
    password: str = Field(min_length=1,max_length=256)


@router.get('/mode')
def mode():
    return {'login_required':enabled()}


@router.post('/login')
def login(req: Login, request: Request, response: Response):
    if not enabled():
        raise HTTPException(409,'当前是本机模式，无需登录。')
    from .knowledge import engine, lock_workspace
    now = int(time.time())
    limit_id = hashlib.sha256((str(request.client.host if request.client else '')+'|'+req.username).encode()).hexdigest()
    with engine.begin() as c:
        lock_workspace(c)
        attempt = c.execute(text('SELECT * FROM auth_attempts WHERE id=:id'),{'id':limit_id}).mappings().first()
        count = attempt['attempts'] if attempt and now-attempt['window_start']<900 else 0
        if count>=10:
            raise HTTPException(429,'登录尝试过多，请15分钟后重试。')
        c.execute(text('INSERT INTO auth_attempts(id,attempts,window_start) VALUES(:id,:count,:start) ON CONFLICT(id) DO UPDATE SET attempts=:count,window_start=:start'),
                  {'id':limit_id,'count':count+1,'start':attempt['window_start'] if count else now})
        user = c.execute(text('SELECT * FROM auth_users WHERE username=:user'),{'user':req.username}).mappings().first()
    expected = user['password_hash'] if user else '00'*16+':'+'00'*32
    if not hmac.compare_digest(password_hash(req.password,expected.split(':')[0]),expected):
        raise HTTPException(401,'用户名或密码不正确。')
    token = secrets.token_urlsafe(32)
    with engine.begin() as c:
        c.execute(text('DELETE FROM auth_sessions WHERE expires<:now'),{'now':now})
        c.execute(text('DELETE FROM auth_attempts WHERE id=:id'),{'id':limit_id})
        c.execute(text('INSERT INTO auth_sessions(token_hash,username,expires) VALUES(:hash,:user,:expires)'),
                  {'hash':hashlib.sha256(token.encode()).hexdigest(),'user':req.username,'expires':now+28800})
    response.set_cookie('brandpilot_session',token,httponly=True,secure=os.getenv('COOKIE_SECURE','true')=='true',samesite='strict',max_age=28800)
    return {'ok':True}


@router.post('/logout')
def logout(request: Request,response: Response):
    from .knowledge import engine
    token = request.cookies.get('brandpilot_session','')
    with engine.begin() as c:
        c.execute(text('DELETE FROM auth_sessions WHERE token_hash=:hash'),{'hash':hashlib.sha256(token.encode()).hexdigest()})
    response.delete_cookie('brandpilot_session')
    return {'ok':True}


async def middleware(request, call_next):
    if not enabled():
        with workspace_scope(LOCAL_WORKSPACE):
            return await call_next(request)
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin = request.headers.get('origin')
        if origin and urlsplit(origin).netloc!=request.headers.get('host'):
            return JSONResponse({'detail':'请求来源不匹配。'},status_code=403)
    if not request.url.path.startswith('/api/') or request.url.path in ('/api/auth/mode','/api/auth/login','/api/health'):
        return await call_next(request)
    from .knowledge import engine
    token = request.cookies.get('brandpilot_session','')
    with engine.connect() as c:
        row = c.execute(text('SELECT u.workspace_id FROM auth_sessions s JOIN auth_users u ON u.username=s.username WHERE s.token_hash=:hash AND s.expires>:now'),
                        {'hash':hashlib.sha256(token.encode()).hexdigest(),'now':int(time.time())}).first()
    if not row:
        return JSONResponse({'detail':'请登录后继续。'},status_code=401)
    # Legacy generation writes to a global catalogue. Keep it local until migrated.
    if not request.url.path.startswith(('/api/auth/', '/api/agent/', '/api/knowledge/', '/api/v2/')) and request.url.path not in ('/api/quota','/api/verify_key'):
        return JSONResponse({'detail':'此旧版共享接口在账号模式下已关闭，请使用品牌工作空间。'},status_code=404)
    with workspace_scope(row[0]):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'private, no-store'
        return response
