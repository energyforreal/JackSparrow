"""
Model promotion validation gate.

Checks:
  1) Walk-forward metadata: walkforward_mean.sharpe >= threshold
  2) Paper-trade soak: realized net PnL, trade frequency, and drawdown thresholds

The script expects paper_trade_logger output lines in:
  logs/paper_trades/paper_trades.log
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, Dict, List

from agent.core.validation_gates import (
    compute_paper_soak_metrics,
    load_metadata_json,
    parse_paper_trade_log,
    validate_paper_soak,
    validate_walkforward_metadata,
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_paper_log() -> Path:
    return _project_root() / "logs" / "paper_trades" / "paper_trades.log"


def _default_model_dir() -> Path:
    # MODEL_DIR is usually set in .env
    env = os.environ.get("MODEL_DIR")
    if env:
        return Path(env)
    # fallback to repository default
    return _project_root() / "agent" / "model_storage"


def validate_model_dir(model_dir: Path, *, min_sharpe: float) -> List[str]:
    if not model_dir.exists():
        return [f"MODEL_DIR does not exist: {model_dir}"]

    metadata_files = sorted(model_dir.glob("metadata_BTCUSD_*.json"))
    if not metadata_files:
        return [f"No metadata_BTCUSD_*.json found in {model_dir}"]

    failures: List[str] = []
    for meta_path in metadata_files:
        metadata = load_metadata_json(meta_path)
        passed, reasons = validate_walkforward_metadata(metadata, min_sharpe=min_sharpe)
        if not passed:
            failures.append(f"{meta_path.name}: {', '.join(reasons)}")

    return failures


def validate_paper_log(paper_log: Path, *, thresholds: Dict[str, Any]) -> List[str]:
    if not paper_log.exists():
        return [f"Paper trade log not found: {paper_log}"]

    closes = parse_paper_trade_log(paper_log)
    metrics = compute_paper_soak_metrics(closes)
    passed, reasons = validate_paper_soak(metrics, **thresholds)

    if passed:
        return []

    # Include computed metrics for operator visibility.
    return [f"paper_soak_failed: {', '.join(reasons)}; metrics={metrics}"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", type=str, default=str(_default_model_dir()))
    ap.add_argument("--paper-log", type=str, default=str(_default_paper_log()))

    ap.add_argument("--min-sharpe", type=float, default=0.0)

    ap.add_argument("--min-total-trades", type=int, default=10)
    ap.add_argument("--min-trades-per-hour", type=float, default=1.0)
    ap.add_argument("--min-net-pnl", type=float, default=0.0)
    ap.add_argument("--max-drawdown-frac", type=float, default=0.25)

    args = ap.parse_args()

    model_dir = Path(args.model_dir)
    paper_log = Path(args.paper_log)

    failures: List[str] = []

    failures.extend(validate_model_dir(model_dir, min_sharpe=args.min_sharpe))

    paper_thresholds = {
        "min_total_trades": args.min_total_trades,
        "min_trades_per_hour": args.min_trades_per_hour,
        "min_net_pnl": args.min_net_pnl,
        "max_drawdown_frac": args.max_drawdown_frac,
    }
    failures.extend(validate_paper_log(paper_log, thresholds=paper_thresholds))

    if failures:
        print("❌ Model promotion validation FAILED")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("✅ Model promotion validation PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

