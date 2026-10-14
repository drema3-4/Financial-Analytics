from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any, cast

import httpx2

from financial_analytics_app.ports import (
    AdvicePrompt,
    AdviceProviderCapabilities,
    AdviceProviderDescriptor,
    AdviceProviderError,
    AdviceProviderResponse,
)

RETRYABLE_STATUS_CODES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class OpenAICompatibleAdviceProvider:
    """Minimal OpenAI chat-completions adapter with no SDK types at its boundary."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        retry_backoff_seconds: float,
        endpoint_scope: str,
        capabilities: AdviceProviderCapabilities,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._sleep = sleep
        self._descriptor = AdviceProviderDescriptor(
            provider="openai_compatible",
            model=model,
            endpoint_scope=endpoint_scope,
        )
        self._capabilities = capabilities

    @property
    def descriptor(self) -> AdviceProviderDescriptor:
        return self._descriptor

    @property
    def capabilities(self) -> AdviceProviderCapabilities:
        return self._capabilities

    def generate(self, prompt: AdvicePrompt) -> AdviceProviderResponse:
        body: dict[str, object] = {
            "model": self._model,
            "messages": [
                {"role": message.role, "content": message.content} for message in prompt.messages
            ],
            "temperature": 0,
            "max_tokens": prompt.max_tokens,
        }
        if self._capabilities.json_schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "financial_advice",
                    "strict": True,
                    "schema": prompt.response_schema,
                },
            }
        if self._capabilities.non_thinking:
            body["chat_template_kwargs"] = {"enable_thinking": False}

        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        retry_after_seconds: int | None = None
        try:
            with httpx2.Client(
                timeout=self._timeout_seconds,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                for attempt in range(self._max_retries + 1):
                    try:
                        response = client.post(self._url, json=body, headers=headers)
                    except httpx2.TimeoutException as error:
                        if attempt < self._max_retries:
                            self._backoff(attempt, None)
                            continue
                        raise AdviceProviderError("timeout", retryable=True) from error
                    except httpx2.TransportError as error:
                        if attempt < self._max_retries:
                            self._backoff(attempt, None)
                            continue
                        raise AdviceProviderError("transport_error", retryable=True) from error

                    retry_after_seconds = _retry_after(response.headers.get("Retry-After"))
                    if response.status_code in RETRYABLE_STATUS_CODES:
                        if attempt < self._max_retries:
                            self._backoff(attempt, retry_after_seconds)
                            continue
                        code = "rate_limited" if response.status_code == 429 else "unavailable"
                        raise AdviceProviderError(
                            code,
                            retryable=True,
                            retry_after_seconds=retry_after_seconds,
                        )
                    if response.status_code < 200 or response.status_code >= 300:
                        raise AdviceProviderError("upstream_rejected")
                    return AdviceProviderResponse(_response_payload(response))
        except AdviceProviderError:
            raise
        except Exception as error:
            raise AdviceProviderError("transport_error", retryable=True) from error
        raise AdviceProviderError(
            "unavailable",
            retryable=True,
            retry_after_seconds=retry_after_seconds,
        )

    def _backoff(self, attempt: int, retry_after_seconds: int | None) -> None:
        calculated = self._retry_backoff_seconds * (2**attempt)
        delay = calculated if retry_after_seconds is None else max(calculated, retry_after_seconds)
        self._sleep(min(delay, 5.0))


def _retry_after(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        seconds = int(value)
    except ValueError:
        return None
    return max(0, min(seconds, 300))


def _response_payload(response: httpx2.Response) -> dict[str, object]:
    try:
        envelope = response.json()
    except (json.JSONDecodeError, ValueError) as error:
        raise AdviceProviderError("invalid_json") from error
    if not isinstance(envelope, dict):
        raise AdviceProviderError("invalid_response")
    choices = envelope.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise AdviceProviderError("invalid_response")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise AdviceProviderError("invalid_response")
    content = message.get("content")
    if not isinstance(content, str):
        raise AdviceProviderError("invalid_response")
    try:
        payload: Any = json.loads(content)
    except json.JSONDecodeError as error:
        raise AdviceProviderError("invalid_json") from error
    if not isinstance(payload, dict):
        raise AdviceProviderError("invalid_response")
    if not all(isinstance(key, str) for key in payload):
        raise AdviceProviderError("invalid_response")
    return cast(dict[str, object], payload)
