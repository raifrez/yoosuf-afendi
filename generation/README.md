# Population generation project

The shared repository includes both the generated population in `../data/processed/population/` and its generation source here. DuckDB is pinned to **1.4.5**. Requires Python 3.9+ and `bsdtar` for the supplied archives.

From the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r data/requirements.txt
.venv/bin/python generation/run.py
```

This reads the original Census/HIES archives in `data/raw/archives/`, builds the deterministic population, exports typed Parquet, copies a complete snapshot into `data/processed/population/`, and runs `data/build.py` to rebuild `data/database/shared.duckdb`. It retains the previous shared Parquet snapshot if the database build fails. No transport selection or actual appointments are inferred.

The generator's extraction caches and immutable runs stay under `generation/data/` and are ignored by Git. Large original archives are local inputs excluded by `data/.gitignore`. Teammates can build the shared database from the committed processed Parquet files without the raw microdata:

```sh
.venv/bin/python data/build.py
```

For a subset, generate without replacing the nationwide shared snapshot:

```sh
.venv/bin/python generation/run.py --islands 69 745 --no-publish
```

To publish that subset intentionally, omit `--no-publish`. A different `--seed` changes assignments reproducibly. Optional `--geography` accepts downloaded local island JSON; `--name-catalog` accepts a reviewed local name list. Ordinary pipeline changes must update the algorithm fingerprint in `population/generate.py` when they change generated records.

Run the tests from this directory:

```sh
cd generation
../.venv/bin/python -m unittest discover -s tests -v
```

The wrapper uses `scenarios/daily-assumed.json` by default. It models daily
demand as 3% of residents and randomly assigns healthcare, education,
employment, or other. Override it with `--journey-scenario scenario.json`. See the
[scenario format and assumptions](docs/POPULATION_GENERATION.md#assumed-daily-journeys).
Passing `--ferry-data data/MTCC.xlsx` instead opts into the workbook's sample
ferry volumes.

See [data shapes and simulator responsibilities](docs/POPULATION_SIMULATION_CONTRACT.md) and the [generation method](docs/POPULATION_GENERATION.md). The complete example is in `examples/`; JSON Schemas are in `schemas/`.

Current generated population: **448,819 people, 90,459 households, and 578 groups** across 193 Census island/ward areas. Names and household membership are synthetic; demographic aggregates come from Census 2022, supported economics are modeled from HIES 2019. Journey requests hold 417,415 placeholder rows for October 2026 (3% of residents travel each day, with a random purpose). The simulator does not use them; it builds its own healthcare and school needs (`simulator/health.py`, `simulator/schools.py`).
