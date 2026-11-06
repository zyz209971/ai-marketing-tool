"""生图：使用独立的图片 API 根据结构化提示词生成产品海报。"""
import base64

from openai import OpenAI

from ..config import (
    IMAGE_API_KEY,
    IMAGE_BASE_URL,
    IMAGE_MODEL,
    USE_IMAGE_MOCK,
)


def _clean_text_zone(text_zone: str) -> str:
    """把「左上角留白区域」这类描述清洗成「左上角」，用于拼排版位置。"""
    position = (text_zone or "").strip()
    for label in ("文案位：", "文案位:"):
        if position.startswith(label):
            position = position[len(label):]
            break
    for token in ("留白区域", "留白", "区域"):
        position = position.replace(token, "")
    position = position.strip()
    return position or "画面顶部"


def build_text_instruction(display_name: str, selling_points: str, price: str, text_zone: str) -> str:
    """显式给出要渲染的文字内容、位置，并负向禁止其它文字。"""
    position = _clean_text_zone(text_zone)
    segments = [f"文案位：在{position}排版文案", f"标题「{display_name}」"]
    if selling_points:
        segments.append(f"卖点「{selling_points}」")
    if price:
        segments.append(f"价格「{price}」")
    segments.append("其余区域禁止出现任何文字、标签、图标、logo、数字")
    return "，".join(segments)


def build_prompt(
    parsed: dict,
    product_name: str,
    selling_points: str,
    price: str,
    product_context: dict | None = None,
) -> str:
    """把结构化提示词 + 产品信息拼成最终文生图提示词（只替换主体，其余复用）。"""
    verified_name = (product_context or {}).get("product_name") or product_name
    brand = (product_context or {}).get("brand", "")
    category = (product_context or {}).get("category", "")
    display_name = f"{brand} {verified_name}".strip()
    subject = f"主体：{display_name}，{selling_points}"
    if category and category not in selling_points:
        subject += f"，产品类别为{category}"
    if price:
        subject += f"，售价 {price}"
    text_instruction = build_text_instruction(display_name, selling_points, price, parsed.get("text_zone", ""))
    parts = {
        "subject": subject,
        "scene": parsed.get("scene", "场景：简洁背景"),
        "composition": parsed.get("composition", "构图：居中"),
        "style": parsed.get("style", "风格：现代简约"),
        "lighting": parsed.get("lighting", "光影：柔光"),
        "color": parsed.get("color", "色彩：暖色系"),
        "text_zone": text_instruction,
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
    return {"format": "svg+xml", "base64": b64, "prompt": prompt, "mock": True}


def generate_image(prompt: str, size: str = "1024x1024") -> dict:
    if USE_IMAGE_MOCK:
        return _mock_image(prompt)

    try:
        client = OpenAI(api_key=IMAGE_API_KEY, base_url=IMAGE_BASE_URL)
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
        m = _mock_image(prompt)
        m["error"] = "生图接口没有返回图片 URL 或 Base64 数据"
        return m
    except Exception as e:
        # 生图失败，返回带错误信息的 mock，便于排查
        m = _mock_image(prompt)
        m["error"] = f"{type(e).__name__}: {e}"
        return m
