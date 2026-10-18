# Прогнозы, сценарии и цели

Прогноз этапа 08 — детерминированная расчётная модель, а не обещание будущего результата.
Он не создаёт операций, не меняет ledger и не выполняет финансовых действий.

## Входной снимок и воспроизводимость

`ForecastInputSnapshot` — immutable domain value. Он содержит:

- точный `captured_at`, локальную дату `as_of`, IANA timezone и одну валюту;
- asset-счета и остатки как сумму immutable postings строго до `captured_at`;
- будущие occurrences активных recurring rules;
- будущие плановые net-interest entries действующих вкладов;
- значения нерегулярных расходов за полные исторические календарные месяцы.

`snapshot_id` — SHA-256 канонического JSON этих полей. Порядок accounts, events и samples
нормализуется перед хешированием. Один snapshot, `monthly-cashflow-v1` и один набор
`forecast-assumptions-v1` всегда дают один `ForecastResult`; clock, БД, FastAPI и LLM внутри
движка отсутствуют.

Все суммы — `Decimal`/`Money`, ставки — `Decimal`/`Rate`. Денежный результат каждого
масштабирования округляется `half_even` до minor unit валюты. Binary float не используется.

## Помесячная шкала

Диапазон прогноза включителен по пользовательской дате horizon. Внутри он разбивается на
полуоткрытые calendar slices `[starts_on, ends_on)`: первый и последний месяц могут быть
неполными. Максимальный горизонт — 600 slices.

Для месяца с индексом `m`, где первый slice имеет `m = 0`:

```text
inflation_factor(m) = (1 + annual_inflation / 12) ^ m
income               = scheduled_income * (1 + income_change)
scheduled_expense    = scheduled_expense * (1 + expense_change) * inflation_factor(m)
irregular_expense    = historical_median * (1 + expense_change)
                       * inflation_factor(m) * slice_days / calendar_month_days
savings_interest     = max(eligible_account_balance, 0) * annual_interest / 12
                       * slice_days / calendar_month_days
closing              = opening + scheduled flows - irregular expense
                       + one-time flows + deposit interest + savings interest
```

С этапа 14 обычные пользовательские счета не приносят процент (включая legacy `savings`).
Параметр scenario savings rate сохраняется в совместимом контракте, но такие счета не делает
процентными. Для вклада используется его собственный versioned interest schedule;
scenario rate не переписывает договор. Transfer даёт две account deltas и нулевое изменение
капитала. Principal flows берутся из того же helper, что и valuation: начальный остаток и
обычный перевод не теряются, капитализированные проценты не учитываются второй раз.

Цель редактируется с optimistic version; удаление выставляет archived и сохраняет audit.
Архивная цель исключена из списка и следующего goal plan. Изменение цели не меняет ledger.

## Baseline нерегулярных расходов

Берутся максимум шесть последних полных календарных месяцев. Месяц первой известной ledger
операции не считается полным; отсчёт начинается со следующего месяца. Для каждого account
явно материализуется zero, если в полном месяце нерегулярного расхода не было.

Recurring ledger transactions исключаются: они уже представлены будущими occurrences.
Expense reversal учитывается в дату reversal противоположной суммой, а итог месяца не может
стать отрицательным расходом. Baseline — медиана месячных значений по account.

- нет полных месяцев: baseline равен нулю и возвращается `no_complete_history`;
- один или два месяца: расчёт выполняется, но возвращается `insufficient_history`;
- три и более: предупреждение о недостатке данных не добавляется.

## Диапазон неопределённости

Метод `historical-expense-min-max-v1` не является вероятностным доверительным интервалом.
Все scheduled, deposit и one-time flows остаются одинаковыми:

- нижняя граница капитала подставляет наблюдавшийся максимум месячного нерегулярного расхода;
- верхняя граница подставляет наблюдавшийся минимум;
- обе траектории применяют те же scenario modifiers и последующее начисление savings interest.

Ответ всегда возвращает имя метода и текстовое объяснение. Метод показывает чувствительность
к уже наблюдаемому разбросу, но не покрывает неизвестные шоки.

## Сценарии

`ForecastScenario` хранит валюту, горизонт, изменения дохода/расхода, annual inflation,
annual savings rate и датированные one-time cashflows. Предположения имеют версию
`forecast-assumptions-v1`; scenario row имеет отдельную optimistic `version`.

Create/update пишут append-only audit events, но не postings. Обновление одного scenario не
меняет другой scenario, исторические операции или snapshot. Compare строит baseline и до 20
выбранных scenarios из одного общего snapshot и возвращает его ID у каждого результата.

Валюты не объединяются и не конвертируются. Для каждой валюты нужен отдельный вызов; скрытого
FX нет.

## Цели и priority allocation

Для цели:

```text
remaining = max(target - saved_amount, 0)
N = число calendar months от as_of до target_date включительно
required_monthly = ceil_to_minor_unit(remaining / N), если N > 0
required_monthly = remaining, если target_date уже прошла
```

`priority-waterfall-v1` сортирует цели по `(priority ASC, target_date ASC, UUID ASC)`. В конце
каждого forecast slice положительный `max(net_change, 0)` последовательно выделяется целям в
этом порядке, не превышая их remaining amount. Оптимизатора и LLM нет.

Для каждой цели возвращаются target/saved/remaining, required monthly contribution, средний
доступный положительный cashflow, contribution gap, фактически выделенная до срока сумма,
expected completion date, projected saved at target, shortfall, feasible flag и статус.
Цель после срока получает `missed_target`; уже достигнутая — нулевой required contribution и
`already_achieved`. Если scenario horizon короче срока, числовой план строится только по
известной шкале и явно возвращается `horizon_before_target:<goal_id>`.

## Ограничения

- Это cashflow forecast, а не гарантия, инвестиционная рекомендация или банковская оферта.
- Нет скрытых FX, рыночных цен, налоговых правил, зарплатного роста или сезонной ML-модели.
- Historical min/max не задаёт вероятность и может не включать будущие экстремумы.
- План цели не резервирует деньги на счёте и не создаёт переводов.
- Связанный account проверяет owner/currency и служит проверяемой связью, но `saved_amount`
  остаётся явным входом цели и не подменяется текущим балансом.
