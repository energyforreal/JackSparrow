"""Denormalize hot analytics columns on trade_outcomes.

Revision ID: 006_trade_outcomes_denorm
Revises: 005_entry_decision_labels
Create Date: 2026-07-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "006_trade_outcomes_denorm"
down_revision: Union[str, None] = "005_entry_decision_labels"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("trade_outcomes", sa.Column("config_hash", sa.String(16), nullable=True))
    op.add_column("trade_outcomes", sa.Column("setup_type", sa.String(64), nullable=True))
    op.add_column("trade_outcomes", sa.Column("regime", sa.String(64), nullable=True))
    op.add_column("trade_outcomes", sa.Column("root_cause", sa.String(64), nullable=True))
    op.add_column(
        "trade_outcomes",
        sa.Column("entry_quality_score", sa.Numeric(8, 6), nullable=True),
    )
    op.add_column("trade_outcomes", sa.Column("mfe_pct", sa.Numeric(12, 6), nullable=True))
    op.add_column("trade_outcomes", sa.Column("mae_pct", sa.Numeric(12, 6), nullable=True))
    op.add_column(
        "trade_outcomes",
        sa.Column("slippage_bps_entry", sa.Numeric(12, 4), nullable=True),
    )
    op.add_column(
        "trade_outcomes",
        sa.Column("decision_event_count", sa.Integer(), nullable=True),
    )
    op.create_index("idx_trade_outcomes_config_hash", "trade_outcomes", ["config_hash"])
    op.create_index("idx_trade_outcomes_setup_type", "trade_outcomes", ["setup_type"])
    op.create_index("idx_trade_outcomes_regime", "trade_outcomes", ["regime"])
    op.create_index("idx_trade_outcomes_root_cause", "trade_outcomes", ["root_cause"])


def downgrade() -> None:
    op.drop_index("idx_trade_outcomes_root_cause", table_name="trade_outcomes")
    op.drop_index("idx_trade_outcomes_regime", table_name="trade_outcomes")
    op.drop_index("idx_trade_outcomes_setup_type", table_name="trade_outcomes")
    op.drop_index("idx_trade_outcomes_config_hash", table_name="trade_outcomes")
    op.drop_column("trade_outcomes", "decision_event_count")
    op.drop_column("trade_outcomes", "slippage_bps_entry")
    op.drop_column("trade_outcomes", "mae_pct")
    op.drop_column("trade_outcomes", "mfe_pct")
    op.drop_column("trade_outcomes", "entry_quality_score")
    op.drop_column("trade_outcomes", "root_cause")
    op.drop_column("trade_outcomes", "regime")
    op.drop_column("trade_outcomes", "setup_type")
    op.drop_column("trade_outcomes", "config_hash")
