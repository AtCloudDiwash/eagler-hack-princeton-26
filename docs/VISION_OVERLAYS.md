# Vision and Image Overlays

The report shows **where** a finding came from by drawing evidence boxes on the aerial image
(Vexcel) and the floor plan (Matterport). Overlays illustrate; the text legend and criterion notes are
the record.

## Box format

`Evidence.box = [x, y, w, h]`, **normalized 0-1** relative to the source image (top-left origin).
Boxes are fractions, so they stay aligned at any rendered size.

## Which source draws on which image

| Evidence `source` | Drawn on | Typical boxed facts |
|---|---|---|
| `vexcel` | `media.aerial_url` (top-down only, never the angled photo) | `building_footprint` (live / snapshot), `visible_parking_count` (hand-made fixture box) |
| `matterport` | `media.floor_plan_url` | `door_width_inches`, `bathrooms_visible`, `kitchen_equipment_visible`, `plumbed_operatories` |
| `costar`, `requirements`, `jurisdiction` | not drawn (no image) | shown as text and evidence chips |

Evidence without a `box` is listed as text only.

## Where boxes come from

### Live Vexcel: building footprint (`vexcel_provider.footprint_box`)

`/property/extract` returns the building outline as WKT (`footprint.wkt`, lon/lat). The live ortho is
requested centred on the listing point, north up, covering `BBOX_METERS` = 100 × 100 m at 800 × 800 px,
so the outline can be mapped onto it:

1. Parse every ring of the (MULTI)POLYGON into (lon, lat) vertices.
2. Convert each vertex to local metres from the centre (equirectangular approximation):
   `east = Δlon(rad) × R × cos(lat0)`, `north = Δlat(rad) × R`, with R = 6,371,008.8 m.
3. Clip each ring to the image rectangle (|east| ≤ 50 m, |north| ≤ 50 m) with Sutherland-Hodgman, so
   vertices far off-image don't stretch the box.
4. Take the bounding box of the clipped points and normalize:
   `x0 = (min east + 50) / 100`, `x1 = (max east + 50) / 100`,
   `y0 = (50 − max north) / 100`, `y1 = (50 − min north) / 100` (image y grows downward).
5. Clamp to 0-1 and return `[x0, y0, x1 − x0, y1 − y0]` rounded to 4 decimals; `None` if the footprint
   is not visible or degenerate.

The box is an axis-aligned bounding box of the outline, not the polygon itself, and it covers the
**whole building** (the suite is usually a fraction of it). Tests: `test_footprint_box_math`,
`test_footprint_clipped_before_bbox`, `test_recorded_footprint_box_matches_visible_roof`.

### Placeholder vs live box rule (`agent_orchestrator.gather_observations`)

Live and snapshot boxes are positioned on the **live 800 × 800 ortho**; hand-made fixture boxes were
drawn for the **placeholder SVGs**. So:

| Image shown (`media.aerial_source`) | Live facts' boxes | Snapshot fixture boxes (note starts "Snapshot of Vexcel property/extract") | Hand-made fixture boxes |
|---|---|---|---|
| `vexcel-live` | drawn | drawn | drawn (see known issue) |
| `placeholder` (mock mode, or the live ortho failed) | dropped (`box: null`) | dropped | drawn |

So in mock mode the Houston footprint box is not drawn (the fact is still listed), and in live mode it
appears as a dashed "Building footprint" outline.

**Known issue:** in live mode the hand-made `visible_parking_count` boxes of the Houston fixtures
(drawn for the placeholder SVG) are still drawn over the real ortho, where they don't line up with
anything. See [DECISIONS_AND_RISKS.md](DECISIONS_AND_RISKS.md#known-issues).

### Fixtures (mock)

`backend/fixtures/observations.json` stores `value`, `confidence`, `note` and an optional `box` per fact.
`gather_observations` turns them into `Evidence` (source `matterport` for the `interior` block,
`vexcel` for `aerial`). Placeholder images are SVGs in `backend/static/aerials/` (4:3) and
`backend/static/floorplans/`, served at `/static/...` and drawn to match the hand-made boxes.
Interior (Matterport) facts are always fixtures; real detection on Matterport scans is out of scope.

## Frontend implementation

- `lib/overlay.ts`
  - `overlayEvidence(result, "vexcel" | "matterport")` collects boxed evidence from `observations`
    and every `criteria_results[].evidence`, filters by source, and de-duplicates by `key + box`.
  - `boxToStyle(box)` → `{left, top, width, height}` percentages, clamped so a box never spills
    outside the image (values rounded to 2 decimals).
  - `isFootprint(evidence)`: true for `building_footprint`.
- `components/analysis/ImageOverlay.tsx`
  - `OverlayImage` renders the image (`MediaImage fit="natural"`) with absolutely positioned boxes:
    cyan filled boxes (`border-accent bg-accent/15`), numbered, with a hover title "Key: value (note)".
    The footprint is drawn **dashed, beneath** the other boxes, tagged "Building footprint".
  - `frame="square"` (used for the aerial) reserves a fixed 1:1 frame, because live Vexcel orthos are
    800 × 800, so nothing shifts while the image loads. The image and its boxes sit in an inner layer
    that follows the image's own aspect and is centred, so the 4:3 placeholder SVGs letterbox without
    distortion and boxes stay aligned to the picture, not the frame.
  - `EvidenceLegend` repeats each box as text (key, value, note, confidence) with a cyan **live** dot
    for `evidence.live`.
- `components/analysis/AerialPanel.tsx`: "Aerial · Vexcel" caption with a **Live · Vexcel** badge and
  the attribution line (`media.aerial_attribution`, fallback "Imagery © Vexcel Imaging") when
  `aerial_source == "vexcel-live"`, otherwise "Placeholder imagery". When `media.oblique_url` exists,
  **Top-down / Angled** tabs (keyboard arrows supported) switch to the oblique photo in the same square
  frame (`fit="contain"`, whole photo visible) with the note "Overlays are drawn on the top-down view."
- `components/analysis/MediaPanel.tsx`: the aerial panel and "Floor plan · Matterport" side by side,
  plus the Matterport 3D tour iframe when `media.matterport_embed_url` is set.

Tests: `frontend/test/overlay.test.ts` (box math, filtering, de-duplication),
`frontend/test/MediaPanel.test.tsx` (live badge and attribution, tabs, footprint box, square frame,
live dots, older runs), `frontend/test/AnalysisCard.test.tsx` (boxes for both sources).

## Confidence

Each observation shows its confidence when known. Facts below 0.7 are added to the result's
assumptions as "Low-confidence observations (verify on site)". Vexcel estimates are deliberately
low: `estimated_parking_spaces` 0.4, `hvac_tons` = unit-detection score × 0.75.
