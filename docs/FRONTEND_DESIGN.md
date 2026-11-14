# Frontend Design

The frontend is a modern, responsive web app. Key pages/components:

1. **Home / Input Page**:
   - Header with app title/logo ("Turnkey Matchmaker").
   - Form for **Business Profile**:
     - Dropdown for business type (restaurant, clinic, gym).
     - Text input for details (placeholder: "e.g. 4-chair dental clinic in Austin, TX...").
     - Location inputs (City, State or zip).
     - Submit button ("Find Spaces").
   - Dark navy background, with teal/cyan accent on buttons and highlights.

2. **Property Selection Page**:
   - After submitting profile, display a grid or list of property cards (from `/properties`).
   - Each card: thumbnail image, address, key stats (size, rent).
   - Checkbox or "Analyze" button to select one or more properties.
   - "Compare" button to run analysis on selected ones.

3. **Analysis Report Page**:
   - Layout: Side-by-side cards or a table for each property.
   - **Summary Card** (top of each): shows total cost range, overall score, key highlight (e.g. "High HVAC cost").
   - **Breakdown Section**: Expandable section listing:
     - Renovation cost breakdown (list or bar chart).
     - Compliance results table: columns for rule, status (PASS/RISK), note.
   - **Overlays Section**: Interactive images:
     - Aerial image with overlays (CVs).
     - Optional Matterport embedded viewer or static floorplan.
   - **Landlord Request**: Text area with bullet points of questions for landlord.
   - Visual style: Use Tailwind CSS (dark background, white text). Use icons (from Heroicons or similar) for items like kitchen, parking, checkmark, warning.

4. **Navigation**:
   - Navbar with "Home", "Settings" (criteria weights, optional admin).
   - "Back" button on Analysis to return to property list.

### Component Breakdown

- `BusinessProfileForm`: Collects input.
- `PropertyCard`: Shows property info on selection page.
- `AnalysisCard`: Displays analysis for one property.
- `CriteriaTable`: Dynamic table of criteria vs. properties.
- `MapOverlay` / `ImageOverlay`: Component to overlay annotations on images.
- `LandlordLetter`: Generates and shows textarea with items.

### Responsive Design

- Mobile: Cards stack vertically.
- Desktop: Use grid or flex for side-by-side.
- Use Tailwind utility classes; avoid heavy custom CSS.

### Theming

- Dark theme: `bg-slate-900`, text `text-white`.
- Accent: `text-cyan-400` or `bg-cyan-500`.
- Use [`@tailwindcss/forms`](https://github.com/tailwindlabs/tailwindcss-forms) for nice form elements.
- If using Shadcn/UI, integrate minimal components for dialogs or tabs.

### Visual Consistency

- Use a consistent card style (rounded corners, shadow).
- Align icons and text in lists.
- Provide tooltips for compliance status using small `?` icon.
