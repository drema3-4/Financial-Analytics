# Этап 02 — Domain model и база данных

## Цель

Заложить финансово корректное ядро и миграции до появления HTTP CRUD.

## Выполни

- Реализуй value objects `Money`, `Currency`, `Rate`, rounding policy, date range и timezone-aware instant. Запрети float на границах.
- Реализуй чистую доменную модель accounts/transactions/postings/categories и правила balanced transaction, transfer, income, expense, reversal.
- Спроектируй SQLAlchemy models и repositories для минимальных таблиц Identity shell, Finance и Control из архитектуры; таблицы пользователя имеют `owner_id`.
- Добавь audit event, idempotency record и optimistic version там, где они нужны для мутаций.
- Создай Alembic migrations с constraints/indexes/FKs. Используй PostgreSQL `NUMERIC` с документированным scale; не храни деньги только как UI-баланс.
- Добавь service/use-case ports и PostgreSQL adapters так, чтобы domain не импортировал FastAPI/SQLAlchemy.
- Напиши unit, property-based и integration tests: balanced postings, currency mismatch, rounding, reversal, rebuild balance, transaction rollback, owner scoping.
- Создай `docs/DATA_MODEL.md` с ER diagram, инвариантами и примерами проводок.

## Gate для человека

После реализации остановись. Покажи схему, спорные решения и доказательства тестами. Не начинай Identity до явного продолжения.

## Приёмка

- Невозможно сохранить несбалансированную проведённую транзакцию.
- Исправление сохраняет исходную запись и причинную связь.
- Баланс полностью перестраивается из posting.
- Repository API не позволяет забыть owner scope; cross-owner integration tests краснеют при снятии фильтра.
- Миграции применяются на чистой БД; downgrade проверен там, где он не разрушает данные.
- Обновлён `STATUS.md`; создан commit `feat(02): establish audited financial domain`.

