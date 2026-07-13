# Frequency experiment — KILL / rollback

**Kill applied (UTC):** 2026-07-13 (~03:49Z / IST 09:19)  
**Experiment start:** 2026-07-12T18:06:53+00:00 (Stage 3 stack)  
**Reference:** [`FREQ_EXPERIMENT.md`](FREQ_EXPERIMENT.md), live trade forensics 2026-07-13

## Trigger

Adverse fill streak after Stage 1–3 admission relax. Kill criteria from FREQ_EXPERIMENT met (negative net EV / rapid adverse fills).

## Outcome (Stage 3 window → kill)

| Metric | Value |
|--------|------:|
| Executed SHORT fills | 7 |
| Thesis type | breakout (not flat-ML) |
| Net PnL (approx.) | **−$4.41** |
| Fee drag | ~$0.51 / round-trip |
| Net winners | 1 / 7 |

## Causal gate

**`V15_ADX_REGIME_FILTER_ENABLED=false` (Stage 1)** — disables `v15_adx_trending_filter`.

Counterfactual on all 7 fills (ADX 26–76):

| Gate | Would block under baseline? |
|------|----------------------------:|
| ADX regime filter (ON, max 25) | **7 / 7** |
| Gate5 ratio 0.75 | 0 / 7 |
| Quality / trade-score 55 | 0 / 7 |
| Flat-hyp ML adoption | 0 / 7 (unused) |

Pre-relax same day: 0 executes; 3× `v15_adx_trending_filter` rejects.

## Restored `.env` (baseline)

```env
V15_ADX_REGIME_FILTER_ENABLED=true
JACKSPARROW_V43_MIN_EDGE_COST_RATIO=0.75
ENTRY_QUALITY_MIN_SCORE=55
AGENT_TRADE_SCORE_MIN=55.0
AGENT_POLICY_ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS=false
```

Kept frozen / on: `AGENT_THESIS_USE_HURST_V2=true`, `V15_ADX_THESIS_AWARE_ENABLED=false`, `AGENT_THESIS_NEUTRAL_MILD_TREND_ENABLED=false`.

## Do not re-open without

1. Rolling replay (7d + 30d) positive EV for the proposed scenario  
2. Explicit promotion-gate write-up  
3. One-knob deploy windows (never Stage 1–3 simultaneous again)

## Next research (not production)

- Fee-aware breakout hold / TP sizing (gross often right, net wrong)  
- Thesis-aware ADX exemption only behind replay — do not enable live to “get fills”
