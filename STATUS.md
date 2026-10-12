# Статус проекта

Обновлено: 2026-10-13

## Текущее состояние

- Стадия: завершён `01 — bootstrap monorepo`.
- Реализация: core stack без бизнес-функций запускается одной Compose-командой.
- Следующий этап: `02 — domain & DB`; до него не добавлены доменные таблицы или финансовая
  логика.
- Host global toolchain из снимка этапа 00 всё ещё может отличаться от baseline; repository
  gate подтверждён в Python 3.12.12 environment, pnpm 12.12.1 и закреплённых containers.
- LLM не входит в core startup; local-vLLM остаётся задачей этапа 09.

## Готово в этапе 01

- Создан monorepo layout для FastAPI API, worker, React/Vite web, backend boundaries и общего
  frontend API package.
- Добавлены `poetry.lock` и `pnpm-lock.yaml`, Ruff, mypy strict baseline, pytest/coverage,
  TypeScript strict, ESLint, Prettier, Vitest и production build.
- Реализованы реальные `/health/live` и `/health/ready`, единый problem-details contract,
  безопасные request/correlation IDs, JSON logging и валидируемые masked settings.
- Добавлен core Compose: PostgreSQL, one-shot migration, API, worker и web; образы закреплены,
  данные находятся в named volume, runtime processes работают не от root.
- Добавлен пустой Alembic baseline `20261013_0001` без доменных таблиц.
- Добавлен CI для backend/frontend quality gates, clean-database migration smoke и Compose
  config.
- README содержит воспроизводимые команды для PowerShell, WSL2 и Linux; API contract описан в
  `docs/API.md`.

## Проверки этапа 01

- Backend: Ruff lint/format, mypy — зелёные; `18 passed`, total coverage `91%`.
- Frontend: ESLint, Prettier, TypeScript — зелёные; `6 passed`, выбранный прикладной код покрыт
  на `100%`; production build — зелёный.
- Compose: `docker compose config --quiet` — зелёный; `docker compose up --build --wait`
  поднял healthy PostgreSQL/API/worker/web.
- Health smoke: API `alive`, API `ready`, database `up`, web `alive`.
- Migration smoke на новом named volume: `20261013_0001 (head)`, exit code `0`.
- Runtime UID: API/worker `10001`, web `1000`, фактические PostgreSQL processes `999`.

## Открытые продуктовые решения

- Базовая валюта и часовой пояс первого пользователя задаются в onboarding, а не фиксируются
  заранее.
- Юрисдикция и налоговые правила не предполагаются; параметры вводит пользователь.
- Конкретный SMTP-провайдер выбирается перед публичным развёртыванием.

## Журнал этапов

| Этап | Состояние | Коммит | Проверки |
|---|---|---|---|
| Подготовка спецификации | завершён | — | ручная проверка документов |
| 00 Preflight | завершён | `chore(00): establish reproducible environment baseline` | scripts, GPU container, docs |
| 01 Bootstrap | завершён | `chore(01): bootstrap application workspace` | backend/frontend quality, migrations, Compose, health |
