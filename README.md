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
  "atoll": "Faafu", "approximate_position": false,
  "departures_per_day": 2, "routes": ["278", "280"]
}
```

### network.json

```text
atolls  { "F": "Faafu", ... }                       atoll code -> name
stops   [ { id, name, atoll, dv, lat, lon, approx } ]
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
- **Three island positions are approximate:** Hon'dehdhoo, Mundoo and Kalaidhoo. They are flagged with `approximate_position: true` and need verifying.
- **Two legs look fast:** route 268 sailing 1 (Gaadhiffushi to Veymandoo, 15 min) and route 278 sailing 1. Either could be a speedboat or a typo in the source.
- **The operator is unverified.** The feed lists Raajje Transport Link (RTL).

`data/gtfs/provenance.txt` records the source and an `observed` / `derived` / `assumed` label for every route, stop and assumption.

The feed passes the [MobilityData GTFS validator](https://github.com/MobilityData/gtfs-validator) 8.0.1 with 0 errors.

## Rebuild the data

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run python -m pipeline.build_gtfs    # data/ferry_schedules.csv -> data/gtfs/ + data/gtfs.zip (fails on bad data)
uv run python -m pipeline.export_web    # data/gtfs/ -> data/export/*.json, *.geojson
uv run pytest -q                        # 16 tests
```

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
  gtfs/, gtfs.zip          generated GTFS feed
  export/                  generated GeoJSON + network.json
pipeline/
  build_gtfs.py            schedule -> GTFS, with checks
  export_web.py            GTFS -> GeoJSON + network.json
  geocode_stops.py         island coordinates from OpenStreetMap
  stops.py                 shared helpers (atoll codes, stop IDs, coordinates)
tests/                     pipeline tests
```

## Attribution

Island coordinates © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors, available under the Open Database License (ODbL). Credit OpenStreetMap wherever you show these positions.
