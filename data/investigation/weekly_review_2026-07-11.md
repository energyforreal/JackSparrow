# Weekly Review — 2026-07-11

**Baseline:** `0503847` / `hold_baseline_policy`  
**Program:** Thesis Intelligence (opened 2026-07-13)

---

## Rolling validation vs baseline

| Window | Policy HOLD % | current EV % | ml_only EV % | Recommendation |
|--------|---------------|-------------:|-------------:|----------------|
| 7d | 90.8% | -0.187 | -0.201 | hold_baseline_policy |
| 30d | 83.7% | -0.200 | -0.203 | hold_baseline_policy |

Archive: [`rolling/2026-07-11/`](rolling/2026-07-11/)

**Assessment:** No drift from baseline. Relaxation scenarios remain negative EV.

---

## Decision Quality Index

| Component | Score | Notes |
|-----------|------:|-------|
| thesis_ml_agreement | 95.87 | Shadow HOLD-dominant |
| replay_ev | 31.27 | 7d current -0.187% |
| shadow_disagreement_ev | 29.44 | Shadow PnL proxy 0 |
| no_rule_fired_rate | 10.83 | B4 rate 89.2% of ML-pass |
| regime_stability | 69.50 | flip_rate 0.061 |
| calibration | 100.00 | Replay labels N=12814, ECE=0.0 |
| **Composite DQI** | **50.52** | Baseline snapshot |

Artifact: [`dqi_2026-07-11.json`](dqi_2026-07-11.json)

---

## Thesis quality

| Metric | Value |
|--------|------:|
| B4 bucket (prior 24h log) | 96.3% |
| B4 rate (7d telemetry) | 89.2% |
| Dominant miss (neutral) | breakout `h_trend` |
| Prototype rule | `neutral_mild_trend` (flag off) |

Memo: [`thesis_rule_miss_2026-07-11.md`](thesis_rule_miss_2026-07-11.md)

---

## G6 / shadow

- 48h shadow: 95.87% agreement, 0 shadow entries — G6 closed (vacuous pass)
- Policy promotion: **not justified**

---

## Ops checklist

- [x] Daily validation script: `scripts/daily_validation.ps1`
- [x] Weekly bundle: `scripts/daily_validation.ps1 -Weekly`
- [x] WebSocket acceptance: no recv errors post-redeploy
- [x] G6 documented in [`promotion_gate_evaluation_g6_2026-07-11.md`](promotion_gate_evaluation_g6_2026-07-11.md)

---

## Next week

1. Log-feature join for thesis miss analysis (reduce default-0 bias)
2. Replay-only shadow eval for `AGENT_THESIS_NEUTRAL_MILD_TREND_ENABLED`
3. DQI week-over-week delta vs 45.03 baseline
