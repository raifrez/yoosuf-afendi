"""Build the shared, app-readable DuckDB snapshot from local source files."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import tempfile

import duckdb


ROOT = Path(__file__).resolve().parent


def sql_string(value):
    return "'" + str(value).replace("'", "''") + "'"


def normalized(value):
    return re.sub("[^a-z0-9]", "", value.lower())


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_id(prefix, value):
    return prefix + hashlib.sha256(value.encode()).hexdigest()[:16]


def infer_island(name, islands):
    """Map explicit whole island names, never fuzzy-match or choose an atoll capital."""
    words = re.sub("[^a-z0-9]+", " ", name.lower()).strip()
    candidates = []
    for island in islands:
        token = re.sub("[^a-z0-9]+", " ", island["name"].lower()).strip()
        if len(token) >= 4 and re.search(r"\b" + re.escape(token) + r"\b", words):
            candidates.append(island)
    # Repeated island names and Maale wards require an explicit source mapping.
    return candidates[0]["island_id"] if len(candidates) == 1 else None


def facilities(islands):
    schools = json.loads((ROOT / "raw/facilities/schools.snapshot.json").read_text())
    health = json.loads((ROOT / "raw/facilities/health_facilities.snapshot.json").read_text())
    profiles = json.loads((ROOT / "raw/facilities/school_profiles.snapshot.json").read_text())
    profile_by_key = {(r["directory_name"], r["directory_phone"]): r for r in profiles["records"]}
    island_codes = {island["island_id"] for island in islands}
    result, grades = [], []
    for record in schools["records"]:
        profile = profile_by_key.get((record["name"], record["phone"]))
        facility_id = source_id("moe-", record["name"] + "|" + str(record["phone"]))
        island_id = profile["island_id"] if profile else infer_island(record["name"], islands)
        if island_id is not None and island_id not in island_codes:
            raise ValueError(f"Unknown school island {island_id}")
        result.append({
            "facility_id": facility_id, "name": record["name"], "kind": "school",
            "facility_type": "government_school", "island_id": island_id,
            "location_match": "official_profile" if profile else "unique_name_derived" if island_id else "unresolved",
            "latitude": None, "longitude": None,
            "phone": record["phone"], "government_level_raw": None,
            "level_family": None, "level_number": None, "level_label": None,
            "registration_number": None, "license_number": None,
            "source_id": schools["source_id"], "source_as_of": schools["source_as_of"],
            "operating_status": None, "grades_status": "verified_profile_range" if profile and profile["grades"] is not None else "unknown",
            "foundation_stage": profile["foundation_stage"] if profile else None,
            "profile_source_url": profile["source_url"] if profile else None,
            "data_classification": "derived",
        })
        if profile and profile["grades"]:
            for grade in profile["grades"]:
                grades.append({"facility_id": facility_id, "grade": grade, "source_url": profile["source_url"], "source_as_of": None, "evidence": profile["grade_evidence"], "data_classification": "derived"})
    for record in health["records"]:
        code = re.sub(r"\s+", "", record["government_level"].upper()).replace("HCGR", "HCG")
        match = re.fullmatch(r"(HCG|HG)([0-9]+)", code)
        family, number = (match[1], int(match[2])) if match else (code, None)
        label = f"Hospital Grade {number}" if family == "HG" else f"Health Centre Grade {number}" if family == "HCG" else "Tertiary Hospital" if family == "T" else "General Clinic" if family == "GC" else record["government_level"]
        kind = "hospital" if family in ("HG", "T") else "health_centre" if family == "HCG" else "clinic"
        island_id = infer_island(record["name"], islands)
        result.append({
            "facility_id": source_id("moh-", record["license_number"]),
            "name": record["name"], "kind": "health", "facility_type": kind,
            "island_id": island_id, "location_match": "unique_name_derived" if island_id else "unresolved",
            "latitude": None, "longitude": None, "phone": None,
            "government_level_raw": record["government_level"], "level_family": family,
            "level_number": number, "level_label": label,
            "registration_number": record["registration_number"], "license_number": record["license_number"],
            "source_id": health["source_id"], "source_as_of": health["source_as_of"],
            "operating_status": "operating_as_of_source_date", "grades_status": None,
            "foundation_stage": None, "profile_source_url": None,
            "data_classification": "derived",
        })
    if len({r["facility_id"] for r in result}) != len(result):
        raise ValueError("Duplicate facility identifier; review source identities before importing")
    return result, grades


def build():
    output = ROOT / "database"
    output.mkdir(exist_ok=True)
    temporary = tempfile.NamedTemporaryFile(prefix=".shared-", suffix=".duckdb", dir=output, delete=False)
    path = Path(temporary.name)
    temporary.close()
    path.unlink()  # DuckDB creates its own database file.
    connection = None
    try:
        connection = duckdb.connect(str(path))
        for schema in ("geo", "population", "services", "transport", "meta"):
            connection.execute(f"CREATE SCHEMA {schema}")
        population_root = ROOT / "processed/population"
        for table in ("islands", "households", "persons", "population_groups", "journey_requests"):
            schema = "geo" if table == "islands" else "population"
            connection.execute(f"CREATE TABLE {schema}.{table} AS SELECT * FROM read_parquet(?)", [str(population_root / (table + ".parquet"))])
        connection.execute("CREATE TABLE geo.atolls AS SELECT atoll_code, count(*) census_areas FROM geo.islands GROUP BY atoll_code")
        records = connection.execute("SELECT island_id, name, atoll_code FROM geo.islands").fetchall()
        islands = [dict(zip(("island_id", "name", "atoll_code"), r)) for r in records]
        facility_rows, grade_rows = facilities(islands)
        processed = ROOT / "processed/facilities"
        processed.mkdir(parents=True, exist_ok=True)
        facility_json, grade_json = processed / "facilities.json", processed / "school_grades.json"
        facility_json.write_text(json.dumps(facility_rows, ensure_ascii=False, indent=2) + "\n")
        grade_json.write_text(json.dumps(grade_rows, ensure_ascii=False, indent=2) + "\n")
        columns = {
            "facility_id": "VARCHAR", "name": "VARCHAR", "kind": "VARCHAR", "facility_type": "VARCHAR", "island_id": "VARCHAR", "location_match": "VARCHAR", "latitude": "DOUBLE", "longitude": "DOUBLE", "phone": "VARCHAR", "government_level_raw": "VARCHAR", "level_family": "VARCHAR", "level_number": "INTEGER", "level_label": "VARCHAR", "registration_number": "VARCHAR", "license_number": "VARCHAR", "source_id": "VARCHAR", "source_as_of": "DATE", "operating_status": "VARCHAR", "grades_status": "VARCHAR", "foundation_stage": "BOOLEAN", "profile_source_url": "VARCHAR", "data_classification": "VARCHAR",
        }
        struct = "{" + ",".join(sql_string(key) + ":" + sql_string(value) for key, value in columns.items()) + "}"
        connection.execute(f"CREATE TABLE services.facilities AS SELECT * FROM read_json(?, format='array', columns={struct})", [str(facility_json)])
        connection.execute("CREATE TABLE services.school_grades AS SELECT * FROM read_json(?, format='array', columns={facility_id:'VARCHAR', grade:'VARCHAR', source_url:'VARCHAR', source_as_of:'DATE', evidence:'VARCHAR', data_classification:'VARCHAR'})", [str(grade_json)])
        for view, predicate in {"schools": "kind='school'", "health_facilities": "kind='health'", "hospitals": "kind='health' AND facility_type='hospital'", "health_centres": "kind='health' AND facility_type='health_centre'"}.items():
            connection.execute(f"CREATE VIEW services.{view} AS SELECT * FROM services.facilities WHERE {predicate}")
        connection.execute("CREATE VIEW services.facility_island_points AS SELECT f.*, i.latitude island_reference_latitude, i.longitude island_reference_longitude FROM services.facilities f LEFT JOIN geo.islands i ON f.island_id=i.island_id")
        # These empty tables declare gaps; they are not sourced schedules or zero-service evidence.
        empty_tables = {
            "transport.terminals": "terminal_id VARCHAR, island_id VARCHAR, name VARCHAR, latitude DOUBLE, longitude DOUBLE, source_id VARCHAR",
            "transport.routes": "route_id VARCHAR, name VARCHAR, mode VARCHAR, source_id VARCHAR",
            "transport.trips": "trip_id VARCHAR, route_id VARCHAR, operating_date DATE, fare_mvr DECIMAL(18,2), source_id VARCHAR",
            "transport.trip_stops": "trip_id VARCHAR, stop_sequence INTEGER, terminal_id VARCHAR, arrival_time TIME, departure_time TIME",
            "transport.transfers": "from_terminal_id VARCHAR, to_facility_id VARCHAR, duration_minutes INTEGER, source_id VARCHAR, data_classification VARCHAR",
            "services.facility_services": "facility_id VARCHAR, service_code VARCHAR, source_id VARCHAR, source_as_of DATE",
            "services.facility_hours": "facility_id VARCHAR, operating_date DATE, opens_at TIME, closes_at TIME, source_id VARCHAR",
        }
        for table, fields in empty_tables.items():
            connection.execute(f"CREATE TABLE {table} ({fields})")
        catalog = json.loads((ROOT / "catalog.json").read_text())
        for source in catalog["sources"]:
            source_path = ROOT / source["local_path"] if source.get("local_path") else None
            if source_path and source_path.exists():
                if source.get("sha256") and file_hash(source_path) != source["sha256"]:
                    raise ValueError(f"Source checksum mismatch: {source['source_id']}")
        connection.execute("CREATE TABLE meta.sources (source_id VARCHAR, publisher VARCHAR, source_url VARCHAR, source_as_of DATE, local_path VARCHAR, sha256 VARCHAR, availability VARCHAR, caveats VARCHAR)")
        connection.executemany("INSERT INTO meta.sources VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [[source.get(key) for key in ("source_id", "publisher", "source_url", "source_as_of", "local_path", "sha256", "availability", "caveats")] for source in catalog["sources"]])
        connection.execute("CREATE TABLE meta.population_manifest (manifest_json JSON)")
        connection.execute("INSERT INTO meta.population_manifest VALUES (?)", [(population_root / "manifest.json").read_text()])
        connection.execute("CREATE TABLE meta.datasets (dataset_name VARCHAR, row_count BIGINT, availability VARCHAR, caveats VARCHAR)")
        tables = ["geo.islands", "geo.atolls", *["population." + table for table in ("persons", "households", "population_groups", "journey_requests")], "services.facilities", "services.schools", "services.health_facilities", "services.hospitals", "services.health_centres", "services.school_grades", *empty_tables]
        counts = {}
        for table in tables:
            count = connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            counts[table] = count
            missing = table in empty_tables or table == "population.journey_requests"
            connection.execute("INSERT INTO meta.datasets VALUES (?, ?, ?, ?)", [table, count, "not_sourced" if missing else "available", "Empty: not evidence of zero services or demand." if missing else "See catalog and source dates; facility mappings and school grade coverage are partial."])
        assert counts["services.schools"] == len(json.loads((ROOT / "raw/facilities/schools.snapshot.json").read_text())["records"])
        assert counts["services.health_facilities"] == len(json.loads((ROOT / "raw/facilities/health_facilities.snapshot.json").read_text())["records"])
        assert connection.execute("SELECT count(*) FROM services.facilities f LEFT JOIN geo.islands i ON f.island_id=i.island_id WHERE f.island_id IS NOT NULL AND i.island_id IS NULL").fetchone()[0] == 0
        assert connection.execute("SELECT count(*)=count(DISTINCT facility_id) FROM services.facilities").fetchone()[0]
        assert connection.execute("SELECT count(*) FROM services.school_grades g LEFT JOIN services.schools s USING(facility_id) WHERE s.facility_id IS NULL").fetchone()[0] == 0
        for table in ("facilities", "school_grades"):
            connection.execute(f"COPY services.{table} TO {sql_string(processed / (table + '.parquet'))} (FORMAT PARQUET, COMPRESSION ZSTD)")
        report = {"duckdb_version": duckdb.__version__, "counts": counts, "location_matches": dict(Counter(r["location_match"] for r in facility_rows)), "school_grade_coverage": "One profile has a verified numeric grade range; other schools remain unknown until sourced.", "checks": {"source_checksums": True, "unique_facility_ids": True, "facility_island_references": True, "school_grade_references": True}, "intended_destination": "/Users/shaaik/projects/yoosuf-afendi/data"}
        connection.close()
        connection = None
        path.replace(output / "shared.duckdb")
        (ROOT / "build_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        if connection is not None:
            connection.close()
        path.unlink(missing_ok=True)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    build()
