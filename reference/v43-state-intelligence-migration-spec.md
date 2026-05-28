# v43 State Intelligence Migration Spec

## Purpose

Define a safe migration path from return-only v43 regression toward market-state
intelligence heads while preserving current runtime compatibility.

This spec is implementation-oriented and maps directly to:

- `feature_store/jacksparrow_v43_train_multihead.py`
- `feature_store/jacksparrow_v43_labels.py`
- `agent/models/v43_pickle_shims.py`
- `agent/core/agent_policy_engine.py`

## 1) State-Head Design (Concrete Labels + Features)

### 1.1 Regime Classifier Head (4-class)

Target classes (`regime_state_t+N`, default `N=3` bars):

- `trending_up`
- `trending_down`
- `ranging`
- `vol_expansion`

Label rules (deterministic baseline):

- `vol_expansion`: `vol_regime > q80(vol_regime rolling 30d)` OR `atr_pct` breakout above rolling q90
- `trending_up`: `adx_14 > 22` and `hurst_60 > 0.55` and `trend_mom > 0`
- `trending_down`: `adx_14 > 22` and `hurst_60 > 0.55` and `trend_mom < 0`
- else `ranging`

Primary feature family:

- Trend/structure: `adx_14`, `di_spread`, `trend_mom`, `trend_conf`, `hurst_60`
- Volatility: `atr_pct`, `vol_regime`, `bb_width`, `sr_compression`
- Multi-timeframe trend: `h_trend`, `h_trend_200`, `h1_trend`, `h1_adx`, `h1_vol_regime`

Model recommendation:

- `LGBMClassifier` with class balancing and probability output.

### 1.2 Volatility Expansion Head (binary)

Target (`vol_expansion_t+N`):

- `1` when realized future volatility over `N` bars exceeds rolling baseline by threshold.
- `0` otherwise.

Suggested definition:

- `future_realized_vol_N > 1.25 * rolling_median_realized_vol_200`

Primary feature family:

- `atr_pct`, `vol_regime`, `bb_width`, `funding_mom`, `funding_rate_roc`, `oi_acceleration`.

Model recommendation:

- `LGBMClassifier` (binary), calibrated probability.

### 1.3 Trade-Quality Head (binary)

Target (`setup_quality_t+N`):

- Built from triple-barrier outcome (`TP first` vs `SL first/timeout`).

Input source:

- Existing helper in `feature_store/jacksparrow_v43_labels.py`:
  - `build_triple_barrier_labels(...)`

Model recommendation:

- `LGBMClassifier` for `p_setup_quality`.

## 2) Hybrid Inference Contract (No Breaking Rewrite)

Keep current return regressor outputs for gate-5 compatibility, add state scores:

- `expected_return` (existing regressor output)
- `p_regime_favorable` (new classifier)
- `p_vol_expansion` (new classifier)
- `p_setup_quality` (new classifier)
- `uncertainty_score` (optional: e.g., entropy or disagreement across heads)

### 2.1 Runtime Decision Contract

Candidate long/short entry must satisfy:

1. Existing v43 gates (threshold + gate-5 edge/cost)
1. `p_regime_favorable >= regime_min` (default 0.60)
1. `p_setup_quality >= quality_min` (default 0.60)
1. If `p_vol_expansion < vol_min` (default 0.50), reduce size or hold
1. If `uncertainty_score > uncertainty_max`, force hold

### 2.2 Policy Fusion Rules (agent_policy_engine)

Apply within `ml_and_thesis` mode:

- Thesis must agree on direction (existing behavior).
- New state heads act as additional ML confidence gates before final adopt.
- Neutral thesis + gated ML adoption remains allowed only when state scores pass minima.

## 3) Run Checklist (Decision-Quality KPIs)

Track these per run in addition to export corr:

1. **Selectivity**

   - Raw candidate rate
   - Gate-5 approved candidate rate
   - Final adopted trade rate

1. **Quality**

   - Net-positive hit rate by horizon (post-cost)
   - Mean net return per executed candidate
   - Profit factor proxy

1. **Risk**

   - Max drawdown proxy
   - Collapse rate / reject reasons distribution
   - HOLD rate in chop/low-confidence regimes

1. **Signal Health**

   - `validation_corr` and `validation_corr_gross`
   - `prediction_std / target_std` ratio
   - Calibrator fallback flags

## 4) Acceptance Gates For Migration

A migration step is accepted only if:

- No regression in export-gate distance for scalp head.
- Decision-quality KPIs improve on at least two horizons.
- Drawdown proxy does not worsen materially.
- No calibrator fallback for target execution horizon.

## 5) Implementation Order

1. Run-10 stabilization (`V43_USE_META_STACK=true`, strict OI + ticker CSV)
1. Add regime and vol-expansion heads (training + metadata)
1. Add trade-quality head (triple-barrier classifier)
1. Wire hybrid fusion rules in policy layer
1. Promote only if acceptance gates pass
