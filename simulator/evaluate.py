"""Round-trip evaluation: outward by `arrive_by`, an activity, home by `home_by`. Pure: no file I/O.

Every request gets exactly one outcome, checked in this order:
  no_data            origin or destination island has no ferry stop (reported separately, not a failure)
  on_island          origin == destination, or both islands are served by the same stop
                     (e.g. Census Hulhudhoo and Meedhoo share the land-linked Hulhumeedhoo jetty).
                     Success with zero travel, flagged so it is never read as good ferry access.
  no_route           no sailings connect home to the destination at any time that day, even
                     allowing transfers `missed_connection_tolerance_minutes` short of the minimum
  missed_connection  outward: no valid on-time journey, but one exists with a too-short transfer
                     (or the destination is reachable only with one). Return: the same, by home_by.
  arrives_late       reachable with valid transfers, but the earliest arrival is after arrive_by
  no_return          the outward trip works but there is no valid way home by home_by;
                     `same_day_return_exists` records whether any later return exists that day

Modelling rules (all `assumed`):
  - Outward: the latest departure from home that still arrives by arrive_by; ties -> fewer transfers.
  - Return: the earliest arrival home leaving at or after arrive_by + activity_minutes; ties -> fewer transfers.
  - The activity starts at arrive_by (arriving early means waiting). No time is modelled between
    the jetty and the home or facility, and leaving after the activity needs no transfer buffer.
  - Burden metrics (minutes, transfers) are only filled for completed round trips.
"""

from dataclasses import dataclass, replace
from typing import Iterable, Mapping, Sequence

from simulator.csa import Journey, Leg, earliest_arrival, latest_departure
from simulator.timetable import DAY_MINUTES, Timetable

SUCCESS, ON_ISLAND, FAILED, NO_DATA = "success", "on_island", "failed", "no_data"
NO_ROUTE, MISSED_CONNECTION, ARRIVES_LATE, NO_RETURN = "no_route", "missed_connection", "arrives_late", "no_return"
OUTWARD, RETURN = "outward", "return"
CLASSIFICATIONS = ("observed", "derived", "assumed", "demo")


@dataclass(frozen=True)
class Params:
    """Modelling parameters; see PARAM_NOTES for their labels."""
    min_transfer_minutes: int = 5
    missed_connection_tolerance_minutes: int = 60

    def __post_init__(self):
        for name in ("min_transfer_minutes", "missed_connection_tolerance_minutes"):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer, got {value!r}")


PARAM_NOTES = {
    "min_transfer_minutes": (
        "assumed", "Minimum minutes between arriving and departing when changing trips at a stop. "
                   "Staying on the same trip needs none. 5 keeps the real F.Nilandhoo chain "
                   "(278_0 arrives 07:35, 280_0 departs 07:40)."),
    "missed_connection_tolerance_minutes": (
        "assumed", "Diagnosis only: a failed journey is a missed connection if it would work with "
                   "a transfer up to this many minutes short of the minimum."),
}


def describe_params(params: Params) -> list[dict]:
    """Rows for showing the parameters and their data labels."""
    return [{"name": name, "value": getattr(params, name), "classification": label, "note": note}
            for name, (label, note) in PARAM_NOTES.items()]


@dataclass(frozen=True)
class Request:
    """A travel need. Times are minutes after midnight; arrive_by is also the activity start."""
    request_id: str
    origin_island_id: str
    destination_island_id: str
    arrive_by: int
    activity_minutes: int
    home_by: int
    purpose: str = "healthcare"
    destination_facility_id: str | None = None
    data_classification: str = "demo"

    def __post_init__(self):
        if not 0 <= self.arrive_by < DAY_MINUTES or not 0 <= self.home_by < DAY_MINUTES:
            raise ValueError(f"{self.request_id}: times must be same-day minutes")
        if self.activity_minutes <= 0:
            raise ValueError(f"{self.request_id}: activity_minutes must be positive")
        if self.arrive_by + self.activity_minutes > self.home_by:
            raise ValueError(f"{self.request_id}: the activity ends after home_by")
        if self.data_classification not in CLASSIFICATIONS:
            raise ValueError(f"{self.request_id}: data_classification must be one of {CLASSIFICATIONS}")


@dataclass(frozen=True)
class MissedTransfer:
    """A change of trips in a diagnostic journey that is shorter than the minimum."""
    stop_id: str
    from_trip: str
    to_trip: str
    arrive: int
    depart: int
    short_by_minutes: int


@dataclass(frozen=True)
class Result:
    request_id: str
    status: str  # success | on_island | failed | no_data
    failure_reason: str | None = None  # no_route | missed_connection | arrives_late | no_return
    failed_leg: str | None = None  # outward | return
    outward_legs: tuple[Leg, ...] = ()
    return_legs: tuple[Leg, ...] = ()
    depart_home: int | None = None
    arrive_destination: int | None = None
    wait_at_destination_minutes: int | None = None  # before the activity + after it, until leaving
    leave_destination: int | None = None
    arrive_home: int | None = None
    in_vehicle_minutes: int | None = None
    transfer_wait_minutes: int | None = None
    transfers: int | None = None
    time_away_minutes: int | None = None
    same_day_return_exists: bool | None = None  # set for no_return
    # The journey that explains a failure: the one with the missed connection, the late
    # arrival, or the return that arrives after home_by. Not a valid itinerary.
    diagnostic_legs: tuple[Leg, ...] = ()
    missed_transfers: tuple[MissedTransfer, ...] = ()

    @property
    def succeeded(self) -> bool:
        return self.status in (SUCCESS, ON_ISLAND)

    @property
    def outcome(self) -> str:
        """The single code: the failure reason for failures, else the status."""
        return self.failure_reason or self.status


def evaluate(timetable: Timetable, island_stops: Mapping[str, Iterable[str]],
             request: Request, params: Params = Params()) -> Result:
    """Outcome and itinerary of one round trip. `island_stops` maps Census island_id -> ferry stop_ids."""
    rid = request.request_id
    origins = frozenset(island_stops.get(request.origin_island_id, ()))
    targets = frozenset(island_stops.get(request.destination_island_id, ()))
    if not origins or not targets:
        return Result(rid, NO_DATA)
    activity_end = request.arrive_by + request.activity_minutes
    if request.origin_island_id == request.destination_island_id or origins & targets:
        return Result(rid, ON_ISLAND, depart_home=request.arrive_by, arrive_destination=request.arrive_by,
                      wait_at_destination_minutes=0, leave_destination=activity_end, arrive_home=activity_end,
                      in_vehicle_minutes=0, transfer_wait_minutes=0, transfers=0,
                      time_away_minutes=request.activity_minutes)

    strict = params.min_transfer_minutes
    relaxed = strict - params.missed_connection_tolerance_minutes
    outward = latest_departure(timetable, origins, targets, request.arrive_by, strict)
    if outward is None:
        return _outward_failure(timetable, origins, targets, request, strict, relaxed)

    back = earliest_arrival(timetable, targets, origins, activity_end, strict)
    if back is not None and back.arrive <= request.home_by:
        return Result(
            rid, SUCCESS, outward_legs=outward.legs, return_legs=back.legs,
            depart_home=outward.depart, arrive_destination=outward.arrive,
            wait_at_destination_minutes=(request.arrive_by - outward.arrive) + (back.depart - activity_end),
            leave_destination=back.depart, arrive_home=back.arrive,
            in_vehicle_minutes=outward.in_vehicle_minutes + back.in_vehicle_minutes,
            transfer_wait_minutes=outward.transfer_wait_minutes + back.transfer_wait_minutes,
            transfers=outward.transfers + back.transfers, time_away_minutes=back.arrive - outward.depart)

    got_there = dict(outward_legs=outward.legs, depart_home=outward.depart, arrive_destination=outward.arrive)
    tight = earliest_arrival(timetable, targets, origins, activity_end, relaxed)
    if tight is not None and tight.arrive <= request.home_by:
        return _failed(rid, MISSED_CONNECTION, RETURN, tight, strict, **got_there)
    return _failed(rid, NO_RETURN, RETURN, back, strict, same_day_return_exists=back is not None, **got_there)


def _outward_failure(timetable: Timetable, origins: frozenset, targets: frozenset,
                     request: Request, strict: int, relaxed: int) -> Result:
    """A missed connection is the reason only if holding it would make the whole round trip work.

    Otherwise the reason is what would still fail (late arrival or no return); the missed
    transfers are still listed.
    """
    rid = request.request_id
    tight_any = earliest_arrival(timetable, origins, targets, 0, relaxed)
    if tight_any is None:
        return _failed(rid, NO_ROUTE, OUTWARD, None, strict)
    tight_on_time = latest_departure(timetable, origins, targets, request.arrive_by, relaxed)
    if tight_on_time is None:
        late = earliest_arrival(timetable, origins, targets, 0, strict) or tight_any
        return _failed(rid, ARRIVES_LATE, OUTWARD, late, strict)
    activity_end = request.arrive_by + request.activity_minutes
    tight_back = earliest_arrival(timetable, targets, origins, activity_end, relaxed)
    if tight_back is not None and tight_back.arrive <= request.home_by:
        return _failed(rid, MISSED_CONNECTION, OUTWARD, tight_on_time, strict)
    back = earliest_arrival(timetable, targets, origins, activity_end, strict)
    return _failed(rid, NO_RETURN, RETURN, back, strict, missed_in=tight_on_time,
                   same_day_return_exists=back is not None)


def _failed(rid: str, reason: str, leg: str, diagnostic: Journey | None, min_transfer: int,
            missed_in: Journey | None = None, **fields) -> Result:
    """`missed_in` is the journey to list short transfers from, when it isn't the diagnostic one."""
    legs = diagnostic.legs if diagnostic else ()
    checked = (missed_in or diagnostic).legs if (missed_in or diagnostic) else ()
    missed = tuple(MissedTransfer(a.to_stop, a.trip_id, b.trip_id, a.arrive, b.depart,
                                  min_transfer - (b.depart - a.arrive))
                   for a, b in zip(checked, checked[1:]) if b.depart - a.arrive < min_transfer)
    return Result(rid, FAILED, reason, leg, diagnostic_legs=legs, missed_transfers=missed, **fields)


def evaluate_requests(timetable: Timetable, island_stops: Mapping[str, Iterable[str]],
                      requests: Sequence[Request], params: Params = Params()) -> list[Result]:
    """Results in request order. Requests with the same islands and times are routed once."""
    ids = [r.request_id for r in requests]
    if len(set(ids)) != len(ids):
        raise ValueError("request_ids must be unique")
    cache: dict[tuple, Result] = {}
    results = []
    for r in requests:
        key = (r.origin_island_id, r.destination_island_id, r.arrive_by, r.activity_minutes, r.home_by)
        if key not in cache:
            cache[key] = evaluate(timetable, island_stops, r, params)
        results.append(replace(cache[key], request_id=r.request_id))
    return results


def appointment_requests(origin_island_ids: Iterable[str], destination_island_ids: Iterable[str],
                         appointment_times: Iterable[int], activity_minutes: int, home_by: int, *,
                         purpose: str = "healthcare", data_classification: str = "demo",
                         id_prefix: str = "demo") -> list[Request]:
    """Every origin x destination x appointment time. IDs: '<prefix>:<origin>:<destination>:<minute>'."""
    destinations, times = list(destination_island_ids), list(appointment_times)
    return [Request(f"{id_prefix}:{o}:{d}:{t}", o, d, t, activity_minutes, home_by,
                    purpose=purpose, data_classification=data_classification)
            for o in origin_island_ids for d in destinations for t in times]


def filter_home_atolls(requests: Iterable[Request], island_atoll: Mapping[str, str],
                       atoll_codes: Iterable[str]) -> list[Request]:
    """Requests whose home island is in one of the atolls (codes compared case-insensitively)."""
    wanted = {code.lower() for code in atoll_codes}
    return [r for r in requests if island_atoll.get(r.origin_island_id, "").lower() in wanted]
