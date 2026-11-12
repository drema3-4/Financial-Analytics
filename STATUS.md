# Статус проекта

Обновлено: 2026-11-12

## Текущее состояние

- Стадия: завершён корректирующий `14 — Core finance workflows` по пользовательским замечаниям.
- Дополнительно исправлен локальный запуск через `127.0.0.1` (CORS и hostname cookie sessions).
- Реализация: отдельные счета/вклады, единый журнал, inline-категории, полные исправления операций,
  CRUD счетов/вкладов/целей, автоматическая капитализация, рабочие диапазоны аналитики.
- Версия: предложение `0.2.0`, tag proposal `v0.2.0`; tag/push/external deploy не выполнялись.
- Следующий внешний gate: выбрать домен/хост, TLS/SMTP/secrets и оператора backup/rollback,
  выполнить независимую ручную приёмку и подтвердить публикацию.
- Host global toolchain из снимка этапа 00 всё ещё может отличаться от baseline; repository
  gate подтверждён в Python 3.12.12 environment, pnpm 12.12.1 и закреплённых containers.
- LLM не входит в core startup. Compose profile `local-llm` и `Qwen/Qwen3-4B-AWQ` **tested**
  на RTX 3050 6 ГБ: context 2048, одна sequence, GPU reserve `0.80`, non-thinking smoke,
  VRAM/latency и полный strict-schema adapter round-trip подтверждены; детали в `docs/LLM.md`.

## Подготовка к публикации на GitHub — 2026-11-12

- В README описаны установка одной строкой для Bash и PowerShell, первый запуск и публикация
  ветки `main`. `OWNER/REPO` заменяется адресом созданного репозитория. ADR-026 фиксирует выбор
  существующего профиля Compose `core` для локальной установки.
- Git и Docker исключают локальные отчёты, демонстрационные материалы и кэши. Проверены правила
  игнорирования `.env` и `.env.demo` и отсутствие этих файлов в истории `main`.
- На Windows с Docker Desktop проверен запуск из отдельного локального Git-клона с пустым томом
  PostgreSQL. API, web и worker прошли healthchecks, Alembic применил `20261017_0012 (head)`.
  `/start` вернул HTTP 200, `scripts/release_smoke.py` прошёл регистрацию, операцию, прогноз и
  цель. Снимок OpenAPI и сгенерированный TypeScript-клиент прошли сверку.

## Демонстрационный стенд — 2026-10-19

- Подготовлен отдельный `financial-analytics-demo` с собственным PostgreSQL volume, случайными
  независимыми secrets и вымышленным master-аккаунтом. Loopback web/API/vLLM:
  `4174`/`8002`/`8003`. Конфигурация — `compose.demo.yaml`, инструкция — `docs/DEMO.md`.
- `scripts/seed_demo.py` регистрирует demo через штатный bootstrap, затем использует API,
  CSRF и idempotency. История за апрель–октябрь: **176 операций**, 4 обычных счёта, 2 вклада,
  15 категорий, 4 группы, 9 регулярных правил, 5 целей и 6 сценариев. Фиксированные исторические
  операции проводит настоящий worker; они не удваиваются в irregular baseline.
- Повторный полный seed сохранил fingerprint журнала. Сравнение всех сценариев и три реальных
  запроса советника также сохранили каждую запись/posting; unbalanced transactions — **0**,
  recurring jobs — **61 succeeded**, dead-letter нет. Основная БД сохранила исходные количества:
  1 user, 10 transactions, 20 postings и 29 audit events. Основной stack оставлен остановленным.
- Массовое наполнение выявило ошибку partial unique-index inference после перехода psycopg
  prepared statement на generic plan. `ON CONFLICT` использует тот же статический predicate,
  что индекс, сохраняя bind parameters для owner/kind/currency. Регрессия воспроизводит прежний
  отказ с `prepare_threshold=0`/`force_generic_plan`, затем проверяет reuse и изоляцию tenants.
- Backend: **138 passed**, coverage **86.83%**, `78.29 s`; Poetry lock, Ruff lint/format,
  strict mypy и OpenAPI/client drift зелёные. Schema contract не менялся, Alembic head
  `20261017_0012`, metadata drift отсутствует. Demo backend/web собраны из закреплённых images;
  Compose core/demo и YAML format проходят проверки.
- Локальная Qwen3-4B-AWQ с context **4096**, одной sequence и non-thinking вернула `available`
  для всех пяти целей: базовые приоритеты **87.00 s**, экономия **66.20 s**, стресс **119.58 s**.
  JSON schema/evidence validation зелёные; timeout 120 s, retries 0. Финансовые расчёты остаются
  детерминированными. Снимки ответов, сравнение и маршрут показа — ignored `generated-reports/demo/`.
- Во встроенном браузере подтверждены обычный вход, пять целей с планом, сравнение экономии,
  роста доходов и стресса, а также успешный живой ответ советника с evidence и без console errors.
  Три вкладки оставлены для показа. Все пять demo services healthy. ADR-025 фиксирует
  изоляцию и эксплуатационный scope; новых продуктовых endpoint или миграций нет.

## Исправление локального запуска — 2026-10-19

- В Chrome воспроизведена ошибка `/start`: web на `127.0.0.1:4173` запрашивал API на
  `localhost:8000`, а CORS разрешал только `localhost:4173`. Контейнеры и БД были исправны.
- Без явного `VITE_API_BASE_URL` gateway выбирает API с тем же loopback hostname, что и web;
  Compose и Settings разрешают ровно два локальных origins. Это также сохраняет доступность
  `SameSite=Strict` session и CSRF cookies. Явный build-time API URL сохраняется, production
  по-прежнему требует настроенные HTTPS origins. Схема API и миграции не менялись.
- Добавлены регрессионные проверки выбора URL и credentialed CORS GET/preflight для обоих
  адресов, включая отказ постороннему origin и другому порту.
- Backend: **137 passed**, coverage **86.80%** (`73.41 s`), на отдельном PostgreSQL 18.6.
  Frontend: **55 passed**, coverage statements **89.20%**, branches **80.46%**, functions
  **85.58%**, lines **89.81%**. Poetry lock, Ruff, strict mypy, API/client drift, TypeScript,
  ESLint, Prettier и production build зелёные.
- Системные E2E: **8 passed** (`1.0 m`) с реальными API/PostgreSQL и пересобранным web image;
  responsive/error browser suite: **13 passed**, восемь system tests skipped в mock-only suite.
  Core пересобран; Alembic head `20261017_0012`, metadata drift отсутствует.
- Дополнительно Chrome на обоих адресах прошёл создание master → создание счёта с CSRF →
  reload → выход → повторный вход. Проверены реальные `Secure; SameSite=Strict` cookies
  без `addCookies`/подмены времени. Только disposable `*_e2e` БД; обычный core API возвращён
  в контейнер, все четыре сервиса healthy. Пользовательская БД не сбрасывалась.

## Готово в этапе 14

- Вклад создаётся отдельно с собственной начальной суммой и условиями; скрытый double-entry
  account создаётся атомарно. Обычные счета не приносят процентов. Пустой вклад можно пополнить
  переводом со счёта без удвоения капитала. Все основные операции доступны и для вкладов.
- UI принимает/показывает годовые проценты без ошибки масштаба. Principal cashflows учитывают
  opening adjustment и операции общего журнала. Worker и финансовые mutations сверяют due
  interest с ledger, проводят только разность и сохраняют audit; повторы/конкуренция без дублей.
- Полное исправление операции атомарно добавляет reversal + replacement. Удаление операции
  создаёт reversal; счета/вклады/цели архивируются. Условия и цели versioned, изменения traceable.
- Категорию можно ввести в форме операции/правила или выбрать существующую. Нет обязательного
  предварительного шага. Убраны дублирующие пустые формы фактов на странице вкладов.
- Analytics starts with aligned month boundaries; balance/report/forecast/goal caches обновляются
  после mutations. Даты учитывают profile timezone, утренние операции не создаются в будущем.
  Диалоги имеют уникальные aria IDs, мобильный профиль содержит ссылки на все разделы.
- ADR-024, SPEC/PLAN, OpenAPI/client, модель данных, расчёты, runbook и regression matrix обновлены.
  Детали плана, ручных действий и ограничений: `docs/CORE_FINANCE_ACCEPTANCE.md`.

## Проверки этапа 14

- Backend: **136 passed**, branch-inclusive coverage **86.80%**, `64.55 s`, с настоящим
  PostgreSQL 18.6. Включены Decimal golden/property, due/replay/concurrency, atomic rollback,
  CRUD/versions/audit/tenant isolation и upgrade legacy contracts без изменения проводок.
- Poetry lock, Ruff lint/format, strict mypy (`86 source files`), OpenAPI/client drift зелёные.
  Миграции upgrade/check/downgrade и metadata drift входят в pytest; установленная core schema
  отдельно проверена `alembic current/check`: `20261017_0012 (head)`, no new operations.
- Frontend: **52 passed**; coverage statements **89.15%**, branches **80.35%**, functions
  **85.52%**, lines **89.77%**. TypeScript, ESLint, Prettier и production build зелёные.
- Реальный Chromium + FastAPI + PostgreSQL: **8 system E2E passed** (повтор `1.7 m`), включая полное
  UI изменение/удаление всех четырёх сущностей. Отдельные responsive/a11y/error browser tests:
  **13 passed**, восемь system tests намеренно skipped в обычном mock-only запуске (повтор `20.7 s`).
- Дополнительно руками через браузер в отдельной реально работающей БД проверены расход с
  новой категорией, исправление суммы/баланса, standalone compound deposit, ставка 10 → 12,5%,
  перевод с карты во вклад, месячная аналитика, создание/изменение/удаление цели и создание/
  предпросмотр/пауза регулярного правила с новой категорией. На 360px проверен путь к вкладу
  через профиль; горизонтального overflow документа нет.
- Обычный core stack пересобран и запущен: web `http://localhost:4173`, API `:8000`, worker и
  PostgreSQL healthy. Перед миграцией сохранён custom-format backup (каталог проверен)
  `tmp/core-before-stage14-20261019.dump`; файл игнорируется Git. Тестовые записи не вносились
  в пользовательскую БД.

Воспроизводимые команды из корня (на host с рабочими pnpm/Poetry и disposable PostgreSQL):

```text
poetry check --lock
poetry run ruff check apps packages/backend tests migrations
poetry run ruff format --check apps packages/backend tests migrations
poetry run mypy
poetry run python scripts/generate_api_client.py --check
# TEST_DATABASE_URL points only to a disposable test server; pytest creates/drops its own DB.
poetry run pytest
pnpm typecheck
pnpm lint
pnpm format:check
pnpm test
pnpm build
pnpm test:e2e
# DATABASE_URL: separately migrated disposable system-E2E database, not the user's DB.
pnpm test:e2e:system
docker compose --profile core up --build --wait
docker compose --profile core exec -T api python -m alembic current
docker compose --profile core exec -T api python -m alembic check
```

На этом Windows host сломан global pnpm shim: те же scripts выполнены через `node` и
установленный `pnpm/bin/pnpm.mjs` версии 12.12.1, без замены lockfile/dependencies.

Ограничения этапа: legacy вклады оставлены в manual mode до проверки владельцем и включения
автоначислений (не угадываем дубли старых фактов); FX/импорт банка/налоговое право и пересчёт
будущих процентов от будущих recurring-пополнений не реализованы. Все сочетания условий во
всех мобильных браузерах руками не проверялись; сложные календарные случаи покрыты engine tests.
Удаление не уничтожает audit и не выполняет фактических банковских действий.

## Готово в этапе 13

- Явные `core`, `mail-catcher`, `local-llm`; core не требует GPU/LLM. Локальные web/API/Mailpit/
  vLLM ports привязаны к loopback. Production overlay убирает build/host ports, сохраняет
  healthchecks и задаёт restart policies/resource limits; upstream images закреплены digest.
  Для server rollout используются immutable digests собственных backend/web images.
- SMTP adapter поддерживает plain development, STARTTLS и implicit TLS с проверкой сертификата.
  Durable identity outbox атомарен с выпуском токена; lease/backoff, пять попыток, dead-letter,
  recovery после crash и очистка raw body при delivery/terminal state проверены на PostgreSQL.
- TTL: invitation `2 h`, verification `30 min`, reset `15 min`. Consume/mutation атомарны;
  повтор известного токена отклоняется и добавляет audit event. Reset завершает старые сессии;
  public recovery request одинаково отвечает `202` для существующей и неизвестной почты.
- UI/API allowlist/invitations разрешены только master/admin; только master выдаёт admin role.
  Revoke блокирует non-master, sessions и unused links, сохраняя user/financial/audit rows.
  Re-add возвращает существующий tenant. Production bootstrap ограничен настроенной почтой и
  выполняется оператором по приватному соединению до открытия ingress.
- Production startup отклоняет default/predictable/reused secrets, debug/DEBUG logging,
  wildcard/HTTP origins, insecure cookies, HTTP public URL, wildcard/all-address proxy trust,
  plaintext SMTP и отсутствующие обязательные настройки. Ошибки settings не печатают inputs.
- Обновлены OpenAPI/client, ADR-023, архитектура/модель данных/security docs, deployment guide,
  changelog, release checklist и user/admin runbook. TLS выдаётся выбранным оператором после
  выбора реального домена/хоста; выдуманного ACME deployment flow нет.

## Проверки этапа 13

- Backend: `131 passed`, coverage `86.46%`, `67.48 s`; Poetry lock, Ruff, strict mypy и
  OpenAPI/client drift зелёные. Migration upgrade/check/empty downgrade на PostgreSQL 18 зелёные.
- Frontend: `44 passed`; coverage statements `89.05%`, branches `80.30%`, functions `84.95%`,
  lines `89.70%`; ESLint, Prettier, TypeScript и production build зелёные.
- Реальный Chromium/FastAPI/PostgreSQL: все семь системных E2E сценариев `SPEC.md` прошли за
  `1.4 m`. Deterministic golden/property/reconciliation и cross-tenant gates входят в pytest.
- Clean-clone core: первый build/start `63.1 s`, финальный cached repeat `33.5 s`, healthy без
  vLLM. Release walkthrough: onboarding → expense → forecast/goal → disabled advice прошёл;
  `10000.00 - 125.25 = 9874.75 RUB` сверено exact Decimal.
- Mail-catcher: финальный clean repeat `27.5 s`, healthy, invitation/reset доставлены по одной попытке, replay обоих отклонён;
  audit содержит `2` rejection events, normal user admin API denied, raw delivery bodies очищены.
- Production-like: `30.0 s`, финальный повтор `31.5 s`, healthy, walkthrough прошёл, web `200 alive`, опубликованных
  ports/build instructions нет; фактический startup с debug/insecure cookie/wildcard CORS/
  default identity secret или слабым DB password завершился exit `1`.
- Backup/restore повторён на revision `20261016_0011`: все counts/digests, postings и balances
  совпали; current-head/metadata drift восстановленной БД зелёные.
- Trivy `0.76.0`: repository lockfiles/Dockerfiles и backend/web runtime — `0 High/Critical`,
  секретов не обнаружено. Полные generated reports/weights/DB/cache в commit не входят.
- GPU: corrected cold-cache startup `232.4 s`, vLLM healthy, simple chat `3048 ms`, observed
  VRAM `5961/6144 MiB`, OOM не наблюдался. После выключения core ready/provider disabled,
  revision `20261016_0011`, users `1`, transactions `2`, goals `1`, баланс `9874.75 RUB` сохранены.
  Полный structured advice превысил deadline клиента `180 s`; его успешность не заявляется.
- Точные команды, найденные/исправленные rehearsal issues и фактические ограничения:
  `docs/FRESH_MACHINE_REHEARSAL.md`.

## Definition of Done и остаточные ограничения

- [x] Все семь ключевых сценариев автоматизированы E2E; release walkthrough и семь ручных
  путей описаны в runbook. Локальная автоматическая release-приёмка пройдена.
- [x] Балансы, проценты, прогнозы и goal feasibility считаются exact decimal engine и сверены
  с независимыми golden/property examples; LLM не вычисляет финансовые результаты.
- [x] Повтор запросов/recurring jobs не создаёт postings-дубли; email delivery at-least-once,
  но ссылка действует один раз. Crash после приёма SMTP может доставить одинаковое письмо дважды.
- [x] Tenant isolation, auth/rate limits, CSRF, session/token replay и backup/restore проверены.
- [x] Core воспроизводится по README из clean clone без host Python/Node/LLM/GPU и hidden `.env`.
- [x] GPU enable/disable без schema delta и потери данных подтверждены; hardware/performance
  ограничение полного совета зафиксировано.
- [x] Код и application runtime прошли vulnerability/secret gates без High/Critical findings.
- [ ] Независимая ручная приёмка всех семи путей на выбранном публичном хосте.

Остаточные deployment boundaries: реальный домен/хост не выбран, TLS ingress/certificate renewal,
SMTP relay с реальными credentials, off-host backup schedule/retention и внешнее восстановление/
rollback ещё не проверены. Локальный smoke использует private HTTP внутри container network
при production HTTPS assumptions; это не доказательство TLS на внешнем домене. Bootstrap email
не является секретом — до инициализации master публичный ingress должен быть закрыт.

Rate limiter хранится в памяти одного API process: перед несколькими replicas нужен shared
limiter либо централизованный proxy policy, в том числе для email recovery abuse. Pending email
jobs содержат raw link до завершения/истечения; DB/backups требуют защиты секретов. Optional vLLM
имеет отдельный upstream security/hardware gate перед публичным использованием; итоговый
application image scan не объявляется полным scan всех upstream GPU dependencies. Скан и SBOM
перед реальной публикацией повторяются. Signed tag/push/deploy требуют отдельного разрешения.

На текущем GPU полный structured advice не уложился в `180 s` client deadline при provider
timeout `120 s` и двух retries. Успешный simple chat не считается доказательством полной
structured генерации. Для ограниченного latency budget оператору следует задать
`LLM_MAX_RETRIES=0` и отдельно проверить полный совет на целевом host; core и deterministic
финансовые сценарии от его результата не зависят.

## Готово в этапе 12

- Семь независимых Playwright system tests реализуют все numbered scenarios `SPEC.md`. Каждый
  тест сбрасывает только изолированную `*_e2e` database, API и browser используют fixed UTC
  clock, а trace/screenshot/video сохраняются только при failure.
- Scenario 2 доказывает полный путь UI action → API transaction → exact zero-sum postings →
  analytics evidence/net worth → forecast opening balance. Все суммы остаются decimal-строками.
- Threat matrix покрывает IDOR/cross-tenant, brute force/rate limits, CSRF/CORS, session
  fixation/replay, SQL/prompt injection, CSV formulas, upload/export boundary и log/LLM
  redaction. Принятых High/Critical исключений нет.
- API публикует JSON logs, безопасные request/correlation IDs, low-cardinality metrics,
  liveness и readiness DB/job/provider. Worker завершает текущий tick по signal, а lease replay
  остаётся idempotent; API имеет явное 30-секундное graceful window и закрывает DB pools.
- PostgreSQL backup/restore scripts для PowerShell/POSIX проверяют archive, запрещают overwrite и
  restore в source/non-empty DB. Drill сравнивает revision, counts, row digests, postings и
  ledger balance в отдельной восстановленной database.
- CI блокирует High/Critical dependency/container findings, secrets, misconfiguration и
  restricted/forbidden licenses; CycloneDX SBOM и полный license JSON сохраняются как artifacts.
  Runtime images переведены на pinned Alpine 3.23, собираются non-root и не содержат npm в web.
- На 10 000 posted transactions подтверждены существующие owner/date index и `<= 5 SELECT`;
  неподтверждённых cache/summary-table оптимизаций не добавлено.

## Проверки этапа 12

- System E2E: `7 passed` за `56.2 s` с реальными API/PostgreSQL/fake-provider; failure-only
  artifacts настроены в Playwright и CI.
- Backend: `124 passed` за `39.34 s`, coverage `86.93%`; Ruff, strict mypy, Poetry lock,
  OpenAPI/generated client drift и migration checks зелёные.
- Frontend: `40 passed` за `15.64 s`, statements coverage `92.80%`; ESLint, Prettier,
  TypeScript и production build зелёные.
- Performance: regression dataset `10 000` transactions прошёл за `5.26 s`; query plan не
  использовал sequential scan/temp I/O и остался в установленном statement budget.
- Restore drill: реальный custom-format backup был восстановлен в отдельную database; exact
  verification прошёл, observed local backup+restore+verify `~17 s`, Alembic revision
  `20261014_0010 (head)` и metadata drift check зелёные.
- Security: оба lockfile scans и итоговые backend/web image scans Trivy `0.76.0` показали
  `0 High/Critical` и `0 secrets`; Dockerfile misconfiguration scan также чистый.

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
| 12 E2E & Hardening | завершён | `test(12): harden end-to-end product behavior` | 7 system E2E, 124 backend, 40 frontend; restore/performance/security/container gates |
