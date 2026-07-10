#!/usr/bin/env python3
"""Grid Pareto threshold replay using offline scenario_runner."""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.testing.scenario_env import load_scenario_env  # noqa: E402

load_scenario_env()


DEFAULT_GRID: Dict[str, List[Any]] = {
    "gate5_ratio": [0.50, 0.75, 1.00],
    "entry_quality_min": [45, 55, 65],
    "conviction_entry_floor": [0.25, 0.35, 0.45],
    "hypothesis_min_margin": [0.02, 0.03, 0.05],
    "debounce_bars": [1, 2, 3],
}


@contextmanager
def _settings_override(overrides: Dict[str, Any]) -> Iterator[None]:
    from agent.core.config import settings

    backup = {k: getattr(settings, k, None) for k in overrides}
    for k, v in overrides.items():
        if hasattr(settings, k):
            setattr(settings, k, v)
    try:
        yield
    finally:
        for k, v in backup.items():
            if hasattr(settings, k):
                setattr(settings, k, v)


def _theta_to_settings(theta: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "jacksparrow_v43_min_edge_cost_ratio": float(theta["gate5_ratio"]),
        "entry_quality_min_score": float(theta["entry_quality_min"]),
        "conviction_entry_floor": float(theta["conviction_entry_floor"]),
        "hypothesis_min_margin": float(theta["hypothesis_min_margin"]),
        "jacksparrow_v43_trade_debounce_bars": int(theta["debounce_bars"]),
    }


def _trace_metrics(trace: Any) -> Dict[str, Any]:
    final = trace.layer("final_decision")
    policy = trace.layer("policy_engine")
    gates = trace.layer("ml_gates")
    signal = "HOLD"
    size = 0.0
    if final and final.ok:
        signal = str(final.output.get("signal") or "HOLD")
        size = float(final.output.get("position_size") or 0.0)
    actionable = signal in {"BUY", "STRONG_BUY", "SELL", "STRONG_SELL", "WEAK_BUY", "WEAK_SELL"}
    conf = 0.0
    if policy and policy.ok:
        conf = float(policy.output.get("confidence") or 0.0)
    collapse = 0.0
    if gates and gates.ok:
        collapse = float(gates.output.get("collapse_rate") or 0.0)
    pnl_proxy = conf * size if actionable else 0.0
    return {
        "signal": signal,
        "actionable": actionable,
        "confidence": conf,
        "position_size": size,
        "collapse_rate": collapse,
        "pnl_proxy": pnl_proxy,
    }


async def _run_grid(
    scenarios: List[Dict[str, Any]],
    grid: Dict[str, List[Any]],
    *,
    max_configs: Optional[int] = None,
) -> List[Dict[str, Any]]:
    from agent.testing.scenario_runner import ScenarioRunner

    keys = list(grid.keys())
    combos = list(itertools.product(*(grid[k] for k in keys)))
    if max_configs is not None:
        combos = combos[: max_configs]

    results: List[Dict[str, Any]] = []
    runner = ScenarioRunner()

    for combo in combos:
        theta = dict(zip(keys, combo))
        settings_map = _theta_to_settings(theta)
        with _settings_override(settings_map):
            traces = await runner.run_all(scenarios)
        metrics = [_trace_metrics(t) for t in traces]
        actionable_n = sum(1 for m in metrics if m["actionable"])
        freq = actionable_n / max(len(metrics), 1)
        pnl_vals = [m["pnl_proxy"] for m in metrics if m["actionable"]]
        mean_pnl = sum(pnl_vals) / len(pnl_vals) if pnl_vals else 0.0
        collapse_vals = [m["collapse_rate"] for m in metrics]
        mean_collapse = sum(collapse_vals) / len(collapse_vals) if collapse_vals else 0.0
        results.append(
            {
                "theta": theta,
                "frequency": round(freq, 4),
                "mean_pnl_proxy": round(mean_pnl, 6),
                "max_dd_proxy": round(min(pnl_vals) if pnl_vals else 0.0, 6),
                "collapse_rate": round(mean_collapse, 4),
                "scenario_count": len(metrics),
            }
        )
    return results


def _pareto_frontier(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Non-dominated on (frequency, mean_pnl_proxy) maximizing both."""
    frontier: List[Dict[str, Any]] = []
    for i, a in enumerate(rows):
        dominated = False
        for j, b in enumerate(rows):
            if i == j:
                continue
            if (
                b["frequency"] >= a["frequency"]
                and b["mean_pnl_proxy"] >= a["mean_pnl_proxy"]
                and (
                    b["frequency"] > a["frequency"]
                    or b["mean_pnl_proxy"] > a["mean_pnl_proxy"]
                )
            ):
                dominated = True
                break
        if not dominated:
            frontier.append(a)
    return sorted(frontier, key=lambda r: (-r["mean_pnl_proxy"], -r["frequency"]))


def _optional_bayesian(
    rows: List[Dict[str, Any]],
    *,
    n_trials: int = 30,
) -> List[Dict[str, Any]]:
    try:
        import optuna
    except ImportError:
        return []

    def objective(trial: "optuna.Trial") -> float:
        theta = {
            "gate5_ratio": trial.suggest_float("gate5_ratio", 0.45, 1.05),
            "entry_quality_min": trial.suggest_float("entry_quality_min", 40.0, 70.0),
            "conviction_entry_floor": trial.suggest_float("conviction_entry_floor", 0.2, 0.5),
            "hypothesis_min_margin": trial.suggest_float("hypothesis_min_margin", 0.015, 0.06),
            "debounce_bars": trial.suggest_int("debounce_bars", 1, 3),
        }
        match = next((r for r in rows if r["theta"] == theta), None)
        if match:
            r = match
        else:
            return 0.0
        lam1, lam2 = 0.5, 0.3
        return r["mean_pnl_proxy"] - lam1 * abs(r["max_dd_proxy"]) - lam2 * r["collapse_rate"]

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=min(n_trials, len(rows)))
    return [{"best_params": study.best_params, "best_value": study.best_value}]


async def run_replay(
    *,
    out_dir: Path,
    max_configs: Optional[int] = None,
    bayesian: bool = False,
) -> Dict[str, Any]:
    from agent.testing.scenario_builder import ALL_SCENARIOS

    scenarios = [fn() for fn in ALL_SCENARIOS]
    grid_results = await _run_grid(scenarios, DEFAULT_GRID, max_configs=max_configs)
    frontier = _pareto_frontier(grid_results)
    report: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "grid_size": len(grid_results),
        "scenario_count": len(scenarios),
        "grid_results": grid_results,
        "pareto_frontier": frontier,
    }
    if bayesian:
        report["bayesian"] = _optional_bayesian(grid_results)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "pareto_frontier.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "logs" / "signal_recovery",
    )
    parser.add_argument(
        "--max-configs",
        type=int,
        default=None,
        help="Cap grid configs (default: full 243)",
    )
    parser.add_argument("--bayesian", action="store_true", help="Run optional Optuna BO")
    args = parser.parse_args()

    report = asyncio.run(
        run_replay(
            out_dir=args.out_dir,
            max_configs=args.max_configs,
            bayesian=args.bayesian,
        )
    )
    print(f"Grid configs: {report['grid_size']}")
    print(f"Pareto frontier size: {len(report['pareto_frontier'])}")
    print(f"Wrote {args.out_dir / 'pareto_frontier.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
