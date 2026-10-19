"""Populate the isolated local demo through the public API; never seed a personal database."""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import secrets
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from release_smoke import ApiSession

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "demo-v1"
RUB = "RUB"


def read_environment(path: Path) -> dict[str, str]:
    return {
        key: value
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
        for key, value in [line.split("=", 1)]
    }


def prepare_environment(path: Path, as_of: date) -> None:
    if path.exists():
        print("Existing demo environment preserved")
        return
    values = {
        "POSTGRES_PASSWORD": secrets.token_urlsafe(24),
        "SESSION_SECRET": secrets.token_urlsafe(40),
        "CSRF_SECRET": secrets.token_urlsafe(40),
        "EMAIL_TOKEN_SECRET": secrets.token_urlsafe(40),
        "LLM_PROVIDER": "openai_compatible",
        "LLM_BASE_URL": "http://vllm:8000/v1",
        "LLM_MODEL": "Qwen/Qwen3-4B-AWQ",
        "LLM_ENDPOINT_SCOPE": "local",
        "LLM_TIMEOUT_SECONDS": "120",
        "LLM_MAX_RETRIES": "0",
        "LLM_MAX_TOKENS": "800",
        "LLM_SUPPORTS_JSON_SCHEMA": "true",
        "LLM_SUPPORTS_SYSTEM_MESSAGES": "true",
        "LLM_SUPPORTS_NON_THINKING": "true",
        "VLLM_MAX_MODEL_LEN": "4096",
        "VLLM_GPU_MEMORY_UTILIZATION": "0.80",
        "DEMO_EMAIL": "demo@example.test",
        "DEMO_PASSWORD": f"Demo-{secrets.token_urlsafe(12)}",
        "DEMO_AS_OF": as_of.isoformat(),
    }
    with path.open("x", encoding="utf-8") as stream:
        stream.write("# Local demo only. Do not commit or use for real finances.\n")
        stream.writelines(f"{key}={value}\n" for key, value in values.items())
    print("Created demo environment with independent credentials; secrets were not printed")


def money(amount: str | Decimal) -> dict[str, str]:
    return {"amount": format(Decimal(amount), ".2f"), "currency": RUB}


def month_offset(value: date, offset: int, day: int = 1) -> date:
    year, month = divmod(value.year * 12 + value.month - 1 + offset, 12)
    return date(year, month + 1, min(day, calendar.monthrange(year, month + 1)[1]))


def at(value: date) -> str:
    return f"{value.isoformat()}T12:00:00+04:00"


def post(api: ApiSession, path: str, body: dict[str, Any], key: str) -> Any:
    return api.request(
        "POST",
        f"/api/v1/{path}",
        body=body,
        csrf=True,
        idempotency_key=f"{PREFIX}:{key}",
        expected=201,
    )


def journal(api: ApiSession) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor = None
    while True:
        query = {"limit": "100"}
        if cursor is not None:
            query["cursor"] = cursor
        page = api.request("GET", f"/api/v1/transactions?{urlencode(query)}")
        items.extend(page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            return items


def fingerprint(api: ApiSession) -> str:
    # Ignore ordering and clocks. Include every posting, not only the visible total.
    data = sorted(journal(api), key=lambda item: item["id"])
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def authenticate(api: ApiSession, env: dict[str, str]) -> dict[str, Any]:
    if env["DEMO_EMAIL"] != "demo@example.test":
        raise RuntimeError("Refusing to seed an identity outside the designated demo account")
    payload = {
        "email": env["DEMO_EMAIL"],
        "password": env["DEMO_PASSWORD"],
        "base_currency": RUB,
        "locale": "ru-RU",
        "timezone": "Europe/Saratov",
    }
    try:
        profile = api.request("POST", "/api/v1/auth/bootstrap", body=payload, expected=201)
    except RuntimeError as error:
        if "returned 409" not in str(error):
            raise
        profile = api.request(
            "POST",
            "/api/v1/auth/login",
            body={"email": payload["email"], "password": payload["password"]},
        )
    if profile["email"] != env["DEMO_EMAIL"]:
        raise RuntimeError("Authenticated profile is not the demo account")
    return profile


def seed(api: ApiSession, today: date) -> dict[str, Any]:
    start = month_offset(today, -6)
    horizon = month_offset(today, 12, today.day)
    accounts = {}
    for key, name, kind, opening in (
        ("card", "ДЕМО · Зарплатная карта", "bank", "110000"),
        ("reserve", "ДЕМО · Финансовая подушка", "bank", "180000"),
        ("travel", "ДЕМО · Копилка на отпуск", "bank", "30000"),
        ("cash", "ДЕМО · Наличные", "cash", "9000"),
    ):
        accounts[key] = post(
            api,
            "accounts",
            {
                "name": name,
                "kind": kind,
                "currency": RUB,
                "opening_balance": money(opening),
                "opening_balance_occurred_at": at(start),
            },
            f"account:{key}",
        )

    groups = {}
    for index, name in enumerate(
        ("Дом и обязательные платежи", "Повседневная жизнь", "Развитие и отдых", "Доходы")
    ):
        groups[index] = post(api, "category-groups", {"name": name}, f"group:{index}")
    categories = {}
    for index, (key, name, kind, group, mandatory) in enumerate(
        (
            ("salary", "Зарплата", "income", 3, False),
            ("side", "Подработка и премии", "income", 3, False),
            ("rent", "Аренда жилья", "expense", 0, True),
            ("utility", "Коммунальные услуги", "expense", 0, True),
            ("internet", "Интернет и связь", "expense", 0, True),
            ("insurance", "Страхование", "expense", 0, True),
            ("groceries", "Продукты", "expense", 1, True),
            ("transport", "Транспорт", "expense", 1, True),
            ("health", "Здоровье", "expense", 1, True),
            ("cafe", "Кафе и рестораны", "expense", 1, False),
            ("subscription", "Подписки", "expense", 2, False),
            ("hobby", "Спорт и увлечения", "expense", 2, False),
            ("clothes", "Одежда", "expense", 1, False),
            ("travel", "Путешествия", "expense", 2, False),
            ("repair", "Непредвиденные расходы", "expense", 0, False),
        )
    ):
        categories[key] = post(
            api,
            "categories",
            {
                "name": name,
                "kind": kind,
                "group_id": groups[group]["id"],
                "is_mandatory": mandatory,
            },
            f"category:{index}",
        )
    tag = post(api, "tags", {"name": "Демонстрация"}, "tag")

    def transfer(
        key: str, source: str, destination: str, amount: str, when: date, description: str
    ) -> Any:
        return post(
            api,
            "transfers",
            {
                "source_account_id": source,
                "destination_account_id": destination,
                "money": money(amount),
                "occurred_at": at(when),
                "description": f"ДЕМО · {description}",
                "tag_ids": [tag["id"]],
            },
            key,
        )

    # Historical fixed payments are produced by the real worker with source=recurring.
    # They therefore do not also enter the irregular-expense baseline.
    existing = api.request("GET", "/api/v1/recurring-rules")
    existing_by_description = {item["operation"]["description"]: item for item in existing}
    rules = []
    for key, kind, amount, day, category in (
        ("salary-advance", "income", "73000", 5, "salary"),
        ("salary-balance", "income", "73000", 20, "salary"),
        ("side", "income", "18000", 12, "side"),
        ("rent", "expense", "35000", 3, "rent"),
        ("utility", "expense", "6500", 8, "utility"),
        ("internet", "expense", "1290", 10, "internet"),
        ("subscription", "expense", "799", 15, "subscription"),
        ("insurance", "expense", "1800", 16, "insurance"),
        ("travel-saving", "transfer", "8000", 25, None),
    ):
        description = (
            f"ДЕМО · {categories[category]['name'] if category else 'В копилку на отпуск'} · {key}"
        )
        if description in existing_by_description:
            rules.append(existing_by_description[description])
            continue
        operation = {
            "kind": kind,
            "account_id": accounts["card"]["id"],
            "money": money(amount),
            "description": description,
            "tag_ids": [tag["id"]],
        }
        if category:
            operation["category_id"] = categories[category]["id"]
        else:
            operation["destination_account_id"] = accounts["travel"]["id"]
        rules.append(
            post(
                api,
                "recurring-rules",
                {
                    "frequency": "monthly",
                    "starts_on": start.replace(day=day).isoformat(),
                    "local_time": "09:00:00",
                    "timezone": "Europe/Saratov",
                    "missing_day_policy": "last_day",
                    "catch_up_policy": "all",
                    "operation": operation,
                },
                f"rule:{key}",
            )
        )

    deposits = []
    for key, name, amount, opened, maturity, rate, source in (
        (
            "reserve",
            "ДЕМО · Подушка — вклад с капитализацией",
            "150000",
            start.replace(day=2),
            month_offset(start, 12, 2),
            "0.12",
            "reserve",
        ),
        (
            "short",
            "ДЕМО · Короткий вклад — скоро погашение",
            "75000",
            month_offset(today, -3, 10),
            today.replace(day=25),
            "0.10",
            "card",
        ),
    ):
        deposit = post(
            api,
            "deposits",
            {
                "name": name,
                "opening_balance": money("0"),
                "currency": RUB,
                "opened_on": opened.isoformat(),
                "matures_on": maturity.isoformat(),
                "rate_periods": [
                    {
                        "starts_on": opened.isoformat(),
                        "ends_on": maturity.isoformat(),
                        "nominal_rate": {"value": rate},
                    }
                ],
                "capitalization_frequency": "monthly_calendar_end",
                "day_count_convention": "actual_365_fixed",
                "rounding_policy": "half_even",
                "interest_rounding_frequency": "capitalization",
                "timezone": "Europe/Saratov",
                "cashflow_cutoff_time": "13:00:00",
                "cashflow_cutoff_inclusive": True,
                "early_close_rule": {"policy": "reprice", "nominal_rate": {"value": "0.01"}},
                "tax_rate": {"value": "0"},
                "automatic_interest": True,
            },
            f"deposit:{key}",
        )
        transfer(
            f"fund:{key}",
            accounts[source]["id"],
            deposit["principal_account_id"],
            amount,
            opened,
            f"Пополнение вклада: {name}",
        )
        deposits.append(deposit)

    for month_index in range(7):
        month = month_offset(start, month_index)
        for category, day, amount in (
            ("groceries", 2, Decimal("4200") + Decimal(month_index) * Decimal("75")),
            ("groceries", 9, Decimal("4850")),
            ("groceries", 16, Decimal("3900") + Decimal(month_index) * Decimal("50")),
            ("groceries", 23, Decimal("4600")),
            ("cafe", 6, Decimal("1750")),
            ("cafe", 13, Decimal("2350")),
            ("cafe", 20, Decimal("1900")),
            ("cafe", 27, Decimal("2200")),
            ("transport", 11, Decimal("4500")),
            ("health", 15, Decimal("1800")),
            ("hobby", 17, Decimal("4500")),
            ("clothes", 18, Decimal("6500")),
        ):
            when = month.replace(day=day)
            if when > today:
                continue
            post(
                api,
                "transactions/expense",
                {
                    "account_id": accounts["card"]["id"],
                    "category_id": categories[category]["id"],
                    "money": money(amount),
                    "occurred_at": at(when),
                    "description": f"ДЕМО · {categories[category]['name']} · {month:%B %Y}",
                    "tag_ids": [tag["id"]],
                },
                f"expense:{month_index}:{category}:{day}",
            )
        transfer(
            f"cash:{month_index}",
            accounts["card"]["id"],
            accounts["cash"]["id"],
            "6000",
            month.replace(day=1),
            "Наличные на месяц",
        )
        post(
            api,
            "transactions/expense",
            {
                "account_id": accounts["cash"]["id"],
                "category_id": categories["transport"]["id"],
                "money": money("3500"),
                "occurred_at": at(month.replace(day=7)),
                "description": "ДЕМО · Такси и небольшие покупки наличными",
                "tag_ids": [tag["id"]],
            },
            f"cash-expense:{month_index}",
        )

    for key, category, amount, when, description in (
        (
            "holiday",
            "travel",
            "85000",
            month_offset(today, -1, 12),
            "Отпуск — заметное изменение расходов",
        ),
        ("repair", "repair", "24000", today.replace(day=10), "Незапланированный ремонт техники"),
    ):
        post(
            api,
            "transactions/expense",
            {
                "account_id": accounts["card"]["id"],
                "category_id": categories[category]["id"],
                "money": money(amount),
                "occurred_at": at(when),
                "description": f"ДЕМО · {description}",
                "tag_ids": [tag["id"]],
            },
            f"event:{key}",
        )

    original = post(
        api,
        "transactions/expense",
        {
            "account_id": accounts["card"]["id"],
            "category_id": categories["cafe"]["id"],
            "money": money("2400"),
            "occurred_at": at(today.replace(day=18)),
            "description": "ДЕМО · Чек кафе до исправления",
            "tag_ids": [tag["id"]],
        },
        "correction:original",
    )
    post(
        api,
        f"transactions/{original['id']}/correction",
        {
            "kind": "expense",
            "account_id": accounts["card"]["id"],
            "category_id": categories["cafe"]["id"],
            "money": money("2200"),
            "occurred_at": at(today.replace(day=18)),
            "description": "ДЕМО · Чек кафе исправлен по квитанции",
            "reason": "Демонстрация исправления с сохранением истории",
            "tag_ids": [tag["id"]],
        },
        "correction:replacement",
    )

    goals = []
    for key, name, target, saved, deadline, priority, account in (
        (
            "reserve",
            "Подушка безопасности — 300 000 ₽",
            "300000",
            "185000",
            month_offset(today, 3, 31),
            1,
            "reserve",
        ),
        (
            "travel",
            "Отпуск у моря — летом",
            "180000",
            "45000",
            month_offset(today, 8, 30),
            2,
            "travel",
        ),
        (
            "laptop",
            "Новый ноутбук — амбициозный срок",
            "240000",
            "20000",
            month_offset(today, 2, 31),
            3,
            "card",
        ),
        (
            "home",
            "Первоначальный взнос — цель с дефицитом",
            "2500000",
            "150000",
            horizon,
            4,
            "reserve",
        ),
        (
            "study",
            "Курс повышения квалификации — накоплено",
            "90000",
            "90000",
            month_offset(today, 1, 30),
            5,
            "reserve",
        ),
    ):
        goals.append(
            post(
                api,
                "goals",
                {
                    "name": name,
                    "target": money(target),
                    "saved_amount": money(saved),
                    "target_date": deadline.isoformat(),
                    "priority": priority,
                    "linked_account_id": accounts[account]["id"],
                },
                f"goal:{key}",
            )
        )

    scenarios = []
    for key, name, income, expense, inflation, interest, one_time in (
        ("baseline", "01 · Базовый план — текущие привычки", "0", "0", "0", "0", []),
        ("economy", "02 · Экономия — расходы ниже на 15%", "0", "-0.15", "0", "0", []),
        ("career", "03 · Рост дохода на 20%, расходов на 5%", "0.20", "0.05", "0.06", "0", []),
        ("stress", "04 · Стресс — доход −20%, расходы +15%", "-0.20", "0.15", "0.10", "0", []),
        (
            "bonus",
            "05 · Премия 180 000 ₽ в подушку",
            "0",
            "0",
            "0",
            "0",
            [(month_offset(today, 1, 15), "180000", "Вымышленная годовая премия")],
        ),
        (
            "purchase",
            "06 · Покупка техники 220 000 ₽",
            "0",
            "0",
            "0",
            "0",
            [(month_offset(today, 1, 20), "-220000", "Вымышленная крупная покупка")],
        ),
    ):
        scenarios.append(
            post(
                api,
                "forecast-scenarios",
                {
                    "name": name,
                    "currency": RUB,
                    "horizon": horizon.isoformat(),
                    "income_change": {"value": income},
                    "expense_change": {"value": expense},
                    "annual_inflation": {"value": inflation},
                    "annual_interest": {"value": interest},
                    "one_time_cashflows": [
                        {
                            "occurs_on": when.isoformat(),
                            "account_id": accounts["card"]["id"],
                            "money": money(amount),
                            "description": description,
                        }
                        for when, amount, description in one_time
                    ],
                },
                f"scenario:{key}",
            )
        )
    return {
        "accounts": accounts,
        "deposits": deposits,
        "goals": goals,
        "scenarios": scenarios,
        "horizon": horizon.isoformat(),
        "as_of": today.isoformat(),
    }


def wait_for_jobs(api: ApiSession) -> None:
    deadline = time.monotonic() + 180
    while True:
        rules = api.request("GET", "/api/v1/recurring-rules")
        if all(
            datetime.fromisoformat(rule["next_occurrence_at"]) > datetime.now(UTC) for rule in rules
        ):
            # Claimed jobs can finish after next_occurrence has advanced.
            previous = fingerprint(api)
            time.sleep(3)
            if fingerprint(api) == previous:
                if api.request("GET", "/api/v1/recurring-jobs/dead-letter"):
                    raise RuntimeError("Demo worker has a dead-letter job")
                return
        if time.monotonic() >= deadline:
            raise RuntimeError("Demo recurring history has not finished materializing")
        time.sleep(2)


def write_showcase(
    output: Path, manifest: dict[str, Any], comparison: dict[str, Any], advice: list[dict[str, Any]]
) -> None:
    lines = [
        "# Демонстрация Financial Analytics",
        "",
        "Все данные, ставки и сценарии вымышлены.",
        "",
        "Открыть: http://127.0.0.1:4174 · логин: demo@example.test.",
        "Пароль находится в локальном `.env.demo`; в отчёт он не включён.",
        "",
        f"История подготовлена на {manifest['as_of']}, горизонт — {manifest['horizon']}.",
        "",
        "## Маршрут показа (7–10 минут)",
        "",
        "1. Обзор: капитал, денежный поток и последние операции.",
        "2. Аналитика: сравнить месяцы, показать категории и обязательные расходы.",
        "3. Операции: отфильтровать «ДЕМО», найти отпуск, ремонт и исправленный чек кафе.",
        "4. Регулярные: две части зарплаты, аренда, связь и перевод в копилку.",
        "5. Вклады: капитализация, пополнение и близкое погашение короткого вклада.",
        "6. Цели: достигнутая, достижимая и проблемная цели; порядок приоритетов и взносы.",
        "7. Прогноз: выбрать несколько сохранённых сценариев и сравнить таблицу ниже.",
        "8. Советник: задать вопрос о приоритетной цели, показать основания и ограничения.",
        "",
        "## Сравнение из детерминированного API",
        "",
        "| Сценарий | Капитал на горизонте, ₽ | Нижняя граница, ₽ | Верхняя граница, ₽ |",
        "|---|---:|---:|---:|",
    ]
    for item in comparison["items"]:
        forecast = item["forecast"]
        lines.append(
            f"| {item['scenario_name']} | {forecast['final_total']['amount']} "
            f"| {forecast['uncertainty_low']['amount']} "
            f"| {forecast['uncertainty_high']['amount']} |"
        )
    lines.extend(
        [
            "",
            "## Цели в базовом плане",
            "",
            "| Цель | Статус | Требуемый взнос в месяц, ₽ | Дефицит к сроку, ₽ |",
            "|---|---|---:|---:|",
        ]
    )
    for goal in comparison["items"][0]["goal_plan"]["goals"]:
        lines.append(
            f"| {goal['name']} | {goal['status']} "
            f"| {goal['required_monthly_contribution']['amount']} | {goal['shortfall']['amount']} |"
        )
    lines.extend(["", "Суммы и статусы выше скопированы из API. LLM их не рассчитывает.", ""])
    for case in advice:
        result = case["response"]
        lines.extend(
            [
                f"## Советник: {case['name']}",
                "",
                f"Статус: {result['status']}; время: {case['elapsed_seconds']} с.",
                "",
            ]
        )
        if result["advice"] is None:
            lines.extend([f"Ответ не получен: {result['error_code']}.", ""])
            continue
        content = result["advice"]
        lines.extend([content["summary"], "", "Наблюдения:", ""])
        lines.extend(
            f"- {item['text']} ({', '.join(item['evidence_ids'])})"
            for item in content["observations"]
        )
        lines.extend(["", "Варианты для рассмотрения:", ""])
        lines.extend(f"- {item}" for item in content["suggestions"])
        lines.extend(["", content["disclaimer"], ""])
    output.joinpath("SHOWCASE.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials-file", type=Path, default=ROOT / ".env.demo")
    parser.add_argument("--prepare-environment", action="store_true")
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--skip-advice", action="store_true")
    args = parser.parse_args()
    if args.prepare_environment:
        if args.as_of is None:
            parser.error("--prepare-environment requires an explicit --as-of date")
        prepare_environment(args.credentials_file, args.as_of)
        return
    env = read_environment(args.credentials_file)
    today = date.fromisoformat(env["DEMO_AS_OF"])
    api = ApiSession("http://127.0.0.1:8002")
    api.request("GET", "/health/ready")
    authenticate(api, env)
    output = ROOT / "generated-reports" / "demo"
    output.mkdir(parents=True, exist_ok=True)
    previous = fingerprint(api) if output.joinpath("manifest.json").exists() else None
    print(json.dumps({"event": "seeding", "synthetic_only": True}), flush=True)
    manifest = seed(api, today)
    wait_for_jobs(api)
    before = fingerprint(api)
    if previous is not None and previous != before:
        raise RuntimeError("Repeated demo seeding changed the financial journal")
    manifest["transaction_count"] = len(journal(api))
    comparison = api.request(
        "POST",
        "/api/v1/forecasts/compare",
        body={
            "currency": RUB,
            "baseline_horizon": manifest["horizon"],
            "scenario_ids": [item["id"] for item in manifest["scenarios"]],
        },
    )
    print(
        json.dumps(
            {
                "event": "seeded",
                "transactions": manifest["transaction_count"],
                "goals": len(manifest["goals"]),
                "scenarios": len(manifest["scenarios"]),
            }
        ),
        flush=True,
    )
    advice = []
    if not args.skip_advice:
        cases = (
            (
                "Подушка и приоритеты",
                None,
                "Какой главный риск для цели первого приоритета "
                "и что учитывать при выборе между целями?",
            ),
            (
                "Экономия расходов на 15%",
                manifest["scenarios"][1]["id"],
                "Как снижение расходов меняет достижимость целей первого и второго приоритетов?",
            ),
            (
                "Стресс и амбициозные цели",
                manifest["scenarios"][3]["id"],
                "Какие риски есть у целей третьего и четвёртого приоритетов в стрессовом сценарии?",
            ),
        )
        for index, (name, scenario_id, question) in enumerate(cases, start=1):
            print(json.dumps({"event": "advice_started", "case": index}), flush=True)
            payload = {"currency": RUB, "question": question, "allow_external_user_text": False}
            payload["scenario_id" if scenario_id else "through"] = (
                scenario_id or manifest["horizon"]
            )
            started = time.monotonic()
            result = api.request("POST", "/api/v1/advice", body=payload)
            case = {
                "name": name,
                "elapsed_seconds": round(time.monotonic() - started, 2),
                "response": result,
            }
            advice.append(case)
            output.joinpath(f"advice-{index}.json").write_text(
                json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(
                json.dumps(
                    {
                        "event": "advice_finished",
                        "case": index,
                        "status": result["status"],
                        "error_code": result["error_code"],
                        "seconds": case["elapsed_seconds"],
                    }
                ),
                flush=True,
            )
            if result["advice"] is not None:
                known = set(result["evidence_ids"])
                if not all(
                    set(item["evidence_ids"]) <= known for item in result["advice"]["observations"]
                ):
                    raise RuntimeError("Advice referenced unknown evidence")
            if fingerprint(api) != before:
                raise RuntimeError(
                    "Financial journal changed while comparing scenarios or requesting advice"
                )
    if fingerprint(api) != before:
        raise RuntimeError("Read/compute requests changed the financial journal")
    output.joinpath("manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    output.joinpath("comparison.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_showcase(output, manifest, comparison, advice)
    print(
        json.dumps(
            {
                "event": "verified",
                "ledger_unchanged_by_queries": True,
                "idempotent_reseed": previous is not None,
                "available_advice": sum(
                    case["response"]["status"] == "available" for case in advice
                ),
            }
        ),
        flush=True,
    )
    if advice and any(case["response"]["status"] != "available" for case in advice):
        raise SystemExit("One or more advice cases are unavailable; inspect the generated report")


if __name__ == "__main__":
    main()
