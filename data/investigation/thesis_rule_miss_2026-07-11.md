# Thesis Rule Miss Diagnostic Memo — 2026-07-11

**Sources:** [`thesis_rule_miss_2026-07-11.json`](thesis_rule_miss_2026-07-11.json), [`thesis_rule_miss_2026-07-11.md`](thesis_rule_miss_2026-07-11.md), 168h telemetry

---

## Executive summary

Among **1573 B4 cycles** (ML gates passed, flat thesis, policy HOLD) in the 7d window:

| Rank | Testable hypothesis | Evidence | Miss rate |
|------|---------------------|----------|----------:|
| H1 | Breakout rules blocked by **`h_trend <= 0`** in neutral regime | Nearest blocker 1489/1489 neutral B4 | **100%** |
| H2 | Breakout ADX/DI/vol trifecta also fails on every cycle | All four breakout gates fail per cycle | 100% |
| H3 | Trend continuation blocked by h1/hurst when breakout fails | Secondary blockers present | ~100% |
| H4 | `regime=neutral` mislabels mild drift bars | h_trend at 0 in telemetry defaults | **Plausible — needs log feature join** |
| H5 | Mean reversion relevant in ranging only | 84 B4 in ranging bucket | 5.3% of total |

**Primary research direction:** H1 + H4 — neutral regime cycles show zero trend feature pressure in available telemetry, blocking all breakout and trend_continuation rules.

---

## Ranked testable hypotheses

### H1 — Zero h_trend blocks breakout (HIGH confidence)

- **Mechanism:** [`agent_thesis_engine.py`](../../agent/core/agent_thesis_engine.py) `_eval_breakout_long` requires `h_trend > 0`
- **Observation:** Nearest miss blocker `breakout:h_trend` on **1489/1489** neutral B4 cycles
- **Test:** Join agent logs for raw `h_trend` / `h1_trend` at decision time; confirm non-zero ML-pass cases exist
- **Prototype:** `AGENT_THESIS_NEUTRAL_MILD_TREND_ENABLED` (default **false**) — fires when `h_trend > 0` and `adx < 22` in neutral

### H2 — Breakout ADX floor unreachable in neutral (MEDIUM confidence)

- **Mechanism:** `adx_14 > 25`, `di_spread > 5`, `vol_regime > 1.1` required simultaneously
- **Observation:** All four gates fail on every diagnosed cycle (blocker_totals 2978 = 2x rules x 2 directions)
- **Test:** Distribution of adx/di/vol on ML-pass cycles from feature store logs
- **Risk:** Lowering ADX globally worsens replay EV — any change must pass 7d+30d replay

### H3 — Regime label noise (MEDIUM confidence)

- **Mechanism:** `regime=neutral` assigned while ML sees directional edge
- **Observation:** 94.6% of B4 in neutral; telemetry often lacks embedded feature values (`adx_14: null` in samples)
- **Test:** Correlate regime classifier output with h_trend distribution; sub-regime branching
- **Action:** Extend `thesis_rule_miss_analysis.py` with `--log` join to v43 feature snapshots

### H4 — Telemetry feature gap (HIGH confidence — data issue)

- **Observation:** B4 telemetry rows rarely include `adx_14`, `h_trend` in `policy_reason_codes` (flat thesis emits no rule codes with values)
- **Impact:** Miss analysis defaults missing features to 0.0, which may **overstate** h_trend blocker frequency
- **Action:** Mandatory log join for Phase 2 engineering decisions

### H5 — Policy relaxation not supported (CONFIRMED)

- 30d replay: all regimes negative EV for `ml_only`, `ml_adopt_flat`, `no_thesis_veto`
- **Do not** pursue 3A.2 or score-min reduction

---

## Regime stratification

| Regime | B4 count | Nearest rule | Nearest blocker |
|--------|--------:|--------------|---------------|
| neutral | 1489 | breakout:LONG | h_trend |
| ranging | 84 | mean_reversion:LONG | bb_pos_hi |

---

## Recommended next steps

1. Add log-feature join to `thesis_rule_miss_analysis.py` for non-default feature values
2. Shadow-eval `AGENT_THESIS_NEUTRAL_MILD_TREND_ENABLED=true` in isolated replay — **not production**
3. Track DQI `no_rule_fired_rate` component weekly (baseline score: 10.83)
4. Re-run attribution: `python tools/commands/decision_attribution.py attribution --hours 168`

---

## Artifacts

- [`thesis_rule_miss_2026-07-11.json`](thesis_rule_miss_2026-07-11.json)
- [`dqi_2026-07-11.json`](dqi_2026-07-11.json)
- [`calibration_replay_2026-07-11.json`](calibration_replay_2026-07-11.json) — N=12814, ECE=0.0 (replay labels)
- [`tests/unit/test_thesis_rule_miss.py`](../../tests/unit/test_thesis_rule_miss.py)
