"""Sizing: how big the user's space should be, and how well a given space matches that.

Two questions, one module, so the size band and the thresholds that judge it live in one place:

- `estimate(intent)`: the size band (min / target / max sq ft) a request implies. A stated size wins, read with
  its qualifier ("at least 2,000", "under 1,500", "1,200-1,800 sq ft"). Otherwise the business's *concept*
  (coffee shop vs full-service vs fine dining, yoga studio vs full gym; business_types.yaml `program.concepts`)
  turns the stated count (seats, operatories, class size, members, employees) or its typical count into
  components: front-of-house per unit + fixed space, grossed up for kitchen/back of house, plus needs that take
  floor area (needs.yaml `adds_sqft`). The band comes from the concept's low / typical / high factors.
- `fit(size, ...)`: a 0-1 score for how well the most direct size evidence (a listed suite, an interior scan,
  the closest listed space, the building footprint) matches the band. Inside the band scores 1; too small falls
  off steeply (a space that can't hold the program is close to useless), too big falls off more gently (you pay
  for, or must subdivide, space you don't need). Discovery's pre-screen, the program's site check, the size_fit
  verdict and the Vexcel Agent's tool all read this one score.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from config import business, needs_registry
from schemas import Intent

MIN_BAND = (0.88, 1.15)  # the band is never narrower than this around the target
_SMALL = r"small|tiny|compact|cozy|intimate|little|hole[\s-]in[\s-]the[\s-]wall"
_LARGE = r"large|big|spacious|huge|flagship"
_SIZE_HINT_SCALE = {"small": 0.7, "large": 1.4}
_NUM = r"(\d[\d,]*(?:\.\d+)?)\s*(k)?"
_UNIT = r"\s*(?:sq\.?\s*ft\.?|sf\b|square\s*f(?:ee|oo)t|sqft|ft2|ft²)"


# ---------------------------------------------------------------- reading the request

def _num(value: str, k: str | None) -> int:
    return int(round(float(value.replace(",", "")) * (1000 if k else 1)))


def parse_size_request(query: str) -> tuple[int | None, int | None, int | None]:
    """(stated sq ft, lower bound, upper bound) from the query. "1,200-1,800 sq ft" -> (1500, 1200, 1800);
    "at least 2,000 sq ft" -> (2000, 2000, None); "under 1.5k sf" -> (1500, None, 1500); "2,400 sq ft" -> (2400, None, None)."""
    q = query.lower()
    # "and" only joins a range after "between" ("200 seats and 3,000 sq ft" is not a range)
    rng = re.search(rf"(?:between\s+{_NUM}\s*(?:{_UNIT})?\s*(?:and|-|–|to)|(?<![\d,.]){_NUM}\s*(?:{_UNIT})?\s*(?:-|–|to))\s*{_NUM}{_UNIT}", q)
    if rng:
        g = rng.groups()
        first, first_k = (g[0], g[1]) if g[0] else (g[2], g[3])
        lo, hi = sorted((_num(first, first_k or g[5]), _num(g[4], g[5])))
        if 100 <= lo < hi <= lo * 5:
            return round((lo + hi) / 2, -1), lo, hi
    one = re.search(rf"(?:(at\s+least|min(?:imum)?(?:\s+of)?|no\s+less\s+than|over|more\s+than)\s+|(under|below|less\s+than|up\s+to|max(?:imum)?(?:\s+of)?|no\s+more\s+than|at\s+most)\s+|~|about\s+|around\s+|roughly\s+)?{_NUM}\s*(\+)?{_UNIT}", q)
    if not one:
        return None, None, None
    sqft = _num(one.group(3), one.group(4))
    if sqft < 100:
        return None, None, None
    if one.group(1) or one.group(5):
        return sqft, sqft, None
    if one.group(2):
        return sqft, None, sqft
    return sqft, None, None


def parse_concept(query: str, business_type: str) -> str | None:
    """The business concept named in the query (earliest keyword wins, longest on ties), else None (the default)."""
    q = query.lower()
    hits = []
    for c in business(business_type)["program"].get("concepts", []):
        for kw in c.get("keywords", []):
            m = re.search(r"(?<![a-z])" + re.escape(kw.lower()).replace(r"\ ", r"[\s-]+") + r"(?![a-z])", q)
            if m:
                hits.append((m.start(), -len(kw), c["id"]))
    return min(hits)[2] if hits else None


def parse_size_hint(query: str) -> str | None:
    q = query.lower()
    if re.search(rf"\b(?:{_SMALL})\b", q):
        return "small"
    if re.search(rf"\b(?:{_LARGE})\b", q):
        return "large"
    return None


# ---------------------------------------------------------------- the estimate

def concept(business_type: str, concept_id: str | None) -> dict:
    concepts = business(business_type)["program"].get("concepts", [])
    return next((c for c in concepts if c["id"] == concept_id), None) or next((c for c in concepts if c.get("default")), None) or (concepts[0] if concepts else {})


def _counts(intent: Intent) -> dict[str, int]:
    return {**intent.occupancy, **({"seats": intent.seats} if intent.seats and "seats" not in intent.occupancy else {})}


def estimate(intent: Intent) -> dict:
    """{target_sqft, min_sqft, max_sqft, basis, concept, concept_label, components, source}. See the module docstring."""
    cfg = business(intent.business_type)
    prog = cfg["program"]
    c = concept(intent.business_type, intent.concept)
    counts = _counts(intent)
    label = c.get("label") or cfg["label"].lower()
    basis: list[str] = []
    components: list[dict] = []

    # 1. the program from counts (stated, or the concept's typical count)
    driver = next((d for d in prog["drivers"] if counts.get(d["field"])), None)
    stated_count = driver is not None
    if not driver:
        for d in prog["drivers"]:
            if (c.get("default_count") or {}).get(d["field"]):
                driver = d
                break
    derived = None  # (low, typical, high)
    if driver:
        fld = driver["field"]
        n = counts.get(fld) or c["default_count"][fld]
        scaled = ""
        if not stated_count and intent.size_hint:
            n = max(1, round(n * _SIZE_HINT_SCALE[intent.size_hint]))
            scaled = f" ({intent.size_hint})"
        per = (c.get("sqft_per") or {}).get(fld) or [driver["sqft_each"]] * 3
        base = c.get("base_sqft", driver.get("base_sqft", 0))
        boh = c.get("back_of_house_share", 0)
        unit = c.get("unit_label") or driver["label"]
        front = [n * f + base for f in per]
        derived = tuple(f / (1 - boh) for f in front)
        how = "you said" if stated_count else f"typical {label}{scaled}"
        components.append({"label": f"{n} {unit} × {per[1]} sq ft", "sqft": n * per[1]})
        if base:
            components.append({"label": c.get("base_label") or "fixed space (entry, counter, office)", "sqft": base})
        if boh:
            components.append({"label": f"kitchen, storage and restrooms ({boh:.0%} of the total)", "sqft": round(derived[1] - front[1])})
        basis.append(f"{n} {unit} ({how}) × {per[0]}-{per[2]} sq ft each" + (f" + {base:,} sq ft {c.get('base_label') or 'fixed space'}" if base else "")
                     + (f", grossed up for {boh:.0%} kitchen and back of house" if boh else "") + f" ≈ {round(derived[1], -1):,.0f} sq ft")
        if c.get("why"):
            basis.append(c["why"])
    elif c.get("default_sqft"):
        lo, typ, hi = c["default_sqft"]
        k = _SIZE_HINT_SCALE.get(intent.size_hint or "", 1)
        derived = (lo * k, typ * k, hi * k)
        basis.append(f"No size given: a typical {label}{' (' + intent.size_hint + ')' if intent.size_hint else ''} is {round(derived[0], -2):,.0f}-{round(derived[2], -2):,.0f} sq ft" + (f" ({c['why']})" if c.get("why") else ""))
        components.append({"label": f"typical {label}", "sqft": round(typ * k)})
    else:
        d = cfg["sizing"].get("default_sqft", 2500)
        derived = (d * 0.8, d, d * 1.3)
        basis.append(f"No size given: typical {cfg['label'].lower()} (~{d:,} sq ft)")

    # 2. needs that take floor area (a full bar, storage, private rooms...)
    registry = needs_registry()
    extra = 0
    for need in intent.needs:
        add = (registry.get(need.id, {}).get("adds_sqft") or {})
        sq = add.get(intent.business_type, add.get("default")) if isinstance(add, dict) else add
        if sq:
            extra += sq
            components.append({"label": need.label.lower(), "sqft": sq})
            basis.append(f"+ {sq:,} sq ft for {need.label.lower()}")
    derived = tuple(v + extra for v in derived)

    # 3. a stated size wins, read with its qualifier
    if intent.sqft or intent.sqft_min or intent.sqft_max:
        lo_s, hi_s = intent.sqft_min, intent.sqft_max
        if not stated_count:
            basis = []  # the typical-size guess no longer applies
        if lo_s and hi_s:
            target, lo, hi = intent.sqft or (lo_s + hi_s) / 2, lo_s, hi_s
            basis.insert(0, f"{lo_s:,}-{hi_s:,} sq ft requested")
        elif lo_s:
            target, lo, hi = lo_s * 1.1, lo_s, lo_s * 1.4
            basis.insert(0, f"At least {lo_s:,} sq ft requested")
        elif hi_s:
            target, lo, hi = hi_s * 0.85, hi_s * 0.6, hi_s
            basis.insert(0, f"Up to {hi_s:,} sq ft requested")
        else:
            target, lo, hi = intent.sqft, intent.sqft * 0.85, intent.sqft * 1.2
            basis.insert(0, f"{intent.sqft:,} sq ft requested")
        if stated_count and abs(derived[1] - target) / target > 0.25:
            basis.append(f"Note: your headcount suggests ~{round(derived[1], -1):,.0f} sq ft, {'more' if derived[1] > target else 'less'} than the size you asked for.")
        # the stated size is the program; a headcount estimate stays in the basis only as a cross-check
        components = [{"label": "the size you asked for", "sqft": int(round(target, -1))}]
        source = "stated"
    else:
        lo, target, hi = derived
        source = "derived" if stated_count else "default"
        if source == "default":  # no count given: the typical size is a guess, so accept a wider band
            lo, hi = lo * 0.9, hi * 1.15

    lo, hi = min(lo, target * MIN_BAND[0]), max(hi, target * MIN_BAND[1])
    lo, hi = intent.sqft_min or lo, intent.sqft_max or hi  # a bound the user set is exact
    return {
        "target_sqft": int(round(target, -1)), "min_sqft": intent.sqft_min or int(round(lo, -1)), "max_sqft": intent.sqft_max or int(round(hi, -1)),
        "basis": basis, "concept": c.get("id"), "concept_label": label, "components": components, "source": source,
    }


# ---------------------------------------------------------------- the fit

TOO_SMALL_ZERO = 0.65  # at 65% of the minimum a space scores 0
TOO_BIG_SLOPE = 0.45  # score lost per doubling above the maximum
STRONG, ADEQUATE = 0.85, 0.5


def band_score(area: float, lo: float, hi: float) -> float:
    """1 inside [lo, hi]; linear to 0 at 65% of lo below it; minus 0.45 per doubling above hi (floor 0.05)."""
    if area <= 0:
        return 0.0
    if area < lo:
        return max(0.0, (area / lo - TOO_SMALL_ZERO) / (1 - TOO_SMALL_ZERO))
    if area > hi:
        return max(0.05, 1 - TOO_BIG_SLOPE * math.log2(area / hi))
    return 1.0


@dataclass(frozen=True)
class SizeFit:
    score: float  # 0-1
    status: str  # strong | adequate | weak (size_fit metric vocabulary)
    reason: str
    data: dict = field(default_factory=dict)

    @property
    def check(self) -> str:
        """pass | risk for the program's site checks."""
        return "pass" if self.score >= STRONG else "risk"


def _status(score: float) -> str:
    return "strong" if score >= STRONG else "adequate" if score >= ADEQUATE else "weak"


def _relation(area: float, lo: int, hi: int, target: int) -> str:
    if area < lo:
        return f"{area / target:.0%} of the ~{target:,} sq ft you need"
    if area > hi:
        return f"{area / target:.1f}x the ~{target:,} sq ft you need"
    return f"inside your {lo:,}-{hi:,} sq ft range"


def fit(size: dict, *, best_space: dict | None = None, closest_space_sqft: float | None = None, space_count: int = 0,
        available_sqft: float | None = None, interior_sqft: float | None = None, footprint_sqft: float | None = None,
        stories: int | None = None, ground_floor_required: bool = False) -> SizeFit | None:
    """Grade the most direct size evidence against the program's band. None when no size evidence exists."""
    target, lo, hi = size["target_sqft"], size["min_sqft"], size["max_sqft"]
    rng = [lo, hi]
    if best_space and best_space.get("sqft"):
        sq = best_space["sqft"]
        low = best_space.get("sqft_min") or sq
        effective = min(max(target, low), sq) if low < sq else sq  # a divisible listing can be leased at your size
        score = band_score(effective, lo, hi)
        suite = f"Suite {best_space['suite']}" if best_space.get("suite") else "The listed space"
        size_txt = f"{low:,.0f}-{sq:,.0f}" if low < sq else f"{sq:,.0f}"
        return SizeFit(score, _status(score), f"{suite} is {size_txt} rentable sq ft, {_relation(effective, lo, hi, target)} (CoStar listing).",
                       {"basis": "costar_listing", "sqft": sq, "sqft_min": low if low < sq else None, "range": rng})
    if interior_sqft:
        score = band_score(interior_sqft, lo, hi)
        return SizeFit(score, _status(score), f"The interior scan measures {interior_sqft:,.0f} sq ft, {_relation(interior_sqft, lo, hi, target)}.",
                       {"basis": "interior_scan", "sqft": round(interior_sqft), "ratio": round(interior_sqft / target, 2), "range": rng})
    if space_count:
        avail = available_sqft or 0
        if closest_space_sqft:
            score = min(band_score(closest_space_sqft, lo, hi), 0.8)  # outside the range by definition (else it'd be best_space)
            return SizeFit(score, _status(score), f"CoStar lists {space_count} space(s) here; the closest to your size is {closest_space_sqft:,.0f} sq ft, {_relation(closest_space_sqft, lo, hi, target)}.",
                           {"basis": "costar_spaces", "spaces": space_count, "closest_sqft": closest_space_sqft, "available_sqft": avail, "range": rng})
        score = 0.5 if avail >= lo else band_score(avail, lo, hi) * 0.8
        return SizeFit(score, _status(score), f"CoStar lists {space_count} space(s) ({avail:,.0f} sq ft in total), none in your {lo:,}-{hi:,} sq ft range" + ("; spaces may be combined or divided." if avail >= lo else "."),
                       {"basis": "costar_spaces", "spaces": space_count, "available_sqft": avail, "range": rng})
    if footprint_sqft:
        st = stories or 1
        data = {"basis": "footprint", "footprint_sqft": round(footprint_sqft), "stories": st, "ratio": round(footprint_sqft / target, 2), "range": rng}
        score = band_score(footprint_sqft, lo, hi)
        if footprint_sqft < lo and st > 1 and footprint_sqft * st >= lo:
            score = 0.3 if ground_floor_required else 0.55
            return SizeFit(score, _status(score), f"Only {footprint_sqft:,.0f} sq ft per floor: ~{target:,} sq ft would span {math.ceil(target / footprint_sqft)} floors" + (", but this use needs one street-level floor." if ground_floor_required else "."), data)
        if footprint_sqft > hi:
            return SizeFit(score, _status(score), f"The {footprint_sqft:,.0f} sq ft building is {footprint_sqft / target:.1f}x the ~{target:,} sq ft you need, and no suite your size is listed: you would pay for extra space or need the owner to divide it.", data)
        return SizeFit(score, _status(score), f"The {footprint_sqft:,.0f} sq ft ground floor is {_relation(footprint_sqft, lo, hi, target)}.", data)
    return None
