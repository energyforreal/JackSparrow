# Early read — Phase A (provisional)

**Elapsed since agent start:** ~37 minutes (plan target T+6h; this is an **early** spot check)  
**Agent started (UTC):** 2026-07-12T10:21:37Z  
**Read at (UTC):** 2026-07-12T10:58Z approx

## Ops / flags

| Check | Result |
|-------|--------|
| `AGENT_THESIS_USE_HURST_V2` | **True** |
| Flat-hyp ML / ADX thesis-aware / mild-trend | **False** |
| Agent / backend health | healthy / OBSERVING / up |
| WS `outbound_agent_command_ws_send_exception` | 1 event at **10:21:30Z** (before agent healthy) — logged as **warning**, `clean_close=True` (teardown path). **No spam loop.** Not a kill. |

## Dual-write / thesis

| Check | Result |
|-------|--------|
| Post-A telemetry dual-write | 2/3 feature rows have `hurst_60` + `hurst_60_v2` |
| Sample | h≈0.11, v2≈0.61 |
| `hurst_60_v2` in reason_codes | 0 hits yet (few cycles) |
| Trend fire approx | 1 weak signal in short window |

## Reject mix (post-A only, N small)

| Reason | Count |
|--------|------:|
| hold_at_synthesis | 1 |
| gates_passed_short | 1 |
| v15_adx_trending_filter | 0 |
| risk-veto-like | 0 |

**vs baseline:** too few events for ±10pp tests. No kill criteria tripped.

## Negative-control freeze (day-0 post-A hour)

Use subsequent days against these provisional rates once N≥20 cycles:

| Control | Early post-A |
|---------|----------------|
| G1 / gates_passed tags | 1 in window |
| Risk veto-like | 0 |
| Handler ADX on non-HOLD | 0 |

## Verdict

- **Continue Phase A** — no kill.
- Re-run a full early-read style check at **T+6h** (~2026-07-12T16:21Z) when more candles exist.
- Do not promote/rollback on this sample.
