"""Phase 3.2: compare label schemes on available price history."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from feature_store.jacksparrow_v43_labels import compare_label_schemes

_PARQUET_CANDIDATES = (
    Path("data/labeled/BTCUSD_5m_labeled.parquet"),
    Path("data/BTCUSD_5m.parquet"),
    Path("feature_store/data/BTCUSD_5m.parquet"),
)


def _load_close_series() -> Optional[pd.Series]:
    for p in _PARQUET_CANDIDATES:
        if not p.is_file():
            continue
        df = pd.read_parquet(p)
        col = "close" if "close" in df.columns else None
        if col is None:
            continue
        return df[col].astype(float)
    return None


def run_label_experiments(
    *,
    out_dir: Path,
    forward_bars: int = 6,
    round_trip_cost: float = 0.0048,
) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    close = _load_close_series()
    if close is None or len(close) < forward_bars + 10:
        n = 2000
        close = pd.Series(
            [100_000.0 * (1.0 + 0.0001 * (i % 50 - 25)) for i in range(n)]
        )
        source = "synthetic_close_fallback"
    else:
        source = "parquet"
        close = close.tail(50000)

    summary = compare_label_schemes(
        close,
        forward_bars=forward_bars,
        round_trip_cost=round_trip_cost,
    )
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": "3.2",
        "close_source": source,
        "forward_bars": forward_bars,
        "round_trip_cost": round_trip_cost,
        "label_comparison": summary,
    }
    out_path = out_dir / "label_experiments_report.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
