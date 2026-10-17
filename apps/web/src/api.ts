import {
  ApiError,
  FinancialAnalyticsClient,
  type AccountResponse,
  type AdjustmentRequest,
  type AllowlistRequest,
  type AllowlistResponse,
  type AdviceProviderStatusResponse,
  type AdviceRequest,
  type AdviceResponse,
  type BootstrapRequest,
  type CreateAccountRequest,
  type CreateCategoryGroupRequest,
  type CreateCategoryRequest,
  type CreateDepositRequest,
  type CreateRecurringRuleRequest,
  type DashboardResponse,
  type DepositCashflowRequest,
  type DepositInterestRequest,
  type DepositTermsResponse,
  type DepositValuationResponse,
  type FinancialReportResponse,
  type ForecastComparisonResponse,
  type ForecastRunResponse,
  type GoalInput,
  type GoalResponse,
  type EmailTokenRequest,
  type InvitationAcceptanceRequest,
  type InvitationRequest,
  type InvitationResponse,
  type LoginRequest,
  type OperationRequest,
  type PeriodGranularity,
  type PreviewOccurrenceResponse,
  type PreviewOccurrencesRequest,
  type ProblemDetails,
  type ProfileResponse,
  type PasswordResetConfirmationRequest,
  type PasswordResetRequest,
  type RecurringRuleResponse,
  type ReversalRequest,
  type ScenarioInput,
  type ScenarioResponse,
  type TransactionKind,
  type TransactionPageResponse,
  type TransactionResponse,
  type TransferRequest,
} from "@financial-analytics/api-contracts";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const csrfCookieName = "fa_csrf";

export type SessionSnapshot =
  | { kind: "anonymous" }
  | { kind: "authenticated"; profile: ProfileResponse; accounts: AccountResponse[] };

export interface FinanceApi {
  bootstrapSession(): Promise<SessionSnapshot>;
  bootstrapMaster(payload: BootstrapRequest): Promise<ProfileResponse>;
  acceptInvitation(payload: InvitationAcceptanceRequest): Promise<ProfileResponse>;
  requestPasswordReset(payload: PasswordResetRequest): Promise<void>;
  confirmPasswordReset(payload: PasswordResetConfirmationRequest): Promise<void>;
  confirmEmailVerification(payload: EmailTokenRequest): Promise<ProfileResponse>;
  login(payload: LoginRequest): Promise<ProfileResponse>;
  listAllowlist(): Promise<AllowlistResponse[]>;
  addAllowlist(payload: AllowlistRequest): Promise<AllowlistResponse>;
  revokeAllowlist(entryId: string): Promise<AllowlistResponse>;
  listInvitations(): Promise<InvitationResponse[]>;
  createInvitation(payload: InvitationRequest): Promise<InvitationResponse>;
  listAccounts(): Promise<AccountResponse[]>;
  createAccount(payload: CreateAccountRequest): Promise<AccountResponse>;
  getDashboard(periodStart?: string, periodEnd?: string): Promise<DashboardResponse>;
  listCategoryGroups(): ReturnType<FinancialAnalyticsClient["listCategoryGroups"]>;
  createCategoryGroup(
    payload: CreateCategoryGroupRequest,
  ): ReturnType<FinancialAnalyticsClient["createCategoryGroup"]>;
  listCategories(): ReturnType<FinancialAnalyticsClient["listCategories"]>;
  createCategory(
    payload: CreateCategoryRequest,
  ): ReturnType<FinancialAnalyticsClient["createCategory"]>;
  listTransactions(filters?: TransactionFilters): Promise<TransactionPageResponse>;
  createOperation(
    kind: "income" | "expense",
    payload: OperationRequest,
  ): Promise<TransactionResponse>;
  createTransfer(payload: TransferRequest): Promise<TransactionResponse>;
  createAdjustment(payload: AdjustmentRequest): Promise<TransactionResponse>;
  reverseTransaction(transactionId: string, payload: ReversalRequest): Promise<TransactionResponse>;
  exportTransactions(filters?: TransactionFilters): Promise<string>;
  listRecurringRules(): Promise<RecurringRuleResponse[]>;
  previewRecurringOccurrences(
    payload: PreviewOccurrencesRequest,
  ): Promise<PreviewOccurrenceResponse[]>;
  createRecurringRule(payload: CreateRecurringRuleRequest): Promise<RecurringRuleResponse>;
  setRecurringRulePaused(
    rule: RecurringRuleResponse,
    paused: boolean,
  ): Promise<RecurringRuleResponse>;
  listDeposits(): Promise<DepositTermsResponse[]>;
  createDeposit(payload: CreateDepositRequest): Promise<DepositTermsResponse>;
  getDepositValuation(depositId: string, asOf: string): Promise<DepositValuationResponse>;
  recordDepositCashflow(
    depositId: string,
    payload: DepositCashflowRequest,
  ): Promise<TransactionResponse>;
  recordDepositInterest(
    depositId: string,
    payload: DepositInterestRequest,
  ): Promise<TransactionResponse>;
  getFinancialReport(
    periodStart: string,
    periodEnd: string,
    granularity: PeriodGranularity,
  ): Promise<FinancialReportResponse>;
  listForecastScenarios(): Promise<ScenarioResponse[]>;
  createForecastScenario(payload: ScenarioInput): Promise<ScenarioResponse>;
  getForecast(
    currency: string,
    through?: string,
    scenarioId?: string,
  ): Promise<ForecastRunResponse>;
  compareForecasts(
    currency: string,
    baselineHorizon: string,
    scenarioIds: string[],
  ): Promise<ForecastComparisonResponse>;
  listFinancialGoals(): Promise<GoalResponse[]>;
  createFinancialGoal(payload: GoalInput): Promise<GoalResponse>;
  getAdviceProviderStatus(): Promise<AdviceProviderStatusResponse>;
  generateAdvice(payload: AdviceRequest): Promise<AdviceResponse>;
  logout(): Promise<void>;
}

export interface TransactionFilters {
  accountId?: string | undefined;
  categoryId?: string | undefined;
  kind?: TransactionKind | undefined;
  occurredFrom?: string | undefined;
  occurredTo?: string | undefined;
  search?: string | undefined;
  cursor?: string | undefined;
  limit?: number | undefined;
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

  async acceptInvitation(payload: InvitationAcceptanceRequest): Promise<ProfileResponse> {
    const profile = await this.client.accept_invitation_api_v1_auth_invitations_accept_post({
      body: payload,
    });
    this.sessionBootstrap = undefined;
    return profile;
  }

  async requestPasswordReset(payload: PasswordResetRequest): Promise<void> {
    await this.client.request_password_reset_api_v1_auth_password_reset_request_post({
      body: payload,
    });
  }

  confirmPasswordReset(payload: PasswordResetConfirmationRequest): Promise<void> {
    return this.client.confirm_password_reset_api_v1_auth_password_reset_confirm_post({
      body: payload,
    });
  }

  confirmEmailVerification(payload: EmailTokenRequest): Promise<ProfileResponse> {
    return this.client.confirm_email_verification_api_v1_auth_email_verification_confirm_post({
      body: payload,
    });
  }

  async login(payload: LoginRequest): Promise<ProfileResponse> {
    const profile = await this.client.login_api_v1_auth_login_post({ body: payload });
    this.sessionBootstrap = undefined;
    return profile;
  }

  listAllowlist(): Promise<AllowlistResponse[]> {
    return this.withSessionRecovery(() => this.client.list_allowlist_api_v1_admin_allowlist_get());
  }

  addAllowlist(payload: AllowlistRequest): Promise<AllowlistResponse> {
    return this.withSessionRecovery(() =>
      this.client.add_allowlist_api_v1_admin_allowlist_post({
        xCSRFToken: this.csrfToken(),
        body: payload,
      }),
    );
  }

  revokeAllowlist(entryId: string): Promise<AllowlistResponse> {
    return this.withSessionRecovery(() =>
      this.client.revoke_allowlist_api_v1_admin_allowlist__entry_id__delete({
        entryId,
        xCSRFToken: this.csrfToken(),
      }),
    );
  }

  listInvitations(): Promise<InvitationResponse[]> {
    return this.withSessionRecovery(() =>
      this.client.list_invitations_api_v1_admin_invitations_get(),
    );
  }

  createInvitation(payload: InvitationRequest): Promise<InvitationResponse> {
    return this.withSessionRecovery(() =>
      this.client.create_invitation_api_v1_admin_invitations_post({
        xCSRFToken: this.csrfToken(),
        body: payload,
      }),
    );
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

  getDashboard(periodStart?: string, periodEnd?: string): Promise<DashboardResponse> {
    return this.withSessionRecovery(() =>
      this.client.getAnalyticsDashboard({
        periodStart: periodStart ?? null,
        periodEnd: periodEnd ?? null,
        granularity: "month",
      }),
    );
  }

  listCategoryGroups() {
    return this.withSessionRecovery(() => this.client.listCategoryGroups());
  }
  createCategoryGroup(payload: CreateCategoryGroupRequest) {
    return this.mutate((token, key) =>
      this.client.createCategoryGroup({ idempotencyKey: key, xCSRFToken: token, body: payload }),
    );
  }
  listCategories() {
    return this.withSessionRecovery(() => this.client.listCategories());
  }
  createCategory(payload: CreateCategoryRequest) {
    return this.mutate((token, key) =>
      this.client.createCategory({ idempotencyKey: key, xCSRFToken: token, body: payload }),
    );
  }
  listTransactions(filters: TransactionFilters = {}) {
    return this.withSessionRecovery(() =>
      this.client.listTransactions({
        accountId: filters.accountId ?? null,
        categoryId: filters.categoryId ?? null,
        kind: filters.kind ?? null,
        occurredFrom: filters.occurredFrom ?? null,
        occurredTo: filters.occurredTo ?? null,
        search: filters.search ?? null,
        cursor: filters.cursor ?? null,
        limit: filters.limit ?? 20,
      }),
    );
  }
  createOperation(kind: "income" | "expense", payload: OperationRequest) {
    return this.mutate((token, key) =>
      kind === "income"
        ? this.client.createIncome({ idempotencyKey: key, xCSRFToken: token, body: payload })
        : this.client.createExpense({ idempotencyKey: key, xCSRFToken: token, body: payload }),
    );
  }
  createTransfer(payload: TransferRequest) {
    return this.mutate((token, key) =>
      this.client.createTransfer({ idempotencyKey: key, xCSRFToken: token, body: payload }),
    );
  }
  createAdjustment(payload: AdjustmentRequest) {
    return this.mutate((token, key) =>
      this.client.createAdjustment({ idempotencyKey: key, xCSRFToken: token, body: payload }),
    );
  }
  reverseTransaction(transactionId: string, payload: ReversalRequest) {
    return this.mutate((token, key) =>
      this.client.reverseTransaction({
        transactionId,
        idempotencyKey: key,
        xCSRFToken: token,
        body: payload,
      }),
    );
  }
  exportTransactions(filters: TransactionFilters = {}) {
    return this.withSessionRecovery(() =>
      this.client.exportTransactionsCsv({
        accountId: filters.accountId ?? null,
        categoryId: filters.categoryId ?? null,
        kind: filters.kind ?? null,
        occurredFrom: filters.occurredFrom ?? null,
        occurredTo: filters.occurredTo ?? null,
        search: filters.search ?? null,
      }),
    );
  }
  listRecurringRules() {
    return this.withSessionRecovery(() => this.client.listRecurringRules());
  }
  previewRecurringOccurrences(payload: PreviewOccurrencesRequest) {
    return this.withSessionRecovery(() =>
      this.client.previewRecurringOccurrences({ body: payload }),
    );
  }
  createRecurringRule(payload: CreateRecurringRuleRequest) {
    return this.withSessionRecovery(() =>
      this.client.createRecurringRule({ xCSRFToken: this.csrfToken(), body: payload }),
    );
  }
  setRecurringRulePaused(rule: RecurringRuleResponse, paused: boolean) {
    const args = { ruleId: rule.id, xCSRFToken: this.csrfToken(), body: { version: rule.version } };
    return this.withSessionRecovery(() =>
      paused ? this.client.pauseRecurringRule(args) : this.client.resumeRecurringRule(args),
    );
  }
  listDeposits() {
    return this.withSessionRecovery(() => this.client.listDeposits());
  }
  createDeposit(payload: CreateDepositRequest) {
    return this.mutate((token, key) =>
      this.client.createDeposit({ idempotencyKey: key, xCSRFToken: token, body: payload }),
    );
  }
  getDepositValuation(depositId: string, asOf: string) {
    return this.withSessionRecovery(() => this.client.getDepositValuation({ depositId, asOf }));
  }
  recordDepositCashflow(depositId: string, payload: DepositCashflowRequest) {
    return this.mutate((token, key) =>
      this.client.recordDepositCashflow({
        depositId,
        idempotencyKey: key,
        xCSRFToken: token,
        body: payload,
      }),
    );
  }
  recordDepositInterest(depositId: string, payload: DepositInterestRequest) {
    return this.mutate((token, key) =>
      this.client.recordDepositInterest({
        depositId,
        idempotencyKey: key,
        xCSRFToken: token,
        body: payload,
      }),
    );
  }
  getFinancialReport(periodStart: string, periodEnd: string, granularity: PeriodGranularity) {
    return this.withSessionRecovery(() =>
      this.client.getFinancialReport({ periodStart, periodEnd, granularity }),
    );
  }
  listForecastScenarios() {
    return this.withSessionRecovery(() => this.client.listForecastScenarios());
  }
  createForecastScenario(payload: ScenarioInput) {
    return this.mutate((token, key) =>
      this.client.createForecastScenario({ idempotencyKey: key, xCSRFToken: token, body: payload }),
    );
  }
  getForecast(currency: string, through?: string, scenarioId?: string) {
    return this.withSessionRecovery(() =>
      this.client.getForecast({
        currency,
        through: through ?? null,
        scenarioId: scenarioId ?? null,
      }),
    );
  }
  compareForecasts(currency: string, baselineHorizon: string, scenarioIds: string[]) {
    return this.withSessionRecovery(() =>
      this.client.compareForecastScenarios({
        body: { currency, baseline_horizon: baselineHorizon, scenario_ids: scenarioIds },
      }),
    );
  }
  listFinancialGoals() {
    return this.withSessionRecovery(() => this.client.listFinancialGoals());
  }
  createFinancialGoal(payload: GoalInput) {
    return this.mutate((token, key) =>
      this.client.createFinancialGoal({ idempotencyKey: key, xCSRFToken: token, body: payload }),
    );
  }
  getAdviceProviderStatus() {
    return this.withSessionRecovery(() => this.client.getAdviceProviderStatus());
  }
  generateAdvice(payload: AdviceRequest) {
    return this.withSessionRecovery(() => this.client.generateFinancialAdvice({ body: payload }));
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

  private mutate<T>(
    action: (csrfToken: string | null, idempotencyKey: string) => Promise<T>,
  ): Promise<T> {
    return this.withSessionRecovery(() => action(this.csrfToken(), createIdempotencyKey()));
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
