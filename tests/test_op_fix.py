import httpx
import time

ql = """[out:json][timeout:25];
(
  node["amenity"="pharmacy"](52.49,13.37,52.53,13.43);
  way["amenity"="pharmacy"](52.49,13.37,52.53,13.43);
)->.primary;
(
  node["leisure"="park"](52.49,13.37,52.53,13.43);
  way["leisure"="park"](52.49,13.37,52.53,13.43);
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

mirrors = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

for m in mirrors:
    try:
        t0 = time.time()
        r = httpx.post(m, data={"data": ql}, headers=headers, timeout=25)
        print(m, "-> HTTP", r.status_code, f"in {time.time()-t0:.2f}s")
        if r.status_code == 200:
            data = r.json()
            elems = data.get("elements", [])
            print("Elements count:", len(elems))
            if elems:
                print("First element:", elems[0].get("tags"))
            break
        else:
            print("Error text:", r.text[:200])
    except Exception as e:
        print(m, "exception:", e)
