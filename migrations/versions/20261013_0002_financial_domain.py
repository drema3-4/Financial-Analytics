"""Establish the audited financial domain schema.

Revision ID: 20261013_0002
Revises: 20261013_0001
Create Date: 2026-10-13 02:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261013_0002"
down_revision: str | None = "20261013_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
MONEY = sa.Numeric(38, 9)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_table(
        "accounts",
        sa.Column("id", UUID, nullable=False),
        sa.Column("owner_id", UUID, nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("archived", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('cash', 'bank', 'savings', 'deposit', 'other_asset', "
            "'system_income', 'system_expense')",
            name="ck_accounts_account_kind",
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_accounts_account_currency"),
        sa.CheckConstraint("char_length(btrim(name)) > 0", name="ck_accounts_account_name"),
        sa.CheckConstraint("version > 0", name="ck_accounts_account_version"),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_accounts_owner_id_users", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_accounts"),
        sa.UniqueConstraint("owner_id", "id", name="uq_accounts_owner_id_id"),
        sa.UniqueConstraint("owner_id", "id", "currency", name="uq_accounts_owner_id_id_currency"),
    )
    op.create_index("ix_accounts_owner_id_archived", "accounts", ["owner_id", "archived"])

    op.create_table(
        "category_groups",
        sa.Column("id", UUID, nullable=False),
        sa.Column("owner_id", UUID, nullable=False),
        sa.Column("parent_id", UUID),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(btrim(name)) > 0", name="ck_category_groups_category_group_name"
        ),
        sa.CheckConstraint("id <> parent_id", name="ck_category_groups_category_group_not_self"),
        sa.CheckConstraint("version > 0", name="ck_category_groups_category_group_version"),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name="fk_category_groups_owner_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "parent_id"],
            ["category_groups.owner_id", "category_groups.id"],
            name="fk_category_groups_owner_id_parent_id_category_groups",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_category_groups"),
        sa.UniqueConstraint("owner_id", "id", name="uq_category_groups_owner_id_id"),
        sa.UniqueConstraint("owner_id", "name", name="uq_category_groups_owner_id_name"),
    )
    op.create_index("ix_category_groups_owner_id", "category_groups", ["owner_id"])

    op.create_table(
        "categories",
        sa.Column("id", UUID, nullable=False),
        sa.Column("owner_id", UUID, nullable=False),
        sa.Column("group_id", UUID),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('income', 'expense')", name="ck_categories_category_kind"),
        sa.CheckConstraint("char_length(btrim(name)) > 0", name="ck_categories_category_name"),
        sa.CheckConstraint("version > 0", name="ck_categories_category_version"),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_categories_owner_id_users", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "group_id"],
            ["category_groups.owner_id", "category_groups.id"],
            name="fk_categories_owner_id_group_id_category_groups",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_categories"),
        sa.UniqueConstraint("owner_id", "id", name="uq_categories_owner_id_id"),
        sa.UniqueConstraint("owner_id", "kind", "name", name="uq_categories_owner_kind_name"),
    )
    op.create_index("ix_categories_owner_id_kind", "categories", ["owner_id", "kind"])

    op.create_table(
        "tags",
        sa.Column("id", UUID, nullable=False),
        sa.Column("owner_id", UUID, nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("char_length(btrim(name)) > 0", name="ck_tags_tag_name"),
        sa.CheckConstraint("version > 0", name="ck_tags_tag_version"),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_tags_owner_id_users", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tags"),
        sa.UniqueConstraint("owner_id", "id", name="uq_tags_owner_id_id"),
        sa.UniqueConstraint("owner_id", "name", name="uq_tags_owner_id_name"),
    )
    op.create_index("ix_tags_owner_id", "tags", ["owner_id"])

    op.create_table(
        "transactions",
        sa.Column("id", UUID, nullable=False),
        sa.Column("owner_id", UUID, nullable=False),
        sa.Column("actor_id", UUID),
        sa.Column("request_id", UUID),
        sa.Column("category_id", UUID),
        sa.Column("reversal_of_id", UUID),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('income', 'expense', 'transfer', 'reversal')",
            name="ck_transactions_transaction_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'posted')", name="ck_transactions_transaction_status"
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_transactions_transaction_currency"),
        sa.CheckConstraint(
            "(kind IN ('income', 'expense') AND category_id IS NOT NULL "
            "AND reversal_of_id IS NULL) OR "
            "(kind = 'transfer' AND category_id IS NULL AND reversal_of_id IS NULL) OR "
            "(kind = 'reversal' AND category_id IS NULL AND reversal_of_id IS NOT NULL)",
            name="ck_transactions_transaction_shape",
        ),
        sa.CheckConstraint("version > 0", name="ck_transactions_transaction_version"),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_transactions_owner_id_users", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name="fk_transactions_actor_id_users", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "category_id"],
            ["categories.owner_id", "categories.id"],
            name="fk_transactions_owner_id_category_id_categories",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "reversal_of_id"],
            ["transactions.owner_id", "transactions.id"],
            name="fk_transactions_owner_id_reversal_of_id_transactions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_transactions"),
        sa.UniqueConstraint("owner_id", "id", name="uq_transactions_owner_id_id"),
        sa.UniqueConstraint(
            "owner_id", "id", "currency", name="uq_transactions_owner_id_id_currency"
        ),
        sa.UniqueConstraint(
            "owner_id", "reversal_of_id", name="uq_transactions_owner_id_reversal_of_id"
        ),
    )
    op.create_index(
        "ix_transactions_owner_id_occurred_at_id",
        "transactions",
        ["owner_id", "occurred_at", "id"],
    )

    op.create_table(
        "postings",
        sa.Column("id", UUID, nullable=False),
        sa.Column("owner_id", UUID, nullable=False),
        sa.Column("transaction_id", UUID, nullable=False),
        sa.Column("account_id", UUID, nullable=False),
        sa.Column("reversal_of_id", UUID),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount <> 0", name="ck_postings_posting_non_zero"),
        sa.CheckConstraint("line_no >= 1", name="ck_postings_posting_line_number"),
        sa.ForeignKeyConstraint(
            ["owner_id", "transaction_id", "currency"],
            ["transactions.owner_id", "transactions.id", "transactions.currency"],
            name="fk_postings_owner_transaction_currency_transactions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "account_id", "currency"],
            ["accounts.owner_id", "accounts.id", "accounts.currency"],
            name="fk_postings_owner_account_currency_accounts",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "reversal_of_id"],
            ["postings.owner_id", "postings.id"],
            name="fk_postings_owner_reversal_postings",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_postings"),
        sa.UniqueConstraint("owner_id", "id", name="uq_postings_owner_id_id"),
        sa.UniqueConstraint(
            "owner_id", "transaction_id", "line_no", name="uq_postings_transaction_line"
        ),
        sa.UniqueConstraint(
            "owner_id", "reversal_of_id", name="uq_postings_owner_id_reversal_of_id"
        ),
    )
    op.create_index("ix_postings_owner_id_account_id", "postings", ["owner_id", "account_id"])
    op.create_index(
        "ix_postings_owner_id_transaction_id", "postings", ["owner_id", "transaction_id"]
    )

    op.create_table(
        "transaction_tags",
        sa.Column("owner_id", UUID, nullable=False),
        sa.Column("transaction_id", UUID, nullable=False),
        sa.Column("tag_id", UUID, nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id", "transaction_id"],
            ["transactions.owner_id", "transactions.id"],
            name="fk_transaction_tags_owner_transaction_transactions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "tag_id"],
            ["tags.owner_id", "tags.id"],
            name="fk_transaction_tags_owner_tag_tags",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("owner_id", "transaction_id", "tag_id", name="pk_transaction_tags"),
    )

    op.create_table(
        "audit_events",
        sa.Column("id", UUID, nullable=False),
        sa.Column("owner_id", UUID, nullable=False),
        sa.Column("actor_id", UUID, nullable=False),
        sa.Column("request_id", UUID),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("aggregate_type", sa.String(80), nullable=False),
        sa.Column("aggregate_id", UUID, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.CheckConstraint("char_length(event_type) > 0", name="ck_audit_events_audit_event_type"),
        sa.CheckConstraint(
            "char_length(aggregate_type) > 0", name="ck_audit_events_audit_aggregate_type"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_audit_events_owner_id_users", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name="fk_audit_events_actor_id_users", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
    )
    op.create_index(
        "ix_audit_events_owner_id_occurred_at", "audit_events", ["owner_id", "occurred_at"]
    )

    op.create_table(
        "idempotency_records",
        sa.Column("id", UUID, nullable=False),
        sa.Column("owner_id", UUID, nullable=False),
        sa.Column("scope", sa.String(120), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(80), nullable=False),
        sa.Column("resource_id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "char_length(scope) > 0", name="ck_idempotency_records_idempotency_scope"
        ),
        sa.CheckConstraint(
            "char_length(idempotency_key) > 0", name="ck_idempotency_records_idempotency_key"
        ),
        sa.CheckConstraint(
            "char_length(request_hash) = 64", name="ck_idempotency_records_idempotency_request_hash"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name="fk_idempotency_records_owner_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_idempotency_records"),
        sa.UniqueConstraint(
            "owner_id", "scope", "idempotency_key", name="uq_idempotency_owner_scope_key"
        ),
    )
    op.create_index("ix_idempotency_records_expires_at", "idempotency_records", ["expires_at"])

    op.create_table(
        "schema_metadata",
        sa.Column("key", sa.String(120), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key", name="pk_schema_metadata"),
    )

    _create_ledger_guards()


def _create_ledger_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION reject_append_only_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = '55000';
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_audit_events_append_only
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();

        CREATE TRIGGER trg_idempotency_records_append_only
        BEFORE UPDATE OR DELETE ON idempotency_records
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();

        CREATE FUNCTION guard_transaction_mutation() RETURNS trigger AS $$
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

        CREATE TRIGGER trg_transactions_immutable
        BEFORE UPDATE OR DELETE ON transactions
        FOR EACH ROW EXECUTE FUNCTION guard_transaction_mutation();

        CREATE FUNCTION guard_posting_mutation() RETURNS trigger AS $$
        DECLARE parent_status text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                SELECT status INTO parent_status FROM transactions
                WHERE owner_id = OLD.owner_id AND id = OLD.transaction_id;
            ELSE
                SELECT status INTO parent_status FROM transactions
                WHERE owner_id = NEW.owner_id AND id = NEW.transaction_id;
            END IF;
            IF parent_status IS DISTINCT FROM 'pending' THEN
                RAISE EXCEPTION 'postings may only change while transaction is pending'
                    USING ERRCODE = '55000';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_postings_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON postings
        FOR EACH ROW EXECUTE FUNCTION guard_posting_mutation();

        CREATE FUNCTION assert_transaction_integrity() RETURNS trigger AS $$
        DECLARE
            checked_owner uuid;
            checked_id uuid;
            tx transactions%ROWTYPE;
            posting_count integer;
            posting_total numeric(38,9);
            invalid_count integer;
            original_count integer;
        BEGIN
            IF TG_TABLE_NAME = 'transactions' THEN
                checked_owner := CASE WHEN TG_OP = 'DELETE' THEN OLD.owner_id ELSE NEW.owner_id END;
                checked_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.id ELSE NEW.id END;
            ELSE
                checked_owner := CASE WHEN TG_OP = 'DELETE' THEN OLD.owner_id ELSE NEW.owner_id END;
                checked_id := CASE WHEN TG_OP = 'DELETE'
                    THEN OLD.transaction_id ELSE NEW.transaction_id END;
            END IF;
            SELECT * INTO tx FROM transactions WHERE owner_id = checked_owner AND id = checked_id;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;
            IF tx.status <> 'posted' THEN
                RAISE EXCEPTION 'pending transaction cannot be committed' USING ERRCODE = '23514';
            END IF;
            SELECT count(*), COALESCE(sum(amount), 0),
                   count(*) FILTER (WHERE currency <> tx.currency)
            INTO posting_count, posting_total, invalid_count
            FROM postings WHERE owner_id = checked_owner AND transaction_id = checked_id;
            IF posting_count < 2 OR posting_total <> 0 OR invalid_count <> 0 THEN
                RAISE EXCEPTION 'posted transaction must have balanced same-currency postings'
                    USING ERRCODE = '23514';
            END IF;
            IF tx.kind = 'reversal' THEN
                SELECT count(*) INTO invalid_count
                FROM transactions
                WHERE owner_id = checked_owner AND id = tx.reversal_of_id
                  AND kind <> 'reversal' AND status = 'posted';
                IF invalid_count <> 1 THEN
                    RAISE EXCEPTION 'reversal must reference a posted ordinary transaction'
                        USING ERRCODE = '23514';
                END IF;
                SELECT count(*) INTO original_count
                FROM postings
                WHERE owner_id = checked_owner AND transaction_id = tx.reversal_of_id;
                SELECT count(*) INTO invalid_count
                FROM postings reversal
                LEFT JOIN postings original
                  ON original.owner_id = reversal.owner_id
                 AND original.id = reversal.reversal_of_id
                 AND original.transaction_id = tx.reversal_of_id
                 AND original.account_id = reversal.account_id
                 AND original.currency = reversal.currency
                 AND original.amount = -reversal.amount
                WHERE reversal.owner_id = checked_owner
                  AND reversal.transaction_id = checked_id
                  AND original.id IS NULL;
                IF original_count <> posting_count OR invalid_count <> 0 THEN
                    RAISE EXCEPTION 'reversal must negate every original posting exactly once'
                        USING ERRCODE = '23514';
                END IF;
            ELSE
                SELECT count(*) INTO invalid_count FROM postings
                WHERE owner_id = checked_owner AND transaction_id = checked_id
                  AND reversal_of_id IS NOT NULL;
                IF invalid_count <> 0 THEN
                    RAISE EXCEPTION 'ordinary posting cannot reference a reversed posting'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;

        CREATE CONSTRAINT TRIGGER trg_transactions_integrity
        AFTER INSERT OR UPDATE ON transactions
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION assert_transaction_integrity();

        CREATE CONSTRAINT TRIGGER trg_postings_integrity
        AFTER INSERT OR UPDATE OR DELETE ON postings
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION assert_transaction_integrity();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_postings_integrity ON postings")
    op.execute("DROP TRIGGER trg_transactions_integrity ON transactions")
    op.execute("DROP TRIGGER trg_postings_immutable ON postings")
    op.execute("DROP TRIGGER trg_transactions_immutable ON transactions")
    op.execute("DROP TRIGGER trg_idempotency_records_append_only ON idempotency_records")
    op.execute("DROP TRIGGER trg_audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION assert_transaction_integrity()")
    op.execute("DROP FUNCTION guard_posting_mutation()")
    op.execute("DROP FUNCTION guard_transaction_mutation()")
    op.execute("DROP FUNCTION reject_append_only_mutation()")
    op.drop_table("schema_metadata")
    op.drop_index("ix_idempotency_records_expires_at", table_name="idempotency_records")
    op.drop_table("idempotency_records")
    op.drop_index("ix_audit_events_owner_id_occurred_at", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("transaction_tags")
    op.drop_index("ix_postings_owner_id_transaction_id", table_name="postings")
    op.drop_index("ix_postings_owner_id_account_id", table_name="postings")
    op.drop_table("postings")
    op.drop_index("ix_transactions_owner_id_occurred_at_id", table_name="transactions")
    op.drop_table("transactions")
    op.drop_index("ix_tags_owner_id", table_name="tags")
    op.drop_table("tags")
    op.drop_index("ix_categories_owner_id_kind", table_name="categories")
    op.drop_table("categories")
    op.drop_index("ix_category_groups_owner_id", table_name="category_groups")
    op.drop_table("category_groups")
    op.drop_index("ix_accounts_owner_id_archived", table_name="accounts")
    op.drop_table("accounts")
    op.drop_table("users")
