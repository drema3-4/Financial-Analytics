# Этап 08 — Прогнозы, сценарии и цели

## Цель

Дать пользователю детерминированный прогноз на произвольную дату и числовой план достижения целей.

## Выполни

- Реализуй immutable `ForecastInputSnapshot`, versioned assumptions и чистый monthly timeline engine.
- Базовый сценарий учитывает текущие остатки, recurring occurrences, deposit schedules и прозрачную baseline-оценку нерегулярных трат из полных исторических периодов.
- Реализуй user scenarios: изменение дохода/расходов, инфляции, ставки, разовых cashflows и горизонта. Сценарий не пишет в фактический ledger.
- Возвращай помесячный ряд, итог по счетам/капиталу, assumptions, предупреждения о недостаточных данных и диапазон неопределённости с объяснимым методом.
- Реализуй goals: target amount/date, saved amount, priority, linked account, required monthly contribution, expected completion date и shortfall.
- Для нескольких целей реализуй явную priority allocation strategy и compare scenarios; никакой оптимизации «чёрным ящиком».
- Добавь golden/property tests: zero activity, only recurrence, deposit maturity, missed target, already achieved, impossible contribution, inflation, same snapshot reproducibility.
- Документируй формулы и ограничения как финансовый прогноз, не гарантию.

## Приёмка

- Один snapshot + версия алгоритма всегда дают один результат.
- Изменение сценария не меняет историю и другие сценарии.
- Goal result содержит проверяемые числа, а не только текстовый совет.
- Обновлён `STATUS.md`; создан commit `feat(08): forecast finances and plan goals`.

