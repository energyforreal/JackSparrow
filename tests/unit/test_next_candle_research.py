"""v9 multi-horizon 5m research: leakage, quality, labels, scaler, ablation hook."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import torch

from feature_store.transformer_btcusd.contract import (
    CHART_PATTERN_COL,
    FEATURE_CONTRACT_VERSION,
    FEATURE_CONTRACT_VERSION_V6,
    FEATURE_CONTRACT_VERSION_V8,
    HORIZON_BARS_5M,
    HORIZON_DIR_COLS,
    HORIZON_STRUCTURE_COLS,
    NEXT_BODY_COL,
    NEXT_DIRECTION_COL,
    NEXT_DIRECTION_NAMES,
    NEXT_RANGE_COL,
    NEXT_WICK_COL,
    ONNX_OUTPUT_NAMES,
    ONNX_OUTPUT_NAMES_V6,
    ONNX_OUTPUT_NAMES_V8,
    ONNX_OUTPUT_NAMES_V9,
    V8_CONTINUOUS_LABEL_COLS,
    ablation_feature_groups,
    default_research_config,
    onnx_output_names_for_contract,
    v9_feature_cols_for_resolution,
)
from feature_store.transformer_btcusd.features import add_features, assemble_raw_frame
from feature_store.transformer_btcusd.inference import (
    feature_config_from_training_export,
    require_onnx_output_names,
)
from feature_store.transformer_btcusd.labels import (
    compute_horizon_behavior_labels,
    compute_next_candle_structure_labels,
)
from feature_store.transformer_btcusd.structure import add_market_structure_features
from scripts.colab.next_candle_research import (
    apply_scaler,
    build_labeled_frame,
    chronological_split,
    fit_label_stats,
    fit_train_scaler,
    leakage_audit,
    ohlcv_quality_report,
    run_ablation_epoch,
    sanitize_feature_values,
    split_window_dict,
    windows_from_frame,
)


def _ohlcv(n: int = 240, freq: str = "5min", seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    close = 50000 + np.cumsum(rng.normal(0, 25, n))
    open_ = close + rng.normal(0, 10, n)
    high = np.maximum(open_, close) + rng.uniform(5, 30, n)
    low = np.minimum(open_, close) - rng.uniform(5, 30, n)
    return pd.DataFrame(
        {
            "time": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 100.0),
        }
    )


def test_ohlcv_quality_report_gappy_series() -> None:
    df = _ohlcv(40)
    df = pd.concat([df.iloc[:10], df.iloc[20:]], ignore_index=True)
    report = ohlcv_quality_report(df, "5m", min_completeness=0.0)
    assert report["rows"] == 30
    assert int(report["missing_candles"]) >= 1


def test_ohlcv_quality_report_rejects_invalid_ohlc() -> None:
    df = _ohlcv(20)
    df.loc[3, "high"] = df.loc[3, "low"] - 10.0
    with pytest.raises(ValueError, match="OHLCV quality failed"):
        ohlcv_quality_report(df, "5m", min_completeness=0.0)


def test_funding_ffill_does_not_backfill_future() -> None:
    ohlcv = _ohlcv(30)
    fund = pd.DataFrame(
        {
            "time": ohlcv["time"].iloc[-5:].reset_index(drop=True),
            "funding_rate": np.linspace(0.0001, 0.0002, 5),
        }
    )
    assembled = assemble_raw_frame(ohlcv, funding_df=fund)
    assert assembled["funding_rate"].iloc[:20].isna().all()
    assert assembled["funding_rate"].iloc[-5:].notna().all()


def test_leakage_audit_rejects_horizon_targets() -> None:
    cols = list(v9_feature_cols_for_resolution("5m"))
    leakage_audit(cols)
    assert "h10m_dir" not in cols
    assert "h5m_mfe" not in cols
    assert CHART_PATTERN_COL not in cols
    with pytest.raises(RuntimeError, match="Future/target"):
        leakage_audit(cols + ["h10m_dir"])


def test_scaler_mean_from_train_only() -> None:
    values = np.zeros((200, 3), dtype=np.float64)
    values[:140] = 1.0
    values[140:] = 100.0
    mean, std = fit_train_scaler(values[:140])
    assert mean[0] == pytest.approx(1.0)
    full_mean = np.nanmean(values, axis=0)
    assert mean[0] != pytest.approx(full_mean[0])
    scaled_test = apply_scaler(values[140:], mean, std)
    assert scaled_test[0, 0] > 10.0


def test_structure_bins_match_next_bar_ohlc() -> None:
    n = 80
    close = np.full(n, 50000.0)
    open_px = np.full(n, 50000.0)
    high = np.full(n, 50020.0)
    low = np.full(n, 49980.0)
    open_px[41] = 49900.0
    close[41] = 50150.0
    high[41] = 50160.0
    low[41] = 49890.0
    df = pd.DataFrame(
        {
            "open": open_px,
            "high": high,
            "low": low,
            "close": close,
            "atr": np.full(n, 40.0),
            "body_ratio": (close - open_px) / 40.0,
            "upper_wick_ratio": np.zeros(n),
            "lower_wick_ratio": np.zeros(n),
            "range_atr": (high - low) / 40.0,
            "vol_z": np.zeros(n),
            "breakout_vol_ratio": np.ones(n),
            CHART_PATTERN_COL: np.zeros(n, dtype=np.int64),
        }
    )
    labeled = compute_next_candle_structure_labels(
        df, path_label_horizon_bars=8, horizon_bars=(1, 3, 6, 12, 24), gate_chart_volume=False
    )
    assert int(labeled.loc[40, NEXT_DIRECTION_COL]) == 2
    assert int(labeled.loc[40, NEXT_BODY_COL]) == 2
    assert int(labeled.loc[40, NEXT_RANGE_COL]) == 2
    assert int(labeled.loc[40, NEXT_WICK_COL]) in (0, 1, 2, 3)


def test_horizon_h10m_is_two_bars() -> None:
    assert HORIZON_BARS_5M[1] == 2
    assert HORIZON_DIR_COLS[1] == "h10m_dir"
    assert HORIZON_BARS_5M == (1, 2, 3, 6, 12, 24)


def test_v6_onnx_names_unchanged_for_all_tf_trainer() -> None:
    v6_15m = onnx_output_names_for_contract(
        FEATURE_CONTRACT_VERSION_V6, resolution="15m"
    )
    v6_5m = onnx_output_names_for_contract(
        FEATURE_CONTRACT_VERSION_V6, resolution="5m"
    )
    assert v6_15m == ONNX_OUTPUT_NAMES_V6
    assert v6_5m == ONNX_OUTPUT_NAMES_V6
    v8_5m = onnx_output_names_for_contract(FEATURE_CONTRACT_VERSION_V8, resolution="5m")
    assert v8_5m == ONNX_OUTPUT_NAMES_V8
    assert "h10m_dir_logits" in v8_5m
    assert "chart_pattern_logits" not in v8_5m
    v9_5m = onnx_output_names_for_contract(FEATURE_CONTRACT_VERSION, resolution="5m")
    assert v9_5m == ONNX_OUTPUT_NAMES_V9
    assert "chart_pattern_logits" in v9_5m
    assert "next_direction_logits" not in v9_5m
    assert onnx_output_names_for_contract(
        FEATURE_CONTRACT_VERSION, resolution="15m"
    ) == ONNX_OUTPUT_NAMES_V6


def test_ablation_groups_keep_candle_chart_as_inputs() -> None:
    groups = ablation_feature_groups("5m")
    assert "body_ratio" in groups["B"]
    assert CHART_PATTERN_COL not in groups["E"]
    assert CHART_PATTERN_COL not in groups["F"]
    assert "peak_diff_atr" in groups["E"]
    assert "h10m_dir" not in groups["F"]
    assert "h5m_mfe" not in groups["F"]


def test_horizon_labels_depend_on_t_plus_1_to_k_only() -> None:
    n = 80
    close = np.full(n, 50000.0)
    df = pd.DataFrame(
        {
            "open": close - 5.0,
            "high": close + 10.0,
            "low": close - 10.0,
            "close": close,
            "atr": np.full(n, 20.0),
            "structure_bias": np.zeros(n),
            "failed_break": np.zeros(n),
            "bars_since_breakout": np.full(n, 99.0),
            "vol_z": np.zeros(n),
            "breakout_vol_ratio": np.ones(n),
        }
    )
    labeled = compute_horizon_behavior_labels(df)
    assert NEXT_DIRECTION_NAMES[int(labeled.loc[40, "h10m_dir"])] == "NEUTRAL"

    beyond = df.copy()
    beyond.loc[43, "close"] = 53000.0
    beyond.loc[43, "high"] = 53020.0
    labeled_beyond = compute_horizon_behavior_labels(beyond)
    assert NEXT_DIRECTION_NAMES[int(labeled_beyond.loc[40, "h10m_dir"])] == "NEUTRAL"

    inside = df.copy()
    inside.loc[42, "close"] = 53000.0
    inside.loc[42, "high"] = 53020.0
    labeled_inside = compute_horizon_behavior_labels(inside)
    assert NEXT_DIRECTION_NAMES[int(labeled_inside.loc[40, "h10m_dir"])] == "STRONG_UP"


def test_horizon_direction_bins_weak_and_strong_atr() -> None:
    n = 80
    close = np.full(n, 50000.0)
    atr = np.full(n, 20.0)
    df = pd.DataFrame(
        {
            "open": close - 5.0,
            "high": close + 10.0,
            "low": close - 10.0,
            "close": close,
            "atr": atr,
            "structure_bias": np.zeros(n),
            "failed_break": np.zeros(n),
            "bars_since_breakout": np.full(n, 99.0),
            "vol_z": np.zeros(n),
            "breakout_vol_ratio": np.ones(n),
        }
    )
    up = df.copy()
    up.loc[42, "close"] = 50000.0 + 20.0  # 1 ATR → UP
    labeled_up = compute_horizon_behavior_labels(up)
    assert NEXT_DIRECTION_NAMES[int(labeled_up.loc[40, "h10m_dir"])] == "UP"
    down = df.copy()
    down.loc[42, "close"] = 50000.0 - 20.0
    labeled_down = compute_horizon_behavior_labels(down)
    assert NEXT_DIRECTION_NAMES[int(labeled_down.loc[40, "h10m_dir"])] == "DOWN"


def test_h5m_vol_is_abs_log_return() -> None:
    n = 80
    close = np.full(n, 50000.0)
    close[41] = 50500.0
    df = pd.DataFrame(
        {
            "open": close - 5.0,
            "high": close + 10.0,
            "low": close - 10.0,
            "close": close,
            "atr": np.full(n, 20.0),
            "structure_bias": np.zeros(n),
            "failed_break": np.zeros(n),
            "bars_since_breakout": np.full(n, 99.0),
            "vol_z": np.zeros(n),
            "breakout_vol_ratio": np.ones(n),
        }
    )
    labeled = compute_horizon_behavior_labels(df)
    expected = abs(np.log(50500.0 / 50000.0))
    assert float(labeled.loc[40, "h5m_vol"]) == pytest.approx(expected)
    assert float(labeled.loc[42, "h5m_vol"]) != pytest.approx(expected)


def test_h2h_structure_ignores_mid_window_breakout() -> None:
    n = 80
    close = np.full(n, 50000.0)
    bars_bo = np.full(n, 99.0)
    bars_bo[50] = 0.0
    df = pd.DataFrame(
        {
            "open": close - 5.0,
            "high": close + 10.0,
            "low": close - 10.0,
            "close": close,
            "atr": np.full(n, 20.0),
            "structure_bias": np.zeros(n),
            "failed_break": np.zeros(n),
            "bars_since_breakout": bars_bo,
            "vol_z": np.zeros(n),
            "breakout_vol_ratio": np.ones(n),
        }
    )
    labeled = compute_horizon_behavior_labels(df)
    assert int(labeled.loc[40, "h2h_structure"]) != 3
    terminal = df.copy()
    terminal.loc[64, "bars_since_breakout"] = 0.0
    labeled_end = compute_horizon_behavior_labels(terminal)
    assert int(labeled_end.loc[40, "h2h_structure"]) == 3


def test_donchian_features_stay_causal_when_future_bar_moves() -> None:
    raw = _ohlcv(220, seed=3)
    feat = add_features(assemble_raw_frame(raw), resolution_minutes=5)
    t = 80
    raw2 = raw.copy()
    raw2.loc[t + 2, "high"] = float(raw2.loc[t + 2, "high"]) + 8000.0
    raw2.loc[t + 2, "close"] = float(raw2.loc[t + 2, "close"]) + 4000.0
    feat2 = add_features(assemble_raw_frame(raw2), resolution_minutes=5)
    for col in ("structure_bias", "hh_count", "dist_to_resistance_atr"):
        assert col in feat.columns
        np.testing.assert_allclose(
            float(feat.loc[t, col]),
            float(feat2.loc[t, col]),
            rtol=1e-8,
            atol=1e-8,
            err_msg=col,
        )
    labeled = compute_horizon_behavior_labels(feat)
    labeled2 = compute_horizon_behavior_labels(feat2)
    assert labeled.loc[t, "h10m_mfe"] != labeled2.loc[t, "h10m_mfe"]


def test_horizon_h1h_uses_close_t_plus_12() -> None:
    n = 80
    close = np.full(n, 50000.0)
    close[52:] = 52000.0
    df = pd.DataFrame(
        {
            "open": close - 5.0,
            "high": close + 10.0,
            "low": close - 10.0,
            "close": close,
            "atr": np.full(n, 20.0),
            "structure_bias": np.zeros(n),
            "failed_break": np.zeros(n),
            "bars_since_breakout": np.full(n, 99.0),
            "vol_z": np.zeros(n),
            "breakout_vol_ratio": np.ones(n),
        }
    )
    labeled = compute_horizon_behavior_labels(df)
    assert HORIZON_DIR_COLS[4] == "h1h_dir"
    assert NEXT_DIRECTION_NAMES[int(labeled.loc[40, "h1h_dir"])] == "STRONG_UP"
    assert NEXT_DIRECTION_NAMES[int(labeled.loc[40, "h10m_dir"])] == "NEUTRAL"


def test_horizon_labels_absent_from_features() -> None:
    raw = _ohlcv(220)
    labeled = build_labeled_frame(raw, config=default_research_config())
    feature_cols = [
        c for c in v9_feature_cols_for_resolution("5m") if c in labeled.columns
    ]
    leakage_audit(feature_cols)
    assert CHART_PATTERN_COL not in feature_cols
    for col in list(HORIZON_DIR_COLS) + list(HORIZON_STRUCTURE_COLS):
        assert col in labeled.columns
        assert col not in feature_cols
    assert "h10m_mfe" in labeled.columns
    assert "h10m_mfe" not in feature_cols


def test_chart_pattern_id_present_after_structure() -> None:
    raw = _ohlcv(220)
    feat = add_features(assemble_raw_frame(raw), resolution_minutes=5)
    assert CHART_PATTERN_COL in feat.columns
    assert feat[CHART_PATTERN_COL].between(0, 8).all()
    structured = add_market_structure_features(feat.copy())
    assert CHART_PATTERN_COL in structured.columns


def test_require_onnx_output_names_v6_default_and_v8() -> None:
    require_onnx_output_names(ONNX_OUTPUT_NAMES)
    require_onnx_output_names(
        ONNX_OUTPUT_NAMES_V9,
        contract_version=FEATURE_CONTRACT_VERSION,
        resolution="5m",
    )
    require_onnx_output_names(
        ONNX_OUTPUT_NAMES_V8,
        contract_version=FEATURE_CONTRACT_VERSION_V8,
        resolution="5m",
    )
    with pytest.raises(RuntimeError, match="missing outputs"):
        require_onnx_output_names(
            ONNX_OUTPUT_NAMES,
            contract_version=FEATURE_CONTRACT_VERSION,
            resolution="5m",
        )


def test_feature_config_export_defaults_to_v6() -> None:
    cfg = feature_config_from_training_export(
        feature_cols=["ret_1"],
        window_len=64,
        label_mean=[0.0],
        label_std=[1.0],
        q_edges=[0.25, 0.5, 0.75],
        config={"symbol": "BTCUSD"},
    )
    assert cfg["feature_contract_version"] == FEATURE_CONTRACT_VERSION_V6


def test_chronological_split_keeps_val_nonempty() -> None:
    slices = chronological_split(80, train_ratio=0.70, validation_ratio=0.15, embargo=48)
    assert slices["val"].stop > slices["val"].start
    assert slices["test"].stop > slices["test"].start
    assert slices["val"].start >= slices["train"].stop


def test_ablation_a_vs_f_tiny_synthetic() -> None:
    raw = _ohlcv(420)
    feat = add_features(assemble_raw_frame(raw), resolution_minutes=5)
    labeled = compute_horizon_behavior_labels(feat)
    labeled = labeled.iloc[:-25].reset_index(drop=True)
    feature_cols = [c for c in v9_feature_cols_for_resolution("5m") if c in labeled.columns]
    labeled[feature_cols] = (
        labeled[feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    )
    leakage_audit(feature_cols)
    packed = windows_from_frame(
        labeled, feature_cols=feature_cols, window_len=16, stride=4
    )
    slices = chronological_split(
        len(packed["x"]), train_ratio=0.70, validation_ratio=0.15, embargo=1
    )
    splits = split_window_dict(packed, slices)
    y_mean = np.nan_to_num(np.nanmean(splits["train"]["y_path"], axis=0), nan=0.0)
    y_std = np.nan_to_num(np.nanstd(splits["train"]["y_path"], axis=0), nan=1.0) + 1e-9
    groups = ablation_feature_groups("5m")
    device = torch.device("cpu")
    scores = {}
    for key in ("A", "F"):
        cols = groups[key]
        idx = np.array([feature_cols.index(c) for c in cols if c in feature_cols], dtype=np.int64)
        assert len(idx) >= 3
        scores[key] = run_ablation_epoch(
            splits["train"],
            splits["val"],
            feature_index=idx,
            config={"sequence_length": 16, "loss_weights": {"direction": 1.0}},
            device=device,
            y_mean=y_mean,
            y_std=y_std,
        )
        assert 0.0 <= scores[key] <= 1.0
    assert "A" in scores and "F" in scores


def test_default_research_config_does_not_gate_structure_loss() -> None:
    cfg = default_research_config()
    assert cfg["gate_chart_volume"] is False
    assert cfg["path_label_horizon_bars"] == 24
    assert cfg["embargo_bars"] == 24
    assert cfg["horizon_bars"][1] == 2


def test_scaler_and_windows_sanitize_inf_nan() -> None:
    raw = _ohlcv(80)
    feat = add_features(assemble_raw_frame(raw), resolution_minutes=5)
    cols = [c for c in v9_feature_cols_for_resolution("5m") if c in feat.columns][:8]
    work = feat.copy()
    work.loc[10, cols[0]] = np.inf
    work.loc[11, cols[1]] = np.nan
    mean, std = fit_train_scaler(work[cols].to_numpy(dtype=np.float64))
    assert np.isfinite(mean).all()
    assert np.isfinite(std).all()
    packed = windows_from_frame(work, feature_cols=cols, window_len=16, stride=4)
    assert np.isfinite(packed["x"]).all()
    cleaned = sanitize_feature_values(work[cols].to_numpy(dtype=np.float64))
    assert np.isfinite(cleaned).all()


def test_fit_label_stats_all_nan_column_is_finite() -> None:
    y = np.full((20, 3), np.nan)
    y[:, 0] = 1.0
    mean, std = fit_label_stats(y)
    assert np.isfinite(mean).all()
    assert np.isfinite(std).all()
    assert mean[1] == pytest.approx(0.0)
    assert std[1] == pytest.approx(1.0, abs=1e-6)


def _tiny_structure_batch(
    *,
    n: int = 8,
    seq: int = 16,
    n_features: int = 4,
    x_inf: bool = False,
) -> tuple:
    from scripts.colab.next_candle_model import NextCandleTransformer

    torch.manual_seed(0)
    n_cont = len(V8_CONTINUOUS_LABEL_COLS)
    n_h = 6
    model = NextCandleTransformer(
        n_features=n_features,
        d_model=16,
        nhead=2,
        num_layers=1,
        dropout=0.0,
        max_len=seq,
        n_continuous=n_cont,
        n_horizons=n_h,
    )
    x = torch.randn(n, seq, n_features)
    if x_inf:
        x[0, 0, 0] = float("inf")
    xcat = torch.zeros(n, seq, dtype=torch.long)
    batch = (
        x,
        xcat,
        torch.zeros(n, n_cont, dtype=torch.float32),
        torch.ones(n, n_cont, dtype=torch.float32),
        torch.ones(n, dtype=torch.long),
        torch.ones(n, n_h, dtype=torch.long),
        torch.zeros(n, n_h, dtype=torch.long),
        torch.zeros(n, dtype=torch.long),
    )
    return model, batch


def test_v8_loss_is_finite() -> None:
    from scripts.colab.next_candle_model import compute_v8_loss

    model, batch = _tiny_structure_batch()
    model.eval()
    with torch.no_grad():
        outs = model(batch[0], batch[1])
    loss = compute_v8_loss(outs, batch)
    assert torch.isfinite(loss)
    assert float(loss) > 0.0


def test_v8_model_outputs_match_onnx_names() -> None:
    model, batch = _tiny_structure_batch()
    model.eval()
    with torch.no_grad():
        outs = model(batch[0], batch[1])
    assert len(outs) == len(ONNX_OUTPUT_NAMES_V9)
    assert outs[-3].shape[-1] == len(V8_CONTINUOUS_LABEL_COLS)
    assert ONNX_OUTPUT_NAMES_V9[-3] == "continuous_pred"
    assert ONNX_OUTPUT_NAMES_V9[-1] == "chart_pattern_logits"
    assert ONNX_OUTPUT_NAMES_V9[1] == "h10m_dir_logits"
    assert outs[0].shape[-1] == 5
    assert outs[-1].shape[-1] == 9


def test_windows_pack_six_horizons_and_24_path_cols() -> None:
    raw = _ohlcv(160)
    feat = add_features(assemble_raw_frame(raw), resolution_minutes=5)
    labeled = compute_horizon_behavior_labels(feat)
    feature_cols = [
        c for c in v9_feature_cols_for_resolution("5m") if c in labeled.columns
    ][:8]
    packed = windows_from_frame(
        labeled, feature_cols=feature_cols, window_len=16, stride=8
    )
    assert packed["horizon_dirs"].shape[1] == 6
    assert packed["horizon_structs"].shape[1] == 6
    assert packed["pattern_ids"].shape[0] == packed["x"].shape[0]
    assert packed["horizon_dirs"].max() <= 4
    assert packed["y_path"].shape[1] == len(V8_CONTINUOUS_LABEL_COLS)


def test_train_next_candle_aborts_on_inf_without_poisoning_weights() -> None:
    from torch.utils.data import DataLoader

    from scripts.colab.next_candle_model import (
        NextCandleDataset,
        NextCandleTransformer,
        train_next_candle,
    )

    torch.manual_seed(0)
    n, seq, n_features = 8, 16, 4
    n_cont = len(V8_CONTINUOUS_LABEL_COLS)
    n_h = 6
    x = np.random.default_rng(0).normal(size=(n, seq, n_features)).astype(np.float32)
    x[0, 0, 0] = np.inf
    ds = NextCandleDataset(
        x,
        np.zeros((n, seq), dtype=np.int64),
        np.zeros((n, n_cont), dtype=np.float32),
        np.ones((n, n_cont), dtype=np.float32),
        np.ones(n, dtype=np.int64),
        np.ones((n, n_h), dtype=np.int64),
        np.zeros((n, n_h), dtype=np.int64),
    )
    loader = DataLoader(ds, batch_size=4, shuffle=False)
    model = NextCandleTransformer(
        n_features=n_features,
        d_model=16,
        nhead=2,
        num_layers=1,
        dropout=0.0,
        max_len=seq,
        n_continuous=n_cont,
        n_horizons=n_h,
    )
    before = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    hist = train_next_candle(
        model,
        loader,
        loader,
        device=torch.device("cpu"),
        epochs=3,
        lr=1e-3,
        weight_decay=0.0,
        patience=8,
    )
    assert hist["ok"] is False
    after = model.state_dict()
    for key, tensor in before.items():
        assert torch.equal(tensor, after[key].detach().cpu())
        assert torch.isfinite(after[key]).all()


def test_research_notebook_smoke() -> None:
    from scripts.colab.smoke_test_next_candle_notebook import validate_notebook

    path = Path(__file__).resolve().parents[2] / "scripts" / "colab" / (
        "transformer_btcusd_next_candle_research.ipynb"
    )
    validate_notebook(path)
