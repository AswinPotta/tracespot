"""
TraceSpot English Rule-Based Parser (rules.py)
Robust natural language parser for geospatial place search queries.
English only.
Supports:
1. Standard relational queries (distance_m)
2. Time-based reach queries ("time_min", "mode": "walk")
3. Sentence-to-itinerary queries ("itinerary" with ordered stops & max_leg_min)
Acts as a high-precision baseline and safety guardrail.
"""

import re
from typing import Dict, List, Optional, Tuple, Any
from ml.schema import TraceSpotQuery, Entity, Relation, Stop, Itinerary, sanitize_and_validate_dict

WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "fifteen": 15, "twenty": 20, "thirty": 30
}

# English Concept Dictionary mapping keywords to (concept_name, [OSM_tags])
CONCEPT_MAP: Dict[str, Tuple[str, List[str]]] = {
    # Places of worship
    "church": ("church", ["amenity=place_of_worship", "amenity=church"]),
    "churches": ("church", ["amenity=place_of_worship", "amenity=church"]),
    "cathedral": ("cathedral", ["amenity=place_of_worship"]),
    "chapel": ("chapel", ["amenity=place_of_worship"]),
    "mosque": ("mosque", ["amenity=place_of_worship"]),
    "synagogue": ("synagogue", ["amenity=place_of_worship"]),
    "temple": ("temple", ["amenity=place_of_worship"]),
    "place of worship": ("place of worship", ["amenity=place_of_worship"]),

    # Health
    "pharmacy": ("pharmacy", ["amenity=pharmacy"]),
    "pharmacies": ("pharmacy", ["amenity=pharmacy"]),
    "drugstore": ("pharmacy", ["amenity=pharmacy"]),
    "chemist": ("pharmacy", ["amenity=pharmacy"]),
    "hospital": ("hospital", ["amenity=hospital"]),
    "hospitals": ("hospital", ["amenity=hospital"]),
    "clinic": ("clinic", ["amenity=clinic"]),
    "doctor": ("doctor", ["amenity=doctors"]),
    "doctors": ("doctor", ["amenity=doctors"]),
    "dentist": ("dentist", ["amenity=dentist"]),

    # Green & Nature
    "park": ("park", ["leisure=park"]),
    "parks": ("park", ["leisure=park"]),
    "garden": ("garden", ["leisure=garden"]),
    "gardens": ("garden", ["leisure=garden"]),
    "river": ("river", ["waterway=river", "waterway=canal"]),
    "rivers": ("river", ["waterway=river", "waterway=canal"]),
    "canal": ("canal", ["waterway=canal"]),
    "lake": ("lake", ["natural=water"]),
    "water": ("water body", ["natural=water"]),
    "forest": ("forest", ["natural=wood"]),
    "wood": ("forest", ["natural=wood"]),
    "beach": ("beach", ["natural=beach"]),

    # Urban micro-features
    "bench": ("bench", ["amenity=bench"]),
    "benches": ("bench", ["amenity=bench"]),
    "park bench": ("bench", ["amenity=bench"]),
    "fountain": ("fountain", ["amenity=fountain"]),
    "fountains": ("fountain", ["amenity=fountain"]),
    "drinking water": ("drinking water", ["amenity=drinking_water"]),
    "shelter": ("shelter", ["amenity=shelter"]),
    "toilet": ("public toilet", ["amenity=toilets"]),
    "toilets": ("public toilet", ["amenity=toilets"]),
    "public toilet": ("public toilet", ["amenity=toilets"]),
    "clock": ("public clock", ["amenity=clock"]),

    # Food & Drink & Generic Itinerary Terms
    "cafe": ("cafe", ["amenity=cafe"]),
    "café": ("cafe", ["amenity=cafe"]),
    "cafes": ("cafe", ["amenity=cafe"]),
    "coffee shop": ("cafe", ["amenity=cafe"]),
    "coffee": ("cafe", ["amenity=cafe"]),
    "restaurant": ("restaurant", ["amenity=restaurant"]),
    "restaurants": ("restaurant", ["amenity=restaurant"]),
    "dinner": ("restaurant", ["amenity=restaurant"]),
    "lunch": ("restaurant", ["amenity=restaurant"]),
    "food": ("restaurant", ["amenity=restaurant"]),
    "bistro": ("restaurant", ["amenity=restaurant"]),
    "bar": ("bar", ["amenity=bar"]),
    "bars": ("bar", ["amenity=bar"]),
    "pub": ("pub", ["amenity=pub"]),
    "pubs": ("pub", ["amenity=pub"]),
    "drink": ("bar", ["amenity=bar", "amenity=pub"]),
    "drinks": ("bar", ["amenity=bar", "amenity=pub"]),
    "bakery": ("bakery", ["shop=bakery"]),
    "bakeries": ("bakery", ["shop=bakery"]),
    "ice cream": ("ice cream", ["amenity=ice_cream"]),

    # Transport
    "bus stop": ("bus stop", ["highway=bus_stop"]),
    "bus stops": ("bus stop", ["highway=bus_stop"]),
    "bus station": ("bus station", ["amenity=bus_station"]),
    "metro station": ("metro station", ["railway=subway_entrance", "railway=station"]),
    "metro stations": ("metro station", ["railway=subway_entrance", "railway=station"]),
    "subway station": ("metro station", ["railway=subway_entrance", "railway=station"]),
    "subway entrance": ("metro entrance", ["railway=subway_entrance"]),
    "subway": ("metro station", ["railway=subway_entrance"]),
    "metro": ("metro station", ["railway=subway_entrance"]),
    "train station": ("train station", ["railway=station"]),
    "train stations": ("train station", ["railway=station"]),
    "railway station": ("train station", ["railway=station"]),
    "station": ("train station", ["railway=station"]),
    "tram stop": ("tram stop", ["railway=tram_stop"]),
    "parking": ("parking", ["amenity=parking"]),
    "parking lot": ("parking", ["amenity=parking"]),
    "car park": ("parking", ["amenity=parking"]),
    "bicycle parking": ("bike rack", ["amenity=bicycle_parking"]),
    "bike parking": ("bike rack", ["amenity=bicycle_parking"]),
    "gas station": ("gas station", ["amenity=fuel"]),
    "fuel": ("gas station", ["amenity=fuel"]),

    # Education & Civic
    "school": ("school", ["amenity=school"]),
    "schools": ("school", ["amenity=school"]),
    "university": ("university", ["amenity=university"]),
    "college": ("college", ["amenity=college"]),
    "library": ("library", ["amenity=library"]),
    "police": ("police station", ["amenity=police"]),
    "police station": ("police station", ["amenity=police"]),
    "fire station": ("fire station", ["amenity=fire_station"]),
    "post office": ("post office", ["amenity=post_office"]),

    # Culture, Tourism & Itinerary generic
    "museum": ("museum", ["tourism=museum"]),
    "museums": ("museum", ["tourism=museum"]),
    "sightseeing": ("attraction", ["tourism=attraction"]),
    "attraction": ("attraction", ["tourism=attraction"]),
    "tourist attraction": ("attraction", ["tourism=attraction"]),
    "theatre": ("theatre", ["amenity=theatre"]),
    "theater": ("theatre", ["amenity=theatre"]),
    "cinema": ("cinema", ["amenity=cinema"]),
    "monument": ("monument", ["historic=monument"]),
    "memorial": ("memorial", ["historic=memorial"]),
    "castle": ("castle", ["historic=castle"]),
    "viewpoint": ("viewpoint", ["tourism=viewpoint"]),
    "hotel": ("hotel", ["tourism=hotel"]),
    "supermarket": ("supermarket", ["shop=supermarket"]),
    "supermarkets": ("supermarket", ["shop=supermarket"]),
    "grocery store": ("supermarket", ["shop=supermarket"]),
}

POPULAR_CITIES = [
    # Europe
    "berlin", "amsterdam", "paris", "london", "madrid", "barcelona",
    "rome", "vienna", "munich", "prague", "warsaw", "brussels",
    "dublin", "lisbon", "stockholm", "copenhagen", "oslo", "helsinki",
    "budapest", "athens", "milan", "lyon", "marseille", "seville",
    "valencia", "frankfurt", "hamburg", "cologne", "zurich", "geneva",
    "edinburgh", "glasgow", "rotterdam", "utrecht",
    # Americas & Oceania
    "new york", "tokyo", "chicago", "san francisco", "toronto", "boston",
    "sydney", "melbourne",
    # India & Indian Metros
    "india", "delhi", "new delhi", "mumbai", "bombay", "bangalore", "bengaluru",
    "hyderabad", "chennai", "kolkata", "pune", "jaipur", "ahmedabad", "surat",
    "lucknow", "kanpur", "nagpur", "indore", "thane", "bhopal", "patna",
    "vadodara", "ghaziabad", "ludhiana", "agra", "nashik", "faridabad",
    "varanasi", "srinagar", "chandigarh", "coimbatore", "mysore", "gurgaon",
    "noida", "kochi", "goa", "kerala",
    # Major Countries & International Hubs
    "germany", "france", "spain", "italy", "uk", "united kingdom", "england",
    "usa", "united states", "canada", "australia", "japan", "singapore", "dubai"
]


def extract_area(text: str) -> Tuple[str, str]:
    """
    Extracts the city or search area from a natural language query.
    Returns (cleaned_query_without_area, area_name).
    """
    cleaned = text.strip()
    text_lower = cleaned.lower()

    # 1. Search against known popular cities first
    for city in POPULAR_CITIES:
        match = re.search(rf'\b{re.escape(city)}\b', text_lower)
        if match:
            remainder = re.sub(rf'\b(?:in|at|near|around)\s+{re.escape(city)}\b', '', cleaned, flags=re.IGNORECASE)
            remainder = re.sub(rf'\b{re.escape(city)}\b', '', remainder, flags=re.IGNORECASE).strip()
            return remainder, city.title()

    # 2. Check for preposition followed by arbitrary city name at end of sentence
    end_match = re.search(r'\b(?:in|at)\s+([a-zA-Z0-9\s\.\-]{2,30})$', cleaned, flags=re.IGNORECASE)
    if end_match:
        cand = end_match.group(1).strip()
        cand_clean = cand.lower()
        stopwords = {"park", "church", "bench", "fountain", "bus stop", "station", "walk", "foot", "min"}
        if not any(sw in cand_clean for sw in stopwords):
            remainder = cleaned[:end_match.start()].strip()
            return remainder, cand.title()

    return cleaned, "Berlin"


def extract_time_walk_constraint(text: str) -> Optional[int]:
    """
    Extracts walking time constraint in minutes from expressions like:
    - 'within a 5 minute walk of'
    - 'within 10 minutes walk'
    - '10 min walk from'
    - 'walking distance of' (default 10 min)
    - '5 minutes away on foot'
    - '5 mins away on foot'
    - 'five minute walk'
    """
    lower = text.lower()

    # Generic walking distance default
    if re.search(r'\b(?:walking distance|walkable)\b', lower):
        # Look for explicit number nearby
        num_m = re.search(r'(\d+|five|ten|fifteen|twenty)\s*(?:min|minute|minutes|mins)?\s*(?:walking distance|walkable)', lower)
        if num_m:
            val = num_m.group(1)
            return WORD_NUMBERS.get(val, int(val) if val.isdigit() else 10)
        return 10

    # Pattern: 'within a 5 minute walk', '10 min walk', '5 minutes away on foot', '15 mins walk'
    pattern = r'(?:within\s+(?:a\s+)?)?(\d+|one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|thirty)\s*(?:min|mins|minute|minutes)\s*(?:walk|walk of|walk from|away on foot|on foot from|on foot)?'
    matches = re.finditer(pattern, lower)
    for m in matches:
        val_str = m.group(1)
        # Check that 'min' or 'minute' or 'walk' follows
        sub_span = lower[m.start():m.end()+15]
        if any(kw in sub_span for kw in ["min", "minute", "walk", "foot"]):
            if val_str.isdigit():
                return int(val_str)
            if val_str in WORD_NUMBERS:
                return WORD_NUMBERS[val_str]

    return None


def extract_distance_meters(text: str) -> Optional[int]:
    """Extracts explicit distance in meters (e.g. 'within 100 m', '100 meters')."""
    lower = text.lower()
    m = re.search(r'(?:within|less than)?\s*(\d+)\s*(?:m|meter|meters)\b', lower)
    if m:
        dist = int(m.group(1))
        return min(max(dist, 10), 5000)

    if any(k in lower for k in ["next to", "adjacent to", "beside"]):
        return 35

    if any(k in lower for k in ["near", "close to", "nearby", "around"]):
        return 150

    return None


def is_itinerary_query(text: str) -> bool:
    """
    Detects if the query specifies a multi-stop itinerary using sequence indicators:
    'then', 'after that', 'followed by', 'and finally', or comma sequences ('cafe, park, dinner').
    """
    lower = text.lower()
    if any(kw in lower for kw in ["then", "after that", "followed by", "and finally"]):
        return True

    # Comma separation with itinerary concepts (e.g. "cafe, park, dinner")
    if "," in lower:
        parts = [p.strip() for p in lower.split(",") if p.strip()]
        matched_concepts = 0
        for part in parts:
            for kw in CONCEPT_MAP.keys():
                if re.search(rf'\b{re.escape(kw)}\b', part):
                    matched_concepts += 1
                    break
        if matched_concepts >= 3:
            return True

    return False


def parse_itinerary_query(cleaned_text: str, area: str) -> TraceSpotQuery:
    """
    Parses a sequence query into an Itinerary with ordered stops and max_leg_min.
    e.g. "cafe, then a park, then dinner, all within a 10 minute walk"
    """
    lower = cleaned_text.lower()

    # Extract max_leg_min
    time_limit = extract_time_walk_constraint(lower) or 10

    # Split sequence by transitions: "then", "after that", "followed by", "and finally", ","
    # Normalize separators into delimiter "|"
    norm = re.sub(r'\b(?:then|after that|followed by|and finally)\b', '|', lower)
    norm = norm.replace(',', '|')

    # Split segments
    segments = [s.strip() for s in norm.split('|') if s.strip()]

    stops: List[Stop] = []
    stop_id = 1
    sorted_keywords = sorted(CONCEPT_MAP.keys(), key=lambda x: len(x), reverse=True)

    for seg in segments:
        # Avoid segments that are purely constraints (e.g. "all within a 10 minute walk in paris")
        if re.search(r'^\s*(?:all|each)?\s*within\s+(?:a\s+)?\d+\s*min', seg):
            continue
        if re.search(r'^\s*(?:within\s+)?\d+\s*min(?:utes?)?\s*walk', seg):
            continue

        matched_name = None
        matched_tags = None
        for kw in sorted_keywords:
            if re.search(rf'\b{re.escape(kw)}\b', seg):
                name, tags = CONCEPT_MAP[kw]
                matched_name = kw
                matched_tags = tags
                break

        if matched_name and matched_tags:
            stops.append(Stop(id=stop_id, name=matched_name, tags=matched_tags))
            stop_id += 1

    # If < 2 stops found, fallback to scanning entire text sequentially
    if len(stops) < 2:
        stops = []
        stop_id = 1
        found_matches = []
        for kw in sorted_keywords:
            for m in re.finditer(rf'\b{re.escape(kw)}\b', lower):
                found_matches.append((m.start(), kw))
        found_matches.sort(key=lambda x: x[0])

        seen_spans = []
        for start_pos, kw in found_matches:
            if any(s <= start_pos < s + len(w) for s, w in seen_spans):
                continue
            seen_spans.append((start_pos, kw))
            name, tags = CONCEPT_MAP[kw]
            stops.append(Stop(id=stop_id, name=kw, tags=tags))
            stop_id += 1

    if len(stops) < 2:
        # Default safety fallback
        stops = [
            Stop(id=1, name="cafe", tags=["amenity=cafe"]),
            Stop(id=2, name="park", tags=["leisure=park"])
        ]

    itinerary = Itinerary(
        stops=stops,
        max_leg_min=time_limit
    )

    data = {
        "area": area,
        "itinerary": itinerary.model_dump()
    }
    return sanitize_and_validate_dict(data)


def parse_query_rule_based(query_text: str) -> TraceSpotQuery:
    """
    Master rule-based parser.
    Converts English natural language query into structured TraceSpotQuery:
    - Itinerary queries
    - Time-based walking reach queries
    - Distance-based proximity queries
    """
    raw = query_text.strip()
    text_without_area, area = extract_area(raw)

    # Check for Feature 2: Itinerary
    if is_itinerary_query(text_without_area):
        return parse_itinerary_query(text_without_area, area)

    # Check for Feature 1: Time-based walking constraint
    time_min = extract_time_walk_constraint(text_without_area)
    dist_m = extract_distance_meters(text_without_area)

    sorted_keywords = sorted(CONCEPT_MAP.keys(), key=lambda x: len(x), reverse=True)
    text_lower = text_without_area.lower()

    found_concepts: List[Tuple[int, str, str, List[str]]] = []
    matched_spans = []

    for kw in sorted_keywords:
        pattern = rf'\b{re.escape(kw)}\b'
        for match in re.finditer(pattern, text_lower):
            start, end = match.span()
            if any(s <= start < e or s < end <= e for s, e in matched_spans):
                continue
            matched_spans.append((start, end))
            name, tags = CONCEPT_MAP[kw]
            found_concepts.append((start, kw, name, tags))

    found_concepts.sort(key=lambda x: x[0])

    if not found_concepts:
        entities = [Entity(id=1, name="place", tags=["amenity=place_of_worship"])]
        return TraceSpotQuery(area=area, entities=entities, relations=[])

    entities = [
        Entity(id=idx, name=name, tags=tags)
        for idx, (_, _, name, tags) in enumerate(found_concepts, start=1)
    ]

    relations: List[Relation] = []
    if len(entities) >= 2:
        for other in entities[1:]:
            if time_min is not None:
                relations.append(Relation(
                    type="within",
                    a=entities[0].id,
                    b=other.id,
                    time_min=time_min,
                    mode="walk"
                ))
            else:
                relations.append(Relation(
                    type="within",
                    a=entities[0].id,
                    b=other.id,
                    distance_m=dist_m or 100
                ))

    data = {
        "area": area,
        "entities": [e.model_dump() for e in entities],
        "relations": [r.model_dump() for r in relations]
    }
    return sanitize_and_validate_dict(data)
