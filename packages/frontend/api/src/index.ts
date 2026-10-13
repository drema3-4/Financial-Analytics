export * from "./generated/client";

import type { ProfileResponse, ReadinessResponse } from "./generated/client";

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
