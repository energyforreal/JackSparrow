"""Add trade_decision_events append-only decision timeline.

Revision ID: 004_trade_decision_events
Revises: 003_analytics_rollups
Create Date: 2026-07-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "004_trade_decision_events"
down_revision: Union[str, None] = "003_analytics_rollups"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "trade_decision_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("position_id", sa.String(255), nullable=True),
        sa.Column("reasoning_chain_id", sa.String(255), nullable=True),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("bar_index", sa.Integer(), nullable=True),
        sa.Column("sequence_num", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("captured_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("caused_by", postgresql.JSONB(), nullable=True),
        sa.Column("delta", postgresql.JSONB(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=True,
        ),
        sa.UniqueConstraint("event_id", name="uq_trade_decision_events_event_id"),
    )
    op.create_index(
        "idx_trade_decision_events_position_seq",
        "trade_decision_events",
        ["position_id", "sequence_num"],
    )
    op.create_index(
        "ix_trade_decision_events_reasoning_chain_id",
        "trade_decision_events",
        ["reasoning_chain_id"],
    )
    op.create_index(
        "ix_trade_decision_events_symbol",
        "trade_decision_events",
        ["symbol"],
    )
    op.create_index(
        "ix_trade_decision_events_event_type",
        "trade_decision_events",
        ["event_type"],
    )
    op.create_index(
        "ix_trade_decision_events_captured_at",
        "trade_decision_events",
        ["captured_at"],
    )


def downgrade() -> None:
    op.drop_table("trade_decision_events")
