# API Contract (v1)

This is the single source of truth shared by the backend (`backend/app/models/`) and the frontend
(`frontend/lib/types.ts`). If you change a shape here, change both sides.

## Base URL and transport

- Backend: `http://localhost:8000`. All business endpoints are prefixed with `/api/v1`.
- Frontend calls **relative** URLs (`/api/v1/...`, `/static/...`); `frontend/next.config.ts` rewrites
  them to the backend (`API_ORIGIN`, default `http://localhost:8000`). CORS is also enabled for
  `CORS_ORIGINS` so the API can be called directly.
- Errors use FastAPI's shape: `{"detail": "<message>"}` (422 for validation, 400 for bad input,
  404 for unknown ids).
- Static media (placeholder aerials, floor plans, listing photos) is served by the backend under
  `/static/...`.

Types below use TypeScript notation. `Status = "PASS" | "RISK" | "UNKNOWN"`.
`CostRange = { min: number; max: number }` (USD).

---

### GET /health

```ts
{ status: "ok"; mode: { costar: "mock" | "live"; matterport: "mock" | "live"; vexcel: "mock" | "live"; parser: "regex" | "claude" } }
```

### GET /api/v1/business-types

Business types from `backend/config/business_types.yaml`, for the profile form's select.

```ts
Array<{ id: string; label: string; capacity_unit: string; default_capacity: number; needs_kitchen: boolean }>
// e.g. { id: "restaurant", label: "Restaurant", capacity_unit: "seats", default_capacity: 40, needs_kitchen: true }
```

### GET /api/v1/criteria?business_type=restaurant&city=Austin&state=TX

The criteria registry (`backend/criteria.yaml`). All query params are optional; when given, only
criteria applicable to that business type / jurisdiction are returned. The UI renders whatever it
gets — it never hard-codes criterion ids.

```ts
Array<{
  id: string; description: string; domain: string; weight: number; hard_block: boolean;
  evaluator: string; required_inputs: string[];
  missing_data_policy: "assume_risk" | "assume_cost" | "unknown" | "ignore";
  evidence_required: boolean; source: string; thresholds: Record<string, unknown>;
  business_types: string[]; applicable_jurisdictions: string[];
}>
```

### GET /api/v1/properties

Query params (all optional): `business_type`, `city` (name or ZIP), `state`, `min_size`, `max_size`
(sq ft), `budget` (max monthly rent). Unknown `business_type` → 400.

```ts
Array<{
  id: string; address: string; city: string; state: string; zip: string;
  size_sqft: number; rent: number /* monthly USD */;
  zoning: string | null; previous_use: string | null; ti_allowance_per_sqft: number | null;
  latitude: number | null; longitude: number | null;
  image_url: string | null /* e.g. "/static/properties/property-123.svg" */;
  matterport_url: string | null; available: boolean;
}>
```

### POST /api/v1/analyze

Runs the full agent pipeline (parse requirements → fetch property → vision observations → cost
engine → compliance/criteria evaluation → ranking), **stores the run in SQLite**, and returns it.

Request:

```json
{
  "business_profile": {
    "type": "restaurant",
    "details": "40 seats, kitchen needed, 2 bathrooms, 20 parking spaces",
    "city": "Austin",
    "state": "TX"
  },
  "property_ids": ["property-123", "property-456"]
}
```

Errors: empty `property_ids` → 422; unknown business type → 400; unknown property id → 404.

Response (`AnalyzeResponse`):

```ts
{
  analysis_id: string;          // uuid4 hex, use with GET /api/v1/analyses/{id}
  created_at: string;           // ISO-8601 UTC
  business_type: string;
  requirements: Requirements;
  ranking_basis: string;        // human sentence, e.g. "Ranked by first-year cost (cost to open + 12 months rent); disqualified properties last."
  results: AnalysisResult[];    // already sorted by rank (1 = best)
  mode: { costar: string; matterport: string; vexcel: string; parser: "regex" | "claude" };
  disclaimer: string;
}

Requirements = {
  business_type: string; business_label: string; city: string; state: string;
  capacity: number; capacity_unit: string; occupant_load: number;
  parking_required: number; parking_source: "user" | "guideline";
  bathrooms_required: number;
  min_sqft: number | null; max_sqft: number | null; max_rent: number | null;
  needs_kitchen: boolean; required_hvac_tons: number; required_electrical_amps: number;
  assumptions: string[];
}

AnalysisResult = {
  property_id: string; address: string; rank: number;
  score: number;                     // criteria fit 0-100
  disqualified: boolean; disqualifiers: string[];   // criterion ids that hard-blocked
  monthly_rent: number;
  total_cost_estimate: CostRange;    // cost to open: net fit-out + rent during build-out
  first_year_cost: CostRange;        // cost to open + rent for ranking horizon
  fit_out_estimate: CostRange;       // gross fit-out before TI allowance
  ti_allowance: number;
  buildout_months: CostRange;
  breakdown: Record<string, CostRange>;          // keyed by cost item id / soft-cost id
  line_items: Array<{ item: string; label: string; qty: number; min: number; max: number; reason: string }>;
  compliance: Record<string, { status: Status; notes: string; source: string }>;  // keyed by criterion id
  criteria_results: CriterionResult[];
  questions_for_landlord: string[];
  landlord_request: string;          // drafted letter (plain text, newlines) asking for TI / fixes
  observations: Record<string, Evidence>;        // keyed by fact name, e.g. "door_width_inches"
  media: { aerial_url: string | null; floor_plan_url: string | null; matterport_embed_url: string | null; image_url: string | null };
  assumptions: string[];
}

CriterionResult = {
  id: string; description: string; domain: string; weight: number; status: Status;
  score: number | null;              // 0..1, null when excluded from the score
  counted: boolean; hard_block: boolean; blocking: boolean;
  notes: string; source: string; evidence: Evidence[];
}

Evidence = {
  key: string; value: unknown; source: "costar" | "matterport" | "vexcel" | "requirements" | "jurisdiction";
  note: string | null; confidence: number | null;
  box: [number, number, number, number] | null;  // normalized [x, y, w, h] overlay on the source image
}
```

Overlay rule for the UI: evidence with `source: "vexcel"` and a `box` is drawn on `media.aerial_url`;
`source: "matterport"` with a `box` is drawn on `media.floor_plan_url`.

### GET /api/v1/analyses?limit=20

Recent stored runs, newest first.

```ts
Array<{
  analysis_id: string; created_at: string; business_type: string; business_label: string;
  city: string; state: string; property_count: number;
  top_property_id: string | null; top_address: string | null;
}>
```

### GET /api/v1/analyses/{analysis_id}

Returns the stored `AnalyzeResponse` exactly as `POST /api/v1/analyze` returned it. Unknown id → 404.
The frontend's shareable report URL is `/analysis/{analysis_id}`.
