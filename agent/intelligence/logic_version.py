"""Strategy logic versioning for reproducible experiment comparisons."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

from agent.core.config import settings

_LOGIC_VERSIONS: Dict[str, str] = {
    "rule_set": "structural_gates_v1",
    "signal_logic": "rule_based_fsm_v1",
    "market_validation": "market_validation_v1",
    "replay_engine": "replay_v1",
    "attribution_logic": "post_trade_analyzer_v1",
    "analysis_engine": "trade_analysis_engine_v1",
}


def _hash_payload(payload: Dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]


def get_logic_version() -> Dict[str, str]:
    """Return component logic version hashes stamped on trade snapshots."""
    gate_env = {
        "min_trend_age": int(getattr(settings, "structural_gate_min_trend_age", 3) or 3),
        "max_failed_breakouts": int(
            getattr(settings, "structural_gate_max_failed_breakouts", 2) or 2
        ),
        "breakout_require_retest": bool(
            getattr(settings, "structural_gate_breakout_require_retest", True)
        ),
    }
    rule_weights = getattr(settings, "gate_category_weights", None)
    weights_hash = ""
    if isinstance(rule_weights, dict) and rule_weights:
        weights_hash = _hash_payload({str(k): float(v) for k, v in rule_weights.items()})

    out = dict(_LOGIC_VERSIONS)
    out["rule_set_hash"] = _hash_payload(gate_env)
    out["signal_logic_hash"] = _hash_payload(
        {"decision_engine_mode": str(getattr(settings, "decision_engine_mode", "ml_legacy"))}
    )
    if weights_hash:
        out["rule_weights_hash"] = weights_hash
    return out
