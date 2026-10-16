from __future__ import annotations

import re

SENSITIVE_PATTERNS = (
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)(authorization|cookie|password|token|api[_-]?key|secret)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)"),
)


def redact_sensitive_text(value: str) -> str:
    """Remove common credential and identity shapes from operational text."""

    redacted = value
    for pattern in SENSITIVE_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted
