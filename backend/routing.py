"""
TraceSpot Walking-Time & Isochrone Routing Service (backend/routing.py)
Provides pedestrian walking routing and isochrone reachability using:
1. Valhalla public instance (valhalla1.openstreetmap.de) for isochrones and routes
2. FOSSGIS OSRM foot profile (routing.openstreetmap.de/routed-foot) for routes and table matrix
3. Straight-line fallback at 83 m/min (5 km/h) clearly labeled "estimated" in the UI.

Includes local SQLite + memory caching, timeouts, retries, polite User-Agent, and concurrency limiting.
"""

import math
import json
import time
import asyncio
import hashlib
from typing import List, Dict, Any, Optional, Tuple, Union
import httpx
from shapely.geometry import shape, Point, Polygon, MultiPolygon

from backend.db import get_cached_routing, set_cached_routing

VALHALLA_BASE = "https://valhalla1.openstreetmap.de"
OSRM_FOOT_BASE = "https://routing.openstreetmap.de/routed-foot"

USER_AGENT = "TraceSpot-WalkingService/2.0 (academic NLP OSM research; tracespot@university.edu)"
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json",
    "Content-Type": "application/json"
}

WALKING_SPEED_M_PER_MIN = 83.33  # 5.0 km/h = 83.33 meters/min

# Concurrency semaphore to respect public OSM servers
_SEMAPHORE = asyncio.Semaphore(4)
_MEMORY_CACHE: Dict[str, Any] = {}


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates great-circle distance between two coordinates in meters."""
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * (math.sin(dlam / 2.0) ** 2)
    return R * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def decode_polyline6(encoded: str) -> List[List[float]]:
    """
    Decodes a Valhalla 6-digit precision polyline string into [[lat, lon], ...].
    """
    points = []
    index = 0
    lat = 0
    lon = 0
    length = len(encoded)

    while index < length:
        # Decode latitude
        shift = 0
        result = 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlat = ~(result >> 1) if (result & 1) else (result >> 1)
        lat += dlat

        # Decode longitude
        shift = 0
        result = 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlon = ~(result >> 1) if (result & 1) else (result >> 1)
        lon += dlon

        points.append([lat / 1e6, lon / 1e6])

    return points


def create_circular_isochrone_polygon(lat: float, lon: float, time_min: int, num_points: int = 48) -> Dict[str, Any]:
    """
    Constructs a fallback circular polygon around a point at 83.33 m/min walking speed.
    Returns GeoJSON Feature.
    """
    radius_m = time_min * WALKING_SPEED_M_PER_MIN
    coords = []
    for i in range(num_points):
        angle = (2.0 * math.pi * i) / num_points
        # 1 deg latitude ~ 111,320m
        dlat = (radius_m * math.cos(angle)) / 111320.0
        # 1 deg longitude ~ 111,320m * cos(lat)
        dlon = (radius_m * math.sin(angle)) / (111320.0 * max(0.1, math.cos(math.radians(lat))))
        coords.append([round(lon + dlon, 6), round(lat + dlat, 6)])
    coords.append(coords[0])  # Close ring

    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [coords]
        },
        "properties": {
            "contour": float(time_min),
            "metric": "time",
            "fill": "#6366f1",
            "source": "estimated"
        }
    }


async def get_walking_isochrone(
    lat: float,
    lon: float,
    times_min: Union[int, List[int]] = 5,
    retries: int = 2
) -> Dict[str, Any]:
    """
    Fetches walking isochrone polygon(s) around (lat, lon) for specified minutes.
    Primary: Valhalla isochrone endpoint.
    Fallback: Estimated circle polygon at 83 m/min walking speed.
    Returns a GeoJSON FeatureCollection with source metadata.
    """
    if isinstance(times_min, int):
        times = [times_min]
    else:
        times = sorted(list(set(times_min)))

    cache_key = f"iso_{lat:.5f}_{lon:.5f}_{'_'.join(str(t) for t in times)}"
    if cache_key in _MEMORY_CACHE:
        return _MEMORY_CACHE[cache_key]

    cached = get_cached_routing(cache_key)
    if cached:
        _MEMORY_CACHE[cache_key] = cached
        return cached

    valhalla_colors = ["#6366f1", "#06b6d4", "#10b981", "#f59e0b"]
    payload = {
        "locations": [{"lat": lat, "lon": lon}],
        "costing": "pedestrian",
        "contours": [
            {"time": t, "color": valhalla_colors[i % len(valhalla_colors)][1:]}
            for i, t in enumerate(times)
        ],
        "polygons": True
    }

    url = f"{VALHALLA_BASE}/isochrone"

    async with _SEMAPHORE:
        for attempt in range(retries):
            try:
                async with httpx.AsyncClient(timeout=9.0) as client:
                    resp = await client.post(url, json=payload, headers=HEADERS)
                    if resp.status_code == 200:
                        data = resp.json()
                        features = data.get("features", [])
                        if features:
                            for f in features:
                                f.setdefault("properties", {})["source"] = "Valhalla"
                            result = {
                                "type": "FeatureCollection",
                                "source": "Valhalla",
                                "features": features
                            }
                            set_cached_routing(cache_key, result)
                            _MEMORY_CACHE[cache_key] = result
                            return result
            except Exception:
                await asyncio.sleep(0.3 * (attempt + 1))

    # Fallback to estimated circular polygons
    features = [create_circular_isochrone_polygon(lat, lon, t) for t in times]
    result = {
        "type": "FeatureCollection",
        "source": "estimated",
        "features": features
    }
    set_cached_routing(cache_key, result)
    _MEMORY_CACHE[cache_key] = result
    return result


async def get_walking_route(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    retries: int = 2
) -> Dict[str, Any]:
    """
    Computes real walking route between two coordinates.
    1. Primary: Valhalla pedestrian route (/route)
    2. Failover: FOSSGIS OSRM foot profile (/routed-foot/route/v1/foot)
    3. Final fallback: Straight-line estimate at 83 m/min (labeled "estimated")
    """
    cache_key = f"route_{lat1:.5f}_{lon1:.5f}_{lat2:.5f}_{lon2:.5f}"
    if cache_key in _MEMORY_CACHE:
        return _MEMORY_CACHE[cache_key]

    cached = get_cached_routing(cache_key)
    if cached:
        _MEMORY_CACHE[cache_key] = cached
        return cached

    straight_dist = haversine_m(lat1, lon1, lat2, lon2)

    # 1. Try Valhalla
    valhalla_url = f"{VALHALLA_BASE}/route"
    valhalla_payload = {
        "locations": [{"lat": lat1, "lon": lon1}, {"lat": lat2, "lon": lon2}],
        "costing": "pedestrian",
        "directions_options": {"units": "kilometers"}
    }

    async with _SEMAPHORE:
        for attempt in range(retries):
            try:
                async with httpx.AsyncClient(timeout=7.0) as client:
                    resp = await client.post(valhalla_url, json=valhalla_payload, headers=HEADERS)
                    if resp.status_code == 200:
                        data = resp.json()
                        trip = data.get("trip", {})
                        summary = trip.get("summary", {})
                        time_sec = summary.get("time", 0)
                        dist_km = summary.get("length", 0)
                        legs = trip.get("legs", [])
                        shape_str = legs[0].get("shape", "") if legs else ""
                        coords = decode_polyline6(shape_str) if shape_str else [[lat1, lon1], [lat2, lon2]]

                        result = {
                            "duration_min": max(1, round(time_sec / 60.0)),
                            "duration_exact_min": round(time_sec / 60.0, 1),
                            "distance_m": round(dist_km * 1000.0),
                            "coordinates": coords,
                            "source": "Valhalla",
                            "geometry": {
                                "type": "LineString",
                                "coordinates": [[c[1], c[0]] for c in coords]
                            }
                        }
                        set_cached_routing(cache_key, result)
                        _MEMORY_CACHE[cache_key] = result
                        return result
            except Exception:
                await asyncio.sleep(0.2)

        # 2. Try FOSSGIS OSRM foot profile
        osrm_url = f"{OSRM_FOOT_BASE}/route/v1/foot/{lon1:.6f},{lat1:.6f};{lon2:.6f},{lat2:.6f}?overview=full&geometries=geojson"
        for attempt in range(retries):
            try:
                async with httpx.AsyncClient(timeout=7.0) as client:
                    resp = await client.get(osrm_url, headers=HEADERS)
                    if resp.status_code == 200:
                        data = resp.json()
                        routes = data.get("routes", [])
                        if routes:
                            rt = routes[0]
                            time_sec = rt.get("duration", 0)
                            dist_m = rt.get("distance", straight_dist)
                            geo_coords = rt.get("geometry", {}).get("coordinates", [])
                            coords = [[c[1], c[0]] for c in geo_coords] if geo_coords else [[lat1, lon1], [lat2, lon2]]

                            result = {
                                "duration_min": max(1, round(time_sec / 60.0)),
                                "duration_exact_min": round(time_sec / 60.0, 1),
                                "distance_m": round(dist_m),
                                "coordinates": coords,
                                "source": "OSRM",
                                "geometry": {
                                    "type": "LineString",
                                    "coordinates": [[c[1], c[0]] for c in coords]
                                }
                            }
                            set_cached_routing(cache_key, result)
                            _MEMORY_CACHE[cache_key] = result
                            return result
            except Exception:
                await asyncio.sleep(0.2)

    # 3. Fallback to Straight-Line Estimate
    dur_min = max(1.0, round(straight_dist / WALKING_SPEED_M_PER_MIN, 1))
    result = {
        "duration_min": max(1, round(dur_min)),
        "duration_exact_min": dur_min,
        "distance_m": round(straight_dist),
        "coordinates": [[lat1, lon1], [lat2, lon2]],
        "source": "estimated",
        "geometry": {
            "type": "LineString",
            "coordinates": [[lon1, lat1], [lon2, lat2]]
        }
    }
    set_cached_routing(cache_key, result)
    _MEMORY_CACHE[cache_key] = result
    return result


async def get_walking_distance_matrix(
    points: List[Tuple[float, float]],
    retries: int = 2
) -> Tuple[List[List[float]], str]:
    """
    Computes an NxN matrix of walking durations (in minutes) between a list of points.
    Used for Itinerary Beam Search optimization.
    1. Primary: FOSSGIS OSRM foot Table API (/routed-foot/table/v1/foot)
    2. Fallback: Straight-line estimate at 83 m/min
    Returns (durations_matrix_in_minutes, source).
    """
    n = len(points)
    if n == 0:
        return [], "OSRM"
    if n == 1:
        return [[0.0]], "OSRM"

    cache_hash = hashlib.sha256(
        json.dumps([[round(lat, 5), round(lon, 5)] for lat, lon in points]).encode()
    ).hexdigest()
    cache_key = f"matrix_{cache_hash}"

    if cache_key in _MEMORY_CACHE:
        return _MEMORY_CACHE[cache_key]["matrix"], _MEMORY_CACHE[cache_key]["source"]

    cached = get_cached_routing(cache_key)
    if cached:
        _MEMORY_CACHE[cache_key] = cached
        return cached["matrix"], cached["source"]

    # Try FOSSGIS OSRM Table API
    coords_param = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in points)
    table_url = f"{OSRM_FOOT_BASE}/table/v1/foot/{coords_param}"

    async with _SEMAPHORE:
        for attempt in range(retries):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(table_url, headers=HEADERS)
                    if resp.status_code == 200:
                        data = resp.json()
                        raw_durations = data.get("durations", [])
                        if len(raw_durations) == n:
                            # Convert seconds to minutes
                            matrix = []
                            for row in raw_durations:
                                matrix.append([
                                    round(sec / 60.0, 2) if sec is not None else 999.0
                                    for sec in row
                                ])
                            res_dict = {"matrix": matrix, "source": "OSRM"}
                            set_cached_routing(cache_key, res_dict)
                            _MEMORY_CACHE[cache_key] = res_dict
                            return matrix, "OSRM"
            except Exception:
                await asyncio.sleep(0.3)

    # Fallback to straight-line matrix
    matrix = []
    for i in range(n):
        row = []
        for j in range(n):
            if i == j:
                row.append(0.0)
            else:
                d = haversine_m(points[i][0], points[i][1], points[j][0], points[j][1])
                row.append(round(d / WALKING_SPEED_M_PER_MIN, 2))
        matrix.append(row)

    res_dict = {"matrix": matrix, "source": "estimated"}
    set_cached_routing(cache_key, res_dict)
    _MEMORY_CACHE[cache_key] = res_dict
    return matrix, "estimated"


def point_in_isochrone_geojson(lat: float, lon: float, isochrone_geojson: Dict[str, Any]) -> bool:
    """
    Uses shapely to verify if a candidate (lat, lon) is strictly within any polygon
    in the isochrone GeoJSON FeatureCollection.
    """
    pt = Point(lon, lat)  # Note: shapely (x, y) = (lon, lat)
    features = isochrone_geojson.get("features", [])
    for feat in features:
        geom_dict = feat.get("geometry", {})
        if not geom_dict:
            continue
        try:
            poly_shape = shape(geom_dict)
            if poly_shape.contains(pt) or poly_shape.touches(pt):
                return True
        except Exception:
            continue
    return False
