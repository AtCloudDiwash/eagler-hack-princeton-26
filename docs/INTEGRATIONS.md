# Integrations

We integrate with the following external data services. For hackathon, we'll use mock data or simple HTTP calls if possible.

## CoStar API (Property Listings)

- **Purpose**: Fetch property metadata (address, size, rent, location).
- **Integration**:
  - If CoStar provides a trial API or dataset, use it. Otherwise, include a JSON fixture (`fixtures/properties.json`) with sample listings.
  - The backend's `costar_provider.py` should abstract the API. For now:
    - Implement a function `search_properties(business_profile)` that reads from `fixtures/properties.json` and filters by city/state and size.
    - If an actual CoStar endpoint exists, use `requests` to call it with `COSTAR_API_KEY` from `.env`.
- **Data Fields**: ID, address, city, state, zip, size, rent, geocoordinates (if available), Matterport tour URL.

## Matterport API (3D Interior Tours)

- **Purpose**: Get a 3D model or snapshot of the property's interior.
- **Integration**:
  - Use Matterport SDK or API if you have a key (`MATTERPORT_API_KEY`). For MVP, we can embed a public demo mattertag or use a static image link.
  - Create `matterport_provider.get_interior(property_id)` that returns an object with:
    - `floor_plan_image_url` (static PNG or JPG of floor plan).
    - `matterport_embed_url` (for iFrame embed) or `None`.
    - Any metadata if available (e.g. list of rooms).
  - If no real API, store a couple of example images in `backend/static/` and map property IDs to them.

## Vexcel Imaging (Aerial Imagery)

- **Purpose**: High-resolution overhead images of properties.
- **Integration**:
  - If Vexcel has an API (`VEXCEL_API_KEY`), use it to fetch an image by coordinates.
  - Alternatively, use a public satellite image API (e.g. Mapbox or Google Static Maps as fallback).
  - `vexcel_provider.get_aerial(property)` should return:
    - `image_url` or binary data of aerial.
    - Optionally, annotation data (GPS polygons).
  - For MVP, include sample aerial images in `backend/static/aerials/`.
  
## Geocoding API (Optional)

- To convert an address to lat/long for aerial fetch.
- Could use Google Geocoding or a free API (e.g. OpenStreetMap Nominatim).
- Define `providers/geocode.py` with function `geocode(address)` that returns lat/lng.
- Use `GEOCODING_API_KEY` if needed.

## Offline/Mock Mode

- If any API fails or `.env` keys are missing, fall back to local data:
  - Use flag `USE_MOCK_DATA` or check if keys are empty.
  - The frontend should still work with mock results (`results.json`).

## API Keys and Configuration

- All keys are read from environment variables (see SECURITY_AND_ENV.md).
- The code should handle missing keys gracefully by switching to mock.
