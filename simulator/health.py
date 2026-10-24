"""Healthcare demand: one appointment per resident per category, at spread times. Pure: no file I/O.

Traveller categories (who -> destination service level):
  health_centre     everyone      nearest health centre or hospital (primary care)
  hospital_child    ages 0-17     nearest hospital in the home atoll (travels with a guardian)
  hospital_adult    ages 18-64    nearest hospital in the home atoll
  hospital_elderly  ages 65+      nearest hospital in the home atoll, home earlier
  referral          everyone      nearest Grade 3 or tertiary hospital, any atoll

Rules (labels in HEALTH_PARAM_NOTES):
  - Each resident gets one appointment per category that applies to them. A rate is the share
    of residents who could make an appointment at their assigned time, not a count of visits.
  - Appointment times are spread over 08:00-14:00 every 30 min, and durations over the level's
    options, chosen deterministically from the person ID and a fixed seed.
  - Destination = nearest by ferry on the baseline (simulator.destinations). A facility on the
    home island needs no ferry (on_island). With no facility of the level on the ferry network,
    the need is no_facility: the data can't answer it, which is not the same as no access.
  - Residents with identical requests are grouped into one Need with a weight; the person ->
    need mapping is kept so a resident's itinerary can be inspected.
"""

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from simulator.destinations import FerryDistances
from simulator.evaluate import NO_DATA, ON_ISLAND, Request
from simulator.scores import NO_FACILITY, Need

HEALTH_CENTRE, HOSPITAL_CHILD, HOSPITAL_ADULT, HOSPITAL_ELDERLY, REFERRAL = (
    "health_centre", "hospital_child", "hospital_adult", "hospital_elderly", "referral")
CATEGORY_NOTES = {
    HEALTH_CENTRE: "Everyone: nearest health centre or hospital (primary care).",
    HOSPITAL_CHILD: "Ages 0-17: nearest hospital in the home atoll, travelling with a guardian.",
    HOSPITAL_ADULT: "Ages 18-64: nearest hospital in the home atoll.",
    HOSPITAL_ELDERLY: "Ages 65+: nearest hospital in the home atoll, home by an earlier time.",
    REFERRAL: "Everyone: nearest Grade 3 or tertiary hospital in any atoll.",
}


@dataclass(frozen=True)
class Resident:
    person_id: str
    home_island_id: str
    age: int
    weight: int = 1
    display_name: str | None = None


@dataclass(frozen=True)
class HealthFacility:
    facility_id: str
    name: str
    island_id: str
    facility_type: str  # hospital | health_centre | clinic
    level_family: str | None = None  # HG | T | HCG | GC
    level_number: int | None = None

    @property
    def is_referral_level(self) -> bool:
        return self.level_family == "T" or (self.level_family == "HG" and (self.level_number or 0) >= 3)


@dataclass(frozen=True)
class HealthParams:
    appointment_slots: tuple[int, ...] = tuple(range(8 * 60, 14 * 60 + 1, 30))
    durations: tuple[tuple[str, tuple[int, ...]], ...] = (
        (HEALTH_CENTRE, (30,)), (HOSPITAL_CHILD, (60, 120)), (HOSPITAL_ADULT, (60, 120)),
        (HOSPITAL_ELDERLY, (60, 120)), (REFERRAL, (120,)))
    home_by: int = 18 * 60
    elderly_home_by: int = 17 * 60
    seed: int = 42

    def duration_options(self, category: str) -> tuple[int, ...]:
        return dict(self.durations)[category]


HEALTH_PARAM_NOTES = {
    "one_appointment_each": ("assumed", "Each resident gets one appointment per category; rates are shares of "
                                        "residents, not visit counts."),
    "appointment_slots": ("assumed", "08:00-14:00 every 30 min, spread evenly over residents."),
    "durations": ("assumed", "Health centre 30 min; hospital 60 or 120 min; referral 120 min."),
    "home_by": ("assumed", "Home by 18:00; ages 65+ by 17:00."),
    "home_atoll_hospital": ("assumed", "Hospital visits go to a hospital in the home atoll."),
    "referral_level": ("derived", "Grade 3 and tertiary hospitals, from the Ministry of Health level codes."),
}


def categories_for(age: int) -> tuple[str, ...]:
    hospital = HOSPITAL_CHILD if age < 18 else HOSPITAL_ADULT if age < 65 else HOSPITAL_ELDERLY
    return HEALTH_CENTRE, hospital, REFERRAL


def appointment(person_id: str, category: str, params: HealthParams) -> tuple[int, int]:
    """(start minute, duration) for a resident's appointment, deterministic per seed."""
    h = int(hashlib.sha256(f"{params.seed}:{person_id}:{category}".encode()).hexdigest()[:12], 16)
    slots, durations = params.appointment_slots, params.duration_options(category)
    return slots[h % len(slots)], durations[(h // len(slots)) % len(durations)]


def health_needs(distances: FerryDistances, island_atoll: Mapping[str, str], residents: Iterable[Resident],
                 facilities: Sequence[HealthFacility], params: HealthParams = HealthParams()
                 ) -> tuple[list[Need], dict[tuple[str, str], str]]:
    """Grouped healthcare needs, and (person_id, category) -> need_id."""
    pools = {
        HEALTH_CENTRE: [f for f in facilities if f.facility_type in ("health_centre", "hospital")],
        "hospital": [f for f in facilities if f.facility_type == "hospital"],
        REFERRAL: [f for f in facilities if f.is_referral_level],
    }
    destinations: dict[tuple[str, str], HealthFacility | str] = {}

    def destination(category: str, home: str) -> HealthFacility | str:
        """The facility, or the label for a need without a trip."""
        if (category, home) in destinations:
            return destinations[category, home]
        pool = pools.get(category, pools["hospital"])
        if category not in (HEALTH_CENTRE, REFERRAL):
            pool = [f for f in pool if island_atoll.get(f.island_id) == island_atoll.get(home)]
        local = [f for f in pool if f.island_id == home]
        if local:
            found = ON_ISLAND
        elif not distances.has_stop(home):
            found = NO_DATA
        else:
            near = distances.nearest(home, [f for f in pool if distances.has_stop(f.island_id)],
                                     lambda f: f.island_id, lambda f: f.facility_id)
            found = near[1] if near else NO_FACILITY
        destinations[category, home] = found
        return found

    weights, templates, person_need = defaultdict(int), {}, {}
    for r in residents:
        for category in categories_for(r.age):
            dest = destination(category, r.home_island_id)
            if isinstance(dest, str):
                need_id = f"health:{category}:{r.home_island_id}:{dest}"
                templates.setdefault(need_id, dict(label=dest))
            else:
                start, duration = appointment(r.person_id, category, params)
                need_id = f"health:{category}:{r.home_island_id}:{dest.facility_id}:{start}:{duration}"
                if need_id not in templates:
                    home_by = params.elderly_home_by if category == HOSPITAL_ELDERLY else params.home_by
                    templates[need_id] = dict(request=Request(
                        need_id, r.home_island_id, dest.island_id, start, duration, home_by, purpose="healthcare",
                        destination_facility_id=dest.facility_id, data_classification="assumed"))
            weights[need_id] += r.weight
            person_need[r.person_id, category] = need_id
    needs = [Need(need_id, need_id.split(":")[1], need_id.split(":")[2], weights[need_id], **templates[need_id])
             for need_id in sorted(weights)]
    return needs, person_need
