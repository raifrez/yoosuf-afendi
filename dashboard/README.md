# M.A.N.D.A.R.I.N dashboard

A static prototype of the impact dashboard. It needs no build step and no backend.

```bash
open dashboard/index.html
```

You can also serve the folder with any static server (for example `python3 -m http.server` from inside `dashboard/`).

**All data is fictional.** `data.js` describes a made-up atoll so the UI and simulator can be built before real data is ready.

## Files

| File | Role | When the backend arrives |
|---|---|---|
| `maldives-geo.js` | Real island and reef outlines for all 20 atolls, from OpenStreetMap (© OpenStreetMap contributors, ODbL), simplified to ~220 KB | Keep; regenerate if you need more detail |
| `map.js` | Maldives map: atoll zoom and the ferry-network overlay | — |
| `data.js` | Demo fixture: islands, trips, journey rules, sources. `atollId` sets which atoll the demo network is drawn in | Replace with real, sourced records in the same shape (or an API that returns it) |
| `simulator.js` | Population generator, journey routing, aggregation, baseline vs scenario comparison, and the timetable optimizer | Can move server-side; keep the output record fields (see `M.A.N.D.A.R.I.N_MAJOR_COMPONENTS.md`) |
| `app.js` | Renders everything from simulator output | Swap `Mandarin.run(...)` for an API call |
| `index.html` | Layout and styles | — |

## Demo stories built into the fixture

| Island | What happens |
|---|---|
| B | The only morning ferry arrives after a 10:00 appointment, and students arrive 3 h 10 min late |
| C | Residents reach the hospital, but the last ferry home leaves at 11:30 |
| D | Misses the connection at Island A by 10 min (5 min gap, 15 min needed) |
| E | No ferry runs on Tuesdays |
| F | Secondary students (45% of the island's school-age children) arrive 60 min late because the ferry leaves at 07:30 |
| G | Everything works, but residents wait 2 h 45 min before the appointment |

The "Try" buttons replay each fix, plus one change that causes a loss (Island A's ferry 90 min later).

## Suggested timetable

"Find the best timetable" searches departure shifts (15-min steps, up to ±4 h, departures 05:00–22:00) one ferry at a time, repeating until nothing improves. It maximizes the people who can complete their trip, never lets anyone who had access lose it, and prefers the fewest minutes moved. "Also cut waiting time" adds waiting as a second goal. It does not check boats, crews, harbour slots or cost, and it can't fix an island with no service that day.

On the demo data it suggests 4 changes: hospital access goes from 54% to 93% and the full school day from 70 to 420 of 470 students. Island E stays unfixed because it has no Tuesday ferry.
