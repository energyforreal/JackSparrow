# JackSparrow Decision Pipeline Forensic Investigation

**Report date:** 2026-07-11  
**Analysis window:** ~12 hours (2026-07-10 18:00 UTC → 2026-07-11 06:10 UTC)  
**Deploy build:** `GIT_COMMIT=0503847`  
**Deliverable type:** Engineering forensic investigation (not a policy recommendation)

---

## 1. Epistemic framing

| Observation | Confidence | Status |
|-------------|------------|--------|
| Pipeline healthy through policy | High | Observed |
| Policy blocked all candidates | High | Observed |
| Policy is dominant rejection layer (this window) | Medium-high | Inferred from funnel |
| Relaxing policy improves PnL | Unknown | Requires counterfactual replay |
| Zero trades was suboptimal | Unknown | May be optimal in ranging chop |

### Mechanism vs reason vs cause

| Layer | Jul 10–11 example | Status |
|-------|-------------------|--------|
| **Mechanism** | Policy emitted `HOLD`; handler emitted `hold_at_synthesis` | Observed |
| **Reason** | `hypothesis_no_rule_fired`, `thesis_type=flat`, `fusion_ml_or_thesis_blocked` | Observed |
| **Cause** | Whether rejections improved risk-adjusted outcomes | Unknown until replay |

---

## 2. Executive summary

The JackSparrow stack is operational. The decision pipeline generated **193 v43 cycles** in 12h with **zero trade executions**. ML gates passed on every cycle; policy collapsed **98%** to HOLD; handler blocked the remaining **4** policy-approved LONGs via ADX filter.

This report documents **what happened**. Whether policy should change requires the counterfactual replay experiments specified in the action plan.

---

## 3. Decision funnel (Sankey)

```
193 Candle closes / v43 cycles
        │
        ▼
193 ML G1–G5 pass (100%)
   110 LONG / 83 SHORT
        │
   ┌────┴────────┐
   ▼             ▼
189 HOLD       4 LONG
   │             │
   ▼             ▼
hold_at_      v15_adx_
synthesis     trending_filter
   │             │
   └──────┬──────┘
          ▼
    0 Risk approval
          ▼
    0 Orders
          ▼
    0 Executions
```

---

## 4. Key metrics (12h window)

| Metric | Value |
|--------|------:|
| v43 decision cycles | 193 (~16/hr) |
| ML gate passes | 193 (100%) |
| Policy HOLD | 189 (98%) |
| Policy LONG | 4 (2%) |
| Handler `hold_at_synthesis` | 189 |
| Handler `v15_adx_trending_filter` | 4 |
| Trade executions | 0 |
| Avg trade score | 47.7 (threshold 55) |
| Collapse rate | 99.6% |
| Lifetime `v43_cnt_trades_executed` | 12 (cumulative, not in window) |

---

## 5. Execution conversion anomaly

The `over_gating_regression` alert fired during the window (225+ raw signals / 0 executions in 7d lookback). This is relabeled here as an **execution conversion anomaly** — it detects volume mismatch, not whether abstention was suboptimal.

---

## 6. Infrastructure notes

- All 5 Docker containers healthy at analysis time
- Delta WebSocket concurrent `recv()` bug (~480k errors/12h) degrades log retention; REST fallback works; decision pipeline unaffected
- Telemetry NDJSON is the reliable source for funnel analysis

---

## 7. Counterfactual execution table (12h window, realized labels)

Populated by `tools/commands/counterfactual_replay.py` on 2026-07-11. Full artifacts: [`counterfactual_replay_2026-07-11.json`](counterfactual_replay_2026-07-11.json), [`directional_stability_2026-07-11.json`](directional_stability_2026-07-11.json).

| Scenario | Trades | Win % | PF | EV % | Max DD % | Exposure | Avg hold |
|----------|--------|-------|-----|------|----------|----------|----------|
| `current` | 0 | — | — | 0.0 | 0.0 | 0.0 | — |
| `ml_adopt_flat` | 0 | — | — | 0.0 | 0.0 | 0.0 | — |
| `ml_adopt_flat_score50` | 0 | — | — | 0.0 | 0.0 | 0.0 | — |
| `ml_only` | 182 | 1.65 | 0.046 | **-0.18** | 1.74 | 9.1 | 1.99 |
| `no_adx` | 4 | 0.0 | 0.0 | **-0.21** | 0.04 | 0.2 | 2.0 |
| `no_thesis_veto` | 182 | 1.65 | 0.046 | **-0.18** | 1.74 | 9.1 | 1.99 |

**30d validation** (`ml_adopt_flat`): 167 trades, 2.4% win, EV **-0.21%**, PF 0.005 — promotion gates G2/G4 **fail**. See [`promotion_gate_evaluation_2026-07-11.md`](promotion_gate_evaluation_2026-07-11.md).

**Directional stability:** flip rate 9.4%, mean run length 10.1 — low oscillation; abstention not explained by chop flips.

---

## 8. Historical consistency

Post-deploy Jul 9 investigation showed **100% B4 bucket** (ML gates pass, policy HOLD, flat hypothesis). Jul 10–11 behavior is consistent — not a transient anomaly.

---

## 9. What this report does not claim

- That policy is "too conservative"
- That enabling `AGENT_POLICY_ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS` will improve PnL
- That ADX-blocked LONGs were missed winners

Counterfactual replay with realized market labels (12h / 7d / 30d) **supports** the above: negative EV on relaxed scenarios; 3A.2 testnet **not enabled**.

---

## 10. Next steps

1. Continue 48–72h forward shadow collection (`LATENT_SHADOW_MODE=true`) per [`shadow_forward_runbook.md`](shadow_forward_runbook.md)
2. Re-evaluate promotion gates when regime shifts or G6 OOS shadow window completes
3. Monitor WebSocket recv fix in `delta_client.py` after agent redeploy
