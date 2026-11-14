# Agent Orchestration

We conceptualize the backend logic as a sequence of "agents" or steps. Each step processes data and passes it on.

1. **Requirements Parser Agent**
   - Input: `BusinessProfile` (free-form details).
   - Action: Use simple NLP heuristics or regex to extract structured needs:
     - Number of seats/rooms (look for digits, e.g. "40-seat").
     - Special needs: "kitchen", "plumbing", "parking 20".
     - Output: A structured dict, e.g. `{"type": "restaurant", "seats": 40, "bathrooms": 2, "parking": 20}`.
   - (For MVP, manual parsing rules are fine. No external LLM calls.)

2. **Property Search Agent**
   - Input: Parsed requirements and location (city, state).
   - Action: Call `costar_provider.search_properties(location, size_range, type)`.
   - Filter results by suitability (minimum size, user budget, etc.).
   - Output: List of `Property` records.

3. **Vision Agent**
   - Input: A `Property` record.
   - Action: 
     - Retrieve data from `matterport_provider` (3D tour or static floor plan image).
     - Retrieve data from `vexcel_provider` (aerial image).
     - (Optional: Run simple object detection on images if feasible; otherwise use placeholders.)
     - Determine observable features: count of bathrooms, visible kitchen equipment, HVAC units, parking count.
   - Output: An `observations` dict for the property, e.g. `{"bathrooms_visible": 1, "kitchen_equipment": false, "parking_visible": 15}`.

4. **Analysis Agent**
   - Input: Observations, user requirements, property metadata.
   - Action:
     - **Fit-Out Identification**: Compare user needs vs observations to find gaps:
       - If kitchen required but none visible, mark "needs_kitchen_install".
       - If bathrooms needed > visible, mark "needs_bathroom_add".
       - If visible parking < required, mark "needs_extra_parking".
     - **Cost Engine**: For each identified gap, estimate cost range (see COST_ENGINE.md).
     - **Compliance Engine**: Check each relevant rule (see COMPLIANCE_AGENT.md).
       - Example: ADA door width from Matterport measurements.
       - Example: Zoning parking from user location.
     - Prepare partial result: list of missing features and compliance results.
   - Output: Intermediate results to feed scoring.

5. **Recommendation Agent**
   - Input: Analysis results from above for each property.
   - Action:
     - Load scoring criteria from `criteria.yaml`.
     - Compute weighted scores (lower cost, PASS flags increase score; RISK flags decrease).
     - Normalize to a 0-100 scale.
     - Identify any `hard_block` failures (e.g. if `hard_block` flag is triggered, mark property as not recommended).
     - Format final JSON output (see API_CONTRACT.md).
   - Output: Final analysis report (list of `AnalysisResult` for each property).

All these steps happen inside the `/api/v1/analyze` handler. For performance, you may parallelize analysis of multiple properties (using threads or asyncio). Use clear function boundaries: e.g., implement each agent as a class or function with well-defined inputs/outputs.
