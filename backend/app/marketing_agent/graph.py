"""Bounded LangGraph decision/tool loop. Each user turn ends with a durable checkpoint.

User waits use interrupt()/Command(resume=...) with persisted business projections.
Explicit approval is checked transactionally by the API, never inferred from chat text.
"""
import copy
from typing import TypedDict
from uuid import uuid4
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from . import model, business, content
from .contracts import Brief


class State(TypedDict, total=False):
    task_id: str
    text: str
    web_search: bool
    input_patch: dict
    operation: str
    brief: dict
    messages: list
    stage: str
    strategy: dict | None
    strategies: list
    approvals: list
    artifacts: list
    tool_results: dict
    trace: list
    decision: dict
    reply: str
    steps: int
    changed: bool
    pending_fields: list
    suggestions: list
    options: list
    brand_context: dict
    revision_scope: str
    source_version: str
    active_attachment_id: str | None
    intake_resume: dict | None
    brand_setup_pending: bool
    turn_intent: str
    clarification_fields: list
    input_request: dict | None
    suspended_attachment_id: str | None
    checkpoint_resume: bool
    next_node: str
    wait_prepared: bool
    demo_mode: bool
    unit_result: dict | None


LABELS = {'sku_id': '商品（T001 茉莉鲜奶茶 / T002 乌龙鲜奶茶 / T003 红茶鲜奶茶）',
          'platform': '推广平台', 'start_date': '活动开始日期', 'end_date': '活动结束日期（不包含）',
          'budget_minor': '预算上限', 'spend_minor': '预计实际营销支出',
          'scenario_qty': '活动销量假设（杯数），或明确选择“只看单位收益”', 'offer': '具体优惠规则'}


def missing_fields(brief):
    from .paths import missing
    return missing(brief)


def clarification(state, missing):
    first = missing[0]
    questions = {
        'promotion_pairs': ('预计有多少组同单两杯会参加优惠？剩余杯数按原价；不知道时可先只看单位收益。', []),
        'sku_id': ('这次想主推哪款饮品？演示门店有茉莉鲜奶茶、乌龙鲜奶茶和红茶鲜奶茶。', ['主推茉莉鲜奶茶', '主推乌龙鲜奶茶', '主推红茶鲜奶茶']),
        'platform': ('准备在哪个平台推广？', ['小红书', '抖音', '微信公众号']),
        'start_date': ('活动准备什么时候开始、持续几天？你可以直接说“下周”或“下周末”。', ['下周', '下周末']),
        'end_date': ('活动准备持续到哪一天？告诉我最后一天的日期就可以。', []),
        'offer': ('你想采用什么优惠？我会先帮你检查成本是否允许。', ['第二杯半价', '第二杯七折', '不打折']),
        'budget_minor': ('这次营销最多愿意投入多少钱？这里问的是预算上限。', []),
        'spend_minor': ('预算已经记下了。你预计实际花多少钱做推广？没有额外投放费用也可以填 0。', ['就按预算花', '预计花费100元', '预计花费0元']),
        'scenario_qty': ('你想按活动期间卖出多少杯来试算？这只是情景假设；暂时没把握，也可以先只看每杯优惠是否划算。', ['暂时只看单位收益']),
    }
    question, suggestions = questions[first]
    if first == 'sku_id':
        products = business.catalog(state['brief'])
        question = '这次想主推哪款商品？' if products else '当前品牌还没有商品。请通过附件上传产品资料并确认，或到品牌管理中添加。'
        suggestions = ['主推'+p['name'] for p in list(products.values())[:6]]
    prefix = ''
    if first == 'sku_id' and 'get_sales_summary' in state.get('tool_results', {}):
        metrics = state['tool_results']['get_sales_summary']['result']['metrics']
        falling = [m for m in metrics if m['change_ratio'] is not None and m['change_ratio'] < 0]
        if falling:
            item = falling[0]
            prefix = f"所选数据中，{item['name']}本期销量较上期下降了 {abs(item['change_ratio'])*100:.0f}%。可以优先考虑它，但这只是变化，暂时不能据此判断原因。\n\n"
    # 优惠缺失时，用本地规则生成候选方案（不调模型），让用户点选而不是手动输入折扣。
    options = []
    if first == 'offer':
        # 候选优惠机制是固定的三类，直接本地生成，省去一次模型调用；成本校验是纯本地计算。
        candidates = [
            {'offer': {'type': 'second_cup_discount', 'pay_bps': 5000}, 'rationale': '鼓励同单购买两杯，让利最明显。'},
            {'offer': {'type': 'second_cup_discount', 'pay_bps': 7000}, 'rationale': '让利更小，作为半价的保守备选。'},
            {'offer': {'type': 'none', 'pay_bps': 10000}, 'rationale': '不降价，侧重商品卖点；作为原价对照。'},
        ]
        for cand in candidates:
            offer = cand['offer']
            label = '原价推广' if offer['type'] == 'none' else f"第二杯{offer['pay_bps']/1000:g}折"
            try:
                evaluation = business.call_tool('evaluate_promotion', {**state['brief'], 'offer': offer})
            except Exception:
                evaluation = None
            if evaluation and evaluation['status'] == 'ok' and not evaluation['missing_fields']:
                options.append({'name': label, 'offer': offer, 'rationale': cand['rationale'], 'evaluation': evaluation})
    return {'stage': 'collecting', 'reply': prefix+question, 'pending_fields': [first], 'clarification_fields': missing,
            'suggestions': suggestions if not options else [], 'options': options}


def dependency(brief):
    return business.fingerprint({'brief': {k: v for k, v in brief.items() if k != 'style'},
                                 'data_version': business.source_version(brief), 'method_version': business.METHOD_VERSION})


def understand(state):
    s = copy.deepcopy(state)
    if s.get('brand_setup_pending'):
        return {**s,'decision':{'action':'answer','intent':'question'},'turn_intent':'question','tool_results':{}}
    if not s['brief'].get('brand_id') and not s.get('demo_mode',True):
        from .paths import onboarding
        return {**s,**onboarding(s),'decision':{'action':'answer','intent':'question'},'turn_intent':'question'}
    from .data import context
    current_version = business.source_version(s['brief'])
    source_changed = s.get('source_version') != current_version
    if source_changed:
        s['tool_results'] = {}
        s['unit_result'] = None
    s['brand_context'] = context(s['brief'])
    decision = model.decide(s, initial=True)
    patch = {**decision.patch, **s.get('input_patch', {})}
    # Content must never bypass approval by carrying promotional terms.
    requested_kind=patch.get('task_kind',s['brief'].get('task_kind','campaign'))
    if requested_kind=='unit_economics':patch['roi_mode']='unit_only'
    if requested_kind=='content':
        if patch.get('offer') and patch['offer'].get('type')!='none':
            patch['task_kind']='campaign'
        else:
            patch.update(offer=None,promotion_pairs=None)
    if requested_kind=='campaign' and s['brief'].get('task_kind')=='unit_economics' and 'roi_mode' not in patch:
        patch['roi_mode']='scenario'
    if requested_kind=='campaign':patch['assess_minimum']=True
    old = s['brief']
    if 'brand_id' in patch and patch['brand_id'] != old.get('brand_id'):
        raise ValueError('切换品牌请新建对话，不能修改已有任务的品牌。')
    if 'sku_id' in patch and patch['sku_id'] != old.get('sku_id'):
        patch = {'variable_cost_override_minor':None, 'min_contribution_override_minor':None, **patch}
    # Unknown keys rejected; nested offers validated after patching as a whole.
    updated = Brief.model_validate({**old, **patch}).model_dump(mode='json')
    if updated.get('sku_id') and updated['sku_id'] not in business.catalog(updated):
        raise ValueError('商品不属于当前品牌或已归档。')
    changed = dependency(updated) != dependency(old) or bool(source_changed and s.get('artifacts')) or bool(s.get('strategy') and s['strategy']['dependency'] != dependency(updated))
    if changed:
        s['unit_result'] = None
        if s.get('strategy'):
            prior = {**s['strategy'], 'status': 'superseded'}
            s['strategies'] = [*s.get('strategies', []), prior]
        s['strategy'] = None
        s['tool_results'] = {}
        s['artifacts'] = [{**a, 'stale': True} for a in s.get('artifacts', [])]
    # A style-only form patch can revise an approved result without a model classification.
    if not changed and updated['style'] != old['style'] and s.get('artifacts'):
        decision.intent, decision.action = 'revise', 'revise'
    elif changed and decision.action == 'revise':
        decision.intent, decision.action = 'plan', 'propose'
    scope = decision.revision_scope
    s.update(brief=updated, changed=changed, decision=decision.model_dump(), steps=0, reply='', trace=[], stage='analyzing', suggestions=[], options=[], clarification_fields=[],
             brand_context=context(updated), revision_scope=scope, source_version=business.source_version(updated), turn_intent=decision.intent)
    return s


def choose(state):
    decision = model.decide(state).model_dump()
    return {'decision': decision, 'steps': state['steps']+1}


def route(state):
    d = state['decision']
    if state.get('brand_setup_pending'):return 'respond'
    if not state['brief'].get('brand_id') and not state.get('demo_mode',True):return 'respond'
    if d['action'] == 'knowledge':
        return 'knowledge'
    if d['action'] == 'revise':
        return 'revise'
    if state['brief'].get('task_kind') in ('brand_setup','content','unit_economics') and d.get('intent')!='question':
        return 'finalize'
    if d['action'] in ('ask', 'answer'):
        return 'respond'
    if d['action'] == 'tool':
        if state['steps'] >= 5:
            return 'finalize'
        name = d.get('tool')
        if name not in business.TOOL_NAMES:
            raise ValueError('模型请求了不允许的工具。')
        if name in state['tool_results']:
            return 'finalize'
        if name in ('get_business_constraints', 'evaluate_promotion') and not state['brief'].get('sku_id'):
            return 'finalize'
        return 'tool'
    return 'finalize'


def tool(state):
    name = state['decision']['tool']
    query = state['decision'].get('tool_query', '') if name == 'web_search' else ''
    result = business.call_tool(name, state['brief'], query)
    return {'tool_results': {**state['tool_results'], name: result},
            'trace': [*state['trace'], {'tool': name, 'status': result['status'], 'snapshot_id': result['snapshot_id']} ]}


def reply(state):
    if state.get('brand_setup_pending'):
        return {'stage':'collecting','pending_fields':[],'clarification_fields':[],
                'reply':'这个新品牌的资料仍是待确认草稿。请先继续补充并确认资料，再使用它写文案或分析优惠；已上传内容仍然保留。'}
    if not state['brief'].get('brand_id') and not state.get('demo_mode',True):
        from .paths import onboarding
        return onboarding(state)
    missing = missing_fields(state['brief'])
    if missing and (state['decision']['action'] == 'ask' or state.get('turn_intent') == 'plan'):
        return clarification(state, missing)
    if not missing and (state['decision']['action'] == 'ask' or state.get('turn_intent') == 'plan'):
        return finalize(state)
    return {'reply': state['decision']['reply'] or (clarification(state, missing)['reply'] if missing else '可以继续告诉我你的想法。'),
            'pending_fields': [], 'suggestions': [],
            'stage': 'awaiting_confirmation' if state.get('strategy') and state['strategy']['status'] == 'proposed' else 'collecting'}


def finalize(state):
    b = state['brief']
    if state.get('source_version') and state['source_version'] != business.source_version(b):
        raise ValueError('分析期间资料已变化，请重新发送需求。')
    missing = missing_fields(b)
    if missing:
        return clarification(state, missing)
    kind=b.get('task_kind','campaign')
    if kind=='brand_setup':
        return {'stage':'collecting','pending_fields':[],'reply':'可以上传品牌介绍、菜单或商品说明，也可以在对话里补充品牌事实。我会先整理为待确认资料，确认后入库。'}
    if kind=='content':
        artifact=content.generate(state,ordinary=True)
        return {'artifacts':[*state['artifacts'],artifact],'stage':'completed','pending_fields':[],
                'reply':'已根据确认资料生成普通文案，不包含优惠承诺。作品已归档，可以继续修改标题或语气。','suggestions':['标题活泼一点','语气简短一点']}
    if b.get('brand_id') and business.catalog(b)[b['sku_id']]['price'] is None:
        from .attachments import draft_note
        from .intake import response
        from .. import knowledge as kb
        from sqlalchemy import text
        import json
        p=business.catalog(b)[b['sku_id']]
        item=draft_note(state['task_id'],b['brand_id'],f"产品名称：{p['name']}\n规格：{p.get('spec','')}\n卖点：{'；'.join(p['selling'])}")
        item['payload']['required_fields']=['products.0.price']
        with kb.engine.begin() as c:
            c.execute(text('UPDATE agent_attachments SET payload=:payload WHERE id=:id'),{'id':item['id'],'payload':json.dumps(item['payload'],ensure_ascii=False)})
        return {**response(item),'intake_resume':{'text':state['text'],'patch':state.get('input_patch',{})}}
    if kind=='unit_economics':
        result=business.call_tool('evaluate_promotion',b)
        if result['missing_fields']:
            return {'stage':'collecting','pending_fields':[x['path'] for x in result['missing_fields']],
                    'clarification_fields':[x['path'] for x in result['missing_fields']], 'reply':result['missing_fields'][0]['reason']}
        return {'stage':'completed','unit_result':result,'pending_fields':[], 'tool_results':{**state['tool_results'],'evaluate_promotion':result},
                'reply':'已完成单位收益测算。结果不代表净利润，也不预测活动销量。'+('尚未指定最低贡献标准，因此不判断是否达标。' if result['result']['feasible'] is None else '请查看成本与优惠边界。')}
    from .intake import require_business
    collection = require_business(state)
    if collection:
        return collection
    if not b.get('offer'):
        probe = business.call_tool('evaluate_promotion', {**b, 'offer': {'type':'none','pay_bps':10000}})
        if probe['missing_fields']:
            first = probe['missing_fields'][0]
            return {'reply':first['reason'], 'stage':'collecting', 'pending_fields':[first['path']], 'options':[], 'suggestions':[]}
        options = []
        # 候选优惠机制固定三类，本地生成（不调模型）；成本校验是纯本地计算。
        for offer, rationale in [
                ({'type': 'second_cup_discount', 'pay_bps': 5000}, '鼓励同单购买两杯，让利最明显。'),
                ({'type': 'second_cup_discount', 'pay_bps': 7000}, '让利更小，作为半价的保守备选。'),
                ({'type': 'none', 'pay_bps': 10000}, '不降价，侧重商品卖点；作为原价对照。')]:
            label = '原价推广' if offer['type']=='none' else f"第二杯{offer['pay_bps']/1000:g}折"
            evaluation = business.call_tool('evaluate_promotion', {**b, 'offer': offer})
            if evaluation['missing_fields']:
                first = evaluation['missing_fields'][0]
                return {'reply': first['reason'], 'stage': 'collecting', 'pending_fields': [first['path']], 'options': [], 'suggestions': []}
            options.append({'name': label, 'offer': offer, 'rationale': rationale, 'evaluation': evaluation})
        if state['source_version'] != business.source_version(b):
            raise ValueError('比较期间资料已变化，请重新发送需求。')
        return {'stage': 'collecting', 'options': options, 'pending_fields': ['offer'], 'suggestions': [],
                'reply': '结合你的目标，我比较了三个活动选择。优惠越大不一定越划算；以下沿用同一销量假设，不代表最优预测。请选一个可行方案，我会整理成待确认策略。'}
    results = copy.deepcopy(state['tool_results'])
    trace = list(state['trace'])
    # Mandatory gate is deterministic even if the model wants to skip the calculator.
    for name in ('get_business_constraints', 'evaluate_promotion'):
        if name not in results:
            results[name] = business.call_tool(name, b)
            trace.append({'tool': name, 'status': results[name]['status'], 'snapshot_id': results[name]['snapshot_id'], 'reason': 'mandatory_gate'})
    evaluation = results['evaluate_promotion']
    if evaluation['status'] != 'ok' or evaluation['result']['feasible'] is not True:
        reasons = evaluation['result']['violations'] or [x['reason'] for x in evaluation['missing_fields']]
        return {'tool_results': results, 'trace': trace, 'stage': 'blocked',
                'reply': '我算了一下，这个方案还不能直接采用：\n'+'\n'.join(reasons)+'\n我们可以调整优惠，或者补充更准确的成本。',
                'suggestions': [] if evaluation['missing_fields'] else ['第二杯七折', '不打折'],
                'pending_fields': [evaluation['missing_fields'][0]['path']] if evaluation['missing_fields'] else []}
    existing = state.get('strategy')
    if existing and existing['dependency'] == dependency(b):
        return {'tool_results': results, 'trace': trace, 'stage': 'completed' if existing['status'] == 'approved' else 'awaiting_confirmation',
                'reply': '当前策略条件没有变化。请使用策略卡确认；已确认的方案可以继续修改文案语气。'}
    version = max([x['version'] for x in state.get('strategies', [])]+[0])+1
    explanation = model.explain_strategy({**state, 'tool_results': results}, evaluation)
    if state.get('source_version') and state['source_version'] != business.source_version(b):
        raise ValueError('策略解释期间资料已变化，请重新计算后确认。')
    strategy = {'id': uuid4().hex, 'version': version, 'status': 'proposed', 'brief': b,
                'dependency': dependency(b), 'evaluation': evaluation, 'snapshot_ids': [r['snapshot_id'] for r in results.values()],
                'rationale': explanation.rationale, 'risks': explanation.risks,
                'data_kind': evaluation['data_kind'], 'product_name': business.catalog(b)[b['sku_id']]['name'],
                'brand_context': state.get('brand_context', {})}
    negative = evaluation['result'].get('incremental_contribution_minor')
    note = '注意：当前情景的增量贡献为负，活动可能不如不促销。' if negative is not None and negative < 0 else ''
    return {'strategy': strategy, 'tool_results': results, 'trace': trace, 'stage': 'awaiting_confirmation',
            'reply': f'我把方案整理好了。{note}下面是活动安排和测算结果，你可以确认，也可以直接告诉我想改哪里。',
            'suggestions': [], 'pending_fields': []}


def generate(state):
    current = state.get('strategy')
    if not current or current['status'] != 'approved' or current['dependency'] != dependency(state['brief']):
        raise ValueError('策略未确认或已失效，请重新确认。')
    from .offline import OfflineEditUnsupported, UnchangedEdit
    try:
        artifact = content.generate(state, revision=state.get('operation') != 'confirm')
    except (OfflineEditUnsupported, UnchangedEdit) as exc:
        return {'stage':'completed','pending_fields':[],'reply':str(exc)}
    if current['dependency'] != dependency(state['brief']):
        raise ValueError('生成期间资料已变化，请重新确认策略。')
    return {'artifacts': [*state['artifacts'], artifact], 'stage': 'completed',
            'reply': '文案写好了。看看是否符合你想要的感觉，也可以继续告诉我怎么改。',
            'suggestions': ['标题活泼一点', '语气简短一点', '第二杯改成七折'], 'pending_fields': []}


def revise(state):
    if state['brief'].get('task_kind')=='content' and state.get('artifacts'):
        from .offline import OfflineEditUnsupported, UnchangedEdit
        try:
            artifact=content.generate(state,revision=True,ordinary=True)
        except (OfflineEditUnsupported, UnchangedEdit) as exc:
            return {'stage':'completed','pending_fields':[],'reply':str(exc)}
        return {'artifacts':[*state['artifacts'],artifact],'stage':'completed','pending_fields':[],'reply':'已按你的意见调整普通文案，并保留此前版本。'}
    if not state.get('artifacts') or not state.get('strategy') or state['strategy']['status'] != 'approved':
        return {'reply': '请先确认当前策略并生成文案，再修改表达。', 'stage': 'collecting'}
    return generate(state)


def knowledge(state):
    if not state['brief'].get('brand_id'):
        return {'stage':'collecting', 'reply':'请先选择实际品牌并新建对话，再补充品牌资料。'}
    from .attachments import draft_note
    item = draft_note(state['task_id'], state['brief']['brand_id'], state['text'])
    from .intake import response
    return response(item)


def prepare_wait(state):
    from .questions import pending
    return {'input_request':pending(state), 'wait_prepared':True}


def await_input(state):
    payload = state.get('input_request')
    if not payload and state.get('active_attachment_id'):
        payload = {'kind':'attachment_confirmation','attachment_id':state['active_attachment_id']}
    if not payload:
        payload = {'kind':'strategy_confirmation','strategy_id':state['strategy']['id'], 'version':state['strategy']['version']}
    # Only receives server-validated state. No LLM, writes, or paid actions before interrupt.
    return interrupt(payload)


def build_graph(checkpointer):
    from . import intake
    graph = StateGraph(State)
    graph.add_node('prepare_wait', prepare_wait)
    graph.add_node('await_input', await_input)
    for name, fn in [('understand', understand), ('choose', choose), ('tool', tool), ('respond', reply),
                     ('finalize', finalize), ('generate', generate), ('revise', revise), ('knowledge', knowledge), ('intake', intake.handle), ('dispatch', intake.dispatch)]:
        graph.add_node(name, fn)
    graph.add_edge(START, 'dispatch')
    graph.add_conditional_edges('dispatch', lambda s: 'prepare_wait' if s['next_node']=='wait' else s['next_node'])
    graph.add_conditional_edges('understand', route)
    graph.add_edge('tool', 'choose')
    graph.add_conditional_edges('choose', route)
    for name in ('respond', 'finalize', 'generate', 'revise', 'knowledge', 'intake'):
        graph.add_edge(name, 'prepare_wait')
    graph.add_conditional_edges('prepare_wait', lambda s: 'await_input' if checkpointer is not None and
        (s.get('input_request') or s.get('active_attachment_id') or s.get('stage')=='awaiting_confirmation') else END)
    graph.add_edge('await_input','dispatch')
    return graph.compile(checkpointer=checkpointer)
