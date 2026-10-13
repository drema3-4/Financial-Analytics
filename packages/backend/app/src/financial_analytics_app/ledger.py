from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID, uuid4

from financial_analytics_app.ports import (
    AuditEvent,
    IdempotencyRecord,
    TransactionCursor,
    TransactionQuery,
    UnitOfWork,
    UnitOfWorkFactory,
)
from financial_analytics_app.services import IdempotencyConflictError
from financial_analytics_domain import (
    Account,
    AccountKind,
    Category,
    CategoryGroup,
    CategoryKind,
    Currency,
    Instant,
    Money,
    Tag,
    Transaction,
)
from financial_analytics_domain.errors import DomainError


class ResourceNotFoundError(LookupError):
    """A tenant-scoped resource is absent or invisible to the current owner."""


class ResourceConflictError(RuntimeError):
    """A requested mutation conflicts with current immutable or versioned state."""


@dataclass(frozen=True, slots=True)
class AccountWithBalance:
    account: Account
    balance: Money


@dataclass(frozen=True, slots=True)
class TransactionPage:
    items: tuple[Transaction, ...]
    has_more: bool
    snapshot_at: datetime


class LedgerService:
    """Framework-independent commands and queries over the audited ledger ports."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        clock: Callable[[], Instant] = Instant.now,
        uuid_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._uuid_factory = uuid_factory

    def create_account(
        self,
        *,
        owner_id: UUID,
        actor_id: UUID,
        name: str,
        kind: AccountKind,
        currency: Currency,
        opening_balance: Money | None,
        occurred_at: Instant,
        idempotency_key: str,
        request_hash: str,
        request_id: UUID | None,
    ) -> Account:
        if not kind.is_asset:
            raise DomainError("the API can only create asset accounts")
        if opening_balance is not None and opening_balance.currency != currency:
            raise DomainError("opening balance currency must match the account")
        with self._uow_factory.open(owner_id) as uow:
            replay_id = self._lock_and_replay(uow, "create_account", idempotency_key, request_hash)
            if replay_id is not None:
                account = uow.ledger.get_account(replay_id)
                if account is None:
                    raise RuntimeError("idempotency record points to a missing account")
                return account

            account = Account(
                id=self._uuid_factory(),
                owner_id=owner_id,
                name=name.strip(),
                kind=kind,
                currency=currency,
            )
            uow.ledger.add_account(account)
            self._audit(uow, actor_id, "ledger.account_created", "account", account.id, request_id)
            if opening_balance is not None:
                equity = self._system_account(
                    uow, actor_id, AccountKind.SYSTEM_EQUITY, currency, request_id
                )
                transaction = Transaction.adjustment(
                    id=self._uuid_factory(),
                    owner_id=owner_id,
                    asset=account,
                    equity_account=equity,
                    amount=opening_balance,
                    occurred_at=occurred_at,
                    posting_ids=(self._uuid_factory(), self._uuid_factory()),
                    description="Opening balance",
                    entry_source="system",
                )
                uow.ledger.add_transaction(transaction, actor_id=actor_id, request_id=request_id)
                self._audit_transaction(uow, actor_id, transaction, request_id)
            self._remember(
                uow,
                owner_id,
                "create_account",
                idempotency_key,
                request_hash,
                "account",
                account.id,
            )
            uow.commit()
            return account

    def list_accounts(
        self, owner_id: UUID, *, include_archived: bool = False
    ) -> tuple[AccountWithBalance, ...]:
        with self._uow_factory.open(owner_id) as uow:
            accounts = uow.ledger.list_accounts(include_archived=include_archived)
            balances = uow.ledger.rebuild_balances()
            return tuple(AccountWithBalance(account, balances[account.id]) for account in accounts)

    def get_account(self, owner_id: UUID, account_id: UUID) -> AccountWithBalance:
        with self._uow_factory.open(owner_id) as uow:
            account = uow.ledger.get_account(account_id)
            if account is None or not account.kind.is_asset:
                raise ResourceNotFoundError("account was not found")
            balances = uow.ledger.rebuild_balances()
            return AccountWithBalance(account, balances[account.id])

    def update_account(
        self,
        *,
        owner_id: UUID,
        actor_id: UUID,
        account_id: UUID,
        version: int,
        name: str | None,
        archived: bool | None,
        request_id: UUID | None,
    ) -> Account:
        with self._uow_factory.open(owner_id) as uow:
            account = uow.ledger.get_account(account_id)
            if account is None or not account.kind.is_asset:
                raise ResourceNotFoundError("account was not found")
            if account.version != version:
                raise ResourceConflictError("account version is stale")
            updated = replace(
                account,
                name=account.name if name is None else name.strip(),
                archived=account.archived if archived is None else archived,
            )
            saved = uow.ledger.save_account(updated)
            self._audit(uow, actor_id, "ledger.account_updated", "account", account_id, request_id)
            uow.commit()
            return saved

    def create_category_group(
        self,
        *,
        owner_id: UUID,
        actor_id: UUID,
        name: str,
        parent_id: UUID | None,
        idempotency_key: str,
        request_hash: str,
        request_id: UUID | None,
    ) -> CategoryGroup:
        with self._uow_factory.open(owner_id) as uow:
            replay_id = self._lock_and_replay(
                uow, "create_category_group", idempotency_key, request_hash
            )
            if replay_id is not None:
                group = uow.ledger.get_category_group(replay_id)
                if group is None:
                    raise RuntimeError("idempotency record points to a missing category group")
                return group
            if parent_id is not None and uow.ledger.get_category_group(parent_id) is None:
                raise ResourceNotFoundError("parent category group was not found")
            group = CategoryGroup(
                id=self._uuid_factory(),
                owner_id=owner_id,
                name=name.strip(),
                parent_id=parent_id,
            )
            uow.ledger.add_category_group(group)
            self._audit(
                uow,
                actor_id,
                "ledger.category_group_created",
                "category_group",
                group.id,
                request_id,
            )
            self._remember(
                uow,
                owner_id,
                "create_category_group",
                idempotency_key,
                request_hash,
                "category_group",
                group.id,
            )
            uow.commit()
            return group

    def list_category_groups(self, owner_id: UUID) -> tuple[CategoryGroup, ...]:
        with self._uow_factory.open(owner_id) as uow:
            return uow.ledger.list_category_groups()

    def create_category(
        self,
        *,
        owner_id: UUID,
        actor_id: UUID,
        name: str,
        kind: CategoryKind,
        group_id: UUID | None,
        idempotency_key: str,
        request_hash: str,
        request_id: UUID | None,
    ) -> Category:
        with self._uow_factory.open(owner_id) as uow:
            replay_id = self._lock_and_replay(uow, "create_category", idempotency_key, request_hash)
            if replay_id is not None:
                category = uow.ledger.get_category(replay_id)
                if category is None:
                    raise RuntimeError("idempotency record points to a missing category")
                return category
            if group_id is not None and uow.ledger.get_category_group(group_id) is None:
                raise ResourceNotFoundError("category group was not found")
            category = Category(
                id=self._uuid_factory(),
                owner_id=owner_id,
                name=name.strip(),
                kind=kind,
                group_id=group_id,
            )
            uow.ledger.add_category(category)
            self._audit(
                uow, actor_id, "ledger.category_created", "category", category.id, request_id
            )
            self._remember(
                uow,
                owner_id,
                "create_category",
                idempotency_key,
                request_hash,
                "category",
                category.id,
            )
            uow.commit()
            return category

    def list_categories(self, owner_id: UUID) -> tuple[Category, ...]:
        with self._uow_factory.open(owner_id) as uow:
            return uow.ledger.list_categories()

    def create_tag(
        self,
        *,
        owner_id: UUID,
        actor_id: UUID,
        name: str,
        idempotency_key: str,
        request_hash: str,
        request_id: UUID | None,
    ) -> Tag:
        with self._uow_factory.open(owner_id) as uow:
            replay_id = self._lock_and_replay(uow, "create_tag", idempotency_key, request_hash)
            if replay_id is not None:
                tag = uow.ledger.get_tag(replay_id)
                if tag is None:
                    raise RuntimeError("idempotency record points to a missing tag")
                return tag
            tag = Tag(id=self._uuid_factory(), owner_id=owner_id, name=name.strip())
            uow.ledger.add_tag(tag)
            self._audit(uow, actor_id, "ledger.tag_created", "tag", tag.id, request_id)
            self._remember(
                uow,
                owner_id,
                "create_tag",
                idempotency_key,
                request_hash,
                "tag",
                tag.id,
            )
            uow.commit()
            return tag

    def list_tags(self, owner_id: UUID) -> tuple[Tag, ...]:
        with self._uow_factory.open(owner_id) as uow:
            return uow.ledger.list_tags()

    def record_income(
        self,
        *,
        owner_id: UUID,
        actor_id: UUID,
        account_id: UUID,
        category_id: UUID,
        amount: Money,
        occurred_at: Instant,
        description: str,
        source: str,
        tag_ids: Sequence[UUID],
        idempotency_key: str,
        request_hash: str,
        request_id: UUID | None,
    ) -> Transaction:
        return self._record_ordinary(
            "income",
            owner_id=owner_id,
            actor_id=actor_id,
            account_id=account_id,
            category_id=category_id,
            amount=amount,
            occurred_at=occurred_at,
            description=description,
            source=source,
            tag_ids=tag_ids,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            request_id=request_id,
        )

    def record_expense(
        self,
        *,
        owner_id: UUID,
        actor_id: UUID,
        account_id: UUID,
        category_id: UUID,
        amount: Money,
        occurred_at: Instant,
        description: str,
        source: str,
        tag_ids: Sequence[UUID],
        idempotency_key: str,
        request_hash: str,
        request_id: UUID | None,
    ) -> Transaction:
        return self._record_ordinary(
            "expense",
            owner_id=owner_id,
            actor_id=actor_id,
            account_id=account_id,
            category_id=category_id,
            amount=amount,
            occurred_at=occurred_at,
            description=description,
            source=source,
            tag_ids=tag_ids,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            request_id=request_id,
        )

    def _record_ordinary(
        self,
        transaction_kind: str,
        *,
        owner_id: UUID,
        actor_id: UUID,
        account_id: UUID,
        category_id: UUID,
        amount: Money,
        occurred_at: Instant,
        description: str,
        source: str,
        tag_ids: Sequence[UUID],
        idempotency_key: str,
        request_hash: str,
        request_id: UUID | None,
    ) -> Transaction:
        scope = f"create_{transaction_kind}"
        with self._uow_factory.open(owner_id) as uow:
            replay = self._transaction_replay(uow, scope, idempotency_key, request_hash)
            if replay is not None:
                return replay
            asset = self._asset_account(uow, account_id)
            category = uow.ledger.get_category(category_id)
            if category is None:
                raise ResourceNotFoundError("category was not found")
            self._require_tags(uow, tag_ids)
            system_kind = (
                AccountKind.SYSTEM_INCOME
                if transaction_kind == "income"
                else AccountKind.SYSTEM_EXPENSE
            )
            system_account = self._system_account(
                uow, actor_id, system_kind, asset.currency, request_id
            )
            transaction_id = self._uuid_factory()
            posting_ids = (self._uuid_factory(), self._uuid_factory())
            if transaction_kind == "income":
                transaction = Transaction.income(
                    id=transaction_id,
                    owner_id=owner_id,
                    asset=asset,
                    income_account=system_account,
                    category=category,
                    amount=amount,
                    occurred_at=occurred_at,
                    posting_ids=posting_ids,
                    description=description,
                    entry_source=source,
                    tag_ids=tag_ids,
                )
            else:
                transaction = Transaction.expense(
                    id=transaction_id,
                    owner_id=owner_id,
                    asset=asset,
                    expense_account=system_account,
                    category=category,
                    amount=amount,
                    occurred_at=occurred_at,
                    posting_ids=posting_ids,
                    description=description,
                    entry_source=source,
                    tag_ids=tag_ids,
                )
            self._persist_transaction(
                uow,
                transaction,
                actor_id,
                scope,
                idempotency_key,
                request_hash,
                request_id,
            )
            return transaction

    def record_transfer(
        self,
        *,
        owner_id: UUID,
        actor_id: UUID,
        source_account_id: UUID,
        destination_account_id: UUID,
        amount: Money,
        occurred_at: Instant,
        description: str,
        source: str,
        tag_ids: Sequence[UUID],
        idempotency_key: str,
        request_hash: str,
        request_id: UUID | None,
    ) -> Transaction:
        scope = "create_transfer"
        with self._uow_factory.open(owner_id) as uow:
            replay = self._transaction_replay(uow, scope, idempotency_key, request_hash)
            if replay is not None:
                return replay
            source_account = self._asset_account(uow, source_account_id)
            destination = self._asset_account(uow, destination_account_id)
            self._require_tags(uow, tag_ids)
            transaction = Transaction.transfer(
                id=self._uuid_factory(),
                owner_id=owner_id,
                source=source_account,
                destination=destination,
                amount=amount,
                occurred_at=occurred_at,
                posting_ids=(self._uuid_factory(), self._uuid_factory()),
                description=description,
                entry_source=source,
                tag_ids=tag_ids,
            )
            self._persist_transaction(
                uow,
                transaction,
                actor_id,
                scope,
                idempotency_key,
                request_hash,
                request_id,
            )
            return transaction

    def record_adjustment(
        self,
        *,
        owner_id: UUID,
        actor_id: UUID,
        account_id: UUID,
        amount: Money,
        occurred_at: Instant,
        description: str,
        source: str,
        tag_ids: Sequence[UUID],
        idempotency_key: str,
        request_hash: str,
        request_id: UUID | None,
    ) -> Transaction:
        scope = "create_adjustment"
        with self._uow_factory.open(owner_id) as uow:
            replay = self._transaction_replay(uow, scope, idempotency_key, request_hash)
            if replay is not None:
                return replay
            asset = self._asset_account(uow, account_id)
            self._require_tags(uow, tag_ids)
            equity = self._system_account(
                uow, actor_id, AccountKind.SYSTEM_EQUITY, asset.currency, request_id
            )
            transaction = Transaction.adjustment(
                id=self._uuid_factory(),
                owner_id=owner_id,
                asset=asset,
                equity_account=equity,
                amount=amount,
                occurred_at=occurred_at,
                posting_ids=(self._uuid_factory(), self._uuid_factory()),
                description=description,
                entry_source=source,
                tag_ids=tag_ids,
            )
            self._persist_transaction(
                uow,
                transaction,
                actor_id,
                scope,
                idempotency_key,
                request_hash,
                request_id,
            )
            return transaction

    def reverse_transaction(
        self,
        *,
        owner_id: UUID,
        actor_id: UUID,
        transaction_id: UUID,
        occurred_at: Instant,
        reason: str,
        idempotency_key: str,
        request_hash: str,
        request_id: UUID | None,
    ) -> Transaction:
        scope = "reverse_transaction"
        with self._uow_factory.open(owner_id) as uow:
            replay = self._transaction_replay(uow, scope, idempotency_key, request_hash)
            if replay is not None:
                return replay
            original = uow.ledger.get_transaction(transaction_id)
            if original is None:
                raise ResourceNotFoundError("transaction was not found")
            transaction = Transaction.reversal(
                id=self._uuid_factory(),
                owner_id=owner_id,
                original=original,
                occurred_at=occurred_at,
                posting_ids=tuple(self._uuid_factory() for _ in original.postings),
                reason=reason,
            )
            self._persist_transaction(
                uow,
                transaction,
                actor_id,
                scope,
                idempotency_key,
                request_hash,
                request_id,
            )
            return transaction

    def get_transaction(self, owner_id: UUID, transaction_id: UUID) -> Transaction:
        with self._uow_factory.open(owner_id) as uow:
            transaction = uow.ledger.get_transaction(transaction_id)
            if transaction is None:
                raise ResourceNotFoundError("transaction was not found")
            return transaction

    def list_transactions(
        self,
        owner_id: UUID,
        query: TransactionQuery,
        *,
        cursor: TransactionCursor | None,
        limit: int,
    ) -> TransactionPage:
        with self._uow_factory.open(owner_id) as uow:
            items, has_more, snapshot_at = uow.ledger.list_transactions(
                query, cursor=cursor, limit=limit
            )
            return TransactionPage(items, has_more, snapshot_at)

    def _lock_and_replay(
        self,
        uow: UnitOfWork,
        scope: str,
        key: str,
        request_hash: str,
    ) -> UUID | None:
        uow.idempotency.lock(scope, key)
        existing = uow.idempotency.get(scope, key)
        if existing is None:
            return None
        if existing.request_hash != request_hash:
            raise IdempotencyConflictError(
                "idempotency key was used with a different request payload"
            )
        return existing.resource_id

    def _transaction_replay(
        self,
        uow: UnitOfWork,
        scope: str,
        key: str,
        request_hash: str,
    ) -> Transaction | None:
        replay_id = self._lock_and_replay(uow, scope, key, request_hash)
        if replay_id is None:
            return None
        transaction = uow.ledger.get_transaction(replay_id)
        if transaction is None:
            raise RuntimeError("idempotency record points to a missing transaction")
        return transaction

    def _remember(
        self,
        uow: UnitOfWork,
        owner_id: UUID,
        scope: str,
        key: str,
        request_hash: str,
        resource_type: str,
        resource_id: UUID,
    ) -> None:
        uow.idempotency.add(
            IdempotencyRecord(
                owner_id=owner_id,
                scope=scope,
                key=key,
                request_hash=request_hash,
                resource_type=resource_type,
                resource_id=resource_id,
                created_at=self._clock(),
            )
        )

    def _persist_transaction(
        self,
        uow: UnitOfWork,
        transaction: Transaction,
        actor_id: UUID,
        scope: str,
        idempotency_key: str,
        request_hash: str,
        request_id: UUID | None,
    ) -> None:
        uow.ledger.add_transaction(transaction, actor_id=actor_id, request_id=request_id)
        self._audit_transaction(uow, actor_id, transaction, request_id)
        self._remember(
            uow,
            transaction.owner_id,
            scope,
            idempotency_key,
            request_hash,
            "transaction",
            transaction.id,
        )
        uow.commit()

    def _asset_account(self, uow: UnitOfWork, account_id: UUID) -> Account:
        account = uow.ledger.get_account(account_id)
        if account is None or not account.kind.is_asset:
            raise ResourceNotFoundError("account was not found")
        if account.archived:
            raise ResourceConflictError("archived accounts cannot receive new postings")
        return account

    def _require_tags(self, uow: UnitOfWork, tag_ids: Sequence[UUID]) -> None:
        if len(set(tag_ids)) != len(tag_ids):
            raise DomainError("transaction tags must be unique")
        for tag_id in tag_ids:
            if uow.ledger.get_tag(tag_id) is None:
                raise ResourceNotFoundError("tag was not found")

    def _system_account(
        self,
        uow: UnitOfWork,
        actor_id: UUID,
        kind: AccountKind,
        currency: Currency,
        request_id: UUID | None,
    ) -> Account:
        account, created = uow.ledger.get_or_create_system_account(kind, currency)
        if created:
            self._audit(
                uow,
                actor_id,
                "ledger.system_account_created",
                "account",
                account.id,
                request_id,
                payload={"kind": kind.value, "currency": currency.code},
            )
        return account

    def _audit_transaction(
        self,
        uow: UnitOfWork,
        actor_id: UUID,
        transaction: Transaction,
        request_id: UUID | None,
    ) -> None:
        self._audit(
            uow,
            actor_id,
            "ledger.transaction_recorded",
            "transaction",
            transaction.id,
            request_id,
            payload={
                "kind": transaction.kind.value,
                "reversal_of_id": (
                    str(transaction.reversal_of_id)
                    if transaction.reversal_of_id is not None
                    else None
                ),
            },
        )

    def _audit(
        self,
        uow: UnitOfWork,
        actor_id: UUID,
        event_type: str,
        aggregate_type: str,
        aggregate_id: UUID,
        request_id: UUID | None,
        *,
        payload: dict[str, object] | None = None,
    ) -> None:
        uow.audit.append(
            AuditEvent(
                id=self._uuid_factory(),
                owner_id=uow.ledger.owner_id,
                actor_id=actor_id,
                event_type=event_type,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                occurred_at=self._clock(),
                request_id=request_id,
                payload=payload,
            )
        )
