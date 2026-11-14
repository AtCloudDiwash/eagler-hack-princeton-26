"""Snapshot live Vexcel property facts into fixtures/observations.json so MOCK mode reproduces them.

For every property (with coordinates) in the properties file, calls the live Vexcel provider with
force_refresh, normalizes /property/extract, prints the facts and merges them into that
property's `aerial` block as {value, confidence, note, box?}. Imagery is NOT copied into the
fixtures: it stays in the gitignored backend/static/vexcel-cache/ (Vexcel imagery is licensed).

Safe to re-run: facts are replaced key by key, other fixture facts (e.g. visible_parking_count)
are kept, and properties outside the account geofence / without data are skipped.

Usage (from backend/, needs VEXCEL_API_KEY in backend/.env):
    venv/bin/python scripts/snapshot_vexcel.py                       # all fixture properties
    venv/bin/python scripts/snapshot_vexcel.py --only property-901   # selected ids
    venv/bin/python scripts/snapshot_vexcel.py --dry-run             # print, don't write
    venv/bin/python scripts/snapshot_vexcel.py --properties /tmp/p.json --observations /tmp/o.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import FIXTURES_DIR, settings  # noqa: E402
from app.models import Evidence, Property  # noqa: E402
from app.providers import vexcel_provider  # noqa: E402

FACT_GROUPS = ("interior", "aerial")


# --------------------------------------------------------------------------------------------
# observations.json read / merge / write (keeps the hand-written one-fact-per-line layout)
# --------------------------------------------------------------------------------------------


def _inline(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))


def _inline_fact(fact: Any) -> str:
    if not isinstance(fact, dict) or not fact:
        return _inline(fact)
    return "{ " + ", ".join(f"{_inline(k)}: {_inline(v)}" for k, v in fact.items()) + " }"


def dump_observations(data: dict[str, Any]) -> str:
    """Serialize like the hand-written fixture: one property block per id, one fact per line."""
    lines = ["{"]
    top = list(data.items())
    for i, (pid, record) in enumerate(top):
        comma = "," if i < len(top) - 1 else ""
        if not isinstance(record, dict):
            lines.append(f"  {_inline(pid)}: {_inline(record)}{comma}")
            continue
        lines.append(f"  {_inline(pid)}: {{")
        fields = list(record.items())
        for j, (name, value) in enumerate(fields):
            fcomma = "," if j < len(fields) - 1 else ""
            if name in FACT_GROUPS and isinstance(value, dict):
                lines.append(f"    {_inline(name)}: {{")
                facts = list(value.items())
                for k, (key, fact) in enumerate(facts):
                    kcomma = "," if k < len(facts) - 1 else ""
                    lines.append(f"      {_inline(key)}: {_inline_fact(fact)}{kcomma}")
                lines.append(f"    }}{fcomma}")
            else:
                lines.append(f"    {_inline(name)}: {_inline(value)}{fcomma}")
        lines.append(f"  }}{comma}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def snapshot_entry(ev: Evidence, on: str) -> dict[str, Any]:
    entry: dict[str, Any] = {"value": ev.value}
    if ev.confidence is not None:
        entry["confidence"] = ev.confidence
    entry["note"] = f"Snapshot of Vexcel property/extract on {on}: {ev.note}" if ev.note else (
        f"Snapshot of Vexcel property/extract on {on}"
    )
    if ev.box is not None:
        entry["box"] = ev.box
    return entry


def merge_snapshot(observations: dict[str, Any], property_id: str, facts: dict[str, Evidence], on: str) -> None:
    """Replace/insert `facts` in the property's aerial block; leave every other fact alone."""
    record = observations.setdefault(property_id, {})
    aerial = record.setdefault("aerial", {})
    for key, ev in facts.items():
        aerial[key] = snapshot_entry(ev, on)


# --------------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------------


def _load_properties(path: Path) -> list[Property]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Property(**p) for p in (raw if isinstance(raw, list) else raw.get("properties", []))]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--properties", type=Path, default=FIXTURES_DIR / "properties.json")
    parser.add_argument("--observations", type=Path, default=FIXTURES_DIR / "observations.json")
    parser.add_argument("--only", default="", help="comma-separated property ids")
    parser.add_argument("--dry-run", action="store_true", help="print facts without writing")
    args = parser.parse_args(argv)

    settings.force_mock = False  # this script is live-only, whatever USE_MOCK_DATA says
    if settings.provider_mode(settings.vexcel_api_key) != "live":
        print("VEXCEL_API_KEY is not set (backend/.env); nothing to snapshot.", file=sys.stderr)
        return 2
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    today = date.today().isoformat()
    snapshots: dict[str, dict[str, Evidence]] = {}

    for prop in _load_properties(args.properties):
        if only and prop.id not in only:
            continue
        if prop.latitude is None or prop.longitude is None:
            print(f"SKIP {prop.id}: no coordinates")
            continue
        result = vexcel_provider.get_aerial(prop, force_refresh=True)
        errors = result["errors"]
        imagery = "ortho+oblique" if result["oblique_url"] and result["aerial_source"] == "vexcel-live" else (
            "ortho" if result["aerial_source"] == "vexcel-live" else "no imagery")
        if errors.get("property") == vexcel_provider.GEOFENCE_REASON:
            print(f"SKIP {prop.id} ({prop.city}, {prop.state}): outside the Vexcel account geofence")
            continue
        if not result["live_observations"]:
            print(f"SKIP {prop.id} ({prop.city}, {prop.state}): no property data ({errors.get('property', 'empty')}); {imagery} cached")
            continue
        facts = result["live_observations"]
        snapshots[prop.id] = facts
        print(f"{prop.id} ({prop.address}, {prop.city}, {prop.state}) - {imagery} cached")
        for key, ev in facts.items():
            conf = f"  conf {ev.confidence:g}" if ev.confidence is not None else ""
            box = f"  box {ev.box}" if ev.box else ""
            print(f"    {key:26} {ev.value!r}{conf}{box}")

    if not snapshots:
        print("No facts to write.")
        return 0
    if args.dry_run:
        print(f"Dry run: {args.observations} not changed.")
        return 0
    # Re-read right before writing so concurrent edits to the fixture are not lost.
    observations = json.loads(args.observations.read_text(encoding="utf-8"))
    for pid, facts in snapshots.items():
        merge_snapshot(observations, pid, facts, today)
    args.observations.write_text(dump_observations(observations), encoding="utf-8")
    print(f"Wrote {sum(len(f) for f in snapshots.values())} facts for {len(snapshots)} properties to {args.observations}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
