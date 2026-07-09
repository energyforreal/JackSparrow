# Trading Decision Forensics Summary — 2026-07-09

Investigation-only pass over 48h Docker agent logs, Postgres `entry_decisions`, Redis gate state, and opportunity replay. No configuration or code changes were applied to the running system.

## Executive conclusion

The trading pipeline is **operational end-to-end**. Zero trades in the investigation window because **entry permission is never granted**, not because execution is broken.

| Check | Result |
|-------|--------|
| Containers healthy | Yes (all 5 up) |
| Decisions generated (48h log) | 299 `decision_ready_emitted` |
| Risk approvals (48h log) | 0 |
| Fills (48h log) | 0 |
| Dominant rejection | `hold_at_synthesis` (94.65% of handler rejects) |
| Secondary rejection | `v15_adx_trending_filter` (5.35%) |

---

## Phase 1 — Decision forensics

### Handler rejection histogram (48h agent log)

| Reason | Count | % |
|--------|------:|--:|
| `hold_at_synthesis` | 283 | 94.65% |
| `v15_adx_trending_filter` | 16 | 5.35% |

Source: [`rejection_forensics_2026-07-09.json`](rejection_forensics_2026-07-09.json)

### Why HOLD at synthesis (48h log)

| Primary cause | Count | % |
|---------------|------:|--:|
| `hypothesis_no_rule_fired` | 283 | 100% |

Top policy reason codes on hold events:

- `hypothesis_no_rule_fired` (566 code hits across payload fields)
- `regime=neutral` (548)
- `fusion_ml_or_thesis_blocked` / `thesis_blocks_ml_adoption` (283 each)
- `thesis_type=flat` (283)

**Semantic note:** `thesis_type=flat` is not the same as `regime=neutral`. `AGENT_POLICY_ADOPT_GATED_ML_WHEN_THESIS_NEUTRAL=true` does **not** apply when `hypothesis_no_rule_fired` is present (by design in `agent_policy_engine.py`).

### Policy / v43 layer (48h log)

| Metric | Value |
|--------|------:|
| v43 prediction cycles | 320 |
| Policy signals emitted | HOLD 283, SHORT 31, LONG 6 |
| v43 gates passed (tag) | short 163, long 157 |
| Latest collapse rate | 99.48% |
| Latest `signals_raw` | 2316 |
| Latest `trades_executed` (v43 counter) | 12 |

### Counter reconciliation

| Source | Trades / counter | Last activity |
|--------|------------------|---------------|
| Postgres `trades` (EXECUTED) | 21 | 2026-06-04 |
| Redis `gate_state:BTCUSD` | `trades_executed` 12 | `signals_raw` 2316 |
| Agent log (latest v43) | 12 | collapse 99.48% |
| **Gap DB − v43** | **9** | Pre-v43 or fills without `v43_closed_bar_index` |

### Execution path sanity

`reconcile_risk_approvals.py`: **0** risk approvals in 48h log — no orphan approvals.

`analyze_agent_logs.py`: 299 decision cycles; 0 risk approved; 0 fills.

### All-time `entry_decisions` (Postgres)

| Reject reason | Count | % |
|---------------|------:|--:|
| `hold_at_synthesis` | 2600 | 96.12% |
| `risk_rejected` | 89 | 3.29% |
| `v15_adx_trending_filter` | 16 | 0.59% |

Source: [`strategy_stat_audit_2026-07-09.json`](strategy_stat_audit_2026-07-09.json)

---

## Phase 2 — Opportunity-cost replay

### `label_entry_decisions.py`

- **Result:** Labeled **0** rows.
- **Cause:** `entry_decisions.metadata` lacks `decision_context.features.close` / price fields for rejected rows.
- **Implication:** DB-based false-negative labeling needs snapshot persistence fix before it can run at scale.

### Log-based opportunity replay (16 non-HOLD rejects)

Script: [`tools/commands/forensics_opportunity_replay.py`](../tools/commands/forensics_opportunity_replay.py)  
Output: [`opportunity_replay_2026-07-09.json`](opportunity_replay_2026-07-09.json)

| Reject reason | n | % would win (12 bars) | Avg forward return % |
|---------------|--:|----------------------:|---------------------:|
| `v15_adx_trending_filter` | 16 | **62.5%** | **+0.0171%** |

Interpretation: ADX filter blocked signals that were **slightly profitable on average** over 12×5m bars in this window — suggests possible over-filtering for breakout-style SHORT/LONG setups, not universal protection.

### Closed-trade baseline (June–July `trade_outcomes`)

- 142 closed trades replayed
- Expectancy: **−$0.85/trade**, win rate **14.1%**, profit factor **0.29**
- Avg MFE $85.77, avg MAE $210.15

Source: [`replay_excursions_2026-07-09.json`](replay_excursions_2026-07-09.json), [`strategy_stat_audit_2026-07-09.json`](strategy_stat_audit_2026-07-09.json)

---

## Success criteria (gates for fix phase)

| Criterion | Met? |
|-----------|------|
| Dominant blocker identified | Yes — `hypothesis_no_rule_fired` → HOLD |
| Opportunity cost quantified | Yes — ADX rejects 62.5% would-win |
| Counters reconciled | Yes — DB 21 vs v43 12 explained |
| No infrastructure regressions | Yes — 0 orphan risk approvals |

**Recommendation:** Proceed to a separate **fix-phase plan** (thesis-aware ADX, policy semantics review). Do not disable filters outright.

---

## Artifacts

| File | Description |
|------|-------------|
| [`agent_forensics_2026-07-09.log`](agent_forensics_2026-07-09.log) | 48h raw agent log export |
| [`baseline_export_2026-07-09.json`](baseline_export_2026-07-09.json) | Postgres + Redis snapshot |
| [`rejection_forensics_2026-07-09.json`](rejection_forensics_2026-07-09.json) | Log forensics breakdown |
| [`strategy_stat_audit_2026-07-09.json`](strategy_stat_audit_2026-07-09.json) | DB rejection + expectancy |
| [`opportunity_replay_2026-07-09.json`](opportunity_replay_2026-07-09.json) | Forward replay of non-HOLD rejects |
| [`replay_excursions_2026-07-09.json`](replay_excursions_2026-07-09.json) | Closed-trade MFE/MAE baseline |
| [`forensics_decision_gate_2026-07-09.json`](forensics_decision_gate_2026-07-09.json) | Synthesized recommendations |
| [`analyze_agent_logs_report.txt`](analyze_agent_logs_report.txt) | Pipeline metrics |
| [`reconcile_risk_approvals_report.txt`](reconcile_risk_approvals_report.txt) | Risk approval reconciliation |

## New tooling added (investigation)

- [`tools/commands/forensics_rejection_breakdown.py`](../tools/commands/forensics_rejection_breakdown.py) — Parses wrapped Docker logs; hold-cause and reject histograms.
- [`tools/commands/forensics_opportunity_replay.py`](../tools/commands/forensics_opportunity_replay.py) — Forward replay for non-HOLD log rejects when DB labels lack price metadata.
