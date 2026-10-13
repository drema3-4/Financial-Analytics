"""Protect posted transaction source and tag links.

Revision ID: 20261013_0005
Revises: 20261013_0004
Create Date: 2026-10-13 15:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261013_0005"
down_revision: str | None = "20261013_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_transaction_source_mutation() RETURNS trigger AS $$
        BEGIN
            IF NEW.source IS DISTINCT FROM OLD.source THEN
                RAISE EXCEPTION 'transaction source is immutable' USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trg_transaction_source_immutable ON transactions;
        CREATE TRIGGER trg_transaction_source_immutable
        BEFORE UPDATE ON transactions
        FOR EACH ROW EXECUTE FUNCTION guard_transaction_source_mutation();

        CREATE OR REPLACE FUNCTION guard_transaction_tag_mutation() RETURNS trigger AS $$
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
                RAISE EXCEPTION 'transaction tags may only change while transaction is pending'
                    USING ERRCODE = '55000';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trg_transaction_tags_immutable ON transaction_tags;
        CREATE TRIGGER trg_transaction_tags_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON transaction_tags
        FOR EACH ROW EXECUTE FUNCTION guard_transaction_tag_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_transaction_tags_immutable ON transaction_tags")
    op.execute("DROP FUNCTION guard_transaction_tag_mutation()")
    op.execute("DROP TRIGGER trg_transaction_source_immutable ON transactions")
    op.execute("DROP FUNCTION guard_transaction_source_mutation()")
