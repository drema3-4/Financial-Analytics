# Security model and secret rotation

## Scope and trust boundaries

The browser, FastAPI process, PostgreSQL, optional SMTP adapter and optional LLM provider are
separate trust boundaries. Core authentication depends only on FastAPI and PostgreSQL; it does
not require SMTP or an LLM. TLS termination is mandatory for a non-local deployment. The local
Compose origin is explicit and uses Secure cookies; production must supply unique secrets.

The current model protects against credential-database disclosure, guessed object IDs,
cross-site requests, stolen/replayed refresh or email tokens, concurrent bootstrap, session
revocation races and accidental sensitive logging. A fully compromised host/browser profile,
malicious browser extension, memory scraping of the live API process and denial of service
beyond one API process are outside the stage-03 boundary. CSP, proxy limits and distributed
rate limiting are deployment hardening work, not substitutes for the controls here.

The executable stage-12 threat matrix, scanner failure policy and exception format are in
[`HARDENING.md`](HARDENING.md). There are no accepted critical/high findings or suppressions.

## Controls

- Passwords use Argon2id (`m=65536`, `t=3`, `p=4`, 32-byte output, 16-byte random salt).
  Parameters travel with the encoded hash and login performs opportunistic rehash.
- Access, refresh, CSRF and email secrets are generated from the OS CSPRNG. PostgreSQL stores
  only keyed SHA-256 digests. Raw values exist only at issue time and in browser cookies or an
  eventual email delivery job.
- Access lifetime is 15 minutes; refresh has a non-sliding 30-day lifetime. Refresh rotates all
  three session secrets atomically. Replay is rejected; a replay carrying the current
  session-bound CSRF proof also revokes that session.
- Access and refresh cookies are `HttpOnly; Secure; SameSite=Strict`; the CSRF cookie is Secure
  and readable so the SPA can echo it in `X-CSRF-Token`. The server also verifies its
  session-bound digest. Login/bootstrap do not rely on an ambient authenticated cookie.
- CORS credentials are returned only to configured exact origins; `*` is rejected. Login and
  refresh are limited by IP plus identity/session key through a replaceable application port.
- The master bootstrap is serialized by a PostgreSQL advisory transaction lock and protected
  by a unique partial index. There is no reset endpoint.
- Every user-owned repository requires an owner at construction and applies it to ID lookup and
  filters. Composite owner foreign keys prevent cross-tenant links. Authorization tests use two
  owners and guessed IDs.
- Security mutations append audit events. Payloads contain bounded state such as purpose or
  revoked count, never email addresses, passwords, raw tokens or financial details. Request
  logs contain method/status and correlation identifiers, not request bodies or cookies.

## Secret inventory

`SESSION_SECRET` hashes access and refresh secrets. `CSRF_SECRET` hashes CSRF secrets.
`EMAIL_TOKEN_SECRET` hashes invitation/verification/reset secrets. Each must be an independent,
random value of at least 32 bytes, delivered via environment/secret manager and never committed.
`POSTGRES_PASSWORD` is independent. Development defaults are public, local-only values and are
rejected when `APP_ENV=production`.

`LLM_API_KEY` is optional for a local endpoint and required for an external production endpoint.
It is represented as `SecretStr`, sent only in the Authorization header and never copied into
provider payloads, status responses, exception messages or logs. External LLM URLs must be
HTTPS in production and cannot contain embedded credentials, query strings or fragments.

## LLM privacy boundary

Advice receives only the sanitized `advice-context-v1`; it excludes identity fields, raw ledger
rows, names, comments/descriptions and transaction/posting IDs. Optional user text is treated as
untrusted data, redacted, and omitted for external providers unless the request explicitly opts
in. Provider responses have no write tools and are schema/evidence validated before display.
Provider request/response bodies are not logged. See [LLM.md](LLM.md) for the exact field and
failure contracts.

Generate a value, for example, with a trusted secret manager or `openssl rand -base64 48`.
Do not paste generated values into tickets, command history, logs, source control or screenshots.

## Rotation procedures

### Session or CSRF secret

1. Schedule a maintenance window and notify users that every session will end.
2. Replace the selected environment secret with a newly generated independent value.
3. Restart every API replica together; mixed keys cause inconsistent authentication.
4. Revoke all rows with `sessions.revoked_at IS NULL` using an audited administrative runbook,
   or let digest mismatch invalidate them immediately. Database revocation is preferred because
   it makes state explicit.
5. Verify old access/refresh/CSRF combinations return `401`/`403`, then perform a fresh login.
6. Remove the old secret from the secret manager after rollback time has elapsed.

There is intentionally no dual-key grace period for session secrets: rotation is also an
emergency global logout mechanism.

### Email-token secret

1. Pause token issuance/delivery jobs.
2. Replace `EMAIL_TOKEN_SECRET` on every issuer and consumer and restart them together.
3. Revoke unconsumed rows, audit the count, and reissue still-needed invitations or recovery
   links. Old links must fail; do not retain the old key for a grace period.
4. Resume jobs and test issue/consume/replay with a non-production address.

### Database password

Create a new database credential or rotate the existing role through the platform secret
manager, update `DATABASE_URL` for API, worker and migration jobs, restart them, verify readiness,
then retire the old credential. Never place a password-bearing URL in logs.

### Argon2 parameters

Change the password-hasher policy in code and deploy it. Existing hashes remain verifiable
because parameters are encoded. A successful login rehashes with the new policy and writes an
audit event; forced bulk password rehash without plaintext is impossible.

## Incident checks

For suspected token theft, revoke the current session or all sessions for the owner, rotate the
relevant HMAC secret if blast radius is unknown, preserve append-only audit rows, and search logs
by request/correlation ID. Never copy credential rows or cookies into the incident channel.
