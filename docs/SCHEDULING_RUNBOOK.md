# Runbook: recurring worker и outbox

## Что гарантирует система

Scheduler материализует due occurrence в `outbox_jobs` и атомарно двигает
`recurring_rules.next_occurrence_at`. Уникальный `dedup_key` имеет вид
`<rule_id>:<occurrence_at UTC>`. Worker доставляет job как минимум один раз, а ledger
idempotency превращает повторную доставку в тот же transaction. Поэтому crash после ledger
commit, но до подтверждения job, не создаёт вторую финансовую операцию.

Lease по умолчанию действует 30 секунд. Claim увеличивает `attempts`; ошибки повторяются с
backoff 5, 10, 20, 40 секунд. Пятая неуспешная попытка переводит job в `dead_letter`.
Истёкший lease забирается другим worker автоматически.

## Ежедневная проверка

Состояние процессов и последние логи:

```text
docker compose ps
docker compose logs --since=30m --no-color worker api postgres
```

Worker healthy, только если heartbeat свежий и PostgreSQL отвечает. Для read-only проверки
очереди внутри PostgreSQL:

```sql
SELECT state, count(*)
FROM outbox_jobs
GROUP BY state
ORDER BY state;

SELECT min(available_at) AS oldest_available, count(*) AS ready
FROM outbox_jobs
WHERE state = 'pending' AND available_at <= now();

SELECT count(*) AS expired_leases
FROM outbox_jobs
WHERE state = 'leased' AND lease_expires_at <= now();

SELECT count(*) AS overdue_rules
FROM recurring_rules
WHERE status = 'active' AND next_occurrence_at <= now();
```

Положительные `ready`, `expired_leases` или `overdue_rules` допустимы кратковременно. Если
значение не уменьшается несколько worker ticks, проверить доступность БД и ошибки worker.
Не выводить `payload` jobs в общие логи: он содержит финансовый шаблон.

Dead-letter текущего пользователя доступен через:

```text
GET /api/v1/recurring-jobs/dead-letter
```

Ответ содержит job/rule IDs, occurrence UTC, attempts и последнюю ошибку, но не изменяет
очередь.

## Безопасный ручной retry

1. Найти job через endpoint dead-letter и записать его `id`, `rule_id`, `occurrence_at`,
   `last_error`.
2. Устранить причину: например, выбрать рабочий account/category в правиле. Не редактировать
   `dedup_key`, occurrence или уже созданную transaction.
3. Выполнить аутентифицированный mutation с действующим CSRF token:

```text
POST /api/v1/recurring-jobs/{job_id}/retry
X-CSRF-Token: <session-csrf-token>
```

4. Убедиться, что job исчез из dead-letter list и затем получил `succeeded`. Если ledger
   transaction уже существовала после crash, worker получит её через тот же idempotency key;
   новая transaction создана не будет.
5. Проверить append-only событие `scheduling.dead_letter_retried` в `audit_events` по
   `aggregate_id = job_id`.

Retry сбрасывает attempts и делает job доступной немедленно, но сохраняет тот же dedup key и
снимок операции. Это принципиально: изменение job payload превратило бы retry в другую
финансовую команду.

## Запрещённые ручные действия

- не удалять rows из `outbox_jobs`, `idempotency_records`, `transactions`, `postings` или
  `audit_events`;
- не переводить job в `succeeded` SQL-командой;
- не сбрасывать attempts и lease напрямую — использовать retry endpoint;
- не создавать «компенсирующую» transaction вручную, пока не проверен idempotency record;
- не менять системное время контейнера для ускорения расписания.

Если ошибка повторяется после исправления ссылки, сохранить job/rule IDs и correlation ID
API-запроса, снять только структурированные логи без payload и подготовить forward fix.
