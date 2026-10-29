"""生成主链路编排：反向解析 → 提示词替换 → 生图 → 文案（RAG 增强）。"""
from .providers import vision, image, copywriting
from . import rag


def run_pipeline(
    product_name: str,
    selling_points: str,
    price: str,
    poster_bytes=None,
    poster_url=None,
) -> dict:
    # 1. 反向解析参考海报（无参考图时用默认结构化模板）
    if poster_bytes or poster_url:
        parsed = vision.parse_poster(poster_bytes, poster_url)
    else:
        parsed = vision._mock_parse()

    # 2. 拼最终提示词（只替换主体）
    prompt = image.build_prompt(parsed, product_name, selling_points, price)

    # 3. 生图
    img = image.generate_image(prompt)

    # 4. RAG 检索营销案例（作为文案参照）
    references = []
    try:
        hits = rag.search_marketing(f"{product_name} {selling_points}", top_k=3)
        references = [h["text"] for h in hits]
    except Exception:
        references = []

    # 5. 文案（带 RAG 参照）
    copies = copywriting.generate_copy(product_name, selling_points, price, references)

    return {
        "parsed_prompt": parsed,
        "final_prompt": prompt,
        "image": img,
        "copywriting": copies,
        "references": references,
    }
