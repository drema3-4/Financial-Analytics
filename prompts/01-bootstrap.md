# Этап 01 — Bootstrap monorepo

## Цель

Создать минимальный, запускаемый и проверяемый каркас всего стека без бизнес-функций.

## Выполни

- Создай структуру из `docs/ARCHITECTURE.md`: FastAPI API, worker process, React/TypeScript/Vite web и общие пакеты.
- Настрой Poetry под Python 3.12.12 environment, lockfile, Ruff, mypy strict-enough baseline, pytest и coverage. Не добавляй vLLM в Poetry.
- Настрой pnpm workspace, зафиксированный `packageManager`, TypeScript strict, ESLint, formatting, Vitest и production build.
- Реализуй `/health/live`, `/health/ready`, единый формат ошибок, request/correlation ID и безопасные settings.
- Добавь PostgreSQL и core services в Compose с healthchecks, named volumes и pinned images. API startup не должен зависеть от LLM.
- Добавь Alembic baseline без доменных таблиц и проверку миграции на чистой БД.
- Добавь CI workflow: backend lint/typecheck/tests, frontend lint/typecheck/tests/build, migration smoke и проверка Compose config.
- Обнови README точными командами Poetry/pnpm/Compose для Windows+WSL2 и Linux.

## Приёмка

- Core stack стартует одной документированной командой; health endpoints отражают реальное состояние.
- Все quality-команды работают локально и в CI, нет подавлений «на будущее».
- Контейнеры не запускаются root там, где это практично, секреты не baked в images.
- Empty test suites не дают ложный зелёный сигнал: есть минимум один meaningful test на слой.
- Обновлён `STATUS.md`; создан commit `chore(01): bootstrap application workspace`.

