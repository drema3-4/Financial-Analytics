from __future__ import annotations

from typing import cast

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Metadata root for future persistence models."""


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

    def close(self) -> None:
        self._engine.dispose()
