"""Offline validation of the checked-in contract schemas and record relationships.

This intentionally supports only the JSON Schema keywords used by this project,
and rejects unsupported keywords. It is not a general JSON Schema implementation.
Use a Draft 2020-12 validator for arbitrary schemas.
"""

import argparse
from collections import Counter
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import re


class ContractError(ValueError):
    """An invalid handoff record or relationship."""


def load_json(path):
    def reject_constant(value):
        raise ValueError(f"Non-finite numbers are not valid JSON: {value}")

    return json.loads(
        Path(path).read_text(encoding="utf-8"),
        parse_float=Decimal,
        parse_constant=reject_constant,
    )


def _same(left, right):
    # In JSON Schema, true is not the number 1.
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    return left == right


class SchemaChecker:
    """Validate the project's schema subset without downloads or dependencies."""

    KEYWORDS = {
        "$schema", "$ref", "title", "description", "type", "additionalProperties",
        "required", "properties", "enum", "const", "minLength", "minimum",
        "maximum", "multipleOf", "pattern", "format", "items", "minItems",
        "allOf", "if", "then",
    }

    def __init__(self, schema_directory):
        self.directory = Path(schema_directory)
        self.schemas = {
            path.name: load_json(path)
            for path in self.directory.glob("*.schema.json")
        }
        if "population.schema.json" not in self.schemas:
            raise ValueError(f"No population schema found in {self.directory}")
        for schema in self.schemas.values():
            self._check_definition(schema)

    def _check_definition(self, schema):
        unsupported = set(schema) - self.KEYWORDS
        if unsupported:
            raise ValueError(f"Unsupported schema keywords: {sorted(unsupported)}")
        if "$ref" in schema and schema["$ref"] not in self.schemas:
            raise ValueError(f"Unknown local schema reference: {schema['$ref']}")
        if "format" in schema and schema["format"] != "date":
            raise ValueError(f"Unsupported schema format: {schema['format']}")
        for child in schema.get("properties", {}).values():
            self._check_definition(child)
        for key in ("items", "if", "then"):
            if key in schema:
                self._check_definition(schema[key])
        for child in schema.get("allOf", []):
            self._check_definition(child)

    def check(self, value, schema=None, path="$"):
        if schema is None:
            schema = self.schemas["population.schema.json"]

        def fail(message):
            raise ContractError(f"{path}: {message}")

        if "$ref" in schema:
            self.check(value, self.schemas[schema["$ref"]], path)
        if "type" in schema:
            types = schema["type"]
            types = [types] if isinstance(types, str) else types
            numeric = isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)
            valid = {
                "null": value is None,
                "boolean": isinstance(value, bool),
                "string": isinstance(value, str),
                "object": isinstance(value, dict),
                "array": isinstance(value, list),
                "number": numeric,
                "integer": numeric and value % 1 == 0,
            }
            if not any(valid[t] for t in types):
                fail(f"expected {' or '.join(types)}")
        if "const" in schema and not _same(value, schema["const"]):
            fail(f"expected constant {schema['const']!r}")
        if "enum" in schema and not any(_same(value, item) for item in schema["enum"]):
            fail(f"expected one of {schema['enum']}")
        if isinstance(value, dict):
            missing = set(schema.get("required", [])) - set(value)
            if missing:
                fail(f"missing required fields: {sorted(missing)}")
            properties = schema.get("properties", {})
            if schema.get("additionalProperties") is False:
                extra = set(value) - set(properties)
                if extra:
                    fail(f"unexpected fields: {sorted(extra)}")
            for key, child in properties.items():
                if key in value:
                    self.check(value[key], child, f"{path}.{key}")
        if isinstance(value, list):
            if len(value) < schema.get("minItems", 0):
                fail("too few items")
            if "items" in schema:
                for index, item in enumerate(value):
                    self.check(item, schema["items"], f"{path}[{index}]")
        if isinstance(value, str):
            if len(value) < schema.get("minLength", 0):
                fail("string is too short")
            if "pattern" in schema and re.search(schema["pattern"], value) is None:
                fail("invalid string format")
            if schema.get("format") == "date":
                try:
                    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                        raise ValueError()
                    date.fromisoformat(value)
                except ValueError:
                    fail("expected a valid YYYY-MM-DD date")
        if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                fail(f"must be at least {schema['minimum']}")
            if "maximum" in schema and value > schema["maximum"]:
                fail(f"must be at most {schema['maximum']}")
            if "multipleOf" in schema:
                if Decimal(str(value)) % Decimal(str(schema["multipleOf"])) != 0:
                    fail(f"must be a multiple of {schema['multipleOf']}")
        for child in schema.get("allOf", []):
            self.check(value, child, path)
        if "if" in schema:
            try:
                self.check(value, schema["if"], path)
            except ContractError:
                pass
            else:
                if "then" in schema:
                    self.check(value, schema["then"], path)


def age_group_for(age):
    if age is None:
        return "unknown"
    return "0_17" if age < 18 else "18_64" if age < 65 else "65_plus"


def _index(records, field, table):
    result = {}
    for record in records:
        key = record[field]
        if key in result:
            raise ContractError(f"{table}: duplicate {field} {key!r}")
        result[key] = record
    return result


def validate_bundle(bundle, schema_directory="schemas"):
    """Raise ContractError for invalid records, totals or same-day request times."""
    SchemaChecker(schema_directory).check(bundle)
    islands = _index(bundle["islands"], "island_id", "islands")
    households = _index(bundle["households"], "household_id", "households")
    people = _index(bundle["persons"], "person_id", "persons")
    groups = _index(bundle["population_groups"], "group_id", "population_groups")
    requests = _index(bundle["journey_requests"], "journey_request_id", "journey_requests")
    _index(bundle["metadata"]["sources"], "source_id", "sources")
    household_members = Counter()
    group_members = Counter()

    def require(condition, message):
        if not condition:
            raise ContractError(message)

    for table in (households, people, groups):
        for record in table.values():
            require(record["home_island_id"] in islands, "Unknown home_island_id")
    for person in people.values():
        require(person["household_id"] in households, "Unknown household_id")
        require(person["group_id"] in groups, "Unknown group_id")
        household = households[person["household_id"]]
        group = groups[person["group_id"]]
        require(person["home_island_id"] == household["home_island_id"], "Person/household island mismatch")
        require(person["home_island_id"] == group["home_island_id"], "Person/group island mismatch")
        require(person["age_group"] == age_group_for(person["age"]), "Person age/age_group mismatch")
        require(person["age_group"] == group["age_group"], "Person/group age_group mismatch")
        household_members[person["household_id"]] += 1
        group_members[person["group_id"]] += person["population_weight"]
    for key, household in households.items():
        require(household_members[key] == household["household_size"], f"Household size mismatch: {key}")
    for key, group in groups.items():
        require(group_members[key] == group["population_weight"], f"Group weight mismatch: {key}")
    for request in requests.values():
        require(request["person_id"] in people, "Unknown request person_id")
        require(request["origin_island_id"] == people[request["person_id"]]["home_island_id"], "Request origin/person island mismatch")
        require((request["destination_facility_id"] is None) != (request["destination_facility_type"] is None), "Journey request needs exactly one facility ID or facility type")
        expected_types = {
            "healthcare": {"hospital", "health_centre", "clinic"},
            "education": {"government_school"},
            "employment": {"workplace"},
            "other": {"other"},
        }
        if request["destination_facility_type"] is not None:
            require(request["destination_facility_type"] in expected_types[request["purpose"]], "Destination facility type does not match journey purpose")
        start = sum(int(part) * scale for part, scale in zip(request["appointment_time"].split(":"), (60, 1)))
        deadline = sum(int(part) * scale for part, scale in zip(request["return_home_by"].split(":"), (60, 1)))
        require(start + request["activity_duration_minutes"] <= deadline, "Activity exceeds same-day return deadline")
    if bundle["metadata"]["data_classification"] != "demo":
        all_records = [*islands.values(), *households.values(), *people.values(), *groups.values(), *requests.values(), *bundle["metadata"]["sources"]]
        require(not any(record["data_classification"] == "demo" for record in all_records), "Demo inputs require demo population classification")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--schemas", type=Path, default=Path("schemas"))
    args = parser.parse_args()
    try:
        bundle = load_json(args.file)
        validate_bundle(bundle, args.schemas)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Invalid handoff: {error}\n")
    print(f"Valid: {len(bundle['households'])} households, {len(bundle['persons'])} people, "
          f"{len(bundle['population_groups'])} groups, {len(bundle['journey_requests'])} requests")


if __name__ == "__main__":
    main()
