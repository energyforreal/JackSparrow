# Evidence Pipeline Status — 2026-07-11

**Status:** Phase 6 live; sample-size gate open; baseline policy unchanged  
**Baseline:** `0503847` / `hold_baseline_policy`

---

## Implementation summary

| Item | Status | Notes |
|------|--------|-------|
| Phase 6 telemetry hardening | **Live** | `core_features` → `extra["features"]` on `v43_prediction_complete` and `decision_ready_emitted` |
| `neutral_mild_trend` replay scenario | **Live** | Added to `counterfactual_replay.py` SCENARIOS; 10 unit tests |
| Weekly 168h log export | **Live** | `phase3_daily_forensics.py --weekly` now exports `--since 168h` |
| Agent redeploy | **Done** | `docker compose up -d --build --force-recreate agent` |
| Task Scheduler | **Registered** | `JackSparrow-DailyValidation` (daily 11:30 local / 06:00 UTC), `JackSparrow-WeeklyValidation` (Sundays) |
| Sample-size gate (`N≥100`) | **FAIL** | `N_high_confidence=26` (baseline window); accumulation ongoing |
| Production policy change | **None** | `AGENT_THESIS_NEUTRAL_MILD_TREND_ENABLED` remains `false` |

---

## Phase 6 verification

Post-deploy telemetry row (2026-07-11T16:25:48Z) carries all eight core thesis features in `extra.features`:

- `adx_14`, `di_spread`, `vol_regime`, `hurst_60`, `h_trend`, `h1_trend`, `rsi_14`, `bb_pos`

Provenance classification: `telemetry_embedded` (medium confidence) per [`decision_observability_program_2026-07-11.md`](decision_observability_program_2026-07-11.md).

---

## Sample-size gate

| Source | `high_confidence` | `sweep_gate` |
|--------|------------------:|--------------|
| Baseline log ([`agent_baseline_2026-07-11.log`](agent_baseline_2026-07-11.log)) | 26 | FAIL |
| Post-redeploy weekly export | 1 | FAIL |

**Why N dropped after redeploy:** `docker logs --since 168h` only returns logs since container creation. Hold-event history resets on `--force-recreate`. Expect N to climb back toward ≥100 over **~2–4 days** of continuous agent uptime via scheduled weekly runs.

**Gate check command:**

```powershell
Get-Content data/investigation/decision_evidence/<date>/coverage.json | Select-String high_confidence,sweep_gate
```

---

## Replay evaluation (168h, economic)

**Artifact:** [`counterfactual_replay_2026-07-11.json`](counterfactual_replay_2026-07-11.json)

| Scenario | Trades | EV % | Notes |
|----------|-------:|-----:|-------|
| `current` | 198 | -0.19 | Baseline |
| `ml_adopt_flat` | 0 | 0.0 | No flat-hypothesis candidates in window |
| `ml_only` | 2098 | -0.20 | Negative EV |
| `no_adx` | 203 | -0.19 | Negative EV |
| `no_thesis_veto` | 2098 | -0.20 | Negative EV |
| **`neutral_mild_trend`** | **0** | **0.0** | Expected: pre-Phase-6 rows lack `extra.features`; only 1 post-deploy cycle at eval time |

**Promotion recommendation:** `hold_baseline_policy` (unchanged).

`neutral_mild_trend` EV becomes measurable once ≥48h of post-Phase-6 telemetry accumulates. Re-run:

```powershell
python tools/commands/counterfactual_replay.py --hours 168 --economic
```

---

## Threshold sweep

**Status:** Skipped — `sweep_gate=FAIL; need N>=100`

Will auto-run when weekly evidence assembly reports `sweep_gate: PASS`.

---

## DQI snapshot

Weekly bundle DQI composite: **68.34** ([`dqi_2026-07-11.json`](dqi_2026-07-11.json))  
Prior baseline: 50.52 — track week-over-week trend, not absolute level.

---

## Governance decision

Per [`investigation_closure_2026-07-11.md`](investigation_closure_2026-07-11.md), **no production policy or thesis flag changes** are justified:

1. Rolling replay (7d/30d) shows negative EV for relaxation scenarios
2. `neutral_mild_trend` not yet evaluable (0 trades; insufficient post-Phase-6 feature coverage)
3. Sample-size gate not passed for threshold calibration
4. Jul-11 window remains essentially neutral-only — regime-stratified validation pending

**Explicitly off the table** (unchanged):

- `AGENT_POLICY_ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS`
- Lowering `AGENT_TRADE_SCORE_MIN`
- Disabling ADX filter
- Global thesis gating relaxation

**Hygiene:** Verify `TRADE_LIFECYCLE_LOG_ONLY=false` in `.env` before first production execution.

---

## Next actions (automated + manual)

| Cadence | Action |
|---------|--------|
| Daily | `JackSparrow-DailyValidation` task (or `scripts/daily_validation.ps1`) |
| Weekly | `JackSparrow-WeeklyValidation` task — monitor `coverage.json` for `sweep_gate: PASS` |
| At gate pass | Re-run `thesis_threshold_sweep.py`; review binding blockers |
| After 48h+ post-deploy | Re-run `counterfactual_replay.py`; assess `neutral_mild_trend` EV |
| On trending window | Re-run replay + sweep for regime-stratified comparison |

---

## Artifacts

- [`decision_evidence/2026-07-11-baseline/`](decision_evidence/2026-07-11-baseline/) — N=26 enriched evidence
- [`counterfactual_replay_2026-07-11.json`](counterfactual_replay_2026-07-11.json)
- [`counterfactual_replay_2026-07-11.md`](counterfactual_replay_2026-07-11.md)
- [`rolling/2026-07-11/`](rolling/2026-07-11/) — rolling validation with `neutral_mild_trend` row
- Unit tests: 24 passed (`test_signal_recovery_telemetry_core_features`, `test_counterfactual_replay_neutral_mild_trend`, `test_decision_evidence`)
