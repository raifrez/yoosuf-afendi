"""Simulator edge cases on tiny hand-made timetables."""

import pytest

from simulator.csa import earliest_arrival, latest_departure
from simulator.diff import compare
from simulator.evaluate import Params, Request, evaluate, evaluate_requests
from simulator.timetable import StopTime, Timetable, Trip, TripShift, apply_edits

ISLAND_STOPS = {"h": {"H"}, "m": {"M"}, "d": {"D"}}


def trip(trip_id, *calls):
    """trip('T', ('H', 480), ('M', 500)): one time per stop, as in the source data."""
    return Trip(trip_id, trip_id.split("_")[0], tuple(StopTime(s, t, t) for s, t in calls))


# H -> M on T, M -> D on U leaving 2 min after T arrives (too short), back D -> M -> H on V.
TIMETABLE = Timetable((
    trip("T_0", ("H", 480), ("M", 500)),
    trip("U_0", ("M", 502), ("D", 520)),
    trip("V_0", ("D", 720), ("M", 740), ("H", 760)),
))


def test_shift_produces_separate_gain_and_loss():
    requests = [Request("from_h", "h", "d", 540, 60, 1080),   # needs T -> U: missed by 3 min
                Request("from_m", "m", "d", 522, 60, 1080)]   # U alone, arrives 08:40 by 08:42
    baseline = evaluate_requests(TIMETABLE, ISLAND_STOPS, requests)
    assert [r.outcome for r in baseline] == ["missed_connection", "success"]
    scenario = evaluate_requests(apply_edits(TIMETABLE, [TripShift("U_0", 5)]), ISLAND_STOPS, requests)
    assert [r.outcome for r in scenario] == ["success", "arrives_late"]
    d = compare(baseline, scenario)
    assert (d.gained, d.lost, d.unchanged) == (("from_h",), ("from_m",), ())


def test_staying_on_board_is_not_a_transfer():
    # V passes M with zero dwell; riding through must not need min_transfer_minutes.
    j = earliest_arrival(TIMETABLE, {"D"}, {"H"}, 700, transfer_minutes=5)
    assert [leg.trip_id for leg in j.legs] == ["V_0"] and j.transfers == 0


def test_latest_departure_ties_go_to_fewer_transfers():
    tt = Timetable((trip("A_0", ("H", 480), ("M", 490)), trip("B_0", ("M", 500), ("D", 530)),
                    trip("C_0", ("H", 480), ("M", 495), ("D", 530))))
    j = latest_departure(tt, {"H"}, {"D"}, 540, transfer_minutes=5)
    assert [leg.trip_id for leg in j.legs] == ["C_0"]


def test_return_missed_connection_and_no_return_with_later_boat():
    tt = Timetable((trip("T_0", ("H", 480), ("D", 500)),
                    trip("R_0", ("D", 600), ("M", 620)), trip("S_0", ("M", 622), ("H", 640)),
                    trip("L_0", ("D", 1100), ("H", 1120))))
    stops = {"h": {"H"}, "d": {"D"}}
    missed = evaluate(tt, stops, Request("x", "h", "d", 510, 60, 1080), Params())
    assert (missed.failure_reason, missed.failed_leg) == ("missed_connection", "return")
    no_ret = evaluate(tt, stops, Request("y", "h", "d", 510, 120, 1080), Params())
    assert no_ret.failure_reason == "no_return" and no_ret.same_day_return_exists is True
    assert no_ret.diagnostic_legs[-1].arrive == 1120


def test_two_islands_on_one_stop_are_on_island():
    r = evaluate(TIMETABLE, {"a": {"H"}, "b": {"H"}}, Request("x", "a", "b", 540, 60, 1080), Params())
    assert r.outcome == "on_island"


@pytest.mark.parametrize("edits", [[TripShift("T_0", 10), TripShift("T_0", 5)], [TripShift("T_0", 1.5)]])
def test_bad_edit_lists_raise(edits):
    with pytest.raises(ValueError):
        apply_edits(TIMETABLE, edits)
