# Compliance Agent

The compliance agent evaluates whether a candidate space meets location-specific requirements. It should not certify legality but flag potential issues.

### Categories of Compliance Checks

1. **Zoning and Permits**
   - *Example:* Parking requirements per zoning. (Tx zoning code might specify X parking spaces per square foot for restaurants.)
   - *Example:* Land use: Is the property zoned for commercial use or specifically for restaurants, medical clinics, etc.?
   - Data Source: City/county zoning maps or CoStar listing data (use `property.zoning` field if available).
   - Output Status: `PASS` if meets known criteria, `RISK` if not, `UNKNOWN` if data is missing.

2. **ADA Accessibility**
   - *Example:* Door widths, number of accessible restrooms, wheelchair ramp presence.
   - Data Source: Matterport measurements (if possible, measure door frames and areas).
   - Threshold: ADA typically requires 32–36 inch clear door width.
   - Output: `PASS` if measured width >= 32in, `RISK` if <32in or no data.

3. **Health and Safety (for restaurants)**
   - *Example:* Is a grease trap present? Is there a permit on file?
   - Data Source: Likely unavailable in imagery; skip or set `UNKNOWN`.
   - We may skip detailed health code; instead, focus on obvious needs (kitchen exhaust existence).
   - Output: `UNKNOWN` with note "Requires inspection."

4. **Building Codes**
   - *Example:* Maximum occupancy vs floor area (not required for early stage).
   - *Example:* Existing HVAC capacity vs expected load.
   - Data Source: Rooftop unit size from aerial (if labeled), or skip.
   - Output: Usually `UNKNOWN` or simple check if feasible.

5. **Plumbing/Electrical Capacity**
   - *Example:* Number of visible sinks, restrooms (from interior plan).
   - Data Source: Matterport snapshot labeling.
   - Output: `PASS`/`RISK` if noticeably insufficient.

### Jurisdiction-Specific Rules

- Use the property city/state to narrow checks. For Hackathon MVP, implement one city’s known rules (e.g. Austin, TX:
  - Parking: 1 space per 75 sqft (or refer to zoning code).
  - ADA: state follows federal ADA.
  - Health: Restaurants need grease trap and ventilation (Flag if none visible).

- Provide citations in `COMPLIANCE_RULE_SOURCES.md` for each rule used.

### Implementation Notes

- The compliance agent runs on each property analysis. It should be a pure function: `def check_compliance(property, business_profile) -> Dict[str, (status, notes)]`.
- Mark a rule as `RISK` if the property clearly violates (e.g. fewer parking than threshold).
- Mark as `UNKNOWN` if we cannot determine (e.g. cannot see electrical panel).
- Never assert compliance with absolute certainty, always allow human follow-up.
- The output `status` values are `PASS`, `RISK`, or `UNKNOWN`.
- In the final report UI, RISK items should be highlighted in red/orange, PASS in green, UNKNOWN in gray.
