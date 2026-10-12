# Этап 04 — Accounts, categories и ledger API

## Цель

Дать законченное API для ежедневного финансового учёта поверх проверенного domain core.

## Выполни

- Реализуй REST endpoints `/api/v1` для счетов, групп/категорий, операций, переводов, корректировок, фильтров, cursor pagination и CSV export.
- Начальный остаток создавай проводкой. Закрытие/архивация счёта не удаляет историю.
- Для команд создания и reversal поддержи `Idempotency-Key` с тем же результатом при безопасном повторе и конфликтом при другом payload.
- Зафиксируй Pydantic request/response contracts, problem details errors и OpenAPI examples.
- Не принимай float для сумм; JSON monetary amount — decimal string плюс currency.
- Добавь generated TypeScript client из зафиксированного OpenAPI и CI drift-check, но не строй UI.
- Добавь integration/contract tests на concurrent requests, duplicate key, cross-owner access, category grouping, pagination stability и CSV escaping/encoding.
- Документируй API usage и примеры curl без реальных секретов.

## Приёмка

- Доход, расход и перевод дают ожидаемые posting и баланс.
- Повтор идентичной команды не удваивает деньги.
- Проведённые операции нельзя физически удалить через API.
- OpenAPI snapshot и generated client воспроизводимы.
- Обновлён `STATUS.md`; создан commit `feat(04): expose idempotent ledger API`.

