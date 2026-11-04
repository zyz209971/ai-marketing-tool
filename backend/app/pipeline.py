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
    # 0. 解析唯一产品事实；同名跨品牌或低置信度时返回 None，避免错误注入。
    product_context = rag.resolve_product_context(product_name)

    # 1. 反向解析参考海报（无参考图时用默认结构化模板）
    if poster_bytes or poster_url:
        parsed = vision.parse_poster(poster_bytes, poster_url)
    else:
        parsed = vision._mock_parse()

    # 2. 拼最终提示词（只替换主体）
    prompt = image.build_prompt(parsed, product_name, selling_points, price, product_context)

    # 3. 生图
    img = image.generate_image(prompt)

    # 4. 按平台分别检索，避免小红书/抖音/公众号共用同一组风格案例。
    references = {}
    try:
        query = f"产品：{product_name}；卖点：{selling_points}；价格：{price}；任务：新品营销文案"
        references = rag.search_for_platforms(query, copywriting.PLATFORMS.keys(), top_k=3)
    except Exception:
        references = {}

    # 5. 文案（带 RAG 参照）
    copies = copywriting.generate_copy(
        product_name,
        selling_points,
        price,
        references,
        product_context=product_context,
    )

    return {
        "parsed_prompt": parsed,
        "final_prompt": prompt,
        "image": img,
        "copywriting": copies,
        "references": references,
        "product_context": product_context,
    }
