import os
import sys
import json
import time

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ml.evaluate import TraceSpotInferenceEngine
from backend.geocode import geocode_area
from backend.overpass import search_with_auto_relax
from backend.ranker import rank_and_explain_results

QUERIES = [
    "cafes in Berlin",
    "cafe within 100 m of a park in Berlin",
    "restaurants near a museum in Paris",
    "pharmacies within 200 m of a hospital in London",
    "coffee shops near a subway station in New York",
    "restaurants within 300 m of a railway station in Mumbai",
    "cafes near a park in Hyderabad",
]

async def run_tests():
    print("=" * 70)
    print("TraceSpot Comprehensive NLP Pipeline Verification")
    print("=" * 70)

    engine = TraceSpotInferenceEngine()
    if engine.model is None:
        print("[!] ERROR: Fine-tuned model failed to load. Halting.")
        return False

    print(f"[*] Engine successfully loaded fine-tuned model on: {engine.device}")
    
    all_passed = True
    results_summary = []

    for idx, q in enumerate(QUERIES, start=1):
        print(f"\n--- Test Query {idx}: '{q}' ---")
        t0 = time.perf_counter()
        query_obj, nlp_lat, method = engine.parse_with_model(q)
        print(f"  [NLP] Method: {method} | Latency: {nlp_lat:.1f}ms")
        print(f"  [NLP] Parsed Area: {query_obj.area}")
        print(f"  [NLP] Entities: {[(e.name, e.tags) for e in query_obj.entities]}")
        print(f"  [NLP] Relations: {[(r.type, r.distance_m) for r in query_obj.relations]}")

        # Geocode
        try:
            geo_info = await geocode_area(query_obj.area)
            center = (geo_info["lat"], geo_info["lon"])
            print(f"  [GEO] Center: {center} ({geo_info.get('display_name')})")
        except Exception as ge:
            print(f"  [GEO ERROR] {ge}")
            all_passed = False
            continue

        # Overpass search
        try:
            raw_res, ql_used, relax_note = await search_with_auto_relax(query_obj, center)
            elem_count = len(raw_res.get("elements", []))
            print(f"  [SEARCH] Raw elements retrieved: {elem_count} (Relax: '{relax_note}')")
        except Exception as se:
            print(f"  [SEARCH ERROR] {se}")
            all_passed = False
            continue

        # Rank and explain
        ranked = rank_and_explain_results(raw_res, query_obj)
        print(f"  [RANKER] Validated and ranked places: {len(ranked)}")
        if ranked:
            top = ranked[0]
            print(f"  [TOP RESULT] '{top['name']}' ({top['primary_type']}) - Score: {top['score']}")
            print(f"               Why: {top['why_matched']}")
            print(f"               Coords: ({top['lat']:.5f}, {top['lon']:.5f})")
            if top.get("related_matches"):
                for rm in top["related_matches"]:
                    print(f"               Rel: {rm['distance_m']}m from {rm['name']} ({rm['type']})")
        else:
            print("  [!] WARNING: 0 places matched.")
            all_passed = False

        total_lat = (time.perf_counter() - t0) * 1000
        print(f"  [TOTAL TIME] {total_lat:.1f}ms")
        results_summary.append({
            "query": q,
            "method": method,
            "area": query_obj.area,
            "count": len(ranked),
            "top_place": ranked[0]["name"] if ranked else None,
            "latency_ms": round(total_lat, 1)
        })

    print("\n" + "=" * 70)
    print("TEST SUMMARY:")
    for r in results_summary:
        print(f"  - '{r['query']}': {r['count']} places found ({r['method']}, {r['latency_ms']}ms)")
    print("=" * 70)
    return all_passed

if __name__ == "__main__":
    import asyncio
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
