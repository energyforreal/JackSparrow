"""CLI entry for adaptive retrain in a subprocess (stdout: one JSON line)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="JackSparrow adaptive retrain worker")
    parser.add_argument("--timeframe", required=True, help="e.g. 5m or 15m")
    parser.add_argument("--parquet-dir", required=True, help="Directory with labeled_{tf}.parquet")
    args = parser.parse_args()

    pdir = Path(args.parquet_dir)
    if not pdir.is_dir():
        out = {"action": "error", "detail": "parquet_dir_missing", "path": str(pdir)}
        print(json.dumps(out), flush=True)
        sys.exit(2)

    from agent.learning.adaptive.adaptive_controller import maybe_retrain_timeframe
    from agent.learning.adaptive.labeled_data import load_labeled_parquet

    df = load_labeled_parquet(pdir, args.timeframe)
    result = maybe_retrain_timeframe(args.timeframe, df)
    print(json.dumps(result), flush=True)
    if result.get("action") == "accepted":
        sys.exit(0)
    if result.get("action") == "error":
        sys.exit(3)
    sys.exit(0)


if __name__ == "__main__":
    main()
