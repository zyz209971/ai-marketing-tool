"""RAG 营销知识库更新脚本（面向团队同学，简化入口）。

把营销案例放进 `marketing/` 文件夹，一条命令重新 embedding 入库。

支持的文件格式（放一起也可以）：
  1. *.txt        纯文本，整个文件算一篇案例
  2. *.json        结构化案例，可选字段：brand / title / content
  3. *.jsonl       与之前 marketing.jsonl 同格式（含 brand/title/chunks）

用法（在 backend 目录下）：
    python scripts/update_marketing.py
    python scripts/update_marketing.py marketing/    # 指定案例文件夹
    python scripts/update_marketing.py --append       # 增量追加（不清空旧数据）

默认行为是「全量重建」：先清空向量库，再把 marketing/ 里的全部案例重新入库。
想只加新案例、保留旧的，加 --append 即可。
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import rag  # noqa: E402

DEFAULT_DIR = Path(__file__).resolve().parent.parent.parent / "marketing"


def load_cases(folder: Path) -> list[dict]:
    """把文件夹里的 txt/json/jsonl 统一解析成案例列表 [{brand,title,content}]。"""
    cases = []
    for f in sorted(folder.iterdir()):
        if not f.is_file():
            continue
        try:
            if f.suffix.lower() == ".txt":
                cases.append({"brand": "", "title": f.stem, "content": f.read_text(encoding="utf-8")})
            elif f.suffix.lower() == ".json":
                d = json.loads(f.read_text(encoding="utf-8"))
                # 兼容单个对象或对象列表
                items = d if isinstance(d, list) else [d]
                for it in items:
                    cases.append({
                        "brand": it.get("brand", ""),
                        "title": it.get("title", f.stem),
                        "content": it.get("content", it.get("text", "")),
                    })
            elif f.suffix.lower() == ".jsonl":
                for line in f.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    d = json.loads(line)
                    cases.append({
                        "brand": d.get("brand", ""),
                        "title": d.get("title", f.stem),
                        "content": d.get("content", ""),
                        "_chunks": d.get("chunks", []),
                    })
        except Exception as e:
            print(f"  ⚠️ 跳过无法解析的文件 {f.name}: {e}")
    return cases


def main():
    parser = argparse.ArgumentParser(description="RAG 营销知识库更新")
    parser.add_argument("folder", nargs="?", default=str(DEFAULT_DIR), help="案例文件夹路径")
    parser.add_argument("--append", action="store_true", help="增量追加，不清空旧数据")
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.exists():
        print(f"案例文件夹不存在: {folder}")
        print("请创建该文件夹，并把营销案例 txt/json/jsonl 放进去。")
        sys.exit(1)

    cases = load_cases(folder)
    if not cases:
        print("没找到任何有效案例文件（支持 .txt / .json / .jsonl）。")
        sys.exit(1)

    print(f"读取到 {len(cases)} 篇案例，开始 embedding…")

    # 组装成 rag.ingest_marketing 需要的 jsonl 临时文件
    tmp = folder / "_cases_tmp.jsonl"
    with open(tmp, "w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    if not args.append:
        # 全量重建：ingest_marketing 内部会先清空
        pass

    def progress(i, n):
        if i % 10 == 0 or i == n:
            print(f"  进度 {i}/{n}")

    total = rag.ingest_marketing(str(tmp), progress, append=args.append)
    tmp.unlink(missing_ok=True)

    mode = "增量追加" if args.append else "全量重建"
    print(f"✅ 完成（{mode}），共 {total} 个 chunk 入库")
    print(f"   向量库路径: {rag.DB_PATH}")


if __name__ == "__main__":
    main()
