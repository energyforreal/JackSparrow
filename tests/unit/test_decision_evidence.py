"""Tests for decision evidence enrichment and provenance."""

from scripts.signal_recovery.decision_evidence import (
    CORE_THESIS_FEATURES,
    build_feature_observations,
    classify_hold_bucket,
    enrich_log_objects,
    filter_high_confidence,
    is_high_confidence_record,
    nearest_before,
    parse_ts_float,
)


def test_provenance_log_beats_telemetry() -> None:
    obs = build_feature_observations(
        log_features={"adx_14": 22.89},
        telemetry_row={"extra": {"features": {"adx_14": 30.0}}},
        reason_codes=[],
    )
    assert obs["adx_14"].source == "log_market_context"
    assert obs["adx_14"].confidence == "high"
    assert obs["adx_14"].value == 22.89


def test_default_missing_excluded() -> None:
    obs = build_feature_observations(log_features={}, telemetry_row={}, reason_codes=[])
    assert obs["adx_14"].source == "default_missing"
    assert obs["adx_14"].confidence == "excluded"
    assert obs["adx_14"].observed is False
    from scripts.signal_recovery.decision_evidence import EnrichedDecisionRecord

    rec = EnrichedDecisionRecord(
        event_id="e0",
        ts="2026-07-11T13:00:00+00:00",
        symbol="BTCUSD",
        bucket="B4",
        regime="neutral",
        eligible_profiles=[],
        policy_reason_codes=[],
        reject=None,
        trade_score=None,
        features=obs,
        hypothesis_snapshot={},
        shadow=None,
    )
    assert not is_high_confidence_record(rec)


def test_high_confidence_all_core_observed() -> None:
    log_feats = {k: 1.0 for k in CORE_THESIS_FEATURES}
    obs = build_feature_observations(log_features=log_feats, telemetry_row=None, reason_codes=[])
    from scripts.signal_recovery.decision_evidence import EnrichedDecisionRecord

    rec = EnrichedDecisionRecord(
        event_id="e1",
        ts="2026-07-11T13:00:00+00:00",
        symbol="BTCUSD",
        bucket="B4",
        regime="neutral",
        eligible_profiles=["breakout"],
        policy_reason_codes=["hypothesis_no_rule_fired"],
        reject="gates_passed_long",
        trade_score=47.0,
        features=obs,
        hypothesis_snapshot={},
        shadow=None,
    )
    assert is_high_confidence_record(rec)
    assert len(filter_high_confidence([rec])) == 1


def test_nearest_before_within_window() -> None:
    rows = [{"x": 1}, {"x": 2}]
    ts_index = [100.0, 110.0]
    assert nearest_before(ts_index, rows, 112.0, max_delta_sec=15.0) == {"x": 2}
    assert nearest_before(ts_index, rows, 80.0, max_delta_sec=15.0) is None


def test_classify_b4_bucket() -> None:
    bucket = classify_hold_bucket(
        codes=["hypothesis_no_rule_fired", "regime=neutral"],
        hyp={"hypotheses": [], "long_pressure": 0, "short_pressure": 0},
        v43={"reject": "gates_passed_long", "policy_signal": "HOLD"},
        cognition={"eligible_profiles": ["breakout"]},
        shadow=None,
    )
    assert bucket == "B4"


def test_enrich_log_objects_minimal() -> None:
    ts = "2026-07-11T13:10:54.207078Z"
    v43_ts = "2026-07-11T13:10:52.974237Z"
    content = (
        '{"event":"mcp_orchestrator_v43_prediction_complete","timestamp":"'
        + v43_ts
        + '","reject":"gates_passed_long","policy_signal":"HOLD","trade_score":47.4}'
        '{"event":"trading_entry_rejected","reason":"hold_at_synthesis","timestamp":"'
        + ts
        + '","event_id":"abc","symbol":"BTCUSD","market_context":{"features":{"adx_14":22.89,"vol_regime":0.77,"hurst_60":0.0,"h_trend":0.0003,"h1_trend":0.004,"di_spread":9.6,"rsi_14":48.0,"bb_pos":0.62},"hypothesis_snapshot":{"reason_codes":["hypothesis_no_rule_fired"],"long_pressure":0,"short_pressure":0,"hypotheses":[]},"policy_verdict":{"reason_codes":["hypothesis_no_rule_fired","regime=neutral"]}}}'
    )
    records = enrich_log_objects(list(__import__("scripts.signal_recovery.decision_evidence", fromlist=["iter_json_objects"]).iter_json_objects(content)))
    assert len(records) == 1
    assert records[0].bucket == "B4"
    assert records[0].features["adx_14"].value == 22.89
    assert records[0].features["adx_14"].source == "log_market_context"


def test_parse_ts_float() -> None:
    assert parse_ts_float("2026-07-11T13:00:00+00:00") is not None
