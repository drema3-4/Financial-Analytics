"""Add explicit analytics classification and measured read index.

Revision ID: 20261013_0009
Revises: 20261013_0008
Create Date: 2026-10-13 23:45:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261013_0009"
down_revision: str | None = "20261013_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "categories",
        sa.Column("is_mandatory", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_check_constraint(
        "ck_categories_category_mandatory_expense",
        "categories",
        "NOT is_mandatory OR kind = 'expense'",
    )
    op.create_index(
        "ix_transactions_owner_id_occurred_at_id_posted",
        "transactions",
        ["owner_id", "occurred_at", "id"],
        postgresql_where=sa.text("status = 'posted'"),
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_owner_id_occurred_at_id_posted", table_name="transactions")
    op.drop_constraint("ck_categories_category_mandatory_expense", "categories", type_="check")
    op.drop_column("categories", "is_mandatory")
