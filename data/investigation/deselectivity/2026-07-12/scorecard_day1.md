# Scorecard day1 — 2026-07-12 (post recreate + funnel)

**Phase A start (UTC):** 2026-07-12T10:21:37Z  
**Scorecard at (UTC):** ~2026-07-12T13:15Z (~T+3h)  
**Ops:** agent/backend/frontend healthy; `AGENT_THESIS_USE_HURST_V2=true`; `TRADE_LIFECYCLE_LOG_ONLY=false`; dual-write 3/3 latest rows.

## Layered funnel (post-A telemetry)

Source: [`funnel_post_a.md`](funnel_post_a.md) / [`funnel_post_a.json`](funnel_post_a.json)

| Layer | Count | Notes |
|-------|------:|-------|
| Thesis fires | **15** | trend_continuation (hurst_v2 path live) |
| Thesis fires / 24h | **~128** | Promote fire criterion (≥5/24h) **PASS** on rate |
| Quality below floor | **15** | Binding — score ~47 &lt; min 55 |
| Gate5 fail | **15** | Binding — negative economic edge |
| HOLD after thesis fire | **15** | 100% of fires held at quality/Gate5 |
| Risk veto-like | 0 | OK vs baseline |
| Dual-write both hurst | see funnel JSON | Live |

Interpretation: Phase A **unblocked thesis generation**. Entry still blocked by **quality floor + Gate5**, not by flat thesis / hurst scale. Do **not** lower floors this window.

## Vs baseline ([SCORECARD_BASELINE.md](SCORECARD_BASELINE.md))

| Metric | Baseline | Day1 post-A | Gate |
|--------|----------|-------------|------|
| Hold cause | `hypothesis_no_rule_fired` 100% | Thesis fires present; hold via quality/Gate5 | Shift expected under A |
| Trend fires | ~0 | 15 in ~3h | ≥5/24h **PASS** (rate) |
| Risk veto | low | 0 | OK |
| Fills / net EV | — | 0 / n/a | **DEFERRED** to T+48–72h |
| Kill criteria | — | none | **PASS** |

## Numeric gate status (day1)

| Gate | Status |
|------|--------|
| Trend fire ≥2× or ≥5/24h | **PASS** (rate; small elapsed window) |
| hold share −10pp | **PENDING** (hold still high; cause shifted) |
| EV ≥ baseline | **DEFERRED** to T+48–72h |
| NegCtrl ±15% | **OK so far** (risk 0) |
| Kill criteria | **NONE TRIPPED** |

## Commands

```powershell
python tools/commands/phase_a_funnel_from_telemetry.py --since 2026-07-12T10:21:37+00:00 --out data/investigation/deselectivity/2026-07-12/funnel_post_a
# Daily: python tools/commands/phase3_daily_forensics.py --workstream hurst_v2 --skip-rolling
```
