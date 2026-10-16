import httpx
import time

mirrors = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

# Simple fast query for pharmacy near park in Berlin center
ql = """[out:json][timeout:20];
(
  node["amenity"="pharmacy"](52.50,13.38,52.53,13.42);
  way["amenity"="pharmacy"](52.50,13.38,52.53,13.42);
)->.primary;
(
  node["leisure"="park"](52.50,13.38,52.53,13.42);
  way["leisure"="park"](52.50,13.38,52.53,13.42);
)->.rel_2;
(
  node.primary(around.rel_2: 200);
  way.primary(around.rel_2: 200);
)->.matched_primary;
(
  .matched_primary;
  node.rel_2(around.matched_primary: 200);
  way.rel_2(around.matched_primary: 200);
);
out center 25;
"""

headers = {
    "User-Agent": "TraceSpot-Research/1.0 (academic NLP OSM project)",
    "Accept": "*/*"
}

for m in mirrors:
    print(f"Trying mirror: {m}...")
    try:
        t0 = time.time()
        r = httpx.post(m, data={"data": ql}, headers=headers, timeout=20)
        elapsed = time.time() - t0
        print(f"  -> HTTP {r.status_code} in {elapsed:.2f}s")
        if r.status_code == 200:
            data = r.json()
            elems = data.get("elements", [])
            print(f"  -> SUCCESS! Returned {len(elems)} elements.")
            if elems:
                print(f"  -> Sample: {elems[0].get('tags')}")
            break
        else:
            print(f"  -> Response text: {r.text[:150]}")
    except Exception as e:
        print(f"  -> Failed with {e}")
