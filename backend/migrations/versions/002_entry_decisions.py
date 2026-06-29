"""Add entry_decisions table for approve/reject funnel analytics.

Revision ID: 002_entry_decisions
Revises: 001_baseline
Create Date: 2026-06-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "002_entry_decisions"
down_revision: Union[str, None] = "001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "entry_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_id", sa.String(255), nullable=False),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("reject_reason", sa.String(128), nullable=True),
        sa.Column("signal", sa.String(64), nullable=True),
        sa.Column("side", sa.String(16), nullable=True),
        sa.Column("confidence", sa.Numeric(8, 6), nullable=True),
        sa.Column("reasoning_chain_id", sa.String(255), nullable=True),
        sa.Column("config_hash", sa.String(16), nullable=True),
        sa.Column("position_id", sa.String(255), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=True,
        ),
        sa.UniqueConstraint("decision_id", name="uq_entry_decisions_decision_id"),
    )
    op.create_index("idx_entry_decisions_symbol_ts", "entry_decisions", ["symbol", "timestamp"])
    op.create_index(
        "idx_entry_decisions_outcome_reason",
        "entry_decisions",
        ["outcome", "reject_reason"],
    )
    op.create_index("ix_entry_decisions_decision_id", "entry_decisions", ["decision_id"])
    op.create_index("ix_entry_decisions_config_hash", "entry_decisions", ["config_hash"])


def downgrade() -> None:
    op.drop_table("entry_decisions")
