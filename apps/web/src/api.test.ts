import { ApiError, FinancialAnalyticsClient } from "@financial-analytics/api-contracts";
import { describe, expect, it, vi } from "vitest";

import { apiErrorMessage, BrowserFinanceApi, readCookie, SessionExpiredError } from "./api";

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

describe("BrowserFinanceApi", () => {
  it("bootstraps an existing session through the generated client", async () => {
    const client = new FinancialAnalyticsClient("http://api.test");
    vi.spyOn(client, "current_profile_api_v1_profile_get").mockResolvedValue(profile);
    vi.spyOn(client, "listAccounts").mockResolvedValue([account]);
    const api = new BrowserFinanceApi(client, () => "");

    await expect(api.bootstrapSession()).resolves.toEqual({
      kind: "authenticated",
      profile,
      accounts: [account],
    });
  });

  it("returns anonymous when neither access nor refresh session is valid", async () => {
    const client = new FinancialAnalyticsClient("http://api.test");
    vi.spyOn(client, "current_profile_api_v1_profile_get").mockRejectedValue(new ApiError(401, {}));
    const refresh = vi
      .spyOn(client, "refresh_api_v1_auth_refresh_post")
      .mockRejectedValue(new ApiError(401, {}));
    const api = new BrowserFinanceApi(client, () => "");

    await expect(api.bootstrapSession()).resolves.toEqual({ kind: "anonymous" });
    expect(refresh).toHaveBeenCalledWith({});
  });

  it("refreshes once and retries a protected request with the CSRF cookie", async () => {
    const client = new FinancialAnalyticsClient("http://api.test");
    const refresh = vi.spyOn(client, "refresh_api_v1_auth_refresh_post").mockResolvedValue(profile);
    const list = vi
      .spyOn(client, "listAccounts")
      .mockRejectedValueOnce(new ApiError(401, {}))
      .mockResolvedValueOnce([account]);
    const api = new BrowserFinanceApi(client, () => "theme=dark; fa_csrf=token%2Bvalue");

    await expect(api.listAccounts()).resolves.toEqual([account]);
    expect(refresh).toHaveBeenCalledWith({
      xCSRFToken: "token+value",
    });
    expect(list).toHaveBeenCalledTimes(2);
  });

  it("surfaces an explicit session-expired error after refresh failure", async () => {
    const client = new FinancialAnalyticsClient("http://api.test");
    vi.spyOn(client, "listAccounts").mockRejectedValue(new ApiError(401, {}));
    vi.spyOn(client, "refresh_api_v1_auth_refresh_post").mockRejectedValue(new ApiError(403, {}));
    const api = new BrowserFinanceApi(client, () => "fa_csrf=stale");

    await expect(api.listAccounts()).rejects.toBeInstanceOf(SessionExpiredError);
  });

  it("delegates authentication, account creation, and logout to generated operations", async () => {
    const client = new FinancialAnalyticsClient("http://api.test");
    const bootstrap = vi
      .spyOn(client, "bootstrap_master_api_v1_auth_bootstrap_post")
      .mockResolvedValue(profile);
    const login = vi.spyOn(client, "login_api_v1_auth_login_post").mockResolvedValue(profile);
    const create = vi.spyOn(client, "createAccount").mockResolvedValue(account);
    const logout = vi
      .spyOn(client, "logout_current_api_v1_auth_logout_post")
      .mockResolvedValue(undefined);
    const api = new BrowserFinanceApi(client, () => "fa_csrf=csrf-value");
    const bootstrapBody = {
      email: profile.email,
      password: "correct horse battery staple",
      base_currency: "RUB",
      locale: "ru-RU",
      timezone: "Europe/Saratov",
    };

    await expect(api.bootstrapMaster(bootstrapBody)).resolves.toEqual(profile);
    await expect(api.login({ email: profile.email, password: "password" })).resolves.toEqual(
      profile,
    );
    await expect(
      api.createAccount({ name: "Основная карта", kind: "bank", currency: "RUB" }),
    ).resolves.toEqual(account);
    await expect(api.logout()).resolves.toBeUndefined();

    expect(bootstrap).toHaveBeenCalledWith({ body: bootstrapBody });
    expect(login).toHaveBeenCalledWith({
      body: { email: profile.email, password: "password" },
    });
    expect(create).toHaveBeenCalledOnce();
    const createArguments = create.mock.calls[0]?.[0];
    expect(typeof createArguments?.idempotencyKey).toBe("string");
    expect(createArguments).toMatchObject({
      xCSRFToken: "csrf-value",
      body: { name: "Основная карта", kind: "bank", currency: "RUB" },
    });
    expect(logout).toHaveBeenCalledWith({ xCSRFToken: "csrf-value" });
  });

  it("routes every finance workflow through the generated client boundary", async () => {
    const client = new FinancialAnalyticsClient("http://api.test");
    const result = {} as never;
    const list = [] as never;
    vi.spyOn(client, "getAnalyticsDashboard").mockResolvedValue(result);
    vi.spyOn(client, "listCategoryGroups").mockResolvedValue(list);
    vi.spyOn(client, "createCategoryGroup").mockResolvedValue(result);
    vi.spyOn(client, "listCategories").mockResolvedValue(list);
    vi.spyOn(client, "createCategory").mockResolvedValue(result);
    vi.spyOn(client, "listTransactions").mockResolvedValue(result);
    vi.spyOn(client, "createIncome").mockResolvedValue(result);
    vi.spyOn(client, "createExpense").mockResolvedValue(result);
    vi.spyOn(client, "createTransfer").mockResolvedValue(result);
    vi.spyOn(client, "createAdjustment").mockResolvedValue(result);
    vi.spyOn(client, "reverseTransaction").mockResolvedValue(result);
    vi.spyOn(client, "exportTransactionsCsv").mockResolvedValue("csv");
    vi.spyOn(client, "listRecurringRules").mockResolvedValue(list);
    vi.spyOn(client, "previewRecurringOccurrences").mockResolvedValue(list);
    vi.spyOn(client, "createRecurringRule").mockResolvedValue(result);
    vi.spyOn(client, "pauseRecurringRule").mockResolvedValue(result);
    vi.spyOn(client, "resumeRecurringRule").mockResolvedValue(result);
    vi.spyOn(client, "listDeposits").mockResolvedValue(list);
    vi.spyOn(client, "createDeposit").mockResolvedValue(result);
    vi.spyOn(client, "getDepositValuation").mockResolvedValue(result);
    vi.spyOn(client, "recordDepositCashflow").mockResolvedValue(result);
    vi.spyOn(client, "recordDepositInterest").mockResolvedValue(result);
    vi.spyOn(client, "getFinancialReport").mockResolvedValue(result);
    vi.spyOn(client, "listForecastScenarios").mockResolvedValue(list);
    vi.spyOn(client, "createForecastScenario").mockResolvedValue(result);
    vi.spyOn(client, "getForecast").mockResolvedValue(result);
    vi.spyOn(client, "compareForecastScenarios").mockResolvedValue(result);
    vi.spyOn(client, "listFinancialGoals").mockResolvedValue(list);
    vi.spyOn(client, "createFinancialGoal").mockResolvedValue(result);
    vi.spyOn(client, "getAdviceProviderStatus").mockResolvedValue(result);
    vi.spyOn(client, "generateFinancialAdvice").mockResolvedValue(result);
    const api = new BrowserFinanceApi(client, () => "fa_csrf=csrf");
    const money = { amount: "10.00", currency: "RUB" };
    const operation = {
      account_id: account.id,
      category_id: "category",
      money,
      occurred_at: "2026-10-16T08:00:00Z",
    };

    await Promise.all([
      api.getDashboard(),
      api.listCategoryGroups(),
      api.createCategoryGroup({ name: "Быт" }),
      api.listCategories(),
      api.createCategory({ name: "Продукты", kind: "expense" }),
      api.listTransactions({ search: "кофе" }),
      api.createOperation("income", operation),
      api.createOperation("expense", operation),
      api.createTransfer({
        source_account_id: account.id,
        destination_account_id: "other",
        money,
        occurred_at: operation.occurred_at,
      }),
      api.createAdjustment({
        account_id: account.id,
        money,
        occurred_at: operation.occurred_at,
        description: "reconcile",
      }),
      api.reverseTransaction("transaction", {
        occurred_at: operation.occurred_at,
        reason: "duplicate",
      }),
      api.exportTransactions({ kind: "expense" }),
      api.listRecurringRules(),
      api.previewRecurringOccurrences({
        frequency: "monthly",
        starts_on: "2026-10-16",
        local_time: "09:00",
        timezone: "Europe/Saratov",
      }),
      api.createRecurringRule({
        frequency: "monthly",
        starts_on: "2026-10-16",
        local_time: "09:00",
        timezone: "Europe/Saratov",
        operation: { kind: "expense", account_id: account.id, category_id: "category", money },
      }),
      api.setRecurringRulePaused(
        {
          id: "rule",
          operation: {
            kind: "expense",
            account_id: account.id,
            destination_account_id: null,
            category_id: "category",
            money,
            description: "",
            tag_ids: [],
          },
          frequency: "monthly",
          starts_on: "2026-10-16",
          local_time: "09:00",
          timezone: "Europe/Saratov",
          missing_day_policy: "last_day",
          catch_up_policy: "all",
          end_date: null,
          next_occurrence_at: null,
          status: "active",
          version: 1,
        },
        true,
      ),
      api.setRecurringRulePaused(
        {
          id: "rule",
          operation: {
            kind: "expense",
            account_id: account.id,
            destination_account_id: null,
            category_id: "category",
            money,
            description: "",
            tag_ids: [],
          },
          frequency: "monthly",
          starts_on: "2026-10-16",
          local_time: "09:00",
          timezone: "Europe/Saratov",
          missing_day_policy: "last_day",
          catch_up_policy: "all",
          end_date: null,
          next_occurrence_at: null,
          status: "paused",
          version: 2,
        },
        false,
      ),
      api.listDeposits(),
      api.createDeposit({
        principal_account_id: account.id,
        currency: "RUB",
        opened_on: "2026-10-16",
        matures_on: "2027-10-16",
        rate_periods: [
          { starts_on: "2026-10-16", ends_on: "2027-10-16", nominal_rate: { value: "0.1" } },
        ],
        capitalization_frequency: "monthly_calendar_end",
        day_count_convention: "actual_365_fixed",
        rounding_policy: "half_even",
        interest_rounding_frequency: "capitalization",
        timezone: "Europe/Saratov",
        cashflow_cutoff_time: "23:59:59",
        cashflow_cutoff_inclusive: true,
        early_close_rule: { policy: "forfeit_interest", nominal_rate: null },
        tax_rate: { value: "0" },
      }),
      api.getDepositValuation("deposit", "2026-10-16"),
      api.recordDepositCashflow("deposit", {
        counterparty_account_id: account.id,
        money,
        occurred_at: operation.occurred_at,
        description: "top up",
      }),
      api.recordDepositInterest("deposit", {
        money,
        occurred_at: operation.occurred_at,
        description: "actual",
      }),
      api.getFinancialReport("2026-10-01", "2026-10-16", "month"),
      api.listForecastScenarios(),
      api.createForecastScenario({ name: "Plan", currency: "RUB", horizon: "2027-10-16" }),
      api.getForecast("RUB", "2027-10-16"),
      api.compareForecasts("RUB", "2027-10-16", ["scenario"]),
      api.listFinancialGoals(),
      api.createFinancialGoal({
        name: "Reserve",
        target: money,
        target_date: "2027-10-16",
        saved_amount: money,
        priority: 1,
      }),
      api.getAdviceProviderStatus(),
      api.generateAdvice({ currency: "RUB" }),
    ]);

    expect(vi.mocked(client.createIncome.bind(client))).toBeTypeOf("function");
    expect(vi.mocked(client.createExpense.bind(client))).toBeTypeOf("function");
    expect(vi.mocked(client.pauseRecurringRule.bind(client))).toBeTypeOf("function");
    expect(vi.mocked(client.resumeRecurringRule.bind(client))).toBeTypeOf("function");
    expect(vi.mocked(client.generateFinancialAdvice.bind(client))).toBeTypeOf("function");
  });

  it("does not hide non-authentication transport failures", async () => {
    const profileFailureClient = new FinancialAnalyticsClient("http://api.test");
    vi.spyOn(profileFailureClient, "current_profile_api_v1_profile_get").mockRejectedValue(
      new Error("transport"),
    );
    await expect(new BrowserFinanceApi(profileFailureClient).bootstrapSession()).rejects.toThrow(
      "transport",
    );

    const listFailureClient = new FinancialAnalyticsClient("http://api.test");
    vi.spyOn(listFailureClient, "listAccounts").mockRejectedValue(new Error("database offline"));
    await expect(new BrowserFinanceApi(listFailureClient).listAccounts()).rejects.toThrow(
      "database offline",
    );
  });

  it("rejects when a retried protected request is still unauthorized", async () => {
    const client = new FinancialAnalyticsClient("http://api.test");
    vi.spyOn(client, "listAccounts").mockRejectedValue(new ApiError(401, {}));
    vi.spyOn(client, "refresh_api_v1_auth_refresh_post").mockResolvedValue(profile);

    await expect(new BrowserFinanceApi(client).listAccounts()).rejects.toBeInstanceOf(
      SessionExpiredError,
    );
  });
});

describe("API helpers", () => {
  it("reads an encoded cookie without exposing neighboring values", () => {
    expect(readCookie("a=1; fa_csrf=hello%20world; b=2", "fa_csrf")).toBe("hello world");
    expect(readCookie("a=1", "fa_csrf")).toBeNull();
  });

  it("maps structured API failures to a safe Russian message", () => {
    const error = new ApiError(401, {
      type: "about:blank",
      title: "Unauthorized",
      status: 401,
      detail: "credentials rejected",
      code: "invalid_credentials",
      instance: "/api/v1/auth/login",
      request_id: "request",
      correlation_id: "correlation",
    });
    expect(apiErrorMessage(error)).toBe("Email или пароль не подошли.");
    expect(apiErrorMessage(new Error("secret transport detail")).includes("secret")).toBe(false);
  });

  it("covers every public safe error category", () => {
    const problem = (code: string, detail = "safe detail") =>
      new ApiError(400, {
        type: "about:blank",
        title: "Failure",
        status: 400,
        detail,
        code,
        instance: "/api/v1/test",
        request_id: "request",
        correlation_id: "correlation",
      });

    expect(apiErrorMessage(new SessionExpiredError())).toContain("Сессия завершилась");
    expect(apiErrorMessage(problem("bootstrap_closed"))).toContain("уже настроено");
    expect(apiErrorMessage(problem("rate_limit_exceeded"))).toContain("Слишком много");
    expect(apiErrorMessage(problem("csrf_validation_failed"))).toContain("токен устарел");
    expect(apiErrorMessage(problem("other", "Понятная ошибка"))).toBe("Понятная ошибка");
    expect(apiErrorMessage(problem("other", ""))).toBe("Не удалось выполнить запрос.");
    expect(apiErrorMessage(new ApiError(500, null))).toContain("Не удалось связаться");
  });
});
