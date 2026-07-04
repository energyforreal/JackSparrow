"""Wallet ledger tables for Delta wallet transaction sync.

Revision ID: 007_wallet_ledger
Revises: 006_trade_outcomes_denorm
Create Date: 2026-07-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "007_wallet_ledger"
down_revision: Union[str, None] = "006_trade_outcomes_denorm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wallet_transactions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("exchange", sa.String(length=32), nullable=False, server_default="delta"),
        sa.Column("exchange_transaction_id", sa.BigInteger(), nullable=False),
        sa.Column("transaction_type", sa.String(length=64), nullable=False),
        sa.Column("asset_symbol", sa.String(length=16), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("order_id", sa.BigInteger(), nullable=True),
        sa.Column("amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("balance_after", sa.Numeric(24, 8), nullable=True),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "exchange",
            "exchange_transaction_id",
            name="uq_wallet_transactions_exchange_tx_id",
        ),
    )
    op.create_index(
        "idx_wallet_transactions_occurred_at",
        "wallet_transactions",
        ["occurred_at"],
    )
    op.create_index(
        "idx_wallet_transactions_transaction_type",
        "wallet_transactions",
        ["transaction_type"],
    )
    op.create_index(
        "idx_wallet_transactions_asset_symbol",
        "wallet_transactions",
        ["asset_symbol"],
    )
    op.create_index(
        "idx_wallet_transactions_order_id",
        "wallet_transactions",
        ["order_id"],
    )

    op.create_table(
        "wallet_sync_state",
        sa.Column("exchange", sa.String(length=32), nullable=False),
        sa.Column("scope_key", sa.String(length=64), nullable=False),
        sa.Column("last_cursor", sa.Text(), nullable=True),
        sa.Column("last_transaction_id", sa.BigInteger(), nullable=True),
        sa.Column("last_occurred_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("exchange", "scope_key"),
    )


def downgrade() -> None:
    op.drop_table("wallet_sync_state")
    op.drop_index("idx_wallet_transactions_order_id", table_name="wallet_transactions")
    op.drop_index("idx_wallet_transactions_asset_symbol", table_name="wallet_transactions")
    op.drop_index("idx_wallet_transactions_transaction_type", table_name="wallet_transactions")
    op.drop_index("idx_wallet_transactions_occurred_at", table_name="wallet_transactions")
    op.drop_table("wallet_transactions")
