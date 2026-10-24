import copy
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from population.names import DEFAULT_CATALOG, NameGenerator
from population.validate import ContractError, SchemaChecker, age_group_for, load_json, validate_bundle


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"


class NameTests(unittest.TestCase):
    def test_seeded_names_match_fixture_and_catalog_fingerprint(self):
        bundle = load_json(ROOT / "examples/population.example.json")
        generator = NameGenerator(bundle["metadata"]["seed"])
        self.assertEqual(generator.catalog_version, bundle["metadata"]["name_catalog_version"])
        self.assertEqual(generator.catalog_sha256, bundle["metadata"]["name_catalog_sha256"])
        for person in bundle["persons"]:
            self.assertEqual(generator.display_name(person["person_id"]), person["display_name"])

    def test_names_are_stable_under_reordering_and_filtering(self):
        ids = [f"person-{index}" for index in range(20)]
        full = {key: NameGenerator(42).display_name(key) for key in ids}
        subset_generator = NameGenerator(42)
        subset = {key: subset_generator.display_name(key) for key in reversed(ids[::3])}
        self.assertEqual(subset, {key: full[key] for key in ids[::3]})

    def test_seed_changes_assignment(self):
        ids = [f"person-{index}" for index in range(20)]
        self.assertNotEqual(
            [NameGenerator(42).display_name(key) for key in ids],
            [NameGenerator(43).display_name(key) for key in ids],
        )

    def test_duplicate_names_are_allowed_and_catalog_is_editable(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog = Path(folder) / "names.json"
            catalog.write_text(json.dumps({"version": "test-v1", "given_names": ["Aminath"], "second_components": ["Noor"]}))
            generator = NameGenerator(42, catalog)
            self.assertEqual(generator.display_name("a"), "Aminath Noor")
            self.assertEqual(generator.display_name("b"), "Aminath Noor")

    def test_invalid_inputs_are_rejected(self):
        for seed in (None, True, "42", 1.5):
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                NameGenerator(seed)
        generator = NameGenerator()
        for person_id in (None, "", " ", 1):
            with self.subTest(person_id=person_id), self.assertRaises(ValueError):
                generator.display_name(person_id)

    def test_invalid_catalogs_are_rejected(self):
        base = json.loads(DEFAULT_CATALOG.read_text())
        for key, value in (("version", ""), ("given_names", []), ("second_components", [" "]), ("given_names", "Aminath")):
            with self.subTest(key=key, value=value), tempfile.TemporaryDirectory() as folder:
                data = dict(base, **{key: value})
                path = Path(folder) / "names.json"
                path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    NameGenerator(catalog_path=path)


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.bundle = load_json(ROOT / "examples/population.example.json")

    def validate(self, bundle=None):
        validate_bundle(self.bundle if bundle is None else bundle, SCHEMAS)

    def test_complete_fixture_and_request_denominator(self):
        self.validate()
        self.assertEqual(sum(group["population_weight"] for group in self.bundle["population_groups"]), 4)
        self.assertEqual(len(self.bundle["journey_requests"]), 2)
        self.assertEqual(len({r["person_id"] for r in self.bundle["journey_requests"]}), 2)

    def test_schema_rejects_wrong_types_missing_and_unknown_fields(self):
        cases = [
            ("persons", "age", "68"),
            ("persons", "age", -1),
            ("persons", "population_weight", True),
            ("persons", "name_is_synthetic", False),
            ("persons", "age_group", "adult"),
            ("population_groups", "population_weight", 0),
            ("households", "monthly_expenditure_mvr", -1),
            ("households", "monthly_income_mvr", Decimal("12.345")),
            ("journey_requests", "transport_mode", "ferry"),
            ("journey_requests", "timezone", "UTC"),
        ]
        for table, field, value in cases:
            with self.subTest(table=table, field=field):
                bundle = copy.deepcopy(self.bundle)
                bundle[table][0][field] = value
                with self.assertRaises(ContractError):
                    self.validate(bundle)
        del self.bundle["persons"][0]["display_name"]
        with self.assertRaises(ContractError):
            self.validate()

    def test_missing_economics_and_decimal_money(self):
        household = self.bundle["households"][0]
        household.update(economic_assignment="unavailable", monthly_income_mvr=None, monthly_expenditure_mvr=None)
        self.validate()
        household["monthly_income_mvr"] = 0
        with self.assertRaises(ContractError):
            self.validate()
        household.update(economic_assignment="demo", monthly_income_mvr=Decimal("-12.34"), monthly_expenditure_mvr=Decimal("12.34"))
        self.validate()

    def test_nonfinite_values_are_not_accepted_as_json(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "invalid.json"
            for value in ("NaN", "Infinity", "-Infinity"):
                with self.subTest(value=value):
                    path.write_text('{"value": ' + value + '}')
                    with self.assertRaisesRegex(ValueError, "Non-finite"):
                        load_json(path)

    def test_unknown_age_and_boundary_groups(self):
        self.assertEqual([age_group_for(age) for age in (None, 0, 17, 18, 64, 65)],
                         ["unknown", "0_17", "0_17", "18_64", "18_64", "65_plus"])
        person = self.bundle["persons"][2]
        person.update(age=None, age_group="unknown")
        self.bundle["population_groups"][0]["age_group"] = "unknown"
        self.validate()
        person["age"] = 18
        with self.assertRaisesRegex(ContractError, "age/age_group"):
            self.validate()

    def test_duplicate_ids(self):
        for table in ("persons", "households", "islands", "population_groups", "journey_requests"):
            with self.subTest(table=table):
                bundle = copy.deepcopy(self.bundle)
                bundle[table].append(copy.deepcopy(bundle[table][0]))
                with self.assertRaisesRegex(ContractError, "duplicate"):
                    self.validate(bundle)

    def test_broken_references(self):
        cases = [("persons", "household_id"), ("persons", "group_id"), ("households", "home_island_id"), ("journey_requests", "person_id")]
        for table, field in cases:
            with self.subTest(table=table, field=field):
                bundle = copy.deepcopy(self.bundle)
                bundle[table][0][field] = "missing"
                with self.assertRaisesRegex(ContractError, "Unknown"):
                    self.validate(bundle)

    def test_inconsistent_household_and_group_weights(self):
        for table, field in (("households", "household_size"), ("population_groups", "population_weight")):
            with self.subTest(table=table):
                bundle = copy.deepcopy(self.bundle)
                bundle[table][0][field] += 1
                with self.assertRaisesRegex(ContractError, "mismatch"):
                    self.validate(bundle)

    def test_mismatched_islands(self):
        for table, field in (("persons", "home_island_id"), ("journey_requests", "origin_island_id")):
            with self.subTest(table=table):
                bundle = copy.deepcopy(self.bundle)
                island = dict(bundle["islands"][0], island_id="demo-island-b")
                bundle["islands"].append(island)
                bundle[table][0][field] = island["island_id"]
                with self.assertRaisesRegex(ContractError, "island mismatch"):
                    self.validate(bundle)

    def test_invalid_dates_times_and_activity_windows(self):
        for field, value in (("date", "2026-02-30"), ("date", "20261024"), ("appointment_time", "24:00"), ("return_home_by", "08:00"), ("activity_duration_minutes", 601)):
            with self.subTest(field=field, value=value):
                bundle = copy.deepcopy(self.bundle)
                bundle["journey_requests"][0][field] = value
                with self.assertRaises(ContractError):
                    self.validate(bundle)

    def test_no_requests_and_empty_population_are_valid(self):
        self.bundle["journey_requests"] = []
        self.validate()
        for key in ("persons", "households", "population_groups", "islands"):
            self.bundle[key] = []
        self.validate()

    def test_demo_inputs_cannot_be_claimed_as_derived_population(self):
        self.bundle["metadata"]["data_classification"] = "derived"
        with self.assertRaisesRegex(ContractError, "Demo inputs"):
            self.validate()

    def test_offline_checker_rejects_unsupported_schema_keywords(self):
        with tempfile.TemporaryDirectory() as folder:
            schema = Path(folder) / "population.schema.json"
            schema.write_text(json.dumps({"type": "object", "oneOf": []}))
            with self.assertRaisesRegex(ValueError, "Unsupported schema keywords"):
                SchemaChecker(folder)

    @unittest.skipUnless(importlib.util.find_spec("jsonschema"), "Optional independent JSON Schema validator is not installed")
    def test_independent_draft_2020_12_validation(self):
        from jsonschema import Draft202012Validator, FormatChecker
        from referencing import Registry, Resource

        base = "https://mandarin.example/schemas/"
        schemas = {path.name: load_json(path) for path in SCHEMAS.glob("*.schema.json")}
        for schema in schemas.values():
            Draft202012Validator.check_schema(schema)
        registry = Registry().with_resources((base + name, Resource.from_contents(schema)) for name, schema in schemas.items())
        root = dict(schemas["population.schema.json"], **{"$id": base + "population.schema.json"})
        Draft202012Validator(root, registry=registry, format_checker=FormatChecker()).validate(self.bundle)


if __name__ == "__main__":
    unittest.main()
