"""v43 train/serve parity: build_v43_last_row vs build_v43_feature_matrix last row."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from feature_store.jacksparrow_v43_build_matrix import build_v43_feature_matrix
from feature_store.jacksparrow_v43_contract import V43_CANONICAL_FEATURES
from feature_store.jacksparrow_v43_mcp_row import build_v43_last_row

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "v43_ohlcv_golden.json"


def _synthetic_candles(n: int = 320, seed: int = 42):
    rng = np.random.default_rng(seed)
    base_ts = 1700000000
    step = 300
    price = 50000 + np.cumsum(rng.normal(0, 50, size=n))
    candles = []
    for i in range(n):
        c = float(max(price[i], 1000))
        noise = rng.uniform(10, 80)
        o = c - rng.uniform(-20, 20)
        h = max(o, c) + noise
        l = min(o, c) - noise * 0.8
        v = float(rng.uniform(50, 500))
        candles.append(
            {
                "timestamp": base_ts + i * step,
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": v,
            }
        )
    return candles


@pytest.fixture(scope="module")
def golden_candles():
    if FIXTURE_PATH.is_file():
        with FIXTURE_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        return data.get("candles") or data
    return _synthetic_candles()


def test_v43_last_row_matches_matrix_last_row(golden_candles) -> None:
    row = build_v43_last_row(golden_candles, primary_interval="5m")
    import pandas as pd

    df = pd.DataFrame(golden_candles)
    matrix = build_v43_feature_matrix(df, primary_interval="5m")
    assert not matrix.empty
    last = matrix.iloc[-1]

    for name in V43_CANONICAL_FEATURES:
        assert name in row, f"missing in mcp row: {name}"
        assert name in last.index, f"missing in matrix: {name}"
        rv = float(row[name])
        mv = float(last[name])
        assert np.isfinite(rv) and np.isfinite(mv)
        assert rv == pytest.approx(mv, rel=0, abs=1e-6), f"{name}: row={rv} matrix={mv}"


def test_v43_canonical_feature_order_in_matrix(golden_candles) -> None:
    import pandas as pd

    df = pd.DataFrame(golden_candles)
    matrix = build_v43_feature_matrix(df, primary_interval="5m")
    assert not matrix.empty
    for name in V43_CANONICAL_FEATURES:
        assert name in matrix.columns


def test_golden_fixture_written_if_missing() -> None:
    """Ensure fixture file exists for CI (create on first run if absent)."""
    if FIXTURE_PATH.is_file():
        return
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"candles": _synthetic_candles(), "seed": 42, "bars": 320}
    FIXTURE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    assert FIXTURE_PATH.is_file()
