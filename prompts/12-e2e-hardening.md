# Этап 12 — E2E, безопасность и эксплуатационная устойчивость

## Цель

Доказать поведение продукта как системы и закрыть высокорисковые пробелы до развёртывания.

## Выполни

- Преврати семь сценариев `SPEC.md` в независимые Playwright E2E tests с детерминированными fixtures/clock и диагностическими artifacts только при failure.
- Создай end-to-end reconciliation: UI action → API → ledger postings → analytics/forecast expected result.
- Проведи threat-model-driven tests: IDOR/cross-tenant, brute force/rate limits, CSRF/CORS, session fixation/replay, injection, malicious CSV cells, upload/export headers, log and LLM redaction.
- Добавь dependency/container vulnerability scan, secret scan, SBOM и license report в CI с обоснованной failure policy.
- Добавь structured logs, metrics и health/readiness для API/worker/jobs/provider; корреляция запроса не раскрывает данные.
- Реализуй PostgreSQL backup и restore scripts. Выполни restore drill в отдельную test database и документируй RPO/RTO assumptions.
- Проверь graceful shutdown, in-flight job lease recovery, migration against realistic copy, unavailable SMTP/LLM и disk/DB errors.
- Измерь ключевые flows на реалистичном объёме данных и устрани только подтверждённые bottlenecks.

## Приёмка

- Семь E2E-сценариев зелёные в чистом окружении.
- Нет открытых critical/high findings либо каждое исключение документировано и явно принято человеком.
- Backup restore доказан фактом, а не только наличием скрипта.
- Worker и API безопасно восстанавливаются после прерывания.
- Обновлён `STATUS.md`; создан commit `test(12): harden end-to-end product behavior`.

