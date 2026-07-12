# Phase 3B Hold — 2026-07-12

**Flag:** `V15_ADX_THESIS_AWARE_ENABLED=false` (unchanged; documented in `.env.example`)

## Promotion gate (re-checked today)

| Source | ADX cohort n | Avg net return % | Net EV positive | Blocked |
|--------|-------------:|-----------------:|:---------------:|:-------:|
| `economic_replay_2026-07-09.json` | 16 | -0.2504 | no | yes |
| `economic_replay_adx_2026-07-12.json` (today’s reject mix) | 5 | -0.2257 | no | yes |

Gate criteria from [`phase3_design_decisions.md`](phase3_design_decisions.md):

- `n >= 30`
- net expectancy ≥ 0

**Result:** promotion remains **blocked**. Do not enable 3B on testnet or production.

## Runtime verification

Agent container settings (2026-07-12):

- `v15_adx_thesis_aware_enabled` = `False`
- `V15_ADX_REGIME_FILTER_ENABLED` remains baseline (`true`)

## Rollback

If ever enabled experimentally: set `V15_ADX_THESIS_AWARE_ENABLED=false` and restart agent.
