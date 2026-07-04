"""Denormalize wallet cost columns on trade_outcomes.

Revision ID: 008_trade_outcomes_wallet_denorm
Revises: 007_wallet_ledger
Create Date: 2026-07-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "008_trade_outcomes_wallet_denorm"
down_revision: Union[str, None] = "007_wallet_ledger"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "trade_outcomes",
        sa.Column("commission_usd", sa.Numeric(24, 8), nullable=True),
    )
    op.add_column(
        "trade_outcomes",
        sa.Column("funding_usd", sa.Numeric(24, 8), nullable=True),
    )
    op.add_column(
        "trade_outcomes",
        sa.Column("net_wallet_impact_usd", sa.Numeric(24, 8), nullable=True),
    )
    op.create_index(
        "idx_trade_outcomes_funding_usd",
        "trade_outcomes",
        ["funding_usd"],
    )


def downgrade() -> None:
    op.drop_index("idx_trade_outcomes_funding_usd", table_name="trade_outcomes")
    op.drop_column("trade_outcomes", "net_wallet_impact_usd")
    op.drop_column("trade_outcomes", "funding_usd")
    op.drop_column("trade_outcomes", "commission_usd")
