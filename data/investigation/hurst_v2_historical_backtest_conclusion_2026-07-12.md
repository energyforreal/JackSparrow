# Hurst v2 Historical Backtest Conclusion — 2026-07-12

**Source:** [`hurst_v2_backtest_60d.md`](hurst_v2_backtest_60d.md) / [`hurst_v2_backtest_60d.json`](hurst_v2_backtest_60d.json)  
**Baseline reference:** `0503847`  
**Task 2 telemetry check:** latest rows carry all 8 core features + `hurst_60_v2` (verified 2026-07-12 ~12:45Z)

---

## Verdict

**CONTINUE Phase A testnet shadow — do not promote to production / live-capital.**

Historical EV for `hurst_v2` is **slightly positive combined** on 60d BTCUSD 5m (`EV_combined = +0.0254%`, `n_fires = 2548`), so the path is **not clearly negative**. It is **promising enough to keep the live dual-write / Phase A flag on testnet**, but **not** sufficient to flip production `.env` for live capital.

---

## Key numbers (60d, horizon=12 bars ≈ 1h, no costs)

| Arm | n_fires | fire% | EV long% | EV short% | EV combined% |
|-----|--------:|------:|---------:|----------:|-------------:|
| legacy | 1615 | 9.1 | +0.1535 | −0.015 | **+0.0608** |
| hurst_v2 | 2548 | 14.4 | +0.0853 | −0.0183 | **+0.0254** |

Hurst scale check: legacy `hurst_60` ≥0.52 on **18/17732** bars; `hurst_60_v2` ≥0.52 on **4175/17732** — confirms the scale bug diagnosis and that v2 unblocks the gate structurally.

Regime mix of v2 fires: neutral 2129 / crisis 381 / ranging 38 — **dominated by a single regime**; does not satisfy a strong multi-regime promotion claim alone.

---

## Branch taken (per outstanding-work Task 4)

| Outcome class | This run |
|---------------|----------|
| Clearly negative across regimes | **No** |
| Positive / promising | **Yes** (combined EV ≥ 0, n ≫ 30) |

**Actions:**

1. Keep `AGENT_THESIS_USE_HURST_V2=true` on **testnet Phase A only** through T+48h / T+72h (`A_GATE_FINAL.md` still due ~2026-07-14).
2. Continue weekly evidence assembly (Task 1 fixed: telemetry-primary B4, `N=289` PASS).
3. Track live `hurst_60_v2` thesis fires toward n≥30 with non-negative realized EV.
4. **Do not** set production/live-capital `AGENT_THESIS_USE_HURST_V2=true` without 7d+30d economic replay + shadow + explicit approval vs `0503847`.
5. Note: legacy arm EV was *higher* than v2 on this window — v2 buys fire rate at a cost of EV dilution; watch Phase A realized EV carefully for kill/rollback.

---

## Explicit non-clearance

This historical backtest is a **directional read only** (no slippage, funding, or walk-forward). It **does not** clear the Context promotion gate.
