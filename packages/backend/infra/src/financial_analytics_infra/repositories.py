from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from types import TracebackType
from uuid import UUID, uuid4

from sqlalchemy import Select, exists, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from financial_analytics_app.ports import (
    AuditEvent,
    AuditRepository,
    DepositRepository,
    IdempotencyRecord,
    IdempotencyRepository,
    LedgerRepository,
    TransactionCursor,
    TransactionQuery,
    UnitOfWork,
)
from financial_analytics_app.services import ConcurrentModificationError
from financial_analytics_domain import (
    Account,
    AccountKind,
    CapitalizationFrequency,
    Category,
    CategoryGroup,
    CategoryKind,
    Currency,
    DayCountConvention,
    DepositRatePeriod,
    DepositTerms,
    EarlyClosePolicy,
    EarlyCloseRule,
    Instant,
    InterestRoundingFrequency,
    Money,
    Posting,
    Rate,
    RoundingPolicy,
    Tag,
    Transaction,
    TransactionKind,
)
from financial_analytics_domain.errors import OwnershipError
from financial_analytics_infra.models import (
    AccountModel,
    AuditEventModel,
    CategoryGroupModel,
    CategoryModel,
    DepositRatePeriodModel,
    DepositTermsModel,
    IdempotencyRecordModel,
    PostingModel,
    TagModel,
    TransactionModel,
    TransactionTagModel,
)


class PostgresLedgerRepository:
    """PostgreSQL adapter whose constructor makes owner scope mandatory."""

    def __init__(self, session: Session, owner_id: UUID) -> None:
        self._session = session
        self._owner_id = owner_id

    @property
    def owner_id(self) -> UUID:
        return self._owner_id

    def _require_owner(self, entity_owner_id: UUID) -> None:
        if entity_owner_id != self._owner_id:
            raise OwnershipError("repository scope does not match entity owner")

    def add_account(self, account: Account) -> None:
        self._require_owner(account.owner_id)
        self._session.add(
            AccountModel(
                id=account.id,
                owner_id=account.owner_id,
                name=account.name,
                kind=account.kind.value,
                currency=account.currency.code,
                archived=account.archived,
                version=account.version,
            )
        )

    def get_account(self, account_id: UUID) -> Account | None:
        row = self._session.scalar(
            select(AccountModel).where(
                AccountModel.owner_id == self._owner_id, AccountModel.id == account_id
            )
        )
        return None if row is None else _account_from_row(row)

    def save_account(self, account: Account) -> Account:
        self._require_owner(account.owner_id)
        new_version = account.version + 1
        changed_id = self._session.scalar(
            update(AccountModel)
            .where(
                AccountModel.owner_id == self._owner_id,
                AccountModel.id == account.id,
                AccountModel.version == account.version,
            )
            .values(
                name=account.name,
                kind=account.kind.value,
                currency=account.currency.code,
                archived=account.archived,
                version=new_version,
                updated_at=func.now(),
            )
            .returning(AccountModel.id)
        )
        if changed_id is None:
            raise ConcurrentModificationError("account version is stale or account is absent")
        return Account(
            id=account.id,
            owner_id=account.owner_id,
            name=account.name,
            currency=account.currency,
            kind=account.kind,
            archived=account.archived,
            version=new_version,
        )

    def list_accounts(self, *, include_archived: bool = False) -> tuple[Account, ...]:
        query = select(AccountModel).where(
            AccountModel.owner_id == self._owner_id,
            AccountModel.kind.not_in(
                (
                    AccountKind.SYSTEM_INCOME.value,
                    AccountKind.SYSTEM_EXPENSE.value,
                    AccountKind.SYSTEM_EQUITY.value,
                )
            ),
        )
        if not include_archived:
            query = query.where(AccountModel.archived.is_(False))
        query = query.order_by(AccountModel.name, AccountModel.id)
        return tuple(_account_from_row(row) for row in self._session.scalars(query))

    def get_or_create_system_account(
        self, kind: AccountKind, currency: Currency
    ) -> tuple[Account, bool]:
        if kind.is_asset:
            raise ValueError("system account kind is required")
        account_id = uuid4()
        statement = (
            postgresql_insert(AccountModel)
            .values(
                id=account_id,
                owner_id=self._owner_id,
                name=f"System {kind.value.removeprefix('system_')} ({currency.code})",
                kind=kind.value,
                currency=currency.code,
                archived=False,
                version=1,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    AccountModel.owner_id,
                    AccountModel.kind,
                    AccountModel.currency,
                ],
                index_where=AccountModel.kind.in_(
                    (
                        AccountKind.SYSTEM_INCOME.value,
                        AccountKind.SYSTEM_EXPENSE.value,
                        AccountKind.SYSTEM_EQUITY.value,
                    )
                ),
            )
            .returning(AccountModel.id)
        )
        created_id = self._session.scalar(statement)
        row = self._session.scalar(
            select(AccountModel).where(
                AccountModel.owner_id == self._owner_id,
                AccountModel.kind == kind.value,
                AccountModel.currency == currency.code,
            )
        )
        if row is None:
            raise RuntimeError("system account upsert did not return an account")
        return _account_from_row(row), created_id is not None

    def add_category_group(self, group: CategoryGroup) -> None:
        self._require_owner(group.owner_id)
        self._session.add(
            CategoryGroupModel(
                id=group.id,
                owner_id=group.owner_id,
                parent_id=group.parent_id,
                name=group.name,
                version=group.version,
            )
        )

    def get_category_group(self, group_id: UUID) -> CategoryGroup | None:
        row = self._session.scalar(
            select(CategoryGroupModel).where(
                CategoryGroupModel.owner_id == self._owner_id,
                CategoryGroupModel.id == group_id,
            )
        )
        return None if row is None else _category_group_from_row(row)

    def list_category_groups(self) -> tuple[CategoryGroup, ...]:
        rows = self._session.scalars(
            select(CategoryGroupModel)
            .where(CategoryGroupModel.owner_id == self._owner_id)
            .order_by(CategoryGroupModel.name, CategoryGroupModel.id)
        )
        return tuple(_category_group_from_row(row) for row in rows)

    def save_category_group(self, group: CategoryGroup) -> CategoryGroup:
        self._require_owner(group.owner_id)
        new_version = group.version + 1
        changed_id = self._session.scalar(
            update(CategoryGroupModel)
            .where(
                CategoryGroupModel.owner_id == self._owner_id,
                CategoryGroupModel.id == group.id,
                CategoryGroupModel.version == group.version,
            )
            .values(name=group.name, parent_id=group.parent_id, version=new_version)
            .returning(CategoryGroupModel.id)
        )
        if changed_id is None:
            raise ConcurrentModificationError("category group version is stale or absent")
        return CategoryGroup(
            id=group.id,
            owner_id=group.owner_id,
            name=group.name,
            parent_id=group.parent_id,
            version=new_version,
        )

    def add_category(self, category: Category) -> None:
        self._require_owner(category.owner_id)
        self._session.add(
            CategoryModel(
                id=category.id,
                owner_id=category.owner_id,
                group_id=category.group_id,
                name=category.name,
                kind=category.kind.value,
                version=category.version,
            )
        )

    def get_category(self, category_id: UUID) -> Category | None:
        row = self._session.scalar(
            select(CategoryModel).where(
                CategoryModel.owner_id == self._owner_id,
                CategoryModel.id == category_id,
            )
        )
        return None if row is None else _category_from_row(row)

    def list_categories(self) -> tuple[Category, ...]:
        rows = self._session.scalars(
            select(CategoryModel)
            .where(CategoryModel.owner_id == self._owner_id)
            .order_by(CategoryModel.kind, CategoryModel.name, CategoryModel.id)
        )
        return tuple(_category_from_row(row) for row in rows)

    def save_category(self, category: Category) -> Category:
        self._require_owner(category.owner_id)
        new_version = category.version + 1
        changed_id = self._session.scalar(
            update(CategoryModel)
            .where(
                CategoryModel.owner_id == self._owner_id,
                CategoryModel.id == category.id,
                CategoryModel.version == category.version,
            )
            .values(
                name=category.name,
                kind=category.kind.value,
                group_id=category.group_id,
                version=new_version,
            )
            .returning(CategoryModel.id)
        )
        if changed_id is None:
            raise ConcurrentModificationError("category version is stale or absent")
        return Category(
            id=category.id,
            owner_id=category.owner_id,
            name=category.name,
            kind=category.kind,
            group_id=category.group_id,
            version=new_version,
        )

    def add_tag(self, tag: Tag) -> None:
        self._require_owner(tag.owner_id)
        self._session.add(
            TagModel(
                id=tag.id,
                owner_id=tag.owner_id,
                name=tag.name,
                version=tag.version,
            )
        )

    def get_tag(self, tag_id: UUID) -> Tag | None:
        row = self._session.scalar(
            select(TagModel).where(TagModel.owner_id == self._owner_id, TagModel.id == tag_id)
        )
        return None if row is None else _tag_from_row(row)

    def list_tags(self) -> tuple[Tag, ...]:
        rows = self._session.scalars(
            select(TagModel)
            .where(TagModel.owner_id == self._owner_id)
            .order_by(TagModel.name, TagModel.id)
        )
        return tuple(_tag_from_row(row) for row in rows)

    def add_transaction(
        self,
        transaction: Transaction,
        *,
        actor_id: UUID,
        request_id: UUID | None,
    ) -> None:
        self._require_owner(transaction.owner_id)
        if actor_id != self._owner_id:
            raise OwnershipError("transaction actor is outside repository scope")
        row = TransactionModel(
            id=transaction.id,
            owner_id=transaction.owner_id,
            actor_id=actor_id,
            request_id=request_id,
            category_id=transaction.category_id,
            reversal_of_id=transaction.reversal_of_id,
            deposit_id=transaction.deposit_id,
            kind=transaction.kind.value,
            status="pending",
            currency=transaction.currency.code,
            description=transaction.description,
            source=transaction.source,
            occurred_at=transaction.occurred_at.value,
            version=transaction.version,
        )
        self._session.add(row)
        self._session.flush()
        self._session.add_all(
            [
                PostingModel(
                    id=posting.id,
                    owner_id=transaction.owner_id,
                    transaction_id=transaction.id,
                    account_id=posting.account_id,
                    reversal_of_id=posting.reversal_of_id,
                    line_no=line_no,
                    currency=posting.amount.currency.code,
                    amount=posting.amount.amount,
                )
                for line_no, posting in enumerate(transaction.postings, start=1)
            ]
        )
        self._session.flush()
        self._session.add_all(
            [
                TransactionTagModel(
                    owner_id=transaction.owner_id,
                    transaction_id=transaction.id,
                    tag_id=tag_id,
                )
                for tag_id in transaction.tag_ids
            ]
        )
        self._session.flush()
        row.status = "posted"
        self._session.flush()

    def get_transaction(self, transaction_id: UUID) -> Transaction | None:
        row = self._session.scalar(self._transaction_query(transaction_id))
        if row is None:
            return None
        postings = self._session.scalars(
            select(PostingModel)
            .where(
                PostingModel.owner_id == self._owner_id,
                PostingModel.transaction_id == transaction_id,
            )
            .order_by(PostingModel.line_no)
        ).all()
        tag_ids = tuple(
            self._session.scalars(
                select(TransactionTagModel.tag_id)
                .where(
                    TransactionTagModel.owner_id == self._owner_id,
                    TransactionTagModel.transaction_id == transaction_id,
                )
                .order_by(TransactionTagModel.tag_id)
            )
        )
        return _transaction_from_rows(row, postings, tag_ids)

    def _transaction_query(self, transaction_id: UUID) -> Select[TransactionModel]:
        return select(TransactionModel).where(
            TransactionModel.owner_id == self._owner_id,
            TransactionModel.id == transaction_id,
            TransactionModel.status == "posted",
        )

    def list_transactions(
        self,
        query: TransactionQuery,
        *,
        cursor: TransactionCursor | None,
        limit: int,
    ) -> tuple[tuple[Transaction, ...], bool, datetime]:
        snapshot_at = (
            cursor.snapshot_at
            if cursor is not None
            else self._session.scalar(select(func.clock_timestamp()))
        )
        if snapshot_at is None:
            raise RuntimeError("database did not return a pagination snapshot")
        statement = select(TransactionModel).where(
            TransactionModel.owner_id == self._owner_id,
            TransactionModel.status == "posted",
            TransactionModel.created_at <= snapshot_at,
        )
        if query.account_id is not None:
            statement = statement.where(
                exists(
                    select(PostingModel.id).where(
                        PostingModel.owner_id == TransactionModel.owner_id,
                        PostingModel.transaction_id == TransactionModel.id,
                        PostingModel.account_id == query.account_id,
                    )
                )
            )
        if query.category_id is not None:
            statement = statement.where(TransactionModel.category_id == query.category_id)
        if query.tag_id is not None:
            statement = statement.where(
                exists(
                    select(TransactionTagModel.tag_id).where(
                        TransactionTagModel.owner_id == TransactionModel.owner_id,
                        TransactionTagModel.transaction_id == TransactionModel.id,
                        TransactionTagModel.tag_id == query.tag_id,
                    )
                )
            )
        if query.kind is not None:
            statement = statement.where(TransactionModel.kind == query.kind.value)
        if query.occurred_from is not None:
            statement = statement.where(TransactionModel.occurred_at >= query.occurred_from)
        if query.occurred_to is not None:
            statement = statement.where(TransactionModel.occurred_at < query.occurred_to)
        if query.search:
            statement = statement.where(TransactionModel.description.ilike(f"%{query.search}%"))
        if cursor is not None:
            statement = statement.where(
                tuple_(TransactionModel.occurred_at, TransactionModel.id)
                < (cursor.occurred_at, cursor.transaction_id)
            )
        rows = self._session.scalars(
            statement.order_by(
                TransactionModel.occurred_at.desc(), TransactionModel.id.desc()
            ).limit(limit + 1)
        ).all()
        has_more = len(rows) > limit
        selected = rows[:limit]
        if not selected:
            return (), False, snapshot_at
        transaction_ids = [row.id for row in selected]
        posting_rows = self._session.scalars(
            select(PostingModel)
            .where(
                PostingModel.owner_id == self._owner_id,
                PostingModel.transaction_id.in_(transaction_ids),
            )
            .order_by(PostingModel.transaction_id, PostingModel.line_no)
        ).all()
        tag_rows = self._session.execute(
            select(TransactionTagModel.transaction_id, TransactionTagModel.tag_id)
            .where(
                TransactionTagModel.owner_id == self._owner_id,
                TransactionTagModel.transaction_id.in_(transaction_ids),
            )
            .order_by(TransactionTagModel.transaction_id, TransactionTagModel.tag_id)
        ).all()
        postings_by_transaction: defaultdict[UUID, list[PostingModel]] = defaultdict(list)
        for posting in posting_rows:
            postings_by_transaction[posting.transaction_id].append(posting)
        tags_by_transaction: defaultdict[UUID, list[UUID]] = defaultdict(list)
        for transaction_id, tag_id in tag_rows:
            tags_by_transaction[transaction_id].append(tag_id)
        return (
            tuple(
                _transaction_from_rows(
                    row,
                    postings_by_transaction[row.id],
                    tags_by_transaction[row.id],
                )
                for row in selected
            ),
            has_more,
            snapshot_at,
        )

    def list_postings(self, account_id: UUID | None = None) -> tuple[Posting, ...]:
        query = (
            select(PostingModel)
            .join(
                TransactionModel,
                (TransactionModel.owner_id == PostingModel.owner_id)
                & (TransactionModel.id == PostingModel.transaction_id),
            )
            .where(
                PostingModel.owner_id == self._owner_id,
                TransactionModel.status == "posted",
            )
            .order_by(PostingModel.created_at, PostingModel.line_no)
        )
        if account_id is not None:
            query = query.where(PostingModel.account_id == account_id)
        return tuple(_posting_from_row(row) for row in self._session.scalars(query))

    def list_deposit_transactions(self, deposit_id: UUID) -> tuple[Transaction, ...]:
        transaction_ids = self._session.scalars(
            select(TransactionModel.id)
            .where(
                TransactionModel.owner_id == self._owner_id,
                TransactionModel.deposit_id == deposit_id,
                TransactionModel.status == "posted",
            )
            .order_by(TransactionModel.occurred_at, TransactionModel.id)
        )
        result: list[Transaction] = []
        for transaction_id in transaction_ids:
            transaction = self.get_transaction(transaction_id)
            if transaction is None:
                raise RuntimeError("posted deposit transaction disappeared")
            result.append(transaction)
        return tuple(result)

    def rebuild_balances(self) -> dict[UUID, Money]:
        accounts = self._session.execute(
            select(AccountModel.id, AccountModel.currency).where(
                AccountModel.owner_id == self._owner_id
            )
        ).all()
        totals = dict(
            self._session.execute(
                select(PostingModel.account_id, func.sum(PostingModel.amount))
                .join(
                    TransactionModel,
                    (TransactionModel.owner_id == PostingModel.owner_id)
                    & (TransactionModel.id == PostingModel.transaction_id),
                )
                .where(
                    PostingModel.owner_id == self._owner_id,
                    TransactionModel.status == "posted",
                )
                .group_by(PostingModel.account_id)
            ).all()
        )
        return {
            account_id: Money.of(totals.get(account_id, 0), Currency(currency))
            for account_id, currency in accounts
        }


class PostgresAuditRepository:
    def __init__(self, session: Session, owner_id: UUID) -> None:
        self._session = session
        self._owner_id = owner_id

    def append(self, event: AuditEvent) -> None:
        if event.owner_id != self._owner_id:
            raise OwnershipError("audit event is outside repository scope")
        self._session.add(
            AuditEventModel(
                id=event.id,
                owner_id=event.owner_id,
                actor_id=event.actor_id,
                request_id=event.request_id,
                event_type=event.event_type,
                aggregate_type=event.aggregate_type,
                aggregate_id=event.aggregate_id,
                occurred_at=event.occurred_at.value,
                payload=event.payload or {},
            )
        )


class PostgresIdempotencyRepository:
    def __init__(self, session: Session, owner_id: UUID) -> None:
        self._session = session
        self._owner_id = owner_id

    def lock(self, scope: str, key: str) -> None:
        digest = hashlib.sha256(f"{self._owner_id}:{scope}:{key}".encode()).digest()
        lock_id = int.from_bytes(digest[:8], byteorder="big", signed=True)
        self._session.execute(select(func.pg_advisory_xact_lock(lock_id)))

    def get(self, scope: str, key: str) -> IdempotencyRecord | None:
        row = self._session.scalar(
            select(IdempotencyRecordModel).where(
                IdempotencyRecordModel.owner_id == self._owner_id,
                IdempotencyRecordModel.scope == scope,
                IdempotencyRecordModel.idempotency_key == key,
            )
        )
        if row is None:
            return None
        return IdempotencyRecord(
            owner_id=row.owner_id,
            scope=row.scope,
            key=row.idempotency_key,
            request_hash=row.request_hash,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            created_at=Instant(row.created_at),
        )

    def add(self, record: IdempotencyRecord) -> None:
        if record.owner_id != self._owner_id:
            raise OwnershipError("idempotency record is outside repository scope")
        self._session.add(
            IdempotencyRecordModel(
                id=uuid4(),
                owner_id=record.owner_id,
                scope=record.scope,
                idempotency_key=record.key,
                request_hash=record.request_hash,
                resource_type=record.resource_type,
                resource_id=record.resource_id,
                created_at=record.created_at.value,
            )
        )


class PostgresDepositRepository:
    def __init__(self, session: Session, owner_id: UUID) -> None:
        self._session = session
        self._owner_id = owner_id

    def add(self, terms: DepositTerms) -> None:
        if terms.owner_id != self._owner_id:
            raise OwnershipError("deposit is outside repository scope")
        self._session.add(
            DepositTermsModel(
                id=terms.id,
                owner_id=terms.owner_id,
                principal_account_id=terms.principal_account_id,
                currency=terms.currency.code,
                opened_on=terms.opened_on,
                matures_on=terms.matures_on,
                capitalization_frequency=terms.capitalization_frequency.value,
                day_count_convention=terms.day_count_convention.value,
                rounding_policy=terms.rounding_policy.value,
                interest_rounding_frequency=terms.interest_rounding_frequency.value,
                timezone=terms.timezone,
                cashflow_cutoff_time=terms.cashflow_cutoff_time,
                cashflow_cutoff_inclusive=terms.cashflow_cutoff_inclusive,
                early_close_policy=terms.early_close_rule.policy.value,
                early_close_rate=(
                    None
                    if terms.early_close_rule.nominal_rate is None
                    else terms.early_close_rule.nominal_rate.value
                ),
                tax_rate=terms.tax_rate.value,
                algorithm_version=terms.algorithm_version,
            )
        )
        self._session.flush()
        self._session.add_all(
            [
                DepositRatePeriodModel(
                    owner_id=terms.owner_id,
                    deposit_id=terms.id,
                    starts_on=period.starts_on,
                    ends_on=period.ends_on,
                    nominal_rate=period.nominal_rate.value,
                )
                for period in terms.rate_periods
            ]
        )

    def get(self, deposit_id: UUID) -> DepositTerms | None:
        row = self._session.scalar(
            select(DepositTermsModel).where(
                DepositTermsModel.owner_id == self._owner_id,
                DepositTermsModel.id == deposit_id,
            )
        )
        if row is None:
            return None
        periods = self._session.scalars(
            select(DepositRatePeriodModel)
            .where(
                DepositRatePeriodModel.owner_id == self._owner_id,
                DepositRatePeriodModel.deposit_id == deposit_id,
            )
            .order_by(DepositRatePeriodModel.starts_on)
        )
        return _deposit_from_rows(row, tuple(periods))

    def list(self) -> tuple[DepositTerms, ...]:
        ids = self._session.scalars(
            select(DepositTermsModel.id)
            .where(DepositTermsModel.owner_id == self._owner_id)
            .order_by(DepositTermsModel.opened_on, DepositTermsModel.id)
        )
        return tuple(terms for deposit_id in ids if (terms := self.get(deposit_id)) is not None)


class PostgresUnitOfWork:
    ledger: LedgerRepository
    audit: AuditRepository
    idempotency: IdempotencyRepository
    deposits: DepositRepository

    def __init__(self, session_factory: sessionmaker[Session], owner_id: UUID) -> None:
        self._session = session_factory()
        self._committed = False
        self.ledger = PostgresLedgerRepository(self._session, owner_id)
        self.audit = PostgresAuditRepository(self._session, owner_id)
        self.idempotency = PostgresIdempotencyRepository(self._session, owner_id)
        self.deposits = PostgresDepositRepository(self._session, owner_id)

    def __enter__(self) -> PostgresUnitOfWork:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is not None or not self._committed:
            self.rollback()
        self._session.close()

    def commit(self) -> None:
        try:
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        self._committed = True

    def rollback(self) -> None:
        self._session.rollback()


class PostgresUnitOfWorkFactory:
    def __init__(self, engine: Engine) -> None:
        self._session_factory = sessionmaker(engine, expire_on_commit=False)

    def open(self, owner_id: UUID) -> UnitOfWork:
        return PostgresUnitOfWork(self._session_factory, owner_id)


def _account_from_row(row: AccountModel) -> Account:
    return Account(
        id=row.id,
        owner_id=row.owner_id,
        name=row.name,
        kind=AccountKind(row.kind),
        currency=Currency(row.currency),
        archived=row.archived,
        version=row.version,
    )


def _category_group_from_row(row: CategoryGroupModel) -> CategoryGroup:
    return CategoryGroup(
        id=row.id,
        owner_id=row.owner_id,
        name=row.name,
        parent_id=row.parent_id,
        version=row.version,
    )


def _category_from_row(row: CategoryModel) -> Category:
    return Category(
        id=row.id,
        owner_id=row.owner_id,
        name=row.name,
        kind=CategoryKind(row.kind),
        group_id=row.group_id,
        version=row.version,
    )


def _tag_from_row(row: TagModel) -> Tag:
    return Tag(id=row.id, owner_id=row.owner_id, name=row.name, version=row.version)


def _posting_from_row(row: PostingModel) -> Posting:
    return Posting(
        id=row.id,
        transaction_id=row.transaction_id,
        account_id=row.account_id,
        amount=Money.of(row.amount, Currency(row.currency)),
        reversal_of_id=row.reversal_of_id,
    )


def _transaction_from_rows(
    row: TransactionModel,
    posting_rows: Sequence[PostingModel],
    tag_ids: Sequence[UUID] = (),
) -> Transaction:
    return Transaction(
        id=row.id,
        owner_id=row.owner_id,
        kind=TransactionKind(row.kind),
        currency=Currency(row.currency),
        occurred_at=Instant(row.occurred_at),
        postings=tuple(_posting_from_row(posting) for posting in posting_rows),
        description=row.description,
        category_id=row.category_id,
        reversal_of_id=row.reversal_of_id,
        version=row.version,
        source=row.source,
        tag_ids=tuple(tag_ids),
        deposit_id=row.deposit_id,
    )


def _deposit_from_rows(
    row: DepositTermsModel,
    period_rows: Sequence[DepositRatePeriodModel],
) -> DepositTerms:
    return DepositTerms(
        id=row.id,
        owner_id=row.owner_id,
        principal_account_id=row.principal_account_id,
        currency=Currency(row.currency),
        opened_on=row.opened_on,
        matures_on=row.matures_on,
        rate_periods=tuple(
            DepositRatePeriod(
                starts_on=period.starts_on,
                ends_on=period.ends_on,
                nominal_rate=Rate.of(period.nominal_rate),
            )
            for period in period_rows
        ),
        capitalization_frequency=CapitalizationFrequency(row.capitalization_frequency),
        day_count_convention=DayCountConvention(row.day_count_convention),
        rounding_policy=RoundingPolicy(row.rounding_policy),
        interest_rounding_frequency=InterestRoundingFrequency(row.interest_rounding_frequency),
        timezone=row.timezone,
        cashflow_cutoff_time=row.cashflow_cutoff_time,
        cashflow_cutoff_inclusive=row.cashflow_cutoff_inclusive,
        early_close_rule=EarlyCloseRule(
            EarlyClosePolicy(row.early_close_policy),
            None if row.early_close_rate is None else Rate.of(row.early_close_rate),
        ),
        tax_rate=Rate.of(row.tax_rate),
        algorithm_version=row.algorithm_version,
    )
