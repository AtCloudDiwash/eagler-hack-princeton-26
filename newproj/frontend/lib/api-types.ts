/**
 * API contract between the FastAPI backend (backend/schemas.py mirrors this) and the Next.js frontend.
 * Base URL: process.env.NEXT_PUBLIC_API_URL (default http://localhost:8000). All routes are under /api.
 *
 *   GET  /api/health                                -> Health
 *   GET  /api/tiles/{z}/{x}/{y}                     -> Vexcel ortho tile image (key stays on the backend)
 *   POST /api/search            {query}             -> SearchResponse          (Step 1-2: discovery, no agents)
 *   GET  /api/properties/{id}                       -> PropertyDetail          (Step 3: selected building)
 *   GET  /api/properties/{id}/neighborhood?radius_m=400 -> Neighborhood        (Step 3: surroundings)
 *   POST /api/analyses          AnalysisRequest     -> {id, status}            (Step 4: start agents)
 *   GET  /api/analyses/{id}                         -> Analysis                (poll; events stream in while running)
 *   GET  /api/analyses                              -> AnalysisSummary[]       (history / compare picker)
 *   GET  /api/business-types                        -> BusinessTypeInfo[]
 */

export type GeoJSONGeometry = { type: "Polygon" | "MultiPolygon" | "Point"; coordinates: unknown };

export type Health = {
  llm: { ok: boolean; provider: string; model: string | null; error?: string | null }; // local Codex CLI
  vexcel: "live" | "demo";
  census: boolean;
  matterport: boolean;
};

export type BusinessTypeInfo = { id: string; label: string; icon: string; default_radius_m: number };

// ---------------------------------------------------------------- discovery

export type Budget = { amount: number; period: "monthly" | "upfront" | "annual"; text: string };

export type Intent = {
  business_type: string; // key in backend/config/business_types.yaml, e.g. "restaurant"
  business_label: string; // "Restaurant"
  location_text: string | null; // "Houston"
  seats: number | null;
  sqft: number | null;
  requirements: string[]; // extra needs pulled from the query ("parking", "accessible")
  budget: Budget | null; // stated in the query ("$8k/month", "budget of $300k"), else null
  parser: "llm" | "rules";
};

export type Candidate = {
  id: string;
  lat: number;
  lon: number;
  footprint: GeoJSONGeometry | null; // building outline, [lon, lat]
  parcel: GeoJSONGeometry | null;
  building_type: string | null; // Vexcel building-type.class, e.g. "commercial"
  area_sqft: number | null;
  roof_condition: number | null; // 1 Bad .. 5 Great
  roof_condition_label: string | null;
  stories_est: number | null;
  match_score: number; // 0-100, deterministic pre-screen (NOT the agent analysis)
  match_reasons: string[];
  source: "vexcel" | "osm" | "demo";
  address: string | null;
};

export type SearchResponse = {
  intent: Intent;
  location: { name: string; lat: number; lon: number; coverage: boolean } | null;
  data_mode: "vexcel_live" | "vexcel_demo" | "osm_only";
  candidates: Candidate[];
  notes: string[]; // human-readable caveats ("Outside Vexcel coverage: footprints from OpenStreetMap")
};

export type KeyFact = { group: string; label: string; value: string; note?: string | null };

export type PropertyDetail = Candidate & {
  key_facts: KeyFact[]; // the most useful fields, readable
  raw: Record<string, unknown> | null; // complete Vexcel GeoJSON feature
  imagery: { collection: string | null; date: string | null; gsd_m: number | null } | null;
};

export type NeighborBuilding = {
  id: string;
  lat: number;
  lon: number;
  footprint: GeoJSONGeometry | null;
  building_type: string | null;
  area_sqft: number | null;
  roof_condition: number | null;
};

export type Place = { id: string; name: string | null; category: string; group: string; lat: number; lon: number; distance_m: number };

export type Neighborhood = {
  center: { lat: number; lon: number };
  radius_m: number;
  buildings: NeighborBuilding[];
  building_mix: Record<string, number>; // building type -> count
  places: Place[];
  place_groups: Record<string, number>; // group label -> count, e.g. "Restaurants & cafes": 29
  stats: Record<string, number | string | null>; // avg roof condition, vehicles seen, etc.
  sources: { name: string; status: "used" | "unavailable" | "demo"; note: string }[];
};

// ---------------------------------------------------------------- analysis

export type AnalysisRequest = {
  query: string;
  intent: Intent;
  property_id: string;
  radius_m: number;
  requirements?: string; // free-text extra requirements from the user
};

export type AgentName = "vexcel" | "neighborhood" | "compliance" | "cost" | "matterport" | "engine";

export type AnalysisEvent = {
  t: number; // seconds since analysis start
  agent: AgentName;
  type: "start" | "plan" | "tool_call" | "tool_result" | "thinking" | "done" | "error" | "skipped" | "followup" | "validation";
  message: string;
  data?: Record<string, unknown> | null;
};

export type Evidence = {
  id: string; // "E7" — cited by findings/metrics
  agent: AgentName;
  tool: string;
  source: string; // "Vexcel /property/extract", "OpenStreetMap (Overpass)", "Houston Code §26-492"
  url: string | null;
  summary: string;
  data: unknown;
};

export type Finding = {
  id: string;
  title: string;
  detail: string;
  impact: "positive" | "negative" | "neutral";
  severity: "low" | "medium" | "high";
  kind: "fact" | "inference" | "assumption";
  why_it_matters: string;
  evidence_ids: string[];
  metric_ids: string[];
  verified: boolean; // false if it cited evidence that doesn't exist (engine validation)
};

export type MetricStatus = "strong" | "adequate" | "weak" | "blocker" | "unknown";

export type MetricResult = {
  id: string;
  name: string;
  category: "common" | "dynamic";
  group: string; // "Building" | "Location" | "Compliance" | "Cost" | "Interior" ...
  owner_agent: AgentName;
  weight: number;
  status: MetricStatus;
  score: number | null; // 0-100, computed in Python from status (+ evidence), null when unknown
  why_it_matters: string; // business-specific, from config
  rationale: string; // agent's explanation
  evidence_ids: string[];
  facts: string[];
  assumptions: string[];
};

export type AgentReport = {
  agent: AgentName;
  label: string; // "Vexcel Agent"
  status: "completed" | "partial" | "failed" | "skipped";
  summary: string;
  findings: Finding[];
  missing_information: string[];
  contradictions: string[];
  followups: string[]; // suggested further investigation
  tool_calls: number;
  duration_s: number;
  error: string | null;
};

export type CostLine = { id: string; label: string; low: number; high: number; reason: string; evidence_ids: string[] };

export type Costs = {
  currency: "USD";
  sqft_used: number | null;
  sqft_basis: string;
  rent: { low_annual: number; high_annual: number; per_sqft_low: number; per_sqft_high: number; source: string } | null;
  fitout: { low: number; high: number; line_items: CostLine[] };
  monthly_occupancy: { low: number; high: number } | null; // rent + NNN + amortized fit-out
  upfront: { low: number; high: number };
  assumptions: string[];
  /** Estimate vs the user's budget, or vs a typical budget for this use + size when none was given. */
  budget?: {
    source: "user" | "typical";
    period: "monthly" | "upfront" | "annual";
    amount: number;
    compare_low: number;
    compare_high: number;
    status: "within" | "partly" | "over";
    note: string;
  };
};

export type ComplianceItem = {
  id: string;
  rule: string;
  status: "pass" | "risk" | "fail" | "unknown";
  detail: string;
  citation: string | null;
  url: string | null;
  evidence_ids: string[];
};

export type Verdict = "recommended" | "conditional" | "not_recommended" | "insufficient_evidence";

export type AnalysisResult = {
  business_type: string;
  business_label: string;
  recommendation: {
    verdict: Verdict;
    label: string; // "Recommended with conditions"
    score: number; // 0-100 weighted, computed in Python
    confidence: number; // 0-100, share of metric weight backed by evidence
    headline: string;
    explanation: string; // LLM narrative grounded on the scored results
    key_reasons: { text: string; impact: "positive" | "negative"; metric_id: string | null; evidence_ids: string[] }[];
    dealbreakers: string[];
  };
  metrics: MetricResult[];
  agents: AgentReport[];
  evidence: Evidence[];
  costs: Costs | null;
  compliance: ComplianceItem[];
  neighborhood: (Neighborhood & { radius_reason: string; highlights: string[] }) | null;
  risks: { text: string; severity: "low" | "medium" | "high"; agent: AgentName }[];
  open_questions: { question: string; why: string; suggested_source: string; agent: AgentName }[];
  conflicts: { description: string; agents: AgentName[]; resolution: string }[];
  followups_run: { agent: AgentName; question: string; outcome: string }[];
  data_sources: { name: string; status: "used" | "unavailable" | "demo"; note: string }[];
};

export type Analysis = {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  created_at: string;
  query: string;
  intent: Intent;
  property: PropertyDetail;
  radius_m: number;
  events: AnalysisEvent[];
  result: AnalysisResult | null;
  error: string | null;
};

export type AnalysisSummary = {
  id: string;
  status: Analysis["status"];
  created_at: string;
  query: string;
  business_label: string;
  property: { id: string; lat: number; lon: number; building_type: string | null; area_sqft: number | null; address: string | null };
  score: number | null;
  confidence: number | null;
  verdict: Verdict | null;
};
