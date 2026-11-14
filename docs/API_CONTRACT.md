# API Contract (v1)

## Base URL
All endpoints are prefixed with `/api/v1`. Example: `http://localhost:8000/api/v1/analyze`.

### 1. GET /api/v1/properties

Retrieve a list of candidate properties for a given business profile.

- **Query Parameters** (all optional, but include at least `city` or `region`):
  - `business_type` (string): The type of business (e.g. "restaurant", "dental_clinic"). Determines which properties are relevant.
  - `city` (string): City name or postal code to filter by location.
  - `min_size` (int, sqft): Minimum square footage.
  - `max_size` (int, sqft): Maximum square footage.
  - `parking` (int): Number of parking spaces required.
  - `budget` (number): Maximum monthly rent (optional).
- **Response**: JSON array of property objects:
  ```json
  [
    {
      "id": "property-123",
      "address": "123 Main St",
      "city": "Austin",
      "state": "TX",
      "zip": "78701",
      "size_sqft": 2500,
      "rent": 5000,
      "image_url": "https://.../thumbnail.jpg"
    },
    {
      "id": "property-456",
      "address": "456 Elm St",
      "city": "Austin",
      "state": "TX",
      "zip": "78702",
      "size_sqft": 2400,
      "rent": 4800,
      "image_url": "https://.../thumb2.jpg"
    }
  ]
  ```

### 2. POST /api/v1/analyze

Analyze one or more selected properties for fit-out and compliance.

- **Request Body** (JSON):
  ```json
  {
    "business_profile": {
      "type": "restaurant",
      "details": "40 seats, kitchen needed, 2 bathrooms required, 20 parking spaces",
      "city": "Austin",
      "state": "TX"
    },
    "property_ids": ["property-123", "property-456"]
  }
  ```
- **Response**: JSON object containing analysis results:
  ```json
  {
    "business_type": "restaurant",
    "results": [
      {
        "property_id": "property-123",
        "score": 82.5,
        "total_cost_estimate": {"min": 300000, "max": 350000},
        "breakdown": {
          "kitchen_install": {"min": 50000, "max": 80000},
          "hvac_upgrade": {"min": 20000, "max": 30000},
          "plumbing": {"min": 10000, "max": 15000},
          "other": {"min": 5000, "max": 10000}
        },
        "compliance": {
          "ADA_accessible": {"status": "PASS", "notes": "Door width 36in meets ADA"},
          "parking_requirement": {"status": "RISK", "notes": "Only 15 spaces visible, 20 required by zoning"},
          "health_department": {"status": "UNKNOWN", "notes": "Health permit not on file"},
          ...
        },
        "questions_for_landlord": [
          "Is the rooftop HVAC rated for restaurant kitchen exhaust?",
          "How many parking spaces are officially assigned to this unit?"
        ]
      },
      {
        "property_id": "property-456",
        ...
      }
    ]
  }
  ```
- **Fields Explained**:
  - `score`: Composite score (0-100) based on criteria (higher is better).
  - `total_cost_estimate`: Estimated range to build out the space.
  - `breakdown`: Cost components by category.
  - `compliance`: Each rule with status (`PASS`/`RISK`/`UNKNOWN`) and explanation.
  - `questions_for_landlord`: Concise questions to clarify unknowns or negotiate TI allowances.
