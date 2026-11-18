"""Explicit long-term preference writes; normal chat never silently becomes memory."""
import time
from fastapi import HTTPException
from sqlalchemy import text
from .. import knowledge as kb, studio


def save_style(task_id, revision):
    from . import store
    from .contracts import Brief
    with kb.engine.begin() as c:
        kb.lock_workspace(c)
        task = store.row(c, task_id)
        if task['active_run'] or task['revision'] != revision:
            raise HTTPException(409, '任务已变化，请刷新后保存偏好。')
        state = store.present(task)['state']
        brand_id, style = state['brief'].get('brand_id'), state['brief']['style']
        if not brand_id or style == Brief().style:
            raise HTTPException(422, '请先选择品牌，并在对话中明确本次表达风格。')
        kb.owned(c, brand_id, kb.get_workspace())
        prior = c.execute(text("SELECT id FROM kb_memories WHERE brand_id=:brand AND kind='tone' ORDER BY updated DESC"), {'brand': brand_id}).first()
        if not prior and c.execute(text('SELECT COUNT(*) FROM kb_memories WHERE brand_id=:brand'), {'brand': brand_id}).scalar_one() >= 30:
            raise HTTPException(422, '该品牌记忆已满，请先在品牌管理中整理。')
        mid = prior[0] if prior else kb.ident()
        c.execute(text('INSERT INTO kb_memories(id,brand_id,kind,content,updated) VALUES(:id,:brand,\'tone\',:content,:updated) ON CONFLICT(id) DO UPDATE SET content=:content,updated=:updated'),
                  {'id': mid, 'brand': brand_id, 'content': style, 'updated': time.time_ns()})
        # The task journal is provenance; the existing preference editor remains authoritative.
        state['messages'].append({'role': 'assistant', 'content': '已按你的确认保存为品牌长期表达偏好：'+style, 'at': store.now(), 'memory_id': mid})
        c.execute(text('UPDATE agent_tasks SET state=:state,revision=revision+1,updated=:updated WHERE id=:id'),
                  {'state': store.dump(state), 'updated': store.now(), 'id': task_id})
    return {'ok': True, 'memory_id': mid}


def preferences(brand_id):
    return studio.memory_context(brand_id, kb.get_workspace()) if brand_id else []
