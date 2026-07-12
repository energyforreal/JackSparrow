# Scorecard day0 — 2026-07-12

**Phase A start (UTC):** 2026-07-12T10:21:37Z  
**Note:** Calendar-day forensics still dominated by **pre-A** hours. Post-A slice is sparse (~1 candle cycle). Numeric promote gates are **not evaluable** yet.

## Full-day reject mix (mostly pre-A)

| Reason | Count | Share | Baseline |
|--------|------:|------:|----------|
| hold_at_synthesis | 47 | 90.4% | 93.9% |
| v15_adx_trending_filter | 5 | 9.6% | 6.1% |

Hold cause: `hypothesis_no_rule_fired` 100% (B4).  
Risk approved / fills (reconcile): **0 / 0**.  
Collapse (v43 latest): ~0.9966 (diagnostic only).

## Post-A slice only (from EARLY_READ)

| Metric | Value | Gate |
|--------|------:|------|
| Trend thesis fires | ~1 | Need ≥5/24h or 2× baseline — **pending** |
| hold_at_synthesis share | 1 event | Need −10pp vs 93.9% — **pending** |
| Fills | 0 | Diagnostic |
| Net EV | n/a | Need ≥ baseline at T+48–72h |
| G1 / gates_passed | 1 | Freeze neg-control |
| Risk veto | 0 | OK |
| Ops | healthy; 1 clean WS warn at recreate | OK — no kill |

## Numeric gate status (day0)

| Gate | Status |
|------|--------|
| Trend fire ≥2× or ≥5/24h | **INSUFFICIENT_DATA** |
| hold share −10pp | **INSUFFICIENT_DATA** |
| EV ≥ baseline | **DEFERRED** to T+48–72h |
| NegCtrl ±15% | **FROZEN** at early post-A rates |
| Kill criteria | **NONE TRIPPED** |

## Commands used

```powershell
python tools/commands/phase3_daily_forensics.py --workstream hurst_v2 --log-out data/investigation/deselectivity/2026-07-12/agent_exp_hurst_v2_2026-07-12.log --skip-docker --skip-rolling
```

Artifacts: `rejection_forensics_day0.json`, `hypothesis_breakdown_day0.json`, `EARLY_READ.md`.
