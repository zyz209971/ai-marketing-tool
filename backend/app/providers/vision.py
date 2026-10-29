"""反向解析：把参考海报解析成结构化提示词。

- 有 QWEN_API_KEY：通过 OpenAI 兼容接口调用通义千问-VL 多模态模型
- 无 key：返回 mock 结构化结果，保证链路可跑通
"""
import json
import base64
from typing import Optional

from openai import OpenAI

from ..config import QWEN_BASE_URL, QWEN_API_KEY, VISION_MODEL, has_api_key, USE_MOCK

PROMPT_TEMPLATE = """你是一个专业的海报设计分析助手。请分析这张商品海报图片，输出一个 JSON 对象（只输出 JSON，不要任何额外文字），字段如下：

{
  "subject": "主体：描述画面中最主要的商品是什么、长什么样",
  "scene": "场景：背景环境",
  "composition": "构图：视角、角度、主体位置",
  "style": "风格：整体视觉风格",
  "lighting": "光影：光线氛围",
  "color": "色彩：主色调与配色",
  "text_zone": "文案位：文案/标题通常放在画面的什么位置"
}

要求：
1. 严格只输出 JSON，不要 markdown 代码块
2. 每个字段用中文描述，简洁准确
3. 不要描述人物（如果画面有人物，忽略之，专注商品与场景）
"""


def _mock_parse() -> dict:
    return {
        "subject": "主体：一杯奶茶，透明杯身，奶盖+珍珠，插着吸管",
        "scene": "场景：奶茶店吧台，木质桌面",
        "composition": "构图：俯拍 45° 居中，产品占画面 60%",
        "style": "风格：ins 简约、清新",
        "lighting": "光影：柔光、高调、通透",
        "color": "色彩：奶油米白 + 奶咖色",
        "text_zone": "文案位：左上角留白区域",
    }


def parse_poster(image_bytes: Optional[bytes], image_url: Optional[str] = None) -> dict:
    """解析参考海报，返回结构化提示词 dict。"""
    if USE_MOCK or not has_api_key():
        return _mock_parse()

    try:
        client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)

        content = [{"type": "text", "text": PROMPT_TEMPLATE}]
        if image_url:
            content.append({"type": "image_url", "image_url": {"url": image_url}})
        elif image_bytes:
            b64 = base64.b64encode(image_bytes).decode()
            content.append(
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
            )

        resp = client.chat.completions.create(
            model=VISION_MODEL,
            messages=[{"role": "user", "content": content}],
            temperature=0.3,
        )
        text = resp.choices[0].message.content.strip()
        # 清洗可能的 markdown 代码块
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except Exception:
        # 解析失败回退 mock，保证链路不中断
        return _mock_parse()
