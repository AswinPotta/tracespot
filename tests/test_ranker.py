"""
Unit tests for Spatial Ranker, Haversine Distance, and Verification Links
"""

import pytest
from backend.ranker import haversine_distance_m, generate_verification_links, rank_and_explain_results
from ml.schema import TraceSpotQuery, Entity, Relation


def test_haversine_distance_accuracy():
    # Distance between Brandenburg Gate (52.51627, 13.37772) and Reichstag (52.51862, 13.37619) ~280 meters
    dist = haversine_distance_m(52.51627, 13.37772, 52.51862, 13.37619)
    assert 250 <= dist <= 310


def test_generate_verification_links():
    tags = {
        "name": "Cathedral",
        "wikipedia": "en:St_Paul's_Cathedral",
        "wikidata": "Q102818"
    }
    links = generate_verification_links("node", "123456", 51.5138, -0.0983, tags)
    assert "https://www.openstreetmap.org/node/123456" in links["osm"]
    assert "google.com/maps" in links["street_view"]
    assert "mapillary.com" in links["mapillary"]
    assert "wikipedia.org/wiki/St_Paul's_Cathedral" in links["wikipedia"]
    assert "wikidata.org/wiki/Q102818" in links["wikidata"]


def test_rank_and_explain_results():
    q = TraceSpotQuery(
        area="Berlin",
        entities=[
            Entity(id=1, name="pharmacy", tags=["amenity=pharmacy"]),
            Entity(id=2, name="park", tags=["leisure=park"])
        ],
        relations=[
            Relation(type="within", a=1, b=2, distance_m=150)
        ]
    )

    dummy_overpass = {
        "elements": [
            {
                "type": "node",
                "id": 101,
                "lat": 52.5200,
                "lon": 13.4000,
                "tags": {"name": "Test Pharmacy", "amenity": "pharmacy"}
            },
            {
                "type": "node",
                "id": 102,
                "lat": 52.5205,
                "lon": 13.4005,
                "tags": {"name": "City Park", "leisure": "park"}
            }
        ]
    }

    results = rank_and_explain_results(dummy_overpass, q)
    assert len(results) >= 1
    assert results[0]["name"] == "Test Pharmacy"
    assert "m from City Park" in results[0]["why_matched"]
    assert results[0]["score"] > 0.5
    assert len(results[0]["related_matches"]) == 1
