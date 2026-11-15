"""Read-only map/nearby actions, independent of editing a property's search requirements."""
from __future__ import annotations

import asyncio
import re

import httpx

import db
from config import business, place_groups
from schemas import RefineRequest, RefineResponse
from services import external, vexcel
from services.geo import haversine_m

# Terms identify the kind of factual place lookup; the data source supplies the actual results.
PLACE_TERMS = {
    'food_drink': r'restaurants?|caf[eé]s?|coffee shops?|bars?',
    'dental_medical': r'dentists?|dental|clinics?|hospitals?|pharmac(?:y|ies)|medical',
    'fitness': r'gyms?|fitness', 'transit': r'transit|bus stops?|train|rail|stations?',
    'parking': r'parking|garages?', 'offices': r'offices?', 'lodging': r'hotels?|lodging',
    'education': r'schools?|universit(?:y|ies)|colleges?|libraries',
    'entertainment': r'theaters?|theatres?|cinemas?|venues?',
    'retail': r'shops?|retail|stores?', 'residential_services': r'parks?|banks?|fuel|community',
}
SPATIAL = re.compile(r'\b(where|which|who|nearest|closest|nearby|around|show|find|highlight|locate|map|hide|pan|move)\b', re.I)
VISUAL = re.compile(r'\b(buildings?|properties|warehouses?|roofs?|patios?|drive[ -]?thr\w*|loading docks?|pools?|solar panels?|outdoor seating)\b', re.I)


def _response(reply: str, **action) -> RefineResponse:
    return RefineResponse(action='map' if action else 'answer', reply=reply, map_action=action or None)


async def respond(req: RefineRequest) -> RefineResponse | None:
    """None means the request belongs to the existing refinement/conversation path."""
    text = req.message.strip()
    q = text.lower().replace('’', "'")
    if re.search(r'\bbudget\b|\d+\s*(?:seats?|sq\s*ft|sqft|sf)\b', q):
        return None
    if re.search(r'\bzoom\s+(?:in|out)\b', q):
        delta = -1 if re.search(r'\bzoom\s+out\b', q) else 1
        return _response('Zoomed out.' if delta < 0 else 'Zoomed in.', kind='zoom', zoom_delta=delta)
    if re.search(r'\b(?:show|switch|use|change|turn)\b.*\b(?:satellite|aerial|street|map)\s*(?:view|layer)\b', q):
        aerial = bool(re.search(r'satellite|aerial', q))
        return _response('Showing aerial imagery.' if aerial else 'Showing the street map.', kind='layer', layer='aerial' if aerial else 'map')
    if re.search(r'\b(?:2d|3d)\b', q) and re.search(r'\b(?:show|switch|use|turn|view|map)\b', q):
        tilt = '3d' in q
        return _response('Showing the 3D view.' if tilt else 'Showing the 2D view.', kind='tilt', tilt=tilt)
    if re.search(r'\b(?:reset map|show all (?:results|buildings)|fit (?:the )?(?:map|results))\b', q):
        return _response('Showing all search results.', kind='fit')
    if re.search(r'\b(?:hide|clear|remove)\b.*\b(?:competitors?|places|markers|highlights|search areas)\b', q):
        return _response('Cleared the map highlights.', kind='clear')
    if not SPATIAL.search(q) and not re.search(r"\b(?:competitors?|competition)\b.*\?", q):
        return None

    groups = [gid for gid, pattern in PLACE_TERMS.items() if re.search(rf'\b(?:{pattern})\b', q)]
    competitors = bool(re.search(r'\bcompetitor\w*|\bcompetition\b', q))
    if competitors:
        groups = business(req.intent.business_type).get('place_roles', {}).get('competitors', [])
    visual = bool(VISUAL.search(q)) and not competitors and (not groups or bool(re.search(r'\b(?:with|that have)\b', q)))
    general_nearby = bool(re.search(r"\bnearby\b|\b(?:near|around) (?:me|here|this|the (?:property|building))\b", q))
    nearest = bool(re.search(r'\bnearest|\bclosest', q))
    named = re.search(r'(?:nearest|closest|where (?:is|are)(?: the)?|find|locate|show me)\s+(.+?)(?:\s+(?:near|around|to|from)\b.*)?[?.!]*$', q)
    pan = re.search(r"\b(?:pan|move)\s+(?:the map\s+)?(north|south|east|west)\b", q)
    if not groups and not visual and not nearest and not named and not pan and not general_nearby:
        return None

    center = req.center.model_dump() if req.center else None
    if req.property_id:
        stored = db.get_property(req.property_id)
        if stored:
            center = {k: stored[0][k] for k in ('lat', 'lon')}
    if not center:
        return _response('Choose a building or search an area first, then ask what is nearby.')
    lat, lon = center['lat'], center['lon']
    if pan:
        direction = pan.group(1)
        return _response(f'Moved the map {direction}.', kind='focus', focus={'lat': lat + (0.003 if direction == 'north' else -0.003 if direction == 'south' else 0), 'lon': lon + (0.003 if direction == 'east' else -0.003 if direction == 'west' else 0)})

    if visual:
        try:
            areas = await asyncio.wait_for(vexcel.semantic_search(text, lat, lon), timeout=25)
        except (vexcel.VexcelError, httpx.HTTPError, ValueError, asyncio.TimeoutError):
            return _response('Visual search is unavailable for this area right now. Try again, or ask for a nearby business by name or type.')
        if not areas['features']:
            return _response('No matching imagery areas were returned here. Try a different description or area.')
        return _response(f"Highlighted {len(areas['features'])} visually similar areas from Vexcel. These are imagery matches; the feature, availability and exact property still need verification.", kind='areas', areas=areas)

    try:
        places = await asyncio.wait_for(external.nearby_places(lat, lon), timeout=25)
    except (httpx.HTTPError, ValueError, RuntimeError, asyncio.TimeoutError):
        return _response('Nearby-place data is unavailable right now. Try again; your property requirements are unchanged.')
    if groups:
        places = [p for p in places if p['group'] in groups]
        # A nearest cafe/pharmacy/bus stop is narrower than its parent map category.
        subtypes = [
            (r'caf[eé]|coffee', 'food_drink', {'amenity=cafe'}),
            (r'restaurant', 'food_drink', {'amenity=restaurant', 'amenity=fast_food', 'amenity=food_court'}),
            (r'pharmac', 'dental_medical', {'amenity=pharmacy'}),
            (r'hospital', 'dental_medical', {'amenity=hospital', 'healthcare=hospital'}),
            (r'clinic', 'dental_medical', {'amenity=clinic', 'healthcare=clinic'}),
            (r'dentist|dental', 'dental_medical', {'amenity=dentist', 'healthcare=dentist'}),
            (r'bus stop', 'transit', {'highway=bus_stop'}),
            (r'train|rail', 'transit', {'railway=station', 'railway=halt', 'railway=tram_stop'}),
            (r'\bpark\b|\bparks\b', 'residential_services', {'leisure=park'}),
            (r'bank', 'residential_services', {'amenity=bank'}),
        ]
        categories: dict[str, set[str]] = {}
        if not competitors:
            for pattern, group, allowed in subtypes:
                if re.search(pattern, q):
                    categories.setdefault(group, set()).update(allowed)
            places = [p for p in places if p['group'] not in categories or p.get('category') in categories[p['group']]]
    elif named and not general_nearby:
        term = named.group(1).strip(' ?.').removeprefix('the ')
        places = [p for p in places if term in str(p.get('name') or '').lower() or term in str(p.get('brand') or '').lower()]
    elif not general_nearby:
        return _response('What would you like to find nearby? For example: the nearest cafe, pharmacy, parking or a business name.')
    places = [{**p, 'distance_m': round(haversine_m(lat, lon, p['lat'], p['lon']))} for p in places]
    places.sort(key=lambda p: p['distance_m'])
    if not places:
        return _response('No matching mapped places were found within 1.5 km. This does not prove none exist; try another area or a different name.')
    shown = places[:1] if nearest else places[:30]
    groups = list(dict.fromkeys(p['group'] for p in shown))
    labels = place_groups()
    names = ', '.join(f"{p.get('name') or labels.get(p['group'], {}).get('label', 'Mapped place')} ({p['distance_m']:,} m)" for p in shown[:3])
    reply = f'The nearest mapped match is {names}.' if nearest else f'Showing {len(shown)} mapped {"potential competitors" if competitors else "nearby places"}: {names}.'
    action = {'kind': 'places', 'places': shown, 'groups': groups}
    if nearest:
        action['focus'] = {k: shown[0][k] for k in ('lat', 'lon')}
    return _response(reply + ' Distances are straight-line; mapped businesses may be incomplete.', **action)
