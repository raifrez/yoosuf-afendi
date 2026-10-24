# Population → simulator handoff, version 1.0

This is the data shape agreement for M.A.N.D.A.R.I.N. The population component supplies synthetic households, people, weighted demographic groups, and separately defined scenario journey requests. The simulator chooses transport modes, routes, departure times, connections, and what counts as the best feasible journey.

**Start here:** [complete example](../examples/population.example.json) · [bundle schema](../schemas/population.schema.json). All counts, ages, economic values, names, and appointments in the example are fictional. Its four residents are not an estimate of Maafushi's population. Only the island identifier/name follows the supplied Census dictionary.

## Files and storage

Use DuckDB to query generated tables and export typed Parquet for simulator exchange. JSON is the human-readable example format. The [generation guide](POPULATION_GENERATION.md) describes the implemented local Excel ingestion, Census synthesis, weighted HIES economic assignment, and export commands.

Each completed generation run will have its own directory:

```text
data/generated/<population_id>/
  population.duckdb              # Typed tables and manifest JSON
  manifest.json                 # The metadata object in the JSON example
  islands.parquet
  households.parquet
  persons.parquet
  population_groups.parquet
  journey_requests.parquet
  generation_report.json        # Source hashes, calibration and checks
  preview.json                  # A small complete-household subset
```

Each array in the JSON bundle becomes the corresponding Parquet table. A bundle must contain all five arrays, including empty arrays when there are no requests. A filtered export includes all required island, household, person, and group records for the selected islands and their requests; it must pass the same totals and reference checks. Keep these snapshots immutable during baseline/scenario comparisons.

IDs are nonempty strings (`VARCHAR`); classifications and categories are strings too. Every documented field is required; only fields explicitly marked nullable accept null. Do not use empty strings for missing values. JSON Schemas describe individual rows; `population.schema.json` describes the complete bundle. Unknown fields are rejected in version 1.0.

## Table shapes

### Islands

Schema: [islands.schema.json](../schemas/islands.schema.json).

| Field | JSON / DuckDB-Parquet type | Meaning |
|---|---|---|
| `island_id` | string / `VARCHAR` | Canonical Census island code as a string, e.g. `"69"` |
| `name` | string / `VARCHAR` | Island name, e.g. `Maafushi` |
| `atoll_code` | string / `VARCHAR` | Atoll abbreviation, e.g. `K` |
| `geography_id` | string or null / nullable `VARCHAR` | Explicit mapping to the downloaded geography dataset's ID |
| `latitude`, `longitude` | number or null / nullable `DOUBLE` | Island reference point in WGS84, never a household address |
| `data_classification` | string / `VARCHAR` | `observed`, `derived`, `assumed`, or `demo` |

The Census code and geography FCODE/ID are different identifiers. Map them explicitly; do not assume equality or silently merge islands by name. Download and retain geography JSON locally before processing. Census totals remain the demographic anchor; geography-layer population figures must not silently replace them.

### Households

Schema: [households.schema.json](../schemas/households.schema.json).

| Field | JSON / DuckDB-Parquet type | Meaning |
|---|---|---|
| `household_id` | string / `VARCHAR` | Unique synthetic household ID |
| `home_island_id` | string / `VARCHAR` | References `islands.island_id` |
| `household_size` | integer / `INTEGER` | Number of linked person rows; at least 1 |
| `monthly_income_mvr` | number or null / nullable `DECIMAL(18,2)` | Household income in MVR/month |
| `monthly_expenditure_mvr` | number or null / nullable `DECIMAL(18,2)` | Household expenditure in MVR/month; nonnegative |
| `economic_assignment` | string / `VARCHAR` | `hies_modeled`, `unavailable`, or `demo` |
| `data_classification` | string / `VARCHAR` | `derived`, `assumed`, or `demo` |

Money has at most two decimal places. Income permits negative values to avoid silently clipping a modeled net loss; source processing must document its income definition. If economics are unavailable, both amounts are null and `economic_assignment` is `unavailable`. Null is not zero. If only one measure is unavailable, its value can be null with an appropriate modeled/demo assignment and metadata caveat. Household totals are not each member's income, disposable income, or travel budget. Never multiply household money by member count when aggregating.

Census and HIES households are different observations from different years: no direct identity join between them is implied. HIES assignment respects survey weights and conservative housing coverage, retains the reference year, and labels imputed household economics as modeled. Do not imply that a 2019 amount is a current nominal income.

### Persons

Schema: [persons.schema.json](../schemas/persons.schema.json).

| Field | JSON / DuckDB-Parquet type | Meaning |
|---|---|---|
| `person_id` | string / `VARCHAR` | Unique synthetic person ID |
| `display_name` | string / `VARCHAR` | Fictional human-readable name |
| `name_is_synthetic` | boolean / `BOOLEAN` | Always `true` |
| `household_id` | string / `VARCHAR` | References `households.household_id` |
| `home_island_id` | string / `VARCHAR` | References `islands.island_id`; matches household and group |
| `age` | integer or null / nullable `INTEGER` | Nonnegative completed years; null if unknown |
| `age_group` | string / `VARCHAR` | `0_17`, `18_64`, `65_plus`, or `unknown` |
| `group_id` | string / `VARCHAR` | References `population_groups.group_id` |
| `population_weight` | integer / `BIGINT` | Always 1 in this version: one row per synthetic resident |
| `data_classification` | string / `VARCHAR` | `derived`, `assumed`, or `demo` |

Known ages determine age groups: 0–17, 18–64, and 65+. A null age requires `unknown`. No sex, nationality, religion, illness, attendance, or observed identity should be inferred from a generated name. Additional demographic fields require a future contract revision.

### Population groups

Schema: [population_groups.schema.json](../schemas/population_groups.schema.json).

| Field | JSON / DuckDB-Parquet type | Meaning |
|---|---|---|
| `group_id` | string / `VARCHAR` | Unique stable synthetic group ID |
| `label` | string / `VARCHAR` | E.g. `Maafushi residents aged 65+` |
| `home_island_id` | string / `VARCHAR` | References `islands.island_id` |
| `age_group` | string / `VARCHAR` | Same categories as persons |
| `population_weight` | integer / `BIGINT` | Positive number of linked person rows |
| `data_classification` | string / `VARCHAR` | `derived`, `assumed`, or `demo` |

Group counts describe the represented population. They are not counts of people requesting healthcare. Groups and persons describe the same residents: never sum both representations. Individual appointment requests are the authoritative demand records in this contract.

### Journey requests: a person's activity and travel need

Schema: [journey_requests.schema.json](../schemas/journey_requests.schema.json).

```json
{
  "journey_request_id": "request-002",
  "person_id": "person-004",
  "purpose": "healthcare",
  "origin_island_id": "69",
  "destination_facility_id": "demo-hospital-001",
  "destination_facility_type": null,
  "date": "2026-10-24",
  "appointment_time": "09:00",
  "activity_duration_minutes": 60,
  "return_home_by": "18:00",
  "timezone": "Indian/Maldives",
  "data_classification": "demo"
}
```

This says that fictional **Mariyam Noor**, aged 68, needs to reach the selected hospital by 09:00, complete a 60-minute visit starting at 09:00, and return home by 18:00. It makes no transport choice and does not guarantee feasibility. Arriving early means waiting until the appointment starts.

| Field | JSON / DuckDB-Parquet type | Meaning |
|---|---|---|
| `journey_request_id` | string / `VARCHAR` | Unique scenario request ID |
| `person_id` | string / `VARCHAR` | References `persons.person_id` |
| `purpose` | string / `VARCHAR` | `healthcare`, `education`, `employment`, or `other` |
| `origin_island_id` | string / `VARCHAR` | Matches the person's home island |
| `destination_facility_id` | string or null / `VARCHAR` | Exact destination, or null when a healthcare facility type must be resolved |
| `destination_facility_type` | string or null / `VARCHAR` | Unresolved target class: three healthcare types, `government_school`, `workplace`, or `other` |
| `date` | ISO `YYYY-MM-DD` string / `DATE` | Selected operating day |
| `appointment_time` | local `HH:MM` string / `TIME` | Latest arrival time and fixed activity start; retained as the contract field name for all purposes |
| `activity_duration_minutes` | integer / `INTEGER` | Positive activity duration |
| `return_home_by` | local `HH:MM` string / `TIME` | Home-return deadline on the same date |
| `timezone` | string / `VARCHAR` | Always `Indian/Maldives` |
| `data_classification` | string / `VARCHAR` | `assumed` or `demo`; never an observed appointment claim |

All times are local; overnight requests are unsupported in version 1.0. The activity must finish by the return deadline even before travel is considered. Every request supplies exactly one of an exact facility ID or a destination facility type. Healthcare types are `hospital`, `health_centre`, and `clinic`; the other purpose/type pairs are education/`government_school`, employment/`workplace`, and other/`other`. A syntactically valid request can still fail routing. The simulator must resolve a suitable destination, available modes, schedules for the selected day, and transfers. Workplace and other destination catalogs are not sourced in this repository.

Requests are created only from explicit scenario assumptions. Census/HIES does not identify actual appointments. The same person may have multiple requests; results per request are not unique-person totals.

The example has **four residents and two requests**. Only one of the two adults has an appointment. Do not evaluate that request with the adult demographic group's weight of 2. If the simulator groups requests for performance, it must group only equivalent requests and use the number of participating people, accounting for any other routing-relevant attributes. Population groups alone do not establish journey equivalence. The original group-level journey-rule workflow remains possible when a simulator rule explicitly applies to every represented group member.

### Generation metadata / manifest

Schema: [generation_metadata.schema.json](../schemas/generation_metadata.schema.json).

The manifest is a JSON object rather than a Parquet table. It records `schema_version` (`1.0`), `population_id`, `synthetic` (`true`), overall `data_classification`, demographic/economic reference years, `currency` (`MVR`), `economic_period` (`month`), integer `seed`, `name_catalog_version`, `name_catalog_sha256`, `sources`, and `assumptions`.

Every source entry contains `source_id`, `publisher`, `file` (local source path or file/member reference), `reference_year` (integer or null), `data_classification`, and `caveats`. Use unique source IDs and explain source scope, date limitations, and modeling decisions in assumptions. Observed sources can produce derived synthetic demographics; generated people remain synthetic. Any material demo input makes the overall population a demo. A name catalog hash records exactly which editable list was used; it is not an identity hash.

## Synthetic names

The dependency-free generator uses SHA-256 of the name-catalog version, integer seed, and stable person ID to choose two components. It does not use input order or global random state. The same ID, seed, catalog, and algorithm produce the same name when generating a subset or a full population.

The editable [starter catalog](../population/data/name_components.json) contains Maldivian name components. Have the team review it for local presentation; it is not a frequency model, a family-name model, or a claim that every combination is culturally preferred. Names are display labels only, may repeat, and are unrelated to source identities. Changing the list or algorithm may change names; preserve its version/hash with each run. Use IDs for all joins.

From the repository root:

```sh
python3 -m population.names --seed 42 person-001 person-004
```

```json
[
  {"person_id": "person-001", "display_name": "Ibrahim Latheef", "name_is_synthetic": true},
  {"person_id": "person-004", "display_name": "Mariyam Noor", "name_is_synthetic": true}
]
```

To use a different local list, pass `--catalog path/to/name_components.json`. Keep both arrays nonempty and bump the version when editing the catalog. Group labels remain demographic descriptions, not people's names.

## Validation and simulator handoff

Run these commands from the repository root; neither requires third-party packages:

```sh
python3 -m population.validate examples/population.example.json
python3 -m unittest discover -s tests -v
```

The offline validator reads the checked-in schemas and implements their used keyword subset, including local references, field types, required fields, enums, numeric bounds, date/time formats, and nullable values. It rejects unsupported keywords rather than treating them as validated. These are standard Draft 2020-12 JSON Schemas; an optional `jsonschema` extra supports independent validation and meta-schema checking in the test suite:

```sh
python3 -m pip install -e '.[validation]'
python3 -m unittest discover -s tests -v
```

Cross-record checks enforce unique IDs, existing references, matching home islands and ages, household membership totals, group weights, and valid same-day activity windows. The validator does not establish transport feasibility, verify external facility IDs, or prove demographic calibration to Census totals. Those checks require their respective source data and simulator inputs. Subset exports must remain internally complete; schema/contract changes must update the example, schemas, types, and tests together.

The simulator developer can start with the JSON fixture, then switch the same logical tables to Parquet. Load the selected population once for repeated transport scenarios. Baseline and comparison must use the same population and requests. Optimization and transport choices stay with the simulator.
