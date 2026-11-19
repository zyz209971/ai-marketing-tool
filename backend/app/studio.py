"""Brand memories and private, versioned campaign drafts."""
import json
import time
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from . import knowledge as kb

router = APIRouter(prefix='/api/knowledge')


def init_db():
    with kb.engine.begin() as c:
        for sql in [
            'CREATE TABLE IF NOT EXISTS kb_memories (id TEXT PRIMARY KEY,brand_id TEXT NOT NULL,kind TEXT NOT NULL,content TEXT NOT NULL,updated BIGINT NOT NULL)',
            'CREATE TABLE IF NOT EXISTS kb_drafts (user_id TEXT NOT NULL,brand_id TEXT NOT NULL,payload TEXT NOT NULL,revision INTEGER NOT NULL,updated BIGINT NOT NULL,PRIMARY KEY(user_id,brand_id))',
            'CREATE TABLE IF NOT EXISTS kb_extractions (version_id TEXT PRIMARY KEY,payload TEXT NOT NULL,confirmed INTEGER NOT NULL DEFAULT 0)',
            'CREATE TABLE IF NOT EXISTS kb_assets (id TEXT PRIMARY KEY,brand_id TEXT NOT NULL,storage_key TEXT NOT NULL,mime TEXT NOT NULL,created BIGINT NOT NULL)',
        ]:
            c.execute(text(sql))


class Memory(BaseModel):
    kind: Literal['audience', 'tone', 'prohibited', 'other']
    content: str = Field(min_length=1, max_length=1500)


def memory_context(brand_id, user):
    with kb.engine.connect() as c:
        kb.owned(c, brand_id, user)
        return [dict(r) for r in c.execute(text('SELECT id,kind,content,updated FROM kb_memories WHERE brand_id=:brand ORDER BY updated DESC'), {'brand': brand_id}).mappings()]


@router.get('/brands/{brand_id}/memories')
def memories(brand_id: str, user: str = Depends(kb.get_workspace)):
    return {'memories': memory_context(brand_id, user)}


@router.post('/brands/{brand_id}/memories')
def add_memory(brand_id: str, req: Memory, user: str = Depends(kb.get_workspace)):
    with kb.engine.begin() as c:
        kb.lock_workspace(c)
        kb.owned(c, brand_id, user)
        if c.execute(text('SELECT COUNT(*) FROM kb_memories WHERE brand_id=:brand'), {'brand': brand_id}).scalar_one() >= 30:
            raise HTTPException(422, '每个品牌最多保存 30 条记忆，请先整理已有内容。')
        mid = kb.ident()
        c.execute(text('INSERT INTO kb_memories(id,brand_id,kind,content,updated) VALUES(:id,:brand,:kind,:content,:updated)'), {'id': mid, 'brand': brand_id, 'updated': time.time_ns(), **req.model_dump()})
    return {'id': mid, **req.model_dump()}


@router.put('/brands/{brand_id}/memories/{memory_id}')
def edit_memory(brand_id: str, memory_id: str, req: Memory, user: str = Depends(kb.get_workspace)):
    with kb.engine.begin() as c:
        kb.lock_workspace(c)
        kb.owned(c, brand_id, user)
        result = c.execute(text('UPDATE kb_memories SET kind=:kind,content=:content,updated=:updated WHERE id=:id AND brand_id=:brand'), {'id': memory_id, 'brand': brand_id, 'updated': time.time_ns(), **req.model_dump()})
        if not result.rowcount:
            raise HTTPException(404, '记忆不存在。')
    return {'ok': True}


@router.delete('/brands/{brand_id}/memories/{memory_id}')
def delete_memory(brand_id: str, memory_id: str, user: str = Depends(kb.get_workspace)):
    with kb.engine.begin() as c:
        kb.lock_workspace(c)
        kb.owned(c, brand_id, user)
        c.execute(text('DELETE FROM kb_memories WHERE id=:id AND brand_id=:brand'), {'id': memory_id, 'brand': brand_id})
    return {'ok': True}


class Draft(BaseModel):
    revision: int = Field(default=0, ge=0)
    payload: dict


@router.get('/brands/{brand_id}/draft')
def get_draft(brand_id: str, user: str = Depends(kb.get_workspace)):
    with kb.engine.connect() as c:
        kb.owned(c, brand_id, user)
        row = c.execute(text('SELECT * FROM kb_drafts WHERE user_id=:user AND brand_id=:brand'), {'user': user, 'brand': brand_id}).mappings().first()
    return {'revision': row['revision'], 'payload': json.loads(row['payload']), 'updated': row['updated']} if row else {'revision': 0, 'payload': None}


@router.put('/brands/{brand_id}/draft')
def save_draft(brand_id: str, req: Draft, user: str = Depends(kb.get_workspace)):
    payload = json.dumps(req.payload, ensure_ascii=False)
    if len(payload.encode()) > 8 * 1024 * 1024:
        raise HTTPException(422, '草稿超过 8MB，请减少参考图片。')
    with kb.engine.begin() as c:
        kb.lock_workspace(c)
        kb.owned(c, brand_id, user)
        c.execute(text("INSERT INTO kb_drafts(user_id,brand_id,payload,revision,updated) VALUES(:user,:brand,'{}',0,0) ON CONFLICT(user_id,brand_id) DO NOTHING"), {'user': user, 'brand': brand_id})
        updated = c.execute(text('UPDATE kb_drafts SET payload=:payload,revision=revision+1,updated=:now WHERE user_id=:user AND brand_id=:brand AND revision=:revision'), {'user': user, 'brand': brand_id, 'payload': payload, 'revision': req.revision, 'now': time.time_ns()})
        if not updated.rowcount:
            raise HTTPException(409, '草稿已在其他页面更新，请先恢复最新草稿。')
    return {'revision': req.revision + 1}


init_db()
