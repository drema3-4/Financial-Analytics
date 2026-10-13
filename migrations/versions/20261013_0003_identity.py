"""Add secure identity, sessions, allowlist, invitations, and email tokens.

Revision ID: 20261013_0003
Revises: 20261013_0002
Create Date: 2026-10-13 03:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261013_0003"
down_revision: str | None = "20261013_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("status", sa.String(16), server_default="active", nullable=False)
    )
    op.add_column(
        "users", sa.Column("is_master", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.add_column(
        "users",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_check_constraint("ck_users_user_status", "users", "status IN ('active', 'disabled')")
    op.create_index(
        "uq_users_single_master",
        "users",
        ["is_master"],
        unique=True,
        postgresql_where=sa.text("is_master"),
    )

    op.create_table(
        "user_profiles",
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("base_currency", sa.String(3), nullable=False),
        sa.Column("locale", sa.String(16), nullable=False),
        sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "base_currency ~ '^[A-Z]{3}$'", name="ck_user_profiles_profile_base_currency"
        ),
        sa.CheckConstraint(
            "char_length(locale) BETWEEN 2 AND 6", name="ck_user_profiles_profile_locale"
        ),
        sa.CheckConstraint(
            "char_length(timezone) BETWEEN 1 AND 100",
            name="ck_user_profiles_profile_timezone",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_profiles_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_user_profiles"),
    )

    op.create_table(
        "credentials",
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "email = lower(email)", name="ck_credentials_credential_email_normalized"
        ),
        sa.CheckConstraint(
            "char_length(password_hash) > 20",
            name="ck_credentials_credential_password_hash",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_credentials_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_credentials"),
        sa.UniqueConstraint("email", name="uq_credentials_email"),
    )

    op.create_table(
        "sessions",
        sa.Column("id", UUID, nullable=False),
        sa.Column("owner_id", UUID, nullable=False),
        sa.Column("access_hash", sa.String(64), nullable=False),
        sa.Column("refresh_hash", sa.String(64), nullable=False),
        sa.Column("csrf_hash", sa.String(64), nullable=False),
        sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("char_length(access_hash) = 64", name="ck_sessions_session_access_hash"),
        sa.CheckConstraint(
            "char_length(refresh_hash) = 64", name="ck_sessions_session_refresh_hash"
        ),
        sa.CheckConstraint("char_length(csrf_hash) = 64", name="ck_sessions_session_csrf_hash"),
        sa.CheckConstraint(
            "access_expires_at <= refresh_expires_at", name="ck_sessions_session_expiry_order"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name="fk_sessions_owner_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
        sa.UniqueConstraint("refresh_hash", name="uq_sessions_refresh_hash"),
    )
    op.create_index("ix_sessions_owner_id_revoked_at", "sessions", ["owner_id", "revoked_at"])
    op.create_index("ix_sessions_refresh_expires_at", "sessions", ["refresh_expires_at"])

    op.create_table(
        "email_allowlist",
        sa.Column("id", UUID, nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("added_by", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "email = lower(email)", name="ck_email_allowlist_allowlist_email_normalized"
        ),
        sa.ForeignKeyConstraint(
            ["added_by"],
            ["users.id"],
            name="fk_email_allowlist_added_by_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_email_allowlist"),
        sa.UniqueConstraint("email", name="uq_email_allowlist_email"),
    )
    op.create_index(
        "ix_email_allowlist_active",
        "email_allowlist",
        ["email"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.create_table(
        "invitations",
        sa.Column("id", UUID, nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("invited_by", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "email = lower(email)", name="ck_invitations_invitation_email_normalized"
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_invitations_invitation_expiry"),
        sa.ForeignKeyConstraint(
            ["invited_by"],
            ["users.id"],
            name="fk_invitations_invited_by_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_invitations"),
    )
    op.create_index("ix_invitations_email_created_at", "invitations", ["email", "created_at"])

    op.create_table(
        "email_tokens",
        sa.Column("id", UUID, nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("user_id", UUID),
        sa.Column("invitation_id", UUID),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "purpose IN ('invitation', 'verify_email', 'reset_password')",
            name="ck_email_tokens_email_token_purpose",
        ),
        sa.CheckConstraint("char_length(token_hash) = 64", name="ck_email_tokens_email_token_hash"),
        sa.CheckConstraint(
            "(user_id IS NULL) <> (invitation_id IS NULL)",
            name="ck_email_tokens_email_token_single_subject",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_email_tokens_email_token_expiry"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_email_tokens_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["invitation_id"],
            ["invitations.id"],
            name="fk_email_tokens_invitation_id_invitations",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_email_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_email_tokens_token_hash"),
    )
    op.create_index("ix_email_tokens_expires_at", "email_tokens", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_email_tokens_expires_at", table_name="email_tokens")
    op.drop_table("email_tokens")
    op.drop_index("ix_invitations_email_created_at", table_name="invitations")
    op.drop_table("invitations")
    op.drop_index("ix_email_allowlist_active", table_name="email_allowlist")
    op.drop_table("email_allowlist")
    op.drop_index("ix_sessions_refresh_expires_at", table_name="sessions")
    op.drop_index("ix_sessions_owner_id_revoked_at", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("credentials")
    op.drop_table("user_profiles")
    op.drop_index("uq_users_single_master", table_name="users")
    op.drop_constraint("ck_users_user_status", "users", type_="check")
    op.drop_column("users", "updated_at")
    op.drop_column("users", "is_master")
    op.drop_column("users", "status")
