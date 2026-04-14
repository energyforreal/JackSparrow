"""UTC-safe parsing of decision payload timestamps (stale-signal age check)."""

from datetime import datetime, timezone

from agent.core.decision_timestamp import decision_payload_timestamp_epoch_seconds


def test_naive_utc_datetime_matches_utc_epoch():
    """Naive datetimes from utcnow() must be interpreted as UTC, not local."""
    dt = datetime(2026, 4, 12, 11, 16, 14)
    got = decision_payload_timestamp_epoch_seconds(dt)
    want = datetime(2026, 4, 12, 11, 16, 14, tzinfo=timezone.utc).timestamp()
    assert abs(got - want) < 1e-6


def test_aware_datetime_unchanged_semantics():
    dt = datetime(2026, 4, 12, 11, 16, 14, tzinfo=timezone.utc)
    got = decision_payload_timestamp_epoch_seconds(dt)
    assert abs(got - dt.timestamp()) < 1e-6


def test_iso_string_z_suffix():
    got = decision_payload_timestamp_epoch_seconds("2026-04-12T11:16:14Z")
    want = datetime(2026, 4, 12, 11, 16, 14, tzinfo=timezone.utc).timestamp()
    assert abs(got - want) < 1e-6


def test_numeric_epoch_seconds():
    base = 1_700_000_000.0
    assert decision_payload_timestamp_epoch_seconds(base) == base


def test_numeric_millis_normalized():
    base = 1_700_000_000.0
    assert abs(decision_payload_timestamp_epoch_seconds(base * 1000.0) - base) < 1e-6
