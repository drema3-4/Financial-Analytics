# Этап 09 — LLM-советник и локальный vLLM

## Цель

Добавить приватный, заменяемый и необязательный слой объяснений поверх готовых финансовых расчётов.

## Выполни

- Реализуй provider port и OpenAI-compatible adapter с configurable `base_url`, `api_key`, `model`, timeout, bounded retry и capability flags. Не протаскивай SDK-типы в application/domain.
- Собери `AdviceContext` только из агрегатов, forecast/goals и безопасных фактов. Сырые transaction comments, email и другие PII внешнему провайдеру не отправляй без отдельного explicit consent.
- Определи versioned prompt и строгую response schema: summary, observations with evidence IDs, suggestions, assumptions, risks, confidence, disclaimer. Валидируй ответ; hallucinated evidence отклоняй.
- Провайдер не получает инструментов записи. Advice endpoints — read/compute only; unavailable LLM возвращает graceful status, а core UI продолжает работать.
- Добавь fake OpenAI-compatible server и contract tests для success, invalid JSON/schema, timeout, retryable/non-retryable errors, rate limit, prompt injection в пользовательском тексте и redaction.
- Добавь Compose profile `local-llm` с pinned `vllm/vllm-openai` image, GPU reservation, cache volume, healthcheck и стартовым `Qwen/Qwen3-4B-AWQ`. Начни с `max-model-len` 2048–4096, одной sequence и non-thinking режима.
- На целевой RTX 3050 6 ГБ запусти smoke/VRAM/latency test. Зафиксируй факты в `docs/LLM.md`; если OOM — уменьши контекст или официальный размер модели. Не ослабляй core и не выдавай непроверенное за успех.
- Добавь provider `disabled` и конфигурацию внешнего OpenAI-compatible endpoint без привязки к конкретному vendor.

## Приёмка

- Приложение и все финансовые функции работают с `LLM_PROVIDER=disabled`.
- Совет ссылается только на переданные evidence IDs и не меняет данные.
- External privacy consent default — off; запросы и логи не содержат секретов/PII.
- Local GPU результат честно отмечен как tested или not tested с причиной.
- Обновлён `STATUS.md`; создан commit `feat(09): add private provider-neutral financial advice`.

