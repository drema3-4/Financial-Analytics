# Журнал архитектурных решений

## ADR-001: модульный монолит

**Решение:** один FastAPI backend, отдельный процесс worker и одна PostgreSQL БД.

**Почему:** персональный продукт не оправдывает распределённую сложность; транзакции ledger и outbox остаются атомарными. Границы модулей и порты сохраняют возможность выделения сервисов позднее.

## ADR-002: double-entry ledger как источник истины

**Решение:** баланс и отчёты выводятся из сбалансированных posting; проведённые записи исправляются reversal/adjustment.

**Почему:** это делает историю проверяемой, переводы однозначными, а кэшируемые остатки — восстанавливаемыми.

## ADR-003: PostgreSQL-backed worker в MVP

**Решение:** durable job table, `SKIP LOCKED`, outbox; Redis не обязателен.

**Почему:** меньше сервисов для локальной установки и достаточно для низкой нагрузки. Порт очереди не связывает домен с реализацией.

## ADR-004: OpenAI-compatible, а не «OpenAPI-compatible», для LLM

**Решение:** адаптер вызывает совместимый с OpenAI endpoint. Сам backend параллельно публикует обычную OpenAPI-схему своего REST API.

**Почему:** это два разных стандарта/контракта. Такое разделение позволяет переключать vLLM и внешний API конфигурацией.

## ADR-005: LLM не участвует в расчётах и мутациях

**Решение:** LLM получает sanitized aggregates и возвращает валидируемое объяснение; инструментов записи нет.

**Почему:** советы вероятностны, а деньги требуют воспроизводимости, тестируемости и аудита.

## ADR-006: локальный кандидат Qwen3-4B-AWQ, но с обязательным benchmark gate

**Решение:** первым испытывается 4-битный Qwen3 4B через vLLM с малым контекстом и одной последовательностью; fallback — меньшая модель или внешний провайдер.

**Почему:** модель официально имеет AWQ-вариант и заявленный vLLM-запуск, но 6 ГБ VRAM находится близко к практической границе после учёта runtime и KV cache. Документ не обещает то, что нельзя подтвердить без конкретной машины/драйвера.

## ADR-007: точная версия Python на уровне среды

**Решение:** `.python-version` и Docker image фиксируют 3.12.12; `pyproject.toml` объявляет совместимость `>=3.12,<3.13`, если зависимость не требует более строгого ограничения.

**Почему:** воспроизводимая среда и корректные package metadata — разные задачи. Lockfile и контейнер фиксируют фактическую сборку.

## ADR-008: воспроизводимый baseline toolchain и container images

**Дата:** 2026-10-13.

**Решение:** зафиксировать следующие версии для этапов bootstrap и локальной разработки:

| Компонент | Зафиксированная версия |
|---|---|
| Node.js | `24.21.0` (LTS) |
| pnpm | `12.12.1` |
| Python | `3.12.12` согласно ADR-007 |
| Poetry | `2.5.1` |
| PostgreSQL | `18.6` |

Базовые container images фиксируются полным тегом и multi-platform manifest digest:

```text
python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
node:24.21.0-bookworm-slim@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20
postgres:18.6-bookworm@sha256:afc7e2d441324c0388fa80c3d24f733b4194a4eb7f47dd8ee2b08eb1a24a647c
nvidia/cuda:12.8.1-base-ubuntu24.04@sha256:133c78a0575303be34164d0b90137a042172bdf60696af01a3c424ab402d86e2
```

CUDA image используется только для диагностики GPU, не как образ приложения. Версия vLLM image и модели намеренно не утверждаются на этапе 00: их фиксация требует профильного smoke-test на этапе 09.

**Почему:** Node 24 находится в LTS, pnpm 12 официально совместим с Node 24, Poetry 2.5.1 является стабильным patch, а PostgreSQL 18.6 — текущим поддерживаемым minor линии 18 на дату решения. Debian Bookworm даёт общий glibc baseline для Python, Node и PostgreSQL. Digest защищает сборку от незаметного перемещения тега; обновление digest выполняется отдельным осознанным изменением с повторной проверкой.

Python 3.12.12 сохранён из исходного требования, хотя на дату решения он уже заменён более новым security patch и не имеет официального Windows installer. Это известное ограничение: разработчик использует официальный source release через доверенный version manager/WSL2 или закреплённый Linux image, а изменение версии требует нового ADR.

## ADR-009: точность финансовых значений и округление

**Дата:** 2026-10-13.

**Решение:** posting amounts хранятся как PostgreSQL `NUMERIC(38, 9)`, но доменный `Money`
принимает только точные `Decimal`/integer/string boundaries и проверяет minor units валюты.
`Rate` допускает до 12 дробных знаков. Округление не выполняется неявно: вызывающий код
обязан выбрать `HALF_EVEN` или `HALF_UP`. Binary float и нечисловые special values запрещены.

**Почему:** storage scale оставляет запас для последующих FX и начислений, а currency scale не
позволяет провести сумму, которую невозможно выразить в расчётных единицах выбранной валюты.
Явная policy делает результаты воспроизводимыми и тестируемыми.

## ADR-010: DB-level ledger gate и tenant-scoped repositories

**Дата:** 2026-10-13.

**Решение:** repository создаётся только с обязательным `owner_id`; пользовательские связи
дублируют owner в составных foreign keys. Запись ledger внутри одной DB-транзакции проходит
служебное состояние `pending`, получает postings и переводится в `posted`. Deferred constraint
triggers запрещают commit pending/несбалансированного ledger, а posted transactions и postings
неизменяемы. Reversal ссылается на исходную transaction и на каждую исходную posting.

**Почему:** обычный row-level `CHECK` не может доказать сумму нескольких postings. Deferred
проверка видит итог атомарной команды и защищает инвариант даже от прямого SQL. Составные FK
не позволяют случайно связать строки разных владельцев, а repository API не имеет
незаскопированных read-методов.

## ADR-011: узкий Identity shell в этапе 02

**Дата:** 2026-10-13.

**Решение:** этап 02 создаёт только таблицу `users(id, created_at)` как FK-root для `owner_id` и
`actor_id`. Credentials, sessions, profile, allowlist и bootstrap master не реализуются до
этапа 03.

**Почему:** финансовые таблицы уже должны доказывать tenant isolation, но реализация
аутентификации до human gate нарушила бы последовательность `PLAN.md`.

## ADR-012: opaque browser sessions, double-submit CSRF и локальный rate limiter

**Дата:** 2026-10-13.

**Решение:** браузер получает два независимых opaque bearer token: короткий access и
долгоживущий refresh. Оба содержат случайный secret и идентификатор server-side session;
в PostgreSQL сохраняются только HMAC-SHA-256 digests secret. Refresh при каждом успешном
использовании атомарно заменяет access, refresh и CSRF secret, не продлевая абсолютный
30-дневный срок. Повтор старого refresh всегда отклоняется; если запрос также доказывает
владение текущим session-bound CSRF secret, atomic compare отзывает session как replay.

Access и refresh передаются только в `HttpOnly; Secure; SameSite=Strict` cookies. Отдельный
случайный CSRF secret доступен JavaScript в `Secure; SameSite=Strict` cookie, привязан к
session своим HMAC digest и должен совпасть с `X-CSRF-Token` для cookie-authenticated
мутаций. CORS принимает credentials только от явного allowlist origins; wildcard запрещён
во всех средах.

Application boundary получает `RateLimiter` port. Этап 03 использует thread-safe sliding
window в памяти процесса для login и refresh. Перед горизонтальным server deployment порт
должен получить общий durable/Redis adapter, но локальный core не получает новый сервис.

**Почему:** opaque sessions позволяют немедленно отзывать отдельную или все сессии, не
помещают claims в браузер и дают однозначную rotation/replay semantics. Раздельные secrets
сокращают последствия утечки одного cookie. Double-submit с server-side binding защищает
cookie-аутентифицированные мутации, а строгий CORS не полагается на wildcard. Локальному
однопроцессному MVP достаточно in-memory limiter без преждевременной инфраструктуры.

## ADR-013: ledger command API, adjustments и стабильная выдача

**Дата:** 2026-10-13.

**Решение:** начальный остаток и ручная корректировка являются immutable transaction типа
`adjustment`. Вторая сторона проводки — скрытый owner-scoped `system_equity` account той же
валюты; HTTP API не выдаёт system accounts как пользовательские. Коррекция проведённой
операции выполняется reversal и, если нужно, новой командой, а не изменением или удалением
истории.

Все create/reversal commands требуют `Idempotency-Key`. Перед чтением append-only replay
record PostgreSQL adapter берёт transaction-level advisory lock, вычисленный из
`owner/scope/key`: конкурентные одинаковые payload возвращают один resource, а иной payload
получает `409`. Request hash строится из канонического JSON контракта.

Журнал использует descending keyset pagination по `(occurred_at, id)` и opaque base64url
cursor. OpenAPI фиксируется в repository; детерминированный generator строит TypeScript
fetch-client и в `--check` режиме используется как CI drift gate.

**Почему:** отдельный adjustment не искажает cash-flow как доход/расход, но сохраняет
double-entry и audit trail. Advisory lock закрывает race до unique constraint без глобальной
сериализации. Keyset cursor остаётся стабильным при вставке новых операций между страницами,
а checked-in snapshot делает HTTP contract и клиент воспроизводимыми.

## ADR-014: materialized recurring occurrences и PostgreSQL outbox

**Дата:** 2026-10-13.

**Решение:** регулярное правило хранит wall-clock расписание (`starts_on`, `local_time`, IANA
timezone), текущее `next_occurrence_at` в UTC и immutable anchor дня/месяца. Scheduler в одной
PostgreSQL-транзакции выбирает due-правила через `FOR UPDATE SKIP LOCKED`, создаёт outbox job
с полным снимком операции и уникальным `dedup_key = (rule_id, occurrence_at)`, затем двигает
`next_occurrence_at`. Поэтому последующее редактирование правила не меняет уже
материализованный occurrence.

Worker арендует jobs через `FOR UPDATE SKIP LOCKED`. Lease имеет владельца и UTC expiry,
claim увеличивает `attempts`, а ошибка переводит job в delayed retry с ограниченным
экспоненциальным backoff. После исчерпания попыток job остаётся в `dead_letter`; ручной retry
возвращает его в очередь и пишет append-only audit event. Финансовая команда выполняется тем
же `LedgerService`, что HTTP API, с ключом `<rule_id>:<occurrence_at UTC>` и каноническим hash
снимка. Commit ledger и подтверждение job намеренно разделены: crash между ними приводит к
повторной доставке, которую поглощает ledger idempotency record.

`catch_up_policy=all` материализует каждый пропущенный occurrence (по одному на правило за
проход для ограничения нагрузки); `latest` материализует только последний due occurrence и
явно пропускает более ранние. Monthly/yearly anchor не дрейфует после короткого месяца:
`last_day` использует последний день конкретного месяца, `skip` пропускает несуществующую
дату. Для DST неоднозначное local time выбирает первый instant (`fold=0`), а несуществующее
local time сдвигается вперёд на величину gap; в ledger всегда сохраняется полученный UTC
instant.

**Почему:** снимок отделяет уже принятое к исполнению финансовое событие от изменяемого
шаблона, а связка durable outbox + idempotent ledger обеспечивает at-least-once delivery с
exactly-once финансовым эффектом без распределённой транзакции. Wall-clock anchor сохраняет
ожидаемое пользовательское время при смене UTC offset и делает leap-year/month-end политику
явной и тестируемой.

## ADR-015: детерминированный план вклада поверх immutable ledger

**Дата:** 2026-10-13.

**Решение:** условия вклада и непересекающиеся интервалы номинальных ставок неизменяемы после
создания. Расчётный интервал дня полуоткрытый: проценты за дату `d` начисляются на
`[d, d + 1)`, дата погашения процентов не приносит. Rate-periods также полуоткрыты и обязаны
без пробелов покрывать весь договорный срок. Поддерживаются явно названные конвенции
`actual_365_fixed` и `actual_actual_isda`; капитализация задаётся как `daily` либо
`monthly_calendar_end`, а округление отдельно задаёт mode (`half_even`/`half_up`) и момент
(`daily`/`capitalization`). Налоговая ставка обязательна даже при нулевом налоге и применяется
к положительному gross interest при каждой капитализации.

Для датированных ledger cashflows договор хранит IANA timezone, local cut-off time и отдельный
признак включения события ровно на cut-off. Cashflow до cut-off начинает участвовать в
начислении в тот же local calendar day, после cut-off — на следующий. Эти параметры не имеют
скрытых банковских defaults. Досрочное закрытие обязательно выбирает `forbid`,
`forfeit_interest` либо `reprice`; для `reprice` обязательна отдельная номинальная ставка.

План не является банковской проводкой и вычисляется чистой функцией из immutable terms,
связанных transfer cashflows, даты оценки и версии алгоритма `deposit-interest-v1`. Фактический
процент банка — отдельная immutable double-entry transaction типа `interest`, связанная с
вкладом. Reconciliation сопоставляет сумму таких postings с планом по local posting date;
коррекция добавляет новую transaction или reversal и никогда не меняет terms или прошлую
проводку. Effective yield — детерминированный Decimal XIRR плановых внешних cashflows и
projected closing value, annualized выбранной day-count convention; корень выбирается
фиксированным bisection algorithm.

**Почему:** отделение производного плана от факта не позволяет банковской корректировке
переписать ожидания, а ledger остаётся единственным источником движения денег. Полуоткрытые
интервалы устраняют двойное начисление на границах ставки и срока. Явные cut-off, day-count,
rounding, tax и early-close semantics делают одинаковый input воспроизводимым без догадок о
конкретном банке или юрисдикции.

## ADR-016: reconciled analytics без неявного FX

**Дата:** 2026-10-13.

**Решение:** аналитика этапа 07 является read model поверх immutable ledger, а не отдельным
источником финансовых фактов. Application query получает только owner-scoped posted
transactions, accounts и справочники; чистый domain calculator восстанавливает показатели из
asset-side postings. Income, expense и deposit interest входят во внешний cash flow, transfer
нейтрален, adjustment меняет net worth, но не income/expense. Reversal учитывается в дату
reversal с видом и категорией исходной операции и строго противоположным вкладом.

Каждая валюта агрегируется отдельно. Пока нет versioned FX fact с rate и source, общий total
для нескольких валют отсутствует, а contract явно сообщает `separated_by_currency`. Периоды
полуоткрытые и строятся от local midnight профиля: day, ISO-week с понедельника и calendar
month. Незакрытый период содержит только факты до query clock, помечается incomplete, а его
comparison использует тот же local elapsed cut предыдущего диапазона. Пустые buckets
материализуются нулями.

Обязательность расхода — явный справочный смысл категории в рамках текущего MVP:
`categories.is_mandatory`; income category не может быть mandatory. Этап 07 не публикует
mutation этого признака, поэтому одна и та же ledger/reference revision воспроизводит тот же
результат.
Savings равен `income - expense`; savings rate определён только при положительном income.
Mandatory share определён только при положительном total expense.

Anomaly rule version `median-mad-v1` использует шесть предыдущих завершённых buckets и требует
минимум три. Baseline — median, dispersion — median absolute deviation, threshold — максимум
из `50% * abs(baseline)` и `3 * MAD`. Ненулевое наблюдение при нулевых baseline/MAD считается
new activity. Незакрытые buckets не получают anomaly flag. Ответ возвращает observed,
baseline, deviation, threshold, rationale и IDs исходных transactions/postings.

**Почему:** эта схема сохраняет сверяемость с ledger и не создаёт ложной точности для FX.
Category flag даёт проверяемый источник обязательной доли вместо эвристики по названию.
Calendar-aligned boundaries и explicit clock устраняют зависимость от timezone хоста, а
median/MAD дают устойчивое и полностью объяснимое правило без LLM. Отдельная таблица
агрегатов пока не вводится: сначала измеряется owner/date access path на реалистичном наборе;
performance budget задаётся формой plan/query count и объёмом прочитанных rows, а не хрупким
wall-clock временем CI.

## ADR-017: immutable forecast snapshot и явный priority waterfall

**Дата:** 2026-10-14.

**Решение:** прогноз строится чистой функцией `monthly-cashflow-v1` из immutable
`ForecastInputSnapshot` и `forecast-assumptions-v1`. Snapshot фиксирует точный instant,
account balances из postings до него, будущие recurring occurrences, плановые deposit
interest entries и owner/account-scoped samples полных месяцев. Его ID — SHA-256
канонического содержимого; результат не персистится как финансовый факт и не пишет ledger.

Baseline нерегулярного расхода — account-level медиана максимум шести полных календарных
месяцев, включая явные нули. Диапазон `historical-expense-min-max-v1` заменяет медиану
наблюдаемым максимумом/минимумом расходов; это sensitivity range, не вероятностный interval.
Каждая валюта прогнозируется отдельно без FX. User rate применяется к savings accounts, а
deposit accounts продолжают использовать неизменяемый `deposit-interest-v1` schedule.

Forecast scenarios и goals — owner-scoped mutable planning records с optimistic version и
append-only audit events. Их изменение не создаёт postings. Несколько целей получают только
явную стратегию `priority-waterfall-v1`: положительный monthly net cashflow распределяется по
priority, target date и UUID. Required contribution, allocation, completion date и shortfall
возвращаются числами.

**Почему:** зафиксированный snapshot устраняет скрытую зависимость от clock/DB между повторными
расчётами. Медиана и min/max легко сверяются вручную, а waterfall позволяет объяснить каждый
выделенный рубль без непрозрачной оптимизации. Разделение planning records и ledger сохраняет
фактическую историю неизменной.

## ADR-018: provider-neutral advice как неперсистентный read/compute use case

**Дата:** 2026-10-14.

**Решение:** application-слой получает собственный `AdviceProvider` port с простыми
dataclass-контрактами сообщений, capabilities, descriptor и результата. OpenAI-compatible
adapter остаётся в infrastructure и вызывает только `/v1/chat/completions`; его HTTP/SDK-типы
не пересекают application boundary. `disabled` является полноценным provider mode и значением
по умолчанию.

`AdviceContext` версии `advice-context-v1` строится заново для каждого запроса только из
owner-scoped analytics aggregates, deterministic forecast, numeric goal plans и ограниченного
набора безопасных фактов. Account/category/goal names, email, transaction descriptions,
transaction/posting IDs и сырые строки ledger в context не входят. Необязательный текст
вопроса сериализуется как отдельное untrusted data-поле, проходит redaction и для внешнего
endpoint передаётся только при явном request-scoped consent, выключенном по умолчанию.

Prompt версии `financial-advice-v1` не даёт модели tools и требует строгий JSON contract.
Application повторно валидирует schema и отклоняет любой observation, сославшийся на evidence
ID вне переданного context. `POST /api/v1/advice` является read/compute операцией без CSRF,
idempotency record, audit mutation или записи результата; disabled, timeout, rate limit и
invalid provider response возвращаются как безопасный status внутри `200`, поэтому optional
LLM не влияет на core readiness.

Локальный vLLM запускается только Compose-профилем `local-llm`, не является dependency API и
использует pinned image/model configuration. Первичный профиль ограничен контекстом 2048,
одной sequence и non-thinking request capability. Фактическая совместимость с RTX 3050 6 ГБ
фиксируется только после отдельного smoke/VRAM/latency прогона; отсутствие Docker, OOM или
ошибка загрузки документируются как результат, а не маскируются fallback-логикой core.

**Почему:** такой разрез сохраняет финансовые вычисления детерминированными, делает утечку
сырого пользовательского текста явным opt-in и позволяет менять локальный/внешний endpoint
одной конфигурацией. Неперсистентный ответ не создаёт нового источника финансовой истины, а
graceful status сохраняет обязательную работоспособность приложения без LLM.

## ADR-019: frontend session boundary и server-derived onboarding

**Дата:** 2026-10-16.

**Решение:** React-приложение использует сгенерированный из OpenAPI fetch-client только через
небольшой browser gateway. Gateway централизует credentials, чтение double-submit CSRF cookie,
idempotency key для финансовой команды, однократный refresh истёкшего access token и перевод
безопасных `ProblemDetails` в UI-состояния. Компоненты и routes не собирают HTTP-запросы сами.

Точка onboarding не хранится отдельным mutable-флагом: успешная master session вместе с
пустым owner-scoped списком счетов означает последний шаг первого запуска; наличие хотя бы
одного счёта ведёт на dashboard. Поэтому повторное открытие, refresh и прерванный мастер
восстанавливаются из server truth. Денежный input хранит пользовательскую строку, удаляет
locale-разделители строковыми операциями и отправляет каноническую decimal-строку без
промежуточного JavaScript `number`.

Для текущего малого route graph используется History API с явными public/protected/not-found
boundaries без runtime router dependency. UI primitives принадлежат приложению, строятся на
нативной семантике (`button`, label/input, table/list, `dialog`) и не зависят от generic admin
kit. Шрифты системные и не загружаются с внешнего CDN. При росте вложенных маршрутов этапа 11
router может быть добавлен отдельным решением, не меняя session/API boundary.

**Почему:** единая session boundary исключает расхождение CSRF/refresh поведения между
экранами, а server-derived onboarding не создаёт второй источник истины. Строковый денежный
путь сохраняет точность контракта. Нативные controls уменьшают accessibility-риск и вес
локального-first приложения; отсутствие преждевременной router/UI-library зависимости
оставляет визуальное направление самостоятельным.

## ADR-020: единый server-state cache и read-after-write для финансового UI

**Дата:** 2026-10-16.

**Решение:** все финансовые экраны используют один `QueryClient` TanStack Query с ключами по
ресурсу и параметрам запроса. Компоненты не копируют server collections в локальное состояние;
локальным остаётся только незаписанное состояние форм и навигации. После подтверждённой
финансовой мутации инвалидируются зависимые queries (`transactions`, `dashboard`, `analytics`
или конкретный ресурс), и UI получает финансовую истину повторным чтением API.

Optimistic update для финансовых значений, статуса recurring rule и плановых сущностей не
используется: даже обратимая визуальная подмена могла бы кратковременно показать баланс,
доходность, прогноз или достижимость, которых сервер не подтверждал. Денежные суммы и ставки
до wire boundary остаются decimal-строками. Единственное использование JavaScript `number` в
finance workspace ограничено геометрией progress/SVG и не формирует подписи, payload или
решения. Графики всегда сопровождаются семантической таблицей с исходными строками API.

History API остаётся route boundary этапа 10: плоский набор финансовых экранов не требует
новой router abstraction. Browser gateway расширен типизированными методами существующего
generated client и по-прежнему единолично отвечает за CSRF, refresh и idempotency.

**Почему:** единый cache устраняет разное поведение загрузки/ошибок и случайные stale-копии,
а read-after-write сохраняет сервер единственным источником финансовой истины. Отказ от
optimistic financial updates важнее субъективной скорости, поскольку последствия сторно,
графики вкладов, агрегаты и goal feasibility зависят от доменных правил backend.

## ADR-021: системный E2E-контур и безопасная наблюдаемость

**Дата:** 2026-10-16.

**Решение:** семь сценариев `SPEC.md` проходят в отдельном Playwright project через
реальные browser, FastAPI и PostgreSQL. Каждый тест получает пустую БД и fixed UTC clock;
сброс разрешён только в `APP_ENV=test` и только для database name с суффиксом `_e2e`.
Ни test-only HTTP endpoint, ни производственный bypass аутентификации не добавляются. Быстрые
route-mocked UI smoke остаются отдельным слоем, но не считаются продуктовой E2E-приёмкой.

Наблюдаемость не переносит финансовые данные в новую систему. JSON-логи и Prometheus text
метрики имеют только bounded low-cardinality labels: method, status class и состояние задания.
URL/path, owner/account/transaction ID, email, body, cookie и provider payload не попадают в
labels или logs.
Readiness требует БД и job store; optional LLM публикует состояние, но не блокирует core.
Worker завершает текущий синхронный tick после SIGTERM/SIGINT и не берёт новую lease.

PostgreSQL backup и restore используют custom-format `pg_dump`/`pg_restore`. Restore всегда
идёт в отдельную предварительно пустую БД; script отказывается восстанавливать в source DB.
Факт restore доказывает CI drill: schema version, row counts, ledger balance и immutable
postings до и после restore сравниваются.

**Почему:** fixed clock и новая БД на сценарий убирают порядок тестов и wall-clock из
результата, а реальный HTTP/DB path ловит ошибки, которые невидимы в route mocks. Ограниченные
labels дают эксплуатационный сигнал без второго канала утечки. Отдельная restore DB делает
drill проверкой резервной копии, а не её наличия на диске.

## ADR-022: минимальные Alpine runtime images как security boundary

**Дата:** 2026-10-16.

**Решение:** backend и web images переходят с Debian Bookworm на официальные pinned
Alpine 3.23 variants тех же Python 3.12.12 и Node.js 24.21.0. Во время сборки применяются
доступные security updates из зафиксированной Alpine-ветки. Web runtime удаляет bundled
`npm`, `npx` и `corepack`: production server использует только `node` и стандартную библиотеку,
а package manager нужен только в builder stage. CI сканирует итоговые runtime images и
блокирует любую High/Critical vulnerability без `ignore-unfixed` или baseline-исключений.

**Почему:** актуальные официальные Bookworm и Trixie variants на дату проверки сохраняли
High/Critical findings в системных пакетах, включая находки без доступного исправления.
Alpine variants имели только исправляемые package findings; обновление packages устраняет их,
а удаление неиспользуемого npm уменьшает web runtime и исключает его dependency tree из
production attack surface. Дистрибутив builder и runtime одинаков, поэтому собранные native
wheels не пересекают glibc/musl boundary.

## ADR-023: invite-only access, SMTP outbox и production overlay

**Дата:** 2026-10-16.

**Решение:** публичная регистрация не добавляется. Первый master создаётся существующим
одноразовым bootstrap, но в production запрос обязан совпасть с заранее настроенным
`BOOTSTRAP_MASTER_EMAIL`. Последующие пользователи создаются только атомарным принятием
неотозванного invitation для активной allowlist-записи. Master и явно назначенный им admin
могут управлять allowlist и приглашениями; выдавать admin-доступ может только master.
Отзыв allowlist является soft-revoke: учётная запись блокируется, сессии и неиспользованные
ссылки отзываются, но пользователь, audit trail и финансовые строки не удаляются.

Invitation, verification и password-reset письма доставляются отдельным durable SMTP outbox.
API сохраняет хеш одноразового токена и delivery job в одной транзакции; raw URL существует в
ограниченном payload outbox до доставки либо terminal/expired/revoked state и затем очищается. Worker арендует jobs
через `FOR UPDATE SKIP LOCKED`, повторяет временные SMTP ошибки с bounded backoff и переводит
исчерпанные задания в dead letter. Логи и audit никогда не содержат email, URL или raw token.
Запрос восстановления пароля всегда отвечает одинаковым `202`, независимо от существования
аккаунта. TTL: invitation 2 часа, verification 30 минут, reset 15 минут; replay отклоняется и,
когда token id существует, добавляет audit event.

Compose получает явные профили `core`, `mail-catcher` и `local-llm`. Production overlay
сбрасывает host ports и build instructions, использует versioned application images, pinned
upstream images, resource limits, restart policies и те же healthchecks. TLS завершается только
на выбранном оператором reverse proxy; приложение доверяет forwarded headers лишь от явно
перечисленных proxy IP/CIDR. Production startup требует HTTPS public URL/origins, Secure cookie,
bootstrap email, SMTP TLS и непредсказуемые независимые secrets. Автоматический ACME flow не
включается до выбора домена и хоста.

**Почему:** отдельный email outbox не смешивает identity delivery с финансовым recurring
outbox, но сохраняет атомарность выдачи ссылки и постановки письма. Soft-revoke выполняет
invite-only policy без нарушения неизменяемой финансовой истории. Overlay позволяет одним и
тем же исходникам обслуживать локальный rehearsal и server deployment, не публикуя database/API
ports и не притворяясь владельцем DNS/TLS инфраструктуры.

**Уточнение rehearsal 2026-10-17:** в пустом HF cache встроенный `hf_transfer` завершился
`Failed too many failures in parallel / no permits available`. Для воспроизводимого local-LLM
используется обычный HTTPS downloader: `HF_HUB_ENABLE_HF_TRANSFER=0` вместе с отключённым Xet;
TLS verification сохраняется. Наблюдавшаяся официальная snapshot revision Qwen3-4B-AWQ
`74d4bd2bd4bff9cafc9345221320bffb08b406a3` закрепляется отдельно от image digest, чтобы обновление
upstream `main` не меняло веса релиза. Это исправление release profile, не смена модели/engine.
## ADR-024: пользовательские вклады отделены от счетов, а удаление сохраняет историю

**Решение:** с этапа 14 пользователь создаёт обычные счета только для денег без процентов
(наличные, банковский счёт/карта и иной актив), а вклад создаёт как отдельный объект с названием,
начальной суммой и условиями. Для double-entry ledger вклад по-прежнему получает внутренний
`deposit` account, но API создаёт его атомарно и UI нигде не предлагает создать или выбрать его
как обычный счёт. Единый журнал принимает счета и вклады как источники/получатели операций;
денежные потоки вклада восстанавливаются по posting его внутреннего account.

Редактирование условий вклада выполняется optimistic update с полным before/after snapshot в
append-only audit. Счета, вклады и цели «удаляются» архивированием. Проведённая операция остаётся
неизменяемой: пользовательское удаление создаёт reversal, а исправление атомарно создаёт reversal
и заменяющую проводку. Поэтому интерфейс даёт ожидаемые действия, но баланс, аналитика и аудит
остаются воспроизводимыми.

Основной экран вклада показывает расчётный баланс, начисленный доход, сумму к погашению и график.
Отдельная форма «факт» убирается: пополнение, снятие, доход и расход вводятся в общем журнале.
Сверка план/факт остаётся доступной в API для банковского начисления процентов, но не дублирует
основной пользовательский сценарий.

**Почему:** пользовательская сущность «вклад» имеет собственные условия и жизненный цикл, поэтому
предварительное создание счёта раскрывает техническую модель и приводит к нулевому графику без
неочевидного дополнительного cashflow. Архивирование и reversal согласуют базовые CRUD-ожидания с
обязательным append-only следом финансовых изменений.

**Дополнение 2026-10-19:** проценты завершённых периодов проводятся автоматически worker и
при изменении principal/условий. Owner/deposit lock защищает сверку expected-minus-posted;
повтор не создаёт дубль, пересчёт добавляет signed correction. Старые договоры сохраняют
ручной режим до проверки пользователем: прежняя модель разрешала несколько договоров на одном
account. Автоматически начислять каждый из них означало бы многократно увеличить капитал.
Включение автоматического режима запрещено до архивирования legacy-дублей. Архивирование
одного дубля не закрывает общий account другого активного договора.

Операция с выбранной датой «сегодня» получает текущее время в явном profile timezone;
прошлая/будущая дата — локальный полдень. Это устраняет будущие проводки при утреннем вводе.
