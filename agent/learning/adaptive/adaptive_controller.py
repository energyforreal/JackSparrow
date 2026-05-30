"""Orchestrate drift detection, warm-start retrain, F1 gate, and artifact save."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from agent.core.config import settings
from agent.learning.adaptive import drift_detector
from agent.learning.adaptive import model_registry
from agent.learning.adaptive import model_validator
from agent.learning.adaptive import performance_trigger
from agent.learning.adaptive import retrain_engine
from agent.learning.adaptive.labeled_data import load_labeled_parquet

logger = structlog.get_logger()


def _state_path() -> Path:
    raw = str(getattr(settings, "adaptive_retrain_state_path", "adaptive_retrain_state.json"))
    path = Path(raw)
    if path.is_absolute():
        return path
    logs_root = os.environ.get("LOGS_ROOT")
    if logs_root:
        return Path(logs_root) / path.name
    return path


def _load_cooldown_state() -> Dict[str, Any]:
    path = _state_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cooldown_state(state: Dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _cooldown_hours_remaining(tf: str, cooldown_hours: float) -> Optional[float]:
    if cooldown_hours <= 0:
        return None
    st = _load_cooldown_state()
    entry = st.get(tf) or {}
    last = entry.get("last_retrain_at")
    if not isinstance(last, str) or not last:
        return None
    try:
        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None
    elapsed_h = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600.0
    rem = float(cooldown_hours) - elapsed_h
    return rem if rem > 0 else None


def _mark_retrained(tf: str) -> None:
    st = _load_cooldown_state()
    st[tf] = {"last_retrain_at": datetime.now(timezone.utc).isoformat()}
    _save_cooldown_state(st)


def _failure_backoff_path() -> Path:
    base = _state_path()
    return base.parent / f"{base.stem}_failure_backoff.json"


def _load_failure_backoff() -> Dict[str, Any]:
    path = _failure_backoff_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_failure_backoff(state: Dict[str, Any]) -> None:
    path = _failure_backoff_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _failure_backoff_hours_remaining(tf: str) -> Optional[float]:
    st = _load_failure_backoff()
    ent = st.get(tf) or {}
    until = ent.get("until_ts")
    if until is None:
        return None
    try:
        rem_s = float(until) - datetime.now(timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None
    return rem_s / 3600.0 if rem_s > 0 else None


def _record_retrain_failure(tf: str) -> None:
    base = float(getattr(settings, "adaptive_retrain_failure_cooldown_base_hours", 1.0) or 1.0)
    max_h = float(getattr(settings, "adaptive_retrain_failure_cooldown_max_hours", 8.0) or 8.0)
    st = _load_failure_backoff()
    ent = st.get(tf) or {}
    failures = int(ent.get("failures", 0)) + 1
    hours = min(max_h, base * (2 ** max(0, failures - 1)))
    until = datetime.now(timezone.utc).timestamp() + hours * 3600.0
    st[tf] = {"failures": failures, "until_ts": until, "hours": hours}
    _save_failure_backoff(st)


def _clear_failure_backoff(tf: str) -> None:
    st = _load_failure_backoff()
    if tf in st:
        del st[tf]
        _save_failure_backoff(st)


def _parsed_adaptive_timeframes() -> List[str]:
    raw = str(getattr(settings, "adaptive_retrain_timeframes", "5m,15m") or "5m,15m")
    return [x.strip() for x in raw.split(",") if x.strip()]


def _retrain_window_rows(tf: str) -> int:
    if tf == "5m":
        return int(getattr(settings, "adaptive_retrain_window_rows_5m", 80000) or 80000)
    if tf == "15m":
        return int(getattr(settings, "adaptive_retrain_window_rows_15m", 40000) or 40000)
    return int(getattr(settings, "adaptive_retrain_window_rows_5m", 80000) or 80000)


def _slice_retrain_tail(df: Any, tf: str) -> Any:
    """Restrict to last N rows and optional rolling-days window."""
    import pandas as pd

    n = _retrain_window_rows(tf)
    tail = df.tail(min(len(df), n))
    days = int(getattr(settings, "adaptive_rolling_days_train", 60) or 60)
    if isinstance(tail.index, pd.DatetimeIndex) and len(tail) > 0:
        try:
            cutoff = tail.index.max() - pd.Timedelta(days=days)
            tail = tail[tail.index >= cutoff]
        except Exception:
            pass
    return tail


async def hot_reload_models(mcp_orchestrator: Any) -> Dict[str, Any]:
    """Refresh MCP model registry from disk (no process restart)."""
    if mcp_orchestrator is None:
        return {"success": False, "reason": "no_orchestrator"}
    try:
        return await mcp_orchestrator.refresh_models()  # type: ignore[union-attr]
    except Exception as e:
        logger.warning(
            "adaptive_hot_reload_failed",
            service="agent",
            component="adaptive_controller",
            error=str(e),
            exc_info=True,
        )
        return {"success": False, "error": str(e)}


def maybe_retrain_timeframe(
    timeframe: str,
    labeled_df: Any,
) -> Dict[str, Any]:
    """Run adaptive pipeline for one timeframe.

    Args:
        timeframe: ``5m`` / ``15m`` / etc.
        labeled_df: DataFrame with feature columns + ``label``.

    Returns:
        Result dict with keys: ``action``, ``detail``, optional ``paths``, ``scores``.
    """
    symbol = str(getattr(settings, "trading_symbol", None) or getattr(settings, "agent_symbol", "BTCUSD"))
    model_dir = Path(str(getattr(settings, "model_dir", "./agent/model_storage")))
    meta_path = model_registry.find_metadata_path(model_dir, symbol, timeframe)
    if meta_path is None:
        return {"action": "skip", "detail": "metadata_not_found", "timeframe": timeframe}

    if labeled_df is None or len(labeled_df) == 0:
        return {"action": "skip", "detail": "no_labeled_data", "timeframe": timeframe}

    min_rows = int(getattr(settings, "adaptive_drift_min_rows", 40000) or 40000)
    if len(labeled_df) < min_rows:
        return {
            "action": "skip",
            "detail": "insufficient_rows",
            "timeframe": timeframe,
            "rows": len(labeled_df),
            "min_rows": min_rows,
        }

    try:
        raw_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {"action": "skip", "detail": "metadata_read_failed", "timeframe": timeframe}

    feature_cols: List[str] = list(raw_meta.get("features") or [])
    if not feature_cols:
        return {"action": "skip", "detail": "no_features_in_metadata", "timeframe": timeframe}

    recent_n = int(getattr(settings, "adaptive_drift_recent_rows", 20000) or 20000)
    past_n = int(getattr(settings, "adaptive_drift_past_rows", 20000) or 20000)
    df = labeled_df
    if len(df) < recent_n + past_n:
        return {"action": "skip", "detail": "insufficient_rows_for_drift_windows", "timeframe": timeframe}

    df_recent = df.iloc[-recent_n:]
    df_past = df.iloc[-(recent_n + past_n) : -recent_n]

    drift_metric = str(getattr(settings, "adaptive_drift_metric", "ks") or "ks").strip().lower()
    limit = int(getattr(settings, "adaptive_drift_feature_limit", 5) or 5)
    min_consensus = int(getattr(settings, "adaptive_drift_consensus_min_count", 5) or 5)
    require_consensus = bool(
        getattr(settings, "adaptive_drift_require_ks_psi_consensus", True)
    )

    drifted_ks = drift_detector.detect_drift(
        df_past,
        df_recent,
        feature_cols,
        alpha=float(getattr(settings, "adaptive_drift_alpha", 0.01) or 0.01),
        stat_threshold=float(getattr(settings, "adaptive_drift_stat_threshold", 0.10) or 0.10),
    )
    drifted_psi = drift_detector.detect_drift_psi(
        df_past,
        df_recent,
        feature_cols,
        psi_threshold=float(getattr(settings, "adaptive_drift_psi_threshold", 0.20) or 0.20),
        bins=int(getattr(settings, "adaptive_drift_psi_bins", 10) or 10),
    )

    consensus_names = drift_detector.consensus_drift_feature_names(
        drifted_ks, drifted_psi
    )
    consensus_detail: Dict[str, Any] = {
        "consensus_drift_count": len(consensus_names),
        "consensus_features_sample": consensus_names[:25],
    }

    if require_consensus:
        drift_triggers = len(consensus_names) >= min_consensus
    else:
        ks_triggers = drift_detector.should_retrain_from_drift(drifted_ks, limit)
        psi_triggers = drift_detector.should_retrain_from_psi(drifted_psi, limit)
        if drift_metric == "either":
            drift_triggers = ks_triggers or psi_triggers
        elif drift_metric in ("both", "all"):
            drift_triggers = ks_triggers and psi_triggers
        elif drift_metric == "psi":
            drift_triggers = psi_triggers
        else:
            drift_triggers = ks_triggers

    perf_triggers = False
    perf_detail: Dict[str, Any] = {}
    if bool(getattr(settings, "adaptive_performance_retrain_enabled", False)):
        perf_triggers, perf_detail = performance_trigger.performance_retrain_triggered()

    if not drift_triggers and not perf_triggers:
        return {
            "action": "skip",
            "detail": "drift_below_threshold",
            "timeframe": timeframe,
            "drift_metric": drift_metric,
            "drifted_ks_count": len(drifted_ks),
            "drifted_psi_count": len(drifted_psi),
            "limit": limit,
            "performance_trigger": perf_detail,
            **consensus_detail,
        }

    cooldown_h = float(getattr(settings, "adaptive_retrain_cooldown_hours", 12.0) or 12.0)
    rem_cd = _cooldown_hours_remaining(timeframe, cooldown_h)
    rem_fb = _failure_backoff_hours_remaining(timeframe)
    rem_parts = [x for x in (rem_cd, rem_fb) if x is not None]
    rem = max(rem_parts) if rem_parts else None
    if rem is not None:
        return {
            "action": "skip",
            "detail": "cooldown",
            "timeframe": timeframe,
            "hours_remaining": round(rem, 2),
            "hours_remaining_success_cooldown": round(rem_cd, 2) if rem_cd else None,
            "hours_remaining_failure_backoff": round(rem_fb, 2) if rem_fb else None,
        }

    df_train = _slice_retrain_tail(df, timeframe)
    try:
        df_clean, X_train, train_median = retrain_engine.prepare_training_matrix(
            df_train, feature_cols
        )
    except Exception as e:
        return {"action": "error", "detail": f"prepare_matrix:{e}", "timeframe": timeframe}

    min_clean = int(getattr(settings, "adaptive_min_clean_rows", 1000) or 1000)
    if len(df_clean) < min_clean:
        return {
            "action": "skip",
            "detail": "recent_window_too_small",
            "timeframe": timeframe,
            "rows": len(df_clean),
        }

    y_train = df_clean["label"].values.astype("int64", copy=False)
    cw = {
        0: float(getattr(settings, "adaptive_class_weight_sell", 1.3)),
        1: float(getattr(settings, "adaptive_class_weight_hold", 0.5)),
        2: float(getattr(settings, "adaptive_class_weight_buy", 1.3)),
    }
    sw = retrain_engine.class_weights_to_sample_weight(y_train, cw)

    latest = meta_path.parent / f"pipeline_{timeframe}_latest.pkl"
    legacy = meta_path.parent / f"pipeline_{timeframe}_v14.pkl"
    pip_path = latest if latest.is_file() else legacy
    if not pip_path.is_file():
        return {"action": "skip", "detail": "pipeline_pickle_missing", "timeframe": timeframe}

    try:
        old_bundle = model_registry.load_pipeline_bundle(pip_path)
    except Exception as e:
        return {"action": "error", "detail": f"load_pipeline:{e}", "timeframe": timeframe}

    rounds = int(getattr(settings, "adaptive_num_boost_round_incremental", 150) or 150)
    try:
        new_model = retrain_engine.warm_start_retrain(
            old_bundle,
            X_train,
            y_train,
            sw,
            num_boost_round=rounds,
        )
    except Exception as e:
        logger.warning(
            "adaptive_warm_start_failed",
            service="agent",
            timeframe=timeframe,
            error=str(e),
            exc_info=True,
        )
        _record_retrain_failure(timeframe)
        return {"action": "error", "detail": f"warm_start:{e}", "timeframe": timeframe}

    val_rows = int(getattr(settings, "adaptive_validation_window_rows", 10000) or 10000)
    df_val = (
        df_clean.iloc[-val_rows:] if len(df_clean) > val_rows else df_clean
    )
    X_val = df_val[feature_cols].fillna(train_median).values.astype("float64")
    y_val = df_val["label"].values.astype("int64", copy=False)

    min_imp = float(getattr(settings, "adaptive_min_f1_improvement", 0.0) or 0.0)
    require_sc = bool(getattr(settings, "adaptive_validation_scorecard_enabled", False))
    require_fg = bool(getattr(settings, "adaptive_v43_five_gates_enabled", False))
    accepted, val_detail = model_validator.validate_model_upgrade(
        old_bundle,
        new_model,
        X_val,
        y_val,
        min_improvement=min_imp,
        require_scorecard=require_sc,
        require_five_gates=require_fg,
    )
    old_f1 = float(val_detail.get("old_f1", 0.0))
    new_f1 = float(val_detail.get("new_f1", 0.0))
    if not accepted:
        logger.info(
            "adaptive_retrain_rejected",
            service="agent",
            timeframe=timeframe,
            old_f1=old_f1,
            new_f1=new_f1,
            rejected_reason=val_detail.get("rejected_reason"),
        )
        _record_retrain_failure(timeframe)
        return {
            "action": "rejected",
            "detail": val_detail.get("rejected_reason") or "validation_gate",
            "timeframe": timeframe,
            "old_f1": old_f1,
            "new_f1": new_f1,
            "validation": val_detail,
        }

    old_meta: Dict[str, Any] = {}
    if isinstance(old_bundle, dict):
        old_meta = dict(old_bundle.get("meta") or {})

    accepted_pipeline: Dict[str, Any] = {
        "model": new_model,
        "features": feature_cols,
        "train_median": train_median,
        "meta": {
            **old_meta,
            "retrained_at": datetime.now(timezone.utc).isoformat(),
            "retrain_method": "warm_start",
            "boost_rounds_added": rounds,
            "n_samples": int(len(y_train)),
            "new_f1": float(new_f1),
            "old_f1": float(old_f1),
            "validation_scorecard": val_detail.get("new_scorecard") or {},
            "validation_prev_scorecard": val_detail.get("old_scorecard") or {},
        },
    }
    version_tag = f"v_auto_{int(time.time())}"
    log_name = str(getattr(settings, "adaptive_retrain_log_name", "retrain_log.json") or "retrain_log.json")
    paths = model_registry.save_accepted_adaptive_pipeline(
        meta_path,
        timeframe,
        accepted_pipeline,
        version_tag=version_tag,
        log_filename=log_name,
        scores={
            "new_f1": new_f1,
            "old_f1": old_f1,
            "n_samples": int(len(y_train)),
            "drifted": len(drifted_ks),
            "drifted_psi": len(drifted_psi),
            "new_scorecard": val_detail.get("new_scorecard"),
            "old_scorecard": val_detail.get("old_scorecard"),
        },
    )
    _clear_failure_backoff(timeframe)
    _mark_retrained(timeframe)

    logger.info(
        "adaptive_retrain_accepted",
        service="agent",
        timeframe=timeframe,
        version=version_tag,
        old_f1=old_f1,
        new_f1=new_f1,
    )
    return {
        "action": "accepted",
        "timeframe": timeframe,
        "version": version_tag,
        "paths": paths,
        "old_f1": old_f1,
        "new_f1": new_f1,
        "needs_model_refresh": True,
    }


def _run_adaptive_retrain_subprocess(timeframe: str, parquet_dir: str) -> Dict[str, Any]:
    """Run ``maybe_retrain_timeframe`` in an isolated process (stdout JSON result)."""
    import json
    import subprocess
    import sys

    cmd = [
        sys.executable,
        "-m",
        "agent.learning.adaptive.retrain_worker",
        "--timeframe",
        timeframe,
        "--parquet-dir",
        parquet_dir,
    ]
    timeout = int(
        getattr(settings, "adaptive_retrain_subprocess_timeout_seconds", 7200) or 7200
    )
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        _record_retrain_failure(timeframe)
        return {"action": "error", "detail": "subprocess_timeout", "timeframe": timeframe}
    lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
    if not lines:
        _record_retrain_failure(timeframe)
        return {
            "action": "error",
            "detail": "subprocess_empty_stdout",
            "timeframe": timeframe,
            "exit_code": proc.returncode,
            "stderr_tail": (proc.stderr or "")[-800:],
        }
    try:
        return json.loads(lines[-1])
    except Exception:
        _record_retrain_failure(timeframe)
        return {
            "action": "error",
            "detail": "subprocess_parse_failed",
            "timeframe": timeframe,
            "exit_code": proc.returncode,
            "stderr_tail": (proc.stderr or "")[-800:],
        }


async def run_adaptive_retrain_tick(mcp_orchestrator: Optional[Any] = None) -> Dict[str, Any]:
    """Evaluate all configured timeframes once (intended hourly)."""
    if not bool(getattr(settings, "adaptive_retrain_enabled", False)):
        return {"ran": False, "reason": "disabled"}

    model_dir = Path(str(getattr(settings, "model_dir", "") or "")).expanduser()
    try:
        resolved = model_dir.resolve()
    except Exception:
        resolved = model_dir
    if any((resolved / name).is_file() for name in ("metadata_v43.json", "metadata_v44.json")):
        logger.info(
            "adaptive_retrain_incompatible_jacksparrow_v43",
            model_dir=str(resolved),
            message=(
                "Adaptive warm-start targets legacy pipeline bundles (metadata_BTCUSD_*.json); "
                "skipped when MODEL_DIR is JackSparrow v43/v44-named bundle."
            ),
        )
        return {"ran": False, "reason": "jacksparrow_v43_model_dir"}

    source = (getattr(settings, "adaptive_labeled_data_source", "none") or "none").strip().lower()
    if source != "parquet":
        return {"ran": False, "reason": f"unsupported_or_none_source:{source}"}

    pdir = Path(str(getattr(settings, "adaptive_retrain_parquet_dir", "") or "").strip())
    if not pdir.is_dir():
        return {"ran": False, "reason": "parquet_dir_missing", "path": str(pdir)}

    results: Dict[str, Any] = {}
    any_accepted = False
    import asyncio

    use_sub = bool(getattr(settings, "adaptive_retrain_subprocess_enabled", True))
    pdir_abs = str(pdir.resolve())
    for tf in _parsed_adaptive_timeframes():
        if use_sub:
            results[tf] = await asyncio.to_thread(
                _run_adaptive_retrain_subprocess,
                tf,
                pdir_abs,
            )
        else:
            df = load_labeled_parquet(pdir, tf)
            results[tf] = maybe_retrain_timeframe(tf, df)
        if results[tf].get("action") == "accepted":
            any_accepted = True
    refresh: Dict[str, Any] = {}
    if any_accepted and mcp_orchestrator is not None:
        refresh = await hot_reload_models(mcp_orchestrator)
    return {"ran": True, "results": results, "refresh_models": refresh}


async def fetch_delta_fills_for_audit(
    delta_client: Any,
    *,
    product_ids: Optional[str] = None,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
    page_size: int = 100,
) -> Dict[str, Any]:
    """Fetch Delta /v2/fills for P&L reconciliation (testnet private API)."""
    if delta_client is None or not hasattr(delta_client, "get_fills"):
        return {"success": False, "error": "delta_client.get_fills unavailable"}
    try:
        payload = await delta_client.get_fills(
            product_ids=product_ids,
            start_time=start_time,
            end_time=end_time,
            page_size=page_size,
        )
        return {"success": True, "payload": payload}
    except Exception as exc:
        logger.warning("adaptive_retrain_fills_fetch_failed", error=str(exc))
        return {"success": False, "error": str(exc)}
