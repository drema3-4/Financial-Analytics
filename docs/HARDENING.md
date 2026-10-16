# E2E and hardening gate

## System E2E boundary

`tests/e2e/system-scenarios.spec.ts` is the product E2E suite. It contains one independent test
for each numbered scenario in `SPEC.md`. Every test truncates only an explicitly named `*_e2e`
database, then uses a real Chromium page, FastAPI process and PostgreSQL. The API, worker and
browser use `2026-10-16T20:00:00Z`; `TEST_CLOCK_AT` is rejected outside `APP_ENV=test`. The
deterministic OpenAI-compatible fixture is a separate HTTP process and has no write tools.

Run against an already-created empty PostgreSQL database whose name ends in `_e2e`:

```powershell
$env:APP_ENV = "test"
$env:DATABASE_URL = "postgresql+psycopg://financial_analytics:password@127.0.0.1:5432/financial_analytics_e2e"
$env:SESSION_SECRET = "replace-with-at-least-32-bytes-for-e2e"
$env:CSRF_SECRET = "replace-with-an-independent-32-byte-e2e-value"
$env:EMAIL_TOKEN_SECRET = "replace-with-an-independent-32-byte-e2e-value"
poetry run alembic upgrade head
pnpm test:e2e:install
pnpm test:e2e:system
```

Trace, screenshot and video are retained only for a failing test. CI uploads `test-results` only
when the system job fails. Route-mocked Playwright tests remain fast UI contract smoke tests and
are not counted as the seven product scenarios.

Scenario 2 is the reconciliation proof. Its browser-created expense is read back from the API;
the two exact decimal postings sum to zero, the transaction ID occurs in analytics evidence,
closing net worth equals the account balance, and the same amount is the forecast opening total.

## Threat-model test matrix

| Threat | Control and executable evidence |
|---|---|
| IDOR / cross-tenant IDs | Every owner-scoped repository filters by owner; ledger, scheduling, deposits, analytics, forecast and goals integration tests use a second owner and require indistinguishable `404` or empty results. |
| Brute force | Login and refresh use the rate-limiter port; identity tests prove the bounded attempt window and `429 Retry-After`. The current single-process limiter is not suitable for multiple API replicas. |
| CSRF / CORS | Session-bound double-submit token, exact origin allowlist, credentialed preflight allow/deny and missing/wrong token tests. Wildcard origins are rejected by settings. |
| Session fixation / replay | Login/bootstrap ignore ambient auth; refresh rotates access/refresh/CSRF atomically. Replay of the old refresh is rejected and revokes its session. |
| SQL / prompt injection | Repository parameters are bound; a PostgreSQL test submits `' OR 1=1 --` as search data. LLM user text is delimited as untrusted JSON. |
| Spreadsheet formula injection | CSV fields whose first non-whitespace character is `=`, `+`, `-` or `@` receive an apostrophe prefix. UTF-8/BOM, quoting, CRLF and a malicious multiline cell are parsed back in an integration test. |
| Upload/export confusion | MVP has no upload endpoint. CSV is attachment-only with fixed filename, UTF-8 content type, `nosniff` and `no-store`; OpenAPI exposes no upload path. |
| Log/LLM data leakage | Logs accept bounded attributes and redact credential assignments, bearer values, email and long card-like numbers. Correlation IDs use a safe alphabet. Provider tests prove raw ledger, IDs, API key and redacted user secrets are absent. |

## CI security policy

Trivy scans lockfiles/repository content and both runtime images. Any known `HIGH` or `CRITICAL`
vulnerability, detected secret, forbidden license or restricted license fails CI, including an
unfixed vulnerability. Misconfigurations are included. A CycloneDX SBOM and full JSON license
report are retained as artifacts; `MEDIUM`, `LOW` and `UNKNOWN` license classifications remain
visible for human release review.

There are currently no accepted critical/high exceptions. A future exception must be a human
decision recorded here with finding ID, affected component, compensating control, owner,
approval date and expiry date. A suppression without those fields is invalid.

## Failure and recovery matrix

| Condition | Expected result | Test/proof |
|---|---|---|
| API SIGTERM with requests in flight | Uvicorn stops accepting work, completes its graceful window, then lifespan disposes pools. | ASGI lifespan tests plus container `init: true`; no mutation is acknowledged before its DB transaction commits. |
| Worker SIGTERM/SIGINT during tick | Signal sets a stop flag; synchronous tick completes, heartbeat is written, and no next lease is claimed. | `test_graceful_stop_finishes_in_flight_tick_and_does_not_claim_another`. |
| Crash after ledger commit, before job ack | Expired lease is reclaimed; deterministic idempotency returns the original transaction. | Scheduling PostgreSQL crash-after-commit and two-worker lease tests. |
| PostgreSQL unavailable | API readiness is `503`; worker does not mark heartbeat or claim work. | Health, database and worker tests. |
| Heartbeat disk write failure | Completed DB work is not rolled back or repeated in-process; worker reports unready and logs a fixed event. | Worker disk-error test. |
| LLM unavailable / timeout / invalid reply | Advice returns a safe optional status; ledger and readiness remain available. | Provider contract matrix and disabled-provider behavior. |
| SMTP unavailable | SMTP is not initialized in the MVP and cannot block core readiness. Email delivery belongs to the next release. | Core Compose profile has no SMTP dependency. |
| Migration on realistic data | A restored API-created ledger copy receives `upgrade head`, `current --check-heads` and `alembic check`. | `backup-restore-drill` CI job. |

## Performance evidence

The gate uses measured query shape rather than a fragile cross-host threshold. The dataset is
10,000 posted transactions for two tenants plus reference rows. PostgreSQL must use the partial
owner/date posted index, return at most 200 rows to an aggregate step, avoid sequential scan/temp
I/O and complete the application report in at most five `SELECT`s. Forecast and advice reuse one
owner-scoped snapshot.

The existing synthetic PostgreSQL test is the regression gate. Stage 12 did not add a cache or
summary table because the measured plan already met the budget; no confirmed bottleneck was
found. Wall-clock observations from the final run are recorded in `STATUS.md` with the command
and are diagnostic rather than a cross-host pass/fail threshold.

The 2026-10-16 local acceptance run completed the 10,000-transaction test in `5.26 s`, the full
seven-scenario system E2E suite in `56.2 s`, and both final runtime image scans with zero
High/Critical vulnerabilities and zero detected secrets. These timings are observations, not CI
thresholds; the executable plan/statement-count invariants are the portable performance gate.
