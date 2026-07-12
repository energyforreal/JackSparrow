# Scorecard — freq Stage 3 (flat-hyp ML ON)

**Stage start (UTC):** 2026-07-12T18:06:53+00:00  
**Scorecard at (UTC):** ~2026-07-12T18:07Z (T+apply)  

## Flags live (verified in agent)

| Flag | Value |
|------|-------|
| `V15_ADX_REGIME_FILTER_ENABLED` | `false` |
| `ENTRY_QUALITY_MIN_SCORE` | `45` |
| `JACKSPARROW_V43_MIN_EDGE_COST_RATIO` | `0.50` |
| `AGENT_TRADE_SCORE_MIN` | `45.0` |
| `AGENT_POLICY_ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS` | `true` |
| `AGENT_THESIS_USE_HURST_V2` | `true` |

## Funnel since Stage 3 start

Source: [`funnel_freq_stage3.md`](funnel_freq_stage3.md) — empty at T+apply (agent just recreated).

## Expected over 24–48h monitor

- Fewer `thesis_blocks_ml_adoption` / `fusion_ml_or_thesis_blocked` on flat cycles when ML gates pass and score ≥45
- Trend fires with scores ~45–54 should no longer emit `quality_below_floor` at min 55
- No `v15_adx_trending_filter` on high-ADX breakouts
- Watch chop / negative EV; apply kill criteria from [`FREQ_EXPERIMENT.md`](FREQ_EXPERIMENT.md)

## Decision

**Hold Stage 3 stack** for 24–48h monitor. Do not enable mild-trend or ADX thesis-aware. Risk knobs stay frozen.

## Ops

Agent healthy after recreate. Monitor window open from Stage 3 start UTC.
