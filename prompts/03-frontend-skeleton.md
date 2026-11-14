Set up the frontend skeleton in `frontend/`:

1. **Home Page (Profile Form)**:
   - Edit `pages/index.tsx`:
     - Create a form with fields:
       - `select` for business type (`restaurant`, `clinic`, etc.).
       - `input type="text"` for details (placeholder example: "40-seat restaurant, need kitchen and parking").
       - `input` for city, state.
       - A "Find Spaces" submit button.
     - On submit, navigate to a property results page (e.g. `/properties` route) with query params or via state.

2. **Properties Page**:
   - Create `pages/properties.tsx`:
     - On mount, read query parameters (business type, location).
     - Fetch from the backend:
       ```
       const res = await fetch(`/api/v1/properties?business_type=${type}&city=${city}`);
       const properties = await res.json();
       ```
     - Display results in a grid of `PropertyCard` components.
   - Each `PropertyCard` shows address, city, size, rent, thumbnail image.
   - Include a checkbox or button to select a property for comparison.

3. **Comparison Button**:
   - On the Properties page, add a "Compare Selected" button.
   - When clicked, gather selected property IDs and send a POST request to `/api/v1/analyze`.
   - Then navigate to `/analysis` page or display results.

4. **Analysis Page (`pages/analysis.tsx`)**:
   - Parse analysis results from API (similar to how you handled /properties).
   - For each property in results, render an `AnalysisCard`:
     - Show property address and score.
     - Show total cost range (format as currency).
     - List compliance statuses (colored indicators).
     - Show breakdown of cost (list).
     - Show any landlord questions.
   - Style using cards or panels.

5. **Styling (Tailwind)**:
   - Ensure dark background: in `globals.css`, set `bg-slate-900` for `body`.
   - Use Tailwind classes like `bg-slate-800 rounded-lg p-4 mb-4` for cards.
   - Buttons: `bg-cyan-500 text-white`.
   - Navigation: Add a basic header with app name on all pages.

6. **State Management**:
   - Simple: use React `useState` or `useRouter` query strings. No need for complex state.

7. **Running Frontend**:
   ```bash
   cd frontend
   npm run dev
   ```
   - Ensure the app loads at `http://localhost:3000` with no errors.

8. **Testing**:
   - Check that form submission triggers a network request (use browser dev tools).
   - Verify data flows from property list to analysis.

9. **Commit**:
   ```bash
   git add frontend
   git commit -m "Frontend skeleton: profile form, property list, and analysis pages"
   ```

After this, the UI should allow entering a profile, listing some mock properties, and receiving an analysis (with placeholder data). Verify basic navigation and fetch calls.
