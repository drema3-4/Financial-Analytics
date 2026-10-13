# API contract through milestone 03

Этап 03 добавляет identity endpoints; финансовый HTTP CRUD остаётся этапом 04. FastAPI
публикует актуальную OpenAPI-схему по `/openapi.json` и интерактивную документацию по `/docs`.

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

## Request tracing

- Клиент может передать `X-Request-ID` и `X-Correlation-ID` длиной до 128 символов из букв,
  цифр, `.`, `_` и `-`.
- Небезопасные или отсутствующие ID заменяются серверным UUID.
- Оба значения возвращаются в response headers и включаются в problem details.
- Логи API имеют JSON-формат и получают эти ID из request context; настройки и database URL
  в них не сериализуются.
