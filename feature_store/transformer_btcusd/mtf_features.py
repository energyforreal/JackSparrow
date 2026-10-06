"""Per-timeframe pattern encodings for the fused multi-TF model.

Each TF is featured on its *native* grid. Resampled HTF structure is never
added; 10m/30m/1h/2h representations come from independently sampled OHLCV.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from feature_store.pattern_features import (
    CANDLESTICK_FEATURES,
    CHART_PATTERN_FEATURES,
    CandlestickPatternEngine,
    ChartPatternEngine,
)
from feature_store.transformer_btcusd.contract import (
    CANDLE_CLASS_CARDINALITY,
    CANDLE_CLASS_COL,
    CHART_PATTERN_CARDINALITY,
    CHART_PATTERN_COL,
    FEATURE_COLS,
    FEATURE_CONTRACT_VERSION_V11,
    FUSION_INPUT_RESOLUTIONS,
    RESOLUTION_MINUTES,
    V14_COUNT_COLS,
    V14_STRUCTURE_LOOKBACK_BARS,
    fusion_feature_cols_v14,
    fusion_native_feature_cols,
    fusion_window_len,
    resolve_fusion_window_lens,
    scale_period,
)
from feature_store.transformer_btcusd.features import add_features, assemble_raw_frame
from feature_store.transformer_btcusd.inference import zscore_window
from feature_store.transformer_btcusd.mtf_frames import (
    bar_close_time,
    last_n_closed_bars,
    normalize_mtf_frames,
)


def fusion_feature_cols() -> Tuple[str, ...]:
    """Continuous columns in each TF window (native TA + pattern engines)."""
    return fusion_native_feature_cols() + tuple(CANDLESTICK_FEATURES) + tuple(
        CHART_PATTERN_FEATURES
    )


def fusion_feature_fingerprint() -> str:
    """Stable hash of fusion feature names for dataset-cache invalidation."""
    blob = "\0".join(fusion_feature_cols()).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def fusion_feature_fingerprint_v14() -> str:
    """Stable hash of the v14 continuous column list."""
    blob = "\0".join(fusion_feature_cols_v14()).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def featured_cache_manifest() -> Dict[str, Any]:
    """Identity for cached native-TF featured frames (independent of stride)."""
    cols = list(fusion_feature_cols())
    return {
        "feature_contract_version": FEATURE_CONTRACT_VERSION_V11,
        "n_features": len(cols),
        "feature_fingerprint": fusion_feature_fingerprint(),
    }


def try_load_featured_frames(cache_dir: Path) -> Optional[Dict[str, pd.DataFrame]]:
    """Load featured_{tf}.parquet when featured_manifest.json matches."""
    root = Path(cache_dir)
    man_path = root / "featured_manifest.json"
    if not man_path.is_file():
        return None
    try:
        stored = json.loads(man_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    expected = featured_cache_manifest()
    for key, value in expected.items():
        if stored.get(key) != value:
            return None
    out: Dict[str, pd.DataFrame] = {}
    for res in FUSION_INPUT_RESOLUTIONS:
        path = root / f"featured_{res}.parquet"
        if not path.is_file():
            return None
        out[str(res)] = pd.read_parquet(path)
    return out


def save_featured_frames(
    cache_dir: Path,
    featured: Mapping[str, pd.DataFrame],
) -> None:
    """Write featured parquets plus featured_manifest.json."""
    root = Path(cache_dir)
    root.mkdir(parents=True, exist_ok=True)
    for res in FUSION_INPUT_RESOLUTIONS:
        frame = featured.get(res)
        if frame is None:
            raise KeyError(f"Missing featured frame for {res}")
        frame.to_parquet(root / f"featured_{res}.parquet", index=False)
    (root / "featured_manifest.json").write_text(
        json.dumps(featured_cache_manifest(), indent=2),
        encoding="utf-8",
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
    extra = pd.concat([cdl, chart], axis=1)
    extra = extra.loc[:, ~extra.columns.duplicated()]
    overlap = [c for c in extra.columns if c in feat.columns]
    if overlap:
        extra = extra.drop(columns=overlap)
    if not extra.empty:
        feat = pd.concat([feat, extra], axis=1)
    missing = [c for c in fusion_feature_cols() if c not in feat.columns]
    if missing:
        zeros = pd.DataFrame(0.0, index=feat.index, columns=missing)
        feat = pd.concat([feat, zeros], axis=1)
    if CANDLE_CLASS_COL not in feat.columns:
        feat[CANDLE_CLASS_COL] = 0
    if CHART_PATTERN_COL not in feat.columns:
        feat[CHART_PATTERN_COL] = 0
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
    window_len: Optional[int] = None,
    funding_df: Optional[pd.DataFrame] = None,
    oi_df: Optional[pd.DataFrame] = None,
    featured: Optional[pd.DataFrame] = None,
    zscore: bool = True,
) -> np.ndarray:
    """Native closed-bar window for one TF at decision time T (closed bars only)."""
    minutes = int(RESOLUTION_MINUTES[str(resolution).strip().lower()])
    width = (
        int(window_len)
        if window_len is not None
        else fusion_window_len(str(resolution))
    )
    if featured is None:
        closed = last_n_closed_bars(
            tf_df,
            decision_time,
            resolution_minutes=minutes,
            window_len=max(int(width) * 4, 256),
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
            window_len=int(width),
        )
    else:
        featured = last_n_closed_bars(
            featured,
            decision_time,
            resolution_minutes=minutes,
            window_len=int(width),
        )
    cols = fusion_feature_cols()
    window = _window_matrix(featured, cols=cols, window_len=int(width))
    if zscore:
        window = zscore_window(window)
    return window


def encode_all_tf_windows(
    frames: Mapping[str, pd.DataFrame],
    decision_time: pd.Timestamp,
    *,
    window_len: Optional[int] = None,
    window_lens: Optional[Mapping[str, int]] = None,
    funding_df: Optional[pd.DataFrame] = None,
    oi_df: Optional[pd.DataFrame] = None,
    featured_by_tf: Optional[Mapping[str, pd.DataFrame]] = None,
    zscore: bool = True,
) -> Dict[str, np.ndarray]:
    """Independent Z-ready windows for 5m/10m/30m/1h/2h at time T."""
    normalized = normalize_mtf_frames(frames)
    lens = resolve_fusion_window_lens(window_lens, window_len)
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
            window_len=int(lens[res]),
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
    """Stack TF windows as (n_tf, window_len, n_features) in fusion order.

    Requires equal (window, feat) shapes. Per-TF equal-span windows differ in
    bar count, so callers should keep a dict or list instead of stacking.
    """
    mats: List[np.ndarray] = []
    for res in FUSION_INPUT_RESOLUTIONS:
        if res not in windows:
            raise KeyError(f"Missing window for {res}")
        mats.append(np.asarray(windows[res], dtype=np.float32))
    shapes = {tuple(mat.shape) for mat in mats}
    if len(shapes) != 1:
        raise ValueError(
            "stack_tf_windows requires equal window shapes; got "
            + ", ".join(
                f"{res}={tuple(mat.shape)}"
                for res, mat in zip(FUSION_INPUT_RESOLUTIONS, mats)
            )
        )
    return np.stack(mats, axis=0)


_FUSION_WINDOW_CHUNK = 4096
_V14_ATR_CLIP = 8.0
_V14_EPS = 1e-9


def scale_v14_feature_window(
    window: np.ndarray,
    *,
    feature_cols: Sequence[str],
    atr: Optional[np.ndarray] = None,
    resolution_minutes: int,
    zscore_returns: bool = True,
) -> np.ndarray:
    """Channel-specific scale for a (T, F) or (N, T, F) v14 window.

    RSI and ADX keep level via affine maps. MACD is ATR-normalized. Counts are
    divided by the structure lookback. ``ret_1`` is z-scored over time.
    Remaining columns pass through. Id sequences are not in this matrix.
    """
    out = np.array(window, dtype=np.float32, copy=True)
    cols = [str(c) for c in feature_cols]
    idx = {name: i for i, name in enumerate(cols)}
    if "rsi_14" in idx:
        out[..., idx["rsi_14"]] = (out[..., idx["rsi_14"]] - 50.0) / 50.0
    if "adx_14" in idx:
        out[..., idx["adx_14"]] = out[..., idx["adx_14"]] / 100.0
    if "macd_hist" in idx:
        if atr is None:
            atr_safe = np.ones(out.shape[:-1], dtype=np.float32)
        else:
            atr_arr = np.asarray(atr, dtype=np.float32)
            if atr_arr.ndim == out.ndim:
                atr_arr = np.squeeze(atr_arr, axis=-1)
            if atr_arr.shape != out.shape[:-1]:
                atr_arr = np.reshape(atr_arr, out.shape[:-1])
            atr_safe = np.maximum(np.abs(atr_arr), _V14_EPS)
        scaled = out[..., idx["macd_hist"]] / atr_safe
        out[..., idx["macd_hist"]] = np.clip(
            scaled, -_V14_ATR_CLIP, _V14_ATR_CLIP
        )
    lookback = float(scale_period(V14_STRUCTURE_LOOKBACK_BARS, resolution_minutes))
    lookback = max(lookback, 1.0)
    for col in V14_COUNT_COLS:
        if col in idx:
            out[..., idx[col]] = out[..., idx[col]] / lookback
    if zscore_returns and "ret_1" in idx:
        i = idx["ret_1"]
        ret = out[..., i]
        time_axis = 1 if out.ndim == 3 else 0
        mu = ret.mean(axis=time_axis, keepdims=True)
        sd = ret.std(axis=time_axis, keepdims=True) + 1e-6
        out[..., i] = (ret - mu) / sd
    return out


def _id_window_vector(
    feat_df: pd.DataFrame,
    *,
    col: str,
    window_len: int,
    max_id: int,
) -> np.ndarray:
    width = int(window_len)
    if col not in feat_df.columns:
        return np.zeros((width,), dtype=np.int64)
    values = pd.to_numeric(feat_df[col], errors="coerce").fillna(0).to_numpy()
    values = np.clip(values.astype(np.int64, copy=False), 0, int(max_id))
    if len(values) < width:
        pad = np.zeros((width - len(values),), dtype=np.int64)
        values = np.concatenate([pad, values]) if len(values) else pad
    else:
        values = values[-width:]
    return values.astype(np.int64, copy=False)


def encode_tf_window_v14(
    tf_df: pd.DataFrame,
    decision_time: pd.Timestamp,
    *,
    resolution: str,
    window_len: Optional[int] = None,
    funding_df: Optional[pd.DataFrame] = None,
    oi_df: Optional[pd.DataFrame] = None,
    featured: Optional[pd.DataFrame] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """v14 closed-bar window: scaled floats plus candle and chart ids."""
    minutes = int(RESOLUTION_MINUTES[str(resolution).strip().lower()])
    width = (
        int(window_len)
        if window_len is not None
        else fusion_window_len(str(resolution))
    )
    if featured is None:
        closed = last_n_closed_bars(
            tf_df,
            decision_time,
            resolution_minutes=minutes,
            window_len=max(int(width) * 4, 256),
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
            window_len=int(width),
        )
    else:
        featured = last_n_closed_bars(
            featured,
            decision_time,
            resolution_minutes=minutes,
            window_len=int(width),
        )
    cols = list(fusion_feature_cols_v14())
    window = _window_matrix(featured, cols=cols, window_len=int(width))
    if "atr" in featured.columns:
        atr = _window_matrix(featured, cols=("atr",), window_len=int(width))
        atr = atr[:, 0]
    else:
        atr = np.ones((int(width),), dtype=np.float32)
    scaled = scale_v14_feature_window(
        window,
        feature_cols=cols,
        atr=atr,
        resolution_minutes=minutes,
        zscore_returns=True,
    )
    candle_ids = _id_window_vector(
        featured,
        col=CANDLE_CLASS_COL,
        window_len=int(width),
        max_id=CANDLE_CLASS_CARDINALITY - 1,
    )
    chart_ids = _id_window_vector(
        featured,
        col=CHART_PATTERN_COL,
        window_len=int(width),
        max_id=CHART_PATTERN_CARDINALITY - 1,
    )
    return scaled, candle_ids, chart_ids


def _open_fusion_id_memmap(
    memmap_dir: Path,
    *,
    kind: str,
    resolution: str,
    shape: Tuple[int, int],
) -> np.ndarray:
    dest = Path(memmap_dir)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"windows_{kind}_{resolution}.npy"
    if path.exists():
        path.unlink()
    return np.lib.format.open_memmap(path, mode="w+", dtype=np.int64, shape=shape)


def _zscore_ret1_windows(mat: np.ndarray, ret_index: int) -> np.ndarray:
    """Per-window z-score of the ``ret_1`` column only."""
    ret = mat[:, :, ret_index]
    mu = ret.mean(axis=1, keepdims=True)
    sd = ret.std(axis=1, keepdims=True) + 1e-6
    mat[:, :, ret_index] = (ret - mu) / sd
    return mat


def collect_training_windows_v14(
    featured_by_tf: Mapping[str, pd.DataFrame],
    decision_times: Sequence[pd.Timestamp],
    *,
    window_len: Optional[int] = None,
    window_lens: Optional[Mapping[str, int]] = None,
    memmap_dir: Optional[Path] = None,
) -> Tuple[Dict[str, np.ndarray], Dict[str, np.ndarray], Dict[str, np.ndarray]]:
    """Build v14 (n, window, feat) arrays plus int64 id windows per TF."""
    n = len(decision_times)
    cols = list(fusion_feature_cols_v14())
    lens = resolve_fusion_window_lens(window_lens, window_len)
    decisions = pd.to_datetime(pd.Index(list(decision_times)), utc=True)
    dec_ns = decisions.asi8
    out: Dict[str, np.ndarray] = {}
    candle_out: Dict[str, np.ndarray] = {}
    chart_out: Dict[str, np.ndarray] = {}
    mmap_root = Path(memmap_dir) if memmap_dir is not None else None
    for res in FUSION_INPUT_RESOLUTIONS:
        if res not in featured_by_tf:
            raise KeyError(f"Missing featured frame for {res}")
        width = int(lens[res])
        shape = (int(n), width, len(cols))
        id_shape = (int(n), width)
        if mmap_root is not None:
            mat = _open_fusion_window_memmap(mmap_root, str(res), shape)
            candle_mat = _open_fusion_id_memmap(
                mmap_root, kind="candle", resolution=str(res), shape=id_shape
            )
            chart_mat = _open_fusion_id_memmap(
                mmap_root, kind="chart", resolution=str(res), shape=id_shape
            )
        else:
            mat = np.zeros(shape, dtype=np.float32)
            candle_mat = np.zeros(id_shape, dtype=np.int64)
            chart_mat = np.zeros(id_shape, dtype=np.int64)
        feat = featured_by_tf[res]
        minutes = int(RESOLUTION_MINUTES[str(res).strip().lower()])
        if feat is None or feat.empty or "time" not in feat.columns:
            out[res] = mat
            candle_out[res] = candle_mat
            chart_out[res] = chart_mat
            continue
        missing = [c for c in cols if c not in feat.columns]
        frame = feat
        if missing:
            zeros = pd.DataFrame(0.0, index=feat.index, columns=missing)
            frame = pd.concat([feat, zeros], axis=1)
        close_ns = pd.DatetimeIndex(
            pd.to_datetime(bar_close_time(frame["time"], minutes), utc=True)
        ).asi8
        values = frame.loc[:, cols].to_numpy(dtype=np.float64)
        values = np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)
        values = values.astype(np.float32, copy=False)
        if "atr" in frame.columns:
            atr_col = frame["atr"].to_numpy(dtype=np.float64)
            atr_col = np.nan_to_num(atr_col, nan=1.0, posinf=1.0, neginf=1.0)
        else:
            atr_col = np.ones((len(frame),), dtype=np.float64)
        atr_vals = atr_col.astype(np.float32, copy=False).reshape(-1, 1)
        cdl_series = (
            pd.to_numeric(frame[CANDLE_CLASS_COL], errors="coerce").fillna(0)
            if CANDLE_CLASS_COL in frame.columns
            else pd.Series(0, index=frame.index)
        )
        chp_series = (
            pd.to_numeric(frame[CHART_PATTERN_COL], errors="coerce").fillna(0)
            if CHART_PATTERN_COL in frame.columns
            else pd.Series(0, index=frame.index)
        )
        cdl_vals = np.clip(
            cdl_series.to_numpy(dtype=np.int64), 0, CANDLE_CLASS_CARDINALITY - 1
        ).reshape(-1, 1).astype(np.float32)
        chp_vals = np.clip(
            chp_series.to_numpy(dtype=np.int64), 0, CHART_PATTERN_CARDINALITY - 1
        ).reshape(-1, 1).astype(np.float32)
        order = np.argsort(close_ns, kind="mergesort")
        close_sorted = close_ns[order]
        values = values[order]
        atr_vals = atr_vals[order]
        cdl_vals = cdl_vals[order]
        chp_vals = chp_vals[order]
        end_idx = np.searchsorted(close_sorted, dec_ns, side="right") - 1
        _gather_windows(values, end_idx, width, out=mat)
        atr_buf = np.zeros((int(n), width, 1), dtype=np.float32)
        _gather_windows(atr_vals, end_idx, width, out=atr_buf)
        atr_buf[atr_buf <= 0] = 1.0
        n_samples = int(mat.shape[0])
        for start in range(0, n_samples, _FUSION_WINDOW_CHUNK):
            stop = min(start + _FUSION_WINDOW_CHUNK, n_samples)
            sl = np.array(mat[start:stop], dtype=np.float32, copy=True)
            atr_sl = atr_buf[start:stop, :, 0]
            sl = scale_v14_feature_window(
                sl,
                feature_cols=cols,
                atr=atr_sl,
                resolution_minutes=minutes,
                zscore_returns=True,
            )
            mat[start:stop] = sl
        cdl_buf = np.zeros((int(n), width, 1), dtype=np.float32)
        chp_buf = np.zeros((int(n), width, 1), dtype=np.float32)
        _gather_windows(cdl_vals, end_idx, width, out=cdl_buf)
        _gather_windows(chp_vals, end_idx, width, out=chp_buf)
        candle_mat[:] = np.clip(
            np.rint(cdl_buf[:, :, 0]), 0, CANDLE_CLASS_CARDINALITY - 1
        ).astype(np.int64)
        chart_mat[:] = np.clip(
            np.rint(chp_buf[:, :, 0]), 0, CHART_PATTERN_CARDINALITY - 1
        ).astype(np.int64)
        del values, atr_vals, atr_buf, cdl_vals, chp_vals, cdl_buf, chp_buf
        if mmap_root is not None:
            mat.flush()
            candle_mat.flush()
            chart_mat.flush()
        out[res] = mat
        candle_out[res] = candle_mat
        chart_out[res] = chart_mat
    return out, candle_out, chart_out


def _zscore_windows(mat: np.ndarray) -> np.ndarray:
    """In-place per-window z-score over time. Matches ``zscore_window``."""
    mu = mat.mean(axis=1, keepdims=True)
    sd = mat.std(axis=1, keepdims=True) + 1e-6
    np.subtract(mat, mu, out=mat)
    np.divide(mat, sd, out=mat)
    return mat


def _zscore_windows_chunked(
    mat: np.ndarray,
    *,
    chunk_size: int = _FUSION_WINDOW_CHUNK,
) -> np.ndarray:
    """Z-score in sample chunks so a memmap is not pulled fully into RAM."""
    n = int(mat.shape[0])
    cs = max(int(chunk_size), 1)
    for start in range(0, n, cs):
        stop = min(start + cs, n)
        sl = np.array(mat[start:stop], dtype=np.float32, copy=True)
        _zscore_windows(sl)
        mat[start:stop] = sl
    return mat


def _open_fusion_window_memmap(
    memmap_dir: Path,
    resolution: str,
    shape: Tuple[int, int, int],
) -> np.ndarray:
    """Create a float32 .npy memmap for one TF's training windows."""
    dest = Path(memmap_dir)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"windows_{resolution}.npy"
    if path.exists():
        path.unlink()
    return np.lib.format.open_memmap(path, mode="w+", dtype=np.float32, shape=shape)


def _gather_windows(
    values: np.ndarray,
    end_idx: np.ndarray,
    window_len: int,
    *,
    out: Optional[np.ndarray] = None,
    chunk_size: int = _FUSION_WINDOW_CHUNK,
) -> np.ndarray:
    """Slice ``window_len`` rows ending at each inclusive ``end_idx`` (pad left).

    ``end_idx == -1`` means no closed bar yet and the row stays zeros.
    Fancy-index gathers run in chunks so peak RAM stays near one chunk.
    """
    n_samples = int(end_idx.shape[0])
    n_feat = int(values.shape[1]) if values.size else 0
    width = int(window_len)
    if out is None:
        out = np.zeros((n_samples, width, n_feat), dtype=np.float32)
    elif tuple(out.shape) != (n_samples, width, n_feat):
        raise ValueError(f"out shape {out.shape} != {(n_samples, width, n_feat)}")
    if values.size == 0 or n_feat == 0:
        return out
    n_bars = int(values.shape[0])
    cs = max(int(chunk_size), 1)
    for start in range(0, n_samples, cs):
        stop = min(start + cs, n_samples)
        out[start:stop] = 0
        idx = end_idx[start:stop]
        valid = (idx >= 0) & (idx < n_bars)
        full = valid & (idx >= width - 1)
        if np.any(full):
            ends = idx[full].astype(np.int64, copy=False)
            starts = ends - width + 1
            offsets = starts[:, None] + np.arange(width, dtype=np.int64)[None, :]
            dest = np.flatnonzero(full) + start
            out[dest] = values[offsets]
        for i in np.flatnonzero(valid & ~full):
            end = int(idx[i]) + 1
            sl = values[:end]
            out[start + int(i), width - len(sl) :, :] = sl
    return out


def collect_training_windows(
    featured_by_tf: Mapping[str, pd.DataFrame],
    decision_times: Sequence[pd.Timestamp],
    *,
    window_len: Optional[int] = None,
    window_lens: Optional[Mapping[str, int]] = None,
    zscore: bool = True,
    memmap_dir: Optional[Path] = None,
) -> Dict[str, np.ndarray]:
    """Build (n, window, feat) arrays per TF. Decision times are 5m closes.

    Uses ``searchsorted`` on bar close times so each TF is scanned once.
    Semantics match ``encode_tf_window(..., featured=frame)``.
    Each TF keeps its own ``window_lens[res]``; arrays are not padded to a
    shared max length.

    When ``memmap_dir`` is set, each TF array is a float32 memmap on disk so
    Colab does not hold five full window tensors in RAM.
    """
    n = len(decision_times)
    cols = list(fusion_feature_cols())
    lens = resolve_fusion_window_lens(window_lens, window_len)
    decisions = pd.to_datetime(pd.Index(list(decision_times)), utc=True)
    dec_ns = decisions.asi8
    out: Dict[str, np.ndarray] = {}
    mmap_root = Path(memmap_dir) if memmap_dir is not None else None
    for res in FUSION_INPUT_RESOLUTIONS:
        if res not in featured_by_tf:
            raise KeyError(f"Missing featured frame for {res}")
        width = int(lens[res])
        shape = (int(n), width, len(cols))
        if mmap_root is not None:
            mat = _open_fusion_window_memmap(mmap_root, str(res), shape)
        else:
            mat = np.zeros(shape, dtype=np.float32)
        feat = featured_by_tf[res]
        minutes = int(RESOLUTION_MINUTES[str(res).strip().lower()])
        if feat is None or feat.empty or "time" not in feat.columns:
            out[res] = mat
            continue
        missing = [c for c in cols if c not in feat.columns]
        frame = feat
        if missing:
            zeros = pd.DataFrame(0.0, index=feat.index, columns=missing)
            frame = pd.concat([feat, zeros], axis=1)
        close_ns = pd.DatetimeIndex(
            pd.to_datetime(bar_close_time(frame["time"], minutes), utc=True)
        ).asi8
        values = frame.loc[:, cols].to_numpy(dtype=np.float64)
        values = np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)
        values = values.astype(np.float32, copy=False)
        order = np.argsort(close_ns, kind="mergesort")
        close_sorted = close_ns[order]
        values = values[order]
        end_idx = np.searchsorted(close_sorted, dec_ns, side="right") - 1
        _gather_windows(values, end_idx, width, out=mat)
        del values
        if zscore:
            _zscore_windows_chunked(mat)
        if mmap_root is not None:
            mat.flush()
        out[res] = mat
    return out


# Re-export so tests can assert 15m is not in the fusion input contract.
NATIVE_ONLY_FEATURE_COLS = FEATURE_COLS
