# Ops Hygiene — 2026-07-12 (Task 6)

## Scheduled tasks

| Task | State | Last run | Last result | Next |
|------|-------|----------|-------------|------|
| `JackSparrow-DailyValidation` | Enabled / Ready | 2026-07-12 11:30 | 0 | 2026-07-13 11:30 |
| `JackSparrow-WeeklyValidation` | Enabled / Ready | 2026-07-12 11:30 | 0 | 2026-07-19 11:30 (Sun) |

Both invoke `scripts/daily_validation.ps1` (weekly adds `-Weekly`). No new registration needed.

## TRADE_LIFECYCLE_LOG_ONLY

- Was: `true` in live `.env` (exit-lifecycle interventions log-only).
- Set to: `false` on 2026-07-12 so Phase A testnet fills can apply TLE actions when trades fire.
- `AGENT_THESIS_USE_HURST_V2=true` remains (Phase A testnet shadow only — not production promotion).

Requires agent restart for `.env` to take effect in the running container.
