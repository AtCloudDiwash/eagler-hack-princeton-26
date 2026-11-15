"""Map and nearby-place requests must work without changing the search or requiring an LLM."""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DATABASE_PATH', '/tmp/turnkey-test.db')

import pytest
import main
from schemas import Intent, MapContext, RefineRequest
from services import external, refine


@pytest.fixture
def places(monkeypatch):
    async def nearby(lat, lon):
        return [
            {'id': 'far', 'name': 'Far Cafe', 'group': 'food_drink', 'category': 'amenity=cafe', 'lat': 29.762, 'lon': -95.37, 'distance_m': 999},
            {'id': 'near', 'name': 'Near Cafe', 'group': 'food_drink', 'category': 'amenity=cafe', 'lat': 29.7601, 'lon': -95.37, 'distance_m': 999},
            {'id': 'parking', 'name': 'Garage', 'group': 'parking', 'category': 'amenity=parking', 'lat': 29.7602, 'lon': -95.37, 'distance_m': 999},
        ]
    async def unexpected(*args):
        raise AssertionError('Map and place questions must not invoke search refinement')
    monkeypatch.setattr(external, 'nearby_places', nearby)
    monkeypatch.setattr(refine, 'refine', unexpected)


def request(message):
    return RefineRequest(intent=Intent(), message=message, center={'lat': 29.76, 'lon': -95.37})


def test_competitors_return_real_places_and_map_action(places):
    out = asyncio.run(main.refine_search(request('where are the other competitors?')))
    assert out.action == 'map' and out.result is None and out.changes == []
    assert out.map_action['groups'] == ['food_drink']
    assert [p['id'] for p in out.map_action['places']] == ['near', 'far']
    assert 'Near Cafe' in out.reply


def test_nearest_place_uses_distance_and_focus(places):
    out = asyncio.run(main.refine_search(request('where is the nearest cafe?')))
    assert out.map_action['places'][0]['id'] == 'near'
    assert out.map_action['focus']['lat'] == 29.7601
    assert 'nearest mapped' in out.reply.lower()


@pytest.mark.parametrize('message,kind', [('zoom in', 'zoom'), ('show satellite view', 'layer'), ('switch to 3d', 'tilt'), ('show all results', 'fit')])
def test_camera_requests_are_actions(places, message, kind):
    out = asyncio.run(main.refine_search(request(message)))
    assert out.action == 'map' and out.map_action['kind'] == kind


def test_unavailable_place_data_gives_actionable_answer(places, monkeypatch):
    async def unavailable(*args):
        raise RuntimeError('upstream unavailable')
    monkeypatch.setattr(external, 'nearby_places', unavailable)
    out = asyncio.run(main.refine_search(request('show competitors on the map')))
    assert out.action == 'answer'
    assert 'try again' in out.reply.lower()
    assert out.result is None


def test_ordinary_requirement_still_reaches_refinement(monkeypatch):
    called = []
    async def change(intent, message, *args):
        called.append(message)
        return {'action': 'answer', 'reply': 'Kept your requirement.', 'changes': [], 'intent': intent}
    monkeypatch.setattr(refine, 'refine', change)
    out = asyncio.run(main.refine_search(request('must have parking')))
    assert called == ['must have parking'] and out.map_action is None


def test_named_nearest_and_generic_nearby(places):
    named = asyncio.run(main.refine_search(request('where is the nearest Near Cafe?')))
    assert named.map_action['places'][0]['name'] == 'Near Cafe'
    nearby = asyncio.run(main.refine_search(request('what is nearby?')))
    assert len(nearby.map_action['places']) == 3


def test_visual_requests_use_vexcel_semantic_search(places, monkeypatch):
    calls = []
    areas = {'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': [[[-95.37, 29.76], [-95.369, 29.76], [-95.369, 29.761], [-95.37, 29.76]]]}, 'properties': {'score': .3}}]}
    async def semantic(text, lat, lon):
        calls.append((text, lat, lon))
        return areas
    from services import vexcel
    monkeypatch.setattr(vexcel, 'semantic_search', semantic)
    out = asyncio.run(main.refine_search(request('show buildings with outdoor patios')))
    assert out.action == 'map' and out.map_action['areas'] == areas
    assert calls == [('show buildings with outdoor patios', 29.76, -95.37)]
    assert 'need verification' in out.reply


def test_selected_property_is_the_nearest_search_origin(places, monkeypatch):
    monkeypatch.setattr(main.db, 'get_property', lambda id: ({'lat': 29.762, 'lon': -95.37}, None))
    req = request('nearest cafe')
    req.property_id = 'selected'
    out = asyncio.run(main.refine_search(req))
    assert out.map_action['places'][0]['id'] == 'far'


def test_nearest_hospital_does_not_return_a_closer_pharmacy(places, monkeypatch):
    async def nearby(*args):
        return [
            {'id': 'pharmacy', 'name': 'Pharmacy', 'group': 'dental_medical', 'category': 'amenity=pharmacy', 'lat': 29.7601, 'lon': -95.37},
            {'id': 'hospital', 'name': 'Hospital', 'group': 'dental_medical', 'category': 'amenity=hospital', 'lat': 29.762, 'lon': -95.37},
        ]
    monkeypatch.setattr(external, 'nearby_places', nearby)
    out = asyncio.run(main.refine_search(request('where is the nearest hospital?')))
    assert out.map_action['places'][0]['id'] == 'hospital'


def test_visual_service_access_error_is_not_a_chat_crash(places, monkeypatch):
    from services import vexcel
    async def denied(*args):
        raise vexcel.VexcelError(403, 'Not entitled')
    monkeypatch.setattr(vexcel, 'semantic_search', denied)
    out = asyncio.run(main.refine_search(request('show buildings with patios')))
    assert out.action == 'answer' and out.map_action is None
    assert 'unavailable' in out.reply


# ---------------------------------------------------------------- interaction types and follow-ups

SHOWN = [
    {'id': 'far', 'name': 'Far Cafe', 'group': 'food_drink', 'category': 'amenity=cafe', 'lat': 29.762, 'lon': -95.37},
    {'id': 'near', 'name': 'Near Cafe', 'group': 'food_drink', 'category': 'amenity=cafe', 'lat': 29.7601, 'lon': -95.37},
]


def follow_up(message, **ctx):
    req = request(message)
    req.map_context = MapContext(**{'places': SHOWN, **ctx})
    return asyncio.run(main.refine_search(req))


def test_nearby_reports_interaction_and_follow_up_suggestions(places):
    out = asyncio.run(main.refine_search(request('show cafes around here')))
    assert out.map_action['interaction'] == 'find_nearby'
    assert out.map_action['suggestions'] and 'Which is closest?' in out.map_action['suggestions']


def test_which_is_closest_resolves_against_shown_places_and_anchors_it(places, monkeypatch):
    async def no_lookup(*args):
        raise AssertionError('closest-of-shown must not refetch places')
    monkeypatch.setattr(external, 'nearby_places', no_lookup)
    out = follow_up('which is closest?')
    assert out.map_action['interaction'] == 'find_nearest'
    assert out.map_action['places'][0]['id'] == 'near'
    assert out.map_action['anchor']['id'] == 'near'


def test_ordinal_reference_inspects_that_place(places):
    out = follow_up('tell me about the second one')
    assert out.map_action['interaction'] == 'inspect'
    assert out.map_action['anchor']['id'] == 'near'
    assert out.map_action['focus'] == {'lat': 29.7601, 'lon': -95.37}


def test_whats_around_it_explores_from_the_anchor(places, monkeypatch):
    calls = []
    async def nearby(lat, lon):
        calls.append((lat, lon))
        return [{'id': 'parking', 'name': 'Garage', 'group': 'parking', 'category': 'amenity=parking', 'lat': 29.7602, 'lon': -95.37}]
    monkeypatch.setattr(external, 'nearby_places', nearby)
    out = follow_up("what's around it?", anchor={'kind': 'place', 'id': 'near', 'label': 'Near Cafe', 'lat': 29.7601, 'lon': -95.37})
    assert calls == [(29.7601, -95.37)]
    assert out.map_action['interaction'] == 'explore_surroundings'
    assert out.map_action['summary'][0]['group'] == 'parking'
    assert 'Near Cafe' in out.reply


def test_radius_adjustment_filters_results(places):
    out = follow_up('only parking within 50 m')
    assert out.map_action['interaction'] == 'adjust_results'
    assert out.map_action['radius_m'] == 50 and [p['id'] for p in out.map_action['places']] == ['parking']
    wider = follow_up('look farther', radius_m=100)
    assert wider.map_action['radius_m'] == 200


@pytest.mark.parametrize('message', ['back', 'go back to the cafes', 'undo'])
def test_back_is_a_client_side_restore(places, message):
    out = follow_up(message)
    assert out.map_action == {'kind': 'back', 'interaction': 'back'}
