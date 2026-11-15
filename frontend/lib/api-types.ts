/**
 * API contract between the FastAPI backend (backend/schemas.py mirrors this) and the Next.js frontend.
 * Base URL: process.env.NEXT_PUBLIC_API_URL (default http://localhost:8000). All routes are under /api.
 *
 *   GET  /api/health                                -> Health
 *   GET  /api/tiles/{z}/{x}/{y}                     -> Vexcel ortho tile image (key stays on the backend)
 *   POST /api/search            {query}             -> SearchResponse          (Step 1-2: discovery, no agents)
 *   GET  /api/properties/{id}                       -> PropertyDetail          (Step 3: selected building)
 *   GET  /api/properties/{id}/neighborhood?radius_m=400 -> Neighborhood        (Step 3: surroundings)
 *   PUT  /api/properties/{id}/matterport {tour}     -> PropertyDetail          (link a Matterport 3D tour)
 *   DELETE /api/properties/{id}/matterport          -> PropertyDetail          (unlink it)
 *   POST /api/analyses          AnalysisRequest     -> {id, status}            (Step 4: start agents)
 *   GET  /api/analyses/{id}                         -> Analysis                (poll; events stream in while running)
 *   GET  /api/analyses                              -> AnalysisSummary[]       (history / compare picker)
 *   GET  /api/business-types                        -> BusinessTypeInfo[]
 */

export type GeoJSONGeometry = { type: "Polygon" | "MultiPolygon" | "Point"; coordinates: unknown };

export type Health = {
  /** Provider analyses will use first, plus the whole fallback chain (Codex → Claude Code → Ollama). */
  llm: {
    ok: boolean;
    provider: string;
    label?: string | null;
    model: string | null;
    error?: string | null;
    providers?: { provider: string; label: string; model: string | null; ok: boolean; error?: string | null; cooling_down?: boolean }[];
  };
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
  budget: Budget | null; // the most recently stated budget ("$8k/month", "budget of $300k"), else null
  budgets?: Budget[]; // every stated budget, one per period (e.g. $9k/month AND $80k upfront)
  parser: "llm" | "rules";
  occupancy?: Record<string, number>; // counts stated: seats, chairs, members, class_size, employees, staff
  needs?: Need[]; // recognised needs (backend/config/needs.yaml)
  open_within_months?: number | null;
  tenure?: "lease" | "buy";
  near?: string[];
  avoid?: string[];
};

export type Need = { id: string; label: string; priority: "must" | "nice" };

export type CheckStatus = "pass" | "risk" | "unknown";

/** What the request implies (backend/services/program.py): size, occupancy, code needs, building needs. */
export type SpaceProgram = {
  business_type: string;
  business_label: string;
  acknowledged: { label: string; value: string; source: "stated" | "derived" | "default" }[];
  size: {
    target_sqft: number;
    min_sqft: number;
    max_sqft: number;
    basis: string[];
    concept?: string | null; // e.g. coffee_shop, full_service, yoga_studio
    concept_label?: string;
    components?: { label: string; sqft: number }[];
    source?: "stated" | "derived" | "default";
  };
  occupancy: { counts: Record<string, number>; group: string; group_label: string; occupant_load: number; area_based_load: number; people_stated: number; basis: string[] };
  code: { id: string; rule: string; value: string; detail: string; citation: string | null }[];
  building: { suitable_types: string[]; acceptable_types: string[]; ground_floor: "required" | "preferred" | "any"; min_ceiling_ft: number; ceiling_reason: string; buildout_months: [number, number] };
  needs: (Need & { owner: AgentName; check: string | null; triggers: string })[];
  timeline: { open_within_months: number; buildout_months: [number, number]; status: "ok" | "tight" | "risk"; detail: string } | null;
  tenure: "lease" | "buy";
  near: string[];
  avoid: string[];
  disclaimer: string;
};

/** A building compared with the program (size, ground floor, ceiling, paving for parking/drive-thru...). */
export type SiteCheck = { id: string; label: string; status: CheckStatus; detail: string };

export type Candidate = {
  id: string;
  lat: number;
  lon: number;
  footprint: GeoJSONGeometry | null; // building outline, [lon, lat]
  parcel: GeoJSONGeometry | null;
  building_type: string | null; // Vexcel building-type.class, e.g. "commercial"
  area_sqft: number | null; // BUILDING FOOTPRINT (outline from above, ~one floor): not the lot, not a leasable suite
  floor_area_est_sqft?: number | null; // footprint × estimated stories
  parcel_sqft?: number | null; // the property: lot/parcel area
  roof_condition: number | null; // 1 Bad .. 5 Great
  roof_condition_label: string | null;
  stories_est: number | null;
  match_score: number; // 0-100, deterministic pre-screen (NOT the agent analysis)
  match_reasons: string[];
  distance_m?: number | null; // from the searched place
  source: "vexcel" | "osm" | "demo" | "costar";
  address: string | null;
  // CoStar (sponsor kit): leasing figures the aerial data can't measure
  costar_id?: number | null;
  building_name?: string | null;
  rentable_sqft?: number | null; // Rentable Building Area (RBA; GLA for retail) of the whole building
  rentable_basis?: "RBA" | "GLA" | null;
  available_sqft?: number | null; // spaces on the market (not lease-pending)
  space_count?: number;
  best_space?: CostarSpace | null; // listed suite closest to the user's size
  closest_space_sqft?: number | null; // no suite in range: the listed space nearest the user's size
  asking_rent_per_sqft_yr?: [number, number] | null;
  /** Similarity to the user's visual needs in Vexcel imagery (pct = rank within this search, 0-100). */
  visual_matches?: { need: string; pct: number }[];
};

export type CostarSpace = {
  listing_id?: number | string;
  suite: string | null;
  floor: string | null;
  sqft: number | null;
  sqft_max?: number | null;
  suggested_portion?: boolean;
  sqft_min?: number | null; // divisible listing: smallest part offered
  rent_per_sqft_yr: number | null; // asking, normalised to $/sq ft/yr
  service: string | null; // TripleNet, FullService, ...
  use: string | null;
  available_on: string | null;
  lease_pending?: boolean;
};

export type CostarSummary = {
  costar_id: number;
  name: string | null;
  address: string | null;
  type: string | null;
  match: string;
  rentable_sqft: number | null;
  rentable_basis: "RBA" | "GLA" | null;
  gross_sqft: number | null;
  typical_floor_sqft: number | null;
  stories: number | null;
  lot_sqft: number | null;
  parking_ratio: number | null;
  spaces: CostarSpace[];
  space_count: number;
  available_sqft: number | null;
  asking_rent_per_sqft_yr: [number, number] | null;
  matterport_models: string[];
  note: string;
};

export type SearchResponse = {
  intent: Intent;
  location: { name: string; lat: number; lon: number; coverage: boolean } | null;
  data_mode: "vexcel_live" | "vexcel_demo" | "osm_only";
  candidates: Candidate[];
  notes: string[]; // human-readable caveats ("Outside Vexcel coverage: footprints from OpenStreetMap")
  program: SpaceProgram | null; // what the request implies (shown before any building is chosen)
  search_id?: string | null; // groups analyses of buildings from this search (Compare)
  query?: string; // client-side: the exact text that produced this result (sent with Analyze)
};

/** One turn of the refine-as-you-go conversation on the discovery page. */
export type ChatTurn = {
  role: "user" | "agent";
  text: string;
  changes?: string[];
  failed?: boolean;
  interaction?: MapInteraction;
  places?: Place[]; // result cards for map answers
  suggestions?: string[]; // follow-up questions the user can tap
};

/** How a map question was handled; each type has one predictable response (backend services/discovery_chat). */
export type MapInteraction =
  | "find_nearby" | "find_nearest" | "find_by_description" | "explore_surroundings"
  | "inspect" | "adjust_results" | "control_view" | "back";

/** What "it", "there" and "around here" refer to in a follow-up: a clicked/found place. */
export type MapAnchor = { kind: "place" | "area" | "view"; id?: string | null; label: string; lat: number; lon: number };

/** The map's conversational state sent with every follow-up. */
export type MapContext = {
  anchor?: MapAnchor | null;
  radius_m?: number | null;
  interaction?: MapInteraction | null;
  places?: Pick<Place, "id" | "name" | "group" | "category" | "lat" | "lon">[];
};

/** POST /api/search/refine: a follow-up either changes the search (re-run, new results) or is answered. */
export type MapAction = {
  kind: "places" | "areas" | "focus" | "zoom" | "layer" | "tilt" | "fit" | "clear" | "back" | "radius";
  interaction?: MapInteraction | null;
  anchor?: MapAnchor | null;
  radius_m?: number | null;
  suggestions?: string[];
  summary?: { group: string; label: string; count: number }[];
  places?: Place[];
  groups?: string[];
  areas?: GeoJSON.FeatureCollection;
  focus?: { lat: number; lon: number };
  zoom_delta?: number;
  layer?: "aerial" | "map";
  tilt?: boolean;
};

export type RefineResponse = {
  action: "refine" | "answer" | "map";
  map_action?: MapAction | null;
  reply: string;
  changes: string[]; // what changed in the search ("60 seats", "+ On-site parking (must)", "Budget $8,000 monthly")
  result: SearchResponse | null; // new results when action === "refine"
};

export type KeyFact = { group: string; label: string; value: string; note?: string | null };

/** One property-panel tile: a known fact, best first (backend services/building_facts.highlights). */
export type Highlight = {
  id: string;
  label: string;
  value: string;
  hint: string;
  source: string; // "CoStar", "CoStar listing", "Vexcel"...
  icon: string; // space | rent | building | year | parking | floors | roof | fan
  missing: boolean; // true: `value` says why it's unknown ("Not listed", "Unknown")
  sub?: string | null; // small context line under the headline ("Suite 170", "of ~1,400 sq ft", "no aerial data")
  status?: "good" | "warn" | "bad" | "unknown"; // set when the tile judges this building against the user's request
};

export type PropertyDetail = Candidate & {
  key_facts: KeyFact[]; // the most useful fields, readable
  highlights?: Highlight[]; // the same 9 panel tiles for every building: what it offers the user's request (or its recorded facts)
  raw: Record<string, unknown> | null; // complete Vexcel GeoJSON feature
  imagery: { collection: string | null; date: string | null; gsd_m: number | null } | null;
  matterport?: MatterportLink | null; // linked 3D tour (null when none)
  costar?: CostarSummary | null; // matched CoStar property: rentable area, spaces on the market, asking rents
  matterport_tours?: BuildingTours | null; // every 3D tour of the building, labelled against the suite for lease
};

/** One 3D tour of the building (fetched live from the Matterport API). */
export type BuildingTour = {
  id: string;
  name: string;
  kind: "suite" | "floor" | "common area" | "apartment" | "building";
  suites: string[];
  floor: number | null;
  captured: string | null;
  area_sqft: number | null;
  chips: string[]; // "Suite 1080", "floor 10", "2021", "not your suite"
  embed_url: string;
  linked: boolean;
};

export type BuildingTours = {
  tours: BuildingTour[];
  match: { id: string; confidence: "strong" | "possible"; signals: string[]; caveats: string[] } | null;
  suite: string | null; // the listed suite the user would lease
  note: string; // "No 3D tour of Suite 170; 2 tours of other parts of the building"
};

/** A Matterport tour linked to a building. The tour always embeds; interior data depends on `data`. */
export type MatterportLink = {
  model_id: string;
  embed_url: string; // public showcase iframe URL
  data: "live" | "recorded" | "embed_only"; // Model API / recorded scan / tour only (no API credentials)
  note: string;
  scan?: { name: string | null; floors: number; rooms: number; total_indoor_area_sqft: number | null; insights_available: boolean } | null;
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

/** quick = agents start from pre-gathered evidence with fewer LLM calls; deep = full investigation. */
export type AnalysisMode = "quick" | "deep";

export type AnalysisRequest = {
  selection?: Record<string, unknown> | null;
  conversation_history?: ChatTurn[];
  query: string;
  intent: Intent;
  property_id: string;
  radius_m: number;
  requirements?: string; // free-text extra requirements from the user
  mode?: AnalysisMode; // default "deep"
  search_id?: string | null; // the search this building came from
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
  /** Every stated budget checked (same shape as `budget`), e.g. monthly AND upfront. */
  budgets?: NonNullable<Costs["budget"]>[];
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
  /** Each need the user stated (search prompt + extra requirements), judged against the evidence. */
  requirement_checks?: { requirement: string; status: "met" | "unmet" | "unknown"; rationale: string; evidence_ids: string[] }[];
  mode?: AnalysisMode;
  data_sources: { name: string; status: "used" | "unavailable" | "demo"; note: string }[];
  program?: SpaceProgram; // absent on analyses run before the space program existed
  site_checks?: SiteCheck[];
};

export type Analysis = {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  created_at: string;
  query: string;
  intent: Intent;
  property: PropertyDetail;
  radius_m: number;
  mode?: AnalysisMode; // absent on analyses made before modes existed (= deep)
  search_id?: string; // group key: the search it came from (older analyses: grouped by request + business)
  base_query?: string; // the search prompt alone (query = prompt + extra requirements)
  extra_requirements?: string | null;
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
  mode?: AnalysisMode;
  search_id?: string;
  base_query?: string;
  extra_requirements?: string | null;
  business_type?: string;
  budget_status?: "within" | "partly" | "over" | null;
};

/** GET /api/searches/{id}: one search, its ranked candidates and the analyses run on them. */
export type SearchGroup = {
  id: string;
  query: string;
  intent: Intent;
  location: SearchResponse["location"];
  legacy: boolean; // made before search ids existed: only analyzed buildings are known
  candidates: Pick<Candidate, "id" | "lat" | "lon" | "building_type" | "area_sqft" | "roof_condition" | "roof_condition_label" | "stories_est" | "match_score" | "match_reasons" | "address" | "source">[];
  analyses: AnalysisSummary[];
};
