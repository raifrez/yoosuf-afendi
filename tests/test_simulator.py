"""Simulator checks against the real ferry feed (data/gtfs, data/export/stop_islands.csv)."""

import pytest

from simulator.diff import compare
from simulator.evaluate import Params, Request, appointment_requests, evaluate, evaluate_requests
from simulator.load import load_island_stops, load_islands, load_timetable
from simulator.timetable import TripShift, apply_edits

FEEALI, NILANDHOO, MEEDHOO, KUDAHUVADHOO = "8", "1158", "1050", "499"
GDH_THINADHOO, GA_MAAMENDHOO = "717", "1085"  # Maamendhoo: no ferry stop in the data


def hm(text: str) -> int:
    h, m = text.split(":")
    return int(h) * 60 + int(m)


@pytest.fixture(scope="module")
def feed():
    return load_timetable(), load_island_stops()


def run(feed, origin, destination, arrive_by, activity=60, home_by="18:00", timetable=None):
    tt, island_stops = feed
    request = Request("r", origin, destination, hm(arrive_by), activity, hm(home_by))
    return evaluate(timetable or tt, island_stops, request, Params())


def trips(legs):
    return [leg.trip_id for leg in legs]


def test_feasible_round_trip(feed):
    r = run(feed, FEEALI, NILANDHOO, "09:00")
    assert (r.status, r.failure_reason) == ("success", None)
    assert trips(r.outward_legs) == ["278_0"] and trips(r.return_legs) == ["278_1"]
    assert (r.depart_home, r.arrive_destination, r.leave_destination, r.arrive_home) == (
        hm("06:30"), hm("07:35"), hm("16:35"), hm("17:40"))
    assert r.transfers == 0 and r.in_vehicle_minutes == 65 + 65
    assert r.wait_at_destination_minutes == (hm("09:00") - hm("07:35")) + (hm("16:35") - hm("10:00"))
    assert r.time_away_minutes == hm("17:40") - hm("06:30")


def test_chained_connection_baseline_then_missed_after_shift(feed):
    # Baseline: 278_0 -> Nilandhoo 07:35, 280_0 07:40 -> Meedhoo 08:05, 288_0 08:10 -> Kudahuvadhoo 10:05.
    base = run(feed, FEEALI, KUDAHUVADHOO, "10:30")
    assert base.status == "success"
    assert trips(base.outward_legs) == ["278_0", "280_0", "288_0"] and base.transfers == 4
    assert trips(base.return_legs) == ["288_1", "280_1", "278_1"] and base.arrive_home == hm("17:40")
    # 280_0 leaves Nilandhoo 07:30, before 278_0 arrives at 07:35.
    shifted = apply_edits(feed[0], [TripShift("280_0", -10)])
    r = run(feed, FEEALI, KUDAHUVADHOO, "10:30", timetable=shifted)
    assert (r.status, r.failure_reason, r.failed_leg) == ("failed", "missed_connection", "outward")
    [missed] = r.missed_transfers
    assert (missed.stop_id, missed.from_trip, missed.to_trip, missed.short_by_minutes) == (
        "F_NILANDHOO", "278_0", "280_0", 10)


def test_missed_connection_only_when_holding_it_would_work(feed):
    shifted = apply_edits(feed[0], [TripShift("280_0", -10)])
    # Holding the connection still arrives 10:05, after an 08:00 appointment.
    late = run(feed, FEEALI, KUDAHUVADHOO, "08:00", timetable=shifted)
    assert (late.failure_reason, late.failed_leg) == ("arrives_late", "outward")
    assert [m.stop_id for m in late.missed_transfers] == ["F_NILANDHOO"]
    # Holding it gets there, but a 13:30 + 60 min visit ends after the last boat (14:05).
    stranded = run(feed, FEEALI, KUDAHUVADHOO, "13:30", timetable=shifted)
    assert (stranded.failure_reason, stranded.failed_leg) == ("no_return", "return")
    assert stranded.same_day_return_exists is False
    assert [m.stop_id for m in stranded.missed_transfers] == ["F_NILANDHOO"]
    # Neither changes reason against the baseline.
    assert run(feed, FEEALI, KUDAHUVADHOO, "08:00").failure_reason == "arrives_late"
    assert run(feed, FEEALI, KUDAHUVADHOO, "13:30").failure_reason == "no_return"


def test_arrives_late(feed):
    r = run(feed, MEEDHOO, KUDAHUVADHOO, "09:00")
    assert (r.status, r.failure_reason) == ("failed", "arrives_late")
    assert r.diagnostic_legs[-1].arrive == hm("10:05")


def test_no_return_after_last_departure(feed):
    r = run(feed, MEEDHOO, KUDAHUVADHOO, "10:30", activity=240)  # ends 14:30; last boat left 14:05
    assert (r.status, r.failure_reason, r.failed_leg) == ("failed", "no_return", "return")
    assert r.same_day_return_exists is False
    assert trips(r.outward_legs) == ["288_0"] and r.arrive_destination == hm("10:05")


def test_no_data_on_island_and_no_route(feed):
    assert run(feed, GA_MAAMENDHOO, NILANDHOO, "09:00").outcome == "no_data"
    assert run(feed, FEEALI, GA_MAAMENDHOO, "09:00").outcome == "no_data"
    on = run(feed, NILANDHOO, NILANDHOO, "09:00")
    assert on.outcome == "on_island" and on.succeeded and on.time_away_minutes == 60
    assert run(feed, FEEALI, GDH_THINADHOO, "09:00").outcome == "no_route"


def test_scenario_never_mutates_baseline(feed):
    tt, island_stops = feed
    requests = appointment_requests([FEEALI, MEEDHOO], [NILANDHOO, KUDAHUVADHOO], range(480, 841, 30), 60, 1080)
    before_trips = tt.trips
    baseline = evaluate_requests(tt, island_stops, requests)
    scenario_tt = apply_edits(tt, [TripShift("280_0", 10), TripShift("288_1", -30)])
    scenario = evaluate_requests(scenario_tt, island_stops, requests)
    assert tt.trips == before_trips and tt.trip("280_0").stop_times[0].departure == hm("07:40")
    assert scenario_tt.trip("280_0").stop_times[0].departure == hm("07:50")
    assert evaluate_requests(tt, island_stops, requests) == baseline
    assert scenario != baseline


@pytest.mark.parametrize("shift, untouched", [("280_0", ("GA", "GDh")), ("193_0", ("F", "Dh"))])
def test_edit_in_one_region_leaves_the_other_identical(feed, shift, untouched):
    tt, island_stops = feed
    islands = load_islands()
    region = ("F", "Dh", "GA", "GDh")
    served = [i for i, row in islands.items() if row["atoll_code"] in region and i in island_stops]
    homes = [i for i in served if islands[i]["atoll_code"] in untouched]
    requests = appointment_requests(homes, served, range(480, 841, 60), 60, 1080)
    scenario_tt = apply_edits(tt, [TripShift(shift, 20)])
    baseline = evaluate_requests(tt, island_stops, requests)
    assert evaluate_requests(scenario_tt, island_stops, requests) == baseline
    assert any(r.succeeded for r in baseline if r.outcome != "on_island")
    d = compare(baseline, evaluate_requests(scenario_tt, island_stops, requests))
    assert (d.gained, d.lost, d.reason_changed) == ((), (), ())


@pytest.mark.parametrize("edit, message", [
    (TripShift("999_9", 10), "Unknown trip_id"),
    (TripShift("278_0", -400), "crosses midnight"),   # 06:30 - 6h40
    (TripShift("234_1", 400), "crosses midnight"),    # last call 18:00 + 6h40
])
def test_invalid_edits_raise(feed, edit, message):
    with pytest.raises(ValueError, match=message):
        apply_edits(feed[0], [edit])
