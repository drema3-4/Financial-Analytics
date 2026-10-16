from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from financial_analytics_api.context import correlation_id_context, request_id_context
from financial_analytics_infra.logging import redact_sensitive_text


class JsonFormatter(logging.Formatter):
    """Emit compact structured logs without serializing arbitrary record attributes."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_sensitive_text(record.getMessage()),
        }
        request_id = request_id_context.get()
        correlation_id = correlation_id_context.get()
        if request_id is not None:
            payload["request_id"] = request_id
        if correlation_id is not None:
            payload["correlation_id"] = correlation_id
        for attribute in ("event", "http_method", "http_status", "duration_ms"):
            value = getattr(record, attribute, None)
            if value is not None:
                payload[attribute] = value
        if record.exc_info is not None:
            payload["exception"] = redact_sensitive_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
