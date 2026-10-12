# Этап 11 — Полный финансовый интерфейс

## Цель

Закрыть все пользовательские финансовые сценарии существующего API без дублирования бизнес-логики в браузере.

## Выполни

- Реализуй dashboard с net worth, cash flow, ближайшими обязательствами, прогрессом целей и явной свежестью данных.
- Реализуй accounts и transaction journal: создание income/expense/transfer, категории/группы, filters, search, pagination, CSV export, correction/reversal с подтверждением последствий.
- Реализуй recurring rules и preview occurrences, pause/resume, политику последнего дня месяца и понятное отображение timezone.
- Реализуй deposits: terms form, rate periods, cashflows, schedule, planned-vs-actual и yield explanation.
- Реализуй analytics charts/tables с доступной табличной альтернативой, comparison и currency warnings.
- Реализуй forecast scenario editor, timeline, assumptions, uncertainty и compare; goals с required contribution/shortfall/priority strategies.
- Реализуй advice view с evidence links, privacy consent, provider status, confidence/disclaimer. Не показывай совет как команду или гарантию.
- Используй server state library последовательно; optimistic updates допускаются только там, где rollback безопасен. Не пересчитывай финансовую истину на frontend.
- Добавь component/integration tests и Playwright happy/negative flows для каждого модуля.

## Приёмка

- Все сценарии из `SPEC.md` доступны через UI и корректно показывают ошибки API.
- Числа/валюты/даты форматируются по профилю, сохраняя точность wire contract.
- Charts не являются единственным способом получить информацию.
- Responsive, keyboard и screen-reader smoke checks проходят.
- Обновлён `STATUS.md`; создан commit `feat(11): deliver complete financial workflows`.

