"""Delta collection, pagination, and quality reports."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from research.swinging.data import collect_resolution, collect_series, fetch_series
from research.swinging.quality import (
    compare_native_to_resampled,
    drop_invalid_ohlc,
    gap_report,
    normalize_ohlcv,
)
from scripts.colab import transformer_data
from tests.unit.swinging_fixtures import make_ohlcv


def test_fetch_series_paginates_backward(monkeypatch) -> None:
    start = 1_700_000_000
    candles = [
        {
            "time": start + index * 300,
            "open": 1.0,
            "high": 2.0,
            "low": 0.5,
            "close": 1.2,
            "volume": 3.0,
        }
        for index in range(6)
    ]
    calls: list[tuple[int, int]] = []

    def fake_page(url, *, symbol, resolution, start_ts, end_ts):
        calls.append((int(start_ts), int(end_ts)))
        return [row for row in candles if int(start_ts) <= int(row["time"]) <= int(end_ts)]

    monkeypatch.setattr(transformer_data, "_request_candle_page", fake_page)
    monkeypatch.setattr(transformer_data.time, "sleep", lambda *_args, **_kwargs: None)

    def fetcher(symbol, resolution, start_ts, end_ts, base_url):
        return transformer_data.fetch_candles(
            symbol,
            resolution,
            start_ts,
            end_ts,
            base_url,
            page_bars=2,
        )

    frame, error = fetch_series(
        "ohlcv",
        "5m",
        datetime.fromtimestamp(start, tz=timezone.utc),
        datetime.fromtimestamp(start + 6 * 300, tz=timezone.utc),
        fetcher=fetcher,
    )
    assert error is None
    assert len(calls) >= 2
    assert len(frame) == 6
    assert frame["time"].is_unique


def test_incremental_append_and_missing_open_interest(tmp_path) -> None:
    first = make_ohlcv(4)
    second = make_ohlcv(4, start="2024-01-01 00:20")

    def fetcher(symbol, resolution, start_ts, end_ts, base_url):
        if str(symbol).startswith("OI:"):
            raise RuntimeError("open interest history is empty")
        if str(symbol) != "BTCUSD":
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
        start = pd.to_datetime(start_ts, unit="s", utc=True)
        end = pd.to_datetime(end_ts, unit="s", utc=True)
        pool = pd.concat([first, second], ignore_index=True)
        pool["time"] = pd.to_datetime(pool["time"], utc=True)
        selected = pool.loc[(pool["time"] >= start) & (pool["time"] < end)]
        return selected.reset_index(drop=True)

    first_manifest = collect_series(
        tmp_path,
        "5m",
        "ohlcv",
        fetcher=fetcher,
        incremental=False,
        start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end=datetime(2024, 1, 1, 0, 20, tzinfo=timezone.utc),
    )
    assert first_manifest["rows"] == 4
    second_manifest = collect_series(
        tmp_path,
        "5m",
        "ohlcv",
        fetcher=fetcher,
        incremental=True,
        end=datetime(2024, 1, 1, 1, tzinfo=timezone.utc),
    )
    assert second_manifest["rows"] == 8
    assert second_manifest["earliest"].startswith("2024-01-01")
    report = collect_resolution(
        tmp_path,
        "5m",
        fetcher=fetcher,
        incremental=True,
    )
    assert report["manifests"]["oi"]["rows"] == 0
    assert report["manifests"]["oi"]["source_error"]
    assert report["manifests"]["ohlcv"]["rows"] == 8


def test_ohlc_gaps_and_resample_agreement() -> None:
    frame = make_ohlcv(48)
    broken = frame.copy()
    broken.loc[3, "high"] = broken.loc[3, "low"] - 1.0
    cleaned, removed = drop_invalid_ohlc(normalize_ohlcv(broken))
    assert removed == 1
    assert len(cleaned) == 47
    gapped = frame.drop(index=10).reset_index(drop=True)
    assert gap_report(gapped, "5m")["gaps"] >= 1
    native = make_ohlcv(4, freq="1h")
    # Rebuild the native hour from the same 5-minute construction the checker uses.
    from research.cpr_mtf.bars import resample_ohlcv

    resampled = resample_ohlcv(frame, "1h")
    report = compare_native_to_resampled(resampled, frame, "1h")
    assert report["overlap"] == len(resampled)
    assert report["close_mismatches"] == 0
    shifted = resampled.copy()
    shifted.loc[0, "close"] = float(shifted.loc[0, "close"]) + 50.0
    mismatch = compare_native_to_resampled(shifted, frame, "1h")
    assert mismatch["close_mismatches"] == 1
    assert native["time"].dt.tz is not None
