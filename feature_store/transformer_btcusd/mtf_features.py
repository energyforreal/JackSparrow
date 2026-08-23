"""Per-timeframe pattern encodings for the fused multi-TF model.

Each TF is featured on its *native* grid. Resampled HTF structure is never
added; 10m/30m/1h/2h representations come from independently sampled OHLCV.
"""

from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from feature_store.pattern_features import (
    CANDLESTICK_FEATURES,
    CHART_PATTERN_FEATURES,
    CandlestickPatternEngine,
    ChartPatternEngine,
)
from feature_store.transformer_btcusd.contract import (
    CANDLE_CLASS_COL,
    FEATURE_COLS,
    FUSION_INPUT_RESOLUTIONS,
    FUSION_WINDOW_LEN,
    RESOLUTION_MINUTES,
    fusion_native_feature_cols,
)
from feature_store.transformer_btcusd.features import add_features, assemble_raw_frame
from feature_store.transformer_btcusd.inference import zscore_window
from feature_store.transformer_btcusd.mtf_frames import (
    last_n_closed_bars,
    normalize_mtf_frames,
)


def fusion_feature_cols() -> Tuple[str, ...]:
    """Continuous columns in each TF window (native TA + pattern engines)."""
    return fusion_native_feature_cols() + tuple(CANDLESTICK_FEATURES) + tuple(
        CHART_PATTERN_FEATURES
    )


def add_native_tf_features(
    df: pd.DataFrame,
    *,
    resolution: str,
    funding_df: Optional[pd.DataFrame] = None,
    oi_df: Optional[pd.DataFrame] = None,
    atr_period: int = 14,
) -> pd.DataFrame:
    """Causal features on one independently sampled TF. No HTF resample."""
    res = str(resolution).strip().lower()
    minutes = int(RESOLUTION_MINUTES[res])
    raw = assemble_raw_frame(df, funding_df=funding_df, oi_df=oi_df)
    feat = add_features(
        raw,
        resolution_minutes=minutes,
        atr_period=atr_period,
        include_htf=False,
    )
    candle_engine = CandlestickPatternEngine()
    chart_engine = ChartPatternEngine()
    cdl = candle_engine.compute_all(feat)
    chart = chart_engine.compute_all(feat, atr_period=atr_period)
    for col in cdl.columns:
        feat[col] = cdl[col].to_numpy()
    for col in chart.columns:
        feat[col] = chart[col].to_numpy()
    cols = fusion_feature_cols()
    for col in cols:
        if col not in feat.columns:
            feat[col] = 0.0
    if CANDLE_CLASS_COL not in feat.columns:
        feat[CANDLE_CLASS_COL] = 0
    return feat


def _window_matrix(
    feat_df: pd.DataFrame,
    *,
    cols: Sequence[str],
    window_len: int,
) -> np.ndarray:
    values = feat_df.loc[:, list(cols)].to_numpy(dtype=np.float64)
    values = np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)
    if len(values) < int(window_len):
        pad = np.zeros((int(window_len) - len(values), values.shape[1]), dtype=np.float64)
        values = np.vstack([pad, values]) if len(values) else pad
    else:
        values = values[-int(window_len) :]
    return values.astype(np.float32)


def encode_tf_window(
    tf_df: pd.DataFrame,
    decision_time: pd.Timestamp,
    *,
    resolution: str,
    window_len: int = FUSION_WINDOW_LEN,
    funding_df: Optional[pd.DataFrame] = None,
    oi_df: Optional[pd.DataFrame] = None,
    featured: Optional[pd.DataFrame] = None,
    zscore: bool = True,
) -> np.ndarray:
    """64-bar native window for one TF at decision time T (closed bars only)."""
    minutes = int(RESOLUTION_MINUTES[str(resolution).strip().lower()])
    if featured is None:
        closed = last_n_closed_bars(
            tf_df,
            decision_time,
            resolution_minutes=minutes,
            window_len=max(int(window_len) * 4, 256),
        )
        featured = add_native_tf_features(
            closed,
            resolution=resolution,
            funding_df=funding_df,
            oi_df=oi_df,
        )
        featured = last_n_closed_bars(
            featured,
            decision_time,
            resolution_minutes=minutes,
            window_len=int(window_len),
        )
    else:
        featured = last_n_closed_bars(
            featured,
            decision_time,
            resolution_minutes=minutes,
            window_len=int(window_len),
        )
    cols = fusion_feature_cols()
    window = _window_matrix(featured, cols=cols, window_len=int(window_len))
    if zscore:
        window = zscore_window(window)
    return window


def encode_all_tf_windows(
    frames: Mapping[str, pd.DataFrame],
    decision_time: pd.Timestamp,
    *,
    window_len: int = FUSION_WINDOW_LEN,
    funding_df: Optional[pd.DataFrame] = None,
    oi_df: Optional[pd.DataFrame] = None,
    featured_by_tf: Optional[Mapping[str, pd.DataFrame]] = None,
    zscore: bool = True,
) -> Dict[str, np.ndarray]:
    """Independent Z-ready windows for 5m/10m/30m/1h/2h at time T."""
    normalized = normalize_mtf_frames(frames)
    out: Dict[str, np.ndarray] = {}
    for res in FUSION_INPUT_RESOLUTIONS:
        df = normalized.get(res)
        if df is None or df.empty:
            raise ValueError(f"Missing independent OHLCV for {res}")
        feat = None if featured_by_tf is None else featured_by_tf.get(res)
        out[res] = encode_tf_window(
            df,
            decision_time,
            resolution=res,
            window_len=window_len,
            funding_df=funding_df,
            oi_df=oi_df,
            featured=feat,
            zscore=zscore,
        )
    return out


def precompute_featured_frames(
    frames: Mapping[str, pd.DataFrame],
    *,
    funding_df: Optional[pd.DataFrame] = None,
    oi_df: Optional[pd.DataFrame] = None,
) -> Dict[str, pd.DataFrame]:
    """Feature each TF once (training). Do not resample across TFs."""
    normalized = normalize_mtf_frames(frames)
    featured: Dict[str, pd.DataFrame] = {}
    for res in FUSION_INPUT_RESOLUTIONS:
        df = normalized.get(res)
        if df is None or df.empty:
            raise ValueError(f"Missing independent OHLCV for {res}")
        featured[res] = add_native_tf_features(
            df,
            resolution=res,
            funding_df=funding_df if res == "5m" else None,
            oi_df=oi_df if res == "5m" else None,
        )
    return featured


def stack_tf_windows(
    windows: Mapping[str, np.ndarray],
) -> np.ndarray:
    """Stack TF windows as (n_tf, window_len, n_features) in fusion order."""
    mats: List[np.ndarray] = []
    for res in FUSION_INPUT_RESOLUTIONS:
        if res not in windows:
            raise KeyError(f"Missing window for {res}")
        mats.append(np.asarray(windows[res], dtype=np.float32))
    return np.stack(mats, axis=0)


def collect_training_windows(
    featured_by_tf: Mapping[str, pd.DataFrame],
    decision_times: Sequence[pd.Timestamp],
    *,
    window_len: int = FUSION_WINDOW_LEN,
    zscore: bool = True,
) -> Dict[str, np.ndarray]:
    """Build (n, window, feat) arrays per TF. Decision times are 5m closes."""
    n = len(decision_times)
    cols = fusion_feature_cols()
    n_feat = len(cols)
    out: Dict[str, np.ndarray] = {
        res: np.zeros((n, int(window_len), n_feat), dtype=np.float32)
        for res in FUSION_INPUT_RESOLUTIONS
    }
    for i, t in enumerate(decision_times):
        for res in FUSION_INPUT_RESOLUTIONS:
            feat = featured_by_tf[res]
            window = encode_tf_window(
                feat,
                pd.Timestamp(t),
                resolution=res,
                window_len=window_len,
                featured=feat,
                zscore=zscore,
            )
            out[res][i] = window
    return out


# Re-export so tests can assert 15m is not in the fusion input contract.
NATIVE_ONLY_FEATURE_COLS = FEATURE_COLS
