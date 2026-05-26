#!/usr/bin/env python3
"""Export in-process v43 OI/ticker ring buffer to CSV for Colab retraining.

Usage (from repo root, while agent has populated the ring buffer):
  python scripts/export_v43_oi_ring_buffer.py --symbol BTCUSD --out data/oi_history.csv

The agent must have run long enough to collect snapshots, or load history first via
``load_oi_ring_buffer_from_records``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pandas as pd  # noqa: E402

from agent.core.v43_oi_frames import (  # noqa: E402
    TICKER_RING_COLUMNS,
    export_oi_ring_buffer,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export v43 OI ring buffer to CSV")
    parser.add_argument("--symbol", default="BTCUSD", help="Symbol key in ring buffer")
    parser.add_argument(
        "--out",
        type=Path,
        default=_REPO / "data" / "oi_history.csv",
        help="Output CSV path",
    )
    args = parser.parse_args()
    rows = export_oi_ring_buffer(str(args.symbol))
    if not rows:
        print(
            f"No rows in ring buffer for {args.symbol!r}. "
            "Run the agent to collect ticker snapshots or load from an existing CSV.",
            file=sys.stderr,
        )
        return 1
    df = pd.DataFrame(rows)
    for col in TICKER_RING_COLUMNS:
        if col not in df.columns:
            df[col] = 0.5 if col == "taker_buy_ratio" else 0.0
    df = df[list(TICKER_RING_COLUMNS)]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    print(f"Wrote {len(df)} rows to {args.out}")
    print(f"Set V43_OI_HISTORY_CSV={args.out} and V43_ALLOW_EMPTY_OI_FOR_TRAINING=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
