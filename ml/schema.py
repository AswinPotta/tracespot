"""
TraceSpot Schema & Tag Whitelist
Defines the Pydantic schema for natural language query representations,
the tag whitelist derived from OpenStreetMap taginfo, and rapidfuzz validation.
Extended in Phase 2 for:
- Time-based search ("time_min", "mode": "walk")
- Sentence-to-itinerary ("itinerary": {"stops": [...], "max_leg_min": 10, "total_max_min": ...})
"""

from typing import List, Optional, Dict, Any
import json
import re
from pydantic import BaseModel, Field, field_validator
from rapidfuzz import process, fuzz

# Whitelist of popular OSM tags with typical categories and frequencies
# Sourced from OpenStreetMap taginfo (taginfo.openstreetmap.org)
OSM_TAG_WHITELIST = {
    # Places of worship & culture
    "amenity=place_of_worship": {"name": "place of worship", "category": "amenity", "count": 1200000},
    "amenity=church": {"name": "church", "category": "amenity", "count": 950000},
    "tourism=museum": {"name": "museum", "category": "tourism", "count": 150000},
    "tourism=attraction": {"name": "tourist attraction", "category": "tourism", "count": 220000},
    "tourism=artwork": {"name": "artwork", "category": "tourism", "count": 180000},
    "tourism=gallery": {"name": "gallery", "category": "tourism", "count": 45000},
    "tourism=viewpoint": {"name": "viewpoint", "category": "tourism", "count": 210000},
    "historic=monument": {"name": "monument", "category": "historic", "count": 120000},
    "historic=memorial": {"name": "memorial", "category": "historic", "count": 480000},
    "historic=castle": {"name": "castle", "category": "historic", "count": 75000},
    "historic=ruins": {"name": "ruins", "category": "historic", "count": 110000},
    "amenity=theatre": {"name": "theatre", "category": "amenity", "count": 60000},
    "amenity=cinema": {"name": "cinema", "category": "amenity", "count": 40000},

    # Health & Social
    "amenity=pharmacy": {"name": "pharmacy", "category": "amenity", "count": 450000},
    "amenity=hospital": {"name": "hospital", "category": "amenity", "count": 190000},
    "amenity=clinic": {"name": "clinic", "category": "amenity", "count": 140000},
    "amenity=doctors": {"name": "doctor", "category": "amenity", "count": 210000},
    "amenity=dentist": {"name": "dentist", "category": "amenity", "count": 130000},
    "amenity=veterinary": {"name": "veterinary", "category": "amenity", "count": 65000},

    # Food, Drink & Leisure
    "amenity=cafe": {"name": "cafe", "category": "amenity", "count": 780000},
    "amenity=restaurant": {"name": "restaurant", "category": "amenity", "count": 1600000},
    "amenity=fast_food": {"name": "fast food", "category": "amenity", "count": 720000},
    "amenity=bar": {"name": "bar", "category": "amenity", "count": 430000},
    "amenity=pub": {"name": "pub", "category": "amenity", "count": 220000},
    "amenity=ice_cream": {"name": "ice cream", "category": "amenity", "count": 55000},
    "leisure=park": {"name": "park", "category": "leisure", "count": 890000},
    "leisure=garden": {"name": "garden", "category": "leisure", "count": 260000},
    "leisure=playground": {"name": "playground", "category": "leisure", "count": 670000},
    "leisure=pitch": {"name": "sports pitch", "category": "leisure", "count": 950000},
    "leisure=sports_centre": {"name": "sports centre", "category": "leisure", "count": 180000},
    "leisure=swimming_pool": {"name": "swimming pool", "category": "leisure", "count": 310000},
    "leisure=dog_park": {"name": "dog park", "category": "leisure", "count": 42000},

    # Nature, Water & Greenery
    "waterway=river": {"name": "river", "category": "waterway", "count": 650000},
    "waterway=canal": {"name": "canal", "category": "waterway", "count": 140000},
    "waterway=stream": {"name": "stream", "category": "waterway", "count": 1800000},
    "natural=water": {"name": "water body", "category": "natural", "count": 2200000},
    "natural=wood": {"name": "forest", "category": "natural", "count": 4500000},
    "natural=tree": {"name": "tree", "category": "natural", "count": 9800000},
    "natural=beach": {"name": "beach", "category": "natural", "count": 130000},
    "natural=coastline": {"name": "coastline", "category": "natural", "count": 89000},

    # Urban micro-features & Furniture
    "amenity=bench": {"name": "bench", "category": "amenity", "count": 3200000},
    "amenity=fountain": {"name": "fountain", "category": "amenity", "count": 240000},
    "amenity=waste_basket": {"name": "trash bin", "category": "amenity", "count": 1400000},
    "amenity=drinking_water": {"name": "drinking water", "category": "amenity", "count": 390000},
    "amenity=toilets": {"name": "public toilet", "category": "amenity", "count": 340000},
    "amenity=shelter": {"name": "shelter", "category": "amenity", "count": 460000},
    "amenity=post_box": {"name": "post box", "category": "amenity", "count": 1100000},
    "amenity=clock": {"name": "public clock", "category": "amenity", "count": 45000},

    # Transport
    "highway=bus_stop": {"name": "bus stop", "category": "highway", "count": 5100000},
    "railway=station": {"name": "train station", "category": "railway", "count": 170000},
    "railway=tram_stop": {"name": "tram stop", "category": "railway", "count": 190000},
    "railway=subway_entrance": {"name": "metro entrance", "category": "railway", "count": 140000},
    "amenity=bus_station": {"name": "bus station", "category": "amenity", "count": 85000},
    "amenity=taxi": {"name": "taxi stand", "category": "amenity", "count": 78000},
    "amenity=parking": {"name": "parking lot", "category": "amenity", "count": 4600000},
    "amenity=bicycle_parking": {"name": "bike rack", "category": "amenity", "count": 1300000},
    "amenity=bicycle_rental": {"name": "bike rental", "category": "amenity", "count": 70000},
    "amenity=fuel": {"name": "gas station", "category": "amenity", "count": 490000},
    "amenity=charging_station": {"name": "EV charger", "category": "amenity", "count": 260000},
    "highway=crossing": {"name": "pedestrian crossing", "category": "highway", "count": 2400000},

    # Education & Civic
    "amenity=school": {"name": "school", "category": "amenity", "count": 1100000},
    "amenity=kindergarten": {"name": "kindergarten", "category": "amenity", "count": 320000},
    "amenity=university": {"name": "university", "category": "amenity", "count": 120000},
    "amenity=college": {"name": "college", "category": "amenity", "count": 80000},
    "amenity=library": {"name": "library", "category": "amenity", "count": 195000},
    "amenity=community_centre": {"name": "community center", "category": "amenity", "count": 210000},
    "amenity=townhall": {"name": "town hall", "category": "amenity", "count": 115000},
    "amenity=police": {"name": "police station", "category": "amenity", "count": 140000},
    "amenity=fire_station": {"name": "fire station", "category": "amenity", "count": 180000},
    "amenity=post_office": {"name": "post office", "category": "amenity", "count": 230000},
    "amenity=courthouse": {"name": "courthouse", "category": "amenity", "count": 35000},

    # Commerce & Services
    "shop=supermarket": {"name": "supermarket", "category": "shop", "count": 890000},
    "shop=convenience": {"name": "convenience store", "category": "shop", "count": 740000},
    "shop=bakery": {"name": "bakery", "category": "shop", "count": 460000},
    "shop=clothes": {"name": "clothing store", "category": "shop", "count": 520000},
    "shop=hairdresser": {"name": "hairdresser", "category": "shop", "count": 410000},
    "shop=butcher": {"name": "butcher", "category": "shop", "count": 180000},
    "shop=books": {"name": "bookstore", "category": "shop", "count": 75000},
    "shop=chemist": {"name": "drugstore", "category": "shop", "count": 85000},
    "shop=florist": {"name": "florist", "category": "shop", "count": 110000},
    "shop=kiosk": {"name": "kiosk", "category": "shop", "count": 140000},
    "amenity=bank": {"name": "bank", "category": "amenity", "count": 490000},
    "amenity=atm": {"name": "atm", "category": "amenity", "count": 410000},
    "amenity=marketplace": {"name": "marketplace", "category": "amenity", "count": 65000},

    # Accommodation
    "tourism=hotel": {"name": "hotel", "category": "tourism", "count": 490000},
    "tourism=hostel": {"name": "hostel", "category": "tourism", "count": 65000},
    "tourism=guest_house": {"name": "guest house", "category": "tourism", "count": 180000},
    "tourism=camp_site": {"name": "campsite", "category": "tourism", "count": 130000},
}

WHITELIST_KEYS = list(OSM_TAG_WHITELIST.keys())


class Entity(BaseModel):
    id: int = Field(..., description="Unique integer entity index starting at 1")
    name: str = Field(..., description="Concept name (e.g. pharmacy, church, bench)")
    tags: List[str] = Field(..., description="OSM tag strings formatted as key=value")

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, v: List[str]) -> List[str]:
        cleaned = []
        for tag in v:
            tag = str(tag).strip()
            if "=" in tag:
                cleaned.append(tag)
        return cleaned


class Relation(BaseModel):
    type: str = Field(default="within", description="Relation type (e.g. within, adjacent, near)")
    a: int = Field(..., description="Entity ID a (subject)")
    b: int = Field(..., description="Entity ID b (reference object)")
    distance_m: Optional[int] = Field(default=None, ge=5, le=5000, description="Maximum distance in meters")
    time_min: Optional[int] = Field(default=None, ge=1, le=120, description="Maximum walking time in minutes")
    mode: Optional[str] = Field(default=None, description="Transport mode (e.g. walk)")


class Stop(BaseModel):
    id: int = Field(..., description="Stop sequence index starting at 1")
    name: str = Field(..., description="Concept name (e.g. cafe, park, restaurant)")
    tags: List[str] = Field(..., description="OSM tag strings formatted as key=value")

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, v: List[str]) -> List[str]:
        cleaned = []
        for tag in v:
            tag = str(tag).strip()
            if "=" in tag:
                cleaned.append(tag)
        return cleaned


class Itinerary(BaseModel):
    stops: List[Stop] = Field(..., min_length=2, description="Ordered sequence of stops")
    max_leg_min: int = Field(default=10, ge=1, le=120, description="Maximum walking time between consecutive stops")
    total_max_min: Optional[int] = Field(default=None, ge=1, le=360, description="Optional maximum total walking time")


class TraceSpotQuery(BaseModel):
    area: str = Field(..., description="Geographical search area or city name")
    entities: List[Entity] = Field(default_factory=list, description="List of target geospatial entities")
    relations: List[Relation] = Field(default_factory=list, description="Spatial relations between entities")
    itinerary: Optional[Itinerary] = Field(default=None, description="Sentence-to-itinerary sequence definition")

    @field_validator("area")
    @classmethod
    def clean_area(cls, v: str) -> str:
        cleaned = re.sub(r'["\']', '', str(v)).strip()
        if not cleaned:
            return "Berlin"
        return cleaned


def sanitize_tag(raw_tag: str, threshold: float = 75.0) -> Optional[str]:
    """
    Validates an OSM tag against the taginfo whitelist.
    If exact match, returns it immediately.
    If misspelled (e.g. amenity=place_worship or leisure=parrk),
    uses rapidfuzz to fuzzy-correct it to the closest whitelist tag.
    Returns None if similarity is below threshold.
    """
    raw_tag = raw_tag.strip().lower()
    if raw_tag in OSM_TAG_WHITELIST:
        return raw_tag

    # If format is key:value or key-value, normalize to key=value
    normalized = re.sub(r'[:\-]', '=', raw_tag, count=1)
    if normalized in OSM_TAG_WHITELIST:
        return normalized

    # Fuzzy match with rapidfuzz
    match, score, _ = process.extractOne(raw_tag, WHITELIST_KEYS, scorer=fuzz.WRatio)
    if score >= threshold:
        return match

    return None


def sanitize_and_validate_dict(data: dict) -> TraceSpotQuery:
    """
    Validates a raw dictionary against the schema, cleans and fuzzy-corrects
    hallucinated tags, fixes relation entity references, and returns a verified TraceSpotQuery.
    Handles standard spatial queries, time-based relations, and sentence-to-itinerary queries.
    """
    if not isinstance(data, dict):
        raise ValueError("Payload must be a dictionary")

    area = str(data.get("area", "")).strip() or "Berlin"

    # --- Case A: Itinerary Query ---
    raw_itinerary = data.get("itinerary")
    if isinstance(raw_itinerary, dict) and raw_itinerary.get("stops"):
        raw_stops = raw_itinerary.get("stops", [])
        cleaned_stops: List[Stop] = []
        for idx, s in enumerate(raw_stops, start=1):
            if not isinstance(s, dict):
                continue
            sid = int(s.get("id", idx))
            name = str(s.get("name", "stop")).strip() or f"stop {idx}"
            raw_tags = s.get("tags", [])
            if isinstance(raw_tags, str):
                raw_tags = [raw_tags]

            verified_tags = []
            for t in raw_tags:
                fixed = sanitize_tag(str(t))
                if fixed and fixed not in verified_tags:
                    verified_tags.append(fixed)

            if not verified_tags:
                name_match, score, _ = process.extractOne(
                    name,
                    [v["name"] for v in OSM_TAG_WHITELIST.values()],
                    scorer=fuzz.WRatio
                )
                if score >= 65:
                    for k, v in OSM_TAG_WHITELIST.items():
                        if v["name"] == name_match:
                            verified_tags.append(k)
                            break

            if not verified_tags:
                verified_tags.append("amenity=cafe")

            cleaned_stops.append(Stop(id=sid, name=name, tags=verified_tags))

        max_leg = int(raw_itinerary.get("max_leg_min", 10))
        total_max = raw_itinerary.get("total_max_min")
        if total_max is not None:
            total_max = int(total_max)

        itinerary_obj = Itinerary(
            stops=cleaned_stops,
            max_leg_min=max(1, min(120, max_leg)),
            total_max_min=total_max
        )

        # Mirror stops into entities for backward compatibility
        entities_mirror = [Entity(id=s.id, name=s.name, tags=s.tags) for s in cleaned_stops]

        return TraceSpotQuery(
            area=area,
            entities=entities_mirror,
            relations=[],
            itinerary=itinerary_obj
        )

    # --- Case B: Standard / Time-Based Spatial Query ---
    entities_raw = data.get("entities", [])
    if not isinstance(entities_raw, list) or len(entities_raw) == 0:
        raise ValueError("Entities list must contain at least one entity")

    cleaned_entities: List[Entity] = []
    valid_ids = set()

    for idx, e in enumerate(entities_raw, start=1):
        if not isinstance(e, dict):
            continue
        eid = int(e.get("id", idx))
        name = str(e.get("name", "place")).strip() or "place"
        raw_tags = e.get("tags", [])
        if isinstance(raw_tags, str):
            raw_tags = [raw_tags]

        verified_tags = []
        for t in raw_tags:
            fixed = sanitize_tag(str(t))
            if fixed and fixed not in verified_tags:
                verified_tags.append(fixed)

        # If all tags were rejected or none provided, try matching entity name against whitelist concepts
        if not verified_tags:
            name_match, score, _ = process.extractOne(
                name,
                [v["name"] for v in OSM_TAG_WHITELIST.values()],
                scorer=fuzz.WRatio
            )
            if score >= 65:
                for k, v in OSM_TAG_WHITELIST.items():
                    if v["name"] == name_match:
                        verified_tags.append(k)
                        break

        # Fallback if still empty
        if not verified_tags:
            verified_tags.append("amenity=place_of_worship" if "church" in name.lower() else "leisure=park")

        cleaned_entities.append(Entity(id=eid, name=name, tags=verified_tags))
        valid_ids.add(eid)

    relations_raw = data.get("relations", [])
    cleaned_relations: List[Relation] = []

    if isinstance(relations_raw, list):
        for r in relations_raw:
            if not isinstance(r, dict):
                continue
            rtype = str(r.get("type", "within")).strip()
            a = int(r.get("a", 1))
            b = int(r.get("b", 2))

            time_min = r.get("time_min")
            mode = r.get("mode")
            dist = r.get("distance_m")

            if time_min is not None:
                t_val = max(1, min(120, int(time_min)))
                m_val = str(mode or "walk").strip().lower()
                if a in valid_ids and b in valid_ids and a != b:
                    cleaned_relations.append(Relation(type=rtype, a=a, b=b, time_min=t_val, mode=m_val))
            else:
                dist_val = int(dist or 100)
                dist_val = max(5, min(5000, dist_val))
                if a in valid_ids and b in valid_ids and a != b:
                    cleaned_relations.append(Relation(type=rtype, a=a, b=b, distance_m=dist_val))

    return TraceSpotQuery(
        area=area,
        entities=cleaned_entities,
        relations=cleaned_relations,
        itinerary=None
    )
