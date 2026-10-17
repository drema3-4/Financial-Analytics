# Server deployment

## Boundary and prerequisites

The application image does not obtain certificates and does not modify DNS. Before deployment,
choose a real host and domain, point DNS to it, and choose an operator-managed reverse proxy or
platform ingress. The public origin below is an example only; do not request a certificate for
it.

Production requires Docker Compose v2, the two application images built from this release,
PostgreSQL 18 storage, an SMTP relay with STARTTLS or implicit TLS, and a TLS-terminating reverse
proxy. The optional local LLM additionally requires the NVIDIA prerequisites in `docs/LLM.md`.

Build and publish application images in a trusted pipeline, with the public API origin compiled
into the web image:

```text
docker build -f infra/docker/backend/Dockerfile -t registry.example/financial-analytics-backend:0.2.0 .
docker build --build-arg VITE_API_BASE_URL=https://finance.example.com -f infra/docker/web/Dockerfile -t registry.example/financial-analytics-web:0.2.0 .
```

Record the registry digests and deploy immutable references such as
`registry.example/financial-analytics-backend@sha256:...`. The overlay defaults to local
versioned tags only for the production-like rehearsal; a real server should set `BACKEND_IMAGE`
and `WEB_IMAGE` to those recorded digests.

## Production environment

Store values in the host secret manager or a root-readable environment file outside the clone.
Required values are deliberately rejected by Compose or application startup when missing or
unsafe:

```text
POSTGRES_PASSWORD=<random database password>
DATABASE_URL=postgresql+psycopg://financial_analytics:<url-encoded-password>@postgres:5432/financial_analytics
BACKEND_IMAGE=registry.example/financial-analytics-backend@sha256:<digest>
WEB_IMAGE=registry.example/financial-analytics-web@sha256:<digest>
CORS_ORIGINS=["https://finance.example.com"]
PUBLIC_BASE_URL=https://finance.example.com
BOOTSTRAP_MASTER_EMAIL=owner@example.com
TRUSTED_PROXY_IPS=["172.20.0.2"]
SESSION_SECRET=<independent random value, at least 32 bytes>
CSRF_SECRET=<independent random value, at least 32 bytes>
EMAIL_TOKEN_SECRET=<independent random value, at least 32 bytes>
SESSION_COOKIE_DOMAIN=
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_FROM_ADDRESS=finance@example.com
SMTP_SECURITY=starttls
SMTP_USERNAME=<relay user when required>
SMTP_PASSWORD=<relay password when required>
```

Use a host-only cookie by leaving `SESSION_COOKIE_DOMAIN` empty. Set a parent domain only when
the browser must send the session to that exact trusted suffix; never use a public suffix or a
broader organizational domain. `TRUSTED_PROXY_IPS` is the proxy container/ingress IP or CIDR,
not the client network and never `*`.

Production startup is blocked for HTTP public URLs/origins, wildcard CORS, insecure cookies,
debug mode/DEBUG logging, default or predictable identity secrets, missing bootstrap email,
untrusted forwarded headers, placeholder database credentials, or plaintext SMTP.

## Reverse proxy and TLS

Prefer one HTTPS origin: proxy `/api/`, `/health/` and `/metrics` to `api:8000`, and all other
paths to `web:4173`. Preserve the original host and set `X-Forwarded-Proto https` and
`X-Forwarded-For`; Uvicorn accepts them only from `TRUSTED_PROXY_IPS`. Do not expose PostgreSQL,
API, web, SMTP catcher, or vLLM host ports from the production overlay. Connect the reverse proxy
to the Compose network instead.
Do not record query strings on `/invite`, `/verify-email` or `/reset-password`, and set
`Referrer-Policy: no-referrer` so email-link tokens do not enter proxy logs or outbound referrers.

The proxy must redirect HTTP to HTTPS, use a currently supported TLS policy, set HSTS only after
the chosen domain is proven, cap request bodies/timeouts, and add a CSP appropriate to the
self-hosted SPA. Certificate issuance/renewal belongs to the selected proxy/platform after DNS
and the real domain are known; this repository intentionally contains no invented ACME command.
Apply centralized rate limits to bootstrap/login and email-recovery requests before opening
ingress; the in-process limiter is not a shared multi-replica or email-abuse limiter.

## Migration and rollout

1. Verify an off-host backup and a recent restore drill.
2. Pull the two application image digests and the pinned upstream images.
3. Render and review the model without printing the resolved secret-bearing environment:
   `docker compose -f compose.yaml -f compose.production.yaml --profile core config --quiet`.
4. Run the one-shot migration first:
   `docker compose -f compose.yaml -f compose.production.yaml --profile core run --rm migrate`.
5. Start and wait for healthchecks:
   `docker compose -f compose.yaml -f compose.production.yaml --profile core up -d --wait`.
6. Keep public ingress disabled (or deny `/api/v1/auth/bootstrap` at the proxy). Through a
   private operator connection/SSH tunnel, verify readiness and bootstrap exactly
   `BOOTSTRAP_MASTER_EMAIL`; then confirm a second bootstrap is rejected. The configured email
   is a restriction, not a secret or proof of mailbox ownership. Master verification here is
   the operator's assertion; never leave an uninitialized instance publicly claimable.
7. Enable the selected HTTPS ingress, then verify the certificate chain, exact CORS origin,
   Secure cookies, forwarded client IP handling and SMTP delivery from outside.

`local-llm` is optional and has no schema delta. Enable it only after core is healthy by adding
`--profile local-llm` and the provider variables from `docs/LLM.md`; removing that profile needs
no migration.

## Rollback

For an application-only fault, keep the migrated database, restore the previous backend/web
image digests, restart API/worker/web, and verify readiness plus a read-only ledger check. Do not
blindly downgrade the database: inspect the failed release migration first. If schema rollback is
required, stop API and worker, take a final backup, restore the pre-release backup into a new
database, verify it as in `docs/BACKUP_AND_RECOVERY.md`, switch `DATABASE_URL`, and retain the
failed database read-only through the incident window.

Identity secret and database credential rotation procedures are in `docs/SECURITY.md`. The
backup schedule is one verified daily archive (7 daily/4 weekly, off-host), with the explicit
24-hour RPO and 60-minute MVP RTO assumptions in `docs/BACKUP_AND_RECOVERY.md`.
