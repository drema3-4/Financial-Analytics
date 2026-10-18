import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { FinanceApi } from "../api";
import { FinanceWorkspace } from "./FinanceWorkspace";

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

function api(overrides: Partial<FinanceApi> = {}): FinanceApi {
  return {
    listAccounts: () => Promise.resolve([account]),
    createAccount: () => Promise.resolve(account),
    createCategory: () => Promise.reject(new Error("not used")),
    createCategoryGroup: () => Promise.reject(new Error("not used")),
    listCategories: () => Promise.resolve([]),
    listCategoryGroups: () => Promise.resolve([]),
    listTransactions: () => Promise.resolve({ items: [], next_cursor: null }),
    listRecurringRules: () => Promise.resolve([]),
    listDeposits: () => Promise.resolve([]),
    listForecastScenarios: () => Promise.resolve([]),
    listFinancialGoals: () => Promise.resolve([]),
    getAdviceProviderStatus: () =>
      Promise.resolve({
        status: "disabled",
        provider: "disabled",
        model: null,
        endpoint_scope: "aggregate_only",
        capabilities: { json_schema: false, system_messages: false, non_thinking: false },
        prompt_version: "v1",
        context_version: "v1",
      }),
    getFinancialReport: () => Promise.resolve(report),
    getForecast: () => Promise.resolve(forecast),
    ...overrides,
  } as FinanceApi;
}

function renderRoute(path: string, financeApi = api()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <FinanceWorkspace
        accounts={[account]}
        api={financeApi}
        navigate={vi.fn()}
        onAccountsChanged={vi.fn()}
        path={path}
        profile={profile}
      />
    </QueryClientProvider>,
  );
}

describe("financial workspace", () => {
  it.each([
    ["/app/accounts", "Счета и категории"],
    ["/app/transactions", "Журнал операций"],
    ["/app/recurring", "Регулярные операции"],
    ["/app/deposits", "Вклады"],
    ["/app/analytics", "Аналитика"],
    ["/app/forecast", "Прогноз"],
    ["/app/goals", "Финансовые цели"],
    ["/app/advice", "Финансовый советник"],
  ])("renders %s with accessible primary heading", async (path, heading) => {
    renderRoute(path);
    expect(await screen.findByRole("heading", { name: heading, level: 1 })).toBeInTheDocument();
  });

  it("offers deterministic advice input when the provider is configured", async () => {
    renderRoute(
      "/app/advice",
      api({
        getAdviceProviderStatus: () =>
          Promise.resolve({
            status: "configured",
            provider: "openai_compatible",
            model: "deterministic-test-provider",
            endpoint_scope: "local",
            capabilities: { json_schema: true, system_messages: true, non_thinking: true },
            prompt_version: "v1",
            context_version: "v1",
          }),
      }),
    );

    expect(await screen.findByLabelText("Вопрос (необязательно)")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Советник недоступен" })).not.toBeInTheDocument();
  });

  it("creates an expense with an exact decimal string and server-owned result", async () => {
    const createOperation = vi.fn(() => Promise.resolve({ id: "tx" } as never));
    const financeApi = api({
      listCategories: () =>
        Promise.resolve([
          {
            id: "cat",
            name: "Продукты",
            kind: "expense",
            group_id: null,
            is_mandatory: true,
            version: 1,
          },
        ]),
      createOperation,
      listTransactions: () => Promise.resolve({ items: [], next_cursor: null }),
    });
    renderRoute("/app/transactions", financeApi);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Новая операция" }));
    await user.type(await screen.findByLabelText("Категория"), "Продукты");
    await user.type(screen.getByLabelText("Сумма"), "1 250,40");
    await user.type(screen.getByLabelText("Комментарий"), "Продукты");
    await user.click(screen.getByRole("button", { name: "Провести" }));
    expect(createOperation).toHaveBeenCalledWith(
      "expense",
      expect.objectContaining({ money: { amount: "1250.40", currency: "RUB" } }),
    );
  });

  it("shows API errors without replacing them with fabricated financial data", async () => {
    renderRoute(
      "/app/analytics",
      api({ getFinancialReport: () => Promise.reject(new Error("offline secret")) }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось связаться");
    expect(screen.getByRole("button", { name: "Попробовать снова" })).toBeEnabled();
  });

  it("creates a new category inside the operation form when the catalogue is empty", async () => {
    const category = {
      id: "new-category",
      name: "Кофе",
      kind: "expense" as const,
      group_id: null,
      is_mandatory: false,
      version: 1,
    };
    const createCategory = vi.fn(() => Promise.resolve(category));
    const createOperation = vi.fn(() => Promise.resolve({ id: "transaction" } as never));
    renderRoute("/app/transactions", api({ createCategory, createOperation }));
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Новая операция" }));
    await user.type(screen.getByLabelText("Категория"), "Кофе");
    await user.type(screen.getByLabelText("Сумма"), "125,25");
    await user.click(screen.getByRole("button", { name: "Провести" }));
    expect(createCategory).toHaveBeenCalledWith({ name: "Кофе", kind: "expense" });
    expect(createOperation).toHaveBeenCalledWith(
      "expense",
      expect.objectContaining({
        category_id: "new-category",
        money: { amount: "125.25", currency: "RUB" },
      }),
    );
  });

  it("edits the profile-local date and opens a clean new operation afterwards", async () => {
    renderRoute(
      "/app/transactions",
      api({
        listTransactions: () =>
          Promise.resolve({
            next_cursor: null,
            items: [
              {
                id: "old-operation",
                kind: "adjustment",
                version: 1,
                occurred_at: "2026-10-18T21:30:00Z",
                description: "Прежние данные",
                source: "manual",
                category_id: null,
                deposit_id: null,
                reversal_of_id: null,
                reversed_by_id: null,
                tag_ids: [],
                postings: [
                  {
                    id: "posting",
                    account_id: account.id,
                    reversal_of_id: null,
                    money: { amount: "123.45", currency: "RUB" },
                  },
                ],
              },
            ],
          }),
      }),
    );
    const user = userEvent.setup();
    const journal = await screen.findByRole("table", { name: "Журнал операций" });
    await user.click(within(journal).getByRole("button", { name: "Изменить" }));
    expect(screen.getByLabelText("Дата")).toHaveValue("2026-10-19");
    await user.click(screen.getByRole("button", { name: "Закрыть" }));
    await user.click(screen.getByRole("button", { name: "Новая операция" }));
    expect(screen.getByLabelText("Сумма")).toHaveValue("");
    expect(screen.getByLabelText("Комментарий")).toHaveValue("");
    expect(screen.getByLabelText("Тип операции")).toHaveValue("expense");
  });

  it("requests an aligned current month and changes grouping without a broken end date", async () => {
    const getFinancialReport = vi.fn(() => Promise.resolve(report));
    renderRoute("/app/analytics", api({ getFinancialReport }));
    await screen.findByRole("heading", { name: "Сравнение периодов" });
    const firstCall = getFinancialReport.mock.calls[0] as unknown as [string, string, string];
    expect(firstCall[0]).toMatch(/-01$/);
    expect(firstCall[1]).toMatch(/-01$/);
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Группировка"), "week");
    await user.click(screen.getByRole("button", { name: "Показать" }));
    const lastCall = getFinancialReport.mock.calls.at(-1) as unknown as [string, string, string];
    expect(new Date(`${lastCall[0]}T00:00:00Z`).getUTCDay()).toBe(1);
    expect(new Date(`${lastCall[1]}T00:00:00Z`).getUTCDay()).toBe(1);
    expect(lastCall[2]).toBe("week");
  });
});

const report = {
  period: {
    start: "2026-10-01",
    end: "2026-10-16",
    timezone: "Europe/Saratov",
    granularity: "month" as const,
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
