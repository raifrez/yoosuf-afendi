"""The demo story: one resident whose hospital visit fails, and one edit that helps and hurts.

Found by sweeping every Faafu/Dhaalu sailing through shifts of -90..+90 min (2026-10-24):
moving 288_1 (Kudahuvadhoo 14:05 -> Meedhoo) 75 min later lets afternoon hospital visits
in Dhaalu get home the same day, while elderly Meedhoo residents now get home after 17:00.

The resident is the first (by person ID) Meedhoo adult whose visit fails in the baseline
because there is no way home, and succeeds with the edit.
"""

from simulator.health import HOSPITAL_ADULT
from simulator.model import Model, Scenario
from simulator.scores import outcome
from simulator.timetable import TripShift

DEMO_EDIT = TripShift("288_1", 75)
DEMO_ISLAND = "1050"  # Dh.Meedhoo


def demo_story(model: Model) -> dict | None:
    if DEMO_ISLAND not in model.region:
        return None
    scenario = Scenario((DEMO_EDIT,))
    run = model.run(scenario)
    base_needs = {n.need_id: n for n in model.baseline.needs}
    scen_needs = {n.need_id: n for n in run.needs}
    for pid in sorted(model.residents):
        r = model.residents[pid]
        if r.home_island_id != DEMO_ISLAND or (pid, HOSPITAL_ADULT) not in model.person_health:
            continue
        need_id = model.person_health[pid, HOSPITAL_ADULT]
        if (outcome(base_needs[need_id], model.baseline.results) == "no_return"
                and outcome(scen_needs[need_id], run.results) == "success"):
            return {"person_id": pid, "display_name": r.display_name, "category": HOSPITAL_ADULT,
                    "island_id": DEMO_ISLAND, "scenario": scenario.as_dict(),
                    "compare": model.compare_payload(run)}
    return None
