from __future__ import annotations

from fastapi.testclient import TestClient

from financial_analytics_api.main import create_app
from financial_analytics_infra.settings import AppEnvironment, Settings


def test_openapi_documents_health_and_problem_details() -> None:
    async def database_is_up() -> bool:
        return True

    settings = Settings(app_env=AppEnvironment.TEST, _env_file=None)
    with TestClient(create_app(settings, database_is_up)) as client:
        schema = client.get("/openapi.json").json()

    assert schema["paths"]["/health/live"]["get"]["responses"]["200"]
    ready_responses = schema["paths"]["/health/ready"]["get"]["responses"]
    problem_schema = ready_responses["503"]["content"]["application/problem+json"]["schema"]
    assert problem_schema["title"] == "ProblemDetails"
