"""Leakage guards for the 15-minute recognition track."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import torch

from research.recognition_15m.bars import resample_completed_15m, synthetic_5m
from research.recognition_15m.contract import (
    ENGINEERED_CHANNELS,
    GEOMETRIC_CLASSES,
    RAW_CHANNELS,
    RULE_CARD_COLUMNS,
    WINDOW_BARS,
)
from research.recognition_15m.dataset import ChannelScaler, prepare_series, stack_windows
from research.recognition_15m.features import add_engineered_features
from research.recognition_15m.integrity import assert_causal_at, assert_feature_names
from research.recognition_15m.labels import build_rule_card, geometry_matrix
from research.recognition_15m.models import RecognitionTCN, train_presence_baseline, train_tcn
from research.recognition_15m.splits import nonoverlapping_ends, purged_split

_LABELS_PATH = (
    Path(__file__).resolve().parents[2] / "research" / "recognition_15m" / "labels.py"
)


def _walk(count: int, seed: int = 0) -> pd.DataFrame:
    """Random 15-minute walk with valid OHLC."""
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0.0, 0.4, count))
    open_ = np.empty(count, dtype=np.float64)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    high = np.maximum(open_, close) + rng.uniform(0.05, 0.4, count)
    low = np.minimum(open_, close) - rng.uniform(0.05, 0.4, count)
    return pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01", periods=count, freq="15min", tz="UTC"),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.uniform(1.0, 5.0, count),
        }
    )


def _hammer_frame(direction: int) -> pd.DataFrame:
    """Trend of ``direction`` followed by one long-lower-wick candle."""
    count = 40
    close = 100.0 + direction * np.arange(count, dtype=np.float64) * 0.8
    open_ = close - direction * 0.3
    high = np.maximum(open_, close) + 0.1
    low = np.minimum(open_, close) - 0.1
    open_[-1] = close[-2]
    close[-1] = open_[-1] + 0.4
    high[-1] = close[-1] + 0.05
    low[-1] = min(open_[-1], close[-1]) - 3.0
    return pd.DataFrame(
        {
            "time": pd.date_range("2024-06-01", periods=count, freq="15min", tz="UTC"),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(count, 4.0),
        }
    )


def test_resample_drops_partial_buckets_and_ignores_the_next_bucket() -> None:
    """An unfinished 15-minute bucket is not a bar, and later bars do not revise it."""
    source = synthetic_5m(2, start="2024-01-01T00:00:00Z")
    partial = resample_completed_15m(source.iloc[:-1])
    complete = resample_completed_15m(source)
    assert len(partial) == 1
    assert len(complete) == 2
    revised = source.copy()
    revised.loc[revised.index[-1], "close"] = 999.0
    untouched = resample_completed_15m(revised)
    assert untouched.iloc[0]["close"] == complete.iloc[0]["close"]
    assert untouched.iloc[1]["close"] != complete.iloc[1]["close"]


def test_level_channels_wait_for_a_confirmed_swing_on_each_side() -> None:
    """Support and resistance stay empty until both zigzag sides have confirmed."""
    source = (
        Path(__file__).resolve().parents[2] / "research" / "recognition_15m" / "features.py"
    ).read_text(encoding="utf-8")
    assert "argrelextrema" not in source
    assert "level_support_dist_atr" in ENGINEERED_CHANNELS
    with pytest.raises(ValueError, match="leak"):
        assert_feature_names(("sr_at_support",))
    frame = _impulse_frame()
    features = add_engineered_features(frame)
    support = features["level_support_dist_atr"].to_numpy(dtype=np.float64)
    finite = np.flatnonzero(np.isfinite(support))
    assert finite.size > 0
    start = int(finite[0])
    assert np.isnan(support[:start]).all()
    tail = features.iloc[start:]
    level_names = [name for name in ENGINEERED_CHANNELS if name.startswith("level_")]
    assert len(level_names) == 7
    for name in level_names:
        assert np.isfinite(tail[name].to_numpy(dtype=np.float64)).all()
    at_support = tail["level_at_support"].to_numpy(dtype=np.float64)
    assert set(np.unique(at_support)).issubset({0.0, 1.0})
    inside = tail["level_range_position"].between(0.0, 1.0)
    assert (tail.loc[inside, "level_support_dist_atr"] >= -1e-6).all()
    assert (tail.loc[inside, "level_resistance_dist_atr"] >= -1e-6).all()
    mutated = frame.copy()
    later = mutated.index[start + 1 :]
    mutated.loc[later, ["open", "high", "low", "close"]] = (
        mutated.loc[later, ["open", "high", "low", "close"]].astype(float) * 1.7
    )
    revised = add_engineered_features(mutated)
    assert revised.iloc[start]["level_support_dist_atr"] == pytest.approx(
        float(features.iloc[start]["level_support_dist_atr"])
    )


def _impulse_frame() -> pd.DataFrame:
    """Flat warmup, a rally, a dump, then a second rally."""
    count = 160
    close = np.full(count, 100.0, dtype=np.float64)
    close[50:70] = np.linspace(100.0, 130.0, 20)
    close[70:100] = np.linspace(130.0, 80.0, 30)
    close[100:] = np.linspace(80.0, 120.0, count - 100)
    open_ = np.empty(count, dtype=np.float64)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    return pd.DataFrame(
        {
            "time": pd.date_range("2024-03-01", periods=count, freq="15min", tz="UTC"),
            "open": open_,
            "high": np.maximum(open_, close) + 0.2,
            "low": np.minimum(open_, close) - 0.2,
            "close": close,
            "volume": np.full(count, 3.0),
        }
    )


def test_allow_list_rejects_pattern_flags_and_forecast_targets() -> None:
    """Rule-engine columns and future-return labels cannot enter the tensor."""
    assert_feature_names(RAW_CHANNELS)
    assert_feature_names(ENGINEERED_CHANNELS)
    with pytest.raises(ValueError, match="leak"):
        assert_feature_names(("close_atr", "bullish_engulfing"))
    with pytest.raises(ValueError, match="leak"):
        assert_feature_names(("close_atr", "forward_return_24"))
    with pytest.raises(ValueError, match="leak"):
        assert_feature_names(("cdl_hammer",))
    with pytest.raises(ValueError, match="leak"):
        assert_feature_names(("hh_count",))
    with pytest.raises(ValueError, match="leak"):
        assert_feature_names(("close_atr", "conventional_name"))
    with pytest.raises(ValueError, match="allow-list"):
        assert_feature_names(("close_atr", "not_a_channel"))


def test_future_bars_do_not_change_features_or_labels() -> None:
    """Scaling every bar after t leaves features and labels at t unchanged."""
    assert_causal_at(_walk(180, seed=3), 120)


def test_purge_gap_is_one_full_window() -> None:
    """Train, validation, and test windows do not share bars."""
    splits = purged_split(np.arange(5000))
    assert int(splits["val"][0] - splits["train"][-1]) >= WINDOW_BARS
    assert int(splits["test"][0] - splits["val"][-1]) >= WINDOW_BARS
    reported = nonoverlapping_ends(splits["test"], WINDOW_BARS)
    assert np.all(np.diff(reported) >= WINDOW_BARS)


def test_scaler_is_fit_on_training_windows_only() -> None:
    """A scaler fit on train does not absorb the test-window mean."""
    train = np.ones((4, WINDOW_BARS, 2), dtype=np.float32)
    test = np.full((4, WINDOW_BARS, 2), 5.0, dtype=np.float32)
    scaler = ChannelScaler().fit(train)
    transformed = scaler.transform(test)
    leaked = ChannelScaler().fit(np.concatenate([train, test], axis=0))
    assert np.allclose(scaler.mean, 1.0)
    assert np.allclose(transformed, (5.0 - 1.0) / scaler.std)
    assert not np.allclose(leaked.mean, scaler.mean)


def test_rule_card_names_stay_out_of_the_feature_tensor() -> None:
    """The same wick is one geometric class, with the textbook name only on the card."""
    decline = _hammer_frame(-1)
    advance = _hammer_frame(1)
    for frame, expected_name in ((decline, "hammer"), (advance, "hanging_man")):
        features = add_engineered_features(frame)
        assert set(ENGINEERED_CHANNELS).isdisjoint(RULE_CARD_COLUMNS)
        assert "hammer" not in features.columns
        assert "hanging_man" not in features.columns
        geometry = geometry_matrix(
            features["open"].to_numpy(dtype=np.float64),
            features["high"].to_numpy(dtype=np.float64),
            features["low"].to_numpy(dtype=np.float64),
            features["close"].to_numpy(dtype=np.float64),
            features["atr"].to_numpy(dtype=np.float64),
        )
        class_index = GEOMETRIC_CLASSES.index("long_lower_wick")
        assert geometry[-1, class_index] == 1.0
        card = build_rule_card(features, features["atr"].to_numpy(dtype=np.float64), geometry)
        hit = card[
            (card["bar_index"] == len(frame) - 1)
            & (card["geometric_class"] == "long_lower_wick")
        ]
        assert hit.iloc[0]["conventional_name"] == expected_name
    prepared = prepare_series(_walk(2500, seed=1))
    windows = stack_windows(prepared, prepared["splits"]["train"][:8], "engineered")
    assert list(windows["channels"]) == list(ENGINEERED_CHANNELS)
    assert set(windows["channels"]).isdisjoint(set(prepared["rule_card"].columns))


def test_labels_do_not_use_centered_extrema() -> None:
    """Swing labels must not confirm a pivot with bars to its right."""
    source = _LABELS_PATH.read_text(encoding="utf-8")
    assert "argrelextrema" not in source


def test_tcn_logits_ignore_future_bars() -> None:
    """A causal stack changes only the last step when the last bar changes."""
    torch.manual_seed(0)
    model = RecognitionTCN(in_channels=5, n_geometry=len(GEOMETRIC_CLASSES), n_states=5, n_tags=4)
    model.eval()
    values = torch.randn(1, WINDOW_BARS, 5)
    revised = values.clone()
    revised[0, -1] += 10.0
    with torch.no_grad():
        original, _, _ = model(values)
        changed, _, _ = model(revised)
    assert torch.allclose(original[0, :-1], changed[0, :-1])
    assert not torch.allclose(original[0, -1], changed[0, -1])


def test_phase1_trainers_run_on_a_tiny_batch() -> None:
    """Head A, Head E, and the presence baseline fit without forecast targets."""
    rng = np.random.default_rng(0)
    count = 24
    features = rng.normal(size=(count, WINDOW_BARS, len(RAW_CHANNELS))).astype(np.float32)
    geometry = np.zeros((count, WINDOW_BARS, len(GEOMETRIC_CLASSES)), dtype=np.float32)
    geometry[:12, 0, 0] = 1.0
    geometry[12:, 0, 1] = 1.0
    state = rng.integers(0, 5, size=count)
    tag = rng.integers(0, 4, size=count)
    batch = {"features": features, "geometry": geometry, "state": state, "tag": tag}
    trained = train_tcn(batch, batch, batch, epochs=1, batch_size=8, seed=0)
    assert "state_dict" in trained
    assert "geometry_macro_f1" in trained["test"]
    assert trained["best_epoch"] == 0
    assert len(trained["train_loss_by_epoch"]) == len(trained["val_loss_by_epoch"]) == 1
    presence = train_presence_baseline(features, geometry, features, geometry, seed=0)
    assert "macro_f1" in presence
    assert "buy" not in presence
