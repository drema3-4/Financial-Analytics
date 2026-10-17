"""Add invite-only roles, verification state, and SMTP delivery jobs.

Revision ID: 20261016_0011
Revises: 20261014_0010
Create Date: 2026-10-16 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261016_0011"
down_revision: str | None = "20261014_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("is_admin", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True)))
    op.add_column(
        "invitations",
        sa.Column("is_admin", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_table(
        "email_delivery_jobs",
        sa.Column("id", UUID, nullable=False),
        sa.Column("token_id", UUID, nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("recipient", sa.String(254), nullable=False),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("text_body", sa.Text()),
        sa.Column("state", sa.String(16), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(200)),
        sa.Column("leased_until", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(1000)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "purpose IN ('invitation', 'verify_email', 'reset_password')",
            name="ck_email_delivery_jobs_email_delivery_job_purpose",
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'leased', 'completed', 'dead_letter')",
            name="ck_email_delivery_jobs_email_delivery_job_state",
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND attempts <= 5",
            name="ck_email_delivery_jobs_email_delivery_job_attempts",
        ),
        sa.ForeignKeyConstraint(
            ["token_id"],
            ["email_tokens.id"],
            name="fk_email_delivery_jobs_token_id_email_tokens",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_email_delivery_jobs"),
        sa.UniqueConstraint("token_id", name="uq_email_delivery_jobs_token_id"),
    )
    op.create_index(
        "ix_email_delivery_jobs_claim",
        "email_delivery_jobs",
        ["state", "available_at", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_email_delivery_jobs_claim", table_name="email_delivery_jobs")
    op.drop_table("email_delivery_jobs")
    op.drop_column("invitations", "is_admin")
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "is_admin")
