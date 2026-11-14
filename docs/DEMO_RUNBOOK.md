# Demo Runbook

A 3-minute live demo of the real UI in mock mode (deterministic: same numbers every time).

## Before the demo (T-10 min)

```bash
# terminal 1
cd backend && venv/bin/uvicorn app.main:app --reload
# terminal 2
cd frontend && npm run dev
```

- [ ] `curl localhost:8000/health` → `"status":"ok"`, all providers `mock`.
- [ ] Open http://localhost:3000. The header pill reads **API · mock data**.
- [ ] Do one full dry run (below) so Next.js has compiled every route. Keep the report tab open as a backup.
- [ ] `git status`: `backend/criteria.yaml` is unmodified (weights back to defaults).
- [ ] Open `backend/criteria.yaml` in an editor, scrolled to `parking_sufficiency`, for the scaling segment.
- [ ] Optional: `cd frontend && npm run e2e` passes (it reuses the running servers).
- [ ] Browser zoom ~110%; close other tabs; notifications off.

## Script

### 1. Problem (0:00-0:20)
> "A cheap lease can hide a $150k kitchen build-out. Listings show rent; small business owners find out
> the real cost after they sign. Turnkey Matchmaker ranks spaces by what it actually costs to open."

### 2. Profile (0:20-0:45), home page `/`
- Business type: **Restaurant**.
- Click **Use example**. It fills **"40 seats, kitchen needed, 2 bathrooms, 20 parking spaces"**
  (or type it). City **Austin**, State **TX**.
- Say: "Plain English. Anything I leave out is filled from the business profile and shown as an assumption."
- Click **Find spaces**.

### 3. Candidate spaces (0:45-1:05), `/properties`
- Four CoStar listings. Point at the rent: **789 Congress is cheapest at $3,600**, and **456 Oak is the
  most expensive at $4,800**.
- Expand **Criteria used (10)**: "This table comes straight from our YAML criteria registry: weights,
  hard blocks, citations."
- Click **Select all**, then **Compare 4 selected**. The progress overlay shows parsing → listings →
  compliance → fit-out.

### 4. Report (1:05-2:15), `/analysis/{id}`
Expected outcome:

| Rank | Property | Rent | First-year cost | Score | Why |
|---|---|---|---|---|---|
| **#1** | 456 Oak Avenue | $4,800 | $72k-$82k | 100 | Second-gen restaurant: kitchen, hood, grease interceptor, 2 restrooms, 22 parking spaces; only permits |
| #2 | 123 Elm Street | $4,000 | $145k-$267k | 32 | Retail shell: full kitchen, grease interceptor, restroom, HVAC, 400 A service |
| #3 | 2100 E Cesar Chavez | $4,200 | $126k-$235k | 0 | **Weak fit** (below the 25 fit-score gate): conditional zoning, 8 of 20 parking spaces, no hood, door width unknown |
| #4 | 789 Congress Ave | $3,600 | $122k-$244k | 22 | **Disqualified**: LO zoning prohibits restaurants |

Talking points, top to bottom:
1. **Requirements summary**: parsed 40 seats, occupant load 46, 2 restrooms, 20 parking (user),
   7 tons HVAC, 400 A. Assumptions are listed, and the mode badges show mock/regex.
2. **Side-by-side table**: "The *most expensive* lease is the cheapest to open, about half the first-year cost of
   #2. The cheapest lease can't legally be a restaurant."
3. **456 card**: all PASS, cost breakdown = permits only, cost to open $14.6k-$24.4k.
4. **123 card → Cost breakdown**: kitchen $40-60k, grease interceptor, restroom, HVAC unit, electrical, then
   general conditions, contingency, permits, TI −$20k. "Ranges from fixed cost bands, never a single fake-precise number."
5. **123 → Visual evidence**: aerial (Vexcel) boxes around the 15-space lot and the rooftop unit;
   floor plan (Matterport) boxes at the 34-inch door and the single restroom. "Every finding links to evidence."
6. **Compliance & criteria**: RISK *Parking: only 15 spaces visible vs 20 needed*, plus the Austin note
   (no city parking minimum since Nov 2023). PASS *ADA: 34 in. door*. Hover the info icon to show the citation.
7. **789 card**: red "Blocked by a hard requirement: Zoning permits this business use". The note says
   "Zoning LO does not permit restaurant use; a rezoning would be required."
8. **321**: "Cheaper than #2 on paper, but it fails or can't confirm almost every check, so it's flagged
   weak fit and ranked after the spaces that actually fit."
9. **Landlord letter** (any card): **Copy**. "A ready-to-send request for TI and free rent during build-out."
10. The URL is shareable: reload the page and it comes back from SQLite. It also appears under
    "Recent analyses" on the home page.

### 5. Config-only scaling (2:15-2:45)
In `backend/criteria.yaml`, change `parking_sufficiency` → `weight: 10` to **`weight: 40`** and save.
No restart is needed: the file is reloaded on the next request.

- Go **Back to spaces** (the "Criteria used" table now shows weight 40) → **Select all** → **Compare 4 selected**.
- New result: 123 Elm drops to score **24.0**, below the gate → **weak fit, #3**. 2100 E Cesar Chavez moves to **#2**.
  456 stays #1, 789 stays disqualified.
- Say: "Business owners care about different things. That's a YAML edit, not a code change. Adding a whole
  new criterion is the same: `window_visibility` was added this way."
- Note: the earlier report URL is a stored snapshot and does not change, by design.
- **Revert the weight to 10** right after (or `git checkout backend/criteria.yaml`).

### 6. Close (2:45-3:00)
> "CoStar listings, Matterport interiors and Vexcel aerials in one ranked answer: what it costs to open,
> what's risky, and what to ask the landlord. Deterministic rules with citations, so every number is explainable."

## Fallback plan

| Problem | Fix |
|---|---|
| Frontend shows "API offline" / "Could not reach the API" | Restart `venv/bin/uvicorn app.main:app --reload` in `backend/`; click **Try again** |
| Next.js error or a slow first compile | Use the pre-opened report tab from the dry run; restart `npm run dev` |
| Port 8000/3000 busy | `lsof -i :8000` and kill it, or run uvicorn on another port and set `API_ORIGIN` in `frontend/.env.local` |
| Results differ from the table above | `git checkout backend/criteria.yaml backend/config/`; check `USE_MOCK_DATA=true` and that `/health` shows mock |
| YAML typo during the scaling segment | The UI shows "Criteria registry error: ... entry #N"; undo the edit and save |
| Browser/UI fails entirely | API demo: `curl -X POST localhost:8000/api/v1/analyze -H 'Content-Type: application/json' -d '{"business_profile":{"type":"restaurant","details":"40 seats, kitchen needed, 2 bathrooms, 20 parking spaces","city":"Austin","state":"TX"},"property_ids":["property-123","property-456","property-789","property-321"]}'`, or open http://localhost:8000/docs |
| Everything is down | Screenshots / screen recording of the dry run |

## Q&A prep

- **Where does the data come from?** Mock fixtures shaped like CoStar / Matterport / Vexcel payloads.
  Live adapters exist behind `USE_MOCK_DATA=false` + keys and fall back to fixtures on any failure
  (see [INTEGRATIONS.md](INTEGRATIONS.md)).
- **Is this AI?** The agent pipeline is deterministic rules for trust and explainability. Claude is optional
  for parsing free text, with a regex fallback. No ML in costs.
- **How accurate are the costs?** Planning ranges from configurable bands, with every assumption listed;
  not contractor quotes.
- **Other cities / businesses?** Add a `jurisdictions.yaml` block (Austin is loaded; others use model codes)
  and a `business_types.yaml` block. A dental clinic already works.
- **Why isn't the fire sprinkler check a disqualifier?** A missing sprinkler system is priced as a
  retrofit, because it can almost always be added. Zoning is the true deal-breaker.
