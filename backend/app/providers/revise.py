"""提示词改写：根据用户修改意见，在原提示词基础上生成新提示词（多轮改图核心）。

用户第一次生成后可能不满意，提出自然语言修改意见（如"去掉柿子和橘子，背景改成绿色调"），
本模块把「原提示词 + 修改意见」交给大模型，让它输出一个修订后的完整提示词。
"""
from openai import OpenAI

from ..config import QWEN_BASE_URL, QWEN_API_KEY, COPY_MODEL, has_api_key, USE_MOCK

REVISE_PROMPT = """你是一个专业的营销海报提示词修订助手。

下面是一段用于文生图的提示词，用户对生成的图片不满意，提出了修改意见。
请根据修改意见，输出一段**修订后的完整提示词**（保留原有的结构：主体/场景/构图/风格/光影/色彩/文案位）。

原提示词：
{original}

用户修改意见：
{feedback}

要求：
1. 严格只输出修订后的提示词正文，不要解释、不要 markdown 代码块
2. 保留原提示词中未被修改的部分
3. 明确落实修改意见（例如"去掉某元素"要删除相关描述、"背景改成某色"要改色彩和场景）
4. 输出仍使用"主体：…，场景：…，构图：…，风格：…，光影：…，色彩：…，文案位：…"的结构
"""


def _mock_revise(original: str, feedback: str) -> str:
    # 无 key 时做简单替换兜底：直接把意见追加说明（不理想但保证链路不断）
    return f"{original}，【用户要求】{feedback}"


def revise_prompt(original: str, feedback: str) -> str:
    if USE_MOCK or not has_api_key():
        return _mock_revise(original, feedback)

    try:
        client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)
        prompt = REVISE_PROMPT.format(original=original, feedback=feedback)
        resp = client.chat.completions.create(
            model=COPY_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
        )
        text = resp.choices[0].message.content.strip()
        # 清洗可能的 markdown 代码块
        if text.startswith("```"):
            text = text.strip("`")
        return text
    except Exception:
        return _mock_revise(original, feedback)
