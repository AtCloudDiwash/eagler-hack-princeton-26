# Integrations

Three data providers live in `backend/app/providers/`. **Mock mode is the default**
(`USE_MOCK_DATA=true`). A provider goes live only when `USE_MOCK_DATA=false` **and** its key is set
(`settings.provider_mode(key)`). Any live failure (network, auth, timeout, unexpected shape) is logged
and **falls back to the fixtures**, so the demo cannot break on an integration. `GET /health` and
`AnalyzeResponse.mode` report each provider's mode.

Placeholder keys from `.env.example` (anything starting with `your_`) count as unset.

## CoStar: listings (`costar_provider.py`)

| | Mock | Live |
|---|---|---|
| Data | `backend/fixtures/properties.json` (4 Austin, TX listings) | `GET {COSTAR_API_BASE_URL}/listings?propertyType=retail&listingType=lease` with `Authorization: Bearer {COSTAR_API_KEY}` |
| Mapping | Direct (`Property(**row)`) | `map_costar_listing` tolerates CoStar-style names (`listingId`, `address.streetAddress`, `availableSpaceSf`, `monthlyRent`, `zoningCode`, `tiAllowancePerSf`, `primaryPhotoUrl`, `virtualTourUrl`, ...) |
| Env | none | `COSTAR_API_KEY`, `COSTAR_API_BASE_URL` (placeholder `https://api.costar.example/v1`; replace with the path from your CoStar developer docs), `PROVIDER_TIMEOUT_SECONDS` |

`search_properties(city, state, min_size, max_size, max_rent)` filters in Python: `city` matches the
city name or the ZIP, and unavailable listings are skipped. `get_property(id)` backs `/analyze`.

Fixture listings:

| id | Address | Sq ft | Rent | Zoning | Previous use | TI/sq ft |
|---|---|---|---|---|---|---|
| property-123 | 123 Elm Street | 2,000 | $4,000 | CS-MU | Retail boutique | $10 |
| property-456 | 456 Oak Avenue | 1,800 | $4,800 | GR | Second-generation restaurant | $0 |
| property-789 | 789 Congress Avenue, Suite 110 | 2,200 | $3,600 | LO | Professional office | $15 |
| property-321 | 2100 E Cesar Chavez Street | 1,600 | $4,200 | LR-V | Coffee shop | $5 |

## Matterport: interior (`matterport_provider.py`)

| | Mock | Live |
|---|---|---|
| Floor plan | `observations.json` → `floor_plan_url` (SVG in `backend/static/floorplans/`) | GraphQL `POST {MATTERPORT_API_BASE_URL}` `model(id){assets{floorplans{url}}}` with basic auth (`MATTERPORT_API_KEY`). Model id is parsed from `matterport_url` (`...?m=<id>`) |
| Interior facts | `observations.json` → `interior` block | **Still from fixtures** (automated door/fixture detection is out of scope) |
| 3D tour | `matterport_embed_url` = listing `matterport_url` (null in fixtures, so the UI shows a "no tour" note) | same |
| Env | none | `MATTERPORT_API_KEY`, `MATTERPORT_API_BASE_URL` (default `https://api.matterport.com/api/models/graph`) |

Functions: `get_interior(prop)`, `get_interior_images(property_id, matterport_url)`.

## Vexcel: aerial (`vexcel_provider.py`)

| | Mock | Live |
|---|---|---|
| Aerial image | `observations.json` → `aerial_url` (SVG in `backend/static/aerials/`) | `GET {VEXCEL_API_BASE_URL}/images/ortho?lat&lon&zoom=20&format=json` with a Bearer key; uses the returned `url`. Needs listing lat/lng |
| Aerial facts | `observations.json` → `aerial` block (`visible_parking_count`, `hvac_tons`, with boxes) | **Still from fixtures** |
| Env | none | `VEXCEL_API_KEY`, `VEXCEL_API_BASE_URL` (placeholder `https://api.vexcel.example/v1`) |

Functions: `get_aerial(prop)`, `get_aerial_image(prop)`.

## Fixture format (`backend/fixtures/observations.json`)

```json
"property-123": {
  "floor_plan_url": "/static/floorplans/property-123.svg",
  "aerial_url": "/static/aerials/property-123.svg",
  "interior": { "door_width_inches": { "value": 34, "confidence": 0.85, "note": "...", "box": [0.08, 0.72, 0.06, 0.1] } },
  "aerial":   { "visible_parking_count": { "value": 15, "confidence": 0.8, "note": "...", "box": [0.05, 0.6, 0.55, 0.3] } }
}
```

A fact that is absent is unknown, which is how the missing-data policies get exercised (e.g.
property-321 has no door width, property-789 no grease interceptor fact).

## Anthropic Claude (optional, requirements parser)

If `ANTHROPIC_API_KEY` is set, `requirements_parser.claude_extract` calls the Messages API
(`ANTHROPIC_MODEL`, default `claude-haiku-5-5`) with a JSON-schema output format, an 8 s timeout and
no retries. Validated fields are merged over the regex result. Any failure falls back to regex. This
is independent of `USE_MOCK_DATA`. `/health` reports `parser: "claude"` when a key is configured, and
`AnalyzeResponse.mode.parser` reports the parser actually used for that run.

## Geocoding (not implemented)

`GEOCODING_API_KEY` is read into settings but nothing uses it: the fixture listings already include
latitude/longitude, which is all Vexcel needs. A future `geocode(address)` would fill lat/lng for live
listings that lack them.

## Switching to live

```bash
# backend/.env
USE_MOCK_DATA=false
COSTAR_API_KEY=...            # only the providers with keys go live
COSTAR_API_BASE_URL=https://<real-host>/<path>
```

Restart uvicorn (env is read at startup), then check `curl localhost:8000/health`. Endpoint paths and
field names for CoStar and Vexcel are placeholders until confirmed against sponsor docs. The mapping
functions are the only code to adjust.
