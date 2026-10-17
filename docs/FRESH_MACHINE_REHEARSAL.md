# Fresh-clone release rehearsal — 2026-10-17

Host: Windows 11 / Docker Desktop WSL2, Engine `29.1.2`, Compose `v2.40.3-desktop.1`,
RTX 3050 Laptop `6144 MiB`. This is a clean-clone run on the existing host, not a newly installed
OS. Docker image/layer cache was available; database and model-cache volumes were new. No `.env`,
Python environment, node_modules, DB or model files were copied into the clone.

Core/mail snapshot: `ea0fb54457000ea676b610a75c2532d07336ca09`; corrected pinned-model profile
snapshot: `5b4ab78b108c872ebff7ddc0209285b65bf04231`. These are detached local Git objects
used before recording evidence, not release tags or additional milestone commits.
Final evidence/docs are committed afterwards. The following commands use disposable projects.
Final core image/production/mail repeat used snapshot
`f0c181a303a0ca33cef6da2ec1a9d35163f55462`, including the database-password startup validation.
For future runs, clone the completed milestone commit normally and omit the historical snapshot
fetch/checkout lines. The final commit contains this implementation plus its evidence/docs;
snapshot objects are not published release references.

## Clean clone and core

```powershell
git clone --no-local 'D:/Pet Projects/Financial_analytics' 'D:/Pet Projects/Financial_analytics/tmp/stage13-rehearsal-20261017'
cd 'D:/Pet Projects/Financial_analytics/tmp/stage13-rehearsal-20261017'
git fetch origin ea0fb54457000ea676b610a75c2532d07336ca09
git checkout --detach FETCH_HEAD
git status --porcelain
docker compose -p fa-stage13-core --profile core up --build --wait
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Get-Content -Encoding utf8 scripts/release_smoke.py -Raw | docker compose -p fa-stage13-core --profile core exec -T api python - --base-url http://127.0.0.1:8000
docker compose -p fa-stage13-core --profile core exec -T api python -m alembic current --check-heads
Invoke-RestMethod http://localhost:4173/health/live
```

Observed: Git status empty; initial build/start `63.1 s`, final cached repeat `33.5 s`, exit `0`.
PostgreSQL/API/worker/web healthy, migrate exited `0`, no vLLM service. Walkthrough returned
`passed`, advice `disabled`, algorithm `monthly-cashflow-v1`. Onboarding → expense → forecast →
goal was exercised; exact forecast opening balance was `9874.75 RUB` after spending `125.25`
from `10000.00`. Revision `20261016_0011 (head)`; web `alive`.

## Mail-catcher and one-time links

```powershell
docker compose -p fa-stage13-core --profile core down --volumes
docker compose -p fa-stage13-mail --profile mail-catcher up --build --wait
Get-Content -Encoding utf8 scripts/release_smoke.py -Raw | docker compose -p fa-stage13-mail --profile mail-catcher exec -T api python - --base-url http://127.0.0.1:8000 --invite-email invited@example.test --mailpit-url http://mailpit:8025
docker compose -p fa-stage13-mail --profile mail-catcher exec -T postgres psql -U financial_analytics -d financial_analytics -c "SELECT event_type,count(*) FROM audit_events WHERE event_type IN ('identity.invitation_accepted','identity.email_token_replay_rejected','identity.password_reset') GROUP BY event_type ORDER BY event_type"
docker compose -p fa-stage13-mail --profile mail-catcher exec -T postgres psql -U financial_analytics -d financial_analytics -c "SELECT purpose,state,attempts,text_body IS NULL AS body_cleared FROM email_delivery_jobs ORDER BY created_at"
docker compose -p fa-stage13-mail --profile mail-catcher down --volumes
```

Observed: pinned Mailpit pulled successfully; services healthy. Successful clean build/start:
`98.0 s`; final clean-database cached repeat with the 15-second worker health timeout took
`27.5 s`. Script result `smtp-accepted-replay-denied-reset-replay-denied-admin-denied`.
Invitation/reset each delivered once, reached `completed`, body cleared. Audit counts: accepted
invitation `1`, password reset `1`, token replay rejected `2`. Reset invalidated the old guest
session; guest admin API returned `403`. A repeat bootstrap against the populated DB returned
`409`, as required. Unknown-account recovery returned the same `202` payload in API tests.

Rehearsal corrections: the script initially sent an extra `is_admin` field to allowlist (`422`);
the payload was fixed before the successful run. Cold worker imports occasionally exceeded the
old 5-second health timeout while ticks succeeded; final Compose uses 15 seconds and was checked
healthy again. The walkthrough deliberately requires an empty database, because onboarding is
single-use.

## Optional GPU profile

Start a new core project and run its walkthrough once, then enable local LLM on that same DB:

```powershell
git fetch origin 5b4ab78b108c872ebff7ddc0209285b65bf04231
git checkout --detach FETCH_HEAD
$env:LLM_PROVIDER = 'openai_compatible'
$env:LLM_BASE_URL = 'http://vllm:8000/v1'
$env:LLM_ENDPOINT_SCOPE = 'local'
$env:LLM_TIMEOUT_SECONDS = '120'
docker compose -p fa-stage13-core --profile local-llm up --build --wait
docker compose -p fa-stage13-core --profile local-llm ps
Invoke-RestMethod http://localhost:8001/health
docker compose -p fa-stage13-core --profile local-llm exec -T postgres psql -U financial_analytics -d financial_analytics -c 'SELECT version_num FROM alembic_version'
docker compose -p fa-stage13-core --profile local-llm stop vllm
Remove-Item Env:LLM_PROVIDER, Env:LLM_BASE_URL, Env:LLM_ENDPOINT_SCOPE, Env:LLM_TIMEOUT_SECONDS -ErrorAction SilentlyContinue
docker compose -p fa-stage13-core --profile core up -d --wait
```

GPU result: corrected startup `232.4 s`, exit `0`; vLLM and core healthy. Downloaded Hugging Face
revision `74d4bd2bd4bff9cafc9345221320bffb08b406a3`; TLS verification stayed enabled. A real
non-thinking chat answered `OK.` in `3048 ms`; observed VRAM max `5961/6144 MiB`, no OOM observed.
After stopping vLLM, core returned `ready`, provider `disabled`; users `1`, transactions `2`,
goals `1`, bank balance `9874.750000000 RUB` and revision `20261016_0011` were unchanged.

The first empty-cache attempt failed after `223.3 s` because the image-enabled `hf_transfer`
downloader reported `no permits available`; core stayed healthy. The corrected profile sets
`HF_HUB_ENABLE_HF_TRANSFER=0` and pins the observed model revision. Retry command was
`docker compose -p fa-stage13-core --profile local-llm up -d --wait` with the same provider env.

Chat and full-adapter commands (run before stopping vLLM):

```powershell
$stage13Body = @{model='Qwen/Qwen3-4B-AWQ';messages=@(@{role='user';content='Reply exactly OK'});temperature=0;max_tokens=64;chat_template_kwargs=@{enable_thinking=$false}} | ConvertTo-Json -Depth 6 -Compress
Invoke-RestMethod http://localhost:8001/v1/chat/completions -Method Post -ContentType 'application/json' -Body $stage13Body
docker cp scripts/release_smoke.py fa-stage13-core-api-1:/tmp/release_smoke.py
$stage13Python = @'
import json, sys, time
sys.path.insert(0, '/tmp')
from release_smoke import ApiSession
client=ApiSession('http://127.0.0.1:8000')
client.request('POST','/api/v1/auth/login',body={'email':'release-smoke@example.test','password':'release smoke password 2026'})
before=client.request('GET','/api/v1/accounts')
started=time.monotonic()
result=client.request('POST','/api/v1/advice',body={'currency':'RUB','through':'2027-10-16','question':'Explain the forecast'})
after=client.request('GET','/api/v1/accounts')
assert before == after
print(json.dumps({'advice_status':result['status'],'error_code':result['error_code'],'elapsed_seconds':round(time.monotonic()-started,2),'ledger_unchanged':True}))
'@
$stage13Python | docker compose -p fa-stage13-core --profile local-llm exec -T api python -
```

The full structured-advice command exceeded the client's `180 s` timeout with provider timeout
`120 s` and two retries. It did not reach the final assertion/print, so full structured success
is **not** claimed. Core stayed ready; subsequent SQL balance/count checks above confirmed data
preservation. The bounded timeout/unavailable contract is separately covered by fake-provider
tests. For a bounded single-attempt GPU trial use `LLM_MAX_RETRIES=0`; test full advice on the
target host before treating it as available to users.

## Production-like private runtime

The ignored `.env.production-rehearsal` used these public synthetic values. Never reuse them on
a public deployment:

```dotenv
POSTGRES_PASSWORD=stage13-rehearsal-database-2026-Alpha!
DATABASE_URL=postgresql+psycopg://financial_analytics:stage13-rehearsal-database-2026-Alpha!@postgres:5432/financial_analytics
PUBLIC_BASE_URL=https://finance.example.test
CORS_ORIGINS=["https://finance.example.test"]
TRUSTED_PROXY_IPS=["127.0.0.1"]
BOOTSTRAP_MASTER_EMAIL=release-smoke@example.test
SESSION_SECRET=stage13-rehearsal-session-2026-Alpha!9
CSRF_SECRET=stage13-rehearsal-csrf-2026-Bravo!8
EMAIL_TOKEN_SECRET=stage13-rehearsal-email-2026-Charlie!7
SMTP_HOST=smtp.example.test
SMTP_PORT=587
SMTP_FROM_ADDRESS=no-reply@example.test
SMTP_SECURITY=starttls
BACKEND_IMAGE=financial-analytics-backend:0.2.0
WEB_IMAGE=financial-analytics-web:0.2.0
LLM_PROVIDER=disabled
```

```powershell
$env:BACKEND_IMAGE = docker image inspect financial-analytics-backend:0.2.0 --format '{{index .RepoDigests 0}}'
$env:WEB_IMAGE = docker image inspect financial-analytics-web:0.2.0 --format '{{index .RepoDigests 0}}'
docker compose -p fa-stage13-prod --env-file .env.production-rehearsal -f compose.yaml -f compose.production.yaml --profile core config --quiet
docker compose -p fa-stage13-prod --env-file .env.production-rehearsal -f compose.yaml -f compose.production.yaml --profile core up -d --wait
Get-Content -Encoding utf8 scripts/release_smoke.py -Raw | docker compose -p fa-stage13-prod --env-file .env.production-rehearsal -f compose.yaml -f compose.production.yaml --profile core exec -T api python - --base-url http://127.0.0.1:8000
docker compose -p fa-stage13-prod --env-file .env.production-rehearsal -f compose.yaml -f compose.production.yaml --profile core exec -T web node -e "fetch('http://127.0.0.1:4173/health/live').then(async r=>console.log(r.status,(await r.json()).status))"
```

Observed: first run `30.0 s`, final repeat `31.5 s`, exit `0`, long-running services healthy, walkthrough passed with advice
disabled; web `200 alive`. Backend/web used local immutable RepoDigests; no registry push.
Parsed Compose model: no published ports, no build instructions, resource limits on every core
service, restart `always` (migrate `no`). Only internal ports appeared in `compose ps`.

Each actual startup command below returned exit `1`. Validation traceback did not print settings
inputs/secrets. Additional unit cases cover weak/reused secrets, HTTP origins, public URL,
SMTP TLS and wildcard/all-address proxy trust.

```powershell
docker compose -p fa-stage13-prod --env-file .env.production-rehearsal -f compose.yaml -f compose.production.yaml --profile core run --rm --no-deps -e DEBUG=true api
docker compose -p fa-stage13-prod --env-file .env.production-rehearsal -f compose.yaml -f compose.production.yaml --profile core run --rm --no-deps -e SESSION_COOKIE_SECURE=false api
docker compose -p fa-stage13-prod --env-file .env.production-rehearsal -f compose.yaml -f compose.production.yaml --profile core run --rm --no-deps -e 'CORS_ORIGINS=["*"]' api
docker compose -p fa-stage13-prod --env-file .env.production-rehearsal -f compose.yaml -f compose.production.yaml --profile core run --rm --no-deps -e SESSION_SECRET=development-session-key-change-me-0001 api
docker compose -p fa-stage13-prod --env-file .env.production-rehearsal -f compose.yaml -f compose.production.yaml --profile core run --rm --no-deps -e DATABASE_URL=postgresql+psycopg://financial_analytics:postgres@postgres:5432/financial_analytics api
docker compose -p fa-stage13-prod --env-file .env.production-rehearsal -f compose.yaml -f compose.production.yaml --profile core down --volumes
```

This smoke uses private container HTTP under production HTTPS assumptions. It does not prove a
real TLS ingress, public DNS, certificate renewal or real SMTP relay. Those require the selected
domain/host and deployment authorization. Mailpit exercises plaintext development SMTP; the
production adapter uses a certificate-verifying SSL context for STARTTLS/implicit TLS.

## Validation and cleanup

- Backend: lock, Ruff, strict mypy, OpenAPI/client drift; final `131 passed`, coverage `86.46%`,
  `67.48 s`. PostgreSQL gate includes clean upgrade/check/empty downgrade.
- Frontend: ESLint/Prettier, TypeScript/build; `44 passed`; coverage `89.05%` statements,
  `80.30%` branches, `84.95%` functions, `89.70%` lines.
- Chromium + real API/PostgreSQL/fake provider: all seven SPEC system scenarios passed (`1.4 m`).
- Backup/restore repeated with `scripts/backup_restore_drill.py` and the PostgreSQL 18 shell
  scripts in separate `stage13_backup_source` / `stage13_restore` databases. All row
  counts/digests, ledger balances and revision `20261016_0011` matched; restored current-head and
  metadata checks passed.
- Trivy `0.76.0`: repository lockfiles/Dockerfiles and application backend/web images passed
  High/Critical vulnerability/secret/misconfiguration gates. Mailpit image also passed with
  zero High/Critical findings and secrets. Optional vLLM upstream dependencies require their own
  pre-deployment security review; this is not a claim that every upstream image was scanned.

Cleanup removes only disposable `fa-stage13-*` resources. Existing user volumes, including the
earlier model cache, are preserved. No push, tag or external deployment was performed. Reports,
local environments, databases and model weights are not committed.
