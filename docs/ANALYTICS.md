# Reconciled analytics

Этап 07 строит отчёты непосредственно из owner-scoped `posted` ledger transactions и их
asset-side postings. Материализованного баланса или параллельного источника финансовых фактов
нет. Каждый денежный metric возвращает формулу и `evidence` с UUID transactions/postings.

## Семантика операций

| Ledger kind | Income/expense и cash flow | Net worth | Breakdown |
|---|---|---|---|
| `income` | asset delta входит в income | входит | категория и группа income |
| `expense` | минус asset delta входит в expense | входит | категория и группа expense |
| `interest` | asset delta входит в income | входит | `Deposit interest` / `Ungrouped` |
| `transfer` | нейтрален: сумма asset postings равна нулю | нейтрален в пределах валюты | не входит |
| `adjustment` | не входит | signed asset delta входит | не входит |
| `reversal` | вид и категория исходной операции, противоположный вклад в дату reversal | противоположный asset delta | исходная категория/группа |

Для валюты `c` и полуоткрытого интервала `[start, data_through)`:

```text
income(c)             = Σ asset_delta(income или interest)
expense(c)            = Σ -asset_delta(expense)
cash_flow(c)          = income(c) - expense(c)
savings(c)            = income(c) - expense(c)
savings_rate(c)       = savings(c) / income(c), только если income(c) > 0
mandatory_expense(c)  = Σ -asset_delta(expense с category.is_mandatory)
mandatory_share(c)    = mandatory_expense(c) / expense(c), только если expense(c) > 0
net_worth(c, t)       = Σ asset postings с occurred_at < t
net_worth_change(c)   = closing_net_worth(c) - opening_net_worth(c)
```

Rates сериализуются decimal string с шестью знаками и не ограничиваются диапазоном
`0..1`: отрицательный savings rate или рост более 100% остаются видимыми. При нулевом или
отрицательном denominator rate равен `null`, а numerator/denominator всё равно возвращаются.

Category и group breakdown имеют `flow_type=income|expense`. Сумма строк каждого flow type
точно совпадает с соответствующим total той же валюты. Отрицательная строка допустима, если в
интервале reversal превышает исходные операции.

## Валюты и пустые данные

Валюты никогда не складываются без сохранённого FX fact. Если отчёт содержит больше одной
валюты, `currency_mode=separated_by_currency`, `combined_currency=null`, а totals/buckets имеют
отдельную строку на валюту. Этап 07 не вводит FX rate/source и не использует base currency как
неявное разрешение на конвертацию.

При одной валюте mode равен `single_currency`; без asset accounts — `empty`. Для существующей
валюты пустой bucket материализуется exact zero. Savings rate и mandatory share такого bucket
равны `null`.

## Периоды и timezone

API принимает local calendar dates и использует IANA timezone из profile. Интервалы
полуоткрытые; boundaries переводятся из local midnight в UTC. Granularity:

- `day` — local calendar day;
- `week` — ISO week с понедельника;
- `month` — calendar month с первого числа.

Start и end должны быть выровнены по granularity; максимум — 366 buckets. Запрос не может
уходить дальше конца текущего local bucket. Для незакрытого bucket `data_through` обрезается
query clock, `is_complete=false`; будущие проводки не попадают в результат. Comparison такого
диапазона использует тот же local elapsed cut предыдущего равного диапазона, а не полный
предыдущий период. Это явно видно в `current_end` и `previous_end`.

## Comparison и anomaly policy

Comparison сопоставляет запрошенный диапазон с непосредственно предшествующим диапазоном того
же числа calendar buckets. Для income, expense, cash flow, savings и closing net worth
возвращаются current, previous, exact delta и `change_rate = delta / abs(previous)`; при нуле
previous rate равен `null`.

Deterministic policy `median-mad-v1` применяется только к завершённым buckets и отдельно к
income/expense каждой валюты:

```text
history   = шесть предыдущих завершённых buckets, пустые buckets имеют zero
baseline  = median(history)
MAD       = median(abs(history[i] - baseline))
threshold = max(0.50 * abs(baseline), 3 * MAD)
flag      = abs(observed - baseline) >= threshold и observed != baseline
```

Минимум baseline buckets — три; текущая версия всегда строит шесть calendar buckets. Ненулевое
значение после полностью нулевой baseline считается new activity. Flag содержит rationale,
observed, baseline, signed deviation, threshold и evidence наблюдаемого bucket. Никакой LLM в
классификации или арифметике не участвует.

## API и подготовка AdviceContext

- `GET /api/v1/analytics/dashboard` — totals, net worth, rates, comparison и anomaly flags;
- `GET /api/v1/reports/financial` — те же totals плюс day/week/month series и category/group
  breakdown.

Оба ответа содержат только финансовые агрегаты, calendar boundaries и opaque ledger UUIDs, без
email, свободного transaction description или credential/session данных. Поэтому application
result можно использовать как основу будущего sanitized `AdviceContext`; передача LLM и
consent остаются этапом 09.

## Измеряемый performance budget

Read path намеренно не имеет materialized aggregates до измерения. Integration gate создаёт
10 000 transactions двух tenants на диапазоне более двух лет и проверяет:

- owner/date query использует partial index
  `ix_transactions_owner_id_occurred_at_id_posted`, без sequential scan `transactions`;
- месячный slice читает не более 200 result rows и не пишет/читает temporary blocks;
- полный application report выполняет не более пяти `SELECT` statements: accounts,
  categories, groups, transactions и postings.

Budget основан на форме plan, row count и query count, а не на нестабильных миллисекундах CI.
При нарушении budget сначала сохраняется новый plan/measurement, затем принимается решение о
materialized read model или дополнительном индексе.
