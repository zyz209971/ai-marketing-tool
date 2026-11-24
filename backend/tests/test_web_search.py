"""web_search 工具：Agent 自主联网搜索能力的契约测试。

验证四点：
1. 工具在白名单 TOOL_NAMES 中，且 call_tool 能正确路由；
2. mock 返回确定性占位结果，且通过 validate_tool 统一校验；
3. Decision 契约允许模型返回 tool='web_search' + tool_query；
4. 工具返回结构对齐其它经营工具（ToolResult 统一信封）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.marketing_agent import business
from app.marketing_agent.contracts import Decision, WebSearchRequest


def test_web_search_in_whitelist():
    assert 'web_search' in business.TOOL_NAMES


def test_web_search_mock_return():
    r = business.web_search(WebSearchRequest(query='2026 立冬节气营销热点'))
    assert r['status'] == 'ok'
    assert r['tool'] == 'web_search'
    assert r['result']['provider'] == 'mock'
    assert len(r['result']['results']) >= 1
    # 返回结构通过 validate_tool 的统一信封校验（已在 web_search 内调用）
    assert r['result']['query'] == '2026 立冬节气营销热点'


def test_call_tool_routes_to_web_search():
    r = business.call_tool('web_search', {'brand_id': None, 'sku_id': None}, '竞品奶茶价格')
    assert r['tool'] == 'web_search'
    assert r['result']['query'] == '竞品奶茶价格'


def test_decision_accepts_web_search():
    d = Decision(action='tool', tool='web_search', tool_query='查一下立冬热点', intent='plan')
    assert d.tool == 'web_search'
    assert d.tool_query == '查一下立冬热点'
    # schema 暴露给模型时含 web_search 枚举
    schema = Decision.model_json_schema()
    enums = schema['properties']['tool']['anyOf'][0]['enum']
    assert 'web_search' in enums
    assert 'tool_query' in schema['properties']
