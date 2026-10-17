from __future__ import annotations

import smtplib
import ssl
from datetime import timedelta
from email.message import EmailMessage
from uuid import UUID

from sqlalchemy import Engine, and_, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from financial_analytics_app.mail import EmailDeliveryJob, EmailJobState
from financial_analytics_domain import EmailTokenPurpose, Instant
from financial_analytics_infra.models import EmailDeliveryJobModel, EmailTokenModel


class SmtpEmailSender:
    """Minimal SMTP adapter; callers never receive transport response bodies."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        from_address: str,
        security: str,
        username: str | None,
        password: str | None,
        timeout_seconds: float,
    ) -> None:
        self._host = host
        self._port = port
        self._from_address = from_address
        self._security = security
        self._username = username
        self._password = password
        self._timeout_seconds = timeout_seconds

    def send(self, *, recipient: str, subject: str, text_body: str) -> None:
        message = EmailMessage()
        message["From"] = self._from_address
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(text_body)
        context = ssl.create_default_context()
        if self._security == "tls":
            connection: smtplib.SMTP = smtplib.SMTP_SSL(
                self._host,
                self._port,
                timeout=self._timeout_seconds,
                context=context,
            )
        else:
            connection = smtplib.SMTP(
                self._host,
                self._port,
                timeout=self._timeout_seconds,
            )
        with connection:
            if self._security == "starttls":
                connection.starttls(context=context)
            if self._username is not None and self._password is not None:
                connection.login(self._username, self._password)
            connection.send_message(message)


class PostgresEmailJobRepository:
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    def claim_jobs(
        self,
        now: Instant,
        *,
        worker_id: str,
        lease_duration: timedelta,
        limit: int,
    ) -> tuple[EmailDeliveryJob, ...]:
        with self._sessions() as session, session.begin():
            unusable_tokens = select(EmailTokenModel.id).where(
                or_(
                    EmailTokenModel.expires_at <= now.value,
                    EmailTokenModel.consumed_at.is_not(None),
                    EmailTokenModel.revoked_at.is_not(None),
                )
            )
            session.execute(
                update(EmailDeliveryJobModel)
                .where(
                    or_(
                        EmailDeliveryJobModel.state == EmailJobState.PENDING.value,
                        and_(
                            EmailDeliveryJobModel.state == EmailJobState.LEASED.value,
                            EmailDeliveryJobModel.leased_until <= now.value,
                        ),
                    ),
                    or_(
                        EmailDeliveryJobModel.token_id.in_(unusable_tokens),
                        EmailDeliveryJobModel.attempts >= 5,
                    ),
                )
                .values(
                    state=EmailJobState.DEAD_LETTER.value,
                    text_body=None,
                    last_error="TokenUnavailable",
                    lease_owner=None,
                    leased_until=None,
                )
            )
            rows = session.scalars(
                select(EmailDeliveryJobModel)
                .where(
                    or_(
                        and_(
                            EmailDeliveryJobModel.state == EmailJobState.PENDING.value,
                            EmailDeliveryJobModel.available_at <= now.value,
                        ),
                        and_(
                            EmailDeliveryJobModel.state == EmailJobState.LEASED.value,
                            EmailDeliveryJobModel.leased_until <= now.value,
                        ),
                    )
                )
                .order_by(EmailDeliveryJobModel.available_at, EmailDeliveryJobModel.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
            claimed: list[EmailDeliveryJob] = []
            for row in rows:
                row.state = EmailJobState.LEASED.value
                row.attempts += 1
                row.lease_owner = worker_id
                row.leased_until = now.value + lease_duration
                session.flush()
                claimed.append(_job_from_row(row))
            return tuple(claimed)

    def complete_job(self, job_id: UUID, *, worker_id: str, completed_at: Instant) -> bool:
        with self._sessions() as session, session.begin():
            row = self._leased_job(session, job_id, worker_id)
            if row is None:
                return False
            row.state = EmailJobState.COMPLETED.value
            row.text_body = None
            row.lease_owner = None
            row.leased_until = None
            row.last_error = None
            row.completed_at = completed_at.value
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
        with self._sessions() as session, session.begin():
            row = self._leased_job(session, job_id, worker_id)
            if row is None:
                return False
            if row.attempts >= 5:
                row.state = EmailJobState.DEAD_LETTER.value
                row.available_at = failed_at.value
                row.text_body = None
            else:
                delay = min(base_backoff.total_seconds() * (2 ** (row.attempts - 1)), 3600)
                row.state = EmailJobState.PENDING.value
                row.available_at = failed_at.value + timedelta(seconds=delay)
            row.lease_owner = None
            row.leased_until = None
            row.last_error = error_code
            return True

    @staticmethod
    def _leased_job(session: Session, job_id: UUID, worker_id: str) -> EmailDeliveryJobModel | None:
        return session.scalar(
            select(EmailDeliveryJobModel)
            .where(
                EmailDeliveryJobModel.id == job_id,
                EmailDeliveryJobModel.state == EmailJobState.LEASED.value,
                EmailDeliveryJobModel.lease_owner == worker_id,
            )
            .with_for_update()
        )


def _job_from_row(row: EmailDeliveryJobModel) -> EmailDeliveryJob:
    return EmailDeliveryJob(
        id=row.id,
        token_id=row.token_id,
        purpose=EmailTokenPurpose(row.purpose),
        recipient=row.recipient,
        subject=row.subject,
        text_body=row.text_body,
        state=EmailJobState(row.state),
        attempts=row.attempts,
        available_at=Instant(row.available_at),
        created_at=Instant(row.created_at),
    )
