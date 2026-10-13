"""Add recurring rules and durable outbox jobs.

Revision ID: 20261013_0006
Revises: 20261013_0005
Create Date: 2026-10-13 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261013_0006"
down_revision: str | None = "20261013_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recurring_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("destination_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("amount", sa.Numeric(38, 9), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "tag_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("frequency", sa.String(16), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("local_time", sa.Time(timezone=False), nullable=False),
        sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("missing_day_policy", sa.String(16), nullable=False),
        sa.Column("catch_up_policy", sa.String(16), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("next_occurrence_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
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
            "kind IN ('income', 'expense', 'transfer')",
            name="ck_recurring_rules_recurring_rule_kind",
        ),
        sa.CheckConstraint(
            "frequency IN ('daily', 'weekly', 'monthly', 'yearly')",
            name="ck_recurring_rules_recurring_rule_frequency",
        ),
        sa.CheckConstraint(
            "missing_day_policy IN ('last_day', 'skip')",
            name="ck_recurring_rules_recurring_rule_missing_day_policy",
        ),
        sa.CheckConstraint(
            "catch_up_policy IN ('all', 'latest')",
            name="ck_recurring_rules_recurring_rule_catch_up_policy",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'completed')",
            name="ck_recurring_rules_recurring_rule_status",
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name="ck_recurring_rules_recurring_rule_currency"
        ),
        sa.CheckConstraint("amount > 0", name="ck_recurring_rules_recurring_rule_amount"),
        sa.CheckConstraint(
            "char_length(timezone) BETWEEN 1 AND 100",
            name="ck_recurring_rules_recurring_rule_timezone",
        ),
        sa.CheckConstraint("version > 0", name="ck_recurring_rules_recurring_rule_version"),
        sa.CheckConstraint(
            "end_date IS NULL OR end_date >= starts_on",
            name="ck_recurring_rules_recurring_rule_end",
        ),
        sa.CheckConstraint(
            "(kind IN ('income', 'expense') AND category_id IS NOT NULL "
            "AND destination_account_id IS NULL) OR "
            "(kind = 'transfer' AND category_id IS NULL "
            "AND destination_account_id IS NOT NULL AND account_id <> destination_account_id)",
            name="ck_recurring_rules_recurring_rule_operation_shape",
        ),
        sa.CheckConstraint(
            "(status = 'completed') = (next_occurrence_at IS NULL)",
            name="ck_recurring_rules_recurring_rule_completion_shape",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name="fk_recurring_rules_owner_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "account_id", "currency"],
            ["accounts.owner_id", "accounts.id", "accounts.currency"],
            name="fk_recurring_rules_owner_account_currency_accounts",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "destination_account_id", "currency"],
            ["accounts.owner_id", "accounts.id", "accounts.currency"],
            name="fk_recurring_rules_owner_destination_currency_accounts",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "category_id"],
            ["categories.owner_id", "categories.id"],
            name="fk_recurring_rules_owner_category_categories",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_recurring_rules"),
        sa.UniqueConstraint("owner_id", "id", name="uq_recurring_rules_owner_id_id"),
    )
    op.create_index(
        "ix_recurring_rules_owner_id_status",
        "recurring_rules",
        ["owner_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_recurring_rules_due",
        "recurring_rules",
        ["next_occurrence_at"],
        unique=False,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "outbox_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("occurrence_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dedup_key", sa.String(200), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("5"), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(160), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
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
            "state IN ('pending', 'leased', 'succeeded', 'dead_letter')",
            name="ck_outbox_jobs_outbox_job_state",
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND max_attempts > 0 AND attempts <= max_attempts",
            name="ck_outbox_jobs_outbox_job_attempts",
        ),
        sa.CheckConstraint(
            "char_length(dedup_key) > 0", name="ck_outbox_jobs_outbox_job_dedup_key"
        ),
        sa.CheckConstraint(
            "(state = 'leased' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) OR "
            "(state <> 'leased' AND lease_owner IS NULL AND lease_expires_at IS NULL)",
            name="ck_outbox_jobs_outbox_job_lease_shape",
        ),
        sa.CheckConstraint(
            "(state = 'succeeded') = (transaction_id IS NOT NULL)",
            name="ck_outbox_jobs_outbox_job_result_shape",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name="fk_outbox_jobs_owner_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "rule_id"],
            ["recurring_rules.owner_id", "recurring_rules.id"],
            name="fk_outbox_jobs_owner_rule_recurring_rules",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "transaction_id"],
            ["transactions.owner_id", "transactions.id"],
            name="fk_outbox_jobs_owner_transaction_transactions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_jobs"),
        sa.UniqueConstraint("dedup_key", name="uq_outbox_jobs_dedup_key"),
    )
    op.create_index(
        "ix_outbox_jobs_owner_id_state",
        "outbox_jobs",
        ["owner_id", "state"],
        unique=False,
    )
    op.create_index(
        "ix_outbox_jobs_claim",
        "outbox_jobs",
        ["state", "available_at", "lease_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_jobs_claim", table_name="outbox_jobs")
    op.drop_index("ix_outbox_jobs_owner_id_state", table_name="outbox_jobs")
    op.drop_table("outbox_jobs")
    op.drop_index("ix_recurring_rules_due", table_name="recurring_rules")
    op.drop_index("ix_recurring_rules_owner_id_status", table_name="recurring_rules")
    op.drop_table("recurring_rules")
