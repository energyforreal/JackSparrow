"""Add entry_decision_labels for reject forward-outcome labeling.

Revision ID: 005_entry_decision_labels
Revises: 004_trade_decision_events
Create Date: 2026-07-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005_entry_decision_labels"
down_revision: Union[str, None] = "004_trade_decision_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "entry_decision_labels",
        sa.Column("decision_id", sa.String(255), primary_key=True),
        sa.Column("label_horizon_bars", sa.Integer(), nullable=False),
        sa.Column("forward_return_pct", sa.Numeric(12, 6), nullable=True),
        sa.Column("forward_mfe_pct", sa.Numeric(12, 6), nullable=True),
        sa.Column("forward_mae_pct", sa.Numeric(12, 6), nullable=True),
        sa.Column("would_have_won", sa.Boolean(), nullable=True),
        sa.Column("labeled_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_entry_decision_labels_labeled_at",
        "entry_decision_labels",
        ["labeled_at"],
    )


def downgrade() -> None:
    op.drop_table("entry_decision_labels")
