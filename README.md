# yoosuf-afendi

Maldives ferry routes as open data, for the M.A.N.D.A.R.I.N transport accessibility project.

The published ferry schedules are turned into a validated [GTFS](https://gtfs.org) feed and map-ready GeoJSON, covering **27 routes, 58 daily sailings and 77 island stops across 11 atolls**.

## Use the data

Everything you need is already built in `data/`. You don't have to run anything.

| File | Use it for |
|---|---|
| `data/export/routes.geojson` | Route lines for a map. One LineString per route. |
| `data/export/stops.geojson` | Island stops for a map. One Point per island. |
| `data/export/network.json` | Timetables for dashboards and animation: every sailing with its time at each stop. |
| `data/export/stop_islands.csv` | Links each ferry stop to its Census `island_id`(s), the key used by the population data. |
| `data/export/island_ferry_coverage.csv` | Every Census island with its population and ferry status: `served`, `no_route_in_data` or `atoll_not_in_data`. |
| `data/gtfs.zip` (and `data/gtfs/`) | The full GTFS feed. Works with any GTFS tool (r5py, OpenTripPlanner, gtfs-kit). |

### routes.geojson

Coordinates are WGS84 `[lon, lat]`. Each feature's properties:

```json
{
  "route_id": "183", "also_published_as": "184", "mode": "ferry",
  "stops": ["Villingili", "Dhevvadhoo", "Thinadhoo"],
  "stop_ids": ["GA_VILLINGILI", "GA_DHEVVADHOO", "GDH_THINADHOO"],
  "atolls": ["Gaafu Alifu", "Gaafu Dhaalu"], "cross_atoll": true,
  "sailings_per_day": 2, "first_departure": "08:00", "last_arrival": "16:35"
}
```

Lines join the islands in calling order. They are straight segments, not the actual sailing path.

### stops.geojson

```json
{
  "stop_id": "F_NILANDHOO", "name": "Nilandhoo", "name_dv": "ފ.ނިލަންދޫ",
  "atoll": "Faafu", "approximate_position": false, "census_island_ids": ["1158"],
  "departures_per_day": 2, "routes": ["278", "280"]
}
```

`census_island_ids` joins to `island_id` in `data/processed/population/`. It holds two IDs for Hulhumeedhoo (Census Hulhudhoo and Meedhoo) and is empty for the four stops that aren't inhabited Census islands (Kooddoo and Kaadehdhoo airports, Felivaru, Madivaru).

### Ferry stops ↔ Census islands

Stops are matched to Census islands within the same atoll, by name (spelling variants allowed, e.g. Bandidhoo/Badidhoo) and by distance (2 km or less). `stop_islands.csv` records the method (`exact`, `spelling_variant` or `manual`), the name similarity and the distance for each stop. Manual decisions, such as Laamu Gan = Census "Gamu", live in `data/stop_islands_manual.csv`.

`island_ferry_coverage.csv` separates islands with no route in this data (`no_route_in_data`) from atolls the schedule data doesn't cover at all (`atoll_not_in_data`, including Malé). Neither means the island has no ferry; it means this dataset doesn't show one.

### network.json

```text
atolls  { "F": "Faafu", ... }                       atoll code -> name
stops   [ { id, name, atoll, dv, lat, lon, approx, islandIds } ]  islandIds = Census island_id(s)
routes  [ { id, aliases, trips: [ { id, calls: [[stop_index, minute], ...] } ] } ]
meta    { feedVersion, assumptions: [...] }
```

`stop_index` is a position in `stops`. `minute` is minutes after midnight, local time (Indian/Maldives, UTC+5). A call of `[12, 455]` would mean the boat is at `stops[12]` at 07:35. To place a boat between two stops, interpolate between consecutive calls.

### Example: MapLibre

```js
map.addSource("routes", { type: "geojson", data: "data/export/routes.geojson" });
map.addLayer({ id: "routes", type: "line", source: "routes",
  paint: { "line-color": "#1967D2", "line-width": 4 } });
map.addSource("stops", { type: "geojson", data: "data/export/stops.geojson" });
map.addLayer({ id: "stops", type: "circle", source: "stops",
  paint: { "circle-radius": 5, "circle-color": "#fff", "circle-stroke-width": 2, "circle-stroke-color": "#3C4043" } });
```

## Know the limits

- **Operating days are assumed.** The source schedule has no days of the week, so every route is treated as running daily.
- **Duplicate route numbers were merged.** 24 route numbers had identical timetables, such as 205 and 206. The lower number is kept and the other appears in `also_published_as`. They may be different days of the same service.
- **One time per stop.** The source gives a single time at each island, so arrival and departure are the same.
- **Island positions** come from OpenStreetMap. Hoadedhdhoo (Hon'dehdhoo), Mundoo and Kalaidhoo are missing or mislabelled there, so they use Census 2022 island reference points instead.
- **Road links aren't modelled.** Addu's Hithadhoo, Maradhoo and Maradhoo-Feydhoo show as `no_route_in_data`, although they are joined by road to the Feydhoo ferry stop.
- **Coverage is limited to the schedule file:** 11 atolls, with no routes to Malé. Islands in other atolls show as `atoll_not_in_data`.
- **Two legs look fast:** route 268 sailing 1 (Gaadhiffushi to Veymandoo, 15 min) and route 278 sailing 1. Either could be a speedboat or a typo in the source.
- **The operator is unverified.** The feed lists Raajje Transport Link (RTL).

`data/gtfs/provenance.txt` records the source and an `observed` / `derived` / `assumed` label for every route, stop and assumption.

The feed passes the [MobilityData GTFS validator](https://github.com/MobilityData/gtfs-validator) 8.0.1 with 0 errors.

## Rebuild the data

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run python -m pipeline.build_gtfs    # data/ferry_schedules.csv -> data/gtfs/ + data/gtfs.zip (fails on bad data)
uv run python -m pipeline.export_web    # data/gtfs/ + Census islands -> data/export/ (json, geojson, csv)
uv run pytest -q                        # 23 tests
```

`export_web` reads the Census islands from `data/processed/population/` (the population generator's output) with DuckDB. To review the stop ↔ island matching on its own, run `uv run python -m pipeline.map_islands`. A stop that matches neither automatically nor in `data/stop_islands_manual.csv` fails the export.

Edit `data/ferry_schedules.csv` and rerun the first two commands. If the schedule adds new islands, geocode them first:

```bash
uv run python -m pipeline.geocode_stops # looks up new islands in OpenStreetMap -> data/stops_geo.csv
```

Islands are matched by exact Dhivehi name within the right atoll. Any it can't match are listed. Add their coordinates by hand to `data/stops_geo_manual.csv`, which overrides the automatic results.

### Layout

```text
data/
  ferry_schedules.csv      source schedule (one row per stop time; trip_id = route number, schedule_idx = sailing)
  ferry_schedules.json     same data in its original JSON shape
  stops_geo.csv            island coordinates from OpenStreetMap
  stops_geo_manual.csv     hand-checked coordinates (override the above)
  stop_islands_manual.csv  hand-checked ferry stop -> Census island decisions
  gtfs/, gtfs.zip          generated GTFS feed
  export/                  generated GeoJSON, network.json, stop/island mapping and coverage
pipeline/
  build_gtfs.py            schedule -> GTFS, with checks
  export_web.py            GTFS -> exports
  map_islands.py           ferry stops <-> Census islands, island ferry coverage
  geocode_stops.py         island coordinates from OpenStreetMap
  stops.py                 shared helpers (atoll codes, stop IDs, coordinates)
tests/                     pipeline tests
```

## Attribution

Island coordinates © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors, available under the Open Database License (ODbL). Credit OpenStreetMap wherever you show these positions. Three stops and all Census island IDs and populations come from Census 2022 (Maldives Bureau of Statistics).
