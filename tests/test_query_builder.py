"""
Unit tests for Overpass Query Builder and Auto-Relaxation
"""

import pytest
from ml.schema import TraceSpotQuery, Entity, Relation
from backend.overpass import build_overpass_ql, build_tag_filter


def test_build_tag_filter():
    assert build_tag_filter(["amenity=pharmacy"]) == '["amenity"="pharmacy"]'
    assert build_tag_filter(["leisure=park", "access=yes"]) == '["leisure"="park"]["access"="yes"]'


def test_build_overpass_ql_single_entity():
    q = TraceSpotQuery(
        area="London",
        entities=[Entity(id=1, name="hospital", tags=["amenity=hospital"])],
        relations=[]
    )
    bbox = (51.4, -0.2, 51.6, 0.0)
    ql = build_overpass_ql(q, bbox)
    assert "[out:json]" in ql
    assert '["amenity"="hospital"]' in ql
    assert "->.primary;" in ql
    assert "around." not in ql


def test_build_overpass_ql_relational():
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
    bbox = (52.4, 13.3, 52.6, 13.5)
    ql = build_overpass_ql(q, bbox)
    assert '["amenity"="pharmacy"]' in ql
    assert '["leisure"="park"]' in ql
    assert "(around.rel_2: 150)" in ql
    assert "matched_primary" in ql



def test_build_overpass_ql_multi_relational():
    q = TraceSpotQuery(
        area="Paris",
        entities=[
            Entity(id=1, name="bench", tags=["amenity=bench"]),
            Entity(id=2, name="fountain", tags=["amenity=fountain"]),
            Entity(id=3, name="bus stop", tags=["highway=bus_stop"])
        ],
        relations=[
            Relation(type="within", a=1, b=2, distance_m=35),
            Relation(type="within", a=1, b=3, distance_m=35)
        ]
    )
    bbox = (48.8, 2.3, 48.9, 2.4)
    ql = build_overpass_ql(q, bbox)
    assert "amenity=bench" in ql
    assert "amenity=fountain" in ql
    assert "highway=bus_stop" in ql
    assert "(around.rel_2: 35)" in ql
    assert "(around.rel_3: 35)" in ql
