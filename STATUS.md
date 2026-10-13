# Статус проекта

Обновлено: 2026-10-13

## Текущее состояние

- Стадия: завершён `04 — Accounts, categories и ledger API`; API/contract gate зелёный.
- Реализация: accounts с opening-balance posting, category groups/categories/tags,
  income/expense/transfer/adjustment/reversal, filters, snapshot cursor pagination и UTF-8
  CSV export доступны под `/api/v1`; revisions `20261013_0004`–`0005` применены.
- Следующий этап: `05 — Scheduling`; не начат и требует отдельного явного запроса.
- Host global toolchain из снимка этапа 00 всё ещё может отличаться от baseline; repository
  gate подтверждён в Python 3.12.12 environment, pnpm 12.12.1 и закреплённых containers.
- LLM не входит в core startup; local-vLLM остаётся задачей этапа 09.

## Готово в этапе 04

- Все пользовательские reads/writes owner-scoped; чужие account/transaction IDs дают
  одинаковый `404`. Cookie-authenticated mutations сохраняют session-bound CSRF gate.
- Все create и reversal commands требуют `Idempotency-Key`. Owner/scope/key advisory lock
  сериализует concurrent duplicates: одинаковый canonical payload возвращает тот же resource,
  другой payload получает `409 idempotency_conflict`.
- Opening balance и ручная сверка — immutable double-entry `adjustment` через скрытый
  owner/currency-scoped `system_equity`; system accounts не попадают в пользовательский list.
- Income, expense и transfer дают детерминированные postings; balances всегда перестраиваются
  из postings. Reversal полностью инвертирует original и сохраняет causal links.
- Account archive не удаляет историю и блокирует новые postings; DELETE для posted transaction
  отсутствует, а DB triggers защищают transaction, postings, source и transaction tags.
- Journal поддерживает account/category/tag/kind/date/search filters и snapshot keyset cursor
  по `(occurred_at, id)`, устойчивый даже к backdated insert между страницами.
- CSV формируется как UTF-8 с BOM/CRLF, RFC 4180 escaping и spreadsheet-formula hardening.
- Pydantic принимает money только как decimal string + currency; float/implicit rounding
  отклоняются. OpenAPI содержит examples/problem details и зафиксирован snapshot.
- Детерминированный generator создаёт typed TypeScript fetch-client; CI `--check` запрещает
  drift между приложением, `docs/openapi.json` и generated source. UI не добавлялся.
- ADR-013 фиксирует adjustment, concurrency/idempotency, pagination и contract generation.

## Проверки этапа 04

- Backend: Poetry lock, Ruff lint/format и strict mypy — зелёные; `56 passed`, total coverage
  `87.81%`.
- PostgreSQL integration: clean upgrade/downgrade, metadata drift, six-way concurrent replay,
  duplicate-key conflict, cross-owner ID isolation, category grouping, posting/balance,
  immutable tags, snapshot pagination и CSV escaping/encoding — зелёные.
- Contract: checked-in OpenAPI snapshot совпадает с app schema; generated TypeScript client
  current. Money schema имеет string amount и examples; posted DELETE отсутствует.
- Frontend regression gate: ESLint, Prettier, TypeScript — зелёные; `8 passed`, coverage
  `100%`; production build — зелёный.
- Compose: backend/web пересобраны; PostgreSQL/API/worker/web healthy, Alembic
  `20261013_0005 (head)`; `/health/ready`, accounts и CSV OpenAPI paths подтверждены smoke.

## Открытые продуктовые решения

- Базовая валюта и часовой пояс первого пользователя задаются в onboarding, а не фиксируются
  заранее.
- Межвалютный transfer пока запрещён; будущая модель должна хранить две явные суммы и курс.
- Трёхбуквенный код валюты, не входящий в встроенный список 0/3-decimal исключений, временно
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
