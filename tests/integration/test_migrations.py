from __future__ import annotations

import os

from alembic import command
from sqlalchemy import create_engine, inspect

from tests.integration.conftest import (
    _alembic_config,
    create_disposable_database,
    drop_disposable_database,
)


def test_clean_upgrade_and_empty_schema_downgrade() -> None:
    base_url = os.environ["TEST_DATABASE_URL"]
    database_url, admin_engine, database_name = create_disposable_database(base_url)
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    engine = create_engine(database_url)
    try:
        config = _alembic_config(database_url)
        command.upgrade(config, "head")
        command.check(config)
        assert {
            "users",
            "accounts",
            "transactions",
            "postings",
            "audit_events",
            "idempotency_records",
            "credentials",
            "sessions",
            "user_profiles",
            "email_allowlist",
            "invitations",
            "email_tokens",
            "recurring_rules",
            "outbox_jobs",
            "deposit_terms",
            "deposit_rate_periods",
        }.issubset(inspect(engine).get_table_names())

        command.downgrade(config, "20261013_0001")
        assert inspect(engine).get_table_names() == ["alembic_version"]
    finally:
        engine.dispose()
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        drop_disposable_database(admin_engine, database_name)
