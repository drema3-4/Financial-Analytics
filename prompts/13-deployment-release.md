# Этап 13 — Invite-only сервер и релиз

## Цель

Сделать воспроизводимый локальный релиз и безопасный путь развёртывания в вебе с email-доступом.

## Выполни

- Заверши Compose profiles: core, mail-catcher и local-llm; добавь production overlay без dev mounts/ports и с pinned images, resource limits, restart policies, healthchecks.
- Реализуй SMTP adapter и jobs для invitation, email verification и password reset. Письма не раскрывают наличие чужого аккаунта; ссылки имеют одноразовый короткий TTL.
- Реализуй UI/API управления allowlist/invitations только для master/admin и bootstrap первой мастер-почты. Удаление из allowlist не должно бесследно уничтожать финансовые данные.
- Документируй reverse proxy/TLS, trusted headers, cookie domain, allowed origins, secret rotation, database migration, backup schedule, restore и rollback. Не изобретай автоматическую выдачу сертификата без выбранного домена/хоста.
- Добавь production configuration validation: слабые/default secrets, debug, wildcard CORS и insecure cookies должны блокировать production startup.
- Проведи fresh-machine rehearsal из чистого clone: local core без GPU, local-llm при доступном GPU и production-like smoke. Зафиксируй точные команды и фактические результаты.
- Создай release checklist, changelog, semantic version/tag proposal и user/admin runbook. Не push/tag/deploy во внешнюю среду без явного разрешения.

## Приёмка

- Локальный core поднимается без LLM; local-llm включается одним profile и может быть выключен без миграций.
- Публичная конфигурация требует HTTPS assumptions и не стартует с известными небезопасными default.
- Только master/admin может разрешать новые email; invitation/token replay отклоняется и аудируется.
- Fresh-machine walkthrough покрывает onboarding → операцию → прогноз → цель → необязательный совет.
- `STATUS.md` показывает полный Definition of Done и честный список остаточных ограничений; создан commit `release(13): prepare invite-only deployment`.

