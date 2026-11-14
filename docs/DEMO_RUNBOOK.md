# Demo Runbook

A 3-minute live demo in **Houston, TX** with real Vexcel aerial imagery and AI roof/HVAC facts
(live mode), or fully offline in mock mode. The ranking is identical in both modes; live mode adds the
real aerial photo, the angled view and the building footprint box.

Why Houston: the sponsor's Vexcel key is geofenced to **Los Angeles and Houston**. The original Austin
listings are kept as an offline dataset (mock mode only, see [Fallback plan](#fallback-plan)).

## Before the demo (T-15 min)

### 1. Live Vexcel setup (skip for a mock-only demo)

`backend/.env` (never show this file on screen):

```bash
USE_MOCK_DATA=false
VEXCEL_API_KEY=<sponsor key>      # expires 2026-12-01
# COSTAR_API_KEY / MATTERPORT_API_KEY stay placeholders: CoStar and Matterport remain mock
```

**Pre-warm the imagery cache while online** (re-downloads ortho, oblique and property data for each
listing into `backend/static/vexcel-cache/`):

```bash
cd backend
venv/bin/python scripts/snapshot_vexcel.py --dry-run \
  --only property-hou-01,property-hou-02,property-hou-03,property-hou-04,property-hou-05
```

- `--dry-run` only prints the facts. Without it the script also rewrites the snapshot facts in
  `backend/fixtures/observations.json`, which you don't need for the demo.
- Expect `property-hou-0N (...) - ortho+oblique cached` for all five. `SKIP ... geofence` means the
  key or coordinates are wrong.
- After this, live mode **serves everything from the cache and makes no API calls**, so the demo works
  offline (venue Wi-Fi down) and keeps working after the key expires. The key must still be set,
  because live mode is `USE_MOCK_DATA=false` + a key.

### 2. Start clean

```bash
# backend stopped: delete old runs so "Recent analyses" is empty (the DB is recreated on startup)
rm -f backend/turnkey.db
# terminal 1
cd backend && venv/bin/uvicorn app.main:app --reload
# terminal 2
cd frontend && npm run dev
```

### 3. Checklist

- [ ] `curl localhost:8000/health` → `"status":"ok"`, `vexcel: "live"` (live demo) and `costar` /
      `matterport` / `parser` = `mock` / `mock` / `regex`. In mock mode everything says `mock`.
- [ ] Open http://localhost:3000. The header pill reads **API · mixed data** (live Vexcel) or
      **API · mock data**.
- [ ] Do one full dry run (click path below), then **reset the DB again** (step 2) so the history is
      clean. Keep a finished report tab open as a backup first.
- [ ] `git status`: `backend/criteria.yaml` and `backend/config/` are unmodified.
- [ ] Open `backend/criteria.yaml` in an editor, scrolled to `roof_condition`, for the scaling segment.
- [ ] Optional: `cd frontend && npm run e2e`. It **reuses the running servers**, so run it before the
      DB reset (it adds runs to "Recent analyses").
- [ ] Browser zoom ~110%; close other tabs; notifications off.

## Script

### 1. Problem (0:00-0:20)
> "A cheap lease can hide a $150k kitchen build-out. Listings show rent; small business owners find out
> the real cost after they sign. Turnkey Matchmaker ranks spaces by what it actually costs to open."

### 2. Profile (0:20-0:40), home page `/`
- Business type **Restaurant**. Type **"40 seats, kitchen needed, 2 bathrooms"**. City is already
  **Houston**, State **TX**.
- Say: "Plain English. Anything I leave out is filled in and shown as an assumption. I didn't give a
  parking number, so Houston's own parking code will be applied."
- Click **Find spaces**. (**Use example** adds "20 parking spaces": the ranking stays the same, see below.)

### 3. Candidate spaces (0:40-1:00), `/properties`
- Five Houston spaces at real buildings, each with a **Sample listing** badge. Hover it: "Real building;
  rent, size and previous use are illustrative until CoStar listings are connected." Be upfront about it.
- **4720 Washington Avenue** shows an orange line: **Use restriction: no food service**.
- Point at rents: 1903 Yale is the **most expensive at $6,300**; 240 W 19th is the cheapest at $4,500.
- Expand **Criteria used (11)**: "This table comes straight from our YAML criteria registry."
- **Select all** → **Compare 5 selected**.

### 4. Report (1:00-2:15), `/analysis/{id}`

Expected outcome (same in mock and live mode):

| Rank | Property | Rent | First-year cost | Score | Why |
|---|---|---|---|---|---|
| **#1** | 1903 Yale St | $6,300 | $93.2k-$104.5k | 100 | Second-gen restaurant: kitchen, hood, grease interceptor, 2 restrooms, 400 A; only permits |
| #2 | 801 St Emanuel St | $5,800 | $114.0k-$174.8k | 66.7 | Bar in EaDo: needs a hood and a grease interceptor; **no city parking minimum** there |
| #3 | 3701 Kirby Dr | $4,600 | $77.7k-$172.9k | 50.0 | **Weak fit** (below the 55 gate): medical office, full kitchen needed, 200 A |
| #4 | 240 W 19th St | $4,500 | $142.5k-$270.0k | 16.7 | **Weak fit**: retail box, stepped entry, 1 restroom, 4 of 18 spaces, roof 2/5 |
| #5 | 4720 Washington Ave | $4,800 | $87.2k-$182.8k | 50.0 | **Disqualified**: recorded `no_food_service` use restriction |

With "20 parking spaces" in the details, 801 St Emanuel scores 55.6 (its 0 on-site spaces now count
against it) and the order is unchanged.

Talking points, top to bottom:
1. **Requirements summary**: 40 seats, occupant load 46, 2 restrooms, **Parking (city code) 14 spaces**
   (Houston Code §26-492: 10 per 1,000 sq ft × 1,400 sq ft, recomputed per property), 7 tons HVAC, 400 A.
   Mode badges show which providers were live.
2. **Side-by-side table**: "The most expensive lease is the cheapest to open. The cheapest lease, the retail box
   at 240 W 19th, costs 1.5x to 2.5x as much in year one."
3. **1903 Yale card → Visual evidence** (live mode): the **real Vexcel aerial** with a **Live · Vexcel**
   badge and the attribution line. The dashed **Building footprint** box comes from Vexcel's AI building
   outline. Click **Angled** for the oblique (north-facing) photo. Facts with a cyan **live** dot came
   from the Vexcel API (served from the server-side cache), not from fixtures.
4. **HVAC → "verify with landlord"**: "Vexcel's AI counted 2 rooftop units on this 19,863 sq ft building.
   Our suite is 2,000 sq ft, so its prorated share is about 1 ton against 10 needed. We don't guess:
   it's UNKNOWN, excluded from the score, no fake cost, and it becomes a landlord question:
   *Which rooftop HVAC units serve this suite?*"
5. **Roof condition from AI**: 1903 Yale's roof scores 4/5 (metal). On **240 W 19th** the roof scores
   **2/5** with water pooling, so the engine adds a **roof repair** line ($7.2k-$16.2k, per sq ft of
   the suite).
6. **Houston has no zoning**: the zoning row on every card says so and cites the deed-restriction rules
   (Code Ch. 10 §§10-551–555). Then **4720 Washington**: red "Blocked by a hard requirement". "Houston
   doesn't zone, but the City enforces deed restrictions, and this one says no food service. You can't
   permit your way around that."
7. **801 St Emanuel → parking**: "0 on-site spaces and it still passes: it's inside the East Downtown
   market-based parking area, where Houston sets no minimum (§26-471)." Compare 240 W 19th: RISK, 4
   spaces vs 18 required by §26-492.
8. **3701 Kirby**: "Cheaper on paper than #2, but it's a medical office: fit score 50, so it's flagged
   weak fit and ranked after real restaurant candidates." (Run it as a *Dental clinic* and Kirby wins.)
9. **Cost breakdown** (801 St Emanuel): hood $15-30k, grease interceptor $8-20k, general conditions,
   contingency, permits. "Ranges from fixed cost bands, never a fake-precise number."
10. **Landlord letter**: **Copy**. "A ready-to-send request for TI and free rent during build-out."
11. Reload: the report comes back from SQLite and appears under "Recent analyses".

**Sample-listing honesty**: the buildings and coordinates are real and the Vexcel data is real; rent,
size, previous use, TI, the interior facts (Matterport) and the striped parking counts are illustrative
until CoStar and Matterport access is connected.

### 5. Config-only scaling (2:15-2:45)

In `backend/criteria.yaml`, `roof_condition` → `thresholds` → change **`min_condition: 3` to `4`**
and save ("I only want a good roof"). No restart: the file is reloaded on the next request.

- **Back to spaces** → **Select all** → **Compare 5 selected**.
- New result: three more roofs (scored 3/5) are now RISK with a roof repair line. **801 St Emanuel**
  drops from 66.7 to **61.1** and its first-year cost rises to **$125.6k-$205.9k** (roof repair
  $9.6k-$21.6k plus soft costs). 1903 Yale (4/5) is untouched and stays #1; the order is unchanged.
- Bigger swing, if you used **Use example** (20 parking spaces): the same edit drops 801 St Emanuel to
  **50.0 → weak fit**, and it falls behind 3701 Kirby to #3.
- Say: "Business owners care about different things. That's one number in YAML, not a code change.
  New criteria work the same way: `window_visibility` and `roof_condition` were added through the registry."
- The earlier report URL is a stored snapshot and does not change, by design.
- **Revert** right after: `git checkout backend/criteria.yaml`.

(Alternative edit: `parking_sufficiency` `weight: 10` → `40` with "20 parking spaces" pushes 801 St
Emanuel to 41.7, weak fit.)

### 6. Close (2:45-3:00)
> "Real Vexcel aerials and AI roof and HVAC facts, Houston's actual parking and deed-restriction rules,
> one ranked answer: what it costs to open, what's risky, and what to ask the landlord. Deterministic
> rules with citations, so every number is explainable."

## Fallback plan

| Problem | Fix |
|---|---|
| No internet | Live mode serves the pre-warmed cache with no calls. If the cache was not warmed, set `USE_MOCK_DATA=true`, restart uvicorn: same ranking, placeholder aerials (no live badge, no footprint box) |
| Aerial shows "Placeholder imagery" in live mode | Cache missing or the call failed (it falls back per item). Re-run the pre-warm command online, or present in mock mode |
| Key expired / rejected (after 2026-12-01) | Cached properties keep working. Otherwise switch to mock mode |
| Frontend shows "API offline" / "Could not reach the API" | Restart `venv/bin/uvicorn app.main:app --reload` in `backend/`; click **Try again** |
| Next.js error or a slow first compile | Use the pre-opened report tab from the dry run; restart `npm run dev` |
| Port 8000/3000 busy | `lsof -i :8000` and kill it, or run uvicorn on another port and set `API_ORIGIN` in `frontend/.env.local` |
| Results differ from the table above | `git checkout backend/criteria.yaml backend/config/ backend/fixtures/`; check `/health` |
| YAML typo during the scaling segment | The UI shows "Criteria registry error: ... entry #N"; undo the edit and save |
| Houston demo fails entirely | **Austin offline dataset** (mock mode): City **Austin**, **Use example**, Compare 4 → 456 Oak #1 ($72.2k-$82.0k, score 100), 2100 E Cesar Chavez and 123 Elm as weak fits, 789 Congress disqualified on zoning (LO prohibits restaurants) |
| Browser/UI fails | API demo: `curl -X POST localhost:8000/api/v1/analyze -H 'Content-Type: application/json' -d '{"business_profile":{"type":"restaurant","details":"40 seats, kitchen needed, 2 bathrooms","city":"Houston","state":"TX"},"property_ids":["property-hou-01","property-hou-02","property-hou-03","property-hou-04","property-hou-05"]}'`, or http://localhost:8000/docs |
| Everything is down | Screenshots / screen recording of the dry run |

## Q&A prep

- **Where does the data come from?** Vexcel is live (ortho + oblique imagery and `/property/extract`
  AI facts: rooftop AC units, roof condition/material/defects, footprint, paved area, vehicles). CoStar
  listings and Matterport interiors are mock fixtures shaped like their payloads until we have access.
  See [INTEGRATIONS.md](INTEGRATIONS.md).
- **Is the Vexcel data per suite?** No, it's per building (and paving per parcel). That's why HVAC is
  prorated by floor area and a short share becomes a landlord question instead of a cost.
- **Why "verify" instead of RISK for HVAC?** A prorated share is an estimate; the building's units may
  well serve the suite. Penalizing it would push good restaurant spaces down on a guess.
- **Is this AI?** Vexcel's AI does the image analysis. Our agent pipeline is deterministic rules for
  trust and explainability; Claude is optional for parsing free text, with a regex fallback. No ML in costs.
- **How accurate are the costs?** Planning ranges from configurable bands, with every assumption listed.
- **Other cities / businesses?** Add a `jurisdictions.yaml` block (Houston and Austin are loaded; others
  use model codes) and a `business_types.yaml` block. A dental clinic already works.
- **Does the key reach the browser?** No. The backend sends it only in the `X-API-KEY` header, caches
  the images, and serves them from `/static`. See [SECURITY_AND_ENV.md](SECURITY_AND_ENV.md).
