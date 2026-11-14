// TypeScript mirror of docs/API_CONTRACT.md (v1). Keep in sync with backend/app/models/.
// If a shape changes in the contract, change it here and in the backend together.

export type Status = "PASS" | "RISK" | "UNKNOWN";

/** USD (or month) range; the cost engine always returns ranges, never point estimates. */
export interface CostRange {
  min: number;
  max: number;
}

export type ProviderMode = "mock" | "live";
/** Open-ended so a future parser still renders (as its raw name). */
export type ParserMode = "regex" | "ollama" | "claude" | (string & {});

export interface HealthResponse {
  status: "ok";
  mode: {
    costar: ProviderMode;
    matterport: ProviderMode;
    vexcel: ProviderMode;
    /** Parser that is *configured* (an analysis's mode.parser is the one actually used). */
    parser: ParserMode;
    /** Summary LLM, e.g. "ollama:qwen3:8b", "anthropic:claude-haiku-5-5" or "none". Absent on older backends. */
    llm?: string;
  };
}

export interface BusinessType {
  id: string;
  label: string;
  capacity_unit: string;
  default_capacity: number;
  needs_kitchen: boolean;
}

export type MissingDataPolicy = "assume_risk" | "assume_cost" | "unknown" | "ignore";

export interface Criterion {
  id: string;
  description: string;
  domain: string;
  weight: number;
  hard_block: boolean;
  evaluator: string;
  required_inputs: string[];
  missing_data_policy: MissingDataPolicy;
  evidence_required: boolean;
  source: string;
  thresholds: Record<string, unknown>;
  business_types: string[];
  applicable_jurisdictions: string[];
}

export interface Property {
  id: string;
  address: string;
  city: string;
  state: string;
  zip: string;
  size_sqft: number;
  /** Monthly rent in USD. */
  rent: number;
  zoning: string | null;
  previous_use: string | null;
  ti_allowance_per_sqft: number | null;
  latitude: number | null;
  longitude: number | null;
  image_url: string | null;
  matterport_url: string | null;
  available: boolean;
  /**
   * Where the listing came from: "costar" (live API) or "sample" (real building, but rent, size and
   * previous use are illustrative until CoStar listings are connected). Optional: older backends omit it.
   */
  listing_source?: string | null;
  /**
   * Recorded use-restriction tags disclosed with the listing (e.g. "no_food_service").
   * null/absent = listing says nothing; [] = listing discloses none.
   */
  use_restrictions?: string[] | null;
}

export interface BusinessProfile {
  type: string;
  details: string;
  city: string;
  state: string;
}

export interface AnalyzeRequest {
  business_profile: BusinessProfile;
  property_ids: string[];
}

export type ParkingSource = "user" | "guideline" | "jurisdiction" | (string & {});

export interface Requirements {
  business_type: string;
  business_label: string;
  city: string;
  state: string;
  capacity: number;
  capacity_unit: string;
  occupant_load: number;
  parking_required: number;
  /** "jurisdiction" = parking minimum from the city's code; open-ended so new sources still render. */
  parking_source: ParkingSource;
  bathrooms_required: number;
  min_sqft: number | null;
  max_sqft: number | null;
  max_rent: number | null;
  needs_kitchen: boolean;
  required_hvac_tons: number;
  required_electrical_amps: number;
  assumptions: string[];
}

export type EvidenceSource = "costar" | "matterport" | "vexcel" | "requirements" | "jurisdiction";

/** Normalized [x, y, w, h] in 0..1, relative to the source image. */
export type OverlayBox = [number, number, number, number];

export interface Evidence {
  key: string;
  value: unknown;
  source: EvidenceSource;
  note: string | null;
  confidence: number | null;
  box: OverlayBox | null;
  /** True when the fact came from a live provider call (e.g. Vexcel property/extract). Absent on older runs. */
  live?: boolean;
}

export interface CriterionResult {
  id: string;
  description: string;
  domain: string;
  weight: number;
  status: Status;
  /** 0..1, null when excluded from the score. */
  score: number | null;
  counted: boolean;
  hard_block: boolean;
  blocking: boolean;
  notes: string;
  source: string;
  evidence: Evidence[];
}

export interface LineItem {
  item: string;
  label: string;
  qty: number;
  min: number;
  max: number;
  reason: string;
}

export interface ComplianceEntry {
  status: Status;
  notes: string;
  source: string;
}

export type AerialSource = "vexcel-live" | "placeholder";

// The Vexcel fields are optional so stored runs from before live imagery still render.
export interface ResultMedia {
  /** Top-down ortho; live Vexcel imagery is cached by the backend under /static/vexcel-cache/. */
  aerial_url: string | null;
  /** Angled Vexcel photo of the building; null when unavailable / mock. */
  oblique_url?: string | null;
  floor_plan_url: string | null;
  matterport_embed_url: string | null;
  image_url: string | null;
  /** Drives the "Live · Vexcel" badge; absent (older runs) is treated as placeholder. */
  aerial_source?: AerialSource;
  /** Must be shown under live imagery, e.g. "© Vexcel Imaging US, Inc.". */
  aerial_attribution?: string | null;
}

export interface AnalysisResult {
  property_id: string;
  address: string;
  rank: number;
  /** Criteria fit, 0-100. */
  score: number;
  disqualified: boolean;
  /** Criterion ids that hard-blocked this property. */
  disqualifiers: string[];
  /** Not disqualified but score < AnalyzeResponse.min_score; ranked after qualifying results. Absent on older runs. */
  weak_fit?: boolean;
  monthly_rent: number;
  /** Cost to open: net fit-out + rent during build-out. */
  total_cost_estimate: CostRange;
  /** Cost to open + rent for the ranking horizon. */
  first_year_cost: CostRange;
  /** Gross fit-out before TI allowance. */
  fit_out_estimate: CostRange;
  ti_allowance: number;
  buildout_months: CostRange;
  breakdown: Record<string, CostRange>;
  line_items: LineItem[];
  compliance: Record<string, ComplianceEntry>;
  criteria_results: CriterionResult[];
  questions_for_landlord: string[];
  landlord_request: string;
  observations: Record<string, Evidence>;
  media: ResultMedia;
  assumptions: string[];
}

export interface AnalysisMode {
  costar: string;
  matterport: string;
  vexcel: string;
  /** Parser actually used for this run ("regex" when an LLM call failed and fell back). */
  parser: ParserMode;
  /** Summary LLM used for this run, or "none". Absent on older runs. */
  llm?: string;
}

/**
 * Plain-English explanation of the ranking, written by an LLM from the response's own numbers and
 * statuses. It never changes costs, scores or compliance (those stay rule-based).
 */
export interface AiSummary {
  /** 2-4 sentences about the ranking as a whole. */
  text: string;
  /** property_id -> one sentence "why this rank". May omit properties. */
  per_property: Record<string, string>;
  /** e.g. "ollama:qwen3:8b". */
  model: string;
  grounded: true;
}

export interface AnalyzeResponse {
  analysis_id: string;
  created_at: string;
  business_type: string;
  requirements: Requirements;
  ranking_basis: string;
  /** Fit-score threshold (costs.yaml ranking.min_score) for weak fits; 0 = gate off. Absent on older runs. */
  min_score?: number;
  /** Already sorted by rank (1 = best). */
  results: AnalysisResult[];
  mode: AnalysisMode;
  disclaimer: string;
  /** null when no LLM was reachable or the call failed; absent on older runs. The UI hides the panel either way. */
  ai_summary?: AiSummary | null;
}

export interface AnalysisSummary {
  analysis_id: string;
  created_at: string;
  business_type: string;
  business_label: string;
  city: string;
  state: string;
  property_count: number;
  top_property_id: string | null;
  top_address: string | null;
}
