"""One graph execution owner. Durable interrupts; external writes stay in business APIs."""
import os
from contextlib import contextmanager
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from ..config import DATA_DIR


@contextmanager
def checkpointer():
    url = os.getenv('AGENT_CHECKPOINT_URL','')
    if url:
        from langgraph.checkpoint.postgres import PostgresSaver
        with PostgresSaver.from_conn_string(url) as saver:
            saver.setup()
            yield saver
    else:
        with SqliteSaver.from_conn_string(str(DATA_DIR/'agent-checkpoints.db')) as saver:
            yield saver


def invoke(state):
    # 店长 Agent + 专家团队编排（薄思考）。默认走 team.py，避免旧的逐字段追问
    # 与多轮模型调用。若显式设置 AGENT_LEGACY_GRAPH 才回退到旧 LangGraph 编排。
    if not os.getenv('AGENT_LEGACY_GRAPH', '').lower() in ('1', 'true'):
        from .team import invoke as team_invoke
        return team_invoke(state)
    from .graph import build_graph
    config = {'configurable':{'thread_id':state['task_id']},'recursion_limit':30}
    with checkpointer() as saver:
        graph = build_graph(saver)
        prior = graph.get_state(config)
        interrupted = any(t.interrupts for t in prior.tasks)
        result = graph.invoke(Command(resume=state) if interrupted else state, config)
        # __interrupt__ is an SDK object, not business state or JSON.
        return {k:v for k,v in result.items() if not k.startswith('__')}


def park(state):
    """Synchronize upload/edit/confirmation APIs without replaying tools or model calls."""
    from .graph import build_graph
    config = {'configurable':{'thread_id':state['task_id']},'recursion_limit':30}
    with checkpointer() as saver:
        graph = build_graph(saver)
        graph.update_state(config,state,as_node='intake')
        result = graph.invoke(None,config)
        return {k:v for k,v in result.items() if not k.startswith('__')}
