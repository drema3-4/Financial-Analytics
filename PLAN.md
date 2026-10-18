# План разработки

Каждый этап выполняется соответствующим файлом из `prompts/`, заканчивается зелёными проверками, обновлением `STATUS.md` и отдельным коммитом. Этапы 00–02 образуют архитектурный gate; после них рекомендуется человеческая проверка до массовой генерации.

| № | Этап | Основной результат | Gate |
|---:|---|---|---|
| 00 | Preflight | проверенная среда, версии, baseline и решения без домыслов | команды окружения воспроизводимы |
| 01 | Bootstrap | monorepo, quality tooling, core Compose и CI | lint/typecheck/test/build проходят |
| 02 | Domain & DB | доменная модель, ledger, миграции и тесты инвариантов | архитектурная проверка |
| 03 | Identity | мастер, login/session, allowlist foundation и tenant isolation | security matrix зелёная |
| 04 | Ledger API | счета, категории, операции, reversals, поиск/экспорт | баланс и идемпотентность доказаны |
| 05 | Scheduling | durable worker и регулярные операции | повтор worker не дублирует проводки |
| 06 | Deposits | условия, cashflows, капитализация и доходность | эталонные таблицы совпадают |
| 07 | Analytics | отчёты и comparison API | агрегаты сходятся с ledger |
| 08 | Forecast & Goals | сценарии, прогноз, цели и стратегии | воспроизводимость и крайние случаи |
| 09 | LLM Advice | provider port, privacy, structured advice и local vLLM profile | core без LLM + fake provider tests |
| 10 | Frontend Foundation | дизайн-система, shell, onboarding, auth и API client | responsive/a11y baseline |
| 11 | Finance UI | операции, расписания, вклады, отчёты, прогнозы, цели, советы | ключевые UI flows работают |
| 12 | E2E & Hardening | E2E, security, observability, backup/restore | семь сценариев зелёные |
| 13 | Deployment | локальный и server profiles, SMTP, TLS docs, release | fresh-machine rehearsal |
| 14 | Core finance workflow correction | отдельные счета/вклады, редактирование и безопасное удаление, единые операции, inline-категории и рабочая аналитика | реальные CRUD/transfer/interest сценарии проходят в браузере |

## Правила изменения плана

- Новая функция сначала сопоставляется с `SPEC.md`; вне MVP — в backlog, не в текущий diff.
- Если этап становится слишком большим для одной проверяемой итерации, его можно разделить, сохранив порядок зависимостей и один commit на подэтап.
- Версии библиотек выбираются на этапе 00/01 по текущей официальной совместимости и фиксируются lockfiles; документы не притворяются вечным реестром latest-версий.
- Реализация следующего этапа не должна маскировать незакрытый gate предыдущего.

