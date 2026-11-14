// Typed client for the Turnkey Matchmaker REST API (docs/API_CONTRACT.md).
// All URLs are relative; next.config.ts rewrites /api/v1/*, /static/* and /health to the backend.

import type {
  AnalysisSummary,
  AnalyzeRequest,
  AnalyzeResponse,
  BusinessType,
  Criterion,
  HealthResponse,
  Property,
} from "./types";

/** Error carrying the HTTP status and FastAPI's `detail` message (status 0 = network failure). */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** FastAPI returns `{detail: string}` or, for 422, `{detail: [{msg, loc}, ...]}`. */
function detailMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const messages = detail
        .map((entry) => (entry && typeof entry === "object" && "msg" in entry ? String(entry.msg) : null))
        .filter(Boolean);
      if (messages.length > 0) return messages.join("; ");
    }
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}), ...init?.headers },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, "Could not reach the Turnkey Matchmaker API. Is the backend running on port 8000?");
  }

  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }

  if (!response.ok) {
    // The Next.js dev proxy answers 500 with an HTML/empty body when the backend is down.
    const fallback =
      response.status >= 500 && body === null
        ? "The API is unavailable right now. Is the backend running on port 8000?"
        : `Request failed (${response.status} ${response.statusText})`;
    throw new ApiError(response.status, detailMessage(body, fallback));
  }
  if (body === null) throw new ApiError(response.status, "The API returned an empty or invalid response.");
  return body as T;
}

/** Builds a query string, skipping empty values. */
export function toQuery(params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && String(value).trim() !== "") search.set(key, String(value).trim());
  }
  const query = search.toString();
  return query ? `?${query}` : "";
}

export interface CriteriaQuery {
  business_type?: string;
  city?: string;
  state?: string;
}

export interface PropertiesQuery extends CriteriaQuery {
  min_size?: number;
  max_size?: number;
  budget?: number;
}

type Opts = { signal?: AbortSignal };

export const api = {
  health: (opts?: Opts) => request<HealthResponse>("/health", opts),
  businessTypes: (opts?: Opts) => request<BusinessType[]>("/api/v1/business-types", opts),
  criteria: (query: CriteriaQuery = {}, opts?: Opts) =>
    request<Criterion[]>(`/api/v1/criteria${toQuery({ ...query })}`, opts),
  properties: (query: PropertiesQuery = {}, opts?: Opts) =>
    request<Property[]>(`/api/v1/properties${toQuery({ ...query })}`, opts),
  analyze: (body: AnalyzeRequest, opts?: Opts) =>
    request<AnalyzeResponse>("/api/v1/analyze", { method: "POST", body: JSON.stringify(body), ...opts }),
  analyses: (limit = 20, opts?: Opts) => request<AnalysisSummary[]>(`/api/v1/analyses${toQuery({ limit })}`, opts),
  analysis: (id: string, opts?: Opts) =>
    request<AnalyzeResponse>(`/api/v1/analyses/${encodeURIComponent(id)}`, opts),
};

/** Human-readable message for any thrown value. */
export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}
