# JackSparrow Signal Recovery Runbook

Operational steps for the runtime signal recovery plan. Reports are written under `logs/signal_recovery/` (or `LOGS_ROOT/signal_recovery/`).

## Phase 1 — Runtime stabilization

1. **Delta IP whitelist (manual):** Add outbound IP `115.96.12.44` to your Delta Exchange API key allowlist.
2. Run pipeline health check:

```bash
python scripts/signal_recovery/run.py phase1
```

3. Keep safety gates at defaults (`AGENT_START_MODE=MONITORING`, do not lower `ai_signal_min_entry_confidence` until signal quality improves).

## Phase 2 — Baseline telemetry (24h)

Telemetry is appended automatically when the agent runs (`SIGNAL_RECOVERY_TELEMETRY_ENABLED=true`, default).

```bash
python scripts/signal_recovery/run.py baseline --hours 24
```

Output: `logs/signal_recovery/baseline_kpis.json`

## Phase 3 — Ablations

**Meta-path A/B** (artifact replay, no live behavior change):

```bash
python scripts/signal_recovery/run.py meta-ablation
```

**Label schemes** (simple vs cost-aware no-trade band vs triple-barrier):

```bash
python scripts/signal_recovery/run.py labels
```

**Live inference stack experiment** (optional, controlled):

```env
JACKSPARROW_V43_INFERENCE_STACK=regressor_mean
```

Restart agent; collect another baseline window; compare KPIs. Revert to `meta_calibrator` for production unless promotion gates pass.

## Phase 4 — Drift

```bash
python scripts/signal_recovery/run.py drift
```

## Phase 5 — Promotion gates

```bash
python scripts/signal_recovery/run.py promotion \
  --baseline logs/signal_recovery/baseline_kpis.json \
  --candidate logs/signal_recovery/baseline_kpis.json
```

Run all phases:

```bash
python scripts/signal_recovery/run.py all
```
