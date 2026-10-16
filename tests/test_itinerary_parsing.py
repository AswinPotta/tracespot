"""
Unit tests for Feature 2 Itinerary Parsing (tests/test_itinerary_parsing.py)
Tests:
- Sequence words ('then', 'after that', 'followed by', 'and finally', commas)
- Generic words mapped to tags:
  'dinner' -> amenity=restaurant
  'coffee' -> amenity=cafe
  'drink'  -> amenity=bar/pub
  'sightseeing' -> tourism=attraction
- Extraction of max_leg_min
"""

import pytest
from ml.rules import parse_query_rule_based


def test_itinerary_basic_sequence():
    q = "cafe, then a park, then a restaurant, each within a 10 minute walk in Paris"
    res = parse_query_rule_based(q)
    assert res.area.lower() == "paris"
    assert res.itinerary is not None
    assert len(res.itinerary.stops) == 3
    assert res.itinerary.max_leg_min == 10

    # Check ordered concepts & tags
    assert "amenity=cafe" in res.itinerary.stops[0].tags
    assert "leisure=park" in res.itinerary.stops[1].tags
    assert "amenity=restaurant" in res.itinerary.stops[2].tags


def test_itinerary_generic_words_mapping():
    # 'coffee' -> cafe, 'sightseeing' -> attraction, 'dinner' -> restaurant, 'drink' -> bar
    q = "coffee, then sightseeing, then dinner, then a drink in London"
    res = parse_query_rule_based(q)
    assert res.area.lower() == "london"
    assert res.itinerary is not None
    stops = res.itinerary.stops
    assert len(stops) == 4

    # Stop 1: coffee -> cafe
    assert "amenity=cafe" in stops[0].tags
    # Stop 2: sightseeing -> attraction
    assert any("tourism=attraction" in t for t in stops[1].tags)
    # Stop 3: dinner -> restaurant
    assert "amenity=restaurant" in stops[2].tags
    # Stop 4: drink -> bar or pub
    assert any("amenity=bar" in t or "amenity=pub" in t for t in stops[3].tags)


def test_itinerary_sequence_transition_words():
    # 'followed by' and 'and finally'
    q = "bakery, followed by a museum, and finally a pub in Edinburgh"
    res = parse_query_rule_based(q)
    assert res.area.lower() == "edinburgh"
    assert res.itinerary is not None
    assert len(res.itinerary.stops) == 3
    assert "shop=bakery" in res.itinerary.stops[0].tags
    assert "tourism=museum" in res.itinerary.stops[1].tags
    assert any("amenity=pub" in t or "amenity=bar" in t for t in res.itinerary.stops[2].tags)


def test_itinerary_time_limits():
    q1 = "bakery then a museum then a bar within 15 minutes walk in Hyderabad"
    res1 = parse_query_rule_based(q1)
    assert res1.itinerary is not None
    assert res1.itinerary.max_leg_min == 15

    q2 = "cafe, then a park, all within a 5 minute walk in Amsterdam"
    res2 = parse_query_rule_based(q2)
    assert res2.itinerary is not None
    assert res2.itinerary.max_leg_min == 5
