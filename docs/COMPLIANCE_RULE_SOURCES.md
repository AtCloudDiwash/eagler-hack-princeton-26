# Compliance Rule Sources

The citations below are what the app shows in each criterion's `source` field (from
`backend/criteria.yaml`, or overridden by `backend/config/jurisdictions.yaml`). Every rule is a
**simplification for decision support**. Users must verify with the city and a licensed professional.

| Criterion | Source string shown | Underlying reference | Simplification |
|---|---|---|---|
| `zoning_use` | "Austin Land Development Code §25-2-491 permitted-use table (simplified — verify per parcel)" (from `jurisdictions.yaml`; the registry fallback is "Austin LDC §25-2-491 use table (simplified)") | City of Austin LDC Chapter 25-2, §25-2-491 permitted, conditional and prohibited uses by district | Base districts only; combining districts / overlays (`-MU`, `-CO`, `-V`) are stripped; only restaurant and medical office uses |
| `parking_sufficiency` | "Business need; Austin has no minimum parking requirement (Nov 2023)" + jurisdiction `parking_note` | Austin City Council eliminated citywide minimum parking requirements on Nov 2, 2023 | Compares visible spaces against what the business needs (user number, or `parking_per_capacity_unit` guideline), not a code minimum. ADA accessible-space counts are not checked |
| `ada_accessibility` | "2010 ADA Standards §404.2.3 (32 in. min clear width)" | U.S. DOJ 2010 ADA Standards for Accessible Design, §404.2.3 clear width; §303 changes in level | Front entry door width and step-free entrance only |
| `kitchen_equipment` | "Restaurant build-out standards" | Industry practice; Type I hood requirement in IMC §507 | Presence of a cooking line and hood from the interior scan |
| `grease_interceptor` | "UPC §1014 Grease Interceptors; Austin Water pretreatment program" | Uniform Plumbing Code §1014; Austin Water Industrial Waste / pretreatment rules | Presence only; sizing not checked |
| `operatory_plumbing` | "Dental clinic build-out standards" | Industry practice | Count of plumbed treatment rooms |
| `bathroom_count` | Jurisdiction `plumbing_code` + " (simplified)": Austin: "2024 Uniform Plumbing Code as amended by Austin (City Code Ch. 25-12), Table 422.1"; default: "Model plumbing code fixture table (IPC Table 2902.1 / UPC Table 422.1)" | UPC Table 422.1 / IPC Table 2902.1 minimum plumbing fixtures | One single-user room up to `single_user_max_occupants`, otherwise separate facilities per sex at `occupants_per_fixture_per_sex` |
| `hvac_capacity` | "Rule of thumb: sq ft per ton by business type" | Industry rule of thumb (restaurant 200 sq ft/ton, dental 300) | Not a Manual N load calculation |
| `electrical_service` | "Typical service size by business type" | Industry practice (restaurant 400 A, dental 200 A) | Not an NEC Article 220 load calculation |
| `fire_safety` | "IBC §903.2 automatic sprinkler thresholds" | IBC §903.2.1.2 (Group A-2: fire area > 5,000 sq ft or occupant load >= 100) | Uses suite size as fire area; Group B is not triggered by size alone |
| `window_visibility` | "Business importance (street visibility drives walk-in traffic)" | Not a code requirement | Street-facing glass area threshold |

## Reference links

- 2010 ADA Standards for Accessible Design: https://www.ada.gov/law-and-regs/design-standards/2010-stds/
- City of Austin Land Development Code (Title 25): https://library.municode.com/tx/austin/codes/land_development_code
- Austin parking reform (Nov 2023): https://www.austintexas.gov/ (search "parking minimums")
- Texas Food Establishment Rules, 25 TAC Chapter 228 (listed as `health_code` in `jurisdictions.yaml`; not evaluated yet): https://www.dshs.texas.gov/retail-food-establishments
- International Building Code / International Plumbing Code: https://codes.iccsafe.org/
- Uniform Plumbing Code (IAPMO): https://epubs.iapmo.org/

## Disclaimer

These rules are for informational use only. The app does not replace a zoning verification letter,
a licensed architect, or a health or building inspection. Any UNKNOWN result comes with a landlord
question so the user can close the gap.
