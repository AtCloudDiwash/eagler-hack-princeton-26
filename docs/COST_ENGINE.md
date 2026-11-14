# Cost Engine

`backend/app/services/cost_engine.py` is deterministic and config-driven
(`backend/config/costs.yaml`). It outputs **ranges only** and uses no ML. Min and max are computed
independently: every min uses the lower bands and every max the upper bands.

## Formula

```
hard costs        = Σ line items                  each: band × qty   (per_sqft items: band × sq ft)
general cond.     = hard × general_conditions_pct          (only if there are hard items)
contingency       = (hard + general cond.) × contingency_pct   (only if there are hard items)
permits           = flat permits_fees band                 (always: any tenant build-out needs a permit)
fit-out (gross)   = hard + general cond. + contingency + permits   = Σ line_items   → fit_out_estimate
TI allowance      = ti_allowance_per_sqft × size_sqft
net fit-out       = max(0, fit-out − TI)
build-out months  = business buildout_months + Σ adds_months of the hard items
cost to open      = net fit-out + rent × build-out months             → total_cost_estimate
first-year cost   = cost to open + horizon_months × rent              → first_year_cost
```

Soft costs (general conditions, contingency, permits) appear in `line_items` and `breakdown` next to
the hard items, so `Σ line_items == fit_out_estimate` (a test checks this).

Fix items come from evaluators as `CostNeed(item, qty, reason)`. `merge_needs` keeps one line per
item id, using the largest quantity and joining the distinct reasons. An item id that is missing
from `costs.yaml` raises `UnknownCostItem`.

## `costs.yaml` structure

```yaml
disclaimer: >-                      # copied into AnalyzeResponse.disclaimer
  Preliminary estimates from fixed cost bands, not contractor quotes. ...
items:                              # hard-cost bands referenced by evaluators
  <item_id>:
    label: "..."                    # shown in the UI and the landlord letter
    unit: each | per_sqft
    min: <usd>
    max: <usd>
    adds_months: { min: n, max: n } # optional, extends build-out (rent paid before opening)
soft_costs:
  permits_fees:           { label, min, max }        # flat USD
  general_conditions_pct: { label, min: 0.10, max: 0.20 }
  contingency_pct:        { label, min: 0.10, max: 0.20 }
ranking:
  horizon_months: 12                # months of rent after opening in first-year cost
  min_score: 25                     # fit score below this ranks as "weak fit" (see Ranking)
```

| Item | Unit | Min | Max | Adds months |
|---|---|---|---|---|
| `kitchen_install` | each | 40,000 | 60,000 | 1-2 |
| `hood_exhaust` | each | 15,000 | 30,000 | 0-1 |
| `grease_interceptor` | each | 8,000 | 20,000 | |
| `restroom_add` | each | 10,000 | 15,000 | |
| `door_widening` | each | 1,000 | 3,000 | |
| `entrance_ramp` | each | 5,000 | 10,000 | |
| `hvac_rtu` (5-ton) | each | 15,000 | 25,000 | |
| `electrical_service_upgrade` | each | 10,000 | 25,000 | |
| `operatory_plumbing` | each | 5,000 | 8,000 | |
| `fire_sprinkler` | per_sqft | 3 | 7 | 1-1 |
| `permits_fees` (soft) | flat | 5,000 | 10,000 | |

Base build-out months come from `business_types.yaml`: restaurant 2-3, dental clinic 2-4.

## Worked example (real output)

Demo profile: restaurant, "40 seats, kitchen needed, 2 bathrooms, 20 parking spaces", Austin, TX.
**property-123**, 123 Elm Street: 2,000 sq ft, $4,000/month, TI $10/sq ft. The evaluators found no
kitchen, no grease interceptor, 1 of 2 restrooms, 5 of 10 HVAC tons, and 200 A of 400 A service.

| Line | Qty | Min | Max |
|---|---|---|---|
| Commercial kitchen | 1 | 40,000 | 60,000 |
| Grease interceptor | 1 | 8,000 | 20,000 |
| Additional restroom | 1 | 10,000 | 15,000 |
| Rooftop HVAC unit (5-ton shortfall) | 1 | 15,000 | 25,000 |
| Electrical service upgrade | 1 | 10,000 | 25,000 |
| **Hard costs** | | **83,000** | **145,000** |
| General conditions (10% / 20% of hard) | | 8,300 | 29,000 |
| Contingency (10% of 91,300 / 20% of 174,000) | | 9,130 | 34,800 |
| Permits and fees | | 5,000 | 10,000 |
| **Fit-out (gross)** | | **105,430** | **218,800** |
| TI allowance ($10 × 2,000) | | −20,000 | −20,000 |
| Net fit-out | | 85,430 | 198,800 |
| Build-out months (2-3 base + kitchen 1-2) | | 3 | 5 |
| Rent during build-out ($4,000 × 3 / × 5) | | 12,000 | 20,000 |
| **Cost to open** | | **97,430** | **218,800** |
| + 12 months rent | | 48,000 | 48,000 |
| **First-year cost** | | **145,430** | **266,800** |

Compare with **property-456**, 456 Oak Avenue: 1,800 sq ft, $4,800/month (the *highest* rent), a
second-generation restaurant where every check passes. Its only line item is permits ($5,000-$10,000).
Build-out is 2-3 months, so cost to open is $14,600-$24,400 and first-year cost is **$72,200-$82,000**,
about half of property-123's.

All four demo properties (first-year cost):

| Rank | Property | Rent | Fit-out | TI | Cost to open | First-year cost | Score | Status |
|---|---|---|---|---|---|---|---|---|
| 1 | property-456 | 4,800 | 5,000-10,000 | 0 | 14,600-24,400 | 72,200-82,000 | 100.0 | qualifying |
| 2 | property-123 | 4,000 | 105,430-218,800 | 20,000 | 97,430-218,800 | 145,430-266,800 | 31.6 | qualifying |
| 3 | property-321 | 4,200 | 75,180-175,600 | 8,000 | 75,580-184,400 | 125,980-234,800 | 0.0 | weak fit |
| 4 | property-789 | 3,600 | 100,590-215,920 | 33,000 | 78,390-200,920 | 121,590-244,120 | 22.2 | disqualified (zoning) |

To reproduce: `POST /api/v1/analyze` with the demo body in [DEMO_RUNBOOK.md](DEMO_RUNBOOK.md),
or `cd backend && venv/bin/pytest -q tests/test_api.py`.

## Ranking

`agent_orchestrator.rank_results` orders results as follows:

1. **Qualifying**: not disqualified and `score >= ranking.min_score` (25), by `first_year_cost.min`
   then `.max`, cheapest first.
2. **Weak fit**: `score < min_score` (`weak_fit: true`). Property-321 is cheaper than 123 on
   first-year cost but scores 0 (conditional zoning, parking shortfall, no hood, unknown ADA ...),
   so it ranks after 123.
3. **Disqualified**: always last.

Ties are broken by higher score. The cost engine itself never looks at the score.

## Helpers

- `price_item(item_id, qty, reason)`: one priced `CostLineItem`.
- `estimate_cost(missing_items, profile=None, size_sqft=None) -> (min, max)`: sums hard-cost bands at
  qty 1 (per-sq-ft items use `size_sqft` or the business's typical size), without soft costs.
- `estimate_kitchen_cost(has_kitchen)`: `(0, 0)` or the `kitchen_install` band.

## Tuning

Edit `costs.yaml`; it reloads on the next request. Adding a new fix item means adding an `items`
entry and having an evaluator emit `CostNeed("<item_id>", qty, reason)`. Results always carry the
disclaimer, and the UI shows every figure as a range.
