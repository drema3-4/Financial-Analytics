#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || -z "${SOURCE_DATABASE_URL:-}" || -z "${RESTORE_DATABASE_URL:-}" ]]; then
  echo "usage: SOURCE_DATABASE_URL=... RESTORE_DATABASE_URL=... scripts/postgres_restore.sh INPUT.dump" >&2
  exit 2
fi

archive=$1
source_url=${SOURCE_DATABASE_URL/postgresql+psycopg:/postgresql:}
restore_url=${RESTORE_DATABASE_URL/postgresql+psycopg:/postgresql:}
source_name=$(psql "$source_url" --tuples-only --no-align --command="SELECT current_database()")
restore_name=$(psql "$restore_url" --tuples-only --no-align --command="SELECT current_database()")

if [[ "$source_name" == "$restore_name" ]]; then
  echo "refusing to restore into the source database" >&2
  exit 2
fi

relation_count=$(psql "$restore_url" --tuples-only --no-align --command="SELECT count(*) FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r','p')")
if [[ "$relation_count" != "0" ]]; then
  echo "restore database must be empty" >&2
  exit 2
fi

pg_restore --dbname="$restore_url" --exit-on-error --single-transaction --no-owner --no-acl "$archive"
psql "$restore_url" --set=ON_ERROR_STOP=1 --command="ANALYZE" >/dev/null
echo "restore completed in a separate empty database"
