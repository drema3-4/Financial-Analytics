from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, time, timedelta
from uuid import UUID, uuid4

from financial_analytics_app.ledger import (
    LedgerService,
    ResourceConflictError,
    ResourceNotFoundError,
)
from financial_analytics_app.ports import AuditEvent, SchedulingRepository
from financial_analytics_domain import (
    CatchUpPolicy,
    Instant,
    MissingDayPolicy,
    Money,
    OutboxJob,
    RecurrenceFrequency,
    RecurringOperation,
    RecurringRule,
    RecurringRuleStatus,
    Transaction,
    TransactionKind,
    first_occurrence,
    occurrences_on_or_after,
)
from financial_analytics_domain.errors import DomainError


@dataclass(frozen=True, slots=True)
class WorkerTickResult:
    materialized: int
    claimed: int
    succeeded: int
    failed: int


class SchedulingService:
    """Application use cases for tenant-scoped recurring-rule management."""

    def __init__(
        self,
        repository: SchedulingRepository,
        *,
        clock: Callable[[], Instant] = Instant.now,
        uuid_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._uuid_factory = uuid_factory

    def create_rule(
        self,
        *,
        owner_id: UUID,
        actor_id: UUID,
        operation: RecurringOperation,
        frequency: RecurrenceFrequency,
        starts_on: date,
        local_time: time,
        timezone: str,
        missing_day_policy: MissingDayPolicy,
        catch_up_policy: CatchUpPolicy,
        end_date: date | None,
        request_id: UUID | None,
    ) -> RecurringRule:
        self._require_actor(owner_id, actor_id)
        self._validate_operation(owner_id, operation)
        draft = RecurringRule(
            id=self._uuid_factory(),
            owner_id=owner_id,
            operation=operation,
            frequency=frequency,
            starts_on=starts_on,
            local_time=local_time,
            timezone=timezone,
            missing_day_policy=missing_day_policy,
            catch_up_policy=catch_up_policy,
            end_date=end_date,
            next_occurrence_at=None,
        )
        rule = draft.with_next(first_occurrence(draft))
        return self._repository.create_rule(
            rule,
            self._audit(
                rule,
                actor_id,
                "scheduling.rule_created",
                request_id,
                payload={"frequency": frequency.value, "kind": operation.kind.value},
            ),
        )

    def get_rule(self, owner_id: UUID, rule_id: UUID) -> RecurringRule:
        rule = self._repository.get_rule(owner_id, rule_id)
        if rule is None:
            raise ResourceNotFoundError("recurring rule was not found")
        return rule

    def list_rules(self, owner_id: UUID) -> tuple[RecurringRule, ...]:
        return self._repository.list_rules(owner_id)

    def update_rule(
        self,
        *,
        owner_id: UUID,
        actor_id: UUID,
        rule_id: UUID,
        expected_version: int,
        operation: RecurringOperation,
        frequency: RecurrenceFrequency,
        starts_on: date,
        local_time: time,
        timezone: str,
        missing_day_policy: MissingDayPolicy,
        catch_up_policy: CatchUpPolicy,
        end_date: date | None,
        request_id: UUID | None,
    ) -> RecurringRule:
        self._require_actor(owner_id, actor_id)
        current = self.get_rule(owner_id, rule_id)
        if current.version != expected_version:
            raise ResourceConflictError("recurring rule version is stale")
        self._validate_operation(owner_id, operation)
        schedule_changed = (
            current.frequency,
            current.starts_on,
            current.local_time,
            current.timezone,
            current.missing_day_policy,
            current.end_date,
        ) != (
            frequency,
            starts_on,
            local_time,
            timezone,
            missing_day_policy,
            end_date,
        )
        updated = replace(
            current,
            operation=operation,
            frequency=frequency,
            starts_on=starts_on,
            local_time=local_time,
            timezone=timezone,
            missing_day_policy=missing_day_policy,
            catch_up_policy=catch_up_policy,
            end_date=end_date,
        )
        if schedule_changed:
            next_values = occurrences_on_or_after(updated, self._clock(), limit=1)
            updated = replace(
                updated,
                next_occurrence_at=next_values[0] if next_values else None,
                status=(
                    RecurringRuleStatus.COMPLETED
                    if not next_values
                    else (
                        RecurringRuleStatus.PAUSED
                        if current.status is RecurringRuleStatus.PAUSED
                        else RecurringRuleStatus.ACTIVE
                    )
                ),
            )
        return self._repository.save_rule(
            updated,
            expected_version=expected_version,
            audit_event=self._audit(
                updated,
                actor_id,
                "scheduling.rule_updated",
                request_id,
                payload={"schedule_changed": schedule_changed},
            ),
        )

    def pause_rule(
        self,
        owner_id: UUID,
        actor_id: UUID,
        rule_id: UUID,
        expected_version: int,
        request_id: UUID | None,
    ) -> RecurringRule:
        return self._set_paused(owner_id, actor_id, rule_id, expected_version, True, request_id)

    def resume_rule(
        self,
        owner_id: UUID,
        actor_id: UUID,
        rule_id: UUID,
        expected_version: int,
        request_id: UUID | None,
    ) -> RecurringRule:
        return self._set_paused(owner_id, actor_id, rule_id, expected_version, False, request_id)

    def preview(
        self,
        *,
        frequency: RecurrenceFrequency,
        starts_on: date,
        local_time: time,
        timezone: str,
        missing_day_policy: MissingDayPolicy,
        end_date: date | None,
        from_at: Instant | None,
        limit: int,
    ) -> tuple[Instant, ...]:
        placeholder = RecurringOperation(
            kind=TransactionKind.TRANSFER,
            account_id=UUID(int=1),
            destination_account_id=UUID(int=2),
            amount=self._preview_money(),
        )
        draft = RecurringRule(
            id=UUID(int=0),
            owner_id=UUID(int=0),
            operation=placeholder,
            frequency=frequency,
            starts_on=starts_on,
            local_time=local_time,
            timezone=timezone,
            missing_day_policy=missing_day_policy,
            catch_up_policy=CatchUpPolicy.ALL,
            end_date=end_date,
            next_occurrence_at=None,
        )
        return occurrences_on_or_after(draft, from_at or self._clock(), limit=limit)

    def list_dead_letters(self, owner_id: UUID) -> tuple[OutboxJob, ...]:
        return self._repository.list_dead_letters(owner_id)

    def retry_dead_letter(
        self,
        *,
        owner_id: UUID,
        actor_id: UUID,
        job_id: UUID,
        request_id: UUID | None,
    ) -> OutboxJob:
        self._require_actor(owner_id, actor_id)
        event = AuditEvent(
            id=self._uuid_factory(),
            owner_id=owner_id,
            actor_id=actor_id,
            event_type="scheduling.dead_letter_retried",
            aggregate_type="outbox_job",
            aggregate_id=job_id,
            occurred_at=self._clock(),
            request_id=request_id,
        )
        job = self._repository.retry_dead_letter(
            owner_id,
            job_id,
            retried_at=event.occurred_at,
            audit_event=event,
        )
        if job is None:
            raise ResourceNotFoundError("dead-letter job was not found")
        return job

    def _set_paused(
        self,
        owner_id: UUID,
        actor_id: UUID,
        rule_id: UUID,
        expected_version: int,
        paused: bool,
        request_id: UUID | None,
    ) -> RecurringRule:
        self._require_actor(owner_id, actor_id)
        current = self.get_rule(owner_id, rule_id)
        if current.version != expected_version:
            raise ResourceConflictError("recurring rule version is stale")
        if current.status is RecurringRuleStatus.COMPLETED:
            raise ResourceConflictError("completed recurring rule cannot be paused or resumed")
        status = RecurringRuleStatus.PAUSED if paused else RecurringRuleStatus.ACTIVE
        if current.status is status:
            return current
        updated = replace(current, status=status)
        event_type = "scheduling.rule_paused" if paused else "scheduling.rule_resumed"
        return self._repository.save_rule(
            updated,
            expected_version=expected_version,
            audit_event=self._audit(updated, actor_id, event_type, request_id),
        )

    def _validate_operation(self, owner_id: UUID, operation: RecurringOperation) -> None:
        problem = self._repository.validate_operation(owner_id, operation)
        if problem is None:
            return
        if problem.endswith("_not_found"):
            raise ResourceNotFoundError("a recurring operation reference was not found")
        if problem == "account_archived":
            raise ResourceConflictError("archived accounts cannot be used by recurring rules")
        raise DomainError(problem.replace("_", " "))

    @staticmethod
    def _require_actor(owner_id: UUID, actor_id: UUID) -> None:
        if owner_id != actor_id:
            raise DomainError("actor must own the recurring rule")

    def _audit(
        self,
        rule: RecurringRule,
        actor_id: UUID,
        event_type: str,
        request_id: UUID | None,
        *,
        payload: dict[str, object] | None = None,
    ) -> AuditEvent:
        return AuditEvent(
            id=self._uuid_factory(),
            owner_id=rule.owner_id,
            actor_id=actor_id,
            event_type=event_type,
            aggregate_type="recurring_rule",
            aggregate_id=rule.id,
            occurred_at=self._clock(),
            request_id=request_id,
            payload=payload,
        )

    @staticmethod
    def _preview_money() -> Money:
        return Money.of("1.00", "USD")


class RecurringJobProcessor:
    """At-least-once job delivery with idempotent ledger effects."""

    def __init__(
        self,
        repository: SchedulingRepository,
        ledger: LedgerService,
        *,
        clock: Callable[[], Instant] = Instant.now,
        lease_duration: timedelta = timedelta(seconds=30),
        base_backoff: timedelta = timedelta(seconds=5),
        batch_size: int = 50,
        after_ledger_commit: Callable[[OutboxJob, Transaction], None] | None = None,
    ) -> None:
        self._repository = repository
        self._ledger = ledger
        self._clock = clock
        self._lease_duration = lease_duration
        self._base_backoff = base_backoff
        self._batch_size = batch_size
        self._after_ledger_commit = after_ledger_commit

    def tick(self, worker_id: str) -> WorkerTickResult:
        now = self._clock()
        materialized = self._repository.materialize_due(now, limit=self._batch_size)
        jobs = self._repository.claim_jobs(
            now,
            worker_id=worker_id,
            lease_duration=self._lease_duration,
            limit=self._batch_size,
        )
        succeeded = failed = 0
        for job in jobs:
            try:
                transaction = self._record(job)
            except Exception as error:
                self._repository.fail_job(
                    job.id,
                    worker_id=worker_id,
                    failed_at=self._clock(),
                    error=f"{type(error).__name__}: {error}"[:1000],
                    base_backoff=self._base_backoff,
                )
                failed += 1
                continue
            if self._after_ledger_commit is not None:
                self._after_ledger_commit(job, transaction)
            self._repository.complete_job(
                job.id,
                worker_id=worker_id,
                transaction_id=transaction.id,
                completed_at=self._clock(),
            )
            succeeded += 1
        return WorkerTickResult(materialized, len(jobs), succeeded, failed)

    def _record(self, job: OutboxJob) -> Transaction:
        operation = job.operation
        request_hash = _job_request_hash(job)
        if operation.kind is TransactionKind.INCOME:
            assert operation.category_id is not None
            return self._ledger.record_income(
                owner_id=job.owner_id,
                actor_id=job.owner_id,
                account_id=operation.account_id,
                category_id=operation.category_id,
                amount=operation.amount,
                occurred_at=job.occurrence_at,
                description=operation.description,
                source="recurring",
                tag_ids=operation.tag_ids,
                idempotency_key=job.dedup_key,
                request_hash=request_hash,
                request_id=None,
            )
        if operation.kind is TransactionKind.EXPENSE:
            assert operation.category_id is not None
            return self._ledger.record_expense(
                owner_id=job.owner_id,
                actor_id=job.owner_id,
                account_id=operation.account_id,
                category_id=operation.category_id,
                amount=operation.amount,
                occurred_at=job.occurrence_at,
                description=operation.description,
                source="recurring",
                tag_ids=operation.tag_ids,
                idempotency_key=job.dedup_key,
                request_hash=request_hash,
                request_id=None,
            )
        assert operation.destination_account_id is not None
        return self._ledger.record_transfer(
            owner_id=job.owner_id,
            actor_id=job.owner_id,
            source_account_id=operation.account_id,
            destination_account_id=operation.destination_account_id,
            amount=operation.amount,
            occurred_at=job.occurrence_at,
            description=operation.description,
            source="recurring",
            tag_ids=operation.tag_ids,
            idempotency_key=job.dedup_key,
            request_hash=request_hash,
            request_id=None,
        )


def _job_request_hash(job: OutboxJob) -> str:
    operation = job.operation
    payload = {
        "rule_id": str(job.rule_id),
        "occurrence_at": job.occurrence_at.value.isoformat(),
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
        "tag_ids": [str(tag_id) for tag_id in operation.tag_ids],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
