"""Stop insertion, road links, dashboard payloads, Find better times and Add a stop."""

import pytest

from simulator.dashboard import HOSPITAL, Dashboard
from simulator.load import load_island_stops
from simulator.model import AddedStop, Model, Scenario
from simulator.optimize import best_stop, network_atolls, run_search, trips_within
from simulator.server import parse_scenario
from simulator.timetable import StopInsertion, StopTime, Timetable, Trip, TripShift, insert_stops

MEEDHOO, MAAMENDHOO, ADDU_HITHADHOO = "1050", "1085", "1004"


def trip(trip_id, *calls):
    return Trip(trip_id, trip_id.split("_")[0], tuple(StopTime(s, t, t) for s, t in calls))


TIMETABLE = Timetable((trip("R_0", ("A", 400), ("B", 430), ("C", 460)), trip("R_1", ("C", 900), ("B", 930), ("A", 960)),
                       trip("Q_0", ("A", 500), ("B", 520))))


def times(tt, trip_id):
    return [(s.stop_id, s.arrival) for s in tt.trip(trip_id).stop_times]


def test_insert_between_stops_moves_later_stops_by_the_detour():
    out = insert_stops(TIMETABLE, [StopInsertion("N", "R", "A", "B", 20, 20)])
    assert times(out, "R_0") == [("A", 400), ("N", 420), ("B", 445), ("C", 475)]  # 20 + 5 call + 20 - 30 = +15
    assert times(out, "R_1") == [("C", 900), ("B", 930), ("N", 950), ("A", 975)]  # same gap, other direction
    assert times(out, "Q_0") == times(TIMETABLE, "Q_0")  # other routes untouched
    assert times(TIMETABLE, "R_0")[1] == ("B", 430)  # the original is never changed


def test_insert_past_the_terminus():
    out = insert_stops(TIMETABLE, [StopInsertion("E", "R", "C", None, 10)])
    assert times(out, "R_0")[-1] == ("E", 475) and times(out, "R_1")[0] == ("E", 885)


def test_road_linked_islands_use_the_ferry_stop():
    stops = load_island_stops()
    assert stops[ADDU_HITHADHOO] == frozenset({"S_FEYDHOO"})
    assert ADDU_HITHADHOO not in load_island_stops(road_links=None)


@pytest.fixture(scope="module")
def model():
    return Model()


def test_model_covers_every_ferry_atoll(model):
    assert set(model.atolls) == {"B", "Dh", "F", "GA", "GDh", "Gn", "L", "Lh", "N", "S", "Th"}
    assert network_atolls(model, "F") == {"F", "Dh"}
    assert network_atolls(model, "GA") == {"GA", "GDh", "Gn", "S"}
    assert set(trips_within(model, model.timetable, "Dh")) == {"288_0", "288_1"}  # 280 crosses atolls
    assert "197_0" in trips_within(model, model.timetable, "GA")  # airport stops don't count


def test_dashboard_records_and_summary(model):
    d = Dashboard(model)
    payload = d.run_payload(model.baseline, [HOSPITAL])["atolls"]["Dh"]
    records, summary = payload["results"][HOSPITAL], payload["summary"][HOSPITAL]
    assert {r["category"] for r in records} == {"hospital_child", "hospital_adult", "hospital_elderly"}
    travellers = [r for r in records if r["status"] in ("success", "failed")]
    assert summary["eligible"] == sum(r["population_weight"] for r in travellers)
    assert summary["total"] == summary["eligible"] + summary["on_island"] + summary["no_data"] + summary["boards_away"]
    late = next(r for r in records if r["failure_reason"] == "late_arrival")
    assert late["last_leg"]["trip_id"] == "288_0" and late["last_leg"]["arr"] == 605  # docks 10:05
    no_return = next(r for r in records if r["failure_reason"] == "no_return" and r["census_island_id"] == MEEDHOO)
    assert no_return["evidence"]["last_workable_departure"] == 845  # 288_1 leaves Kudahuvadhoo 14:05
    run = model.run(Scenario((TripShift("288_1", 75),)))
    assert d.compare_payload(run, [HOSPITAL])["atolls"]["Dh"][HOSPITAL] == {"gained": 523, "lost": 17, "newly_served": 0}
    assert [t["trip_id"] for t in d.changed_trips(run)] == ["288_1"]


def test_added_stop_is_newly_served_not_gained(model):
    best = best_stop(model, Scenario(), MAAMENDHOO)["best"]
    assert best["ok"] and best["lost"] == 0 and best["served"] > 0
    scenario = parse_scenario({"shifts": best["shifts"], "added_stops": [{k: best[k] for k in ("island_id", "route_id", "a", "b")}]})
    run = model.run(scenario)
    c = Dashboard(model).compare_payload(run, [HOSPITAL])["atolls"]["GA"][HOSPITAL]
    assert c["newly_served"] == best["served"] and c["lost"] == 0
    with pytest.raises(ValueError, match="already has a ferry stop"):
        model.run(Scenario(added_stops=(AddedStop(MEEDHOO, "288", "DH_MEEDHOO", None),)))
    with pytest.raises(ValueError, match="no sailing between"):
        model.run(Scenario(added_stops=(AddedStop(MAAMENDHOO, "288", "DH_MEEDHOO", "GA_KONDEY"),)))


def test_find_better_times_never_costs_anyone_access(model):
    steps = []
    found = run_search(model, Scenario(), "Dh", on_progress=steps.append)
    assert found["done"] and found["access_gain"] > 0 and steps[-1]["done"] is True
    run = model.run(Scenario(tuple(TripShift(t, s) for t, s in found["shifts"].items())))
    assert model.compare_payload(run)["lost"] == 0


def test_parse_scenario_dashboard_shape():
    s = parse_scenario({"shifts": {"288_1": 75, "280_0": 0}, "added_stops": [{"island_id": "1085", "route_id": "197", "a": "GA_KOODDOO", "b": None}]})
    assert s.timetable_edits == (TripShift("288_1", 75),)  # zero shifts are dropped
    assert s.added_stops == (AddedStop("1085", "197", "GA_KOODDOO", None),)
    with pytest.raises(ValueError):
        parse_scenario({"shifts": {"288_1": True}})
