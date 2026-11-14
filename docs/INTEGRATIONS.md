# Integrations

Three data providers live in `backend/app/providers/`. **Mock mode is the default**
(`USE_MOCK_DATA=true`). A provider goes live only when `USE_MOCK_DATA=false` **and** its key is set
(`settings.provider_mode(key)`). Placeholder keys from `.env.example` (anything starting with `your_`)
count as unset. Any live failure is logged and **falls back to the fixtures**, so the demo cannot break
on an integration. `GET /health` and `AnalyzeResponse.mode` report each provider's mode.

| Provider | Status | What is live |
|---|---|---|
| **Vexcel** | **Real API, verified end to end** (sponsor key, geofenced to Los Angeles + Houston) | Top-down ortho, oblique (angled) photo, `/property/extract` AI facts |
| CoStar | Mock (adapter written against placeholder endpoints; no key yet) | Nothing yet |
| Matterport | Mock (floor-plan GraphQL adapter written; no key, no tour links yet) | Nothing yet |

Live mode for the demo is therefore `USE_MOCK_DATA=false` + `VEXCEL_API_KEY`: Vexcel goes live,
CoStar and Matterport stay mock, and `/health` reports `vexcel: "live"` (header pill "API · mixed data").

## Vexcel: aerial imagery + property intelligence (`vexcel_provider.py`)

### Endpoints (live)

Base URL `VEXCEL_API_BASE_URL` (default `https://api.vexcelgroup.com/v2`). The key travels **only** in
the `X-API-KEY` request header. Every request is centred on the listing's point
(`wkt=POINT(lon lat)`, `srid=4326`), so the listing needs latitude/longitude.

| Item | Request | Result |
|---|---|---|
| Ortho (top-down) | `GET /ortho/extract` `layer=urban`, `bbox-dimensions=100,100` (metres), `destination-dimensions=800,800`, `image-format=jpeg` | 800×800 JPEG covering 100 × 100 m, north up → `media.aerial_url` |
| Oblique (angled) | `GET /oriented/extract` `layer=urban`, `product-type=oblique-north`, `bbox-dimensions=100,100`, `image-format=jpeg` | North-facing angled JPEG → `media.oblique_url` (the "Angled" tab) |
| Property facts | `GET /property/extract` `unit-system=imperial`, `total-records=1` | GeoJSON; normalized into Evidence facts (below) |

`product-type` must be one of `oblique-north`, `oblique-south`, `oblique-east`, `oblique-west`. The
earlier value `oblique-n` is invalid and Vexcel silently returned a top-down (nadir) image instead of an
error (fixed in commit c3fedf3; the Houston cache was re-fetched).

The three calls run in parallel, each with `PROVIDER_TIMEOUT_SECONDS`. Responses are validated (an
image must be `image/*` or a JPEG; property data must have `features`).

### Geofence

The sponsor key only works for **Los Angeles and Houston**; elsewhere Vexcel answers 403. That is why
the demo city is Houston. Austin listings still work in live mode: their calls get 403 and fall back to
the fixture placeholders (the 403 is remembered, see below).

### Cache (`backend/static/vexcel-cache/<property_id>/`)

```
ortho.jpg  oblique.jpg  property.json  meta.json   # meta: latitude, longitude, fetched_at, errors
```

- The backend downloads once and serves the files from `/static/vexcel-cache/...`, so the **key never
  reaches the browser** and repeat analyses make **no calls**. A complete cache works with no network.
- The folder is **gitignored**: Vexcel imagery is licensed and must not be committed or redistributed.
- **Per-item fallback**: imagery can exist where property data 404s, and vice versa.
- **Permanent failures** (403 geofence, 404 no data, unusable content) are stored in `meta.json` and not
  retried. **Transient failures** (timeouts, 5xx, network) are remembered in memory for 10 minutes so a
  flaky API doesn't add a timeout to every analysis.
- If a listing's coordinates change, its cache is discarded and re-fetched.
- `get_aerial(prop, force_refresh=True)` (used by the snapshot script) re-requests everything.

### Facts (`normalize_property_extract`)

Facts are built from the primary structure of the first feature. A null/absent source field produces
no fact, so fixture facts can fill the gap. Live facts carry `live: true` and **win over fixture facts
of the same key**.

| Fact | From | Notes |
|---|---|---|
| `rooftop_hvac_units` | `roof-objects.ac-unit.count` | **Whole building** |
| `hvac_tons` | units × `tons_per_unit` (5, from `hvac_capacity.thresholds`) | Whole building; confidence = unit score × 0.75. The HVAC check prorates it to the suite |
| `paved_area_sqft` | `hardscapes.area` | **Parcel-level** paving; excludes shared lots and street parking |
| `estimated_parking_spaces` | floor(paved ÷ `sqft_per_space`, 350, from `parking_sufficiency.thresholds`) | **Omitted when paving is under one space** (no false zeros); confidence 0.4 |
| `vehicles_count` | `vehicles.count` | Context only, never a space count |
| `roof_condition` | `roof-characteristics.condition` | 1 (poor) to 5 (excellent); feeds `roof_condition` |
| `roof_material` | `roof-characteristics.material.class` | e.g. metal, membrane |
| `roof_defects` | `roof-defects.*.detected == true` | e.g. `["discoloration", "water-pooling"]`; tarp / structural damage are serious |
| `building_footprint_sqft` | `footprint.area` | Whole building; used to prorate HVAC |
| `building_footprint` | `footprint.wkt` | Carries the overlay `box` on the ortho ([VISION_OVERLAYS.md](VISION_OVERLAYS.md)) |
| `building_type` | `building-type.class` | e.g. commercial |

Each note ends with the imagery date, e.g. "(Vexcel imagery 2025-12-19)". The thresholds are read from
the criteria registry, so the normalization and the evaluators always agree.

### Mock mode and snapshots

In mock mode the `aerial` block of `backend/fixtures/observations.json` provides the facts and an SVG in
`backend/static/aerials/` is the image. For the five Houston listings that block is a **snapshot of the
real `/property/extract` responses** (notes start "Snapshot of Vexcel property/extract on 2026-11-14"),
so mock mode reproduces the live ranking exactly. `visible_parking_count` for Houston is hand-entered
(note "Placeholder: ..."), because Vexcel parcel paving was under one space for every listing.

`backend/scripts/snapshot_vexcel.py` (run from `backend/`):

```bash
venv/bin/python scripts/snapshot_vexcel.py                          # live: all fixture properties
venv/bin/python scripts/snapshot_vexcel.py --only property-hou-01   # selected ids
venv/bin/python scripts/snapshot_vexcel.py --dry-run                # print, don't write the fixture
venv/bin/python scripts/snapshot_vexcel.py --from-cache             # re-normalize the cache, no key/network
```

Live runs ignore `USE_MOCK_DATA`, force-refresh the cache (so they also pre-warm it), and merge facts
key by key into each property's `aerial` block, keeping hand-written facts and removing snapshot facts
the normalization no longer emits. Imagery is never copied into the fixtures. Properties outside the
geofence are skipped. `--from-cache` is for re-deriving facts after a normalization change.

Functions: `get_aerial(prop, force_refresh=False)` → `{aerial_url, oblique_url, aerial_source
("vexcel-live" | "placeholder"), aerial_attribution ("© Vexcel Imaging US, Inc."), observations,
live_observations, errors}`; `get_aerial_image(prop)`; `fetch_live`; `read_cached_property`;
`normalize_property_extract`; `footprint_box`.

## CoStar: listings (`costar_provider.py`), mock

| | Mock | Live (untested placeholder) |
|---|---|---|
| Data | `backend/fixtures/properties.json` (5 Houston sample listings + 4 Austin listings) | `GET {COSTAR_API_BASE_URL}/listings?propertyType=retail&listingType=lease` with `Authorization: Bearer {COSTAR_API_KEY}` |
| Mapping | Direct (`Property(**row)`) | `map_costar_listing` tolerates CoStar-style names (`listingId`, `address.streetAddress`, `availableSpaceSf`, `monthlyRent`, `zoningCode`, `tiAllowancePerSf`, `primaryPhotoUrl`, `virtualTourUrl`, ...) |
| Env | none | `COSTAR_API_KEY`, `COSTAR_API_BASE_URL` (placeholder `https://api.costar.example/v1`) |

`search_properties(city, state, min_size, max_size, max_rent)` filters in Python: `city` matches the
city name or the ZIP, and unavailable listings are skipped. `get_property(id)` backs `/analyze`.

**Houston sample listings** (`listing_source: "sample"`): real buildings and coordinates, illustrative
rent, size, previous use and TI. The UI shows a "Sample listing" badge. Houston has no zoning, so
`zoning` is null.

| id | Address | Sq ft | Rent | Previous use | TI/sq ft | Use restrictions |
|---|---|---|---|---|---|---|
| property-hou-01 | 1903 Yale Street | 2,000 | $6,300 | Second-generation restaurant (kitchen + hood) | $0 | none |
| property-hou-02 | 240 W 19th Street | 1,800 | $4,500 | Retail (gift boutique) | $15 | none |
| property-hou-03 | 4720 Washington Avenue | 2,000 | $4,800 | Retail (mattress showroom) | $30 | `no_food_service` |
| property-hou-04 | 801 St Emanuel Street (EaDo) | 2,400 | $5,800 | Bar / lounge, no cooking line | $0 | none |
| property-hou-05 | 3701 Kirby Drive | 1,900 | $4,600 | Medical office (earlier a dental suite) | $35 | none |

**Austin listings** (offline dataset; outside the Vexcel geofence, `listing_source` null):

| id | Address | Sq ft | Rent | Zoning | Previous use | TI/sq ft |
|---|---|---|---|---|---|---|
| property-123 | 123 Elm Street | 2,000 | $4,000 | CS-MU | Retail boutique | $10 |
| property-456 | 456 Oak Avenue | 1,800 | $4,800 | GR | Second-generation restaurant | $0 |
| property-789 | 789 Congress Avenue, Suite 110 | 2,200 | $3,600 | LO | Professional office | $15 |
| property-321 | 2100 E Cesar Chavez Street | 1,600 | $4,200 | LR-V | Coffee shop | $5 |

## Matterport: interior (`matterport_provider.py`), mock

| | Mock | Live (untested) |
|---|---|---|
| Floor plan | `observations.json` → `floor_plan_url` (SVG in `backend/static/floorplans/`) | GraphQL `POST {MATTERPORT_API_BASE_URL}` `model(id){assets{floorplans{url}}}` with basic auth (`MATTERPORT_API_KEY`); model id parsed from `matterport_url` (`...?m=<id>`) |
| Interior facts | `observations.json` → `interior` block (door width, step-free entry, kitchen, hood, grease interceptor, restrooms, operatories, amps, sprinklers, window area) | **Still from fixtures** (automated detection is out of scope) |
| 3D tour | `matterport_embed_url` = listing `matterport_url` | same |

**3D tours:** no listing has a tour link yet (`matterport_url` is null everywhere), so the report shows
"No Matterport 3D tour for this listing". The viewer is ready: set a listing's `matterport_url` to a
`https://my.matterport.com/show/?m=<id>` link and the report embeds it in an iframe.

Functions: `get_interior(prop)`, `get_interior_images(property_id, matterport_url)`.

## Fixture format (`backend/fixtures/observations.json`)

```json
"property-hou-01": {
  "floor_plan_url": "/static/floorplans/property-hou-01.svg",
  "aerial_url": "/static/aerials/property-hou-01.svg",
  "interior": { "door_width_inches": { "value": 36, "confidence": 0.9, "note": "...", "box": [0.1, 0.72, 0.06, 0.1] } },
  "aerial":   { "roof_condition": { "value": 4, "note": "Snapshot of Vexcel property/extract on 2026-11-14: ..." } }
}
```

A fact that is absent is unknown, which is how the missing-data policies get exercised (e.g.
property-hou-05 has no grease interceptor fact).

## Anthropic Claude (optional, requirements parser)

If `ANTHROPIC_API_KEY` is set, `requirements_parser.claude_extract` calls the Messages API
(`ANTHROPIC_MODEL`, default `claude-haiku-5-5`) with a JSON-schema output format, an 8 s timeout and
no retries. Validated fields are merged over the regex result. Any failure falls back to regex. This
is independent of `USE_MOCK_DATA`. `/health` reports `parser: "claude"` when a key is configured, and
`AnalyzeResponse.mode.parser` reports the parser actually used for that run.

## Geocoding (not implemented)

`GEOCODING_API_KEY` is read into settings but nothing uses it: every fixture listing has
latitude/longitude, which is all Vexcel needs. A future `geocode(address)` would fill lat/lng for live
CoStar listings that lack them.

## Switching to live

```bash
# backend/.env
USE_MOCK_DATA=false
VEXCEL_API_KEY=...            # only providers with keys go live
```

Restart uvicorn (env is read at startup), then `curl localhost:8000/health`. CoStar and Matterport
endpoint paths are still placeholders until confirmed against sponsor docs; their mapping functions are
the only code to adjust.
