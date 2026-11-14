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
{ status: "ok"; mode: { costar: "mock" | "live"; matterport: "mock" | "live"; vexcel: "mock" | "live"; parser: "regex" | "ollama" | "claude"; llm: string /* e.g. "ollama:qwen3:8b", "anthropic:claude-haiku-5-5", "none" */ } }
```

`mode.parser` here is the parser that is *configured* ("claude" when `ANTHROPIC_API_KEY` is set).
An analysis response's `mode.parser` is the parser that was *actually used* for that run, so it reads
"regex" if the Claude call failed and fell back.

### GET /api/v1/business-types

Business types from `backend/config/business_types.yaml`, for the profile form's select.

```ts
Array<{ id: string; label: string; capacity_unit: string; default_capacity: number; needs_kitchen: boolean }>
// e.g. { id: "restaurant", label: "Restaurant", capacity_unit: "seats", default_capacity: 40, needs_kitchen: true }
```

### GET /api/v1/criteria?business_type=restaurant&city=Austin&state=TX

The criteria registry (`backend/criteria.yaml`). All query params are optional; when given, only
criteria applicable to that business type / jurisdiction are returned. The UI renders whatever it
gets — it never hard-codes criterion ids. Unknown `business_type` → 400; a malformed
`criteria.yaml` → 500 with a message naming the bad entry.

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
  use_restrictions: string[] | null;  // recorded deed / lease use-restriction tags, e.g. ["no_food_service"]; null = listing says nothing, [] = none disclosed
  listing_source: string | null;      // "costar" (live API) or "sample" (hand-made demo listing at a real address; rent/size/TI illustrative)
}>
```

### POST /api/v1/analyze

Runs the full agent pipeline (parse requirements → fetch property → vision observations →
compliance/criteria evaluation (which emits the needed cost items) → cost engine → scoring →
ranking), **stores the run in SQLite**, and returns it.

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
  ranking_basis: string;        // human sentence, e.g. "Ranked by first-year cost (cost to open + 12 months rent) among properties with a fit score of at least 55; weak fits (score below 55) next, then disqualified properties; ties broken by criteria score."
  min_score: number;            // costs.yaml ranking.min_score; non-disqualified results scoring below it are weak fits (0 = gate off / older runs)
  results: AnalysisResult[];    // already sorted by rank (1 = best)
  mode: { costar: string; matterport: string; vexcel: string; parser: "regex" | "ollama" | "claude"; llm: string };
  disclaimer: string;
  ai_summary: {                  // null when no LLM is reachable or the call failed (UI hides the panel)
    text: string;                // 2-4 sentence plain-English explanation of the ranking
    per_property: Record<string, string>;  // property_id -> one sentence "why this rank"
    model: string;               // e.g. "ollama:qwen3:8b"
    grounded: true;              // generated only from this response's numbers/statuses; never changes them
  } | null;
}

Requirements = {
  business_type: string; business_label: string; city: string; state: string;
  capacity: number; capacity_unit: string; occupant_load: number;
  parking_required: number;
  parking_source: "user" | "guideline" | "jurisdiction";  // jurisdiction = city code minimum (jurisdictions.yaml parking_ratios)
  bathrooms_required: number;
  min_sqft: number | null; max_sqft: number | null; max_rent: number | null;
  needs_kitchen: boolean; required_hvac_tons: number; required_electrical_amps: number;
  assumptions: string[];
}

AnalysisResult = {
  property_id: string; address: string; rank: number;
  listing_source: string | null;     // Property.listing_source ("sample" drives the "Sample listing" badge); null in older stored runs
  use_restrictions: string[] | null; // Property.use_restrictions; null when not stated / older stored runs
  score: number;                     // criteria fit 0-100
  disqualified: boolean; disqualifiers: string[];   // criterion ids that hard-blocked
  weak_fit: boolean;                 // not disqualified but score < min_score; ranked after qualifying results, before disqualified
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
  media: {
    aerial_url: string | null;          // top-down ortho; live Vexcel image is cached by the backend and served from /static/vexcel-cache/...
    oblique_url: string | null;         // angled Vexcel photo of the building (null when unavailable / mock)
    floor_plan_url: string | null; matterport_embed_url: string | null; image_url: string | null;
    aerial_source: "vexcel-live" | "placeholder";   // drives the "Live · Vexcel" badge and attribution line
    aerial_attribution: string | null;  // e.g. "© Vexcel Imaging US, Inc." — must be shown under live imagery
  };
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
  live: boolean;                     // true when the fact came from a live provider call (e.g. Vexcel property/extract), false for fixtures/derived
}
```

Overlay rule for the UI: evidence with `source: "vexcel"` and a `box` is drawn on `media.aerial_url`;
`source: "matterport"` with a `box` is drawn on `media.floor_plan_url`. Boxes of live Vexcel facts and of
fixture facts snapshotted from live Vexcel (note starts "Snapshot of Vexcel property/extract") are
positioned on the live 800×800 ortho, so the backend sends them with `box: null` when
`media.aerial_source == "placeholder"`; hand-made fixture boxes drawn for the placeholder SVGs are kept.

Vexcel facts (live mode, from `/property/extract`; mock mode replays a snapshot of them for the Houston
listings): `rooftop_hvac_units` and `hvac_tons` (units × tons per unit) — both **whole building**,
`paved_area_sqft`, `estimated_parking_spaces`, `vehicles_count`, `roof_condition` (1–5, 5 = best),
`roof_material`, `roof_defects`, `building_footprint_sqft`, `building_type`. A `building_footprint`
evidence item carries the footprint's `box` on the aerial image. The Vexcel API key never reaches the
browser: the backend downloads imagery and serves it from `/static`.

Parking estimate rule: `paved_area_sqft` is parcel-level paving (excludes shared lots and street parking).
`estimated_parking_spaces` = floor(paved ÷ `sqft_per_space`, the `parking_sufficiency` threshold, 350) and
is **omitted** when paving is under one space, so it never reads as "0 spaces"; parking is then UNKNOWN
unless a `visible_parking_count` exists. `vehicles_count` appears in parking evidence as context only,
never as a space count.

Evidence keys added by evaluators (in `CriterionResult.evidence`):

| key | source | criterion | meaning |
|---|---|---|---|
| `use_restrictions` | costar | zoning_use | restriction tags disclosed in the listing (`[]` = none disclosed) |
| `zoning_mode` | jurisdiction | zoning_use | `"no zoning"` for a no-zoning city (e.g. Houston); note = the city's zoning note |
| `use_restriction_rule` | jurisdiction | zoning_use | e.g. `"no_food_service: prohibits restaurant"` when a restriction blocks the use |
| `zoning_rule` | jurisdiction | zoning_use | e.g. `"CS: permitted"` from the city's use table |
| `business_required_parking` | requirements | parking_sufficiency | spaces this property must provide; note says why (user / city code / guideline) |
| `code_required_parking` | jurisdiction | parking_sufficiency | city minimum for this property's size; note shows the math and citation (only where a minimum applies) |
| `parking_rule` | jurisdiction | parking_sufficiency | the city's parking rule, e.g. `"10 per 1,000 sq ft GFA"`, `"no minimum (East Downtown (EaDo) market-based parking area)"`, `"no parking minimum"` (Austin); note = citation |
| `hvac_tons_suite_share` | vexcel | hvac_capacity | building tons × min(1, `size_sqft` ÷ `building_footprint_sqft`) when the footprint is known and larger than the listing and `hvac_capacity.thresholds.prorate_by_footprint` is true; the criterion is evaluated against this value |

HVAC verify rule (`hvac_capacity`): when the capacity is a prorated `hvac_tons_suite_share` and it is below
the need, the result is `status: "UNKNOWN"` with `counted: false` / `score: null` (excluded from the fit
score, like `missing_data_policy: unknown`), no `hvac_rtu` line item, and the landlord question "Which
rooftop HVAC units serve this suite, and what is their tonnage and age?". Notes read "Building has N
rooftop units (≈X tons total); your prorated share ≈Y tons vs Z needed — ask the landlord which units
serve your suite." It stays `RISK` (scored 0, with `hvac_rtu` units priced) when the building has zero
detected rooftop units or when direct (non-prorated) tonnage is short.

The `parking_sufficiency` result's `source` is the jurisdiction's parking citation (e.g. Houston Code
Ch. 26 §26-492, §26-471 in a market-based area, Austin's parking note); its `required_inputs` stay
`["business_required_parking"]`, computed per property (city minimum for the property's size and
location, never below a user-stated number).

### GET /api/v1/analyses?limit=20

Recent stored runs, newest first. `limit` is 1–100 (default 20); outside that range → 422.

```ts
Array<{
  analysis_id: string; created_at: string; business_type: string; business_label: string;
  city: string; state: string; property_count: number;
  top_property_id: string | null; top_address: string | null;
}>
```

### GET /api/v1/analyses/{analysis_id}

Returns the stored `AnalyzeResponse` as `POST /api/v1/analyze` returned it, re-validated against the
current model: runs stored before a field existed get its default (e.g. `min_score: 0`,
`weak_fit: false`); a run that no longer validates is returned as the raw stored JSON. Unknown id → 404.
The frontend's shareable report URL is `/analysis/{analysis_id}`.
