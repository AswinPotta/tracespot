import httpx
import time

endpoints = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter"
]

test_query = """[out:json][timeout:10];
node["amenity"="pharmacy"](52.51,13.39,52.52,13.41);
out 5;"""

headers = {
    "User-Agent": "TraceSpot-Research/1.0 (academic NLP OSM project)",
    "Accept": "*/*"
}

for ep in endpoints:
    t0 = time.time()
    try:
        r = httpx.post(ep, data={"data": test_query}, headers=headers, timeout=10.0)
        elapsed = time.time() - t0
        print(f"[{r.status_code}] {ep} in {elapsed:.2f}s")
        if r.status_code == 200:
            count = len(r.json().get("elements", []))
            print(f"       -> Success! {count} elements returned.")
    except Exception as e:
        print(f"[ERR] {ep} in {time.time()-t0:.2f}s -> {type(e).__name__}: {e}")
