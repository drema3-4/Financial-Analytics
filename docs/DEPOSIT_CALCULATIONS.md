# Расчёт вкладов

## Пользовательский сценарий этапа 14

Вклад создаётся отдельным объектом с названием, суммой и условиями; внутренний ledger account
создаёт сервер. Нулевой начальный остаток позволяет затем внести деньги переводом со счёта
без удвоения капитала. Начальная сумма уже существующего вклада оформляется adjustment.
UI принимает `10` как `10%`, API хранит exact Decimal долю `0.1`.

Единый журнал — источник пополнений, снятий, доходов и расходов. `principal_cashflows` читает
все principal postings. Отменённая исходная операция и reversal исключаются из исправленного
расчётного cashflow, а ledger сохраняет обе строки. После погашения операции меняют остаток,
но не приносят новых процентов.

Worker и финансовые mutations вызывают `reconcile_interest`. Под owner/deposit advisory lock
вычисляются due net-interest и уже проведённый interest с учётом reversals. В ledger и audit
добавляется только ненулевая разность. Изменение ставки или прошлой операции может создать
положительную или отрицательную корректировку. Условия имеют optimistic version и полный
before/after snapshot; повтор worker не дублирует начисления.

`earned_interest` — расчётная стоимость на начало даты минус чистая сумма principal cashflows
до неё; показатель не обнуляется после капитализации. `ledger_balance` содержит проведённые
операции всей выбранной даты. `current_value` добавляет ещё не капитализированные проценты,
а при погашении уже проведённые финальные проценты повторно не добавляются.

Старые договоры получают `automatic_interest=false`; миграция не меняет их проводки. После
проверки суммы и условий пользователь включает начисления в редакторе. Активные legacy-дубли
нужно предварительно архивировать; общий account остаётся активным, пока нужен другому договору.

Форма «факт» и пустая сверка убраны из основного UI. Совместимые legacy API bank fact остаются
для ручной сверки; в автоматическом режиме ledger приводится к расчёту договора. Расчётные
interest-строки управляются через условия вклада, пользовательские операции — через журнал.

Ниже описана неизменённая математика чистого engine; application valuation использует
приведённую выше семантику текущего ledger-остатка.

Документ описывает версию `deposit-interest-v1`. Расчёт выполняет чистая функция
`project_deposit(terms, cashflows, as_of, close_on)`: она не читает часы, БД или настройки
приложения. При одинаковых входах и версии алгоритма порядок и значения schedule одинаковы.

## Обязательные условия

`DepositTerms` хранит principal deposit account и currency; полуоткрытый договорный интервал
`[opened_on, matures_on)`; один или несколько последовательных rate periods; capitalization;
day-count; rounding mode и rounding frequency; IANA timezone и local cashflow cut-off;
early-close rule; явную tax rate. Эти параметры нельзя опустить в create API.

Rate period `[starts_on, ends_on)` включает левую и исключает правую границу. Периоды должны
быть отсортированы и без пробелов покрывать весь срок. Поэтому на дате изменения применяется
ровно новая ставка, а одна дата не попадает в два периода.

## Cashflow и cut-off

Пополнение или снятие — обычная immutable ledger transaction `transfer`; `deposit_id`
в совместимом cashflow endpoint необязателен для общего журнала, связь определяется account.
Положительная posting principal account означает пополнение, отрицательная — снятие.
Локальная дата действия определяется из UTC instant в `terms.timezone`:

```text
effective_date = local_date,     если local_time < cut_off
effective_date = local_date,     если local_time = cut_off и cut_off_inclusive = true
effective_date = local_date + 1, иначе
```

Cashflow применяется перед начислением за effective date. Отрицательный projected balance
запрещён. Дата погашения не приносит процент и не принимает новый расчётный cashflow.

## Day-count и дневной процент

Для balance `B_d`, nominal annual rate `r_d` и даты `d` точный процент:

```text
I_d = B_d × r_d × year_fraction(d, d + 1)
```

- `actual_365_fixed`: `year_fraction(a,b) = actual_days(a,b) / 365`.
- `actual_actual_isda`: интервал разбивается по календарным годам; доля каждого фрагмента
  равна `actual_days / 365` или `/ 366` для соответствующего года.

Все операнды — `Decimal`; binary float не попадает ни в домен, ни в JSON rate/money.

## Капитализация, округление и налог

`daily` капитализирует после каждого расчётного дня. `monthly_calendar_end` капитализирует на
первой дате следующего календарного месяца и всегда закрывает незавершённый период на
погашении. При `interest_rounding_frequency=daily` каждый `I_d` сначала округляется до minor
unit валюты. При `capitalization` сначала суммируются точные `I_d`, затем округляется сумма.
Mode всегда один из `half_even` или `half_up`.

Для capitalization event:

```text
gross = round(sum(day_interest))
tax   = round(max(gross, 0) × tax_rate)
net   = gross - tax
closing_balance = opening_balance + cashflows + net
```

Нулевая tax rate всё равно передаётся явно. Алгоритм не определяет юрисдикцию и не подбирает
льготы.

## Текущая стоимость и досрочное закрытие

`as_of` означает начало указанной local calendar date. Ответ разделяет:

- `current_principal` — применённые cashflows и уже капитализированный net interest;
- `accrued_interest` — ещё не капитализированный gross минус расчётный tax после округления;
- `current_value` — сумма двух предыдущих величин;
- `projected_maturity_value` — закрывающий balance полного выбранного срока.

При раннем `close_on` правило обязательно задаёт одно из: `forbid`; `forfeit_interest`
(пересчёт всего срока под 0); `reprice` (пересчёт всего срока под отдельную early-close rate).
Уже капитализированные плановые строки не считаются банковским фактом: результат заново
строится из cashflows по правилу договора.

## Effective yield

Effective yield — Decimal XIRR плановых внешних потоков. Пополнение имеет отрицательный знак
для вкладчика, снятие — положительный; projected closing value добавляется положительным
потоком на `closes_on`. Решается уравнение:

```text
Σ CF_i / (1 + y) ^ year_fraction(opened_on, date_i) = 0
```

Алгоритм использует 64-digit Decimal context и 192 фиксированных шага bisection на
детерминированной bracket. Результат округляется до 12 знаков. При отсутствии потоков обоих
знаков или bracket значение `null`, а не выдуманная доходность.

## План и факт

Чистый engine возвращает schedule и сам не создаёт ledger postings. Application worker
автоматически проводит due interest при automatic_interest=true (описано выше).
В ручном режиме банковский факт записывается новой
immutable transaction kind `interest` с `deposit_id`; её две posting увеличивают principal и
балансируют `system_income`. Исправление — reversal и новая posting (либо отдельная signed
posting), поэтому исходная запись остаётся в audit trail.

Reconciliation группирует planned net interest и фактические principal postings по local
posting date и возвращает `variance = actual - planned`. Фактическая корректировка не меняет
terms, rate periods, cashflows или schedule algorithm input.

## Эталонные таблицы

Независимые входы и ручные формулы находятся в
`tests/fixtures/deposits/{terms,rate_periods,cashflows,expected_schedule}.csv`. Они покрывают
monthly/daily capitalization, cashflow до/после cut-off, частичное снятие, leap year,
`half_even`/`half_up`, rate boundary, tax и early close. Unit test сравнивает каждую денежную
ячейку с результатом engine до заявленного minor-unit rounding.
