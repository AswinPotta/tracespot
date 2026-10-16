"""
Unit tests for Rule-based Parser on Required Prompts (English Only)
"""

import pytest
from ml.rules import parse_query_rule_based


def test_required_prompt_1_berlin():
    q = "pharmacy near a park in Berlin"
    res = parse_query_rule_based(q)
    assert res.area.lower() == "berlin"
    assert len(res.entities) == 2
    assert res.entities[0].name == "pharmacy"
    assert "amenity=pharmacy" in res.entities[0].tags
    assert res.entities[1].name == "park"
    assert "leisure=park" in res.entities[1].tags
    assert len(res.relations) == 1
    assert res.relations[0].a == 1
    assert res.relations[0].b == 2


def test_required_prompt_2_amsterdam():
    q = "church within 100 m of a river in Amsterdam"
    res = parse_query_rule_based(q)
    assert res.area.lower() == "amsterdam"
    assert len(res.entities) == 2
    assert res.entities[0].name == "church"
    assert "amenity=place_of_worship" in res.entities[0].tags
    assert res.entities[1].name == "river"
    assert "waterway=river" in res.entities[1].tags
    assert len(res.relations) == 1
    assert res.relations[0].distance_m == 100


def test_required_prompt_3_paris_multi():
    q = "bench next to a fountain and a bus stop in Paris"
    res = parse_query_rule_based(q)
    assert res.area.lower() == "paris"
    assert len(res.entities) == 3
    assert res.entities[0].name == "bench"
    assert "amenity=bench" in res.entities[0].tags
    assert res.entities[1].name == "fountain"
    assert "amenity=fountain" in res.entities[1].tags
    assert res.entities[2].name == "bus stop"
    assert "highway=bus_stop" in res.entities[2].tags
    assert len(res.relations) == 2


def test_required_prompt_4_london_single():
    q = "hospital in London"
    res = parse_query_rule_based(q)
    assert res.area.lower() == "london"
    assert len(res.entities) == 1
    assert res.entities[0].name == "hospital"
    assert "amenity=hospital" in res.entities[0].tags
    assert len(res.relations) == 0


def test_required_prompt_chennai_time():
    q = "supermarket within 10 minutes walk of a train station in Chennai"
    res = parse_query_rule_based(q)
    assert res.area.lower() == "chennai"
    assert len(res.entities) == 2
    assert "shop=supermarket" in res.entities[0].tags
    assert "railway=station" in res.entities[1].tags
    assert len(res.relations) == 1
    assert res.relations[0].time_min == 10
    assert res.relations[0].mode == "walk"


def test_required_prompt_hyderabad_itinerary():
    q = "bakery then a museum then a bar within 15 minutes walk in Hyderabad"
    res = parse_query_rule_based(q)
    assert res.area.lower() == "hyderabad"
    assert res.itinerary is not None
    assert len(res.itinerary.stops) == 3
    assert res.itinerary.max_leg_min == 15
