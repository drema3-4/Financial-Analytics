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

