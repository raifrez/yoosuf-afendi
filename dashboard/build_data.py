"""Bundle the ferry network and dashboard inputs into dashboard/network-data.js.

Reads data/export/network.json (from pipeline.export_web), data/facilities.csv
and the stop populations: data/export/stop_islands.csv links each stop to its
Census island(s) and data/export/island_ferry_coverage.csv gives each island's
Census 2022 population. A stop's population is the sum over its islands; a stop
that is not a Census inhabited island (airport, industrial) has 0 residents.
Rows in data/island_population.csv override a stop's figure by hand. Rerun
after rebuilding the feed:

    python3 dashboard/build_data.py
"""

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = Path(__file__).resolve().parent / "network-data.js"

# Feed atoll codes -> map (maldives-geo.js) atoll ids
GEO_ID = {"Ga": "GA", "Gdh": "GDh"}


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [row for row in csv.DictReader(f) if any(v.strip() for v in row.values() if v)]


CENSUS_SOURCE = "Census 2022 (Maldives Bureau of Statistics)"


def stop_populations(stop_ids: list[str]) -> dict[str, dict]:
    """stop_id -> {population, source, islandIds, note}; raises if a stop is unmatched."""
    island_pop = {r["island_id"]: int(r["population"]) for r in read_csv(DATA / "export" / "island_ferry_coverage.csv")}
    links = {r["stop_id"]: r for r in read_csv(DATA / "export" / "stop_islands.csv")}
    overrides = {r["stop_id"]: r for r in read_csv(DATA / "island_population.csv") if r.get("population")}
    out, unmatched = {}, []
    for sid in stop_ids:
        if sid in overrides:
            o = overrides[sid]
            src = " ".join(x for x in (o.get("source"), o.get("year")) if x) or "data/island_population.csv"
            out[sid] = {"population": int(o["population"]), "source": src, "islandIds": [], "note": "manual override"}
            continue
        link = links.get(sid)
        ids = [i for i in (link["island_ids"].split(";") if link else []) if i]
        if link is None or any(i not in island_pop for i in ids):
            unmatched.append(sid)
            continue
        out[sid] = {"population": sum(island_pop[i] for i in ids), "source": CENSUS_SOURCE, "islandIds": ids,
                    "note": link.get("note") or None}
    if unmatched:
        raise SystemExit(f"no Census population for stops: {', '.join(unmatched)} "
                         "(add them to data/stop_islands_manual.csv or data/island_population.csv)")
    return out


def main() -> None:
    net = json.loads((DATA / "export" / "network.json").read_text(encoding="utf-8"))
    pops = stop_populations([s["id"] for s in net["stops"]])

    stops = []
    for s in net["stops"]:
        p = pops.get(s["id"])
        stops.append({
            "id": s["id"], "name": s["name"], "dv": s.get("dv", ""), "atoll": GEO_ID.get(s["atoll"], s["atoll"]),
            "lat": s["lat"], "lon": s["lon"], "approx": s.get("approx", False),
            "population": p["population"], "populationSource": p["source"],
            "censusIslandIds": p["islandIds"], "populationNote": p["note"],
        })

    trips = []
    for r in net["routes"]:
        for t in r["trips"]:
            trips.append({
                "id": f"R{t['id']}", "route": r["id"], "aliases": r.get("aliases") or "",
                "calls": [[net["stops"][i]["id"], m] for i, m in t["calls"]],
            })

    facilities = []
    for f in read_csv(DATA / "facilities.csv"):
        facilities.append({
            "atoll": GEO_ID.get(f["atoll"], f["atoll"]), "stop": f["stop_id"], "name": f["facility"],
            "service": f["service"], "walkMin": int(f["harbour_to_facility_min"] or 10),
            "classification": f["classification"], "source": f["source"], "note": f["note"],
        })

    # Every Census island, with whether the ferry schedule serves it. Used for the
    # "not on the ferry schedule" issue. Census atoll codes differ slightly from the map's.
    census_atoll = {"Adh": "ADh", "MLE": "K"}
    road = {(r["atoll"], r["island_name"]): r for r in read_csv(DATA / "road_links.csv")}
    islands = []
    for r in read_csv(DATA / "export" / "island_ferry_coverage.csv"):
        link = road.get((r["atoll_code"], r["name"]))
        islands.append({
            "id": r["island_id"], "name": r["name"],
            "atoll": GEO_ID.get(r["atoll_code"], census_atoll.get(r["atoll_code"], r["atoll_code"])),
            "population": int(r["population"] or 0), "status": r["ferry_status"],
            "stops": [x for x in (r["stop_ids"] or "").split(";") if x],
            "roadLinkedTo": link["linked_stop_id"] if link else None,
            "roadNote": link["note"] if link else None,
        })

    bundle = {
        "meta": {
            **net.get("meta", {}),
            "builtFrom": ["data/export/network.json", "data/facilities.csv", "data/export/stop_islands.csv",
                          "data/export/island_ferry_coverage.csv", "data/island_population.csv", "data/road_links.csv"],
            "population": {
                "source": CENSUS_SOURCE, "year": 2022, "classification": "observed",
                "measure": "People enumerated on each Census island (Malé wards and administrative islands)",
                "files": ["data/export/stop_islands.csv", "data/export/island_ferry_coverage.csv"],
                "overrides": sum(1 for p in pops.values() if p["note"] == "manual override"),
            },
        },
        "atolls": {GEO_ID.get(k, k): v for k, v in net["atolls"].items()},
        "stops": stops, "trips": trips, "facilities": facilities, "islands": islands,
    }
    OUT.write_text(
        "// Generated by dashboard/build_data.py from data/. Do not edit by hand.\n"
        "// Island coordinates © OpenStreetMap contributors (ODbL).\n"
        "window.MANDARIN_DATA = " + json.dumps(bundle, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT.relative_to(ROOT)}: {len(stops)} stops, {len(trips)} sailings, "
          f"{len(facilities)} facilities, {sum(1 for s in stops if s['population'] is not None)} populations "
          f"({sum(1 for s in stops if s['population'] == 0)} with no Census residents)")


if __name__ == "__main__":
    main()
