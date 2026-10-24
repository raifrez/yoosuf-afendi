"""Export the GTFS feed (data/gtfs/) for map, dashboard and simulator builders.

Writes data/export/:
  network.json               every sailing with stop times; stops carry Census island_ids
  routes.geojson             route lines
  stops.geojson              island stop points
  stop_islands.csv           ferry stop -> Census island_id(s), with match method
  island_ferry_coverage.csv  every Census island: served / no route in data / atoll not in data
If a local web/ app exists, network.json is also copied to web/public/data/.

Usage: uv run python -m pipeline.export_web
"""

import json
from pathlib import Path

from pipeline.build_gtfs import OUT as GTFS, to_minutes, write_csv
from pipeline.map_islands import coverage, load_census_islands, map_stops
from pipeline.stops import ATOLLS, DATA, read_csv, split_stop_name, stop_id

EXPORT = DATA / "export"
WEB_PUBLIC = Path(__file__).resolve().parent.parent / "web" / "public"


def build_network(gtfs: Path = GTFS) -> dict:
    table = lambda name: read_csv(gtfs / f"{name}.txt")
    dv = {t["record_id"]: t["translation"] for t in table("translations")}
    stop_prov = {p["entity_id"]: p["note"] for p in table("provenance") if p["entity_type"] == "stop"}

    stops = []
    for s in table("stops"):
        code, island = split_stop_name(s["stop_name"])
        stops.append({"id": s["stop_id"], "name": island, "atoll": code, "dv": dv.get(s["stop_id"], ""),
                      "lat": float(s["stop_lat"]), "lon": float(s["stop_lon"]),
                      "approx": stop_prov.get(s["stop_id"], "").startswith("manual_approx"), "islandIds": []})
    stop_index = {s["id"]: i for i, s in enumerate(stops)}

    stop_times: dict[str, list] = {}
    for st in table("stop_times"):
        stop_times.setdefault(st["trip_id"], []).append(
            (int(st["stop_sequence"]), stop_index[st["stop_id"]], to_minutes(st["departure_time"])))

    routes = {r["route_id"]: {"id": r["route_id"],
                              "aliases": r["route_desc"].removeprefix("Also published as route "),
                              "trips": []} for r in table("routes")}
    for t in table("trips"):
        calls = [[stop, minute] for _, stop, minute in sorted(stop_times[t["trip_id"]])]
        routes[t["route_id"]]["trips"].append({"id": t["trip_id"], "calls": calls})

    feed = table("feed_info")[0]
    return {"atolls": {code: name for code, (name, _) in ATOLLS.items()},
            "stops": stops, "routes": list(routes.values()),
            "meta": {"feedVersion": feed["feed_version"], "assumptions": [
                p["note"] for p in table("provenance") if p["classification"] == "assumed"]}}


def hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def build_geojson(network: dict) -> tuple[dict, dict]:
    """(routes, stops) FeatureCollections. Route lines follow the stop order of the route's longest sailing."""
    stops, atolls = network["stops"], network["atolls"]
    departures: dict[int, int] = {}
    stop_routes: dict[int, set] = {}
    route_features = []
    for r in network["routes"]:
        trips = r["trips"]
        for t in trips:
            for stop, _ in t["calls"][:-1]:
                departures[stop] = departures.get(stop, 0) + 1
            for stop, _ in t["calls"]:
                stop_routes.setdefault(stop, set()).add(r["id"])
        line = max(trips, key=lambda t: len(t["calls"]))["calls"]
        route_atolls = list(dict.fromkeys(stops[s]["atoll"] for t in trips for s, _ in t["calls"]))
        route_features.append({"type": "Feature", "geometry": {
            "type": "LineString", "coordinates": [[stops[s]["lon"], stops[s]["lat"]] for s, _ in line]},
            "properties": {
                "route_id": r["id"], "also_published_as": r["aliases"], "mode": "ferry",
                "stops": [stops[s]["name"] for s, _ in line], "stop_ids": [stops[s]["id"] for s, _ in line],
                "atolls": [atolls[a] for a in route_atolls], "cross_atoll": len(route_atolls) > 1,
                "sailings_per_day": len(trips),
                "first_departure": hhmm(min(t["calls"][0][1] for t in trips)),
                "last_arrival": hhmm(max(t["calls"][-1][1] for t in trips))}})
    stop_features = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
                      "properties": {"stop_id": s["id"], "name": s["name"], "name_dv": s["dv"],
                                     "atoll": atolls[s["atoll"]], "approximate_position": s["approx"],
                                     "census_island_ids": s["islandIds"],
                                     "departures_per_day": departures.get(i, 0),
                                     "routes": sorted(stop_routes.get(i, ()), key=int)}}
                     for i, s in enumerate(stops)]
    return ({"type": "FeatureCollection", "features": route_features},
            {"type": "FeatureCollection", "features": stop_features})


def main() -> None:
    network = build_network()
    islands = load_census_islands()
    mapping = map_stops(islands)
    ids = {stop_id(m.stop_name): m.island_ids for m in mapping}
    for s in network["stops"]:
        s["islandIds"] = ids[s["id"]]

    routes_gj, stops_gj = build_geojson(network)
    files = {"network.json": json.dumps(network, ensure_ascii=False, separators=(",", ":")),
             "routes.geojson": json.dumps(routes_gj, ensure_ascii=False, indent=1),
             "stops.geojson": json.dumps(stops_gj, ensure_ascii=False, indent=1)}
    EXPORT.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (EXPORT / name).write_text(text + "\n", encoding="utf-8")

    write_csv(EXPORT / "stop_islands.csv",
              ["stop_id", "stop_name", "island_ids", "method", "name_similarity", "distance_km", "note"],
              [{"stop_id": stop_id(m.stop_name), "stop_name": m.stop_name, "island_ids": ";".join(m.island_ids),
                "method": m.method, "name_similarity": m.similarity, "distance_km": m.distance_km, "note": m.note}
               for m in mapping])
    cov = coverage(mapping, islands, network)
    write_csv(EXPORT / "island_ferry_coverage.csv", list(cov[0]), cov)
    print(f"Wrote {EXPORT}: {', '.join(files)}, stop_islands.csv, island_ferry_coverage.csv "
          f"({len(network['stops'])} stops, {len(network['routes'])} routes, {len(cov)} Census islands)")

    if WEB_PUBLIC.is_dir():
        (WEB_PUBLIC / "data").mkdir(exist_ok=True)
        (WEB_PUBLIC / "data" / "network.json").write_text(files["network.json"], encoding="utf-8")
        print(f"Copied network.json to {WEB_PUBLIC / 'data'}")


if __name__ == "__main__":
    main()
