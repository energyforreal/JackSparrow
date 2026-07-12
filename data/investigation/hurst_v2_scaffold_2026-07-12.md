# hurst_60_v2 Scaffold — 2026-07-12

**Status:** Dual-write live in code; thesis/ML still on legacy `hurst_60`  
**Parent:** [`hurst_scale_diagnosis_2026-07-12.md`](hurst_scale_diagnosis_2026-07-12.md)  
**Flag:** `AGENT_THESIS_USE_HURST_V2=false` (default)

---

## What shipped

| Piece | Behavior |
|-------|----------|
| `_hurst_variance_ratio_v2` | Sum aggregation + `H = 0.5 * log(Var(sum_4)/Var(r))/log(4)` → RW≈0.5 |
| `_hurst_fast` / `hurst_60` | **Frozen** (train/serve + thesis default) |
| `build_v43_feature_matrix(..., for_training=False)` | Adds `hurst_60_v2` column (stripped from ML contract keep-list otherwise) |
| `build_v43_last_row` | Emits `hurst_60_v2` alongside `hurst_60` |
| Telemetry | `RESEARCH_THESIS_FEATURES` embeds `hurst_60_v2` into `extra.features` when present |
| Thesis | Reads `hurst_60_v2` **only** if `AGENT_THESIS_USE_HURST_V2=true` |

---

## Explicit non-goals (this change)

- No change to `V43_CANONICAL_FEATURES` / model metadata
- No change to regime labels that use `hurst_60 > 0.55`
- No production enable of `AGENT_THESIS_USE_HURST_V2`
- No promotion without 7d+30d replay + shadow + approval vs `0503847`

---

## Validation path after agent redeploy

1. Confirm telemetry rows carry both `hurst_60` and `hurst_60_v2` in `extra.features`
2. Offline: compare distributions (legacy clip-at-0 vs v2 near 0.5 on RW-like windows)
3. Counterfactual: thesis trend fire rate / EV with flag on **testnet only**
4. If EV positive under governance stack → document promotion gate; else keep flag off

---

## Unit locks

- `tests/unit/test_hurst_fast_scale.py` — RW→~0 legacy; RW→~0.5 v2
- `tests/unit/test_thesis_rule_miss.py::test_thesis_hurst_v2_flag_reads_v2_feature`
- `tests/unit/test_signal_recovery_telemetry_core_features.py` — research embed

## Validation update (2026-07-12T07:41Z)

- Telemetry dual-write confirmed (121 rows)
- Offline counterfactual: `hurst_v2_vol_counterfactual_2026-07-12.json` / `hurst_v2_vol_counterfactual_2026-07-12.md`
- Production flag still **false**; no vol_regime promotion
