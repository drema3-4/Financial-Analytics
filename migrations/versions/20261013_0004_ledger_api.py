"""Add adjustment semantics and transaction source for the ledger API.

Revision ID: 20261013_0004
Revises: 20261013_0003
Create Date: 2026-10-13 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261013_0004"
down_revision: str | None = "20261013_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_accounts_account_kind", "accounts", type_="check")
    op.create_check_constraint(
        "ck_accounts_account_kind",
        "accounts",
        "kind IN ('cash', 'bank', 'savings', 'deposit', 'other_asset', "
        "'system_income', 'system_expense', 'system_equity')",
    )
    op.create_index(
        "uq_accounts_owner_system_kind_currency",
        "accounts",
        ["owner_id", "kind", "currency"],
        unique=True,
        postgresql_where=sa.text("kind IN ('system_income', 'system_expense', 'system_equity')"),
    )

    op.add_column(
        "transactions",
        sa.Column("source", sa.String(32), server_default=sa.text("'manual'"), nullable=False),
    )
    op.drop_constraint("ck_transactions_transaction_kind", "transactions", type_="check")
    op.drop_constraint("ck_transactions_transaction_shape", "transactions", type_="check")
    op.create_check_constraint(
        "ck_transactions_transaction_kind",
        "transactions",
        "kind IN ('income', 'expense', 'transfer', 'adjustment', 'reversal')",
    )
    op.create_check_constraint(
        "ck_transactions_transaction_shape",
        "transactions",
        "(kind IN ('income', 'expense') AND category_id IS NOT NULL "
        "AND reversal_of_id IS NULL) OR "
        "(kind IN ('transfer', 'adjustment') AND category_id IS NULL "
        "AND reversal_of_id IS NULL) OR "
        "(kind = 'reversal' AND category_id IS NULL AND reversal_of_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_transactions_transaction_source",
        "transactions",
        "char_length(btrim(source)) BETWEEN 1 AND 32",
    )


def downgrade() -> None:
    op.drop_constraint("ck_transactions_transaction_source", "transactions", type_="check")
    op.drop_constraint("ck_transactions_transaction_shape", "transactions", type_="check")
    op.drop_constraint("ck_transactions_transaction_kind", "transactions", type_="check")
    op.create_check_constraint(
        "ck_transactions_transaction_kind",
        "transactions",
        "kind IN ('income', 'expense', 'transfer', 'reversal')",
    )
    op.create_check_constraint(
        "ck_transactions_transaction_shape",
        "transactions",
        "(kind IN ('income', 'expense') AND category_id IS NOT NULL "
        "AND reversal_of_id IS NULL) OR "
        "(kind = 'transfer' AND category_id IS NULL AND reversal_of_id IS NULL) OR "
        "(kind = 'reversal' AND category_id IS NULL AND reversal_of_id IS NOT NULL)",
    )
    op.drop_column("transactions", "source")

    op.drop_index("uq_accounts_owner_system_kind_currency", table_name="accounts")
    op.drop_constraint("ck_accounts_account_kind", "accounts", type_="check")
    op.create_check_constraint(
        "ck_accounts_account_kind",
        "accounts",
        "kind IN ('cash', 'bank', 'savings', 'deposit', 'other_asset', "
        "'system_income', 'system_expense')",
    )
