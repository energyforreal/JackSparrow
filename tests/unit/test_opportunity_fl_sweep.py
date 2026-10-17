"""Tests for the frozen 30m 50-feature long/short policy and MLP notebook."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
SWEEP_NOTEBOOK = (
    REPO / "scripts" / "colab" / "transformer_btcusd_opportunity_30m_h24_fl_sweep.ipynb"
)
SOURCE_NOTEBOOK = (
    REPO / "scripts" / "colab" / "transformer_btcusd_opportunity_10m.ipynb"
)
SPECS_MODULE = REPO / "scripts" / "colab" / "opportunity_fl_sweep.py"


def _cell_text(cell: Dict[str, Any]) -> str:
    source = cell.get("source", [])
    if isinstance(source, str):
        return source
    return "".join(source)


def _load_notebook(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _code_cells(path: Path) -> list[str]:
    nb = _load_notebook(path)
    return [_cell_text(c) for c in nb["cells"] if c.get("cell_type") == "code"]


def _cell_named(path: Path, name: str) -> str:
    marker = f"# CELL: {name}"
    for source in _code_cells(path):
        if source.startswith(marker) or marker in source.splitlines()[0:3]:
            return source
    raise AssertionError(f"{path.name} is missing {marker}")


def _exec_cell(path: Path, name: str, ns: Dict[str, Any] | None = None) -> Dict[str, Any]:
    env: Dict[str, Any] = {} if ns is None else ns
    exec(_cell_named(path, name), env, env)
    return env


def _exec_specs() -> Dict[str, Any]:
    return _exec_cell(SWEEP_NOTEBOOK, "FL_SPECS")


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("opportunity_fl_sweep", SPECS_MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ohlcv(
    n: int = 80,
    *,
    close: np.ndarray | None = None,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    open_: np.ndarray | None = None,
    volume: float | np.ndarray = 10.0,
) -> pd.DataFrame:
    times = pd.date_range("2024-01-01", periods=n, freq="30min", tz="UTC")
    if close is None:
        close = np.full(n, 100.0)
    if open_ is None:
        open_ = close.copy()
    if high is None:
        high = np.maximum(close, open_) + 0.2
    if low is None:
        low = np.minimum(close, open_) - 0.2
    vol = np.full(n, float(volume)) if np.isscalar(volume) else np.asarray(volume)
    return pd.DataFrame(
        {
            "time": times,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": vol,
        }
    )


def test_source_notebook_is_unchanged() -> None:
    joined = "\n".join(_code_cells(SOURCE_NOTEBOOK))
    assert "# CELL: FL_SPECS" not in joined
    assert "# CELL: FL_RUN" not in joined
    assert '"ensemble": ["LR", "RF", "XGB", "LGBM", "CatBoost"]' in joined
    assert "opportunity_30m_h24_fl_sweep" not in joined
    assert "opportunity_30m_h24_policy" not in joined
    assert "opportunity_30m_h24_twosided" not in joined
    assert "opportunity_30m_h24_regime" not in joined
    assert "run_fixed_target_experiments" not in joined
    assert "run_policy_and_multihead" not in joined
    assert "run_regime_exclusive_sweep" not in joined


def test_sweep_notebook_config_is_frozen_xgb_30m() -> None:
    ns: Dict[str, Any] = {"Dict": Dict, "Any": Any, "Tuple": Tuple, "json": json}
    _exec_cell(SWEEP_NOTEBOOK, "CONFIG", ns)
    cfg = ns["CONFIG"]
    assert cfg["resolution"] == "30m"
    assert int(cfg["horizon_bars"]) == 24
    assert int(cfg["horizon_minutes"]) == 720
    assert int(cfg["bar_minutes"]) == 30
    assert int(cfg["purge_bars"]) == 25
    assert cfg["ensemble"] == ["XGB"]
    assert cfg["export_dir"] == "export/opportunity_30m_h24_regime"
    assert cfg["run_baseline_train"] is False
    assert int(cfg["walk_forward_folds"]) == 4
    joined = "\n".join(_code_cells(SWEEP_NOTEBOOK))
    assert "# CELL: FL_SPECS" in joined
    assert "# CELL: FL_RUN" in joined
    assert "run_regime_exclusive_sweep" in joined
    assert "run_feature_label_sweep" not in joined
    run = _cell_named(SWEEP_NOTEBOOK, "FL_RUN")
    assert "make_archive" in run
    assert "bars," in run
    assert "featured," not in run
    assert "inner_calibration_split=inner_calibration_split" in run
    assert "run_fixed_target_experiments(" not in run
    assert "run_regime_exclusive_sweep(" in run
    assert "Barrier compare" in run
    assert "Test once" in run
    assert "copied_to_live" in run
    train = _cell_named(SWEEP_NOTEBOOK, "TRAIN")
    assert "run_baseline_train" in train
    assert "Skipping baseline TRAIN" in train
    gate = _cell_named(SWEEP_NOTEBOOK, "GATE")
    assert "run_baseline_train" in gate
    assert "Skipping baseline GATE" in gate
    howto = "\n".join(
        _cell_text(c)
        for c in _load_notebook(SWEEP_NOTEBOOK)["cells"]
        if c.get("cell_type") == "markdown"
    )
    assert "Runtime → Run all" in howto
    assert "transformer_btcusd_opportunity_30m_h24_fl_sweep.ipynb" in howto
    assert "opportunity_30m_h24_regime" in howto
    assert "--gpu none" in howto


def test_fixed_feature_contract_is_fifty_named_columns() -> None:
    ns = _exec_specs()
    cols = ns["FIXED_FEATURE_COLS"]
    assert len(cols) == 50
    assert len(set(cols)) == 50
    assert cols[0] == "return_1"
    assert cols[6] == "return_48"
    assert cols[7:12] == (
        "candle_body",
        "range_pct",
        "upper_wick_pct",
        "lower_wick_pct",
        "close_location",
    )
    assert cols[-2:] == ("drawdown_48", "distance_from_rolling_extreme")
    assert ns["FROZEN_HORIZON_BARS"] == 24
    assert ns["TP_ATR_MULT"] == 4.0
    assert ns["SL_ATR_MULT"] == 2.0
    assert [s["id"] for s in ns["TARGET_SPECS"]] == [
        "direction_head",
        "return_head",
        "volatility_head",
        "opportunity_head",
        "opportunity_short_head",
        "excursion_head",
        "exclusive_head",
    ]
    assert list(ns["POLICY_HEAD_IDS"]) == [
        "exclusive_head",
        "volatility_head",
        "excursion_head",
    ]
    assert [b["id"] for b in ns["BARRIER_SPECS"]] == ["b2_2", "b3_3", "b4_2"]
    assert ns["MLP_HIDDEN"] == (64, 32)


def test_feature_builder_ignores_non_ohlcv_columns() -> None:
    fl = _load_module()
    frame = _ohlcv(60)
    frame["ret_1"] = 999.0
    featured = fl.add_fixed_ohlcv_features(frame)
    assert "ret_1" not in featured.columns
    assert list(featured.columns[:6]) == list(fl.OHLCV_COLS)
    for col in fl.FIXED_FEATURE_COLS:
        assert col in featured.columns


def test_features_are_causal_to_future_bar_mutation() -> None:
    fl = _load_module()
    rng = np.random.default_rng(0)
    n = 90
    close = 100.0 + np.cumsum(rng.normal(0.0, 0.3, size=n))
    volume = rng.uniform(5.0, 20.0, size=n)
    frame = _ohlcv(
        n,
        close=close,
        high=close + rng.uniform(0.1, 0.8, size=n),
        low=close - rng.uniform(0.1, 0.8, size=n),
        open_=close + rng.normal(0.0, 0.1, size=n),
        volume=volume,
    )
    feat_a = fl.add_fixed_ohlcv_features(frame)
    t = 60
    mutated = frame.copy()
    mutated.loc[t + 1, "close"] = mutated.loc[t + 1, "close"] * 1.8
    mutated.loc[t + 1, "high"] = mutated.loc[t + 1, "close"] + 2.0
    mutated.loc[t + 1, "low"] = mutated.loc[t + 1, "close"] - 2.0
    mutated.loc[t + 1, "volume"] = 10_000.0
    feat_b = fl.add_fixed_ohlcv_features(mutated)
    for col in fl.FIXED_FEATURE_COLS:
        a = feat_a.loc[t, col]
        b = feat_b.loc[t, col]
        if np.isnan(a) and np.isnan(b):
            continue
        assert a == pytest.approx(b, rel=0.0, abs=1e-12), col


def test_breakout_distance_excludes_current_bar() -> None:
    fl = _load_module()
    n = 40
    close = np.full(n, 100.0)
    high = np.full(n, 101.0)
    low = np.full(n, 99.0)
    high[10] = 110.0
    frame = _ohlcv(n, close=close, high=high, low=low)
    feat = fl.add_fixed_ohlcv_features(frame)
    t = 30
    mutated = frame.copy()
    mutated.loc[t, "high"] = 200.0
    feat_mut = fl.add_fixed_ohlcv_features(mutated)
    assert feat.loc[t, "breakout_distance_24"] == pytest.approx(
        feat_mut.loc[t, "breakout_distance_24"]
    )


def test_direction_neutral_band_uses_half_atr() -> None:
    fl = _load_module()
    n = 50
    close = np.full(n, 100.0)
    close[24] = 100.0 * np.exp(0.02)
    frame = _ohlcv(n, close=close)
    frame["atr"] = 2.0
    labeled = fl.attach_fixed_targets(frame, dir_band_atr_mult=0.5)
    band = 0.5 * 2.0 / 100.0
    assert float(labeled.loc[0, "y_return"]) == pytest.approx(0.02)
    assert band < 0.02
    assert int(labeled.loc[0, "y_direction"]) == fl.DIR_UP

    close_n = np.full(n, 100.0)
    close_n[24] = 100.0 * np.exp(0.005)
    frame_n = _ohlcv(n, close=close_n)
    frame_n["atr"] = 2.0
    labeled_n = fl.attach_fixed_targets(frame_n, dir_band_atr_mult=0.5)
    assert abs(float(labeled_n.loc[0, "y_return"])) < band
    assert int(labeled_n.loc[0, "y_direction"]) == fl.DIR_NEUTRAL

    close_d = np.full(n, 100.0)
    close_d[24] = 100.0 * np.exp(-0.02)
    frame_d = _ohlcv(n, close=close_d)
    frame_d["atr"] = 2.0
    labeled_d = fl.attach_fixed_targets(frame_d, dir_band_atr_mult=0.5)
    assert int(labeled_d.loc[0, "y_direction"]) == fl.DIR_DOWN
    assert np.all(labeled.loc[n - 24 :, "y_direction"].to_numpy() == fl.UNLABELED)


def test_opportunity_first_touch_and_same_bar_is_sl_first() -> None:
    fl = _load_module()
    n = 40
    close = np.full(n, 100.0)
    high = np.full(n, 100.2)
    low = np.full(n, 99.8)

    tp = high.copy()
    tp[3] = 105.0
    frame_tp = _ohlcv(n, close=close, high=tp, low=low)
    frame_tp["atr"] = 1.0
    lab_tp = fl.attach_fixed_targets(frame_tp)
    assert int(lab_tp.loc[0, "y_opportunity"]) == fl.OPP_TP_FIRST
    assert float(lab_tp.loc[0, "same_bar_double_touch"]) == 0.0

    sl = low.copy()
    sl[3] = 97.0
    frame_sl = _ohlcv(n, close=close, high=high, low=sl)
    frame_sl["atr"] = 1.0
    lab_sl = fl.attach_fixed_targets(frame_sl)
    assert int(lab_sl.loc[0, "y_opportunity"]) == fl.OPP_SL_FIRST

    both_high = high.copy()
    both_low = low.copy()
    both_high[3] = 105.0
    both_low[3] = 97.0
    frame_both = _ohlcv(n, close=close, high=both_high, low=both_low)
    frame_both["atr"] = 1.0
    lab_both = fl.attach_fixed_targets(frame_both)
    assert int(lab_both.loc[0, "y_opportunity"]) == fl.OPP_SL_FIRST
    assert float(lab_both.loc[0, "same_bar_double_touch"]) == 1.0

    frame_to = _ohlcv(n, close=close, high=high, low=low)
    frame_to["atr"] = 1.0
    lab_to = fl.attach_fixed_targets(frame_to)
    assert int(lab_to.loc[0, "y_opportunity"]) == fl.OPP_TIMEOUT
    assert float(lab_to.loc[0, "same_bar_double_touch"]) == 0.0

    short_tp = low.copy()
    short_tp[3] = 95.0
    frame_stp = _ohlcv(n, close=close, high=high, low=short_tp)
    frame_stp["atr"] = 1.0
    lab_stp = fl.attach_fixed_targets(frame_stp)
    assert int(lab_stp.loc[0, "y_opportunity_short"]) == fl.OPP_TP_FIRST

    short_sl = high.copy()
    short_sl[3] = 103.0
    frame_ssl = _ohlcv(n, close=close, high=short_sl, low=low)
    frame_ssl["atr"] = 1.0
    lab_ssl = fl.attach_fixed_targets(frame_ssl)
    assert int(lab_ssl.loc[0, "y_opportunity_short"]) == fl.OPP_SL_FIRST

    both_s_high = high.copy()
    both_s_low = low.copy()
    both_s_high[3] = 103.0
    both_s_low[3] = 95.0
    frame_sboth = _ohlcv(n, close=close, high=both_s_high, low=both_s_low)
    frame_sboth["atr"] = 1.0
    lab_sboth = fl.attach_fixed_targets(frame_sboth)
    assert int(lab_sboth.loc[0, "y_opportunity_short"]) == fl.OPP_SL_FIRST
    assert float(lab_sboth.loc[0, "same_bar_double_touch_short"]) == 1.0


def test_return_vol_and_excursion_use_bars_t1_to_t24() -> None:
    fl = _load_module()
    rng = np.random.default_rng(1)
    n = 80
    close = 100.0 + np.cumsum(rng.normal(0.0, 0.4, size=n))
    high = close + rng.uniform(0.2, 1.0, size=n)
    low = close - rng.uniform(0.2, 1.0, size=n)
    frame = _ohlcv(n, close=close, high=high, low=low)
    frame["atr"] = 1.5
    labeled = fl.attach_fixed_targets(frame)
    i = 10
    expected_r = float(np.log(close[i + 24] / close[i]))
    steps = np.log(close[i + 1 : i + 25] / close[i : i + 24])
    expected_vol = float(np.sqrt(np.mean(np.square(steps))))
    expected_up = float((high[i + 1 : i + 25].max() - close[i]) / close[i])
    expected_dn = float((close[i] - low[i + 1 : i + 25].min()) / close[i])
    assert float(labeled.loc[i, "y_return"]) == pytest.approx(expected_r)
    assert float(labeled.loc[i, "y_volatility"]) == pytest.approx(expected_vol)
    assert float(labeled.loc[i, "y_upside"]) == pytest.approx(expected_up)
    assert float(labeled.loc[i, "y_downside"]) == pytest.approx(expected_dn)


def test_barrier_pct_is_causal_four_two_atr() -> None:
    fl = _load_module()
    n = 40
    close = np.full(n, 100.0)
    frame = _ohlcv(n, close=close)
    frame["atr"] = 2.0
    labeled = fl.attach_fixed_targets(frame)
    assert float(labeled.loc[0, "tp_pct"]) == pytest.approx(0.08)
    assert float(labeled.loc[0, "sl_pct"]) == pytest.approx(0.04)
    mutated = frame.copy()
    mutated.loc[1:, "close"] = 180.0
    mutated.loc[1:, "high"] = 181.0
    mutated.loc[1:, "low"] = 179.0
    relabeled = fl.attach_fixed_targets(mutated)
    assert float(relabeled.loc[0, "sl_pct"]) == pytest.approx(0.04)
    assert float(relabeled.loc[0, "tp_pct"]) == pytest.approx(0.08)


def test_regime_policy_skips_range_conflict_and_adverse_excursion() -> None:
    fl = _load_module()
    p = np.array(
        [
            [0.9, 0.05, 0.05],
            [0.9, 0.05, 0.05],
            [0.9, 0.05, 0.05],
            [0.05, 0.9, 0.05],
            [0.9, 0.05, 0.05],
        ]
    )
    pred_up = np.array([0.01, 0.01, 0.01, 0.01, 0.01])
    pred_down = np.array([0.01, 0.01, 0.05, 0.01, 0.01])
    sl = np.full(5, 0.02)
    regime = np.array(
        [
            fl.REGIME_UP,
            fl.REGIME_UP,
            fl.REGIME_UP,
            fl.REGIME_DOWN,
            fl.REGIME_RANGE,
        ]
    )
    long_t, short_t = fl.apply_regime_policy(
        p,
        pred_up,
        pred_down,
        sl,
        regime,
        thr_long=0.5,
        thr_short=0.5,
        k_dd=1.0,
    )
    assert long_t.tolist() == [True, True, False, False, False]
    assert short_t.tolist() == [False, False, False, True, False]


def test_policy_takes_low_vol_and_skips_adverse_excursion() -> None:
    fl = _load_module()
    p_tp = np.array([0.9, 0.9, 0.2])
    pred_adverse = np.array([0.01, 0.05, 0.01])
    sl = np.full(3, 0.02)
    take = fl.apply_policy_mask(
        p_tp,
        pred_adverse,
        sl,
        thr_opp=0.5,
        k_dd=1.0,
    )
    assert take.tolist() == [True, False, False]


def test_r_multiple_uses_causal_sl_pct() -> None:
    fl = _load_module()
    pnl = np.array([0.04, -0.02, 0.01])
    sl = np.array([0.02, 0.02, 0.02])
    r = fl.r_multiple(pnl, sl)
    assert r == pytest.approx([2.0, -1.0, 0.5])
    scored = fl.score_policy_r(
        np.array([True, True, True]),
        pnl,
        sl,
        min_signals=2,
    )
    assert scored["n"] == 3.0
    assert scored["r_expectancy"] == pytest.approx(0.5)


def test_long_path_pnl_follows_first_touch_then_cost() -> None:
    fl = _load_module()
    y = np.array(
        [fl.OPP_TP_FIRST, fl.OPP_SL_FIRST, fl.OPP_TIMEOUT], dtype=np.int64
    )
    tp = np.array([0.04, 0.04, 0.04])
    sl = np.array([0.02, 0.02, 0.02])
    timeout = np.array([0.01, 0.01, 0.01])
    pnl = fl.long_path_pnl(y, tp, sl, timeout, cost=0.0016)
    assert pnl == pytest.approx([0.0384, -0.0216, 0.0084])
    short_pnl = fl.short_path_pnl(y, tp, sl, timeout, cost=0.0016)
    assert short_pnl == pytest.approx([0.0384, -0.0216, -0.0116])


def test_policy_test_gate_requires_majority_and_comparators() -> None:
    fl = _load_module()
    assert fl.policy_test_gate([0.2, 0.1, 0.05, 0.04], 0.0, -0.1) is True
    assert fl.policy_test_gate([0.2, -0.1, -0.05, 0.04], 0.0, -0.1) is False
    assert fl.policy_test_gate([0.2, 0.1, 0.05, 0.04], 0.3, -0.1) is False
    assert fl.policy_test_gate([0.2, 0.1, 0.05, 0.04], 0.0, 0.25) is False
    both = fl.policy_test_gate(
        [0.2, 0.1, 0.05, 0.04],
        0.0,
        -0.1,
        long_r=0.1,
        short_r=0.05,
        long_n=120,
        short_n=120,
        min_signals=100,
    )
    assert both is True
    one_side = fl.policy_test_gate(
        [0.2, 0.1, 0.05, 0.04],
        0.0,
        -0.1,
        long_r=0.2,
        short_r=-0.1,
        long_n=120,
        short_n=120,
        min_signals=100,
    )
    assert one_side is False
    fragile = fl.policy_test_gate(
        [0.2, 0.1, 0.05, 0.04],
        0.0,
        -0.1,
        long_r=0.1,
        short_r=0.05,
        long_n=120,
        short_n=120,
        min_signals=100,
        cost_stress_r=-0.01,
    )
    assert fragile is False
    range_fail = fl.policy_test_gate(
        [0.2, 0.1, 0.05, 0.04],
        0.0,
        -0.1,
        long_r=0.1,
        short_r=0.05,
        long_n=120,
        short_n=120,
        min_signals=100,
        range_fill_share=0.2,
    )
    assert range_fail is False


def test_policy_mlp_has_three_heads_when_torch_present() -> None:
    fl = _load_module()
    if not fl.torch_available():
        pytest.skip("torch is not installed")
    model = fl._build_policy_mlp(50, fl.MLP_HIDDEN)
    assert model.exclusive.out_features == 3
    assert model.vol.out_features == 1
    assert model.exc.out_features == 2
    first = model.backbone[0]
    last_linear = model.backbone[3]
    assert first.in_features == 50
    assert first.out_features == 64
    assert last_linear.out_features == 32


def test_majority_skill_requires_more_than_half_the_folds() -> None:
    fl = _load_module()
    two_of_three = fl.majority_skill([0.4, 0.5, 0.9], [0.8, 0.7, 0.8])
    assert two_of_three["learnable"] is True
    assert two_of_three["n_folds_scored"] == 3
    one_of_three = fl.majority_skill([0.4, 0.9, 0.9], [0.8, 0.7, 0.8])
    assert one_of_three["learnable"] is False


def test_log_loss_matches_class_frequency_baseline() -> None:
    fl = _load_module()
    y = np.array([0, 0, 1, 2], dtype=np.int64)
    prior = fl._class_prior(y, 3)
    proba = np.repeat(prior[None, :], y.size, axis=0)
    ll = fl._log_loss(y, proba, n_classes=3)
    expected = float(-np.mean(np.log(prior[y])))
    assert ll == pytest.approx(expected)


def test_specs_module_matches_injected_cell() -> None:
    cell = _cell_named(SWEEP_NOTEBOOK, "FL_SPECS")
    module = SPECS_MODULE.read_text(encoding="utf-8")
    assert module in cell


def test_assign_regime_uses_slope_and_adx() -> None:
    fl = _load_module()
    slope = np.array([0.01, -0.01, 0.01, 0.0, np.nan])
    adx = np.array([25.0, 25.0, 10.0, 30.0, 25.0])
    regime = fl.assign_regime(slope, adx)
    assert regime.tolist() == [
        fl.REGIME_UP,
        fl.REGIME_DOWN,
        fl.REGIME_RANGE,
        fl.REGIME_RANGE,
        fl.REGIME_RANGE,
    ]


def test_exclusive_labels_skip_conflict_and_mismatched_regime() -> None:
    fl = _load_module()
    y_long = np.array(
        [
            fl.OPP_TP_FIRST,
            fl.OPP_TP_FIRST,
            fl.OPP_SL_FIRST,
            fl.OPP_TP_FIRST,
            fl.UNLABELED,
        ],
        dtype=np.int64,
    )
    y_short = np.array(
        [
            fl.OPP_TIMEOUT,
            fl.OPP_TP_FIRST,
            fl.OPP_TP_FIRST,
            fl.OPP_TIMEOUT,
            fl.OPP_TIMEOUT,
        ],
        dtype=np.int64,
    )
    path = fl.exclusive_path_labels(y_long, y_short)
    assert path.tolist() == [
        fl.EXCL_LONG,
        fl.EXCL_SKIP,
        fl.EXCL_SHORT,
        fl.EXCL_LONG,
        fl.UNLABELED,
    ]
    regime = np.array(
        [
            fl.REGIME_UP,
            fl.REGIME_UP,
            fl.REGIME_DOWN,
            fl.REGIME_DOWN,
            fl.REGIME_UP,
        ]
    )
    y = fl.exclusive_regime_labels(path, regime)
    assert y.tolist() == [
        fl.EXCL_LONG,
        fl.EXCL_SKIP,
        fl.EXCL_SHORT,
        fl.EXCL_SKIP,
        fl.UNLABELED,
    ]


def test_regime_is_causal_to_future_bar_mutation() -> None:
    fl = _load_module()
    rng = np.random.default_rng(3)
    n = 120
    close = 100.0 + np.cumsum(rng.normal(0.02, 0.3, size=n))
    frame = _ohlcv(
        n,
        close=close,
        high=close + rng.uniform(0.1, 0.6, size=n),
        low=close - rng.uniform(0.1, 0.6, size=n),
        open_=close + rng.normal(0.0, 0.1, size=n),
        volume=rng.uniform(5.0, 20.0, size=n),
    )
    feat_a = fl.add_fixed_ohlcv_features(frame)
    lab_a = fl.attach_fixed_targets(feat_a)
    t = 70
    mutated = frame.copy()
    mutated.loc[t + 1, "close"] = mutated.loc[t + 1, "close"] * 1.8
    mutated.loc[t + 1, "high"] = mutated.loc[t + 1, "close"] + 2.0
    mutated.loc[t + 1, "low"] = mutated.loc[t + 1, "close"] - 2.0
    feat_b = fl.add_fixed_ohlcv_features(mutated)
    lab_b = fl.attach_fixed_targets(feat_b)
    assert int(lab_a.loc[t, "regime"]) == int(lab_b.loc[t, "regime"])
    assert float(feat_a.loc[t, "ema_slope_48"]) == pytest.approx(
        float(feat_b.loc[t, "ema_slope_48"])
    )
    assert float(feat_a.loc[t, "adx_14"]) == pytest.approx(
        float(feat_b.loc[t, "adx_14"])
    )


def test_attach_exclusive_uses_barrier_multiples() -> None:
    fl = _load_module()
    n = 80
    close = np.full(n, 100.0)
    frame = _ohlcv(n, close=close)
    featured = fl.add_fixed_ohlcv_features(frame)
    featured["atr"] = 2.0
    labeled = fl.attach_fixed_targets(
        featured, tp_atr_mult=2.0, sl_atr_mult=2.0
    )
    assert float(labeled.loc[0, "tp_pct"]) == pytest.approx(0.04)
    assert float(labeled.loc[0, "sl_pct"]) == pytest.approx(0.04)
    assert "y_exclusive" in labeled.columns
    assert "regime" in labeled.columns


def test_non_overlapping_mask_skips_open_horizon() -> None:
    fl = _load_module()
    take = np.array([True, True, True, True])
    kept = fl.non_overlapping_mask(take, horizon_bars=2)
    assert kept.tolist() == [True, False, True, False]


def test_regime_unfiltered_sides_skip_range() -> None:
    fl = _load_module()
    regime = np.array([fl.REGIME_UP, fl.REGIME_DOWN, fl.REGIME_RANGE])
    long_t, short_t = fl.regime_unfiltered_sides(regime)
    assert long_t.tolist() == [True, False, False]
    assert short_t.tolist() == [False, True, False]
