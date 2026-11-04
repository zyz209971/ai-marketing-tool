"""重建或增量更新产品与营销 RAG 索引。

默认读取 backend/data 下的三份标准数据；也可传入任意文件或文件夹。
支持 txt/json/jsonl，保留原始中文字段并由 app.rag 统一规范化。
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import rag  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"
DEFAULT_INPUTS = [DATA_DIR / "产品.jsonl", DATA_DIR / "推文.jsonl", DATA_DIR / "小红书推文.jsonl"]
MARKETING_DIR = BACKEND_DIR.parent / "marketing"


def _load_file(path: Path) -> list[dict]:
    records = []
    suffix = path.suffix.lower()
    if suffix == ".txt":
        records.append({
            "title": path.stem,
            "content": path.read_text(encoding="utf-8"),
            "_source_file": str(path),
        })
    elif suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict):
                item = dict(item)
                item["_source_file"] = str(path)
                records.append(item)
    elif suffix == ".jsonl":
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path.name}:{line_number} JSON 格式错误: {exc}") from exc
                if isinstance(item, dict):
                    item["_source_file"] = str(path)
                    records.append(item)
    return records


def load_records(inputs: list[Path]) -> tuple[list[dict], list[Path]]:
    files = []
    for item in inputs:
        if item.is_dir():
            files.extend(
                path for path in sorted(item.rglob("*"))
                if path.is_file() and path.suffix.lower() in {".txt", ".json", ".jsonl"}
                and not path.name.startswith("_")
            )
        elif item.is_file():
            files.append(item)
        else:
            print(f"[WARN] 跳过不存在的路径: {item}")

    records = []
    for path in files:
        try:
            loaded = _load_file(path)
            records.extend(loaded)
            print(f"  {path.name}: {len(loaded)} 条")
        except Exception as exc:
            print(f"[ERROR] 读取失败 {path}: {exc}")
            raise
    return records, files


def main():
    parser = argparse.ArgumentParser(description="重建产品与营销 RAG 混合索引")
    parser.add_argument("inputs", nargs="*", help="JSONL/JSON/TXT 文件或文件夹；不填则读取 backend/data 三份标准数据")
    parser.add_argument("--append", action="store_true", help="增量更新；同 document_id/chunk_id 自动覆盖，不产生重复")
    parser.add_argument("--include-marketing-dir", action="store_true", help="同时导入项目根目录 marketing/ 中的案例")
    args = parser.parse_args()

    inputs = [Path(value).resolve() for value in args.inputs] if args.inputs else list(DEFAULT_INPUTS)
    if args.include_marketing_dir and MARKETING_DIR.exists():
        inputs.append(MARKETING_DIR)

    print("读取数据源：")
    records, files = load_records(inputs)
    if not records:
        print("[ERROR] 没有读取到有效记录")
        sys.exit(1)
    print(f"共 {len(files)} 个文件、{len(records)} 条记录，开始构建索引……")

    def progress(i, n):
        if i % 100 == 0 or i == n:
            print(f"  规范化进度 {i}/{n}")

    stats = rag.ingest_records(records, progress=progress, append=args.append)
    index = rag.index_stats()
    mode = "增量更新" if args.append else "全量重建"
    print(f"[OK] {mode}完成")
    print(f"   输入记录: {stats['records']}")
    print(f"   写入 chunk: {stats['chunks']}")
    print(f"   重复/覆盖: {stats['duplicates']}")
    print(f"   Embedding 已启用: {stats['embedding_enabled']}")
    print(f"   向量化成功: {stats['embedded']}")
    print(f"   向量化失败: {stats['embedding_failed']}")
    print(f"   当前索引: {json.dumps(index, ensure_ascii=False)}")
    print(f"   数据库: {rag.DB_PATH}")
    if stats["chunks"] == 0:
        print("[ERROR] 没有任何 chunk 入库，请检查数据字段和日志")
        sys.exit(2)


if __name__ == "__main__":
    main()
