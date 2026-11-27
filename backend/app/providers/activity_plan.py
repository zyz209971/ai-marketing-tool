"""活动策划 Agent：策划活动方案 + 测算能不能回本。

分工：
- LLM：根据商家目标（清库存/拉新/冲销量）生成 2-3 个活动方案（活动类型、折扣、目标）
- 代码：用 finance 引擎测算每个方案的毛利、净利、回本所需销量
- LLM：把数字翻译成人话解读 + 对比推荐

关键：算账全部用代码，LLM 只做方案生成和解读。
"""
import json

from openai import OpenAI

from ..config import QWEN_BASE_URL, QWEN_API_KEY, COPY_MODEL, has_api_key, USE_MOCK
from ..finance import SkuInput, StoreInput, calc_activity


def _default_sku() -> SkuInput:
    """示例目标产品（演示数据）。"""
    return SkuInput(
        name="招牌珍珠奶茶",
        online_price=12, offline_price=12,
        pack_cost=0, self_marketing_ratio=0.18,
        online_volume=2000, offline_volume=3000,
        ingredient_cost=4.5, packing_cost=1.0,
    )


def _mock_plan(goal: str, sku: SkuInput) -> dict:
    """无 key 时的 mock 方案。"""
    return {
        "summary": f"针对「{goal}」的目标，为你策划了以下活动方案。",
        "plans": [
            {"name": "第二杯半价", "type": "折扣", "discount": 0.25, "expected_volume": 600, "budget": 300, "online_ratio": 0.4,
             "desc": "同款第二杯半价，适合清库存，让顾客一次多买。"},
            {"name": "买一送一", "type": "买赠", "discount": 0.5, "expected_volume": 800, "budget": 500, "online_ratio": 0.4,
             "desc": "力度最大，引流效果强，但利润让利多。"},
            {"name": "满20减5", "type": "满减", "discount": 0.25, "expected_volume": 500, "budget": 200, "online_ratio": 0.5,
             "desc": "门槛适中，拉高客单价，适合冲销量。"},
        ],
    }


PLAN_PROMPT = """你是资深茶饮营销活动策划师。请为商家策划一场营销活动。

商家目标：{goal}
目标产品：{product}（成本 {cost} 元，售价 {price} 元）

请策划 3 个不同的活动方案（如：第二杯半价、买一送一、满减、套餐搭售、限时折扣等），
每个方案需给出：
- name：活动名
- type：活动类型（折扣/买赠/满减/套餐）
- discount：等效折扣力度（0-1 之间的小数，第二杯半价≈0.25，买一送一=0.5，满减按比例估算）
- expected_volume：预计活动期间能带来的销量（杯，合理估算）
- budget：活动预算（元，含物料/投放/让利外的额外成本）
- online_ratio：外卖占比（0-1 之间的小数）
- desc：一句话说明活动玩法和适用场景

要求：方案要可执行、符合校园奶茶场景，不要空泛。

请严格按以下 JSON 格式输出（不要输出 JSON 以外的文字）：
{{
  "summary": "一句话概括本次策划思路",
  "plans": [
    {{"name": "", "type": "", "discount": 0.25, "expected_volume": 600, "budget": 300, "online_ratio": 0.4, "desc": ""}}
  ]
}}
"""

INTERPRET_PROMPT = """你是茶饮经营顾问。以下是三个活动方案的测算结果，请给商家一份人话解读。

商家目标：{goal}
测算结果（JSON）：
{results}

要求：
1. 对比三个方案，指出哪个「最快回本」「净利最高」，并说明原因。
2. 给一个明确的推荐结论。
3. 用通俗易懂的话，不要堆术语，200 字以内。

直接输出解读文字，不要 JSON。
"""


def _interpret(goal: str, results: list[dict]) -> str:
    if USE_MOCK or not has_api_key():
        best = max(results, key=lambda r: r["net_profit"])
        return (f"三个方案中，「{best['name']}」综合表现最好，预计净利 {best['net_profit']} 元。"
                f"如果想最快回本，注意控制让利力度；如果首要目标是清库存，选让利最大的方案。")
    try:
        client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)
        resp = client.chat.completions.create(
            model=COPY_MODEL,
            messages=[{"role": "user", "content": INTERPRET_PROMPT.format(goal=goal, results=json.dumps(results, ensure_ascii=False))}],
            temperature=0.5,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        best = max(results, key=lambda r: r["net_profit"])
        return f"推荐「{best['name']}」，预计净利 {best['net_profit']} 元。"


def plan_activity(goal: str, product_name: str = "", product_cost: float = 4.5, product_price: float = 12.0) -> dict:
    """活动策划主入口：LLM 出方案 → 代码测算 → 解读推荐。"""
    sku = SkuInput(
        name=product_name or "招牌珍珠奶茶",
        online_price=product_price, offline_price=product_price,
        pack_cost=0, self_marketing_ratio=0.18,
        online_volume=2000, offline_volume=3000,
        ingredient_cost=product_cost, packing_cost=1.0,
    )

    # 1. LLM 生成方案
    if USE_MOCK or not has_api_key():
        plan = _mock_plan(goal, sku)
    else:
        try:
            client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)
            resp = client.chat.completions.create(
                model=COPY_MODEL,
                messages=[{"role": "user", "content": PLAN_PROMPT.format(
                    goal=goal, product=sku.name, cost=sku.ingredient_cost, price=sku.online_price)}],
                temperature=0.7,
            )
            text = resp.choices[0].message.content.strip()
            if text.startswith("```"):
                text = text.strip("`")
                if text.startswith("json"):
                    text = text[4:]
            plan = json.loads(text)
        except Exception:
            plan = _mock_plan(goal, sku)

    # 2. 代码测算每个方案
    results = []
    for p in plan.get("plans", []):
        r = calc_activity({
            "name": p.get("name"),
            "target_sku": sku,
            "discount": p.get("discount", 0.25),
            "expected_volume": p.get("expected_volume", 0),
            "budget": p.get("budget", 0),
            "online_ratio": p.get("online_ratio", 0.4),
        })
        results.append({**p, **r})

    # 3. LLM 解读 + 推荐
    interpretation = _interpret(goal, results)

    return {
        "goal": goal,
        "summary": plan.get("summary", ""),
        "plans": results,
        "interpretation": interpretation,
    }
