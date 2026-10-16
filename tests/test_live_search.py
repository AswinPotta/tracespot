"""
Integration Test for Real OpenStreetMap Live Search on Phase 2 Target Queries:
1. "pharmacy within a 5 minute walk of a metro station in Berlin" (Time-Based Isochrone)
2. "supermarket within 10 minutes walk of a train station in Chennai" (Time-Based Isochrone)
3. "cafe, then a park, then a restaurant, each within a 10 minute walk in Paris" (Sentence-to-Itinerary)
4. "bakery then a museum then a bar within 15 minutes walk in Hyderabad" (Sentence-to-Itinerary)
5. "church within 100 m of a river in Amsterdam" (Standard Spatial Proximity)
"""

import pytest
import httpx
from backend.main import app


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.anyio
async def test_live_search_phase2_queries():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=60.0) as client:
        # 1. Feature 1: Time-based Isochrone queries
        time_queries = [
            ("pharmacy within a 5 minute walk of a metro station in Berlin", "Berlin", "pharmacy", "metro"),
            ("supermarket within 10 minutes walk of a train station in Chennai", "Chennai", "supermarket", "train")
        ]

        for query, expected_area, exp_entity, exp_anchor in time_queries:
            resp = await client.post("/api/search", json={"query": query})
            assert resp.status_code == 200, f"Failed for {query}: {resp.text}"
            data = resp.json()

            assert data["status"] == "success"
            assert data["query_type"] == "time_based"
            assert data["parsed_query"]["area"].lower() == expected_area.lower()
            assert "isochrone_geojson" in data
            assert "anchors" in data and len(data["anchors"]) > 0
            assert "results" in data and len(data["results"]) > 0
            first = data["results"][0]
            assert "walk_time_min" in first
            assert "walk_distance_m" in first
            assert "routing_source" in first

        # 2. Feature 2: Sentence-to-Itinerary queries
        itinerary_queries = [
            ("cafe, then a park, then a restaurant, each within a 10 minute walk in Paris", "Paris", 3),
            ("bakery then a museum then a bar within 15 minutes walk in Hyderabad", "Hyderabad", 3)
        ]

        for query, expected_area, min_stops in itinerary_queries:
            resp = await client.post("/api/search", json={"query": query})
            assert resp.status_code == 200, f"Failed for {query}: {resp.text}"
            data = resp.json()

            assert data["status"] == "success"
            assert data["query_type"] == "itinerary"
            assert data["parsed_query"]["area"].lower() == expected_area.lower()
            assert "itinerary" in data
            itineraries = data["itinerary"]["itineraries"]
            assert len(itineraries) > 0
            first_plan = itineraries[0]
            assert len(first_plan["stops"]) >= min_stops
            assert first_plan["total_walking_time_min"] > 0
            assert "route_geojson" in first_plan
            assert "timeline_text" in first_plan

        # 3. Standard Proximity Query
        resp = await client.post("/api/search", json={"query": "church within 100 m of a river in Amsterdam"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert len(data["results"]) > 0
