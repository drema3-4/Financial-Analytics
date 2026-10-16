from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from sqlalchemy import Engine, MetaData, create_engine, text
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Metadata root for PostgreSQL persistence models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


@dataclass(frozen=True, slots=True)
class JobQueueSnapshot:
    pending: int
    leased: int
    dead_letter: int


class Database:
    """Small SQLAlchemy lifecycle and readiness adapter."""

    def __init__(self, url: str) -> None:
        self._engine: Engine = create_engine(
            url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 2},
        )

    def ping(self) -> bool:
        try:
            with self._engine.connect() as connection:
                result = cast(int, connection.scalar(text("SELECT 1")))
                return result == 1
        except Exception:
            return False

    def job_queue_snapshot(self) -> JobQueueSnapshot:
        """Return bounded operational counts without tenant or payload data."""

        statement = text(
            """
            SELECT
              count(*) FILTER (WHERE state = 'pending') AS pending,
              count(*) FILTER (WHERE state = 'leased') AS leased,
              count(*) FILTER (WHERE state = 'dead_letter') AS dead_letter
            FROM outbox_jobs
            """
        )
        with self._engine.connect() as connection:
            row = connection.execute(statement).one()
        return JobQueueSnapshot(
            pending=int(row.pending),
            leased=int(row.leased),
            dead_letter=int(row.dead_letter),
        )

    @property
    def engine(self) -> Engine:
        return self._engine

    def close(self) -> None:
        self._engine.dispose()
