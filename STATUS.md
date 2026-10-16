# Статус проекта

Обновлено: 2026-10-16

## Текущее состояние

- Стадия: завершён `11 — Finance UI`; все пользовательские сценарии существующего финансового
  API доступны через адаптивный интерфейс.
- Реализация: TanStack Query единообразно управляет server state без optimistic financial
  truth; dashboard, ledger journal, recurring rules, deposits, analytics, forecast/goals и
  advice показывают server-derived данные, freshness, timezone, currency и privacy boundaries.
- Следующий этап: `12 — E2E & Hardening`; не начат и требует отдельного явного запроса.
- Host global toolchain из снимка этапа 00 всё ещё может отличаться от baseline; repository
  gate подтверждён в Python 3.12.12 environment, pnpm 12.12.1 и закреплённых containers.
- LLM не входит в core startup. Compose profile `local-llm` и `Qwen/Qwen3-4B-AWQ` **tested**
  на RTX 3050 6 ГБ: context 2048, одна sequence, GPU reserve `0.80`, non-thinking smoke,
  VRAM/latency и полный strict-schema adapter round-trip подтверждены; детали в `docs/LLM.md`.

## Готово в этапе 11

- Dashboard показывает net worth, cash flow, income/expense, ближайшие активные recurring
  obligations, progress целей, счета и явный `data_through`; multi-currency данные не
  объединяются и сопровождаются предупреждением об отсутствии FX.
- Accounts/categories и transaction journal закрывают создание income/expense/transfer,
  category/group management, search/filters, cursor pagination, CSV export и append-only
  reversal с явным подтверждением последствий.
- Recurring UI создаёт правила, получает server preview, показывает local/UTC и IANA timezone,
  missing-day policy, next occurrence и pause/resume без optimistic state.
- Deposits включают terms/rate period/tax/capitalization форму, cashflow/withdrawal и actual
  interest ввод, server schedule, planned-vs-actual reconciliation и объяснение yield.
- Analytics содержит server-derived metrics, deterministic anomalies, period comparison,
  currency warnings, SVG overview и полную табличную альтернативу.
- Forecast editor показывает assumptions, month timeline, uncertainty/disclaimer и compare;
  goals показывают required contribution, contribution gap, shortfall, completion и явную
  priority strategy.
- Advice показывает provider status, request-scoped privacy consent, evidence anchors,
  confidence и disclaimer; suggestions не оформлены как команды или гарантии.
- Browser gateway расширен всеми существующими finance endpoints. Decimal money/rates идут в
  wire contract строками; JS number используется только для несмысловой геометрии SVG/progress.
  ADR-020 и `docs/UI.md` фиксируют server-state/read-after-write и accessibility правила.

## Проверки этапа 11

- Frontend: ESLint, Prettier, strict TypeScript и production build — зелёные.
- Component/integration: `39 passed`; coverage `92.80%` statements, `84.33%` branches,
  `92.45%` functions и `93.47%` lines, включая route smoke каждого финансового модуля,
  exact decimal operation payload и безопасное отображение API error.
- Playwright Chrome: `13 passed` — onboarding/login, responsive smoke всех восьми финансовых
  модулей, transaction API negative flow, invalid deposit term и disabled advice fallback.
- Keyboard/native semantics, focus baseline, screen-reader headings/labels/table alternatives и
  отсутствие horizontal overflow проверены component/Playwright smoke.

## Готово в этапе 10

- `docs/UI.md` фиксирует самостоятельное редакционное направление, design tokens, кириллическую
  типографику, chart palette, responsive rules и обязательные состояния вместо generic admin
  template. Базовые button/input/money/date/dialog/drawer/table/list/state/toast components
  используют нативную семантику и видимый focus.
- Browser gateway интегрирует checked-in generated client, credential cookies, double-submit
  CSRF, криптографический idempotency key и один session refresh. Истёкшая session получает
  отдельное состояние и безопасно возвращает пользователя ко входу.
- Первый запуск ведёт через master email/password, базовую валюту, locale, IANA timezone и
  первый счёт. Начальный остаток нормализуется из locale input только строковыми операциями и
  отправляется как Decimal contract; дата фиксируется как local noon выбранного timezone и
  сохраняется UTC instant.
- App shell использует public/protected/not-found boundaries, desktop sidebar и mobile
  header/bottom navigation. Dashboard подтверждает первый счёт, не забирая объём Finance UI
  этапа 11. Global error boundary сообщает, что финансовые данные не изменены.
- Playwright smoke перехватывает API на contract boundary, проверяет login и полный onboarding,
  строковый JSON amount, CSRF header, keyboard submit и отсутствие horizontal overflow при
  ширине 360 px. ADR-019 фиксирует session/onboarding boundary.

## Проверки этапа 10

- Frontend: ESLint и Prettier, strict TypeScript, production build — зелёные.
- Component/integration: `28 passed`; coverage `92.17%` statements, `84.11%` branches,
  `89.71%` functions и `93.07%` lines при required `80%`.
- Playwright Chromium/Chrome smoke: `2 passed` — существующий login и новый master onboarding
  до dashboard, включая mobile 360 px.

## Готово в этапе 09

- Application `AdviceProvider` port не содержит HTTP/SDK types. OpenAI-compatible adapter
  настраивает `base_url`, secret API key, model, timeout, retry budget и capability flags;
  `disabled` — отдельный provider и default.
- Bounded retry охватывает timeout/transport, `408/409/425/429/5xx`; остальные `4xx` не
  повторяются. Upstream body, URL, key, prompt и financial context не входят в ошибки/логи.
- Advice context исключает identity, names, comments/descriptions, raw transactions и ledger
  IDs. External user text требует request-scoped consent default off, остаётся untrusted data и
  проходит email/phone/card/token/secret redaction даже после consent.
- Strict response содержит summary, observations с evidence IDs, suggestions, assumptions,
  risks, confidence и фиксированный disclaimer. Extra/wrong fields и hallucinated evidence
  отклоняют весь ответ.
- `GET /api/v1/advice/status` и read/compute-only `POST /api/v1/advice` закреплены в OpenAPI и
  generated TypeScript client. Optional provider не участвует в readiness и не получает write
  tools; advice не создаёт ledger, audit, idempotency или другие DB records.
- Fake OpenAI-compatible server проверяет success, invalid JSON/envelope/schema, timeout,
  bounded retry, non-retryable error, rate limit/`Retry-After`, prompt injection framing,
  redaction и отсутствие API key в body.
- `local-llm` использует pinned `vllm/vllm-openai:v0.11.0` manifest, GPU reservation,
  persistent Hugging Face cache, `/health`, `Qwen/Qwen3-4B-AWQ`, context 2048, одну sequence и
  per-request non-thinking. Проверенный reserve для 6 ГБ — `0.80`; Xet отключён без отключения
  TLS verification. Core Compose model profile не включает.
- ADR-018 и `docs/LLM.md` фиксируют неперсистентный use case, privacy boundary, provider config,
  запуск профиля и честный hardware-test result.

## Проверки этапа 09

- Backend: Poetry lock, Ruff lint/format, strict mypy и generated OpenAPI/client drift — зелёные;
  полный PostgreSQL gate на pinned PostgreSQL 18: `109 passed`, migrations зелёные, total
  coverage `87.01%` при required `85%`; fake-provider contract matrix входит в этот прогон.
- Frontend на pinned pnpm `12.12.1`: ESLint, Prettier, TypeScript, production build зелёные;
  `8 passed`, coverage `100%`.
- Compose: production API/web images пересобраны; PostgreSQL, migrations, API, worker и web
  прошли runtime health с `LLM_PROVIDER=disabled`. Core service list не содержит vLLM; pinned
  image manifest и `local-llm` runtime проверены.
- RTX 3050 6 ГБ (`6144 MiB`, driver `577.05`): vLLM `/health=200`; observed max `5528 MiB`;
  simple non-thinking latency `3777 ms` cold и `81/100 ms` warm. Полный adapter + strict schema
  + evidence validation — `85,313 ms` с timeout 120 s; CUDA OOM не было.

## Готово в этапе 08

- `ForecastInputSnapshot` неизменяем и имеет canonical SHA-256 fingerprint. Одинаковые snapshot,
  scenario и algorithm/assumptions versions дают байт-в-байт одинаковый доменный результат.
- Чистый `monthly-cashflow-v1` строит ряд до произвольной даты из текущих остатков, будущих
  recurring occurrences, deposit schedules и median baseline по шести последним полным
  историческим месяцам. Все money/rate операции используют `Decimal` и half-even rounding.
- User scenarios изменяют income/expense, inflation, annual interest, one-time cashflows и
  horizon только в forecast input. Создание, изменение и сравнение сценариев не пишет postings
  и не меняет историю или соседние scenarios.
- Каждый прогноз возвращает monthly account/capital totals, effective assumptions, warnings и
  объяснимый min/max range `historical-expense-min-max-v1`; недостаточная полная история явно
  помечается, а не маскируется искусственным confidence score.
- Goals содержат target/date, saved amount, priority, linked account, required monthly
  contribution, expected completion date, shortfall и contribution gap. Несколько целей
  получают средства по явному waterfall `priority`, затем `target_date`, затем UUID.
- Owner-scoped CRUD для `/forecast-scenarios` и `/goals`, одиночный `/forecasts` и
  `/forecasts/compare` закреплены в OpenAPI и generated TypeScript client. Мутации сценариев и
  целей имеют optimistic version, idempotency и audit trail; cross-owner IDs возвращают `404`.
- ADR-017 и `docs/FORECASTS_AND_GOALS.md` фиксируют формулы, порядок применения cashflow,
  uncertainty/goal allocation и ограничения: результат является модельным прогнозом, а не
  финансовой гарантией.

## Проверки этапа 08

- Backend: Ruff lint/format, strict mypy, generated OpenAPI/client drift и Poetry lock — зелёные;
  `93 passed`, total coverage `86.74%`.
- Golden/property coverage включает zero activity, only recurrence, deposit maturity, missed
  target, already achieved, impossible contribution, inflation и same-snapshot reproducibility.
- PostgreSQL: clean upgrade/check/downgrade и metadata drift зелёные; scenario isolation,
  owner-scoped access, compare на одном snapshot, audit events и отсутствие ledger mutations
  подтверждены integration-тестом.
- Frontend: ESLint, Prettier, TypeScript и production build зелёные; `8 passed`, coverage `100%`.

## Готово в этапе 07

- Чистый analytics calculator восстанавливает каждый показатель из immutable asset postings.
  Income/expense/interest дают внешний cash flow, transfer нейтрален, adjustment влияет только
  на net worth, reversal в свою дату даёт противоположный вклад вида/категории оригинала.
- Каждый money/rate metric публикует формулу, exact decimal inputs и evidence с transaction и
  posting UUID. Category/group breakdown разделён по `flow_type` и точно сходится с totals.
- `categories.is_mandatory` имеет DB constraint `expense only`; mandatory share и savings rate
  возвращают `null` при неположительном denominator вместо выдуманного значения.
- Валюты агрегируются только отдельно. При нескольких валютах contract возвращает
  `currency_mode=separated_by_currency` и `combined_currency=null`; FX без сохранённых
  rate/source не выполняется.
- Day/ISO-week/month boundaries строятся из IANA timezone profile, переводятся в UTC и остаются
  полуоткрытыми. Пустые buckets имеют zero; текущий bucket помечается incomplete и обрезается
  `data_through`, а comparison использует тот же local elapsed cut предыдущего диапазона.
- Anomaly policy `median-mad-v1` сравнивает завершённый bucket с median/MAD шести предыдущих,
  возвращает rationale, baseline, signed deviation, threshold и evidence; LLM не участвует.
- `GET /api/v1/analytics/dashboard` и `GET /api/v1/reports/financial` закреплены в OpenAPI и
  generated TypeScript client. Ответ не содержит profile/description и подготовлен как основа
  будущего sanitized AdviceContext.
- ADR-016 и `docs/ANALYTICS.md` фиксируют формулы, transfers/reversals, open/empty/mixed-currency
  semantics, comparison/anomaly policy и measurement-first performance budget.

## Проверки этапа 07

- Backend: Ruff lint/format, strict mypy, generated OpenAPI/client drift — зелёные; `82 passed`,
  total coverage `87.37%`.
- PostgreSQL: clean upgrade/check/downgrade и metadata drift зелёные; API reconciliation,
  mixed-currency contract, reversal/transfer semantics и cross-owner isolation проверены.
- Synthetic performance gate: 10 000 transactions двух tenants; monthly owner/date plan
  использует partial posted index без sequential scan или temp I/O, result rows `<= 200`,
  application report выполняет `<= 5 SELECT`.
- Frontend: ESLint, Prettier, TypeScript зелёные; `8 passed`, coverage `100%`, production build
  зелёный. Compose backend/web пересобраны; PostgreSQL/API/worker/web healthy, Alembic
  `20261013_0009`; оба analytics paths подтверждены runtime OpenAPI smoke-test.

## Готово в этапе 06

- `DepositTerms` связывает owner-scoped principal account и currency с полуоткрытым сроком,
  непрерывными rate periods, explicit daily/month-end capitalization, Actual/365 Fixed или
  Actual/Actual ISDA, rounding mode/frequency, IANA timezone/cut-off, early-close rule, tax и
  алгоритмом `deposit-interest-v1`.
- Чистый engine считает daily accrual без clock/DB/framework, применяет cashflow до начисления
  по явному cut-off, поддерживает rate boundary, leap year, tax, `half_even`/`half_up`, partial
  withdrawal и полный deterministic reprice/forfeit при early close.
- API публикует create/list/get terms, linked cashflow transfer, factual interest posting и
  valuation: schedule, current principal/value, accrued interest, projected maturity value,
  Decimal XIRR effective yield и planned-vs-actual reconciliation.
- Пополнения/снятия остаются ordinary immutable transfer transactions с `deposit_id`.
  Фактический bank interest — отдельная double-entry transaction kind `interest`; reversal и
  новая корректировка не меняют terms или производный план и остаются в audit trail.
- `deposit_terms`/`deposit_rate_periods` append-only, составные owner/account/deposit FK не
  допускают cross-tenant links. Repository reads обязательным образом owner-scoped.
- ADR-015 фиксирует полузакрытые границы, cut-off/rounding/tax/early-close/XIRR semantics;
  `docs/DEPOSIT_CALCULATIONS.md` документирует формулы и связь плана с ledger fact.

## Проверки этапа 06

- Backend: Ruff lint/format, strict mypy, generated OpenAPI/client drift — зелёные; `75 passed`,
  total coverage `86.61%`.
- Эталонные fixtures: независимые CSV terms/rates/cashflows/formulas совпадают до minor-unit
  rounding для monthly/daily capitalization, cut-off, withdrawal, leap year, rounding, tax,
  rate boundary и early close; property tests подтверждают deterministic result.
- PostgreSQL: clean upgrade/check/downgrade и metadata drift зелёные; deposit cashflow,
  interest correction через reversal, append-only audit и cross-owner `404` проверены.
- Contract/frontend: все deposit paths и обязательные ambiguous parameters закреплены в
  OpenAPI; TypeScript client current; ESLint/Prettier/TypeScript зелёные, `8 passed`, frontend
  coverage `100%`, production build зелёный.

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
| 06 Deposits | завершён | `feat(06): model deposits and compound interest` | 75 backend tests, 86.61%, fixtures/property/integration/contract, 8 frontend tests, Compose |
| 07 Analytics | завершён | `feat(07): provide reconciled financial analytics` | 82 backend tests, 87.37%, reconciliation/plan/integration/contract, 8 frontend tests, Compose |
| 08 Forecast & Goals | завершён | `feat(08): forecast finances and plan goals` | 93 backend tests, 86.74%, golden/property/integration/contract, 8 frontend tests |
| 09 LLM Advice | завершён | `feat(09): add private provider-neutral financial advice` | 109 backend / 87.01%, fake provider matrix, 8 frontend tests; RTX 3050 local vLLM tested |
| 10 Frontend Foundation | завершён | `feat(10): build accessible application foundation` | 28 component/integration, 2 Playwright; lint/typecheck/build, a11y/responsive baseline |
| 11 Finance UI | завершён | `feat(11): deliver complete financial workflows` | 39 component/integration, 13 Playwright; lint/typecheck/build, responsive/a11y smoke |
