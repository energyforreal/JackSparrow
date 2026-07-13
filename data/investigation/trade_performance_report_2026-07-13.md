# Trade execution & performance report

**Window:** 2026-07-11 → 2026-07-13 (IST report ~11:42)  
**Symbol / venue:** BTCUSD · Delta India testnet  
**Sources:** `decision_telemetry.ndjson`, agent fill + `position_closed_successfully` logs  
**Related:** [`FREQ_EXPERIMENT_KILL.md`](deselectivity/2026-07-12/FREQ_EXPERIMENT_KILL.md)

---

## Executive summary

All realized trading in this window occurred **only** during the frequency-experiment window (ADX filter OFF). **7 breakout SHORT** round-trips netted **≈ −$4.41**. Before that experiment and after the kill/redeploy: **0 executes**.

| Metric | Value |
|--------|------:|
| Round trips | 7 |
| Side | 100% SHORT (thesis `breakout_short`) |
| Size | 4.0 contracts |
| Gross winners | 5 / 7 |
| Net winners | 1 / 7 |
| Net PnL | **−$4.41** |
| Typical RT fee | ~$0.51 |

---

## How trades are carried out

1. Candle close → IC / v43 prediction (expected return + gate stack)  
2. Thesis engine fused under `AGENT_POLICY_MODE=ml_or_thesis`  
3. Policy emits LONG / SHORT / HOLD with `trade_score` and sizing  
4. Trading handler applies stale-age, **ADX regime**, risk, debounce  
5. Exchange gateway places Delta testnet order (~60% margin fraction)  
6. Lifecycle / brackets manage exit → flat  

**What filled:** only steps that cleared the handler after Stage 1 turned `V15_ADX_REGIME_FILTER_ENABLED=false`. Flat-ML (Stage 3) was on but **unused** — every fill had a live breakout thesis.

---

## Execution by phase

| Phase | Gates | Executes | Dominant blocks | PnL |
|-------|-------|---------:|-----------------|-----|
| Pre-freq (→ Jul 12 18:06Z) | ADX ON, Gate5 0.75, quality 55 | **0** | 29× `v15_adx_trending_filter`; HOLDs | — |
| Freq experiment | ADX OFF, Gate5 0.50, quality 45, flat-ML ON | **7** | HOLDs on non-breakout cycles | **−$4.41** |
| Post-kill (since ~03:52Z Jul 13) | Baseline restored | **0** | Flat thesis → `thesis_blocks_ml_adoption` | $0 |

Pre-freq already produced many breakout SHORT/LONG **policy** signals; the ADX trending filter stopped them from becoming orders. Disabling that filter is what created the fill set.

---

## Trade ledger

| # | Entry (UTC) | Hold | Entry → Exit | ADX | Score | Pts | Gross | Fees | Net | Outcome driver |
|---|-------------|------|--------------|-----|-------|-----|-------|------|-----|----------------|
| 1 | Jul 12 22:26 | 86m | 63817 → 63796 | 75.5 | 62.4 | +22 | +0.09 | 0.51 | **−0.42** | Fees > move |
| 2 | Jul 12 23:55 | 16m | 63738 → 64250 | 39.7 | 62.6 | −512 | −2.05 | ~0.51 | **−2.56** | Short into bounce |
| 3 | Jul 13 00:40 | 55m | 63578 → 63588 | 43.8 | 62.6 | −10 | −0.04 | 0.51 | **−0.55** | Wrong-way + fees |
| 4 | Jul 13 01:40 | 7m | 63668 → 63587 | 26.1 | 59.2 | +81 | +0.32 | 0.51 | **−0.19** | Gross win, net loss |
| 5 | Jul 13 01:48 | 26m | 63575 → 63445 | 26.3 | 56.0 | +130 | +0.52 | 0.51 | **+0.01** | Only net winner |
| 6 | Jul 13 02:15 | 8m | 63439 → 63384 | 43.9 | 62.1 | +55 | +0.22 | 0.51 | **−0.29** | Gross win, net loss |
| 7 | Jul 13 02:25 | 33m | 63368 → 63344 | 41.2 | 59.0 | +23 | +0.09 | 0.51 | **−0.41** | Gross win, net loss |

---

## Reasons for that performance

### 1. Admission (primary)

`V15_ADX_REGIME_FILTER_ENABLED=false` removed `v15_adx_trending_filter` (ADX &gt; 25).  
Counterfactual: **7 / 7** fills would have been blocked under baseline ADX.  
Gate5 0.50, quality 45, and flat-ML were **not** causal for this set (scores 56–63; edge already cleared 0.75; thesis was breakout).

### 2. Fee drag vs scalp edge

Round-trip fees ≈ **$0.51**. Typical winning gross was **$0.09–$0.32**, so directionally correct trades still lost net. Only one trade cleared costs (+$0.01).

### 3. Path risk on high-ADX breakout shorts

Trade 2 (−$2.56) dominates the loss: short into a sharp bounce. Remaining trades were short holds (7–86m) in a regime where ADX was elevated but follow-through after cost was insufficient.

---

## Current status

Baseline gates restored and Docker rebuilt/redeployed. Live telemetry: Gate5 **0.75**, quality **55**, flat-ML **off**, **0** post-kill executes. Experiment bleed stopped.

---

## Implications

- Do not re-disable ADX for fill-rate without replay EV.  
- Even “correct” breakout shorts at this size/hold need fee-aware TP or fewer round-trips before any admission relax.  
- Resume selectivity / thesis work under restored gates; treat frequency experiments as closed.
