"""Look up island coordinates for every ferry stop via OpenStreetMap Nominatim.

Results are cached in data/stops_geo.csv; only stops missing from the cache
are queried. Matches are accepted only when OSM places the island in the
expected atoll; everything else is written with status 'unresolved' for
manual review.

Usage: uv run python -m pipeline.geocode_stops
"""

import csv
import json
import time
import urllib.parse
import urllib.request

from pipeline.stops import ATOLLS, GEO_AUTO as CACHE, GEO_MANUAL, SCHEDULES, read_csv, split_stop_name

FIELDS = ["stop_name", "stop_name_dv", "lat", "lon", "osm_type", "osm_id",
          "osm_display_name", "status"]
NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "mandarin-datathon/0.1 (ferry accessibility prototype)"
# Island polygons give a better centroid than the town node.
PLACE_RANK = {"island": 0, "islet": 1, "town": 2, "village": 3, "city": 4}


def nominatim(query: str) -> list[dict]:
    url = NOMINATIM + "?" + urllib.parse.urlencode(
        {"q": query, "countrycodes": "mv", "format": "jsonv2", "limit": 10})
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def best_match(results: list[dict], island_dv: str, atoll_dv: str) -> dict | None:
    # Exact Dhivehi name only: Nominatim fuzzy-matches near spellings
    # (e.g. ކަލައިދޫ -> ކަޅައިދޫ), which are different islands.
    candidates = [r for r in results
                  if r["name"] == island_dv and atoll_dv in r["display_name"]
                  and r["addresstype"] in PLACE_RANK]
    return min(candidates, key=lambda r: PLACE_RANK[r["addresstype"]], default=None)


def geocode(stop_name: str, stop_name_dv: str) -> dict:
    code, _ = split_stop_name(stop_name)
    atoll_dv = ATOLLS[code][1]
    island_dv = stop_name_dv.partition(".")[2]
    match = None
    for query in (f"{island_dv}, {atoll_dv}", island_dv):
        match = best_match(nominatim(query), island_dv, atoll_dv)
        time.sleep(1.1)  # Nominatim usage policy: max 1 request/second
        if match:
            break
    row = {"stop_name": stop_name, "stop_name_dv": stop_name_dv, "status": "unresolved"}
    if match:
        row.update(lat=match["lat"], lon=match["lon"], osm_type=match["osm_type"],
                   osm_id=match["osm_id"], osm_display_name=match["display_name"],
                   status=f"osm_{match['addresstype']}")
    return row


def main() -> None:
    cached = {r["stop_name"]: r for r in read_csv(CACHE) if r["status"] != "unresolved"}
    manual = {r["stop_name"] for r in read_csv(GEO_MANUAL)}
    stops = {r["stop_name"]: r["stop_name_dv"] for r in read_csv(SCHEDULES)}

    rows = []
    for name, name_dv in sorted(stops.items()):
        if name in manual:
            continue
        row = cached.get(name) or geocode(name, name_dv)
        print(f"{row['status']:>14}  {name}")
        rows.append(row)

    with CACHE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    unresolved = [r["stop_name"] for r in rows if r["status"] == "unresolved"]
    print(f"\n{len(rows) - len(unresolved)}/{len(rows)} resolved -> {CACHE}")
    if unresolved:
        print(f"Unresolved (add to {GEO_MANUAL.name}):", ", ".join(unresolved))


if __name__ == "__main__":
    main()
