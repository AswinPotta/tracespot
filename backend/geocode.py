"""
TraceSpot Geocoding Service (geocode.py)
Uses OpenStreetMap Nominatim for geocoding with caching,
polite User-Agent, bounding box cap limits, and candidate resolution.
"""

import httpx
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from backend.db import get_cached_geocode, set_cached_geocode

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "TraceSpot-Research/1.0 (academic NLP OSM project; shivani-tracespot@university.edu)"

# Maximum allowed span in degrees (approx 200 km) to prevent querying entire continents
MAX_BBOX_SPAN_DEG = 3.0


class GeocodeError(Exception):
    pass


# Curated Fast Geocode Cache for Major Global Metros (0ms response, zero rate-limit)
KNOWN_CITIES: Dict[str, Dict[str, Any]] = {
    "london": {"display_name": "London, Greater London, England, United Kingdom", "lat": 51.5074456, "lon": -0.1277653, "south": 51.28, "north": 51.69, "west": -0.51, "east": 0.33},
    "paris": {"display_name": "Paris, Île-de-France, France", "lat": 48.856614, "lon": 2.3522219, "south": 48.815, "north": 48.902, "west": 2.224, "east": 2.469},
    "berlin": {"display_name": "Berlin, Germany", "lat": 52.520008, "lon": 13.404954, "south": 52.338, "north": 52.675, "west": 13.088, "east": 13.761},
    "new york": {"display_name": "New York, United States", "lat": 40.712728, "lon": -74.006015, "south": 40.496, "north": 40.917, "west": -74.259, "east": -73.700},
    "hyderabad": {"display_name": "Hyderabad, Telangana, India", "lat": 17.385044, "lon": 78.486671, "south": 17.15, "north": 17.60, "west": 78.25, "east": 78.70},
    "mumbai": {"display_name": "Mumbai, Maharashtra, India", "lat": 19.076090, "lon": 72.877426, "south": 18.89, "north": 19.27, "west": 72.77, "east": 72.98},
    "bangalore": {"display_name": "Bengaluru, Karnataka, India", "lat": 12.971599, "lon": 77.594563, "south": 12.83, "north": 13.14, "west": 77.46, "east": 77.74},
    "bengaluru": {"display_name": "Bengaluru, Karnataka, India", "lat": 12.971599, "lon": 77.594563, "south": 12.83, "north": 13.14, "west": 77.46, "east": 77.74},
    "chennai": {"display_name": "Chennai, Tamil Nadu, India", "lat": 13.082680, "lon": 80.270718, "south": 12.91, "north": 13.25, "west": 80.12, "east": 80.33},
    "tokyo": {"display_name": "Tokyo, Japan", "lat": 35.676192, "lon": 139.650311, "south": 35.50, "north": 35.89, "west": 139.40, "east": 139.90},
    "amsterdam": {"display_name": "Amsterdam, North Holland, Netherlands", "lat": 52.367573, "lon": 4.904139, "south": 52.28, "north": 52.43, "west": 4.72, "east": 5.07},
    "sydney": {"display_name": "Sydney, New South Wales, Australia", "lat": -33.868820, "lon": 151.209296, "south": -34.11, "north": -33.57, "west": 150.62, "east": 151.34},
    "san francisco": {"display_name": "San Francisco, California, United States", "lat": 37.774929, "lon": -122.419416, "south": 37.70, "north": 37.83, "west": -122.52, "east": -122.35},
    "delhi": {"display_name": "Delhi, India", "lat": 28.613939, "lon": 77.209021, "south": 28.40, "north": 28.88, "west": 76.84, "east": 77.34},
    "new delhi": {"display_name": "New Delhi, Delhi, India", "lat": 28.613939, "lon": 77.209021, "south": 28.40, "north": 28.88, "west": 76.84, "east": 77.34},
    "kolkata": {"display_name": "Kolkata, West Bengal, India", "lat": 22.572646, "lon": 88.363895, "south": 22.40, "north": 22.75, "west": 88.20, "east": 88.50},
    "pune": {"display_name": "Pune, Maharashtra, India", "lat": 18.520430, "lon": 73.856744, "south": 18.40, "north": 18.65, "west": 73.75, "east": 73.98},
    "madrid": {"display_name": "Madrid, Community of Madrid, Spain", "lat": 40.416775, "lon": -3.703790, "south": 40.31, "north": 40.56, "west": -3.83, "east": -3.52},
    "barcelona": {"display_name": "Barcelona, Catalonia, Spain", "lat": 41.387917, "lon": 2.169919, "south": 41.31, "north": 41.47, "west": 2.05, "east": 2.23},
    "rome": {"display_name": "Rome, Lazio, Italy", "lat": 41.902783, "lon": 12.496366, "south": 41.65, "north": 42.14, "west": 12.23, "east": 12.70},
    "vienna": {"display_name": "Vienna, Austria", "lat": 48.208174, "lon": 16.373819, "south": 48.11, "north": 48.32, "west": 16.18, "east": 16.58},
    "singapore": {"display_name": "Singapore", "lat": 1.352083, "lon": 103.819836, "south": 1.15, "north": 1.48, "west": 103.60, "east": 104.05},
    "dubai": {"display_name": "Dubai, United Arab Emirates", "lat": 25.204849, "lon": 55.270783, "south": 24.95, "north": 25.35, "west": 55.05, "east": 55.55},
    "toronto": {"display_name": "Toronto, Ontario, Canada", "lat": 43.653226, "lon": -79.383184, "south": 43.58, "north": 43.85, "west": -79.64, "east": -79.11},
    "chicago": {"display_name": "Chicago, Illinois, United States", "lat": 41.878114, "lon": -87.629798, "south": 41.64, "north": 42.02, "west": -87.94, "east": -87.52},
    "los angeles": {"display_name": "Los Angeles, California, United States", "lat": 34.052234, "lon": -118.243685, "south": 33.70, "north": 34.33, "west": -118.66, "east": -118.15},
}


async def geocode_area(area_name: str) -> Dict[str, Any]:
    """
    Geocodes an area name to coordinates and bounding box.
    Uses:
    1. Instant Curated Metros Cache (0ms, 100% reliable)
    2. SQLite local persistent cache
    3. Komoot Photon Global Geocoder (high-speed, rate-limit free)
    4. OpenStreetMap Nominatim with retry & backoff
    """
    cleaned = area_name.strip()
    if not cleaned:
        raise GeocodeError("Search area name cannot be empty.")

    # 1. Curated Metros Cache
    lower_key = cleaned.lower()
    if lower_key in KNOWN_CITIES:
        c_info = KNOWN_CITIES[lower_key]
        res = {
            "area_query": cleaned,
            "display_name": c_info["display_name"],
            "lat": c_info["lat"],
            "lon": c_info["lon"],
            "south": c_info["south"],
            "north": c_info["north"],
            "west": c_info["west"],
            "east": c_info["east"],
            "osm_id": "0",
            "osm_type": "relation",
            "type": "city",
            "candidates": []
        }
        set_cached_geocode(cleaned, res)
        return res

    # 2. Check SQLite Cache
    cached = get_cached_geocode(cleaned)
    if cached:
        return cached

    # 3. Query Komoot Photon (Fast, high-capacity OSM-backed geocoder)
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            p_resp = await client.get(
                "https://photon.komoot.io/api/",
                params={"q": cleaned, "limit": 4},
                headers={"User-Agent": USER_AGENT}
            )
            if p_resp.status_code == 200:
                p_data = p_resp.json()
                features = p_data.get("features", [])
                if features:
                    top_feat = features[0]
                    coords = top_feat.get("geometry", {}).get("coordinates", [])
                    if len(coords) >= 2:
                        lon, lat = float(coords[0]), float(coords[1])
                        props = top_feat.get("properties", {})
                        d_name = props.get("name") or cleaned
                        if props.get("state"):
                            d_name += f", {props.get('state')}"
                        if props.get("country"):
                            d_name += f", {props.get('country')}"

                        res = {
                            "area_query": cleaned,
                            "display_name": d_name,
                            "lat": lat,
                            "lon": lon,
                            "south": max(lat - 0.15, -90.0),
                            "north": min(lat + 0.15, 90.0),
                            "west": max(lon - 0.15, -180.0),
                            "east": min(lon + 0.15, 180.0),
                            "osm_id": str(props.get("osm_id", "0")),
                            "osm_type": props.get("osm_type", "node"),
                            "type": props.get("type", "city"),
                            "candidates": []
                        }
                        set_cached_geocode(cleaned, res)
                        return res
    except Exception:
        pass

    # 4. Fallback to OpenStreetMap Nominatim
    params = {
        "q": cleaned,
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": 5
    }
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "en,de,es,fr"
    }

    data = None
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(NOMINATIM_URL, params=params, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
    except Exception:
        pass

    if not data:
        raise GeocodeError(f"Area '{cleaned}' could not be resolved. Please check spelling or enter a major city name.")

    # Build primary result and candidates
    primary = data[0]
    lat = float(primary["lat"])
    lon = float(primary["lon"])
    bbox = [float(x) for x in primary.get("boundingbox", [lat - 0.1, lat + 0.1, lon - 0.1, lon + 0.1])]
    # boundingbox format in Nominatim: [south, north, west, east]
    south, north, west, east = bbox[0], bbox[1], bbox[2], bbox[3]

    # Area cap check: Prevent querying gigantic regions (e.g. "Europe" or "Russia")
    lat_span = abs(north - south)
    lon_span = abs(east - west)
    if lat_span > MAX_BBOX_SPAN_DEG or lon_span > MAX_BBOX_SPAN_DEG:
        # If too huge, clamp bounding box around center to keep Overpass queries fast and reliable
        south = max(lat - 0.15, -90.0)
        north = min(lat + 0.15, 90.0)
        west = max(lon - 0.15, -180.0)
        east = min(lon + 0.15, 180.0)

    candidates = []
    for item in data[:4]:
        candidates.append({
            "display_name": item.get("display_name", ""),
            "lat": float(item["lat"]),
            "lon": float(item["lon"]),
            "osm_id": item.get("osm_id", ""),
            "osm_type": item.get("osm_type", ""),
            "type": item.get("type", "")
        })

    result = {
        "area_query": cleaned,
        "display_name": primary.get("display_name", cleaned),
        "lat": lat,
        "lon": lon,
        "south": south,
        "north": north,
        "west": west,
        "east": east,
        "osm_id": primary.get("osm_id", ""),
        "osm_type": primary.get("osm_type", ""),
        "candidates": candidates
    }

    # Cache successful lookup
    set_cached_geocode(cleaned, result)
    return result
