# Phase 3 Design Decisions

Generated: 2026-07-09

## 3A.1 — Hypothesis investigation (complete)

**Artifact:** `data/investigation/hypothesis_breakdown_2026-07-09.json`  
**Gate doc:** `data/investigation/phase3_gate_decision_3a1.md`

| Bucket | Count | % |
|--------|------:|--:|
| B4 (v43 gates passed, policy HOLD, flat hypothesis) | 283 | 100% |
| B1/B2/B3/A | 0 | 0% |

**Gate decision:** `proceed_3a2` — B4 share exceeds 30% threshold.

**Interpretation:** All `hold_at_synthesis` events in the 48h window are policy blocks on flat hypothesis while v43 gates passed. Shadow pipeline agrees with HOLD (100%) but does not model gated ML adoption — consistent with architectural policy block, not upstream selector zeroing.

## 3A.2 — Policy semantics (implemented, testnet pending)

**Flag:** `AGENT_POLICY_ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS=false` (default off)

**Behavior (Option A — narrow):** When flag is `true`, `_thesis_blocks_gated_ml_adoption()` allows gated ML if:

- `hypothesis_no_rule_fired` / flat hypothesis codes present
- `ml_validation.final_long` or `final_short` is true
- `trade_score >= AGENT_TRADE_SCORE_MIN`
- Never bypasses crisis/veto/open-position/ATR blocks

**Testnet protocol:** Enable only this flag for 48–72h. Keep `V15_ADX_REGIME_FILTER_ENABLED` unchanged.

**Promotion criteria:**

| Metric | Baseline | Target |
|--------|----------|--------|
| risk_approved_count | 0 | > 0 when v43 gates pass |
| hold_at_synthesis rate | 94.7% | Meaningful decrease |
| Net expectancy (new fills) | -$0.85 | Not worse than baseline |

**Rollback:** Set flag `false`; no other changes.

## Economic replay — ADX cohort (complete)

**Artifact:** `data/investigation/economic_replay_2026-07-09.json`

| Metric | Value |
|--------|-------|
| ADX reject cohort n | 16 |
| Avg net return % | -0.2504 |
| Avg gross return % | -0.0505 |
| Net win rate | 18.75% |
| Promotion gate | **BLOCKED** (n < 30, net expectancy negative) |

**Decision:** Do **not** promote 3B to testnet until sample expands and net expectancy turns positive.

## 3B — Thesis-aware ADX (implemented, testnet blocked)

**Flag:** `V15_ADX_THESIS_AWARE_ENABLED=false` (default off)

**Behavior:** When enabled, skip high-ADX cap (`v15_adx_ranging_max`) for `breakout` and `trend_continuation` thesis types; keep strict cap for `mean_reversion`, `flat`, and unknown.

**Blocked until:** Economic replay promotion gate passes (n ≥ 30, positive net expectancy).

## 3C — Observability (complete)

**Changes:**

- `build_reject_snapshot()` / `_enrich_reject_forensics()` persist price, ATR, ADX, policy, ML, hypothesis, thesis_type, correlation_id
- `trading_handler` diagnostics include `policy_verdict`, `trade_score`, `correlation_id`
- `label_entry_decisions.reference_price_from_metadata()` falls back to `current_price`

## Experiment matrix

| Run | Active flags | Status |
|-----|--------------|--------|
| Baseline | — | Complete |
| 3A.1 | telemetry only | Complete |
| 3A.2 | `AGENT_POLICY_ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS=true` | Ready for testnet |
| 3B | `V15_ADX_THESIS_AWARE_ENABLED=true` | Blocked by economic replay |
| 3C | snapshot enrichment | Shipped |

## Daily forensics during experiments

```powershell
python tools/commands/phase3_daily_forensics.py --workstream 3a2
```

Or manually:

```powershell
docker logs jacksparrow-agent --since 24h > data/investigation/agent_exp_3a2_<date>.log
python tools/commands/forensics_rejection_breakdown.py <log>
python tools/commands/forensics_hypothesis_breakdown.py <log>
python tools/commands/reconcile_risk_approvals.py <log>
```
