"""Build a reproducible population from Census aggregates and weighted HIES donors."""

import argparse
from bisect import bisect_left
from collections import Counter, defaultdict
import csv
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import math
from pathlib import Path
import random
import re
import shutil
import tempfile

from .names import NameGenerator
from .prepare import SOURCES, prepare, sha256
from .validate import SchemaChecker, age_group_for, validate_bundle
from .xlsx import rows
from .ferry import allocate_volumes, ferry_volumes, journey_rows, load_scenario
from .demand import daily_allocations, daily_journey_rows, PURPOSES


AGE_GROUPS = ("0_17", "18_64", "65_plus", "unknown")
INHABITED_TYPES = {"Maale", "Administrative Island"}
NULL = "\\N"
TABLE_TYPES = {
    "islands": {"island_id": "VARCHAR", "name": "VARCHAR", "atoll_code": "VARCHAR", "geography_id": "VARCHAR", "latitude": "DOUBLE", "longitude": "DOUBLE", "data_classification": "VARCHAR"},
    "households": {"household_id": "VARCHAR", "home_island_id": "VARCHAR", "household_size": "INTEGER", "monthly_income_mvr": "DECIMAL(18,2)", "monthly_expenditure_mvr": "DECIMAL(18,2)", "economic_assignment": "VARCHAR", "data_classification": "VARCHAR"},
    "persons": {"person_id": "VARCHAR", "display_name": "VARCHAR", "name_is_synthetic": "BOOLEAN", "household_id": "VARCHAR", "home_island_id": "VARCHAR", "age": "INTEGER", "age_group": "VARCHAR", "group_id": "VARCHAR", "population_weight": "BIGINT", "data_classification": "VARCHAR"},
    "population_groups": {"group_id": "VARCHAR", "label": "VARCHAR", "home_island_id": "VARCHAR", "age_group": "VARCHAR", "population_weight": "BIGINT", "data_classification": "VARCHAR"},
    "journey_requests": {"journey_request_id": "VARCHAR", "person_id": "VARCHAR", "purpose": "VARCHAR", "origin_island_id": "VARCHAR", "destination_facility_id": "VARCHAR", "destination_facility_type": "VARCHAR", "date": "DATE", "appointment_time": "TIME", "activity_duration_minutes": "INTEGER", "return_home_by": "TIME", "timezone": "VARCHAR", "data_classification": "VARCHAR"},
}


def stable_int(seed, *parts):
    payload = json.dumps([seed, *parts], ensure_ascii=False, separators=(",", ":"))
    return int.from_bytes(hashlib.sha256(payload.encode()).digest(), "big")


def decimal_or_none(value):
    try:
        number = Decimal(value)
        return number if number.is_finite() else None
    except (ValueError, ArithmeticError):
        return None


def coordinate(value):
    """Accept decimal degrees or Census DMS, returning null for unavailable data."""
    if not value:
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except ValueError:
        match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)°\s*(\d+(?:\.\d+)?)\x27\s*(\d+(?:\.\d+)?)"\s*([NSEW])\s*', value)
        if not match:
            raise ValueError(f"Unsupported Census coordinate {value!r}")
        degrees, minutes, seconds = (float(x) for x in match.groups()[:3])
        if minutes >= 60 or seconds >= 60:
            raise ValueError("Invalid DMS coordinate")
        return round((degrees + minutes / 60 + seconds / 3600) * (-1 if match[4] in "SW" else 1), 8)


def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8") as source:
        yield from csv.DictReader(source)


def geography_index(path):
    if path is None:
        return {}
    payload = json.loads(Path(path).read_text())
    records = payload["islands"] if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError("Geography JSON must be a list or an object with an islands list")
    result = defaultdict(list)
    for record in records:
        if record.get("fcode"):
            result[record["fcode"]].append(record)
    return result


def census_profiles(paths, island_filter=None, geography=None):
    """Aggregate source households; source IDs never leave these internal profiles."""
    dictionary = {}
    for row in rows(paths["census_dictionary"], sheet="island_code"):
        try:
            code = str(int(row.get("island_code", "")))
        except ValueError:
            continue
        dictionary[code] = row["value label"]
    geo = geography_index(geography)
    islands, households = {}, {}
    source_counts = Counter()
    for row in read_csv(paths["census_households"]):
        source_counts["all_households"] += 1
        source_counts["all_reported_people"] += int(row["no_of_ppl"])
        if row["island_type"] not in INHABITED_TYPES:
            continue
        if not re.fullmatch(r"LD[0-9]+", row["fcode"]):
            raise ValueError("Administrative Census household has an unrecognized FCODE")
        code = str(int(row["fcode"][2:]))
        if code not in dictionary:
            raise ValueError(f"Census FCODE has no island dictionary entry: {row['fcode']}")
        if island_filter is not None and code not in island_filter:
            continue
        if row["unit__id"] in households:
            raise ValueError("Duplicate Census household ID")
        size = int(row["no_of_ppl"])
        if size <= 0:
            raise ValueError("Census household has no members")
        households[row["unit__id"]] = {
            "island": code, "size": size, "counts": Counter(),
            "economic_eligible": row["unit_type"] == "House/flat/apartment",
        }
        record = {
            "island_id": code,
            "name": dictionary[code].split(".", 1)[-1],
            "atoll_code": row["atoll_code"],
            "geography_id": None,
            "latitude": coordinate(row["latitude"]),
            "longitude": coordinate(row["longitude"]),
            "data_classification": "derived",
        }
        candidates = geo.get(row["fcode"], [])
        # Reused geographic FCODEs are deliberately left unresolved.
        if len(candidates) == 1:
            match = candidates[0]
            if match.get("island_code") is not None and str(int(match["island_code"])) != code:
                raise ValueError(f"Conflicting geography code for {row['fcode']}")
            record["geography_id"] = match["id"]
        if code in islands and islands[code] != record:
            raise ValueError(f"Inconsistent Census island coordinates or codes for {code}")
        islands[code] = record
    if island_filter is not None and island_filter - set(islands):
        raise ValueError(f"Unknown or excluded island IDs: {sorted(island_filter - set(islands))}")
    histograms = defaultdict(Counter)
    source_people_by_island = Counter()
    member_ids = set()
    usual_residence_label_differences = 0
    for row in read_csv(paths["census_persons"]):
        source_counts["all_persons"] += 1
        household = households.get(row["unit__id"])
        if household is None:
            continue
        key = (row["unit__id"], row["ind__id"])
        if key in member_ids:
            raise ValueError("Duplicate Census member within a household")
        member_ids.add(key)
        if row["fcode"] != f"LD{int(household['island']):04d}":
            raise ValueError("Census person/household island mismatch")
        value = decimal_or_none(row["age"])
        age = int(value) if value is not None and value >= 0 and value % 1 == 0 else None
        group = age_group_for(age)
        household["counts"][group] += 1
        histograms[(household["island"], group)][age] += 1
        source_people_by_island[household["island"]] += 1
        usual_residence_label_differences += row["island_code"] != row["usual_residence"]
    templates = defaultdict(Counter)
    size_histograms = defaultdict(Counter)
    for household in households.values():
        if sum(household["counts"].values()) != household["size"]:
            raise ValueError("Census household member count does not match household file")
        composition = tuple(household["counts"][group] for group in AGE_GROUPS)
        templates[household["island"]][(household["economic_eligible"], composition)] += 1
        size_histograms[household["island"]][household["size"]] += 1
    return {
        "islands": islands, "templates": templates, "age_histograms": histograms,
        "size_histograms": size_histograms, "people_by_island": source_people_by_island,
        "source_counts": dict(source_counts), "selected_households": len(households),
        "usual_residence_label_differences": usual_residence_label_differences,
    }


class EconomicDonors:
    """Draw an income/expenditure pair using the household survey selection weight."""

    def __init__(self, paths):
        expenditure = defaultdict(Decimal)
        expense_rows = Counter()
        for row in read_csv(paths["hies_expenditure"]):
            value = decimal_or_none(row["annexp"])
            if value is None:
                raise ValueError("Invalid HIES annualized expenditure")
            expenditure[row["uqhh__id"]] += value
            expense_rows[row["uqhh__id"]] += 1
        by_pool = defaultdict(list)
        self.report = Counter()
        seen = set()
        for row in read_csv(paths["hies_income"]):
            source_id = row["uqhh__id"]
            if source_id in seen:
                raise ValueError("Duplicate HIES income household ID")
            seen.add(source_id)
            self.report["income_households"] += 1
            if not expense_rows[source_id]:
                self.report["excluded_missing_expenditure"] += 1
                continue
            income, weight = decimal_or_none(row["totalIncome"]), decimal_or_none(row["wgt"])
            size = int(row["hhsize"])
            annual_expense = expenditure[source_id]
            if income is None or weight is None or weight <= 0 or size <= 0 or annual_expense < 0:
                raise ValueError("Invalid HIES donor income, expenditure, weight or size")
            domain = "male" if row["maleatoll"] == "Male" else "atolls" if row["maleatoll"] in ("Atoll", "Atolls") else None
            if domain is None:
                raise ValueError(f"Unknown HIES domain {row['maleatoll']!r}")
            by_pool[(domain, size)].append((source_id, income, annual_expense / 12, weight))
        self.pools = {}
        for key, donors in by_pool.items():
            cumulative, records, total = [], [], Decimal(0)
            for _, income, expense, weight in sorted(donors):
                total += weight
                cumulative.append(total)
                records.append((income, expense))
            self.pools[key] = (cumulative, records)
            self.report["eligible_paired_donors"] += len(records)

    def choose(self, domain, household_size, seed, household_id):
        sizes = [size for candidate_domain, size in self.pools if candidate_domain == domain]
        if not sizes:
            return None
        donor_size = household_size if household_size in sizes else min(sizes, key=lambda size: (abs(size - household_size), size))
        cumulative, records = self.pools[(domain, donor_size)]
        # An integer-derived Decimal draw avoids global RNG and floating-point CDFs.
        fraction = Decimal(stable_int(seed, "economics", household_id)) / Decimal(2 ** 256)
        index = min(bisect_left(cumulative, fraction * cumulative[-1]), len(records) - 1)
        income, expense = records[index]
        money = lambda value: value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return money(income), money(expense), donor_size, len(records)


def make_manifest(population_id, seed, names, geography=None):
    source_rows = []
    for key, (archive, member, _, _) in SOURCES.items():
        if key.startswith("hies_"):
            member = "Dataset/HIES2019_EXCEL format/Non-Raised_Dataset.7z!" + member
        source_rows.append({
            "source_id": key, "publisher": "Maldives Bureau of Statistics",
            "file": archive + "!" + member,
            "reference_year": 2019 if key.startswith("hies") else 2022,
            "data_classification": "observed",
            "caveats": "Source records remain in the local preparation cache; exports contain aggregate-derived synthetic records. HIES economic assignment is modeled, not an identity join.",
        })
    if geography:
        source_rows.append({"source_id": "local_geography", "publisher": "mvgeo-data / Maldives Bureau of Statistics", "file": str(geography), "reference_year": None, "data_classification": "derived", "caveats": "Local downloaded snapshot; map only unique matching FCODEs with consistent Census codes. Geography population values are not used."})
    assumptions = [
        "Coverage is Census Maale and Administrative Island areas; non-administrative islands, including resorts/industrial islands, are excluded. Maale wards remain separate Census origins.",
        "Modeled home island is the Census enumeration locality, not registered address or a claim of exact usual residence. Some usual-residence labels differ because of ward naming or mobility.",
        "Synthetic households reproduce each island's household age-band composition counts and size distribution. Ages are shuffled among age-band slots, preserving exact island single-year-age totals; observed identities and household IDs are not exported.",
        "Household relationships, sex, nationality, disability and within-household exact-age correlations are not synthesized in schema 1.0. This is not a calibrated model of those attributes.",
        "Economics apply only to regular house/flat/apartment templates. Other housing units have null income and expenditure. HIES covers normal housing and has limits for collective and non-administrative populations.",
        "HIES donor pairs are selected with household survey weights within Male/Atolls and exact household size where available. Missing exact sizes use nearest size in the same domain without scaling; limited donor support is reported.",
        "Monthly expenditure is sum(annexp)/12 from the non-raised item-level master expenditure file. Do not annualize again or multiply amounts by selection weights. Donors without expenditure rows are excluded, not treated as zero spending.",
        "Income and expenditure are modeled in 2019 nominal MVR, with no inflation or population-year projection. No observed island income estimates, affordability limits, or actual appointments are inferred.",
        "Journey requests are empty until an explicit scenario supplies destinations and appointment rules. The simulator chooses transport and routes.",
        "Display names are fictional labels from the versioned starter catalog; names can repeat and imply no source identity, sex or nationality.",
    ]
    if geography is None:
        assumptions.append("No downloaded geography JSON was supplied. Census dictionary names and Census island coordinates are used; geography_id remains null. The repository ZIP contains downloader code, not the published JSON datasets.")
    return {
        "schema_version": "1.0", "population_id": population_id, "synthetic": True,
        "data_classification": "assumed", "demographic_reference_year": 2022,
        "economic_reference_year": 2019, "currency": "MVR", "economic_period": "month",
        "seed": seed, "name_catalog_version": names.catalog_version,
        "name_catalog_sha256": names.catalog_sha256, "sources": source_rows,
        "assumptions": assumptions,
    }


def write_staging(directory, profiles, donors, seed, manifest, schemas, names, journey_scenario=None, journey_counts=None):
    """Write bounded-memory CSV staging, validating each generated record."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    checker = SchemaChecker(schemas)
    checker.check(manifest, checker.schemas["generation_metadata.schema.json"])
    handles, writers = {}, {}
    for table, types in TABLE_TYPES.items():
        handle = (directory / (table + ".csv")).open("w", newline="", encoding="utf-8")
        handles[table] = handle
        writers[table] = csv.DictWriter(handle, fieldnames=list(types))
        writers[table].writeheader()
    preview = {"metadata": dict(manifest, population_id=manifest["population_id"] + "-preview"), **{table: [] for table in TABLE_TYPES}}
    preview["metadata"]["assumptions"] = list(manifest["assumptions"]) + ["This preview is a small complete-household subset; its counts are not national or island population totals."]
    report = {"counts": Counter(), "economics": Counter(), "calibration": [], "checks": {}}
    generated_ages = defaultdict(Counter)

    def write(table, record, include_preview=False):
        checker.check(record, checker.schemas[table + ".schema.json"])
        writers[table].writerow({key: NULL if value is None else value for key, value in record.items()})
        report["counts"][table] += 1
        if table == "journey_requests":
            report.setdefault("journey_purpose_counts", Counter())[record["purpose"]] += 1
            if record["destination_facility_type"] is not None:
                report.setdefault("destination_facility_type_counts", Counter())[record["destination_facility_type"]] += 1
        if include_preview:
            preview[table].append(record)

    try:
        for code in sorted(profiles["islands"], key=int):
            island = profiles["islands"][code]
            write("islands", island)
            template_pool = []
            for template, count in sorted(profiles["templates"][code].items()):
                template_pool.extend([template] * count)
            rng = random.Random(stable_int(seed, "households", code))
            rng.shuffle(template_pool)
            age_pools = {}
            for group in AGE_GROUPS:
                pool = []
                for age, count in sorted(profiles["age_histograms"][(code, group)].items(), key=lambda item: -1 if item[0] is None else item[0]):
                    pool.extend([age] * count)
                random.Random(stable_int(seed, "ages", code, group)).shuffle(pool)
                age_pools[group] = pool
            island_group_counts = Counter()
            island_people = []
            for sequence, (economic_eligible, composition) in enumerate(template_pool, 1):
                household_id = f"hh-{code}-{sequence:06d}"
                size = sum(composition)
                pair = donors.choose("male" if island["atoll_code"] == "MLE" else "atolls", size, seed, household_id) if economic_eligible else None
                if pair:
                    income, expense, donor_size, support = pair
                    report["economics"]["modeled_households"] += 1
                    report["economics"]["nearest_size_fallback_households"] += donor_size != size
                    report["economics"]["households_with_fewer_than_5_donors"] += support < 5
                else:
                    income = expense = None
                    report["economics"]["unavailable_households"] += 1
                household = {
                    "household_id": household_id, "home_island_id": code, "household_size": size,
                    "monthly_income_mvr": income, "monthly_expenditure_mvr": expense,
                    "economic_assignment": "hies_modeled" if pair else "unavailable",
                    "data_classification": "assumed" if pair else "derived",
                }
                sample = len(preview["households"]) < 8 and size <= 12
                write("households", household, sample)
                members = [age_pools[group].pop() for group, count in zip(AGE_GROUPS, composition) for _ in range(count)]
                random.Random(stable_int(seed, "member_order", household_id)).shuffle(members)
                for member, age in enumerate(members, 1):
                    person_id = f"person-{code}-{sequence:06d}-{member:03d}"
                    group = age_group_for(age)
                    record = {
                        "person_id": person_id, "display_name": names.display_name(person_id),
                        "name_is_synthetic": True, "household_id": household_id,
                        "home_island_id": code, "age": age, "age_group": group,
                        "group_id": f"grp-{code}-{group}", "population_weight": 1,
                        "data_classification": "derived",
                    }
                    write("persons", record, sample)
                    if journey_scenario:
                        island_people.append(person_id)
                    generated_ages[(code, group)][age] += 1
                    island_group_counts[group] += 1
            if any(age_pools.values()):
                raise ValueError(f"Unallocated ages on island {code}")
            if journey_scenario and journey_counts.get(code, 0):
                if journey_scenario.get("model", "ferry") == "population_daily":
                    requests = daily_journey_rows(code, island_people, journey_counts[code], journey_scenario, seed)
                else:
                    scenario = dict(journey_scenario, destination_facility_id=journey_scenario["destinations"][island["atoll_code"]])
                    requests = journey_rows(code, island_people, journey_counts[code], scenario, seed)
                preview_people = {person["person_id"] for person in preview["persons"]}
                for request in requests:
                    write("journey_requests", request, request["person_id"] in preview_people)
            for group, count in sorted(island_group_counts.items()):
                label = {"0_17": "aged 0–17", "18_64": "aged 18–64", "65_plus": "aged 65+", "unknown": "with unknown age"}[group]
                write("population_groups", {"group_id": f"grp-{code}-{group}", "label": f"{island['name']} residents {label}", "home_island_id": code, "age_group": group, "population_weight": count, "data_classification": "derived"})
            report["calibration"].append({"island_id": code, "name": island["name"], "source_people": profiles["people_by_island"][code], "generated_people": sum(island_group_counts.values()), "source_households": sum(profiles["templates"][code].values()), "generated_households": len(template_pool)})
        if any(generated_ages[key] != counter for key, counter in profiles["age_histograms"].items()):
            raise ValueError("Generated single-year-age totals do not match Census")
    finally:
        for handle in handles.values():
            handle.close()
    selected_islands = {person["home_island_id"] for person in preview["persons"]}
    preview["islands"] = [profiles["islands"][code] for code in sorted(selected_islands, key=int)]
    preview_counts = Counter((person["home_island_id"], person["age_group"], person["group_id"]) for person in preview["persons"])
    for (code, group, group_id), count in sorted(preview_counts.items()):
        preview["population_groups"].append({"group_id": group_id, "label": f"{profiles['islands'][code]['name']} preview {group}", "home_island_id": code, "age_group": group, "population_weight": count, "data_classification": "derived"})
    validate_bundle(preview, schemas)
    report["counts"].setdefault("journey_requests", 0)
    report["checks"] = {"all_rows_pass_schema": True, "single_year_age_totals_match": True, "household_composition_counts_match": True, "preview_passes_contract": True}
    return report, preview


def json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(type(value).__name__)


def dump_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, default=json_default) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--source-dir", type=Path, help="Original archive directory; defaults to --root")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--islands", nargs="+", help="Canonical Census island codes; default all inhabited Census areas")
    parser.add_argument("--geography", type=Path, help="Previously downloaded local islands.json")
    parser.add_argument("--name-catalog", type=Path)
    parser.add_argument("--ferry-data", type=Path, help="Opt into sample ferry volumes instead of 3%% daily population demand; requires --journey-scenario")
    parser.add_argument("--journey-scenario", type=Path, help="Monthly destination/time assumptions; defaults to 3%% daily demand with uniformly random purposes")
    parser.add_argument("--stage-only", action="store_true", help="Prepare validated CSV staging without DuckDB export")
    args = parser.parse_args(argv)
    if args.ferry_data and not args.journey_scenario:
        parser.error("--ferry-data requires --journey-scenario")
    scenario = load_scenario(args.journey_scenario, "ferry" if args.ferry_data else "population_daily") if args.journey_scenario else None
    root = args.root.resolve()
    paths, source_hashes = prepare(root, source_dir=args.source_dir)
    names = NameGenerator(args.seed, args.name_catalog)
    selected = set(args.islands) if args.islands else None
    print("Building aggregate Census household templates and age totals...", flush=True)
    profiles = census_profiles(paths, None if scenario else selected, args.geography)
    journey_counts = None
    ferry_totals = None
    if scenario:
        if selected is not None and selected - profiles["islands"].keys():
            raise ValueError(f"Unknown or excluded island IDs: {sorted(selected - profiles['islands'].keys())}")
        if args.ferry_data:
            ferry_totals = ferry_volumes(args.ferry_data, scenario["month"])
            journey_counts = allocate_volumes(ferry_totals, profiles["islands"], profiles["people_by_island"])
        else:
            journey_counts = daily_allocations(dict(profiles["people_by_island"]))
        if args.ferry_data:
            generated_codes = selected if selected is not None else journey_counts.keys()
            required_atolls = {profiles["islands"][code]["atoll_code"] for code in generated_codes if journey_counts.get(code, 0)}
            if required_atolls - scenario["destinations"].keys():
                raise ValueError(f"Scenario missing destinations for {sorted(required_atolls - scenario['destinations'].keys())}")
        if selected is not None:
            profiles = census_profiles(paths, selected, args.geography)
    print("Building paired weighted HIES donor pools...", flush=True)
    donors = EconomicDonors(paths)
    fingerprint = {"sources": source_hashes, "seed": args.seed, "islands": sorted(selected) if selected is not None else "inhabited", "names": names.catalog_sha256, "geography": sha256(args.geography) if args.geography else None, "algorithm": "aggregate-households-v1"}
    if scenario:
        fingerprint.update(ferry_data=sha256(args.ferry_data) if args.ferry_data else None, journey_scenario=scenario, algorithm="aggregate-households-demand-v3")
    suffix = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()[:12]
    population_id = f"population-2022-seed{args.seed}-{suffix}"
    manifest = make_manifest(population_id, args.seed, names, args.geography)
    if scenario:
        manifest["assumptions"] = [item for item in manifest["assumptions"] if not item.startswith("Journey requests are empty")]
        if args.ferry_data:
            manifest["data_classification"] = "demo"
            manifest["sources"].append({"source_id": "mtcc_sample_ferry", "publisher": "Local sample workbook (not observed MTCC statistics)", "file": str(args.ferry_data), "reference_year": int(scenario["month"][:4]), "data_classification": "demo", "caveats": "Workbook README: randomly generated passenger figures; partial route coverage. Counts are boardings, not unique travelers or observed origins."})
            manifest["assumptions"].extend([
                "Demo journeys match summed monthly ferry route boardings, allocated to islands by Census population using largest remainders. Combined Gaafu Alifu/Dhaalu counts are split by population; absent atolls remain unmodeled.",
                "Residents are sampled with replacement; dates are uniform within the reporting month. Destinations, purpose and appointment rules are supplied scenario assumptions. Ferry boardings do not establish healthcare demand, origin-destination flows, or distinct travelers.",
            ])
        else:
            manifest["assumptions"].extend([
                "Assume 3% of residents have daily travel needs. Each request independently draws healthcare, education, employment or other with equal probability, so realized counts vary. National demand rounds half up; largest remainders allocate the daily total across all Census islands and wards before filtering.",
                "Healthcare requests independently draw hospital, health_centre or clinic with equal probability. Education targets government_school, employment targets workplace and other targets other; the routing layer must select a matching destination. Workplace and other destination catalogs are not currently sourced. Each day samples distinct residents without replacement within islands. Residents can travel on multiple days. One request represents a person's daily activity and return deadline, not two ferry boardings.",
            ])
        manifest["assumptions"].append("Journey scenario: " + json.dumps(scenario, sort_keys=True))
    cache_root = root / "data/cache"
    stage = cache_root / (population_id + "-staging")
    if stage.exists():
        print(f"Reusing validated staging: {stage}", flush=True)
        if not args.stage_only:
            from .export import export_run
            output = root / "data/generated" / population_id
            if output.exists():
                print(f"Existing immutable population: {output}", flush=True)
            else:
                print(f"Parquet and DuckDB output: {export_run(stage, output)}", flush=True)
        return stage if args.stage_only else output
    print(f"Generating {sum(profiles['people_by_island'].values()):,} people across {len(profiles['islands'])} Census areas...", flush=True)
    temporary = Path(tempfile.mkdtemp(prefix=".population-staging-", dir=cache_root))
    try:
        working = temporary / "run"
        report, preview = write_staging(working, profiles, donors, args.seed, manifest, root / "schemas", names, scenario, journey_counts)
        if scenario:
            if args.ferry_data:
                report["ferry_demand"] = {"month": scenario["month"], "source_area_boardings": ferry_totals, "allocated_island_requests": {code: count for code, count in journey_counts.items() if code in profiles["islands"]}, "data_classification": "demo"}
                source_hashes = dict(source_hashes, mtcc_sample_ferry=sha256(args.ferry_data))
            else:
                report["daily_travel_demand"] = {"month": scenario["month"], "daily_population_rate": 0.03, "purpose_probabilities": {purpose: 1 / len(PURPOSES) for purpose in PURPOSES}, "healthcare_facility_type_probabilities": {facility_type: 1 / 3 for facility_type in ("hospital", "health_centre", "clinic")}, "national_daily_people": sum(journey_counts.values()), "selected_daily_people": sum(count for code, count in journey_counts.items() if code in profiles["islands"]), "daily_people_by_island": {code: count for code, count in journey_counts.items() if code in profiles["islands"]}, "data_classification": "assumed"}
            source_hashes = dict(source_hashes, journey_scenario=sha256(args.journey_scenario))
        report.update({"population_id": population_id, "source_sha256": source_hashes, "source_counts": profiles["source_counts"], "donors": dict(donors.report), "usual_residence_label_differences": profiles["usual_residence_label_differences"], "geography_matched_areas": sum(row['geography_id'] is not None for row in profiles['islands'].values())})
        dump_json(working / "manifest.json", manifest)
        dump_json(working / "generation_report.json", report)
        dump_json(working / "preview.json", preview)
        working.rename(stage)
    finally:
        shutil.rmtree(temporary)
    print(f"Validated staging: {stage}", flush=True)
    if not args.stage_only:
        from .export import export_run
        output = export_run(stage, root / "data/generated" / population_id)
        print(f"Parquet and DuckDB output: {output}", flush=True)
        return output
    return stage


if __name__ == "__main__":
    main()
