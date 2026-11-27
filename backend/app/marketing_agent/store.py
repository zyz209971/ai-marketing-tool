"""SQLAlchemy business records, optimistic revisions and durable request receipts."""
import json
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import text, inspect
from fastapi import HTTPException
from .. import knowledge as kb
from .contracts import Brief
from .graph import dependency
from .business import fingerprint, call_tool


def now():
    return datetime.now(timezone.utc).isoformat()


def dump(value):
    return json.dumps(value, ensure_ascii=False)


def init_db():
    with kb.engine.begin() as c:
        c.execute(text('CREATE TABLE IF NOT EXISTS agent_tasks (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, state TEXT NOT NULL, active_run TEXT, updated TEXT NOT NULL)'))
        c.execute(text('CREATE TABLE IF NOT EXISTS agent_runs (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, request_id TEXT NOT NULL, request_hash TEXT NOT NULL, status TEXT NOT NULL, error TEXT NOT NULL, created TEXT NOT NULL, UNIQUE(task_id,request_id))'))

    columns = {x['name'] for x in inspect(kb.engine).get_columns('agent_tasks')}
    if 'workspace_id' not in columns:
        with kb.engine.begin() as c:
            c.execute(text("ALTER TABLE agent_tasks ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'local-preview-workspace'"))


def create_task(brand_id=None,demo=False,sku_id=None):
    if brand_id:
        from .data import snapshot
        catalog = snapshot(brand_id)['products']
    else:
        catalog = {}
    if sku_id and sku_id not in catalog:
        raise HTTPException(422, '请选择当前品牌下仍在使用的商品。')
    ident = uuid4().hex
    state = {'task_id': ident, 'demo_mode':bool(demo and not brand_id), 'brief': Brief(brand_id=brand_id, sku_id=sku_id).model_dump(mode='json'), 'stage': 'collecting',
             'messages': [{'role': 'assistant', 'content': '你好，我是你的营销助手。\n\n聊聊这次的想法吧：想推广新品、给销量一般的饮品做个活动，还是先看看最近卖得怎么样？', 'at': now()}],
             'strategy': None, 'strategies': [], 'approvals': [], 'artifacts': [], 'tool_results': {}, 'trace': [],
             'pending_fields': [], 'options': [], 'suggestions': ['帮我制定下周的促销方案', '看看最近哪些饮品卖得不好', '我想做第二杯半价']}
    if not brand_id and not demo:
        from .paths import onboarding
        guide=onboarding(state)
        state['messages'][0]['content']=guide['reply']
        state['suggestions']=guide['suggestions']
    with kb.engine.begin() as c:
        c.execute(text('INSERT INTO agent_tasks(id,revision,state,active_run,updated,workspace_id) VALUES(:id,0,:state,NULL,:now,:workspace)'),
                  {'id': ident, 'state': dump(state), 'now': now(), 'workspace':kb.get_workspace()})
    return get_task(ident)


def row(c, ident):
    result = c.execute(text('SELECT * FROM agent_tasks WHERE id=:id AND workspace_id=:workspace'), {'id': ident,'workspace':kb.get_workspace()}).mappings().first()
    if not result:
        raise HTTPException(404, '营销任务不存在。')
    return dict(result)


def present(value):
    state=json.loads(value['state'])
    state['brief']=Brief.model_validate(state['brief']).model_dump(mode='json')
    state.setdefault('demo_mode',not bool(state['brief'].get('brand_id')))
    return {'id': value['id'], 'revision': value['revision'], 'active_run': value['active_run'],
            'updated': value['updated'], 'state': state}


def get_task(ident):
    with kb.engine.connect() as c:
        return present(row(c, ident))


def list_tasks(brand_id=None, q='', limit=50, offset=0):
    with kb.engine.connect() as c:
        rows = c.execute(text('SELECT * FROM agent_tasks WHERE workspace_id=:workspace ORDER BY updated DESC'), {'workspace':kb.get_workspace()}).mappings().all()
        names={b['id']:b['name'] for b in kb.accessible_brands(c,kb.get_workspace())}
    result=[]
    for row_ in rows:
        s=json.loads(row_['state']);brief=s['brief'];bid=brief.get('brand_id')
        title=next((m['content'][:80] for m in s['messages'] if m['role']=='user'),'新的营销对话')
        if brand_id is not None and bid!=brand_id:continue
        if q and q.casefold() not in (title+' '+names.get(bid,'')).casefold():continue
        result.append({'id':row_['id'],'updated':row_['updated'],'stage':s['stage'],'title':title,'brand_id':bid,
            'brand_name':names.get(bid,'模拟门店' if s.get('demo_mode',True) else '尚未建立品牌'),
            'task_kind':brief.get('task_kind','campaign'),'active_run':row_['active_run']})
    return result[offset:offset+limit]


def get_run(ident):
    with kb.engine.connect() as c:
        result = c.execute(text('SELECT r.* FROM agent_runs r JOIN agent_tasks t ON t.id=r.task_id WHERE r.id=:id AND t.workspace_id=:workspace'), {'id': ident,'workspace':kb.get_workspace()}).mappings().first()
    if not result:
        raise HTTPException(404, '执行记录不存在。')
    return {k: result[k] for k in ('id', 'task_id', 'status', 'error', 'created')}


def cancel_run(ident):
    """Mark a queued/running run as cancelled and release the task lock.

    The worker thread checks ``task.active_run != run_id`` before writing any
    result, so flipping the lock here makes the in-flight execution a no-op
    without killing the thread or risking a partial write.
    """
    with kb.engine.begin() as c:
        kb.lock_workspace(c)
        run = c.execute(text('SELECT id,task_id,status FROM agent_runs WHERE id=:id'), {'id': ident}).mappings().first()
        if not run:
            raise HTTPException(404, '执行记录不存在。')
        task = c.execute(text('SELECT id FROM agent_tasks WHERE id=:id'), {'id': run['task_id']}).mappings().first()
        if not task:
            raise HTTPException(404, '对话不存在。')
        if run['status'] not in ('queued', 'running'):
            return {'run_id': ident, 'status': run['status'], 'cancelled': False}
        # Only clear the lock if this run still owns it, so we never clobber a newer run.
        c.execute(text("UPDATE agent_tasks SET active_run=NULL WHERE id=:id AND active_run=:run"),
                  {'id': run['task_id'], 'run': ident})
        c.execute(text("UPDATE agent_runs SET status='cancelled', error='' WHERE id=:id"), {'id': ident})
    return {'run_id': ident, 'status': 'cancelled', 'cancelled': True}


def submission_receipt(ident, request_id):
    with kb.engine.connect() as c:
        row(c, ident)  # Authorize the conversation before looking up a receipt.
        result = c.execute(text('SELECT id,status FROM agent_runs WHERE task_id=:task AND request_id=:key'),
                           {'task': ident, 'key': request_id}).mappings().first()
    return {'found': True, 'run_id': result['id'], 'status': result['status']} if result else {'found': False}


def enqueue(ident, request, operation):
    request_payload = request.model_dump(mode='json')
    request_hash = fingerprint({'operation': operation, 'payload': request_payload})
    with kb.engine.begin() as c:
        kb.lock_workspace(c)
        row(c, ident)  # Authorize before consulting an idempotency receipt.
        prior = c.execute(text('SELECT id,request_hash FROM agent_runs WHERE task_id=:task AND request_id=:key'),
                          {'task': ident, 'key': request.request_id}).mappings().first()
        if prior:
            if prior['request_hash'] != request_hash:
                raise HTTPException(409, '同一请求标识不能用于不同内容。')
            return prior['id'], None
        task = row(c, ident)
        if task['active_run'] or task['revision'] != request.expected_revision:
            raise HTTPException(409, '任务正在执行或版本已更新，请刷新后继续。')
        if c.execute(text("SELECT COUNT(*) FROM agent_runs WHERE status IN ('queued','running')")).scalar_one() >= 8:
            raise HTTPException(429, '待处理任务较多，请稍后再试。')
        state = json.loads(task['state'])
        state['brief']=Brief.model_validate(state['brief']).model_dump(mode='json')
        if len(state['messages']) >= 200:
            raise HTTPException(422, '当前会话已达到本地演示上限，请新建活动。')
        state.update(operation=operation, text='', input_patch={}, reply='', trace=[], steps=0, decision={}, changed=False, wait_prepared=False)
        if operation == 'answer':
            from .questions import normalize_answer
            request = normalize_answer(request, state.get('input_request'))
        if operation == 'confirm':
            if state.get('active_attachment_id'):
                raise HTTPException(409, '请先补齐并确认待处理资料，再确认活动策略。')
            strategy = state.get('strategy')
            if (not strategy or strategy['id'] != request.strategy_id or strategy['version'] != request.strategy_version
                    or strategy['dependency'] != dependency(state['brief']) or strategy['status'] not in ('proposed', 'approved')):
                raise HTTPException(409, '确认的策略已失效，请查看最新策略。')
            evaluation = call_tool('evaluate_promotion', state['brief'])
            if evaluation['status'] != 'ok' or evaluation['result']['feasible'] is not True:
                raise HTTPException(409, '当前方案未通过生成前检查。')
            # Do not bill/generate again for a new approval request after success.
            if any(a['strategy_id'] == strategy['id'] and not a['stale'] for a in state['artifacts']):
                raise HTTPException(409, '该策略已有文案，请使用聊天提出修改。')
            strategy['status'] = 'approved'
            state['approvals'].append({'strategy_id': strategy['id'], 'version': strategy['version'],
                                       'at': now(), 'actor': kb.get_workspace(), 'request_id': request.request_id})
            state['messages'].append({'role': 'user', 'content': f"确认策略 v{strategy['version']} 并生成文案", 'at': now()})
        else:
            if not request.text.strip() and not request.patch:
                raise HTTPException(422, '请填写消息或补充资料。')
            # Validate explicit patches synchronously so malformed UI input is actionable.
            Brief.model_validate({**state['brief'], **request.patch})
            state.update(text=request.text, input_patch=request.patch, web_search=bool(getattr(request, 'web_search', True)))
            state['messages'].append({'role': 'user', 'content': request.text or '已通过表单补充资料',
                                      'patch': request.patch, 'at': now()})
        run_id = uuid4().hex
        state['stage'] = 'generating' if operation == 'confirm' else 'analyzing'
        c.execute(text('INSERT INTO agent_runs(id,task_id,request_id,request_hash,status,error,created) VALUES(:id,:task,:key,:hash,\'queued\',\'\',:now)'),
                  {'id': run_id, 'task': ident, 'key': request.request_id, 'hash': request_hash, 'now': now()})
        c.execute(text('UPDATE agent_tasks SET state=:state,revision=revision+1,active_run=:run,updated=:now WHERE id=:id'),
                  {'id': ident, 'state': dump(state), 'run': run_id, 'now': now()})
    return run_id, state


def running(run_id):
    with kb.engine.begin() as c:
        c.execute(text("UPDATE agent_runs SET status='running' WHERE id=:id AND status='queued'"), {'id': run_id})


def finish(run_id, task_id, state=None, error=None):
    with kb.engine.begin() as c:
        kb.lock_workspace(c)
        task = row(c, task_id)
        if task['active_run'] != run_id:
            return
        saved = state if state is not None else json.loads(task['state'])
        if error:
            saved['stage'] = 'failed'
        else:
            if not saved.get('wait_prepared'):
                from .runtime import park
                saved = park(saved)
        message = {'role': 'assistant', 'content': error or saved['reply'], 'at': now()}
        if not error:
            previous = json.loads(task['state'])
            if saved.get('strategy') and saved['stage'] == 'awaiting_confirmation':
                message['strategy_ref'] = saved['strategy']['id']
            if len(saved['artifacts']) > len(previous['artifacts']):
                message['artifact_ref'] = saved['artifacts'][-1]['id']
            if saved.get('options'):
                message['options'] = saved['options']
            sales = saved.get('tool_results', {}).get('get_sales_summary')
            if sales and (not previous.get('tool_results', {}).get('get_sales_summary') or any(t.get('tool')=='get_sales_summary' for t in saved.get('trace', []))):
                message['sales'] = sales
        saved['messages'].append(message)
        from .archive import save
        save(c,saved)
        c.execute(text('UPDATE agent_tasks SET state=:state,revision=revision+1,active_run=NULL,updated=:now WHERE id=:id'),
                  {'state': dump(saved), 'now': now(), 'id': task_id})
        c.execute(text('UPDATE agent_runs SET status=:status,error=:error WHERE id=:id'),
                  {'status': 'failed' if error else 'succeeded', 'error': error or '', 'id': run_id})


def recover_interrupted():
    """One local worker process only. Never silently replay a potentially billed call."""
    with kb.engine.connect() as c:
        runs = c.execute(text("SELECT r.id,r.task_id,t.workspace_id FROM agent_runs r JOIN agent_tasks t ON t.id=r.task_id WHERE r.status IN ('queued','running')")).mappings().all()
    for run in runs:
        from ..auth import workspace_scope
        with workspace_scope(run['workspace_id']):
            finish(run['id'], run['task_id'], error='服务已重启，上次执行结果未确认。请检查当前状态后重新提交；系统不会自动重放模型调用。')
