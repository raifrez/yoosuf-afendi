"""Baseline vs scenario comparison. Pure: no file I/O.

Gains and losses are kept separate and never netted: a scenario that helps one
island and hurts another shows both.
"""

from dataclasses import dataclass
from typing import Sequence

from simulator.evaluate import FAILED, Result


@dataclass(frozen=True)
class Diff:
    gained: tuple[str, ...]  # request_ids: failed -> success
    lost: tuple[str, ...]  # request_ids: success -> failed
    unchanged: tuple[str, ...]  # everything else, including no_data and on_island
    reason_changed: tuple[tuple[str, str, str], ...]  # (request_id, baseline, scenario); failed in both


def compare(baseline: Sequence[Result], scenario: Sequence[Result]) -> Diff:
    """Compare results for the same request IDs (in baseline order)."""
    base = {r.request_id: r for r in baseline}
    scen = {r.request_id: r for r in scenario}
    if len(base) != len(baseline) or len(scen) != len(scenario):
        raise ValueError("duplicate request_id in results")
    if base.keys() != scen.keys():
        raise ValueError("baseline and scenario must cover the same request IDs")
    gained, lost, unchanged, reason_changed = [], [], [], []
    for rid, b in base.items():
        s = scen[rid]
        if b.status == FAILED and s.succeeded:
            gained.append(rid)
        elif b.succeeded and s.status == FAILED:
            lost.append(rid)
        else:
            unchanged.append(rid)
            if b.status == s.status == FAILED and b.failure_reason != s.failure_reason:
                reason_changed.append((rid, b.failure_reason, s.failure_reason))
    return Diff(tuple(gained), tuple(lost), tuple(unchanged), tuple(reason_changed))
