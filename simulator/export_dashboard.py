"""Bundle engine results for the dashboard into dashboard/engine-data.js (no server needed).

  uv run python -m simulator.export_dashboard

window.MANDARIN_ENGINE = {
  meta        categories, atolls, islands {island_id: {name, atoll, population}}
  baseline    scores per island x category and atoll x category (as /api/baseline)
  demo        the demo resident with before/after itineraries (as /api/demo)
  scenarios   [{id, label, description, scenario, compare (as /api/scenario), scores (after the change)}]
}
Scenarios are precomputed with the same engine and rules as the API: two single-sailing
shifts, Find better times for Dhaalu, and Add a stop for GA. Maamendhoo.
"""

import json
import sys
from dataclasses import replace
from pathlib import Path

from simulator.demo_story import demo_story
from simulator.load import load_island_stops
from simulator.model import AddedStop, Model, Scenario
from simulator.optimize import best_stop, run_search
from simulator.schools import DEFAULT_SESSION
from simulator.timetable import TripShift

OUT = Path(__file__).resolve().parent.parent / "dashboard" / "engine-data.js"
MAAMENDHOO = "1085"


def place(model: Model, stop_id: str) -> str:
    """Census island name for a ferry stop (the stop's own island, not road links)."""
    if stop_id.startswith("ADD_"):
        return model.islands[stop_id[4:]]["name"]
    direct = {s: i for i, stops in load_island_stops(road_links=None).items() for s in stops}
    if stop_id in direct:
        return model.islands[direct[stop_id]]["name"]
    return model.stop_names.get(stop_id, stop_id).split(".", 1)[-1]  # "Ga.Kooddoo" (airport) -> "Kooddoo"


def sailings(model: Model, scenario: Scenario) -> str:
    """'The 16:45 boat from Viligili to Gemanafushi leaves at 15:35 instead (arrives 17:00, not 18:10).' per shift."""
    before = model.network(replace(scenario, timetable_edits=()))[0]
    after = model.network(scenario)[0]
    out = []
    for e in scenario.timetable_edits:
        b, a = before.trip(e.trip_id).stop_times, after.trip(e.trip_id).stop_times
        via = [place(model, st.stop_id) for st in a[1:-1]]
        out.append(f"The {hhmm(b[0].departure)} boat from {place(model, b[0].stop_id)} "
                   f"{'via ' + ', '.join(via) + ' ' if via else ''}to {place(model, b[-1].stop_id)} "
                   f"leaves at {hhmm(a[0].departure)} instead (arrives {hhmm(a[-1].arrival)}, not {hhmm(b[-1].arrival)}).")
    return " ".join(out)


def scenarios(model: Model) -> list[tuple[str, str, str, Scenario]]:
    found = run_search(model, Scenario(), "Dh")
    stop = best_stop(model, Scenario(), MAAMENDHOO)["best"]
    name = model.islands[MAAMENDHOO]["name"]
    viligili = Scenario((TripShift("236_1", -70),))
    kudahuvadhoo = Scenario((TripShift("288_1", 75),))
    dhaalu = Scenario(tuple(TripShift(t, s) for t, s in found["shifts"].items()))
    new_stop = Scenario(tuple(TripShift(t, s) for t, s in stop["shifts"].items()),
                        added_stops=(AddedStop(MAAMENDHOO, stop["route_id"], stop["a"], stop["b"]),))
    where = (f"after {place(model, stop['a'])}, at the end of the route" if stop["b"] is None
             else f"between {place(model, stop['a'])} and {place(model, stop['b'])}")
    return [
        ("viligili-earlier", "Earlier boat home from Viligili", sailings(model, viligili), viligili),
        ("kudahuvadhoo-later", "Later last boat from Kudahuvadhoo", sailings(model, kudahuvadhoo), kudahuvadhoo),
        ("dhaalu-better-times", "Better boat times for Dhaalu",
         "Found by searching Dhaalu's own boats in 15-min steps for the times that make the most trips work "
         "without anyone losing one. " + sailings(model, dhaalu), dhaalu),
        ("maamendhoo-stop", f"New ferry stop at {name}",
         f"{name} has no ferry stop today. Route {stop['route_id']}'s boats also call there ({where})."
         + (" Its times also move so connections keep working. " + sailings(model, new_stop) if new_stop.timetable_edits else ""), new_stop),
    ]


def hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def rules(model: Model) -> list[str]:
    """How the synthetic residents travel, read from the parameters the model runs with."""
    h, s, p = model.health_params, model.school_params, model.params
    slots = h.appointment_slots
    mins = lambda c: " or ".join(f"{d} min" for d in h.duration_options(c))  # noqa: E731
    return [
        f"Each resident gets one appointment per kind of care, at a fixed time between {hhmm(slots[0])} and {hhmm(slots[-1])} "
        f"(every {slots[1] - slots[0]} min): health centre {mins('health_centre')}, hospital {mins('hospital_adult')}, referral {mins('referral')}.",
        f"They must arrive by the appointment and be home by {hhmm(h.home_by)}; residents aged 65+ by {hhmm(h.elderly_home_by)}.",
        "Children (0-17), adults (18-64) and the elderly (65+) go to the nearest hospital in their home atoll; "
        "referrals go to the nearest Grade 3 or tertiary hospital in any atoll.",
        f"Students (6-17) whose grade isn't taught at home commute daily if the school is within "
        f"{s.max_school_commute_minutes} min by ferry; further away they board. School starts {hhmm(DEFAULT_SESSION.start)}.",
        f"Connections need {p.min_transfer_minutes} min. Islands with no ferry stop in the schedule show as no data.",
    ]


def main() -> int:
    model = Model()
    meta = model.meta()
    out = {
        "meta": {"categories": meta["categories"], "atolls": meta["atolls"], "residents": len(model.residents),
                 "population_source": "built from Census 2022 and HIES 2019 (one record per person)",
                 "rules": rules(model),
                 "islands": {i["island_id"]: {"name": i["name"], "atoll": i["atoll"], "population": i["population"]}
                             for i in meta["islands"]}},
        "baseline": model.scores_payload(model.baseline),
        "demo": demo_story(model),
        "scenarios": [],
    }
    for sid, label, description, scenario in scenarios(model):
        run = model.run(scenario)
        out["scenarios"].append({"id": sid, "label": label, "description": description, "scenario": scenario.as_dict(),
                                 "compare": model.compare_payload(run), "scores": model.scores_payload(run)})
    OUT.write_text("// Generated by simulator/export_dashboard.py. Do not edit by hand.\n"
                   "window.MANDARIN_ENGINE = " + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";\n")
    print(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB, {len(out['scenarios'])} scenarios)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
