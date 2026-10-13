export interface LivenessResponse {
  status: "alive";
}

export interface ReadinessResponse {
  status: "ready";
  checks: {
    database: "up";
  };
}

export interface ProblemDetails {
  type: string;
  title: string;
  status: number;
  detail: string;
  code: string;
  instance: string;
  request_id: string;
  correlation_id: string;
  errors?: Record<string, unknown>[];
}

export interface BootstrapRequest {
  email: string;
  password: string;
  base_currency: string;
  locale: string;
  timezone: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface ProfileResponse {
  id: string;
  email: string;
  base_currency: string;
  locale: string;
  timezone: string;
  status: "active" | "disabled";
  is_master: boolean;
  created_at: string;
}

export function isReadinessResponse(value: unknown): value is ReadinessResponse {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  if (candidate.status !== "ready") {
    return false;
  }
  const checks = candidate.checks;
  return (
    typeof checks === "object" &&
    checks !== null &&
    (checks as Record<string, unknown>).database === "up"
  );
}

export function isProfileResponse(value: unknown): value is ProfileResponse {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.id === "string" &&
    typeof candidate.email === "string" &&
    typeof candidate.base_currency === "string" &&
    typeof candidate.locale === "string" &&
    typeof candidate.timezone === "string" &&
    (candidate.status === "active" || candidate.status === "disabled") &&
    typeof candidate.is_master === "boolean" &&
    typeof candidate.created_at === "string"
  );
}
