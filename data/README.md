# Shared Maldives data

This folder is prepared for `/Users/shaaik/projects/yoosuf-afendi/data`. It contains a local DuckDB snapshot, Parquet tables, original provided archives, structured captures of official facility directories, source metadata, and the build script. Preparation took place in `datathon` because the current session cannot write to the destination repository.

## Use from any app

Install the pinned dependency from `requirements.txt`. Open the database read-only:

```python
import duckdb

db = duckdb.connect("data/database/shared.duckdb", read_only=True)
print(db.execute("SELECT count(*) FROM population.persons").fetchone())
```

Each app can read this snapshot. Only `build.py` writes the database; apps must not concurrently update the shared DuckDB file. Consumers on different machines need a local copy of the snapshot. Read-only access is also suitable for querying the included Parquet files directly.

## Included data

| Dataset | Rows | Coverage |
|---|---:|---|
| `geo.islands` | 193 | Census inhabited/administrative areas, including separate Maale wards |
| `geo.atolls` | 21 | Atoll codes derived from those areas |
| `population.persons` | 448,819 | Named synthetic people; Census 2022 demographic anchor |
| `population.households` | 90,459 | Synthetic household memberships; supported economics modeled from HIES 2019 |
| `population.population_groups` | 578 | Island/age population weights |
| `population.journey_requests` | 417,415 | Assumed October 2026 demand: 13,465 people per day |
| `services.schools` | 220 | Listed government schools; directory headline says 219, retained as a source discrepancy |
| `services.health_facilities` | 193 | Government facilities in the official December 2024 list |
| `services.hospitals` | 22 | Facilities classified as HG or T by that source |
| `services.health_centres` | 164 | HCG classifications; other health entries are clinics |
| `services.clinics` | 7 | General clinics (`GC`) in the government health list |
| `services.school_grades` | 12 | Grades 1–12 for one verified school profile, Maafushi School |

The health snapshot is a **2024 government list**, not the live registry of all public/private facilities. Its operating status applies to the source date. Exact source level codes and registration/license numbers are retained, including duplicate registration numbers in the source. Facility identifiers use license numbers for health entries and name/contact identity for the school directory.

School grades are **partial**. Maafushi School's official profile states foundation stage through Grade 12; numeric grades are expanded from that explicit range, and foundation is retained separately as a stage. Other school offerings remain unknown until verified. No grade is inferred from a school name or from aggregate island enrollment. `grades_status` distinguishes a verified profile range from unknown information.

The combined `services.facilities` table contains all school and health entries. It includes `government_level_raw`, `level_family`, `level_number`, and `level_label`, allowing hospital/health-centre grades to be filtered and sorted within their classification. These fields do not establish clinical specialties or appointment availability. A single universal medical capability ranking is not imposed.

## Locations and routing gaps

- Two schools have island mappings from reviewed official profiles. Other mappings use a unique whole island name appearing in the facility name; repeated names and unresolved facilities are left null. `location_match` records the method.
- Health facilities are placed in this order: `manual_sourced` (a reviewed row in `facility_islands_manual.csv`, with its URL in `location_source_url`); `atoll_name_derived` (the "<Atoll> <Island> Health Centre" name matches an island in that atoll exactly); `atoll_spelling_variant` (one island in that atoll has a clearly closer name, ≥ 0.8 similarity and a 0.1 lead over the next); and `unique_name_derived`. All 22 hospitals and 164 health centres are placed. Six of the 7 clinics are unresolved. To fix a facility, add a sourced row to the lookup, update its `sha256` in `catalog.json`, and rebuild.
- Facility coordinates are unknown and remain null. `services.facility_island_points` joins Census **island reference points**, explicitly named as such, for approximate map placement. They are not facility entrance coordinates or evidence for a walking transfer time.
- `transport.terminals`, `routes`, `trips`, `trip_stops`, and `transfers` are empty typed tables. Verified timetables, fares, operating dates, and terminal data still need to be sourced.
- `services.facility_services` and `facility_hours` are empty: specialties and opening hours have not been established.
- `population.journey_requests` assumes 3% of residents travel daily and randomly assigns healthcare, education, employment, or other with equal probability. Healthcare requests target hospital, health centre, or clinic categories. Workplace and other destination catalogs are still missing, so those requests cannot yet be fully routed.

`meta.datasets` marks these gaps as `not_sourced`. An empty table is not evidence that there is no transport, no healthcare service, or no demand. The data snapshot alone is not sufficient for a complete accessibility simulation.

## Layout and provenance

```text
data/
  MTCC.xlsx                       # Optional demo passenger workbook; not observed demand
  database/shared.duckdb
  processed/population/*.parquet
  processed/facilities/*.parquet
  processed/facilities/*.json
  raw/archives/                 # Original supplied Census/HIES archives and geography tooling ZIP
  raw/facilities/*.snapshot.json
  raw/pipeline/population_generator.zip
  schemas/*.schema.json
  catalog.json
  build_report.json
  build.py
  requirements.txt
```

`catalog.json` and `meta.sources` contain source URLs, dates, local paths, checksums, and availability. Facility snapshots are factual structured extracts saved from official web/PDF captures; they are not original HTML or PDF bytes. The original facility PDF URL is retained for retrieval. Original supplied microdata archives are copied unchanged and remain local inputs; generated synthetic records are separate from source microdata. Large archives and generated database files are ignored by this folder's Git rules; compressed Parquet, snapshots, and the catalog can accompany the repository.

Population provenance, reference years, seed, assumptions, and validation are in `processed/population/manifest.json` and `generation_report.json`. The original generator code/contracts/tests are included in `raw/pipeline/population_generator.zip` for inspection. HIES economics retain 2019 nominal MVR; neither reference-year population nor household spending is projected to 2026. Original observed identities are not exported as synthetic person IDs.

The provided geography repository ZIP contains downloader code, not its published JSON files. No school/facility locations or population totals are claimed to come from unavailable geography JSON. The population's island coordinates come from the supplied Census data.

## Rebuild and query

Run from the shared repository after copying this folder:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r data/requirements.txt
.venv/bin/python data/build.py
```

The build requires only local inputs. It verifies source hashes and facility references, creates a temporary database, and replaces the shared snapshot after successful completion. Review changes to source snapshots and update their catalog checksums before rebuilding an intentionally revised dataset. Restart long-lived app connections to consume a new snapshot.

Find hospitals by their source classification:

```sql
SELECT name, government_level_raw, level_label, island_id
FROM services.hospitals
ORDER BY CASE WHEN level_family = 'T' THEN 0 ELSE 1 END,
         level_number DESC, name;
```

Find schools with verified Grade 11 provision:

```sql
SELECT s.name, s.island_id, g.source_url
FROM services.schools s
JOIN services.school_grades g USING (facility_id)
WHERE g.grade = '11';
```

That query returns only verified records in this snapshot; it is not a national count of schools offering Grade 11. Check `grades_status` and `meta.datasets` when interpreting coverage.

## Sources

- [Census microdata access](https://app.statisticsmaldives.gov.mv/census-data/) — supplied Census 2022 household and individual archives.
- [HIES 2019](https://statisticsmaldives.gov.mv/hies-2019/) — supplied income/expenditure archive; non-raised donor data used for modeling.
- [Official government school directory](https://www.moe.gov.mv/en/schools) — names and contact details, page dated 23 May 2025.
- [Official government health-facility list](https://health.gov.mv/en/publications/government-health-facilities-list-1) — snapshot dated 31 December 2024.
- [Maafushi School profile](https://www.moe.gov.mv/en/schools/526) — verified grade range and island.
- [Sheikh Ibrahim School profile](https://www.moe.gov.mv/en/schools/435) — verified island, no grade offering established.
- [RTL](https://www.rtl.mv/) — transport discovery link only; schedules have not been downloaded or represented as verified data.
- `MTCC.xlsx` — optional local demo workbook; its own README says passenger counts are randomly generated and not actual MTCC/RTL figures.
