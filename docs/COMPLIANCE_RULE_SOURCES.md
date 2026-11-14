# Compliance Rule Sources

The citations below are what the app shows in each criterion's `source` field (from
`backend/criteria.yaml`, or overridden per city by `backend/config/jurisdictions.yaml`). Every rule
is a **simplification for decision support**. Users must verify with the city and a licensed
professional. The Houston rules were researched in Nov 2026; the comments in `jurisdictions.yaml`
hold the full research notes.

## By criterion

| Criterion | Houston, TX (demo city) | Austin, TX (offline dataset) | Other cities (default) |
|---|---|---|---|
| `zoning_use` | "Houston has no zoning; recorded deed restrictions are enforceable by the City (Houston Code of Ordinances Ch. 10, Art. XV, §§10-551–10-555); development rules in Code Ch. 42". `zoning_mode: none` → PASS with a "verify deed restrictions" note | "Austin Land Development Code §25-2-491 permitted-use table (simplified — verify per parcel)" | Registry fallback: "Local zoning / land-use rules for the property's city (citation per jurisdiction)" → UNKNOWN (no table) |
| `zoning_use` (use restriction) | "Recorded deed restriction / lease use clause disclosed in the listing; deed restrictions on use are enforceable by the City of Houston (Code Ch. 10, Art. XV, §§10-551–10-555)" | "Recorded deed restriction / lease use clause disclosed in the listing" | same as Austin |
| `parking_sufficiency` | Code Ch. 26, Art. VIII, §26-492 (Ord. 2013-208): restaurant (Class 7(e)) **10.0**, medical/dental clinic (Class 3(d)) **3.5** spaces per 1,000 sq ft GFA. In a market-based parking area: "Houston Code Ch. 26, §26-471 (market-based parking area)", for EaDo "... as amended by Ord. 2019-0540 (July 2019 expansion)" → no minimum | Austin parking note: minimums eliminated citywide Nov 2, 2023 (ADA accessible-space rules still apply) | "No local parking rule loaded; compared against the spaces your business needs." |
| `ada_accessibility` | "2010 ADA Standards §404.2.3 (32 in. min clear width)" | same | same |
| `kitchen_equipment` | "Restaurant build-out standards" | same | same |
| `grease_interceptor` | "UPC §1014 Grease Interceptors; Austin Water pretreatment program" (registry text, not city-specific; see known issues) | same | same |
| `operatory_plumbing` | "Dental clinic build-out standards" | same | same |
| `bathroom_count` | "2021 Uniform Plumbing Code with City of Houston amendments (effective Jan 2, 2024), Table 422.1 (simplified)" | "2024 Uniform Plumbing Code as amended by Austin (City Code Ch. 25-12), Table 422.1 (simplified)" | "Model plumbing code fixture table (IPC Table 2902.1 / UPC Table 422.1) (simplified)" |
| `hvac_capacity` | "Rule of thumb: sq ft per ton by business type" | same | same |
| `electrical_service` | "Typical service size by business type" | same | same |
| `fire_safety` | "IBC §903.2 automatic sprinkler thresholds" | same | same |
| `window_visibility` | "Business importance (street visibility drives walk-in traffic)" | same | same |
| `roof_condition` | "Vexcel AI roof condition score (1–5) from aerial imagery" | same (no data offline → UNKNOWN, not scored) | same |

## Simplifications

| Rule | Simplification |
|---|---|
| Houston no-zoning | Houston has no zoning ordinance, so there is no use table. The check passes and asks the landlord about deed restrictions (UNKNOWN if the listing doesn't state its restrictions at all). A restriction is only caught when the listing discloses it (`Property.use_restrictions`, mapped to blocked uses by `use_restriction_blocks`) |
| Use restrictions | Tags such as `no_food_service`, `no_restaurant`, `no_cooking`, `office_only` block restaurants; `no_medical` blocks medical offices. A blocking restriction is a definitive failure (hard block) in any city |
| Houston parking ratios | The conservative full-restaurant ratio (10.0) is used; the smaller "small/neighborhood restaurant" classes (8.0 / 9.0, §26-472 definitions) were not verified. Re-tenanting with the same use class (only the *incremental* increase is required) is not modeled, so the full ratio is applied. Chapter 26 revisions were proposed in May 2026: re-verify |
| Market-based parking areas | Downtown and EaDo are modeled as **conservative inner rectangles** of the official map; Midtown (only partly in the area) is not modeled, so Midtown listings get the minimum. A listing outside the rectangles is treated as subject to minimums |
| Parking requirement | Per property: the city minimum for the listing's actual size and location, never below the user's stated number; with no city minimum, the user's number or the business guideline (`parking_per_capacity_unit`). ADA accessible-space counts are not checked |
| Austin zoning | Base districts only; combining districts / overlays (`-MU`, `-CO`, `-V`) are stripped; only restaurant and medical office uses |
| ADA | Front entry door width and step-free entrance only (§404.2.3 clear width; §303 changes in level) |
| Kitchen | Presence of a cooking line and Type I hood (IMC §507) from the interior scan |
| Grease interceptor | Presence only; sizing and pump-out schedule not checked |
| Restrooms | One single-user room up to `single_user_max_occupants`, otherwise separate facilities per sex. For a 40-seat restaurant (occupant load 46) this gives 2, which matches UPC 2021 Table 422.1 (Assembly: restaurants). Houston amendments to 422.1 were not reviewed |
| HVAC | Industry rule of thumb (restaurant 200 sq ft/ton, dental 300), not a Manual N load calculation. Vexcel rooftop units are building-level; the suite share is prorated by floor area and a short share is "verify with landlord" |
| Electrical | Industry practice (restaurant 400 A, dental 200 A), not an NEC Article 220 load calculation |
| Fire sprinklers | IBC §903.2.1.2 (Group A-2: fire area > 5,000 sq ft or occupant load >= 100), using suite size as fire area; Group B is not triggered by size alone |
| Roof | Vexcel AI condition score (1-5) and detected defects from aerial imagery; not a roof inspection |

## Recorded but not evaluated

`jurisdictions.yaml` also records, for reference only (no evaluator reads them yet): `building_code`
(Houston: 2021 IBC with City of Houston amendments), `health_code` (Houston: Texas Food Establishment
Rules 25 TAC Ch. 228 and the FDA Food Code, adopted by reference effective Sept 1, 2025; plan review,
pre-operational inspection and annual Food Dealer permit; Austin: 25 TAC Ch. 228), `grease_code`
(Houston: Code Ch. 47, Art. XI; §47-512(b) quarterly pump-out; annual FOG generator permit) and
`plumbing_fixture_note`.

## Reference links

Houston:
- Deed Restriction Enforcement (City Legal Dept.): https://www.houstontx.gov/legal/deed.html
- Off-street parking ordinance: https://www.houstontx.gov/planning/Off-Street-Parking-Ordinance.html
- §26-492 parking requirements by use: https://www.houstontx.gov/planning/DevelopRegs/docs_pdfs/Requirements%20for%20Use%20Classifications.pdf
- Food permits (Houston Health Department): https://www.houstonhealth.org/services/permits/food-permits
- Opening a food establishment: https://www.houstonhealth.org/services/permits/food-permits/opening-food-establishment

Austin:
- Land Development Code (Title 25): https://library.municode.com/tx/austin/codes/land_development_code
- Austin parking reform (Nov 2023): https://www.austintexas.gov/ (search "parking minimums")

General:
- 2010 ADA Standards for Accessible Design: https://www.ada.gov/law-and-regs/design-standards/2010-stds/
- Texas Food Establishment Rules, 25 TAC Chapter 228: https://www.dshs.texas.gov/retail-food-establishments
- International Building Code / International Plumbing Code: https://codes.iccsafe.org/
- Uniform Plumbing Code (IAPMO): https://epubs.iapmo.org/

## Disclaimer

These rules are for informational use only. The app does not replace a title / deed-restriction
search, a zoning verification letter, a licensed architect, or a health or building inspection. Every
UNKNOWN or "verify" result comes with a landlord question so the user can close the gap.
