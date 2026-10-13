from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from financial_analytics_infra.database import Base

MONEY_PRECISION = 38
MONEY_SCALE = 9


class UserModel(Base):
    """Identity root shared by authentication and tenant-owned data."""

    __table_args__ = (
        CheckConstraint("status IN ('active', 'disabled')", name="user_status"),
        Index(
            "uq_users_single_master",
            "is_master",
            unique=True,
            postgresql_where=text("is_master"),
        ),
    )

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'active'"))
    is_master: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class UserProfileModel(Base):
    __tablename__ = "user_profiles"
    __table_args__ = (
        CheckConstraint("base_currency ~ '^[A-Z]{3}$'", name="profile_base_currency"),
        CheckConstraint("char_length(locale) BETWEEN 2 AND 6", name="profile_locale"),
        CheckConstraint("char_length(timezone) BETWEEN 1 AND 100", name="profile_timezone"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CredentialModel(Base):
    __tablename__ = "credentials"
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="credential_email_normalized"),
        CheckConstraint("char_length(password_hash) > 20", name="credential_password_hash"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SessionModel(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("char_length(access_hash) = 64", name="session_access_hash"),
        CheckConstraint("char_length(refresh_hash) = 64", name="session_refresh_hash"),
        CheckConstraint("char_length(csrf_hash) = 64", name="session_csrf_hash"),
        CheckConstraint("access_expires_at <= refresh_expires_at", name="session_expiry_order"),
        Index("ix_sessions_owner_id_revoked_at", "owner_id", "revoked_at"),
        Index("ix_sessions_refresh_expires_at", "refresh_expires_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    access_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    refresh_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    access_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    refresh_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rotated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailAllowlistModel(Base):
    __tablename__ = "email_allowlist"
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="allowlist_email_normalized"),
        Index("ix_email_allowlist_active", "email", postgresql_where=text("revoked_at IS NULL")),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    added_by: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InvitationModel(Base):
    __tablename__ = "invitations"
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="invitation_email_normalized"),
        CheckConstraint("expires_at > created_at", name="invitation_expiry"),
        Index("ix_invitations_email_created_at", "email", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    invited_by: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailTokenModel(Base):
    __tablename__ = "email_tokens"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('invitation', 'verify_email', 'reset_password')",
            name="email_token_purpose",
        ),
        CheckConstraint("char_length(token_hash) = 64", name="email_token_hash"),
        CheckConstraint(
            "(user_id IS NULL) <> (invitation_id IS NULL)", name="email_token_single_subject"
        ),
        CheckConstraint("expires_at > created_at", name="email_token_expiry"),
        Index("ix_email_tokens_expires_at", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    invitation_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("invitations.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AccountModel(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("owner_id", "id", name="uq_accounts_owner_id_id"),
        UniqueConstraint("owner_id", "id", "currency", name="uq_accounts_owner_id_id_currency"),
        CheckConstraint(
            "kind IN ('cash', 'bank', 'savings', 'deposit', 'other_asset', "
            "'system_income', 'system_expense', 'system_equity')",
            name="account_kind",
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="account_currency"),
        CheckConstraint("char_length(btrim(name)) > 0", name="account_name"),
        CheckConstraint("version > 0", name="account_version"),
        Index("ix_accounts_owner_id_archived", "owner_id", "archived"),
        Index(
            "uq_accounts_owner_system_kind_currency",
            "owner_id",
            "kind",
            "currency",
            unique=True,
            postgresql_where=text("kind IN ('system_income', 'system_expense', 'system_equity')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __mapper_args__ = {"version_id_col": version}


class DepositTermsModel(Base):
    __tablename__ = "deposit_terms"
    __table_args__ = (
        UniqueConstraint("owner_id", "id", name="uq_deposit_terms_owner_id_id"),
        ForeignKeyConstraint(
            ["owner_id", "principal_account_id", "currency"],
            ["accounts.owner_id", "accounts.id", "accounts.currency"],
            name="fk_deposit_terms_owner_account_currency_accounts",
            ondelete="RESTRICT",
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="deposit_terms_currency"),
        CheckConstraint("matures_on > opened_on", name="deposit_terms_date_order"),
        CheckConstraint(
            "capitalization_frequency IN ('daily', 'monthly_calendar_end')",
            name="deposit_terms_capitalization_frequency",
        ),
        CheckConstraint(
            "day_count_convention IN ('actual_365_fixed', 'actual_actual_isda')",
            name="deposit_terms_day_count_convention",
        ),
        CheckConstraint(
            "rounding_policy IN ('half_even', 'half_up')",
            name="deposit_terms_rounding_policy",
        ),
        CheckConstraint(
            "interest_rounding_frequency IN ('daily', 'capitalization')",
            name="deposit_terms_interest_rounding_frequency",
        ),
        CheckConstraint(
            "early_close_policy IN ('forbid', 'forfeit_interest', 'reprice')",
            name="deposit_terms_early_close_policy",
        ),
        CheckConstraint(
            "(early_close_policy = 'reprice') = (early_close_rate IS NOT NULL)",
            name="deposit_terms_early_close_rate_shape",
        ),
        CheckConstraint("early_close_rate >= 0", name="deposit_terms_early_close_rate"),
        CheckConstraint("tax_rate >= 0 AND tax_rate < 1", name="deposit_terms_tax_rate"),
        CheckConstraint("char_length(timezone) BETWEEN 1 AND 100", name="deposit_terms_timezone"),
        CheckConstraint(
            "algorithm_version = 'deposit-interest-v1'",
            name="deposit_terms_algorithm_version",
        ),
        Index("ix_deposit_terms_owner_id_opened_on", "owner_id", "opened_on"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    principal_account_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    opened_on: Mapped[date] = mapped_column(Date, nullable=False)
    matures_on: Mapped[date] = mapped_column(Date, nullable=False)
    capitalization_frequency: Mapped[str] = mapped_column(String(32), nullable=False)
    day_count_convention: Mapped[str] = mapped_column(String(32), nullable=False)
    rounding_policy: Mapped[str] = mapped_column(String(16), nullable=False)
    interest_rounding_frequency: Mapped[str] = mapped_column(String(24), nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False)
    cashflow_cutoff_time: Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    cashflow_cutoff_inclusive: Mapped[bool] = mapped_column(Boolean, nullable=False)
    early_close_policy: Mapped[str] = mapped_column(String(24), nullable=False)
    early_close_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 12))
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(20, 12), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class DepositRatePeriodModel(Base):
    __tablename__ = "deposit_rate_periods"
    __table_args__ = (
        PrimaryKeyConstraint("owner_id", "deposit_id", "starts_on"),
        ForeignKeyConstraint(
            ["owner_id", "deposit_id"],
            ["deposit_terms.owner_id", "deposit_terms.id"],
            name="fk_deposit_rate_periods_owner_deposit_deposit_terms",
            ondelete="RESTRICT",
        ),
        CheckConstraint("ends_on > starts_on", name="deposit_rate_periods_date_order"),
        CheckConstraint("nominal_rate >= 0", name="deposit_rate_periods_nominal_rate"),
        Index("ix_deposit_rate_periods_owner_id_deposit_id", "owner_id", "deposit_id"),
    )

    owner_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    deposit_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    nominal_rate: Mapped[Decimal] = mapped_column(Numeric(20, 12), nullable=False)


class CategoryGroupModel(Base):
    __tablename__ = "category_groups"
    __table_args__ = (
        UniqueConstraint("owner_id", "id", name="uq_category_groups_owner_id_id"),
        UniqueConstraint("owner_id", "name", name="uq_category_groups_owner_id_name"),
        ForeignKeyConstraint(
            ["owner_id", "parent_id"],
            ["category_groups.owner_id", "category_groups.id"],
            name="fk_category_groups_owner_id_parent_id_category_groups",
            ondelete="RESTRICT",
        ),
        CheckConstraint("char_length(btrim(name)) > 0", name="category_group_name"),
        CheckConstraint("id <> parent_id", name="category_group_not_self"),
        CheckConstraint("version > 0", name="category_group_version"),
        Index("ix_category_groups_owner_id", "owner_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    parent_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __mapper_args__ = {"version_id_col": version}


class CategoryModel(Base):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("owner_id", "id", name="uq_categories_owner_id_id"),
        UniqueConstraint("owner_id", "kind", "name", name="uq_categories_owner_kind_name"),
        ForeignKeyConstraint(
            ["owner_id", "group_id"],
            ["category_groups.owner_id", "category_groups.id"],
            name="fk_categories_owner_id_group_id_category_groups",
            ondelete="RESTRICT",
        ),
        CheckConstraint("kind IN ('income', 'expense')", name="category_kind"),
        CheckConstraint("char_length(btrim(name)) > 0", name="category_name"),
        CheckConstraint("version > 0", name="category_version"),
        Index("ix_categories_owner_id_kind", "owner_id", "kind"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    group_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __mapper_args__ = {"version_id_col": version}


class TagModel(Base):
    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("owner_id", "id", name="uq_tags_owner_id_id"),
        UniqueConstraint("owner_id", "name", name="uq_tags_owner_id_name"),
        CheckConstraint("char_length(btrim(name)) > 0", name="tag_name"),
        CheckConstraint("version > 0", name="tag_version"),
        Index("ix_tags_owner_id", "owner_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __mapper_args__ = {"version_id_col": version}


class TransactionModel(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("owner_id", "id", name="uq_transactions_owner_id_id"),
        UniqueConstraint("owner_id", "id", "currency", name="uq_transactions_owner_id_id_currency"),
        UniqueConstraint(
            "owner_id", "reversal_of_id", name="uq_transactions_owner_id_reversal_of_id"
        ),
        ForeignKeyConstraint(
            ["owner_id", "category_id"],
            ["categories.owner_id", "categories.id"],
            name="fk_transactions_owner_id_category_id_categories",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "reversal_of_id"],
            ["transactions.owner_id", "transactions.id"],
            name="fk_transactions_owner_id_reversal_of_id_transactions",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "deposit_id"],
            ["deposit_terms.owner_id", "deposit_terms.id"],
            name="fk_transactions_owner_id_deposit_id_deposit_terms",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "kind IN ('income', 'expense', 'transfer', 'adjustment', 'interest', 'reversal')",
            name="transaction_kind",
        ),
        CheckConstraint("status IN ('pending', 'posted')", name="transaction_status"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="transaction_currency"),
        CheckConstraint("char_length(btrim(source)) BETWEEN 1 AND 32", name="transaction_source"),
        CheckConstraint(
            "(kind IN ('income', 'expense') AND category_id IS NOT NULL "
            "AND reversal_of_id IS NULL) OR "
            "(kind IN ('transfer', 'adjustment', 'interest') AND category_id IS NULL "
            "AND reversal_of_id IS NULL) OR "
            "(kind = 'reversal' AND category_id IS NULL AND reversal_of_id IS NOT NULL)",
            name="transaction_shape",
        ),
        CheckConstraint(
            "(kind = 'interest' AND deposit_id IS NOT NULL AND source = 'deposit_interest') OR "
            "(kind = 'transfer' AND ((deposit_id IS NULL AND source <> 'deposit_cashflow') OR "
            "(deposit_id IS NOT NULL AND source = 'deposit_cashflow'))) OR "
            "(kind = 'reversal') OR "
            "(kind IN ('income', 'expense', 'adjustment') AND deposit_id IS NULL)",
            name="transaction_deposit_shape",
        ),
        CheckConstraint("version > 0", name="transaction_version"),
        Index(
            "ix_transactions_owner_id_occurred_at_id",
            "owner_id",
            "occurred_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    actor_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    request_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    category_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    reversal_of_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    deposit_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    source: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'manual'"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class PostingModel(Base):
    __tablename__ = "postings"
    __table_args__ = (
        UniqueConstraint("owner_id", "id", name="uq_postings_owner_id_id"),
        UniqueConstraint(
            "owner_id", "transaction_id", "line_no", name="uq_postings_transaction_line"
        ),
        UniqueConstraint("owner_id", "reversal_of_id", name="uq_postings_owner_id_reversal_of_id"),
        ForeignKeyConstraint(
            ["owner_id", "transaction_id", "currency"],
            ["transactions.owner_id", "transactions.id", "transactions.currency"],
            name="fk_postings_owner_transaction_currency_transactions",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "currency"],
            ["accounts.owner_id", "accounts.id", "accounts.currency"],
            name="fk_postings_owner_account_currency_accounts",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "reversal_of_id"],
            ["postings.owner_id", "postings.id"],
            name="fk_postings_owner_reversal_postings",
            ondelete="RESTRICT",
        ),
        CheckConstraint("amount <> 0", name="posting_non_zero"),
        CheckConstraint("line_no >= 1", name="posting_line_number"),
        Index("ix_postings_owner_id_account_id", "owner_id", "account_id"),
        Index("ix_postings_owner_id_transaction_id", "owner_id", "transaction_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    transaction_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    account_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    reversal_of_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(MONEY_PRECISION, MONEY_SCALE), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class TransactionTagModel(Base):
    __tablename__ = "transaction_tags"
    __table_args__ = (
        PrimaryKeyConstraint("owner_id", "transaction_id", "tag_id"),
        ForeignKeyConstraint(
            ["owner_id", "transaction_id"],
            ["transactions.owner_id", "transactions.id"],
            name="fk_transaction_tags_owner_transaction_transactions",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "tag_id"],
            ["tags.owner_id", "tags.id"],
            name="fk_transaction_tags_owner_tag_tags",
            ondelete="RESTRICT",
        ),
    )

    owner_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    transaction_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    tag_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))


class AuditEventModel(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint("char_length(event_type) > 0", name="audit_event_type"),
        CheckConstraint("char_length(aggregate_type) > 0", name="audit_aggregate_type"),
        Index("ix_audit_events_owner_id_occurred_at", "owner_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    actor_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    request_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class IdempotencyRecordModel(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "scope", "idempotency_key", name="uq_idempotency_owner_scope_key"
        ),
        CheckConstraint("char_length(scope) > 0", name="idempotency_scope"),
        CheckConstraint("char_length(idempotency_key) > 0", name="idempotency_key"),
        CheckConstraint("char_length(request_hash) = 64", name="idempotency_request_hash"),
        Index("ix_idempotency_records_expires_at", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    scope: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RecurringRuleModel(Base):
    __tablename__ = "recurring_rules"
    __table_args__ = (
        UniqueConstraint("owner_id", "id", name="uq_recurring_rules_owner_id_id"),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "currency"],
            ["accounts.owner_id", "accounts.id", "accounts.currency"],
            name="fk_recurring_rules_owner_account_currency_accounts",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "destination_account_id", "currency"],
            ["accounts.owner_id", "accounts.id", "accounts.currency"],
            name="fk_recurring_rules_owner_destination_currency_accounts",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "category_id"],
            ["categories.owner_id", "categories.id"],
            name="fk_recurring_rules_owner_category_categories",
            ondelete="RESTRICT",
        ),
        CheckConstraint("kind IN ('income', 'expense', 'transfer')", name="recurring_rule_kind"),
        CheckConstraint(
            "frequency IN ('daily', 'weekly', 'monthly', 'yearly')",
            name="recurring_rule_frequency",
        ),
        CheckConstraint(
            "missing_day_policy IN ('last_day', 'skip')",
            name="recurring_rule_missing_day_policy",
        ),
        CheckConstraint(
            "catch_up_policy IN ('all', 'latest')",
            name="recurring_rule_catch_up_policy",
        ),
        CheckConstraint(
            "status IN ('active', 'paused', 'completed')", name="recurring_rule_status"
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="recurring_rule_currency"),
        CheckConstraint("amount > 0", name="recurring_rule_amount"),
        CheckConstraint("char_length(timezone) BETWEEN 1 AND 100", name="recurring_rule_timezone"),
        CheckConstraint("version > 0", name="recurring_rule_version"),
        CheckConstraint("end_date IS NULL OR end_date >= starts_on", name="recurring_rule_end"),
        CheckConstraint(
            "(kind IN ('income', 'expense') AND category_id IS NOT NULL "
            "AND destination_account_id IS NULL) OR "
            "(kind = 'transfer' AND category_id IS NULL "
            "AND destination_account_id IS NOT NULL AND account_id <> destination_account_id)",
            name="recurring_rule_operation_shape",
        ),
        CheckConstraint(
            "(status = 'completed') = (next_occurrence_at IS NULL)",
            name="recurring_rule_completion_shape",
        ),
        Index("ix_recurring_rules_owner_id_status", "owner_id", "status"),
        Index(
            "ix_recurring_rules_due",
            "next_occurrence_at",
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    account_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    destination_account_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    category_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(MONEY_PRECISION, MONEY_SCALE), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    tag_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    frequency: Mapped[str] = mapped_column(String(16), nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    local_time: Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False)
    missing_day_policy: Mapped[str] = mapped_column(String(16), nullable=False)
    catch_up_policy: Mapped[str] = mapped_column(String(16), nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    next_occurrence_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __mapper_args__ = {"version_id_col": version}


class OutboxJobModel(Base):
    __tablename__ = "outbox_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "rule_id"],
            ["recurring_rules.owner_id", "recurring_rules.id"],
            name="fk_outbox_jobs_owner_rule_recurring_rules",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "transaction_id"],
            ["transactions.owner_id", "transactions.id"],
            name="fk_outbox_jobs_owner_transaction_transactions",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("dedup_key", name="uq_outbox_jobs_dedup_key"),
        CheckConstraint(
            "state IN ('pending', 'leased', 'succeeded', 'dead_letter')",
            name="outbox_job_state",
        ),
        CheckConstraint(
            "attempts >= 0 AND max_attempts > 0 AND attempts <= max_attempts",
            name="outbox_job_attempts",
        ),
        CheckConstraint("char_length(dedup_key) > 0", name="outbox_job_dedup_key"),
        CheckConstraint(
            "(state = 'leased' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) OR "
            "(state <> 'leased' AND lease_owner IS NULL AND lease_expires_at IS NULL)",
            name="outbox_job_lease_shape",
        ),
        CheckConstraint(
            "(state = 'succeeded') = (transaction_id IS NOT NULL)",
            name="outbox_job_result_shape",
        ),
        Index("ix_outbox_jobs_owner_id_state", "owner_id", "state"),
        Index("ix_outbox_jobs_claim", "state", "available_at", "lease_expires_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    rule_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    occurrence_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("5"))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(160))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    transaction_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class SchemaMetadataModel(Base):
    __tablename__ = "schema_metadata"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
