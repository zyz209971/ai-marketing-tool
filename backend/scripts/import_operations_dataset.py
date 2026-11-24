"""Import the team synthetic catalog, costs, history and campaign feedback.

The brand must already exist. Every file goes through the same preview/confirm
functions as the HTTP API, so rerunning this command is idempotent.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import operations  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--brand-id", required=True)
    parser.add_argument("--source", default="brandpilot-luckin-operations-synthetic-v2")
    args = parser.parse_args()
    files = [("products", args.dataset/"products.csv"), ("costs", args.dataset/"costs.csv"),
             ("orders", args.dataset/"orders.csv"), ("orders", args.dataset/"campaign_feedback"/"orders.csv")]
    results = []
    for data_type, path in files:
        if not path.exists():
            raise SystemExit(f"missing: {path}")
        preview = operations.preview_import(path.read_bytes(), args.brand_id, path.name, args.source, True, data_type)
        confirmed = operations.confirm_import(preview["import_id"])
        results.append({"file": str(path), "preview": {k: preview[k] for k in ("valid_count", "error_count", "reused")},
                        "confirmed": confirmed})
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
