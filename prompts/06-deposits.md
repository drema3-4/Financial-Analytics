# Этап 06 — Вклады и сложные проценты

## Цель

Добавить воспроизводимый расчёт вкладов с пополнениями, снятиями и капитализацией.

## Выполни

- Реализуй `DepositTerms`: principal account, currency, open/maturity dates, nominal rates/periods, capitalization frequency, day-count convention, rounding, early-close rule и явный tax parameter.
- Отдели плановый interest schedule от фактических posting банка. Пополнение/снятие — обычные ledger cashflows со ссылкой на вклад.
- Interest engine сделай чистой функцией; поддержи изменение ставки по периодам и граничные даты.
- Верни API schedule/current value/accrued interest/projected maturity value/effective yield и reconciliation факта с планом.
- Создай независимые табличные fixtures с ручным/формульным расчётом для monthly/daily capitalization, пополнения перед/после cut-off, частичного снятия, leap year, rounding и early close.
- Используй Decimal на всём пути. Любая неоднозначная банковская конвенция должна быть обязательным параметром, не скрытым default.
- Добавь property/integration/contract tests и документацию формул.

## Приёмка

- Эталонные примеры совпадают до заявленного правила округления.
- Одинаковый input и версия алгоритма дают одинаковый schedule.
- Фактическая корректировка банка не переписывает исходный план и аудируется.
- Обновлён `STATUS.md`; создан commit `feat(06): model deposits and compound interest`.

