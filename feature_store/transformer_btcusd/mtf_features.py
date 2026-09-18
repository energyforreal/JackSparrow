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
    CANDLE_CLASS_COL,
    FEATURE_COLS,
    FEATURE_CONTRACT_VERSION_V11,
    FUSION_INPUT_RESOLUTIONS,
    RESOLUTION_MINUTES,
    fusion_native_feature_cols,
    fusion_window_len,
    resolve_fusion_window_lens,
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
