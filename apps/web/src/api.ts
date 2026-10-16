import {
  ApiError,
  FinancialAnalyticsClient,
  type AccountResponse,
  type BootstrapRequest,
  type CreateAccountRequest,
  type LoginRequest,
  type ProblemDetails,
  type ProfileResponse,
} from "@financial-analytics/api-contracts";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const csrfCookieName = "fa_csrf";

export type SessionSnapshot =
  | { kind: "anonymous" }
  | { kind: "authenticated"; profile: ProfileResponse; accounts: AccountResponse[] };

export interface FinanceApi {
  bootstrapSession(): Promise<SessionSnapshot>;
  bootstrapMaster(payload: BootstrapRequest): Promise<ProfileResponse>;
  login(payload: LoginRequest): Promise<ProfileResponse>;
  listAccounts(): Promise<AccountResponse[]>;
  createAccount(payload: CreateAccountRequest): Promise<AccountResponse>;
  logout(): Promise<void>;
}

export class SessionExpiredError extends Error {
  constructor() {
    super("Сессия завершилась. Войдите снова, чтобы продолжить.");
    this.name = "SessionExpiredError";
  }
}

export class BrowserFinanceApi implements FinanceApi {
  private sessionBootstrap: Promise<SessionSnapshot> | undefined;

  constructor(
    private readonly client = new FinancialAnalyticsClient(apiBaseUrl),
    private readonly cookieSource: () => string = () => document.cookie,
  ) {}

  bootstrapSession(): Promise<SessionSnapshot> {
    this.sessionBootstrap ??= this.loadSession();
    return this.sessionBootstrap;
  }

  async bootstrapMaster(payload: BootstrapRequest): Promise<ProfileResponse> {
    const profile = await this.client.bootstrap_master_api_v1_auth_bootstrap_post({
      body: payload,
    });
    this.sessionBootstrap = undefined;
    return profile;
  }

  async login(payload: LoginRequest): Promise<ProfileResponse> {
    const profile = await this.client.login_api_v1_auth_login_post({ body: payload });
    this.sessionBootstrap = undefined;
    return profile;
  }

  async listAccounts(): Promise<AccountResponse[]> {
    return this.withSessionRecovery(() => this.client.listAccounts());
  }

  async createAccount(payload: CreateAccountRequest): Promise<AccountResponse> {
    const idempotencyKey = createIdempotencyKey();
    return this.withSessionRecovery(() =>
      this.client.createAccount({
        idempotencyKey,
        xCSRFToken: this.csrfToken(),
        body: payload,
      }),
    );
  }

  async logout(): Promise<void> {
    try {
      await this.client.logout_current_api_v1_auth_logout_post({
        xCSRFToken: this.csrfToken(),
      });
    } finally {
      this.sessionBootstrap = undefined;
    }
  }

  private async loadSession(): Promise<SessionSnapshot> {
    let profile: ProfileResponse;
    try {
      profile = await this.client.current_profile_api_v1_profile_get();
    } catch (error: unknown) {
      if (!isAuthenticationError(error)) {
        throw error;
      }
      try {
        profile = await this.refreshSession();
      } catch (refreshError: unknown) {
        if (isAuthenticationError(refreshError)) {
          return { kind: "anonymous" };
        }
        throw refreshError;
      }
    }
    const accounts = await this.withSessionRecovery(() => this.client.listAccounts());
    return { kind: "authenticated", profile, accounts };
  }

  private async withSessionRecovery<T>(action: () => Promise<T>): Promise<T> {
    try {
      return await action();
    } catch (error: unknown) {
      if (!isAuthenticationError(error)) {
        throw error;
      }
    }

    try {
      await this.refreshSession();
    } catch (error: unknown) {
      if (isAuthenticationError(error)) {
        throw new SessionExpiredError();
      }
      throw error;
    }

    try {
      return await action();
    } catch (error: unknown) {
      if (isAuthenticationError(error)) {
        throw new SessionExpiredError();
      }
      throw error;
    }
  }

  private refreshSession(): Promise<ProfileResponse> {
    const csrfToken = this.csrfToken();
    return this.client.refresh_api_v1_auth_refresh_post(
      csrfToken === null ? {} : { xCSRFToken: csrfToken },
    );
  }

  private csrfToken(): string | null {
    return readCookie(this.cookieSource(), csrfCookieName);
  }
}

export const browserFinanceApi: FinanceApi = new BrowserFinanceApi();

export function readCookie(cookieHeader: string, name: string): string | null {
  for (const part of cookieHeader.split(";")) {
    const [rawName, ...rawValue] = part.trim().split("=");
    if (rawName === name) {
      return decodeURIComponent(rawValue.join("="));
    }
  }
  return null;
}

export function apiErrorMessage(error: unknown): string {
  if (error instanceof SessionExpiredError) {
    return error.message;
  }
  if (error instanceof ApiError && isProblemDetails(error.payload)) {
    switch (error.payload.code) {
      case "invalid_credentials":
        return "Email или пароль не подошли.";
      case "bootstrap_closed":
        return "Пространство уже настроено. Войдите с email мастер-пользователя.";
      case "rate_limit_exceeded":
        return "Слишком много попыток. Подождите немного и попробуйте снова.";
      case "csrf_validation_failed":
        return "Защитный токен устарел. Обновите страницу и повторите действие.";
      default:
        return error.payload.detail || "Не удалось выполнить запрос.";
    }
  }
  return "Не удалось связаться с приложением. Проверьте подключение и попробуйте снова.";
}

function isProblemDetails(value: unknown): value is ProblemDetails {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Partial<ProblemDetails>;
  return (
    typeof candidate.status === "number" &&
    typeof candidate.code === "string" &&
    typeof candidate.detail === "string"
  );
}

function isAuthenticationError(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 401 || error.status === 403);
}

function createIdempotencyKey(): string {
  return crypto.randomUUID();
}
