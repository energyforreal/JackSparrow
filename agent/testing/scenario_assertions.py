"""
Scenario assertions — checks whether each layer's output is rational
given the expected behaviour defined in the scenario.

Each assertion returns a dict:
  {
    "check":   str,        # name of the check
    "passed":  bool,
    "actual":  Any,        # what we observed
    "expected": Any,       # what we required
    "severity": str,       # "critical" | "warning" | "info"
    "note":    str,        # explanation
  }

A scenario is considered PASSED only when all "critical" assertions pass.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from agent.testing.scenario_runner import ScenarioTrace

# Tier 1: pipeline health (default CI gate). Tier 2: scenario ``expected`` dict.
TIER1_CHECK_NAMES = frozenset({
    "ml_layer_healthy",
    "pipeline_complete",
    "score_execution_coherence",
    "gate_policy_coherence",
    "expected_return_stable",
    "multi_horizon_alignment_range",
})


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────

def _mk(check: str, passed: bool, actual: Any, expected: Any,
        severity: str = "critical", note: str = "") -> Dict[str, Any]:
    return {
        "check": check,
        "passed": passed,
        "actual": actual,
        "expected": expected,
        "severity": severity,
        "note": note,
    }


def _layer_out(trace: "ScenarioTrace", name: str) -> Dict[str, Any]:
    lyr = trace.layer(name)
    return lyr.output if lyr and lyr.ok else {}


# ──────────────────────────────────────────────────────────────────────────
# Individual checks
# ──────────────────────────────────────────────────────────────────────────

def check_ml_layer_healthy(trace: "ScenarioTrace") -> Dict[str, Any]:
    lyr = trace.layer("ml_inference")
    ok = lyr is not None and lyr.ok
    return _mk("ml_layer_healthy", ok, "ok" if ok else "error",
               "ok", "critical", "ML model must run without error")


def check_pipeline_complete(trace: "ScenarioTrace") -> Dict[str, Any]:
    """All 8 layers must be present and error-free."""
    required = [
        "ml_inference", "multi_horizon", "market_structure",
        "thesis", "ml_gates", "trade_scorer", "policy_engine",
        "portfolio_guard",
    ]
    missing = [n for n in required if trace.layer(n) is None]
    errored = [n for n in required if trace.layer(n) and not trace.layer(n).ok]
    ok = not missing and not errored
    return _mk(
        "pipeline_complete", ok,
        f"missing={missing} errored={errored}", "all layers ok",
        "critical", "Every layer must complete without errors",
    )


def check_expected_policy_signal(trace: "ScenarioTrace") -> Optional[Dict[str, Any]]:
    allowed = trace.expected.get("policy_signal_in")
    if allowed is None:
        return None
    out = _layer_out(trace, "policy_engine")
    actual = out.get("signal", "UNKNOWN")
    ok = actual in allowed
    return _mk(
        "expected_policy_signal", ok, actual, f"one of {allowed}",
        "critical", f"Policy signal must match expected set",
    )


def check_execute(trace: "ScenarioTrace") -> Optional[Dict[str, Any]]:
    expected_exec = trace.expected.get("execute")
    if expected_exec is None:
        return None
    fin = _layer_out(trace, "final_decision")
    actual = fin.get("execute", False)
    ok = bool(actual) == bool(expected_exec)
    return _mk(
        "expected_execute", ok, actual, expected_exec,
        "critical", "Trade execution intent must match expected",
    )


def check_score_min(trace: "ScenarioTrace") -> Optional[Dict[str, Any]]:
    min_req = trace.expected.get("score_min")
    if min_req is None:
        return None
    out = _layer_out(trace, "trade_scorer")
    actual = out.get("score", 0.0)
    ok = actual >= min_req
    return _mk(
        "score_above_min", ok, round(actual, 1), f">= {min_req}",
        "critical", "Trade score must exceed minimum for expected entry",
    )


def check_score_max(trace: "ScenarioTrace") -> Optional[Dict[str, Any]]:
    max_req = trace.expected.get("score_max")
    if max_req is None:
        return None
    out = _layer_out(trace, "trade_scorer")
    actual = out.get("score", 100.0)
    ok = actual <= max_req
    return _mk(
        "score_below_max", ok, round(actual, 1), f"<= {max_req}",
        "warning", "Trade score should stay low in no-edge scenarios",
    )


def check_portfolio_guard(trace: "ScenarioTrace") -> Optional[Dict[str, Any]]:
    allowed = trace.expected.get("portfolio_guard_action_in")
    if allowed is None:
        return None
    out = _layer_out(trace, "portfolio_guard")
    actual = out.get("action", "allow")
    ok = actual in allowed
    return _mk(
        "portfolio_guard_action", ok, actual, f"one of {allowed}",
        "critical", "Portfolio guard must take expected protective action",
    )


def check_ml_confirms(trace: "ScenarioTrace") -> Optional[Dict[str, Any]]:
    expected_conf = trace.expected.get("ml_confirms")
    if expected_conf is None:
        return None
    out = _layer_out(trace, "trade_scorer")
    actual = bool(out.get("ml_confirms", False))
    ok = actual == bool(expected_conf)
    return _mk(
        "ml_confirms_direction", ok, actual, expected_conf,
        "warning", "Whether ML gates confirmed the thesis direction",
    )


def check_thesis_direction(trace: "ScenarioTrace") -> Optional[Dict[str, Any]]:
    expected_dir = trace.expected.get("thesis_direction")
    if expected_dir is None:
        return None
    out = _layer_out(trace, "thesis")
    actual = out.get("direction", "FLAT")
    ok = actual == expected_dir
    return _mk(
        "thesis_direction", ok, actual, expected_dir,
        "warning", "Thesis engine direction from rule-based analysis",
    )


# ── Coherence checks (cross-layer consistency) ────────────────────────────

def check_score_execution_coherence(trace: "ScenarioTrace") -> Dict[str, Any]:
    """If score passed=True, policy should not be HOLD (and vice versa)."""
    score_out = _layer_out(trace, "trade_scorer")
    policy_out = _layer_out(trace, "policy_engine")
    fin = _layer_out(trace, "final_decision")
    score_passed = score_out.get("passed", False)
    policy_signal = policy_out.get("signal", "HOLD")
    is_entry = policy_signal in {"BUY", "STRONG_BUY", "SELL", "STRONG_SELL"}
    will_execute = bool(fin.get("execute", False))

    # score=passed AND policy=HOLD is suspicious (score overridden)
    # score=failed AND policy=BUY should never happen (code prevents it)
    if score_passed and not is_entry:
        note = "Score passed but policy held — check policy mode config (ml_only forces ML gate priority)"
        ok = True   # not necessarily wrong, policy can override
        severity = "warning"
    elif not score_passed and is_entry and will_execute:
        note = "INCOHERENT: score failed but policy issued entry — orchestrator score gate may be bypassed"
        ok = False
        severity = "critical"
    elif not score_passed and is_entry and not will_execute:
        note = "Policy entry signal but final execute=false (e.g. portfolio guard block) — acceptable"
        ok = True
        severity = "info"
    else:
        note = "Score and policy execution intent are consistent"
        ok = True
        severity = "info"

    return _mk(
        "score_execution_coherence", ok,
        f"score_passed={score_passed} policy_signal={policy_signal}",
        "consistent", severity, note,
    )


def check_gate_policy_coherence(trace: "ScenarioTrace") -> Dict[str, Any]:
    """If all gates rejected, policy must not issue entry."""
    gate_out = _layer_out(trace, "ml_gates")
    policy_out = _layer_out(trace, "policy_engine")
    gates_passed = gate_out.get("final_long") or gate_out.get("final_short")
    policy_signal = policy_out.get("signal", "HOLD")
    is_entry = policy_signal in {"BUY", "STRONG_BUY", "SELL", "STRONG_SELL"}

    if not gates_passed and is_entry:
        # Only wrong if policy mode is ml_only; thesis_only/ml_or_thesis can bypass
        note = "Gates rejected ML signal but policy still issued entry — check policy mode"
        ok = False
        severity = "warning"
    else:
        note = "Gate → policy direction is consistent"
        ok = True
        severity = "info"

    return _mk(
        "gate_policy_coherence", ok,
        f"gates_passed={gates_passed} policy_signal={policy_signal}",
        "consistent", severity, note,
    )


def check_stability(trace: "ScenarioTrace") -> Dict[str, Any]:
    """
    Basic sanity: expected_return should be finite and not extreme (±50%/bar).
    """
    ml_out = _layer_out(trace, "ml_inference")
    er = float(ml_out.get("expected_return", 0.0))
    ok = abs(er) < 0.5
    return _mk(
        "expected_return_stable", ok, round(er, 6), "abs < 0.5",
        "warning", "Expected return should be in a realistic range",
    )


def check_multi_horizon_alignment(trace: "ScenarioTrace") -> Dict[str, Any]:
    """Alignment score should be ≥ 0 (always true, but checks for NaN/negative)."""
    mh_out = _layer_out(trace, "multi_horizon")
    align = float(mh_out.get("alignment_score", -1.0))
    ok = 0.0 <= align <= 1.0
    return _mk(
        "multi_horizon_alignment_range", ok, round(align, 3), "0.0 - 1.0",
        "warning", "Alignment score must be a valid 0-1 fraction",
    )


# ──────────────────────────────────────────────────────────────────────────
# Master evaluator
# ──────────────────────────────────────────────────────────────────────────

def evaluate(trace: "ScenarioTrace", *, strict: bool = False) -> Dict[str, Any]:
    """
    Run all assertions against a completed ScenarioTrace.
    Returns a structured dict and also stores it on trace.assertions.

    When ``strict`` is False (default), ``scenario_passed`` reflects Tier 1 only.
    When True, all critical checks including behavioral ``expected`` must pass.
    """
    checks: List[Dict[str, Any]] = []

    # ── always-run checks ──────────────────────────────────────────────────
    checks.append(check_ml_layer_healthy(trace))
    checks.append(check_pipeline_complete(trace))
    checks.append(check_score_execution_coherence(trace))
    checks.append(check_gate_policy_coherence(trace))
    checks.append(check_stability(trace))
    checks.append(check_multi_horizon_alignment(trace))

    # ── scenario-specific checks ───────────────────────────────────────────
    for fn in [
        check_expected_policy_signal,
        check_execute,
        check_score_min,
        check_score_max,
        check_portfolio_guard,
        check_ml_confirms,
        check_thesis_direction,
    ]:
        result = fn(trace)
        if result is not None:
            checks.append(result)

    # ── summary ───────────────────────────────────────────────────────────
    critical = [c for c in checks if c["severity"] == "critical"]
    warnings = [c for c in checks if c["severity"] == "warning"]
    passed_critical = all(c["passed"] for c in critical)
    passed_warnings = all(c["passed"] for c in warnings)

    tier1_critical = [c for c in critical if c["check"] in TIER1_CHECK_NAMES]
    tier2_critical = [c for c in critical if c["check"] not in TIER1_CHECK_NAMES]
    tier1_passed = all(c["passed"] for c in tier1_critical) if tier1_critical else True
    tier2_passed = all(c["passed"] for c in tier2_critical) if tier2_critical else True

    result = {
        "strict": strict,
        "tier1_passed": tier1_passed,
        "tier2_passed": tier2_passed,
        "scenario_passed": passed_critical if strict else tier1_passed,
        "all_passed": passed_critical and passed_warnings,
        "critical_passed": sum(1 for c in critical if c["passed"]),
        "critical_total": len(critical),
        "tier1_critical_passed": sum(1 for c in tier1_critical if c["passed"]),
        "tier1_critical_total": len(tier1_critical),
        "tier2_critical_passed": sum(1 for c in tier2_critical if c["passed"]),
        "tier2_critical_total": len(tier2_critical),
        "warnings_passed": sum(1 for c in warnings if c["passed"]),
        "warnings_total": len(warnings),
        "checks": checks,
        "failed_critical": [c["check"] for c in critical if not c["passed"]],
        "failed_tier1": [c["check"] for c in tier1_critical if not c["passed"]],
        "failed_tier2": [c["check"] for c in tier2_critical if not c["passed"]],
        "failed_warnings": [c["check"] for c in warnings if not c["passed"]],
    }

    trace.assertions = result
    return result
