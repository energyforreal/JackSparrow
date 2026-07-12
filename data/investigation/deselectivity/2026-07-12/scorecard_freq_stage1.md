# Scorecard — freq Stage 1 (ADX filter OFF)

**Stage start (UTC):** 2026-07-12T18:04:07+00:00  
**Scorecard at (UTC):** 2026-07-12T18:05:00Z (T+~1m apply + funnel)  
**Flag live:** `V15_ADX_REGIME_FILTER_ENABLED=false` (verified in agent)  
**Unchanged:** quality floor 55, Gate5 0.75, flat-hyp ML false, hurst_v2 true

## Funnel since Stage 1 start

Source: [`funnel_freq_stage1.md`](funnel_freq_stage1.md)

| Layer | Count |
|-------|------:|
| Thesis fires | 0 |
| Quality below floor | 0 |
| Gate5 fail | 0 |
| HOLD after thesis fire | 0 |
| Fills / executed | 0 (expected at T+1m) |

Window too short for rate stats; Stage 1 only removes ADX handler veto on rare quality-passing breakouts.

## Context from Phase A + 24h forensics (decision input)

| Evidence | Result |
|----------|--------|
| Phase A (~7h) ADX rejects | 3 breakout LONGs only |
| Phase A quality/Gate5 on trend fires | 15/15 held |
| Latest 24h funnel (`funnel_hurst_v2`) | fires=52, quality_below=15, gate5_fail=15, hold_after_fire=15 |
| Risk approvals → fills | 0 |

Stage 1 cannot unlock the binding bottleneck (quality + Gate5 on trend fires). ADX-off remains useful so future breakouts are not killed, but fill rate will stay near zero without Stage 2.

## Decision

**Proceed to Stage 2** (quality 45 + Gate5 0.50). Do not hold on Stage 1 alone for “considerable frequency.”

Monitor Stage 1 ADX effect in parallel after Stage 2 lands (handler should not show `v15_adx_trending_filter`).

## Kill check

None tripped at apply (ops healthy; agent recreated successfully).
