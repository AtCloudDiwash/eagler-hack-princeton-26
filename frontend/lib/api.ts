/** Thin typed client for the FastAPI backend. All secrets live on the backend. */
import type {
  Analysis,
  AnalysisRequest,
  AnalysisSummary,
  BusinessTypeInfo,
  ChatTurn,
  Health,
  Intent,
  Neighborhood,
  PropertyDetail,
  RefineResponse,
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
  /** Apply a follow-up ("make it 60 seats", "which ones have parking?") to the current search. */
  refine: (body: { intent: Intent; message: string; history: ChatTurn[]; matches: Record<string, unknown>[] }, signal?: AbortSignal) =>
    request<RefineResponse>("/api/search/refine", { method: "POST", body: JSON.stringify(body), signal }),
  /** With the user's request, the detail's panel tiles describe what this building offers that request. */
  property: (id: string, signal?: AbortSignal, forRequest?: { business_type: string; sqft?: number; budget?: { amount: number; period: string } | null }) => {
    const q = new URLSearchParams();
    if (forRequest) {
      q.set("business_type", forRequest.business_type);
      if (forRequest.sqft) q.set("sqft", String(Math.round(forRequest.sqft)));
      if (forRequest.budget) {
        q.set("budget_amount", String(forRequest.budget.amount));
        q.set("budget_period", forRequest.budget.period);
      }
    }
    return request<PropertyDetail>(`/api/properties/${encodeURIComponent(id)}${q.size ? `?${q}` : ""}`, { signal });
  },
  neighborhood: (id: string, radius: number, signal?: AbortSignal) =>
    request<Neighborhood>(`/api/properties/${encodeURIComponent(id)}/neighborhood?radius_m=${radius}`, { signal }),
  linkMatterport: (id: string, tour: string) =>
    request<PropertyDetail>(`/api/properties/${encodeURIComponent(id)}/matterport`, { method: "PUT", body: JSON.stringify({ tour }) }),
  unlinkMatterport: (id: string) => request<PropertyDetail>(`/api/properties/${encodeURIComponent(id)}/matterport`, { method: "DELETE" }),
  startAnalysis: (body: AnalysisRequest) =>
    request<{ id: string; status: string }>("/api/analyses", { method: "POST", body: JSON.stringify(body) }),
  analysis: (id: string, signal?: AbortSignal) => request<Analysis>(`/api/analyses/${encodeURIComponent(id)}`, { signal }),
  analyses: () => request<AnalysisSummary[]>("/api/analyses"),
  searchGroup: (id: string) => request<SearchGroup>(`/api/searches/${encodeURIComponent(id)}`),
};
