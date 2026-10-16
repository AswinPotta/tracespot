"""
Unit tests for Feature 1 Time-Phrase Parsing (tests/test_time_phrase_parsing.py)
Tests recognition of:
- 'within a 5 minute walk of'
- '10 min walk from'
- 'walking distance of' (default 10 min)
- '5 minutes away on foot'
- Noisy variations: '5 mins', 'five minute', 'walkable'
"""

import pytest
from ml.rules import parse_query_rule_based
from ml.schema import TraceSpotQuery


def test_time_phrase_within_minute_walk():
    q = "pharmacy within a 5 minute walk of a metro station in Berlin"
    res = parse_query_rule_based(q)
    assert res.area.lower() == "berlin"
    assert len(res.entities) == 2
    assert "amenity=pharmacy" in res.entities[0].tags
    assert any("subway" in t or "station" in t for t in res.entities[1].tags)
    assert len(res.relations) == 1
    rel = res.relations[0]
    assert rel.time_min == 5
    assert rel.mode == "walk"


def test_time_phrase_min_walk_from():
    q = "supermarket 10 min walk from a train station in Chennai"
    res = parse_query_rule_based(q)
    assert res.area.lower() == "chennai"
    assert "shop=supermarket" in res.entities[0].tags
    assert any("railway=station" in t for t in res.entities[1].tags)
    assert len(res.relations) == 1
    rel = res.relations[0]
    assert rel.time_min == 10
    assert rel.mode == "walk"


def test_time_phrase_walking_distance_default():
    q = "cafe within walking distance of a museum in Zurich"
    res = parse_query_rule_based(q)
    assert res.area.lower() == "zurich"
    assert "amenity=cafe" in res.entities[0].tags
    assert "tourism=museum" in res.entities[1].tags
    assert len(res.relations) == 1
    rel = res.relations[0]
    assert rel.time_min == 10  # default 10 min
    assert rel.mode == "walk"


def test_time_phrase_minutes_away_on_foot():
    q = "bar 5 minutes away on foot from a hotel in Amsterdam"
    res = parse_query_rule_based(q)
    assert res.area.lower() == "amsterdam"
    assert "amenity=bar" in res.entities[0].tags
    assert "tourism=hotel" in res.entities[1].tags
    assert len(res.relations) == 1
    rel = res.relations[0]
    assert rel.time_min == 5
    assert rel.mode == "walk"


def test_time_phrase_word_numbers_and_noise():
    # 'five minute' word number and '5 mins'
    q1 = "bakery within five minute walk of a park in Vienna"
    res1 = parse_query_rule_based(q1)
    assert res1.relations[0].time_min == 5
    assert res1.relations[0].mode == "walk"

    q2 = "pharmacy 15 mins away on foot from a clinic in Warsaw"
    res2 = parse_query_rule_based(q2)
    assert res2.relations[0].time_min == 15
    assert res2.relations[0].mode == "walk"


def test_time_phrase_walkable():
    q = "restaurant walkable from a train station in Paris"
    res = parse_query_rule_based(q)
    assert res.relations[0].time_min == 10
    assert res.relations[0].mode == "walk"


def test_old_behavior_distance_preserved():
    # Distance in meters should NOT use time_min
    q = "church within 100 m of a river in Amsterdam"
    res = parse_query_rule_based(q)
    assert len(res.relations) == 1
    assert res.relations[0].distance_m == 100
    assert res.relations[0].time_min is None
