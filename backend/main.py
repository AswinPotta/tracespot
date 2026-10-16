"""
TraceSpot Backend API (main.py)
FastAPI service providing natural-language place search on OpenStreetMap.
Includes:
- English NL parsing (Fine-tuned T5-small + RapidFuzz whitelist + rule fallback)
- Feature 1: Time-based reach search with Valhalla isochrones & actual walking times
- Feature 2: Sentence-to-itinerary planner with Beam Search & walking route timelines
- Nominatim geocoding & Overpass mirror execution with auto-relaxation
- SQLite search history & saved spots board
- GeoJSON/CSV/Itinerary export & ablation metrics APIs
"""

import os
import sys
import time
import io
import csv
import json
from typing import Dict, Any, Optional, List

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ml.schema import TraceSpotQuery, sanitize_and_validate_dict
from ml.rules import parse_query_rule_based
from ml.evaluate import TraceSpotInferenceEngine
from backend.geocode import geocode_area, GeocodeError
from backend.overpass import (
    build_overpass_ql, execute_overpass_query, search_with_auto_relax,
    search_time_based_with_isochrone, OverpassError
)
from backend.ranker import rank_and_explain_results
from backend.planner import plan_itinerary
from backend import db

app = FastAPI(
    title="TraceSpot API",
    description="Natural-Language Place Search & Walking Itinerary on OpenStreetMap",
    version="2.0.0"
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Shared ML Inference Engine instance
inference_engine = TraceSpotInferenceEngine()


# --- Pydantic Request Models ---
class SearchRequest(BaseModel):
    query: str
    force_baseline: bool = False
    time_min_override: Optional[int] = None


class CustomQLRequest(BaseModel):
    ql_query: str
    query_obj: dict


class SaveSpotRequest(BaseModel):
    spot_name: str
    lat: float
    lon: float
    tags: dict
    query_text: str
    status: str = "Confirmed"
    note: str = ""
    osm_id: str = ""
    osm_type: str = "node"


class UpdateSpotRequest(BaseModel):
    status: Optional[str] = None
    note: Optional[str] = None


class ExportItineraryRequest(BaseModel):
    itinerary_data: dict
    format: str = "geojson"  # "geojson" or "text"


# --- API Routes ---

@app.get("/")
def serve_index():
    """Serves the main single-page web app."""
    index_path = os.path.join("static", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "TraceSpot API is running. index.html not found."}


@app.post("/api/search")
async def search_endpoint(req: SearchRequest):
    """
    Unified Natural-Language Search Endpoint:
    1. Parses English natural language into schema (T5-small + Whitelist or Baseline)
    2. Geocodes area with Nominatim
    3. Handles:
       - Feature 2: Sentence-to-Itinerary (Beam search planner)
       - Feature 1: Time-Based Reach Search (Valhalla isochrone + Shapely filter + walk times)
       - Standard: Spatial Proximity Search (Auto-relax + Ranker)
    4. Records search into SQLite history
    """
    query_text = req.query.strip()
    if not query_text:
        raise HTTPException(status_code=400, detail="Search query cannot be empty.")

    total_start = time.perf_counter()

    # Step 1: Parse Query into Target JSON Schema
    if req.force_baseline:
        parsed_query, parse_lat = inference_engine.parse_with_baseline(query_text)
        method_used = "rule_based_baseline"
    else:
        parsed_query, parse_lat, method_used = inference_engine.parse_with_model(query_text)

    # Step 2: Geocode Area via Nominatim
    try:
        geo_info = await geocode_area(parsed_query.area)
    except GeocodeError as ge:
        raise HTTPException(status_code=404, detail=str(ge))

    spatial_target = (geo_info["lat"], geo_info["lon"])

    # Step 3: Route by Query Type

    # Case A: Sentence-to-Itinerary Query (Feature 2)
    if parsed_query.itinerary is not None:
        try:
            itin_res = await plan_itinerary(parsed_query, spatial_target)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Itinerary planning error: {str(e)}")

        total_latency_ms = round((time.perf_counter() - total_start) * 1000, 2)

        # Record to SQLite history
        db.record_search_history(
            query_text=query_text,
            parsed_json=parsed_query.model_dump(),
            detected_lang="en",
            result_count=len(itin_res.get("itineraries", [])),
            relaxation=itin_res.get("relaxation_applied", "")
        )

        return {
            "status": "success",
            "query": query_text,
            "method_used": method_used,
            "query_type": "itinerary",
            "parse_latency_ms": round(parse_lat, 2),
            "total_latency_ms": total_latency_ms,
            "parsed_query": parsed_query.model_dump(),
            "geocode": geo_info,
            "routing_source": itin_res.get("routing_source", "OSRM"),
            "relaxation_applied": itin_res.get("relaxation_applied", ""),
            "itinerary": itin_res
        }

    # Case B: Time-Based Walking Reach Search (Feature 1)
    has_time_relation = any(r.time_min is not None for r in parsed_query.relations)
    if has_time_relation or req.time_min_override is not None:
        try:
            time_res = await search_time_based_with_isochrone(
                parsed_query,
                spatial_target,
                time_min_override=req.time_min_override
            )
        except OverpassError as oe:
            raise HTTPException(status_code=502, detail=str(oe))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Time-based search error: {str(e)}")

        total_latency_ms = round((time.perf_counter() - total_start) * 1000, 2)

        db.record_search_history(
            query_text=query_text,
            parsed_json=parsed_query.model_dump(),
            detected_lang="en",
            result_count=time_res["results_count"],
            relaxation=time_res.get("relaxation_applied", "")
        )

        return {
            "status": "success",
            "query": query_text,
            "method_used": method_used,
            "query_type": "time_based",
            "parse_latency_ms": round(parse_lat, 2),
            "total_latency_ms": total_latency_ms,
            "parsed_query": parsed_query.model_dump(),
            "geocode": geo_info,
            "overpass_ql": time_res["overpass_ql"],
            "routing_source": time_res["routing_source"],
            "isochrone_geojson": time_res["isochrone_geojson"],
            "anchors": time_res["anchors"],
            "time_min": time_res["time_min"],
            "relaxation_applied": time_res["relaxation_applied"],
            "results_count": time_res["results_count"],
            "results": time_res["results"]
        }

    # Case C: Standard Spatial Proximity Search
    try:
        raw_overpass, executed_ql, relax_msg = await search_with_auto_relax(parsed_query, spatial_target)
    except Exception as e:
        raw_overpass = {"elements": []}
        executed_ql = ""
        relax_msg = f"Search fallback: {str(e)}"

    ranked_places = rank_and_explain_results(raw_overpass, parsed_query)
    total_latency_ms = round((time.perf_counter() - total_start) * 1000, 2)

    db.record_search_history(
        query_text=query_text,
        parsed_json=parsed_query.model_dump(),
        detected_lang="en",
        result_count=len(ranked_places),
        relaxation=relax_msg
    )

    return {
        "status": "success",
        "query": query_text,
        "method_used": method_used,
        "query_type": "spatial",
        "parse_latency_ms": round(parse_lat, 2),
        "total_latency_ms": total_latency_ms,
        "parsed_query": parsed_query.model_dump(),
        "geocode": geo_info,
        "overpass_ql": executed_ql,
        "relaxation_applied": relax_msg,
        "results_count": len(ranked_places),
        "results": ranked_places
    }


@app.post("/api/search/custom-overpass")
async def search_custom_overpass(req: CustomQLRequest):
    """Allows user to edit generated Overpass QL directly in Explain tab and re-run."""
    total_start = time.perf_counter()
    try:
        validated_query = sanitize_and_validate_dict(req.query_obj)
        raw_overpass = await execute_overpass_query(req.ql_query)
        ranked_places = rank_and_explain_results(raw_overpass, validated_query)
        total_latency_ms = round((time.perf_counter() - total_start) * 1000, 2)

        return {
            "status": "success",
            "overpass_ql": req.ql_query,
            "results_count": len(ranked_places),
            "results": ranked_places,
            "total_latency_ms": total_latency_ms
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Custom Overpass execution error: {str(e)}")


@app.get("/api/history")
def get_history(limit: int = Query(30, ge=1, le=100)):
    """Fetches recent search history from SQLite."""
    return db.get_search_history(limit=limit)


@app.delete("/api/history")
def clear_history():
    """Clears search history."""
    db.clear_search_history()
    return {"status": "cleared"}


@app.get("/api/saved")
def get_saved():
    """Retrieves all saved spots on the Saved Spots board."""
    return db.get_saved_spots()


@app.post("/api/saved")
def add_saved(req: SaveSpotRequest):
    """Saves a spot to SQLite."""
    saved_id = db.add_saved_spot(
        spot_name=req.spot_name,
        lat=req.lat,
        lon=req.lon,
        tags=req.tags,
        query_text=req.query_text,
        status=req.status,
        note=req.note,
        osm_id=req.osm_id,
        osm_type=req.osm_type
    )
    return {"status": "saved", "id": saved_id}


@app.put("/api/saved/{spot_id}")
def update_saved(spot_id: int, req: UpdateSpotRequest):
    """Updates status or note of a saved spot."""
    ok = db.update_saved_spot(spot_id, status=req.status, note=req.note)
    if not ok:
        raise HTTPException(status_code=404, detail="Saved spot not found")
    return {"status": "updated"}


@app.delete("/api/saved/{spot_id}")
def delete_saved(spot_id: int):
    """Deletes a spot from the saved board."""
    ok = db.delete_saved_spot(spot_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Saved spot not found")
    return {"status": "deleted"}


@app.get("/api/export/geojson")
def export_geojson(source: str = Query("saved", description="'saved' or 'last_search'")):
    """Exports saved spots as standard GeoJSON FeatureCollection."""
    spots = db.get_saved_spots()
    features = []
    for sp in spots:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [sp["lon"], sp["lat"]]
            },
            "properties": {
                "id": sp["id"],
                "name": sp["spot_name"],
                "status": sp["status"],
                "note": sp["note"],
                "query": sp["query_text"],
                "osm_id": sp["osm_id"],
                "tags": sp["tags"]
            }
        })

    geojson_data = {
        "type": "FeatureCollection",
        "name": "TraceSpot_Export",
        "features": features
    }
    return JSONResponse(
        content=geojson_data,
        headers={"Content-Disposition": "attachment; filename=tracespot_places.geojson"}
    )


@app.get("/api/export/csv")
def export_csv():
    """Exports saved spots to CSV."""
    spots = db.get_saved_spots()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Name", "Latitude", "Longitude", "Status", "Note", "Query", "OSM ID", "OSM Type"])
    for s in spots:
        writer.writerow([s["id"], s["spot_name"], s["lat"], s["lon"], s["status"], s["note"], s["query_text"], s["osm_id"], s["osm_type"]])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=tracespot_places.csv"}
    )


@app.post("/api/export/itinerary")
def export_itinerary_endpoint(req: ExportItineraryRequest):
    """
    Exports walking itinerary as:
    1. GeoJSON (FeatureCollection with Stop Points and Route LineStrings)
    2. Printable list (plain text formatted timeline)
    """
    itin = req.itinerary_data
    if req.format == "text":
        lines = [
            f"=== TRACESPOT WALKING ITINERARY ===",
            f"Area: {itin.get('area', 'Unknown')}",
            f"Total Duration: {itin.get('total_walking_time_min', 0)} minutes",
            f"Total Distance: {itin.get('total_distance_m', 0)} meters",
            f"",
            f"TIMELINE:",
        ]
        for idx, s in enumerate(itin.get("stops", []), start=1):
            lines.append(f"  Step {idx}: {s.get('name')} [{s.get('concept', '').title()}] (Coordinates: {s.get('lat'):.5f}, {s.get('lon'):.5f})")
            if idx <= len(itin.get("legs", [])):
                leg = itin["legs"][idx - 1]
                lines.append(f"     |--- 🚶 Walk {leg.get('duration_min')} min ({leg.get('distance_m')} m) via {leg.get('source')} --->")

        content = "\n".join(lines)
        return StreamingResponse(
            iter([content]),
            media_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=itinerary_plan.txt"}
        )

    # GeoJSON FeatureCollection format
    features = []
    # 1. Stop Point features
    for s in itin.get("stops", []):
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [s["lon"], s["lat"]]
            },
            "properties": {
                "stop_number": s.get("stop_number"),
                "name": s.get("name"),
                "concept": s.get("concept"),
                "type": "Stop"
            }
        })
    # 2. Route LineString feature
    route_geom = itin.get("route_geojson", {})
    if route_geom and route_geom.get("geometry"):
        features.append({
            "type": "Feature",
            "geometry": route_geom["geometry"],
            "properties": {
                "total_walking_time_min": itin.get("total_walking_time_min"),
                "total_distance_m": itin.get("total_distance_m"),
                "type": "RoutePath"
            }
        })

    geojson_out = {
        "type": "FeatureCollection",
        "name": "TraceSpot_Itinerary_Export",
        "features": features
    }
    return JSONResponse(
        content=geojson_out,
        headers={"Content-Disposition": "attachment; filename=tracespot_itinerary.geojson"}
    )


@app.get("/api/metrics")
def get_metrics():
    """Returns model vs baseline evaluation metrics from ml/metrics.json."""
    metrics_path = os.path.join("ml", "metrics.json")
    if os.path.exists(metrics_path):
        with open(metrics_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"error": "metrics.json not found."}


@app.get("/api/ablation")
def get_ablation_results():
    """Returns 4-pillar ablation and geometry evaluation results from ml/ablation_results.json."""
    path = os.path.join("ml", "ablation_results.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"error": "ablation_results.json not found. Run python ml/ablation.py."}


@app.post("/api/evaluate/live")
def live_evaluation_run():
    """Runs a live comparative benchmark across 10 diverse test queries."""
    sample_queries = [
        "pharmacy near a park in Berlin",
        "pharmacy within a 5 minute walk of a metro station in Berlin",
        "supermarket within 10 minutes walk of a train station in Chennai",
        "cafe, then a park, then a restaurant, each within a 10 minute walk in Paris",
        "bakery then a museum then a bar within 15 minutes walk in Hyderabad",
        "church within 100 m of a river in Amsterdam",
        "bench next to a fountain and a bus stop in Paris",
        "hospital in London",
        "bakery near a school in Vienna",
        "library next to a museum in Rome"
    ]
    results = []
    for q in sample_queries:
        b_res, b_lat = inference_engine.parse_with_baseline(q)
        m_res, m_lat, method = inference_engine.parse_with_model(q)
        results.append({
            "query": q,
            "baseline": {
                "parsed": b_res.model_dump(),
                "latency_ms": round(b_lat, 2)
            },
            "model": {
                "parsed": m_res.model_dump(),
                "latency_ms": round(m_lat, 2),
                "method": method
            }
        })
    return {"queries_tested": len(results), "comparisons": results}
