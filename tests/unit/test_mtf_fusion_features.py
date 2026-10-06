"""Tests that fusion encodings stay native-TF and omit resampled HTF columns."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from feature_store.transformer_btcusd.contract import (
    CANDLE_CLASS_COL,
    CHART_PATTERN_COL,
    FEATURE_COLS,
    FUSION_INPUT_RESOLUTIONS,
    FUSION_TARGET_WINDOW_MINUTES,
    RESOLUTION_MINUTES,
    V14_DROPPED_COLS,
    fusion_feature_groups_v14,
    fusion_window_len,
    fusion_window_lens,
)
from feature_store.transformer_btcusd.mtf_features import (
    collect_training_windows,
    collect_training_windows_v14,
    encode_tf_window,
    encode_tf_window_v14,
    fusion_feature_cols,
    fusion_feature_cols_v14,
    save_featured_frames,
    scale_v14_feature_window,
    stack_tf_windows,
    try_load_featured_frames,
)
from feature_store.transformer_btcusd.mtf_frames import bar_close_time
from scripts.colab.mtf_fusion_research import (
    build_dataset_from_ohlcv,
    leakage_audit,
    save_fusion_dataset_cache,
    try_load_fusion_dataset_cache,
)


def test_fusion_feature_cols_omit_htf_and_15m() -> None:
    cols = fusion_feature_cols()
    assert cols
    assert all(not name.startswith("htf_") for name in cols)
    joined = " ".join(cols)
    assert "15m" not in joined
    assert "cdl_doji" in cols
    assert "sr_support_dist_pct" in cols


def test_leakage_audit_allows_causal_swing_dir() -> None:
    cols = list(fusion_feature_cols())
    assert "last_swing_dir" in cols
    leakage_audit(cols)


def test_leakage_audit_rejects_horizon_and_htf() -> None:
    cols = list(fusion_feature_cols())
    with pytest.raises(RuntimeError, match="h30m_dir"):
        leakage_audit(cols + ["h30m_dir"])
    with pytest.raises(RuntimeError, match="htf_"):
        leakage_audit(cols + ["htf_structure_bias"])


def _toy_featured(resolution: str, n_bars: int) -> pd.DataFrame:
    minutes = int(RESOLUTION_MINUTES[resolution])
    times = pd.date_range("2024-01-01", periods=n_bars, freq=f"{minutes}min", tz="UTC")
    cols = list(fusion_feature_cols())
    ramp = np.linspace(0.0, 1.0, n_bars, dtype=np.float64)
    data = {name: ramp + (idx * 0.01) for idx, name in enumerate(cols)}
    data["time"] = times
    data["atr"] = np.full(n_bars, 2.0, dtype=np.float64)
    data[CANDLE_CLASS_COL] = np.arange(n_bars, dtype=np.int64) % 13
    data[CHART_PATTERN_COL] = np.arange(n_bars, dtype=np.int64) % 9
    return pd.DataFrame(data)


def test_collect_training_windows_matches_encode_tf_window() -> None:
    featured = {res: _toy_featured(res, 48) for res in FUSION_INPUT_RESOLUTIONS}
    closes = bar_close_time(featured["5m"]["time"], 5)
    decisions = list(closes.iloc[20:24])
    batched = collect_training_windows(
        featured, decisions, window_len=8, zscore=True
    )
    for res, mat in batched.items():
        assert mat.shape == (4, 8, len(fusion_feature_cols()))
        for i, t in enumerate(decisions):
            ref = encode_tf_window(
                featured[res],
                pd.Timestamp(t),
                resolution=res,
                window_len=8,
                featured=featured[res],
                zscore=True,
            )
            np.testing.assert_allclose(mat[i], ref, rtol=1e-5, atol=1e-5)


def test_collect_training_windows_pads_short_history() -> None:
    featured = {res: _toy_featured(res, 3) for res in FUSION_INPUT_RESOLUTIONS}
    t = bar_close_time(featured["5m"]["time"], 5).iloc[-1]
    batched = collect_training_windows(
        featured, [t], window_len=8, zscore=False
    )
    ref = encode_tf_window(
        featured["5m"],
        pd.Timestamp(t),
        resolution="5m",
        window_len=8,
        featured=featured["5m"],
        zscore=False,
    )
    np.testing.assert_allclose(batched["5m"][0], ref, rtol=1e-5, atol=1e-5)
    assert np.all(batched["5m"][0, :5] == 0.0)


def test_collect_training_windows_memmap_matches_ram(tmp_path) -> None:
    featured = {res: _toy_featured(res, 48) for res in FUSION_INPUT_RESOLUTIONS}
    closes = bar_close_time(featured["5m"]["time"], 5)
    decisions = list(closes.iloc[20:28])
    ram = collect_training_windows(
        featured, decisions, window_len=8, zscore=True
    )
    mapped = collect_training_windows(
        featured,
        decisions,
        window_len=8,
        zscore=True,
        memmap_dir=tmp_path,
    )
    for res in FUSION_INPUT_RESOLUTIONS:
        np.testing.assert_allclose(mapped[res], ram[res], rtol=1e-5, atol=1e-5)
        assert (tmp_path / f"windows_{res}.npy").is_file()


def test_featured_cache_roundtrip(tmp_path) -> None:
    featured = {res: _toy_featured(res, 12) for res in FUSION_INPUT_RESOLUTIONS}
    save_featured_frames(tmp_path, featured)
    loaded = try_load_featured_frames(tmp_path)
    assert loaded is not None
    for res in FUSION_INPUT_RESOLUTIONS:
        pd.testing.assert_frame_equal(
            loaded[res].reset_index(drop=True),
            featured[res].reset_index(drop=True),
            check_dtype=False,
        )


def test_window_dataset_cache_roundtrip(tmp_path) -> None:
    featured = {res: _toy_featured(res, 48) for res in FUSION_INPUT_RESOLUTIONS}
    closes = bar_close_time(featured["5m"]["time"], 5)
    decisions = list(closes.iloc[20:28])
    windows, candle_ids, chart_ids = collect_training_windows_v14(
        featured,
        decisions,
        window_len=8,
        memmap_dir=tmp_path,
    )
    labels = np.zeros((len(decisions), 3), dtype=np.int64)
    times = pd.Series(pd.to_datetime(decisions, utc=True))
    save_fusion_dataset_cache(
        tmp_path, labels=labels, decision_times=times, window_len=8, stride=4
    )
    loaded = try_load_fusion_dataset_cache(tmp_path, window_len=8, stride=4)
    assert loaded is not None
    cached_w, cached_y, cached_t, cached_cdl, cached_chp = loaded
    from scripts.colab.mtf_fusion_model import FusionTrainLabels

    assert isinstance(cached_y, FusionTrainLabels)
    np.testing.assert_array_equal(cached_y.direction, labels)
    assert len(cached_t) == len(decisions)
    for res in FUSION_INPUT_RESOLUTIONS:
        np.testing.assert_allclose(cached_w[res], windows[res], rtol=1e-5, atol=1e-5)
        np.testing.assert_array_equal(cached_cdl[res], candle_ids[res])
        np.testing.assert_array_equal(cached_chp[res], chart_ids[res])
    miss = try_load_fusion_dataset_cache(tmp_path, window_len=8, stride=8)
    assert miss is None


def test_build_dataset_cache_hit_skips_featuring(tmp_path, monkeypatch) -> None:
    calls = {"n": 0}

    def fake_precompute(frames, **kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        n_bars = len(frames["5m"])
        return {res: _toy_featured(res, n_bars) for res in FUSION_INPUT_RESOLUTIONS}

    monkeypatch.setattr(
        "scripts.colab.mtf_fusion_research.precompute_featured_frames",
        fake_precompute,
    )
    n = 80
    times = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    close = 100.0 + np.linspace(0.0, 20.0, n)
    df5 = pd.DataFrame(
        {
            "time": times,
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1.0,
        }
    )
    frames = {"5m": df5}
    first = build_dataset_from_ohlcv(
        frames, window_len=8, stride=4, memmap_dir=tmp_path
    )
    assert calls["n"] == 1
    second = build_dataset_from_ohlcv(
        frames, window_len=8, stride=4, memmap_dir=tmp_path
    )
    assert calls["n"] == 1
    from scripts.colab.mtf_fusion_model import FusionTrainLabels

    assert isinstance(first[1], FusionTrainLabels)
    np.testing.assert_array_equal(first[1].direction, second[1].direction)
    np.testing.assert_allclose(first[1].path, second[1].path, equal_nan=True)
    assert len(first[2]) == len(second[2])


def test_fusion_window_span_within_one_bar() -> None:
    target = FUSION_TARGET_WINDOW_MINUTES
    print("resolution  minutes/bar  window_len  span_min  err")
    for res in FUSION_INPUT_RESOLUTIONS:
        minutes = int(RESOLUTION_MINUTES[res])
        width = fusion_window_len(res)
        span = width * minutes
        err = span - target
        print(f"{res:10} {minutes:11d} {width:10d} {span:8d} {err:4d}")
        assert abs(err) <= minutes


def test_collect_training_windows_per_tf_lengths() -> None:
    lens = fusion_window_lens()
    featured = {
        res: _toy_featured(res, int(lens[res]) + 8) for res in FUSION_INPUT_RESOLUTIONS
    }
    t = bar_close_time(featured["5m"]["time"], 5).iloc[-1]
    batched = collect_training_windows(featured, [t], zscore=False)
    n_feat = len(fusion_feature_cols())
    for res, mat in batched.items():
        assert mat.shape == (1, int(lens[res]), n_feat)
        ref = encode_tf_window(
            featured[res],
            pd.Timestamp(t),
            resolution=res,
            window_len=int(lens[res]),
            featured=featured[res],
            zscore=False,
        )
        np.testing.assert_allclose(mat[0], ref, rtol=1e-5, atol=1e-5)


def test_stack_tf_windows_rejects_unequal_lengths() -> None:
    n_feat = len(fusion_feature_cols())
    windows = {
        res: np.zeros((fusion_window_len(res), n_feat), dtype=np.float32)
        for res in FUSION_INPUT_RESOLUTIONS
    }
    with pytest.raises(ValueError, match="equal window shapes"):
        stack_tf_windows(windows)


def test_fusion_feature_groups_uses_v14_disjoint_map() -> None:
    from scripts.colab.mtf_fusion_research import fusion_feature_groups

    cols = list(fusion_feature_cols_v14())
    groups = fusion_feature_groups(cols)
    assert groups["price"] == ["ret_1"]
    assert "rsi_14" in groups["momentum"]
    assert "adx_14" in groups["trend"]
    assert "vol_z" in groups["flow"]
    assert "hour_sin" in groups["context"]
    assert not any(name.startswith("cdl_") for names in groups.values() for name in names)


def test_v14_groups_are_disjoint_and_drop_duplicates() -> None:
    cols = fusion_feature_cols_v14()
    groups = fusion_feature_groups_v14()
    flat = [name for key in groups for name in groups[key]]
    assert tuple(flat) == cols
    assert len(cols) == len(set(cols))
    assert set(cols) == set(FEATURE_COLS) - set(V14_DROPPED_COLS)
    for dropped in V14_DROPPED_COLS:
        assert dropped not in cols
    joined = " ".join(cols)
    assert "cdl_" not in joined
    assert "chp_" not in joined
    assert "sr_" not in joined
    assert "tl_" not in joined
    assert "bo_" not in joined
    assert all(not name.startswith("htf_") for name in cols)
    assigned = {name: key for key, members in groups.items() for name in members}
    assert len(assigned) == len(cols)


def test_v14_scaler_keeps_passthrough_and_affine_rsi() -> None:
    cols = ["ret_1", "rsi_14", "vol_z", "hh_count"]
    window = np.array(
        [
            [0.1, 70.0, 1.5, 12.0],
            [0.2, 70.0, 1.5, 12.0],
            [0.3, 70.0, 1.5, 12.0],
            [0.4, 70.0, 1.5, 12.0],
        ],
        dtype=np.float32,
    )
    scaled = scale_v14_feature_window(
        window, feature_cols=cols, resolution_minutes=5, zscore_returns=True
    )
    np.testing.assert_allclose(scaled[:, 1], (70.0 - 50.0) / 50.0)
    np.testing.assert_allclose(scaled[:, 2], 1.5)
    assert abs(float(scaled[:, 0].mean())) < 1e-5
    lookback = 96.0
    np.testing.assert_allclose(scaled[:, 3], 12.0 / lookback)


def test_collect_v14_matches_encode_tf_window_v14() -> None:
    featured = {res: _toy_featured(res, 48) for res in FUSION_INPUT_RESOLUTIONS}
    closes = bar_close_time(featured["5m"]["time"], 5)
    decisions = list(closes.iloc[20:24])
    windows, candle_ids, chart_ids = collect_training_windows_v14(
        featured, decisions, window_len=8
    )
    n_feat = len(fusion_feature_cols_v14())
    for res, mat in windows.items():
        assert mat.shape == (4, 8, n_feat)
        for i, t in enumerate(decisions):
            feat, cdl, chp = encode_tf_window_v14(
                featured[res],
                pd.Timestamp(t),
                resolution=res,
                window_len=8,
                featured=featured[res],
            )
            np.testing.assert_allclose(mat[i], feat, rtol=1e-5, atol=1e-5)
            np.testing.assert_array_equal(candle_ids[res][i], cdl)
            np.testing.assert_array_equal(chart_ids[res][i], chp)
            assert feat.dtype == np.float32
            assert cdl.dtype == np.int64
            assert chp.dtype == np.int64
