"""从 CSV 导入产品知识库（覆盖式导入）。

用法：
    python scripts/import_csv.py <产品知识库.csv>

CSV 需包含表头：品牌,产品名,卖点,价格,分类
（与「产品知识库.csv」导出的格式一致；用 Excel/WPS 编辑后另存为 CSV 即可回导）

导入为「全量覆盖」：会清空现有产品表后重新写入 CSV 里的全部数据。
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402
import sqlite3  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print("用法: python import_csv.py <产品知识库.csv>")
        sys.exit(1)

    csv_path = Path(sys.argv[1])
    if not csv_path.exists():
        print(f"文件不存在: {csv_path}")
        sys.exit(1)

    rows = []
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            brand = (r.get("品牌") or "").strip()
            name = (r.get("产品名") or "").strip()
            points = (r.get("卖点") or "").strip()
            price = (r.get("价格") or "").strip()
            category = (r.get("分类") or "").strip()
            if not name:
                continue
            rows.append((brand, name, points, price, category))

    if not rows:
        print("CSV 里没有有效数据")
        sys.exit(1)

    # 全量覆盖导入
    db.init_db()
    conn = sqlite3.connect(db.DB_PATH)
    conn.execute("DELETE FROM products")
    conn.commit()
    conn.close()

    for brand, name, points, price, category in rows:
        db.upsert_product(name=name, brand=brand, selling_points=points, price=price, category=category)

    print(f"✅ 已覆盖导入 {len(rows)} 条产品 → {db.DB_PATH}")


if __name__ == "__main__":
    main()
