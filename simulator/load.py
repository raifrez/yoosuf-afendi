"""Load the simulator's inputs from the repo's generated files. All file I/O lives here (and in the CLI).

  data/gtfs/{trips,stop_times,stops}.txt     timetable (observed sailings; operating days assumed daily)
  data/export/stop_islands.csv               ferry stop -> Census island_id(s) (derived)
  data/processed/population/islands.parquet  Census islands: name, atoll_code (+ population)
  data/processed/facilities/facilities.parquet  hospitals and their island_id (island links derived)
"""

from collections import defaultdict
from pathlib import Path

import duckdb

from pipeline.build_gtfs import OUT as GTFS, to_minutes
from pipeline.export_web import EXPORT
from pipeline.map_islands import load_census_islands
from pipeline.stops import DATA, read_csv
from simulator.timetable import StopTime, Timetable, Trip

STOP_ISLANDS = EXPORT / "stop_islands.csv"
FACILITIES = DATA / "processed" / "facilities" / "facilities.parquet"


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing; build it first (see CLAUDE.md 'How to')")
    return read_csv(path)


def load_timetable(gtfs: Path = GTFS) -> Timetable:
    """Every trip in the feed. The feed has one service, assumed to run daily; more than one
    service would need operating days, which are not modelled yet."""
    trips = _rows(gtfs / "trips.txt")
    services = {t["service_id"] for t in trips}
    if len(services) != 1:
        raise ValueError(f"Feed has services {sorted(services)}; operating days are not modelled yet")
    calls = defaultdict(list)
    for st in _rows(gtfs / "stop_times.txt"):
        calls[st["trip_id"]].append((int(st["stop_sequence"]), StopTime(
            st["stop_id"], to_minutes(st["arrival_time"]), to_minutes(st["departure_time"]))))
    return Timetable(tuple(Trip(t["trip_id"], t["route_id"], tuple(s for _, s in sorted(calls[t["trip_id"]])))
                           for t in trips))


def load_stop_names(gtfs: Path = GTFS) -> dict[str, str]:
    """stop_id -> stop_name, e.g. 'F_NILANDHOO' -> 'F.Nilandhoo'."""
    return {s["stop_id"]: s["stop_name"] for s in _rows(gtfs / "stops.txt")}


def load_island_stops(path: Path = STOP_ISLANDS) -> dict[str, frozenset[str]]:
    """Census island_id -> the ferry stop_ids serving it. A stop can serve several islands;
    stops on no Census island (airports, industrial islands) are left out."""
    islands = defaultdict(set)
    for row in _rows(path):
        for island_id in filter(None, row["island_ids"].split(";")):
            islands[island_id].add(row["stop_id"])
    return {island_id: frozenset(stops) for island_id, stops in islands.items()}


def load_islands() -> dict[str, dict]:
    """island_id -> {island_id, name, atoll_code, lat, lon, population} for every Census island."""
    return {i["island_id"]: i for i in load_census_islands()}


def load_hospitals(path: Path = FACILITIES) -> list[dict]:
    """Hospitals linked to a Census island: facility_id, name, island_id, location_match."""
    rel = duckdb.sql(f"""
        SELECT facility_id, name, island_id, location_match FROM '{path}'
        WHERE facility_type = 'hospital' AND island_id IS NOT NULL ORDER BY island_id, name""")
    return [dict(zip(rel.columns, row)) for row in rel.fetchall()]
