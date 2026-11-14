Final refinements before demo:

1. **UI Polish**:
   - Ensure colors are consistent. Add app icon or logo (if available).
   - Add spinner or loading indicator on analysis request.
   - Add tooltips or info icons on compliance labels.
   - Ensure fonts and spacing look neat.

2. **Content Completeness**:
   - Make sure every piece of data returned by backend is shown in UI (cost breakdown, compliance notes, etc).
   - If some fields are empty, show a placeholder like "N/A".

3. **Responsive Check**:
   - Shrink browser window to simulate mobile. Fix any layout issues.

4. **Mock Scenario**:
   - Create a demo profile and save sample API responses as fixtures.
   - Use those to test the flow once more. Example: Business Profile "Restaurant, 40 seats", Properties "Lease A" and "Lease B".

5. **Testing**:
   - Run all tests (`pytest`, `npm test`). Fix any failing tests.
   - Add any missing edge-case tests from TEST_PLAN.md.

6. **Criteria Scaling Test**:
   - As a final check, open `criteria.yaml` and add a new criterion entry (e.g., "exterior_paint_quality").
   - See if the system can load it without code changes and affects scoring.
   - Write a test to confirm that new criterion appears in the scoring JSON.

7. **Documentation Finalization**:
   - Ensure all `.md` docs are filled out (the ones in `docs/`).
   - Update README with current instructions if anything changed.
   - Verify `.env.example` lists all variables from code.

8. **Clean up**:
   - Remove any debug code or console logs.
   - Commit final changes:
     ```bash
     git add .
     git commit -m "Final polish before demo"
     ```

Once complete, the app should be ready to showcase. Verify the demo runbook steps from DEMO_RUNBOOK.md with this final version.
