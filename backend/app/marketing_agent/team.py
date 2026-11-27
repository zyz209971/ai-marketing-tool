"""店长 Agent + 专家团队编排（薄思考）。

团队结构（1 店长 + 4 专家）：
- StoreManager（店长 Agent）      分诊：看懂用户要什么，派给对的专家
- SalesAnalyst（经营分析 Agent）  销量 / 成本 / 优惠测算（复用 business.py，纯本地计算）
- CampaignPlanner（活动方案 Agent）策划活动 / 定优惠 / 出方案（复用 evaluate_promotion）
- Copywriter（文案生成 Agent）     把方案写成多平台文案（复用 providers/copywriting）
- PosterDesigner（海报生成 Agent） 产品海报（复用 providers/image）

设计原则（平衡「思考时间」与「编排设计」）：
1. 能写死的编排写进代码，不让模型来回「想」；
2. 模型只在两处出手：店长分诊（1 次）+ 被调用的专家产出（各 1 次）；
3. 缺信息不逐项追问，用默认值 + 可点选兜底；
4. 复用 business.py / providers 的全部能力，前端与 store/api 契约不变。

本模块只负责「编排」，不重复实现任何经营计算或文案/生图逻辑。
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from uuid import uuid4

from . import business
from .contracts import Brief
from ..config import AGENT_USE_MOCK as USE_MOCK

# 商品名 → demo 商品外的常见别名（用户可能用口语/别名称呼模拟商品）。
_SKU_ALIASES = {
    '茉莉': 'T001', '茉莉花': 'T001', '茉莉奶绿': 'T001',
    '乌龙': 'T002', '乌龙奶茶': 'T002',
    '红茶': 'T003', '红茶奶茶': 'T003',
}


def _resolve_product(state: dict) -> dict:
    """解析用户想要的产品，返回 {name, points, price, brand, category, source}。

    优先级（用户要求：优先走 RAG 产品库，不再先匹配 demo 的 3 个模拟商品）：
    1. 先从用户文本剥离动作词/平台词，得到商品名候选，直接去 RAG 产品库检索真实产品；
       命中就用它的真实名称/卖点/价格/品牌/类别，绝不静默降级成别的商品；
    2. RAG 检索不到 → 才回退到 demo catalog（T001/T002/T003）按别名匹配；
    3. 都找不到 → 返回 None，由调用方给出「告诉我想写哪款」的引导。

    source 标记：'rag'（RAG 知识库真实产品）| 'catalog'（demo 模拟商品）| None。
    """
    b = state.get('brief', {})
    text = state.get('text', '')
    catalog = business.catalog(b)
    # 1. 优先去 RAG 产品库检索真实产品（用户提到的商品名）。
    from .. import rag
    # 从整句话里剥离「帮我写/做个/的海报/文案」等动作与平台词，尽量还原商品名，
    # 提高 RAG 产品检索的命中率（整句检索会稀释得分）。
    _noise = ('帮我', '写一条', '写一条', '写', '做个', '做张', '生成', '给我', '来一段', '来一条',
              '出一条', '出一段', '的', '海报', '配图', '文案', '标题', '内容', '小红书', '抖音',
              '公众号', '一条', '一张', '一篇', '活动', '推广', '宣传')
    _name_candidate = text
    for w in _noise:
        _name_candidate = _name_candidate.replace(w, '')
    _name_candidate = re.sub(r'[，。！？!?、,.：:；;\s]+', ' ', _name_candidate).strip()
    # 依次尝试：剥离后的候选名 → 整句；阈值对候选名更宽松。
    hits = None
    for candidate, threshold in ((_name_candidate, 0.20), (text, 0.30)):
        if not candidate:
            continue
        _hits = rag.search_products(candidate, top_k=3, use_vector=False)
        if _hits and _hits[0].get('score', 0.0) >= threshold and _hits[0].get('product_name'):
            hits = _hits
            break
    if hits and hits[0].get('product_name'):
        h = hits[0]
        import re as _re
        facts = []
        for label in ('卖点', '规格', '热量', '成分'):
            m = _re.search(rf'{label}[:：]([^；;]*)', h.get('text') or '')
            if m and m[1].strip():
                facts.append(m[1].strip())
        points = '、'.join(facts) if facts else (h.get('category') or '饮品')
        price = ''
        pm = _re.search(r'价格[:：]([^；;]*)', h.get('text') or '')
        if pm:
            price = pm[1].strip()
        return {'name': h['product_name'], 'points': points, 'price': price,
                'brand': h.get('brand', ''), 'category': h.get('category', ''),
                'sku_id': None, 'source': 'rag'}
    # 2. RAG 检索不到，才回退到 demo catalog（T001/T002/T003）。
    if b.get('sku_id') and b['sku_id'] in catalog:
        p = catalog[b['sku_id']]
        return {'name': p['name'], 'points': '、'.join(p.get('selling', [])) or '鲜奶茶饮',
                'price': f"¥{p['price']/100:.2f}" if p.get('price') else '',
                'brand': '', 'category': '', 'sku_id': b['sku_id'], 'source': 'catalog'}
    for alias, sku in _SKU_ALIASES.items():
        if alias in text and sku in catalog:
            p = catalog[sku]
            return {'name': p['name'], 'points': '、'.join(p.get('selling', [])) or '鲜奶茶饮',
                    'price': f"¥{p['price']/100:.2f}" if p.get('price') else '',
                    'brand': '', 'category': '', 'sku_id': sku, 'source': 'catalog'}
    # 3. 完全找不到，返回 None。
    return None

# 团队角色（中文展示名 + 英文标识），供进度提示与日志使用。
TEAM = {
    'manager': {'name': '店长 Agent', 'key': 'StoreManager'},
    'analyst': {'name': '经营分析 Agent', 'key': 'SalesAnalyst'},
    'planner': {'name': '活动方案 Agent', 'key': 'CampaignPlanner'},
    'copywriter': {'name': '文案生成 Agent', 'key': 'Copywriter'},
    'poster': {'name': '海报生成 Agent', 'key': 'PosterDesigner'},
}

# 用户主动要海报时才会触发海报 Agent 的关键词。
_POSTER_WORDS = ('海报', '配个图', '配图', '做个图', '做张图', '生成图片', '生成海报', '出图', '图片')


# ---------------------------------------------------------------------------
# 店长 Agent：分诊（这是整套流程里唯一一次「理解意图」的模型调用点）
# ---------------------------------------------------------------------------

def _extract_brief(state: dict) -> dict:
    """轻量字段提取（规则，不调模型）。

    从用户文本里识别商品/平台/优惠/日期，补进 brief；提取不到用默认值兜底，
    避免像旧版那样逐项追问。这是「能写死就不调模型」原则的落地。
    """
    text = state.get('text', '')
    b = dict(state.get('brief', {}))
    # 商品：按名称或编号匹配 catalog。匹配不到就保持 sku_id 为空，
    # 不再静默兜底成第一个商品——真正的商品解析交给 _resolve_product，
    # 它会在 catalog 找不到时去 RAG 产品库检索真实产品（如「抹茶丝绒拿铁」）。
    catalog = business.catalog(b)
    if not b.get('sku_id'):
        for sku, p in catalog.items():
            if p['name'] in text or sku in text:
                b['sku_id'] = sku
                break
        else:
            for alias, sku in _SKU_ALIASES.items():
                if alias in text and sku in catalog:
                    b['sku_id'] = sku
                    break
    # 平台：小红书/抖音/公众号。
    for label, value in [('小红书', 'xiaohongshu'), ('抖音', 'douyin'), ('公众号', 'wechat_official_account')]:
        if label in text:
            b['platform'] = value
            break
    if not b.get('platform'):
        b['platform'] = 'xiaohongshu'
    # 优惠：第二杯半价/七折/不打折等。
    if '第二杯半价' in text or '第二杯五折' in text or '半价' in text:
        b['offer'] = {'type': 'second_cup_discount', 'pay_bps': 5000}
    elif re.search(r'第二杯(?:改成|改为|调整为)?\s*([一二三四五六七八九]|\d(?:\.\d)?)折', text):
        m = re.search(r'第二杯(?:改成|改为|调整为)?\s*([一二三四五六七八九]|\d(?:\.\d)?)折', text)
        raw = m[1]
        digits = '一二三四五六七八九'
        discount = digits.index(raw) + 1 if raw in digits else float(raw)
        b['offer'] = {'type': 'second_cup_discount', 'pay_bps': int(discount * 1000)}
    elif '不打折' in text or '原价' in text or '取消优惠' in text:
        b['offer'] = {'type': 'none', 'pay_bps': 10000}
    # 日期：YYYY-MM-DD 区间，或「下周」。
    dates = re.findall(r'\d{4}-\d{2}-\d{2}', text)
    if len(dates) >= 2:
        b['start_date'] = dates[0]
        b['end_date'] = dates[1]
    elif '下周' in text and not b.get('start_date'):
        today = date.today()
        start = today + timedelta(days=7 - today.weekday())
        b['start_date'] = start.isoformat()
        b['end_date'] = (start + timedelta(days=7)).isoformat()
    return b


def _classify(text: str, brief: dict) -> str:
    t = text.strip()
    # 用户点选方案（「选择第二杯5折」带 patch.offer）→ 直接出方案，不再重新给候选。
    if brief.get('offer') and re.search(r'选择|选这个|就这个|用这个|确定', t):
        return 'planner_chosen'
    # 追问优先（借鉴 agent-team 分支）：店长记忆里有上一轮结果，且这句话像追问
    # （短问句、有疑问词/问号、没有「帮我做/写/生成」等强任务动词）→ 交给追问记忆回答。
    from ..providers import keeper_memory
    _task_verbs = ('帮我', '做个', '做张', '写', '生成', '出一张', '出一条', '看看', '分析', '测算', '策划', '选择', '选')
    if (keeper_memory.get_context() and len(t) <= 40
            and re.search(r'？|\?|吗|呢|怎么样|为什么|怎么算|如何|多少|觉得|建议', t)
            and not any(v in t for v in _task_verbs)):
        return 'chat'
    # 明确要海报 → poster
    if any(w in t for w in _POSTER_WORDS):
        return 'poster'
    # 明确要写文案 / 出内容 → copywriter
    if re.search(r'写.*(文案|标题|内容)|文案|标题|写一段|写点|来一段|出一段|生成.*文案', t):
        return 'copywriter'
    # 只做经营分析 / 看数据 → analyst
    if re.search(r'(卖得|销量|卖得|卖了多少|看看.*(数据|销量)|分析.*(销量|数据)|最近.*(销量|经营)|哪个.*(卖得|销量)|滞销|动销)', t):
        return 'analyst'
    # 活动 / 促销 / 优惠 / 方案 → planner
    if re.search(r'(活动|促销|优惠|折扣|第二杯|半价|打折|方案|策略|策划|ROI|测算|推广|营销)', t):
        return 'planner'
    # 既有商品又要求文案+图的完整需求 → full（活动方案+文案+海报一条龙）
    if re.search(r'(全套|一条龙|方案.*(文案|海报)|文案.*海报|海报.*文案)', t):
        return 'full'
    return 'chat'

    # 注意：上面的规则分支用于离线演示与快速兜底。真实 LLM 模式可在此处
    # 追加一次轻量分诊调用；为控制模型调用次数，规则已覆盖绝大多数演示场景。


def _manager_dispatch(state: dict) -> dict:
    """店长 Agent：分诊并返回派单结果 + 给用户的一句团队话术。"""
    # 每轮必须重新分类：服务端会把上一轮持久化的 state（含旧 team_intent）读出来，
    # 盲信遗留值会让第二轮沿用第一轮的意图（追问/新任务全被旧 intent 劫持）。
    state.pop('team_intent', None)
    intent = _classify(state.get('text', ''), state.get('brief', {}))
    state['team_intent'] = intent
    # 团队话术：让「团队协作」对用户可见，但不啰嗦。
    role_hint = {
        'analyst': '经营分析 Agent 正在查看经营数据',
        'planner': '活动方案 Agent 正在测算优惠',
        'planner_chosen': '活动方案 Agent 正在整理方案，文案生成 Agent 正在撰写',
        'copywriter': '文案生成 Agent 正在撰写文案',
        'poster': '海报生成 Agent 正在出图',
        'full': '正在调度经营分析、活动方案、文案与海报四个 Agent 协作',
        'chat': '店长 Agent',
    }[intent]
    return {'team_intent': intent, 'role_hint': role_hint}


# ---------------------------------------------------------------------------
# 专家 Agent 1：经营分析 Agent（纯本地计算，不调模型）
# ---------------------------------------------------------------------------

def _sales_analyst(state: dict) -> dict:
    """经营分析 Agent：销量 / 成本 / 测算，直接复用 business.py 的本地工具。"""
    b = state['brief']
    summary = business.call_tool('get_sales_summary', b)
    tools = {'get_sales_summary': summary}
    if b.get('sku_id'):
        constraints = business.call_tool('get_business_constraints', b)
        tools['get_business_constraints'] = constraints
    # 组装给前端看的分析话术（前端有专门的「经营数据概览」卡片，靠 sales 字段触发）。
    metrics = summary['result'].get('metrics', [])
    lines = []
    for m in metrics:
        chg = ''
        if m.get('change_ratio') is not None:
            arrow = '下降' if m['change_ratio'] < 0 else '上升'
            chg = f"，本期{arrow} {abs(m['change_ratio'])*100:.0f}%"
        lines.append(f"· {m['name']}：上期 {m.get('previous_qty') or '未知'} 杯 → 本期 {m.get('current_qty') or '未知'} 杯{chg}")
    body = '\n'.join(lines) if lines else '暂未取到销量数据。'
    reply = f"我帮你看了最近的经营数据：\n{body}\n\n这只是描述性对比，不能据此断定原因。想继续看哪款商品的成本，或者做个优惠测算，直接告诉我。"
    return {'tool_results': {**state.get('tool_results', {}), **tools},
            'reply': reply, 'stage': 'completed', 'pending_fields': [],
            'suggestions': ['帮我测算第二杯半价是否划算', '看看哪款饮品卖得不好', '帮我写一条活动文案']}


# ---------------------------------------------------------------------------
# 专家 Agent 2：活动方案 Agent（复用 evaluate_promotion 的测算 + 本地候选方案）
# ---------------------------------------------------------------------------

def _campaign_planner(state: dict) -> dict:
    """活动方案 Agent：定优惠 / 出方案，复用 business.py 的测算。

    不做逐字段追问：缺的信息用默认值补上，优惠直接给可点选候选方案。
    """
    b = state['brief']
    # 兜底默认值：商品/平台/日期/优惠没给时，用演示门店默认，避免阻塞。
    if not b.get('sku_id'):
        first_sku = next(iter(business.catalog(b)), None)
        b['sku_id'] = b['sku_id'] or first_sku
    if not b.get('platform'):
        b['platform'] = 'xiaohongshu'
    if not b.get('start_date'):
        today = date.today()
        b['start_date'] = (today + timedelta(days=7 - today.weekday())).isoformat()
        b['end_date'] = (date.fromisoformat(b['start_date']) + timedelta(days=7)).isoformat()
    # 候选优惠：固定三类，本地生成 + 本地成本校验（不调模型）。
    # 候选阶段只看「单位收益」（roi_mode=unit_only），不需要日期/销量/预算，
    # 避免逐项追问；用户选定方案后再补 ROI 情景。
    probe_brief = {**b, 'roi_mode': 'unit_only', 'assess_minimum': True}
    options = []
    for offer, rationale in [
            ({'type': 'second_cup_discount', 'pay_bps': 5000}, '鼓励同单买两杯，让利最明显。'),
            ({'type': 'second_cup_discount', 'pay_bps': 7000}, '让利更小，作为半价的保守备选。'),
            ({'type': 'none', 'pay_bps': 10000}, '不降价，侧重商品卖点，作为原价对照。')]:
        label = '原价推广' if offer['type'] == 'none' else f"第二杯{offer['pay_bps']/1000:g}折"
        try:
            evaluation = business.call_tool('evaluate_promotion', {**probe_brief, 'offer': offer})
        except Exception:
            evaluation = None
        if evaluation and evaluation['status'] == 'ok' and not evaluation['missing_fields']:
            options.append({'name': label, 'offer': offer, 'rationale': rationale, 'evaluation': evaluation})
    if not options:
        # 测算还缺成本等字段时，退回经营分析去补数，不硬编方案。
        return _sales_analyst(state)
    product_name = business.catalog(b)[b['sku_id']]['name'] if b.get('sku_id') in business.catalog(b) else '饮品'
    reply = (f"我比对了三个活动选择，供你点选（同一商品、同一优惠方式下的单位收益）：\n"
             f"选一个可行的，我就整理成方案，再让文案生成 Agent 帮你写出来。")
    return {'brief': b, 'options': options, 'pending_fields': ['offer'],
            'stage': 'collecting', 'reply': reply,
            'suggestions': [], 'tool_results': state.get('tool_results', {})}


def _campaign_planner_chosen(state: dict) -> dict:
    """用户已选定优惠方案：活动方案 Agent 出最终方案，并转交文案 Agent 写出来。"""
    b = state['brief']
    # 最终方案测算也只看单位收益，避免 ROI 情景字段再触发追问。
    b['roi_mode'] = 'unit_only'
    b['assess_minimum'] = True
    evaluation = business.call_tool('evaluate_promotion', b)
    if evaluation.get('status') != 'ok' or evaluation['missing_fields']:
        return _campaign_planner(state)
    product_name = business.catalog(b)[b['sku_id']]['name'] if b.get('sku_id') in business.catalog(b) else '饮品'
    offer = b.get('offer') or {}
    offer_label = '原价推广' if offer.get('type') == 'none' else f"第二杯{offer.get('pay_bps', 5000)/1000:g}折"
    avg = evaluation['result'].get('average_contribution_minor')
    tool_results = {**state.get('tool_results', {}), 'evaluate_promotion': evaluation}
    # 方案已定，直接交文案 Agent 产出文案。
    state_for_copy = {**state, 'brief': b, 'tool_results': tool_results}
    copied = _copywriter(state_for_copy)
    reply = (f"方案确定：{product_name} · {offer_label}。\n"
             f"平均每杯贡献收益 {('¥' + format(avg/100, '.2f')) if avg is not None else '暂未测算'}。\n"
             f"文案生成 Agent 已经帮你写好了，往下看。")
    return {**copied, 'brief': b, 'tool_results': tool_results, 'reply': reply,
            'stage': 'completed', 'pending_fields': [], 'options': [], 'suggestions': ['顺便帮我做个海报', '语气再简短一点']}


# ---------------------------------------------------------------------------
# 专家 Agent 3：文案生成 Agent（复用 providers/copywriting 或 campaign）
# ---------------------------------------------------------------------------

def _copywriter(state: dict) -> dict:
    """文案生成 Agent：把产品/方案写成多平台文案。

    复用旧版 pipeline 的 RAG 增强能力：
    1. rag.resolve_product_context —— 解析唯一产品事实，注入品牌/类别/卖点，避免凭空编造；
    2. rag.search_for_platforms —— 按平台分别检索爆款营销案例作为风格参考（小红书/抖音/公众号各取各的）；
    3. copywriting.generate_copy —— 三平台并行生成，带上 references + product_context。
    """
    b = state['brief']
    from ..providers import copywriting
    from .. import rag
    product = _resolve_product(state)
    if product is None:
        return {'reply': '先告诉我想写哪款饮品的文案，我再帮你写。', 'stage': 'collecting',
                'pending_fields': ['sku_id'], 'options': [], 'suggestions': []}
    name = product['name']
    points = product['points']
    price = product['price']
    # RAG 产品上下文：解析唯一产品，注入已确认的品牌/类别/卖点（防止幻觉）。
    # 若商品本身来自 RAG（source=='rag'），直接用它带回的真实信息作为上下文，不再二次检索。
    product_context = None
    if product['source'] == 'rag':
        product_context = {'product_name': name, 'brand': product['brand'],
                           'category': product['category'], 'text': points}
    else:
        product_context = rag.resolve_product_context(name)
    # RAG 爆款案例：按平台分别检索，作为写作风格/结构参考。
    references = {}
    try:
        query = f"产品：{name}；卖点：{points}；价格：{price}；任务：新品营销文案"
        references = rag.search_for_platforms(query, copywriting.PLATFORMS.keys(), top_k=3)
    except Exception:
        references = {}
    copies = copywriting.generate_copy(name, points, price, references, product_context=product_context)
    is_mock = getattr(copywriting, 'USE_MOCK', True) or not copywriting.has_api_key()
    # 收集 RAG 命中的 source_refs（文档 id），写进 artifact 供前端「查看依据」展示。
    source_refs = []
    for refs in references.values():
        for r in refs:
            if r.get('document_id') and r['document_id'] not in source_refs:
                source_refs.append(r['document_id'])
    retrieval = {
        'marketing_refs': [r.get('document_id') for refs in references.values() for r in refs],
        'memory_refs': [],
    }
    # 组装成前端能渲染的 artifact（复用 content.generate 的 artifact 结构约定）。
    # copies 现在每个平台返回 list[str]（3 条候选），逐条编号展示。
    lines = []
    for platform, candidates in copies.items():
        candidates = candidates if isinstance(candidates, list) else [candidates]
        lines.append(f"【{platform}】")
        for idx, text in enumerate(candidates, 1):
            lines.append(f"{idx}. {text}")
    body = '\n\n'.join(lines)
    artifact = {'id': uuid4().hex, 'kind': 'content', 'title': f"{name} 营销文案",
                'body': body, 'summary': '', 'hashtags': [],
                'platform': b.get('platform') or 'xiaohongshu',
                'strategy_id': None, 'strategy_version': None,
                'version': len(state.get('artifacts', [])) + 1,
                'creative_body': body, 'revision_scope': 'all', 'parent_artifact_id': None,
                'knowledge_version': '', 'source_refs': source_refs, 'retrieval': retrieval,
                'mock': is_mock,
                'data_kind': 'synthetic', 'stale': False,
                'validation': {'terms_match': True, 'semantic_review': 'not_automatically_verified'},
                'style': b.get('style', '自然、简洁，不夸大功效')}
    return {'artifacts': [*state.get('artifacts', []), artifact],
            'stage': 'completed', 'pending_fields': [],
            'reply': f"文案写好了（{name}），已结合知识库里的产品资料和爆款案例参考。可以点下方「复制文案」，或告诉我语气想怎么调。",
            'suggestions': ['标题活泼一点', '语气简短一点', '顺便帮我做个海报']}


# ---------------------------------------------------------------------------
# 专家 Agent 4：海报生成 Agent（复用 providers/image）
# ---------------------------------------------------------------------------

def _poster_designer(state: dict) -> dict:
    """海报生成 Agent：产品海报，复用旧版 pipeline 的生图 + RAG 能力。

    1. rag.resolve_product_context —— 解析唯一产品，注入品牌/类别，避免生图时串产品；
    2. vision.parse_poster —— 有参考海报时反向解析出结构化提示词（复用旧版反向解析）；
    3. image.build_prompt —— 用产品上下文 + 解析结果拼最终提示词（只替换主体，其余复用）；
    4. image.generate_image —— 出图（通义万相）。
    """
    b = state['brief']
    from ..providers import image, vision
    from .. import rag
    product = _resolve_product(state)
    if product is None:
        return {'reply': '先告诉我想给哪款饮品做海报。', 'stage': 'collecting',
                'pending_fields': ['sku_id'], 'options': [], 'suggestions': []}
    name = product['name']
    points = product['points']
    price = product['price']
    # RAG 产品上下文：解析唯一产品，注入品牌/类别，避免生图串产品、防幻觉。
    if product['source'] == 'rag':
        product_context = {'product_name': name, 'brand': product['brand'],
                           'category': product['category'], 'text': points}
    else:
        product_context = rag.resolve_product_context(name)
    # 反向解析：有参考海报图时用 vision 解析；无图则用 mock 结构化模板兜底。
    poster_url = state.get('poster_url') or b.get('poster_url')
    if poster_url:
        parsed = vision.parse_poster(None, poster_url)
    else:
        parsed = vision._mock_parse()
    # 拼最终提示词：只替换主体，其余（场景/构图/风格/光影/色彩）复用解析结果。
    prompt = image.build_prompt(parsed, name, points, price, product_context)
    result = image.generate_image(prompt)
    # 把生图结果放进 artifacts，前端可用 artifact 卡片或后续海报组件展示。
    poster = {'id': uuid4().hex, 'kind': 'poster', 'title': f"{name} 产品海报",
              'image': result, 'prompt': prompt, 'version': len(state.get('artifacts', [])) + 1,
              'mock': result.get('mock', False), 'stale': False,
              'product_context': product_context}
    if result.get('error'):
        return {'artifacts': [*state.get('artifacts', []), poster], 'stage': 'completed',
                'pending_fields': [],
                'reply': f"海报生成了，但出图服务返回了提示：{result['error']}。海报占位已保留，可配置生图密钥后重试。",
                'suggestions': ['重新生成海报', '帮我写这款的文案']}
    return {'artifacts': [*state.get('artifacts', []), poster], 'stage': 'completed',
            'pending_fields': [],
            'reply': f"海报做好了（{name}），已结合知识库里的产品资料生成。可以在作品里查看图片，需要调整风格或换商品随时说。",
            'suggestions': ['换个暖色调', '顺便帮我写文案']}


# ---------------------------------------------------------------------------
# 店长总调度：把分诊结果派给对应专家
# ---------------------------------------------------------------------------

def dispatch(state: dict) -> dict:
    """店长 Agent 的调度入口。返回更新后的 state（契约与旧 runtime 一致）。"""
    intent = state.get('team_intent') or _classify(state.get('text', ''), state.get('brief', {}))
    state['team_intent'] = intent

    if intent == 'analyst':
        return _sales_analyst(state)
    if intent == 'planner_chosen':
        # 用户已选优惠方案：直接出方案 + 文案，不再给候选。
        return _campaign_planner_chosen(state)
    if intent == 'planner':
        return _campaign_planner(state)
    if intent == 'copywriter':
        return _copywriter(state)
    if intent == 'poster':
        return _poster_designer(state)
    if intent == 'full':
        # 一条龙并行化（借鉴 agent-team 分支的调度模式）：
        # 经营分析 与 海报生成 互不依赖 → 线程池并行；方案 → 文案 有依赖 → 串行。
        # 店长的「思考链路」显性化：拆解过程写进回复，看得见但不多花模型调用。
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_analysis = pool.submit(_sales_analyst, state)
            fut_poster = pool.submit(_poster_designer, state)
            analysis_result = fut_analysis.result()
            poster_result = fut_poster.result()
        state.update(analysis_result)
        state.update(_campaign_planner(state))
        state.update(_copywriter(state))
        state.update(poster_result)
        plan_lines = ['我拆解了一下你的需求，并行派给团队：',
                      '· 让「经营分析 Agent」盘点店内热销/滞销，定位问题品',
                      '· 让「活动方案 Agent」出优惠候选并本地测算',
                      '· 让「文案生成 Agent」把方案写成多平台文案',
                      '· 让「海报生成 Agent」出产品海报（与分析并行）']
        state['reply'] = '\n'.join(plan_lines) + '\n\n都完成了，请查看下方结果，需要调整直接说。'
        return state
    # chat：先试「追问」——用户没命中任务关键词时，基于上一轮结果用 LLM 回答（店长不失忆）。
    from ..providers import keeper_memory
    follow = keeper_memory.answer_followup(state.get('text', ''))
    if follow.get('reply'):
        return {'stage': 'collecting', 'pending_fields': [],
                'reply': follow['reply'], 'is_followup': True,
                'suggestions': ['帮我做个第二杯半价的活动', '帮我写一条小红书文案']}
    # 没有上下文（首轮闲聊）：给一个轻量的团队引导。
    return {'stage': 'collecting', 'pending_fields': [],
            'reply': '我是店长 Agent，下面有经营分析、活动方案、文案生成、海报生成四位助手。\n'
                     '你可以直接说：看销量、做个活动方案、写条文案、配张海报。',
            'suggestions': ['看看最近哪些饮品卖得不好', '帮我做个第二杯半价的活动', '帮我写一条小红书文案', '帮我做个产品海报']}


def _save_team_context(message: str, merged: dict):
    """把本轮团队处理结果压缩成摘要，存进店长记忆（供追问时使用）。

    摘要包含：回复、优惠候选及测算数字、销量对比结论、产出物标题。
    """
    from ..providers import keeper_memory
    intent = merged.get('team_intent', 'chat')
    agent_names = {'analyst': '经营分析', 'planner': '活动方案', 'planner_chosen': '活动方案+文案',
                   'copywriter': '文案生成', 'poster': '海报生成', 'full': '全团队协作',
                   'chat': '店长'}.get(intent, intent)
    parts = [f'调度了：{agent_names} Agent']
    reply = merged.get('reply', '')
    if reply:
        parts.append(f'店长回复：{reply[:400]}')
    # 优惠候选及测算数字（追问「划算吗/怎么算的」时要引用）。
    options = merged.get('options') or []
    if options:
        opt_lines = []
        for o in options[:3]:
            avg = (o.get('evaluation', {}).get('result', {}) or {}).get('average_contribution_minor')
            opt_lines.append(f"「{o.get('name')}」平均每杯贡献 {('¥' + format(avg/100, '.2f')) if avg is not None else '暂未测算'}")
        parts.append('给出的优惠候选：' + '；'.join(opt_lines))
    # 销量对比结论（追问「为什么卖得不好」时要引用）。
    sales = (merged.get('tool_results', {}) or {}).get('get_sales_summary', {})
    metrics = (sales.get('result', {}) or {}).get('metrics', [])
    if metrics:
        sales_lines = [f"{m['name']}：{m.get('previous_qty') or '?'}→{m.get('current_qty') or '?'}杯"
                       for m in metrics[:5]]
        parts.append('销量对比：' + '；'.join(sales_lines))
    # 产出物（追问「刚才写的文案呢」时要引用）。
    artifacts = merged.get('artifacts') or []
    if artifacts:
        parts.append('产出了：' + '、'.join(a.get('title', '') for a in artifacts[-3:]))
    keeper_memory.save_context(message, [intent], None, None)
    # 把自定义摘要塞进记忆上下文（keeper_memory 支持 summary 字段）。
    ctx = keeper_memory.get_context()
    if ctx is not None:
        ctx['summary'] = '\n'.join(parts)[:keeper_memory.MAX_CONTEXT_CHARS]


def invoke(state: dict) -> dict:
    """team 编排的统一入口：店长分诊 → 派单 → 返回结果 state。"""
    state = dict(state)
    # 先做轻量字段提取（规则，不调模型），补齐商品/平台/优惠，避免逐项追问。
    if state.get('text'):
        extracted = _extract_brief(state)
        # 用户通过 patch 显式传入的字段优先，不被规则覆盖。
        extracted.update(state.get('input_patch') or {})
        state['brief'] = Brief.model_validate(extracted).model_dump(mode='json')
    dispatch_info = _manager_dispatch(state)
    state.update(dispatch_info)
    result = dispatch(state)
    # 保证前端依赖的字段存在。
    state.setdefault('artifacts', [])
    state.setdefault('options', [])
    state.setdefault('suggestions', [])
    state.setdefault('pending_fields', [])
    state.setdefault('tool_results', {})
    state.setdefault('strategy', None)
    state.setdefault('strategies', [])
    state.setdefault('unit_result', None)
    state.setdefault('input_request', None)
    merged = {**state, **result}
    # 保存本轮上下文到店长记忆：下一轮用户追问（无任务关键词）时，
    # 店长能基于本轮的具体结果回答，不再答非所问（借鉴 agent-team 分支的 keeper_memory）。
    try:
        _save_team_context(state.get('text', ''), merged)
    except Exception:
        pass  # 记忆失败不影响主链路
    # 标记本轮已完整产出，跳过 runtime.park（旧 graph 的同步逻辑），
    # 由 store.finish 直接落库。避免 team 编排再被旧 graph 接管。
    merged['wait_prepared'] = True
    merged['team_trace'] = [{'agent': TEAM['manager']['key'], 'status': 'dispatched'},
                            {'agent': TEAM.get({'analyst': 'analyst', 'planner': 'planner', 'planner_chosen': 'planner',
                                                'copywriter': 'copywriter', 'poster': 'poster',
                                                'full': 'manager', 'chat': 'manager'}[merged['team_intent']], {}).get('key', '')},
                            {'status': 'done'}]
    return merged
