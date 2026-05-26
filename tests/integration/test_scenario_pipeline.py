"""Integration: offline v43 scenario harness (Tier 1 pipeline health)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.testing.scenario_env import load_scenario_env

load_scenario_env()

import pytest

from agent.testing.scenario_assertions import evaluate
from agent.testing.scenario_builder import ALL_SCENARIOS
from agent.testing.scenario_runner import ScenarioRunner


@pytest.mark.asyncio
async def test_scenario_pipeline_tier1_all_scenarios() -> None:
    """Every registered scenario completes all layers without fatal errors."""
    runner = ScenarioRunner()
    scenarios = [fn() for fn in ALL_SCENARIOS]
    traces = await runner.run_all(scenarios)
    assert len(traces) == len(ALL_SCENARIOS)
    for trace in traces:
        evaluate(trace, strict=False)
        assert trace.error is None, f"{trace.scenario_name}: {trace.error}"
        assert trace.assertions.get("tier1_passed"), (
            f"{trace.scenario_name} tier1 failed: "
            f"{trace.assertions.get('failed_tier1')}"
        )


@pytest.mark.asyncio
async def test_chop_market_thesis_chop_veto() -> None:
    """Harness passes market_structure into thesis (chop veto path)."""
    from agent.testing.scenario_builder import get_scenario

    runner = ScenarioRunner()
    trace = await runner.run(get_scenario("chop_market"))
    thesis = trace.layer("thesis")
    assert thesis and thesis.ok
    codes = thesis.output.get("reason_codes") or []
    assert any("chop" in str(c).lower() for c in codes), codes
