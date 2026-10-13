from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from financial_analytics_api.main import create_app
from financial_analytics_infra.settings import AppEnvironment, Settings

ROOT = Path(__file__).resolve().parents[2]


def test_openapi_documents_health_identity_and_problem_details() -> None:
    async def database_is_up() -> bool:
        return True

    settings = Settings(app_env=AppEnvironment.TEST, _env_file=None)
    with TestClient(create_app(settings, database_is_up)) as client:
        schema = client.get("/openapi.json").json()

    assert schema["paths"]["/health/live"]["get"]["responses"]["200"]
    assert schema["paths"]["/api/v1/auth/bootstrap"]["post"]["responses"]["201"]
    assert schema["paths"]["/api/v1/auth/login"]["post"]["responses"]["200"]
    assert schema["paths"]["/api/v1/auth/refresh"]["post"]["responses"]["200"]
    assert schema["paths"]["/api/v1/auth/logout"]["post"]["responses"]["204"]
    assert schema["paths"]["/api/v1/auth/logout-all"]["post"]["responses"]["204"]
    assert schema["paths"]["/api/v1/profile"]["get"]["responses"]["200"]
    identity_problem = schema["paths"]["/api/v1/auth/login"]["post"]["responses"]["401"]
    assert identity_problem["content"]["application/problem+json"]["schema"]["$ref"].endswith(
        "/ProblemDetails"
    )
    ready_responses = schema["paths"]["/health/ready"]["get"]["responses"]
    problem_schema = ready_responses["503"]["content"]["application/problem+json"]["schema"]
    assert problem_schema["title"] == "ProblemDetails"


def test_openapi_documents_ledger_contracts_examples_and_exact_money() -> None:
    settings = Settings(app_env=AppEnvironment.TEST, _env_file=None)
    with TestClient(create_app(settings)) as client:
        schema = client.get("/openapi.json").json()

    required_paths = {
        "/api/v1/accounts",
        "/api/v1/accounts/{account_id}",
        "/api/v1/category-groups",
        "/api/v1/categories",
        "/api/v1/tags",
        "/api/v1/transactions/income",
        "/api/v1/transactions/expense",
        "/api/v1/transfers",
        "/api/v1/adjustments",
        "/api/v1/transactions",
        "/api/v1/transactions/export.csv",
        "/api/v1/transactions/{transaction_id}/reversal",
    }
    assert required_paths <= schema["paths"].keys()
    assert "delete" not in schema["paths"]["/api/v1/transactions/{transaction_id}"]

    create_account = schema["paths"]["/api/v1/accounts"]["post"]
    headers = {item["name"]: item for item in create_account["parameters"]}
    assert headers["Idempotency-Key"]["required"] is True
    assert create_account["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/CreateAccountRequest"
    )
    assert schema["components"]["schemas"]["CreateAccountRequest"]["examples"]
    amount_schema = schema["components"]["schemas"]["MoneyInput"]["properties"]["amount"]
    assert amount_schema["type"] == "string"
    assert "pattern" in amount_schema
    assert "409" in create_account["responses"]
    assert create_account["responses"]["409"]["content"]["application/problem+json"]


def test_checked_in_openapi_snapshot_matches_application() -> None:
    settings = Settings(app_env=AppEnvironment.TEST, _env_file=None)
    generated = create_app(settings).openapi()
    snapshot = json.loads((ROOT / "docs" / "openapi.json").read_text(encoding="utf-8"))
    assert snapshot == generated


def test_openapi_documents_recurring_rules_preview_and_dead_letter_retry() -> None:
    settings = Settings(app_env=AppEnvironment.TEST, _env_file=None)
    schema = create_app(settings).openapi()
    required_paths = {
        "/api/v1/recurring-rules",
        "/api/v1/recurring-rules/preview",
        "/api/v1/recurring-rules/{rule_id}",
        "/api/v1/recurring-rules/{rule_id}/pause",
        "/api/v1/recurring-rules/{rule_id}/resume",
        "/api/v1/recurring-jobs/dead-letter",
        "/api/v1/recurring-jobs/{job_id}/retry",
    }
    assert required_paths <= schema["paths"].keys()
    preview = schema["paths"]["/api/v1/recurring-rules/preview"]["post"]
    assert preview["operationId"] == "previewRecurringOccurrences"
    assert preview["responses"]["200"]
    retry = schema["paths"]["/api/v1/recurring-jobs/{job_id}/retry"]["post"]
    assert "403" in retry["responses"]


def test_openapi_documents_deposit_terms_exact_rates_and_valuation() -> None:
    settings = Settings(app_env=AppEnvironment.TEST, _env_file=None)
    schema = create_app(settings).openapi()
    required_paths = {
        "/api/v1/deposits",
        "/api/v1/deposits/{deposit_id}",
        "/api/v1/deposits/{deposit_id}/cashflows",
        "/api/v1/deposits/{deposit_id}/interest-postings",
        "/api/v1/deposits/{deposit_id}/valuation",
    }
    assert required_paths <= schema["paths"].keys()
    create = schema["paths"]["/api/v1/deposits"]["post"]
    assert create["operationId"] == "createDeposit"
    request_schema = schema["components"]["schemas"]["CreateDepositRequest"]
    required = set(request_schema["required"])
    assert {
        "capitalization_frequency",
        "day_count_convention",
        "rounding_policy",
        "interest_rounding_frequency",
        "cashflow_cutoff_time",
        "cashflow_cutoff_inclusive",
        "early_close_rule",
        "tax_rate",
    } <= required
    assert schema["components"]["schemas"]["RateInput"]["properties"]["value"]["type"] == ("string")
    valuation = schema["paths"]["/api/v1/deposits/{deposit_id}/valuation"]["get"]
    as_of = next(item for item in valuation["parameters"] if item["name"] == "as_of")
    assert as_of["required"] is True


def test_openapi_documents_reconciled_analytics_contracts() -> None:
    settings = Settings(app_env=AppEnvironment.TEST, _env_file=None)
    schema = create_app(settings).openapi()
    assert {
        "/api/v1/analytics/dashboard",
        "/api/v1/reports/financial",
    } <= schema["paths"].keys()
    dashboard = schema["paths"]["/api/v1/analytics/dashboard"]["get"]
    report = schema["paths"]["/api/v1/reports/financial"]["get"]
    assert dashboard["operationId"] == "getAnalyticsDashboard"
    assert report["operationId"] == "getFinancialReport"
    report_parameters = {item["name"]: item for item in report["parameters"]}
    assert report_parameters["period_start"]["required"] is True
    assert report_parameters["period_end"]["required"] is True
    assert report_parameters["granularity"]["schema"]["$ref"].endswith("/PeriodGranularity")
    assert set(schema["components"]["schemas"]["PeriodGranularity"]["enum"]) == {
        "day",
        "week",
        "month",
    }
    money_metric = schema["components"]["schemas"]["MoneyMetricResponse"]
    assert {"value", "formula", "evidence"} <= set(money_metric["required"])
    category = schema["components"]["schemas"]["CategoryResponse"]
    assert "is_mandatory" in category["required"]
