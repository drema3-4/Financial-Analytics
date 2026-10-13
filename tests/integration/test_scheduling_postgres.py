from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, time, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from financial_analytics_api.main import create_app
from financial_analytics_app import LedgerService, RecurringJobProcessor, SchedulingService
from financial_analytics_app.identity import (
    AuthenticatedSession,
    AuthService,
    CsrfValidationError,
)
from financial_analytics_domain import (
    CatchUpPolicy,
    Currency,
    EmailAddress,
    Instant,
    MissingDayPolicy,
    Money,
    OutboxJob,
    RecurrenceFrequency,
    RecurringOperation,
    RecurringRule,
    Transaction,
    TransactionKind,
    UserProfile,
    UserStatus,
)
from financial_analytics_infra.models import (
    AccountModel,
    AuditEventModel,
    CategoryModel,
    OutboxJobModel,
    PostingModel,
    TransactionModel,
    UserModel,
)
from financial_analytics_infra.repositories import PostgresUnitOfWorkFactory
from financial_analytics_infra.scheduling import PostgresSchedulingRepository
from financial_analytics_infra.settings import AppEnvironment, Settings

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
TODAY = NOW.date()


class MutableClock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> Instant:
        return Instant(self.value)


class StubApiAuth:
    def __init__(self, profiles: dict[str, UserProfile]) -> None:
        self._profiles = profiles

    def authenticate_access(self, raw_token: str) -> AuthenticatedSession:
        profile = self._profiles[raw_token]
        return AuthenticatedSession(profile, uuid4(), "unused-in-stub")

    def verify_csrf(
        self,
        authenticated: AuthenticatedSession,
        *,
        cookie_token: str | None,
        header_token: str | None,
    ) -> None:
        expected = f"csrf-{authenticated.profile.id}"
        if cookie_token != expected or header_token != expected:
            raise CsrfValidationError("invalid csrf")


def _profile(owner_id: UUID, token: str) -> UserProfile:
    return UserProfile(
        id=owner_id,
        email=EmailAddress(f"{token}@example.test"),
        base_currency=Currency("RUB"),
        locale="ru-RU",
        timezone="Europe/Saratov",
        status=UserStatus.ACTIVE,
        is_master=False,
        created_at=Instant(NOW),
    )


def _seed_ledger(engine: Engine, owner_id: UUID) -> tuple[UUID, UUID]:
    account_id, category_id = uuid4(), uuid4()
    with Session(engine) as session:
        session.add(UserModel(id=owner_id))
        session.flush()
        session.add(
            AccountModel(
                id=account_id,
                owner_id=owner_id,
                name="Schedule account",
                kind="bank",
                currency="RUB",
            )
        )
        session.add(
            CategoryModel(
                id=category_id,
                owner_id=owner_id,
                name=f"Income {owner_id}",
                kind="income",
            )
        )
        session.commit()
    return account_id, category_id


def _operation(
    account_id: UUID,
    category_id: UUID,
    *,
    amount: str = "10.00",
    description: str = "scheduled",
) -> RecurringOperation:
    return RecurringOperation(
        kind=TransactionKind.INCOME,
        account_id=account_id,
        category_id=category_id,
        amount=Money.of(amount, "RUB"),
        description=description,
    )


def _create_rule(
    service: SchedulingService,
    owner_id: UUID,
    operation: RecurringOperation,
    *,
    starts_on: date = TODAY,
    end_date: date | None = TODAY,
    catch_up_policy: CatchUpPolicy = CatchUpPolicy.ALL,
) -> RecurringRule:
    return service.create_rule(
        owner_id=owner_id,
        actor_id=owner_id,
        operation=operation,
        frequency=RecurrenceFrequency.DAILY,
        starts_on=starts_on,
        local_time=time(9),
        timezone="UTC",
        missing_day_policy=MissingDayPolicy.LAST_DAY,
        catch_up_policy=catch_up_policy,
        end_date=end_date,
        request_id=None,
    )


def _processor(
    engine: Engine,
    repository: PostgresSchedulingRepository,
    clock: MutableClock,
    *,
    after_commit: Callable[[OutboxJob, Transaction], None] | None = None,
) -> RecurringJobProcessor:
    return RecurringJobProcessor(
        repository,
        LedgerService(PostgresUnitOfWorkFactory(engine), clock=clock),
        clock=clock,
        lease_duration=timedelta(seconds=10),
        base_backoff=timedelta(seconds=1),
        after_ledger_commit=after_commit,
    )


def test_crash_after_commit_and_double_delivery_create_one_transaction(
    postgres_engine: Engine,
) -> None:
    owner_id = uuid4()
    account_id, category_id = _seed_ledger(postgres_engine, owner_id)
    clock = MutableClock()
    repository = PostgresSchedulingRepository(postgres_engine)
    service = SchedulingService(repository, clock=clock)
    _create_rule(service, owner_id, _operation(account_id, category_id))

    def crash_after_commit(*_: object) -> None:
        raise RuntimeError("simulated process crash")

    with pytest.raises(RuntimeError, match="simulated process crash"):
        _processor(postgres_engine, repository, clock, after_commit=crash_after_commit).tick(
            "worker-crash"
        )

    with Session(postgres_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(TransactionModel)
                .where(TransactionModel.owner_id == owner_id)
            )
            == 1
        )
        job = session.scalar(select(OutboxJobModel).where(OutboxJobModel.owner_id == owner_id))
        assert job is not None and job.state == "leased" and job.attempts == 1

    clock.value += timedelta(seconds=11)
    result = _processor(postgres_engine, repository, clock).tick("worker-restarted")
    assert result.succeeded == 1
    with Session(postgres_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(TransactionModel)
                .where(TransactionModel.owner_id == owner_id)
            )
            == 1
        )
        job = session.scalar(select(OutboxJobModel).where(OutboxJobModel.owner_id == owner_id))
        assert job is not None and job.state == "succeeded" and job.attempts == 2
    with Session(postgres_engine) as session, pytest.raises(DBAPIError):
        job = session.scalar(select(OutboxJobModel).where(OutboxJobModel.owner_id == owner_id))
        assert job is not None
        job.payload = {"kind": "tampered"}
        session.commit()


def test_two_workers_use_skip_locked_and_do_not_duplicate_occurrence(
    postgres_engine: Engine,
) -> None:
    owner_id = uuid4()
    account_id, category_id = _seed_ledger(postgres_engine, owner_id)
    clock = MutableClock()
    repository = PostgresSchedulingRepository(postgres_engine)
    _create_rule(
        SchedulingService(repository, clock=clock),
        owner_id,
        _operation(account_id, category_id),
    )

    def run(worker_id: str) -> object:
        local_repository = PostgresSchedulingRepository(postgres_engine)
        return _processor(postgres_engine, local_repository, clock).tick(worker_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run, ("worker-a", "worker-b")))

    with Session(postgres_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxJobModel)
                .where(OutboxJobModel.owner_id == owner_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(TransactionModel)
                .where(TransactionModel.owner_id == owner_id)
            )
            == 1
        )


def test_missed_runs_apply_all_or_latest_catch_up_policy(postgres_engine: Engine) -> None:
    owner_id = uuid4()
    account_id, category_id = _seed_ledger(postgres_engine, owner_id)
    clock = MutableClock()
    repository = PostgresSchedulingRepository(postgres_engine)
    service = SchedulingService(repository, clock=clock)
    start = NOW.date() - timedelta(days=3)
    _create_rule(
        service,
        owner_id,
        _operation(account_id, category_id, description="catch-up-all"),
        starts_on=start,
        catch_up_policy=CatchUpPolicy.ALL,
    )
    _create_rule(
        service,
        owner_id,
        _operation(account_id, category_id, description="catch-up-latest"),
        starts_on=start,
        catch_up_policy=CatchUpPolicy.LATEST,
    )
    processor = _processor(postgres_engine, repository, clock)
    for _ in range(4):
        processor.tick("catch-up-worker")

    with Session(postgres_engine) as session:
        rows = session.scalars(
            select(TransactionModel)
            .where(TransactionModel.owner_id == owner_id)
            .order_by(TransactionModel.occurred_at)
        ).all()
        all_rows = [row for row in rows if row.description == "catch-up-all"]
        latest_rows = [row for row in rows if row.description == "catch-up-latest"]
        assert [row.occurred_at.date() for row in all_rows] == [
            start + timedelta(days=offset) for offset in range(4)
        ]
        assert [row.occurred_at.date() for row in latest_rows] == [NOW.date()]


def test_rule_edit_changes_only_future_operations(postgres_engine: Engine) -> None:
    owner_id = uuid4()
    account_id, category_id = _seed_ledger(postgres_engine, owner_id)
    clock = MutableClock()
    repository = PostgresSchedulingRepository(postgres_engine)
    service = SchedulingService(repository, clock=clock)
    rule = _create_rule(
        service,
        owner_id,
        _operation(account_id, category_id, amount="10.00", description="before-edit"),
        end_date=NOW.date() + timedelta(days=1),
    )
    _processor(postgres_engine, repository, clock).tick("edit-worker")

    current = service.get_rule(owner_id, rule.id)
    service.update_rule(
        owner_id=owner_id,
        actor_id=owner_id,
        rule_id=rule.id,
        expected_version=current.version,
        operation=_operation(account_id, category_id, amount="20.00", description="after-edit"),
        frequency=current.frequency,
        starts_on=current.starts_on,
        local_time=current.local_time,
        timezone=current.timezone,
        missing_day_policy=current.missing_day_policy,
        catch_up_policy=current.catch_up_policy,
        end_date=current.end_date,
        request_id=None,
    )
    clock.value += timedelta(days=1)
    _processor(postgres_engine, repository, clock).tick("edit-worker")

    with Session(postgres_engine) as session:
        rows = session.execute(
            select(TransactionModel.description, func.max(func.abs(PostingModel.amount)))
            .join(PostingModel, PostingModel.transaction_id == TransactionModel.id)
            .where(TransactionModel.owner_id == owner_id)
            .group_by(TransactionModel.id, TransactionModel.description)
            .order_by(TransactionModel.occurred_at)
        ).all()
        assert [(description, str(amount)) for description, amount in rows] == [
            ("before-edit", "10.000000000"),
            ("after-edit", "20.000000000"),
        ]


def test_dead_letter_is_visible_and_manual_retry_is_audited(postgres_engine: Engine) -> None:
    owner_id = uuid4()
    account_id, category_id = _seed_ledger(postgres_engine, owner_id)
    clock = MutableClock()
    repository = PostgresSchedulingRepository(postgres_engine)
    service = SchedulingService(repository, clock=clock)
    _create_rule(service, owner_id, _operation(account_id, category_id))
    assert repository.materialize_due(clock(), limit=10) == 1
    with Session(postgres_engine) as session:
        account = session.get(AccountModel, account_id)
        assert account is not None
        account.archived = True
        job = session.scalar(select(OutboxJobModel).where(OutboxJobModel.owner_id == owner_id))
        assert job is not None
        job.max_attempts = 1
        session.commit()

    result = _processor(postgres_engine, repository, clock).tick("failing-worker")
    assert result.failed == 1
    dead_letters = service.list_dead_letters(owner_id)
    assert len(dead_letters) == 1 and dead_letters[0].state.value == "dead_letter"

    with Session(postgres_engine) as session:
        account = session.get(AccountModel, account_id)
        assert account is not None
        account.archived = False
        session.commit()
    retried = service.retry_dead_letter(
        owner_id=owner_id,
        actor_id=owner_id,
        job_id=dead_letters[0].id,
        request_id=None,
    )
    assert retried.state.value == "pending" and retried.attempts == 0
    assert _processor(postgres_engine, repository, clock).tick("retry-worker").succeeded == 1

    with Session(postgres_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEventModel)
                .where(
                    AuditEventModel.owner_id == owner_id,
                    AuditEventModel.event_type == "scheduling.dead_letter_retried",
                )
            )
            == 1
        )
    assert service.list_dead_letters(owner_id) == ()


def test_expired_final_attempt_lease_moves_to_dead_letter(postgres_engine: Engine) -> None:
    owner_id = uuid4()
    account_id, category_id = _seed_ledger(postgres_engine, owner_id)
    clock = MutableClock()
    repository = PostgresSchedulingRepository(postgres_engine)
    service = SchedulingService(repository, clock=clock)
    _create_rule(service, owner_id, _operation(account_id, category_id))
    assert repository.materialize_due(clock(), limit=10) == 1
    with Session(postgres_engine) as session:
        job = session.scalar(select(OutboxJobModel).where(OutboxJobModel.owner_id == owner_id))
        assert job is not None
        job.max_attempts = 1
        session.commit()

    claimed = repository.claim_jobs(
        clock(), worker_id="crashed-final-worker", lease_duration=timedelta(seconds=10), limit=10
    )
    assert len(claimed) == 1 and claimed[0].attempts == 1
    clock.value += timedelta(seconds=11)
    assert (
        repository.claim_jobs(
            clock(), worker_id="recovery-worker", lease_duration=timedelta(seconds=10), limit=10
        )
        == ()
    )
    dead_letters = service.list_dead_letters(owner_id)
    assert len(dead_letters) == 1
    assert dead_letters[0].last_error == "lease expired after final attempt"


def test_recurring_api_preview_management_and_owner_isolation(postgres_engine: Engine) -> None:
    owner_id, other_owner_id = uuid4(), uuid4()
    account_id, category_id = _seed_ledger(postgres_engine, owner_id)
    _seed_ledger(postgres_engine, other_owner_id)
    profiles = {
        "owner": _profile(owner_id, "owner"),
        "other": _profile(other_owner_id, "other"),
    }
    auth = StubApiAuth(profiles)
    repository = PostgresSchedulingRepository(postgres_engine)

    async def ready() -> bool:
        return True

    app = create_app(
        Settings(app_env=AppEnvironment.TEST, _env_file=None),
        ready,
        cast(AuthService, auth),
        LedgerService(PostgresUnitOfWorkFactory(postgres_engine)),
        SchedulingService(repository, clock=lambda: Instant(NOW)),
    )

    def client(token: str, owner: UUID) -> TestClient:
        result = TestClient(app, base_url="https://testserver")
        result.cookies.set("fa_access", token)
        result.cookies.set("fa_csrf", f"csrf-{owner}")
        return result

    schedule: dict[str, object] = {
        "frequency": "daily",
        "starts_on": NOW.date().isoformat(),
        "local_time": "09:00:00",
        "timezone": "UTC",
        "missing_day_policy": "last_day",
        "catch_up_policy": "all",
        "end_date": (NOW.date() + timedelta(days=2)).isoformat(),
    }
    with client("owner", owner_id) as owner, client("other", other_owner_id) as other:
        preview = owner.post(
            "/api/v1/recurring-rules/preview",
            json={**schedule, "count": 3, "from_at": NOW.isoformat()},
        )
        assert preview.status_code == 200
        assert len(preview.json()) == 3
        assert owner.get("/api/v1/transactions").json()["items"] == []

        created = owner.post(
            "/api/v1/recurring-rules",
            json={
                **schedule,
                "operation": {
                    "kind": "income",
                    "account_id": str(account_id),
                    "category_id": str(category_id),
                    "money": {"amount": "15.00", "currency": "RUB"},
                    "description": "API schedule",
                },
            },
            headers={"X-CSRF-Token": f"csrf-{owner_id}"},
        )
        assert created.status_code == 201, created.text
        rule = created.json()
        assert other.get(f"/api/v1/recurring-rules/{rule['id']}").status_code == 404
        assert other.get("/api/v1/recurring-rules").json() == []

        paused = owner.post(
            f"/api/v1/recurring-rules/{rule['id']}/pause",
            json={"version": rule["version"]},
            headers={"X-CSRF-Token": f"csrf-{owner_id}"},
        )
        assert paused.status_code == 200 and paused.json()["status"] == "paused"
        resumed = owner.post(
            f"/api/v1/recurring-rules/{rule['id']}/resume",
            json={"version": paused.json()["version"]},
            headers={"X-CSRF-Token": f"csrf-{owner_id}"},
        )
        assert resumed.status_code == 200 and resumed.json()["status"] == "active"
