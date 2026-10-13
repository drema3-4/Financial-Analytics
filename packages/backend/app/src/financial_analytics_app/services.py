from __future__ import annotations

from collections.abc import Callable
from uuid import UUID, uuid4

from financial_analytics_app.ports import (
    AuditEvent,
    IdempotencyRecord,
    UnitOfWorkFactory,
)
from financial_analytics_domain import Instant, Transaction
from financial_analytics_domain.errors import OwnershipError


class IdempotencyConflictError(ValueError):
    """The same idempotency key was reused for a different command."""


class ConcurrentModificationError(RuntimeError):
    """An optimistic version check rejected a stale mutation."""


class RecordTransaction:
    """Atomically persist an immutable transaction, audit event, and replay record."""

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

    def execute(
        self,
        transaction: Transaction,
        *,
        actor_id: UUID,
        idempotency_key: str | None = None,
        request_hash: str | None = None,
        request_id: UUID | None = None,
    ) -> UUID:
        if actor_id != transaction.owner_id:
            raise OwnershipError("actor must own the transaction")
        if (idempotency_key is None) != (request_hash is None):
            raise ValueError("idempotency key and request hash must be supplied together")

        with self._uow_factory.open(transaction.owner_id) as uow:
            if idempotency_key is not None and request_hash is not None:
                existing = uow.idempotency.get("record_transaction", idempotency_key)
                if existing is not None:
                    if existing.request_hash != request_hash:
                        raise IdempotencyConflictError(
                            "idempotency key was used with a different request"
                        )
                    return existing.resource_id

            uow.ledger.add_transaction(transaction, actor_id=actor_id, request_id=request_id)
            now = self._clock()
            uow.audit.append(
                AuditEvent(
                    id=self._uuid_factory(),
                    owner_id=transaction.owner_id,
                    actor_id=actor_id,
                    event_type="ledger.transaction_recorded",
                    aggregate_type="transaction",
                    aggregate_id=transaction.id,
                    occurred_at=now,
                    request_id=request_id,
                    payload={
                        "kind": transaction.kind.value,
                        "reversal_of_id": (
                            str(transaction.reversal_of_id)
                            if transaction.reversal_of_id is not None
                            else None
                        ),
                    },
                )
            )
            if idempotency_key is not None and request_hash is not None:
                uow.idempotency.add(
                    IdempotencyRecord(
                        owner_id=transaction.owner_id,
                        scope="record_transaction",
                        key=idempotency_key,
                        request_hash=request_hash,
                        resource_type="transaction",
                        resource_id=transaction.id,
                        created_at=now,
                    )
                )
            uow.commit()
        return transaction.id
