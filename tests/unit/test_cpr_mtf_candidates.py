"""Candidate generation, annotations, and breakout targets."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.cpr_mtf.annotations import (
    blank_annotation,
    breakout_rows,
    breakout_status,
    read_annotations,
    validate_annotation,
    write_annotations,
)
from research.cpr_mtf.candidates import (
    apply_quota,
    deduplicate_candidates,
    generate_candidates,
    proposal_record,
    propose_pairs,
    stack_candidates,
)
from research.cpr_mtf.contract import (
    MAX_CANDIDATES,
    MAX_CANDIDATES_PER_TIMEFRAME,
    MAX_PER_FAMILY,
    MODEL_CANDIDATE_FEATURES,
    PAIR_LIMIT,
)
from research.cpr_mtf.swings import detect_swings
from research.cpr_mtf.windows import prepare_timeframe
from tests.unit.cpr_mtf_support import manual_candidate, piecewise_closes, series_from_closes


def test_swing_is_invisible_until_the_reversal_prints() -> None:
    """The pivot stays hidden until price has reversed by 1.5 ATR."""
    base = series_from_closes(piecewise_closes([(60, 100.0), (15, 120.0), (2, 119.6)]))
    top = int(np.argmax(base["close"].to_numpy()))
    before = detect_swings(base, "15m", _atr(base))
    assert not any(
        swing.swing_type == "high" and swing.pivot_index >= top - 1 for swing in before
    )
    extended = _append_move(base, -2.0)
    matched = [
        swing
        for swing in detect_swings(extended, "15m", _atr(extended))
        if swing.swing_type == "high" and swing.pivot_index >= top - 1
    ]
    assert matched
    found = matched[0]
    assert found.confirmation_index > found.pivot_index
    assert found.prominence_atr >= 1.5
    hidden = extended.iloc[: found.confirmation_index]
    assert all(
        swing.pivot_index != found.pivot_index
        for swing in detect_swings(hidden, "15m", _atr(hidden))
    )


def test_double_flag_and_triangle_appear_when_their_last_swing_confirms() -> None:
    """Each synthetic formation is absent on the bar before its confirming swing."""
    cases = {
        "double": piecewise_closes(
            [(70, 100.0), (12, 120.0), (12, 100.0), (12, 120.0), (12, 100.0)]
        ),
        "flag": piecewise_closes(
            [
                (70, 110.0),
                (8, 100.0),
                (16, 150.0),
                (6, 135.0),
                (6, 142.0),
                (6, 132.0),
                (8, 138.0),
            ]
        ),
        "symmetrical_triangle": piecewise_closes(
            [
                (70, 100.0),
                (12, 130.0),
                (12, 100.0),
                (12, 120.0),
                (12, 110.0),
                (8, 118.0),
            ]
        ),
    }
    for pattern, closes in cases.items():
        end, prepared = _first_pattern(series_from_closes(closes), pattern)
        assert end is not None, _swing_text(prepared, pattern)
        hits = [item for item in _at(prepared, end) if item.pattern == pattern]
        assert any(item.last_confirmation_index == end for item in hits)
        assert all(item.pattern != pattern for item in _at(prepared, end - 1))


def test_repeated_doubles_respect_the_family_and_timeframe_caps() -> None:
    """A long run of similar peaks keeps two doubles and at most twelve proposals."""
    segments = [(60, 100.0)]
    for _ in range(8):
        segments.extend([(8, 120.0), (8, 100.0)])
    prepared = prepare_timeframe(series_from_closes(piecewise_closes(segments)), "15m")
    candidates = generate_candidates(
        prepared.frame, prepared.swings, "15m", len(prepared.frame) - 1
    )
    doubles = [item for item in candidates if item.pattern == "double"]
    assert doubles
    assert len(doubles) <= MAX_PER_FAMILY
    assert len(candidates) <= MAX_CANDIDATES_PER_TIMEFRAME
    padded, mask, ordered = stack_candidates({"15m": candidates, "1h": [], "4h": []})
    assert padded.shape == (MAX_CANDIDATES, len(MODEL_CANDIDATE_FEATURES))
    assert int(mask.sum()) == len(ordered) == len(candidates)


def test_quota_and_dedup_prefer_the_higher_rule_score() -> None:
    """Duplicate ids collapse, and each family stops at two rows."""
    first = manual_candidate(rule_score=0.2)
    second = manual_candidate(rule_score=0.9)
    kept = deduplicate_candidates([first, second])
    assert len(kept) == 1
    assert kept[0].rule_score == 0.9
    crowd = []
    for index in range(5):
        crowd.append(
            manual_candidate(
                candidate_id=f"15m|double|a|b{index}",
                pattern="double",
                rule_score=1.0 - index * 0.01,
            )
        )
    for index in range(20):
        crowd.append(
            manual_candidate(
                candidate_id=f"15m|flag|a|c{index}",
                pattern="flag",
                rule_score=0.5 - index * 0.01,
            )
        )
    limited = apply_quota(crowd)
    assert sum(item.pattern == "double" for item in limited) == MAX_PER_FAMILY
    assert len(limited) <= MAX_CANDIDATES_PER_TIMEFRAME


def test_proposal_metadata_stays_out_of_the_geometry_vector() -> None:
    """Type and rule score are proposal fields, and a blank annotation stays empty."""
    prepared = prepare_timeframe(
        series_from_closes(
            piecewise_closes([(70, 100.0), (12, 120.0), (12, 100.0), (12, 120.0), (12, 100.0)])
        ),
        "15m",
    )
    end, _ = _first_pattern(prepared.frame, "double")
    candidate = next(item for item in _at(prepared, end) if item.pattern == "double")
    proposal = proposal_record(candidate)
    annotation = blank_annotation(proposal["candidate_id"])
    assert proposal["candidate_type_proposal"] == "double"
    assert "candidate_quality_rule_score" in proposal
    assert annotation["identity"] == ""
    assert annotation["identity"] != proposal["candidate_type_proposal"]
    assert len(candidate.features) == len(MODEL_CANDIDATE_FEATURES)
    assert np.isfinite(candidate.features).all()


def test_pairs_keep_overlap_first_and_leave_relationship_blank() -> None:
    """Cross-timeframe pairs are capped, and the relationship label is unset."""
    overlapping = []
    for index in range(4):
        overlapping.append(
            manual_candidate(
                candidate_id=f"15m|rectangle|a|{index}",
                timeframe="15m",
                upper_price_at_asof=110.0,
                lower_price_at_asof=100.0,
            )
        )
        overlapping.append(
            manual_candidate(
                candidate_id=f"1h|channel|a|{index}",
                timeframe="1h",
                pattern="ascending_channel",
                upper_price_at_asof=108.0,
                lower_price_at_asof=101.0,
            )
        )
    disjoint = manual_candidate(
        candidate_id="4h|rectangle|a|z",
        timeframe="4h",
        upper_price_at_asof=20.0,
        lower_price_at_asof=10.0,
    )
    pairs = propose_pairs([*overlapping, disjoint])
    assert pairs
    assert len(pairs) <= PAIR_LIMIT
    assert all(pair["relationship"] == "" for pair in pairs)
    assert pairs[0]["price_overlap"] is True
    assert pairs[0]["time_overlap"] is True
    assert any(pair["price_overlap"] is False for pair in pairs)


def test_breakout_labels_are_separate_from_features(tmp_path) -> None:
    """Horizons past the series are masked, and a two-close breach is a breakout."""
    inside = _path([95.0] * 20)
    assert breakout_status(inside, manual_candidate(), 0, 12) == "no_breakout"
    assert breakout_status(inside, manual_candidate(), 0, 24) == "masked"
    up = _path([95.0, 100.25, 100.30] + [95.0] * 12)
    assert breakout_status(up, manual_candidate(direction="bullish"), 0, 12) == "upside_breakout"
    strong = _path([95.0, 100.5] + [95.0] * 12)
    neutral = manual_candidate(direction="neutral")
    assert breakout_status(strong, neutral, 0, 12) == "upside_breakout"
    down = _path([95.0, 89.5, 89.4] + [95.0] * 12)
    assert breakout_status(down, manual_candidate(direction="bullish"), 0, 12) == "invalidated"
    ambiguous = _path([95.0, 95.0])
    ambiguous.loc[1, "high"] = 101.0
    ambiguous.loc[1, "low"] = 89.0
    assert breakout_status(ambiguous, manual_candidate(), 0, 1) == "ambiguous"
    rows = breakout_rows(inside, manual_candidate(), 0)
    assert {row["status"] for row in rows} == {"no_breakout", "masked"}
    assert "breakout_status" not in inside.columns
    annotation = blank_annotation("15m|double|a|b")
    write_annotations(tmp_path / "annotations.jsonl", [annotation])
    assert read_annotations(tmp_path / "annotations.jsonl") == [annotation]
    with pytest.raises(ValueError):
        validate_annotation({**annotation, "identity": "buy"})


def _atr(frame: pd.DataFrame) -> np.ndarray:
    prepared, _ = _prepared_atr(frame)
    return prepared


def _prepared_atr(frame: pd.DataFrame) -> tuple[np.ndarray, object]:
    from research.cpr_mtf.features import causal_atr
    from research.cpr_mtf.contract import ATR_PERIOD

    high = frame["high"].to_numpy(dtype=np.float64)
    low = frame["low"].to_numpy(dtype=np.float64)
    close = frame["close"].to_numpy(dtype=np.float64)
    return causal_atr(high, low, close, ATR_PERIOD), None


def _append_move(frame: pd.DataFrame, step: float) -> pd.DataFrame:
    """Add one bar that continues the close by ``step``."""
    last = frame.iloc[-1]
    close = float(last["close"]) + step
    open_ = float(last["close"])
    row = {
        "time": pd.Timestamp(last["time"]) + pd.Timedelta(minutes=15),
        "open": open_,
        "high": max(open_, close) + 0.2,
        "low": min(open_, close) - 0.2,
        "close": close,
        "volume": float(last["volume"]),
    }
    return pd.concat([frame, pd.DataFrame([row])], ignore_index=True)


def _first_pattern(frame: pd.DataFrame, pattern: str):
    """Return the first as-of index where ``pattern`` is proposed."""
    columns = ["time", "open", "high", "low", "close", "volume"]
    prepared = prepare_timeframe(frame.loc[:, columns], "15m")
    for end in range(1, len(prepared.frame)):
        if any(item.pattern == pattern for item in _at(prepared, end)):
            return end, prepared
    return None, prepared


def _at(prepared, end: int):
    return generate_candidates(prepared.frame, prepared.swings, "15m", end)


def _swing_text(prepared, pattern: str) -> str:
    swings = [
        (swing.swing_type, swing.pivot_index, round(swing.pivot_price, 2), swing.confirmation_index)
        for swing in prepared.swings
    ]
    return f"no {pattern}; swings={swings}"


def _path(closes: list[float]) -> pd.DataFrame:
    """OHLC around a close path, using the manual candidate's price scale."""
    return series_from_closes(np.asarray(closes, dtype=np.float64), wick=0.05)
