# Generate the population

In the shared repository, use `generation/run.py` from the repository root as documented in [the generation README](../README.md). That wrapper supplies `data/raw/archives` as the source directory and publishes the result into the shared data folder. The CLI examples below describe the standalone project layout; pass `--source-dir ../data/raw/archives` when invoking it directly from `generation/`.

The generator uses the three local Census/HIES archives. It creates a reproducible synthetic population with the [agreed data shapes](POPULATION_SIMULATION_CONTRACT.md), fictional display names, modeled monthly economics, and weighted demographic groups. It does not infer appointments or choose transport.

## Run

Run from the repository root. Python 3.9+ and the `bsdtar` command are required for reading the supplied archives. The Excel reader uses the standard library; DuckDB is required for final database/Parquet export.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install 'duckdb==1.4.5'
.venv/bin/python -m population.generate
```

The first run streams selected columns from the large workbooks into `data/cache/`. Later runs reuse those caches after checking archive hashes. It discovers the variable-name header rows rather than treating the Excel display labels as variable names. Raw source records and their identifiers stay in the ignored local preparation cache.

Each run exports to `data/generated/<population_id>/`:

| File | Contents |
|---|---|
| `population.duckdb` | Typed materialized tables and a `generation_metadata` table containing the manifest JSON |
| `islands.parquet` | Census locality IDs, dictionary names, island coordinates, optional geography mapping |
| `households.parquet` | Synthetic households with modeled or unavailable economic attributes |
| `persons.parquet` | Named synthetic people and their household/group IDs |
| `population_groups.parquet` | Island/age groups with represented population weights |
| `journey_requests.parquet` | Empty typed table until an appointment scenario is defined |
| `manifest.json` | Reference years, seed, source references, and assumptions |
| `generation_report.json` | Source hashes, coverage, calibration, donor support, and validation results |
| `preview.json` | A small, internally complete household subset that follows the JSON contract |

Parquet files use ZSTD compression. The exporter checks database relationships, compares per-area totals to Census, and checks that all Parquet values round-trip. It publishes a complete run only after those checks pass, and does not overwrite an existing run. Repeating the command reuses finished staging or the existing output.

Useful variants:

```sh
# Only the selected Census island codes; same people/names/economics as filtering a full run.
.venv/bin/python -m population.generate --islands 69 745

# A different reproducible assignment.
.venv/bin/python -m population.generate --seed 43

# Use geography JSON already downloaded to local disk.
.venv/bin/python -m population.generate --geography data/raw/geo/islands.json

# Prepare/generate without DuckDB, retaining validated intermediate CSV files.
python3 -m population.generate --stage-only
```

If DuckDB is unavailable, validated CSV staging remains in `data/cache/<population_id>-staging/`. After installing DuckDB, rerun `population.generate`, or finish only the export:

```sh
.venv/bin/python -m population.export data/cache/<population_id>-staging
```

Use the actual printed population ID rather than the placeholder. CSV staging uses `\N` for null. Its values have been checked against the row schemas, but final Parquet/database checks require DuckDB. Do not present a staged-only run as a completed Parquet export.

## Demographic method and coverage

- Select Census `Maale` and `Administrative Island` records. Keep Maale wards separate, because they have separate Census codes. Non-administrative islands, resorts, and industrial islands are outside this build's coverage.
- Link Census individuals to Census households internally, validate household sizes, and aggregate each locality's household age-band composition counts. Source identity fields never become output IDs.
- Expand those aggregate templates into new households and shuffle their ordering using a seed specific to each locality. Shuffle source age counts into matching age-band slots, creating new household memberships while preserving exact locality single-year ages, age-band composition counts, and household sizes.
- Assign new household/person IDs and independent fictional display names. This does not reconstruct observed individuals, familial relationships, sex, nationality, or exact-age correlations within households, and it is not a privacy guarantee for small statistical cells.

**Home island is modeled from the Census enumeration locality.** It is not the registered island, and it is not a claim of exact usual residence. The source's usual-residence labels also differ for Maale wards and some spelling variants; the report's label-difference count is not a count of migrants. Consumers needing a usual-residence population should make that a separate calibration choice, rather than silently replacing the origin field.

The supplied `mvgeo-data-main.zip` contains code and download instructions, not its published JSON datasets. Without a local geography file, Census DMS coordinates are converted to decimal degrees and `geography_id` remains null. With a local file, join only unique, consistent FCODE matches; ambiguous matches stay null. Geographic population fields never replace Census calibration totals.

## HIES economic method

- Use the **non-raised** HIES income and master-expenditure workbooks. Join only HIES records to each other using their household IDs.
- Sum the master file's already annualized `annexp` values per household and divide by 12. Do not apply recall factors again. Retain the donor's corresponding income with its spending.
- Exclude income households with no expenditure rows. Missing expenditure is not zero expenditure.
- For regular house/flat/apartment templates, select a paired donor using household selection weights, within Male or Atolls and exact household size when supported. If that size has no donors, use the nearest size within the same domain, without scaling the household amounts. The report counts fallback cases and assignments supported by fewer than five donors.
- Leave income and spending null for other housing unit types. This conservative coverage rule avoids assigning normal-household economics to labour quarters, boats, and other units. HIES has documented coverage limits for collective living and non-administrative areas; see the [official population report, page 8](https://statisticsmaldives.gov.mv/mbs/wp-content/uploads/2021/03/HIES2019-PopulationDistributionMigration.pdf).

These are modeled household values in **2019 nominal MVR**. They are not observed island incomes, current-year estimates, income minus essential costs, or travel budgets. Exact island income distributions and all household-economic correlations are not calibrated. The donor sample's finite support and nearest-size fallback are limitations retained in the manifest and report.

## Verification

```sh
python3 -m unittest discover -s tests -v
python3 -m population.validate data/cache/<population_id>-staging/preview.json
```

The standard-library tests cover spreadsheet headers/types, synthesis totals, filtering/repeatability, weighted paired economics, missing data, and cross-record references. The Parquet integration test runs when DuckDB is installed. For independent Draft 2020-12 validation, also install `jsonschema` and rerun the suite.

The simulator can query Parquet directly:

```python
import duckdb

connection = duckdb.connect()
people = connection.execute(
    "SELECT * FROM read_parquet(?) WHERE home_island_id = ?",
    ["data/generated/<population_id>/persons.parquet", "69"],
).fetchall()
```

Population groups describe residents, not healthcare demand. Appointments remain explicit scenario inputs; no fictional hospital schedule is added to the source-derived national population by default.
