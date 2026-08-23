"""Tests that fusion encodings stay native-TF and omit resampled HTF columns."""

from __future__ import annotations

from feature_store.transformer_btcusd.mtf_features import fusion_feature_cols


def test_fusion_feature_cols_omit_htf_and_15m() -> None:
    cols = fusion_feature_cols()
    assert cols
    assert all(not name.startswith("htf_") for name in cols)
    joined = " ".join(cols)
    assert "15m" not in joined
    assert "cdl_doji" in cols
    assert "sr_support_dist_pct" in cols
