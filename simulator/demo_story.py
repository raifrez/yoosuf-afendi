"""The demo story: one fixed resident whose hospital visit fails, and one edit that helps and hurts.

Resident (fixed demo input, chosen 2026-10-24): Aminath Shafeeg, 68, GA. Gemanafushi, the first
resident aged 65+ on the island with a healthcare request in the generated demand. Her elderly
hospital visit goes to Viligili (Gaafu Alifu Atoll Hospital, Grade 2). She arrives at 07:50, but
the only boat home (236_1, Viligili 16:45) lands at 18:10, after her 17:00 home-by: no_return.
Thinadhoo (her referral hospital) fails too: she arrives late.

Edit: 236_1 leaves Viligili 70 min earlier (15:35, home 17:00). Found by sweeping 236_1 through
-35..-120 min in the model: -70 is the smallest shift that brings her home in time and has the
largest gain. Kodey loses: its residents back from Thinadhoo reach Viligili after 236_1 has gone.
"""

from simulator.health import HOSPITAL_ELDERLY
from simulator.model import Model, Scenario
from simulator.timetable import TripShift

DEMO_PERSON = "person-1182-000243-001"  # Aminath Shafeeg, GA. Gemanafushi
DEMO_CATEGORY = HOSPITAL_ELDERLY
DEMO_EDIT = TripShift("236_1", -70)


def demo_story(model: Model) -> dict | None:
    r = model.residents.get(DEMO_PERSON)
    if r is None:
        return None
    scenario = Scenario((DEMO_EDIT,))
    return {"person_id": DEMO_PERSON, "display_name": r.display_name, "age": r.age, "category": DEMO_CATEGORY,
            "island_id": r.home_island_id, "data_classification": "demo", "scenario": scenario.as_dict(),
            "compare": model.compare_payload(model.run(scenario))}
