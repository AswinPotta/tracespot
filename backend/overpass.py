"""
TraceSpot Overpass Engine (overpass.py)
Constructs Overpass QL queries from structured JSON,
executes queries with mirror failover, caching, retries,
and handles auto-relaxation when 0 results are returned.
"""

import math
import hashlib
import json
import time
import asyncio
import httpx
from typing import List, Dict, Any, Optional, Tuple, Union
from ml.schema import TraceSpotQuery, Entity, Relation
from backend.db import get_cached_overpass, set_cached_overpass

# Overpass API Mirrors for high reliability failover
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]


USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TraceSpotApp/2.0 (Academic Research; contact@tracespot.app)"


class OverpassError(Exception):
    pass


def build_tag_filter(tags: List[str]) -> str:
    """Formats list of 'key=value' tags into Overpass filter syntax [\"key\"=\"value\"]."""
    filters = []
    for tag in tags:
        if "=" in tag:
            k, v = tag.split("=", 1)
            filters.append(f'["{k}"="{v}"]')
        else:
            filters.append(f'["{tag}"]')
    return "".join(filters)


def build_overpass_ql(
    query_obj: TraceSpotQuery,
    spatial_target: Union[Tuple[float, float], Tuple[float, float, float, float]],  # (lat, lon) OR (south, west, north, east)
    radius_m: int = 3500,
    timeout: int = 25,
    max_results: int = 40,
    distance_override: Optional[Dict[Tuple[int, int], int]] = None,
    drop_relations: Optional[List[Tuple[int, int]]] = None
) -> str:
    """
    Builds an optimized, robust Overpass QL query string.
    Uses spatial radius (around:radius, lat, lon) or bounding box.
    Outputs primary matches AND matched relational entities for map lines.
    """
    if len(spatial_target) == 2:
        lat, lon = spatial_target
        spatial_filter = f"(around:{radius_m}, {lat:.5f}, {lon:.5f})"
    else:
        south, west, north, east = spatial_target
        spatial_filter = f"({south:.5f},{west:.5f},{north:.5f},{east:.5f})"

    entities = {e.id: e for e in query_obj.entities}
    if not entities:
        raise OverpassError("Query must have at least one entity.")

    primary_id = query_obj.entities[0].id
    primary_entity = entities[primary_id]

    active_relations = []
    for r in query_obj.relations:
        if drop_relations and (r.a, r.b) in drop_relations:
            continue
        active_relations.append(r)

    lines = [
        f"[out:json][timeout:{timeout}];",
        f"// TraceSpot Query for: {query_obj.area}",
    ]

    # 1. Fetch Primary Entity candidates into .primary
    lines.append(f"// Entity 1: {primary_entity.name} ({', '.join(primary_entity.tags)})")
    lines.append(f"(")
    for tag in primary_entity.tags:
        t_filter = build_tag_filter([tag])
        lines.append(f"  node{spatial_filter}{t_filter};")
        lines.append(f"  way{spatial_filter}{t_filter};")
    lines.append(f")->.primary;")

    # 2. Fetch Relational context entities if relations exist
    rel_sets = []
    for idx, rel in enumerate(active_relations, start=1):
        ref_id = rel.b if rel.a == primary_id else rel.a
        ref_entity = entities.get(ref_id)
        if not ref_entity:
            continue

        ref_set_name = f"rel_{ref_id}"
        if ref_set_name not in rel_sets:
            lines.append(f"// Entity {ref_id}: {ref_entity.name} ({', '.join(ref_entity.tags)})")
            lines.append(f"(")
            for tag in ref_entity.tags:
                t_filter = build_tag_filter([tag])
                lines.append(f"  node{spatial_filter}{t_filter};")
                lines.append(f"  way{spatial_filter}{t_filter};")
            lines.append(f")->.{ref_set_name};")
            rel_sets.append(ref_set_name)


    # 3. Filter primary entities around each related entity
    if active_relations and rel_sets:
        filter_expr = ""
        for rel in active_relations:
            ref_id = rel.b if rel.a == primary_id else rel.a
            dist = rel.distance_m if rel.distance_m is not None else int((rel.time_min or 10) * 100)
            if distance_override and (rel.a, rel.b) in distance_override:
                dist = distance_override[(rel.a, rel.b)]
            ref_set_name = f"rel_{ref_id}"
            filter_expr += f"(around.{ref_set_name}: {dist})"

        lines.append(f"// Filter primary entities satisfying proximity constraints")
        lines.append(f"(")
        lines.append(f"  node.primary{filter_expr};")
        lines.append(f"  way.primary{filter_expr};")
        lines.append(f")->.matched_primary;")

        # Output both matched primary entities and the reference entities that matched them
        lines.append(f"// Return matched primary items and surrounding context items")
        lines.append(f"(")
        lines.append(f"  .matched_primary;")
        for rel in active_relations:
            ref_id = rel.b if rel.a == primary_id else rel.a
            dist = rel.distance_m if rel.distance_m is not None else int((rel.time_min or 10) * 100)
            if distance_override and (rel.a, rel.b) in distance_override:
                dist = distance_override[(rel.a, rel.b)]
            lines.append(f"  node.rel_{ref_id}(around.matched_primary: {dist});")
            lines.append(f"  way.rel_{ref_id}(around.matched_primary: {dist});")
        lines.append(f");")
    else:
        # Single entity query
        lines.append(f"// Return primary items")
        lines.append(f"(")
        lines.append(f"  .primary;")
        lines.append(f");")

    lines.append(f"out center {max_results};")
    return "\n".join(lines)


async def execute_overpass_query(ql_query: str) -> Dict[str, Any]:
    """
    Executes Overpass QL against mirrors with failover, retries, and local caching.
    """
    # 1. Check Cache
    query_hash = hashlib.sha256(ql_query.encode("utf-8")).hexdigest()
    cached = get_cached_overpass(query_hash)
    if cached:
        return cached

    # 2. Iterate through mirrors with polite backoff
    last_error = None
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Referer": "https://tracespot-8ev9.onrender.com"
    }

    for mirror in OVERPASS_MIRRORS:
        try:
            async with httpx.AsyncClient(timeout=3.5) as client:
                resp = await client.post(mirror, data={"data": ql_query}, headers=headers)

                if resp.status_code == 200:
                    data = resp.json()
                    # Cache successful response
                    set_cached_overpass(query_hash, data)
                    return data
                elif resp.status_code == 429:
                    last_error = f"Mirror {mirror} returned status 429 (rate limited)"
                    continue
                elif resp.status_code == 504:
                    last_error = f"Mirror {mirror} returned status 504 (timeout)"
                    continue
                else:
                    last_error = f"Mirror {mirror} returned error {resp.status_code}: {resp.text[:150]}"
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            last_error = f"Mirror {mirror} connection error: {str(exc)}"
            continue

    raise OverpassError(f"All Overpass mirrors failed or timed out. Last error: {last_error}")


async def fetch_places_via_nominatim(
    tags: List[str],
    lat: float,
    lon: float,
    radius_km: float = 4.0,
    limit: int = 25,
    concept_name: str = ""
) -> List[Dict[str, Any]]:
    """
    High-speed OpenStreetMap Nominatim candidate retrieval.
    Translates results into standard OSM element dictionaries compatible with Overpass.
    """
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(0.2, math.cos(math.radians(lat))))
    left, top, right, bottom = lon - dlon, lat + dlat, lon + dlon, lat - dlat
    viewbox = f"{left:.5f},{top:.5f},{right:.5f},{bottom:.5f}"

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json"
    }

    elements: List[Dict[str, Any]] = []
    seen_ids = set()

    for tag in tags:
        key, val = (tag.split("=", 1) if "=" in tag else (tag, ""))
        params = {
            "viewbox": viewbox,
            "bounded": 1,
            "format": "jsonv2",
            "limit": limit
        }
        if key == "amenity" and val:
            params["amenity"] = val
        else:
            search_term = concept_name or val.replace("_", " ") or key
            params["q"] = search_term

        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.get("https://nominatim.openstreetmap.org/search", params=params, headers=headers)
                if resp.status_code == 200:
                    places = resp.json()
                    for p in places:
                        osm_id = str(p.get("osm_id", ""))
                        if not osm_id or osm_id in seen_ids:
                            continue
                        seen_ids.add(osm_id)

                        raw_name = p.get("name") or (p.get("display_name", "").split(",")[0] if p.get("display_name") else "Place")
                        p_lat = float(p.get("lat", 0.0))
                        p_lon = float(p.get("lon", 0.0))
                        osm_type = p.get("osm_type", "node")

                        elem_tags = {
                            "name": raw_name,
                            key: val if val else p.get("type", ""),
                            p.get("category", "amenity"): p.get("type", "")
                        }
                        if p.get("category") == "amenity":
                            elem_tags["amenity"] = p.get("type", "")

                        elements.append({
                            "type": osm_type,
                            "id": int(osm_id) if osm_id.isdigit() else osm_id,
                            "lat": p_lat,
                            "lon": p_lon,
                            "tags": elem_tags
                        })
        except Exception:
            pass

        if len(elements) >= limit:
            break

    return elements


async def search_with_auto_relax(
    query_obj: TraceSpotQuery,
    spatial_target: Union[Tuple[float, float], Tuple[float, float, float, float]]
) -> Tuple[Dict[str, Any], str, str]:
    """
    Executes search with auto-relaxation and zero-crash Nominatim fallback:
    1. Try Overpass with initial constraints
    2. If 0 results, relax distance (2.5x) or expand radius (to 8km)
    3. If Overpass fails or still 0 results, fall back to Nominatim with Python proximity filtering.
    """
    from backend.routing import haversine_m

    lat_c, lon_c = spatial_target[:2] if len(spatial_target) == 2 else ((spatial_target[0] + spatial_target[2]) / 2, (spatial_target[1] + spatial_target[3]) / 2)

    overpass_failed = False
    ql_initial = build_overpass_ql(query_obj, spatial_target)
    res = {"elements": []}

    try:
        res = await execute_overpass_query(ql_initial)
        elements = res.get("elements", [])
        if len(elements) > 0:
            return res, ql_initial, ""
    except OverpassError:
        overpass_failed = True

    # If Overpass is alive but returned 0 results:
    if not overpass_failed:
        # Stage 1: Auto-Relax - Widen distance by 2.5x
        if query_obj.relations:
            dist_override = {}
            for r in query_obj.relations:
                r_dist = r.distance_m if r.distance_m is not None else int((r.time_min or 5) * 80)
                new_dist = min(int(r_dist * 2.5), 1500)
                dist_override[(r.a, r.b)] = new_dist
            ql_relaxed_dist = build_overpass_ql(query_obj, spatial_target, distance_override=dist_override)
            try:
                res_relaxed = await execute_overpass_query(ql_relaxed_dist)
                if len(res_relaxed.get("elements", [])) > 0:
                    orig_dist = query_obj.relations[0].distance_m or 300
                    new_d = dist_override.get((query_obj.relations[0].a, query_obj.relations[0].b), orig_dist * 2)
                    msg = f"Auto-relaxed distance from {orig_dist}m to {new_d}m to find nearby matches."
                    return res_relaxed, ql_relaxed_dist, msg
            except OverpassError:
                overpass_failed = True

        # Stage 2: Widen spatial radius to 8km
        if not overpass_failed:
            ql_wider = build_overpass_ql(query_obj, spatial_target, radius_m=8000)
            try:
                res_wider = await execute_overpass_query(ql_wider)
                if len(res_wider.get("elements", [])) > 0:
                    return res_wider, ql_wider, "Expanded search area radius to 8km around city center."
            except OverpassError:
                overpass_failed = True

    # Stage 3: Universal Nominatim Fallback (Zero crash guarantee)
    primary_entity = query_obj.entities[0]
    primary_cands = await fetch_places_via_nominatim(
        tags=primary_entity.tags,
        lat=lat_c,
        lon=lon_c,
        radius_km=6.0,
        limit=30,
        concept_name=primary_entity.name
    )

    if not primary_cands:
        primary_cands = await fetch_places_via_nominatim(
            tags=primary_entity.tags,
            lat=lat_c,
            lon=lon_c,
            radius_km=12.0,
            limit=25,
            concept_name=primary_entity.name
        )

    if not query_obj.relations or not primary_cands:
        return {"elements": primary_cands}, ql_initial, "Retrieved live OpenStreetMap places via high-speed Nominatim index."

    # If query has relations (e.g. restaurant near beach), fetch related entities and match in Python
    rel_entity = query_obj.entities[1] if len(query_obj.entities) > 1 else query_obj.entities[0]
    rel_cands = await fetch_places_via_nominatim(
        tags=rel_entity.tags,
        lat=lat_c,
        lon=lon_c,
        radius_km=10.0,
        limit=20,
        concept_name=rel_entity.name
    )

    max_dist = query_obj.relations[0].distance_m or 300
    matched_primary = []
    matched_rel = []

    # Try matching within strict distance or relaxed distance
    for max_d in [max_dist, max_dist * 2.5, 1200]:
        matched_primary.clear()
        matched_rel.clear()
        for p in primary_cands:
            for r in rel_cands:
                d = haversine_m(p["lat"], p["lon"], r["lat"], r["lon"])
                if d <= max_d:
                    if p not in matched_primary:
                        matched_primary.append(p)
                    if r not in matched_rel:
                        matched_rel.append(r)
        if matched_primary:
            break

    if matched_primary:
        combined = matched_primary + matched_rel
        return {"elements": combined}, ql_initial, f"Auto-matched nearby {rel_entity.name} in OpenStreetMap via spatial proximity index."
    else:
        return {"elements": primary_cands}, ql_initial, f"Showing closest {primary_entity.name}s in {query_obj.area} (no exact match directly beside {rel_entity.name})."


async def query_nearby_essentials(lat: float, lon: float, radius_m: int = 500) -> Dict[str, Any]:
    """
    Executes a fast single Overpass query to count essential amenities within radius_m (500m):
    - Pharmacies: amenity=pharmacy
    - Supermarkets / Groceries: shop=supermarket, shop=convenience, shop=grocery
    - Transit stops: highway=bus_stop, railway=station|subway_entrance|tram_stop
    """
    ql = f"""[out:json][timeout:10];
(
  node["amenity"="pharmacy"](around:{radius_m},{lat:.6f},{lon:.6f});
  way["amenity"="pharmacy"](around:{radius_m},{lat:.6f},{lon:.6f});
  node["shop"~"supermarket|convenience|grocery"](around:{radius_m},{lat:.6f},{lon:.6f});
  way["shop"~"supermarket|convenience|grocery"](around:{radius_m},{lat:.6f},{lon:.6f});
  node["highway"="bus_stop"](around:{radius_m},{lat:.6f},{lon:.6f});
  node["railway"~"station|subway_entrance|tram_stop"](around:{radius_m},{lat:.6f},{lon:.6f});
);
out tags;
"""
    try:
        data = await execute_overpass_query(ql)
    except Exception as e:
        return {
            "lat": lat,
            "lon": lon,
            "radius_m": radius_m,
            "pharmacies": 0,
            "supermarkets": 0,
            "transit": 0,
            "total": 0,
            "error": str(e)
        }

    elements = data.get("elements", [])
    pharmacy_count = 0
    supermarket_count = 0
    transit_count = 0

    for el in elements:
        t = el.get("tags", {})
        if t.get("amenity") == "pharmacy":
            pharmacy_count += 1
        if t.get("shop") in ["supermarket", "convenience", "grocery"]:
            supermarket_count += 1
        if t.get("highway") == "bus_stop" or t.get("railway") in ["station", "subway_entrance", "tram_stop"]:
            transit_count += 1

    return {
        "lat": lat,
        "lon": lon,
        "radius_m": radius_m,
        "pharmacies": pharmacy_count,
        "supermarkets": supermarket_count,
        "transit": transit_count,
        "total": pharmacy_count + supermarket_count + transit_count
    }


async def search_time_based_with_isochrone(
    query_obj: TraceSpotQuery,
    spatial_target: Tuple[float, float],
    time_min_override: Optional[int] = None,
    radius_m: int = 3500
) -> Dict[str, Any]:
    """
    Search flow for Feature 1 (Time-based search):
    1. Finds anchor objects (e.g. metro stations) via Overpass around spatial_target
    2. Computes walking reach area (Valhalla isochrone polygon, or fallback circle) around anchors
    3. Finds candidate objects (e.g. pharmacies) inside the polygons using shapely
    4. Ranks candidates by actual walking time from the nearest anchor
    5. Returns (ranked_places, reach_geojson, executed_ql, routing_source, relaxation_msg, anchors)
    """
    from backend.ranker import element_matches_tags, get_element_coords, generate_verification_links
    from backend.routing import get_walking_isochrone, get_walking_route, point_in_isochrone_geojson, haversine_m

    lat_center, lon_center = spatial_target

    # Determine time limit
    time_min = time_min_override
    if time_min is None:
        if query_obj.relations and query_obj.relations[0].time_min:
            time_min = query_obj.relations[0].time_min
        else:
            time_min = 10

    primary_entity = query_obj.entities[0]
    anchor_entity = query_obj.entities[1] if len(query_obj.entities) > 1 else query_obj.entities[0]

    # Build Overpass QL to fetch primary candidates and anchors
    ql_lines = [
        f"[out:json][timeout:25];",
        f"// Feature 1 Time-based: {primary_entity.name} within {time_min} min walk of {anchor_entity.name} in {query_obj.area}",
        "("
    ]
    for tag in primary_entity.tags:
        t_filter = build_tag_filter([tag])
        ql_lines.append(f"  node(around:{radius_m}, {lat_center:.5f}, {lon_center:.5f}){t_filter};")
        ql_lines.append(f"  way(around:{radius_m}, {lat_center:.5f}, {lon_center:.5f}){t_filter};")
    for tag in anchor_entity.tags:
        t_filter = build_tag_filter([tag])
        ql_lines.append(f"  node(around:{radius_m}, {lat_center:.5f}, {lon_center:.5f}){t_filter};")
        ql_lines.append(f"  way(around:{radius_m}, {lat_center:.5f}, {lon_center:.5f}){t_filter};")
    ql_lines.append(");")
    ql_lines.append("out center 60;")
    executed_ql = "\n".join(ql_lines)

    try:
        raw_res = await execute_overpass_query(executed_ql)
        elements = raw_res.get("elements", [])
    except Exception:
        primary_el = await fetch_places_via_nominatim(primary_entity.tags, lat_center, lon_center, radius_km=5.0, concept_name=primary_entity.name)
        anchor_el = await fetch_places_via_nominatim(anchor_entity.tags, lat_center, lon_center, radius_km=5.0, concept_name=anchor_entity.name)
        elements = primary_el + anchor_el

    raw_candidates = []
    raw_anchors = []

    for el in elements:
        coords = get_element_coords(el)
        if not coords:
            continue
        p_lat, p_lon = coords
        tags = el.get("tags", {})
        osm_id = str(el.get("id"))
        osm_type = el.get("type", "node")
        dist_to_center = haversine_m(p_lat, p_lon, lat_center, lon_center)

        is_primary = element_matches_tags(tags, primary_entity.tags)
        is_anchor = element_matches_tags(tags, anchor_entity.tags)

        # Distinguish between anchor and candidate if different entities
        if primary_entity.id != anchor_entity.id:
            if is_anchor:
                raw_anchors.append({
                    "id": f"{osm_type}_{osm_id}",
                    "osm_id": osm_id,
                    "osm_type": osm_type,
                    "name": tags.get("name") or tags.get("description") or f"Nearest {anchor_entity.name.title()}",
                    "lat": p_lat,
                    "lon": p_lon,
                    "tags": tags,
                    "dist_to_center": dist_to_center
                })
            elif is_primary:
                raw_candidates.append({
                    "id": f"{osm_type}_{osm_id}",
                    "osm_id": osm_id,
                    "osm_type": osm_type,
                    "name": tags.get("name") or tags.get("description") or f"Unnamed {primary_entity.name.title()}",
                    "primary_type": primary_entity.name,
                    "lat": p_lat,
                    "lon": p_lon,
                    "tags": tags,
                    "dist_to_center": dist_to_center,
                    "verification_links": generate_verification_links(osm_type, osm_id, p_lat, p_lon, tags)
                })
        else:
            if is_primary:
                raw_candidates.append({
                    "id": f"{osm_type}_{osm_id}",
                    "osm_id": osm_id,
                    "osm_type": osm_type,
                    "name": tags.get("name") or tags.get("description") or f"Unnamed {primary_entity.name.title()}",
                    "primary_type": primary_entity.name,
                    "lat": p_lat,
                    "lon": p_lon,
                    "tags": tags,
                    "dist_to_center": dist_to_center,
                    "verification_links": generate_verification_links(osm_type, osm_id, p_lat, p_lon, tags)
                })

    # Sort anchors by distance to city center; keep top 3-4
    raw_anchors.sort(key=lambda x: x["dist_to_center"])
    anchors = raw_anchors[:4]

    # Fallback anchor if none found in OSM
    if not anchors:
        anchors = [{
            "id": "anchor_center",
            "osm_id": "0",
            "osm_type": "node",
            "name": f"{query_obj.area} Central Area",
            "lat": lat_center,
            "lon": lon_center,
            "tags": {"name": f"{query_obj.area} Central Area"},
            "dist_to_center": 0.0
        }]

    # Compute walking reach isochrone polygons around anchors
    all_reach_features = []
    routing_source = "Valhalla"

    # Multi-ring isochrone contours (e.g. 5m and 10m rings if time_min <= 10)
    contours_to_fetch = [time_min, min(time_min * 2, 20)] if time_min <= 10 else [time_min]

    for a in anchors:
        iso_res = await get_walking_isochrone(a["lat"], a["lon"], contours_to_fetch)
        routing_source = iso_res.get("source", routing_source)
        for feat in iso_res.get("features", []):
            feat_props = feat.setdefault("properties", {})
            feat_props["anchor_name"] = a["name"]
            feat_props["anchor_lat"] = a["lat"]
            feat_props["anchor_lon"] = a["lon"]
            all_reach_features.append(feat)

    reach_geojson = {
        "type": "FeatureCollection",
        "source": routing_source,
        "features": all_reach_features
    }

    # Filter candidates strictly inside the reach polygons using shapely
    matched_candidates = []
    for cand in raw_candidates:
        if point_in_isochrone_geojson(cand["lat"], cand["lon"], reach_geojson):
            matched_candidates.append(cand)

    relaxation_msg = ""
    # Auto-relax if no candidates fall strictly inside the polygon
    if not matched_candidates:
        # Fallback to closest candidates to any anchor
        raw_candidates.sort(key=lambda c: min(haversine_m(c["lat"], c["lon"], a["lat"], a["lon"]) for a in anchors) if anchors else c["dist_to_center"])
        candidates_to_rank = raw_candidates[:12]
        relaxation_msg = f"Auto-relaxed reach limit beyond {time_min} min walk to include closest available {primary_entity.name}s."
    else:
        candidates_to_rank = matched_candidates

    # Rank candidates by actual walking time from the closest anchor
    ranked_results = []
    for cand in candidates_to_rank:
        # Find closest anchor to this candidate
        best_anchor = min(anchors, key=lambda a: haversine_m(cand["lat"], cand["lon"], a["lat"], a["lon"]))
        route_res = await get_walking_route(best_anchor["lat"], best_anchor["lon"], cand["lat"], cand["lon"])

        walking_dur = route_res["duration_min"]
        walking_dist = route_res["distance_m"]
        route_src = route_res["source"]
        route_coords = route_res["coordinates"]

        # Satisfaction score
        dur_ratio = min(walking_dur / (time_min * 1.4), 1.0)
        score = max(0.40, round(1.0 - dur_ratio * 0.45, 2))

        why_matched = f"{walking_dur} min walk ({walking_dist} m) from {best_anchor['name']} ({anchor_entity.name})"
        if route_src != "Valhalla":
            why_matched += f" [{route_src}]"

        cand_entry = {
            "id": cand["id"],
            "osm_id": cand["osm_id"],
            "osm_type": cand["osm_type"],
            "name": cand["name"],
            "primary_type": primary_entity.name,
            "lat": cand["lat"],
            "lon": cand["lon"],
            "tags": cand["tags"],
            "score": score,
            "walking_time_min": walking_dur,
            "walking_distance_m": walking_dist,
            "walk_time_min": walking_dur,
            "walk_distance_m": walking_dist,
            "routing_source": route_src,
            "anchor_name": best_anchor["name"],
            "anchor_coords": [best_anchor["lat"], best_anchor["lon"]],
            "route_coordinates": route_coords,
            "related_matches": [{
                "name": best_anchor["name"],
                "type": anchor_entity.name,
                "distance_m": walking_dist,
                "lat": best_anchor["lat"],
                "lon": best_anchor["lon"],
                "relation_line": [[cand["lat"], cand["lon"]], [best_anchor["lat"], best_anchor["lon"]]]
            }],
            "why_matched": why_matched,
            "verification_links": cand["verification_links"]
        }
        ranked_results.append(cand_entry)

    # Sort ascending by actual walking time
    ranked_results.sort(key=lambda x: x["walking_time_min"])

    return {
        "status": "success",
        "time_search_mode": True,
        "time_min": time_min,
        "area": query_obj.area,
        "primary_entity": primary_entity.name,
        "anchor_entity": anchor_entity.name,
        "results_count": len(ranked_results),
        "results": ranked_results,
        "isochrone_geojson": reach_geojson,
        "anchors": anchors,
        "routing_source": routing_source,
        "relaxation_applied": relaxation_msg,
        "overpass_ql": executed_ql
    }

