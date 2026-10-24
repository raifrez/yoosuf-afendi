"""Compile data/ferry_schedules.csv into a GTFS feed at data/gtfs/ (+ data/gtfs.zip).

Source rows are one stop time each: `trip_id` is the published route number and
`schedule_idx` one sailing of it. Route numbers with identical sailings are
merged (the lowest number is kept, the others recorded as aliases).

Usage: uv run python -m pipeline.build_gtfs
"""

import csv
import math
import sys
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pipeline.stops import ATOLLS, DATA, SCHEDULES, load_stop_coords, read_csv, split_stop_name, stop_id

OUT = DATA / "gtfs"
AGENCY_ID = "RTL"
SERVICE_ID = "ASSUMED_DAILY"
FEED_START, FEED_END = "20260101", "20261231"
MAX_PLAUSIBLE_KMH = 50  # straight-line speed; ferries ~20 km/h, speedboats ~45 km/h
CENSUS_POINTS = "Census 2022 island reference points (Maldives Bureau of Statistics), data/processed/population/islands.parquet"


@dataclass(frozen=True)
class StopTime:
    stop_name: str
    stop_name_dv: str
    time: str  # HH:MM:SS


@dataclass
class Route:
    route_id: str
    sailings: list[tuple[StopTime, ...]]
    aliases: list[str]


def to_minutes(hms: str) -> int:
    h, m, s = (int(x) for x in hms.split(":"))
    return h * 60 + m + s // 60


def load_routes(path: Path = SCHEDULES) -> dict[str, list[tuple[StopTime, ...]]]:
    """route number -> sailings (ordered by schedule_idx), each an ordered stop tuple."""
    rows = defaultdict(list)
    for r in read_csv(path):
        rows[(r["trip_id"], int(r["schedule_idx"]))].append(
            (int(r["order"]), StopTime(r["stop_name"], r["stop_name_dv"], r["timing"])))
    routes = defaultdict(list)
    for (route, idx), stops in sorted(rows.items(), key=lambda kv: (int(kv[0][0]), kv[0][1])):
        orders = sorted(o for o, _ in stops)
        if orders != list(range(1, len(stops) + 1)):
            raise ValueError(f"Route {route} sailing {idx}: stop order {orders} is not 1..n")
        routes[route].append(tuple(st for _, st in sorted(stops, key=lambda x: x[0])))
    return dict(routes)


def merge_duplicates(routes: dict[str, list[tuple[StopTime, ...]]]) -> list[Route]:
    by_signature: dict[tuple, Route] = {}
    for route_id in sorted(routes, key=int):
        sig = tuple(routes[route_id])
        if sig in by_signature:
            by_signature[sig].aliases.append(route_id)
        else:
            by_signature[sig] = Route(route_id, routes[route_id], [])
    return list(by_signature.values())


def haversine_km(a: dict, b: dict) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (float(a["lat"]), float(a["lon"]),
                                                float(b["lat"]), float(b["lon"])))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def validate(routes: list[Route], coords: dict[str, dict]) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    for route in routes:
        for idx, sailing in enumerate(route.sailings):
            where = f"route {route.route_id} sailing {idx}"
            names = [st.stop_name for st in sailing]
            if len(sailing) < 2:
                errors.append(f"{where}: fewer than 2 stops")
            if len(set(names)) < len(names):
                errors.append(f"{where}: repeated stop {names}")
            for st in sailing:
                split_stop_name(st.stop_name)  # raises on unknown atoll code
                if to_minutes(st.time) >= 24 * 60:
                    errors.append(f"{where}: {st.stop_name} at {st.time} is overnight (unsupported)")
                if st.stop_name not in coords:
                    errors.append(f"{where}: no coordinates for {st.stop_name}")
            for a, b in zip(sailing, sailing[1:]):
                minutes = to_minutes(b.time) - to_minutes(a.time)
                if minutes <= 0:
                    errors.append(f"{where}: {a.stop_name} {a.time} -> {b.stop_name} {b.time} not increasing")
                elif a.stop_name in coords and b.stop_name in coords:
                    km = haversine_km(coords[a.stop_name], coords[b.stop_name])
                    if km / (minutes / 60) > MAX_PLAUSIBLE_KMH:
                        warnings.append(f"{where}: {a.stop_name} -> {b.stop_name} {km:.1f} km in "
                                        f"{minutes} min ({km / (minutes / 60):.0f} km/h)")
    for name, c in sorted(coords.items()):
        if c["status"] == "manual_approx":
            warnings.append(f"approximate coordinates for {name}: {c['note']}")
    return errors, sorted(set(warnings))


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_tables(routes: list[Route], coords: dict[str, dict], source_date: str) -> dict[str, tuple[list[str], list[dict]]]:
    stops = {st.stop_name: st.stop_name_dv for r in routes for s in r.sailings for st in s}
    t: dict[str, tuple[list[str], list[dict]]] = {}

    t["agency"] = (["agency_id", "agency_name", "agency_url", "agency_timezone", "agency_lang"], [{
        "agency_id": AGENCY_ID, "agency_name": "Raajje Transport Link (operator unverified)",
        "agency_url": "https://rtl.mv", "agency_timezone": "Indian/Maldives", "agency_lang": "en"}])

    t["stops"] = (["stop_id", "stop_name", "stop_lat", "stop_lon", "location_type", "stop_desc"], [{
        "stop_id": stop_id(name), "stop_name": name, "stop_lat": coords[name]["lat"],
        "stop_lon": coords[name]["lon"], "location_type": 0,
        "stop_desc": f"{split_stop_name(name)[1]}, {ATOLLS[split_stop_name(name)[0]][0]} Atoll"}
        for name in sorted(stops)])

    t["routes"] = (["route_id", "agency_id", "route_short_name", "route_long_name", "route_type", "route_desc"], [{
        "route_id": r.route_id, "agency_id": AGENCY_ID, "route_short_name": r.route_id,
        "route_long_name": f"{r.sailings[0][0].stop_name} – {r.sailings[0][-1].stop_name}",
        "route_type": 4,
        "route_desc": f"Also published as route {', '.join(r.aliases)}" if r.aliases else ""}
        for r in routes])

    t["trips"] = (["route_id", "service_id", "trip_id", "trip_headsign"], [{
        "route_id": r.route_id, "service_id": SERVICE_ID, "trip_id": f"{r.route_id}_{i}",
        "trip_headsign": s[-1].stop_name} for r in routes for i, s in enumerate(r.sailings)])

    # Source gives one time per stop, so arrival == departure.
    t["stop_times"] = (["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"], [{
        "trip_id": f"{r.route_id}_{i}", "arrival_time": st.time, "departure_time": st.time,
        "stop_id": stop_id(st.stop_name), "stop_sequence": seq}
        for r in routes for i, s in enumerate(r.sailings) for seq, st in enumerate(s, 1)])

    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    t["calendar"] = (["service_id", *days, "start_date", "end_date"], [{
        "service_id": SERVICE_ID, **{d: 1 for d in days}, "start_date": FEED_START, "end_date": FEED_END}])

    t["feed_info"] = (["feed_publisher_name", "feed_publisher_url", "feed_lang", "feed_start_date",
                       "feed_end_date", "feed_version"], [{
        "feed_publisher_name": "M.A.N.D.A.R.I.N datathon team (unofficial, contains assumptions)",
        "feed_publisher_url": "https://example.org/mandarin", "feed_lang": "en",
        "feed_start_date": FEED_START, "feed_end_date": FEED_END,
        "feed_version": f"source-{source_date}-built-{date.today().isoformat()}"}])

    t["translations"] = (["table_name", "field_name", "language", "translation", "record_id"], [{
        "table_name": "stops", "field_name": "stop_name", "language": "dv",
        "translation": dv, "record_id": stop_id(name)} for name, dv in sorted(stops.items())])

    # Non-standard extension file: where every entity came from.
    src = f"data/{SCHEDULES.name}"
    provenance = [
        {"entity_type": "dataset", "entity_id": SCHEDULES.name, "source": src, "observed_date": source_date,
         "classification": "observed", "note": "Publisher/retrieval method not recorded"},
        {"entity_type": "calendar", "entity_id": SERVICE_ID, "source": "", "observed_date": "",
         "classification": "assumed", "note": "Source has no operating days; every route assumed to run daily"},
        {"entity_type": "stop_times", "entity_id": "*", "source": src, "observed_date": source_date,
         "classification": "assumed", "note": "One time per stop in source; arrival_time set equal to departure_time"},
        {"entity_type": "agency", "entity_id": AGENCY_ID, "source": "", "observed_date": "",
         "classification": "assumed", "note": "Operator not stated in source"},
    ]
    provenance += [{"entity_type": "route", "entity_id": r.route_id, "source": src, "observed_date": source_date,
                    "classification": "observed",
                    "note": f"Merged identical routes {', '.join(r.aliases)}" if r.aliases else ""} for r in routes]
    provenance += [{"entity_type": "stop", "entity_id": stop_id(name),
                    "source": CENSUS_POINTS if coords[name]["status"] == "census_point" else "OpenStreetMap via Nominatim (ODbL)",
                    "observed_date": date.today().isoformat(),
                    "classification": "derived", "note": f"{coords[name]['status']}: {coords[name]['note']}"}
                   for name in sorted(stops)]
    t["provenance"] = (["entity_type", "entity_id", "source", "observed_date", "classification", "note"], provenance)
    return t


def main() -> int:
    routes = merge_duplicates(load_routes())
    coords = load_stop_coords()
    errors, warnings = validate(routes, coords)
    for w in warnings:
        print("WARN ", w)
    for e in errors:
        print("ERROR", e)
    if errors:
        print(f"\n{len(errors)} error(s); feed not written.")
        return 1

    source_date = date.fromtimestamp(SCHEDULES.stat().st_mtime).isoformat()
    tables = build_tables(routes, coords, source_date)
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.txt"):
        old.unlink()
    for name, (fields, rows) in tables.items():
        write_csv(OUT / f"{name}.txt", fields, rows)
    with zipfile.ZipFile(DATA / "gtfs.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(OUT.glob("*.txt")):
            z.write(f, f.name)

    counts = ", ".join(f"{len(rows)} {name}" for name, (_, rows) in tables.items()
                       if name in ("stops", "routes", "trips", "stop_times"))
    print(f"\nWrote {OUT} and gtfs.zip: {counts}; {len(warnings)} warning(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
