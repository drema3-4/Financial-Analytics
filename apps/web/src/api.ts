import { isReadinessResponse, type ReadinessResponse } from "@financial-analytics/api-contracts";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export async function fetchReadiness(signal?: AbortSignal): Promise<ReadinessResponse> {
  const request: RequestInit = { headers: { Accept: "application/json" } };
  if (signal !== undefined) {
    request.signal = signal;
  }
  const response = await fetch(`${apiBaseUrl}/health/ready`, request);
  if (!response.ok) {
    throw new Error(`Readiness check failed with HTTP ${String(response.status)}`);
  }
  const body: unknown = await response.json();
  if (!isReadinessResponse(body)) {
    throw new Error("Readiness response does not match the API contract");
  }
  return body;
}
