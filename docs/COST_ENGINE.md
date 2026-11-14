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

**What is not priced:** a "verify with landlord" result (e.g. a short prorated HVAC share, see
[COMPLIANCE_AGENT.md](COMPLIANCE_AGENT.md#hvac-proration-building-level-vexcel-data)) adds **no** cost;
it becomes a landlord question instead. HVAC is priced (`hvac_rtu`) only when the building has zero
detected rooftop units or direct tonnage is short.

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
  min_score: 55                     # fit score below this ranks as "weak fit" (see Ranking)
```

| Item | Unit | Min | Max | Adds months | Emitted by |
|---|---|---|---|---|---|
| `kitchen_install` | each | 40,000 | 60,000 | 1-2 | `kitchen_checker` |
| `hood_exhaust` | each | 15,000 | 30,000 | 0-1 | `kitchen_checker` |
| `grease_interceptor` | each | 8,000 | 20,000 | | `grease_checker` |
| `restroom_add` | each | 10,000 | 15,000 | | `bathroom_checker` |
| `door_widening` | each | 1,000 | 3,000 | | `ada_checker` |
| `entrance_ramp` | each | 5,000 | 10,000 | | `ada_checker` |
| `hvac_rtu` (5-ton) | each | 15,000 | 25,000 | | `hvac_checker` |
| `electrical_service_upgrade` | each | 10,000 | 25,000 | | `electrical_checker` |
| `operatory_plumbing` | each | 5,000 | 8,000 | | `operatory_checker` |
| `fire_sprinkler` | per_sqft | 3 | 7 | 1-1 | `fire_safety_checker` |
| `roof_repair` (flat roof repair / recoat) | per_sqft (qty = the **suite's** `size_sqft`, a tenant's share, not the whole building) | 4 | 9 | | `roof_checker` |
| `permits_fees` (soft) | flat | 5,000 | 10,000 | | always |

Base build-out months come from `business_types.yaml`: restaurant 2-3, dental clinic 2-4.

## Worked example (real output)

Demo profile: restaurant, "40 seats, kitchen needed, 2 bathrooms", Houston, TX.
**property-hou-02**, 240 W 19th Street: 1,800 sq ft, $4,500/month, TI $15/sq ft. The evaluators found a
stepped entrance, no kitchen, no grease interceptor, 1 of 2 restrooms, 200 A of 400 A service, and a
Vexcel roof condition of 2/5. HVAC (3 rooftop units on a 9,390 sq ft building → ≈2.9-ton share vs 9
needed) is "verify with landlord", so it is not priced.

| Line | Qty | Min | Max |
|---|---|---|---|
| ADA entrance ramp | 1 | 5,000 | 10,000 |
| Commercial kitchen | 1 | 40,000 | 60,000 |
| Grease interceptor | 1 | 8,000 | 20,000 |
| Additional restroom | 1 | 10,000 | 15,000 |
| Electrical service upgrade | 1 | 10,000 | 25,000 |
| Roof repair / recoat ($4-$9 × 1,800 sq ft) | 1,800 | 7,200 | 16,200 |
| **Hard costs** | | **80,200** | **146,200** |
| General conditions (10% / 20% of hard) | | 8,020 | 29,240 |
| Contingency (10% of 88,220 / 20% of 175,440) | | 8,822 | 35,088 |
| Permits and fees | | 5,000 | 10,000 |
| **Fit-out (gross)** | | **102,042** | **220,528** |
| TI allowance ($15 × 1,800) | | −27,000 | −27,000 |
| Net fit-out | | 75,042 | 193,528 |
| Build-out months (2-3 base + kitchen 1-2) | | 3 | 5 |
| Rent during build-out ($4,500 × 3 / × 5) | | 13,500 | 22,500 |
| **Cost to open** | | **88,542** | **216,028** |
| + 12 months rent | | 54,000 | 54,000 |
| **First-year cost** | | **142,542** | **270,028** |

Compare with **property-hou-01**, 1903 Yale Street: 2,000 sq ft, $6,300/month (the *highest* rent), a
second-generation restaurant. Its only line item is permits ($5,000-$10,000). Build-out is 2-3 months,
so cost to open is $17,600-$28,900 and first-year cost is **$93,200-$104,500**.

All five Houston properties (first-year cost):

| Rank | Property | Rent | Fit-out | TI | Cost to open | First-year cost | Score | Status |
|---|---|---|---|---|---|---|---|---|
| 1 | hou-01 1903 Yale St | 6,300 | 5,000-10,000 | 0 | 17,600-28,900 | 93,200-104,500 | 100.0 | qualifying |
| 2 | hou-04 801 St Emanuel St | 5,800 | 32,830-82,000 | 0 | 44,430-105,200 | 114,030-174,800 | 66.7 | qualifying |
| 3 | hou-05 3701 Kirby Dr | 4,600 | 75,180-161,200 | 66,500 | 22,480-117,700 | 77,680-172,900 | 50.0 | weak fit |
| 4 | hou-02 240 W 19th St | 4,500 | 102,042-220,528 | 27,000 | 88,542-216,028 | 142,542-270,028 | 16.7 | weak fit |
| 5 | hou-03 4720 Washington Ave | 4,800 | 75,180-161,200 | 60,000 | 29,580-125,200 | 87,180-182,800 | 50.0 | disqualified (use restriction) |

Austin offline dataset ("40 seats, kitchen needed, 2 bathrooms, 20 parking spaces"):

| Rank | Property | Rent | First-year cost | Score | Status |
|---|---|---|---|---|---|
| 1 | property-456 456 Oak Ave | 4,800 | 72,200-82,000 | 100.0 | qualifying |
| 2 | property-321 2100 E Cesar Chavez St | 4,200 | 125,980-234,800 | 0.0 | weak fit |
| 3 | property-123 123 Elm St | 4,000 | 145,430-266,800 | 31.6 | weak fit |
| 4 | property-789 789 Congress Ave | 3,600 | 121,590-244,120 | 22.2 | disqualified (zoning) |

To reproduce: `POST /api/v1/analyze` with the body in [DEMO_RUNBOOK.md](DEMO_RUNBOOK.md#fallback-plan),
or `cd backend && venv/bin/pytest -q tests/test_houston.py tests/test_api.py`.

## Ranking

`agent_orchestrator.rank_results` orders results as follows:

1. **Qualifying**: not disqualified and `score >= ranking.min_score` (**55**), by `first_year_cost.min`
   then `.max`, cheapest first.
2. **Weak fit**: `score < min_score` (`weak_fit: true`), also by first-year cost. 3701 Kirby is cheaper
   than 801 St Emanuel on first-year minimum but scores exactly 50 for a restaurant (it is a medical
   office), so it ranks after it.
3. **Disqualified**: always last.

Ties are broken by higher score. The cost engine itself never looks at the score. Why 55: "clearly more
than half of the weighted, scored criteria pass"; the earlier value 25 let a medical office (50) outrank
real restaurant candidates. Set it to 0 to rank purely by first-year cost.

## Helpers

- `price_item(item_id, qty, reason)`: one priced `CostLineItem`.
- `estimate_cost(missing_items, profile=None, size_sqft=None) -> (min, max)`: sums hard-cost bands at
  qty 1 (per-sq-ft items use `size_sqft` or the business's typical size), without soft costs.
- `estimate_kitchen_cost(has_kitchen)`: `(0, 0)` or the `kitchen_install` band.

## Tuning

Edit `costs.yaml`; it reloads on the next request. Adding a new fix item means adding an `items`
entry and having an evaluator emit `CostNeed("<item_id>", qty, reason)`. Results always carry the
disclaimer, and the UI shows every figure as a range.
