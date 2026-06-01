"""Baseline schema marker — tables may already exist via AUTO_CREATE_DB_SCHEMA.

Revision ID: 001_baseline
Revises:
Create Date: 2026-06-01

Use ``alembic revision --autogenerate`` for incremental changes after this baseline.
Production should set ``AUTO_CREATE_DB_SCHEMA=false`` and manage schema via Alembic.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Enable TimescaleDB hypertables for time-series tables when extension is present."""
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'trade_outcomes'
            ) THEN
                PERFORM create_hypertable(
                    'trade_outcomes', 'closed_at', if_not_exists => TRUE, migrate_data => TRUE
                );
            END IF;
        EXCEPTION
            WHEN undefined_function THEN
                RAISE NOTICE 'TimescaleDB create_hypertable unavailable; skipping trade_outcomes';
            WHEN others THEN
                RAISE NOTICE 'trade_outcomes hypertable skipped: %', SQLERRM;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'prediction_audit'
            ) THEN
                PERFORM create_hypertable(
                    'prediction_audit', 'created_at', if_not_exists => TRUE, migrate_data => TRUE
                );
            END IF;
        EXCEPTION
            WHEN undefined_function THEN
                RAISE NOTICE 'TimescaleDB create_hypertable unavailable; skipping prediction_audit';
            WHEN others THEN
                RAISE NOTICE 'prediction_audit hypertable skipped: %', SQLERRM;
        END $$;
        """
    )


def downgrade() -> None:
    pass
