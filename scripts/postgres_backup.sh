#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || -z "${DATABASE_URL:-}" ]]; then
  echo "usage: DATABASE_URL=... scripts/postgres_backup.sh OUTPUT.dump" >&2
  exit 2
fi

output=$1
if [[ -e "$output" ]]; then
  echo "refusing to overwrite an existing backup" >&2
  exit 2
fi

postgres_url=${DATABASE_URL/postgresql+psycopg:/postgresql:}
umask 077
pg_dump --dbname="$postgres_url" --format=custom --compress=9 --no-owner --no-acl --file="$output"
pg_restore --list "$output" >/dev/null
echo "backup created and archive catalog verified"
