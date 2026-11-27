"""店长对话记忆 + 追问回答。

解决「追问就失忆」的问题：
- 维护最近一轮的任务上下文（调度了哪些 Agent、结果摘要）
- 用户追问（没命中任何任务关键词）时，把上下文交给 LLM，
  让店长基于刚才的方案给出合理回答，而不是答非所问。
"""
from openai import OpenAI

from ..config import QWEN_BASE_URL, QWEN_API_KEY, COPY_MODEL, has_api_key, USE_MOCK

# 极简 session（单商家 Demo）：保存最近一轮的上下文
# 结构：{"message": 用户原话, "agents": [...], "analysis": {...}, "activity": {...}, "reply": ...}
_last_context: dict | None = None

MAX_CONTEXT_CHARS = 3000  # 上下文截断长度，防止 prompt 过长


def save_context(message: str, agents: list, analysis: dict | None, activity: dict | None):
    """每轮任务结束后保存上下文，供追问时使用。"""
    global _last_context
    _last_context = {
        "message": message,
        "agents": agents,
        "analysis": analysis,
        "activity": activity,
    }


def get_context() -> dict | None:
    return _last_context


def _summarize_context(ctx: dict) -> str:
    """把上一轮结果压缩成文本，塞进追问 prompt。"""
    parts = [f"商家上一条需求：{ctx['message']}"]
    # 团队编排（team.py）保存的通用摘要：reply/方案候选/分析结论等文本。
    if ctx.get("summary"):
        parts.append(f"上一轮的处理结果摘要：\n{ctx['summary']}")
    if "shop_analysis" in ctx["agents"] and ctx.get("analysis"):
        a = ctx["analysis"]
        hot = "、".join(p.get("name", "") for p in (a.get("hot") or []))
        slow = "、".join(p.get("name", "") for p in (a.get("slow") or []))
        parts.append(f"经营分析结果——热销：{hot}；滞销：{slow}")
        for c in (a.get("conclusions") or [])[:3]:
            parts.append(f"  滞销归因：{c.get('name','')} → {c.get('reasoning','')[:150]}")
    if "activity_plan" in ctx["agents"] and ctx.get("activity"):
        act = ctx["activity"]
        parts.append(f"活动策划思路：{act.get('summary', '')[:300]}")
        for p in (act.get("plans") or []):
            parts.append(
                f"  方案「{p.get('name','')}」：{p.get('desc','')[:120]}；"
                f"预计销量 {p.get('expected_volume')} 杯，预算 {p.get('budget')} 元，"
                f"净利 {p.get('net_profit')} 元，回本需 {p.get('break_even_volume')} 杯"
            )
        if act.get("interpretation"):
            parts.append(f"店长建议：{act['interpretation'][:300]}")
    text = "\n".join(parts)
    return text[:MAX_CONTEXT_CHARS]


FOLLOWUP_PROMPT = """你是校园奶茶店的「AI 营销店长」。商家刚才让你完成了一轮经营分析/活动策划，现在他针对结果提出了追问。

上一轮的上下文：
{context}

商家的追问：
{question}

要求：
1. 必须基于上一轮的具体数据和方案回答，引用具体数字（如销量、净利、回本杯数），不要泛泛而谈
2. 如果商家质疑某个数字（比如觉得销量估计太高），要正面回应：解释这个估算的依据，并主动给出调整方式（比如按更保守的销量重算会怎样）
3. 口语化、像店长跟老板聊天，不要太长，300 字以内
4. 如果追问需要重新测算，给出调整后的估算结论
"""


def answer_followup(question: str) -> dict:
    """用 LLM 基于上一轮上下文回答追问。返回 {"reply": ...}。"""
    ctx = get_context()
    if not ctx:
        return {"reply": None}  # 没有上下文，交给上层走引导

    if USE_MOCK or not has_api_key():
        return {"reply": "（示例模式）针对你的追问：我刚才的方案里预计销量 600 杯是按万圣节当天校园流量的乐观估计。如果你觉得卖不了这么多，我们可以按 300 杯重算——按这个量，第二杯半价方案的净利会降到约 100 元，回本杯数不变，但预算要压缩到 150 元。你可以告诉我一个你估计的销量，我重新帮你算一遍。"}

    try:
        client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)
        resp = client.chat.completions.create(
            model=COPY_MODEL,
            messages=[{"role": "user", "content": FOLLOWUP_PROMPT.format(
                context=_summarize_context(ctx), question=question
            )}],
            temperature=0.6,
        )
        return {"reply": resp.choices[0].message.content.strip()}
    except Exception as e:
        return {"reply": f"我尝试结合刚才的方案回答你，但出了点问题：{e}"}
