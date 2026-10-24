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
| `data.js` | Demo fixture: islands, trips, journey rules, sources | Replace with real, sourced records in the same shape (or an API that returns it) |
| `simulator.js` | Population generator, journey routing, aggregation, baseline vs scenario comparison | Can move server-side; keep the output record fields (see `M.A.N.D.A.R.I.N_MAJOR_COMPONENTS.md`) |
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
