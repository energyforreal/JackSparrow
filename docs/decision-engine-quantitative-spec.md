# JackSparrow Decision Engine — Quantitative Specification

Canonical mathematical and architectural reference for the v43 / IC decision pipeline.
Consolidates forensic analysis (v1), engineering review (v2), latent-variable spec (v3),
and validation methodology (v4).

**Authority:** `PolicyVerdict.signal` on `DECISION_READY` — not reasoning text.

**Related (operational detail):**
- [Entry quality and lifecycle](entry-quality-and-lifecycle.md)
- [Logic and reasoning](05-logic-reasoning.md)
- [Signal recovery runbook](signal_recovery_runbook.md)
- [ML lifecycle](JackSparrow_Combined_Architecture_Report.md) (training only)

---

## 1. Pipeline overview

```text
CandleClosed → Features → Thesis/Hypothesis → IC (synthetic ER)
  → Gates 1–5 → Entry quality / trade_score → Reasoning (advisory)
  → Policy fusion → Conviction → Portfolio guard → DECISION_READY
  → Trading handler → Risk → Execution
```

Default fusion mode: `ml_or_thesis`. IC path uses **rule-based** intelligence (`RuleBasedIntelligenceNode`), not pickle ML.

---

## 2. Latent variables (target spec)

### ε — Net edge

**Target:** \(\varepsilon^* = \mathbb{E}[\Delta p \mid \mathbf{x}, d] - c_{\text{rt}}\)

**Current proxy (IC path):** \(\varepsilon_{\text{proxy}} = \text{ER}_{\text{synthetic}} - \tau\)

ER is synthesized from thesis/hypothesis (`ic_context_builder.py`), **not** calibrated \(\mathbb{E}[\Delta p]\).
Telemetry records `expected_return_is_synthetic=true` when applicable.

### κ — Directional confidence

**Target:** \(\kappa = P(\text{direction profitable within horizon} \mid \mathbf{x})\) under frozen policy \(\pi_0\).

**Current:** `model_confidence` (ML) or thesis `confidence` (policy). Handler uses calibrated display confidence separately.

**Calibration:** Fit Platt / isotonic / beta on labeled outcomes. Report Brier, ECE, AUC. See `tools/commands/fit_calibrator.py`.

### q — Tradeability quality (soft, continuous)

Weighted sum of regime fit, trend stability, freshness, position context, microstructure penalties, economic soft score.
**Excludes** hard vetoes (see §3).

### A — Agreement

Cross-source directional consensus (thesis, ML gated, MTF, horizon). Default composite in `agent/core/latent_scoring.py`.

### Ranking score

\(S = \sigma(\varepsilon_{\text{proxy}}/\varepsilon_0) \cdot \kappa \cdot q \cdot A\) (shadow mode only until validated).

---

## 3. Quality (Q) vs constraints (C)

| In Q (soft) | In C (hard veto) |
|-------------|------------------|
| regime_fit, trend_stability, freshness | `liquidity_ok` false |
| position_context penalties | `has_open_position` |
| microstructure spread penalty | Gate 1–5 fail |
| economic soft (edge ratio) | entry_quality policy veto |
| | conviction < floor |
| | portfolio_guard block |
| | handler confidence / risk |

**Rule:** \(\bigwedge C_i = \text{PASS}\) required before entry; \(q\) modulates ranking and size only.

---

## 4. Shared latent factor Z (conceptual)

Z is **not computed in production**. It denotes that `{ADX, ATR, chop, vol_regime}` jointly drive thesis, trade_score, conviction, and gates.
Use Z buckets in attribution (`decision_attribution.py latent-buckets`).

---

## 5. Policy-dependent labels (frozen π₀)

Labels for calibration depend on exit policy. Snapshot at entry:

```json
{
  "horizon_bars": "exec_bars",
  "stop_loss_pct": "settings",
  "take_profit_pct": "settings",
  "trade_lifecycle_enabled": "bool",
  "round_trip_cost": "round_trip_cost_pct()"
}
```

Primary label: \(y = \mathbb{1}[\text{signed\_return\_at\_H} > c_{\text{rt}}]\).  
Recalibrate when \(\pi_0\) changes.

---

## 6. Metric dependency (summary)

Features → market structure Z → parallel paths:

- **Thesis:** rules → hypothesis margin → aggregate_confidence → ER synthetic
- **ML:** ER → Gate 1 → Gates 2–5 → final_long/short → model_confidence
- **Quality:** 8 dimensions → trade_score
- **Evidence:** ml_edge, legacy_trade_score_norm → conviction
- **Policy:** fusion → policy_confidence → entry_quality veto → sizing

Duplicate pathways: edge in Gate 5, ml dimension, ml_edge evidence; confidence in policy, conviction, calibrated display.

---

## 7. Telemetry schema (v3)

See [Logging — decision telemetry](12-logging.md#decision-telemetry-v3). Fields: `latent`, `gates`, `scores`, `signals`, `constraints`, `terminal_cause`, `bar_index`, `policy_snapshot`.

---

## 8. Validation roadmap

| Phase | Tool | Output |
|-------|------|--------|
| Attribution | `decision_attribution.py` | `attribution_report.json` |
| Replay Pareto | `threshold_replay.py` | `pareto_frontier.json` |
| Calibration | `build_calibration_dataset.py`, `fit_calibrator.py` | ECE, Brier, reliability |
| Ablation | `metric_ablation.py` | `ablation_report.md` |
| Shadow | `LATENT_SHADOW_MODE`, `shadow_eval.py` | counterfactual PnL |

**Gate:** No policy refactor until ablation + shadow justify changes.

---

## 9. Key thresholds (defaults)

| Setting | Default |
|---------|---------|
| `hypothesis_min_margin` | 0.03 |
| `entry_quality_min_score` | 55 |
| `conviction_entry_floor` | 0.35 |
| `jacksparrow_v43_min_edge_cost_ratio` | 0.75 |
| `agent_policy_mode` | ml_or_thesis |

---

## 10. Code anchors

| Component | Path |
|-----------|------|
| Policy fusion | `agent/core/agent_policy_engine.py` |
| Entry quality | `agent/core/entry_quality.py` |
| Conviction | `agent/core/conviction.py` |
| Gates | `agent/core/v43_signal_gates.py` |
| Hypothesis | `agent/core/hypothesis_aggregator.py` |
| Telemetry | `agent/core/signal_recovery_telemetry.py` |
| Latent shadow | `agent/core/latent_scoring.py` |
| Orchestrator | `agent/core/mcp_orchestrator.py` |
