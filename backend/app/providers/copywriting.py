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

COPY_PROMPT = """你是资深的电商营销文案专家，服务过多个头部饮品品牌。请为下面这款产品写 {platform} 平台的营销文案。

产品信息：
- 名称：{name}
- 卖点：{points}
- 价格：{price}
{product_facts}

平台风格要求：{style}
{reference}

【写作硬性要求】
1. 必须紧扣上面「卖点」里的具体事实来写，卖点里有的数字、规格、成分，要自然融进文案；卖点里没有的功效，一律不得编造。
2. 禁止使用空话套话和烂大街的口水词，包括但不限于：「绝绝子」「谁懂啊」「太绝了」「好喝到哭」「姐妹们冲」「YYDS」「狠狠」「拿捏」这类词一个都不许出现。
3. 文案要有「钩子」：第一句就要抓住人，可以是具体数字、反差对比、真实场景或一个痛点。
4. 有价格就自然带出价格，并把「划算」说具体（便宜多少、相当于每天多少、对比什么）。
5. 结尾要有明确的行动号召，让人想点、想买、想进店。
6. 语气口语化但不油腻，像真人推荐，不像广告机器人。

【输出格式】输出 3 条不同角度的候选文案，每条之间单独用一行「---」分隔，每条 120~200 字、自成一段完整文案。三条分别从「真实口感/品质」「性价比/价格」「场景/情绪」三个角度切入，但正文里不要出现「口感」「性价比」「场景」这些说明词，直接写文案本身。不要输出任何解释、编号或标签前缀。

第一条（真实口感/品质角度）：
第二条（性价比/价格角度）：
第三条（场景/情绪角度）：
"""


def _split_candidates(text: str) -> list[str]:
    """把模型输出的「候选1/候选2/候选3」文本解析成候选列表。

    兼容多种分隔形式：`---` 分隔、`候选N：` 前缀、纯换行分隔。清洗掉空串和残留标签。
    """
    import re as _re
    if not text:
        return []
    # 先按「候选N」或「方案N」切分（冒号可能紧跟在数字后）。
    parts = _re.split(r'\n\s*候选\s*[1-9一二三四五六七八九]\s*[：:]?', text)
    if len(parts) > 1:
        candidates = parts
    else:
        # 退化为按 --- 或空行切分。
        candidates = [p for p in _re.split(r'\n\s*---+\s*\n|\n\s*\n', text)]
    cleaned = []
    for c in candidates:
        # 按行过滤：整行是角度标签（含「角度切入」「角度」等说明词）的行直接丢弃。
        kept_lines = []
        for line in c.split('\n'):
            if _re.search(r'角度\s*切入|真实口感|性价比|场景|情绪', line) and len(line.strip()) < 40:
                continue
            kept_lines.append(line)
        c = '\n'.join(kept_lines)
        # 去掉段首残留的冒号、以及「候选N」标签、数字序号。
        c = _re.sub(r'^(候选\s*[1-9一二三四五六七八九]\s*[：:]\s*)?', '', c.strip())
        c = _re.sub(r'^[0-9]+[.、）)]\s*', '', c)
        c = c.strip().lstrip('：:').strip()
        if c and c not in ('---',):
            cleaned.append(c)
    return cleaned[:3] if cleaned else ([text.strip()] if text.strip() else [])


def _mock_copy(name: str, points: str, price: str) -> dict:
    """mock 兜底：每个平台给 3 条候选（结构同真实返回，保证前端一致）。"""
    out = {}
    for platform, style in PLATFORMS.items():
        price_str = f"，现在只要 {price}" if price else ""
        tag = " #种草 #好物推荐" if platform == "小红书" else " #热门 #必买"
        candidates = [
            f"{name}｜{points}{price_str}，入口顺滑、回甘清爽，来一杯试试～{tag}",
            f"一杯{name}，{points}，性价比拉满，通勤路上解馋又解渴{tag}",
            f"下午三点有点困？来杯{name}提提神，{points}，值得回购{tag}",
        ]
        out[platform] = candidates
    return out


def generate_copy(name: str, points: str, price: str, references=None, product_context: dict | None = None) -> dict:
    """生成多平台文案；每个平台返回 3 条候选（list[str]）。

    references 可按平台分别提供结构化检索结果。
    """
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
                temperature=0.9,
            )
            text = resp.choices[0].message.content.strip()
            return platform, _split_candidates(text)

        # 三个平台文案并行生成，显著缩短等待时间
        out = {}
        with ThreadPoolExecutor(max_workers=3) as pool:
            for platform, candidates in pool.map(_gen, PLATFORMS.keys()):
                out[platform] = candidates
        return out
    except Exception:
        return _mock_copy(name, points, price)
