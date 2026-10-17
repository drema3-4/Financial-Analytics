import { expect, test } from "@playwright/test";
import type { Page, Route } from "playwright";

const apiOrigin = "http://127.0.0.1:8000";
const profile = {
  id: "11111111-1111-4111-8111-111111111111",
  email: "owner@example.com",
  base_currency: "RUB",
  locale: "ru-RU",
  timezone: "Europe/Saratov",
  status: "active",
  is_master: true,
  is_admin: false,
  email_verified: true,
  created_at: "2026-10-14T08:00:00Z",
};
const account = {
  id: "22222222-2222-4222-8222-222222222222",
  name: "Основная карта",
  kind: "bank",
  currency: "RUB",
  balance: { amount: "125000.50", currency: "RUB" },
  archived: false,
  version: 1,
};

const screens = [
  ["accounts", "Счета и категории"],
  ["transactions", "Журнал операций"],
  ["recurring", "Регулярные операции"],
  ["deposits", "Вклады"],
  ["analytics", "Аналитика"],
  ["forecast", "Прогноз"],
  ["goals", "Финансовые цели"],
  ["advice", "Финансовый советник"],
] as const;

for (const [path, heading] of screens) {
  test(`${path} module has a responsive accessible happy path`, async ({ page }) => {
    await mockFinanceApi(page);
    await page.goto(`/app/${path}`);
    await expect(page.getByRole("heading", { name: heading, level: 1 })).toBeVisible();
    await expect(page.locator("main#main-content")).toBeVisible();
    await expect
      .poll(() =>
        page.evaluate(
          () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
        ),
      )
      .toBe(true);
  });
}

test("transaction API failure is announced and recoverable", async ({ page }) => {
  await mockFinanceApi(page, "/api/v1/transactions");
  await page.goto("/app/transactions");
  await expect(page.getByRole("alert")).toContainText("Не удалось");
  await expect(page.getByRole("button", { name: "Попробовать снова" })).toBeEnabled();
});

test("deposit form rejects an impossible term without a mutation", async ({ page }) => {
  await mockFinanceApi(page);
  await page.goto("/app/deposits");
  await page.getByRole("button", { name: "Добавить вклад" }).click();
  await page.getByLabel("Открытие").fill("2027-01-01");
  await page.getByLabel("Окончание").fill("2026-01-01");
  await page.getByRole("button", { name: "Создать и построить график" }).click();
  await expect(page.getByRole("alert")).toContainText("позже открытия");
});

test("advice stays explicitly unavailable when provider is disabled", async ({ page }) => {
  await mockFinanceApi(page);
  await page.goto("/app/advice");
  await expect(page.getByRole("heading", { name: "Советник недоступен" })).toBeVisible();
  await expect(page.getByText("Финансовые функции продолжают работать без LLM")).toBeVisible();
});

async function mockFinanceApi(page: Page, failingPath?: string) {
  await page.route(`${apiOrigin}/**`, async (route: Route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === failingPath) {
      await route.fulfill({ status: 422, json: problem() });
      return;
    }
    if (path === "/api/v1/profile") {
      await route.fulfill({ json: profile });
      return;
    }
    if (path === "/api/v1/accounts") {
      await route.fulfill({ json: [account] });
      return;
    }
    if (
      [
        "/api/v1/categories",
        "/api/v1/category-groups",
        "/api/v1/transactions",
        "/api/v1/recurring-rules",
        "/api/v1/deposits",
        "/api/v1/forecast-scenarios",
        "/api/v1/financial-goals",
      ].includes(path)
    ) {
      await route.fulfill({
        json: path === "/api/v1/transactions" ? { items: [], next_cursor: null } : [],
      });
      return;
    }
    if (path === "/api/v1/reports/financial") {
      await route.fulfill({ json: report });
      return;
    }
    if (path === "/api/v1/forecasts") {
      await route.fulfill({ json: forecast });
      return;
    }
    if (path === "/api/v1/advice/status") {
      await route.fulfill({
        json: {
          status: "disabled",
          provider: "disabled",
          model: null,
          endpoint_scope: "aggregate_only",
          capabilities: { json_schema: false, system_messages: false, non_thinking: false },
          prompt_version: "v1",
          context_version: "v1",
        },
      });
      return;
    }
    await route.fulfill({ status: 404, json: problem() });
  });
}

function problem() {
  return {
    type: "about:blank",
    title: "Invalid request",
    status: 422,
    detail: "Request cannot be processed.",
    code: "invalid_request",
    instance: "/api/v1/test",
    request_id: "request",
    correlation_id: "correlation",
  };
}
const report = {
  period: {
    start: "2026-10-01",
    end: "2026-10-16",
    timezone: "Europe/Saratov",
    granularity: "month",
    start_at: "2026-09-30T20:00:00Z",
    end_at: "2026-10-16T20:00:00Z",
  },
  data_through: "2026-10-16T08:00:00Z",
  currency_mode: "single",
  combined_currency: "RUB",
  totals: [],
  buckets: [],
  comparison: {
    current_start: "2026-10-01",
    current_end: "2026-10-16",
    previous_start: "2026-09-15",
    previous_end: "2026-09-30",
    current_is_complete: false,
    currencies: [],
  },
  anomaly_policy: {
    version: "v1",
    baseline_buckets: 3,
    minimum_buckets: 3,
    baseline_statistic: "median",
    threshold_formula: "fixed",
    incomplete_buckets_evaluated: false,
  },
  anomalies: [],
};
const forecast = {
  disclaimer: "Прогноз не является гарантией.",
  forecast: {
    snapshot_id: "snapshot",
    algorithm_version: "v1",
    assumptions: {
      version: "v1",
      horizon: "2027-10-16",
      income_change: "0",
      expense_change: "0",
      annual_inflation: "0",
      annual_interest: "0",
      one_time_cashflows: [],
    },
    uncertainty_method: "range",
    uncertainty_explanation: "Диапазон основан на истории.",
    baseline_expenses: [],
    warnings: [],
    timeline: [],
    accounts: [],
    opening_total: { amount: "100", currency: "RUB" },
    final_total: { amount: "120", currency: "RUB" },
    uncertainty_low: { amount: "90", currency: "RUB" },
    uncertainty_high: { amount: "140", currency: "RUB" },
  },
  goal_plan: {
    allocation_version: "v1",
    allocation_explanation: "По приоритету.",
    forecast_snapshot_id: "snapshot",
    currency: "RUB",
    warnings: [],
    goals: [],
  },
};
