"""Tests that fusion encodings stay native-TF and omit resampled HTF columns."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from feature_store.transformer_btcusd.contract import (
    FUSION_INPUT_RESOLUTIONS,
    RESOLUTION_MINUTES,
)
from feature_store.transformer_btcusd.mtf_features import (
    collect_training_windows,
    encode_tf_window,
    fusion_feature_cols,
)
from feature_store.transformer_btcusd.mtf_frames import bar_close_time
from scripts.colab.mtf_fusion_research import leakage_audit


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
    with pytest.raises(RuntimeError, match="h10m_dir"):
        leakage_audit(cols + ["h10m_dir"])
    with pytest.raises(RuntimeError, match="htf_"):
        leakage_audit(cols + ["htf_structure_bias"])


def _toy_featured(resolution: str, n_bars: int) -> pd.DataFrame:
    minutes = int(RESOLUTION_MINUTES[resolution])
    times = pd.date_range("2024-01-01", periods=n_bars, freq=f"{minutes}min", tz="UTC")
    cols = list(fusion_feature_cols())
    ramp = np.linspace(0.0, 1.0, n_bars, dtype=np.float64)
    data = {name: ramp + (idx * 0.01) for idx, name in enumerate(cols)}
    data["time"] = times
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
