"""文案生成：联网搜索爆款文案 → 大模型改写。

- 有 key：调用大模型（OpenAI 兼容接口）生成多平台文案
- 无 key：返回 mock 文案，保证链路可跑通

说明：真正的"联网搜索爆款文案"需要额外接入搜索 API，当前先实现
"给定产品信息 → 生成多平台营销文案"的主干，搜索源二期接入。
"""
from concurrent.futures import ThreadPoolExecutor

from openai import OpenAI

from ..config import QWEN_BASE_URL, QWEN_API_KEY, COPY_MODEL, has_api_key, USE_MOCK

PLATFORMS = {
    "小红书": "口语化、带 emoji、突出种草感、加话题标签、多用感叹和对比",
    "抖音": "短句、节奏快、有钩子开头、带行动号召、口语化、加热门话题",
    "公众号": "标题党但克制、正文有层次、讲故事感、适当留悬念",
}

COPY_PROMPT = """你是资深电商营销文案专家。请为下面这款产品，分别写 {platform} 风格的营销文案。

产品信息：
- 名称：{name}
- 卖点：{points}
- 价格：{price}
{product_facts}

平台风格要求：{style}
{reference}

要求：
1. 直接输出文案正文，不要解释、不要标题前缀
2. 200 字以内
3. 符合该平台调性
"""


def _mock_copy(name: str, points: str, price: str) -> dict:
    out = {}
    for platform, style in PLATFORMS.items():
        out[platform] = (
            f"【{name}】{points}！"
            + (f" 现在只要 {price}，" if price else "")
            + " 好喝到停不下来，赶紧来一杯试试～"
            + (" #种草 #好物推荐" if platform == "小红书" else " #热门 #必买")
        )
    return out


def generate_copy(name: str, points: str, price: str, references=None, product_context: dict | None = None) -> dict:
    """生成多平台文案；references 可按平台分别提供结构化检索结果。"""
    if USE_MOCK or not has_api_key():
        return _mock_copy(name, points, price)

    try:
        client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)

        def _gen(platform):
            style = PLATFORMS[platform]
            product_facts = ""
            if product_context:
                product_facts = (
                    "\n核验产品资料（仅使用明确出现的事实；若价格冲突，以用户本次填写的活动价格为准）：\n"
                    + product_context.get("text", "")[:700]
                )
            platform_refs = references.get(platform, []) if isinstance(references, dict) else (references or [])
            ref_block = ""
            if platform_refs:
                rendered = []
                for index, ref in enumerate(platform_refs[:3], 1):
                    if isinstance(ref, dict):
                        metadata = " / ".join(
                            value for value in (
                                ref.get("platform", ""), ref.get("brand", ""), ref.get("title", "")
                            ) if value
                        )
                        source_note = "风格案例" if ref.get("platform") == platform else "行业事实案例"
                        rendered.append(
                            f"参照{index}（{source_note}{'；' + metadata if metadata else ''}）：\n"
                            f"{ref.get('text', '')[:500]}"
                        )
                    else:
                        rendered.append(f"参照{index}：\n{str(ref)[:500]}")
                ref_block = (
                    "\n以下内容仅作为事实、结构和表达风格参考。不得照抄，不得虚构案例中的销量或功效：\n"
                    + "\n\n".join(rendered)
                )
            prompt = COPY_PROMPT.format(
                platform=platform,
                name=name,
                points=points,
                price=price,
                style=style,
                reference=ref_block,
                product_facts=product_facts,
            )
            resp = client.chat.completions.create(
                model=COPY_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.8,
            )
            return platform, resp.choices[0].message.content.strip()

        # 三个平台文案并行生成，显著缩短等待时间
        out = {}
        with ThreadPoolExecutor(max_workers=3) as pool:
            for platform, text in pool.map(_gen, PLATFORMS.keys()):
                out[platform] = text
        return out
    except Exception:
        return _mock_copy(name, points, price)
