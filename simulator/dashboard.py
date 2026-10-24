"""Payloads for the dashboard (dashboard/), in the record shapes its views render.

The engine's rules decide everything: who travels, where, when and what counts as a
failure. This module only reshapes results. One record per Need group (residents of one
island with the same category, destination, appointment time and length):

  group_id, category, census_island_id, stop_id, population_weight, status
  success, failure_reason      late_arrival | no_return | missed_connection | no_route (failed only)
  destination                  {stop_id, island_id, name}
  arrive_by, activity_end, home_by, first_dep, facility_arrival, home_arrival   (minutes)
  minutes_late, wait_before_minutes, wait_after_minutes, travel_minutes, wait_minutes, transfer_minutes
  last_leg                     {trip_id, arr}: the outward boat that docks last (late_arrival grouping)
  evidence                     missed_connection: {at, arrived, departs, gap, needed}
                               no_return: {return_ready, last_workable_departure, late_home_departure, late_home_arrival}

`status` is success | failed | on_island | no_data | no_facility | boards_away. "hospital"
combines the three hospital categories (child, adult, elderly), which partition residents by age.
"""

from collections import defaultdict

from simulator.csa import latest_departure
from simulator.health import HOSPITAL_ADULT, HOSPITAL_CHILD, HOSPITAL_ELDERLY
from simulator.model import Model, Run
from simulator.scores import outcome

HOSPITAL = "hospital"
HOSPITAL_PARTS = (HOSPITAL_CHILD, HOSPITAL_ADULT, HOSPITAL_ELDERLY)
REASONS = {"arrives_late": "late_arrival", "no_return": "no_return", "missed_connection": "missed_connection",
           "no_route": "no_route"}


def category_of(name: str) -> set[str]:
    return set(HOSPITAL_PARTS) if name == HOSPITAL else {name}


def _leg(l) -> dict:
    return {"trip_id": l.trip_id, "from": l.from_stop, "to": l.to_stop, "dep": l.depart, "arr": l.arrive}


class Dashboard:
    def __init__(self, model: Model):
        self.m = model

    def _stop(self, run: Run, island_id: str) -> str | None:
        stops = sorted(run.island_stops.get(island_id, ()))
        return stops[0] if stops else None

    def record(self, run: Run, need) -> dict:
        m, code = self.m, outcome(need, run.results)
        status = "success" if code == "success" else "failed" if code in REASONS else code
        rec = {"group_id": need.need_id, "category": need.category, "census_island_id": need.home_island_id,
               "stop_id": self._stop(run, need.home_island_id), "population_weight": need.weight,
               "status": status, "success": status == "success", "failure_reason": REASONS.get(code)}
        q = need.request
        if q is None:
            return rec
        r = run.results[need.need_id]
        dest_stop = self._stop(run, q.destination_island_id)
        rec.update({
            "destination": {"stop_id": dest_stop, "island_id": q.destination_island_id,
                            "name": m.islands[q.destination_island_id]["name"]},
            "arrive_by": q.arrive_by, "activity_end": q.arrive_by + q.activity_minutes, "home_by": q.home_by})
        if status == "success":
            rec.update({"first_dep": r.depart_home, "facility_arrival": r.arrive_destination, "home_arrival": r.arrive_home,
                        "wait_before_minutes": q.arrive_by - r.arrive_destination,
                        "wait_after_minutes": r.leave_destination - (q.arrive_by + q.activity_minutes),
                        "travel_minutes": r.in_vehicle_minutes, "transfer_minutes": r.transfer_wait_minutes,
                        "wait_minutes": r.transfer_wait_minutes + r.wait_at_destination_minutes,
                        "time_away_minutes": r.time_away_minutes,
                        "last_leg": _leg(r.outward_legs[-1]) if r.outward_legs else None})
        elif code == "arrives_late" and r.diagnostic_legs:
            last = r.diagnostic_legs[-1]
            rec.update({"facility_arrival": last.arrive, "minutes_late": last.arrive - q.arrive_by,
                        "first_dep": r.diagnostic_legs[0].depart, "last_leg": _leg(last)})
        elif code == "missed_connection" and r.missed_transfers:
            x = r.missed_transfers[0]
            rec["evidence"] = {"at": x.stop_id, "arrived": x.arrive, "departs": x.depart, "gap": x.depart - x.arrive,
                               "needed": m.params.min_transfer_minutes, "leg": r.failed_leg}
        elif code == "no_return":
            home = run.island_stops.get(need.home_island_id, ())
            dest = run.island_stops.get(q.destination_island_id, ())
            last_ok = latest_departure(run.timetable, dest, home, q.home_by, m.params.min_transfer_minutes)
            late = r.diagnostic_legs
            rec.update({"facility_arrival": r.arrive_destination, "first_dep": r.depart_home,
                        "last_leg": _leg(r.outward_legs[-1]) if r.outward_legs else None,
                        "evidence": {"return_ready": q.arrive_by + q.activity_minutes,
                                     "last_workable_departure": last_ok.depart if last_ok else None,
                                     "late_home_departure": late[0].depart if late else None,
                                     "late_home_arrival": late[-1].arrive if late else None}})
        return rec

    def summary(self, records: list[dict]) -> dict:
        travellers = [r for r in records if r["status"] in ("success", "failed")]
        ok = [r for r in travellers if r["success"]]
        eligible, success = sum(r["population_weight"] for r in travellers), sum(r["population_weight"] for r in ok)
        by_reason = defaultdict(int)
        for r in travellers:
            if not r["success"]:
                by_reason[r["failure_reason"]] += r["population_weight"]
        avg = lambda k: sum(r[k] * r["population_weight"] for r in ok) / success if success else None  # noqa: E731
        weight = lambda status: sum(r["population_weight"] for r in records if r["status"] == status)  # noqa: E731
        return {"total": sum(r["population_weight"] for r in records), "eligible": eligible, "success": success,
                "failed": eligible - success, "access_pct": success / eligible * 100 if eligible else None,
                "by_reason": dict(by_reason), "on_island": weight("on_island"),
                "no_data": weight("no_data") + weight("no_facility"), "boards_away": weight("boards_away"),
                "avg_travel_minutes": avg("travel_minutes"), "avg_wait_minutes": avg("wait_minutes"),
                "avg_transfer_minutes": avg("transfer_minutes")}

    def run_payload(self, run: Run, categories: list[str]) -> dict:
        wanted = set().union(*(category_of(c) for c in categories))
        by_atoll = defaultdict(lambda: defaultdict(list))
        for need in run.needs:
            if need.category in wanted:
                rec = self.record(run, need)
                atoll = self.m.island_atoll[need.home_island_id]
                for c in categories:
                    if need.category in category_of(c):
                        by_atoll[atoll][c].append(rec)
        return {"atolls": {a: {"summary": {c: self.summary(recs) for c, recs in cats.items()},
                               "results": {c: recs for c, recs in cats.items()}}
                           for a, cats in sorted(by_atoll.items())}}

    def compare_payload(self, run: Run, categories: list[str]) -> dict:
        c = self.m.compare_payload(run)
        out = defaultdict(lambda: defaultdict(lambda: {"gained": 0, "lost": 0, "newly_served": 0}))
        for row in c["atolls"]:
            for name in categories:
                if row["category"] in category_of(name):
                    out[row["atoll"]][name]["gained"] += row["gained"]
                    out[row["atoll"]][name]["lost"] += row["lost"]
        for row in c["newly_served"]:
            for name in categories:
                if row["category"] in category_of(name):
                    out[row["atoll"]][name]["newly_served"] += row["residents"]
        return {"atolls": {a: dict(v) for a, v in out.items()}, "gained": c["gained"], "lost": c["lost"]}

    def changed_trips(self, run: Run) -> list[dict]:
        """Trips whose calls differ from the published schedule, for the map and timetable."""
        base = {t.trip_id: t.stop_times for t in self.m.timetable.trips}
        return [{"trip_id": t.trip_id, "route_id": t.route_id,
                 "calls": [[st.stop_id, st.departure] for st in t.stop_times]}
                for t in run.timetable.trips if t.stop_times != base.get(t.trip_id)]

    def added_stops(self, run: Run) -> list[dict]:
        return [{"stop_id": a.stop_id, "island_id": a.island_id, "name": self.m.islands[a.island_id]["name"],
                 "atoll": self.m.island_atoll[a.island_id], "lat": self.m.islands[a.island_id]["lat"],
                 "lon": self.m.islands[a.island_id]["lon"], "route_id": a.route_id, "a": a.a, "b": a.b}
                for a in run.scenario.added_stops]

    def journey(self, run: Run, group_id: str) -> dict:
        """Full itinerary for one group: outward, return, and the diagnostic journey of a failure."""
        need = next(n for n in run.needs if n.need_id == group_id)
        rec = self.record(run, need)
        if need.request is None:
            return rec
        r = run.results[group_id]
        return {**rec, "legs": [_leg(l) for l in r.outward_legs], "return_legs": [_leg(l) for l in r.return_legs],
                "diagnostic_legs": [_leg(l) for l in r.diagnostic_legs],
                "missed_transfers": [{"at": x.stop_id, "from_trip": x.from_trip, "to_trip": x.to_trip,
                                      "arrived": x.arrive, "departs": x.depart, "short_by": x.short_by_minutes}
                                     for x in r.missed_transfers],
                "same_day_return_exists": r.same_day_return_exists}
