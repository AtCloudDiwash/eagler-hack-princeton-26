# Vision and Image Overlays

The app will present aerial and interior images with annotations to explain findings.

## Aerial Images (Vexcel)

- Display the aerial image in the frontend with **normalized coordinate overlays** highlighting relevant features:
  - **Rooftop HVAC units**: Mark bounding boxes over identified HVAC on roof.
  - **Parking areas**: Shade or outline parking lot and count visible spaces.
  - **Ingress/Egress**: Highlight curb cuts or entry points.
- Implementation:
  - If Vexcel API provides metadata (e.g. building outlines or parking polygons), use that to draw shapes.
  - Otherwise, use a placeholder annotation layer (e.g. HTML `<div>`s with absolute positioning).
  - Normalize coordinates so overlays scale with image size.
- UI: Overlay boxes in teal color with semi-transparent fill. Tooltip on hover to show notes (e.g. "3 HVAC units detected").

## Interior Images (Matterport)

- Ideally embed a Matterport 3D viewer component (if licensing allows). If not, use a static floorplan screenshot:
  - On the image, draw markers/icons for:
    - **Plumbing fixtures** (sinks, toilets).
    - **Electric panels**.
    - **Doors** (mark width arrows for ADA).
  - Alternatively, list detected items next to image with icons.
- Implementation:
  - Use Matterport SDK if available (requires API key). As fallback, show a static image and use CSS overlays for measurements.
  - Show dimension lines for any ADA corridors (if coordinate data is available).
  - Example: A green arrow icon for a 36in door.
- UI: Use SVG or Canvas overlays for measurements. If not feasible, at least list observations next to image.

## Visual Evidence in Report

- Each compliance/cost finding in the UI should reference the image when possible:
  - "ADA Accessible: PASS (36in door width) [image]" where [image] is clickable.
  - "Visible plumbing: 2 sinks, 1 toilet" with icon.

Remember: Any visual detection is best-effort. Default to text if unsure. The overlay is meant to **illustrate**, not to be a formal blueprint.
