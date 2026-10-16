"""
TraceSpot Dataset Generator (data_gen.py)
Generates 5,000 (natural language sentence -> JSON) training pairs:
- English only (removed Spanish, German, French)
- Standard spatial queries (~70%)
- Time-based walking queries (~15%)
- Sentence-to-itinerary queries (~15%)
- Rich sentence templates with noise ("5 mins", "five minute", "walkable", etc.)
- Saves to data/train.jsonl and data/test.jsonl
"""

import os
import sys
import json
import random
import re
from typing import List, Dict, Any, Tuple

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ml.schema import OSM_TAG_WHITELIST, TraceSpotQuery, Entity, Relation, Stop, Itinerary

REAL_CITIES = [
    "Berlin", "Amsterdam", "Paris", "London", "Madrid", "Barcelona",
    "Rome", "Vienna", "Munich", "Prague", "Warsaw", "Brussels",
    "Dublin", "Lisbon", "Stockholm", "Copenhagen", "Zurich", "Geneva",
    "New York", "Chicago", "San Francisco", "Sydney", "Toronto",
    "Chennai", "Hyderabad", "Delhi", "Bangalore", "Mumbai", "Pune", "Kolkata"
]

CONCEPTS = {
    "church": {"tags": ["amenity=place_of_worship"], "words": ["church", "cathedral", "chapel", "place of worship"]},
    "pharmacy": {"tags": ["amenity=pharmacy"], "words": ["pharmacy", "drugstore", "chemist", "apothecary"]},
    "park": {"tags": ["leisure=park"], "words": ["park", "public park", "city park", "green space"]},
    "river": {"tags": ["waterway=river"], "words": ["river", "waterway", "canal", "stream"]},
    "bench": {"tags": ["amenity=bench"], "words": ["bench", "park bench", "seat"]},
    "fountain": {"tags": ["amenity=fountain"], "words": ["fountain", "water fountain", "ornamental fountain"]},
    "bus stop": {"tags": ["highway=bus_stop"], "words": ["bus stop", "transit stop", "bus station"]},
    "metro station": {"tags": ["railway=subway_entrance"], "words": ["metro station", "subway station", "subway entrance", "metro"]},
    "train station": {"tags": ["railway=station"], "words": ["train station", "railway station", "central station", "railroad station"]},
    "hospital": {"tags": ["amenity=hospital"], "words": ["hospital", "medical center", "clinic"]},
    "cafe": {"tags": ["amenity=cafe"], "words": ["cafe", "coffee shop", "coffee", "cafeteria"]},
    "restaurant": {"tags": ["amenity=restaurant"], "words": ["restaurant", "dinner", "lunch", "bistro", "eatery"]},
    "bar": {"tags": ["amenity=bar"], "words": ["bar", "pub", "drink", "drinks"]},
    "museum": {"tags": ["tourism=museum"], "words": ["museum", "art museum", "history museum"]},
    "bakery": {"tags": ["shop=bakery"], "words": ["bakery", "bakeshop", "pastry shop"]},
    "supermarket": {"tags": ["shop=supermarket"], "words": ["supermarket", "grocery store", "food market"]},
    "school": {"tags": ["amenity=school"], "words": ["school", "primary school", "high school"]},
    "library": {"tags": ["amenity=library"], "words": ["library", "public library"]},
    "hotel": {"tags": ["tourism=hotel"], "words": ["hotel", "inn", "boutique hotel"]},
    "attraction": {"tags": ["tourism=attraction"], "words": ["sightseeing", "tourist attraction", "landmark", "monument"]},
    "bicycle parking": {"tags": ["amenity=bicycle_parking"], "words": ["bicycle parking", "bike rack", "bike parking"]}
}

REALISTIC_PAIRS = [
    ("pharmacy", "park"),
    ("pharmacy", "metro station"),
    ("pharmacy", "train station"),
    ("supermarket", "train station"),
    ("supermarket", "metro station"),
    ("church", "river"),
    ("bench", "fountain"),
    ("bench", "park"),
    ("cafe", "fountain"),
    ("cafe", "metro station"),
    ("cafe", "park"),
    ("restaurant", "hotel"),
    ("bakery", "school"),
    ("library", "museum"),
    ("bicycle parking", "train station"),
    ("bicycle parking", "metro station"),
    ("bar", "restaurant"),
    ("museum", "park"),
]

TEMPLATES_STANDARD_PAIR = [
    ("{e1} near a {e2} in {city}", "within", 150),
    ("{e1} next to a {e2} in {city}", "within", 35),
    ("{e1} within {dist} m of a {e2} in {city}", "within", None),
    ("{e1} close to a {e2} in {city}", "within", 150),
    ("{e1} beside a {e2} in {city}", "within", 35),
    ("find a {e1} next to a {e2} in {city}", "within", 35),
    ("show me {e1} near {e2} in {city}", "within", 150),
]

TEMPLATES_STANDARD_SINGLE = [
    ("{e1} in {city}", None),
    ("find {e1} in {city}", None),
    ("show me {e1} in {city}", None),
    ("{e1} located in {city}", None),
]

TEMPLATES_TIME_BASED = [
    ("{e1} within a {time} minute walk of a {e2} in {city}", "within", "walk"),
    ("{e1} within {time} minutes walk of a {e2} in {city}", "within", "walk"),
    ("{e1} within {time} min walk of a {e2} in {city}", "within", "walk"),
    ("{e1} {time} min walk from a {e2} in {city}", "within", "walk"),
    ("{e1} {time} minute walk from a {e2} in {city}", "within", "walk"),
    ("{e1} within walking distance of a {e2} in {city}", "within", "walk"),  # default 10 min
    ("{e1} {time} minutes away on foot from a {e2} in {city}", "within", "walk"),
    ("{e1} {time} mins away on foot from a {e2} in {city}", "within", "walk"),
    ("{e1} walkable from a {e2} in {city}", "within", "walk"),  # default 10 min
    ("find {e1} within a {time} minute walk of a {e2} in {city}", "within", "walk"),
]

TEMPLATES_ITINERARY = [
    ("{s1}, then a {s2}, then {s3}, all within a {time} minute walk in {city}", 3),
    ("{s1} then a {s2} then a {s3} within {time} minutes walk in {city}", 3),
    ("{s1}, followed by a {s2}, and finally {s3} in {city}", 3),
    ("{s1}, after that a {s2}, then {s3} in {city}", 3),
    ("{s1}, then a {s2}, each within a {time} minute walk in {city}", 2),
    ("{s1} followed by {s2} within {time} min walk in {city}", 2),
    ("visit a {s1}, then a {s2}, then {s3} in {city}", 3),
]


def add_light_noise(text: str) -> str:
    """Injects slight typographical noise, casing variations, or slang contractions."""
    prob = random.random()
    if prob < 0.15:
        return text.lower()
    elif prob < 0.25:
        # replace 'minutes' with 'mins' or '5' with 'five'
        text = text.replace("5 minutes", "5 mins").replace("10 minutes", "10 mins")
        text = text.replace("5 minute", "five minute").replace("10 minute", "ten minute")
        return text
    elif prob < 0.35 and len(text) > 12:
        idx = random.randint(2, len(text) - 4)
        return text[:idx] + text[idx+1] + text[idx] + text[idx+2:]
    return text


def generate_single_example() -> Tuple[str, Dict[str, Any]]:
    category = random.choices(["standard_pair", "standard_single", "time_based", "itinerary"], weights=[0.45, 0.25, 0.15, 0.15])[0]
    city = random.choice(REAL_CITIES)

    if category == "time_based":
        pair = random.choice(REALISTIC_PAIRS)
        c1_key, c2_key = pair
        c1 = CONCEPTS[c1_key]
        c2 = CONCEPTS[c2_key]
        w1 = random.choice(c1["words"])
        w2 = random.choice(c2["words"])

        tmpl, rtype, mode = random.choice(TEMPLATES_TIME_BASED)
        time_val = random.choice([3, 5, 7, 10, 15, 20])
        # If template is 'walking distance' without {time}, time defaults to 10
        if "{time}" in tmpl:
            sentence = tmpl.format(e1=w1, e2=w2, time=time_val, city=city)
            actual_time = time_val
        else:
            sentence = tmpl.format(e1=w1, e2=w2, city=city)
            actual_time = 10

        sentence = add_light_noise(sentence)
        entities = [
            {"id": 1, "name": c1_key, "tags": c1["tags"]},
            {"id": 2, "name": c2_key, "tags": c2["tags"]}
        ]
        relations = [
            {"type": "within", "a": 1, "b": 2, "time_min": actual_time, "mode": "walk"}
        ]
        return sentence, {"area": city, "entities": entities, "relations": relations}

    elif category == "itinerary":
        tmpl, stop_count = random.choice(TEMPLATES_ITINERARY)
        time_val = random.choice([5, 10, 15, 20])
        
        # Pick 2 or 3 distinct concepts
        chosen_keys = random.sample(["cafe", "park", "restaurant", "bar", "bakery", "museum", "attraction"], stop_count)
        words = [random.choice(CONCEPTS[k]["words"]) for k in chosen_keys]

        if stop_count == 3:
            if "{time}" in tmpl:
                sentence = tmpl.format(s1=words[0], s2=words[1], s3=words[2], time=time_val, city=city)
                actual_time = time_val
            else:
                sentence = tmpl.format(s1=words[0], s2=words[1], s3=words[2], city=city)
                actual_time = 10
        else:
            if "{time}" in tmpl:
                sentence = tmpl.format(s1=words[0], s2=words[1], time=time_val, city=city)
                actual_time = time_val
            else:
                sentence = tmpl.format(s1=words[0], s2=words[1], city=city)
                actual_time = 10

        sentence = add_light_noise(sentence)
        stops = [
            {"id": i + 1, "name": k, "tags": CONCEPTS[k]["tags"]}
            for i, k in enumerate(chosen_keys)
        ]
        itinerary = {
            "stops": stops,
            "max_leg_min": actual_time
        }
        entities = [{"id": s["id"], "name": s["name"], "tags": s["tags"]} for s in stops]
        return sentence, {"area": city, "entities": entities, "relations": [], "itinerary": itinerary}

    elif category == "standard_pair":
        pair = random.choice(REALISTIC_PAIRS)
        c1_key, c2_key = pair
        c1 = CONCEPTS[c1_key]
        c2 = CONCEPTS[c2_key]
        w1 = random.choice(c1["words"])
        w2 = random.choice(c2["words"])

        tmpl, rtype, default_dist = random.choice(TEMPLATES_STANDARD_PAIR)
        dist_val = random.choice([25, 50, 75, 100, 150, 200, 250, 300, 500])
        if "{dist}" in tmpl:
            sentence = tmpl.format(e1=w1, e2=w2, dist=dist_val, city=city)
            actual_dist = dist_val
        else:
            sentence = tmpl.format(e1=w1, e2=w2, city=city)
            actual_dist = default_dist or 100

        sentence = add_light_noise(sentence)
        entities = [
            {"id": 1, "name": c1_key, "tags": c1["tags"]},
            {"id": 2, "name": c2_key, "tags": c2["tags"]}
        ]
        relations = [
            {"type": "within", "a": 1, "b": 2, "distance_m": actual_dist}
        ]
        return sentence, {"area": city, "entities": entities, "relations": relations}

    else:
        # Standard single
        c1_key = random.choice(list(CONCEPTS.keys()))
        c1 = CONCEPTS[c1_key]
        w1 = random.choice(c1["words"])
        tmpl, _ = random.choice(TEMPLATES_STANDARD_SINGLE)
        sentence = tmpl.format(e1=w1, city=city)
        sentence = add_light_noise(sentence)
        entities = [{"id": 1, "name": c1_key, "tags": c1["tags"]}]
        return sentence, {"area": city, "entities": entities, "relations": []}


def build_dataset(total_count: int = 5000, seed: int = 42) -> Tuple[List[Dict], List[Dict]]:
    random.seed(seed)
    dataset = []

    # Include explicit benchmark anchor queries
    anchors = [
        ("pharmacy within a 5 minute walk of a metro station in Berlin", {
            "area": "Berlin",
            "entities": [{"id": 1, "name": "pharmacy", "tags": ["amenity=pharmacy"]}, {"id": 2, "name": "metro station", "tags": ["railway=subway_entrance"]}],
            "relations": [{"type": "within", "a": 1, "b": 2, "time_min": 5, "mode": "walk"}]
        }),
        ("supermarket within 10 minutes walk of a train station in Chennai", {
            "area": "Chennai",
            "entities": [{"id": 1, "name": "supermarket", "tags": ["shop=supermarket"]}, {"id": 2, "name": "train station", "tags": ["railway=station"]}],
            "relations": [{"type": "within", "a": 1, "b": 2, "time_min": 10, "mode": "walk"}]
        }),
        ("cafe, then a park, then a restaurant, each within a 10 minute walk in Paris", {
            "area": "Paris",
            "entities": [{"id": 1, "name": "cafe", "tags": ["amenity=cafe"]}, {"id": 2, "name": "park", "tags": ["leisure=park"]}, {"id": 3, "name": "restaurant", "tags": ["amenity=restaurant"]}],
            "relations": [],
            "itinerary": {
                "stops": [{"id": 1, "name": "cafe", "tags": ["amenity=cafe"]}, {"id": 2, "name": "park", "tags": ["leisure=park"]}, {"id": 3, "name": "restaurant", "tags": ["amenity=restaurant"]}],
                "max_leg_min": 10
            }
        }),
        ("bakery then a museum then a bar within 15 minutes walk in Hyderabad", {
            "area": "Hyderabad",
            "entities": [{"id": 1, "name": "bakery", "tags": ["shop=bakery"]}, {"id": 2, "name": "museum", "tags": ["tourism=museum"]}, {"id": 3, "name": "bar", "tags": ["amenity=bar"]}],
            "relations": [],
            "itinerary": {
                "stops": [{"id": 1, "name": "bakery", "tags": ["shop=bakery"]}, {"id": 2, "name": "museum", "tags": ["tourism=museum"]}, {"id": 3, "name": "bar", "tags": ["amenity=bar"]}],
                "max_leg_min": 15
            }
        }),
        ("church within 100 m of a river in Amsterdam", {
            "area": "Amsterdam",
            "entities": [{"id": 1, "name": "church", "tags": ["amenity=place_of_worship"]}, {"id": 2, "name": "river", "tags": ["waterway=river"]}],
            "relations": [{"type": "within", "a": 1, "b": 2, "distance_m": 100}]
        }),
        ("bench next to a fountain and a bus stop in Paris", {
            "area": "Paris",
            "entities": [{"id": 1, "name": "bench", "tags": ["amenity=bench"]}, {"id": 2, "name": "fountain", "tags": ["amenity=fountain"]}, {"id": 3, "name": "bus stop", "tags": ["highway=bus_stop"]}],
            "relations": [{"type": "within", "a": 1, "b": 2, "distance_m": 35}, {"type": "within", "a": 1, "b": 3, "distance_m": 35}]
        }),
        ("hospital in London", {
            "area": "London",
            "entities": [{"id": 1, "name": "hospital", "tags": ["amenity=hospital"]}],
            "relations": []
        })
    ]

    for s, tj in anchors:
        dataset.append({
            "input_text": s,
            "target_json": tj,
            "target_text": json.dumps(tj, separators=(',', ':'))
        })

    while len(dataset) < total_count:
        sentence, target_json = generate_single_example()
        dataset.append({
            "input_text": sentence,
            "target_json": target_json,
            "target_text": json.dumps(target_json, separators=(',', ':'))
        })

    random.shuffle(dataset)
    split_idx = int(total_count * 0.90)
    train_data = dataset[:split_idx]
    test_data = dataset[split_idx:]
    return train_data, test_data


def save_dataset(train_data: List[Dict], test_data: List[Dict], output_dir: str = "data"):
    os.makedirs(output_dir, exist_ok=True)
    train_path = os.path.join(output_dir, "train.jsonl")
    test_path = os.path.join(output_dir, "test.jsonl")
    full_path = os.path.join(output_dir, "dataset.json")

    with open(train_path, "w", encoding="utf-8") as f:
        for item in train_data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    with open(test_path, "w", encoding="utf-8") as f:
        for item in test_data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    with open(full_path, "w", encoding="utf-8") as f:
        json.dump({"train": len(train_data), "test": len(test_data), "samples": train_data[:10]}, f, indent=2, ensure_ascii=False)

    print(f"[OK] Saved {len(train_data)} train examples -> {train_path}")
    print(f"[OK] Saved {len(test_data)} test examples -> {test_path}")


if __name__ == "__main__":
    train, test = build_dataset(total_count=5000)
    save_dataset(train, test)
