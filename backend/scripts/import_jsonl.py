"""从 RAG 知识库导出的 JSONL 数据中，抽取「产品名 + 价格 + 品牌」灌入 SQLite 产品库。

用法：
    python scripts/import_jsonl.py <products.jsonl 路径> [marketing.jsonl 路径]

抽取策略（保证数据干净）：
- 只处理「菜单页 / 单品页」两类记录（title 含"菜单"或"热量·价格"），
  丢弃"品牌大全/对比/排行/起源介绍"等干扰页。
- 用严格正则 `产品名 [评分] 本品牌 ¥价格` 抽取，品牌名必须精确匹配本品牌别名，
  从而排除"同类产品对比"里混入的其他品牌。
- 按 (品牌, 产品名) 去重。
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402


# 品牌 -> 可能的别名（content 里出现的形式）
BRAND_ALIASES = {
    "霸王茶姬": ["霸王茶姬"],
    "星巴克": ["星巴克"],
    "瑞幸": ["瑞幸", "瑞幸咖啡", "luckin coffee", "luckin"],
    "库迪": ["库迪", "库迪咖啡", "COTTI", "Cotti Coffee"],
    "喜茶": ["喜茶", "HEYTEA"],
    "奈雪的茶": ["奈雪的茶", "奈雪", "NAYUKI"],
    "沪上阿姨": ["沪上阿姨"],
}

# 评分残留（前导 ".8"、".9"、结尾 ".8" 等）
LEAD_SCORE_RE = re.compile(r"^\s*\.\d+\s+")
TAIL_SCORE_RE = re.compile(r"[\s\.]+\d\.\d+\s*$")
# 容量/热量前缀（"355-592ml"、"500-650ml"、"1,000ml"、"240 kcal"、"122 kcal" 等）
MEASURE_RE = re.compile(
    r"^\s*[\d\.,]+\s*[-–~]?\s*[\d\.,]*\s*(?:ml|kcal|L)\s*"
)
# 纯热量/容量残留前缀（更宽：任意"数字...kcal/ml/L"开头，含范围"0-134 kcal"）
MEASURE_BROAD_RE = re.compile(r"^\s*[\d\.,\-\~–]+\s*(?:kcal|ml|L)\s*")
# 标签词
NOISE_TOKENS = ["新品", "门店限定", "区域限定", "地域限定", "原创", "首创", "店舗限定", "NEW", "B"]


def clean_name(raw: str, brand: str) -> str | None:
    name = raw.strip()
    if not name:
        return None

    # 去掉品牌别名
    for alias in BRAND_ALIASES.get(brand, [brand]):
        name = re.sub(re.escape(alias), "", name)

    # 去容量/热量前缀
    name = MEASURE_RE.sub("", name).strip()
    name = MEASURE_BROAD_RE.sub("", name).strip()
    # 去前导评分 ".8"、".9"
    name = LEAD_SCORE_RE.sub("", name).strip()
    # 去结尾评分 " 4.8"
    name = TAIL_SCORE_RE.sub("", name).strip()
    # 去结尾的 kcal/热量 残留（如"拿铁 150 kcal"）
    name = re.sub(r"\s+[\d\.,\-–~]+\s*(?:kcal|ml|L)\s*$", "", name).strip()

    # 兜底：循环剥离开头残留的「数字+单位」段（如 "122 kcal 丝绒拿铁" → "丝绒拿铁"）
    prev = None
    while prev != name:
        prev = name
        name = re.sub(r"^\s*[\d\.,\-–~]+\s*(?:kcal|ml|L|折|倍)\s*", "", name).strip()
        name = re.sub(r"^\s*\d+\s*", "", name).strip()  # 纯数字开头（如 "15 金桂拿铁"、"18 咖啡饮品菜单"）
        name = re.sub(r"^\s*(?:咖啡饮品菜单|奶茶饮品菜单|饮品菜单)\s*", "", name).strip()
    name = name.strip()

    # 去掉开头/结尾标签
    for tok in NOISE_TOKENS:
        name = re.sub(r"^\s*" + re.escape(tok) + r"\s+", "", name, flags=re.IGNORECASE)
        name = re.sub(r"\s+" + re.escape(tok) + r"\s*$", "", name, flags=re.IGNORECASE)
    name = name.strip()

    # 去掉残留符号、多余空格
    name = name.replace("¥", "").replace("￥", "").strip()
    name = re.sub(r"\s+", " ", name).strip()
    name = name.strip("·.- ")

    if len(name) < 2 or len(name) > 20:
        return None
    if not any("\u4e00" <= c <= "\u9fff" for c in name):
        return None
    return name


def extract_products(content: str, brand: str) -> list[tuple[str, str]]:
    """从菜单页/单品页 content 抽取 (产品名, 价格)，要求品牌名紧邻。"""
    items = []
    aliases = BRAND_ALIASES.get(brand, [brand])
    for alias in aliases:
        # 产品名（不含空格）+ 可选评分 + 品牌别名 + ¥价格
        # 用 \S+ 限定产品名不含空格，避免把上一个产品的"122 kcal"尾巴带进来
        pat = re.compile(
            r"([^\s¥￥]{2,30}?)\s*(?:\d\.\d+\s*)?" + re.escape(alias) + r"\s*[¥￥](\d+)"
        )
        for m in pat.finditer(content):
            name = clean_name(m.group(1), brand)
            if name:
                items.append((name, m.group(2)))
    return items


def is_chinese_text(s: str) -> bool:
    return any("\u4e00" <= c <= "\u9fff" for c in s)


def main():
    if len(sys.argv) < 2:
        print("用法: python import_jsonl.py <products.jsonl> [marketing.jsonl]")
        sys.exit(1)

    products_path = Path(sys.argv[1])
    if not products_path.exists():
        print(f"文件不存在: {products_path}")
        sys.exit(1)

    products = {}  # (brand, name) -> price

    with open(products_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            title = d.get("title", "")
            brand = d.get("brand", "")
            content = d.get("content", "")

            # 只处理中文菜单页/单品页
            if not is_chinese_text(title):
                continue
            if "選單" in title or "選單" in content:
                continue  # 繁体
            if "¥" not in content and "￥" not in content:
                continue

            # 关键：只保留「菜单」或「单品（热量·价格）」两类页
            is_menu = "菜单" in title or "新品上市" in title or "下架" in title
            is_single = "热量" in title and "价格" in title
            if not (is_menu or is_single):
                continue

            for name, price in extract_products(content, brand):
                key = (brand, name)
                if key not in products:
                    products[key] = price

    db.init_db()
    inserted = 0
    for (brand, name), price in products.items():
        db.upsert_product(
            name=name,
            brand=brand,
            selling_points=f"{brand}在售产品",
            price=f"{price}元",
            category="饮品",
        )
        inserted += 1

    print(f"✅ 抽取产品 {len(products)} 款，已导入 SQLite 知识库")
    print(f"   数据库路径: {db.DB_PATH}")

    from collections import Counter
    bc = Counter(b for (b, _) in products.keys())
    for b, c in bc.most_common():
        print(f"   - {b}: {c} 款")


if __name__ == "__main__":
    main()
