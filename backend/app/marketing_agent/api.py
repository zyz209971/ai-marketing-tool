import logging
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import ValidationError
from openai import APIError
from langgraph.checkpoint.sqlite import SqliteSaver
from ..config import DATA_DIR
from ..v2 import require_access
from . import store, model, business
from .contracts import MessageInput, ConfirmInput, Brief, SalesRequest, ConstraintsRequest, EvaluationRequest, ToolResult, RESULT_TYPES, CreateConversation
from .graph import build_graph
from .contracts import AnswerInput, InputRequest, RememberStyleInput

logger = logging.getLogger(__name__)
def require_local(request: Request):
    from ..auth import enabled
    if enabled():
        return
    local = {'127.0.0.1', 'localhost', '::1'}
    if (not request.client or request.client.host not in local or request.url.hostname not in local
            or any(h in request.headers for h in ('forwarded', 'x-forwarded-for', 'x-forwarded-host', 'x-forwarded-proto'))):
        raise HTTPException(403, '营销 Agent 当前为本机开发版，尚未开放公网访问。')


router = APIRouter(prefix='/api/agent', tags=['marketing agent'], dependencies=[Depends(require_local), Depends(require_access)])
pool = None


def startup():
    global pool
    store.init_db()
    from . import data
    data.init_db()
    store.recover_interrupted()
    pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='marketing-agent')


def shutdown():
    global pool
    if pool:
        pool.shutdown(wait=True)
        pool = None


def execute(run_id, state):
    store.running(run_id)
    try:
        from .runtime import invoke
        result = invoke(state)
        store.finish(run_id, state['task_id'], state=dict(result))
    except APIError as exc:
        from .provider_errors import public_message
        logger.warning('Agent provider failed run=%s type=%s status=%s', run_id, type(exc).__name__, getattr(exc,'status_code',None))
        store.finish(run_id, state['task_id'], error=public_message(exc))
    except (ValidationError, ValueError) as exc:
        logger.warning('Agent validation failed run=%s type=%s', run_id, type(exc).__name__)
        store.finish(run_id, state['task_id'], error='输入或模型结果未通过校验，请核对日期、金额、优惠规则及模型 Tool Calling 支持后重试。')
    except Exception:
        logger.exception('Agent execution failed run=%s', run_id)
        store.finish(run_id, state['task_id'], error='本轮执行失败，已有资料已保留。请检查后端日志后重新提交。')


def submit(task_id, request, operation):
    if pool is None:
        raise HTTPException(503, 'Agent 工作线程未启动。')
    try:
        run_id, state = store.enqueue(task_id, request, operation)
    except ValidationError as exc:
        raise HTTPException(422, '资料格式不正确：'+ '; '.join(e['msg'] for e in exc.errors())) from None
    if state is not None:
        pool.submit(__import__("contextvars").copy_context().run, execute, run_id, state)
    return {'run_id': run_id}


@router.get('/config')
def config():
    from .. import knowledge as kb
    return {'mode': model.mode(), 'data_kind': 'task_scoped', 'store_id': None,
            'products': business.PRODUCTS, 'data_version': business.DATA_VERSION,
            'brands': kb.brands(kb.get_workspace())['brands'],
            'note': '单门店本地开发版。新会话引导品牌建档；仅显式选择演示门店使用模拟数据。离线模式不调用模型。'}


@router.get('/contracts')
def contracts():
    return {'Brief': Brief.model_json_schema(), 'ToolResult': ToolResult.model_json_schema(),
            'InputRequest': InputRequest.model_json_schema(), 'AnswerInput': AnswerInput.model_json_schema(),
            'requests': {name: cls.model_json_schema() for name, cls in
                         [('get_sales_summary', SalesRequest), ('get_business_constraints', ConstraintsRequest), ('evaluate_promotion', EvaluationRequest)]},
            'results': {name: cls.model_json_schema() for name, cls in RESULT_TYPES.items()}}


@router.get('/demo-orders')
def demo_orders():
    return {'data_kind': 'synthetic', 'data_version': business.DATA_VERSION, 'orders': list(business.records())}


@router.post('/conversations', status_code=201)
def create(request: CreateConversation = CreateConversation()):
    return store.create_task(request.brand_id,request.demo)


@router.get('/conversations')
def listing(brand_id: str | None = None, q: str = Query('',max_length=100), limit: int = Query(50,ge=1,le=100), offset: int = Query(0,ge=0)):
    rows=store.list_tasks(brand_id,q,limit+1,offset)
    return {'conversations': rows[:limit], 'has_more':len(rows)>limit,'offset':offset}


@router.get('/conversations/{task_id}')
def detail(task_id: str):
    value = store.get_task(task_id)
    value['catalog'] = business.catalog(value['state']['brief']) if value['state']['brief'].get('brand_id') or value['state'].get('demo_mode',True) else {}
    if value['state']['brief'].get('brand_id'):
        from .data import snapshot
        snap=snapshot(value['state']['brief']['brand_id'])
        value['brand_name'] = snap['brand']['name']
        for artifact in value['state']['artifacts']:
            artifact['stale']=artifact['stale'] or artifact.get('knowledge_version')!=snap['version']
    from .attachments import listing
    value['attachments'] = listing(task_id)
    return value


@router.post('/conversations/{task_id}/messages', status_code=202)
def message(task_id: str, request: MessageInput):
    return submit(task_id, request, 'message')


@router.post('/conversations/{task_id}/answers', status_code=202)
def answer(task_id: str, request: AnswerInput):
    return submit(task_id, request, 'answer')


@router.post('/conversations/{task_id}/remember-style')
def remember_style(task_id: str, request: RememberStyleInput):
    from .memory import save_style
    return save_style(task_id, request.expected_revision)


@router.post('/conversations/{task_id}/confirm', status_code=202)
def confirm(task_id: str, request: ConfirmInput):
    return submit(task_id, request, 'confirm')


@router.get('/runs/{run_id}')
def run(run_id: str):
    return store.get_run(run_id)


from .attachments import register
register(router)
