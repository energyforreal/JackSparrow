# Evidence Accumulation Fix — 2026-07-12 (Task 1)

## Problem

`decision_evidence/2026-07-12/coverage.json` previously showed `N=33 / sweep_gate=FAIL` because
`assemble_decision_evidence.py` was **log-primary** and defaulted to the day-scoped
`agent_exp_shadow_2026-07-12.log` (33 `hold_at_synthesis` events). Cumulative
`decision_telemetry.ndjson` was unused for record *production*.

## Fix

1. [`scripts/signal_recovery/decision_evidence.py`](../../scripts/signal_recovery/decision_evidence.py)
   `enrich_from_sources` now emits **telemetry-primary B4** rows when:
   - `event == v43_prediction_complete`
   - `hypothesis_no_rule_fired` (or `thesis_no_rule_fired`) in reason codes
   - signal HOLD
   - gates passed (`reject` tag or g1+g2–g5 / no `gate_reject`)
   - all 8 `CORE_THESIS_FEATURES` present in `extra.features`
2. Log-derived rows remain primary; telemetry rows within 15s of a log hold (same symbol)
   are deduped.
3. [`assemble_decision_evidence.py`](../../tools/commands/assemble_decision_evidence.py)
   no longer hard-requires a log file when telemetry is available.

## Result (this run)

| Metric | Value |
|--------|------:|
| high_confidence | **289** |
| sweep_gate | **PASS** |
| telemetry_only | 261 |
| telemetry_path | `logs/agent/signal_recovery/decision_telemetry.ndjson` |
| log_path | `data/investigation/agent_exp_168h_holds.log` |

Re-run:

```powershell
python tools/commands/assemble_decision_evidence.py --hours 168 `
  --log data/investigation/agent_exp_168h_holds.log `
  --telemetry logs/agent/signal_recovery/decision_telemetry.ndjson `
  --out-dir data/investigation/decision_evidence/2026-07-12
```
