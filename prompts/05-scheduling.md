# Этап 05 — Worker и регулярные операции

## Цель

Надёжно создавать запланированные операции ровно один раз, включая рестарты и конкурирующие worker.

## Выполни

- Реализуй PostgreSQL-backed jobs/outbox с lease, attempts, exponential backoff, dead-letter state, dedup key и `FOR UPDATE SKIP LOCKED`.
- Реализуй recurring rules для income/expense/transfer: daily, weekly, monthly, yearly, pause/resume, end date, next occurrence.
- Явно поддержи политику несуществующего дня месяца (`last_day`/`skip`) и DST в timezone пользователя; сохраняй occurrence instant в UTC.
- Worker вызывает тот же application use case, что и API, с детерминированным idempotency key `(rule_id, occurrence_at)`.
- Добавь endpoint preview будущих occurrences без записи ledger и endpoints управления правилами.
- Сделай clock инъецируемым; тесты не должны ждать реального времени.
- Напиши tests на crash-after-commit, double delivery, два worker, missed runs/catch-up policy, leap year, DST и изменение правила после созданных операций.
- Добавь runbook мониторинга и ручного безопасного retry.

## Приёмка

- Любое количество повторов одного occurrence создаёт не более одной финансовой транзакции.
- Уже созданные операции не меняются при редактировании правила.
- Dead-letter виден оператору, а retry аудируется.
- Обновлён `STATUS.md`; создан commit `feat(05): process recurring operations reliably`.

