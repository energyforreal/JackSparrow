#!/usr/bin/env python3
"""Gate 5 pass-rate diagnostic using exported metadata thresholds (no agent logs required).

Usage:
  python scripts/v43_gate5_metadata_diagnostic.py
  python scripts/v43_gate5_metadata_diagnostic.py --ratio 0.2
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agent.core.config import settings
from agent.core.v43_signal_gates import gate5_long_edge_metrics, gate5_short_edge_metrics


def _load_metadata() -> dict:
    meta_path = (
        _REPO
        / "agent"
        / "model_storage"
        / "JackSparrow_v43_models_BTCUSD"
        / "metadata_v43.json"
    )
    with meta_path.open(encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate 5 diagnostic from metadata thresholds")
    parser.add_argument(
        "--ratio",
        type=float,
        default=None,
        help="Override JACKSPARROW_V43_MIN_EDGE_COST_RATIO for this run",
    )
    args = parser.parse_args()
    if args.ratio is not None:
        settings.jacksparrow_v43_min_edge_cost_ratio = float(args.ratio)

    meta = _load_metadata()
    ratio = float(settings.jacksparrow_v43_min_edge_cost_ratio)
    rtc = 2.0 * (
        float(settings.jacksparrow_v43_maker_fee_rate)
        + float(settings.jacksparrow_v43_slippage_pct)
    )
    print(f"Gate 5 diagnostic (ratio={ratio}, round_trip={rtc:.6f})")
    print(f"primary_execution_horizon_bars={meta.get('primary_execution_horizon_bars')}")
    print()

  # Representative edges from validation prediction_std in metadata
    edge_samples = {
        "thin": 0.00015,
        "moderate": 0.00030,
        "strong": 0.00080,
    }

    horizons = meta.get("horizons") or {}
    for hkey, block in horizons.items():
        if not isinstance(block, dict):
            continue
        vm = block.get("validation_metrics") or {}
        dt = float(vm.get("dynamic_threshold") or block.get("dynamic_threshold") or 0.0)
        st = float(vm.get("short_threshold") or block.get("short_threshold") or dt)
        pred_std = float(vm.get("prediction_std") or 0.0)
        print(f"=== {hkey} (forward_bars={block.get('forward_bars')}) ===")
        print(f"  dynamic_threshold={dt:.6f}  short_threshold={st:.6f}  pred_std={pred_std:.6f}")
        print(f"  gate5_rhs (ratio*rtc)={ratio * rtc:.6f}")
        for label, edge in edge_samples.items():
            long_m = gate5_long_edge_metrics(dt + edge, dt)
            short_m = gate5_short_edge_metrics(-(dt + edge), dt)
            print(
                f"  {label:8s} edge={edge:.6f}  long_pass={long_m.passes}  "
                f"short_pass={short_m.passes}"
            )
        print()

    print("Run analyze_v43_gate_rejects.py on agent NDJSON logs for live reject counts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
