"""Add immutable deposit terms and deposit-linked ledger entries.

Revision ID: 20261013_0008
Revises: 20261013_0007
Create Date: 2026-10-13 19:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261013_0008"
down_revision: str | None = "20261013_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "deposit_terms",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("principal_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("opened_on", sa.Date(), nullable=False),
        sa.Column("matures_on", sa.Date(), nullable=False),
        sa.Column("capitalization_frequency", sa.String(32), nullable=False),
        sa.Column("day_count_convention", sa.String(32), nullable=False),
        sa.Column("rounding_policy", sa.String(16), nullable=False),
        sa.Column("interest_rounding_frequency", sa.String(24), nullable=False),
        sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("cashflow_cutoff_time", sa.Time(timezone=False), nullable=False),
        sa.Column("cashflow_cutoff_inclusive", sa.Boolean(), nullable=False),
        sa.Column("early_close_policy", sa.String(24), nullable=False),
        sa.Column("early_close_rate", sa.Numeric(20, 12), nullable=True),
        sa.Column("tax_rate", sa.Numeric(20, 12), nullable=False),
        sa.Column("algorithm_version", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_deposit_terms"),
        sa.UniqueConstraint("owner_id", "id", name="uq_deposit_terms_owner_id_id"),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_deposit_terms_owner_id_users", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "principal_account_id", "currency"],
            ["accounts.owner_id", "accounts.id", "accounts.currency"],
            name="fk_deposit_terms_owner_account_currency_accounts",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name="ck_deposit_terms_deposit_terms_currency"
        ),
        sa.CheckConstraint(
            "matures_on > opened_on", name="ck_deposit_terms_deposit_terms_date_order"
        ),
        sa.CheckConstraint(
            "capitalization_frequency IN ('daily', 'monthly_calendar_end')",
            name="ck_deposit_terms_deposit_terms_capitalization_frequency",
        ),
        sa.CheckConstraint(
            "day_count_convention IN ('actual_365_fixed', 'actual_actual_isda')",
            name="ck_deposit_terms_deposit_terms_day_count_convention",
        ),
        sa.CheckConstraint(
            "rounding_policy IN ('half_even', 'half_up')",
            name="ck_deposit_terms_deposit_terms_rounding_policy",
        ),
        sa.CheckConstraint(
            "interest_rounding_frequency IN ('daily', 'capitalization')",
            name="ck_deposit_terms_deposit_terms_interest_rounding_frequency",
        ),
        sa.CheckConstraint(
            "early_close_policy IN ('forbid', 'forfeit_interest', 'reprice')",
            name="ck_deposit_terms_deposit_terms_early_close_policy",
        ),
        sa.CheckConstraint(
            "(early_close_policy = 'reprice') = (early_close_rate IS NOT NULL)",
            name="ck_deposit_terms_deposit_terms_early_close_rate_shape",
        ),
        sa.CheckConstraint(
            "early_close_rate >= 0", name="ck_deposit_terms_deposit_terms_early_close_rate"
        ),
        sa.CheckConstraint(
            "tax_rate >= 0 AND tax_rate < 1", name="ck_deposit_terms_deposit_terms_tax_rate"
        ),
        sa.CheckConstraint(
            "char_length(timezone) BETWEEN 1 AND 100",
            name="ck_deposit_terms_deposit_terms_timezone",
        ),
        sa.CheckConstraint(
            "algorithm_version = 'deposit-interest-v1'",
            name="ck_deposit_terms_deposit_terms_algorithm_version",
        ),
    )
    op.create_index(
        "ix_deposit_terms_owner_id_opened_on", "deposit_terms", ["owner_id", "opened_on"]
    )
    op.create_table(
        "deposit_rate_periods",
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("deposit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("nominal_rate", sa.Numeric(20, 12), nullable=False),
        sa.PrimaryKeyConstraint(
            "owner_id", "deposit_id", "starts_on", name="pk_deposit_rate_periods"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "deposit_id"],
            ["deposit_terms.owner_id", "deposit_terms.id"],
            name="fk_deposit_rate_periods_owner_deposit_deposit_terms",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "ends_on > starts_on", name="ck_deposit_rate_periods_deposit_rate_periods_date_order"
        ),
        sa.CheckConstraint(
            "nominal_rate >= 0",
            name="ck_deposit_rate_periods_deposit_rate_periods_nominal_rate",
        ),
    )
    op.create_index(
        "ix_deposit_rate_periods_owner_id_deposit_id",
        "deposit_rate_periods",
        ["owner_id", "deposit_id"],
    )
    op.add_column(
        "transactions", sa.Column("deposit_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_transactions_owner_id_deposit_id_deposit_terms",
        "transactions",
        "deposit_terms",
        ["owner_id", "deposit_id"],
        ["owner_id", "id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint("ck_transactions_transaction_kind", "transactions", type_="check")
    op.drop_constraint("ck_transactions_transaction_shape", "transactions", type_="check")
    op.create_check_constraint(
        "ck_transactions_transaction_kind",
        "transactions",
        "kind IN ('income', 'expense', 'transfer', 'adjustment', 'interest', 'reversal')",
    )
    op.create_check_constraint(
        "ck_transactions_transaction_shape",
        "transactions",
        "(kind IN ('income', 'expense') AND category_id IS NOT NULL "
        "AND reversal_of_id IS NULL) OR "
        "(kind IN ('transfer', 'adjustment', 'interest') AND category_id IS NULL "
        "AND reversal_of_id IS NULL) OR "
        "(kind = 'reversal' AND category_id IS NULL AND reversal_of_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_transactions_transaction_deposit_shape",
        "transactions",
        "(kind = 'interest' AND deposit_id IS NOT NULL AND source = 'deposit_interest') OR "
        "(kind = 'transfer' AND ((deposit_id IS NULL AND source <> 'deposit_cashflow') OR "
        "(deposit_id IS NOT NULL AND source = 'deposit_cashflow'))) OR "
        "(kind = 'reversal') OR "
        "(kind IN ('income', 'expense', 'adjustment') AND deposit_id IS NULL)",
    )
    _replace_transaction_guard(include_deposit=True)
    op.execute(
        """
        CREATE TRIGGER trg_deposit_terms_append_only
        BEFORE UPDATE OR DELETE ON deposit_terms
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();

        CREATE TRIGGER trg_deposit_rate_periods_append_only
        BEFORE UPDATE OR DELETE ON deposit_rate_periods
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();

        CREATE FUNCTION assert_deposit_transaction_integrity() RETURNS trigger AS $$
        DECLARE
            checked_owner uuid;
            checked_id uuid;
            tx transactions%ROWTYPE;
            principal_id uuid;
            principal_posting_count integer;
            original_deposit_id uuid;
        BEGIN
            IF TG_TABLE_NAME = 'transactions' THEN
                checked_owner := CASE WHEN TG_OP = 'DELETE' THEN OLD.owner_id ELSE NEW.owner_id END;
                checked_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.id ELSE NEW.id END;
            ELSE
                checked_owner := CASE WHEN TG_OP = 'DELETE' THEN OLD.owner_id ELSE NEW.owner_id END;
                checked_id := CASE WHEN TG_OP = 'DELETE'
                    THEN OLD.transaction_id ELSE NEW.transaction_id END;
            END IF;
            SELECT * INTO tx FROM transactions
            WHERE owner_id = checked_owner AND id = checked_id;
            IF NOT FOUND OR tx.status <> 'posted' THEN
                RETURN NULL;
            END IF;
            IF tx.kind = 'reversal' THEN
                SELECT deposit_id INTO original_deposit_id FROM transactions
                WHERE owner_id = checked_owner AND id = tx.reversal_of_id;
                IF original_deposit_id IS DISTINCT FROM tx.deposit_id THEN
                    RAISE EXCEPTION 'deposit reversal must preserve the original deposit link'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            IF tx.deposit_id IS NULL THEN
                RETURN NULL;
            END IF;
            SELECT principal_account_id INTO principal_id FROM deposit_terms
            WHERE owner_id = checked_owner AND id = tx.deposit_id;
            SELECT count(*) INTO principal_posting_count FROM postings
            WHERE owner_id = checked_owner AND transaction_id = checked_id
              AND account_id = principal_id;
            IF principal_posting_count <> 1 THEN
                RAISE EXCEPTION 'deposit transaction requires exactly one principal posting'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;

        CREATE CONSTRAINT TRIGGER trg_transactions_deposit_integrity
        AFTER INSERT OR UPDATE ON transactions
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION assert_deposit_transaction_integrity();

        CREATE CONSTRAINT TRIGGER trg_postings_deposit_integrity
        AFTER INSERT OR UPDATE OR DELETE ON postings
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION assert_deposit_transaction_integrity();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_postings_deposit_integrity ON postings")
    op.execute("DROP TRIGGER trg_transactions_deposit_integrity ON transactions")
    op.execute("DROP FUNCTION assert_deposit_transaction_integrity()")
    op.execute("DROP TRIGGER trg_deposit_rate_periods_append_only ON deposit_rate_periods")
    op.execute("DROP TRIGGER trg_deposit_terms_append_only ON deposit_terms")
    _replace_transaction_guard(include_deposit=False)
    op.drop_constraint("ck_transactions_transaction_deposit_shape", "transactions", type_="check")
    op.drop_constraint("ck_transactions_transaction_shape", "transactions", type_="check")
    op.drop_constraint("ck_transactions_transaction_kind", "transactions", type_="check")
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
    op.drop_constraint(
        "fk_transactions_owner_id_deposit_id_deposit_terms", "transactions", type_="foreignkey"
    )
    op.drop_column("transactions", "deposit_id")
    op.drop_index("ix_deposit_rate_periods_owner_id_deposit_id", table_name="deposit_rate_periods")
    op.drop_table("deposit_rate_periods")
    op.drop_index("ix_deposit_terms_owner_id_opened_on", table_name="deposit_terms")
    op.drop_table("deposit_terms")


def _replace_transaction_guard(*, include_deposit: bool) -> None:
    deposit_clause = (
        "AND NEW.deposit_id IS NOT DISTINCT FROM OLD.deposit_id" if include_deposit else ""
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION guard_transaction_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.status = 'posted' THEN
                    RAISE EXCEPTION 'posted transaction is immutable' USING ERRCODE = '55000';
                END IF;
                RETURN OLD;
            END IF;
            IF OLD.status = 'posted' THEN
                RAISE EXCEPTION 'posted transaction is immutable' USING ERRCODE = '55000';
            END IF;
            IF NOT (
                OLD.status = 'pending' AND NEW.status = 'posted'
                AND NEW.id IS NOT DISTINCT FROM OLD.id
                AND NEW.owner_id IS NOT DISTINCT FROM OLD.owner_id
                AND NEW.actor_id IS NOT DISTINCT FROM OLD.actor_id
                AND NEW.request_id IS NOT DISTINCT FROM OLD.request_id
                AND NEW.category_id IS NOT DISTINCT FROM OLD.category_id
                AND NEW.reversal_of_id IS NOT DISTINCT FROM OLD.reversal_of_id
                {deposit_clause}
                AND NEW.kind IS NOT DISTINCT FROM OLD.kind
                AND NEW.currency IS NOT DISTINCT FROM OLD.currency
                AND NEW.description IS NOT DISTINCT FROM OLD.description
                AND NEW.occurred_at IS NOT DISTINCT FROM OLD.occurred_at
                AND NEW.version IS NOT DISTINCT FROM OLD.version
                AND NEW.created_at IS NOT DISTINCT FROM OLD.created_at
            ) THEN
                RAISE EXCEPTION 'only pending-to-posted transition is allowed'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
