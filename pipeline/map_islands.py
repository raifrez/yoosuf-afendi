"""Link ferry stops to Census islands (the population's `island_id`).

A stop matches a Census island automatically when they are in the same atoll,
their names are similar (spelling variants such as Bandidhoo/Badidhoo) and
their reference points are close. Everything else must be decided in
data/stop_islands_manual.csv; an unresolved stop is an error.

Usage: uv run python -m pipeline.map_islands   (prints the mapping for review)
"""

import difflib
import re
from dataclasses import dataclass
from pathlib import Path

import duckdb

from pipeline.build_gtfs import haversine_km
from pipeline.stops import DATA, SCHEDULES, load_stop_coords, read_csv, split_stop_name, stop_id

POPULATION = DATA / "processed" / "population"
MANUAL = DATA / "stop_islands_manual.csv"
MIN_NAME_SIMILARITY = 0.8
MAX_DISTANCE_KM = 2.0


@dataclass
class StopIslands:
    stop_name: str
    island_ids: list[str]  # empty = not a Census inhabited island
    method: str  # exact | spelling_variant | manual
    similarity: float | None
    distance_km: float | None
    note: str


def load_census_islands(population: Path = POPULATION) -> list[dict]:
    """Census islands with their resident population (sum of group weights)."""
    sql = f"""
        SELECT i.island_id, i.name, i.atoll_code, i.latitude AS lat, i.longitude AS lon,
               coalesce(sum(g.population_weight), 0)::BIGINT AS population
        FROM '{population / "islands.parquet"}' i
        LEFT JOIN '{population / "population_groups.parquet"}' g ON g.home_island_id = i.island_id
        GROUP BY ALL ORDER BY i.atoll_code, i.name"""
    rel = duckdb.sql(sql)
    return [dict(zip(rel.columns, row)) for row in rel.fetchall()]


def normalise(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower())


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalise(a), normalise(b)).ratio()


def auto_match(stop_name: str, coords: dict, islands: list[dict]) -> StopIslands | None:
    code, island = split_stop_name(stop_name)
    candidates = [i for i in islands if i["atoll_code"].lower() == code.lower()]
    if not candidates:
        return None
    best = max(candidates, key=lambda i: similarity(island, i["name"]))
    sim = similarity(island, best["name"])
    km = haversine_km(coords, best)
    if sim >= MIN_NAME_SIMILARITY and km <= MAX_DISTANCE_KM:
        method = "exact" if sim == 1 else "spelling_variant"
        return StopIslands(stop_name, [best["island_id"]], method, round(sim, 2), round(km, 2), "")
    return None


def map_stops(islands: list[dict] | None = None, coords: dict | None = None,
              manual: Path = MANUAL, stop_names: list[str] | None = None) -> list[StopIslands]:
    islands = load_census_islands() if islands is None else islands
    coords = load_stop_coords() if coords is None else coords
    stop_names = sorted({r["stop_name"] for r in read_csv(SCHEDULES)}) if stop_names is None else stop_names
    known = {i["island_id"] for i in islands}
    overrides = {r["stop_name"]: r for r in read_csv(manual)}

    result, unresolved = [], []
    for name in stop_names:
        if name in overrides:
            ids = [i for i in overrides[name]["island_ids"].split(";") if i]
            missing = [i for i in ids if i not in known]
            if missing:
                raise ValueError(f"{manual.name}: {name} refers to unknown Census island(s) {missing}")
            result.append(StopIslands(name, ids, "manual", None, None, overrides[name]["note"]))
        elif match := auto_match(name, coords[name], islands):
            result.append(match)
        else:
            unresolved.append(name)
    if unresolved:
        raise ValueError(f"No Census island match for {unresolved}; add them to {manual}")
    return result


def coverage(mapping: list[StopIslands], islands: list[dict], network: dict) -> list[dict]:
    """One row per Census island: is it served by a ferry stop in this data?"""
    stop_index = {s["id"]: i for i, s in enumerate(network["stops"])}
    stop_routes: dict[int, set] = {}
    departures: dict[int, int] = {}
    for r in network["routes"]:
        for t in r["trips"]:
            for k, (s, _) in enumerate(t["calls"]):
                stop_routes.setdefault(s, set()).add(r["id"])
                if k < len(t["calls"]) - 1:
                    departures[s] = departures.get(s, 0) + 1
    by_island: dict[str, list[str]] = {}
    for m in mapping:
        for island_id in m.island_ids:
            by_island.setdefault(island_id, []).append(stop_id(m.stop_name))
    ferry_atolls = {s["atoll"].lower() for s in network["stops"]}

    rows = []
    for i in islands:
        stops = by_island.get(i["island_id"], [])
        idx = [stop_index[s] for s in stops]
        routes = sorted({r for s in idx for r in stop_routes.get(s, ())}, key=int)
        status = ("served" if stops else
                  "no_route_in_data" if i["atoll_code"].lower() in ferry_atolls else "atoll_not_in_data")
        rows.append({"island_id": i["island_id"], "name": i["name"], "atoll_code": i["atoll_code"],
                     "population": i["population"], "ferry_status": status,
                     "stop_ids": ";".join(stops), "routes": ";".join(routes),
                     "departures_per_day": sum(departures.get(s, 0) for s in idx)})
    return rows


def main() -> None:
    for m in map_stops():
        ids = ";".join(m.island_ids) or "(none)"
        detail = f"sim={m.similarity} d={m.distance_km}km" if m.method != "manual" else m.note
        print(f"{m.method:>16}  {m.stop_name:22} -> {ids:9}  {detail}")


if __name__ == "__main__":
    main()
