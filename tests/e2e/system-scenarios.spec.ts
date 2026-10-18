import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import process from "node:process";

import { expect, test } from "@playwright/test";
import type { APIResponse, Page, Response } from "@playwright/test";

interface MoneyResponse {
  amount: string;
  currency: string;
}

interface AccountResponse {
  id: string;
  balance: MoneyResponse;
}

interface PostingResponse {
  account_id: string;
  money: MoneyResponse;
}

interface TransactionResponse {
  id: string;
  postings: PostingResponse[];
}

interface TransactionPageResponse {
  items: TransactionResponse[];
}

interface EvidenceResponse {
  transaction_ids: string[];
}

interface MoneyMetricResponse {
  value: MoneyResponse;
  evidence: EvidenceResponse;
}

interface FinancialReportResponse {
  totals: {
    currency: string;
    expense: MoneyMetricResponse;
    cash_flow: MoneyMetricResponse;
    closing_net_worth: MoneyMetricResponse;
  }[];
}

interface ForecastRunResponse {
  forecast: { opening_total: MoneyResponse };
}

const apiOrigin = "http://127.0.0.1:8000";
const fixedNow = new Date("2026-10-16T20:00:00Z");

test.describe("SPEC.md system scenarios", () => {
  test.skip(process.env.E2E_SYSTEM !== "1", "requires the real API and an isolated *_e2e database");

  test.beforeEach(async ({ page }) => {
    const reset = spawnSync("poetry", ["run", "python", "scripts/reset_e2e_database.py"], {
      cwd: process.cwd(),
      env: { ...process.env, APP_ENV: "test" },
      stdio: "pipe",
    });
    if (reset.status !== 0) {
      throw new Error(
        `E2E database reset failed with status ${String(reset.status)}: ${reset.stderr.toString()}`,
      );
    }
    await page.clock.install({ time: fixedNow });
  });

  test("1. first run creates the master profile, account, and exact opening posting", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 360, height: 800 });
    await page.goto("/start");
    await page.getByLabel("Email").fill("owner@example.test");
    await page.getByLabel("Пароль", { exact: true }).fill("correct horse battery staple");
    await page.getByLabel("Повторите пароль").fill("correct horse battery staple");
    await page.getByRole("button", { name: "Продолжить" }).click();
    await page.getByLabel("Основная валюта").selectOption("RUB");
    await page.getByLabel("Формат чисел и дат").selectOption("ru-RU");
    await page.getByLabel("Часовой пояс").fill("Europe/Saratov");
    const bootstrapResponse = page.waitForResponse(
      (response) => response.url().endsWith("/api/v1/auth/bootstrap") && response.status() === 201,
    );
    await page.getByRole("button", { name: "Создать профиль" }).click();
    await installDeterministicSessionCookies(page, await bootstrapResponse);
    await page.getByLabel("Название счёта").fill("Основная карта");
    await page.getByLabel("Начальный остаток").fill("125 000,50");
    await page.getByLabel("Дата остатка").fill("2026-10-16");
    await page.getByRole("button", { name: "Создать счёт и открыть обзор" }).click();

    await expect(page.getByRole("heading", { name: "Финансовый обзор" })).toBeVisible();
    const accounts = await getJson<AccountResponse[]>(page, "/api/v1/accounts");
    expect(accounts).toHaveLength(1);
    expect(required(accounts[0], "opening account").balance.amount).toBe("125000.50");
    const transactions = await getJson<TransactionPageResponse>(
      page,
      "/api/v1/transactions?limit=20",
    );
    expect(transactions.items).toHaveLength(1);
    expect(sumPostings(required(transactions.items[0], "opening transaction"))).toBe("0.00");
  });

  test("2. expense reconciles UI, API postings, analytics, and forecast", async ({ page }) => {
    const setup = await bootstrapOwner(page, [
      { name: "Основная карта", kind: "bank", opening: "1000.00" },
    ]);

    await page.goto("/app/transactions");
    await page.getByRole("button", { name: "Новая операция" }).click();
    await page.getByLabel("Категория").fill("Продукты");
    await page.getByLabel("Сумма").fill("125,25");
    await page.getByLabel("Дата").fill("2026-10-16");
    await page.getByLabel("Комментарий").fill("продукты");
    const createdResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/v1/transactions/expense") && response.status() === 201,
    );
    await page.getByRole("button", { name: "Провести" }).click();
    const created = await responseJson<TransactionResponse>(await createdResponse);
    await expect(page.getByRole("cell", { name: /продукты Расход · manual/ })).toBeVisible();

    const transaction = await getJson<TransactionResponse>(
      page,
      `/api/v1/transactions/${created.id}`,
    );
    expect(transaction.id).toBe(created.id);
    expect(transaction.postings.map((item) => item.money.amount).sort()).toEqual([
      "-125.25",
      "125.25",
    ]);
    expect(sumPostings(transaction)).toBe("0.00");

    const report = await getJson<FinancialReportResponse>(
      page,
      "/api/v1/reports/financial?period_start=2026-10-01&period_end=2026-11-01&granularity=month",
    );
    const rub = required(
      report.totals.find((item) => item.currency === "RUB"),
      "RUB report total",
    );
    expect(rub.expense.value.amount).toBe("125.25");
    expect(rub.closing_net_worth.value.amount).toBe("874.75");
    expect(rub.cash_flow.evidence.transaction_ids).toContain(created.id);

    const forecast = await getJson<ForecastRunResponse>(
      page,
      "/api/v1/forecasts?currency=RUB&through=2027-10-16",
    );
    expect(forecast.forecast.opening_total.amount).toBe("874.75");
    expect(required(setup.accounts[0], "expense account").id).toBe(
      required(transaction.postings[0], "expense posting").account_id,
    );
  });

  test("3. monthly subscription previews and repeated worker delivery stays single", async ({
    page,
  }) => {
    await bootstrapOwner(page, [{ name: "Карта", kind: "bank", opening: "1000.00" }]);
    await page.goto("/app/recurring");
    await page.getByRole("button", { name: "Новое правило" }).click();
    await page.getByLabel("Периодичность").selectOption("monthly");
    await page.getByLabel("Категория").fill("Подписки");
    await page.getByLabel("Сумма").fill("99,00");
    await page.getByLabel("Описание").fill("Месячная подписка");
    await page.getByLabel("Начало").fill("2026-10-16");
    await page.getByLabel("Локальное время").fill("09:00");
    await page.getByRole("button", { name: "Предпросмотр дат" }).click();
    await expect(page.locator(".preview-list li")).toHaveCount(6);
    await page.getByRole("button", { name: "Сохранить правило" }).click();
    await expect(page.getByRole("cell", { name: "Месячная подписка" })).toBeVisible();

    runWorkerOnce();
    runWorkerOnce();
    const transactions = await getJson<TransactionPageResponse>(
      page,
      "/api/v1/transactions?search=%D0%9C%D0%B5%D1%81%D1%8F%D1%87%D0%BD%D0%B0%D1%8F%20%D0%BF%D0%BE%D0%B4%D0%BF%D0%B8%D1%81%D0%BA%D0%B0&limit=20",
    );
    expect(transactions.items).toHaveLength(1);
    expect(sumPostings(required(transactions.items[0], "recurring transaction"))).toBe("0.00");
  });

  test("4. capitalized deposit with top-up exposes schedule and yield", async ({ page }) => {
    const setup = await bootstrapOwner(page, [
      { name: "Текущий счёт", kind: "bank", opening: "500.00" },
    ]);
    await page.goto("/app/deposits");
    await page.getByRole("button", { name: "Добавить вклад" }).click();
    await page.getByLabel("Название вклада").fill("Резерв с капитализацией");
    await page.getByLabel("Начальная сумма").fill("1000,00");
    await page.getByLabel("Открытие").fill("2026-09-01");
    await page.getByLabel("Окончание").fill("2027-09-01");
    await page.getByLabel("Номинальная ставка, %").fill("10");
    await page.getByLabel("Капитализация").selectOption("monthly_calendar_end");
    await page.getByRole("button", { name: "Создать вклад", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Оценка вклада" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Список вкладов" })).toContainText("10%");
    const deposits = await getJson<{ id: string; principal_account_id: string }[]>(
      page,
      "/api/v1/deposits",
    );
    const deposit = required(deposits[0], "new deposit");
    const valuation = await getJson<{
      ledger_balance: MoneyResponse;
      earned_interest: MoneyResponse;
    }>(page, `/api/v1/deposits/${deposit.id}/valuation?as_of=2026-10-17`);
    expect(valuation.ledger_balance.amount).toBe("1008.22");
    expect(valuation.earned_interest.amount).toBe("12.64");
    await page.goto("/app/transactions");
    await page.getByRole("button", { name: "Новая операция" }).click();
    await page.getByLabel("Тип операции").selectOption("transfer");
    await page
      .getByLabel("Со счёта")
      .selectOption(required(setup.accounts[0], "counterparty account").id);
    await page.getByLabel("На счёт").selectOption(deposit.principal_account_id);
    await page.getByLabel("Сумма").fill("100,00");
    await page.getByLabel("Дата").fill("2026-10-16");
    await page.getByLabel("Комментарий").fill("Пополнение вклада");
    await page.getByRole("button", { name: "Провести" }).click();
    await expect(page.getByRole("dialog")).not.toBeVisible();
    const bank = await getJson<AccountResponse>(
      page,
      `/api/v1/accounts/${required(setup.accounts[0], "bank").id}`,
    );
    expect(bank.balance.amount).toBe("400.00");
    await page.goto("/app/deposits");
    await page.getByRole("button", { name: /Резерв с капитализацией/ }).click();
    await expect(page.getByText("Эффективная доходность", { exact: true })).toBeVisible();
    await expect(page.getByRole("table", { name: "График начислений" })).toBeVisible();
  });

  test("5. changed forecast scenario is recalculated and compared", async ({ page }) => {
    await bootstrapOwner(page, [{ name: "Счёт", kind: "bank", opening: "1000.00" }]);
    await page.goto("/app/forecast");
    await page.getByRole("button", { name: "Новый сценарий" }).click();
    const scenarioDialog = page.getByRole("dialog", { name: "Редактор сценария" });
    await scenarioDialog.getByLabel("Название").fill("Рост дохода");
    await scenarioDialog.getByLabel("Горизонт").fill("2027-10-16");
    await scenarioDialog.getByLabel("Изменение дохода, %").fill("10");
    await scenarioDialog.getByRole("button", { name: "Сохранить сценарий" }).click();
    await expect(page.getByText("Не гарантия")).toBeVisible();
    await page.getByLabel("Рост дохода").check();
    await expect(page.getByRole("table", { name: "Сравнение сценариев" })).toContainText(
      "Рост дохода",
    );
  });

  test("6. goal shows required contribution and numeric feasibility actions", async ({ page }) => {
    await bootstrapOwner(page, [{ name: "Накопления", kind: "bank", opening: "10000.00" }]);
    await page.goto("/app/goals");
    await page.getByRole("button", { name: "Новая цель" }).click();
    await page.getByLabel("Название цели").fill("Резерв");
    await page.getByLabel("Целевая сумма").fill("100000,00");
    await page.getByLabel("Уже накоплено").fill("10000,00");
    await page.getByLabel("Срок").fill("2027-10-16");
    await page.getByRole("button", { name: "Создать цель" }).click();
    const plan = page.getByRole("table", { name: "Расчёт достижимости целей" });
    await expect(plan).toContainText("Резерв");
    await expect(plan).toContainText("Нужно в месяц");
    await expect(plan).toContainText("увеличить взнос или срок");
  });

  test("7. advice cites shown metrics and cannot mutate the ledger", async ({ page }) => {
    await bootstrapOwner(page, [{ name: "Счёт", kind: "bank", opening: "1000.00" }]);
    const before = await getJson<TransactionPageResponse>(page, "/api/v1/transactions?limit=100");
    await page.goto("/app/advice");
    await page.getByLabel("Вопрос (необязательно)").fill("Объясни мой прогноз");
    await page.getByRole("button", { name: "Получить варианты и объяснение" }).click();
    await expect(page.getByRole("heading", { name: "Наблюдения и варианты" })).toBeVisible();
    await expect(page.getByRole("link", { name: "[forecast:result]" })).toBeVisible();
    await expect(page.getByText("Советник ничего не изменил.")).toBeVisible();
    const after = await getJson<TransactionPageResponse>(page, "/api/v1/transactions?limit=100");
    expect(after.items.map((item) => item.id)).toEqual(before.items.map((item) => item.id));
  });

  test("8. user can edit and delete operations, accounts, deposits and goals through the real UI", async ({
    page,
  }) => {
    test.setTimeout(60000);
    await bootstrapOwner(page, [
      { name: "Карта для исправлений", kind: "bank", opening: "1000.00" },
    ]);
    await page.goto("/app/transactions");
    await page.getByRole("button", { name: "Новая операция" }).click();
    await page.getByLabel("Категория").fill("Новая категория в форме");
    await page.getByLabel("Сумма").fill("100,00");
    await page.getByLabel("Комментарий").fill("Покупка для исправления");
    await page.getByRole("button", { name: "Провести", exact: true }).click();
    let row = page.getByRole("row").filter({ hasText: "Покупка для исправления" });
    await row.getByRole("button", { name: "Изменить", exact: true }).click();
    await page.getByLabel("Сумма").fill("125,25");
    await page.getByLabel("Комментарий").fill("Исправленная покупка");
    await page.getByRole("button", { name: "Сохранить исправление" }).click();
    row = page.getByRole("row").filter({ hasText: "Исправленная покупка" });
    await expect(row).toContainText("125,25");
    await row.getByRole("button", { name: "Удалить", exact: true }).click();
    await page.getByRole("button", { name: "Удалить операцию (сторнировать)" }).click();
    await expect(row).toContainText("Отменена");

    await page.goto("/app/analytics");
    await expect(page.getByRole("heading", { name: "Итоги · RUB" })).toBeVisible();
    await expect(page.getByRole("alert")).toHaveCount(0);

    await page.goto("/app/goals");
    await page.getByRole("button", { name: "Новая цель" }).click();
    await page.getByLabel("Название цели").fill("На отпуск");
    await page.getByLabel("Целевая сумма").fill("10000,00");
    await page.getByRole("button", { name: "Создать цель", exact: true }).click();
    const goalsTable = page.getByRole("table", { name: "Финансовые цели", exact: true });
    await goalsTable.getByRole("button", { name: "Изменить" }).click();
    await page.getByLabel("Название цели").fill("На ремонт");
    await page.getByLabel("Целевая сумма").fill("12000,00");
    await page.getByRole("button", { name: "Сохранить изменения" }).click();
    await expect(goalsTable).toContainText("На ремонт");
    await goalsTable.getByRole("button", { name: "Удалить", exact: true }).click();
    await page.getByRole("button", { name: "Удалить цель", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Целей пока нет" })).toBeVisible();

    await page.goto("/app/deposits");
    await page.getByRole("button", { name: "Добавить вклад" }).click();
    await page.getByLabel("Название вклада").fill("Вклад для исправлений");
    await page.getByLabel("Начальная сумма").fill("1000,00");
    await page.getByRole("button", { name: "Создать вклад", exact: true }).click();
    await page.getByRole("button", { name: "Изменить вклад", exact: true }).click();
    await page.getByLabel("Название вклада").fill("Исправленный вклад");
    await expect(page.getByLabel("Номинальная ставка, %", { exact: true })).toHaveValue("10");
    await page.getByLabel("Номинальная ставка, %", { exact: true }).fill("12,5");
    await page.getByRole("button", { name: "Сохранить изменения" }).click();
    await expect(page.getByRole("navigation", { name: "Список вкладов" })).toContainText("12,5%");
    await page.getByRole("button", { name: "Удалить вклад", exact: true }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Удалить вклад", exact: true })
      .click();
    await expect(page.getByRole("heading", { name: "Вкладов пока нет" })).toBeVisible();

    await page.goto("/app/accounts");
    const accountsTable = page.getByRole("table", { name: "Счета", exact: true });
    await accountsTable.getByRole("button", { name: "Изменить" }).click();
    const accountDialog = page.getByRole("dialog", { name: "Изменить счёт" });
    await accountDialog.getByLabel("Название счёта").fill("Исправленная карта");
    await accountDialog.getByLabel("Текущий остаток").fill("1500,50");
    await page.getByRole("button", { name: "Сохранить изменения" }).click();
    await expect(accountsTable).toContainText("Исправленная карта");
    await expect(accountsTable).toContainText("1 500,50".replace(" ", "\u00a0"));
    await accountsTable.getByRole("button", { name: "Удалить", exact: true }).click();
    await page.getByRole("button", { name: "Удалить счёт", exact: true }).click();
    await expect(accountsTable.getByRole("row")).toHaveCount(1);
  });
});

async function bootstrapOwner(
  page: Page,
  accounts: { name: string; kind: string; opening: string }[],
): Promise<{ accounts: AccountResponse[] }> {
  const bootstrapResponse = await page.request.post(`${apiOrigin}/api/v1/auth/bootstrap`, {
    data: {
      email: "owner@example.test",
      password: "correct horse battery staple",
      base_currency: "RUB",
      locale: "ru-RU",
      timezone: "Europe/Saratov",
    },
  });
  await expectOk(bootstrapResponse);
  await installDeterministicSessionCookies(page, bootstrapResponse);
  const created: AccountResponse[] = [];
  for (const [index, account] of accounts.entries()) {
    created.push(
      await mutateJson<AccountResponse>(
        page,
        "/api/v1/accounts",
        {
          name: account.name,
          kind: account.kind,
          currency: "RUB",
          opening_balance: { amount: account.opening, currency: "RUB" },
          opening_balance_occurred_at: "2026-10-01T08:00:00Z",
        },
        `e2e-account-${String(index)}`,
      ),
    );
  }
  return { accounts: created };
}

async function mutateJson<T>(
  page: Page,
  path: string,
  data: unknown,
  key = `e2e-${randomUUID()}`,
): Promise<T> {
  const cookies = await page.context().cookies(apiOrigin);
  const csrf = cookies.find((cookie) => cookie.name === "fa_csrf")?.value;
  if (csrf === undefined) throw new Error("CSRF cookie is missing after authenticated bootstrap");
  const response = await page.request.post(`${apiOrigin}${path}`, {
    data,
    headers: { "X-CSRF-Token": csrf, "Idempotency-Key": key },
  });
  await expectOk(response);
  return responseJson<T>(response);
}

async function getJson<T>(page: Page, path: string): Promise<T> {
  const response = await page.request.get(`${apiOrigin}${path}`);
  await expectOk(response);
  return responseJson<T>(response);
}

async function expectOk(response: APIResponse): Promise<void> {
  expect(response.ok(), `${String(response.status())} ${await response.text()}`).toBe(true);
}

async function responseJson<T>(response: APIResponse | Response): Promise<T> {
  const body: unknown = await response.json();
  return body as T;
}

async function installDeterministicSessionCookies(
  page: Page,
  response: APIResponse | Response,
): Promise<void> {
  const cookiePaths: Record<string, string> = {
    fa_access: "/",
    fa_csrf: "/",
    fa_refresh: "/api/v1/auth",
  };
  const headers: { name: string; value: string }[] = await response.headersArray();
  const cookies = headers
    .filter((header) => header.name.toLowerCase() === "set-cookie")
    .map((header) => required(header.value.split(";", 1)[0], "Set-Cookie value"))
    .map((pair) => {
      const separator = pair.indexOf("=");
      if (separator <= 0) throw new Error("Invalid Set-Cookie response");
      const name = pair.slice(0, separator);
      return {
        name,
        value: pair.slice(separator + 1),
        domain: "127.0.0.1",
        path: cookiePaths[name] ?? "/",
        httpOnly: name !== "fa_csrf",
        secure: false,
        sameSite: "Strict" as const,
      };
    });
  expect(cookies.map((cookie) => cookie.name).sort()).toEqual([
    "fa_access",
    "fa_csrf",
    "fa_refresh",
  ]);
  await page.context().addCookies(cookies);
}

function sumPostings(transaction: TransactionResponse): string {
  const cents = transaction.postings.reduce((sum, posting) => {
    const amountParts = posting.money.amount.split(".");
    const whole = required(amountParts[0], "posting whole amount");
    const fraction = amountParts[1] ?? "";
    const sign = whole.startsWith("-") ? -1n : 1n;
    const absoluteWhole = BigInt(whole.replace("-", ""));
    return sum + sign * (absoluteWhole * 100n + BigInt(fraction.padEnd(2, "0")));
  }, 0n);
  const absolute = cents < 0n ? -cents : cents;
  return `${cents < 0n ? "-" : ""}${(absolute / 100n).toString()}.${(absolute % 100n)
    .toString()
    .padStart(2, "0")}`;
}

function required<T>(value: T | undefined, label: string): T {
  if (value === undefined) throw new Error(`Missing ${label}`);
  return value;
}

function runWorkerOnce(): void {
  const result = spawnSync(
    "poetry",
    ["run", "python", "-m", "financial_analytics_worker", "--once"],
    {
      cwd: process.cwd(),
      env: { ...process.env, APP_ENV: "test", TEST_CLOCK_AT: fixedNow.toISOString() },
      stdio: "pipe",
    },
  );
  if (result.status !== 0) throw new Error(`worker failed: ${result.stderr.toString()}`);
}
