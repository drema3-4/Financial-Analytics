from __future__ import annotations

import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


def main() -> None:
    if os.getenv("APP_ENV") != "test":
        raise RuntimeError("E2E reset requires APP_ENV=test")
    database_url = os.getenv("DATABASE_URL")
    if database_url is None:
        raise RuntimeError("DATABASE_URL is required")
    database_name = make_url(database_url).database or ""
    if not database_name.endswith("_e2e"):
        raise RuntimeError("E2E reset is restricted to database names ending in _e2e")

    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            tables = [
                name
                for name in inspect(connection).get_table_names(schema="public")
                if name != "alembic_version"
            ]
            if tables:
                quoted = ", ".join(f'"{name}"' for name in sorted(tables))
                connection.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
