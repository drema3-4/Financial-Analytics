import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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
    await user.selectOptions(await screen.findByLabelText("Категория"), "cat");
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
});

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
