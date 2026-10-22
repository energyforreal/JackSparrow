"""Phase 1 integrity checks for the 30-minute forecast research set."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research.forecast_30m.integrity import (
    HORIZON_BARS,
    audit_frame,
    audit_path,
    chronological_split,
    source_decision,
    to_epoch_seconds,
    write_audit_outputs,
)

_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "research" / "forecast_30m" / "integrity.py"
)


def _bars(
    count: int,
    *,
    start: str = "2024-01-01T00:00:00Z",
    drop_offsets: tuple[int, ...] = (),
) -> pd.DataFrame:
    stamps = pd.date_range(start, periods=count, freq="30min", tz="UTC")
    keep = [offset for offset in range(count) if offset not in drop_offsets]
    stamps = stamps[keep]
    price = np.full(len(stamps), 100.0)
    return pd.DataFrame(
        {
            "time": stamps,
            "open": price,
            "high": price + 1.0,
            "low": price - 1.0,
            "close": price + 0.25,
            "volume": np.full(len(stamps), 10.0),
        }
    )


def test_epoch_seconds_are_utc() -> None:
    series = pd.Series([pd.Timestamp("2024-01-01T00:00:00Z")])
    assert int(to_epoch_seconds(series)[0]) == 1_704_067_200


def test_regular_series_only_the_tail_is_ineligible() -> None:
    report = audit_frame(_bars(48))
    assert report["gaps"] == 0
    assert report["completeness"] == 1.0
    assert report["invalid_ohlc_rows"] == 0
    assert report["eligible_rows"] == 48 - HORIZON_BARS
    assert report["tail_ineligible_rows"] == HORIZON_BARS
    assert report["gap_ineligible_rows"] == 0
    assert source_decision(report, min_rows=1)["accepted"] is True


def test_duplicate_timestamp_is_reported() -> None:
    frame = _bars(6)
    frame = pd.concat([frame, frame.iloc[[2]]], ignore_index=True)
    report = audit_frame(frame)
    assert report["duplicate_timestamp_values"] == 1
    assert report["duplicate_extra_rows"] == 1
    decision = source_decision(report, min_rows=1)
    assert decision["accepted"] is False
    assert "duplicate_timestamps" in decision["reasons"]


def test_high_below_low_is_invalid() -> None:
    frame = _bars(6)
    frame.loc[3, "high"] = 90.0
    frame.loc[3, "low"] = 95.0
    report = audit_frame(frame)
    assert report["invalid_ohlc_rows"] == 1
    assert report["invalid_ohlc_reasons"]["high_below_low"] == 1
    decision = source_decision(report, min_rows=1)
    assert "invalid_ohlc" in decision["reasons"]


def test_missing_bar_makes_crossing_horizons_ineligible() -> None:
    frame = _bars(40, drop_offsets=(10,))
    report = audit_frame(frame)
    assert report["deduplicated_rows"] == 39
    assert report["gaps"] == 1
    assert report["gap_examples"][0]["missing_bars"] == 1
    assert report["gap_ineligible_rows"] == 10
    assert report["eligible_rows"] == 5
    assert report["tail_ineligible_rows"] == 24
    decision = source_decision(report, min_rows=1)
    assert "irregular_intervals" in decision["reasons"]


def test_short_series_is_not_a_provisional_source() -> None:
    decision = source_decision(audit_frame(_bars(48)))
    assert decision["accepted"] is False
    assert decision["reasons"] == ["row_count_below_minimum"]


def test_chronological_split_reserves_the_last_fraction() -> None:
    frame = _bars(100)
    epochs = to_epoch_seconds(frame["time"])
    split = chronological_split(epochs, holdout_fraction=0.15)
    assert split["development_rows"] == 85
    assert split["holdout_rows"] == 15
    assert split["development_end_exclusive"] == split["holdout_start"]
    assert split["holdout_status"] == "unread"
    assert split["purge_bars"] == HORIZON_BARS
    assert split["holdout_start"] == pd.Timestamp(frame.loc[85, "time"]).isoformat()


def test_audit_path_writes_hash_and_unread_holdout(tmp_path: Path) -> None:
    source = tmp_path / "btcusd_30m.parquet"
    _bars(80).to_parquet(source, index=False)
    report = audit_path(source, min_rows=1)
    assert len(report["source_sha256"]) == 64
    assert report["source_decision"]["accepted"] is True
    audit_out = tmp_path / "data_audit.json"
    splits_out = tmp_path / "splits.yaml"
    write_audit_outputs(report, audit_out=audit_out, splits_out=splits_out)
    loaded = json.loads(audit_out.read_text(encoding="utf-8"))
    text = splits_out.read_text(encoding="utf-8")
    assert loaded["eligible_rows"] == 80 - HORIZON_BARS
    assert "status: unread" in text
    assert f"sha256: {report['source_sha256']}" in text
    assert "provisional: true" in text


def test_missing_column_raises() -> None:
    frame = _bars(4).drop(columns=["volume"])
    with pytest.raises(ValueError, match="volume"):
        audit_frame(frame)


def test_research_module_does_not_touch_live_trading() -> None:
    source = _MODULE_PATH.read_text(encoding="utf-8")
    for forbidden in ("fusion_node", "exchange_gateway", "model_storage", "place_order"):
        assert forbidden not in source
