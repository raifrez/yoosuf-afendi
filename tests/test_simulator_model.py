"""Healthcare demand, scoring, weighted totals, the model and the API's scenario parsing."""

from collections import Counter

import pytest

from simulator.demo_story import DEMO_EDIT, demo_story
from simulator.destinations import FerryDistances
from simulator.evaluate import evaluate_requests
from simulator.health import (HEALTH_CENTRE, HOSPITAL_ADULT, HOSPITAL_CHILD, HOSPITAL_ELDERLY, REFERRAL,
                              HealthFacility, HealthParams, Resident, appointment, categories_for, health_needs)
from simulator.model import Model, Scenario
from simulator.schools import SCHOOL, SCHOOL_AGES
from simulator.scores import NO_FACILITY, Need, check_totals, score, weighted_median
from simulator.server import parse_scenario
from simulator.timetable import StopTime, Timetable, Trip, TripShift


def trip(trip_id, *calls):
    return Trip(trip_id, trip_id.split("_")[0], tuple(StopTime(s, t, t) for s, t in calls))


# h -> p (hospital island) at 07:00-07:30, back 15:00-15:30; n has no stop.
TIMETABLE = Timetable((trip("T_0", ("H", 420), ("P", 450)), trip("T_1", ("P", 900), ("H", 930))))
STOPS = {"h": {"H"}, "p": {"P"}}
ATOLLS = {"h": "X", "p": "X", "n": "X"}
FACILITIES = [HealthFacility("hc_h", "H Health Centre", "h", "health_centre", "HCG", 1),
              HealthFacility("hosp_p", "P Hospital", "p", "hospital", "HG", 1)]
RESIDENTS = [Resident("r1", "h", 30), Resident("r2", "h", 70), Resident("r3", "h", 10, weight=2),
             Resident("r4", "n", 40), Resident("r5", "p", 50)]


def test_categories_and_appointments_are_deterministic():
    assert categories_for(17) == (HEALTH_CENTRE, HOSPITAL_CHILD, REFERRAL)
    assert categories_for(18)[1] == HOSPITAL_ADULT and categories_for(65)[1] == HOSPITAL_ELDERLY
    params = HealthParams()
    assert appointment("p1", HOSPITAL_ADULT, params) == appointment("p1", HOSPITAL_ADULT, params)
    starts = Counter(appointment(f"p{i}", HOSPITAL_ADULT, params)[0] for i in range(2600))
    assert set(starts) == set(params.appointment_slots) and min(starts.values()) > 150  # spread over all slots


def test_health_needs_destinations_and_weights():
    needs, person = health_needs(FerryDistances(TIMETABLE, STOPS, 5), ATOLLS, RESIDENTS, FACILITIES)
    by_id = {n.need_id: n for n in needs}
    assert by_id[person["r1", HEALTH_CENTRE]].label == "on_island"
    hospital = by_id[person["r1", HOSPITAL_ADULT]]
    assert hospital.request.destination_island_id == "p" and hospital.request.home_by == 18 * 60
    assert by_id[person["r2", HOSPITAL_ELDERLY]].request.home_by == 17 * 60
    assert by_id[person["r4", HOSPITAL_ADULT]].label == "no_data"  # no ferry stop, no local hospital
    assert by_id[person["r5", HOSPITAL_ADULT]].label == "on_island"
    assert by_id[person["r1", REFERRAL]].label == NO_FACILITY  # no Grade 3 hospital anywhere
    for category in (HEALTH_CENTRE, REFERRAL):  # everyone, with r3 weighing 2
        assert sum(n.weight for n in needs if n.category == category) == 6


def test_scores_and_weighted_totals():
    needs, _ = health_needs(FerryDistances(TIMETABLE, STOPS, 5), ATOLLS, RESIDENTS, FACILITIES)
    results = {r.request_id: r for r in evaluate_requests(TIMETABLE, STOPS, [n.request for n in needs if n.request])}
    scores = score(needs, results)
    check_totals(needs, scores)
    assert scores["p", HOSPITAL_ADULT].success_rate is None and scores["p", HOSPITAL_ADULT].on_island == 1
    assert scores["n", HOSPITAL_ADULT].success_rate is None and scores["n", HOSPITAL_ADULT].no_data == 1
    s = scores["h", HOSPITAL_ADULT]  # arrives 07:30, last boat home 15:00: some slots fail
    assert s.total == s.travellers == 1 and s.success + sum(s.failures.values()) == 1
    with pytest.raises(AssertionError):
        check_totals(needs + [Need("extra", HOSPITAL_ADULT, "h", 1, label="no_data")], scores)


def test_weighted_median():
    assert weighted_median([]) is None
    assert weighted_median([(10, 1), (20, 1), (30, 5)]) == 30
    assert weighted_median([(10, 3), (20, 1)]) == 10


@pytest.fixture(scope="module")
def model():
    return Model()


def test_model_totals_match_residents(model):
    residents = list(model.residents.values())
    for category in (HEALTH_CENTRE, REFERRAL):
        assert sum(s.total for (_, c), s in model.baseline.islands.items() if c == category) == sum(r.weight for r in residents)
    adults = sum(r.weight for r in residents if 18 <= r.age < 65)
    assert sum(s.total for (_, c), s in model.baseline.islands.items() if c == HOSPITAL_ADULT) == adults
    students = sum(r.weight for r in residents if r.age in SCHOOL_AGES)
    assert sum(s.total for (_, c), s in model.baseline.islands.items() if c == SCHOOL) == students
    # Atoll scores are sums over residents, not averages of islands.
    for (atoll, category), s in model.baseline.atolls.items():
        parts = [v for (i, c), v in model.baseline.islands.items() if c == category and model.island_atoll[i] == atoll]
        assert s.total == sum(p.total for p in parts) and s.success == sum(p.success for p in parts)


def test_scenario_never_changes_baseline_and_networks_stay_isolated(model):
    before = {k: v.as_dict() for k, v in model.baseline.islands.items()}
    run = model.run(Scenario((TripShift("288_1", 75),)))
    assert {k: v.as_dict() for k, v in model.baseline.islands.items()} == before
    for (island, category), s in run.islands.items():
        if model.island_atoll[island] in ("GA", "GDh"):
            assert s.as_dict() == before[island, category]


def test_demo_story_has_gains_and_losses(model):
    story = demo_story(model)
    assert story["scenario"]["timetable_edits"] == [{"trip_id": DEMO_EDIT.trip_id, "shift_minutes": DEMO_EDIT.shift_minutes}]
    assert story["compare"]["gained"] > 0 and story["compare"]["lost"] > 0
    trips = {t["category"]: t for t in model.resident_payload(story["person_id"], model.run(Scenario((DEMO_EDIT,))))["trips"]}
    assert (trips[HOSPITAL_ADULT]["baseline"]["outcome"], trips[HOSPITAL_ADULT]["scenario"]["outcome"]) == ("no_return", "success")


def test_parse_scenario():
    s = parse_scenario({"timetable_edits": [{"trip_id": "280_0", "shift_minutes": 10}],
                        "default_session": {"start": "08:00", "end": "13:00"},
                        "school_sessions": {"f1": {"start": "10:15", "end": "14:00"}}})
    assert s.timetable_edits == (TripShift("280_0", 10),) and s.default_session.start == 480
    assert s.school_sessions[0][0] == "f1" and parse_scenario({}).is_baseline
    with pytest.raises(ValueError):
        parse_scenario({"timetable_edits": [{"trip_id": "280_0", "shift_minutes": "10"}]})
    with pytest.raises(ValueError):
        parse_scenario({"default_session": {"start": "13:00", "end": "08:00"}})
