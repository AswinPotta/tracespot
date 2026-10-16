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


async def geocode_area(area_name: str) -> Dict[str, Any]:
    """
    Geocodes an area name to coordinates and bounding box using Nominatim.
    Uses SQLite caching to respect Nominatim usage policy (1 request per second).
    """
    cleaned = area_name.strip()
    if not cleaned:
        raise GeocodeError("Search area name cannot be empty.")

    # 1. Check Cache
    cached = get_cached_geocode(cleaned)
    if cached:
        return cached

    # 2. Query Nominatim
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

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(NOMINATIM_URL, params=params, headers=headers)
            if resp.status_code == 429:
                raise GeocodeError("Nominatim rate limit reached. Please wait a moment before re-trying.")
            resp.raise_for_status()
            data = resp.json()
    except httpx.RequestError as exc:
        raise GeocodeError(f"Nominatim network error: {str(exc)}")

    if not data:
        raise GeocodeError(f"Area '{cleaned}' was not found on OpenStreetMap. Check spelling or try a larger neighboring city.")

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
