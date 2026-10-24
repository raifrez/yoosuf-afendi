"""School demand: who commutes to another island's school, and when. Pure: no file I/O.

Each student is placed in exactly one category. The category is decided once, on the
baseline timetable, so ferry and school-time scenarios keep the same students and requests:
  home_island    a school on the home island teaches their grade (no ferry trip)
  daily_commute  the nearest school teaching the grade is within `max_school_commute_minutes`
                 one way; the student gets a round-trip request: arrive by the session start,
                 stay for the session, home by `school_home_by`
  boards_away    the nearest such school is further than that. Modelled as living away from
                 home to study, not as a daily trip: an access barrier, reported as a count
  no_data        the home island has no ferry stop and no school teaching the grade
  no_school      no school teaching the grade can be reached by ferry from the home island

Rules (labels in SCHOOL_PARAM_NOTES):
  - Grade from age: grade = age - 5 for ages 6-17 (derived: National Curriculum Framework 2014,
    Table 2, age at the start of each grade). Everyone of school age counts as a student
    (assumed: enrolment is not known, so counts are an upper bound; rates are unaffected).
  - A school with unknown grades is assumed to teach grades 1-10. Grades 11-12 count only
    where a school profile states them.
  - Only schools in the student's home atoll are candidates (assumed: students attend their
    own atoll's schools; set `home_atoll_only=False` to allow any atoll).
  - Nearest = the shortest one-way ferry time on any sailing that day (simulator.destinations):
    distance, not whether the session times fit.
  - Sessions: 07:05-12:05 for every school by default (assumed, from Rinbudhoo School's
    profile, the only one stating class hours), overridable per school. Changing sessions
    changes the requests' times, never who is a commuter.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from simulator.destinations import FerryDistances
from simulator.evaluate import ON_ISLAND, Params, Request, Result
from simulator.scores import BOARDS_AWAY as SCORE_BOARDS_AWAY, NO_FACILITY, Need
from simulator.timetable import DAY_MINUTES, Timetable

HOME_ISLAND, DAILY_COMMUTE, BOARDS_AWAY, NO_DATA, NO_SCHOOL = (
    "home_island", "daily_commute", "boards_away", "no_data", "no_school")
SCHOOL_AGES = range(6, 18)  # grades 1-12
ASSUMED_GRADES_WHEN_UNKNOWN = frozenset(range(1, 11))


@dataclass(frozen=True)
class Session:
    """School hours in minutes after midnight."""
    start: int
    end: int

    def __post_init__(self):
        if not 0 <= self.start < self.end < DAY_MINUTES:
            raise ValueError(f"a session must start before it ends, within the day: {self}")


DEFAULT_SESSION = Session(7 * 60 + 5, 12 * 60 + 5)


@dataclass(frozen=True)
class SchoolParams:
    max_school_commute_minutes: int = 30
    school_home_by: int = 18 * 60
    home_atoll_only: bool = True

    def __post_init__(self):
        if not isinstance(self.max_school_commute_minutes, int) or self.max_school_commute_minutes < 0:
            raise ValueError("max_school_commute_minutes must be a non-negative integer")
        if not 0 <= self.school_home_by < DAY_MINUTES:
            raise ValueError("school_home_by must be a same-day time")


SCHOOL_PARAM_NOTES = {
    "max_school_commute_minutes": (
        "assumed", "Longest one-way ferry time a student commutes daily. Further away, the "
                   "student is counted as boarding away from home."),
    "school_home_by": ("assumed", "Latest time a commuting student gets home."),
    "home_atoll_only": ("assumed", "Students attend a school in their own atoll."),
    "default_session": ("assumed", "07:05-12:05 for every school, from Rinbudhoo School's profile "
                                   "(the only school stating class hours)."),
    "grade_from_age": ("derived", "grade = age - 5, from the National Curriculum Framework 2014, Table 2."),
    "students": ("assumed", "Everyone aged 6-17 is a student; enrolment is not known."),
    "unknown_grades": ("assumed", "A school whose grades are not sourced teaches grades 1-10."),
}


@dataclass(frozen=True)
class School:
    facility_id: str
    name: str
    island_id: str
    grades: frozenset[int] | None  # None = not sourced

    def teaches(self, grade: int) -> bool:
        return grade in (ASSUMED_GRADES_WHEN_UNKNOWN if self.grades is None else self.grades)


@dataclass(frozen=True)
class Student:
    person_id: str
    home_island_id: str
    age: int
    weight: int = 1


@dataclass(frozen=True)
class Assignment:
    person_id: str
    home_island_id: str
    grade: int
    weight: int
    category: str
    school_facility_id: str | None = None
    school_island_id: str | None = None
    one_way_minutes: int | None = None  # nearest school's shortest ferry time; 0 on the home island

    @property
    def request_id(self) -> str:
        return f"school:{self.person_id}"


def grade_for_age(age: int) -> int | None:
    return age - 5 if age in SCHOOL_AGES else None


def assign_students(baseline: Timetable, island_stops: Mapping[str, Iterable[str]],
                    island_atoll: Mapping[str, str], students: Iterable[Student], schools: Sequence[School],
                    school_params: SchoolParams = SchoolParams(), params: Params = Params()) -> list[Assignment]:
    """One category per school-age student. Pass the baseline timetable, never a scenario.
    `island_atoll` maps Census island_id -> atoll_code."""
    local = defaultdict(list)
    for school in schools:
        local[school.island_id].append(school)
    distances = FerryDistances(baseline, island_stops, params.min_transfer_minutes)

    result = []
    for s in students:
        grade = grade_for_age(s.age)
        if grade is None:
            continue
        base = dict(person_id=s.person_id, home_island_id=s.home_island_id, grade=grade, weight=s.weight)
        here = next((sc for sc in local[s.home_island_id] if sc.teaches(grade)), None)
        if here is not None:
            result.append(Assignment(**base, category=HOME_ISLAND, school_facility_id=here.facility_id,
                                     school_island_id=here.island_id, one_way_minutes=0))
            continue
        if not distances.has_stop(s.home_island_id):
            result.append(Assignment(**base, category=NO_DATA))
            continue
        candidates = [sc for sc in schools if sc.teaches(grade) and distances.has_stop(sc.island_id)
                      and (not school_params.home_atoll_only
                           or island_atoll.get(sc.island_id) == island_atoll.get(s.home_island_id))]
        found = distances.nearest(s.home_island_id, candidates, lambda sc: sc.island_id, lambda sc: sc.facility_id)
        if found is None:
            result.append(Assignment(**base, category=NO_SCHOOL))
            continue
        m, school = found
        category = DAILY_COMMUTE if m <= school_params.max_school_commute_minutes else BOARDS_AWAY
        result.append(Assignment(**base, category=category, school_facility_id=school.facility_id,
                                 school_island_id=school.island_id, one_way_minutes=m))
    return result


def school_requests(assignments: Iterable[Assignment], sessions: Mapping[str, Session] | None = None,
                    default_session: Session = DEFAULT_SESSION,
                    school_params: SchoolParams = SchoolParams()) -> list[Request]:
    """Round-trip requests for daily commuters. `sessions` overrides hours per school facility_id.
    The same assignments with different sessions give the same request IDs, so a school-time
    edit compares against the baseline like a ferry shift."""
    sessions = sessions or {}
    requests = []
    for a in assignments:
        if a.category != DAILY_COMMUTE:
            continue
        session = sessions.get(a.school_facility_id, default_session)
        if session.end > school_params.school_home_by:
            raise ValueError(f"session for {a.school_facility_id} ends after school_home_by")
        requests.append(Request(a.request_id, a.home_island_id, a.school_island_id, session.start,
                                session.end - session.start, school_params.school_home_by,
                                purpose="education", destination_facility_id=a.school_facility_id,
                                data_classification="assumed"))
    return requests


def summarise(assignments: Iterable[Assignment], results: Iterable[Result]) -> dict[str, Counter]:
    """home island_id -> weighted students per label. Commuters are labelled by their trip's
    outcome (success, arrives_late, ...); everyone else by their category."""
    outcome = {r.request_id: r.outcome for r in results}
    summary = defaultdict(Counter)
    for a in assignments:
        label = outcome[a.request_id] if a.category == DAILY_COMMUTE else a.category
        summary[a.home_island_id][label] += a.weight
    return dict(summary)


SCHOOL = "school"
_NEED_LABELS = {HOME_ISLAND: ON_ISLAND, BOARDS_AWAY: SCORE_BOARDS_AWAY, NO_DATA: NO_DATA, NO_SCHOOL: NO_FACILITY}


def school_need_id(a: Assignment) -> str:
    return a.request_id if a.category == DAILY_COMMUTE else f"school:{a.home_island_id}:{_NEED_LABELS[a.category]}"


def school_needs(assignments: Sequence[Assignment], sessions: Mapping[str, Session] | None = None,
                 default_session: Session = DEFAULT_SESSION, school_params: SchoolParams = SchoolParams()) -> list[Need]:
    """Needs for scoring: one per commuter (a trip), one per island and no-trip category (a label)."""
    requests = {r.request_id: r for r in school_requests(assignments, sessions, default_session, school_params)}
    weights = Counter()
    for a in assignments:
        weights[school_need_id(a), a.home_island_id, a.category] += a.weight
    return [Need(need_id, SCHOOL, island, w, request=requests[need_id]) if category == DAILY_COMMUTE
            else Need(need_id, SCHOOL, island, w, label=_NEED_LABELS[category])
            for (need_id, island, category), w in sorted(weights.items())]
