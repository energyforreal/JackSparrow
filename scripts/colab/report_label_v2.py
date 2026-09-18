"""CLI: Label V2 distribution report. Does not train or export a model."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd

from feature_store.transformer_btcusd.contract import (
    LABEL_V2_THETA_GRID,
    LABEL_V2_TP_SL_GRID,
    default_fusion_training_config,
)
from feature_store.transformer_btcusd.mtf_labels_v2 import (
    compute_fusion_path_targets,
    format_label_v2_table,
    summarize_label_v2,
)
from scripts.colab.transformer_data import fetch_candles, validate_ohlcv_completeness


def _parse_grid(raw: Optional[str]) -> Tuple[Tuple[float, float], ...]:
    if not raw:
        return tuple((float(a), float(b)) for a, b in LABEL_V2_TP_SL_GRID)
    pairs = []
    for chunk in str(raw).split(","):
        sl_s, tp_s = chunk.strip().split("/")
        pairs.append((float(sl_s), float(tp_s)))
    return tuple(pairs)


def _parse_thetas(raw: Optional[str]) -> Tuple[float, ...]:
    if not raw:
        return tuple(float(t) for t in LABEL_V2_THETA_GRID)
    return tuple(float(x.strip()) for x in str(raw).split(",") if x.strip())


def _load_frame(
    parquet: Optional[Path],
    *,
    history_days: int,
    base_url: str,
    cache_path: Path,
) -> pd.DataFrame:
    if parquet is not None:
        path = Path(parquet)
        if not path.is_file():
            raise FileNotFoundError(f"parquet not found: {path}")
        df = pd.read_parquet(path)
        print(f"Loaded {path} rows={len(df)}")
        return df
    if cache_path.is_file():
        df = pd.read_parquet(cache_path)
        print(f"Loaded cache {cache_path} rows={len(df)}")
        return df
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=int(history_days))
    print(f"Fetching BTCUSD 5m OHLCV for {history_days}d...")
    raw = fetch_candles(
        "BTCUSD",
        "5m",
        int(start_dt.timestamp()),
        int(end_dt.timestamp()),
        base_url,
    )
    report = validate_ohlcv_completeness(raw, "5m", symbol="BTCUSD")
    print(
        f"OHLCV BTCUSD 5m: {report['rows']} bars, "
        f"completeness {report['completeness']:.1%}, gaps={report['gaps']}"
    )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    raw.to_parquet(cache_path, index=False)
    print(f"Wrote cache {cache_path}")
    return raw


def _freeze_gate(report: Dict[str, Any]) -> Dict[str, Any]:
    """Record chosen θ per horizon for the go/no-go stop."""
    chosen = dict(report.get("chosen_theta") or {})
    span = dict(report.get("span") or {})
    return {
        "overall": report.get("overall"),
        "chosen_theta": chosen,
        "frozen": {
            "h30m": chosen.get("h30m"),
            "h1h": chosen.get("h1h"),
            "h2h": chosen.get("h2h"),
        },
        "span": span,
        "notes": (
            "Do not retrain the fused Transformer until overall is go "
            "(h2h may be regression-only). Live v11 2-class labels stay in force."
        ),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Label V2 path-target distribution report (no training)."
    )
    parser.add_argument("--parquet", type=Path, default=None)
    parser.add_argument("--history-days", type=int, default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("export/label_v2/label_v2_report.json"),
    )
    parser.add_argument("--thetas", type=str, default=None)
    parser.add_argument(
        "--tp-sl-grid",
        type=str,
        default=None,
        help="Comma-separated sl/tp pairs, e.g. 1.0/1.5,1.5/2.25",
    )
    args = parser.parse_args(argv)

    cfg = default_fusion_training_config()
    history_days = int(args.history_days or cfg.get("history_days") or 900)
    out_path = Path(args.output)
    cache_path = out_path.parent / "btcusd_5m_raw.parquet"
    df = _load_frame(
        args.parquet,
        history_days=history_days,
        base_url=str(cfg.get("base_url") or "https://api.india.delta.exchange"),
        cache_path=cache_path,
    )
    labeled = compute_fusion_path_targets(df)
    report = summarize_label_v2(
        labeled,
        thetas=_parse_thetas(args.thetas),
        tp_sl_grid=_parse_grid(args.tp_sl_grid),
        already_labeled=True,
    )
    report["gate"] = _freeze_gate(report)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(format_label_v2_table(report))
    print(json.dumps(report["gate"], indent=2))
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
