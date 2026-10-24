"""School demand rules: who commutes, who boards away, and before/after school-time edits."""

import pytest

from simulator.diff import compare
from simulator.evaluate import evaluate_requests
from simulator.load import load_island_stops, load_islands, load_schools, load_timetable
from simulator.schools import (BOARDS_AWAY, DAILY_COMMUTE, HOME_ISLAND, NO_DATA, NO_SCHOOL, School,
                               SchoolParams, Session, Student, assign_students, grade_for_age,
                               school_requests, summarise)
from simulator.timetable import StopTime, Timetable, Trip

FEEALI, MAAEBOODHOO, MEEDHOO, KUDAHUVADHOO = "8", "209", "1050", "499"


def hm(text: str) -> int:
    h, m = text.split(":")
    return int(h) * 60 + int(m)


def trip(trip_id, *calls):
    return Trip(trip_id, trip_id.split("_")[0], tuple(StopTime(s, hm(t), hm(t)) for s, t in calls))


# a -> b in 20 min; c -> b in 60 min; c -> z (another atoll) in 10 min; d has a stop but no sailings.
TIMETABLE = Timetable((
    trip("T_0", ("A", "06:30"), ("B", "06:50")), trip("T_1", ("B", "13:00"), ("A", "13:20")),
    trip("U_0", ("C", "06:00"), ("B", "07:00")), trip("U_1", ("B", "13:00"), ("C", "14:00")),
    trip("W_0", ("C", "06:00"), ("Z", "06:10")), trip("X_0", ("Q", "06:00"), ("R", "06:30")),
))
STOPS = {"a": {"A"}, "b": {"B"}, "c": {"C"}, "z": {"Z"}, "d": {"D"}}
ATOLLS = {"a": "X", "b": "X", "c": "X", "d": "X", "n": "X", "z": "Y"}
SCHOOLS = [School("s_a", "A School", "a", None),  # grades not sourced -> assumed 1-10
           School("s_b", "B School", "b", frozenset(range(1, 13))),
           School("s_z", "Z School", "z", frozenset(range(1, 13)))]
STUDENTS = [Student("a16", "a", 16), Student("a10", "a", 10), Student("c17", "c", 17),
            Student("n16", "n", 16), Student("d16", "d", 16), Student("a5", "a", 5), Student("a18", "a", 18)]


def by_person(assignments):
    return {a.person_id: a for a in assignments}


def test_grade_for_age():
    assert [grade_for_age(a) for a in (5, 6, 15, 16, 17, 18)] == [None, 1, 10, 11, 12, None]


def test_categories():
    got = by_person(assign_students(TIMETABLE, STOPS, ATOLLS, STUDENTS, SCHOOLS))
    assert set(got) == {"a16", "a10", "c17", "n16", "d16"}  # ages 5 and 18 are not school age
    assert (got["a10"].category, got["a10"].school_facility_id) == (HOME_ISLAND, "s_a")
    assert (got["a16"].category, got["a16"].school_facility_id, got["a16"].one_way_minutes) == (DAILY_COMMUTE, "s_b", 20)
    # Z School is 10 min away but in another atoll; B School is 60 min.
    assert (got["c17"].category, got["c17"].school_facility_id, got["c17"].one_way_minutes) == (BOARDS_AWAY, "s_b", 60)
    assert got["n16"].category == NO_DATA and got["d16"].category == NO_SCHOOL


def test_other_atolls_and_commute_limit_are_parameters():
    anywhere = by_person(assign_students(TIMETABLE, STOPS, ATOLLS, STUDENTS, SCHOOLS, SchoolParams(home_atoll_only=False)))
    assert (anywhere["c17"].category, anywhere["c17"].school_facility_id) == (DAILY_COMMUTE, "s_z")
    strict = by_person(assign_students(TIMETABLE, STOPS, ATOLLS, STUDENTS, SCHOOLS, SchoolParams(max_school_commute_minutes=15)))
    assert strict["a16"].category == BOARDS_AWAY


def test_school_time_edit_compares_against_baseline():
    assignments = assign_students(TIMETABLE, STOPS, ATOLLS, STUDENTS, SCHOOLS)
    baseline_requests = school_requests(assignments)
    scenario_requests = school_requests(assignments, {"s_b": Session(hm("06:40"), hm("11:00"))})
    assert [r.request_id for r in baseline_requests] == [r.request_id for r in scenario_requests] == ["school:a16"]
    [base] = evaluate_requests(TIMETABLE, STOPS, baseline_requests)
    [scen] = evaluate_requests(TIMETABLE, STOPS, scenario_requests)
    assert (base.outcome, scen.outcome) == ("success", "arrives_late")  # T_0 arrives 06:50
    assert compare([base], [scen]).lost == ("school:a16",)
    summary = summarise(assignments, [base])
    assert summary["a"] == {"success": 1, HOME_ISLAND: 1} and summary["c"] == {BOARDS_AWAY: 1}


def test_session_validation():
    with pytest.raises(ValueError):
        Session(hm("12:00"), hm("07:00"))
    assignments = assign_students(TIMETABLE, STOPS, ATOLLS, STUDENTS, SCHOOLS)
    with pytest.raises(ValueError, match="after school_home_by"):
        school_requests(assignments, default_session=Session(hm("13:00"), hm("19:00")))


@pytest.fixture(scope="module")
def real():
    islands = load_islands()
    return load_timetable(), load_island_stops(), {i: r["atoll_code"] for i, r in islands.items()}, load_schools()


def test_real_feed_commutes(real):
    timetable, stops, atolls, schools = real
    students = [Student("feeali", FEEALI, 16), Student("maaeboodhoo", MAAEBOODHOO, 16), Student("meedhoo", MEEDHOO, 17)]
    got = by_person(assign_students(timetable, stops, atolls, students, schools))
    names = {s.facility_id: s.name for s in schools}
    assert (got["feeali"].category, names[got["feeali"].school_facility_id], got["feeali"].one_way_minutes) == (
        DAILY_COMMUTE, "Bilehdhoo School", 25)
    assert (got["maaeboodhoo"].category, got["maaeboodhoo"].school_island_id) == (DAILY_COMMUTE, KUDAHUVADHOO)
    assert (got["meedhoo"].category, got["meedhoo"].one_way_minutes) == (BOARDS_AWAY, 115)

    assignments = list(got.values())
    dh_aec = got["maaeboodhoo"].school_facility_id
    base = {r.request_id: r for r in evaluate_requests(timetable, stops, school_requests(assignments))}
    later = {r.request_id: r for r in evaluate_requests(
        timetable, stops, school_requests(assignments, {dh_aec: Session(hm("10:15"), hm("14:00"))}))}
    assert base["school:feeali"].outcome == "success"  # 278_0 reaches Biledhdhoo 06:55
    assert base["school:maaeboodhoo"].outcome == "arrives_late"  # 288_0 reaches Kudahuvadhoo 10:05
    assert later["school:maaeboodhoo"].outcome == "success" and later["school:feeali"].outcome == "success"
