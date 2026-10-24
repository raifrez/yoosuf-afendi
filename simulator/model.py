"""The simulation model for a region: load once, run the baseline and any scenario.

A scenario is sailing shifts, added stops and school hours. It is applied to copies: the
baseline timetable, population and needs are never changed, and every scenario is scored
over the same residents and requests as the baseline. The one exception is an added stop:
its island had no ferry in the baseline (no_data), so its residents' destinations are
found on the scenario network, and they are reported as newly served, not as gains.
"""

import json
import math
import statistics
from dataclasses import dataclass, field

from pipeline.build_gtfs import haversine_km
from pipeline.export_web import hhmm
from pipeline.stops import DATA
from simulator.destinations import FerryDistances
from simulator.evaluate import PARAM_NOTES, Params, Result, evaluate_requests
from simulator.health import CATEGORY_NOTES, HEALTH_PARAM_NOTES, HealthParams, categories_for, health_needs
from simulator.load import (load_health_facilities, load_island_stops, load_islands, load_residents,
                            load_schools, load_stop_names, load_stop_points, load_timetable)
from simulator.schools import (DEFAULT_SESSION, SCHOOL, SCHOOL_AGES, SCHOOL_PARAM_NOTES, SchoolParams, Session,
                               Student, assign_students, school_need_id, school_needs)
from simulator.scores import Need, Score, check_totals, gains_and_losses, outcome, score
from simulator.timetable import StopInsertion, Timetable, TripShift, apply_edits, insert_stops

DEMO_ATOLLS = ("F", "Dh", "GA", "GDh")
DEFAULT_SPEED_KM_PER_MIN = 0.55  # ~33 km/h, when a route has no timed legs (assumed)


@dataclass(frozen=True)
class AddedStop:
    """A stop for an island that isn't on the schedule, added to every sailing of `route_id`
    between neighbouring stops `a` and `b`, or past the terminus `a` when `b` is None. Leg
    times use the route's median boat speed and straight-line distance (assumed)."""
    island_id: str
    route_id: str
    a: str
    b: str | None = None

    @property
    def stop_id(self) -> str:
        return f"ADD_{self.island_id}"
CATEGORIES = {**CATEGORY_NOTES, SCHOOL: "Ages 6-17 whose grade isn't taught on the home island: daily commute "
                                        "to the nearest school in the home atoll that teaches it."}


@dataclass(frozen=True)
class Scenario:
    timetable_edits: tuple[TripShift, ...] = ()
    default_session: Session = DEFAULT_SESSION
    school_sessions: tuple[tuple[str, Session], ...] = ()  # (facility_id, hours)
    added_stops: tuple[AddedStop, ...] = ()

    @property
    def is_baseline(self) -> bool:
        return (not self.timetable_edits and self.default_session == DEFAULT_SESSION and not self.school_sessions
                and not self.added_stops)

    def as_dict(self) -> dict:
        return {"timetable_edits": [{"trip_id": e.trip_id, "shift_minutes": e.shift_minutes} for e in self.timetable_edits],
                "default_session": session_dict(self.default_session),
                "school_sessions": {f: session_dict(s) for f, s in self.school_sessions},
                "added_stops": [{"island_id": a.island_id, "route_id": a.route_id, "a": a.a, "b": a.b}
                                for a in self.added_stops]}


@dataclass
class Run:
    scenario: Scenario
    timetable: Timetable
    needs: list[Need]
    results: dict[str, Result]
    island_stops: dict = field(default_factory=dict)
    person_health: dict = field(default_factory=dict)  # (person_id, category) -> need_id
    person_school: dict = field(default_factory=dict)  # person_id -> Assignment
    islands: dict[tuple, Score] = field(default_factory=dict)  # (island_id, category)
    atolls: dict[tuple, Score] = field(default_factory=dict)  # (atoll_code, category)


def session_dict(s: Session) -> dict:
    return {"start": hhmm(s.start), "end": hhmm(s.end)}


def labelled(notes: dict, values: dict | None = None) -> list[dict]:
    """Parameter rows with their data label, for showing assumptions."""
    return [{"name": k, "classification": label, "note": note, "value": (values or {}).get(k)}
            for k, (label, note) in notes.items()]


def score_rows(scores: dict[tuple, Score], key: str) -> list[dict]:
    return [{key: k[0], "category": k[1], **s.as_dict()} for k, s in sorted(scores.items())]


class Model:
    def __init__(self, atolls=None, params=Params(), school_params=SchoolParams(), health_params=HealthParams()):
        """`atolls` None = every atoll with a ferry stop in the data."""
        self.params, self.school_params, self.health_params = params, school_params, health_params
        self.timetable, self.island_stops, self.islands = load_timetable(), load_island_stops(), load_islands()
        self.stop_names, self.stop_points = load_stop_names(), load_stop_points()
        self.island_atoll = {i: r["atoll_code"] for i, r in self.islands.items()}
        self.atolls = tuple(atolls) if atolls else tuple(sorted({self.island_atoll[i] for i in self.island_stops}))
        wanted = {a.lower() for a in self.atolls}
        self.region = sorted((i for i, a in self.island_atoll.items() if a.lower() in wanted),
                             key=lambda i: (self.island_atoll[i], self.islands[i]["name"]))
        self.residents = {r.person_id: r for r in load_residents(self.region)}
        self.health_facilities = load_health_facilities()
        self.schools = load_schools()
        distances = FerryDistances(self.timetable, self.island_stops, params.min_transfer_minutes)
        self.health_needs, self.person_health = health_needs(
            distances, self.island_atoll, self.residents.values(), self.health_facilities, health_params)
        students = [Student(r.person_id, r.home_island_id, r.age, r.weight)
                    for r in self.residents.values() if r.age in SCHOOL_AGES]
        self.assignments = assign_students(self.timetable, self.island_stops, self.island_atoll, students,
                                           self.schools, school_params, params)
        self.person_school = {a.person_id: a for a in self.assignments}
        self.baseline = self.run(Scenario())

    def route_speed(self, route_id: str) -> float:
        """Median boat speed of a route on the baseline, km per minute."""
        speeds = [haversine_km(self.stop_points[a.stop_id], self.stop_points[b.stop_id]) / (b.arrival - a.departure)
                  for t in self.timetable.trips if t.route_id == route_id
                  for a, b in zip(t.stop_times, t.stop_times[1:]) if b.arrival > a.departure]
        return statistics.median(speeds) if speeds else DEFAULT_SPEED_KM_PER_MIN

    def network(self, scenario: Scenario) -> tuple[Timetable, dict]:
        """The scenario's timetable and island -> stops: added stops first, then sailing shifts."""
        island_stops, points, insertions = dict(self.island_stops), dict(self.stop_points), []
        for add in scenario.added_stops:
            island = self.islands.get(add.island_id)
            if island is None or island.get("lat") is None or add.island_id not in self.region:
                raise ValueError(f"can't add a stop for island {add.island_id}: not in the region or no position")
            if self.island_stops.get(add.island_id):
                raise ValueError(f"island {add.island_id} already has a ferry stop")
            points[add.stop_id] = {"lat": island["lat"], "lon": island["lon"]}
            speed = self.route_speed(add.route_id)
            leg = lambda stop: max(1, math.ceil(haversine_km(points[stop], points[add.stop_id]) / speed))  # noqa: E731
            if add.a not in points or (add.b is not None and add.b not in points):
                raise ValueError(f"unknown stop next to {add.stop_id}")
            insertions.append(StopInsertion(add.stop_id, add.route_id, add.a, add.b, leg(add.a),
                                            leg(add.b) if add.b else None))
            island_stops[add.island_id] = frozenset({add.stop_id})
        timetable = insert_stops(self.timetable, insertions) if insertions else self.timetable
        for add in scenario.added_stops:
            if not any(st.stop_id == add.stop_id for t in timetable.trips for st in t.stop_times):
                raise ValueError(f"route {add.route_id} has no sailing between {add.a} and {add.b or 'its end'}")
        return apply_edits(timetable, scenario.timetable_edits), island_stops

    def run(self, scenario: Scenario) -> Run:
        timetable, island_stops = self.network(scenario)
        health, person_health = self.health_needs, self.person_health
        assignments, person_school = self.assignments, self.person_school
        added = {a.island_id for a in scenario.added_stops}
        if added:
            distances = FerryDistances(timetable, island_stops, self.params.min_transfer_minutes)
            residents = [r for r in self.residents.values() if r.home_island_id in added]
            extra, extra_person = health_needs(distances, self.island_atoll, residents, self.health_facilities,
                                               self.health_params)
            health = [n for n in health if n.home_island_id not in added] + extra
            person_health = {**person_health, **extra_person}
            students = [Student(r.person_id, r.home_island_id, r.age, r.weight) for r in residents if r.age in SCHOOL_AGES]
            extra_assign = assign_students(timetable, island_stops, self.island_atoll, students, self.schools,
                                           self.school_params, self.params)
            assignments = [a for a in assignments if a.home_island_id not in added] + extra_assign
            person_school = {**person_school, **{a.person_id: a for a in extra_assign}}
        needs = health + school_needs(assignments, dict(scenario.school_sessions), scenario.default_session,
                                      self.school_params)
        results = {r.request_id: r for r in evaluate_requests(
            timetable, island_stops, [n.request for n in needs if n.request], self.params)}
        run = Run(scenario, timetable, needs, results, island_stops, person_health, person_school)
        run.islands = score(needs, results)
        run.atolls = score(needs, results, lambda n: (self.island_atoll[n.home_island_id], n.category))
        check_totals(needs, run.islands)
        check_totals(needs, run.atolls, lambda n: (self.island_atoll[n.home_island_id], n.category))
        return run

    # --- JSON payloads for the dashboard -------------------------------------------------

    def meta(self) -> dict:
        catalog = json.loads((DATA / "catalog.json").read_text())
        return {
            "atolls": list(self.atolls),
            "categories": [{"id": k, "note": v} for k, v in CATEGORIES.items()],
            "islands": [{"island_id": i, "name": self.islands[i]["name"], "atoll": self.island_atoll[i],
                         "population": self.islands[i]["population"], "lat": self.islands[i]["lat"],
                         "lon": self.islands[i]["lon"], "stop_ids": sorted(self.island_stops.get(i, ()))}
                        for i in self.region],
            "schools": [{"facility_id": s.facility_id, "name": s.name, "island_id": s.island_id,
                         "grades": sorted(s.grades) if s.grades else None}
                        for s in self.schools if s.island_id in self.region],
            "hospitals": [{"facility_id": f.facility_id, "name": f.name, "island_id": f.island_id,
                           "level": f"{f.level_family}{f.level_number or ''}"}
                          for f in self.health_facilities if f.facility_type == "hospital" and f.island_id in self.region],
            "default_session": session_dict(DEFAULT_SESSION),
            "parameters": (labelled(PARAM_NOTES, vars(self.params))
                           + labelled(SCHOOL_PARAM_NOTES, vars(self.school_params)) + labelled(HEALTH_PARAM_NOTES)),
            "data_labels": [
                {"name": "Ferry timetable", "classification": "observed", "note": "RTL schedules; operating days assumed daily."},
                {"name": "Stop to island links", "classification": "derived", "note": "data/export/stop_islands.csv"},
                {"name": "Residents", "classification": "derived", "note": "Synthetic population from Census 2022 and HIES 2019."},
                {"name": "Facility locations", "classification": "derived", "note": "Ministry lists linked to islands; see location_match."},
                {"name": "Results", "classification": "derived", "note": "Modelled access barriers, not counts of patients denied care or school absences."},
            ],
            "sources": [{k: s.get(k) for k in ("source_id", "publisher", "source_url", "source_as_of", "availability")}
                        for s in catalog["sources"]],
        }

    def scores_payload(self, run: Run) -> dict:
        return {"scenario": run.scenario.as_dict(), "islands": score_rows(run.islands, "island_id"),
                "atolls": score_rows(run.atolls, "atoll")}

    def compare_payload(self, run: Run) -> dict:
        base, scen = list(self.baseline.results.values()), [run.results[k] for k in self.baseline.results]
        by_island = gains_and_losses(run.needs, base, scen)
        by_atoll = gains_and_losses(run.needs, base, scen, lambda n: (self.island_atoll[n.home_island_id], n.category))
        added = {a.island_id for a in run.scenario.added_stops}
        newly = {}  # (atoll, category) -> residents of added-stop islands whose trip now works
        for n in run.needs:
            if n.home_island_id in added and outcome(n, run.results) == "success":
                key = (self.island_atoll[n.home_island_id], n.category)
                newly[key] = newly.get(key, 0) + n.weight
        return {"islands": [{"island_id": k[0], "category": k[1], **v} for k, v in sorted(by_island.items())],
                "atolls": [{"atoll": k[0], "category": k[1], **v} for k, v in sorted(by_atoll.items())],
                "newly_served": [{"atoll": k[0], "category": k[1], "residents": v} for k, v in sorted(newly.items())],
                "gained": sum(v["gained"] for v in by_island.values()),
                "lost": sum(v["lost"] for v in by_island.values())}

    def person_needs(self, person_id: str, run: Run | None = None) -> dict[str, str]:
        """category -> need_id for one resident, in `run` (default: the baseline)."""
        run = run or self.baseline
        out = {c: run.person_health[person_id, c] for c in categories_for(self.residents[person_id].age)}
        if person_id in run.person_school:
            out[SCHOOL] = school_need_id(run.person_school[person_id])
        return out

    def resident_payload(self, person_id: str, run: Run) -> dict:
        r = self.residents[person_id]
        needs = {n.need_id: n for n in run.needs}
        base_needs = {n.need_id: n for n in self.baseline.needs}
        trips = []
        scenario_ids = self.person_needs(person_id, run)
        for category, need_id in self.person_needs(person_id).items():
            trips.append({"category": category, "baseline": self._trip(base_needs[need_id], self.baseline),
                          "scenario": None if run.scenario.is_baseline else self._trip(needs[scenario_ids[category]], run)})
        school = self.person_school.get(person_id)
        return {"person_id": person_id, "display_name": r.display_name, "age": r.age,
                "home_island_id": r.home_island_id, "school_grade": school.grade if school else None,
                "trips": trips}

    def _trip(self, need: Need, run: Run) -> dict:
        out = {"outcome": outcome(need, run.results), "request": None}
        if need.request is None:
            return out
        q, res = need.request, run.results[need.need_id]
        leg = self._leg
        out["request"] = {"destination_island_id": q.destination_island_id, "facility_id": q.destination_facility_id,
                          "arrive_by": hhmm(q.arrive_by), "activity_minutes": q.activity_minutes, "home_by": hhmm(q.home_by)}
        out.update({
            "failed_leg": res.failed_leg, "same_day_return_exists": res.same_day_return_exists,
            "outward": [leg(l) for l in res.outward_legs], "return": [leg(l) for l in res.return_legs],
            "diagnostic": [leg(l) for l in res.diagnostic_legs],
            "missed_transfers": [{"stop": self.stop_names.get(m.stop_id, m.stop_id), "from_trip": m.from_trip,
                                  "to_trip": m.to_trip, "arrive": hhmm(m.arrive), "depart": hhmm(m.depart),
                                  "short_by_minutes": m.short_by_minutes} for m in res.missed_transfers],
            "in_vehicle_minutes": res.in_vehicle_minutes, "transfer_wait_minutes": res.transfer_wait_minutes,
            "wait_at_destination_minutes": res.wait_at_destination_minutes, "time_away_minutes": res.time_away_minutes,
            "transfers": res.transfers})
        return out

    def _leg(self, l) -> dict:
        return {"trip_id": l.trip_id, "from": self.stop_names.get(l.from_stop, l.from_stop),
                "to": self.stop_names.get(l.to_stop, l.to_stop), "depart": hhmm(l.depart), "arrive": hhmm(l.arrive)}

    def residents_list(self, run: Run, island_id: str, category: str, outcome_code: str | None, limit: int) -> list[dict]:
        needs = {n.need_id: n for n in run.needs}
        base_needs = {n.need_id: n for n in self.baseline.needs}
        rows = []
        for pid, r in self.residents.items():
            if r.home_island_id != island_id:
                continue
            need_id = self.person_needs(pid).get(category)
            if need_id is None:
                continue
            base = outcome(base_needs[need_id], self.baseline.results)
            scen = outcome(needs[self.person_needs(pid, run)[category]], run.results)
            if outcome_code and outcome_code not in (base, scen):
                continue
            rows.append({"person_id": pid, "display_name": r.display_name, "age": r.age, "baseline": base,
                         "scenario": None if run.scenario.is_baseline else scen})
            if len(rows) >= limit:
                break
        return rows
