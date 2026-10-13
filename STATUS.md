# Статус проекта

Обновлено: 2026-10-13

## Текущее состояние

- Стадия: завершён `03 — Identity, мастер-доступ и изоляция`; security matrix зелёная.
- Реализация: одноразовый master bootstrap, Argon2id credentials, opaque access/refresh
  sessions, CSRF/CORS/rate limits, allowlist/invitation/email-token foundation и revision
  `20261013_0003` готовы без SMTP, LLM и invitation UI.
- Следующий этап: `04 — Ledger API`; не начат и требует отдельного явного запроса.
- Host global toolchain из снимка этапа 00 всё ещё может отличаться от baseline; repository
  gate подтверждён в Python 3.12.12 environment, pnpm 12.12.1 и закреплённых containers.
- LLM не входит в core startup; local-vLLM остаётся задачей этапа 09.

## Готово в этапе 03

- Master создаётся ровно один раз под PostgreSQL advisory transaction lock и partial unique
  index; profile сохраняет нормализованный email, base currency, locale и IANA timezone.
- Пароли хэшируются Argon2id; login использует одинаковую дорогую verify-path для известного и
  неизвестного email и opportunistic rehash при смене параметров.
- Access/refresh/CSRF — независимые CSPRNG secrets; БД хранит только HMAC-SHA-256 digests.
  Refresh rotation атомарна, имеет абсолютный TTL, а replay/expiry/revoke тестируются.
- Browser contract использует `HttpOnly; Secure; SameSite=Strict` access/refresh cookies,
  session-bound double-submit CSRF, exact-origin credentialed CORS и единые problem details.
- Реализованы logout текущей/всех sessions и current profile; disabled user блокируется как в
  login, так и при последующем использовании/refresh session.
- Application `RateLimiter` port имеет thread-safe локальный sliding-window adapter для login
  и refresh. Горизонтальный server deployment потребует shared adapter.
- Созданы allowlist, invitation и purpose-bound email-token модели/use cases с повторной
  allowlist-проверкой, TTL, atomic one-time consumption и replay tests; SMTP/UI отложены до 13.
- Security mutations пишут append-only audit без email/password/raw tokens/financial payload.
- ADR-012 фиксирует session architecture; `docs/SECURITY.md` описывает threat model, границы и
  ротацию session/CSRF/email/database secrets.

## Проверки этапа 03

- Backend: Poetry lock, Ruff lint/format и strict mypy — зелёные; `50 passed`, total coverage
  `89.67%`.
- PostgreSQL integration: clean upgrade/downgrade disposable database, metadata drift,
  master concurrency gate, hash/redaction, rotation/replay/expiry/revoke/disabled user и
  двухвладельческая ID/filter isolation — зелёные.
- Frontend regression gate: ESLint, Prettier, TypeScript — зелёные; `7 passed`, coverage
  `100%`; production build — зелёный.
- Compose: backend image с Argon2 пересобран; PostgreSQL/API/worker/web healthy, Alembic
  `20261013_0003 (head)`, drift отсутствует; identity paths присутствуют в OpenAPI.
- Health smoke: API `ready`, database `up`, web `alive`; core login integration не использует
  SMTP или LLM.

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
