import assert from "node:assert/strict";

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

test("existing user logs in and reaches the dashboard", async ({ page }) => {
  await mockApi(page, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/v1/auth/login") {
      await route.fulfill({ json: profile });
    } else if (path === "/api/v1/accounts") {
      await route.fulfill({ json: [account] });
    } else {
      await route.fulfill({ status: 401, json: problem("invalid_session") });
    }
  });

  await page.goto("/login");
  await page.getByLabel("Email").fill("owner@example.com");
  await page.getByLabel("Пароль").fill("correct horse battery staple");
  await page.getByLabel("Пароль").press("Enter");

  await expect(page.getByRole("heading", { name: "Добро пожаловать." })).toBeVisible();
  await expect(page.getByText("Основная карта").first()).toBeVisible();
  await expect(page).toHaveURL(/\/app\/dashboard$/u);
});

test("first run creates master and an exact opening balance at 360px", async ({
  page,
  context,
}) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await context.addCookies([{ name: "fa_csrf", value: "e2e-csrf", url: "http://127.0.0.1:4173" }]);
  let bootstrapBody: unknown;
  let accountBody: unknown;
  let accountHeaders: Record<string, string> = {};

  await mockApi(page, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/v1/auth/bootstrap") {
      bootstrapBody = request.postDataJSON();
      await route.fulfill({ status: 201, json: profile });
    } else if (path === "/api/v1/accounts" && request.method() === "POST") {
      accountBody = request.postDataJSON();
      accountHeaders = request.headers();
      await route.fulfill({ status: 201, json: account });
    } else {
      await route.fulfill({ status: 401, json: problem("invalid_session") });
    }
  });

  await page.goto("/start");
  await expectNoHorizontalOverflow(page);
  await page.getByLabel("Email").fill("owner@example.com");
  await page.getByLabel("Пароль", { exact: true }).fill("correct horse battery staple");
  await page.getByLabel("Повторите пароль").fill("correct horse battery staple");
  await page.getByLabel("Повторите пароль").press("Enter");

  await page.getByLabel("Основная валюта").selectOption("RUB");
  await page.getByLabel("Формат чисел и дат").selectOption("ru-RU");
  await page.getByLabel("Часовой пояс").fill("Europe/Saratov");
  await page.getByRole("button", { name: "Создать профиль" }).click();

  await expect(page.getByRole("heading", { name: "С чего начнём?" })).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await page.getByLabel("Название счёта").fill("Основная карта");
  await page.getByLabel("Начальный остаток").fill("125 000,50");
  await page.getByLabel("Дата остатка").fill("2026-10-14");
  await page.getByLabel("Дата остатка").press("Enter");

  await expect(page.getByRole("heading", { name: "Добро пожаловать." })).toBeVisible();
  await expectNoHorizontalOverflow(page);
  assert.deepStrictEqual(bootstrapBody, {
    email: "owner@example.com",
    password: "correct horse battery staple",
    base_currency: "RUB",
    locale: "ru-RU",
    timezone: "Europe/Saratov",
  });
  assert.deepStrictEqual(accountBody, {
    name: "Основная карта",
    kind: "bank",
    currency: "RUB",
    opening_balance: { amount: "125000.50", currency: "RUB" },
    opening_balance_occurred_at: "2026-10-14T08:00:00.000Z",
  });
  expect(
    typeof (accountBody as { opening_balance: { amount: unknown } }).opening_balance.amount,
  ).toBe("string");
  expect(accountHeaders["x-csrf-token"]).toBe("e2e-csrf");
});

async function mockApi(page: Page, handler: (route: Route) => Promise<void>): Promise<void> {
  await page.route(`${apiOrigin}/**`, handler);
}

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      ),
    )
    .toBe(true);
}

function problem(code: string) {
  return {
    type: "about:blank",
    title: "Unauthorized",
    status: 401,
    detail: "Session is not available.",
    code,
    instance: "/api/v1/profile",
    request_id: "request",
    correlation_id: "correlation",
  };
}
