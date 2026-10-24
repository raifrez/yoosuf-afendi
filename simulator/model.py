"""The simulation model for a region: load once, run the baseline and any scenario.

A scenario is ferry edits plus school hours. It is applied to copies: the baseline
timetable, population and needs are never changed, and every scenario is scored over
the same residents and requests as the baseline.
"""

import json
from dataclasses import dataclass, field

from pipeline.export_web import hhmm
from pipeline.stops import DATA
from simulator.destinations import FerryDistances
from simulator.evaluate import PARAM_NOTES, Params, Result, evaluate_requests
from simulator.health import CATEGORY_NOTES, HEALTH_PARAM_NOTES, HealthParams, categories_for, health_needs
from simulator.load import (load_health_facilities, load_island_stops, load_islands, load_residents,
                            load_schools, load_stop_names, load_timetable)
from simulator.schools import (DEFAULT_SESSION, SCHOOL, SCHOOL_AGES, SCHOOL_PARAM_NOTES, SchoolParams, Session,
                               Student, assign_students, school_need_id, school_needs)
from simulator.scores import Need, Score, check_totals, gains_and_losses, outcome, score
from simulator.timetable import Timetable, TripShift, apply_edits

DEMO_ATOLLS = ("F", "Dh", "GA", "GDh")
CATEGORIES = {**CATEGORY_NOTES, SCHOOL: "Ages 6-17 whose grade isn't taught on the home island: daily commute "
                                        "to the nearest school in the home atoll that teaches it."}


@dataclass(frozen=True)
class Scenario:
    timetable_edits: tuple[TripShift, ...] = ()
    default_session: Session = DEFAULT_SESSION
    school_sessions: tuple[tuple[str, Session], ...] = ()  # (facility_id, hours)

    @property
    def is_baseline(self) -> bool:
        return not self.timetable_edits and self.default_session == DEFAULT_SESSION and not self.school_sessions

    def as_dict(self) -> dict:
        return {"timetable_edits": [{"trip_id": e.trip_id, "shift_minutes": e.shift_minutes} for e in self.timetable_edits],
                "default_session": session_dict(self.default_session),
                "school_sessions": {f: session_dict(s) for f, s in self.school_sessions}}


@dataclass
class Run:
    scenario: Scenario
    timetable: Timetable
    needs: list[Need]
    results: dict[str, Result]
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
    def __init__(self, atolls=DEMO_ATOLLS, params=Params(), school_params=SchoolParams(), health_params=HealthParams()):
        self.atolls, self.params, self.school_params, self.health_params = tuple(atolls), params, school_params, health_params
        self.timetable, self.island_stops, self.islands = load_timetable(), load_island_stops(), load_islands()
        self.stop_names = load_stop_names()
        self.island_atoll = {i: r["atoll_code"] for i, r in self.islands.items()}
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

    def run(self, scenario: Scenario) -> Run:
        timetable = apply_edits(self.timetable, scenario.timetable_edits)
        needs = self.health_needs + school_needs(self.assignments, dict(scenario.school_sessions),
                                                 scenario.default_session, self.school_params)
        results = {r.request_id: r for r in evaluate_requests(
            timetable, self.island_stops, [n.request for n in needs if n.request], self.params)}
        run = Run(scenario, timetable, needs, results)
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
        return {"islands": [{"island_id": k[0], "category": k[1], **v} for k, v in sorted(by_island.items())],
                "atolls": [{"atoll": k[0], "category": k[1], **v} for k, v in sorted(by_atoll.items())],
                "gained": sum(v["gained"] for v in by_island.values()),
                "lost": sum(v["lost"] for v in by_island.values())}

    def person_needs(self, person_id: str) -> dict[str, str]:
        """category -> need_id for one resident."""
        out = {c: self.person_health[person_id, c] for c in categories_for(self.residents[person_id].age)}
        if person_id in self.person_school:
            out[SCHOOL] = school_need_id(self.person_school[person_id])
        return out

    def resident_payload(self, person_id: str, run: Run) -> dict:
        r = self.residents[person_id]
        needs = {n.need_id: n for n in run.needs}
        base_needs = {n.need_id: n for n in self.baseline.needs}
        trips = []
        for category, need_id in self.person_needs(person_id).items():
            trips.append({"category": category, "baseline": self._trip(base_needs[need_id], self.baseline),
                          "scenario": None if run.scenario.is_baseline else self._trip(needs[need_id], run)})
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
            scen = outcome(needs[need_id], run.results)
            if outcome_code and outcome_code not in (base, scen):
                continue
            rows.append({"person_id": pid, "display_name": r.display_name, "age": r.age, "baseline": base,
                         "scenario": None if run.scenario.is_baseline else scen})
            if len(rows) >= limit:
                break
        return rows
