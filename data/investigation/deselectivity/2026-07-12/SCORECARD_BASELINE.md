# Baseline scorecard — 2026-07-12 (pre Hurst-v2)

## Reject mix

| Reason | Count | Share |
|--------|------:|------:|
| hold_at_synthesis | 92 | 93.9% |
| v15_adx_trending_filter | 6 | 6.1% |

Hold primary cause: **hypothesis_no_rule_fired** 100% (B4).  
V43: signals_raw≈3504, trades_executed≈12, collapse≈0.9966.  
Telemetry dual-write: 213/267 recent hurst rows have both `hurst_60` and `hurst_60_v2`.

## Flags at baseline

| Flag | Value |
|------|-------|
| AGENT_THESIS_USE_HURST_V2 | false |
| ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS | false |
| V15_ADX_THESIS_AWARE_ENABLED | false |
| V15_ADX_REGIME_FILTER_ENABLED | true |

## Negative-control expectations after A

| Metric | Expectation |
|--------|-------------|
| G1 admit rate | ~unchanged |
| Handler rejects \| non-HOLD thesis | ~unchanged mix quality |
| Risk veto rate | ~unchanged |

## Artifacts

- `rejection_forensics_baseline.json`
- `hypothesis_breakdown_baseline.json`
- `redis_gate_state_BTCUSD.txt`
- `dual_write_check.txt`
- `baseline_agent.log`
