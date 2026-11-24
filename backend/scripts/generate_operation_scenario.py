"""Generate a deterministic, approved-campaign feedback CSV."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import operations  # noqa: E402
from app.operations import SimulationRequest  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("campaign_id")
    parser.add_argument("--scenario", choices=("stable", "declining_sales", "high_cost", "underperforming"), required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--actual-qty", type=int)
    parser.add_argument("--promotion-pairs", type=int)
    parser.add_argument("--marketing-spend-minor", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = operations.simulate(args.campaign_id, SimulationRequest(
        scenario=args.scenario, seed=args.seed, actual_qty=args.actual_qty,
        promotion_pairs=args.promotion_pairs, marketing_spend_minor=args.marketing_spend_minor))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(operations.simulation_csv(result["simulation_run_id"]), encoding="utf-8-sig")
    args.output.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"csv": str(args.output), "metadata": str(args.output.with_suffix('.json')),
                      "simulation_run_id": result["simulation_run_id"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
