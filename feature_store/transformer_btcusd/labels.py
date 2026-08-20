"""Forward-looking market labels for per-TF transformer training."""

from __future__ import annotations

from typing import Dict, Sequence

import numpy as np
import pandas as pd

from feature_store.transformer_btcusd.contract import (
    BREAKOUT_VOL_CONFIRM,
    CANDLE_CLASS_COL,
    CANDLE_FAMILY_DOJI,
    CHART_PATTERN_COL,
    CONTINUOUS_LABEL_COLS,
    FUTURE_CANDLE_COL,
    HORIZON_BARS_5M,
    HORIZON_DIR_ATR_DEADZONE,
    HORIZON_DIR_COLS,
    HORIZON_SPECS,
    HORIZON_STRUCTURE_COLS,
    MAX_V8_HORIZON_BARS,
    NEXT_BODY_COL,
    NEXT_DIRECTION_COL,
    NEXT_RANGE_COL,
    NEXT_WICK_COL,
    PATH_LABEL_HORIZON_BARS,
    PATTERN_ACTIVE_COL,
    SAMPLE_WEIGHT_COL,
    STRUCTURE_OUTCOME_COL,
    V8_CONTINUOUS_LABEL_COLS,
    VOL_Z_DRY,
    VOL_Z_EXPANSION,
    VOLUME_CONFIRMS_COL,
    VOLUME_STATE_COL,
    expected_direction_from_chart_pattern,
    max_label_horizon_bars,
)

_EPS = 1e-9
_STRUCTURE_OUTCOME_RANGE = 0
_STRUCTURE_OUTCOME_CONT_LONG = 1
_STRUCTURE_OUTCOME_CONT_SHORT = 2
_STRUCTURE_OUTCOME_BREAKOUT = 3
_STRUCTURE_OUTCOME_FAILED_BREAK = 4
_STRUCTURE_OUTCOME_REVERSAL = 5


def _sign_nonzero(value: float) -> float:
    if not np.isfinite(value) or abs(value) <= _EPS:
        return 0.0
    return 1.0 if value > 0.0 else -1.0


def _structure_outcome_id(
    *,
    bias_now: float,
    bias_end: float,
    mfe: float,
    mae: float,
    fwd_failed: np.ndarray,
    fwd_bars_since_breakout: np.ndarray,
) -> int:
    """Priority: failed break, breakout, reversal, continuation, else range."""
    if fwd_failed.size and np.any(fwd_failed >= 0.5):
        return _STRUCTURE_OUTCOME_FAILED_BREAK
    if fwd_bars_since_breakout.size and np.any(fwd_bars_since_breakout <= 0.5):
        return _STRUCTURE_OUTCOME_BREAKOUT
    s0 = _sign_nonzero(bias_now)
    s1 = _sign_nonzero(bias_end)
    if s0 != 0.0 and s1 != 0.0 and s0 != s1:
        return _STRUCTURE_OUTCOME_REVERSAL
    if bias_end > 0.0 and float(mfe) > float(mae):
        return _STRUCTURE_OUTCOME_CONT_LONG
    if bias_end < 0.0 and float(mae) > float(mfe):
        return _STRUCTURE_OUTCOME_CONT_SHORT
    return _STRUCTURE_OUTCOME_RANGE


def compute_market_labels(
    df: pd.DataFrame,
    *,
    path_label_horizon_bars: int = PATH_LABEL_HORIZON_BARS,
    mae_floor_atr_mult: float,
) -> pd.DataFrame:
    """Compute path/risk and forward-pattern labels on the native TF grid."""
    path_horizon = int(path_label_horizon_bars)
    max_horizon = max_label_horizon_bars(path_horizon)

    out_df = df.copy()
    n = len(out_df)
    close = out_df["close"].values
    high = out_df["high"].values
    low = out_df["low"].values
    open_px = out_df["open"].values
    atr = out_df["atr"].values
    volume = out_df["volume"].values
    has_oi = "open_interest" in out_df.columns
    oi = out_df["open_interest"].values if has_oi else np.full(n, np.nan)
    bias = (
        out_df["structure_bias"].to_numpy(dtype=np.float64)
        if "structure_bias" in out_df.columns
        else np.zeros(n, dtype=np.float64)
    )
    failed = (
        out_df["failed_break"].to_numpy(dtype=np.float64)
        if "failed_break" in out_df.columns
        else np.zeros(n, dtype=np.float64)
    )
    bars_bo = (
        out_df["bars_since_breakout"].to_numpy(dtype=np.float64)
        if "bars_since_breakout" in out_df.columns
        else np.full(n, np.inf)
    )
    candle_ids = (
        out_df[CANDLE_CLASS_COL].to_numpy(dtype=np.int64)
        if CANDLE_CLASS_COL in out_df.columns
        else np.zeros(n, dtype=np.int64)
    )

    path_cols = list(CONTINUOUS_LABEL_COLS)
    out: dict[str, np.ndarray] = {c: np.full(n, np.nan) for c in path_cols}
    structure_ids = np.full(n, np.nan)
    future_candle = np.full(n, np.nan)

    for i in range(n - max_horizon):
        entry = close[i]
        atr_i = float(atr[i]) if np.isfinite(atr[i]) else _EPS
        atr_i = max(atr_i, _EPS)

        fwd_close = close[i + 1 : i + path_horizon + 1]
        fwd_high = high[i + 1 : i + path_horizon + 1]
        fwd_low = low[i + 1 : i + path_horizon + 1]

        fwd_rets = np.log(fwd_close / np.concatenate(([entry], fwd_close[:-1])))
        out["future_volatility"][i] = fwd_rets.std()

        favorable = (fwd_high - entry) / entry
        adverse = (entry - fwd_low) / entry
        mfe_idx = int(np.argmax(favorable))
        out["mfe"][i] = favorable[mfe_idx]
        out["mae"][i] = adverse[int(np.argmax(adverse))]

        if out["mfe"][i] >= mae_floor_atr_mult * atr[i] / entry:
            out["drawdown_before_mfe"][i] = (
                adverse[: mfe_idx + 1].max() if mfe_idx > 0 else 0.0
            )

        out["trend_strength"][i] = abs(fwd_close[-1] - entry) / (atr_i)

        if has_oi and not np.isnan(oi[i]) and oi[i] != 0:
            out["future_oi_change_pct"][i] = (oi[i + path_horizon] - oi[i]) / (
                abs(oi[i]) + _EPS
            )
        past_start = max(0, i - path_horizon)
        past_vol_mean = volume[past_start : i + 1].mean()
        out["future_volume_change_pct"][i] = (
            volume[i + 1 : i + path_horizon + 1].mean() - past_vol_mean
        ) / (past_vol_mean + _EPS)

        move_atr = (close[i + 1] - close[i]) / atr_i
        body = float(close[i] - open_px[i])
        cid = int(candle_ids[i])
        if cid in CANDLE_FAMILY_DOJI or abs(body) <= _EPS:
            out["candle_follow_through_atr"][i] = abs(move_atr)
        else:
            out["candle_follow_through_atr"][i] = float(np.sign(body)) * move_atr

        end = i + path_horizon
        out["structure_delta"][i] = float(bias[end] - bias[i])
        future_candle[i] = float(candle_ids[i + 1])
        structure_ids[i] = float(
            _structure_outcome_id(
                bias_now=float(bias[i]),
                bias_end=float(bias[end]),
                mfe=float(out["mfe"][i]),
                mae=float(out["mae"][i]),
                fwd_failed=failed[i + 1 : i + path_horizon + 1],
                fwd_bars_since_breakout=bars_bo[i + 1 : i + path_horizon + 1],
            )
        )

    for col, values in out.items():
        out_df[col] = values
    out_df[STRUCTURE_OUTCOME_COL] = structure_ids
    out_df[FUTURE_CANDLE_COL] = future_candle
    return out_df


def trim_label_tail(
    df: pd.DataFrame,
    *,
    path_label_horizon_bars: int = PATH_LABEL_HORIZON_BARS,
) -> pd.DataFrame:
    """Drop rows without complete forward labels."""
    max_horizon = max_label_horizon_bars(path_label_horizon_bars)
    return df.iloc[: -(max_horizon + 1)].reset_index(drop=True)


def active_training_label_cols() -> tuple[str, ...]:
    return CONTINUOUS_LABEL_COLS


def label_nan_summary(df: pd.DataFrame) -> Dict[str, float]:
    """Per-label NaN rates for notebook diagnostics."""
    cols = [c for c in CONTINUOUS_LABEL_COLS if c in df.columns]
    if not cols:
        return {}
    return df[cols].isna().mean().round(4).to_dict()


def _volume_state_id(vol_z: float, breakout_vol_ratio: float) -> int:
    if np.isfinite(vol_z) and vol_z >= VOL_Z_EXPANSION:
        return 2
    if np.isfinite(breakout_vol_ratio) and breakout_vol_ratio >= BREAKOUT_VOL_CONFIRM:
        return 2
    if np.isfinite(vol_z) and vol_z <= VOL_Z_DRY:
        return 0
    return 1


def _volume_confirms(pattern_id: int, volume_state: int) -> int:
    pid = int(pattern_id)
    vs = int(volume_state)
    if pid == 0:
        return 0
    if pid in (1, 2, 7, 4, 5, 8) and vs != 2:
        return 0
    if pid == 3 and vs == 2:
        return 0
    return 1


def _wick_class(upper: float, lower: float) -> int:
    u = float(upper) if np.isfinite(upper) else 0.0
    lo = float(lower) if np.isfinite(lower) else 0.0
    if u > 0.30 and lo > 0.30:
        return 3
    if u > 2.0 * max(lo, 1e-6) and u > 0.30:
        return 1
    if lo > 2.0 * max(u, 1e-6) and lo > 0.30:
        return 2
    return 0


def _horizon_direction(move: float, atr: float) -> int:
    dead = HORIZON_DIR_ATR_DEADZONE * max(float(atr), 1e-9)
    if abs(float(move)) < dead:
        return 1
    return 2 if float(move) > 0.0 else 0


def compute_horizon_behavior_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Label wall-clock path behavior at 5m/10m/15m/30m/1h/2h on the 5m grid.

    Features at bar t stay causal. Targets at t use bars t+1 ... t+k only.
    """
    out_df = df.copy()
    n = len(out_df)
    max_k = int(MAX_V8_HORIZON_BARS)
    close = out_df["close"].to_numpy(dtype=np.float64)
    high = out_df["high"].to_numpy(dtype=np.float64)
    low = out_df["low"].to_numpy(dtype=np.float64)
    atr = (
        out_df["atr"].to_numpy(dtype=np.float64)
        if "atr" in out_df.columns
        else np.full(n, np.nan)
    )
    bias = (
        out_df["structure_bias"].to_numpy(dtype=np.float64)
        if "structure_bias" in out_df.columns
        else np.zeros(n, dtype=np.float64)
    )
    failed = (
        out_df["failed_break"].to_numpy(dtype=np.float64)
        if "failed_break" in out_df.columns
        else np.zeros(n, dtype=np.float64)
    )
    bars_bo = (
        out_df["bars_since_breakout"].to_numpy(dtype=np.float64)
        if "bars_since_breakout" in out_df.columns
        else np.full(n, np.inf)
    )
    vol_z = (
        out_df["vol_z"].to_numpy(dtype=np.float64)
        if "vol_z" in out_df.columns
        else np.zeros(n)
    )
    bo_vol = (
        out_df["breakout_vol_ratio"].to_numpy(dtype=np.float64)
        if "breakout_vol_ratio" in out_df.columns
        else np.ones(n)
    )

    dir_out = {col: np.full(n, np.nan) for col in HORIZON_DIR_COLS}
    struct_out = {col: np.full(n, np.nan) for col in HORIZON_STRUCTURE_COLS}
    cont_out = {col: np.full(n, np.nan) for col in V8_CONTINUOUS_LABEL_COLS}
    vol_state = np.full(n, np.nan)

    for i in range(n - max_k):
        entry = float(close[i])
        atr_i = float(atr[i]) if np.isfinite(atr[i]) else _EPS
        atr_i = max(atr_i, _EPS)
        vol_state[i] = float(_volume_state_id(float(vol_z[i]), float(bo_vol[i])))
        for key, k in HORIZON_SPECS:
            kk = int(k)
            fwd_close = close[i + 1 : i + kk + 1]
            fwd_high = high[i + 1 : i + kk + 1]
            fwd_low = low[i + 1 : i + kk + 1]
            if fwd_close.size < kk:
                continue
            move = float(close[i + kk] - close[i])
            dir_out[f"{key}_dir"][i] = float(_horizon_direction(move, atr_i))
            log_base = np.concatenate(([entry], fwd_close[:-1]))
            fwd_rets = np.log(
                np.maximum(fwd_close, _EPS) / np.maximum(log_base, _EPS)
            )
            cont_out[f"{key}_vol"][i] = float(fwd_rets.std())
            scale = max(abs(entry), _EPS)
            favorable = (fwd_high - entry) / scale
            adverse = (entry - fwd_low) / scale
            cont_out[f"{key}_mfe"][i] = float(favorable.max())
            cont_out[f"{key}_mae"][i] = float(adverse.max())
            cont_out[f"{key}_trend_strength"][i] = abs(
                float(fwd_close[-1] - entry)
            ) / atr_i
            end = i + kk
            struct_out[f"{key}_structure"][i] = float(
                _structure_outcome_id(
                    bias_now=float(bias[i]),
                    bias_end=float(bias[end]),
                    mfe=float(cont_out[f"{key}_mfe"][i]),
                    mae=float(cont_out[f"{key}_mae"][i]),
                    fwd_failed=failed[i + 1 : i + kk + 1],
                    fwd_bars_since_breakout=bars_bo[i + 1 : i + kk + 1],
                )
            )

    for col, values in dir_out.items():
        out_df[col] = values
    for col, values in struct_out.items():
        out_df[col] = values
    for col, values in cont_out.items():
        out_df[col] = values
    out_df[VOLUME_STATE_COL] = vol_state
    return out_df


def trim_v8_label_tail(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows without a complete longest-horizon (2h / 24-bar) label."""
    max_h = int(MAX_V8_HORIZON_BARS)
    if len(df) <= max_h + 1:
        return df.iloc[0:0].reset_index(drop=True)
    return df.iloc[: -(max_h + 1)].reset_index(drop=True)


def compute_next_candle_structure_labels(
    df: pd.DataFrame,
    *,
    path_label_horizon_bars: int = PATH_LABEL_HORIZON_BARS,
    horizon_bars: Sequence[int] = HORIZON_BARS_5M,
    gate_chart_volume: bool = True,
) -> pd.DataFrame:
    """Label t+1 candle structure, 5m horizon directions, and volume/chart gates.

    Target anatomy is computed from bar t+1 OHLC only. Bin edges for body/range
    use a causal rolling window through bar t (no future leakage).
    """
    out_df = df.copy()
    n = len(out_df)
    max_h = max(int(path_label_horizon_bars), max(int(k) for k in horizon_bars))
    close = out_df["close"].to_numpy(dtype=np.float64)
    open_px = out_df["open"].to_numpy(dtype=np.float64)
    high = out_df["high"].to_numpy(dtype=np.float64)
    low = out_df["low"].to_numpy(dtype=np.float64)
    atr = (
        out_df["atr"].to_numpy(dtype=np.float64)
        if "atr" in out_df.columns
        else np.full(n, np.nan)
    )
    body_ratio = (
        out_df["body_ratio"].to_numpy(dtype=np.float64)
        if "body_ratio" in out_df.columns
        else (close - open_px) / np.maximum(high - low, 1e-9)
    )
    upper = (
        out_df["upper_wick_ratio"].to_numpy(dtype=np.float64)
        if "upper_wick_ratio" in out_df.columns
        else np.zeros(n)
    )
    lower = (
        out_df["lower_wick_ratio"].to_numpy(dtype=np.float64)
        if "lower_wick_ratio" in out_df.columns
        else np.zeros(n)
    )
    range_atr = (
        out_df["range_atr"].to_numpy(dtype=np.float64)
        if "range_atr" in out_df.columns
        else (high - low) / np.maximum(atr, 1e-9)
    )
    vol_z = (
        out_df["vol_z"].to_numpy(dtype=np.float64)
        if "vol_z" in out_df.columns
        else np.zeros(n)
    )
    bo_vol = (
        out_df["breakout_vol_ratio"].to_numpy(dtype=np.float64)
        if "breakout_vol_ratio" in out_df.columns
        else np.ones(n)
    )
    pattern = (
        out_df[CHART_PATTERN_COL].to_numpy(dtype=np.int64)
        if CHART_PATTERN_COL in out_df.columns
        else np.zeros(n, dtype=np.int64)
    )
    candle_ids = (
        out_df[CANDLE_CLASS_COL].to_numpy(dtype=np.int64)
        if CANDLE_CLASS_COL in out_df.columns
        else np.zeros(n, dtype=np.int64)
    )

    abs_body = np.abs(body_ratio)
    q33 = (
        pd.Series(abs_body)
        .shift(1)
        .rolling(64, min_periods=20)
        .quantile(0.33)
        .to_numpy()
    )
    q66 = (
        pd.Series(abs_body)
        .shift(1)
        .rolling(64, min_periods=20)
        .quantile(0.66)
        .to_numpy()
    )
    rng_med = (
        pd.Series(range_atr).shift(1).rolling(64, min_periods=20).median().to_numpy()
    )

    nxt_dir = np.full(n, np.nan)
    nxt_body = np.full(n, np.nan)
    nxt_wick = np.full(n, np.nan)
    nxt_range = np.full(n, np.nan)
    vol_state = np.full(n, np.nan)
    vol_ok = np.zeros(n, dtype=np.float64)
    pat_active = np.zeros(n, dtype=np.float64)
    weight = np.zeros(n, dtype=np.float64)
    horizon_out = {col: np.full(n, np.nan) for col in HORIZON_DIR_COLS}

    for i in range(n - max_h):
        j = i + 1
        body_j = close[j] - open_px[j]
        atr_i = float(atr[i]) if np.isfinite(atr[i]) else 1e-9
        atr_i = max(atr_i, 1e-9)
        if abs(body_j) < 0.15 * atr_i:
            nxt_dir[i] = 1.0
        elif body_j > 0:
            nxt_dir[i] = 2.0
        else:
            nxt_dir[i] = 0.0

        ab = abs(float(body_ratio[j]))
        lo_b = float(q33[j]) if np.isfinite(q33[j]) else 0.30
        hi_b = float(q66[j]) if np.isfinite(q66[j]) else 0.70
        if ab <= lo_b:
            nxt_body[i] = 0.0
        elif ab >= hi_b:
            nxt_body[i] = 2.0
        else:
            nxt_body[i] = 1.0

        nxt_wick[i] = float(_wick_class(float(upper[j]), float(lower[j])))
        med = float(rng_med[j]) if np.isfinite(rng_med[j]) else 1.0
        ra = float(range_atr[j]) if np.isfinite(range_atr[j]) else med
        if ra < 0.70 * med:
            nxt_range[i] = 0.0
        elif ra > 1.40 * med:
            nxt_range[i] = 2.0
        else:
            nxt_range[i] = 1.0

        vs = _volume_state_id(float(vol_z[i]), float(bo_vol[i]))
        vol_state[i] = float(vs)
        pid = int(pattern[i])
        pat_active[i] = 0.0 if pid == 0 else 1.0
        vol_ok[i] = float(_volume_confirms(pid, vs))
        if gate_chart_volume:
            weight[i] = float(pat_active[i] >= 0.5 and vol_ok[i] >= 0.5)
        else:
            weight[i] = 1.0

        for col, k in zip(HORIZON_DIR_COLS, horizon_bars):
            kk = int(k)
            if i + kk >= n:
                continue
            move = close[i + kk] - close[i]
            horizon_out[col][i] = float(_horizon_direction(move, atr_i))

    out_df[NEXT_DIRECTION_COL] = nxt_dir
    out_df[NEXT_BODY_COL] = nxt_body
    out_df[NEXT_WICK_COL] = nxt_wick
    out_df[NEXT_RANGE_COL] = nxt_range
    out_df[VOLUME_STATE_COL] = vol_state
    out_df[VOLUME_CONFIRMS_COL] = vol_ok
    out_df[PATTERN_ACTIVE_COL] = pat_active
    out_df[SAMPLE_WEIGHT_COL] = weight
    for col, values in horizon_out.items():
        out_df[col] = values
    expected = np.array(
        [expected_direction_from_chart_pattern(int(p)) for p in pattern],
        dtype=np.float64,
    )
    agrees = (nxt_dir == expected).astype(np.float64)
    out_df["pattern_validates"] = agrees * vol_ok
    if CANDLE_CLASS_COL in out_df.columns:
        future = np.full(n, np.nan)
        future[: n - 1] = candle_ids[1:].astype(np.float64)
        if FUTURE_CANDLE_COL not in out_df.columns:
            out_df[FUTURE_CANDLE_COL] = future
    return out_df


def trim_v7_label_tail(
    df: pd.DataFrame,
    *,
    path_label_horizon_bars: int = PATH_LABEL_HORIZON_BARS,
    horizon_bars: Sequence[int] = HORIZON_BARS_5M,
) -> pd.DataFrame:
    """Drop rows without complete t+k and path labels."""
    max_h = max(int(path_label_horizon_bars), max(int(k) for k in horizon_bars))
    return df.iloc[: -(max_h + 1)].reset_index(drop=True)
