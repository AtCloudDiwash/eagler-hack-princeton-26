Integrate data sources and enhance functionality:

1. **CoStar Integration**:
   - In `backend/app/providers/costar_provider.py`:
     - If `COSTAR_API_KEY` is present in `.env`, implement a function to query CoStar (using `requests`). If not, default to reading `fixtures/properties.json`.
     - Map CoStar fields to our `Property` model.
   - Update `/properties` endpoint to use `costar_provider.search_properties`.

2. **Matterport Integration**:
   - In `providers/matterport_provider.py`, add:
     ```python
     def get_interior_images(property_id):
         # If MATTERPORT_API_KEY exists, call Matterport API
         # Else, return a static image URL from fixtures or static files
         return {"floor_plan_url": "...", "matterport_url": None}
     ```
   - Backend: modify analysis to attach these URLs to results.

3. **Vexcel Integration**:
   - In `providers/vexcel_provider.py`, add a similar stub:
     ```python
     def get_aerial_image(address):
         # Use coordinates or address to fetch; if no key, return sample image path
         return {"aerial_url": "static/aerials/sample.jpg"}
     ```
   - Backend: call this and include `aerial_url` in results.

4. **Overlay Annotations**:
   - (At least record the intention: in `VisionOverlays`, annotate known points.)
   - Ensure the analysis result includes coordinates or descriptions for overlays (e.g. store in `AnalysisResult`).

5. **Frontend Enhancements**:
   - On the Analysis page, use the returned image URLs:
     - For aerial, use `<img src={aerial_url} />` and overlay using absolute-positioned divs (if coordinates given).
     - For Matterport, if a URL is provided, embed as `<iframe>` (Matterport embed code).
   - Show a placeholder if no image available.

6. **Compliance Rule Data**:
   - Make sure `compliance_engine` uses any relevant thresholds from `criteria.yaml`.
   - Example: if parking rule says min_ratio=1, compute required spaces as seats/20.

7. **Dynamic Criteria Display**:
   - In `frontend`, load `criteria.yaml` (or have backend send descriptions).
   - Display criteria descriptions and weights in a table, if needed.

8. **Error Handling**:
   - If any API call fails (no internet, bad key), catch exceptions and fallback to mock data.
   - Ensure UI shows an error message if analysis fails.

9. **Review Integration Flow**:
   - Test end-to-end with mock data now replaced by fixture logic.
   - Adjust CORS or proxy if needed (Next.js dev proxy or `http://localhost:8000`).

10. **Commit**:
    ```bash
    git add backend/providers backend/services frontend/components
    git commit -m "Add providers for CoStar/Matterport/Vexcel and image display in frontend"
    ```
