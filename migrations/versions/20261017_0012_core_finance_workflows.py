"""Separate user-facing deposits and archive mutable planning records.

Revision ID: 20261017_0012
Revises: 20261016_0011
Create Date: 2026-10-17 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261017_0012"
down_revision: str | None = "20261016_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "deposit_terms",
        sa.Column(
            "automatic_interest", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
    )
    op.add_column(
        "deposit_terms",
        sa.Column("name", sa.String(160), nullable=False, server_default="Вклад"),
    )
    op.add_column(
        "deposit_terms",
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "deposit_terms",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "deposit_terms",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_check_constraint(
        "ck_deposit_terms_deposit_terms_name",
        "deposit_terms",
        "char_length(btrim(name)) > 0",
    )
    op.create_check_constraint(
        "ck_deposit_terms_deposit_terms_version", "deposit_terms", "version > 0"
    )
    op.execute(
        """
        DROP TRIGGER trg_deposit_terms_append_only ON deposit_terms;
        DROP TRIGGER trg_deposit_rate_periods_append_only ON deposit_rate_periods;

        UPDATE deposit_terms AS d
        SET name = a.name, archived = a.archived, automatic_interest = false
        FROM accounts AS a
        WHERE a.owner_id = d.owner_id AND a.id = d.principal_account_id;

        UPDATE accounts AS a
        SET kind = 'other_asset'
        WHERE a.kind = 'deposit'
          AND NOT EXISTS (
              SELECT 1 FROM deposit_terms AS d
              WHERE d.owner_id = a.owner_id AND d.principal_account_id = a.id
          );

        CREATE TRIGGER trg_deposit_terms_no_delete
        BEFORE DELETE ON deposit_terms
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.add_column(
        "financial_goals",
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.alter_column("deposit_terms", "name", server_default=None)


def downgrade() -> None:
    op.drop_column("financial_goals", "archived")
    op.execute(
        """
        DROP TRIGGER trg_deposit_terms_no_delete ON deposit_terms;

        CREATE TRIGGER trg_deposit_terms_append_only
        BEFORE UPDATE OR DELETE ON deposit_terms
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();

        CREATE TRIGGER trg_deposit_rate_periods_append_only
        BEFORE UPDATE OR DELETE ON deposit_rate_periods
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.drop_constraint("ck_deposit_terms_deposit_terms_version", "deposit_terms", type_="check")
    op.drop_constraint("ck_deposit_terms_deposit_terms_name", "deposit_terms", type_="check")
    op.drop_column("deposit_terms", "updated_at")
    op.drop_column("deposit_terms", "version")
    op.drop_column("deposit_terms", "archived")
    op.drop_column("deposit_terms", "name")
    op.drop_column("deposit_terms", "automatic_interest")
