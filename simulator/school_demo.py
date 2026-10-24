"""Who in the chosen atolls commutes to another island's school, and does the commute work?

  uv run python -m simulator.school_demo --atolls F Dh
      [--shift 280_0=+10 ...]                  ferry edits (scenario)
      [--session 08:00-13:00]                  new hours for every school (scenario)
      [--school-session "NAME=10:15-14:00" ...] new hours for one school (scenario)
      [--max-commute 30]                       one-way minutes a student commutes daily

The baseline is 07:05-12:05 at every school on the unedited timetable. Any edit is compared
against it, with gained and lost students kept separate. --max-commute changes who is a
commuter, so it applies to the baseline and scenario alike.
"""

import argparse
import sys
from collections import Counter

from pipeline.build_gtfs import to_minutes
from pipeline.export_web import hhmm
from simulator.demo import parse_shift
from simulator.diff import compare
from simulator.evaluate import Params, evaluate_requests
from simulator.load import load_island_stops, load_islands, load_schools, load_students, load_timetable
from simulator.schools import (BOARDS_AWAY, DAILY_COMMUTE, DEFAULT_SESSION, HOME_ISLAND, NO_DATA, NO_SCHOOL,
                               SCHOOL_PARAM_NOTES, SchoolParams, Session, assign_students, school_requests,
                               summarise)
from simulator.timetable import apply_edits

OTHER = (BOARDS_AWAY, NO_DATA, NO_SCHOOL)


def parse_session(text: str) -> Session:
    """'07:05-12:05' -> Session(425, 725)."""
    try:
        start, end = (to_minutes(t.strip() + ":00") for t in text.split("-"))
        return Session(start, end)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"expected HH:MM-HH:MM, got {text!r} ({e})") from None


def parse_school_session(text: str) -> tuple[str, Session]:
    name, sep, hours = text.rpartition("=")
    if not sep or not name.strip():
        raise argparse.ArgumentTypeError(f"expected NAME=HH:MM-HH:MM, got {text!r}")
    return name.strip(), parse_session(hours)


def island_label(islands, island_id):
    return f"{islands[island_id]['atoll_code']}.{islands[island_id]['name']}"


def commuter_lines(assignments, results, islands, schools) -> list[str]:
    outcome = {r.request_id: r.outcome for r in results}
    groups = Counter((a.home_island_id, a.school_facility_id, a.one_way_minutes, outcome[a.request_id])
                     for a in assignments if a.category == DAILY_COMMUTE for _ in range(a.weight))
    return [f"  {island_label(islands, h):18} -> {schools[f].name} ({island_label(islands, schools[f].island_id)}), "
            f"{m} min: {n} students, {o}" for (h, f, m, o), n in sorted(groups.items())]


def island_table(summary, islands, in_region) -> list[str]:
    head = f"  {'home island':18} {'students':>8} {'home':>5} {'commute ok':>10} {'commute fails':>13} " \
           f"{'boards away':>11} {'no data':>7}"
    lines = [head]
    for i in in_region:
        c = summary.get(i, Counter())
        fails = sum(n for k, n in c.items() if k not in (HOME_ISLAND, "success", "on_island", *OTHER))
        ok = c["success"] + c["on_island"]
        lines.append(f"  {island_label(islands, i):18} {sum(c.values()):8} {c[HOME_ISLAND]:5} {ok:10} {fails:13} "
                     f"{c[BOARDS_AWAY]:11} {c[NO_DATA] + c[NO_SCHOOL]:7}")
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--atolls", nargs="+", required=True, help="home atoll codes, e.g. F Dh")
    ap.add_argument("--shift", nargs="*", type=parse_shift, default=[], metavar="TRIP=MIN")
    ap.add_argument("--session", type=parse_session, metavar="HH:MM-HH:MM")
    ap.add_argument("--school-session", nargs="*", type=parse_school_session, default=[], metavar="NAME=HH:MM-HH:MM")
    ap.add_argument("--max-commute", type=int, default=SchoolParams().max_school_commute_minutes, metavar="MIN")
    args = ap.parse_args(argv)

    timetable, island_stops, islands = load_timetable(), load_island_stops(), load_islands()
    wanted = {a.lower() for a in args.atolls}
    in_region = sorted((i for i, row in islands.items() if row["atoll_code"].lower() in wanted),
                       key=lambda i: (islands[i]["atoll_code"], islands[i]["name"]))
    schools = load_schools()
    by_id = {s.facility_id: s for s in schools}
    try:
        school_params, params = SchoolParams(max_school_commute_minutes=args.max_commute), Params()
        overrides = {}
        for name, session in args.school_session:
            matches = [s for s in schools if s.name == name and s.island_id in in_region]
            if len(matches) != 1:
                raise ValueError(f"school {name!r} matches {len(matches)} schools in atolls {args.atolls}")
            overrides[matches[0].facility_id] = session
        scenario_tt = apply_edits(timetable, args.shift)
        assignments = assign_students(timetable, island_stops, {i: r['atoll_code'] for i, r in islands.items()},
                                      load_students(in_region), schools, school_params, params)
        baseline_requests = school_requests(assignments, school_params=school_params)
        scenario_requests = school_requests(assignments, overrides, args.session or DEFAULT_SESSION, school_params)
    except ValueError as e:
        print(f"Invalid input: {e}", file=sys.stderr)
        return 2

    baseline = evaluate_requests(timetable, island_stops, baseline_requests, params)
    categories = Counter()
    for a in assignments:
        categories[a.category] += a.weight
    print(f"School-age residents (6-17) in atolls {' '.join(args.atolls)}: {sum(categories.values())}  "
          + "  ".join(f"{k} {v}" for k, v in sorted(categories.items())))
    print(f"Params: max_school_commute_minutes={school_params.max_school_commute_minutes}; "
          f"school_home_by={hhmm(school_params.school_home_by)}; "
          f"baseline session {hhmm(DEFAULT_SESSION.start)}-{hhmm(DEFAULT_SESSION.end)}")
    print("Labels: " + "; ".join(f"{k} [{label}]" for k, (label, _) in SCHOOL_PARAM_NOTES.items()))
    print("\nBaseline commuters")
    print("\n".join(commuter_lines(assignments, baseline, islands, by_id) or ["  (none)"]))
    print("\n".join(island_table(summarise(assignments, baseline), islands, in_region)))
    boarding = Counter((a.home_island_id, a.school_facility_id, a.one_way_minutes)
                       for a in assignments if a.category == BOARDS_AWAY for _ in range(a.weight))
    if boarding:
        print(f"\nBoards away from home (nearest school teaching their grade is over {args.max_commute} min)")
        for (h, f, m), n in sorted(boarding.items()):
            print(f"  {island_label(islands, h):18} -> {by_id[f].name} ({island_label(islands, by_id[f].island_id)}), "
                  f"{m} min: {n} students")
    if not (args.shift or args.session or args.school_session):
        return 0

    scenario = evaluate_requests(scenario_tt, island_stops, scenario_requests, params)
    edits = [f"{e.trip_id} {e.shift_minutes:+d} min" for e in args.shift]
    if args.session:
        edits.append(f"all schools {hhmm(args.session.start)}-{hhmm(args.session.end)}")
    edits += [f"{by_id[f].name} {hhmm(s.start)}-{hhmm(s.end)}" for f, s in overrides.items()]
    print(f"\nScenario ({'; '.join(edits)}) commuters")
    print("\n".join(commuter_lines(assignments, scenario, islands, by_id) or ["  (none)"]))
    d = compare(baseline, scenario)
    print(f"\nStudents gained {len(d.gained)}  lost {len(d.lost)}  unchanged {len(d.unchanged)}  "
          f"failure reason changed {len(d.reason_changed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
