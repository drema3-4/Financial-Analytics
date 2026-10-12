# Bootstrap API contract

Контракт этапа 01 не содержит финансовых ресурсов. FastAPI публикует актуальную OpenAPI-схему
по `/openapi.json` и интерактивную документацию по `/docs`.

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
