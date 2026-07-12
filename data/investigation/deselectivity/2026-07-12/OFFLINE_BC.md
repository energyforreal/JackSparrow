# Offline B/C prep — 2026-07-12

Flags remain **false**: `ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS`, `V15_ADX_THESIS_AWARE_ENABLED`.

## B — Policy (flat-hyp + gated ML)

### Forward / promotion-style CF
[`counterfactual_replay_day0.json`](counterfactual_replay_day0.json):

- Recommendation: **`hold_baseline_policy`**
- Promotion gates: G1 sample fail (n=0), G2 net EV fail, G4 regime fail; G3 DD / G5 stability pass
- **Do not enable 3A.2** on this evidence

### Selection bias (Flat hold population)
From 47 `hold_at_synthesis` events ([`offline_bc_analysis.json`](offline_bc_analysis.json)):

| Feature | n | mean | median |
|---------|--:|-----:|-------:|
| ADX | 47 | 38.5 | 38.3 |
| vol_regime | 47 | 0.86 | 0.86 |
| spread | 47 | 0.15 | 0.16 |
| ATR / funding | 0 | — | — |

**Note:** No recent executed fills in-window for a true Flat+ML vs Executed table; bias analysis is Flat-HOLD feature dist only. Re-run when fills exist under A or paper.

## C — Handler (ADX)

| Metric | Value |
|--------|------:|
| ADX reject n (day log) | 5 |
| ADX buckets | **100% in 45–55** |
| Mean ADX | 49.6 |
| Economic replay net win % | **0%** |
| Avg net return % | **−0.23** |
| promotion_gate_3b | **blocked** (n=5 &lt; 30, EV negative) |

Artifacts: [`economic_replay_adx_day0.json`](economic_replay_adx_day0.json).

**Do not enable 3B.** Continue accumulating ADX rejects under live A toward n≥30.
