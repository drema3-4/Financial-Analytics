from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
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
    """Identity-owned shell; credentials and sessions belong to milestone 03."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class AccountModel(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("owner_id", "id", name="uq_accounts_owner_id_id"),
        UniqueConstraint("owner_id", "id", "currency", name="uq_accounts_owner_id_id_currency"),
        CheckConstraint(
            "kind IN ('cash', 'bank', 'savings', 'deposit', 'other_asset', "
            "'system_income', 'system_expense')",
            name="account_kind",
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="account_currency"),
        CheckConstraint("char_length(btrim(name)) > 0", name="account_name"),
        CheckConstraint("version > 0", name="account_version"),
        Index("ix_accounts_owner_id_archived", "owner_id", "archived"),
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
        CheckConstraint(
            "kind IN ('income', 'expense', 'transfer', 'reversal')",
            name="transaction_kind",
        ),
        CheckConstraint("status IN ('pending', 'posted')", name="transaction_status"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="transaction_currency"),
        CheckConstraint(
            "(kind IN ('income', 'expense') AND category_id IS NOT NULL "
            "AND reversal_of_id IS NULL) OR "
            "(kind = 'transfer' AND category_id IS NULL AND reversal_of_id IS NULL) OR "
            "(kind = 'reversal' AND category_id IS NULL AND reversal_of_id IS NOT NULL)",
            name="transaction_shape",
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
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
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


class SchemaMetadataModel(Base):
    __tablename__ = "schema_metadata"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
