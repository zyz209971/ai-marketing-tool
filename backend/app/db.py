"""SQLite 知识库：商家产品库。

存储商家产品信息（品牌 / 名称 / 卖点 / 价格 / 行业），支撑"输入产品名 → 自动补全"。
首次运行自动建表；仅 SEED_DEMO_DATA=true 时写入示例。真实资料由导入流程提供。
"""
import sqlite3
import os
from pathlib import Path
from .config import DATA_DIR

DB_PATH = DATA_DIR / "products.db"

# 预置示例商家产品（演示用，后续可替换成真实数据）
SEED_PRODUCTS = [
    ("招牌珍珠奶茶", "", "现煮珍珠、低糖健康、奶香浓郁", "15元", "奶茶"),
    ("杨枝甘露", "", "新鲜芒果、椰奶打底、料超足", "18元", "奶茶"),
    ("芝士葡萄", "", "现剥葡萄、咸香芝士奶盖", "19元", "奶茶"),
    ("柠檬绿茶", "", "鲜榨柠檬、清新解腻、零脂", "12元", "茶饮"),
    ("黑糖波波鲜奶", "", "手熬黑糖、Q弹波波、纯鲜奶", "16元", "奶茶"),
]


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """建表，并在显式启用开发示例时为新空库植入数据。"""
    conn = _connect()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand TEXT DEFAULT '',
            name TEXT NOT NULL,
            selling_points TEXT,
            price TEXT,
            category TEXT,
            UNIQUE(brand, name)
        )
        """
    )
    # 生产环境默认禁止自动植入示例。
    count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    if count == 0 and os.getenv('SEED_DEMO_DATA', '').lower() == 'true':
        conn.executemany(
            "INSERT INTO products (name, brand, selling_points, price, category) VALUES (?,?,?,?,?)",
            SEED_PRODUCTS,
        )
    conn.commit()
    conn.close()


def lookup_product(name: str) -> dict | None:
    """按产品名检索。先精确匹配，再模糊匹配。"""
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM products WHERE name = ?", (name.strip(),)
    ).fetchone()
    if not row:
        row = conn.execute(
            "SELECT * FROM products WHERE name LIKE ? LIMIT 1",
            (f"%{name.strip()}%",),
        ).fetchone()
    conn.close()
    if row:
        return {
            "brand": row["brand"],
            "name": row["name"],
            "selling_points": row["selling_points"],
            "price": row["price"],
            "category": row["category"],
        }
    return None


def search_products(keyword: str, limit: int = 5) -> list[dict]:
    """模糊搜索产品，用于输入联想候选列表。"""
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM products WHERE name LIKE ? LIMIT ?",
        (f"%{keyword.strip()}%", limit),
    ).fetchall()
    conn.close()
    return [
        {
            "brand": r["brand"],
            "name": r["name"],
            "selling_points": r["selling_points"],
            "price": r["price"],
            "category": r["category"],
        }
        for r in rows
    ]


def upsert_product(
    name: str, selling_points: str = "", price: str = "", category: str = "", brand: str = ""
):
    """新增或更新产品（生成后自动沉淀到知识库）。"""
    conn = _connect()
    conn.execute(
        """
        INSERT INTO products (name, brand, selling_points, price, category) VALUES (?,?,?,?,?)
        ON CONFLICT(brand, name) DO UPDATE SET
            selling_points=excluded.selling_points,
            price=excluded.price,
            category=excluded.category
        """,
        (name.strip(), brand, selling_points, price, category),
    )
    conn.commit()
    conn.close()


# 模块加载时初始化
init_db()
