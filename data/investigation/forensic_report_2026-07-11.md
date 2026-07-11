# JackSparrow Decision Pipeline Forensic Investigation

**Report date:** 2026-07-11  
**Analysis window:** ~12 hours (2026-07-10 18:00 UTC → 2026-07-11 06:10 UTC)  
**Deploy build:** `GIT_COMMIT=0503847`  
**Deliverable type:** Engineering forensic investigation (not a policy recommendation)

---

## 1. Epistemic framing

### Evidence levels

| Level | Meaning | Example |
|-------|---------|---------|
| **Observed** | Directly measured at runtime | `hold_at_synthesis`, `trade_allowed=false` |
| **Derived** | Computed from observations | 189/193 policy HOLD |
| **Experimental** | Replay/shadow results (assumption-bound) | Counterfactual EV, threshold sweeps |
| **Hypothetical** | Not yet validated for production | Enabling 3A.2 improves live performance |

### Confidence table

| Statement | Confidence | Evidence level |
|-----------|------------|----------------|
| Infrastructure healthy | **Very High** | Observed |
| `AGENT_START_MODE=MONITORING` is not suppressing trades | **High** | Observed |
| Policy is the active rejection mechanism | **High** | Observed + Derived |
| Tested relaxation strategies produced positive expectancy | **Not supported** | Experimental |
| Current abstention is globally optimal | **Unknown** | Hypothetical |

### Mechanism vs reason vs cause

| Layer | Jul 10–11 example | Status |
|-------|-------------------|--------|
| **Mechanism** | Policy emitted `HOLD`; handler emitted `hold_at_synthesis` | Observed |
| **Reason** | `hypothesis_no_rule_fired`, `thesis_type=flat`, `fusion_ml_or_thesis_blocked` | Observed |
| **Cause** | Whether rejections improved risk-adjusted outcomes | Experimental (assumption-bound); not globally proven |

### Causal chain (supported by evidence)

```
Market data healthy
        │
        ▼
Feature generation healthy
        │
        ▼
ML produces directional candidates
        │
        ▼
Policy evaluates thesis
        │
        ▼
thesis_blocks_ml_adoption
        │
        ▼
trade_allowed = false
        │
        ▼
hold_at_synthesis
        │
        ▼
No risk approval
        │
        ▼
No orders
```

`AGENT_START_MODE=MONITORING` does not appear in this chain: the agent initializes
market data, transitions to `OBSERVING`, and continues full decision evaluation.
Startup mode is not participating in the rejection path.

---

## 2. Executive summary

The JackSparrow stack is operational. The decision pipeline generated **193 v43 cycles** in 12h with **zero trade executions**. ML gates passed on every cycle; policy collapsed **98%** to HOLD; handler blocked the remaining **4** policy-approved LONGs via ADX filter.

This report documents **what happened**. Whether policy should change requires
counterfactual replay and forward shadow evaluation under validated assumptions.
Preliminary replay (Jul 11 artifact) does not support relaxing the tested gates
in the analyzed windows; a production policy change remains unjustified until
multi-regime validation and forward shadow testing consistently demonstrate
positive risk-adjusted outcomes.

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
| Replay ML candidates | 182 (telemetry rows with ML direction; 11 cycles lack replay extract) |
| ML gate passes | 193 (100%) |
| Policy HOLD | 189 (98%) |
| Policy LONG | 4 (2%) |
| Handler `hold_at_synthesis` | 189 |
| Handler `v15_adx_trending_filter` | 4 |
| Trade executions | 0 |
| Avg trade score | 47.7 (threshold 55) |
| Collapse rate | 99.6% |
| Lifetime `v43_cnt_trades_executed` | 12 (cumulative, not in window) |

**Note:** Funnel count (193) is the full decision window; replay candidate set (182) is
`v43_prediction_complete` telemetry rows with extractable ML direction.

---

## 5. Execution conversion alert

The `over_gating_regression` alert fired during the window (225+ raw signals / 0
executions in 7d lookback). This is relabeled here as an **execution conversion
alert** — it detects volume mismatch (many candidates, few executions), not whether
abstention was suboptimal. Replay suggests zero executions may have been preferable
under tested assumptions in this window.

---

## 6. Infrastructure notes

- All 5 Docker containers healthy at analysis time
- Delta WebSocket concurrent `recv()` bug (~480k errors/12h) degrades log retention; REST fallback works; decision pipeline unaffected
- Telemetry NDJSON is the reliable source for funnel analysis

### Additional validation (Jul 11)

A background Docker log scan confirmed that `AGENT_START_MODE=MONITORING` is
operating as designed. The agent initializes market data, transitions to
`OBSERVING`, and continues full decision evaluation. Repeated `trade_allowed=false`,
`thesis_blocks_ml_adoption`, and `hold_at_synthesis` events confirm that the
absence of trades is attributable to policy decisions rather than startup mode,
infrastructure, or connectivity. This strengthens the conclusion that policy is
the active rejection layer while leaving the profitability of alternative policies
to be determined by counterfactual replay and shadow evaluation.

| Hypothesis | Status | Evidence |
|------------|--------|----------|
| Docker/container issue | **Ruled out** | Services healthy; decision loop active |
| Market data failure | **Ruled out** | Market data streaming; REST fallback working |
| `AGENT_START_MODE=MONITORING` preventing trading | **Ruled out** | Agent enters `OBSERVING`; decisions continue |
| Decision pipeline stalled | **Ruled out** | ML, policy, and handler execute every cycle |
| Policy/handler rejection | **Supported** | `trade_allowed=false`, `hold_at_synthesis`, `thesis_blocks_ml_adoption` |

---

## 7. Counterfactual execution table (12h window, realized labels)

Populated by `tools/commands/counterfactual_replay.py` on 2026-07-11. Full artifacts: [`counterfactual_replay_2026-07-11.json`](counterfactual_replay_2026-07-11.json), [`directional_stability_2026-07-11.json`](directional_stability_2026-07-11.json).

**Replay qualification:** Results reflect the assumptions of
`tools/commands/counterfactual_replay.py` — realized candle labels where available
(Jul 11 artifact: 182/182 labeled, 0 errors, `label_source=candles`),
`economic=true` exit model (SL/TP excursions, taker fees, slippage), 2-bar hold
horizon, and scenario inclusion filters. Earlier investigation tools (economic
replay, threshold replay, shadow evaluation) used different assumptions and are
not interchangeable with this artifact. Conclusions inherit the replay methodology;
they do not establish global optimality of abstention.

| Scenario | Trades | Win % | PF | EV % | Max DD % | Exposure | Avg hold |
|----------|--------|-------|-----|------|----------|----------|----------|
| `current` | 0 | — | — | 0.0 | 0.0 | 0.0 | — |
| `ml_adopt_flat` | 0 | — | — | 0.0 | 0.0 | 0.0 | — |
| `ml_adopt_flat_score50` | 0 | — | — | 0.0 | 0.0 | 0.0 | — |
| `ml_only` | 182 | 1.65 | 0.046 | **-0.18** | 1.74 | 9.1 | 1.99 |
| `no_adx` | 4 | 0.0 | 0.0 | **-0.21** | 0.04 | 0.2 | 2.0 |
| `no_thesis_veto` | 182 | 1.65 | 0.046 | **-0.18** | 1.74 | 9.1 | 1.99 |

**Scenario note:** `ml_only` and `no_thesis_veto` use identical inclusion filters in the
current replay implementation (all ML-directional candidates); results are not independent
confirmations.

**30d validation** (`counterfactual_replay_30d.json`):

| Scenario | Trades | Win % | EV % | Max DD % |
|----------|--------|-------|------|----------|
| `current` (policy-approved, handler-passed) | 374 | 7.22 | **-0.20** | 3.74 |
| `ml_adopt_flat` | 167 | 2.4 | **-0.21** | 1.75 |
| `ml_only` | 2243 | 3.08 | **-0.20** | 22.76 |

Promotion gates G2/G4 **fail** for `ml_adopt_flat`. See [`promotion_gate_evaluation_2026-07-11.md`](promotion_gate_evaluation_2026-07-11.md).

**12h regime coverage:** essentially neutral-only; conclusions are regime-specific.

**Directional stability:** flip rate 9.4%, mean run length 10.1 — low oscillation; abstention not explained by chop flips.

---

## 8. Historical consistency

Post-deploy Jul 9 investigation showed **100% B4 bucket** (ML gates pass, policy HOLD, flat hypothesis). Jul 10–11 behavior is consistent — not a transient anomaly.

---

## 9. What this report does not claim

- That policy is "too conservative"
- That enabling `AGENT_POLICY_ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS` will improve PnL
- That ADX-blocked LONGs were missed winners
- That current abstention is globally optimal

**What experimental evidence does show (assumption-bound):** Under the replay
assumptions documented in Section 7, the tested relaxed policies produced lower
realized expectancy than abstention in the analyzed 12h/30d windows — negative EV on
`ml_only`, `no_thesis_veto`, and `ml_adopt_flat`. This weakens the hypothesis that
"simply relaxing policy will improve performance" but does not prove current abstention
is optimal across regimes or replay methodologies. 3A.2 testnet remains **not enabled**.

---

## 11. Evidence matrix

| Question | Answer | Evidence level |
|----------|--------|----------------|
| Infrastructure healthy? | Yes | Observed |
| Market data healthy? | Yes | Observed |
| `AGENT_START_MODE=MONITORING` suppressing trades? | No | Observed |
| ML generating signals? | Yes | Observed |
| Policy rejecting signals? | Yes | Observed + Derived |
| Alternative policy better under replay assumptions? | No | Experimental |
| Should production policy change now? | Not justified | Engineering judgment |

Investigation closed: [`investigation_closure_2026-07-11.md`](investigation_closure_2026-07-11.md).

---

## 10. Next steps

1. Continue 48–72h forward shadow collection (`LATENT_SHADOW_MODE=true`) per [`shadow_forward_runbook.md`](shadow_forward_runbook.md)
2. Run daily rolling validation: `python tools/commands/rolling_validation.py --economic`
3. Re-evaluate promotion gates when regime shifts or G6 OOS shadow window completes
4. Redeploy agent after WebSocket recv fix in `delta_client.py`
