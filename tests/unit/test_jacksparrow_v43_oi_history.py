"""Tests for OI candle → ticker frame conversion."""

from __future__ import annotations

import pandas as pd

from feature_store.jacksparrow_v43_oi_history import oi_candles_to_ticker_frame


def test_oi_candles_to_ticker_frame_basic() -> None:
    ts = pd.date_range("2024-01-01", periods=5, freq="5min", tz="UTC")
    oi = pd.DataFrame({"timestamp": ts, "oi_contracts": [100.0, 110.0, 105.0, 120.0, 115.0]})
    out = oi_candles_to_ticker_frame(oi)
    assert len(out) == 5
    assert float(out["oi_contracts"].iloc[-1]) == 115.0


def test_oi_candles_to_ticker_frame_enriches_mark_spot() -> None:
    ts = pd.date_range("2024-01-01", periods=3, freq="5min", tz="UTC")
    oi = pd.DataFrame({"timestamp": ts, "close": [1000.0, 1010.0, 1020.0]})
    mark = pd.DataFrame({"timestamp": ts, "close": [50000.0, 50100.0, 50200.0]})
    spot = pd.DataFrame({"timestamp": ts, "close": [49900.0, 50000.0, 50100.0]})
    out = oi_candles_to_ticker_frame(oi, df_mark=mark, df_spot=spot)
    assert float(out["mark_price"].iloc[-1]) == 50200.0
    assert float(out["spot_price"].iloc[-1]) == 50100.0


def test_oi_candles_align_to_primary_timestamps() -> None:
    ts = pd.date_range("2024-01-01", periods=4, freq="5min", tz="UTC")
    primary = pd.DataFrame(
        {
            "timestamp": ts,
            "open": 1.0,
            "high": 1.0,
            "low": 1.0,
            "close": 100.0,
            "volume": 1.0,
        }
    )
    oi_raw = pd.DataFrame(
        {
            "timestamp": ts + pd.Timedelta(minutes=1),
            "close": [1000.0, 1010.0, 1020.0, 1030.0],
        }
    )
    out = oi_candles_to_ticker_frame(oi_raw, align_to=primary)
    assert len(out) == len(primary)
    assert float(out["oi_contracts"].max()) >= 1000.0


def test_oi_candles_empty_returns_empty_schema() -> None:
    out = oi_candles_to_ticker_frame(pd.DataFrame())
    assert list(out.columns) == list(
        (
            "timestamp",
            "oi_contracts",
            "oi_value_usd",
            "taker_buy_ratio",
            "mark_price",
            "spot_price",
            "best_bid",
            "best_ask",
            "bid_size",
            "ask_size",
            "price_band_upper",
            "price_band_lower",
            "predicted_funding_rate",
        )
    )
    assert len(out) == 0
