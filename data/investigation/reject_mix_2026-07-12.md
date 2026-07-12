# Reject Mix Snapshot — 2026-07-12

**Sources:** `agent.log` + `agent.log.1`, `rejection_forensics_2026-07-12.json`, Redis `gate_state:BTCUSD`

## Handler rejects
| Reason | Count | Share |
|--------|------:|------:|
| hold_at_synthesis | 46 | 90.2% |
| v15_adx_trending_filter | 5 | 9.8% |

## Hold-at-synthesis primary cause
- **hypothesis_no_rule_fired**: 46/46 (100%) — Phase 3A.1 bucket **B4**; gate decision remains `proceed_3a2` (testnet-only for 3A.2 flag)

## ADX secondary path
Last non-HOLD cascades were all SHORT breakouts blocked by `v15_adx_trending_filter` (ADX 46–54, score ~61.5). Thesis-aware ADX (3B) stays **off** until economic replay gate passes.

## Redis gate_state hygiene
- Snapshot saved to `redis_gate_state_BTCUSD.txt` (TTL ~24h rolling)
- Counters show high cumulative `signals_raw` and collapse ~0.996; last `trades_by_date` entries through 2026-07-08
- **No reset performed** — preserving counters for ongoing forensics; reset would quiet collapse alerts but would not widen gate-1 admission

## Implication
Dominant zero-trade driver is thesis non-fire (Hurst/vol), not ADX. Next: Hurst v2 / vol_regime research path (Track B2).
