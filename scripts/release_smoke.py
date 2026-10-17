from __future__ import annotations

import argparse
import json
import re
import time
from decimal import Decimal
from http.cookies import SimpleCookie
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen


class ApiSession:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._cookies: dict[str, str] = {}

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        csrf: bool = False,
        idempotency_key: str | None = None,
        expected: int = 200,
    ) -> Any:
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body, separators=(",", ":")).encode()
            headers["Content-Type"] = "application/json"
        if self._cookies:
            headers["Cookie"] = "; ".join(
                f"{name}={value}" for name, value in self._cookies.items()
            )
        if csrf:
            headers["X-CSRF-Token"] = self._cookies["fa_csrf"]
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        request = Request(f"{self._base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=180) as response:  # noqa: S310 - explicit operator URL
                payload = response.read()
                status = response.status
                set_cookie = response.headers.get_all("Set-Cookie") or []
        except HTTPError as error:
            payload = error.read()
            status = error.code
            set_cookie = error.headers.get_all("Set-Cookie") or []
        for value in set_cookie:
            parsed = SimpleCookie(value)
            for name, morsel in parsed.items():
                self._cookies[name] = morsel.value
        if status != expected:
            detail = payload.decode("utf-8", errors="replace")[:1000]
            raise RuntimeError(f"{method} {path} returned {status}, expected {expected}: {detail}")
        if not payload or payload == b"null":
            return None
        return json.loads(payload)


def mail_token(mailpit_url: str, recipient: str, route: str) -> str:
    for _ in range(60):
        with urlopen(f"{mailpit_url.rstrip('/')}/api/v1/messages", timeout=10) as response:
            messages = json.load(response)["messages"]
        for message in messages:
            if not any(address["Address"] == recipient for address in message["To"]):
                continue
            with urlopen(
                f"{mailpit_url.rstrip('/')}/api/v1/message/{message['ID']}", timeout=10
            ) as response:
                body = json.load(response)["Text"]
            for link in re.findall(r"https?://\S+", body):
                parsed = urlsplit(link)
                if parsed.path == route:
                    return parse_qs(parsed.query)["token"][0]
        time.sleep(1)
    raise RuntimeError(f"SMTP delivery of {route} did not arrive within 60 seconds")


def run(base_url: str, invite_email: str | None = None, mailpit_url: str | None = None) -> None:
    client = ApiSession(base_url)
    ready = client.request("GET", "/health/ready")
    if ready["status"] != "ready":
        raise RuntimeError("API did not report ready")
    profile = client.request(
        "POST",
        "/api/v1/auth/bootstrap",
        body={
            "email": "release-smoke@example.test",
            "password": "release smoke password 2026",
            "base_currency": "RUB",
            "locale": "ru-RU",
            "timezone": "Europe/Saratov",
        },
        expected=201,
    )
    account = client.request(
        "POST",
        "/api/v1/accounts",
        body={
            "name": "Release smoke account",
            "kind": "bank",
            "currency": "RUB",
            "opening_balance": {"amount": "10000.00", "currency": "RUB"},
            "opening_balance_occurred_at": "2026-10-16T08:00:00Z",
        },
        csrf=True,
        idempotency_key="release-smoke-account",
        expected=201,
    )
    category = client.request(
        "POST",
        "/api/v1/categories",
        body={"name": "Release smoke expense", "kind": "expense"},
        csrf=True,
        idempotency_key="release-smoke-category",
        expected=201,
    )
    transaction = client.request(
        "POST",
        "/api/v1/transactions/expense",
        body={
            "account_id": account["id"],
            "category_id": category["id"],
            "money": {"amount": "125.25", "currency": "RUB"},
            "occurred_at": "2026-10-16T09:00:00Z",
            "description": "Release smoke operation",
            "source": "manual",
        },
        csrf=True,
        idempotency_key="release-smoke-expense",
        expected=201,
    )
    goal = client.request(
        "POST",
        "/api/v1/goals",
        body={
            "name": "Release smoke reserve",
            "target": {"amount": "100000.00", "currency": "RUB"},
            "target_date": "2027-10-16",
            "saved_amount": {"amount": "10000.00", "currency": "RUB"},
            "priority": 1,
            "linked_account_id": account["id"],
        },
        csrf=True,
        idempotency_key="release-smoke-goal",
        expected=201,
    )
    forecast_query = urlencode({"currency": "RUB", "through": "2027-10-16"})
    forecast = client.request("GET", f"/api/v1/forecasts?{forecast_query}")
    advice = client.request(
        "POST",
        "/api/v1/advice",
        body={"through": "2027-10-16", "question": "Объясни прогноз"},
    )
    if forecast["forecast"]["algorithm_version"] != "monthly-cashflow-v1":
        raise RuntimeError("unexpected forecast algorithm")
    if not forecast["goal_plan"]["goals"]:
        raise RuntimeError("goal was not included in the forecast plan")
    if Decimal(forecast["forecast"]["opening_total"]["amount"]) != Decimal("9874.75"):
        raise RuntimeError("forecast opening balance does not reconcile with the operation")
    if advice["status"] not in {"disabled", "available"}:
        raise RuntimeError("optional advice returned an unexpected status")
    invitation_status = "not-requested"
    if invite_email is not None:
        client.request(
            "POST",
            "/api/v1/admin/allowlist",
            body={"email": invite_email},
            csrf=True,
            expected=201,
        )
        invitation = client.request(
            "POST",
            "/api/v1/admin/invitations",
            body={"email": invite_email, "is_admin": False},
            csrf=True,
            expected=201,
        )
        invitation_status = "created" if invitation["id"] else "invalid"
        if mailpit_url is not None:
            raw_token = mail_token(mailpit_url, invite_email, "/invite")
            guest = ApiSession(base_url)
            acceptance = {
                "token": raw_token,
                "password": "invited release smoke password",
                "base_currency": "RUB",
                "locale": "ru-RU",
                "timezone": "Europe/Saratov",
            }
            guest.request("POST", "/api/v1/auth/invitations/accept", body=acceptance, expected=201)
            guest.request("POST", "/api/v1/auth/invitations/accept", body=acceptance, expected=400)
            guest.request("GET", "/api/v1/admin/allowlist", expected=403)
            guest.request(
                "POST",
                "/api/v1/auth/password-reset/request",
                body={"email": invite_email},
                expected=202,
            )
            reset_token = mail_token(mailpit_url, invite_email, "/reset-password")
            reset = {"token": reset_token, "new_password": "reset release smoke password"}
            guest.request("POST", "/api/v1/auth/password-reset/confirm", body=reset, expected=204)
            guest.request("POST", "/api/v1/auth/password-reset/confirm", body=reset, expected=400)
            guest.request("GET", "/api/v1/profile", expected=401)
            invitation_status = "smtp-accepted-replay-denied-reset-replay-denied-admin-denied"
    print(
        json.dumps(
            {
                "status": "passed",
                "profile_id": profile["id"],
                "transaction_id": transaction["id"],
                "goal_id": goal["id"],
                "forecast_algorithm": forecast["forecast"]["algorithm_version"],
                "advice_status": advice["status"],
                "invitation_status": invitation_status,
            },
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage-13 release walkthrough")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--invite-email")
    parser.add_argument("--mailpit-url")
    args = parser.parse_args()
    if args.mailpit_url is not None and args.invite_email is None:
        parser.error("--mailpit-url requires --invite-email")
    run(args.base_url, args.invite_email, args.mailpit_url)


if __name__ == "__main__":
    main()
