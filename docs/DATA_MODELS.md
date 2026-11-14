# Data Models

These models define the structure of data in requests, responses, and storage.

## app/models/BusinessProfile.py

- **BusinessProfile** (Pydantic BaseModel):
  - `type: str` – Business category (e.g. "restaurant", "gym", "clinic").
  - `details: str` – Free-text describing requirements (parsed into structured needs).
  - `city: str`
  - `state: str`

*Example:*
```python
class BusinessProfile(BaseModel):
    type: str
    details: str
    city: str
    state: str
```

## app/models/Property.py

- **Property** (SQLModel or Pydantic):
  - `id: str`
  - `address: str`
  - `city: str`
  - `state: str`
  - `zip: str`
  - `size_sqft: int`
  - `rent: float` (monthly)
  - `latitude: float` (optional)
  - `longitude: float` (optional)
  - `image_url: str` (thumbnail)
  - `matterport_url: str` (link to 3D tour)
  - `available: bool`

*Example:*
```python
class Property(BaseModel):
    id: str
    address: str
    city: str
    state: str
    zip: str
    size_sqft: int
    rent: float
    latitude: Optional[float]
    longitude: Optional[float]
    image_url: Optional[str]
    matterport_url: Optional[str]
```

## app/models/AnalysisResult.py

- **AnalysisResult** (Pydantic):
  - `property_id: str`
  - `score: float`
  - `total_cost_estimate: {min: float, max: float}`
  - `breakdown: Dict[str, {min: float, max: float}]` (cost categories)
  - `compliance: Dict[str, {status: str, notes: str}]`
  - `questions_for_landlord: List[str]`

*Example:*
```python
class AnalysisResult(BaseModel):
    property_id: str
    score: float
    total_cost_estimate: CostRange
    breakdown: Dict[str, CostRange]
    compliance: Dict[str, ComplianceStatus]
    questions_for_landlord: List[str]
```

- **CostRange**: model with `min: float`, `max: float`.
- **ComplianceStatus**: model with `status: str` (PASS/RISK/UNKNOWN), `notes: str`.

## app/models/Criterion.py

- **Criterion** (for criteria registry, if loaded as model):
  - `id: str`
  - `description: str`
  - `domain: str`
  - `weight: float`
  - `hard_block: bool`
  - `evaluator: str`
  - `required_inputs: List[str]`
  - `missing_data_policy: str`
  - `evidence_required: bool`
  - `source: str`
  - `thresholds: any` (dependent on evaluator)
  - `jurisdictions: List[str]`

*Example YAML (criteria.yaml) entry:*
```yaml
- id: 'adequate_parking'
  description: 'Parking meets local zoning requirements'
  domain: 'regulatory'
  weight: 10
  hard_block: false
  evaluator: 'parking_checker'
  required_inputs: ['visible_parking_count', 'business_parking_req']
  missing_data_policy: 'assume_risk'
  evidence_required: true
  source: 'City of Austin Zoning Code'
  thresholds:
    min_spaces_per_sqft: 0.001
  jurisdictions: ['TX', 'Austin']
```

## Relationships

- A `BusinessProfile` leads to multiple `AnalysisResult`s (one per property).
- Criteria are independent of specific data models and are loaded from `criteria.yaml` at startup.
