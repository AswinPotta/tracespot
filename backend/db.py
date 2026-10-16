"""
TraceSpot SQLite Database Layer (db.py)
Manages search history, saved spots board, and local caching for
Nominatim geocoding and Overpass query responses.
"""

import sqlite3
import json
import time
from typing import List, Dict, Any, Optional

DB_PATH = "tracespot.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # Search history table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS search_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        query_text TEXT NOT NULL,
        parsed_json TEXT NOT NULL,
        detected_lang TEXT DEFAULT 'en',
        result_count INTEGER DEFAULT 0,
        relaxation_applied TEXT DEFAULT '',
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Saved spots board table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS saved_spots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        spot_name TEXT NOT NULL,
        lat REAL NOT NULL,
        lon REAL NOT NULL,
        tags_json TEXT NOT NULL,
        query_text TEXT NOT NULL,
        status TEXT DEFAULT 'Confirmed',  -- Confirmed / Likely / Rejected
        note TEXT DEFAULT '',
        osm_id TEXT DEFAULT '',
        osm_type TEXT DEFAULT 'node',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Nominatim Geocoding Cache table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS geocode_cache (
        area_query TEXT PRIMARY KEY,
        response_json TEXT NOT NULL,
        created_at REAL NOT NULL
    );
    """)

    # Overpass Query Cache table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS overpass_cache (
        query_hash TEXT PRIMARY KEY,
        response_json TEXT NOT NULL,
        created_at REAL NOT NULL
    );
    """)

    # Walking Routing Cache table (Valhalla isochrones/routes & OSRM)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS routing_cache (
        cache_key TEXT PRIMARY KEY,
        response_json TEXT NOT NULL,
        created_at REAL NOT NULL
    );
    """)

    conn.commit()
    conn.close()


# --- Search History Operations ---
def record_search_history(query_text: str, parsed_json: dict, detected_lang: str, result_count: int, relaxation: str = "") -> int:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO search_history (query_text, parsed_json, detected_lang, result_count, relaxation_applied) VALUES (?, ?, ?, ?, ?)",
        (query_text, json.dumps(parsed_json), detected_lang, result_count, relaxation)
    )
    conn.commit()
    inserted_id = cursor.lastrowid
    conn.close()
    return inserted_id


def get_search_history(limit: int = 30) -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM search_history ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    results = []
    for r in rows:
        results.append({
            "id": r["id"],
            "query_text": r["query_text"],
            "parsed_json": json.loads(r["parsed_json"]),
            "detected_lang": r["detected_lang"],
            "result_count": r["result_count"],
            "relaxation_applied": r["relaxation_applied"],
            "timestamp": r["timestamp"]
        })
    conn.close()
    return results


def clear_search_history():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM search_history")
    conn.commit()
    conn.close()


# --- Saved Spots Board Operations ---
def add_saved_spot(spot_name: str, lat: float, lon: float, tags: dict, query_text: str, status: str = "Confirmed", note: str = "", osm_id: str = "", osm_type: str = "node") -> int:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO saved_spots (spot_name, lat, lon, tags_json, query_text, status, note, osm_id, osm_type)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (spot_name, lat, lon, json.dumps(tags), query_text, status, note, osm_id, osm_type)
    )
    conn.commit()
    inserted_id = cursor.lastrowid
    conn.close()
    return inserted_id


def get_saved_spots() -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM saved_spots ORDER BY id DESC")
    rows = cursor.fetchall()
    results = []
    for r in rows:
        results.append({
            "id": r["id"],
            "spot_name": r["spot_name"],
            "lat": r["lat"],
            "lon": r["lon"],
            "tags": json.loads(r["tags_json"]),
            "query_text": r["query_text"],
            "status": r["status"],
            "note": r["note"],
            "osm_id": r["osm_id"],
            "osm_type": r["osm_type"],
            "created_at": r["created_at"]
        })
    conn.close()
    return results


def update_saved_spot(spot_id: int, status: Optional[str] = None, note: Optional[str] = None) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    if status is not None and note is not None:
        cursor.execute("UPDATE saved_spots SET status = ?, note = ? WHERE id = ?", (status, note, spot_id))
    elif status is not None:
        cursor.execute("UPDATE saved_spots SET status = ? WHERE id = ?", (status, spot_id))
    elif note is not None:
        cursor.execute("UPDATE saved_spots SET note = ? WHERE id = ?", (note, spot_id))
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def delete_saved_spot(spot_id: int) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM saved_spots WHERE id = ?", (spot_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


# --- Caching Operations ---
def get_cached_geocode(area_query: str, max_age_sec: float = 86400 * 7) -> Optional[dict]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT response_json, created_at FROM geocode_cache WHERE area_query = ?", (area_query.lower().strip(),))
    row = cursor.fetchone()
    conn.close()
    if row and (time.time() - row["created_at"] < max_age_sec):
        return json.loads(row["response_json"])
    return None


def set_cached_geocode(area_query: str, data: dict):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO geocode_cache (area_query, response_json, created_at) VALUES (?, ?, ?)",
        (area_query.lower().strip(), json.dumps(data), time.time())
    )
    conn.commit()
    conn.close()


def get_cached_overpass(query_hash: str, max_age_sec: float = 3600 * 24) -> Optional[dict]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT response_json, created_at FROM overpass_cache WHERE query_hash = ?", (query_hash,))
    row = cursor.fetchone()
    conn.close()
    if row and (time.time() - row["created_at"] < max_age_sec):
        return json.loads(row["response_json"])
    return None


def set_cached_overpass(query_hash: str, data: dict):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO overpass_cache (query_hash, response_json, created_at) VALUES (?, ?, ?)",
        (query_hash, json.dumps(data), time.time())
    )
    conn.commit()
    conn.close()


def get_cached_routing(cache_key: str, max_age_sec: float = 3600 * 24 * 7) -> Optional[dict]:
    """Retrieves cached routing result (isochrone or route) if fresh."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT response_json, created_at FROM routing_cache WHERE cache_key = ?", (cache_key,))
    row = cursor.fetchone()
    conn.close()
    if row and (time.time() - row["created_at"] < max_age_sec):
        return json.loads(row["response_json"])
    return None


def set_cached_routing(cache_key: str, data: dict):
    """Caches routing result into SQLite."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO routing_cache (cache_key, response_json, created_at) VALUES (?, ?, ?)",
        (cache_key, json.dumps(data), time.time())
    )
    conn.commit()
    conn.close()


# Initialize database upon import
init_db()
