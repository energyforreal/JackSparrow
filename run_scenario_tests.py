#!/usr/bin/env python3
"""
JackSparrow v43 — Scenario Validation Runner
============================================

Usage:
    python run_scenario_tests.py                     # run all 7 scenarios
    python run_scenario_tests.py --scenario strong_breakout
    python run_scenario_tests.py --scenario chop_market --verbose
    python run_scenario_tests.py --list
    python run_scenario_tests.py --save              # save JSON traces to disk
    python run_scenario_tests.py --strict            # Tier 1 + behavioral expected=* checks

Validates that the agent's reasoning is coherent across synthetic market
conditions WITHOUT connecting to the exchange.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# ensure repo root is importable
_REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(_REPO))


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="JackSparrow v43 Scenario Test Runner")
    p.add_argument("--scenario", "-s", help="Run a single named scenario")
    p.add_argument("--list", "-l", action="store_true", help="List available scenarios")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Print full per-layer detail for every scenario")
    p.add_argument("--save", action="store_true",
                   help="Save JSON traces to tests/scenarios/traces/")
    p.add_argument("--strict", action="store_true",
                   help="Fail on behavioral expected=* checks (default: Tier 1 pipeline only)")
    p.add_argument("--model", "-m", help="Path to metadata_v43.json (override default)")
    p.add_argument("--symbol", default="BTCUSD", help="Trading symbol (default: BTCUSD)")
    return p.parse_args()


async def _main() -> int:
    args = _parse_args()

    from agent.testing.scenario_env import load_scenario_env

    load_scenario_env()

    from agent.testing.scenario_builder import ALL_SCENARIOS, list_scenario_names, get_scenario
    from agent.testing.scenario_runner import ScenarioRunner
    from agent.testing.scenario_assertions import evaluate
    from agent.testing.trace_logger import (
        print_trace, print_summary, save_trace, save_run_summary
    )

    if args.list:
        print("\nAvailable scenarios:")
        for name in list_scenario_names():
            print(f"  - {name}")
        return 0

    # resolve which scenarios to run
    if args.scenario:
        try:
            scenarios = [get_scenario(args.scenario)]
        except KeyError:
            print(f"[ERROR] Unknown scenario: {args.scenario}")
            print(f"Available: {list_scenario_names()}")
            return 1
    else:
        scenarios = [fn() for fn in ALL_SCENARIOS]

    # build runner
    meta = Path(args.model) if args.model else None
    runner = ScenarioRunner(metadata_path=meta, symbol=args.symbol)

    print(f"\nRunning {len(scenarios)} scenario(s) -- symbol={args.symbol}")
    print("    Model: " + str(runner.metadata_path))

    # execute
    traces = await runner.run_all(scenarios)

    # assertions
    for trace in traces:
        evaluate(trace, strict=bool(args.strict))

    # output
    verbose = args.verbose or (len(traces) == 1)
    for trace in traces:
        if verbose:
            print_trace(trace)

    if len(traces) > 1 or not verbose:
        print_summary(traces)

    # save
    if args.save:
        from agent.testing.trace_logger import _DEFAULT_OUT
        for trace in traces:
            path = save_trace(trace)
            print(f"    Saved: {path}")
        summary_path = save_run_summary(traces)
        print(f"    Summary: {summary_path}")

    # exit code: Tier 1 by default; --strict requires full critical (incl. behavioral)
    if args.strict:
        ok = all(t.assertions.get("scenario_passed", False) for t in traces)
    else:
        ok = all(t.assertions.get("tier1_passed", t.assertions.get("scenario_passed", False)) for t in traces)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
