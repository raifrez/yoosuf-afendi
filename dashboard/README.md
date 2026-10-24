# M.A.N.D.A.R.I.N dashboard

Can islanders reach their atoll hospital and get home the same day on the published ferries? This dashboard runs the real ferry schedules in `data/` through a journey simulator and shows the answer for every atoll, plus timetable changes that would help.

No build step or backend is needed:

```bash
python3 -m http.server 8765 --directory dashboard   # then open http://localhost:8765
```

Opening `dashboard/index.html` directly also works.

## What it shows

The screen is a full-height map and one rail on the right.

- **Ferries move along their routes** when you open an atoll, looping through the day (a small clock chip shows the time). Each route has its own colour; moved sailings get a turquoise outline. Positions are interpolated on straight lines between stops.
- **Current issues** lead the rail: residents who can't make a same-day hospital trip, inhabited islands not on the ferry schedule (Census ↔ ferry stops; road-linked islands in `data/road_links.csv` are excluded), long waits (2 h+ before the appointment) and very long days (10 h+). Atolls without ferry data are listed as not checked.
- **All of the Maldives:** the ferry network in numbers, how many residents can make a same-day hospital trip, and the atolls where residents are cut off (also shown as red bubbles on the map).
- **Follow the ferry:** click a ferry, or a route in the rail, to follow that sailing. The camera keeps it centred and a card lists its stops and times (passed, next with ETA, arrived). Drag the map or press × to stop.
- **Map controls:** scroll to zoom, drag to pan, or use the +/−/fit buttons. Opening an atoll frames its ferry stops; island names and route numbers are placed so they don't overlap (crowded ones appear as you zoom in).
- **One atoll:** its sailings, first and last times, its barriers (grouped by cause, such as "Route 288 docks at 10:05") and each island's journey step by step.
- **Add a stop** for an inhabited island that isn't on the schedule: tries every gap and both ends of each route in the atoll (detour time from the route's own boat speed + a 5-min call; later stops move later) and applies the placement that gets the island to the hospital and back without costing anyone access. Island positions come from `data/export/island_points.csv` (Census reference points exported from `data/processed/population/islands.parquet`).
- **Move a sailing** to compare against the published schedule. Every stop of the sailing moves together.
- **Find better times** for one atoll or every atoll. It searches 15-min shifts of sailings inside the atoll, maximizes residents with a complete trip, and never lets anyone lose access. It doesn't check boats, crews or cost.
- **Journey rule** (appointment time, length, home-by time and time to change boats). It is an assumption, so it can be changed in the sidebar to test how sensitive the results are.

## Data

| File | What it is | Status |
|---|---|---|
| `data/export/network.json` | Ferry sailings and stops (from `pipeline/`) | Observed; operating days assumed daily |
| `data/facilities.csv` | The hospital island for each atoll | 7 from OpenStreetMap, 3 assumed at the atoll capital |
| `data/export/stop_islands.csv` + `data/export/island_ferry_coverage.csv` | Each stop's Census island(s) and their populations (from `pipeline/map_islands.py`) | Observed: Census 2022 people enumerated per island. Hulhumeedhoo sums Census Hulhudhoo and Meedhoo; Kooddoo, Kaadehdhoo, Felivaru and Madivaru aren't inhabited Census islands, so they count 0 residents. The hospital island's own residents aren't modeled |
| `data/island_population.csv` | Manual population overrides (`stop_id,population,source,year`) | Empty; a row replaces that stop's Census figure |
| `dashboard/maldives-geo.js` | Island and reef outlines for the map | OpenStreetMap (ODbL), simplified |

After changing anything in `data/`, rebuild the dashboard bundle:

```bash
python3 dashboard/build_data.py
```

## Files

| File | Role |
|---|---|
| `build_data.py` | Bundles `data/` into `network-data.js` |
| `simulator.js` | Journey routing, failure reasons, aggregation, comparison and the timetable optimizer |
| `map.js` | Maldives map, atoll zoom, routes, stops and problem bubbles |
| `app.js` | Dashboard views; every number comes from simulator output |
| `dropdown.js` | Themed dropdown used in place of native selects |
| `index.html` | Layout and styles |
