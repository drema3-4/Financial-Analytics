from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from financial_analytics_domain import EmailTokenPurpose, Instant


class EmailJobState(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    COMPLETED = "completed"
    DEAD_LETTER = "dead_letter"


@dataclass(frozen=True, slots=True)
class EmailDeliveryJob:
    id: UUID
    token_id: UUID
    purpose: EmailTokenPurpose
    recipient: str
    subject: str
    text_body: str | None
    state: EmailJobState
    attempts: int
    available_at: Instant
    created_at: Instant


@dataclass(frozen=True, slots=True)
class EmailJobTickResult:
    materialized: int
    claimed: int
    succeeded: int
    failed: int


class EmailSender(Protocol):
    def send(self, *, recipient: str, subject: str, text_body: str) -> None: ...


class EmailJobRepository(Protocol):
    def claim_jobs(
        self,
        now: Instant,
        *,
        worker_id: str,
        lease_duration: timedelta,
        limit: int,
    ) -> tuple[EmailDeliveryJob, ...]: ...

    def complete_job(self, job_id: UUID, *, worker_id: str, completed_at: Instant) -> bool: ...

    def fail_job(
        self,
        job_id: UUID,
        *,
        worker_id: str,
        failed_at: Instant,
        error_code: str,
        base_backoff: timedelta,
    ) -> bool: ...


class EmailJobProcessor:
    """Deliver durable identity mail without logging recipient, link, or SMTP details."""

    def __init__(
        self,
        repository: EmailJobRepository,
        sender: EmailSender,
        *,
        clock: Callable[[], Instant] = Instant.now,
        lease_duration: timedelta = timedelta(minutes=2),
        base_backoff: timedelta = timedelta(seconds=10),
        batch_size: int = 1,
    ) -> None:
        self._repository = repository
        self._sender = sender
        self._clock = clock
        self._lease_duration = lease_duration
        self._base_backoff = base_backoff
        self._batch_size = batch_size

    def tick(self, worker_id: str) -> EmailJobTickResult:
        jobs = self._repository.claim_jobs(
            self._clock(),
            worker_id=worker_id,
            lease_duration=self._lease_duration,
            limit=self._batch_size,
        )
        succeeded = failed = 0
        for job in jobs:
            try:
                if job.text_body is None:
                    raise ValueError("email job payload is unavailable")
                self._sender.send(
                    recipient=job.recipient,
                    subject=job.subject,
                    text_body=job.text_body,
                )
            except Exception as error:
                self._repository.fail_job(
                    job.id,
                    worker_id=worker_id,
                    failed_at=self._clock(),
                    error_code=type(error).__name__[:100],
                    base_backoff=self._base_backoff,
                )
                failed += 1
                continue
            self._repository.complete_job(
                job.id,
                worker_id=worker_id,
                completed_at=self._clock(),
            )
            succeeded += 1
        return EmailJobTickResult(0, len(jobs), succeeded, failed)


class CompositeJobProcessor:
    """Run independent durable processors in one worker tick."""

    def __init__(self, *processors: object) -> None:
        self._processors = processors

    def tick(self, worker_id: str) -> EmailJobTickResult:
        totals = [0, 0, 0, 0]
        for processor in self._processors:
            result = processor.tick(worker_id)  # type: ignore[attr-defined]
            totals[0] += int(getattr(result, "materialized", 0))
            totals[1] += int(getattr(result, "claimed", 0))
            totals[2] += int(getattr(result, "succeeded", 0))
            totals[3] += int(getattr(result, "failed", 0))
        return EmailJobTickResult(*totals)
