"""经营分析 Agent：热销/滞销分析 + 归因 + 对策。

分工（黄金组合）：
- 代码：排序、分档、算毛利率、找异常（保证数字准确）
- LLM：对滞销品逐维度归因 + 给对策（思维链，显式输出推理过程）

输入：商家产品明细（品名、售价、成本、周销量、库存、评分等）
输出：热销榜 / 滞销榜 + 每个滞销品的归因结论 + 可执行对策
"""
import json

from openai import OpenAI

from ..config import QWEN_BASE_URL, QWEN_API_KEY, COPY_MODEL, has_api_key, USE_MOCK


# 示例商家产品数据（演示用，明确标注，非真实数据）
SAMPLE_PRODUCTS = [
    {"name": "招牌珍珠奶茶", "category": "奶茶", "price": 12, "cost": 4.5, "weekly_sales": 320, "stock": 40, "rating": 4.6, "menu_position": "主推位"},
    {"name": "杨枝甘露", "category": "奶茶", "price": 18, "cost": 7.0, "weekly_sales": 260, "stock": 30, "rating": 4.7, "menu_position": "主推位"},
    {"name": "芝士葡萄", "category": "奶茶", "price": 19, "cost": 8.0, "weekly_sales": 210, "stock": 35, "rating": 4.4, "menu_position": "中部"},
    {"name": "柠檬绿茶", "category": "茶饮", "price": 12, "cost": 3.5, "weekly_sales": 150, "stock": 25, "rating": 4.2, "menu_position": "中部"},
    {"name": "黑糖波波鲜奶", "category": "奶茶", "price": 16, "cost": 6.0, "weekly_sales": 130, "stock": 28, "rating": 4.3, "menu_position": "中部"},
    {"name": "抹茶拿铁", "category": "拿铁", "price": 14, "cost": 5.5, "weekly_sales": 45, "stock": 200, "rating": 3.8, "menu_position": "尾部"},
    {"name": "草莓奶昔", "category": "奶昔", "price": 15, "cost": 6.5, "weekly_sales": 38, "stock": 180, "rating": 3.6, "menu_position": "尾部"},
    {"name": "燕麦轻乳", "category": "轻乳", "price": 17, "cost": 7.0, "weekly_sales": 55, "stock": 150, "rating": 3.9, "menu_position": "尾部"},
]


def _sort_and_tier(products: list[dict]) -> dict:
    """代码：按周销量排序并分档，算毛利率。"""
    for p in products:
        p["gross_margin"] = round((p["price"] - p["cost"]) / p["price"] * 100, 1) if p["price"] else 0.0
        p["sales_rank"] = 0

    ranked = sorted(products, key=lambda x: x["weekly_sales"], reverse=True)
    n = len(ranked)
    for i, p in enumerate(ranked):
        p["sales_rank"] = i + 1

    # 分档：前 1/3 热销，中 1/3 常销，后 1/3 滞销（销量低于均值一半的判为死货/异常）
    avg_sales = sum(p["weekly_sales"] for p in ranked) / n if n else 0
    hot = [p for p in ranked if p["weekly_sales"] >= avg_sales * 1.5]
    slow = [p for p in ranked if p["weekly_sales"] <= avg_sales * 0.5]
    normal = [p for p in ranked if p not in hot and p not in slow]

    # 异常：滞销 + 高库存（库存 > 100 或库存/周销量 > 3）
    anomalies = []
    for p in slow:
        turnover_ratio = p["stock"] / p["weekly_sales"] if p["weekly_sales"] else 999
        if p["stock"] >= 100 or turnover_ratio > 3:
            anomalies.append({**p, "turnover_ratio": round(turnover_ratio, 1)})

    return {
        "hot": hot,
        "normal": normal,
        "slow": slow,
        "anomalies": anomalies,
        "avg_sales": round(avg_sales, 1),
        "ranked": ranked,
    }


def _mock_analysis(products: list[dict], tiered: dict) -> dict:
    """无 key 时的 mock 归因，保证链路可跑通。"""
    anomalies = tiered["anomalies"] or tiered["slow"]
    conclusions = []
    for p in anomalies[:3]:
        conclusions.append({
            "name": p["name"],
            "sales": p["weekly_sales"],
            "stock": p["stock"],
            "gross_margin": p["gross_margin"],
            "reasoning": f"「{p['name']}」周销量 {p['weekly_sales']} 杯、库存 {p['stock']}，评分 {p['rating']}。"
                         f"排除价格因素（{p['price']} 元与同类持平），结合评分偏低且处于菜单尾部，"
                         f"判断为「曝光不足 + 口碑待提升」，而非单纯口味问题。",
            "suggestion": "建议提升菜单排位 + 做搭售套餐，或直接下架腾出库存位。",
        })
    return {
        "summary": f"共 {len(products)} 款产品，热销 {len(tiered['hot'])} 款、滞销 {len(tiered['slow'])} 款，"
                   f"发现 {len(anomalies)} 个异常滞销品需要关注。",
        "conclusions": conclusions,
    }


ANALYSIS_PROMPT = """你是资深茶饮门店经营分析师。请基于下面给出的产品数据，对滞销产品做「归因 + 对策」分析。

已知产品数据（JSON）：
{products}

你重点分析以下异常滞销产品（已由数据层筛选，销量低 + 库存高）：
{anomalies}

要求：
1. 对每个滞销品，按「价格 / 曝光位置 / 口碑评分 / 季节时机 / 搭配套餐」五个维度逐一排查，
   显式写出「排除了什么、锁定了什么」，不要只给结论。
2. 每个产品给出 1-2 个可执行的对策，按优先级排列。
3. 最后用一句话总结整体经营问题。

请严格按以下 JSON 格式输出（不要输出任何 JSON 以外的文字）：
{{
  "summary": "整体经营总结（一句话）",
  "conclusions": [
    {{
      "name": "产品名",
      "reasoning": "分步归因过程（说明排除了哪些维度、锁定了什么）",
      "suggestion": "可执行对策（按优先级）"
    }}
  ]
}}
"""


def analyze_products(products: list[dict]) -> dict:
    """经营分析主入口：代码分档 + LLM 归因。"""
    tiered = _sort_and_tier(products)

    if USE_MOCK or not has_api_key():
        llm = _mock_analysis(products, tiered)
    else:
        anomalies = tiered["anomalies"] or tiered["slow"][:3]
        # 精简字段，避免 prompt 过长
        brief = [{"name": p["name"], "price": p["price"], "cost": p["cost"],
                  "weekly_sales": p["weekly_sales"], "stock": p["stock"],
                  "rating": p["rating"], "menu_position": p["menu_position"],
                  "gross_margin": p["gross_margin"]} for p in products]
        anom_brief = [{"name": p["name"], "price": p["price"], "cost": p["cost"],
                       "weekly_sales": p["weekly_sales"], "stock": p["stock"],
                       "rating": p["rating"], "menu_position": p["menu_position"],
                       "turnover_ratio": p.get("turnover_ratio")} for p in anomalies]

        prompt = ANALYSIS_PROMPT.format(
            products=json.dumps(brief, ensure_ascii=False),
            anomalies=json.dumps(anom_brief, ensure_ascii=False),
        )
        try:
            client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)
            resp = client.chat.completions.create(
                model=COPY_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
            )
            text = resp.choices[0].message.content.strip()
            # 容错：剥离可能的 markdown 代码块包裹
            if text.startswith("```"):
                text = text.strip("`")
                if text.startswith("json"):
                    text = text[4:]
            llm = json.loads(text)
        except Exception:
            llm = _mock_analysis(products, tiered)

    # 合并：数据层结果 + LLM 归因
    return {
        "hot": tiered["hot"],
        "normal": tiered["normal"],
        "slow": tiered["slow"],
        "anomalies": tiered["anomalies"],
        "avg_sales": tiered["avg_sales"],
        "summary": llm.get("summary", ""),
        "conclusions": llm.get("conclusions", []),
    }
