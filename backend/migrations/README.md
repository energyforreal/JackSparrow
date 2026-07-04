# Database migrations

Alembic revisions for the JackSparrow PostgreSQL analytics and governance tables.

## Revisions

| ID | File | Description |
|----|------|-------------|
| `001_baseline` | `001_baseline_schema.py` | No-op baseline for deployments that used `create_all` |
| `002_entry_decisions` | `002_entry_decisions.py` | `entry_decisions` — approve/reject/executed funnel |
| `003_analytics_rollups` | `003_analytics_rollups.py` | `analytics_rollups` — daily/regime/config_hash aggregates |
| `004_trade_decision_events` | `004_trade_decision_events.py` | `trade_decision_events` — append-only decision timeline |
| `005_entry_decision_labels` | `005_entry_decision_labels.py` | `entry_decision_labels` — reject forward outcomes |
| `006_trade_outcomes_denorm` | `006_trade_outcomes_denorm.py` | Denormalized columns on `trade_outcomes` |
| `007_wallet_ledger` | `007_wallet_ledger.py` | `wallet_transactions`, `wallet_sync_state` |
| `008_trade_outcomes_wallet_denorm` | `008_trade_outcomes_wallet_denorm.py` | Wallet cost columns on `trade_outcomes` |

## Apply migrations

Configure `DATABASE_URL` in `.env`, then from **repo root**:

```bash
alembic -c alembic.ini upgrade head
alembic -c alembic.ini revision --autogenerate -m "describe change"
```

## Docker

Backend container includes `alembic.ini` and `backend/migrations/`. On startup (when `AUTO_CREATE_DB_SCHEMA=true`), the backend runs `alembic upgrade head` before verifying the head revision.

Manual apply inside compose:

```bash
docker compose run --rm --no-deps backend sh -c "cd /app && alembic -c alembic.ini upgrade head"
```

### Schema drift (tables exist, version lags)

If `Base.metadata.create_all` already created tables but `alembic_version` is behind:

```bash
docker compose exec postgres psql -U jacksparrow -d trading_agent -c "\dt entry_decisions"
docker compose exec postgres psql -U jacksparrow -d trading_agent -c "SELECT * FROM alembic_version;"

# When tables exist and match migration DDL:
docker compose run --rm --no-deps backend sh -c "cd /app && alembic -c alembic.ini stamp head"
```

## Production

Set `AUTO_CREATE_DB_SCHEMA=false` only when schema is managed externally via CI/CD `alembic upgrade head`. Startup will skip auto-migrate but still expects the DB at head if verification is enabled.
