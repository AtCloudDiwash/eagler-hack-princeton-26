# Demo Runbook

This guide explains how to present the working prototype in a live demo.

1. **Setup Check (before demo)**:
   - Confirm frontend (`localhost:3000`) and backend (`localhost:8000`) are running. No errors in console.
   - Ensure the `.env` (or mock mode) is set so the app has at least 2 sample properties to compare.
   - Pre-select a demo business profile and sample properties (know which properties by name).
   - Run a quick test call to `/api/v1/analyze` to warm caches.

2. **Introduction (0:00-0:15)**:
   - Briefly introduce the problem: “Traditional CRE search only shows rent, hiding the real cost.”
   - State the solution: “Turnkey Matchmaker shows the actual cost to open a business in each space.”

3. **Show Home Page (0:15-0:45)**:
   - Enter a scenario: e.g., “40-seat restaurant in [Demo City] requiring a kitchen and 2 bathrooms.”
   - Click “Find Spaces”.

4. **Property Selection (0:45-1:00)**:
   - Show the list of candidate spaces (2 or 3).
   - Highlight addresses and monthly rent.
   - Select two spaces for comparison.

5. **Analysis (1:00-1:30)**:
   - Click “Compare”.
   - Point out the loading spinner (if any) and explain it’s running analysis.

6. **Review Results (1:30-2:30)**:
   - For **Property A**: show total cost range (\$X–\$Y), score, key findings.
   - Expand breakdown: highlight that it needed a kitchen + ADA fixes, so higher cost.
   - Show overlays: roof HVAC units highlighted, door width noted.
   - For **Property B**: cheaper total cost because it already had a kitchen.
   - Emphasize surprising insight: “Even though A’s rent is lower, B is \$Z cheaper overall due to fewer renovations.”

7. **Compliance Flags**:
   - Scroll to compliance section.
   - Show one `RISK` (e.g. parking shortfall) with note “Only 15 of required 20 spaces”.
   - Show a `PASS` (e.g. ADA door width).

8. **Landlord Requests**:
   - Reveal the draft list of landlord questions (e.g. about exhaust capacity, assigned parking).
   - Mention this helps negotiate TI allowances.

9. **Custom Weighting (optional)**:
   - If time, go to Settings or developer console, adjust a criterion weight (like Parking weight).
   - Rerun scoring and show how ranking changes.

10. **Conclusion (2:30-2:50)**:
    - Summarize: “This demo showed how Turnkey Matchmaker helps avoid hidden costs using real data.”
    - If applicable, mention sponsors: “We used CoStar/Matterport/Vexcel data per sponsor requirements.”

11. **Fallback Plan**:
    - If something fails, be ready with screenshots or a recorded video of the above steps.
    - Emphasize the core functionality even if some integrations are offline.

12. **Q&A Prep**:
    - Be prepared to explain where the data came from, any assumptions made, and how adding more data (like actual CoStar API) would enhance it.
