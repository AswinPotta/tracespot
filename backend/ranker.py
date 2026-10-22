"""
TraceSpot Result Ranker & Spatial Verifier (ranker.py)
Pairs primary matches with surrounding entities, calculates exact Haversine distances,
scores constraint satisfaction and distance fit, constructs 'why it matched' explanations,
and generates verification links (OSM, Wikipedia, Google Street View, Mapillary).
"""

import math
from typing import List, Dict, Any, Optional, Tuple
from ml.schema import TraceSpotQuery


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates great-circle distance between two points in meters."""
    R = 6371000.0  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2))
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


def get_element_coords(el: dict) -> Optional[Tuple[float, float]]:
    """Extracts latitude and longitude from node or way center."""
    if "lat" in el and "lon" in el:
        return float(el["lat"]), float(el["lon"])
    center = el.get("center")
    if center and "lat" in center and "lon" in center:
        return float(center["lat"]), float(center["lon"])
    return None


def generate_verification_links(osm_type: str, osm_id: Any, lat: float, lon: float, tags: dict) -> Dict[str, str]:
    """Generates external verification links for journalism and investigative research."""
    links = {
        "osm": f"https://www.openstreetmap.org/{osm_type}/{osm_id}",
        "street_view": f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}",
        "mapillary": f"https://www.mapillary.com/app/?lat={lat:.6f}&lng={lon:.6f}&z=17",
        "directions_google": f"https://www.google.com/maps/dir/?api=1&destination={lat:.6f},{lon:.6f}",
        "directions_apple": f"https://maps.apple.com/?daddr={lat:.6f},{lon:.6f}",
        "directions_osm": f"https://www.openstreetmap.org/directions?engine=fossgis_osrm_car&route=%3B{lat:.6f}%2C{lon:.6f}",
    }

    if "wikipedia" in tags:
        wiki_tag = str(tags["wikipedia"]).strip()
        if ":" in wiki_tag:
            lang, page = wiki_tag.split(":", 1)
            page_clean = page.replace(" ", "_")
            links["wikipedia"] = f"https://{lang}.wikipedia.org/wiki/{page_clean}"
        else:
            links["wikipedia"] = f"https://en.wikipedia.org/wiki/{wiki_tag.replace(' ', '_')}"

    if "wikidata" in tags:
        wikidata_id = str(tags["wikidata"]).strip()
        links["wikidata"] = f"https://www.wikidata.org/wiki/{wikidata_id}"

    return links


def element_matches_tags(el_tags: dict, target_tags: List[str]) -> bool:
    """Checks whether an element matches any of the target tag key=value requirements."""
    for tt in target_tags:
        if "=" in tt:
            k, v = tt.split("=", 1)
            if el_tags.get(k) == v:
                return True
        elif tt in el_tags:
            return True
    return False


def rank_and_explain_results(
    raw_overpass_data: dict,
    query_obj: TraceSpotQuery
) -> List[Dict[str, Any]]:
    """
    Ranks Overpass elements against the query constraints and produces detailed explanations.
    """
    elements = raw_overpass_data.get("elements", [])
    if not elements:
        return []

    primary_id = query_obj.entities[0].id
    primary_entity = query_obj.entities[0]
    entities_by_id = {e.id: e for e in query_obj.entities}

    # Partition elements into primary candidates and related context items
    primary_elements = []
    context_elements = []

    for el in elements:
        tags = el.get("tags", {})
        coords = get_element_coords(el)
        if not coords:
            continue

        if element_matches_tags(tags, primary_entity.tags):
            primary_elements.append((el, coords))
        else:
            context_elements.append((el, coords))

    # If no elements were classified as primary (e.g. tag overlap), treat first batch as primary
    if not primary_elements:
        for el in elements[:15]:
            coords = get_element_coords(el)
            if coords:
                primary_elements.append((el, coords))

    ranked_results = []

    for prim_el, (p_lat, p_lon) in primary_elements:
        tags = prim_el.get("tags", {})
        osm_id = prim_el.get("id")
        osm_type = prim_el.get("type", "node")
        name = tags.get("name") or tags.get("description") or f"Unnamed {primary_entity.name.title()}"

        relations_satisfied = 0
        total_relations = len(query_obj.relations)
        explanations = []
        matched_related_objects = []

        if total_relations == 0:
            # Single object query
            score = 0.95
            explanations.append(f"Direct match for '{primary_entity.name}' in {query_obj.area}")
        else:
            # Relational search: find closest context item for each relation
            for rel in query_obj.relations:
                target_ref_id = rel.b if rel.a == primary_id else rel.a
                ref_entity = entities_by_id.get(target_ref_id)
                if not ref_entity:
                    continue

                best_dist = float("inf")
                best_ref_el = None
                best_ref_coords = None

                for ctx_el, (c_lat, c_lon) in context_elements:
                    c_tags = ctx_el.get("tags", {})
                    if element_matches_tags(c_tags, ref_entity.tags):
                        dist = haversine_distance_m(p_lat, p_lon, c_lat, c_lon)
                        if dist < best_dist:
                            best_dist = dist
                            best_ref_el = ctx_el
                            best_ref_coords = (c_lat, c_lon)

                # Strict distance verification without slack
                req_dist = rel.distance_m if rel.distance_m is not None else int((rel.time_min or 5) * 80)
                threshold = float(req_dist)
                if best_ref_el and best_dist <= threshold:
                    relations_satisfied += 1
                    ref_name = best_ref_el.get("tags", {}).get("name") or ref_entity.name
                    dist_int = int(round(best_dist))
                    explanations.append(f"{dist_int} m from {ref_name} ({ref_entity.name})")

                    matched_related_objects.append({
                        "entity_id": target_ref_id,
                        "name": ref_name,
                        "type": ref_entity.name,
                        "lat": best_ref_coords[0],
                        "lon": best_ref_coords[1],
                        "distance_m": dist_int,
                        "relation_line": [
                            [p_lat, p_lon],
                            [best_ref_coords[0], best_ref_coords[1]]
                        ]
                    })
                elif best_ref_el:
                    # Found but farther than requested constraint
                    dist_int = int(round(best_dist))
                    ref_name = best_ref_el.get("tags", {}).get("name") or ref_entity.name
                    explanations.append(f"{dist_int} m from {ref_name} (exceeds {req_dist}m constraint)")

            # Compute score
            rel_ratio = relations_satisfied / total_relations if total_relations > 0 else 1.0
            # Distance fit bonus if closer than requested
            if matched_related_objects:
                avg_dist = sum(r["distance_m"] for r in matched_related_objects) / len(matched_related_objects)
                base_req = query_obj.relations[0].distance_m or 300
                dist_penalty = min(avg_dist / (base_req + 1), 1.0) * 0.2
            else:
                dist_penalty = 0.3

            score = max(0.40, round(0.70 * rel_ratio + 0.30 * (1.0 - dist_penalty), 2))

        why_matched = "; ".join(explanations) if explanations else f"Located in {query_obj.area}"
        verification_links = generate_verification_links(osm_type, osm_id, p_lat, p_lon, tags)

        ranked_results.append({
            "id": f"{osm_type}_{osm_id}",
            "osm_id": str(osm_id),
            "osm_type": osm_type,
            "name": name,
            "primary_type": primary_entity.name,
            "lat": p_lat,
            "lon": p_lon,
            "tags": tags,
            "score": score,
            "why_matched": why_matched,
            "relations_satisfied": f"{relations_satisfied}/{total_relations}" if total_relations > 0 else "N/A",
            "verification_links": verification_links,
            "related_matches": matched_related_objects
        })

    # Sort descending by match score
    ranked_results.sort(key=lambda x: x["score"], reverse=True)
    return ranked_results
