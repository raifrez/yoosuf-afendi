"""Find better times: a coordinate search over sailing shifts inside one atoll.

Objective, in order: (1) more residents with a working round trip (every category with a
ferry trip), (2) fewer residents with a long wait before the appointment or a long day,
(3) less total waiting, (4) the smallest total change to the timetable. Hard constraint:
nobody who has a working trip at the start loses it. It doesn't check boats, crews,
harbours or cost.

Only residents in the atoll's connected ferry network are evaluated: no sailing links them
to anyone else, so nobody else's trip can change.
"""

from dataclasses import dataclass, replace
from typing import Callable, Iterator

from simulator.evaluate import evaluate_requests
from simulator.model import Model, Scenario
from simulator.timetable import TripShift, apply_edits

LONG_WAIT, LONG_DAY = 120, 10 * 60


@dataclass(frozen=True)
class SearchOptions:
    step: int = 15
    max_shift: int = 180
    max_passes: int = 3
    long_wait: int = LONG_WAIT
    long_day: int = LONG_DAY


def network_atolls(model: Model, atoll: str) -> set[str]:
    """Atolls joined to `atoll` by sailings, directly or through others."""
    stop_atoll = {s: model.island_atoll[i] for i, stops in model.island_stops.items() for s in stops}
    links = [{stop_atoll[st.stop_id] for st in t.stop_times if st.stop_id in stop_atoll} for t in model.timetable.trips]
    found, grew = {atoll}, True
    while grew:
        grew = False
        for atolls in links:
            if atolls & found and not atolls <= found:
                found |= atolls
                grew = True
    return found


def trips_within(model: Model, timetable, atoll: str) -> list[str]:
    """Sailings whose every stop is in the atoll (as the dashboard's candidates)."""
    stop_atoll = {s: model.island_atoll[i] for i, stops in model.island_stops.items() for s in stops}
    added = {f"ADD_{i}": model.island_atoll[i] for i in model.islands}
    out = []
    for t in timetable.trips:
        # Stops on no Census island (airports) don't decide which atoll a sailing is in.
        atolls = {stop_atoll.get(st.stop_id) or added.get(st.stop_id) for st in t.stop_times} - {None}
        if atolls == {atoll}:
            out.append(t.trip_id)
    return sorted(out, key=lambda tid: timetable.trip(tid).stop_times[0].departure)


def search(model: Model, scenario: Scenario, atoll: str, opts: SearchOptions = SearchOptions(),
           candidates: list[str] | None = None) -> Iterator[dict]:
    """Yields progress after each candidate sailing ({pass, trip_id, evaluated, shifts});
    the final item has done=True and the best shifts (merged into the scenario's own)."""
    base_tt, island_stops = model.network(replace(scenario, timetable_edits=()))
    start = model.run(replace(scenario, timetable_edits=()))
    component = network_atolls(model, atoll)
    needs = [n for n in start.needs if n.request is not None and model.island_atoll[n.home_island_id] in component]
    requests = [n.request for n in needs]
    weight = {n.need_id: n.weight for n in needs}
    had_access = {n.need_id for n in needs if start.results[n.need_id].succeeded}
    fixed = {e.trip_id: e.shift_minutes for e in scenario.timetable_edits}
    candidates = candidates if candidates is not None else trips_within(model, base_tt, atoll)
    evaluated = 0

    def score(shifts: dict[str, int]):
        nonlocal evaluated
        evaluated += 1
        edits = [TripShift(t, s) for t, s in {**fixed, **shifts}.items() if s]
        try:
            tt = apply_edits(base_tt, edits)
        except ValueError:
            return None
        results = evaluate_requests(tt, island_stops, requests, model.params)
        ok = [r for r in results if r.succeeded]
        if len(had_access - {r.request_id for r in ok}):
            return None
        by_id = {n.need_id: n.request for n in needs}
        long = sum(weight[r.request_id] for r in ok if r.status == "success" and (
            by_id[r.request_id].arrive_by - r.arrive_destination >= opts.long_wait or r.time_away_minutes >= opts.long_day))
        wait = sum(weight[r.request_id] * (r.transfer_wait_minutes + r.wait_at_destination_minutes)
                   for r in ok if r.status == "success")
        moved = sum(abs(s) for s in shifts.values())
        return (-sum(weight[r.request_id] for r in ok), long, wait, moved)

    shifts: dict[str, int] = {}
    best = score(shifts)
    for p in range(opts.max_passes):
        improved = False
        for trip_id in candidates:
            current = shifts.get(trip_id, 0)
            pick, pick_score = current, best
            for s in range(-opts.max_shift, opts.max_shift + 1, opts.step):
                if s == current:
                    continue
                trial = {**shifts, trip_id: s}
                if not s:
                    del trial[trip_id]
                sc = score(trial)
                if sc is not None and (pick_score is None or sc < pick_score):
                    pick, pick_score = s, sc
            if pick != current:
                shifts = {**shifts, trip_id: pick}
                if not pick:
                    del shifts[trip_id]
                best, improved = pick_score, True
            yield {"done": False, "pass": p, "trip_id": trip_id, "evaluated": evaluated, "shifts": dict(shifts)}
        if not improved:
            break
    merged = {**fixed, **shifts}
    yield {"done": True, "evaluated": evaluated, "shifts": {t: s for t, s in merged.items() if s},
           "access_gain": (-best[0] - sum(weight[i] for i in had_access)) if best else 0}


def run_search(model: Model, scenario: Scenario, atoll: str, opts: SearchOptions = SearchOptions(),
               on_progress: Callable[[dict], None] | None = None, candidates: list[str] | None = None) -> dict:
    last = None
    for step in search(model, scenario, atoll, opts, candidates):
        last = step
        if on_progress:
            on_progress(step)
    return last


def best_stop(model: Model, scenario: Scenario, island_id: str, on_progress: Callable[[dict], None] | None = None) -> dict:
    """Add a stop: try every gap and both ends of every route inside the island's atoll, keep the
    placement that gives the island's residents the most working hospital trips, then costs
    nobody access, then delays later stops least. If none works on its own, retry the four most
    direct placements while also searching that route's sailing times (nobody may lose access)."""
    from simulator.dashboard import HOSPITAL_PARTS
    from simulator.model import AddedStop
    atoll = model.island_atoll[island_id]
    current = model.run(scenario)
    had = {k for k, r in current.results.items() if r.succeeded}
    base_tt, _ = model.network(replace(scenario, timetable_edits=()))
    routes = sorted({base_tt.trip(t).route_id for t in trips_within(model, base_tt, atoll)})
    cands = []
    for route in routes:
        longest = max((t.stop_times for t in base_tt.trips if t.route_id == route), key=len)
        stops = [st.stop_id for st in longest]
        cands += [(route, a, b) for a, b in zip(stops, stops[1:])] + [(route, stops[0], None), (route, stops[-1], None)]

    def trial(route, a, b, extra_shifts=None):
        add = AddedStop(island_id, route, a, b)
        sc = replace(scenario, added_stops=scenario.added_stops + (add,),
                     timetable_edits=extra_shifts if extra_shifts is not None else scenario.timetable_edits)
        try:
            run = model.run(sc)
        except ValueError:
            return None
        served = sum(n.weight for n in run.needs if n.home_island_id == island_id and n.category in HOSPITAL_PARTS
                     and n.request is not None and run.results[n.need_id].succeeded)
        lost = sum(n.weight for n in run.needs if n.need_id in had and not run.results[n.need_id].succeeded)
        base = {t.trip_id: t.stop_times for t in model.network(replace(sc, added_stops=scenario.added_stops))[0].trips}
        delay = max([0] + [t.stop_times[-1].departure - base[t.trip_id][-1].departure for t in run.timetable.trips
                           if t.route_id == route and t.trip_id in base])
        return {"island_id": island_id, "route_id": route, "a": a, "b": b, "served": served, "lost": lost,
                "delay_minutes": delay, "ok": served > 0 and lost == 0,
                "shifts": {e.trip_id: e.shift_minutes for e in sc.timetable_edits}}

    tried = []
    for i, (route, a, b) in enumerate(cands):
        r = trial(route, a, b)
        if r:
            tried.append(r)
        if on_progress:
            on_progress({"done": False, "tried": i + 1, "of": len(cands), "route_id": route})
    if not tried:
        return {"done": True, "best": None, "reason": "no route in the atoll can call at this island"}
    best = min(tried, key=lambda r: (-r["served"], r["lost"], r["delay_minutes"]))
    if not best["ok"]:
        for r in sorted(tried, key=lambda r: r["delay_minutes"])[:4]:
            sc = replace(scenario, added_stops=scenario.added_stops + (AddedStop(island_id, r["route_id"], r["a"], r["b"]),))
            tt, _ = model.network(replace(sc, timetable_edits=()))
            found = run_search(model, sc, atoll, SearchOptions(max_passes=2),
                               candidates=[t.trip_id for t in tt.trips if t.route_id == r["route_id"]],
                               on_progress=on_progress and (lambda s: on_progress({**s, "route_id": r["route_id"]})))
            again = trial(r["route_id"], r["a"], r["b"], tuple(TripShift(t, s) for t, s in found["shifts"].items()))
            if again and again["ok"]:
                best = again
                break
    return {"done": True, "best": best}
