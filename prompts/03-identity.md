# Этап 03 — Identity, мастер-доступ и изоляция

## Цель

Реализовать безопасный локальный вход и фундамент будущего invite-only сервера.

## Выполни

- Реализуй одноразовый bootstrap мастер-пользователя с email, хэшированным Argon2id паролем, базовой валютой, locale и timezone. После создания мастер-bootstrap закрывается.
- Реализуй login, refresh rotation, logout текущей и всех сессий, профиль текущего пользователя. Refresh secrets хранятся только в хэшированном виде.
- Выбери безопасную browser session схему согласно архитектуре: HttpOnly/Secure/SameSite cookies, CSRF для мутаций и строгий CORS.
- Добавь rate limiting интерфейс и рабочую локальную реализацию для login/token endpoints.
- Создай allowlist/invitation/email-token модели и use cases, но UI приглашений и реальную отправку писем оставь этапу 13. Токены одноразовые, TTL и replay tests обязательны.
- Добавь audit events без паролей, сырых токенов и лишних финансовых данных.
- Напиши security matrix tests: anonymous/authenticated, owner/other owner, expired/replayed/revoked session, CSRF, disabled user.
- Документируй threat model и процедуры смены секретов в `docs/SECURITY.md`.

## Приёмка

- Два тестовых пользователя не могут читать/менять объекты друг друга ни по угадываемому ID, ни через фильтры.
- Пароль/refresh/email tokens никогда не сохраняются и не логируются открытым текстом.
- Повтор bootstrap и replay токена отклоняются.
- Core login работает без SMTP и LLM.
- Обновлён `STATUS.md`; создан commit `feat(03): secure identity and tenant isolation`.

