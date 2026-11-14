# Criteria Registry

We use a YAML (or JSON) file (`criteria.yaml`) to define scoring criteria. This makes the system extensible: adding or adjusting criteria is done by editing this config, not code.

## Structure of `criteria.yaml`

Each entry in the YAML list is a criterion with fields:

- `id` (string): unique key.
- `description` (string): human-readable description.
- `domain` (string): e.g. "space", "regulatory", "cost".
- `weight` (float): how important this criterion is relative to others.
- `hard_block` (bool): if true, failing this criterion means the space is disqualified.
- `evaluator` (string): name of the function or rule that evaluates this criterion.
- `required_inputs` (list of str): pieces of data needed from analysis, e.g. `["visible_parking", "required_parking"]`.
- `missing_data_policy` (string): policy if data is missing (`"assume_risk"`, `"ignore"`, etc.).
- `evidence_required` (bool): whether this criterion needs observable evidence to score positively.
- `source` (string): reference to code or rule source (for display/citation).
- `thresholds`: criterion-specific thresholds.
- `applicable_jurisdictions` (list of str): regions where this rule applies (use "*ALL*" for general).

### Example Criteria Entries

```yaml
- id: "parking_sufficiency"
  description: "Enough parking spaces for the business type"
  domain: "regulatory"
  weight: 10
  hard_block: false
  evaluator: "check_parking_spaces"
  required_inputs:
    - "visible_parking_count"
    - "business_parking_requirement"
  missing_data_policy: "assume_risk"
  evidence_required: true
  source: "City of Austin Zoning Code, Sec. 25-6-478"
  thresholds:
    min_ratio: 1  # 1 parking spot per 20 seats
  applicable_jurisdictions: ["ALL"]

- id: "ada_door_width"
  description: "Doorway meets ADA width requirements"
  domain: "safety"
  weight: 5
  hard_block: false
  evaluator: "check_ada_door_width"
  required_inputs: ["door_width_in_inches"]
  missing_data_policy: "assume_risk"
  evidence_required: true
  source: "ADA Title III, 2010 Standards"
  thresholds:
    min_width: 32
  applicable_jurisdictions: ["ALL"]

- id: "kitchen_presence"
  description: "Existing commercial kitchen equipment"
  domain: "space"
  weight: 15
  hard_block: false
  evaluator: "check_kitchen_equipment"
  required_inputs: ["kitchen_equipment_visible"]
  missing_data_policy: "assume_cost"
  evidence_required: false
  source: "Restaurant Fit-Out Requirements"
  thresholds: {}
  applicable_jurisdictions: ["ALL"]
```

## How the Registry is Used

- On startup, the backend loads `criteria.yaml`.
- Each criterion's `evaluator` corresponds to a function in `criteria_manager.py` that returns a score or boolean.
- The `weight` influences how much each criterion contributes to the final score.
- The system iterates through criteria, and if `hard_block` and condition is failed, the property gets disqualified or drastically reduced.
- The frontend can display each criterion (ID and description) in a comparison table.

## Scaling Criteria

- To **add a new criterion**, simply append to `criteria.yaml`. Provide an evaluator name and implement the corresponding function.
- Example: To add "window_line_of_sight" criterion, create an entry with an `evaluator` and update `criteria_manager.py`.
- The UI should automatically render any criteria listed here.
