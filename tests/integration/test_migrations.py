from __future__ import annotations

import os
from dataclasses import replace
from datetime import date, datetime, time
from uuid import uuid4

from alembic import command
from sqlalchemy import MetaData, Table, create_engine, inspect, select

from financial_analytics_app.deposits import DepositService
from financial_analytics_app.services import RecordTransaction
from financial_analytics_domain import Account, AccountKind, Currency, Instant, Money, Transaction
from financial_analytics_infra.repositories import PostgresUnitOfWorkFactory
from tests.integration.conftest import (
    _alembic_config,
    create_disposable_database,
    drop_disposable_database,
)
from tests.integration.test_ledger_api import _insert_owners


def test_clean_upgrade_and_empty_schema_downgrade() -> None:
    base_url = os.environ["TEST_DATABASE_URL"]
    database_url, admin_engine, database_name = create_disposable_database(base_url)
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    engine = create_engine(database_url)
    try:
        config = _alembic_config(database_url)
        command.upgrade(config, "head")
        command.check(config)
        assert {
            "users",
            "accounts",
            "transactions",
            "postings",
            "audit_events",
            "idempotency_records",
            "credentials",
            "sessions",
            "user_profiles",
            "email_allowlist",
            "invitations",
            "email_tokens",
            "recurring_rules",
            "outbox_jobs",
            "deposit_terms",
            "deposit_rate_periods",
            "forecast_scenarios",
            "financial_goals",
        }.issubset(inspect(engine).get_table_names())
        assert "is_mandatory" in {
            column["name"] for column in inspect(engine).get_columns("categories")
        }
        assert "ix_transactions_owner_id_occurred_at_id_posted" in {
            index["name"] for index in inspect(engine).get_indexes("transactions")
        }

        command.downgrade(config, "20261013_0001")
        assert inspect(engine).get_table_names() == ["alembic_version"]
    finally:
        engine.dispose()
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        drop_disposable_database(admin_engine, database_name)


def test_populated_legacy_deposits_keep_money_and_duplicates_can_be_archived() -> None:
    database_url, admin_engine, database_name = create_disposable_database(
        os.environ["TEST_DATABASE_URL"]
    )
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    engine = create_engine(database_url)
    try:
        config = _alembic_config(database_url)
        command.upgrade(config, "20261016_0011")
        owner = uuid4()
        _insert_owners(engine, owner)
        currency = Currency("RUB")
        principal = Account(uuid4(), owner, "Старый вклад", currency, AccountKind.DEPOSIT)
        equity = Account(uuid4(), owner, "Equity", currency, AccountKind.SYSTEM_EQUITY)
        factory = PostgresUnitOfWorkFactory(engine)
        with factory.open(owner) as uow:
            uow.ledger.add_account(principal)
            uow.ledger.add_account(equity)
            uow.commit()
        opening = Transaction.adjustment(
            id=uuid4(),
            owner_id=owner,
            asset=principal,
            equity_account=equity,
            amount=Money.of("1000.00", currency),
            occurred_at=Instant(datetime.fromisoformat("2026-01-01T08:00:00Z")),
            posting_ids=(uuid4(), uuid4()),
            description="Legacy opening",
        )
        RecordTransaction(factory).execute(
            opening, actor_id=owner, idempotency_key="legacy-opening", request_hash="a" * 64
        )
        terms_table = Table("deposit_terms", MetaData(), autoload_with=engine)
        rates_table = Table("deposit_rate_periods", MetaData(), autoload_with=engine)
        first, second = uuid4(), uuid4()
        with engine.begin() as connection:
            for deposit_id in (first, second):
                connection.execute(
                    terms_table.insert().values(
                        id=deposit_id,
                        owner_id=owner,
                        principal_account_id=principal.id,
                        currency="RUB",
                        opened_on=date(2026, 1, 1),
                        matures_on=date(2026, 3, 1),
                        capitalization_frequency="monthly_calendar_end",
                        day_count_convention="actual_365_fixed",
                        rounding_policy="half_even",
                        interest_rounding_frequency="capitalization",
                        timezone="UTC",
                        cashflow_cutoff_time=time(23, 59, 59),
                        cashflow_cutoff_inclusive=True,
                        early_close_policy="forfeit_interest",
                        early_close_rate=None,
                        tax_rate="0",
                        algorithm_version="deposit-interest-v1",
                    )
                )
                connection.execute(
                    rates_table.insert().values(
                        owner_id=owner,
                        deposit_id=deposit_id,
                        starts_on=date(2026, 1, 1),
                        ends_on=date(2026, 3, 1),
                        nominal_rate="0.365",
                    )
                )
        command.upgrade(config, "head")
        with factory.open(owner) as uow:
            assert uow.ledger.get_transaction(opening.id) == opening
            assert uow.ledger.rebuild_balances()[principal.id] == Money.of("1000", currency)
            assert len(uow.deposits.list()) == 2
            assert all(not item.automatic_interest for item in uow.deposits.list())
        service = DepositService(
            factory, clock=lambda: Instant(datetime.fromisoformat("2026-02-02T09:00:00Z"))
        )
        service.archive(
            owner_id=owner, actor_id=owner, deposit_id=first, expected_version=1, request_id=None
        )
        with factory.open(owner) as uow:
            account = uow.ledger.get_account(principal.id)
            assert account is not None and not account.archived
            survivor = uow.deposits.get(second)
            assert survivor is not None
        service.update(
            terms=replace(survivor, automatic_interest=True),
            actor_id=owner,
            expected_version=1,
            request_id=None,
        )
        with factory.open(owner) as uow:
            assert uow.ledger.rebuild_balances()[principal.id] == Money.of("1031", currency)
        command.check(config)
        # The migration did not duplicate the original opening posting.
        with engine.connect() as connection:
            assert (
                connection.scalar(select(terms_table.c.id).where(terms_table.c.id == first))
                == first
            )
    finally:
        engine.dispose()
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        drop_disposable_database(admin_engine, database_name)
