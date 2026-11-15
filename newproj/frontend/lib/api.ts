/** Thin typed client for the FastAPI backend. All secrets live on the backend. */
import type {
  Analysis,
  AnalysisRequest,
  AnalysisSummary,
  BusinessTypeInfo,
  Health,
  Neighborhood,
  PropertyDetail,
  SearchGroup,
  SearchResponse,
} from "./api-types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
export const TILE_URL = `${API_URL}/api/tiles/{z}/{x}/{y}`;

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit & { signal?: AbortSignal }): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(`Can't reach the backend at ${API_URL}. Is it running?`, 0);
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : body.error || JSON.stringify(body.detail ?? body);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detail, res.status);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => request<Health>("/api/health"),
  businessTypes: () => request<BusinessTypeInfo[]>("/api/business-types"),
  search: (query: string, signal?: AbortSignal) =>
    request<SearchResponse>("/api/search", { method: "POST", body: JSON.stringify({ query }), signal }),
  property: (id: string, signal?: AbortSignal) => request<PropertyDetail>(`/api/properties/${encodeURIComponent(id)}`, { signal }),
  neighborhood: (id: string, radius: number, signal?: AbortSignal) =>
    request<Neighborhood>(`/api/properties/${encodeURIComponent(id)}/neighborhood?radius_m=${radius}`, { signal }),
  startAnalysis: (body: AnalysisRequest) =>
    request<{ id: string; status: string }>("/api/analyses", { method: "POST", body: JSON.stringify(body) }),
  analysis: (id: string, signal?: AbortSignal) => request<Analysis>(`/api/analyses/${encodeURIComponent(id)}`, { signal }),
  analyses: () => request<AnalysisSummary[]>("/api/analyses"),
  searchGroup: (id: string) => request<SearchGroup>(`/api/searches/${encodeURIComponent(id)}`),
};
