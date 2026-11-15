"""Record the demo-mode Vexcel sample (downtown Houston) from your own key.

Vexcel responses are licensed data, so the fixture is gitignored. Run once with VEXCEL_API_KEY set:
    cd backend && .venv/bin/python scripts/record_demo_fixture.py
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings  # noqa: E402
from services import vexcel  # noqa: E402


async def main() -> None:
    if not settings.vexcel_api_key:
        sys.exit("Set VEXCEL_API_KEY in backend/.env first.")
    features = await vexcel.property_extract(29.7560, -95.3650, 2400, limit=400, calculated=True)
    vexcel.DEMO_FIXTURE.parent.mkdir(exist_ok=True)
    vexcel.DEMO_FIXTURE.write_text(json.dumps({"type": "FeatureCollection", "note": "Recorded Vexcel sample for demo mode (licensed; do not commit)", "features": features}))
    print(f"Saved {len(features)} parcels to {vexcel.DEMO_FIXTURE}")


asyncio.run(main())
