"""Load one generated dashboard fixture into an existing brand."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from app import operations  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("case", type=Path)
    parser.add_argument("--brand-id", required=True)
    parser.add_argument("--dataset", type=Path,
                        default=REPO / "合成数据+人工答案+商品图片+csv+json")
    args = parser.parse_args()
    manifest = json.loads((args.case / "manifest.json").read_text(encoding="utf-8"))
    results = []
    for data_type in ("products", "costs", "orders"):
        path = args.case / "orders.csv" if data_type == "orders" else args.dataset / f"{data_type}.csv"
        if data_type == "orders" and not manifest["has_orders"]:
            results.append({"file": str(path), "skipped": True, "reason": "empty dashboard case"})
            continue
        preview = operations.preview_import(path.read_bytes(), args.brand_id, path.name,
                                            f"dashboard-fixture:{manifest['case_id']}", True, data_type)
        confirmed = operations.confirm_import(preview["import_id"])
        results.append({"file": str(path), "valid_count": preview["valid_count"],
                        "error_count": preview["error_count"], "confirmed": confirmed})
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
