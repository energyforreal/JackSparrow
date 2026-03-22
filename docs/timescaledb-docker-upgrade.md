# TimescaleDB extension upgrade (Docker volume)

If PostgreSQL logs report the TimescaleDB extension in the **data volume** is older than the library shipped with the image (for example installed `2.13.1` vs image `2.25.x`), plan an upgrade in a **maintenance window** after backup.

## Preconditions

- Backup the `postgres-data` volume (or dump with `pg_dump`).
- Confirm the [TimescaleDB upgrade matrix](https://docs.timescale.com/self-hosted/latest/upgrades/) for your Postgres major version.

## Steps (typical)

1. Stop the stack: `docker compose down` (or stop only `postgres` if others can stay down).
2. Start Postgres with the same image you use in production (`timescale/timescaledb:...`).
3. Connect as superuser and run:

```sql
ALTER EXTENSION timescaledb UPDATE;
```

4. Verify: `\dx timescaledb` in `psql` should show the new version.
5. Restart the full stack and run application smoke tests.

## Notes

- Run first against a **restored copy** of the volume if possible.
- If `ALTER EXTENSION` fails, follow the error hint and Timescale’s major-version upgrade docs rather than forcing.
