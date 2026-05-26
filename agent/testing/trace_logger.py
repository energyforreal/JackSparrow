"""
Trace logger — persists ScenarioTrace results as structured JSON files.
Also prints a human-readable summary table to stdout.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from agent.testing.scenario_runner import ScenarioTrace

# default output directory
_DEFAULT_OUT = Path(__file__).resolve().parents[2] / "tests" / "scenarios" / "traces"


def _strip_private(obj: object) -> object:
    """Remove internal _obj references (non-serialisable live objects)."""
    if isinstance(obj, dict):
        return {k: _strip_private(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [_strip_private(i) for i in obj]
    return obj


def save_trace(trace: "ScenarioTrace", out_dir: Path = _DEFAULT_OUT) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    fname = f"{trace.scenario_name}_{ts}.json"
    path = out_dir / fname
    payload = _strip_private(trace.to_dict())
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    return path


def save_run_summary(traces: List["ScenarioTrace"], out_dir: Path = _DEFAULT_OUT) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    fname = f"run_summary_{ts}.json"
    path = out_dir / fname
    summary = {
        "run_at": ts,
        "scenarios_run": len(traces),
        "scenarios_passed": sum(1 for t in traces if t.assertions.get("scenario_passed")),
        "scenarios_tier1_passed": sum(1 for t in traces if t.assertions.get("tier1_passed")),
        "scenarios": [
            {
                "name": t.scenario_name,
                "passed": t.assertions.get("scenario_passed"),
                "tier1_passed": t.assertions.get("tier1_passed"),
                "all_passed": t.assertions.get("all_passed"),
                "failed_critical": t.assertions.get("failed_critical", []),
                "failed_tier1": t.assertions.get("failed_tier1", []),
                "failed_tier2": t.assertions.get("failed_tier2", []),
                "failed_warnings": t.assertions.get("failed_warnings", []),
                "total_ms": round(t.total_ms, 1),
                "error": t.error,
            }
            for t in traces
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    return path


# ──────────────────────────────────────────────────────────────────────────
# Console output
# ──────────────────────────────────────────────────────────────────────────

_RESET = "\033[0m"
_GREEN = "\033[92m"
_RED   = "\033[91m"
_YELLOW= "\033[93m"
_CYAN  = "\033[96m"
_BOLD  = "\033[1m"
_DIM   = "\033[2m"


def _c(text: str, code: str) -> str:
    """Apply ANSI colour if stdout supports it."""
    if os.isatty(1):
        return f"{code}{text}{_RESET}"
    return text


def print_trace(trace: "ScenarioTrace") -> None:
    """Print a detailed single-scenario trace."""
    title = f"\n{'='*70}"
    print(title)
    print(_c(f"  SCENARIO: {trace.scenario_name.upper()}", _BOLD + _CYAN))
    print(f"  {trace.description}")
    print(f"  Symbol: {trace.symbol}  |  Total: {trace.total_ms:.0f} ms")
    if trace.error:
        print(_c(f"  FATAL ERROR: {trace.error}", _RED))
    print("-" * 70)

    # Layers
    for lyr in trace.layers:
        if lyr.name == "final_decision":
            continue
        status = _c("+", _GREEN) if lyr.ok else _c("x", _RED)
        print(f"  {status}  [{lyr.name:<20}]  {lyr.duration_ms:5.1f} ms", end="")
        if lyr.error:
            print(f"  {_c('ERROR: ' + lyr.error, _RED)}")
        else:
            print()

        out = {k: v for k, v in lyr.output.items() if not k.startswith("_") and k not in ("pred_context",)}
        for k, v in out.items():
            if isinstance(v, dict) and len(v) > 4:
                print(f"      {_c(k, _DIM)}: {{...{len(v)} keys}}")
            else:
                print(f"      {_c(k, _DIM)}: {v}")

    # Final decision box
    fin = trace.layer("final_decision")
    if fin:
        out = fin.output
        execute = out.get("execute")
        signal = out.get("signal", "?")
        guard = out.get("guard_action", "?")
        color = _GREEN if execute else _YELLOW
        print("-" * 70)
        print(_c(f"  FINAL DECISION:", _BOLD))
        print(f"    Signal      : {_c(signal, color)}")
        print(f"    Execute     : {_c(str(execute), color)}")
        print(f"    Size        : {out.get('position_size', 0):.4f}")
        print(f"    Guard       : {guard}")
        print(f"    Reason      : {out.get('reason', [])}")

    # Assertions
    a = trace.assertions
    if a:
        print("-" * 70)
        sp = a.get("scenario_passed")
        ap = a.get("all_passed")
        label = "ALL PASSED" if ap else ("CRITICAL PASSED" if sp else "FAILED")
        color = _GREEN if ap else (_YELLOW if sp else _RED)
        print(_c(f"  ASSERTIONS: {label}", _BOLD + color))
        print(f"    Critical: {a.get('critical_passed')}/{a.get('critical_total')}  "
              f"Warnings: {a.get('warnings_passed')}/{a.get('warnings_total')}")
        for ch in a.get("checks", []):
            s = "+" if ch["passed"] else "x"
            col = _GREEN if ch["passed"] else (_RED if ch["severity"] == "critical" else _YELLOW)
            print(f"    {_c(s, col)} {ch['check']:<40} "
                  f"actual={str(ch['actual']):<20} expected={ch['expected']}")
            if ch.get("note") and not ch["passed"]:
                print(f"      -> {_c(ch['note'], _DIM)}")

    print("=" * 70)


def print_summary(traces: List["ScenarioTrace"]) -> None:
    """Print a compact summary table of all scenarios."""
    total = len(traces)
    passed = sum(1 for t in traces if t.assertions.get("scenario_passed"))
    tier1 = sum(1 for t in traces if t.assertions.get("tier1_passed"))
    all_ok = sum(1 for t in traces if t.assertions.get("all_passed"))

    print(f"\n{'='*70}")
    print(_c("  SCENARIO TEST RUN SUMMARY", _BOLD))
    print(f"  {tier1}/{total} TIER1 PASSED  |  {passed}/{total} CRITICAL  |  {all_ok}/{total} FULL")
    print("-" * 70)
    print(f"  {'Scenario':<35} {'Status':<14} {'Score':>6}  {'Signal':<12} ms")
    print("-" * 70)

    for t in traces:
        sp = t.assertions.get("scenario_passed")
        t1 = t.assertions.get("tier1_passed")
        ap = t.assertions.get("all_passed")
        status = "ALL PASS" if ap else ("TIER1 OK" if t1 and not sp else ("CRIT PASS" if sp else "FAILED   "))
        color = _GREEN if ap else (_GREEN if t1 and not sp else (_YELLOW if sp else _RED))

        score_out = _layer_out_simple(t, "trade_scorer")
        score = f"{score_out.get('score', 0.0):5.1f}" if score_out else "  N/A"
        policy_out = _layer_out_simple(t, "policy_engine")
        signal = policy_out.get("signal", "?") if policy_out else "?"
        ms = f"{t.total_ms:5.0f}"

        fc = t.assertions.get("failed_tier2") or t.assertions.get("failed_critical", [])
        fc_str = f"  [{', '.join(fc)}]" if fc else ""

        print(f"  {t.scenario_name:<35} {_c(status, color):<14} {score}  {signal:<12} {ms}{fc_str}")

    print("=" * 70 + "\n")


def _layer_out_simple(trace: "ScenarioTrace", name: str) -> dict:
    lyr = trace.layer(name)
    return lyr.output if lyr and lyr.ok else {}
