from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from financial_analytics_app import (
    ConcurrentModificationError,
    IdempotencyConflictError,
    RecordTransaction,
)
from financial_analytics_domain import (
    Account,
    AccountKind,
    Currency,
    Instant,
    Money,
    Transaction,
)
from financial_analytics_domain.errors import OwnershipError
from financial_analytics_infra.models import (
    AccountModel,
    AuditEventModel,
    IdempotencyRecordModel,
    PostingModel,
    TransactionModel,
    UserModel,
)
from financial_analytics_infra.repositories import PostgresUnitOfWorkFactory

pytestmark = pytest.mark.integration

NOW = Instant(datetime(2026, 10, 13, 1, 30, tzinfo=UTC))
RUB = Currency("RUB")


def _create_owner(engine: Engine) -> UUID:
    owner_id = uuid4()
    with Session(engine) as session:
        session.add(UserModel(id=owner_id))
        session.commit()
    return owner_id


def _account(owner_id: UUID, name: str, kind: AccountKind = AccountKind.BANK) -> Account:
    return Account(uuid4(), owner_id, name, RUB, kind)


def test_repository_api_is_owner_scoped(postgres_engine: Engine) -> None:
    first_owner = _create_owner(postgres_engine)
    second_owner = _create_owner(postgres_engine)
    first = _account(first_owner, "First")
    second = _account(second_owner, "Second")
    factory = PostgresUnitOfWorkFactory(postgres_engine)

    with factory.open(first_owner) as uow:
        uow.ledger.add_account(first)
        uow.commit()
    with factory.open(second_owner) as uow:
        uow.ledger.add_account(second)
        uow.commit()

    with factory.open(first_owner) as uow:
        assert uow.ledger.get_account(first.id) == first
        assert uow.ledger.get_account(second.id) is None
        assert uow.ledger.list_postings(second.id) == ()
        assert set(uow.ledger.rebuild_balances()) == {first.id}
        with pytest.raises(OwnershipError):
            uow.ledger.save_account(replace(second, name="Cross-tenant write"))


def test_system_account_upsert_with_prepared_generic_plans(postgres_engine: Engine) -> None:
    owners = (_create_owner(postgres_engine), _create_owner(postgres_engine))
    engine = create_engine(
        postgres_engine.url,
        connect_args={"prepare_threshold": 0, "options": "-c plan_cache_mode=force_generic_plan"},
    )
    factory = PostgresUnitOfWorkFactory(engine)
    accounts: dict[tuple[UUID, AccountKind], Account] = {}
    try:
        for owner in owners:
            for kind in (
                AccountKind.SYSTEM_INCOME,
                AccountKind.SYSTEM_EXPENSE,
                AccountKind.SYSTEM_EQUITY,
            ):
                with factory.open(owner) as uow:
                    account, created = uow.ledger.get_or_create_system_account(kind, RUB)
                    assert created is True
                    accounts[(owner, kind)] = account
                    uow.commit()
                for _ in range(12):
                    with factory.open(owner) as uow:
                        replay, created = uow.ledger.get_or_create_system_account(kind, RUB)
                        assert replay == account
                        assert created is False
                        uow.commit()
        with factory.open(owners[0]) as uow:
            for kind in (AccountKind.SYSTEM_INCOME, AccountKind.SYSTEM_EXPENSE):
                assert accounts[(owners[0], kind)].id != accounts[(owners[1], kind)].id
                assert uow.ledger.get_account(accounts[(owners[1], kind)].id) is None
    finally:
        engine.dispose()


def test_database_rejects_unbalanced_posted_transaction(postgres_engine: Engine) -> None:
    owner_id = _create_owner(postgres_engine)
    source = _account(owner_id, "Source")
    destination = _account(owner_id, "Destination")
    transaction_id = uuid4()
    factory = PostgresUnitOfWorkFactory(postgres_engine)
    with factory.open(owner_id) as uow:
        uow.ledger.add_account(source)
        uow.ledger.add_account(destination)
        uow.commit()

    with Session(postgres_engine) as session:
        row = TransactionModel(
            id=transaction_id,
            owner_id=owner_id,
            actor_id=owner_id,
            kind="transfer",
            status="pending",
            currency="RUB",
            occurred_at=NOW.value,
            version=1,
        )
        session.add(row)
        session.flush()
        session.add_all(
            [
                PostingModel(
                    id=uuid4(),
                    owner_id=owner_id,
                    transaction_id=transaction_id,
                    account_id=source.id,
                    line_no=1,
                    currency="RUB",
                    amount=Decimal("-10.000000000"),
                ),
                PostingModel(
                    id=uuid4(),
                    owner_id=owner_id,
                    transaction_id=transaction_id,
                    account_id=destination.id,
                    line_no=2,
                    currency="RUB",
                    amount=Decimal("9.990000000"),
                ),
            ]
        )
        session.flush()
        row.status = "posted"
        with pytest.raises(IntegrityError):
            session.commit()

    with Session(postgres_engine) as session:
        assert session.get(TransactionModel, transaction_id) is None


def test_record_reversal_audit_idempotency_and_rebuild(postgres_engine: Engine) -> None:
    owner_id = _create_owner(postgres_engine)
    source = _account(owner_id, "Source")
    destination = _account(owner_id, "Destination", AccountKind.SAVINGS)
    factory = PostgresUnitOfWorkFactory(postgres_engine)
    with factory.open(owner_id) as uow:
        uow.ledger.add_account(source)
        uow.ledger.add_account(destination)
        uow.commit()

    original = Transaction.transfer(
        id=uuid4(),
        owner_id=owner_id,
        source=source,
        destination=destination,
        amount=Money.of("250.25", RUB),
        occurred_at=NOW,
        posting_ids=(uuid4(), uuid4()),
    )
    reversal = Transaction.reversal(
        id=uuid4(),
        owner_id=owner_id,
        original=original,
        occurred_at=NOW,
        posting_ids=(uuid4(), uuid4()),
        reason="Wrong destination",
    )
    service = RecordTransaction(factory, clock=lambda: NOW)

    first_result = service.execute(
        original,
        actor_id=owner_id,
        idempotency_key="original",
        request_hash="a" * 64,
    )
    replay_result = service.execute(
        original,
        actor_id=owner_id,
        idempotency_key="original",
        request_hash="a" * 64,
    )
    with pytest.raises(IdempotencyConflictError):
        service.execute(
            original,
            actor_id=owner_id,
            idempotency_key="original",
            request_hash="c" * 64,
        )
    service.execute(
        reversal,
        actor_id=owner_id,
        idempotency_key="reversal",
        request_hash="b" * 64,
    )

    assert first_result == replay_result == original.id
    with factory.open(owner_id) as uow:
        assert uow.ledger.get_transaction(original.id) == original
        assert uow.ledger.get_transaction(reversal.id) == reversal
        assert uow.ledger.rebuild_balances() == {
            source.id: Money.of("0", RUB),
            destination.id: Money.of("0", RUB),
        }
    with Session(postgres_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(TransactionModel)
                .where(TransactionModel.owner_id == owner_id)
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEventModel)
                .where(AuditEventModel.owner_id == owner_id)
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(IdempotencyRecordModel)
                .where(IdempotencyRecordModel.owner_id == owner_id)
            )
            == 2
        )

        with pytest.raises(DBAPIError):
            session.execute(
                update(TransactionModel)
                .where(TransactionModel.id == original.id)
                .values(description="rewrite history")
            )


def test_unit_of_work_rolls_back_all_rows_after_commit_failure(postgres_engine: Engine) -> None:
    owner_id = _create_owner(postgres_engine)
    account = _account(owner_id, "Duplicate")
    factory = PostgresUnitOfWorkFactory(postgres_engine)

    with pytest.raises(IntegrityError), factory.open(owner_id) as uow:
        uow.ledger.add_account(account)
        uow.ledger.add_account(account)
        uow.commit()

    with Session(postgres_engine) as session:
        assert session.get(AccountModel, account.id) is None


def test_account_mutation_uses_optimistic_version(postgres_engine: Engine) -> None:
    owner_id = _create_owner(postgres_engine)
    account = _account(owner_id, "Mutable")
    factory = PostgresUnitOfWorkFactory(postgres_engine)
    with factory.open(owner_id) as uow:
        uow.ledger.add_account(account)
        uow.commit()

    with factory.open(owner_id) as uow:
        updated = uow.ledger.save_account(replace(account, name="New name"))
        uow.commit()
    assert updated.version == 2

    with factory.open(owner_id) as uow, pytest.raises(ConcurrentModificationError):
        uow.ledger.save_account(replace(account, name="Stale name"))
