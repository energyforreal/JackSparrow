#!/usr/bin/env python3
"""Generate cognition rollout Replay Summary and diff vs baseline."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

DEFAULT_OUT_DIR = _REPO / "logs" / "agent" / "cognition_rollout"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Cognition rollout Replay Summary")
    p.add_argument("--stage", required=True, help="Stage label e.g. phase0, stage1")
    p.add_argument("--baseline", help="Prior summary JSON for diff metrics")
    p.add_argument("--out", help="Output path (default: logs/agent/cognition_rollout/{stage}.json)")
    p.add_argument("--symbol", default="BTCUSD")
    p.add_argument(
        "--selector",
        choices=("true", "false"),
        help="Override COGNITION_SELECTOR_ENABLED for this run",
    )
    p.add_argument(
        "--scorer",
        choices=("true", "false"),
        help="Override COGNITION_SCORER_ENABLED for this run",
    )
    p.add_argument(
        "--temporal",
        choices=("true", "false"),
        help="Override COGNITION_TEMPORAL_AUTHORITY_ENABLED for this run",
    )
    return p.parse_args()


def _apply_flag_overrides(args: argparse.Namespace) -> None:
    import os

    if args.selector is not None:
        os.environ["COGNITION_SELECTOR_ENABLED"] = args.selector
    if args.scorer is not None:
        os.environ["COGNITION_SCORER_ENABLED"] = args.scorer
    if args.temporal is not None:
        os.environ["COGNITION_TEMPORAL_AUTHORITY_ENABLED"] = args.temporal
    if any(getattr(args, k) is not None for k in ("selector", "scorer", "temporal")):
        from agent.core.config import reload_settings

        reload_settings()


async def _run_regression(symbol: str) -> list:
    from agent.testing.scenario_env import load_scenario_env

    load_scenario_env()

    from agent.testing.cognition_rollout import REGRESSION_SCENARIOS, record_from_scenario_trace
    from agent.testing.scenario_builder import get_scenario
    from agent.testing.scenario_runner import ScenarioRunner
    from agent.intelligence.cognition.flags import (
        cognition_expectation_enabled,
        cognition_scorer_enabled,
        cognition_selector_enabled,
        cognition_shadow_enabled,
        cognition_temporal_authority_enabled,
    )

    runner = ScenarioRunner(symbol=symbol, include_cognition=True)
    runner.what_if = True
    scenarios = [get_scenario(name) for name in REGRESSION_SCENARIOS]
    traces = await runner.run_all(scenarios)
    records = [record_from_scenario_trace(t) for t in traces]
    flags = {
        "shadow": cognition_shadow_enabled(),
        "selector": cognition_selector_enabled(),
        "scorer": cognition_scorer_enabled(),
        "expectation": cognition_expectation_enabled(),
        "temporal_authority": cognition_temporal_authority_enabled(),
    }
    return records, flags


async def _main() -> int:
    args = _parse_args()
    from agent.testing.scenario_env import load_scenario_env

    load_scenario_env()
    _apply_flag_overrides(args)

    from agent.testing.cognition_rollout import (
        build_summary_from_records,
        diff_summaries,
        load_summary,
        write_summary,
    )

    records, flags = await _run_regression(args.symbol)
    summary = build_summary_from_records(
        records, stage=args.stage, symbol=args.symbol, flags=flags
    )

    if args.baseline:
        baseline_path = Path(args.baseline)
        if baseline_path.is_file():
            baseline = load_summary(baseline_path)
            summary = diff_summaries(summary, baseline)

    out_path = Path(args.out) if args.out else DEFAULT_OUT_DIR / f"{args.stage}.json"
    write_summary(out_path, summary)
    print(json.dumps(summary.to_dict(), indent=2))
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
