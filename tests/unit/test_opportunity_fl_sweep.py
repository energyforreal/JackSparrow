"""Exec the feature-label sweep cells from the generated 30m notebook."""

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


def _frame(
    n: int = 40,
    *,
    close: np.ndarray | None = None,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    atr: float | np.ndarray = 10.0,
) -> pd.DataFrame:
    times = pd.date_range("2024-01-01", periods=n, freq="30min", tz="UTC")
    if close is None:
        close = np.full(n, 100.0)
    if high is None:
        high = close + 0.2
    if low is None:
        low = close - 0.2
    atr_arr = np.full(n, float(atr)) if np.isscalar(atr) else np.asarray(atr, dtype=np.float64)
    return pd.DataFrame(
        {
            "time": times,
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": 1.0,
            "atr": atr_arr,
        }
    )


def test_source_notebook_is_unchanged() -> None:
    joined = "\n".join(_code_cells(SOURCE_NOTEBOOK))
    assert "# CELL: FL_SPECS" not in joined
    assert "# CELL: FL_RUN" not in joined
    assert '"ensemble": ["LR", "RF", "XGB", "LGBM", "CatBoost"]' in joined
    assert "opportunity_30m_h24_fl_sweep" not in joined


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
    assert cfg["export_dir"] == "export/opportunity_30m_h24_fl_sweep"
    assert cfg["run_baseline_train"] is False
    assert int(cfg["walk_forward_folds"]) == 4
    joined = "\n".join(_code_cells(SWEEP_NOTEBOOK))
    assert "# CELL: FL_SPECS" in joined
    assert "# CELL: FL_RUN" in joined
    assert "run_feature_label_sweep" in joined
    assert "make_archive" in _cell_named(SWEEP_NOTEBOOK, "FL_RUN")
    assert "Stage A" in _cell_named(SWEEP_NOTEBOOK, "FL_RUN")
    assert "Stage B" in _cell_named(SWEEP_NOTEBOOK, "FL_RUN")
    assert "Stage C" in _cell_named(SWEEP_NOTEBOOK, "FL_RUN")
    train = _cell_named(SWEEP_NOTEBOOK, "TRAIN")
    assert "run_baseline_train" in train
    assert "Skipping baseline TRAIN" in train


def test_barrier_specs_are_24_bars_and_l0_is_4_2() -> None:
    ns = _exec_specs()
    l0 = ns["label_spec_by_id"]("L0")
    assert l0["tp_atr_mult"] == 4.0
    assert l0["sl_atr_mult"] == 2.0
    assert l0["horizon_bars"] == 24
    assert l0["kind"] == "barrier"
    for spec in ns["barrier_label_specs"]():
        assert int(spec["horizon_bars"]) == 24
    for spec in ns["LABEL_SPECS"]:
        assert int(spec["horizon_bars"]) == 24
        assert spec["horizon_bars"] == ns["FROZEN_HORIZON_BARS"]


def test_feature_families_disjoint_except_f0() -> None:
    ns = _exec_specs()
    current = ns["CURRENT_FEATURE_COLS"]
    f7 = ns["F7_COLS"]
    assert ns["family_columns"]("F0") == current + f7
    union: set[str] = set()
    for fam in ns["disjoint_family_ids"]():
        cols = ns["family_columns"](fam)
        overlap = union.intersection(cols)
        assert not overlap, f"{fam} overlaps {sorted(overlap)}"
        union.update(cols)
    core = set().union(
        *(ns["family_columns"](fid) for fid in ("F1", "F2", "F3", "F4", "F5", "F6"))
    )
    assert core == set(current)
    assert set(ns["family_columns"]("F0")) == set(current) | set(f7)
    assert "rv24_over_sl" not in f7
    assert "rv_24" in f7


def test_leave_one_family_out_drops_exactly_that_family() -> None:
    ns = _exec_specs()
    f0 = set(ns["family_columns"]("F0"))
    for fam in ns["disjoint_family_ids"]():
        dropped = set(ns["family_columns"](fam))
        left = set(ns["family_columns"](f"F0_minus_{fam}"))
        assert left == f0 - dropped
        assert dropped.isdisjoint(left)
        assert dropped
    names = [name for name, _cols in ns["screen_column_sets"]()]
    assert "F0" in names
    assert "F7" in names
    assert "F0_minus_F6" in names


def test_l0_apply_matches_notebook_barrier() -> None:
    ns: Dict[str, Any] = {}
    _exec_cell(SOURCE_NOTEBOOK, "LABELS", ns)
    _exec_cell(SWEEP_NOTEBOOK, "FL_SPECS", ns)
    close = np.linspace(100.0, 108.0, 40)
    frame = _frame(40, close=close, high=close + 1.0, low=close - 1.0, atr=2.0)
    spec = ns["label_spec_by_id"]("L0")
    labeled = ns["apply_label_spec"](
        frame, spec, ns["compute_opportunity_labels"], atr_period=14
    )
    reference = ns["compute_opportunity_labels"](
        frame, tp_mult=4.0, sl_mult=2.0, horizon_bars=24, atr_period=14
    )
    np.testing.assert_array_equal(
        labeled["trade_label"].to_numpy(), reference["trade_label"].to_numpy()
    )
    assert "opp_label" in labeled.columns
    assert "dir_train_mask" in labeled.columns


def test_l5_tp_pct_is_causal_not_forward_return() -> None:
    ns: Dict[str, Any] = {}
    _exec_cell(SOURCE_NOTEBOOK, "LABELS", ns)
    _exec_cell(SWEEP_NOTEBOOK, "FL_SPECS", ns)
    close = np.linspace(100.0, 130.0, 80)
    atr = 2.0
    frame = _frame(80, close=close, high=close + 0.5, low=close - 0.5, atr=atr)
    labeled = ns["apply_label_spec"](
        frame, ns["label_spec_by_id"]("L5"), ns["compute_opportunity_labels"]
    )
    usable = labeled["trade_label"].to_numpy() >= 0
    tp = labeled["tp_pct"].to_numpy(dtype=np.float64)
    sl = labeled["sl_pct"].to_numpy(dtype=np.float64)
    causal = atr / close
    fwd = np.full(len(close), np.nan)
    fwd[:-24] = close[24:] / close[:-24] - 1.0
    np.testing.assert_allclose(tp[usable], causal[usable], rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(sl[usable], causal[usable], rtol=1e-12, atol=1e-12)
    assert not np.allclose(tp[usable], np.abs(fwd[usable]))
    assert bool(labeled["opportunity_degenerate"].iloc[0]) is True


def test_l7_timeout_bars_remain_scored() -> None:
    ns: Dict[str, Any] = {}
    _exec_cell(SOURCE_NOTEBOOK, "LABELS", ns)
    _exec_cell(SWEEP_NOTEBOOK, "FL_SPECS", ns)
    close = np.full(80, 100.0)
    frame = _frame(80, close=close, high=close + 0.05, low=close - 0.05, atr=2.0)
    labeled = ns["apply_label_spec"](
        frame, ns["label_spec_by_id"]("L7"), ns["compute_opportunity_labels"]
    )
    assert ns["l7_timeouts_are_scored"](labeled)
    long_c = labeled["long_code"].to_numpy(dtype=np.float64)
    short_c = labeled["short_code"].to_numpy(dtype=np.float64)
    labels = labeled["trade_label"].to_numpy(dtype=np.int64)
    timeout = (
        np.isfinite(long_c)
        & np.isfinite(short_c)
        & (long_c == float(ns["NEITHER"]))
        & (short_c == float(ns["NEITHER"]))
    )
    assert timeout.any()
    assert np.all(labels[timeout] == ns["LABEL_NO_TRADE"])
    dir_mask = labeled["dir_train_mask"].to_numpy()
    assert not np.any(dir_mask[timeout])


def test_f7_distances_follow_spec_tp_sl() -> None:
    ns = _exec_specs()
    rng = np.random.default_rng(0)
    close = 100.0 + np.cumsum(rng.normal(0.0, 0.4, size=120))
    frame = _frame(120, close=close, high=close + 0.8, low=close - 0.8, atr=1.5)
    four = ns["add_f7_features"](frame, tp_atr_mult=4.0, sl_atr_mult=2.0)
    six = ns["add_f7_features"](frame, tp_atr_mult=6.0, sl_atr_mult=3.0)
    pct = ns["add_f7_features"](frame, tp_pct=0.008, sl_pct=0.004)
    ratio = (
        four["rv24_over_tp"].to_numpy(dtype=np.float64)
        / six["rv24_over_tp"].to_numpy(dtype=np.float64)
    )
    finite = np.isfinite(ratio)
    assert finite.any()
    np.testing.assert_allclose(ratio[finite], 6.0 / 4.0, rtol=1e-10, atol=1e-10)
    assert not np.allclose(
        four["rv24_over_tp"].to_numpy(), pct["rv24_over_tp"].to_numpy(), equal_nan=True
    )
    l0_kw = ns["spec_f7_kwargs"](ns["label_spec_by_id"]("L0"))
    l3_kw = ns["spec_f7_kwargs"](ns["label_spec_by_id"]("L3"))
    assert l0_kw["tp_atr_mult"] == 4.0
    assert l3_kw["tp_atr_mult"] == 6.0


def test_stage_b_row_schema_rejects_test_metrics() -> None:
    ns = _exec_specs()
    valid = {
        "label_id": "L0",
        "feature_family": "F0",
        "wf_r_expectancy": -0.12,
        "wf_tstat": -0.4,
        "wf_positive_share": 0.0,
        "n_LONG": 120.0,
        "n_SHORT": 50.0,
    }
    assert ns["validate_stage_b_row"](valid) is True
    with pytest.raises(ValueError, match="test metrics"):
        ns["validate_stage_b_row"]({**valid, "test_r_expectancy": -0.001})
    with pytest.raises(ValueError, match="test metrics"):
        ns["validate_stage_b_row"]({**valid, "test_precision_LONG": 0.4})
    with pytest.raises(ValueError, match="missing fields"):
        ns["validate_stage_b_row"]({"label_id": "L0"})


def _l0_row(family: str, *, wf_r: float, dir_auc: float = 0.55) -> Dict[str, Any]:
    return {
        "label_id": "L0",
        "label_group": "L0",
        "feature_family": family,
        "wf_r_expectancy": wf_r,
        "dir_auc": dir_auc,
        "n_LONG": 120.0,
        "n_SHORT": 50.0,
    }


def test_diagnosis_vol_features() -> None:
    ns = _exec_specs()
    table = [
        _l0_row("F0", wf_r=-0.1),
        _l0_row("F1", wf_r=-0.11),
        _l0_row("F2", wf_r=-0.09),
        _l0_row("F3", wf_r=0.05),
        _l0_row("F4", wf_r=-0.08),
        _l0_row("F5", wf_r=-0.07),
        _l0_row("F6", wf_r=-0.12),
        _l0_row("F7", wf_r=0.04),
    ]
    assert ns["diagnose_sweep"](table) == ns["DIAGNOSIS_VOL_FEATURES"]


def test_diagnosis_first_touch_rule() -> None:
    ns = _exec_specs()
    table = [
        _l0_row("F0", wf_r=-0.10),
        _l0_row("F7", wf_r=-0.08),
        {
            "label_id": "L1_2_2",
            "label_group": "L1",
            "feature_family": "F0",
            "wf_r_expectancy": 0.03,
            "dir_auc": 0.56,
        },
    ]
    assert ns["diagnose_sweep"](table) == ns["DIAGNOSIS_FIRST_TOUCH"]


def test_diagnosis_barrier_absent() -> None:
    ns = _exec_specs()
    table = [_l0_row(fam, wf_r=-0.10) for fam in ("F0", "F1", "F3", "F7")]
    assert ns["diagnose_sweep"](table) == ns["DIAGNOSIS_BARRIER_ABSENT"]


def test_diagnosis_null_shuffle() -> None:
    ns = _exec_specs()
    table = [_l0_row("F0", wf_r=0.02), _l0_row("F7", wf_r=0.01)]
    assert ns["diagnose_sweep"](table, shuffle_best_r=0.05) == ns["DIAGNOSIS_NULL"]


def test_diagnosis_short_side_absent() -> None:
    ns = _exec_specs()
    table = [
        _l0_row("F0", wf_r=0.04, dir_auc=0.50),
        _l0_row("F1", wf_r=0.03, dir_auc=0.49),
        _l0_row("F7", wf_r=0.02, dir_auc=0.51),
    ]
    assert ns["diagnose_sweep"](table) == ns["DIAGNOSIS_SHORT_ABSENT"]


def test_stage_a_keep_uses_sides_not_exclusive_expectancy() -> None:
    ns = _exec_specs()
    keep = ns["stage_a_should_keep"]
    both_sides = {
        "class_mix": {"LONG": 0.22, "SHORT": 0.18, "NO_TRADE": 0.60},
        "exclusive_long_expectancy_pct": -0.01,
        "exclusive_short_expectancy_pct": -0.01,
        "opportunity_rate": 0.40,
        "breakeven_win_rate": 0.40,
        "base_long_tp_rate": 0.35,
        "base_short_tp_rate": 0.20,
    }
    assert keep(both_sides)
    assert not keep(
        {
            "class_mix": {"LONG": 0.22, "SHORT": 0.05, "NO_TRADE": 0.73},
            "exclusive_long_expectancy_pct": 0.02,
            "exclusive_short_expectancy_pct": 0.02,
            "opportunity_rate": 0.40,
        }
    )
    degen = {**both_sides, "opportunity_rate": 0.99, "opportunity_degenerate": True}
    assert not keep(degen)
    assert keep(degen, allow_degenerate_opp=True)


def test_ranking_prefers_equal_r_not_wider_percent_bracket() -> None:
    ns = _exec_specs()
    ranked = ns["select_top_pairs"](
        [
            {
                "label_id": "L3",
                "feature_family": "F0",
                "wf_r_expectancy": 0.20,
                "val_expectancy": 0.009,
            },
            {
                "label_id": "L0",
                "feature_family": "F7",
                "wf_r_expectancy": 0.35,
                "val_expectancy": 0.004,
            },
        ],
        k=1,
    )
    assert ranked[0]["label_id"] == "L0"
    same_r = ns["select_top_pairs"](
        [
            {
                "label_id": "L3",
                "feature_family": "F0",
                "wf_r_expectancy": 0.50,
                "val_expectancy": 0.009,
            },
            {
                "label_id": "L0",
                "feature_family": "F7",
                "wf_r_expectancy": 0.50,
                "val_expectancy": 0.004,
            },
        ],
        k=2,
    )
    assert [r["wf_r_expectancy"] for r in same_r] == [0.50, 0.50]


def test_weighted_r_requires_min_signals() -> None:
    ns = _exec_specs()
    pnl = np.array([0.02, -0.01, 0.02, -0.01], dtype=np.float64)
    sl = np.full(4, 0.01, dtype=np.float64)
    pred = np.array([0, 0, 1, 1], dtype=np.int64)
    scored = ns["weighted_r_score"](pred, pnl, -pnl, sl, min_signals=100)
    assert scored["r_expectancy"] == float("-inf")
    scored_ok = ns["weighted_r_score"](pred, pnl, -pnl, sl, min_signals=1)
    assert np.isfinite(scored_ok["r_expectancy"])


def test_attach_heads_split_opportunity_and_direction() -> None:
    ns: Dict[str, Any] = {}
    _exec_cell(SOURCE_NOTEBOOK, "LABELS", ns)
    _exec_cell(SWEEP_NOTEBOOK, "FL_SPECS", ns)
    close = np.linspace(100.0, 110.0, 60)
    frame = _frame(60, close=close, high=close + 3.0, low=close - 3.0, atr=1.0)
    labeled = ns["apply_label_spec"](
        frame, ns["label_spec_by_id"]("L0"), ns["compute_opportunity_labels"]
    )
    valid = labeled["trade_label"].to_numpy() >= 0
    opp = labeled["opp_label"].to_numpy(dtype=np.float64)
    assert set(np.unique(opp[valid])).issubset({0.0, 1.0})
    dir_mask = labeled["dir_train_mask"].to_numpy()
    names = labeled["trade_name"].to_numpy()
    assert np.all(np.isin(names[dir_mask], ["LONG", "SHORT"]))
    assert np.all(~dir_mask[names == "NO_TRADE"])


@pytest.mark.skipif(
    importlib.util.find_spec("xgboost") is None, reason="xgboost not installed"
)
def test_fit_opp_dir_uses_binary_direction_head() -> None:
    ns = _exec_specs()
    rng = np.random.default_rng(0)
    x = rng.normal(size=(160, 5)).astype(np.float32)
    opp = rng.integers(0, 2, size=160).astype(np.float64)
    y = rng.integers(0, 2, size=160)
    dir_ok = np.ones(160, dtype=bool)
    cfg = {
        "max_depth": 2,
        "learning_rate": 0.3,
        "min_leaf": 1,
        "threads_per_model": 1,
    }
    opp_clf, dir_clf = ns["_fit_opp_dir"](
        x,
        opp,
        y,
        dir_ok,
        config=cfg,
        n_estimators=8,
        seed=42,
        skip_opp=False,
    )
    p_opp, p_dir = ns["_predict_combined"](opp_clf, dir_clf, x, False)
    assert p_opp.shape == (160,)
    assert p_dir.shape == (160, 3)
    np.testing.assert_allclose(p_dir[:, 0] + p_dir[:, 1], 1.0, atol=1e-6)


def test_specs_module_matches_injected_cell() -> None:
    cell = _cell_named(SWEEP_NOTEBOOK, "FL_SPECS")
    module = SPECS_MODULE.read_text(encoding="utf-8")
    assert module in cell
