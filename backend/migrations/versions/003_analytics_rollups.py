"""Add analytics_rollups for precomputed performance summaries.

Revision ID: 003_analytics_rollups
Revises: 002_entry_decisions
Create Date: 2026-06-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "003_analytics_rollups"
down_revision: Union[str, None] = "002_entry_decisions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analytics_rollups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("period_type", sa.String(32), nullable=False),
        sa.Column("period_key", sa.String(128), nullable=False),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("trade_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("win_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_pnl_usd", sa.Numeric(24, 8), nullable=False, server_default="0"),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "period_type",
            "period_key",
            "symbol",
            name="idx_analytics_rollups_unique",
        ),
    )
    op.create_index("ix_analytics_rollups_period_type", "analytics_rollups", ["period_type"])
    op.create_index("ix_analytics_rollups_symbol", "analytics_rollups", ["symbol"])


def downgrade() -> None:
    op.drop_table("analytics_rollups")
