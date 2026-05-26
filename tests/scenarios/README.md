# Scenario validation harness

Offline replay of synthetic market data through the v43 agent pipeline (no exchange).

## Run

```bash
python run_scenario_tests.py --list
python run_scenario_tests.py --save
python run_scenario_tests.py --scenario strong_breakout --verbose
```

- Default exit code uses **Tier 1** (pipeline health) only.
- `--strict` also requires behavioral checks from each scenario's `expected` dict.

## Environment

[`tests/scenarios/.env.scenario`](.env.scenario) is loaded automatically by [`run_scenario_tests.py`](../../run_scenario_tests.py) before settings initialize. Merge those keys into your root `.env` when promoting portfolio guard to live.

## Traces

JSON output: `tests/scenarios/traces/`
