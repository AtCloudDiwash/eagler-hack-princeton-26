# Vision and Image Overlays

The report shows **where** a finding came from by drawing evidence boxes on the aerial image
(Vexcel) and the floor plan (Matterport). Overlays illustrate; the text legend and criterion notes are
the record.

## Box format

`Evidence.box = [x, y, w, h]`, **normalized 0-1** relative to the source image (top-left origin).
Boxes are percentages, so they stay aligned at any rendered size.

## Which source draws on which image

| Evidence `source` | Drawn on | Typical facts |
|---|---|---|
| `vexcel` | `media.aerial_url` | `visible_parking_count` (parking lot), `hvac_tons` (rooftop units) |
| `matterport` | `media.floor_plan_url` | `door_width_inches` (entry door), `bathrooms_visible`, `kitchen_equipment_visible` (cooking line) |
| `costar`, `requirements`, `jurisdiction` | not drawn (no image) | shown as text and evidence chips |

Evidence without a `box` is listed as text only.

## Where boxes come from

- **Mock (default and current live behavior):** `backend/fixtures/observations.json` stores `value`,
  `confidence`, `note` and an optional `box` per fact. `agent_orchestrator.gather_observations` turns
  them into `Evidence` (source `matterport` for the `interior` block, `vexcel` for `aerial`).
- Placeholder images are SVGs in `backend/static/aerials/` and `backend/static/floorplans/`, served
  at `/static/...` and drawn to match the fixture boxes.
- Real detection (object detection on Vexcel imagery, measurements from Matterport) is out of scope.
  A live implementation only needs to emit the same `Evidence` shape.

Demo boxes, for example: property-123 has a parking lot box `[0.05, 0.6, 0.55, 0.3]` (15 spaces) and an
HVAC box on the aerial, plus entry door and restroom boxes on the floor plan. Property-456 has a
kitchen line box `[0.55, 0.1, 0.4, 0.35]`.

## Frontend implementation

- `lib/overlay.ts`
  - `overlayEvidence(result, "vexcel" | "matterport")` collects boxed evidence from `observations`
    and from every `criteria_results[].evidence`, filters by source, and de-duplicates by `key + box`.
  - `boxToStyle(box)` → `{left, top, width, height}` percentages, clamped so a box never spills
    outside the image (values rounded to 2 decimals).
- `components/analysis/ImageOverlay.tsx` renders the image (`MediaImage fit="natural"`) with
  absolutely positioned cyan boxes (`border-accent bg-accent/15`), each numbered, with a hover title
  "Key: value (note)". A numbered legend below repeats key, value, note and confidence. No image →
  placeholder text, and boxes are not drawn.
- `components/analysis/MediaPanel.tsx` places "Aerial · Vexcel" and "Floor plan · Matterport" side
  by side and embeds the Matterport 3D tour iframe when `media.matterport_embed_url` is set.

Tests: `frontend/test/overlay.test.ts` (box math, filtering, de-duplication) and
`frontend/test/AnalysisCard.test.tsx` (boxes drawn for both sources).

## Confidence

Each observation shows its confidence. Facts below 0.7 are added to the result's assumptions as
"Low-confidence observations (verify on site)", e.g. `hvac_tons` (0.6) on property-123.
