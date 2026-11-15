This prompt focuses on adding more criteria without changing code:

1. **Add a New Criterion**:
   - In `criteria.yaml`, append an entry for a new criterion, e.g.:
     ```yaml
     - id: "window_visibility"
       description: "Restaurant windows visible from street"
       domain: "marketing"
       weight: 5
       hard_block: false
       evaluator: "check_window_visibility"
       required_inputs: ["window_area"]
       missing_data_policy: "ignore"
       evidence_required: false
       source: "Business Importance"
       thresholds:
         min_area: 10
       applicable_jurisdictions: ["ALL"]
     ```
   - Also increase existing criteria weights to total 100 if needed (normalization is allowed by code).

2. **Implement Evaluator Stub**:
   - In `backend/app/services/compliance_engine.py` or `criteria_manager.py`, add a stub function `check_window_visibility(window_area, min_area) -> status, notes` that simply returns PASS if `window_area >= min_area`, else UNKNOWN.

3. **Test Scaling**:
   - Rerun the analysis endpoint; it should now include the new criterion in scoring.
   - Write a unit test: simulate a property with `window_area` below threshold and ensure the score reflects the change (the max score should adjust based on new weight).
   - Ensure no code errors occur on loading the updated `criteria.yaml`.

4. **Frontend**:
   - Confirm that the frontend does not break; it should automatically display the new criterion in any criteria tables (if implemented).

This demonstrates that criteria can be scaled by config alone. Commit your changes:

```bash
git add backend/criteria.yaml backend/app/services
git commit -m "Add 'window_visibility' criterion to criteria.yaml"
```
