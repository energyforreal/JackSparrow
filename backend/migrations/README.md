# Database migrations

- Baseline revision: `001_baseline` (no-op for existing `create_all` deployments).
- Configure `DATABASE_URL` in `.env`, then from repo root:

```bash
alembic -c alembic.ini upgrade head
alembic -c alembic.ini revision --autogenerate -m "describe change"
```

Set `AUTO_CREATE_DB_SCHEMA=false` in production once migrations are applied.
