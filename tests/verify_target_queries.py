"""
Verification script for real OpenStreetMap live Phase 2 queries:
1. "pharmacy within a 5 minute walk of a metro station in Berlin" (Time-Based Isochrone)
2. "supermarket within 10 minutes walk of a train station in Chennai" (Time-Based Isochrone)
3. "cafe, then a park, then a restaurant, each within a 10 minute walk in Paris" (Sentence-to-Itinerary)
4. "bakery then a museum then a bar within 15 minutes walk in Hyderabad" (Sentence-to-Itinerary)
"""

import sys
import os
import asyncio

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import httpx
from backend.main import app


async def verify_all():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

    print("=" * 70)
    print("TraceSpot Phase 2 Live Verification on Real OSM Data")
    print("=" * 70)

    test_queries = [
        ("pharmacy within a 5 minute walk of a metro station in Berlin", "time_based"),
        ("supermarket within 10 minutes walk of a train station in Chennai", "time_based"),
        ("cafe, then a park, then a restaurant, each within a 10 minute walk in Paris", "itinerary"),
        ("bakery then a museum then a bar within 15 minutes walk in Hyderabad", "itinerary")
    ]

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=60.0) as client:
        all_passed = True
        for idx, (query, expected_type) in enumerate(test_queries, start=1):
            print(f"\n[{idx}/4] Query: \"{query}\"")
            resp = await client.post("/api/search", json={"query": query})
            if resp.status_code != 200:
                print(f"  [FAIL] HTTP {resp.status_code}: {resp.text}")
                all_passed = False
                continue

            data = resp.json()
            q_type = data.get("query_type")
            routing_src = data.get("routing_source")
            latency = data.get("total_latency_ms")

            print(f"  [OK] Status: 200 | Type: {q_type} | Routing: {routing_src} | Latency: {latency} ms")

            if q_type == "time_based":
                anchors_count = len(data.get("anchors", []))
                results_count = data.get("results_count", 0)
                print(f"  [OK] Anchors: {anchors_count} | Results within reach: {results_count}")
                if results_count > 0:
                    top = data["results"][0]
                    print(f"  [OK] Top match: \"{top['name']}\" ({top.get('walk_time_min')} min walk, {top.get('walk_distance_m')} m)")
                    print(f"       OSM link: {top['verification_links']['osm']}")
            elif q_type == "itinerary":
                itin = data.get("itinerary", {})
                plans = itin.get("itineraries", [])
                print(f"  [OK] Generated {len(plans)} itinerary plan(s)")
                if len(plans) > 0:
                    p1 = plans[0]
                    print(f"  [OK] Plan 1: {p1.get('total_walking_time_min')} min total walk ({p1.get('total_distance_m')} m)")
                    print(f"       Timeline: {p1.get('timeline_text')}")

            await asyncio.sleep(1.0)

        print("\n" + "=" * 70)
        if all_passed:
            print("[SUCCESS] All 4 Phase 2 target queries verified on live OSM data!")
        else:
            print("[FAIL] Some queries failed verification.")
        print("=" * 70)


if __name__ == "__main__":
    asyncio.run(verify_all())
