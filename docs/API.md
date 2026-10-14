# API contract through milestone 08

FastAPI публикует актуальную OpenAPI-схему по `/openapi.json` и интерактивную документацию
по `/docs`. Зафиксированный snapshot находится в `docs/openapi.json`; из него
детерминированно строится TypeScript fetch-client в
`packages/frontend/api/src/generated/client.ts`.

## Identity

| Method | Path | Authentication | Result |
|---|---|---|---|
| `POST` | `/api/v1/auth/bootstrap` | только до первого master | profile + session cookies, `201` |
| `POST` | `/api/v1/auth/login` | email/password, rate limited | profile + session cookies |
| `POST` | `/api/v1/auth/refresh` | refresh cookie + CSRF, rate limited | rotated cookies + profile |
| `POST` | `/api/v1/auth/logout` | access cookie + CSRF | revoke current, `204` |
| `POST` | `/api/v1/auth/logout-all` | access cookie + CSRF | revoke all owner sessions, `204` |
| `GET` | `/api/v1/profile` | access cookie | current owner profile |

Bootstrap/login принимают JSON и никогда не возвращают token в body. Access `fa_access` и
refresh `fa_refresh` имеют `HttpOnly; Secure; SameSite=Strict`; `fa_csrf` имеет
`Secure; SameSite=Strict` и передаётся обратно заголовком `X-CSRF-Token` для mutation.
Имена cookie конфигурируемы. Публичный profile содержит `id`, нормализованный `email`,
`base_currency`, `locale`, `timezone`, `status`, `is_master`, `created_at`.

Expected security errors: `bootstrap_closed` (`409`), `invalid_credentials`/`invalid_session`
(`401`), `csrf_validation_failed`/`user_disabled` (`403`) и `rate_limit_exceeded` (`429` с
`Retry-After`). Ответ не различает неизвестный email и неверный пароль.

Allowlist, invitation и email-token use cases существуют на application boundary, но намеренно
не публикуются HTTP/UI до этапа 13 и не требуют SMTP.

## Ledger API

Все пути имеют prefix `/api/v1`, требуют access cookie, а mutations дополнительно требуют
`X-CSRF-Token`. Каждая create/reversal command требует caller-generated `Idempotency-Key`
длиной 1–200 ASCII-символов. Повтор с тем же key и тем же JSON возвращает тот же resource и
не создаёт новую проводку; тот же key с другим payload возвращает `409 idempotency_conflict`.

| Method | Path | Result |
|---|---|---|
| `POST`, `GET` | `/accounts` | создать/list accounts; optional opening balance — adjustment posting |
| `GET`, `PATCH` | `/accounts/{id}` | account с rebuilt balance; rename/archive по optimistic `version` |
| `POST`, `GET` | `/category-groups` | древовидные группы; list включает принадлежащие группе categories |
| `POST`, `GET` | `/categories` | income/expense categories |
| `POST`, `GET` | `/tags` | transaction tags |
| `POST` | `/transactions/income` | income с asset/system-income postings |
| `POST` | `/transactions/expense` | expense с asset/system-expense postings |
| `POST` | `/transfers` | same-currency transfer между asset accounts |
| `POST` | `/adjustments` | signed manual reconciliation через system-equity account |
| `POST` | `/transactions/{id}/reversal` | полная противоположная проводка со ссылками на original |
| `GET` | `/transactions`, `/transactions/{id}` | journal/detail; posted transaction не имеет DELETE API |
| `GET` | `/transactions/export.csv` | filtered UTF-8 CSV с BOM и CRLF |

`GET /transactions` принимает `account_id`, `category_id`, `tag_id`, `kind`, полуоткрытый
интервал `occurred_from <= occurred_at < occurred_to`, substring `search`, `limit` 1–100 и
opaque `cursor`. Порядок — `(occurred_at DESC, id DESC)`; `next_cursor` остаётся стабильным,
если перед чтением следующей страницы появились более новые операции. CSV принимает те же
filters без cursor/limit. Поля с запятыми, кавычками и переводами строк экранируются RFC 4180;
ячейки, начинающиеся как spreadsheet formula, получают безопасный apostrophe prefix.

Сумма в JSON всегда объект с decimal string и currency:

```json
{"amount": "1250.00", "currency": "RUB"}
```

JSON number, включая `1250.0`, отклоняется с `422 validation_error`. Сервер не выполняет
неявное округление и проверяет minor units валюты. Межвалютный transfer возвращает domain
validation error; скрытого FX нет.

## Recurring rules

Все пути требуют access cookie; mutations также требуют `X-CSRF-Token`.

| Method | Path | Result |
|---|---|---|
| `POST`, `GET` | `/recurring-rules` | создать/list owner-scoped rules |
| `GET`, `PUT` | `/recurring-rules/{id}` | получить или полностью обновить rule по `version` |
| `POST` | `/recurring-rules/{id}/pause` | приостановить, сохранив next occurrence |
| `POST` | `/recurring-rules/{id}/resume` | возобновить с выбранной catch-up policy |
| `POST` | `/recurring-rules/preview` | вычислить 1–100 будущих UTC/local occurrences без записи rule или ledger |
| `GET` | `/recurring-jobs/dead-letter` | owner-scoped jobs после исчерпания attempts |
| `POST` | `/recurring-jobs/{id}/retry` | аудируемый безопасный retry dead-letter job |

Операция rule имеет kind `income`, `expense` или `transfer`, exact decimal `money`, ссылки на
account/category/destination, description и tags. Расписание задаётся local `starts_on` +
`local_time`, IANA `timezone`, frequency `daily|weekly|monthly|yearly`, optional inclusive
`end_date`, `missing_day_policy=last_day|skip` и `catch_up_policy=all|latest`.

`next_occurrence_at` и preview `occurrence_at` всегда UTC instants. `local_at` показывает
соответствующий offset пользователя. На DST gap local time сдвигается вперёд на размер gap;
при повторённом времени выбирается первый instant. `all` догоняет каждый пропуск, `latest`
создаёт только последний due occurrence. Уже материализованный job хранит snapshot, поэтому
редактирование rule действует только на ещё не материализованные события.

Preview является чистым query: он не создаёт rule, outbox job, transaction или audit event.
Ручной retry описан в [SCHEDULING_RUNBOOK.md](SCHEDULING_RUNBOOK.md).

## Deposits

Все create/posting команды требуют `Idempotency-Key`, access cookie и CSRF. Все reads и FK
owner-scoped; чужой UUID неотличим от отсутствующего (`404`).

| Method | Path | Result |
|---|---|---|
| `POST`, `GET` | `/deposits` | создать immutable terms или получить owner list |
| `GET` | `/deposits/{id}` | получить terms и версию алгоритма |
| `POST` | `/deposits/{id}/cashflows` | linked same-currency transfer: signed пополнение/снятие |
| `POST` | `/deposits/{id}/interest-postings` | immutable фактический signed interest posting |
| `GET` | `/deposits/{id}/valuation?as_of=...&close_on=...` | schedule, current/accrued/projected values, effective yield и reconciliation |

Rates и money принимаются только decimal strings. Create требует явные capitalization,
day-count, rounding mode/frequency, timezone/cut-off/equality rule, early-close rule и tax
rate; банковских defaults нет. `as_of` обязателен и означает начало local calendar date.
`close_on` optional и активирует явно заданную early-close policy.

Schedule — расчётный план и не создаёт postings. Cashflow остаётся transaction `transfer` с
`deposit_id`; банковский процент — отдельная transaction `interest`. Исправление выполняется
reversal/новой posting, поэтому reconciliation меняется, но план и terms не переписываются.
Полная семантика и формулы — в [DEPOSIT_CALCULATIONS.md](DEPOSIT_CALCULATIONS.md).

## Analytics and reports

Оба read endpoint требуют access cookie и используют timezone текущего profile. Money и rates
возвращаются decimal strings; бинарных JSON numbers для финансовых значений нет.

| Method | Path | Result |
|---|---|---|
| `GET` | `/analytics/dashboard` | totals, net worth, savings/mandatory rates, comparison и anomalies |
| `GET` | `/reports/financial` | dashboard metrics плюс series и category/group breakdown |

Параметры: `period_start`, `period_end` как local dates и
`granularity=day|week|month`. Для dashboard обе даты optional вместе: без них возвращается
текущий local bucket. Detailed report требует обе даты. Неделя начинается в понедельник,
месяц — первого числа; невыровненные границы и диапазон дальше текущего bucket получают `422`.

`currency_mode=separated_by_currency` и `combined_currency=null` гарантируют отсутствие
скрытой суммы разных валют. Каждый metric имеет formula/evidence; detailed breakdown содержит
`flow_type`, поэтому его строки сверяются с income/expense отдельно. Точные формулы, reversal,
open-period comparison и anomaly thresholds описаны в [ANALYTICS.md](ANALYTICS.md).

## Forecast scenarios and goals

Все planning records owner-scoped. Create требует access cookie, CSRF и `Idempotency-Key`;
update требует access cookie, CSRF и optimistic `version`. Чужой UUID неотличим от
отсутствующего (`404`). Ни один путь прогноза не создаёт ledger transaction/posting.

| Method | Path | Result |
|---|---|---|
| `POST`, `GET` | `/forecast-scenarios` | создать/list versioned scenario assumptions |
| `GET`, `PUT` | `/forecast-scenarios/{id}` | получить/полностью обновить scenario |
| `POST`, `GET` | `/goals` | создать/list numeric financial goals |
| `GET`, `PUT` | `/goals/{id}` | получить/полностью обновить goal |
| `GET` | `/forecasts?currency=...&through=...` | baseline forecast и планы целей |
| `GET` | `/forecasts?currency=...&scenario_id=...` | forecast по сохранённому scenario horizon |
| `POST` | `/forecasts/compare` | baseline и до 20 scenarios из одного snapshot |

Scenario задаёт decimal-string rates в объектах `RateInput`, horizon и до 100 one-time
cashflows. One-time account обязан принадлежать owner и иметь валюту scenario. Goal содержит
target/saved `Money`, target date, priority и optional linked account той же owner/currency.

Forecast возвращает `snapshot_id`, версии algorithm/assumptions, account totals, monthly
timeline, baseline samples, warnings и lower/upper sensitivity range с именем и объяснением
метода. В том же ответе goal plan содержит required monthly contribution, average available,
contribution gap, allocated amount, expected completion date и shortfall. Все money/rate
values остаются decimal strings. Формулы и ограничения описаны в
[FORECASTS_AND_GOALS.md](FORECASTS_AND_GOALS.md); ответ содержит явный disclaimer, что прогноз
не является гарантией.

### Пример account с opening balance

Ниже используются placeholder cookie jar и CSRF token; это не реальные секреты:

```bash
curl --request POST 'https://localhost:8000/api/v1/accounts' \
  --cookie cookies.txt \
  --header 'Content-Type: application/json' \
  --header 'X-CSRF-Token: <csrf-token-from-cookie>' \
  --header 'Idempotency-Key: account-20261013-001' \
  --data '{
    "name": "Основная карта",
    "kind": "bank",
    "currency": "RUB",
    "opening_balance": {"amount": "15000.00", "currency": "RUB"},
    "opening_balance_occurred_at": "2026-10-13T09:00:00+04:00"
  }'
```

### Пример expense и следующей страницы

```bash
curl --request POST 'https://localhost:8000/api/v1/transactions/expense' \
  --cookie cookies.txt \
  --header 'Content-Type: application/json' \
  --header 'X-CSRF-Token: <csrf-token-from-cookie>' \
  --header 'Idempotency-Key: expense-20261013-001' \
  --data '{
    "account_id": "018f0000-0000-7000-8000-000000000001",
    "category_id": "018f0000-0000-7000-8000-000000000002",
    "money": {"amount": "1250.00", "currency": "RUB"},
    "occurred_at": "2026-10-13T10:15:00+04:00",
    "description": "Продукты",
    "source": "manual",
    "tag_ids": []
  }'

curl --get 'https://localhost:8000/api/v1/transactions' \
  --cookie cookies.txt \
  --data-urlencode 'limit=50' \
  --data-urlencode 'cursor=<next_cursor-from-previous-response>'
```

Для обновления generated artifacts:

```text
poetry run python scripts/generate_api_client.py
poetry run python scripts/generate_api_client.py --check
```

## Health

`GET /health/live` проверяет только работающий HTTP process:

```json
{"status": "alive"}
```

`GET /health/ready` выполняет реальный PostgreSQL `SELECT 1`. Успешный ответ:

```json
{"status": "ready", "checks": {"database": "up"}}
```

LLM не является обязательной зависимостью readiness.

## Ошибки

Ошибки возвращаются с media type `application/problem+json` и единой формой:

```json
{
  "type": "urn:financial-analytics:error:dependency_unavailable",
  "title": "Service unavailable",
  "status": 503,
  "detail": "A required service dependency is unavailable.",
  "code": "dependency_unavailable",
  "instance": "/health/ready",
  "request_id": "7c8eb85b-3c07-4fbf-8508-6bad61f17827",
  "correlation_id": "7c8eb85b-3c07-4fbf-8508-6bad61f17827"
}
```

Validation errors дополнительно содержат `errors`; необработанные исключения не раскрывают
внутреннее сообщение клиенту.

Ledger-specific errors: `resource_not_found` (`404`, одинаково для отсутствующего и чужого
resource), `idempotency_conflict`/`resource_conflict` (`409`), `invalid_cursor`,
`invalid_date_range` и `domain_validation_error` (`422`).

## Request tracing

- Клиент может передать `X-Request-ID` и `X-Correlation-ID` длиной до 128 символов из букв,
  цифр, `.`, `_` и `-`.
- Небезопасные или отсутствующие ID заменяются серверным UUID.
- Оба значения возвращаются в response headers и включаются в problem details.
- Логи API имеют JSON-формат и получают эти ID из request context; настройки и database URL
  в них не сериализуются.
