"""Success rates per island x traveller category, from simulator results. Pure: no file I/O.

A Need is one group of residents with the same travel need: either a ferry round trip
(`request`) or an outcome that needs no trip (`label`). Every resident is in exactly one
Need per category, so weighted totals add up to the residents in that category.

Per group (island x category, or atoll x category):
  total        residents in the category
  no_data      the data can't answer: no ferry stop, or no facility of the level on the network
  on_island    the facility is on the home island: no ferry needed (shown, not scored)
  boards_away  schools only: too far for a daily commute
  travellers   total - no_data - on_island - boards_away: residents who need a ferry trip
  success      travellers whose round trip works; success_rate = success / travellers
               (None when there are no travellers: show "on island" or "no data", never 0)
  failures     travellers by failure reason
  burden       weighted medians over successful trips: minutes on board, waiting, away from home

Atoll rates are computed over the atoll's residents, never averaged across islands.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Sequence

from simulator.diff import compare
from simulator.evaluate import FAILED, NO_DATA, ON_ISLAND, SUCCESS, Request, Result

NO_FACILITY, BOARDS_AWAY = "no_facility", "boards_away"
NO_DATA_LABELS = (NO_DATA, NO_FACILITY)


@dataclass(frozen=True)
class Need:
    need_id: str
    category: str
    home_island_id: str
    weight: int
    request: Request | None = None
    label: str | None = None  # without a trip: on_island | no_data | no_facility | boards_away

    def __post_init__(self):
        if (self.request is None) == (self.label is None):
            raise ValueError(f"{self.need_id}: a need has either a request or a label")
        if self.request is not None and self.request.request_id != self.need_id:
            raise ValueError(f"{self.need_id}: request_id must equal need_id")


@dataclass
class Score:
    total: int = 0
    no_data: int = 0
    on_island: int = 0
    boards_away: int = 0
    success: int = 0
    failures: Counter = field(default_factory=Counter)
    _burden: dict = field(default_factory=lambda: defaultdict(list), repr=False)

    @property
    def travellers(self) -> int:
        return self.success + sum(self.failures.values())

    @property
    def success_rate(self) -> float | None:
        return self.success / self.travellers if self.travellers else None

    def burden(self) -> dict[str, float | None]:
        return {name: weighted_median(values) for name, values in
                (("in_vehicle_minutes", self._burden["in_vehicle"]), ("waiting_minutes", self._burden["waiting"]),
                 ("time_away_minutes", self._burden["away"]))}

    def as_dict(self) -> dict:
        return {"total": self.total, "no_data": self.no_data, "on_island": self.on_island,
                "boards_away": self.boards_away, "travellers": self.travellers, "success": self.success,
                "success_rate": self.success_rate, "failures": dict(self.failures), "burden": self.burden()}


def weighted_median(values: Sequence[tuple[int, int]]) -> float | None:
    """Median of (value, weight) pairs."""
    if not values:
        return None
    ordered, half, seen = sorted(values), sum(w for _, w in values) / 2, 0
    for value, weight in ordered:
        seen += weight
        if seen >= half:
            return value
    return ordered[-1][0]


def outcome(need: Need, results: Mapping[str, Result]) -> str:
    """The need's single outcome code: success, a failure reason, or a no-trip label."""
    if need.label is not None:
        return need.label
    r = results[need.need_id]
    return r.failure_reason if r.status == FAILED else r.status


def score(needs: Iterable[Need], results: Mapping[str, Result],
          group: Callable[[Need], tuple] = lambda n: (n.home_island_id, n.category)) -> dict[tuple, Score]:
    """Scores per group key; by default (home island, category)."""
    scores = defaultdict(Score)
    for n in needs:
        s, code = scores[group(n)], outcome(n, results)
        s.total += n.weight
        if code in NO_DATA_LABELS:
            s.no_data += n.weight
        elif code == ON_ISLAND:
            s.on_island += n.weight
        elif code == BOARDS_AWAY:
            s.boards_away += n.weight
        elif code == SUCCESS:
            s.success += n.weight
            r = results[n.need_id]
            s._burden["in_vehicle"].append((r.in_vehicle_minutes, n.weight))
            s._burden["waiting"].append((r.transfer_wait_minutes + r.wait_at_destination_minutes, n.weight))
            s._burden["away"].append((r.time_away_minutes, n.weight))
        else:
            s.failures[code] += n.weight
    return dict(scores)


def check_totals(needs: Sequence[Need], scores: Mapping[tuple, Score],
                 group: Callable[[Need], tuple] = lambda n: (n.home_island_id, n.category)) -> None:
    """Weighted totals: every group's parts add up, and the groups add up to the needs."""
    expected = Counter()
    for n in needs:
        expected[group(n)] += n.weight
    for key, s in scores.items():
        parts = s.no_data + s.on_island + s.boards_away + s.travellers
        if parts != s.total or s.total != expected[key]:
            raise AssertionError(f"weighted totals do not add up for {key}: parts {parts}, total {s.total}, "
                                 f"expected {expected[key]}")
    if set(scores) != set(expected):
        raise AssertionError("scored groups differ from the needs' groups")


def gains_and_losses(needs: Iterable[Need], baseline: Sequence[Result], scenario: Sequence[Result],
                     group: Callable[[Need], tuple] = lambda n: (n.home_island_id, n.category)) -> dict[tuple, dict]:
    """Weighted residents gained and lost per group, kept separate (never netted)."""
    d = compare(baseline, scenario)
    gained, lost = set(d.gained), set(d.lost)
    out = defaultdict(lambda: {"gained": 0, "lost": 0})
    for n in needs:
        if n.need_id in gained:
            out[group(n)]["gained"] += n.weight
        elif n.need_id in lost:
            out[group(n)]["lost"] += n.weight
    return dict(out)
