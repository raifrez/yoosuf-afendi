# Demo resident: Aminath Shafeeg, GA. Gemanafushi

The opening of the demo story: one synthetic resident whose hospital visit fails, why it fails, and one ferry edit that fixes it for her island while costing another island.

Results are **modelled access barriers**, not counts of patients denied care. Source of truth: `simulator/demo_story.py` (fixed input) and `data/export/simulation/demo.json` (generated). Numbers below are from the model run on 2026-10-24 over the four demo atolls (F, Dh, GA, GDh).

## Who she is

| | | Label |
|---|---|---|
| Person | `person-1182-000243-001`, Aminath Shafeeg, 68 (name is synthetic) | `derived` |
| Home | GA. Gemanafushi (Census `1182`), 1,318 residents in the model | `derived` |
| Household | `hh-1182-000243`, 5 people: Fathimath Naeem (36), Ali Rasheed (21), Mohamed Shafeeg (15), Mohamed Naeem (11) | `derived` |
| Why her | First resident aged 65+ on Gemanafushi (by date, then person ID) with a healthcare request in the generated demand | `demo` |

## Her needs (baseline timetable)

| Category | Destination | Appointment | Outcome |
|---|---|---|---|
| `health_centre` | Health centre on Gemanafushi | none needed | `on_island` |
| `hospital_elderly` | Gaafu Alifu Atoll Hospital, GA. Viligili (Grade 2) | 11:30, 120 min, home by 17:00 | **`no_return`** |
| `referral` | Dr. Abdul Samad Memorial Hospital, GDh. Thinadhoo (Grade 3) | 08:00, 120 min, home by 18:00 | **`arrives_late`** |

## Why her hospital visit fails

| | Sailing | Depart | Arrive |
|---|---|---|---|
| Outward | `236_0` Gemanafushi → Viligili | 06:20 | 07:50 |
| Appointment | Viligili hospital | 11:30 | 13:30 |
| Only boat home | `236_1` Viligili → Gemanafushi | 16:45 | **18:10** |

She can get to the hospital, but the only boat home lands at 18:10, 70 minutes after her 17:00 home-by time: **she can get there but can't get back the same day.**

There's no backup hospital. Her referral trip to Thinadhoo goes via Viligili (`236_0` then `183_0`) and arrives at 09:35, after her 08:00 appointment.

**Her island:** none of Gemanafushi's 79 elderly residents can make a same-day hospital visit (0%, all `no_return`).

## The edit: `236_1` leaves 70 minutes earlier

Viligili → Gemanafushi moves from 16:45 to **15:35**. The scenario is applied to a copy, so the baseline doesn't change.

### Her journey after the edit: `success`

| | Sailing | Depart | Arrive |
|---|---|---|---|
| Outward | `236_0` Gemanafushi → Viligili | 06:20 | 07:50 |
| Appointment | Viligili hospital | 11:30 | 13:30 |
| Home | `236_1` Viligili → Gemanafushi | 15:35 | **17:00** |

**Burden, shown next to the score, not inside it:** 175 min on boats, 345 min waiting at the hospital, 640 min (10 h 40 min) away from home. Her referral trip still fails (`arrives_late`), because the edit doesn't touch the morning sailings.

### Who gains and who loses (counted separately, never netted)

| Island | Category | Gained | Lost |
|---|---|---|---|
| GA. Gemanafushi | `hospital_adult` | 745 | 0 |
| GA. Gemanafushi | `hospital_child` | 450 | 0 |
| GA. Gemanafushi | `hospital_elderly` | 72 | 0 |
| GA. Kanduhulhudhoo | `hospital_adult` | 378 | 0 |
| GA. Kanduhulhudhoo | `hospital_child` | 190 | 0 |
| GA. Kodey | `hospital_elderly` | 26 | 0 |
| GA. Kodey | `hospital_adult` | 0 | 4 |
| GA. Kodey | `hospital_child` | 0 | 5 |
| GA. Kodey | `referral` | 0 | **187** |
| **Total** | | **1,861** | **196** |

- **Gemanafushi elderly:** 0% → 91% (72 of 79). The other 7 still can't get home in time.
- **Kodey referral:** 57% → **0%** (187 of 328 lose). Kodey residents coming back from Thinadhoo reach Viligili at 16:35, an hour after their connecting boat home now leaves.

## Why −70 minutes

`236_1` was swept from −35 to −120 minutes in 5-minute steps. −70 is the smallest shift that brings her home by 17:00, and no larger shift gains more. At −35 she still arrives home at 17:35 (`no_return`). Larger shifts (−80 and beyond) gain fewer residents and cost Kodey more.

## Assumptions to show on screen

| Assumption | Label |
|---|---|
| Ferry timetable (RTL schedules); operating days assumed daily | `observed` / `assumed` |
| Hospital visits go to a hospital in the home atoll; referral to the nearest Grade 3 or tertiary hospital | `assumed` / `derived` |
| Appointment time and duration spread deterministically over 08:00–14:00 (seed 42) | `assumed` |
| Home by 17:00 for ages 65+, 18:00 for everyone else | `assumed` |
| Minimum transfer time 5 min; no jetty → facility time | `assumed` |
| Choice of resident and edit | `demo` |

Her failure depends on the assumed 17:00 home-by time for ages 65+.

## Reproduce

```bash
uv run python -m simulator.export          # writes data/export/simulation/demo.json
uv run python -m simulator.demo --atolls GA GDh --shift 236_1=-70
uv run python -m simulator.server          # GET /api/demo; POST /api/scenario with the edit;
                                           # GET /api/resident/person-1182-000243-001
```
