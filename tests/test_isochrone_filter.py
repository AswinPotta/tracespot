"""
Unit tests for Isochrone-to-Candidate Filter (tests/test_isochrone_filter.py)
Tests:
- Point containment within isochrone GeoJSON polygons using Shapely
- Handling of points inside vs outside polygon
- Fallback circular polygon generation at 83 m/min walking speed
"""

import pytest
from shapely.geometry import Point, shape
from backend.routing import (
    point_in_isochrone_geojson,
    create_circular_isochrone_polygon,
    haversine_m
)


def test_create_circular_isochrone_polygon():
    center_lat, center_lon = 52.5200, 13.4050
    time_min = 5
    feature = create_circular_isochrone_polygon(center_lat, center_lon, time_min=time_min, num_points=36)
    
    assert feature["type"] == "Feature"
    assert feature["geometry"]["type"] == "Polygon"
    assert feature["properties"]["contour"] == 5.0
    assert feature["properties"]["source"] == "estimated"

    poly = shape(feature["geometry"])
    assert poly.is_valid
    assert poly.area > 0


def test_point_in_isochrone_geojson():
    center_lat, center_lon = 52.5200, 13.4050
    # 5 min walk = ~416m radius
    iso_feature = create_circular_isochrone_polygon(center_lat, center_lon, time_min=5)
    geojson_collection = {
        "type": "FeatureCollection",
        "features": [iso_feature]
    }

    # Point ~100m away (well inside 5 min reach)
    inside_lat, inside_lon = center_lat + 0.0008, center_lon + 0.0008
    assert point_in_isochrone_geojson(inside_lat, inside_lon, geojson_collection) is True

    # Point ~2.5km away (definitely outside 5 min reach)
    outside_lat, outside_lon = center_lat + 0.025, center_lon + 0.025
    assert point_in_isochrone_geojson(outside_lat, outside_lon, geojson_collection) is False


def test_filter_candidate_places_in_polygon():
    center_lat, center_lon = 48.8566, 2.3522  # Paris
    iso_feature = create_circular_isochrone_polygon(center_lat, center_lon, time_min=10)
    iso_geojson = {"type": "FeatureCollection", "features": [iso_feature]}

    candidates = [
        {"name": "Nearby Pharmacy", "lat": 48.8570, "lon": 2.3530},     # ~80m inside
        {"name": "Close Drugstore", "lat": 48.8590, "lon": 2.3550},      # ~350m inside
        {"name": "Distant Chemist", "lat": 48.8900, "lon": 2.4100},      # ~5.5km outside
    ]

    matched = [c for c in candidates if point_in_isochrone_geojson(c["lat"], c["lon"], iso_geojson)]
    assert len(matched) == 2
    assert matched[0]["name"] == "Nearby Pharmacy"
    assert matched[1]["name"] == "Close Drugstore"
