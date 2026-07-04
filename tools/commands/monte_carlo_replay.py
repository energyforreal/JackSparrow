"""Multi-regime replay and Monte Carlo validation tooling."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any, Dict, List


def _load_fixture(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_monte_carlo(
    *,
    runs: int = 100,
    base_expectancy: float = -0.001,
    slippage_std: float = 0.0003,
    fee_rate: float = 0.001,
) -> Dict[str, Any]:
    """Simulate trade outcomes with randomized slippage/fees."""
    outcomes: List[float] = []
    for _ in range(runs):
        slip = abs(random.gauss(0.0, slippage_std))
        fee = fee_rate * 2.0
        noise = random.gauss(0.0, 0.002)
        outcomes.append(base_expectancy + noise - slip - fee)
    outcomes.sort()
    p5 = outcomes[int(0.05 * len(outcomes))]
    p95 = outcomes[int(0.95 * len(outcomes))]
    return {
        "runs": runs,
        "mean_expectancy": sum(outcomes) / len(outcomes),
        "p5": p5,
        "p95": p95,
        "pct_positive": sum(1 for x in outcomes if x > 0) / len(outcomes),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Monte Carlo replay with slippage/fees")
    parser.add_argument("--runs", type=int, default=100)
    parser.add_argument("--fixture-dir", type=str, default="tests/fixtures/regime_scenarios")
    args = parser.parse_args()

    result = run_monte_carlo(runs=args.runs)
    print(json.dumps(result, indent=2))

    fixture_dir = Path(args.fixture_dir)
    if fixture_dir.is_dir():
        for fp in sorted(fixture_dir.glob("*.json")):
            print(f"fixture: {fp.name} loaded ({len(_load_fixture(fp))} keys)")


if __name__ == "__main__":
    main()
