# Cost Estimation Engine

This module computes rough cost ranges for required renovations and improvements. It is **deterministic and rule-based**. Do not attempt to use ML or precise calculations; use broad estimates and clearly state assumptions.

### Cost Factors

For each type of work, we will define a **cost-per-unit** or a flat range. Examples:
- **Kitchen Installation** (if none exists):
  - Base cost per kitchen: \$40,000 – \$60,000 for a small restaurant kitchen (hood, vent, basic fixtures).
- **HVAC Upgrade**:
  - Cost per rooftop unit: \$15,000 – \$25,000 each (depending on capacity).
- **ADA Improvements**:
  - Ramp installation: \$5,000 – \$10,000.
  - Door widening: \$1,000 – \$3,000 per door.
- **Plumbing**:
  - Per new bathroom (toilet + sink): \$10,000 – \$15,000.
  - For a dental clinic, cost per treatment room plumbing: \$5,000 – \$8,000.
- **Electrical Upgrade**:
  - Per panel: \$8,000 – \$12,000.
- **Other**:
  - Demolition/Construction Labor: estimate 10–20% of total build-out.
  - Permits/Fees: flat \$5,000–\$10,000.

### Strategy

1. Identify missing infrastructure from analysis (e.g., "needs 1 kitchen", "needs 5 parking spaces").
2. For each missing item, assign a cost range by looking it up:
   - We can hardcode cost ranges in the code or load from a small JSON (`costs.json`).
   - Adjust based on size: e.g. larger square footage or more seats might mean a bigger kitchen.
3. Sum all min and max costs to produce `total_cost_estimate`.
4. Apply a margin (e.g. +20%) to account for contingency if desired.

### Example

```python
def estimate_cost(missing_items: List[str], business_type: str) -> CostRange:
    # Example pseudocode
    total_min = 0
    total_max = 0
    for item in missing_items:
        if item == "kitchen_install":
            total_min += 40000
            total_max += 60000
        elif item == "bathroom_add":
            total_min += 10000
            total_max += 15000
        elif item == "extra_parking":
            # Suppose cost per space is high (land cost not included)
            total_min += 5000 * num_extra_spaces
            total_max += 8000 * num_extra_spaces
        # ... other items ...
    return {"min": total_min, "max": total_max}
```

### Documentation

- Document all cost assumptions (see COMMENT in code and in this doc).
- Clearly label cost results as **estimates** and not quotes.
- The frontend should present costs as a range and note the assumptions (e.g. "Costs are preliminary estimates; actual construction quotes may vary.").
