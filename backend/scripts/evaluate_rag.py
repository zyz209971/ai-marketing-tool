"""RAG 离线回归评测：50 条真实标注用例 + 标准检索指标。"""
import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import rag  # noqa: E402

DEFAULT_DATASET = Path(__file__).resolve().parent.parent / "eval" / "rag_queries.jsonl"


def load_cases(path: Path) -> list[dict]:
    cases = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                case = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name}:{line_number} JSON 错误: {exc}") from exc
            if not case.get("id") or not case.get("query"):
                raise ValueError(f"{path.name}:{line_number} 缺少 id/query")
            cases.append(case)
    return cases


def retrieve(case: dict, top_k: int) -> list[dict]:
    if case.get("kind") == "product":
        return rag.search_products(case["query"], top_k=top_k)
    return rag.search_marketing(
        case["query"],
        top_k=top_k,
        platform=case.get("platform") or None,
    )


def evaluate_case(case: dict, top_k: int) -> dict:
    started = time.perf_counter()
    error = ""
    try:
        results = retrieve(case, top_k)
    except Exception as exc:
        results, error = [], f"{type(exc).__name__}: {exc}"
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    relevant = set(case.get("relevant_document_ids") or [])

    if not relevant:
        top_score = results[0].get("score", 0.0) if results else 0.0
        threshold = float(case.get("max_top_score", 0.35))
        passed = not error and top_score <= threshold
        return {
            "id": case["id"], "group": case.get("group", ""), "query": case["query"],
            "negative": True, "passed": passed, "top_score": top_score,
            "threshold": threshold, "latency_ms": latency_ms, "error": error,
            "top1": results[0].get("title") if results else None,
        }

    ranked_ids = [item.get("document_id") for item in results]
    first_rank = next((index + 1 for index, value in enumerate(ranked_ids) if value in relevant), None)
    hit1 = int(bool(ranked_ids and ranked_ids[0] in relevant))
    hit5_ids = set(ranked_ids[:5])
    recall5 = len(hit5_ids & relevant) / len(relevant)
    reciprocal_rank = 1 / first_rank if first_rank else 0.0

    combined_text = " ".join(
        " ".join(str(item.get(key, "")) for key in ("title", "product_name", "text"))
        for item in results[:5]
    )
    required_terms = case.get("required_terms") or []
    terms_ok = all(term.lower() in combined_text.lower() for term in required_terms)
    expected_platform = case.get("platform") or ""
    platform_ok = not expected_platform or bool(results and results[0].get("platform") == expected_platform)
    passed = not error and first_rank is not None and first_rank <= 5 and terms_ok and platform_ok

    return {
        "id": case["id"], "group": case.get("group", ""), "query": case["query"],
        "negative": False, "passed": passed, "hit1": hit1,
        "recall5": round(recall5, 4), "reciprocal_rank": round(reciprocal_rank, 4),
        "first_relevant_rank": first_rank, "terms_ok": terms_ok,
        "platform_ok": platform_ok, "latency_ms": latency_ms, "error": error,
        "top1": results[0].get("title") if results else None,
        "top1_id": results[0].get("document_id") if results else None,
        "top1_score": results[0].get("score") if results else None,
    }


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return round(ordered[index], 1)


def build_report(results: list[dict]) -> dict:
    positives = [item for item in results if not item["negative"]]
    negatives = [item for item in results if item["negative"]]
    platform_cases = [item for item in positives if item["id"].startswith("xiaohongshu_")]
    groups = defaultdict(list)
    for item in results:
        groups[item["group"]].append(item)

    metrics = {
        "cases": len(results),
        "passed": sum(item["passed"] for item in results),
        "pass_rate": round(sum(item["passed"] for item in results) / max(len(results), 1), 4),
        "hit_at_1": round(sum(item["hit1"] for item in positives) / max(len(positives), 1), 4),
        "recall_at_5": round(sum(item["recall5"] for item in positives) / max(len(positives), 1), 4),
        "mrr_at_10": round(sum(item["reciprocal_rank"] for item in positives) / max(len(positives), 1), 4),
        "platform_accuracy": round(sum(item["platform_ok"] for item in platform_cases) / max(len(platform_cases), 1), 4),
        "negative_rejection_rate": round(sum(item["passed"] for item in negatives) / max(len(negatives), 1), 4),
        "latency_ms_p50": round(statistics.median(item["latency_ms"] for item in results), 1),
        "latency_ms_p95": percentile([item["latency_ms"] for item in results], 0.95),
    }
    group_summary = {
        name: {
            "cases": len(items),
            "passed": sum(item["passed"] for item in items),
            "pass_rate": round(sum(item["passed"] for item in items) / len(items), 4),
        }
        for name, items in groups.items()
    }
    thresholds = {
        "hit_at_1": 0.80,
        "recall_at_5": 0.90,
        "mrr_at_10": 0.80,
        "platform_accuracy": 0.95,
        "negative_rejection_rate": 0.75,
    }
    threshold_passed = all(metrics[name] >= value for name, value in thresholds.items())
    return {
        "metrics": metrics,
        "thresholds": thresholds,
        "threshold_passed": threshold_passed,
        "groups": group_summary,
        "failed_cases": [item for item in results if not item["passed"]],
        "index": rag.index_stats(),
        "details": results,
    }


def main():
    parser = argparse.ArgumentParser(description="运行 RAG 标注集评测")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--output", default="")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    cases = load_cases(Path(args.dataset))
    if args.limit:
        cases = cases[:args.limit]
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        results = list(pool.map(lambda case: evaluate_case(case, args.top_k), cases))
    report = build_report(results)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    raise SystemExit(0 if report["threshold_passed"] else 1)


if __name__ == "__main__":
    main()
