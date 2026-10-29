"""把 marketing.jsonl 导入 RAG 向量库。

用法：
    python scripts/import_marketing.py <marketing.jsonl 路径>
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import rag  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print("用法: python import_marketing.py <marketing.jsonl>")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"文件不存在: {path}")
        sys.exit(1)

    def progress(i, n):
        if i % 20 == 0 or i == n:
            print(f"  进度 {i}/{n}")

    print("开始导入（需为每个 chunk 调 embedding，请稍候）…")
    total = rag.ingest_marketing(str(path), progress)
    print(f"✅ 完成，共 {total} 个 chunk 入库")
    print(f"   向量库路径: {rag.DB_PATH}")


if __name__ == "__main__":
    main()
