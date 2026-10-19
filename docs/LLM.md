# LLM-советник и provider-neutral запуск

Этап 09 добавляет необязательный слой объяснений поверх уже рассчитанных analytics, forecast и
goal plan. LLM не рассчитывает деньги, не получает tools и не имеет endpoint для записи.
Core stack, readiness и все финансовые функции работают при `LLM_PROVIDER=disabled` — это
значение по умолчанию.

## Контракт и границы

- Application port принимает только `AdvicePrompt` и возвращает обычный JSON object; типы
  HTTP-клиента и OpenAI SDK не пересекают application/domain boundary.
- `advice-context-v1` содержит только агрегаты выбранной валюты, comparison/anomaly facts,
  итог deterministic forecast и числовые goal plans. Money/rate передаются строками.
- В context не входят email, account/category/goal names, transaction comments/descriptions,
  transaction/posting IDs и сырые ledger rows. Описание one-time event также не передаётся.
- Необязательный вопрос сериализуется отдельным `untrusted_user_text`, а не добавляется к
  инструкциям. Email, телефон, длинные номера карт/счетов, bearer/token/key и явные
  password/secret assignments заменяются на `[REDACTED]`.
- Для `LLM_ENDPOINT_SCOPE=external` вопрос целиком пропускается, пока конкретный запрос не
  установит `allow_external_user_text=true`. Default — `false`; даже после consent redaction
  остаётся обязательным. Агрегированные safe facts передаются независимо от этого флага.
- Prompt `financial-advice-v1` требует JSON со строго заданными полями `summary`,
  `observations[].evidence_ids`, `suggestions`, `assumptions`, `risks`, `confidence` и
  `disclaimer`. Extra fields и неправильные типы отклоняются. Любая ссылка не из списка
  переданных evidence IDs отклоняет весь ответ как `invalid_response`.
- Ответ не сохраняется в БД и не создаёт audit/idempotency/ledger mutations. `POST /advice`
  здесь является read/compute запросом, как сравнение forecast scenarios.

## API

- `GET /api/v1/advice/status` — безопасный configured status без base URL и API key.
- `POST /api/v1/advice` — собирает owner-scoped context и возвращает advice, переданный модели
  sanitized evidence map либо graceful status. Для baseline нужен `through`; вместо него можно
  указать `scenario_id`. Currency по умолчанию берётся из профиля, analytics period — текущий
  локальный календарный месяц.

Provider failures не превращают optional LLM в отказ core API:

| `status` | Значение |
|---|---|
| `configured` | provider настроен; status endpoint не выполняет сетевой health probe |
| `available` | schema и evidence references прошли проверку |
| `disabled` | provider намеренно выключен |
| `unavailable` | timeout, transport, bounded retry exhaustion, rate limit или upstream reject |
| `invalid_response` | JSON/schema/evidence contract нарушен |

`error_code` намеренно короткий и не включает upstream body, URL, ключ, prompt или финансовые
данные. Request middleware не логирует body; provider adapter также не логирует запрос/ответ.

## Конфигурация

Core/default:

```text
LLM_PROVIDER=disabled
```

Любой OpenAI-compatible endpoint настраивается без vendor-specific класса:

```text
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://llm.example.test/v1
LLM_API_KEY=local-or-secret-manager-value
LLM_MODEL=deployed-model-name
LLM_ENDPOINT_SCOPE=external
LLM_TIMEOUT_SECONDS=20
LLM_MAX_RETRIES=2
LLM_RETRY_BACKOFF_SECONDS=0.25
LLM_MAX_TOKENS=800
LLM_SUPPORTS_JSON_SCHEMA=true
LLM_SUPPORTS_SYSTEM_MESSAGES=true
LLM_SUPPORTS_NON_THINKING=false
```

Retry budget ограничен `0..3`, timeout — `0..120` секунд. Повторяются только timeout/transport
и HTTP `408`, `409`, `425`, `429`, `5xx` из allowlist; остальные `4xx` не повторяются.
`Retry-After` учитывается с локальным cap 5 секунд ожидания на попытку. В production внешний
endpoint обязан использовать HTTPS и API key. Capability flags нужно выставлять по
фактическому контракту endpoint: при выключенном JSON Schema prompt всё равно проверяется
локально строгой response schema.

## Локальный vLLM profile

Compose service использует официальный image
`vllm/vllm-openai:v0.11.0@sha256:014a95f21c9edf6abe0aea6b07353f96baa4ec291c427bb1176dc7c93a85845c`,
модель `Qwen/Qwen3-4B-AWQ`, persistent volume `huggingface_cache`, одну GPU и healthcheck
`/health`. Начальные ограничения:

```text
--max-model-len 2048
--max-num-seqs 1
--gpu-memory-utilization 0.80
```

На целевой RTX 3050 исходное значение `0.90` требовало 5.4 GiB свободной VRAM при фактически
доступных 5.02 GiB, поэтому проверенный default снижен до `0.80`. Это меняет только размер
предварительно резервируемого GPU cache и не уменьшает контекст или модель. Для загрузки весов
profile устанавливает `HF_HUB_DISABLE_XET=1`: обычный проверяемый HTTPS остаётся включён, но
обходится несовместимый с локальной TLS-цепочкой Xet transport.

Non-thinking включается capability-флагом в каждом chat request через
`chat_template_kwargs.enable_thinking=false`. API не зависит от health vLLM, поэтому медленная
загрузка модели или OOM не блокируют PostgreSQL, worker, web и backend readiness.

Запуск из PowerShell:

```powershell
$env:LLM_PROVIDER = "openai_compatible"
$env:LLM_BASE_URL = "http://vllm:8000/v1"
$env:LLM_ENDPOINT_SCOPE = "local"
$env:LLM_TIMEOUT_SECONDS = "120"
docker compose --profile local-llm up --build --wait
```

vLLM публикуется для диагностики на `http://localhost:8001`; backend обращается к нему только
по внутреннему имени `vllm:8000`. Для возврата к core остановите optional service, удалите
provider overrides и пересоздайте core; schema и финансовые volumes остаются прежними:

```powershell
docker compose --profile local-llm stop vllm
Remove-Item Env:LLM_PROVIDER, Env:LLM_BASE_URL, Env:LLM_ENDPOINT_SCOPE, Env:LLM_TIMEOUT_SECONDS -ErrorAction SilentlyContinue
docker compose --profile core up -d --wait
```

## RTX 3050 6 ГБ: smoke, VRAM и latency

Целевой host на 2026-10-14: `NVIDIA GeForce RTX 3050 6GB Laptop GPU`, `6144 MiB`, driver
`577.05`, Docker Engine `29.1.2`. Результат: **tested** на pinned vLLM `0.11.0` и
`Qwen/Qwen3-4B-AWQ` с context 2048, одной sequence, AWQ Marlin и non-thinking mode.

Исходный GPU reserve `0.90` был честно отклонён vLLM preflight: свободно `5.02/6.0 GiB`, а
требовалось `5.4 GiB`. Это не CUDA OOM. При `0.80` та же модель и context успешно загрузились;
vLLM сообщил `2.5138 GiB` для model weights, `2.10 GiB` доступного KV cache и capacity
`15,248` tokens. Первый download весов занял `105.40 s`, engine init после загрузки — `59.34 s`.
Уменьшать context либо переходить на меньшую модель не потребовалось.

Измерения host `nvidia-smi`:

- до vLLM: `560 MiB`;
- сразу после health: `5487 MiB`;
- максимум, наблюдавшийся во время smoke/structured проверок: `5528 MiB` из `6144 MiB`;
- CUDA OOM во время старта и генерации не было.

Три одинаковых `/v1/chat/completions` запроса с `max_tokens=64`, `temperature=0` и
`enable_thinking=false` вернули `OK`: первый `3777 ms`, повторные `81 ms` и `100 ms`. Отдельный
end-to-end прогон application adapter с настоящей строгой Advice JSON Schema успешно прошёл
локальную schema/evidence validation за `85,313 ms`; ответ сослался только на переданный
`analytics:cash-flow`. Попытка с timeout 60 s закономерно завершилась timeout во время
constrained decoding, поэтому для этой GPU локальному profile рекомендован
`LLM_TIMEOUT_SECONDS=120`. Provider остаётся bounded и при timeout возвращает graceful
`unavailable`.

На машине Docker/Hugging Face Xet transport не доверял локальной TLS-цепочке. Profile использует
`HF_HUB_DISABLE_XET=1`, после чего веса скачались по обычному HTTPS с проверкой сертификатов;
TLS verification не отключалась. Persistent `huggingface_cache` сохранён для повторных запусков.

В release rehearsal этапа 13 дополнительно обнаружен сбой встроенного `hf_transfer` при
скачивании в пустой cache (`no permits available`). Profile закрепляет
`HF_HUB_ENABLE_HF_TRANSFER=0`, обычный certificate-verifying HTTPS downloader и model revision
`74d4bd2bd4bff9cafc9345221320bffb08b406a3` через `VLLM_MODEL_REVISION`. Model weights не входят в Git.

Повтор 2026-10-17: corrected cold-cache startup `232.4 s`, health `200`, simple chat `3048 ms`,
observed VRAM `5961/6144 MiB`, OOM не наблюдался. Полный structured advice на release fixture
превысил `180 s` client deadline при provider timeout `120 s` и двух retries; доступность полного
совета в этом прогоне не подтверждена. Для одного ограниченного по времени запроса задайте
`LLM_MAX_RETRIES=0` и измерьте полный adapter round-trip на целевом host. После выключения vLLM
core ready/provider disabled и финансовые данные/schema сохранились. Точные команды и результаты
приведены в `docs/FRESH_MACHINE_REHEARSAL.md`.

Проверочная последовательность:

```text
docker compose --profile local-llm up -d vllm
docker compose ps vllm
docker compose logs --no-color vllm
docker exec financial-analytics-vllm-1 nvidia-smi --query-compute-apps=used_memory --format=csv,noheader,nounits
```

Smoke вызывает `/v1/chat/completions` с `max_tokens=64`, `temperature=0` и
`chat_template_kwargs: {"enable_thinking": false}`; latency измеряется wall-clock отдельно для
первого и повторного запроса. Если на другом host 4B AWQ получает OOM, сначала уменьшается
`VLLM_MAX_MODEL_LEN`; следующий допустимый шаг — официальный меньший Qwen3 AWQ. CPU offload,
сокращение deterministic context и перенос финансовых вычислений в LLM не считаются успехом.

## Демонстрационный прогон 2026-10-19

Отдельный стенд из [DEMO.md](DEMO.md) содержит 176 синтетических операций, шесть сценариев
и пять целей с разной достижимостью. Для полного контекста нескольких целей используется
`VLLM_MAX_MODEL_LEN=4096`, та же закреплённая Qwen3-4B-AWQ, GPU reserve `0.80`, одна sequence,
non-thinking, `LLM_MAX_TOKENS=800`, provider timeout `120 s`, retries `0`.

Реальные запросы через зарегистрированный demo tenant и HTTP `POST /api/v1/advice`:

| Запрос | Итог | Время |
|---|---|---:|
| Базовые приоритеты и подушка безопасности | `available` | 87.00 s |
| Сценарий снижения расходов на 15% | `available` | 66.20 s |
| Стрессовый сценарий и проблемные цели | `available` | 119.58 s |

Все ответы прошли строгую schema/evidence validation. Fingerprint полного журнала до и после
трёх запросов и сравнения сценариев совпал. Наблюдавшаяся VRAM во время генерации —
`5806/6144 MiB`; OOM не наблюдался. Последний запрос близок к timeout, поэтому это измерение
успешного прогона, а не гарантия latency. Для показа подготовлены ignored снимки ответов в
`generated-reports/demo/SHOWCASE.md` и `advice-1.json`–`advice-3.json`.

Core/default profile не меняет context 2048. Demo override используется только в отдельном
Compose project; личные данные в эксперимент не копировались.
