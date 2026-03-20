"""
Release workflow for Colab exports.

Typical flow:
  1) Train in Colab and download ZIP
  2) Extract ZIP into a folder under agent/model_storage (or any folder holding metadata_BTCUSD_*.json)
  3) Run this script pointing at the extracted folder

This script:
  - validates walk-forward Sharpe from metadata_BTCUSD_*.json
  - validates paper-soak net PnL + activity using logs/paper_trades/paper_trades.log (if present / required)
  - records an append-only release history JSONL entry
  - optionally updates MODEL_DIR in the local .env file
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.core.validation_gates import (
    compute_paper_soak_metrics,
    load_metadata_json,
    parse_paper_trade_log,
    validate_paper_soak,
    validate_walkforward_metadata,
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_paper_log(project_root: Path) -> Path:
    return project_root / "logs" / "paper_trades" / "paper_trades.log"


def _update_env_model_dir(env_path: Path, new_model_dir: Path) -> None:
    """
    Update only the MODEL_DIR=... line inside .env.

    Keeps all other variables unchanged.
    """
    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    out: List[str] = []
    updated = False
    for line in lines:
        if line.startswith("MODEL_DIR="):
            rel = str(new_model_dir)
            if str(new_model_dir).startswith(str(_project_root())):
                rel = os.path.relpath(str(new_model_dir), str(_project_root()))
                # Keep relative style used in repo (.env uses ./...)
                if not rel.startswith("."):
                    rel = "./" + rel
            out.append(f"MODEL_DIR={rel}\n")
            updated = True
        else:
            out.append(line)

    if not updated:
        raise RuntimeError(f"MODEL_DIR= line not found in {env_path}")

    env_path.write_text("".join(out), encoding="utf-8")


def main() -> int:
    project_root = _project_root()

    ap = argparse.ArgumentParser()
    ap.add_argument("--export-dir", required=True, type=str, help="Extracted Colab export directory (must contain metadata_BTCUSD_*.json)")
    ap.add_argument("--symbol", default="BTCUSD", type=str)

    ap.add_argument("--env-path", default=str(project_root / ".env"), type=str)
    ap.add_argument("--update-env", default="false", type=str, help="true/false: update MODEL_DIR in .env on success")

    ap.add_argument("--require-paper-log", default="true", type=str, help="true/false: fail if paper log missing")

    ap.add_argument("--min-sharpe", type=float, default=0.0)
    ap.add_argument("--min-total-trades", type=int, default=10)
    ap.add_argument("--min-trades-per-hour", type=float, default=1.0)
    ap.add_argument("--min-net-pnl", type=float, default=0.0)
    ap.add_argument("--max-drawdown-frac", type=float, default=0.25)

    args = ap.parse_args()

    export_dir = Path(args.export_dir)
    if not export_dir.exists():
        print(f"❌ export-dir not found: {export_dir}")
        return 1

    metadata_files = sorted(export_dir.glob(f"metadata_{args.symbol}_*.json"))
    if not metadata_files:
        print(f"❌ No metadata_{args.symbol}_*.json found in {export_dir}")
        return 1

    # 1) Walk-forward validation
    wf_failures: List[str] = []
    wf_summary: List[Dict[str, Any]] = []
    for meta_path in metadata_files:
        metadata = load_metadata_json(meta_path)
        passed, reasons = validate_walkforward_metadata(metadata, min_sharpe=args.min_sharpe)
        if not passed:
            wf_failures.append(f"{meta_path.name}: {', '.join(reasons)}")
        wf_summary.append(
            {
                "file": meta_path.name,
                "sharpe": (metadata.get("walkforward_mean") or {}).get("sharpe"),
                "passed": passed,
                "reasons": reasons,
            }
        )

    # 2) Paper soak validation (optional but usually required)
    require_paper = str(args.require_paper_log).lower() in ("1", "true", "yes")
    paper_log = _default_paper_log(project_root)
    paper_summary: Dict[str, Any] = {"paper_log": str(paper_log)}
    paper_failures: List[str] = []

    if paper_log.exists():
        closes = parse_paper_trade_log(paper_log)
        metrics = compute_paper_soak_metrics(closes)
        passed, reasons = validate_paper_soak(
            metrics,
            min_total_trades=args.min_total_trades,
            min_trades_per_hour=args.min_trades_per_hour,
            min_net_pnl=args.min_net_pnl,
            max_drawdown_frac=args.max_drawdown_frac,
        )
        paper_summary["metrics"] = metrics
        paper_summary["passed"] = passed
        paper_summary["reasons"] = reasons
        if not passed:
            paper_failures.append(", ".join(reasons))
    else:
        paper_summary["missing"] = True
        if require_paper:
            paper_failures.append(f"paper log missing: {paper_log}")

    if wf_failures or paper_failures:
        print("❌ Release validation FAILED")
        for f in wf_failures:
            print(f"  - walkforward: {f}")
        for f in paper_failures:
            print(f"  - paper_soak: {f}")
        return 1

    # 3) Record release history
    history_path = project_root / "agent" / "model_storage" / "release_history.jsonl"
    history_path.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "export_dir": str(export_dir),
        "symbol": args.symbol,
        "metadata_files": [p.name for p in metadata_files],
        "walkforward": wf_summary,
        "paper_soak": paper_summary,
    }
    with history_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")

    print(f"✅ Release validated and recorded in: {history_path}")

    # 4) Optional MODEL_DIR switch
    if str(args.update_env).lower() in ("1", "true", "yes"):
        env_path = Path(args.env_path)
        if not env_path.exists():
            raise FileNotFoundError(str(env_path))
        _update_env_model_dir(env_path, export_dir)
        print(f"✅ Updated MODEL_DIR in {env_path}")
        print("Restart the agent process to pick up the new model_dir.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

