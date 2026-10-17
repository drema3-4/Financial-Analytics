# PostgreSQL backup and recovery

## Scope and assumptions

The scripts create a PostgreSQL custom-format logical backup with ownership/ACL removed. They do
not include model caches, `.env`, application logs or external object storage. The destination
must encrypt backups at rest, restrict read access, verify retention and keep an off-host copy.

Without WAL archiving, the assumed schedule is one successful daily backup:

For the chosen server, schedule it at **02:00 UTC daily**, keep the Sunday archive as the weekly
copy, and run an isolated restore verification at least monthly and before each migration.
Alert on a failed run or a missing successful archive within 24 hours. Scheduler/storage setup
belongs to that host's operator; this repository does not claim an off-host schedule is active.

- RPO: at most 24 hours, plus transactions since the last completed backup;
- RTO target: 60 minutes for the MVP dataset, including integrity checks and restart;
- restore compatibility: the same PostgreSQL major client/server, currently 18;
- retention assumption: 7 daily and 4 weekly verified archives.

These are explicit assumptions, not guarantees. RPO below 24 hours requires more frequent
backups or WAL archiving/PITR, which belongs to deployment scope.

The 2026-10-16 local drill used an API-seeded source database and a distinct empty restore
database. Backup, restore and exact verification completed in approximately 17 seconds,
including client-container startup. All public-table counts and canonical row digests matched,
postings remained zero-sum, and the restored copy passed Alembic head and metadata drift checks.
This is evidence for the current dataset only; the operational RTO target remains 60 minutes.

## Backup

`DATABASE_URL` is read from the environment and never printed. Output must not exist; the POSIX
script uses restrictive creation permissions and both variants validate the archive catalog.

```bash
DATABASE_URL='postgresql://...' scripts/postgres_backup.sh /secure/backup/app.dump
```

```powershell
$env:DATABASE_URL = "postgresql://..."
./scripts/postgres_backup.ps1 -Output D:\secure\backup\app.dump
```

Record start/end time, source size, archive size, PostgreSQL version and checksum in the operator
log; never record the URL or password.

## Restore drill

Create a new empty database. Both restore scripts query `current_database()`, refuse equal
source/target names and refuse a target containing public tables.

```bash
SOURCE_DATABASE_URL='postgresql://.../financial_analytics' \
RESTORE_DATABASE_URL='postgresql://.../financial_analytics_restore' \
scripts/postgres_restore.sh /secure/backup/app.dump
```

After restore:

1. run `scripts/backup_restore_drill.py verify` with both URLs;
2. run Alembic `upgrade head`, `current --check-heads` and `check` against the restored URL;
3. start an isolated API against the restore database and check `/health/ready`;
4. compare table counts, exact row digests and zero-sum postings;
5. record restore plus verification time as observed RTO;
6. destroy the disposable database only after saving the drill record.

The CI `backup-restore-drill` job seeds financial facts through the real API, backs up with the
pinned PostgreSQL 18 client, restores to `financial_analytics_restore`, compares every public
table digest and ledger balance, then runs migration checks. Merely having scripts is not proof.

For production recovery, quiesce API and worker before the final backup/restore, preserve the
failed database for investigation, restore into a new database, complete these checks, switch the
secret-managed `DATABASE_URL`, and keep the old database read-only through rollback time.
