from __future__ import annotations

from fastapi.testclient import TestClient

from financial_analytics_api.main import create_app
from financial_analytics_infra.settings import AppEnvironment, Settings


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
