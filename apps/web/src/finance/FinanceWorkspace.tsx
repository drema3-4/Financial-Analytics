/* eslint-disable @typescript-eslint/no-non-null-assertion, @typescript-eslint/no-deprecated, @typescript-eslint/use-unknown-in-catch-callback-variable, @typescript-eslint/restrict-template-expressions, @typescript-eslint/no-unnecessary-condition */
import { useState, type FormEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  AccountResponse,
  CategoryResponse,
  CategoryKind,
  DashboardResponse,
  DepositValuationResponse,
  DepositTermsResponse,
  FinancialReportResponse,
  ForecastRunResponse,
  GoalResponse,
  PeriodGranularity,
  PreviewOccurrenceResponse,
  ProfileResponse,
  RecurrenceFrequency,
  RecurringRuleResponse,
  TransactionKind,
  TransactionResponse,
} from "@financial-analytics/api-contracts";

import { apiErrorMessage, type FinanceApi, type TransactionFilters } from "../api";
import {
  Button,
  DateControl,
  Dialog,
  EmptyState,
  ErrorState,
  InputField,
  LoadingState,
  operationInstant,
  MoneyInput,
  parseLocalizedDecimal,
  ResponsiveDataView,
  SelectField,
  todayIsoDate,
} from "../ui";

type Navigate = (path: string, options?: { replace?: boolean }) => void;

interface WorkspaceProps {
  accounts: AccountResponse[];
  api: FinanceApi;
  navigate: Navigate;
  onAccountsChanged: (accounts: AccountResponse[]) => void;
  path: string;
  profile: ProfileResponse;
}

interface FinancialInstrument {
  currency: string;
  id: string;
  kind: "account" | "deposit";
  name: string;
}

const transactionLabels: Record<TransactionKind, string> = {
  income: "Доход",
  expense: "Расход",
  transfer: "Перевод",
  adjustment: "Корректировка",
  interest: "Проценты",
  reversal: "Сторно",
};

export function FinanceWorkspace(props: WorkspaceProps) {
  const accounts = useQuery({
    queryKey: ["accounts"],
    queryFn: () => props.api.listAccounts(),
    initialData: props.accounts,
  });
  return <FinanceRoutes {...props} accounts={accounts.data} />;
}

function FinanceRoutes(props: WorkspaceProps) {
  switch (props.path) {
    case "/app/dashboard":
      return <DashboardPage {...props} />;
    case "/app/accounts":
      return <AccountsPage {...props} />;
    case "/app/transactions":
      return <TransactionsPage {...props} />;
    case "/app/recurring":
      return <RecurringPage {...props} />;
    case "/app/deposits":
      return <DepositsPage {...props} />;
    case "/app/analytics":
      return <AnalyticsPage {...props} />;
    case "/app/forecast":
      return <ForecastPage {...props} />;
    case "/app/goals":
      return <GoalsPage {...props} />;
    case "/app/advice":
      return <AdvicePage {...props} />;
    default:
      return (
        <ErrorState
          message="Такого раздела нет или адрес изменился."
          onRetry={() => {
            props.navigate("/app/dashboard", { replace: true });
          }}
          title="Страница не найдена"
        />
      );
  }
}

function DashboardPage({ accounts, api, profile }: WorkspaceProps) {
  const dashboard = useQuery({ queryKey: ["dashboard"], queryFn: () => api.getDashboard() });
  const rules = useQuery({ queryKey: ["recurring"], queryFn: () => api.listRecurringRules() });
  const goals = useQuery({ queryKey: ["goals"], queryFn: () => api.listFinancialGoals() });
  if (dashboard.isLoading || rules.isLoading || goals.isLoading)
    return <LoadingState label="Собираем обзор из проводок" />;
  if (dashboard.error)
    return <QueryError error={dashboard.error} retry={() => void dashboard.refetch()} />;
  const data = dashboard.data;
  if (data === undefined)
    return (
      <EmptyState title="Пока нет данных для обзора" description="Добавьте первую операцию." />
    );
  const total =
    data.totals.find((item) => item.currency === profile.base_currency) ?? data.totals[0];
  const upcoming = (rules.data ?? [])
    .filter((rule) => rule.status === "active" && rule.next_occurrence_at !== null)
    .slice(0, 4);
  return (
    <Page
      title="Финансовый обзор"
      eyebrow={`Главная · ${profile.base_currency}`}
      actions={<Freshness value={data.data_through} profile={profile} />}
    >
      {data.currency_mode === "separated_by_currency" ? <CurrencyWarning /> : null}
      {total === undefined ? (
        <EmptyState
          title="Нет проводок за период"
          description="Показатели появятся после операции."
        />
      ) : (
        <div className="metric-strip">
          <Metric
            label="Капитал"
            value={money(total.closing_net_worth.value, profile)}
            note={total.closing_net_worth.formula}
          />
          <Metric
            label="Денежный поток"
            value={money(total.cash_flow.value, profile)}
            note={periodLabel(data)}
          />
          <Metric label="Доходы" value={money(total.income.value, profile)} />
          <Metric label="Расходы" value={money(total.expense.value, profile)} />
        </div>
      )}
      <div className="workspace-grid">
        <Section
          title="Ближайшие обязательства"
          subtitle={`Время показано для ${profile.timezone}`}
        >
          {upcoming.length === 0 ? (
            <EmptyState
              title="Обязательств нет"
              description="Создайте регулярное правило, чтобы видеть ближайшие списания."
            />
          ) : (
            <ul className="clean-list">
              {upcoming.map((rule) => (
                <li key={rule.id}>
                  <strong>
                    {rule.operation.description || transactionLabels[rule.operation.kind]}
                  </strong>
                  <span>
                    {money(rule.operation.money, profile)} ·{" "}
                    {dateTime(rule.next_occurrence_at!, profile)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Section>
        <Section title="Цели" subtitle="Накоплено / целевая сумма">
          {(goals.data ?? []).length === 0 ? (
            <EmptyState
              title="Целей пока нет"
              description="Создайте цель и получите расчёт необходимого взноса."
            />
          ) : (
            <ul className="clean-list">
              {(goals.data ?? []).slice(0, 4).map((goal) => (
                <li key={goal.id}>
                  <strong>{goal.name}</strong>
                  <span>
                    {money(goal.saved_amount, profile)} / {money(goal.target, profile)}
                  </span>
                  <progress
                    aria-label={`Прогресс цели ${goal.name}`}
                    max={decimalForProgress(goal.target.amount)}
                    value={decimalForProgress(goal.saved_amount.amount)}
                  />
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>
      <Section title="Счета" subtitle="Остатки получены из ledger API">
        <ResponsiveDataView
          caption="Счета и остатки"
          columns={[
            { key: "name", label: "Счёт", render: (row: AccountResponse) => row.name },
            { key: "kind", label: "Тип", render: (row: AccountResponse) => accountKind(row.kind) },
            {
              key: "balance",
              label: "Остаток",
              numeric: true,
              render: (row: AccountResponse) => money(row.balance, profile),
            },
          ]}
          getKey={(row) => row.id}
          rows={accounts}
        />
      </Section>
      {data.anomalies.length > 0 ? (
        <Notice title="Изменения, заслуживающие внимания">
          {data.anomalies.map((item) => item.rationale).join(" · ")}
        </Notice>
      ) : null}
    </Page>
  );
}

function AccountsPage(props: WorkspaceProps) {
  const { api, profile } = props;
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [categoryOpen, setCategoryOpen] = useState(false);
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"cash" | "bank" | "other_asset">("bank");
  const [amount, setAmount] = useState("");
  const [categoryName, setCategoryName] = useState("");
  const [categoryKind, setCategoryKind] = useState<CategoryKind>("expense");
  const [groupName, setGroupName] = useState("");
  const [error, setError] = useState<string>();
  const [editing, setEditing] = useState<AccountResponse>();
  const [editName, setEditName] = useState("");
  const [editKind, setEditKind] = useState<"bank" | "cash" | "other_asset">("bank");
  const [editBalance, setEditBalance] = useState("");
  const [archiving, setArchiving] = useState<AccountResponse>();
  const categories = useQuery({ queryKey: ["categories"], queryFn: () => api.listCategories() });
  const groups = useQuery({
    queryKey: ["category-groups"],
    queryFn: () => api.listCategoryGroups(),
  });
  const createAccount = useMutation({
    mutationFn: api.createAccount.bind(api),
    onSuccess: async () => {
      const accounts = await api.listAccounts();
      props.onAccountsChanged(accounts);
      await invalidateFinance(queryClient);
      setOpen(false);
    },
  });
  const createGroup = useMutation({
    mutationFn: api.createCategoryGroup.bind(api),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["category-groups"] }),
  });
  const createCategory = useMutation({
    mutationFn: api.createCategory.bind(api),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["categories"] }),
  });
  const updateAccount = useMutation({
    mutationFn: ({ account, archived }: { account: AccountResponse; archived?: boolean }) => {
      const balance = parseLocalizedDecimal(editBalance, profile.locale);
      if (archived === undefined && balance === null) throw new Error("invalid_amount");
      return api.updateAccount(account.id, {
        version: account.version,
        name: archived === undefined ? editName : null,
        kind: archived === undefined ? editKind : null,
        balance:
          archived === undefined && balance !== null
            ? { amount: balance, currency: account.currency }
            : null,
        balance_occurred_at: archived === undefined ? new Date().toISOString() : null,
        archived: archived ?? null,
      });
    },
    onSuccess: async () => {
      const accounts = await api.listAccounts();
      props.onAccountsChanged(accounts);
      setEditing(undefined);
      setArchiving(undefined);
      await invalidateFinance(queryClient);
    },
  });
  async function submitAccount(event: FormEvent) {
    event.preventDefault();
    setError(undefined);
    const parsed =
      amount === "" || /^0(?:[.,]0+)?$/.test(amount.trim())
        ? undefined
        : parseLocalizedDecimal(amount, profile.locale);
    if (parsed === null) {
      setError("Проверьте сумму.");
      return;
    }
    try {
      await createAccount.mutateAsync({
        name,
        kind,
        currency: profile.base_currency,
        opening_balance:
          parsed === undefined ? null : { amount: parsed, currency: profile.base_currency },
        opening_balance_occurred_at:
          parsed === undefined
            ? null
            : operationInstant(todayIsoDate(new Date(), profile.timezone), profile.timezone),
      });
    } catch (cause) {
      setError(apiErrorMessage(cause));
    }
  }
  return (
    <Page
      title="Счета и категории"
      eyebrow="Структура денег"
      actions={
        <>
          <Button
            onClick={() => {
              setCategoryOpen(true);
            }}
            variant="secondary"
          >
            Категории
          </Button>
          <Button
            onClick={() => {
              setOpen(true);
            }}
          >
            Новый счёт
          </Button>
        </>
      }
    >
      <ResponsiveDataView
        caption="Счета"
        columns={[
          { key: "name", label: "Счёт", render: (row: AccountResponse) => row.name },
          { key: "kind", label: "Тип", render: (row: AccountResponse) => accountKind(row.kind) },
          {
            key: "balance",
            label: "Остаток",
            numeric: true,
            render: (row: AccountResponse) => money(row.balance, profile),
          },
          {
            key: "actions",
            label: "Действия",
            render: (row: AccountResponse) => (
              <div className="inline-actions">
                <Button
                  variant="quiet"
                  onClick={() => {
                    setEditName(row.name);
                    setEditKind(
                      row.kind === "cash" || row.kind === "other_asset" ? row.kind : "bank",
                    );
                    setEditBalance(row.balance.amount);
                    setEditing(row);
                  }}
                >
                  Изменить
                </Button>
                <Button
                  variant="quiet"
                  onClick={() => {
                    setArchiving(row);
                  }}
                >
                  Удалить
                </Button>
              </div>
            ),
          },
        ]}
        getKey={(row) => row.id}
        rows={props.accounts}
      />
      <Dialog
        open={open}
        onClose={() => {
          setOpen(false);
        }}
        title="Новый счёт"
        description="Начальный остаток будет отдельной проводкой."
      >
        <form className="form-stack" onSubmit={(event) => void submitAccount(event)}>
          <InputField
            label="Название счёта"
            required
            value={name}
            onChange={(e) => {
              setName(e.target.value);
            }}
          />
          <SelectField
            label="Тип счёта"
            value={kind}
            onChange={(e) => {
              setKind(e.target.value as typeof kind);
            }}
          >
            <option value="bank">Банковский</option>
            <option value="cash">Наличные</option>
            <option value="other_asset">Иной актив</option>
          </SelectField>
          <MoneyInput
            label="Начальный остаток"
            currency={profile.base_currency}
            locale={profile.locale}
            value={amount}
            onChange={setAmount}
          />
          <FormError error={error ?? mutationError(createAccount.error)} />
          <Button loading={createAccount.isPending} type="submit">
            Создать счёт
          </Button>
        </form>
      </Dialog>
      <Dialog
        open={editing !== undefined}
        onClose={() => {
          setEditing(undefined);
        }}
        title="Изменить счёт"
        description="Изменение остатка сохранится отдельной корректирующей операцией."
      >
        <form
          className="form-stack"
          onSubmit={(event) => {
            event.preventDefault();
            if (editing !== undefined) updateAccount.mutate({ account: editing });
          }}
        >
          <InputField
            label="Название счёта"
            required
            value={editName}
            onChange={(event) => {
              setEditName(event.target.value);
            }}
          />
          <SelectField
            label="Тип счёта"
            value={editKind}
            onChange={(event) => {
              setEditKind(event.target.value as typeof editKind);
            }}
          >
            <option value="bank">Банковский</option>
            <option value="cash">Наличные</option>
            <option value="other_asset">Иной актив</option>
          </SelectField>
          <MoneyInput
            label="Текущий остаток"
            currency={editing?.currency ?? profile.base_currency}
            locale={profile.locale}
            value={editBalance}
            onChange={setEditBalance}
          />
          <FormError error={mutationError(updateAccount.error)} />
          <Button loading={updateAccount.isPending} type="submit">
            Сохранить изменения
          </Button>
        </form>
      </Dialog>
      <Dialog
        open={archiving !== undefined}
        onClose={() => {
          setArchiving(undefined);
        }}
        title="Удалить счёт?"
        description="Счёт исчезнет из активных списков, но его операции и аудит сохранятся."
      >
        <FormError error={mutationError(updateAccount.error)} />
        <Button
          loading={updateAccount.isPending}
          onClick={() => {
            if (archiving !== undefined)
              updateAccount.mutate({ account: archiving, archived: true });
          }}
        >
          Удалить счёт
        </Button>
      </Dialog>
      <Dialog
        open={categoryOpen}
        onClose={() => {
          setCategoryOpen(false);
        }}
        title="Категории и группы"
        description="Группы формируют структуру отчётов."
      >
        <div className="workspace-grid">
          <form
            className="form-stack"
            onSubmit={(e) => {
              e.preventDefault();
              void createGroup.mutateAsync({ name: groupName }).then(() => {
                setGroupName("");
              });
            }}
          >
            <InputField
              label="Название группы"
              required
              value={groupName}
              onChange={(e) => {
                setGroupName(e.target.value);
              }}
            />
            <Button loading={createGroup.isPending} type="submit">
              Добавить группу
            </Button>
          </form>
          <form
            className="form-stack"
            onSubmit={(e) => {
              e.preventDefault();
              void createCategory
                .mutateAsync({ name: categoryName, kind: categoryKind })
                .then(() => {
                  setCategoryName("");
                });
            }}
          >
            <InputField
              label="Название категории"
              required
              value={categoryName}
              onChange={(e) => {
                setCategoryName(e.target.value);
              }}
            />
            <SelectField
              label="Назначение"
              value={categoryKind}
              onChange={(e) => {
                setCategoryKind(e.target.value as CategoryKind);
              }}
            >
              <option value="expense">Расход</option>
              <option value="income">Доход</option>
            </SelectField>
            <Button loading={createCategory.isPending} type="submit">
              Добавить категорию
            </Button>
          </form>
        </div>
        <FormError error={mutationError(createGroup.error ?? createCategory.error)} />
        <ul className="clean-list">
          {(groups.data ?? []).map((group) => (
            <li key={group.id}>
              <strong>{group.name}</strong>
              <span>{group.categories.length} категорий</span>
            </li>
          ))}
        </ul>
        <p className="field-note">Всего категорий: {categories.data?.length ?? 0}</p>
      </Dialog>
    </Page>
  );
}

function TransactionsPage({ accounts, api, profile }: WorkspaceProps) {
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<TransactionFilters>({ limit: 20 });
  const [applied, setApplied] = useState<TransactionFilters>({ limit: 20 });
  const [history, setHistory] = useState<(string | undefined)[]>([]);
  const [editorOpen, setEditorOpen] = useState(false);
  const [kind, setKind] = useState<"income" | "expense" | "transfer" | "adjustment">("expense");
  const [selectedAccountId, setAccountId] = useState(accounts[0]?.id ?? "");
  const [selectedDestinationId, setDestinationId] = useState(accounts[1]?.id ?? "");
  const [categoryName, setCategoryName] = useState("");
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [occurredOn, setOccurredOn] = useState(todayIsoDate(new Date(), profile.timezone));
  const [reversing, setReversing] = useState<TransactionResponse>();
  const [reason, setReason] = useState("");
  const [editing, setEditing] = useState<TransactionResponse>();
  const [error, setError] = useState<string>();
  const transactions = useQuery({
    queryKey: ["transactions", applied],
    queryFn: () => api.listTransactions(applied),
  });
  const categories = useQuery({ queryKey: ["categories"], queryFn: () => api.listCategories() });
  const deposits = useQuery({ queryKey: ["deposits"], queryFn: () => api.listDeposits() });
  const instruments = financialInstruments(accounts, deposits.data ?? []);
  const accountId = instruments.some((item) => item.id === selectedAccountId)
    ? selectedAccountId
    : (instruments[0]?.id ?? "");
  const destinationId = instruments.some(
    (item) => item.id === selectedDestinationId && item.id !== accountId,
  )
    ? selectedDestinationId
    : (instruments.find((item) => item.id !== accountId)?.id ?? "");
  async function resolveCategory(): Promise<CategoryResponse> {
    const normalized = categoryName.trim();
    if (normalized === "") throw new Error("category_required");
    const existing = (categories.data ?? []).find(
      (category) =>
        category.kind === kind &&
        category.name.localeCompare(normalized, profile.locale, { sensitivity: "accent" }) === 0,
    );
    if (existing !== undefined) return existing;
    const created = await api.createCategory({ name: normalized, kind: kind as CategoryKind });
    await queryClient.invalidateQueries({ queryKey: ["categories"] });
    return created;
  }
  const create = useMutation({
    mutationFn: async () => {
      const parsed = parseLocalizedDecimal(amount, profile.locale);
      if (parsed === null) throw new Error("invalid_amount");
      const occurred_at = operationInstant(occurredOn, profile.timezone);
      if (kind === "transfer")
        return api.createTransfer({
          source_account_id: accountId,
          destination_account_id: destinationId,
          money: {
            amount: parsed,
            currency: instrumentCurrency(instruments, accountId, profile.base_currency),
          },
          occurred_at,
          description,
        });
      if (kind === "adjustment") {
        if (description.trim() === "") throw new Error("description_required");
        return api.createAdjustment({
          account_id: accountId,
          money: {
            amount: parsed,
            currency: instrumentCurrency(instruments, accountId, profile.base_currency),
          },
          occurred_at,
          description,
        });
      }
      const category = await resolveCategory();
      return api.createOperation(kind, {
        account_id: accountId,
        category_id: category.id,
        money: {
          amount: parsed,
          currency: instrumentCurrency(instruments, accountId, profile.base_currency),
        },
        occurred_at,
        description,
      });
    },
    onSuccess: async () => {
      setEditorOpen(false);
      setAmount("");
      setDescription("");
      setEditing(undefined);
      await invalidateFinance(queryClient);
    },
  });
  const correct = useMutation({
    mutationFn: async () => {
      if (editing === undefined) throw new Error("missing_transaction");
      const parsed = parseLocalizedDecimal(amount, profile.locale);
      if (parsed === null) throw new Error("invalid_amount");
      const category = kind === "income" || kind === "expense" ? await resolveCategory() : null;
      return api.correctTransaction(editing.id, {
        kind,
        account_id: accountId,
        destination_account_id: kind === "transfer" ? destinationId : null,
        category_id: category?.id ?? null,
        money: {
          amount: parsed,
          currency: instrumentCurrency(instruments, accountId, profile.base_currency),
        },
        occurred_at: operationInstant(occurredOn, profile.timezone),
        description,
        reason,
        tag_ids: [],
      });
    },
    onSuccess: async () => {
      setEditorOpen(false);
      setEditing(undefined);
      setReason("");
      await invalidateFinance(queryClient);
    },
  });
  const reverse = useMutation({
    mutationFn: () =>
      api.reverseTransaction(reversing!.id, { occurred_at: reversing!.occurred_at, reason }),
    onSuccess: async () => {
      setReversing(undefined);
      setReason("");
      await invalidateFinance(queryClient);
    },
  });
  async function exportCsv() {
    try {
      const csv = await api.exportTransactions(applied);
      const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "transactions.csv";
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (cause) {
      setError(apiErrorMessage(cause));
    }
  }
  function beginCorrection(row: TransactionResponse) {
    if (!["income", "expense", "transfer", "adjustment"].includes(row.kind)) return;
    const knownIds = new Set(instruments.map((item) => item.id));
    const assetPostings = row.postings.filter((posting) => knownIds.has(posting.account_id));
    const primary =
      row.kind === "transfer"
        ? assetPostings.find((posting) => posting.money.amount.startsWith("-"))
        : assetPostings[0];
    const destination =
      row.kind === "transfer"
        ? assetPostings.find((posting) => !posting.money.amount.startsWith("-"))
        : undefined;
    if (primary === undefined) {
      setError("Не удалось определить актив операции для исправления.");
      return;
    }
    setEditing(row);
    setKind(row.kind as "income" | "expense" | "transfer" | "adjustment");
    setAccountId(primary.account_id);
    setDestinationId(destination?.account_id ?? "");
    setCategoryName(
      (categories.data ?? []).find((category) => category.id === row.category_id)?.name ?? "",
    );
    setAmount(
      row.kind === "adjustment" ? primary.money.amount : primary.money.amount.replace(/^-/, ""),
    );
    setDescription(row.description);
    setOccurredOn(todayIsoDate(new Date(row.occurred_at), profile.timezone));
    setReason("Исправление данных операции");
    setEditorOpen(true);
  }
  const rows = transactions.data?.items ?? [];
  return (
    <Page
      title="Журнал операций"
      eyebrow="Доходы, расходы и переводы"
      actions={
        <>
          <Button variant="secondary" onClick={() => void exportCsv()}>
            Экспорт CSV
          </Button>
          <Button
            onClick={() => {
              setEditing(undefined);
              setReason("");
              setKind("expense");
              setAmount("");
              setDescription("");
              setCategoryName("");
              setOccurredOn(todayIsoDate(new Date(), profile.timezone));
              setError(undefined);
              create.reset();
              correct.reset();
              setEditorOpen(true);
            }}
          >
            Новая операция
          </Button>
        </>
      }
    >
      <form
        className="filter-bar"
        aria-label="Фильтры журнала"
        onSubmit={(e) => {
          e.preventDefault();
          setHistory([]);
          setApplied({ ...filters, cursor: undefined });
        }}
      >
        <InputField
          label="Поиск"
          value={filters.search ?? ""}
          onChange={(e) => {
            setFilters({ ...filters, search: e.target.value || undefined });
          }}
        />
        <SelectField
          label="Счёт"
          value={filters.accountId ?? ""}
          onChange={(e) => {
            setFilters({ ...filters, accountId: e.target.value || undefined });
          }}
        >
          <option value="">Все счета</option>
          {instruments.map((instrument) => (
            <option key={instrument.id} value={instrument.id}>
              {instrument.name}
            </option>
          ))}
        </SelectField>
        <SelectField
          label="Тип"
          value={filters.kind ?? ""}
          onChange={(e) => {
            setFilters({
              ...filters,
              kind: (e.target.value || undefined) as TransactionKind | undefined,
            });
          }}
        >
          <option value="">Все типы</option>
          {Object.entries(transactionLabels).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </SelectField>
        <DateControl
          label="С даты"
          value={filters.occurredFrom?.slice(0, 10) ?? ""}
          onChange={(e) => {
            setFilters({ ...filters, occurredFrom: e.target.value || undefined });
          }}
        />
        <DateControl
          label="По дату"
          value={filters.occurredTo?.slice(0, 10) ?? ""}
          onChange={(e) => {
            setFilters({ ...filters, occurredTo: e.target.value || undefined });
          }}
        />
        <Button type="submit">Применить</Button>
      </form>
      <FormError error={error} />
      {transactions.isLoading ? (
        <LoadingState label="Загружаем журнал" />
      ) : transactions.error ? (
        <QueryError error={transactions.error} retry={() => void transactions.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState
          title="Операций не найдено"
          description="Измените фильтры или добавьте операцию."
        />
      ) : (
        <>
          <ResponsiveDataView
            caption="Журнал операций"
            columns={[
              {
                key: "date",
                label: "Дата",
                render: (row: TransactionResponse) => dateTime(row.occurred_at, profile),
              },
              {
                key: "description",
                label: "Операция",
                render: (row: TransactionResponse) => (
                  <>
                    <strong>{row.description || transactionLabels[row.kind]}</strong>
                    <small className="subtle">
                      {transactionLabels[row.kind]} · {row.source}
                    </small>
                  </>
                ),
              },
              {
                key: "amount",
                label: "Сумма",
                numeric: true,
                render: (row: TransactionResponse) =>
                  row.postings
                    .filter((posting) => instruments.some((item) => item.id === posting.account_id))
                    .map(
                      (posting) =>
                        `${instruments.find((item) => item.id === posting.account_id)?.name ?? "Актив"}: ${money(posting.money, profile)}`,
                    )
                    .join(" → "),
              },
              {
                key: "actions",
                label: "Действия",
                render: (row: TransactionResponse) =>
                  row.kind === "reversal" || row.reversed_by_id != null ? (
                    <span>
                      {row.kind === "reversal" ? "Сторно" : "Отменена"} · история сохранена
                    </span>
                  ) : row.kind === "interest" ? (
                    <span>По условиям вклада</span>
                  ) : (
                    <div className="inline-actions">
                      <Button
                        variant="quiet"
                        onClick={() => {
                          beginCorrection(row);
                        }}
                      >
                        Изменить
                      </Button>
                      <Button
                        variant="quiet"
                        onClick={() => {
                          setReason("Удаление ошибочной операции");
                          setReversing(row);
                        }}
                      >
                        Удалить
                      </Button>
                    </div>
                  ),
              },
            ]}
            getKey={(row) => row.id}
            rows={rows}
          />
          <div className="pagination">
            <Button
              variant="secondary"
              disabled={history.length === 0}
              onClick={() => {
                const next = [...history];
                const cursor = next.pop();
                setHistory(next);
                setApplied({ ...applied, cursor });
              }}
            >
              Назад
            </Button>
            <span>Страница {history.length + 1}</span>
            <Button
              variant="secondary"
              disabled={transactions.data?.next_cursor === null}
              onClick={() => {
                setHistory([...history, applied.cursor]);
                setApplied({ ...applied, cursor: transactions.data?.next_cursor ?? undefined });
              }}
            >
              Далее
            </Button>
          </div>
        </>
      )}
      <Dialog
        open={editorOpen}
        onClose={() => {
          setEditorOpen(false);
          setEditing(undefined);
        }}
        title={editing === undefined ? "Новая операция" : "Изменить операцию"}
        description={
          editing === undefined
            ? "Баланс и отчёты пересчитает сервер по проводкам."
            : "Сервер атомарно сторнирует исходную проводку и создаст исправленную."
        }
      >
        <form
          className="form-stack"
          onSubmit={(e) => {
            e.preventDefault();
            setError(undefined);
            const mutation = editing === undefined ? create : correct;
            void mutation.mutateAsync().catch((cause) => {
              setError(
                cause instanceof Error && cause.message === "invalid_amount"
                  ? "Проверьте сумму."
                  : cause instanceof Error && cause.message === "category_required"
                    ? "Выберите категорию."
                    : cause instanceof Error && cause.message === "description_required"
                      ? "Укажите причину корректировки."
                      : apiErrorMessage(cause),
              );
            });
          }}
        >
          <SelectField
            label="Тип операции"
            value={kind}
            onChange={(e) => {
              setKind(e.target.value as typeof kind);
            }}
          >
            <option value="expense">Расход</option>
            <option value="income">Доход</option>
            <option value="transfer">Перевод</option>
            <option value="adjustment">Корректировка остатка</option>
          </SelectField>
          <SelectField
            label={kind === "transfer" ? "Со счёта" : "Счёт"}
            value={accountId}
            onChange={(e) => {
              setAccountId(e.target.value);
            }}
          >
            {instruments.map((instrument) => (
              <option key={instrument.id} value={instrument.id}>
                {instrument.name}
              </option>
            ))}
          </SelectField>
          {kind === "transfer" ? (
            <SelectField
              label="На счёт"
              value={destinationId}
              onChange={(e) => {
                setDestinationId(e.target.value);
              }}
            >
              {instruments
                .filter((instrument) => instrument.id !== accountId)
                .map((instrument) => (
                  <option key={instrument.id} value={instrument.id}>
                    {instrument.name}
                  </option>
                ))}
            </SelectField>
          ) : kind === "adjustment" ? null : (
            <>
              <InputField
                label="Категория"
                list="transaction-category-suggestions"
                hint="Выберите предложение или введите новое название — категория создастся при сохранении."
                value={categoryName}
                onChange={(e) => {
                  setCategoryName(e.target.value);
                }}
              />
              <datalist id="transaction-category-suggestions">
                {(categories.data ?? [])
                  .filter((category) => category.kind === kind)
                  .map((category) => (
                    <option key={category.id} value={category.name} />
                  ))}
              </datalist>
            </>
          )}
          <MoneyInput
            label="Сумма"
            currency={instrumentCurrency(instruments, accountId, profile.base_currency)}
            locale={profile.locale}
            value={amount}
            onChange={setAmount}
          />
          <DateControl
            label="Дата"
            required
            value={occurredOn}
            onChange={(e) => {
              setOccurredOn(e.target.value);
            }}
          />
          <InputField
            label="Комментарий"
            value={description}
            onChange={(e) => {
              setDescription(e.target.value);
            }}
          />
          {editing === undefined ? null : (
            <InputField
              label="Причина исправления"
              required
              value={reason}
              onChange={(event) => {
                setReason(event.target.value);
              }}
            />
          )}
          <FormError error={error ?? mutationError(create.error ?? correct.error)} />
          <Button loading={create.isPending || correct.isPending} type="submit">
            {editing === undefined ? "Провести" : "Сохранить исправление"}
          </Button>
        </form>
      </Dialog>
      <Dialog
        open={reversing !== undefined}
        onClose={() => {
          setReversing(undefined);
        }}
        title="Удалить операцию?"
        description="Исходная проводка останется в аудите. Сервер создаст сторно; баланс и отчёты пересчитаются."
      >
        <form
          className="form-stack"
          onSubmit={(e) => {
            e.preventDefault();
            reverse.mutate();
          }}
        >
          <InputField
            label="Причина удаления"
            required
            value={reason}
            onChange={(e) => {
              setReason(e.target.value);
            }}
          />
          <FormError error={mutationError(reverse.error)} />
          <Button loading={reverse.isPending} type="submit">
            Удалить операцию (сторнировать)
          </Button>
        </form>
      </Dialog>
    </Page>
  );
}

function RecurringPage({ accounts, api, profile }: WorkspaceProps) {
  const queryClient = useQueryClient();
  const rules = useQuery({ queryKey: ["recurring"], queryFn: () => api.listRecurringRules() });
  const categories = useQuery({ queryKey: ["categories"], queryFn: () => api.listCategories() });
  const deposits = useQuery({ queryKey: ["deposits"], queryFn: () => api.listDeposits() });
  const instruments = financialInstruments(accounts, deposits.data ?? []);
  const [open, setOpen] = useState(false);
  const [frequency, setFrequency] = useState<RecurrenceFrequency>("monthly");
  const [kind, setKind] = useState<"income" | "expense" | "transfer">("expense");
  const [selectedAccountId, setAccountId] = useState(accounts[0]?.id ?? "");
  const [selectedDestinationId, setDestinationId] = useState(accounts[1]?.id ?? "");
  const accountId = instruments.some((item) => item.id === selectedAccountId)
    ? selectedAccountId
    : (instruments[0]?.id ?? "");
  const destinationId = instruments.some(
    (item) => item.id === selectedDestinationId && item.id !== accountId,
  )
    ? selectedDestinationId
    : (instruments.find((item) => item.id !== accountId)?.id ?? "");
  const [categoryName, setCategoryName] = useState("");
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [startsOn, setStartsOn] = useState(todayIsoDate(new Date(), profile.timezone));
  const [localTime, setLocalTime] = useState("09:00");
  const [missingPolicy, setMissingPolicy] = useState<"last_day" | "skip">("last_day");
  const [preview, setPreview] = useState<PreviewOccurrenceResponse[]>([]);
  const payload = (categoryId: string | null) => ({
    frequency,
    starts_on: startsOn,
    local_time: localTime,
    timezone: profile.timezone,
    missing_day_policy: missingPolicy,
    operation: {
      kind,
      account_id: accountId,
      destination_account_id: kind === "transfer" ? destinationId : null,
      category_id: kind === "transfer" ? null : categoryId,
      money: {
        amount: parseLocalizedDecimal(amount, profile.locale) ?? amount,
        currency: instrumentCurrency(instruments, accountId, profile.base_currency),
      },
      description,
    },
  });
  const previewMutation = useMutation({
    mutationFn: () =>
      api.previewRecurringOccurrences({
        frequency,
        starts_on: startsOn,
        local_time: localTime,
        timezone: profile.timezone,
        missing_day_policy: missingPolicy,
        count: 6,
      }),
    onSuccess: setPreview,
  });
  const create = useMutation({
    mutationFn: async () => {
      const parsed = parseLocalizedDecimal(amount, profile.locale);
      if (parsed === null) throw new Error("invalid_amount");
      let categoryId: string | null = null;
      if (kind !== "transfer") {
        const normalized = categoryName.trim();
        if (normalized === "") throw new Error("category_required");
        const existing = (categories.data ?? []).find(
          (category) =>
            category.kind === kind &&
            category.name.localeCompare(normalized, profile.locale, { sensitivity: "base" }) === 0,
        );
        const category = existing ?? (await api.createCategory({ name: normalized, kind: kind }));
        categoryId = category.id;
        if (existing === undefined)
          await queryClient.invalidateQueries({ queryKey: ["categories"] });
      }
      return api.createRecurringRule({
        ...payload(categoryId),
        operation: {
          ...payload(categoryId).operation,
          money: {
            amount: parsed,
            currency: instrumentCurrency(instruments, accountId, profile.base_currency),
          },
        },
      });
    },
    onSuccess: async () => {
      setOpen(false);
      await queryClient.invalidateQueries({ queryKey: ["recurring"] });
    },
  });
  const toggle = useMutation({
    mutationFn: ({ rule, paused }: { rule: RecurringRuleResponse; paused: boolean }) =>
      api.setRecurringRulePaused(rule, paused),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["recurring"] }),
  });
  return (
    <Page
      title="Регулярные операции"
      eyebrow="Расписание"
      actions={
        <Button
          onClick={() => {
            setOpen(true);
          }}
        >
          Новое правило
        </Button>
      }
    >
      <Notice title={`Часовой пояс: ${profile.timezone}`}>
        Локальное время хранится вместе с IANA timezone. Для несуществующего дня месяца правило явно
        выбирается ниже.
      </Notice>
      {rules.isLoading ? (
        <LoadingState label="Загружаем правила" />
      ) : rules.error ? (
        <QueryError error={rules.error} retry={() => void rules.refetch()} />
      ) : (rules.data ?? []).length === 0 ? (
        <EmptyState
          title="Правил пока нет"
          description="Создайте подписку, зарплату или регулярный перевод."
        />
      ) : (
        <ResponsiveDataView
          caption="Регулярные правила"
          columns={[
            {
              key: "operation",
              label: "Операция",
              render: (row: RecurringRuleResponse) =>
                row.operation.description || transactionLabels[row.operation.kind],
            },
            {
              key: "schedule",
              label: "Расписание",
              render: (row: RecurringRuleResponse) =>
                `${frequencyLabel(row.frequency)}, ${row.local_time} (${row.timezone}); ${row.missing_day_policy === "last_day" ? "последний день" : "пропуск"}`,
            },
            {
              key: "next",
              label: "Следующая",
              render: (row: RecurringRuleResponse) =>
                row.next_occurrence_at === null ? "—" : dateTime(row.next_occurrence_at, profile),
            },
            {
              key: "state",
              label: "Состояние",
              render: (row: RecurringRuleResponse) => (
                <Button
                  variant="quiet"
                  loading={toggle.isPending}
                  onClick={() => {
                    toggle.mutate({ rule: row, paused: row.status === "active" });
                  }}
                >
                  {row.status === "active" ? "Приостановить" : "Возобновить"}
                </Button>
              ),
            },
          ]}
          getKey={(row) => row.id}
          rows={rules.data ?? []}
        />
      )}
      <Dialog
        open={open}
        onClose={() => {
          setOpen(false);
        }}
        title="Новое регулярное правило"
        description="Просмотрите ближайшие срабатывания до сохранения."
      >
        <form
          className="form-stack"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <div className="form-grid">
            <SelectField
              label="Операция"
              value={kind}
              onChange={(e) => {
                setKind(e.target.value as typeof kind);
              }}
            >
              <option value="expense">Расход</option>
              <option value="income">Доход</option>
              <option value="transfer">Перевод</option>
            </SelectField>
            <SelectField
              label="Периодичность"
              value={frequency}
              onChange={(e) => {
                setFrequency(e.target.value as RecurrenceFrequency);
              }}
            >
              <option value="daily">Ежедневно</option>
              <option value="weekly">Еженедельно</option>
              <option value="monthly">Ежемесячно</option>
              <option value="yearly">Ежегодно</option>
            </SelectField>
          </div>
          <SelectField
            label="Счёт"
            value={accountId}
            onChange={(e) => {
              setAccountId(e.target.value);
            }}
          >
            {instruments.map((instrument) => (
              <option key={instrument.id} value={instrument.id}>
                {instrument.name}
              </option>
            ))}
          </SelectField>
          {kind === "transfer" ? (
            <SelectField
              label="Счёт назначения"
              value={destinationId}
              onChange={(e) => {
                setDestinationId(e.target.value);
              }}
            >
              {instruments
                .filter((instrument) => instrument.id !== accountId)
                .map((instrument) => (
                  <option key={instrument.id} value={instrument.id}>
                    {instrument.name}
                  </option>
                ))}
            </SelectField>
          ) : (
            <>
              <InputField
                label="Категория"
                list="recurring-category-suggestions"
                hint="Выберите существующую или введите новую категорию."
                value={categoryName}
                onChange={(e) => {
                  setCategoryName(e.target.value);
                }}
              />
              <datalist id="recurring-category-suggestions">
                {(categories.data ?? [])
                  .filter((category) => category.kind === kind)
                  .map((category) => (
                    <option key={category.id} value={category.name} />
                  ))}
              </datalist>
            </>
          )}
          <MoneyInput
            label="Сумма"
            currency={instrumentCurrency(instruments, accountId, profile.base_currency)}
            locale={profile.locale}
            value={amount}
            onChange={setAmount}
          />
          <InputField
            label="Описание"
            value={description}
            onChange={(e) => {
              setDescription(e.target.value);
            }}
          />
          <div className="form-grid">
            <DateControl
              label="Начало"
              value={startsOn}
              onChange={(e) => {
                setStartsOn(e.target.value);
              }}
            />
            <InputField
              label="Локальное время"
              type="time"
              value={localTime}
              onChange={(e) => {
                setLocalTime(e.target.value);
              }}
            />
          </div>
          <SelectField
            label="Если дня нет в месяце"
            value={missingPolicy}
            onChange={(e) => {
              setMissingPolicy(e.target.value as typeof missingPolicy);
            }}
          >
            <option value="last_day">Последний день месяца</option>
            <option value="skip">Пропустить месяц</option>
          </SelectField>
          <p className="field-note">Timezone: {profile.timezone}</p>
          <Button
            variant="secondary"
            type="button"
            loading={previewMutation.isPending}
            onClick={() => {
              previewMutation.mutate();
            }}
          >
            Предпросмотр дат
          </Button>
          {preview.length > 0 ? (
            <ol className="preview-list">
              {preview.map((item) => (
                <li key={item.occurrence_at}>
                  {dateTime(item.local_at, profile)} <small>UTC: {item.occurrence_at}</small>
                </li>
              ))}
            </ol>
          ) : null}
          <FormError error={mutationError(previewMutation.error ?? create.error)} />
          <Button loading={create.isPending} type="submit">
            Сохранить правило
          </Button>
        </form>
      </Dialog>
    </Page>
  );
}

function DepositsPage({ api, profile }: WorkspaceProps) {
  const queryClient = useQueryClient();
  const deposits = useQuery({ queryKey: ["deposits"], queryFn: () => api.listDeposits() });
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<string>();
  const [editing, setEditing] = useState<DepositTermsResponse>();
  const [archiving, setArchiving] = useState<DepositTermsResponse>();
  const [name, setName] = useState("");
  const [openingBalance, setOpeningBalance] = useState("");
  const [openedOn, setOpenedOn] = useState(todayIsoDate(new Date(), profile.timezone));
  const [maturesOn, setMaturesOn] = useState(nextYearIso(profile.timezone));
  const [rate, setRate] = useState("10");
  const [firstRateEnds, setFirstRateEnds] = useState(nextYearIso(profile.timezone));
  const [secondRateEnabled, setSecondRateEnabled] = useState(false);
  const [secondRateStarts, setSecondRateStarts] = useState("");
  const [secondRateEnds, setSecondRateEnds] = useState("");
  const [secondRate, setSecondRate] = useState("");
  const [taxRate, setTaxRate] = useState("0");
  const [automaticInterest, setAutomaticInterest] = useState(true);
  const [capitalization, setCapitalization] = useState<"daily" | "monthly_calendar_end">(
    "monthly_calendar_end",
  );
  const [error, setError] = useState<string>();
  const selectedDeposit = (deposits.data ?? []).find((item) => item.id === selected);
  const asOf = todayIsoDate(new Date(), profile.timezone);
  const valuation = useQuery({
    queryKey: ["deposit-valuation", selected, asOf],
    queryFn: () => api.getDepositValuation(selected!, asOf),
    enabled: selected !== undefined,
  });
  const save = useMutation({
    mutationFn: async () => {
      const terms = {
        name,
        currency: editing?.currency ?? profile.base_currency,
        opened_on: openedOn,
        matures_on: maturesOn,
        rate_periods: [
          {
            starts_on: openedOn,
            ends_on: secondRateEnabled ? firstRateEnds : maturesOn,
            nominal_rate: { value: normalizeRate(rate) },
          },
          ...(secondRateEnabled
            ? [
                {
                  starts_on: secondRateStarts,
                  ends_on: secondRateEnds,
                  nominal_rate: { value: normalizeRate(secondRate) },
                },
              ]
            : []),
        ],
        capitalization_frequency: capitalization,
        day_count_convention: editing?.day_count_convention ?? ("actual_365_fixed" as const),
        rounding_policy: editing?.rounding_policy ?? ("half_even" as const),
        interest_rounding_frequency:
          editing?.interest_rounding_frequency ?? ("capitalization" as const),
        timezone: editing?.timezone ?? profile.timezone,
        cashflow_cutoff_time: editing?.cashflow_cutoff_time ?? "23:59:59",
        cashflow_cutoff_inclusive: editing?.cashflow_cutoff_inclusive ?? true,
        early_close_rule: {
          policy: editing?.early_close_rule.policy ?? ("forfeit_interest" as const),
          nominal_rate:
            editing?.early_close_rule.nominal_rate == null
              ? null
              : { value: editing.early_close_rule.nominal_rate },
        },
        tax_rate: { value: normalizeRate(taxRate) },
        automatic_interest: automaticInterest,
      };
      if (editing !== undefined)
        return api.updateDeposit(editing.id, { ...terms, version: editing.version });
      const parsed = parseLocalizedDecimal(openingBalance, profile.locale);
      if (parsed === null || parsed.startsWith("-")) throw new Error("invalid_amount");
      return api.createDeposit({
        ...terms,
        opening_balance: { amount: parsed, currency: profile.base_currency },
      });
    },
    onSuccess: async (value) => {
      setOpen(false);
      setEditing(undefined);
      setSelected(value.id);
      await invalidateFinance(queryClient);
    },
  });
  const archive = useMutation({
    mutationFn: (deposit: DepositTermsResponse) => api.archiveDeposit(deposit.id, deposit.version),
    onSuccess: async () => {
      setArchiving(undefined);
      setSelected(undefined);
      await invalidateFinance(queryClient);
    },
  });
  function newDeposit() {
    setEditing(undefined);
    setName("");
    setOpeningBalance("");
    setOpenedOn(todayIsoDate(new Date(), profile.timezone));
    setMaturesOn(nextYearIso(profile.timezone));
    setRate("10");
    setTaxRate("0");
    setAutomaticInterest(true);
    setSecondRateEnabled(false);
    setCapitalization("monthly_calendar_end");
    setError(undefined);
    setOpen(true);
  }
  function editDeposit(deposit: DepositTermsResponse) {
    const first = deposit.rate_periods[0];
    const second = deposit.rate_periods[1];
    setEditing(deposit);
    setName(deposit.name);
    setOpenedOn(deposit.opened_on);
    setMaturesOn(deposit.matures_on);
    setRate(rateToPercentInput(first?.nominal_rate ?? "0"));
    setTaxRate(rateToPercentInput(deposit.tax_rate));
    setAutomaticInterest(deposit.automatic_interest);
    setCapitalization(deposit.capitalization_frequency);
    setSecondRateEnabled(second !== undefined);
    setFirstRateEnds(first?.ends_on ?? deposit.matures_on);
    setSecondRateStarts(second?.starts_on ?? "");
    setSecondRateEnds(second?.ends_on ?? "");
    setSecondRate(rateToPercentInput(second?.nominal_rate ?? "0"));
    setError(undefined);
    setOpen(true);
  }
  return (
    <Page
      title="Вклады"
      eyebrow="Сложные проценты"
      actions={<Button onClick={newDeposit}>Добавить вклад</Button>}
    >
      <Notice title="Вклады и счета разделены">
        Начальная сумма задаётся здесь. Пополнения, снятия и переводы между счетами и вкладами
        создаются во вкладке «Операции».
      </Notice>
      {deposits.isLoading ? (
        <LoadingState label="Загружаем вклады" />
      ) : deposits.error ? (
        <QueryError error={deposits.error} retry={() => void deposits.refetch()} />
      ) : (deposits.data ?? []).length === 0 ? (
        <EmptyState
          title="Вкладов пока нет"
          description="Добавьте начальную сумму, ставку и срок — график рассчитается автоматически."
        />
      ) : (
        <div className="deposit-layout">
          <nav aria-label="Список вкладов" className="selection-list">
            {(deposits.data ?? []).map((deposit) => (
              <button
                className={selected === deposit.id ? "is-selected" : ""}
                key={deposit.id}
                onClick={() => {
                  setSelected(deposit.id);
                }}
                type="button"
              >
                <strong>{deposit.name}</strong>
                <span>
                  {deposit.opened_on} — {deposit.matures_on}
                </span>
                <small>
                  {percent(deposit.rate_periods[0]?.nominal_rate ?? "0", profile.locale)} ·{" "}
                  {deposit.capitalization_frequency === "daily" ? "ежедневно" : "ежемесячно"}
                </small>
              </button>
            ))}
          </nav>
          <div>
            {selectedDeposit === undefined ? (
              <EmptyState title="Выберите вклад" description="Справа появятся расчёт и график." />
            ) : (
              <>
                {selectedDeposit.automatic_interest ? null : (
                  <Notice title="Вклад из предыдущей версии">
                    Автоматические проводки пока выключены. Проверьте сумму и условия через
                    «Изменить вклад» и включите начисления. Если несколько старых вкладов используют
                    один остаток, сначала удалите дубли.
                  </Notice>
                )}
                <div className="section-actions">
                  <Button
                    variant="secondary"
                    onClick={() => {
                      editDeposit(selectedDeposit);
                    }}
                  >
                    Изменить вклад
                  </Button>
                  <Button
                    variant="quiet"
                    onClick={() => {
                      setArchiving(selectedDeposit);
                    }}
                  >
                    Удалить вклад
                  </Button>
                </div>
                {valuation.isLoading ? (
                  <LoadingState label="Рассчитываем сложные проценты" />
                ) : valuation.error ? (
                  <QueryError error={valuation.error} retry={() => void valuation.refetch()} />
                ) : valuation.data === undefined ? null : (
                  <DepositDetails value={valuation.data} profile={profile} />
                )}
              </>
            )}
          </div>
        </div>
      )}
      <Dialog
        open={open}
        onClose={() => {
          setOpen(false);
        }}
        title={editing === undefined ? "Новый вклад" : "Изменить вклад"}
        description="Введите ставку как банковский процент: 10 означает 10% годовых."
      >
        <form
          className="form-stack"
          onSubmit={(event) => {
            event.preventDefault();
            setError(undefined);
            if (compareIsoDates(openedOn, maturesOn) >= 0) {
              setError("Дата окончания должна быть позже открытия.");
              return;
            }
            void save.mutateAsync().catch((cause) => {
              setError(
                cause instanceof Error && cause.message === "invalid_amount"
                  ? "Введите положительную начальную сумму."
                  : apiErrorMessage(cause),
              );
            });
          }}
        >
          <InputField
            label="Название вклада"
            required
            value={name}
            onChange={(event) => {
              setName(event.target.value);
            }}
          />
          {editing === undefined ? (
            <MoneyInput
              label="Начальная сумма"
              currency={profile.base_currency}
              locale={profile.locale}
              value={openingBalance}
              onChange={setOpeningBalance}
            />
          ) : null}
          {editing === undefined ? (
            <p className="field-note">
              Если деньги сейчас на обычном счёте, укажите 0 и затем оформите перевод во вклад в
              разделе «Операции».
            </p>
          ) : null}
          <div className="form-grid">
            <DateControl
              label="Открытие"
              required
              value={openedOn}
              onChange={(e) => {
                setOpenedOn(e.target.value);
              }}
            />
            <DateControl
              label="Окончание"
              required
              value={maturesOn}
              onChange={(e) => {
                setMaturesOn(e.target.value);
              }}
            />
          </div>
          <div className="form-grid">
            <InputField
              label="Номинальная ставка, %"
              inputMode="decimal"
              required
              value={rate}
              onChange={(e) => {
                setRate(e.target.value);
              }}
            />
            <InputField
              label="Налог, %"
              inputMode="decimal"
              required
              value={taxRate}
              onChange={(e) => {
                setTaxRate(e.target.value);
              }}
            />
          </div>
          <SelectField
            label="Капитализация"
            value={capitalization}
            onChange={(e) => {
              setCapitalization(e.target.value as typeof capitalization);
            }}
          >
            <option value="monthly_calendar_end">Ежемесячно</option>
            <option value="daily">Ежедневно</option>
          </SelectField>
          <label className="consent-row">
            <input
              type="checkbox"
              checked={secondRateEnabled}
              onChange={(event) => {
                setSecondRateEnabled(event.target.checked);
              }}
            />
            <span>
              <strong>Ставка меняется в течение срока</strong>
              <small>Добавить второй непрерывный период ставки.</small>
            </span>
          </label>
          {secondRateEnabled ? (
            <div className="form-grid">
              <DateControl
                label="Конец первого периода"
                value={firstRateEnds}
                onChange={(e) => {
                  setFirstRateEnds(e.target.value);
                }}
              />
              <DateControl
                label="Начало второго периода"
                value={secondRateStarts}
                onChange={(e) => {
                  setSecondRateStarts(e.target.value);
                }}
              />
              <DateControl
                label="Конец второго периода"
                value={secondRateEnds}
                onChange={(e) => {
                  setSecondRateEnds(e.target.value);
                }}
              />
              <InputField
                label="Ставка второго периода, %"
                value={secondRate}
                onChange={(e) => {
                  setSecondRate(e.target.value);
                }}
              />
            </div>
          ) : null}
          <FormError error={error ?? mutationError(save.error)} />
          <label className="consent-row">
            <input
              type="checkbox"
              checked={automaticInterest}
              onChange={(event) => {
                setAutomaticInterest(event.target.checked);
              }}
            />
            <span>Автоматически начислять проценты и добавлять их в журнал</span>
          </label>
          <Button loading={save.isPending} type="submit">
            {editing === undefined ? "Создать вклад" : "Сохранить изменения"}
          </Button>
        </form>
      </Dialog>
      <Dialog
        open={archiving !== undefined}
        onClose={() => {
          setArchiving(undefined);
        }}
        title="Удалить вклад?"
        description="Вклад исчезнет из активного списка. Операции и история изменений сохранятся."
      >
        <FormError error={mutationError(archive.error)} />
        <Button
          loading={archive.isPending}
          onClick={() => {
            if (archiving !== undefined) archive.mutate(archiving);
          }}
        >
          Удалить вклад
        </Button>
      </Dialog>
    </Page>
  );
}

function DepositDetails({
  value,
  profile,
}: {
  value: DepositValuationResponse;
  profile: ProfileResponse;
}) {
  return (
    <Section
      title="Оценка вклада"
      subtitle={`Алгоритм ${value.algorithm_version} · на ${value.as_of}`}
    >
      <div className="metric-strip">
        <Metric label="Текущая стоимость" value={money(value.current_value, profile)} />
        <Metric label="Начисленный доход" value={money(value.earned_interest, profile)} />
        <Metric label="К погашению" value={money(value.projected_maturity_value, profile)} />
        <Metric
          label="Эффективная доходность"
          value={
            value.effective_yield === null
              ? "Недостаточно данных"
              : percent(value.effective_yield, profile.locale)
          }
        />
      </div>
      <Notice title="Автоматический расчёт">
        Проценты за завершённые периоды автоматически добавляются в журнал и участвуют в следующих
        начислениях. Остаток после капитализации: {money(value.ledger_balance, profile)}. Условия:
        Actual/365, округление до копеек при капитализации.
      </Notice>
      <h3>План начислений</h3>
      <ResponsiveDataView
        caption="График начислений"
        columns={[
          {
            key: "period",
            label: "Период",
            render: (row: DepositValuationResponse["schedule"][number]) =>
              `${row.accrual_starts_on} — ${row.accrual_ends_on}`,
          },
          {
            key: "cashflow",
            label: "Денежный поток",
            numeric: true,
            render: (row: DepositValuationResponse["schedule"][number]) =>
              money(row.cashflow, profile),
          },
          {
            key: "interest",
            label: "Чистые проценты",
            numeric: true,
            render: (row: DepositValuationResponse["schedule"][number]) =>
              money(row.net_interest, profile),
          },
          {
            key: "balance",
            label: "Остаток",
            numeric: true,
            render: (row: DepositValuationResponse["schedule"][number]) =>
              money(row.closing_balance, profile),
          },
        ]}
        getKey={(row) => `${row.accrual_starts_on}-${row.posting_date}`}
        rows={value.schedule}
      />
    </Section>
  );
}

function AnalyticsPage({ api, profile }: WorkspaceProps) {
  const initialRange = currentAnalyticsRange("month", profile.timezone);
  const [start, setStart] = useState(initialRange.start);
  const [end, setEnd] = useState(initialRange.end);
  const [granularity, setGranularity] = useState<PeriodGranularity>("month");
  const [params, setParams] = useState({ start, end, granularity });
  const [periodError, setPeriodError] = useState<string>();
  const report = useQuery({
    queryKey: ["analytics", params],
    queryFn: () => api.getFinancialReport(params.start, params.end, params.granularity),
  });
  return (
    <Page
      title="Аналитика"
      eyebrow="Проверяемые показатели"
      actions={<Freshness value={report.data?.data_through} profile={profile} />}
    >
      <form
        className="filter-bar"
        onSubmit={(e) => {
          e.preventDefault();
          if (!analyticsRangeIsAligned(start, end, granularity)) {
            setPeriodError(analyticsAlignmentHint(granularity));
            return;
          }
          setPeriodError(undefined);
          setParams({ start, end, granularity });
        }}
      >
        <DateControl
          label="Начало периода"
          value={start}
          onChange={(e) => {
            setStart(e.target.value);
          }}
        />
        <DateControl
          label="Конец периода (не включая)"
          value={end}
          onChange={(e) => {
            setEnd(e.target.value);
          }}
        />
        <SelectField
          label="Группировка"
          value={granularity}
          onChange={(e) => {
            const next = e.target.value as PeriodGranularity;
            const range = currentAnalyticsRange(next, profile.timezone);
            setGranularity(next);
            setStart(range.start);
            setEnd(range.end);
          }}
        >
          <option value="day">День</option>
          <option value="week">Неделя</option>
          <option value="month">Месяц</option>
        </SelectField>
        <Button type="submit">Показать</Button>
      </form>
      <FormError error={periodError} />
      {report.isLoading ? (
        <LoadingState label="Строим отчёт по проводкам" />
      ) : report.error ? (
        <QueryError error={report.error} retry={() => void report.refetch()} />
      ) : report.data === undefined ? null : (
        <AnalyticsReport data={report.data} profile={profile} />
      )}
    </Page>
  );
}

function AnalyticsReport({
  data,
  profile,
}: {
  data: FinancialReportResponse;
  profile: ProfileResponse;
}) {
  return (
    <>
      {data.currency_mode === "separated_by_currency" ? <CurrencyWarning /> : null}
      <div className="chart-grid">
        {data.totals.map((total) => (
          <Section
            key={total.currency}
            title={`Итоги · ${total.currency}`}
            subtitle="График дополнен полной таблицей ниже"
          >
            <BarChart income={total.income.value.amount} expense={total.expense.value.amount} />
            <div className="metric-strip">
              <Metric label="Доход" value={money(total.income.value, profile)} />
              <Metric label="Расход" value={money(total.expense.value, profile)} />
              <Metric label="Cash flow" value={money(total.cash_flow.value, profile)} />
              <Metric
                label="Savings rate"
                value={
                  total.savings_rate.value === null
                    ? "—"
                    : percent(total.savings_rate.value, profile.locale)
                }
              />
            </div>
            <ResponsiveDataView
              caption={`Категории, ${total.currency}`}
              columns={[
                {
                  key: "name",
                  label: "Категория",
                  render: (row: (typeof total.category_breakdown)[number]) => row.name,
                },
                {
                  key: "type",
                  label: "Поток",
                  render: (row: (typeof total.category_breakdown)[number]) => row.flow_type,
                },
                {
                  key: "amount",
                  label: "Сумма",
                  numeric: true,
                  render: (row: (typeof total.category_breakdown)[number]) =>
                    money(row.amount, profile),
                },
              ]}
              getKey={(row) => `${row.flow_type}-${row.id ?? row.name}`}
              rows={total.category_breakdown}
            />
          </Section>
        ))}
      </div>
      <Section
        title="Сравнение периодов"
        subtitle={`${data.comparison.previous_start} — ${data.comparison.previous_end} → ${data.comparison.current_start} — ${data.comparison.current_end}`}
      >
        <ResponsiveDataView
          caption="Сравнение периодов"
          columns={[
            {
              key: "currency",
              label: "Валюта",
              render: (row: FinancialReportResponse["comparison"]["currencies"][number]) =>
                row.currency,
            },
            {
              key: "income",
              label: "Δ доход",
              numeric: true,
              render: (row: FinancialReportResponse["comparison"]["currencies"][number]) =>
                money(row.income.delta, profile),
            },
            {
              key: "expense",
              label: "Δ расход",
              numeric: true,
              render: (row: FinancialReportResponse["comparison"]["currencies"][number]) =>
                money(row.expense.delta, profile),
            },
            {
              key: "worth",
              label: "Δ капитал",
              numeric: true,
              render: (row: FinancialReportResponse["comparison"]["currencies"][number]) =>
                money(row.net_worth.delta, profile),
            },
          ]}
          getKey={(row) => row.currency}
          rows={data.comparison.currencies}
        />
      </Section>
      {data.anomalies.length > 0 ? (
        <Notice title="Детерминированные аномалии">
          {data.anomalies.map((item) => item.rationale).join(" · ")}
        </Notice>
      ) : null}
    </>
  );
}

function BarChart({ income, expense }: { income: string; expense: string }) {
  const values = [decimalForProgress(income), decimalForProgress(expense)];
  const max = Math.max(...values, 1);
  return (
    <svg aria-hidden="true" className="mini-chart" viewBox="0 0 320 96">
      <rect
        x="0"
        y="12"
        width={(280 * (values[0] ?? 0)) / max}
        height="26"
        rx="4"
        className="chart-income"
      />
      <rect
        x="0"
        y="56"
        width={(280 * (values[1] ?? 0)) / max}
        height="26"
        rx="4"
        className="chart-expense"
      />
    </svg>
  );
}

function ForecastPage({ accounts, api, profile }: WorkspaceProps) {
  const queryClient = useQueryClient();
  const scenarios = useQuery({
    queryKey: ["scenarios"],
    queryFn: () => api.listForecastScenarios(),
  });
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [horizon, setHorizon] = useState(nextYearIso(profile.timezone));
  const [incomeChange, setIncomeChange] = useState("0");
  const [expenseChange, setExpenseChange] = useState("0");
  const [inflation, setInflation] = useState("0");
  const [interest, setInterest] = useState("0");
  const [eventDate, setEventDate] = useState("");
  const [eventAccountId, setEventAccountId] = useState(accounts[0]?.id ?? "");
  const [eventAmount, setEventAmount] = useState("");
  const [eventDescription, setEventDescription] = useState("");
  const [selected, setSelected] = useState<string>("baseline");
  const [runParams, setRunParams] = useState({ selected: "baseline", horizon });
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const forecast = useQuery({
    queryKey: ["forecast", runParams],
    queryFn: () =>
      api.getForecast(
        profile.base_currency,
        runParams.selected === "baseline" ? runParams.horizon : undefined,
        runParams.selected === "baseline" ? undefined : runParams.selected,
      ),
  });
  const comparison = useQuery({
    queryKey: ["forecast-compare", compareIds, horizon],
    queryFn: () => api.compareForecasts(profile.base_currency, horizon, compareIds),
    enabled: compareIds.length > 0,
  });
  const create = useMutation({
    mutationFn: () => {
      const parsedEventAmount =
        eventAmount === "" ? undefined : parseLocalizedDecimal(eventAmount, profile.locale);
      if (parsedEventAmount === null) throw new Error("invalid_event_amount");
      return api.createForecastScenario({
        name,
        currency: profile.base_currency,
        horizon,
        income_change: { value: normalizeRate(incomeChange) },
        expense_change: { value: normalizeRate(expenseChange) },
        annual_inflation: { value: normalizeRate(inflation) },
        annual_interest: { value: normalizeRate(interest) },
        one_time_cashflows:
          parsedEventAmount === undefined || eventDate === ""
            ? []
            : [
                {
                  occurs_on: eventDate,
                  account_id: eventAccountId,
                  money: {
                    amount: parsedEventAmount,
                    currency: accountCurrency(accounts, eventAccountId, profile.base_currency),
                  },
                  description: eventDescription,
                },
              ],
      });
    },
    onSuccess: async (value) => {
      setOpen(false);
      setSelected(value.id);
      setRunParams({ selected: value.id, horizon: value.horizon });
      await queryClient.invalidateQueries({ queryKey: ["scenarios"] });
    },
  });
  return (
    <Page
      title="Прогноз"
      eyebrow="Сценарии, не гарантии"
      actions={
        <Button
          onClick={() => {
            setOpen(true);
          }}
        >
          Новый сценарий
        </Button>
      }
    >
      <form
        className="filter-bar"
        onSubmit={(e) => {
          e.preventDefault();
          setRunParams({ selected, horizon });
        }}
      >
        <SelectField
          label="Сценарий"
          value={selected}
          onChange={(e) => {
            setSelected(e.target.value);
          }}
        >
          <option value="baseline">Базовый</option>
          {(scenarios.data ?? []).map((scenario) => (
            <option key={scenario.id} value={scenario.id}>
              {scenario.name}
            </option>
          ))}
        </SelectField>
        {selected === "baseline" ? (
          <DateControl
            label="Горизонт"
            value={horizon}
            onChange={(e) => {
              setHorizon(e.target.value);
            }}
          />
        ) : null}
        <Button type="submit">Рассчитать</Button>
      </form>
      {forecast.isLoading ? (
        <LoadingState label="Сервер строит прогноз" />
      ) : forecast.error ? (
        <QueryError error={forecast.error} retry={() => void forecast.refetch()} />
      ) : forecast.data === undefined ? null : (
        <ForecastResult value={forecast.data} profile={profile} />
      )}
      <Section
        title="Сравнить сценарии"
        subtitle="Выберите один или несколько сохранённых вариантов"
      >
        <div className="check-list">
          {(scenarios.data ?? []).map((scenario) => (
            <label key={scenario.id}>
              <input
                type="checkbox"
                checked={compareIds.includes(scenario.id)}
                onChange={(e) => {
                  setCompareIds(
                    e.target.checked
                      ? [...compareIds, scenario.id]
                      : compareIds.filter((id) => id !== scenario.id),
                  );
                }}
              />
              {scenario.name}
            </label>
          ))}
        </div>
        {comparison.isFetching ? (
          <LoadingState label="Сравниваем" />
        ) : comparison.error ? (
          <QueryError error={comparison.error} retry={() => void comparison.refetch()} />
        ) : comparison.data === undefined ? (
          <p className="field-note">Сравнение появится после выбора.</p>
        ) : (
          <ResponsiveDataView
            caption="Сравнение сценариев"
            columns={[
              {
                key: "name",
                label: "Сценарий",
                render: (row: (typeof comparison.data.items)[number]) => row.scenario_name,
              },
              {
                key: "total",
                label: "Итог",
                numeric: true,
                render: (row: (typeof comparison.data.items)[number]) =>
                  money(row.forecast.final_total, profile),
              },
              {
                key: "range",
                label: "Диапазон",
                render: (row: (typeof comparison.data.items)[number]) =>
                  `${money(row.forecast.uncertainty_low, profile)} — ${money(row.forecast.uncertainty_high, profile)}`,
              },
            ]}
            getKey={(row) => row.scenario_id ?? "baseline"}
            rows={comparison.data.items}
          />
        )}
      </Section>
      <Dialog
        open={open}
        onClose={() => {
          setOpen(false);
        }}
        title="Редактор сценария"
        description="Изменяются только допущения. Расчёт выполняется сервером."
      >
        <form
          className="form-stack"
          onSubmit={(e) => {
            e.preventDefault();
            void create.mutateAsync();
          }}
        >
          <InputField
            label="Название"
            required
            value={name}
            onChange={(e) => {
              setName(e.target.value);
            }}
          />
          <DateControl
            label="Горизонт"
            required
            value={horizon}
            onChange={(e) => {
              setHorizon(e.target.value);
            }}
          />
          <div className="form-grid">
            <InputField
              label="Изменение дохода, %"
              value={incomeChange}
              onChange={(e) => {
                setIncomeChange(e.target.value);
              }}
            />
            <InputField
              label="Изменение расходов, %"
              value={expenseChange}
              onChange={(e) => {
                setExpenseChange(e.target.value);
              }}
            />
            <InputField
              label="Инфляция, % годовых"
              value={inflation}
              onChange={(e) => {
                setInflation(e.target.value);
              }}
            />
            <InputField
              label="Ставка, % годовых"
              value={interest}
              onChange={(e) => {
                setInterest(e.target.value);
              }}
            />
          </div>
          <fieldset className="form-stack">
            <legend>Разовое событие (необязательно)</legend>
            <DateControl
              label="Дата события"
              value={eventDate}
              onChange={(event) => {
                setEventDate(event.target.value);
              }}
            />
            <SelectField
              label="Счёт события"
              value={eventAccountId}
              onChange={(event) => {
                setEventAccountId(event.target.value);
              }}
            >
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.name}
                </option>
              ))}
            </SelectField>
            <MoneyInput
              label="Сумма события"
              currency={accountCurrency(accounts, eventAccountId, profile.base_currency)}
              locale={profile.locale}
              value={eventAmount}
              onChange={setEventAmount}
            />
            <InputField
              label="Описание события"
              value={eventDescription}
              onChange={(event) => {
                setEventDescription(event.target.value);
              }}
            />
          </fieldset>
          <FormError
            error={
              create.error instanceof Error && create.error.message === "invalid_event_amount"
                ? "Проверьте сумму разового события."
                : mutationError(create.error)
            }
          />
          <Button loading={create.isPending} type="submit">
            Сохранить сценарий
          </Button>
        </form>
      </Dialog>
    </Page>
  );
}

function ForecastResult({
  value,
  profile,
}: {
  value: ForecastRunResponse;
  profile: ProfileResponse;
}) {
  const forecast = value.forecast;
  return (
    <>
      <div className="metric-strip">
        <Metric label="На старте" value={money(forecast.opening_total, profile)} />
        <Metric label="На горизонте" value={money(forecast.final_total, profile)} />
        <Metric label="Нижняя граница" value={money(forecast.uncertainty_low, profile)} />
        <Metric label="Верхняя граница" value={money(forecast.uncertainty_high, profile)} />
      </div>
      <Notice title="Не гарантия">
        {value.disclaimer} {forecast.uncertainty_explanation}
      </Notice>
      <Section title="Допущения" subtitle={`Версия ${forecast.assumptions.version}`}>
        <dl className="assumption-grid">
          <div>
            <dt>Доход</dt>
            <dd>{percent(forecast.assumptions.income_change, profile.locale)}</dd>
          </div>
          <div>
            <dt>Расходы</dt>
            <dd>{percent(forecast.assumptions.expense_change, profile.locale)}</dd>
          </div>
          <div>
            <dt>Инфляция</dt>
            <dd>{percent(forecast.assumptions.annual_inflation, profile.locale)}</dd>
          </div>
          <div>
            <dt>Ставка</dt>
            <dd>{percent(forecast.assumptions.annual_interest, profile.locale)}</dd>
          </div>
        </dl>
      </Section>
      <Section
        title="Помесячная линия"
        subtitle="Таблица содержит те же данные, что визуальная линия"
      >
        <ResponsiveDataView
          caption="Помесячный прогноз"
          columns={[
            {
              key: "period",
              label: "Месяц",
              render: (row: ForecastRunResponse["forecast"]["timeline"][number]) => row.starts_on,
            },
            {
              key: "income",
              label: "Регулярный доход",
              numeric: true,
              render: (row: ForecastRunResponse["forecast"]["timeline"][number]) =>
                money(row.scheduled_income, profile),
            },
            {
              key: "expense",
              label: "Регулярный расход",
              numeric: true,
              render: (row: ForecastRunResponse["forecast"]["timeline"][number]) =>
                money(row.scheduled_expense, profile),
            },
            {
              key: "closing",
              label: "Итог",
              numeric: true,
              render: (row: ForecastRunResponse["forecast"]["timeline"][number]) =>
                money(row.closing_total, profile),
            },
            {
              key: "uncertainty",
              label: "Неопределённость",
              render: (row: ForecastRunResponse["forecast"]["timeline"][number]) =>
                `${money(row.uncertainty_low, profile)} — ${money(row.uncertainty_high, profile)}`,
            },
          ]}
          getKey={(row) => row.starts_on}
          rows={forecast.timeline}
        />
      </Section>
    </>
  );
}

function GoalsPage({ accounts, api, profile }: WorkspaceProps) {
  const queryClient = useQueryClient();
  const goals = useQuery({ queryKey: ["goals"], queryFn: () => api.listFinancialGoals() });
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<GoalResponse>();
  const [archiving, setArchiving] = useState<GoalResponse>();
  const [name, setName] = useState("");
  const [target, setTarget] = useState("");
  const [saved, setSaved] = useState("0");
  const [date, setDate] = useState(nextYearIso(profile.timezone));
  const [priority, setPriority] = useState("1");
  const [linked, setLinked] = useState("");
  const goalHorizon = (goals.data ?? []).reduce(
    (latest, goal) => (goal.target_date > latest ? goal.target_date : latest),
    date,
  );
  const forecast = useQuery({
    queryKey: ["goals-plan", goalHorizon, goals.data],
    queryFn: () => api.getForecast(profile.base_currency, goalHorizon),
    enabled: (goals.data?.length ?? 0) > 0,
  });
  const saveGoal = useMutation({
    mutationFn: () => {
      const targetAmount = parseLocalizedDecimal(target, profile.locale);
      const savedAmount = parseLocalizedDecimal(saved, profile.locale);
      if (targetAmount === null || savedAmount === null) throw new Error("invalid_amount");
      const payload = {
        name,
        target: { amount: targetAmount, currency: profile.base_currency },
        target_date: date,
        saved_amount: { amount: savedAmount, currency: profile.base_currency },
        priority: Number(priority),
        linked_account_id: linked || null,
      };
      return editing === undefined
        ? api.createFinancialGoal(payload)
        : api.updateFinancialGoal(editing.id, { ...payload, version: editing.version });
    },
    onSuccess: async () => {
      setOpen(false);
      setEditing(undefined);
      await invalidateFinance(queryClient);
    },
  });
  const archiveGoal = useMutation({
    mutationFn: (goal: GoalResponse) => api.archiveFinancialGoal(goal.id, goal.version),
    onSuccess: async () => {
      setArchiving(undefined);
      await invalidateFinance(queryClient);
    },
  });
  function newGoal() {
    setEditing(undefined);
    setName("");
    setTarget("");
    setSaved("0");
    setDate(nextYearIso(profile.timezone));
    setPriority("1");
    setLinked("");
    setOpen(true);
  }
  function editGoal(goal: GoalResponse) {
    setEditing(goal);
    setName(goal.name);
    setTarget(goal.target.amount);
    setSaved(goal.saved_amount.amount);
    setDate(goal.target_date);
    setPriority(String(goal.priority));
    setLinked(goal.linked_account_id ?? "");
    setOpen(true);
  }
  return (
    <Page
      title="Финансовые цели"
      eyebrow="Приоритетные стратегии"
      actions={<Button onClick={newGoal}>Новая цель</Button>}
    >
      {goals.isLoading ? (
        <LoadingState label="Загружаем цели" />
      ) : goals.error ? (
        <QueryError error={goals.error} retry={() => void goals.refetch()} />
      ) : (goals.data ?? []).length === 0 ? (
        <EmptyState
          title="Целей пока нет"
          description="Добавьте сумму и срок, чтобы сервер рассчитал необходимый взнос."
        />
      ) : (
        <ResponsiveDataView
          caption="Финансовые цели"
          columns={[
            {
              key: "priority",
              label: "Приоритет",
              render: (row: GoalResponse) => `№ ${row.priority}`,
            },
            { key: "name", label: "Цель", render: (row: GoalResponse) => row.name },
            {
              key: "saved",
              label: "Накоплено",
              numeric: true,
              render: (row: GoalResponse) =>
                `${money(row.saved_amount, profile)} / ${money(row.target, profile)}`,
            },
            { key: "date", label: "Срок", render: (row: GoalResponse) => row.target_date },
            {
              key: "actions",
              label: "Действия",
              render: (row: GoalResponse) => (
                <div className="inline-actions">
                  <Button
                    variant="quiet"
                    onClick={() => {
                      editGoal(row);
                    }}
                  >
                    Изменить
                  </Button>
                  <Button
                    variant="quiet"
                    onClick={() => {
                      setArchiving(row);
                    }}
                  >
                    Удалить
                  </Button>
                </div>
              ),
            },
          ]}
          getKey={(row) => row.id}
          rows={goals.data ?? []}
        />
      )}
      {forecast.isFetching ? (
        <LoadingState label="Рассчитываем стратегию" />
      ) : forecast.data === undefined ? null : (
        <Section
          title="План по приоритетам"
          subtitle="Свободные средства распределяются по приоритету целей и срокам. Для каждой цели показаны необходимый взнос и недостача."
        >
          <ResponsiveDataView
            caption="Расчёт достижимости целей"
            columns={[
              {
                key: "name",
                label: "Цель",
                render: (row: ForecastRunResponse["goal_plan"]["goals"][number]) => row.name,
              },
              {
                key: "required",
                label: "Нужно в месяц",
                numeric: true,
                render: (row: ForecastRunResponse["goal_plan"]["goals"][number]) =>
                  money(row.required_monthly_contribution, profile),
              },
              {
                key: "gap",
                label: "Дефицит взноса",
                numeric: true,
                render: (row: ForecastRunResponse["goal_plan"]["goals"][number]) =>
                  money(row.contribution_gap, profile),
              },
              {
                key: "shortfall",
                label: "Недостача к сроку",
                numeric: true,
                render: (row: ForecastRunResponse["goal_plan"]["goals"][number]) =>
                  money(row.shortfall, profile),
              },
              {
                key: "strategy",
                label: "Стратегия",
                render: (row: ForecastRunResponse["goal_plan"]["goals"][number]) =>
                  row.feasible_by_target
                    ? `Приоритет ${row.priority}: продолжать план`
                    : `Приоритет ${row.priority}: увеличить взнос или срок`,
              },
            ]}
            getKey={(row) => row.goal_id}
            rows={forecast.data.goal_plan.goals}
          />
        </Section>
      )}
      <Dialog
        open={open}
        onClose={() => {
          setOpen(false);
          setEditing(undefined);
        }}
        title={editing === undefined ? "Новая цель" : "Изменить цель"}
        description="Достижимость, взнос и недостачу рассчитает сервер."
      >
        <form
          className="form-stack"
          onSubmit={(e) => {
            e.preventDefault();
            saveGoal.mutate();
          }}
        >
          <InputField
            label="Название цели"
            required
            value={name}
            onChange={(e) => {
              setName(e.target.value);
            }}
          />
          <div className="form-grid">
            <MoneyInput
              label="Целевая сумма"
              currency={profile.base_currency}
              locale={profile.locale}
              value={target}
              onChange={setTarget}
            />
            <MoneyInput
              label="Уже накоплено"
              currency={profile.base_currency}
              locale={profile.locale}
              value={saved}
              onChange={setSaved}
            />
          </div>
          <div className="form-grid">
            <DateControl
              label="Срок"
              value={date}
              onChange={(e) => {
                setDate(e.target.value);
              }}
            />
            <InputField
              label="Приоритет"
              type="number"
              min="1"
              value={priority}
              onChange={(e) => {
                setPriority(e.target.value);
              }}
            />
          </div>
          <SelectField
            label="Связанный счёт (необязательно)"
            value={linked}
            onChange={(e) => {
              setLinked(e.target.value);
            }}
          >
            <option value="">Без привязки</option>
            {accounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.name}
              </option>
            ))}
          </SelectField>
          <FormError
            error={
              saveGoal.error instanceof Error && saveGoal.error.message === "invalid_amount"
                ? "Проверьте суммы."
                : mutationError(saveGoal.error)
            }
          />
          <Button loading={saveGoal.isPending} type="submit">
            {editing === undefined ? "Создать цель" : "Сохранить изменения"}
          </Button>
        </form>
      </Dialog>
      <Dialog
        open={archiving !== undefined}
        onClose={() => {
          setArchiving(undefined);
        }}
        title="Удалить цель?"
        description="Цель исчезнет из активного плана, а запись об удалении останется в аудите."
      >
        <FormError error={mutationError(archiveGoal.error)} />
        <Button
          loading={archiveGoal.isPending}
          onClick={() => {
            if (archiving !== undefined) archiveGoal.mutate(archiving);
          }}
        >
          Удалить цель
        </Button>
      </Dialog>
    </Page>
  );
}

function AdvicePage({ api, profile }: WorkspaceProps) {
  const status = useQuery({
    queryKey: ["advice-status"],
    queryFn: () => api.getAdviceProviderStatus(),
  });
  const [question, setQuestion] = useState("");
  const [consent, setConsent] = useState(false);
  const advice = useMutation({
    mutationFn: () =>
      api.generateAdvice({
        currency: profile.base_currency,
        through: nextYearIso(profile.timezone),
        question: question || null,
        allow_external_user_text: consent,
      }),
  });
  return (
    <Page
      title="Финансовый советник"
      eyebrow="Объяснение, не команда"
      actions={
        status.data === undefined ? null : (
          <span className={`status-pill status-pill--${status.data.status}`}>
            {status.data.status} · {status.data.provider}
          </span>
        )
      }
    >
      <Notice title="Приватность">
        Совет строится из агрегированных метрик и детерминированных расчётов. Сырые транзакции не
        передаются. Текст вопроса внешнему провайдеру отправляется только с явным согласием.
      </Notice>
      {status.error ? (
        <QueryError error={status.error} retry={() => void status.refetch()} />
      ) : status.data?.status !== "available" && status.data?.status !== "configured" ? (
        <EmptyState
          title="Советник недоступен"
          description="Финансовые функции продолжают работать без LLM. Проверьте статус провайдера позже."
        />
      ) : (
        <form
          className="form-stack advice-form"
          onSubmit={(e) => {
            e.preventDefault();
            void advice.mutateAsync();
          }}
        >
          <InputField
            label="Вопрос (необязательно)"
            value={question}
            onChange={(e) => {
              setQuestion(e.target.value);
            }}
            hint="Не вводите номера карт, пароли и другие секреты."
          />
          <label className="consent-row">
            <input
              type="checkbox"
              checked={consent}
              onChange={(e) => {
                setConsent(e.target.checked);
              }}
            />
            <span>
              <strong>Разрешить передать этот текст внешнему провайдеру</strong>
              <small>
                Согласие действует только для этого запроса; чувствительные шаблоны редактируются.
              </small>
            </span>
          </label>
          <FormError error={mutationError(advice.error)} />
          <Button loading={advice.isPending} type="submit">
            Получить варианты и объяснение
          </Button>
        </form>
      )}
      {advice.data?.advice === null ? (
        advice.data === undefined ? null : (
          <Notice title="Ответ не получен">
            Код: {advice.data.error_code ?? "provider_unavailable"}. Попробуйте позже.
          </Notice>
        )
      ) : advice.data?.advice === undefined ? null : (
        <Section
          title="Наблюдения и варианты"
          subtitle={`Уверенность: ${confidenceLabel(advice.data.advice.confidence)}`}
        >
          <p className="advice-summary">{advice.data.advice.summary}</p>
          <h3>Наблюдения</h3>
          <ul>
            {advice.data.advice.observations.map((observation, index) => (
              <li key={`${index}-${observation.text}`}>
                {observation.text}{" "}
                {observation.evidence_ids.map((id) => (
                  <a href={`#evidence-${id}`} key={id}>
                    [{id}]
                  </a>
                ))}
              </li>
            ))}
          </ul>
          <h3>Варианты для рассмотрения</h3>
          <ul>
            {advice.data.advice.suggestions.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <h3>Основания</h3>
          {advice.data.evidence.map((evidence) => (
            <article className="evidence" id={`evidence-${evidence.id}`} key={evidence.id}>
              <strong>
                {evidence.id} · {evidence.kind}
              </strong>
              <dl>
                {evidence.facts.map((fact) => (
                  <div key={fact.name}>
                    <dt>{fact.name}</dt>
                    <dd>{fact.value}</dd>
                  </div>
                ))}
              </dl>
            </article>
          ))}
          <Notice title="Ограничения">
            {advice.data.advice.disclaimer} Уверенность «
            {confidenceLabel(advice.data.advice.confidence)}» не означает гарантию. Советник ничего
            не изменил.
          </Notice>
          <p className="field-note">
            Передан текст:{" "}
            {advice.data.privacy.external_user_text_shared ? "да, по согласию" : "нет"}; редакций:{" "}
            {advice.data.privacy.redactions_applied}.
          </p>
        </Section>
      )}
    </Page>
  );
}

function Page({
  actions,
  children,
  eyebrow,
  title,
}: {
  actions?: ReactNode;
  children: ReactNode;
  eyebrow: string;
  title: string;
}) {
  return (
    <div className="finance-page">
      <header className="page-heading">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h1>{title}</h1>
        </div>
        {actions === undefined ? null : <div className="page-actions">{actions}</div>}
      </header>
      {children}
    </div>
  );
}

function Section({
  children,
  subtitle,
  title,
}: {
  children: ReactNode;
  subtitle?: string;
  title: string;
}) {
  return (
    <section className="finance-section">
      <header className="section-heading">
        <div>
          <h2>{title}</h2>
          {subtitle === undefined ? null : <p>{subtitle}</p>}
        </div>
      </header>
      {children}
    </section>
  );
}

function Metric({ label, note, value }: { label: string; note?: string; value: string }) {
  return (
    <article className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
      {note === undefined ? null : <small>{note}</small>}
    </article>
  );
}

function Notice({ children, title }: { children: ReactNode; title: string }) {
  return (
    <aside className="finance-notice">
      <span aria-hidden="true">i</span>
      <div>
        <strong>{title}</strong>
        <p>{children}</p>
      </div>
    </aside>
  );
}

function QueryError({ error, retry }: { error: unknown; retry: () => void }) {
  return (
    <ErrorState
      message={apiErrorMessage(error)}
      onRetry={retry}
      title="Не удалось получить данные"
    />
  );
}

function FormError({ error }: { error?: string | undefined }) {
  return error === undefined ? null : (
    <p className="form-error" role="alert">
      {error}
    </p>
  );
}

function Freshness({ profile, value }: { profile: ProfileResponse; value?: string | undefined }) {
  return (
    <div className="date-stamp">
      <span>Данные актуальны на</span>
      <strong>{value === undefined ? "обновляются…" : dateTime(value, profile)}</strong>
    </div>
  );
}

function CurrencyWarning() {
  return (
    <Notice title="Валюты не объединены">
      Без заданного курса суммы разных валют показаны раздельно. Единого итога нет.
    </Notice>
  );
}

function money(value: { amount: string; currency: string }, profile: ProfileResponse): string {
  const negative = value.amount.startsWith("-");
  const unsigned = negative ? value.amount.slice(1) : value.amount;
  const [integer = "0", fraction] = unsigned.split(".");
  let group = "\u00a0";
  let decimal = ",";
  try {
    const parts = new Intl.NumberFormat(profile.locale).formatToParts(12345.6);
    group = parts.find((part) => part.type === "group")?.value ?? group;
    decimal = parts.find((part) => part.type === "decimal")?.value ?? decimal;
  } catch {
    /* deterministic fallback */
  }
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/gu, group);
  return `${negative ? "−" : ""}${grouped}${fraction === undefined ? "" : `${decimal}${fraction}`}\u00a0${value.currency}`;
}

function percent(value: string, locale: string): string {
  const separator = locale.startsWith("en") ? "." : ",";
  return `${rateToPercentInput(value).replace(".", separator)}%`;
}

function rateToPercentInput(value: string): string {
  const normalized = value.trim();
  const match = /^(?<sign>-?)(?<whole>\d+)(?:\.(?<fraction>\d+))?$/u.exec(normalized);
  if (match?.groups === undefined) return normalized;
  const whole = match.groups.whole ?? "0";
  const fraction = match.groups.fraction ?? "";
  const digits = `${whole}${fraction}`;
  const point = whole.length + 2;
  const expanded = point >= digits.length ? digits.padEnd(point, "0") : digits;
  const raw =
    point >= expanded.length ? expanded : `${expanded.slice(0, point)}.${expanded.slice(point)}`;
  const cleaned = raw
    .replace(/^0+(?=\d)/u, "")
    .replace(/\.0+$/u, "")
    .replace(/(\.\d*?)0+$/u, "$1");
  return `${match.groups.sign}${cleaned || "0"}`;
}

function normalizeRate(value: string): string {
  const normalized = value.trim().replace(",", ".");
  const match = /^(?<sign>-?)(?<whole>\d+)(?:\.(?<fraction>\d+))?$/u.exec(normalized);
  if (match?.groups === undefined) return normalized;
  const digits = `${match.groups.whole}${match.groups.fraction ?? ""}`.replace(/^0+(?=\d)/u, "");
  const scale = (match.groups.fraction ?? "").length + 2;
  const padded = digits.padStart(scale + 1, "0");
  return `${match.groups.sign}${padded.slice(0, -scale)}.${padded.slice(-scale)}`
    .replace(/\.0+$/u, "")
    .replace(/(\.\d*?)0+$/u, "$1");
}

function dateTime(value: string, profile: ProfileResponse): string {
  try {
    return new Intl.DateTimeFormat(profile.locale, {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: profile.timezone,
    }).format(new Date(value));
  } catch {
    return value;
  }
}

function decimalForProgress(value: string): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(parsed, 0) : 0;
}

function periodLabel(data: DashboardResponse): string {
  return `${data.period.start} — ${data.period.end}`;
}
function accountCurrency(accounts: AccountResponse[], id: string, fallback: string): string {
  return accounts.find((item) => item.id === id)?.currency ?? fallback;
}
function financialInstruments(
  accounts: AccountResponse[],
  deposits: DepositTermsResponse[],
): FinancialInstrument[] {
  return [
    ...accounts.map((account) => ({
      id: account.id,
      name: account.name,
      currency: account.currency,
      kind: "account" as const,
    })),
    ...deposits.map((deposit) => ({
      id: deposit.principal_account_id,
      name: `${deposit.name} · вклад`,
      currency: deposit.currency,
      kind: "deposit" as const,
    })),
  ];
}
function instrumentCurrency(
  instruments: FinancialInstrument[],
  id: string,
  fallback: string,
): string {
  return instruments.find((item) => item.id === id)?.currency ?? fallback;
}
function accountKind(value: string): string {
  return (
    (
      {
        bank: "Банковский",
        cash: "Наличные",
        savings: "Накопительный",
        deposit: "Вклад",
        other_asset: "Иной актив",
      } as Record<string, string>
    )[value] ?? value
  );
}
function frequencyLabel(value: RecurrenceFrequency): string {
  return { daily: "ежедневно", weekly: "еженедельно", monthly: "ежемесячно", yearly: "ежегодно" }[
    value
  ];
}
function mutationError(error: unknown): string | undefined {
  if (error instanceof Error) {
    if (error.message === "invalid_amount") return "Проверьте сумму.";
    if (error.message === "category_required")
      return "Введите название категории или выберите существующую.";
  }
  return error === null || error === undefined ? undefined : apiErrorMessage(error);
}
function compareIsoDates(left: string, right: string): number {
  return left.localeCompare(right);
}
function currentAnalyticsRange(
  granularity: PeriodGranularity,
  timezone: string,
): { start: string; end: string } {
  const today = new Date(`${todayIsoDate(new Date(), timezone)}T00:00:00Z`);
  if (granularity === "day") {
    return { start: isoDate(today), end: isoDate(addUtcDays(today, 1)) };
  }
  if (granularity === "week") {
    const mondayOffset = (today.getUTCDay() + 6) % 7;
    const start = addUtcDays(today, -mondayOffset);
    return { start: isoDate(start), end: isoDate(addUtcDays(start, 7)) };
  }
  const start = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), 1));
  const end = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth() + 1, 1));
  return { start: isoDate(start), end: isoDate(end) };
}
function analyticsRangeIsAligned(
  start: string,
  end: string,
  granularity: PeriodGranularity,
): boolean {
  if (start >= end) return false;
  if (granularity === "day") return true;
  const startDate = new Date(`${start}T00:00:00Z`);
  const endDate = new Date(`${end}T00:00:00Z`);
  if (granularity === "week") return startDate.getUTCDay() === 1 && endDate.getUTCDay() === 1;
  return startDate.getUTCDate() === 1 && endDate.getUTCDate() === 1;
}
function analyticsAlignmentHint(granularity: PeriodGranularity): string {
  if (granularity === "week")
    return "Для недельной группировки начало и конец периода должны приходиться на понедельник.";
  if (granularity === "month")
    return "Для месячной группировки начало и конец периода должны быть первым числом месяца.";
  return "Конец периода должен быть позже начала.";
}
function addUtcDays(value: Date, days: number): Date {
  return new Date(value.getTime() + days * 86_400_000);
}
function isoDate(value: Date): string {
  return value.toISOString().slice(0, 10);
}
function nextYearIso(timezone?: string): string {
  const today = todayIsoDate(new Date(), timezone);
  const year = Number(today.slice(0, 4)) + 1;
  const month = Number(today.slice(5, 7));
  const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const day = Math.min(Number(today.slice(8, 10)), lastDay);
  return `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}
function confidenceLabel(value: "low" | "medium" | "high"): string {
  return { low: "низкая", medium: "средняя", high: "высокая" }[value];
}
async function invalidateFinance(queryClient: ReturnType<typeof useQueryClient>): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ["transactions"] }),
    queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
    queryClient.invalidateQueries({ queryKey: ["analytics"] }),
    queryClient.invalidateQueries({ queryKey: ["accounts"] }),
    queryClient.invalidateQueries({ queryKey: ["deposits"] }),
    queryClient.invalidateQueries({ queryKey: ["deposit-valuation"] }),
    queryClient.invalidateQueries({ queryKey: ["goals"] }),
    queryClient.invalidateQueries({ queryKey: ["goals-plan"] }),
    queryClient.invalidateQueries({ queryKey: ["forecast"] }),
  ]);
}
