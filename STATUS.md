# Статус проекта

Обновлено: 2026-10-13

## Текущее состояние

- Стадия: завершён `05 — Scheduling`; worker/reliability gate зелёный.
- Реализация: recurring income/expense/transfer rules, UTC occurrences из wall-clock IANA
  schedules, PostgreSQL outbox с lease/backoff/dead-letter и owner-scoped management API
  доступны под `/api/v1`; revisions `20261013_0006`–`0007` применены.
- Следующий этап: `06 — Deposits`; не начат и требует отдельного явного запроса.
- Host global toolchain из снимка этапа 00 всё ещё может отличаться от baseline; repository
  gate подтверждён в Python 3.12.12 environment, pnpm 12.12.1 и закреплённых containers.
- LLM не входит в core startup; local-vLLM остаётся задачей этапа 09.

## Готово в этапе 05

- `recurring_rules` поддерживают income/expense/transfer, daily/weekly/monthly/yearly,
  pause/resume, inclusive end date, optimistic version и вычисляемый `next_occurrence_at`.
- Чистый domain calendar сохраняет monthly/yearly anchor. Несуществующий день обрабатывается
  явной policy `last_day`/`skip`; DST gap сдвигается вперёд, fold выбирает первый instant.
  Все persisted occurrences нормализованы в UTC.
- Catch-up policy `all` материализует каждый пропуск по одному за scheduler pass; `latest`
  создаёт только последний due occurrence. Preview возвращает UTC/local occurrences без
  записи rule, outbox, audit или ledger.
- Scheduler атомарно выбирает due rules через `FOR UPDATE SKIP LOCKED`, пишет immutable
  operation snapshot в `outbox_jobs` с уникальным dedup key `(rule_id, occurrence_at)` и
  двигает next occurrence.
- Worker claim использует `FOR UPDATE SKIP LOCKED`, 30-секундный lease, attempts, backoff
  5/10/20/40 секунд и `dead_letter` после пятой ошибки. Истёкший lease безопасно забирается
  конкурирующим worker.
- Job вызывает тот же `LedgerService`, что HTTP API, с source `recurring` и детерминированным
  idempotency key. Crash между ledger commit и job acknowledgement приводит к replay той же
  transaction, а не к дублю.
- API публикует create/list/get/update/pause/resume rules, preview, owner-scoped dead-letter
  list и аудируемый retry. Cross-owner IDs остаются неразличимым `404`.
- Редактирование rule влияет только на ещё не материализованные occurrences; созданные
  transactions и outbox snapshots не переписываются.
- ADR-014 фиксирует outbox/calendar semantics. `docs/SCHEDULING_RUNBOOK.md` описывает
  мониторинг, диагностику lease/backlog и единственную безопасную процедуру ручного retry.

## Проверки этапа 05

- Backend: Poetry lock, Ruff lint/format и strict mypy — зелёные; `68 passed`, total coverage
  `86.80%`.
- PostgreSQL integration: clean upgrade/downgrade, metadata drift, crash-after-commit,
  double delivery, два worker/`SKIP LOCKED`, `all`/`latest` catch-up, dead-letter/audit retry,
  rule edit immutability и cross-owner API isolation — зелёные.
- Calendar: month-end `last_day`/`skip`, leap year, DST gap/fold и inclusive end date —
  зелёные без ожидания реального времени; все clocks инъецируемы.
- Contract: checked-in OpenAPI snapshot и generated TypeScript client current; scheduling,
  preview и dead-letter paths проверены.
- Frontend regression gate: ESLint, Prettier, TypeScript — зелёные; `8 passed`, coverage
  `100%`; production build — зелёный.
- Compose: backend/web пересобраны; PostgreSQL/API/worker/web healthy, Alembic
  `20261013_0007 (head)`; recurring OpenAPI paths подтверждены smoke-test.

## Открытые продуктовые решения

- Базовая валюта и часовой пояс первого пользователя задаются в onboarding, а не фиксируются
  заранее.
- Межвалютный transfer пока запрещён; будущая модель должна хранить две явные суммы и курс.
- Трёхбуквенный код валюты, не входящий во встроенный список 0/3-decimal исключений, временно
  получает 2 minor units; полноценный versioned currency catalog требует отдельного решения.
- Юрисдикция и налоговые правила не предполагаются; параметры вводит пользователь.
- Конкретный SMTP-провайдер выбирается перед публичным развёртыванием.
- Перед несколькими API replicas локальный in-memory rate limiter заменяется shared adapter.

## Журнал этапов

| Этап | Состояние | Коммит | Проверки |
|---|---|---|---|
| Подготовка спецификации | завершён | — | ручная проверка документов |
| 00 Preflight | завершён | `chore(00): establish reproducible environment baseline` | scripts, GPU container, docs |
| 01 Bootstrap | завершён | `chore(01): bootstrap application workspace` | backend/frontend quality, migrations, Compose, health |
| 02 Domain & DB | завершён | `feat(02): establish audited financial domain` | 35 backend tests, property/integration, migration up/down, Compose |
| 03 Identity | завершён | `feat(03): secure identity and tenant isolation` | 50 backend tests, 89.67%, security matrix, migration, Compose |
| 04 Ledger API | завершён | `feat(04): expose idempotent ledger API` | 56 backend tests, generated client drift, 8 frontend tests, Compose |
| 05 Scheduling | завершён | `feat(05): process recurring operations reliably` | 68 backend tests, 86.80%, worker concurrency/replay, 8 frontend tests, Compose |
