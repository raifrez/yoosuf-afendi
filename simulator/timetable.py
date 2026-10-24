"""Timetable model and scenario edits. Pure: no file I/O.

Times are integer minutes after midnight, local Indian/Maldives time, same day
only (0 <= t < 1440). A Timetable is immutable: `apply_edits` returns a new
Timetable built from copies and never changes the one it was given.
"""

from dataclasses import dataclass, field
from typing import Iterable

DAY_MINUTES = 24 * 60


@dataclass(frozen=True)
class StopTime:
    stop_id: str
    arrival: int
    departure: int


@dataclass(frozen=True)
class Trip:
    trip_id: str
    route_id: str
    stop_times: tuple[StopTime, ...]


@dataclass(frozen=True)
class Connection:
    """One hop of a trip: leave `from_stop` at `departure`, reach the next call `to_stop` at `arrival`."""
    trip_id: str
    from_stop: str
    to_stop: str
    departure: int
    arrival: int


@dataclass(frozen=True)
class TripShift:
    """Scenario edit: move every stop time of `trip_id` by `shift_minutes` (negative = earlier)."""
    trip_id: str
    shift_minutes: int


def _scan_order(c: Connection) -> tuple:
    return c.departure, c.arrival, c.trip_id


@dataclass(frozen=True)
class Timetable:
    """All trips of one operating day.

    `connections` are sorted by departure. `reverse_connections` are the same hops
    time-reversed (stops swapped, times negated) so a latest-departure query can
    run as an earliest-arrival scan.
    """
    trips: tuple[Trip, ...]
    connections: tuple[Connection, ...] = field(init=False, repr=False)
    reverse_connections: tuple[Connection, ...] = field(init=False, repr=False)

    def __post_init__(self):
        trips = tuple(self.trips)
        _validate(trips)
        hops = [Connection(t.trip_id, a.stop_id, b.stop_id, a.departure, b.arrival)
                for t in trips for a, b in zip(t.stop_times, t.stop_times[1:])]
        reverse = [Connection(c.trip_id, c.to_stop, c.from_stop, -c.arrival, -c.departure) for c in hops]
        object.__setattr__(self, "trips", trips)
        object.__setattr__(self, "connections", tuple(sorted(hops, key=_scan_order)))
        object.__setattr__(self, "reverse_connections", tuple(sorted(reverse, key=_scan_order)))

    def trip(self, trip_id: str) -> Trip:
        for t in self.trips:
            if t.trip_id == trip_id:
                return t
        raise KeyError(trip_id)


def _validate(trips: tuple[Trip, ...]) -> None:
    seen = set()
    for t in trips:
        if t.trip_id in seen:
            raise ValueError(f"Duplicate trip_id {t.trip_id!r}")
        seen.add(t.trip_id)
        if len(t.stop_times) < 2:
            raise ValueError(f"Trip {t.trip_id}: fewer than 2 stop times")
        for st in t.stop_times:
            for minute in (st.arrival, st.departure):
                if not isinstance(minute, int) or not 0 <= minute < DAY_MINUTES:
                    raise ValueError(f"Trip {t.trip_id} at {st.stop_id}: time {minute!r} is not "
                                     f"a same-day minute (0-{DAY_MINUTES - 1})")
            if st.departure < st.arrival:
                raise ValueError(f"Trip {t.trip_id} at {st.stop_id}: departs before it arrives")
        for a, b in zip(t.stop_times, t.stop_times[1:]):
            if b.arrival <= a.departure:
                raise ValueError(f"Trip {t.trip_id}: {a.stop_id} -> {b.stop_id} times not increasing")


def apply_edits(timetable: Timetable, edits: Iterable[TripShift]) -> Timetable:
    """A new Timetable with each edited trip shifted. Raises ValueError on an unknown
    trip, a trip edited twice, a non-integer shift, or a shift that crosses midnight."""
    known = {t.trip_id for t in timetable.trips}
    shifts: dict[str, int] = {}
    for e in edits:
        if e.trip_id not in known:
            raise ValueError(f"Unknown trip_id {e.trip_id!r}")
        if e.trip_id in shifts:
            raise ValueError(f"Trip {e.trip_id} is edited more than once")
        if not isinstance(e.shift_minutes, int) or isinstance(e.shift_minutes, bool):
            raise ValueError(f"Trip {e.trip_id}: shift_minutes must be an integer, got {e.shift_minutes!r}")
        shifts[e.trip_id] = e.shift_minutes

    trips = []
    for t in timetable.trips:
        s = shifts.get(t.trip_id, 0)
        if s:
            first, last = t.stop_times[0].arrival + s, t.stop_times[-1].departure + s
            if first < 0 or last >= DAY_MINUTES:
                raise ValueError(f"Shifting {t.trip_id} by {s:+d} min crosses midnight "
                                 "(same-day timetables only)")
            t = Trip(t.trip_id, t.route_id,
                     tuple(StopTime(st.stop_id, st.arrival + s, st.departure + s) for st in t.stop_times))
        trips.append(t)
    return Timetable(tuple(trips))
