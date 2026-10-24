"""Read sample ferry boarding volumes and allocate modeled journey demand."""

from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation

from .xlsx import rows


# The workbook combines the two southern atolls; it does not report their split.
ATOLLS = {
    "Haa Alifu": ("HA",),
    "Lhaviyani": ("Lh",),
    "Noonu": ("N",),
    "Gaafu Alifu & Gaafu Dhaalu": ("GA", "GDh"),
}


def ferry_volumes(path, month):
    """Sum route passenger boardings for a reporting month, not unique people."""
    date.fromisoformat(month + "-01")
    totals = Counter()
    seen = set()
    months = set()
    for row in rows(path, sheet="ferry_monthly", columns=["month", "atoll", "route_id", "passengers"]):
        date.fromisoformat(row["month"] + "-01")
        months.add(row["month"])
        key = (row["month"], row["atoll"], row["route_id"])
        if key in seen:
            raise ValueError(f"Duplicate ferry route/month: {key}")
        seen.add(key)
        if row["atoll"] not in ATOLLS:
            raise ValueError(f"Unmapped ferry atoll: {row['atoll']!r}")
        try:
            count = Decimal(row["passengers"])
        except InvalidOperation as error:
            raise ValueError("Invalid ferry passenger count") from error
        if not count.is_finite() or count < 0 or count != count.to_integral_value():
            raise ValueError("Invalid ferry passenger count")
        if row["month"] == month:
            totals[row["atoll"]] += int(count)
    if month not in months:
        raise ValueError(f"No ferry data for {month}")
    return dict(totals)


def allocate_volumes(totals, islands, populations):
    """Largest-remainder allocation, preserving each source area's exact total.

    Call with the full population before filtering islands so a subset receives
    the same island volumes as a national run. Uncovered atolls stay unmodeled.
    """
    result = {}
    for atoll, count in sorted(totals.items()):
        candidates = sorted(
            (code for code, island in islands.items()
             if island["atoll_code"] in ATOLLS[atoll] and populations[code] > 0),
            key=int,
        )
        total_population = sum(populations[code] for code in candidates)
        if not total_population:
            raise ValueError(f"No population for ferry area {atoll}")
        allocations = {code: count * populations[code] // total_population for code in candidates}
        remaining = count - sum(allocations.values())
        order = sorted(candidates, key=lambda code: (-(count * populations[code] % total_population), int(code)))
        for code in order[:remaining]:
            allocations[code] += 1
        result.update(allocations)
    return result


def load_scenario(path, model="ferry"):
    """Require appointment assumptions explicitly instead of inferring them."""
    import json
    import re
    scenario = json.loads(path.read_text())
    required = {"month", "appointment_time", "activity_duration_minutes", "return_home_by"}
    if model == "ferry":
        required.update(("purpose", "destinations"))
    if set(scenario) != required:
        raise ValueError(f"Journey scenario must contain exactly {sorted(required)}")
    date.fromisoformat(scenario["month"] + "-01")
    from .demand import PURPOSES
    if model == "ferry" and scenario["purpose"] not in PURPOSES:
        raise ValueError("Invalid journey purpose")
    for field in ("appointment_time", "return_home_by"):
        if not isinstance(scenario[field], str) or not re.fullmatch(r"([01][0-9]|2[0-3]):[0-5][0-9]", scenario[field]):
            raise ValueError(f"Invalid scenario {field}")
    duration = scenario["activity_duration_minutes"]
    if type(duration) is not int or duration < 1:
        raise ValueError("Invalid scenario activity_duration_minutes")
    minutes = lambda value: sum(int(part) * scale for part, scale in zip(value.split(":"), (60, 1)))
    if minutes(scenario["appointment_time"]) + duration > minutes(scenario["return_home_by"]):
        raise ValueError("Activity exceeds same-day return deadline")
    if model == "ferry":
        if not isinstance(scenario["destinations"], dict) or not scenario["destinations"] or any(
            not isinstance(value, str) or not value.strip() for value in scenario["destinations"].values()
        ):
            raise ValueError("Ferry scenario destinations must map Census atoll codes to facility IDs")
    scenario["model"] = model
    return scenario


def journey_rows(code, people, count, scenario, seed):
    """Draw residents with replacement: boardings can include repeat travelers."""
    import calendar
    import random
    from .generate import stable_int

    rng = random.Random(stable_int(seed, "ferry-journeys", scenario["month"], code))
    year, month = map(int, scenario["month"].split("-"))
    days = calendar.monthrange(year, month)[1]
    for index in range(count):
        person_id = rng.choice(people)
        yield {
            "journey_request_id": f"request-{scenario['month']}-{code}-{index + 1:07d}",
            "person_id": person_id, "purpose": scenario["purpose"],
            "origin_island_id": code,
            "destination_facility_id": scenario["destination_facility_id"],
            "destination_facility_type": None,
            "date": date(year, month, rng.randint(1, days)).isoformat(),
            "appointment_time": scenario["appointment_time"],
            "activity_duration_minutes": scenario["activity_duration_minutes"],
            "return_home_by": scenario["return_home_by"],
            "timezone": "Indian/Maldives", "data_classification": "demo",
        }
