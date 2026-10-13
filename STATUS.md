# Статус проекта

Обновлено: 2026-10-13

## Текущее состояние

- Стадия: реализован `02 — domain & DB`; работа остановлена на обязательном human gate.
- Реализация: чистый financial domain, audited double-entry ledger, owner-scoped PostgreSQL
  adapters и revision `20261013_0002` готовы без HTTP CRUD.
- Следующий этап: `03 — Identity` не начат и требует явного продолжения после архитектурной
  проверки схемы и решений этапа 02.
- Host global toolchain из снимка этапа 00 всё ещё может отличаться от baseline; repository
  gate подтверждён в Python 3.12.12 environment, pnpm 12.12.1 и закреплённых containers.
- LLM не входит в core startup; local-vLLM остаётся задачей этапа 09.

## Готово в этапе 02

- Добавлены строгие value objects `Currency`, `Money`, `Rate`, rounding policy, `DateRange` и
  UTC-normalized `Instant`; float, special Decimal values и неявное округление запрещены.
- Реализованы accounts, category groups/categories/tags, postings и фабрики income, expense,
  transfer и exact reversal. Балансы перестраиваются только из posting.
- Application boundary содержит owner-scoped repository/UoW ports и атомарный
  `RecordTransaction`; domain не импортирует FastAPI или SQLAlchemy.
- PostgreSQL adapters используют mandatory `owner_id`, optimistic version и одну транзакцию
  для ledger, audit и idempotency record.
- Revision `20261013_0002` создаёт Identity shell, Finance и Control schema с composite owner
  FK, indexes, `NUMERIC(38, 9)`, append-only guards и deferred balance/reversal triggers.
- Добавлены unit, Hypothesis property-based и PostgreSQL integration tests для balance,
  currency mismatch, rounding, reversal, rebuild, rollback, idempotency, optimistic locking и
  cross-owner isolation.
- Создан `docs/DATA_MODEL.md`; точность, DB gate, Identity shell и границы этапа закреплены в
  ADR-009—ADR-011. API contract явно подтверждает отсутствие HTTP CRUD на этапе 02.

## Проверки этапа 02

- Backend: Poetry lock, Ruff lint/format и strict mypy — зелёные; `35 passed`, total coverage
  `87.97%`.
- Из них PostgreSQL integration: `6 passed`; clean upgrade, metadata drift check и downgrade
  пустой disposable database до `20261013_0001` проверены.
- Frontend regression gate: ESLint, Prettier, TypeScript — зелёные; `6 passed`, coverage
  `100%`; production build — зелёный.
- Compose: финальный backend image пересобран; пустая локальная схема прошла downgrade/upgrade;
  PostgreSQL/API/worker/web healthy, Alembic `20261013_0002 (head)`, drift отсутствует.
- Health smoke: API `ready`, database `up`, web `alive`.

## Открытые продуктовые решения

- Базовая валюта и часовой пояс первого пользователя задаются в onboarding, а не фиксируются
  заранее.
- Межвалютный transfer пока запрещён; будущая модель должна хранить две явные суммы и курс.
- Трёхбуквенный код валюты, не входящий в встроенный список 0/3-decimal исключений, временно
  получает 2 minor units; полноценный versioned currency catalog требует отдельного решения.
- Юрисдикция и налоговые правила не предполагаются; параметры вводит пользователь.
- Конкретный SMTP-провайдер выбирается перед публичным развёртыванием.

## Журнал этапов

| Этап | Состояние | Коммит | Проверки |
|---|---|---|---|
| Подготовка спецификации | завершён | — | ручная проверка документов |
| 00 Preflight | завершён | `chore(00): establish reproducible environment baseline` | scripts, GPU container, docs |
| 01 Bootstrap | завершён | `chore(01): bootstrap application workspace` | backend/frontend quality, migrations, Compose, health |
| 02 Domain & DB | human gate | `feat(02): establish audited financial domain` | 35 backend tests, property/integration, migration up/down, Compose |
