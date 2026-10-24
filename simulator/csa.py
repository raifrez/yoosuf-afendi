"""Round-based connection scan (CSA). Pure: no file I/O.

Round k finds the best journeys that board at most k trips. Boarding in round k
only uses arrivals settled in round k-1, so:
  - the first round that reaches the best time gives the fewest-transfer journey;
  - the scan stays correct for any transfer allowance, including the negative one
    used to diagnose missed connections.
Staying on the same trip needs no transfer; changing trips at a stop needs
`transfer_minutes` between arriving and departing. Boarding at the start needs none.

A latest-departure query is the same scan over the time-reversed connections.
"""

from dataclasses import dataclass
from typing import Collection, Sequence

from simulator.timetable import Connection, Timetable

NEVER = 10**9  # an arrival or ready time later than any real one


@dataclass(frozen=True)
class Leg:
    trip_id: str
    from_stop: str
    to_stop: str
    depart: int
    arrive: int


@dataclass(frozen=True)
class Journey:
    legs: tuple[Leg, ...]

    @property
    def depart(self) -> int:
        return self.legs[0].depart

    @property
    def arrive(self) -> int:
        return self.legs[-1].arrive

    @property
    def transfers(self) -> int:
        return len(self.legs) - 1

    @property
    def in_vehicle_minutes(self) -> int:
        return sum(leg.arrive - leg.depart for leg in self.legs)

    @property
    def transfer_wait_minutes(self) -> int:
        return sum(b.depart - a.arrive for a, b in zip(self.legs, self.legs[1:]))


def earliest_arrival(timetable: Timetable, origins: Collection[str], targets: Collection[str],
                     depart_at: int, transfer_minutes: int) -> Journey | None:
    """Earliest arrival at any target stop, leaving an origin stop at or after `depart_at`.
    Ties go to the journey with fewer transfers. None if no target can be reached."""
    origins, targets = _endpoints(origins, targets)
    conns = timetable.connections
    pairs = _scan(conns, origins, targets, depart_at, transfer_minutes)
    if pairs is None:
        return None
    return Journey(tuple(Leg(conns[b].trip_id, conns[b].from_stop, conns[a].to_stop,
                             conns[b].departure, conns[a].arrival) for b, a in pairs))


def latest_departure(timetable: Timetable, origins: Collection[str], targets: Collection[str],
                     arrive_by: int, transfer_minutes: int) -> Journey | None:
    """Latest departure from an origin stop that still reaches a target stop by `arrive_by`.
    Ties go to the journey with fewer transfers. None if no such journey exists."""
    origins, targets = _endpoints(origins, targets)
    conns = timetable.reverse_connections
    pairs = _scan(conns, targets, origins, -arrive_by, transfer_minutes)
    if pairs is None:
        return None
    # A reversed leg boards at the original leg's last stop and alights at its first.
    return Journey(tuple(Leg(conns[b].trip_id, conns[a].to_stop, conns[b].from_stop,
                             -conns[a].arrival, -conns[b].departure) for b, a in reversed(pairs)))


def _endpoints(origins: Collection[str], targets: Collection[str]) -> tuple[frozenset[str], frozenset[str]]:
    origins, targets = frozenset(origins), frozenset(targets)
    if not origins or not targets:
        raise ValueError("origins and targets must each have at least one stop")
    if origins & targets:
        raise ValueError(f"origin and target share stop(s) {sorted(origins & targets)}")
    return origins, targets


def _scan(conns: Sequence[Connection], sources: frozenset[str], sinks: frozenset[str],
          start: int, transfer: int) -> list[tuple[int, int]] | None:
    """Fewest-trip journey with the earliest arrival at a sink, as (board, alight)
    connection-index pairs in travel order. None if no sink is reachable."""
    ready = {s: start for s in sources}  # earliest time a traveller can board at a stop
    arrival: dict[str, int] = {}  # earliest arrival at a stop so far (never at a source)
    parents: list[dict] = [{}]  # parents[r][stop] = (round, board, alight), as of round r
    # Every round improves at least one stop's arrival, and each improvement uses a
    # different connection, so this bound is never the reason the scan stops.
    for r in range(1, len(conns) + 2):
        boarded: dict[str, int] = {}
        current = dict(parents[-1])
        improved = []
        for i, c in enumerate(conns):
            b = boarded.get(c.trip_id)
            if b is None:
                if ready.get(c.from_stop, NEVER) > c.departure:
                    continue
                boarded[c.trip_id] = b = i
            if c.to_stop not in sources and c.arrival < arrival.get(c.to_stop, NEVER):
                arrival[c.to_stop] = c.arrival
                current[c.to_stop] = (r, b, i)
                improved.append(c.to_stop)
        if not improved:
            break
        parents.append(current)
        ready = {**ready, **{s: min(ready.get(s, NEVER), arrival[s] + transfer) for s in improved}}

    def best(r: int) -> tuple[int, str] | None:
        reached = [(conns[parents[r][s][2]].arrival, s) for s in sinks if s in parents[r]]
        return min(reached) if reached else None

    final = best(len(parents) - 1)
    if final is None:
        return None
    k = next(r for r in range(1, len(parents)) if (b := best(r)) and b[0] == final[0])
    stop, pairs = best(k)[1], []
    while stop not in sources:
        r, b, a = parents[k][stop]
        pairs.append((b, a))
        stop, k = conns[b].from_stop, r - 1
    return pairs[::-1]
