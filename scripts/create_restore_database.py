from __future__ import annotations

import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def main() -> None:
    source_url = os.getenv("SOURCE_DATABASE_URL")
    restore_url = os.getenv("RESTORE_DATABASE_URL")
    if source_url is None or restore_url is None:
        raise RuntimeError("SOURCE_DATABASE_URL and RESTORE_DATABASE_URL are required")
    source = make_url(source_url)
    restore = make_url(restore_url)
    if source.database == restore.database:
        raise RuntimeError("restore database must differ from source")
    if restore.database is None or not restore.database.endswith("_restore"):
        raise RuntimeError("restore database name must end in _restore")

    admin = create_engine(source.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            exists = connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": restore.database},
            )
            if exists:
                raise RuntimeError("restore database already exists")
            quoted_database = admin.dialect.identifier_preparer.quote(restore.database)
            connection.execute(text(f"CREATE DATABASE {quoted_database}"))
    finally:
        admin.dispose()


if __name__ == "__main__":
    main()
