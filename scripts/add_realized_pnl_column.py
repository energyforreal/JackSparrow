#!/usr/bin/env python3
"""
Database migration script to add realized_pnl column to positions table.

This script adds the realized_pnl column to the positions table for the audit fix B2.
Run this before starting the backend if the column doesn't exist.
"""

import asyncio
import sys
from pathlib import Path

# Add project root and backend to path
project_root = Path(__file__).resolve().parents[1]
backend_path = project_root / "backend"
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(backend_path))

from backend.core.database import engine
from backend.core.config import settings
from sqlalchemy import text


async def add_realized_pnl_column():
    """Add realized_pnl column to positions table if it doesn't exist."""
    async with engine.begin() as connection:
        # Check if column exists
        result = await connection.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'positions' AND column_name = 'realized_pnl'
        """))

        if result.fetchone():
            print("✓ realized_pnl column already exists")
            return

        # Add the column
        print("Adding realized_pnl column to positions table...")
        await connection.execute(text("""
            ALTER TABLE positions
            ADD COLUMN realized_pnl DECIMAL(18, 8) DEFAULT 0.0
        """))

        print("✓ realized_pnl column added successfully")

        # Backfill existing closed positions
        print("Backfilling realized_pnl for existing closed positions...")
        await connection.execute(text("""
            UPDATE positions
            SET realized_pnl = COALESCE(unrealized_pnl, 0.0)
            WHERE status = 'CLOSED'
        """))

        print("✓ Backfill completed")


async def main():
    """Main migration function."""
    print("Starting database migration: add realized_pnl column")
    print(f"Database: {settings.database_url.replace(settings.database_url.split('@')[0].split('//')[1], '***:***@')}")

    try:
        await add_realized_pnl_column()
        print("Migration completed successfully!")
    except Exception as e:
        print(f"Migration failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())