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
- **All of the Maldives:** the ferry network in numbers, how many islands can make a same-day hospital trip, and the atolls where islands are cut off (also shown as red bubbles on the map).
- **Map controls:** scroll to zoom, drag to pan, or use the +/−/fit buttons. Opening an atoll frames its ferry stops; island names and route numbers are placed so they don't overlap (crowded ones appear as you zoom in).
- **One atoll:** its sailings, first and last times, its barriers (grouped by cause, such as "Route 288 docks at 10:05") and each island's journey step by step.
- **Move a sailing** to compare against the published schedule. Every stop of the sailing moves together.
- **Suggest a timetable** for one atoll or every atoll. It searches 15-min shifts of sailings inside the atoll, maximizes islands with a complete trip, and never lets anyone lose access. It doesn't check boats, crews or cost.
- **Journey rule** (appointment time, length, home-by time and time to change boats). It is an assumption, so it can be changed in the sidebar to test how sensitive the results are.

## Data

| File | What it is | Status |
|---|---|---|
| `data/export/network.json` | Ferry sailings and stops (from `pipeline/`) | Observed; operating days assumed daily |
| `data/facilities.csv` | The hospital island for each atoll | 7 from OpenStreetMap, 3 assumed at the atoll capital |
| `data/island_population.csv` | Island populations | **Empty.** Until it's filled, each island counts once. Add Census 2022 figures (`stop_id,population,source,year`) and every count switches to residents |
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
