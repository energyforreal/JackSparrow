"""Load the 10m opportunity Colab and execute only its label cell."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import pytest

NOTEBOOK = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "colab"
    / "transformer_btcusd_opportunity_10m.ipynb"
)
FORBIDDEN = (
    "feature_store",
    "scripts.colab",
    "train_mtf_fusion",
    "MtfFusionTransformer",
    "MarketTransformer",
    "fusion_policy",
    "git clone",
    "agent.model_storage",
)
# Fixtures below are 20 bars long with ATR 10 on a 100 close; use a tight,
# short bracket so single-bar excursions of 16 / 12 hit TP / SL.
BRACKET: Dict[str, Any] = {"tp_mult": 1.5, "sl_mult": 1.0, "horizon_bars": 3}


def _cell_text(cell: Dict[str, Any]) -> str:
    source = cell.get("source", [])
    if isinstance(source, str):
        return source
    return "".join(source)


def _load_notebook() -> Dict[str, Any]:
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))


def _code_cells() -> list[str]:
    nb = _load_notebook()
    return [_cell_text(c) for c in nb["cells"] if c.get("cell_type") == "code"]


def _cell_named(name: str) -> str:
    marker = f"# CELL: {name}"
    for source in _code_cells():
        if source.startswith(marker) or marker in source.splitlines()[0:3]:
            return source
    raise AssertionError(f"Notebook is missing {marker}")


def _exec_labels() -> Dict[str, Any]:
    ns: Dict[str, Any] = {}
    exec(_cell_named("LABELS"), ns, ns)
    return ns


def _frame(
    n: int = 20,
    *,
    close: np.ndarray | None = None,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    atr: float | np.ndarray = 10.0,
) -> pd.DataFrame:
    times = pd.date_range("2024-01-01", periods=n, freq="10min", tz="UTC")
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


def test_notebook_is_the_training_script() -> None:
    assert NOTEBOOK.is_file()
    sources = _code_cells()
    joined = "\n".join(sources)
    assert "# CELL: LABELS" in joined
    assert "# CELL: GATE" in joined
    assert "# CELL: TRAIN" in joined
    assert "# CELL: EVAL" in joined
    assert "ready_to_promote" in joined
    assert "LogisticRegression" in joined
    assert "Ridge" in joined
    assert "RandomForestClassifier" in joined
    assert "XGBClassifier" in joined
    assert "LGBMClassifier" in joined
    assert "CatBoostClassifier" in joined
    assert "ThreadPoolExecutor" in joined
    assert "import time" in _cell_named("ENV")
    assert "exclusive_long_expectancy_pct" in joined
    assert "always_in_long_expectancy_pct" in joined
    assert "long_path_codes" in joined
    assert "expectancy_rank_score" in joined
    # Decision rule, ensemble candidate and promotion gate must be present.
    assert "choose_thresholds" in joined
    assert "apply_thresholds" in joined
    assert "ENSEMBLE_NAME" in joined
    assert "promotion_gate" in joined
    assert "tp_cost_ratio" in joined
    # Probabilities are thresholded; class re-weighting would distort them.
    assert "class_weight" not in _cell_named("MODEL")
    assert "auto_class_weights" not in _cell_named("MODEL")
    for needle in FORBIDDEN:
        assert needle not in joined, needle


def test_gate_cell_appears_before_train_cell() -> None:
    names: list[str] = []
    for source in _code_cells():
        first = source.lstrip().splitlines()[0] if source.strip() else ""
        if first.startswith("# CELL:"):
            names.append(first.replace("# CELL:", "").strip())
    assert names.index("GATE") < names.index("TRAIN")
    assert names.index("LABELS") < names.index("GATE")
    assert names.index("EVAL") > names.index("TRAIN")
    assert names.index("PROMOTE") > names.index("EVAL")
    assert names.index("EXPORT") > names.index("PROMOTE")


def _exec_config() -> Dict[str, Any]:
    ns: Dict[str, Any] = {"Dict": Dict, "Any": Any, "Tuple": Tuple, "json": json}
    exec(_cell_named("CONFIG"), ns, ns)
    return ns


def test_config_purge_covers_horizon() -> None:
    cfg = _exec_config()["CONFIG"]
    assert int(cfg["purge_bars"]) > int(cfg["horizon_bars"])
    assert float(cfg["tp_atr_mult"]) > float(cfg["sl_atr_mult"])
    assert float(cfg["min_tp_cost_ratio"]) >= 3.0


def test_config_derives_horizon_from_resolution() -> None:
    ns = _exec_config()
    cfg = ns["CONFIG"]
    assert cfg["resolution"] == "10m"
    assert int(cfg["horizon_minutes"]) == 240
    assert int(cfg["bar_minutes"]) == 10
    assert int(cfg["horizon_bars"]) == 24
    assert int(cfg["purge_bars"]) == 25
    assert cfg["export_dir"] == "export/opportunity_10m"
    expected = (("5m", 5, 48), ("15m", 15, 16), ("30m", 30, 8), ("1h", 60, 4))
    for res, bar_min, horizon_bars in expected:
        trial = dict(cfg)
        trial["resolution"] = res
        trial["horizon_minutes"] = 240
        ns["apply_resolution_config"](trial)
        assert trial["bar_minutes"] == bar_min
        assert trial["horizon_bars"] == horizon_bars
        assert trial["purge_bars"] == horizon_bars + 1
        assert trial["export_dir"] == f"export/opportunity_{res}"
    assert set(ns["RESOLUTION_MINUTES"]) >= {"5m", "10m", "15m", "30m", "1h"}


def test_fetch_map_covers_sweep_resolutions() -> None:
    fetch = _cell_named("FETCH")
    for res in ("5m", "10m", "15m", "30m", "1h"):
        assert f'"{res}":' in fetch
    assert "raw_bars = fetch_candles" in fetch
    assert "CONFIG[\"resolution\"]" in fetch or "CONFIG['resolution']" in fetch
    assert "resolution_5m" not in fetch
    bars_cell = _cell_named("BARS")
    assert "build_10m_ohlcv_from_5m" in bars_cell
    assert "bars_10m" not in bars_cell
    joined = "\n".join(_code_cells())
    assert "bars_10m" not in joined


def _reference_labels(
    ns: Dict[str, Any], frame: pd.DataFrame, *, tp_mult: float, sl_mult: float, horizon_bars: int
) -> np.ndarray:
    """Per-bar reference: walk every path with ``tp_sl_from_path``."""
    close = frame["close"].to_numpy(float)
    high = frame["high"].to_numpy(float)
    low = frame["low"].to_numpy(float)
    atr = frame["atr"].to_numpy(float)
    n = len(frame)
    out = np.full(n, ns["LABEL_UNLABELED"], dtype=np.int64)
    for i in range(n - horizon_bars):
        if not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        fh = high[i + 1 : i + 1 + horizon_bars]
        fl = low[i + 1 : i + 1 + horizon_bars]
        lc = ns["tp_sl_from_path"](fh, fl, close[i], atr[i], tp_mult, sl_mult, "LONG")
        sc = ns["tp_sl_from_path"](fh, fl, close[i], atr[i], tp_mult, sl_mult, "SHORT")
        l_win = lc == ns["TP_FIRST"]
        s_win = sc == ns["TP_FIRST"]
        if l_win and not s_win:
            out[i] = ns["LABEL_LONG"]
        elif s_win and not l_win:
            out[i] = ns["LABEL_SHORT"]
        else:
            out[i] = ns["LABEL_NO_TRADE"]
    return out


def test_vectorised_labels_match_per_bar_walk() -> None:
    ns = _exec_labels()
    rng = np.random.default_rng(7)
    n = 400
    close = 100.0 + np.cumsum(rng.normal(0.0, 1.5, n))
    high = close + np.abs(rng.normal(0.0, 2.0, n))
    low = close - np.abs(rng.normal(0.0, 2.0, n))
    atr = np.full(n, 3.0)
    atr[10] = 0.0
    frame = _frame(n, close=close, high=high, low=low, atr=atr)
    for tp, sl, k in ((1.5, 1.0, 3), (4.0, 2.0, 24), (2.0, 2.0, 6)):
        labeled = ns["compute_opportunity_labels"](frame, tp_mult=tp, sl_mult=sl, horizon_bars=k)
        ref = _reference_labels(ns, frame, tp_mult=tp, sl_mult=sl, horizon_bars=k)
        assert np.array_equal(labeled["trade_label"].to_numpy(), ref), (tp, sl, k)


def test_ambiguous_is_scored_as_stop_in_pnl() -> None:
    ns = _exec_labels()
    n = 20
    close = np.full(n, 100.0)
    high = close + 0.2
    low = close - 0.2
    high[1] = 116.0
    low[1] = 88.0
    labeled = ns["compute_opportunity_labels"](
        _frame(n, close=close, high=high, low=low), **BRACKET
    )
    assert float(labeled.loc[0, "long_code"]) == float(ns["AMBIGUOUS"])
    assert float(labeled.loc[0, "long_pnl_pct"]) == pytest.approx(-0.10)
    assert float(labeled.loc[0, "tp_pct"]) == pytest.approx(0.15)
    assert float(labeled.loc[0, "sl_pct"]) == pytest.approx(0.10)


def test_long_only_win() -> None:
    ns = _exec_labels()
    n = 20
    close = np.full(n, 100.0)
    high = close + 0.2
    low = close - 0.2
    high[1] = 116.0
    labeled = ns["compute_opportunity_labels"](
        _frame(n, close=close, high=high, low=low), **BRACKET
    )
    assert int(labeled.loc[0, "trade_label"]) == int(ns["LABEL_LONG"])
    assert float(labeled.loc[0, "long_result"]) == 1.0
    assert float(labeled.loc[0, "short_result"]) == 0.0
    assert float(labeled.loc[0, "long_code"]) == float(ns["TP_FIRST"])


def test_short_only_win() -> None:
    ns = _exec_labels()
    n = 20
    close = np.full(n, 100.0)
    high = close + 0.2
    low = close - 0.2
    low[1] = 84.0
    labeled = ns["compute_opportunity_labels"](
        _frame(n, close=close, high=high, low=low), **BRACKET
    )
    assert int(labeled.loc[0, "trade_label"]) == int(ns["LABEL_SHORT"])
    assert float(labeled.loc[0, "short_result"]) == 1.0
    assert float(labeled.loc[0, "long_result"]) == 0.0
    assert float(labeled.loc[0, "short_code"]) == float(ns["TP_FIRST"])


def test_both_sides_win_is_no_trade() -> None:
    ns = _exec_labels()
    n = 20
    close = np.full(n, 100.0)
    high = close + 0.2
    low = close - 0.2
    high[1] = 106.0
    low[1] = 94.0
    labeled = ns["compute_opportunity_labels"](
        _frame(n, close=close, high=high, low=low),
        tp_mult=0.5,
        sl_mult=2.0,
        horizon_bars=3,
    )
    assert int(labeled.loc[0, "long_result"]) == 1
    assert int(labeled.loc[0, "short_result"]) == 1
    assert int(labeled.loc[0, "trade_label"]) == int(ns["LABEL_NO_TRADE"])


def test_neither_side_is_no_trade() -> None:
    ns = _exec_labels()
    labeled = ns["compute_opportunity_labels"](_frame(20), **BRACKET)
    assert int(labeled.loc[0, "trade_label"]) == int(ns["LABEL_NO_TRADE"])
    assert float(labeled.loc[0, "long_result"]) == 0.0
    assert float(labeled.loc[0, "short_result"]) == 0.0
    assert float(labeled.loc[0, "long_code"]) == float(ns["NEITHER"])
    assert float(labeled.loc[0, "short_code"]) == float(ns["NEITHER"])


def test_same_candle_double_touch_is_not_a_win() -> None:
    ns = _exec_labels()
    n = 20
    close = np.full(n, 100.0)
    high = close + 0.2
    low = close - 0.2
    high[1] = 116.0
    low[1] = 88.0
    labeled = ns["compute_opportunity_labels"](
        _frame(n, close=close, high=high, low=low), **BRACKET
    )
    assert float(labeled.loc[0, "long_code"]) == float(ns["AMBIGUOUS"])
    assert float(labeled.loc[0, "long_result"]) == 0.0
    assert int(labeled.loc[0, "trade_label"]) == int(ns["LABEL_NO_TRADE"])


def test_signal_bar_high_low_excluded_from_path() -> None:
    ns = _exec_labels()
    n = 20
    close = np.full(n, 100.0)
    high = close + 0.2
    low = close - 0.2
    high[0] = 200.0
    low[0] = 1.0
    labeled = ns["compute_opportunity_labels"](
        _frame(n, close=close, high=high, low=low), **BRACKET
    )
    assert float(labeled.loc[0, "upside"]) == pytest.approx(0.02)
    assert float(labeled.loc[0, "downside"]) == pytest.approx(0.02)
    assert int(labeled.loc[0, "trade_label"]) == int(ns["LABEL_NO_TRADE"])


def test_upside_downside_match_three_candle_window() -> None:
    ns = _exec_labels()
    n = 20
    close = np.full(n, 100.0)
    high = close + 0.1
    low = close - 0.1
    high[1] = 100.4
    high[2] = 106.5
    high[3] = 101.0
    low[1] = 99.0
    low[2] = 97.6
    low[3] = 99.5
    labeled = ns["compute_opportunity_labels"](
        _frame(n, close=close, high=high, low=low), **BRACKET
    )
    assert float(labeled.loc[0, "upside"]) == pytest.approx(0.65)
    assert float(labeled.loc[0, "downside"]) == pytest.approx(0.24)


def test_last_three_rows_unlabeled() -> None:
    ns = _exec_labels()
    labeled = ns["compute_opportunity_labels"](_frame(20), **BRACKET)
    assert (labeled["trade_label"].iloc[-3:] == ns["LABEL_UNLABELED"]).all()
    assert labeled["upside"].iloc[-3:].isna().all()
    assert int(labeled.loc[16, "trade_label"]) != int(ns["LABEL_UNLABELED"])


def test_non_positive_atr_unlabeled() -> None:
    ns = _exec_labels()
    n = 20
    atr = np.full(n, 10.0)
    atr[4] = 0.0
    labeled = ns["compute_opportunity_labels"](_frame(n, atr=atr), **BRACKET)
    assert int(labeled.loc[4, "trade_label"]) == int(ns["LABEL_UNLABELED"])
    assert pd.isna(labeled.loc[4, "upside"])
    assert int(labeled.loc[5, "trade_label"]) != int(ns["LABEL_UNLABELED"])


def test_tp_sl_same_bar_helper() -> None:
    ns = _exec_labels()
    code = ns["tp_sl_from_path"](
        np.array([116.0]),
        np.array([88.0]),
        100.0,
        10.0,
        1.5,
        1.0,
        "LONG",
    )
    assert int(code) == int(ns["AMBIGUOUS"])


def _exec_gate_helpers() -> Dict[str, Any]:
    ns: Dict[str, Any] = {
        "Dict": Dict,
        "List": List,
        "Any": Any,
        "json": json,
        "Path": Path,
        "np": np,
        "pd": pd,
        "CONFIG": {"tp_atr_mult": 1.5, "sl_atr_mult": 1.0},
    }
    exec(_cell_named("LABELS"), ns, ns)
    gate_src = _cell_named("GATE")
    helpers = gate_src.split("EXPORT_DIR = Path")[0]
    exec(helpers, ns, ns)
    return ns


def _entry_mix_frame(n: int = 60) -> pd.DataFrame:
    """Exclusive LONG/SHORT every 6th bar; remaining bars stop-out the long side."""
    close = np.full(n, 100.0)
    high = close + 0.2
    low = close - 0.2
    for i in range(n - 3):
        if i % 6 == 0:
            high[i + 1] = 116.0
        elif i % 6 == 1:
            low[i + 1] = 84.0
        else:
            low[i + 1] = 88.0
    return _frame(n, close=close, high=high, low=low)


def test_gate_uses_exclusive_expectancy_not_always_in() -> None:
    ns = _exec_gate_helpers()
    labeled = ns["compute_opportunity_labels"](_entry_mix_frame(60), **BRACKET)
    report = ns["summarize_label_gate"](
        labeled,
        train_fraction=1.0,
        round_trip_cost_pct=0.0016,
        minority_rate=0.15,
        ambiguous_win_max=0.50,
    )
    assert "long_path_codes" in report
    assert "short_path_codes" in report
    for key in ("TP_FIRST", "SL_FIRST", "NEITHER", "AMBIGUOUS"):
        assert key in report["long_path_codes"]
        assert key in report["short_path_codes"]
    assert report["exclusive_long_expectancy_pct"] > 0.0
    assert report["exclusive_short_expectancy_pct"] > 0.0
    assert report["always_in_long_expectancy_pct"] < 0.0
    assert report["passed"] is True
    assert report["reasons"] == []


def test_gate_reports_bracket_economics() -> None:
    ns = _exec_gate_helpers()
    labeled = ns["compute_opportunity_labels"](_entry_mix_frame(60), **BRACKET)
    report = ns["summarize_label_gate"](
        labeled,
        train_fraction=1.0,
        round_trip_cost_pct=0.0016,
        minority_rate=0.15,
        ambiguous_win_max=0.50,
        min_tp_cost_ratio=4.0,
    )
    # ATR 10 on a 100 close: TP 1.5 ATR = 15% of price, SL = 10%.
    assert report["median_tp_pct"] == pytest.approx(0.15)
    assert report["median_sl_pct"] == pytest.approx(0.10)
    assert report["tp_cost_ratio"] == pytest.approx(0.15 / 0.0016)
    assert report["breakeven_win_rate"] == pytest.approx((0.10 + 0.0016) / 0.25)
    assert report["passed"] is True


def test_gate_fails_when_tp_barely_clears_cost() -> None:
    ns = _exec_gate_helpers()
    n = 60
    close = np.full(n, 100.0)
    high = close + 0.0002
    low = close - 0.0002
    # ATR 0.01 -> TP 1.5 ATR = 0.015% of price, far below 4x a 0.16% cost.
    for i in range(n - 3):
        if i % 6 == 0:
            high[i + 1] = 100.016
        elif i % 6 == 1:
            low[i + 1] = 99.984
        else:
            low[i + 1] = 99.988
    frame = _frame(n, close=close, high=high, low=low, atr=0.01)
    labeled = ns["compute_opportunity_labels"](frame, **BRACKET)
    report = ns["summarize_label_gate"](
        labeled,
        train_fraction=1.0,
        round_trip_cost_pct=0.0016,
        minority_rate=0.15,
        ambiguous_win_max=0.50,
        min_tp_cost_ratio=4.0,
    )
    assert report["passed"] is False
    assert "tp_distance_below_cost_ratio" in report["reasons"]
    assert report["tp_cost_ratio"] < 1.0


def test_gate_fails_when_exclusive_expectancy_missing() -> None:
    ns = _exec_gate_helpers()
    labeled = ns["compute_opportunity_labels"](_frame(20), **BRACKET)
    report = ns["summarize_label_gate"](
        labeled,
        train_fraction=1.0,
        round_trip_cost_pct=0.0016,
        minority_rate=0.15,
        ambiguous_win_max=0.50,
    )
    assert report["passed"] is False
    assert "exclusive_long_expectancy_not_positive" in report["reasons"]
    assert "exclusive_short_expectancy_not_positive" in report["reasons"]
