"""Sanity view: every home island in the chosen atolls to every hospital island in them.

  uv run python -m simulator.demo --atolls F Dh [--shift 280_0=+10 ...]

Requests are `demo`: appointments every 30 min 08:00-14:00, 60 min activity, home by 18:00.
"""

import argparse
import sys

from pipeline.export_web import hhmm
from simulator.diff import compare
from simulator.evaluate import (Params, appointment_requests, describe_params, evaluate_requests,
                                filter_home_atolls)
from simulator.load import load_hospitals, load_island_stops, load_islands, load_timetable
from simulator.timetable import TripShift, apply_edits

TIMES = range(8 * 60, 14 * 60 + 1, 30)
ACTIVITY, HOME_BY = 60, 18 * 60
CODES = {"success": "✓", "on_island": "=", "no_data": ".", "no_route": "R",
         "missed_connection": "M", "arrives_late": "L", "no_return": "N"}


def parse_shift(text: str) -> TripShift:
    """'280_0=+10' -> TripShift('280_0', 10)."""
    trip_id, sep, minutes = text.partition("=")
    try:
        return TripShift(trip_id.strip(), int(minutes))
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected TRIP_ID=MINUTES (e.g. 280_0=+10), got {text!r}") from None


def matrix(title: str, results, islands, hospitals, origins) -> list[str]:
    by_id = {r.request_id: r for r in results}
    lines = [title, f"  {'home -> hospital':38} " + " ".join(hhmm(t).replace(":", "") for t in TIMES)]
    for o in origins:
        for h in hospitals:
            codes = [CODES[by_id[f"demo:{o}:{h}:{t}"].outcome] for t in TIMES]
            if set(codes) == {CODES["no_data"]}:
                continue
            label = f"{islands[o]['atoll_code']}.{islands[o]['name']} -> {islands[h]['atoll_code']}.{islands[h]['name']}"
            lines.append(f"  {label:38} " + " ".join(f"{c:4}" for c in codes).rstrip())
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--atolls", nargs="+", required=True, help="home atoll codes, e.g. F Dh")
    ap.add_argument("--shift", nargs="*", type=parse_shift, default=[], metavar="TRIP=MIN")
    args = ap.parse_args(argv)

    timetable, island_stops, islands = load_timetable(), load_island_stops(), load_islands()
    wanted = {a.lower() for a in args.atolls}
    in_region = sorted((i for i, row in islands.items() if row["atoll_code"].lower() in wanted),
                       key=lambda i: (islands[i]["atoll_code"], islands[i]["name"]))
    hospitals = sorted({h["island_id"] for h in load_hospitals() if h["island_id"] in in_region},
                       key=in_region.index)
    if not hospitals:
        print(f"No hospital island linked in atolls {args.atolls}", file=sys.stderr)
        return 1
    params = Params()
    requests = filter_home_atolls(appointment_requests(in_region, hospitals, TIMES, ACTIVITY, HOME_BY),
                                  {i: row["atoll_code"] for i, row in islands.items()}, args.atolls)
    try:
        scenario_tt = apply_edits(timetable, args.shift)
    except ValueError as e:
        print(f"Invalid edit: {e}", file=sys.stderr)
        return 2

    baseline = evaluate_requests(timetable, island_stops, requests, params)
    print(f"Requests [demo]: {len(requests)} = {len(in_region)} home islands x {len(hospitals)} hospital islands "
          f"x {len(TIMES)} appointment times; {ACTIVITY} min activity; home by {hhmm(HOME_BY)}")
    print("Params: " + "; ".join(f"{p['name']}={p['value']} [{p['classification']}]" for p in describe_params(params)))
    print("Codes: " + "  ".join(f"{c} {name}" for name, c in CODES.items()) + "  (all-'.' rows hidden)")
    no_data = [f"{islands[i]['atoll_code']}.{islands[i]['name']}" for i in in_region if i not in island_stops]
    if no_data:
        print(f"No ferry stop in data ({len(no_data)}): {', '.join(no_data)}")
    print("\n".join(matrix("\nBaseline", baseline, islands, hospitals, in_region)))
    if not args.shift:
        return 0

    scenario = evaluate_requests(scenario_tt, island_stops, requests, params)
    edits = ", ".join(f"{e.trip_id} {e.shift_minutes:+d} min" for e in args.shift)
    print("\n".join(matrix(f"\nScenario ({edits})", scenario, islands, hospitals, in_region)))
    d = compare(baseline, scenario)
    print(f"\nGained {len(d.gained)}  Lost {len(d.lost)}  Unchanged {len(d.unchanged)}  "
          f"Failure reason changed {len(d.reason_changed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
