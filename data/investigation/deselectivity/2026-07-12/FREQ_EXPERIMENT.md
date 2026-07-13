# Frequency experiment — staged admission relax (testnet)

**Start (UTC):** 2026-07-12T18:03:07+00:00  
**Context:** Overrides Phase A “do not lower floors” freeze for a controlled fill-rate test.  
**Keep frozen:** risk size / DD / margin; `V15_ADX_THESIS_AWARE_ENABLED`; `AGENT_THESIS_NEUTRAL_MILD_TREND_ENABLED`.  
**Keep on:** `AGENT_THESIS_USE_HURST_V2=true`

## Baseline flags (pre-experiment)

| Flag | Baseline |
|------|----------|
| `V15_ADX_REGIME_FILTER_ENABLED` | `true` |
| `JACKSPARROW_V43_MIN_EDGE_COST_RATIO` | `0.75` |
| `ENTRY_QUALITY_MIN_SCORE` | unset → default **55** |
| `AGENT_TRADE_SCORE_MIN` | `55.0` (lowered to 45 at Stage 3 for flat-ML) |
| `AGENT_POLICY_ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS` | `false` |
| `AGENT_THESIS_USE_HURST_V2` | `true` |

## Rollback values (restore last stage on kill)

```env
V15_ADX_REGIME_FILTER_ENABLED=true
JACKSPARROW_V43_MIN_EDGE_COST_RATIO=0.75
ENTRY_QUALITY_MIN_SCORE=55
AGENT_TRADE_SCORE_MIN=55.0
AGENT_POLICY_ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS=false
```

Then: `docker compose up -d agent` and verify via `agent.core.config.settings`.

## Kill criteria (any stage — roll back immediately)

- Risk / G1 / conditional-handler reject share outside ±15% of baseline
- Rapid adverse fill streak or DD breach vs baseline tolerance
- Ops unhealthy (no decisions, stale market data, order errors)

## Stages

### Stage 1 — ADX filter OFF

- Change: `V15_ADX_REGIME_FILTER_ENABLED=false`
- Stage start UTC: **2026-07-12T18:04:07+00:00**
- Applied: verified `v15_adx_regime_filter_enabled=False`
- Monitor: 12–24h fills, `handler_reject_reason`, risk veto
- Pass/hold: clean fills without risk spike
- Fail/next: still ~0 fills → Stage 2 (Phase A attribution already showed quality/Gate5 bind trend fires)

### Stage 2 — Quality 45 + Gate5 0.50

- Change: `ENTRY_QUALITY_MIN_SCORE=45`, `JACKSPARROW_V43_MIN_EDGE_COST_RATIO=0.50`
- Stage start UTC: **2026-07-12T18:05:31+00:00**
- Applied: verified `entry_quality_min=45.0`, `gate5=0.5`, ADX still off
- Monitor: 24h thesis-fire → non-HOLD, fills, EV/DD
- Pass/hold: meaningful fill rate with acceptable EV/DD
- Fail/next: flat-thesis HOLDs still dominate → Stage 3

### Stage 3 — Flat-hyp ML adoption

- Change: `AGENT_POLICY_ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS=true`
- Also set `AGENT_TRADE_SCORE_MIN=45` (was 55) so flat-ML override can clear scores ~47; rollback restores 55.0
- Stage start UTC: **2026-07-12T18:06:53+00:00**
- Applied: verified `allow_flat_ml=True`, `trade_score_min=45.0`
- Monitor: 24–48h; less `thesis_blocks_ml_adoption`; fill rate; chop/EV

## Separation from Phase A

Phase A window: `2026-07-12T10:21:37+00:00` → Stage 1 start.  
Frequency experiment telemetry: use `--since` stage start timestamps below; artifacts `funnel_freq_stageN` / `scorecard_freq_stageN.md`.

## Stage apply log

| Stage | Applied UTC | Notes |
|-------|-------------|-------|
| 1 | 2026-07-12T18:04:07+00:00 | ADX filter off; verified in container |
| 2 | 2026-07-12T18:05:31+00:00 | quality 45 + Gate5 0.50; verified |
| 3 | 2026-07-12T18:06:53+00:00 | flat-ML on + trade_score_min 45; verified |

## Current live stack (end of apply session)

```env
V15_ADX_REGIME_FILTER_ENABLED=false
JACKSPARROW_V43_MIN_EDGE_COST_RATIO=0.50
ENTRY_QUALITY_MIN_SCORE=45
AGENT_TRADE_SCORE_MIN=45.0
AGENT_POLICY_ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS=true
AGENT_THESIS_USE_HURST_V2=true
```

## KILLED 2026-07-13

Baseline restored. See [`FREQ_EXPERIMENT_KILL.md`](FREQ_EXPERIMENT_KILL.md) — Stage 1 ADX OFF was causal; Stages 2–3 not causal for the loss fills.

## Rollback procedure (kill → restore baseline)

1. Restore rollback block in `.env` (see “Rollback values” above).
2. `docker compose up -d agent --force-recreate`
3. Verify:
   ```powershell
   docker compose exec agent python -c "from agent.core.config import settings; print(settings.v15_adx_regime_filter_enabled, settings.entry_quality_min_score, settings.jacksparrow_v43_min_edge_cost_ratio, settings.agent_policy_allow_gated_ml_on_flat_hypothesis, settings.agent_trade_score_min)"
   ```
   Expect: `True 55.0 0.75 False 55.0`

## Monitor commands (24–48h)

```powershell
python tools/commands/phase_a_funnel_from_telemetry.py --since 2026-07-12T18:06:53+00:00 --out data/investigation/deselectivity/2026-07-12/funnel_freq_stage3_day1
python tools/commands/phase3_daily_forensics.py --workstream hurst_v2 --skip-rolling
```

