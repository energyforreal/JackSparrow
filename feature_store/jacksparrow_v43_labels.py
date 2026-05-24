"""Label schemes for JackSparrow v43 training experiments (signal recovery plan)."""

from __future__ import annotations

from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd

from feature_store.jacksparrow_v43_train_multihead import (
    build_cost_aware_forward_labels,
    build_forward_labels,
)


def build_triple_barrier_labels(
    close: pd.Series,
    *,
    forward_bars: int,
    take_profit_pct: float,
    stop_loss_pct: float,
) -> Tuple[pd.Series, Dict[str, float]]:
    """Triple-barrier labels: +1 TP hit first, -1 SL hit first, 0 timeout within horizon."""
    c = close.astype(float)
    n = len(c)
    fb = int(forward_bars)
    tp = float(take_profit_pct)
    sl = float(stop_loss_pct)
    out = pd.Series(np.nan, index=c.index, dtype=float)
    tp_hits = 0
    sl_hits = 0
    timeouts = 0
    for i in range(n - fb):
        entry = float(c.iloc[i])
        if not np.isfinite(entry) or entry <= 0:
            continue
        window = c.iloc[i + 1 : i + fb + 1].astype(float)
        if window.empty:
            continue
        rel = window / entry - 1.0
        tp_idx = rel[rel >= tp].index
        sl_idx = rel[rel <= -sl].index
        first_tp = tp_idx[0] if len(tp_idx) else None
        first_sl = sl_idx[0] if len(sl_idx) else None
        if first_tp is not None and (first_sl is None or first_tp <= first_sl):
            out.iloc[i] = 1.0
            tp_hits += 1
        elif first_sl is not None:
            out.iloc[i] = -1.0
            sl_hits += 1
        else:
            out.iloc[i] = 0.0
            timeouts += 1
    valid = out.notna()
    total = int(valid.sum())
    stats = {
        "take_profit_pct": tp,
        "stop_loss_pct": sl,
        "forward_bars": fb,
        "labeled_fraction": float(total / max(1, n)),
        "tp_hit_fraction": float(tp_hits / max(1, total)),
        "sl_hit_fraction": float(sl_hits / max(1, total)),
        "timeout_fraction": float(timeouts / max(1, total)),
    }
    return out, stats


def compare_label_schemes(
    close: pd.Series,
    *,
    forward_bars: int,
    round_trip_cost: float,
    take_profit_pct: float = 0.01,
    stop_loss_pct: float = 0.01,
) -> Dict[str, Any]:
    """Summarize simple / no-trade-band / triple-barrier label distributions."""
    raw = build_forward_labels(close, forward_bars)
    cost_masked, cost_stats = build_cost_aware_forward_labels(
        close, forward_bars, round_trip_cost=round_trip_cost
    )
    tb, tb_stats = build_triple_barrier_labels(
        close,
        forward_bars=forward_bars,
        take_profit_pct=take_profit_pct,
        stop_loss_pct=stop_loss_pct,
    )
    valid_raw = raw.dropna()
    valid_cost = cost_masked.dropna()
    valid_tb = tb.dropna()

    def _moments(s: pd.Series) -> Dict[str, float]:
        if s.empty:
            return {"count": 0.0, "mean": 0.0, "std": 0.0, "positive_frac": 0.0}
        return {
            "count": float(s.size),
            "mean": float(s.mean()),
            "std": float(s.std()) if s.size > 1 else 0.0,
            "positive_frac": float((s > 0).mean()),
        }

    return {
        "forward_bars": int(forward_bars),
        "round_trip_cost": float(round_trip_cost),
        "simple_forward": _moments(valid_raw),
        "cost_aware_no_trade_band": {**_moments(valid_cost), **cost_stats},
        "triple_barrier": {
            **_moments(valid_tb),
            **tb_stats,
            "long_frac": float((valid_tb > 0).mean()) if not valid_tb.empty else 0.0,
            "short_frac": float((valid_tb < 0).mean()) if not valid_tb.empty else 0.0,
            "flat_frac": float((valid_tb == 0).mean()) if not valid_tb.empty else 0.0,
        },
    }
