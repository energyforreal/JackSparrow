# Scorecard — freq Stage 2 (quality 45 + Gate5 0.50)

**Stage start (UTC):** 2026-07-12T18:05:31+00:00  
**Scorecard at (UTC):** ~2026-07-12T18:06Z (T+apply)  
**Flags live (verified):**
- `V15_ADX_REGIME_FILTER_ENABLED=false`
- `ENTRY_QUALITY_MIN_SCORE=45`
- `JACKSPARROW_V43_MIN_EDGE_COST_RATIO=0.50`
- `AGENT_POLICY_ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS=false`
- `AGENT_TRADE_SCORE_MIN=55.0` (still baseline; matters for Stage 3 flat-ML override)

## Funnel since Stage 2 start

Source: [`funnel_freq_stage2.md`](funnel_freq_stage2.md) — empty window at T+apply (0 predictions yet).

| Layer | Count |
|-------|------:|
| Thesis fires | 0 |
| Quality below floor | 0 |
| Gate5 fail | 0 |
| Fills | 0 |

## Decision input (Phase A attribution)

| Factor | Share / count |
|--------|----------------|
| Flat thesis + ML blocked | ~82% of Phase A cycles |
| Trend fires blocked only by quality/Gate5 | 15 (now should admit if scores ≥45 and Gate5 eases) |
| Breakouts killed by ADX | 3 (Stage 1 already off) |

Stage 2 unlocks **thesis-fire path** only. Overall rate will still be dominated by flat-thesis HOLDs until Stage 3.

## Decision

**Proceed to Stage 3** (allow gated ML on flat hypothesis + align `AGENT_TRADE_SCORE_MIN=45` so ~47 scores can adopt). Goal remains considerable frequency, not thesis-only fills.

## Kill check

None at apply. Ops: agent healthy after recreate.
