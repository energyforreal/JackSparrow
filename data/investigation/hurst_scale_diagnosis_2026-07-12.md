# Hurst Scale Diagnosis — 2026-07-12

**Status:** Feature-science finding (no production threshold / formula change)  
**Related:** [`h_trend_blocker_diagnosis_2026-07-12.md`](h_trend_blocker_diagnosis_2026-07-12.md)

---

## Verdict

Live `hurst_60 ≈ 0` on ~96% of high-confidence B4 rows is the **clip floor** of a **mis-scaled variance-ratio estimator**, not missing data and not classic Hurst≈0 mean-reversion.

Thesis gates at `AGENT_THESIS_TREND_HURST_MIN=0.52` (and regime `hurst > 0.55`) assume a **classic Hurst scale** (RW≈0.5). Under the shipped formula those gates are effectively unreachable on near-RW 5m crypto.

---

## Formula (shipped)

```85:90:feature_store/jacksparrow_v43_mcp_row.py
def _hurst_fast(close: pd.Series, window: int = 60) -> pd.Series:
    log_ret = np.log(close / close.shift(1))
    var1 = log_ret.rolling(window, min_periods=max(2, window // 2)).var()
    var4 = log_ret.rolling(4, min_periods=2).mean().rolling(window, min_periods=max(2, window // 2)).var()
    h = 0.5 + 0.5 * np.log((var4 + 1e-12) / (var1 + 1e-12)) / np.log(4)
    return h.clip(0.0, 1.0).fillna(0.5)
```

| Piece | Behavior |
|-------|----------|
| Window | 60 bars (~5h on 5m) |
| Coarse grain | `rolling(4).mean()` of log returns (**mean**, not sum) |
| Scale claim (legacy notebook) | H≈0.5 RW, >0.55 trend, <0.45 MR |
| Actual RW math | `Var(mean_4)/Var(1)≈1/4` → **H≈0.0** |
| Clip | `clip(0.0, 1.0)` → MR / RW land on **0.0** |
| Missing / warmup | `fillna(0.5)` — **distinct** from live zeros |

---

## Evidence (2026-07-12 B4, N=137)

| Observation | Value |
|-------------|------:|
| `hurst_60 == 0` | 132 (96.4%) |
| `hurst_60 ≥ 0.52` | **0** |
| Trend continuation all-gates pass | **0** |
| Blocked only by hurst (live gates) | 49 |

Interpretation in `thesis_feature_distribution.py` already notes zeros are computed clips, not fillna(0.5).

---

## What not to do yet

| Change | Why blocked |
|--------|-------------|
| Lower `AGENT_THESIS_TREND_HURST_MIN` toward 0.05 | Changes semantics without recalibrated EV; may admit noise |
| Rescale `_hurst_fast` in place | Train/serve + historical features share this definition; needs versioned feature + model retrain plan |
| Enable `neutral_mild_trend` | Separate prototype; replay EV still negative (N=5) |

---

## Diagnostics fix shipped alongside this memo

`diagnose_rule_miss` previously compared `h_trend` / `h1_trend` to a synthetic **0.001** floor, ranking tiny positive drifts as nearest misses and hiding `hurst_60`.

**Fix:** only flag when live sign gates fail (`h <= 0` / `h1 <= 0`), matching `_eval_trend_continuation_long` / breakout.

Re-run: `thesis_rule_miss_analysis.py` on `decision_evidence/2026-07-12/enriched.ndjson` after the fix.

---

## Research options (governance-gated)

1. **Document-only:** treat `hurst_60` as a variance-ratio persistence score on [0,1] with RW≈0; retune thesis/regime thresholds via replay (new feature contract note).
2. **Correct estimator (scaffolded 2026-07-12):** `hurst_60_v2` dual-write via `_hurst_variance_ratio_v2`; thesis reads it only when `AGENT_THESIS_USE_HURST_V2=true`. See [`hurst_v2_scaffold_2026-07-12.md`](hurst_v2_scaffold_2026-07-12.md).
3. **Drop Hurst from thesis gates** until a calibrated substitute exists — only with positive/non-worsening replay EV.

Any production change still requires the closure-doc stack (7d+30d replay, shadow, regime stratification, approval vs `0503847`).

---

## Unit lock

`tests/unit/test_hurst_fast_scale.py` asserts RW synthetic series map near 0 (not 0.5) and warmup fillna is 0.5.
