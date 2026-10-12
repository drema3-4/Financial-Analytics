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
