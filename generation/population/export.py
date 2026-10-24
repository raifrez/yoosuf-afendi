"""Export validated population staging to typed Parquet and a DuckDB database."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from .generate import TABLE_TYPES


def sql_string(value):
    return "'" + str(value).replace("'", "''") + "'"


def export_run(staging, output):
    try:
        import duckdb
    except ImportError as error:
        raise RuntimeError(
            "DuckDB is not installed. Install with .venv/bin/python -m pip install duckdb, "
            "then run .venv/bin/python -m population.export " + str(staging)
        ) from error
    staging, output = Path(staging).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError(f"Output already exists; refusing to change an immutable run: {output}")
    manifest = json.loads((staging / "manifest.json").read_text())
    report = json.loads((staging / "generation_report.json").read_text())
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".population-export-", dir=output.parent))
    connection = None
    try:
        connection = duckdb.connect(str(temporary / "population.duckdb"))
        connection.execute("SET threads = 4")
        for table, types in TABLE_TYPES.items():
            path = staging / (table + ".csv")
            columns = "{" + ", ".join(sql_string(name) + ": 'VARCHAR'" for name in types) + "}"
            casts = ", ".join(f'CAST("{column}" AS {datatype}) AS "{column}"' for column, datatype in types.items())
            connection.execute(
                f"CREATE TABLE {table} AS SELECT {casts} FROM read_csv(?, header=true, columns={columns}, nullstr='\\N')",
                [str(path)],
            )

        checks = {
            "unique_island_ids": "SELECT count(*) = count(DISTINCT island_id) FROM islands",
            "unique_household_ids": "SELECT count(*) = count(DISTINCT household_id) FROM households",
            "unique_person_ids": "SELECT count(*) = count(DISTINCT person_id) FROM persons",
            "unique_group_ids": "SELECT count(*) = count(DISTINCT group_id) FROM population_groups",
            "unique_request_ids": "SELECT count(*) = count(DISTINCT journey_request_id) FROM journey_requests",
            "household_membership_matches": "SELECT count(*) = 0 FROM households h LEFT JOIN (SELECT household_id, count(*) n FROM persons GROUP BY household_id) p USING (household_id) WHERE h.household_size <> coalesce(p.n, 0)",
            "group_weights_match": "SELECT count(*) = 0 FROM population_groups g LEFT JOIN (SELECT group_id, sum(population_weight) n FROM persons GROUP BY group_id) p USING (group_id) WHERE g.population_weight <> coalesce(p.n, 0)",
            "all_person_references_match": "SELECT count(*) = 0 FROM persons p LEFT JOIN households h USING (household_id) LEFT JOIN population_groups g USING (group_id) LEFT JOIN islands i ON p.home_island_id = i.island_id WHERE h.household_id IS NULL OR g.group_id IS NULL OR i.island_id IS NULL OR p.home_island_id <> h.home_island_id OR p.home_island_id <> g.home_island_id OR p.age_group <> g.age_group",
            "all_household_islands_exist": "SELECT count(*) = 0 FROM households h LEFT JOIN islands i ON h.home_island_id = i.island_id WHERE i.island_id IS NULL",
            "all_group_islands_exist": "SELECT count(*) = 0 FROM population_groups g LEFT JOIN islands i ON g.home_island_id = i.island_id WHERE i.island_id IS NULL",
            "age_groups_match": "SELECT count(*) = 0 FROM persons WHERE age_group <> CASE WHEN age IS NULL THEN 'unknown' WHEN age < 18 THEN '0_17' WHEN age < 65 THEN '18_64' ELSE '65_plus' END",
            "individual_weights_are_one": "SELECT count(*) = 0 FROM persons WHERE population_weight <> 1",
            "unavailable_economics_are_null": "SELECT count(*) = 0 FROM households WHERE economic_assignment = 'unavailable' AND (monthly_income_mvr IS NOT NULL OR monthly_expenditure_mvr IS NOT NULL)",
            "request_origins_match": "SELECT count(*) = 0 FROM journey_requests r LEFT JOIN persons p USING (person_id) WHERE p.person_id IS NULL OR r.origin_island_id <> p.home_island_id",
            "request_destinations_match_purpose": "SELECT count(*) = 0 FROM journey_requests WHERE (destination_facility_id IS NULL) = (destination_facility_type IS NULL) OR (destination_facility_type IS NOT NULL AND NOT ((purpose = 'healthcare' AND destination_facility_type IN ('hospital', 'health_centre', 'clinic')) OR (purpose = 'education' AND destination_facility_type = 'government_school') OR (purpose = 'employment' AND destination_facility_type = 'workplace') OR (purpose = 'other' AND destination_facility_type = 'other')))",
        }
        for name, query in checks.items():
            passed = connection.execute(query).fetchone()[0]
            if not passed:
                raise ValueError(f"Generated database failed check: {name}")
            report["checks"][name] = True
        for area in report["calibration"]:
            counts = connection.execute("SELECT (SELECT count(*) FROM persons WHERE home_island_id = ?), (SELECT count(*) FROM households WHERE home_island_id = ?)", [area["island_id"], area["island_id"]]).fetchone()
            if counts != (area["source_people"], area["source_households"]):
                raise ValueError(f"Source calibration mismatch for island {area['island_id']}")
        report["checks"]["parquet_source_calibration_matches"] = True
        report["storage"] = {"duckdb_version": duckdb.__version__, "parquet_compression": "ZSTD", "tables": {}}
        for table, types in TABLE_TYPES.items():
            destination = temporary / (table + ".parquet")
            first = next(iter(types))
            order = f'"{first}"' if table == "islands" else f'home_island_id, "{first}"' if "home_island_id" in types else f'"{first}"'
            connection.execute(f"COPY (SELECT * FROM {table} ORDER BY {order}) TO {sql_string(destination)} (FORMAT PARQUET, COMPRESSION ZSTD)")
            count = connection.execute(f"SELECT count(*) FROM read_parquet({sql_string(destination)})").fetchone()[0]
            if count != report["counts"][table]:
                raise ValueError(f"Parquet row count mismatch for {table}")
            # Check exported values, not only file presence or row counts.
            mismatch = connection.execute(f"SELECT count(*) FROM ((SELECT * FROM {table} EXCEPT ALL SELECT * FROM read_parquet({sql_string(destination)})) UNION ALL (SELECT * FROM read_parquet({sql_string(destination)}) EXCEPT ALL SELECT * FROM {table}))").fetchone()[0]
            if mismatch:
                raise ValueError(f"Parquet round-trip mismatch for {table}")
            report["storage"]["tables"][table] = {"rows": count, "bytes": destination.stat().st_size}
        report["checks"]["parquet_roundtrip_matches"] = True
        connection.execute("CREATE TABLE generation_metadata (manifest_json JSON)")
        connection.execute("INSERT INTO generation_metadata VALUES (?)", [json.dumps(manifest, ensure_ascii=False)])
        connection.close()
        connection = None
        for name in ("manifest.json", "preview.json"):
            shutil.copyfile(staging / name, temporary / name)
        (temporary / "generation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        temporary.rename(output)
        return output
    finally:
        if connection is not None:
            connection.close()
        if temporary.exists():
            shutil.rmtree(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("staging", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.staging / "manifest.json").read_text())
    output = args.output or Path("data/generated") / manifest["population_id"]
    try:
        print(export_run(args.staging, output))
    except (RuntimeError, ValueError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
