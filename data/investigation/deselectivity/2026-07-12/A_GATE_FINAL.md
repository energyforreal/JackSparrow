# Phase A gate — FINAL artifact (window still open)

**Evaluated:** 2026-07-12 ~T+3h (calendar ahead of scheduled T+48h = **2026-07-14 ~10:21 UTC**)  
**Decision:** **CONTINUE** — neither promote to production nor rollback Phase A  
**Production / live-capital flip:** **NOT AUTHORIZED** (historical backtest ≠ clearance; live EV still deferred)

This file is the living gate record. **Re-open and update at true T+48h / T+72h** with economic rolling + fills; until then promote criteria that need realized EV stay **DEFERRED**.

## Kill criteria

| Criterion | Status (T+3h) |
|-----------|---------------|
| Agent unhealthy | **PASS** (healthy after recreate) |
| WS error loop | **PASS** |
| Risk veto spike >15% | **PASS** (0) |
| G1 collapse >15% w/o thesis benefit | **PASS / watch** |
| Unexplained handler failure | **PASS** |

## Promote criteria (all required for longer testnet shadow; production still needs full stack)

| Criterion | Status (T+3h) |
|-----------|---------------|
| Replay EV ≥ baseline | **DEFERRED** (run at T+48h without `--skip-rolling`) |
| Testnet EV ≥ baseline | **DEFERRED** (0 fills; all thesis fires held) |
| DD ≤ tolerance | **DEFERRED** |
| Trend fire ≥2× or ≥5/24h | **PASS (rate)** — funnel `fires/24h≈128` on ~2.8h window ([`funnel_post_a.json`](funnel_post_a.json)); reconfirm on full 24h+ |
| Neg controls stable | **OK so far** |
| Ops healthy | **PASS** (`hurst_v2=true`, `TLE_LOG_ONLY=false`) |

## Evidence cited

- [`scorecard_day1.md`](scorecard_day1.md) — layered funnel  
- [`funnel_post_a.md`](funnel_post_a.md) — 15 thesis fires, 15 quality_below, 15 Gate5 fail, 15 HOLD-after-fire  
- [`../../hurst_v2_historical_backtest_conclusion_2026-07-12.md`](../../hurst_v2_historical_backtest_conclusion_2026-07-12.md) — directional EV promising, not clearance  

## Action

1. Keep `AGENT_THESIS_USE_HURST_V2=true` on **testnet only**.  
2. Daily: `phase3_daily_forensics.py --workstream hurst_v2 --skip-rolling` + funnel scorecard.  
3. At **T+48h (2026-07-14 ~10:21 UTC)**: re-run forensics **with** rolling/economic; rewrite this file’s promote/EV rows; CONTINUE to T+72h or rollback.  
4. **Do not** lower quality floor / Gate5 ratio; **do not** enable mild_trend / ADX 3B / flat-hyp ML.

## Rollback trigger

Kill criteria trip, or final-window live EV clearly worse than baseline → set `AGENT_THESIS_USE_HURST_V2=false` and recreate agent per [`RUNBOOK.md`](RUNBOOK.md).
