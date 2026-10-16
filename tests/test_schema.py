"""
Unit tests for TraceSpot Schema, Tag Whitelist & RapidFuzz Sanitization
"""

import pytest
from ml.schema import (
    TraceSpotQuery,
    Entity,
    Relation,
    sanitize_tag,
    sanitize_and_validate_dict,
    OSM_TAG_WHITELIST
)


def test_tag_whitelist_loaded():
    assert len(OSM_TAG_WHITELIST) >= 80
    assert "amenity=place_of_worship" in OSM_TAG_WHITELIST
    assert "amenity=pharmacy" in OSM_TAG_WHITELIST
    assert "leisure=park" in OSM_TAG_WHITELIST
    assert "waterway=river" in OSM_TAG_WHITELIST
    assert "highway=bus_stop" in OSM_TAG_WHITELIST


def test_sanitize_exact_tag():
    assert sanitize_tag("amenity=pharmacy") == "amenity=pharmacy"
    assert sanitize_tag("leisure=park") == "leisure=park"
    assert sanitize_tag("amenity:cafe") == "amenity=cafe"


def test_sanitize_fuzzy_tag_correction():
    # Misspelled or slightly altered tags should be fuzzy-corrected by rapidfuzz
    assert sanitize_tag("amenity=place_worship") == "amenity=place_of_worship"
    assert sanitize_tag("leisure=parrk") == "leisure=park"
    assert sanitize_tag("waterway=riveer") == "waterway=river"
    assert sanitize_tag("highway=busstop") == "highway=bus_stop"


def test_sanitize_invalid_hallucinated_tag():
    # Complete hallucination should return None
    assert sanitize_tag("spaceship=launchpad") is None
    assert sanitize_tag("random_gibberish_12345") is None


def test_schema_validation_valid():
    payload = {
        "area": "Berlin",
        "entities": [
            {"id": 1, "name": "pharmacy", "tags": ["amenity=pharmacy"]},
            {"id": 2, "name": "park", "tags": ["leisure=park"]}
        ],
        "relations": [
            {"type": "within", "a": 1, "b": 2, "distance_m": 150}
        ]
    }
    validated = sanitize_and_validate_dict(payload)
    assert validated.area == "Berlin"
    assert len(validated.entities) == 2
    assert len(validated.relations) == 1
    assert validated.relations[0].distance_m == 150


def test_schema_validation_filters_hallucinated_relations():
    # If relation points to non-existent entity, it should be dropped safely
    payload = {
        "area": "Amsterdam",
        "entities": [
            {"id": 1, "name": "church", "tags": ["amenity=place_of_worship"]}
        ],
        "relations": [
            {"type": "within", "a": 1, "b": 99, "distance_m": 100}
        ]
    }
    validated = sanitize_and_validate_dict(payload)
    assert len(validated.entities) == 1
    assert len(validated.relations) == 0  # Invalid reference dropped
