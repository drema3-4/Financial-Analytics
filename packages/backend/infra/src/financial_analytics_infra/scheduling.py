from __future__ import annotations

from datetime import timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import Engine, and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from financial_analytics_app.ports import AuditEvent
from financial_analytics_app.services import ConcurrentModificationError
from financial_analytics_domain import (
    AccountKind,
    CatchUpPolicy,
    CategoryKind,
    Currency,
    Instant,
    MissingDayPolicy,
    Money,
    OutboxJob,
    OutboxJobState,
    RecurrenceFrequency,
    RecurringOperation,
    RecurringRule,
    RecurringRuleStatus,
    TransactionKind,
    latest_due_occurrence,
    next_occurrence,
    occurrence_dedup_key,
)
from financial_analytics_infra.models import (
    AccountModel,
    AuditEventModel,
    CategoryModel,
    OutboxJobModel,
    RecurringRuleModel,
    TagModel,
)


class PostgresSchedulingRepository:
    """PostgreSQL implementation of recurring rules and the leased outbox."""

    def __init__(self, engine: Engine) -> None:
        self._session_factory = sessionmaker(engine, expire_on_commit=False)

    def validate_operation(self, owner_id: UUID, operation: RecurringOperation) -> str | None:
        with self._session_factory() as session:
            account = session.scalar(
                select(AccountModel).where(
                    AccountModel.owner_id == owner_id,
                    AccountModel.id == operation.account_id,
                )
            )
            if account is None or not AccountKind(account.kind).is_asset:
                return "account_not_found"
            if account.archived:
                return "account_archived"
            if account.currency != operation.amount.currency.code:
                return "account currency mismatch"
            if operation.destination_account_id is not None:
                destination = session.scalar(
                    select(AccountModel).where(
                        AccountModel.owner_id == owner_id,
                        AccountModel.id == operation.destination_account_id,
                    )
                )
                if destination is None or not AccountKind(destination.kind).is_asset:
                    return "destination_not_found"
                if destination.archived:
                    return "account_archived"
                if destination.currency != account.currency:
                    return "transfer currency mismatch"
            if operation.category_id is not None:
                category = session.scalar(
                    select(CategoryModel).where(
                        CategoryModel.owner_id == owner_id,
                        CategoryModel.id == operation.category_id,
                    )
                )
                if category is None:
                    return "category_not_found"
                expected = (
                    CategoryKind.INCOME
                    if operation.kind is TransactionKind.INCOME
                    else CategoryKind.EXPENSE
                )
                if CategoryKind(category.kind) is not expected:
                    return "category kind mismatch"
            if operation.tag_ids:
                found = session.scalars(
                    select(TagModel.id).where(
                        TagModel.owner_id == owner_id,
                        TagModel.id.in_(operation.tag_ids),
                    )
                ).all()
                if len(found) != len(operation.tag_ids):
                    return "tag_not_found"
        return None

    def create_rule(self, rule: RecurringRule, audit_event: AuditEvent) -> RecurringRule:
        with self._session_factory() as session, session.begin():
            row = RecurringRuleModel(
                id=rule.id,
                owner_id=rule.owner_id,
                account_id=rule.operation.account_id,
                destination_account_id=rule.operation.destination_account_id,
                category_id=rule.operation.category_id,
                kind=rule.operation.kind.value,
                amount=rule.operation.amount.amount,
                currency=rule.operation.amount.currency.code,
                description=rule.operation.description,
                tag_ids=[str(value) for value in rule.operation.tag_ids],
                frequency=rule.frequency.value,
                starts_on=rule.starts_on,
                local_time=rule.local_time,
                timezone=rule.timezone,
                missing_day_policy=rule.missing_day_policy.value,
                catch_up_policy=rule.catch_up_policy.value,
                end_date=rule.end_date,
                next_occurrence_at=(
                    None if rule.next_occurrence_at is None else rule.next_occurrence_at.value
                ),
                status=rule.status.value,
                version=rule.version,
                updated_at=audit_event.occurred_at.value,
            )
            session.add(row)
            self._append_audit(session, audit_event)
            session.flush()
            return _rule_from_row(row)

    def get_rule(self, owner_id: UUID, rule_id: UUID) -> RecurringRule | None:
        with self._session_factory() as session:
            row = session.scalar(
                select(RecurringRuleModel).where(
                    RecurringRuleModel.owner_id == owner_id,
                    RecurringRuleModel.id == rule_id,
                )
            )
            return None if row is None else _rule_from_row(row)

    def list_rules(self, owner_id: UUID) -> tuple[RecurringRule, ...]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(RecurringRuleModel)
                .where(RecurringRuleModel.owner_id == owner_id)
                .order_by(RecurringRuleModel.created_at, RecurringRuleModel.id)
            ).all()
            return tuple(_rule_from_row(row) for row in rows)

    def save_rule(
        self,
        rule: RecurringRule,
        *,
        expected_version: int,
        audit_event: AuditEvent,
    ) -> RecurringRule:
        with self._session_factory() as session, session.begin():
            row = session.scalar(
                select(RecurringRuleModel)
                .where(
                    RecurringRuleModel.owner_id == rule.owner_id,
                    RecurringRuleModel.id == rule.id,
                )
                .with_for_update()
            )
            if row is None:
                raise ConcurrentModificationError("recurring rule no longer exists")
            if row.version != expected_version:
                raise ConcurrentModificationError("recurring rule version is stale")
            row.account_id = rule.operation.account_id
            row.destination_account_id = rule.operation.destination_account_id
            row.category_id = rule.operation.category_id
            row.kind = rule.operation.kind.value
            row.amount = rule.operation.amount.amount
            row.currency = rule.operation.amount.currency.code
            row.description = rule.operation.description
            row.tag_ids = [str(value) for value in rule.operation.tag_ids]
            row.frequency = rule.frequency.value
            row.starts_on = rule.starts_on
            row.local_time = rule.local_time
            row.timezone = rule.timezone
            row.missing_day_policy = rule.missing_day_policy.value
            row.catch_up_policy = rule.catch_up_policy.value
            row.end_date = rule.end_date
            row.next_occurrence_at = (
                None if rule.next_occurrence_at is None else rule.next_occurrence_at.value
            )
            row.status = rule.status.value
            row.updated_at = audit_event.occurred_at.value
            self._append_audit(session, audit_event)
            session.flush()
            return _rule_from_row(row)

    def materialize_due(self, now: Instant, *, limit: int) -> int:
        with self._session_factory() as session, session.begin():
            rows = session.scalars(
                select(RecurringRuleModel)
                .where(
                    RecurringRuleModel.status == RecurringRuleStatus.ACTIVE.value,
                    RecurringRuleModel.next_occurrence_at.is_not(None),
                    RecurringRuleModel.next_occurrence_at <= now.value,
                )
                .order_by(RecurringRuleModel.next_occurrence_at, RecurringRuleModel.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
            materialized = 0
            for row in rows:
                rule = _rule_from_row(row)
                assert rule.next_occurrence_at is not None
                if rule.catch_up_policy is CatchUpPolicy.LATEST:
                    occurrence, following = latest_due_occurrence(rule, now)
                    assert occurrence is not None
                else:
                    occurrence = rule.next_occurrence_at
                    following = next_occurrence(rule, occurrence)
                job_id = uuid4()
                inserted_id = session.scalar(
                    insert(OutboxJobModel)
                    .values(
                        id=job_id,
                        owner_id=rule.owner_id,
                        rule_id=rule.id,
                        occurrence_at=occurrence.value,
                        dedup_key=occurrence_dedup_key(rule.id, occurrence),
                        payload=_operation_payload(rule.operation),
                        state=OutboxJobState.PENDING.value,
                        attempts=0,
                        max_attempts=5,
                        available_at=now.value,
                        updated_at=now.value,
                    )
                    .on_conflict_do_nothing(index_elements=[OutboxJobModel.dedup_key])
                    .returning(OutboxJobModel.id)
                )
                materialized += int(inserted_id is not None)
                row.next_occurrence_at = None if following is None else following.value
                row.status = (
                    RecurringRuleStatus.COMPLETED.value
                    if following is None
                    else RecurringRuleStatus.ACTIVE.value
                )
                row.updated_at = now.value
            return materialized

    def claim_jobs(
        self,
        now: Instant,
        *,
        worker_id: str,
        lease_duration: timedelta,
        limit: int,
    ) -> tuple[OutboxJob, ...]:
        if not worker_id.strip() or len(worker_id) > 160:
            raise ValueError("worker_id must contain 1 to 160 characters")
        with self._session_factory() as session, session.begin():
            exhausted_leases = session.scalars(
                select(OutboxJobModel)
                .where(
                    OutboxJobModel.state == OutboxJobState.LEASED.value,
                    OutboxJobModel.lease_expires_at <= now.value,
                    OutboxJobModel.attempts >= OutboxJobModel.max_attempts,
                )
                .with_for_update(skip_locked=True)
            ).all()
            for exhausted in exhausted_leases:
                exhausted.state = OutboxJobState.DEAD_LETTER.value
                exhausted.lease_owner = None
                exhausted.lease_expires_at = None
                exhausted.last_error = "lease expired after final attempt"
                exhausted.available_at = now.value
                exhausted.updated_at = now.value
            rows = session.scalars(
                select(OutboxJobModel)
                .where(
                    OutboxJobModel.attempts < OutboxJobModel.max_attempts,
                    or_(
                        and_(
                            OutboxJobModel.state == OutboxJobState.PENDING.value,
                            OutboxJobModel.available_at <= now.value,
                        ),
                        and_(
                            OutboxJobModel.state == OutboxJobState.LEASED.value,
                            OutboxJobModel.lease_expires_at <= now.value,
                        ),
                    ),
                )
                .order_by(OutboxJobModel.available_at, OutboxJobModel.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
            claimed: list[OutboxJob] = []
            for row in rows:
                row.state = OutboxJobState.LEASED.value
                row.attempts += 1
                row.lease_owner = worker_id
                row.lease_expires_at = now.value + lease_duration
                row.updated_at = now.value
                session.flush()
                claimed.append(_job_from_row(row))
            return tuple(claimed)

    def complete_job(
        self,
        job_id: UUID,
        *,
        worker_id: str,
        transaction_id: UUID,
        completed_at: Instant,
    ) -> None:
        with self._session_factory() as session, session.begin():
            row = self._leased_job(session, job_id, worker_id)
            row.state = OutboxJobState.SUCCEEDED.value
            row.transaction_id = transaction_id
            row.lease_owner = None
            row.lease_expires_at = None
            row.last_error = None
            row.updated_at = completed_at.value

    def fail_job(
        self,
        job_id: UUID,
        *,
        worker_id: str,
        failed_at: Instant,
        error: str,
        base_backoff: timedelta,
    ) -> None:
        with self._session_factory() as session, session.begin():
            row = self._leased_job(session, job_id, worker_id)
            if row.attempts >= row.max_attempts:
                row.state = OutboxJobState.DEAD_LETTER.value
                row.available_at = failed_at.value
            else:
                exponent = max(0, row.attempts - 1)
                delay_seconds = min(base_backoff.total_seconds() * (2**exponent), 3600)
                row.state = OutboxJobState.PENDING.value
                row.available_at = failed_at.value + timedelta(seconds=delay_seconds)
            row.lease_owner = None
            row.lease_expires_at = None
            row.last_error = error
            row.updated_at = failed_at.value

    def list_dead_letters(self, owner_id: UUID) -> tuple[OutboxJob, ...]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(OutboxJobModel)
                .where(
                    OutboxJobModel.owner_id == owner_id,
                    OutboxJobModel.state == OutboxJobState.DEAD_LETTER.value,
                )
                .order_by(OutboxJobModel.updated_at.desc(), OutboxJobModel.id)
            ).all()
            return tuple(_job_from_row(row) for row in rows)

    def retry_dead_letter(
        self,
        owner_id: UUID,
        job_id: UUID,
        *,
        retried_at: Instant,
        audit_event: AuditEvent,
    ) -> OutboxJob | None:
        with self._session_factory() as session, session.begin():
            row = session.scalar(
                select(OutboxJobModel)
                .where(
                    OutboxJobModel.owner_id == owner_id,
                    OutboxJobModel.id == job_id,
                    OutboxJobModel.state == OutboxJobState.DEAD_LETTER.value,
                )
                .with_for_update()
            )
            if row is None:
                return None
            row.state = OutboxJobState.PENDING.value
            row.attempts = 0
            row.available_at = retried_at.value
            row.lease_owner = None
            row.lease_expires_at = None
            row.updated_at = retried_at.value
            self._append_audit(session, audit_event)
            session.flush()
            return _job_from_row(row)

    @staticmethod
    def _leased_job(session: Session, job_id: UUID, worker_id: str) -> OutboxJobModel:
        row = session.scalar(
            select(OutboxJobModel)
            .where(
                OutboxJobModel.id == job_id,
                OutboxJobModel.state == OutboxJobState.LEASED.value,
                OutboxJobModel.lease_owner == worker_id,
            )
            .with_for_update()
        )
        if row is None:
            raise RuntimeError("job lease is absent, expired, or owned by another worker")
        return row

    @staticmethod
    def _append_audit(session: Session, event: AuditEvent) -> None:
        session.add(
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


def _rule_from_row(row: RecurringRuleModel) -> RecurringRule:
    operation = RecurringOperation(
        kind=TransactionKind(row.kind),
        account_id=row.account_id,
        destination_account_id=row.destination_account_id,
        category_id=row.category_id,
        amount=Money.of(row.amount, Currency(row.currency)),
        description=row.description,
        tag_ids=tuple(UUID(value) for value in row.tag_ids),
    )
    return RecurringRule(
        id=row.id,
        owner_id=row.owner_id,
        operation=operation,
        frequency=RecurrenceFrequency(row.frequency),
        starts_on=row.starts_on,
        local_time=row.local_time,
        timezone=row.timezone,
        missing_day_policy=MissingDayPolicy(row.missing_day_policy),
        catch_up_policy=CatchUpPolicy(row.catch_up_policy),
        end_date=row.end_date,
        next_occurrence_at=(
            None if row.next_occurrence_at is None else Instant(row.next_occurrence_at)
        ),
        status=RecurringRuleStatus(row.status),
        version=row.version,
    )


def _operation_payload(operation: RecurringOperation) -> dict[str, object]:
    return {
        "kind": operation.kind.value,
        "account_id": str(operation.account_id),
        "destination_account_id": (
            None
            if operation.destination_account_id is None
            else str(operation.destination_account_id)
        ),
        "category_id": None if operation.category_id is None else str(operation.category_id),
        "amount": str(operation.amount.amount),
        "currency": operation.amount.currency.code,
        "description": operation.description,
        "tag_ids": [str(value) for value in operation.tag_ids],
    }


def _job_from_row(row: OutboxJobModel) -> OutboxJob:
    payload = row.payload
    operation = RecurringOperation(
        kind=TransactionKind(str(payload["kind"])),
        account_id=UUID(str(payload["account_id"])),
        destination_account_id=(
            None
            if payload.get("destination_account_id") is None
            else UUID(str(payload["destination_account_id"]))
        ),
        category_id=(
            None if payload.get("category_id") is None else UUID(str(payload["category_id"]))
        ),
        amount=Money.of(str(payload["amount"]), str(payload["currency"])),
        description=str(payload.get("description", "")),
        tag_ids=tuple(UUID(str(value)) for value in cast(list[object], payload.get("tag_ids", []))),
    )
    return OutboxJob(
        id=row.id,
        owner_id=row.owner_id,
        rule_id=row.rule_id,
        occurrence_at=Instant(row.occurrence_at),
        operation=operation,
        dedup_key=row.dedup_key,
        state=OutboxJobState(row.state),
        attempts=row.attempts,
        max_attempts=row.max_attempts,
        available_at=Instant(row.available_at),
        lease_owner=row.lease_owner,
        lease_expires_at=(None if row.lease_expires_at is None else Instant(row.lease_expires_at)),
        last_error=row.last_error,
        transaction_id=row.transaction_id,
    )
