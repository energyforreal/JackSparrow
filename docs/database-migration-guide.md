# Database Schema Migration Guide

## Overview

This guide explains how to fix the database schema mismatch issue where PostgreSQL columns are VARCHAR but SQLAlchemy expects enum types.

## Problem

The error occurs because:
- Database columns (`positions.status`, `trades.status`) are VARCHAR
- SQLAlchemy models expect PostgreSQL enum types (`positionstatus`, `tradestatus`)
- This causes query failures: `operator does not exist: character varying = positionstatus`

## Solution

Run the migration script to convert VARCHAR columns to PostgreSQL enum types.

## Migration Steps

### 1. Backup Database (Recommended)

```bash
pg_dump -U your_user -d your_database > backup_before_enum_migration.sql
```

### 2. Run Migration Script

```bash
python scripts/migrate_enum_types.py
```

The script will:
- Create enum types if they don't exist
- Check current column types
- Migrate `positions.status` from VARCHAR to `positionstatus` enum
- Migrate `trades.status` from VARCHAR to `tradestatus` enum
- Preserve all existing data

### 3. Verify Migration

After migration, test the endpoints:
```bash
curl http://localhost:8000/api/v1/portfolio/summary
curl http://localhost:8000/api/v1/portfolio/performance
```

### 4. Restart Backend

Restart the backend service to ensure changes take effect:
```bash
# If using systemd
sudo systemctl restart jacksparrow-backend

# Or if running manually
# Stop and restart the backend process
```

## What Changed

### Database Models (`backend/core/database.py`)
- Updated enum column definitions to use `PostgresEnum` with explicit type names
- This ensures SQLAlchemy knows about the PostgreSQL enum types

### Migration Script (`scripts/migrate_enum_types.py`)
- Safely converts VARCHAR columns to enum types
- Preserves all existing data
- Handles edge cases and errors gracefully

## Rollback

If you need to rollback the migration:

```sql
-- Convert back to VARCHAR (if needed)
ALTER TABLE positions ALTER COLUMN status TYPE VARCHAR(50);
ALTER TABLE trades ALTER COLUMN status TYPE VARCHAR(50);
```

Then restore from backup:
```bash
psql -U your_user -d your_database < backup_before_enum_migration.sql
```

## Related Files

- `scripts/migrate_enum_types.py` - Migration script
- `backend/core/database.py` - Updated SQLAlchemy models
- `scripts/setup_db.py` - Database setup script (uses enum types)

