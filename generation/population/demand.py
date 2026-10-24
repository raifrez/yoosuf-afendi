"""Assumed daily travel needs: 3% of residents with random trip purposes."""

import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import random


PURPOSES = ("healthcare", "education", "employment", "other")
HEALTHCARE_FACILITY_TYPES = ("hospital", "health_centre", "clinic")
DESTINATION_TYPES = {
    "education": "government_school",
    "employment": "workplace",
    "other": "other",
}
DAILY_RATE = Decimal("0.03")


def daily_allocations(populations):
    """Round nationally, then apportion to islands before any island filtering."""
    if any(type(value) is not int or value < 0 for value in populations.values()):
        raise ValueError("Population counts must be nonnegative integers")
    total = sum(populations.values())
    target = int((total * DAILY_RATE).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    counts = {code: int(value * DAILY_RATE) for code, value in populations.items()}
    order = sorted(populations, key=lambda code: (-(populations[code] * DAILY_RATE % 1), int(code)))
    for code in order[:target - sum(counts.values())]:
        counts[code] += 1
    return counts


def daily_journey_rows(code, people, count, scenario, seed):
    """Select distinct residents per day; a resident may travel on later days."""
    from .generate import stable_int

    year, month = map(int, scenario["month"].split("-"))
    for day in range(1, calendar.monthrange(year, month)[1] + 1):
        travel_date = date(year, month, day).isoformat()
        rng = random.Random(stable_int(seed, "daily-travel-v1", travel_date, code))
        for index, person_id in enumerate(rng.sample(people, count)):
            purpose = rng.choice(PURPOSES)
            healthcare = purpose == "healthcare"
            facility_type = rng.choice(HEALTHCARE_FACILITY_TYPES) if healthcare else DESTINATION_TYPES[purpose]
            yield {
                "journey_request_id": f"request-{travel_date}-{code}-{index + 1:07d}",
                "person_id": person_id, "purpose": purpose,
                "origin_island_id": code,
                "destination_facility_id": None,
                "destination_facility_type": facility_type,
                "date": travel_date,
                "appointment_time": scenario["appointment_time"],
                "activity_duration_minutes": scenario["activity_duration_minutes"],
                "return_home_by": scenario["return_home_by"],
                "timezone": "Indian/Maldives", "data_classification": "assumed",
            }
