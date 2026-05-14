# JackSparrow v43 — trade execution runbook

Operational guide for tuning v43 entry frequency while keeping rollback discipline (**one environment knob change per deploy window**). Pair with [`.env.example`](../.env.example) and code in [`agent/core/v43_signal_gates.py`](../agent/core/v43_signal_gates.py), [`agent/core/mcp_orchestrator.py`](../agent/core/mcp_orchestrator.py), [`agent/core/config.py`](../agent/core/config.py).

---

## Phase 0 — Baseline and safety

### Required checks (before any tuning)

| Item | Where to verify | Notes |
|------|-----------------|--------|
| `TRADING_MODE` | `.env` / compose | `paper` vs `live` must match intent. |
| `EXCHANGE_BACKEND` | `.env` | `delta_paper_sim` vs `delta_live` aligned with `TRADING_MODE`. |
| Delta cluster | `DELTA_EXCHANGE_BASE_URL`, `WEBSOCKET_URL` | India prod vs testnet must match the same cluster (see `.env.example`). |
| Model bundle | `MODEL_DIR`, `AGENT_MODEL_DIR` | Must contain `metadata_v43.json` and the artifact basename below. |
| v43 artifact | `JACKSPARROW_V43_ARTIFACT_BASENAME` | Default in code: `model_artifact_v43_patched.pkl`. Confirm file exists under `MODEL_DIR`. |
| Threshold patch | Agent startup logs | When using an unpatched artifact, runtime may still apply a patch — watch for `v43_threshold_patch_applied` or related model-load logs in [`jack_sparrow_v43_node.py`](../agent/models/jack_sparrow_v43_node.py). |

### Success metrics (pick 2–3 and record “before” values)

1. **Reject mix**: Share of cycles with `reject` / `reject_tail` = `below_threshold` vs `min_edge_cost` vs `debounce` / `freq_*` / `trending_blocked` (from agent NDJSON). Use [`scripts/analyze_v43_gate_rejects.py`](../scripts/analyze_v43_gate_rejects.py).
2. **Risk bounds**: Max daily trades within `JACKSPARROW_V43_MAX_TRADES_PER_DAY`; max drawdown / portfolio heat within your risk policy.
3. **Latency / health**: Agent healthy; no sustained `delta_client` / candle fetch failures.

### Rollback bounds

Define hard stops before changing config (e.g. “if paper PnL drawdown exceeds X% in 48h, revert last knob”). Default rollback values for code-shipped defaults:

| Variable | Current code default | Conservative rollback |
|----------|----------------------|-------------------------|
| `JACKSPARROW_V43_MIN_EDGE_COST_RATIO` | `0.75` | `1.5` (legacy stricter gate) |
| `JACKSPARROW_V43_TRADE_DEBOUNCE_BARS` | `3` | `6` (~30 min on 5m bars) |
| `JACKSPARROW_V43_BLOCK_TRENDING_ENTRIES` | `true` (unchanged) | keep `true` if whipsaw rises when trialing `false` |

---

## Model promotion gate

Before swapping in a newly exported v43 regression bundle, confirm the notebook
metadata describes the export as a tradable expected-return model:

1. **Embargoed split**: `metadata_v43.json` includes `split.split_method =
   chronological_embargo`, `split.embargo_bars = 120`, and train/validation
   timestamp ranges.
2. **Validation metrics**: `validation_metrics` includes ensemble RMSE, MAE,
   correlation, directional accuracy, validation prediction threshold, long/short
   candidate counts, hit rates, and net returns after the runtime fee/slippage
   assumptions.
3. **Runtime smoke**: `JackSparrowV43Node.predict()` emits `expected_return`,
   `threshold`, `regime`, `uncertainty`, `unc_scale`, and `closed_bar_features`
   for the exported artifact.
4. **Paper first**: run the bundle in paper mode and compare `below_threshold`,
   `min_edge_cost`, debounce/cap, and regime rejects before moving any execution
   knobs.

The v43 model predicts **simple forward return** over the 120-bar horizon. It is
not a probability, so all gate tuning should compare expected-return units to
costs and realized returns.

---

## Phase 1 — Edge vs cost (primary lever)

**Action**: Adjust `JACKSPARROW_V43_MIN_EDGE_COST_RATIO` in steps (e.g. `1.5` → `1.0` → `0.75` → `0.5`). Code default is now **`0.75`**.

**Verify**: Log lines with event **`v43_gate5_rejected`** include `edge_pct`, `lhs` (= expected-return edge over threshold), `rhs` (= ratio × round-trip cost). Expect fewer `min_edge_cost` rejects when lowering the ratio (see [`scripts/analyze_v43_gate_rejects.py`](../scripts/analyze_v43_gate_rejects.py)).

**Rollback**: If edge quality degrades vs Phase 0 metrics, restore the previous ratio only.

---

## Phase 2 — Shorts and debounce

**Shorts** (optional, product + margin): set `JACKSPARROW_V43_SHORT_EXECUTION_ENABLED=true` in `.env` only when symmetric shorts are allowed.

**Debounce**: Code default `JACKSPARROW_V43_TRADE_DEBOUNCE_BARS` is **`3`** (~15 min between entries on 5m cadence). Increase if you see duplicate-like entries; wall-clock debounce in `trading_handler` still applies.

---

## Optional — Near-threshold band (only if `below_threshold` dominates)

If logs show frequent `reject=below_threshold` where `expected_return` is *just* under `threshold`, you can trial a small
epsilon band so downstream gates (debounce/caps/regime/gate5/confidence/risk) still protect execution.

- **Env**: `JACKSPARROW_V43_NEAR_THRESHOLD_EPSILON` (default `0.0` = strict).  
- **Behavior**: when `expected_return > threshold - epsilon`, the v43 path treats it as a raw candidate. If it still fails,
  the reject reason becomes `near_threshold` for easier aggregation.

Start small (e.g. `0.00010` = 1 bp in expected_return units) and roll back if quality degrades.

---

## Phase 3 — Trending regime (higher risk)

**Trial**: Set `JACKSPARROW_V43_BLOCK_TRENDING_ENTRIES=false` to allow entries when the model labels `trending`. Monitor whipsaw and reject mix.

**Rollback**: Set back to `true` if churn increases without benefit.

---

## Phase 4 — Confidence and minimal gates

Prefer Phases 1–3 before lowering **`AI_SIGNAL_MIN_ENTRY_CONFIDENCE`** (default `0.70`).

**Paper-only validation**: `AI_SIGNAL_MINIMAL_ENTRY_GATES=true` bypasses most legacy filters in the trading handler — use **only in paper** to measure raw throughput; not a live risk posture without review. `risk_manager.validate_trade` still runs on every entry. See [Logic & reasoning](05-logic-reasoning.md#trading-handler-default-vs-minimal-ai-entry-gates).

Optional paper override: `PAPER_TRADE_VALIDATION_MODE=true` with `PAPER_TRADE_VALIDATION_MIN_CONFIDENCE` (see `config.py`).

---

## Phase 5 — Observability and discipline

- **Structured events**: `v43_gate5_rejected` (long/short) with numeric diagnostics; existing `mcp_orchestrator_v43_prediction_complete` continues to carry `reject`, `proba`, `thr`.
- **Aggregation**: `python scripts/analyze_v43_gate_rejects.py path/to/agent.log` (or pipe NDJSON stdin).
- **Process**: One knob per deploy; capture 24h of logs before the next change.

---

## Deliverables checklist

- [ ] Phase 0 table filled for your environment.
- [ ] Before/after reject counts from the analyzer script.
- [ ] Runbook version noted in internal change log when defaults drift.
