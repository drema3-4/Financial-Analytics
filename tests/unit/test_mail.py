from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from uuid import UUID

import pytest

from financial_analytics_app.mail import (
    EmailDeliveryJob,
    EmailJobProcessor,
    EmailJobState,
)
from financial_analytics_domain import EmailTokenPurpose, Instant
from financial_analytics_infra.mail import SmtpEmailSender


class FakeEmailRepository:
    def __init__(self, jobs: tuple[EmailDeliveryJob, ...]) -> None:
        self.jobs = {job.id: job for job in jobs}
        self.failures: list[str] = []

    def claim_jobs(
        self,
        now: Instant,
        *,
        worker_id: str,
        lease_duration: timedelta,
        limit: int,
    ) -> tuple[EmailDeliveryJob, ...]:
        claimed = tuple(self.jobs.values())[:limit]
        for job in claimed:
            self.jobs[job.id] = replace(job, state=EmailJobState.LEASED, attempts=job.attempts + 1)
        return tuple(self.jobs[job.id] for job in claimed)

    def complete_job(self, job_id: UUID, *, worker_id: str, completed_at: Instant) -> bool:
        self.jobs[job_id] = replace(
            self.jobs[job_id], state=EmailJobState.COMPLETED, text_body=None
        )
        return True

    def fail_job(
        self,
        job_id: UUID,
        *,
        worker_id: str,
        failed_at: Instant,
        error_code: str,
        base_backoff: timedelta,
    ) -> bool:
        self.failures.append(error_code)
        self.jobs[job_id] = replace(self.jobs[job_id], state=EmailJobState.PENDING)
        return True


class RecordingSender:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[tuple[str, str, str]] = []

    def send(self, *, recipient: str, subject: str, text_body: str) -> None:
        if self.fail:
            raise TimeoutError("sensitive upstream detail")
        self.sent.append((recipient, subject, text_body))


def make_job(job_id: int = 1) -> EmailDeliveryJob:
    now = Instant(datetime(2026, 10, 16, tzinfo=UTC))
    return EmailDeliveryJob(
        id=UUID(int=job_id),
        token_id=UUID(int=job_id + 100),
        purpose=EmailTokenPurpose.INVITATION,
        recipient="guest@example.test",
        subject="Invite",
        text_body="https://finance.example.test/invite?token=secret",
        state=EmailJobState.PENDING,
        attempts=0,
        available_at=now,
        created_at=now,
    )


def test_email_job_processor_delivers_and_clears_one_time_payload() -> None:
    job = make_job()
    repository = FakeEmailRepository((job,))
    sender = RecordingSender()
    result = EmailJobProcessor(repository, sender, clock=lambda: job.created_at).tick("worker")

    assert result.succeeded == 1
    assert sender.sent == [(job.recipient, job.subject, job.text_body)]
    assert repository.jobs[job.id].state is EmailJobState.COMPLETED
    assert repository.jobs[job.id].text_body is None


def test_email_job_processor_records_only_exception_class_on_failure() -> None:
    job = make_job()
    repository = FakeEmailRepository((job,))
    result = EmailJobProcessor(
        repository,
        RecordingSender(fail=True),
        clock=lambda: job.created_at,
    ).tick("worker")

    assert result.failed == 1
    assert repository.failures == ["TimeoutError"]
    assert "sensitive" not in " ".join(repository.failures)


def test_smtp_adapter_uses_starttls_auth_and_structured_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeSmtpConnection()
    monkeypatch.setattr(
        "financial_analytics_infra.mail.smtplib.SMTP",
        lambda host, port, timeout: connection,
    )
    sender = SmtpEmailSender(
        host="smtp.example.test",
        port=587,
        from_address="no-reply@example.test",
        security="starttls",
        username="relay-user",
        password="relay-password",
        timeout_seconds=5,
    )

    sender.send(
        recipient="guest@example.test",
        subject="Invitation",
        text_body="One-time link",
    )

    assert connection.started_tls
    assert connection.credentials == ("relay-user", "relay-password")
    assert connection.message is not None
    assert connection.message["To"] == "guest@example.test"
    assert connection.message["From"] == "no-reply@example.test"
    assert "One-time link" in connection.message.get_content()


class FakeSmtpConnection:
    def __init__(self) -> None:
        self.started_tls = False
        self.credentials: tuple[str, str] | None = None
        self.message: EmailMessage | None = None

    def __enter__(self) -> FakeSmtpConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def starttls(self, *, context: object) -> None:
        self.started_tls = True

    def login(self, username: str, password: str) -> None:
        self.credentials = (username, password)

    def send_message(self, message: EmailMessage) -> None:
        self.message = message
