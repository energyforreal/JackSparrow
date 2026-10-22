"""Run the v3 confirmation experiment. The v1 holdout is never scored here."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Mapping

import joblib
import numpy as np
import pandas as pd
import requests
import structlog

from research.forecast_30m.contract_v3 import (
    BOOTSTRAP_ALPHA,
    BOOTSTRAP_BLOCK_BARS,
    BOOTSTRAP_DRAWS,
    BREAKEVEN_PRECISION,
    CUSUM_THRESHOLD,
    DELTA_HISTORY_URL,
    DELTA_PAGE_DELAY_SECONDS,
    DELTA_PAGE_SIZE,
    DEVELOPMENT_END_EXCLUSIVE,
    FEATURE_COLUMNS,
    FEATURE_VERSION,
    HORIZON_BARS,
    LABEL_VERSION,
    ORIGINAL_SOURCE,
    POLICY_THRESHOLD,
    ROUND_TRIP_COST,
    SEED,
    SL_PCT,
    SNAPSHOT_END,
    SPEC_VERSION,
    TP_PCT,
)
from research.forecast_30m.dataset import build_event_frames
from research.forecast_30m.evaluation import (
    buy_and_hold_bar_returns,
    confirmation_gate,
    one_position_policy,
)
from research.forecast_30m.inference import ORDERS_ENABLED
from research.forecast_30m.integrity import (
    _REPO_ROOT,
    audit_frame,
    file_sha256,
    repo_relative,
)
from research.forecast_30m.labels import render_labels_v3_yaml, score_fixed_percent_barrier
from research.forecast_30m.models import predict_bundle, train_xgboost_event_policy
from research.forecast_30m.validation import (
    assert_development_only,
    assert_outside_embargo,
)

logger = structlog.get_logger()
_PHASE1_AUDIT = _REPO_ROOT / "export" / "forecast_30m" / "data_audit.json"
_ORIGINAL = _REPO_ROOT / ORIGINAL_SOURCE
_EXPORT = _REPO_ROOT / "export" / "forecast_30m" / "v3"
_CONFIG = _REPO_ROOT / "research" / "forecast_30m" / "configs"
_BAR_SECONDS = 30 * 60


def run_research_v3() -> dict[str, Any]:
    """Measure the v3 event rule, fit on development, and score the tail once.

    Returns:
        A JSON-safe summary. Model objects stay in the artifact directory.
    """
    development_end = pd.Timestamp(DEVELOPMENT_END_EXCLUSIVE)
    snapshot_end = pd.Timestamp(SNAPSHOT_END)
    original_hash = _assert_original_snapshot()
    candles = _load_extended_candles()
    audit = _write_extended_audit(candles, original_hash)
    development, embargo, confirmation = build_event_frames(
        candles,
        development_end=development_end,
        snapshot_end=snapshot_end,
    )
    assert_development_only(development, development_end)
    assert_outside_embargo(development, development_end, snapshot_end)
    logger.info(
        "forecast_30m_v3_events",
        development_events=int(len(development)),
        embargo_events=int(len(embargo)),
        confirmation_events=int(len(confirmation)),
    )
    barrier_row = score_fixed_percent_barrier(
        development["long_path_code"].to_numpy(dtype=np.int64),
        development["short_path_code"].to_numpy(dtype=np.int64),
        development["forward_return_24"].to_numpy(dtype=np.float64),
        np.ones(len(development), dtype=bool),
        tp_pct=TP_PCT,
        sl_pct=SL_PCT,
        cost=ROUND_TRIP_COST,
    )
    report = {
        "spec_version": SPEC_VERSION,
        "cusum_threshold": CUSUM_THRESHOLD,
        "tp_pct": TP_PCT,
        "sl_pct": SL_PCT,
        "policy_threshold": POLICY_THRESHOLD,
        "breakeven_precision": BREAKEVEN_PRECISION,
        "round_trip_cost": ROUND_TRIP_COST,
        "development_events": int(len(development)),
        "embargo_events": int(len(embargo)),
        "confirmation_events_on_disk": int(len(confirmation)),
        "barrier": {
            "selected": barrier_row if barrier_row.get("passed") else None,
            "reason": "fixed_percent_barrier_passed"
            if barrier_row.get("passed")
            else "no_barrier_passed",
            "candidate": barrier_row,
        },
    }
    _write_json(_EXPORT / "label_report.json", report)
    (_CONFIG / "labels_v3.yaml").write_text(render_labels_v3_yaml(report), encoding="utf-8")
    development["breakeven_precision"] = BREAKEVEN_PRECISION
    development.to_parquet(_EXPORT / "dataset_development.parquet", index=False)

    if not barrier_row.get("passed"):
        confirmation_report = {
            "scored": False,
            "labels_read": False,
            "reason": "barrier_screen_failed",
            "fail_reasons": list(barrier_row.get("fail_reasons") or []),
        }
        trained = {"gate": {"passed": False, "reasons": ["barrier_screen_failed"]}}
        _write_json(_EXPORT / "phase4_development.json", {"gate": trained["gate"]})
        _write_json(_EXPORT / "phase5_confirmation.json", confirmation_report)
        artifact = _write_artifact(trained, report, audit, confirmation_report, original_hash)
        return _summary(trained, confirmation_report, artifact)

    try:
        trained = train_xgboost_event_policy(
            development,
            holdout_start=development_end,
            embargo_end=snapshot_end,
        )
    except ValueError as exc:
        trained = {
            "algorithm": "xgb",
            "gate": {
                "passed": False,
                "reasons": ["too_few_event_rows", str(exc)],
                "trades": int(len(development)),
            },
            "bundles": None,
            "oof": {},
            "fold_stats": [],
            "features": list(FEATURE_COLUMNS),
        }
    _write_json(_EXPORT / "phase4_development.json", _public_training(trained))

    confirmation_report = _maybe_score_confirmation(
        trained,
        confirmation,
        candles,
        snapshot_end=snapshot_end,
    )
    if confirmation_report.get("labels_read"):
        confirmation.to_parquet(_EXPORT / "dataset_confirmation.parquet", index=False)
    _write_json(_EXPORT / "phase5_confirmation.json", confirmation_report)
    artifact = _write_artifact(trained, report, audit, confirmation_report, original_hash)
    logger.info(
        "forecast_30m_v3_complete",
        development_passed=bool(trained.get("gate", {}).get("passed")),
        confirmation_scored=bool(confirmation_report.get("scored")),
        confirmation_passed=bool(confirmation_report.get("passed")),
        artifact=str(artifact),
    )
    return _summary(trained, confirmation_report, artifact)


def _maybe_score_confirmation(
    trained: Mapping[str, Any],
    confirmation: pd.DataFrame,
    candles: pd.DataFrame,
    *,
    snapshot_end: pd.Timestamp,
) -> dict[str, Any]:
    """Score the frozen tail only after the development gate passes."""
    gate = trained.get("gate") or {}
    if not gate.get("passed"):
        reasons = list(gate.get("reasons") or ["development_gate_failed"])
        return {
            "scored": False,
            "labels_read": False,
            "reason": str(reasons[0]),
            "development_reasons": reasons,
        }
    bundles = trained.get("bundles") or {}
    if "long_tp" not in bundles or "short_tp" not in bundles:
        return {
            "scored": False,
            "labels_read": False,
            "reason": "bundles_missing",
        }
    if confirmation.empty:
        return {
            "scored": True,
            "labels_read": True,
            "passed": False,
            "reason": "insufficient_confirmation_window",
            "trades": 0,
        }
    long_bundle = bundles["long_tp"]
    short_bundle = bundles["short_tp"]
    features = list(long_bundle["features"])
    long_p = predict_bundle(
        long_bundle, confirmation.loc[:, features].to_numpy(dtype=np.float64)
    )
    short_p = predict_bundle(
        short_bundle, confirmation.loc[:, features].to_numpy(dtype=np.float64)
    )
    origin, length, open_first, close_last = _confirmation_window(candles, snapshot_end)
    policy = one_position_policy(
        confirmation,
        long_p,
        short_p,
        threshold=POLICY_THRESHOLD,
        cost=ROUND_TRIP_COST,
        horizon_bars=HORIZON_BARS,
        series_length=length,
        series_origin=origin,
    )
    buy_hold = buy_and_hold_bar_returns(
        open_first,
        close_last,
        n_bars=length,
        cost=ROUND_TRIP_COST,
    )
    decision = confirmation_gate(
        policy["bar_returns"],
        buy_hold,
        trades=int(policy["trades"]),
        expectancy=policy["expectancy"],
        profit_factor=policy["profit_factor"],
        max_drawdown=policy["max_drawdown"],
        block_length=BOOTSTRAP_BLOCK_BARS,
        draws=BOOTSTRAP_DRAWS,
        seed=SEED,
        alpha=BOOTSTRAP_ALPHA,
    )
    decision["scored"] = True
    decision["labels_read"] = True
    decision["buy_and_hold_return"] = float(buy_hold.sum())
    return _json_ready(decision)


def _confirmation_window(
    candles: pd.DataFrame,
    snapshot_end: pd.Timestamp,
) -> tuple[int, int, float, float]:
    stamps = pd.to_datetime(candles["time"], utc=True)
    mask = stamps > snapshot_end
    if not bool(mask.any()):
        return 0, 0, float("nan"), float("nan")
    positions = np.flatnonzero(mask.to_numpy())
    origin = int(positions[0])
    length = int(positions.size)
    open_first = float(candles["open"].to_numpy(dtype=np.float64)[origin])
    close_last = float(candles["close"].to_numpy(dtype=np.float64)[positions[-1]])
    return origin, length, open_first, close_last


def _assert_original_snapshot() -> str:
    audit = json.loads(_PHASE1_AUDIT.read_text(encoding="utf-8"))
    source_hash = file_sha256(_ORIGINAL)
    if source_hash != audit["source_sha256"]:
        raise RuntimeError("OHLCV snapshot hash does not match the Phase 1 audit")
    if not audit["source_decision"]["accepted"]:
        raise RuntimeError("Phase 1 did not accept this OHLCV snapshot")
    return source_hash


def _load_extended_candles() -> pd.DataFrame:
    original = pd.read_parquet(_ORIGINAL)
    extended = _append_public_candles(original)
    _EXPORT.mkdir(parents=True, exist_ok=True)
    destination = _EXPORT / "btcusd_30m_extended.parquet"
    extended.to_parquet(destination, index=False)
    logger.info(
        "forecast_30m_v3_extended_snapshot",
        path=repo_relative(destination),
        original_rows=int(len(original)),
        extended_rows=int(len(extended)),
        last_timestamp=str(pd.to_datetime(extended["time"], utc=True).iloc[-1]),
    )
    return extended


def _append_public_candles(original: pd.DataFrame) -> pd.DataFrame:
    """Append closed 30-minute BTCUSD candles after the frozen snapshot."""
    stamps = pd.to_datetime(original["time"], utc=True)
    last_epoch = int(stamps.iloc[-1].timestamp())
    now = int(time.time())
    last_closed_open = (now // _BAR_SECONDS - 1) * _BAR_SECONDS
    start = last_epoch + _BAR_SECONDS
    if start > last_closed_open:
        return original.copy()
    fetched: list[dict[str, Any]] = []
    current_start = start
    while current_start <= last_closed_open:
        current_end = min(
            current_start + DELTA_PAGE_SIZE * _BAR_SECONDS,
            last_closed_open + _BAR_SECONDS,
        )
        page = _fetch_delta_page(current_start, current_end)
        if page:
            fetched.extend(page)
        current_start = current_end + _BAR_SECONDS
        time.sleep(DELTA_PAGE_DELAY_SECONDS)
    if not fetched:
        return original.copy()
    added = pd.DataFrame(fetched)
    added["time"] = pd.to_datetime(added["time"], unit="s", utc=True)
    for column in ("open", "high", "low", "close", "volume"):
        added[column] = pd.to_numeric(added[column], errors="coerce")
    last_closed = pd.Timestamp(last_closed_open, unit="s", tz="UTC")
    added = added.loc[
        (added["time"] > stamps.iloc[-1]) & (added["time"] <= last_closed),
        ["time", "open", "high", "low", "close", "volume"],
    ]
    combined = pd.concat([original, added], ignore_index=True, sort=False)
    combined["time"] = pd.to_datetime(combined["time"], utc=True)
    combined = combined.drop_duplicates(subset=["time"], keep="first")
    combined = combined.sort_values("time").reset_index(drop=True)
    return combined


def _fetch_delta_page(start_ts: int, end_ts: int) -> list[dict[str, Any]]:
    params = {
        "symbol": "BTCUSD",
        "resolution": "30m",
        "start": int(start_ts),
        "end": int(end_ts),
        "page_size": DELTA_PAGE_SIZE,
    }
    response = requests.get(DELTA_HISTORY_URL, params=params, timeout=20)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        raise RuntimeError(f"Delta history error: {payload}")
    rows = payload.get("result") or []
    rows = [row for row in rows if isinstance(row, dict) and "time" in row]
    rows.sort(key=lambda row: int(row["time"]))
    return rows


def _write_extended_audit(candles: pd.DataFrame, original_hash: str) -> dict[str, Any]:
    report = audit_frame(candles)
    report["source_path"] = repo_relative(_EXPORT / "btcusd_30m_extended.parquet")
    report["source_sha256"] = file_sha256(_EXPORT / "btcusd_30m_extended.parquet")
    report["original_sha256"] = original_hash
    report["spec_version"] = SPEC_VERSION
    report["v3_split"] = {
        "development_end_exclusive": DEVELOPMENT_END_EXCLUSIVE,
        "embargo_start": DEVELOPMENT_END_EXCLUSIVE,
        "embargo_end": SNAPSHOT_END,
        "confirmation_start_exclusive": SNAPSHOT_END,
        "last_timestamp": report["last_timestamp"],
        "holdout_status": "embargoed",
    }
    _write_json(_EXPORT / "data_audit.json", report)
    (_EXPORT / "splits.yaml").write_text(_render_splits_v3(report), encoding="utf-8")
    return report


def _render_splits_v3(report: Mapping[str, Any]) -> str:
    split = report["v3_split"]
    lines = [
        "# v3 confirmation split. The v1 holdout is embargoed, not unread.",
        f"spec_version: {SPEC_VERSION}",
        "instrument: BTCUSD",
        "resolution: 30m",
        "timezone: UTC",
        f"source_path: {report['source_path']}",
        f"source_sha256: {report['source_sha256']}",
        f"original_sha256: {report['original_sha256']}",
        f"rows: {report['deduplicated_rows']}",
        f"first_timestamp: {report['first_timestamp']}",
        f"last_timestamp: {report['last_timestamp']}",
        "development:",
        f"  end_exclusive: {split['development_end_exclusive']}",
        "embargo:",
        f"  start: {split['embargo_start']}",
        f"  end: {split['embargo_end']}",
        "  status: embargoed",
        "confirmation:",
        f"  start_exclusive: {split['confirmation_start_exclusive']}",
        f"  end: {split['last_timestamp']}",
        "  status: unread_until_development_passes",
        "",
    ]
    return "\n".join(lines)


def _write_artifact(
    trained: Mapping[str, Any],
    report: Mapping[str, Any],
    audit: Mapping[str, Any],
    confirmation_report: Mapping[str, Any],
    original_hash: str,
) -> Path:
    destination = _EXPORT / "artifacts" / LABEL_VERSION
    destination.mkdir(parents=True, exist_ok=True)
    bundles = dict(trained.get("bundles") or {})
    joblib.dump(bundles, destination / "models.joblib")
    manifest = {
        "spec_version": SPEC_VERSION,
        "label_version": LABEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "feature_columns": list(FEATURE_COLUMNS),
        "original_sha256": original_hash,
        "extended_sha256": audit.get("source_sha256"),
        "development_end_exclusive": DEVELOPMENT_END_EXCLUSIVE,
        "snapshot_end": SNAPSHOT_END,
        "label_selection": {
            "entry": "next_open",
            "cusum_threshold": CUSUM_THRESHOLD,
            "tp_pct": TP_PCT,
            "sl_pct": SL_PCT,
            "policy_threshold": POLICY_THRESHOLD,
            "breakeven_precision": BREAKEVEN_PRECISION,
            "round_trip_cost": ROUND_TRIP_COST,
            "barrier_reason": report["barrier"]["reason"],
        },
        "development_gate_passed": bool(trained.get("gate", {}).get("passed")),
        "confirmation_scored": bool(confirmation_report.get("scored", False)),
        "confirmation_passed": bool(confirmation_report.get("passed", False)),
        "orders_enabled": ORDERS_ENABLED,
        "promoted_to_agent": False,
        "targets_in_artifact": sorted(bundles),
    }
    _write_json(destination / "manifest.json", manifest)
    return destination


def _public_training(trained: Mapping[str, Any]) -> dict[str, Any]:
    public = {
        key: value
        for key, value in trained.items()
        if key not in {"bundles", "bundle"}
    }
    return _json_ready(public)


def _summary(
    trained: Mapping[str, Any],
    confirmation_report: Mapping[str, Any],
    artifact: Path,
) -> dict[str, Any]:
    return {
        "development_passed": bool(trained.get("gate", {}).get("passed")),
        "confirmation_scored": bool(confirmation_report.get("scored", False)),
        "confirmation_passed": bool(confirmation_report.get("passed", False)),
        "reason": confirmation_report.get("reason"),
        "artifact": artifact.as_posix(),
        "orders_enabled": ORDERS_ENABLED,
        "promoted_to_agent": False,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_ready(payload), indent=2) + "\n", encoding="utf-8")


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, np.ndarray):
        return _json_ready(value.tolist())
    return value


if __name__ == "__main__":
    run_research_v3()
