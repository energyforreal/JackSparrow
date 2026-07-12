# h_trend Blocker Diagnosis — 2026-07-12

**Status:** Research finding (no production change)  
**Evidence:** `decision_evidence/2026-07-12/` (N_high_confidence=137, sweep_gate=PASS)  
**Companion:** `thesis_rule_miss_2026-07-12.md`, `hurst_distribution_2026-07-12.md`, `threshold_sweep_2026-07-12.md`

---

## Headline

The threshold-sweep / nearest-miss ranking that named **`h_trend`** as the dominant blocker is partly a **diagnostic artifact**. The real structural blocker for trend continuation on this window is **`hurst_60 ≈ 0`**.

---

## Why nearest-miss overstated h_trend

| Layer | `h_trend` / `h1_trend` gate |
|-------|------------------------------|
| Live rule (`_eval_trend_continuation_long`) | `h > 0` and `h1 > 0` |
| Miss diagnostic (`diagnose_rule_miss`) | gap vs synthetic threshold **0.001** |

Sample nearest miss: `value=0.0006`, `threshold=0.001`, `gap=0.0004` — this would **pass** the live `h > 0` check, but ranks as nearest miss because the gap to 0.001 is tiny.

**B4 h_trend distribution (N=137):**

| Bucket | Count | % |
|--------|------:|--:|
| `h_trend <= 0` | 34 | 24.8 |
| `0 < h_trend < 0.001` | 103 | 75.2 |
| mean / median | 0.000189 / 0.000587 | |

`h1_trend` is fine: **0%** ≤ 0; mean ≈ 0.003.

---

## Corrected trend_continuation counterfactual

Holding live gates (`h1>0`, `h>0`, RSI∈[40,65], `hurst≥0.52`):

| Outcome | Count |
|---------|------:|
| Passes all trend gates | **0** |
| Blocked only by `h_trend` | **0** |
| Blocked only by `hurst_60` | **49** |
| Blocked only by RSI | 0 |
| Blocked by multiple gates | 88 |

**Hurst distribution (high-confidence B4):**

| Bucket | Count |
|--------|------:|
| exactly 0 | **132 (96.4%)** |
| 0–0.3 | 5 |
| ≥0.52 | **0** |

`hurst_60=0.0` is a computed clip (not a missing-data fill of 0.5). At `AGENT_THESIS_TREND_HURST_MIN=0.52`, trend continuation cannot fire on this window.

---

## Breakout picture (same window)

| Check | Result |
|-------|--------|
| `h_trend > 0` | 103/137 (75%) |
| ADX < 25 | 21.9% |
| Vol regime < 1.1 | **68.6%** |
| All baseline breakout gates pass | **0** |

Nearest-rule mix: trend_continuation 100, breakout 34, mean_reversion 3. Regime: **neutral 134 / ranging 3**.

---

## Implications for governance

1. **Do not relax `h_trend` thresholds** based on nearest-miss alone — most “near misses” already satisfy `h > 0`.
2. **Do not promote `neutral_mild_trend`** on this evidence (replay EV −0.23%, N=5).
3. **Primary research target:** why `hurst_60` is clipped to 0 on ~96% of B4 cycles — resolved in [`hurst_scale_diagnosis_2026-07-12.md`](hurst_scale_diagnosis_2026-07-12.md) (variance-ratio scale bug vs classic Hurst). Next: versioned estimator or retuned thresholds via replay only.
4. **Secondary:** breakout `vol_regime` floor (1.1) excludes ~69% of B4; fire-rate grid shows lift only when vol is relaxed — still needs EV validation before any flag change.
5. **Diagnostics fix (done):** `diagnose_rule_miss` now aligns `h_trend` / `h1_trend` with live `> 0` gates; miss analysis ranks nearest on the ML side only.

---

## Artifacts

- `thesis_rule_miss_2026-07-12.json` / `.md`
- `hurst_distribution_2026-07-12.json` / `.md`
- `threshold_sweep_2026-07-12.json` / `.md`
- `counterfactual_replay_2026-07-12.md` (policy still `hold_baseline_policy`)
