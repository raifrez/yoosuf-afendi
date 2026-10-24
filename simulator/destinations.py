"""Nearest facility by ferry, measured on the baseline timetable. Pure: no file I/O.

"Nearest" is the shortest one-way ferry time (first boarding to arrival, valid transfers) on
any sailing that day: a measure of distance, not of whether a given appointment time fits.
It is always measured on the baseline, so scenarios never change who goes where.
"""

from typing import Iterable, Mapping, Sequence, TypeVar

from simulator.csa import earliest_arrival
from simulator.timetable import Timetable

F = TypeVar("F")


def shortest_trip_minutes(timetable: Timetable, origins: Iterable[str], targets: Iterable[str],
                          transfer_minutes: int) -> int | None:
    """Shortest one-way ferry time, first boarding to arrival, over every departure of the day."""
    origins, targets = frozenset(origins), frozenset(targets)
    if origins & targets:
        return 0
    best = None
    for t in sorted({c.departure for c in timetable.connections if c.from_stop in origins}):
        journey = earliest_arrival(timetable, origins, targets, t, transfer_minutes)
        if journey is not None and (best is None or journey.arrive - journey.depart < best):
            best = journey.arrive - journey.depart
    return best


class FerryDistances:
    """Cached shortest ferry times between Census islands on one (baseline) timetable."""

    def __init__(self, baseline: Timetable, island_stops: Mapping[str, Iterable[str]], transfer_minutes: int):
        self.baseline, self.island_stops, self.transfer_minutes = baseline, island_stops, transfer_minutes
        self._cache: dict[tuple[str, str], int | None] = {}

    def has_stop(self, island_id: str) -> bool:
        return bool(self.island_stops.get(island_id))

    def minutes(self, home: str, island: str) -> int | None:
        if home == island:
            return 0
        if (home, island) not in self._cache:
            self._cache[home, island] = shortest_trip_minutes(
                self.baseline, self.island_stops.get(home, ()), self.island_stops.get(island, ()), self.transfer_minutes)
        return self._cache[home, island]

    def nearest(self, home: str, facilities: Sequence[F], island_of, key) -> tuple[int, F] | None:
        """(minutes, facility) for the facility on the island nearest `home` by ferry, ties broken by
        `key(facility)`; facilities on the home island count as 0 minutes. None if none is reachable."""
        reachable = sorted(((m, key(f), f) for f in facilities
                            if (m := self.minutes(home, island_of(f))) is not None), key=lambda x: x[:2])
        return (reachable[0][0], reachable[0][2]) if reachable else None
