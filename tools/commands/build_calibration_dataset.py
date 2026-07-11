#!/usr/bin/env python3
"""Build calibration dataset from decision telemetry + horizon labels."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.core.decision_telemetry import frozen_policy_snapshot  # noqa: E402
from agent.core.v43_signal_gates import round_trip_cost_pct  # noqa: E402
from scripts.signal_recovery.log_parser import load_telemetry  # noqa: E402

FROZEN_PI0 = frozen_policy_snapshot()


def _signed_return_label(
    expected_return: float,
    *,
    cost_rt: Optional[float] = None,
) -> int:
    """Primary label: 1 if signed ER proxy exceeds round-trip cost."""
    c = cost_rt if cost_rt is not None else float(FROZEN_PI0["round_trip_cost"])
    return 1 if float(expected_return) > c else 0


def build_rows(telemetry_path: Path) -> List[Dict[str, Any]]:
    return build_rows_from_telemetry(load_telemetry(telemetry_path))


def build_rows_from_telemetry(
    telemetry_rows: List[Dict[str, Any]],
    *,
    replay_labels: Optional[Dict[str, int]] = None,
) -> List[Dict[str, Any]]:
    """Build calibration rows; optional replay_labels maps ts -> 0/1."""
    rows: List[Dict[str, Any]] = []
    for r in telemetry_rows:
        if r.get("event") not in (None, "decision_cycle", "decision_cycle_v3", "v43_prediction_complete"):
            continue
        latent = r.get("latent") if isinstance(r.get("latent"), dict) else {}
        scores = r.get("scores") if isinstance(r.get("scores"), dict) else {}
        er = r.get("expected_return")
        if er is None:
            continue
        kappa_raw = scores.get("conviction") or r.get("confidence")
        if kappa_raw is None:
            continue
        regime = (
            r.get("regime")
            or (r.get("extra") or {}).get("regime")
            or "unknown"
        )
        thesis = r.get("thesis_signal") or r.get("hypothesis_dominant") or "unknown"
        cost = float(
            (r.get("policy_snapshot") or {}).get("round_trip_cost")
            or FROZEN_PI0["round_trip_cost"]
        )
        ts_key = str(r.get("ts") or "")
        if replay_labels and ts_key in replay_labels:
            y = int(replay_labels[ts_key])
            label_source = "replay_forward_return"
        else:
            y = _signed_return_label(float(er), cost_rt=cost)
            label_source = "signed_return_proxy"
        rows.append(
            {
                "ts": r.get("ts"),
                "symbol": r.get("symbol"),
                "bar_index": r.get("bar_index"),
                "features": {
                    "trade_score": r.get("trade_score"),
                    "hypothesis_margin": r.get("hypothesis_margin"),
                    "collapse_rate": r.get("v43_collapse_rate"),
                },
                "epsilon_proxy": latent.get("epsilon_proxy"),
                "kappa_raw": float(kappa_raw),
                "q": latent.get("q_composite"),
                "A": latent.get("A_composite"),
                "y": y,
                "alt_label": y,
                "label_source": label_source,
                "regime": str(regime),
                "thesis_type": str(thesis),
                "policy_snapshot": r.get("policy_snapshot") or FROZEN_PI0,
            }
        )
    return rows


def _labels_from_replay_json(replay_path: Path) -> Dict[str, int]:
    """Map telemetry ts -> win label from counterfactual replay candidates."""
    data = json.loads(replay_path.read_text(encoding="utf-8"))
    labels: Dict[str, int] = {}
    for cand in data.get("candidates") or []:
        ts = cand.get("ts")
        if ts is None:
            continue
        ret = cand.get("realized_return_pct")
        if ret is None:
            continue
        cost = float(
            (cand.get("policy_snapshot") or {}).get("round_trip_cost")
            or FROZEN_PI0["round_trip_cost"]
        )
        labels[str(ts)] = 1 if float(ret) > cost else 0
    return labels


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--telemetry",
        type=Path,
        default=ROOT / "logs" / "signal_recovery" / "decision_telemetry.ndjson",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "logs" / "signal_recovery" / "calibration_dataset.json",
    )
    parser.add_argument(
        "--replay-json",
        type=Path,
        default=None,
        help="Use forward-return labels from counterfactual replay candidates",
    )
    args = parser.parse_args()

    replay_labels = _labels_from_replay_json(args.replay_json) if args.replay_json else None
    rows = build_rows_from_telemetry(
        load_telemetry(args.telemetry),
        replay_labels=replay_labels,
    )
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "frozen_pi0": FROZEN_PI0,
        "round_trip_cost_pct": round_trip_cost_pct(),
        "label_spec": (
            "y = 1[replay_forward_return > round_trip_cost]"
            if replay_labels
            else "y = 1[signed_return_proxy > round_trip_cost]"
        ),
        "sample_count": len(rows),
        "rows": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Built {len(rows)} calibration rows -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
