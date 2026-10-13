from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url

ROOT = Path(__file__).resolve().parents[2]


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def create_disposable_database(base_url: str) -> tuple[str, Engine, str]:
    source = make_url(base_url)
    database_name = f"financial_analytics_test_{uuid4().hex}"
    admin_url: URL = source.set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    database_url = source.set(database=database_name).render_as_string(hide_password=False)
    return database_url, admin_engine, database_name


def drop_disposable_database(admin_engine: Engine, database_name: str) -> None:
    if not database_name.startswith("financial_analytics_test_"):
        raise RuntimeError("refusing to drop a database outside the test namespace")
    with admin_engine.connect() as connection:
        connection.execute(text(f'DROP DATABASE "{database_name}" WITH (FORCE)'))
    admin_engine.dispose()


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    base_url = os.getenv("TEST_DATABASE_URL")
    if base_url is None:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    database_url, admin_engine, database_name = create_disposable_database(base_url)
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        command.upgrade(_alembic_config(database_url), "head")
        yield database_url
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        drop_disposable_database(admin_engine, database_name)


@pytest.fixture(scope="session")
def postgres_engine(postgres_url: str) -> Iterator[Engine]:
    engine = create_engine(postgres_url)
    try:
        yield engine
    finally:
        engine.dispose()
