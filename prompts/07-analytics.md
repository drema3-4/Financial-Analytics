# Этап 07 — Аналитика и отчёты

## Цель

Построить объяснимые агрегаты, которые полностью сходятся с ledger и станут входом для прогнозов и советов.

## Выполни

- Реализуй application queries для cash flow, income/expense, category/group breakdown, net worth, обязательной доли расходов, savings rate и сравнения периодов.
- Определи поведение переводов, reversals, незакрытого текущего периода, пустых периодов и нескольких валют. Не суммируй разные валюты без явного зафиксированного FX rate/source.
- Добавь deterministic anomaly flags на основе прозрачных порогов/статистики и возвращай rationale, baseline и величину отклонения.
- Реализуй period granularity day/week/month и timezone-correct boundaries.
- Добавь API для dashboard и detailed reports с стабильными response contracts; оптимизируй запросы только после измерения.
- Проверь plans индексов на реалистичном synthetic dataset; добавь performance budget, не зависящий от сверхточного времени CI.
- Напиши reconciliation tests: сумма breakdown равна total, transfers нейтральны для income/expense, reversal компенсирует исходное, tenant scope не нарушается.

## Приёмка

- Любой показатель можно объяснить формулой и набором исходных проводок.
- API не выдаёт misleading total для смешанных валют.
- Результаты воспроизводимы и подготовлены к sanitized AdviceContext.
- Обновлён `STATUS.md`; создан commit `feat(07): provide reconciled financial analytics`.

