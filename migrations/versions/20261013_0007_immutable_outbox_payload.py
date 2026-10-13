"""Protect outbox identity and operation snapshots.

Revision ID: 20261013_0007
Revises: 20261013_0006
Create Date: 2026-10-13 17:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261013_0007"
down_revision: str | None = "20261013_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION guard_outbox_job_identity_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'outbox jobs are append-only' USING ERRCODE = '55000';
            END IF;
            IF NEW.owner_id IS DISTINCT FROM OLD.owner_id
                OR NEW.rule_id IS DISTINCT FROM OLD.rule_id
                OR NEW.occurrence_at IS DISTINCT FROM OLD.occurrence_at
                OR NEW.dedup_key IS DISTINCT FROM OLD.dedup_key
                OR NEW.payload IS DISTINCT FROM OLD.payload
                OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'outbox job identity and payload are immutable'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_outbox_jobs_identity_immutable
        BEFORE UPDATE OR DELETE ON outbox_jobs
        FOR EACH ROW EXECUTE FUNCTION guard_outbox_job_identity_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_outbox_jobs_identity_immutable ON outbox_jobs")
    op.execute("DROP FUNCTION guard_outbox_job_identity_mutation()")
