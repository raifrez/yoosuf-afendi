"""M.A.N.D.A.R.I.N journey simulator: round trips over the ferry timetable.

Core (no file I/O, portable): timetable (model + edits), csa (connection scan),
evaluate (round trips and failure reasons), diff (baseline vs scenario),
schools (who commutes to another island's school, and when).
Inputs: simulator.load. Sanity views: uv run python -m simulator.demo --atolls F Dh
and uv run python -m simulator.school_demo --atolls F Dh
"""

from simulator.csa import Journey, Leg, earliest_arrival, latest_departure
from simulator.diff import Diff, compare
from simulator.evaluate import (Params, Request, Result, MissedTransfer, appointment_requests,
                                describe_params, evaluate, evaluate_requests, filter_home_atolls)
from simulator.schools import (Assignment, School, SchoolParams, Session, Student, assign_students,
                               school_requests, summarise)
from simulator.timetable import Timetable, Trip, StopTime, TripShift, apply_edits
