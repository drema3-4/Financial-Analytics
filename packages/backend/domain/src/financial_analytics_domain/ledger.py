from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from financial_analytics_domain.errors import (
    CurrencyMismatchError,
    DomainError,
    OwnershipError,
    UnbalancedTransactionError,
)
from financial_analytics_domain.values import Currency, Instant, Money


class AccountKind(StrEnum):
    CASH = "cash"
    BANK = "bank"
    SAVINGS = "savings"
    DEPOSIT = "deposit"
    OTHER_ASSET = "other_asset"
    SYSTEM_INCOME = "system_income"
    SYSTEM_EXPENSE = "system_expense"
    SYSTEM_EQUITY = "system_equity"

    @property
    def is_asset(self) -> bool:
        return self not in {self.SYSTEM_INCOME, self.SYSTEM_EXPENSE, self.SYSTEM_EQUITY}


class CategoryKind(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"


class TransactionKind(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"
    TRANSFER = "transfer"
    ADJUSTMENT = "adjustment"
    INTEREST = "interest"
    REVERSAL = "reversal"


@dataclass(frozen=True, slots=True)
class Account:
    id: UUID
    owner_id: UUID
    name: str
    currency: Currency
    kind: AccountKind
    version: int = 1
    archived: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise DomainError("account name must not be empty")
        if self.version < 1:
            raise DomainError("account version must be positive")


@dataclass(frozen=True, slots=True)
class CategoryGroup:
    id: UUID
    owner_id: UUID
    name: str
    parent_id: UUID | None = None
    version: int = 1

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise DomainError("category group name must not be empty")
        if self.id == self.parent_id:
            raise DomainError("category group cannot be its own parent")


@dataclass(frozen=True, slots=True)
class Category:
    id: UUID
    owner_id: UUID
    name: str
    kind: CategoryKind
    group_id: UUID | None = None
    is_mandatory: bool = False
    version: int = 1

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise DomainError("category name must not be empty")
        if self.kind is CategoryKind.INCOME and self.is_mandatory:
            raise DomainError("only expense categories can be mandatory")


@dataclass(frozen=True, slots=True)
class Tag:
    id: UUID
    owner_id: UUID
    name: str
    version: int = 1

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise DomainError("tag name must not be empty")


@dataclass(frozen=True, slots=True)
class Posting:
    id: UUID
    transaction_id: UUID
    account_id: UUID
    amount: Money
    reversal_of_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.amount.amount == 0:
            raise DomainError("posting amount must not be zero")


@dataclass(frozen=True, slots=True)
class Transaction:
    id: UUID
    owner_id: UUID
    kind: TransactionKind
    currency: Currency
    occurred_at: Instant
    postings: tuple[Posting, ...]
    description: str = ""
    category_id: UUID | None = None
    reversal_of_id: UUID | None = None
    version: int = 1
    source: str = "manual"
    tag_ids: tuple[UUID, ...] = ()
    deposit_id: UUID | None = None
    reversed_by_id: UUID | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if len(self.postings) < 2:
            raise UnbalancedTransactionError("a transaction requires at least two postings")
        if any(posting.transaction_id != self.id for posting in self.postings):
            raise DomainError("every posting must reference its transaction")
        if any(posting.amount.currency != self.currency for posting in self.postings):
            raise CurrencyMismatchError("all postings must use the transaction currency")
        total = sum(
            (posting.amount.amount for posting in self.postings),
            start=Money.of("0", self.currency).amount,
        )
        if total != 0:
            raise UnbalancedTransactionError("posting amounts must sum to zero")
        if (self.kind is TransactionKind.REVERSAL) != (self.reversal_of_id is not None):
            raise DomainError("only reversal transactions have a causal transaction link")
        if self.kind in {TransactionKind.INCOME, TransactionKind.EXPENSE}:
            if self.category_id is None:
                raise DomainError("income and expense require a category")
        elif self.category_id is not None:
            raise DomainError(
                "transfer, adjustment, interest, and reversal do not carry a category"
            )
        if self.kind is TransactionKind.INTEREST and self.deposit_id is None:
            raise DomainError("deposit interest requires a deposit link")
        if self.deposit_id is not None and self.kind not in {
            TransactionKind.TRANSFER,
            TransactionKind.INTEREST,
            TransactionKind.REVERSAL,
        }:
            raise DomainError(
                "only deposit cashflows, interest, and reversals carry a deposit link"
            )
        if self.version < 1:
            raise DomainError("transaction version must be positive")
        if not self.source.strip() or len(self.source) > 32:
            raise DomainError("transaction source must contain 1 to 32 characters")
        if len(set(self.tag_ids)) != len(self.tag_ids):
            raise DomainError("transaction tags must be unique")

    @staticmethod
    def _same_owner(owner_id: UUID, *entities: Account | Category) -> None:
        if any(entity.owner_id != owner_id for entity in entities):
            raise OwnershipError("all ledger entities must have the same owner")

    @staticmethod
    def _positive_in_currency(amount: Money, currency: Currency) -> None:
        if not amount.is_positive():
            raise DomainError("transaction amount must be positive")
        if amount.currency != currency:
            raise CurrencyMismatchError("amount and account currencies differ")

    @classmethod
    def transfer(
        cls,
        *,
        id: UUID,
        owner_id: UUID,
        source: Account,
        destination: Account,
        amount: Money,
        occurred_at: Instant,
        posting_ids: Sequence[UUID],
        description: str = "",
        entry_source: str = "manual",
        tag_ids: Sequence[UUID] = (),
        deposit_id: UUID | None = None,
    ) -> Transaction:
        cls._same_owner(owner_id, source, destination)
        if source.id == destination.id:
            raise DomainError("transfer accounts must differ")
        if not source.kind.is_asset or not destination.kind.is_asset:
            raise DomainError("transfer requires two asset accounts")
        if source.currency != destination.currency:
            raise CurrencyMismatchError(
                "cross-currency transfer requires an explicit FX transaction model"
            )
        cls._positive_in_currency(amount, source.currency)
        first, second = _two_posting_ids(posting_ids)
        return cls(
            id=id,
            owner_id=owner_id,
            kind=TransactionKind.TRANSFER,
            currency=source.currency,
            occurred_at=occurred_at,
            description=description,
            source=entry_source,
            tag_ids=tuple(tag_ids),
            deposit_id=deposit_id,
            postings=(
                Posting(first, id, source.id, -amount),
                Posting(second, id, destination.id, amount),
            ),
        )

    @classmethod
    def income(
        cls,
        *,
        id: UUID,
        owner_id: UUID,
        asset: Account,
        income_account: Account,
        category: Category,
        amount: Money,
        occurred_at: Instant,
        posting_ids: Sequence[UUID],
        description: str = "",
        entry_source: str = "manual",
        tag_ids: Sequence[UUID] = (),
    ) -> Transaction:
        cls._same_owner(owner_id, asset, income_account, category)
        _require_income_expense_shape(
            asset,
            income_account,
            category,
            amount,
            AccountKind.SYSTEM_INCOME,
            CategoryKind.INCOME,
        )
        first, second = _two_posting_ids(posting_ids)
        return cls(
            id=id,
            owner_id=owner_id,
            kind=TransactionKind.INCOME,
            currency=asset.currency,
            occurred_at=occurred_at,
            description=description,
            category_id=category.id,
            source=entry_source,
            tag_ids=tuple(tag_ids),
            postings=(
                Posting(first, id, asset.id, amount),
                Posting(second, id, income_account.id, -amount),
            ),
        )

    @classmethod
    def expense(
        cls,
        *,
        id: UUID,
        owner_id: UUID,
        asset: Account,
        expense_account: Account,
        category: Category,
        amount: Money,
        occurred_at: Instant,
        posting_ids: Sequence[UUID],
        description: str = "",
        entry_source: str = "manual",
        tag_ids: Sequence[UUID] = (),
    ) -> Transaction:
        cls._same_owner(owner_id, asset, expense_account, category)
        _require_income_expense_shape(
            asset,
            expense_account,
            category,
            amount,
            AccountKind.SYSTEM_EXPENSE,
            CategoryKind.EXPENSE,
        )
        first, second = _two_posting_ids(posting_ids)
        return cls(
            id=id,
            owner_id=owner_id,
            kind=TransactionKind.EXPENSE,
            currency=asset.currency,
            occurred_at=occurred_at,
            description=description,
            category_id=category.id,
            source=entry_source,
            tag_ids=tuple(tag_ids),
            postings=(
                Posting(first, id, asset.id, -amount),
                Posting(second, id, expense_account.id, amount),
            ),
        )

    @classmethod
    def adjustment(
        cls,
        *,
        id: UUID,
        owner_id: UUID,
        asset: Account,
        equity_account: Account,
        amount: Money,
        occurred_at: Instant,
        posting_ids: Sequence[UUID],
        description: str,
        entry_source: str = "manual",
        tag_ids: Sequence[UUID] = (),
    ) -> Transaction:
        cls._same_owner(owner_id, asset, equity_account)
        if not asset.kind.is_asset or equity_account.kind is not AccountKind.SYSTEM_EQUITY:
            raise DomainError("adjustment account roles are invalid")
        if asset.currency != equity_account.currency or amount.currency != asset.currency:
            raise CurrencyMismatchError("adjustment accounts and amount must share a currency")
        if amount.amount == 0:
            raise DomainError("adjustment amount must not be zero")
        if not description.strip():
            raise DomainError("adjustment description must not be empty")
        first, second = _two_posting_ids(posting_ids)
        return cls(
            id=id,
            owner_id=owner_id,
            kind=TransactionKind.ADJUSTMENT,
            currency=asset.currency,
            occurred_at=occurred_at,
            description=description,
            source=entry_source,
            tag_ids=tuple(tag_ids),
            postings=(
                Posting(first, id, asset.id, amount),
                Posting(second, id, equity_account.id, -amount),
            ),
        )

    @classmethod
    def deposit_interest(
        cls,
        *,
        id: UUID,
        owner_id: UUID,
        deposit_id: UUID,
        principal_account: Account,
        income_account: Account,
        amount: Money,
        occurred_at: Instant,
        posting_ids: Sequence[UUID],
        description: str,
    ) -> Transaction:
        cls._same_owner(owner_id, principal_account, income_account)
        if principal_account.kind is not AccountKind.DEPOSIT:
            raise DomainError("deposit interest requires a deposit principal account")
        if income_account.kind is not AccountKind.SYSTEM_INCOME:
            raise DomainError("deposit interest requires a system income account")
        if principal_account.currency != income_account.currency:
            raise CurrencyMismatchError("deposit interest accounts must share a currency")
        if amount.currency != principal_account.currency or amount.amount == 0:
            raise DomainError("deposit interest amount must be non-zero in deposit currency")
        if not description.strip():
            raise DomainError("deposit interest description must not be empty")
        first, second = _two_posting_ids(posting_ids)
        return cls(
            id=id,
            owner_id=owner_id,
            kind=TransactionKind.INTEREST,
            currency=principal_account.currency,
            occurred_at=occurred_at,
            description=description,
            source="deposit_interest",
            deposit_id=deposit_id,
            postings=(
                Posting(first, id, principal_account.id, amount),
                Posting(second, id, income_account.id, -amount),
            ),
        )

    @classmethod
    def reversal(
        cls,
        *,
        id: UUID,
        owner_id: UUID,
        original: Transaction,
        occurred_at: Instant,
        posting_ids: Sequence[UUID],
        reason: str,
        entry_source: str = "manual",
    ) -> Transaction:
        if original.owner_id != owner_id:
            raise OwnershipError("reversal owner must match the original transaction")
        if original.kind is TransactionKind.REVERSAL:
            raise DomainError("a reversal cannot reverse another reversal")
        if not reason.strip():
            raise DomainError("reversal reason must not be empty")
        if len(posting_ids) != len(original.postings):
            raise DomainError("reversal requires one new posting id per original posting")
        postings = tuple(
            Posting(
                id=new_id,
                transaction_id=id,
                account_id=old.account_id,
                amount=-old.amount,
                reversal_of_id=old.id,
            )
            for new_id, old in zip(posting_ids, original.postings, strict=True)
        )
        return cls(
            id=id,
            owner_id=owner_id,
            kind=TransactionKind.REVERSAL,
            currency=original.currency,
            occurred_at=occurred_at,
            postings=postings,
            description=reason,
            reversal_of_id=original.id,
            source=entry_source,
            tag_ids=original.tag_ids,
            deposit_id=original.deposit_id,
        )


def _two_posting_ids(posting_ids: Sequence[UUID]) -> tuple[UUID, UUID]:
    if len(posting_ids) != 2:
        raise DomainError("transaction requires exactly two posting ids")
    return posting_ids[0], posting_ids[1]


def _require_income_expense_shape(
    asset: Account,
    system_account: Account,
    category: Category,
    amount: Money,
    expected_account_kind: AccountKind,
    expected_category_kind: CategoryKind,
) -> None:
    if not asset.kind.is_asset or system_account.kind is not expected_account_kind:
        raise DomainError("transaction account roles are invalid")
    if category.kind is not expected_category_kind:
        raise DomainError("category kind does not match transaction kind")
    if asset.currency != system_account.currency or amount.currency != asset.currency:
        raise CurrencyMismatchError("transaction accounts and amount must share a currency")
    if not amount.is_positive():
        raise DomainError("transaction amount must be positive")


def rebuild_balances(
    accounts: Iterable[Account], transactions: Iterable[Transaction]
) -> dict[UUID, Money]:
    """Rebuild balances solely from immutable postings, without a stored balance."""

    account_map = {account.id: account for account in accounts}
    balances = {account.id: Money.of("0", account.currency) for account in account_map.values()}
    for transaction in transactions:
        for posting in transaction.postings:
            account = account_map.get(posting.account_id)
            if account is None:
                continue
            if account.owner_id != transaction.owner_id:
                raise OwnershipError("posting transaction and account owners differ")
            balances[account.id] = balances[account.id] + posting.amount
    return balances
