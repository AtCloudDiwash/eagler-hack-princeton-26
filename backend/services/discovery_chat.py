"""Read-only map questions, independent of editing a property's search requirements.

Every map question is classified into one interaction type. Each type has one predictable response and map action:

  find_nearby          "show cafés around here"         -> pins + short list
  find_nearest         "where's the closest parking?"   -> one highlighted place + distance; it becomes the anchor
  find_by_description  "find roofs with solar panels"   -> Vexcel imagery areas
  explore_surroundings "what's around this street?"     -> everything nearby, grouped by category
  inspect              "what is that?", "the second one" -> the referenced place, focused, as the new anchor
  adjust_results       "only cafés", "look farther"      -> narrows/widens the current results
  control_view         "zoom out", "aerial", "3D"         -> camera/layer change
  back                 "go back", "back to the cafés"    -> client restores the previous map state

Follow-ups resolve against the client's MapContext: the anchor ("around it", "near there"), the radius and the
places currently shown ("which is closest?", "the second one").
"""
from __future__ import annotations

import asyncio
import re

import httpx

import db
from config import business, place_groups
from schemas import MapContext, RefineRequest, RefineResponse
from services import external, vexcel
from services.geo import haversine_m

# Terms identify the kind of factual place lookup; the data source supplies the actual results.
PLACE_TERMS = {
    'food_drink': r'restaurants?|caf[eé]s?|coffee(?: shops?)?|bars?|food',
    'dental_medical': r'dentists?|dental|clinics?|hospitals?|pharmac(?:y|ies)|medical|doctors?',
    'fitness': r'gyms?|fitness', 'transit': r'transit|bus(?: stops?)?|trains?|rail|stations?|metro',
    'parking': r'parking|garages?', 'offices': r'offices?', 'lodging': r'hotels?|lodging|museums?|attractions?',
    'education': r'schools?|universit(?:y|ies)|colleges?|librar(?:y|ies)',
    'entertainment': r'theaters?|theatres?|cinemas?|venues?|stadiums?',
    'retail': r'shops?|retail|stores?', 'residential_services': r'parks?|banks?|fuel|gas stations?|community',
}
# A nearest café/pharmacy/bus stop is narrower than its parent map category.
SUBTYPES = [
    (r'caf[eé]|coffee', 'food_drink', {'amenity=cafe'}),
    (r'restaurant', 'food_drink', {'amenity=restaurant', 'amenity=fast_food', 'amenity=food_court'}),
    (r'\bbars?\b', 'food_drink', {'amenity=bar', 'amenity=pub'}),
    (r'pharmac', 'dental_medical', {'amenity=pharmacy'}),
    (r'hospital', 'dental_medical', {'amenity=hospital', 'healthcare=hospital'}),
    (r'clinic', 'dental_medical', {'amenity=clinic', 'healthcare=clinic'}),
    (r'dentist|dental', 'dental_medical', {'amenity=dentist', 'healthcare=dentist'}),
    (r'bus', 'transit', {'highway=bus_stop'}),
    (r'train|rail|metro', 'transit', {'railway=station', 'railway=halt', 'railway=tram_stop'}),
    (r'\bparks?\b', 'residential_services', {'leisure=park'}),
    (r'bank', 'residential_services', {'amenity=bank'}),
]
SPATIAL = re.compile(r'\b(where|which|who|nearest|closest|nearby|around|show|find|highlight|locate|map|hide|pan|move|any)\b', re.I)
VISUAL = re.compile(r'\b(buildings?|properties|warehouses?|roofs?|patios?|drive[ -]?thr\w*|loading docks?|pools?|solar panels?|outdoor seating|courtyards?|vacant lots?)\b', re.I)
ORDINALS = {'first': 0, '1st': 0, 'second': 1, '2nd': 1, 'third': 2, '3rd': 2, 'fourth': 3, '4th': 3, 'fifth': 4, '5th': 4}
DEICTIC = r'\b(?:it|there|that(?: one| place)?|this(?: one| place)?|them|those)\b'
MAX_RADIUS = external.PLACES_RADIUS_M


def _response(reply: str, interaction: str | None = None, suggestions: list[str] | None = None, **action) -> RefineResponse:
    if action:
        action['interaction'] = interaction
        if suggestions:
            action['suggestions'] = suggestions
    return RefineResponse(action='map' if action else 'answer', reply=reply, map_action=action or None)


def _label(gid: str) -> str:
    return place_groups().get(gid, {}).get('label', gid.replace('_', ' '))


def _place_name(p: dict) -> str:
    return p.get('name') or p.get('brand') or _label(p['group'])


def _fmt_m(m: int) -> str:
    return f'{m / 1000:.1f} km' if m >= 1000 else f'{m:,} m'


def _anchor(p: dict) -> dict:
    return {'kind': 'place', 'id': p.get('id'), 'label': _place_name(p), 'lat': p['lat'], 'lon': p['lon']}


def _groups_in(q: str) -> list[str]:
    return [gid for gid, pattern in PLACE_TERMS.items() if re.search(rf'\b(?:{pattern})\b', q)]


def _narrow(places: list[dict], q: str) -> list[dict]:
    categories: dict[str, set[str]] = {}
    for pattern, group, allowed in SUBTYPES:
        if re.search(pattern, q):
            categories.setdefault(group, set()).update(allowed)
    return [p for p in places if p['group'] not in categories or p.get('category') in categories[p['group']]]


def _origin(req: RefineRequest, ctx: MapContext, q: str) -> tuple[dict | None, str]:
    """Where "nearby" means: the anchor when the user points at it (or it is a clicked place), else the building."""
    if ctx.anchor and (ctx.anchor.kind != 'view' or not req.property_id):
        return {'lat': ctx.anchor.lat, 'lon': ctx.anchor.lon}, ctx.anchor.label
    if req.property_id:
        stored = db.get_property(req.property_id)
        if stored:
            return {k: stored[0][k] for k in ('lat', 'lon')}, 'the selected building'
    if req.center:
        return req.center.model_dump(), 'the map view'
    return None, ''


def _control_view(q: str, req: RefineRequest) -> RefineResponse | None:
    if re.search(r'\bzoom\s+(?:in|out)\b|\bcloser look\b', q):
        delta = -1 if re.search(r'\bzoom\s+out\b', q) else 1
        return _response('Zoomed out.' if delta < 0 else 'Zoomed in.', 'control_view', kind='zoom', zoom_delta=delta)
    if re.search(r'\b(?:show|switch|use|change|turn)\b.*\b(?:satellite|aerial|street|map)\s*(?:view|layer|imagery)?\b', q) and re.search(r'satellite|aerial|street map|street view|map view|map layer', q):
        aerial = bool(re.search(r'satellite|aerial', q))
        return _response('Showing aerial imagery.' if aerial else 'Showing the street map.', 'control_view', kind='layer', layer='aerial' if aerial else 'map')
    if re.search(r'\b(?:2d|3d)\b', q) and re.search(r'\b(?:show|switch|use|turn|view|map|go)\b', q):
        tilt = '3d' in q
        return _response('Showing the 3D view.' if tilt else 'Showing the 2D view.', 'control_view', kind='tilt', tilt=tilt)
    if re.search(r'\b(?:reset map|show all (?:results|buildings|matches)|fit (?:the )?(?:map|results))\b', q):
        return _response('Showing all search results.', 'control_view', kind='fit')
    if re.search(r'\b(?:hide|clear|remove)\b.*\b(?:competitors?|places|pins|markers|highlights|search areas|results)\b', q):
        return _response('Cleared the map highlights.', 'control_view', kind='clear')
    return None


def _ordinal(q: str, ctx: MapContext) -> dict | None:
    if not ctx.places:
        return None
    m = re.search(r'\b(first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|last)\b(?:\s+(?:one|place|result|pin))?', q)
    if not m:
        return None
    i = len(ctx.places) - 1 if m.group(1) == 'last' else ORDINALS[m.group(1)]
    return ctx.places[i] if i < len(ctx.places) else None


def _summary(places: list[dict]) -> list[dict]:
    counts: dict[str, int] = {}
    for p in places:
        counts[p['group']] = counts.get(p['group'], 0) + 1
    return [{'group': g, 'label': _label(g), 'count': n} for g, n in sorted(counts.items(), key=lambda kv: -kv[1])]


async def respond(req: RefineRequest) -> RefineResponse | None:
    """None means the request belongs to the existing refinement/conversation path."""
    text = req.message.strip()
    q = text.lower().replace('’', "'")
    ctx = req.map_context or MapContext()
    if re.search(r'\bbudget\b|\d+\s*(?:seats?|sq\s*ft|sqft|sf)\b', q):
        return None

    # ---- back: the client owns the history of map states
    if re.fullmatch(r"(?:go |take me )?back(?: to (?:the )?.+)?[.!]*|undo(?: that)?[.!]*|previous (?:results|view)[.!]*", q):
        return _response('Back to the previous map view.', 'back', kind='back')

    # ---- control the view
    view = _control_view(q, req)
    if view:
        return view
    pan = re.search(r"\b(?:pan|move|look)\s+(?:the map\s+)?(north|south|east|west)\b", q)

    # ---- inspect a referenced place: "the second one", "tell me about it"
    picked = _ordinal(q, ctx)
    asks_about_anchor = bool(re.search(rf"\b(?:what(?:'s| is)|tell me (?:more )?about|more about|details (?:on|about)|info(?:rmation)? (?:on|about))\s+{DEICTIC}", q))
    if picked or (asks_about_anchor and ctx.anchor and ctx.anchor.kind == 'place' and not re.search(r'\baround\b|\bnear\b', q)):
        if picked is None:
            picked = next((p for p in ctx.places if p.get('id') == ctx.anchor.id), None) or {
                'id': ctx.anchor.id, 'name': ctx.anchor.label, 'group': '', 'lat': ctx.anchor.lat, 'lon': ctx.anchor.lon}
        origin, _ = _origin(req.model_copy(update={'map_context': None}), MapContext(), q)
        dist = f", {_fmt_m(round(haversine_m(origin['lat'], origin['lon'], picked['lat'], picked['lon'])))} from the building" if origin and req.property_id else ''
        kind = f" ({_label(picked['group'])})" if picked.get('group') else ''
        return _response(
            f"{_place_name(picked) if picked.get('group') else picked.get('name')}{kind}{dist}. I've centered the map on it; ask what's around it or find something near it.",
            'inspect', ["What's around it?", 'Where is the nearest parking?', 'Back'],
            kind='focus', focus={'lat': picked['lat'], 'lon': picked['lon']}, anchor=_anchor(picked) if picked.get('group') else ctx.anchor.model_dump(),
        )

    # ---- adjust current results: "only cafés", "look farther", "within 300 m"
    farther = re.search(r'\b(?:look |search )?(?:farther|further|wider|expand|bigger area|more area)\b', q)
    closer = re.search(r'\b(?:closer|narrower|tighter|smaller area|walking distance)\b', q) and not re.search(r'closest', q)
    within = re.search(r'\bwithin\s+(\d+(?:\.\d+)?)\s*(m|meters?|metres?|km|kilometers?|kilometres?|mi|miles?|min(?:ute)?s?(?: walk)?)\b', q)
    only = re.match(r'(?:only|just)\s+(?:show\s+)?(.+?)[.!?]*$', q)
    radius = ctx.radius_m
    if within:
        n, unit = float(within.group(1)), within.group(2)
        radius = round(n * (1000 if unit.startswith('k') else 1609 if unit.startswith('mi') and not unit.startswith('min') else 80 if unit.startswith('min') else 1))
    elif farther:
        radius = min(MAX_RADIUS, (ctx.radius_m or 500) * 2)
    elif closer:
        radius = max(100, (ctx.radius_m or MAX_RADIUS) // 2)
    radius = min(MAX_RADIUS, radius) if radius else None
    adjusting = bool(within or farther or closer or only)
    if farther and ctx.radius_m in (None, MAX_RADIUS):
        return _response(f'Already showing everything mapped within {_fmt_m(MAX_RADIUS)}. Move the anchor or the map to look elsewhere.',
                         'adjust_results', ['Zoom out', 'Back'], kind='radius', radius_m=MAX_RADIUS)

    competitors = bool(re.search(r'\bcompetitor\w*|\bcompetition\b', q))
    groups = business(req.intent.business_type).get('place_roles', {}).get('competitors', []) if competitors else _groups_in(q)
    explore = bool(re.search(r"\bwhat(?:'s| is| else is)\s+(?:around|nearby|near|close)|\bsurround\w*|\bneighbou?rhood\b|\barea (?:like|around)\b|\bwhat(?:'s| is) (?:here|nearby)\b|\bexplore\b|\bwhat is nearby\b|\bwhat's nearby\b", q))
    nearest = bool(re.search(r'\bnearest|\bclosest', q))
    visual = bool(VISUAL.search(q)) and not competitors and (not groups or bool(re.search(r'\b(?:with|that have|having)\b', q)))
    general_nearby = bool(re.search(r"\bnearby\b|\b(?:near|around) (?:me|here|this|that|it|there|the (?:property|building))\b", q))
    named = re.search(r'(?:nearest|closest|where (?:is|are)(?: the)?|find|locate|show me)\s+(.+?)(?:\s+(?:near|around|to|from)\b.*)?[?.!]*$', q)

    named_term = re.sub(DEICTIC, '', named.group(1)).strip(' ?.').removeprefix('the ').strip() if named else ''
    named_term = re.sub(r'^(?:one|ones|place|places|pin|pins|of (?:them|these|those)|(?:of )?these|(?:of )?those)$', '', named_term)
    similar = re.search(r'\b(?:others?|more|ones) like (?:it|this|that)\b|\bsimilar (?:places|ones)\b', q)

    # "Which is closest?" about the places already shown: no new lookup.
    if nearest and not groups and not visual and ctx.places and not named_term:
        origin, origin_label = _origin(req, ctx, q)
        if origin:
            ranked = sorted(ctx.places, key=lambda p: haversine_m(origin['lat'], origin['lon'], p['lat'], p['lon']))
            best = ranked[0]
            d = round(haversine_m(origin['lat'], origin['lon'], best['lat'], best['lon']))
            return _response(
                f'{_place_name(best)} is the closest of these, {_fmt_m(d)} from {origin_label} (straight-line).',
                'find_nearest', ["What's around it?", 'Tell me about it', 'Back'],
                kind='places', places=[{**best, 'distance_m': d}], groups=[best['group']], focus={'lat': best['lat'], 'lon': best['lon']}, anchor=_anchor(best),
            )

    # "Show others like it": same category as the anchored place, around the building rather than the place itself.
    like = None
    if similar and ctx.anchor and ctx.anchor.kind == 'place':
        like = next((p for p in ctx.places if p.get('id') == ctx.anchor.id), None)
        if like:
            groups = [like['group']]
            ctx = ctx.model_copy(update={'anchor': None})

    if adjusting and not groups and not explore and ctx.places:
        # Re-run the previous lookup's groups with the new radius (only/just X handled below via groups).
        groups = list(dict.fromkeys(p['group'] for p in ctx.places))
    if only and not groups:
        return _response("Which kind of place should I keep? For example: 'only cafés' or 'only parking'.", 'adjust_results')

    if not (SPATIAL.search(q) or explore or adjusting or pan or like or re.search(r"\b(?:competitors?|competition)\b.*\?", q)):
        return None
    if not groups and not visual and not nearest and not named_term and not pan and not general_nearby and not explore and not adjusting:
        return None

    center, origin_label = _origin(req, ctx, q)
    if not center:
        return _response('Choose a building or search an area first, then ask what is nearby.')
    lat, lon = center['lat'], center['lon']
    if pan:
        direction = pan.group(1)
        step = {'north': (0.003, 0), 'south': (-0.003, 0), 'east': (0, 0.003), 'west': (0, -0.003)}[direction]
        return _response(f'Moved the map {direction}.', 'control_view', kind='focus', focus={'lat': lat + step[0], 'lon': lon + step[1]})

    if visual:
        try:
            areas = await asyncio.wait_for(vexcel.semantic_search(text, lat, lon), timeout=25)
        except (vexcel.VexcelError, httpx.HTTPError, ValueError, asyncio.TimeoutError):
            return _response('Visual search is unavailable for this area right now. Try again, or ask for a nearby business by name or type.')
        if not areas['features']:
            return _response('No matching imagery areas were returned here. Try a different description or area.')
        return _response(f"Highlighted {len(areas['features'])} visually similar areas from Vexcel. These are imagery matches; the feature, availability and exact property still need verification.",
                         'find_by_description', ['Zoom in', 'Show aerial imagery', 'Clear highlights'], kind='areas', areas=areas)

    try:
        places = await asyncio.wait_for(external.nearby_places(lat, lon), timeout=25)
    except (httpx.HTTPError, ValueError, RuntimeError, asyncio.TimeoutError):
        return _response('Nearby-place data is unavailable right now. Try again; your property requirements are unchanged.')
    places = [{**p, 'distance_m': round(haversine_m(lat, lon, p['lat'], p['lon']))} for p in places]
    if ctx.anchor and ctx.anchor.kind == 'place':  # "around it" means other places, not the anchor itself
        places = [p for p in places if p.get('id') != ctx.anchor.id]
    if radius:
        places = [p for p in places if p['distance_m'] <= radius]
    places.sort(key=lambda p: p['distance_m'])
    within_txt = f' within {_fmt_m(radius)}' if radius else ''
    around = f' around {origin_label}' if ctx.anchor and ctx.anchor.kind == 'place' else ''

    # ---- explore surroundings: everything, grouped
    if explore and not groups and not nearest:
        if not places:
            return _response(f'No mapped places were found{within_txt}{around}. Try looking farther.', 'explore_surroundings', ['Look farther'])
        summary = _summary(places)
        top = ', '.join(f"{s['count']} {s['label'].lower()}" for s in summary[:4])
        return _response(
            f"Around {origin_label}{within_txt}: {top}. The closest is {_place_name(places[0])} ({_fmt_m(places[0]['distance_m'])}). Mapped businesses may be incomplete.",
            'explore_surroundings', [f"Only {summary[0]['label'].lower()}", 'Where is the nearest transit?', 'Look farther' if radius and radius < MAX_RADIUS else 'Zoom out'],
            kind='places', places=places[:60], groups=[s['group'] for s in summary], summary=summary, radius_m=radius,
        )

    if groups:
        places = [p for p in places if p['group'] in groups]
        if like and like.get('category'):
            places = [p for p in places if p.get('category') == like['category']]
        elif not competitors:
            places = _narrow(places, q)
    elif named_term and not general_nearby:
        places = [p for p in places if named_term in str(p.get('name') or '').lower() or named_term in str(p.get('brand') or '').lower()]
    elif not general_nearby and not adjusting:
        return _response('What would you like to find nearby? For example: the nearest cafe, pharmacy, parking or a business name.', 'find_nearby')
    if not places:
        return _response(f'No matching mapped places were found{within_txt or " within 1.5 km"}{around}. This does not prove none exist; try looking farther or a different name.',
                         'find_nearby', ['Look farther'] if radius and radius < MAX_RADIUS else ['What is around here?'])

    shown = places[:1] if nearest else places[:30]
    groups = list(dict.fromkeys(p['group'] for p in shown))
    names = ', '.join(f"{_place_name(p)} ({_fmt_m(p['distance_m'])})" for p in shown[:3])
    tail = ' Distances are straight-line; mapped businesses may be incomplete.'
    if nearest:
        best = shown[0]
        return _response(f'The nearest mapped match{around} is {names}.' + tail, 'find_nearest', ["What's around it?", 'Show others like it', 'Back'],
                         kind='places', places=shown, groups=groups, focus={'lat': best['lat'], 'lon': best['lon']}, anchor=_anchor(best), radius_m=radius)
    what = 'potential competitors' if competitors else 'nearby places' if not groups or len(groups) > 1 else _label(groups[0]).lower()
    interaction = 'adjust_results' if adjusting else 'find_nearby'
    return _response(f'Showing {len(shown)} mapped {what}{around}{within_txt}: {names}.' + tail, interaction,
                     ['Which is closest?', 'Look farther' if radius and radius < MAX_RADIUS else 'Look closer', 'Tell me about the first one'],
                     kind='places', places=shown, groups=groups, radius_m=radius)
