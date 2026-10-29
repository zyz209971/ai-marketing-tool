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


def generate_copy(name: str, points: str, price: str, references: list[str] | None = None) -> dict:
    """生成多平台文案。references 为 RAG 检索到的营销案例，作为爆款参照。"""
    if USE_MOCK or not has_api_key():
        return _mock_copy(name, points, price)

    ref_block = ""
    if references:
        # 每篇参照只取前 300 字精华，既保留爆款风格参照，又避免 prompt 过长拖慢生成
        ref_text = "\n\n".join(
            f"参照案例{i+1}：{r[:300]}" for i, r in enumerate(references)
        )
        ref_block = f"\n以下是可参考的同类爆款营销案例（用于风格与话术参照，请借鉴其表达但不要照抄）：\n{ref_text}"

    try:
        client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)

        def _gen(platform):
            style = PLATFORMS[platform]
            prompt = COPY_PROMPT.format(
                platform=platform,
                name=name,
                points=points,
                price=price,
                style=style,
                reference=ref_block,
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
