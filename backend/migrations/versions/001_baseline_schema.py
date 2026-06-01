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
    # No-op baseline: existing deployments rely on SQLAlchemy create_all / inline migrations.
    # Future revisions should use autogenerate against backend.core.database models.
    pass


def downgrade() -> None:
    pass
