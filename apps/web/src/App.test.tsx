import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { FinanceApi } from "./api";
import { SessionExpiredError } from "./api";
import { App } from "./App";

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

function fakeApi(overrides: Partial<FinanceApi> = {}): FinanceApi {
  return {
    bootstrapSession: () => Promise.resolve({ kind: "anonymous" }),
    bootstrapMaster: () => Promise.resolve(profile),
    login: () => Promise.resolve(profile),
    listAccounts: () => Promise.resolve([account]),
    createAccount: () => Promise.resolve(account),
    logout: () => Promise.resolve(),
    ...overrides,
  };
}

describe("App routes", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
  });

  it("takes an existing user from login to the dashboard", async () => {
    const login = vi.fn(() => Promise.resolve(profile));
    const api = fakeApi({ login });
    const user = userEvent.setup();
    render(<App api={api} />);

    expect(await screen.findByRole("heading", { name: "С возвращением" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Email"), "owner@example.com");
    await user.type(screen.getByLabelText("Пароль"), "correct horse battery staple");
    await user.click(screen.getByRole("button", { name: "Войти" }));

    expect(await screen.findByRole("heading", { name: "Добро пожаловать." })).toBeInTheDocument();
    expect(screen.getAllByText(/125.000,50.RUB/u).length).toBeGreaterThan(0);
    expect(login).toHaveBeenCalledWith({
      email: "owner@example.com",
      password: "correct horse battery staple",
    });
  });

  it("keeps a failed login on the form with a designed error", async () => {
    const api = fakeApi({ login: () => Promise.reject(new Error("network secret")) });
    const user = userEvent.setup();
    render(<App api={api} />);

    await user.type(await screen.findByLabelText("Email"), "owner@example.com");
    await user.type(screen.getByLabelText("Пароль"), "wrong password");
    await user.click(screen.getByRole("button", { name: "Войти" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось связаться");
    expect(screen.getByRole("heading", { name: "С возвращением" })).toBeInTheDocument();
  });

  it("completes master bootstrap and sends the opening balance as an exact string", async () => {
    const bootstrapMaster = vi.fn(() => Promise.resolve(profile));
    const createAccount = vi.fn(() => Promise.resolve(account));
    const api = fakeApi({ bootstrapMaster, createAccount });
    const user = userEvent.setup();
    render(<App api={api} />);

    await user.click(await screen.findByRole("link", { name: "Настроить пространство" }));
    await user.type(screen.getByLabelText("Email"), "owner@example.com");
    await user.type(screen.getByLabelText("Пароль"), "correct horse battery staple");
    await user.type(screen.getByLabelText("Повторите пароль"), "correct horse battery staple");
    await user.click(screen.getByRole("button", { name: "Продолжить" }));
    await user.selectOptions(screen.getByLabelText("Основная валюта"), "RUB");
    await user.selectOptions(screen.getByLabelText("Формат чисел и дат"), "ru-RU");
    await user.clear(screen.getByLabelText("Часовой пояс"));
    await user.type(screen.getByLabelText("Часовой пояс"), "Europe/Saratov");
    await user.click(screen.getByRole("button", { name: "Создать профиль" }));

    expect(await screen.findByRole("heading", { name: "С чего начнём?" })).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Название счёта"));
    await user.type(screen.getByLabelText("Название счёта"), "Основная карта");
    await user.type(screen.getByLabelText("Начальный остаток"), "125 000,50");
    await user.clear(screen.getByLabelText("Дата остатка"));
    await user.type(screen.getByLabelText("Дата остатка"), "2026-10-14");
    await user.click(screen.getByRole("button", { name: "Создать счёт и открыть обзор" }));

    expect(await screen.findByRole("heading", { name: "Добро пожаловать." })).toBeInTheDocument();
    expect(bootstrapMaster).toHaveBeenCalledWith({
      email: "owner@example.com",
      password: "correct horse battery staple",
      base_currency: "RUB",
      locale: "ru-RU",
      timezone: "Europe/Saratov",
    });
    expect(createAccount).toHaveBeenCalledWith({
      name: "Основная карта",
      kind: "bank",
      currency: "RUB",
      opening_balance: { amount: "125000.50", currency: "RUB" },
      opening_balance_occurred_at: "2026-10-14T08:00:00.000Z",
    });
  });

  it("validates password and opening balance before making API calls", async () => {
    const bootstrapMaster = vi.fn(() => Promise.resolve(profile));
    const createAccount = vi.fn(() => Promise.reject(new Error("offline")));
    const api = fakeApi({ bootstrapMaster, createAccount });
    const user = userEvent.setup();
    render(<App api={api} />);

    await user.click(await screen.findByRole("link", { name: "Настроить пространство" }));
    await user.type(screen.getByLabelText("Email"), "owner@example.com");
    await user.type(screen.getByLabelText("Пароль"), "short");
    await user.type(screen.getByLabelText("Повторите пароль"), "short");
    await user.click(screen.getByRole("button", { name: "Продолжить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("не менее 12");

    await user.clear(screen.getByLabelText("Пароль"));
    await user.clear(screen.getByLabelText("Повторите пароль"));
    await user.type(screen.getByLabelText("Пароль"), "correct horse battery staple");
    await user.type(screen.getByLabelText("Повторите пароль"), "different long password");
    await user.click(screen.getByRole("button", { name: "Продолжить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("не совпадают");

    await user.clear(screen.getByLabelText("Повторите пароль"));
    await user.type(screen.getByLabelText("Повторите пароль"), "correct horse battery staple");
    await user.click(screen.getByRole("button", { name: "Продолжить" }));
    await user.click(screen.getByRole("button", { name: "Назад" }));
    expect(screen.getByRole("heading", { name: "Профиль владельца" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Продолжить" }));
    await user.click(screen.getByRole("button", { name: "Создать профиль" }));

    await user.type(await screen.findByLabelText("Начальный остаток"), "12,3,4");
    await user.click(screen.getByRole("button", { name: "Создать счёт и открыть обзор" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Проверьте сумму");
    expect(createAccount.mock.calls).toHaveLength(0);

    await user.clear(screen.getByLabelText("Начальный остаток"));
    await user.type(screen.getByLabelText("Начальный остаток"), "100,00");
    await user.click(screen.getByRole("button", { name: "Создать счёт и открыть обзор" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось связаться");
  });

  it("routes an authenticated profile without accounts to the last onboarding step", async () => {
    window.history.replaceState(null, "", "/app/dashboard");
    const api = fakeApi({
      bootstrapSession: () => Promise.resolve({ kind: "authenticated", profile, accounts: [] }),
    });
    render(<App api={api} />);

    expect(await screen.findByRole("heading", { name: "С чего начнём?" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/onboarding/account");
  });

  it("returns to login with a clear message when the session expires", async () => {
    window.history.replaceState(null, "", "/onboarding/account");
    const api = fakeApi({
      bootstrapSession: () => Promise.resolve({ kind: "authenticated", profile, accounts: [] }),
      createAccount: () => Promise.reject(new SessionExpiredError()),
    });
    const user = userEvent.setup();
    render(<App api={api} />);

    await user.click(await screen.findByRole("button", { name: "Создать счёт и открыть обзор" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Сессия завершилась");
    expect(screen.getByRole("heading", { name: "С возвращением" })).toBeInTheDocument();
  });

  it("renders a designed global loading failure", async () => {
    const api = fakeApi({
      bootstrapSession: () => Promise.reject(new Error("offline")),
    });
    render(<App api={api} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось связаться");
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Попробовать снова" })).toBeEnabled();
    });
  });

  it("renders route boundaries and supports profile drawer logout", async () => {
    const cashAccount = {
      ...account,
      id: "33333333-3333-4333-8333-333333333333",
      kind: "cash",
      balance: { amount: "-100", currency: "RUB" },
    };
    const unknownAccount = {
      ...account,
      id: "44444444-4444-4444-8444-444444444444",
      kind: "brokerage",
      balance: { amount: "0", currency: "RUB" },
    };
    const logout = vi.fn(() => Promise.resolve());
    window.history.replaceState(null, "", "/app/missing");
    const api = fakeApi({
      bootstrapSession: () =>
        Promise.resolve({
          kind: "authenticated",
          profile,
          accounts: [cashAccount, unknownAccount],
        }),
      logout,
    });
    const user = userEvent.setup();
    render(<App api={api} />);

    expect(await screen.findByRole("heading", { name: "Страница не найдена" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Попробовать снова" }));
    expect(await screen.findByRole("heading", { name: "Добро пожаловать." })).toBeInTheDocument();
    expect(screen.getAllByText(/−100.RUB/u).length).toBeGreaterThan(0);
    expect(screen.getAllByText("brokerage").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "Открыть профиль" }));
    expect(screen.getByRole("dialog", { name: "Профиль" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Выйти" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Вы вышли");
    expect(logout).toHaveBeenCalledOnce();
  });
});
