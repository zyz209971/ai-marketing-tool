"""生图：根据结构化提示词生成产品海报。

- 有 QWEN_API_KEY：通过 OpenAI 兼容接口调用通义万相(qwen-image-3.0-pro)
- 无 key：返回 mock 结果（占位图 base64）
"""
import base64
import os

from openai import OpenAI

from ..config import QWEN_BASE_URL, QWEN_API_KEY, IMAGE_MODEL, has_api_key, USE_MOCK


def build_prompt(parsed: dict, product_name: str, selling_points: str, price: str) -> str:
    """把结构化提示词 + 产品信息拼成最终文生图提示词（只替换主体，其余复用）。"""
    subject = f"主体：{product_name}，{selling_points}"
    if price:
        subject += f"，售价 {price}"
    parts = {
        "subject": subject,
        "scene": parsed.get("scene", "场景：简洁背景"),
        "composition": parsed.get("composition", "构图：居中"),
        "style": parsed.get("style", "风格：现代简约"),
        "lighting": parsed.get("lighting", "光影：柔光"),
        "color": parsed.get("color", "色彩：暖色系"),
        "text_zone": parsed.get("text_zone", "文案位：预留留白"),
    }
    labels = {
        "subject": "主体",
        "scene": "场景",
        "composition": "构图",
        "style": "风格",
        "lighting": "光影",
        "color": "色彩",
        "text_zone": "文案位",
    }
    segments = []
    for k, v in parts.items():
        label = labels[k]
        if v.startswith(label):
            segments.append(v)
        else:
            segments.append(f"{label}：{v}")
    return "，".join(segments)


def _mock_image(prompt: str) -> dict:
    # 生成一个简单占位 SVG 转 base64，方便前端预览
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="768" height="1024">
  <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#fdf6ec"/><stop offset="1" stop-color="#f3e2c7"/>
  </linearGradient></defs>
  <rect width="768" height="1024" fill="url(#g)"/>
  <text x="40" y="80" font-family="sans-serif" font-size="28" fill="#8a6d3b">营销海报 · Mock 占位</text>
  <text x="40" y="500" font-family="sans-serif" font-size="24" fill="#5a4a2a">提示词已生成，配置 API Key 后出真实图片</text>
</svg>"""
    b64 = base64.b64encode(svg.encode()).decode()
    return {"format": "svg", "base64": b64, "prompt": prompt, "mock": True}


def generate_image(prompt: str, size: str = "1024x1024") -> dict:
    if USE_MOCK or not has_api_key():
        return _mock_image(prompt)

    try:
        client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)
        resp = client.images.generate(
            model=IMAGE_MODEL,
            prompt=prompt,
            size=size,
            n=1,
        )
        data = resp.data[0]
        # OpenAI 兼容接口可能返回 url 或 b64_json
        if getattr(data, "url", None):
            return {"format": "url", "url": data.url, "prompt": prompt, "mock": False}
        if getattr(data, "b64_json", None):
            return {"format": "png", "base64": data.b64_json, "prompt": prompt, "mock": False}
        return _mock_image(prompt)
    except Exception as e:
        # 生图失败，返回带错误信息的 mock，便于排查
        m = _mock_image(prompt)
        m["error"] = str(e)
        return m
