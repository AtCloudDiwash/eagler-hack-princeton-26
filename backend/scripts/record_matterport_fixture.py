"""Record Matterport Model API responses so the interior agent survives an API outage (or runs without credentials).

Records both query tiers (CORE: identity, floors, rooms, owner annotations; PI: areas, room classifications,
ceilings, door/window openings) exactly as services/matterport.fetch_model returns them. Needs
MATTERPORT_API_KEY / MATTERPORT_API_SECRET with access to the model. The scan data belongs to the model
owner, so recordings are gitignored.

Two kinds of recording:
  default      fixtures/matterport/<id>.json — always served instead of the live API (the UI says "recorded").
  --fallback   fixtures/matterport/fallback/<id>.json — a safety net served ONLY when the live API fails, so the
               UI keeps showing live data normally. Use this before a demo.

Usage:
    cd backend && .venv/bin/python scripts/record_matterport_fixture.py "https://my.matterport.com/show/?m=oNAvrNiXZS7"
    cd backend && .venv/bin/python scripts/record_matterport_fixture.py --fallback oNAvrNiXZS7 WSYTQt3istC
    cd backend && .venv/bin/python scripts/record_matterport_fixture.py --fallback --linked
        (every scan linked to a saved building, plus the suite scan the analysis would pick for amenity-linked ones)
"""
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db  # noqa: E402
from services import matterport, scan_identity  # noqa: E402


async def linked_scans() -> list[str]:
    """Scans the saved buildings use: their linked scan, or the scan choose_scan would analyze instead."""
    ids: list[str] = []
    with db.conn() as c:
        rows = [json.loads(r[0]) for r in c.execute("select candidate from properties")]
    for prop in rows:
        linked = prop.get("matterport_model_id")
        if not linked:
            continue
        ids.append(linked)
        try:
            choice = await scan_identity.choose_scan(prop)
            if choice.get("switched"):
                ids.append(choice["model_id"])
        except Exception as err:  # noqa: BLE001
            print(f"  (could not check {linked}: {err})")
    return list(dict.fromkeys(ids))


async def record(model_id: str, fallback: bool) -> None:
    folder = matterport.FALLBACK_DIR if fallback else matterport.FIXTURE_DIR
    path = folder / f"{model_id}.json"
    primary = matterport.FIXTURE_DIR / f"{model_id}.json"
    backup = primary.with_suffix(".json.bak")
    if primary.exists():
        primary.rename(backup)  # fetch_model serves an existing recording first: re-record from the live API
    try:
        raw = await matterport.fetch_model(model_id, use_cache=False)
    finally:
        if backup.exists():
            backup.rename(primary)
    if raw.get("served_from") == "fallback":
        print(f"{model_id}: live API failed, kept the existing safety-net copy")
        return
    s = matterport.summarize(raw)
    facts = matterport.interior_facts(s)
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**raw, "recorded_at": str(date.today())}, indent=1))
    print(f"Saved '{s['name']}' ({len(s['floors'])} floors, {len(s['rooms'])} rooms, tiers: {', '.join(s['tiers_available'])}) to {path}")
    print(f"  address {s['identity']['address'] or 'not recorded'}; captured {s['identity'].get('captured') or '?'}; "
          f"area {facts['indoor_area_with_walls_sqft'] or facts['indoor_area_sqft'] or 'unknown'} sq ft; {len(facts['doorways'])} doors")


async def main() -> None:
    args = sys.argv[1:]
    fallback = "--fallback" in args
    use_linked = "--linked" in args
    targets = [a for a in args if not a.startswith("--")]
    if not targets and not use_linked:
        sys.exit(__doc__)
    if not matterport.has_credentials():
        sys.exit("Set MATTERPORT_API_KEY and MATTERPORT_API_SECRET in backend/.env first.")
    ids = [matterport.parse_model_id(t) or sys.exit(f"Not a Matterport tour link or model id: {t}") for t in targets]
    if use_linked:
        ids += await linked_scans()
    for model_id in dict.fromkeys(ids):
        try:
            await record(model_id, fallback)
        except Exception as err:  # noqa: BLE001 - keep recording the others
            print(f"{model_id}: failed — {err}")


asyncio.run(main())
