# Financial Analytics

Local-first приложение для учёта личных финансов. Этап 05 даёт idempotent ledger API для
accounts, categories, income/expense/transfer/adjustment/reversal, stable cursor pagination,
UTF-8 CSV export, recurring rules и PostgreSQL outbox worker с lease/backoff/dead-letter.
Generated TypeScript client построен поверх double-entry domain core. Identity
использует одноразовый master bootstrap, Argon2id и ротируемые cookie sessions с CSRF/CORS.

Источники требований: [SPEC.md](SPEC.md), [PLAN.md](PLAN.md) и
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Быстрый запуск core stack

Нужны Docker Engine / Docker Desktop с Compose v2. На Windows должен использоваться Docker
Desktop с WSL2 backend и Linux containers.

Из корня репозитория на Windows PowerShell, в WSL2 или Linux выполните одну команду:

```text
docker compose up --build --wait
```

Команда собирает закреплённые Python/Node images, запускает PostgreSQL, применяет Alembic
миграции и ждёт healthchecks API, worker и web. LLM не входит в core stack и не влияет на
startup. Для zero-config локального запуска Compose использует пароль
`financial_analytics_dev`; PostgreSQL не публикуется на host. Это только development default.
Чтобы задать свой пароль до первого запуска, создайте `.env` из `.env.example` и замените
placeholder.

После запуска доступны:

- web: <http://localhost:4173>;
- API docs: <http://localhost:8000/docs>;
- liveness: <http://localhost:8000/health/live>;
- readiness: <http://localhost:8000/health/ready>.

Первый мастер создаётся один раз через `POST /api/v1/auth/bootstrap`; контракт доступен в
`/docs`. Задайте email, пароль длиной от 12 символов, базовую валюту, locale и IANA timezone.
Успешный ответ устанавливает Secure/HttpOnly session cookies, после чего повторный bootstrap
возвращает `409`. Для production обязательно замените три identity secrets из `.env.example`;
процедуры ротации описаны в [docs/SECURITY.md](docs/SECURITY.md).

`/health/live` сообщает о работе процесса. `/health/ready` возвращает `200` только после
успешного `SELECT 1` в PostgreSQL; при недоступности БД API продолжает стартовать и возвращает
единый `503 application/problem+json`.

Статус и логи:

```text
docker compose ps
docker compose logs --no-color api worker web postgres
```

Остановить stack, сохранив данные в named volume:

```text
docker compose down
```

Удаление volume выполняется только осознанно командой `docker compose down --volumes`: она
безвозвратно удаляет локальную БД.

## Закреплённый toolchain

- Python `3.12.12`, Poetry `2.5.1`;
- Node.js `24.21.0`, pnpm `12.12.1`;
- PostgreSQL `18.6`;
- container tags и multi-platform digests зафиксированы в Dockerfiles и `compose.yaml`;
- Python и frontend dependency graph зафиксированы в `poetry.lock` и `pnpm-lock.yaml`.

Проверить host environment:

```powershell
./scripts/preflight.ps1 -SkipGpuContainer
```

```bash
./scripts/preflight.sh --skip-gpu-container
```

Подробности установки версий и ограничения Windows описаны в
[docs/ENVIRONMENT.md](docs/ENVIRONMENT.md). Python 3.12.12 не имеет официального Windows
installer, поэтому для этой версии используйте доверенный version manager или WSL2, либо
выполняйте проверки в закреплённом backend image.

## Backend: локальная разработка

Команды одинаковы в PowerShell, WSL2 и Linux после выбора Python `3.12.12`:

```text
poetry env use 3.12.12
poetry install --no-interaction
poetry check --lock
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy
poetry run python scripts/generate_api_client.py --check
poetry run pytest
```

Локальный API использует `DATABASE_URL` из environment или `.env`. Запуск:

```text
poetry run financial-analytics-api
```

Worker:

```text
poetry run financial-analytics-worker
```

Применить и проверить миграции при доступном PostgreSQL:

PowerShell:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://financial_analytics:financial_analytics_dev@localhost:5432/financial_analytics"
poetry run alembic upgrade head
poetry run alembic current --check-heads
poetry run alembic check
```

WSL2 / Linux:

```bash
export DATABASE_URL="postgresql+psycopg://financial_analytics:financial_analytics_dev@localhost:5432/financial_analytics"
poetry run alembic upgrade head
poetry run alembic current --check-heads
poetry run alembic check
```

По умолчанию Compose PostgreSQL не публикует порт на host. Для host Poetry-команд временно
добавьте `ports: ["5432:5432"]` через локальный Compose override; не коммитьте такой override
для публичного развёртывания. Без override миграции проверяются внутри сети Compose:

```text
docker compose run --rm migrate python -m alembic current --check-heads
```

## Frontend: локальная разработка

Активируйте ровно зафиксированный pnpm через Corepack:

```text
corepack enable
corepack prepare pnpm@12.12.1 --activate
pnpm install --frozen-lockfile
```

Quality gate:

```text
pnpm lint
pnpm format:check
pnpm typecheck
pnpm test
pnpm build
```

Development server:

```text
pnpm --filter @financial-analytics/web exec vite --host 127.0.0.1
```

По умолчанию web обращается к `http://localhost:8000`. Другой адрес задаётся через
`VITE_API_BASE_URL` до build/start.

## Compose и migration smoke

Проверка Compose без запуска сервисов:

```text
docker compose config --quiet
```

Revisions `20261013_0004`–`0007` добавляют Ledger API и recurring rules/outbox. CI проверяет
upgrade на чистой PostgreSQL database, отсутствие drift между SQLAlchemy metadata и Alembic,
integration tests и downgrade до пустого bootstrap revision. Полная схема и правила — в
[docs/DATA_MODEL.md](docs/DATA_MODEL.md), а мониторинг/retry worker — в
[docs/SCHEDULING_RUNBOOK.md](docs/SCHEDULING_RUNBOOK.md). Security model — в
[docs/SECURITY.md](docs/SECURITY.md).

## Структура

```text
apps/api/                    FastAPI composition root и HTTP contracts
apps/worker/                 отдельный background process
apps/web/                    React / TypeScript / Vite SPA
packages/backend/domain/     framework-independent domain boundary
packages/backend/app/        use cases and ports boundary
packages/backend/infra/      settings и database adapters
packages/frontend/api/       общие TypeScript API contracts
tests/unit/                  backend unit/component tests
tests/integration/           PostgreSQL repositories, invariants и migrations
tests/contract/              OpenAPI contract tests
infra/docker/                non-root runtime images
migrations/                  Alembic environment и revisions
```

Формат health/error API и заголовки трассировки описаны в
[docs/API.md](docs/API.md). Текущий gate — в [STATUS.md](STATUS.md).
