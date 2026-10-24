from collections import Counter
import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from xml.sax.saxutils import escape
import zipfile

from population.generate import EconomicDonors, census_profiles, coordinate, make_manifest, read_csv, write_staging
from population.names import NameGenerator
from population.xlsx import rows


ROOT = Path(__file__).resolve().parents[1]


def xlsx(path, data, shared=False):
    """Tiny real XLSX fixture, with a nonmatching sheetId and relationship ID."""
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    strings = []
    xml_rows = []
    for index, values in enumerate(data, 1):
        cells = []
        for column, value in enumerate(values):
            if value is None:
                continue
            letter = chr(65 + column)
            if shared:
                strings.append(str(value))
                body = f'<c r="{letter}{index}" t="s"><v>{len(strings) - 1}</v></c>'
            else:
                body = f'<c r="{letter}{index}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
            cells.append(body)
        xml_rows.append(f'<row r="{index}">' + "".join(cells) + '</row>')
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="island_code" sheetId="7" r:id="rId8"/></sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId8" Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{ns}"><sheetData>' + "".join(xml_rows) + '</sheetData></worksheet>')
        if shared:
            archive.writestr("xl/sharedStrings.xml", f'<sst xmlns="{ns}">' + "".join('<si><t>' + escape(s) + '</t></si>' for s in strings) + '</sst>')


def csv_file(path, records):
    with path.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    return path


def source_fixture(folder):
    dictionary = folder / "dictionary.xlsx"
    xlsx(dictionary, [["island_code", "value label"], [69, "K.Maafushi"], [745, "K.Thulusdhoo"]])
    household = lambda key, code, size, kind="House/flat/apartment", island_type="Administrative Island": {
        "unit__id": key, "fcode": f"LD{code:04d}", "atoll_code": "K", "island_code": str(code),
        "latitude": '4° 0\' 0" N', "longitude": '73° 0\' 0" E', "island_type": island_type,
        "unit_type": kind, "no_of_ppl": size,
    }
    household_rows = [household("source-a", 69, 2), household("source-b", 69, 2),
                      household("source-c", 745, 1, "Labour/staff quarters"), household("source-excluded", 999, 1, island_type="Non-Administrative Island")]
    person_rows = []
    for key, code, ages in [("source-a", 69, [17, 18]), ("source-b", 69, [66, 36]), ("source-c", 745, [-99]), ("source-excluded", 999, [45])]:
        for index, age in enumerate(ages, 1):
            person_rows.append({"unit__id": key, "ind__id": index, "fcode": f"LD{code:04d}", "island_type": "Administrative Island" if code != 999 else "Non-Administrative Island", "island_code": str(code), "usual_residence": str(code), "age": age})
    income = [
        {"uqhh__id": "donor-a", "totalIncome": "10000", "wgt": "2", "hhsize": "2", "maleatoll": "Atoll"},
        {"uqhh__id": "donor-b", "totalIncome": "20000", "wgt": "1", "hhsize": "2", "maleatoll": "Atoll"},
        {"uqhh__id": "donor-no-expense", "totalIncome": "50000", "wgt": "100", "hhsize": "2", "maleatoll": "Atoll"},
    ]
    expenditure = [{"uqhh__id": "donor-a", "annexp": "60000"}, {"uqhh__id": "donor-a", "annexp": "24000"}, {"uqhh__id": "donor-b", "annexp": "180000"}]
    return {
        "census_dictionary": dictionary,
        "census_households": csv_file(folder / "households.csv", household_rows),
        "census_persons": csv_file(folder / "persons.csv", person_rows),
        "hies_income": csv_file(folder / "income.csv", income),
        "hies_expenditure": csv_file(folder / "expenditure.csv", expenditure),
    }


class SpreadsheetTests(unittest.TestCase):
    def test_variable_headers_blanks_shared_and_inline_strings(self):
        with tempfile.TemporaryDirectory() as folder:
            for shared in (False, True):
                with self.subTest(shared=shared):
                    path = Path(folder) / "source.xlsx"
                    xlsx(path, [["Human title", "Another title", "ignore"], [], ["unit__id", "age", "unused"], ["abc", 17, "private"], ["def", None, "private"]], shared)
                    result = list(rows(path, ["unit__id", "age"], header_key="unit__id"))
                    self.assertEqual(result, [{"unit__id": "abc", "age": "17"}, {"unit__id": "def", "age": ""}])

    def test_missing_required_column_and_sheet_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.xlsx"
            xlsx(path, [["unit__id"], ["abc"]])
            with self.assertRaisesRegex(ValueError, "missing columns"):
                list(rows(path, ["unit__id", "age"], header_key="unit__id"))
            with self.assertRaisesRegex(ValueError, "Worksheet"):
                list(rows(path, sheet="missing"))

    def test_coordinates(self):
        self.assertEqual(coordinate('73° 30\' 0" E'), 73.5)
        self.assertEqual(coordinate('0° 30\' 0" S'), -0.5)
        self.assertEqual(coordinate("73.5"), 73.5)
        self.assertIsNone(coordinate(""))
        with self.assertRaises(ValueError):
            coordinate('73° 60\' 0" E')


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.paths = source_fixture(self.folder)
        self.profiles = census_profiles(self.paths)
        self.donors = EconomicDonors(self.paths)

    def generate(self, destination, profiles=None):
        names = NameGenerator(42)
        manifest = make_manifest("test-population", 42, names)
        return write_staging(destination, profiles or self.profiles, self.donors, 42, manifest, ROOT / "schemas", names)

    def test_source_scope_and_template_totals(self):
        self.assertEqual(self.profiles["source_counts"]["all_persons"], 6)
        self.assertEqual(sum(self.profiles["people_by_island"].values()), 5)
        self.assertEqual(self.profiles["selected_households"], 3)
        self.assertEqual(set(self.profiles["islands"]), {"69", "745"})

    def test_economics_are_paired_annualized_and_weighted(self):
        pairs = Counter()
        for index in range(3000):
            income, expense, size, support = self.donors.choose("atolls", 2, 42, f"hh-{index}")
            pairs[(income, expense)] += 1
            self.assertEqual((size, support), (2, 2))
        self.assertEqual(set(pairs), {(10000, 7000), (20000, 15000)})
        self.assertGreater(pairs[(10000, 7000)], pairs[(20000, 15000)] * 1.7)
        self.assertLess(pairs[(10000, 7000)], pairs[(20000, 15000)] * 2.3)
        self.assertEqual(self.donors.report["excluded_missing_expenditure"], 1)
        self.assertIsNone(self.donors.choose("male", 2, 42, "a"))
        self.assertEqual(self.donors.choose("atolls", 3, 42, "a")[2], 2)

    def test_generation_preserves_marginals_without_source_identifiers(self):
        destination = self.folder / "run"
        report, preview = self.generate(destination)
        self.assertEqual(report["counts"]["persons"], 5)
        self.assertEqual(report["counts"]["households"], 3)
        self.assertEqual(report["counts"]["journey_requests"], 0)
        self.assertEqual(report["economics"]["unavailable_households"], 1)
        people = list(read_csv(destination / "persons.csv"))
        self.assertEqual(Counter(person["age"] for person in people), Counter(["17", "18", "36", "66", "\\N"]))
        self.assertTrue(all(person["display_name"] for person in people))
        for path in destination.glob("*.csv"):
            text = path.read_text()
            self.assertNotIn("source-a", text)
            self.assertNotIn("donor-a", text)
        self.assertEqual(len(preview["persons"]), 5)

    def test_nationwide_and_filtered_outputs_have_identical_people(self):
        self.generate(self.folder / "full")
        subset = census_profiles(self.paths, {"69"})
        self.generate(self.folder / "subset", subset)
        full_people = [row for row in read_csv(self.folder / "full/persons.csv") if row["home_island_id"] == "69"]
        self.assertEqual(full_people, list(read_csv(self.folder / "subset/persons.csv")))
        full_households = [row for row in read_csv(self.folder / "full/households.csv") if row["home_island_id"] == "69"]
        self.assertEqual(full_households, list(read_csv(self.folder / "subset/households.csv")))

    def test_repeated_generation_matches_logical_rows(self):
        self.generate(self.folder / "first")
        self.generate(self.folder / "second")
        for path in (self.folder / "first").glob("*.csv"):
            self.assertEqual(path.read_bytes(), (self.folder / "second" / path.name).read_bytes())

    def test_bad_source_household_count_fails(self):
        records = list(read_csv(self.paths["census_households"]))
        records[0]["no_of_ppl"] = "3"
        csv_file(self.paths["census_households"], records)
        with self.assertRaisesRegex(ValueError, "member count"):
            census_profiles(self.paths)

    def test_unknown_island_filter_fails(self):
        with self.assertRaisesRegex(ValueError, "Unknown or excluded"):
            census_profiles(self.paths, {"999"})

    def test_geography_mapping_is_explicit_and_does_not_use_population(self):
        path = self.folder / "islands.json"
        path.write_text(json.dumps({"islands": [{"id": "geo-69", "fcode": "LD0069", "island_code": "69", "population_total": 999999}]}))
        profiles = census_profiles(self.paths, geography=path)
        self.assertEqual(profiles["islands"]["69"]["geography_id"], "geo-69")
        self.assertEqual(profiles["people_by_island"]["69"], 4)
        path.write_text(json.dumps({"islands": [{"id": "a", "fcode": "LD0069"}, {"id": "b", "fcode": "LD0069"}]}))
        self.assertIsNone(census_profiles(self.paths, geography=path)["islands"]["69"]["geography_id"])

    @unittest.skipUnless(importlib.util.find_spec("duckdb"), "DuckDB is not installed")
    def test_duckdb_parquet_roundtrip_and_immutable_output(self):
        from population.export import export_run
        from population.generate import dump_json
        import duckdb

        stage = self.folder / "run"
        report, preview = self.generate(stage)
        report["population_id"] = "test-population"
        dump_json(stage / "generation_report.json", report)
        dump_json(stage / "manifest.json", make_manifest("test-population", 42, NameGenerator(42)))
        dump_json(stage / "preview.json", preview)
        output = export_run(stage, self.folder / "output")
        connection = duckdb.connect()
        self.addCleanup(connection.close)
        self.assertEqual(connection.execute("SELECT count(*) FROM read_parquet(?)", [str(output / "persons.parquet")]).fetchone()[0], 5)
        self.assertEqual(connection.execute("SELECT count(*) FROM read_parquet(?)", [str(output / "journey_requests.parquet")]).fetchone()[0], 0)
        types = {row[0]: row[1] for row in connection.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(output / "households.parquet")]).fetchall()}
        self.assertEqual(types["monthly_income_mvr"], "DECIMAL(18,2)")
        with self.assertRaisesRegex(ValueError, "already exists"):
            export_run(stage, output)


if __name__ == "__main__":
    unittest.main()
