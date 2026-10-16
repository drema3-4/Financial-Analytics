from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from financial_analytics_api.ledger import _csv_safe
from financial_analytics_api.logging import JsonFormatter
from financial_analytics_api.observability import MetricsRegistry
from financial_analytics_infra.database import JobQueueSnapshot
from financial_analytics_infra.settings import AppEnvironment, Settings


@pytest.mark.parametrize(
    "malicious",
    ["=1+1", "+cmd", "-2+3", "@SUM(A1:A2)", "\t=1+1", "\r=1+1", "\n=1+1", " \ufeff=1+1"],
)
def test_csv_cells_cannot_start_spreadsheet_formulas(malicious: str) -> None:
    assert _csv_safe(malicious).startswith("'")


def test_structured_log_redacts_credentials_identity_and_card_data() -> None:
    record = logging.LogRecord(
        "security",
        logging.ERROR,
        __file__,
        1,
        (
            "authorization=Bearer abc.def cookie=session-value password=hunter2 "
            "owner@example.test 4111 1111 1111 1111"
        ),
        (),
        None,
    )
    payload = json.loads(JsonFormatter().format(record))
    serialized = json.dumps(payload)
    assert payload["level"] == "ERROR"
    for secret in ("abc.def", "session-value", "hunter2", "owner@example.test", "4111"):
        assert secret not in serialized
    assert "[REDACTED]" in payload["message"]


def test_metrics_have_only_bounded_labels_and_no_resource_identifiers() -> None:
    registry = MetricsRegistry()
    registry.observe_request("GET", 200, 0.01)
    registry.observe_request("UNTRUSTED", 503, 0.02)
    rendered = registry.render(
        ready=True,
        jobs=JobQueueSnapshot(pending=2, leased=1, dead_letter=0),
        provider_status="disabled",
    )
    assert 'method="GET",status_class="2xx"' in rendered
    assert 'method="OTHER",status_class="5xx"' in rendered
    assert 'state="pending"} 2' in rendered
    assert "/api/" not in rendered
    assert "owner" not in rendered
    assert "transaction" not in rendered


def test_fixed_clock_is_rejected_outside_test_and_requires_timezone() -> None:
    with pytest.raises(ValidationError, match="allowed only"):
        Settings(
            app_env=AppEnvironment.DEVELOPMENT,
            test_clock_at=datetime(2026, 10, 16, 8, tzinfo=UTC),
            _env_file=None,
        )
    with pytest.raises(ValidationError, match="UTC offset"):
        Settings(
            app_env=AppEnvironment.TEST,
            test_clock_at=datetime(2026, 10, 16, 8),
            _env_file=None,
        )
