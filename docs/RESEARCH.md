# Исследование и основания решений

Проверено 2026-10-12. Ссылки нужны для повторной проверки перед этапами, где версия инструмента влияет на реализацию.

## Как вести длинную разработку в Codex

Официальная практика OpenAI для long-horizon задач рекомендует хранить цель, этапный план, runbook и живой статус в репозитории, а после каждой контрольной точки запускать тесты/линтеры/сборку и исправлять ошибки до движения дальше. Поэтому этот репозиторий содержит `SPEC.md`, `PLAN.md`, `IMPLEMENT.md` и `STATUS.md`, а не один монолитный промпт.

- [Run long horizon tasks with Codex](https://developers.openai.com/blog/run-long-horizon-tasks-with-codex)
- [Codex Prompting Guide](https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide)

`AGENTS.md` оставлен коротким и содержит только постоянные инварианты. Детали конкретного этапа живут в этапном промпте, чтобы не засорять контекст каждого запуска.

## vLLM на Windows и в Docker

vLLM требует Linux и не поддерживает Windows нативно; официальный путь на Windows — WSL с совместимым Linux-дистрибутивом. Поэтому целевой локальный путь — Linux-контейнер в Docker Desktop/WSL2, а не установка vLLM в Poetry-окружение Windows.

- [vLLM GPU installation requirements](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/)
- [Official vLLM Docker image](https://docs.vllm.ai/en/latest/deployment/docker/)
- [Docker Compose GPU support](https://docs.docker.com/compose/how-tos/gpu-support/)

Compose должен резервировать NVIDIA GPU с `capabilities: [gpu]`; наличие GPU проверяется отдельным preflight. Версии драйвера, Docker Desktop, CUDA userland и vLLM image нужно фиксировать после успешного smoke-test.

## OpenAI-compatible API

vLLM публикует OpenAI-compatible сервер и поддерживает как минимум Chat Completions и Responses API. Для широкого выбора провайдеров MVP использует Chat Completions как минимальный контракт и изолирует его адаптером.

- [vLLM OpenAI-compatible server](https://docs.vllm.ai/en/latest/serving/openai_compatible_server/)

## Локальная модель для 6 ГБ

У официального Qwen есть `Qwen3-4B-AWQ`: 4B параметров, 4-bit AWQ, и в model card приведён запуск через vLLM. Это делает модель разумным первым кандидатом, но model card не гарантирует работу в 6 ГБ при любом контексте и версии runtime. Весовые файлы — лишь часть VRAM; нужны KV cache, activations и служебные буферы.

- [Qwen3-4B-AWQ model card](https://huggingface.co/Qwen/Qwen3-4B-AWQ)

Принята безопасная стратегия: сначала контекст 2048–4096, одна последовательность, выключенный thinking, измерение VRAM и latency. При OOM уменьшается контекст или размер модели. Выбор не должен блокировать core-приложение.

## Что перепроверить перед публичным релизом

- Поддерживаемые теги vLLM и CUDA/driver matrix для конкретной машины.
- Актуальные security advisories всех lockfiles и container images.
- Почтовый провайдер, DNS-записи, rate limits и правила доставки.
- Юрисдикционные требования к хранению и обработке финансовых данных.
- Модель, лицензия, privacy terms и политика retention выбранного внешнего LLM-провайдера.

