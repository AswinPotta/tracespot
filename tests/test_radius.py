import httpx
import time

ql = """[out:json][timeout:15];
(
  node(around:2000, 52.5200, 13.4050)["amenity"="pharmacy"];
  way(around:2000, 52.5200, 13.4050)["amenity"="pharmacy"];
)->.primary;
(
  node(around:2000, 52.5200, 13.4050)["leisure"="park"];
  way(around:2000, 52.5200, 13.4050)["leisure"="park"];
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
    t0 = time.time()
    try:
        r = httpx.post(m, data={"data": ql}, headers=headers, timeout=15)
        print(f"[{r.status_code}] {m} in {time.time()-t0:.2f}s")
        if r.status_code == 200:
            elems = r.json().get("elements", [])
            print(f"Success! {len(elems)} elements.")
            if elems:
                print("Element tags:", elems[0].get("tags"))
            break
        else:
            print("Response:", r.text[:150])
    except Exception as e:
        print(f"Error {m}: {e}")
