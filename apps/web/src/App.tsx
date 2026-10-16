import {
  Component,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ErrorInfo,
  type ReactNode,
  type SyntheticEvent,
} from "react";
import type {
  AccountResponse,
  BootstrapRequest,
  CreateAccountRequest,
  ProfileResponse,
} from "@financial-analytics/api-contracts";

import { apiErrorMessage, browserFinanceApi, SessionExpiredError, type FinanceApi } from "./api";
import {
  Button,
  DateControl,
  Dialog,
  ErrorState,
  InputField,
  isZeroDecimal,
  LoadingState,
  localDateAtNoonUtc,
  MoneyInput,
  parseLocalizedDecimal,
  ResponsiveDataView,
  SelectField,
  todayIsoDate,
  ToastProvider,
  useToast,
} from "./ui";
import "./styles.css";

type Navigate = (path: string, options?: { replace?: boolean }) => void;
type AppState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "anonymous"; notice?: string | undefined }
  | { status: "authenticated"; profile: ProfileResponse; accounts: AccountResponse[] };

const currencies = ["RUB", "USD", "EUR", "KZT", "CNY"] as const;
const accountKinds = ["bank", "cash", "savings", "deposit", "other_asset"] as const;
type AccountKind = (typeof accountKinds)[number];

const accountKindLabels: Record<AccountKind, string> = {
  bank: "Банковский счёт",
  cash: "Наличные",
  savings: "Накопительный",
  deposit: "Вклад",
  other_asset: "Другой актив",
};

export function App({ api = browserFinanceApi }: { api?: FinanceApi }) {
  return (
    <GlobalErrorBoundary>
      <ToastProvider>
        <Application api={api} />
      </ToastProvider>
    </GlobalErrorBoundary>
  );
}

function Application({ api }: { api: FinanceApi }) {
  const [path, navigate] = useBrowserPath();
  const [state, setState] = useState<AppState>({ status: "loading" });
  const bootstrapPromise = useRef<ReturnType<FinanceApi["bootstrapSession"]> | null>(null);
  const initialPath = useRef(path);

  useEffect(() => {
    let active = true;
    bootstrapPromise.current ??= api.bootstrapSession();
    void bootstrapPromise.current
      .then((session) => {
        if (!active) return;
        if (session.kind === "anonymous") {
          setState({ status: "anonymous" });
          if (initialPath.current !== "/login" && initialPath.current !== "/start") {
            navigate("/login", { replace: true });
          }
          return;
        }
        setState({
          status: "authenticated",
          profile: session.profile,
          accounts: session.accounts,
        });
        if (session.accounts.length === 0) {
          navigate("/onboarding/account", { replace: true });
        } else if (
          initialPath.current === "/" ||
          initialPath.current === "/login" ||
          initialPath.current === "/start"
        ) {
          navigate("/app/dashboard", { replace: true });
        }
      })
      .catch((error: unknown) => {
        if (active) setState({ status: "error", message: apiErrorMessage(error) });
      });
    return () => {
      active = false;
    };
  }, [api, navigate]);

  const expireSession = useCallback(
    (error: unknown) => {
      if (error instanceof SessionExpiredError) {
        setState({ status: "anonymous", notice: error.message });
        navigate("/login", { replace: true });
        return true;
      }
      return false;
    },
    [navigate],
  );

  if (state.status === "loading") {
    return (
      <main className="centered-page" id="main-content">
        <LoadingState label="Открываем ваше финансовое пространство" />
      </main>
    );
  }

  if (state.status === "error") {
    return (
      <main className="centered-page" id="main-content">
        <ErrorState
          message={state.message}
          onRetry={() => {
            window.location.reload();
          }}
        />
      </main>
    );
  }

  if (state.status === "anonymous") {
    if (path === "/start") {
      return (
        <FirstRunPage
          api={api}
          navigate={navigate}
          onAuthenticated={(profile) => {
            setState({ status: "authenticated", profile, accounts: [] });
            navigate("/onboarding/account", { replace: true });
          }}
        />
      );
    }
    return (
      <LoginPage
        api={api}
        navigate={navigate}
        notice={state.notice}
        onAuthenticated={(profile, accounts) => {
          setState({ status: "authenticated", profile, accounts });
          navigate(accounts.length === 0 ? "/onboarding/account" : "/app/dashboard", {
            replace: true,
          });
        }}
      />
    );
  }

  if (state.accounts.length === 0) {
    return (
      <AccountSetupPage
        api={api}
        onCreated={(account) => {
          setState({ ...state, accounts: [account] });
          navigate("/app/dashboard", { replace: true });
        }}
        onSessionExpired={expireSession}
        profile={state.profile}
      />
    );
  }

  return (
    <AppShell
      navigate={navigate}
      onLogout={async () => {
        try {
          await api.logout();
        } finally {
          setState({ status: "anonymous", notice: "Вы вышли из пространства." });
          navigate("/login", { replace: true });
        }
      }}
      profile={state.profile}
    >
      {path === "/app/dashboard" || path === "/" ? (
        <Dashboard accounts={state.accounts} profile={state.profile} />
      ) : (
        <NotFound navigate={navigate} />
      )}
    </AppShell>
  );
}

function LoginPage({
  api,
  navigate,
  notice,
  onAuthenticated,
}: {
  api: FinanceApi;
  navigate: Navigate;
  notice?: string | undefined;
  onAuthenticated: (profile: ProfileResponse, accounts: AccountResponse[]) => void;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string>();
  const [pending, setPending] = useState(false);

  async function submit(event: SyntheticEvent<HTMLFormElement, SubmitEvent>) {
    event.preventDefault();
    setError(undefined);
    setPending(true);
    try {
      const profile = await api.login({ email, password });
      const accounts = await api.listAccounts();
      onAuthenticated(profile, accounts);
    } catch (submitError: unknown) {
      setError(apiErrorMessage(submitError));
    } finally {
      setPending(false);
    }
  }

  return (
    <GuestLayout
      kicker="Ваши данные остаются под вашим контролем"
      title="Спокойный взгляд на деньги."
    >
      <section className="auth-panel" aria-labelledby="login-title">
        <p className="eyebrow">Личное пространство</p>
        <h1 id="login-title">С возвращением</h1>
        <p className="lede">Войдите, чтобы продолжить с последней сохранённой точки.</p>
        {notice === undefined ? null : (
          <p className="inline-notice" role="status">
            {notice}
          </p>
        )}
        <form className="form-stack" onSubmit={(event) => void submit(event)}>
          <InputField
            autoComplete="email"
            label="Email"
            onChange={(event) => {
              setEmail(event.target.value);
            }}
            required
            type="email"
            value={email}
          />
          <InputField
            autoComplete="current-password"
            label="Пароль"
            onChange={(event) => {
              setPassword(event.target.value);
            }}
            required
            type="password"
            value={password}
          />
          {error === undefined ? null : (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <Button className="button--wide" loading={pending} type="submit">
            Войти
          </Button>
        </form>
        <p className="auth-switch">
          Это первый запуск?{" "}
          <RouteLink navigate={navigate} to="/start">
            Настроить пространство
          </RouteLink>
        </p>
      </section>
    </GuestLayout>
  );
}

function FirstRunPage({
  api,
  navigate,
  onAuthenticated,
}: {
  api: FinanceApi;
  navigate: Navigate;
  onAuthenticated: (profile: ProfileResponse) => void;
}) {
  const [step, setStep] = useState<1 | 2>(1);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [currency, setCurrency] = useState<(typeof currencies)[number]>("RUB");
  const [locale, setLocale] = useState(defaultLocale);
  const [timezone, setTimezone] = useState(defaultTimezone);
  const [error, setError] = useState<string>();
  const [pending, setPending] = useState(false);

  function continueToPreferences(event: SyntheticEvent<HTMLFormElement, SubmitEvent>) {
    event.preventDefault();
    if (password.length < 12) {
      setError("Пароль должен содержать не менее 12 символов.");
      return;
    }
    if (password !== confirmation) {
      setError("Пароли не совпадают.");
      return;
    }
    setError(undefined);
    setStep(2);
  }

  async function createProfile(event: SyntheticEvent<HTMLFormElement, SubmitEvent>) {
    event.preventDefault();
    setError(undefined);
    setPending(true);
    const payload: BootstrapRequest = {
      email,
      password,
      base_currency: currency,
      locale,
      timezone,
    };
    try {
      onAuthenticated(await api.bootstrapMaster(payload));
    } catch (submitError: unknown) {
      setError(apiErrorMessage(submitError));
    } finally {
      setPending(false);
    }
  }

  return (
    <GuestLayout
      kicker="Первый запуск · около двух минут"
      title="Соберём основу вашей финансовой картины."
    >
      <section className="auth-panel auth-panel--wide" aria-labelledby="onboarding-title">
        <div className="onboarding-heading">
          <div>
            <p className="eyebrow">Настройка пространства</p>
            <h1 id="onboarding-title">
              {step === 1 ? "Профиль владельца" : "Как показывать ваши данные"}
            </h1>
          </div>
          <ol className="stepper" aria-label="Шаги настройки">
            <li
              aria-current={step === 1 ? "step" : undefined}
              className={step >= 1 ? "is-done" : ""}
            >
              <span>1</span> Профиль
            </li>
            <li
              aria-current={step === 2 ? "step" : undefined}
              className={step >= 2 ? "is-done" : ""}
            >
              <span>2</span> Формат
            </li>
            <li>
              <span>3</span> Первый счёт
            </li>
          </ol>
        </div>

        {step === 1 ? (
          <form className="form-stack" onSubmit={continueToPreferences}>
            <p className="lede">
              Этот пользователь станет мастером локального пространства. Email нужен только для
              входа.
            </p>
            <InputField
              autoComplete="email"
              label="Email"
              onChange={(event) => {
                setEmail(event.target.value);
              }}
              required
              type="email"
              value={email}
            />
            <div className="form-grid">
              <InputField
                autoComplete="new-password"
                hint="Не менее 12 символов"
                label="Пароль"
                minLength={12}
                onChange={(event) => {
                  setPassword(event.target.value);
                }}
                required
                type="password"
                value={password}
              />
              <InputField
                autoComplete="new-password"
                label="Повторите пароль"
                onChange={(event) => {
                  setConfirmation(event.target.value);
                }}
                required
                type="password"
                value={confirmation}
              />
            </div>
            {error === undefined ? null : (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
            <div className="form-actions form-actions--end">
              <Button type="submit">Продолжить</Button>
            </div>
          </form>
        ) : (
          <form className="form-stack" onSubmit={(event) => void createProfile(event)}>
            <p className="lede">
              Валюта задаёт основной контекст. Locale и часовой пояс отвечают за ввод, даты и
              расписания — финансовые значения от этого не пересчитываются.
            </p>
            <div className="form-grid">
              <SelectField
                label="Основная валюта"
                onChange={(event) => {
                  setCurrency(event.target.value as (typeof currencies)[number]);
                }}
                value={currency}
              >
                {currencies.map((code) => (
                  <option key={code} value={code}>
                    {code}
                  </option>
                ))}
              </SelectField>
              <SelectField
                label="Формат чисел и дат"
                onChange={(event) => {
                  setLocale(event.target.value);
                }}
                value={locale}
              >
                <option value="ru-RU">Русский · Россия</option>
                <option value="en-US">English · United States</option>
                <option value="en-GB">English · United Kingdom</option>
                <option value="kk-KZ">Қазақша · Қазақстан</option>
              </SelectField>
            </div>
            <InputField
              autoComplete="off"
              hint="IANA timezone, например Europe/Saratov"
              label="Часовой пояс"
              list="timezone-options"
              onChange={(event) => {
                setTimezone(event.target.value);
              }}
              required
              value={timezone}
            />
            <datalist id="timezone-options">
              <option value="Europe/Moscow" />
              <option value="Europe/Saratov" />
              <option value="Asia/Almaty" />
              <option value="Asia/Yekaterinburg" />
              <option value="UTC" />
            </datalist>
            {error === undefined ? null : (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
            <div className="form-actions">
              <Button
                onClick={() => {
                  setStep(1);
                }}
                variant="secondary"
              >
                Назад
              </Button>
              <Button loading={pending} type="submit">
                Создать профиль
              </Button>
            </div>
          </form>
        )}
        <p className="auth-switch">
          Пространство уже настроено?{" "}
          <RouteLink navigate={navigate} to="/login">
            Войти
          </RouteLink>
        </p>
      </section>
    </GuestLayout>
  );
}

function AccountSetupPage({
  api,
  onCreated,
  onSessionExpired,
  profile,
}: {
  api: FinanceApi;
  onCreated: (account: AccountResponse) => void;
  onSessionExpired: (error: unknown) => boolean;
  profile: ProfileResponse;
}) {
  const { announce } = useToast();
  const [name, setName] = useState("Основной счёт");
  const [kind, setKind] = useState<AccountKind>("bank");
  const [balance, setBalance] = useState("");
  const [balanceDate, setBalanceDate] = useState(todayIsoDate);
  const [balanceError, setBalanceError] = useState<string>();
  const [error, setError] = useState<string>();
  const [pending, setPending] = useState(false);

  async function submit(event: SyntheticEvent<HTMLFormElement, SubmitEvent>) {
    event.preventDefault();
    setBalanceError(undefined);
    setError(undefined);
    const normalizedBalance =
      balance.trim() === "" ? null : parseLocalizedDecimal(balance, profile.locale);
    if (balance.trim() !== "" && normalizedBalance === null) {
      setBalanceError("Проверьте сумму и десятичный разделитель.");
      return;
    }

    let payload: CreateAccountRequest = {
      name: name.trim(),
      kind,
      currency: profile.base_currency,
    };
    if (normalizedBalance !== null && !isZeroDecimal(normalizedBalance)) {
      payload = {
        ...payload,
        opening_balance: { amount: normalizedBalance, currency: profile.base_currency },
        opening_balance_occurred_at: localDateAtNoonUtc(balanceDate, profile.timezone),
      };
    }

    setPending(true);
    try {
      const account = await api.createAccount(payload);
      announce("Первый счёт создан. Пространство готово к работе.", "success");
      onCreated(account);
    } catch (submitError: unknown) {
      if (!onSessionExpired(submitError)) setError(apiErrorMessage(submitError));
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="onboarding-page" id="main-content">
      <div className="onboarding-account">
        <header className="onboarding-account__intro">
          <a
            className="brand"
            href="/app/dashboard"
            onClick={(event) => {
              event.preventDefault();
            }}
          >
            <BrandMark />
            <span>Financial Analytics</span>
          </a>
          <div>
            <p className="eyebrow">Последний шаг · Первый счёт</p>
            <h1>С чего начнём?</h1>
            <p className="lede">
              Добавьте один реальный счёт. Начальный остаток будет записан отдельной проводкой и
              останется проверяемым.
            </p>
          </div>
          <ol className="stepper stepper--vertical" aria-label="Шаги настройки">
            <li className="is-done">
              <span>✓</span> Профиль
            </li>
            <li className="is-done">
              <span>✓</span> Формат
            </li>
            <li aria-current="step" className="is-done">
              <span>3</span> Первый счёт
            </li>
          </ol>
        </header>
        <section className="account-form-panel" aria-labelledby="account-title">
          <div>
            <p className="eyebrow">Счёт 01</p>
            <h2 id="account-title">Основной источник денег</h2>
          </div>
          <form className="form-stack" onSubmit={(event) => void submit(event)}>
            <InputField
              autoFocus
              label="Название счёта"
              maxLength={160}
              onChange={(event) => {
                setName(event.target.value);
              }}
              required
              value={name}
            />
            <SelectField
              label="Тип счёта"
              onChange={(event) => {
                setKind(event.target.value as AccountKind);
              }}
              value={kind}
            >
              {accountKinds.map((value) => (
                <option key={value} value={value}>
                  {accountKindLabels[value]}
                </option>
              ))}
            </SelectField>
            <div className="form-grid">
              <MoneyInput
                currency={profile.base_currency}
                error={balanceError}
                label="Начальный остаток"
                locale={profile.locale}
                onChange={setBalance}
                value={balance}
              />
              <DateControl
                label="Дата остатка"
                onChange={(event) => {
                  setBalanceDate(event.target.value);
                }}
                required
                value={balanceDate}
              />
            </div>
            <p className="field-note">Оставьте сумму пустой или укажите 0, если счёт пока пуст.</p>
            {error === undefined ? null : (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
            <Button className="button--wide" loading={pending} type="submit">
              Создать счёт и открыть обзор
            </Button>
          </form>
        </section>
      </div>
    </main>
  );
}

function AppShell({
  children,
  navigate,
  onLogout,
  profile,
}: {
  children: ReactNode;
  navigate: Navigate;
  onLogout: () => Promise<void>;
  profile: ProfileResponse;
}) {
  const [profileOpen, setProfileOpen] = useState(false);
  const [logoutPending, setLogoutPending] = useState(false);

  return (
    <div className="app-frame">
      <a className="skip-link" href="#main-content">
        Перейти к содержимому
      </a>
      <aside className="sidebar">
        <a
          className="brand brand--sidebar"
          href="/app/dashboard"
          onClick={(event) => {
            event.preventDefault();
            navigate("/app/dashboard");
          }}
        >
          <BrandMark />
          <span>
            Financial
            <br />
            Analytics
          </span>
        </a>
        <nav aria-label="Основная навигация" className="main-nav">
          <RouteLink className="nav-link is-active" navigate={navigate} to="/app/dashboard">
            <span aria-hidden="true">⌂</span>
            Обзор
          </RouteLink>
        </nav>
        <button
          className="profile-button"
          onClick={() => {
            setProfileOpen(true);
          }}
          type="button"
        >
          <span className="profile-button__avatar" aria-hidden="true">
            {profile.email.slice(0, 1).toUpperCase()}
          </span>
          <span>
            <strong>Профиль</strong>
            <small>{profile.email}</small>
          </span>
        </button>
      </aside>
      <header className="mobile-header">
        <a
          aria-label="Financial Analytics — обзор"
          className="brand"
          href="/app/dashboard"
          onClick={(event) => {
            event.preventDefault();
            navigate("/app/dashboard");
          }}
        >
          <BrandMark />
        </a>
        <p>Financial Analytics</p>
        <button
          aria-label="Открыть профиль"
          className="avatar-button"
          onClick={() => {
            setProfileOpen(true);
          }}
          type="button"
        >
          {profile.email.slice(0, 1).toUpperCase()}
        </button>
      </header>
      <main className="app-content" id="main-content" tabIndex={-1}>
        {children}
      </main>
      <nav aria-label="Навигация на мобильном" className="mobile-nav">
        <RouteLink className="mobile-nav__link is-active" navigate={navigate} to="/app/dashboard">
          <span aria-hidden="true">⌂</span>
          Обзор
        </RouteLink>
        <button
          className="mobile-nav__link"
          onClick={() => {
            setProfileOpen(true);
          }}
          type="button"
        >
          <span aria-hidden="true">○</span>
          Профиль
        </button>
      </nav>
      <Dialog
        description="Данные профиля и управление текущей сессией."
        onClose={() => {
          setProfileOpen(false);
        }}
        open={profileOpen}
        title="Профиль"
        variant="drawer"
      >
        <dl className="profile-details">
          <div>
            <dt>Email</dt>
            <dd>{profile.email}</dd>
          </div>
          <div>
            <dt>Основная валюта</dt>
            <dd>{profile.base_currency}</dd>
          </div>
          <div>
            <dt>Формат</dt>
            <dd>{profile.locale}</dd>
          </div>
          <div>
            <dt>Часовой пояс</dt>
            <dd>{profile.timezone}</dd>
          </div>
        </dl>
        <Button
          className="button--wide"
          loading={logoutPending}
          onClick={() => {
            setLogoutPending(true);
            void onLogout().finally(() => {
              setLogoutPending(false);
            });
          }}
          variant="secondary"
        >
          Выйти
        </Button>
      </Dialog>
    </div>
  );
}

function Dashboard({
  accounts,
  profile,
}: {
  accounts: AccountResponse[];
  profile: ProfileResponse;
}) {
  return (
    <div className="dashboard">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Обзор · {profile.base_currency}</p>
          <h1>Добро пожаловать.</h1>
          <p className="lede">
            Основа готова. Все будущие показатели будут собираться из проводок.
          </p>
        </div>
        <div className="date-stamp">
          <span>Часовой пояс</span>
          <strong>{profile.timezone}</strong>
        </div>
      </header>
      <section className="account-section" aria-labelledby="accounts-title">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Активы</p>
            <h2 id="accounts-title">Ваши счета</h2>
          </div>
          <span className="count-badge">{accounts.length}</span>
        </div>
        <ResponsiveDataView
          caption="Счета и текущие остатки"
          columns={[
            {
              key: "name",
              label: "Счёт",
              render: (account) => (
                <span className="account-name">
                  <span aria-hidden="true">{account.kind === "cash" ? "◇" : "▱"}</span>
                  {account.name}
                </span>
              ),
            },
            {
              key: "kind",
              label: "Тип",
              render: (account) => accountKindLabel(account.kind),
            },
            {
              key: "balance",
              label: "Остаток",
              numeric: true,
              render: (account) =>
                formatMoney(account.balance.amount, account.balance.currency, profile.locale),
            },
          ]}
          getKey={(account) => account.id}
          rows={accounts}
        />
      </section>
      <aside className="foundation-note">
        <span aria-hidden="true">i</span>
        <div>
          <strong>Базовая настройка завершена</strong>
          <p>Операции и аналитические разделы появятся на следующем этапе интерфейса.</p>
        </div>
      </aside>
    </div>
  );
}

function GuestLayout({
  children,
  kicker,
  title,
}: {
  children: ReactNode;
  kicker: string;
  title: string;
}) {
  return (
    <main className="guest-page" id="main-content">
      <section className="guest-story" aria-labelledby="guest-story-title">
        <a className="brand brand--light" href="/login">
          <BrandMark />
          <span>Financial Analytics</span>
        </a>
        <div className="guest-story__copy">
          <p>{kicker}</p>
          <h2 id="guest-story-title">{title}</h2>
        </div>
        <p className="guest-story__foot">
          Цифры, которые можно проверить. Решения, которые понятны.
        </p>
      </section>
      <div className="guest-workspace">{children}</div>
    </main>
  );
}

function RouteLink({
  children,
  className,
  navigate,
  to,
}: {
  children: ReactNode;
  className?: string | undefined;
  navigate: Navigate;
  to: string;
}) {
  return (
    <a
      className={className}
      href={to}
      onClick={(event) => {
        if (!event.defaultPrevented && event.button === 0 && !event.metaKey && !event.ctrlKey) {
          event.preventDefault();
          navigate(to);
        }
      }}
    >
      {children}
    </a>
  );
}

function BrandMark() {
  return (
    <svg aria-hidden="true" className="brand-mark" viewBox="0 0 40 40">
      <path d="M7 29V19c0-7.18 5.82-13 13-13s13 5.82 13 13v10" />
      <path d="M13 30V19a7 7 0 0 1 14 0v11" />
      <path d="M5 30h30" />
    </svg>
  );
}

function NotFound({ navigate }: { navigate: Navigate }) {
  return (
    <ErrorState
      message="Такого раздела пока нет или адрес изменился."
      onRetry={() => {
        navigate("/app/dashboard", { replace: true });
      }}
      title="Страница не найдена"
    />
  );
}

function useBrowserPath(): [string, Navigate] {
  const [path, setPath] = useState(() => normalizePath(window.location.pathname));
  useEffect(() => {
    const update = () => {
      setPath(normalizePath(window.location.pathname));
    };
    window.addEventListener("popstate", update);
    return () => {
      window.removeEventListener("popstate", update);
    };
  }, []);
  const navigate = useCallback<Navigate>((nextPath, options) => {
    const normalized = normalizePath(nextPath);
    if (options?.replace === true) {
      window.history.replaceState(null, "", normalized);
    } else {
      window.history.pushState(null, "", normalized);
    }
    setPath(normalized);
    window.scrollTo({ top: 0, behavior: "auto" });
  }, []);
  return [path, navigate];
}

function normalizePath(path: string): string {
  if (path === "") return "/";
  return path.length > 1 ? path.replace(/\/+$/u, "") : path;
}

function formatMoney(amount: string, currency: string, locale: string): string {
  const negative = amount.startsWith("-");
  const unsigned = negative ? amount.slice(1) : amount;
  const [integer = "0", fraction] = unsigned.split(".");
  let group = "\u00a0";
  let decimal = ",";
  try {
    const parts = new Intl.NumberFormat(locale).formatToParts(12345.6);
    group = parts.find((part) => part.type === "group")?.value ?? group;
    decimal = parts.find((part) => part.type === "decimal")?.value ?? decimal;
  } catch {
    // Stable Russian-style fallback keeps the decimal string exact.
  }
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/gu, group);
  return `${negative ? "−" : ""}${grouped}${fraction === undefined ? "" : `${decimal}${fraction}`}\u00a0${currency}`;
}

function accountKindLabel(kind: string): string {
  return accountKinds.includes(kind as AccountKind) ? accountKindLabels[kind as AccountKind] : kind;
}

function defaultLocale(): string {
  const locale = navigator.language;
  if (locale === "ru-RU" || locale === "en-US" || locale === "en-GB" || locale === "kk-KZ") {
    return locale;
  }
  if (locale.startsWith("kk")) return "kk-KZ";
  if (locale.startsWith("en")) return "en-US";
  return "ru-RU";
}

function defaultTimezone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

interface BoundaryState {
  failed: boolean;
}

class GlobalErrorBoundary extends Component<{ children: ReactNode }, BoundaryState> {
  override state: BoundaryState = { failed: false };

  static getDerivedStateFromError(): BoundaryState {
    return { failed: true };
  }

  override componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Unhandled application error", error.name, info.componentStack);
  }

  override render() {
    if (this.state.failed) {
      return (
        <main className="centered-page" id="main-content">
          <ErrorState
            message="Непредвиденная ошибка остановила этот экран. Финансовые данные не изменены."
            onRetry={() => {
              window.location.reload();
            }}
          />
        </main>
      );
    }
    return this.props.children;
  }
}
